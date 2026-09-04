"""Credential-resolutie Odoo (besluit 0012/0016): store-first — `platform.odoo_koppeling` draagt URL,
company en de envelope-versleutelde API-key; de dev-terugval leest `ODOO_URL`/`ODOO_API_KEY` uit de
omgeving (of `verkenning/.env`, zoals de STAP-0-scripts) UITSLUITEND in `environment == "dev"` en alleen
voor het company-id dat de koppeling-rij zelf noemt. De key wordt nooit gelogd of teruggegeven."""

from __future__ import annotations

import os
import pathlib
import uuid
from dataclasses import dataclass
from datetime import date

from app.config import settings
from app.db.models import Administratie
from app.db.session import scoped_session
from app.odoo.client import OdooClient
from app.odoo.models import OdooKoppeling
from app.security.envelope import unwrap_secret

_VERKENNING_ENV = pathlib.Path(__file__).resolve().parents[3] / "verkenning" / ".env"


class GeenOdooKoppeling(Exception):
    """Deze administratie heeft geen (volledige) Odoo-koppeling — niet-onboarded of verkeerde backend."""


@dataclass(frozen=True)
class OdooVerbinding:
    """Alles wat de adapter nodig heeft, zónder het geheim (dat leeft alleen in de client)."""

    administratie_id: uuid.UUID
    odoo_url: str
    company_id: int
    company_naam: str | None
    journal_purchase_id: int | None
    journal_general_id: int | None
    journal_sale_id: int | None
    analytic_plan_id: int | None
    #: Blok D: alleen-lezen-koppeling (Odoo = leesbron, boeken blijft in RLZ) + voorraad-knip.
    alleen_lezen: bool = False
    voorraad_knip_datum: date | None = None
    #: Blok E (migratie 0104): overstap van een RLZ-administratie — factuurdatum < overgangsdatum = weigering
    #: in de inkoop-adapter (hoort nog in RLZ). None = geen poort.
    overgangsdatum: date | None = None


def lees_dev_env() -> tuple[str | None, str | None]:
    """(url, api_key) uit de omgeving / verkenning/.env — alleen dev; nooit loggen."""
    url = os.environ.get("ODOO_URL")
    key = os.environ.get("ODOO_API_KEY")
    if (not url or not key) and _VERKENNING_ENV.exists():
        try:
            from dotenv import dotenv_values

            env = dotenv_values(_VERKENNING_ENV)
            url = url or env.get("ODOO_URL")
            key = key or env.get("ODOO_API_KEY")
        except Exception:  # noqa: BLE001 — dev-gemak, nooit een crash
            pass
    return (url or None), (key or None)


def koppeling_voor(administratie_id: uuid.UUID) -> OdooVerbinding:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise GeenOdooKoppeling(f"Onbekende administratie: {administratie_id}")
        rij = session.get(OdooKoppeling, administratie_id)
        # Blok D: een ALLEEN-LEZEN-koppeling mag óók bij een RLZ-administratie (Odoo is dan uitsluitend
        # leesbron, bv. de voorraad-uitstroom van Universal Verkoop); een schrijvende koppeling vereist
        # backend 'odoo' — het domein boekt nooit in twee systemen.
        if administratie.boekhoud_backend != "odoo" and not (rij is not None and rij.alleen_lezen):
            raise GeenOdooKoppeling(
                f"Administratie {administratie.naam} draait niet op Odoo (backend {administratie.boekhoud_backend})"
            )
        if rij is None:
            raise GeenOdooKoppeling(f"Administratie {administratie.naam} heeft geen Odoo-koppeling (company onbekend)")
        return OdooVerbinding(
            administratie_id=administratie_id,
            odoo_url=rij.odoo_url,
            company_id=rij.company_id,
            company_naam=rij.company_naam,
            journal_purchase_id=rij.journal_purchase_id,
            journal_general_id=rij.journal_general_id,
            journal_sale_id=rij.journal_sale_id,
            analytic_plan_id=rij.analytic_plan_id,
            alleen_lezen=bool(rij.alleen_lezen),
            voorraad_knip_datum=rij.voorraad_knip_datum,
            overgangsdatum=rij.overgangsdatum,
        )


def leeskoppeling_voor(administratie_id: uuid.UUID) -> OdooVerbinding | None:
    """Blok D: de alleen-lezen Odoo-koppeling van een (RLZ-)administratie, of None als die er niet is —
    voor de voorraad-leesroutes (knip-dedup in rlz_uitstroom, bron in verkoop_uitstroom). Nooit een fout:
    geen koppeling = geen Odoo-leesbron."""
    try:
        verbinding = koppeling_voor(administratie_id)
    except GeenOdooKoppeling:
        return None
    return verbinding if verbinding.alleen_lezen else None


def _api_key_voor(administratie_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is not None and rij.api_key_ciphertext:
            return unwrap_secret(rij.api_key_ciphertext, rij.wrapped_data_key).decode()
    if settings.environment == "dev":
        _, key = lees_dev_env()
        if key:
            return key
    raise GeenOdooKoppeling("Geen Odoo-API-key in de credential-store voor deze administratie")


def odoo_client_voor(administratie_id: uuid.UUID, *, read_only: bool = False) -> OdooClient:
    """Client gebonden aan de company van de koppeling — de enige toegestane manier om vanuit de app
    een Odoo-verbinding te openen (company-poort). Een ALLEEN-LEZEN-koppeling (blok D) levert ALTIJD een
    read-only client, ongeacht het argument — de poort "nooit een write op company 3" zit hier, niet bij
    de aanroeper."""
    verbinding = koppeling_voor(administratie_id)
    return OdooClient(
        url=verbinding.odoo_url,
        api_key=_api_key_voor(administratie_id),
        company_id=verbinding.company_id,
        read_only=read_only or verbinding.alleen_lezen,
    )
