"""Omzetbron PILATES BETALINGSEXPORT (Peter 15-09): export van het boekingsplatform (bsport-/Momoyoga-achtig; de PSP
betaalt per batch netto uit). Kolommen: Factuurnummer (= transactie-id), Betaaldatum/-tijd, Bedrag, Betaalstatus,
Transactiekosten, Betaalmethode (ideal/apple_pay/sepa/Betaalkaart/Contant/dispute), Aankopen (productnaam),
Bankoverschrijving (= uitbetalings- batch), Transactiedatum (= uitbetaaldatum), klantnaam/e-mail (PII — NOOIT in
regels/omschrijvingen/veldvoorstel).

Boekmodel: één kassarapport-document (Receipt) per UITBETALING: omzetregels per GB-categorie (som Bedrag,
kassabedragen incl. btw), disputes als negatieve regel in de categorie van het product, transactiekosten als negatieve
regel "Transactiekosten PSP" → het documenttotaal is de netto uitbetaling, die de bankmatch tegen de echte ontvangst
GROEN maakt. Betaalmethode Contant = geen uitbetaling → eigen pseudo-batch ('contant-<maand>'). Idempotentie op
Factuurnummer per administratie (overlappende week-/maandexports boeken niets dubbel — controle in de documentenlaag)."""  # noqa: E501

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal

from app.omzet.bronnen.grid import Grid

BRON = "pilates_betalingsexport"
CATEGORIE_KOSTEN = "Transactiekosten PSP"
CATEGORIE_PILATES = "Pilateslessen"
CATEGORIE_YOGA = "Yoga"
CATEGORIE_KLEDING = "Kleding & producten"
CATEGORIE_ETEN = "Eten/drinken"
#: Besluit Peter 16-09 ("Combi verdelen pro rato"): het product "combi Abonnement" is een pseudo-categorie die bij het
#: bouwen van het veldvoorstel pro rato over Pilateslessen en Yoga wordt verdeeld (basis: netto-omzet van diezelfde
#: categorieën in DEZELFDE batch → laatste 30 dagen → 50/50 mét oranje signaal), cent-exact, restcent op de grootste.
CATEGORIE_COMBI = "combi Abonnement"
CATEGORIE_COMBI_BESLISPUNT = CATEGORIE_COMBI  # naam uit 15-09 blijft importeerbaar
COMBI_REGEL_PRO_RATO = "pro_rato_batch"
COMBI_BASIS_BATCH = "batch"
COMBI_BASIS_HISTORIE = "historie_30d"
COMBI_BASIS_50_50 = "50_50"
_TOL = Decimal("0.01")

#: Default-voorstel productnaam → categorie (per administratie instelbaar; onbekend = blokkerende check).
DEFAULT_PRODUCT_CATEGORIEEN: dict[str, str] = {
    "combi abonnement": CATEGORIE_COMBI,
    "onbeperkt abonnement": CATEGORIE_PILATES,
    "5 rittenkaart": CATEGORIE_PILATES,
    "10 rittenkaart": CATEGORIE_PILATES,
    "20 rittenkaart": CATEGORIE_PILATES,
    "drop-in": CATEGORIE_PILATES,
    "proefles": CATEGORIE_PILATES,
    "losse les mat pilates": CATEGORIE_PILATES,
    "yoga 5 rittenkaart": CATEGORIE_YOGA,
    "yoga 10 rittenkaart": CATEGORIE_YOGA,
    "losse les yoga": CATEGORIE_YOGA,
}

KOLOMMEN = (
    "Factuurnummer",
    "Betaaldatum",
    "Bedrag",
    "Betaalstatus",
    "Transactiekosten",
    "Betaalmethode",
    "Aankopen",
    "Bankoverschrijving",
    "Transactiedatum",
)


@dataclass(frozen=True)
class Transactie:
    factuurnummer: str
    betaaldatum: date | None
    bedrag: Decimal
    status: str
    kosten: Decimal
    methode: str
    product: str | None
    batch: str | None
    uitbetaaldatum: date | None

    @property
    def geslaagd(self) -> bool:
        return self.status.strip().lower() in ("succeeded", "succesvol", "paid", "betaald")

    @property
    def contant(self) -> bool:
        return self.methode.strip().lower() == "contant"

    @property
    def dispute(self) -> bool:
        return self.methode.strip().lower() == "dispute" or self.bedrag < 0


