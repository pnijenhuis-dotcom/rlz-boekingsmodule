"""Blok 5 feedbackrun A 25-09 — FV-14 (crediteur aanmaken mét adres, IBAN-ontbreekt-waarschuwing) en FV-15
(crediteur achteraf bewerken: PUT-route, kenmerk 'handmatig', audit oud→nieuw, fail-open adres, IBAN nooit via PUT)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.main import app
from app.rlz.client import RlzApiError, adres_als_regel
from app.security.tokens import create_access_token
from app.sync import service
from tests.sync.conftest import FakeRlzClient

ADRES = {"straat": "Kantoorlaan 12", "postcode": "5611 AB", "plaats": "Eindhoven", "land": "NL"}


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def bestaande_vendor(administratie_id: uuid.UUID) -> uuid.UUID:
    vid = uuid.uuid4()
    service.sync_vendors(
        administratie_id=administratie_id,
        client=FakeRlzClient({"Vendors": [{"id": str(vid), "Name": "Floor Bouwliftenservice", "IsArchived": False}]}),
    )
    return vid


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _audit(admin_engine: Engine, vendor_id: uuid.UUID, actie: str) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :rid AND actie = :a"),
            {"rid": vendor_id, "a": actie},
        ).all()


def _kenmerk(admin_engine: Engine, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> tuple | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT kvk_nummer, kvk_nummer_bron, btw_nummer, btw_nummer_bron FROM boekhouding.crediteur_kenmerk "
                "WHERE administratie_id = :aid AND vendor_id = :vid"
            ),
            {"aid": administratie_id, "vid": vendor_id},
        ).first()


# ---- put_vendor-body -------------------------------------------------------------------------------------------


def test_adres_als_regel_zelfde_vorm_als_de_ubl_adresregel() -> None:
    assert adres_als_regel(ADRES) == "Kantoorlaan 12, 5611 AB Eindhoven, NL"
    assert adres_als_regel({"plaats": "Eindhoven"}) == "Eindhoven"
    assert adres_als_regel({}) is None
    assert adres_als_regel(None) is None


def test_put_vendor_body_draagt_fullAddress_en_city_alleen_met_adres() -> None:
    """De letterlijke body naar RLZ: Name altijd; FullAddress + City alleen als er een adres is (bewezen DTO-velden,
    nooit AddressList/Country zonder bekend sub-model)."""
    from app.rlz.client import RlzClient

    gezien: list[tuple[str, dict]] = []

    class Stub(RlzClient):
        def __init__(self) -> None:  # noqa: D401 — geen echte verbinding
            pass

        def put(self, path: str, body: dict) -> None:  # type: ignore[override]
            gezien.append((path, body))

    vid = uuid.uuid4()
    Stub().put_vendor(vid, name="Floor")
    Stub().put_vendor(vid, name="Floor", adres=ADRES)
    assert gezien[0] == (f"Vendors/{vid}", {"id": str(vid), "Name": "Floor"})
    assert gezien[1] == (
        f"Vendors/{vid}",
        {"id": str(vid), "Name": "Floor", "FullAddress": "Kantoorlaan 12, 5611 AB Eindhoven, NL", "City": "Eindhoven"},
    )


# ---- FV-14 aanmaken mét adres + IBAN-waarschuwing ----------------------------------------------------------------


def test_aanmaken_met_adres_en_zonder_iban_geeft_waarschuwing_geen_blokkade(
    boeken_aan: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
) -> None:
    client = FakeRlzClient({})
    uit = service.maak_crediteur_aan(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, naam="Confide BV", client=client, adres=ADRES
    )
    assert client.vendor_puts == [{"vendor_id": uit.id, "name": "Confide BV", "adres": ADRES}]
    assert service.IBAN_ONTBREEKT_WAARSCHUWING in uit.waarschuwingen
    with admin_engine.connect() as conn:
        brondata = conn.execute(
            text("SELECT brondata FROM boekhouding.vendor_cache WHERE id = :id"), {"id": uit.id}
        ).scalar_one()
    assert brondata["FullAddress"] == "Kantoorlaan 12, 5611 AB Eindhoven, NL"
    assert brondata["adres_velden"] == ADRES


def test_aanmaken_adres_geweigerd_door_rlz_is_fail_open_met_waarschuwing(
    boeken_aan: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
) -> None:
    client = FakeRlzClient({})
    client.adres_fout = RlzApiError(400, "PUT", "Vendors/x", "FullAddress not allowed")
    uit = service.maak_crediteur_aan(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        naam="Confide BV",
        client=client,
        adres=ADRES,
        iban="NL91ABNA0417164300",
    )
    # Eén mislukte PUT mét adres → tweede PUT zonder adres: de crediteur bestaat, het adres = zichtbare waarschuwing.
    assert client.vendor_puts == [{"vendor_id": uit.id, "name": "Confide BV", "adres": None}]
    assert any(w.startswith(service.ADRES_NIET_GEACCEPTEERD) for w in uit.waarschuwingen)
    assert service.IBAN_ONTBREEKT_WAARSCHUWING not in uit.waarschuwingen
    assert uit.iban_vertrouwd


def test_aanmaken_500_op_de_naam_put_gooit_gewoon(
    boeken_aan: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
) -> None:
    client = FakeRlzClient({})
    client.adres_fout = RlzApiError(503, "PUT", "Vendors/x", "down")
    with pytest.raises(RlzApiError):
        service.maak_crediteur_aan(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            naam="Confide BV",
            client=client,
            adres=ADRES,
        )


# ---- FV-15 bewerken ----------------------------------------------------------------------------------------------


def test_wijzig_crediteur_naam_adres_kenmerk_cache_en_audit(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    bestaande_vendor: uuid.UUID,
    admin_engine: Engine,
) -> None:
    client = FakeRlzClient({})
    uit = service.wijzig_crediteur(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=bestaande_vendor,
        naam="Floor Bouwliftenservice B.V.",
        kvk_nummer="12345678",
        btw_nummer="NL001234567B01",
        adres=ADRES,
        client=client,
    )
    assert uit.id == bestaande_vendor  # het BESTAANDE id, nooit een nieuw GUID
    assert client.vendor_puts == [
        {"vendor_id": bestaande_vendor, "name": "Floor Bouwliftenservice B.V.", "adres": ADRES}
    ]
    assert uit.kvk_opgeslagen and uit.btw_opgeslagen
    assert (
        service.IBAN_ONTBREEKT_WAARSCHUWING in uit.waarschuwingen
    )  # geen vertrouwd IBAN → waarschuwing, geen blokkade
    with admin_engine.connect() as conn:
        naam, brondata = conn.execute(
            text("SELECT naam, brondata FROM boekhouding.vendor_cache WHERE id = :id"), {"id": bestaande_vendor}
        ).one()
    assert naam == "Floor Bouwliftenservice B.V."
    assert brondata["Name"] == "Floor Bouwliftenservice B.V."
    assert brondata["FullAddress"] == "Kantoorlaan 12, 5611 AB Eindhoven, NL"
    assert brondata["City"] == "Eindhoven"
    # KvK/btw = mens-keuze: bron 'handmatig' (wint voortaan van de factuur — regel neem_over_uit_veldvoorstel).
    assert _kenmerk(admin_engine, administratie_id, bestaande_vendor) == (
        "12345678",
        "handmatig",
        "NL001234567B01",
        "handmatig",
    )
    audits = _audit(admin_engine, bestaande_vendor, "crediteur_gewijzigd")
    assert len(audits) == 1
    oud, nieuw = audits[0]
    assert oud["naam"] == "Floor Bouwliftenservice" and oud["kvk_nummer"] is None
    assert nieuw["naam"] == "Floor Bouwliftenservice B.V." and nieuw["kvk_nummer"] == "12345678"
    assert nieuw["adres"]["plaats"] == "Eindhoven" and nieuw["bron"] == "controlescherm"

    # Detail-lezing (bewerk-modus van het paneel) toont dezelfde stand, IBAN's lees-only (hier leeg).
    d = service.crediteur_detail(administratie_id=administratie_id, vendor_id=bestaande_vendor)
    assert d.naam == "Floor Bouwliftenservice B.V." and d.kvk_nummer == "12345678" and d.btw_nummer == "NL001234567B01"
    assert d.adres["straat"] == "Kantoorlaan 12" and d.adres["regel"] == "Kantoorlaan 12, 5611 AB Eindhoven, NL"
    assert d.vertrouwde_ibans == () and d.backend == "rlz"


def test_wijzig_adres_geweigerd_is_fail_open_naam_wel_opgeslagen(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    bestaande_vendor: uuid.UUID,
    admin_engine: Engine,
) -> None:
    client = FakeRlzClient({})
    client.adres_fout = RlzApiError(400, "PUT", "Vendors/x", "nope")
    uit = service.wijzig_crediteur(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=bestaande_vendor,
        naam="Floor Nieuw",
        adres=ADRES,
        client=client,
    )
    assert client.vendor_puts == [{"vendor_id": bestaande_vendor, "name": "Floor Nieuw", "adres": None}]
    assert any(w.startswith(service.ADRES_NIET_GEACCEPTEERD) for w in uit.waarschuwingen)
    with admin_engine.connect() as conn:
        naam, brondata = conn.execute(
            text("SELECT naam, brondata FROM boekhouding.vendor_cache WHERE id = :id"), {"id": bestaande_vendor}
        ).one()
    assert naam == "Floor Nieuw" and "FullAddress" not in brondata


def test_wijzig_ongeldig_kvk_is_waarschuwing_niet_opgeslagen(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    bestaande_vendor: uuid.UUID,
    admin_engine: Engine,
) -> None:
    uit = service.wijzig_crediteur(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=bestaande_vendor,
        naam="Floor Bouwliftenservice",
        kvk_nummer="12",
        client=FakeRlzClient({}),
    )
    assert any("KvK-nummer '12'" in w for w in uit.waarschuwingen)
    assert not uit.kvk_opgeslagen
    assert _kenmerk(admin_engine, administratie_id, bestaande_vendor) is None


def test_wijzig_failsafe_uit_geeft_geen_rlz_write(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, bestaande_vendor: uuid.UUID
) -> None:
    client = FakeRlzClient({})
    with pytest.raises(service.CrediteurAanmakenUitgeschakeld):
        service.wijzig_crediteur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=bestaande_vendor,
            naam="X",
            client=client,
        )
    assert client.vendor_puts == []


def test_wijzig_onbekende_vendor_en_naam_van_andere_crediteur(
    boeken_aan: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, bestaande_vendor: uuid.UUID
) -> None:
    with pytest.raises(service.CrediteurNietGevonden):
        service.wijzig_crediteur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            naam="X",
            client=FakeRlzClient({}),
        )
    andere = uuid.uuid4()
    service.sync_vendors(
        administratie_id=administratie_id,
        client=FakeRlzClient(
            {
                "Vendors": [
                    {"id": str(bestaande_vendor), "Name": "Floor Bouwliftenservice", "IsArchived": False},
                    {"id": str(andere), "Name": "Universal Nederland B.V.", "IsArchived": False},
                ]
            }
        ),
    )
    with pytest.raises(service.CrediteurBestaatAl) as exc:
        service.wijzig_crediteur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=bestaande_vendor,
            naam="universal nederland b.v.",
            client=FakeRlzClient({}),
        )
    assert exc.value.vendor_id == andere


# ---- routes (status-contract scherm ↔ server) ---------------------------------------------------------------------


class TestRoutes:
    def test_put_bewerken_200_en_iban_veld_is_422(
        self,
        boeken_aan: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        bestaande_vendor: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeRlzClient({})
        monkeypatch.setattr(service, "_open_client_indien_nodig", lambda aid, client: (fake, False))
        client = TestClient(app)
        pad = f"/administraties/{administratie_id}/crediteuren/{bestaande_vendor}"
        resp = client.put(
            pad,
            json={"naam": "Floor Bouwliftenservice B.V.", "kvk_nummer": "12345678", "adres": {"plaats": "Eindhoven"}},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == str(bestaande_vendor) and body["kvk_opgeslagen"] is True
        assert service.IBAN_ONTBREEKT_WAARSCHUWING in body["waarschuwingen"]
        assert fake.vendor_puts[-1]["adres"] == {"plaats": "Eindhoven"}
        assert len(_audit(admin_engine, bestaande_vendor, "crediteur_gewijzigd")) == 1

        # IBAN hoort NIET op de bewerk-PUT: extra="forbid" → 422 (de IBAN-wissel/vier-ogen-route is de enige weg).
        resp = client.put(
            pad, json={"naam": "Floor", "iban": "NL91ABNA0417164300"}, headers=_bearer(gescoopte_gebruiker)
        )
        assert resp.status_code == 422, resp.text

        # Detail-lezing voor de bewerk-modus.
        resp = client.get(pad, headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["naam"] == "Floor Bouwliftenservice B.V." and d["kvk_nummer"] == "12345678"
        assert d["adres"]["plaats"] == "Eindhoven" and d["vertrouwde_ibans"] == [] and d["backend"] == "rlz"

    def test_put_bewerken_403_bij_failsafe_uit_en_404_onbekend(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        bestaande_vendor: uuid.UUID,
        boeken_aan_later: None = None,
    ) -> None:
        client = TestClient(app)
        resp = client.put(
            f"/administraties/{administratie_id}/crediteuren/{bestaande_vendor}",
            json={"naam": "Floor"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 403, resp.text
        resp = client.get(
            f"/administraties/{administratie_id}/crediteuren/{uuid.uuid4()}", headers=_bearer(gescoopte_gebruiker)
        )
        assert resp.status_code == 404, resp.text

    def test_post_aanmaken_neemt_adres_mee(
        self,
        boeken_aan: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeRlzClient({})
        monkeypatch.setattr(service, "_open_client_indien_nodig", lambda aid, client: (fake, False))
        client = TestClient(app)
        resp = client.post(
            f"/administraties/{administratie_id}/crediteuren",
            json={"naam": "Confide BV", "adres": ADRES},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        assert fake.vendor_puts[-1]["adres"] == ADRES
        assert service.IBAN_ONTBREEKT_WAARSCHUWING in resp.json()["waarschuwingen"]
