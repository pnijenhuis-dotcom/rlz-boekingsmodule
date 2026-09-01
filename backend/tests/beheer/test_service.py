from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.beheer import service


def _audit_acties(admin_engine: Engine, *, tabel: str, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = :tabel AND record_id = :id ORDER BY tijdstip"
                ),
                {"tabel": tabel, "id": record_id},
            )
            .scalars()
            .all()
        )


class TestPerAdministratieToggle:
    def test_default_uit(self, administratie_id: uuid.UUID) -> None:
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_aanzetten_en_uitzetten(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is True

        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=False)
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_elke_wijziging_wordt_geaudit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        assert acties == ["boeken_ingeschakeld_gewijzigd", "boeken_ingeschakeld_gewijzigd"]

    def test_onbekende_administratie_geeft_beheerfout(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(service.BeheerFout):
            service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=uuid.uuid4(), ingeschakeld=True)


class TestOverzichtBoekenStatus:
    def test_geeft_naam_en_toggle_per_administratie(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)

        overzicht = service.overzicht_boeken_status()

        item = next(i for i in overzicht if i.administratie_id == administratie_id)
        assert item.boeken_ingeschakeld is True
        assert item.naam

    def test_leeg_zonder_administraties(self) -> None:
        assert service.overzicht_boeken_status() == []


class TestProjectVerplicht:
    def test_default_uit(self, administratie_id: uuid.UUID) -> None:
        assert service.haal_project_verplicht_op(administratie_id=administratie_id) is False

    def test_aanzetten_en_uitzetten(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        assert service.haal_project_verplicht_op(administratie_id=administratie_id) is True

        service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=False)
        assert service.haal_project_verplicht_op(administratie_id=administratie_id) is False

    def test_wijziging_wordt_geaudit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        assert acties == ["project_verplicht_gewijzigd"]

    def test_onbekende_administratie_geeft_beheerfout(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(service.BeheerFout):
            service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=uuid.uuid4(), verplicht=True)


class TestEigenaarInstelling:
    """Eigenaar per administratie (migratie 0021, vragenworkflow): default-toewijzing voor
    nieuwe vragen — alleen een actieve gebruiker mét scope (of een Beheerder) kan eigenaar zijn."""

    def test_default_geen_eigenaar(self, administratie_id: uuid.UUID) -> None:
        assert service.haal_eigenaar_op(administratie_id=administratie_id) is None

    def test_zetten_en_weghalen_met_audit(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        service.zet_eigenaar(
            actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gescoopte_gebruiker
        )
        assert service.haal_eigenaar_op(administratie_id=administratie_id) == gescoopte_gebruiker

        service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=None)
        assert service.haal_eigenaar_op(administratie_id=administratie_id) is None
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        assert acties == ["eigenaar_gewijzigd", "eigenaar_gewijzigd"]

    def test_eigenaar_zonder_scope_geweigerd(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        buitenstaander = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'Zonder scope', :mail, 'boekhouding', 'actief')"
                ),
                {"id": buitenstaander, "mail": f"{buitenstaander}@test.local"},
            )
        with pytest.raises(service.OngeldigeEigenaar):
            service.zet_eigenaar(
                actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=buitenstaander
            )

    def test_beheerder_mag_eigenaar_zijn_zonder_scope_rij(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        service.zet_eigenaar(
            actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=beheerder_id
        )
        assert service.haal_eigenaar_op(administratie_id=administratie_id) == beheerder_id


class TestMedewerkersLijst:
    """Toewijsbare medewerkers (vraagmodal PART B): scope-gebruikers + actieve Beheerders,
    nooit gebruikers zonder scope op déze administratie."""

    def test_bevat_scope_gebruiker_en_beheerder_niet_de_buitenstaander(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        buitenstaander = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'Zonder scope', :mail, 'boekhouding', 'actief')"
                ),
                {"id": buitenstaander, "mail": f"{buitenstaander}@test.local"},
            )
        medewerkers = service.lijst_medewerkers(administratie_id=administratie_id)
        ids = {m.id for m in medewerkers}
        assert gescoopte_gebruiker in ids
        assert beheerder_id in ids
        assert buitenstaander not in ids
        assert all(m.naam for m in medewerkers)

    def test_inactieve_scope_gebruiker_niet_toewijsbaar(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.gebruiker SET status = 'geblokkeerd' WHERE id = :id"),
                {"id": gescoopte_gebruiker},
            )
        medewerkers = service.lijst_medewerkers(administratie_id=administratie_id)
        assert gescoopte_gebruiker not in {m.id for m in medewerkers}


