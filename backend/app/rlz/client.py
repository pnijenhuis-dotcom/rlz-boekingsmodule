from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

BASE_URL = "https://apps.reeleezee.nl/api/v1"

# Geverifieerde ActionKind-waarden (verkenning/api-verkenning.md, PoC 2 juli 2026).
ACTION_BOOK = 17
ACTION_CORRECT = 19
ACTION_SETTLE = 34
ACTION_DUPLICATE_CHECK = 138


class RlzApiError(Exception):
    """RLZ API gaf een niet-2xx-status die na alle retries nog steeds faalde."""

    def __init__(self, status_code: int, method: str, url: str, body: str) -> None:
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body
        super().__init__(f"{method} {url} -> {status_code}: {body[:500]}")


class RlzRateLimitError(RlzApiError):
    """RLZ gaf 429 (rate limit) — na alle retries structureel geen ruimte meer."""

    def __init__(self, status_code: int, method: str, url: str, body: str, retry_after: float | None) -> None:
        super().__init__(status_code, method, url, body)
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, RlzApiError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _wait_for_rate_limit_or_backoff(retry_state: Any) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RlzRateLimitError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


class RlzClient:
    """HTTP-client voor de Reeleezee REST-API (OData v4), één instantie per webservice-login.

    Een login geeft volledige toegang tot precies de administratie(s) waarvoor hij is aangemaakt
    (geen scopes — behandelen als boekhoudtoegang). Multi-administratie-logins routeren via
    `{adminId}/...`; zie `for_administration`.

    Alle endpoints/velden hieronder zijn geverifieerd tegen de live API — zie
    verkenning/api-verkenning.md. Waar een payload-vorm nog niet geverifieerd is (bv. de exacte
    criteria voor de duplicaatcheck-actie 138), geeft de aanroeper die expliciet mee in plaats
    van dat deze client een veld verzint.
    """

    def __init__(
        self,
        *,
        username: str,
        password: str,
        admin_id: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._admin_id = admin_id
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._client = httpx.Client(
                base_url=base_url,
                headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
                timeout=timeout,
            )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RlzClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def for_administration(self, admin_id: str) -> RlzClient:
        """Zelfde login/verbinding, gescoped op een andere administratie-id."""
        return RlzClient(username="", password="", admin_id=admin_id, client=self._client)

    def _path(self, path: str) -> str:
        path = path.lstrip("/")
        return f"/{self._admin_id}/{path}" if self._admin_id else f"/{path}"

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=_wait_for_rate_limit_or_backoff,
        reraise=True,
    )
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._path(path)
        response = self._client.request(method, url, **kwargs)
        _log_rate_limit_headers(method, url, response)
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            raise RlzRateLimitError(response.status_code, method, url, response.text, retry_after)
        if response.status_code >= 400:
            raise RlzApiError(response.status_code, method, url, response.text)
        return response

    # --- generieke helpers ---------------------------------------------------------------

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params).json()

    def request_raw(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Rauwe response incl. headers — vooral voor het observeren van rate-limit-headers."""
        return self._request(method, path, **kwargs)

    def put(self, path: str, body: dict[str, Any], *, params: dict[str, Any] | None = None) -> httpx.Response:
        return self._request("PUT", path, json=body, params=params)

    def post_action(self, path: str, action_type: int, **extra_body: Any) -> httpx.Response:
        """POST .../Actions {Type: n, ...extra}. n.a.v. verkenning/api-verkenning.md: 17=Book,
        19=Correct, 34=verrekenen, 138=duplicaatcheck (collectie), 15/16=Link/UnlinkPayment."""
        body = {"Type": action_type, **extra_body}
        return self._request("POST", f"{path.rstrip('/')}/Actions", json=body)

    def get_lines(
        self, entity_path: str, entity_id: uuid.UUID | str, *, expand: str = "Account,Project"
    ) -> list[dict[str, Any]]:
        return self.get(f"{entity_path}/{entity_id}/Lines", params={"$expand": expand}).get("value", [])

    # --- domeinspecifieke helpers (geverifieerde payload-vormen) --------------------------

    def list_administrations(self) -> list[dict[str, Any]]:
        return self.get("Administrations").get("value", [])

    def put_vendor(
        self, vendor_id: uuid.UUID, *, name: str, payment_due_days: int | None = None
    ) -> httpx.Response:
        body: dict[str, Any] = {"id": str(vendor_id), "Name": name}
        if payment_due_days is not None:
            body["PaymentDueDays"] = payment_due_days
        return self.put(f"Vendors/{vendor_id}", body)

    def put_purchase_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        vendor_id: uuid.UUID,
        lines: list[dict[str, Any]],
        reference: str | None = None,
        **extra: Any,
    ) -> httpx.Response:
        body: dict[str, Any] = {
            "id": str(invoice_id),
            "Entity": {"id": str(vendor_id)},
            "DocumentLineList": lines,
            **extra,
        }
        if reference is not None:
            body["Reference"] = reference
        return self.put(f"PurchaseInvoices/{invoice_id}", body)

    def put_manual_journal(
        self,
        journal_id: uuid.UUID,
        *,
        diary_id: uuid.UUID,
        lines: list[dict[str, Any]],
        auto_correct: bool = False,
        **extra: Any,
    ) -> httpx.Response:
        body: dict[str, Any] = {
            "id": str(journal_id),
            "JournalEntryDiary": {"id": str(diary_id)},
            "DocumentLineList": lines,
            **extra,
        }
        return self.put(f"ManualJournals/{journal_id}", body, params={"autoCorrect": str(auto_correct).lower()})

    def book_purchase_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        return self.post_action(f"PurchaseInvoices/{invoice_id}", ACTION_BOOK)

    def correct_purchase_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        """Stornering (koppelcontract §7.3): nooit hard verwijderen, altijd actie 19 + creditboeking."""
        return self.post_action(f"PurchaseInvoices/{invoice_id}", ACTION_CORRECT)

    def check_purchase_invoice_duplicate(self, **criteria: Any) -> httpx.Response:
        """Collectie-actie 138 — vóór elke boeking (idempotentie-hard-rule). Exacte criteria-velden
        nog niet geverifieerd (open punt verkenning/api-verkenning.md), dus expliciet meegeven."""
        return self.post_action("PurchaseInvoices", ACTION_DUPLICATE_CHECK, **criteria)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _log_rate_limit_headers(method: str, url: str, response: httpx.Response) -> None:
    relevant = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
    if relevant:
        logger.info("RLZ rate-limit headers voor %s %s (status %s): %s", method, url, response.status_code, relevant)
