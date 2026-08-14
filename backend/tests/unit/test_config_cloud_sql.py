"""Cloud SQL-URL-compositie (F2, app/config.py): losse wachtwoord-secrets + instance-
connection-name → volledige unix-socket-URL's, met URL-encoding (de gegenereerde
wachtwoorden bevatten base64-tekens) en fail-closed op een verbinding zonder wachtwoord."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

VERBINDING = "rlz-boekhouding:europe-west4:rlz-sql"


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_app_url_gecomposeerd_met_url_encoding() -> None:
    s = _settings(cloud_sql_verbinding=VERBINDING, app_db_wachtwoord="a+b/c=")
    assert s.app_database_url == (
        f"postgresql+psycopg://boekhouding_app:a%2Bb%2Fc%3D@/boekhouding?host=/cloudsql/{VERBINDING}"
    )
    # De service krijgt bewust géén owner-wachtwoord: die URL blijft de (luid falende) default.
    assert s.database_url == Settings(_env_file=None).database_url


def test_owner_url_gecomposeerd_voor_migratie_job() -> None:
    s = _settings(cloud_sql_verbinding=VERBINDING, db_owner_wachtwoord="geheim")
    assert s.database_url == (
        f"postgresql+psycopg://postgres:geheim@/boekhouding?host=/cloudsql/{VERBINDING}"
    )
    assert s.app_database_url == Settings(_env_file=None).app_database_url


def test_verbinding_zonder_wachtwoord_faalt_hard() -> None:
    with pytest.raises(ValidationError, match="cloud_sql_verbinding"):
        _settings(cloud_sql_verbinding=VERBINDING)


def test_zonder_verbinding_blijven_dev_defaults() -> None:
    s = _settings(app_db_wachtwoord="wordt-genegeerd")
    assert s.app_database_url == Settings(_env_file=None).app_database_url
