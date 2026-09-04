"""Veldextractie voor het documenttype "verplichting" (offerte / prijsopgave / opdrachtbevestiging —
wens Peter 04-09, mockup `offerte-matching.html` blok 1 "Controle kantoor").

Zelfde vorm als de andere extracties: AI LEEST, CODE BESLIST. De AI leest de kopvelden voor met een
zekerheidsscore per veld; déze code parseert de bedragen/datums (nooit een gok doorgeven), matcht de
crediteur uitsluitend tegen de eigen vendor-cache (btw → KvK → naam, hergebruik van
`controle.match_vendor_met_waarschuwing`) en het project deterministisch tegen de project-cache.

SCHEMA (bugfix 31-08, unionlimiet): SENTINEL-patroon — alle velden zijn verplichte strings, `""`
betekent "niet gelezen" en wordt door deze code None. Géén nullable/union-velden erbij; het schema
staat in `app/extractie/schema_poort.py::live_schemas()` en wordt daar op de limiet getoetst.

AVG: draait uitsluitend achter de per-administratie-gate `ai_extractie_ingeschakeld` + de
AI-kostenpoort ín de client — zie `app/documenten/service.py::_verplichting_extractie_detail`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from app.aikosten.service import AiVerbruikReferentie
from app.extractie import controle
from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer
from app.extractie.client import AiExtractieFout, ClaudeExtractieClient

#: Toegestane soort-labels (gelijk aan de CHECK op verplichting.soort_label).
SOORT_LABELS = ("offerte", "prijsopgave", "opdrachtbevestiging")

#: De kopvelden waarvoor het voorstel een herkomst + zekerheid draagt (DTO-contract).
HERKOMST_VELDEN = (
    "soort_label",
    "leverancier",
    "project",
    "offertenummer",
    "totaalbedrag_excl",
    "geldig_tot",
    "omschrijving",
)

_ZEKERHEID_VELDEN = ("lev", "nr", "dat", "geldig", "excl", "soort", "proj", "oms")
_TEKSTVELDEN = ("lev", "btwnr", "kvk", "nr", "dat", "geldig", "excl", "soort", "proj", "oms")

VERPLICHTING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # Sentinel-patroon: verplichte strings, "" = niet gelezen (nooit nullable — unionlimiet).
        "lev": {"type": "string"},
        "btwnr": {"type": "string"},
        "kvk": {"type": "string"},
        "nr": {"type": "string"},
        "dat": {"type": "string"},
        "geldig": {"type": "string"},
        "excl": {"type": "string"},
        "soort": {"type": "string"},
        "proj": {"type": "string"},
        "oms": {"type": "string"},
        "z": {
            "type": "object",
            "properties": {naam: {"type": "number"} for naam in _ZEKERHEID_VELDEN},
            "required": list(_ZEKERHEID_VELDEN),
            "additionalProperties": False,
        },
    },
    "required": ["lev", "btwnr", "kvk", "nr", "dat", "geldig", "excl", "soort", "proj", "oms", "z"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een extractie-assistent voor een administratiekantoor. Je krijgt een INKOMENDE
OFFERTE, PRIJSOPGAVE of OPDRACHTBEVESTIGING van een leverancier (geen factuur). Het kantoor legt zulke
documenten ter goedkeuring voor aan de klant; latere facturen worden ertegen afgezet.

Lees uitsluitend voor wat er letterlijk in het document staat. Reken niets uit, leid niets af en gok
nooit: staat een gegeven er niet (leesbaar) in, geef dan een LEGE STRING "" voor dat veld.

Velden:
- lev: naam van de leverancier/afzender (degene die de offerte uitbrengt).
- btwnr: het btw-/omzetbelastingnummer van de LEVERANCIER zoals vermeld.
- kvk: het KvK-/handelsregisternummer van de LEVERANCIER zoals vermeld.
- nr: het offerte-/opgave-/opdrachtnummer van dit document (het nummer waarmee de leverancier het
  document zelf aanduidt), letterlijk.
- dat: de datum van het document (YYYY-MM-DD).
- geldig: de datum tot en met wanneer de offerte geldig is / het aanbod gestand wordt gedaan
  (YYYY-MM-DD). Alleen als er een concrete einddatum staat; "30 dagen geldig" zonder datum = "".
- excl: het totaalbedrag EXCLUSIEF btw, als string met punt-decimaal, zonder valutateken en zonder
  duizendtalscheiding (bv. "48500.00"). Staat er alleen een bedrag inclusief btw, geef dan "".
- soort: precies één van "offerte", "prijsopgave", "opdrachtbevestiging" — wat het document zelf
  zegt te zijn. Twijfel of iets anders: "".
- proj: het project/werk waar de offerte over gaat zoals VERMELD (projectnummer, werknummer of
  projectnaam/adres, bv. "26140" of "Verbouwing Koningstraat").
- oms: één korte regel die het werk omschrijft (max ~80 tekens), in je eigen woorden samengevat uit
  de omschrijving in het document.
- z: per veld één zekerheidsscore tussen 0 en 1 (0 als je het veld niet gelezen hebt).

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord; laat zulke nummers volledig weg."""

