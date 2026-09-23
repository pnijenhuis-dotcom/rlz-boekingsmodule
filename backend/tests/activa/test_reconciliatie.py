# ruff: noqa: F811 — pytest-fixtures als parameters
"""Reconciliatieblok `activa`: pure toets (vijf soorten), registry/teksten-guard (alle soorten in `meten` sinds 21-09,
leesbare
tekst mét handeling), cli_blok mét FakeBoekClient (403 = afwijking register_niet_leesbaar; leesbaar = aansluiting; Odoo
overgeslagen; geen credential = FOUT-regel), en de registratie in run.BLOKKEN."""

from __future__ import annotations

import argparse
import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.activa import reconciliatie as rec
from app.activa import service
from app.activa.models import KoppelingStatus
from app.activa.register import Activum, Methode, methode_voor_termijn, naar_activum
from app.documenten import boeken
from app.reconciliatie import run as run_service
from app.reconciliatie import soort_stand, teksten
from app.reconciliatie.run import Bevinding, Verzamelaar
from app.rlz.credentials import GeenRlzCredentials
from tests.activa.conftest import GB_0108
from tests.documenten.fake_rlz_client import FakeBoekClient

ARGS = argparse.Namespace()
VANDAAG = date(2026, 9, 21)


def _activum(**kw) -> Activum:  # noqa: ANN003
    basis = dict(
        id=uuid.uuid4(),
        receipt_number="7",
        omschrijving="Bureau",
        invoice_reference="KI-1",
        aanschafwaarde=Decimal("1250.00"),
        aanschafdatum=date(2026, 9, 1),
        boekwaarde=Decimal("1250.00"),
        afschrijving_cumulatief=Decimal("0.00"),
        type=1,
        status=2,
        methode_id=None,
        methode_naam="Lineair 5 jaar",
        methode_maanden=60,
    )
    basis.update(kw)
    return Activum(**basis)


def _regel(**kw) -> rec.ModuleRegel:  # noqa: ANN003
    basis = dict(
        document_id=uuid.uuid4(),
        regel_volgnummer=1,
        boek_cyclus=0,
        referentie="KI-1",
        leverancier_naam="Kantoorinrichting B.V.",
        ledger_code="0107",
        ledger_naam="Inventaris",
        netto=Decimal("1250.00"),
        factuurdatum=date(2026, 9, 1),
        koppeling_status=None,
        koppeling_rlz_id=None,
    )
    basis.update(kw)
    return rec.ModuleRegel(**basis)


