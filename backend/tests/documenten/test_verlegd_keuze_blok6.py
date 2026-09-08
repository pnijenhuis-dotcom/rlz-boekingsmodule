"""Blok 6 herstelrun "Basis eerst" 08-09 — verlegd-tarief deterministisch kiezen (migratie 0123).

Casus Universal Steigerbouw (bevinding 4c bundel 08-09): 12 `IsRelayed`-tarieven zonder favoriet →
`verlegd_taxrate_voor` gaf None en de Spot-Services-regel viel terug op een administratie-default "die toevallig
klopt". Nu: `bepaal_verlegd_taxrate` = voorkeur Beheerder → meest gebruikt in de RLZ-historie (gelijkspel NL > EU,
hoog > laag, naam) → één/NL/favoriet → administratie-default als die verlegd is → None; elke keuze draagt haar
herkomst."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.beheer import btw_default
from app.db.session import scoped_session
from app.documenten import regel_prefill
from app.documenten.boekvoorstel import BoekvoorstelRegelData, _regel_snapshot
from app.documenten.regel_prefill import (
    BTW_BRON_FACTUUR_VERLEGD,
    VERLEGD_HERKOMST_DEFAULT,
    VERLEGD_HERKOMST_ENIGE,
    VERLEGD_HERKOMST_ENIGE_NL,
    VERLEGD_HERKOMST_FAVORIET,
    VERLEGD_HERKOMST_HISTORIE,
    VERLEGD_HERKOMST_VOORKEUR,
    VerlegdKeuze,
    _met_factuur_verlegd,
    bepaal_verlegd_taxrate,
    verlegd_taxrate_voor,
)
from app.geheugen.models import BoekingObservatie
from app.sync.models import TaxRateCache

NL_HOOG = uuid.UUID("66666666-0000-0000-0000-000000000001")
NL_LAAG = uuid.UUID("66666666-0000-0000-0000-000000000002")
EU_DIENSTEN_HOOG = uuid.UUID("66666666-0000-0000-0000-000000000003")
EU_PRODUCTEN_HOOG = uuid.UUID("66666666-0000-0000-0000-000000000004")
EXEU_HOOG = uuid.UUID("66666666-0000-0000-0000-000000000005")
HOOG_21 = uuid.UUID("66666666-0000-0000-0000-000000000010")
VENDOR = uuid.UUID("66666666-0000-0000-0000-000000000099")
GB = uuid.UUID("66666666-0000-0000-0000-000000000098")
VANDAAG = date(2026, 9, 8)


def _tarief(id_: uuid.UUID, naam: str, *, verlegd: bool = True, favoriet: bool = False, verdwenen: bool = False):
    return TaxRateCache(
        id=id_,
        administratie_id=None,
        naam=naam,
        percentage=Decimal("0") if verlegd else Decimal("0.2100"),
        brondata={"IsRelayed": verlegd, "IsFavorite": favoriet},
        verdwenen_uit_bron_op=datetime.now(UTC) if verdwenen else None,
    )


def _zet_tarieven(administratie_id: uuid.UUID, *rijen: TaxRateCache) -> None:
    with scoped_session(administratie_id) as session:
        for rij in rijen:
            rij.administratie_id = administratie_id
            session.add(rij)


def _observaties(administratie_id: uuid.UUID, btw_id: uuid.UUID, aantal: int, *, dagen_terug: int = 30) -> None:
    with scoped_session(administratie_id) as session:
        for _ in range(aantal):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR,
                    regel_sleutel=None,
                    gb_id=GB,
                    btw_id=btw_id,
                    project_id=None,
                    bron="rlz_seed",
                    bron_datum=VANDAAG - timedelta(days=dagen_terug),
                )
            )


def _keuze(administratie_id: uuid.UUID) -> VerlegdKeuze | None:
    with scoped_session(administratie_id) as session:
        return bepaal_verlegd_taxrate(session, administratie_id=administratie_id, vandaag=VANDAAG)


@pytest.fixture
def universal(administratie_id: uuid.UUID) -> None:
    """De productie-stand Universal in het klein: vijf IsRelayed-tarieven zonder favoriet + één 21 %-tarief."""
    _zet_tarieven(
        administratie_id,
        _tarief(NL_HOOG, "NL, BTW verlegd (hoog)"),
        _tarief(NL_LAAG, "NL, BTW verlegd (laag)"),
        _tarief(EU_DIENSTEN_HOOG, "EU, Diensten verlegd (hoog)"),
        _tarief(EU_PRODUCTEN_HOOG, "EU, Producten verlegd (hoog)"),
        _tarief(EXEU_HOOG, "Ex EU, Diensten verlegd (hoog)"),
        _tarief(HOOG_21, "NL, Hoog Tarief", verlegd=False, favoriet=True),
    )


class TestStap1Voorkeur:
    def test_voorkeur_wint_van_historie(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, universal: None):
        _observaties(administratie_id, NL_HOOG, 5)
        btw_default.zet_verlegd_voorkeur(actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=NL_LAAG)
        keuze = _keuze(administratie_id)
        assert keuze == VerlegdKeuze(taxrate_id=NL_LAAG, herkomst=VERLEGD_HERKOMST_VOORKEUR)
        assert keuze.detail == "voorkeur beheerder"

    def test_verdwenen_voorkeur_valt_door_naar_historie(self, administratie_id: uuid.UUID, universal: None):
        _zet_tarieven(administratie_id, _tarief(uuid.UUID(int=77), "NL, Oud verlegd", verdwenen=True))
        with scoped_session(administratie_id) as session:
            from app.db.models import Administratie

            session.get(Administratie, administratie_id).voorkeurs_verlegd_taxrate_id = uuid.UUID(int=77)
        _observaties(administratie_id, EU_DIENSTEN_HOOG, 2)
        keuze = _keuze(administratie_id)
        assert keuze is not None and keuze.taxrate_id == EU_DIENSTEN_HOOG
        assert keuze.herkomst == VERLEGD_HERKOMST_HISTORIE

    def test_voorkeur_moet_verlegd_en_gesynct_zijn(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, universal: None
    ):
        with pytest.raises(btw_default.BtwDefaultOnbekendTarief):
            btw_default.zet_verlegd_voorkeur(
                actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=HOOG_21
            )
        with pytest.raises(btw_default.BtwDefaultOnbekendTarief):
            btw_default.zet_verlegd_voorkeur(
                actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=uuid.UUID(int=1234)
            )


class TestStap2Historie:
    def test_meest_gebruikt_wint_met_telling(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, NL_HOOG, 3)
        _observaties(administratie_id, NL_LAAG, 5)
        _observaties(administratie_id, HOOG_21, 40)  # geen verlegd-tarief: telt niet mee
        keuze = _keuze(administratie_id)
        assert keuze == VerlegdKeuze(taxrate_id=NL_LAAG, herkomst=VERLEGD_HERKOMST_HISTORIE, aantal=5)
        assert keuze.detail == "meest gebruikt in RLZ-historie (5×)"

    def test_gelijkspel_nl_boven_eu(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, EU_DIENSTEN_HOOG, 4)
        _observaties(administratie_id, NL_LAAG, 4)
        assert _keuze(administratie_id).taxrate_id == NL_LAAG

    def test_gelijkspel_hoog_boven_laag(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, NL_LAAG, 4)
        _observaties(administratie_id, NL_HOOG, 4)
        assert _keuze(administratie_id).taxrate_id == NL_HOOG

    def test_gelijkspel_naam_alfabetisch(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, EU_PRODUCTEN_HOOG, 2)
        _observaties(administratie_id, EU_DIENSTEN_HOOG, 2)
        _observaties(administratie_id, EXEU_HOOG, 2)
        assert _keuze(administratie_id).taxrate_id == EU_DIENSTEN_HOOG  # "eu, diensten…" < "eu, producten…" < "ex eu…"

    def test_venster_400_dagen_wint_van_oudere_historie(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, NL_LAAG, 10, dagen_terug=500)
        _observaties(administratie_id, NL_HOOG, 1, dagen_terug=10)
        keuze = _keuze(administratie_id)
        assert keuze.taxrate_id == NL_HOOG and keuze.aantal == 1

    def test_zonder_recente_historie_telt_alles_wat_er_is(self, administratie_id: uuid.UUID, universal: None):
        _observaties(administratie_id, NL_LAAG, 3, dagen_terug=500)
        keuze = _keuze(administratie_id)
        assert keuze == VerlegdKeuze(taxrate_id=NL_LAAG, herkomst=VERLEGD_HERKOMST_HISTORIE, aantal=3)


class TestStap3EnigeNlFavoriet:
    def test_enige_verlegd_code(self, administratie_id: uuid.UUID):
        _zet_tarieven(
            administratie_id, _tarief(NL_HOOG, "NL, BTW verlegd (hoog)"), _tarief(HOOG_21, "NL, Hoog", verlegd=False)
        )
        assert _keuze(administratie_id) == VerlegdKeuze(taxrate_id=NL_HOOG, herkomst=VERLEGD_HERKOMST_ENIGE)

    def test_enige_nl_verlegd_code(self, administratie_id: uuid.UUID):
        _zet_tarieven(
            administratie_id,
            _tarief(NL_HOOG, "NL, BTW verlegd (hoog)"),
            _tarief(EU_DIENSTEN_HOOG, "EU, Diensten verlegd"),
        )
        assert _keuze(administratie_id) == VerlegdKeuze(taxrate_id=NL_HOOG, herkomst=VERLEGD_HERKOMST_ENIGE_NL)

    def test_favoriet_beslist(self, administratie_id: uuid.UUID):
        _zet_tarieven(
            administratie_id,
            _tarief(NL_HOOG, "NL, BTW verlegd (hoog)"),
            _tarief(NL_LAAG, "NL, BTW verlegd (laag)", favoriet=True),
        )
        assert _keuze(administratie_id) == VerlegdKeuze(taxrate_id=NL_LAAG, herkomst=VERLEGD_HERKOMST_FAVORIET)


class TestStap4DefaultEnLeeg:
    def test_universal_zonder_historie_valt_op_de_verlegde_default(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, universal: None
    ):
        """De productie-stand 08-09: default = "NL, BTW verlegd (hoog)" — nu expliciet als herkomst, geen toeval."""
        btw_default.zet_btw_default(actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=NL_HOOG)
        assert _keuze(administratie_id) == VerlegdKeuze(taxrate_id=NL_HOOG, herkomst=VERLEGD_HERKOMST_DEFAULT)
        with scoped_session(administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=administratie_id) == NL_HOOG

    def test_niet_verlegde_default_geeft_leeg(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, universal: None
    ):
        btw_default.zet_btw_default(actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=HOOG_21)
        assert _keuze(administratie_id) is None

    def test_meerduidig_zonder_alles_is_leeg(self, administratie_id: uuid.UUID, universal: None):
        assert _keuze(administratie_id) is None

    def test_geen_verlegd_tarieven_is_leeg(self, administratie_id: uuid.UUID):
        _zet_tarieven(administratie_id, _tarief(HOOG_21, "NL, Hoog", verlegd=False))
        assert _keuze(administratie_id) is None


class TestHerkomstNaarDeRegel:
    def test_regel_draagt_detail_en_snapshot_bewaart_het(self):
        regel = BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=None,
            project_id=None,
            netto_bedrag=Decimal("100"),
            btw_bedrag=Decimal("0"),
            omschrijving="Steiger",
        )
        keuze = VerlegdKeuze(taxrate_id=NL_HOOG, herkomst=VERLEGD_HERKOMST_HISTORIE, aantal=12)
        gevuld = _met_factuur_verlegd(regel, verlegd=keuze)
        assert gevuld.taxrate_id == NL_HOOG and gevuld.btw_bron == BTW_BRON_FACTUUR_VERLEGD
        assert gevuld.btw_bron_detail == "meest gebruikt in RLZ-historie (12×)"
        assert _regel_snapshot(1, gevuld)["btw_bron_detail"] == "meest gebruikt in RLZ-historie (12×)"

    def test_regel_met_btw_of_gevuld_veld_blijft_ongemoeid(self):
        keuze = VerlegdKeuze(taxrate_id=NL_HOOG, herkomst=VERLEGD_HERKOMST_VOORKEUR)
        met_btw = BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=None,
            project_id=None,
            netto_bedrag=Decimal("100"),
            btw_bedrag=Decimal("21"),
            omschrijving=None,
        )
        assert _met_factuur_verlegd(met_btw, verlegd=keuze).taxrate_id is None
        assert _met_factuur_verlegd(met_btw, verlegd=None).btw_bron_detail is None
        gevuld = BoekvoorstelRegelData(
            ledger_id=None, taxrate_id=HOOG_21, project_id=None, netto_bedrag=None, btw_bedrag=None, omschrijving=None
        )
        assert _met_factuur_verlegd(gevuld, verlegd=keuze).taxrate_id == HOOG_21

    def test_module_exporteert_compat_naam(self):
        assert regel_prefill.verlegd_taxrate_voor is verlegd_taxrate_voor
