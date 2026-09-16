"""Lees-only nulmeting activa (STAP-0 16-09): MVA-selectie (vlag alleen is te breed, a9) en het rapport op een fake."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.activa import nulmeting

L1, L2, L3, L4 = (str(uuid.UUID(int=n)) for n in (1, 2, 3, 4))


class _Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get(self, pad: str, *, params=None):
        self.calls.append((pad, params or {}))
        if pad == "Ledgers":
            return {
                "value": [
                    {
                        "id": L1,
                        "AccountNumber": "0107",
                        "Description": "Kantoorinventaris",
                        "AccountType": 3,
                        "IsFixedAssetAccount": True,
                    },
                    {
                        "id": L2,
                        "AccountNumber": "7005",
                        "Description": "Inhuur steiger",
                        "AccountType": 2,
                        "IsFixedAssetAccount": True,
                    },
                    {
                        "id": L3,
                        "AccountNumber": "1100",
                        "Description": "Voorraad",
                        "AccountType": 3,
                        "IsFixedAssetAccount": True,
                    },
                    {
                        "id": L4,
                        "AccountNumber": "0101",
                        "Description": "Totaal",
                        "AccountType": 3,
                        "IsFixedAssetAccount": True,
                        "IsTotalAccount": True,
                    },
                ]
            }
        if pad == "FixedAssets":
            return {"@odata.count": 2, "value": [{"id": "f"}]}
        if pad == "JournalEntryLines":
            return {
                "value": [{"DebitAmount": 1000.0, "CreditAmount": 0.0}, {"DebitAmount": 0.0, "CreditAmount": 250.5}]
            }
        raise AssertionError(pad)

    def close(self) -> None:
        pass


def test_mva_selectie_vlag_plus_type_plus_reeks() -> None:
    assert nulmeting.is_mva_rekening({"AccountNumber": "0107", "AccountType": 3, "IsFixedAssetAccount": True})
    assert not nulmeting.is_mva_rekening({"AccountNumber": "7005", "AccountType": 2, "IsFixedAssetAccount": True})
    assert not nulmeting.is_mva_rekening({"AccountNumber": "1100", "AccountType": 3, "IsFixedAssetAccount": True})
    assert not nulmeting.is_mva_rekening({"AccountNumber": "0107", "AccountType": 3, "IsFixedAssetAccount": False})


def test_saldo_debit_min_credit_en_calls() -> None:
    fake = _Fake()
    saldo, regels, calls = nulmeting.saldo_rlz(fake, L1)
    assert saldo == Decimal("749.50") and regels == 2 and calls == 1
    assert fake.calls[0][1]["$filter"] == f"Account/id eq {L1}"


def test_meting_op_fake_client(monkeypatch) -> None:
    administratie_id = uuid.uuid4()  # onbekende administratie: geen RLS-rijen, RLZ via de fake
    monkeypatch.setattr(nulmeting, "backend_voor", lambda _aid: nulmeting.Backend.RLZ)
    fake = _Fake()
    m = nulmeting.meet_administratie(administratie_id, client=fake)
    assert [r.code for r in m.rekeningen] == ["0107"]  # 7005 (kosten), 1100 (voorraad) en het totaal vallen af
    assert m.fixed_assets == 2 and m.rekeningen[0].saldo == Decimal("749.50")
    assert m.calls == 3
    uit: list[str] = []
    nulmeting.print_rapport([m], dagen=400, stdout=uit.append)
    assert "1 MVA-rekening(en), 2 activa" in uit[1] and "0107 Kantoorinventaris: saldo € 749.50" in uit[2]
