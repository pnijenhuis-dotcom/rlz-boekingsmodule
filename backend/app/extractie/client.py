from __future__ import annotations

import base64
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import anthropic

from app.aikosten.service import AiVerbruikReferentie, controleer_poort, registreer_verbruik
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaudeAntwoord:
    """Eén Claude-aanroep, mét tokenmeting. `afgekapt=True` (stop_reason=max_tokens) is géén
    exception maar een signaal: de aanroeper (app/extractie/service.py) schakelt dan automatisch
    over op chunked extractie. `data` is None bij afkap — de JSON is dan per definitie
    onbruikbaar afgebroken."""

    data: dict[str, Any] | None
    afgekapt: bool
    input_tokens: int
    output_tokens: int


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
        verbruik_referentie: AiVerbruikReferentie | None = None,
    ) -> None:
        self._model = model or settings.ai_extractie_model
        # AI-kostenmeter (besluit 2026-08-14): de referentie (document/intake-bericht + bron)
        # waaronder élke aanroep van deze client-instantie in platform.ai_gebruik landt.
        self._verbruik_referentie = verbruik_referentie
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

    def vraag_json(self, *, system: str, opdracht: str, json_schema: dict[str, Any]) -> ClaudeAntwoord:
        """Tekst in → schema-gevalideerde JSON uit (blok D 28-08: catalogus-normalisatie). Exact
        dezelfde kostenpoort, throttle, verbruiksregistratie en stop_reason-afhandeling als de
        PDF-variant — géén tweede pad om de kostenmeter heen."""
        return self._vraag(
            system=system,
            json_schema=json_schema,
            content=[{"type": "text", "text": opdracht}],
        )

    def extraheer_json_uit_pdf(
        self,
        *,
        pdf_bytes: bytes,
        system: str,
        opdracht: str,
        json_schema: dict[str, Any],
        cache_document: bool = False,
    ) -> ClaudeAntwoord:
        """Stuurt de PDF (base64 document-block) + opdracht naar Claude en geeft het
        schema-gevalideerde JSON-object terug, mét tokenmeting. Een afgekapte respons
        (stop_reason=max_tokens) is een normaal resultaat (`afgekapt=True`) — het signaal voor de
        adaptieve chunking in service.py, geen fout. Elke andere niet-succesvolle uitkomst wordt
        een AiExtractieFout met een uitlegbare melding — nooit een kale SDK-exception richting de
        upload-flow ("niets verdwijnt stil").

        Streamend (Anthropic-aanbeveling voor lange document-requests): een niet-streamende call
        liep in de praktijk tegen de request-timeout aan (2026-07-10, echte factuur op Opus) —
        bij streaming telt de timeout per chunk i.p.v. over de hele respons, en
        `get_final_message()` verzamelt alsnog het complete antwoord, inclusief `stop_reason`.
        Timeouts en connectiefouten retryt de SDK zelf (APITimeoutError ⊂ APIConnectionError,
        gedekt door max_retries).

        `cache_document=True` zet een prompt-cache-breakpoint op het document-block: bij chunked
        extractie sturen alle vervolgcalls exact dezelfde PDF — de kop-call schrijft de cache,
        de regel-calls lezen 'm (~0.1x inputprijs) i.p.v. de PDF telkens opnieuw te betalen. Bij
        een enkele call bewust uit (cache-write kost 1.25x zonder her-gebruik)."""
        document_block: dict[str, Any] = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(pdf_bytes).decode(),
            },
        }
        if cache_document:
            document_block["cache_control"] = {"type": "ephemeral"}
        return self._vraag(
            system=system, json_schema=json_schema, content=[document_block, {"type": "text", "text": opdracht}]
        )

    def _vraag(self, *, system: str, json_schema: dict[str, Any], content: list[dict[str, Any]]) -> ClaudeAntwoord:
        # Harde kostenpoort (besluit 2026-08-14) vóór élke AI-call — hier in de client zodat geen
        # enkel aanroeppad (inkoop, rapport, splitsing, normalisatie, ook individuele chunk-calls)
        # eromheen kan. AiKostenLimietBereikt/AiKostenModelOnbekend propageren naar de aanroeper,
        # die het document zichtbaar op het handmatige pad zet ("niets verdwijnt stil").
        controleer_poort(model=self._model)
        _THROTTLE.wacht()
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=settings.ai_extractie_max_tokens,
                system=system,
                output_config={"format": {"type": "json_schema", "schema": json_schema}},
                messages=[{"role": "user", "content": content}],
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APITimeoutError as exc:
            raise AiExtractieFout(
                f"Claude API-timeout na {settings.ai_extractie_timeout_seconds:.0f}s (na SDK-retries) — "
                "probeer het opnieuw via 'Opnieuw extraheren' of vul handmatig in."
            ) from exc
        except anthropic.APIError as exc:
            raise AiExtractieFout(f"Claude API-fout: {exc}") from exc

        usage = response.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cache_schrijf_tokens = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_lees_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)

        # Kostenmeter: élke gedane aanroep wordt gelogd met de wérkelijke usage — vóór elke
        # branch (ook afkap en refusal kosten tokens). Faalt de registratie, dan propageert dat
        # als zichtbare fout: liever een mislukte extractie dan een ongemeten call.
        registreer_verbruik(
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_schrijf_tokens=cache_schrijf_tokens,
            cache_lees_tokens=cache_lees_tokens,
            referentie=self._verbruik_referentie,
        )

        if response.stop_reason == "refusal":
            raise AiExtractieFout("Claude weigerde dit document te verwerken (stop_reason=refusal).")
        if response.stop_reason == "max_tokens":
            logger.info(
                "AI-extractie afgekapt (model=%s, in=%s uit=%s tokens) — chunking neemt het over",
                response.model,
                input_tokens,
                output_tokens,
            )
            return ClaudeAntwoord(data=None, afgekapt=True, input_tokens=input_tokens, output_tokens=output_tokens)

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
            "AI-extractie-aanroep gelukt (model=%s, in=%s uit=%s tokens)",
            response.model,
            input_tokens,
            output_tokens,
        )
        return ClaudeAntwoord(data=resultaat, afgekapt=False, input_tokens=input_tokens, output_tokens=output_tokens)
