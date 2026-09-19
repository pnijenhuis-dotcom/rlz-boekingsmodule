# ruff: noqa: F811 — pytest-fixtures als parameters
"""Opdracht Peter 19-09 — Projecten: tab "Afsluiten? (N)" mét bulk-afsluiten en "Niet afsluiten".

Kandidaat-redenen deterministisch (stil N mnd per administratie / eindfactuur geboekt / naam zegt afgesloten / looptijd
verstreken;
geen activiteit = NIET stil), laatste activiteit + open posten per rij (chip let op, geen blokkade), bulk-uitkomst per rij
(gelukt / bron weigert mét reden / al afgesloten / geen toegang), "Niet afsluiten" mét verplichte reden onthouden tot
nieuwe
activiteit (audit), rechten (Beheerder + B+P handelen, Boekhouding leest alleen), stil-venster instelbaar per administratie,
CLI op dezelfde motor. De chip op Inzicht › Projecten leest dezelfde motor."""

from __future__ import annotations

import argparse
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.main import app
from app.projecten import afsluiten, kantoor
from app.projecten.cli_cmd import _afsluit_kandidaten
from app.projecten.models import ProjectRegelCache
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.projecten.conftest import FakeProjectClient
from tests.projecten.test_kantoorbreed import tweede_administratie  # noqa: F401
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)
VANDAAG = date(2026, 9, 19)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _regel(
    engine: Engine, aid, pid, soort: str, netto: str, datum: date, *, omschrijving: str | None = None, referentie=None
):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_regel_cache "
                "(id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag, datum, omschrijving, "
                "referentie) "
                "VALUES (:id, :aid, :doc, :soort, :pid, :netto, :datum, :oms, :ref)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": aid,
                "doc": uuid.uuid4(),
                "soort": soort,
                "pid": pid,
                "netto": netto,
                "datum": datum,
                "oms": omschrijving,
                "ref": referentie,
            },
        )


def _planning(engine: Engine, aid, pid, gid, datum: date) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.planning_toewijzing (administratie_id, gebruiker_id, project_id, datum, "
                "dagdeel, "
                "toegevoegd_door) VALUES (:aid, :gid, :pid, :d, 'heel', :gid)"
            ),
            {"aid": aid, "gid": gid, "pid": pid, "d": datum},
        )


def _open_inkoop(engine: Engine, aid, pid, netto: str) -> None:
    """Een inkoopdocument te_controleren mét een boekvoorstelregel op het project = 'inkoop nog niet geboekt'."""
    did = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, bestandsnaam, sha256_hash, opslag_pad, "
                "status) "
                "VALUES (:id, :aid, 'upload', 'f.pdf', :hash, :pad, 'te_controleren')"
            ),
            {"id": did, "aid": aid, "hash": uuid.uuid4().hex, "pad": f"x/{did}.pdf"},
        )
        conn.execute(text("INSERT INTO boekhouding.boekvoorstel (document_id) VALUES (:d)"), {"d": did})
        conn.execute(
            text(
                "INSERT INTO boekhouding.boekvoorstel_regel (id, document_id, volgnummer, project_id, netto_bedrag) "
                "VALUES (:id, :d, 1, :pid, :netto)"
            ),
            {"id": uuid.uuid4(), "d": did, "pid": pid, "netto": netto},
        )


def _spec_looptijd(engine: Engine, aid, pid, door, tot: date) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_specificatie (project_id, administratie_id, looptijd_tot, "
                "bijgewerkt_door) "
                "VALUES (:pid, :aid, :tot, :door)"
            ),
            {"pid": pid, "aid": aid, "tot": tot, "door": door},
        )


def _audit(aid, actie: str) -> list[AuditEvent]:
    with scoped_session(aid) as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.actie == actie)))


