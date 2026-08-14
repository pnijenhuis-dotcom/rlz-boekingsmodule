"""Kassarapport-extractie (omzetmodule, fase 2): AI leest het rapport voor, code rekent.

Zelfde patroon als de factuurextractie (app/extractie/service.py + controle.py), maar voor
kassarapporten (pilot: BLOW Margerapport — categorieën met inkoop-/verkooptotalen per periode):
- Claude leest uitsluitend voor (periode, categorieën, bedragen zoals ze er staan), met één
  zekerheidsscore per kopveld/regel; structured outputs dwingen valide JSON af.
- De deterministische controlelaag hieronder parst bedragen/datums, toetst de regelsommen tegen
  de rapport-totalen en berekent de marge — nooit de AI (kernprincipe: code voor cijfers).
- AVG-gate: de aanroeper (app/documenten/service.py) laat een kassarapport-PDF alleen deze kant
  op als `ai_extractie_ingeschakeld` aan staat — zelfde gate als de factuurextractie, en de
  AVG-volgorde (DPA/EU-verwerking/verwerkersregister) geldt onverkort: tot die rond is draait
  dit alleen op test-/eigen data.

Een kassarapport is klein (één pagina, handvol categorieën) — bewust géén chunking-machinerie:
kapt de respons af (max_tokens), dan is dat een zichtbare extractiefout, geen chunk-trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.aikosten.service import AiVerbruikReferentie
from app.extractie.bsn import verwijder_bsns
from app.extractie.client import AiExtractieFout, ClaudeExtractieClient

logger = logging.getLogger(__name__)

# Draad-key -> interne veldnaam (kop). Compact formaat, zelfde overweging als de
# factuurextractie (groottevrij-besluit): korte keys op de draad, volledige namen intern.
_KOP_KEYS: dict[str, str] = {
    "titel": "rapport_titel",
    "ent": "entiteit_naam",
    "start": "periode_start",
    "eind": "periode_eind",
    "tot_i": "totaal_kostprijs",
    "tot_v": "totaal_omzet",
}

_STRING_OF_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

RAPPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kop": {
            "type": "object",
            "properties": {key: _STRING_OF_NULL for key in _KOP_KEYS},
            "required": list(_KOP_KEYS),
            "additionalProperties": False,
        },
        "kz": {
            "type": "object",
            "properties": {key: {"type": "number"} for key in _KOP_KEYS},
            "required": list(_KOP_KEYS),
            "additionalProperties": False,
        },
        # Eén rapportregel: c=categorie, i=inkooptotaal (kostprijs), v=verkooptotaal (omzet),
        # z=één zekerheidsscore voor de hele regel.
        "regels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "c": _STRING_OF_NULL,
                    "i": _STRING_OF_NULL,
                    "v": _STRING_OF_NULL,
                    "z": {"type": "number"},
                },
                "required": ["c", "i", "v", "z"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["kop", "kz", "regels"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een extractie-assistent voor kassarapporten (omzetrapporten) van een administratiekantoor.

Lees uitsluitend voor wat er letterlijk op het rapport staat. Reken niets uit, leid niets af en vul niets
aan: staat een waarde niet (leesbaar) op het document, geef dan null. Een leeg voorstel is beter dan een
voorstel dat gokt.

Veldsleutels (compact, antwoord bevat NIETS anders dan deze velden):
- kop: titel=rapporttitel/-soort, ent=naam van de onderneming/entiteit waar het rapport over gaat,
  start=begindatum van de rapportperiode, eind=einddatum van de rapportperiode,
  tot_i=totaal inkoop/kostprijs zoals vermeld, tot_v=totaal verkoop/omzet zoals vermeld —
  totalen dus niet zelf optellen, alleen voorlezen.
- kz: per kopveld één zekerheidsscore tussen 0 en 1 (zelfde sleutels als kop).
- regels: één item per omzetcategorie/productgroep, in documentvolgorde. c=categorienaam zoals die
  er staat (inclusief eventuele nummering), i=inkooptotaal/kostprijs van die categorie,
  v=verkooptotaal/omzet van die categorie, z=één zekerheidsscore voor de hele regel.
  Totaalregels ("Totaal", "Subtotaal") zijn GEEN categorie — die horen alleen in tot_i/tot_v.

Notatie: bedragen als string met punt-decimaal zonder duizendtalscheiding en zonder valutateken
(bijv. "1234.56"); datums als ISO 8601 (YYYY-MM-DD). Ontbreekt het jaartal bij de periode maar staat
het elders op het rapport (bv. in een datumregel of bestandsvermelding), gebruik dan dát jaartal;
is het nergens vermeld, geef de datum dan als null.

Wees zuinig: echo nooit overige documenttekst — alleen de gevraagde veldwaarden.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord. Laat zulke nummers volledig weg; vervang ze in tekstvelden door "[BSN weggelaten]"."""

