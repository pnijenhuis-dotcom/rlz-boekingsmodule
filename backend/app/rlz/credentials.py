from __future__ import annotations

import os

from app.rlz.client import RlzClient

# TIJDELIJK: credential-store-integratie volgt later (zie CLAUDE.md "Secrets" en
# Platform/registers/conventies.md) — tot die tijd rechtstreeks via .env-logins, zelfde
# prefixen als tests/integration/conftest.py. Nieuwe administraties hier toevoegen zodra de
# webservice-login bevestigd is (Platform/registers/entiteiten.md); BLOw ontbreekt bewust — het
# volledige RLZ-adminId staat nergens in de repo (het register toont 'm afgekapt), dus geen
# aanname/gok hier.
_PREFIX_PER_RLZ_ADMIN_ID: dict[str, str] = {
    "3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac": "UNIVERSAL",  # Universal Steigerbouw B.V.
    "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5": "TESTADMIN",  # Administratiekantoor Nijenhuis (test)
    "be5e66b3-b38c-4927-85c1-670490f16e3a": "RUBICON",  # Rubicon Investments B.V. (0009-b)
}


class GeenRlzCredentials(Exception):
    """Geen .env-credentials beschikbaar voor deze RLZ-administratie (nog niet geregistreerd, of
    de env-vars zijn niet gevuld — bv. Rubicon: webservice-toegang was bij het opstellen van dit
    bestand nog niet bevestigd, zie Platform/OPEN_ITEMS.md 'Grootboek-koppeling')."""


def resolve_credentials(rlz_admin_id: str) -> tuple[str, str]:
    prefix = _PREFIX_PER_RLZ_ADMIN_ID.get(rlz_admin_id)
    if prefix is None:
        raise GeenRlzCredentials(f"Geen credential-prefix geregistreerd voor RLZ-adminId {rlz_admin_id!r}")
    username = os.environ.get(f"{prefix}_USERNAME")
    password = os.environ.get(f"{prefix}_PASSWORD")
    if not username or not password:
        raise GeenRlzCredentials(f"{prefix}_USERNAME/{prefix}_PASSWORD niet gevuld in de omgeving")
    return username, password


def client_voor_rlz_admin_id(rlz_admin_id: str) -> RlzClient:
    username, password = resolve_credentials(rlz_admin_id)
    return RlzClient(username=username, password=password, admin_id=rlz_admin_id)
