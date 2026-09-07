"""Extractieveld `proj` op kop- én regelniveau (blok 10 07-09, casus Spot Services): sentinel-string in het
inkoopschema (geen union — unionlimiet-poort blijft groen), normalisatie naar `project_tekst`, en het
veldvoorstel draagt de tekst ruw door (kop + per regel) — matchen doet de prefill, niet de extractie."""

from __future__ import annotations

from app.extractie import controle, service
from app.extractie.schema_poort import ANTHROPIC_UNION_LIMIET, tel_union_parameters


class TestSchema:
    def test_proj_in_kop_en_regels_als_sentinel_string(self) -> None:
        kop = service.FACTUUR_SCHEMA["properties"]["kop"]
        assert kop["properties"]["proj"] == {"type": "string"}
        assert "proj" in kop["required"] and "proj" in service.FACTUUR_SCHEMA["properties"]["kz"]["required"]
        regel = service.FACTUUR_SCHEMA["properties"]["regels"]["items"]
        assert regel["properties"]["proj"] == {"type": "string"}
        assert "proj" in regel["required"]
        assert "proj" in service.KOP_SCHEMA["properties"]["kop"]["properties"]
        assert "proj" in service.REGELS_SCHEMA["properties"]["regels"]["items"]["properties"]

    def test_geen_extra_unions(self) -> None:
        for schema in (service.FACTUUR_SCHEMA, service.KOP_SCHEMA, service.REGELS_SCHEMA):
            assert tel_union_parameters(schema) == 0 <= ANTHROPIC_UNION_LIMIET

    def test_prompt_vraagt_het_projectnummer_van_de_opdrachtgever(self) -> None:
        assert "proj=het projectnummer/werknummer/referentie van de OPDRACHTGEVER" in service.SYSTEM_PROMPT
        assert (
            "proj=het\n  projectnummer/werknummer van de opdrachtgever als dat óp deze regel staat"
            in service.SYSTEM_PROMPT
        )


class TestNormalisatie:
    def test_kop_en_regel_proj_worden_project_tekst(self) -> None:
        uit = service._Genormaliseerd()
        service._normaliseer_kop({"kop": {"proj": " 26140 "}, "kz": {"proj": 0.9}}, uit)
        assert uit.kop["project_tekst"].waarde == "26140" and uit.kop["project_tekst"].zekerheid == 0.9
        service._normaliseer_regels(
            [
                {
                    "o": "Steiger",
                    "n": "100.00",
                    "b": "21.00",
                    "h": "",
                    "e": "",
                    "p": "",
                    "a": "",
                    "proj": "26127",
                    "z": 0.9,
                }
            ],
            uit,
        )
        assert uit.regels[0].project_tekst == "26127"

    def test_lege_sentinel_wordt_none(self) -> None:
        uit = service._Genormaliseerd()
        service._normaliseer_kop({"kop": {"proj": ""}, "kz": {}}, uit)
        assert uit.kop["project_tekst"].waarde is None
        service._normaliseer_regels(
            [{"o": "x", "n": "1", "b": "", "h": "", "e": "", "p": "", "a": "", "proj": "  ", "z": 1}], uit
        )
        assert uit.regels[0].project_tekst is None
        service._normaliseer_regels([{"o": "x", "n": "1", "b": "", "z": 1}], uit)  # oud antwoord zonder proj
        assert uit.regels[1].project_tekst is None


class TestVeldvoorstel:
    def test_project_tekst_kop_en_per_regel_ruw_doorgegeven(self) -> None:
        extractie = service.AiFactuurExtractie(
            kop={"project_tekst": service.AiVeld(waarde="26140", zekerheid=0.9)},
            regels=[
                service.AiRegel(
                    omschrijving="A", netto_bedrag="10.00", btw_bedrag="2.10", hoeveelheid=None, zekerheid=0.9
                ),
                service.AiRegel(
                    omschrijving="B",
                    netto_bedrag="5.00",
                    btw_bedrag="1.05",
                    hoeveelheid=None,
                    zekerheid=0.9,
                    project_tekst="26127",
                ),
            ],
            bsn_verwijderd=0,
        )
        voorstel = controle.bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["project_tekst"] == "26140"
        assert [r["project_tekst"] for r in voorstel["regels"]] == [None, "26127"]
        assert "project_suggestie" not in voorstel  # matchen gebeurt bij de prefill (actuele cache + geheugen)