class TestToetsPuur:
    def test_boeking_met_koppeling_aangemaakt_of_bedragmatch_binnen_30_dagen_sluit(self) -> None:
        a = _activum()
        gekoppeld = _regel(koppeling_status="aangemaakt", koppeling_rlz_id=a.id)
        assert rec.toets(module_regels=[gekoppeld], activa=[a], mislukt=[], vandaag=VANDAAG) == []
        los = _regel(factuurdatum=date(2026, 9, 25))  # geen koppeling, wél zelfde bedrag binnen 30 d
        assert rec.toets(module_regels=[los], activa=[a], mislukt=[], vandaag=VANDAAG) == []

    def test_boeking_zonder_activum_en_activum_zonder_boeking(self) -> None:
        a = _activum(aanschafwaarde=Decimal("999.00"))
        r = _regel()
        uit = rec.toets(module_regels=[r], activa=[a], mislukt=[], vandaag=VANDAAG)
        assert [x.soort for x in uit] == ["mva_boeking_zonder_activum", "activum_zonder_boeking"]
        assert uit[0].sleutel == f"{r.document_id}:1:0" and uit[0].detail["bedrag"] == "1250.00"
        assert uit[1].sleutel == str(a.id) and uit[1].detail["rlz_receipt_number"] == "7"

    def test_bedragmatch_buiten_30_dagen_telt_niet(self) -> None:
        a = _activum(aanschafdatum=date(2026, 6, 1))
        uit = rec.toets(module_regels=[_regel()], activa=[a], mislukt=[], vandaag=VANDAAG)
        assert sorted(x.soort for x in uit) == ["activum_zonder_boeking", "mva_boeking_zonder_activum"]

    def test_register_van_voor_2026_blijft_buiten_beeld(self) -> None:
        a = _activum(aanschafdatum=date(2025, 3, 1), afschrijving_cumulatief=Decimal("200.00"))
        assert rec.toets(module_regels=[], activa=[a], mislukt=[], vandaag=VANDAAG) == []

    def test_afschrijving_niet_gelopen_na_een_jaar_met_boekwaarde(self) -> None:
        oud = _activum(
            aanschafdatum=date(2025, 1, 15), afschrijving_cumulatief=Decimal("0.00"), boekwaarde=Decimal("1250.00")
        )
        vers = _activum(aanschafdatum=date(2026, 3, 1), afschrijving_cumulatief=Decimal("0.00"))
        afgeschreven = _activum(
            aanschafdatum=date(2025, 1, 15), afschrijving_cumulatief=Decimal("0.00"), boekwaarde=Decimal("0.00")
        )
        uit = rec.toets(module_regels=[], activa=[oud, vers, afgeschreven], mislukt=[], vandaag=VANDAAG)
        soorten = [x.soort for x in uit]
        assert soorten.count("afschrijving_niet_gelopen") == 1
        assert soorten.count("activum_zonder_boeking") == 1  # alleen `vers` (≥ 2026) zonder boeking

    def test_register_niet_gelezen_toetst_alleen_mislukt(self) -> None:
        m = rec.MislukteKoppeling(
            koppeling_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            regel_volgnummer=1,
            herkomst="automatisch",
            omschrijving="Bureau",
            aanschafwaarde=Decimal("1250.00"),
            reden="geen afschrijvingsrekening",
            referentie="KI-1",
            leverancier_naam="X",
        )
        uit = rec.toets(module_regels=[_regel()], activa=None, mislukt=[m], vandaag=VANDAAG)
        assert [x.soort for x in uit] == ["activum_aanmaken_mislukt"] and "geen afschrijvingsrekening" in uit[0].tekst
        assert uit[0].detail["herkomst"] == "automatisch" and uit[0].detail["koppeling_id"] == str(m.koppeling_id)

    def test_mislukt_na_mens_klik_is_eigen_soort_direct_actie(self) -> None:
        """BUG 24-09 (BLOw 23-09): een `mislukt` mét herkomst `mens` = bevestigde handeling niet uitgevoerd → soort
        `activum_aanmaken_mislukt_mens`, code-default `actie` (geen meetfase), handeling "Opnieuw aanmaken" op de
        rij."""
        m = rec.MislukteKoppeling(
            koppeling_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            regel_volgnummer=1,
            herkomst="mens",
            omschrijving="Kantoorinventaris",
            aanschafwaarde=Decimal("935.00"),
            reden="geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa",
            referentie="23619",
            leverancier_naam="Leverancier",
        )
        uit = rec.toets(module_regels=[], activa=None, mislukt=[m], vandaag=VANDAAG)
        assert [x.soort for x in uit] == ["activum_aanmaken_mislukt_mens"] and "ná een mens-klik" in uit[0].tekst
        assert uit[0].detail["herkomst"] == "mens" and uit[0].detail["regel_volgnummer"] == 1
        assert rec.HANDELING["activum_aanmaken_mislukt_mens"].startswith("Opnieuw aanmaken")
        d = soort_stand.REGISTRY["activum_aanmaken_mislukt_mens"]
        assert d.default == soort_stand.ACTIE and d.sinds == date(2026, 9, 24)
        assert "Peter 23/24-09" in (d.direct_actie_reden or "")
        assert soort_stand.code_default("activum_aanmaken_mislukt") == soort_stand.METEN


