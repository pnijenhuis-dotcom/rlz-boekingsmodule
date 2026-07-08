from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import Engine, text

from app import cli
from app.auth import service
from app.db.models import GebruikerRol


def test_bootstrap_maakt_eerste_beheerder_aan(admin_engine: Engine) -> None:
    resultaat = service.bootstrap_eerste_beheerder(naam="Eerste Beheerder", e_mail="beheerder@test.local")

    with admin_engine.connect() as conn:
        rol, status = conn.execute(
            text("SELECT rol, status FROM platform.gebruiker WHERE id = :id"), {"id": resultaat.gebruiker_id}
        ).one()
        aantal_uitnodigingen = conn.execute(
            text("SELECT count(*) FROM platform.uitnodiging WHERE gebruiker_id = :id"),
            {"id": resultaat.gebruiker_id},
        ).scalar_one()
        actie = conn.execute(
            text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker' AND record_id = :id"),
            {"id": resultaat.gebruiker_id},
        ).scalar_one()

    assert rol == GebruikerRol.BEHEERDER.value
    assert status == "uitgenodigd"
    assert aantal_uitnodigingen == 1
    assert actie == "eerste_beheerder_bootstrapped"


def test_bootstrap_is_idempotent_weigert_tweede_beheerder(admin_engine: Engine) -> None:
    service.bootstrap_eerste_beheerder(naam="Eerste", e_mail="eerste@test.local")

    with pytest.raises(service.AuthError, match="bestaat al een Beheerder"):
        service.bootstrap_eerste_beheerder(naam="Tweede", e_mail="tweede@test.local")

    with admin_engine.connect() as conn:
        aantal_beheerders = conn.execute(
            text("SELECT count(*) FROM platform.gebruiker WHERE rol = 'beheerder'")
        ).scalar_one()
    assert aantal_beheerders == 1


def test_bootstrap_token_werkt_met_bestaande_accept_en_totp_flow() -> None:
    """Het bootstrap-commando maakt geen aparte activatieroute — de gewone
    accepteer_uitnodiging()/bevestig_totp()-flow moet het opgeleverde token gewoon accepteren."""
    resultaat = service.bootstrap_eerste_beheerder(naam="Peter", e_mail="peter@test.local")

    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
    code = pyotp.TOTP(acceptatie.secret).now()
    paar = service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)

    assert paar.access_token
    assert paar.refresh_token


def test_cli_bootstrap_beheerder_slaagt_en_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    exitcode = cli.main(["bootstrap-beheerder", "--naam", "CLI Beheerder", "--e-mail", "cli@test.local"])
    uit = capsys.readouterr()
    assert exitcode == 0
    assert "Eerste Beheerder aangemaakt" in uit.out

    exitcode = cli.main(["bootstrap-beheerder", "--naam", "Nog een", "--e-mail", "nogeen@test.local"])
    uit = capsys.readouterr()
    assert exitcode == 1
    assert "bestaat al een Beheerder" in uit.err
