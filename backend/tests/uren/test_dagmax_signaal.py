"""Signaal >N uur per dag (steigerbouw-run A6): som van de uren per persoon per kalenderdag over
álle weekstaten heen (twee projecten = twee staten) boven de administratie-drempel = oranje vlag
op de dagregel — geen blokkade; drempel per administratie (default 12) via beheer, geaudit."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.beheer import service as beheer_service
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service
from tests.uren.conftest import maak_project

client = TestClient(app)
JAAR, WEEK = 2026, 34
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _zet(administratie_id, zzper, project_id, uren):
    return service.zet_dag(
        administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK,
        datum=MAANDAG, uren=Decimal(uren), m2=None, actor_id=zzper,
    )


def test_som_over_projecten_heen_boven_drempel(administratie_id, project_id, gekoppelde_zzper, beheerder_id, admin_engine):
    zzper = gekoppelde_zzper
    project_b = maak_project(admin_engine, administratie_id, "26099 Breda (Moeskops)")
    service.koppel_project(administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_b, actor_id=beheerder_id)
    staat_a = _zet(administratie_id, zzper, project_id, "7")
    assert staat_a.dagen[0].boven_dagmax is False and staat_a.dagen[0].dagmax_uren == Decimal("12")
    # Concept-uren op het andere project tellen nog niet mee ('ingediende uren'); ná indienen wél.
    _zet(administratie_id, zzper, project_b, "6")
    staat_a = service.weekstaat_detail(administratie_id=administratie_id, weekstaat_id=staat_a.id)
    assert staat_a.dagen[0].dag_totaal_uren == Decimal("7") and not staat_a.dagen[0].boven_dagmax
    service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_b, jaar=JAAR, weeknummer=WEEK, actor_id=zzper)
    staat_a = service.weekstaat_detail(administratie_id=administratie_id, weekstaat_id=staat_a.id)
    assert staat_a.dagen[0].dag_totaal_uren == Decimal("13") and staat_a.dagen[0].boven_dagmax is True
    # Indienen blijft mogelijk — signaal, geen blokkade.
    staat_a = service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=WEEK, actor_id=zzper)
    assert staat_a.status == "ingediend" and staat_a.dagen[0].boven_dagmax


def test_drempel_per_administratie_geaudit(administratie_id, project_id, gekoppelde_zzper, beheerder_id):
    with pytest.raises(beheer_service.BeheerFout):
        beheer_service.zet_uren_dagmax(actor_id=beheerder_id, administratie_id=administratie_id, dagmax_uren=Decimal("25"))
    beheer_service.zet_uren_dagmax(actor_id=beheerder_id, administratie_id=administratie_id, dagmax_uren=Decimal("8"))
    staat = _zet(administratie_id, gekoppelde_zzper, project_id, "9")
    assert staat.dagen[0].boven_dagmax is True and staat.dagen[0].dagmax_uren == Decimal("8")
    h = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
    resp = client.get(f"/administraties/{administratie_id}/uren-dagmax-instelling", headers=h)
    assert resp.status_code == 200 and Decimal(resp.json()["dagmax_uren"]) == Decimal("8")
    resp = client.put(f"/administraties/{administratie_id}/uren-dagmax-instelling", json={"dagmax_uren": "10"}, headers=h)
    assert resp.status_code == 200
    resp = client.put(f"/administraties/{administratie_id}/uren-dagmax-instelling", json={"dagmax_uren": "0"}, headers=h)
    assert resp.status_code == 422
    resp = client.get("/administraties/instellingen", headers=h)
    if resp.status_code == 200:
        rij = next(a for a in resp.json()["administraties"] if a["id"] == str(administratie_id))
        assert Decimal(rij["uren_dagmax_uren"]) == Decimal("10")
    _ = uuid.uuid4()