class TestRedenenPuur:
    def test_stil_grens_zes_maanden_en_geen_activiteit_is_niet_stil(self) -> None:
        act = afsluiten.Activiteit("inkoop", date(2026, 3, 19), Decimal("100"), "F-1")
        redenen, tekst = afsluiten.bepaal_redenen(
            naam="26010 A", laatste=act, jongste_verkoop=None, looptijd_tot=None, vandaag=VANDAAG, stil_maanden=6
        )
        assert redenen == ("stil",) and "venster 6 mnd" in tekst
        recenter = afsluiten.Activiteit("inkoop", date(2026, 3, 20))
        assert (
            afsluiten.bepaal_redenen(
                naam="26010 A",
                laatste=recenter,
                jongste_verkoop=None,
                looptijd_tot=None,
                vandaag=VANDAAG,
                stil_maanden=6,
            )[0]
            == ()
        )
        # Korter venster per administratie: 3 maanden → 20 maart is wél stil.
        assert afsluiten.bepaal_redenen(
            naam="26010 A", laatste=recenter, jongste_verkoop=None, looptijd_tot=None, vandaag=VANDAAG, stil_maanden=3
        )[0] == ("stil",)
        # Geen activiteit bekend = leeftijd onbekend → géén stil-reden (een nieuw project mag nooit "afsluiten?" heten), wél tekst.
        redenen, tekst = afsluiten.bepaal_redenen(
            naam="26011 B", laatste=None, jongste_verkoop=None, looptijd_tot=None, vandaag=VANDAAG, stil_maanden=6
        )
        assert redenen == () and "telt niet als stil" in tekst

    def test_eindfactuur_naam_en_looptijd(self) -> None:
        eind = ProjectRegelCache(
            id=uuid.uuid4(),
            administratie_id=uuid.uuid4(),
            rlz_document_id=uuid.uuid4(),
            soort="verkoop",
            project_id=uuid.uuid4(),
            netto_bedrag=Decimal("1"),
            omschrijving="Eindafrekening steiger fase 2",
            referentie="VF-9",
        )
        assert afsluiten.is_eindfactuur(eind) is True
        assert (
            afsluiten.is_eindfactuur(
                ProjectRegelCache(
                    id=uuid.uuid4(),
                    administratie_id=uuid.uuid4(),
                    rlz_document_id=uuid.uuid4(),
                    soort="verkoop",
                    project_id=uuid.uuid4(),
                    netto_bedrag=Decimal("1"),
                    omschrijving="Termijn 3",
                    referentie="VF-8",
                )
            )
            is False
        )
        act = afsluiten.Activiteit("verkoop", VANDAAG - timedelta(days=10))
        redenen, tekst = afsluiten.bepaal_redenen(
            naam="Afgesloten 26012 Tilburg (van Kasteren)",
            laatste=act,
            jongste_verkoop=eind,
            looptijd_tot=VANDAAG - timedelta(days=1),
            vandaag=VANDAAG,
            stil_maanden=6,
        )
        assert redenen == ("eindfactuur", "naam_afgesloten", "looptijd_verstreken")
        assert "eindfactuur geboekt" in tekst and "naam zegt afgesloten" in tekst and "looptijd tot" in tekst
        # Looptijd vandaag = nog niet verstreken; "afgesloten" midden in de naam telt niet.
        assert (
            afsluiten.bepaal_redenen(
                naam="26013 Afgesloten-weg Ede",
                laatste=act,
                jongste_verkoop=None,
                looptijd_tot=VANDAAG,
                vandaag=VANDAAG,
                stil_maanden=6,
            )[0]
            == ()
        )


