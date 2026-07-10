from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.extractie.bsn import verwijder_bsns
from app.extractie.client import ClaudeExtractieClient

# --- JSON-schema voor structured outputs -------------------------------------------------------
# Elk veld is {waarde, zekerheid}: de zekerheidsscore per veld is een harde eis (controlescherm
# toont percentages, oranje bij laag). Structured outputs ondersteunen geen minimum/maximum-
# constraints — de 0..1-clamp gebeurt deterministisch in _als_veld().

_VELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "waarde": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "zekerheid": {"type": "number"},
    },
    "required": ["waarde", "zekerheid"],
    "additionalProperties": False,
}

_KOP_VELDEN = (
    "leverancier_naam",
    "factuurnummer",
    "factuurdatum",
    "vervaldatum",
    "valuta",
    "totaal_excl",
    "totaal_incl",
    "btw_bedrag",
)
_REGEL_VELDEN = ("omschrijving", "netto_bedrag", "btw_bedrag", "hoeveelheid")

FACTUUR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{veld: _VELD_SCHEMA for veld in _KOP_VELDEN},
        "regels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {veld: _VELD_SCHEMA for veld in _REGEL_VELDEN},
                "required": list(_REGEL_VELDEN),
                "additionalProperties": False,
            },
        },
    },
    "required": [*_KOP_VELDEN, "regels"],
    "additionalProperties": False,
}

# AI leest, code rekent, mens drukt (kernprincipe): de prompt vraagt uitsluitend om VOORLEZEN wat
# er op de factuur staat — nooit rekenen, afleiden of gokken. De BSN-instructie is de eerste
# verdedigingslinie; app/extractie/bsn.py is de deterministische tweede.
SYSTEM_PROMPT = """Je bent een extractie-assistent voor Nederlandse inkoopfacturen van een administratiekantoor.

Lees uitsluitend voor wat er letterlijk op de factuur staat. Reken niets uit, leid niets af en vul niets aan:
staat een waarde niet (leesbaar) op het document, geef dan null. Een voorstel dat leeg is, is beter dan een
voorstel dat gokt.

Notatie:
- Bedragen als string met punt-decimaal en zonder duizendtalscheiding (bijv. "1234.56"), zonder valutateken.
  Creditbedragen negatief ("-25.00").
- Datums als ISO 8601 (YYYY-MM-DD).
- Valuta als ISO-code (bijv. "EUR"), alleen indien vermeld.
- "totaal_excl"/"totaal_incl"/"btw_bedrag" zijn de totalen zoals ze óp de factuur staan — niet zelf optellen.
- Factuurregels: één item per factuurregel, in documentvolgorde. "hoeveelheid" alleen als die expliciet
  vermeld staat.

Zekerheid: geef per veld een score tussen 0 en 1 — hoe zeker je bent dat de waarde exact en op de juiste
plek is voorgelezen. Gebruik lage scores bij slecht leesbare scans, dubbelzinnige labels of afgeleide
posities.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord — ook niet als het prominent op het document staat (bijv. bij een G-rekening/WKA-verklaring of
urenstaat). Laat zulke nummers volledig weg; vervang ze in omschrijvingen door "[BSN weggelaten]"."""

OPDRACHT = (
    "Extraheer de kopgegevens en factuurregels van deze inkoopfactuur volgens het schema. "
    "Alleen voorlezen wat er staat; onbekend of onleesbaar = null."
)


@dataclass(frozen=True)
class AiVeld:
    """Eén geëxtraheerd veld: de ruwe tekstwaarde zoals de AI hem voorlas (nog niet geparst —
    parsen is de taak van de deterministische controlelaag) + zekerheidsscore 0..1."""

    waarde: str | None
    zekerheid: float


@dataclass(frozen=True)
class AiRegel:
    omschrijving: AiVeld
    netto_bedrag: AiVeld
    btw_bedrag: AiVeld
    hoeveelheid: AiVeld


@dataclass(frozen=True)
class AiFactuurExtractie:
    kop: dict[str, AiVeld]
    regels: list[AiRegel]
    bsn_verwijderd: int


def _veld_en_bsn(ruw: Any) -> tuple[AiVeld, int]:
    """Defensieve normalisatie van één {waarde, zekerheid}-object: structured outputs garanderen
    het schema, maar de zekerheids-clamp (0..1) en het BSN-post-filter blijven onze eigen,
    deterministische verantwoordelijkheid. Retourneert (veld, aantal verwijderde BSN's)."""
    if not isinstance(ruw, dict):
        return AiVeld(waarde=None, zekerheid=0.0), 0
    waarde = ruw.get("waarde")
    if waarde is not None and not isinstance(waarde, str):
        waarde = str(waarde)
    zekerheid_ruw = ruw.get("zekerheid")
    zekerheid = float(zekerheid_ruw) if isinstance(zekerheid_ruw, int | float) else 0.0
    zekerheid = min(max(zekerheid, 0.0), 1.0)
    bsn_aantal = 0
    if waarde is not None:
        waarde = waarde.strip() or None
    if waarde is not None:
        waarde, bsn_aantal = verwijder_bsns(waarde)
    return AiVeld(waarde=waarde, zekerheid=zekerheid), bsn_aantal


def extraheer_inkoopfactuur(
    pdf_bytes: bytes, *, client: ClaudeExtractieClient | None = None
) -> AiFactuurExtractie:
    """Stuurt de PDF naar Claude en normaliseert het resultaat naar AiFactuurExtractie. De
    deterministische controlelaag (app/extractie/controle.py) parst en toetst daarna — deze
    functie voegt zelf geen interpretatie toe, behalve het verplichte BSN-post-filter."""
    client = client or ClaudeExtractieClient()
    ruw = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes,
        system=SYSTEM_PROMPT,
        opdracht=OPDRACHT,
        json_schema=FACTUUR_SCHEMA,
    )

    bsn_totaal = 0
    kop: dict[str, AiVeld] = {}
    for naam in _KOP_VELDEN:
        veld, bsn = _veld_en_bsn(ruw.get(naam))
        kop[naam] = veld
        bsn_totaal += bsn

    regels: list[AiRegel] = []
    ruwe_regels = ruw.get("regels")
    if isinstance(ruwe_regels, list):
        for ruwe_regel in ruwe_regels:
            if not isinstance(ruwe_regel, dict):
                continue
            velden: dict[str, AiVeld] = {}
            for naam in _REGEL_VELDEN:
                veld, bsn = _veld_en_bsn(ruwe_regel.get(naam))
                velden[naam] = veld
                bsn_totaal += bsn
            regels.append(AiRegel(**velden))

    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=bsn_totaal)
