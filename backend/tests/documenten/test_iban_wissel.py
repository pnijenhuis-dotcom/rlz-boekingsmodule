"""IBAN-wissel-fraudecontrole, integraal: extractie-veldvoorstel -> vertrouwde set
(RLZ-seed/baseline/bevestigd, app/documenten/leverancier_iban.py) -> harde check in
voer_checks_uit. Geldlogica, dus elk pad expliciet (CLAUDE.md: tests verplicht)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import boekvoorstel, leverancier_iban, service
from app.documenten.models import DocumentGebeurtenis, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient

VERTROUWD_IBAN = "NL91ABNA0417164300"
ANDER_IBAN = "BE68539007547034"


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


def _document_met_iban(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    factuur_iban: str | None,
) -> uuid.UUID:
    """Geüpload document + veldvoorstel-gebeurtenis met IBAN (zoals de AI-extractie die schrijft)
    + opgeslagen boekvoorstel — klaar voor voer_checks_uit."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=f"%PDF-1.4 test {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=resultaat.document_id,
                van_status=DocumentStatus.TE_CONTROLEREN,
                naar_status=DocumentStatus.TE_CONTROLEREN,
                actor_id=actor_id,
                detail={"veldvoorstel": {"bron": "ai", "iban": factuur_iban}},
            )
        )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


def _iban_resultaat(rapport) -> object:
    return next(r for r in rapport.resultaten if r.naam == "IBAN-wissel")


def _iban_rijen(admin_engine: Engine, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT iban, bron, bevestigd_door FROM boekhouding.leverancier_iban "
                    "WHERE administratie_id = :a AND vendor_id = :v ORDER BY iban"
                ),
                {"a": administratie_id, "v": vendor_id},
            )
        )


@pytest.fixture
def vendor_id() -> uuid.UUID:
    return uuid.uuid4()


class TestEersteKeer:
    def test_eerste_keer_legt_baseline_vast_zonder_blok(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=VERTROUWD_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )

        resultaat = _iban_resultaat(rapport)
        assert resultaat.ok
        assert "baseline" in resultaat.melding
        assert not rapport.geblokkeerd
        rijen = _iban_rijen(admin_engine, administratie_id, vendor_id)
        assert [(r.iban, r.bron, r.bevestigd_door) for r in rijen] == [(VERTROUWD_IBAN, "baseline", None)]
        # De IBAN-mutatie is het controlewaardige feit: audit_event verplicht.
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'leverancier_iban' AND record_id = :v"
                ),
                {"v": vendor_id},
            ).scalar_one()
        assert audit == 1

    def test_mislukte_rlz_seed_blokkeert_op_eigen_titel_en_legt_geen_baseline_vast(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Fail-closed: mislukt de seed-poging (lege set), dan weten we niet of RLZ een
        tegensprekende bankrelatie heeft — geen baseline vastleggen én de IBAN-wissel-check
        blokkeert ZELF, onafhankelijk van wat de duplicaatcheck doet."""
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=VERTROUWD_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(faal_op="bank_relations"),
        )
        resultaat = _iban_resultaat(rapport)
        assert not resultaat.ok
        assert "kon niet worden opgehaald" in resultaat.melding
        # Op eigen titel geblokkeerd: ook als álle andere checks groen zouden zijn, blokkeert
        # het rapport al door deze ene rij.
        assert rapport.geblokkeerd
        andere = [r for r in rapport.resultaten if r.naam != "IBAN-wissel"]
        assert all(r.ok for r in andere)
        assert _iban_rijen(admin_engine, administratie_id, vendor_id) == []


class TestMatchEnWissel:
    def test_matchende_iban_passeert(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
    ) -> None:
        leverancier_iban.leg_baseline_vast(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=VERTROUWD_IBAN, actor_id=gescoopte_gebruiker
        )
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=VERTROUWD_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )
        assert _iban_resultaat(rapport).ok
        assert not rapport.geblokkeerd

    def test_gewijzigde_iban_blokkeert(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
    ) -> None:
        leverancier_iban.leg_baseline_vast(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=VERTROUWD_IBAN, actor_id=gescoopte_gebruiker
        )
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=ANDER_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )
        resultaat = _iban_resultaat(rapport)
        assert not resultaat.ok
        assert rapport.geblokkeerd
        # Privacy: het volledige IBAN staat niet in de melding.
        assert ANDER_IBAN not in resultaat.melding

    def test_tweede_bevestigde_iban_g_rekening_passeert(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """WKA/G-rekening: na menselijke bevestiging is de tweede rekening gewoon vertrouwd —
        meerwaardige set, geen wissel-signaal meer."""
        leverancier_iban.leg_baseline_vast(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=VERTROUWD_IBAN, actor_id=gescoopte_gebruiker
        )
        leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=ANDER_IBAN, actor_id=gescoopte_gebruiker
        )
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=ANDER_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )
        assert _iban_resultaat(rapport).ok
        rijen = _iban_rijen(admin_engine, administratie_id, vendor_id)
        assert [(r.iban, r.bron, r.bevestigd_door) for r in rijen] == [
            (ANDER_IBAN, "bevestigd", gescoopte_gebruiker),
            (VERTROUWD_IBAN, "baseline", None),
        ]


class TestRlzSeed:
    def test_seed_uit_rlz_maakt_eerste_keer_niet_blind(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Crediteur met een RLZ-bankrelatie: het factuur-IBAN dat daarvan afwijkt blokkeert al
        bij de állereerste factuur — er is geen blinde baseline."""
        client = FakeBoekClient(
            bank_relations=[
                {"IBAN": VERTROUWD_IBAN, "IsArchived": False},
                {"IBAN": "ongeldig-nummer", "IsArchived": False},  # wordt genegeerd (mod-97)
                {"IBAN": ANDER_IBAN, "IsArchived": True},  # gearchiveerd telt niet
            ]
        )
        document_id = _document_met_iban(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            factuur_iban=ANDER_IBAN,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=client
        )
        assert not _iban_resultaat(rapport).ok
        rijen = _iban_rijen(admin_engine, administratie_id, vendor_id)
        assert [(r.iban, r.bron) for r in rijen] == [(VERTROUWD_IBAN, "rlz_seed")]


class TestBevestigen:
    def test_ongeldig_iban_wordt_geweigerd(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, vendor_id: uuid.UUID
    ) -> None:
        with pytest.raises(leverancier_iban.OngeldigIban):
            leverancier_iban.bevestig_iban(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                iban="NL91ABNA0417164301",  # mod-97 faalt
                actor_id=gescoopte_gebruiker,
            )

    def test_bevestigen_normaliseert_en_is_idempotent(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        eerste = leverancier_iban.bevestig_iban(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            iban="nl91 abna 0417 1643 00",
            actor_id=gescoopte_gebruiker,
        )
        tweede = leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=VERTROUWD_IBAN, actor_id=gescoopte_gebruiker
        )
        assert eerste == tweede == VERTROUWD_IBAN
        assert len(_iban_rijen(admin_engine, administratie_id, vendor_id)) == 1
        # Idempotent: de herhaalde bevestiging van hetzelfde IBAN geeft geen tweede audit-rij.
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'leverancier_iban' AND record_id = :v"
                ),
                {"v": vendor_id},
            ).scalar_one()
        assert audit == 1
