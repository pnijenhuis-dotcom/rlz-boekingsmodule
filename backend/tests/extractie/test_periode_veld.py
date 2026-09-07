"""Blok 11 vervolgrun 07-09: nieuw kopveld `periode` (de periode waarop de factuur betrekking heeft, letterlijk) in
FACTUUR_SCHEMA én KOP_SCHEMA — sentinel-string volgens de union-limiet-regel (bugfix 31-08: `""` = onbekend → None,
nooit nullable/union). De normalisatie naar ISO-weken is deterministisch (app/documenten/periode.py) — hier alleen het
voorlezen en het doorgeven als `veldvoorstel["periode_tekst"]`."""

from __future__ import annotations

import json

from app.extractie.controle import bouw_veldvoorstel
from app.extractie.schema_poort import tel_union_parameters
from app.extractie.service import FACTUUR_SCHEMA, KOP_SCHEMA, SYSTEM_PROMPT, extraheer_inkoopfactuur
from tests.extractie.test_service import _client_met, _regel, _respons, _ruwe_factuur

PERIODE = "Periode: week 34 t/m 35 2026"


def test_periode_staat_als_sentinel_string_in_beide_kopschema_s() -> None:
    for schema in (FACTUUR_SCHEMA, KOP_SCHEMA):
        kop = schema["properties"]["kop"]
        assert kop["properties"]["periode"] == {"type": "string"}  # geen union/nullable
        assert "periode" in kop["required"]
        assert "periode" in schema["properties"]["kz"]["properties"]
    assert tel_union_parameters(FACTUUR_SCHEMA) == 0 and tel_union_parameters(KOP_SCHEMA) == 0


def test_prompt_vraagt_om_de_letterlijke_periode() -> None:
    assert "periode=" in SYSTEM_PROMPT
    assert "letterlijk" in SYSTEM_PROMPT.split("periode=", 1)[1][:200]


def test_periode_wordt_voorgelezen_en_sentinel_wordt_none() -> None:
    ruw = _ruwe_factuur(regels=[_regel("Huur lift")], periode=f"  {PERIODE} ")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    assert extractie.kop["periode"].waarde == PERIODE
    assert extractie.kop["periode"].zekerheid == 0.9

    ruw = _ruwe_factuur(periode="")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    assert extractie.kop["periode"].waarde is None


def test_controlelaag_geeft_de_ruwe_tekst_door_als_periode_tekst() -> None:
    ruw = _ruwe_factuur(periode=PERIODE)
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
    veldvoorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.5)
    assert veldvoorstel["periode_tekst"] == PERIODE

    ruw = _ruwe_factuur(periode="")
    client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
    veldvoorstel = bouw_veldvoorstel(extraheer_inkoopfactuur(b"%PDF-1.4", client=client), vendors=[], taxrates=[], zekerheid_drempel=0.5)
    assert veldvoorstel["periode_tekst"] is None
