"""Betaalstatus van een inkoopfactuur (blok 3 bundel 08-09 avond; STAP-0 08-09 in api-verkenning "Betaalstatus
inkoopfactuur — STAP-0 08-09"): het RLZ-UI-veld "Betaling" = `QuickPaymentSelection` op de PurchaseInvoice. Effect in
RLZ: de post blijft OPEN (BaseRemainingAmount ongewijzigd) maar verdwijnt uit de betaallijst — precies wat een
declaratie
(al door een medewerker betaald) of een incasso-factuur (de bank haalt 'm zelf) nodig heeft.

Pure module (geen DB, geen HTTP): de acht RLZ-waarden LETTERLIJK, normalisatie voor de label-match tegen RLZ's
per-document
keuzelijst, en de DETERMINISTISCHE incasso-detectie op factuurtekst (Code voor cijfers, AI voor taal: de AI mag een
`betaalwijze`-/`incasso_datum`-tekst voorlezen, óf die tekst een incasso betekent en welke datum dat is beslist deze
code).

Winnaarsvolgorde (documenten/boekvoorstel.py): mens > kanaal (declaraties@ = "Betaald per bank") > factuur (incasso) >
leeg.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from app.extractie.controle import parse_datum

# De acht RLZ-waarden — de `Description` van `GET PurchaseInvoices/{id}/QuickPaymentSelections` (STAP-0 08-09,
# identiek in
# productie- en testadministratie). We bewaren en tonen ZE ZO (RLZ's eigen spelling: "Betaald - contant" met los
# streepje,
# "Verrekend met prive" zonder accent) zodat het controlescherm en RLZ dezelfde woorden gebruiken.
NOG_TE_BETALEN = "Nog te betalen"
AUTOMATISCH_GEINCASSEERD = "Wordt automatisch geïncasseerd"
BETAALD_PER_BANK = "Betaald per bank"
BETAALD_MET_PIN = "Betaald met PIN"
BETAALD_MET_CREDITCARD = "Betaald met Creditcard"
BETAALD_CONTANT = "Betaald - contant"
VERREKEND_MET_PRIVE = "Verrekend met prive"
VERREKEND_MET_REKENING_COURANT = "Verrekend met Rekening Courant"

BETAALSTATUSSEN: tuple[str, ...] = (
    NOG_TE_BETALEN,
    AUTOMATISCH_GEINCASSEERD,
    BETAALD_PER_BANK,
    BETAALD_MET_PIN,
    BETAALD_MET_CREDITCARD,
    BETAALD_CONTANT,
    VERREKEND_MET_PRIVE,
    VERREKEND_MET_REKENING_COURANT,
)

# Herkomst van de stand op het boekvoorstel (kolom `betaalstatus_herkomst`, migratie 0126).
HERKOMST_KANAAL = "kanaal"  # declaraties@-postvak → "Betaald per bank"
HERKOMST_FACTUUR = "factuur"  # deterministische incasso-detectie op de factuurtekst / UBL PaymentMeansCode 59
HERKOMST_MENS = "mens"  # keuze op het controlescherm, wint altijd
HERKOMSTEN: tuple[str, ...] = (HERKOMST_KANAAL, HERKOMST_FACTUUR, HERKOMST_MENS)

# Intake-kanalen (kolom `intake_bericht.kanaal`): het bestaande facturen@-postvak en het nieuwe declaraties@-postvak.
KANAAL_FACTUREN = "facturen"
KANAAL_DECLARATIES = "declaraties"
KANALEN: tuple[str, ...] = (KANAAL_FACTUREN, KANAAL_DECLARATIES)
# Wat een kanaal over de betaalstatus zegt: een declaratie is per definitie al door de medewerker betaald.
BETAALSTATUS_PER_KANAAL: dict[str, str] = {KANAAL_DECLARATIES: BETAALD_PER_BANK}

# UBL: cac:PaymentMeans/cbc:PaymentMeansCode (UNCL4461) — 59 = SEPA direct debit, 49 = direct debit.
UBL_INCASSO_CODES: frozenset[str] = frozenset({"59", "49"})


def normaliseer_label(tekst: str | None) -> str:
    """Vergelijkingsvorm van een RLZ-keuzelabel: kleine letters, accenten weg, alleen letters/cijfers. Zo matcht
    "Betaald – contant" (mens-typografie) op "Betaald - contant" (RLZ) en "geïncasseerd" op "geincasseerd"."""
    if not tekst:
        return ""
    zonder_accent = "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", zonder_accent.lower())


_GENORMALISEERD: dict[str, str] = {normaliseer_label(s): s for s in BETAALSTATUSSEN}


def canoniek(tekst: str | None) -> str | None:
    """De canonieke RLZ-waarde voor een (mens-)invoer, of None als het geen van de acht is (nooit een gok)."""
    return _GENORMALISEERD.get(normaliseer_label(tekst))


def is_geldig(tekst: str | None) -> bool:
    return canoniek(tekst) is not None


def kies_keuze_id(keuzes: list[dict], betaalstatus: str) -> str | None:
    """Het RLZ-keuze-id voor een betaalstatus uit de per-document opgehaalde `QuickPaymentSelections`-lijst — match op
    het genormaliseerde label, nooit op een gehardcode GUID (les RLZ-systeemrekeningen: GUID's zijn template-GUID's,
    maar
    we varen op wat déze administratie teruggeeft)."""
    doel = normaliseer_label(betaalstatus)
    for keuze in keuzes:
        if normaliseer_label(str(keuze.get("Description") or "")) == doel:
            return str(keuze.get("id")) if keuze.get("id") else None
    return None


# --- deterministische incasso-detectie ----------------------------------------------------------------------------


@dataclass(frozen=True)
class IncassoDetectie:
    """Uitkomst van de tekst-detectie: de betaalstatus (altijd `AUTOMATISCH_GEINCASSEERD`), de verwachte betaaldatum als
    die uit de tekst te halen was, en de zin die de detectie droeg (zichtbaar op het controlescherm — niets
    onzichtbaar)."""

    betaalstatus: str
    verwachte_betaaldatum: date | None
    bron_tekst: str


# Zinsdelen die een automatische incasso aankondigen. Bewust géén los "SEPA" of "machtiging": die woorden staan ook op
# facturen die om een gewone overboeking vragen ("SEPA-overboeking", "machtiging intrekken") — alleen combinaties die
# ondubbelzinnig zijn. Kleine letters, accenten weg (zie _plat).
_INCASSO_PATRONEN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"wordt\s+(?:automatisch\s+)?ge.?ncasseerd",
        r"automatisch(?:e)?\s+incasso",
        r"automatische\s+afschrijving",
        r"via\s+(?:sepa[\s-]*)?incasso",
        r"sepa[\s-]*(?:direct[\s-]*debit|incasso)",
        r"per\s+incasso",
        r"middels\s+incasso",
        r"(?:wij|we)\s+(?:schrijven|incasseren|zullen)\b[^.\n]{0,80}?\b(?:af(?:schrijven)?|incasseren)",
        r"(?:het|dit)\s+(?:factuur)?bedrag\s+wordt\b[^.\n]{0,60}?\b(?:afgeschreven|ge.?ncasseerd)",
        r"incasso\s+(?:op|rond|omstreeks|per|vanaf|ca\.?)\s+\d",
        r"direct\s+debit",
    )
)

# Niet-incasso-uitsluitingen: een factuur die juist zegt dat er NIET geïncasseerd wordt.
_NEGATIES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (r"geen\s+(?:automatische\s+)?incasso", r"niet\s+(?:automatisch\s+)?ge.?ncasseerd")
)

_MAANDEN = {
    "januari": 1,
    "jan": 1,
    "februari": 2,
    "feb": 2,
    "maart": 3,
    "mrt": 3,
    "april": 4,
    "apr": 4,
    "mei": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "augustus": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_DATUM_NUMERIEK = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")
_DATUM_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATUM_TEKST = re.compile(
    r"\b(\d{1,2})\s+(januari|jan|februari|feb|maart|mrt|april|apr|mei|juni|jun|juli|jul|augustus|aug|september|sept|sep|"
    r"oktober|okt|november|nov|december|dec)\.?\s*(\d{4})?\b"
)
_TERMIJN_DAGEN = re.compile(r"(?:binnen|na|over)\s+(\d{1,3})\s+dagen")
_ROND_DE = re.compile(
    r"(?:rond|omstreeks|op|per|vanaf|ca\.?)\s+(?:de\s+)?(\d{1,2})(?:e|ste|de)?\s+(?:van\s+)?(?:de|elke|iedere)?\s*maand"
)


def _plat(tekst: str) -> str:
    zonder_accent = "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))
    return re.sub(r"[ \t\xa0]+", " ", zonder_accent.lower())


def _zin_rond(tekst_plat: str, positie: int, origineel: str) -> str:
    """De zin (tot punt/regeleinde) rond een trefpositie, uit het origineel (zelfde lengte na _plat: NFKD-stripping kan
    lengtes verschuiven — daarom terug via de platte tekst en begrensd afkappen)."""
    begin = max(tekst_plat.rfind("\n", 0, positie), tekst_plat.rfind(". ", 0, positie))
    begin = 0 if begin < 0 else begin + 1
    eind_kandidaten = [i for i in (tekst_plat.find("\n", positie), tekst_plat.find(". ", positie)) if i >= 0]
    eind = min(eind_kandidaten) if eind_kandidaten else len(tekst_plat)
    zin = tekst_plat[begin:eind].strip()
    return zin[:200]


def _datum_uit(zin: str, *, anker: date | None) -> date | None:
    """Een concrete datum uit de incasso-zin: ISO, dd-mm-jjjj, '15 oktober (2026)', 'binnen 14 dagen' (t.o.v. het
    anker =
    factuurdatum), 'rond de 25e van de maand' (eerstvolgende zo'n dag ná het anker). Geen datum = None — nooit
    gokken."""
    m = _DATUM_ISO.search(zin)
    if m:
        return parse_datum(m.group(0))
    m = _DATUM_NUMERIEK.search(zin)
    if m:
        d, mm, jj = m.groups()
        jaar = int(jj) if len(jj) == 4 else 2000 + int(jj)
        try:
            return date(jaar, int(mm), int(d))
        except ValueError:
            return None
    m = _DATUM_TEKST.search(zin)
    if m:
        d, maand, jj = m.groups()
        jaar = int(jj) if jj else (anker.year if anker else None)
        if jaar is None:
            return None
        try:
            kandidaat = date(jaar, _MAANDEN[maand], int(d))
        except ValueError:
            return None
        # Zonder jaartal en vóór het anker: de factuur bedoelt volgend jaar (december-factuur, incasso in januari).
        if not jj and anker is not None and kandidaat < anker:
            try:
                kandidaat = date(jaar + 1, _MAANDEN[maand], int(d))
            except ValueError:
                return None
        return kandidaat
    m = _TERMIJN_DAGEN.search(zin)
    if m and anker is not None:
        return anker + timedelta(days=int(m.group(1)))
    m = _ROND_DE.search(zin)
    if m and anker is not None:
        dag = int(m.group(1))
        if 1 <= dag <= 31:
            jaar, maand = anker.year, anker.month
            for _ in range(3):
                try:
                    kandidaat = date(jaar, maand, dag)
                except ValueError:
                    kandidaat = None
                if kandidaat is not None and kandidaat >= anker:
                    return kandidaat
                maand += 1
                if maand > 12:
                    maand, jaar = 1, jaar + 1
    return None


def detecteer_incasso(
    *teksten: str | None, factuurdatum: date | None = None, incasso_datum_tekst: str | None = None
) -> IncassoDetectie | None:
    """Deterministische incasso-detectie over één of meer teksten (PDF-tekstlaag, het AI-veld `betaalwijze`, de
    mail-body). Eerste ondubbelzinnige treffer wint; een expliciete negatie ("geen automatische incasso") in dezelfde
    tekst
    telt zwaarder. `incasso_datum_tekst` (AI-veld, ruw) wordt alleen als DATUM geparst (code), nooit als bewijs van
    incasso.
    None = geen incasso-vermelding gevonden (de betaalstatus blijft dan leeg — nooit "Nog te betalen" invullen)."""
    for tekst in teksten:
        if not tekst:
            continue
        plat = _plat(tekst)
        if any(n.search(plat) for n in _NEGATIES):
            continue
        for patroon in _INCASSO_PATRONEN:
            m = patroon.search(plat)
            if not m:
                continue
            zin = _zin_rond(plat, m.start(), tekst)
            datum = _datum_uit(zin, anker=factuurdatum)
            if datum is None and incasso_datum_tekst:
                datum = parse_datum(incasso_datum_tekst) or _datum_uit(_plat(incasso_datum_tekst), anker=factuurdatum)
            if datum is None:
                # Zoek nog in de directe omgeving (de datum staat vaak in de volgende regel: "Incassodatum:
                # 25-09-2026").
                omgeving = plat[m.start() : m.start() + 240]
                datum = _datum_uit(omgeving, anker=factuurdatum)
            return IncassoDetectie(betaalstatus=AUTOMATISCH_GEINCASSEERD, verwachte_betaaldatum=datum, bron_tekst=zin)
    return None


def is_ubl_incasso(payment_means_code: str | None) -> bool:
    """UBL PaymentMeansCode 59 (SEPA direct debit) of 49 (direct debit) = incasso — deterministisch, geen tekst
    nodig."""
    return (payment_means_code or "").strip() in UBL_INCASSO_CODES
