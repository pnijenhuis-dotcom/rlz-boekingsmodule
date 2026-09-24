"""`doorbelasting-factuur-pdf-toets` — LEES-ONLY meetinstrument (bundelrun 24-09 blok 4, casus KF → Molenhof Verhuur
B.V., Lusso 261004: € 4.741,55 + provisie € 237,08, chip "factuur ontbreekt — factuur-PDF onvolledig: btw-som € 1.045,52,
totaal incl € 6.024,15").

Hypothese (Cowork 24-09): de motor boekt de btw PER REGEL afgerond (995,73 + 49,79 = 1.045,52 — `geld.btw_over`), RLZ
rendert op de factuur de btw-specificatie per tarief over het subtotaal (21 % × 4.978,63 = 1.045,51) → de cent-exacte toets
`factuur.controleer_factuur_tekst` vindt "€ 1.045,52" niet in de PDF-tekst en zet `factuur_pdf_status = ontbreekt`.

Dit instrument doet uitsluitend GET's en schrijft niets:
  (c) telling kantoorbreed: élke doorbelasting-boeking mét `factuur_pdf_status = 'ontbreekt'` (of NULL), per administratie in
      haar EIGEN RLS-scope, geclassificeerd op de vastgelegde reden — `onvolledig_cent` (alleen btw-som/totaal ontbreken én het
      geboekte btw-bedrag verschilt precies één cent van het factuur-niveau-bedrag = per-regel-afronding), `onvolledig_anders`
      (KvK/btw-nummer/referentie ontbreekt of een groter verschil), `render_mislukt`, `geen_pdf`, `onleesbaar`, `overig`;
  (a) `--pdf`: voor de geselecteerde boekingen (begrens mét --administratie/--referentie/--max) het RLZ-record van de verkoop
      (`GET SalesInvoices/{id}` — regelsom TaxAmount = wat RLZ vastlegde uit onze PUT) én RLZ's eigen render
      (`GET SalesInvoices/{id}/Download`, Accept application/pdf) — de gerenderde bedragen worden náást de geboekte gezet:
      uitkomst A = PDF toont het factuur-niveau-bedrag terwijl het record/journaal de regelsom draagt (RLZ herrekent op de
      print), uitkomst B = record én PDF dragen het factuur-niveau-bedrag (dan boekten wíj anders dan RLZ vastlegt).

Geen wijziging in geldlogica: blok 4 (b) volgt pas ná dit rapport en Peters akkoord (opdracht 24-09).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

COMMANDO = "doorbelasting-factuur-pdf-toets"

KLASSE_CENT = "onvolledig_cent"
KLASSE_ANDERS = "onvolledig_anders"
KLASSE_RENDER = "render_mislukt"
KLASSE_GEEN_PDF = "geen_pdf"
KLASSE_ONLEESBAAR = "onleesbaar"
KLASSE_OVERIG = "overig"

UITKOMST_A = "A: PDF toont het factuur-niveau-bedrag, RLZ-record draagt de regelsom (RLZ herrekent op de print)"
UITKOMST_B = "B: RLZ-record én PDF dragen het factuur-niveau-bedrag — geboekt bedrag wijkt af"
UITKOMST_COMPLEET = "compleet: PDF toont de geboekte bedragen"
UITKOMST_ONBEKEND = "onbekend: geen van beide bedragen in de PDF-tekst gevonden"

CENT = Decimal("0.01")
#: De onderdelen staan tussen "factuur-PDF onvolledig:" en het advies ná " — " (24-09: twee adviesvormen — lay-out óf
#: RLZ-vorm/data-stap — beide beginnen ná hetzelfde scheidingsteken).
_ONTBREKEND_RE = re.compile(r"factuur-PDF onvolledig:\s*(.*?)(?:\s+—\s+(?:lay-out|de RLZ-factuur)|$)", re.S)


@dataclass(frozen=True)
class Klassificatie:
    klasse: str
    ontbrekend: tuple[str, ...]
    btw_geboekt: Decimal
    btw_factuurniveau: Decimal
    verschil_ct: int
    percentage: Decimal | None


def _pct(netto_totaal: Decimal, provisie: Decimal, btw: Decimal) -> Decimal | None:
    subtotaal = netto_totaal + provisie
    if subtotaal == 0:
        return None
    return (btw / subtotaal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def btw_factuurniveau(netto_totaal: Decimal, provisie: Decimal, percentage: Decimal) -> Decimal:
    """Btw zoals een factuur-lay-out 'm per tarief toont: percentage × subtotaal, één keer afgerond."""
    return ((netto_totaal + provisie) * percentage / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def ontbrekende_onderdelen(reden: str | None) -> tuple[str, ...]:
    """De onderdelen uit de reden-tekst van `factuur.haal_en_controleer_factuur` ("factuur-PDF onvolledig: a, b — …")."""
    if not reden:
        return ()
    m = _ONTBREKEND_RE.search(reden)
    if not m:
        return ()
    return tuple(x.strip() for x in m.group(1).split(", ") if x.strip())


def classificeer(*, reden: str | None, netto_totaal: Decimal, provisie: Decimal, btw_geboekt: Decimal) -> Klassificatie:
    """Pure classificatie van één 'ontbreekt'-reden (geen I/O)."""
    pct = _pct(netto_totaal, provisie, btw_geboekt)
    factuurniveau = btw_factuurniveau(netto_totaal, provisie, pct) if pct is not None else btw_geboekt
    verschil_ct = int(((btw_geboekt - factuurniveau) / CENT).to_integral_value())
    onderdelen = ontbrekende_onderdelen(reden)
    tekst = (reden or "").lower()
    if onderdelen:
        alleen_bedragen = all(o.startswith(("btw-som", "totaal incl.", "subtotaal excl.")) for o in onderdelen)
        if alleen_bedragen and abs(verschil_ct) == 1:
            klasse = KLASSE_CENT
        else:
            klasse = KLASSE_ANDERS
    elif "render mislukt" in tekst:
        klasse = KLASSE_RENDER
    elif "geen pdf" in tekst:
        klasse = KLASSE_GEEN_PDF
    elif "onleesbaar" in tekst:
        klasse = KLASSE_ONLEESBAAR
    else:
        klasse = KLASSE_OVERIG
    return Klassificatie(
        klasse=klasse,
        ontbrekend=onderdelen,
        btw_geboekt=btw_geboekt,
        btw_factuurniveau=factuurniveau,
        verschil_ct=verschil_ct,
        percentage=pct,
    )


@dataclass
class PdfToets:
    """Uitkomst van de (a)-stap voor één boeking — alles gelezen, niets geschreven."""

    record_regelsom_btw: Decimal | None
    record_total_tax: Decimal | None
    pdf_bevat_btw_geboekt: bool
    pdf_bevat_btw_factuurniveau: bool
    pdf_bevat_totaal_geboekt: bool
    pdf_bevat_totaal_factuurniveau: bool
    uitkomst: str
    fout: str | None = None


def toets_pdf_tekst(
    tekst: str, *, netto_totaal: Decimal, provisie: Decimal, btw_geboekt: Decimal, btw_factuurniveau_bedrag: Decimal
) -> tuple[bool, bool, bool, bool]:
    from app.doorbelasting.factuur import nl_bedrag, normaliseer_tekst

    t = normaliseer_tekst(tekst)
    subtotaal = netto_totaal + provisie

    def _in(bedrag: Decimal) -> bool:
        return normaliseer_tekst(f"€ {nl_bedrag(bedrag)}") in t

    return (
        _in(btw_geboekt),
        _in(btw_factuurniveau_bedrag),
        _in(subtotaal + btw_geboekt),
        _in(subtotaal + btw_factuurniveau_bedrag),
    )


def bepaal_uitkomst(
    *, record_regelsom_btw: Decimal | None, btw_geboekt: Decimal, btw_factuurniveau_bedrag: Decimal, pdf_geboekt: bool, pdf_factuurniveau: bool
) -> str:
    if pdf_geboekt:
        return UITKOMST_COMPLEET
    if not pdf_factuurniveau:
        return UITKOMST_ONBEKEND
    if record_regelsom_btw is not None and record_regelsom_btw == btw_factuurniveau_bedrag != btw_geboekt:
        return UITKOMST_B
    return UITKOMST_A


def toets_pdf_van_boeking(
    client,  # noqa: ANN001 — RlzClient of fake (alleen GET)
    *,
    verkoop_rlz_id: uuid.UUID,
    netto_totaal: Decimal,
    provisie: Decimal,
    btw_geboekt: Decimal,
    btw_factuurniveau_bedrag: Decimal,
) -> PdfToets:
    from app.doorbelasting.factuur import pdf_tekst

    regelsom: Decimal | None = None
    total_tax: Decimal | None = None
    try:
        record = client.get_sales_invoice(verkoop_rlz_id)
        regels = record.get("DocumentLineList") or []
        if regels:
            regelsom = sum((Decimal(str(r.get("TaxAmount") or 0)) for r in regels), Decimal(0)).quantize(CENT)
        for sleutel in ("TotalTaxAmount", "TaxAmount", "BaseTaxAmount"):
            if record.get(sleutel) is not None:
                total_tax = Decimal(str(record[sleutel])).quantize(CENT)
                break
    except Exception as exc:  # noqa: BLE001 — lees-only: zichtbaar in de uitkomst, nooit een crash
        return PdfToets(None, None, False, False, False, False, UITKOMST_ONBEKEND, fout=f"record niet leesbaar: {exc.__class__.__name__}: {str(exc)[:160]}")
    try:
        pdf = client.download_sales_invoice_pdf(verkoop_rlz_id)
        tekst = pdf_tekst(pdf) if pdf and pdf.startswith(b"%PDF") else ""
    except Exception as exc:  # noqa: BLE001
        return PdfToets(regelsom, total_tax, False, False, False, False, UITKOMST_ONBEKEND, fout=f"render niet leesbaar: {exc.__class__.__name__}: {str(exc)[:160]}")
    b_g, b_f, t_g, t_f = toets_pdf_tekst(
        tekst, netto_totaal=netto_totaal, provisie=provisie, btw_geboekt=btw_geboekt, btw_factuurniveau_bedrag=btw_factuurniveau_bedrag
    )
    return PdfToets(
        record_regelsom_btw=regelsom,
        record_total_tax=total_tax,
        pdf_bevat_btw_geboekt=b_g,
        pdf_bevat_btw_factuurniveau=b_f,
        pdf_bevat_totaal_geboekt=t_g,
        pdf_bevat_totaal_factuurniveau=t_f,
        uitkomst=bepaal_uitkomst(
            record_regelsom_btw=regelsom,
            btw_geboekt=btw_geboekt,
            btw_factuurniveau_bedrag=btw_factuurniveau_bedrag,
            pdf_geboekt=b_g,
            pdf_factuurniveau=b_f,
        ),
    )


@dataclass
class Rij:
    administratie: str
    administratie_id: str
    boeking_id: str
    document_id: str
    status: str
    doelentiteit: str
    bron_referentie: str | None
    verkoop_referentie: str | None
    netto_totaal: str
    provisie: str
    btw_geboekt: str
    btw_factuurniveau: str
    verschil_ct: int
    klasse: str
    ontbrekend: list[str]
    reden: str | None
    pdf: dict | None = None


@dataclass
class Meting:
    rijen: list[Rij] = field(default_factory=list)
    per_klasse: dict[str, int] = field(default_factory=dict)
    fouten: list[str] = field(default_factory=list)
    administraties: int = 0


def _administraties(term: str | None) -> list[tuple[uuid.UUID, str]] | None:
    from app.beheer.bua_cli import _administraties as _adms

    return _adms(term)


def meet(
    *,
    administratie: str | None,
    referentie: str | None,
    met_pdf: bool,
    maximum: int,
    client_factory: Callable[[uuid.UUID], object] | None = None,
) -> Meting | None:
    from sqlalchemy import select

    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel
    from app.doorbelasting.factuur import FACTUUR_STATUS_ONTBREEKT
    from app.doorbelasting.factuur_herstel import HERSTELBARE_STATUSSEN
    from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingMapping

    adms = _administraties(administratie)
    if adms is None:
        return None
    meting = Meting()
    ref_norm = (referentie or "").strip().lower()
    for aid, naam in adms:
        try:
            with scoped_session(aid) as session:
                boekingen = session.scalars(
                    select(DoorbelastingBoeking)
                    .where(
                        DoorbelastingBoeking.administratie_id == aid,
                        DoorbelastingBoeking.status.in_(HERSTELBARE_STATUSSEN),
                        (DoorbelastingBoeking.factuur_pdf_status.is_(None))
                        | (DoorbelastingBoeking.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT),
                    )
                    .order_by(DoorbelastingBoeking.aangemaakt_op)
                ).all()
                rijen: list[Rij] = []
                for b in boekingen:
                    voorstel = session.get(Boekvoorstel, b.document_id)
                    bron_ref = voorstel.referentie if voorstel is not None else None
                    if ref_norm and ref_norm not in " ".join(x for x in (bron_ref, b.verkoop_referentie) if x).lower():
                        continue
                    mapping = session.get(DoorbelastingMapping, b.mapping_id)
                    k = classificeer(
                        reden=b.factuur_pdf_reden,
                        netto_totaal=Decimal(b.netto_totaal),
                        provisie=Decimal(b.provisie_bedrag),
                        btw_geboekt=Decimal(b.btw_bedrag),
                    )
                    rijen.append(
                        Rij(
                            administratie=naam,
                            administratie_id=str(aid),
                            boeking_id=str(b.id),
                            document_id=str(b.document_id),
                            status=b.status,
                            doelentiteit=mapping.doelentiteit_naam if mapping else "?",
                            bron_referentie=bron_ref,
                            verkoop_referentie=b.verkoop_referentie,
                            netto_totaal=f"{Decimal(b.netto_totaal):.2f}",
                            provisie=f"{Decimal(b.provisie_bedrag):.2f}",
                            btw_geboekt=f"{k.btw_geboekt:.2f}",
                            btw_factuurniveau=f"{k.btw_factuurniveau:.2f}",
                            verschil_ct=k.verschil_ct,
                            klasse=k.klasse,
                            ontbrekend=list(k.ontbrekend),
                            reden=b.factuur_pdf_reden,
                        )
                    )
                    meting.per_klasse[k.klasse] = meting.per_klasse.get(k.klasse, 0) + 1
            if rijen:
                meting.administraties += 1
            if met_pdf and rijen:
                factory = client_factory or _standaard_client
                client = factory(aid)
                try:
                    for rij in rijen:
                        if sum(1 for r in meting.rijen if r.pdf is not None) >= maximum:
                            break
                        toets = toets_pdf_van_boeking(
                            client,
                            verkoop_rlz_id=next(b.verkoop_rlz_id for b in boekingen if str(b.id) == rij.boeking_id),
                            netto_totaal=Decimal(rij.netto_totaal),
                            provisie=Decimal(rij.provisie),
                            btw_geboekt=Decimal(rij.btw_geboekt),
                            btw_factuurniveau_bedrag=Decimal(rij.btw_factuurniveau),
                        )
                        rij.pdf = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(toets).items()}
                finally:
                    sluit = getattr(client, "close", None)
                    if callable(sluit):
                        sluit()
            meting.rijen.extend(rijen)
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de meting niet
            meting.fouten.append(f"{naam}: {exc.__class__.__name__}: {str(exc)[:200]}")
    return meting


