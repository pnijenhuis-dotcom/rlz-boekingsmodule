"""Replay-motor RLZ → Odoo, DRY-RUN (run 2 VGG 12-09, blok 6; besluit Peter 12-09 punt 1a: eerst een volledige dry-run
zonder Odoo-writes mét reconciliatierapport).

`dry_run(administratie_id, *, client=None, tot=None, pandenlijst=None, ...) -> ReplayRapport`:
1. leest RLZ (`rlz_bron.lees_bron`) — alle geboekte documenten (Status 2/3) + regels, bank mét PaymentReferenceList,
   rekeningen + statements, JournalEntryLines, Ledgers, TaxRates; concepten en systeemhulzen tellen als "niet migreren";
2. laadt de vertaalcontext: grootboek (C `rj220.vertaal_grootboek`, lazy → fallback mapping), rollen (C
`rj220.rollen_voor`,
   lazy → alles None), pand-toewijzing (B `pand_per_document`, lazy → leeg), doelkoppeling (D
   `odoo_doel.doelkoppeling_voor`,
   lazy → lege `Doel`, zichtbaar als LET OP);
3. vertaalt élk geboekt document en élke bankregel (`vertaling.py`);
4. bouwt het reconciliatierapport (`rapport.py`): saldibalans RLZ vs berekend Odoo, open posten, per pand, tabellen,
export.
Schrijft niets — geen RLZ, geen Odoo, geen DB (de DB wordt alleen gelezen voor rlz_admin_id/koppeling/panden; een test
geeft `client` + `doel` + `panden` mee en raakt de DB niet). `pandenlijst` (Salesforce/CSV-seam van B) is een
lees-lijst om
tegen te matchen: alleen gebruikt om pand-codes in het rapport te verrijken, nooit als bron van een boeking."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.migratie import rlz_bron, vertaling
from app.migratie.rapport import EXPORT_MAAND, EXPORT_TYPES, PEILDATUM_JAAREINDE, ReplayRapport
from app.migratie.vertaling import Context, Doel, MoveVoorstel, PandToewijzing, RolRekeningen, Vertaald
from app.rlz.lezen import LeesClient, als_bedrag, als_datum
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)
NUL = Decimal("0.00")
VIRTUEEL_AFSCHRIFT = "99999999"  # RLZ's "lopend afschrift" (api-verkenning "Bankmodule STAP 0" §2)
_EINDSALDO_SLEUTELS = ("EndBalance", "ClosingBalance", "BalanceEnd", "EndingBalance", "Balance", "NewBalance")
_BEGINSALDO_SLEUTELS = ("StartBalance", "OpeningBalance", "BalanceStart", "BeginBalance", "PreviousBalance")


def laad_doel(administratie_id: uuid.UUID) -> tuple[Doel, str | None]:
    """Doelkoppeling via D's `odoo_doel.doelkoppeling_voor` (eist migratie_doel=True). Ontbreekt D of de rij: lege Doel
    +
    melding (LET OP) — de vertaling loopt door met `journal_id None`, het rapport kan niet GROEN worden."""
    try:
        from app.migratie.odoo_doel import doelkoppeling_voor  # noqa: PLC0415 — D bouwt 'm parallel
    except ImportError:
        return Doel(), "doelkoppeling: module app.migratie.odoo_doel ontbreekt (blok 5) — dagboeken leeg in de vals"
    try:
        k = doelkoppeling_voor(administratie_id)
    except Exception as exc:  # noqa: BLE001 — GeenMigratieDoel of DB-fout: zichtbaar, niet crashen
        return Doel(), f"doelkoppeling niet geladen: {type(exc).__name__}: {exc}"
    return (
        Doel(
            company_id=getattr(k, "company_id", None),
            journal_sale_id=getattr(k, "journal_sale_id", None),
            journal_purchase_id=getattr(k, "journal_purchase_id", None),
            journal_general_id=getattr(k, "journal_general_id", None),
            journal_bank_id=getattr(k, "journal_bank_id", None),
            analytic_plan_id=getattr(k, "analytic_plan_id", None),
        ),
        None,
    )


def dry_run(
    administratie_id: uuid.UUID,
    *,
    client: LeesClient | None = None,
    tot: date | None = None,
    pandenlijst: Any = None,
    doel: Doel | None = None,
    odoo_accounts: list[dict[str, Any]] | None = None,
    rollen: RolRekeningen | None = None,
    panden: dict[uuid.UUID, PandToewijzing] | None = None,
    administratie_naam: str | None = None,
    rlz_admin_id: str | None = None,
    voortgang: Callable[[str], None] | None = None,
    nu: datetime | None = None,
) -> ReplayRapport:
    tot = tot or vandaag_nl()
    let_op: list[str] = []
    if client is None:
        from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor  # noqa: PLC0415

        rlz_admin_id = rlz_admin_id or rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
        eigen_client = True
    else:
        eigen_client = False
    try:
        bron = rlz_bron.lees_bron(client, voortgang=voortgang)
    finally:
        if eigen_client and hasattr(client, "close"):
            client.close()  # type: ignore[union-attr]

    if bron.blokkering:
        # Blok 7b punt 1c: een webfilter-403 midden in de run = ROOD mét de blokkeringsregel, NIETS doorgerekend.
        rapport = ReplayRapport(
            administratie_id=str(administratie_id),
            administratie_naam=administratie_naam,
            rlz_admin_id=rlz_admin_id,
            gegenereerd_op=(nu or datetime.now(UTC)).isoformat(timespec="seconds"),
            tot=tot.isoformat(),
        )
        rapport.blokkering = bron.blokkering
        rapport.gelezen = dict(bron.gelezen)
        rapport.fouten = [f.als_dict() for f in bron.fouten]
        rapport.overgeslagen = list(bron.overgeslagen)
        rapport.let_op = let_op + [f"{rlz_bron.BLOKKERING_TEKST}: rapport niet doorgerekend met halve data"]
        rapport.tellers = _lees_tellers(bron)
        return rapport

    if doel is None:
        doel, melding = laad_doel(administratie_id)
        if melding:
            let_op.append(melding)
    if not doel.compleet:
        let_op.append("doelkoppeling incompleet — één of meer dagboeken (sale/purchase/general/bank) onbekend")
    if odoo_accounts is None:
        odoo_accounts = []
        let_op.append("geen Odoo-rekeningen meegegeven (--odoo-rekeningen) — élke grootboekregel is ongemapt")
    grootboek = vertaling.laad_grootboek(bron.ledgers, odoo_accounts)
    if rollen is None:
        rollen = vertaling.laad_rollen(administratie_id)
    if panden is None:
        try:
            panden = vertaling.laad_panden(administratie_id, boekingen=_rlz_boekingen(bron))
        except Exception as exc:  # noqa: BLE001
            panden = {}
            let_op.append(f"pand-toewijzing niet geladen: {type(exc).__name__}: {exc}")
        if not panden:
            let_op.append("geen pand-toewijzing (B `pand_per_document` ontbreekt of leeg) — alles zonder pand")
    if pandenlijst is not None:
        let_op.append("pandenlijst meegegeven — alleen lees-lijst om tegen te matchen (nooit bron van een boeking)")
    ctx = Context(
        administratie_id=administratie_id,
        doel=doel,
        grootboek=grootboek,
        ledgers=vertaling.ledgers_index(bron.ledgers),
        rollen=rollen,
        panden=panden,
        btw_ledgers=vertaling.btw_ledgers_uit(bron.ledgers, bron.taxrates),
    )
    rapport = ReplayRapport(
        administratie_id=str(administratie_id),
        administratie_naam=administratie_naam,
        rlz_admin_id=rlz_admin_id,
        gegenereerd_op=(nu or datetime.now(UTC)).isoformat(timespec="seconds"),
        tot=tot.isoformat(),
    )
    rapport.gelezen = dict(bron.gelezen)
    rapport.fouten = [f.als_dict() for f in bron.fouten]
    rapport.overgeslagen = list(bron.overgeslagen)
    rapport.let_op = let_op
    rapport.doel = {
        "company_id": doel.company_id,
        "journal_sale_id": doel.journal_sale_id,
        "journal_purchase_id": doel.journal_purchase_id,
        "journal_general_id": doel.journal_general_id,
        "journal_bank_id": doel.journal_bank_id,
    }
    if not bron.bank_expand_gelukt:
        let_op.append("PaymentTransactions zonder PaymentReferenceList ($expand geweigerd) — reconcile-paren onbekend")
    _vertaal_en_rapporteer(ctx, bron, rapport, tot=tot)
    return rapport


def _rlz_boekingen(bron: rlz_bron.RlzBron) -> list[Any] | None:
    """B's `RlzBoeking`-lijst (via `panden.service._naar_boeking` + `_naar_bankmutatie`, ontknipt) zodat
    `pand_per_document` dezelfde afleiding draait als `pandenregister-afleiden` (blok 7b punt 5: ÉÉN bron — de
    verkopen zijn notaris-ontvangsten op de bank, dus zonder bankmutaties telt de per-pand-tabel 0 verkopen); None
    als B's module ontbreekt (dan alleen DB-rijen)."""
    try:
        from app.panden.service import _naar_bankmutatie, _naar_boeking  # noqa: PLC0415 — B bouwt 'm parallel
    except ImportError:
        return None
    uit = []
    for pad, rij in bron.alle_documenten():
        if pad in ("PurchaseInvoices", "SalesInvoices", "ManualJournals") and rlz_bron.is_geboekt(rij):
            b = _naar_boeking(pad, rij)
            if b is not None:
                uit.append(b)
    for tx in bron.bank:
        b = _naar_bankmutatie(tx)
        if b is not None:
            uit.append(b)
    return uit


