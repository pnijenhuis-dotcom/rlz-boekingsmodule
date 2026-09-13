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
tegen te matchen: alleen gebruikt om pand-codes in het rapport te verrijken, nooit als bron van een boeking.

Blok 7c 13-09 (fixes uit de productienameting 13-09, besluit Peter): (1) > 0 geboekte documenten zonder leesbare
regels = oordeel "ONVOLLEDIG — niet doorrekenen" mét lijst — geen saldibalans-toets, open posten, per pand,
statements, btw of export op halve data; (2) de EventID-koppeling bestaat niet (STAP-0) — het rapport toont per
DocumentType het aantal journaalposten naast het aantal geboekte documenten; (3) `date` = `BookDate` uit de document-
vorm (`bron.rij_met_kop`), teller BookDate/Date-terugval; (4) pandenmodel op grootboek-regels (aankoop = 7000-regels +
koopsom-regel van een aankoop-memoriaal, verkoop = opbrengst-regels, kosten = overige kostenregels, notaris-ontvangst
= alleen bank; vaste activa nooit; controle verkoop − aankoop − kosten − notaris = 0 ± aanbetalingen); (5) btw tweede
bron: journaalregels op RLZ-btw-grootboeken + regels mét btw-code zonder bedrag; (6) partner uit de tegenpartij van de
bankmutatie, rest = beslispunt; (7) saldibalans: afletter-/tegenzijde-GROEPEN (crediteuren, debiteuren, bank,
tussenrekening) tellen op groepsniveau, niet per rekening (de dry-run simuleert geen reconcile)."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import replace
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
        vaste_activa_ledgers=vertaling.vaste_activa_uit(bron.ledgers),
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
    als B's module ontbreekt (dan alleen DB-rijen). Blok 7c: óók CONCEPTEN (voor het signaal "verkoopfactuur nog
    concept in RLZ") en mét de grootboekcodes van de gelezen regels (`grootboeken`), zodat de afleiding een notaris-
    inkoopfactuur mét 7000-regel als `aankoop` classificeert en een vast-actief-factuur (0101) aan geen pand hangt."""
    try:
        from app.panden.service import _naar_bankmutatie, _naar_boeking  # noqa: PLC0415 — B bouwt 'm parallel
    except ImportError:
        return None
    ledgers = vertaling.ledgers_index(bron.ledgers)
    vaste_activa = vertaling.vaste_activa_uit(bron.ledgers)
    uit = []
    for pad, rij in bron.alle_documenten():
        if pad in ("PurchaseInvoices", "SalesInvoices", "ManualJournals") and (
            rlz_bron.is_geboekt(rij) or rlz_bron.is_concept(rij)
        ):
            b = _naar_boeking(pad, bron.rij_met_kop(rij))
            if b is None:
                continue
            regels = bron.regels.get(rlz_bron.doc_id(rij) or "")
            if regels:
                codes = set()
                vast = set()
                for r in regels:
                    lid = rlz_bron.ref_id(r.get("Account")) or ""
                    code = ledgers.get(lid, (None, None, None))[0]
                    if code:
                        codes.add(str(code))
                        if lid in vaste_activa:
                            vast.add(str(code))
                b = replace(b, grootboeken=frozenset(codes), vaste_activa=frozenset(vast))
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
        "regels_via_documentvorm": bron.regels_via_documentvorm,
        "regels_via_lines": bron.regels_via_lines,
        "rlz_calls": bron.client_calls,
        "webfilter_treffers": bron.webfilter_treffers,
        "gewacht_seconden": bron.gewacht_seconden,
    }


# ---- vertaling + rapport ---------------------------------------------------------------------------------------


def _vertaal_en_rapporteer(ctx: Context, bron: rlz_bron.RlzBron, rapport: ReplayRapport, *, tot: date) -> None:
    open_bank = rlz_bron.open_bank_sleutels(bron.bank)
    tegenpartijen = vertaling.bank_tegenpartijen(bron.bank)
    per_collectie: dict[str, dict[str, int]] = {}
    documenten: list[Vertaald] = []
    concepten: list[tuple[str, dict[str, Any]]] = []
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
            concepten.append((pad, rij))
            continue
        if not rlz_bron.is_geboekt(rij):
            tel["niet_migreren"] += 1
            continue
        tel["geboekt"] += 1
        regels = bron.regels.get(rid)
        documenten.append(
            vertaling.vertaal_document(ctx, pad, bron.rij_met_kop(rij), regels, bank_tegenpartij=tegenpartijen.get(rid))
        )
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
    _onvolledig(rapport, bron, documenten)
    _tabellen(ctx, rapport, alle, bron)
    _journaal(ctx, rapport, bron, documenten)
    if rapport.onvolledig:
        # blok 7c punt 1: halve regel-data = geen saldibalans-toets, geen open posten/per pand/statements/btw/export
        rapport.let_op.append(
            f"{rlz_bron.ONVOLLEDIG_TEKST}: {len(rapport.onvolledig)} geboekt(e) document(en) zonder leesbare regels — "
            "saldibalans, open posten, per pand, statements, btw en export niet berekend"
        )
        return
    _saldibalans(ctx, bron, rapport, alle, tot=tot)
    _open_posten(rapport, documenten, bankregels)
    _per_pand(ctx, rapport, alle, concepten)
    _statements(rapport, bron, bankregels, tot=tot)
    _btw(ctx, rapport, alle, bron, tot=tot)
    _export(rapport)


def _onvolledig(rapport: ReplayRapport, bron: rlz_bron.RlzBron, documenten: list[Vertaald]) -> None:
    """Blok 7c punt 1: de lijst geboekte documenten zonder leesbare regels (boekstuk, type, datum, bedrag, route)."""
    rapport.onvolledig = [
        {
            "boekstuk": v.move.boekstuk,
            "rlz_id": v.move.rlz_id,
            "move_type": v.move.move_type,
            "date": v.move.date,
            "bedrag": v.bedrag,
            "route": bron.regel_fouten.get(v.move.rlz_id, "regels niet leesbaar"),
        }
        for v in documenten
        if v.zonder_regels
    ]


def _tellers(
    rapport: ReplayRapport, per_collectie: dict[str, dict[str, int]], alle: list[Vertaald], bron: rlz_bron.RlzBron
) -> None:
    per_type: dict[str, dict[str, int]] = {}
    btw_regels = 0
    btw_docs = 0
    btw_code_zonder_bedrag = 0
    p_nieuw = 0
    p_uit_bank = 0
    p_onbekend = 0
    bookdate = 0
    date_terugval = 0
    for v in alle:
        t = per_type.setdefault(v.move.move_type, {"vertaalbaar": 0, "zonder_pand": 0, "niet_vertaalbaar": 0})
        t[v.move.status] += 1
        if v.btw_regels:
            btw_regels += v.btw_regels
            btw_docs += 1
        btw_code_zonder_bedrag += v.btw_code_zonder_bedrag
        if v.partner and v.partner.voorstel == "nieuw (res.partner)":
            p_nieuw += 1
            if v.partner.herkomst == "bank":
                p_uit_bank += 1
        elif v.partner and v.partner.voorstel == "onbekend":
            p_onbekend += 1
        if v.move.move_type != "bank":
            if v.boekdatum_herkomst == "BookDate":
                bookdate += 1
            elif v.boekdatum_herkomst == "Date":
                date_terugval += 1
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
        "btw_code_zonder_bedrag": btw_code_zonder_bedrag,
        "partners_nieuw": p_nieuw,
        "partners_uit_bank": p_uit_bank,
        "partners_onbekend": p_onbekend,
        "bookdate_uit_document": bookdate,
        "bookdate_terugval_date": date_terugval,
        "bank_expand_gelukt": bron.bank_expand_gelukt,
    }


def _journaal(ctx: Context, rapport: ReplayRapport, bron: rlz_bron.RlzBron, documenten: list[Vertaald]) -> None:
    """Blok 7c punt 2: er ís geen koppeling journaalregel ↔ document in de RLZ-API (STAP-0 13-09: `EventID` =
    soortcode). Het rapport zegt dat letterlijk en toont per DocumentType het aantal journaalposten (unieke
    `JournalEntry.id`) naast het aantal geboekte documenten van dat type — een volledigheidstoets zonder koppeling per
    regel."""
    n_jr = len(bron.journaalregels)
    posten: dict[int | None, set[str]] = {}
    regels_per_type: dict[int | None, int] = {}
    for jr in bron.journaalregels:
        dt = rlz_bron.journaalregel_documenttype(jr)
        regels_per_type[dt] = regels_per_type.get(dt, 0) + 1
        jid = rlz_bron.journaalregel_journaalpost_id(jr)
        if jid:
            posten.setdefault(dt, set()).add(jid)
    docs_per_type: dict[int | None, int] = {}
    for v in documenten:
        dt = {"in_invoice": 1, "in_refund": 1, "out_invoice": 10, "out_refund": 10, "entry": 11, "bank_direct": 19}.get(
            v.move.move_type
        )
        docs_per_type[dt] = docs_per_type.get(dt, 0) + 1
    per_type = [
        {
            "documenttype": dt,
            "naam": rlz_bron.DOCTYPE_NAMEN.get(dt, f"overig ({dt})") if dt is not None else "onbekend",
            "journaalposten": len(posten.get(dt, set())),
            "journaalregels": regels_per_type.get(dt, 0),
            "documenten_geboekt": docs_per_type.get(dt, 0),
        }
        for dt in sorted(set(regels_per_type) | set(docs_per_type), key=lambda x: (x is None, x or 0))
    ]
    jr_gelezen = "JournalEntryLines" in bron.gelezen
    if not jr_gelezen:
        rlz_kolom = (
            "RLZ-kolom NIET beschikbaar: JournalEntryLines niet leesbaar — een terugval op Ledgers-saldi per datum "
            "kent de RLZ-API niet als bewezen route (STAP-0 nodig); kolom toont € 0,00 en telt niet als sluitend"
        )
    elif n_jr:
        rlz_kolom = (
            "koppeling journaalregel ↔ document bestaat niet in de RLZ-API (JournalEntry draagt alleen id/BookDate/"
            "DocumentType/EventID = soortcode, STAP-0 13-09) — RLZ-kolom = som per grootboek; BookDate per document "
            "komt van de document-vorm"
        )
    else:
        rlz_kolom = "JournalEntryLines leeg — RLZ-kolom € 0,00"
    rapport.journaal = {
        "regels": n_jr,
        "gelezen": jr_gelezen,
        "rlz_kolom": rlz_kolom,
        "per_documenttype": per_type,
    }


#: RLZ-bankgrootboeken zonder `UseForPaymentAccount`-vlag op de Ledgers-rij: naam mét IBAN/bank/ING/spaar-/betaalrek.
_BANK_LEDGER_REGEX = re.compile(r"\bbank\b|\bING\b|\bNL\d{2}[A-Z]{4}\w*|spaarrekening|betaalrekening|\bkas\b", re.I)
_GROEP_REGEX: tuple[tuple[str, str, str], ...] = (
    ("crediteuren", r"\bcrediteuren\b", "afletter-afhankelijk: inkoopfacturen ↔ betalingen/verrekeningen"),
    ("debiteuren", r"\bdebiteuren\b", "afletter-afhankelijk: verkoopfacturen ↔ ontvangsten/verrekeningen"),
    ("tussenrekening", r"nog te rubriceren|kruisposten|tussenrekening", "open/ongekoppelde bankmutaties"),
)


def afletter_groepen(ctx: Context, sleutel_voor_ledger: Callable[[str | None], str]) -> dict[str, dict[str, Any]]:
    """Blok 7c punt 7, keuze (b): de rekeningen die alleen ná het afletteren netto sluiten (én de bankrekening, die
    zonder Odoo-id als `bank:<naam>` staat tegenover RLZ 1001) tellen niet per rekening maar per GROEP. RLZ-kant:
    grootboeken op Description-regex (crediteuren/debiteuren/nog te rubriceren|kruisposten|tussenrekening) resp.
    `UseForPaymentAccount`/bank-naam; Odoo-kant: de impliciete pseudo-sleutels, de doel-id's en dezelfde RLZ-
    grootboeken vertaald. Deterministisch en in het rapport benoemd per groep."""
    groepen: dict[str, dict[str, Any]] = {
        naam: {"reden": reden, "sleutels": set(), "rlz_codes": []} for naam, _rx, reden in _GROEP_REGEX
    }
    groepen["bank"] = {
        "reden": "bankrekening zonder Odoo-id in de doelkoppeling (bank:<naam> ↔ RLZ 1001)",
        "sleutels": set(),
        "rlz_codes": [],
    }
    for lid, (code, naam, _t) in ctx.ledgers.items():
        tekst = f"{naam or ''}"
        for g, rx, _r in _GROEP_REGEX:
            if re.search(rx, tekst, re.I):
                groepen[g]["sleutels"].add(sleutel_voor_ledger(lid))
                groepen[g]["rlz_codes"].append(code or lid)
        if _BANK_LEDGER_REGEX.search(tekst):
            groepen["bank"]["sleutels"].add(sleutel_voor_ledger(lid))
            groepen["bank"]["rlz_codes"].append(code or lid)
    groepen["crediteuren"]["sleutels"].add(vertaling.IMPLICIET_CREDITEUREN)
    groepen["debiteuren"]["sleutels"].add(vertaling.IMPLICIET_DEBITEUREN)
    groepen["tussenrekening"]["sleutels"].add(vertaling.IMPLICIET_TUSSENREKENING)
    if ctx.doel.rekening_crediteuren_id:
        groepen["crediteuren"]["sleutels"].add(str(ctx.doel.rekening_crediteuren_id))
    if ctx.doel.rekening_debiteuren_id:
        groepen["debiteuren"]["sleutels"].add(str(ctx.doel.rekening_debiteuren_id))
    for oid in ctx.doel.rekening_bank_ids.values():
        groepen["bank"]["sleutels"].add(str(oid))
    return groepen


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

    bank_ledgers: set[str] = set()
    for r in bron.ledgers:
        lid = rlz_bron.doc_id(r)
        if lid and (r.get("UseForPaymentAccount") is True):
            bank_ledgers.add(sleutel_voor_ledger(lid))
    for jr in bron.journaalregels:
        ledger_id = rlz_bron.ref_id(jr.get("Account"))
        d, c = rlz_bron.debet_credit(jr)
        datum = rlz_bron.journaalregel_datum(jr)
        tel(rlz, sleutel_voor_ledger(ledger_id), d - c, datum)

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

    # blok 7c punt 7 (b): groepen — bank-pseudo-sleutels + RLZ-bankgrootboeken horen bij groep "bank"
    groepen = afletter_groepen(ctx, sleutel_voor_ledger)
    groepen["bank"]["sleutels"] |= bank_ledgers
    groepen["bank"]["sleutels"] |= {s for s in set(rlz) | set(odoo) if s.startswith("bank:")}
    groep_van: dict[str, str] = {}
    for g, info in groepen.items():
        for sl in info["sleutels"]:
            groep_van[sl] = g

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
                "groep": groep_van.get(s),
            }
        )
    rapport.saldibalans = rijen
    groep_rijen = []
    for g, info in groepen.items():
        leden = [r for r in rijen if r["groep"] == g]
        if not leden:
            continue
        r_je = sum((r["rlz_jaareinde"] for r in leden), NUL)
        o_je = sum((r["odoo_jaareinde"] for r in leden), NUL)
        r_tot = sum((r["rlz_tot"] for r in leden), NUL)
        o_tot = sum((r["odoo_tot"] for r in leden), NUL)
        s_je = sum((schoon_je.get(r["rekening"], NUL) for r in leden), NUL)
        s_tot = sum((schoon_tot.get(r["rekening"], NUL) for r in leden), NUL)
        groep_rijen.append(
            {
                "groep": g,
                "reden": info["reden"],
                "rekeningen": [r["rekening"] for r in leden],
                "rlz_jaareinde": r_je.quantize(Decimal("0.01")),
                "odoo_jaareinde": o_je.quantize(Decimal("0.01")),
                "verschil_jaareinde": (o_je - r_je + s_je).quantize(Decimal("0.01")),
                "rlz_tot": r_tot.quantize(Decimal("0.01")),
                "odoo_tot": o_tot.quantize(Decimal("0.01")),
                "verschil_tot": (o_tot - r_tot + s_tot).quantize(Decimal("0.01")),
            }
        )
    rapport.afletter_groepen = groep_rijen


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


AANKOOP_GROOTBOEKEN: frozenset[str] = frozenset({"7000"})  # RLZ "Inkopen vastgoed" (besluit Peter 13-09)
LEDGERTYPE_KOSTEN = 2


def _per_pand(
    ctx: Context, rapport: ReplayRapport, alle: list[Vertaald], concepten: list[tuple[str, dict[str, Any]]]
) -> None:
    """Blok 7c punt 4 (besluit Peter 13-09) — deterministisch op grootboek-REGELS, niet op het documentbedrag:
    aankoop = regels op 7000 (notaris-inkoopfactuur) + de koopsom-regel (rol voorraad_panden, activa) van een aankoop-
    memoriaal; verkoop = opbrengst-regels (AccountType 1, credit − debit) op documenten; kosten = overige kostenregels
    (AccountType 2 behalve 7000: 4601/4612/7001 …); aanbetalingen = documenten mét soort aanbetaling (documentbedrag);
    notaris-ontvangst = ALLEEN bankmutaties op het pand (netto, nooit verkoop of kosten). Regels op VASTE ACTIVA (0101
    Gebouwen en terreinen) tellen nergens. Controle per verkocht pand: verkoop − aankoop − kosten − notaris-ontvangst =
    0, anders "sluit ná aanbetalingen" als het verschil precies de aanbetalingen is, anders SIGNAAL. Een concept-
    verkoopfactuur op een pand mét notaris-ontvangst = signaal "verkoopfactuur nog concept in RLZ — boeken vóór
    replay"."""
    per: dict[str, dict[str, Any]] = {}

    def rij_voor(p: PandToewijzing) -> dict[str, Any]:
        return per.setdefault(
            p.pand_code,
            {
                "pand": f"{p.pand_code} — {p.adres}",
                "aankoop": NUL,
                "aanbetalingen": NUL,
                "kosten": NUL,
                "verkoop": NUL,
                "notaris_ontvangst": NUL,
                "documenten": 0,
                "zonder_regels": 0,
                "signalen": [],
            },
        )

    for v in alle:
        p = v.pand
        if not vertaling.pand_telt(p) or p is None or v.bedrag is None:
            continue
        rij = rij_voor(p)
        rij["documenten"] += 1
        if v.move.move_type == "bank":
            rij["notaris_ontvangst"] += v.bedrag  # netto: ontvangst +, betaling aan notaris −
            continue
        if v.zonder_regels:
            rij["zonder_regels"] += 1
        if p.soort == "aanbetaling":
            rij["aanbetalingen"] += abs(v.bedrag)
            continue
        for i, r in enumerate(x for x in v.regels if x.bron == "regel"):
            lid = r.rlz_ledger_id or ""
            if lid in ctx.vaste_activa_ledgers:
                continue  # vast actief: nooit aan een pand (Donkerslootstraat 105B, 0101)
            code, _naam, ltype = ctx.ledgers.get(lid, (None, None, None))
            saldo = r.debet - r.credit
            koopsom = p.soort == "aankoop" and v.koopsom_regel == i and ltype == vertaling.LEDGERTYPE_ACTIVA
            if (code or "") in AANKOOP_GROOTBOEKEN or koopsom:
                rij["aankoop"] += saldo
            elif ltype == vertaling.LEDGERTYPE_OPBRENGST:
                rij["verkoop"] += -saldo
            elif ltype == LEDGERTYPE_KOSTEN:
                rij["kosten"] += saldo
    # concept-verkoopfacturen op een pand (signaal, nooit een boeking)
    for pad, rij_c in concepten:
        rid = rlz_bron.doc_id(rij_c) or ""
        p = ctx.panden.get(uuid.UUID(rid)) if vertaling._is_uuid(rid) else None
        if p is None or not vertaling.pand_telt(p) or p.soort != "verkoop":
            continue
        if rlz_bron.documenttype_van(pad, rij_c) != rlz_bron.DOCTYPE_VERKOOP:
            continue
        rij = rij_voor(p)
        rij["signalen"].append(
            f"verkoopfactuur {rlz_bron.boekstuk_van(rij_c) or rid} nog concept in RLZ — boeken vóór replay"
        )
    for rij in per.values():
        verkocht = rij["verkoop"] != 0 or rij["notaris_ontvangst"] > 0
        rij["marge"] = (rij["verkoop"] - rij["aankoop"] - rij["kosten"]).quantize(Decimal("0.01")) if verkocht else None
        if rij["zonder_regels"]:
            rij["controle"] = f"onvolledig — {rij['zonder_regels']} document(en) zonder regels"
        elif not verkocht:
            rij["controle"] = "— (niet verkocht)"
        else:
            verschil = (rij["verkoop"] - rij["aankoop"] - rij["kosten"] - rij["notaris_ontvangst"]).quantize(
                Decimal("0.01")
            )
            if verschil == 0:
                rij["controle"] = "sluit"
            elif abs(verschil) == rij["aanbetalingen"].quantize(Decimal("0.01")) and rij["aanbetalingen"]:
                rij["controle"] = f"sluit ná aanbetalingen (Δ {verschil} = aanbetalingen)"
            else:
                rij["controle"] = f"SIGNAAL: sluit niet (Δ {verschil})"
                rij["signalen"].append(f"verkoop − aankoop − kosten − notaris-ontvangst = {verschil} (≠ 0)")
            if rij["verkoop"] == 0 and rij["notaris_ontvangst"] > 0:
                rij["signalen"].append("notaris-ontvangst zonder geboekte verkoopfactuur (opbrengst-regel ontbreekt)")
        if rij["marge"] is not None and rij["marge"] < 0 and not rij["signalen"]:
            rij["signalen"].append(f"negatieve marge {rij['marge']} zonder verklarende regel")
        rij["aankoop"] = rij["aankoop"].quantize(Decimal("0.01"))
        rij["kosten"] = rij["kosten"].quantize(Decimal("0.01"))
        rij["verkoop"] = rij["verkoop"].quantize(Decimal("0.01"))
        rij["notaris_ontvangst"] = rij["notaris_ontvangst"].quantize(Decimal("0.01"))
        rij["aanbetalingen"] = rij["aanbetalingen"].quantize(Decimal("0.01"))
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


