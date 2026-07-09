from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class MigratieVersieAchterstand(RuntimeError):
    """De database staat niet op de laatste migratie uit de repo (CLAUDE.md-taak "geen raadsel-
    500 door een gemiste migratie meer")."""


def _laatste_migratie_in_repo() -> str:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise MigratieVersieAchterstand("Geen migraties gevonden in de repo (migrations/versions is leeg).")
    return head


def _huidige_migratie_in_database(engine: Engine) -> str | None:
    """None betekent: geen alembic_version-rij (lege/verse database, of de tabel bestaat nog niet
    — beide gevallen zijn voor de aanroeper gewoon "loopt achter")."""
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
    except ProgrammingError:
        return None


def controleer_versies(*, huidige: str | None, laatste: str, fail_fast: bool) -> None:
    """Losse vergelijk-/besluitstap (apart van de DB-/repo-lookups hierboven) zodat het
    mismatch-gedrag zelf met gewone parameters te unit-testen is, zonder database of
    migrations-directory (zelfde patroon als app/security/tokens.py::_resolve_jwt_secret)."""
    if huidige == laatste:
        return
    melding = (
        f"Database loopt achter: huidige migratie {huidige!r}, repo verwacht {laatste!r} — "
        "draai `make migrate`."
    )
    if fail_fast:
        logger.error(melding)
        raise MigratieVersieAchterstand(melding)
    logger.warning("%s (fail_fast staat uit, app start alsnog)", melding)


def controleer_migratie_versie(engine: Engine, *, fail_fast: bool) -> None:
    """Startup-guard: vergelijkt de alembic-versie van `engine` met de laatste migratie in de
    repo. Gebruikt de normale runtime-engine (least-privilege `boekhouding_app`-rol, zie
    app/db/session.py) — die rol heeft sinds migratie 0013 SELECT op `alembic_version`."""
    laatste = _laatste_migratie_in_repo()
    huidige = _huidige_migratie_in_database(engine)
    controleer_versies(huidige=huidige, laatste=laatste, fail_fast=fail_fast)
