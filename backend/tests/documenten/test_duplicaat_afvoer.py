"""Duplicaat-auto-afvoer (besluit Peter 04-09, migratie 0105; blok A1/A2 04-09, migratie 0109): bij een
HARDE match (crediteur op btw-nummer + referentie + totaalbedrag; origineel geboekt in RLZ/Odoo óf een
ouder/verder app-document) gaat het duplicaat automatisch naar Afgewezen mét kruisverwijzing beide kanten,
audit en tijdlijn — STANDAARD AAN achter één platformbrede noodrem, systeem-actor, volumerem. Sinds A2 óók
een duplicaat bij de klant-accordeur of met een open vraag (ronde/vraag mét reden gesloten). De één-klik-
variant werkt altijd; heropenen haalt terug. Zachte signalen (andere crediteur zonder btw-match) voeren
nooit af."""

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
from app.accordering import service as accordering_service
from app.documenten import afwijzen, boekvoorstel, duplicaat_afvoer, duplicaatsignaal, service, vragen
from app.documenten.models import AfwijzingStatus, CrediteurKenmerk, Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.accordering.conftest import maak_accordeur, zet_schema
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
def standaard_aan() -> None:
    """Blok A1: de platformbrede noodrem staat standaard AAN — geen opt-in meer nodig."""
    assert beheer_service.haal_duplicaat_autoafvoer_platform_op() is True


@pytest.fixture
def noodrem_uit(beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=False)


def _noodrem_aan(beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=True)


def _rlz_treffer(administratie_id: uuid.UUID, document_id: uuid.UUID) -> uuid.UUID:
    """Berekent het duplicaatsignaal mét een geboekte RLZ-treffer (origineel buiten de app) — de hook
    daarachter draait het automatische afvoerpad."""
    rlz_id = uuid.uuid4()
    duplicaatsignaal.bereken_duplicaatsignaal(
        administratie_id=administratie_id,
        document_id=document_id,
        client=FakeBoekClient(duplicaten=[{"id": str(rlz_id), "Reference": REF, "InvoiceNumber": "INK-77"}]),
    )
    duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id)
    return rlz_id


def _ronde_status(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT status FROM boekhouding.document_accordering WHERE document_id = :id ORDER BY aangeboden_op"
                ),
                {"id": document_id},
            )
            .scalars()
            .all()
        )


def _tijdlijn_alle(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(d) if d else {}
            for d in conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id ORDER BY tijdstip"),
                {"id": document_id},
            ).scalars()
        ]


class TestAutomatischPad:
    def test_harde_match_geboekt_origineel_in_rlz_voert_af_met_kruisverwijzing_audit_en_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        standaard_aan: None,
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
        standaard_aan: None,
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
        standaard_aan: None,
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
        standaard_aan: None,
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

    def test_vraag_open_wint_van_een_ouder_te_controleren_exemplaar(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
        noodrem_uit: None,
    ) -> None:
        """Noodrem UIT tijdens de uploads (anders voert de opslag-hook B direct af): A (oudste, te_controleren)
        en B (jonger, vraag_open). Rangorde: een document met een open vraag staat vóór een kaal
        te_controleren-exemplaar → B is het origineel, A gaat af. (Sinds A2 is vraag_open zelf óók afvoerbaar
        zodra er een hoger origineel is — zie TestAfwikkeling.)"""
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
        _noodrem_aan(beheerder_id)
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
        standaard_aan: None,
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
        standaard_aan: None,
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
        standaard_aan: None,
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