OPDRACHT = (
    "Extraheer de kopgegevens (kop + kz) en ALLE omzetcategorieën (regels) van dit kassarapport "
    "volgens het schema. Alleen voorlezen wat er staat; onbekend of onleesbaar = null."
)

# Vrije-tekstvelden die door het BSN-post-filter gaan (zelfde afweging als de factuurextractie:
# gestructureerde velden — datums, bedragen — zijn per definitie geen BSN).
_VRIJE_TEKST_KOP_KEYS = frozenset({"titel", "ent"})


@dataclass(frozen=True)
class AiRapportVeld:
    waarde: str | None
    zekerheid: float


@dataclass(frozen=True)
class AiRapportRegel:
    categorie: str | None
    kostprijs_bedrag: str | None
    omzet_bedrag: str | None
    zekerheid: float


@dataclass(frozen=True)
class AiRapportExtractie:
    kop: dict[str, AiRapportVeld]
    regels: list[AiRapportRegel]
    bsn_verwijderd: int


def _als_tekst(waarde: Any) -> str | None:
    if waarde is None:
        return None
    if not isinstance(waarde, str):
        waarde = str(waarde)
    waarde = waarde.strip()
    return waarde or None


def _als_zekerheid(ruw: Any) -> float:
    zekerheid = float(ruw) if isinstance(ruw, int | float) else 0.0
    return min(max(zekerheid, 0.0), 1.0)


