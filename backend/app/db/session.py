from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.app_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def session_factory_for(bind: Engine) -> sessionmaker:
    """Losse sessionmaker voor een ander engine dan de globale runtime-engine (bv. in tests,
    gebonden aan de testdatabase i.p.v. app_database_url)."""
    return sessionmaker(bind=bind, expire_on_commit=False)


@contextmanager
def scoped_session(
    administratie_id: uuid.UUID | None, *, session_factory: sessionmaker | None = None
) -> Generator[Session, None, None]:
    """Open een transactie gescoped op één administratie voor Row-Level Security.

    De scope wordt gezet via `set_config(..., is_local=true)`, het functie-equivalent van
    `SET LOCAL` — geldt uitsluitend voor de lopende transactie, nooit sessie-breed (de sessie
    kan door connection pooling hergebruikt worden voor een andere administratie). `set_config`
    accepteert een echte parameter, in tegenstelling tot het SQL-statement `SET`, dat geen
    bind-parameters ondersteunt en dus string-formatting (injectierisico) zou vereisen.

    `administratie_id=None` scoped op platformbrede rijen (administratie_id IS NULL in het
    beleid) — géén toegang tot administratie-gebonden rijen.
    """
    session = (session_factory or SessionLocal)()
    try:
        session.execute(
            text("SELECT set_config('app.current_administratie_id', :value, true)"),
            {"value": str(administratie_id) if administratie_id else ""},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
