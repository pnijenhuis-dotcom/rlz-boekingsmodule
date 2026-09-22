"""CLI's rond het kenmerk `btw_plichtig` (BUG Peter 22-09, casus Vastgoedgroep Nederland / Studio Lacy Lion 2026-042 →
RLZ-04-00000925; BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK
(Peter 22-09)").

1. `btw-in-niet-plichtige-administratie --administratie <naam|uuid> [--jaar 2026] [--rlz] [--json-uit]` — LEES-ONLY
   nazorgrapport (nameting-allowlist, job-image/leesreplica): álle door de module GEBOEKTE inkoopfacturen van het jaar
   mét btw ≠ 0 op regelniveau; per document boekstuk, leverancier, referentie, datum, netto/btw/bruto (module) en — mét
   `--rlz`, uitsluitend GET — de RLZ-crediteurpost (`BaseInvoiceAmount`), betaald (`BasePaidAmount`), open
   (`BaseRemainingAmount`) en de kolom "te weinig betaald" = bruto module − crediteurpost RLZ. Plus de RLZ-kant zonder
   module-spoor: PurchaseInvoices van het jaar mét `TotalTaxAmount` ≠ 0 (collectie-GET, client-side gefilterd) en het
   aantal ingediende btw-aangiften (TaxDeclarations) — "aangiftepoort n.v.t." is dan een gemeten feit. Schrijft niets.
2. `btw-plichtig-kandidaten` — LEES-ONLY detector-lijst (RLZ-signaal EnableTaxReporting false / geen tarief > 0 %).
3. `btw-plichtig-zetten --administratie <naam|uuid> (--aan | --uit) [--dry-run]` — SCHRIJVEND (weigerlijst nameting.sh):
   zet het kenmerk mét bron 'mens' onder de systeem-actor + audit; productie uitsluitend via `gcloud run jobs execute`
   op de job-image ná deploy, ná Peters besluit per administratie.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

COMMANDO_RAPPORT = "btw-in-niet-plichtige-administratie"
COMMANDO_KANDIDATEN = "btw-plichtig-kandidaten"
COMMANDO_ZETTEN = "btw-plichtig-zetten"
BRON_ZETTEN = "cli btw-plichtig-zetten (besluit Peter 22-09)"


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO_RAPPORT,
        help="LEES-ONLY (22-09): module-geboekte inkoopfacturen van het jaar mét btw ≠ 0 in één administratie; "
        "--rlz = RLZ-crediteurpost/betaald/open per document (GET) + RLZ-documenten mét TotalTaxAmount ≠ 0 + "
        "aantal ingediende aangiften. Kolom 'te weinig betaald' = bruto module − crediteurpost RLZ.",
    )
    p.add_argument("--administratie", required=True, help="Administratie (naam ilike of uuid).")
    p.add_argument("--jaar", type=int, default=2026, help="Factuurjaar (default 2026).")
    p.add_argument("--rlz", action="store_true", help="Ook de RLZ-kant lezen (uitsluitend GET).")
    p.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer.")
    k = subparsers.add_parser(
        COMMANDO_KANDIDATEN,
        help="LEES-ONLY (22-09): administraties die kandidaat 'niet btw-plichtig' zijn (RLZ EnableTaxReporting false "
        "of geen tarief > 0 %) en nog geen mens-bevestiging dragen.",
    )
    k.add_argument("--json-uit", action="store_true", dest="json_uit")
    z = subparsers.add_parser(
        COMMANDO_ZETTEN,
        help="SCHRIJVEND (22-09): zet `btw_plichtig` aan/uit voor één administratie (bron 'mens', audit). Productie "
        "alleen via gcloud run jobs execute ná Peters besluit; --dry-run toont wat er zou wijzigen.",
    )
    z.add_argument("--administratie", required=True, help="Administratie (naam ilike of uuid).")
    stand = z.add_mutually_exclusive_group(required=True)
    stand.add_argument("--aan", action="store_true", help="Btw-plichtig = true.")
    stand.add_argument("--uit", action="store_true", help="Btw-plichtig = false (btw in de kosten, harde check).")
    z.add_argument("--dry-run", action="store_true", dest="dry_run")


def dispatch(args: argparse.Namespace) -> int | None:
    commando = getattr(args, "commando", None)
    if commando == COMMANDO_RAPPORT:
        return rapport(args)
    if commando == COMMANDO_KANDIDATEN:
        return kandidaten_rapport(args)
    if commando == COMMANDO_ZETTEN:
        return zetten(args)
    return None


# ---- rapport (lees-only) ---------------------------------------------------------------------------------------------


@dataclass
class DocumentRij:
    document_id: str
    boekstuk: str | None
    leverancier: str | None
    referentie: str | None
    factuurdatum: str | None
    regels_met_btw: int
    netto: str
    btw: str
    bruto: str
    rlz_status: int | None = None
    rlz_crediteurpost: str | None = None
    rlz_btw: str | None = None
    rlz_betaald: str | None = None
    rlz_open: str | None = None
    te_weinig_betaald: str | None = None
    rlz_melding: str | None = None


@dataclass
class RlzRij:
    """RLZ-inkoopfactuur van het jaar mét TotalTaxAmount ≠ 0 zonder module-spoor."""

    rlz_id: str
    boekstuk: str | None
    leverancier: str | None
    referentie: str | None
    datum: str | None
    status: int | None
    crediteurpost: str | None
    btw: str | None
    betaald: str | None
    open: str | None


def _d(x: Decimal | float | int | None) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.01')):f}" if x is not None else "0.00"


def _dec(x: Any) -> Decimal | None:
    try:
        return Decimal(str(x)) if x is not None else None
    except Exception:  # noqa: BLE001
        return None


def module_documenten(administratie_id: uuid.UUID, *, jaar: int) -> list[DocumentRij]:
    """Geboekte inkoopfacturen (factuurdatum in `jaar`) mét ≥ 1 regel btw ≠ 0 — in de eigen RLS-scope, geen RLZ-call."""
    from sqlalchemy import select

    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
    from app.sync.models import VendorCache

    van, tot = date(jaar, 1, 1), date(jaar, 12, 31)
    uit: list[DocumentRij] = []
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Boekvoorstel, Document.status)
            .join(Document, Document.id == Boekvoorstel.document_id)
            .where(
                Document.administratie_id == administratie_id,
                Document.status == DocumentStatus.GEBOEKT,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                Boekvoorstel.factuurdatum >= van,
                Boekvoorstel.factuurdatum <= tot,
            )
            .order_by(Boekvoorstel.factuurdatum, Boekvoorstel.referentie)
        ).all()
        vendors = {
            v.id: v.naam
            for v in session.scalars(select(VendorCache).where(VendorCache.administratie_id == administratie_id))
        }
        for bv, _status in rijen:
            regels = session.scalars(
                select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == bv.document_id)
            ).all()
            met_btw = [r for r in regels if r.btw_bedrag is not None and r.btw_bedrag != 0]
            if not met_btw:
                continue
            netto = sum((r.netto_bedrag or Decimal(0) for r in regels), Decimal(0))
            btw = sum((r.btw_bedrag or Decimal(0) for r in regels), Decimal(0))
            bruto = bv.totaalbedrag if bv.totaalbedrag is not None else netto + btw
            uit.append(
                DocumentRij(
                    document_id=str(bv.document_id),
                    boekstuk=bv.rlz_boekstuknummer,
                    leverancier=vendors.get(bv.vendor_id) if bv.vendor_id else None,
                    referentie=bv.referentie,
                    factuurdatum=bv.factuurdatum.isoformat() if bv.factuurdatum else None,
                    regels_met_btw=len(met_btw),
                    netto=_d(netto),
                    btw=_d(btw),
                    bruto=_d(bruto),
                )
            )
        cycli = {str(bv.document_id): bv.boek_cyclus for bv, _ in rijen}
    for rij in uit:
        rij.__dict__["_boek_cyclus"] = cycli.get(rij.document_id, 0)
    return uit


def verrijk_met_rlz(client, rijen: list[DocumentRij]) -> set[str]:  # noqa: ANN001
    """Per module-document één GET op het eigen client-GUID (`rlz_herboeking_id`) — crediteurpost, btw, betaald, open.
    'te weinig betaald' = bruto module − crediteurpost RLZ (alleen als de post lager is). Geeft de RLZ-id-set terug."""
    from app.documenten.rlz_ids import rlz_herboeking_id
    from app.rlz.client import RlzApiError

    gezien: set[str] = set()
    for rij in rijen:
        rlz_id = rlz_herboeking_id(uuid.UUID(rij.document_id), int(rij.__dict__.get("_boek_cyclus", 0)))
        gezien.add(str(rlz_id))
        try:
            doc = client.get(f"PurchaseInvoices/{rlz_id}")
        except RlzApiError as exc:
            rij.rlz_melding = f"GET PurchaseInvoices/{rlz_id} -> {exc.status_code}"
            continue
        post = _dec(doc.get("BaseInvoiceAmount"))
        rij.rlz_status = doc.get("Status")
        rij.rlz_crediteurpost = _d(post) if post is not None else None
        rij.rlz_btw = _d(_dec(doc.get("TotalTaxAmount")))
        rij.rlz_betaald = _d(_dec(doc.get("BasePaidAmount")))
        rij.rlz_open = _d(_dec(doc.get("BaseRemainingAmount")))
        if post is not None:
            verschil = Decimal(rij.bruto) - abs(post)
            rij.te_weinig_betaald = _d(verschil) if verschil > 0 else "0.00"
        if not rij.boekstuk and doc.get("ReceiptNumber"):
            rij.boekstuk = doc.get("ReceiptNumber")
    return gezien


def rlz_documenten_met_btw(client, *, jaar: int, uitgezonderd: set[str]) -> list[RlzRij]:  # noqa: ANN001
    """RLZ-inkoopfacturen van het jaar mét TotalTaxAmount ≠ 0 zonder module-spoor (collectie-GET, dezelfde
    pagineervorm als `reconciliatie/rlz_dubbel.lees_purchase_invoices`; datum-bovengrens client-side)."""
    from app.reconciliatie.rlz_dubbel import lees_purchase_invoices

    uit: list[RlzRij] = []
    for doc in lees_purchase_invoices(client, vanaf=date(jaar, 1, 1)):
        datum = str(doc.get("Date") or "")[:10]
        if datum and datum > f"{jaar}-12-31":
            continue
        btw = _dec(doc.get("TotalTaxAmount"))
        if not btw or str(doc.get("id")) in uitgezonderd:
            continue
        entity = doc.get("Entity") if isinstance(doc.get("Entity"), dict) else {}
        uit.append(
            RlzRij(
                rlz_id=str(doc.get("id")),
                boekstuk=doc.get("ReceiptNumber"),
                leverancier=(entity or {}).get("Name") or (entity or {}).get("SearchName"),
                referentie=doc.get("Reference"),
                datum=datum or None,
                status=doc.get("Status"),
                crediteurpost=_d(_dec(doc.get("BaseInvoiceAmount"))),
                btw=_d(btw),
                betaald=_d(_dec(doc.get("BasePaidAmount"))),
                open=_d(_dec(doc.get("BaseRemainingAmount"))),
            )
        )
    return uit


def _client_voor(administratie_id: uuid.UUID):  # noqa: ANN202
    from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

    rid = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rid).for_administration(rid)


def rapport(args: argparse.Namespace) -> int:
    from app.beheer import btw_plichtig
    from app.geheugen.btw_default_cli import _zoek_administratie

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    aid, naam = gevonden
    stand = btw_plichtig.haal_op(administratie_id=aid)
    rijen = module_documenten(aid, jaar=args.jaar)
    rlz_rijen: list[RlzRij] = []
    aangiften: int | None = None
    rlz_melding: str | None = None
    if args.rlz:
        try:
            client = _client_voor(aid)
        except Exception as exc:  # noqa: BLE001 — geen credential = zichtbaar overgeslagen
            rlz_melding = f"RLZ-kant overgeslagen: {type(exc).__name__}: {exc}"
        else:
            try:
                gezien = verrijk_met_rlz(client, rijen)
                rlz_rijen = rlz_documenten_met_btw(client, jaar=args.jaar, uitgezonderd=gezien)
                try:
                    decl = client.list_tax_declarations()
                    aangiften = len([d for d in decl if d.get("Status") in (2, 3)])
                except Exception as exc:  # noqa: BLE001
                    rlz_melding = f"TaxDeclarations niet leesbaar: {type(exc).__name__}: {exc}"
            finally:
                client.close()
    for rij in rijen:
        rij.__dict__.pop("_boek_cyclus", None)
    if args.json_uit:
        print(
            json.dumps(
                {
                    "administratie": naam,
                    "administratie_id": str(aid),
                    "jaar": args.jaar,
                    "btw_plichtig": stand.btw_plichtig,
                    "btw_plichtig_bron": stand.bron,
                    "rlz_signaal_enable_tax_reporting": stand.rlz_signaal,
                    "geen_btw_taxrate": stand.geen_btw_taxrate_naam,
                    "module": [asdict(r) for r in rijen],
                    "rlz_zonder_module_spoor": [asdict(r) for r in rlz_rijen],
                    "ingediende_aangiften": aangiften,
                    "rlz_melding": rlz_melding,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(f"btw-in-niet-plichtige-administratie — {naam} · jaar {args.jaar} (LEES-ONLY)")
    print(
        f"  kenmerk btw_plichtig={stand.btw_plichtig} bron={stand.bron or 'nooit bevestigd'} · RLZ EnableTaxReporting="
        f"{stand.rlz_signaal if stand.rlz_signaal is not None else 'niet gelezen'} · geen-btw-code: "
        f"{stand.geen_btw_taxrate_naam or 'GEEN (PUT zonder TaxRate)'}"
        + (f" · kandidaat niet btw-plichtig ({stand.kandidaat_reden})" if stand.kandidaat else "")
    )
    print(f"\nMODULE — geboekte inkoopfacturen {args.jaar} mét btw ≠ 0 op een regel: {len(rijen)}")
    print(
        f"  {'boekstuk':<18}{'leverancier':<32}{'referentie':<18}{'datum':<11}{'netto':>11}{'btw':>10}{'bruto':>11}"
        f"{'RLZ post':>11}{'betaald':>10}{'open':>10}{'TE WEINIG':>11}"
    )
    totaal_te_weinig = Decimal(0)
    for r in rijen:
        te_weinig = Decimal(r.te_weinig_betaald) if r.te_weinig_betaald else None
        if te_weinig:
            totaal_te_weinig += te_weinig
        print(
            f"  {(r.boekstuk or '—')[:17]:<18}{(r.leverancier or '—')[:31]:<32}{(r.referentie or '—')[:17]:<18}"
            f"{(r.factuurdatum or '—'):<11}{r.netto:>11}{r.btw:>10}{r.bruto:>11}"
            f"{(r.rlz_crediteurpost or '—'):>11}{(r.rlz_betaald or '—'):>10}{(r.rlz_open or '—'):>10}"
            f"{(r.te_weinig_betaald or '—'):>11}" + (f"   ⚠ {r.rlz_melding}" if r.rlz_melding else "")
        )
    if args.rlz:
        print(f"  TOTAAL te weinig betaald (bruto module − crediteurpost RLZ): € {_d(totaal_te_weinig)}")
        print(f"\nRLZ — inkoopfacturen {args.jaar} mét TotalTaxAmount ≠ 0 zónder module-spoor: {len(rlz_rijen)}")
        for r in rlz_rijen:
            print(
                f"  {(r.boekstuk or '—')[:17]:<18}{(r.leverancier or '—')[:31]:<32}{(r.referentie or '—')[:17]:<18}"
                f"{(r.datum or '—'):<11}{'':>11}{(r.btw or '—'):>10}{'':>11}{(r.crediteurpost or '—'):>11}"
                f"{(r.betaald or '—'):>10}{(r.open or '—'):>10}"
            )
        print(
            f"\nAANGIFTEPOORT — ingediende btw-aangiften in RLZ: "
            f"{aangiften if aangiften is not None else 'niet gelezen'}"
            + (" → geen aangifte, 'Corrigeren…' storneert zonder tegenboek-pad" if aangiften == 0 else "")
        )
        if rlz_melding:
            print(f"  LET-OP {rlz_melding}")
    else:
        print("\nRLZ-kant niet gelezen (geef --rlz mee voor crediteurpost/betaald/open en 'te weinig betaald').")
    print(
        "\nHerstel per document = 'Corrigeren…' (⋯-menu op het geboekte document, 21-09) mét de regel op bruto / "
        "btw 0 — "
        "de nabetaling aan de leverancier is het verschil in de kolom TE WEINIG. Dit rapport schrijft niets."
    )
    return 0


# ---- kandidaten (lees-only) -----------------------------------------------------------------------------------------


def kandidaten_rapport(args: argparse.Namespace) -> int:
    from app.beheer import btw_plichtig

    rijen = btw_plichtig.kandidaten()
    if getattr(args, "json_uit", False):
        print(json.dumps([{**asdict(k), "administratie_id": str(k.administratie_id)} for k in rijen], indent=2))
        return 0
    print(
        f"btw-plichtig-kandidaten — {len(rijen)} administratie(s) kandidaat 'niet btw-plichtig' zonder mens-bevestiging"
    )
    for k in rijen:
        reden = (
            "RLZ EnableTaxReporting=false" if k.reden == "rlz_signaal" else "geen tarief met percentage > 0 in de cache"
        )
        print(f"  {k.naam:<45} {k.administratie_id}  {reden}")
    print(
        "Bevestigen: Instellingen › Administraties › ‹administratie› › Boeken & AI › Btw-plichtig, of "
        "`btw-plichtig-zetten`."
    )
    return 0


# ---- zetten (schrijvend) --------------------------------------------------------------------------------------------


def zetten(args: argparse.Namespace) -> int:
    from app.beheer import btw_plichtig
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.geheugen.btw_default_cli import _zoek_administratie

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    aid, naam = gevonden
    nieuw = bool(args.aan)
    huidig = btw_plichtig.haal_op(administratie_id=aid)
    label = "btw-plichtig" if nieuw else "NIET btw-plichtig (btw in de kosten, harde check)"
    if huidig.btw_plichtig == nieuw and huidig.bron == btw_plichtig.BRON_MENS:
        print(f"ONGEWIJZIGD {naam}: staat al op {label} (bron mens)")
        return 0
    if args.dry_run:
        print(
            f"DRY-RUN  {naam}: zou {huidig.btw_plichtig} (bron {huidig.bron or 'geen'}) → {nieuw} zetten [{label}] — "
            "niets geschreven"
        )
        return 0
    stand = btw_plichtig.zet(actor_id=SYSTEEM_ACTOR_ID, administratie_id=aid, btw_plichtig=nieuw)
    print(
        f"GEZET    {naam}: btw_plichtig={stand.btw_plichtig} bron={stand.bron} — audit "
        f"{btw_plichtig.AUDIT_ACTIE} ({BRON_ZETTEN}); geen-btw-code: {stand.geen_btw_taxrate_naam or 'GEEN'}"
    )
    return 0
