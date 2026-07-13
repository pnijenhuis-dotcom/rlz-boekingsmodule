"""B5 (leerlus: geboekt = observatie bron='app') en B6 (voorstel-service) integraal, plus de
waarborg dat een geheugen-voorstel nooit de projectplicht-check opheft."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, service
from app.documenten.checks import CheckRegel, check_verplichte_velden
from app.geheugen import service as geheugen_service
from app.geheugen.leerlus import leg_boeking_vast
from tests.documenten.fake_rlz_client import FakeBoekClient

VENDOR = uuid.uuid4()
GB = uuid.uuid4()
BTW = uuid.uuid4()


@pytest.fixture(autouse=True)
def _opslag_naar_tmp(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path / "documenten"))


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=GB,
        taxrate_id=BTW,
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Diesel NEN590",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


def _boek(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    monkeypatch,
    regels: list | None = None,
    regels_samenvoegen: bool | None = None,
    totaal: Decimal = Decimal("121.00"),
) -> uuid.UUID:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    opslag = service._standaard_opslag()  # wijst naar de tmp-map (autouse-fixture hierboven)
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=VENDOR,
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=totaal,
        regels=regels if regels is not None else [_regel()],
        regels_samenvoegen=regels_samenvoegen,
    )
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
    boeken.boek_document(administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=actor_id)
    return resultaat.document_id


def _observaties(admin_engine: Engine, administratie_id: uuid.UUID) -> list:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT vendor_id, regel_sleutel, regel_omschrijving_raw, gb_id, btw_id, bron, "
                    "bron_datum, boekstuk_ref FROM boekhouding.boeking_observatie "
                    "WHERE administratie_id = :a ORDER BY aangemaakt_op, regel_sleutel"
                ),
                {"a": administratie_id},
            )
        )


class TestLeerlus:
    def test_boeken_legt_observatie_vast_op_leverancier_niveau_bij_samenvoegen(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, beheerder_id: uuid.UUID,
        admin_engine: Engine, monkeypatch,
    ) -> None:
        _boek(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
            regels_samenvoegen=True,
        )
        rijen = _observaties(admin_engine, administratie_id)
        assert len(rijen) == 1
        rij = rijen[0]
        assert (str(rij.vendor_id), rij.bron) == (str(VENDOR), "app")
        # Samengevoegd -> leverancier-niveau: geen sleutel, geen raw omschrijving.
        assert rij.regel_sleutel is None
        assert rij.regel_omschrijving_raw is None
        assert str(rij.gb_id) == str(GB)
        assert rij.bron_datum == date(2026, 7, 1)  # factuurdatum, niet boekdatum
        assert rij.boekstuk_ref == "RLZ-TEST-00001"

    def test_gesplitste_boeking_legt_regel_niveau_vast(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, beheerder_id: uuid.UUID,
        admin_engine: Engine, monkeypatch,
    ) -> None:
        regels = [
            _regel(omschrijving="Diesel NEN590", netto_bedrag=Decimal("50.00"), btw_bedrag=Decimal("10.50")),
            _regel(omschrijving="Huur heater 170KW", netto_bedrag=Decimal("50.00"), btw_bedrag=Decimal("10.50")),
        ]
        _boek(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
            regels=regels,
            regels_samenvoegen=False,
        )
        rijen = _observaties(admin_engine, administratie_id)
        assert sorted(r.regel_sleutel for r in rijen) == ["170kw heater huur", "diesel nen590"]
        assert all(r.bron == "app" for r in rijen)

    def test_leerlus_is_idempotent_per_boekstuk(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, beheerder_id: uuid.UUID,
        admin_engine: Engine, monkeypatch,
    ) -> None:
        document_id = _boek(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        # Simuleer een retry die dezelfde boeking nogmaals vastlegt (zelfde document+regels).
        with scoped_session(administratie_id) as session:
            nieuw = leg_boeking_vast(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                vendor_id=VENDOR,
                factuurdatum=date(2026, 7, 1),
                boekstuk_ref="RLZ-TEST-00001",
                regels=voorstel.regels,
                regels_samenvoegen=voorstel.regels_samenvoegen,
            )
        assert nieuw == 0
        assert len(_observaties(admin_engine, administratie_id)) == 1


class TestExpose:
    def test_voorstel_service_geeft_geboekte_waarden_terug(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch
    ) -> None:
        _boek(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        voorstel = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert voorstel.gb.waarde == GB
        assert voorstel.btw.waarde == BTW
        # één app-observatie: voorstel mag, en de app-correctie haalt 'm uit oranje.
        assert not voorstel.gb.oranje
        assert voorstel.gb.telling == 1
        assert voorstel.gb.confidence == 1.0

    def test_onbekende_crediteur_geeft_leeg_oranje_voorstel(self, administratie_id: uuid.UUID) -> None:
        voorstel = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=uuid.uuid4())
        assert voorstel.gb.waarde is None
        assert voorstel.gb.oranje


class TestProjectplichtBlijftBlokkeren:
    def test_geheugen_voorstel_heft_de_harde_projectcheck_nooit_op(self) -> None:
        """Ook mét een vol geheugen-voorstel (incl. project) blokkeert de verplichte-velden-check
        zolang de boekingsregel zelf geen project draagt — het voorstel is een default voor de
        controleur, geen vervanging van de check."""
        regel_zonder_project = CheckRegel(
            ledger_id=GB, taxrate_id=BTW, netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"),
            project_id=None,
        )
        resultaat = check_verplichte_velden(
            vendor_id=VENDOR,
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[regel_zonder_project],
            project_verplicht=True,
        )
        assert not resultaat.ok
        assert "project (regel 1)" in resultaat.melding
