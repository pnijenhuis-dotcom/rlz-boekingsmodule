"""Acceptatie van reconciliatie-afwijkingen (migratie 0042).

De kern van deze laag is niet "afwijkingen kunnen wegklikken" maar het tegenovergestelde:
een acceptatie is zo smal mogelijk (bron + soort + detail) en valt vanzelf weg zodra de
werkelijkheid verandert. Die eigenschap is hier de belangrijkste test."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import ReconciliatieBron
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401

_SOORT = "ontbreekt_in_rlz"
_DETAIL = "GET /8dbfb856/PurchaseInvoices/8ffda67d -> 404: NotFound_PurchaseInvoice"


def _afwijking(record_id: uuid.UUID, detail: str = _DETAIL) -> list[tuple[uuid.UUID, str, str]]:
    return [(record_id, _SOORT, detail)]


class TestVingerafdruk:
    def test_zelfde_afwijking_geeft_zelfde_vingerafdruk(self) -> None:
        eerst = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL)
        nogmaals = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL)
        assert eerst == nogmaals

    def test_ander_detail_geeft_andere_vingerafdruk(self) -> None:
        """Anders zou een acceptatie ook een veranderde situatie blijven afdekken."""
        origineel = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL)
        anders = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL + " (2e keer)")
        assert origineel != anders

    def test_andere_bron_geeft_andere_vingerafdruk(self) -> None:
        assert acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL) != (
            acceptatie_service.vingerafdruk(bron="bank", soort=_SOORT, detail=_DETAIL)
        )


class TestBeoordeel:
    def test_zonder_acceptatie_telt_alles_mee(self, administratie_id: uuid.UUID) -> None:  # noqa: F811
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN,
            administratie_id=administratie_id,
            afwijkingen=_afwijking(uuid.uuid4()),
        )
        assert len(beoordeeld) == 1
        assert beoordeeld[0].telt_mee is True
        assert beoordeeld[0].acceptatie is None

    def test_geaccepteerde_afwijking_blijft_zichtbaar_maar_telt_niet_mee(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        record_id = uuid.uuid4()
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=record_id,
            soort=_SOORT,
            detail=_DETAIL,
            reden="kliktest-documenten na storno in de RLZ-UI opgeruimd",
            beheerder_id=beheerder_id,
        )
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN,
            administratie_id=administratie_id,
            afwijkingen=_afwijking(record_id),
        )
        assert beoordeeld[0].telt_mee is False
        assert beoordeeld[0].acceptatie is not None
        # Zichtbaar blijven is het punt: het detail verdwijnt niet uit het rapport.
        assert beoordeeld[0].detail == _DETAIL
        assert "kliktest" in beoordeeld[0].acceptatie.reden

    def test_veranderde_afwijking_alarmeert_opnieuw(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        """De belangrijkste waarborg: accepteren dekt exact één situatie af, geen categorie."""
        record_id = uuid.uuid4()
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=record_id,
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN,
            administratie_id=administratie_id,
            afwijkingen=[(record_id, "bedrag_wijkt_af", "eigen=€121.00 rlz=€999.00")],
        )
        assert beoordeeld[0].telt_mee is True

    def test_acceptatie_werkt_niet_door_naar_een_andere_administratie(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        record_id = uuid.uuid4()
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=record_id,
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.administratie (id, naam, rlz_admin_id) "
                    "VALUES (:id, 'Andere BV', :rlz)"
                ),
                {"id": andere, "rlz": str(uuid.uuid4())},
            )
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN, administratie_id=andere, afwijkingen=_afwijking(record_id)
        )
        assert beoordeeld[0].telt_mee is True


class TestAccepteren:
    def test_alleen_een_beheerder_mag_accepteren(
        self, administratie_id: uuid.UUID, actieve_gebruiker  # noqa: F811
    ) -> None:
        """Accepteren maakt een blokkerend signaal niet-blokkerend — dat is een
        beheerdershandeling, geen gewone controleurshandeling."""
        with pytest.raises(acceptatie_service.AcceptatieFout):
            acceptatie_service.accepteer(
                administratie_id=administratie_id,
                bron=ReconciliatieBron.DOCUMENTEN,
                record_id=uuid.uuid4(),
                soort=_SOORT,
                detail=_DETAIL,
                reden="ik vind het prima zo",
                beheerder_id=actieve_gebruiker.id,
            )

    def test_lege_reden_wordt_geweigerd(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        with pytest.raises(acceptatie_service.AcceptatieFout):
            acceptatie_service.accepteer(
                administratie_id=administratie_id,
                bron=ReconciliatieBron.DOCUMENTEN,
                record_id=uuid.uuid4(),
                soort=_SOORT,
                detail=_DETAIL,
                reden="  ",
                beheerder_id=beheerder_id,
            )

    def test_tweede_acceptatie_hergebruikt_dezelfde_rij(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        record_id = uuid.uuid4()
        kwargs = dict(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=record_id,
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        assert acceptatie_service.accepteer(**kwargs) == acceptatie_service.accepteer(**kwargs)

    def test_acceptatie_landt_in_het_audit_log(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=uuid.uuid4(),
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        with admin_engine.begin() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'reconciliatie_afwijking_geaccepteerd'"
                )
            ).scalar_one()
        assert aantal == 1


class TestIntrekken:
    def test_intrekken_laat_de_afwijking_weer_meetellen(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        record_id = uuid.uuid4()
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=record_id,
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        vaf = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL)
        acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            vingerafdruk_waarde=vaf,
            reden="document blijkt tóch te ontbreken zonder verklaring",
            beheerder_id=beheerder_id,
        )
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN,
            administratie_id=administratie_id,
            afwijkingen=_afwijking(record_id),
        )
        assert beoordeeld[0].telt_mee is True

    def test_intrekken_verwijdert_niets(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=uuid.uuid4(),
            soort=_SOORT,
            detail=_DETAIL,
            reden="beoordeeld en akkoord",
            beheerder_id=beheerder_id,
        )
        vaf = acceptatie_service.vingerafdruk(bron="documenten", soort=_SOORT, detail=_DETAIL)
        acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            vingerafdruk_waarde=vaf,
            reden="toch weer oppakken",
            beheerder_id=beheerder_id,
        )
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text(
                    "SELECT ingetrokken_op, ingetrokken_door FROM boekhouding.reconciliatie_acceptatie "
                    "WHERE vingerafdruk = :vaf"
                ),
                {"vaf": vaf},
            ).one()
        assert rij.ingetrokken_op is not None
        assert rij.ingetrokken_door == beheerder_id

    def test_onbekende_vingerafdruk_geeft_een_fout(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        with pytest.raises(acceptatie_service.AcceptatieFout):
            acceptatie_service.trek_in(
                administratie_id=administratie_id,
                bron=ReconciliatieBron.DOCUMENTEN,
                vingerafdruk_waarde="0123456789abcdef",
                reden="bestaat niet",
                beheerder_id=beheerder_id,
            )


class TestUitsluiting:
    """Uitsluiting (migratie 0043) haalt een administratie uit de exit-code, niet uit het
    rapport — de rapportkant daarvan zit in de CLI; hier de servicelaag."""

    def test_uitsluiting_zonder_reden_wordt_geweigerd(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        with pytest.raises(beheer_service.BeheerFout):
            beheer_service.zet_reconciliatie_uitgesloten(
                actor_id=beheerder_id, administratie_id=administratie_id, uitgesloten=True, reden=None
            )

    def test_uitgesloten_administratie_staat_in_het_overzicht_en_kan_terug(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        beheer_service.zet_reconciliatie_uitgesloten(
            actor_id=beheerder_id,
            administratie_id=administratie_id,
            uitgesloten=True,
            reden="test-administratie: draagt permanent testboekingen",
        )
        assert acceptatie_service.uitgesloten_administraties()[administratie_id].startswith("test-administratie")

        beheer_service.zet_reconciliatie_uitgesloten(
            actor_id=beheerder_id, administratie_id=administratie_id, uitgesloten=False, reden=None
        )
        assert administratie_id not in acceptatie_service.uitgesloten_administraties()
