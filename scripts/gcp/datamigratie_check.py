#!/usr/bin/env python3
"""Datamigratie-verificatie (GCP-draaiboek F1.6, tranche 2): vergelijkt bron- en
doeldatabase ná de pg_dump/restore — rijtellingen per tabel (schema's platform +
boekhouding) én per-administratie-tellingen voor elke tabel met een
administratie_id-kolom (documenten, werkvoorraad, audit, boekingsgeheugen, …).

Bewust generiek via information_schema: een tabel die later bij komt telt automatisch
mee en kan nooit stil buiten de vergelijking vallen. De alembic-versie moet identiek
zijn (zelfde migratiekop aan beide kanten — anders vergelijk je appels met peren).

Gebruik (repo-root, backend-venv):

    BRON_DATABASE_URL="postgresql+psycopg://postgres@localhost:5433/boekhouding" \\
    DOEL_DATABASE_URL="postgresql+psycopg://<cloud-sql-user>@<host>/boekhouding" \\
    backend/.venv/bin/python scripts/gcp/datamigratie_check.py

Exit 0 = alle tellingen gelijk; exit 1 = verschil of fout (met rapport). Read-only:
dit script schrijft in géén van beide databases iets.

NB documenten-bestanden (GCS-bucket vs ./.data/documenten) zijn een aparte check in het
stappenplan (gsutil rsync -n als droogloop-vergelijking) — dit script dekt de database."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

SCHEMAS = ("platform", "boekhouding")


def _engine(url: str):
    from sqlalchemy import create_engine

    return create_engine(url)


def _alembic_versie(conn) -> str | None:
    from sqlalchemy import text

    if not conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar():
        return None
    return conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()


def _tabellen(conn) -> list[tuple[str, str]]:
    from sqlalchemy import text

    rijen = conn.execute(
        text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema = ANY(:schemas) AND table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name"
        ),
        {"schemas": list(SCHEMAS)},
    )
    return [(r[0], r[1]) for r in rijen]


def _heeft_administratie_kolom(conn, schema: str, tabel: str) -> bool:
    from sqlalchemy import text

    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = :s "
                "AND table_name = :t AND column_name = 'administratie_id'"
            ),
            {"s": schema, "t": tabel},
        ).scalar()
    )


def _telling(conn, schema: str, tabel: str) -> int:
    from sqlalchemy import text

    return conn.execute(text(f'SELECT count(*) FROM "{schema}"."{tabel}"')).scalar_one()


def _per_administratie(conn, schema: str, tabel: str) -> dict[str, int]:
    from sqlalchemy import text

    rijen = conn.execute(
        text(f'SELECT administratie_id::text, count(*) FROM "{schema}"."{tabel}" GROUP BY administratie_id')
    )
    return {r[0]: r[1] for r in rijen}


def main() -> int:
    bron_url = os.environ.get("BRON_DATABASE_URL")
    doel_url = os.environ.get("DOEL_DATABASE_URL")
    if not bron_url or not doel_url:
        print("FOUT: zet BRON_DATABASE_URL én DOEL_DATABASE_URL (zie de docstring).")
        return 1

    bron_engine, doel_engine = _engine(bron_url), _engine(doel_url)
    verschillen: list[str] = []
    try:
        with bron_engine.connect() as bron, doel_engine.connect() as doel:
            v_bron, v_doel = _alembic_versie(bron), _alembic_versie(doel)
            print(f"alembic_version  bron={v_bron}  doel={v_doel}")
            if v_bron != v_doel:
                verschillen.append(f"alembic_version wijkt af: bron {v_bron} vs doel {v_doel}")

            bron_tabellen, doel_tabellen = set(_tabellen(bron)), set(_tabellen(doel))
            for schema, tabel in sorted(bron_tabellen - doel_tabellen):
                verschillen.append(f"tabel {schema}.{tabel} ontbreekt in DOEL")
            for schema, tabel in sorted(doel_tabellen - bron_tabellen):
                verschillen.append(f"tabel {schema}.{tabel} ontbreekt in BRON")

            print(f"\n{'tabel':45s} {'bron':>8s} {'doel':>8s}")
            for schema, tabel in sorted(bron_tabellen & doel_tabellen):
                n_bron, n_doel = _telling(bron, schema, tabel), _telling(doel, schema, tabel)
                marker = "" if n_bron == n_doel else "  <-- VERSCHIL"
                print(f"{schema + '.' + tabel:45s} {n_bron:8d} {n_doel:8d}{marker}")
                if n_bron != n_doel:
                    verschillen.append(f"{schema}.{tabel}: bron {n_bron} vs doel {n_doel}")

                if n_bron and _heeft_administratie_kolom(bron, schema, tabel):
                    per_bron, per_doel = (
                        _per_administratie(bron, schema, tabel),
                        _per_administratie(doel, schema, tabel),
                    )
                    for admin_id in sorted(set(per_bron) | set(per_doel), key=str):
                        a, b = per_bron.get(admin_id, 0), per_doel.get(admin_id, 0)
                        if a != b:
                            verschillen.append(
                                f"{schema}.{tabel} administratie {admin_id}: bron {a} vs doel {b}"
                            )
                            print(f"    administratie {admin_id}: {a} vs {b}  <-- VERSCHIL")
    finally:
        bron_engine.dispose()
        doel_engine.dispose()

    print()
    if verschillen:
        print(f"NIET GELIJK — {len(verschillen)} verschil(len):")
        for v in verschillen:
            print(f"  - {v}")
        return 1
    print("GELIJK: alle tabellen en per-administratie-tellingen komen overeen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
