"""Duplicaat-auto-afvoer (besluit Peter 04-09, migratie 0105): bij een HARDE match (crediteur op
btw-nummer + referentie + totaalbedrag; origineel geboekt in RLZ/Odoo óf een ouder/verder app-document)
gaat het duplicaat automatisch naar Afgewezen mét kruisverwijzing beide kanten, audit en tijdlijn —
alleen bij de opt-in, systeem-actor, volumerem. De één-klik-variant werkt altijd; heropenen haalt terug.
Zachte signalen (andere crediteur zonder btw-match) voeren nooit af."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import afwijzen, boekvoorstel, duplicaat_afvoer, duplicaatsignaal, service
from app.documenten.models import AfwijzingStatus, CrediteurKenmerk, Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_vragen import _extra_gebruiker, _status

client = TestClient(app)

REF = "F-2026-0042"
TOTAAL = Decimal("121.00")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _upload_met_kop(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    referentie: str = REF,
    totaal: Decimal = TOTAAL,
    naam: str = "factuur.pdf",
) -> uuid.UUID:
    """Upload + kop opslaan: de opslag-hook draait het duplicaatsignaal (RLZ onbereikbaar in de test →
    'onbekend', kop wél gecachet) en daarachter de auto-afvoer."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=b"%PDF-1.4 " + naam.encode() + uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=totaal,
        regels=[],
    )
    return resultaat.document_id


def _afwijzing_rij(admin_engine: Engine, document_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        rij = (
            conn.execute(
                text(
                    "SELECT id, status, reden, automatisch, duplicaat_van_document_id, duplicaat_van_rlz_document_id, "
                    "duplicaat_van_referentie, afgewezen_door FROM boekhouding.afwijzing WHERE document_id = :id "
                    "ORDER BY afgewezen_op DESC LIMIT 1"
                ),
                {"id": document_id},
            )
            .mappings()
            .first()
        )
    return dict(rij) if rij else None


def _audit_acties(admin_engine: Engine, *, tabel: str, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = :tabel AND record_id = :id ORDER BY tijdstip"
                ),
                {"tabel": tabel, "id": record_id},
            )
            .scalars()
            .all()
        )


def _tijdlijn_details(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(d) if d else {}
            for d in conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND naar_status = 'afgewezen' ORDER BY tijdstip"
                ),
                {"id": document_id},
            ).scalars()
        ]


def _zet_btw(admin_engine: Engine, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, btw: str) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                btw_nummer=btw,
                btw_nummer_geverifieerd=True,
                btw_nummer_bron="factuur",
            )
        )


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


@pytest.fixture
def opt_in_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    assert beheer_service.haal_duplicaat_autoafvoer_ingeschakeld_op(administratie_id=administratie_id) is False
    beheer_service.zet_duplicaat_autoafvoer_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