def _standaard_client(administratie_id: uuid.UUID):  # noqa: ANN202
    from app.documenten.boeken import _rlz_client_voor

    return _rlz_client_voor(administratie_id)


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="LEES-ONLY (blok 4 bundelrun 24-09): doorbelasting-boekingen zonder factuur-PDF geclassificeerd op de reden "
        "(cent-verschil per-regel-afronding vs. anders); --pdf leest RLZ-record + render en zet de bedragen naast elkaar.",
    )
    p.add_argument("--administratie", default=None, help="Beperk tot één administratie (uuid of naamdeel).")
    p.add_argument("--referentie", default=None, help="Beperk tot boekingen waarvan bron- of verkoopreferentie deze tekst bevat.")
    p.add_argument("--pdf", action="store_true", help="Lees per geselecteerde boeking het RLZ-record en de factuur-render (alleen GET).")
    p.add_argument("--max", type=int, default=3, dest="maximum", help="Maximaal aantal PDF-renders per run (default 3).")
    p.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer (JSON).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run(args)


def run(args: argparse.Namespace, *, uit=None, client_factory=None) -> int:  # noqa: ANN001
    uit = uit or sys.stdout
    meting = meet(
        administratie=args.administratie,
        referentie=args.referentie,
        met_pdf=bool(args.pdf),
        maximum=int(args.maximum or 3),
        client_factory=client_factory,
    )
    if meting is None:
        print(f"{COMMANDO}: --administratie {args.administratie!r} onbekend of niet eenduidig", file=sys.stderr)
        return 2
    if args.json_uit:
        print(json.dumps({"rijen": [asdict(r) for r in meting.rijen], "per_klasse": meting.per_klasse, "fouten": meting.fouten}, indent=2, ensure_ascii=False), file=uit)
    else:
        print(f"== {COMMANDO} (lees-only; alleen GET) ==", file=uit)
        for r in meting.rijen:
            print(
                f"{r.administratie} · doel {r.doelentiteit} · bron {r.bron_referentie or '?'} · verkoop {r.verkoop_referentie or '?'} · "
                f"status {r.status} · netto {r.netto_totaal} + provisie {r.provisie} · btw geboekt {r.btw_geboekt} / factuur-niveau "
                f"{r.btw_factuurniveau} (verschil {r.verschil_ct:+d} ct) · klasse {r.klasse} · ontbrekend: {', '.join(r.ontbrekend) or '-'}",
                file=uit,
            )
            if r.pdf is not None:
                p = r.pdf
                print(
                    f"   PDF/record: regelsom-btw record {p.get('record_regelsom_btw')} · total-tax record {p.get('record_total_tax')} · "
                    f"PDF bevat btw geboekt={p.get('pdf_bevat_btw_geboekt')} factuur-niveau={p.get('pdf_bevat_btw_factuurniveau')} · "
                    f"totaal geboekt={p.get('pdf_bevat_totaal_geboekt')} factuur-niveau={p.get('pdf_bevat_totaal_factuurniveau')} → "
                    f"{p.get('uitkomst')}" + (f" · fout: {p.get('fout')}" if p.get("fout") else ""),
                    file=uit,
                )
        for f in meting.fouten:
            print(f"FOUT {f}", file=uit)
        klassen = " · ".join(f"{k} {v}" for k, v in sorted(meting.per_klasse.items())) or "geen"
        print(
            f"TOTAAL: {len(meting.rijen)} boeking(en) zonder factuur-PDF in {meting.administraties} administratie(s) · "
            f"{klassen} · fouten {len(meting.fouten)}",
            file=uit,
        )
    return 0
