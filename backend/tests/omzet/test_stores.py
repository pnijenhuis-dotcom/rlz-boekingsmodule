# ruff: noqa: F811 — pytest-fixtures als parameters
"""Store → administratie PLATFORMBREED (Peter 16-09 avond: Sunshine Island = eigen BV; migratie 0151): normalisatie,
upsert op de unieke storenaam (verhuizen = dezelfde rij, nooit twee administraties), ontkoppelen zonder verwijderen,
de afgeleide per-administratie-weergave, de Beheerder-routes, de intake (dagstaat → ándere administratie op de store,
onbekende store → verzamelbak mét reden + Stores-link, kascheck volgt de dagstaat uit dezelfde mail of de enige open
dagstaat van die dag) en de data-stap `omzet-stores-migreren` (dry-run default, idempotent, conflict nooit overschreven)."""

from __future__ import annotations

import argparse
import copy
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app import cli
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.intake import verwerking
from app.intake.eml import IntakeBijlage
from app.intake.redenen import omschrijf_intake_reden
from app.intake.verzamelbak import lijst_verzamelbak
from app.main import app
from app.omzet.bronnen import service as bronnen_service
from app.omzet.bronnen import stores
from app.omzet.models import OmzetInstelling, OmzetStoreRoutering
from app.security.tokens import create_access_token
from tests.omzet.test_bronnen import DAGSTAAT, KASCHECK, grid_naar_xlsx

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def sunshine(admin_engine: Engine) -> uuid.UUID:
    """Tweede actieve administratie — de eigen BV van de tweede studio (buiten de scope van `gescoopte_gebruiker`)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Sunshine Island B.V.', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def dagstaat_met_store(store: str) -> bytes:
    grid = copy.deepcopy(DAGSTAAT)
    vervangen = 0
    for rij in grid.rijen:
        for c, w in list(rij.items()):
            if isinstance(w, str) and w.strip() == "Elderveld":
                rij[c] = store
                vervangen += 1
    assert vervangen >= 1, "de fixture-dagstaat draagt 'Store Used: Elderveld'"
    return grid_naar_xlsx(grid)


def _spreadsheet(naam: str, inhoud: bytes, actor: uuid.UUID, opslag, **kw):  # noqa: ANN001
    return verwerking._verwerk_spreadsheet(  # noqa: SLF001
        IntakeBijlage(bestandsnaam=naam, inhoud=inhoud, content_type="application/octet-stream"),
        afzender="pos@zonnestudio.example",
        actor_id=actor,
        intake_bericht_id=None,
        opslag=opslag,
        **kw,
    )


def _audit(admin_engine: Engine, actie: str) -> list:
    """Audit-rijen als eigenaar lezen (RLS scoped audit_event op administratie — de schema-owner ziet alles)."""
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT actie, oude_waarde, nieuwe_waarde, administratie_id FROM platform.audit_event "
                "WHERE actie = :actie ORDER BY tijdstip"
            ),
            {"actie": actie},
        ).all()


class TestNormalisatieEnKoppelen:
    def test_normaliseer_store(self) -> None:
        assert stores.normaliseer_store("Sunshine  Island") == "sunshine island"
        assert stores.normaliseer_store(" SUNSHINE-ISLAND ") == "sunshine island"
        assert stores.normaliseer_store("Elderveld") == "elderveld"
        assert stores.normaliseer_store("") is None and stores.normaliseer_store(None) is None
        assert stores.normaliseer_store(" - ") is None

    def test_koppel_upsert_verhuizen_ontkoppelen_en_audit(self, administratie_id, sunshine, beheerder_id, admin_engine) -> None:
        a = stores.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
        b = stores.koppel(store="Sunshine Island", administratie_id=sunshine, actor_id=beheerder_id)
        assert (a.administratie_id, b.administratie_id, b.administratie_naam) == (
            administratie_id,
            sunshine,
            "Sunshine Island B.V.",
        )
        assert stores.administratie_voor_store("sunshine island") == sunshine
        assert stores.administratie_voor_store("ELDERVELD") == administratie_id
        assert stores.administratie_voor_store("Onbekend") is None
        # Dezelfde store nog eens koppelen aan een ándere administratie = DEZELFDE rij verhuist (unieke index) —
        # twee administraties voor één store kan structureel niet.
        b2 = stores.koppel(store="sunshine island", administratie_id=administratie_id, actor_id=beheerder_id)
        assert b2.id == b.id and b2.administratie_id == administratie_id
        with scoped_session(None) as session:
            assert session.scalar(select(OmzetStoreRoutering.store_norm).where(OmzetStoreRoutering.store_norm == "sunshine island")) == "sunshine island"
            assert len(list(session.scalars(select(OmzetStoreRoutering)))) == 2
        # Ontkoppelen = actief=False, rij blijft; routeren geeft None; opnieuw activeren herstelt.
        uit = stores.zet_actief(routering_id=b.id, actief=False, actor_id=beheerder_id)
        assert uit.actief is False and stores.administratie_voor_store("Sunshine Island") is None
        assert [s.store_naam for s in stores.lijst()] == ["Elderveld", "Sunshine Island"]
        stores.zet_actief(routering_id=b.id, actief=True, actor_id=beheerder_id)
        assert stores.administratie_voor_store("Sunshine Island") == administratie_id
        assert len(_audit(admin_engine, "omzet_store_gekoppeld")) == 2
        gewijzigd = _audit(admin_engine, "omzet_store_gewijzigd")
        assert len(gewijzigd) == 3
        assert gewijzigd[0].oude_waarde["administratie_id"] == str(sunshine)
        assert gewijzigd[0].nieuwe_waarde["administratie_id"] == str(administratie_id)

    def test_lege_naam_en_onbekende_administratie_worden_geweigerd(self, administratie_id, beheerder_id) -> None:
        with pytest.raises(stores.StoreFout):
            stores.koppel(store="  ", administratie_id=administratie_id, actor_id=beheerder_id)
        with pytest.raises(stores.StoreFout):
            stores.koppel(store="X", administratie_id=uuid.uuid4(), actor_id=beheerder_id)
        with pytest.raises(stores.StoreOnbekend):
            stores.zet_actief(routering_id=uuid.uuid4(), actief=False, actor_id=beheerder_id)


class TestAfgeleideWeergaveEnRoutes:
    def test_bron_instellingen_toont_stores_afgeleid_en_weigert_schrijven(
        self, administratie_id, sunshine, beheerder_id
    ) -> None:
        stores.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
        stores.koppel(store="Sunshine Island", administratie_id=sunshine, actor_id=beheerder_id)
        with scoped_session(administratie_id) as session:
            assert bronnen_service.bron_instellingen_voor(session, administratie_id)["stores"] == ["Elderveld"]
        with scoped_session(sunshine) as session:
            assert bronnen_service.bron_instellingen_voor(session, sunshine)["stores"] == ["Sunshine Island"]
        with pytest.raises(ValueError, match="platformbreed"):
            bronnen_service.zet_bron_instellingen(
                administratie_id=administratie_id, actor_id=beheerder_id, waarden={"stores": ["X"]}
            )
        # Legacy-JSON (0146) wordt niet meer als instelling gelezen — alleen de tabel telt.
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            rij = session.get(OmzetInstelling, administratie_id) or OmzetInstelling(administratie_id=administratie_id)
            rij.bron_instellingen = {**(rij.bron_instellingen or {}), "stores": ["Legacy"]}
            session.add(rij)
        with scoped_session(administratie_id) as session:
            assert bronnen_service.bron_instellingen_voor(session, administratie_id)["stores"] == ["Elderveld"]
        assert stores.administratie_voor_store("Legacy") is None

    def test_routes_lezen_kantoorrol_schrijven_beheerder(self, administratie_id, sunshine, beheerder_id, gescoopte_gebruiker) -> None:
        kop_b = _bearer(beheerder_id, rol="beheerder")
        kop_k = _bearer(gescoopte_gebruiker, rol="boekhouding")
        r = client.post("/instellingen/omzet/stores", headers=kop_b, json={"store": "Sunshine Island", "administratie_id": str(sunshine)})
        assert r.status_code == 200 and r.json()["administratie_naam"] == "Sunshine Island B.V."
        rid = r.json()["id"]
        assert client.post("/instellingen/omzet/stores", headers=kop_k, json={"store": "X", "administratie_id": str(administratie_id)}).status_code == 403
        r = client.get("/instellingen/omzet/stores", headers=kop_k)
        assert r.status_code == 200 and [s["store_naam"] for s in r.json()["stores"]] == ["Sunshine Island"]
        assert r.json()["doel_pad"] == "/instellingen/boeken#stores"
        r = client.put(f"/instellingen/omzet/stores/{rid}", headers=kop_b, json={"actief": False})
        assert r.status_code == 200 and r.json()["actief"] is False
        r = client.put(f"/instellingen/omzet/stores/{rid}", headers=kop_b, json={"administratie_id": str(administratie_id), "actief": True})
        assert r.status_code == 200 and (r.json()["administratie_id"], r.json()["actief"]) == (str(administratie_id), True)
        assert client.put(f"/instellingen/omzet/stores/{uuid.uuid4()}", headers=kop_b, json={"actief": False}).status_code == 404
        assert client.post("/instellingen/omzet/stores", headers=kop_b, json={"store": " ", "administratie_id": str(sunshine)}).status_code == 422
        # De per-administratie-PUT weigert `stores` (extra=forbid → 422 uit pydantic).
        assert client.put(f"/administraties/{administratie_id}/omzet/bron-instellingen", headers=kop_b, json={"stores": ["X"]}).status_code == 422


class TestIntakeOpStore:
    def test_dagstaat_landt_op_de_store_in_een_andere_administratie(
        self, administratie_id, sunshine, beheerder_id, gescoopte_gebruiker, opslag, admin_engine
    ) -> None:
        stores.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
        stores.koppel(store="Sunshine Island", administratie_id=sunshine, actor_id=beheerder_id)
        res_e = _spreadsheet("8-9-26.xlsx", grid_naar_xlsx(DAGSTAAT), gescoopte_gebruiker, opslag)
        res_s = _spreadsheet("8-9-26 (2).xlsx", dagstaat_met_store("Sunshine Island"), gescoopte_gebruiker, opslag)
        assert res_e.uitkomst == "toegewezen" and res_e.detail.endswith(str(administratie_id))
        assert res_s.uitkomst == "toegewezen" and res_s.detail.endswith(str(sunshine))
        with scoped_session(sunshine) as session:
            doc = session.get(Document, res_s.document_id)
            assert (doc.administratie_id, doc.soort) == (sunshine, DocumentSoort.KASSARAPPORT.value)
        herkend = _audit(admin_engine, "omzetbron_herkend")
        assert {(e.nieuwe_waarde["store"], e.nieuwe_waarde["routering"]) for e in herkend} == {
            ("Elderveld", "store"),
            ("Sunshine Island", "store"),
        }

    def test_onbekende_store_gaat_naar_de_verzamelbak_met_reden_en_stores_link(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine
    ) -> None:
        # Alleen Elderveld gekoppeld; de tenaamstelling/afzender mag NIET naar Elderveld raden.
        stores.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
        res = _spreadsheet("8-9-26.xlsx", dagstaat_met_store("Sunshine Island"), gescoopte_gebruiker, opslag)
        assert res.uitkomst == "verzamelbak" and "/instellingen/boeken#stores" in (res.detail or "")
        with scoped_session(None) as session:
            doc = session.get(Document, res.document_id)
            assert doc.administratie_id is None and doc.soort == DocumentSoort.KASSARAPPORT.value
        [item] = [i for i in lijst_verzamelbak() if i.document_id == res.document_id]
        assert item.reden.startswith("omzetbron_store_onbekend: Sunshine Island")
        assert item.reden_label == omschrijf_intake_reden(item.reden, tenaamstelling="Sunshine Island")
        assert "niet gekoppeld" in item.reden_label and "Stores" in item.reden_label
        [e] = _audit(admin_engine, "omzetbron_store_onbekend")
        assert e.nieuwe_waarde["store"] == "Sunshine Island" and e.administratie_id is None

    def test_kascheck_volgt_de_dagstaat_uit_dezelfde_mail_en_anders_de_enige_open_dagstaat(
        self, administratie_id, sunshine, beheerder_id, gescoopte_gebruiker, opslag
    ) -> None:
        stores.koppel(store="Sunshine Island", administratie_id=sunshine, actor_id=beheerder_id)
        bijlagen = [
            IntakeBijlage(bestandsnaam="8-9-26.xlsx", inhoud=dagstaat_met_store("Sunshine Island"), content_type="x"),
            IntakeBijlage(bestandsnaam="kascheck-2026-09-08.xlsx", inhoud=grid_naar_xlsx(KASCHECK, blad="Kascheck"), content_type="x"),
        ]
        assert verwerking._dagstaat_mail_store(bijlagen) == "Sunshine Island"  # noqa: SLF001
        # (1) mail mét dagstaat: de kascheck volgt de store uit de mail — beide in Sunshine Island.
        res_k = _spreadsheet("kascheck-2026-09-08.xlsx", bijlagen[1].inhoud, gescoopte_gebruiker, opslag, mail_store="Sunshine Island")
        assert res_k.uitkomst == "toegewezen" and "store_uit_mail" in res_k.detail and res_k.detail.endswith(str(sunshine))
        # (2) losse kascheck-mail: de enige administratie met een dagstaat van die dag die op zijn kascheck wacht wint.
        res_d = _spreadsheet("9-9-26.xlsx", bijlagen[0].inhoud, gescoopte_gebruiker, opslag)
        assert res_d.uitkomst == "toegewezen" and res_d.detail.endswith(str(sunshine))
        with scoped_session(sunshine) as session:
            vv = bronnen_service._laatste_veldvoorstel(session, res_d.document_id)  # noqa: SLF001
        if vv["bron_detail"].get("wacht_op") == "kascheck":
            assert bronnen_service.administratie_voor_kascheck(date(2026, 9, 8)) == sunshine
            res_k2 = _spreadsheet("kascheck-2026-09-08 (2).xlsx", bijlagen[1].inhoud, gescoopte_gebruiker, opslag)
            assert res_k2.uitkomst == "toegewezen" and "open_dagstaat" in res_k2.detail
            with scoped_session(sunshine) as session:
                kas = session.get(Document, res_k2.document_id)
                assert kas.administratie_id == sunshine
                assert (kas.status, kas.samengevoegd_in_id) == (DocumentStatus.SAMENGEVOEGD, res_d.document_id)
        assert bronnen_service.administratie_voor_kascheck(None) is None


class TestMigratieDatastap:
    def test_dry_run_schrijf_idempotent_en_conflict(self, administratie_id, sunshine, beheerder_id, capsys) -> None:
        for aid, lijst in ((administratie_id, ["Elderveld", "Sunshine Island"]), (sunshine, ["Sunshine Island"])):
            with scoped_session(aid, actor_id=beheerder_id) as session:
                rij = session.get(OmzetInstelling, aid) or OmzetInstelling(administratie_id=aid)
                rij.bron_instellingen = {"stores": lijst}
                session.add(rij)
        dry = stores.migreer_uit_bron_instellingen(schrijf=False)
        assert sorted(r.uitkomst for r in dry) == ["dry_run", "dry_run", "dry_run"]
        with scoped_session(None) as session:
            assert list(session.scalars(select(OmzetStoreRoutering))) == []
        echt = stores.migreer_uit_bron_instellingen(schrijf=True)
        per = {(r.administratie_id, r.store): r.uitkomst for r in echt}
        # Volgorde op administratienaam: 'Sunshine Island B.V.' < de testadministratie? — deterministisch: de eerste die
        # 'Sunshine Island' claimt wint, de tweede is een conflict (nooit overschreven).
        assert per[(administratie_id, "Elderveld")] == "aangemaakt"
        uitkomsten = {per[(administratie_id, "Sunshine Island")], per[(sunshine, "Sunshine Island")]}
        assert uitkomsten == {"aangemaakt", "conflict"}
        opnieuw = stores.migreer_uit_bron_instellingen(schrijf=True)
        assert sorted(r.uitkomst for r in opnieuw) == ["bestaat_al", "bestaat_al", "conflict"]
        assert len(stores.lijst()) == 2 and all(s.bron == "migratie" for s in stores.lijst())
        assert stores.administratie_voor_store("Elderveld") == administratie_id
        # CLI-vorm: dry-run default print, --schrijf idempotent.
        assert cli._omzet_stores_migreren(argparse.Namespace(schrijf=False)) == 0  # noqa: SLF001
        uit = capsys.readouterr().out
        assert "DRY-RUN" in uit and "bestaat_al" in uit
