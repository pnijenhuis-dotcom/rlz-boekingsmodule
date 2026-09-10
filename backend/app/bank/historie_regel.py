"""Historie-regel voor bankmutaties zonder open-post-match (blok B bundel 10-09; besluit Peter 10-09).

Deterministisch en puur (code voor cijfers, geen I/O, geen AI): een open mutatie waarvoor géén open
post/factuur bestaat en géén vaste regel geldt, krijgt een grootboek-/btw-voorstel uit de HISTORIE van
dezelfde tegenpartij — sleutel = tegenrekening-IBAN + genormaliseerde omschrijvingskern (bedrag vrij:
een variabel maandbedrag van dezelfde partij op dezelfde rekening is precies het geval).

Voorwaarden voor een KANDIDAAT (automatisch boeken achter `bank_autoboeken_ingeschakeld`, mét de
AI-plausibiliteitstoets als poort — app/aitoets/):
- historie-dekking ≥ 6 maanden (oudste boeking in de bron ≥ `MIN_DEKKING_DAGEN` vóór vandaag; korter =
  "historie te kort", geen voorstel — een jonge administratie heeft nog geen patroon);
- ≥ `MIN_BOEKINGEN` boekingen op de sleutel;
- 100 % dezelfde (grootboek, btw-behandeling) → groen, automatisch kandidaat; < 100 % → oranje voorstel
  "historie: k van n op …" (k/n van de meest voorkomende combinatie), mens bevestigt; gelijkstand = oranje,
  nooit gokken.
- NOOIT als voor de tegenpartij open posten/facturen bestaan (naam-overlap met een open post, of een
  geleerde IBAN↔relatie) — open-post-match gaat vóór (mockup-volgorde 1–5; dit is stap 3b).

Bron van de historie: RLZ-historie (direct-op-grootboek-boekingen, `BankMutationDirectBookings` via de
PaymentReferenceList van afgeletterde mutaties) én module-boekingen (`bank_boeking`) — gecached in
`bank_historie_boeking` (app/bank/historie_bron.py, migratie 0129). Zie BESLISSINGEN "BANK — HISTORIE-REGEL +
AI-PLAUSIBILITEITSTOETS ALS POORT"."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date

from app.bank.matchmotor import (
    IbanRelatie,
    MutatieGegevens,
    OpenPost,
    naam_komt_overeen,
    normaliseer_iban,
)

BRON_RLZ = "rlz"
BRON_MODULE = "module"

#: Minimale historie-dekking: de oudste boeking in de bron moet minstens zoveel dagen oud zijn.
MIN_DEKKING_DAGEN = 183
#: Minimaal aantal boekingen op de sleutel vóór er een voorstel komt.
MIN_BOEKINGEN = 3
#: Woorden korter dan dit tellen niet in de omschrijvingskern.
_MIN_WOORD_LENGTE = 3

# Bank-opmaakwoorden (SEPA-veldlabels en betaalvormen) die in élke omschrijving van een bank kunnen staan
# en niets zeggen over de tegenpartij/prestatie — ze zouden anders twee verschillende betalingen op dezelfde
# kern trekken of een kern kunstmatig vullen.
_KERN_STOPWOORDEN = frozenset(
    {
        "sepa",
        "iban",
        "bic",
        "naam",
        "omschrijving",
        "kenmerk",
        "machtiging",
        "incassant",
        "incasso",
        "overboeking",
        "periodieke",
        "periodiek",
        "periode",
        "termijn",
        "datum",
        "valutadatum",
        "transactie",
        "eur",
        "euro",
        "betaling",
        "betaalkenmerk",
        "factuurnummer",
        "factuurnr",
        "factuur",
        "referentie",
        "ref",
        "nr",
        "van",
        "voor",
        "aan",
        "the",
        "and",
        "een",
        "het",
        "met",
        "bij",
        "via",
        "ideal",
        "pin",
    }
)

_IBAN_PATROON = re.compile(r"\b[a-z]{2}\d{2}[a-z0-9]{4}\d{7}[a-z0-9]{0,16}\b")
_DATUM_PATROON = re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.](?:\d{2}|\d{4})\b|\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")
_BEDRAG_PATROON = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b")
_SPLITSER = re.compile(r"[^0-9a-zà-ÿ]+")


def omschrijvingskern(omschrijving: str | None) -> str:
    """De stabiele kern van een bankomschrijving: lowercase, zonder IBAN's, datums, bedragen, cijferreeksen
    (kenmerken, factuurnummers, periodes) en bank-opmaakwoorden; alleen woorden ≥ 3 letters, in volgorde,
    ontdubbeld en met enkele spaties. Lege kern = geen sleutel (nooit een voorstel op niets)."""
    if not omschrijving:
        return ""
    tekst = omschrijving.lower()
    tekst = _IBAN_PATROON.sub(" ", tekst)
    tekst = _DATUM_PATROON.sub(" ", tekst)
    tekst = _BEDRAG_PATROON.sub(" ", tekst)
    woorden: list[str] = []
    for token in _SPLITSER.split(tekst):
        if not token or any(teken.isdigit() for teken in token):
            continue  # kenmerk-/factuurnummer-/periodetokens ("f0024082026", "2026w36") vallen weg
        if len(token) < _MIN_WOORD_LENGTE or token in _KERN_STOPWOORDEN:
            continue
        if token not in woorden:
            woorden.append(token)
    return " ".join(woorden)


@dataclass(frozen=True)
class HistorieSleutel:
    iban: str
    kern: str

    def label(self) -> str:
        return f"{self.iban} · {self.kern}"


def historie_sleutel(tegenrekening_iban: str | None, omschrijving: str | None) -> HistorieSleutel | None:
    """IBAN (genormaliseerd) + omschrijvingskern; ontbreekt één van beide → geen sleutel."""
    iban = normaliseer_iban(tegenrekening_iban)
    kern = omschrijvingskern(omschrijving)
    if iban is None or not kern:
        return None
    return HistorieSleutel(iban=iban, kern=kern)


@dataclass(frozen=True)
class HistorieBoeking:
    """Eén eerdere direct-op-grootboek-boeking van een bankmutatie (RLZ-historie of module)."""

    payment_transaction_id: uuid.UUID
    datum: date
    tegenrekening_iban: str | None
    omschrijving: str | None
    tegenpartij_naam: str | None
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    bron: str  # BRON_RLZ | BRON_MODULE


@dataclass(frozen=True)
class HistorieVoorstel:
    kleur: str  # "groen" (100 %, automatisch kandidaat) | "oranje" (k van n, bevestigen)
    k: int
    n: int
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    automatisch_kandidaat: bool
    sleutel: HistorieSleutel

    def label(self, rekening_label: str) -> str:
        """Chip-/bron-tekst: "historie: k van n op ‹rekening›"."""
        return f"historie: {self.k} van {self.n} op {rekening_label}"


@dataclass(frozen=True)
class HistorieUitkomst:
    """Voorstel óf een leesbare reden waarom er geen historie-voorstel is (nooit stil)."""

    voorstel: HistorieVoorstel | None
    reden: str


def _open_posten_voor_tegenpartij(
    mutatie: MutatieGegevens, *, open_posten: list[OpenPost], iban_relaties: list[IbanRelatie], iban: str
) -> bool:
    if any(naam_komt_overeen(post.tegenpartij_naam, mutatie.tegenpartij_naam) for post in open_posten):
        return True
    return any(normaliseer_iban(relatie.iban) == iban for relatie in iban_relaties)


def bepaal_historie_voorstel(
    mutatie: MutatieGegevens,
    historie: list[HistorieBoeking],
    *,
    open_posten: list[OpenPost],
    iban_relaties: list[IbanRelatie],
    vandaag: date,
) -> HistorieUitkomst:
    """De historie-regel voor één mutatie (puur). Volgorde van de poorten is bewust: eerst de sleutel
    (geen IBAN/kern = niets te matchen), dan open posten (open-post-match gaat vóór), dan dekking, dan aantal,
    dan de 100 %-toets."""
    sleutel = historie_sleutel(mutatie.tegenrekening_iban, mutatie.omschrijving)
    if sleutel is None:
        return HistorieUitkomst(None, "geen sleutel — tegenrekening-IBAN of omschrijvingskern ontbreekt")
    if _open_posten_voor_tegenpartij(mutatie, open_posten=open_posten, iban_relaties=iban_relaties, iban=sleutel.iban):
        return HistorieUitkomst(None, "open posten voor deze tegenpartij — open-post-match gaat vóór")
    if not historie:
        return HistorieUitkomst(None, "geen historie beschikbaar")
    oudste = min(boeking.datum for boeking in historie)
    if (vandaag - oudste).days < MIN_DEKKING_DAGEN:
        return HistorieUitkomst(
            None, f"historie te kort — oudste boeking {oudste.isoformat()}, minimaal {MIN_DEKKING_DAGEN} dagen vereist"
        )
    op_sleutel = [
        boeking for boeking in historie if historie_sleutel(boeking.tegenrekening_iban, boeking.omschrijving) == sleutel
    ]
    n = len(op_sleutel)
    if n < MIN_BOEKINGEN:
        return HistorieUitkomst(None, f"{n} eerdere boeking(en) op deze sleutel — minimaal {MIN_BOEKINGEN} vereist")
    tellingen = Counter((boeking.ledger_id, boeking.taxrate_id) for boeking in op_sleutel)
    gesorteerd = sorted(tellingen.items(), key=lambda kv: (-kv[1], str(kv[0][0]), str(kv[0][1])))
    (ledger_id, taxrate_id), k = gesorteerd[0]
    gelijkstand = len(gesorteerd) > 1 and gesorteerd[1][1] == k
    volledig = k == n and not gelijkstand
    voorstel = HistorieVoorstel(
        kleur="groen" if volledig else "oranje",
        k=k,
        n=n,
        ledger_id=ledger_id,
        taxrate_id=taxrate_id,
        automatisch_kandidaat=volledig,
        sleutel=sleutel,
    )
    if volledig:
        return HistorieUitkomst(voorstel, f"{n} eerdere boekingen, alle op dezelfde rekening en btw-behandeling")
    if gelijkstand:
        return HistorieUitkomst(voorstel, f"gelijkstand: {k} van {n} op twee combinaties — bevestigen")
    return HistorieUitkomst(voorstel, f"{k} van {n} op de meest voorkomende combinatie — bevestigen")


def historie_samenvatting(historie: list[HistorieBoeking], sleutel: HistorieSleutel | None, *, rekening_label) -> str:
    """Deterministische samenvatting voor de AI-plausibiliteitstoets (geen rijen, geen persoonsgegevens buiten
    wat de sleutel al draagt): "n eerdere mutaties, k× ‹rekening› (p %)"."""
    if sleutel is None:
        return "geen historie-sleutel"
    op_sleutel = [b for b in historie if historie_sleutel(b.tegenrekening_iban, b.omschrijving) == sleutel]
    if not op_sleutel:
        return "0 eerdere mutaties op deze sleutel"
    tellingen = Counter((b.ledger_id, b.taxrate_id) for b in op_sleutel)
    n = len(op_sleutel)
    delen = [
        f"{aantal}× {rekening_label(ledger_id, taxrate_id)} ({round(100 * aantal / n)} %)"
        for (ledger_id, taxrate_id), aantal in sorted(tellingen.items(), key=lambda kv: (-kv[1], str(kv[0][0])))
    ]
    return f"{n} eerdere mutaties, " + ", ".join(delen)
