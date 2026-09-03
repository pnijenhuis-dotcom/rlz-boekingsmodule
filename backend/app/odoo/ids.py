"""Id-vertaling Odoo ↔ app (STAP-0 §3.1: Odoo geeft server-int-id's, geen client-GUID's; onze
domeinkolommen — vendor_id/ledger_id/taxrate_id/project_id op het boekvoorstel, rlz_document_id in de
tijdlijn — zijn UUID's). De adapter vertaalt in twee richtingen:

- app → Odoo: `odoo_uuid(company, model, odoo_id)` is een DETERMINISTISCHE UUIDv5 — dezelfde Odoo-rij
  krijgt altijd dezelfde lokale UUID (idempotente sync, stabiele verwijzingen);
- Odoo → app: de omgekeerde weg loopt via `boekhouding.odoo_id_koppeling` (gevuld door de sync) —
  een UUID die dáár niet staat is fail-loud (`OnbekendeOdooId`), nooit een gok.

Het domein blijft zo UUID-vrij van Odoo-kennis (guardrail 0016)."""

from __future__ import annotations

import uuid

# Vast, mag NOOIT wijzigen (zelfde reden als app/documenten/rlz_ids.py::_NAMESPACE).
_NAMESPACE = uuid.UUID("5d0a6a1e-0d0c-4f7a-9c2b-0d0020260903")

#: Sentinel-prefix in `platform.administratie.rlz_admin_id` voor Odoo-administraties — de kolom is
#: NOT NULL UNIQUE en wordt overal als "RLZ-adminId" gebruikt; élke RLZ-client-resolutie op een
#: sentinel is fail-loud (app/rlz/credentials.py).
SENTINEL_PREFIX = "odoo:"

#: Synthetische Odoo-id voor "geen btw" (besluit Peter 02-09: 0 %-inkoop = géén tax_ids meegeven;
#: Odoo company 1 heeft geen inkoop-0 %-code). De cache-rij bestaat zodat de controleur 'm kan kiezen;
#: de adapter stuurt voor deze code géén tax_ids.
GEEN_BTW_ODOO_ID = 0


def odoo_uuid(company_id: int, model: str, odoo_id: int) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{company_id}:{model}:{int(odoo_id)}")


def odoo_admin_sentinel(odoo_url: str, company_id: int) -> str:
    """Waarde voor `administratie.rlz_admin_id` van een Odoo-administratie: leesbaar, uniek per
    (host, company) en herkenbaar aan het prefix."""
    host = odoo_url.split("//", 1)[-1].rstrip("/").lower()
    return f"{SENTINEL_PREFIX}{host}:{int(company_id)}"


def is_odoo_sentinel(rlz_admin_id: str | None) -> bool:
    return bool(rlz_admin_id) and str(rlz_admin_id).startswith(SENTINEL_PREFIX)
