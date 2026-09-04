"""Keten projectverdeling tegen de test-DB: omzetselectie, opt-in-prefill, opslaan + live herberekening, de
harde check "Projectverdeling", boeken via de RLZ-adapter (regels gesplitst mét Project, btw sluitend) mét bevroren
omzetstanden, tegenboek-spiegel, hercontrole boven/onder de drempel (idempotent) en herverdelen (aangifte-poort)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.documenten.models import DocumentStatus
from app.projectverdeling import data as pv
from app.projectverdeling import hercontrole, service
from app.projectverdeling.omzet import omzet_per_project
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.projectverdeling.conftest import PERIODE, seed_omzet

AANGIFTE_Q3_INGEDIEND = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _rij(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT status, pro_rato_bedrag, verdeling, omzetstanden, boek_cyclus, hercontrole_afwijking_pct, "
                    "hercontrole_verdeling FROM boekhouding.projectverdeling WHERE document_id = :id"
                ),
                {"id": document_id},
            )
            .mappings()
            .one()
        )


class TestOmzetSelectie:
    def test_alleen_actieve_niet_ovh_projecten_met_omzet_in_de_maand(self, administratie_id, projecten) -> None:
        with scoped_session(administratie_id) as session:
            selectie = omzet_per_project(session, administratie_id=administratie_id, periode=PERIODE)
        per_project = {s.project_id: s.omzet for s in selectie.standen}
        assert per_project == {
            projecten["eindhoven"]: Decimal("6000.00"),
            projecten["tilburg"]: Decimal("2500.00"),
            projecten["venlo"]: Decimal("1500.00"),
        }
        assert not selectie.cache_leeg

    def test_lege_maand_versus_lege_cache(self, administratie_id, projecten, admin_engine) -> None:
        with scoped_session(administratie_id) as session:
            geen = omzet_per_project(session, administratie_id=administratie_id, periode=date(2025, 1, 1))
        assert geen.standen == [] and not geen.cache_leeg
        with admin_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM boekhouding.project_regel_cache WHERE administratie_id = :aid"),
                {"aid": administratie_id},
            )
        with scoped_session(administratie_id) as session:
            leeg = omzet_per_project(session, administratie_id=administratie_id, periode=PERIODE)
        assert leeg.standen == [] and leeg.cache_leeg


class TestVoorstelEnPrefill:
    def test_zonder_opt_in_geen_verdeling(self, administratie_id, document_zonder_project, projecten) -> None:
        voorstel = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        )
        assert voorstel.projectverdeling is None

    def test_beschikbaar_volgt_projectplicht_of_actieve_projecten(
        self, admin_engine, administratie_id, projecten
    ) -> None:
        """B1 (04-09): beschikbaar op élk inkoopdocument zodra de administratie projectplicht heeft óf actieve
        projecten kent; een administratie zonder beide krijgt geen blok (beslispunt 6 van 04-09 ongewijzigd)."""
        assert service.is_beschikbaar(administratie_id=administratie_id) is True
        kaal = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Kaal (test)', :rlz)"),
                {"id": kaal, "rlz": f"rlz-{kaal}"},
            )
        assert service.is_beschikbaar(administratie_id=kaal) is False
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET project_verplicht = true WHERE id = :id"), {"id": kaal}
            )
        assert service.is_beschikbaar(administratie_id=kaal) is True

    def test_opt_in_geeft_prefill_met_alleen_restant(
        self, administratie_id, beheerder_id, vendor_id, document_zonder_project, projecten, monkeypatch
    ) -> None:
        service.zet_leverancier_pro_rato(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=beheerder_id, ingeschakeld=True
        )
        # Periode-default = vorige maand t.o.v. vandaag → pin 'vandaag' op augustus 2026 zodat juli de maand is.
        monkeypatch.setattr(service, "date", _VasteDatum)
        voorstel = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        )
        data = voorstel.projectverdeling
        assert data is not None and data.prefill and not data.opgeslagen
        assert data.pro_rato and data.pro_rato_periode == PERIODE
        assert data.vaste_regels == []
        assert data.pro_rato_bedrag == Decimal("2000.00") and data.compleet
        assert sum(d.bedrag for d in data.delen) == Decimal("2000.00")
        assert data.aantal_projecten_met_omzet == 3
        assert {d.project_naam for d in data.delen} == {
            "26120 Eindhoven (BAM)",
            "26127 Tilburg (Heijmans)",
            "26131 Venlo (Dura)",
        }

    def test_opslaan_vast_plus_restant_en_te_veel_vast(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten
    ) -> None:
        data = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[
                pv.VasteRegel(
                    project_id=projecten["tilburg"], bedrag=Decimal("600.00"), hint="rechtstreeks steigerbouwen"
                )
            ],
            pro_rato_periode=PERIODE,
        )
        assert data is not None and data.opgeslagen and data.compleet
        assert data.pro_rato_bedrag == Decimal("1400.00")
        tilburg = [d for d in data.delen if d.project_id == projecten["tilburg"]]
        assert {d.wijze for d in tilburg} == {"vast", "pro_rato"}
        assert sum(d.bedrag for d in tilburg) == Decimal("950.00")
        assert service.check(data).ok

        te_veel = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("2500.00"))],
            pro_rato_periode=PERIODE,
        )
        assert te_veel is not None and not te_veel.compleet
        check = service.check(te_veel)
        assert not check.ok and "meer vast verdeeld" in check.melding

    def test_check_blokkeert_boeken_zolang_verdeling_niet_sluit(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, document_zonder_project, projecten, monkeypatch
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("600.00"))],
            pro_rato_periode=None,  # pro rato uit → € 1.400 onverdeeld
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks) as exc:
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
            )
        namen = {r.naam: r for r in exc.value.rapport.resultaten}
        assert not namen["Projectverdeling"].ok
        assert "nog niet verdeeld" in namen["Projectverdeling"].melding

    def test_projectplicht_telt_complete_verdeling_als_project(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, document_zonder_project, projecten, admin_engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET project_verplicht = true WHERE id = :id"),
                {"id": administratie_id},
            )
        rapport_zonder = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_zonder_project, client=FakeBoekClient()
        )
        verplicht = next(r for r in rapport_zonder.resultaten if r.naam == "Verplichte velden")
        assert not verplicht.ok and "project (regel 1)" in verplicht.melding

        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        rapport_met = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_zonder_project, client=FakeBoekClient()
        )
        per_naam = {r.naam: r for r in rapport_met.resultaten}
        assert per_naam["Verplichte velden"].ok
        assert per_naam["Projectverdeling"].ok

    def test_vervallen_stopt_de_prefill(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, vendor_id, document_zonder_project, projecten
    ) -> None:
        service.zet_leverancier_pro_rato(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=beheerder_id, ingeschakeld=True
        )
        data = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=None,
            vervallen=True,
        )
        assert data is not None and data.status == pv.STATUS_VERVALLEN and not data.actief
        assert service.check(data).ok


class _VasteDatum(date):
    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return date(2026, 8, 12)


@pytest.fixture
def geboekt_met_verdeling(
    administratie_id, beheerder_id, gescoopte_gebruiker, document_zonder_project, projecten, monkeypatch
) -> tuple[uuid.UUID, FakeBoekClient]:
    """Floorbeheer geboekt via de gewone motor: € 600 vast Tilburg + € 1.400 pro rato juli; fake-client mét
    ingediende Q3-aangifte (storno geblokkeerd → tegenboeken is straks de route)."""
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    service.sla_op(
        administratie_id=administratie_id,
        document_id=document_zonder_project,
        actor_id=gescoopte_gebruiker,
        vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("600.00"))],
        pro_rato_periode=PERIODE,
    )
    fake = FakeBoekClient(aangiften=[AANGIFTE_Q3_INGEDIEND])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    boeken.boek_document(
        administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
    )
    return document_zonder_project, fake


class TestBoekenMetVerdeling:
    def test_rlz_regels_gesplitst_per_project_en_btw_sluitend(
        self, geboekt_met_verdeling, projecten, admin_engine
    ) -> None:
        document_id, fake = geboekt_met_verdeling
        [put] = fake.puts
        lines = put["lines"]
        assert len(lines) == 3  # Eindhoven / Tilburg (600 vast + 350 pro rato) / Venlo
        per_project = {line["Project"]["id"]: line for line in lines}
        assert set(per_project) == {str(projecten["eindhoven"]), str(projecten["tilburg"]), str(projecten["venlo"])}
        assert round(sum(line["NetAmount"] for line in lines), 2) == 2000.00
        assert round(sum(line["TaxAmount"] for line in lines), 2) == 420.00
        assert per_project[str(projecten["tilburg"])]["NetAmount"] == 950.00
        assert per_project[str(projecten["eindhoven"])]["NetAmount"] == 840.00
        assert all(line["Description"] == "Vloeronderhoud kantoor" for line in lines)
        assert _status(admin_engine, document_id) == "geboekt"

    def test_omzetstanden_bevroren_bij_boeken(self, geboekt_met_verdeling, projecten, admin_engine) -> None:
        document_id, _ = geboekt_met_verdeling
        rij = _rij(admin_engine, document_id)
        assert rij["status"] == "geboekt" and rij["boek_cyclus"] == 0
        assert rij["pro_rato_bedrag"] == Decimal("1400.00")
        assert {s["project_id"]: s["omzet"] for s in rij["omzetstanden"]} == {
            str(projecten["eindhoven"]): "6000.00",
            str(projecten["tilburg"]): "2500.00",
            str(projecten["venlo"]): "1500.00",
        }
        assert sum(Decimal(d["bedrag"]) for d in rij["verdeling"]) == Decimal("2000.00")
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE record_id = :id AND tabel = 'projectverdeling' "
                        "ORDER BY tijdstip"
                    ),
                    {"id": document_id},
                )
                .scalars()
                .all()
            )
        assert "projectverdeling_bevroren" in acties

    def test_geboekt_voorstel_leest_bevroren_stand_ook_als_omzet_wijzigt(
        self, geboekt_met_verdeling, administratie_id, projecten, admin_engine
    ) -> None:
        document_id, _ = geboekt_met_verdeling
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2026, 7, 20))
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        data = voorstel.projectverdeling
        assert data is not None and data.status == "geboekt"
        venlo = [d for d in data.delen if d.project_id == projecten["venlo"]]
        assert venlo[0].bedrag == Decimal("210.00")  # bevroren, niet herrekend

    def test_tegenboek_lines_spiegelen_de_splitsing(self, geboekt_met_verdeling, administratie_id, projecten) -> None:
        document_id, _ = geboekt_met_verdeling
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        from app.backends.rlz_inkoop import tegenboek_lines

        lines = tegenboek_lines(voorstel, "TEGENBOEKING FB-2026-0731")
        assert len(lines) == 3
        assert round(sum(line["NetAmount"] for line in lines), 2) == -2000.00
        assert round(sum(line["TaxAmount"] for line in lines), 2) == -420.00
        assert {line["Project"]["id"] for line in lines} == {
            str(p) for p in (projecten["eindhoven"], projecten["tilburg"], projecten["venlo"])
        }


class TestHercontrole:
    def test_onder_drempel_geen_signaal_boven_drempel_wel_en_idempotent(
        self, geboekt_met_verdeling, administratie_id, projecten, admin_engine
    ) -> None:
        document_id, _ = geboekt_met_verdeling
        # Ongewijzigde omzet → 0 % afwijking, geen signaal.
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2))
        assert tellers == {"beoordeeld": 1, "herrekend": 1, "signalen": 0, "overgeslagen": 0}
        rij = _rij(admin_engine, document_id)
        assert rij["hercontrole_afwijking_pct"] == Decimal("0.00") and rij["hercontrole_verdeling"] is None

        # Nagekomen factuur Venlo (+ € 1.000): Venlo 210 → 318,18 = 7,73 % > 5 % drempel.
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2026, 7, 20))
        tellers = hercontrole.herbereken_administratie(
            administratie_id=administratie_id, vandaag=date(2026, 9, 2), forceer=True
        )
        assert tellers["signalen"] == 1
        rij = _rij(admin_engine, document_id)
        assert rij["hercontrole_afwijking_pct"] == Decimal("7.73")
        assert sum(Decimal(d["bedrag"]) for d in rij["hercontrole_verdeling"]) == Decimal("2000.00")

        def tijdlijn_signalen() -> int:
            with admin_engine.connect() as conn:
                return conn.execute(
                    text(
                        "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                        "AND detail ? 'projectverdeling_afwijking'"
                    ),
                    {"id": document_id},
                ).scalar_one()

        assert tijdlijn_signalen() == 1
        # Nogmaals (geforceerd) mét dezelfde uitkomst → geen tweede tijdlijnregel.
        hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2), forceer=True)
        assert tijdlijn_signalen() == 1
        # Buiten de cadans (20e, geen verse sync) → overgeslagen.
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 20))
        assert tellers["overgeslagen"] == 1 and tellers["herrekend"] == 0

        # Lijst-chipdata + kantoorbrede lijst.
        with scoped_session(administratie_id) as session:
            assert service.afwijkingen_per_document(session, [document_id]) == {document_id: Decimal("7.73")}
        from app.db.models import GebruikerRol

        with admin_engine.connect() as conn:
            beheerder = conn.execute(
                text("SELECT id FROM platform.gebruiker WHERE rol = 'beheerder' LIMIT 1")
            ).scalar_one()
        lijst = service.hercontrole_signalen(actor_id=beheerder, rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 1 and lijst.rijen[0].afwijking_pct == Decimal("7.73")
        assert lijst.rijen[0].referentie == "FB-2026-0731"

    def test_drempel_instelling_beheerder(
        self, geboekt_met_verdeling, administratie_id, beheerder_id, projecten, admin_engine
    ) -> None:
        document_id, _ = geboekt_met_verdeling
        service.zet_instellingen(
            administratie_id=administratie_id, actor_id=beheerder_id, drempel_pct=Decimal("10.00"), wachtweken=6
        )
        stand = service.haal_instellingen(administratie_id=administratie_id)
        assert (stand.drempel_pct, stand.wachtweken) == (Decimal("10.00"), 6)
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2026, 7, 20))
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2))
        assert tellers["signalen"] == 0  # 7,73 % < 10 %
        with pytest.raises(service.ProjectverdelingServiceFout):
            service.zet_instellingen(
                administratie_id=administratie_id, actor_id=beheerder_id, drempel_pct=Decimal("150"), wachtweken=None
            )


class TestHerverdelen:
    def _signaleer(self, administratie_id, projecten, admin_engine) -> None:
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2026, 7, 20))
        hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2), forceer=True)

    def test_herverdelen_is_tegenboeken_en_opnieuw_boeken_met_nieuwe_verdeling(
        self, geboekt_met_verdeling, administratie_id, gescoopte_gebruiker, projecten, admin_engine
    ) -> None:
        document_id, fake = geboekt_met_verdeling
        self._signaleer(administratie_id, projecten, admin_engine)

        resultaat = service.herverdelen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden="omzet juli gewijzigd — nagekomen factuur Venlo",
        )
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert _status(admin_engine, document_id) == "te_controleren"
        # Tegenboeking in RLZ: gespiegelde, gesplitste regels.
        tegenboeking = fake.puts[-1]
        assert round(sum(line["NetAmount"] for line in tegenboeking["lines"]), 2) == -2000.00
        assert len(tegenboeking["lines"]) == 3
        # Verdeling staat weer als VOORSTEL klaar, live herrekend op de nieuwe omzetstand.
        rij = _rij(admin_engine, document_id)
        assert rij["status"] == "voorstel" and rij["hercontrole_verdeling"] is None
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        data = voorstel.projectverdeling
        assert data is not None and data.status == "voorstel" and data.compleet and data.boek_cyclus == 1
        venlo = [d for d in data.delen if d.project_id == projecten["venlo"]]
        assert venlo[0].bedrag == Decimal("318.18")
        assert [r.bedrag for r in data.vaste_regels] == [Decimal("600.00")]

    def test_herverdelen_zonder_signaal_is_422_en_zonder_aangifteblokkade_409(
        self, geboekt_met_verdeling, administratie_id, gescoopte_gebruiker, projecten, admin_engine
    ) -> None:
        document_id, fake = geboekt_met_verdeling
        with pytest.raises(service.ProjectverdelingServiceFout, match="geen hercontrole-afwijking"):
            service.herverdelen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="test reden",
            )
        self._signaleer(administratie_id, projecten, admin_engine)
        fake.aangiften = []  # periode open → storno vrij → tegenboeken is niet de route
        with pytest.raises(service.HerverdelenGeblokkeerd, match="stornering"):
            service.herverdelen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="test reden",
            )
        assert _status(admin_engine, document_id) == "geboekt"
        assert _rij(admin_engine, document_id)["status"] == "geboekt"


class TestLeverancierOptIn:
    def test_lijst_en_zetten_met_audit(self, administratie_id, beheerder_id, admin_engine) -> None:
        vendor = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                    "VALUES (:id, :aid, 'Floorbeheer B.V.', '{}')"
                ),
                {"id": vendor, "aid": administratie_id},
            )
        assert (
            service.lijst_leverancier_pro_rato(administratie_id=administratie_id)[0].projectverdeling_pro_rato is False
        )
        assert service.zet_leverancier_pro_rato(
            administratie_id=administratie_id, vendor_id=vendor, actor_id=beheerder_id, ingeschakeld=True
        )
        [rij] = service.lijst_leverancier_pro_rato(administratie_id=administratie_id)
        assert rij.projectverdeling_pro_rato and rij.naam == "Floorbeheer B.V."
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(text("SELECT actie FROM platform.audit_event WHERE record_id = :id"), {"id": vendor})
                .scalars()
                .all()
            )
        assert "leverancier_projectverdeling_pro_rato_gewijzigd" in acties


def _checks(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict[str, object]:
    rapport = boekvoorstel.voer_checks_uit(
        administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
    )
    return {r.naam: r for r in rapport.resultaten}


class TestB3DekkingOpgeslagenVerdeling:
    """Bugfix 04-09 (casus Kader Consultancy F212604921, Universal Steigerbouw): de checks toetsen de OPGESLAGEN
    verdeling van het document — niet de leverancier-opt-in. Zelfde functie (voer_checks_uit) voedt het
    controlescherm én de boekmotor-poort, dus melding en boekweigering kunnen nooit verschillen."""

    @pytest.fixture(autouse=True)
    def _projectplicht(self, administratie_id, admin_engine) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET project_verplicht = true WHERE id = :id"),
                {"id": administratie_id},
            )

    def test_a_een_regel_zonder_kolomproject_met_geldige_verdeling_boekt(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, document_zonder_project, projecten, admin_engine, monkeypatch
    ) -> None:
        # Vóór de verdeling: blokkade mét handelingsperspectief; "Projectverdeling" zegt niet vals "niet van toepassing".
        voor = _checks(administratie_id, document_zonder_project)
        assert not voor["Verplichte velden"].ok and "project (regel 1)" in voor["Verplichte velden"].melding
        assert voor["Projectverdeling"].ok and voor["Projectverdeling"].signaal
        assert "1 regel zonder project" in voor["Projectverdeling"].melding
        assert "Verdelen over projecten…" in voor["Projectverdeling"].melding

        # Geen leverancier-opt-in — de mens slaat een pro-rato-verdeling op (juli: 3 projecten mét omzet).
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        na = _checks(administratie_id, document_zonder_project)
        assert na["Verplichte velden"].ok, na["Verplichte velden"].melding
        assert na["Projectverdeling"].ok and not na["Projectverdeling"].signaal
        assert na["Projectverdeling"].melding == "Verdeeld: € 2000,00 over 3 projecten, pro rato omzet juli 2026"

        # Boekmotor-poort: dezelfde dekking — boeken kan.
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
        )
        assert _status(admin_engine, document_zonder_project) == DocumentStatus.GEBOEKT.value
        assert len(fake.puts) == 1 and len(fake.puts[0]["lines"]) == 3  # regel gesplitst per project

    def test_b_verdeling_weggehaald_geeft_de_blokkade_terug(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, document_zonder_project, projecten, monkeypatch
    ) -> None:
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        assert _checks(administratie_id, document_zonder_project)["Verplichte velden"].ok
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=None,
            vervallen=True,
        )
        terug = _checks(administratie_id, document_zonder_project)
        assert not terug["Verplichte velden"].ok
        assert "project (regel 1)" in terug["Verplichte velden"].melding
        assert 'gebruik "Verdelen over projecten…"' in terug["Verplichte velden"].melding
        assert terug["Projectverdeling"].signaal and "Geen projectverdeling — 1 regel zonder project" in terug["Projectverdeling"].melding
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks) as exc:
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
            )
        assert not {r.naam: r for r in exc.value.rapport.resultaten}["Verplichte velden"].ok

    def test_b2_onvolledige_verdeling_dekt_niets(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten
    ) -> None:
        """€ 600 vast, pro rato uit → € 1.400 onverdeeld: beide checks benoemen het (spec: onvolledig = blokkade blijft)."""
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("600.00"))],
            pro_rato_periode=None,
        )
        per_naam = _checks(administratie_id, document_zonder_project)
        assert not per_naam["Verplichte velden"].ok and "project (regel 1)" in per_naam["Verplichte velden"].melding
        assert not per_naam["Projectverdeling"].ok and "nog niet verdeeld" in per_naam["Projectverdeling"].melding

    def test_c_mengvorm_kolomproject_op_regel_1_verdeling_voor_regel_2(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten, vendor_id
    ) -> None:
        from tests.projectverdeling.conftest import regel

        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="FB-2026-0731",
            factuurdatum=date(2026, 7, 31),
            totaalbedrag=Decimal("2420.00"),
            regels=[
                regel(project_id=projecten["tilburg"], netto_bedrag=Decimal("500.00"), btw_bedrag=Decimal("105.00")),
                regel(netto_bedrag=Decimal("1500.00"), btw_bedrag=Decimal("315.00")),
            ],
        )
        voor = _checks(administratie_id, document_zonder_project)
        assert "project (regel 2)" in voor["Verplichte velden"].melding
        assert "project (regel 1)" not in voor["Verplichte velden"].melding
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode=PERIODE,
        )
        na = _checks(administratie_id, document_zonder_project)
        assert na["Verplichte velden"].ok
        # Alleen regel 2 (€ 1.500) is het te verdelen bedrag; regel 1 houdt zijn kolom-project.
        assert na["Projectverdeling"].melding == "Verdeeld: € 1500,00 over 3 projecten, pro rato omzet juli 2026"

    def test_d_opt_in_en_niet_opt_in_leverancier_gedragen_zich_identiek(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, document_zonder_project, projecten, vendor_id
    ) -> None:
        service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("600.00"))],
            pro_rato_periode=PERIODE,
        )
        zonder = _checks(administratie_id, document_zonder_project)
        service.zet_leverancier_pro_rato(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=beheerder_id, ingeschakeld=True
        )
        met = _checks(administratie_id, document_zonder_project)
        for naam in ("Verplichte velden", "Projectverdeling"):
            assert (zonder[naam].ok, zonder[naam].signaal, zonder[naam].melding) == (
                met[naam].ok,
                met[naam].signaal,
                met[naam].melding,
            )
        assert met["Verplichte velden"].ok
        assert met["Projectverdeling"].melding == "Verdeeld: € 2000,00 over 3 projecten, vast + pro rato omzet juli 2026"

    def test_zonder_projectplicht_blijft_geen_verdeling_niet_van_toepassing(
        self, administratie_id, document_zonder_project, projecten, admin_engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET project_verplicht = false WHERE id = :id"),
                {"id": administratie_id},
            )
        per_naam = _checks(administratie_id, document_zonder_project)
        assert per_naam["Verplichte velden"].ok
        assert per_naam["Projectverdeling"].ok and not per_naam["Projectverdeling"].signaal
        assert per_naam["Projectverdeling"].melding == "Geen projectverdeling van toepassing"
