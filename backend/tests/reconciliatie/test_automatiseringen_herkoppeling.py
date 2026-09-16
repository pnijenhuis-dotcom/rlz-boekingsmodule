"""Teller `doorbelasting_herkoppeling` (blok 1, 16-09 nacht): gedaan = gekoppeld, overgeslagen `doel_niet_onboarded`
(zichtbaar, geen LET-OP) en `doel_bijna_match` = harde voorwaarde mét deeplink naar Instellingen › Administraties ›
‹bron› › Doorbelasting. Puur op `bereken`/`bevindingen`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.reconciliatie import automatiseringen as au

NU = datetime(2026, 9, 17, 3, 0, tzinfo=UTC)
BRON = uuid.uuid4()


def _feiten(nw: dict) -> au.Feiten:
    f = au.Feiten(administraties={BRON: "Kempen Facilities"})
    f.audit.append(au.AuditFeit(actie="doorbelasting_herkoppeling_run", tijdstip=NU - timedelta(hours=2), administratie_id=BRON, nieuwe_waarde=nw))
    return f


def test_teller_gedaan_overgeslagen_en_let_op_met_deeplink() -> None:
    nw = {
        "open": 3, "gekoppeld": 1, "bijna_match": 1, "meerdere": 0, "geen": 1,
        "niet_gekoppeld": [{"mapping_id": str(uuid.uuid4()), "doelentiteit_naam": "Mantelzorgwoning MN B.V.", "reden": "bijna_match",
                            "kandidaten": [{"id": str(uuid.uuid4()), "naam": "Mantelzorgwoningen Midden Nederland"}]}],
    }
    tellers = {t.sleutel: t for t in au.bereken(_feiten(nw), nu=NU)}
    t = tellers[au.DOORBELASTING_HERKOPPELING]
    assert t.stand == "altijd" and t.dag.gedaan == 1 and t.dag.overgeslagen[au.DOEL_NIET_ONBOARDED] == 1
    assert t.dag.overgeslagen[au.DOEL_BIJNA_MATCH] == 1 and t.dag.verwacht == 3
    assert len(t.harde_voorwaarden) == 1
    hv = t.harde_voorwaarden[0]
    assert hv.categorie == au.DOEL_BIJNA_MATCH and hv.administratie_id == BRON and "Mantelzorgwoning" in (hv.voorbeeld or "")
    bev = [b for b in au.bevindingen([t], namen={BRON: "Kempen Facilities"}) if b["soort"] == "let_op"]
    assert len(bev) == 1
    assert bev[0]["detail"]["doel_pad"] == f"/instellingen/administraties/{BRON}/doorbelasting"
    assert bev[0]["detail"]["reden"] == au.DOEL_BIJNA_MATCH
    assert au.DOEL_BIJNA_MATCH in au.HARDE_VOORWAARDEN and au.DOEL_NIET_ONBOARDED not in au.HARDE_VOORWAARDEN


def test_geen_kandidaat_is_geen_let_op() -> None:
    nw = {"open": 1, "gekoppeld": 0, "bijna_match": 0, "meerdere": 0, "geen": 1, "niet_gekoppeld": []}
    tellers = {t.sleutel: t for t in au.bereken(_feiten(nw), nu=NU)}
    t = tellers[au.DOORBELASTING_HERKOPPELING]
    assert t.harde_voorwaarden == [] and t.dag.overgeslagen[au.DOEL_NIET_ONBOARDED] == 1
    assert not [b for b in au.bevindingen([t]) if b["soort"] == "let_op"]
