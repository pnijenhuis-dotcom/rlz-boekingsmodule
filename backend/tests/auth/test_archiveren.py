"""Gebruiker archiveren/dearchiveren (feedbackronde 26-08 punt 1, migratie 0075 — 0052-patroon).

Archiveren = uit alle default-lijsten, toegang per direct dicht (sessies dood, login weigert),
historie onaangetast; dearchiveren zet exact de status van vóór archivering terug. Guards
server-side onvoorwaardelijk (eigen account, systeem-actor, laatste actieve Beheerder); open
werk is een waarschuwing mét aantallen, geen blokkade.
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


def _acties(admin_engine: Engine, gebruiker_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker' AND record_id = :id"),
                {"id": gebruiker_id},
            ).scalars()
        )


def test_archiveren_zet_status_kolommen_en_audit(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)

    assert _status(admin_engine, actieve_gebruiker.id) == "gearchiveerd"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT gearchiveerd_op, gearchiveerd_door, status_voor_archivering "
                "FROM platform.gebruiker WHERE id = :id"
            ),
            {"id": actieve_gebruiker.id},
        ).one()
    assert rij.gearchiveerd_op is not None
    assert rij.gearchiveerd_door == beheerder_id
    assert rij.status_voor_archivering == "actief"
    assert "gebruiker_gearchiveerd" in _acties(admin_engine, actieve_gebruiker.id)


def test_archivering_maakt_refresh_en_login_dood(beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    with pytest.raises(service.AuthError):
        service.vernieuw_token(refresh_token=actieve_gebruiker.activatie_paar.refresh_token)
    code = pyotp.TOTP(actieve_gebruiker.secret).now()
    with pytest.raises(service.AuthError):
        service.login(e_mail=actieve_gebruiker.e_mail, wachtwoord=actieve_gebruiker.wachtwoord, totp_code=code)


def test_eigen_account_niet_archiveerbaar(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="eigen account"):
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=beheerder_id)


def test_systeem_actor_niet_archiveerbaar(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="systeemgebruiker"):
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=SYSTEEM_ACTOR_ID)


def test_laatste_actieve_beheerder_niet_archiveerbaar(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    ander = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Tweede', :mail, 'beheerder', 'actief')"
            ),
            {"id": ander, "mail": f"{ander}@test.local"},
        )
    # Twee actieve beheerders: de tweede mag weg (de eerste blijft over)…
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=ander)
    # …maar daarna is beheerder_id de laatste — een derde beheerder kan hem niet archiveren.
    derde = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Derde', :mail, 'beheerder', 'geblokkeerd')"
            ),
            {"id": derde, "mail": f"{derde}@test.local"},
        )
    with pytest.raises(service.AuthError, match="laatste actieve Beheerder"):
        service.archiveer_gebruiker(actor_id=derde, doel_gebruiker_id=beheerder_id)


def test_dubbel_archiveren_weigert(beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    with pytest.raises(service.AuthError, match="al gearchiveerd"):
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)


def test_gearchiveerde_kan_niet_geblokkeerd_of_gemuteerd_worden(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    with pytest.raises(service.AuthError, match="dearchiveer eerst"):
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    with pytest.raises(service.AuthError, match="dearchiveer eerst"):
        service.wijzig_rol(
            actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id, nieuwe_rol=GebruikerRol.BOEKHOUDING
        )
    # Punt 22 (opruimrun 28-08): e-mail wijzigen mág wél op een gearchiveerd account (adres vrijmaken
    # zonder carrousel) — zonder uitnodigingsmail; zie tests/auth/test_e_mail_opruimrun_28_08.py.
    gewijzigd = service.wijzig_e_mail(
        actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id, nieuw_e_mail="nieuw@test.local"
    )
    assert gewijzigd.nieuw_e_mail == "nieuw@test.local" and gewijzigd.vernieuwde_uitnodiging is None


def test_dearchiveren_zet_vorige_status_terug(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    service.dearchiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)

    assert _status(admin_engine, actieve_gebruiker.id) == "actief"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT gearchiveerd_op, gearchiveerd_door, status_voor_archivering "
                "FROM platform.gebruiker WHERE id = :id"
            ),
            {"id": actieve_gebruiker.id},
        ).one()
    assert rij.gearchiveerd_op is None and rij.gearchiveerd_door is None and rij.status_voor_archivering is None
    assert "gebruiker_gedearchiveerd" in _acties(admin_engine, actieve_gebruiker.id)


def test_geblokkeerde_die_gearchiveerd_wordt_komt_geblokkeerd_terug(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    """Archiveren is geen heractiveren: de blokkade-status van vóór archivering blijft bewaard."""
    service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert _status(admin_engine, actieve_gebruiker.id) == "gearchiveerd"
    service.dearchiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert _status(admin_engine, actieve_gebruiker.id) == "geblokkeerd"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT geblokkeerd_op, status_voor_blokkade FROM platform.gebruiker WHERE id = :id"),
            {"id": actieve_gebruiker.id},
        ).one()
    assert rij.geblokkeerd_op is not None and rij.status_voor_blokkade == "actief"


def test_dearchiveren_van_niet_gearchiveerde_weigert(beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
    with pytest.raises(service.AuthError, match="niet gearchiveerd"):
        service.dearchiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)


def test_lijst_verbergt_gearchiveerden_standaard_en_toont_ze_op_verzoek(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
) -> None:
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert all(item.id != actieve_gebruiker.id for item in service.lijst_gebruikers(actor_id=beheerder_id))
    lijst = service.lijst_gebruikers(actor_id=beheerder_id, inclusief_gearchiveerd=True)
    rij = next(item for item in lijst if item.id == actieve_gebruiker.id)
    assert rij.status.value == "gearchiveerd"
    assert rij.gearchiveerd_op is not None
    assert rij.gearchiveerd_door_naam == "Test-Beheerder"


def test_open_werk_telling_is_nul_zonder_werk_en_telt_open_accorderingsstap(
    beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    werk = service.open_werk_van_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert (werk.open_accorderingen, werk.weekstaten_ter_keuring, werk.eigen_open_weekstaten) == (0, 0, 0)
    assert werk.heeft_open_werk is False

    # Eén open accorderingsronde met een vereiste stap zonder besluit voor deze gebruiker.
    document_id, accordering_id = uuid.uuid4(), uuid.uuid4()
    service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id, administratie_id=administratie_id)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, soort, bestandsnaam, sha256_hash, "
                "status, opslag_pad) VALUES (:d, :a, 'upload', 'inkoopfactuur', 'f.pdf', :h, 'ter_accordering', 'p')"
            ),
            {"d": document_id, "a": administratie_id, "h": uuid.uuid4().hex},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.document_accordering (id, administratie_id, document_id, status, "
                "aangeboden_door) VALUES (:id, :a, :d, 'open', :b)"
            ),
            {"id": accordering_id, "a": administratie_id, "d": document_id, "b": beheerder_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.accordering_stap (id, administratie_id, accordering_id, volgnummer, "
                "accordeur_gebruiker_id, vereist) VALUES (:id, :a, :acc, 1, :g, true)"
            ),
            {"id": uuid.uuid4(), "a": administratie_id, "acc": accordering_id, "g": actieve_gebruiker.id},
        )
    werk = service.open_werk_van_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert werk.open_accorderingen == 1 and werk.heeft_open_werk is True
    # Open werk is een waarschuwing, geen blokkade: archiveren mag gewoon.
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
    assert _status(admin_engine, actieve_gebruiker.id) == "gearchiveerd"


def test_planning_pool_en_veldwerkers_paneel_sluiten_gearchiveerden_uit(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    from app.uren import overzichten

    zzper = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Zzp Archief', :mail, 'zzper', 'actief')"
            ),
            {"id": zzper, "mail": f"{zzper}@test.local"},
        )
    assert any(k.gebruiker_id == zzper for k in overzichten.veldgebruikers_overzicht(actor_id=beheerder_id))
    service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=zzper)
    assert all(k.gebruiker_id != zzper for k in overzichten.veldgebruikers_overzicht(actor_id=beheerder_id))
