"""Peter 15-09: `boekvoorstel.bepaal_verlegd_basis` — (a) vermelding, (b) kolomcode, (c) verlegd-leverancier via
geheugen of KvK-SBI 41/42/43; telkens ÉN factuur-btw 0. Zonder basis blijft 0 % leeg (vrijgesteld ≠ verlegd)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten.models import CrediteurKenmerk
from app.geheugen.models import BoekingObservatie
from app.integraties import kvk
from app.sync.models import TaxRateCache, VendorCache
from tests.auth.conftest import administratie_id  # noqa: F401

VERLEGD = uuid.UUID("77777777-0000-0000-0000-000000000001")
HOOG = uuid.UUID("77777777-0000-0000-0000-000000000021")
GB = uuid.UUID("77777777-0000-0000-0000-000000000098")
VENDOR = uuid.UUID("77777777-0000-0000-0000-000000000099")


def _vv(**over) -> dict:  # noqa: ANN003
    basis = {
        "btw_bedrag": "0.00",
        "totaal_excl": "20000.00",
        "totaal_incl": "20000.00",
        "btw_verlegd_vermelding": None,
        "btw_verlegd_kolom": None,
    }
    basis.update(over)
    return basis


class TestPuur:
    def test_factuur_is_verlegd_op_vermelding_of_kolomcode_alleen_met_btw_nul(self) -> None:
        assert boekvoorstel._factuur_is_verlegd(_vv(btw_verlegd_kolom="V"))
        assert boekvoorstel._factuur_is_verlegd(_vv(btw_verlegd_vermelding="BTW verlegd"))
        assert not boekvoorstel._factuur_is_verlegd(_vv())  # 0 % zonder vermelding/kolomcode
        assert not boekvoorstel._factuur_is_verlegd(_vv(btw_verlegd_kolom="V", btw_bedrag="4200.00"))
        assert not boekvoorstel._factuur_is_verlegd(_vv(btw_verlegd_kolom="V", btw_bedrag=None, totaal_incl="24200.00"))
        assert not boekvoorstel._factuur_is_verlegd(None)

    def test_kvk_sbi_parse_en_bouw(self) -> None:
        profiel = kvk.verwerk_basisprofiel(
            {
                "naam": "Grondwerken Reeuwijk B.V.",
                "sbiActiviteiten": [{"sbiCode": "4312", "sbiOmschrijving": "Grondverzet", "indHoofdactiviteit": "Ja"}],
                "_embedded": {"hoofdvestiging": {"sbiActiviteiten": [{"sbiCode": "4312"}, {"sbiCode": "7112"}]}},
            }
        )
        assert profiel["sbi_codes"] == ["4312", "7112"]
        assert kvk.is_bouw_sbi(profiel["sbi_codes"]) and kvk.is_bouw_sbi(["41"]) and kvk.is_bouw_sbi(["4221"])
        assert not kvk.is_bouw_sbi(["6420", "7112"]) and not kvk.is_bouw_sbi([]) and not kvk.is_bouw_sbi(None)
        assert "sbi_codes" not in (kvk.verwerk_basisprofiel({"naam": "x"}) or {})


@pytest.fixture
def stamdata(administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811 — fixture-naam (leesbare tests)
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=VERLEGD,
                administratie_id=administratie_id,
                naam="NL, BTW verlegd (hoog)",
                percentage=Decimal("0"),
                brondata={"IsRelayed": True},
            )
        )
        session.add(
            TaxRateCache(
                id=HOOG,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={"IsRelayed": False, "IsFavorite": True},
            )
        )
        session.add(
            VendorCache(
                id=VENDOR,
                administratie_id=administratie_id,
                naam="Grondwerken Reeuwijk B.V.",
                brondata={"Name": "Grondwerken Reeuwijk B.V."},
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id,
                vendor_id=VENDOR,
                btw_nummer=None,
                btw_nummer_geverifieerd=None,
                btw_nummer_bron=None,
                kvk_nummer="91000073",
                kvk_nummer_bron="factuur",
            )
        )
    return administratie_id


def _basis(administratie_id: uuid.UUID, vv: dict | None, vendor: uuid.UUID | None = VENDOR):  # noqa: F811
    with scoped_session(administratie_id) as session:
        return boekvoorstel.bepaal_verlegd_basis(
            session, administratie_id=administratie_id, vendor_id=vendor, veldvoorstel=vv
        )


class TestBasisMetDb:
    def test_vermelding_wint_dan_kolomcode(self, stamdata: uuid.UUID) -> None:
        assert _basis(stamdata, _vv(btw_verlegd_vermelding="BTW verlegd", btw_verlegd_kolom="V")).soort == "vermelding"
        b = _basis(stamdata, _vv(btw_verlegd_kolom="V"))
        assert (b.soort, b.detail) == ("kolomcode", 'kolomcode "V" op alle regels')

    def test_zonder_basis_of_met_btw_blijft_none(self, stamdata: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(boekvoorstel, "_kvk_sbi_codes", lambda kvk_nummer: ["6420"])  # holding, geen bouw
        assert _basis(stamdata, _vv()) is None
        assert _basis(stamdata, _vv(btw_verlegd_kolom="V", btw_bedrag="4200.00")) is None
        assert _basis(stamdata, _vv(), vendor=None) is None
        assert _basis(stamdata, None) is None

    def test_leverancier_geheugen_maakt_nul_procent_verlegd(
        self, stamdata: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(boekvoorstel, "_kvk_sbi_codes", lambda kvk_nummer: None)
        with scoped_session(stamdata) as session:
            for i in range(2):
                session.add(
                    BoekingObservatie(
                        id=uuid.uuid4(),
                        administratie_id=stamdata,
                        vendor_id=VENDOR,
                        regel_sleutel=None,
                        regel_omschrijving_raw=f"termijn {i}",
                        gb_id=GB,
                        btw_id=VERLEGD,
                        project_id=None,
                        bron="app",
                        bron_datum=date(2026, 8, 1),
                        boekstuk_ref=None,
                    )
                )
            # een boeking op 21 % telt niet
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=stamdata,
                    vendor_id=VENDOR,
                    regel_sleutel=None,
                    regel_omschrijving_raw="materiaal",
                    gb_id=GB,
                    btw_id=HOOG,
                    project_id=None,
                    bron="app",
                    bron_datum=date(2026, 8, 2),
                    boekstuk_ref=None,
                )
            )
        b = _basis(stamdata, _vv())
        assert (b.soort, b.detail) == ("leverancier_geheugen", "leverancier eerder verlegd geboekt (2×)")

    def test_kvk_sbi_bouw_via_de_lookup_alleen_als_terugval(
        self, stamdata: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gevraagd: list[str] = []

        def nep(kvk_nummer: str) -> list[str]:
            gevraagd.append(kvk_nummer)
            return ["4312"]

        monkeypatch.setattr(boekvoorstel, "_kvk_sbi_codes", nep)
        b = _basis(stamdata, _vv())
        assert (b.soort, b.detail) == ("kvk_sbi", "KvK SBI 4312 (bouw)") and gevraagd == ["91000073"]
        # mét kolomcode wordt KvK niet geraadpleegd
        gevraagd.clear()
        assert _basis(stamdata, _vv(btw_verlegd_kolom="V")).soort == "kolomcode" and gevraagd == []

    def test_kvk_lookup_in_testomgeving_of_bij_storing_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: E501
        # code-default settings = KvK-testomgeving → de prefill raadpleegt KvK nooit (geen netwerk in tests)
        assert kvk.is_testomgeving()
        assert boekvoorstel._kvk_sbi_codes("91000073") is None
        monkeypatch.setattr(kvk, "is_testomgeving", lambda: False)
        monkeypatch.setattr(kvk, "config_probleem", lambda: None)

        def kapot(nummer: str):  # noqa: ANN202
            raise kvk.KvkFout("KvK antwoordde HTTP 500")

        monkeypatch.setattr(kvk, "haal_basisprofiel", kapot)
        assert boekvoorstel._kvk_sbi_codes("91000073") is None
        monkeypatch.setattr(kvk, "haal_basisprofiel", lambda nummer: {"naam": "x", "sbi_codes": ["4312"]})
        assert boekvoorstel._kvk_sbi_codes("91000073") == ["4312"]
