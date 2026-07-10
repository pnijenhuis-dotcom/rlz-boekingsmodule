from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.extractie.bsn import verwijder_bsns
from app.extractie.client import ClaudeExtractieClient

logger = logging.getLogger(__name__)

# --- Compact uitvoerschema (structured outputs) -------------------------------------------------
# Groottevrij-besluit (2026-07-10): korte JSON-keys en één zekerheidsgetal per kopveld/per regel,
# zodat een normale factuur ruim binnen het tokenbudget blijft — het verbose
# {waarde, zekerheid}-object per veld uit de eerste versie kostte per regel een veelvoud aan
# output-tokens. Het compacte formaat is alléén het API-draadformaat: intern (AiVeld/AiRegel) en
# richting tijdlijn/frontend blijven de volledige veldnamen.

# Draad-key -> interne veldnaam (kop).
_KOP_KEYS: dict[str, str] = {
    "lev": "leverancier_naam",
    "nr": "factuurnummer",
    "dat": "factuurdatum",
    "verval": "vervaldatum",
    "val": "valuta",
    "excl": "totaal_excl",
    "incl": "totaal_incl",
    "btw": "btw_bedrag",
}

_STRING_OF_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_KOP_PROPS: dict[str, Any] = {
    "kop": {
        "type": "object",
        "properties": {key: _STRING_OF_NULL for key in _KOP_KEYS},
        "required": list(_KOP_KEYS),
        "additionalProperties": False,
    },
    # Zekerheid per kopveld, als parallel object met dezelfde korte keys — één getal per veld.
    "kz": {
        "type": "object",
        "properties": {key: {"type": "number"} for key in _KOP_KEYS},
        "required": list(_KOP_KEYS),
        "additionalProperties": False,
    },
}

# Eén factuurregel: o=omschrijving, n=netto, b=btw, h=hoeveelheid, z=zekerheid (één getal voor de
# hele regel — het controlescherm toont per regel toch het minimum).
_REGEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "o": _STRING_OF_NULL,
        "n": _STRING_OF_NULL,
        "b": _STRING_OF_NULL,
        "h": _STRING_OF_NULL,
        "z": {"type": "number"},
    },
    "required": ["o", "n", "b", "h", "z"],
    "additionalProperties": False,
}

_REGELS_PROP: dict[str, Any] = {"regels": {"type": "array", "items": _REGEL_SCHEMA}}

FACTUUR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {**_KOP_PROPS, **_REGELS_PROP},
    "required": ["kop", "kz", "regels"],
    "additionalProperties": False,
}

# Deelschema's voor chunked extractie: kop apart, regels per indexblok.
KOP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _KOP_PROPS,
    "required": ["kop", "kz"],
    "additionalProperties": False,
}

REGELS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _REGELS_PROP,
    "required": ["regels"],
    "additionalProperties": False,
}

# AI leest, code rekent, mens drukt (kernprincipe): de prompt vraagt uitsluitend om VOORLEZEN wat
# er op de factuur staat — nooit rekenen, afleiden of gokken. De BSN-instructie is de eerste
# verdedigingslinie; app/extractie/bsn.py is de deterministische tweede.
SYSTEM_PROMPT = """Je bent een extractie-assistent voor Nederlandse inkoopfacturen van een administratiekantoor.

Lees uitsluitend voor wat er letterlijk op de factuur staat. Reken niets uit, leid niets af en vul niets aan:
staat een waarde niet (leesbaar) op het document, geef dan null. Een voorstel dat leeg is, is beter dan een
voorstel dat gokt.

Veldsleutels (compact, antwoord bevat NIETS anders dan deze velden):
- kop: lev=leveranciersnaam, nr=factuurnummer, dat=factuurdatum, verval=vervaldatum, val=valuta,
  excl=totaal exclusief btw, incl=totaal inclusief btw, btw=btw-bedrag — telkens zoals ze óp de factuur
  staan, totalen dus niet zelf optellen.
- kz: per kopveld één zekerheidsscore tussen 0 en 1 (zelfde sleutels als kop).
- regels: één item per factuurregel, in documentvolgorde. o=regelomschrijving (kort, alleen de
  omschrijvingstekst van de regel zelf), n=nettobedrag, b=btw-bedrag van de regel, h=hoeveelheid (alleen
  indien expliciet vermeld), z=één zekerheidsscore voor de hele regel.

Notatie: bedragen als string met punt-decimaal zonder duizendtalscheiding en zonder valutateken (bijv.
"1234.56", credit negatief "-25.00"); datums als ISO 8601 (YYYY-MM-DD); valuta als ISO-code (bijv. "EUR").

Wees zuinig: echo nooit overige documenttekst (adresblokken, betalingsvoorwaarden, voetteksten,
disclaimers) — alleen de gevraagde veldwaarden.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord — ook niet als het prominent op het document staat (bijv. bij een G-rekening/WKA-verklaring of
urenstaat). Laat zulke nummers volledig weg; vervang ze in omschrijvingen door "[BSN weggelaten]"."""

