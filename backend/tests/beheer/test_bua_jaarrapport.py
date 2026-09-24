# ruff: noqa: F401, F811 — pytest-fixtures uit test_bua_cli (scenario, tweede_administratie) als parameters
"""BUA-jaarrapport (besluit Peter 24-09 "nee standaard 21 % btw aanhouden … liever een correctie indienen"): lees-only
CLI
`bua-jaarrapport` (module + bank; `--rlz` = JournalEntryLines alleen GET, boekjaar client-side op BookDate; geen
credential = zichtbaar "niet gemeten"), categorie BUA / kantine / sponsoring (kantine en sponsoring NIET in het
correctievoorstel), reconciliatie-stap `bua_correctie_open` (meten; niets vóór 1 december, één rij per administratie mét
BUA-btw > 0 daarna, deeplink "Rapport openen"), lees-only route mét kantoorrol + scope. Élke CLI-vorm uit het meetrecept
wordt letterlijk via `cli.main` aangeroepen (regel 19-09)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.beheer import bua_cli
from app.main import app
from app.reconciliatie import kantoorbreed, soort_stand, teksten
from app.reconciliatie.run import Bevinding, Verzamelaar
from app.rlz.credentials import GeenRlzCredentials
from app.security.tokens import create_access_token
from tests.beheer.test_bua_cli import Stam, scenario, tweede_administratie

pytestmark = pytest.mark.usefixtures("_clean_tables")
client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class FakeRlz:
    """Speelt de bewezen JournalEntryLines-vorm na: `$filter` uitsluitend `Account/id eq <guid>` (nooit een int op een
    enum-veld), `$expand=JournalEntry` mét `BookDate`; regels van een ander jaar vallen client-side af."""

    def __init__(self, regels: dict[str, list[dict]]) -> None:
        self.regels = regels
        self.calls: list[dict] = []
        self.gesloten = False

    def get(self, pad: str, *, params: dict | None = None) -> dict:
        assert pad == "JournalEntryLines"
        p = params or {}
        self.calls.append(p)
        # Alleen de bewezen vorm: een GUID achter  — nooit een int-literal (enum-guard) of een tweede voorwaarde.
        assert re.fullmatch(r"Account/id eq [0-9a-f-]{36}", p["$filter"]), p["$filter"]
        assert p["$expand"] == "JournalEntry"
        ledger = p["$filter"].split(" eq ", 1)[1]
        return {"value": list(self.regels.get(ledger, []))}

    def close(self) -> None:
        self.gesloten = True


# ---- puur ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("naam", "categorie"),
    [
        ("Representatiekosten (beperkt aftrekbaar)", "BUA"),
        ("Relatiegeschenken (beperkt aftrekbaar)", "BUA"),
        ("Personeelsfeest", "BUA"),
        ("Horecakosten", "BUA"),
        ("Kantinekosten", "kantine"),
        ("Kosten promotie/sponsoring", "sponsoring — reclame"),
        ("Sponsoring voetbalclub", "sponsoring — reclame"),
    ],
)
def test_categorie_voor_is_puur(naam: str, categorie: str) -> None:
    assert bua_cli.categorie_voor("4xxx", naam) == categorie
    assert bua_cli.categorie_voor("4xxx", naam) == bua_cli.categorie_voor("4xxx", naam)


def test_let_op_tekst_letterlijk() -> None:
    assert "€ 227-drempel per begunstigde per jaar is niet uit de boekhouding te halen" in bua_cli.LET_OP_DREMPEL
    assert "voorstel = volledige btw-som" in bua_cli.LET_OP_DREMPEL
    assert "de module past niets toe" in bua_cli.LET_OP_DREMPEL


# ---- motor per administratie ----------------------------------------------------------------------------------------


def test_jaarrapport_per_administratie_module_plus_bank_en_categorieen(scenario: tuple[Stam, Stam]) -> None:
    a, b = scenario
    ra = bua_cli.jaarrapport_voor(a.aid, "Scope-test", jaar=2026)
    per = {r.code: r for r in ra.rekeningen}
    assert set(per) == {"4510", "4508", "4014", "4503"}
    assert per["4510"].categorie == "BUA" and per["4014"].categorie == "kantine"
    assert per["4503"].categorie == "sponsoring — reclame"
    # 4510: twee geboekte module-regels btw 0,00; 4508: één geboekte bankboeking btw 10,50 → BUA-btw A = 10,50.
    assert (per["4510"].documenten, per["4510"].btw_totaal) == (2, Decimal("0.00"))
    assert (per["4508"].documenten, per["4508"].btw_totaal) == (1, Decimal("10.50"))
    assert ra.bua_btw == Decimal("10.50") and ra.correctie_voorstel == Decimal("10.50")
    assert ra.som("kantine") == Decimal("0.00") and ra.rlz_kant == "niet gemeten"
    assert per["4510"].rlz_n is None and per["4510"].rlz_btw is None
    rb = bua_cli.jaarrapport_voor(b.aid, "Tweede BV", jaar=2026)
    assert rb.bua_btw == Decimal("21.00")  # geen lek: B's 100/21 alleen bij B


def test_kantine_en_sponsoring_tellen_niet_in_het_voorstel(scenario: tuple[Stam, Stam]) -> None:
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from tests.beheer.test_bua_cli import _document

    a, _b = scenario
    # Eén extra geboekte regel op kantine (4014) en sponsoring (4503) mét btw → getoond, niet in de som.
    _document(a, SYSTEEM_ACTOR_ID, factuurdatum=date(2026, 7, 1), regels=[("4014", "100.00", "9.00")])
    _document(a, SYSTEEM_ACTOR_ID, factuurdatum=date(2026, 7, 2), regels=[("4503", "200.00", "42.00")])
    ra = bua_cli.jaarrapport_voor(a.aid, "Scope-test", jaar=2026)
    assert ra.som("kantine") == Decimal("9.00") and ra.som("sponsoring — reclame") == Decimal("42.00")
    assert ra.bua_btw == Decimal("10.50") and ra.correctie_voorstel == Decimal("10.50")


def test_rlz_kant_via_journal_entry_lines_alleen_get_en_boekjaar_client_side(scenario: tuple[Stam, Stam]) -> None:
    a, _b = scenario
    fake = FakeRlz(
        {
            str(a.gb["4510"]): [
                {
                    "DebitAmount": 100.0,
                    "CreditAmount": 0.0,
                    "VatAmount": 21.0,
                    "JournalEntry": {"BookDate": "2026-02-01T00:00:00"},
                },
                {
                    "DebitAmount": 50.0,
                    "CreditAmount": 0.0,
                    "VatAmount": 10.5,
                    "JournalEntry": {"BookDate": "2025-12-31T00:00:00"},
                },
                {
                    "DebitAmount": 0.0,
                    "CreditAmount": 20.0,
                    "VatAmount": -4.2,
                    "JournalEntry": {"BookDate": "2026-03-01T00:00:00"},
                },
            ]
        }
    )
    ra = bua_cli.jaarrapport_voor(a.aid, "Scope-test", jaar=2026, rlz=True, rlz_client_voor=lambda aid: fake)
    per = {r.code: r for r in ra.rekeningen}
    assert (per["4510"].rlz_n, per["4510"].rlz_netto, per["4510"].rlz_btw) == (2, "80.00", "16.80"), ra.rlz_kant
    assert (per["4508"].rlz_n, per["4508"].rlz_btw) == (0, "0.00")
    assert ra.rlz_kant.startswith("gemeten") and fake.gesloten
    assert len(fake.calls) == 4 and all(c["$top"] == "200" for c in fake.calls)


def test_rlz_zonder_credential_is_zichtbaar_niet_gemeten_geen_fout(scenario: tuple[Stam, Stam]) -> None:
    a, _b = scenario

    def geen(aid: uuid.UUID):  # noqa: ANN202
        raise GeenRlzCredentials("geen webservice-login voor deze administratie")

    ra = bua_cli.jaarrapport_voor(a.aid, "Scope-test", jaar=2026, rlz=True, rlz_client_voor=geen)
    assert ra.rlz_kant.startswith("niet gemeten (geen RLZ-verbinding: geen webservice-login")
    assert ra.bua_btw == Decimal("10.50") and all(r.rlz_n is None for r in ra.rekeningen)


# ---- CLI: élke vorm uit het meetrecept letterlijk -------------------------------------------------------------------


def test_cli_bua_jaarrapport_alle_vormen_uit_het_meetrecept(
    scenario: tuple[Stam, Stam], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _b = scenario
    # Vorm 1 — de nameting-workflow: kantoorbreed.
    assert cli.main(["bua-jaarrapport", "--jaar", "2026"]) == 0
    uit = capsys.readouterr().out
    assert "BUA-jaarrapport 2026 — 2 administratie(s)" in uit and "RLZ-kant niet gemeten (--rlz)" in uit
    assert (
        "TOTAAL 2 administratie(s) mét BUA-btw van 2 · BUA-btw € 31.50 · voorstel correctie € 31.50 · kantine € 0.00 · "
        "sponsoring € 0.00 · fouten 0"
    ) in uit
    assert bua_cli.LET_OP_DREMPEL in uit and "correctie laatste aangifte (voorstel) € 10.50" in uit
    assert "sponsoring — reclame" in uit and "kantine" in uit
    # Vorm 2 — één administratie op naamdeel.
    assert cli.main(["bua-jaarrapport", "--jaar", "2026", "--administratie", "Tweede"]) == 0
    uit = capsys.readouterr().out
    assert "1 administratie(s)" in uit and "TOTAAL 1 administratie(s) mét BUA-btw van 1 · BUA-btw € 21.00" in uit
    # Vorm 3 — JSON op uuid.
    assert cli.main(["bua-jaarrapport", "--jaar", "2026", "--administratie", str(a.aid), "--json-uit"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["jaar"] == 2026 and data["administraties"] == 1 and data["fouten"] == []
    [adm] = data["per_administratie"]
    assert adm["bua_btw"] == "10.50" and adm["correctie_voorstel"] == "10.50" and adm["rlz_kant"] == "niet gemeten"
    assert {r["code"]: r["categorie"] for r in adm["rekeningen"]}["4503"] == "sponsoring — reclame"
    assert data["let_op"] == bua_cli.LET_OP_DREMPEL and data["totaal"].startswith("TOTAAL 1 administratie(s)")
    # Vorm 4 — --rlz mét fake client (alleen GET) …
    fake = FakeRlz(
        {
            str(a.gb["4508"]): [
                {
                    "DebitAmount": 10.0,
                    "CreditAmount": 0.0,
                    "VatAmount": 2.1,
                    "JournalEntry": {"BookDate": "2026-01-05T00:00:00"},
                }
            ]
        }
    )
    monkeypatch.setattr(bua_cli, "_rlz_client_voor", lambda aid: fake)
    assert cli.main(["bua-jaarrapport", "--jaar", "2026", "--rlz", "--administratie", str(a.aid)]) == 0
    uit = capsys.readouterr().out
    assert "RLZ-kant gelezen via JournalEntryLines (alleen GET)" in uit and "RLZ-kant: gemeten" in uit
    assert "2.10" in uit and fake.gesloten

    # … en --rlz zonder credential = zichtbaar, exit 0.
    def geen(aid: uuid.UUID):  # noqa: ANN202
        raise GeenRlzCredentials("geen login")

    monkeypatch.setattr(bua_cli, "_rlz_client_voor", geen)
    assert cli.main(["bua-jaarrapport", "--jaar", "2026", "--rlz"]) == 0
    uit = capsys.readouterr().out
    assert uit.count("niet gemeten (geen RLZ-verbinding: geen login)") == 2 and "fouten 0" in uit
    # Onbekende administratie = exit 2, zichtbaar.
    assert cli.main(["bua-jaarrapport", "--administratie", "bestaat-niet-xyz"]) == 2
    assert "onbekend" in capsys.readouterr().err


def test_kapotte_administratie_stopt_de_rest_niet(scenario: tuple[Stam, Stam], monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = scenario
    echte = bua_cli.jaarrapport_voor

    def kapot(aid: uuid.UUID, naam: str, **kw):  # noqa: ANN003, ANN202
        if aid == a.aid:
            raise RuntimeError("scope stuk")
        return echte(aid, naam, **kw)

    monkeypatch.setattr(bua_cli, "jaarrapport_voor", kapot)
    rapport = bua_cli.meet_jaarrapport(administratie=None, jaar=2026)
    assert rapport is not None and len(rapport.fouten) == 1 and "scope stuk" in rapport.fouten[0]
    assert [x.administratie_id for x in rapport.per_administratie] == [str(b.aid)]
    assert bua_cli.jaarrapport_totaal(rapport).endswith("fouten 1")


# ---- reconciliatie-stap `bua_correctie_open` -------------------------------------------------------------------------


def test_soort_bua_correctie_open_start_in_meten_blok_documenten() -> None:
    d = soort_stand.REGISTRY["bua_correctie_open"]
    assert (d.blok, d.default, d.sinds) == ("documenten", soort_stand.METEN, date(2026, 9, 24))
    assert soort_stand.code_default("bua_correctie_open") == "meten"
    b = Bevinding("documenten", "afwijking", None, "v", "t", {"afwijking_soort": "bua_correctie_open"})
    assert soort_stand.in_meting(b, None)


def test_stap_doet_niets_voor_1_december(scenario: tuple[Stam, Stam]) -> None:
    uit: list[str] = []
    v = Verzamelaar()
    v.start_blok("documenten")
    assert bua_cli.reconciliatie_stap(v, stdout=uit.append, vandaag=date(2026, 11, 30)) == 0
    assert v.bevindingen == [] and uit == ["BUA-jaarcorrectie: nog niet aan de orde (pas vanaf 1 december 2026)"]


def test_stap_vanaf_1_december_een_rij_per_administratie_met_bua_btw(scenario: tuple[Stam, Stam]) -> None:
    a, b = scenario
    uit: list[str] = []
    v = Verzamelaar()
    v.start_blok("documenten")
    assert bua_cli.reconciliatie_stap(v, stdout=uit.append, vandaag=date(2026, 12, 1)) == 2
    assert len(v.bevindingen) == 2 and v.blokken["documenten"].afwijkingen == 2
    per = {x.administratie_id: x for x in v.bevindingen}
    ba = per[a.aid]
    assert ba.blok == "documenten" and ba.soort == "afwijking"
    assert ba.vingerafdruk == f"documenten:{a.aid}:bua_correctie_open:2026"
    assert ba.detail["afwijking_soort"] == "bua_correctie_open" and ba.detail["btw_som"] == "10.50"
    assert ba.detail["jaar"] == 2026 and ba.detail["kantine_btw"] == "0.00"
    assert [r["code"] for r in ba.detail["rekeningen"]] == ["4508"]  # alleen rekeningen mét btw ≠ 0
    assert per[b.aid].detail["btw_som"] == "21.00"
    assert any("2 administratie(s) mét BUA-btw > 0 · 0 fout(en)" in r for r in uit)
    # Leesbare tekst zonder GUID's + handeling "Rapport openen" = deeplink naar het blok op de tab Boeken & AI.
    lees = teksten.leesbaar(ba, administratie_naam="Scope-test")
    assert lees.titel.startswith("BUA-correctie 2026 nog te beoordelen") and "€ 10,50" in lees.wat
    assert "BUA-jaarrapport" in lees.doe and not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)

    class _B:
        blok = "documenten"
        administratie_id = a.aid
        detail = ba.detail

    assert kantoorbreed._doel_pad(_B()) == f"/instellingen/administraties/{a.aid}?tab=boeken-ai#bua-jaarrapport"  # noqa: SLF001
    # Lees-only (verzamelaar None): dezelfde regels, niets vastgelegd.
    uit2: list[str] = []
    assert bua_cli.reconciliatie_stap(None, stdout=uit2.append, vandaag=date(2026, 12, 15)) == 2
    assert sum("soort=bua_correctie_open" in r for r in uit2) == 2


def test_documenten_blok_roept_de_stap_aan_zonder_rlz(monkeypatch: pytest.MonkeyPatch) -> None:
    """De stap hangt aan het einde van `_reconciliatie` (blok documenten); een fout erin is zichtbaar, geen crash."""
    import argparse

    from app.documenten import reconciliatie as rec_service
    from app.documenten import storno_detectie

    monkeypatch.setattr(rec_service, "reconcilieer_alle_administraties", lambda: {})
    monkeypatch.setattr(storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
    aangeroepen: list[object] = []
    monkeypatch.setattr(bua_cli, "reconciliatie_stap", lambda verzamelaar, **kw: aangeroepen.append(verzamelaar) or 0)
    assert cli._reconciliatie(argparse.Namespace(), verzamelaar=None) == 0  # noqa: SLF001
    assert aangeroepen == [None]

    def kapot(verzamelaar, **kw):  # noqa: ANN001, ANN003, ANN202
        raise RuntimeError("stuk")

    monkeypatch.setattr(bua_cli, "reconciliatie_stap", kapot)
    v = Verzamelaar()
    v.start_blok("documenten")
    assert cli._reconciliatie(argparse.Namespace(), verzamelaar=v) == 1  # noqa: SLF001
    assert [b.soort for b in v.bevindingen] == ["fout"] and "BUA-jaarcorrectie viel om" in v.bevindingen[0].tekst


# ---- route -----------------------------------------------------------------------------------------------------------


def test_route_bua_jaarrapport_kantoorrol_met_scope_en_404(
    scenario: tuple[Stam, Stam], beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
) -> None:
    a, _b = scenario
    r = client.get(f"/administraties/{a.aid}/bua-jaarrapport?jaar=2026", headers=_bearer(beheerder_id, rol="beheerder"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jaar"] == 2026 and data["bua_btw"] == "10.50" and data["correctie_voorstel"] == "10.50"
    assert data["let_op"] == bua_cli.LET_OP_DREMPEL and data["rlz_kant"] == "niet gemeten"
    assert {x["code"] for x in data["rekeningen"]} == {"4510", "4508", "4014", "4503"}
    # Boekhouding mét scope op déze administratie leest óók (lees-only, geen Beheerder-only).
    r2 = client.get(f"/administraties/{a.aid}/bua-jaarrapport", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
    assert r2.status_code == 200 and r2.json()["jaar"] == 2026
    # Onbekende administratie = 404 (Beheerder), buiten scope = 403 (boekhouding).
    vreemd = uuid.uuid4()
    assert (
        client.get(
            f"/administraties/{vreemd}/bua-jaarrapport", headers=_bearer(beheerder_id, rol="beheerder")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/administraties/{vreemd}/bua-jaarrapport", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        ).status_code
        == 403
    )
