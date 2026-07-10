from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.extractie.client import AiExtractieFout, ClaudeExtractieClient
from app.extractie.service import (
    FACTUUR_SCHEMA,
    KOP_SCHEMA,
    OPDRACHT,
    REGELS_SCHEMA,
    SYSTEM_PROMPT,
    extraheer_inkoopfactuur,
)

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
        usage=SimpleNamespace(input_tokens=100, output_tokens=10),
    )


class _FakeStream:
    """Nabootsing van de streaming-contextmanager van de SDK: de client gebruikt
    `messages.stream(...)` + `get_final_message()` (timeout-fix 2026-07-10). Een optionele
    `fout` gooit bij het openen — zoals een APITimeoutError uit de SDK dat doet."""

    def __init__(self, respons: SimpleNamespace, fout: Exception | None = None) -> None:
        self._respons = respons
        self._fout = fout

    def __enter__(self) -> _FakeStream:
        if self._fout is not None:
            raise self._fout
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def get_final_message(self) -> SimpleNamespace:
        return self._respons


class _FakeMessages:
    """Gescript: elke stream()-aanroep consumeert het volgende antwoord — zo zijn chunking-
    scenario's (afkap → kop-call → regel-batches) exact na te spelen. Het laatste antwoord
    blijft herhalen zodat enkelvoudige tests één respons kunnen meegeven."""

    def __init__(self, responsen: list[SimpleNamespace], fout: Exception | None = None) -> None:
        self._responsen = list(responsen)
        self._fout = fout
        self.aanroepen: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.aanroepen.append(kwargs)
        respons = self._responsen.pop(0) if len(self._responsen) > 1 else self._responsen[0]
        return _FakeStream(respons, self._fout)

    @property
    def laatste_kwargs(self) -> dict[str, Any] | None:
        return self.aanroepen[-1] if self.aanroepen else None


class _FakeAnthropic:
    def __init__(self, responsen: list[SimpleNamespace], fout: Exception | None = None) -> None:
        self.messages = _FakeMessages(responsen, fout)


def _client_met(
    *responsen: SimpleNamespace, fout: Exception | None = None
) -> tuple[ClaudeExtractieClient, _FakeMessages]:
    fake = _FakeAnthropic(list(responsen) or [_respons()], fout)
    client = ClaudeExtractieClient(client=fake)  # type: ignore[arg-type]
    return client, fake.messages


# Compact draadformaat (2026-07-10): kop/kz met korte keys, regels als {o,n,b,h,z}.


def _regel(o: str, n: str = "100.00", b: str = "21.00", h: str | None = None, z: float = 0.9) -> dict[str, Any]:
    return {"o": o, "n": n, "b": b, "h": h, "z": z}


def _ruwe_factuur(regels: list[dict[str, Any]] | None = None, **kop_overrides: Any) -> dict[str, Any]:
    kop: dict[str, Any] = {
        "lev": "Bouwmaat Nederland B.V.",
        "nr": "F-001",
        "dat": "2026-07-01",
        "verval": None,
        "val": "EUR",
        "excl": "100.00",
        "incl": "121.00",
        "btw": "21.00",
    }
    kop.update(kop_overrides)
    return {
        "kop": kop,
        "kz": {key: 0.9 for key in kop},
        "regels": regels if regels is not None else [_regel("Materiaal")],
    }


def _kop_only(**kop_overrides: Any) -> dict[str, Any]:
    factuur = _ruwe_factuur(**kop_overrides)
    return {"kop": factuur["kop"], "kz": factuur["kz"]}


