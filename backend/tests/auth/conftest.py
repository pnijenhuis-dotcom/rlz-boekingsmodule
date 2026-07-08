from __future__ import annotations

import uuid
from dataclasses import dataclass

import pyotp
import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol


@pytest.fixture
def beheerder_id(admin_engine: Engine) -> uuid.UUID:
    """Bootstrapt een actieve Beheerder rechtstreeks als schema-owner. In de praktijk is er nog
    geen 'nodig een eerste Beheerder uit'-mechanisme (kip-ei-probleem) — open item, zie
    eindrapport."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Test-Beheerder', :mail, 'beheerder', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    return gid


@dataclass(frozen=True)
class ActieveGebruiker:
    """Volledig geactiveerde gebruiker (uitgenodigd -> wachtwoord -> TOTP bevestigd) — herbruikbaar
    voor tests die daadwerkelijk moeten inloggen (login()/vernieuw_token()), i.p.v. de kortere
    `_bearer()`-shortcut die alleen een access-token nodig heeft.

    `activatie_paar` is de TokenPaar die bevestig_totp() al uitgeeft bij activatie — een tweede,
    onafhankelijke sessie naast een latere login()-aanroep. Handig voor "meerdere sessies
    tegelijk"-tests (logout scoping) zonder tegen verify_code()'s ±1-stap-venster aan te lopen:
    twee losse login()-aanroepen vlak na elkaar hebben geen ruimte voor twee verschillende, nog
    niet geaccepteerde TOTP-stappen binnen hetzelfde venster."""

    id: uuid.UUID
    e_mail: str
    wachtwoord: str
    secret: str
    activatie_paar: service.TokenPaar


@pytest.fixture
def actieve_gebruiker(beheerder_id: uuid.UUID) -> ActieveGebruiker:
    e_mail = f"{uuid.uuid4()}@test.local"
    wachtwoord = "een-heel-lang-wachtwoord"
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Actieve Gebruiker",
        e_mail=e_mail,
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord=wachtwoord)
    code = pyotp.TOTP(acceptatie.secret).now()
    activatie_paar = service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)
    return ActieveGebruiker(
        id=resultaat.gebruiker_id,
        e_mail=e_mail,
        wachtwoord=wachtwoord,
        secret=acceptatie.secret,
        activatie_paar=activatie_paar,
    )


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Scope-test', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid
