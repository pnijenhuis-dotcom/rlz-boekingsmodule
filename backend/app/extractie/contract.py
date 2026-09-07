"""Contract-/offerte-ontleding voor de projectenmodule (mockup projecten-invoer.html, akkoord
Peter 22-08; herzien blok D6 07-09 — besluit Peter 06-09 "kopvelden + auto-first").

De AI leest VOOR wat er letterlijk staat: de KOPVELDEN soort werk, contract-m² en doorlopende huur
daarna (expliciet uitgevraagd — "niet in contract aangetroffen" is een expliciete uitkomst via het
sentinel-patroon: verplichte string, `""` = niet aangetroffen → deterministisch None), plus de
REGELS looptijd, huurtijd, opdrachtgever, werknummer, verrekenstaffels en boeteclausules, elk mét
citaat en zekerheidsscore. Het schema is volledig union-vrij (0 anyOf/nullable — Anthropic's limiet
van 16 union-parameters, bugfix 31-08; testpoort tests/extractie/test_schema_unionlimiet.py).

Rekenen doet de AI nooit: alle afleidingen (getal-parsing, eenheid-mapping, doorlopende huur uit
een huurstaffel "€ 150/week uitgaande van 9 weken" → "vanaf week 10") zijn deterministische code
in deze module (pure functies, los testbaar). Wegschrijven (auto-first, herkomst 'contract')
gebeurt in app/projecten/ontleding.py. Zelfde infra als de andere extracties:
ClaudeExtractieClient (streaming, structured outputs, throttling) mét de AI-kostenpoort ín de
client; draait uitsluitend achter de per-administratie AVG-gate (ai_extractie_ingeschakeld)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.aikosten.service import AiVerbruikReferentie
from app.extractie.client import AiExtractieFout, ClaudeExtractieClient

# Sentinel in het AI-antwoord: lege string = "niet in contract aangetroffen" (verplichte string,
# nooit null — union-limiet-patroon app/extractie/service.py).
NIET_AANGETROFFEN = ""

# Kopvelden die het schema expliciet uitvraagt (D6). Elk kopveld = waarde + citaat.
KOPVELDEN = ("soort_werk", "contract_m2", "doorlopende_huur_na")

# Regelsoorten in de regels-lijst. contract_m2/doorlopende_huur/soort_werk zitten bewust NIET in
# deze enum: die worden als kopveld uitgevraagd (anders leest de AI ze dubbel).
_REGEL_SOORTEN = (
    "looptijd",
    "huurtijd",
    "opdrachtgever",
    "werknummer",
    "staffel",
    "boete",
)

_TEKST: dict[str, Any] = {"type": "string"}

CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kop": {
            "type": "object",
            "properties": {
                # Soort werk (bv. "gevelsteiger renovatie", "steigerhuur + montage"); "" = niet aangetroffen.
                "soort_werk": _TEKST,
                "soort_werk_citaat": _TEKST,
                # Gecontracteerd aantal m² als getal-string ("4200", "4200.5"); "" = niet aangetroffen.
                "contract_m2": _TEKST,
                "contract_m2_citaat": _TEKST,
                # Tarief doorlopende huur ná de inbegrepen periode, tekst zoals die er staat
                # (bv. "€ 0,42 /m²/week na 16 weken"); "" = niet aangetroffen.
                "doorlopende_huur_na": _TEKST,
                "doorlopende_huur_na_citaat": _TEKST,
            },
            "required": [
                "soort_werk",
                "soort_werk_citaat",
                "contract_m2",
                "contract_m2_citaat",
                "doorlopende_huur_na",
                "doorlopende_huur_na_citaat",
            ],
            "additionalProperties": False,
        },
        "regels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "soort": {"type": "string", "enum": list(_REGEL_SOORTEN)},
                    # Korte omschrijving (bv. "Staffel: trapsteiger").
                    "oms": _TEKST,
                    # Letterlijk citaat + vindplaats (bv. '§4.2 "verrekenbaar tegen € 9,20 per m²"'); "" = geen.
                    "citaat": _TEKST,
                    # Soort-afhankelijk: getal/bedrag als string met punt-decimaal ("9.20"); bij tekstvelden
                    # de tekst; bij looptijd leeg (datums in van/tot). "" = onbekend.
                    "waarde": _TEKST,
                    "eenheid": _TEKST,  # alleen staffels: de eenheid zoals die er staat; anders ""
                    "van": _TEKST,  # alleen looptijd (YYYY-MM-DD); anders ""
                    "tot": _TEKST,  # alleen looptijd (YYYY-MM-DD); anders ""
                    "z": {"type": "number"},
                },
                "required": ["soort", "oms", "citaat", "waarde", "eenheid", "van", "tot", "z"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["kop", "regels"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een extractie-assistent voor steigerbouw-contracten en -offertes van een
administratiekantoor.

Lees uitsluitend voor wat er letterlijk in het document staat. Reken niets uit, leid niets af en vul niets
aan. Elk gegeven draagt een citaat (letterlijke zinsnede + vindplaats zoals paragraafnummer of pagina)
zodat de controleur het kan verifiëren.

KOPVELDEN (altijd beantwoorden — staat een gegeven niet (leesbaar) in het document, geef dan precies een
lege string "" als waarde én als citaat; dat betekent "niet in contract aangetroffen" en is een geldige uitkomst):
- soort_werk: het soort werk/de opdracht in enkele woorden zoals het document het noemt
  (bv. "gevelsteiger t.b.v. renovatie", "steigerhuur incl. montage/demontage").
- contract_m2: het gecontracteerde aantal m² steigerwerk (getal als string, bv. "4200").
- doorlopende_huur_na: het tarief voor doorlopende huur ná de inbegrepen huur-/standtijd, als tekst zoals die
  er staat (bv. "€ 0,42 /m²/week na 16 weken", "€ 150 per week vanaf week 10").

REGELS (alleen deze soorten; onbekend of onleesbaar = de regel weglaten):
- looptijd: de contract-/uitvoeringsperiode (van/tot als YYYY-MM-DD; ontbreekt een kant, geef die als "").
- huurtijd: de in de aanneemsom inbegrepen huurtijd/standtijd (waarde = tekst zoals die er staat, bv. "16 weken").
- opdrachtgever: de contractuele opdrachtgever (waarde = naam).
- werknummer: het werk-/projectnummer dat de OPDRACHTGEVER hanteert (waarde = nummer zoals vermeld).
- staffel: één verrekenprijs/staffelregel (oms = korte naam van het item, waarde = prijs als string met
  punt-decimaal zonder valutateken, eenheid = de eenheid zoals die er staat, bv. "m²", "m¹/week", "uur",
  "week"). Elke verrekenbare prijs is een eigen regel; nulregels/tariefstaffels zonder prijs weglaten. Staat er
  bij een huurstaffel een uitgangsperiode ("€ 150/week uitgaande van 9 weken"), neem die zin letterlijk op in
  het citaat.
- boete: een boeteclausule (waarde = bedrag of tekst, oms beschrijft de clausule) — ter info, wordt projectsignaal.

Velden die voor een regelsoort niet van toepassing zijn (eenheid, van, tot) krijgen "". z = één zekerheidsscore
tussen 0 en 1 per regel. Notatie: bedragen als string met punt-decimaal zonder duizendtalscheiding en zonder
valutateken; datums als ISO 8601 (YYYY-MM-DD).

Wees zuinig: echo nooit overige documenttekst — alleen de gevraagde velden.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord. Laat zulke nummers volledig weg; vervang ze in tekstvelden door "[BSN weggelaten]"."""