def _lees_tellers(bron: rlz_bron.RlzBron) -> dict[str, Any]:
    return {
        "regel_calls": bron.regel_calls,
        "regel_fouten": len(bron.regel_fouten),
        "regels_via_collectie": bron.regels_via_collectie,
        "rlz_calls": bron.client_calls,
        "webfilter_treffers": bron.webfilter_treffers,
        "gewacht_seconden": bron.gewacht_seconden,
    }


# ---- vertaling + rapport ---------------------------------------------------------------------------------------


def _vertaal_en_rapporteer(ctx: Context, bron: rlz_bron.RlzBron, rapport: ReplayRapport, *, tot: date) -> None:
    open_bank = rlz_bron.open_bank_sleutels(bron.bank)
    per_collectie: dict[str, dict[str, int]] = {}
    documenten: list[Vertaald] = []
    huls_ids: set[str] = set()
    for pad, rij in bron.alle_documenten():
        tel = per_collectie.setdefault(pad, {"gelezen": 0, "geboekt": 0, "concept": 0, "huls": 0, "niet_migreren": 0})
        tel["gelezen"] += 1
        rid = rlz_bron.doc_id(rij) or ""
        if rlz_bron.is_huls(rij, open_bank):
            tel["huls"] += 1
            tel["niet_migreren"] += 1
            huls_ids.add(rid)
            continue
        if rlz_bron.is_concept(rij):
            tel["concept"] += 1
            tel["niet_migreren"] += 1
            continue
        if not rlz_bron.is_geboekt(rij):
            tel["niet_migreren"] += 1
            continue
        tel["geboekt"] += 1
        regels = bron.regels.get(rid)
        if regels is None and rid in bron.regel_fouten:
            regels = None
        documenten.append(vertaling.vertaal_document(ctx, pad, rij, regels))
        if rid in bron.regel_fouten:
            documenten[-1].move.reden = f"{bron.regel_fouten[rid]}; {documenten[-1].move.reden}"

    ankers = {v.move.rlz_id: vertaling.document_anker(ctx, v) for v in documenten}
    for hid in huls_ids:
        ankers[hid] = vertaling.DocumentAnker(str(vertaling.anker_voor(ctx.administratie_id, hid)), None, "huls", True)
    bankregels: list[Vertaald] = [
        vertaling.vertaal_bankregel(ctx, tx, ankers, expand_gelukt=bron.bank_expand_gelukt) for tx in bron.bank
    ]
    # bank-directe documenten zonder enige gekoppelde mutatie zijn anders onzichtbaar
    direct_ids_met_mutatie: set[str] = set()
    for tx in bron.bank:
        for pr in tx.get("PaymentReferenceList") or []:
            if isinstance(pr, dict) and isinstance(pr.get("Document"), dict) and pr["Document"].get("id"):
                direct_ids_met_mutatie.add(str(pr["Document"]["id"]))
    for v in documenten:
        if v.move.move_type == "bank_direct" and v.move.rlz_id not in direct_ids_met_mutatie:
            v.move.status = vertaling.STATUS_NIET
            v.move.reden = "bank-directe boeking zonder gekoppelde bankmutatie (PaymentReferenceList); " + v.move.reden

    alle = documenten + bankregels
    rapport.moves = [v.move for v in alle]
    _tellers(rapport, per_collectie, alle, bron)
    _saldibalans(ctx, bron, rapport, alle, tot=tot)
    _open_posten(rapport, documenten, bankregels)
    _per_pand(rapport, alle)
    _tabellen(ctx, rapport, alle, bron)
    _statements(rapport, bron, bankregels, tot=tot)
    _btw(ctx, rapport, alle, tot=tot)
    _export(rapport)


