"""Registersync-koppelvlak (koppelcontract §8 v1.18): telling == tabel-telling, veldenset dekt de
contract-§, actuele-rijen-semantiek, expliciet-lege levering, HMAC/replay/nonce-afwijzing,
leveringslog en de responstijd-toets op het ontwerppunt (~16 administraties / ~5.500 rijen) —
end-to-end door de FastAPI-app en de echte (RLS-)testdatabase heen."""

from __future__ import annotations

import secrets as secrets_module
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings as app_settings
from app.documenten.webhook import bereken_handtekening
from app.main import app
from app.registersync.router import DEV_SECRET, ONDERTEKENDE_DATA
from app.registersync.schemas import NONCE_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER

client = TestClient(app)
ENDPOINT = "/koppelvlak/vastgoed/register"

ADMINISTRATIE_VELDEN = {"id", "rlz_admin_id", "naam", "actief"}
GROOTBOEK_VELDEN = {"ledger_id", "administratie_id", "code", "naam", "soort", "is_totaalrekening"}


def headers(*, secret: str = DEV_SECRET, timestamp: str | None = None, nonce: str | None = None) -> dict[str, str]:
    timestamp = timestamp or datetime.now(UTC).isoformat()
    nonce = nonce or secrets_module.token_hex(16)
    return {
        TIMESTAMP_HEADER: timestamp,
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: bereken_handtekening(
            secret=secret, payload_json=ONDERTEKENDE_DATA, timestamp=timestamp, nonce=nonce
        ),
    }


def seed_administratie(
    admin_engine: Engine, naam: str, *, actief: bool = True, is_vastgoed: bool = False, gearchiveerd: bool = False
) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, actief, is_vastgoed, gearchiveerd_op) "
                "VALUES (:id, :naam, :rlz, :actief, :vg, :arch)"
            ),
            {
                "id": aid,
                "naam": naam,
                "rlz": f"rlz-{aid}",
                "actief": actief and not gearchiveerd,
                "vg": is_vastgoed,
                "arch": datetime.now(UTC) if gearchiveerd else None,
            },
        )
    return aid


def seed_grootboek(
    admin_engine: Engine, administratie_id: uuid.UUID, aantal: int, *, verdwenen: int = 0
) -> None:
    """`aantal` actuele rijen + `verdwenen` rijen met verdwenen_uit_bron_op gezet (horen NIET in
    de snapshot). Batch-insert: de performance-test seedt ~5.500 rijen."""
    rijen = [
        {
            "id": uuid.uuid4(), "aid": administratie_id, "code": f"{4000 + i:04d}",
            "naam": f"Rekening {i}", "soort": 2 if i % 2 else 3, "tot": i % 10 == 0, "weg": None,
        }
        for i in range(aantal)
    ] + [
        {
            "id": uuid.uuid4(), "aid": administratie_id, "code": f"9{i:03d}",
            "naam": f"Verdwenen {i}", "soort": 2, "tot": False, "weg": datetime.now(UTC),
        }
        for i in range(verdwenen)
    ]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.grootboekrekening "
                "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening, verdwenen_uit_bron_op) "
                "VALUES (:id, :aid, :code, :naam, :soort, :tot, :weg)"
            ),
            rijen,
        )


def tabel_tellingen(admin_engine: Engine) -> tuple[int, int]:
    with admin_engine.connect() as conn:
        # v1.19: gearchiveerde administraties reizen niet mee (afwezigheid = verdwenen).
        adm = conn.execute(
            text("SELECT count(*) FROM platform.administratie WHERE gearchiveerd_op IS NULL")
        ).scalar_one()
        gb = conn.execute(
            text("SELECT count(*) FROM platform.grootboekrekening WHERE verdwenen_uit_bron_op IS NULL")
        ).scalar_one()
    return adm, gb


# --- inhoud ---------------------------------------------------------------------------------------


