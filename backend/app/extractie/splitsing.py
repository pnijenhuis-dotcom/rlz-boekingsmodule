"""Intake-AI: tenaamstelling + multi-factuur-grensdetectie op een binnengekomen PDF.

AI leest, code beslist: de AI rapporteert per gevonden factuur het paginabereik, de
tenaamstelling (geadresseerde — leidend voor de administratie-toewijzing), de leverancier en
het factuurnummer; de deterministische validatie hieronder toetst de paginabereiken (binnen
het document, oplopend, niet overlappend). Splitsen zelf gebeurt nooit hier: het voorstel
gaat ALTIJD eerst ter controle naar een mens (app/intake/splitsing.py).

PROPORTIONELE VALIDATIE (spoedopdracht 02-09, diagnose punt 1 — 72/76 splitsingsfouten sinds
25-08): claude-sonnet-5 antwoordde op 1-pagina-PDF's systematisch `ep=2`, waarna de oude
alles-of-niets-validatie het HELE voorstel verwierp, inclusief de correct gelezen
tenaamstelling. Sinds 02-09 (a) gaat het wérkelijke pagina-aantal als feit mee in de opdracht
(lokaal bewezen 3/3 correct) en (b) is de poort chirurgisch: één herkende factuur = het hele
document (bereik genormaliseerd naar 1–N, splitsing is niet aan de orde); bij meerdere facturen
krijgt alleen het ongeldige deel `ongeldig_reden` (de mens ziet het en beslist), de geldige delen
en álle gelezen tenaamstellingen blijven staan. `valideer_segmenten` blijft de harde
alles-of-niets-poort voor de door de MENS bevestigde bereiken (app/intake/splitsing.py).

AVG: draait uitsluitend achter de platform-brede intake-gate (settings.intake_ai_ingeschakeld,
default UIT) — op dit punt is er nog geen administratie, dus de per-administratie-gate kan
niet gelden. Het BSN-postfilter geldt op de vrije-tekstvelden zoals bij elke extractie."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.aikosten.service import AiVerbruikReferentie
from app.extractie.bsn import verwijder_bsns
from app.extractie.client import AiExtractieFout, ClaudeExtractieClient

logger = logging.getLogger(__name__)

_STRING_OF_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

#: Documentsoort-herkenning door de intake-AI (offerte-matching 04-09) — sentinel-waarden.
DOCUMENTSOORT_FACTUUR = "factuur"
DOCUMENTSOORT_VERPLICHTING = "verplichting"
DOCUMENTSOORT_ONDUIDELIJK = "onduidelijk"
DOCUMENTSOORTEN = (DOCUMENTSOORT_FACTUUR, DOCUMENTSOORT_VERPLICHTING, DOCUMENTSOORT_ONDUIDELIJK)

SPLITSING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facturen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sp": {"type": "integer"},
                    "ep": {"type": "integer"},
                    "ten": _STRING_OF_NULL,
                    "lev": _STRING_OF_NULL,
                    "nr": _STRING_OF_NULL,
                    "z": {"type": "number"},
                    # Bijlage-bewust (blok B 04-09): aantal pagina's dat de FACTUUR zelf beslaat; 0 = onbekend.
                    # Bewust een kale integer (sentinel-patroon, geen union) — de unionlimiet blijft 3.
                    "fp": {"type": "integer"},
                    # Documentsoort-herkenning (offerte-matching 04-09): "factuur" | "verplichting" |
                    # "onduidelijk" | "" (niet gelezen). Sentinel-string, GEEN union — de unionlimiet blijft 3.
                    "ds": {"type": "string"},
                },
                "required": ["sp", "ep", "ten", "lev", "nr", "z", "fp", "ds"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facturen"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een intake-assistent voor een administratiekantoor. Een PDF uit het centrale
factuur-postvak kan één factuur bevatten, of meerdere facturen achter elkaar (batch-scan).

Identificeer elke afzonderlijke factuur in het document. Per factuur geef je:
- sp: eerste pagina van die factuur (1-gebaseerd), ep: laatste pagina.
- ten: de tenaamstelling — de naam van de GEADRESSEERDE (aan wie de factuur gericht is), letterlijk
  zoals die op de factuur staat. Onleesbaar of afwezig = null.
- lev: de naam van de leverancier/afzender van de factuur. Onbekend = null.
- nr: het factuurnummer. Onbekend = null.
- z: één zekerheidsscore tussen 0 en 1 voor deze factuur (grens + velden samen).
- fp: het aantal pagina's dat de FACTUUR ZELF beslaat (de pagina's met factuurkop, regels en totalen),
  zónder de bijlagen. Weet je het niet: 0.
- ds: wat voor document dit is. "factuur" voor een factuur of creditnota (een betalingsverzoek voor
  geleverd werk of goederen). "verplichting" voor een OFFERTE, PRIJSOPGAVE, AANBIEDING of
  OPDRACHTBEVESTIGING — een aanbod/toezegging vóóraf, waar nog niet om betaling wordt gevraagd.
  Twijfel je: "onduidelijk". Niet te bepalen: "".

BIJLAGEN HOREN BIJ DE FACTUUR: een factuur bestaat uit de factuurpagina's PLUS haar bijbehorende
bijlagen — werkbonnen, urenstaten, specificaties, pakbonnen, weekstaten, mandagenregisters,
leverbonnen. Zulke vervolgpagina's hebben géén eigen factuurkop en géén eigen factuurnummer en horen
ALTIJD bij de factuur ervóór; ze zijn nooit een nieuwe factuur, ook niet als ze een ander lettertype,
logo van een onderaannemer of eigen paginanummering dragen. Een NIEUWE factuur begint uitsluitend bij een
nieuwe factuurkop: eigen factuurnummer én factuurdatum én geadresseerde. Twijfel = géén nieuwe factuur
(dan liever één factuur met een lagere z).

Regels: pagina's staan in documentvolgorde. Reken niets uit en gok niet: bij twijfel een lagere z.
Eén factuur = één item met sp=1 en ep=laatste pagina.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord; vervang zulke nummers door "[BSN weggelaten]"."""

