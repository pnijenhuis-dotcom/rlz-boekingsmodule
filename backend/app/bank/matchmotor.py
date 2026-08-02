"""Deterministische matchmotor voor bankmutaties (code voor cijfers — geen AI, geen gok).

Voorstel-volgorde (goedgekeurd ontwerp, mockup #bankdetail + CLAUDE.md "Bank", stap 4 hersteld
na de schrijf-PoC):
1. exacte match (factuurreferentie gevonden in de mutatietekst én exact bedrag) → groen;
2. gedeeltelijke match (referentie zónder exact bedrag — deelbetaling/G-rekening-split — of
   exact bedrag zonder referentie) → oranje, bevestigen;
3. vaste regel uit het geheugen (tegenpartij → grootboek/btw) → direct-op-grootboek-voorstel;
4. RLZ's eigen voorstel (auto-gevuld MatchedPaymentItem bij exacte bedrag-match) — mét bron;
5. handmatig.

Stap 1/2/4 zijn afletter-voorstellen tegen een open post: die kunnen via de publieke API niet
geschreven worden (15/16/34/218 dicht — fallback-PoC), dus ze monden uit in het assist-model
(app/bank/afletteren.py). Stap 3 is wél volautomatisch bouwbaar (direct-op-grootboek).

Alles hier is puur en zonder I/O: de service-laag (voorstellen.py) voert data aan, deze module
beslist — en is daarmee 1-op-1 unit-testbaar (tests verplicht op geldlogica)."""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.geheugen.normalisatie import normaliseer_regel_sleutel

# Een referentie korter dan dit aantal tekens (na normalisatie) is te generiek om op te matchen
# ("1", "42" — dat soort tokens staat in elke omschrijving); nooit een voorstel op baseren.
_MIN_REFERENTIE_LENGTE = 4

_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")


def _genormaliseerd(tekst: str | None) -> str:
    """Lowercase + alles behalve letters/cijfers eruit — "2026-0642" en "2026 0642" worden
    beide "20260642", zodat opmaakverschillen tussen bankomschrijving en factuurreferentie
    geen match breken."""
    if not tekst:
        return ""
    return _NIET_ALFANUMERIEK.sub("", tekst.lower())


def referentie_komt_voor(referentie: str | None, *mutatie_teksten: str | None) -> bool:
    """Deterministische referentie-match: de genormaliseerde referentie moet als substring in
    één van de genormaliseerde mutatieteksten staan (naam + omschrijving)."""
    ref = _genormaliseerd(referentie)
    if len(ref) < _MIN_REFERENTIE_LENGTE:
        return False
    return any(ref in _genormaliseerd(tekst) for tekst in mutatie_teksten if tekst)


def tegenpartij_sleutel(naam: str | None) -> str | None:
    """Zelfde normalisatie als het boekingsgeheugen (token-set) — de sleutel waarop vaste
    regels en de 3×-teller matchen."""
    return normaliseer_regel_sleutel(naam)


class VoorstelSoort(enum.StrEnum):
    EXACTE_MATCH = "exacte_match"
    DEEL_MATCH = "deel_match"
    VASTE_REGEL = "vaste_regel"
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


