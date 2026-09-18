"""Planning — urenstatus in het grid + terugwerkende kracht (Peter/Haci 15-09, Universal Steigerbouw).

A. Per kaartje de urenstatus uit de weekstaat (één leesbron, set-based): grijs 'geen', blauw 'ingevuld' (uren · m²),
   groen 'gekeurd' (door wie/wanneer), oranje 'vraag' (afgekeurd); weektotaal per rij; querytelling constant in het
   aantal projecten (meetlat zoals test_tellers_querytelling.py).
B. Wijziging in een verstreken/lopende week: audit draagt `achteraf`/`week_status`, één OPEN melding-rij per
   veldwerker × week (gebundeld), de 10-min-job stuurt één push per persoon × week en sluit de rijen; toekomstige
   week = niets.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, event, select, text

from app.auth import service as auth_service
from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.db import session as db_session
from app.db.session import scoped_session
from app.tijd import vandaag_nl
from app.uren import planning, planning_meldingen, service
from app.uren.models import PlanningWijzigingMelding
from tests.uren.conftest import maak_project

JAAR, WEEK = 2026, 35
MA = date(2026, 8, 24)
DI = date(2026, 8, 25)
WO = date(2026, 8, 26)
VANDAAG = date(2026, 8, 27)  # donderdag in week 35
#: Buiten de stille uren (20:00–08:00 NL) — de job verstuurt anders niets.
WERKTIJD = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


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


def _plan(administratie_id, gebruiker, project_id, datum, actor):  # noqa: ANN001
    planning.plan_toewijzing(
        administratie_id=administratie_id, gebruiker_id=gebruiker, project_id=project_id, datum=datum, actor_id=actor
    )


def _uren(administratie_id, zzper, project_id, datum, uren="8", m2=None):  # noqa: ANN001
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        m2=Decimal(m2) if m2 else None,
        actor_id=zzper,
    )


def _grid(administratie_id, beheerder_id):  # noqa: ANN001
    return planning.planning_overzicht(
        administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
    )


class TestUrenstatusInHetGrid:
    def test_vier_standen_en_weektotaal(self, administratie_id, project_id, zzper, uitvoerder, beheerder_id) -> None:
        for d in (MA, DI, WO, date(2026, 8, 28)):
            _plan(administratie_id, zzper, project_id, d, beheerder_id)
        # 18-09: keuren vereist scope op de administratie (koppeling is geen keurpoort meer); plannen koppelt zelf.
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id
        )
        _plan(administratie_id, uitvoerder, project_id, date(2026, 8, 28), beheerder_id)
        # ma: gekeurd (8 u, 42 m²); di: ingevuld (concept, 6 u); wo: niets; vr: nog niet aan de beurt.
        _uren(administratie_id, zzper, project_id, MA, "8", "42")
        staat = service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=zzper,
        )
        # Keuring door de uitvoerder gebeurt op weekniveau; voor de status-afleiding is de weekstaat-status leidend.
        service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)
        grid = _grid(administratie_id, beheerder_id)
        rij = next(r for r in grid.projecten if r.project_id == project_id)
        (ma,) = rij.per_datum[MA.isoformat()]
        assert (ma.uren_status, ma.uren, ma.m2) == (planning.UREN_STATUS_GEKEURD, Decimal("8.00"), Decimal("42.00"))
        assert ma.uren_detail is not None and ma.uren_detail.startswith("8 u · 42 m² · gekeurd door ")
        # Week 35 ligt in het verleden t.o.v. het planmoment (vandaag) → 'achteraf' — de test plant historisch.
        assert ma.weekstaat_id == staat.id and ma.achteraf is True
        (wo,) = rij.per_datum[WO.isoformat()]
        assert (wo.uren_status, wo.uren, wo.uren_detail) == (planning.UREN_STATUS_GEEN, None, "geen uren ingevuld")
        # De weekstaat is per persoon × project × week: ma én di staan in dezelfde (nu goedgekeurde) staat.
        assert rij.week_uren.gekeurd_uren == Decimal("8") and rij.week_uren.ingevuld_uren == Decimal("8")
        assert rij.week_uren.open_aantal == 0
        # di + wo (gepland, geen uren, vóór vandaag) tellen als "zonder uren"; vr ligt ná vandaag en telt niet.
        assert rij.week_uren.zonder_uren_aantal == 2

    def test_ingevuld_en_afgekeurd(self, administratie_id, project_id, zzper, uitvoerder, beheerder_id) -> None:
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, DI, beheerder_id)
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id
        )
        _plan(administratie_id, uitvoerder, project_id, DI, beheerder_id)
        _uren(administratie_id, zzper, project_id, MA, "6")
        rij = next(r for r in _grid(administratie_id, beheerder_id).projecten if r.project_id == project_id)
        (ma,) = rij.per_datum[MA.isoformat()]
        assert ma.uren_status == planning.UREN_STATUS_INGEVULD and "6 u · ingevuld (concept)" in (ma.uren_detail or "")
        staat = service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=zzper,
        )
        service.keur_week_af(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder, reden="10 u i.p.v. 8 u"
        )
        rij = next(r for r in _grid(administratie_id, beheerder_id).projecten if r.project_id == project_id)
        (ma,) = rij.per_datum[MA.isoformat()]
        assert ma.uren_status == planning.UREN_STATUS_VRAAG and "afgekeurd door" in (ma.uren_detail or "")
        assert "10 u i.p.v. 8 u" in (ma.uren_detail or "")
        assert rij.week_uren.open_aantal == 1 and rij.week_uren.gekeurd_uren == Decimal("0")

    def test_querytelling_constant_in_het_aantal_projecten(
        self, admin_engine: Engine, administratie_id, zzper, beheerder_id
    ) -> None:
        """Set-based: N=3 en N=12 projecten mét planning én uren geven hetzelfde aantal statements."""

        def _opzet(n: int) -> None:
            for i in range(n):
                pid = maak_project(admin_engine, administratie_id, f"Project {n}-{i}")
                _plan(administratie_id, zzper, pid, MA, beheerder_id)
                _uren(administratie_id, zzper, pid, MA, "4")

        _opzet(3)
        with _Teller() as klein:
            _grid(administratie_id, beheerder_id)
        _opzet(9)
        with _Teller() as groot:
            _grid(administratie_id, beheerder_id)
        assert len(groot.statements) == len(klein.statements), (len(klein.statements), len(groot.statements))


@pytest.fixture
def push_ok(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def _nep(gebruiker, *, onderwerp, pushtekst, mailtekst, url, extra_payload=None):  # noqa: ANN001
        verzonden.append({"gebruiker_id": gebruiker.id, "onderwerp": onderwerp, "pushtekst": pushtekst, "url": url})
        return verzending.VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": 1}, 0)

    monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _nep)
    return verzonden


def _open_rijen(administratie_id) -> list[PlanningWijzigingMelding]:  # noqa: ANN001
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(select(PlanningWijzigingMelding)).all()
        for r in rijen:
            session.expunge(r)
        return list(rijen)


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"), {"a": actie}
            )
        ]


class TestTerugwerkendeKracht:
    def test_wijziging_in_verstreken_week_geeft_audit_vlag_en_een_gebundelde_melding(
        self, admin_engine: Engine, administratie_id, project_id, tweede_project_id, zzper, beheerder_id, push_ok
    ) -> None:
        vandaag = vandaag_nl()
        vorige_week = vandaag - timedelta(days=7 + vandaag.weekday())  # maandag van vorige week
        _plan(administratie_id, zzper, project_id, vorige_week, beheerder_id)
        _plan(administratie_id, zzper, project_id, vorige_week + timedelta(days=1), beheerder_id)
        planning.verplaats_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            van_project_id=project_id,
            van_datum=vorige_week,
            naar_project_id=tweede_project_id,
            naar_datum=vorige_week,
            actor_id=beheerder_id,
        )
        audit = _audit(admin_engine, "planning_gepland")
        assert audit[-1]["achteraf"] is True and audit[-1]["week_status"] == "verstreken"
        assert audit[-1]["veldwerker_gemeld"] is True
        # Drie wijzigingen in dezelfde week → één open rij mét teller 3.
        (rij,) = _open_rijen(administratie_id)
        assert (rij.gebruiker_id, rij.gemeld_op, rij.aantal_wijzigingen) == (zzper, None, 3)
        assert (rij.jaar, rij.weeknummer) == vorige_week.isocalendar()[:2]
        # De job bundelt tot één bericht en sluit de rij.
        rapport = planning_meldingen.verstuur_planning_meldingen(nu=WERKTIJD)
        assert (rapport.kandidaten, rapport.berichten, rapport.verzonden_push, rapport.mislukt) == (1, 1, 1, 0)
        (bericht,) = push_ok
        week = vorige_week.isocalendar()[1]
        assert bericht["gebruiker_id"] == zzper and f"week {week}" in bericht["pushtekst"]
        assert bericht["url"] == f"/accordeur?planning={vorige_week.isocalendar()[0]}-W{week:02d}"
        (rij,) = _open_rijen(administratie_id)
        assert rij.gemeld_op is not None and rij.kanaal == "push"
        assert _audit(admin_engine, "planning_wijziging_gemeld")[-1]["aantal_wijzigingen"] == 3
        # Tweede run: niets open, niets verstuurd.
        rapport2 = planning_meldingen.verstuur_planning_meldingen(nu=WERKTIJD)
        assert rapport2.kandidaten == 0 and len(push_ok) == 1

    def test_toekomstige_week_geeft_geen_melding_en_geen_achteraf(
        self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id
    ) -> None:
        vandaag = vandaag_nl()
        volgende_week = vandaag + timedelta(days=7 - vandaag.weekday())
        _plan(administratie_id, zzper, project_id, volgende_week, beheerder_id)
        audit = _audit(admin_engine, "planning_gepland")
        assert audit[-1]["achteraf"] is False and audit[-1]["week_status"] == "toekomst"
        assert audit[-1]["veldwerker_gemeld"] is False
        assert _open_rijen(administratie_id) == []

    def test_lopende_week_meldt_wel_maar_is_niet_achteraf_voor_een_dag_vandaag_of_later(
        self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id
    ) -> None:
        vandaag = vandaag_nl()
        _plan(administratie_id, zzper, project_id, vandaag, beheerder_id)
        audit = _audit(admin_engine, "planning_gepland")[-1]
        assert audit["week_status"] == "lopend" and audit["achteraf"] is False and audit["veldwerker_gemeld"] is True
        assert len(_open_rijen(administratie_id)) == 1

    def test_puur_week_is_verstreken_of_lopend(self) -> None:
        assert planning.week_is_verstreken_of_lopend(date(2026, 9, 7), date(2026, 9, 15))  # week 37 vs 38: verstreken
        assert planning.week_is_verstreken_of_lopend(date(2026, 9, 20), date(2026, 9, 15))  # zondag zelfde week 38
        assert not planning.week_is_verstreken_of_lopend(date(2026, 9, 21), date(2026, 9, 15))  # week 39

    def test_achteraf_chip_in_het_grid(self, administratie_id, project_id, zzper, beheerder_id) -> None:
        vandaag = vandaag_nl()
        gisteren = vandaag - timedelta(days=1)
        _plan(administratie_id, zzper, project_id, gisteren, beheerder_id)
        jaar, week, _ = gisteren.isocalendar()
        grid = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=jaar, weeknummer=week, actor_id=beheerder_id, vandaag=vandaag
        )
        rij = next(r for r in grid.projecten if r.project_id == project_id)
        (kaart,) = rij.per_datum[gisteren.isoformat()]
        assert kaart.achteraf is True and kaart.uren_status == planning.UREN_STATUS_GEEN
