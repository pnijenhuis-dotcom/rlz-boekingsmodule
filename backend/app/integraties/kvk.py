"""KvK Basisprofiel-API — bedrijfsgegevens ophalen op KvK-nummer voor het ZZP-dossier (A3,
steigerbouw-run 25-08). Eigen kopie van het Vastly-client-patroon
(Vastgoed software/src/layer2_integraties/kvk.py): officiële API, `apikey`-header,
test-omgeving als dev-default (KvK's publieke testsleutel, fictieve data), productie via
KVK_API_KEY + KVK_BASE_URL uit Secret Manager/.env (nooit in code of git).

Officiële bron: https://developers.kvk.nl/documentation — GET {base}/basisprofielen/{kvkNummer}.
Veldpaden geverifieerd door Vastly tegen een live test-respons (kvkNummer 68750110):
- naam: top-level `naam`, fallback `handelsnamen[0].naam`, dan `statutaireNaam`;
- rechtsvorm: `_embedded.eigenaar.rechtsvorm` (vrije tekst, hier onvertaald doorgegeven);
- adres/plaats: `_embedded.hoofdvestiging.adressen[]` type bezoekadres, anders
  correspondentieadres zonder postbus; AVG: `indAfgeschermd == "Ja"` → geen adres;
- uitgeschreven: `materieleRegistratie.datumEinde` gevuld → expliciet gesignaleerd.

Deterministisch, geen LLM. Een mens BEVESTIGT altijd (mockup meerwerk-kantoor: "Opgehaald via
KvK-API — bevestigen"); de lookup zelf schrijft niets weg."""

from __future__ import annotations

import time

import httpx

from app.config import settings

_TEST_BASE = "https://api.kvk.nl/test/api/v1/basisprofielen"
_TEST_API_KEY = "l7xx1f2691f2520d487b902f4e0b57a0b197"  # KvK's eigen publieke testsleutel, fictieve data
_TIMEOUT = 10.0
_MAX_RETRIES = 3


class KvkFout(Exception):
    pass


class KvkConfiguratieFout(KvkFout):
    """Sleutel en base-URL komen niet uit dezelfde omgeving (test vs. productie) — de les uit
    het Vastly-productie-incident 18-08 (productiesleutel tegen de test-URL = stille 401)."""


def _base_url() -> str:
    return settings.kvk_base_url or _TEST_BASE


def _api_key() -> str:
    return settings.kvk_api_key or _TEST_API_KEY


def is_testomgeving() -> bool:
    return "/test/" in _base_url()


def config_probleem() -> str | None:
    url_is_test = is_testomgeving()
    key_is_test = _api_key() == _TEST_API_KEY
    if key_is_test == url_is_test:
        return None
    if url_is_test:
        return (
            "KvK-configuratiefout: KVK_API_KEY is gezet (eigen sleutel) maar KVK_BASE_URL ontbreekt of wijst "
            "naar de testomgeving — zet KVK_BASE_URL op https://api.kvk.nl/api/v1/basisprofielen."
        )
    return "KvK-configuratiefout: KVK_BASE_URL wijst naar productie maar er is geen eigen KVK_API_KEY."


def geldig_kvk_nummer(nummer: str) -> bool:
    return len(nummer) == 8 and nummer.isdigit()


def _formatteer_datum(waarde: object) -> str:
    s = str(waarde)
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}-{s[4:6]}-{s[0:4]}"
    return s


def _kies_adres(adressen: list[dict]) -> dict | None:
    bezoek = next((a for a in adressen if a.get("type") == "bezoekadres"), None)
    if bezoek is not None:
        return bezoek
    correspondentie = next((a for a in adressen if a.get("type") == "correspondentieadres"), None)
    if correspondentie is not None and not correspondentie.get("postbusnummer"):
        return correspondentie
    return None


def _doe_request(kvk_nummer: str, headers: dict) -> httpx.Response:
    laatste_fout: KvkFout | None = None
    for poging in range(_MAX_RETRIES):
        try:
            resp = httpx.get(f"{_base_url()}/{kvk_nummer}", headers=headers, timeout=_TIMEOUT)
        except httpx.RequestError as e:
            raise KvkFout(f"KvK niet bereikbaar: {e}") from e
        if resp.status_code == 429:
            laatste_fout = KvkFout("KvK rate limit (429) — herhaaldelijk geraakt na retries")
            time.sleep(float(resp.headers.get("Retry-After", 2**poging)))
            continue
        return resp
    assert laatste_fout is not None
    raise laatste_fout


def verwerk_basisprofiel(body: object) -> dict | None:
    """Pure parser (testbaar zonder netwerk): KvK-respons → {naam, rechtsvorm, adres, postcode,
    plaats, uitgeschreven, datum_einde} — ontbrekende velden ontbreken, nooit None-gevuld."""
    if not isinstance(body, dict):
        raise KvkFout("Onverwachte KvK-respons (schema-afwijking?): body is geen object")
    resultaat: dict = {}
    naam = (
        body.get("naam")
        or next(
            (h.get("naam") for h in (body.get("handelsnamen") or []) if isinstance(h, dict) and h.get("naam")), None
        )
        or body.get("statutaireNaam")
    )
    if naam:
        resultaat["naam"] = naam
    eigenaar = (body.get("_embedded") or {}).get("eigenaar") or {}
    if isinstance(eigenaar, dict) and eigenaar.get("rechtsvorm"):
        resultaat["rechtsvorm"] = str(eigenaar["rechtsvorm"])
    hoofdvestiging = (body.get("_embedded") or {}).get("hoofdvestiging") or {}
    adressen = hoofdvestiging.get("adressen") if isinstance(hoofdvestiging, dict) else None
    if isinstance(adressen, list):
        gekozen = _kies_adres([a for a in adressen if isinstance(a, dict)])
        if gekozen is not None and gekozen.get("indAfgeschermd") != "Ja":
            straat, huisnummer = gekozen.get("straatnaam"), gekozen.get("huisnummer")
            if straat and huisnummer is not None:
                resultaat["adres"] = f"{straat} {huisnummer}{gekozen.get('huisnummerToevoeging') or ''}".strip()
            if gekozen.get("postcode"):
                resultaat["postcode"] = gekozen["postcode"]
            if gekozen.get("plaats"):
                resultaat["plaats"] = gekozen["plaats"]
    registratie = body.get("materieleRegistratie")
    if isinstance(registratie, dict) and registratie.get("datumEinde"):
        resultaat["uitgeschreven"] = True
        resultaat["datum_einde"] = _formatteer_datum(registratie["datumEinde"])
    return resultaat or None


def haal_basisprofiel(kvk_nummer: str) -> dict | None:
    """None = niet gevonden (404). Raise-t KvkFout/KvkConfiguratieFout — de router vertaalt."""
    if not geldig_kvk_nummer(kvk_nummer):
        raise KvkFout("Een KvK-nummer bestaat uit precies 8 cijfers")
    probleem = config_probleem()
    if probleem:
        raise KvkConfiguratieFout(probleem)
    resp = _doe_request(kvk_nummer, {"apikey": _api_key(), "Accept": "application/json"})
    if resp.status_code == 404:
        return None
    if not resp.is_success:
        raise KvkFout(f"KvK antwoordde HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise KvkFout(f"Onverwachte KvK-respons (schema-afwijking?): {e}") from e
    return verwerk_basisprofiel(body)
