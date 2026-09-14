"""Odoo-koppelwizard nazorg 14-09 (pure logica, geen DB, geen netwerk):

- punt 1: memoriaal-dagboek OP TYPE — company-vorm A (MISC/INV/BILL, Universal 1–4), vorm B (MEM/F/LF, NL-template
  5/7/8/9), nul kandidaten, twee kandidaten; regressie company 3 (MISC náást STJ/EXCH/CABA/TAX) blijft groen;
- punt 3: tijdbudget per probe — budget op = zichtbaar "probe onderbroken (time-out na N s)", `groen` False;
- punt 4: URL-normalisatie (zes invoervormen) + foutvertaling (status + pad + één zin, nooit een exception-naam);
- failsafe laag 3: naamnormalisatie company ↔ Reeleezee-administratie; laag 2: de leesbare 409-redenen."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.odoo import probe as probe_mod
from app.odoo.client import OdooFout
from app.odoo.fouten import vertaal_verbindingsfout
from app.odoo.ids import normaliseer_odoo_url, odoo_admin_sentinel, odoo_host
from app.odoo.probe import (
    SLEUTEL_ONDERBROKEN,
    SYSTEEM_GENERAL_DAGBOEKCODES,
    is_ok,
    kies_memoriaal_dagboek,
    memoriaal_kandidaten,
    voer_probe_uit,
)
from app.odoo.service import CompanyClaim, normaliseer_administratienaam

# --- fixtures: de dagboeken zoals Peter ze 14-09 in de Odoo-UI vaststelde -------------------------------------------

SYSTEEM = [
    {"id": 11, "code": "EXCH", "name": "Koersverschillen", "type": "general"},
    {"id": 12, "code": "CABA", "name": "Kasstelsel btw", "type": "general"},
    {"id": 14, "code": "TAX", "name": "Btw-aangiften", "type": "general"},
    {"id": 36, "code": "STJ", "name": "Voorraadwaardering", "type": "general"},
]
VORM_A = [  # Universal-companies (1–4) + Camping Nieuwenhoven (10 sinds 14-09)
    {"id": 8, "code": "INV", "name": "Sales", "type": "sale"},
    {"id": 9, "code": "BILL", "name": "Purchases", "type": "purchase"},
    {"id": 13, "code": "BNK1", "name": "Bank", "type": "bank"},
    {"id": 10, "code": "MISC", "name": "Miscellaneous Operations", "type": "general"},
    *SYSTEEM,
]
VORM_B = [  # NL-template-companies (5, 7, 8, 9)
    {"id": 48, "code": "F", "name": "Verkoop", "type": "sale"},
    {"id": 49, "code": "LF", "name": "Inkoop", "type": "purchase"},
    {"id": 53, "code": "BNK1", "name": "Bank", "type": "bank"},
    {"id": 50, "code": "MEM", "name": "Memoriaal", "type": "general"},
    *SYSTEEM,
]


class FakeOdooClient:
    """Speelt de leesroutes van de probe af op een dagboekenlijst; telt calls; kan per call vertragen (budget-test)."""

    company_id = 1

    def __init__(self, journals: list[dict[str, Any]], *, klok: list[float] | None = None) -> None:
        self.journals = journals
        self.calls: list[str] = []
        self.klok = klok  # gesimuleerde monotonic-tijden (budget-test)

    def versie(self) -> dict:
        self.calls.append("versie")
        return {"server_version": "19.0+e"}

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict | None:
        self.calls.append(f"read:{model}")
        assert model == "res.company"
        return {"id": odoo_id, "name": "Testcompany", "extract_in_invoice_digitalization_mode": "no_send"}

    def has_access(self, model: str, operatie: str) -> bool:
        self.calls.append(f"has_access:{model}:{operatie}")
        return True

    def search_read(self, model: str, domain: list, fields: list[str], **kw: Any) -> list[dict]:
        self.calls.append(f"search_read:{model}")
        if model == "account.journal":
            soort = next(v for k, _, v in domain if k == "type")
            return [j for j in self.journals if j["type"] == soort]
        if model == "account.analytic.plan":
            return [{"id": 2, "name": "Project"}]
        if model == "res.users.apikeys":
            return [{"name": "N-Module", "expiration_date": False}]
        raise AssertionError(model)

    def search_count(self, model: str, domain: list) -> int:
        self.calls.append(f"search_count:{model}")
        return 16


# --- punt 1 -------------------------------------------------------------------------------------------------------


class TestMemoriaalOpType:
    def test_systeemcodes_zijn_de_vier_vastgestelde(self) -> None:
        assert set(SYSTEEM_GENERAL_DAGBOEKCODES) == {"EXCH", "CABA", "TAX", "STJ"}

    def test_vorm_a_misc_groen_met_code_in_rapport(self) -> None:
        p = voer_probe_uit(FakeOdooClient(VORM_A))  # type: ignore[arg-type]
        assert p.groen, p.rode_regels()
        assert p.journal_general_id == 10
        assert p.rapport["dagboek:memoriaal"] == "ok (memoriaal-dagboek: MISC)"
        assert (p.journal_purchase_id, p.journal_sale_id) == (9, 8)

    def test_vorm_b_mem_groen_zonder_iets_in_odoo_te_wijzigen(self) -> None:
        """Company 7 (MEM) — de module past zich aan, niet Odoo (besluit Peter 14-09)."""
        p = voer_probe_uit(FakeOdooClient(VORM_B))  # type: ignore[arg-type]
        assert p.groen, p.rode_regels()
        assert p.journal_general_id == 50
        assert p.rapport["dagboek:memoriaal"] == "ok (memoriaal-dagboek: MEM)"
        assert (p.journal_purchase_id, p.journal_sale_id) == (49, 48)

    def test_regressie_company_3_blijft_werken(self) -> None:
        """Bestaande koppeling company 3 (MISC náást de systeemdagboeken) — zelfde id als vóór 14-09."""
        p = voer_probe_uit(FakeOdooClient(VORM_A))  # type: ignore[arg-type]
        assert p.journal_general_id == 10 and is_ok(p.rapport["dagboek:memoriaal"])

    def test_nul_kandidaten_leesbaar_rood_met_codes(self) -> None:
        journals = [j for j in VORM_A if j["code"] != "MISC"]
        p = voer_probe_uit(FakeOdooClient(journals))  # type: ignore[arg-type]
        assert not p.groen and p.journal_general_id is None
        tekst = p.rapport["dagboek:memoriaal"]
        assert tekst.startswith("geen memoriaal-dagboek") and "EXCH (Koersverschillen)" in tekst
        assert "maak een memoriaal-dagboek" in tekst

    def test_twee_kandidaten_nooit_stil_de_eerste(self) -> None:
        journals = [*VORM_B, {"id": 99, "code": "MISC", "name": "Miscellaneous Operations", "type": "general"}]
        p = voer_probe_uit(FakeOdooClient(journals))  # type: ignore[arg-type]
        assert not p.groen and p.journal_general_id is None
        assert p.rapport["dagboek:memoriaal"] == (
            "meerdere memoriaal-kandidaten: MEM (Memoriaal), MISC (Miscellaneous Operations) — kies er één in Odoo "
            "(archiveer de andere) of benoem 'm"
        )

    def test_kandidaten_filter_is_hoofdletterongevoelig(self) -> None:
        rijen = [{"id": 1, "code": "exch", "name": "x"}, {"id": 2, "code": " Mem ", "name": "M"}]
        assert [r["id"] for r in memoriaal_kandidaten(rijen)] == [2]
        assert kies_memoriaal_dagboek(rijen) == (2, "ok (memoriaal-dagboek:  Mem )")

    @pytest.mark.parametrize(
        ("waarde", "verwacht"),
        [
            ("ok", True),
            ("ok (memoriaal-dagboek: MEM)", True),
            ("ok (geen lock dates)", True),
            ("okee", False),
            ("geen leesrecht", False),
            (None, False),
        ],
    )
    def test_is_ok(self, waarde: str | None, verwacht: bool) -> None:
        assert is_ok(waarde) is verwacht


# --- punt 3: tijdbudget -----------------------------------------------------------------------------------------------


class TestProbeTijdbudget:
    def test_budget_op_geeft_zichtbaar_onderbroken_rapport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tijd = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0])  # start, toets verbinding ok, daarna over budget
        monkeypatch.setattr(probe_mod.time, "monotonic", lambda: next(tijd, 100.0))
        c = FakeOdooClient(VORM_A)
        p = voer_probe_uit(c, timeout_s=45.0)  # type: ignore[arg-type]
        assert p.onderbroken and not p.groen
        assert p.rapport[SLEUTEL_ONDERBROKEN] == "probe onderbroken (time-out na 45 s) — probeer deze company los"
        assert p.rapport["verbinding"] == "ok"
        # De probe stopte ná het verbindings-/company-deel — geen dertig calls meer.
        assert not any(call.startswith("has_access") for call in c.calls)

    def test_zonder_budget_ongewijzigd(self) -> None:
        p = voer_probe_uit(FakeOdooClient(VORM_A))  # type: ignore[arg-type]
        assert not p.onderbroken and SLEUTEL_ONDERBROKEN not in p.rapport


# --- punt 4: URL-normalisatie + foutvertaling ------------------------------------------------------------------------


class TestUrlNormalisatie:
    @pytest.mark.parametrize(
        "invoer",
        [
            "https://universal-steigers.odoo.com/odoo",
            "https://universal-steigers.odoo.com/web",
            "https://universal-steigers.odoo.com/odoo/action-123?debug=1",
            "https://universal-steigers.odoo.com/",
            "https://Universal-Steigers.odoo.com/odoo/#home",
            "  universal-steigers.odoo.com  ",
        ],
    )
    def test_zes_invoervormen_worden_scheme_plus_host(self, invoer: str) -> None:
        assert normaliseer_odoo_url(invoer) == "https://universal-steigers.odoo.com"
        assert odoo_host(invoer) == "universal-steigers.odoo.com"

    def test_http_en_poort_blijven(self) -> None:
        assert normaliseer_odoo_url("http://localhost:8069/odoo") == "http://localhost:8069"

    @pytest.mark.parametrize("invoer", ["", "https://", "ftp://x.odoo.com", "https://geen host", "onzin"])
    def test_onleesbaar_is_valueerror_zonder_call(self, invoer: str) -> None:
        with pytest.raises(ValueError):
            normaliseer_odoo_url(invoer)

    def test_sentinel_negeert_pad(self) -> None:
        assert odoo_admin_sentinel("https://x.odoo.com/odoo", 6) == "odoo:x.odoo.com:6"
        assert odoo_admin_sentinel("https://x.odoo.com/", 6) == odoo_admin_sentinel("https://X.odoo.com/odoo", 6)


def _http_status(status: int, pad: str) -> httpx.HTTPStatusError:
    verzoek = httpx.Request("POST", f"https://x.odoo.com{pad}")
    return httpx.HTTPStatusError("x", request=verzoek, response=httpx.Response(status, request=verzoek))


class TestFoutvertaling:
    def test_404_op_version_info_verwijst_naar_het_domein(self) -> None:
        tekst = vertaal_verbindingsfout(_http_status(404, "/web/webclient/version_info"))
        assert (
            tekst == "404 op /web/webclient/version_info — controleer of de URL alleen het domein is "
            "(bv. https://naam.odoo.com)"
        )
        assert "HTTPStatusError" not in tekst

    def test_odoofout_404_draagt_json2_pad(self) -> None:
        exc = OdooFout(404, None, "Not Found", model="res.company", methode="search_read")
        assert vertaal_verbindingsfout(exc) == (
            "404 op /json/2/res.company/search_read — controleer of de URL alleen het domein is (bv. https://naam.odoo.com)"
        )

    def test_401_en_403_en_5xx(self) -> None:
        assert vertaal_verbindingsfout(OdooFout(401, None, "", model="res.company", methode="search_read")).startswith(
            "401 op /json/2/res.company/search_read — Odoo weigert deze API-key"
        )
        assert "mist rechten" in vertaal_verbindingsfout(
            OdooFout(403, "AccessError", "", model="account.move", methode="has_access")
        )
        assert vertaal_verbindingsfout(_http_status(503, "/web/webclient/version_info")).startswith(
            "503 op /web/webclient/version_info — Odoo geeft een serverfout"
        )

    def test_timeout_en_connect(self) -> None:
        assert (
            vertaal_verbindingsfout(httpx.ReadTimeout("x"), timeout_s=45)
            == "time-out na 45 s — Odoo antwoordde niet op tijd, probeer het opnieuw"
        )
        assert vertaal_verbindingsfout(httpx.ConnectError("nodename nor servname provided")).startswith(
            "geen verbinding met de host"
        )

    def test_onbekende_fout_nooit_klassenaam(self) -> None:
        tekst = vertaal_verbindingsfout(RuntimeError("kaboem"))
        assert "RuntimeError" not in tekst and "kaboem" in tekst

    def test_probe_verbindingsregel_gebruikt_de_vertaling(self) -> None:
        class Kapot(FakeOdooClient):
            def versie(self) -> dict:
                raise _http_status(404, "/odoo/web/webclient/version_info")

        p = voer_probe_uit(Kapot(VORM_A))  # type: ignore[arg-type]
        assert p.rapport == {
            "verbinding": "niet bereikbaar: 404 op /odoo/web/webclient/version_info — controleer of de URL alleen het "
            "domein is (bv. https://naam.odoo.com)"
        }


# --- failsafe laag 2/3: redenen en naamnormalisatie ------------------------------------------------------------------


class TestClaimRedenen:
    def _claim(self, **kw: Any) -> CompanyClaim:
        basis: dict[str, Any] = {
            "administratie_id": uuid.uuid4(),
            "administratie_naam": "Vastgoedgroep Nederland",
            "company_naam": "Vastgoedgroep Nederland B.V.",
            "migratie_doel": False,
            "alleen_lezen": False,
            "gearchiveerd": False,
        }
        basis.update(kw)
        return CompanyClaim(**basis)

    def test_migratiedoel_reden_en_label(self) -> None:
        c = self._claim(migratie_doel=True)
        assert c.reden(6) == (
            "company 6 (Vastgoedgroep Nederland B.V.) is gereserveerd als migratiedoel voor administratie "
            "‹Vastgoedgroep Nederland›"
        )
        assert c.wizard_label() == "migratiedoel (Vastgoedgroep Nederland)"

    def test_gekoppeld_reden_leesbron_en_gearchiveerd(self) -> None:
        assert self._claim(
            alleen_lezen=True, administratie_naam="Universal Verkoop", company_naam="Universal Verkoop"
        ).reden(3) == (
            "company 3 (Universal Verkoop) is al gekoppeld aan administratie ‹Universal Verkoop› "
            "(alleen-lezen leesbron)"
        )
        assert (
            self._claim(gearchiveerd=True, company_naam=None)
            .reden(1)
            .endswith(
                "‹Vastgoedgroep Nederland — gearchiveerd› — dearchiveer die administratie of wijzig háár koppeling"
            )
        )
        assert self._claim().wizard_label() == "al gekoppeld (Vastgoedgroep Nederland)"


class TestNaamnormalisatie:
    @pytest.mark.parametrize(
        ("naam", "verwacht"),
        [
            ("Vastgoedgroep Nederland B.V.", "vastgoedgroepnederland"),
            ("Vastgoedgroep Nederland", "vastgoedgroepnederland"),
            ('Caravanpark "De Visotter"', "caravanparkdevisotter"),
            ("De Visotter", "devisotter"),
            ("Universal Steigerbouw BV", "universalsteigerbouw"),
        ],
    )
    def test_normaliseer(self, naam: str, verwacht: str) -> None:
        assert normaliseer_administratienaam(naam) == verwacht