OPDRACHT = (
    "Identificeer alle afzonderlijke facturen in deze PDF volgens het schema — paginabereik, "
    "tenaamstelling (geadresseerde), leverancier en factuurnummer per factuur. Bijlagen (werkbonnen, "
    "urenstaten, specificaties, pakbonnen) horen bij de factuur ervóór; geef per factuur in fp het aantal "
    "pagina's van de factuur zelf (0 = onbekend). Geef in ds aan of het een factuur is of een "
    "offerte/prijsopgave/opdrachtbevestiging (verplichting); bij twijfel \"onduidelijk\"."
)


def opdracht_met_paginatelling(paginas: int) -> str:
    """Het wérkelijke pagina-aantal (door code geteld, `tel_paginas`) als FEIT in de opdracht
    (diagnose 02-09 §1.4: zonder dit feit antwoordt het model op 1-pagina-PDF's `ep=2`; mét
    het feit 3/3 correct). Prompt-wijziging, géén schema-wijziging."""
    paginas = max(int(paginas), 1)
    if paginas == 1:
        telling = (
            "FEIT: dit document heeft precies 1 pagina (door code geteld). Er bestaat geen pagina 2; "
            "elke factuur heeft dus sp=1 en ep=1."
        )
    else:
        telling = (
            f"FEIT: dit document heeft precies {paginas} pagina's (door code geteld), genummerd 1 tot en "
            f"met {paginas}. Een paginabereik kan nooit buiten 1–{paginas} vallen."
        )
    return f"{OPDRACHT}\n\n{telling}"


