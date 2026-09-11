"""Deterministische matchmotor voor bankmutaties (code voor cijfers — geen AI, geen gok).

Voorstel-volgorde (goedgekeurd ontwerp, mockup #bankdetail + CLAUDE.md "Bank", stap 4 hersteld
na de schrijf-PoC):
1. exacte match — sinds blok 2 (08-09): TEKEN klopt (inkoop↔afschrijving, verkoop↔bijschrijving,
   creditnota omgekeerd) én NAAM/IBAN én factuurNUMMER als heel token én BEDRAG cent-exact → groen
   (auto-afletteren-kandidaat achter de opt-in);
2. gedeeltelijke match — geen teken-mismatch en twee van {naam/IBAN, nummer, bedrag}
   (deelbetaling/G-rekening-split, nummer zonder naam, naam+bedrag zonder nummer) → oranje, bevestigen;
3. vaste regel uit het geheugen (tegenpartij → grootboek/btw) → direct-op-grootboek-voorstel;
3b. historie-regel (blok B bundel 10-09, app/bank/historie_regel.py): IBAN + omschrijvingskern in de
   historie ≥ 3× op dezelfde rekening/btw → groen (automatisch kandidaat achter de opt-in, mét de
   AI-plausibiliteitstoets als poort) of oranje "k van n" — nooit als er open posten voor de tegenpartij zijn;
4. RLZ's eigen voorstel (auto-gevuld MatchedPaymentItem bij exacte bedrag-match) — mét bron;
5. handmatig.

Stap 1/2/4 zijn afletter-voorstellen tegen een open post: die kunnen via de publieke API niet
geschreven worden (15/16/34/218 dicht — fallback-PoC), dus ze monden uit in het assist-model
(app/bank/afletteren.py). Stap 3 is wél volautomatisch bouwbaar (direct-op-grootboek).

Alles hier is puur en zonder I/O: de service-laag (voorstellen.py) voert data aan, deze module
beslist — en is daarmee 1-op-1 unit-testbaar (tests verplicht op geldlogica).

Aanleiding herziening stap 1/2 (productie 08-09, Administratiekantoor Nijenhuis C.V.): de oude
substring-referentiematch koppelde € 12.500 BIJ van een privépersoon aan verkoopfactuur 2352 ("2352"
zat in het kenmerk 26247623521810) en een afschrijving aan een verkoopfactuur (tekenfout). Zie
BESLISSINGEN "MATCHMOTOR BANK — NAAM/IBAN + NUMMER + BEDRAG + TEKEN (blok 2 bundel 08-09)"."""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.tijd import vandaag_nl

# --- referentie (factuurnummer) als HEEL token ------------------------------------------------------
#
# Blok 2 bundel 08-09 (productiegeval Administratiekantoor Nijenhuis C.V.): de oude substring-match
# zag "2352" in het betalingskenmerk "26247623521810" en stelde verkoopfactuur 2352 voor bij een
# bijschrijving van € 12.500 van een heel andere partij. Een factuurnummer telt sindsdien alleen als
# HEEL token: tokeniseer op niet-alfanumeriek, vergelijk genormaliseerde tokens én samengestelde
# aangrenzende tokens ("2026-0642" in de omschrijving → tokens "2026","0642" → samengesteld
# "20260642" = de genormaliseerde referentie), nooit als substring van een langer cijferblok.

# Een referentie korter dan dit aantal tekens (na normalisatie) is te generiek om op te matchen
# ("1", "42" — dat soort tokens staat in elke omschrijving); nooit een voorstel op baseren.
_MIN_REFERENTIE_LENGTE = 4
# 4–5 tekens ("2352", "26247"): alleen tellen als het bedrag óók exact klopt (brief 2a-ii).
_KORTE_REFERENTIE_GRENS = 6
# Samengestelde tokens: maximaal zoveel aangrenzende tokens aaneengeplakt ("F", "2026", "0642").
_MAX_SAMENGESTELDE_TOKENS = 4
# Een cijferkern (letters vooraan gestript) moet minstens zo lang zijn om als kern te tellen.
_MIN_CIJFERKERN_LENGTE = 6

_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")
_LEIDENDE_LETTERS = re.compile(r"^[a-z]+")


