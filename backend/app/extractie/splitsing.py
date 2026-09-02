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
                },
                "required": ["sp", "ep", "ten", "lev", "nr", "z"],
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

Regels: pagina's staan in documentvolgorde; een vervolgpagina (regelbijlage, specificatie) hoort bij
de factuur ervóór. Reken niets uit en gok niet: bij twijfel een lagere z. Eén factuur = één item met
sp=1 en ep=laatste pagina.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord; vervang zulke nummers door "[BSN weggelaten]"."""

OPDRACHT = (
    "Identificeer alle afzonderlijke facturen in deze PDF volgens het schema — paginabereik, "
    "tenaamstelling (geadresseerde), leverancier en factuurnummer per factuur."
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

    @property
    def geldig(self) -> bool:
        return self.ongeldig_reden is None

    def als_dict(self) -> dict:
        return {
            "start_pagina": self.start_pagina,
            "eind_pagina": self.eind_pagina,
            "tenaamstelling": self.tenaamstelling,
            "leverancier": self.leverancier,
            "factuurnummer": self.factuurnummer,
            "zekerheid": self.zekerheid,
            "ongeldig_reden": self.ongeldig_reden,
        }


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
        segmenten.append(
            FactuurSegment(
                start_pagina=start,
                eind_pagina=eind,
                tenaamstelling=tenaamstelling,
                leverancier=leverancier,
                factuurnummer=factuurnummer,
                zekerheid=min(max(zekerheid, 0.0), 1.0),
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
