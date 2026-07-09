from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: fileConfig()'s default (True) zet .disabled op elke logger
    # die op dit moment al bestaat (bv. app.main, app.rlz.client — aangemaakt zodra die modules
    # ergens geïmporteerd zijn) en niet met naam in alembic.ini's [loggers] staat. In de testsuite
    # draait command.upgrade() in-process (tests/conftest.py), na het importeren van app.main —
    # zonder deze flag loggen die modules nooit meer iets, ook niet buiten migraties, voor de rest
    # van diezelfde procesrun. Productie draait migraties in een los `alembic upgrade`-proces, dus
    # dit raakt daar geen al-lopende app, maar de stille disable is nergens iets waard.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    from app.config import settings

    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