def _genormaliseerd(tekst: str | None) -> str:
    """Lowercase + alles behalve letters/cijfers eruit — "2026-0642" en "2026 0642" worden
    beide "20260642", zodat opmaakverschillen tussen bankomschrijving en factuurreferentie
    geen match breken."""
    if not tekst:
        return ""
    return _NIET_ALFANUMERIEK.sub("", tekst.lower())


def _tokens(tekst: str | None) -> list[str]:
    if not tekst:
        return []
    return [token for token in _NIET_ALFANUMERIEK.split(tekst.lower()) if token]


def _samengestelde_tokens(tokens: list[str]) -> set[str]:
    """Alle losse tokens plus alle aaneengeplakte reeksen van 2..N aangrenzende tokens."""
    uit: set[str] = set()
    for i in range(len(tokens)):
        for n in range(1, _MAX_SAMENGESTELDE_TOKENS + 1):
            if i + n > len(tokens):
                break
            uit.add("".join(tokens[i : i + n]))
    return uit


def _cijferkern(token: str) -> str | None:
    """Het cijferdeel ná een eventueel letter-voorvoegsel ("F20260642" → "20260642"); alleen een
    zuivere cijferreeks van voldoende lengte telt. Vangt "INV20260642" vs "2026-0642" — een
    voorvoegsel van letters, nooit een langer CIJFERblok."""
    kern = _LEIDENDE_LETTERS.sub("", token)
    if len(kern) >= _MIN_CIJFERKERN_LENGTE and kern.isdigit():
        return kern
    return None


def referentie_als_token(referentie: str | None, *mutatie_teksten: str | None) -> bool:
    """Deterministische factuurnummer-match: de genormaliseerde referentie staat als HEEL token (of
    als aaneengeplakte reeks aangrenzende tokens) in één van de mutatieteksten. Een referentie
    korter dan `_MIN_REFERENTIE_LENGTE` matcht nooit; een substring van een langer cijferblok
    matcht nooit ("2352" ⊄ "26247623521810")."""
    ref = _genormaliseerd(referentie)
    if len(ref) < _MIN_REFERENTIE_LENGTE:
        return False
    kandidaten: set[str] = set()
    for tekst in mutatie_teksten:
        kandidaten |= _samengestelde_tokens(_tokens(tekst))
    if ref in kandidaten:
        return True
    kern = _cijferkern(ref)
    if kern is None:
        return False
    return any(_cijferkern(kandidaat) == kern for kandidaat in kandidaten)


def referentie_is_kort(referentie: str | None) -> bool:
    """4–5 tekens na normalisatie: telt alleen samen met een exact bedrag."""
    return len(_genormaliseerd(referentie)) < _KORTE_REFERENTIE_GRENS


def referentie_komt_voor(referentie: str | None, *mutatie_teksten: str | None) -> bool:
    """LEGACY substring-match (min 4) — sinds blok 2 (08-09) NIET meer door de matchmotor gebruikt
    (zie `referentie_als_token`). Blijft bestaan voor `app/bank/betaald_signaal.py`; open punt B2:
    ook dat signaal naar de token-vorm brengen."""
    ref = _genormaliseerd(referentie)
    if len(ref) < _MIN_REFERENTIE_LENGTE:
        return False
    return any(ref in _genormaliseerd(tekst) for tekst in mutatie_teksten if tekst)


def tegenpartij_sleutel(naam: str | None) -> str | None:
    """Zelfde normalisatie als het boekingsgeheugen (token-set) — de sleutel waarop vaste
    regels en de 3×-teller matchen."""
    return normaliseer_regel_sleutel(naam)


# --- naam + IBAN ---------------------------------------------------------------------------------------

# Rechtsvormen, aanspreekvormen, stopwoorden en te generieke bedrijfsnaam-woorden: tellen nooit als
# significant token (brief 2a-iii). "Tupker Beheer" en "Kempen Beheer" matchen dus niet op "beheer".
_NAAM_STOPTOKENS = frozenset(
    {
        "bv", "nv", "vof", "cv", "b", "v", "n", "o", "f", "c", "ba", "bvba", "gmbh", "ltd", "sa", "sarl",
        "de", "het", "een", "en", "van", "der", "den", "des", "the", "and", "of",
        "hr", "dhr", "mw", "mevr", "mr", "mrs", "fam",
        "holding", "beheer", "groep", "group", "nederland", "netherlands", "international", "services",
        "service", "bedrijf", "company", "onderneming", "administratiekantoor", "accountants",
    }
)
_MIN_NAAM_TOKEN_LENGTE = 3
_NAAM_TOKEN_SPLITSER = re.compile(r"[^0-9a-zà-ÿ]+")