@dataclass(frozen=True)
class FactuurSegment:
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None
    leverancier: str | None
    factuurnummer: str | None
    zekerheid: float
    #: Gezet door `beoordeel_segmenten` als dít deel de deterministische paginabereik-toets niet
    #: doorstaat (proportionele validatie 02-09): het deel gaat als "ongeldig — mens beslist" mee
    #: in het splitsingsvoorstel; de overige delen en de gelezen tenaamstellingen blijven staan.
    ongeldig_reden: str | None = None
    #: Bijlage-bewust (blok B 04-09): het aantal pagina's dat de FACTUUR zelf beslaat volgens het
    #: model (`fp`; 0/afwezig = None = onbekend). Puur informatief — de bereik-toets rekent er
    #: nooit mee; `bijlage_paginas` leidt code er deterministisch uit af.
    factuur_paginas: int | None = None
    #: Documentsoort-herkenning (offerte-matching 04-09): DOCUMENTSOORT_FACTUUR |
    #: DOCUMENTSOORT_VERPLICHTING | DOCUMENTSOORT_ONDUIDELIJK | None (niet gelezen). De ROUTING
    #: beslist code (app/intake/verwerking.py): verplichting = eigen documentsoort mét dezelfde
    #: tenaamstelling-routing, onduidelijk = verzamelbak mét reden — nooit stil als factuur.
    documentsoort: str | None = None

    @property
    def geldig(self) -> bool:
        return self.ongeldig_reden is None

    @property
    def bijlage_paginas(self) -> int | None:
        """Aantal bijlagepagina's = (ep − sp + 1) − fp, door code berekend; None = onbekend
        (geen fp, fp buiten het bereik = onbetrouwbaar). Nooit negatief."""
        return bereken_bijlage_paginas(
            start_pagina=self.start_pagina, eind_pagina=self.eind_pagina, factuur_paginas=self.factuur_paginas
        )

    def als_dict(self) -> dict:
        return {
            "start_pagina": self.start_pagina,
            "eind_pagina": self.eind_pagina,
            "tenaamstelling": self.tenaamstelling,
            "leverancier": self.leverancier,
            "factuurnummer": self.factuurnummer,
            "zekerheid": self.zekerheid,
            "ongeldig_reden": self.ongeldig_reden,
            "factuur_paginas": self.factuur_paginas,
            "bijlage_paginas": self.bijlage_paginas,
            "documentsoort": self.documentsoort,
        }


def bereken_bijlage_paginas(*, start_pagina: int, eind_pagina: int, factuur_paginas: int | None) -> int | None:
    """Deterministisch (code, geen AI): bijlagepagina's = bereik − factuurpagina's. Onbekend (None/0),
    een omgekeerd bereik of fp buiten het bereik (fp > bereik = onbetrouwbaar antwoord) → None."""
    if factuur_paginas is None or factuur_paginas < 1:
        return None
    bereik = eind_pagina - start_pagina + 1
    if bereik < 1 or factuur_paginas > bereik:
        return None
    return bereik - factuur_paginas


# Begeleidende mailtekst als hint in de opdracht (punt 1c): begrensd én door het BSN-filter,
# dezelfde AVG-discipline als de documentinhoud. Eén plek voor alle extractie-opdrachten.
MAIL_CONTEXT_MAX_TEKENS = 4_000


def met_mail_context(opdracht: str, mail_context: str | None) -> str:
    if not mail_context or not mail_context.strip():
        return opdracht
    schoon, _ = verwijder_bsns(mail_context.strip())
    if len(schoon) > MAIL_CONTEXT_MAX_TEKENS:
        schoon = schoon[:MAIL_CONTEXT_MAX_TEKENS].rstrip() + " […]"
    return (
        f"{opdracht}\n\n"
        "Begeleidende e-mail waarmee dit document is aangeleverd — uitsluitend CONTEXT/HINT (bijvoorbeeld "
        "voor wie de factuur bestemd is); wat op het document zelf staat is altijd leidend en de mailtekst "
        "mag nooit als factuurinhoud worden overgenomen:\n"
        f"<<<\n{schoon}\n>>>"
    )


def _schoon(waarde: Any) -> tuple[str | None, int]:
    if waarde is None:
        return None, 0
    tekst = str(waarde).strip()
    if not tekst:
        return None, 0
    return verwijder_bsns(tekst)


def valideer_segmenten(segmenten: list[FactuurSegment], *, paginas: int) -> str | None:
    """Deterministische validatie (code beslist): None = geldig, anders de reden waarom het
    voorstel als geheel ongeldig is (→ geen splitsingsvoorstel, document naar de verzamelbak)."""
    if not segmenten:
        return "geen facturen herkend"
    vorige_eind = 0
    for segment in segmenten:
        if segment.start_pagina < 1 or segment.eind_pagina > paginas:
            return (
                f"paginabereik {segment.start_pagina}–{segment.eind_pagina} valt buiten het "
                f"document ({paginas} pagina's)"
            )
        if segment.start_pagina > segment.eind_pagina:
            return f"paginabereik {segment.start_pagina}–{segment.eind_pagina} is omgekeerd"
        if segment.start_pagina <= vorige_eind:
            return "paginabereiken overlappen of staan niet in volgorde"
        vorige_eind = segment.eind_pagina
    return None