@dataclass(frozen=True)
class Controle:
    naam: str
    ok: bool
    detail: str
    blokkerend: bool = True


@dataclass
class Batch:
    batch_id: str
    uitbetaaldatum: date | None
    transacties: list[Transactie]
    contant: bool = False

    @property
    def bruto(self) -> Decimal:
        return sum((t.bedrag for t in self.transacties), Decimal(0)).quantize(_TOL)

    @property
    def kosten(self) -> Decimal:
        return sum((t.kosten for t in self.transacties), Decimal(0)).quantize(_TOL)

    @property
    def netto(self) -> Decimal:
        return (self.bruto - self.kosten).quantize(_TOL)

    @property
    def periode(self) -> tuple[date | None, date | None]:
        datums = [t.betaaldatum for t in self.transacties if t.betaaldatum]
        return (min(datums), max(datums)) if datums else (None, None)


# ---------------------------------------------------------------------------------------- herkenning + parsen


def is_betalingsexport(grid: Grid) -> bool:
    kop = _kopregel(grid)
    return kop is not None and all(k in kop for k in ("Factuurnummer", "Bedrag", "Bankoverschrijving", "Aankopen"))


def _kopregel(grid: Grid) -> dict[str, int] | None:
    for r in range(min(5, len(grid.rijen))):
        rij = grid.rijen[r]
        namen: dict[str, int] = {}
        for c in sorted(rij):
            w = rij[c]
            if isinstance(w, str):
                # Dubbele kop 'Betaalstatus' (kolom 6 'Succeeded' én kolom 12 'Succesvol'): de EERSTE telt — die draagt de  # noqa: E501
                # PSP-status waarop geboekt wordt.
                namen.setdefault(w.strip(), c)
        if "Factuurnummer" in namen and "Bedrag" in namen:
            return namen
    return None


def _product_sleutel(tekst: str) -> str:
    """Productnaam-normalisatie mét cijfers (5/10/20 rittenkaart blijven onderscheidbaar): lowercase, alles behalve
    letters/cijfers → één spatie."""
    return re.sub(r"[^a-z0-9]+", " ", tekst.lower()).strip()


def _datum(w) -> date | None:  # noqa: ANN001
    if isinstance(w, date):
        return w
    if isinstance(w, str):
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", w.strip())
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    if isinstance(w, datetime):
        return w.date()
    return None


def parse_transacties(grid: Grid) -> list[Transactie]:
    kop = _kopregel(grid)
    if kop is None:
        raise ValueError("Geen kopregel met Factuurnummer/Bedrag gevonden")
    kop_r = next(
        r
        for r in range(min(5, len(grid.rijen)))
        if any(isinstance(w, str) and w.strip() == "Factuurnummer" for w in grid.rijen[r].values())
    )
    uit: list[Transactie] = []
    for r in range(kop_r + 1, len(grid.rijen)):
        rij = grid.rijen[r]
        if not rij:
            continue
        nummer = rij.get(kop["Factuurnummer"])
        bedrag = grid.getal(r, kop["Bedrag"])
        if nummer is None or bedrag is None:
            continue
        kosten = grid.getal(r, kop["Transactiekosten"]) if "Transactiekosten" in kop else None
        product = rij.get(kop["Aankopen"]) if "Aankopen" in kop else None
        batch = rij.get(kop["Bankoverschrijving"]) if "Bankoverschrijving" in kop else None
        uit.append(
            Transactie(
                factuurnummer=str(nummer).strip(),
                betaaldatum=_datum(rij.get(kop.get("Betaaldatum", -1))),
                bedrag=bedrag.quantize(_TOL),
                status=str(rij.get(kop.get("Betaalstatus", -1)) or "").strip(),
                kosten=(kosten or Decimal(0)).quantize(_TOL),
                methode=str(rij.get(kop.get("Betaalmethode", -1)) or "").strip(),
                product=str(product).strip() if product is not None else None,
                batch=str(batch).strip() if batch is not None else None,
                uitbetaaldatum=_datum(rij.get(kop.get("Transactiedatum", -1))),
            )
        )
    return uit


