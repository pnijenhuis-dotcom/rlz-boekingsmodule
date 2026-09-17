"""1001-model — SCHRIJF b (VGG run 2 blok 9, opdracht Peter 16-09 avond), LEES-ONLY in de replay.

Het open modelpunt sinds blok 7d (14-09): een MEMORIAAL dat in RLZ rechtstreeks op de bankrekening 1001 boekt, wordt
in Odoo dubbel geteld — de statement line voedt de bankrekening al (Odoo: bank uitsluitend via
`account.bank.statement.line`) én de memoriaalregel deed dat nog eens (−85.376,31 per 31-12-2025 / +71.343,31 per
14-09-2026 in de nametingen). Het model legt per memoriaal-1001-regel vast waar hij in het Odoo-doel hoort:

* **gekoppeld** — de regel staat één-op-één tegenover een RLZ-bankmutatie (zelfde tekenrichting, cent-exact bedrag):
  eerste bewijs = `PaymentReferenceList` van de mutatie wijst naar dit memoriaal; tweede bewijs = een VRIJE mutatie
  (zonder enige koppeling) mét hetzelfde bedrag binnen ± `VENSTER_DAGEN`. De regel landt dan op de outstanding-/
  suspense-rekening van het bankdagboek (lees-only geresolved zoals 1012: payment-method-line → company-default →
  KLIKPUNT; onbekend = pseudo-sleutel `IMPLICIET_OUTSTANDING`, zodat de groepstoets al klopt en het rapport het
  klikpunt benoemt) en de statement line reconcilieert ertegen: haar tegenregel gaat van de tussenrekening naar
  diezelfde outstanding-rekening. Netto: bank één keer (statement line), outstanding 0, de andere kant van het
  memoriaal ongewijzigd.
* **geen_bankmutatie** — geen kandidaat: de regel blijft op de TUSSENREKENING mét reden ("geen bankmutatie binnen
  ± 3 d"); Odoo boekt nooit buiten statement lines op de bank.
* **meerduidig** — twee of meer kandidaten: NIET toegewezen (aparte teller), óók op de tussenrekening mét reden — de
  mens kiest de mutatie.

Alles deterministisch, cent-exact, geen afronding; de balansguard van blok 7d blijft ROOD-bepalend (debet/credit van de
regel veranderen niet, alleen de bestemming). Geen RLZ-/Odoo-/DB-writes. Guard: `tests/migratie/test_model_1001.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from app.migratie import rekening_mapping, rlz_bron
from app.migratie.vertaling import IMPLICIET_TUSSENREKENING, BalansRegel, Context, Vertaald

NUL = Decimal("0.00")
#: Pseudo-sleutel voor de outstanding-/suspense-rekening van BNK1 zolang die in Odoo niet is ingesteld (KLIKPUNT).
IMPLICIET_OUTSTANDING = "impliciet:outstanding-bnk1"
#: Venster voor het tweede bewijs (bedrag + datum), in kalenderdagen aan weerszijden.
VENSTER_DAGEN = 3

BEWIJS_KOPPELING = "PaymentReferenceList"
BEWIJS_BEDRAG_DATUM = "bedrag + datum"

UITKOMST_GEKOPPELD = "gekoppeld"
UITKOMST_GEEN = "geen_bankmutatie"
UITKOMST_MEERDUIDIG = "meerduidig"

BESTEMMING_OUTSTANDING = "outstanding"
BESTEMMING_TUSSENREKENING = "tussenrekening"

REDEN_GEEN = f"geen bankmutatie binnen ± {VENSTER_DAGEN} d — blijft op de tussenrekening"
REDEN_MEERDUIDIG = "meerduidig — niet toegewezen, mens kiest de mutatie; blijft op de tussenrekening"
#: Markering op de BalansRegel van een verplaatste memoriaalregel (`bron` blijft leesbaar voor de saldibalans).
BRON_1001 = "regel"


@dataclass
class Uitkomst1001:
    regels: list[dict[str, Any]] = field(default_factory=list)
    outstanding_sleutel: str = IMPLICIET_OUTSTANDING
    outstanding_bekend: bool = False
    outstanding_melding: str | None = None
    bank_ledger_codes: list[str] = field(default_factory=list)
    #: Blok 10 (17-09) "één regel, één bestemming": een 1001-regel die óók de RJ-220-rol kreeg — ROOD-bepalend, nooit stil.
    overlappen: list[dict[str, Any]] = field(default_factory=list)

    @property
    def gekoppeld(self) -> int:
        return sum(1 for r in self.regels if r["uitkomst"] == UITKOMST_GEKOPPELD)

    @property
    def geen_kandidaat(self) -> int:
        return sum(1 for r in self.regels if r["uitkomst"] == UITKOMST_GEEN)

    @property
    def meerduidig(self) -> int:
        return sum(1 for r in self.regels if r["uitkomst"] == UITKOMST_MEERDUIDIG)

    @property
    def via_koppeling(self) -> int:
        return sum(1 for r in self.regels if r["bewijs"] == BEWIJS_KOPPELING)

    @property
    def via_bedrag_datum(self) -> int:
        return sum(1 for r in self.regels if r["bewijs"] == BEWIJS_BEDRAG_DATUM)

    def tellers(self) -> dict[str, Any]:
        return {
            "regels_1001": len(self.regels),
            "gekoppeld": self.gekoppeld,
            "via_koppeling": self.via_koppeling,
            "via_bedrag_datum": self.via_bedrag_datum,
            "geen_bankmutatie": self.geen_kandidaat,
            "meerduidig": self.meerduidig,
            "outstanding_sleutel": self.outstanding_sleutel,
            "outstanding_bekend": self.outstanding_bekend,
            "overlappen": len(self.overlappen),
            "met_rj220_tegenzijde": sum(1 for r in self.regels if r.get("rj220_tegenzijde")),
        }

    def als_dict(self) -> dict[str, Any]:
        return {
            "tellers": self.tellers(),
            "outstanding_melding": self.outstanding_melding,
            "bank_ledger_codes": list(self.bank_ledger_codes),
            "venster_dagen": VENSTER_DAGEN,
            "regels": list(self.regels),
            "overlappen": list(self.overlappen),
        }


# ---- hulpfuncties -------------------------------------------------------------------------------------------------


def bank_ledger_ids(ctx: Context, ledgers: list[dict[str, Any]]) -> dict[str, str]:
    """RLZ-grootboeken die 'de bank' zijn: de tabelcodes met doel `bank_statement_lines` (1001) én élke Ledgers-rij
    mét `UseForPaymentAccount`. Geeft ledger-id → code (of id)."""
    codes = {
        m.rlz_code
        for m in rekening_mapping.EXPLICIETE_MAPPING.values()
        if m.doel == rekening_mapping.DOEL_BANK_STATEMENT_LINES
    }
    uit: dict[str, str] = {}
    for lid, (code, _naam, _t) in ctx.ledgers.items():
        if code and code in codes:
            uit[lid] = code
    for r in ledgers:
        lid = rlz_bron.doc_id(r)
        if lid and r.get("UseForPaymentAccount") is True:
            uit.setdefault(lid, str(r.get("AccountNumber") or lid))
    return uit


def outstanding_sleutel_voor(ctx: Context) -> tuple[str, bool, str | None]:
    """(sleutel, bekend, melding): de echte Odoo-rekening-id als de 1012-resolutie 'm vond, anders de pseudo-sleutel."""
    o = ctx.outstanding
    if o is not None and getattr(o, "gevonden", False) and getattr(o, "account_id", None) is not None:
        return str(o.account_id), True, getattr(o, "melding", None)
    melding = (
        getattr(o, "melding", None) if o is not None else "outstanding-rekening niet opgezocht (geen doelkoppeling)"
    )
    return IMPLICIET_OUTSTANDING, False, melding