OPDRACHT = (
    "Extraheer de kopgegevens (kop + kz) en ALLE factuurregels (regels) van deze inkoopfactuur "
    "volgens het schema. Alleen voorlezen wat er staat; onbekend of onleesbaar = null."
)

OPDRACHT_KOP = (
    "Extraheer alleen de kopgegevens (kop + kz) van deze inkoopfactuur volgens het schema — "
    "géén factuurregels. Alleen voorlezen wat er staat; onbekend of onleesbaar = null."
)

# {start}/{eind} zijn 1-gebaseerde regelnummers in documentvolgorde; de batch-loop hieronder
# bepaalt de blokgrootte adaptief (halveren bij afkap) — geen handmatige drempel.
OPDRACHT_REGELS = (
    "Geef uitsluitend factuurregels {start} tot en met {eind} van deze inkoopfactuur (1-gebaseerd, "
    "documentvolgorde) volgens het schema. Bestaat regel {start} niet, geef dan een lege lijst; zijn er "
    "minder regels dan {eind}, geef dan alleen de resterende. Sla geen regels over en herhaal geen "
    "eerdere regels."
)

# Adaptieve chunking: startblokgrootte en ondergrens (halveren bij afkap van een regel-call), plus
# een harde rem op het totale aantal aanroepen per document — een vangnet tegen een model dat
# blijft "doorleveren", geen normale-bedrijfsvoering-limiet (~40 regel-calls ≈ 1000 regels).
_REGEL_BATCH = 25
_REGEL_BATCH_MINIMUM = 5
_MAX_AANROEPEN = 42


@dataclass(frozen=True)
class AiVeld:
    """Eén geëxtraheerd kopveld: de ruwe tekstwaarde zoals de AI hem voorlas (nog niet geparst —
    parsen is de taak van de deterministische controlelaag) + zekerheidsscore 0..1."""

    waarde: str | None
    zekerheid: float


@dataclass(frozen=True)
class AiRegel:
    """Eén factuurregel met één zekerheidsscore voor de hele regel (compact schema, 2026-07-10)."""

    omschrijving: str | None
    netto_bedrag: str | None
    btw_bedrag: str | None
    hoeveelheid: str | None
    zekerheid: float


@dataclass(frozen=True)
class ExtractieMetriek:
    """Tokenmeting per extractie (groottevrij-besluit: meten en loggen). Gaat als `ai_metriek`
    de document-tijdlijn in — kosteninzicht per document, zonder ooit documentinhoud te loggen."""

    aanroepen: int
    input_tokens: int
    output_tokens: int
    chunked: bool

    def als_dict(self) -> dict[str, int | bool]:
        return {
            "aanroepen": self.aanroepen,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "chunked": self.chunked,
        }


@dataclass(frozen=True)
class AiFactuurExtractie:
    kop: dict[str, AiVeld]
    regels: list[AiRegel]
    bsn_verwijderd: int
    # False = de regelset is mogelijk incompleet (chunking kon het niet compleet krijgen) — de
    # aanroeper beslist wat dat betekent (projectadministratie: blokkeren, zie documenten/service).
    volledig: bool = True
    metriek: ExtractieMetriek | None = None