def _tellers(
    rapport: ReplayRapport, per_collectie: dict[str, dict[str, int]], alle: list[Vertaald], bron: rlz_bron.RlzBron
) -> None:
    per_type: dict[str, dict[str, int]] = {}
    btw_regels = 0
    btw_docs = 0
    p_nieuw = 0
    p_onbekend = 0
    for v in alle:
        t = per_type.setdefault(v.move.move_type, {"vertaalbaar": 0, "zonder_pand": 0, "niet_vertaalbaar": 0})
        t[v.move.status] += 1
        if v.btw_regels:
            btw_regels += v.btw_regels
            btw_docs += 1
        if v.partner and v.partner.voorstel == "nieuw (res.partner)":
            p_nieuw += 1
        elif v.partner and v.partner.voorstel == "onbekend":
            p_onbekend += 1
    rapport.tellers = {
        "per_collectie": per_collectie,
        "per_type": per_type,
        "geboekt": sum(c["geboekt"] for c in per_collectie.values()),
        "concept": sum(c["concept"] for c in per_collectie.values()),
        "huls": sum(c["huls"] for c in per_collectie.values()),
        "niet_migreren": sum(c["niet_migreren"] for c in per_collectie.values()),
        "moves": len(alle),
        **_lees_tellers(bron),
        "btw_regels": btw_regels,
        "btw_documenten": btw_docs,
        "partners_nieuw": p_nieuw,
        "partners_onbekend": p_onbekend,
        "bank_expand_gelukt": bron.bank_expand_gelukt,
    }