def naam_tokens(naam: str | None) -> set[str]:
    """Significante naamtokens: lowercase, gesplitst op niet-alfanumeriek (punten, koppeltekens,
    "B.V." → "b","v" vallen weg), zonder rechtsvorm/stopwoorden, minimaal 3 tekens."""
    if not naam:
        return set()
    return {
        token
        for token in _NAAM_TOKEN_SPLITSER.split(naam.lower())
        if len(token) >= _MIN_NAAM_TOKEN_LENGTE and token not in _NAAM_STOPTOKENS
    }


def naam_komt_overeen(naam_a: str | None, naam_b: str | None) -> bool:
    """Token-overlap van minstens één significant token."""
    return bool(naam_tokens(naam_a) & naam_tokens(naam_b))


def normaliseer_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    genormaliseerd = re.sub(r"[^0-9A-Z]+", "", iban.upper())
    return genormaliseerd or None


@dataclass(frozen=True)
class IbanRelatie:
    """Geleerde koppeling tegenrekening-IBAN ↔ RLZ-entity (bank_relatie_iban, migratie 0127):
    gevoed door élke geslaagde, geverifieerde aflettering (afletteren.py)."""

    iban: str
    entity_guid: uuid.UUID


# --- teken ---------------------------------------------------------------------------------------------

# RLZ-conventie (api-verkenning H1 "open PaymentItem −100" op een inkoopfactuur; replay 09-08 "post van
# −105,42"): een INKOOP-post is negatief, een VERKOOP-post positief; creditnota's omgekeerd. Het teken
# klopt dus precies dan als mutatie en post hetzelfde teken dragen — toetsbaar zodra de documentsoort
# bekend is (DocumentType 1/10 uit de cache). Onbekende soort = niet toetsbaar → hooguit oranje.
_TEKEN_TOETSBARE_SOORTEN = frozenset({"Inkoopfactuur", "Verkoopfactuur"})

TEKEN_OK = "ok"
TEKEN_MISMATCH = "mismatch"
TEKEN_ONBEKEND = "onbekend"


class VoorstelSoort(enum.StrEnum):
    EXACTE_MATCH = "exacte_match"
    DEEL_MATCH = "deel_match"
    VASTE_REGEL = "vaste_regel"
    HISTORIE_REGEL = "historie_regel"
    RLZ_VOORSTEL = "rlz_voorstel"
    HANDMATIG = "handmatig"


@dataclass(frozen=True)
class MutatieGegevens:
    id: uuid.UUID
    bedrag: Decimal | None
    open_bedrag: Decimal | None
    tegenpartij_naam: str | None
    omschrijving: str | None
    tegenrekening_iban: str | None
    rlz_voorstel_item_id: uuid.UUID | None

    @property
    def te_verwerken_bedrag(self) -> Decimal | None:
        """Hét bedrag waarop voorstellen én boeken werken (blok 3 nachtrun 10/11-09, bug Zilver Beheer): het OPEN bedrag
        van de mutatie (RLZ `OpenAmount`), terugval het totaal als de sync het open bedrag (nog) niet kent."""
        return open_bedrag_van(self.bedrag, self.open_bedrag)


def open_bedrag_van(bedrag: Decimal | None, open_bedrag: Decimal | None) -> Decimal | None:
    """Eén bron voor 'wat staat er nog te verwerken': `open_bedrag` als de sync 'm kent, anders `bedrag`. Een
    mutatie die in RLZ al deels is afgeletterd (Zilver Beheer 01-07: +5.023,09, gekoppeld 2.512,04, open 2.511,05)
    wordt zo nooit meer op het totaal getoetst of geboekt."""
    return open_bedrag if open_bedrag is not None else bedrag


