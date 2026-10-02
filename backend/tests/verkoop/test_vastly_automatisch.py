# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Vastly-verkoopfacturen volledig automatisch (Peter 28/29-09 "moet gewoon als omzet geboekt worden, punt"; migratie
0172; herzien 01-10 "100 % auto zonder menselijke tussenstap … hou het simpel", migratie 0173; BESLISSINGEN
"VASTLY-VERKOOP — ADMINISTRATIE-ID UIT DE UBL ALS EERSTE BRON, TERUGVAL EN HISTORIE-AFLEIDING UIT (Peter 01-10)"):

1. entiteit → administratie: administratie-id `RLZ-ADMINISTRATIE:<uuid>` uit de UBL als EERSTE bron (bron 'ubl', rij bron
   'ubl'), daarna KvK → identiteit/koppeling; een BESTAANDE mens-koppeling op naam wordt nog gelezen, er komen geen
   nieuwe bij (geen koppelroute); onbekend/onbekend id = geregistreerd zonder administratie, NIET in de verzamelbak, wél
   de bevinding "melden bij Vastly";
2. omzetrekening: uitsluitend `AccountingCost` — zonder (bekende) code weigert het autoboek-pad `omzetrekening_ontbreekt`,
   nooit een afgeleide rekening (guard op het afwezig-pad: ook mét een bestaande historie-rij);