def _saldibalans(
    ctx: Context, bron: rlz_bron.RlzBron, rapport: ReplayRapport, alle: list[Vertaald], *, tot: date
) -> None:
    jaareinde = date.fromisoformat(PEILDATUM_JAAREINDE)
    rlz: dict[str, list[Decimal]] = {}
    odoo: dict[str, list[Decimal]] = {}
    omschr: dict[str, str] = {}

    def sleutel_voor_ledger(ledger_id: str | None) -> str:
        vert = ctx.grootboek.get(ledger_id or "")
        if vert and vert.odoo_account_id is not None:
            omschr.setdefault(
                str(vert.odoo_account_id),
                f"{vert.odoo_code or ''} ← RLZ {vert.rlz_code or ''} {vert.rlz_naam or ''}".strip(),
            )
            return str(vert.odoo_account_id)
        code, naam, _t = ctx.ledgers.get(ledger_id or "", (None, None, None))
        s = f"ongemapt:{code or ledger_id or '?'}"
        omschr.setdefault(s, f"RLZ {code or ''} {naam or ''}".strip())
        return s

    def tel(d: dict[str, list[Decimal]], s: str, bedrag: Decimal, datum: date | None) -> None:
        rij = d.setdefault(s, [NUL, NUL])
        if datum is None:
            return
        if datum <= jaareinde:
            rij[0] += bedrag
        if datum <= tot:
            rij[1] += bedrag

    bekende_bronnen = {v.move.rlz_id for v in alle}
    met_bron = 0
    for jr in bron.journaalregels:
        ledger_id = rlz_bron.ref_id(jr.get("Account"))
        d, c = rlz_bron.debet_credit(jr)
        datum = rlz_bron.journaalregel_datum(jr)
        tel(rlz, sleutel_voor_ledger(ledger_id), d - c, datum)
        if rlz_bron.journaalregel_bron_id(jr) in bekende_bronnen:
            met_bron += 1
    n_jr = len(bron.journaalregels)
    jr_gelezen = "JournalEntryLines" in bron.gelezen
    if not jr_gelezen:
        rlz_kolom = (
            "RLZ-kolom NIET beschikbaar: JournalEntryLines niet leesbaar — een terugval op Ledgers-saldi per datum "
            "kent de RLZ-API niet als bewezen route (STAP-0 nodig); kolom toont € 0,00 en telt niet als sluitend"
        )
    elif n_jr and met_bron == 0:
        rlz_kolom = (
            "EventID-koppeling KLOPT NIET (0 journaalregels treffen een bekend document/mutatie) — de RLZ-kolom blijft "
            "de som per grootboek uit JournalEntryLines (koppeling per document is daarvoor niet nodig)"
        )
    elif n_jr:
        rlz_kolom = f"EventID-koppeling herkend op {met_bron}/{n_jr} journaalregels; RLZ-kolom = som per grootboek"
    else:
        rlz_kolom = "JournalEntryLines leeg — RLZ-kolom € 0,00"
    rapport.journaal = {
        "regels": n_jr,
        "met_bron": met_bron,
        "zonder_bron": n_jr - met_bron,
        "gelezen": jr_gelezen,
        "rlz_kolom": rlz_kolom,
    }

    herclass: dict[tuple[str, str], list[Any]] = {}
    for v in alle:
        if v.move.move_type == "bank_direct":
            continue  # telt via de bankregel (tegenregel)
        for r in v.regels:
            datum = date.fromisoformat(r.datum) if r.datum else None
            if r.rekening.startswith("ongemapt:") and r.rlz_ledger_id:
                s = sleutel_voor_ledger(r.rlz_ledger_id)
            else:
                s = r.rekening
                omschr.setdefault(s, s)
            tel(odoo, s, r.debet - r.credit, datum)
        for van, naar, bedrag in v.herclassificaties:
            h = herclass.setdefault((van, naar), [NUL, NUL, 0])
            datum = date.fromisoformat(v.move.date) if v.move.date else None
            if datum and datum <= jaareinde:
                h[0] += bedrag
            if datum and datum <= tot:
                h[1] += bedrag
            h[2] += 1
    rapport.herclassificaties = [
        {"van": van, "naar": naar, "bedrag": h[1], "bedrag_jaareinde": h[0], "documenten": h[2]}
        for (van, naar), h in sorted(herclass.items())
    ]
    schoon_je: dict[str, Decimal] = {}
    schoon_tot: dict[str, Decimal] = {}
    for (van, naar), h in herclass.items():
        schoon_je[van] = schoon_je.get(van, NUL) + h[0]
        schoon_je[naar] = schoon_je.get(naar, NUL) - h[0]
        schoon_tot[van] = schoon_tot.get(van, NUL) + h[1]
        schoon_tot[naar] = schoon_tot.get(naar, NUL) - h[1]

    rijen = []
    for s in sorted(set(rlz) | set(odoo), key=lambda x: (x.startswith(("impliciet", "bank:", "ongemapt", "rol:")), x)):
        r_je, r_tot = rlz.get(s, [NUL, NUL])
        o_je, o_tot = odoo.get(s, [NUL, NUL])
        v_je = (o_je - r_je).quantize(Decimal("0.01"))
        v_tot = (o_tot - r_tot).quantize(Decimal("0.01"))
        rijen.append(
            {
                "rekening": s,
                "omschrijving": omschr.get(s, s),
                "rlz_jaareinde": r_je.quantize(Decimal("0.01")),
                "odoo_jaareinde": o_je.quantize(Decimal("0.01")),
                "verschil_jaareinde": v_je,
                "verschil_jaareinde_geschoond": (v_je + schoon_je.get(s, NUL)).quantize(Decimal("0.01")),
                "rlz_tot": r_tot.quantize(Decimal("0.01")),
                "odoo_tot": o_tot.quantize(Decimal("0.01")),
                "verschil_tot": v_tot,
                "verschil_tot_geschoond": (v_tot + schoon_tot.get(s, NUL)).quantize(Decimal("0.01")),
            }
        )
    rapport.saldibalans = rijen


