"""Guard: de grootboek-sync schrijft `is_activa` uit de bron — RLZ (vlag ÉN AccountType 3 ÉN 0xxx) en Odoo
(`asset_fixed`)."""

from __future__ import annotations

import uuid

from app.odoo import sync as odoo_sync
from app.sync import service as sync_service


def _rlz(code: str, soort: int, vlag: bool, totaal: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "AccountNumber": code,
        "Description": "x",
        "AccountType": soort,
        "IsTotalAccount": totaal,
        "IsFixedAssetAccount": vlag,
    }


def test_rlz_grootboek_waarden_schrijft_is_activa() -> None:
    assert sync_service._grootboek_waarden(_rlz("0107", 3, True))["is_activa"] is True
    assert sync_service._grootboek_waarden(_rlz("3000", 3, True))["is_activa"] is False  # vlag te breed (STAP-0 a9)
    assert sync_service._grootboek_waarden(_rlz("0107", 2, True))["is_activa"] is False
    assert sync_service._grootboek_waarden(_rlz("0107", 3, False))["is_activa"] is False
    assert sync_service._grootboek_waarden(_rlz("0100", 3, True, totaal=True))["is_activa"] is False
    # Zonder de vlag in de respons (oude fake/onvolledige rij) = False, nooit een KeyError.
    rij = _rlz("0107", 3, True)
    del rij["IsFixedAssetAccount"]
    assert sync_service._grootboek_waarden(rij)["is_activa"] is False


def test_odoo_grootboek_waarden_schrijft_is_activa() -> None:
    basis = {"code": "0107", "naam": "Inventaris", "soort": 3, "standaard_taxrate_id": None}
    assert odoo_sync._grootboek_waarden({**basis, "account_type": "asset_fixed"})["is_activa"] is True
    assert odoo_sync._grootboek_waarden({**basis, "account_type": "asset_current"})["is_activa"] is False
    assert odoo_sync._grootboek_waarden(basis)["is_activa"] is False
