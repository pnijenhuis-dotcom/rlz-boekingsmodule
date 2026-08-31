"""Werkopdrachten per project × periode (31-08, migratie 0091): append-only versies,
dag-override wint alleen die dag, grid- en veld-voeding, poorten + audit."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.uren import planning, service as uren_service, werkopdracht

JAAR, WEEK = 2026, 35
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)
DINSDAG = MAANDAG + timedelta(days=1)


def _audit(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip, id"),
                {"id": record_id},
            )
        ]


def _maak(administratie_id, project_id, beheerder_id, *, tekst="Montage fase 1 — zuidgevel eerst"):
    return werkopdracht.maak_werkopdracht(
        administratie_id=administratie_id,
        project_id=project_id,
        van=MAANDAG,
        tot_en_met=MAANDAG + timedelta(days=30),
        tekst=tekst,
        actor_id=beheerder_id,
    )


class TestAppendOnly:
    def test_wijzigen_is_nieuwe_versie_met_historie(self, administratie_id, project_id, beheerder_id, admin_engine):
        w = _maak(administratie_id, project_id, beheerder_id)
        assert w.versie == 1
        w2 = werkopdracht.wijzig_werkopdracht(
            administratie_id=administratie_id, groep_id=w.groep_id, van=w.van, tot_en_met=w.tot_en_met,
            tekst="Montage fase 1 — oost eerst", actor_id=beheerder_id,
        )
        assert w2.versie == 2 and w2.groep_id == w.groep_id and w2.tekst == "Montage fase 1 — oost eerst"
        assert [h.omschrijving for h in w2.historie] == ["aangemaakt", "gewijzigd (versie 2)"]
        # Idempotent: exact dezelfde inhoud = geen lege versie erbij.
        w3 = werkopdracht.wijzig_werkopdracht(
            administratie_id=administratie_id, groep_id=w.groep_id, van=w2.van, tot_en_met=w2.tot_en_met,
            tekst=w2.tekst, actor_id=beheerder_id,
        )
        assert w3.versie == 2
        # De oude versie staat onaangeroerd in de tabel (append-only, DB-grant zonder UPDATE/DELETE).
        with admin_engine.begin() as conn:
            teksten = [
                r[0]
                for r in conn.execute(
                    text("SELECT tekst FROM boekhouding.werkopdracht WHERE groep_id = :g ORDER BY versie"),
                    {"g": w.groep_id},
                )
            ]
        assert teksten == ["Montage fase 1 — zuidgevel eerst", "Montage fase 1 — oost eerst"]
        assert _audit(admin_engine, w.groep_id) == ["werkopdracht_aangemaakt", "werkopdracht_gewijzigd"]

    def test_meerdere_en_overlappende_per_project(self, administratie_id, project_id, beheerder_id):
        _maak(administratie_id, project_id, beheerder_id, tekst="Montage fase 1")
        _maak(administratie_id, project_id, beheerder_id, tekst="Demontage west + tellen retour")
        alle = werkopdracht.werkopdrachten_project(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id
        )
        assert sorted(w.tekst for w in alle) == ["Demontage west + tellen retour", "Montage fase 1"]

    def test_validaties(self, administratie_id, project_id, beheerder_id):
        with pytest.raises(uren_service.OngeldigeInvoer):
            werkopdracht.maak_werkopdracht(
                administratie_id=administratie_id, project_id=project_id, van=DINSDAG, tot_en_met=MAANDAG,
                tekst="x", actor_id=beheerder_id,
            )
        with pytest.raises(uren_service.OngeldigeInvoer):
            werkopdracht.maak_werkopdracht(
                administratie_id=administratie_id, project_id=project_id, van=MAANDAG, tot_en_met=DINSDAG,
                tekst="   ", actor_id=beheerder_id,
            )
        with pytest.raises(uren_service.NietGevonden):
            werkopdracht.maak_werkopdracht(
                administratie_id=administratie_id, project_id=uuid.uuid4(), van=MAANDAG, tot_en_met=DINSDAG,
                tekst="x", actor_id=beheerder_id,
            )


class TestDagOverride:
    def test_override_wint_alleen_die_dag(self, administratie_id, project_id, beheerder_id, admin_engine):
        w = _maak(administratie_id, project_id, beheerder_id)
        werkopdracht.zet_dag_override(
            administratie_id=administratie_id, groep_id=w.groep_id, datum=DINSDAG,
            tekst="di afwijkend: traptoren bijplaatsen", actor_id=beheerder_id,
        )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            di = werkopdracht.teksten_voor_dag(
                session, administratie_id=administratie_id, project_id=project_id, datum=DINSDAG
            )
            wo_dag = werkopdracht.teksten_voor_dag(
                session, administratie_id=administratie_id, project_id=project_id, datum=MAANDAG
            )
            buiten = werkopdracht.teksten_voor_dag(
                session, administratie_id=administratie_id, project_id=project_id, datum=MAANDAG + timedelta(days=60)
            )
        assert [(t.tekst, t.afwijkend) for t in di] == [("di afwijkend: traptoren bijplaatsen", True)]
        assert [(t.tekst, t.afwijkend) for t in wo_dag] == [("Montage fase 1 — zuidgevel eerst", False)]
        assert buiten == []
        # Override buiten de periode = geweigerd; lege tekst = geweigerd.
        with pytest.raises(uren_service.OngeldigeInvoer):
            werkopdracht.zet_dag_override(
                administratie_id=administratie_id, groep_id=w.groep_id, datum=MAANDAG + timedelta(days=60),
                tekst="x", actor_id=beheerder_id,
            )
        with pytest.raises(uren_service.OngeldigeInvoer):
            werkopdracht.zet_dag_override(
                administratie_id=administratie_id, groep_id=w.groep_id, datum=DINSDAG, tekst=" ", actor_id=beheerder_id
            )
        # Override wijzigen = nieuwe versie (append-only), zichtbaar in de historie.
        w2 = werkopdracht.zet_dag_override(
            administratie_id=administratie_id, groep_id=w.groep_id, datum=DINSDAG,
            tekst="di afwijkend: tóch demontage", actor_id=beheerder_id,
        )
        assert [o.tekst for o in w2.dag_overrides] == ["di afwijkend: tóch demontage"]
        assert any("dag-override" in h.omschrijving and "gewijzigd" in h.omschrijving for h in w2.historie)
        assert "werkopdracht_dag_override_gezet" in _audit(admin_engine, w.groep_id)


class TestGridEnVeld:
    def test_planning_overzicht_draagt_chip_en_override(self, administratie_id, project_id, beheerder_id):
        w = _maak(administratie_id, project_id, beheerder_id)
        werkopdracht.zet_dag_override(
            administratie_id=administratie_id, groep_id=w.groep_id, datum=DINSDAG,
            tekst="di afwijkend", actor_id=beheerder_id,
        )
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id
        )
        rij = next(r for r in data.projecten if r.project_id == project_id)
        assert [x.tekst for x in rij.werkopdrachten] == ["Montage fase 1 — zuidgevel eerst"]
        assert [t.tekst for t in rij.werkopdracht_overrides[DINSDAG.isoformat()]] == ["di afwijkend"]
        # Een week búiten de periode draagt geen chip.
        latere = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK + 10, actor_id=beheerder_id
        )
        rij_later = next(r for r in latere.projecten if r.project_id == project_id)
        assert rij_later.werkopdrachten == []

    def test_veld_app_ziet_geldende_tekst_bij_geplande_dag(
        self, administratie_id, project_id, beheerder_id, gekoppelde_zzper
    ):
        from app.auth import service as auth_service

        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=gekoppelde_zzper, administratie_id=administratie_id
        )
        w = _maak(administratie_id, project_id, beheerder_id)
        werkopdracht.zet_dag_override(
            administratie_id=administratie_id, groep_id=w.groep_id, datum=DINSDAG,
            tekst="di afwijkend: traptoren", actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id,
            datum=MAANDAG, dagdeel="heel", actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id,
            datum=DINSDAG, dagdeel="heel", actor_id=beheerder_id,
        )
        dagen = planning.mijn_planning(
            veldwerker_id=gekoppelde_zzper, actor_id=gekoppelde_zzper, jaar=JAAR, weeknummer=WEEK
        )
        per_datum = {d.datum: d for d in dagen}
        assert [(t.tekst, t.afwijkend) for t in per_datum[MAANDAG].werkopdrachten] == [
            ("Montage fase 1 — zuidgevel eerst", False)
        ]
        assert [(t.tekst, t.afwijkend) for t in per_datum[DINSDAG].werkopdrachten] == [
            ("di afwijkend: traptoren", True)
        ]


class TestPoorten:
    def test_opt_in_en_recht_vereist(self, administratie_zonder_opt_in, beheerder_id, administratie_id, project_id, admin_engine):
        from tests.uren.conftest import maak_gebruiker

        with pytest.raises(uren_service.ModuleUitgeschakeld):
            werkopdracht.maak_werkopdracht(
                administratie_id=administratie_zonder_opt_in, project_id=uuid.uuid4(), van=MAANDAG,
                tot_en_met=DINSDAG, tekst="x", actor_id=beheerder_id,
            )
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        with pytest.raises(uren_service.GeenToegang):
            werkopdracht.maak_werkopdracht(
                administratie_id=administratie_id, project_id=project_id, van=MAANDAG, tot_en_met=DINSDAG,
                tekst="x", actor_id=boekhouder,
            )
