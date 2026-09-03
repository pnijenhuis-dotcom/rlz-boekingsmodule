# ruff: noqa: F811 — pytest-fixtures als parameters
"""Crediteuren-dubbelen v2 (design-ronde 03-09, mockup crediteuren-dubbelen-v2.html, migratie 0100): kantoorbrede
lijst (bundeling per ledenset, sortering zwaarste sleutel eerst, facetten, zoek, paginering, scope), afmelden mét
verplichte reden, "Voorkeur kiezen & rest archiveren…" (LIVE open-posten-toets fail-closed, werklijst-regel,
verhuizing geheugen + kenmerk + IBAN mét audit — geen RLZ-write) en de dagelijkse hertoets die afvinkt."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.crediteuren import service
from app.crediteuren.models import CrediteurArchiveerWerklijst
from app.db.session import scoped_session
from app.documenten.models import CrediteurKenmerk, LeverancierIban
from app.geheugen.models import BoekingObservatie, ObservatieBron
from app.main import app
from app.rlz.client import RlzApiError
from app.security.tokens import create_access_token
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


class FakeRlz:
    """RLZ-leesroutes zoals de service ze gebruikt: PurchaseInvoices per Entity + Vendors/{id}?fields=all."""

    def __init__(
        self,
        *,
        open_posten: dict[uuid.UUID, list[dict]] | None = None,
        gearchiveerd: set[uuid.UUID] = frozenset(),
        afwezig: set[uuid.UUID] = frozenset(),
        fout: Exception | None = None,
    ) -> None:
        self.open_posten = open_posten or {}
        self.gearchiveerd = set(gearchiveerd)
        self.afwezig = set(afwezig)
        self.fout = fout
        self.aanroepen: list[str] = []

    def get(self, path: str, *, params: dict | None = None):
        self.aanroepen.append(path)
        if self.fout is not None:
            raise self.fout
        if path == "PurchaseInvoices":
            vendor = uuid.UUID((params or {})["$filter"].split("Entity/id eq ")[1].split(" ")[0])
            return {"value": self.open_posten.get(vendor, [])}
        if path.startswith("Vendors/"):
            vid = uuid.UUID(path.split("/")[1])
            if vid in self.afwezig:
                raise RlzApiError(404, "GET", path, "not found")
            return {"id": str(vid), "IsArchived": vid in self.gearchiveerd, "RecordStatus": 2}
        raise AssertionError(f"onverwachte RLZ-call {path}")

    def close(self) -> None:
        pass


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
        assert body["totaal"] == 3 and body["tellers"] == {"clusters": 3, "klaargezet": 0, "administraties": 2}
        eerste = body["rijen"][0]
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
        cool = next(c for c in body["rijen"] if c["administratie_id"] == str(andere_administratie))
        assert cool["kvk_verschilt"] is False and cool["afmelden_primair"] is False
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
            "clusters": 3,
            "klaargezet": 0,
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
            f"/crediteuren/dubbelen/{andere_administratie}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(COOL), "overige_vendor_ids": [str(COOL_BV)]},
        )
        assert r.status_code == 404
        assert client.get("/crediteuren/dubbelen/stand", headers=headers).json()["clusters"] == 2


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


class TestArchiveer:
    def test_verhuist_geheugen_kenmerk_iban_met_audit_en_zet_werklijst_klaar(
        self, dubbelen, administratie_id, beheerder_id, admin_engine, monkeypatch
    ) -> None:
        rlz = FakeRlz()
        monkeypatch.setattr(service, "_open_client", lambda aid: rlz)
        headers = _bearer(beheerder_id, rol="beheerder")
        detail = client.get(
            f"/crediteuren/dubbelen/{administratie_id}/cluster-detail?vendor_ids={LABO_BV}&vendor_ids={LABO}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        d = detail.json()
        assert d["toets_ok"] is True and d["voorkeur_suggestie"] == str(LABO_BV)
        assert d["open_posten"] == {str(LABO_BV): [], str(LABO): []}
        assert rlz.aanroepen == ["PurchaseInvoices", "PurchaseInvoices"]  # detail toetst álle leden
        rlz.aanroepen.clear()

        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 200, r.text
        uit = r.json()
        assert uit["melding"] == "klaargezet — archiveer in RLZ: Labo Derva"
        assert uit["geheugen_verhuisd"] == 2 and uit["kenmerk_verhuisd"] is True and uit["ibans_verhuisd"] == 1
        assert rlz.aanroepen == ["PurchaseInvoices"]  # alleen de te archiveren crediteur, alleen lezen

        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            obs = session.scalars(select(BoekingObservatie).where(BoekingObservatie.vendor_id == LABO_BV)).all()
            assert len(obs) == 4  # 2 eigen seed + 2 verhuisd (seed + app), bron-rijen blijven staan
            assert {o.regel_sleutel for o in obs} == {None, "lab kosten"}
            assert (
                session.scalars(select(BoekingObservatie).where(BoekingObservatie.vendor_id == LABO)).all().__len__()
                == 2
            )
            kenmerk = session.get(CrediteurKenmerk, (administratie_id, LABO_BV))
            assert kenmerk is not None and kenmerk.btw_nummer == BTW and kenmerk.kvk_nummer == "12345678"
            assert session.get(LeverancierIban, (administratie_id, LABO_BV, IBAN)) is not None
            werk = session.scalars(select(CrediteurArchiveerWerklijst)).all()
            assert (
                len(werk) == 1
                and werk[0].status == "open"
                and werk[0].te_archiveren == [{"vendor_id": str(LABO), "naam": "Labo Derva"}]
            )
        assert _audit_acties(admin_engine, "crediteur_geheugen_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_kenmerk_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_iban_verhuisd") == 1
        assert _audit_acties(admin_engine, "crediteur_archiveer_klaargezet") == 1

        # Cluster blijft zichtbaar als "klaargezet" en telt niet meer als te behandelen.
        body = client.get("/crediteuren/dubbelen", headers=headers).json()
        labo = next(c for c in body["rijen"] if c["soort"] == "btw_nummer")
        assert (
            labo["klaargezet"]["namen"] == ["Labo Derva"] and labo["klaargezet"]["werklijst_id"] == uit["werklijst_id"]
        )
        assert body["tellers"] == {"clusters": 2, "klaargezet": 1, "administraties": 2}
        # Idempotent: nogmaals = dezelfde regel, niets dubbel.
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO)]},
        )
        assert (
            r.status_code == 200
            and r.json()["al_klaargezet"] is True
            and r.json()["werklijst_id"] == uit["werklijst_id"]
        )
        assert _audit_acties(admin_engine, "crediteur_archiveer_klaargezet") == 1
        werklijst = client.get("/crediteuren/werklijst", headers=headers).json()
        assert (
            werklijst["open"] == 1
            and werklijst["gedaan"] == 0
            and werklijst["regels"][0]["voorkeur_naam"] == "Labo Derva B.V."
        )

    def test_weigert_bij_open_posten_en_bij_mislukte_toets(
        self, dubbelen, administratie_id, beheerder_id, admin_engine, monkeypatch
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        open_post = {
            "id": "f-1",
            "Reference": "F-2026-17",
            "Date": "2026-08-01T00:00:00",
            "Status": 2,
            "BaseRemainingAmount": "121.00",
        }
        gesloten = {"id": "f-2", "Reference": "F-2026-16", "Status": 3, "BaseRemainingAmount": "0"}
        rlz = FakeRlz(open_posten={LABO: [open_post, gesloten]})
        monkeypatch.setattr(service, "_open_client", lambda aid: rlz)
        d = client.get(
            f"/crediteuren/dubbelen/{administratie_id}/cluster-detail?vendor_ids={LABO_BV}&vendor_ids={LABO}",
            headers=headers,
        ).json()
        assert d["toets_ok"] is True and [p["referentie"] for p in d["open_posten"][str(LABO)]] == ["F-2026-17"]
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 409, r.text
        assert "eerst afletteren" in r.json()["detail"]["bericht"]
        assert r.json()["detail"]["open_posten"][str(LABO)][0]["open_bedrag"] == "121.00"
        # Andersom (Labo Derva B.V. archiveren) heeft géén open posten → zou wél mogen; hier alleen toetsen dat
        # niets geschreven is ná de blokkade.
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert session.scalars(select(CrediteurArchiveerWerklijst)).all() == []
        assert _audit_acties(admin_engine, "crediteur_archiveer_klaargezet") == 0

        # RLZ onbereikbaar = toets mislukt = fail-closed (409, niets gewijzigd).
        monkeypatch.setattr(
            service, "_open_client", lambda aid: FakeRlz(fout=RlzApiError(503, "GET", "PurchaseInvoices", "down"))
        )
        d = client.get(
            f"/crediteuren/dubbelen/{administratie_id}/cluster-detail?vendor_ids={LABO_BV}&vendor_ids={LABO}",
            headers=headers,
        ).json()
        assert d["toets_ok"] is False and "mislukt" in d["toets_fout"]
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 409 and "opnieuw proberen" in r.json()["detail"]
        # Voorkeur in de overige-lijst / lege overige = 422.
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=headers,
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO_BV)]},
        )
        assert r.status_code == 422

    def test_open_posten_toets_valt_terug_op_entity_filter_bij_400(self) -> None:
        class Client400:
            def __init__(self) -> None:
                self.filters: list[str] = []

            def get(self, path, *, params=None):
                self.filters.append(params["$filter"])
                if "BaseRemainingAmount" in params["$filter"]:
                    raise RlzApiError(400, "GET", path, "invalid")
                return {
                    "value": [
                        {"id": "x", "Status": 2, "BaseRemainingAmount": 5},
                        {"id": "y", "Status": 1, "BaseRemainingAmount": 5},
                    ]
                }

        c = Client400()
        posten = service.open_posten_van_crediteur(c, LABO)  # type: ignore[arg-type]
        assert [p.rlz_document_id for p in posten] == ["x"]
        assert len(c.filters) == 2 and c.filters[1] == f"Entity/id eq {LABO}"


class TestWerklijstHertoets:
    def _klaarzetten(self, administratie_id, beheerder_id, monkeypatch) -> uuid.UUID:
        monkeypatch.setattr(service, "_open_client", lambda aid: FakeRlz())
        r = client.post(
            f"/crediteuren/dubbelen/{administratie_id}/archiveer",
            headers=_bearer(beheerder_id, rol="beheerder"),
            json={"voorkeur_vendor_id": str(LABO_BV), "overige_vendor_ids": [str(LABO)]},
        )
        assert r.status_code == 200, r.text
        return uuid.UUID(r.json()["werklijst_id"])

    def test_hertoets_zet_gedaan_bij_isarchived_of_afwezig(
        self, dubbelen, administratie_id, beheerder_id, admin_engine, monkeypatch
    ) -> None:
        werklijst_id = self._klaarzetten(administratie_id, beheerder_id, monkeypatch)
        # Nog actief in RLZ → blijft open, mét hertoets-detail.
        uit = service.hertoets_werklijst(client_factory=lambda aid: FakeRlz())
        assert uit[administratie_id] == {"open": 1, "gedaan": 0, "nog_open": 1}
        with scoped_session(administratie_id) as session:
            rij = session.get(CrediteurArchiveerWerklijst, werklijst_id)
            assert (
                rij is not None
                and rij.status == "open"
                and rij.hertoets_detail == {str(LABO): "actief"}
                and rij.laatste_hertoets_op is not None
            )
        # IsArchived: true → gedaan mét audit (systeem-actor).
        uit = service.hertoets_werklijst(client_factory=lambda aid: FakeRlz(gearchiveerd={LABO}))
        assert uit[administratie_id] == {"open": 1, "gedaan": 1, "nog_open": 0}
        with scoped_session(administratie_id) as session:
            rij = session.get(CrediteurArchiveerWerklijst, werklijst_id)
            assert rij.status == "gedaan" and rij.gedaan_bron == "hertoets" and rij.gedaan_op is not None
        assert _audit_acties(admin_engine, "crediteur_archiveer_gedaan") == 1
        # Niets open meer → administratie niet in het rapport.
        assert service.hertoets_werklijst(client_factory=lambda aid: FakeRlz()) == {}
        # Zodra de crediteur in RLZ gearchiveerd is, verdwijnt het cluster via de Vendors-sync (is_gearchiveerd).
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.vendor_cache SET is_gearchiveerd = true WHERE id = :id"), {"id": LABO}
            )
        body = client.get("/crediteuren/dubbelen", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert all(c["soort"] != "btw_nummer" for c in body["rijen"])
        werklijst = client.get("/crediteuren/werklijst", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert werklijst["open"] == 0 and werklijst["gedaan"] == 1

    def test_afwezig_404_telt_als_gearchiveerd_en_fout_stopt_de_rest_niet(
        self, dubbelen, administratie_id, beheerder_id, monkeypatch
    ) -> None:
        werklijst_id = self._klaarzetten(administratie_id, beheerder_id, monkeypatch)
        uit = service.hertoets_werklijst(client_factory=lambda aid: FakeRlz(afwezig={LABO}))
        assert uit[administratie_id]["gedaan"] == 1
        with scoped_session(administratie_id) as session:
            assert session.get(CrediteurArchiveerWerklijst, werklijst_id).hertoets_detail == {str(LABO): "gearchiveerd"}

    def test_fout_per_administratie_is_zichtbaar(self, dubbelen, administratie_id, beheerder_id, monkeypatch) -> None:
        self._klaarzetten(administratie_id, beheerder_id, monkeypatch)

        def kapot(aid):
            raise RuntimeError("geen credentials")

        uit = service.hertoets_werklijst(client_factory=kapot)
        assert uit[administratie_id] == "RuntimeError: geen credentials"

    def test_handmatig_markeer_als_gedaan(
        self, dubbelen, administratie_id, beheerder_id, admin_engine, monkeypatch
    ) -> None:
        werklijst_id = self._klaarzetten(administratie_id, beheerder_id, monkeypatch)
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.post(f"/crediteuren/werklijst/{werklijst_id}/gedaan", headers=headers)
        assert r.status_code == 200 and r.json()["status"] == "gedaan" and r.json()["gedaan_bron"] == "handmatig"
        assert _audit_acties(admin_engine, "crediteur_archiveer_gedaan") == 1
        # Idempotent + onbekend = 404.
        assert client.post(f"/crediteuren/werklijst/{werklijst_id}/gedaan", headers=headers).status_code == 200
        assert _audit_acties(admin_engine, "crediteur_archiveer_gedaan") == 1
        assert client.post(f"/crediteuren/werklijst/{uuid.uuid4()}/gedaan", headers=headers).status_code == 404
