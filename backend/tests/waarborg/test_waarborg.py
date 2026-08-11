"""VASTLY-WAARBORG-route (blok E 2026-08-10): parser, intake-routing (herkenning + failsafes +
idempotentie op bericht_id + plausibiliteits-signaal), voorstel/tegenrekening, harde checks per
weiger-reden en de boekmotor (saldo-0-memoriaal, debet/credit per richting, storno-vrij pad)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import boeken as documenten_boeken
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_waarborg_memoriaal_id
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.waarborg_xml import (
    parseer_waarborg_bericht,
    waarborg_velden_ontbrekend,
)
from app.intake.verwerking import verwerk_eml
from app.waarborg import boeken as waarborg_boeken
from app.waarborg import service as waarborg_service
from app.waarborg.models import WaarborgBericht
from tests.intake.conftest import bouw_eml
from tests.waarborg.conftest import (
    BERICHT_ID,
    TEGENREKENING_LEDGER_ID,
    WAARBORG_LEDGER_ID,
    FakeOmzetClient,
    bouw_waarborg_xml,
)


def _verwerk(inhoud: bytes, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str = "waarborg.xml"):
    eml = bouw_eml(afzender="boekhouding@vastly.nl", bijlagen=[(naam, inhoud, "application", "xml")])
    return verwerk_eml(eml, actor_id=actor_id, opslag=opslag)


class TestParser:
    def test_parseert_alle_contractvelden(self) -> None:
        bericht = parseer_waarborg_bericht(bouw_waarborg_xml())
        assert bericht.bericht_id == BERICHT_ID
        assert bericht.schema_versie == "1.0"
        assert bericht.verhuurder_entiteit == "Rubicon Investments B.V."
        assert bericht.rlz_admin_id_hint == "be5e66b3-b38c-4927-85c1-670490f16e3a"
        assert bericht.contract_referentie == "CT-2026-0042"
        assert bericht.huurder == "J. de Tester"
        assert bericht.bedrag == Decimal("1500.00")
        assert bericht.richting == "ontvangst"
        assert bericht.datum.isoformat() == "2026-08-01"
        assert bericht.balans_gb_code == "0204"
        assert waarborg_velden_ontbrekend(bericht) == []

    @pytest.mark.parametrize(
        ("weglaten", "verwacht_in_melding"),
        [
            ({"bericht_id": None}, "bericht_id"),
            ({"contract_referentie": None}, "contract_referentie"),
            ({"bedrag": None}, "bedrag"),
            ({"bedrag": "-10.00"}, "bedrag"),
            ({"richting": "storting"}, "richting"),
            ({"datum": "gisteren"}, "datum"),
            ({"balans_gb_code": None}, "balans_gb_code"),
        ],
    )
    def test_ontbrekende_of_onbruikbare_velden(self, weglaten: dict, verwacht_in_melding: str) -> None:
        bericht = parseer_waarborg_bericht(bouw_waarborg_xml(**weglaten))
        ontbrekend = waarborg_velden_ontbrekend(bericht)
        assert any(verwacht_in_melding in melding for melding in ontbrekend), ontbrekend


class TestIntakeRouting:
    def test_geldig_bericht_wordt_toegewezen_met_registratie(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = _verwerk(bouw_waarborg_xml(), gescoopte_gebruiker, opslag)
        [bijlage] = resultaat.bijlagen
        assert bijlage.uitkomst == "toegewezen"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT soort, status, administratie_id FROM boekhouding.document WHERE id = :id"),
                {"id": bijlage.document_id},
            ).one()
        assert rij.soort == "waarborg"
        assert rij.status == "te_controleren"
        assert rij.administratie_id == administratie_heet_rubicon
        with scoped_session(administratie_heet_rubicon) as session:
            bericht = session.get(WaarborgBericht, bijlage.document_id)
            assert bericht is not None
            assert bericht.bericht_id == BERICHT_ID
            assert bericht.bedrag == Decimal("1500.00")

    def test_incompleet_bericht_valt_zichtbaar_in_verzamelbak(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = _verwerk(bouw_waarborg_xml(balans_gb_code=None), gescoopte_gebruiker, opslag)
        [bijlage] = resultaat.bijlagen
        assert bijlage.uitkomst == "verzamelbak"
        assert "waarborg_invalide" in (bijlage.detail or "")
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT soort, status FROM boekhouding.document WHERE id = :id"),
                {"id": bijlage.document_id},
            ).one()
        assert rij.soort == "waarborg"
        assert rij.status == "niet_toegewezen"

    def test_onbekende_verhuurder_valt_in_verzamelbak(
        self, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = _verwerk(
            bouw_waarborg_xml(verhuurder="Onbekende Verhuurder B.V."), gescoopte_gebruiker, opslag
        )
        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "waarborg_niet_toewijsbaar" in (resultaat.bijlagen[0].detail or "")

    def test_idempotent_op_bericht_id(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        eerste = _verwerk(bouw_waarborg_xml(), gescoopte_gebruiker, opslag)
        tweede = _verwerk(bouw_waarborg_xml(), gescoopte_gebruiker, opslag, naam="waarborg-kopie.xml")
        assert eerste.bijlagen[0].uitkomst == "toegewezen"
        assert tweede.bijlagen[0].uitkomst == "waarborg_duplicaat"
        assert tweede.bijlagen[0].document_id == eerste.bijlagen[0].document_id
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.waarborg_bericht WHERE bericht_id = :bid"),
                {"bid": str(BERICHT_ID)},
            ).scalar()
        assert aantal == 1

    def test_zelfde_kernvelden_ander_bericht_id_geeft_signaal_geen_dedup(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        _verwerk(bouw_waarborg_xml(), gescoopte_gebruiker, opslag)
        ander_id = uuid.uuid4()
        tweede = _verwerk(
            bouw_waarborg_xml(bericht_id=ander_id), gescoopte_gebruiker, opslag, naam="waarborg-2.xml"
        )
        # Geen stille dedup: het nieuwe bericht wordt gewoon verwerkt…
        assert tweede.bijlagen[0].uitkomst == "toegewezen"
        # …mét een zichtbaar plausibiliteits-signaal in het audit-log.
        with admin_engine.connect() as conn:
            signalen = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'waarborg_zelfde_kernvelden_signaal'")
            ).scalar()
        assert signalen == 1


def _toegewezen_document(
    administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, **xml_kwargs
) -> uuid.UUID:
    resultaat = _verwerk(bouw_waarborg_xml(**xml_kwargs), actor_id, opslag)
    assert resultaat.bijlagen[0].uitkomst == "toegewezen", resultaat.bijlagen[0]
    document_id = resultaat.bijlagen[0].document_id
    assert document_id is not None
    return document_id


class TestVoorstelEnChecks:
    def test_voorstel_brongegeven_plus_gb_resolutie(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
    ) -> None:
        document_id = _toegewezen_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        data = waarborg_service.haal_waarborg_voorstel_op(
            administratie_id=administratie_heet_rubicon, document_id=document_id
        )
        assert data.balans_gb_status == "bekend"
        assert data.balans_ledger_id == WAARBORG_LEDGER_ID
        assert data.tegenrekening_ledger_id is None
        assert data.status == "open"

    def test_checks_blokkeren_zonder_tegenrekening_en_onbekende_gb(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        # Geen rekeningschema-fixture: 0204 is onbekend in deze administratie.
        document_id = _toegewezen_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        rapport = waarborg_service.voer_waarborg_checks_uit(
            administratie_id=administratie_heet_rubicon, document_id=document_id
        )
        assert rapport.geblokkeerd is True
        per_naam = {r.naam: r for r in rapport.resultaten}
        assert per_naam["verplichte_velden"].ok is False  # tegenrekening ontbreekt
        assert per_naam["balans_gb_bekend"].ok is False

    def test_checks_groen_met_tegenrekening_en_bekende_gb(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
    ) -> None:
        document_id = _toegewezen_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        waarborg_service.sla_tegenrekening_op(
            administratie_id=administratie_heet_rubicon,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            tegenrekening_ledger_id=TEGENREKENING_LEDGER_ID,
        )
        rapport = waarborg_service.voer_waarborg_checks_uit(
            administratie_id=administratie_heet_rubicon, document_id=document_id
        )
        assert rapport.geblokkeerd is False, [(r.naam, r.melding) for r in rapport.resultaten if not r.ok]

    def test_memoriaal_lines_ontvangst_credit_op_waarborgrekening(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
    ) -> None:
        """Inrichtingskeuze Peter 2026-08-09 (§6.4/v1.11): ontvangst → waarborgrekening aan de
        CREDITZIJDE (saldo presenteert zich als verplichting); terugbetaling = spiegelbeeld."""
        document_id = _toegewezen_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        waarborg_service.sla_tegenrekening_op(
            administratie_id=administratie_heet_rubicon,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            tegenrekening_ledger_id=TEGENREKENING_LEDGER_ID,
        )
        data = waarborg_service.haal_waarborg_voorstel_op(
            administratie_id=administratie_heet_rubicon, document_id=document_id
        )
        waarborg_kant, tegen_kant = waarborg_service.memoriaal_lines(data)
        assert waarborg_kant["Account"]["id"] == str(WAARBORG_LEDGER_ID)
        assert waarborg_kant["CreditOrDebit"] == 2
        assert waarborg_kant["CreditAmount"] == 1500.0
        assert tegen_kant["CreditOrDebit"] == 1
        assert tegen_kant["DebitAmount"] == 1500.0


class TestBoekmotor:
    def _boekbaar_document(
        self,
        administratie_id: uuid.UUID,
        actor_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        **xml_kwargs,
    ) -> uuid.UUID:
        document_id = _toegewezen_document(administratie_id, actor_id, opslag, **xml_kwargs)
        waarborg_service.sla_tegenrekening_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            tegenrekening_ledger_id=TEGENREKENING_LEDGER_ID,
        )
        return document_id

    def test_boekt_saldo_0_memoriaal_en_registreert(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
        document_id = self._boekbaar_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)

        resultaat = waarborg_boeken.boek_waarborg_document(
            administratie_id=administratie_heet_rubicon,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
        )
        assert resultaat.status == DocumentStatus.GEBOEKT
        assert resultaat.memoriaal_rlz_id == rlz_waarborg_memoriaal_id(document_id)
        journal = client.manual_journals[str(resultaat.memoriaal_rlz_id)]
        assert journal["Status"] == 3  # memoriaal: direct afgeletterd (saldo 0), RLZ-gedrag
        credit = [line for line in journal["DocumentLineList"] if line.get("CreditOrDebit") == 2]
        debet = [line for line in journal["DocumentLineList"] if line.get("CreditOrDebit") == 1]
        assert credit[0]["Account"]["id"] == str(WAARBORG_LEDGER_ID)
        assert debet[0]["Account"]["id"] == str(TEGENREKENING_LEDGER_ID)
        with scoped_session(administratie_heet_rubicon) as session:
            bericht = session.get(WaarborgBericht, document_id)
            assert bericht.status == "geboekt"
            assert bericht.rlz_boekstuknummer is not None

    def test_terugbetaling_spiegelt_de_richting(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
        document_id = self._boekbaar_document(
            administratie_heet_rubicon, gescoopte_gebruiker, opslag,
            bericht_id=uuid.uuid4(), richting="terugbetaling",
        )
        resultaat = waarborg_boeken.boek_waarborg_document(
            administratie_id=administratie_heet_rubicon,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
        )
        journal = client.manual_journals[str(resultaat.memoriaal_rlz_id)]
        debet = [line for line in journal["DocumentLineList"] if line.get("CreditOrDebit") == 1]
        assert debet[0]["Account"]["id"] == str(WAARBORG_LEDGER_ID)

    def test_geblokkeerde_checks_weigeren_de_boeking(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
        # Geen tegenrekening gekozen → verplichte velden blokkeert.
        document_id = _toegewezen_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        with pytest.raises(documenten_boeken.BoekenGeblokkeerdDoorChecks):
            waarborg_boeken.boek_waarborg_document(
                administratie_id=administratie_heet_rubicon,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
            )

    def test_tweede_boeking_blokkeert_op_al_geboekt(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
        document_id = self._boekbaar_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        waarborg_boeken.boek_waarborg_document(
            administratie_id=administratie_heet_rubicon, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        # GEBOEKT is terminaal — de statuspoort weigert een tweede poging.
        with pytest.raises(documenten_boeken.OngeldigeBoekpoging):
            waarborg_boeken.boek_waarborg_document(
                administratie_id=administratie_heet_rubicon,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
            )

    def test_rlz_fout_zet_boeken_mislukt(
        self,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        waarborg_rekeningschema: None,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        client = FakeOmzetClient(faal_op="memoriaal_put")
        monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
        document_id = self._boekbaar_document(administratie_heet_rubicon, gescoopte_gebruiker, opslag)
        with pytest.raises(documenten_boeken.RlzBoekingMislukt):
            waarborg_boeken.boek_waarborg_document(
                administratie_id=administratie_heet_rubicon,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
            )
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
            ).scalar()
        assert status == "boeken_mislukt"