class TestClaudeExtractieClient:
    def test_stuurt_pdf_als_document_block_met_schema(self) -> None:
        client, messages = _client_met(_respons(tekst=json.dumps(_ruwe_factuur())))
        pdf = b"%PDF-1.4 test"

        antwoord = client.extraheer_json_uit_pdf(
            pdf_bytes=pdf, system=SYSTEM_PROMPT, opdracht=OPDRACHT, json_schema=FACTUUR_SCHEMA
        )

        assert antwoord.afgekapt is False
        assert antwoord.data is not None and antwoord.data["kop"]["nr"] == "F-001"
        assert antwoord.input_tokens == 100 and antwoord.output_tokens == 10
        kwargs = messages.laatste_kwargs
        assert kwargs is not None
        document_block = kwargs["messages"][0]["content"][0]
        assert document_block["type"] == "document"
        assert document_block["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(document_block["source"]["data"]) == pdf
        assert "cache_control" not in document_block  # enkele call: geen cache-write betalen
        assert kwargs["output_config"]["format"]["schema"] is FACTUUR_SCHEMA
        assert kwargs["system"] == SYSTEM_PROMPT
        # Extractie hoort niet "creatief" te zijn én het model accepteert ze niet: nooit
        # sampling-parameters meesturen.
        assert "temperature" not in kwargs

    def test_cache_document_zet_breakpoint_op_document_block(self) -> None:
        client, messages = _client_met(_respons(tekst="{}"))
        client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={}, cache_document=True)
        document_block = messages.laatste_kwargs["messages"][0]["content"][0]  # type: ignore[index]
        assert document_block["cache_control"] == {"type": "ephemeral"}

    def test_afkap_is_signaal_geen_fout(self) -> None:
        # Groottevrij-besluit: stop_reason=max_tokens is het chunking-signaal, geen exception.
        client, _ = _client_met(_respons(stop_reason="max_tokens"))
        antwoord = client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})
        assert antwoord.afgekapt is True
        assert antwoord.data is None
        assert antwoord.input_tokens == 100  # tokenmeting ook bij afkap

    def test_timeout_wordt_uitlegbare_fout_met_herstelhint(self) -> None:
        import anthropic
        import httpx

        timeout = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        client, _ = _client_met(_respons(), fout=timeout)
        with pytest.raises(AiExtractieFout, match="timeout.*Opnieuw extraheren"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_refusal_wordt_uitlegbare_fout(self) -> None:
        client, _ = _client_met(_respons(stop_reason="refusal", content=[]))
        with pytest.raises(AiExtractieFout, match="refusal"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_respons_zonder_tekstblok_wordt_fout(self) -> None:
        client, _ = _client_met(_respons(content=[SimpleNamespace(type="thinking", text=None)]))
        with pytest.raises(AiExtractieFout, match="tekstblok"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})

    def test_ongeldige_json_wordt_fout(self) -> None:
        client, _ = _client_met(_respons(tekst="dit is geen json"))
        with pytest.raises(AiExtractieFout, match="JSON"):
            client.extraheer_json_uit_pdf(pdf_bytes=b"x", system="s", opdracht="o", json_schema={})


class TestExtraheerInkoopfactuurEnkeleCall:
    def test_normaliseert_kop_en_regels(self) -> None:
        client, _ = _client_met(_respons(tekst=json.dumps(_ruwe_factuur())))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        # Compact draadformaat → volledige interne veldnamen.
        assert extractie.kop["factuurnummer"].waarde == "F-001"
        assert extractie.kop["leverancier_naam"].waarde == "Bouwmaat Nederland B.V."
        assert extractie.kop["vervaldatum"].waarde is None
        assert len(extractie.regels) == 1
        assert extractie.regels[0].netto_bedrag == "100.00"
        assert extractie.regels[0].zekerheid == 0.9
        assert extractie.volledig is True
        assert extractie.bsn_verwijderd == 0
        assert extractie.metriek is not None
        assert extractie.metriek.aanroepen == 1
        assert extractie.metriek.chunked is False
        assert extractie.metriek.input_tokens == 100

    def test_zekerheid_wordt_geclampt_op_0_tot_1(self) -> None:
        ruw = _ruwe_factuur(regels=[_regel("Materiaal", z=1.7)])
        ruw["kz"]["incl"] = -0.3
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.regels[0].zekerheid == 1.0
        assert extractie.kop["totaal_incl"].zekerheid == 0.0

    def test_bsn_postfilter_verwijdert_ook_wat_de_prompt_doorlaat(self) -> None:
        # 111222333 doorstaat de elfproef — mocht het model de prompt-instructie negeren, dan
        # haalt de deterministische tweede linie het alsnog weg vóór persistentie.
        ruw = _ruwe_factuur(regels=[_regel("Uren week 27, BSN 111222333, J. Jansen")])
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert "111222333" not in (extractie.regels[0].omschrijving or "")
        assert extractie.bsn_verwijderd == 1

    def test_factuurnummer_dat_elfproef_doorstaat_blijft_ongemoeid(self) -> None:
        # Fix 2026-07-10 (Peters controle, 20260064.pdf): het BSN-filter draait nooit op
        # gestructureerde velden — een 9-cijferig factuurnummer dat toevallig de elfproef
        # doorstaat (111222333) blijft exact zoals gelezen.
        ruw = _ruwe_factuur()
        ruw["kop"]["nr"] = "111222333"
        ruw["regels"] = [_regel("Steigerhuur week 27", n="111222333")]  # ook bedragvelden nooit
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.kop["factuurnummer"].waarde == "111222333"
        assert extractie.regels[0].netto_bedrag == "111222333"
        assert extractie.bsn_verwijderd == 0

    def test_defensief_tegen_rare_vormen(self) -> None:
        ruw = _ruwe_factuur(regels=[{"o": "ok"}, "geen dict"])  # incomplete + kapotte regel
        ruw["kop"]["nr"] = 12345  # verkeerd type
        ruw["kz"]["nr"] = "hoog"
        client, _ = _client_met(_respons(tekst=json.dumps(ruw)))
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.kop["factuurnummer"].waarde == "12345"
        assert extractie.kop["factuurnummer"].zekerheid == 0.0
        assert len(extractie.regels) == 1
        assert extractie.regels[0].netto_bedrag is None


class TestAdaptieveChunking:
    def test_afkap_schakelt_over_op_chunked_en_merge_behoudt_volgorde(self) -> None:
        # Script: volle poging kapt af → kop-call → 25 regels → 25 regels → laatste blok van 3.
        batch1 = [_regel(f"regel {i}") for i in range(1, 26)]
        batch2 = [_regel(f"regel {i}") for i in range(26, 51)]
        batch3 = [_regel(f"regel {i}") for i in range(51, 54)]
        client, messages = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps(_kop_only())),
            _respons(tekst=json.dumps({"regels": batch1})),
            _respons(tekst=json.dumps({"regels": batch2})),
            _respons(tekst=json.dumps({"regels": batch3})),
        )

        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)

        assert extractie.volledig is True
        assert extractie.kop["factuurnummer"].waarde == "F-001"
        assert len(extractie.regels) == 53
        assert [r.omschrijving for r in extractie.regels] == [f"regel {i}" for i in range(1, 54)]
        assert extractie.metriek is not None
        assert extractie.metriek.aanroepen == 5
        assert extractie.metriek.chunked is True
        # Vervolgcalls: kop + regels met prompt-cache op het document-block, en de juiste schema's.
        schemas = [aanroep["output_config"]["format"]["schema"] for aanroep in messages.aanroepen]
        assert schemas == [FACTUUR_SCHEMA, KOP_SCHEMA, REGELS_SCHEMA, REGELS_SCHEMA, REGELS_SCHEMA]
        for aanroep in messages.aanroepen[1:]:
            assert aanroep["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # Indexvensters in de opdrachten: 1-25, 26-50, 51-75.
        assert "1 tot en met 25" in messages.aanroepen[2]["messages"][0]["content"][1]["text"]
        assert "26 tot en met 50" in messages.aanroepen[3]["messages"][0]["content"][1]["text"]
        assert "51 tot en met 75" in messages.aanroepen[4]["messages"][0]["content"][1]["text"]

    def test_naad_ontdubbeling_bij_dubbel_geleverde_grensregel(self) -> None:
        batch1 = [_regel(f"regel {i}") for i in range(1, 26)]
        # Model herhaalt regel 25 als eerste van het tweede blok — exact dubbel op de naad.
        batch2 = [_regel("regel 25")] + [_regel(f"regel {i}") for i in range(26, 30)]
        client, _ = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps(_kop_only())),
            _respons(tekst=json.dumps({"regels": batch1})),
            _respons(tekst=json.dumps({"regels": batch2})),
        )

        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)

        assert extractie.volledig is True
        assert [r.omschrijving for r in extractie.regels] == [f"regel {i}" for i in range(1, 30)]

    def test_regelblok_dat_afkapt_halveert_de_batch(self) -> None:
        # Eerste regel-call (blok van 25) kapt af → zelfde blok opnieuw met 12 → 12 regels →
        # laatste blok. Geen handmatige drempel: het schaalt vanzelf mee.
        batch_12 = [_regel(f"regel {i}") for i in range(1, 13)]
        rest = [_regel(f"regel {i}") for i in range(13, 15)]
        client, messages = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps(_kop_only())),
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps({"regels": batch_12})),
            _respons(tekst=json.dumps({"regels": rest})),
        )

        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)

        assert extractie.volledig is True
        assert len(extractie.regels) == 14
        # Na de afkap vraagt hij hetzelfde startpunt opnieuw, met een gehalveerd venster.
        assert "1 tot en met 25" in messages.aanroepen[2]["messages"][0]["content"][1]["text"]
        assert "1 tot en met 12" in messages.aanroepen[3]["messages"][0]["content"][1]["text"]

    def test_afkap_op_minimumblok_geeft_onvolledig(self) -> None:
        # Elke regel-call kapt af: 25 → 12 → 6 → 5 (minimum) → nog steeds afkap → opgeven.
        client, _ = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps(_kop_only())),
            _respons(stop_reason="max_tokens"),
        )

        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)

        assert extractie.volledig is False
        assert extractie.regels == []
        assert extractie.kop["factuurnummer"].waarde == "F-001"  # kop is er wél

    def test_kop_call_die_afkapt_geeft_onvolledig(self) -> None:
        client, _ = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(stop_reason="max_tokens"),
        )
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.volledig is False
        assert extractie.regels == []

    def test_tokens_worden_over_alle_aanroepen_opgeteld(self) -> None:
        client, _ = _client_met(
            _respons(stop_reason="max_tokens"),
            _respons(tekst=json.dumps(_kop_only())),
            _respons(tekst=json.dumps({"regels": [_regel("enige regel")]})),
        )
        extractie = extraheer_inkoopfactuur(b"%PDF-1.4", client=client)
        assert extractie.metriek is not None
        assert extractie.metriek.aanroepen == 3
        assert extractie.metriek.input_tokens == 300
        assert extractie.metriek.output_tokens == 30


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

        for schema in (FACTUUR_SCHEMA, KOP_SCHEMA, REGELS_SCHEMA):
            controleer(schema)
