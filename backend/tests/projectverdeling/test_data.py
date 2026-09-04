"""Pure geldlogica projectverdeling (geen DB): verdelen cent-exact (ook negatief), vaste regels + restant,
RLZ-regelsplitsing mét sluitende btw, Odoo-percentages som exact 100, hercontrole-afwijking, OVH-herkenning,
cadans-regel en het tijd-gebonden flankerende signaal."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.odoo.inkoop import OdooInkoopPort, _Regel
from app.projecten.cijfers import ProjectCijfers, ProjectWeek
from app.projectverdeling import data as pv
from app.projectverdeling.flankerend import inkoop_zonder_omzet_weken, looptijd_weken
from app.projectverdeling.hercontrole import moet_herrekenen
from app.projectverdeling.omzet import is_ovh_project

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def standen(*omzetten: str) -> list[pv.Omzetstand]:
    ids = [A, B, C]
    return [pv.Omzetstand(project_id=ids[i], omzet=Decimal(o)) for i, o in enumerate(omzetten)]


class TestPeriode:
    def test_default_periode_is_vorige_kalendermaand(self) -> None:
        assert pv.default_periode(date(2026, 9, 4)) == date(2026, 8, 1)
        assert pv.default_periode(date(2026, 1, 15)) == date(2025, 12, 1)

    def test_periode_eind_en_label(self) -> None:
        assert pv.periode_eind(date(2026, 12, 1)) == date(2027, 1, 1)
        assert pv.periode_label(date(2026, 7, 1)) == "juli 2026"


class TestVerdelen:
    def test_pro_rato_som_exact_en_grootste_rest(self) -> None:
        delen = pv.verdeel_pro_rato(Decimal("1400.00"), standen("6000", "2500", "1500"))
        assert [d.bedrag for d in delen] == [Decimal("840.00"), Decimal("350.00"), Decimal("210.00")]
        assert sum(d.bedrag for d in delen) == Decimal("1400.00")
        assert [d.aandeel for d in delen] == [Decimal("0.600000"), Decimal("0.250000"), Decimal("0.150000")]

    def test_pro_rato_restcenten_gaan_naar_grootste_rest(self) -> None:
        delen = pv.verdeel_pro_rato(Decimal("100.00"), standen("1", "1", "1"))
        assert sorted(d.bedrag for d in delen) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]

    def test_negatief_restant_creditnota(self) -> None:
        delen = pv.verdeel_pro_rato(Decimal("-100.00"), standen("1", "1", "1"))
        assert sum(d.bedrag for d in delen) == Decimal("-100.00")
        assert all(d.bedrag < 0 for d in delen)

    def test_omzetloos_project_doet_niet_mee(self) -> None:
        delen = pv.verdeel_pro_rato(Decimal("10.00"), standen("5", "0"))
        assert len(delen) == 1 and delen[0].project_id == A

    def test_basisbedrag_alleen_regels_zonder_project(self) -> None:
        assert pv.basisbedrag_van([(None, Decimal("100")), (A, Decimal("50")), (None, Decimal("20.5"))]) == Decimal(
            "120.50"
        )
        assert pv.basisbedrag_van([(A, Decimal("50"))]) == Decimal("0.00")
        assert pv.basisbedrag_van([(None, None), (None, Decimal("5"))]) is None


class TestBereken:
    def test_vast_plus_restant_pro_rato(self) -> None:
        b = pv.bereken(
            basisbedrag=Decimal("2000.00"),
            vaste_regels=[pv.VasteRegel(project_id=B, bedrag=Decimal("600.00"))],
            pro_rato=True,
            periode=date(2026, 7, 1),
            omzetstanden=standen("6000", "2500", "1500"),
        )
        assert b.compleet and b.blokkade is None
        assert b.restant == Decimal("1400.00")
        assert sum(d.bedrag for d in b.delen) == Decimal("2000.00")
        assert [d.wijze for d in b.delen] == ["vast", "pro_rato", "pro_rato", "pro_rato"]

    def test_te_veel_vast_is_blokkerend(self) -> None:
        b = pv.bereken(
            basisbedrag=Decimal("100.00"),
            vaste_regels=[pv.VasteRegel(project_id=A, bedrag=Decimal("150.00"))],
            pro_rato=True,
            periode=date(2026, 7, 1),
            omzetstanden=standen("1"),
        )
        assert not b.compleet and "50.00 meer vast verdeeld" in (b.blokkade or "")

    def test_restant_nul_is_compleet_zonder_pro_rato(self) -> None:
        b = pv.bereken(
            basisbedrag=Decimal("100.00"),
            vaste_regels=[pv.VasteRegel(project_id=A, bedrag=Decimal("100.00"))],
            pro_rato=False,
            periode=None,
            omzetstanden=[],
        )
        assert b.compleet and b.restant == Decimal("0.00")

    def test_restant_zonder_pro_rato_is_blokkerend(self) -> None:
        b = pv.bereken(basisbedrag=Decimal("100.00"), vaste_regels=[], pro_rato=False, periode=None, omzetstanden=[])
        assert not b.compleet and "nog niet verdeeld" in (b.blokkade or "")

    def test_geen_omzet_geeft_actie_reden(self) -> None:
        leeg = pv.bereken(
            basisbedrag=Decimal("100.00"), vaste_regels=[], pro_rato=True, periode=date(2026, 7, 1), omzetstanden=[]
        )
        assert "Geen omzet in juli 2026" in (leeg.blokkade or "")
        cache_leeg = pv.bereken(
            basisbedrag=Decimal("100.00"),
            vaste_regels=[],
            pro_rato=True,
            periode=date(2026, 7, 1),
            omzetstanden=[],
            omzet_cache_leeg=True,
        )
        assert "ververs de projectcijfers" in (cache_leeg.blokkade or "")

    def test_regelbedragen_ontbreken(self) -> None:
        b = pv.bereken(
            basisbedrag=None, vaste_regels=[], pro_rato=True, periode=date(2026, 7, 1), omzetstanden=standen("1")
        )
        assert not b.compleet and "Regelbedragen ontbreken" in (b.blokkade or "")

    def test_dubbel_project_in_vaste_regels_geweigerd(self) -> None:
        with pytest.raises(pv.ProjectverdelingFout):
            pv.bereken(
                basisbedrag=Decimal("100.00"),
                vaste_regels=[pv.VasteRegel(A, Decimal("10.00")), pv.VasteRegel(A, Decimal("20.00"))],
                pro_rato=False,
                periode=None,
                omzetstanden=[],
            )

    def test_creditnota_basis_negatief(self) -> None:
        b = pv.bereken(
            basisbedrag=Decimal("-200.00"),
            vaste_regels=[pv.VasteRegel(project_id=A, bedrag=Decimal("-50.00"))],
            pro_rato=True,
            periode=date(2026, 7, 1),
            omzetstanden=standen("3", "1"),
        )
        assert b.compleet and b.restant == Decimal("-150.00")
        assert sum(d.bedrag for d in b.delen) == Decimal("-200.00")
        te_veel = pv.bereken(
            basisbedrag=Decimal("-200.00"),
            vaste_regels=[pv.VasteRegel(project_id=A, bedrag=Decimal("-250.00"))],
            pro_rato=True,
            periode=date(2026, 7, 1),
            omzetstanden=standen("3", "1"),
        )
        assert not te_veel.compleet


class TestRlzSplitsing:
    def test_regel_splitsing_netto_en_btw_sluitend(self) -> None:
        gewichten = [(A, Decimal("840.00")), (B, Decimal("950.00")), (C, Decimal("210.00"))]
        delen = pv.splits_regel(Decimal("2000.00"), Decimal("420.00"), gewichten)
        assert sum(d.netto for d in delen) == Decimal("2000.00")
        assert sum(d.btw for d in delen) == Decimal("420.00")
        assert [d.project_id for d in delen] == [A, B, C]

    def test_splitsing_met_lastige_centen(self) -> None:
        gewichten = [(A, Decimal("1")), (B, Decimal("1")), (C, Decimal("1"))]
        delen = pv.splits_regel(Decimal("10.00"), Decimal("2.10"), gewichten)
        assert sum(d.netto for d in delen) == Decimal("10.00")
        assert sum(d.btw for d in delen) == Decimal("2.10")

    def test_splitsing_zonder_btw(self) -> None:
        delen = pv.splits_regel(Decimal("10.00"), None, [(A, Decimal("1")), (B, Decimal("1"))])
        assert [d.btw for d in delen] == [Decimal("0.00"), Decimal("0.00")]

    def test_gewichten_per_project_voegt_vast_en_pro_rato_samen(self) -> None:
        delen = [
            pv.VerdeelDeel(project_id=B, wijze="vast", bedrag=Decimal("600.00")),
            pv.VerdeelDeel(project_id=A, wijze="pro_rato", bedrag=Decimal("840.00")),
            pv.VerdeelDeel(project_id=B, wijze="pro_rato", bedrag=Decimal("350.00")),
            pv.VerdeelDeel(project_id=C, wijze="pro_rato", bedrag=Decimal("0.00")),
        ]
        assert pv.gewichten_per_project(delen) == [(B, Decimal("950.00")), (A, Decimal("840.00"))]


class TestOdooPercentages:
    def test_percentages_sommen_exact_op_100(self) -> None:
        pct = pv.analytic_percentages([(A, Decimal("1")), (B, Decimal("1")), (C, Decimal("1"))])
        assert sum(p for _, p in pct) == Decimal("100.00")
        assert sorted(p for _, p in pct) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]

    def test_regel_vals_draagt_de_distributie(self) -> None:
        r = _Regel(
            naam="x",
            account_id=1,
            tax_id=None,
            netto=Decimal("10"),
            btw=Decimal("0"),
            analytic_account_id=None,
            product_id=None,
            quantity=Decimal("1"),
            price_unit=Decimal("10"),
            product_uom_id=None,
            analytic_distribution={"7": 33.33, "8": 33.33, "9": 33.34},
        )
        vals = OdooInkoopPort._regel_vals(None, r)  # type: ignore[arg-type] — methode gebruikt self niet
        assert vals["analytic_distribution"] == {"7": 33.33, "8": 33.33, "9": 33.34}
        assert abs(sum(vals["analytic_distribution"].values()) - 100) < 1e-9

    def test_regel_vals_zonder_distributie_valt_terug_op_enkel_project(self) -> None:
        r = _Regel("x", 1, None, Decimal("10"), Decimal("0"), 5, None, Decimal("1"), Decimal("10"), None)
        assert OdooInkoopPort._regel_vals(None, r)["analytic_distribution"] == {"5": 100}  # type: ignore[arg-type]


class TestHercontroleLogica:
    def test_afwijking_pct_is_max_verschil_over_restant(self) -> None:
        oud = pv.verdeel_pro_rato(Decimal("1400.00"), standen("6000", "2500", "1500"))
        nieuw = pv.verdeel_pro_rato(Decimal("1400.00"), standen("6000", "2500", "2500"))
        pct = pv.afwijking_pct(oud, nieuw, Decimal("1400.00"))
        # Venlo ging van 210,00 naar 318,18 → 108,18 / 1400 = 7,73 %
        assert pct == Decimal("7.73")
        assert pv.afwijking_pct(oud, oud, Decimal("1400.00")) == Decimal("0.00")

    def test_moet_herrekenen_cadans(self) -> None:
        aug = datetime(2026, 8, 3, 7, 0, tzinfo=UTC)
        assert moet_herrekenen(hercontrole_op=None, laatste_sync=None, vandaag=date(2026, 9, 15), forceer=False)
        assert moet_herrekenen(hercontrole_op=aug, laatste_sync=None, vandaag=date(2026, 9, 2), forceer=False)
        assert not moet_herrekenen(hercontrole_op=aug, laatste_sync=None, vandaag=date(2026, 8, 20), forceer=False)
        assert not moet_herrekenen(
            hercontrole_op=datetime(2026, 9, 1, tzinfo=UTC), laatste_sync=None, vandaag=date(2026, 9, 5), forceer=False
        )
        verse_sync = datetime(2026, 8, 20, tzinfo=UTC)
        assert moet_herrekenen(hercontrole_op=aug, laatste_sync=verse_sync, vandaag=date(2026, 8, 21), forceer=False)
        assert moet_herrekenen(hercontrole_op=aug, laatste_sync=None, vandaag=date(2026, 8, 20), forceer=True)


class TestOvh:
    @pytest.mark.parametrize(
        ("naam", "ovh"),
        [
            ("OVH · Overhead / algemene kosten", True),
            ("OVH", True),
            ("ovh - kantoor", True),
            ("Algemene overhead", True),
            ("26120 Eindhoven (BAM)", False),
            ("Overhoven Steigers 3", False),
            (None, False),
        ],
    )
    def test_is_ovh_project(self, naam: str | None, ovh: bool) -> None:
        assert is_ovh_project(naam) is ovh


def _cijfers(weken: list[tuple[int, int, str, str]]) -> ProjectCijfers:
    ws = [
        ProjectWeek(
            jaar=j,
            weeknummer=w,
            baten=Decimal(baten),
            kosten_geboekt=Decimal(kosten),
            kosten_onderweg=Decimal(0),
            onderweg_onbepaalbaar_uren=Decimal(0),
            saldo=Decimal(baten) - Decimal(kosten),
            cumulatief=Decimal(0),
        )
        for j, w, baten, kosten in weken
    ]
    return ProjectCijfers(
        project_id=A,
        project_naam="p",
        opdrachtgever=None,
        baten_geboekt=Decimal(0),
        kosten_geboekt=Decimal(0),
        uren_onderweg_bedrag=Decimal(0),
        uren_onderweg_uren=Decimal(0),
        onbepaalbaar_uren=Decimal(0),
        meerwerk_onderweg_bedrag=Decimal(0),
        onderweg_saldo=Decimal(0),
        verwachte_marge=Decimal(0),
        marge_pct=None,
        weken=ws,
        heeft_activiteit=True,
    )


class TestFlankerend:
    def test_signaal_zwijgt_binnen_de_wachttijd(self) -> None:
        # Kosten in week 34 en 35 (2026), geen omzet; eerste kostenweek start ma 17-08-2026.
        cijfers = _cijfers([(2026, 34, "0", "500"), (2026, 35, "0", "300")])
        assert inkoop_zonder_omzet_weken(cijfers, vandaag=date(2026, 9, 1), wachtweken=4) == 0
        assert inkoop_zonder_omzet_weken(cijfers, vandaag=date(2026, 9, 20), wachtweken=4) == 2
        # wachtweken 0 = oud gedrag
        assert inkoop_zonder_omzet_weken(cijfers, vandaag=date(2026, 9, 1), wachtweken=0) == 2

    def test_looptijd_uit_specificatie_wint(self) -> None:
        cijfers = _cijfers([(2026, 34, "0", "500")])
        assert looptijd_weken(cijfers, vandaag=date(2026, 9, 1), looptijd_van=date(2026, 6, 1)) == 13
        assert (
            inkoop_zonder_omzet_weken(cijfers, vandaag=date(2026, 9, 1), wachtweken=4, looptijd_van=date(2026, 6, 1))
            == 1
        )

    def test_geen_kosten_geen_signaal(self) -> None:
        cijfers = _cijfers([(2026, 34, "100", "0")])
        assert inkoop_zonder_omzet_weken(cijfers, vandaag=date(2026, 12, 1), wachtweken=4) == 0
        assert looptijd_weken(cijfers, vandaag=date(2026, 12, 1), looptijd_van=None) is None
