from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.extractie.client import AiExtractieFout, ClaudeExtractieClient
from app.extractie.service import FACTUUR_SCHEMA, OPDRACHT, SYSTEM_PROMPT, extraheer_inkoopfactuur

# --- gemockte Claude-API (geen echte calls in de kale suite) -----------------------------------


def _respons(
    *, stop_reason: str = "end_turn", content: list[Any] | None = None, tekst: str | None = None
) -> SimpleNamespace:
    if content is None:
        content = [SimpleNamespace(type="text", text=tekst if tekst is not None else "{}")]
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        model="claude-test",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


class _FakeMessages:
    def __init__(self, respons: SimpleNamespace) -> None:
        self._respons = respons
        self.laatste_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.laatste_kwargs = kwargs
        return self._respons


class _FakeAnthropic:
    def __init__(self, respons: SimpleNamespace) -> None:
        self.messages = _FakeMessages(respons)


def _client_met(respons: SimpleNamespace) -> tuple[ClaudeExtractieClient, _FakeMessages]:
    fake = _FakeAnthropic(respons)
    client = ClaudeExtractieClient(client=fake)  # type: ignore[arg-type]
    return client, fake.messages


def _ruw_veld(waarde: str | None, zekerheid: float = 0.9) -> dict[str, Any]:
    return {"waarde": waarde, "zekerheid": zekerheid}


def _ruwe_factuur(**overrides: Any) -> dict[str, Any]:
    basis: dict[str, Any] = {
        "leverancier_naam": _ruw_veld("Bouwmaat Nederland B.V."),
        "factuurnummer": _ruw_veld("F-001"),
        "factuurdatum": _ruw_veld("2026-07-01"),
        "vervaldatum": _ruw_veld(None),
        "valuta": _ruw_veld("EUR"),
        "totaal_excl": _ruw_veld("100.00"),
        "totaal_incl": _ruw_veld("121.00"),
        "btw_bedrag": _ruw_veld("21.00"),
        "regels": [
            {
                "omschrijving": _ruw_veld("Materiaal"),
                "netto_bedrag": _ruw_veld("100.00"),
                "btw_bedrag": _ruw_veld("21.00"),
                "hoeveelheid": _ruw_veld(None),
            }
        ],
    }
    basis.update(overrides)
    return basis


class TestClaudeExtractieClient:
    def test_stuurt_pdf_als_document_block_met_schema(self) -> None:
        client, messages = _client_met(_respons(tekst=json.dumps(_ruwe_factuur())))
        pdf = b"%PDF-1.4 test"

        resultaat = client.extraheer_json_uit_pdf(
            pdf_bytes=pdf, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=FACTUUR_SCHEMA
        )

        assert resultaat["factuurnummer"]["waarde"] == "F-001"
        kwargs = messages.laatste_kwargs
        assert kwargs is not None
        document_block = kwargs["messages"][0]["content"][0]
        assert document_block["type"] == "document"
        assert document_block["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(document_block["source"]["data"]) == pdf
        assert kwargs["output_config"]["format"]["schema"] is FACTUUR_SCHEMA
        assert kwargs["system"] == SYSTEM_PROMPT
        # Extractie hoort niet "creatief" te zijn én het model accepteert ze niet: nooit
        # sampling-parameters meesturen.
        assert "temperature" not in kwargs

    def test_refusal_wordt_uitlegbare_fout(self) -> None:
        client, _ = _client_met(_respons(stop_reason="refusal", content=[]))
        with pytest.raises(AiExtractieFout, match="refusal"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_afgekapte_respons_wordt_uitlegbare_fout(self) -> None:
        client, _ = _client_met(_respons(stop_reason="max_tokens"))
        with pytest.raises(AiExtractieFout, match="max_tokens"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_respons_zonder_tekstblok_wordt_fout(self) -> None:
        client, _ = _client_met(_respons(content=[SimpleNamespace(type="thinking", text=None)]))
        with pytest.raises(AiExtractieFout, match="tekstblok"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_ongeldige_json_wordt_fout(self) -> None:
        client, _ = _client_met(_respons(tekst="dit is geen json"))
        with pytest.raises(AiExtractieFout, match="JSON"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})


class TestExtraheerInkoopfactuur:
    def test_normaliseert_kop_en_regels(self) -> None:
        client, _ = _client_met(_respons(tekst=json.dumps(_ruwe_factuur())))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.kop["factuurnummer"].waarde == "F-001"
        assert extractie.kop["vervaldatum"].waarde is None
        assert len(extractie.regels) == 1
        assert extractie.regels[0].netto_bedrag.waarde == "100.00"
        assert extractie.bsn_verwijderd == 0

    def test_zekerheid_wordt_geclampt_op_0_tot_1(self) -> None:
        ruw = _ruwe_factuur(
            factuurnummer={"waarde": "F-001", "zekerheid": 1.7},
            totaal_incl={"waarde": "121.00", "zekerheid": -0.3},
        )
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.kop["factuurnummer"].zekerheid == 1.0
        assert extractie.kop["totaal_incl"].zekerheid == 0.0

    def test_bsn_postfilter_verwijdert_ook_wat_de_prompt_doorlaat(self) -> None:
        # 111222333 doorstaat de elfproef — mocht het model de prompt-instructie negeren, dan
        # haalt de deterministische tweede linie het alsnog weg vóór persistentie.
        ruw = _ruwe_factuur()
        ruw["regels"][0]["omschrijving"] = _ruw_veld("Uren week 27, BSN 111222333, J. Jansen")
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert "111222333" not in (extractie.regels[0].omschrijving.waarde or "")
        assert extractie.bsn_verwijderd == 1

    def test_defensief_tegen_rare_vormen(self) -> None:
        ruw = _ruwe_factuur(
            factuurnummer={"waarde": 12345, "zekerheid": "hoog"},  # verkeerde typen
            regels=[{"omschrijving": _ruw_veld("ok")}, "geen dict"],  # incomplete + kapotte regel
        )
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.kop["factuurnummer"].waarde == "12345"
        assert extractie.kop["factuurnummer"].zekerheid == 0.0
        assert len(extractie.regels) == 1
        assert extractie.regels[0].netto_bedrag.waarde is None


class TestFactuurSchema:
    def test_alle_objecten_verbieden_extra_properties(self) -> None:
        """Structured outputs vereisen additionalProperties: False op elk object — een stille
        schema-fout zou pas bij de eerste echte API-call opduiken."""

        def controleer(schema: dict) -> None:
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert set(schema.get("required", [])) == set(schema.get("properties", {}))
                for sub in schema["properties"].values():
                    controleer(sub)
            if schema.get("type") == "array":
                controleer(schema["items"])

        controleer(FACTUUR_SCHEMA)