def is_deels_afgeletterd(bedrag: Decimal | None, open_bedrag: Decimal | None) -> bool:
    """DTO-contract N3a↔N3b: open bekend, ≠ totaal en ≠ 0 — de mutatie is in RLZ al deels gekoppeld."""
    return bedrag is not None and open_bedrag is not None and open_bedrag != bedrag and open_bedrag != 0


@dataclass(frozen=True)
class OpenPost:
    id: uuid.UUID
    bedrag: Decimal | None
    referentie: str | None
    referentie2: str | None
    rlz_document_id: uuid.UUID | None
    # Doel-post-specs (blok E5, 01/02-09) — sinds blok 2 (08-09) óók motor-invoer: `tegenpartij_naam`
    # (naam-toets) en `documentsoort` (teken-toets). `entity_guid` voedt de IBAN-toets.
    tegenpartij_naam: str | None = None
    documentsoort: str | None = None
    boekstuknummer: str | None = None
    factuurdatum: date | None = None
    entity_guid: uuid.UUID | None = None


@dataclass(frozen=True)
class VasteRegelGegevens:
    id: uuid.UUID
    tegenpartij_sleutel: str
    tegenrekening_iban: str | None
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    omschrijving: str | None


@dataclass(frozen=True)
class Voorstel:
    """Eén voorstel per mutatie, mét herkomst (mockup: 'Elke regel toont wélke bron het
    voorstel deed'). `kleur` volgt het vaste patroon: groen = deterministisch zeker, oranje =
    markeren/bevestigen, nooit stil overnemen. `bron` zegt sinds blok 2 (08-09) EXACT wat matchte
    ("IBAN + nummer + bedrag", "nummer + bedrag, naam onbekend") — nooit meer "naam + referentie"
    als de naam niet getoetst is."""

    soort: VoorstelSoort
    kleur: str  # "groen" | "oranje"
    bron: str  # herkomst-chip-tekst
    reden: str
    payment_item_id: uuid.UUID | None = None
    rlz_document_id: uuid.UUID | None = None
    regel_id: uuid.UUID | None = None
    # Stap 3b (blok B bundel 10-09): het grootboek-/btw-doel uit de historie + de k-van-n-telling. Alleen
    # gevuld bij soort HISTORIE_REGEL; kleur "groen" = 100 % = automatisch kandidaat.
    ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    historie_k: int | None = None
    historie_n: int | None = None


def teken_toets(mutatie: MutatieGegevens, post: OpenPost) -> str:
    """TEKEN_OK / TEKEN_MISMATCH / TEKEN_ONBEKEND (documentsoort of bedrag onbekend). Toetst het OPEN bedrag."""
    bedrag = mutatie.te_verwerken_bedrag
    if bedrag is None or post.bedrag is None or bedrag == 0 or post.bedrag == 0:
        return TEKEN_ONBEKEND
    if post.documentsoort not in _TEKEN_TOETSBARE_SOORTEN:
        return TEKEN_ONBEKEND
    return TEKEN_OK if (bedrag > 0) == (post.bedrag > 0) else TEKEN_MISMATCH


def _naam_of_iban(
    mutatie: MutatieGegevens,
    post: OpenPost,
    *,
    vaste_regels: list[VasteRegelGegevens],
    iban_relaties: list[IbanRelatie],
) -> str | None:
    """"IBAN" (geleerde IBAN↔entity-koppeling, of een vaste regel op dit IBAN wiens tegenpartij-
    sleutel de postnaam dekt), "naam" (token-overlap) of None."""
    iban = normaliseer_iban(mutatie.tegenrekening_iban)
    if iban is not None:
        if post.entity_guid is not None and any(
            relatie.entity_guid == post.entity_guid and normaliseer_iban(relatie.iban) == iban
            for relatie in iban_relaties
        ):
            return "IBAN"
        if post.tegenpartij_naam and any(
            regel.tegenrekening_iban
            and normaliseer_iban(regel.tegenrekening_iban) == iban
            and naam_komt_overeen(regel.tegenpartij_sleutel, post.tegenpartij_naam)
            for regel in vaste_regels
        ):
            return "IBAN"
    if naam_komt_overeen(mutatie.tegenpartij_naam, post.tegenpartij_naam):
        return "naam"
    return None