def test_telling_gelijk_aan_tabel_telling_en_actuele_rijen_semantiek(admin_engine: Engine) -> None:
    a = seed_administratie(admin_engine, "Alfa B.V.", is_vastgoed=True)
    b = seed_administratie(admin_engine, "Bèta Holding", actief=False)  # niet-actief, niet-vastgoed: tóch geleverd
    c = seed_administratie(admin_engine, "Gamma zonder grootboek")
    d = seed_administratie(admin_engine, "Delta gearchiveerd", gearchiveerd=True)  # v1.19: niet geleverd
    seed_grootboek(admin_engine, a, 5, verdwenen=2)
    seed_grootboek(admin_engine, b, 3, verdwenen=1)

    resp = client.get(ENDPOINT, headers=headers())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    adm_tabel, gb_tabel = tabel_tellingen(admin_engine)
    assert body["schema_version"] == "1.0"
    assert body["administraties"]["aantal"] == adm_tabel == len(body["administraties"]["rijen"])
    assert body["grootboekrekeningen"]["aantal"] == gb_tabel == 8 == len(body["grootboekrekeningen"]["rijen"])
    geleverde_admins = {r["id"] for r in body["administraties"]["rijen"]}
    assert {str(a), str(b), str(c)} <= geleverde_admins  # ongefilterd: ook niet-actief/niet-vastgoed
    assert str(d) not in geleverde_admins  # gearchiveerd = afwezig = verdwenen (contract v1.19)
    assert {r["actief"] for r in body["administraties"]["rijen"] if r["id"] == str(b)} == {False}
    assert not any(r["naam"].startswith("Verdwenen") for r in body["grootboekrekeningen"]["rijen"])
    per_admin = {str(a): 0, str(b): 0, str(c): 0}
    for r in body["grootboekrekeningen"]["rijen"]:
        per_admin[r["administratie_id"]] = per_admin.get(r["administratie_id"], 0) + 1
    assert per_admin[str(a)] == 5 and per_admin[str(b)] == 3 and per_admin[str(c)] == 0
    datetime.fromisoformat(body["generated_at"])  # ISO-8601
    assert body["bron_laatst_gesynchroniseerd_op"] is not None


def test_veldenset_dekt_exact_de_contract_paragraaf(admin_engine: Engine) -> None:
    a = seed_administratie(admin_engine, "Veldentest")
    seed_grootboek(admin_engine, a, 2)

    body = client.get(ENDPOINT, headers=headers()).json()

    assert set(body) == {
        "schema_version", "generated_at", "bron_laatst_gesynchroniseerd_op",
        "administraties", "grootboekrekeningen",
    }
    assert set(body["administraties"]) == {"aantal", "rijen"}
    assert set(body["grootboekrekeningen"]) == {"aantal", "rijen"}
    for rij in body["administraties"]["rijen"]:
        assert set(rij) == ADMINISTRATIE_VELDEN
    for rij in body["grootboekrekeningen"]["rijen"]:
        assert set(rij) == GROOTBOEK_VELDEN
        assert isinstance(rij["soort"], int) and isinstance(rij["is_totaalrekening"], bool)


def test_inbox_adres_op_elke_actieve_rij(admin_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """v1.19-notitie (2), verzoek Vastly 31-08: mét geconfigureerd centraal intake-adres draagt
    élke ACTIEVE administratie-rij `inbox_adres`; een niet-actieve rij draagt het veld NIET
    (afwezig = geen uitspraak, Vastly raakt de cache niet aan). Envelope, handtekening en
    top-level-veldenset blijven ongewijzigd (additief, geen versiebump)."""
    monkeypatch.setattr(app_settings, "intake_postvak_adres", "facturen@ak-nijenhuis.nl")
    a = seed_administratie(admin_engine, "Actief mét inbox")
    b = seed_administratie(admin_engine, "Niet-actief", actief=False)

    resp = client.get(ENDPOINT, headers=headers())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "schema_version", "generated_at", "bron_laatst_gesynchroniseerd_op",
        "administraties", "grootboekrekeningen",
    }
    per_id = {r["id"]: r for r in body["administraties"]["rijen"]}
    assert set(per_id[str(a)]) == ADMINISTRATIE_VELDEN | {"inbox_adres"}
    assert per_id[str(a)]["inbox_adres"] == "facturen@ak-nijenhuis.nl"
    assert set(per_id[str(b)]) == ADMINISTRATIE_VELDEN  # geen uitspraak = veld afwezig
    for rij in body["administraties"]["rijen"]:
        if rij["actief"]:
            assert rij["inbox_adres"] == "facturen@ak-nijenhuis.nl"


def test_inbox_adres_zonder_config_afwezig(admin_engine: Engine) -> None:
    """Zonder geconfigureerd adres (code-default None, o.a. dev): het veld ontbreekt op élke rij —
    geen uitspraak, nooit een onbedoeld `null` (dat zou Vastly's cache expliciet leegmaken)."""
    seed_administratie(admin_engine, "Zonder config")
    body = client.get(ENDPOINT, headers=headers()).json()
    assert all("inbox_adres" not in rij for rij in body["administraties"]["rijen"])


def test_leeg_grootboekregister_is_expliciet_aantal_0(admin_engine: Engine) -> None:
    seed_administratie(admin_engine, "Leeg")
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM platform.grootboekrekening"))

    body = client.get(ENDPOINT, headers=headers()).json()

    assert body["grootboekrekeningen"] == {"aantal": 0, "rijen": []}
    assert body["administraties"]["aantal"] >= 1
    assert body["bron_laatst_gesynchroniseerd_op"] is None