OPDRACHT = (
    "Ontleed dit contract/deze offerte volgens het schema: de kopvelden soort_werk, contract_m2 en "
    "doorlopende_huur_na (niet aangetroffen = lege string), en de regels looptijd, huurtijd, opdrachtgever, "
    "werknummer, ALLE verrekenstaffels en eventuele boeteclausules. Alleen voorlezen wat er staat, mét citaat."
)


@dataclass(frozen=True)
class ContractRegel:
    soort: str
    omschrijving: str
    citaat: str | None
    waarde: str | None
    eenheid: str | None
    van: str | None
    tot: str | None
    zekerheid: float


@dataclass(frozen=True)
class ContractKop:
    """De drie expliciet uitgevraagde kopvelden; None = "niet in contract aangetroffen" (sentinel)."""

    soort_werk: str | None = None
    soort_werk_citaat: str | None = None
    contract_m2: str | None = None
    contract_m2_citaat: str | None = None
    doorlopende_huur_na: str | None = None
    doorlopende_huur_na_citaat: str | None = None


@dataclass(frozen=True)
class ContractOntleding:
    kop: ContractKop
    regels: list[ContractRegel]


def _als_tekst(waarde: Any) -> str | None:
    """Sentinel-normalisatie: None/""/whitespace → None, anders de gestripte tekst."""
    if waarde is None:
        return None
    tekst = str(waarde).strip()
    return tekst or None


