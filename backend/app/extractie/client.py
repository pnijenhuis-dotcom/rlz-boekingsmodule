from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


class AiExtractieNietGeconfigureerd(Exception):
    """Geen ANTHROPIC_API_KEY geconfigureerd — AI-extractie is dan niet beschikbaar. Bewust géén
    fallback (besluit 0012-stijl: de key komt uitsluitend uit .env/Secret Manager); de aanroeper
    slaat de extractie zichtbaar over, raadt nooit stil."""


class AiExtractieFout(Exception):
    """De Claude-aanroep faalde ná de SDK-retries, of leverde geen bruikbaar resultaat op."""


class _Throttle:
    """Minimale tussenruimte tussen twee aanroepen, procesbreed (zelfde conventie als de
    per-seconde-gates in de andere koppeling-clients, registers/conventies.md). Retry/backoff op
    429/5xx/connectiefouten zit al in de officiële SDK (max_retries) — dit voorkomt alleen dat we
    zélf in bursts tegen de rate limit aanlopen."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._laatste: float = 0.0

    def wacht(self) -> None:
        with self._lock:
            nu = time.monotonic()
            te_wachten = self._laatste + self._min_interval - nu
            if te_wachten > 0:
                time.sleep(te_wachten)
            self._laatste = time.monotonic()


_THROTTLE = _Throttle(settings.ai_extractie_min_interval_seconds)


class ClaudeExtractieClient:
    """Config-gedreven client voor de Claude API (kern-AI-koppeling,
    Platform/registers/koppelingen.md). Model + key uit settings — nooit hardcoded, key nooit in
    logs/output (besluit 0012). Gebruikt de officiële `anthropic`-SDK: retry/backoff op 429/5xx en
    connectiefouten is ingebouwd; sampling-parameters (temperature e.d.) worden bewust niet
    meegegeven — die accepteert het model niet en extractie hoort sowieso niet "creatief" te zijn.

    `output_config.format` (structured outputs) dwingt af dat de respons valide JSON volgens het
    meegegeven schema is — geen parse-gok over vrije tekst."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._model = model or settings.ai_extractie_model
        if client is not None:
            self._client = client
            return
        key = api_key or settings.anthropic_api_key
        if not key:
            raise AiExtractieNietGeconfigureerd(
                "Geen anthropic_api_key geconfigureerd (backend/.env lokaal, Secret Manager in Cloud Run)."
            )
        self._client = anthropic.Anthropic(
            api_key=key,
            timeout=settings.ai_extractie_timeout_seconds,
            max_retries=3,
        )

    def extraheer_json_uit_pdf(
        self, *, pdf_bytes: bytes, system: str, opdracht: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Stuurt de PDF (base64 document-block) + opdracht naar Claude en geeft het
        schema-gevalideerde JSON-object terug. Elke niet-succesvolle uitkomst wordt een
        AiExtractieFout met een uitlegbare melding — nooit een kale SDK-exception richting de
        upload-flow ("niets verdwijnt stil").

        Streamend (Anthropic-aanbeveling voor lange document-requests): een niet-streamende call
        liep in de praktijk tegen de request-timeout aan (2026-07-10, echte factuur op Opus) —
        bij streaming telt de timeout per chunk i.p.v. over de hele respons, en
        `get_final_message()` verzamelt alsnog het complete antwoord, inclusief `stop_reason`
        voor de max_tokens-afkapdetectie hieronder. Timeouts en connectiefouten retryt de SDK
        zelf (APITimeoutError ⊂ APIConnectionError, gedekt door max_retries)."""
        _THROTTLE.wacht()
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=settings.ai_extractie_max_tokens,
                system=system,
                output_config={"format": {"type": "json_schema", "schema": json_schema}},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                                },
                            },
                            {"type": "text", "text": opdracht},
                        ],
                    }
                ],
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APITimeoutError as exc:
            raise AiExtractieFout(
                f"Claude API-timeout na {settings.ai_extractie_timeout_seconds:.0f}s (na SDK-retries) — "
                "probeer het opnieuw via 'Opnieuw extraheren' of vul handmatig in."
            ) from exc
        except anthropic.APIError as exc:
            raise AiExtractieFout(f"Claude API-fout: {exc}") from exc
        if response.stop_reason == "refusal":
            raise AiExtractieFout("Claude weigerde dit document te verwerken (stop_reason=refusal).")
        if response.stop_reason == "max_tokens":
            raise AiExtractieFout(
                "Claude-respons afgekapt (max_tokens) — document te omvangrijk voor de huidige limiet."
            )
        tekst = next((blok.text for blok in response.content if blok.type == "text"), None)
        if tekst is None:
            raise AiExtractieFout("Claude-respons bevat geen tekstblok.")
        try:
            resultaat = json.loads(tekst)
        except json.JSONDecodeError as exc:
            raise AiExtractieFout(f"Claude-respons is geen geldige JSON: {exc}") from exc
        if not isinstance(resultaat, dict):
            raise AiExtractieFout("Claude-respons is geen JSON-object.")
        logger.info(
            "AI-extractie gelukt (model=%s, in=%s uit=%s tokens)",
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return resultaat