def _open_posten(rapport: ReplayRapport, documenten: list[Vertaald], bankregels: list[Vertaald]) -> None:
    gekoppeld: dict[str, Decimal] = {}
    for b in bankregels:
        for rc in (b.move.bank or {}).get("reconcile", []):
            gekoppeld[rc["anker"]] = gekoppeld.get(rc["anker"], NUL) + (rc["bedrag"] or NUL)
    kandidaten: list[dict[str, Any]] = []
    for v in documenten:
        if v.move.move_type in ("entry", "bank_direct") or v.bedrag is None:
            continue
        rlz_open = v.open_bedrag if v.open_bedrag is not None else NUL
        som_koppelingen = gekoppeld.get(v.move.anker, NUL)
        berekend = (v.bedrag - som_koppelingen).quantize(Decimal("0.01"))
        kandidaten.append(
            {
                "boekstuk": v.move.boekstuk,
                "anker": v.move.anker,
                "move_type": v.move.move_type,
                "entity_id": v.entity_id,
                "bedrag": v.bedrag,
                "rlz_open": rlz_open,
                "berekend_open": berekend,
                "som_koppelingen": som_koppelingen.quantize(Decimal("0.01")),
                "oorzaak": "",
                "verrekend_met": None,
            }
        )
    # Blok 7b punt 4: factuur↔creditnota-verrekening in RLZ (beide open 0 in RLZ, berekend +X en −X, zelfde relatie,
    # zelfde kant in/out) als PAAR lezen → berekend 0 voor beide; de export krijgt het paar als reconcile-voorstel.
    # RLZ's eigen verrekeningsspoor (actie 34) is niet als leesroute bewezen → herkomst "afgeleid uit bedrag + relatie".
    verrekeningen: list[dict[str, Any]] = []
    open_kandidaten = [k for k in kandidaten if k["rlz_open"] == 0 and k["berekend_open"] != 0]
    gebruikt: set[str] = set()
    for a in open_kandidaten:
        if a["anker"] in gebruikt:
            continue
        kant_a = "in" if a["move_type"].startswith("in_") else "out"
        for b in open_kandidaten:
            if b["anker"] in gebruikt or b is a:
                continue
            kant_b = "in" if b["move_type"].startswith("in_") else "out"
            if kant_a != kant_b or a["entity_id"] != b["entity_id"] or a["entity_id"] is None:
                continue
            if a["berekend_open"] + b["berekend_open"] != 0:
                continue
            gebruikt.update({a["anker"], b["anker"]})
            factuur, credit = (a, b) if a["berekend_open"] > 0 else (b, a)
            verrekeningen.append(
                {
                    "factuur": factuur["boekstuk"],
                    "factuur_anker": factuur["anker"],
                    "creditnota": credit["boekstuk"],
                    "creditnota_anker": credit["anker"],
                    "bedrag": factuur["berekend_open"],
                    "herkomst": "afgeleid uit bedrag + relatie (RLZ-verrekeningsspoor niet gelezen)",
                }
            )
            for k in (a, b):
                k["verrekend_met"] = b["boekstuk"] if k is a else a["boekstuk"]
                k["berekend_open"] = NUL
                k["oorzaak"] = f"verrekend factuur↔creditnota met {k['verrekend_met']} (afgeleid)"
            break
    rijen = []
    for k in kandidaten:
        verschil = (k["berekend_open"] - k["rlz_open"]).quantize(Decimal("0.01"))
        if k["rlz_open"] == 0 and k["berekend_open"] == 0:
            continue
        if verschil != 0 and not k["oorzaak"]:
            if k["som_koppelingen"] and abs(k["som_koppelingen"]) != abs(k["bedrag"]):
                k["oorzaak"] = (
                    f"koppelingen som € {k['som_koppelingen']} ≠ documenttotaal € {k['bedrag']} (Δ {verschil}) — "
                    "mogelijk betalingsverschil-afboeking in RLZ; niet stil afgerond, controleren"
                )
            elif not k["som_koppelingen"]:
                k["oorzaak"] = "RLZ open 0 zonder gekoppelde bankmutatie of tegenpost — verrekening/afboeking in RLZ?"
            else:
                k["oorzaak"] = "open in RLZ ≠ berekend"
        rijen.append(
            {
                "boekstuk": k["boekstuk"],
                "anker": k["anker"],
                "move_type": k["move_type"],
                "bedrag": k["bedrag"],
                "rlz_open": k["rlz_open"],
                "berekend_open": k["berekend_open"],
                "verschil": verschil,
                "oorzaak": k["oorzaak"],
            }
        )
    rapport.open_posten = sorted(rijen, key=lambda r: (r["verschil"] == 0, r["boekstuk"] or ""))
    rapport.verrekeningen = verrekeningen
    rapport.open_bank = [
        {
            "boekstuk": b.move.boekstuk,
            "anker": b.move.anker,
            "date": b.move.date,
            "bedrag": b.bedrag,
            "open_bedrag": b.open_bedrag,
        }
        for b in bankregels
        if b.open_bedrag is not None and b.open_bedrag != 0
    ]
    rapport.som_verschillen = [
        {
            "boekstuk": v.move.boekstuk,
            "move_type": v.move.move_type,
            "bedrag": v.bedrag,
            "som_verschil": v.som_verschil,
        }
        for v in documenten
        if v.som_verschil is not None and v.som_verschil != 0
    ]


