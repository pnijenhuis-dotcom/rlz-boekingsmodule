"""Casus (v) — project afgesloten (blok 3 18-09, Peter: "als een project afgesloten is kan het uit de lijst"): een
factuurregel op een AFGESLOTEN project is een ORANJE SIGNAAL, nooit een blokkade (nagekomen facturen bestaan). De check leeft
lokaal (`check_project_afgesloten`, geen RLZ) en draait in beide rapport-takken van `boekvoorstel` (normaal + RLZ-storing).
Hier: (1) het pure gedrag op de gouden-set-projecten, (2) de lijstroute `GET /administraties/{id}/projecten` houdt een
afgesloten project ZICHTBAAR onderaan als inactief (combobox-patroon 16-09) — het verdwijnt uit de keuzelijsten van planning/
weekstaat via `is_actief`, niet door 'm te verbergen op een document dat er al op staat."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.documenten.checks import CheckRegel, check_project_afgesloten
from tests.keten.conftest import PROJECT_26049, PROJECT_26084, Keten


def _regel(pid: uuid.UUID | None) -> CheckRegel:
    return CheckRegel(ledger_id=None, taxrate_id=None, netto_bedrag=Decimal("100"), btw_bedrag=Decimal("21"), project_id=pid)


def test_regel_op_afgesloten_project_is_signaal_geen_blokkade() -> None:
    uit = check_project_afgesloten(
        regels=[_regel(PROJECT_26049), _regel(PROJECT_26084), _regel(None)],
        afgesloten={PROJECT_26049: ("26049 Hoofddorp (Grunsven)", date(2026, 9, 15))},
    )
    assert uit is not None
    assert uit.ok is True and uit.signaal is True and uit.naam == "Project afgesloten"
    assert "26049 Hoofddorp (Grunsven) (afgesloten op 15-09-2026)" in uit.melding
    assert "26084" not in uit.melding
    # Niets afgesloten = geen rij (de check zwijgt tot hij iets te zeggen heeft).
    assert check_project_afgesloten(regels=[_regel(PROJECT_26049)], afgesloten={}) is None


def test_afgesloten_project_blijft_zichtbaar_onderaan_in_de_lijstroute(keten: Keten) -> None:
    with keten.admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE boekhouding.project_cache SET status = 'afgesloten', is_actief = false, afgesloten_op = now() "
                "WHERE id = :id AND administratie_id = :adm"
            ),
            {"id": PROJECT_26049, "adm": keten.administratie_id},
        )
    try:
        resp = keten.api.get(f"/administraties/{keten.administratie_id}/projecten", headers=keten.headers)
        assert resp.status_code == 200, resp.text
        rijen = resp.json()["projecten"]
        assert rijen[-1]["id"] == str(PROJECT_26049) and rijen[-1]["is_actief"] is False
        assert all(r["is_actief"] for r in rijen[:-1])
    finally:
        with keten.admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.project_cache SET status = 'lopend', is_actief = true, afgesloten_op = NULL "
                    "WHERE id = :id AND administratie_id = :adm"
                ),
                {"id": PROJECT_26049, "adm": keten.administratie_id},
            )
