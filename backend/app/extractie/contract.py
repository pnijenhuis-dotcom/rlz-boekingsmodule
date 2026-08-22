"""Contract-/offerte-ontleding voor de projectenmodule (mockup projecten-invoer.html, akkoord
Peter 22-08): de AI leest specs (contract-m², looptijd, huurtijd, doorlopende huur,
opdrachtgever, werknummer), verrekenstaffels en boeteclausules VOOR — mét citaat en
zekerheidsscore per regel. De mens bevestigt per regel (✓/✗); er wordt nooit iets
automatisch overgenomen (app/projecten/ontleding.py schrijft pas bij bevestiging,
deterministisch). Zelfde infra als de andere extracties: ClaudeExtractieClient (streaming,
structured outputs, throttling) mét de AI-kostenpoort ín de client; draait uitsluitend
achter de per-administratie AVG-gate (ai_extractie_ingeschakeld) — zie ontleding.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.aikosten.service import AiVerbruikReferentie
from app.extractie.client import AiExtractieFout, ClaudeExtractieClient

_SOORTEN = (
    "contract_m2",
    "looptijd",
    "huurtijd",
    "doorlopende_huur",
    "opdrachtgever",
    "werknummer",
    "staffel",
    "boete",
)

_STRING_OF_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "soort": {"type": "string", "enum": list(_SOORTEN)},
                    # Korte omschrijving voor de bevestig-regel (bv. "Staffel: trapsteiger").
                    "oms": {"type": "string"},
                    # Letterlijk citaat + vindplaats
                    # (bv. '§4.2 "verrekenbaar tegen € 9,20 per m²"').
                    "citaat": _STRING_OF_NULL,
                    # Soort-afhankelijk: getal/bedrag als string met punt-decimaal ("4200",
                    # "9.20"); bij looptijd ISO-datums in van/tot; bij tekstvelden de tekst.
                    "waarde": _STRING_OF_NULL,
                    "eenheid": _STRING_OF_NULL,  # alleen staffels: de eenheid zoals die er staat
                    "van": _STRING_OF_NULL,  # alleen looptijd (YYYY-MM-DD)
                    "tot": _STRING_OF_NULL,  # alleen looptijd (YYYY-MM-DD)
                    "z": {"type": "number"},
                },
                "required": ["soort", "oms", "citaat", "waarde", "eenheid", "van", "tot", "z"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["regels"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een extractie-assistent voor steigerbouw-contracten en -offertes van een 
administratiekantoor.

Lees uitsluitend voor wat er letterlijk in het document staat. Reken niets uit, leid niets af en vul niets
aan: staat een gegeven er niet (leesbaar) in, laat het dan weg. Een kort voorstel is beter dan een voorstel
dat gokt. Elk voorstel draagt een citaat (letterlijke zinsnede + vindplaats zoals paragraafnummer of pagina)
zodat de controleur het kan verifiëren.

Regelsoorten (alleen deze, antwoord bevat niets anders):
- contract_m2: het gecontracteerde aantal m² steigerwerk (waarde = getal als string, bv. "4200").
- looptijd: de contract-/uitvoeringsperiode (van/tot als YYYY-MM-DD; ontbreekt een kant, geef die als null).
- huurtijd: de in de aanneemsom inbegrepen huurtijd/standtijd (waarde = tekst zoals die er staat, bv. "16 weken").
- doorlopende_huur: het tarief voor doorlopende huur ná de inbegrepen periode (waarde = tekst, bv. "€ 0,42 /m²/week").
- opdrachtgever: de contractuele opdrachtgever (waarde = naam).
- werknummer: het werk-/projectnummer dat de OPDRACHTGEVER hanteert (waarde = nummer zoals vermeld).
- staffel: één verrekenprijs/staffelregel (oms = korte naam van het item, waarde = prijs als string met
  punt-decimaal zonder valutateken, eenheid = de eenheid zoals die er staat, bv. "m²", "m¹/week", "uur").
  Elke verrekenbare prijs is een eigen regel; nulregels/tariefstaffels zonder prijs weglaten.
- boete: een boeteclausule (waarde = bedrag of tekst, oms beschrijft de clausule) — ter info, wordt projectsignaal.

z = één zekerheidsscore tussen 0 en 1 per regel. Notatie: bedragen als string met punt-decimaal zonder
duizendtalscheiding en zonder valutateken; datums als ISO 8601 (YYYY-MM-DD).

Wees zuinig: echo nooit overige documenttekst — alleen de gevraagde regels.

HARDE PRIVACYREGEL (AVG): neem nooit een burgerservicenummer (BSN) of ander persoonsnummer op in je
antwoord. Laat zulke nummers volledig weg; vervang ze in tekstvelden door "[BSN weggelaten]"."""

OPDRACHT = (
    "Ontleed dit contract/deze offerte volgens het schema: specs (contract_m2, looptijd, huurtijd, "
    "doorlopende_huur, opdrachtgever, werknummer), ALLE verrekenstaffels en eventuele boeteclausules. "
    "Alleen voorlezen wat er staat, mét citaat per regel; onbekend of onleesbaar = weglaten."
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


def _als_tekst(waarde: Any) -> str | None:
    if waarde is None:
        return None
    tekst = str(waarde).strip()
    return tekst or None


def extraheer_contract(
    pdf_bytes: bytes,
    *,
    client: ClaudeExtractieClient | None = None,
    verbruik_referentie: AiVerbruikReferentie | None = None,
) -> list[ContractRegel]:
    """Stuurt het contract/de offerte naar Claude en normaliseert het resultaat tot
    voorstel-regels. Eén aanroep; een afgekapte respons is een zichtbare fout."""
    client = client or ClaudeExtractieClient(verbruik_referentie=verbruik_referentie)
    antwoord = client.extraheer_json_uit_pdf(
        pdf_bytes=pdf_bytes, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=CONTRACT_SCHEMA
    )
    if antwoord.afgekapt:
        raise AiExtractieFout(
            "De contract-ontleding werd afgekapt (max_tokens) — probeer opnieuw of vul handmatig in."
        )
    data = antwoord.data or {}
    regels: list[ContractRegel] = []
    for ruw in data.get("regels") or []:
        if not isinstance(ruw, dict) or ruw.get("soort") not in _SOORTEN:
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
    return regels
