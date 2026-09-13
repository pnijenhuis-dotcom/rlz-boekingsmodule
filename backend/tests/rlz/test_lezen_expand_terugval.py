"""Blok 7b 13-09 (punt 1a): `lees_collectie` mét terugval-keten op `$expand` — de regels komen mee op de collectie
(`Entity,DocumentLineList($expand=Account,TaxRate)`); weigert RLZ die vorm (400) dan de volgende variant, uiteindelijk
zonder expand; `expand_gebruikt` zegt welke vorm het werd, `expand_gelukt` blijft alleen True bij de eerste."""

from __future__ import annotations

from app.rlz.client import RlzApiError, RlzWebfilterError
from app.rlz.lezen import lees_collectie


class Client:
    def __init__(self, weiger: set[str], *, webfilter: bool = False) -> None:
        self.weiger = weiger
        self.webfilter = webfilter
        self.calls: list[dict] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append(params)
        if self.webfilter:
            raise RlzWebfilterError(403, "GET", path, "<HTML>Access Denied</HTML>")
        if params.get("$expand") in self.weiger:
            raise RlzApiError(400, "GET", path, "expand onbekend")
        return {"value": [{"id": "1", "expand": params.get("$expand")}]}


def test_eerste_variant_lukt() -> None:
    c = Client(set())
    uit = lees_collectie(
        c, "PurchaseInvoices", expand="Entity,DocumentLineList($expand=Account,TaxRate)", expand_terugval=("Entity",)
    )
    assert (
        uit.gelukt and uit.expand_gelukt and uit.expand_gebruikt == "Entity,DocumentLineList($expand=Account,TaxRate)"
    )
    assert len(c.calls) == 1


def test_terugval_op_de_volgende_variant_zichtbaar() -> None:
    c = Client({"Entity,DocumentLineList($expand=Account,TaxRate)"})
    uit = lees_collectie(
        c, "PurchaseInvoices", expand="Entity,DocumentLineList($expand=Account,TaxRate)", expand_terugval=("Entity",)
    )
    assert uit.gelukt and uit.expand_gelukt is False and uit.expand_gebruikt == "Entity"
    assert [p.get("$expand") for p in c.calls] == ["Entity,DocumentLineList($expand=Account,TaxRate)", "Entity"]


def test_uiteindelijk_zonder_expand() -> None:
    c = Client({"A,B", "A"})
    uit = lees_collectie(c, "X", expand="A,B", expand_terugval=("A",))
    assert uit.gelukt and uit.expand_gebruikt is None and uit.expand_gelukt is False
    assert [p.get("$expand") for p in c.calls] == ["A,B", "A", None]


def test_andere_fout_dan_400_stopt_de_keten() -> None:
    c = Client(set(), webfilter=True)
    uit = lees_collectie(c, "X", expand="A,B", expand_terugval=("A",))
    assert not uit.gelukt and isinstance(uit.fout, RlzWebfilterError) and len(c.calls) == 1