def _tx_datum(tx: dict[str, Any]) -> date | None:
    from app.rlz.lezen import als_datum  # noqa: PLC0415

    return als_datum(tx.get("BookDate")) or als_datum(tx.get("Date"))


def _tx_bedrag(tx: dict[str, Any]) -> Decimal:
    from app.rlz.lezen import als_bedrag  # noqa: PLC0415

    return als_bedrag(tx.get("Amount")) or NUL


def _regel_datum(r: BalansRegel) -> date | None:
    try:
        return date.fromisoformat(r.datum) if r.datum else None
    except ValueError:
        return None


def _zelfde_richting_en_bedrag(regel_bedrag: Decimal, tx_bedrag: Decimal) -> bool:
    """Debet op 1001 (geld erin) ↔ mutatie +; credit ↔ mutatie −; cent-exact."""
    if regel_bedrag == 0 or tx_bedrag == 0:
        return False
    if (regel_bedrag > 0) != (tx_bedrag > 0):
        return False
    return abs(regel_bedrag).quantize(Decimal("0.01")) == abs(tx_bedrag).quantize(Decimal("0.01"))


def is_vrij(b: Vertaald) -> bool:
    """Een bankregel zonder enige koppeling (geen reconcile, geen directe tegenregels) — staat op de tussenrekening."""
    bank = b.move.bank or {}
    return not bank.get("reconcile") and not bank.get("tegenregel")