OPDRACHT = (
    "Lees de kopgegevens van deze offerte/prijsopgave/opdrachtbevestiging voor volgens het schema: "
    "leverancier (mét btw-/KvK-nummer), documentnummer, datum, geldigheidsdatum, totaalbedrag "
    "exclusief btw, soort document, project/werk en een korte omschrijving. Niet gelezen = lege string."
)


@dataclass(frozen=True)
class ProjectKandidaat:
    """Actief project uit de project-cache — de deterministische match-basis (nooit AI)."""

    id: uuid.UUID
    naam: str


@dataclass(frozen=True)
class AiVerplichtingExtractie:
    """Ruwe, door de AI voorgelezen tekstwaarden + zekerheden — één op één uit de respons."""

    velden: dict[str, str | None]
    zekerheid: dict[str, float]


def _sentinel(waarde: Any) -> str | None:
    """Sentinel-lezing: alles behalve een niet-lege string is "niet gelezen"."""
    if not isinstance(waarde, str):
        return None
    schoon = waarde.strip()
    return schoon or None


def extraheer_verplichting(
    pdf_bytes: bytes,
    *,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
) -> AiVerplichtingExtractie:
    """Eén Claude-aanroep. Een afgekapte respons is een zichtbare fout (nooit een half voorstel)."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=VERPLICHTING_SCHEMA
    )
    if antwoord.afgekapt:
        raise AiExtractieFout(
            "De verplichting-extractie werd afgekapt (max_tokens) — probeer opnieuw of vul handmatig in."
        )
    data = antwoord.data or {}
    velden = {naam: _sentinel(data.get(naam)) for naam in _TEKSTVELDEN}
    ruwe_z = data.get("z") if isinstance(data.get("z"), dict) else {}
    zekerheid = {
        naam: min(max(float(ruwe_z.get(naam)), 0.0), 1.0)
        if isinstance(ruwe_z.get(naam), int | float) and not isinstance(ruwe_z.get(naam), bool)
        else 0.0
        for naam in _ZEKERHEID_VELDEN
    }
    return AiVerplichtingExtractie(velden=velden, zekerheid=zekerheid)


_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")
_NUMMER_PREFIX = re.compile(r"^\s*([0-9][0-9A-Za-z\-]*)")


def _norm(tekst: str | None) -> str:
    return _NIET_ALFANUMERIEK.sub("", (tekst or "").lower())


def match_project(
    project_tekst: str | None, kandidaten: list[ProjectKandidaat]
) -> tuple[uuid.UUID | None, str | None, str | None]:
    """Deterministische project-suggestie: (project_id, match, naam) of (None, None, None).

    Volgorde: nummer-prefix exact (de naamconventie van de klant is "26127 Tilburg (Heijmans)" —
    het eerste token is het projectnummer) → naam-bevat (genormaliseerd, in één van beide
    richtingen) → geen suggestie. Bij méér dan één plausibele kandidaat géén suggestie
    ("nooit auto-toewijzen bij twijfel")."""
    if not project_tekst or not kandidaten:
        return None, None, None
    gelezen_nummer = _NUMMER_PREFIX.match(project_tekst)
    if gelezen_nummer is not None:
        doel = _norm(gelezen_nummer.group(1))
        op_nummer = [
            k
            for k in kandidaten
            if (m := _NUMMER_PREFIX.match(k.naam or "")) is not None and _norm(m.group(1)) == doel
        ]
        if len(op_nummer) == 1:
            return op_nummer[0].id, "nummer", op_nummer[0].naam
        if len(op_nummer) > 1:
            return None, None, None
    doel = _norm(project_tekst)
    if len(doel) < 4:
        return None, None, None
    op_naam = [k for k in kandidaten if (n := _norm(k.naam)) and (doel in n or n in doel)]
    if len(op_naam) == 1:
        return op_naam[0].id, "naam", op_naam[0].naam
    if op_naam:
        return None, None, None
    # Laatste kans: fuzzy op de genormaliseerde naam mét één uniek beste resultaat (zelfde drempel
    # als de crediteur-match) — "Koningstraat verbouwing" vs "26140 Koningstraat (Confide)".
    scores = sorted(
        ((SequenceMatcher(None, doel, _norm(k.naam)).ratio(), k) for k in kandidaten if k.naam),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scores or scores[0][0] < 0.85:
        return None, None, None
    besten = [k for score, k in scores if scores[0][0] - score < 0.02]
    if len(besten) != 1:
        return None, None, None
    return besten[0].id, "naam", besten[0].naam


def bouw_verplichting_veldvoorstel(
    extractie: AiVerplichtingExtractie,
    *,
    vendors: list[controle.VendorKandidaat],
    projecten: list[ProjectKandidaat],
    zekerheid_drempel: float,
) -> dict:
    """Zet de AI-lezing om in het veldvoorstel-dict dat (net als bij inkoop) in de document-tijdlijn
    wordt opgeslagen en het reviewscherm voedt. Alle cijfers/datums hier zijn door déze code geparst;
    onparseerbare waarden blijven leeg en worden benoemd (`onparseerbaar`) — nooit een gok."""
    velden = extractie.velden
    onparseerbaar: list[str] = []
    lage_zekerheid: list[str] = []

    def tekst(naam: str) -> str | None:
        waarde = velden.get(naam)
        if waarde is not None and extractie.zekerheid.get(naam, 0.0) < zekerheid_drempel:
            lage_zekerheid.append(naam)
        return waarde

    leverancier_naam = tekst("lev")
    offertenummer = tekst("nr")
    omschrijving = tekst("oms")
    project_tekst = tekst("proj")

    datum_ruw = tekst("dat")
    datum = controle.parse_datum(datum_ruw)
    if datum_ruw and datum is None:
        onparseerbaar.append("datum")
    geldig_ruw = tekst("geldig")
    geldig_tot = controle.parse_datum(geldig_ruw)
    if geldig_ruw and geldig_tot is None:
        onparseerbaar.append("geldig_tot")
    excl_ruw = tekst("excl")
    totaal_excl = controle.parse_bedrag(excl_ruw)
    if excl_ruw and totaal_excl is None:
        onparseerbaar.append("totaalbedrag_excl")

    soort_ruw = (tekst("soort") or "").strip().lower()
    soort_label = soort_ruw if soort_ruw in SOORT_LABELS else None
    if soort_ruw and soort_label is None:
        onparseerbaar.append("soort_label")

    btw_gelezen = valideer_btw_nummer(tekst("btwnr"))
    btw_nummer = btw_gelezen.genormaliseerd if btw_gelezen else None
    if velden.get("btwnr") and btw_nummer is None:
        onparseerbaar.append("btw_nummer")
    kvk_nummer = normaliseer_kvk_nummer(tekst("kvk"))
    if velden.get("kvk") and kvk_nummer is None:
        onparseerbaar.append("kvk_nummer")

    vendor_id, vendor_match, vendor_waarschuwing = controle.match_vendor_met_waarschuwing(
        leverancier_naam, vendors, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer
    )
    vendor_naam = next((v.naam for v in vendors if v.id == vendor_id), None) if vendor_id else None
    project_id, project_match, project_naam = match_project(project_tekst, projecten)

    # Zekerheden onder de DTO-veldnamen (het reviewscherm toont de chips per veld).
    zekerheid_per_veld = {
        "soort_label": extractie.zekerheid.get("soort", 0.0),
        "leverancier": extractie.zekerheid.get("lev", 0.0),
        "project": extractie.zekerheid.get("proj", 0.0),
        "offertenummer": extractie.zekerheid.get("nr", 0.0),
        "totaalbedrag_excl": extractie.zekerheid.get("excl", 0.0),
        "geldig_tot": extractie.zekerheid.get("geldig", 0.0),
        "omschrijving": extractie.zekerheid.get("oms", 0.0),
    }
    return {
        "bron": "ai",
        "soort_label": soort_label,
        "leverancier_naam": leverancier_naam,
        "offertenummer": offertenummer,
        "datum": datum.isoformat() if datum else None,
        "geldig_tot": geldig_tot.isoformat() if geldig_tot else None,
        "totaal_excl": str(totaal_excl) if totaal_excl is not None else None,
        "project_tekst": project_tekst,
        "omschrijving": omschrijving,
        "btw_nummer": btw_nummer,
        "kvk_nummer": kvk_nummer,
        "vendor_suggestie": (
            {"vendor_id": str(vendor_id), "naam": vendor_naam, "match": vendor_match} if vendor_id else None
        ),
        "vendor_waarschuwing": vendor_waarschuwing.als_dict() if vendor_waarschuwing else None,
        "project_suggestie": (
            {"project_id": str(project_id), "naam": project_naam, "match": project_match} if project_id else None
        ),
        "zekerheid": zekerheid_per_veld,
        "zekerheid_drempel": zekerheid_drempel,
        "onparseerbaar": onparseerbaar,
        "lage_zekerheid": lage_zekerheid,
        "ruw": {naam: velden.get(naam) for naam in velden},
    }


def als_datum(waarde: object) -> date | None:
    """Herlezen van een ISO-datum uit het veldvoorstel (dict-waarde)."""
    return controle.parse_datum(waarde if isinstance(waarde, str) else None)


def als_bedrag(waarde: object) -> Decimal | None:
    return controle.parse_bedrag(waarde if isinstance(waarde, str) else None)