class _Teller:
    """Muteerbare tokenteller over de (mogelijk meerdere) aanroepen van één extractie."""

    def __init__(self) -> None:
        self.aanroepen = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def tel(self, antwoord: Any) -> Any:
        self.aanroepen += 1
        self.input_tokens += antwoord.input_tokens
        self.output_tokens += antwoord.output_tokens
        return antwoord


@dataclass
class _Genormaliseerd:
    kop: dict[str, AiVeld] = field(default_factory=dict)
    regels: list[AiRegel] = field(default_factory=list)
    bsn_verwijderd: int = 0


def _schoon_tekst(waarde: Any) -> tuple[str | None, int]:
    """Waarde defensief naar (geschoonde string of None, aantal verwijderde BSN's)."""
    if waarde is None:
        return None, 0
    if not isinstance(waarde, str):
        waarde = str(waarde)
    waarde = waarde.strip()
    if not waarde:
        return None, 0
    return verwijder_bsns(waarde)


def _als_zekerheid(ruw: Any) -> float:
    zekerheid = float(ruw) if isinstance(ruw, int | float) else 0.0
    return min(max(zekerheid, 0.0), 1.0)


def _normaliseer_kop(data: dict[str, Any], uit: _Genormaliseerd) -> None:
    kop_ruw = data.get("kop") if isinstance(data.get("kop"), dict) else {}
    kz_ruw = data.get("kz") if isinstance(data.get("kz"), dict) else {}
    for key, veldnaam in _KOP_KEYS.items():
        waarde, bsn = _schoon_tekst(kop_ruw.get(key))
        uit.bsn_verwijderd += bsn
        uit.kop[veldnaam] = AiVeld(waarde=waarde, zekerheid=_als_zekerheid(kz_ruw.get(key)))


def _normaliseer_regels(ruwe_regels: Any, uit: _Genormaliseerd) -> None:
    if not isinstance(ruwe_regels, list):
        return
    for ruwe_regel in ruwe_regels:
        if not isinstance(ruwe_regel, dict):
            continue
        waarden: dict[str, str | None] = {}
        for key in ("o", "n", "b", "h"):
            waarde, bsn = _schoon_tekst(ruwe_regel.get(key))
            uit.bsn_verwijderd += bsn
            waarden[key] = waarde
        uit.regels.append(
            AiRegel(
                omschrijving=waarden["o"],
                netto_bedrag=waarden["n"],
                btw_bedrag=waarden["b"],
                hoeveelheid=waarden["h"],
                zekerheid=_als_zekerheid(ruwe_regel.get("z")),
            )
        )


def _zelfde_regel(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(key) == b.get(key) for key in ("o", "n", "b", "h"))


