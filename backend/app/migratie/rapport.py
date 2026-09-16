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
niets niet-vertaalbaar, geen leesfouten. Geen writes.

Blok 7c 13-09: oordeel **"ONVOLLEDIG — niet doorrekenen"** zodra ≥ 1 geboekt document geen leesbare regels heeft
(lijst `onvolledig`; saldibalans/open posten/per pand/statements/btw/export ontbreken dan bewust). Saldibalans:
rekeningen in een afletter-/tegenzijde-GROEP (crediteuren, debiteuren, bank, tussenrekening — `afletter_groepen`)
tellen niet per rekening maar per groep in het oordeel (de dry-run simuleert geen reconcile; keuze (b) van punt 7).
Per pand: aankoop/kosten/ verkoop uit grootboek-regels, notaris-ontvangst apart (alleen bank), controle + signalen.
Partners: teller "uit bankmutatie" + BESLISPUNT Peter voor de rest. Btw: tweede bron (journaalregels op btw-
grootboeken) + btw-code-zonder- bedrag. Journaal: per DocumentType journaalposten ↔ geboekte documenten (er is geen
koppeling per regel)."""

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
    "Statements per maand (besloten JA, 12-09; VORM blok 7b 13-09): RLZ heeft voor VGG géén /Statements-koppen → één "
    "`account.bank.statement` per maand per journal met `balance_end_real` = lopend saldo berekend uit de "
    "PaymentTransactions (beginsaldo 0 bij start administratie). Toets: het berekende saldo per 31-12-2025 en per "
    "vandaag (tabel 'Saldo-toets') naast het echte banksaldo leggen — Peter.",
    "Bank-aanlevering ná de kanteling: B (Odoo-banksynchronisatie) als eindbeeld, A (wij leveren statement lines) als "
    "brug — vastgelegd 12-09, dry-run rekent A door.",
    "Anker (BESLIST 13-09, advies overgenomen): facturen `ref` = kaal RLZ-factuur-/boekstuknummer + `mig:<anker>` in "
    "`invoice_origin`; memorialen anker in `ref`; bankregels `unique_import_id`. Zoek-vóór-create per type.",
    "Impliciete zijden (crediteuren/debiteuren/bankrekening) hebben in de doelkoppeling nog geen Odoo-id: tot die er "
    "zijn verschijnen ze als `impliciet:…`/`bank:…` in de saldibalans en kan het rapport niet GROEN worden.",
    "Verrekening factuur↔creditnota: het paar is AFGELEID uit bedrag + relatie (RLZ open 0, berekend ±X); de RLZ-"
    "leesroute van actie 34 is niet bewezen — STAP-0 via `rlz-lezen` op zo'n document (PaymentTermList/expand) "
    "als Peter het spoor uit RLZ zelf wil.",
    "Partners zonder Entity én zonder bankmutatie (BESLIST 14-09, blok 7d punt 6): GEEN dummy-partner 'Bank-direct "
    "(onbekend)' — het document blijft een GEBLOKKEERD concept met reden 'partner onbekend — toewijzen in Toewijzing' "
    "tot een mens de partner geeft (tabel 'Geblokkeerd — partner onbekend'; teller `geblokkeerd_partner`).",
    "Per-pand-controle 'sluit' (BESLIST 14-09, blok 7d punt 5): GO-eis bij SCHRIJF c, niet bij SCHRIJF a; zonder "
    "doelkoppeling toont het rapport de stand 'niet meetbaar — doelkoppeling ontbreekt'; bedragen met zekerheid "
    "'midden' blijven buiten de sommen (mens wint) — het rapport zegt per pand hoeveel er op de Toewijzing wachten.",
)
ONVOLLEDIG_OORDEEL = "ONVOLLEDIG — niet doorrekenen"
GROEN_ZONDER_DOEL = "GROEN ZONDER DOEL"
NIET_MEETBAAR_TEKST = "niet meetbaar — doelkoppeling ontbreekt"


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
    # ---- blok 7b 13-09 ----
    blokkering: str | None = None  # webfilter-403 midden in de run → niets doorgerekend (punt 1c)
    verrekeningen: list[dict[str, Any]] = field(default_factory=list)  # factuur↔creditnota-paren (punt 4)
    som_verschillen: list[dict[str, Any]] = field(default_factory=list)  # Σ regels ≠ documenttotaal (punt 4)
    saldo_toets: list[dict[str, Any]] = field(default_factory=list)  # berekend banksaldo per journal (punt 3)
    btw: dict[str, Any] = field(default_factory=dict)  # afwikkelrol: afmeldingsdatum + restsaldo (besluit 13-09)
    # ---- blok 7c 13-09 ----
    onvolledig: list[dict[str, Any]] = field(default_factory=list)  # geboekte documenten zonder leesbare regels
    afletter_groepen: list[dict[str, Any]] = field(default_factory=list)  # groepstoets (punt 7, keuze b)
    # ---- blok 7d 14-09 ----
    doel_afwezig: bool = False  # punt 5: doelkoppeling/rekeningmapping ontbreekt → derde stand "GROEN ZONDER DOEL"
    uit_balans: list[dict[str, Any]] = field(default_factory=list)  # punt 1: memorialen Σ debet ≠ Σ credit
    resultaatposten: dict[str, Any] = field(default_factory=dict)  # punt 3: DocumentType 0 buiten de toets
    betalingsverschillen: list[dict[str, Any]] = field(default_factory=list)  # punt 4: write-offs
    geblokkeerd: list[dict[str, Any]] = field(default_factory=list)  # punt 6: partner onbekend
    # ---- blok 8 15-09 ----
    expliciete_mapping: list[dict[str, Any]] = field(default_factory=list)  # tabel rekening_mapping (1012, 1001)
    model_1001: dict[str, Any] = field(default_factory=dict)  # blok 9 16-09: SCHRIJF b — 1001-model per memoriaalregel

    # ---- oordeel ----
    @property
    def verschillen(self) -> int:
        """Rekeningen buiten een groep per rekening; groepsleden alleen op groepsniveau (blok 7c punt 7 b). Zonder
        doelkoppeling (blok 7d punt 5) is de groepstoets 'niet meetbaar' en telt hij niet."""
        n = sum(
            1
            for r in self.saldibalans
            if r.get("groep") is None and (r["verschil_jaareinde_geschoond"] != 0 or r["verschil_tot_geschoond"] != 0)
        )
        if not self.doel_afwezig:
            n += sum(
                1 for g in self.afletter_groepen if (g["verschil_jaareinde"] or 0) != 0 or (g["verschil_tot"] or 0) != 0
            )
        n += sum(1 for r in self.open_posten if r["verschil"] != 0)
        return n

    @property
    def onvolledig_oordeel(self) -> bool:
        return self.blokkering is None and (bool(self.onvolledig) or int(self.tellers.get("regel_fouten", 0)) > 0)

    @property
    def memoriaal_uit_balans(self) -> int:
        return int(self.tellers.get("memoriaal_uit_balans", 0)) or len(self.uit_balans)

    @property
    def resultaat_sluit(self) -> bool:
        """Blok 7d punt 3: leeg blok (geen DocumentType-0-posten) telt als sluitend."""
        return bool(self.resultaatposten.get("sluit", True))

    @property
    def _basis_groen(self) -> bool:
        """De toetsen die in élke stand moeten kloppen (doel-onafhankelijk)."""
        return (
            self.blokkering is None
            and not self.onvolledig_oordeel
            and not self.fouten
            and self.verschillen == 0
            and not self.som_verschillen
            and self.memoriaal_uit_balans == 0
            and self.resultaat_sluit
        )

    @property
    def groen(self) -> bool:
        return self._basis_groen and not self.doel_afwezig and not self.niet_vertaalbaar

    @property
    def groen_zonder_doel(self) -> bool:
        """Blok 7d punt 5: alle doel-onafhankelijke toetsen groen; alleen documenten die UITSLUITEND door de ontbrekende
        doelkoppeling (mapping/rol) of de partner-blokkade niet vertaalbaar zijn mogen overblijven."""
        return self.doel_afwezig and self._basis_groen and int(self.tellers.get("niet_vertaalbaar_overig", 0)) == 0

    @property
    def oordeel(self) -> str:
        if self.blokkering:
            return "ROOD — RLZ-blokkering — meting ongeldig"
        if self.onvolledig_oordeel:
            return ONVOLLEDIG_OORDEEL
        if self.groen:
            return "GROEN"
        if self.groen_zonder_doel:
            return f"{GROEN_ZONDER_DOEL} — groepstoets en per pand {NIET_MEETBAAR_TEKST}"
        return "ROOD"

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
            "groen_zonder_doel": self.groen_zonder_doel,
            "doel_afwezig": self.doel_afwezig,
            "oordeel": self.oordeel,
            "blokkering": self.blokkering,
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
            "saldo_toets": self.saldo_toets,
            "verrekeningen": self.verrekeningen,
            "som_verschillen": self.som_verschillen,
            "btw": self.btw,
            "onvolledig": self.onvolledig,
            "afletter_groepen": self.afletter_groepen,
            "uit_balans": self.uit_balans,
            "resultaatposten": self.resultaatposten,
            "betalingsverschillen": self.betalingsverschillen,
            "geblokkeerd": self.geblokkeerd,
            "expliciete_mapping": self.expliciete_mapping,
            "model_1001": self.model_1001,
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


def _of(w: object) -> str:
    return "—" if w is None else str(w)


def _tabel(regels: list[str], kop: list[str], rijen: list[list[str]], leeg: str = "_geen_") -> None:
    if not rijen:
        regels.append(leeg)
        return
    regels.append("| " + " | ".join(kop) + " |")
    regels.append("|" + "---|" * len(kop))
    regels.extend("| " + " | ".join(r) + " |" for r in rijen)


def _model_1001_sectie(L: list[str], r: ReplayRapport) -> None:
    """Blok 9 16-09 (SCHRIJF b): per memoriaal-1001-regel boekstuk, bedrag, gekozen bestemming en bewijs."""
    m = r.model_1001 or {}
    t = m.get("tellers") or {}
    L += [
        "",
        f"#### 1001-model (blok 9, SCHRIJF b — `app/migratie/model_1001.py`) — {t.get('regels_1001', 0)} "
        f"memoriaal-1001-regel(s): {t.get('gekoppeld', 0)} gekoppeld → outstanding BNK1 "
        f"({t.get('via_koppeling', 0)} via PaymentReferenceList, {t.get('via_bedrag_datum', 0)} via bedrag + datum "
        f"± {m.get('venster_dagen', 3)} d), {t.get('geen_bankmutatie', 0)} zonder bankmutatie → tussenrekening, "
        f"{t.get('meerduidig', 0)} meerduidig → tussenrekening (niet toegewezen)",
        "",
    ]
    if m:
        stand = "bekend" if t.get("outstanding_bekend") else "NIET ingesteld — KLIKPUNT PETER"
        codes = ", ".join(m.get("bank_ledger_codes") or []) or "—"
        L.append(
            f"Outstanding-rekening BNK1: {stand} (sleutel {t.get('outstanding_sleutel')}); "
            f"bankgrootboeken RLZ: {codes}."
            + (f" Melding: {m.get('outstanding_melding')}" if m.get("outstanding_melding") else "")
        )
        L.append("")
    _tabel(
        L,
        [
            "Boekstuk",
            "Regel",
            "Datum",
            "Bedrag (debet − credit)",
            "Uitkomst",
            "Bestemming",
            "Bewijs",
            "Mutatie",
            "Δ dagen",
            "Kandidaten",
            "Reden",
        ],
        [
            [
                _md(x["boekstuk"]),
                str(x["regel"]),
                _md(x["datum"]),
                _eur(x["bedrag"]),
                _md(x["uitkomst"]),
                _md(x["bestemming"]),
                _md(x.get("bewijs")),
                _md(f"{x['mutatie']} ({x['mutatie_datum']})" if x.get("mutatie") else None),
                _of(x.get("dagen_verschil")),
                str(x.get("kandidaten", 0)),
                _md(x.get("reden")),
            ]
            for x in (m.get("regels") or [])
        ],
        leeg="_geen memoriaalregels op een bankgrootboek_",
    )


def als_markdown(r: ReplayRapport) -> str:
    L: list[str] = []
    kop = r.administratie_naam or r.administratie_id
    L.append(
        f"### VGG-replay {kop} (RLZ {r.rlz_admin_id or '?'}, DRY-RUN — niets geschreven, "
        f"tot {r.tot}, {r.gegenereerd_op})"
    )
    L.append("")
    L.append(
        f"**Oordeel: {r.oordeel}** — {r.verschillen} verschil(len), "
        f"{len(r.niet_vertaalbaar)} niet vertaalbaar"
        + (
            f" (waarvan {r.tellers.get('niet_vertaalbaar_doel', 0)} alleen door de ontbrekende doelkoppeling, "
            f"{r.tellers.get('niet_vertaalbaar_overig', 0)} overig)"
            if r.doel_afwezig
            else ""
        )
        + f", {len(r.fouten)} leesfout(en), {r.tellers.get('regel_fouten', 0)} document(en) zonder leesbare regels, "
        f"{len(r.som_verschillen)} regelsom ≠ totaal, memoriaal uit balans {r.memoriaal_uit_balans}, "
        f"resultaatposten {'sluiten' if r.resultaat_sluit else 'SLUITEN NIET'}, "
        f"betalingsverschillen {len(r.betalingsverschillen)}, geblokkeerd (partner) "
        f"{r.tellers.get('geblokkeerd_partner', 0)}."
    )
    L.append("")
    if r.blokkering:
        L.append(f"**RLZ-blokkering — meting ongeldig:** {_md(r.blokkering)}")
        L.append("")
    L.append("Gelezen: " + (", ".join(f"{k} {v}" for k, v in sorted(r.gelezen.items())) or "niets") + ".")
    t0 = r.tellers
    L.append(
        f"RLZ-calls: {_of(t0.get('rlz_calls'))} (webfilter-treffers hervat: {_of(t0.get('webfilter_treffers'))}, "
        f"gewacht {_of(t0.get('gewacht_seconden'))} s); "
        f"regels per document: {t0.get('regel_calls', 0)} calls — {t0.get('regels_via_documentvorm', 0)} via de "
        f"document-vorm (kop mét BookDate + DocumentLineList), {t0.get('regels_via_lines', 0)} via /Lines-terugval, "
        f"{t0.get('regel_fouten', 0)} zonder regels. BookDate: {t0.get('bookdate_uit_document', 0)} documenten uit het "
        f"document, {t0.get('bookdate_terugval_date', 0)} terugval op Date."
    )
    if r.doel:
        L.append("Doel: " + ", ".join(f"{k} {v if v is not None else '—'}" for k, v in r.doel.items()) + ".")
    for f in r.fouten:
        L.append(f"- FOUT {f['route']}: {f['status']} {f['melding']}")
    for o in r.overgeslagen:
        L.append(f"- OVERGESLAGEN {o}")
    for lo in r.let_op:
        L.append(f"- LET OP {lo}")
    if r.blokkering:
        L.append("")
        L.append("_Niets doorgerekend: saldibalans, open posten, per pand en export ontbreken bewust (halve data)._")
        return "\n".join(L).rstrip() + "\n"
    if r.onvolledig:
        L += ["", f"#### {ONVOLLEDIG_OORDEEL} — {len(r.onvolledig)} geboekt(e) document(en) zonder leesbare regels", ""]
        L.append(
            "_Geen saldibalans-toets, open posten, per pand, statements, btw of export op halve regel-data. Eerst de "
            "regelroute herstellen (rlz_bron.regel_routes), dan opnieuw meten._"
        )
        L.append("")
        _tabel(
            L,
            ["Boekstuk", "Type", "Datum", "Bedrag", "Route (letterlijk RLZ-antwoord)"],
            [
                [_md(x["boekstuk"]), _md(x["move_type"]), _md(x["date"]), _eur(x["bedrag"]), _md(x["route"])]
                for x in r.onvolledig
            ],
        )

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
        ["Move-type", "Vertaalbaar", "Zonder pand", "Niet vertaalbaar", "Geblokkeerd (partner)"],
        [
            [mt, str(v["vertaalbaar"]), str(v["zonder_pand"]), str(v["niet_vertaalbaar"]), str(v.get("geblokkeerd", 0))]
            for mt, v in sorted(per_type.items())
        ],
    )
    L.append("")
    L.append(
        f"Btw-teller: {t.get('btw_regels', 0)} regel(s) mét TaxAmount ≠ 0 in {t.get('btw_documenten', 0)} document(en) "
        "→ allemaal als balansregel naar 'Btw-afwikkeling historisch' zonder tax_ids (besluit Peter 13-09: VGG niet "
        f"btw-plichtig, foute registratie Belastingdienst); {t.get('btw_code_zonder_bedrag', 0)} regel(s) dragen een "
        "btw-code (TaxRate) met bedrag 0 — dat was de teller van blok 7 (883), geen btw."
    )
    L.append(
        f"Partners: {t.get('partners_nieuw', 0)} nieuw (res.partner), waarvan {t.get('partners_uit_bank', 0)} uit de "
        f"tegenpartij van de bankmutatie (naam + IBAN); {t.get('partners_onbekend', 0)} onbekend (geen Entity, geen "
        "bankmutatie) → geblokkeerd concept 'partner onbekend — toewijzen in Toewijzing' (besluit Peter 14-09: geen "
        "dummy-partner)."
    )
    if r.uit_balans or r.tellers.get("memoriaal_uit_balans"):
        L += ["", f"#### Memoriaal uit balans — {len(r.uit_balans)} (blok 7d punt 1: Σ debet ≠ Σ credit → ROOD)", ""]
        _tabel(
            L,
            ["Boekstuk", "Datum", "Bedrag", "Σ debet − Σ credit", "Reden"],
            [
                [_md(x["boekstuk"]), _md(x["date"]), _eur(x["bedrag"]), _eur(x["uit_balans"]), _md(x["reden"])]
                for x in r.uit_balans
            ],
        )
    if r.geblokkeerd:
        L += [
            "",
            f"#### Geblokkeerd — partner onbekend — {len(r.geblokkeerd)} (besluit Peter 14-09: geen dummy-partner)",
            "",
        ]
        _tabel(
            L,
            ["Boekstuk", "Type", "Datum", "Bedrag", "Blokkade", "Reden"],
            [
                [
                    _md(x["boekstuk"]),
                    _md(x["move_type"]),
                    _md(x["date"]),
                    _eur(x["bedrag"]),
                    _md(x["blokkade"]),
                    _md(x["reden"]),
                ]
                for x in r.geblokkeerd
            ],
        )
    b = r.btw
    if b:
        L += ["", "#### Btw-afwikkeling historisch (besluit Peter 13-09)", ""]
        rol = b.get("rol_ingesteld")
        rol_tekst = (
            f"Odoo account {rol}"
            if rol is not None
            else "NIET ingesteld (vgg-rekeningen --maak-aan, stap 2a) — documenten mét btw tot dan niet vertaalbaar"
        )
        L.append(f"- Rol-rekening: {rol_tekst}")
        L.append(
            f"- Btw-regels: {b.get('btw_regels', 0)} in {b.get('documenten_met_btw', 0)} document(en), "
            f"Σ btw (debet − credit) {_eur(b.get('btw_bedrag_totaal'))}; OB-afwikkelboekingen op een "
            f"RLZ-btw-grootboek: {b.get('documenten_ob_afwikkeling', 0)} document(en)"
        )
        L.append(
            f"- Tweede bron (JournalEntryLines op de RLZ-btw-grootboeken): {b.get('journaalregels_btw_grootboek', 0)} "
            f"journaalregel(s), Σ {_eur(b.get('journaalregels_btw_som'))}, laatste "
            f"{b.get('laatste_journaalregel_btw') or '—'}; regels mét btw-code zonder bedrag: "
            f"{b.get('btw_code_zonder_bedrag', 0)} (0,00 is alleen echt als beide bronnen 0 zijn)"
        )
        L.append(
            f"- Afmeldingsdatum zoals uit de data blijkt: {b.get('afmeldingsdatum_uit_data') or '—'} "
            f"(laatste btw-regel {b.get('laatste_btw_regel') or '—'}, "
            f"laatste OB-mutatie {b.get('laatste_ob_mutatie') or '—'})"
        )
        L.append(
            f"- Restsaldo rekening per {PEILDATUM_JAAREINDE}: {_eur(b.get('restsaldo_jaareinde'))}; "
            f"per {b.get('peildatum')}: {_eur(b.get('restsaldo_tot'))} (0,00 = volledig afgewikkeld)"
        )
        L.append(
            "- RLZ-btw-grootboeken herkend: "
            + (", ".join(f"{x['code']} {x['naam']}" for x in b.get("btw_ledgers", [])) or "geen")
        )

    L += [
        "",
        f"#### Saldibalans RLZ (JournalEntryLines) vs berekend Odoo — per {PEILDATUM_JAAREINDE} en per {r.tot}",
        "",
    ]
    j = r.journaal
    L.append(f"Journaalregels: {j.get('regels', 0)} gelezen. {j.get('rlz_kolom', '')}.")
    L.append("")
    if j.get("per_documenttype"):
        L.append(
            "Journaalposten per documentsoort — volledigheidstoets op `JournalEntry.EventID` (blok 7d punt 2: alleen "
            "posten mét een document-EventID tellen tegen de geboekte documenten; de rest apart):"
        )
        L.append("")
        _tabel(
            L,
            [
                "DocumentType",
                "Journaalposten (RLZ)",
                "Journaalregels",
                "Documentposten (EventID)",
                "Overige posten",
                "Geboekte documenten (vertaald)",
                "Oordeel",
            ],
            [
                [
                    _md(x["naam"]),
                    str(x["journaalposten"]),
                    str(x["journaalregels"]),
                    _of(x.get("documentposten")),
                    _of(x.get("overige_posten")),
                    str(x["documenten_geboekt"]),
                    _md(x.get("oordeel") or ""),
                ]
                for x in j["per_documenttype"]
            ],
        )
        L.append("")
        L.append("Journaalposten per EventID (soortcode) per DocumentType:")
        L.append("")
        _tabel(
            L,
            ["DocumentType", "EventID", "Journaalposten", "Soort"],
            [
                [_md(x["naam"]), _of(e["eventid"]), str(e["posten"]), _md(e["soort"])]
                for x in j["per_documenttype"]
                for e in x.get("per_eventid", [])
            ],
        )
        L.append("")
    rp = r.resultaatposten
    if rp:
        L += ["", "#### RLZ-resultaatposten (niet gemigreerd, Odoo berekent zelf) — blok 7d punt 3", ""]
        L.append(
            f"{rp.get('posten', 0)} journaalpost(en) / {rp.get('regels', 0)} regel(s) met DocumentType 0; "
            f"Σ debet − credit per {PEILDATUM_JAAREINDE} {_eur(rp.get('som_jaareinde'))}, per {r.tot} "
            f"{_eur(rp.get('som_tot'))} — sluitcontrole "
            f"{'GROEN' if rp.get('sluit') else 'ROOD (RLZ-kolom onvolledig gelezen → oordeel ROOD)'}."
        )
        d3 = rp.get("sluitcontrole_7999_8999_0509")
        if d3:
            L.append(
                f"7999 Winst + 8999 Verlies = −0509 Resultaat lopend boekjaar: per {PEILDATUM_JAAREINDE} "
                f"{_eur(d3['7999_plus_8999_jaareinde'])} vs {_eur(d3['min_0509_jaareinde'])}; per {r.tot} "
                f"{_eur(d3['7999_plus_8999_tot'])} vs {_eur(d3['min_0509_tot'])} → "
                f"{'sluit' if d3['sluit'] else 'SLUIT NIET'}."
            )
        L.append("")
        _tabel(
            L,
            ["Rekening", "Omschrijving", f"RLZ {PEILDATUM_JAAREINDE}", f"RLZ {r.tot}"],
            [
                [_md(x["rekening"]), _md(x["omschrijving"]), _eur(x["rlz_jaareinde"]), _eur(x["rlz_tot"])]
                for x in rp.get("rekeningen", [])
            ],
            leeg="_geen resultaatposten in JournalEntryLines_",
        )
        L.append("")
        L.append(f"_{rp.get('toelichting', '')}_")
        L.append("")
    top = sorted(
        (x for x in r.saldibalans if x.get("groep") is None),
        key=lambda x: -max(abs(x["verschil_jaareinde_geschoond"]), abs(x["verschil_tot_geschoond"])),
    )[:10]
    L.append("Top 10 verschillen buiten de afletter-/tegenzijde-groepen (geschoond voor RJ 220-herclassificatie):")
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
    L += [
        "",
        "Groepstoets afletter-/tegenzijde-rekeningen (blok 7c punt 7 b — telt per GROEP in het oordeel"
        + (f"; blok 7d punt 5: {NIET_MEETBAAR_TEKST}, telt nu NIET" if r.doel_afwezig else "")
        + "):",
        "",
    ]
    _tabel(
        L,
        [
            "Groep",
            "Rekeningen",
            f"RLZ {PEILDATUM_JAAREINDE}",
            f"Odoo {PEILDATUM_JAAREINDE}",
            "Verschil",
            f"RLZ {r.tot}",
            f"Odoo {r.tot}",
            "Verschil",
            "Stand / reden",
        ],
        [
            [
                _md(g["groep"]),
                _md(", ".join(g["rekeningen"])),
                _eur(g["rlz_jaareinde"]),
                _eur(g["odoo_jaareinde"]),
                _eur(g["verschil_jaareinde"]) if g.get("verschil_jaareinde") is not None else "—",
                _eur(g["rlz_tot"]),
                _eur(g["odoo_tot"]),
                _eur(g["verschil_tot"]) if g.get("verschil_tot") is not None else "—",
                _md((g.get("stand") or g["reden"]) + "".join(f" · {m}" for m in (g.get("modelpunten") or []))),
            ]
            for g in r.afletter_groepen
        ],
        leeg="_geen groepsrekeningen in deze saldibalans_",
    )
    for g in r.afletter_groepen:
        # blok 8 15-09: de SCHRIJF-b-markeringen uit de mappingtabel voluit (de tabelcel kapt af)
        for m in g.get("modelpunten") or []:
            L.append(f"- Modelpunt {g['groep']}groep: {m}")
        # blok 9 16-09: élk resterend groepsverschil in benoemde restcategorieën mét regel (nooit 'onverklaard')
        for rest in g.get("rest") or []:
            aantal = f" ({rest['aantal']}×)" if rest.get("aantal") else ""
            L.append(
                f"- Rest {g['groep']}groep — {rest['categorie']}{aantal}: {_eur(rest['bedrag_jaareinde'])} per "
                f"{PEILDATUM_JAAREINDE} / {_eur(rest['bedrag_tot'])} per {r.tot} — {rest['regel']}"
            )
    _model_1001_sectie(L, r)
    L += ["", "Volledige tabel (kolom Groep = telt alleen op groepsniveau):", ""]
    _tabel(
        L,
        [*kop_sb, "Groep"],
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
                _md(x.get("groep") or ""),
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
        ["Boekstuk", "Type", "Bedrag", "Open RLZ", "Open berekend", "Verschil", "Oorzaak"],
        [
            [
                _md(x["boekstuk"]),
                _md(x["move_type"]),
                _eur(x["bedrag"]),
                _eur(x["rlz_open"]),
                _eur(x["berekend_open"]),
                _eur(x["verschil"]),
                _md(x.get("oorzaak") or ""),
            ]
            for x in r.open_posten
        ],
        leeg="_geen open posten en geen verschillen_",
    )
    L += [
        "",
        f"Verrekeningen factuur↔creditnota (paar afgeleid; run 3 = reconcile beide moves) — {len(r.verrekeningen)}",
        "",
    ]
    _tabel(
        L,
        ["Factuur", "Creditnota", "Bedrag", "Herkomst"],
        [[_md(x["factuur"]), _md(x["creditnota"]), _eur(x["bedrag"]), _md(x["herkomst"])] for x in r.verrekeningen],
    )
    som_wo = sum((x["write_off"] for x in r.betalingsverschillen), NUL).quantize(Decimal("0.01"))
    L += [
        "",
        f"Betalingsverschillen (blok 7d punt 4: RLZ open 0, koppelingen ≠ totaal → write-off op Betalingsverschillen, "
        f"cent-exact) — {len(r.betalingsverschillen)} / Σ {_eur(som_wo)}",
        "",
    ]
    _tabel(
        L,
        ["Boekstuk", "Type", "Documenttotaal", "Betaald", "Restant", "Write-off", "Rekening", "Datum"],
        [
            [
                _md(x["boekstuk"]),
                _md(x["move_type"]),
                _eur(x["bedrag"]),
                _eur(x["betaald"]),
                _eur(x["restant"]),
                _eur(x["write_off"]),
                _md(x["rekening"]),
                _md(x["datum"]),
            ]
            for x in r.betalingsverschillen
        ],
        leeg="_geen betalingsverschillen_",
    )
    L += ["", f"Regelsom ≠ documenttotaal (cent-exact, nooit stil afgerond) — {len(r.som_verschillen)}", ""]
    _tabel(
        L,
        ["Boekstuk", "Type", "Documenttotaal", "Σ regels − totaal"],
        [
            [_md(x["boekstuk"]), _md(x["move_type"]), _eur(x["bedrag"]), _eur(x["som_verschil"])]
            for x in r.som_verschillen
        ],
        leeg="_alle regelsommen sluiten cent-exact_",
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

    L += [
        "",
        "#### Per pand (toewijzingen mens/hoog; grootboek-regels: aankoop = 7000/koopsom, verkoop = opbrengst-regels, "
        "kosten = overige kostenregels; notaris-ontvangst = alleen bank; vaste activa nooit — blok 7c punt 4)",
        "",
    ]
    _tabel(
        L,
        [
            "Pand",
            "Aankoop",
            "Aanbetalingen",
            "Kosten",
            "Verkoop",
            "Notaris-ontvangst (bank)",
            "Marge (verkoop − aankoop − kosten)",
            "Controle",
            "Midden-koppelingen (wachten op Toewijzing)",
            "Signalen",
        ],
        [
            [
                _md(p["pand"]),
                _eur(p["aankoop"]),
                _eur(p["aanbetalingen"]),
                _eur(p["kosten"]),
                _eur(p["verkoop"]),
                _eur(p.get("notaris_ontvangst")),
                _eur(p["marge"]) if p["marge"] is not None else ("—" if r.doel_afwezig else "— (niet verkocht)"),
                _md(p.get("controle") or ""),
                str(p.get("midden_wachtend", 0)),
                _md("; ".join(p.get("signalen") or [])),
            ]
            for p in r.per_pand
        ],
    )
    n_sig = sum(1 for p in r.per_pand if p.get("signalen"))
    n_midden = sum(int(p.get("midden_wachtend", 0)) for p in r.per_pand)
    L.append("")
    L.append(
        f"Panden mét signaal: {n_sig} van {len(r.per_pand)}; midden-koppelingen die op de Toewijzing wachten: "
        f"{n_midden} (buiten de sommen — mens wint). Per-pand 'sluit' = GO-eis bij SCHRIJF c, niet bij SCHRIJF a "
        "(besluit Peter 14-09)."
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
    L += [
        "",
        f"#### Expliciete rekeningmapping (blok 8, `app/migratie/rekening_mapping.py`) — {len(r.expliciete_mapping)}",
        "",
    ]
    _tabel(
        L,
        ["RLZ-code", "Doel", "Groep", "SCHRIJF", "Odoo-rekening", "Stand", "Toelichting"],
        [
            [
                _md(x["rlz_code"]),
                _md(x["doel"]),
                _md(x["groep"]),
                _md(x["schrijf_fase"]),
                _md(f"{x['odoo_code'] or ''} (id {x['odoo_account_id']})" if x.get("odoo_account_id") else "—"),
                _md(x.get("stand")),
                _md(x["toelichting"]),
            ]
            for x in r.expliciete_mapping
        ],
        leeg="_geen expliciete mapping toegepast_",
    )
    L += ["", f"#### Ongemapte RLZ-rekeningen — {len(r.ongemapt)} (voorstel = mens beslist, blok 8 1b)", ""]
    _tabel(
        L,
        ["RLZ-code", "Naam", "Type", "Regels", "Documenten", "Voorgestelde Odoo-tegenhanger"],
        [
            [
                _md(x["rlz_code"]),
                _md(x["rlz_naam"]),
                _md(x["account_type"]),
                str(x["regels"]),
                str(x["documenten"]),
                _md(x.get("voorstel") or "—"),
            ]
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

    L += [
        "",
        "#### Saldo-toets bank (berekend lopend saldo uit PaymentTransactions, beginsaldo 0 — Peter legt dit naast "
        "het echte banksaldo)",
        "",
    ]
    _tabel(
        L,
        [
            "Journal (IBAN)",
            "RLZ-rekeningen",
            "Regels",
            f"Berekend saldo {PEILDATUM_JAAREINDE}",
            f"Berekend saldo {r.tot}",
            "Afschrift-koppen RLZ",
            "Eerste/laatste mutatie",
        ],
        [
            [
                _md(s["rekening"]),
                str(s["rlz_rekeningen"]),
                str(s["regels"]),
                _eur(s["saldo_jaareinde"]),
                _eur(s["saldo_tot"]),
                str(s["afschrift_koppen_rlz"]),
                f"{s['eerste_mutatie'] or '—'} / {s['laatste_mutatie'] or '—'}",
            ]
            for s in r.saldo_toets
        ],
    )
    L += [
        "",
        "#### Voorstel `account.bank.statement` per maand per journal (balance_end_real = berekend lopend saldo; "
        "besluit-vorm punt 3)",
        "",
    ]
    _tabel(
        L,
        ["Journal", "Maand", "Regels", "Som regels", "Beginsaldo", "Eindsaldo = balance_end_real", "RLZ-kop"],
        [
            [
                _md(s["rekening"]),
                _md(s["maand"]),
                str(s["regels"]),
                _eur(s["som"]),
                _eur(s["beginsaldo"]),
                _eur(s["balance_end_real"]),
                _md(s["sluit"]),
            ]
            for s in r.statements
        ],
    )

    L += ["", "#### Beslispunten Peter (stand ná blok 7d 14-09)", ""]
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
