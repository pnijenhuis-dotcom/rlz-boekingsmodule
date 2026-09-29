"""`credential-naar-secretmanager` (opdracht Peter 29-09): store → Secret Manager, waarde nooit in de uitvoer (besluit
0012), bestaande versie nooit stil overschreven, dry-run schrijft niets, onbekende administratie / ontbrekende
credential = zichtbare regel + exit 1, één audit per administratie zonder waarde. De Secret-Manager-poort is een
fake: de echte REST-poort raakt hier nooit het netwerk."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app import cli as app_cli
from app.beheer import credential_naar_secretmanager as csm
from app.credentialstore import service as credentialstore_service
from tests.doorbelasting.conftest import maak_administratie

WACHTWOORD = "Zeer-Geheim-Wachtwoord-2029!"
GEBRUIKER = "WS_universal_nl"


class FakeSecretManager:
    def __init__(self, bestaand: dict[str, int] | None = None, *, kapot: set[str] | None = None) -> None:
        self.versies: dict[str, list[str]] = {}
        self.bestaand = dict(bestaand or {})
        self.kapot = set(kapot or ())

    def laatste_versie(self, naam: str) -> str | None:
        if naam in self.kapot:
            raise RuntimeError(f"{naam}: container bestaat niet in project test")
        if naam in self.versies:
            return str(len(self.versies[naam]) + self.bestaand.get(naam, 0))
        return str(self.bestaand[naam]) if naam in self.bestaand else None

    def voeg_versie_toe(self, naam: str, waarde: str) -> str:
        self.versies.setdefault(naam, []).append(waarde)
        return str(len(self.versies[naam]) + self.bestaand.get(naam, 0))


@pytest.fixture
def universal_nl(admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:
    aid = maak_administratie(admin_engine, "Universal Nederland B.V.")
    credentialstore_service.zet_credential(
        actor_id=beheerder_id, administratie_id=aid, webservice_username=GEBRUIKER, wachtwoord=WACHTWOORD
    )
    return aid


def _audits(admin_engine: Engine, aid: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT actie, nieuwe_waarde::text AS nw FROM platform.audit_event "
                    "WHERE record_id = :id AND actie = :a"
                ),
                {"id": aid, "a": csm.ACTIE_AUDIT},
            )
        ]


def test_zet_beide_secrets_toont_alleen_naam_en_aantal_tekens(
    universal_nl: uuid.UUID, admin_engine: Engine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSecretManager()
    monkeypatch.setattr(csm, "RestSecretManager", lambda project: fake)
    monkeypatch.setattr(csm, "DOELEN", (("Universal Nederland", "UNIVERSAL_NEDERLAND"),))

    assert app_cli.main(["credential-naar-secretmanager"]) == 0
    uit = capsys.readouterr().out

    assert f"RLZ_WS_USER_UNIVERSAL_NEDERLAND: versie 1 gezet ({len(GEBRUIKER)} tekens)" in uit
    assert f"RLZ_WS_PASSWORD_UNIVERSAL_NEDERLAND: versie 1 gezet ({len(WACHTWOORD)} tekens)" in uit
    assert "2 versie(s) gezet, 0 al aanwezig, 0 administratie(s) mét fout" in uit
    # Besluit 0012: de waarde staat nergens in de uitvoer — wél exact in Secret Manager.
    assert WACHTWOORD not in uit and GEBRUIKER not in uit
    assert fake.versies["RLZ_WS_USER_UNIVERSAL_NEDERLAND"] == [GEBRUIKER]
    assert fake.versies["RLZ_WS_PASSWORD_UNIVERSAL_NEDERLAND"] == [WACHTWOORD]
    audits = _audits(admin_engine, universal_nl)
    assert len(audits) == 1
    assert f'"RLZ_WS_PASSWORD_UNIVERSAL_NEDERLAND": {len(WACHTWOORD)}' in audits[0]["nw"]
    assert WACHTWOORD not in audits[0]["nw"] and GEBRUIKER not in audits[0]["nw"]


def test_bestaande_versie_wordt_niet_stil_overschreven_tenzij_overschrijven(universal_nl: uuid.UUID) -> None:
    fake = FakeSecretManager(bestaand={"RLZ_WS_USER_UNIVERSAL_NEDERLAND": 1})
    doelen = (("Universal Nederland", "UNIVERSAL_NEDERLAND"),)
    uitkomsten = csm.verwerk(poort=fake, doelen=doelen, schrijf_audit=lambda *a, **k: None)
    u = uitkomsten[0]
    assert u.gezet == 1 and u.overgeslagen == 1 and not u.fout
    assert any("RLZ_WS_USER_UNIVERSAL_NEDERLAND: heeft al versie 1 — niet overschreven" in r for r in u.regels)
    assert "RLZ_WS_USER_UNIVERSAL_NEDERLAND" not in fake.versies

    uitkomsten = csm.verwerk(poort=fake, doelen=doelen, overschrijven=True, schrijf_audit=lambda *a, **k: None)
    assert uitkomsten[0].gezet == 2
    assert any("RLZ_WS_USER_UNIVERSAL_NEDERLAND: versie 2 gezet" in r for r in uitkomsten[0].regels)


def test_dry_run_schrijft_niets_en_geen_audit(universal_nl: uuid.UUID, admin_engine: Engine) -> None:
    fake = FakeSecretManager()
    uitkomsten = csm.verwerk(poort=fake, doelen=(("Universal Nederland", "UNIVERSAL_NEDERLAND"),), dry_run=True)
    assert fake.versies == {}
    assert uitkomsten[0].gezet == 0 and not uitkomsten[0].fout
    assert any(f"ZOU versie zetten ({len(WACHTWOORD)} tekens) — dry-run" in r for r in uitkomsten[0].regels)
    assert _audits(admin_engine, universal_nl) == []


def test_onbekende_administratie_en_ontbrekende_credential_zijn_zichtbaar_en_exit_1(
    admin_engine: Engine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    maak_administratie(admin_engine, "BWC Steigers B.V.")  # wél een administratie, géén credential
    fake = FakeSecretManager()
    monkeypatch.setattr(csm, "RestSecretManager", lambda project: fake)
    monkeypatch.setattr(csm, "DOELEN", (("Bestaat Niet Holding", "BESTAAT_NIET"), ("BWC Steigers", "BWC_STEIGERS")))
    assert app_cli.main(["credential-naar-secretmanager"]) == 1
    uit = capsys.readouterr().out
    assert "BESTAAT_NIET: administratie 'Bestaat Niet Holding' niet (eenduidig) gevonden — overgeslagen" in uit
    assert "BWC_STEIGERS: 'BWC Steigers B.V.' heeft geen credential in de store — overgeslagen" in uit
    assert fake.versies == {}


def test_kapotte_container_is_een_zichtbare_fout_de_rest_loopt_door(universal_nl: uuid.UUID) -> None:
    fake = FakeSecretManager(kapot={"RLZ_WS_USER_UNIVERSAL_NEDERLAND"})
    uitkomsten = csm.verwerk(
        poort=fake, doelen=(("Universal Nederland", "UNIVERSAL_NEDERLAND"),), schrijf_audit=lambda *a, **k: None
    )
    u = uitkomsten[0]
    assert u.fout and u.gezet == 1
    assert any(r.startswith("RLZ_WS_USER_UNIVERSAL_NEDERLAND: FOUT") for r in u.regels)
    assert WACHTWOORD not in "\n".join(u.regels)


def test_vaste_lijst_is_de_opdracht_van_29_09_en_prefix_filter() -> None:
    assert [p for _, p in csm.DOELEN] == [
        "UNIVERSAL_NEDERLAND",
        "UNIVERSAL_VERKOOP",
        "UNIVERSAL_MATERIAAL",
        "UNIVERSAL_STEIGERBOUW",
        "BWC_STEIGERS",
        "BRADWOLFF_CONSTRUCTIE",
        "INPENSAS_BEHEER",
        "BRADWOLFF_HOLDING",
        "DE_WIT_BEHEER_OSS",
    ]
    assert csm.secretnamen("DE_WIT_BEHEER_OSS") == (
        "RLZ_WS_USER_DE_WIT_BEHEER_OSS",
        "RLZ_WS_PASSWORD_DE_WIT_BEHEER_OSS",
    )
    assert app_cli.main(["credential-naar-secretmanager", "--prefix", "ONBEKEND"]) == 2


def test_rest_poort_speelt_de_secret_manager_api_na(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub speelt het bewezen API-gedrag na (regel 21-09): versies-lijst mét `filter=state:ENABLED`, hoogste nummer
    wint,
    `:addVersion` mét base64-payload; een 404 op de container is een fout mét naam, nooit de waarde in de melding."""
    import base64

    import httpx

    aanroepen: list[tuple[str, str, dict]] = []

    class _Antwoord:
        def __init__(self, status: int, body: dict) -> None:
            self.status_code = status
            self._body = body

        def json(self) -> dict:
            return self._body

    def _get(url: str, *, params: dict, headers: dict, timeout: float) -> _Antwoord:
        aanroepen.append(("GET", url, params))
        if url.endswith("/secrets/RLZ_WS_USER_BESTAAT_NIET/versions"):
            return _Antwoord(404, {})
        return _Antwoord(
            200,
            {"versions": [{"name": "projects/1/secrets/X/versions/2"}, {"name": "projects/1/secrets/X/versions/3"}]},
        )

    def _post(url: str, *, json: dict, headers: dict, timeout: float) -> _Antwoord:
        aanroepen.append(("POST", url, json))
        return _Antwoord(200, {"name": "projects/1/secrets/X/versions/4"})

    monkeypatch.setattr(httpx, "get", _get)
    monkeypatch.setattr(httpx, "post", _post)
    poort = csm.RestSecretManager("rlz-boekhouding")
    monkeypatch.setattr(poort, "_headers", lambda: {"Authorization": "Bearer test"})

    assert poort.laatste_versie("RLZ_WS_USER_X") == "3"
    assert (
        aanroepen[0][1]
        == "https://secretmanager.googleapis.com/v1/projects/rlz-boekhouding/secrets/RLZ_WS_USER_X/versions"
    )
    assert aanroepen[0][2]["filter"] == "state:ENABLED"
    with pytest.raises(RuntimeError, match="RLZ_WS_USER_BESTAAT_NIET: container bestaat niet"):
        poort.laatste_versie("RLZ_WS_USER_BESTAAT_NIET")

    assert poort.voeg_versie_toe("RLZ_WS_USER_X", "geheim") == "4"
    methode, url, body = aanroepen[-1]
    assert methode == "POST" and url.endswith("/secrets/RLZ_WS_USER_X:addVersion")
    assert base64.b64decode(body["payload"]["data"]).decode() == "geheim"