def transactie_sleutel(t: Transactie) -> str:
    """Identiteit van één transactieregel voor de dedupe over exports heen. Het Factuurnummer alléén volstaat niet:
    hetzelfde nummer komt terug bij betaling, dispute (chargeback) én herbetaling (bewezen in de juli-export:
    06ead052 driemaal). Sleutel = nummer|methode|bedrag|betaaldatum."""
    return f"{t.factuurnummer}|{t.methode or ''}|{t.bedrag}|{t.betaaldatum.isoformat() if t.betaaldatum else ''}"


def groepeer_batches(transacties: list[Transactie]) -> list[Batch]:
    """Per Bankoverschrijving één batch; Contant → pseudo-batch per maand ('contant-JJJJ-MM'); niet-geslaagd blijft
    buiten
    élke batch (de documentenlaag toont ze als controle)."""
    per: dict[str, list[Transactie]] = defaultdict(list)
    for t in transacties:
        if not t.geslaagd:
            continue
        if t.contant:
            maand = t.betaaldatum.strftime("%Y-%m") if t.betaaldatum else "onbekend"
            per[f"contant-{maand}"].append(t)
        elif t.batch:
            per[t.batch].append(t)
        else:
            per["zonder-uitbetaling"].append(t)
    uit: list[Batch] = []
    for batch_id, ts in per.items():
        contant = batch_id.startswith("contant-")
        uitbetaal = (
            next((t.uitbetaaldatum for t in ts if t.uitbetaaldatum), None)
            if not contant
            else max((t.betaaldatum for t in ts if t.betaaldatum), default=None)
        )
        uit.append(
            Batch(
                batch_id=batch_id,
                uitbetaaldatum=uitbetaal,
                transacties=sorted(ts, key=lambda t: (t.betaaldatum or date.min, t.factuurnummer)),
                contant=contant,
            )
        )
    return sorted(uit, key=lambda b: (b.uitbetaaldatum or date.max, b.batch_id))


def categorie_voor(product: str | None, mapping: dict[str, str] | None = None) -> str | None:
    """Productnaam → categorie: eerst de instelling van de administratie, dan de default-lijst; prefix-match op de
    genormaliseerde naam ("Proefles Reformer Pilates (1 maand geldig) - Proefles" → 'proefles'). Onbekend = None."""
    if not product:
        return None
    sleutel = _product_sleutel(product)
    kandidaten = {_product_sleutel(k): v for k, v in DEFAULT_PRODUCT_CATEGORIEEN.items()}
    kandidaten.update({_product_sleutel(k): v for k, v in (mapping or {}).items()})
    if sleutel in kandidaten:
        return kandidaten[sleutel]
    for naam, categorie in sorted(kandidaten.items(), key=lambda kv: -len(kv[0])):
        if sleutel.startswith(naam) or naam in sleutel:
            return categorie
    return None


# ---------------------------------------------------------------------------------------- veldvoorstel per batch