def _per_pand(rapport: ReplayRapport, alle: list[Vertaald]) -> None:
    """Blok 7b punt 5: één bron — dezelfde afleiding als het pandenregister (documenten ÉN bankmutaties; in de dry-run
    in-memory, ná `--schrijf` de `pand_boeking`-rijen via `pand_per_document`); marge alleen bij verkoop."""
    per: dict[str, dict[str, Any]] = {}
    for v in alle:
        p = v.pand
        if not vertaling.pand_telt(p) or p is None or v.bedrag is None:
            continue
        rij = per.setdefault(
            p.pand_code,
            {
                "pand": f"{p.pand_code} — {p.adres}",
                "aankoop": NUL,
                "aanbetalingen": NUL,
                "kosten": NUL,
                "verkoop": NUL,
                "documenten": 0,
            },
        )
        rij["documenten"] += 1
        b = abs(v.bedrag)
        if p.soort == "aankoop":
            rij["aankoop"] += b
        elif p.soort == "aanbetaling":
            rij["aanbetalingen"] += b
        elif p.soort in ("kosten", "vaste_lasten"):
            rij["kosten"] += b
        elif p.soort == "verkoop":
            rij["verkoop"] += b
    for rij in per.values():
        rij["marge"] = (
            (rij["verkoop"] - rij["aankoop"] - rij["kosten"]).quantize(Decimal("0.01")) if rij["verkoop"] else None
        )
    rapport.per_pand = [per[k] for k in sorted(per)]


def _tabellen(ctx: Context, rapport: ReplayRapport, alle: list[Vertaald], bron: rlz_bron.RlzBron) -> None:
    def rij(v: Vertaald) -> dict[str, Any]:
        return {
            "boekstuk": v.move.boekstuk,
            "anker": v.move.anker,
            "move_type": v.move.move_type,
            "date": v.move.date,
            "bedrag": v.bedrag,
            "reden": v.move.reden,
        }

    rapport.niet_vertaalbaar = [rij(v) for v in alle if v.move.status == vertaling.STATUS_NIET]
    rapport.zonder_pand = [rij(v) for v in alle if v.move.status == vertaling.STATUS_ZONDER_PAND]
    ongemapt: dict[str, dict[str, Any]] = {}
    for v in alle:
        for lid in v.ongemapt:
            code, naam, t = ctx.ledgers.get(lid, (None, None, None))
            o = ongemapt.setdefault(
                lid,
                {
                    "rlz_ledger_id": lid,
                    "rlz_code": code,
                    "rlz_naam": naam,
                    "account_type": t,
                    "regels": 0,
                    "documenten": 0,
                },
            )
            o["documenten"] += 1
            o["regels"] += sum(1 for r in v.regels if r.rlz_ledger_id == lid)
    rapport.ongemapt = sorted(ongemapt.values(), key=lambda o: (o["rlz_code"] or "", o["rlz_ledger_id"]))
    partners: dict[tuple[str, str], dict[str, Any]] = {}
    for v in alle:
        p = v.partner
        if p is None or p.voorstel == "n.v.t.":
            continue
        sleutelwaarde = p.kvk or p.btw or p.iban or p.naam or "?"
        rij_p = partners.setdefault(
            (p.sleutel, sleutelwaarde),
            {
                "naam": p.naam,
                "sleutel": p.sleutel,
                "kvk": p.kvk,
                "btw": p.btw,
                "iban": p.iban,
                "voorstel": p.voorstel,
                "documenten": 0,
            },
        )
        rij_p["documenten"] += 1
    rapport.partners = sorted(partners.values(), key=lambda p: (p["voorstel"], p["naam"] or ""))


def _iban_schoon(waarde: object) -> str | None:
    if not isinstance(waarde, str):
        return None
    schoon = "".join(ch for ch in waarde.upper() if ch.isalnum())
    return schoon if len(schoon) >= 15 and schoon[:2].isalpha() else None