class TestAfwikkeling:
    """Blok A2 04-09 (besluit Peter "geen dubbeling"): een hard duplicaat bij de klant-accordeur of met een open
    vraag wordt óók automatisch afgevoerd — ronde ingetrokken/vervallen en vraag gesloten, beide mét reden,
    tijdlijn + audit; heropenen keert terug naar een herstelbare herkomst."""

    def test_ter_accordering_duplicaat_afgevoerd_ronde_vervalt_met_reden_buiten_de_configuratie_banner(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "Accordeur A")
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
        )
        vendor_id = uuid.uuid4()
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, b)
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        assert _status(admin_engine, b) == DocumentStatus.TER_ACCORDERING.value
        assert _ronde_status(admin_engine, b) == ["open"]

        _noodrem_aan(beheerder_id)
        rlz_id = _rlz_treffer(administratie_id, b)  # origineel al geboekt in RLZ → B is het duplicaat
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        assert _ronde_status(admin_engine, b) == ["vervallen"]
        rij = _afwijzing_rij(admin_engine, b)
        assert rij is not None and rij["automatisch"] is True and rij["duplicaat_van_rlz_document_id"] == rlz_id

        details = _tijdlijn_alle(admin_engine, b)
        vervallen = [d for d in details if d.get("accordering_vervallen_duplicaat")]
        assert len(vervallen) == 1
        assert vervallen[0]["reden"] == f"afgevoerd als duplicaat van {REF}"
        assert vervallen[0]["accordering_vervallen"] is True
        # Geen herstelwerk: de "configuratie gewijzigd — opnieuw aanbieden"-banner telt deze batch niet.
        assert accordering_service.vervallen_meldingen(administratie_id=administratie_id) == []
        assert "accordering_vervallen" in _audit_acties(
            admin_engine, tabel="document_accordering", record_id=uuid.UUID(vervallen[0]["accordering_id"])
        )
        # Heropenen keert terug naar de herkomst ná de afwikkeling (klaar_om_te_boeken), nooit naar ter_accordering.
        afwijzen.heropen(administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker)
        assert _status(admin_engine, b) == DocumentStatus.KLAAR_OM_TE_BOEKEN.value

    def test_vraag_open_duplicaat_afgevoerd_vraag_gesloten_met_slotbericht(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        vendor_id = uuid.uuid4()
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=b,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Is dit de juiste leverancier?",
        )
        assert _status(admin_engine, b) == DocumentStatus.VRAAG_OPEN.value

        _noodrem_aan(beheerder_id)
        _rlz_treffer(administratie_id, b)
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        with admin_engine.connect() as conn:
            status, reden = conn.execute(
                text("SELECT status, ingetrokken_reden FROM boekhouding.vraag WHERE id = :id"), {"id": vraag.id}
            ).one()
            berichten = (
                conn.execute(
                    text("SELECT tekst FROM boekhouding.vraag_bericht WHERE vraag_id = :id ORDER BY geplaatst_op"),
                    {"id": vraag.id},
                )
                .scalars()
                .all()
            )
        assert status == "ingetrokken" and reden == f"afgevoerd als duplicaat van {REF}"
        assert berichten[-1] == f"Vraag gesloten: document afgevoerd als duplicaat van {REF}."
        assert "vraag_gesloten_wegens_duplicaat" in _audit_acties(admin_engine, tabel="vraag", record_id=vraag.id)
        tijdlijn = _tijdlijn_alle(admin_engine, b)
        assert any(d.get("vraag_gesloten_wegens_duplicaat") for d in tijdlijn)
        # Heropenen → de herkomst van vóór de vraag (te_controleren), niet vraag_open.
        afwijzen.heropen(administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker)
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value

    def test_een_klik_op_ter_accordering_en_vraag_open_werkt(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        # A (ouder) krijgt een open vraag en is daarmee het origineel; B (jonger, te_controleren) het duplicaat.
        vragen.stel_vraag(administratie_id=administratie_id, document_id=a, actor_id=gescoopte_gebruiker, vraag_tekst="?")
        stand_b = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=b)
        assert stand_b.kandidaat is not None and stand_b.kandidaat.document_id == a
        # De één-klik op het vraag_open-origineel zelf weigert leesbaar (het ís het origineel).
        with pytest.raises(duplicaat_afvoer.GeenHardeMatch):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=a, actor_id=gescoopte_gebruiker
            )
        # Zet B vooruit naar vraag_open: A blijft (ouder binnen dezelfde rang) het origineel, B is afvoerbaar.
        vragen.stel_vraag(administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker, vraag_tekst="?")
        resultaat = duplicaat_afvoer.voer_af_als_duplicaat(
            administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker
        )
        assert resultaat.al_afgevoerd is False and resultaat.origineel.document_id == a
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, a) == DocumentStatus.VRAAG_OPEN.value


class TestEenKlik:
    def test_noodrem_uit_niets_automatisch_maar_een_klik_werkt_en_is_idempotent(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
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
        noodrem_uit: None,
    ) -> None:
        vendor_id = uuid.uuid4()
        _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        b = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        # Sinds A2 is vraag_open afvoerbaar; boeken_mislukt (er liep al een boekpoging) niet.
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, b)
            assert document is not None
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.BOEKEN_MISLUKT, actor_id=gescoopte_gebruiker
            )
        with pytest.raises(duplicaat_afvoer.AfvoerNietMogelijk, match="boeken_mislukt"):
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
        noodrem_uit: None,
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

    def test_noodrem_beheerder_only_met_audit_default_aan(
        self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        pad = "/instellingen/duplicaat-autoafvoer"
        assert client.get(pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        assert (
            client.put(pad, json={"ingeschakeld": False}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code
            == 403
        )
        beheerder = _bearer(beheerder_id, rol="beheerder")
        assert client.get(pad, headers=beheerder).json() == {"ingeschakeld": True}  # standaard AAN (A1)
        assert client.put(pad, json={"ingeschakeld": False}, headers=beheerder).json() == {"ingeschakeld": False}
        assert client.get(pad, headers=beheerder).json() == {"ingeschakeld": False}
        # De per-administratie-toggle van 0105 is weg: geen route, geen veld in het overzicht.
        overzicht = client.get("/instellingen/administraties", headers=beheerder)
        assert overzicht.status_code == 200
        assert all("duplicaat_autoafvoer_ingeschakeld" not in r for r in overzicht.json()["administraties"])
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'duplicaat_afvoer_instelling' "
                        "AND actie = 'duplicaat_autoafvoer_platform_gewijzigd'"
                    )
                )
                .scalars()
                .all()
            )
        assert acties == ["duplicaat_autoafvoer_platform_gewijzigd"]