def bouw_batch_veldvoorstel(
    batch: Batch,
    *,
    product_categorieen: dict[str, str] | None = None,
    al_geboekte_factuurnummers: set[str] | None = None,
    bestandsnaam: str | None = None,
    combi_regel: str = COMBI_REGEL_PRO_RATO,
    combi_historie_basis: dict[str, Decimal] | None = None,
) -> dict:
    """Veldvoorstel van één uitbetaling. `combi_regel` (besluit Peter 16-09): 'pro_rato_batch' verdeelt het product
    "combi Abonnement" pro rato over Pilateslessen en Yoga; `combi_historie_basis` = netto-omzet per categorie van de
    laatste 30 dagen (terugval als de batch zelf geen basis heeft); zonder beide → 50/50 mét oranje controle."""
    per_categorie: dict[str, Decimal] = defaultdict(Decimal)
    onbekend: dict[str, Decimal] = defaultdict(Decimal)
    disputes: list[dict] = []
    combi_bedrag = Decimal(0)
    combi_transacties = 0
    for t in batch.transacties:
        cat = categorie_voor(t.product, product_categorieen)
        if cat == CATEGORIE_COMBI and combi_regel == COMBI_REGEL_PRO_RATO:
            combi_bedrag += t.bedrag
            combi_transacties += 1
            if t.dispute:
                disputes.append(
                    {"factuurnummer": t.factuurnummer, "bedrag": str(t.bedrag), "categorie": cat, "fee": str(t.kosten)}
                )
            continue
        if cat is None or cat == CATEGORIE_COMBI:
            onbekend[t.product or "(zonder productnaam)"] += t.bedrag
            cat = t.product or "(zonder productnaam)"
        per_categorie[cat] += t.bedrag
        if t.dispute:
            # Blok D: de dispute-fee zit in `kosten` en telt dus al mee in de regel "Transactiekosten PSP".
            disputes.append(
                {"factuurnummer": t.factuurnummer, "bedrag": str(t.bedrag), "categorie": cat, "fee": str(t.kosten)}
            )
    combi_verdeling: dict | None = None
    if combi_transacties:
        combi_verdeling = _verdeel_combi(
            combi_bedrag.quantize(_TOL),
            batch_basis={k: per_categorie.get(k, Decimal(0)) for k in (CATEGORIE_PILATES, CATEGORIE_YOGA)},
            historie_basis=combi_historie_basis,
        )
        combi_verdeling["transacties"] = combi_transacties
        for cat, deel in combi_verdeling["verdeling"].items():
            per_categorie[cat] += Decimal(deel)
    regels = [
        {
            "categorie": cat,
            "omzet_bedrag": str(bedrag.quantize(_TOL)),
            "kostprijs_bedrag": None,
            "zekerheid": 1.0,
            "onzeker": False,
            "herkomst_bron": "onbekend_product" if cat in onbekend else "product_categorie",
        }
        for cat, bedrag in per_categorie.items()
    ]
    if batch.kosten != 0:
        regels.append(
            {
                "categorie": CATEGORIE_KOSTEN,
                "omzet_bedrag": str((-batch.kosten).quantize(_TOL)),
                "kostprijs_bedrag": None,
                "zekerheid": 1.0,
                "onzeker": False,
                "herkomst_bron": "psp_kosten",
            }
        )
    som = sum((Decimal(r["omzet_bedrag"]) for r in regels), Decimal(0)).quantize(_TOL)
    dubbel = sorted({transactie_sleutel(t) for t in batch.transacties} & set(al_geboekte_factuurnummers or ()))
    controles = [
        asdict(
            Controle(
                "Som regels = netto uitbetaling",
                abs(som - batch.netto) <= _TOL,
                f"{som} vs bruto {batch.bruto} − kosten {batch.kosten} = {batch.netto}",
            )
        ),
        asdict(
            Controle(
                "Alle producten gecategoriseerd",
                not onbekend,
                "onbekend: " + ", ".join(f"{k} ({v})" for k, v in onbekend.items())
                if onbekend
                else f"{len(per_categorie)} categorie(ën)",
            )
        ),
        asdict(
            Controle(
                "Geen transactie al geboekt",
                not dubbel,
                f"al geboekt in een eerder document: {', '.join(dubbel)}"
                if dubbel
                else f"{len(batch.transacties)} transacties nieuw",
            )
        ),
        asdict(
            Controle(
                "Uitbetaaldatum bekend",
                batch.contant or batch.uitbetaaldatum is not None,
                batch.uitbetaaldatum.isoformat()
                if batch.uitbetaaldatum
                else ("contant — geen uitbetaling" if batch.contant else "geen Transactiedatum"),
            )
        ),
    ]
    if disputes:
        controles.append(
            asdict(
                Controle(
                    "Disputes/terugbetalingen",
                    True,
                    f"{len(disputes)} negatieve transactie(s) in de categorie van het product; de dispute-fee "
                    "telt mee in de transactiekosten",
                    blokkerend=False,
                )
            )
        )
    if combi_verdeling is not None:
        basis = combi_verdeling["basis"]
        controles.append(
            asdict(
                Controle(
                    "Combi-verdeling Pilates/Yoga",
                    basis != COMBI_BASIS_50_50,
                    (
                        f"combi Abonnement € {combi_verdeling['bedrag']} pro rato verdeeld op basis van "
                        + {
                            COMBI_BASIS_BATCH: "de netto-omzet Pilates/Yoga in deze uitbetaling",
                            COMBI_BASIS_HISTORIE: "de netto-omzet Pilates/Yoga van de laatste 30 dagen",
                            COMBI_BASIS_50_50: "50/50 — geen omzetbasis in deze batch of de laatste 30 dagen",
                        }[basis]
                        + ": "
                        + ", ".join(f"{k} € {v}" for k, v in combi_verdeling["verdeling"].items())
                    ),
                    blokkerend=False,
                )
            )
        )
    start, eind = batch.periode
    return {
        "soort": "kassarapport",
        "bron": BRON,
        "rapport_titel": f"Uitbetaling {batch.batch_id}"
        + (f" · {batch.uitbetaaldatum.isoformat()}" if batch.uitbetaaldatum else ""),
        "entiteit_naam": None,
        "periode_start": start.isoformat() if start else None,
        "periode_eind": eind.isoformat() if eind else None,
        "totaal_omzet": str(batch.netto),
        "totaal_kostprijs": None,
        "marge_pct": None,
        "zekerheden": {"periode_start": 1.0, "periode_eind": 1.0, "totaal_omzet": 1.0, "totaal_kostprijs": 0.0},
        "regels": regels,
        "regelsom_omzet": {
            "vergelijkbaar": True,
            "som": str(som),
            "totaal": str(batch.netto),
            "verschil": str(abs(som - batch.netto)),
            "sluit": abs(som - batch.netto) <= _TOL,
        },
        "regelsom_kostprijs": {"vergelijkbaar": False, "reden": "geen kostprijs in deze bron"},
        "onparseerbaar": [],
        "bsn_verwijderd": 0,
        "bron_detail": {
            "batch_id": batch.batch_id,
            "uitbetaaldatum": batch.uitbetaaldatum.isoformat() if batch.uitbetaaldatum else None,
            "contant": batch.contant,
            "bruto": str(batch.bruto),
            "kosten": str(batch.kosten),
            "netto": str(batch.netto),
            "aantal_transacties": len(batch.transacties),
            "transactie_ids": sorted(transactie_sleutel(t) for t in batch.transacties),
            "betaalmethoden": dict(sorted(_tel(t.methode for t in batch.transacties).items())),
            "disputes": disputes,
            "combi_verdeling": combi_verdeling,
            "onbekende_producten": sorted(onbekend),
            "controles": controles,
            "sluit": all(c["ok"] for c in controles if c["blokkerend"]),
            "bestandsnaam": bestandsnaam,
        },
    }


