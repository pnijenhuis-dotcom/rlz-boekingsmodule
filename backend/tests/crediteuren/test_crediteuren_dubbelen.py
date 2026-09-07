# ruff: noqa: F811 — pytest-fixtures als parameters
"""Crediteuren-dubbelen v2 → schaalbaar (design-ronde 03-09, migratie 0100; blok B13 07-09, migratie 0117): kantoorbrede
lijst (bundeling per ledenset, sortering zwaarste sleutel eerst, classificatie eenduidig/twijfel, facetten, zoek,
paginering, scope), afmelden mét verplichte reden en "Voorkeur kiezen…" door de mens (verliezers in de module
onbruikbaar, verhuizing geheugen + kenmerk + IBAN mét audit — geen RLZ-call). De auto-run, terugdraaien, export en de
verliezer-uitsluiting in de leespaden staan in `test_auto_afhandeling.py`."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.crediteuren.models import CrediteurDubbelAfhandeling
from app.db.session import scoped_session
from app.documenten.models import CrediteurKenmerk, LeverancierIban
from app.geheugen.models import BoekingObservatie, ObservatieBron
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import VendorCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)

LABO_BV = uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111")
LABO = uuid.UUID("aaaaaaaa-2222-2222-2222-222222222222")
WOLA = uuid.UUID("bbbbbbbb-1111-1111-1111-111111111111")
WOLA_BV = uuid.UUID("bbbbbbbb-2222-2222-2222-222222222222")
COOL = uuid.UUID("cccccccc-1111-1111-1111-111111111111")
COOL_BV = uuid.UUID("cccccccc-2222-2222-2222-222222222222")
BTW = "BE0424612847"
IBAN = "NL91ABNA0417164300"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _vendor(admin_engine: Engine, aid: uuid.UUID, vendor_id: uuid.UUID, naam: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, :naam, '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": vendor_id, "aid": aid, "naam": naam},
        )


@pytest.fixture
def andere_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def dubbelen(
    admin_engine: Engine, administratie_id: uuid.UUID, andere_administratie: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    """Drie clusters: Labo Derva (btw + naam, adm 1), Wola/Wola b.v. (naam, KvK verschilt, adm 1), Coolblue (adm 2)."""
    _vendor(admin_engine, administratie_id, LABO_BV, "Labo Derva B.V.")
    _vendor(admin_engine, administratie_id, LABO, "Labo Derva")
    _vendor(admin_engine, administratie_id, WOLA, "Wola")
    _vendor(admin_engine, administratie_id, WOLA_BV, "Wola b.v.")
    _vendor(admin_engine, andere_administratie, COOL, "Coolblue")
    _vendor(admin_engine, andere_administratie, COOL_BV, "Coolblue B.V.")
    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id, vendor_id=LABO_BV, btw_nummer=BTW, btw_nummer_bron="factuur"
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id,
                vendor_id=LABO,
                btw_nummer=BTW,
                btw_nummer_bron="factuur",
                kvk_nummer="12345678",
                kvk_nummer_bron="factuur",
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id, vendor_id=WOLA, kvk_nummer="11111111", kvk_nummer_bron="factuur"
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id, vendor_id=WOLA_BV, kvk_nummer="22222222", kvk_nummer_bron="rlz"
            )
        )
        session.add(LeverancierIban(administratie_id=administratie_id, vendor_id=LABO, iban=IBAN, bron="rlz_seed"))
        for i, ref in enumerate(("INK-1", "INK-2")):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=LABO_BV,
                    gb_id=uuid.uuid4(),
                    bron=ObservatieBron.RLZ_SEED.value,
                    bron_datum=date(2026, 7, 1 + i),
                    boekstuk_ref=ref,
                )
            )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=LABO,
                gb_id=uuid.uuid4(),
                bron=ObservatieBron.RLZ_SEED.value,
                bron_datum=date(2026, 8, 20),
                boekstuk_ref="INK-9",
            )
        )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=LABO,
                gb_id=uuid.uuid4(),
                regel_sleutel="lab kosten",
                bron=ObservatieBron.APP.value,
                bron_datum=date(2026, 8, 25),
            )
        )


def _audit_acties(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar() or 0
        )


class TestLijst:
    def test_bundelt_sorteert_facetten_zoekt_pagineert(
        self, dubbelen, administratie_id, andere_administratie, beheerder_id
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.get("/crediteuren/dubbelen", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        # Tellers: clusters = TWIJFEL (Wola: KvK verschilt), eenduidig = Labo (naam identiek, verliezer 1 boeking) +
        # Coolblue (naam identiek, 0 boekingen).
        assert body["totaal"] == 3 and body["tellers"] == {"clusters": 1, "eenduidig": 2, "administraties": 2}
        eerste = body["rijen"][0]
        assert eerste["eenduidig"] is True and eerste["classificatie_reden"].startswith("eenduidig: identieke naam")
        # Labo Derva: zelfde btw én genormaliseerde naam → één cluster mét twee chips, zwaarste sleutel btw bovenaan.
        assert eerste["soort"] == "btw_nummer" and eerste["chips"] == ["zelfde btw-nummer", "naam ≈"]
        assert [s["soort"] for s in eerste["sleutels"]] == ["btw_nummer", "naam"]
        kaarten = {k["naam"]: k for k in eerste["crediteuren"]}
        assert (
            kaarten["Labo Derva B.V."]["aantal_boekingen"] == 2
            and kaarten["Labo Derva B.V."]["laatst_geboekt"] == "2026-07-02"
        )
        assert kaarten["Labo Derva"]["aantal_boekingen"] == 1 and kaarten["Labo Derva"]["ibans"] == [IBAN]
        assert eerste["laatst_geboekt"] == "2026-08-20" and eerste["afmelden_primair"] is False
        # Voorkeur vooringevuld: meest gebruikt (2 boekingen) wint.
        assert eerste["voorkeur_suggestie"] == str(LABO_BV)
        # Wola: naam-cluster mét aantoonbaar verschillende KvK → afmelden primair.
        wola = next(c for c in body["rijen"] if c["soort"] == "naam" and c["administratie_id"] == str(administratie_id))
        assert wola["kvk_verschilt"] is True and wola["afmelden_primair"] is True
        assert wola["chips"] == ["naam ≈", "verschillend KvK — géén dubbel"]
        assert wola["eenduidig"] is False and "verschillend KvK-nummer" in wola["classificatie_reden"]
        cool = next(c for c in body["rijen"] if c["administratie_id"] == str(andere_administratie))
        assert cool["kvk_verschilt"] is False and cool["afmelden_primair"] is False and cool["eenduidig"] is True
        assert client.get("/crediteuren/dubbelen?classificatie=twijfel", headers=headers).json()["totaal"] == 1
        assert client.get("/crediteuren/dubbelen?classificatie=eenduidig", headers=headers).json()["totaal"] == 2
        assert client.get("/crediteuren/dubbelen?classificatie=onzin", headers=headers).status_code == 422
        # Facetten + filters.
        assert body["facetten"]["sleutels"] == {"btw_nummer": 1, "naam": 2}
        assert {f["naam"]: f["aantal"] for f in body["facetten"]["administraties"]} == {"Scope-test": 2, "Andere BV": 1}
        assert client.get("/crediteuren/dubbelen?sleutel=naam", headers=headers).json()["totaal"] == 2
        assert (
            client.get(f"/crediteuren/dubbelen?administratie_id={andere_administratie}", headers=headers).json()[
                "totaal"
            ]
            == 1
        )
        assert client.get("/crediteuren/dubbelen?q=coolblue", headers=headers).json()["totaal"] == 1
        assert client.get(f"/crediteuren/dubbelen?q={IBAN}", headers=headers).json()["totaal"] == 1
        assert client.get("/crediteuren/dubbelen?sleutel=onzin", headers=headers).status_code == 422
        p2 = client.get("/crediteuren/dubbelen?pagina=2", headers=headers).json()
        assert p2["totaal"] == 3 and p2["rijen"] == [] and p2["per_pagina"] == 25
        assert client.get("/crediteuren/dubbelen/stand", headers=headers).json() == {
            "clusters": 1,
            "eenduidig": 2,
            "administraties": 2,
        }

    def test_niet_beheerder_met_scope_ziet_alleen_eigen_administratie(
        self, dubbelen, administratie_id, andere_administratie, gescoopte_gebruiker
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        assert body["totaal"] == 2 and body["tellers"]["administraties"] == 1
        assert {c["administratie_id"] for c in body["rijen"]} == {str(administratie_id)}
        assert [f["naam"] for f in body["facetten"]["administraties"]] == ["Scope-test"]
        # Buiten scope = 404, óók met een expliciet filter (filter, geen poort: leeg resultaat).
        assert (
            client.get(f"/crediteuren/dubbelen?administratie_id={andere_administratie}", headers=headers).json()[
                "totaal"
            ]
            == 0
        )
        r = client.get(
            f"/crediteuren/dubbelen/{andere_administratie}/cluster-detail?vendor_ids={COOL}&vendor_ids={COOL_BV}",
            headers=headers,
        )
        assert r.status_code == 404
        r = client.post(
            f"/crediteuren/dubbelen/{andere_administratie}/afhandelen",
            headers=headers,
            json={"voorkeur_vendor_id": str(COOL), "verliezer_vendor_ids": [str(COOL_BV)]},
        )
        assert r.status_code == 404
        assert client.get("/crediteuren/dubbelen/stand", headers=headers).json() == {
            "clusters": 1,
            "eenduidig": 1,
            "administraties": 1,
        }


class TestAfmelden:
    def test_reden_verplicht_cluster_verdwijnt_en_komt_niet_terug(
        self, dubbelen, administratie_id, beheerder_id, admin_engine
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        pad = f"/crediteuren/dubbelen/{administratie_id}/afmelden"
        assert client.post(pad, headers=headers, json={"vendor_ids": [str(WOLA), str(WOLA_BV)]}).status_code == 422
        assert (
            client.post(
                pad, headers=headers, json={"vendor_ids": [str(WOLA), str(WOLA_BV)], "reden": "   "}
            ).status_code
            == 422
        )
        # Geen bestaand cluster voor deze combinatie → fail-closed 422.
        r = client.post(pad, headers=headers, json={"vendor_ids": [str(WOLA), str(LABO)], "reden": "andere entiteit"})
        assert r.status_code == 422
        r = client.post(
            pad,
            headers=headers,
            json={"vendor_ids": [str(WOLA), str(WOLA_BV)], "reden": "verschillende KvK — twee bedrijven"},
        )
        assert r.status_code == 200, r.text
        afmelding_id = r.json()["afmelding_id"]
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        assert body["totaal"] == 2 and all(
            c["soort"] != "naam" or c["administratie_id"] != str(administratie_id) for c in body["rijen"]
        )
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgemeld") == 1
        # Idempotent: tweede keer dezelfde rij, geen tweede audit.
        r = client.post(pad, headers=headers, json={"vendor_ids": [str(WOLA_BV), str(WOLA)], "reden": "nogmaals"})
        assert r.status_code == 200 and r.json()["afmelding_id"] == afmelding_id
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgemeld") == 1


class TestAfhandelenMens:
    def test_voorkeur_kiezen_verhuist_markeert_en_audit_geen_rlz(
        self, dubbelen, administratie_id, beheerder_id, admin_engine
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        detail = client.get(
            f"/crediteuren/dubbelen/{administratie_id}/cluster-detail?vendor_ids={LABO_BV}&vendor_ids={LABO}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        d = detail.json()
        assert d["voorkeur_suggestie"] == str(LABO_BV) and d["eenduidig"] is True
        assert "open_posten" not in d  # geen RLZ-toets meer (07-09)

        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/afhandelen",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "verliezer_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 200, r.text
        uit = r.json()
        assert uit["melding"].startswith("afgehandeld — Labo Derva is in de module onbruikbaar")
        assert uit["geheugen_verhuisd"] == 2 and uit["kenmerk_verhuisd"] is True and uit["ibans_verhuisd"] == 1

        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            obs = session.scalars(select(BoekingObservatie).where(BoekingObservatie.vendor_id == LABO_BV)).all()
            assert len(obs) == 4  # 2 eigen seed + 2 verhuisd (seed + app), bron-rijen blijven staan
            assert {o.regel_sleutel for o in obs} == {None, "lab kosten"}
            assert len(session.scalars(select(BoekingObservatie).where(BoekingObservatie.vendor_id == LABO)).all()) == 2
            kenmerk = session.get(CrediteurKenmerk, (administratie_id, LABO_BV))
            assert kenmerk is not None and kenmerk.btw_nummer == BTW and kenmerk.kvk_nummer == "12345678"
            assert session.get(LeverancierIban, (administratie_id, LABO_BV, IBAN)) is not None
            verliezer = session.get(VendorCache, (LABO, administratie_id))
            assert (
                verliezer is not None
                and verliezer.voorkeur_vendor_id == LABO_BV
                and verliezer.dubbel_afgehandeld_bron == "mens"
                and verliezer.dubbel_afgehandeld_door == beheerder_id
            )
            assert session.get(VendorCache, (LABO_BV, administratie_id)).voorkeur_vendor_id is None
            log = session.scalars(select(CrediteurDubbelAfhandeling)).all()
            assert len(log) == 1 and log[0].bron == "mens" and log[0].verliezers == [
                {"vendor_id": str(LABO), "naam": "Labo Derva"}
            ]
            assert [(p[0], p[1]) for p in log[0].verhuisd["geheugen"]].__len__() == 2
            assert log[0].verhuisd["kenmerk_oud"]["kvk_nummer"] is None and log[0].verhuisd["ibans"] == [IBAN]
        assert _audit_acties(admin_engine, "crediteur_geheugen_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_kenmerk_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_iban_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 1

        # Het cluster verdwijnt uit de lijst (de verliezer is geen dubbel meer) — niets blijft "klaargezet" hangen.
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        assert body["totaal"] == 2 and all(c["soort"] != "btw_nummer" for c in body["rijen"])
        assert body["tellers"] == {"clusters": 1, "eenduidig": 1, "administraties": 2}
        # Nogmaals afhandelen op een al-verliezer = 422 fail-closed, niets dubbel.
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/afhandelen",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "verliezer_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 422 and "al afgehandeld" in r.json()["detail"]
        assert _audit_acties(admin_engine, "crediteur_dubbel_afgehandeld") == 1
        # Log-lijst kantoorbreed.
        log = client.get("/crediteuren/afhandelingen", headers=headers).json()
        assert log["actief"] == 1 and log["teruggedraaid"] == 0
        assert log["regels"][0]["voorkeur_naam"] == "Labo Derva B.V."

    def test_zonder_verliezer_of_zelfde_id_422(self, dubbelen, administratie_id, beheerder_id) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/afhandelen",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "verliezer_vendor_ids": [str(LABO_BV)]},
        )
        assert r.status_code == 422
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/afhandelen",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "verliezer_vendor_ids": [str(uuid.uuid4())]},
        )
        assert r.status_code == 422
