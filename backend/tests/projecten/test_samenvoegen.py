# ruff: noqa: F811 — pytest-fixtures als parameters
"""Run A 02-10 punt 11 (Peter: "per abuis is 2x projectnummer 26149 gemaakt, moet gecheckt en voorkomen worden").

Diagnose (leesreplica 02-10): "26149" (RLZ-UI, alleen het nummer als naam) náást "26149 Poeldijk, Anjerstraat 245 (Weboma)"
(projectenmodule, 18-09 15:23) — de 0160-poort zocht in RLZ op `startswith(Name,'26149 ')` mét spatie en zag het kale
RLZ-UI-project niet. Hier: (1) de poort treft nu óók een project dat alléén het nummer heet (cache én RLZ); (2) route A
(pand-project) loopt door dezelfde nummerpoort; (3) nazorg-CLI `project-dubbel-samenvoegen` — dry-run default, `--uitvoeren`
hangt om mét audit + tijdlijn en sluit de verliezer af via de 0160-flow; conflicten blijven staan (nooit verwijderen);
idempotent; (4) FK-dekking-guard: élke project-kolom in Base.metadata staat in het REGISTER; (5) `dubbele_nummers` telt een
samengevoegde verliezer niet meer."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, select, text

from app import cli
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.projecten import kantoor, motor, samenvoegen
from app.projecten import nummer as nummer_module
from app.sync.models import ProjectCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.projecten.conftest import FakeProjectClient
from tests.uren.conftest import maak_gebruiker, maak_project

NUMMER = "26149"
KAAL = "26149"
VOL = "26149 Poeldijk, Anjerstraat 245 (Weboma)"


def _rij(aid: uuid.UUID, pid: uuid.UUID) -> ProjectCache:
    with scoped_session(aid) as session:
        rij = session.get(ProjectCache, (pid, aid))
        session.expunge(rij)
        return rij


def _tel(admin_engine: Engine, sql: str, **params) -> int:
    with admin_engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar() or 0)


class TestPoortDichtgezet:
    def test_rlz_project_dat_alleen_het_nummer_heet_blokkeert_nu(self, administratie_id, beheerder_id) -> None:
        """De 26149-casus: het RLZ-UI-project heet exact "26149" (geen spatie erachter) — vóór 02-10 onzichtbaar voor de
        `startswith(Name,'26149 ')`-poort, nu 409."""
        fake = FakeProjectClient()
        extern = uuid.uuid4()
        fake.projects["rlz-ui"] = {"id": str(extern), "Name": KAAL, "IsActive": True}
        with pytest.raises(nummer_module.ProjectnummerBestaatAl) as exc:
            kantoor.maak_project_aan(
                administratie_id=administratie_id, actor_id=beheerder_id, projectnummer=NUMMER,
                plaats="Poeldijk, Anjerstraat 245", opdrachtgever="Weboma", client=fake,
            )
        assert exc.value.treffer.project_id == extern and exc.value.treffer.bron == "rlz"
        assert fake.put_project_aanroepen == 0
        assert fake.prefixes_aanroepen == [(KAAL, f"Afgesloten {KAAL}")]
        # "261490" blijft géén treffer voor 26149 (lokale exacte toets), dus 26149 is vrij zodra het kale project weg is.
        fake.projects = {"lang": {"id": str(uuid.uuid4()), "Name": "261490 Ander", "IsActive": True}}
        res = kantoor.maak_project_aan(
            administratie_id=administratie_id, actor_id=beheerder_id, projectnummer=NUMMER,
            plaats="Poeldijk", opdrachtgever="Weboma", client=fake,
        )
        assert res.bestond_al is False

    def test_kale_naam_in_de_cache_blokkeert_ook(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        pid = maak_project(admin_engine, administratie_id, KAAL)
        with pytest.raises(nummer_module.ProjectnummerBestaatAl) as exc:
            kantoor.maak_project_aan(
                administratie_id=administratie_id, actor_id=beheerder_id, projectnummer=NUMMER,
                plaats="Poeldijk", opdrachtgever="Weboma", client=FakeProjectClient(),
            )
        assert exc.value.treffer.project_id == pid and exc.value.treffer.bron == "cache"

    def test_route_a_pandproject_loopt_door_de_nummerpoort(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        """Route A toetste tot 02-10 alleen de exacte naam — een pandnaam mét cijfer-prefix naast een bestaand nummer = conflict."""
        maak_project(admin_engine, administratie_id, VOL)
        fake = FakeProjectClient()
        with pytest.raises(motor.ProjectNaamConflict):
            motor.maak_pand_project_aan(
                administratie_id=administratie_id, actor_id=beheerder_id, pand_referentie="pand-1",
                naam_invoer="26149 Dorpsstraat 1, Zwolle", client=fake,
            )
        assert fake.put_project_aanroepen == 0
        # Zonder cijfer-prefix (het normale pand-formaat) verandert er niets.
        res = motor.maak_pand_project_aan(
            administratie_id=administratie_id, actor_id=beheerder_id, pand_referentie="pand-2",
            naam_invoer="Dorpsstraat 1, Zwolle", client=fake,
        )
        assert fake.put_project_aanroepen == 1 and res.projectnaam == "Dorpsstraat 1, Zwolle"


class TestFkDekkingGuard:
    def test_elke_projectkolom_in_metadata_staat_in_het_register(self) -> None:
        geregistreerd = {(k.tabel, k.kolom) for k in samenvoegen.REGISTER}
        ontbreekt = samenvoegen.project_kolommen_in_metadata() - geregistreerd
        assert not ontbreekt, f"project-kolommen zonder omhang-/rapportregel in samenvoegen.REGISTER: {sorted(ontbreekt)}"
        for k in samenvoegen.REGISTER:
            t = samenvoegen._tabel(k.tabel)  # bestaat
            if k.wijze != samenvoegen.EIGEN:
                assert k.kolom in t.c, f"{k.tabel}.{k.kolom} bestaat niet"
        assert {k.wijze for k in samenvoegen.REGISTER} <= {
            samenvoegen.OMHANGEN, samenvoegen.RAPPORT, samenvoegen.JSON_LIJST, samenvoegen.EIGEN
        }
        for k in samenvoegen.REGISTER:
            if k.wijze == samenvoegen.RAPPORT:
                assert k.reden, f"{k.tabel}: RAPPORT zonder reden"


class TestBlijver:
    def _k(self, naam: str, *, kopp: int = 0, op: datetime | None = None, module: bool = False, status="lopend", reden=None):
        return samenvoegen.Kandidaat(
            project_id=uuid.uuid5(uuid.NAMESPACE_URL, naam), naam=naam, status=status, is_actief=True,
            afsluit_reden=reden, aangemaakt_op=op, module_aangemaakt=module, koppelingen={"x": kopp} if kopp else {},
        )

    def test_oudste_met_koppelingen_wint(self) -> None:
        oud_leeg = self._k("26149", op=datetime(2026, 9, 18, 10, tzinfo=UTC))
        jong_vol = self._k(VOL, kopp=25, op=datetime(2026, 9, 18, 13, 23, tzinfo=UTC), module=True)
        assert samenvoegen.kies_blijver([oud_leeg, jong_vol]) is jong_vol
        oud_vol = self._k("26149 Oud (X)", kopp=1, op=datetime(2026, 9, 1, tzinfo=UTC))
        assert samenvoegen.kies_blijver([oud_vol, jong_vol]) is oud_vol  # beide koppelingen → oudste
        # Niemand koppelingen → oudste; onbekende leeftijd telt als jongst.
        onbekend = self._k("26149 Onbekend")
        assert samenvoegen.kies_blijver([oud_leeg, onbekend]) is oud_leeg
        # Al samengevoegde verliezer doet niet mee.
        klaar = self._k("26149 klaar", kopp=99, status="afgesloten", reden=f"{samenvoegen.SAMENVOEG_REDEN_PREFIX} 26149 — …")
        assert samenvoegen.kies_blijver([klaar, onbekend]) is onbekend
        # Volledig gelijk → via de module aangemaakt → langste naam → kleinste id: deterministisch.
        a = self._k("26149 A", module=True)
        b = self._k("26149 B (langer)")
        assert samenvoegen.kies_blijver([b, a]) is a
        assert samenvoegen.kies_blijver([self._k("26149 B (langer)"), self._k("26149 A")]).naam == "26149 B (langer)"


@pytest.fixture
def casus(admin_engine: Engine, administratie_id, beheerder_id):
    """De 26149-casus: kale verliezer mét wat koppelingen, volle blijver mét méér koppelingen; één reserverings-conflict."""
    kaal = maak_project(admin_engine, administratie_id, KAAL)
    vol = maak_project(admin_engine, administratie_id, VOL)
    zzper = maak_gebruiker(admin_engine, "zzper", "Irfan O.")
    with admin_engine.begin() as conn:
        # de blijver draagt de meeste koppelingen (zoals 42b27746… in productie: 18 planning, 5 reserveringen, 2 meerwerk)
        vol_dagen = (date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 30))
        for pid, dag in (*((vol, d) for d in vol_dagen), (kaal, date(2026, 9, 25))):
            conn.execute(
                text(
                    "INSERT INTO boekhouding.planning_toewijzing (administratie_id, gebruiker_id, project_id, datum, dagdeel, "
                    "toegevoegd_door) VALUES (:aid, :gid, :pid, :d, 'heel', :gid)"
                ),
                {"aid": administratie_id, "gid": zzper, "pid": pid, "d": dag},
            )
        # reserveringen: vol op 23-09 en 28-09; kaal op 28-09 (CONFLICT: blijft staan) en 29-09 (hangt om)
        for pid, dag in ((vol, date(2026, 9, 23)), (vol, date(2026, 9, 28)), (kaal, date(2026, 9, 28)), (kaal, date(2026, 9, 29))):
            conn.execute(
                text(
                    "INSERT INTO boekhouding.planning_reservering (id, administratie_id, project_id, datum, aangemaakt_door) "
                    "VALUES (:id, :aid, :pid, :d, :g)"
                ),
                {"id": uuid.uuid4(), "aid": administratie_id, "pid": pid, "d": dag, "g": beheerder_id},
            )
        conn.execute(
            text(
                "INSERT INTO boekhouding.leverancier_werknummer (id, administratie_id, project_id, vendor_id, werknummer, "
                "bron, bevestigd, aangemaakt_door) VALUES (:id, :aid, :pid, :v, 'W-26149', 'handmatig', false, :g)"
            ),
            {"id": uuid.uuid4(), "aid": administratie_id, "pid": kaal, "v": uuid.uuid4(), "g": beheerder_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.planning_conflict_akkoord (id, administratie_id, gebruiker_id, datum, soort, project_ids, "
                "reden, aangemaakt_door) VALUES (:id, :aid, :gid, :d, 'dubbel', CAST(:pids AS jsonb), 'beide halve dagen', :g)"
            ),
            {
                "id": uuid.uuid4(), "aid": administratie_id, "gid": zzper, "d": date(2026, 9, 25),
                "pids": f'["{kaal}", "{uuid.uuid4()}"]', "g": beheerder_id,
            },
        )
        # RLZ-factuurregel-cache op de verliezer: alleen RAPPORT (de factuur staat in RLZ op dat project).
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_regel_cache (id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag) "
                "VALUES (:id, :aid, :doc, 'inkoop', :pid, 100.00)"
            ),
            {"id": uuid.uuid4(), "aid": administratie_id, "doc": uuid.uuid4(), "pid": kaal},
        )
    return {"kaal": kaal, "vol": vol, "zzper": zzper}


class TestSamenvoegen:
    def test_dry_run_schrijft_niets_en_toont_het_plan(self, admin_engine: Engine, administratie_id, casus) -> None:
        uit = samenvoegen.samenvoegen(
            administratie_id=administratie_id, administratie_naam="Universal Steigerbouw", nummer=NUMMER, dry_run=True
        )
        assert uit.blijver is not None and uit.blijver.project_id == casus["vol"]  # meeste koppelingen (leeftijd onbekend)
        assert [v.kandidaat.project_id for v in uit.verliezers] == [casus["kaal"]]
        per = {t.tabel: t for t in uit.verliezers[0].tabellen}
        assert per["planning_toewijzing"].aantal == 1
        assert per["planning_reservering"].aantal == 1 and per["planning_reservering"].blijft == 1
        assert per["leverancier_werknummer"].aantal == 1
        assert per["planning_conflict_akkoord"].aantal == 1
        assert per["project_regel_cache"].blijft == 1 and per["project_regel_cache"].aantal == 0
        assert uit.omgehangen == 4 and uit.blijft == 2
        assert "zou afsluiten" in uit.verliezers[0].archief
        regels = samenvoegen.rapportregels(uit)
        assert regels[-1].startswith(f"TOTAAL: nummer {NUMMER} — blijft {casus['vol']}")
        assert "dry-run" in regels[-1] and "4 rij(en) omgehangen in 4 tabel(len)" in regels[-1]
        # niets geschreven
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.planning_toewijzing WHERE project_id = :p", p=casus["kaal"]) == 1
        assert _tel(admin_engine, "SELECT count(*) FROM platform.audit_event WHERE actie = :a", a=samenvoegen.AUDIT_OMGEHANGEN) == 0
        assert _rij(administratie_id, casus["kaal"]).status == "lopend"

    def test_uitvoeren_hangt_om_met_audit_sluit_af_en_is_idempotent(
        self, admin_engine: Engine, administratie_id, beheerder_id, casus
    ) -> None:
        fake = FakeProjectClient()
        fake.projects[str(casus["kaal"])] = {"id": str(casus["kaal"]), "Name": KAAL, "IsActive": True}
        uit = samenvoegen.samenvoegen(
            administratie_id=administratie_id, administratie_naam="Universal Steigerbouw", nummer=NUMMER,
            actor_id=beheerder_id, dry_run=False, client=fake,
        )
        assert uit.fout is None and uit.omgehangen == 4 and uit.blijft == 2
        kaal, vol = casus["kaal"], casus["vol"]
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.planning_toewijzing WHERE project_id = :p", p=kaal) == 0
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.planning_toewijzing WHERE project_id = :p", p=vol) == 6
        # conflict-reservering (28-09) blijft bij de verliezer staan — nooit verwijderd; 29-09 is omgehangen
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.planning_reservering WHERE project_id = :p", p=kaal) == 1
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.planning_reservering WHERE project_id = :p", p=vol) == 3
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.leverancier_werknummer WHERE project_id = :p", p=vol) == 1
        with admin_engine.connect() as conn:
            pids = conn.execute(text("SELECT project_ids FROM boekhouding.planning_conflict_akkoord")).scalar()
        assert str(vol) in pids and str(kaal) not in pids and pids == sorted(pids)
        # RAPPORT-tabel onaangeraakt
        assert _tel(admin_engine, "SELECT count(*) FROM boekhouding.project_regel_cache WHERE project_id = :p", p=kaal) == 1
        # audit: één per omgehangen rij + één samenvatting op de verliezer; alles binnen de administratie-scope
        with scoped_session(administratie_id) as session:
            omgehangen = list(session.scalars(select(AuditEvent).where(AuditEvent.actie == samenvoegen.AUDIT_OMGEHANGEN)))
            samengevoegd = list(session.scalars(select(AuditEvent).where(AuditEvent.actie == samenvoegen.AUDIT_SAMENGEVOEGD)))
        assert len(omgehangen) == 4 and {a.tabel for a in omgehangen} == {
            "planning_toewijzing", "planning_reservering", "leverancier_werknummer", "planning_conflict_akkoord"
        }
        assert all(a.oude_waarde[next(iter(a.oude_waarde))] == str(kaal) for a in omgehangen)
        assert len(samengevoegd) == 1 and samengevoegd[0].record_id == kaal
        assert samengevoegd[0].nieuwe_waarde["blijver_project_id"] == str(vol)
        assert samengevoegd[0].nieuwe_waarde["blijft_staan"] == {"planning (reserveringen)": 1, "RLZ-factuurregels (leescache)": 1}
        # verliezer afgesloten via de 0160-flow: RLZ IsActive false (teruggelezen) + status + reden-prefix
        rij = _rij(administratie_id, kaal)
        assert rij.status == "afgesloten" and rij.is_actief is False
        assert (rij.afsluit_reden or "").startswith(f"{samenvoegen.SAMENVOEG_REDEN_PREFIX} {NUMMER} — samengevoegd in {vol}")
        assert fake.projects[str(kaal)]["IsActive"] is False
        assert _rij(administratie_id, vol).status == "lopend"
        # dubbele_nummers telt de samengevoegde verliezer niet meer → de reconciliatie-soort sluit
        with scoped_session(administratie_id) as session:
            assert nummer_module.dubbele_nummers(session, administratie_id=administratie_id) == []
        # idempotent: tweede run hangt niets om en herkent de verliezer
        uit2 = samenvoegen.samenvoegen(
            administratie_id=administratie_id, administratie_naam="Universal Steigerbouw", nummer=NUMMER,
            actor_id=beheerder_id, dry_run=False, client=fake,
        )
        assert uit2.blijver.project_id == vol and uit2.omgehangen == 0
        assert uit2.verliezers[0].archief.startswith("al samengevoegd")
        with scoped_session(administratie_id) as session:
            assert session.scalar(select(AuditEvent).where(AuditEvent.actie == samenvoegen.AUDIT_OMGEHANGEN).limit(1)) is not None
            assert len(list(session.scalars(select(AuditEvent).where(AuditEvent.actie == samenvoegen.AUDIT_SAMENGEVOEGD)))) == 2

    def test_bron_weigert_blijft_zichtbaar_en_herhaalbaar(self, administratie_id, beheerder_id, casus) -> None:
        """Geen RLZ-project meer onder het verliezer-id → de 0160-flow weigert (bron wint); de koppelingen zijn wél
        omgehangen en de uitkomst zegt dat luid; een tweede run hangt niets dubbel."""
        fake = FakeProjectClient()  # verliezer bestaat niet in RLZ
        uit = samenvoegen.samenvoegen(
            administratie_id=administratie_id, administratie_naam="X", nummer=NUMMER,
            actor_id=beheerder_id, dry_run=False, client=fake,
        )
        assert uit.omgehangen == 4
        assert uit.fout and "bron weigert" in uit.fout and "run opnieuw" in uit.fout
        assert _rij(administratie_id, casus["kaal"]).status == "lopend"
        uit2 = samenvoegen.samenvoegen(
            administratie_id=administratie_id, administratie_naam="X", nummer=NUMMER,
            actor_id=beheerder_id, dry_run=False, client=fake,
        )
        assert uit2.omgehangen == 0 and uit2.blijver.project_id == casus["vol"]

    def test_geen_dubbel_is_geen_fout(self, admin_engine: Engine, administratie_id) -> None:
        maak_project(admin_engine, administratie_id, VOL)
        uit = samenvoegen.samenvoegen(administratie_id=administratie_id, administratie_naam="X", nummer=NUMMER)
        assert uit.verliezers == [] and uit.fout and "niets samen te voegen" in uit.fout
        assert samenvoegen.rapportregels(uit)[-1].startswith(f"TOTAAL: nummer {NUMMER} — niets samen te voegen")


class TestCli:
    def test_alle_vormen_uit_het_meetrecept(
        self, admin_engine: Engine, administratie_id, beheerder_id, casus, monkeypatch, capsys
    ) -> None:
        import app.rlz.credentials as cred

        fake = FakeProjectClient()
        fake.projects[str(casus["kaal"])] = {"id": str(casus["kaal"]), "Name": KAAL, "IsActive": True}
        monkeypatch.setattr(cred, "rlz_admin_id_voor", lambda aid: "fake-admin")
        monkeypatch.setattr(cred, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET naam = 'Universal Steigerbouw B.V.' WHERE id = :a"), {"a": administratie_id})
        # dry-run: zonder vlag (default), mét --dry-run, administratie als naam én als id
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal Steigerbouw", "--nummer", NUMMER]) == 0
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", str(administratie_id), "--nummer", NUMMER, "--dry-run"]) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN" in uit and f"TOTAAL: nummer {NUMMER} — blijft {casus['vol']}" in uit
        assert _rij(administratie_id, casus["kaal"]).status == "lopend"
        # argumentfouten
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", NUMMER, "--dry-run", "--uitvoeren"]) == 2
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", "26x49"]) == 2
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "bestaat-niet", "--nummer", NUMMER]) == 2
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", NUMMER, "--actor", "niemand@x.nl"]) == 2
        # echte run mét systeem-actor (default: passeert de rolpoort — de job-executie is de poort) en daarna idempotent
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", NUMMER, "--uitvoeren"]) == 0
        uit = capsys.readouterr().out
        assert "UITGEVOERD" in uit and "afgesloten via de 0160-flow" in uit
        rij = _rij(administratie_id, casus["kaal"])
        assert rij.status == "afgesloten" and fake.projects[str(casus["kaal"])]["IsActive"] is False
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", NUMMER, "--uitvoeren", "--actor", str(beheerder_id)]) == 0
        assert "al samengevoegd" in capsys.readouterr().out
        # geen RLZ-login = zichtbaar, exit 1, koppelingen al omgehangen
        kaal2 = maak_project(admin_engine, administratie_id, "26150 Een (A)")
        maak_project(admin_engine, administratie_id, "26150 Twee (B)")
        monkeypatch.setattr(cred, "client_voor_rlz_admin_id", lambda rlz_admin_id: (_ for _ in ()).throw(cred.GeenRlzCredentials("geen login")))
        assert cli.main(["project-dubbel-samenvoegen", "--administratie", "Universal", "--nummer", "26150", "--uitvoeren"]) == 1
        gelezen = capsys.readouterr()
        assert "bron weigert" in gelezen.err + gelezen.out
        assert _rij(administratie_id, kaal2).status == "lopend"
