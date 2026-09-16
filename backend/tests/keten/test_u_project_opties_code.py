"""Casus (u) — projectveld in het controle-/verplichting-scherm (feedback Peter 16-09, screenshot Offerte S00642
Bouwadvies Oost Nederland): de lijstroute `GET /administraties/{id}/projecten` die élke project-combobox voedt, moet
(1) de projectcode los van de naam dragen (STAP-0 16-09: RLZ heeft géén codeveld op Projects, de code is de
cijfer-prefix uit de naamconventie), (2) inactieve projecten ZICHTBAAR onderaan zetten i.p.v. verbergen, en (3) een
administratie zonder projecten een gewone lege lijst geven — de frontend maakt daar "Geen projecten in deze
administratie — Project aanmaken →" van, nooit meer een weggeknipte sliver."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from tests.keten.conftest import PROJECT_25011, PROJECT_26049, PROJECT_26084, Keten


def _projecten(keten: Keten) -> list[dict]:
    resp = keten.api.get(f"/administraties/{keten.administratie_id}/projecten", headers=keten.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["projecten"]


def test_projectcode_los_van_de_naam(keten: Keten) -> None:
    per_id = {p["id"]: p for p in _projecten(keten)}
    assert per_id[str(PROJECT_26049)] == {
        "id": str(PROJECT_26049),
        "code": "26049",
        "naam": "Hoofddorp (Grunsven)",
        "is_actief": True,
    }
    assert per_id[str(PROJECT_25011)]["code"] == "25011"
    assert per_id[str(PROJECT_26084)]["naam"] == "Opdrachtgever A (Universal Nederland)"


def test_inactief_project_blijft_zichtbaar_onderaan(keten: Keten) -> None:
    inactief_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    with keten.admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                "VALUES (:id, :adm, '00001 Afgesloten werk (Oud)', false, '{}'::jsonb)"
            ),
            {"id": inactief_id, "adm": keten.administratie_id},
        )
    try:
        rijen = _projecten(keten)
        assert rijen[-1] == {
            "id": str(inactief_id),
            "code": "00001",
            "naam": "Afgesloten werk (Oud)",
            "is_actief": False,
        }
        # Actieve projecten blijven alfabetisch vóór het inactieve — het inactieve staat ondanks '00001' NIET bovenaan.
        assert [r["is_actief"] for r in rijen[:-1]] == [True] * (len(rijen) - 1)
    finally:
        with keten.admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM boekhouding.project_cache WHERE id = :id"), {"id": inactief_id})
