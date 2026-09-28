"""Planning v4 (feedback Peter 28-09; opdracht `2026-09-28-planning-v4-pool-weg-matrix-uitlijning-paneel-plus-zzp-
kopie-naar-volgende-week`; geen migratie) — backend-deel:

- bulkroute bron `kopie_volgende_week` ("Kopiëren naar ‹weekdag› volgende week", besluit Peter: alleen dezelfde
  weekdag): conflict elders = gepland + gemarkeerd (oranje), afwezig in week+1 = OVERGESLAGEN mét reden (niet
  gepland,
  conflict 'afwezig' in de uitkomst), bestaande kaart = samengevoegd (overgeslagen, niets dubbel), idempotent,
  ongedaan = exact de aangemaakte set terug, audit per (persoon, dag) mét bron;
- quick-add uit het ploeg-paneel (bron `planning_paneel`): audit `veldwerker_aangemaakt`, de nieuwe veldwerker staat
  direct in de pool mét `dossier_onvolledig=True`; dubbelencheck alleen op HARDE sleutels (e-mail = 409 leesbaar;
  dezelfde naam is geen bezwaar — broers, correctie Peter 21-09); rolgroep-poort blijft gelden;
- `dossier.onvolledig_per_veldwerker` set-based: statements onafhankelijk van het aantal personen."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from app.auth import service as auth_service
from app.db import session as db_session
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.uren import dossier as dossier_service
from app.uren import planning
from app.uren.models import VeldwerkerDossier
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI, WO, DO, VR = (date(2026, 8, d) for d in (17, 18, 19, 20, 21))
MA1, DO1 = date(2026, 8, 24), date(2026, 8, 27)  # dezelfde weekdag in week+1
VANDAAG = date(2026, 8, 10)


class _Teller:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def __enter__(self) -> _Teller:
        event.listen(db_session.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(db_session.engine, "before_cursor_execute", self)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _toewijzingen(admin_engine: Engine, administratie_id: uuid.UUID) -> set[tuple[uuid.UUID, uuid.UUID, date]]:
    with admin_engine.begin() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT gebruiker_id, project_id, datum FROM boekhouding.planning_toewijzing "
                    "WHERE administratie_id = :a"
                ),
                {"a": administratie_id},
            ).all()
        )


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"), {"a": actie}
            ).mappings()
        ]


def _kopie(
    administratie_id, project_id, wie: list[uuid.UUID], datum: date, actor_id, correlatie_id=None, verwijderen=False
):
    return planning.plan_bulk(
        administratie_id=administratie_id,
        items=[(g, project_id, datum, "heel") for g in wie],
        bron="kopie_volgende_week",
        verwijderen=verwijderen,
        correlatie_id=correlatie_id,
        actor_id=actor_id,
        vandaag=VANDAAG,
    )


@pytest.fixture
def tweede_zzper(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "zzper", "Irfan O.")


class TestKopieVolgendeWeek:
    def test_zelfde_weekdag_week_plus_1_gedaan_bestaand_samengevoegd_idempotent_en_ongedaan(
        self, admin_engine, administratie_id, project_id, zzper, tweede_zzper, beheerder_id
    ):
        for g in (zzper, tweede_zzper):
            planning.plan_toewijzing(
                administratie_id=administratie_id,
                gebruiker_id=g,
                project_id=project_id,
                datum=MA,
                actor_id=beheerder_id,
            )
        # De kaart van ma 17-8 staat in week+1 al deels (zzper op ma 24-8): samenvoegen, niets dubbel.
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=project_id,
            datum=MA1,
            actor_id=beheerder_id,
        )
        res = _kopie(administratie_id, project_id, [zzper, tweede_zzper], MA1, beheerder_id)
        per = {r.gebruiker_id: r for r in res.resultaten}
        assert per[zzper].uitkomst == "overgeslagen" and per[zzper].reden == "stond al op dit project gepland"
        assert per[tweede_zzper].uitkomst == "gedaan"
        assert [r.gebruiker_id for r in res.aangemaakt] == [tweede_zzper]
        assert (tweede_zzper, project_id, MA1) in _toewijzingen(admin_engine, administratie_id)
        assert len(_toewijzingen(admin_engine, administratie_id)) == 4
        # Audit per (persoon, dag) mét de bron; de samenvattende rij telt.
        gepland = [
            r
            for r in _audit(admin_engine, "planning_gepland")
            if r["nieuwe_waarde"].get("bron") == "kopie_volgende_week"
        ]
        assert len(gepland) == 1 and gepland[0]["nieuwe_waarde"]["datum"] == MA1.isoformat()
        assert gepland[0]["nieuwe_waarde"]["achteraf"] is False  # week+1 ligt in de toekomst — nooit 'achteraf'
        assert _audit(admin_engine, "planning_bulk")[-1]["nieuwe_waarde"] == {
            **_audit(admin_engine, "planning_bulk")[-1]["nieuwe_waarde"],
            "bron": "kopie_volgende_week",
            "gedaan": 1,
            "overgeslagen": 1,
            "conflict": 0,
        }
        # Idempotent: dezelfde kopie nog eens = alles overgeslagen.
        weer = _kopie(administratie_id, project_id, [zzper, tweede_zzper], MA1, beheerder_id)
        assert {r.uitkomst for r in weer.resultaten} == {"overgeslagen"} and weer.aangemaakt == []
        # Ongedaan = exact de aangemaakte set terug (bron ongedaan, zelfde correlatie-id) — de vooraf bestaande kaart
        # blijft.
        terug = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(r.gebruiker_id, r.project_id, r.datum, r.dagdeel) for r in res.aangemaakt],
            bron="ongedaan",
            verwijderen=True,
            correlatie_id=res.correlatie_id,
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in terug.resultaten] == ["gedaan"]
        assert _toewijzingen(admin_engine, administratie_id) == {
            (zzper, project_id, MA),
            (tweede_zzper, project_id, MA),
            (zzper, project_id, MA1),
        }

    def test_conflict_elders_gepland_en_oranje_afwezig_overgeslagen_met_reden(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, tweede_zzper, beheerder_id
    ):
        # zzper staat do 27-8 al op een ánder project → conflict (WEL gepland); tweede_zzper is do 27-8 afwezig →
        # overgeslagen.
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=tweede_project_id,
            datum=DO1,
            actor_id=beheerder_id,
        )
        planning.voeg_afwezigheid_toe(
            administratie_id=administratie_id,
            gebruiker_id=tweede_zzper,
            van=DO1,
            tot=DO1,
            reden="verlof",
            actor_id=beheerder_id,
        )
        res = _kopie(administratie_id, project_id, [zzper, tweede_zzper], DO1, beheerder_id)
        per = {r.gebruiker_id: r for r in res.resultaten}
        assert per[zzper].uitkomst == "conflict" and per[zzper].conflict == "project"
        assert per[zzper].conflict_projectnaam == "26021 Tilburg (Heijmans)"
        assert per[tweede_zzper].uitkomst == "overgeslagen" and per[tweede_zzper].conflict == "afwezig"
        assert "afwezig t/m 2026-08-27 (verlof)" in (per[tweede_zzper].reden or "")
        # Afwezig = NIET gepland (anders dan het vulhandvat, dat wél plant en markeert); de conflict-kaart wél.
        assert (tweede_zzper, project_id, DO1) not in _toewijzingen(admin_engine, administratie_id)
        assert (zzper, project_id, DO1) in _toewijzingen(admin_engine, administratie_id)
        assert [r.gebruiker_id for r in res.aangemaakt] == [zzper]
        assert _audit(admin_engine, "planning_bulk")[-1]["nieuwe_waarde"]["overgeslagen"] == 1
        # Het vulhandvat/ploeg-pad is ongewijzigd: afwezig = gepland + gemarkeerd.
        vh = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(tweede_zzper, project_id, DO1, "heel")],
            bron="ploeg",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert vh.resultaten[0].uitkomst == "conflict" and vh.resultaten[0].conflict == "afwezig"

    def test_route_accepteert_de_bron_en_geeft_de_uitkomst_terug(
        self, administratie_id, project_id, zzper, beheerder_id
    ):
        resp = client.post(
            f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "bron": "kopie_volgende_week",
                "items": [{"gebruiker_id": str(zzper), "project_id": str(project_id), "datum": MA1.isoformat()}],
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resultaten"][0]["uitkomst"] == "gedaan"
        assert planning.BRON_KOPIE_VOLGENDE_WEEK in planning.BULK_BRONNEN


class TestQuickAddPloegPaneel:
    def _post(self, beheerder_id, body: dict):
        return client.post("/auth/uitnodigingen", json=body, headers=_bearer(beheerder_id, rol="beheerder"))

    def _body(self, administratie_id, *, naam="Irfan O.", e_mail=None, rol="zzper") -> dict:
        return {
            "naam": naam,
            "e_mail": e_mail or f"{uuid.uuid4()}@test.local",
            "rol": rol,
            "administratie_ids": [str(administratie_id)],
            "uitnodiging_later": True,
            "bron": "planning_paneel",
        }

    def test_audit_veldwerker_aangemaakt_en_direct_in_de_pool_met_dossier_onvolledig(
        self, admin_engine, administratie_id, beheerder_id
    ):
        resp = self._post(beheerder_id, self._body(administratie_id))
        assert resp.status_code == 200, resp.text
        gebruiker_id = uuid.UUID(resp.json()["gebruiker_id"])
        with admin_engine.connect() as conn:
            rijen = (
                conn.execute(
                    text(
                        "SELECT actie, tabel, nieuwe_waarde FROM platform.audit_event WHERE actie IN "
                        "('veldwerker_aangemaakt', 'gebruiker_uitgenodigd') "
                        "AND (record_id = :g OR correlatie_id = :g) ORDER BY actie"
                    ),
                    {"g": gebruiker_id},
                )
                .mappings()
                .all()
            )
        acties = {r["actie"]: r for r in rijen}
        assert acties["gebruiker_uitgenodigd"]["nieuwe_waarde"]["bron"] == "planning_paneel"
        va = acties["veldwerker_aangemaakt"]
        assert va["tabel"] == "gebruiker"
        assert va["nieuwe_waarde"] == {
            **va["nieuwe_waarde"],
            "bron": "planning_paneel",
            "rol": "zzper",
            "dossier_onvolledig": True,
            "administratie_ids": [str(administratie_id)],
        }
        # Direct aanvinkbaar: de nieuwe veldwerker staat in de pool van de planning (status uitgenodigd telt mee) mét de
        # chip.
        week = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id
        )
        persoon = next(p for p in week.pool if p.gebruiker_id == gebruiker_id)
        assert persoon.dossier_onvolledig is True and persoon.naam == "Irfan O."
        # En via de route (DTO-veld).
        resp = client.get(
            f"/uren/kantoor/planning?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200
        dto = next(p for p in resp.json()["pool"] if p["gebruiker_id"] == str(gebruiker_id))
        assert dto["dossier_onvolledig"] is True

    def test_dubbelencheck_alleen_harde_sleutels_email_409_zelfde_naam_mag(self, administratie_id, beheerder_id):
        e_mail = f"{uuid.uuid4()}@test.local"
        eerste = self._post(beheerder_id, self._body(administratie_id, naam="M. Demir", e_mail=e_mail))
        assert eerste.status_code == 200, eerste.text
        # Dezelfde naam mét een eigen e-mail = een tweede account (broers in één ploeg, correctie Peter 21-09).
        broer = self._post(beheerder_id, self._body(administratie_id, naam="M. Demir"))
        assert broer.status_code == 200, broer.text
        assert broer.json()["gebruiker_id"] != eerste.json()["gebruiker_id"]
        # Hetzelfde e-mailadres = harde sleutel → 409 leesbaar, nooit een tweede account.
        dubbel = self._post(beheerder_id, self._body(administratie_id, naam="Ander Persoon", e_mail=e_mail))
        assert dubbel.status_code == 409, dubbel.text
        assert "al in gebruik" in dubbel.json()["detail"]

    def test_rolgroep_poort_geldt_ook_voor_de_paneel_ingang(self, administratie_id, beheerder_id):
        resp = self._post(beheerder_id, self._body(administratie_id, rol="boekhouding"))
        assert resp.status_code == 422, resp.text
        with pytest.raises(auth_service.RolgroepPastNietBijIngang):
            auth_service.toets_rolgroep_bij_bron(bron="planning_paneel", rol=GebruikerRol.BEHEERDER)
        auth_service.toets_rolgroep_bij_bron(bron="planning_paneel", rol=GebruikerRol.UITVOERDER)


class TestDossierOnvolledigSetBased:
    def test_nieuwe_veldwerker_onvolledig_geblokkeerd_onvolledig_en_statements_onafhankelijk_van_aantal(
        self, admin_engine, administratie_id, zzper, beheerder_id
    ):
        anderen = [maak_gebruiker(admin_engine, "zzper", f"Persoon {i}") for i in range(4)]
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(VeldwerkerDossier(administratie_id=administratie_id, gebruiker_id=anderen[0], geblokkeerd=True))
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            with _Teller() as klein:
                een = dossier_service.onvolledig_per_veldwerker(
                    session, administratie_id=administratie_id, gebruiker_ids=[zzper]
                )
            with _Teller() as groot:
                veel = dossier_service.onvolledig_per_veldwerker(
                    session, administratie_id=administratie_id, gebruiker_ids=[zzper, *anderen]
                )
            assert (
                dossier_service.onvolledig_per_veldwerker(session, administratie_id=administratie_id, gebruiker_ids=[])
                == {}
            )
        assert een == {zzper: True}  # zonder één document: alle verplichte typen ontbreken
        assert veel[anderen[0]] is True and all(veel[g] is True for g in anderen)
        assert len(groot.statements) == len(klein.statements), (len(klein.statements), len(groot.statements))

    def test_zonder_verplichte_typen_en_zonder_signalen_is_het_dossier_niet_onvolledig(
        self, administratie_id, zzper, beheerder_id
    ):
        dossier_service.zet_documenttypen(
            administratie_id=administratie_id,
            typen=[dossier_service.TypeDef("vca", "VCA", False, False, False, 1)],
            actor_id=beheerder_id,
        )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            uit = dossier_service.onvolledig_per_veldwerker(
                session, administratie_id=administratie_id, gebruiker_ids=[zzper]
            )
        assert uit == {zzper: False}
        week = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id
        )
        assert next(p for p in week.pool if p.gebruiker_id == zzper).dossier_onvolledig is False
