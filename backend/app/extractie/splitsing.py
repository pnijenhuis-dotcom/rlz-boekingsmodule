"""Intake-AI: tenaamstelling + multi-factuur-grensdetectie op een binnengekomen PDF.

AI leest, code beslist: de AI rapporteert per gevonden factuur het paginabereik, de
tenaamstelling (geadresseerde — leidend voor de administratie-toewijzing), de leverancier en
het factuurnummer; de deterministische validatie hieronder toetst de paginabereiken (binnen
het document, oplopend, niet overlappend) en een ongeldig voorstel telt als "geen voorstel" —
het document valt dan gewoon in de verzamelbak. Splitsen zelf gebeurt nooit hier: het voorstel
gaat ALTIJD eerst ter controle naar een mens (app/intake/splitsing.py).

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


@dataclass(frozen=True)
class FactuurSegment:
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None
    leverancier: str | None
    factuurnummer: str | None
    zekerheid: float

    def als_dict(self) -> dict:
        return {
            "start_pagina": self.start_pagina,
            "eind_pagina": self.eind_pagina,
            "tenaamstelling": self.tenaamstelling,
            "leverancier": self.leverancier,
            "factuurnummer": self.factuurnummer,
            "zekerheid": self.zekerheid,
        }


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


def detecteer_facturen(
    pdf_bytes: bytes,
    *,
    paginas: int,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
) -> list[FactuurSegment]:
    """Eén Claude-aanroep → gevalideerde segmenten. Elke ongeldige uitkomst (afkap, ongeldige
    bereiken) is een AiExtractieFout — de aanroeper vangt 'm en routeert naar de verzamelbak,
    nooit een stille gok."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=SPLITSING_SCHEMA
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

    reden = valideer_segmenten(segmenten, paginas=paginas)
    if reden is not None:
        raise AiExtractieFout(f"Splitsingsvoorstel ongeldig: {reden}")
    logger.info("Splitsingsdetectie: %s factuur/facturen in %s pagina('s)", len(segmenten), paginas)
    return segmenten