class TestAutomatischPad:
    def test_harde_match_geboekt_origineel_in_rlz_voert_af_met_kruisverwijzing_audit_en_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        assert _status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value  # onbekend → niets
        rlz_id = uuid.uuid4()
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(duplicaten=[{"id": str(rlz_id), "Reference": REF, "InvoiceNumber": "INK-77"}]),
        )
        afgevoerd = duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id)
        assert afgevoerd == [document_id]
        assert _status(admin_engine, document_id) == DocumentStatus.AFGEWEZEN.value

        rij = _afwijzing_rij(admin_engine, document_id)
        assert rij is not None
        assert rij["status"] == AfwijzingStatus.OPEN.value
        assert rij["automatisch"] is True
        assert rij["duplicaat_van_rlz_document_id"] == rlz_id
        assert rij["duplicaat_van_document_id"] is None
        assert rij["duplicaat_van_referentie"] == REF
        assert rij["reden"] == f"Duplicaat van {REF} (boekstuk INK-77)"
        assert rij["afgewezen_door"] == uuid.UUID("00000000-0000-0000-0000-000000000001")  # systeem-actor

        details = _tijdlijn_details(admin_engine, document_id)
        assert len(details) == 1
        assert details[0]["automatisch_afgevoerd"] is True
        assert details[0]["duplicaat_van_rlz_document_id"] == str(rlz_id)
        assert details[0]["reden"].startswith("Duplicaat van")
        assert "duplicaat_afgevoerd" in _audit_acties(admin_engine, tabel="document", record_id=document_id)
        assert "document_afgewezen" in _audit_acties(admin_engine, tabel="afwijzing", record_id=rij["id"])

        stand = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=document_id)
        assert stand.kandidaat is None
        assert stand.afgevoerd_als_duplicaat_van is not None
        assert stand.afgevoerd_als_duplicaat_van.rlz_document_id == rlz_id
        assert stand.afgevoerd_als_duplicaat_van.bron == "geboekt"

    def test_werkvoorraad_origineel_het_oudste_blijft_staan_kruisverwijzing_beide_kanten(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="a.pdf",
        )
        # De tweede upload met dezelfde kop wordt in de opslag-hook (post-commit) direct afgevoerd.
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="b.pdf",
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        rij = _afwijzing_rij(admin_engine, b)
        assert rij is not None and rij["duplicaat_van_document_id"] == a and rij["automatisch"] is True
        assert rij["reden"].startswith(f"Duplicaat van {REF} (document a.pdf")
        assert "in de werkvoorraad" in rij["reden"]

        stand_a = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=a)
        assert stand_a.kandidaat is None and stand_a.afgevoerd_als_duplicaat_van is None
        assert [d.document_id for d in stand_a.afgevoerde_duplicaten] == [b]
        assert stand_a.afgevoerde_duplicaten[0].automatisch is True
        stand_b = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=b)
        assert stand_b.afgevoerd_als_duplicaat_van is not None
        assert stand_b.afgevoerd_als_duplicaat_van.document_id == a
        assert stand_b.afgevoerd_als_duplicaat_van.bestandsnaam == "a.pdf"
        assert stand_b.afgevoerd_als_duplicaat_van.bron == "werkvoorraad"

    def test_zelfde_btw_nummer_bij_andere_vendor_is_dezelfde_crediteur(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        v1, v2 = uuid.uuid4(), uuid.uuid4()
        _zet_btw(admin_engine, administratie_id=administratie_id, vendor_id=v1, btw="NL123456789B01")
        _zet_btw(admin_engine, administratie_id=administratie_id, vendor_id=v2, btw="NL123456789B01")
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=v1
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=v2
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value

    def test_zacht_signaal_andere_crediteur_zonder_btw_match_voert_nooit_af(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        v1, v2 = uuid.uuid4(), uuid.uuid4()
        _zet_btw(admin_engine, administratie_id=administratie_id, vendor_id=v1, btw="NL111111111B01")
        _zet_btw(admin_engine, administratie_id=administratie_id, vendor_id=v2, btw="NL222222222B01")
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=v1
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=v2
        )
        # Zelfde vendor maar ander bedrag: óók geen harde match.
        c = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=v1,
            totaal=Decimal("121.01"),
        )
        for d in (a, b, c):
            assert _status(admin_engine, d) == DocumentStatus.TE_CONTROLEREN.value
        assert _afwijzing_rij(admin_engine, b) is None
        assert (
            duplicaat_afvoer.werkvoorraad_matches_bulk(administratie_id=administratie_id, document_ids=[a, b, c]) == {}
        )

    def test_verder_in_de_flow_wint_als_origineel_en_wordt_zelf_nooit_afgevoerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
    ) -> None:
        """Opt-in pas ná de uploads: A (oudste, te_controleren) en B (jonger, vraag_open). B staat verder in de
        flow en is het origineel; A gaat als duplicaat af, B blijft — een vraag_open-document wordt nooit
        automatisch afgevoerd."""
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, b)
            assert document is not None
            _schrijf_overgang(session, document=document, naar=DocumentStatus.VRAAG_OPEN, actor_id=gescoopte_gebruiker)
        beheer_service.zet_duplicaat_autoafvoer_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        afgevoerd = duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=b)
        assert afgevoerd == [a]
        assert _status(admin_engine, b) == DocumentStatus.VRAAG_OPEN.value
        rij = _afwijzing_rij(admin_engine, a)
        assert rij is not None and rij["duplicaat_van_document_id"] == b

    def test_volumerem_weigert_met_audit_en_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "max_duplicaat_afvoer_per_dag_per_administratie", 1)
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        c = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, c) == DocumentStatus.TE_CONTROLEREN.value  # rem bereikt: blijft staan
        assert "duplicaat_afvoer_geweigerd" in _audit_acties(admin_engine, tabel="document", record_id=c)
        with admin_engine.connect() as conn:
            reden = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'reden' FROM platform.audit_event WHERE tabel = 'document' "
                    "AND record_id = :id AND actie = 'duplicaat_afvoer_geweigerd'"
                ),
                {"id": c},
            ).scalar_one()
        assert "Volumerem" in reden and "1 " in reden
        # Één-klik telt niet mee en werkt óók boven de rem.
        resultaat = duplicaat_afvoer.voer_af_als_duplicaat(
            administratie_id=administratie_id, document_id=c, actor_id=gescoopte_gebruiker
        )
        assert resultaat.al_afgevoerd is False and resultaat.afwijzing.automatisch is False

    def test_zonder_eigenaar_geweigerd_met_reden_nooit_stil(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        assert "duplicaat_afvoer_geweigerd" in _audit_acties(admin_engine, tabel="document", record_id=b)

    def test_heropenen_haalt_terug_en_origineel_toont_geen_afgevoerd_duplicaat_meer(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        opt_in_aan: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        data = afwijzen.heropen(administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker)
        assert data.status == AfwijzingStatus.HEROPEND.value
        assert data.duplicaat_van_document_id == a  # historie blijft in de rij staan
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        stand_a = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=a)
        assert stand_a.afgevoerde_duplicaten == []
        stand_b = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=b)
        assert stand_b.afgevoerd_als_duplicaat_van is None
        assert stand_b.kandidaat is not None and stand_b.kandidaat.document_id == a  # knop weer beschikbaar


