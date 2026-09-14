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


#: Uitgeschreven in SQL voor de unieke index `uq_odoo_koppeling_host_company` (migratie 0140) — MOET dezelfde
#: uitkomst geven als `odoo_host()` voor élke URL die de service opslaat (de service slaat sinds 14-09 alleen
#: nog genormaliseerde `scheme://host`-URL's op; voor legacy-rijen zonder pad is de uitkomst identiek).
ODOO_HOST_SQL = "lower(split_part(split_part(odoo_url, '//', 2), '/', 1))"


def odoo_host(odoo_url: str) -> str:
    """DE host-normalisatie van een Odoo-URL — de enige variant in de codebase (opdracht Peter 14-09, punt 2a):
    alles ná `//` tot het eerste `/`, `?` of `#`, kleine letters, zonder witruimte. Zonder scheme telt de hele
    invoer tot het eerste pad-teken als host. Een poort blijft onderdeel van de host (`x.odoo.com:8069`)."""
    rest = odoo_url.strip()
    if "//" in rest:
        rest = rest.split("//", 1)[1]
    for scheider in ("/", "?", "#"):
        rest = rest.split(scheider, 1)[0]
    return rest.strip().lower()


def normaliseer_odoo_url(odoo_url: str) -> str:
    """Invoer mét webclient-pad (`/odoo`, `/web`, `/odoo/action-…`), trailing slash of query wordt `scheme://host`
    (punt 4 opdracht 14-09): de JSON-2-client plakt `/json/2/…` achter de URL en een pad geeft dan een 404. Zonder
    scheme = https. Lege host = ValueError (leesbaar, geen HTTP-call)."""
    invoer = odoo_url.strip()
    scheme = "https"
    if "://" in invoer:
        kop, _rest = invoer.split("://", 1)
        if kop.lower() in ("http", "https"):
            scheme = kop.lower()
        else:
            raise ValueError(f"Odoo-URL heeft een onbekend schema '{kop}' — gebruik https://<host>")
    host = odoo_host(invoer)
    if not host or " " in host or "." not in host and host != "localhost" and not host.startswith("localhost:"):
        raise ValueError("Odoo-URL mist een geldige host — gebruik bv. https://naam.odoo.com")
    return f"{scheme}://{host}"


def odoo_admin_sentinel(odoo_url: str, company_id: int) -> str:
    """Waarde voor `administratie.rlz_admin_id` van een Odoo-administratie: leesbaar, uniek per
    (host, company) en herkenbaar aan het prefix."""
    return f"{SENTINEL_PREFIX}{odoo_host(odoo_url)}:{int(company_id)}"


def is_odoo_sentinel(rlz_admin_id: str | None) -> bool:
    return bool(rlz_admin_id) and str(rlz_admin_id).startswith(SENTINEL_PREFIX)
