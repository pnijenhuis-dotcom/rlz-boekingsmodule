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
# Bewezen zonder waarneembaar effect (verkenning/api-verkenning.md "Actie 138" en "Boekt RLZ..."):
# geen enkel geval (concept/geboekt, duplicaat/uniek) laat een verschil zien in respons of
# document, en Book (17) blokkeert duplicaten ook zelf niet. Niet gebruiken voor idempotentie —
# zie find_purchase_invoices_by_reference() voor de eigen duplicaatcheck die dat wél doet.
ACTION_DUPLICATE_CHECK_UNRELIABLE = 138


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
    verkenning/api-verkenning.md.
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
        19=Correct (zet terug naar concept, géén apart creditdocument), 34=verrekenen,
        138=duplicaatcheck (per document, bewezen zonder effect), 15/16=Link/UnlinkPayment.
        `path` moet het document-pad zijn (`PurchaseInvoices/{id}`), niet de collectie: RLZ's
        Actions-routes zijn per-document, ook voor 138 (collectie-vorm geeft altijd 400)."""
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

    def upload_bijlage(
        self, entity_path: str, entity_id: uuid.UUID, *, upload_id: uuid.UUID, filename: str, content_base64: str
    ) -> httpx.Response:
        """PDF/XML-bijlage bij een document (bv. `PurchaseInvoices/{id}`). Geverifieerd
        (verkenning/api-verkenning.md "Boekstuknummer, factuurdatum en /Uploads"): RLZ wil hier
        expliciet PUT, geen POST (405 "Must use PUT instead of POST") — zelfde client-GUID-vorm als
        de documenten zelf. `upload_id` is de eigen client-GUID voor de bijlage (apart van
        `entity_id`, dat het document zelf is)."""
        body = {"id": str(upload_id), "FileName": filename, "Content": content_base64}
        return self.put(f"{entity_path}/{entity_id}/Uploads/{upload_id}", body)

    def book_purchase_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        return self.post_action(f"PurchaseInvoices/{invoice_id}", ACTION_BOOK)

    def correct_purchase_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        """Stornering (koppelcontract §7.3): nooit hard verwijderen, altijd actie 19. Geverifieerd
        gedrag (verkenning/api-verkenning.md "Actie 19 Correct"): zet hetzelfde document terug
        naar concept (Status 1) — er komt géén apart creditdocument bij."""
        return self.post_action(f"PurchaseInvoices/{invoice_id}", ACTION_CORRECT)

    def run_unreliable_duplicate_check_action(self, invoice_id: uuid.UUID) -> httpx.Response:
        """Actie 138 op een bestaand document. Bewezen zonder waarneembaar effect (drie
        experimenten, verkenning/api-verkenning.md "Actie 138"): geen verschil in respons of
        document tussen een echt duplicaat en een unieke factuur, in concept- én geboekte staat,
        en Book (17) boekt duplicaten zelf ook zonder blokkade. **Gebruik dit niet voor
        idempotentie** — zie find_purchase_invoices_by_reference()."""
        return self.post_action(f"PurchaseInvoices/{invoice_id}", ACTION_DUPLICATE_CHECK_UNRELIABLE)

    # --- bankmodule (geverifieerde vormen: api-verkenning.md "Bankmodule STAP 0" +
    # "Bankmodule schrijf-PoC", 2 augustus 2026) ---------------------------------------------

    def list_payment_accounts(self) -> list[dict[str, Any]]:
        """Alle rekeningen incl. kas (Type 3) — één leesroute voor bank én kas."""
        return self.get("PaymentAccounts").get("value", [])

    def get_last_bank_import(self, account_id: uuid.UUID | str) -> dict[str, Any] | None:
        """Versheid-probe per rekening (STAP 0 §3): bestandsnaam, datum, BankImportSource/-Type.
        None bij 404 — een rekening zonder ooit een aanlevering hééft geen LastBankImport; dat is
        de onboarding-check, geen fout."""
        try:
            return self.get(f"PaymentAccounts/{account_id}/LastBankImport")
        except RlzApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def list_payment_transactions(self, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Ruwe bankmutaties (STAP 0 §2: dé bron, niet Statements). Geverifieerde OData-parameters:
        `$filter=PaymentAccount/id eq {guid}` / `IsComplete eq false` / `CreateDate ge {iso}`,
        `$orderby`, `$top`, `$count=true`, `$expand=PaymentAccount,MatchedPaymentItem,...`.
        ⚠️ Afgeletterd-status altijd op OpenAmount toetsen — IsComplete is stale na storno."""
        return self.get("PaymentTransactions", params=params).get("value", [])

    def get_payment_transaction(self, tx_id: uuid.UUID | str, *, expand: str | None = None) -> dict[str, Any]:
        params = {"$expand": expand} if expand else None
        return self.get(f"PaymentTransactions/{tx_id}", params=params)

    def list_payment_items(self, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Open posten om tegen af te letteren. Alleen de collectie-GET bestaat — per-id is 404
        (schrijf-PoC §5); filteren dus altijd via `$filter` (bv. `Document/id eq {guid}`)."""
        return self.get("PaymentItems", params=params).get("value", [])

    def put_bank_mutation_direct_booking(
        self,
        booking_id: uuid.UUID,
        *,
        payment_transaction_id: uuid.UUID | str,
        lines: list[dict[str, Any]],
        description: str | None = None,
    ) -> httpx.Response:
        """Mutatie direct op grootboek (schrijf-PoC §3, volledig geverifieerd): boekt in één klap
        (document meteen Status 3, reeks RLZ-07 — actie 17 is niet nodig en geeft 409) én lettert
        de mutatie af (OpenAmount 0). Regelbedragen dragen het TEKEN VAN DE MUTATIE (PoC:
        NetAmount = Amount van de transactie, −121 bij een afschrijving). Regelmodel kent ook
        TaxRate/Project/Department. Terugdraaien = actie 19 op dit document
        (correct_bank_mutation_direct_booking); de crediteuren-koppelrekening is geen geldig
        regel-doel (500)."""
        body: dict[str, Any] = {
            "id": str(booking_id),
            "PaymentTransaction": {"id": str(payment_transaction_id)},
            "DocumentLineList": lines,
        }
        if description is not None:
            body["Description"] = description
        return self.put(f"BankMutationDirectBookings/{booking_id}", body)

    def get_bank_mutation_direct_booking(self, booking_id: uuid.UUID | str) -> dict[str, Any]:
        return self.get(f"BankMutationDirectBookings/{booking_id}")

    def correct_bank_mutation_direct_booking(self, booking_id: uuid.UUID | str) -> httpx.Response:
        """Storno van een directe bankboeking (schrijf-PoC §3): actie 19 → document terug naar
        Status 1, mutatie weer open (OpenAmount hersteld). ⚠️ IsComplete blijft daarna stale op
        true — nooit op dat veld toetsen."""
        return self.post_action(f"BankMutationDirectBookings/{booking_id}", ACTION_CORRECT)

    # --- omzetmodule (geverifieerde vormen: api-verkenning.md "Omzetmodule STAP 0",
    # 7 augustus 2026) --------------------------------------------------------------------------

    def put_customer(self, customer_id: uuid.UUID, *, name: str) -> httpx.Response:
        """Debiteur aanmaken/bijwerken — zelfde minimale vorm als put_vendor (STAP 0 §5:
        geverifieerd voor de systeemdebiteur "Kasomzet")."""
        return self.put(f"Customers/{customer_id}", {"id": str(customer_id), "Name": name})

    def put_sales_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        customer_id: uuid.UUID,
        lines: list[dict[str, Any]],
        **extra: Any,
    ) -> httpx.Response:
        """Verkoopfactuur (STAP 0 §1): zelfde regelvorm als inkoop (Account/TaxRate/NetAmount/
        TaxAmount/Description), Entity = de debiteur. ⚠️ `Reference` is hier NIET van ons — RLZ
        overschrijft 'm met zijn eigen verkoopnummering ("RLZ-{InvoiceNumber}"); een expliciet
        `InvoiceNumber` (int, via **extra) is wél zetbaar en is het herstel-pad wanneer boeken
        op "Dit factuurnummer is al in gebruik" stukloopt."""
        body: dict[str, Any] = {
            "id": str(invoice_id),
            "Entity": {"id": str(customer_id)},
            "DocumentLineList": lines,
            **extra,
        }
        return self.put(f"SalesInvoices/{invoice_id}", body)

    def get_sales_invoice(self, invoice_id: uuid.UUID | str) -> dict[str, Any]:
        return self.get(f"SalesInvoices/{invoice_id}")

    def book_sales_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        return self.post_action(f"SalesInvoices/{invoice_id}", ACTION_BOOK)

    def correct_sales_invoice(self, invoice_id: uuid.UUID) -> httpx.Response:
        """Actie 19 op een geboekte verkoopfactuur → Status 1, zelfde heropen-gedrag als inkoop
        (STAP 0 §1, geverifieerd)."""
        return self.post_action(f"SalesInvoices/{invoice_id}", ACTION_CORRECT)

    def max_sales_invoice_number(self) -> int:
        """Hoogste InvoiceNumber in de SalesInvoices-collectie. ⚠️ De collectie ziet
        API-aangemaakte facturen NIET (STAP 0 §2) — dit dekt dus alleen de UI-/importfacturen;
        de aanroeper moet het eigen lokale maximum ernaast leggen (app/omzet/boeken.py)."""
        rijen = self.get("SalesInvoices", params={"$orderby": "InvoiceNumber desc", "$top": "1"}).get("value", [])
        if not rijen:
            return 0
        return int(rijen[0].get("InvoiceNumber") or 0)

    def list_journal_entry_diaries(self) -> list[dict[str, Any]]:
        """Dagboeken per administratie — het memoriaal-dagboek-GUID wordt hieruit gekozen
        (STAP 0 §3: lijkt RLZ-breed hetzelfde systeem-GUID, maar nooit hardcoden)."""
        return self.get("JournalEntryDiaries").get("value", [])

    def get_manual_journal(self, journal_id: uuid.UUID | str) -> dict[str, Any]:
        return self.get(f"ManualJournals/{journal_id}")

    def book_manual_journal(self, journal_id: uuid.UUID) -> httpx.Response:
        """Actie 17 op een memoriaal → Status 3 (saldo 0, niets open). RLZ weigert hier zelf een
        niet-sluitend memoriaal met een 400 (STAP 0 §4) — onze saldo-0-check zit er als
        fail-fast vóór."""
        return self.post_action(f"ManualJournals/{journal_id}", ACTION_BOOK)

    def correct_manual_journal(self, journal_id: uuid.UUID) -> httpx.Response:
        return self.post_action(f"ManualJournals/{journal_id}", ACTION_CORRECT)

    def find_manual_journals_by_reference(self, *, reference: str) -> list[dict[str, Any]]:
        """RLZ-side duplicaatcheck voor de omzet-periode: de ManualJournals-collectie is (anders
        dan SalesInvoices) wél vers en behoudt onze eigen Reference (STAP 0 §2/§3)."""
        escaped = reference[:30].replace("'", "''")
        return self.get("ManualJournals", params={"$filter": f"Reference eq '{escaped}'"}).get("value", [])

    def find_purchase_invoices_by_reference(
        self, *, vendor_id: uuid.UUID | str, reference: str, total_amount: float | None = None
    ) -> list[dict[str, Any]]:
        """Eigen duplicaatcheck (idempotentie-fundament — RLZ's actie 138 geeft geen bruikbaar
        signaal, zie run_unreliable_duplicate_check_action). Vóór elke PUT+Book aanroepen; niet-
        leeg resultaat = al aangemaakt, dus PUT overslaan (client-GUID maakt de PUT zelf al
        idempotent, maar dit vangt ook niet-deterministische GUID's af).

        RLZ kapt `Reference` af op 30 tekens (geverifieerd) — filter dus op de afgekapte vorm,
        anders mist de check net-te-lange referenties zoals een volledige UUID. `total_amount`
        filtert op `BaseInvoiceAmount` (netto + btw, geverifieerd veld) — optioneel, voor
        onderscheid tussen twee facturen die toevallig dezelfde (afgekapte) referentie delen."""
        truncated_reference = reference[:30].replace("'", "''")
        filter_expr = f"Entity/id eq {vendor_id} and Reference eq '{truncated_reference}'"
        if total_amount is not None:
            filter_expr += f" and BaseInvoiceAmount eq {total_amount}"
        return self.get("PurchaseInvoices", params={"$filter": filter_expr}).get("value", [])


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