def test_twee_snapshots_van_dezelfde_stand_zijn_identiek(admin_engine: Engine) -> None:
    a = seed_administratie(admin_engine, "Determinisme")
    seed_grootboek(admin_engine, a, 20)
    een = client.get(ENDPOINT, headers=headers()).json()
    twee = client.get(ENDPOINT, headers=headers()).json()
    een.pop("generated_at"), twee.pop("generated_at")
    assert een == twee


# --- auth / replay --------------------------------------------------------------------------------


def test_zonder_headers_401() -> None:
    resp = client.get(ENDPOINT)
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "handtekening_ongeldig"


def test_fout_secret_401() -> None:
    resp = client.get(ENDPOINT, headers=headers(secret="verkeerd"))
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "handtekening_ongeldig"


def test_projectaanvraag_secret_werkt_hier_niet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compartimentering: het (dev-)secret van route A tekent geen registersync-verzoek."""
    resp = client.get(ENDPOINT, headers=headers(secret="dev-only-insecure-projectaanvraag-hmac-secret"))
    assert resp.status_code == 401


def test_timestamp_buiten_venster_400() -> None:
    oud = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    resp = client.get(ENDPOINT, headers=headers(timestamp=oud))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "timestamp_buiten_venster"


def test_timestamp_zonder_tijdzone_400() -> None:
    resp = client.get(ENDPOINT, headers=headers(timestamp=datetime.now().isoformat()))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "timestamp_ongeldig"


def test_nonce_hergebruik_409(admin_engine: Engine) -> None:
    seed_administratie(admin_engine, "Nonce")
    h = headers()
    assert client.get(ENDPOINT, headers=h).status_code == 200
    # Zelfde nonce, verse timestamp (opnieuw getekend): geweigerd.
    herhaald = headers(nonce=h[NONCE_HEADER])
    resp = client.get(ENDPOINT, headers=herhaald)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "nonce_hergebruikt"


def test_zonder_secret_buiten_dev_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "environment", "production")
    monkeypatch.setattr(app_settings, "registersync_hmac_secret", None)
    resp = client.get(ENDPOINT, headers=headers())
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "niet_geconfigureerd"


def test_geconfigureerd_secret_wint_boven_dev_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "registersync_hmac_secret", "echt-secret")
    assert client.get(ENDPOINT, headers=headers()).status_code == 401
    assert client.get(ENDPOINT, headers=headers(secret="echt-secret")).status_code == 200


# --- leveringslog + performance -------------------------------------------------------------------


def test_levering_wordt_gelogd_met_tellingen(admin_engine: Engine) -> None:
    a = seed_administratie(admin_engine, "Log")
    seed_grootboek(admin_engine, a, 4)
    h = headers()
    body = client.get(ENDPOINT, headers=h).json()
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT aantal_administraties, aantal_grootboekrekeningen, duur_ms "
                "FROM boekhouding.registersync_levering WHERE nonce = :n"
            ),
            {"n": h[NONCE_HEADER]},
        ).one()
    assert rij.aantal_administraties == body["administraties"]["aantal"]
    assert rij.aantal_grootboekrekeningen == body["grootboekrekeningen"]["aantal"] == 4
    assert rij.duur_ms >= 0


def test_ontwerppunt_16_administraties_5500_rijen_binnen_de_tijd(admin_engine: Engine) -> None:
    """Performance-toets (Vastly's ontwerppunt 15 administraties / ~5.500 rekeningen; wij 16):
    ruim binnen de Cloud Run-request-timeout. De gemeten tijd wordt gerapporteerd (-s / -rA)."""
    for i in range(16):
        aid = seed_administratie(admin_engine, f"Perf {i:02d}")
        seed_grootboek(admin_engine, aid, 344)  # 16 × 344 = 5.504
    adm_tabel, gb_tabel = tabel_tellingen(admin_engine)
    assert gb_tabel >= 5_504

    start = time.perf_counter()
    resp = client.get(ENDPOINT, headers=headers())
    duur = time.perf_counter() - start

    assert resp.status_code == 200
    body = resp.json()
    assert body["administraties"]["aantal"] == adm_tabel
    assert body["grootboekrekeningen"]["aantal"] == gb_tabel
    print(f"\nregistersync ontwerppunt: {adm_tabel} administraties, {gb_tabel} rijen, "
          f"{duur * 1000:.0f} ms end-to-end, {len(resp.content) / 1024:.0f} KiB")
    assert duur < 5.0, f"snapshot duurde {duur:.2f} s"