# --- deterministische afleidingen (code, geen AI) --------------------------------------------------

_GETAL_RUIS = re.compile(r"(?i)(€|eur\b|m\s*[²2]|m\s*[¹1]|stuks?|st\.|per\b|week|wk|/|\s)")


def parse_getal(tekst: str | None) -> Decimal | None:
    """Getal uit contracttekst → Decimal, deterministisch. Herkent Nederlandse én punt-notatie:
    "4200" → 4200, "4.200" → 4200 (duizendtal), "4200,50"/"4200.50" → 4200.50, "1.234,56" → 1234.56,
    "€ 9,20 per m²" → 9.20, "150,-" → 150. Onleesbaar → None (nooit gokken)."""
    if tekst is None:
        return None
    schoon = _GETAL_RUIS.sub("", tekst).replace(",-", "").replace(",–", "").strip()
    if not re.fullmatch(r"-?\d[\d.,]*", schoon):
        return None
    if "," in schoon and "." in schoon:
        # Laatste scheidingsteken is de decimaal; de andere is duizendtal.
        if schoon.rfind(",") > schoon.rfind("."):
            schoon = schoon.replace(".", "").replace(",", ".")
        else:
            schoon = schoon.replace(",", "")
    elif "," in schoon:
        delen = schoon.split(",")
        # "1,234,567" (meerdere komma's) = duizendtallen; "4200,50" = decimaal.
        schoon = "".join(delen) if len(delen) > 2 else f"{delen[0]}.{delen[1]}"
    elif "." in schoon:
        delen = schoon.split(".")
        # Alleen punten: "4.200"/"1.234.567" (groepen van 3) = duizendtal, "4200.5" = decimaal.
        if len(delen) > 2 or (len(delen) == 2 and len(delen[1]) == 3 and delen[0].lstrip("-").isdigit()):
            schoon = "".join(delen)
    try:
        return Decimal(schoon)
    except InvalidOperation:
        return None


_EENHEID_PATRONEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("m2", re.compile(r"(?i)(m\s*[²2]\b|vierkante\s*meter|\bm2\b)")),
    ("m1", re.compile(r"(?i)(m\s*[¹1]\b|strekkende|\bm1\b|\bmeter\b|\bm\b)")),
    ("stuks", re.compile(r"(?i)(\bst(uk|uks|\.)?\b|\bpcs?\b)")),
    ("manuren", re.compile(r"(?i)(man)?u(u)?r(en)?\b|\bh\b|\bhr\b")),
)


def map_eenheid(eenheid_tekst: str | None) -> str | None:
    """AI-eenheid zoals die in het contract staat → één van de vier meerwerk-eenheden (m2/m1/stuks/
    manuren), deterministisch; None = niet herkend (regel wordt zichtbaar 'ongeldig', nooit gegokt).
    "m²/week" → m2 (huur per m² per week is een m²-prijs), "m¹" → m1, "per stuk" → stuks, "uur" → manuren."""
    tekst = (eenheid_tekst or "").strip()
    if not tekst:
        return None
    for code, patroon in _EENHEID_PATRONEN:
        if patroon.search(tekst):
            return code
    return None


@dataclass(frozen=True)
class DoorlopendeHuurAfleiding:
    bedrag: Decimal
    per: str  # "week" of "m² per week"
    vanaf_week: int
    bron: str  # het citaat/de tekst waaruit afgeleid

    @property
    def omschrijving(self) -> str:
        bedrag = f"{self.bedrag:f}".rstrip("0").rstrip(".") if "." in f"{self.bedrag:f}" else f"{self.bedrag:f}"
        return (
            f"€ {bedrag.replace('.', ',')} per {self.per} vanaf week {self.vanaf_week} "
            f"(afgeleid uit staffel: {self.bron})"
        )