def _journals_per_rekening(rekeningen: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """(rekening-id → journal-sleutel, journal-sleutel → weergavenaam). Twee RLZ-rekeningen met dezelfde IBAN
    (schoonlijst-categorie "dubbele IBAN": NL95INGB0114119295) = ÉÉN Odoo-journal (blok 7b punt 3)."""
    sleutel: dict[str, str] = {}
    namen: dict[str, str] = {}
    for r in rekeningen:
        rid = str(r.get("id") or "")
        if not rid:
            continue
        iban = _iban_schoon(r.get("IBAN")) or _iban_schoon(r.get("AccountNumber")) or _iban_schoon(r.get("Number"))
        js = iban or rid
        sleutel[rid] = js
        naam = str(r.get("Name") or r.get("Description") or iban or rid)
        if js not in namen:
            namen[js] = f"{iban} · {naam}" if iban else naam
        elif naam not in namen[js]:
            namen[js] += f" + {naam}"
    return sleutel, namen


def _statements(rapport: ReplayRapport, bron: rlz_bron.RlzBron, bankregels: list[Vertaald], *, tot: date) -> None:
    """Blok 7b punt 3 (besluit-vorm voor Peter): RLZ heeft voor VGG géén `/Statements`-koppen → één
    `account.bank.statement` per maand per journal met `balance_end_real` = LOPEND SALDO berekend uit de
    PaymentTransactions (beginsaldo 0 bij de start van de administratie). Handmatige toets: het rapport toont het
    berekende saldo per 31-12-2025 en per `tot` zodat Peter dat naast het echte banksaldo legt."""
    jaareinde = date.fromisoformat(PEILDATUM_JAAREINDE)
    per_rek_journal, namen = _journals_per_rekening(bron.rekeningen)
    per_journal: dict[str, list[Vertaald]] = {}
    for b in bankregels:
        if not b.move.date:
            continue
        rek = (b.move.bank or {}).get("rekening_rlz_id") or "?"
        per_journal.setdefault(per_rek_journal.get(rek, rek), []).append(b)
    rijen = []
    toets = []
    for js in sorted(per_journal):
        regels = sorted(per_journal[js], key=lambda b: (b.move.date or "", b.move.boekstuk or ""))
        saldo = NUL
        saldo_je: Decimal | None = None
        saldo_tot: Decimal | None = None
        per_maand: dict[str, dict[str, Any]] = {}
        for b in regels:
            d = date.fromisoformat(b.move.date or "")
            m = per_maand.setdefault(
                (b.move.date or "")[:7], {"regels": 0, "som": NUL, "beginsaldo": saldo, "eindsaldo": saldo}
            )
            saldo += b.bedrag or NUL
            m["regels"] += 1
            m["som"] += b.bedrag or NUL
            m["eindsaldo"] = saldo
            if d <= jaareinde:
                saldo_je = saldo
            if d <= tot:
                saldo_tot = saldo
            b.move.bank = {**(b.move.bank or {}), "statement_maand": (b.move.date or "")[:7], "journal_sleutel": js}
        rekening_ids = [rid for rid, j in per_rek_journal.items() if j == js] or [js]
        koppen_totaal = sum(
            1
            for rid in rekening_ids
            for st in bron.statements.get(rid, [])
            if str(st.get("Number")) != VIRTUEEL_AFSCHRIFT
        )
        for maand, m in sorted(per_maand.items()):
            koppen = [
                st
                for rid in rekening_ids
                for st in bron.statements.get(rid, [])
                if (als_datum(st.get("Date")) or date.min).isoformat()[:7] == maand
                and str(st.get("Number")) != VIRTUEEL_AFSCHRIFT
            ]
            koppen.sort(key=lambda st: (als_datum(st.get("Date")) or date.min, str(st.get("Number") or "")))
            eind_rlz = _eerste_bedrag(koppen[-1], _EINDSALDO_SLEUTELS) if koppen else None
            begin_rlz = _eerste_bedrag(koppen[0], _BEGINSALDO_SLEUTELS) if koppen else None
            eind_berekend = m["eindsaldo"].quantize(Decimal("0.01"))
            balance_end_real = eind_berekend
            if not koppen:
                sluit = "geen afschrift-kop in RLZ — balance_end_real = berekend lopend saldo"
            elif eind_rlz is None or begin_rlz is None:
                sluit = f"saldo-veld ontbreekt op /Statements (velden: {', '.join(sorted(koppen[-1].keys()))[:80]})"
            elif (begin_rlz + m["som"]).quantize(Decimal("0.01")) == eind_rlz:
                balance_end_real = eind_rlz  # RLZ kent het echte saldo → dat wint van het berekende (beginsaldo 0)
                offset = (eind_rlz - eind_berekend).quantize(Decimal("0.01"))
                sluit = "ja (RLZ-kop sluit op de som" + (
                    f"; RLZ-saldo = berekend + € {offset} = beginsaldo vóór de eerste mutatie)" if offset else ")"
                )
            else:
                som_m = m["som"].quantize(Decimal("0.01"))
                sluit = f"NEE (RLZ-kop: begin € {begin_rlz} + som € {som_m} ≠ eind € {eind_rlz})"
            rijen.append(
                {
                    "rekening": namen.get(js, js),
                    "journal_sleutel": js,
                    "rekening_rlz_ids": rekening_ids,
                    "maand": maand,
                    "regels": m["regels"],
                    "som": m["som"].quantize(Decimal("0.01")),
                    "beginsaldo": m["beginsaldo"].quantize(Decimal("0.01")),
                    "eindsaldo": eind_berekend,
                    "balance_end_real": balance_end_real,
                    "eindsaldo_rlz_kop": eind_rlz,
                    "sluit": sluit,
                    "afschriften": len(koppen),
                }
            )
        toets.append(
            {
                "rekening": namen.get(js, js),
                "journal_sleutel": js,
                "rlz_rekeningen": len(rekening_ids),
                "regels": len(regels),
                "saldo_jaareinde": (saldo_je if saldo_je is not None else NUL).quantize(Decimal("0.01")),
                "saldo_tot": (saldo_tot if saldo_tot is not None else NUL).quantize(Decimal("0.01")),
                "afschrift_koppen_rlz": koppen_totaal,
                "eerste_mutatie": regels[0].move.date if regels else None,
                "laatste_mutatie": regels[-1].move.date if regels else None,
            }
        )
    rapport.statements = rijen
    rapport.saldo_toets = toets


def _eerste_bedrag(kop: dict[str, Any], sleutels: tuple[str, ...]) -> Decimal | None:
    for s in sleutels:
        b = als_bedrag(kop.get(s))
        if b is not None:
            return b
    return None


def _btw(ctx: Context, rapport: ReplayRapport, alle: list[Vertaald], *, tot: date) -> None:
    """Besluit Peter 13-09: rapporteer de afmeldingsdatum zoals die uit de data blijkt (laatste btw-regel / laatste
    OB-mutatie) en het restsaldo van "Btw-afwikkeling historisch" per 31-12-2025 en per vandaag."""
    rol_id = ctx.rollen.btw_afwikkeling_historisch
    rek = str(rol_id) if rol_id is not None else vertaling.ROL_BTW_PSEUDO
    laatste_btw: str | None = None
    laatste_ob: str | None = None
    btw_docs = 0
    ob_docs = 0
    btw_som = NUL
    for v in alle:
        if v.btw_regels:
            btw_docs += 1
            if v.move.date and (laatste_btw is None or v.move.date > laatste_btw):
                laatste_btw = v.move.date
        if v.ob_afwikkeling:
            ob_docs += 1
            if v.move.date and (laatste_ob is None or v.move.date > laatste_ob):
                laatste_ob = v.move.date
        btw_som += v.btw_bedrag
    rij = next((r for r in rapport.saldibalans if r["rekening"] == rek), None)
    ledgers = sorted(
        (ctx.ledgers.get(lid, (None, None, None))[0] or "?", ctx.ledgers.get(lid, (None, None, None))[1] or lid)
        for lid in ctx.btw_ledgers
    )
    kandidaten = [d for d in (laatste_btw, laatste_ob) if d]
    rapport.btw = {
        "rol_ingesteld": rol_id,
        "rekening": rek,
        "btw_regels": rapport.tellers.get("btw_regels", 0),
        "documenten_met_btw": btw_docs,
        "documenten_ob_afwikkeling": ob_docs,
        "btw_bedrag_totaal": btw_som.quantize(Decimal("0.01")),
        "laatste_btw_regel": laatste_btw,
        "laatste_ob_mutatie": laatste_ob,
        "afmeldingsdatum_uit_data": max(kandidaten) if kandidaten else None,
        "restsaldo_jaareinde": rij["odoo_jaareinde"] if rij else NUL,
        "restsaldo_tot": rij["odoo_tot"] if rij else NUL,
        "btw_ledgers": [{"code": c, "naam": n} for c, n in ledgers],
        "peildatum": tot.isoformat(),
    }


def _export(rapport: ReplayRapport) -> None:
    export: dict[str, list[dict[str, Any]]] = {}
    fallback = False
    for mt in EXPORT_TYPES:
        kandidaten = sorted(
            (m for m in rapport.moves if m.move_type == mt and m.status == vertaling.STATUS_VERTAALBAAR and m.date),
            key=lambda m: (m.date or "", m.boekstuk or ""),
        )
        juli = [m for m in kandidaten if (m.date or "").startswith(EXPORT_MAAND)]
        keuze = juli[:3]
        if not keuze and kandidaten:
            keuze = kandidaten[:3]
            fallback = True
        export[mt] = [_compact(m) for m in keuze]
    rapport.export = export
    if fallback:
        rapport.export_melding = (
            f"geen (voldoende) vertaalbare documenten in {EXPORT_MAAND} voor elk type — vroegste 3 getoond"
        )


def _compact(m: MoveVoorstel) -> dict[str, Any]:
    return {
        "anker": m.anker,
        "boekstuk": m.boekstuk,
        "move_type": m.move_type,
        "date": m.date,
        "vals": m.vals,
        "bank": m.bank,
    }
