"""Nabundel-nazorg (akkoord Peter 02-09, gebouwd 03-09): UBL+PDF-paren die vóór de bundeling gescheiden
verwerkt zijn (PDF al toegewezen + geëxtraheerd, UBL nog in de verzamelbak mét zusje-signaal) alsnog
samenvoegen: UBL = data, PDF = beeld, deterministische her-extractie, UBL-rij → samengevoegd.

Getest: motorgedrag per status (samenvoegen vs overslaan mét reden), bescherming van een opgeslagen
boekvoorstel, match-twijfel, dry-run schrijft niets, idempotentie (tweede run = 0), het toewijzings-
geheugen leert niets, en de ongedaan-route op een nagebundeld paar (ook via de bestaande
verzamelbak-route en de HTTP-route)."""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import boekvoorstel as boekvoorstel_service
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentGebeurtenis
from app.intake import nabundelen, verzamelbak
from app.intake.models import IntakeBericht, ToewijzingRegel
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_pdf, bouw_ubl

client = TestClient(app)

UBL_NAAM = "RLZ-2080141234.xml"
PDF_NAAM = "RLZ-2080141234.pdf"


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _gescheiden_paar(
    actor: uuid.UUID,
    administratie_id: uuid.UUID,
    *,
    ubl_naam: str = UBL_NAAM,
    pdf_naam: str = PDF_NAAM,
    extra_bijlagen: list[dict] | None = None,
    pdf_inhoud: bytes | None = None,
    ubl_inhoud: bytes | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Herschept de cloud-situatie van vóór migratie 0098: één intake-bericht, de PDF via AI toegewezen
    (als document in de administratie, AI-gate uit → extractie overgeslagen → te_controleren), de UBL in
    de verzamelbak; `intake_bericht.detail.bijlagen` legt de uitkomst per bijlage vast — de bron van de
    zusje-detectie. Geeft (bericht_id, ubl_id, pdf_id)."""
    bericht_id = uuid.uuid4()
    with scoped_session(None, actor_id=actor) as session:
        session.add(
            IntakeBericht(
                id=bericht_id,
                message_id=f"<{bericht_id}@test.local>",
                afzender="administratie@universal-steigerbouw.nl",
                onderwerp="RLZ export",
                verwerkt_door=actor,
                detail={"bijlagen": [], "verwerking": "bezig"},
            )
        )
    pdf_bytes = pdf_inhoud if pdf_inhoud is not None else bouw_pdf(1) + pdf_naam.encode()
    pdf_id = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=pdf_naam,
        inhoud=pdf_bytes,
        actor_id=actor,
        intake_bericht_id=bericht_id,
        afzender_hint="administratie@universal-steigerbouw.nl",
        tenaamstelling="Universal Steigerbouw B.V.",
    ).document_id
    ubl_id = documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=ubl_naam,
        inhoud=ubl_inhoud
        if ubl_inhoud is not None
        else bouw_ubl(klant="Universal Steigerbouw B.V.", factuurnummer="2080141234"),
        actor_id=actor,
        reden="tenaamstelling_niet_eenduidig",
        intake_bericht_id=bericht_id,
        afzender_hint="administratie@universal-steigerbouw.nl",
        tenaamstelling="Universal Steigerbouw B.V.",
    )
    bijlagen = [
        {
            "bestandsnaam": pdf_naam,
            "uitkomst": "toegewezen",
            "document_id": str(pdf_id),
            "detail": f"ai → {administratie_id}",
        },
        {
            "bestandsnaam": ubl_naam,
            "uitkomst": "verzamelbak",
            "document_id": str(ubl_id),
            "detail": "tenaamstelling_niet_eenduidig",
        },
        *(extra_bijlagen or []),
    ]
    with scoped_session(None, actor_id=actor) as session:
        bericht = session.get(IntakeBericht, bericht_id)
        assert bericht is not None
        bericht.detail = {"bijlagen": bijlagen}
    return bericht_id, ubl_id, pdf_id


def _document(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT administratie_id, status, bestandsnaam, opslag_pad, sha256_hash, bron_opslag_pad, "
                "bron_bestandsnaam, bron_content_type, samengevoegd_in_id, tenaamstelling "
                "FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()
    return dict(rij._mapping)


def _zet_status(admin_engine: Engine, document_id: uuid.UUID, status: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET status = :s WHERE id = :id"), {"s": status, "id": document_id}
        )


def _audit_acties(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": record_id},
            )
        ]


def _tijdlijn_details(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[dict]:
    with scoped_session(administratie_id) as session:
        return [
            g.detail or {}
            for g in session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip)
            )
        ]


class TestNabundelMotor:
    def test_te_controleren_paar_wordt_samengevoegd_met_herextractie(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        voor = _document(admin_engine, pdf_id)
        assert voor["status"] == "te_controleren" and voor["bron_opslag_pad"] is None
        # Het zusje-signaal van de verzamelbak legt hetzelfde paar (voorwaarde 3: bestaande detectie).
        items = verzamelbak.lijst_verzamelbak()
        assert [i.document_id for i in items] == [ubl_id] and items[0].zusje_document_id == pdf_id
        with scoped_session(None) as session:
            regels_voor = session.scalars(select(ToewijzingRegel)).all()

        telling = nabundelen.nabundel_verzamelbak()
        assert telling.als_dict() == {
            "kandidaten": 1,
            "samengevoegd": 1,
            "gekoppeld_voorstel_behouden": 0,
            "overgeslagen": 0,
            "mislukt": 0,
        }
        assert telling.uitkomsten[0].pdf_document_id == pdf_id

        # PDF-document = HET document: UBL is hoofdbestand/data, PDF het beeld (bundelingsmodel).
        na = _document(admin_engine, pdf_id)
        assert na["administratie_id"] == administratie_id
        assert na["bestandsnaam"] == UBL_NAAM and na["opslag_pad"] == f"{administratie_id}/{pdf_id}.xml"
        assert na["bron_opslag_pad"] == voor["opslag_pad"] and na["bron_bestandsnaam"] == PDF_NAAM
        assert na["bron_content_type"] == "application/pdf"
        assert na["sha256_hash"] != voor["sha256_hash"]
        assert na["status"] == "te_controleren"
        beeld, naam, ct = documenten_service.haal_bijlage_op(administratie_id=administratie_id, document_id=pdf_id)
        assert ct == "application/pdf" and naam == PDF_NAAM and beeld.startswith(b"%PDF")
        data, naam, _ = documenten_service.haal_bijlage_op(
            administratie_id=administratie_id, document_id=pdf_id, vorm="data"
        )
        assert naam == UBL_NAAM and b"2080141234" in data
        assert na["sha256_hash"] == hashlib.sha256(data).hexdigest()
        # Her-extractie uit de UBL: het boekvoorstel is vooringevuld met de UBL-velden.
        voorstel = boekvoorstel_service.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=pdf_id)
        assert voorstel.opgeslagen is False and voorstel.referentie == "2080141234"
        details = _tijdlijn_details(administratie_id, pdf_id)
        assert any(d.get("nagebundeld_met") == str(ubl_id) and d.get("voorstel_behouden") is False for d in details)
        assert any("veldvoorstel" in d for d in details)
        assert "document_nagebundeld" in _audit_acties(admin_engine, pdf_id)

        # UBL-rij: terminaal samengevoegd mét verwijzing, uit de verzamelbak, nooit verwijderd.
        ubl = _document(admin_engine, ubl_id)
        assert ubl["status"] == "samengevoegd" and ubl["samengevoegd_in_id"] == pdf_id
        assert ubl["administratie_id"] is None
        assert verzamelbak.lijst_verzamelbak() == []
        # Het toewijzings-geheugen leerde niets.
        with scoped_session(None) as session:
            assert session.scalars(select(ToewijzingRegel)).all() == regels_voor

        # Idempotent: tweede run vindt niets meer.
        tweede = nabundelen.nabundel_verzamelbak()
        assert tweede.kandidaten == 0 and tweede.samengevoegd == 0

    def test_handmatig_afmaken_wordt_ook_samengevoegd(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        _zet_status(admin_engine, pdf_id, "handmatig_afmaken")
        telling = nabundelen.nabundel_verzamelbak()
        assert telling.samengevoegd == 1
        na = _document(admin_engine, pdf_id)
        assert na["status"] == "te_controleren" and na["bestandsnaam"] == UBL_NAAM
        assert _document(admin_engine, ubl_id)["status"] == "samengevoegd"

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            ("geboekt", "al geboekt"),
            ("ter_accordering", "ter accordering"),
            ("vraag_open", "open vraag"),
            ("afgewezen", "afgewezen"),
            ("klaar_om_te_boeken", "klaar om te boeken"),
        ],
    )
    def test_andere_status_wordt_overgeslagen_met_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        status: str,
        fragment: str,
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        voor = _document(admin_engine, pdf_id)
        _zet_status(admin_engine, pdf_id, status)

        telling = nabundelen.nabundel_verzamelbak()
        assert telling.kandidaten == 1 and telling.overgeslagen == 1 and telling.samengevoegd == 0
        assert fragment in (telling.uitkomsten[0].reden or "")
        assert telling.overgeslagen_per_reden() == {telling.uitkomsten[0].reden: 1}
        # Niets geraakt: PDF-document ongewijzigd, UBL nog in de bak.
        na = _document(admin_engine, pdf_id)
        assert (
            na["bestandsnaam"] == PDF_NAAM and na["opslag_pad"] == voor["opslag_pad"] and na["bron_opslag_pad"] is None
        )
        assert na["status"] == status
        assert _document(admin_engine, ubl_id)["status"] == "niet_toegewezen"
        assert [i.document_id for i in verzamelbak.lijst_verzamelbak()] == [ubl_id]
        assert "document_nagebundeld" not in _audit_acties(admin_engine, pdf_id)

    def test_opgeslagen_boekvoorstel_wordt_nooit_overschreven(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        boekvoorstel_service.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=pdf_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="MENS-9",
            factuurdatum=None,
            totaalbedrag=Decimal("121.00"),
            regels=[],
        )
        tijdlijn_voor = len(_tijdlijn_details(administratie_id, pdf_id))

        telling = nabundelen.nabundel_verzamelbak()
        assert telling.gekoppeld_voorstel_behouden == 1 and telling.samengevoegd == 0
        assert "voorstel" in (telling.uitkomsten[0].reden or "")
        # UBL wél gekoppeld als data/beeld …
        na = _document(admin_engine, pdf_id)
        assert na["bestandsnaam"] == UBL_NAAM and na["bron_bestandsnaam"] == PDF_NAAM
        assert _document(admin_engine, ubl_id)["status"] == "samengevoegd"
        # … maar het mens-voorstel staat er nog exact zo en er is GEEN her-extractie gedraaid.
        voorstel = boekvoorstel_service.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=pdf_id)
        assert voorstel.opgeslagen is True and voorstel.referentie == "MENS-9"
        details = _tijdlijn_details(administratie_id, pdf_id)
        assert len(details) == tijdlijn_voor + 1  # alleen de nabundel-notitie
        assert details[-1].get("voorstel_behouden") is True
        assert not any(d.get("reden") == "extractie gestart" for d in details[tijdlijn_voor:])
        assert na["status"] == "te_controleren"

    def test_twijfel_wordt_overgeslagen_nooit_gegokt(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Twee toegewezen PDF's met dezelfde naamstam in het bericht = meerduidig.
        _, ubl_id, pdf_id = _gescheiden_paar(
            gescoopte_gebruiker,
            administratie_id,
            extra_bijlagen=[
                {
                    "bestandsnaam": PDF_NAAM,
                    "uitkomst": "toegewezen",
                    "document_id": str(uuid.uuid4()),
                    "detail": f"ai → {administratie_id}",
                }
            ],
        )
        # Tweede paar: administratie niet af te leiden uit het detail.
        _, ubl2_id, _ = _gescheiden_paar(
            gescoopte_gebruiker, administratie_id, ubl_naam="RLZ-2.xml", pdf_naam="RLZ-2.pdf"
        )
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            b2 = session.get(Document, ubl2_id)
            assert b2 is not None and b2.intake_bericht_id is not None
            bericht = session.get(IntakeBericht, b2.intake_bericht_id)
            assert bericht is not None
            bijlagen = list(bericht.detail["bijlagen"])
            bijlagen[0] = {**bijlagen[0], "detail": "ai (administratie onbekend)"}
            bericht.detail = {"bijlagen": bijlagen}

        telling = nabundelen.nabundel_verzamelbak()
        assert telling.kandidaten == 2 and telling.overgeslagen == 2 and telling.samengevoegd == 0
        redenen = {u.ubl_document_id: u.reden or "" for u in telling.uitkomsten}
        assert "meerduidig" in redenen[ubl_id]
        assert "niet af te leiden" in redenen[ubl2_id]
        assert _document(admin_engine, pdf_id)["bestandsnaam"] == PDF_NAAM
        assert {i.document_id for i in verzamelbak.lijst_verzamelbak()} == {ubl_id, ubl2_id}

    def test_gewone_bak_rij_zonder_zusje_is_geen_kandidaat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        los = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="los.xml",
            inhoud=bouw_ubl(klant="Onbekend BV", factuurnummer="LOS-1"),
            actor_id=gescoopte_gebruiker,
            reden="tenaamstelling_niet_eenduidig",
        )
        telling = nabundelen.nabundel_verzamelbak(dry_run=True)
        assert telling.kandidaten == 1 and all(u.ubl_document_id != los for u in telling.uitkomsten)

    def test_dry_run_toetst_alles_maar_schrijft_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        _, ubl_geboekt_id, pdf_geboekt_id = _gescheiden_paar(
            gescoopte_gebruiker, administratie_id, ubl_naam="RLZ-3.xml", pdf_naam="RLZ-3.pdf"
        )
        _zet_status(admin_engine, pdf_geboekt_id, "geboekt")
        voor = {d: _document(admin_engine, d) for d in (ubl_id, pdf_id, ubl_geboekt_id, pdf_geboekt_id)}

        telling = nabundelen.nabundel_verzamelbak(dry_run=True)
        assert telling.kandidaten == 2 and telling.samengevoegd == 0 and telling.overgeslagen == 1
        per_ubl = {u.ubl_document_id: u for u in telling.uitkomsten}
        assert per_ubl[ubl_id].uitkomst == nabundelen.UITKOMST_KANDIDAAT
        assert "her-extractie" in (per_ubl[ubl_id].reden or "")
        assert per_ubl[ubl_geboekt_id].uitkomst == nabundelen.UITKOMST_OVERGESLAGEN
        for d, snapshot in voor.items():
            assert _document(admin_engine, d) == snapshot
        assert "document_nagebundeld" not in _audit_acties(admin_engine, pdf_id)

    def test_ongeldige_ubl_is_mislukt_en_raakt_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id, ubl_inhoud=b"<kapot>")
        voor = _document(admin_engine, pdf_id)
        telling = nabundelen.nabundel_verzamelbak()
        assert telling.mislukt == 1 and telling.samengevoegd == 0
        assert "geen geldige UBL" in (telling.uitkomsten[0].reden or "")
        assert _document(admin_engine, pdf_id) == voor
        assert _document(admin_engine, ubl_id)["status"] == "niet_toegewezen"


class TestOngedaan:
    def test_ongedaan_via_bestaande_verzamelbak_route(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        voor = _document(admin_engine, pdf_id)
        assert nabundelen.nabundel_verzamelbak().samengevoegd == 1

        teruggezet = verzamelbak.maak_samenvoegen_ongedaan(document_id=pdf_id, actor_id=gescoopte_gebruiker)
        assert teruggezet == ubl_id
        na = _document(admin_engine, pdf_id)
        assert na["bestandsnaam"] == PDF_NAAM and na["opslag_pad"] == voor["opslag_pad"]
        assert na["sha256_hash"] == voor["sha256_hash"]
        assert na["bron_opslag_pad"] is None and na["bron_bestandsnaam"] is None and na["bron_content_type"] is None
        assert na["status"] == "te_controleren"
        beeld, naam, ct = documenten_service.haal_bijlage_op(administratie_id=administratie_id, document_id=pdf_id)
        assert naam == PDF_NAAM and ct == "application/pdf" and beeld.startswith(b"%PDF")
        ubl = _document(admin_engine, ubl_id)
        assert ubl["status"] == "niet_toegewezen" and ubl["samengevoegd_in_id"] is None
        assert [i.document_id for i in verzamelbak.lijst_verzamelbak()] == [ubl_id]
        assert "document_nabundeling_ongedaan" in _audit_acties(admin_engine, pdf_id)
        details = _tijdlijn_details(administratie_id, pdf_id)
        assert any(d.get("nabundeling_ongedaan") == str(ubl_id) and "Opnieuw extraheren" in d["reden"] for d in details)
        # Het UBL-bestand onder het administratie-prefix is niet verwijderd (nooit verwijderen).
        opslag = documenten_service._standaard_opslag()
        assert b"2080141234" in opslag.lezen(pad=f"{administratie_id}/{pdf_id}.xml")
        # En daarna opnieuw nabundelen kan gewoon weer (zelfde paar).
        assert nabundelen.nabundel_verzamelbak().samengevoegd == 1

    def test_ongedaan_geweigerd_als_document_al_verder_is(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        assert nabundelen.nabundel_verzamelbak().samengevoegd == 1
        _zet_status(admin_engine, pdf_id, "geboekt")
        with pytest.raises(nabundelen.NabundelingOngedaanGeweigerd, match="geboekt"):
            verzamelbak.maak_samenvoegen_ongedaan(document_id=pdf_id, actor_id=gescoopte_gebruiker)
        assert _document(admin_engine, ubl_id)["status"] == "samengevoegd"
        # HTTP-route: leesbare 409, geen 500.
        r = client.post(f"/verzamelbak/{pdf_id}/samenvoegen-ongedaan", headers=_bearer(gescoopte_gebruiker))
        assert r.status_code == 409 and "geboekt" in r.json()["detail"]

    def test_ongedaan_via_http_route(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, ubl_id, pdf_id = _gescheiden_paar(gescoopte_gebruiker, administratie_id)
        assert nabundelen.nabundel_verzamelbak().samengevoegd == 1
        r = client.post(f"/verzamelbak/{pdf_id}/samenvoegen-ongedaan", headers=_bearer(gescoopte_gebruiker))
        assert r.status_code == 200, r.text
        assert r.json()["teruggezet_document_id"] == str(ubl_id)
        assert _document(admin_engine, pdf_id)["bestandsnaam"] == PDF_NAAM

    def test_handmatige_samenvoeging_in_de_bak_blijft_ongewijzigd_werken(self, gescoopte_gebruiker: uuid.UUID) -> None:
        ubl_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="a.xml",
            inhoud=bouw_ubl(klant="X"),
            actor_id=gescoopte_gebruiker,
            reden="tenaamstelling_niet_eenduidig",
        )
        pdf_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="b.pdf",
            inhoud=bouw_pdf(1),
            actor_id=gescoopte_gebruiker,
            reden="tenaamstelling_niet_eenduidig",
        )
        verzamelbak.voeg_samen(leidend_document_id=ubl_id, ander_document_id=pdf_id, actor_id=gescoopte_gebruiker)
        assert verzamelbak.maak_samenvoegen_ongedaan(document_id=ubl_id, actor_id=gescoopte_gebruiker) == pdf_id
        with pytest.raises(verzamelbak.SamenvoegenGeweigerd):
            verzamelbak.maak_samenvoegen_ongedaan(document_id=ubl_id, actor_id=gescoopte_gebruiker)