_HUUR_BEDRAG = re.compile(
    r"(?i)€?\s*(?P<bedrag>\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?:,-|,–)?\s*"
    r"(?:per|/|p\.|p/)\s*(?P<m2>m\s*[²2]\s*(?:per|/|p\.|p/)\s*)?(?:week|wk)\b"
)
_HUUR_WEKEN = re.compile(
    r"(?i)(?:uitgaande\s+van|op\s+basis\s+van|gebaseerd\s+op|na|ná|vanaf|eerste|inbegrepen|inclusief|incl\.?)"
    r"\s*(?:de\s+)?(?:eerste\s+)?(?P<weken>\d{1,3})\s*(?:weken|wkn?|week)"
)


def leid_doorlopende_huur_af(teksten: list[str]) -> DoorlopendeHuurAfleiding | None:
    """Deterministische afleiding uit een huurstaffel: "€ 150/week uitgaande van 9 weken" →
    € 150 per week vanaf week 10. Zoekt in elke tekst (citaat, of omschrijving+waarde+eenheid) naar een
    week-tarief én een uitgangsperiode in weken; beide nodig, eerste treffer wint, anders None.
    Geen AI-rekenwerk: N+1 is code."""
    for tekst in teksten:
        if not tekst:
            continue
        bedrag_m = _HUUR_BEDRAG.search(tekst)
        weken_m = _HUUR_WEKEN.search(tekst)
        if bedrag_m is None or weken_m is None:
            continue
        bedrag = parse_getal(bedrag_m.group("bedrag"))
        weken = int(weken_m.group("weken"))
        if bedrag is None or bedrag <= 0 or weken <= 0:
            continue
        return DoorlopendeHuurAfleiding(
            bedrag=bedrag,
            per="m² per week" if bedrag_m.group("m2") else "week",
            vanaf_week=weken + 1,
            bron=tekst.strip(),
        )
    return None


# --- AI-aanroep -----------------------------------------------------------------------------------


def _normaliseer(data: dict[str, Any]) -> ContractOntleding:
    ruwe_kop = data.get("kop") if isinstance(data.get("kop"), dict) else {}
    kop = ContractKop(
        soort_werk=_als_tekst(ruwe_kop.get("soort_werk")),
        soort_werk_citaat=_als_tekst(ruwe_kop.get("soort_werk_citaat")),
        contract_m2=_als_tekst(ruwe_kop.get("contract_m2")),
        contract_m2_citaat=_als_tekst(ruwe_kop.get("contract_m2_citaat")),
        doorlopende_huur_na=_als_tekst(ruwe_kop.get("doorlopende_huur_na")),
        doorlopende_huur_na_citaat=_als_tekst(ruwe_kop.get("doorlopende_huur_na_citaat")),
    )
    regels: list[ContractRegel] = []
    for ruw in data.get("regels") or []:
        if not isinstance(ruw, dict) or ruw.get("soort") not in _REGEL_SOORTEN:
            continue
        omschrijving = _als_tekst(ruw.get("oms"))
        if not omschrijving:
            continue
        zekerheid = ruw.get("z")
        regels.append(
            ContractRegel(
                soort=str(ruw["soort"]),
                omschrijving=omschrijving,
                citaat=_als_tekst(ruw.get("citaat")),
                waarde=_als_tekst(ruw.get("waarde")),
                eenheid=_als_tekst(ruw.get("eenheid")),
                van=_als_tekst(ruw.get("van")),
                tot=_als_tekst(ruw.get("tot")),
                zekerheid=min(max(float(zekerheid) if isinstance(zekerheid, int | float) else 0.0, 0.0), 1.0),
            )
        )
    return ContractOntleding(kop=kop, regels=regels)


def extraheer_contract(
    pdf_bytes: bytes,
    *,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
) -> ContractOntleding:
    """Stuurt het contract/de offerte naar Claude en normaliseert het resultaat (sentinels → None).
    Eén aanroep; een afgekapte respons is een zichtbare fout."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=CONTRACT_SCHEMA
    )
    if antwoord.afgekapt:
        raise AiExtractieFout(
            "De contract-ontleding werd afgekapt (max_tokens) — probeer opnieuw of vul handmatig in."
        )
    return _normaliseer(antwoord.data or {})