def _bedrag_exact(mutatie: MutatieGegevens, post: OpenPost) -> bool:
    """Cent-exact tegen het OPEN bedrag van de mutatie (blok 3 nachtrun 10/11-09): een deels afgeletterde
    mutatie matcht op wat er nog open staat, nooit op het totaal."""
    bedrag = mutatie.te_verwerken_bedrag
    return bedrag is not None and post.bedrag is not None and abs(post.bedrag) == abs(bedrag)


@dataclass(frozen=True)
class PostScore:
    """Deterministische score van één open post tegen één mutatie (brief 2a): teken, naam/IBAN,
    nummer (heel token), bedrag (cent-exact). Puur — geen I/O."""

    post: OpenPost
    teken: str
    naam_of_iban: str | None
    nummer: bool
    bedrag: bool

    @property
    def aantal(self) -> int:
        return int(self.naam_of_iban is not None) + int(self.nummer) + int(self.bedrag)

    @property
    def groen(self) -> bool:
        """Auto-afletteren-kandidaat: teken klopt én naam/IBAN én nummer én bedrag."""
        return self.teken == TEKEN_OK and self.aantal == 3

    @property
    def oranje(self) -> bool:
        """Bevestigen: geen teken-mismatch en minstens twee van {naam/IBAN, nummer, bedrag}."""
        return not self.groen and self.teken != TEKEN_MISMATCH and self.aantal >= 2

    def label(self) -> str:
        aanwezig = [
            deel
            for deel, ok in (
                (self.naam_of_iban or "naam", self.naam_of_iban is not None),
                ("nummer", self.nummer),
                ("bedrag", self.bedrag),
            )
            if ok
        ]
        tekst = " + ".join(aanwezig)
        ontbrekend = []
        if self.naam_of_iban is None:
            ontbrekend.append("naam onbekend")
        if not self.nummer:
            ontbrekend.append("nummer niet gevonden")
        if not self.bedrag:
            ontbrekend.append("bedrag wijkt af")
        if ontbrekend:
            tekst += ", " + ", ".join(ontbrekend)
        if self.teken == TEKEN_ONBEKEND:
            tekst += " — documentsoort onbekend, teken niet getoetst"
        return tekst


def score_post(
    mutatie: MutatieGegevens,
    post: OpenPost,
    *,
    vaste_regels: list[VasteRegelGegevens],
    iban_relaties: list[IbanRelatie],
) -> PostScore:
    bedrag = _bedrag_exact(mutatie, post)
    nummer = referentie_als_token(post.referentie, mutatie.tegenpartij_naam, mutatie.omschrijving)
    if nummer and referentie_is_kort(post.referentie) and not bedrag:
        nummer = False  # korte referentie telt alleen samen met een exact bedrag
    return PostScore(
        post=post,
        teken=teken_toets(mutatie, post),
        naam_of_iban=_naam_of_iban(mutatie, post, vaste_regels=vaste_regels, iban_relaties=iban_relaties),
        nummer=nummer,
        bedrag=bedrag,
    )


def _vaste_regel_voor(mutatie: MutatieGegevens, regels: list[VasteRegelGegevens]) -> VasteRegelGegevens | None:
    """IBAN-match (exact) wint van naam-match; beide deterministisch. Meerdere naam-matches kan
    niet voorkomen (unique index op actieve sleutel per administratie)."""
    if mutatie.tegenrekening_iban:
        for regel in regels:
            if regel.tegenrekening_iban and regel.tegenrekening_iban == mutatie.tegenrekening_iban:
                return regel
    sleutel = tegenpartij_sleutel(mutatie.tegenpartij_naam)
    if sleutel is None:
        return None
    for regel in regels:
        if regel.tegenpartij_sleutel == sleutel:
            return regel
    return None


def _meerdere_kandidaten(scores: list[PostScore], kleur: str) -> Voorstel:
    refs = ", ".join(repr(s.post.referentie) for s in scores[:5])
    return Voorstel(
        soort=VoorstelSoort.HANDMATIG,
        kleur="oranje",
        bron="handmatig — meerdere kandidaten",
        reden=f"{len(scores)} open posten scoren gelijkwaardig ({kleur}: {refs}); geen eenduidige keuze",
    )


