"""JSON-2-client voor Odoo 19 (STAP-0 §1.1: `POST /json/2/<model>/<method>`, bearer-API-key, uitsluitend
benoemde argumenten; géén `X-Odoo-Database`-header — Odoo Online is single-db per host).

Ontwerpregels:
- COMPANY-POORT: de client is gebonden aan één `company_id`; élke call draagt `context.allowed_company_ids
  = [company_id]` (multi-company-db met tien bedrijven — STAP-0 §1.3). De adapter zet bovendien
  `company_id` in élke create-vals en leest 'm ná de write terug (post-write-verificatie).
- `read_only=True` weigert élke schrijfmethode vóór de call (blok D: company 3 = uitsluitend lezen).
- Retry/backoff op transportfouten, 429 en 5xx (tenacity, zelfde patroon als RlzClient); throttling
  via een minimale tussenpoos per call (Odoo Online publiceert geen limiet, wel worker-time-outs).
- Secrets nooit in logs of foutmeldingen: alleen model, methode en HTTP-status worden gelogd.
- Foutsemantiek (STAP-0 §1.11): 422 = `odoo.exceptions.UserError`/`ValidationError`, 403 = AccessError,
  404 = onbekend model/methode, 500 = o.a. `ValueError: Invalid field`. `read` op een onbekend id geeft
  `[]` — aanroepers toetsen op lengte."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SCHRIJFMETHODEN = frozenset(
    {
        "create",
        "write",
        "unlink",
        "action_post",
        "button_draft",
        "button_cancel",
        "reverse_moves",
        "action_reverse",
        "reconcile",
        "action_archive",
        "action_unarchive",
        "toggle_active",
        "register_as_main_attachment",
        "message_post",
        "copy",
    }
)


class OdooFout(Exception):
    """Odoo antwoordde niet-200 (ná retries) — draagt de exceptie-naam en de (gelokaliseerde) melding.
    Foutvertaling gebeurt op `naam` en op herkenbare tekstfragmenten (app/odoo/fouten.py)."""

    def __init__(self, status: int, naam: str | None, melding: str | None, *, model: str, methode: str) -> None:
        self.status = status
        self.naam = naam
        self.melding = melding or ""
        self.model = model
        self.methode = methode
        super().__init__(f"Odoo {model}.{methode} -> {status} {naam or ''}: {self.melding[:400]}")


class OdooAlleenLezen(Exception):
    """Schrijfmethode aangeroepen op een read-only client (company 3-poort, blok D)."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, OdooFout):
        return exc.status == 429 or exc.status >= 500
    return False


class OdooClient:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        company_id: int,
        read_only: bool = False,
        timeout: float = 60.0,
        min_tussenpoos_s: float = 0.05,
        client: httpx.Client | None = None,
    ) -> None:
        if not url or not api_key:
            raise ValueError("Odoo-URL en API-key zijn verplicht")
        if int(company_id) <= 0:
            raise ValueError("Odoo company_id moet > 0 zijn")
        self.url = url.rstrip("/")
        self.company_id = int(company_id)
        self.read_only = read_only
        self._min_tussenpoos = min_tussenpoos_s
        self._laatste_call = 0.0
        self._lock = threading.Lock()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.url,
            headers={
                "Authorization": f"bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "rlz-boekingsmodule-odoo-adapter",
            },
            timeout=timeout,
        )
        self.aanroepen = 0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OdooClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- transport -----------------------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            wacht = self._min_tussenpoos - (time.monotonic() - self._laatste_call)
            if wacht > 0:
                time.sleep(wacht)
            self._laatste_call = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def _post(self, model: str, methode: str, body: dict[str, Any]) -> Any:
        self._throttle()
        self.aanroepen += 1
        response = self._client.post(f"/json/2/{model}/{methode}", content=json.dumps(body, default=str))
        if response.status_code == 200:
            return response.json() if response.content else None
        naam = melding = None
        try:
            data = response.json()
            if isinstance(data, dict):
                naam = data.get("name")
                melding = data.get("message")
        except ValueError:
            melding = response.text[:400]
        logger.warning("Odoo %s.%s -> HTTP %s (%s)", model, methode, response.status_code, naam)
        raise OdooFout(response.status_code, naam, melding, model=model, methode=methode)

    def call(self, model: str, methode: str, **kwargs: Any) -> Any:
        """Generieke aanroep mét de company-context. Schrijfmethoden op een read-only client = fout
        vóór de call (nooit een halve write)."""
        if methode in SCHRIJFMETHODEN and self.read_only:
            raise OdooAlleenLezen(f"{model}.{methode} geweigerd: deze Odoo-verbinding is alleen-lezen")
        context = {"allowed_company_ids": [self.company_id], **(kwargs.pop("context", None) or {})}
        return self._post(model, methode, {**kwargs, "context": context})

    # --- gemak ---------------------------------------------------------------------------
    def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str],
        *,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kw: dict[str, Any] = {"domain": domain, "fields": fields, "offset": offset}
        if limit is not None:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.call(model, "search_read", **kw)

    def search_read_alles(
        self, model: str, domain: list, fields: list[str], *, pagina: int = 500, order: str = "id"
    ) -> list[dict[str, Any]]:
        """Gepagineerd (STAP-0 §3.7: nooit volledige collecties in één request)."""
        rijen: list[dict[str, Any]] = []
        offset = 0
        while True:
            deel = self.search_read(model, domain, fields, limit=pagina, offset=offset, order=order)
            rijen.extend(deel)
            if len(deel) < pagina:
                return rijen
            offset += pagina

    def search_count(self, model: str, domain: list) -> int:
        return int(self.call(model, "search_count", domain=domain))

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        return self.call(model, "read", ids=ids, fields=fields)

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        rijen = self.read(model, [int(odoo_id)], fields)
        return rijen[0] if rijen else None

    def create(self, model: str, vals: dict[str, Any]) -> int:
        resultaat = self.call(model, "create", vals_list=[vals])
        if isinstance(resultaat, list):
            return int(resultaat[0])
        return int(resultaat)

    def write(self, model: str, ids: list[int], vals: dict[str, Any]) -> bool:
        return bool(self.call(model, "write", ids=ids, vals=vals))

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, dict]:
        return self.call(model, "fields_get", attributes=attributes or ["type", "string", "relation"])

    def has_access(self, model: str, operatie: str) -> bool:
        try:
            return bool(self.call(model, "has_access", operation=operatie))
        except OdooFout:
            return False

    def versie(self) -> dict[str, Any]:
        """`/web/webclient/version_info` (JSON-RPC-vorm, geen auth nodig) — verbindingscheck."""
        self._throttle()
        response = self._client.post(
            "/web/webclient/version_info",
            content=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}),
        )
        response.raise_for_status()
        return response.json().get("result", {})