def _btw(ctx: Context, rapport: ReplayRapport, alle: list[Vertaald], bron: rlz_bron.RlzBron, *, tot: date) -> None:
    """Besluit Peter 13-09: rapporteer de afmeldingsdatum zoals die uit de data blijkt (laatste btw-regel / laatste
    OB-mutatie) en het restsaldo van "Btw-afwikkeling historisch" per 31-12-2025 en per vandaag. Blok 7c punt 5: een
    TWEEDE bron — journaalregels op de RLZ-btw-grootboeken (aantal + Σ) — plus het aantal regels mét een btw-code maar
    TaxAmount 0 (de teller die blok 7 als "883 regels mét btw" rapporteerde). 0,00 is alleen echt als beide bronnen 0
    zijn."""
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
    jr_btw_regels = 0
    jr_btw_som = NUL
    jr_laatste: str | None = None
    for jr in bron.journaalregels:
        lid = rlz_bron.ref_id(jr.get("Account"))
        if lid and lid in ctx.btw_ledgers:
            d, c = rlz_bron.debet_credit(jr)
            jr_btw_regels += 1
            jr_btw_som += d - c
            datum = rlz_bron.journaalregel_datum(jr)
            if datum and (jr_laatste is None or datum.isoformat() > jr_laatste):
                jr_laatste = datum.isoformat()
    rij = next((r for r in rapport.saldibalans if r["rekening"] == rek), None)
    ledgers = sorted(
        (ctx.ledgers.get(lid, (None, None, None))[0] or "?", ctx.ledgers.get(lid, (None, None, None))[1] or lid)
        for lid in ctx.btw_ledgers
    )
    kandidaten = [d for d in (laatste_btw, laatste_ob, jr_laatste) if d]
    rapport.btw = {
        "rol_ingesteld": rol_id,
        "rekening": rek,
        "btw_regels": rapport.tellers.get("btw_regels", 0),
        "documenten_met_btw": btw_docs,
        "documenten_ob_afwikkeling": ob_docs,
        "btw_bedrag_totaal": btw_som.quantize(Decimal("0.01")),
        "btw_code_zonder_bedrag": rapport.tellers.get("btw_code_zonder_bedrag", 0),
        "journaalregels_btw_grootboek": jr_btw_regels,
        "journaalregels_btw_som": jr_btw_som.quantize(Decimal("0.01")),
        "laatste_btw_regel": laatste_btw,
        "laatste_ob_mutatie": laatste_ob,
        "laatste_journaalregel_btw": jr_laatste,
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
