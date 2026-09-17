"""`rlz-feiten` (Feiten eerst, besluit Peter 17-09 — "bank is leidend" als leesstap die altijd gedaan wordt).

  rlz-feiten rlz  --administratie <uuid|naamdeel> (--boekstuk RLZ-01-00000006 | --id <guid>) [--collectie …]
      → document (kop) + regels (Account, Debit/Credit of NetAmount, Project) + de bankmutaties die er in RLZ aan hangen
        (PaymentReferenceList/Document = bewijs 1) en cent-exacte kandidaten ± 3 d mét zelfde richting (bewijs 2) — in één tabel.
  rlz-feiten bank --administratie <uuid|naamdeel> [--omschrijving test] [--iban NL..] [--bedrag 12600.00] [--datum 2026-08-15]
                  [--van 2026-01-01] [--tot 2026-12-31]
      → alle mutaties die matchen: datum, bedrag, richting, tegenpartij (initialen), IBAN (laatste 4), mutatie-id (8),
        afgeletterd-status (OpenAmount) en de RLZ-koppelingen (boekstuk/type). Niets gevonden = zegt dat letterlijk.

Lees-only via `LeesOnlyClient` (élke niet-GET geweigerd), uitvoer ALTIJD geanonimiseerd (Cloud Logging), Odoo-administratie =
zichtbaar overgeslagen (exit 1 mét reden). Exit 0 = uitvoer; 1 = RLZ-/credential-fout; 2 = ongeldige invoer/niet eenduidig."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.rlz.client import RlzApiError
from app.rlz.lezen import als_bedrag, als_datum, als_int, lees_collectie
from app.rlz.lezen_cli import LeesOnlyClient, _client_voor, _initialen, _tekst_anon, _zoek_administraties, anonimiseer
from app.rlz.tekst import ontknip

RLZ_FEITEN_COMMANDO = "rlz-feiten"
DOCUMENT_COLLECTIES = ("PurchaseInvoices", "SalesInvoices", "ManualJournals", "Receipts")
DOCUMENT_EXPAND = "Entity,DocumentLineList($expand=Account,TaxRate,Project)"
DOCUMENT_EXPAND_TERUGVAL = ("Entity,DocumentLineList($expand=Account)", "Entity", None)
BANK_EXPAND = "PaymentAccount,PaymentReferenceList($expand=Document)"
BANK_EXPAND_TERUGVAL = ("PaymentReferenceList($expand=Document)", "PaymentAccount", None)
#: Bewijs 2 (blok 9 VGG): cent-exact bedrag + zelfde richting binnen ± zoveel dagen rond de documentdatum.
KANDIDAAT_VENSTER_DAGEN = 3
#: Zonder --van/--tot: zoveel dagen terug (zelfde horizon als de reconciliatie).
BANK_HORIZON_DAGEN = 400


def register_rlz_feiten(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        RLZ_FEITEN_COMMANDO,
        help="Lees-only feiten uit Reeleezee: 'rlz' = document + regels + bankmutaties; 'bank' = mutaties mét koppelingen.",
    )
    sub = p.add_subparsers(dest="feiten_soort", required=True)
    d = sub.add_parser("rlz", help="Document op boekstuknummer of id, mét regels en bankmutaties.")
    d.add_argument("--administratie", required=True)
    d.add_argument("--boekstuk", default=None, help="Bv. RLZ-01-00000006 (ReceiptNumber).")
    d.add_argument("--id", default=None, dest="rlz_id", help="RLZ-document-GUID.")
    d.add_argument("--collectie", default=None, choices=DOCUMENT_COLLECTIES, help="Beperk tot één collectie.")
    b = sub.add_parser("bank", help="Bankmutaties op omschrijving/IBAN/bedrag/datum, mét koppelingen.")
    b.add_argument("--administratie", required=True)
    b.add_argument("--omschrijving", default=None, help="Substring (hoofdletterongevoelig) van de omschrijving/naam.")
    b.add_argument("--iban", default=None, help="Tegenrekening-IBAN (spaties/hoofdletters vrij).")
    b.add_argument("--bedrag", default=None, help="Cent-exact |bedrag|, bv. 12600.00.")
    b.add_argument("--datum", default=None, help="Exacte BookDate JJJJ-MM-DD.")
    b.add_argument("--van", default=None, help="BookDate ≥ JJJJ-MM-DD (default: 400 dagen terug).")
    b.add_argument("--tot", default=None, help="BookDate ≤ JJJJ-MM-DD (default: vandaag).")


def _norm_iban(x: object) -> str:
    return "".join(str(x or "").upper().split())


def _richting(bedrag: Decimal | None) -> str:
    if bedrag is None:
        return "?"
    return "uitgaand" if bedrag < 0 else "inkomend" if bedrag > 0 else "nul"


def _id8(x: object) -> str:
    return str(x)[:8] + "…" if x else "-"


def _koppelingen(mutatie: dict[str, Any]) -> list[dict[str, Any]]:
    uit: list[dict[str, Any]] = []
    for ref in mutatie.get("PaymentReferenceList") or []:
        if not isinstance(ref, dict):
            continue
        doc = ref.get("Document") if isinstance(ref.get("Document"), dict) else {}
        uit.append(
            {
                "document_id": _id8(doc.get("id") or (ref.get("Document") or {}).get("id") if isinstance(ref.get("Document"), dict) else None),
                "document_id_vol": str(doc.get("id")) if doc.get("id") else None,
                "boekstuk": doc.get("ReceiptNumber"),
                "type": doc.get("DocumentType"),
                "bedrag": str(als_bedrag(ref.get("Amount"))) if ref.get("Amount") is not None else None,
            }
        )
    return uit


def _mutatie_rij(m: dict[str, Any]) -> dict[str, Any]:
    bedrag = als_bedrag(m.get("Amount"))
    open_ = als_bedrag(m.get("OpenAmount") if m.get("OpenAmount") is not None else m.get("BaseOpenAmount"))
    rekening = m.get("PaymentAccount") if isinstance(m.get("PaymentAccount"), dict) else {}
    return {
        "mutatie_id": _id8(m.get("id")),
        "mutatie_id_vol": str(m.get("id")) if m.get("id") else None,
        "boekdatum": als_datum(m.get("BookDate")).isoformat() if als_datum(m.get("BookDate")) else None,
        "bedrag": str(bedrag) if bedrag is not None else None,
        "richting": _richting(bedrag),
        "open_bedrag": str(open_) if open_ is not None else None,
        "afgeletterd": (open_ == 0) if open_ is not None else None,
        "tegenpartij": _initialen(str(m.get("Name"))) if m.get("Name") else None,
        "iban_laatste4": ("…" + _norm_iban(m.get("CounterAccount"))[-4:]) if m.get("CounterAccount") else None,
        "omschrijving": _tekst_anon(ontknip(m.get("Reference") or m.get("Description")) or ""),
        "rekening": rekening.get("Name") or _id8(rekening.get("id")),
        "koppelingen": [{k: v for k, v in k_.items() if k != "document_id_vol"} for k_ in _koppelingen(m)],
    }


def _regel_rij(r: dict[str, Any]) -> dict[str, Any]:
    account = r.get("Account") if isinstance(r.get("Account"), dict) else {}
    project = r.get("Project") if isinstance(r.get("Project"), dict) else {}
    debet, credit, netto = als_bedrag(r.get("DebitAmount")), als_bedrag(r.get("CreditAmount")), als_bedrag(r.get("NetAmount"))
    return {
        "rekening": f"{account.get('Code') or account.get('Number') or ''} {account.get('Name') or ''}".strip() or _id8(account.get("id")),
        "debet": str(debet) if debet is not None else None,
        "credit": str(credit) if credit is not None else None,
        "netto": str(netto) if netto is not None else None,
        "project": project.get("Name") or (_id8(project.get("id")) if project else None),
        "omschrijving": _tekst_anon(ontknip(r.get("Description")) or ""),
    }


def _document_rij(collectie: str, d: dict[str, Any]) -> dict[str, Any]:
    entity_id, entity_naam = None, None
    ent = d.get("Entity") if isinstance(d.get("Entity"), dict) else None
    if ent:
        entity_id, entity_naam = _id8(ent.get("id")), (_initialen(str(ent.get("Name"))) if ent.get("Name") else None)
    return {
        "collectie": collectie,
        "boekstuk": d.get("ReceiptNumber"),
        "id": _id8(d.get("id")),
        "document_type": d.get("DocumentType"),
        "status": als_int(d.get("Status")),
        "datum": als_datum(d.get("Date")).isoformat() if als_datum(d.get("Date")) else None,
        "boekdatum": als_datum(d.get("BookDate")).isoformat() if als_datum(d.get("BookDate")) else None,
        "bedrag": str(als_bedrag(d.get("BaseInvoiceAmount") or d.get("TotalAmount") or d.get("Amount"))),
        "relatie": entity_naam,
        "relatie_id": entity_id,
        "omschrijving": _tekst_anon(ontknip(d.get("Description") or d.get("Header")) or ""),
        "regels": [_regel_rij(r) for r in (d.get("DocumentLineList") or []) if isinstance(r, dict)],
    }


def _bank_filter(van: date, tot: date) -> str:
    return f"BookDate ge {van.isoformat()}T00:00:00Z and BookDate le {tot.isoformat()}T23:59:59Z"


def _lees_bank(client: LeesOnlyClient, *, van: date, tot: date) -> tuple[list[dict[str, Any]], str | None]:
    uit = lees_collectie(client, "PaymentTransactions", filter_=_bank_filter(van, tot), expand=BANK_EXPAND, expand_terugval=BANK_EXPAND_TERUGVAL)
    if not uit.gelukt:
        return [], f"PaymentTransactions: HTTP {uit.fout.status_code if uit.fout else '?'} {_tekst_anon((uit.fout.body if uit.fout else '')[:200])}"
    return uit.rijen, None


def _vind_document(client: LeesOnlyClient, *, collecties: tuple[str, ...], boekstuk: str | None, rlz_id: str | None) -> list[tuple[str, dict[str, Any]]]:
    gevonden: list[tuple[str, dict[str, Any]]] = []
    for coll in collecties:
        if rlz_id:
            if coll == "Receipts":
                continue  # geen {id}-route (api-verkenning "Receipts-verkenning")
            try:
                d = client.get(f"{coll}/{rlz_id}", params={"$expand": DOCUMENT_EXPAND})
            except RlzApiError as exc:
                if exc.status_code == 404:
                    continue
                if exc.status_code == 400:
                    try:
                        d = client.get(f"{coll}/{rlz_id}", params={"$expand": "Entity"})
                    except RlzApiError:
                        continue
                else:
                    raise
            if isinstance(d, dict) and d.get("id"):
                gevonden.append((coll, d))
            continue
        uit = lees_collectie(client, coll, filter_=f"ReceiptNumber eq '{boekstuk}'", expand=DOCUMENT_EXPAND, expand_terugval=DOCUMENT_EXPAND_TERUGVAL)
        if uit.gelukt:
            gevonden.extend((coll, r) for r in uit.rijen)
    return gevonden


def _bank_bij_document(mutaties: list[dict[str, Any]], *, doc_id: str, datum: date | None, bedrag: Decimal | None, collectie: str) -> tuple[list[dict], list[dict]]:
    """→ (bewijs 1: mutaties die via PaymentReferenceList aan dit document hangen, bewijs 2: cent-exacte kandidaten ± 3 d)."""
    bewijs1, bewijs2 = [], []
    for m in mutaties:
        refs = _koppelingen(m)
        if any(k.get("document_id_vol") == doc_id for k in refs):
            bewijs1.append(_mutatie_rij(m))
            continue
        if datum is None or bedrag is None:
            continue
        bd = als_datum(m.get("BookDate"))
        mb = als_bedrag(m.get("Amount"))
        if bd is None or mb is None or abs((bd - datum).days) > KANDIDAAT_VENSTER_DAGEN or abs(mb) != abs(bedrag):
            continue
        # richting: inkoop = uitgaand (negatief), verkoop = inkomend; memoriaal/receipt = onbepaald → beide
        if collectie == "PurchaseInvoices" and mb > 0:
            continue
        if collectie == "SalesInvoices" and mb < 0:
            continue
        bewijs2.append(_mutatie_rij(m))
    return bewijs1, bewijs2


def _administratie(tekst: str) -> tuple[uuid.UUID, str, str] | None:
    treffers = _zoek_administraties(tekst)
    if len(treffers) != 1:
        namen = ", ".join(n for _, n, _ in treffers[:10]) or "geen"
        print(f"rlz-feiten: --administratie {tekst!r} is niet eenduidig ({len(treffers)} treffers: {namen})", file=sys.stderr)
        return None
    return treffers[0]


def run_rlz_feiten(args: argparse.Namespace, *, client_factory=None, uit=None) -> int:  # noqa: ANN001
    from app.rlz.credentials import GeenRlzCredentials

    uit = uit or sys.stdout
    client_factory = client_factory or _client_voor
    adm = _administratie(args.administratie)
    if adm is None:
        return 2
    administratie_id, naam, rlz_admin_id = adm
    try:
        client = client_factory(rlz_admin_id)
    except GeenRlzCredentials as exc:
        print(f"rlz-feiten: geen Reeleezee-verbinding voor {naam!r} (Odoo-administratie of ontbrekende credential — zichtbaar overgeslagen): {exc}", file=sys.stderr)
        return 1
    kop: dict[str, Any] = {"administratie": naam, "administratie_id": _id8(administratie_id), "soort": args.feiten_soort}
    try:
        try:
            if args.feiten_soort == "rlz":
                return _run_rlz(args, client, kop, uit)
            return _run_bank(args, client, kop, uit)
        finally:
            client.close()
    except RlzApiError as exc:
        print(f"rlz-feiten: RLZ HTTP {exc.status_code}: {_tekst_anon(exc.body[:300])}", file=sys.stderr)
        return 1


def _run_rlz(args: argparse.Namespace, client: LeesOnlyClient, kop: dict[str, Any], uit) -> int:  # noqa: ANN001
    if bool(args.boekstuk) == bool(args.rlz_id):
        print("rlz-feiten rlz: precies één van --boekstuk of --id", file=sys.stderr)
        return 2
    collecties = (args.collectie,) if args.collectie else DOCUMENT_COLLECTIES
    gevonden = _vind_document(client, collecties=collecties, boekstuk=args.boekstuk, rlz_id=args.rlz_id)
    kop["zoek"] = {"boekstuk": args.boekstuk, "id": _id8(args.rlz_id) if args.rlz_id else None, "collecties": list(collecties)}
    if not gevonden:
        kop["uitkomst"] = "bestaat niet (meer) in Reeleezee — in geen van de doorzochte collecties"
        print(json.dumps({"rlz_feiten": kop, "documenten": []}, indent=2, ensure_ascii=False, default=str), file=uit)
        return 0
    documenten = []
    for coll, d in gevonden:
        rij = _document_rij(coll, d)
        datum = als_datum(d.get("Date")) or als_datum(d.get("BookDate"))
        bedrag = als_bedrag(d.get("BaseInvoiceAmount") or d.get("TotalAmount") or d.get("Amount"))
        if datum is not None:
            van, tot = datum - timedelta(days=60), datum + timedelta(days=90)
            mutaties, fout = _lees_bank(client, van=van, tot=tot)
        else:
            mutaties, fout = [], "geen documentdatum — bank niet gelezen"
        b1, b2 = _bank_bij_document(mutaties, doc_id=str(d.get("id")), datum=datum, bedrag=bedrag, collectie=coll)
        rij["bank"] = {
            "gelezen_venster": [van.isoformat(), tot.isoformat()] if datum else None,
            "fout": fout,
            "gekoppeld_bewijs1": b1,
            "kandidaten_bewijs2_cent_exact_pm3d": b2,
            "oordeel": (
                "bank-bevestigd (gekoppeld)" if b1 else "kandidaat op bedrag+richting ± 3 d, niet gekoppeld" if b2 else
                ("geen bankmutatie gevonden" if not fout else "bank niet leesbaar")
            ),
        }
        documenten.append(rij)
    kop["uitkomst"] = f"{len(documenten)} document(en) gevonden"
    print(json.dumps({"rlz_feiten": kop, "documenten": anonimiseer(documenten)}, indent=2, ensure_ascii=False, default=str), file=uit)
    return 0


def _run_bank(args: argparse.Namespace, client: LeesOnlyClient, kop: dict[str, Any], uit) -> int:  # noqa: ANN001
    from app.tijd import vandaag_nl

    try:
        tot = date.fromisoformat(args.tot) if args.tot else vandaag_nl()
        van = date.fromisoformat(args.van) if args.van else tot - timedelta(days=BANK_HORIZON_DAGEN)
        datum = date.fromisoformat(args.datum) if args.datum else None
        bedrag = Decimal(str(args.bedrag).replace(",", ".")).quantize(Decimal("0.01")) if args.bedrag else None
    except (ValueError, InvalidOperation) as exc:
        print(f"rlz-feiten bank: ongeldige datum/bedrag: {exc}", file=sys.stderr)
        return 2
    if datum:
        van, tot = min(van, datum), max(tot, datum)
    if not any([args.omschrijving, args.iban, bedrag, datum]):
        print("rlz-feiten bank: minstens één van --omschrijving/--iban/--bedrag/--datum", file=sys.stderr)
        return 2
    mutaties, fout = _lees_bank(client, van=van, tot=tot)
    kop["filter"] = {"omschrijving": args.omschrijving, "iban_laatste4": ("…" + _norm_iban(args.iban)[-4:]) if args.iban else None,
                     "bedrag": str(bedrag) if bedrag else None, "datum": datum.isoformat() if datum else None,
                     "venster": [van.isoformat(), tot.isoformat()], "gelezen": len(mutaties), "fout": fout}
    zoek = (args.omschrijving or "").lower()
    iban = _norm_iban(args.iban) if args.iban else None
    treffers = []
    for m in mutaties:
        tekst = f"{ontknip(m.get('Reference') or '') or ''} {ontknip(m.get('Description') or '') or ''} {m.get('Name') or ''}".lower()
        if zoek and zoek not in tekst:
            continue
        if iban and _norm_iban(m.get("CounterAccount")) != iban:
            continue
        mb = als_bedrag(m.get("Amount"))
        if bedrag is not None and (mb is None or abs(mb) != bedrag):
            continue
        if datum is not None and als_datum(m.get("BookDate")) != datum:
            continue
        treffers.append(_mutatie_rij(m))
    treffers.sort(key=lambda r: (r["boekdatum"] or "", r["mutatie_id"]))
    kop["uitkomst"] = f"{len(treffers)} mutatie(s) gevonden" if treffers else (
        "niets gevonden — in dit venster staat geen mutatie die aan het filter voldoet" if not fout else "bank niet leesbaar"
    )
    print(json.dumps({"rlz_feiten": kop, "mutaties": anonimiseer(treffers)}, indent=2, ensure_ascii=False, default=str), file=uit)
    return 0
