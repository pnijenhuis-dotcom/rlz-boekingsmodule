# ruff: noqa: F811 — pytest-fixtures als parameters
"""Opdracht 19-09 — pro-rato projectverdeling × projectstatus (nazorg rapport 2026-09-18-facturen-zonder-project,
beslispunt 3).

A1 de omzetsleutel neemt uitsluitend projecten mét `is_actief` ÉN module-status ≠ afgesloten; een project dat alleen op
   NAAM "Afgesloten" zegt blijft in de sleutel (nooit stil uitsluiten op naam) en is een LET-OP "afsluiten?";
A2 afsluiten (0160-flow) herrekent de nog niet geboekte verdelingen die het project raken mét tijdlijnregel + audit,
   geboekte verdelingen blijven staan; heropenen is het spiegelbeeld;
A3 lees-only rapport: geboekte delen op afgesloten/'Afgesloten'-projecten mét voorstel per rij, overhead via de sleutel;
   reconciliatieblok `projecten` draagt de LET-OP (soort start in `meten`)."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.documenten.models import DocumentGebeurtenis
from app.projecten import kantoor
from app.projecten import nummer as nummer_module
from app.projecten import status as status_service
from app.projectverdeling import afgesloten, service
from app.projectverdeling import data as pv
from app.projectverdeling.cli_cmd import run_projectverdeling
from app.projectverdeling.models import Projectverdeling
from app.projectverdeling.omzet import actieve_projecten_met_afgesloten_naam, naam_zegt_afgesloten, omzet_per_project
from app.reconciliatie import soort_stand, teksten
from app.reconciliatie.run import Verzamelaar
from app.sync.models import PROJECT_STATUS_AFGESLOTEN
from tests.projecten.conftest import FakeProjectClient
from tests.projectverdeling.conftest import PERIODE, seed_omzet


def _hernoem(admin_engine: Engine, aid: uuid.UUID, pid: uuid.UUID, naam: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.project_cache SET naam = :naam WHERE id = :id AND administratie_id = :aid"),
            {"naam": naam, "id": pid, "aid": aid},
        )


def _rij(aid: uuid.UUID, document_id: uuid.UUID) -> Projectverdeling:
    with scoped_session(aid) as session:
        row = session.scalar(select(Projectverdeling).where(Projectverdeling.document_id == document_id))
        assert row is not None
        session.expunge(row)
        return row


def _tijdlijn_redenen(aid: uuid.UUID, document_id: uuid.UUID) -> list[str]:
    with scoped_session(aid) as session:
        return [
            (g.detail or {}).get("reden", "")
            for g in session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip)
            )
        ]


def _project_via_motor(
    aid: uuid.UUID, actor: uuid.UUID, fake: FakeProjectClient, nummer: str, plaats: str
) -> uuid.UUID:
    return kantoor.maak_project_aan(
        administratie_id=aid, actor_id=actor, projectnummer=nummer, plaats=plaats, opdrachtgever="Test", client=fake
    ).rlz_project_id


class TestNaam:
    def test_naam_zegt_afgesloten_is_deterministisch_op_het_eerste_woord(self) -> None:
        assert naam_zegt_afgesloten("Afgesloten 26012 Tilburg (van Kasteren)")
        assert naam_zegt_afgesloten("afgesloten Wildvank")
        assert naam_zegt_afgesloten("  AFGESLOTEN: 25017 Kudo")
        assert not naam_zegt_afgesloten("26012 Tilburg (Afgesloten fase)")
        assert not naam_zegt_afgesloten("Afgeslotenweg 12")
        assert not naam_zegt_afgesloten(None) and not naam_zegt_afgesloten("")


class TestSleutel:
    def test_module_afgesloten_valt_uit_de_sleutel_ook_als_de_bron_nog_actief_zegt(
        self, admin_engine: Engine, administratie_id, projecten
    ) -> None:
        """Bron-spiegel `is_actief` blijft true (RLZ heropend buiten de module om) maar de module-status is afgesloten →
        uit de sleutel: de status is leidend náást `is_actief`."""
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.project_cache SET status = 'afgesloten' WHERE id = :id AND administratie_id "
                    "= :aid"
                ),
                {"id": projecten["tilburg"], "aid": administratie_id},
            )
        with scoped_session(administratie_id) as session:
            selectie = omzet_per_project(session, administratie_id=administratie_id, periode=PERIODE)
        assert {s.project_id for s in selectie.standen} == {projecten["eindhoven"], projecten["venlo"]}
        assert selectie.naam_afgesloten_actief == []

    def test_naam_afgesloten_blijft_in_de_sleutel_en_is_een_let_op(
        self, admin_engine: Engine, administratie_id, projecten
    ) -> None:
        _hernoem(admin_engine, administratie_id, projecten["venlo"], "Afgesloten 26131 Venlo (Dura)")
        with scoped_session(administratie_id) as session:
            selectie = omzet_per_project(session, administratie_id=administratie_id, periode=PERIODE)
            let_op = actieve_projecten_met_afgesloten_naam(session, administratie_id=administratie_id)
            bevindingen = afgesloten.let_op_bevindingen(
                session, administratie_id=administratie_id, administratie_naam="Test"
            )
        # Nooit stil uitsluiten op naam: Venlo telt nog mee (15 %) …
        assert {s.project_id for s in selectie.standen} == {
            projecten["eindhoven"],
            projecten["tilburg"],
            projecten["venlo"],
        }
        # … maar wordt als signaal gemarkeerd.
        assert [s.project_id for s in selectie.naam_afgesloten_actief] == [projecten["venlo"]]
        assert [p.id for p in let_op] == [projecten["venlo"]]
        assert len(bevindingen) == 1
        b = bevindingen[0]
        assert b["soort"] == "let_op" and b["detail"]["afwijking_soort"] == afgesloten.SOORT_NAAM_AFGESLOTEN
        assert b["vingerafdruk"] == f"projecten:{administratie_id}:naam_afgesloten:{projecten['venlo']}"
        assert "afsluiten?" in b["tekst"]
        # Een écht afgesloten project met zo'n naam is géén LET-OP meer (de actie is gedaan).
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.project_cache SET status = 'afgesloten', is_actief = false "
                    "WHERE id = :id AND administratie_id = :aid"
                ),
                {"id": projecten["venlo"], "aid": administratie_id},
            )
        with scoped_session(administratie_id) as session:
            assert actieve_projecten_met_afgesloten_naam(session, administratie_id=administratie_id) == []


class TestHerberekeningBijStatuswissel:
    def test_afsluiten_herrekent_voorstel_met_tijdlijn_en_audit_heropenen_spiegelt(
        self,
        admin_engine: Engine,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        document_zonder_project,
        projecten,
    ) -> None:
        fake = FakeProjectClient()
        ede = _project_via_motor(administratie_id, beheerder_id, fake, "26150", "Ede")
        seed_omzet(admin_engine, administratie_id, ede, "10000.00", date(2026, 7, 8))  # 50 % van de juli-omzet
        data = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        assert data is not None and data.compleet
        assert ede in {d.project_id for d in data.delen}
        voor = _rij(administratie_id, document_zonder_project)
        assert ede in {uuid.UUID(d["project_id"]) for d in voor.verdeling}
        ede_deel = next(d for d in voor.verdeling if d["project_id"] == str(ede))
        assert Decimal(ede_deel["bedrag"]) == Decimal("1000.00")

        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=ede, actor_id=beheerder_id, reden="klaar", client=fake
        )

        na = _rij(administratie_id, document_zonder_project)
        assert na.status == pv.STATUS_VOORSTEL
        assert ede not in {uuid.UUID(d["project_id"]) for d in na.verdeling}
        assert sum(Decimal(d["bedrag"]) for d in na.verdeling) == Decimal("2000.00")
        assert ede not in {uuid.UUID(s["project_id"]) for s in na.omzetstanden}
        redenen = _tijdlijn_redenen(administratie_id, document_zonder_project)
        assert "verdeling herberekend: 26150 Ede (Test) afgesloten" in redenen
        with scoped_session(administratie_id) as session:
            audits = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.actie == "projectverdeling_herberekend",
                        AuditEvent.record_id == document_zonder_project,
                    )
                )
            )
        assert len(audits) == 1 and audits[0].nieuwe_waarde["project_id"] == str(ede)
        # De live lezing en het snapshot zeggen nu hetzelfde.
        from app.documenten import boekvoorstel

        live = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        ).projectverdeling
        assert live is not None and {d.project_id for d in live.delen} == {
            uuid.UUID(d["project_id"]) for d in na.verdeling
        }

        # Heropenen = spiegelbeeld: Ede komt terug, eigen tijdlijnregel.
        status_service.heropen_project(
            administratie_id=administratie_id, project_id=ede, actor_id=beheerder_id, client=fake
        )
        terug = _rij(administratie_id, document_zonder_project)
        assert ede in {uuid.UUID(d["project_id"]) for d in terug.verdeling}
        assert "verdeling herberekend: 26150 Ede (Test) heropend" in _tijdlijn_redenen(
            administratie_id, document_zonder_project
        )

    def test_voorstel_zonder_het_project_krijgt_geen_tijdlijnregel(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, document_zonder_project, projecten
    ) -> None:
        """Weert (omzetloos) zit niet in de sleutel: afsluiten raakt de verdeling niet → geen regel, geen audit."""
        fake = FakeProjectClient()
        weert = _project_via_motor(administratie_id, beheerder_id, fake, "26160", "Weert")
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        uitkomst = afgesloten.herbereken_na_projectstatus(
            administratie_id=administratie_id,
            project_id=weert,
            project_naam="26160 Weert (Test)",
            naar=PROJECT_STATUS_AFGESLOTEN,
            actor_id=beheerder_id,
        )
        assert uitkomst.bekeken == 0 and uitkomst.herberekend == 0
        assert not any("herberekend" in r for r in _tijdlijn_redenen(administratie_id, document_zonder_project))

    def test_geboekte_verdeling_blijft_staan_en_rapport_toont_voorstel(
        self,
        admin_engine: Engine,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        document_zonder_project,
        projecten,
    ) -> None:
        fake = FakeProjectClient()
        ede = _project_via_motor(administratie_id, beheerder_id, fake, "26150", "Ede")
        naam_af = _project_via_motor(administratie_id, beheerder_id, fake, "26151", "Wamel")
        _hernoem(admin_engine, administratie_id, naam_af, "Afgesloten 26151 Wamel (Test)")
        # Bevroren (geboekte) verdeling — rechtstreeks als boekstand gezet (het boekpad zelf is elders getest).
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                Projectverdeling(
                    administratie_id=administratie_id,
                    document_id=document_zonder_project,
                    status=pv.STATUS_GEBOEKT,
                    pro_rato_periode=PERIODE,
                    pro_rato_bedrag=Decimal("2000.00"),
                    verdeling=[
                        {"project_id": str(ede), "wijze": "pro_rato", "bedrag": "1200.00"},
                        {"project_id": str(naam_af), "wijze": "pro_rato", "bedrag": "500.00"},
                        {"project_id": str(projecten["eindhoven"]), "wijze": "pro_rato", "bedrag": "300.00"},
                    ],
                    omzetstanden=[],
                    boek_cyclus=0,
                )
            )
        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=ede, actor_id=beheerder_id, client=fake
        )
        row = _rij(administratie_id, document_zonder_project)
        assert row.status == pv.STATUS_GEBOEKT and len(row.verdeling) == 3  # boekstand onaangeroerd
        assert not any("herberekend" in r for r in _tijdlijn_redenen(administratie_id, document_zonder_project))

        with scoped_session(administratie_id) as session:
            rijen = afgesloten.rapport_geboekt_op_afgesloten(session, administratie_id=administratie_id)
        per_project = {r.project_id: r for r in rijen}
        assert set(per_project) == {ede, naam_af}  # Eindhoven (lopend, actief) staat er niet in
        assert per_project[ede].project_stand == "afgesloten (module)" and per_project[ede].bedrag == Decimal("1200.00")
        assert "storno 19 + herverdeling" in per_project[ede].voorstel
        assert per_project[naam_af].project_stand == "naam zegt afgesloten, actief"
        assert per_project[naam_af].voorstel.startswith("laten staan tot het project is afgesloten")
        assert per_project[ede].referentie == "FB-2026-0731"


class TestReconciliatieEnRapport:
    def test_blok_projecten_draagt_let_op_zonder_exit_1_en_soort_start_in_meten(
        self, admin_engine: Engine, administratie_id, projecten
    ) -> None:
        _hernoem(admin_engine, administratie_id, projecten["eindhoven"], "Afgesloten 26120 Eindhoven (BAM)")
        verzamelaar = Verzamelaar()
        verzamelaar.start_blok(nummer_module.BLOK)
        uit: list[str] = []
        exit_code = nummer_module.cli_blok(None, verzamelaar=verzamelaar, stdout=uit.append)
        assert exit_code == 0  # een LET-OP is geen afwijking
        bev = [b for b in verzamelaar.bevindingen if b.blok == "projecten" and b.soort == "let_op"]
        assert len(bev) == 1
        assert bev[0].detail["afwijking_soort"] == afgesloten.SOORT_NAAM_AFGESLOTEN
        assert bev[0].detail["project_naam"] == "Afgesloten 26120 Eindhoven (BAM)"
        assert soort_stand.code_default(afgesloten.SOORT_NAAM_AFGESLOTEN) == soort_stand.METEN
        leesbaar = teksten.leesbaar(bev[0], administratie_naam="Scope-test")
        assert leesbaar.titel.startswith("Project heet 'Afgesloten' maar staat actief")
        assert "Afgesloten 26120 Eindhoven (BAM)" in leesbaar.wat
        assert "Projecten › Afsluiten" in leesbaar.doe
        assert any("1 actief project(en) mét 'Afgesloten'-naam" in r for r in uit)

    def test_overhead_rapport_en_cli(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten, capsys
    ) -> None:
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        with scoped_session(administratie_id) as session:
            zonder_gb = afgesloten.rapport_overhead_via_sleutel(session, administratie_id=administratie_id)
        assert len(zonder_gb.rijen) == 1 and not zonder_gb.rijen[0].overhead  # grootboek onbekend = nooit raden
        assert not zonder_gb.heeft_ovh_project or zonder_gb.ovh_projecten  # fixture heeft een OVH-project
        with scoped_session(administratie_id) as session:
            ledger_id = session.execute(
                text("SELECT ledger_id FROM boekhouding.boekvoorstel_regel WHERE document_id = :d"),
                {"d": document_zonder_project},
            ).scalar_one()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.grootboekrekening (ledger_id, administratie_id, code, naam, soort, "
                    "is_totaalrekening) VALUES (:l, :aid, '4499', 'Diverse kantoorkosten', 2, false)"
                ),
                {"l": ledger_id, "aid": administratie_id},
            )
        with scoped_session(administratie_id) as session:
            rapport = afgesloten.rapport_overhead_via_sleutel(session, administratie_id=administratie_id)
        assert rapport.rijen[0].overhead and rapport.rijen[0].grootboek == ["4499 Diverse kantoorkosten"]
        assert rapport.onderweg_overhead == Decimal("2000.00") and rapport.geboekt_overhead == Decimal("0")
        assert rapport.heeft_ovh_project and rapport.ovh_projecten == ["OVH · Overhead / algemene kosten"]

        rc = run_projectverdeling(
            argparse.Namespace(
                commando="projectverdeling-afgesloten-rapport",
                administratie=str(administratie_id),
                alle_projectverplicht=False,
            )
        )
        out = capsys.readouterr().out
        assert rc == 0 and "LEES-ONLY" in out and "OVERHEAD" in out and "OVH-project aanwezig: ja" in out
        assert "Totaal: 0 actief project(en) mét 'Afgesloten'-naam, 0 geboekt(e) verdelingsdeel(en)" in out
