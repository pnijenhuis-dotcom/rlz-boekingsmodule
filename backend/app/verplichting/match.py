"""Deterministische factuur↔verplichting-match (mockup `offerte-matching.html` ②/③, besluiten
Peter 04-09). PUUR: geen DB, geen AI, geen RLZ-/Odoo-calls — `match_pipeline.py` is de glue.

Match-sleutel (②): crediteur-identiteit (btw-nummer-groep, anders de vendor zelf) + project; het
offertenummer op de factuur VERSTERKT de match; meerdere lopende verplichtingen bij dezelfde
combinatie = de mens koppelt éénmalig ("Koppel offerte…"), die keuze wordt daarna onthouden.

Cumulatief (③, besluit Peter): verbruik = som van de gematchte facturen; `binnen` iff het verbruik
ná deze factuur ≤ het goedgekeurde offertebedrag — GEEN tolerantiemarge, de grens ís het bedrag.
Buiten = oranje vlag mét het bedrag erover (⑤), nooit een blokkade.

Verbruik-definitie (besluit in CONTRACT_B, beslispunt voor Peter): `verbruik_voor` telt UITSLUITEND
het verrekende (= geboekte) verbruik. Nog open facturen op dezelfde verplichting tellen niet mee —
anders zou een factuur die nog in de werkvoorraad ligt een tweede factuur ten onrechte "buiten"
maken en zou intrekken/afwijzen de stand van andere documenten verschuiven.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

#: Uitkomsten (gelijk aan de CHECK op verplichting_match.uitkomst).
BINNEN = "binnen"
BUITEN = "buiten"
GEEN_MATCH = "geen_match"
MEERDERE_KANDIDATEN = "meerdere_kandidaten"
NIET_TOETSBAAR = "niet_toetsbaar"
GEEN_VERPLICHTING = "geen_verplichting"

UITKOMSTEN = (BINNEN, BUITEN, GEEN_MATCH, MEERDERE_KANDIDATEN, NIET_TOETSBAAR, GEEN_VERPLICHTING)

#: Uitkomsten die de werkvoorraad-teller "buiten offerte" voeden (⑤) — buiten óf géén match terwijl
#: er wél lopende verplichtingen van deze crediteur zijn.
TELT_ALS_BUITEN_OFFERTE = (BUITEN, GEEN_MATCH)

#: Handelingsperspectief bij "buiten" (⑤/B6): meerwerk rekt een offerte niet op.
MEERWERK_HANDELING = (
    "Meerwerk rekt een offerte niet op: laat aanvullend werk als aparte verplichting accorderen."
)

_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")


def normaliseer_nummer(nummer: str | None) -> str | None:
    """Offertenummer-vorm voor de tekstvergelijking: hoofdletter-/witruimte-/leesteken-ongevoelig.
    "26140-OFF-01" → "26140off01". Te kort (< 4 tekens) = onbruikbaar als anker: zulke nummers
    komen te makkelijk toevallig in een factuurtekst voor."""
    if not nummer:
        return None
    genormaliseerd = _NIET_ALFANUMERIEK.sub("", nummer.strip().lower())
    return genormaliseerd if len(genormaliseerd) >= 4 else None


def _normaliseer_tekst(tekst: str | None) -> str:
    return _NIET_ALFANUMERIEK.sub("", (tekst or "").lower())


@dataclass(frozen=True)
class Kandidaat:
    """Een LOPENDE verplichting (document geaccordeerd, niet vervallen) van dezelfde crediteur —
    de pipeline levert alleen die aan; de geldigheidstoets t.o.v. de factuurdatum zit hier."""

    document_id: uuid.UUID
    project_id: uuid.UUID | None = None
    offertenummer: str | None = None
    soort_label: str | None = None
    goedgekeurd_bedrag_excl: Decimal | None = None
    verbruikt_bedrag_excl: Decimal = Decimal(0)
    geldig_tot: date | None = None


@dataclass(frozen=True)
class FactuurFeiten:
    """De door CODE vastgestelde feiten van de inkoopfactuur (nooit AI-uitkomsten)."""

    document_id: uuid.UUID
    #: Crediteur-identiteit ("btw:NL…" / "vendor:<uuid>") — None = geen crediteur → niet toetsbaar.
    vendor_sleutel: str | None = None
    #: De ENE distinct project_id over de boekvoorstel-regels; 0 of > 1 distinct = None.
    project_id: uuid.UUID | None = None
    #: Σ netto_bedrag van het (opgeslagen óf prefill) boekvoorstel, anders veldvoorstel-totaal_excl.
    bedrag_excl: Decimal | None = None
    factuurdatum: date | None = None
    #: Referentie, betalingskenmerk, regel-omschrijvingen, veldvoorstel-teksten — voor de
    #: offertenummer-versterking (②).
    teksten: tuple[str, ...] = ()
    #: Al verrekend bedrag van DEZE factuur op de gematchte verplichting (herberekening ná boeken):
    #: het zit dan al in `Kandidaat.verbruikt_bedrag_excl` en mag niet dubbel tellen.
    eigen_verrekend: Decimal | None = None


@dataclass(frozen=True)
class MatchUitkomst:
    uitkomst: str
    verplichting_document_id: uuid.UUID | None = None
    bedrag_excl: Decimal | None = None
    verbruik_voor: Decimal | None = None
    verbruik_na: Decimal | None = None
    overschrijding_excl: Decimal | None = None
    melding: str = ""
    #: Alle lopende + geldige kandidaten (de "Koppel offerte…"-dialoog toont ze).
    kandidaat_ids: tuple[uuid.UUID, ...] = ()
    #: Waarom deze kandidaat: handmatig | offertenummer | project | onthouden | enige.
    grond: str | None = None
    details: dict = field(default_factory=dict)


def _bedrag(waarde: Decimal | None) -> str:
    return f"€ {waarde:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".") if waarde is not None else "—"


def percentage(verbruik: Decimal | None, totaal: Decimal | None) -> int | None:
    """Verbruikspercentage voor de balk — integer, nooit negatief; boven 100 blijft > 100 (rood)."""
    if verbruik is None or totaal is None or totaal == 0:
        return None
    ruw = (verbruik / totaal) * Decimal(100)
    return max(int(ruw.quantize(Decimal("1"))), 0)


def _geldig(kandidaat: Kandidaat, factuurdatum: date | None) -> bool:
    """Verstreken geldigheid = géén kandidaat. Zonder factuurdatum toetsen we niet op geldigheid
    (fail-open op dit punt: de datum is dan onbekend, niet verstreken)."""
    if kandidaat.geldig_tot is None or factuurdatum is None:
        return True
    return kandidaat.geldig_tot >= factuurdatum


def bepaal_match(
    feiten: FactuurFeiten,
    kandidaten: list[Kandidaat],
    *,
    handmatig_gekoppeld_id: uuid.UUID | None = None,
    onthouden_id: uuid.UUID | None = None,
) -> MatchUitkomst:
    """De volledige beslisboom. `handmatig_gekoppeld_id` = de koppeling op DEZE match-rij (wint
    altijd zolang die verplichting lopend + geldig is); `onthouden_id` = de laatste HANDMATIGE
    koppeling voor dezelfde crediteur + project (②: "daarna onthouden")."""
    if feiten.vendor_sleutel is None:
        return MatchUitkomst(
            uitkomst=NIET_TOETSBAAR,
            melding="Geen crediteur op het boekvoorstel — de offerte-toets kan (nog) niet draaien.",
        )
    if feiten.bedrag_excl is None:
        return MatchUitkomst(
            uitkomst=NIET_TOETSBAAR,
            melding="Geen bedrag exclusief btw bekend — de offerte-toets kan (nog) niet draaien.",
        )

    geldige = [k for k in kandidaten if _geldig(k, feiten.factuurdatum)]
    kandidaat_ids = tuple(k.document_id for k in geldige)
    if not geldige:
        verstreken = len(kandidaten) - len(geldige)
        if verstreken:
            return MatchUitkomst(
                uitkomst=GEEN_MATCH,
                bedrag_excl=feiten.bedrag_excl,
                melding=(
                    f"{verstreken} goedgekeurde verplichting(en) van deze leverancier zijn verstreken op de "
                    "factuurdatum — geen geldige offerte om tegen te toetsen."
                ),
                details={"verstreken_kandidaten": verstreken},
            )
        return MatchUitkomst(
            uitkomst=GEEN_VERPLICHTING,
            bedrag_excl=feiten.bedrag_excl,
            melding="Geen goedgekeurde verplichting van deze leverancier — niets te toetsen.",
        )

    per_id = {k.document_id: k for k in geldige}

    # (a) handmatige koppeling op dit document wint altijd.
    if handmatig_gekoppeld_id is not None and handmatig_gekoppeld_id in per_id:
        return _beoordeel(
            feiten, per_id[handmatig_gekoppeld_id], kandidaat_ids=kandidaat_ids, grond="handmatig"
        )

    # (b) offertenummer van een kandidaat komt letterlijk in de factuurtekst voor.
    tekst = "".join(_normaliseer_tekst(t) for t in feiten.teksten)
    op_nummer = [
        k for k in geldige if (nr := normaliseer_nummer(k.offertenummer)) is not None and nr in tekst
    ]
    if len(op_nummer) == 1:
        return _beoordeel(feiten, op_nummer[0], kandidaat_ids=kandidaat_ids, grond="offertenummer")

    # (c) project-sleutel.
    if feiten.project_id is not None:
        op_project = [k for k in geldige if k.project_id == feiten.project_id]
        if len(op_project) == 1:
            return _beoordeel(feiten, op_project[0], kandidaat_ids=kandidaat_ids, grond="project")
        if len(op_project) > 1:
            if onthouden_id is not None and any(k.document_id == onthouden_id for k in op_project):
                return _beoordeel(feiten, per_id[onthouden_id], kandidaat_ids=kandidaat_ids, grond="onthouden")
            return MatchUitkomst(
                uitkomst=MEERDERE_KANDIDATEN,
                bedrag_excl=feiten.bedrag_excl,
                melding=(
                    f"{len(op_project)} goedgekeurde verplichtingen van deze leverancier op dit project — "
                    "koppel de juiste offerte (die keuze wordt daarna onthouden)."
                ),
                kandidaat_ids=kandidaat_ids,
            )
        return MatchUitkomst(
            uitkomst=GEEN_MATCH,
            bedrag_excl=feiten.bedrag_excl,
            melding=(
                "Geen goedgekeurde offerte gevonden voor deze leverancier + dit project — "
                "koppel er zelf een of laat het werk als verplichting accorderen."
            ),
            kandidaat_ids=kandidaat_ids,
        )

    # (d) factuur zonder (eenduidig) project.
    if len(geldige) == 1:
        return _beoordeel(feiten, geldige[0], kandidaat_ids=kandidaat_ids, grond="enige")
    return MatchUitkomst(
        uitkomst=MEERDERE_KANDIDATEN,
        bedrag_excl=feiten.bedrag_excl,
        melding=(
            f"{len(geldige)} goedgekeurde verplichtingen van deze leverancier en geen eenduidig project op de "
            "factuur — koppel de juiste offerte."
        ),
        kandidaat_ids=kandidaat_ids,
    )


def _beoordeel(
    feiten: FactuurFeiten, kandidaat: Kandidaat, *, kandidaat_ids: tuple[uuid.UUID, ...], grond: str
) -> MatchUitkomst:
    """Cumulatieve toets op de gekozen kandidaat (③)."""
    totaal = kandidaat.goedgekeurd_bedrag_excl
    if totaal is None:
        return MatchUitkomst(
            uitkomst=NIET_TOETSBAAR,
            verplichting_document_id=kandidaat.document_id,
            bedrag_excl=feiten.bedrag_excl,
            melding=(
                "De gekoppelde verplichting heeft geen goedgekeurd bedrag — cumulatief toetsen kan niet "
                "(bedrag aanvullen en opnieuw laten accorderen)."
            ),
            kandidaat_ids=kandidaat_ids,
            grond=grond,
        )
    bedrag = feiten.bedrag_excl or Decimal(0)
    # Herberekening ná boeken: het eigen, al verrekende bedrag zit al in verbruikt_bedrag_excl.
    eigen = feiten.eigen_verrekend or Decimal(0)
    verbruik_voor = (kandidaat.verbruikt_bedrag_excl - eigen).quantize(Decimal("0.01"))
    if verbruik_voor < 0:
        verbruik_voor = Decimal("0.00")
    verbruik_na = (verbruik_voor + bedrag).quantize(Decimal("0.01"))
    binnen = verbruik_na <= totaal
    over = (verbruik_na - totaal).quantize(Decimal("0.01")) if not binnen else None
    nummer = kandidaat.offertenummer or "zonder nummer"
    if binnen:
        melding = (
            f"Binnen de goedgekeurde offerte {nummer}: deze factuur {_bedrag(bedrag)} past; verbruik ná deze "
            f"factuur {_bedrag(verbruik_na)} van {_bedrag(totaal)}."
        )
    else:
        melding = (
            f"Buiten de offerte {nummer} — cumulatief {_bedrag(verbruik_na)} van {_bedrag(totaal)} "
            f"({_bedrag(over)} over). {MEERWERK_HANDELING}"
        )
    return MatchUitkomst(
        uitkomst=BINNEN if binnen else BUITEN,
        verplichting_document_id=kandidaat.document_id,
        bedrag_excl=bedrag,
        verbruik_voor=verbruik_voor,
        verbruik_na=verbruik_na,
        overschrijding_excl=over,
        melding=melding,
        kandidaat_ids=kandidaat_ids,
        grond=grond,
        details={"totaal_excl": str(totaal), "percentage_na": percentage(verbruik_na, totaal)},
    )