def extraheer_kassarapport(
    pdf_bytes: bytes,
    *,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
) -> AiRapportExtractie:
    """Stuurt het kassarapport naar Claude en normaliseert het resultaat. Eén aanroep — een
    afgekapte respons is bij een éénpagina-rapport een zichtbare fout, geen chunking-signaal."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=RAPPORT_SCHEMA
    )
    if antwoord.afgekapt:
        raise AiExtractieFout(
            "De rapport-extractie werd afgekapt (max_tokens) — ongebruikelijk voor een kassarapport; "
            "probeer opnieuw of vul handmatig in."
        )

    data = antwoord.data or {}
    kop_ruw = data.get("kop") if isinstance(data.get("kop"), dict) else {}
    kz_ruw = data.get("kz") if isinstance(data.get("kz"), dict) else {}

    bsn_totaal = 0
    kop: dict[str, AiRapportVeld] = {}
    for key, veldnaam in _KOP_KEYS.items():
        tekst = _als_tekst(kop_ruw.get(key))
        if tekst is not None and key in _VRIJE_TEKST_KOP_KEYS:
            tekst, bsn = verwijder_bsns(tekst)
            bsn_totaal += bsn
        kop[veldnaam] = AiRapportVeld(waarde=tekst, zekerheid=_als_zekerheid(kz_ruw.get(key)))

    regels: list[AiRapportRegel] = []
    for ruwe_regel in data.get("regels") or []:
        if not isinstance(ruwe_regel, dict):
            continue
        categorie = _als_tekst(ruwe_regel.get("c"))
        if categorie is not None:
            categorie, bsn = verwijder_bsns(categorie)
            bsn_totaal += bsn
        regels.append(
            AiRapportRegel(
                categorie=categorie,
                kostprijs_bedrag=_als_tekst(ruwe_regel.get("i")),
                omzet_bedrag=_als_tekst(ruwe_regel.get("v")),
                zekerheid=_als_zekerheid(ruwe_regel.get("z")),
            )
        )

    logger.info(
        "Rapport-extractie afgerond: %s categorie(ën), in=%s uit=%s tokens",
        len(regels),
        antwoord.input_tokens,
        antwoord.output_tokens,
    )
    return AiRapportExtractie(kop=kop, regels=regels, bsn_verwijderd=bsn_totaal)


# --- deterministische controlelaag (code voor cijfers — geen AI hieronder) ----------------------

# Toegestane afronding tussen "som van de categorieregels" en het rapport-totaal — zelfde
# tolerantie als de regeltelling-check op inkoopfacturen (app/documenten/checks.py).
_ROND_TOLERANTIE = Decimal("0.01")


def _parse_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _parse_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def bouw_rapport_veldvoorstel(extractie: AiRapportExtractie, *, zekerheid_drempel: float) -> dict:
    """Deterministische controlelaag over de AI-uitvoer: parsen (onparseerbaar = leeg + benoemd),
    regelsom vs rapport-totaal (omzet én kostprijs apart), marge in code berekend. Het resultaat
    is het `veldvoorstel`-dict voor de document-tijdlijn (zelfde sleutel-conventie als de
    factuurextractie; het omzetreview-scherm prefillt hieruit)."""
    onparseerbaar: list[str] = []

    def _kopveld(naam: str) -> tuple[str | None, float]:
        veld = extractie.kop.get(naam)
        return (veld.waarde, veld.zekerheid) if veld else (None, 0.0)

    periode_start_raw, periode_start_z = _kopveld("periode_start")
    periode_eind_raw, periode_eind_z = _kopveld("periode_eind")
    periode_start = _parse_datum(periode_start_raw)
    periode_eind = _parse_datum(periode_eind_raw)
    if periode_start_raw and periode_start is None:
        onparseerbaar.append("periode_start")
    if periode_eind_raw and periode_eind is None:
        onparseerbaar.append("periode_eind")

    totaal_omzet_raw, totaal_omzet_z = _kopveld("totaal_omzet")
    totaal_kostprijs_raw, totaal_kostprijs_z = _kopveld("totaal_kostprijs")
    totaal_omzet = _parse_decimal(totaal_omzet_raw)
    totaal_kostprijs = _parse_decimal(totaal_kostprijs_raw)
    if totaal_omzet_raw and totaal_omzet is None:
        onparseerbaar.append("totaal_omzet")
    if totaal_kostprijs_raw and totaal_kostprijs is None:
        onparseerbaar.append("totaal_kostprijs")

    regels: list[dict] = []
    for i, regel in enumerate(extractie.regels, start=1):
        omzet = _parse_decimal(regel.omzet_bedrag)
        kostprijs = _parse_decimal(regel.kostprijs_bedrag)
        if regel.omzet_bedrag and omzet is None:
            onparseerbaar.append(f"omzet regel {i}")
        if regel.kostprijs_bedrag and kostprijs is None:
            onparseerbaar.append(f"kostprijs regel {i}")
        regels.append(
            {
                "categorie": regel.categorie,
                "omzet_bedrag": str(omzet) if omzet is not None else None,
                "kostprijs_bedrag": str(kostprijs) if kostprijs is not None else None,
                "zekerheid": regel.zekerheid,
                "onzeker": regel.zekerheid < zekerheid_drempel,
            }
        )

    # Regelsom vs rapport-totaal, per kolom — alléén als alle regelbedragen van die kolom geparst
    # zijn (een gedeeltelijke som vergelijken zou schijnzekerheid geven).
    def _som_vs_totaal(kolom: str, totaal: Decimal | None) -> dict:
        bedragen = [_parse_decimal(r[kolom]) for r in regels]
        if totaal is None:
            return {"vergelijkbaar": False, "reden": "geen rapport-totaal gelezen"}
        if not regels or any(b is None for b in bedragen):
            return {"vergelijkbaar": False, "reden": "niet alle regelbedragen leesbaar"}
        som = sum(bedragen, Decimal(0))
        verschil = abs(som - totaal)
        return {
            "vergelijkbaar": True,
            "som": str(som),
            "totaal": str(totaal),
            "verschil": str(verschil),
            "sluit": verschil <= _ROND_TOLERANTIE,
        }

    # Marge zoals het kantoor 'm hanteert (mockup: "marge 160%"): verkoop / inkoop — in code, op
    # de gelezen totalen; geen marge zonder beide totalen of bij kostprijs 0.
    marge_pct = None
    if totaal_omzet is not None and totaal_kostprijs not in (None, Decimal(0)):
        marge_pct = str((totaal_omzet / totaal_kostprijs * 100).quantize(Decimal("0.1")))

    return {
        "soort": "kassarapport",
        "rapport_titel": _kopveld("rapport_titel")[0],
        "entiteit_naam": _kopveld("entiteit_naam")[0],
        "periode_start": periode_start.isoformat() if periode_start else None,
        "periode_eind": periode_eind.isoformat() if periode_eind else None,
        "totaal_omzet": str(totaal_omzet) if totaal_omzet is not None else None,
        "totaal_kostprijs": str(totaal_kostprijs) if totaal_kostprijs is not None else None,
        "marge_pct": marge_pct,
        "zekerheden": {
            "periode_start": periode_start_z,
            "periode_eind": periode_eind_z,
            "totaal_omzet": totaal_omzet_z,
            "totaal_kostprijs": totaal_kostprijs_z,
        },
        "regels": regels,
        "regelsom_omzet": _som_vs_totaal("omzet_bedrag", totaal_omzet),
        "regelsom_kostprijs": _som_vs_totaal("kostprijs_bedrag", totaal_kostprijs),
        "onparseerbaar": onparseerbaar,
        "bsn_verwijderd": extractie.bsn_verwijderd,
    }
