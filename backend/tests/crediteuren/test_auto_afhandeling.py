# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels
"""Crediteuren-dubbelen schaalbaar (blok B13 07-09, migratie 0117): classificatie eenduidig/twijfel, de auto-run
(dry-run vs echt, één transactie per cluster, audit, idempotent), terugdraaien mét herstel van markering/kenmerk/
boekvoorstel, de CSV-export, en de verliezer-uitsluiting in de leespaden (extractie-kandidaten, naammatch,
crediteuren-combobox, geheugen-groep, terugkerend-signaal, hervertaling open boekvoorstel)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.crediteuren import afhandeling, service
from app.crediteuren.models import CrediteurArchiveerWerklijst, CrediteurDubbelAfhandeling
from app.crediteuren.voorkeur import verliezers, voorkeur_van
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import boekvoorstel as boekvoorstel_module
from app.documenten.crediteur_kenmerk import kandidaten_met_kenmerken
from app.documenten.models import (
    Boekvoorstel,
    CrediteurKenmerk,
    Document,
    DocumentBron,
    DocumentStatus,
    LeverancierVoorkeur,
)
from app.geheugen.regel_gb import vendor_groep
from app.main import app
from app.sync import service as sync_service
from app.sync.models import VendorCache
from app.terugkerend.service import _facturen_per_vendor
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.crediteuren.test_crediteuren_dubbelen import (  # noqa: F401
    BTW,
    COOL,
    COOL_BV,
    IBAN,
    LABO,
    LABO_BV,
    WOLA,
    WOLA_BV,
    _audit_acties,
    _bearer,
    andere_administratie,
    dubbelen,
)
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)


def _actor(gebruiker_id: uuid.UUID, rol: str = "beheerder") -> service.Actor:
    return service.Actor(id=gebruiker_id, rol=GebruikerRol(rol))


def _document(session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, status: DocumentStatus) -> uuid.UUID:
    document_id = uuid.uuid4()
    session.add(
        Document(
            id=document_id,
            administratie_id=administratie_id,
            bron=DocumentBron.UPLOAD,
            bestandsnaam=f"{document_id}.pdf",
            sha256_hash=uuid.uuid4().hex * 2,
            status=status,
            opslag_pad=f"test/{document_id}.pdf",
        )
    )
    session.flush()  # RLS op boekvoorstel toetst via het document — dat moet eerst bestaan
    session.add(Boekvoorstel(document_id=document_id, vendor_id=vendor_id, factuurdatum=date(2026, 8, 1)))
    session.flush()
    return document_id


class TestClassificatie:
    def test_eenduidig_en_twijfel_op_kaartgegevens(self, dubbelen, administratie_id, beheerder_id) -> None:
        clusters = {c.soort: c for c in service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")}
        labo, wola = clusters["btw_nummer"], clusters["naam"]
        cl = afhandeling.classificeer(labo)
        assert cl.eenduidig and cl.voorkeur_vendor_id == LABO_BV and cl.verliezer_vendor_ids == [LABO]
        assert cl.reden.startswith("eenduidig: identieke naam, geen conflicterend KvK/btw")
        # KvK-conflict = twijfel, óók al is de naam identiek.
        assert not afhandeling.classificeer(wola).eenduidig
        assert "verschillend KvK-nummer" in afhandeling.classificeer(wola).reden
        # Grens N: de verliezer Labo Derva draagt 1 boeking → bij N = 0 is het mens.
        strak = afhandeling.classificeer(labo, max_boekingen=0)
        assert not strak.eenduidig and "1 boekingen (> 0)" in strak.reden
        # Menskeuze (autoboek-opt-in / veldwerker-koppeling) op de verliezer = twijfel.
        mens = afhandeling.classificeer(labo, menskeuze=frozenset({LABO}))
        assert not mens.eenduidig and "autoboek-opt-in of veldwerker-koppeling op Labo Derva" in mens.reden
        # Alleen-btw (naam én IBAN verschillen) = twijfel — fiscale eenheid.
        alleen_btw = service.Cluster(**{**labo.__dict__, "sleutels": [("btw_nummer", BTW)]})
        assert "fiscale eenheid" in afhandeling.classificeer(alleen_btw).reden

    def test_alleen_kvk_eenduidig_alleen_btw_twijfel_kvk_met_btw_conflict_twijfel(
        self, dubbelen, administratie_id, beheerder_id
    ) -> None:
        """Besluit Peter 07-09 (beslispunt 2): één KvK-nummer = één rechtspersoon, ook met meerdere handelsnamen →
        alleen-KvK is EENDUIDIG; alleen-btw (fiscale eenheid) blijft twijfel; zelfde KvK + conflicterend btw = twijfel."""
        clusters = {c.soort: c for c in service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")}
        labo = clusters["btw_nummer"]

        def kaart(vendor_id: uuid.UUID, naam: str, *, kvk: str | None, btw: str | None, boekingen: int = 1) -> service.Kaart:
            return service.Kaart(
                vendor_id=vendor_id, naam=naam, btw_nummer=btw, kvk_nummer=kvk, ibans=[], aantal_boekingen=boekingen,
                laatst_geboekt=None,
            )

        def cluster(kaarten: list[service.Kaart], sleutels: list[tuple[str, str]]) -> service.Cluster:
            return service.Cluster(
                **{
                    **labo.__dict__,
                    "crediteuren": kaarten,
                    "sleutels": sleutels,
                    "soort": sleutels[0][0],
                    "voorkeur_suggestie": service._voorkeur_suggestie(kaarten),
                }
            )

        a, b = uuid.uuid4(), uuid.uuid4()
        # Alleen-KvK: namen én IBAN's verschillen, KvK genormaliseerd gelijk ("KvK 1234.5678" ≡ "12345678").
        alleen_kvk = cluster(
            [kaart(a, "Hubo Oirschot", kvk="12345678", btw=None, boekingen=3), kaart(b, "Bouwmarkt Oirschot B.V.", kvk="KvK 1234.5678", btw=None)],
            [("kvk_nummer", "12345678")],
        )
        cl = afhandeling.classificeer(alleen_kvk)
        assert cl.eenduidig and cl.voorkeur_vendor_id == a and cl.verliezer_vendor_ids == [b]
        assert cl.reden.startswith("eenduidig: zelfde KvK-nummer (één rechtspersoon, handelsnamen mogen verschillen), geen conflicterend KvK/btw")
        # Alleen-btw (fiscale eenheid): geen naam/IBAN-sleutel, KvK ontbreekt of verschilt → twijfel.
        alleen_btw = cluster(
            [kaart(a, "Holding A", kvk=None, btw=BTW), kaart(b, "Werkmij B", kvk=None, btw=BTW)], [("btw_nummer", BTW)]
        )
        cl = afhandeling.classificeer(alleen_btw)
        assert not cl.eenduidig and "alleen zelfde btw-nummer" in cl.reden and "fiscale eenheid" in cl.reden
        # Alleen-btw mét één kaart mét KvK en één zonder: geen 'zelfde KvK op alle kaarten' → twijfel.
        half_kvk = cluster(
            [kaart(a, "Holding A", kvk="12345678", btw=BTW), kaart(b, "Werkmij B", kvk=None, btw=BTW)], [("btw_nummer", BTW)]
        )
        assert not afhandeling.classificeer(half_kvk).eenduidig
        # Zelfde KvK maar conflicterend btw-nummer → twijfel (datakwaliteit), mét beide motiveringen zichtbaar.
        kvk_btw_conflict = cluster(
            [kaart(a, "Hubo Oirschot", kvk="12345678", btw="NL123456789B01"), kaart(b, "Bouwmarkt Oirschot B.V.", kvk="12345678", btw=BTW)],
            [("kvk_nummer", "12345678")],
        )
        cl = afhandeling.classificeer(kvk_btw_conflict)
        assert not cl.eenduidig and "verschillend btw-nummer" in cl.reden and "fiscale eenheid" not in cl.reden
        # De N-grens en menskeuze gelden onverkort voor alleen-KvK-clusters.
        assert not afhandeling.classificeer(alleen_kvk, max_boekingen=0).eenduidig
        assert not afhandeling.classificeer(alleen_kvk, menskeuze=frozenset({b})).eenduidig

    def test_menskeuze_uit_db(self, dubbelen, administratie_id, beheerder_id) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                LeverancierVoorkeur(
                    administratie_id=administratie_id, vendor_id=LABO, regels_samenvoegen=True, autoboeken_ingeschakeld=True
                )
            )
        clusters = service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")
        labo = next(c for c in clusters if c.soort == "btw_nummer")
        assert not labo.eenduidig and "autoboek-opt-in" in labo.classificatie_reden


class TestAutoRun:
    def test_dry_run_telt_zonder_te_schrijven_en_echt_handelt_af(
        self, dubbelen, administratie_id, andere_administratie, beheerder_id, admin_engine: Engine
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        # Open boekvoorstel op de verliezer + een GEBOEKT document op de verliezer (historie, blijft staan).
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            open_doc = _document(session, administratie_id=administratie_id, vendor_id=LABO, status=DocumentStatus.TE_CONTROLEREN)
            geboekt_doc = _document(session, administratie_id=administratie_id, vendor_id=LABO, status=DocumentStatus.GEBOEKT)
            # Eén geboekt document op de voorkeur houdt Labo Derva B.V. de meest gebruikte (3 vs 2 boekingen).
            _document(session, administratie_id=administratie_id, vendor_id=LABO_BV, status=DocumentStatus.GEBOEKT)

        r = client.post("/crediteuren/dubbelen/auto-afhandelen", headers=headers, json={"dry_run": True})
        assert r.status_code == 200, r.text
        preview = r.json()
        assert preview["dry_run"] is True and preview["eenduidig"] == 2 and preview["twijfel"] == 1
        assert preview["afgehandeld"] == 0 and preview["fouten"] == 0
        per_adm = {a["administratie_naam"]: a for a in preview["administraties"]}
        assert per_adm["Scope-test"]["eenduidig"] == 1 and per_adm["Scope-test"]["twijfel"] == 1
        assert per_adm["Andere BV"]["eenduidig"] == 1 and per_adm["Andere BV"]["twijfel"] == 0
        labo_voorbeeld = per_adm["Scope-test"]["voorbeelden"][0]
        assert labo_voorbeeld["voorkeur_naam"] == "Labo Derva B.V." and labo_voorbeeld["verliezer_namen"] == ["Labo Derva"]
        assert labo_voorbeeld["afgehandeld"] is False
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert verliezers(session, administratie_id=administratie_id) == {}  # dry-run schreef niets
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 0

        r = client.post("/crediteuren/dubbelen/auto-afhandelen", headers=headers, json={"dry_run": False})
        assert r.status_code == 200, r.text
        uit = r.json()
        assert uit["afgehandeld"] == 2 and uit["fouten"] == 0 and uit["twijfel"] == 1
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 2
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert verliezers(session, administratie_id=administratie_id) == {LABO: LABO_BV}
            assert voorkeur_van(session, administratie_id=administratie_id, vendor_id=LABO) == LABO_BV
            assert voorkeur_van(session, administratie_id=administratie_id, vendor_id=WOLA) == WOLA
            vc = session.get(VendorCache, (LABO, administratie_id))
            assert vc.dubbel_afgehandeld_bron == "auto" and vc.dubbel_afgehandeld_op is not None
            # Open boekvoorstel hervertaald, geboekt document onaangeroerd.
            assert session.get(Boekvoorstel, open_doc).vendor_id == LABO_BV
            assert session.get(Boekvoorstel, geboekt_doc).vendor_id == LABO
            log = session.scalars(select(CrediteurDubbelAfhandeling)).one()
            assert log.bron == "auto" and log.run_id == uuid.UUID(uit["run_id"])
            assert log.verhuisd["boekvoorstellen"] == [{"document_id": str(open_doc), "van_vendor_id": str(LABO)}]
            assert log.sleutels == [{"soort": "btw_nummer", "sleutel": BTW}, {"soort": "naam", "sleutel": "labo derva"}]
        with scoped_session(andere_administratie, actor_id=beheerder_id) as session:
            kaart = verliezers(session, administratie_id=andere_administratie)
            assert len(kaart) == 1 and set(kaart) <= {COOL, COOL_BV}
        # Lijst: alleen het twijfelcluster (Wola) blijft; KPI = 1.
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        assert body["totaal"] == 1 and body["tellers"] == {"clusters": 1, "eenduidig": 0, "administraties": 1}
        # Idempotent: tweede echte run doet niets.
        r2 = client.post("/crediteuren/dubbelen/auto-afhandelen", headers=headers, json={"dry_run": False}).json()
        assert r2["eenduidig"] == 0 and r2["afgehandeld"] == 0
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 2

    def test_scope_niet_beheerder_raakt_alleen_eigen_administratie(
        self, dubbelen, administratie_id, andere_administratie, gescoopte_gebruiker, beheerder_id
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        r = client.post("/crediteuren/dubbelen/auto-afhandelen", headers=headers, json={"dry_run": False})
        assert r.status_code == 200, r.text
        assert r.json()["afgehandeld"] == 1 and [a["administratie_naam"] for a in r.json()["administraties"]] == ["Scope-test"]
        with scoped_session(andere_administratie, actor_id=beheerder_id) as session:
            assert verliezers(session, administratie_id=andere_administratie) == {}
        # Filter op een administratie buiten scope = 404 (bewuste poort op een expliciet doel).
        r = client.post(
            "/crediteuren/dubbelen/auto-afhandelen",
            headers=headers,
            json={"dry_run": True, "administratie_id": str(andere_administratie)},
        )
        assert r.status_code == 404

    def test_systeem_run_zonder_actor_over_alle_actieve_administraties(
        self, dubbelen, administratie_id, andere_administratie, beheerder_id
    ) -> None:
        uit = afhandeling.auto_afhandelen(None, dry_run=False)
        assert uit.afgehandeld == 2 and uit.twijfel == 1
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            vc = session.get(VendorCache, (LABO, administratie_id))
            assert vc.voorkeur_vendor_id == LABO_BV and vc.dubbel_afgehandeld_bron == "auto"


class TestVerliezerOnbruikbaar:
    def test_leespaden_negeren_verliezer_en_vertalen_naar_voorkeur(
        self, dubbelen, administratie_id, beheerder_id
    ) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            # Vóór afhandeling: verliezer is gewoon zichtbaar/kiesbaar.
            assert LABO in {k.id for k in kandidaten_met_kenmerken(session, administratie_id=administratie_id)}
            assert (
                boekvoorstel_module._raad_vendor_id(session, administratie_id=administratie_id, leverancier_naam="labo derva")
                == LABO
            )
        assert LABO in {v.id for v in sync_service.lijst_vendors(administratie_id=administratie_id)}

        afhandeling.auto_afhandelen(_actor(beheerder_id), dry_run=False, administratie_id=administratie_id)

        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            # 1. Extractie-kandidaten (match_vendor + template herken_crediteur lezen déze lijst).
            ids = {k.id for k in kandidaten_met_kenmerken(session, administratie_id=administratie_id)}
            assert LABO not in ids and LABO_BV in ids
            # 2. Exacte naammatch: de verliezer heette precies "Labo Derva" — geen voorstel meer (nooit een verliezer).
            assert (
                boekvoorstel_module._raad_vendor_id(session, administratie_id=administratie_id, leverancier_naam="Labo Derva")
                is None
            )
            # 3. Geheugen-groep: verliezer vertaalt naar de voorkeur en zit zelf niet in de groep (geen dubbel gewicht).
            assert vendor_groep(session, administratie_id=administratie_id, vendor_id=LABO) == frozenset({LABO_BV})
            assert vendor_groep(session, administratie_id=administratie_id, vendor_id=LABO_BV) == frozenset({LABO_BV})
            # 4. Terugkerend-signaal: historie van de verliezer telt mee op de voorkeur.
            per = _facturen_per_vendor(session, administratie_id)
            assert LABO not in per and LABO_BV in per
            assert {f.datum for f in per[LABO_BV]} >= {date(2026, 7, 1), date(2026, 7, 2), date(2026, 8, 20)}
        # 5. Crediteuren-combobox (controlescherm).
        assert LABO not in {v.id for v in sync_service.lijst_vendors(administratie_id=administratie_id)}
        # 6. Een opgeslagen voorstel dat (race) nog een verliezer draagt, opent op de voorkeur.
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            doc = _document(session, administratie_id=administratie_id, vendor_id=LABO, status=DocumentStatus.TE_CONTROLEREN)
        voorstel = boekvoorstel_module.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc)
        assert voorstel.vendor_id == LABO_BV


class TestTerugdraaien:
    def test_herstelt_markering_kenmerk_en_boekvoorstel_met_audit(
        self, dubbelen, administratie_id, beheerder_id, admin_engine: Engine
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            doc = _document(session, administratie_id=administratie_id, vendor_id=LABO, status=DocumentStatus.TE_CONTROLEREN)
        afhandeling.auto_afhandelen(_actor(beheerder_id), dry_run=False, administratie_id=administratie_id)
        log = client.get("/crediteuren/afhandelingen", headers=headers).json()
        assert log["actief"] == 1
        afhandeling_id = log["regels"][0]["id"]
        assert log["regels"][0]["boekvoorstellen_hervertaald"] == 1

        pad = f"/crediteuren/afhandelingen/{afhandeling_id}/terugdraaien"
        assert client.post(pad, headers=headers, json={"reden": "  "}).status_code == 422
        r = client.post(pad, headers=headers, json={"reden": "Toch twee bedrijven"})
        assert r.status_code == 200, r.text
        assert r.json()["teruggedraaid_op"] is not None and r.json()["teruggedraaid_reden"] == "Toch twee bedrijven"
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            vc = session.get(VendorCache, (LABO, administratie_id))
            assert vc.voorkeur_vendor_id is None and vc.dubbel_afgehandeld_bron is None
            kenmerk = session.get(CrediteurKenmerk, (administratie_id, LABO_BV))
            assert kenmerk.kvk_nummer is None and kenmerk.btw_nummer == BTW  # oude stand van de voorkeur terug
            assert session.get(Boekvoorstel, doc).vendor_id == LABO
        assert _audit_acties(admin_engine, "crediteur_dubbel_teruggedraaid") == 1
        # Het cluster is weer zichtbaar (twee leden, dus opnieuw eenduidig — de mens meldt 'm zo nodig af).
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        assert any(c["soort"] == "btw_nummer" for c in body["rijen"])
        # Nogmaals = 422; log blijft zichtbaar als teruggedraaid.
        assert client.post(pad, headers=headers, json={"reden": "nogmaals"}).status_code == 422
        log = client.get("/crediteuren/afhandelingen", headers=headers).json()
        assert log["actief"] == 0 and log["teruggedraaid"] == 1
        assert client.post(f"/crediteuren/afhandelingen/{uuid.uuid4()}/terugdraaien", headers=headers, json={"reden": "x"}).status_code == 404


class TestExport:
    def test_opruimlijst_csv_bevat_verliezers_en_geen_teller(self, dubbelen, administratie_id, beheerder_id) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        leeg = client.get("/crediteuren/opruimlijst.csv", headers=headers)
        assert leeg.status_code == 200 and leeg.headers["content-type"].startswith("text/csv")
        assert leeg.text.lstrip("﻿").splitlines() == [
            "administratie;voorkeur;verliezer;verliezer_vendor_id;bron;afgehandeld_op;in_rlz"
        ]
        afhandeling.auto_afhandelen(_actor(beheerder_id), dry_run=False)
        r = client.get("/crediteuren/opruimlijst.csv", headers=headers)
        regels = r.text.lstrip("﻿").splitlines()
        assert len(regels) == 3  # kop + Labo Derva + Coolblue-verliezer
        labo = next(x for x in regels if "Labo Derva;" in x)
        assert labo.startswith("Scope-test;Labo Derva B.V.;Labo Derva;") and labo.endswith(";auto;" + labo.split(";")[5] + ";actief")
        assert "attachment" in r.headers["content-disposition"]


class TestKaartTelling:
    def test_verhuisd_geheugen_telt_op_voorkeur_na_afhandeling(self, dubbelen, administratie_id, beheerder_id) -> None:
        """Ná afhandeling draagt de voorkeur de gekopieerde observaties: de kaart van Labo Derva B.V. telt 3 boekstukken
        (2 eigen + INK-9 van de verliezer) — zichtbaar in een eventueel nieuw cluster mét een derde crediteur."""
        afhandeling.auto_afhandelen(_actor(beheerder_id), dry_run=False, administratie_id=administratie_id)
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(VendorCache(id=uuid.uuid4(), administratie_id=administratie_id, naam="LABO DERVA bv", brondata={}))
        clusters = service._clusters_voor_administratie(_actor(beheerder_id), administratie_id, "S")
        labo = next(c for c in clusters if c.soort == "naam" and c.sleutel == "labo derva")
        assert {k.naam for k in labo.crediteuren} == {"Labo Derva B.V.", "LABO DERVA bv"}
        assert next(k for k in labo.crediteuren if k.naam == "Labo Derva B.V.").aantal_boekingen == 3
        assert Decimal(labo.aantal_boekingen) == 3


class TestNazorgWerklijst:
    """Beslispunt 7 (besluit Peter 07-09): open legacy-werklijst-regels → markeringen via `handel_af` (bron 'mens',
    actor = aanmaker), regel 'gedaan' mét bron 'nazorg'. Dry-run schrijft niets; idempotent."""

    def _werklijst_regel(self, session, *, administratie_id, voorkeur, voorkeur_naam, te_archiveren, aanmaker) -> uuid.UUID:
        rij = CrediteurArchiveerWerklijst(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            voorkeur_vendor_id=voorkeur,
            voorkeur_naam=voorkeur_naam,
            te_archiveren=[{"vendor_id": str(v), "naam": n} for v, n in te_archiveren],
            status="open",
            aangemaakt_door=aanmaker,
        )
        session.add(rij)
        session.flush()
        return rij.id

    def test_dry_run_schrijft_niets_echte_run_markeert_logt_audit_en_is_idempotent(
        self, dubbelen, administratie_id, andere_administratie, beheerder_id, admin_engine: Engine
    ) -> None:
        # Coolblue (adm 2) is al automatisch afgehandeld: COOL = voorkeur, COOL_BV = verliezer.
        afhandeling.auto_afhandelen(_actor(beheerder_id), dry_run=False, administratie_id=andere_administratie)
        spook = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            regel_labo = self._werklijst_regel(
                session, administratie_id=administratie_id, voorkeur=LABO_BV, voorkeur_naam="Labo Derva B.V.",
                te_archiveren=[(LABO, "Labo Derva"), (spook, "Spook B.V.")], aanmaker=beheerder_id,
            )
        with scoped_session(andere_administratie, actor_id=beheerder_id) as session:
            regel_cool = self._werklijst_regel(
                session, administratie_id=andere_administratie, voorkeur=COOL, voorkeur_naam="Coolblue",
                te_archiveren=[(COOL_BV, "Coolblue B.V.")], aanmaker=beheerder_id,
            )
            regel_fout = self._werklijst_regel(
                session, administratie_id=andere_administratie, voorkeur=COOL_BV, voorkeur_naam="Coolblue B.V.",
                te_archiveren=[(COOL, "Coolblue")], aanmaker=beheerder_id,
            )
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 1

        # Dry-run: telt, schrijft niets.
        dry = afhandeling.nazorg_werklijst(dry_run=True)
        assert dry.dry_run and dry.regels == 3 and dry.om_te_zetten == 1 and dry.omgezet == 0
        assert dry.al_gemarkeerd == 1 and dry.niet_meer_bestaand == 1 and dry.fouten == 1 and dry.systeem_actor_fallback == 0
        per = {a.administratie_naam: a for a in dry.administraties}
        assert per["Scope-test"].details[0].uitkomst == "zou omzetten" and per["Scope-test"].details[0].om_te_zetten == ["Labo Derva"]
        assert per["Scope-test"].details[0].niet_meer_bestaand == ["Spook B.V."]
        fout = next(d for d in per["Andere BV"].details if d.uitkomst == "fout")
        assert fout.werklijst_id == regel_fout and "intussen zelf verliezer" in fout.fout
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert verliezers(session, administratie_id=administratie_id) == {}
            assert session.get(CrediteurArchiveerWerklijst, regel_labo).status == "open"
        assert _audit_acties(admin_engine, "crediteur_werklijst_nazorg") == 0
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 1

        # Echte run.
        echt = afhandeling.nazorg_werklijst(dry_run=False)
        assert echt.regels == 3 and echt.omgezet == 1 and echt.al_gemarkeerd == 1 and echt.niet_meer_bestaand == 1 and echt.fouten == 1
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert verliezers(session, administratie_id=administratie_id) == {LABO: LABO_BV}
            vc = session.get(VendorCache, (LABO, administratie_id))
            assert vc.dubbel_afgehandeld_bron == "mens" and vc.dubbel_afgehandeld_door == beheerder_id
            log = session.scalars(select(CrediteurDubbelAfhandeling)).one()
            assert log.bron == "mens" and log.run_id == echt.run_id and log.afgehandeld_door == beheerder_id
            assert log.classificatie_reden.startswith(afhandeling.NAZORG_PREFIX + "mens koos voorkeur 'Labo Derva B.V.' op ")
            assert "huidige classificatie: eenduidig: identieke naam" in log.classificatie_reden
            assert log.sleutels == [{"soort": "btw_nummer", "sleutel": BTW}, {"soort": "naam", "sleutel": "labo derva"}]
            regel = session.get(CrediteurArchiveerWerklijst, regel_labo)
            assert regel.status == "gedaan" and regel.gedaan_bron == "nazorg" and regel.gedaan_door == beheerder_id
            assert regel.gedaan_op is not None
            assert regel.hertoets_detail[str(LABO)].startswith("nazorg 07-09: gemarkeerd als verliezer (afhandeling ")
            assert regel.hertoets_detail[str(spook)] == "nazorg 07-09: niet meer in vendor_cache"
        with scoped_session(andere_administratie, actor_id=beheerder_id) as session:
            cool = session.get(CrediteurArchiveerWerklijst, regel_cool)
            assert cool.status == "gedaan" and cool.gedaan_bron == "nazorg"
            assert cool.hertoets_detail[str(COOL_BV)] == "nazorg 07-09: was al gemarkeerd als verliezer"
            assert session.get(CrediteurArchiveerWerklijst, regel_fout).status == "open"  # blijft zichtbaar, niets stil
            assert len(session.scalars(select(CrediteurDubbelAfhandeling)).all()) == 1  # alleen de auto-run van Coolblue
        assert _audit_acties(admin_engine, "crediteur_werklijst_nazorg") == 2
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 2
        # Export: alleen de nog-open (fout)regel staat nog als legacy in de lijst.
        csv_tekst = afhandeling.export_opruimlijst(_actor(beheerder_id))
        assert csv_tekst.count("werklijst (vóór 07-09)") == 1 and "Coolblue B.V.;Coolblue;" in csv_tekst

        # Tweede run: niets meer om te zetten, alleen de fout-regel blijft; geen nieuwe audit.
        opnieuw = afhandeling.nazorg_werklijst(dry_run=False)
        assert opnieuw.regels == 1 and opnieuw.omgezet == 0 and opnieuw.om_te_zetten == 0 and opnieuw.fouten == 1
        assert _audit_acties(admin_engine, "crediteur_werklijst_nazorg") == 2
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 2
