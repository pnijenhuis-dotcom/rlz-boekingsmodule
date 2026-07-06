from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.auth import service
from app.db.models import GebruikerRol
from app.db.session import scoped_session, session_factory_for


def test_rls_blokkeert_scope_insert_zonder_beheerder_of_matchende_administratie(
    app_engine: Engine, admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Non-superuser test-rol (boekhouding_app, net als app_engine elders): een sessie die niet
    als Beheerder telt én niet op de doel-administratie gescoped is, mag nooit een scope-rij
    kunnen inserten — zelfs niet als de applicatielaag een bug zou hebben en het toch probeert."""
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Doelwit",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[],
    ).gebruiker_id

    factory = session_factory_for(app_engine)
    # Sessie gescoped op een ANDERE administratie dan administratie_id, actor = de niet-beheerder
    # doelgebruiker zelf (dus geen current_actor_is_beheerder()-bypass).
    with scoped_session(uuid.uuid4(), actor_id=doel, session_factory=factory) as session:
        with pytest.raises(DBAPIError, match="row-level security"):
            session.execute(
                text(
                    "INSERT INTO platform.gebruiker_administratie (gebruiker_id, administratie_id) "
                    "VALUES (:g, :a)"
                ),
                {"g": doel, "a": administratie_id},
            )
        session.rollback()


def test_scope_toevoegen_en_verwijderen_via_servicelaag(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Accordeur",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[],
    ).gebruiker_id

    service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=doel, administratie_id=administratie_id)
    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.gebruiker_administratie WHERE gebruiker_id = :g"), {"g": doel}
        ).scalar_one()
    assert aantal == 1

    service.verwijder_scope(actor_id=beheerder_id, doel_gebruiker_id=doel, administratie_id=administratie_id)
    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.gebruiker_administratie WHERE gebruiker_id = :g"), {"g": doel}
        ).scalar_one()
    assert aantal == 0


def test_audit_event_bij_scope_toevoegen_en_verwijderen(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Geaudit",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[],
    ).gebruiker_id

    service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=doel, administratie_id=administratie_id)
    service.verwijder_scope(actor_id=beheerder_id, doel_gebruiker_id=doel, administratie_id=administratie_id)

    with admin_engine.connect() as conn:
        acties = conn.execute(
            text(
                "SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker_administratie' "
                "AND record_id = :g ORDER BY tijdstip"
            ),
            {"g": doel},
        ).scalars().all()
    assert acties == ["scope_toegevoegd", "scope_verwijderd"]


def test_initiele_scope_bij_uitnodiging_wordt_geaudit(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Met initiele scope",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[administratie_id],
    )
    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.gebruiker_administratie WHERE gebruiker_id = :g"),
            {"g": resultaat.gebruiker_id},
        ).scalar_one()
        actie = conn.execute(
            text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker_administratie' AND record_id = :g"),
            {"g": resultaat.gebruiker_id},
        ).scalar_one()
    assert aantal == 1
    assert actie == "scope_toegevoegd"