def _ontdubbel_naad(bestaand: list[dict[str, Any]], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministische naad-ontdubbeling bij chunked regel-calls: als het model bij een
    blokgrens één regel dubbel levert (laatste van het vorige blok == eerste van het nieuwe),
    valt die ene weg. Verder wordt er nooit ontdubbeld — echte facturen kunnen legitiem
    identieke regels bevatten; volledigheid wordt bewaakt door de regelsom-check."""
    if bestaand and batch and _zelfde_regel(bestaand[-1], batch[0]):
        return batch[1:]
    return batch


def _chunked_regels(
    client: ClaudeExtractieClient, pdf_bytes: bytes, teller: _Teller
) -> tuple[list[dict[str, Any]], bool]:
    """Regel-extractie in indexblokken: vraag regels start..start+B-1, tot een blok kleiner dan B
    (of leeg) terugkomt. Kapt een blok zelf af, dan halveert B en wordt hetzelfde blok opnieuw
    gevraagd — adaptief, geen handmatige drempel. Retourneert (ruwe regels, volledig)."""
    regels: list[dict[str, Any]] = []
    batch_grootte = _REGEL_BATCH
    while teller.aanroepen < _MAX_AANROEPEN:
        start = len(regels) + 1
        antwoord = teller.tel(
            client.extraheer_json_uit_pdf(
                pdf_bytes=pdf_bytes,
                system=SYSTEM_PROMPT,
                opdracht=OPDRACHT_REGELS.format(start=start, eind=start + batch_grootte - 1),
                json_schema=REGELS_SCHEMA,
                cache_document=True,
            )
        )
        if antwoord.afgekapt:
            if batch_grootte > _REGEL_BATCH_MINIMUM:
                batch_grootte = max(_REGEL_BATCH_MINIMUM, batch_grootte // 2)
                continue  # zelfde blok opnieuw, kleiner
            logger.warning("Chunked extractie: blok vanaf regel %s kapt zelfs op minimumgrootte af", start)
            return regels, False
        ruwe_batch = antwoord.data.get("regels") if antwoord.data else None
        batch = [regel for regel in ruwe_batch if isinstance(regel, dict)] if isinstance(ruwe_batch, list) else []
        batch = _ontdubbel_naad(regels, batch)
        regels.extend(batch)
        if len(batch) < batch_grootte:
            return regels, True  # minder dan gevraagd = laatste blok gehad
    logger.warning("Chunked extractie: maximum aantal aanroepen (%s) bereikt", _MAX_AANROEPEN)
    return regels, False


def extraheer_inkoopfactuur(
    pdf_bytes: bytes, *, client: ClaudeExtractieClient | None = None
) -> AiFactuurExtractie:
    """Stuurt de PDF naar Claude en normaliseert het resultaat naar AiFactuurExtractie.

    Adaptieve chunking (groottevrij-besluit 2026-07-10): eerst één aanroep voor kop + alle
    regels; kapt die af (stop_reason=max_tokens), dan automatisch chunked — kop in één call,
    regels per indexblok (met batch-halvering bij afkap), daarna deterministisch samengevoegd
    (documentvolgorde, naad-ontdubbeling). Elke deelstap loopt via dezelfde streamende client
    met SDK-retries. `volledig=False` betekent: ook chunking kreeg de regelset niet aantoonbaar
    compleet — de aanroeper beslist (projectadministratie: blokkeren).

    De deterministische controlelaag (app/extractie/controle.py) parst en toetst daarna — deze
    functie voegt zelf geen interpretatie toe, behalve het verplichte BSN-post-filter."""
    client = client or ClaudeExtractieClient()
    teller = _Teller()
    uit = _Genormaliseerd()

    eerste = teller.tel(
        client.extraheer_json_uit_pdf(
            pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=FACTUUR_SCHEMA
        )
    )

    if not eerste.afgekapt:
        volledig = True
        _normaliseer_kop(eerste.data or {}, uit)
        _normaliseer_regels((eerste.data or {}).get("regels"), uit)
    else:
        # Afkap → chunked: kop apart (schrijft meteen de prompt-cache voor de regel-calls).
        kop_antwoord = teller.tel(
            client.extraheer_json_uit_pdf(
                pdf_bytes=pdf_bytes,
                system=SYSTEM_PROMPT,
                opdracht=OPDRACHT_KOP,
                json_schema=KOP_SCHEMA,
                cache_document=True,
            )
        )
        _normaliseer_kop(kop_antwoord.data or {}, uit)
        if kop_antwoord.afgekapt:
            # Kop-only die afkapt is geen groottevraagstuk maar iets structureels geks — regels
            # proberen is dan zinloos; onvolledig, aanroeper beslist.
            volledig = False
        else:
            ruwe_regels, volledig = _chunked_regels(client, pdf_bytes, teller)
            _normaliseer_regels(ruwe_regels, uit)

    metriek = ExtractieMetriek(
        aanroepen=teller.aanroepen,
        input_tokens=teller.input_tokens,
        output_tokens=teller.output_tokens,
        chunked=teller.aanroepen > 1,
    )
    logger.info(
        "AI-extractie afgerond: %s regel(s), volledig=%s, %s aanroep(en), in=%s uit=%s tokens",
        len(uit.regels),
        volledig,
        metriek.aanroepen,
        metriek.input_tokens,
        metriek.output_tokens,
    )
    return AiFactuurExtractie(
        kop=uit.kop,
        regels=uit.regels,
        bsn_verwijderd=uit.bsn_verwijderd,
        volledig=volledig,
        metriek=metriek,
    )
