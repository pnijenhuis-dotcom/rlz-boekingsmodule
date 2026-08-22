"""Kantoor-projectenmodule (mockup projecten-invoer.html, akkoord Peter 22-08): de
rekenlaag resultaat-per-project (weekverdeling, werkweek-herleiding, onderweg-verrijking
zonder gokken, detail==overzicht), de lijst-badges, de schrijfpaden mét de
schrijfrol-poort (Beheerder/Boekhouding+Projecten), nieuw-project via de bestaande
motor-bouwstenen en de contract-ontleding (voorstel → bevestigen per regel)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.extractie.contract import ContractRegel
from app.projecten import cijfers, kantoor, ontleding
from tests.projecten.conftest import FakeProjectClient
from tests.uren.conftest import maak_gebruiker, maak_project

VANDAAG = date(2026, 8, 22)  # week 34


def _insert_regel(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    soort: str,
    netto: str,
    datum: str,
    rlz_document_id: uuid.UUID | None = None,
    referentie: str | None = None,
    verdwenen: bool = False,
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_regel_cache "
                "(id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag, datum, referentie, "
                " verdwenen_uit_bron_op) "
                "VALUES (:id, :aid, :doc, :soort, :pid, :netto, :datum, :ref, "
                " CASE WHEN :verdwenen THEN now() ELSE NULL END)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": administratie_id,
                "doc": rlz_document_id or uuid.uuid4(),
                "soort": soort,
                "pid": project_id,
                "netto": netto,
                "datum": datum,
                "ref": referentie,
                "verdwenen": verdwenen,
            },
        )


def _insert_weekstaat(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    week: int,
    uren_per_dag: list[tuple[str, str]],
    status: str = "goedgekeurd",
    verrekend_met: uuid.UUID | None = None,
) -> uuid.UUID:
    staat_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.weekstaat "
                "(id, administratie_id, gebruiker_id, project_id, jaar, weeknummer, status, "
                " goedgekeurd_op, goedgekeurd_door, verrekend_met_document_id, verrekend_op) "
                "VALUES (:id, :aid, :gid, :pid, :jaar, :week, :status, now(), :gid, CAST(:vdoc AS uuid), "
                " CASE WHEN CAST(:vdoc AS uuid) IS NULL THEN NULL ELSE now() END)"
            ),
            {"id": staat_id, "aid": administratie_id, "gid": gebruiker_id, "pid": project_id,
             "jaar": jaar, "week": week, "status": status, "vdoc": verrekend_met},
        )
        for datum, uren in uren_per_dag:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.weekstaat_dag "
                    "(id, weekstaat_id, administratie_id, datum, uren, ingevuld_door) "
                    "VALUES (:id, :sid, :aid, :datum, :uren, :gid)"
                ),
                {"id": uuid.uuid4(), "sid": staat_id, "aid": administratie_id, "datum": datum,
                 "uren": uren, "gid": gebruiker_id},
            )
    return staat_id


class TestRekenlaag:
    def test_tegels_weekverdeling_en_onderweg(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26014 Breda (Moeskops)")
        zzper = maak_gebruiker(admin_engine, "zzper", "Milan K.")
        # Baten: verkoopfactuur in week 31 (ma 27-07-2026); kosten: inkoop in week 32.
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="verkoop", netto="42800.00", datum="2026-07-27", referentie="termijn 2")
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="inkoop", netto="12980.00", datum="2026-08-05")
        # Verdwenen regel telt nooit mee (storno in RLZ).
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="inkoop", netto="9999.00", datum="2026-08-05", verdwenen=True)
        # Onderweg: goedgekeurde ONverrekende staat in week 34 (8 uur) mét tarief € 45.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.veldwerker_crediteur "
                    "(administratie_id, gebruiker_id, vendor_id, uurtarief, autoboeken_ingeschakeld, gekoppeld_door) "
                    "VALUES (:aid, :gid, :vendor, 45.00, false, :door)"
                ),
                {"aid": administratie_id, "gid": zzper, "vendor": uuid.uuid4(), "door": beheerder_id},
            )
        _insert_weekstaat(admin_engine, administratie_id=administratie_id, gebruiker_id=zzper,
                          project_id=project_id, jaar=2026, week=34, uren_per_dag=[("2026-08-17", "8.00")])
        # Baten onderweg: goedgekeurd meerwerk € 2.620 (nog niet doorbelast).
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.meerwerk (id, administratie_id, project_id, omschrijving, aantal, "
                    " eenheid, datum_uitgevoerd, gemeld_door, status, prijs_per_eenheid, bedrag, beoordeeld_door, "
                    " beoordeeld_op) "
                    "VALUES (:id, :aid, :pid, 'trapsteiger', 100, 'm2', '2026-08-10', :gid, 'goedgekeurd', "
                    " 26.20, 2620.00, :door, now())"
                ),
                {"id": uuid.uuid4(), "aid": administratie_id, "pid": project_id, "gid": zzper, "door": beheerder_id},
            )

        with scoped_session(administratie_id) as session:
            data = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)

        assert data.baten_geboekt == Decimal("42800.00")
        assert data.kosten_geboekt == Decimal("12980.00")
        assert data.uren_onderweg_bedrag == Decimal("360.00")  # 8 × 45
        assert data.onbepaalbaar_uren == Decimal("0")
        assert data.meerwerk_onderweg_bedrag == Decimal("2620.00")
        assert data.onderweg_saldo == Decimal("2260.00")
        verwacht = Decimal("42800.00") + Decimal("2620.00") - Decimal("12980.00") - Decimal("360.00")
        assert data.verwachte_marge == verwacht
        # Weektabel: week 31 baten, week 32 kosten, week 34 onderweg; cumulatief loopt door.
        per_week = {(w.jaar, w.weeknummer): w for w in data.weken}
        assert per_week[(2026, 31)].baten == Decimal("42800.00")
        assert per_week[(2026, 31)].baten_detail == ["termijn 2"]
        assert per_week[(2026, 32)].kosten_geboekt == Decimal("12980.00")
        assert per_week[(2026, 34)].kosten_onderweg == Decimal("360.00")
        assert data.weken[-1].cumulatief == Decimal("42800.00") - Decimal("12980.00") - Decimal("360.00")

    def test_uren_zonder_tarief_zijn_onbepaalbaar_nooit_gokken(
        self, admin_engine: Engine, administratie_id: uuid.UUID
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26015 Deurne (Bots)")
        zzper = maak_gebruiker(admin_engine, "zzper", "Zonder Tarief")
        _insert_weekstaat(admin_engine, administratie_id=administratie_id, gebruiker_id=zzper,
                          project_id=project_id, jaar=2026, week=33, uren_per_dag=[("2026-08-10", "6.50")])
        with scoped_session(administratie_id) as session:
            data = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)
        assert data.uren_onderweg_bedrag == Decimal("0")
        assert data.onbepaalbaar_uren == Decimal("6.50")
        [week] = data.weken
        assert week.onderweg_onbepaalbaar_uren == Decimal("6.50")

    def test_werkweek_herleiding_verdeelt_verrekende_factuur_over_staat_weken(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, opslag=None
    ) -> None:
        """Kosten op werkweek waar herleidbaar (mockup-notitie): een geboekte ZZP-factuur met
        verrekende weekstaten wordt over de staat-weken verdeeld naar rato van de uren, niet
        op de factuurdatum-week."""
        from app.documenten.rlz_ids import rlz_herboeking_id

        project_id = maak_project(admin_engine, administratie_id, "26016 Groesbeek (Janssen)")
        zzper = maak_gebruiker(admin_engine, "zzper", "Ali D.")
        # Lokaal geboekt document + boekvoorstel (cyclus 0) — het anker voor de herleiding.
        document_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.document (id, administratie_id, bron, soort, bestandsnaam, "
                    " sha256_hash, status, opslag_pad) "
                    "VALUES (:id, :aid, 'upload', 'inkoopfactuur', 'zzp.pdf', :hash, 'geboekt', 'x')"
                ),
                {"id": document_id, "aid": administratie_id, "hash": uuid.uuid4().hex},
            )
            conn.execute(
                text("INSERT INTO boekhouding.boekvoorstel (document_id, boek_cyclus) VALUES (:id, 0)"),
                {"id": document_id},
            )
        # Factuurregels in de cache onder het actuele RLZ-GUID; factuurdatum week 35.
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="inkoop", netto="1000.00", datum="2026-08-24",
                      rlz_document_id=rlz_herboeking_id(document_id, 0))
        # Twee verrekende staten: week 33 (6 u) en week 34 (2 u) → 750/250-verdeling.
        _insert_weekstaat(admin_engine, administratie_id=administratie_id, gebruiker_id=zzper,
                          project_id=project_id, jaar=2026, week=33, uren_per_dag=[("2026-08-10", "6.00")],
                          verrekend_met=document_id)
        _insert_weekstaat(admin_engine, administratie_id=administratie_id, gebruiker_id=zzper,
                          project_id=project_id, jaar=2026, week=34, uren_per_dag=[("2026-08-17", "2.00")],
                          verrekend_met=document_id)
        with scoped_session(administratie_id) as session:
            data = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)
        per_week = {(w.jaar, w.weeknummer): w for w in data.weken}
        assert per_week[(2026, 33)].kosten_geboekt == Decimal("750.00")
        assert per_week[(2026, 34)].kosten_geboekt == Decimal("250.00")
        assert (2026, 35) not in per_week  # niet óók op factuurdatum-week (nooit dubbel)
        assert per_week[(2026, 33)].kosten_detail == ["uit weekstaten"]
        assert data.kosten_geboekt == Decimal("1000.00")

    def test_overzicht_gebruikt_dezelfde_rekenlaag_als_het_detail(
        self, admin_engine: Engine, administratie_id: uuid.UUID
    ) -> None:
        """Mockup-eis: cijfers moeten per definitie op elkaar sluiten — het overzicht komt uit
        exact dezelfde functie als het detail."""
        project_id = maak_project(admin_engine, administratie_id, "26017 Zwolle (Kuijer)")
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="verkoop", netto="61080.00", datum="2026-08-03")
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="inkoop", netto="38900.00", datum="2026-08-04")
        with scoped_session(administratie_id) as session:
            detail = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)
        overzicht = cijfers.overzicht_alle_projecten(administratie_id=administratie_id, vandaag=VANDAAG)
        [rij] = [r for r in overzicht.rijen if r.cijfers.project_id == project_id]
        assert rij.cijfers.baten_geboekt == detail.baten_geboekt
        assert rij.cijfers.kosten_geboekt == detail.kosten_geboekt
        assert rij.cijfers.verwachte_marge == detail.verwachte_marge
        assert overzicht.baten_totaal == detail.baten_geboekt
        assert overzicht.marge_totaal == detail.verwachte_marge

    def test_kosten_zonder_omzet_signaal_en_trend(
        self, admin_engine: Engine, administratie_id: uuid.UUID
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26018 Haarlem (Slokker)")
        # Drie recente weken kosten zonder enige baten → signaal 3 wkn; trend dalend
        # (recente 4 weken negatiever dan de 4 ervoor, met baten in de oudere periode).
        _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                      soort="verkoop", netto="5000.00", datum="2026-07-06")  # week 28
        for datum in ("2026-08-03", "2026-08-10", "2026-08-17"):  # weken 32/33/34
            _insert_regel(admin_engine, administratie_id=administratie_id, project_id=project_id,
                          soort="inkoop", netto="2000.00", datum=datum)
        with scoped_session(administratie_id) as session:
            data = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)
        assert cijfers.kosten_zonder_omzet_weken(data) == 3
        assert cijfers.trend_over_vier_weken(data, vandaag=VANDAAG) == "dalend"


class TestLijstEnSchrijfpaden:
    def test_lijst_badges_en_zonder_specs_teller(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        met_spec = maak_project(admin_engine, administratie_id, "26014 Breda (Moeskops)")
        zonder_spec = maak_project(admin_engine, administratie_id, "26015 Deurne (Bots)")
        zzper = maak_gebruiker(admin_engine, "zzper", "Actief Iemand")
        kantoor.zet_specificatie(
            administratie_id=administratie_id, project_id=met_spec, actor_id=beheerder_id,
            opdrachtgever="Moeskops Bouw", contract_m2=Decimal("4200"), looptijd_tot=date(2026, 11, 30),
        )
        # Alleen het project mét uren-activiteit telt mee in de zonder-specs-teller (keuze 5).
        _insert_weekstaat(admin_engine, administratie_id=administratie_id, gebruiker_id=zzper,
                          project_id=zonder_spec, jaar=2026, week=34, uren_per_dag=[("2026-08-17", "4.00")])
        rijen = kantoor.projecten_lijst(administratie_id=administratie_id)
        per_project = {r.project_id: r for r in rijen}
        assert per_project[met_spec].specs_status == "compleet"
        assert per_project[zonder_spec].specs_status == "geen"
        assert per_project[zonder_spec].heeft_activiteit is True
        assert per_project[met_spec].heeft_activiteit is False
        # Zoeken op opdrachtgever uit de spec.
        gezocht = kantoor.projecten_lijst(administratie_id=administratie_id, zoek="moeskops")
        assert [r.project_id for r in gezocht] == [met_spec]

    def test_schrijfrol_poort(self, admin_engine: Engine, administratie_id: uuid.UUID) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26020 Test (X)")
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Alleen Lezen")
        with pytest.raises(kantoor.GeenSchrijfrecht):
            kantoor.zet_specificatie(
                administratie_id=administratie_id, project_id=project_id, actor_id=boekhouder,
                opdrachtgever="Mag niet",
            )
        projecten_rol = maak_gebruiker(admin_engine, "boekhouding_projecten", "Mag Wel")
        kantoor.zet_specificatie(
            administratie_id=administratie_id, project_id=project_id, actor_id=projecten_rol,
            opdrachtgever="Mag wel",
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None and detail.specificatie.opdrachtgever == "Mag wel"

    def test_staffel_en_werknummer(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26021 Tilburg (Heijmans)")
        staffel_id = kantoor.voeg_staffel_toe(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            omschrijving="Trapsteiger", eenheid="m2", prijs_per_eenheid=Decimal("9.20"), bron="contract §4.2",
        )
        with pytest.raises(kantoor.OngeldigeInvoer, match="Eenheid"):
            kantoor.voeg_staffel_toe(
                administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
                omschrijving="Fout", eenheid="dagdeel", prijs_per_eenheid=Decimal("1"),
            )
        kantoor.wijzig_staffel(
            administratie_id=administratie_id, staffel_id=staffel_id, actor_id=beheerder_id,
            omschrijving="Trapsteiger", eenheid="m2", prijs_per_eenheid=Decimal("9.50"), verrekenbaar=False,
        )
        vendor = uuid.uuid4()
        kantoor.voeg_werknummer_toe(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            vendor_id=vendor, werknummer="BF-2231",
        )
        with pytest.raises(kantoor.OngeldigeInvoer, match="al gekoppeld"):
            kantoor.voeg_werknummer_toe(
                administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
                vendor_id=vendor, werknummer="BF-2231",
            )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        [staffel] = detail.staffels
        assert (staffel.prijs_per_eenheid, staffel.verrekenbaar) == (Decimal("9.50"), False)
        [werknummer] = detail.werknummers
        assert (werknummer.werknummer, werknummer.bevestigd) == ("BF-2231", True)

    def test_document_upload_en_leespad(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        from app.documenten.storage import LokaleBestandsopslag

        opslag = LokaleBestandsopslag(tmp_path)
        monkeypatch.setattr("app.projecten.kantoor.standaard_opslag", lambda: opslag)
        project_id = maak_project(admin_engine, administratie_id, "26022 Eindhoven (BAM)")
        document_id = kantoor.upload_project_document(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            soort="contract", titel="Opdrachtbevestiging v2", bestandsnaam="ob.pdf", inhoud=b"%PDF-1.4 contract",
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        [doc] = detail.documenten
        assert (doc.id, doc.soort, doc.ontleed) == (document_id, "contract", False)
        with admin_engine.connect() as conn:
            pad = conn.execute(
                text("SELECT opslag_pad FROM boekhouding.project_document WHERE id = :id"), {"id": document_id}
            ).scalar_one()
        assert opslag.lezen(pad=pad) == b"%PDF-1.4 contract"


class TestNieuwProject:
    def test_via_de_bestaande_motorbouwstenen(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        fake = FakeProjectClient()
        resultaat = kantoor.maak_project_aan(
            administratie_id=administratie_id, actor_id=beheerder_id,
            projectnummer="26127", plaats="Tilburg", opdrachtgever="Heijmans",
            startdatum=date(2026, 9, 1), client=fake,
        )
        assert resultaat.projectnaam == "26127 Tilburg (Heijmans)"
        assert resultaat.bestond_al is False
        assert fake.put_project_aanroepen == 1
        assert fake.projects[str(resultaat.rlz_project_id)]["IsActive"] is True
        # Cache-upsert + spec-opdrachtgever + startdatum.
        with admin_engine.connect() as conn:
            naam = conn.execute(
                text("SELECT naam FROM boekhouding.project_cache WHERE id = :id"),
                {"id": resultaat.rlz_project_id},
            ).scalar_one()
            spec = conn.execute(
                text("SELECT opdrachtgever, looptijd_van FROM boekhouding.project_specificatie WHERE project_id = :id"),
                {"id": resultaat.rlz_project_id},
            ).one()
        assert naam == "26127 Tilburg (Heijmans)"
        assert (spec.opdrachtgever, spec.looptijd_van) == ("Heijmans", date(2026, 9, 1))
        # Idempotent: tweede klik = bestond_al, géén tweede PUT.
        tweede = kantoor.maak_project_aan(
            administratie_id=administratie_id, actor_id=beheerder_id,
            projectnummer="26127", plaats="Tilburg", opdrachtgever="Heijmans", client=fake,
        )
        assert tweede.bestond_al is True
        assert fake.put_project_aanroepen == 1

    def test_naamconventie_poorten(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(kantoor.OngeldigeInvoer, match="cijfers"):
            kantoor.maak_project_aan(
                administratie_id=administratie_id, actor_id=beheerder_id,
                projectnummer="26x", plaats="Tilburg", opdrachtgever="Heijmans", client=FakeProjectClient(),
            )
        with pytest.raises(kantoor.OngeldigeInvoer, match="50"):
            kantoor.maak_project_aan(
                administratie_id=administratie_id, actor_id=beheerder_id,
                projectnummer="26128", plaats="Z" * 40, opdrachtgever="Heijmans", client=FakeProjectClient(),
            )

    def test_volgende_projectnummer(self, admin_engine: Engine, administratie_id: uuid.UUID) -> None:
        assert kantoor.volgende_projectnummer(administratie_id=administratie_id, vandaag=VANDAAG) == "26001"
        maak_project(admin_engine, administratie_id, "26014 Breda (Moeskops)")
        maak_project(admin_engine, administratie_id, "26126 Elders (X)")
        maak_project(admin_engine, administratie_id, "25099 Vorig jaar (Y)")  # telt niet mee
        assert kantoor.volgende_projectnummer(administratie_id=administratie_id, vandaag=VANDAAG) == "26127"


class TestOntleding:
    def _document(self, admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch) -> uuid.UUID:
        from app.documenten.storage import LokaleBestandsopslag

        opslag = LokaleBestandsopslag(tmp_path)
        monkeypatch.setattr("app.projecten.kantoor.standaard_opslag", lambda: opslag)
        monkeypatch.setattr("app.projecten.ontleding.standaard_opslag", lambda: opslag)
        return kantoor.upload_project_document(
            administratie_id=administratie_id, project_id=project_id, actor_id=beheerder_id,
            soort="contract", titel="OB", bestandsnaam="ob.pdf", inhoud=b"%PDF-1.4 contract",
        )

    def test_gate_uit_geeft_duidelijke_fout(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26030 Gate (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        with pytest.raises(ontleding.OntledingUitgeschakeld, match="AVG-gate"):
            ontleding.ontleed_document(
                administratie_id=administratie_id, project_id=project_id,
                project_document_id=document_id, actor_id=beheerder_id,
            )

    def test_voorstel_en_bevestigen_per_regel(
        self, admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path, monkeypatch
    ) -> None:
        project_id = maak_project(admin_engine, administratie_id, "26031 Ontleed (X)")
        document_id = self._document(admin_engine, administratie_id, beheerder_id, project_id, tmp_path, monkeypatch)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET ai_extractie_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        monkeypatch.setattr("app.projecten.ontleding.settings.anthropic_api_key", "test-key", raising=False)

        def fake_extraheer(pdf_bytes, *, verbruik_referentie=None):
            assert pdf_bytes == b"%PDF-1.4 contract"
            return [
                ContractRegel(soort="contract_m2", omschrijving="Contract-m²",
                              citaat='p.1: "4.200 m² steigerwerk"', waarde="4200", eenheid=None,
                              van=None, tot=None, zekerheid=0.95),
                ContractRegel(soort="staffel", omschrijving="Trapsteiger",
                              citaat='§4.2 "€ 9,20 per m²"', waarde="9.20", eenheid="m²",
                              van=None, tot=None, zekerheid=0.9),
                ContractRegel(soort="boete", omschrijving="Boeteclausule",
                              citaat='§7 "€ 500 per kalenderdag"', waarde="500", eenheid=None,
                              van=None, tot=None, zekerheid=0.8),
            ]

        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id,
            project_document_id=document_id, actor_id=beheerder_id, extraheer=fake_extraheer,
        )
        assert resultaat.aantal_regels == 3
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert len(detail.ontleding) == 3
        per_soort = {r.soort: r for r in detail.ontleding}
        # Bevestigen contract_m2 → deterministisch naar de specificatie.
        ontleding.beslis_regel(
            administratie_id=administratie_id, regel_id=per_soort["contract_m2"].id,
            actor_id=beheerder_id, bevestigen=True,
        )
        # Staffel vereist een mens-gekozen eenheid uit de vaste vier (AI-eenheid = voorstel).
        with pytest.raises(kantoor.OngeldigeInvoer, match="eenheid"):
            ontleding.beslis_regel(
                administratie_id=administratie_id, regel_id=per_soort["staffel"].id,
                actor_id=beheerder_id, bevestigen=True,
            )
        ontleding.beslis_regel(
            administratie_id=administratie_id, regel_id=per_soort["staffel"].id,
            actor_id=beheerder_id, bevestigen=True, eenheid="m2",
        )
        # Afwijzen laat niets achter in spec/staffels.
        ontleding.beslis_regel(
            administratie_id=administratie_id, regel_id=per_soort["boete"].id,
            actor_id=beheerder_id, bevestigen=False,
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None and detail.specificatie.contract_m2 == Decimal("4200")
        [staffel] = detail.staffels
        assert (staffel.omschrijving, staffel.eenheid, staffel.prijs_per_eenheid) == (
            "Trapsteiger", "m2", Decimal("9.20"),
        )
        assert staffel.bron == '§4.2 "€ 9,20 per m²"'
        statussen = {r.soort: r.status for r in detail.ontleding}
        assert statussen == {"contract_m2": "bevestigd", "staffel": "bevestigd", "boete": "afgewezen"}
        # Een regel kan maar één keer beslist worden.
        with pytest.raises(kantoor.OngeldigeInvoer, match="al beslist"):
            ontleding.beslis_regel(
                administratie_id=administratie_id, regel_id=per_soort["boete"].id,
                actor_id=beheerder_id, bevestigen=True,
            )
        # Her-ontleding vervangt alleen de (niet meer bestaande) voorstel-regels; besliste
        # regels blijven als vastlegging staan.
        ontleding.ontleed_document(
            administratie_id=administratie_id, project_id=project_id,
            project_document_id=document_id, actor_id=beheerder_id, extraheer=lambda *_a, **_k: [],
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert len(detail.ontleding) == 3  # de drie besliste regels blijven