@dataclass(frozen=True)
class BeoordeeldeSegmenten:
    """Uitkomst van de proportionele validatie: álle segmenten (ongeldige mét `ongeldig_reden`)
    plus de normalisaties die code heeft toegepast (voor de tijdlijn/logging)."""

    segmenten: list[FactuurSegment]
    normalisaties: list[str]

    @property
    def geldig(self) -> list[FactuurSegment]:
        return [s for s in self.segmenten if s.geldig]

    @property
    def ongeldig(self) -> list[FactuurSegment]:
        return [s for s in self.segmenten if not s.geldig]


def _bereik_reden(segment: FactuurSegment, *, paginas: int) -> str | None:
    if segment.start_pagina < 1 or segment.eind_pagina > paginas:
        return (
            f"paginabereik {segment.start_pagina}–{segment.eind_pagina} valt buiten het document "
            f"({paginas} pagina's)"
        )
    if segment.start_pagina > segment.eind_pagina:
        return f"paginabereik {segment.start_pagina}–{segment.eind_pagina} is omgekeerd"
    return None


def beoordeel_segmenten(segmenten: list[FactuurSegment], *, paginas: int) -> BeoordeeldeSegmenten:
    """Proportionele validatie (spoedopdracht 02-09): code beslist, maar chirurgisch.

    - Geen segmenten: niets te beoordelen (de aanroeper meldt "geen facturen herkend").
    - Precies één herkende factuur: één factuur = het hele document, dus het bereik wordt
      DETERMINISTISCH genormaliseerd naar 1–`paginas` (het AI-bereik doet er niet toe; op een
      1-pagina-document is splitsing per definitie niet aan de orde). De gelezen
      tenaamstelling/leverancier/nummer blijven onaangeroerd.
    - Meerdere facturen: per deel de bereik-toets (binnen het document, niet omgekeerd) en op de
      geldige delen de volgorde-/overlap-toets; een deel dat faalt krijgt `ongeldig_reden`, de
      rest blijft staan. Het voorstel gaat sowieso ter controle naar een mens."""
    paginas = max(int(paginas), 1)
    if not segmenten:
        return BeoordeeldeSegmenten(segmenten=[], normalisaties=[])
    if len(segmenten) == 1:
        enige = segmenten[0]
        if (enige.start_pagina, enige.eind_pagina) == (1, paginas):
            return BeoordeeldeSegmenten(segmenten=[enige], normalisaties=[])
        genormaliseerd = FactuurSegment(
            start_pagina=1,
            eind_pagina=paginas,
            tenaamstelling=enige.tenaamstelling,
            leverancier=enige.leverancier,
            factuurnummer=enige.factuurnummer,
            zekerheid=enige.zekerheid,
            factuur_paginas=enige.factuur_paginas,
        )
        return BeoordeeldeSegmenten(
            segmenten=[genormaliseerd],
            normalisaties=[
                f"paginabereik {enige.start_pagina}–{enige.eind_pagina} genormaliseerd naar 1–{paginas} "
                "(één herkende factuur = het hele document)"
            ],
        )

    beoordeeld: list[FactuurSegment] = []
    vorige_eind = 0
    for segment in segmenten:
        reden = _bereik_reden(segment, paginas=paginas)
        if reden is None and segment.start_pagina <= vorige_eind:
            reden = (
                f"paginabereik {segment.start_pagina}–{segment.eind_pagina} overlapt met een vorig deel "
                "of staat niet in volgorde"
            )
        if reden is None:
            vorige_eind = segment.eind_pagina
            beoordeeld.append(segment)
        else:
            beoordeeld.append(
                FactuurSegment(
                    start_pagina=segment.start_pagina,
                    eind_pagina=segment.eind_pagina,
                    tenaamstelling=segment.tenaamstelling,
                    leverancier=segment.leverancier,
                    factuurnummer=segment.factuurnummer,
                    zekerheid=segment.zekerheid,
                    ongeldig_reden=reden,
                    factuur_paginas=segment.factuur_paginas,
                    documentsoort=segment.documentsoort,
                )
            )
    return BeoordeeldeSegmenten(segmenten=beoordeeld, normalisaties=[])