class TestRegisterLezer:
    def test_naar_activum_leest_de_stap0_vorm(self) -> None:
        rij = {
            "id": "11111111-1111-4111-8111-111111111111",
            "ReceiptNumber": "3",
            "Description": "Pilates reformer",
            "InvoiceReference": "F-88",
            "TotalAmountPurchase": 7927.8,
            "PurchaseDate": "2026-02-01T00:00:00",
            "CurrentBookValue": 7000.5,
            "CurrentDepreciationValue": 927.3,
            "Type": 1,
            "Status": 2,
            "DepreciationMethod": {
                "id": "22222222-2222-4222-8222-222222222222",
                "NumberOfMonths": 60,
                "Description": "Lineair 5 jaar",
            },
        }
        a = naar_activum(rij)
        assert (
            a.aanschafwaarde == Decimal("7927.80") and a.aanschafdatum == date(2026, 2, 1) and a.receipt_number == "3"
        )
        assert (
            a.methode_maanden == 60
            and a.methode_naam == "Lineair 5 jaar"
            and a.afschrijving_cumulatief == Decimal("927.30")
        )

    def test_methode_voor_termijn_kiest_lineair_op_maanden(self) -> None:
        m60 = Methode(id=uuid.uuid4(), naam="Lineair 5 jaar", maanden=60, basis=1)
        m36 = Methode(id=uuid.uuid4(), naam="Lineair 3 jaar", maanden=36, basis=1)
        deg = Methode(id=uuid.uuid4(), naam="Degressief 5 jaar", maanden=60, basis=4)
        assert methode_voor_termijn([deg, m36, m60], 60) is m60
        assert methode_voor_termijn([m36, m60], 84) is None
        assert methode_voor_termijn([deg], 60) is None


class TestRegistryEnTeksten:
    def test_alle_soorten_in_meten_sinds_21_09_met_leesbare_tekst_en_handeling(self) -> None:
        for soort in rec.SOORTEN:
            d = soort_stand.REGISTRY[soort]
            assert d.blok == "activa"
            if soort == rec.SOORT_AANMAKEN_MISLUKT_MENS:
                # BUG 24-09: de enige activa-soort die direct in `actie` start (besluit Peter, reden in de registry).
                assert d.default == soort_stand.ACTIE and d.sinds == date(2026, 9, 24) and d.direct_actie_reden
            else:
                assert d.default == soort_stand.METEN and d.sinds == date(2026, 9, 21)
            b = Bevinding(
                blok="activa",
                soort="afwijking",
                administratie_id=uuid.uuid4(),
                vingerafdruk="x",
                tekst=f"AFWIJKING soort={soort}",
                detail={
                    "afwijking_soort": soort,
                    "administratie_naam": "Pilates Bloom B.V.",
                    "omschrijving": "Reformer",
                    "rlz_receipt_number": "3",
                    "bedrag": "7927.80",
                    "aanschafdatum": "2026-02-01",
                    "leverancier_naam": "Balanced Body",
                    "factuurnummer": "F-88",
                    "ledger_code": "0107",
                    "ledger_naam": "Inventaris",
                    "reden": "geen afschrijvingsrekening",
                },
            )
            lees = teksten.leesbaar(b)
            assert len(lees.titel) <= teksten.MAX_TITEL and lees.wat and lees.doe
            assert not teksten.bevat_technische_sleutel(lees.wat) and not teksten.bevat_technische_sleutel(lees.doe)
            assert "Afwijking activa" not in lees.titel, soort  # élke soort heeft een eigen tekst
        assert "€ 7.927,80" in teksten.leesbaar(b).wat

    def test_blok_staat_in_run_blokken(self) -> None:
        # 23-09: ná activa kwam het postvak-blok `intake` (Peter 22-09) — activa blijft vlak vóór intake.
        assert "activa" in run_service.BLOKKEN and run_service.BLOKKEN[-2:] == ("activa", "intake")