def bepaal_voorstel(
    mutatie: MutatieGegevens,
    *,
    open_posten: list[OpenPost],
    vaste_regels: list[VasteRegelGegevens],
    iban_relaties: list[IbanRelatie] | None = None,
    historie: list | None = None,
    vandaag: date | None = None,
    rekening_label=None,
) -> Voorstel:
    """Het ene voorstel voor deze mutatie, in de vaste volgorde 1–5. Stap 1/2 sinds blok 2 (08-09)
    op de score per open post: GROEN = teken + naam/IBAN + nummer + bedrag (auto-afletteren-
    kandidaat), ORANJE = geen teken-mismatch + twee van {naam/IBAN, nummer, bedrag} (bevestigen),
    anders door naar vaste regel / RLZ-voorstel / handmatig. Bij meerdere gelijkwaardige
    kandidaten binnen een kleur wordt er nooit blind één gekozen (handmatig mét reden).

    `historie` (blok B bundel 10-09, optioneel — bestaande aanroepers ongewijzigd): lijst
    `historie_regel.HistorieBoeking`; stap 3b ná de vaste regel en vóór het RLZ-voorstel.
    `rekening_label(ledger_id, taxrate_id) -> str` levert de leesbare rekening voor het bron-label
    (default: de eerste 8 tekens van het ledger-id — de servicelaag geeft code + naam mee)."""
    relaties = iban_relaties or []
    scores = [score_post(mutatie, post, vaste_regels=vaste_regels, iban_relaties=relaties) for post in open_posten]

    groen = [s for s in scores if s.groen]
    if len(groen) == 1:
        s = groen[0]
        return Voorstel(
            soort=VoorstelSoort.EXACTE_MATCH,
            kleur="groen",
            bron=s.label(),
            reden=(
                f"Open post {s.post.referentie!r}: teken klopt, {s.naam_of_iban} matcht, factuurnummer als heel "
                "token in de mutatie én bedrag cent-exact gelijk"
            ),
            payment_item_id=s.post.id,
            rlz_document_id=s.post.rlz_document_id,
        )
    if len(groen) > 1:
        return _meerdere_kandidaten(groen, "groen")

    oranje = [s for s in scores if s.oranje]
    if len(oranje) == 1:
        s = oranje[0]
        return Voorstel(
            soort=VoorstelSoort.DEEL_MATCH,
            kleur="oranje",
            bron=s.label(),
            reden=f"Open post {s.post.referentie!r} matcht op {s.label()} — bevestigen",
            payment_item_id=s.post.id,
            rlz_document_id=s.post.rlz_document_id,
        )
    if len(oranje) > 1:
        return _meerdere_kandidaten(oranje, "oranje")

    # Stap 3: vaste regel uit het geheugen.
    regel = _vaste_regel_voor(mutatie, vaste_regels)
    if regel is not None:
        return Voorstel(
            soort=VoorstelSoort.VASTE_REGEL,
            kleur="groen",
            bron="vaste regel",
            reden="Tegenpartij matcht een door een mens bevestigde vaste regel",
            regel_id=regel.id,
        )

    # Stap 3b: historie-regel (IBAN + omschrijvingskern, bedrag vrij) — lokale import: historie_regel
    # bouwt op de types van deze module (geen kring op module-niveau).
    if historie:
        from app.bank import historie_regel

        uitkomst = historie_regel.bepaal_historie_voorstel(
            mutatie,
            historie,
            open_posten=open_posten,
            iban_relaties=relaties,
            vandaag=vandaag or vandaag_nl(),
        )
        if uitkomst.voorstel is not None:
            h = uitkomst.voorstel
            label = (
                rekening_label(h.ledger_id, h.taxrate_id) if rekening_label is not None else str(h.ledger_id)[:8]
            )
            return Voorstel(
                soort=VoorstelSoort.HISTORIE_REGEL,
                kleur=h.kleur,
                bron=h.label(label),
                reden=f"Historie-regel op {h.sleutel.label()}: {uitkomst.reden}",
                ledger_id=h.ledger_id,
                taxrate_id=h.taxrate_id,
                historie_k=h.k,
                historie_n=h.n,
            )

    # Stap 4: RLZ's eigen voorstel (MatchedPaymentItem — alleen exacte bedrag-match, schrijf-PoC).
    if mutatie.rlz_voorstel_item_id is not None:
        rlz_post = next((p for p in open_posten if p.id == mutatie.rlz_voorstel_item_id), None)
        return Voorstel(
            soort=VoorstelSoort.RLZ_VOORSTEL,
            kleur="oranje",
            bron="voorstel Reeleezee — bedrag-match",
            reden="Reeleezee stelt deze open post zelf voor (MatchedPaymentItem, exacte bedrag-match)",
            payment_item_id=mutatie.rlz_voorstel_item_id,
            rlz_document_id=rlz_post.rlz_document_id if rlz_post else None,
        )

    # Stap 5: handmatig.
    return Voorstel(
        soort=VoorstelSoort.HANDMATIG,
        kleur="oranje",
        bron="handmatig",
        reden="Geen regel en geen open-post-match",
    )


