"""Guard op de volledigheid van Base.metadata in migrations/env.py (afsluitroutine-adoptie,
2026-08-07 — vastgoed-patroon, hier aangescherpt omdat deze repo wél ORM-modellen heeft).

Twee borgingen:
1. env.py importeert élke `app/**/models.py` — een nieuwe model-module die daar ontbreekt maakt
   `alembic check`/autogenerate stil onbetrouwbaar (vergelijking tegen een half model → foute
   drop-voorstellen).
2. Base.metadata (met alle modules geïmporteerd) dekt exact de tabellen van de live, volledig
   gemigreerde testdatabase — een migratie-tabel zonder model of een model zonder migratie valt
   hier direct om.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.config import settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Tabellen die bewust géén ORM-model hebben. Alleen met motivering toevoegen.
_BEWUST_ZONDER_MODEL: set[str] = {
    "platform.alembic_version",  # Alembic's eigen versietabel (alembic.ini version_table_schema)
    "public.alembic_version",  # idem, als de versietabel in public staat
}


def _alle_model_modules() -> list[str]:
    return sorted(
        ".".join(p.relative_to(_BACKEND_ROOT).with_suffix("").parts)
        for p in (_BACKEND_ROOT / "app").rglob("models.py")
    )


class TestEnvPyImporteertAlleModelModules:
    def test_elke_model_module_staat_in_env_py(self) -> None:
        env_tekst = (_BACKEND_ROOT / "migrations" / "env.py").read_text()
        ontbrekend = [m for m in _alle_model_modules() if m not in env_tekst]
        assert not ontbrekend, (
            f"model-module(s) {ontbrekend} worden niet geïmporteerd in migrations/env.py — "
            "Base.metadata is dan incompleet en autogenerate/alembic check stelt foute drops voor"
        )


class TestMetadataDektLiveTestdatabase:
    def test_metadata_tabellen_gelijk_aan_testdatabase(self) -> None:
        import importlib

        for module in _alle_model_modules():
            importlib.import_module(module)
        from app.db.models import Base

        meta_tabellen = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()}

        engine = create_engine(settings.test_database_url)
        try:
            inspector = inspect(engine)
            db_tabellen = {
                f"{schema}.{tabel}"
                for schema in ("platform", "boekhouding", "mi")
                for tabel in inspector.get_table_names(schema=schema)
            }
        finally:
            engine.dispose()
        db_tabellen -= _BEWUST_ZONDER_MODEL

        zonder_model = db_tabellen - meta_tabellen
        zonder_migratie = meta_tabellen - db_tabellen
        fouten = []
        if zonder_model:
            fouten.append(
                f"tabellen in de testdatabase zonder ORM-model: {sorted(zonder_model)} — model "
                "toevoegen (en importeren in env.py) of expliciet motiveren in _BEWUST_ZONDER_MODEL"
            )
        if zonder_migratie:
            fouten.append(
                f"modellen zonder tabel in de gemigreerde testdatabase: {sorted(zonder_migratie)} "
                "— migratie vergeten?"
            )
        assert not fouten, "\n".join(fouten)