class TestGlobaleKillSwitch:
    def test_default_aan(self) -> None:
        assert service.haal_globale_kill_switch_op() is True

    def test_uitzetten_en_aanzetten(self, beheerder_id: uuid.UUID) -> None:
        service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=False)
        assert service.haal_globale_kill_switch_op() is False

        service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=True)
        assert service.haal_globale_kill_switch_op() is True


class TestIntakeAiToggle:
    """Intake-AI-toggle (migratie 0029): platform-brede AVG-gate, default UIT; de env-setting is
    uitsluitend fallback zolang de singleton-rij ontbreekt."""

    def test_default_uit(self) -> None:
        assert service.haal_intake_ai_ingeschakeld_op() is False
        assert service.intake_ai_effectief_ingeschakeld() is False

    def test_aanzetten_en_uitzetten_met_audit(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        service.zet_intake_ai_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True)
        assert service.haal_intake_ai_ingeschakeld_op() is True
        assert service.intake_ai_effectief_ingeschakeld() is True

        service.zet_intake_ai_ingeschakeld(actor_id=beheerder_id, ingeschakeld=False)
        assert service.intake_ai_effectief_ingeschakeld() is False

        acties = _audit_acties(
            admin_engine, tabel="intake_instelling", record_id=uuid.UUID("00000000-0000-0000-0000-000000000000")
        )
        assert acties == ["intake_ai_ingeschakeld_gewijzigd", "intake_ai_ingeschakeld_gewijzigd"]

    def test_db_rij_is_leidend_boven_env(self, monkeypatch) -> None:
        # De rij bestaat (migratie-seed, hersteld door _clean_tables) en staat UIT — een
        # aan-gezette env-setting mag daar niet doorheen prikken.
        monkeypatch.setattr(service.settings, "intake_ai_ingeschakeld", True)
        assert service.intake_ai_effectief_ingeschakeld() is False

    def test_env_is_fallback_zonder_rij(self, admin_engine: Engine, monkeypatch) -> None:
        from sqlalchemy import text as sql_text

        monkeypatch.setattr(service.settings, "intake_ai_ingeschakeld", True)
        with admin_engine.begin() as conn:
            conn.execute(sql_text("DELETE FROM platform.intake_instelling"))
        try:
            assert service.intake_ai_effectief_ingeschakeld() is True
            with pytest.raises(service.BeheerFout):
                service.haal_intake_ai_ingeschakeld_op()
        finally:
            with admin_engine.begin() as conn:
                conn.execute(
                    sql_text(
                        "INSERT INTO platform.intake_instelling (singleton, ai_ingeschakeld) "
                        "VALUES (true, false) ON CONFLICT (singleton) DO NOTHING"
                    )
                )


class TestPersistentiePerInstelbaarVeld:
    """Vastly-port (b), 2026-08-07: elk instelbaar veld heeft een eigen zetten→lezen-round-trip.
    ai_extractie, bank_autoboeken en webhook_aflevering werden tot nu toe alleen als setup-helper
    in andere tests aangeroepen — een veld dat stil niet persisteert (de Vastly-checkbox-bug)
    viel dan nergens."""

    def test_ai_extractie_ingeschakeld_persisteert(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        assert service.haal_ai_extractie_ingeschakeld_op(administratie_id=administratie_id) is False
        service.zet_ai_extractie_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        assert service.haal_ai_extractie_ingeschakeld_op(administratie_id=administratie_id) is True
        overzicht = service.overzicht_administratie_instellingen()
        rij = next(r for r in overzicht if r.administratie_id == administratie_id)
        assert rij.ai_extractie_ingeschakeld is True

    def test_bank_autoboeken_ingeschakeld_persisteert(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        assert service.haal_bank_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is False
        service.zet_bank_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        assert service.haal_bank_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is True

    def test_webhook_aflevering_ingeschakeld_persisteert(self, beheerder_id: uuid.UUID) -> None:
        assert service.haal_webhook_aflevering_ingeschakeld_op() is False
        service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True)
        assert service.haal_webhook_aflevering_ingeschakeld_op() is True
        service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=False)
        assert service.haal_webhook_aflevering_ingeschakeld_op() is False


