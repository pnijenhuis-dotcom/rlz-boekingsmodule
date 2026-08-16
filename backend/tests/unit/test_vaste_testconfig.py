"""Vangnet op de vaste testconfig (hygiëne-run 2026-08-16, "de webauthn-les").

De suite draait op de code-defaults, nooit op dev-.env-waarden — alleen de vier
database-URL's blijven omgevingsafhankelijk. Dit vangnet faalt zodra die borging uit
tests/conftest.py zou verdwijnen of een fixture settings sessie-breed muteert zonder herstel.
"""

from __future__ import annotations

from app.config import Settings, settings

DB_VELDEN = ("database_url", "app_database_url", "test_database_url", "test_app_database_url")


def test_suite_draait_op_code_defaults() -> None:
    schoon = Settings(_env_file=None)
    afwijkend = {
        veld: (getattr(settings, veld), getattr(schoon, veld))
        for veld in Settings.model_fields
        if veld not in DB_VELDEN and getattr(settings, veld) != getattr(schoon, veld)
    }
    assert afwijkend == {}, (
        "settings wijken af van de code-defaults tijdens de testrun — een test of fixture "
        f"pint niet netjes via monkeypatch, of de conftest-borging is weg: {afwijkend}"
    )


def test_dev_stub_staat_uit_in_de_suite() -> None:
    """De concrete les van 2026-08-14: de dev-stub mag in dev-.env aan staan (LAN-kliktests),
    maar de suite ziet 'm altijd uit tenzij een test 'm expliciet zelf aanzet."""
    assert settings.auth_biometrie_dev_stub is False