# ---- het model ----------------------------------------------------------------------------------------------------


def pas_1001_model_toe(
    ctx: Context, bron: rlz_bron.RlzBron, documenten: list[Vertaald], bankregels: list[Vertaald]
) -> Uitkomst1001:
    """Herbestemt de memoriaal-1001-regels (in place op `documenten`/`bankregels`) en geeft het rapport per regel."""
    sleutel, bekend, melding = outstanding_sleutel_voor(ctx)
    bank_ids = bank_ledger_ids(ctx, bron.ledgers)
    uit = Uitkomst1001(
        outstanding_sleutel=sleutel,
        outstanding_bekend=bekend,
        outstanding_melding=melding,
        bank_ledger_codes=sorted(set(bank_ids.values())),
    )
    if not bank_ids:
        return uit

    txs: dict[str, dict[str, Any]] = {}
    for tx in bron.bank:
        tid = rlz_bron.doc_id(tx)
        if tid:
            txs[tid] = tx
    bankregel_van: dict[str, Vertaald] = {b.move.rlz_id: b for b in bankregels}
    # eerste bewijs: welke mutaties wijzen (PaymentReferenceList) naar welk document
    gelinkt_aan: dict[str, list[str]] = {}
    for tid, tx in txs.items():
        for pr in tx.get("PaymentReferenceList") or []:
            doc = pr.get("Document") if isinstance(pr, dict) and isinstance(pr.get("Document"), dict) else None
            did = rlz_bron.doc_id(doc) if doc else None
            if did:
                gelinkt_aan.setdefault(did, []).append(tid)
    geclaimd: set[str] = set()

    for v in documenten:
        if v.move.move_type != "entry" or v.zonder_regels:
            continue
        posities = [
            i for i, r in enumerate(v.regels) if r.bron == BRON_1001 and r.rlz_ledger_id and r.rlz_ledger_id in bank_ids
        ]
        if not posities:
            continue
        # aantal 1001-regels per (richting, |bedrag|) in dít memoriaal — voor het paren van gelijke bedragen (bewijs 1)
        gelijk: dict[tuple[bool, Decimal], int] = {}
        for i in posities:
            r = v.regels[i]
            bedrag = (r.debet - r.credit).quantize(Decimal("0.01"))
            if bedrag != 0:
                k = (bedrag > 0, abs(bedrag))
                gelijk[k] = gelijk.get(k, 0) + 1
        for i in posities:
            r = v.regels[i]
            bedrag = (r.debet - r.credit).quantize(Decimal("0.01"))
            if bedrag == 0:
                continue
            datum = _regel_datum(r)
            rij: dict[str, Any] = {
                "boekstuk": v.move.boekstuk,
                "rlz_id": v.move.rlz_id,
                "regel": i + 1,
                "datum": r.datum,
                "rlz_code": bank_ids.get(r.rlz_ledger_id or "", "1001"),
                "bedrag": bedrag,
                "uitkomst": None,
                "bestemming": None,
                "bewijs": None,
                "mutatie": None,
                "mutatie_datum": None,
                "dagen_verschil": None,
                "kandidaten": 0,
                "reden": None,
                # Blok 10: de RJ-220-herclassificatie van dit memoriaal (tegenzijde → rol), zichtbaar náást de 1001-regel.
                "rj220_tegenzijde": (
                    "; ".join(f"{van} → {naar} ({bed})" for van, naar, bed in v.herclassificaties) if v.herclassificaties else None
                ),
            }
            if v.rol_regel_index == i:
                # Eén regel, twee bestemmingen (rol én outstanding/tussenrekening) — mag niet: melden als overlap; de
                # herbestemming hieronder gaat gewoon door zodat het rapport beide bestemmingen toont, het oordeel is ROOD.
                uit.overlappen.append(
                    {
                        "boekstuk": v.move.boekstuk,
                        "rlz_id": v.move.rlz_id,
                        "regel": i + 1,
                        "rlz_code": rij["rlz_code"],
                        "bedrag": bedrag,
                        "herclassificatie": rij["rj220_tegenzijde"],
                        "reden": "1001-regel kreeg óók de RJ-220-rol — één regel, één bestemming (blok 10, 17-09)",
                    }
                )
            # (1) gekoppelde mutaties van dit memoriaal, zelfde richting + cent-exact
            kandidaten = [
                tid
                for tid in gelinkt_aan.get(v.move.rlz_id, [])
                if tid not in geclaimd and _zelfde_richting_en_bedrag(bedrag, _tx_bedrag(txs[tid]))
            ]
            bewijs = BEWIJS_KOPPELING
            if not kandidaten:
                # (2) vrije mutaties: zelfde richting, cent-exact, binnen het venster
                bewijs = BEWIJS_BEDRAG_DATUM
                for tid, tx in txs.items():
                    if tid in geclaimd:
                        continue
                    b = bankregel_van.get(tid)
                    if b is None or not is_vrij(b):
                        continue
                    if not _zelfde_richting_en_bedrag(bedrag, _tx_bedrag(tx)):
                        continue
                    td = _tx_datum(tx)
                    if datum is None or td is None or abs((td - datum).days) > VENSTER_DAGEN:
                        continue
                    kandidaten.append(tid)
            kandidaten.sort(key=lambda t: (_tx_datum(txs[t]) or date.min, str(txs[t].get("TransactionId") or "")))
            rij["kandidaten"] = len(kandidaten)
            gekozen: str | None = None
            if len(kandidaten) == 1:
                gekozen = kandidaten[0]
            elif len(kandidaten) > 1 and bewijs == BEWIJS_KOPPELING:
                # evenveel gelijke 1001-regels als gekoppelde mutaties → paar in datumvolgorde (deterministisch)
                k = (bedrag > 0, abs(bedrag))
                if gelijk.get(k, 0) == len(kandidaten) + sum(
                    1
                    for rr in uit.regels
                    if rr["rlz_id"] == v.move.rlz_id
                    and rr["uitkomst"] == UITKOMST_GEKOPPELD
                    and (rr["bedrag"] > 0, abs(rr["bedrag"])) == k
                ):
                    gekozen = kandidaten[0]
            if gekozen is not None:
                geclaimd.add(gekozen)
                tx = txs[gekozen]
                td = _tx_datum(tx)
                rij.update(
                    {
                        "uitkomst": UITKOMST_GEKOPPELD,
                        "bestemming": BESTEMMING_OUTSTANDING,
                        "bewijs": bewijs,
                        "mutatie": str(tx.get("TransactionId") or gekozen),
                        "mutatie_datum": td.isoformat() if td else None,
                        "dagen_verschil": (td - datum).days if (td and datum) else None,
                        "reden": f"→ outstanding BNK1 ({sleutel}); statement line {tx.get('TransactionId') or gekozen} "
                        f"reconcilieert ertegen (bewijs {bewijs})",
                    }
                )
                _herbestem_regel(v, i, sleutel, bekend, rij["reden"])
                _herbestem_mutatie(bankregel_van.get(gekozen), v, tx, sleutel, bewijs)
            else:
                meerduidig = len(kandidaten) > 1
                rij.update(
                    {
                        "uitkomst": UITKOMST_MEERDUIDIG if meerduidig else UITKOMST_GEEN,
                        "bestemming": BESTEMMING_TUSSENREKENING,
                        "bewijs": None,
                        "reden": (
                            f"{REDEN_MEERDUIDIG} ({len(kandidaten)} kandidaten: "
                            + ", ".join(str(txs[t].get("TransactionId") or t) for t in kandidaten)
                            + ")"
                            if meerduidig
                            else REDEN_GEEN
                        ),
                    }
                )
                _herbestem_regel(v, i, IMPLICIET_TUSSENREKENING, False, rij["reden"])
            uit.regels.append(rij)
    return uit