class TestCliBlok:
    def _run(
        self, client: FakeBoekClient | None, *, fout: Exception | None = None
    ) -> tuple[int, Verzamelaar, list[str]]:
        uit: list[str] = []
        verzamelaar = Verzamelaar()
        verzamelaar.start_blok(rec.BLOK)

        def client_voor(aid: uuid.UUID):  # noqa: ANN202
            if fout is not None:
                raise fout
            return client

        code = rec.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=uit.append, client_voor=client_voor)
        return code, verzamelaar, uit

    def test_zonder_mva_rekeningen_niets_getoetst(self, administratie_id: uuid.UUID) -> None:
        code, verzamelaar, uit = self._run(FakeBoekClient())
        assert code == 0 and verzamelaar.bevindingen == [] and "0 administratie(s)" in uit[-1]

    def test_lees_only_run_schrijft_de_probe_stand_niet(self, stamgegevens: None, administratie_id: uuid.UUID) -> None:
        """Nameting 22-09: `reconciliatie-alles --alleen activa --lees-only` meldde "niets vastgelegd" maar zette op
        75 administraties `register_geprobeerd_op` op het meetmoment (leesreplica 10:18 UTC). Lees-only = verzamelaar
        None → de probe doet alleen de GET; een echte run (verzamelaar) schrijft de stand wél."""
        from app.activa import instelling as instelling_service
        from app.db.session import scoped_session

        client = FakeBoekClient()
        client.fixed_assets_403 = True
        uit: list[str] = []
        code = rec.cli_blok(ARGS, verzamelaar=None, stdout=uit.append, client_voor=lambda aid: client)
        assert code == 1 and any("activa_register_niet_leesbaar" in regel for regel in uit)
        with scoped_session(administratie_id) as session:
            stand = instelling_service.lees_stand(session, administratie_id)
            assert stand.register_geprobeerd_op is None and stand.register_leesbaar is None
        # tegenproef: de echte run legt de stand wél vast
        code, _verzamelaar, _ = self._run(client)
        assert code == 1
        with scoped_session(administratie_id) as session:
            stand = instelling_service.lees_stand(session, administratie_id)
            assert stand.register_leesbaar is False and stand.register_geprobeerd_op is not None

    def test_403_is_afwijking_register_niet_leesbaar_met_handeling(
        self, stamgegevens: None, administratie_id: uuid.UUID
    ) -> None:
        client = FakeBoekClient()
        client.fixed_assets_403 = True
        code, verzamelaar, uit = self._run(client)
        assert code == 1
        [b] = verzamelaar.bevindingen
        assert b.soort == "afwijking" and b.detail["afwijking_soort"] == "activa_register_niet_leesbaar"
        assert b.administratie_id == administratie_id and "RLZ-recht 'Vaste activa'" in b.tekst
        assert b.vingerafdruk == f"activa:{administratie_id}:activa_register_niet_leesbaar"

    def test_geboekte_mva_regel_zonder_activum_en_los_activum(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
    ) -> None:
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        # Register: één los activum van dit jaar zonder module-boeking + één oud activum zonder afschrijving.
        rlz.fixed_assets = {
            "a1": {
                "id": str(uuid.uuid4()),
                "ReceiptNumber": "1",
                "Description": "Los activum",
                "TotalAmountPurchase": 800.0,
                "PurchaseDate": "2026-05-01T00:00:00",
                "CurrentBookValue": 800.0,
                "CurrentDepreciationValue": 0.0,
                "Type": 1,
            },
            "a2": {
                "id": str(uuid.uuid4()),
                "ReceiptNumber": "2",
                "Description": "Oude machine",
                "TotalAmountPurchase": 9000.0,
                "PurchaseDate": "2024-01-10T00:00:00",
                "CurrentBookValue": 9000.0,
                "CurrentDepreciationValue": 0.0,
                "Type": 1,
            },
        }
        code, verzamelaar, uit = self._run(rlz)
        assert code == 1
        soorten = sorted(b.detail["afwijking_soort"] for b in verzamelaar.bevindingen)
        assert soorten == ["activum_zonder_boeking", "afschrijving_niet_gelopen", "mva_boeking_zonder_activum"]
        zonder = next(b for b in verzamelaar.bevindingen if b.detail["afwijking_soort"] == "mva_boeking_zonder_activum")
        assert zonder.detail["leverancier_naam"] == "Kantoorinrichting B.V." and zonder.detail["bedrag"] == "1250.00"
        assert zonder.detail["handeling"] == "Activum aanmaken op het controlescherm"
        assert verzamelaar.blokken[rec.BLOK].gecontroleerd == 1
        # Ná "Activum aanmaken" (document is geboekt → direct in RLZ) verdwijnt de boeking-zonder-activum.
        service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=factuur,
            regel_volgnummer=1,
            actor_id=gescoopte_gebruiker,
            afschrijving_ledger_id=GB_0108,
            client=rlz,
        )
        code, verzamelaar, _ = self._run(rlz)
        assert sorted(b.detail["afwijking_soort"] for b in verzamelaar.bevindingen) == [
            "activum_zonder_boeking",
            "afschrijving_niet_gelopen",
        ]

    def test_mislukte_koppeling_is_afwijking_met_opnieuw_aanmaken(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
    ) -> None:
        # BUG 24-09: zonder afschrijvingsrekening kan er niet meer gepland worden (0107 → conventie 0108 vult wél voor);
        # de mislukking komt hier van RLZ zelf (PUT weigert) — een mens-klik → soort `_mens`, direct actie.
        service.plan_of_maak_aan(
            administratie_id=administratie_id, document_id=factuur, regel_volgnummer=1, actor_id=gescoopte_gebruiker
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        rlz.faal_op = "fixed_asset_put"
        service.verwerk_na_boeken(
            administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, client=rlz
        )
        rlz.faal_op = None
        code, verzamelaar, _ = self._run(rlz)
        mislukt = [b for b in verzamelaar.bevindingen if b.detail["afwijking_soort"] == "activum_aanmaken_mislukt_mens"]
        assert len(mislukt) == 1 and "PUT FixedAssets mislukt" in mislukt[0].tekst
        assert mislukt[0].detail["handeling"].startswith("Opnieuw aanmaken") and mislukt[0].detail["herkomst"] == "mens"
        assert mislukt[0].detail["document_id"] == str(factuur) and mislukt[0].detail["regel_volgnummer"] == 1
        assert not [b for b in verzamelaar.bevindingen if b.detail["afwijking_soort"] == "activum_aanmaken_mislukt"]

    def test_geen_credential_is_zichtbare_fout_en_odoo_overgeslagen(
        self, stamgegevens: None, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        code, verzamelaar, uit = self._run(None, fout=GeenRlzCredentials("geen credential"))
        assert code == 1 and [b.soort for b in verzamelaar.bevindingen] == ["fout"]
        assert any("geen RLZ-verbinding" in regel for regel in uit)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET boekhoud_backend = 'odoo' WHERE id = :a"),
                {"a": administratie_id},
            )
        code, verzamelaar, uit = self._run(FakeBoekClient())
        assert code == 0 and verzamelaar.bevindingen == [] and any(regel.startswith("OVERGESLAGEN") for regel in uit)


@pytest.mark.parametrize("soort", rec.SOORTEN)
def test_handeling_per_soort(soort: str) -> None:
    assert rec.HANDELING[soort]


def test_koppelingstatus_enum_dekt_de_check_constraint() -> None:
    assert {s.value for s in KoppelingStatus} == {"gepland", "aangemaakt", "overgeslagen", "mislukt", "beoordelen"}
    assert len(rec.SOORTEN) == 6 and rec.SOORTEN[-1] == "activum_aanmaken_mislukt_mens"
    assert replace(_activum(), boekwaarde=None).boekwaarde is None
