"""Blok 9 vervolgrun 07-09: nieuw kopveld `betreft` (betreft-/onderwerpregel van de factuur) in FACTUUR_SCHEMA én
KOP_SCHEMA — sentinel-string volgens de union-limiet-regel (bugfix 31-08: `""` = onbekend → None, nooit
nullable/union), vrije tekst dus achter het BSN-filter. De kop-omschrijving zelf wordt deterministisch afgeleid in
app/documenten/kop_omschrijving.py — hier alleen het voorlezen."""

from __future__ import annotations

import json

from app.extractie.service import FACTUUR_SCHEMA, KOP_SCHEMA, OPDRACHT, OPDRACHT_KOP, SYSTEM_PROMPT, extraheer_inkoopfactuur
from app.extractie.schema_poort import tel_union_parameters
from tests.extractie.test_service import _client_met, _regel, _respons, _ruwe_factuur

BETREFT = "Betreft: huur steigermateriaal project 26123 week 34"


def test_betreft_staat_als_sentinel_string_in_beide_kopschema_s() -> None:
    for schema in (FACTUUR_SCHEMA, KOP_SCHEMA):
        kop = schema["properties"]["kop"]
        assert kop["properties"]["betreft"] == {"type": "string"}  # geen union/nullable
        assert "betreft" in kop["required"]
        assert "betreft" in schema["properties"]["kz"]["properties"]
    assert tel_union_parameters(FACTUUR_SCHEMA) == 0 and tel_union_parameters(KOP_SCHEMA) == 0


def test_prompt_en_opdrachten_vragen_om_de_betreft_regel() -> None:
    assert "betreft=" in SYSTEM_PROMPT
    assert "betreft" in OPDRACHT and "betreft" in OPDRACHT_KOP


def test_betreft_wordt_voorgelezen_en_sentinel_wordt_none() -> None:
    ruw = _ruwe_factuur(regels=[_regel("Huur lift"), _regel("Transport")], betreft=f"  {BETREFT} ")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    assert extractie.kop["betreft"].waarde == BETREFT
    assert extractie.kop["betreft"].zekerheid == 0.9

    ruw = _ruwe_factuur(betreft="")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    assert extractie.kop["betreft"].waarde is None


def test_betreft_is_vrije_tekst_dus_bsn_filter() -> None:
    ruw = _ruwe_factuur(betreft="Betreft: uren J. Jansen, BSN 111222333")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    assert "111222333" not in (extractie.kop["betreft"].waarde or "")
    assert extractie.bsn_verwijderd >= 1