def _herbestem_regel(v: Vertaald, i: int, sleutel: str, account_bekend: bool, reden: str) -> None:
    r = v.regels[i]
    v.regels[i] = replace(r, rekening=sleutel)
    # vals: memoriaalregels staan 1-op-1 in line_ids (entry kent geen btw-splitsing) — positie = index onder `regel`
    lijnen = v.move.vals.get("line_ids") if isinstance(v.move.vals, dict) else None
    regel_posities = [j for j, rr in enumerate(v.regels) if rr.bron == BRON_1001]
    if isinstance(lijnen, list) and i in regel_posities:
        p = regel_posities.index(i)
        if p < len(lijnen) and isinstance(lijnen[p], list) and len(lijnen[p]) == 3 and isinstance(lijnen[p][2], dict):
            lijnen[p][2]["account_id"] = int(sleutel) if account_bekend and sleutel.isdigit() else None
            lijnen[p][2]["model_1001"] = reden
    v.move.reden = f"regel {i + 1} (1001-model): {reden}; {v.move.reden}"


def _herbestem_mutatie(b: Vertaald | None, v: Vertaald, tx: dict[str, Any], sleutel: str, bewijs: str) -> None:
    if b is None:
        return
    for j, r in enumerate(b.regels):
        if r.bron == "tegenregel" and r.rekening == IMPLICIET_TUSSENREKENING:
            b.regels[j] = replace(r, rekening=sleutel)
            break
    bank = dict(b.move.bank or {})
    reconcile = list(bank.get("reconcile") or [])
    gevonden = False
    for rc in reconcile:
        if rc.get("anker") == v.move.anker:
            rc["via_outstanding"] = sleutel
            rc["model_1001"] = bewijs
            gevonden = True
    if not gevonden:
        reconcile.append(
            {
                "anker": v.move.anker,
                "boekstuk": v.move.boekstuk,
                "move_type": "entry",
                "bedrag": _tx_bedrag(tx),
                "via_outstanding": sleutel,
                "model_1001": bewijs,
            }
        )
        bank["restant_berekend"] = NUL
    bank["reconcile"] = reconcile
    b.move.bank = bank
    b.move.reden = (
        f"1001-model: reconcile tegen memoriaal {v.move.boekstuk or v.move.rlz_id} via outstanding ({bewijs}); "
        + (b.move.reden or "")
    )
