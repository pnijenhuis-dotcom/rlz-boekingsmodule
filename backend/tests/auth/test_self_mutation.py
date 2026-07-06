from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol


def test_beheerder_kan_eigen_rol_niet_wijzigen(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="eigen rol"):
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=beheerder_id, nieuwe_rol=GebruikerRol.BOEKHOUDING)


def test_beheerder_kan_eigen_scope_niet_wijzigen(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="eigen scope"):
        service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=beheerder_id, administratie_id=administratie_id)
    with pytest.raises(service.AuthError, match="eigen scope"):
        service.verwijder_scope(
            actor_id=beheerder_id, doel_gebruiker_id=beheerder_id, administratie_id=administratie_id
        )


def test_beheerder_kan_rol_van_ander_wel_wijzigen(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Ander",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    ).gebruiker_id

    service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=doel, nieuwe_rol=GebruikerRol.BOEKHOUDING_PROJECTEN)

    with admin_engine.connect() as conn:
        rol = conn.execute(text("SELECT rol FROM platform.gebruiker WHERE id = :id"), {"id": doel}).scalar_one()
    assert rol == "boekhouding_projecten"

    with admin_engine.connect() as conn:
        actie = conn.execute(
            text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker' AND record_id = :id"),
            {"id": doel},
        ).scalar_one()
    assert actie == "rol_wijziging"


def test_tweede_beheerder_aanwijzen_door_andere_beheerder_werkt(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    """'Tweede beheerder alleen door een andere beheerder' volgt automatisch uit Beheerder-only +
    self-mutation-blokkade: deze actor (bestaande Beheerder) wijst een ANDERE gebruiker aan als
    Beheerder — nooit zichzelf."""
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Toekomstig Beheerder",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    ).gebruiker_id

    service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=doel, nieuwe_rol=GebruikerRol.BEHEERDER)

    with admin_engine.connect() as conn:
        rol = conn.execute(text("SELECT rol FROM platform.gebruiker WHERE id = :id"), {"id": doel}).scalar_one()
    assert rol == "beheerder"


def test_onbekende_doelgebruiker_faalt(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="Onbekende gebruiker"):
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=uuid.uuid4(), nieuwe_rol=GebruikerRol.BOEKHOUDING)
