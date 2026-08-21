"""Weekstaat-statusmachine (fase 1, BOUW GO 2026-08-21): concept → ingediend → goedgekeurd /
afgekeurd-op-WEEKNIVEAU-met-verplichte-reden → corrigeren → opnieuw ingediend; goedgekeurd =
getekende urenstaat (onmuteerbaar, alleen open te breken door een nieuwe afkeuring);
detacheerder-namens-flow; weekstaat-per-project; idempotente besluit-herhaling."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.uren import service
from tests.uren.conftest import maak_gebruiker, maak_project

JAAR, WEEK = 2026, 34
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _zet_dag(administratie_id, zzper, project_id, *, actor=None, datum=MAANDAG, uren="8", m2=None):
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        m2=Decimal(m2) if m2 is not None else None,
        actor_id=actor or zzper,
    )


def _dien_in(administratie_id, zzper, project_id, *, actor=None):
    return service.dien_week_in(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        actor_id=actor or zzper,
    )


class TestInvullen:
    def test_dag_zetten_maakt_concept_staat_met_totalen(self, administratie_id, project_id, gekoppelde_zzper):
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="8", m2="120")
        staat = _zet_dag(
            administratie_id, gekoppelde_zzper, project_id, datum=MAANDAG + timedelta(days=1), uren="6.5"
        )
        assert staat.status == "concept"
        assert staat.totaal_uren == Decimal("14.5")
        assert staat.totaal_m2 == Decimal("120")
        assert len(staat.dagen) == 2
        assert all(not d.namens for d in staat.dagen)

    def test_dag_bijwerken_is_upsert(self, administratie_id, project_id, gekoppelde_zzper):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="8")
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="4")
        assert len(staat.dagen) == 1
        assert staat.totaal_uren == Decimal("4")

    def test_datum_buiten_week_weigert(self, administratie_id, project_id, gekoppelde_zzper):
        with pytest.raises(service.OngeldigeInvoer, match="valt buiten week"):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id, datum=MAANDAG + timedelta(days=7))

    def test_uren_grenzen(self, administratie_id, project_id, gekoppelde_zzper):
        with pytest.raises(service.OngeldigeInvoer):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="25")
        with pytest.raises(service.OngeldigeInvoer):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="-1")

    def test_zonder_projectkoppeling_geen_toegang(self, administratie_id, project_id, zzper):
        with pytest.raises(service.GeenToegang, match="niet aan dit project gekoppeld"):
            _zet_dag(administratie_id, zzper, project_id)

    def test_opt_in_uit_blokkeert(self, admin_engine, administratie_zonder_opt_in, zzper):
        project = maak_project(admin_engine, administratie_zonder_opt_in, "26099 Elders")
        with pytest.raises(service.ModuleUitgeschakeld):
            _zet_dag(administratie_zonder_opt_in, zzper, project)

    def test_weekstaat_per_project_twee_staten_zelfde_dag(
        self, administratie_id, project_id, tweede_project_id, gekoppelde_zzper, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=gekoppelde_zzper,
            project_id=tweede_project_id,
            actor_id=beheerder_id,
        )
        staat_a = _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="6")
        staat_b = _zet_dag(administratie_id, gekoppelde_zzper, tweede_project_id, uren="2")
        assert staat_a.id != staat_b.id
        assert (staat_a.totaal_uren, staat_b.totaal_uren) == (Decimal("6"), Decimal("2"))


class TestIndienen:
    def test_indienen_en_idempotente_herhaling(self, administratie_id, project_id, gekoppelde_zzper):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        assert staat.status == "ingediend"
        assert staat.ingediend_door == gekoppelde_zzper
        assert not staat.ingediend_namens
        herhaald = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        assert herhaald.status == "ingediend"
        assert herhaald.ingediend_op == staat.ingediend_op

    def test_lege_week_indienen_mag(self, administratie_id, project_id, gekoppelde_zzper):
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        assert staat.status == "ingediend"
        assert staat.totaal_uren == Decimal("0")

    def test_ingediend_is_bevroren(self, administratie_id, project_id, gekoppelde_zzper):
        _dien_in(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.WeekstaatBevroren):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id)


class TestKeuren:
    def test_goedkeuren_en_idempotente_herhaling(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder
    ):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        goed = service.keur_week_goed(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder
        )
        assert goed.status == "goedgekeurd"
        assert goed.goedgekeurd_door_naam == "Ben v. Dijk"
        herhaald = service.keur_week_goed(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder
        )
        assert herhaald.goedgekeurd_op == goed.goedgekeurd_op

    def test_uitvoerder_zonder_toewijzing_keurt_niet(
        self, admin_engine, administratie_id, project_id, gekoppelde_zzper, uitvoerder
    ):
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.GeenToegang, match="niet aan dit project gekoppeld"):
            service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)

    def test_zzper_keurt_nooit(self, administratie_id, project_id, gekoppelde_zzper):
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.GeenToegang, match="Alleen een uitvoerder"):
            service.keur_week_goed(
                administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_zzper
            )

    def test_concept_kan_niet_goedgekeurd_worden(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder
    ):
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.OngeldigeOvergang):
            service.keur_week_goed(
                administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder
            )

    def test_afkeuren_vereist_reden(self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder):
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.RedenVerplicht):
            service.keur_week_af(
                administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder, reden="  "
            )

    def test_afkeuren_corrigeren_opnieuw_indienen(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder
    ):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="10")
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        afgekeurd = service.keur_week_af(
            administratie_id=administratie_id,
            weekstaat_id=staat.id,
            actor_id=gekoppelde_uitvoerder,
            reden="Wo max 8 uur afgesproken op dit werk",
        )
        assert afgekeurd.status == "corrigeren"
        assert afgekeurd.afkeur_reden == "Wo max 8 uur afgesproken op dit werk"
        # dagen zijn weer muteerbaar, en de wéék gaat opnieuw in
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="8")
        opnieuw = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        assert opnieuw.status == "ingediend"

    def test_goedgekeurd_is_onmuteerbaar_maar_opnieuw_afkeurbaar(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder
    ):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        staat = _dien_in(administratie_id, gekoppelde_zzper, project_id)
        service.keur_week_goed(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder
        )
        with pytest.raises(service.WeekstaatBevroren):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        with pytest.raises(service.OngeldigeOvergang):
            _dien_in(administratie_id, gekoppelde_zzper, project_id)
        # de enige terugweg: een nieuwe afkeuring door de uitvoerder
        heropend = service.keur_week_af(
            administratie_id=administratie_id,
            weekstaat_id=staat.id,
            actor_id=gekoppelde_uitvoerder,
            reden="Correctie nodig: m² gevel B dubbel geteld",
        )
        assert heropend.status == "corrigeren"
        assert heropend.goedgekeurd_op is None
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="7")


class TestDetacheerderNamens:
    def test_gekoppelde_detacheerder_vult_in_en_dient_in_namens(
        self, admin_engine: Engine, administratie_id, project_id, gekoppelde_zzper, detacheerder, beheerder_id
    ):
        service.koppel_detacheerder(
            detacheerder_id=detacheerder, zzper_id=gekoppelde_zzper, actor_id=beheerder_id
        )
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, actor=detacheerder)
        assert staat.dagen[0].namens is True
        assert staat.dagen[0].ingevuld_door == detacheerder
        assert staat.gebruiker_id == gekoppelde_zzper  # de staat blijft van de ZZP'er
        ingediend = _dien_in(administratie_id, gekoppelde_zzper, project_id, actor=detacheerder)
        assert ingediend.ingediend_namens is True
        assert ingediend.ingediend_door_naam == "Karin S."
        # audit draagt de namens-vastlegging ("ingevuld door X namens Y")
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'namens_gebruiker_id' FROM platform.audit_event "
                    "WHERE actie = 'weekstaat_ingediend' ORDER BY tijdstip DESC LIMIT 1"
                )
            ).scalar_one()
        assert rij == str(gekoppelde_zzper)

    def test_niet_gekoppelde_detacheerder_geweigerd(
        self, administratie_id, project_id, gekoppelde_zzper, detacheerder
    ):
        with pytest.raises(service.GeenToegang, match="niet aan deze ZZP'er gekoppeld"):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id, actor=detacheerder)

    def test_andere_zzper_mag_niet_namens(self, admin_engine, administratie_id, project_id, gekoppelde_zzper):
        indringer = maak_gebruiker(admin_engine, "zzper", "Stefan B.")
        with pytest.raises(service.GeenToegang):
            _zet_dag(administratie_id, gekoppelde_zzper, project_id, actor=indringer)
