"""Transport (D1), materiaalstand + huurperiode (D4), wachtrisico (D5), m²-toetsbron bij de
keuring en materiaalmatch (D6) — deterministische geldlogica + statusseam + audit."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.materiaal import match as materiaalmatch
from app.materiaal import service as materiaal
from app.materiaal.models import MateriaalProduct
from app.uren import planning, service as uren_service
from tests.materiaal.conftest import product_id_op_naam
from tests.uren.conftest import maak_gebruiker

JAAR, WEEK = 2026, 35
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _audit(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [r[0] for r in conn.execute(text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip, id"), {"id": record_id})]


def _buis(administratie_id, leverancier_id, beheerder_id, lengte: str) -> str:
    return str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, f"Steigerbuis tubelock {lengte} mtr"))


def plan(administratie_id, beheerder_id, project_id, leverancier_id, *, soort, datum, regels, status=None):
    """Statusflow 31-08: naar 'geleverd' loopt via gereserveerd → bevestigd (voertuig) →
    definitief → geleverd (de seam dwingt de keten af)."""
    t = materiaal.plan_transport(administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id, leverancier_id=leverancier_id, soort=soort, datum=datum, tijdstip=None, regels=regels, omschrijving=None)
    if status:
        keten = {"bevestigd": ["bevestigd"], "definitief": ["bevestigd", "definitief"], "geleverd": ["bevestigd", "definitief", "geleverd"], "geannuleerd": ["geannuleerd"]}[status]
        for stap in keten:
            t = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status=stap, voertuig="combi" if stap == "bevestigd" else None, reden="test" if stap == "geannuleerd" else None)
    return t


class TestTransport:
    def test_statusseam_overgangen_en_audit(self, administratie_id, project_id, leverancier_id, beheerder_id, admin_engine):
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        t = plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG, regels={b4: 115})
        assert t.status == "gereserveerd" and t.m2 == Decimal("100.00") and t.samenvatting == "Levering steiger 100.00 m²"
        # Bevestigen vereist de voertuigtoezegging (31-08).
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="bevestigd")
        t = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="bevestigd", voertuig="voorwagen")
        assert t.status == "bevestigd" and t.voertuig == "voorwagen"
        # Geleverd kan pas ná definitief (materiaallijst-stap zit ertussen).
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="geleverd")
        t = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="definitief")
        t = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="geleverd")
        assert t.status == "geleverd" and t.status_bron == "kantoor"
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="gereserveerd")
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.wijzig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, tijdstip=None, omschrijving="x")
        # De legacywaarde 'gepland' is geen geldige doelstatus meer.
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="gepland")
        t2 = plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="retour", datum=MAANDAG + timedelta(days=7), regels={b4: 15})
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t2.id, nieuwe_status="geannuleerd")
        t2 = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t2.id, nieuwe_status="geannuleerd", reden="retour vervalt")
        assert t2.status == "geannuleerd" and t2.status_reden == "retour vervalt"
        acties = _audit(admin_engine, t.id)
        assert acties == ["transport_gereserveerd", "transport_status_gewijzigd", "transport_status_gewijzigd", "transport_status_gewijzigd"]
        with pytest.raises(uren_service.OngeldigeInvoer):
            plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG, regels={str(uuid.uuid4()): 1})

    def test_materiaalstand_huurperiode_en_m2(self, administratie_id, project_id, leverancier_id, beheerder_id):
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        b2 = _buis(administratie_id, leverancier_id, beheerder_id, "2")
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG, regels={b4: 100, b2: 50}, status="geleverd")
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG + timedelta(days=7), regels={b4: 50}, status="geleverd")
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="retour", datum=MAANDAG + timedelta(days=14), regels={b2: 50}, status="geleverd")
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG + timedelta(days=21), regels={b4: 999})  # gereserveerd: telt niet
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            stand = materiaal.materiaalstand_in_sessie(session, administratie_id=administratie_id, project_id=project_id, tot_en_met=MAANDAG + timedelta(days=27))
        per = {r.naam: r for r in stand.regels}
        b4r, b2r = per["Steigerbuis tubelock 4 mtr"], per["Steigerbuis tubelock 2 mtr"]
        assert (b4r.geleverd, b4r.retour, b4r.op_locatie) == (150, 0, 150) and b4r.laatste_retour is None and b4r.eerste_levering == MAANDAG
        assert b4r.huurdagen_tot_vandaag == 28  # loopt nog: dag 0 t/m dag 27
        # item-weken: 100 × 7 d + 150 × 21 d = 3850 item-dagen / 7 = 550
        assert b4r.huur_eenheden == Decimal("550.00")
        assert (b2r.geleverd, b2r.retour, b2r.op_locatie) == (50, 50, 0) and b2r.laatste_retour == MAANDAG + timedelta(days=14)
        assert b2r.huurdagen_tot_vandaag == 14 and b2r.huur_eenheden == Decimal("100.00")  # 50 × 14 / 7
        # m² op locatie: 150 × 4 / 4,6 = 130,43
        assert stand.m2_op_locatie == Decimal("130.43") and stand.leveranciers == ["Universal Nederland B.V."]

    def test_wachtrisico_kruissignaal_beide_tabs(self, administratie_id, project_id, tweede_project_id, leverancier_id, gekoppelde_zzper, beheerder_id):
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        di = MAANDAG + timedelta(days=1)
        # Project A: ploeg gepland op di, levering di nog 'gereserveerd' → rood. Project B: levering geleverd → geen signaal.
        planning.plan_toewijzing(administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id, datum=di, dagdeel="heel", actor_id=beheerder_id)
        planning.plan_toewijzing(administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=tweede_project_id, datum=MAANDAG, dagdeel="heel", actor_id=beheerder_id)
        t = plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=di, regels={b4: 100})
        plan(administratie_id, beheerder_id, tweede_project_id, leverancier_id, soort="levering", datum=MAANDAG, regels={b4: 10}, status="geleverd")
        week = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        assert [(m.project_id, m.datum, m.aantal_personen, m.transport_id) for m in week.wachtrisico] == [(project_id, di, 1, t.id)]
        rij = next(r for r in week.projecten if r.project_id == project_id)
        assert rij.ploeg_label == "ploeg di (1 man)" and rij.week_transporten == 1
        # Personeel-tab (planning-overzicht) draagt hetzelfde signaal.
        pw = planning.planning_overzicht(administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id)
        assert len(pw.wachtrisico) == 1 and pw.wachtrisico[0].project_id == project_id
        # Een BEVESTIGDE levering neemt het risico weg (D5: "zonder bevestigde levering"); terug
        # naar gereserveerd = weer rood; geleverd (via definitief) = definitief weg.
        materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="bevestigd", voertuig="combi")
        assert materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK).wachtrisico == []
        materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="gereserveerd")
        assert len(materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK).wachtrisico) == 1
        materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="bevestigd", voertuig="combi")
        materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="definitief")
        materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="geleverd")
        assert materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK).wachtrisico == []

    def test_m2_toetsbron_bij_keuring(self, administratie_id, project_id, leverancier_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id):
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        zzper = gekoppelde_zzper
        # Zonder leveringen: geen signaal (niets om tegen te toetsen).
        staat = uren_service.zet_dag(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK, datum=MAANDAG, uren=Decimal("8"), m2=Decimal("120"), actor_id=zzper)
        assert staat.m2_geleverd_project is None and staat.meer_gebouwd_dan_geleverd is False
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=MAANDAG, regels={b4: 115}, status="geleverd")  # 100 m²
        staat = uren_service.weekstaat_detail(administratie_id=administratie_id, weekstaat_id=staat.id)
        assert staat.m2_geleverd_project == Decimal("100.00") and staat.m2_gebouwd_project == Decimal("120") and staat.meer_gebouwd_dan_geleverd is True
        uren_service.zet_dag(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK, datum=MAANDAG, uren=Decimal("8"), m2=Decimal("90"), actor_id=zzper)
        staat = uren_service.weekstaat_detail(administratie_id=administratie_id, weekstaat_id=staat.id)
        assert staat.meer_gebouwd_dan_geleverd is False


class TestMateriaalmatch:
    def test_koppel_product_langste_match(self):
        producten = [MateriaalProduct(id=uuid.uuid4(), naam=n) for n in ("Steigerbuis tubelock 2 mtr", "Steigerbuis tubelock 2,8 mtr", "Kruiskoppeling")]
        assert materiaalmatch.koppel_product("Huur steigerbuis tubelock 2,8 m 50 st wk 35-38", producten).naam == "Steigerbuis tubelock 2,8 mtr"
        assert materiaalmatch.koppel_product("kruiskoppeling", producten).naam == "Kruiskoppeling"
        assert materiaalmatch.koppel_product("Transportkosten", producten) is None

    def test_match_afwijking_en_poort(self, administratie_id, project_id, leverancier_id, beheerder_id, admin_engine, monkeypatch, tmp_path):
        from app.documenten import boekvoorstel as bv_module
        from app.documenten.boekvoorstel import BoekvoorstelRegelData, sla_boekvoorstel_op
        from app.documenten import service as documenten_service
        from app.documenten.models import DocumentSoort
        from app.documenten.storage import LokaleBestandsopslag

        vendor = uuid.uuid4()
        materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=leverancier_id, naam="Universal Nederland B.V.", bestel_email="reijer@universalbv.nl", telefoon=None, adres=None, vendor_id=vendor)
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        plan(administratie_id, beheerder_id, project_id, leverancier_id, soort="levering", datum=date(2026, 8, 3), regels={b4: 100}, status="geleverd")
        # factuur 28-08: 100 stuks op locatie, 26 dagen → 100 × 26 / 7 = 371,43 item-weken
        veldvoorstel = {"regels": [{"omschrijving": "Huur steigerbuis tubelock 4 mtr", "hoeveelheid": "100"}, {"omschrijving": "Transportkosten", "hoeveelheid": "1"}]}
        monkeypatch.setattr(bv_module, "_laatste_veldvoorstel", lambda session, document_id: veldvoorstel)
        opslag = LokaleBestandsopslag(tmp_path / "doc")
        res = documenten_service.upload_document(administratie_id=administratie_id, bestandsnaam="huur.pdf", inhoud=b"%PDF-1.4 huur", actor_id=beheerder_id, opslag=opslag, soort=DocumentSoort.INKOOPFACTUUR)
        sla_boekvoorstel_op(
            administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, vendor_id=vendor, referentie="2026-2201", factuurdatum=date(2026, 8, 28),
            totaalbedrag=Decimal("500"), regels=[BoekvoorstelRegelData(ledger_id=None, taxrate_id=None, project_id=project_id, netto_bedrag=Decimal("500"), btw_bedrag=Decimal("0"), omschrijving=None)],
        )
        # Expliciete run (de post-commit-hook in sla_boekvoorstel_op draait 'm ook; fouten daar zijn gelogd, niet blokkerend).
        m = materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=res.document_id)
        assert m is not None and m.uitkomst == "match" and m.aantal_regels_getoetst == 1 and m.aantal_regels_onbekend == 1
        assert materiaalmatch.lees_materiaalmatch(administratie_id=administratie_id, document_id=res.document_id).uitkomst == "match"
        assert m.details["regels"][0]["status"] == "match_aantal" and m.details["regels"][0]["verwacht_huur_eenheden"] == "371.43"
        # Factuur claimt 1.200 m²-equivalent buizen (mockup: 1.200 vs 1.000) → afwijking
        veldvoorstel["regels"][0]["hoeveelheid"] = "120"
        m = materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=res.document_id)
        assert m.uitkomst == "afwijking" and m.aantal_regels_afwijkend == 1
        with pytest.raises(materiaalmatch.MateriaalAfwijkingBevestigingVereist) as exc:
            materiaalmatch.toets_materiaalmatch_poort(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, bevestigd=False)
        assert exc.value.match_info["aantal_regels_afwijkend"] == 1
        materiaalmatch.toets_materiaalmatch_poort(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, bevestigd=True)
        materiaalmatch.toets_materiaalmatch_poort(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, bevestigd=False)  # persistent
        assert "materiaalmatch_afwijking_bevestigd" in _audit(admin_engine, res.document_id)
        # Herberekening wist de bevestiging (nieuwe cijfers = nieuwe beslissing).
        materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=res.document_id)
        with pytest.raises(materiaalmatch.MateriaalAfwijkingBevestigingVereist):
            materiaalmatch.toets_materiaalmatch_poort(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, bevestigd=False)
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert materiaalmatch.open_materiaalmatches_in_sessie(session, administratie_id=administratie_id) == 1

    def test_niet_toetsbaar_zonder_project_of_leveringen(self, administratie_id, leverancier_id, beheerder_id, monkeypatch, tmp_path):
        from app.documenten import boekvoorstel as bv_module
        from app.documenten.boekvoorstel import BoekvoorstelRegelData, sla_boekvoorstel_op
        from app.documenten import service as documenten_service
        from app.documenten.models import DocumentSoort
        from app.documenten.storage import LokaleBestandsopslag

        vendor = uuid.uuid4()
        materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=leverancier_id, naam="Universal Nederland B.V.", bestel_email=None, telefoon=None, adres=None, vendor_id=vendor)
        monkeypatch.setattr(bv_module, "_laatste_veldvoorstel", lambda session, document_id: {"regels": [{"omschrijving": "Kruiskoppeling", "hoeveelheid": "10"}]})
        res = documenten_service.upload_document(administratie_id=administratie_id, bestandsnaam="x.pdf", inhoud=b"%PDF-1.4 x", actor_id=beheerder_id, opslag=LokaleBestandsopslag(tmp_path / "d"), soort=DocumentSoort.INKOOPFACTUUR)
        sla_boekvoorstel_op(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, vendor_id=vendor, referentie="X-1", factuurdatum=date(2026, 8, 28), totaalbedrag=Decimal("10"), regels=[BoekvoorstelRegelData(ledger_id=None, taxrate_id=None, project_id=None, netto_bedrag=Decimal("10"), btw_bedrag=Decimal("0"), omschrijving=None)])
        # De post-commit-hook in sla_boekvoorstel_op heeft de match al berekend (pipeline-trigger).
        m = materiaalmatch.lees_materiaalmatch(administratie_id=administratie_id, document_id=res.document_id)
        assert m is not None, "hook ná voorstel-opslag heeft geen materiaalmatch achtergelaten"
        assert m.uitkomst == "niet_toetsbaar" and "geen geleverde transporten" in m.details["reden"]
        materiaalmatch.toets_materiaalmatch_poort(administratie_id=administratie_id, document_id=res.document_id, actor_id=beheerder_id, bevestigd=False)  # geen blokkade