class TestMotorOpDatabase:
    def test_kandidaten_redenen_laatste_activiteit_open_posten_en_sortering(
        self, admin_engine: Engine, administratie_id, beheerder_id
    ) -> None:
        zzper = maak_gebruiker(admin_engine, "zzper", "Irfan O.")
        naam_af = maak_project(admin_engine, administratie_id, "Afgesloten 26012 Tilburg (van Kasteren)")
        stil_eind = maak_project(admin_engine, administratie_id, "25017 Arnhem (Kudo)")
        druk = maak_project(admin_engine, administratie_id, "26014 Breda (Moeskops)")
        leeg = maak_project(admin_engine, administratie_id, "26099 Nieuw (gisteren)")
        looptijd = maak_project(admin_engine, administratie_id, "25050 Ede (Welling)")
        _regel(
            admin_engine,
            administratie_id,
            naam_af,
            "inkoop",
            "500.00",
            VANDAAG - timedelta(days=17),
            referentie="IF-77",
        )
        _regel(admin_engine, administratie_id, stil_eind, "inkoop", "200.00", VANDAAG - timedelta(days=300))
        _regel(
            admin_engine,
            administratie_id,
            stil_eind,
            "verkoop",
            "12000.00",
            VANDAAG - timedelta(days=250),
            omschrijving="Eindfactuur fase 2",
            referentie="VF-201",
        )
        _regel(
            admin_engine,
            administratie_id,
            stil_eind,
            "verkoop",
            "3000.00",
            VANDAAG - timedelta(days=280),
            omschrijving="Termijn 2",
        )
        _open_inkoop(admin_engine, administratie_id, stil_eind, "150.00")
        _planning(admin_engine, administratie_id, druk, zzper, VANDAAG - timedelta(days=3))
        _regel(admin_engine, administratie_id, looptijd, "inkoop", "50.00", VANDAAG - timedelta(days=20))
        _spec_looptijd(admin_engine, administratie_id, looptijd, beheerder_id, VANDAAG - timedelta(days=5))

        with scoped_session(administratie_id) as session:
            rijen = {
                k.project_id: k
                for k in afsluiten.kandidaten_voor_administratie(
                    session, administratie_id=administratie_id, administratie_naam="Universal", vandaag=VANDAAG
                )
            }
        assert rijen[naam_af].redenen == ("naam_afgesloten",) and rijen[naam_af].kandidaat
        assert (
            rijen[naam_af].laatste_activiteit.soort == "inkoop"
            and rijen[naam_af].laatste_activiteit.boekstuk == "IF-77"
        )
        assert rijen[naam_af].laatste_activiteit.bedrag == Decimal("500.00") and rijen[naam_af].stil_dagen == 17
        assert rijen[stil_eind].redenen == ("stil", "eindfactuur") and "VF-201" in rijen[stil_eind].reden_tekst
        assert rijen[stil_eind].laatste_activiteit.soort == "verkoop" and rijen[
            stil_eind
        ].laatste_activiteit.datum == VANDAAG - timedelta(days=250)
        assert rijen[stil_eind].open_posten.inkoop_niet_geboekt == 1 and rijen[
            stil_eind
        ].open_posten.inkoop_niet_geboekt_bedrag == Decimal("150.00")
        assert rijen[stil_eind].open_posten.let_op is True and rijen[naam_af].open_posten.let_op is False
        assert rijen[druk].redenen == () and rijen[druk].laatste_activiteit.soort == "planning"
        assert rijen[leeg].redenen == () and rijen[leeg].laatste_activiteit is None
        assert rijen[looptijd].redenen == ("looptijd_verstreken",)
        # Sortering: "Afgesloten …" eerst, dan meeste redenen.
        gesorteerd = afsluiten._sorteer([k for k in rijen.values() if k.redenen])
        assert [k.project_id for k in gesorteerd] == [naam_af, stil_eind, looptijd]

    def test_eindfactuur_meerdere_regels_op_jongste_datum_is_deterministisch(
        self, admin_engine: Engine, administratie_id
    ) -> None:
        """Nameting 19-09: een verkoopfactuur heeft meerdere regels op dezelfde datum — de reden `eindfactuur` mag niet
        afhangen van de rijvolgorde van de database (replica ≠ primary). Eén regel mét de tekst = reden; een OUDERE
        eindafrekening mét jongere termijnen erna (casus Universal 25017) = géén reden."""
        meerregelig = maak_project(admin_engine, administratie_id, "25018 Arnhem (Kudo) meerregelig")
        oud_eind = maak_project(admin_engine, administratie_id, "25017 Arnhem (Kudo) oude eindafrekening")
        d = VANDAAG - timedelta(days=100)
        # Meerregelig: de niet-eindfactuurregel wordt EERST ingevoegd (heap-volgorde zou 'm anders als eerste geven).
        _regel(
            admin_engine,
            administratie_id,
            meerregelig,
            "verkoop",
            "500.00",
            d,
            omschrijving="Transport",
            referentie="VF-300",
        )
        _regel(
            admin_engine,
            administratie_id,
            meerregelig,
            "verkoop",
            "9000.00",
            d,
            omschrijving="Eindfactuur fase 3",
            referentie="VF-300",
        )
        _regel(
            admin_engine,
            administratie_id,
            meerregelig,
            "verkoop",
            "10.00",
            d,
            omschrijving="Kraan",
            referentie="VF-300",
        )
        # 25017-casus: eindafrekening 06-03, daarna twee termijnen — jongste regel is geen eindfactuur.
        _regel(
            admin_engine,
            administratie_id,
            oud_eind,
            "verkoop",
            "13670.00",
            VANDAAG - timedelta(days=197),
            omschrijving="Eindafrekening",
            referentie="808010670",
        )
        _regel(
            admin_engine,
            administratie_id,
            oud_eind,
            "verkoop",
            "10000.00",
            VANDAAG - timedelta(days=108),
            omschrijving="Hefsteiger compleet 2e van 2 termijnen)",
            referentie="808010818",
        )
        with scoped_session(administratie_id) as session:
            for _ in range(3):  # herhaling = zelfde uitkomst
                rijen = {
                    k.project_id: k
                    for k in afsluiten.kandidaten_voor_administratie(
                        session, administratie_id=administratie_id, administratie_naam="Universal", vandaag=VANDAAG
                    )
                }
                assert rijen[meerregelig].redenen == ("eindfactuur",) and "VF-300" in rijen[meerregelig].reden_tekst
                assert rijen[meerregelig].laatste_activiteit.datum == d
                assert rijen[oud_eind].redenen == () and rijen[oud_eind].laatste_activiteit.boekstuk == "808010818"

    def test_kantoorbreed_chip_leest_dezelfde_motor(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        pid = maak_project(admin_engine, administratie_id, "Afgesloten 26051 Opijnen (van Kessel)")
        _regel(admin_engine, administratie_id, pid, "inkoop", "10.00", VANDAAG - timedelta(days=2))
        r = client.get("/projecten/kantoorbreed", headers=_bearer(beheerder_id))
        assert r.status_code == 200, r.text
        rij = next(x for x in r.json()["rijen"] if x["project_id"] == str(pid))
        assert rij["kandidaat_afsluiten"] is True and "naam zegt afgesloten" in rij["kandidaat_reden"]
        assert r.json()["tellers"]["kandidaat_afsluiten"] == 1


class TestApiLijstEnNietAfsluiten:
    def test_lijst_filter_zoek_en_niet_afsluiten_onthouden_tot_nieuwe_activiteit(
        self, admin_engine: Engine, administratie_id, beheerder_id
    ) -> None:
        zzper = maak_gebruiker(admin_engine, "zzper", "Irfan O.")
        a = maak_project(admin_engine, administratie_id, "Afgesloten 26012 Tilburg (van Kasteren)")
        b = maak_project(admin_engine, administratie_id, "25017 Arnhem (Kudo)")
        _regel(admin_engine, administratie_id, a, "inkoop", "1.00", VANDAAG - timedelta(days=1))
        _regel(admin_engine, administratie_id, b, "inkoop", "1.00", VANDAAG - timedelta(days=400))
        kop = _bearer(beheerder_id)
        r = client.get("/projecten/afsluit-kandidaten", headers=kop)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["totaal"] == 2 and d["tellers"]["kandidaten"] == 2 and d["tellers"]["uitgesteld"] == 0
        assert d["tellers"]["per_reden"] == {
            "stil": 1,
            "eindfactuur": 0,
            "naam_afgesloten": 1,
            "looptijd_verstreken": 0,
        }
        assert d["rijen"][0]["project_id"] == str(a)  # "Afgesloten …" bovenaan
        assert (
            d["redenen"] == ["stil", "eindfactuur", "naam_afgesloten", "looptijd_verstreken"]
            and d["reden_labels"]["stil"] == "geen activiteit"
        )
        assert d["stil_maanden"] is None
        # Filter op reden + zoekveld + één administratie (deeplink) → stil_maanden gevuld.
        r = client.get("/projecten/afsluit-kandidaten", params={"reden": "stil"}, headers=kop)
        assert [x["project_id"] for x in r.json()["rijen"]] == [str(b)]
        r = client.get(
            "/projecten/afsluit-kandidaten",
            params={"q": "kudo", "administratie_id": str(administratie_id)},
            headers=kop,
        )
        assert r.json()["totaal"] == 1 and r.json()["stil_maanden"] == 6
        assert client.get("/projecten/afsluit-kandidaten", params={"reden": "onzin"}, headers=kop).status_code == 422

        # "Niet afsluiten" zonder reden = 422 (niets verdwijnt stil); mét reden → weg uit kandidaten, zichtbaar onder uitgesteld.
        assert (
            client.post(
                f"/projecten/{administratie_id}/{b}/niet-afsluiten", json={"reden": ""}, headers=kop
            ).status_code
            == 422
        )
        r = client.post(
            f"/projecten/{administratie_id}/{b}/niet-afsluiten",
            json={"reden": "Nog garantiewerk in oktober"},
            headers=kop,
        )
        assert r.status_code == 200, r.text
        assert (
            r.json()["reden"] == "Nog garantiewerk in oktober"
            and r.json()["laatste_activiteit"] == (VANDAAG - timedelta(days=400)).isoformat()
        )
        d = client.get("/projecten/afsluit-kandidaten", headers=kop).json()
        assert d["tellers"] == {
            "kandidaten": 1,
            "uitgesteld": 1,
            "administraties": 1,
            "per_reden": {"stil": 0, "eindfactuur": 0, "naam_afgesloten": 1, "looptijd_verstreken": 0},
            "let_op": 0,
        }
        u = client.get("/projecten/afsluit-kandidaten", params={"toon_uitgesteld": "true"}, headers=kop).json()
        assert [x["project_id"] for x in u["rijen"]] == [str(b)] and u["rijen"][0]["uitstel"][
            "reden"
        ] == "Nog garantiewerk in oktober"
        audit = _audit(administratie_id, "project_afsluiten_uitgesteld")
        assert (
            len(audit) == 1
            and audit[0].nieuwe_waarde["reden"] == "Nog garantiewerk in oktober"
            and audit[0].oude_waarde is None
        )
        # Nieuwe activiteit ná het snapshot → opnieuw kandidaat.
        _planning(admin_engine, administratie_id, b, zzper, VANDAAG - timedelta(days=200))
        d = client.get("/projecten/afsluit-kandidaten", params={"reden": "stil"}, headers=kop).json()
        assert [x["project_id"] for x in d["rijen"]] == [str(b)] and d["rijen"][0]["uitstel"] is None
        # Opnieuw uitstellen = upsert mét oud→nieuw in het audit-spoor.
        client.post(f"/projecten/{administratie_id}/{b}/niet-afsluiten", json={"reden": "Toch nog even"}, headers=kop)
        audit = _audit(administratie_id, "project_afsluiten_uitgesteld")
        assert len(audit) == 2 and any(
            e.oude_waarde and e.oude_waarde["reden"] == "Nog garantiewerk in oktober" for e in audit
        )

    def test_rechten_boekhouding_leest_maar_handelt_niet(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker
    ) -> None:
        a = maak_project(admin_engine, administratie_id, "Afgesloten 26012 Tilburg (van Kasteren)")
        _regel(admin_engine, administratie_id, a, "inkoop", "1.00", VANDAAG - timedelta(days=1))
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.get("/projecten/afsluit-kandidaten", headers=kop).json()["tellers"]["kandidaten"] == 1
        assert (
            client.post(
                f"/projecten/{administratie_id}/{a}/niet-afsluiten", json={"reden": "x"}, headers=kop
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/projecten/afsluiten-bulk",
                json={"items": [{"administratie_id": str(administratie_id), "project_id": str(a)}]},
                headers=kop,
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"/projecten/{administratie_id}/afsluit-instelling", json={"stil_maanden": 3}, headers=kop
            ).status_code
            == 403
        )
        # Boekhouding+Projecten mag wél (Haci/Iris-patroon).
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci Y.")
        from app.auth import service as auth_service

        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=administratie_id)
        r = client.post(
            f"/projecten/{administratie_id}/{a}/niet-afsluiten",
            json={"reden": "Loopt nog"},
            headers=_bearer(bp, rol="boekhouding_projecten"),
        )
        assert r.status_code == 200, r.text
        # Klant-accordeur heeft geen kantoorrol → 403 op de lijst.
        acc = maak_gebruiker(admin_engine, "klant_accordeur", "Klant K.")
        assert (
            client.get("/projecten/afsluit-kandidaten", headers=_bearer(acc, rol="klant_accordeur")).status_code == 403
        )

    def test_stil_venster_per_administratie(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        pid = maak_project(admin_engine, administratie_id, "25017 Arnhem (Kudo)")
        _regel(admin_engine, administratie_id, pid, "inkoop", "1.00", VANDAAG - timedelta(days=100))
        kop = _bearer(beheerder_id)
        assert client.get(f"/projecten/{administratie_id}/afsluit-instelling", headers=kop).json() == {
            "stil_maanden": 6
        }
        assert (
            client.put(
                f"/projecten/{administratie_id}/afsluit-instelling", json={"stil_maanden": 0}, headers=kop
            ).status_code
            == 422
        )
        assert (
            client.put(
                f"/projecten/{administratie_id}/afsluit-instelling", json={"stil_maanden": 37}, headers=kop
            ).status_code
            == 422
        )
        r = client.put(f"/projecten/{administratie_id}/afsluit-instelling", json={"stil_maanden": 3}, headers=kop)
        assert r.status_code == 200 and r.json() == {"stil_maanden": 3}
        # Audit zonder administratie_id (platform-tabel) — platform-breed lezen.
        with scoped_session(None) as session:
            ev = list(
                session.scalars(select(AuditEvent).where(AuditEvent.actie == "project_afsluit_stil_maanden_gewijzigd"))
            )
        assert (
            len(ev) == 1
            and ev[0].oude_waarde == {"project_afsluit_stil_maanden": 6}
            and ev[0].nieuwe_waarde == {"project_afsluit_stil_maanden": 3}
        )
        d = client.get(
            "/projecten/afsluit-kandidaten", params={"administratie_id": str(administratie_id)}, headers=kop
        ).json()
        assert (
            d["stil_maanden"] == 3
            and d["tellers"]["kandidaten"] == 1
            and d["rijen"][0]["redenen"] == ["stil"]
            and d["rijen"][0]["stil_maanden"] == 3
        )


class TestBulkAfsluiten:
    def test_uitkomst_per_rij_gelukt_bron_weigert_al_afgesloten_geen_toegang(
        self, admin_engine: Engine, administratie_id, tweede_administratie, beheerder_id, monkeypatch
    ) -> None:
        fake = FakeProjectClient()
        res_a = kantoor.maak_project_aan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            projectnummer="26012",
            plaats="Tilburg",
            opdrachtgever="Kasteren",
            client=fake,
        )
        res_b = kantoor.maak_project_aan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            projectnummer="26051",
            plaats="Opijnen",
            opdrachtgever="Kessel",
            client=fake,
        )
        res_c = kantoor.maak_project_aan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            projectnummer="26064",
            plaats="Apeldoorn",
            opdrachtgever="Kuijer",
            client=fake,
        )
        ander = maak_project(admin_engine, tweede_administratie, "Kantoorpand Eindhoven")
        # C is al afgesloten (0160-flow) — bulk meldt "al afgesloten", geen tweede PUT.
        from app.projecten import status as status_service

        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=res_c.rlz_project_id, actor_id=beheerder_id, client=fake
        )
        puts_voor = fake.put_project_aanroepen

        weigeraar = FakeProjectClient()
        weigeraar.projects = fake.projects
        weigeraar.negeer_is_active = True
        # Testseam: één bron-client per administratie (`_bron_client`). Eerst A + C + buiten-scope + onbekend met de
        # gewone fake;
        # daarna B apart mét de weigeraar (negeer_is_active zou anders óók A raken).
        monkeypatch.setattr(afsluiten, "_bron_client", lambda aid: (fake, None))
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Iris V.")
        from app.auth import service as auth_service

        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=administratie_id)
        kop = _bearer(bp, rol="boekhouding_projecten")
        r = client.post(
            "/projecten/afsluiten-bulk",
            json={
                "items": [
                    {"administratie_id": str(administratie_id), "project_id": str(res_a.rlz_project_id)},
                    {"administratie_id": str(administratie_id), "project_id": str(res_c.rlz_project_id)},
                    {"administratie_id": str(tweede_administratie), "project_id": str(ander)},
                    {"administratie_id": str(administratie_id), "project_id": str(uuid.uuid4())},
                ],
                "reden": "Opgeleverd — bulk 19-09",
            },
            headers=kop,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert [u["uitkomst"] for u in d["uitkomsten"]] == ["gelukt", "al_afgesloten", "geen_toegang", "niet_gevonden"]
        assert d["gelukt"] == 1 and d["mislukt"] == 3
        assert (
            d["uitkomsten"][0]["naam"] == "26012 Tilburg (Kasteren)"
            and d["uitkomsten"][2]["detail"] == "Administratie buiten je scope"
        )
        assert fake.projects[str(res_a.rlz_project_id)]["IsActive"] is False
        assert fake.put_project_aanroepen == puts_voor + 1  # alleen A kreeg een PUT
        audit = _audit(administratie_id, "project_afgesloten")
        assert len(audit) == 2 and any(e.nieuwe_waarde["afsluit_reden"] == "Opgeleverd — bulk 19-09" for e in audit)

        # B: RLZ neemt IsActive niet over → bron weigert mét reden, status ongewijzigd.
        monkeypatch.setattr(afsluiten, "_bron_client", lambda aid: (weigeraar, None))
        r = client.post(
            "/projecten/afsluiten-bulk",
            json={"items": [{"administratie_id": str(administratie_id), "project_id": str(res_b.rlz_project_id)}]},
            headers=kop,
        )
        assert (
            r.json()["uitkomsten"][0]["uitkomst"] == "bron_weigert"
            and "RLZ wint" in r.json()["uitkomsten"][0]["detail"]
        )
        with scoped_session(administratie_id) as session:
            from app.sync.models import ProjectCache

            assert session.get(ProjectCache, (res_b.rlz_project_id, administratie_id)).status == "lopend"
        # Geen credential = leesbare reden per rij, geen 500.
        monkeypatch.setattr(afsluiten, "_bron_client", lambda aid: (None, "Geen RLZ-login voor deze administratie"))
        r = client.post(
            "/projecten/afsluiten-bulk",
            json={"items": [{"administratie_id": str(administratie_id), "project_id": str(res_b.rlz_project_id)}]},
            headers=kop,
        )
        assert r.json()["uitkomsten"][0] == {
            "administratie_id": str(administratie_id),
            "project_id": str(res_b.rlz_project_id),
            "naam": "26051 Opijnen (Kessel)",
            "uitkomst": "bron_weigert",
            "detail": "Geen RLZ-login voor deze administratie",
        }

    def test_bulk_leeg_is_422_en_boekhouding_403(self, administratie_id, beheerder_id, gescoopte_gebruiker) -> None:
        assert (
            client.post("/projecten/afsluiten-bulk", json={"items": []}, headers=_bearer(beheerder_id)).status_code
            == 422
        )
        r = client.post(
            "/projecten/afsluiten-bulk",
            json={"items": [{"administratie_id": str(administratie_id), "project_id": str(uuid.uuid4())}]},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 403


class TestCli:
    def test_cli_rapport_op_dezelfde_motor(self, admin_engine: Engine, administratie_id, beheerder_id, capsys) -> None:
        a = maak_project(admin_engine, administratie_id, "Afgesloten 26012 Tilburg (van Kasteren)")
        b = maak_project(admin_engine, administratie_id, "25017 Arnhem (Kudo)")
        _regel(
            admin_engine, administratie_id, a, "inkoop", "500.00", date.today() - timedelta(days=17), referentie="IF-77"
        )
        _regel(
            admin_engine,
            administratie_id,
            b,
            "verkoop",
            "1.00",
            date.today() - timedelta(days=400),
            omschrijving="Slotfactuur",
        )
        afsluiten.stel_afsluiten_uit(
            administratie_id=administratie_id, project_id=b, actor_id=beheerder_id, reden="Garantie loopt"
        )
        rc = _afsluit_kandidaten(argparse.Namespace(administratie=str(administratie_id), maanden=None, alles=False))
        uit = capsys.readouterr().out
        assert rc == 0
        assert "1 kandidaat, 1 uitgesteld" in uit and "naam zegt afgesloten 1" in uit
        assert "KANDIDAAT " in uit and "Afgesloten 26012 Tilburg" in uit and "laatste=inkoop" in uit and "IF-77" in uit
        assert "UITGESTELD" in uit and "Garantie loopt" in uit and "redenen=stil,eindfactuur" in uit
        assert "nooit automatisch" in uit
