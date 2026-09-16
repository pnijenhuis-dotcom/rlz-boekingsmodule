# ruff: noqa: F811 — fixtures uit tests.auth.conftest worden via import geregistreerd en als parameter gebruikt
"""Intercompany blok A (16-09): identiteit-sync, relatie-afleiding (kvk > btw > naam, doorbelasting → bevestigd,
mens-rijen ongemoeid), RC-koppelingen (over en weer / eenzijdig), Beheerder-poort en routes. Geen RLZ-calls: een
kleine fake beantwoordt `AdministrationSettings` en `Customers` per rlz_admin_id."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.models import CrediteurKenmerk
from app.doorbelasting import intercompany as doorbelasting_intercompany
from app.doorbelasting.models import DoorbelastingMapping, IntercompanyTegenpartij
from app.intercompany import identiteit, rc_koppelingen, relaties
from app.intercompany.models import AdministratieIdentiteit, IntercompanyRelatie, RcKoppeling
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import VendorCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

KVK_A = "12345678"
KVK_B = "90425405"
BTW_B = "NL001234567B01"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class FakeRlzClient:
    """Duck-typed RlzClient: `get("AdministrationSettings")` / `get("Customers")` per administratie."""

    def __init__(self, rid: str, settings: dict[str, dict[str, Any]], customers: dict[str, list[dict[str, Any]]]):
        self.rid = rid
        self._settings = settings
        self._customers = customers
        self.calls: list[str] = []
        self.gesloten = False

    def for_administration(self, rid: str) -> FakeRlzClient:
        self.rid = rid
        return self

    def close(self) -> None:
        self.gesloten = True

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(path)
        if path == "AdministrationSettings":
            return {"value": [self._settings.get(self.rid, {})]}
        if path == "Customers":
            skip = int((params or {}).get("$skip", "0"))
            return {"value": self._customers.get(self.rid, [])[skip:]}
        raise AssertionError(f"onverwachte RLZ-route {path}")


@pytest.fixture
def adm_b(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": "Kempen Facilities B.V.", "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def adm_c(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": "Derde Groepsmaatschappij B.V.", "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def adm_a(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'Kempen B.V.' WHERE id = :id"), {"id": administratie_id}
        )
    return administratie_id


@pytest.fixture
def rlz(monkeypatch: pytest.MonkeyPatch, adm_a: uuid.UUID, adm_b: uuid.UUID) -> dict[str, Any]:
    """Fake-RLZ mét de identiteiten van A (Kempen B.V.) en B (Kempen Facilities); Customers per test vulbaar."""
    settings = {
        f"rlz-{adm_a}": {"CompanyName": "Kempen B.V.", "ChamberOfCommerceNumber": KVK_A},
        f"rlz-{adm_b}": {
            "CompanyName": "Kempen Facilities B.V.",
            "ChamberOfCommerceNumber": KVK_B,
            "StandardBusinessIdentification": "6420",
        },
    }
    customers: dict[str, list[dict[str, Any]]] = {}
    clients: list[FakeRlzClient] = []

    def fabriek(rid: str) -> FakeRlzClient:
        c = FakeRlzClient(rid, settings, customers)
        clients.append(c)
        return c

    monkeypatch.setattr(identiteit, "client_voor_rlz_admin_id", fabriek)
    return {"settings": settings, "customers": customers, "clients": clients}


def _vendor(aid: uuid.UUID, naam: str, *, kvk: str | None = None, btw: str | None = None) -> uuid.UUID:
    vid = uuid.uuid4()
    with scoped_session(aid) as session:
        session.add(
            VendorCache(
                id=vid,
                administratie_id=aid,
                naam=naam,
                brondata={"ChamberOfCommerceNumber": kvk} if kvk else {},
            )
        )
        if btw:
            session.add(
                CrediteurKenmerk(administratie_id=aid, vendor_id=vid, btw_nummer=btw, btw_nummer_bron="factuur")
            )
    return vid


def _relaties(aid: uuid.UUID) -> list[IntercompanyRelatie]:
    with scoped_session(None) as session:
        rijen = list(session.query(IntercompanyRelatie).filter_by(administratie_a_id=aid).all())
        session.expunge_all()
        return rijen


# --- naam_norm -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ruw", "verwacht"),
    [
        ("Kempen Facilities B.V.", "kempen facilities"),
        ("Rekening-courant Kempen B.V.", "rekening courant kempen"),
        ("KEMPEN BV", "kempen"),
        ("Universal Steigerbouw Nederland b.v.", "universal steigerbouw nederland"),
        ("Kempen Holding N.V.", "kempen holding"),
        ("Cv-ketel Service", "cv ketel service"),
        (None, ""),
    ],
)
def test_naam_norm(ruw: str | None, verwacht: str) -> None:
    assert identiteit.naam_norm(ruw) == verwacht


# --- identiteit ------------------------------------------------------------------------------------------------------


def test_sync_identiteiten_leest_kvk_en_naam_en_bewaart_afkortingen(adm_a, adm_b, rlz) -> None:
    with scoped_session(None) as session:
        session.add(AdministratieIdentiteit(administratie_id=adm_b, afkortingen=["KF"], bron="rlz"))
    uitkomsten = identiteit.sync_identiteiten()
    assert {u.stand for u in uitkomsten} == {"gelezen"}
    with scoped_session(None) as session:
        b = session.get(AdministratieIdentiteit, adm_b)
        a = session.get(AdministratieIdentiteit, adm_a)
        assert (b.kvk, b.naam, b.naam_norm, b.sbi, b.afkortingen, b.bron) == (
            KVK_B,
            "Kempen Facilities B.V.",
            "kempen facilities",
            "6420",
            ["KF"],
            "rlz",
        )
        assert (a.kvk, a.naam_norm, a.btw) == (KVK_A, "kempen", None)
        assert a.gelezen_op is not None
    assert all(c.gesloten for c in rlz["clients"])


def test_sync_identiteiten_mens_rij_niet_overschreven_en_fout_zichtbaar(adm_a, adm_b, rlz) -> None:
    with scoped_session(None) as session:
        session.add(AdministratieIdentiteit(administratie_id=adm_a, kvk="00000001", naam="Handmatig", bron="mens"))

    def lezer(aid: uuid.UUID) -> identiteit.Identiteit:
        if aid == adm_b:
            raise RuntimeError("RLZ 503")
        return identiteit.lees_identiteit(aid)

    uitkomsten = identiteit.sync_identiteiten(lezer=lezer)
    per = {u.administratie_id: u for u in uitkomsten}
    assert per[adm_a].stand == "mens"
    assert per[adm_b].stand == "fout" and "RLZ 503" in (per[adm_b].melding or "")
    with scoped_session(None) as session:
        assert session.get(AdministratieIdentiteit, adm_a).kvk == "00000001"


# --- relaties --------------------------------------------------------------------------------------------------------


def test_afleiding_kvk_boven_btw_boven_naam_en_naam_only_niet_actief(adm_a, adm_b, rlz) -> None:
    identiteit.sync_identiteiten()
    with scoped_session(None) as session:
        session.get(AdministratieIdentiteit, adm_b).btw = BTW_B
    v_kvk = _vendor(adm_a, "KF Facilitair (oude naam)", kvk=KVK_B)
    v_btw = _vendor(adm_a, "Kempen Fac.", btw=BTW_B)
    v_naam = _vendor(adm_a, "Kempen Facilities BV")
    _vendor(adm_a, "Bouwmaat Eindhoven B.V.", kvk="11112222")

    uitkomst = relaties.leid_relaties_af()

    assert uitkomst.relaties_nieuw == 3 and uitkomst.per_basis == {"kvk": 1, "btw": 1, "naam": 1}
    per_entity = {r.entity_in_a: r for r in _relaties(adm_a)}
    assert per_entity[v_kvk].basis == "kvk" and per_entity[v_kvk].richting == "crediteur"
    assert per_entity[v_btw].basis == "btw"
    assert per_entity[v_naam].basis == "naam" and per_entity[v_naam].status == "afgeleid"
    assert all(r.administratie_b_id == adm_b and r.bron == "afgeleid" for r in per_entity.values())
    actief = {p.entity_in_a for p in relaties.actieve_paren()}
    assert actief == {v_kvk, v_btw}, "naam-only telt pas mee ná bevestiging"
    # Herafleiding = idempotent.
    opnieuw = relaties.leid_relaties_af()
    assert (opnieuw.relaties_nieuw, opnieuw.relaties_ongewijzigd) == (0, 3)


def test_zelfde_kvk_bij_twee_administraties_geeft_beide_richtingen(adm_a, adm_b, rlz) -> None:
    identiteit.sync_identiteiten()
    v_in_a = _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)  # B levert aan A
    customer_in_b = uuid.uuid4()
    rlz["customers"][f"rlz-{adm_b}"] = [
        {"id": str(customer_in_b), "Name": "Kempen B.V.", "ChamberOfCommerceNumber": KVK_A},
        {"id": str(uuid.uuid4()), "Name": "Particulier Jansen", "ChamberOfCommerceNumber": None},
    ]
    uitkomst = relaties.leid_relaties_af()
    assert uitkomst.debiteuren_bekeken == 2 and uitkomst.relaties_nieuw == 2
    paren = {(p.administratie_a_id, p.richting): p for p in relaties.actieve_paren()}
    assert paren[(adm_a, "crediteur")].entity_in_a == v_in_a
    assert paren[(adm_a, "crediteur")].entity_in_b == customer_in_b
    assert paren[(adm_b, "debiteur")].entity_in_a == customer_in_b
    assert paren[(adm_b, "debiteur")].entity_in_b == v_in_a
    assert paren[(adm_b, "debiteur")].administratie_b_id == adm_a
    # Eén Customers-leesroute per administratie, ongeacht het aantal debiteuren.
    assert sum(c.calls.count("Customers") for c in rlz["clients"]) == 2


def test_geen_credential_voor_debiteuren_is_zichtbaar_overgeslagen(adm_a, adm_b, rlz, monkeypatch) -> None:
    from app.rlz.credentials import GeenRlzCredentials

    identiteit.sync_identiteiten()

    def geen(rid: str):
        raise GeenRlzCredentials("geen login")

    monkeypatch.setattr(identiteit, "client_voor_rlz_admin_id", geen)
    _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)
    uitkomst = relaties.leid_relaties_af()
    assert uitkomst.relaties_nieuw == 1, "crediteuren uit de cache lopen door zonder RLZ"
    assert len(uitkomst.overgeslagen) == 2 and uitkomst.fouten == []


def test_doorbelasting_rijen_worden_bevestigd_overgenomen(adm_a, adm_b, beheerder_id, rlz) -> None:
    identiteit.sync_identiteiten()
    doel_customer = uuid.uuid4()
    crediteur_in_b = uuid.uuid4()
    with scoped_session(adm_a) as session:
        mapping = DoorbelastingMapping(
            administratie_id=adm_a,
            doelentiteit_naam="Kempen Facilities",
            doel_customer_guid=doel_customer,
            doel_administratie_id=adm_b,
            intercompany=True,
            aangemaakt_door=beheerder_id,
        )
        session.add(mapping)
        session.flush()
        mapping_id = mapping.id
        session.add(
            IntercompanyTegenpartij(
                administratie_id=adm_a, entity_guid=doel_customer, naam="Kempen Facilities", mapping_id=mapping_id
            )
        )
    with scoped_session(adm_b) as session:
        session.add(
            IntercompanyTegenpartij(
                administratie_id=adm_b, entity_guid=crediteur_in_b, naam="Kempen B.V.", mapping_id=mapping_id
            )
        )
    uitkomst = relaties.leid_relaties_af()
    assert uitkomst.doorbelasting_overgenomen == 2
    a = {r.entity_in_a: r for r in _relaties(adm_a)}[doel_customer]
    b = {r.entity_in_a: r for r in _relaties(adm_b)}[crediteur_in_b]
    assert (a.richting, a.basis, a.status, a.administratie_b_id) == ("debiteur", "doorbelasting", "bevestigd", adm_b)
    assert (b.richting, b.basis, b.status, b.administratie_b_id) == ("crediteur", "doorbelasting", "bevestigd", adm_a)
    # De oude leesbron (doorbelasting/intercompany.py) is ongewijzigd: actieve intercompany_tegenpartij-rijen.
    with scoped_session(adm_b) as session:
        assert doorbelasting_intercompany.is_intercompany_leverancier(
            session, administratie_id=adm_b, vendor_id=crediteur_in_b
        )
        assert doorbelasting_intercompany.intercompany_entity_guids(session, administratie_id=adm_b) == {crediteur_in_b}
        assert not doorbelasting_intercompany.is_intercompany_leverancier(
            session, administratie_id=adm_b, vendor_id=None
        )


def test_mens_rij_blijft_staan_bij_herafleiding_met_audit(adm_a, adm_b, beheerder_id, rlz, admin_engine) -> None:
    identiteit.sync_identiteiten()
    v = _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)
    relaties.leid_relaties_af()
    rel = _relaties(adm_a)[0]
    info = relaties.zet_status(rel.id, status="uitgesloten", reden="Is een echte externe klant", actor_id=beheerder_id)
    assert (info.status, info.bron, info.actief) == ("uitgesloten", "mens", False)
    uitkomst = relaties.leid_relaties_af()
    assert uitkomst.mens_rijen_overgeslagen == 1
    rel2 = _relaties(adm_a)[0]
    assert (rel2.status, rel2.bron, rel2.reden, rel2.entity_in_a) == (
        "uitgesloten",
        "mens",
        "Is een echte externe klant",
        v,
    )
    assert relaties.actieve_paren() == []
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = :a"),
            {"a": relaties.AUDIT_ACTIE},
        ).all()
    assert len(rijen) == 1 and rijen[0][0]["status"] == "afgeleid" and rijen[0][1]["status"] == "uitgesloten"
    # Terug naar afgeleid = systeem beheert 'm weer.
    terug = relaties.zet_status(rel.id, status="afgeleid", reden=None, actor_id=beheerder_id)
    assert (terug.status, terug.bron, terug.actief) == ("afgeleid", "afgeleid", True)


def test_zet_status_niet_beheerder_en_uitsluiten_zonder_reden(adm_a, adm_b, beheerder_id, rlz, admin_engine) -> None:
    identiteit.sync_identiteiten()
    _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)
    relaties.leid_relaties_af()
    rel = _relaties(adm_a)[0]
    boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Boekhouder")
    with pytest.raises(relaties.GeenBeheerder):
        relaties.zet_status(rel.id, status="bevestigd", reden=None, actor_id=boekhouder)
    with pytest.raises(relaties.IntercompanyFout, match="reden"):
        relaties.zet_status(rel.id, status="uitgesloten", reden="  ", actor_id=beheerder_id)
    with pytest.raises(relaties.RelatieOnbekend):
        relaties.zet_status(uuid.uuid4(), status="bevestigd", reden=None, actor_id=beheerder_id)


# --- rekening-courant ------------------------------------------------------------------------------------------------


def _rekening(aid: uuid.UUID, code: str, naam: str, *, soort: int = 3, totaal: bool = False) -> uuid.UUID:
    lid = uuid.uuid4()
    with scoped_session(aid) as session:
        session.add(
            Grootboekrekening(
                ledger_id=lid, administratie_id=aid, code=code, naam=naam, soort=soort, is_totaalrekening=totaal
            )
        )
    return lid


def test_rc_afleiding_over_en_weer_en_eenzijdig(adm_a, adm_b, adm_c, rlz) -> None:
    rlz["settings"][f"rlz-{adm_c}"] = {
        "CompanyName": "Derde Groepsmaatschappij B.V.",
        "ChamberOfCommerceNumber": "55556666",
    }
    identiteit.sync_identiteiten()
    rc_a = _rekening(adm_a, "1400", "RC Kempen Facilities")
    rc_b = _rekening(adm_b, "1600", "Rekening-courant Kempen B.V.", soort=4)
    rc_a_derde = _rekening(adm_a, "1401", "RC Derde Groepsmaatschappij")  # C heeft geen tegenrekening
    _rekening(adm_a, "4000", "Kempen Facilities doorbelaste kosten", soort=2)  # W&V → nooit RC
    _rekening(adm_a, "1000", "Kas")
    _rekening(adm_b, "1", "Vorderingen totaal", totaal=True)
    _rekening(adm_b, "1610", "Rekening-courant Onbekend Holding", soort=4)

    uitkomst = rc_koppelingen.leid_rc_koppelingen_af()

    assert (uitkomst.koppelingen_nieuw, uitkomst.zonder_tegenrekening, uitkomst.meerduidig) == (3, 1, 0)
    with scoped_session(None) as session:
        rijen = {(k.administratie_a_id, k.rekening_a): k for k in session.query(RcKoppeling).all()}
        k_a = rijen[(adm_a, rc_a)]
        assert (k_a.administratie_b_id, k_a.rekening_b, k_a.rekening_b_code, k_a.basis, k_a.status) == (
            adm_b,
            rc_b,
            "1600",
            "naam",
            "afgeleid",
        )
        k_b = rijen[(adm_b, rc_b)]
        assert (k_b.administratie_b_id, k_b.rekening_b, k_b.rekening_b_naam) == (adm_a, rc_a, "RC Kempen Facilities")
        k_c = rijen[(adm_a, rc_a_derde)]
        assert (k_c.administratie_b_id, k_c.rekening_b) == (adm_c, None)
    actief = rc_koppelingen.actieve_rc_koppelingen()
    assert len(actief) == 3
    # Idempotent.
    opnieuw = rc_koppelingen.leid_rc_koppelingen_af()
    assert (opnieuw.koppelingen_nieuw, opnieuw.koppelingen_ongewijzigd) == (0, 3)


def test_rc_afkorting_en_meerduidig(adm_a, adm_b, adm_c, beheerder_id, rlz) -> None:
    rlz["settings"][f"rlz-{adm_c}"] = {"CompanyName": "Kempen Beheer B.V.", "ChamberOfCommerceNumber": "55556666"}
    identiteit.sync_identiteiten()
    info = rc_koppelingen.zet_afkortingen(adm_b, ["KF", " kf ", ""], actor_id=beheerder_id)
    assert info.afkortingen == ["KF"]
    rc_afk = _rekening(adm_a, "1400", "RC KF")
    _rekening(adm_a, "1402", "RC Kempen Facilities / Kempen Beheer")  # twee niet-geneste treffers → niet raden
    uitkomst = rc_koppelingen.leid_rc_koppelingen_af()
    assert (uitkomst.koppelingen_nieuw, uitkomst.meerduidig, uitkomst.per_basis) == (1, 1, {"afkorting": 1})
    with scoped_session(None) as session:
        k = session.query(RcKoppeling).one()
        assert (k.rekening_a, k.administratie_b_id, k.basis, k.rekening_b) == (rc_afk, adm_b, "afkorting", None)
    # Sync overschrijft de afkortingen niet.
    identiteit.sync_identiteiten()
    with scoped_session(None) as session:
        assert session.get(AdministratieIdentiteit, adm_b).afkortingen == ["KF"]


def test_zet_rc_status_beheerder_only(adm_a, adm_b, beheerder_id, rlz, admin_engine) -> None:
    identiteit.sync_identiteiten()
    _rekening(adm_a, "1400", "RC Kempen Facilities")
    rc_koppelingen.leid_rc_koppelingen_af()
    k = rc_koppelingen.alle_rc_koppelingen()[0]
    boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Boekhouder")
    with pytest.raises(relaties.GeenBeheerder):
        rc_koppelingen.zet_rc_status(k.id, status="uitgesloten", reden="x", actor_id=boekhouder)
    with pytest.raises(relaties.GeenBeheerder):
        rc_koppelingen.zet_afkortingen(adm_b, ["KF"], actor_id=boekhouder)
    info = rc_koppelingen.zet_rc_status(k.id, status="uitgesloten", reden="Geen RC maar borg", actor_id=beheerder_id)
    assert (info.status, info.bron, info.actief) == ("uitgesloten", "mens", False)
    assert rc_koppelingen.actieve_rc_koppelingen() == []
    rc_koppelingen.leid_rc_koppelingen_af()
    assert rc_koppelingen.alle_rc_koppelingen()[0].status == "uitgesloten"


# --- routes ----------------------------------------------------------------------------------------------------------


def test_routes_beheerder_200_boekhouding_403(adm_a, adm_b, beheerder_id, rlz, admin_engine) -> None:
    _vendor(adm_a, "Kempen Facilities B.V.", kvk=KVK_B)
    _rekening(adm_a, "1400", "RC Kempen Facilities")
    resp = client.post("/intercompany/afleiden", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["identiteiten"] == {"gelezen": 2}
    assert body["relaties"]["relaties_nieuw"] == 1 and body["rc_koppelingen"]["koppelingen_nieuw"] == 1

    resp = client.get("/intercompany/relaties", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200
    rel = resp.json()["relaties"][0]
    assert (rel["administratie_a_naam"], rel["administratie_b_naam"], rel["basis"], rel["actief"]) == (
        "Kempen B.V.",
        "Kempen Facilities B.V.",
        "kvk",
        True,
    )
    resp = client.put(
        f"/intercompany/relaties/{rel['id']}",
        json={"status": "uitgesloten", "reden": "toch extern"},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 200 and resp.json()["status"] == "uitgesloten" and resp.json()["bron"] == "mens"
    resp = client.put(
        f"/intercompany/relaties/{rel['id']}",
        json={"status": "uitgesloten"},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 409

    resp = client.get("/intercompany/rc-koppelingen", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200
    rc = resp.json()
    assert len(rc["koppelingen"]) == 1 and rc["koppelingen"][0]["rekening_b"] is None
    assert {i["administratie_naam"] for i in rc["identiteiten"]} == {"Kempen B.V.", "Kempen Facilities B.V."}
    resp = client.put(
        f"/intercompany/identiteit/{adm_b}/afkortingen",
        json={"afkortingen": ["KF"]},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 200 and resp.json()["afkortingen"] == ["KF"]
    resp = client.put(
        f"/intercompany/rc-koppelingen/{rc['koppelingen'][0]['id']}",
        json={"status": "bevestigd"},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 200 and resp.json()["status"] == "bevestigd"

    boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Boekhouder")
    for methode, pad in (
        ("GET", "/intercompany/relaties"),
        ("GET", "/intercompany/rc-koppelingen"),
        ("POST", "/intercompany/afleiden"),
        ("PUT", f"/intercompany/identiteit/{adm_b}/afkortingen"),
    ):
        resp = client.request(methode, pad, json={"afkortingen": []}, headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 403, f"{methode} {pad}: {resp.status_code}"
