"""Blok 6 run 11-09 middag — beginscherm kantoor-web traag (kliktest Peter 11-09; 34 → 71 administraties in twee
dagen).
Cloud Logging vóór (08-09 t/m 11-09): `GET /werkvoorraad/overzicht` p50 2,8 s / p95 6,1 s — een lus per administratie
met
`scoped_session`-wissel en ±10 queries. Deze tests zijn de MEETLAT (schaalregel 2 → 2000):

1. het aantal SQL-statements van de leesroute is CONSTANT in het aantal administraties (N=5 == N=200, tolerantie ≤ +3)
   en het aantal `scoped_session`-wissels (set_config-paren) per request is één;
2. dat geldt voor de Beheerder én voor een niet-Beheerder mét scope — en RLS blijft de waarheid: een niet-Beheerder ziet
   in de set-based cache-lezing uitsluitend de administraties in zijn scope (app-DB-rol, geen owner-test);
3. grove lokale latency-indicatie vóór (directe telling per administratie) / ná (cache) bij N=200 — in het rapport.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import Engine, event, select, text

from app.auth import service as auth_service
from app.db import session as db_session
from app.db.session import scoped_session
from app.documenten import service
from app.werkvoorraad import tellers
from app.werkvoorraad.models import WerkvoorraadTellerCache

TOLERANTIE = 3


class _Teller:
    """Telt élk statement dat via de service-engine naar Postgres gaat (incl. set_config = scope-wissel)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def __enter__(self) -> _Teller:
        event.listen(db_session.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(db_session.engine, "before_cursor_execute", self)

    @property
    def scope_wissels(self) -> int:
        return sum(1 for s in self.statements if "app.current_administratie_id" in s)


def _maak_administraties(admin_engine: Engine, n: int) -> list[tuple[uuid.UUID, str]]:
    uit = []
    with admin_engine.begin() as conn:
        for i in range(n):
            aid = uuid.uuid4()
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
                {"id": aid, "naam": f"Klant {i:03d}", "rlz": f"rlz-{aid}"},
            )
            uit.append((aid, f"Klant {i:03d}"))
    return uit


def _maak_boekhouder(admin_engine: Engine) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Boekhouder N', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    return gid


def _tel(
    actor: uuid.UUID, administraties: list[tuple[uuid.UUID, str]]
) -> tuple[_Teller, list[service.WerkvoorraadKlant]]:
    with _Teller() as teller:
        klanten = service.werkvoorraad_overzicht(administratie_ids_met_naam=administraties, actor_id=actor)
    return teller, klanten


@pytest.mark.parametrize("rol", ["beheerder", "boekhouding"])
def test_statements_constant_in_aantal_administraties(
    rol: str, admin_engine: Engine, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
) -> None:
    """N=5 en N=200: exact hetzelfde aantal statements (± tolerantie) en precies één scope-wissel."""
    klein = _maak_administraties(admin_engine, 5)
    groot = klein + _maak_administraties(admin_engine, 195)
    if rol == "beheerder":
        actor = beheerder_id
    else:
        actor = gescoopte_gebruiker
        for aid, _ in groot:
            auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=actor, administratie_id=aid)
    # Cache gevuld zoals ná de nachtelijke herberekening (sync-alles).
    rapport = tellers.herreken_alle(administratie_ids=[aid for aid, _ in groot])
    assert rapport.fouten == [] and rapport.administraties == 200

    t5, k5 = _tel(actor, klein)
    t200, k200 = _tel(actor, groot)
    assert len(k5) == 5 and len(k200) == 200
    assert all(k.te_controleren == 0 for k in k200)

    aantal_5, aantal_200 = len(t5.statements), len(t200.statements)
    print(
        f"\n[blok 6] rol={rol}: statements N=5 → {aantal_5}, N=200 → {aantal_200}; "
        f"scope-wissels N=200 → {t200.scope_wissels}"
    )
    assert aantal_200 <= aantal_5 + TOLERANTIE, (aantal_5, aantal_200)
    assert t200.scope_wissels == 1, t200.statements
    # Concreet: set_config administratie + set_config actor + één SELECT over de cache = 3 statements.
    assert aantal_200 <= 3 + TOLERANTIE


def test_rls_niet_beheerder_ziet_alleen_eigen_scope_in_de_cache(admin_engine: Engine, beheerder_id: uuid.UUID) -> None:
    """Set-based lezen onder RLS (app-rol): de cache-policy (0136) laat een niet-Beheerder uitsluitend rijen van zijn
    eigen scope zien; zonder scope = nul rijen (fail-closed), Beheerder = alles."""
    administraties = _maak_administraties(admin_engine, 3)
    tellers.herreken_alle(administratie_ids=[aid for aid, _ in administraties])
    met_scope = _maak_boekhouder(admin_engine)
    zonder_scope = _maak_boekhouder(admin_engine)
    in_scope = [administraties[0][0], administraties[2][0]]
    for aid in in_scope:
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=met_scope, administratie_id=aid)

    def zichtbaar(actor: uuid.UUID) -> set[uuid.UUID]:
        with scoped_session(None, actor_id=actor) as session:
            return set(session.scalars(select(WerkvoorraadTellerCache.administratie_id).distinct()).all())

    assert zichtbaar(met_scope) == set(in_scope)
    assert zichtbaar(zonder_scope) == set()
    assert zichtbaar(beheerder_id) >= {aid for aid, _ in administraties}


def test_latency_indicatie_direct_versus_cache_n200(admin_engine: Engine, beheerder_id: uuid.UUID) -> None:
    """Grove lokale indicatie voor het rapport (geen assert op tijd — de echte nameting is Cloud Logging ná deploy):
    directe telling per administratie (het oude pad, actor_id=None) versus de set-based cache-lezing bij N=200."""
    groot = _maak_administraties(admin_engine, 200)
    t0 = time.perf_counter()
    service.werkvoorraad_overzicht(administratie_ids_met_naam=groot)  # oud pad: telt direct + vult de cache
    direct_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    klanten = service.werkvoorraad_overzicht(administratie_ids_met_naam=groot, actor_id=beheerder_id)
    cache_ms = (time.perf_counter() - t0) * 1000
    assert len(klanten) == 200
    print(f"\n[blok 6] N=200 lokaal: direct per administratie {direct_ms:.0f} ms → set-based cache {cache_ms:.0f} ms")
    assert cache_ms < direct_ms