def _verdeel_combi(
    bedrag: Decimal, *, batch_basis: dict[str, Decimal], historie_basis: dict[str, Decimal] | None
) -> dict:
    """Drie takken, deterministisch: batch-basis → historie-basis (30 d) → 50/50. Cent-exact via
    `tegenzijde.verdeel_pro_rato` (restcent op de grootste basis)."""
    from app.omzet.bronnen.tegenzijde import verdeel_pro_rato

    for basis_naam, basis in ((COMBI_BASIS_BATCH, batch_basis), (COMBI_BASIS_HISTORIE, historie_basis or {})):
        verdeling = verdeel_pro_rato(bedrag, {k: basis.get(k, Decimal(0)) for k in (CATEGORIE_PILATES, CATEGORIE_YOGA)})
        if verdeling:
            totaal = sum(v for v in basis.values() if v and v > 0)
            return {
                "bedrag": str(bedrag),
                "basis": basis_naam,
                "aandeel": {
                    k: str((Decimal(basis.get(k, 0) or 0) / totaal).quantize(Decimal("0.0001"))) for k in verdeling
                },
                "verdeling": {k: str(v) for k, v in sorted(verdeling.items())},
            }
    verdeling = verdeel_pro_rato(bedrag, {CATEGORIE_PILATES: Decimal(1), CATEGORIE_YOGA: Decimal(1)})
    return {
        "bedrag": str(bedrag),
        "basis": COMBI_BASIS_50_50,
        "aandeel": {CATEGORIE_PILATES: "0.5000", CATEGORIE_YOGA: "0.5000"},
        "verdeling": {k: str(v) for k, v in sorted(verdeling.items())},
    }


def _tel(items) -> dict[str, int]:  # noqa: ANN001
    uit: dict[str, int] = defaultdict(int)
    for i in items:
        uit[str(i)] += 1
    return dict(uit)


def batch_uit_bestandsnaam(bestandsnaam: str) -> str | None:
    """Kinddocument per uitbetaling heet '<stam> — uitbetaling <batch>.xlsx' (documentenlaag) → de batch-id."""
    m = re.search(r"— uitbetaling (\S+)\.xlsx$", bestandsnaam)
    return m.group(1) if m else None


def kind_bestandsnaam(bestandsnaam: str, batch_id: str) -> str:
    stam = re.sub(r"\.xlsx$", "", bestandsnaam, flags=re.I)
    return f"{stam} — uitbetaling {batch_id}.xlsx"
