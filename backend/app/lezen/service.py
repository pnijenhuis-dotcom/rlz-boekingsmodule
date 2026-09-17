"""Uitvoering van leesqueries (Feiten eerst, 17-09).

Bibliotheek-query (`voer_query_uit`): `scope: administratie` → per administratie een `scoped_session(aid, actor=systeem)`
(RLS via `app.current_administratie_id`, geen bypass), resultaten samengevoegd mét kolom `administratie`; `scope: platform`
→ één `scoped_session(None)`. Draait op de runtime-engine (job-image) — dat is dezelfde toegang als élke bestaande lees-only
CLI, alleen nu gereviewd en versieneerd. Audit `db_lezen` per aanroep (querynaam, versie, params, rijen, actor).

Vrije SELECT (`voer_sql_uit`): UITSLUITEND op de leesreplica (`settings.lees_database_url`; ontbreekt → `GeenLeesreplica`,
nooit stil op de primary), als een actieve BEHEERDER (RLS-scope = alles, `app.current_actor_id` gezet in de READ ONLY-
transactie), `statement_timeout`, rijenplafond, SELECT-only-poort. Audit `db_lezen_sql` (sha256 van de query, rijen, duur)."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, select, text

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.lezen import bibliotheek
from app.lezen.sql_poort import GeenSelect, toets_select_only
from app.lezen.uitvoer import MAX_RIJEN_CLI, MAX_RIJEN_ROUTE, Resultaat, bouw_resultaat

STATEMENT_TIMEOUT_MS = 60_000


class GeenLeesreplica(RuntimeError):
    """`LEES_DATABASE_URL` is niet gezet: vrije SQL draait nooit op de primary."""


class GeenBeheerder(PermissionError):
    """Vrije SQL leest als een actieve Beheerder; een andere actor wordt geweigerd."""


class OntbrekendeParameter(ValueError):
    pass


@dataclass(frozen=True)
class Uitkomst:
    resultaat: Resultaat
    query: str
    versie: str | None
    duur_ms: int


_lees_engine: Engine | None = None


def lees_engine() -> Engine:
    """Engine op de leesreplica; één per proces. `settings.lees_database_url` leeg → GeenLeesreplica."""
    global _lees_engine  # noqa: PLW0603 — proces-brede cache, zelfde patroon als app.db.session.engine
    url = (settings.lees_database_url or "").strip()
    if not url:
        raise GeenLeesreplica(
            "leesreplica niet geconfigureerd (LEES_DATABASE_URL leeg) — vrije SQL draait nooit op de primary; "
            "klikpunt: scripts/gcp/leesreplica.sh --apply en de env op service/jobs zetten"
        )
    if _lees_engine is None or str(_lees_engine.url) != url:
        _lees_engine = create_engine(url, pool_pre_ping=True)
    return _lees_engine


def _administraties(session, *, alleen: uuid.UUID | None) -> list[tuple[uuid.UUID, str]]:  # noqa: ANN001
    stmt = select(Administratie.id, Administratie.naam).order_by(Administratie.naam)
    if alleen is not None:
        stmt = stmt.where(Administratie.id == alleen)
    return [(rij.id, rij.naam) for rij in session.execute(stmt)]


def _params_voor(q: bibliotheek.Query, params: dict[str, Any], *, administratie_id: uuid.UUID | None) -> dict[str, Any]:
    uit: dict[str, Any] = {}
    for p in q.parameters:
        if p == "administratie_id":
            uit[p] = str(administratie_id) if administratie_id else None
            continue
        if p in params and params[p] not in (None, ""):
            uit[p] = params[p]
        elif p in q.optioneel:
            uit[p] = None
        else:
            raise OntbrekendeParameter(f"query {q.naam!r} vereist --param {p}=…")
    onbekend = set(params) - set(q.parameters)
    if onbekend:
        raise OntbrekendeParameter(f"onbekende parameter(s) voor {q.naam!r}: {', '.join(sorted(onbekend))}")
    return uit


def voer_query_uit(
    naam: str,
    params: dict[str, Any] | None = None,
    *,
    administratie_id: uuid.UUID | None = None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    max_rijen: int = MAX_RIJEN_CLI,
    session_factory=None,  # noqa: ANN001 — tests binden de testdatabase
) -> Uitkomst:
    q = bibliotheek.zoek(naam)
    params = dict(params or {})
    start = time.monotonic()
    kolommen: list[str] = []
    rijen: list[tuple[Any, ...]] = []
    administraties = 0
    if q.scope == "platform":
        with scoped_session(None, actor_id=actor_id, session_factory=session_factory) as session:
            res = session.execute(text(q.sql), _params_voor(q, params, administratie_id=None))
            kolommen = list(res.keys())
            rijen = [tuple(r) for r in res.fetchall()]
    else:
        with scoped_session(None, actor_id=actor_id, session_factory=session_factory) as session:
            adms = _administraties(session, alleen=administratie_id)
        for aid, adm_naam in adms:
            with scoped_session(aid, actor_id=actor_id, session_factory=session_factory) as session:
                res = session.execute(text(q.sql), _params_voor(q, params, administratie_id=aid))
                if not kolommen:
                    kolommen = ["administratie", *res.keys()]
                deel = [(adm_naam, *tuple(r)) for r in res.fetchall()]
            if deel:
                administraties += 1
                rijen.extend(deel)
    duur_ms = int((time.monotonic() - start) * 1000)
    resultaat = bouw_resultaat(kolommen or ["administratie", *q.kolommen], rijen, max_rijen=max_rijen, meta={"query": q.naam, "versie": q.versie})
    resultaat.administraties = administraties
    with scoped_session(None, actor_id=actor_id, session_factory=session_factory) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="lezen",
            record_id=uuid.uuid5(uuid.NAMESPACE_URL, f"db-lezen:{q.naam}"),
            actie="db_lezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "query": q.naam,
                "versie": q.versie,
                "params": {k: str(v) for k, v in params.items()},
                "administratie_id": str(administratie_id) if administratie_id else None,
                "rijen": resultaat.totaal,
                "duur_ms": duur_ms,
            },
        )
    return Uitkomst(resultaat=resultaat, query=q.naam, versie=q.versie, duur_ms=duur_ms)


def _is_actieve_beheerder(actor_id: uuid.UUID, *, session_factory=None) -> str:  # noqa: ANN001
    with scoped_session(None, actor_id=actor_id, session_factory=session_factory) as session:
        rij = session.get(Gebruiker, actor_id)
        if rij is None or rij.rol != GebruikerRol.BEHEERDER or rij.status != GebruikerStatus.ACTIEF:
            raise GeenBeheerder("vrije SQL leest uitsluitend als een actieve Beheerder")
        return rij.naam


def voer_sql_uit(
    sql: str,
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID | None = None,
    max_rijen: int = MAX_RIJEN_ROUTE,
    engine: Engine | None = None,
    session_factory=None,  # noqa: ANN001
) -> Uitkomst:
    """Vrije SELECT op de leesreplica als Beheerder `actor_id`. Volgorde: poort → beheerder-toets → replica-engine →
    READ ONLY-transactie mét actor-GUC (+ optioneel `app.current_administratie_id`) + statement_timeout → rijenplafond →
    audit (op de primary, via de runtime-sessie). RLS blijft gelden: tabellen mét een strikt administratie-beleid zonder
    Beheerder-clausule (bv. `bank_mutatie`) geven alleen rijen als `administratie_id` is meegegeven — nooit een bypass."""
    schoon = toets_select_only(sql)  # GeenSelect → aanroeper vertaalt
    naam = _is_actieve_beheerder(actor_id, session_factory=session_factory)
    eng = engine or lees_engine()
    start = time.monotonic()
    with eng.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SELECT set_config('statement_timeout', :t, true)"), {"t": str(STATEMENT_TIMEOUT_MS)})
            conn.execute(text("SELECT set_config('app.current_actor_id', :a, true)"), {"a": str(actor_id)})
            conn.execute(
                text("SELECT set_config('app.current_administratie_id', :adm, true)"),
                {"adm": str(administratie_id) if administratie_id else ""},
            )
            res = conn.execute(text(schoon))
            kolommen = list(res.keys())
            rijen = [tuple(r) for r in res.fetchmany(max_rijen + 1)]
    duur_ms = int((time.monotonic() - start) * 1000)
    resultaat = bouw_resultaat(kolommen, rijen, max_rijen=max_rijen, anonimiseer_namen=False, meta={"als": naam})
    with scoped_session(None, actor_id=actor_id, session_factory=session_factory) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="lezen",
            record_id=uuid.uuid5(uuid.NAMESPACE_URL, "db-lezen:sql"),
            actie="db_lezen_sql",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "sha256": hashlib.sha256(schoon.encode()).hexdigest(),
                "lengte": len(schoon),
                "administratie_id": str(administratie_id) if administratie_id else None,
                "rijen": resultaat.totaal,
                "afgekapt": resultaat.afgekapt,
                "duur_ms": duur_ms,
                "eerste_regel": schoon.splitlines()[0][:200],
            },
        )
    return Uitkomst(resultaat=resultaat, query="sql", versie=None, duur_ms=duur_ms)


def overzicht() -> list[dict[str, Any]]:
    return [
        {
            "naam": q.naam,
            "versie": q.versie,
            "doel": q.doel,
            "scope": q.scope,
            "parameters": list(q.parameters),
            "optioneel": list(q.optioneel),
            "kolommen": list(q.kolommen),
        }
        for q in bibliotheek.laad_alle().values()
    ]


__all__: Sequence[str] = (
    "GeenBeheerder",
    "GeenLeesreplica",
    "GeenSelect",
    "OntbrekendeParameter",
    "Uitkomst",
    "lees_engine",
    "overzicht",
    "voer_query_uit",
    "voer_sql_uit",
)


def _stil(_: Iterable[Any]) -> None:  # pragma: no cover — houdt de import van Iterable nuttig voor type-checkers
    return None