class TestEenKlik:
    def test_opt_in_uit_niets_automatisch_maar_een_klik_werkt_en_is_idempotent(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        matches = duplicaat_afvoer.werkvoorraad_matches_bulk(administratie_id=administratie_id, document_ids=[a, b])
        assert set(matches) == {b} and matches[b].document_id == a

        resultaat = duplicaat_afvoer.voer_af_als_duplicaat(
            administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker
        )
        assert resultaat.al_afgevoerd is False
        assert resultaat.afwijzing.automatisch is False
        assert resultaat.afwijzing.afgewezen_door == gescoopte_gebruiker
        assert resultaat.afwijzing.duplicaat_van_document_id == a
        assert resultaat.origineel.document_id == a
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        details = _tijdlijn_details(admin_engine, b)
        assert "automatisch_afgevoerd" not in details[0]
        assert details[0]["duplicaat_van_document_id"] == str(a)

        herhaald = duplicaat_afvoer.voer_af_als_duplicaat(
            administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker
        )
        assert herhaald.al_afgevoerd is True and herhaald.afwijzing.id == resultaat.afwijzing.id

        with pytest.raises(duplicaat_afvoer.GeenHardeMatch):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=a, actor_id=gescoopte_gebruiker
            )

    def test_verkeerde_status_en_gewone_afwijzing_geven_leesbare_weigering(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, b)
            assert document is not None
            _schrijf_overgang(session, document=document, naar=DocumentStatus.VRAAG_OPEN, actor_id=gescoopte_gebruiker)
        with pytest.raises(duplicaat_afvoer.AfvoerNietMogelijk, match="vraag_open"):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker
            )

        c = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=uuid.uuid4(),
            referentie="X-1",
        )
        afwijzen.wijs_af(
            administratie_id=administratie_id, document_id=c, actor_id=gescoopte_gebruiker, reden="Niet onze bestelling"
        )
        with pytest.raises(duplicaat_afvoer.AfvoerNietMogelijk, match="andere reden"):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=c, actor_id=gescoopte_gebruiker
            )
        with pytest.raises(duplicaat_afvoer.GeenHardeMatch):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id,
                document_id=_upload_met_kop(
                    administratie_id=administratie_id,
                    actor_id=gescoopte_gebruiker,
                    opslag=opslag,
                    vendor_id=uuid.uuid4(),
                    referentie="Y-1",
                ),
                actor_id=gescoopte_gebruiker,
            )


