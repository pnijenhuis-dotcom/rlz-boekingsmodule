# ruff: noqa: F811 — pytest-fixtures als parameters
"""Autoboek-kandidaten-motor (blok B 01-09, mockup autoboek-kandidaten.html, migratie 0095): pure
reeks-analyse ("N identieke mens-boekingen op rij" — telling herzien 10-09 avond, blok 3: de eerste boeking telt
als 1, een afwijkende boeking start een nieuwe reeks, automatisch telt niet en breekt niet), kwalificatie
mét leesbare redenen, heroverweeg-signalen (advies-only), DB-keten (herberekenen, tabs, bulk aanzetten
mét LIVE hertoets via de bestaande opt-in-schrijver, verbergen mét verplichte reden, uitzetten,
drempel) en rolpoorten (Beheerder-only)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.autoboek_kandidaten import motor, service
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
    LeverancierVoorkeur,
)
from app.geheugen.engine import Observatie
from app.geheugen.models import BoekingObservatie, ObservatieBron
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)
VENDOR = uuid.UUID("aaaaaaaa-2222-2222-2222-222222222222")
GB_A = uuid.UUID("11111111-0000-0000-0000-000000000001")
GB_B = uuid.UUID("11111111-0000-0000-0000-000000000002")
BTW = uuid.UUID("22222222-0000-0000-0000-000000000001")
BTW_EU = uuid.UUID("22222222-0000-0000-0000-000000000002")
T0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _boeking(n: int, *, gb=GB_A, btw=BTW, project=None, bedrag="100.00", automatisch=False, btw_naam="NL, Hoog") -> motor.Boeking:
    return motor.Boeking(
        document_id=uuid.uuid4(),
        geboekt_op=T0 + timedelta(days=30 * n),
        factuurdatum=(T0 + timedelta(days=30 * n)).date(),
        totaalbedrag=Decimal(bedrag),
        regels=(motor.GeboekteRegel(gb_id=gb, btw_id=btw, project_id=project, btw_naam=btw_naam),),
        automatisch=automatisch,
    )


class TestMotorReeks:
    """Telling herzien 10-09 avond (blok 3, besluit Peter): de reeks telt IDENTIEKE mens-boekingen op rij, de eerste
    telt als 1. Tot 10-09 telde de motor "ongewijzigd t.o.v. het voorstel" (eerste boeking = referentiepunt)."""

    def test_precies_drie_identieke_mens_boekingen_is_drie(self) -> None:
        reeks = motor.analyseer_reeks([_boeking(i) for i in range(3)], seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 3 and reeks.correcties == 0 and reeks.mens_boekingen == 3
        assert reeks.reeks_waarden == frozenset({(None, GB_A, BTW, None)})

    def test_twee_identieke_boekingen_is_twee(self) -> None:
        reeks = motor.analyseer_reeks([_boeking(i) for i in range(2)], seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 2

    def test_drie_waarvan_de_middelste_afwijkt_is_een(self) -> None:
        # A, B, A: de laatste boeking start een nieuwe reeks en telt zelf als 1.
        boekingen = [_boeking(0), _boeking(1, gb=GB_B), _boeking(2)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 1 and reeks.mens_boekingen == 3

    def test_vier_waarvan_de_eerste_afwijkt_is_drie(self) -> None:
        boekingen = [_boeking(0, gb=GB_B), _boeking(1), _boeking(2), _boeking(3)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 3 and reeks.reeks_waarden == frozenset({(None, GB_A, BTW, None)})

    def test_zes_identieke_boekingen_tellen_alle_zes(self) -> None:
        # Telling herzien 10-09: was 5 (de eerste boeking bevestigde niets).
        reeks = motor.analyseer_reeks([_boeking(i) for i in range(6)], seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 6 and reeks.correcties == 0 and reeks.mens_boekingen == 6
        assert reeks.bedrag_vast is True and reeks.laatste_factuur_bedrag == Decimal("100.00")

    def test_rlz_seed_verandert_de_telling_niet(self) -> None:
        # Telling herzien 10-09: de RLZ-seed telt niet als boeking; drie identieke mens-boekingen = 3, mét of zonder
        # seed.
        seed = [Observatie(None, GB_A, BTW, None, ObservatieBron.RLZ_SEED.value, date(2025, 12, 1))]
        reeks = motor.analyseer_reeks([_boeking(i) for i in range(3)], seed_observaties=seed, project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 3
        andere_seed = [Observatie(None, GB_B, BTW, None, ObservatieBron.RLZ_SEED.value, date(2025, 12, 1))]
        reeks = motor.analyseer_reeks(
            [_boeking(i) for i in range(3)], seed_observaties=andere_seed, project_verplicht=False
        )
        # Afwijken van het RLZ-voorstel = correctie (heroverwegen), geen reeksbreuk.
        assert reeks.reeks_ongewijzigd == 3 and reeks.correcties >= 1

    def test_correctie_start_de_teller_opnieuw_en_benoemt_het_veld(self) -> None:
        # Eén boeking op A, dan drie keer B: de eerste B is een correctie t.o.v. het voorstel én start een nieuwe reeks
        # (telt zelf als 1) — telling herzien 10-09: reeks 3 (was 2).
        boekingen = [_boeking(0), _boeking(1, gb=GB_B), _boeking(2, gb=GB_B), _boeking(3, gb=GB_B)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.correcties == 1 and reeks.laatste_correctie_velden == ("grootboek",)
        assert reeks.reeks_ongewijzigd == 3

    def test_correcties_blijven_gemeten_tegenover_het_voorstel_de_reeks_tegenover_de_vorige_boeking(self) -> None:
        # Vier keer A, dan drie keer B: het geheugen stelt (gewogen meerderheid) nog A voor, dus élke B is een correctie
        # voor heroverwegen (3); de reeks telt de drie identieke B's (telling herzien 10-09: was 0). Het "nooit gokken"
        # zit sinds 10-09 in de service-poort: het actuele geheugen-voorstel moet gelijk zijn aan `reeks_waarden`.
        boekingen = [_boeking(i) for i in range(4)] + [_boeking(4 + i, gb=GB_B) for i in range(3)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 3 and reeks.correcties == 3
        assert reeks.reeks_waarden == frozenset({(None, GB_B, BTW, None)})

    def test_btw_correctie_en_wisselend_bedrag(self) -> None:
        boekingen = [_boeking(0), _boeking(1), _boeking(2, btw=BTW_EU, btw_naam="EU, Diensten", bedrag="120.00")]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.laatste_correctie_velden == ("btw",) and reeks.buitenland is True
        assert reeks.bedrag_vast is False and reeks.reeks_ongewijzigd == 1

    def test_automatisch_geboekt_telt_niet_en_breekt_de_reeks_niet_maar_voedt_het_geheugen(self) -> None:
        # Telling herzien 10-09: mens A, auto, auto, mens A = 2 identieke mens-boekingen (was 1).
        boekingen = [_boeking(0), _boeking(1, automatisch=True), _boeking(2, automatisch=True), _boeking(3)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.mens_boekingen == 2 and reeks.reeks_ongewijzigd == 2
        # Een automatische boeking met ándere waarden breekt de reeks evenmin.
        boekingen = [_boeking(0), _boeking(1, gb=GB_B, automatisch=True), _boeking(2)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert reeks.mens_boekingen == 2 and reeks.reeks_ongewijzigd == 2

    def test_projectplicht_vergelijkt_ook_het_project(self) -> None:
        p1, p2 = uuid.uuid4(), uuid.uuid4()
        boekingen = [_boeking(0, project=p1), _boeking(1, project=p1), _boeking(2, project=p2)]
        reeks = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=True)
        assert reeks.laatste_correctie_velden == ("project",) and reeks.reeks_ongewijzigd == 1
        assert reeks.reeks_waarden == frozenset({(None, GB_A, BTW, p2)})
        zonder = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False)
        assert zonder.reeks_ongewijzigd == 3 and zonder.reeks_waarden == frozenset({(None, GB_A, BTW, None)})

    def test_meer_regels_met_dezelfde_waarden_zijn_identiek_aan_een_regel(self) -> None:
        # Leveranciersniveau: aantal en volgorde van gelijke regels tellen niet; een extra regel op een ander GB wél.
        twee_regels = motor.Boeking(
            document_id=uuid.uuid4(),
            geboekt_op=T0 + timedelta(days=30),
            factuurdatum=None,
            totaalbedrag=Decimal("100.00"),
            regels=(
                motor.GeboekteRegel(gb_id=GB_A, btw_id=BTW, project_id=None, btw_naam="NL, Hoog"),
                motor.GeboekteRegel(gb_id=GB_A, btw_id=BTW, project_id=None, btw_naam="NL, Hoog"),
            ),
        )
        reeks = motor.analyseer_reeks(
            [_boeking(0), twee_regels, _boeking(2)], seed_observaties=[], project_verplicht=False
        )
        assert reeks.reeks_ongewijzigd == 3
        gemengd = motor.Boeking(
            document_id=uuid.uuid4(),
            geboekt_op=T0 + timedelta(days=30),
            factuurdatum=None,
            totaalbedrag=Decimal("100.00"),
            regels=(
                motor.GeboekteRegel(gb_id=GB_A, btw_id=BTW, project_id=None, btw_naam="NL, Hoog"),
                motor.GeboekteRegel(gb_id=GB_B, btw_id=BTW, project_id=None, btw_naam="NL, Hoog"),
            ),
        )
        reeks = motor.analyseer_reeks([_boeking(0), gemengd, _boeking(2)], seed_observaties=[], project_verplicht=False)
        assert reeks.reeks_ongewijzigd == 1

    def test_correcties_na_activatie_worden_apart_geteld(self) -> None:
        boekingen = [_boeking(i) for i in range(3)] + [_boeking(3, gb=GB_B)]
        reeks = motor.analyseer_reeks(
            boekingen, seed_observaties=[], project_verplicht=False, vanaf=T0 + timedelta(days=75)
        )
        assert reeks.correcties_na == {"grootboek": 1}
        eerder = motor.analyseer_reeks(boekingen, seed_observaties=[], project_verplicht=False, vanaf=T0 + timedelta(days=100))
        assert eerder.correcties_na == {}


def _reeks(n: int, **kw) -> motor.Reeks:
    return motor.Reeks(
        reeks_ongewijzigd=n,
        correcties=kw.get("correcties", 0),
        laatste_correctie=kw.get("laatste_correctie"),
        laatste_correctie_velden=kw.get("velden", ()),
        mens_boekingen=n,
        laatste_factuur_datum=date(2026, 8, 25),
        laatste_factuur_bedrag=Decimal("10"),
        laatste_document_id=None,
        bedrag_vast=kw.get("bedrag_vast", True),
        buitenland=kw.get("buitenland", False),
        correcties_na=kw.get("correcties_na", {}),
    )


class TestKwalificatieEnHeroverwegen:
    def test_kwalificeert_alleen_als_alles_groen(self) -> None:
        ok = motor.kwalificeer(_reeks(5), drempel=5, geheugen_bevestigd=True, geheugen_reden=None, open_vragen=0, afgewezen=0, duplicaatsignalen=0, veldwerker_gekoppeld=False)
        assert ok.kwalificeert and ok.redenen == ()
        assert ok.chips == (
            "5 identieke boekingen",
            "geheugen bevestigd",
            "0 vragen / 0 correcties",
            "vast maandbedrag",
        )

    def test_elke_blokkade_is_een_leesbare_reden(self) -> None:
        k = motor.kwalificeer(_reeks(4, bedrag_vast=False, buitenland=True), drempel=5, geheugen_bevestigd=False, geheugen_reden="btw: leverancier-fallback", open_vragen=1, afgewezen=2, duplicaatsignalen=1, veldwerker_gekoppeld=True)
        assert not k.kwalificeert
        assert k.redenen == (
            "4 identieke boekingen (drempel 5)",
            "geheugen niet volledig app-bevestigd (btw: leverancier-fallback)",
            "1 open vraag",
            "2 afgewezen documenten",
            "1 duplicaatsignaal",
            "crediteur gekoppeld aan een veldwerker — autoboeken loopt via de urenmatch-opt-in",
        )
        assert "bedrag wisselt" in k.chips and "buitenland-tarief" in k.chips

    def test_heroverwegen_zonder_activatiemoment_zwijgt(self) -> None:
        assert motor.heroverweeg_signalen(_reeks(2, correcties_na={"btw": 1}), gebeurtenissen=[], actief_sinds=None) == ()

    def test_heroverwegen_benoemt_correctie_vraag_afwijzing_auto_correctie_en_buitenland(self) -> None:
        sinds = datetime(2026, 8, 12, tzinfo=UTC)
        reeks = _reeks(0, correcties=2, laatste_correctie=datetime(2026, 8, 28, tzinfo=UTC), velden=("grootboek",), correcties_na={"grootboek": 2}, buitenland=True)
        signalen = motor.heroverweeg_signalen(
            reeks,
            gebeurtenissen=[
                motor.Gebeurtenis("vraag", datetime(2026, 8, 1, tzinfo=UTC), uuid.uuid4()),  # vóór activatie: telt niet
                motor.Gebeurtenis("vraag", datetime(2026, 8, 20, tzinfo=UTC), uuid.uuid4()),
                motor.Gebeurtenis("afwijzing", datetime(2026, 8, 21, tzinfo=UTC), uuid.uuid4()),
                motor.Gebeurtenis("correctie_automatisch", datetime(2026, 8, 22, tzinfo=UTC), uuid.uuid4()),
            ],
            actief_sinds=sinds,
        )
        assert signalen == (
            "2 correcties ná activatie",
            "GB-code gewijzigd door mens (28 Aug)",
            "vraag gesteld (20 Aug)",
            "afgewezen (21 Aug)",
            "correctie op automatisch geboekt document (22 Aug)",
            "buitenland-signaal",
        )


# --------------------------------------------------------------------------- DB-keten


@pytest.fixture
def vendor(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Ebbers Salarisadvies B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR, "aid": administratie_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.taxrate_cache (id, administratie_id, naam, percentage, brondata) "
                "VALUES (:id, :aid, 'NL, Hoog', 21, '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": BTW, "aid": administratie_id},
        )
    return VENDOR


VENDOR_2 = uuid.UUID("aaaaaaaa-3333-3333-3333-333333333333")


@pytest.fixture
def tweede_vendor(admin_engine: Engine, administratie_id: uuid.UUID, vendor: uuid.UUID) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Transip B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_2, "aid": administratie_id},
        )
    return VENDOR_2


def _geboekt(
    administratie_id: uuid.UUID,
    actor: uuid.UUID,
    opslag,
    *,
    n: int,
    gb: uuid.UUID = GB_A,
    automatisch: bool = False,
    status: DocumentStatus = DocumentStatus.GEBOEKT,
    bedrag: str = "2721.83",
    vendor: uuid.UUID = VENDOR,
) -> uuid.UUID:
    tijdstip = T0 + timedelta(days=30 * n)
    document_id = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"ebbers-{vendor.hex[:6]}-{n}.pdf",
        inhoud=f"%PDF-1.4 ebbers {vendor} {n}".encode(),
        actor_id=actor,
        opslag=opslag,
    ).document_id
    with scoped_session(administratie_id, actor_id=actor) as session:
        session.add(
            Boekvoorstel(document_id=document_id, vendor_id=vendor, factuurdatum=tijdstip.date(), totaalbedrag=Decimal(bedrag), referentie=f"F-{vendor.hex[:6]}-{n}")
        )
        session.add(BoekvoorstelRegel(document_id=document_id, volgnummer=1, ledger_id=gb, taxrate_id=BTW, netto_bedrag=Decimal("2249.45"), btw_bedrag=Decimal("472.38"), omschrijving="Salarisverwerking"))
        document = session.get(Document, document_id)
        assert document is not None
        document.status = status
        if status == DocumentStatus.GEBOEKT:
            from app.db.systeem_actor import SYSTEEM_ACTOR_ID

            session.add(
                DocumentGebeurtenis(
                    document_id=document_id,
                    van_status=DocumentStatus.TE_CONTROLEREN,
                    naar_status=DocumentStatus.GEBOEKT,
                    actor_id=SYSTEEM_ACTOR_ID if automatisch else actor,
                    detail={"automatisch_geboekt": True} if automatisch else {"reden": "geboekt in RLZ"},
                    tijdstip=tijdstip,
                )
            )
            # Leerlus-equivalent: de bevestigde waarden als app-observatie (bron van "geheugen bevestigd").
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=vendor,
                    gb_id=gb,
                    btw_id=BTW,
                    bron=ObservatieBron.APP.value,
                    bron_datum=tijdstip.date(),
                )
            )
        elif status == DocumentStatus.VRAAG_OPEN:
            session.add(
                DocumentGebeurtenis(
                    document_id=document_id,
                    van_status=DocumentStatus.TE_CONTROLEREN,
                    naar_status=DocumentStatus.VRAAG_OPEN,
                    actor_id=actor,
                    detail={"reden": "vraag"},
                    tijdstip=tijdstip,
                )
            )
    return document_id


def _audit_acties(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar() or 0)


class TestKeten:
    def test_vijf_op_rij_maakt_een_kandidaat_en_bulk_aanzetten_hertoetst_live(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        # Deze test toetst de motor op de oorspronkelijke drempel 5 (01-09); de platformbrede default is sinds blok A
        # 10-09 3 — expliciet terugzetten zodat "4 identieke bij drempel 5" hier zijn betekenis houdt.
        service.zet_drempel(actor_id=beheerder_id, drempel=5)
        for n in range(4):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        tellers = service.herbereken_administratie(administratie_id=administratie_id)
        assert tellers == {"kandidaten": 0, "actief": 0, "heroverwegen": 0, "verborgen": 0, "rijen": 1, "geactiveerd": 0}
        lijst = service.lijst(tab="kandidaten")
        assert lijst.totaal == 0
        # Niet-kwalificerend blijft leesbaar in de stand (telling herzien 10-09: vier identieke boekingen = 4).
        stand = service.hertoets_vendor(administratie_id=administratie_id, vendor_id=vendor)
        assert stand.reeks_ongewijzigd == 4 and stand.redenen == ["4 identieke boekingen (drempel 5)"]

        _geboekt(administratie_id, beheerder_id, opslag, n=4)
        service.herbereken_alle()
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tellers"]["kandidaten"] == 1 and body["tellers"]["laatste_run_op"] is not None
        rij = body["rijen"][0]
        assert rij["leverancier_naam"] == "Ebbers Salarisadvies B.V." and rij["kwalificeert"] is True
        assert rij["chips"] == [
            "5 identieke boekingen",
            "geheugen bevestigd",
            "0 vragen / 0 correcties",
            "vast maandbedrag",
        ]
        assert rij["laatste_factuur_bedrag"] == "2721.83"
        # Zoeken op administratie- of leveranciernaam.
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten&q=ebbers", headers=headers).json()["totaal"] == 1
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten&q=nergens", headers=headers).json()["totaal"] == 0
        assert client.get("/instellingen/autoboeken/stand", headers=headers).json()["kandidaten"] == 1

        # Bulk aanzetten: LIVE hertoets — een tweede (onbekende) leverancier wordt overgeslagen mét reden.
        onbekend = uuid.uuid4()
        r = client.post(
            "/instellingen/autoboeken/kandidaten/aanzetten",
            headers=headers,
            json={"items": [
                {"administratie_id": str(administratie_id), "vendor_id": str(vendor)},
                {"administratie_id": str(administratie_id), "vendor_id": str(onbekend)},
            ]},
        )
        assert r.status_code == 200, r.text
        uit = r.json()
        assert uit["aangezet"] == 1 and uit["overgeslagen"] == 1
        assert uit["uitkomsten"][1]["status"] == "overgeslagen" and "kwalificeert niet meer" in uit["uitkomsten"][1]["reden"]
        with scoped_session(administratie_id) as session:
            voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor))
            assert voorkeur is not None and voorkeur.autoboeken_ingeschakeld is True
        assert _audit_acties(admin_engine, "leverancier_autoboeken_gewijzigd") >= 1
        assert _audit_acties(admin_engine, "autoboek_kandidaat_aangezet") == 1
        # Nu op de tab Actief, niet meer kandidaat; tweede keer aanzetten = overgeslagen "staat al aan".
        assert client.get("/instellingen/autoboeken/kandidaten?tab=actief", headers=headers).json()["totaal"] == 1
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 0
        r = client.post("/instellingen/autoboeken/kandidaten/aanzetten", headers=headers, json={"items": [{"administratie_id": str(administratie_id), "vendor_id": str(vendor)}]})
        assert r.json()["uitkomsten"][0]["reden"] == "autoboeken staat al aan"

        # Heroverwegen: een mens corrigeert de GB ná activatie (activatie = nu; de correctie ligt
        # daarom bewust vóóruit in de tijd) → signaal, niets automatisch uit.
        _geboekt(administratie_id, beheerder_id, opslag, n=40, gb=GB_B)
        service.herbereken_administratie(administratie_id=administratie_id)
        r = client.get("/instellingen/autoboeken/kandidaten?tab=heroverwegen", headers=headers)
        assert r.json()["totaal"] == 1
        signalen = r.json()["rijen"][0]["heroverweeg_signalen"]
        assert signalen[0] == "1 correctie ná activatie" and any(s.startswith("GB-code gewijzigd door mens") for s in signalen)
        with scoped_session(administratie_id) as session:
            assert session.get(LeverancierVoorkeur, (administratie_id, vendor)).autoboeken_ingeschakeld is True
        # Uitzetten = één klik via de bestaande schrijver; de reeks staat op 1 (de correctie start een nieuwe reeks)
        # → geen kandidaat.
        r = client.post(f"/instellingen/autoboeken/kandidaten/{administratie_id}/{vendor}/uitzetten", headers=headers)
        assert r.status_code == 204
        with scoped_session(administratie_id) as session:
            assert session.get(LeverancierVoorkeur, (administratie_id, vendor)).autoboeken_ingeschakeld is False
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 0
        assert client.get("/instellingen/autoboeken/kandidaten?tab=heroverwegen", headers=headers).json()["totaal"] == 0

    def test_verbergen_vereist_reden_en_is_terugvindbaar(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        for n in range(6):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        service.herbereken_administratie(administratie_id=administratie_id)
        headers = _bearer(beheerder_id, rol="beheerder")
        pad = f"/instellingen/autoboeken/kandidaten/{administratie_id}/{vendor}"
        assert client.post(f"{pad}/verbergen", headers=headers, json={"reden": "  "}).status_code == 422
        assert client.post(f"{pad}/verbergen", headers=headers, json={"reden": "wil ik handmatig houden"}).status_code == 204
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 0
        verborgen = client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten&verborgen=true", headers=headers).json()
        assert verborgen["totaal"] == 1 and verborgen["rijen"][0]["snooze_reden"] == "wil ik handmatig houden"
        assert verborgen["tellers"]["verborgen"] == 1
        # De dagelijkse herberekening laat de snooze staan.
        service.herbereken_administratie(administratie_id=administratie_id)
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 0
        assert _audit_acties(admin_engine, "autoboek_kandidaat_verborgen") == 1
        assert client.post(f"{pad}/weer-tonen", headers=headers).status_code == 204
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 1

    def test_open_vraag_of_afwijzing_blokkeert_en_drempel_is_instelbaar_met_audit(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        for n in range(6):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
        _geboekt(administratie_id, beheerder_id, opslag, n=7, status=DocumentStatus.VRAAG_OPEN)
        stand = service.hertoets_vendor(administratie_id=administratie_id, vendor_id=vendor)
        assert not stand.kwalificeert and "1 open vraag" in stand.redenen and stand.open_vragen == 1
        headers = _bearer(beheerder_id, rol="beheerder")
        assert client.put("/instellingen/autoboeken/instelling", headers=headers, json={"drempel_op_rij": 0}).status_code == 422
        r = client.put("/instellingen/autoboeken/instelling", headers=headers, json={"drempel_op_rij": 8})
        assert r.status_code == 200 and r.json()["drempel_op_rij"] == 8
        assert client.get("/instellingen/autoboeken/instelling", headers=headers).json()["drempel_op_rij"] == 8
        assert _audit_acties(admin_engine, "autoboek_drempel_gewijzigd") == 1
        stand = service.hertoets_vendor(administratie_id=administratie_id, vendor_id=vendor)
        # Telling herzien 10-09 (was "5 op rij ongewijzigd").
        assert "6 identieke boekingen (drempel 8)" in stand.redenen

    def test_herbereken_endpoint_en_sync_alles_rapport(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, opslag) -> None:
        _geboekt(administratie_id, beheerder_id, opslag, n=0)
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.post("/instellingen/autoboeken/herbereken", headers=headers)
        assert r.status_code == 200 and r.json()["fouten"] == 0 and r.json()["administraties"] >= 1
        from app.cli import _rapporteer_autoboek_kandidaten

        assert _rapporteer_autoboek_kandidaten(service.herbereken_alle()) == 0
        assert _rapporteer_autoboek_kandidaten({administratie_id: "RuntimeError: kapot"}) == 1


class TestBulkVerbergenEnSelecteerAlle:
    """B5.1 + B5.2 (design-ronde 03-09, mockup inzicht-kantoorbreed ⑧): bulk-verbergen server-side in
    één call mét uitkomst per rij, en `alle: true` = exact de filterset van de lijst zonder paginering."""

    def _twee_kandidaten(self, administratie_id, beheerder_id, opslag) -> None:
        for n in range(6):
            _geboekt(administratie_id, beheerder_id, opslag, n=n)
            _geboekt(administratie_id, beheerder_id, opslag, n=n, vendor=VENDOR_2, bedrag="99.00")
        service.herbereken_administratie(administratie_id=administratie_id)

    def test_reden_verplicht_en_precies_een_selectievorm(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, tweede_vendor: uuid.UUID, opslag
    ) -> None:
        self._twee_kandidaten(administratie_id, beheerder_id, opslag)
        headers = _bearer(beheerder_id, rol="beheerder")
        item = {"administratie_id": str(administratie_id), "vendor_id": str(vendor)}
        pad = "/instellingen/autoboeken/kandidaten/verbergen"
        assert client.post(pad, headers=headers, json={"items": [item]}).status_code == 422
        assert client.post(pad, headers=headers, json={"items": [item], "reden": "   "}).status_code == 422
        assert client.post(pad, headers=headers, json={"items": [], "reden": "x"}).status_code == 422
        assert client.post(pad, headers=headers, json={"reden": "x"}).status_code == 422
        assert client.post(pad, headers=headers, json={"items": [item], "alle": True, "reden": "x"}).status_code == 422
        assert client.post("/instellingen/autoboeken/kandidaten/aanzetten", headers=headers, json={"items": []}).status_code == 422
        # Niets verborgen door de geweigerde aanroepen.
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 2

    def test_bulk_verbergen_uitkomst_per_rij_en_een_fout_stopt_de_rest_niet(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        vendor: uuid.UUID,
        tweede_vendor: uuid.UUID,
        opslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._twee_kandidaten(administratie_id, beheerder_id, opslag)
        headers = _bearer(beheerder_id, rol="beheerder")
        pad = "/instellingen/autoboeken/kandidaten/verbergen"
        onbekend = uuid.uuid4()

        # Eén kapotte rij (gesimuleerde DB-fout op de tweede leverancier) → 'fout', de rest gaat door.
        echte_verbergen = service.verbergen

        def kapot(*, administratie_id, vendor_id, actor_id, reden):
            if vendor_id == tweede_vendor:
                raise RuntimeError("verbinding weg")
            return echte_verbergen(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, reden=reden)

        monkeypatch.setattr(service, "verbergen", kapot)
        r = client.post(
            pad,
            headers=headers,
            json={
                "items": [
                    {"administratie_id": str(administratie_id), "vendor_id": str(vendor)},
                    {"administratie_id": str(administratie_id), "vendor_id": str(onbekend)},
                    {"administratie_id": str(administratie_id), "vendor_id": str(tweede_vendor)},
                ],
                "reden": "wil ik handmatig houden",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verborgen"] == 1 and body["overgeslagen"] == 2
        statussen = [(u["status"], u["reden"]) for u in body["uitkomsten"]]
        assert statussen[0] == ("verborgen", None)
        assert statussen[1] == ("overgeslagen", "onbekende kandidaat")
        assert statussen[2][0] == "fout" and "verbinding weg" in statussen[2][1]
        # Namen reizen mee (ook voor rijen buiten de huidige pagina); onbekende rij zonder naam.
        assert body["uitkomsten"][0]["leverancier_naam"] == "Ebbers Salarisadvies B.V."
        assert body["uitkomsten"][0]["administratie_naam"]
        assert body["uitkomsten"][1]["leverancier_naam"] is None
        assert _audit_acties(admin_engine, "autoboek_kandidaat_verborgen") == 1
        monkeypatch.undo()

        # Tweede keer: de al verborgen rij wordt overgeslagen mét reden, de andere wordt nu wél verborgen.
        r = client.post(
            pad,
            headers=headers,
            json={
                "items": [
                    {"administratie_id": str(administratie_id), "vendor_id": str(vendor)},
                    {"administratie_id": str(administratie_id), "vendor_id": str(tweede_vendor)},
                ],
                "reden": "tweede ronde",
            },
        )
        body = r.json()
        assert [u["status"] for u in body["uitkomsten"]] == ["overgeslagen", "verborgen"]
        assert body["uitkomsten"][0]["reden"] == "al verborgen"
        assert _audit_acties(admin_engine, "autoboek_kandidaat_verborgen") == 2
        lijst = client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten&verborgen=true", headers=headers).json()
        assert lijst["totaal"] == 2 and {r_["snooze_reden"] for r_ in lijst["rijen"]} == {"wil ik handmatig houden", "tweede ronde"}
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 0

    def test_alle_true_herleidt_exact_de_filterset_zonder_paginering(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendor: uuid.UUID, tweede_vendor: uuid.UUID, opslag, admin_engine: Engine
    ) -> None:
        self._twee_kandidaten(administratie_id, beheerder_id, opslag)
        headers = _bearer(beheerder_id, rol="beheerder")
        # Service-laag: de filterset is exact wat de lijst zou tonen (sortering identiek), zonder paginering.
        alle = service.rijen_binnen_filter(tab="kandidaten")
        assert [r.vendor_id for r in alle] == [r.vendor_id for r in service.lijst(tab="kandidaten", per_pagina=1).rijen] + [
            r.vendor_id for r in service.lijst(tab="kandidaten", pagina=2, per_pagina=1).rijen
        ]
        assert service.rijen_binnen_filter(tab="kandidaten", q="transip") and all(
            r.vendor_id == tweede_vendor for r in service.rijen_binnen_filter(tab="kandidaten", q="transip")
        )
        assert service.rijen_binnen_filter(tab="actief") == []
        with pytest.raises(service.AutoboekKandidaatFout):
            service.rijen_binnen_filter(tab="bestaat-niet")

        # Verbergen mét alle:true + q: alleen Transip wordt verborgen.
        r = client.post(
            "/instellingen/autoboeken/kandidaten/verbergen",
            headers=headers,
            json={"alle": True, "tab": "kandidaten", "q": "transip", "reden": "eerst kijken"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["verborgen"] == 1 and [u["vendor_id"] for u in r.json()["uitkomsten"]] == [str(tweede_vendor)]
        assert client.get("/instellingen/autoboeken/kandidaten?tab=kandidaten", headers=headers).json()["totaal"] == 1

        # Aanzetten mét alle:true (zonder q): de resterende kandidaat — Transip zit niet meer in de filterset.
        r = client.post("/instellingen/autoboeken/kandidaten/aanzetten", headers=headers, json={"alle": True, "tab": "kandidaten"})
        assert r.status_code == 200, r.text
        assert r.json()["aangezet"] == 1 and r.json()["uitkomsten"][0]["vendor_id"] == str(vendor)
        assert r.json()["uitkomsten"][0]["leverancier_naam"] == "Ebbers Salarisadvies B.V."
        with scoped_session(administratie_id) as session:
            assert session.get(LeverancierVoorkeur, (administratie_id, vendor)).autoboeken_ingeschakeld is True
            assert session.get(LeverancierVoorkeur, (administratie_id, tweede_vendor)) is None
        # Onbekende tab in de selectie = dezelfde 404 als de lijst-GET geeft (`_vertaal`), niets gebeurd.
        assert client.post("/instellingen/autoboeken/kandidaten/aanzetten", headers=headers, json={"alle": True, "tab": "x"}).status_code == 404
        # Verbergen op een actieve rij = overgeslagen mét reden (verbergen geldt voor kandidaten).
        r = client.post(
            "/instellingen/autoboeken/kandidaten/verbergen",
            headers=headers,
            json={"items": [{"administratie_id": str(administratie_id), "vendor_id": str(vendor)}], "reden": "x"},
        )
        assert r.json()["uitkomsten"][0]["status"] == "overgeslagen" and "staat aan" in r.json()["uitkomsten"][0]["reden"]


class TestRolpoorten:
    @pytest.mark.parametrize("rol", ["boekhouding", "boekhouding_projecten"])
    def test_alleen_beheerder(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, rol: str) -> None:
        headers = _bearer(gescoopte_gebruiker, rol=rol)
        assert (
            client.post(
                "/instellingen/autoboeken/kandidaten/verbergen",
                headers=headers,
                json={"items": [{"administratie_id": str(administratie_id), "vendor_id": str(VENDOR)}], "reden": "x"},
            ).status_code
            == 403
        )
        assert client.get("/instellingen/autoboeken/kandidaten", headers=headers).status_code == 403
        assert client.get("/instellingen/autoboeken/stand", headers=headers).status_code == 403
        assert client.post("/instellingen/autoboeken/herbereken", headers=headers).status_code == 403
        assert client.put("/instellingen/autoboeken/instelling", headers=headers, json={"drempel_op_rij": 5}).status_code == 403
        assert (
            client.post(
                "/instellingen/autoboeken/kandidaten/aanzetten",
                headers=headers,
                json={"items": [{"administratie_id": str(administratie_id), "vendor_id": str(VENDOR)}]},
            ).status_code
            == 403
        )
