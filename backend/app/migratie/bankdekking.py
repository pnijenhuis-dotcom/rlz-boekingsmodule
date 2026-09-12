"""Bank is leidend bij dubbelen (run 2 VGG 12-09, blok 1 + 2; aanvulling Peter 12-09, CONTRACT_RUN2 besluit 6).

Een groep boekingen met gelijk bedrag en gelijke datum is pas "vermoedelijk dubbel" als er MINDER bankmutaties
tegenover staan dan boekingen. Evenveel (of meer) bankmutaties = echt (twee betalingen zijn twee boekingen) → niet
melden, wél tellen als "bank-bevestigd". De drie VGG-paren RLZ-25-00000312/313, RLZ-28-00000061/062 en
RLZ-46-00000166/167 zijn zulke echte paren.

Deze module is PUUR (geen RLZ, geen DB, geen AI); gedeeld door `app/migratie/schoonlijst.py` (blok 1) en
`app/reconciliatie/rlz_dubbel.py` (blok 2, lees-only snede 2). Agent E kopieert de bank-direct-herkenning voor de
"niet migreren"-telling.

Regels:
- Een bankmutatie matcht een boeking op cent-exact |bedrag|, ZELFDE TEKEN en `BookDate` binnen ±`venster_dagen`
  (default 3). Greedy: elke bankmutatie telt één keer per groep (dichtstbijzijnde datum eerst).
- `bank is None` = PaymentTransactions niet leesbaar → niets filteren (`bank_bevestigd=False`), wél markeren
  ("bank niet gelezen"). Nooit stil.
- Bank-directe boekingen zijn per definitie bank-bevestigd: de Receipts-collectie (een Receipt ís een bankmutatie-
  boeking) én documenten uit een bankdagboek-reeks. Zo'n reeks wordt uit de DATA afgeleid (`leid_bank_reeksen_af`):
  een boekstukreeks (`RLZ-NN`) waarvan de documenten zonder Entity 1-op-1 op PaymentTransactions vallen. Op VGG
  bleken dat (nameting 11-09 + blok 0 12-09) de reeksen RLZ-09, RLZ-25, RLZ-28, RLZ-46 en RLZ-60 —
  `BANK_REEKSEN_VGG` staat hier als gedocumenteerde referentie, NIET als default-lijst: herkenning gaat op gedrag
  (afgeleide set) of op een dagboeknaam die onmiskenbaar een bankrekening is.
- Teken per collectie (`teken_van`): PurchaseInvoices → −1 (af; een creditnota met negatief bedrag → +1),
  SalesInvoices → +1 (bij; creditnota → −1), ManualJournals/Receipts → het teken van het bedrag zelf; onbekend/0 →
  None = geen bankfilter mogelijk (de aanroeper meldt dan zonder filter)."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rlz.lezen import als_bedrag, als_datum, entity_van

VENSTER_DAGEN_DEFAULT = 3
#: Op VGG bank-direct gebleken boekstukreeksen (nameting 11-09; bevestigd door Peter 12-09). Referentie voor de
#: lezer en voor tests — de herkenning zelf gaat op gedrag (`leid_bank_reeksen_af`), niet op deze lijst alleen.
BANK_REEKSEN_VGG: frozenset[str] = frozenset({"RLZ-09", "RLZ-25", "RLZ-28", "RLZ-46", "RLZ-60"})
#: Een reeks geldt pas als bank-direct als hij genoeg documenten heeft én (bijna) álle Entity-loze documenten
#: op een bankmutatie vallen — één toevalstreffer maakt geen bankdagboek.
REEKS_MIN_DOCUMENTEN = 3
REEKS_MIN_DEKKING = Decimal("0.8")
_REEKS = re.compile(r"^([A-Z]{2,5}-\d{2,3})-\d+$")
_BANK_DAGBOEK = re.compile(r"\b(bank|rabo|rabobank|ing|abn|amro|knab|bunq|triodos|sns|asn|regiobank|deutsche)\b", re.I)


@dataclass(frozen=True)
class BankMutatie:
    """Eén PaymentTransaction, platgeslagen: `bedrag` = |Amount| cent-exact, `teken` = −1 af / +1 bij."""

    rlz_id: str
    bedrag: Decimal
    boekdatum: date
    teken: int


@dataclass(frozen=True)
class Dekking:
    """Uitkomst per groep: `bank_bevestigd` = evenveel of meer bankmutaties dan boekingen (bank gelezen);
    `bank_gelezen=False` = niets gefilterd, markering in `detail`."""

    boekingen: int
    bankmutaties: int
    bank_bevestigd: bool
    bank_gelezen: bool
    detail: str


def reeks_van(boekstuk: str | None) -> str | None:
    """`RLZ-25-00000312` → `RLZ-25`; None als het boekstuk die vorm niet heeft."""
    if not isinstance(boekstuk, str):
        return None
    m = _REEKS.match(boekstuk.strip())
    return m.group(1) if m else None


def bankmutaties_uit_rijen(rijen: Iterable[Mapping[str, object]]) -> list[BankMutatie]:
    """PaymentTransactions-rijen (Amount, BookDate/Date, id) → `BankMutatie`; rijen zonder bedrag, met bedrag 0 of
    zonder datum vallen weg (die kunnen niets bevestigen). Gesorteerd op datum, stabiel op id."""
    uit: list[BankMutatie] = []
    for r in rijen:
        bedrag = als_bedrag(r.get("Amount"))
        datum = als_datum(r.get("BookDate")) or als_datum(r.get("Date"))
        if bedrag is None or bedrag == 0 or datum is None:
            continue
        uit.append(
            BankMutatie(
                rlz_id=str(r.get("id") or ""),
                bedrag=abs(bedrag),
                boekdatum=datum,
                teken=1 if bedrag > 0 else -1,
            )
        )
    uit.sort(key=lambda m: (m.boekdatum, m.rlz_id))
    return uit


def teken_van(collectie: str, bedrag: Decimal | None) -> int | None:
    """Verwacht teken van de bankmutatie die bij een document van deze collectie hoort; None = onbekend → geen
    bankfilter."""
    if bedrag is None or bedrag == 0:
        return None
    richting = 1 if bedrag > 0 else -1
    if collectie == "PurchaseInvoices":
        return -richting
    if collectie == "SalesInvoices":
        return richting
    if collectie in ("ManualJournals", "Receipts"):
        return richting
    return None


def is_bank_direct(
    collectie: str,
    boekstuk: str | None,
    dagboek: str | None,
    *,
    bank_reeksen: Collection[str] = (),
) -> bool:
    """Receipts óf een boekstukreeks uit `bank_reeksen` (afgeleid met `leid_bank_reeksen_af`) óf een dagboeknaam
    die onmiskenbaar een bankrekening is. Zonder afgeleide set en zonder dagboeknaam is alleen Receipts bank-direct —
    bewust: een reekscode alleen zegt per administratie iets anders."""
    if collectie == "Receipts":
        return True
    reeks = reeks_van(boekstuk)
    if reeks is not None and reeks in bank_reeksen:
        return True
    return bool(dagboek and _BANK_DAGBOEK.search(dagboek))


def _match_greedy(
    boekingen: Sequence[tuple[Decimal, date, int]], bank: Sequence[BankMutatie], *, venster_dagen: int
) -> int:
    """Aantal boekingen dat een EIGEN bankmutatie vindt (|bedrag| gelijk, teken gelijk, datum binnen het venster);
    per boeking de dichtstbijzijnde vrije mutatie, boekingen op datumvolgorde."""
    vrij: dict[int, BankMutatie] = dict(enumerate(bank))
    gevonden = 0
    for bedrag, datum, teken in sorted(boekingen, key=lambda b: b[1]):
        beste: int | None = None
        beste_afstand: int | None = None
        for i, m in vrij.items():
            if m.teken != teken or m.bedrag != abs(bedrag):
                continue
            afstand = abs((m.boekdatum - datum).days)
            if afstand > venster_dagen:
                continue
            if beste_afstand is None or afstand < beste_afstand:
                beste, beste_afstand = i, afstand
        if beste is not None:
            del vrij[beste]
            gevonden += 1
    return gevonden


def dekking_voor(
    groep: Sequence[tuple[Decimal, date, int]],
    bank: Sequence[BankMutatie] | None,
    *,
    venster_dagen: int = VENSTER_DAGEN_DEFAULT,
) -> Dekking:
    """Bankdekking van één groep boekingen `(bedrag, datum, teken)`. `bank=None` = niet gelezen → nooit bevestigd,
    zichtbaar gemarkeerd. Een boeking met teken None (`teken_van` onbekend) sluit het filter voor de hele groep uit
    (detail "teken onbekend") — liever één regel te veel gemeld dan één stil weggefilterd."""
    n = len(groep)
    if bank is None:
        return Dekking(
            boekingen=n, bankmutaties=0, bank_bevestigd=False, bank_gelezen=False, detail="bank niet gelezen"
        )
    if any(t is None for _, _, t in groep):
        return Dekking(
            boekingen=n,
            bankmutaties=0,
            bank_bevestigd=False,
            bank_gelezen=True,
            detail="teken onbekend — geen bankfilter",
        )
    k = _match_greedy(groep, bank, venster_dagen=venster_dagen)
    bevestigd = n > 0 and k >= n
    return Dekking(
        boekingen=n,
        bankmutaties=k,
        bank_bevestigd=bevestigd,
        bank_gelezen=True,
        detail=f"{n} boekingen, {k} bankmutaties (±{venster_dagen} d)",
    )


def leid_bank_reeksen_af(
    documenten: Mapping[str, Iterable[Mapping[str, object]]],
    bank: Sequence[BankMutatie] | None,
    *,
    venster_dagen: int = 0,
    min_documenten: int = REEKS_MIN_DOCUMENTEN,
    min_dekking: Decimal = REEKS_MIN_DEKKING,
) -> dict[str, tuple[int, int]]:
    """Per boekstukreeks (`RLZ-NN`) van Entity-loze documenten: (aantal, aantal dat op een bankmutatie valt —
    cent-exact |bedrag|, teken via `teken_van` (een inkoopfactuur van € 415 hoort bij een afboeking van € −415),
    zelfde dag). Een reeks met ≥ `min_documenten` én dekking ≥ `min_dekking` is een
    bankdagboek-reeks (bank-direct). Bank niet gelezen → leeg (niets af te leiden, niets te filteren).
    Op VGG: RLZ-09, RLZ-25, RLZ-28, RLZ-46, RLZ-60 (`BANK_REEKSEN_VGG`)."""
    if bank is None:
        return {}
    per_reeks: dict[str, list[tuple[Decimal, date, int]]] = {}
    for collectie, rijen in documenten.items():
        # Receipts zijn per definitie bank-direct; ze doen tóch mee zodat de kop laat zien welke reeks dat is (VGG:
        # RLZ-09 8/8) en de afleiding voor E één beeld geeft.
        for r in rijen:
            if entity_van(dict(r))[0] is not None:
                continue
            reeks = reeks_van(r.get("ReceiptNumber") if isinstance(r.get("ReceiptNumber"), str) else None)
            bedrag = als_bedrag(r.get("BaseInvoiceAmount"))
            datum = als_datum(r.get("Date")) or als_datum(r.get("BookDate"))
            teken = teken_van(collectie, bedrag)
            if reeks is None or bedrag is None or datum is None or teken is None:
                continue
            per_reeks.setdefault(reeks, []).append((bedrag, datum, teken))
    uit: dict[str, tuple[int, int]] = {}
    for reeks, boekingen in per_reeks.items():
        n = len(boekingen)
        if n < min_documenten:
            continue
        k = _match_greedy(boekingen, bank, venster_dagen=venster_dagen)
        if Decimal(k) / Decimal(n) >= min_dekking:
            uit[reeks] = (n, k)
    return dict(sorted(uit.items()))