class TestRouter:
    def test_afvoeren_als_duplicaat_200_idempotent_409_en_detail_lijst_dragen_kruisverwijzing(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="a.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="b.pdf",
        )

        lijst = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
        assert lijst.status_code == 200
        per_id = {d["id"]: d for d in lijst.json()["documenten"]}
        assert per_id[str(b)]["duplicaat_werkvoorraad_van"]["document_id"] == str(a)
        assert per_id[str(a)]["duplicaat_werkvoorraad_van"] is None

        detail_b = client.get(f"/administraties/{administratie_id}/documenten/{b}", headers=headers)
        assert detail_b.status_code == 200
        assert detail_b.json()["duplicaat_afvoer"]["kandidaat"]["document_id"] == str(a)
        assert detail_b.json()["duplicaat_afvoer"]["kandidaat"]["bestandsnaam"] == "a.pdf"

        resp = client.post(f"/administraties/{administratie_id}/documenten/{b}/afvoeren-als-duplicaat", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["al_afgevoerd"] is False and body["automatisch"] is False
        assert body["document_status"] == "afgewezen" and body["origineel"]["document_id"] == str(a)
        assert body["reden"].startswith(f"Duplicaat van {REF}")

        herhaald = client.post(
            f"/administraties/{administratie_id}/documenten/{b}/afvoeren-als-duplicaat", headers=headers
        )
        assert herhaald.status_code == 200 and herhaald.json()["al_afgevoerd"] is True
        assert herhaald.json()["afwijzing_id"] == body["afwijzing_id"]

        # Het origineel zelf afvoeren = 409 mét leesbare uitleg (b is al afgevoerd, dus voor a is er geen
        # groepslid meer: "geen harde match (meer)").
        fout = client.post(f"/administraties/{administratie_id}/documenten/{a}/afvoeren-als-duplicaat", headers=headers)
        assert fout.status_code == 409 and "duplicaat" in fout.json()["detail"].lower()

        lijst = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
        per_id = {d["id"]: d for d in lijst.json()["documenten"]}
        afwijzing = per_id[str(b)]["afwijzing"]
        assert afwijzing["duplicaat_van_document_id"] == str(a) and afwijzing["automatisch"] is False
        assert afwijzing["duplicaat_van_referentie"] == REF
        detail_a = client.get(f"/administraties/{administratie_id}/documenten/{a}", headers=headers).json()
        assert [d["document_id"] for d in detail_a["duplicaat_afvoer"]["afgevoerde_duplicaten"]] == [str(b)]
        detail_b = client.get(f"/administraties/{administratie_id}/documenten/{b}", headers=headers).json()
        assert detail_b["duplicaat_afvoer"]["afgevoerd_als_duplicaat_van"]["document_id"] == str(a)
        assert detail_b["afwijzing"]["duplicaat_van_document_id"] == str(a)

    def test_onbekend_document_404(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}/afvoeren-als-duplicaat",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 404

    def test_instelling_beheerder_only_met_audit(
        self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        pad = f"/administraties/{administratie_id}/duplicaat-autoafvoer-instelling"
        assert client.get(pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        assert (
            client.put(
                pad, json={"ingeschakeld": True}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
            ).status_code
            == 403
        )
        beheerder = _bearer(beheerder_id, rol="beheerder")
        assert client.get(pad, headers=beheerder).json() == {"ingeschakeld": False}
        assert client.put(pad, json={"ingeschakeld": True}, headers=beheerder).json() == {"ingeschakeld": True}
        assert client.get(pad, headers=beheerder).json() == {"ingeschakeld": True}
        overzicht = client.get("/instellingen/administraties", headers=beheerder)
        assert overzicht.status_code == 200
        rij = next(r for r in overzicht.json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["duplicaat_autoafvoer_ingeschakeld"] is True
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'administratie' AND record_id = :id "
                        "AND actie = 'duplicaat_autoafvoer_ingeschakeld_gewijzigd'"
                    ),
                    {"id": administratie_id},
                )
                .scalars()
                .all()
            )
        assert acties == ["duplicaat_autoafvoer_ingeschakeld_gewijzigd"]
