"""Reconciliatierapport van de replay (run 2 VGG 12-09, blok 6) — markdown op stdout + JSON (`--json-uit`).

Inhoud (contract E): tellers (gelezen per collectie; geboekt/concept/huls; vertaalbaar/zonder pand/niet vertaalbaar per
move-type); saldibalans RLZ per grootboek per 31-12-2025 én per `tot` (vandaag) uit JournalEntryLines NAAST de berekende
Odoo-saldibalans uit de vertaalde moves — beide per Odoo-rekening (RLZ-ledger → Odoo via dezelfde vertaling; ongemapt
blijft
als `ongemapt:<code>` zichtbaar) → verschil per rekening, RJ 220-herclassificaties apart zodat het geschoonde verschil
telt; open posten RLZ (BaseRemainingAmount/OpenAmount ≠ 0) vs berekend uit de reconcile-paren; per pand aankoop/
aanbetalingen/kosten/verkoop/marge; tabellen niet vertaalbaar / zonder pand / ongemapte rekeningen / partners;
btw-teller;
voorstel `account.bank.statement` per maand met `balance_end_real` uit /Statements (beslispunt Peter); blok
"EXPORT juli 2025" (eerste 3 vertaalbare per type als compacte JSON). GROEN alleen als álle geschoonde verschillen 0,00,
niets niet-vertaalbaar, geen leesfouten. Geen writes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.migratie.vertaling import MoveVoorstel

NUL = Decimal("0.00")
EXPORT_TYPES = ("in_invoice", "entry", "out_invoice", "bank")
EXPORT_MAAND = "2025-07"
PEILDATUM_JAAREINDE = "2025-12-31"

BESLISPUNTEN = (
    "Statements per maand: één `account.bank.statement` per maand mét `balance_end_real` uit RLZ `/Statements` "
    "(saldocontrole gratis) — of alleen losse regels zonder statement (Odoo: 'bank statements are optional')?",
    "Bank-aanlevering ná de kanteling: A = wij schrijven statement lines (brug, dit pad) / B = Odoo-banksynchronisatie "
    "+ wij lezen (eindbeeld) — dry-run rekent A door, beslist niets.",
    "Anker in Odoo-veld `ref` als `<boekstuk> · mig:<anker>` (geen x_-veld, zoek-vóór-create op `ref ilike 'mig:…'`): "
    "akkoord dat `ref` daarmee niet meer het kale factuurnummer is? Alternatief: `invoice_origin`/`narration`.",
    "Impliciete zijden (crediteuren/debiteuren/bankrekening) hebben in de doelkoppeling nog geen Odoo-id: tot die er "
    "zijn verschijnen ze als `impliciet:…`/`bank:…` in de saldibalans en kan het rapport niet GROEN worden.",
)


@dataclass
class ReplayRapport:
    administratie_id: str
    administratie_naam: str | None
    rlz_admin_id: str | None
    gegenereerd_op: str
    tot: str
    dry_run: bool = True
    moves: list[MoveVoorstel] = field(default_factory=list)
    gelezen: dict[str, int] = field(default_factory=dict)
    fouten: list[dict[str, Any]] = field(default_factory=list)
    overgeslagen: list[str] = field(default_factory=list)
    let_op: list[str] = field(default_factory=list)
    tellers: dict[str, Any] = field(default_factory=dict)
    saldibalans: list[dict[str, Any]] = field(default_factory=list)
    herclassificaties: list[dict[str, Any]] = field(default_factory=list)
    journaal: dict[str, Any] = field(default_factory=dict)
    open_posten: list[dict[str, Any]] = field(default_factory=list)
    open_bank: list[dict[str, Any]] = field(default_factory=list)
    per_pand: list[dict[str, Any]] = field(default_factory=list)
    niet_vertaalbaar: list[dict[str, Any]] = field(default_factory=list)
    zonder_pand: list[dict[str, Any]] = field(default_factory=list)
    ongemapt: list[dict[str, Any]] = field(default_factory=list)
    partners: list[dict[str, Any]] = field(default_factory=list)
    statements: list[dict[str, Any]] = field(default_factory=list)
    export: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    export_melding: str | None = None
    doel: dict[str, Any] = field(default_factory=dict)

    # ---- oordeel ----
    @property
    def verschillen(self) -> int:
        n = sum(
            1 for r in self.saldibalans if r["verschil_jaareinde_geschoond"] != 0 or r["verschil_tot_geschoond"] != 0
        )
        n += sum(1 for r in self.open_posten if r["verschil"] != 0)
        return n

    @property
    def groen(self) -> bool:
        return (
            not self.fouten
            and not self.niet_vertaalbaar
            and self.verschillen == 0
            and int(self.tellers.get("regel_fouten", 0)) == 0
        )

    # ---- uitvoer ----
    def als_dict(self) -> dict[str, Any]:
        return {
            "administratie_id": self.administratie_id,
            "administratie_naam": self.administratie_naam,
            "rlz_admin_id": self.rlz_admin_id,
            "gegenereerd_op": self.gegenereerd_op,
            "tot": self.tot,
            "dry_run": self.dry_run,
            "groen": self.groen,
            "verschillen": self.verschillen,
            "tellers": self.tellers,
            "gelezen": dict(sorted(self.gelezen.items())),
            "fouten": self.fouten,
            "overgeslagen": self.overgeslagen,
            "let_op": self.let_op,
            "doel": self.doel,
            "saldibalans": self.saldibalans,
            "herclassificaties": self.herclassificaties,
            "journaal": self.journaal,
            "open_posten": self.open_posten,
            "open_bank": self.open_bank,
            "per_pand": self.per_pand,
            "niet_vertaalbaar": self.niet_vertaalbaar,
            "zonder_pand": self.zonder_pand,
            "ongemapt": self.ongemapt,
            "partners": self.partners,
            "statements": self.statements,
            "export": self.export,
            "export_melding": self.export_melding,
            "beslispunten": list(BESLISPUNTEN),
            "moves": [m.als_dict() for m in self.moves],
        }

    def als_json(self) -> str:
        return json.dumps(self.als_dict(), ensure_ascii=False, indent=2, default=_json_default)

    def als_markdown(self) -> str:
        return als_markdown(self)


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


# ---- markdown -------------------------------------------------------------------------------------------------------


def _md(w: object) -> str:
    if w is None or w == "":
        return "—"
    t = str(w).replace("|", "\\|").replace("\n", " ")
    return t if len(t) <= 110 else t[:107] + "…"


def _eur(b: object) -> str:
    if b is None:
        return "—"
    try:
        d = Decimal(str(b))
    except Exception:  # noqa: BLE001
        return _md(b)
    return f"€ {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tabel(regels: list[str], kop: list[str], rijen: list[list[str]], leeg: str = "_geen_") -> None:
    if not rijen:
        regels.append(leeg)
        return
    regels.append("| " + " | ".join(kop) + " |")
    regels.append("|" + "---|" * len(kop))
    regels.extend("| " + " | ".join(r) + " |" for r in rijen)


def als_markdown(r: ReplayRapport) -> str:
    L: list[str] = []
    kop = r.administratie_naam or r.administratie_id
    L.append(
        f"### VGG-replay {kop} (RLZ {r.rlz_admin_id or '?'}, DRY-RUN — niets geschreven, "
        f"tot {r.tot}, {r.gegenereerd_op})"
    )
    L.append("")
    L.append(
        f"**Oordeel: {'GROEN' if r.groen else 'ROOD'}** — {r.verschillen} verschil(len), "
        f"{len(r.niet_vertaalbaar)} niet vertaalbaar, "
        f"{len(r.fouten)} leesfout(en), {r.tellers.get('regel_fouten', 0)} document(en) zonder leesbare regels."
    )
    L.append("")
    L.append("Gelezen: " + (", ".join(f"{k} {v}" for k, v in sorted(r.gelezen.items())) or "niets") + ".")
    if r.doel:
        L.append("Doel: " + ", ".join(f"{k} {v if v is not None else '—'}" for k, v in r.doel.items()) + ".")
    for f in r.fouten:
        L.append(f"- FOUT {f['route']}: {f['status']} {f['melding']}")
    for o in r.overgeslagen:
        L.append(f"- OVERGESLAGEN {o}")
    for lo in r.let_op:
        L.append(f"- LET OP {lo}")

    t = r.tellers
    L += ["", "#### Tellers", ""]
    per_coll = t.get("per_collectie", {})
    _tabel(
        L,
        ["Collectie", "Gelezen", "Geboekt", "Concept", "Systeemhuls", "Niet migreren"],
        [
            [c, str(v["gelezen"]), str(v["geboekt"]), str(v["concept"]), str(v["huls"]), str(v["niet_migreren"])]
            for c, v in sorted(per_coll.items())
        ],
    )
    L.append("")
    per_type = t.get("per_type", {})
    _tabel(
        L,
        ["Move-type", "Vertaalbaar", "Zonder pand", "Niet vertaalbaar"],
        [
            [mt, str(v["vertaalbaar"]), str(v["zonder_pand"]), str(v["niet_vertaalbaar"])]
            for mt, v in sorted(per_type.items())
        ],
    )
    L.append("")
    L.append(
        f"Regel-calls: {t.get('regel_calls', 0)} ({t.get('regel_fouten', 0)} zonder regels). "
        f"Btw-teller: {t.get('btw_regels', 0)} regel(s) mét TaxRate/TaxAmount ≠ 0 "
        f"in {t.get('btw_documenten', 0)} document(en)"
        f"{' — moet 0 zijn (niet btw-plichtig)' if t.get('btw_regels', 0) else ' (verwacht 0: niet btw-plichtig)'}. "
        f"Partners: {t.get('partners_nieuw', 0)} nieuw (res.partner), {t.get('partners_onbekend', 0)} onbekend."
    )

    L += [
        "",
        f"#### Saldibalans RLZ (JournalEntryLines) vs berekend Odoo — per {PEILDATUM_JAAREINDE} en per {r.tot}",
        "",
    ]
    j = r.journaal
    L.append(
        f"Journaalregels: {j.get('regels', 0)} gelezen, {j.get('met_bron', 0)} met herkend brondocument/-mutatie, "
        f"{j.get('zonder_bron', 0)} zonder (informatief; koppeling via JournalEntry.EventID = aanname)."
    )
    L.append("")
    top = sorted(
        r.saldibalans, key=lambda x: -max(abs(x["verschil_jaareinde_geschoond"]), abs(x["verschil_tot_geschoond"]))
    )[:10]
    L.append("Top 10 verschillen (geschoond voor RJ 220-herclassificatie):")
    L.append("")
    kop_sb = [
        "Rekening",
        "Omschrijving",
        f"RLZ {PEILDATUM_JAAREINDE}",
        f"Odoo {PEILDATUM_JAAREINDE}",
        "Verschil",
        f"RLZ {r.tot}",
        f"Odoo {r.tot}",
        "Verschil",
    ]
    _tabel(
        L,
        kop_sb,
        [
            [
                _md(x["rekening"]),
                _md(x["omschrijving"]),
                _eur(x["rlz_jaareinde"]),
                _eur(x["odoo_jaareinde"]),
                _eur(x["verschil_jaareinde_geschoond"]),
                _eur(x["rlz_tot"]),
                _eur(x["odoo_tot"]),
                _eur(x["verschil_tot_geschoond"]),
            ]
            for x in top
            if x["verschil_jaareinde_geschoond"] != 0 or x["verschil_tot_geschoond"] != 0
        ],
        leeg="_alle verschillen 0,00_",
    )
    L += ["", "Volledige tabel:", ""]
    _tabel(
        L,
        kop_sb,
        [
            [
                _md(x["rekening"]),
                _md(x["omschrijving"]),
                _eur(x["rlz_jaareinde"]),
                _eur(x["odoo_jaareinde"]),
                _eur(x["verschil_jaareinde_geschoond"]),
                _eur(x["rlz_tot"]),
                _eur(x["odoo_tot"]),
                _eur(x["verschil_tot_geschoond"]),
            ]
            for x in r.saldibalans
        ],
    )
    if r.herclassificaties:
        L += ["", "RJ 220-herclassificaties (Odoo-kant, verplaatst van mapping-rekening naar rol-rekening):", ""]
        _tabel(
            L,
            ["Van", "Naar", "Bedrag (debet − credit)", "Documenten"],
            [[_md(h["van"]), _md(h["naar"]), _eur(h["bedrag"]), str(h["documenten"])] for h in r.herclassificaties],
        )

    L += ["", "#### Open posten — RLZ vs berekend uit reconcile-paren", ""]
    _tabel(
        L,
        ["Boekstuk", "Type", "Bedrag", "Open RLZ", "Open berekend", "Verschil"],
        [
            [
                _md(x["boekstuk"]),
                _md(x["move_type"]),
                _eur(x["bedrag"]),
                _eur(x["rlz_open"]),
                _eur(x["berekend_open"]),
                _eur(x["verschil"]),
            ]
            for x in r.open_posten
        ],
        leeg="_geen open posten en geen verschillen_",
    )
    L.append("")
    L.append(
        f"Open bankmutaties (OpenAmount ≠ 0): {len(r.open_bank)}"
        + (
            " — "
            + ", ".join(f"{x['boekstuk']} {_eur(x['open_bedrag'])}" for x in r.open_bank[:10])
            + ("…" if len(r.open_bank) > 10 else "")
            if r.open_bank
            else ""
        )
    )

    L += ["", "#### Per pand (alleen toewijzingen mens/hoog)", ""]
    _tabel(
        L,
        ["Pand", "Aankoop", "Aanbetalingen", "Kosten", "Verkoop", "Marge (verkoop − aankoop − kosten)"],
        [
            [
                _md(p["pand"]),
                _eur(p["aankoop"]),
                _eur(p["aanbetalingen"]),
                _eur(p["kosten"]),
                _eur(p["verkoop"]),
                _eur(p["marge"]) if p["marge"] is not None else "— (niet verkocht)",
            ]
            for p in r.per_pand
        ],
    )

    L += ["", f"#### Niet vertaalbaar — {len(r.niet_vertaalbaar)}", ""]
    _tabel(
        L,
        ["Boekstuk", "Type", "Datum", "Bedrag", "Reden"],
        [
            [_md(x["boekstuk"]), _md(x["move_type"]), _md(x["date"]), _eur(x["bedrag"]), _md(x["reden"])]
            for x in r.niet_vertaalbaar
        ],
    )
    L += ["", f"#### Zonder pand (voorstel midden/laag — mens beslist in de Toewijzing) — {len(r.zonder_pand)}", ""]
    _tabel(
        L,
        ["Boekstuk", "Type", "Datum", "Bedrag", "Reden"],
        [
            [_md(x["boekstuk"]), _md(x["move_type"]), _md(x["date"]), _eur(x["bedrag"]), _md(x["reden"])]
            for x in r.zonder_pand
        ],
    )
    L += ["", f"#### Ongemapte RLZ-rekeningen — {len(r.ongemapt)}", ""]
    _tabel(
        L,
        ["RLZ-code", "Naam", "Type", "Regels", "Documenten"],
        [
            [_md(x["rlz_code"]), _md(x["rlz_naam"]), _md(x["account_type"]), str(x["regels"]), str(x["documenten"])]
            for x in r.ongemapt
        ],
    )
    L += ["", f"#### Partners (voorstel zoek-vóór-create; dry-run leest Odoo niet) — {len(r.partners)}", ""]
    _tabel(
        L,
        ["Naam", "Sleutel", "KvK", "Btw", "IBAN", "Voorstel", "Documenten"],
        [
            [
                _md(p["naam"]),
                _md(p["sleutel"]),
                _md(p["kvk"]),
                _md(p["btw"]),
                _md(p["iban"]),
                _md(p["voorstel"]),
                str(p["documenten"]),
            ]
            for p in r.partners
        ],
    )

    L += ["", "#### Voorstel `account.bank.statement` per maand (balance_end_real uit /Statements — beslispunt)", ""]
    _tabel(
        L,
        ["Rekening", "Maand", "Regels", "Som regels", "Beginsaldo", "Eindsaldo (statement)", "Sluit"],
        [
            [
                _md(s["rekening"]),
                _md(s["maand"]),
                str(s["regels"]),
                _eur(s["som"]),
                _eur(s["beginsaldo"]),
                _eur(s["eindsaldo"]),
                _md(s["sluit"]),
            ]
            for s in r.statements
        ],
    )

    L += ["", "#### Beslispunten Peter (niet beslist in deze run)", ""]
    L.extend(f"{i}. {b}" for i, b in enumerate(BESLISPUNTEN, start=1))

    L += [
        "",
        f"#### EXPORT {EXPORT_MAAND} — eerste 3 vertaalbare documenten per type "
        "(input `vgg-odoo-stap0` + menselijke controle)",
        "",
    ]
    if r.export_melding:
        L.append(f"_{r.export_melding}_")
        L.append("")
    for mt in EXPORT_TYPES:
        L.append(f"**{mt}** ({len(r.export.get(mt, []))})")
        L.append("")
        L.append("```json")
        L.append(json.dumps(r.export.get(mt, []), ensure_ascii=False, default=_json_default, separators=(",", ":")))
        L.append("```")
        L.append("")
    return "\n".join(L).rstrip() + "\n"