@dataclass(frozen=True)
class OpenPost:
    id: uuid.UUID
    bedrag: Decimal | None
    referentie: str | None
    referentie2: str | None
    rlz_document_id: uuid.UUID | None


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
    markeren/bevestigen, nooit stil overnemen."""

    soort: VoorstelSoort
    kleur: str  # "groen" | "oranje"
    bron: str  # herkomst-chip-tekst
    reden: str
    payment_item_id: uuid.UUID | None = None
    rlz_document_id: uuid.UUID | None = None
    regel_id: uuid.UUID | None = None


def _referentie_kandidaten(mutatie: MutatieGegevens, open_posten: list[OpenPost]) -> list[OpenPost]:
    return [
        post
        for post in open_posten
        if referentie_komt_voor(post.referentie, mutatie.tegenpartij_naam, mutatie.omschrijving)
    ]


def _bedrag_kandidaten(mutatie: MutatieGegevens, open_posten: list[OpenPost]) -> list[OpenPost]:
    if mutatie.bedrag is None:
        return []
    return [post for post in open_posten if post.bedrag is not None and abs(post.bedrag) == abs(mutatie.bedrag)]


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


def bepaal_voorstel(
    mutatie: MutatieGegevens,
    *,
    open_posten: list[OpenPost],
    vaste_regels: list[VasteRegelGegevens],
) -> Voorstel:
    """Het ene voorstel voor deze mutatie, in de vaste volgorde 1–5. Bij meerdere gelijkwaardige
    kandidaten binnen een stap wordt er nooit blind één gekozen: dan zakt het voorstel naar
    oranje mét de reden, of (zonder eenduidige kandidaat) door naar de volgende stap."""
    # Stap 1/2: match tegen open posten (referentie en/of bedrag).
    ref_kandidaten = _referentie_kandidaten(mutatie, open_posten)
    if len(ref_kandidaten) == 1:
        post = ref_kandidaten[0]
        bedrag_exact = (
            mutatie.bedrag is not None and post.bedrag is not None and abs(post.bedrag) == abs(mutatie.bedrag)
        )
        if bedrag_exact:
            return Voorstel(
                soort=VoorstelSoort.EXACTE_MATCH,
                kleur="groen",
                bron="exacte match — referentie + bedrag",
                reden=f"Referentie {post.referentie!r} gevonden in de mutatie én bedrag exact gelijk",
                payment_item_id=post.id,
                rlz_document_id=post.rlz_document_id,
            )
        return Voorstel(
            soort=VoorstelSoort.DEEL_MATCH,
            kleur="oranje",
            bron="match op referentie, bedrag wijkt af — bevestigen",
            reden=(
                f"Referentie {post.referentie!r} gevonden, maar het bedrag verschilt "
                "(deelbetaling of G-rekening-split?)"
            ),
            payment_item_id=post.id,
            rlz_document_id=post.rlz_document_id,
        )
    if len(ref_kandidaten) > 1:
        # Meerdere posten met een matchende referentie: alleen een exacte bedrag-match binnen
        # die set maakt het nog eenduidig; anders is dit een handmatige beoordeling.
        exacte = _bedrag_kandidaten(mutatie, ref_kandidaten)
        if len(exacte) == 1:
            post = exacte[0]
            return Voorstel(
                soort=VoorstelSoort.EXACTE_MATCH,
                kleur="groen",
                bron="exacte match — referentie + bedrag",
                reden=f"Meerdere referentie-matches; alleen {post.referentie!r} matcht ook op bedrag",
                payment_item_id=post.id,
                rlz_document_id=post.rlz_document_id,
            )
        return Voorstel(
            soort=VoorstelSoort.HANDMATIG,
            kleur="oranje",
            bron="handmatig — meerdere kandidaten",
            reden=f"{len(ref_kandidaten)} open posten matchen op referentie; geen eenduidige keuze",
        )

    bedrag_kandidaten = _bedrag_kandidaten(mutatie, open_posten)
    if len(bedrag_kandidaten) == 1:
        post = bedrag_kandidaten[0]
        return Voorstel(
            soort=VoorstelSoort.DEEL_MATCH,
            kleur="oranje",
            bron="match op bedrag, geen referentie — bevestigen",
            reden=f"Bedrag matcht exact met open post {post.referentie!r}, maar de referentie is niet gevonden",
            payment_item_id=post.id,
            rlz_document_id=post.rlz_document_id,
        )

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
    Werkt tekenvast voor negatieve (afschrijving) én positieve bedragen."""
    if not btw_percentage:
        return bedrag, Decimal("0.00")
    netto = (bedrag / (1 + btw_percentage)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return netto, bedrag - netto