class TestIsVastgoedToggle:
    """Avondrun 26-08 (S2-draaiboek R1): is_vastgoed als Beheerder-toggle — audit oud→nieuw;
    UIT neemt verkoop-autoboeken zichtbaar mee uit (409-regel: die opt-in bestaat alleen bij
    is_vastgoed)."""

    def test_default_uit_en_aanzetten(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        assert service.haal_is_vastgoed_op(administratie_id=administratie_id) is False
        r = service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=True)
        assert r.is_vastgoed is True
        assert r.verkoop_autoboeken_uitgezet is False
        assert service.haal_is_vastgoed_op(administratie_id=administratie_id) is True

    def test_wijziging_geaudit_oud_naar_nieuw(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=True)
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT actor_id, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE tabel = 'administratie' AND record_id = :id AND actie = 'is_vastgoed_gewijzigd'"
                ),
                {"id": administratie_id},
            ).one()
        assert rij.actor_id == beheerder_id
        assert rij.oude_waarde == {"is_vastgoed": False}
        assert rij.nieuwe_waarde == {"is_vastgoed": True}

    def test_uitzetten_neemt_verkoop_autoboeken_zichtbaar_mee_uit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=True)
        service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        r = service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=False)
        assert r.is_vastgoed is False
        assert r.verkoop_autoboeken_ingeschakeld is False
        assert r.verkoop_autoboeken_uitgezet is True
        assert service.haal_verkoop_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is False
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        # Twee is_vastgoed-audits (aan, uit) + drie verkoop-audits: de spiegel gaat mee AAN met is_vastgoed
        # (v2 30-08), de expliciete opt-in (no-op, tóch geauditeerd) en mee UIT.
        assert acties.count("is_vastgoed_gewijzigd") == 2
        assert acties.count("verkoop_autoboeken_ingeschakeld_gewijzigd") == 3
        with admin_engine.connect() as conn:
            laatste = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE tabel = 'administratie' "
                    "AND record_id = :id AND actie = 'verkoop_autoboeken_ingeschakeld_gewijzigd' "
                    "ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"id": administratie_id},
            ).scalar_one()
        assert laatste == {"verkoop_autoboeken_ingeschakeld": False, "reden": "volgt is_vastgoed (v2 30-08)"}

    def test_uitzetten_zonder_opt_in_raakt_verkoop_niet(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        r = service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=False)
        assert r.verkoop_autoboeken_uitgezet is False
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        assert "verkoop_autoboeken_ingeschakeld_gewijzigd" not in acties

    def test_tier_vlag_afgeletterd_event_blijft_staan(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Besluit 0018: aparte kolom — de vastgoed-toggle raakt de tier-vlag niet (Rubicon AAN)."""
        service.zet_afgeletterd_event_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=True)
        service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=False)
        with admin_engine.connect() as conn:
            vlag = conn.execute(
                text("SELECT afgeletterd_event_ingeschakeld FROM platform.administratie WHERE id = :id"),
                {"id": administratie_id},
            ).scalar_one()
        assert vlag is True

    def test_onbekende_administratie(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(service.BeheerFout):
            service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=uuid.uuid4(), is_vastgoed=True)


class TestOverzichtDoorbelastingDoel:
    """Instellingen v3 (01-09): de detailpagina toont de Doorbelasting-tab bij bron óf doel — het
    lijst-DTO draagt daarom `doorbelasting_doel` (doel van ≥ 1 actieve mapping). De mapping-tabel
    is RLS-gescoopt op de bron; de service leest per bron-administratie."""

    def test_doel_vlag_volgt_actieve_mapping(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.doorbelasting.models import DoorbelastingMapping
        from app.db.session import scoped_session

        doel_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Doel (test)', :rlz)"),
                {"id": doel_id, "rlz": f"rlz-{doel_id}"},
            )
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                DoorbelastingMapping(
                    administratie_id=administratie_id,
                    doelentiteit_naam="Doel (test)",
                    doel_customer_guid=uuid.uuid4(),
                    doel_administratie_id=doel_id,
                    aangemaakt_door=beheerder_id,
                )
            )

        per_id = {r.administratie_id: r for r in service.overzicht_administratie_instellingen()}
        assert per_id[administratie_id].doorbelasting_ingeschakeld is True
        assert per_id[administratie_id].doorbelasting_doel is False
        assert per_id[doel_id].doorbelasting_doel is True
        assert per_id[doel_id].doorbelasting_ingeschakeld is False

    def test_inactieve_mapping_telt_niet(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.doorbelasting.models import DoorbelastingMapping
        from app.db.session import scoped_session

        doel_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Doel (test)', :rlz)"),
                {"id": doel_id, "rlz": f"rlz-{doel_id}"},
            )
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                DoorbelastingMapping(
                    administratie_id=administratie_id,
                    doelentiteit_naam="Doel (test)",
                    doel_customer_guid=uuid.uuid4(),
                    doel_administratie_id=doel_id,
                    actief=False,
                    aangemaakt_door=beheerder_id,
                )
            )
        per_id = {r.administratie_id: r for r in service.overzicht_administratie_instellingen()}
        assert per_id[doel_id].doorbelasting_doel is False