3. btw = standaardtarief van de administratie bij ambiguïteit (test in test_autoboeken.py);
4. autoboek zonder drempels (test_autoboeken.py) + heraanbied-motor (dry-run/echt, CLI-vormen uit het meetrecept);
5. UBL nooit door de AI (guards);
6. reconciliatieblok `vastly_verkoop` (drie soorten; handeling alleen "Opnieuw aanbieden") + dagteller + routes
   (koppel-/rekening-kiezen-routes bestaan niet meer)."""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as documenten_boeken
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.intake import verzamelbak
from app.intake.verwerking import verwerk_eml
from app.intercompany.identiteit import naam_norm
from app.intercompany.models import AdministratieIdentiteit
from app.main import app
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.reconciliatie.run import Verzamelaar
from app.security.tokens import create_access_token
from app.verkoop import entiteit, heraanbieden, omzetrekening
from app.verkoop import reconciliatie as vastly_reconciliatie
from app.verkoop.models import VastlyEntiteitKoppeling, VastlyOmzetrekening
from tests.intake.conftest import bouw_eml
from tests.verkoop.conftest import (
    OMZET_LEDGER_ID,
    FakeVerkoopClient,
    bouw_vastly_verkoop_ubl,
    upload_verkoopfactuur,
)

KVK = "87654321"
LEVERANCIER = "Rubicon Investments B.V."
client = TestClient(app)


def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeVerkoopClient())


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}).scalar_one()


def _verwerk(inhoud: bytes, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str = "factuur-RUB-2026-0099-ubl.xml"):
    return verwerk_eml(bouw_eml(bijlagen=[(naam, inhoud, "application", "xml")]), actor_id=actor_id, opslag=opslag)


@pytest.fixture
def vastgoed_administratie(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.administratie SET is_vastgoed = true, naam = :n WHERE id = :id"), {"id": administratie_id, "n": LEVERANCIER})
    return administratie_id


@pytest.fixture
def identiteit_kvk(vastgoed_administratie: uuid.UUID) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(AdministratieIdentiteit(administratie_id=vastgoed_administratie, kvk=KVK, naam=LEVERANCIER, naam_norm="rubicon investments", bron="rlz"))


def _headers(gid: uuid.UUID, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gid, rol=rol)}"}


# ---- 1. entiteitenregister ------------------------------------------------------------------------------------------


class TestEntiteitenregister:
    def test_kvk_via_identiteit_wijst_toe_en_legt_koppeling_vast(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie, identiteit_kvk
    ) -> None:
        _patch_client(monkeypatch)
        r = _verwerk(bouw_vastly_verkoop_ubl(leverancier="Andere Schrijfwijze Rubicon BV", leverancier_kvk=KVK), gescoopte_gebruiker, opslag)
        [b] = r.bijlagen
        assert b.uitkomst == "toegewezen" and "identiteit_kvk" in (b.detail or "")
        # Nooit een mens: de intake-hook boekt direct (rekeningschema + 21 % uniek).
        assert _status(admin_engine, b.document_id) == "geboekt"
        with scoped_session(None) as session:
            [k] = session.query(VastlyEntiteitKoppeling).all()
            assert (k.sleutel_soort, k.sleutel, k.administratie_id, k.bron) == ("kvk", KVK, vastgoed_administratie, "identiteit")

    def test_naam_alleen_wijst_nooit_toe_en_staat_niet_in_de_verzamelbak(
        self, gescoopte_gebruiker, admin_engine, opslag, vastgoed_administratie
    ) -> None:
        r = _verwerk(bouw_vastly_verkoop_ubl(leverancier=LEVERANCIER), gescoopte_gebruiker, opslag)
        [b] = r.bijlagen
        assert b.uitkomst == "entiteit_niet_gekoppeld"
        assert (b.detail or "").startswith("vastly_entiteit_niet_gekoppeld: naam=rubicon investments|weergave=Rubicon Investments B.V.")
        with scoped_session(None) as session:
            d = session.get(Document, b.document_id)
            assert d is not None and d.administratie_id is None and d.status == DocumentStatus.NIET_TOEGEWEZEN  # niets verdwijnt
        assert all(i.document_id != b.document_id for i in verzamelbak.lijst_verzamelbak()), "Peter: niet in de verzamelbak"
        assert [k.document_id for k in heraanbieden.vind_niet_gekoppeld()] == [b.document_id]

    def test_administratie_id_uit_ubl_is_eerste_bron_zonder_kvk(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie
    ) -> None:
        """01-10: natuurlijke persoon zonder KvK (Van Rooijen) — het platform-administratie-id in de UBL koppelt zonder mens;
        registerrij op de naam-sleutel mét bron 'ubl'; direct geboekt, nul mens-stappen."""
        _patch_client(monkeypatch)
        ubl = bouw_vastly_verkoop_ubl(leverancier="B. van Rooijen", factuurnummer="BG-2026-0026", platform_administratie_id=str(vastgoed_administratie))
        [b] = _verwerk(ubl, gescoopte_gebruiker, opslag, naam="factuur-BG-2026-0026-ubl.xml").bijlagen
        assert b.uitkomst == "toegewezen" and (b.detail or "").startswith("entiteitenregister:ubl → ")
        assert _status(admin_engine, b.document_id) == "geboekt"
        with scoped_session(None) as session:
            [k] = session.query(VastlyEntiteitKoppeling).all()
            assert (k.sleutel_soort, k.sleutel, k.administratie_id, k.bron) == ("naam", "b van rooijen", vastgoed_administratie, "ubl")

    def test_administratie_id_wint_van_kvk_en_bestaande_rij_blijft(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie, identiteit_kvk
    ) -> None:
        _patch_client(monkeypatch)
        ubl = bouw_vastly_verkoop_ubl(leverancier=LEVERANCIER, leverancier_kvk=KVK, platform_administratie_id=str(vastgoed_administratie))
        [b] = _verwerk(ubl, gescoopte_gebruiker, opslag).bijlagen
        assert b.uitkomst == "toegewezen" and "entiteitenregister:ubl" in (b.detail or "")
        with scoped_session(None) as session:
            [k] = session.query(VastlyEntiteitKoppeling).all()
            assert (k.sleutel_soort, k.sleutel, k.bron) == ("kvk", KVK, "ubl")
            # Een bestaande rij wordt nooit stil overschreven: de UBL wint voor dít document, de rij blijft.
            besluit = entiteit.resolve_administratie(session, entiteit.EntiteitSleutels(kvk=KVK, naam_norm=None, weergave=None, administratie_id=vastgoed_administratie, administratie_id_ruw=str(vastgoed_administratie)))
            assert besluit.bron == "ubl"
            assert session.query(VastlyEntiteitKoppeling).count() == 1

    @pytest.mark.parametrize("ruw", [str(uuid.UUID(int=7)), "geen-uuid", ""])
    def test_onbekend_administratie_id_weigert_zichtbaar_en_valt_nooit_terug_op_kvk(
        self, gescoopte_gebruiker, admin_engine, opslag, vastgoed_administratie, identiteit_kvk, ruw
    ) -> None:
        """Koppelcontract §2d-notitie 01-10 punt 3: een id dat de module niet kent = zichtbaar weigeren, nooit stil een andere
        administratie — óók niet via de (bekende) KvK."""
        ubl = bouw_vastly_verkoop_ubl(leverancier=LEVERANCIER, leverancier_kvk=KVK, factuurnummer="VF-X", platform_administratie_id=ruw)
        [b] = _verwerk(ubl, gescoopte_gebruiker, opslag, naam="vf-x-ubl.xml").bijlagen
        assert b.uitkomst == "entiteit_niet_gekoppeld", b
        assert (b.detail or "").startswith("vastly_entiteit_niet_gekoppeld: kvk=87654321|naam=rubicon investments|weergave=Rubicon Investments B.V.")
        if ruw:
            assert f"administratie_id={ruw}" in (b.detail or "")
        with scoped_session(None) as session:
            d = session.get(Document, b.document_id)
            assert d is not None and d.administratie_id is None and d.status == DocumentStatus.NIET_TOEGEWEZEN
            assert session.query(VastlyEntiteitKoppeling).count() == 0
        assert all(i.document_id != b.document_id for i in verzamelbak.lijst_verzamelbak())

    def test_bestaande_mens_koppeling_op_naam_wordt_nog_gelezen_maar_niet_meer_gemaakt(self, gescoopte_gebruiker, vastgoed_administratie) -> None:
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            session.add(VastlyEntiteitKoppeling(sleutel_soort="naam", sleutel=naam_norm(LEVERANCIER), administratie_id=vastgoed_administratie, bron=entiteit.BRON_MENS, weergave=LEVERANCIER))
            session.flush()
            besluit = entiteit.resolve_administratie(session, entiteit.EntiteitSleutels(kvk=None, naam_norm="rubicon investments", weergave=None))
            assert (besluit.administratie_id, besluit.bron) == (vastgoed_administratie, "koppeling_naam")
            # Geen KvK, geen id, geen bestaande rij → weigering mét reden; niets geschreven (geen mens-route meer).
            ander = entiteit.resolve_administratie(session, entiteit.EntiteitSleutels(kvk=None, naam_norm="iemand anders", weergave="Iemand Anders"))
            assert ander.administratie_id is None and ander.weigering == entiteit.WEIGERING_GEEN_ID_GEEN_KVK
            assert "geen administratie-id en geen bekende KvK — melden bij Vastly" in entiteit.weigering_tekst(ander.sleutels, ander.weigering)
            assert session.query(VastlyEntiteitKoppeling).count() == 1
        assert not hasattr(entiteit, "koppel_entiteit") and not hasattr(heraanbieden, "heraanbied_voor_sleutel")

    def test_reden_roundtrip(self) -> None:
        s = entiteit.EntiteitSleutels(kvk=KVK, naam_norm="rubicon investments", weergave=LEVERANCIER)
        assert entiteit.sleutels_uit_reden(s.als_reden()) == s
        aid = uuid.uuid4()
        met_id = entiteit.EntiteitSleutels(kvk=None, naam_norm="b van rooijen", weergave="B. van Rooijen", administratie_id=aid, administratie_id_ruw=str(aid))
        assert met_id.als_reden().endswith(f"|administratie_id={aid}") and entiteit.sleutels_uit_reden(met_id.als_reden()) == met_id
        ongeldig = entiteit.EntiteitSleutels(kvk=None, naam_norm="x", weergave=None, administratie_id=None, administratie_id_ruw="geen-uuid")
        assert entiteit.sleutels_uit_reden(ongeldig.als_reden()) == ongeldig
        assert entiteit.sleutels_uit_reden("vastly_verkoop_zonder_eenduidige_entiteit").primair is None


# ---- 2. omzetrekening ----------------------------------------------------------------------------------------------


class TestOmzetrekening:
    @pytest.mark.parametrize(
        ("omschrijving", "soort"),
        [("Huur september 2026", "huur"), ("Voorschot servicekosten", "servicekosten"), ("Waarborgsom", "waarborg"), ("Parkeerplaats", "overig"), (None, "overig"), ("Servicekosten huur", "servicekosten")],
    )
    def test_classificatie_is_pure_tekst(self, omschrijving, soort) -> None:
        assert omzetrekening.classificeer_regel(omschrijving) == soort

    def test_zonder_code_nooit_afgeleid_ook_niet_uit_een_bestaande_historie_rij(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie
    ) -> None:
        """Guard afwezig-pad (opdracht 01-10 punt 4): precies één omzetrekening 8000 in het schema én een rij van 29-09 in
        `vastly_omzetrekening` — toch blijft de regel leeg en weigert het pad; de API-vorm van de afleiding bestaat niet meer."""
        with scoped_session(vastgoed_administratie, actor_id=SYSTEEM_ACTOR_ID) as session:
            session.add(VastlyOmzetrekening(administratie_id=vastgoed_administratie, regelsoort="huur", ledger_id=OMZET_LEDGER_ID, bron="historie"))
        _patch_client(monkeypatch)
        document_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-Z", regels=[{"naam": "Huur oktober", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": None}]))
        assert _status(admin_engine, document_id) == "te_controleren"
        from app.verkoop import voorstel as voorstel_service

        [regel] = voorstel_service.haal_verkoop_voorstel_op(administratie_id=vastgoed_administratie, document_id=document_id).regels
        assert (regel.gb_code_status, regel.ledger_id, regel.gb_bron, regel.regelsoort) == ("ontbreekt", None, None, "huur")
        reden = vastly_reconciliatie.autoboeken.beoordeel_lees_only(administratie_id=vastgoed_administratie, document_id=document_id)
        assert reden is not None and reden.startswith("omzetrekening_ontbreekt: regel 1 (huur): geen grootboekcode")
        for naam in ("leid_af", "omzetrekening_voor", "zet_omzetrekening", "standen_voor", "keuzelijst", "GB_BRON_OMZETREKENING"):
            assert not hasattr(omzetrekening, naam), naam


# ---- 4. heraanbieden + CLI -------------------------------------------------------------------------------------------


class TestHeraanbieden:
    def test_dry_run_telt_en_schrijft_niets_en_echte_run_boekt(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie, capsys
    ) -> None:
        _patch_client(monkeypatch)
        # (a) niet-gekoppeld via intake; (b) open te_controleren: upload zonder is_vastgoed-hook-boeking simuleren door
        # de administratie tijdelijk géén vastgoed te laten zijn.
        [b] = _verwerk(bouw_vastly_verkoop_ubl(leverancier=LEVERANCIER, factuurnummer="VF-A"), gescoopte_gebruiker, opslag).bijlagen
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET is_vastgoed = false WHERE id = :id"), {"id": vastgoed_administratie})
        open_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-B"))
        assert _status(admin_engine, open_id) == "te_controleren"
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": vastgoed_administratie})

        # Dry-run: telling per uitkomst, niets geschreven (geen audit, statussen gelijk).
        assert cli.main([heraanbieden.COMMANDO, "--dry-run"]) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN" in uit and "TOTAAL: 2 kandidaten" in uit and "entiteit_niet_gekoppeld 1" in uit and "zou_boeken 1" in uit
        assert _status(admin_engine, open_id) == "te_controleren" and _status(admin_engine, b.document_id) == "niet_toegewezen"
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = 'vastly_verkoop_heraanbieding_run'")).scalar_one() == 0
        # Zustervorm mét --administratie (meetrecept-regel 19-09: élke vorm letterlijk).
        assert cli.main([heraanbieden.COMMANDO, "--dry-run", "--administratie", LEVERANCIER]) == 0
        assert "TOTAAL: 1 kandidaten" in capsys.readouterr().out
        assert cli.main([heraanbieden.COMMANDO, "--dry-run", "--uitvoeren"]) == 2

        # Échte run: het open document boekt; het niet-gekoppelde blijft (register kent 'm niet) — zichtbaar.
        assert cli.main([heraanbieden.COMMANDO, "--uitvoeren"]) == 0
        uit = capsys.readouterr().out
        assert "UITGEVOERD" in uit and "geboekt 1" in uit and "entiteit_niet_gekoppeld 1" in uit
        assert _status(admin_engine, open_id) == "geboekt"
        with admin_engine.connect() as conn:
            rij = conn.execute(text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'vastly_verkoop_heraanbieding_run'")).scalar_one()
        assert rij["per_uitkomst"] == {"entiteit_niet_gekoppeld": 1, "geboekt": 1} and rij["bron"] == "cli"

        # 01-10: geen mens-koppeling meer — het niet-gekoppelde document blijft zichtbaar staan mét de reden "melden bij
        # Vastly" tot Vastly de UBL mét administratie-id herzendt (dan neemt dezelfde motor 'm mee).
        [u] = [u for u in heraanbieden.draai(bron="cli", dry_run=True).uitkomsten if u.uitkomst == "entiteit_niet_gekoppeld"]
        assert "geen administratie-id en geen bekende KvK — melden bij Vastly" in (u.reden or "")
        assert [k.document_id for k in heraanbieden.vind_niet_gekoppeld()] == [b.document_id]
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.toewijzing_regel")).scalar_one() == 0

    def test_dagteller_uit_run_audit(self) -> None:
        nu = datetime.now(UTC)
        feiten = auto.Feiten(
            audit=[auto.AuditFeit(actie="vastly_verkoop_heraanbieding_run", tijdstip=nu - timedelta(hours=1), administratie_id=None, nieuwe_waarde={"dry_run": False, "per_uitkomst": {"geboekt": 3, "toegewezen": 1, "geweigerd": 2, "entiteit_niet_gekoppeld": 9}})],
        )
        t = {x.sleutel: x for x in auto.bereken(feiten, nu=nu)}[auto.VASTLY_HERAANBIEDING]
        assert t.dag.gedaan == 4 and t.dag.overgeslagen == {"geweigerd": 2, "entiteit_niet_gekoppeld": 9}


# ---- 5. UBL nooit door de AI ----------------------------------------------------------------------------------------


class TestUblNooitAi:
    def test_pdf_extractie_slaat_verkoopfactuur_over_en_herextractie_weigert(
        self, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, vastgoed_administratie
    ) -> None:
        # Een verkoopfactuur is altijd een Vastly-UBL: ook mét een PDF-suffix op het hoofdbestand (nabundel-/rename-
        # randgeval, bijvangst RUB-2026-0034 24-09) gaat er NOOIT een AI-call uit.
        transient = Document(id=uuid.uuid4(), administratie_id=vastgoed_administratie, soort=DocumentSoort.VERKOOPFACTUUR.value, bestandsnaam="factuur-RUB-1.pdf", sha256_hash="x", status=DocumentStatus.EXTRACTIE_BEZIG, opslag_pad="n/a")
        with scoped_session(vastgoed_administratie) as session:
            detail, blokkeer = documenten_service._pdf_extractie_detail(session, document=transient, opslag=opslag)
        assert detail["ai_extractie_overgeslagen"] == documenten_service.UBL_NOOIT_AI and blokkeer is False
        document_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl())
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET bestandsnaam = 'factuur-RUB-1.pdf' WHERE id = :id"), {"id": document_id})
        with pytest.raises(documenten_service.HerextractieNietToegestaan):
            documenten_service.herextraheer_document(administratie_id=vastgoed_administratie, document_id=document_id, actor_id=gescoopte_gebruiker, opslag=opslag)

    def test_ai_heraanbieding_kent_geen_verkoopfactuur_kandidaat(self, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, vastgoed_administratie) -> None:
        from app.aikosten import heraanbieden as ai_heraanbieden

        document_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl())
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET bestandsnaam = 'factuur-RUB-2.pdf', status = 'te_controleren' WHERE id = :id"), {"id": document_id})
            conn.execute(
                text("INSERT INTO boekhouding.document_gebeurtenis (id, document_id, van_status, naar_status, actor_id, detail) VALUES (:i, :d, 'extractie_bezig', 'te_controleren', :a, CAST(:det AS jsonb))"),
                {"i": uuid.uuid4(), "d": document_id, "a": SYSTEEM_ACTOR_ID, "det": '{"ai_extractie_overgeslagen": "ai_limiet_bereikt"}'},
            )
        kandidaten, mens_bezig = ai_heraanbieden.vind_kandidaten_documenten([vastgoed_administratie])
        assert all(k.document_id != document_id for k in kandidaten + mens_bezig)


# ---- 6. reconciliatieblok + teksten + routes -------------------------------------------------------------------------


class TestReconciliatieBlok:
    def _oud(self, admin_engine: Engine, document_id: uuid.UUID, status: str | None = None) -> None:
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET aangemaakt_op = now() - interval '2 days'" + (", status = :st" if status else "") + " WHERE id = :id"), {"id": document_id, **({"st": status} if status else {})})

    def test_drie_soorten_met_handeling_en_leesbare_teksten(
        self, monkeypatch, gescoopte_gebruiker, admin_engine, opslag, rekeningschema, vastgoed_administratie, capsys
    ) -> None:
        _patch_client(monkeypatch)
        # (1) niet-gekoppelde entiteit (twee facturen, één bevinding)
        a = _verwerk(bouw_vastly_verkoop_ubl(leverancier="Van Rooijen / Schaalje", factuurnummer="BG-1"), gescoopte_gebruiker, opslag, naam="bg-1-ubl.xml").bijlagen[0]
        _verwerk(bouw_vastly_verkoop_ubl(leverancier="Van Rooijen / Schaalje", factuurnummer="BG-2"), gescoopte_gebruiker, opslag, naam="bg-2-ubl.xml")
        # (2) omzetrekening ontbreekt (01-10: per DOCUMENT, handeling alleen "Opnieuw aanbieden"): regel zonder code → open > 1 dag
        rek_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-R", regels=[{"naam": "Parkeren", "netto": "100.00", "pct": "21.00", "categorie": "S", "gb_code": None}]))
        self._oud(admin_engine, rek_id)
        # (3) niet geboekt: boeken_mislukt > 1 dag
        mislukt_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-M"))
        self._oud(admin_engine, mislukt_id, status="boeken_mislukt")
        # (4) jonger dan een dag: geen bevinding
        upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-J", regels=[{"naam": "Parkeren", "netto": "1.00", "pct": "21.00", "categorie": "S", "gb_code": None}]))

        v = Verzamelaar()
        v.start_blok(vastly_reconciliatie.BLOK)
        code = vastly_reconciliatie.cli_blok(argparse.Namespace(), v, stdout=lambda s: None)
        assert code == 1
        per_soort = {b.detail["afwijking_soort"]: b for b in v.bevindingen}
        assert set(per_soort) == {"vastly_entiteit_niet_gekoppeld", "vastly_omzetrekening_ontbreekt", "vastly_verkoop_niet_geboekt"}
        ent = per_soort["vastly_entiteit_niet_gekoppeld"]
        assert ent.administratie_id is None and ent.detail["aantal"] == 2 and ent.detail["sleutel_soort"] == "naam" and ent.detail["sleutel"] == "van rooijen schaalje"
        assert {d["document_id"] for d in ent.detail["documenten"]} >= {str(a.document_id)}
        assert ent.detail["administratie_id_ubl"] is None and ent.detail["reden"] == "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly"
        rek = per_soort["vastly_omzetrekening_ontbreekt"]
        assert rek.administratie_id == vastgoed_administratie and rek.detail["document_id"] == str(rek_id) and rek.detail["regelsoort"] == "overig"
        assert rek.detail["reden"].startswith("omzetrekening_ontbreekt: regel 1 (overig): geen grootboekcode") and rek.detail["doel_pad"] == f"/verkoop/{vastgoed_administratie}/{rek_id}"
        nb = per_soort["vastly_verkoop_niet_geboekt"]
        assert nb.detail["document_id"] == str(mislukt_id) and "boeken_mislukt" in nb.detail["reden"] and nb.detail["doel_pad"] == f"/verkoop/{vastgoed_administratie}/{mislukt_id}"
        # Leesbare laag: titel/wat/doe — de handeling is melden bij Vastly / Opnieuw aanbieden, nooit een mens-keuze.
        for b in v.bevindingen:
            lb = teksten.leesbaar(b, administratie_naam=LEVERANCIER)
            assert lb.titel and lb.wat and lb.doe
            assert "Koppel aan administratie" not in lb.doe and "Rekening kiezen" not in lb.doe
        assert "melden bij vastly" in teksten.leesbaar(ent).doe.lower() and "geen koppelknop" in teksten.leesbaar(ent).doe
        assert "Melden bij Vastly" in teksten.leesbaar(rek).doe and "Opnieuw aanbieden" in teksten.leesbaar(rek).doe and "Opnieuw aanbieden" in teksten.leesbaar(nb).doe
        # Een UBL mét een onbekend administratie-id: de bevinding noemt het id.
        _verwerk(bouw_vastly_verkoop_ubl(leverancier="Onbekende Verhuurder", factuurnummer="BG-9", platform_administratie_id=str(uuid.UUID(int=9))), gescoopte_gebruiker, opslag, naam="bg-9-ubl.xml")
        v2 = Verzamelaar()
        v2.start_blok(vastly_reconciliatie.BLOK)
        vastly_reconciliatie.cli_blok(argparse.Namespace(), v2, stdout=lambda s: None)
        [onb] = [b for b in v2.bevindingen if b.detail.get("afwijking_soort") == "vastly_entiteit_niet_gekoppeld" and b.detail.get("sleutel") == "onbekende verhuurder"]
        assert onb.detail["administratie_id_ubl"] == str(uuid.UUID(int=9)) and str(uuid.UUID(int=9)) in teksten.leesbaar(onb).wat
        # Meetlat uit het recept, letterlijk: lees-only deelrun via de CLI.
        assert cli.main(["reconciliatie-alles", "--alleen", "vastly_verkoop", "--lees-only"]) == 1
        uit = capsys.readouterr().out
        assert "VASTLY " in uit and "entiteiten niet gekoppeld 2, omzetrekening ontbreekt 1, niet geboekt 1" in uit

    def test_routes_opnieuw_aanbieden_en_vervallen_routes(
        self, monkeypatch, gescoopte_gebruiker, beheerder_id, admin_engine, opslag, rekeningschema, boeken_aan, vastgoed_administratie
    ) -> None:
        _patch_client(monkeypatch)
        kantoor = _headers(gescoopte_gebruiker, "boekhouding")
        beheer = _headers(beheerder_id, "beheerder")
        # 01-10: de mens-koppelroute en de instellingenroutes bestaan niet meer (404 — geen stille 200, geen handeling).
        assert client.post("/reconciliatie/vastly/entiteit-koppelen", json={"sleutel_soort": "naam", "sleutel": "x", "administratie_id": str(vastgoed_administratie)}, headers=kantoor).status_code == 404
        assert client.get(f"/administraties/{vastgoed_administratie}/vastly-instellingen", headers=kantoor).status_code == 404
        assert client.put(f"/administraties/{vastgoed_administratie}/vastly-omzetrekeningen", json={"regelsoort": "huur", "ledger_id": str(OMZET_LEDGER_ID)}, headers=beheer).status_code == 404
        # Opnieuw aanbieden: boeken_mislukt → te_controleren → autoboek → geboekt; geboekt document = 409.
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET is_vastgoed = false WHERE id = :id"), {"id": vastgoed_administratie})
        open_id = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-O"))
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": vastgoed_administratie})
            conn.execute(text("UPDATE boekhouding.document SET status = 'boeken_mislukt' WHERE id = :id"), {"id": open_id})
        o = client.post(f"/reconciliatie/vastly/documenten/{open_id}/opnieuw-aanbieden", json={"administratie_id": str(vastgoed_administratie)}, headers=kantoor)
        assert o.status_code == 200, o.text
        assert o.json()["uitkomst"] == "geboekt" and _status(admin_engine, open_id) == "geboekt"
        assert client.post(f"/reconciliatie/vastly/documenten/{open_id}/opnieuw-aanbieden", json={"administratie_id": str(vastgoed_administratie)}, headers=kantoor).status_code == 409
        assert client.post(f"/reconciliatie/vastly/documenten/{uuid.uuid4()}/opnieuw-aanbieden", json={"administratie_id": str(vastgoed_administratie)}, headers=kantoor).status_code == 404
        # Opnieuw aanbieden op een document zónder code = geweigerd mét de reden (ná herzending door Vastly pas geboekt).
        zonder_code = upload_verkoopfactuur(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(factuurnummer="VF-Q", regels=[{"naam": "Huur", "netto": "10.00", "pct": "21.00", "categorie": "S", "gb_code": None}]))
        q = client.post(f"/reconciliatie/vastly/documenten/{zonder_code}/opnieuw-aanbieden", json={"administratie_id": str(vastgoed_administratie)}, headers=kantoor)
        assert q.status_code == 200 and q.json()["uitkomst"] == "geweigerd" and q.json()["reden"].startswith("omzetrekening_ontbreekt")
