"""Drift-guard KvK-productieconfig (E7, besluit Peter 07-09): de dossier-KvK-check draaide in productie
op KvK's TESTOMGEVING omdat deploy.yml geen KVK_BASE_URL/KVK_API_KEY droeg. Deze test leest
deploy.yml en eist dat de rlz-backend-service (1) de productie-URL mét het `/basisprofielen`-pad
draagt (de client plakt er `/{kvkNummer}` achter — `https://api.kvk.nl/api/v1` zónder pad zou een
stille 404 = "niet gevonden" geven) en (2) het secret KVK_API_KEY gemount heeft, en dat die
combinatie de consistentiecheck in app/integraties/kvk.py doorstaat (les Vastly 18-08: productiesleutel
tegen de test-URL = stille 401). Alleen de service — geen job raakt de KvK-API (least privilege)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import settings
from app.integraties import kvk

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"
PRODUCTIE_BASE_URL = "https://api.kvk.nl/api/v1/basisprofielen"


def _deploy_tekst() -> str:
    return DEPLOY_YML.read_text(encoding="utf-8")


def _base_urls_in_deploy() -> list[str]:
    return re.findall(r"KVK_BASE_URL=([^@\"\s,]+)", _deploy_tekst())


def test_deploy_yml_zet_precies_een_kvk_base_url_op_productie_met_basisprofielen_pad() -> None:
    urls = _base_urls_in_deploy()
    assert urls == [PRODUCTIE_BASE_URL], f"verwacht precies één KVK_BASE_URL={PRODUCTIE_BASE_URL}, gevonden {urls}"
    assert "/test/" not in urls[0]
    assert urls[0].endswith("/basisprofielen"), "de client plakt /{kvkNummer} achter de base-URL"


def test_deploy_yml_mount_kvk_api_key_precies_een_keer_als_secret_op_de_service() -> None:
    hits = re.findall(r"KVK_API_KEY=KVK_API_KEY:latest", _deploy_tekst())
    assert len(hits) == 1, f"verwacht één secret-mount KVK_API_KEY=KVK_API_KEY:latest, gevonden {len(hits)}"
    # Nooit als klare waarde in env-vars (besluit 0012): alleen de --set-secrets-vorm mag voorkomen.
    assert not re.search(r"KVK_API_KEY=(?!KVK_API_KEY:latest)", _deploy_tekst())


def test_test_en_productie_base_url_delen_hetzelfde_pad() -> None:
    assert kvk._TEST_BASE.rsplit("/", 1)[1] == PRODUCTIE_BASE_URL.rsplit("/", 1)[1] == "basisprofielen"


def test_productie_url_uit_deploy_yml_met_eigen_sleutel_doorstaat_de_consistentiecheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "kvk_base_url", _base_urls_in_deploy()[0])
    monkeypatch.setattr(settings, "kvk_api_key", "geen-echte-sleutel-alleen-vorm")
    assert kvk.is_testomgeving() is False
    assert kvk.config_probleem() is None


def test_productie_url_zonder_eigen_sleutel_wordt_geweigerd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "kvk_base_url", PRODUCTIE_BASE_URL)
    monkeypatch.setattr(settings, "kvk_api_key", None)
    assert kvk.config_probleem() is not None