def detecteer_facturen(
    pdf_bytes: bytes,
    *,
    paginas: int,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
    mail_context: str | None = None,
) -> list[FactuurSegment]:
    """Eén Claude-aanroep → beoordeelde segmenten (proportionele validatie, zie
    `beoordeel_segmenten`). Alleen een ONBRUIKBAAR antwoord (afkap, onleesbaar bereik, geen
    facturen herkend) is een AiExtractieFout — de aanroeper vangt 'm en routeert naar de
    verzamelbak, nooit een stille gok. Een ongeldig paginabereik verwerpt sinds 02-09 nooit
    meer het hele voorstel: de teruggegeven lijst kan delen mét `ongeldig_reden` bevatten.
    `mail_context` = de begeleidende mailtekst als HINT (feedbackronde 25-08 deel 3 punt 1c) —
    gaat BSN-gefilterd mee in de opdracht, het document blijft leidend."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes,
        system=SYSTEM_PROMPT,
        opdracht=met_mail_context(opdracht_met_paginatelling(paginas), mail_context),
        json_schema=SPLITSING_SCHEMA,
    )
    if antwoord.afgekapt:
        raise AiExtractieFout("Splitsingsdetectie afgekapt (max_tokens) — voorstel onbruikbaar.")

    segmenten: list[FactuurSegment] = []
    for ruw in (antwoord.data or {}).get("facturen") or []:
        if not isinstance(ruw, dict):
            continue
        tenaamstelling, _ = _schoon(ruw.get("ten"))
        leverancier, _ = _schoon(ruw.get("lev"))
        factuurnummer, _ = _schoon(ruw.get("nr"))
        try:
            start, eind = int(ruw.get("sp")), int(ruw.get("ep"))
        except (TypeError, ValueError):
            raise AiExtractieFout("Splitsingsvoorstel bevat een onleesbaar paginabereik.") from None
        zekerheid = float(ruw.get("z")) if isinstance(ruw.get("z"), int | float) else 0.0
        # fp (bijlage-bewust, 04-09): sentinel 0/afwezig/onleesbaar = onbekend — nooit een fout, alleen
        # informatief; de bereik-toets rekent er niet mee.
        fp_ruw = ruw.get("fp")
        fp_bruikbaar = isinstance(fp_ruw, int) and not isinstance(fp_ruw, bool) and fp_ruw > 0
        factuur_paginas = int(fp_ruw) if fp_bruikbaar else None
        # ds (offerte-matching 04-09): sentinel — alleen de drie bekende waarden zijn een uitspraak;
        # alles anders (leeg, onbekend woord) = None = "niet gelezen" → bestaande factuur-routing.
        ds_ruw = ruw.get("ds")
        documentsoort = (
            ds_ruw.strip().lower()
            if isinstance(ds_ruw, str) and ds_ruw.strip().lower() in DOCUMENTSOORTEN
            else None
        )
        segmenten.append(
            FactuurSegment(
                start_pagina=start,
                eind_pagina=eind,
                tenaamstelling=tenaamstelling,
                leverancier=leverancier,
                factuurnummer=factuurnummer,
                zekerheid=min(max(zekerheid, 0.0), 1.0),
                factuur_paginas=factuur_paginas,
                documentsoort=documentsoort,
            )
        )

    if not segmenten:
        raise AiExtractieFout("Splitsingsvoorstel ongeldig: geen facturen herkend")
    beoordeeld = beoordeel_segmenten(segmenten, paginas=paginas)
    for normalisatie in beoordeeld.normalisaties:
        logger.info("Splitsingsdetectie: %s", normalisatie)
    for deel in beoordeeld.ongeldig:
        logger.warning("Splitsingsdetectie: deel ongeldig — %s (mens beslist)", deel.ongeldig_reden)
    logger.info(
        "Splitsingsdetectie: %s factuur/facturen in %s pagina('s), %s deel/delen ongeldig",
        len(beoordeeld.segmenten),
        paginas,
        len(beoordeeld.ongeldig),
    )
    return beoordeeld.segmenten
