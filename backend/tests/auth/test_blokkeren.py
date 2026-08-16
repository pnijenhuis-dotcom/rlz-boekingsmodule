"""Gebruiker blokkeren/heractiveren (beheer-mini 2026-08-16, migratie 0052).

Poortlogica: blokkade bijt per direct (sessies dood, refresh weigert, login weigert),
guards zijn server-side onvoorwaardelijk (eigen account, systeem-actor, laatste actieve
Beheerder), heractiveren zet exact de status van vóór de blokkade terug en alles is geauditeerd.
"""

from __future__ import annotations

import uuid

import pyotp
import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

from .conftest import ActieveGebruiker


def _status(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM platform.gebruiker WHERE id = :id"), {"id": gebruiker_id}
        ).scalar_one()


def test_blokkeren_zet_status_en_audit(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)

    assert _status(admin_engine, actieve_gebruiker.id) == "geblokkeerd"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT geblokkeerd_op, geblokkeerd_door, status_voor_blokkade "
                "FROM platform.gebruiker WHERE id = :id"
            ),
            {"id": actieve_gebruiker.id},
        ).one()
    assert rij.geblokkeerd_op is not None
    assert rij.geblokkeerd_door == beheerder_id
    assert rij.status_voor_blokkade == "actief"
    with admin_engine.connect() as conn:
        acties = conn.execute(
            text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker' AND record_id = :id"),
            {"id": actieve_gebruiker.id},
        ).scalars().all()
    assert "gebruiker_geblokkeerd" in acties


def test_blokkade_maakt_refresh_en_login_dood(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
) -> None:
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)

    # De lopende sessie (refresh-token uit de activatie) is per direct ingetrokken.
    with pytest.raises(service.AuthError):
        service.vernieuw_token(refresh_token=actieve_gebruiker.activatie_paar.refresh_token)

    # Nieuw inloggen wordt geweigerd — generieke fout (geen status-enumeratie).
    code = pyotp.TOTP(actieve_gebruiker.secret).now()
    with pytest.raises(service.AuthError):
        service.login(e_mail=actieve_gebruiker.e_mail, wachtwoord=actieve_gebruiker.wachtwoord, totp_code=code)


def test_eigen_account_niet_blokkeerbaar(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="eigen account"):
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=beheerder_id)


def test_systeem_actor_niet_blokkeerbaar(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="systeemgebruiker"):
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=SYSTEEM_ACTOR_ID)


def test_laatste_actieve_beheerder_niet_blokkeerbaar(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
) -> None:
    """De fixture-beheerder is de enige actieve Beheerder; ook een andere (niet-zelf) actor
    mag hem dan niet blokkeren — de guard is onvoorwaardelijk server-side."""
    with pytest.raises(service.AuthError, match="laatste actieve Beheerder"):
        service.blokkeer_gebruiker(actor_id=actieve_gebruiker.id, doel_gebruiker_id=beheerder_id)


def test_niet_laatste_beheerder_wel_blokkeerbaar(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    tweede = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Tweede Beheerder', :mail, 'beheerder', 'actief')"
            ),
            {"id": tweede, "mail": f"{tweede}@test.local"},
        )
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=tweede)
    assert _status(admin_engine, tweede) == "geblokkeerd"


def test_dubbel_blokkeren_weigert(beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    with pytest.raises(service.AuthError, match="al geblokkeerd"):
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)


def test_heractiveren_zet_vorige_status_terug(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    service.heractiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)

    assert _status(admin_engine, actieve_gebruiker.id) == "actief"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT geblokkeerd_op, geblokkeerd_door, status_voor_blokkade "
                "FROM platform.gebruiker WHERE id = :id"
            ),
            {"id": actieve_gebruiker.id},
        ).one()
    assert rij.geblokkeerd_op is None and rij.geblokkeerd_door is None and rij.status_voor_blokkade is None
    with admin_engine.connect() as conn:
        acties = conn.execute(
            text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker' AND record_id = :id"),
            {"id": actieve_gebruiker.id},
        ).scalars().all()
    assert "gebruiker_geheractiveerd" in acties

    # NB: een directe login-rondgang kan hier niet — de TOTP-replaybescherming weigert een code
    # uit dezelfde tijdstap als de activatie (zie ActieveGebruiker-docstring). Dat inloggen op
    # status 'actief' werkt, dekken de bestaande login-tests; hier telt de status-terugkeer.


def test_heractiveren_half_geactiveerd_gaat_terug_de_flow_in(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Een gebruiker die nog in 'uitgenodigd' stond, komt na blokkade + heractivering weer in
    'uitgenodigd' — nooit in 'actief' zonder credentials."""
    doel = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Nog Niet Actief",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    ).gebruiker_id

    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=doel)
    service.heractiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=doel)
    assert _status(admin_engine, doel) == "uitgenodigd"


def test_heractiveren_van_niet_geblokkeerde_weigert(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
) -> None:
    with pytest.raises(service.AuthError, match="niet geblokkeerd"):
        service.heractiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)


def test_lijst_toont_blokkadegegevens(beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    lijst = service.lijst_gebruikers(actor_id=beheerder_id)
    rij = next(item for item in lijst if item.id == actieve_gebruiker.id)
    assert rij.status.value == "geblokkeerd"
    assert rij.geblokkeerd_op is not None
    assert rij.geblokkeerd_door_naam == "Test-Beheerder"