# --- 3×-regelvoorstel ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegelVoorstel:
    """Voorstel om een vaste regel aan te maken (mockup: 'Na 3× dezelfde handmatige boeking
    stelt de app een vaste regel voor') — de app stelt voor, een mens bevestigt."""

    tegenpartij_sleutel: str
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    aantal_boekingen: int


REGELVOORSTEL_DREMPEL = 3


def stel_regel_voor(
    *,
    tegenpartij_naam: str | None,
    historie: list[tuple[str, uuid.UUID, uuid.UUID | None]],
    bestaande_sleutels: set[str],
) -> RegelVoorstel | None:
    """`historie` = (tegenpartij_sleutel, ledger_id, taxrate_id) per eerdere handmatige boeking.
    Pas een voorstel bij >= 3 boekingen van deze tegenpartij op hetzélfde grootboek (én zelfde
    btw-code) en alleen als er nog geen actieve regel voor deze sleutel bestaat."""
    sleutel = tegenpartij_sleutel(tegenpartij_naam)
    if sleutel is None or sleutel in bestaande_sleutels:
        return None
    tellingen: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
    for hist_sleutel, ledger_id, taxrate_id in historie:
        if hist_sleutel == sleutel:
            tellingen[(ledger_id, taxrate_id)] = tellingen.get((ledger_id, taxrate_id), 0) + 1
    if not tellingen:
        return None
    (ledger_id, taxrate_id), aantal = max(tellingen.items(), key=lambda kv: (kv[1], str(kv[0][0])))
    if aantal < REGELVOORSTEL_DREMPEL:
        return None
    return RegelVoorstel(
        tegenpartij_sleutel=sleutel, ledger_id=ledger_id, taxrate_id=taxrate_id, aantal_boekingen=aantal
    )


# --- btw-splitsing (code rekent, nooit AI) -------------------------------------------------------


def splits_incl_bedrag(bedrag: Decimal, btw_percentage: Decimal | None) -> tuple[Decimal, Decimal]:
    """Splitst een inclusief mutatiebedrag in (netto, btw) bij een gegeven btw-fractie (0.21
    voor 21% — de vorm waarin TaxRateCache.percentage staat). Afronding half-up op de netto;
    btw = bedrag − netto zodat de som ALTIJD exact het mutatiebedrag is (geen centverlies).
    Werkt tekenvast voor negatieve (afschrijving) én positieve bedragen.

    Eenheids-guard (geldlogica-verificatie 2026-08-10, app/sync/btw.py): de fractie is de
    canonieke eenheid — een waarde ≥ 1 kan alleen een per ongeluk doorgegeven UBL-percentage
    (21.00) zijn en zou het geld stil verminken (121 / 22 i.p.v. 121 / 1,21). Hard falen."""
    if btw_percentage is not None and btw_percentage >= 1:
        raise ValueError(
            f"btw_percentage moet de fractie zijn (0.21 voor 21%), kreeg {btw_percentage} — "
            "vermoedelijk een UBL-percentage; normaliseer via app.sync.btw.ubl_percent_naar_fractie"
        )
    if not btw_percentage:
        return bedrag, Decimal("0.00")
    netto = (bedrag / (1 + btw_percentage)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return netto, bedrag - netto
