"""Rollen, module-recht en koppelingen (fase 1): de drie veldrollen volgen de accordeur-
authcadans (passkey-activatie, externe-rol-gates), het module-recht 'Meerwerk & urenstaten'
(0019-patroon: DB-CHECK + recht-helper), en het kantoor-beheer van de koppeltabellen
(uitvoerder↔project, detacheerder↔zzp'er) mét RLS en audit."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.auth import service as auth_service
from app.auth.rollen import EXTERNE_APP_ROLLEN, is_externe_app_rol, is_kantoorrol
from app.db.models import DetacheerderKoppeling, GebruikerRol
from app.db.session import scoped_session
from app.uren import service
from tests.uren.conftest import maak_gebruiker


class TestRollen:
    def test_veldrollen_zijn_externe_app_rollen(self):
        assert {GebruikerRol.ZZPER, GebruikerRol.UITVOERDER, GebruikerRol.DETACHEERDER} <= EXTERNE_APP_ROLLEN
        assert is_externe_app_rol(GebruikerRol.KLANT_ACCORDEUR)
        assert not is_kantoorrol(GebruikerRol.ZZPER)
        assert is_kantoorrol(GebruikerRol.BEHEERDER)

    @pytest.mark.parametrize("rol", [GebruikerRol.ZZPER, GebruikerRol.UITVOERDER, GebruikerRol.DETACHEERDER])
    def test_activering_volgt_de_passkey_flow(self, beheerder_id, rol):
        """0040-lijn: een veldrol-uitnodiging accepteren geeft de passkey-tak (wacht_op_passkey
        + setup-token), niet de kantoor-TOTP-tak."""
        resultaat = auth_service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Veldwerker",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=rol,
            administratie_ids=[],
        )
        acceptatie = auth_service.accepteer_uitnodiging(
            token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord"
        )
        assert acceptatie.soort == "passkey"
        assert acceptatie.passkey_setup_token is not None


class TestModuleRecht:
    @staticmethod
    def _ken_recht_toe(admin_engine: Engine, actor: uuid.UUID, gebruiker: uuid.UUID, rol: str) -> None:
        """Insert als owner mét gezette actor — de audit-trigger uit 0034 eist die ook hier."""
        with admin_engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_actor_id', :actor, true)"), {"actor": str(actor)}
            )
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker_module_rol (gebruiker_id, module, rol) "
                    "VALUES (:gid, 'boekhouding', :rol)"
                ),
                {"gid": gebruiker, "rol": rol},
            )

    def test_db_check_accepteert_alleen_geldige_module_rollen(self, admin_engine: Engine, beheerder_id):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        self._ken_recht_toe(admin_engine, beheerder_id, medewerker, "meerwerk_urenstaten")
        andere = maak_gebruiker(admin_engine, "boekhouding", "Annemieke B.")
        with pytest.raises(IntegrityError, match="ck_gebruiker_module_rol_geldig"):
            self._ken_recht_toe(admin_engine, beheerder_id, andere, "onzin")

    def test_recht_helper(self, admin_engine: Engine, beheerder_id):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        zzper = maak_gebruiker(admin_engine, "zzper", "Milan K.")
        assert service.heeft_meerwerk_urenstaten_recht(gebruiker_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert not service.heeft_meerwerk_urenstaten_recht(gebruiker_id=medewerker, rol=GebruikerRol.BOEKHOUDING)
        # een externe rol heeft het kantoor-recht per definitie nooit
        assert not service.heeft_meerwerk_urenstaten_recht(gebruiker_id=zzper, rol=GebruikerRol.ZZPER)
        TestModuleRecht._ken_recht_toe(admin_engine, beheerder_id, medewerker, "meerwerk_urenstaten")
        assert service.heeft_meerwerk_urenstaten_recht(gebruiker_id=medewerker, rol=GebruikerRol.BOEKHOUDING)


class TestProjectKoppeling:
    def test_koppelen_valideert_rol_en_is_idempotent(
        self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, actor_id=beheerder_id
        )
        service.koppel_project(  # idempotent — geen fout, geen dubbele rij
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, actor_id=beheerder_id
        )
        with admin_engine.begin() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.uren_project_toewijzing WHERE gebruiker_id = :gid"),
                {"gid": zzper},
            ).scalar_one()
        assert aantal == 1
        accordeur = maak_gebruiker(admin_engine, "klant_accordeur", "Accordeur")
        with pytest.raises(service.OngeldigeInvoer, match="ZZP'ers en uitvoerders"):
            service.koppel_project(
                administratie_id=administratie_id,
                gebruiker_id=accordeur,
                project_id=project_id,
                actor_id=beheerder_id,
            )

    def test_ontkoppelen_laat_bestaande_weekstaten_staan(
        self, admin_engine: Engine, administratie_id, project_id, gekoppelde_zzper, beheerder_id
    ):
        from datetime import date
        from decimal import Decimal

        service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            datum=date.fromisocalendar(2026, 34, 1),
            uren=Decimal("8"),
            actor_id=gekoppelde_zzper,
        )
        service.ontkoppel_project(
            administratie_id=administratie_id,
            gebruiker_id=gekoppelde_zzper,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        with admin_engine.begin() as conn:
            staten = conn.execute(text("SELECT count(*) FROM boekhouding.weekstaat")).scalar_one()
        assert staten == 1  # niets verdwijnt


class TestDetacheerderKoppeling:
    def test_rolvalidatie_en_idempotentie(self, admin_engine: Engine, zzper, detacheerder, beheerder_id):
        with pytest.raises(service.OngeldigeInvoer, match="detacheerder"):
            service.koppel_detacheerder(detacheerder_id=zzper, zzper_id=zzper, actor_id=beheerder_id)
        with pytest.raises(service.OngeldigeInvoer, match="ZZP'er"):
            service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=detacheerder, actor_id=beheerder_id)
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        with admin_engine.begin() as conn:
            aantal = conn.execute(text("SELECT count(*) FROM platform.detacheerder_koppeling")).scalar_one()
        assert aantal == 1

    def test_rls_detacheerder_leest_alleen_eigen_rijen(
        self, admin_engine: Engine, zzper, detacheerder, beheerder_id
    ):
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        andere = maak_gebruiker(admin_engine, "detacheerder", "Andere D.")
        with scoped_session(None, actor_id=detacheerder) as session:
            eigen = session.query(DetacheerderKoppeling).all()
        with scoped_session(None, actor_id=andere) as session:
            vreemd = session.query(DetacheerderKoppeling).all()
        assert len(eigen) == 1
        assert vreemd == []

    def test_ontkoppelen_geaudit(self, admin_engine: Engine, zzper, detacheerder, beheerder_id):
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        service.ontkoppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        with admin_engine.begin() as conn:
            acties = conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'detacheerder_koppeling' "
                    "ORDER BY tijdstip"
                )
            ).scalars().all()
        assert acties == ["detacheerder_gekoppeld", "detacheerder_ontkoppeld"]
