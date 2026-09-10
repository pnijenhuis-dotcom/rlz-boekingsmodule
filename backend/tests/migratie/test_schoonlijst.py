"""Blok D1 (bundel 10-09): schoonlijst vóór een RLZ → Odoo-overstap — getest zonder RLZ (dict-client).

Elke categorie, paginering ($top/$skip), lege administratie, 403 op één route = zichtbare regel i.p.v. crash, Receipts
optioneel (404 = OVERGESLAGEN), bijlagecheck-grens zichtbaar, `$expand`-terugval, verwachtingen náást gevonden, JSON
stabiel gesorteerd. Geen DB nodig."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

from app.migratie import schoonlijst
from app.migratie.schoonlijst import (
    Schoonlijst,
    als_markdown,
    dubbele_iban,
    dubbelen,
    maak_schoonlijst,
    normaliseer_iban,
    open_bankregels,
    parse_verwacht,
)
from app.rlz import lezen
from app.rlz.client import RlzApiError

ENTITY_A = str(uuid.uuid4())


def _doc(
    *,
    boekstuk: str,
    bedrag: float | None = 100.0,
    datum: str = "2026-08-15T00:00:00",
    entity: str | None = ENTITY_A,
    entity_naam: str = "Notaris Ouwerkerk",
    status: int = 2,
    omschrijving: str | None = "Betreft Kerkstraat 44",
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "ReceiptNumber": boekstuk,
        "BaseInvoiceAmount": bedrag,
        "Date": datum,
        "BookDate": datum,
        "Entity": {"id": entity, "Name": entity_naam} if entity else None,
        "Status": status,
        "Description": omschrijving,
        "Reference": None,
    }


def _tx(*, open_bedrag: float, bedrag: float = 250.0, rekening: str = "Betaalrekening", naam: str = "Homekeur") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "TransactionId": "TX-1",
        "BookDate": "2026-08-20T00:00:00",
        "Amount": bedrag,
        "OpenAmount": open_bedrag,
        "IsComplete": open_bedrag == 0,
        "Name": naam,
        "Reference": "keuring Kerkstraat 44",
        "CounterAccount": "NL91ABNA0417164300",
        "PaymentAccount": {"id": str(uuid.uuid4()), "Name": rekening},
    }


def _rekening(*, naam: str, iban: str | None, type_: int = 1, archief: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "Name": naam,
        "IBAN": iban,
        "Type": type_,
        "IsArchived": archief,
        "CurrentBalance": 10.0,
    }


class NepClient:
    """Dict-client: per pad een lijst rijen; `fouten` per pad = RlzApiError; `uploads` per document-id = lijst.
    Registreert élke GET (pad + params)."""

    def __init__(
        self,
        collecties: dict[str, list[dict]] | None = None,
        *,
        fouten: dict[str, RlzApiError] | None = None,
        uploads: dict[str, list[dict]] | None = None,
        expand_weigeren: set[str] | None = None,
    ) -> None:
        self.collecties = collecties or {}
        self.fouten = fouten or {}
        self.uploads = uploads or {}
        self.expand_weigeren = expand_weigeren or set()
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        if path in self.fouten:
            raise self.fouten[path]
        if path.endswith("/Uploads"):
            collectie, doc_id, _ = path.split("/")
            if collectie not in self.collecties:
                raise RlzApiError(404, "GET", path, "_NotFound")
            return {"value": self.uploads.get(doc_id, [])[: int(params.get("$top", 1))]}
        if path not in self.collecties:
            raise RlzApiError(404, "GET", path, "_NotFound")
        if "$expand" in params and path in self.expand_weigeren:
            raise RlzApiError(400, "GET", path, "expand niet ondersteund")
        rijen = self.collecties[path]
        skip = int(params.get("$skip", 0))
        top = int(params.get("$top", len(rijen) or 1))
        return {"value": rijen[skip : skip + top]}

    def __enter__(self) -> NepClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _basis() -> dict[str, list[dict]]:
    return {
        "PurchaseInvoices": [],
        "SalesInvoices": [],
        "ManualJournals": [],
        "PaymentTransactions": [],
        "PaymentAccounts": [],
    }


# ---- helpers -----------------------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        ("iban", "verwacht"),
        [
            ("NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"),
            ("nl91abna0417164300", "NL91ABNA0417164300"),
            (None, None),
            ("", None),
        ],
    )
    def test_normaliseer_iban(self, iban: str | None, verwacht: str | None) -> None:
        assert normaliseer_iban(iban) == verwacht

    def test_parse_verwacht(self) -> None:
        assert parse_verwacht("concepten=17, dubbelen=3,open_bankregels=44,dubbele_iban=1") == {
            "concepten": 17,
            "dubbelen": 3,
            "open_bankregels": 44,
            "dubbele_iban": 1,
        }
        assert parse_verwacht(None) == {}
        with pytest.raises(ValueError, match="onbekende verwachting"):
            parse_verwacht("bankregels=44")


# ---- categorieën (puur) --------------------------------------------------------------------------------


class TestCategorieen:
    def test_concepten_alleen_status_1(self) -> None:
        rijen = [
            _doc(boekstuk="RLZ-04-1", status=1),
            _doc(boekstuk="RLZ-04-2", status=2),
            _doc(boekstuk="RLZ-04-3", status=3),
        ]
        uit = schoonlijst.concepten("PurchaseInvoices", rijen)
        assert [r.boekstuk for r in uit] == ["RLZ-04-1"]
        assert "concept" in uit[0].bevinding
        assert uit[0].entity == "Notaris Ouwerkerk"

    def test_dubbelen_zelfde_bedrag_datum_relatie(self) -> None:
        rijen = [
            _doc(boekstuk="RLZ-04-846", bedrag=20000.0),
            _doc(boekstuk="RLZ-04-847", bedrag=20000.0),
            _doc(boekstuk="RLZ-04-848", bedrag=20000.0, status=1),
            _doc(boekstuk="RLZ-04-900", bedrag=20000.0, datum="2026-08-16T00:00:00"),  # andere datum
            _doc(boekstuk="RLZ-04-901", bedrag=20000.01),  # cent verschil
        ]
        uit = dubbelen("PurchaseInvoices", rijen)
        assert sorted(r.boekstuk for r in uit) == ["RLZ-04-846", "RLZ-04-847", "RLZ-04-848"]
        assert len({r.extra["groep"] for r in uit}) == 1
        assert all("3× € 20000.00 op 2026-08-15" in r.bevinding for r in uit)
        concept = next(r for r in uit if r.boekstuk == "RLZ-04-848")
        assert concept.bevinding.endswith("(concept)")

    def test_dubbelen_beide_zonder_relatie_tellen_en_andere_relatie_niet(self) -> None:
        rijen = [
            _doc(boekstuk="A", entity=None),
            _doc(boekstuk="B", entity=None),
            _doc(boekstuk="C", entity=str(uuid.uuid4())),
        ]
        uit = dubbelen("ManualJournals", rijen)
        assert sorted(r.boekstuk for r in uit) == ["A", "B"]
        assert "zonder relatie" in uit[0].bevinding

    def test_open_bankregels_toetst_open_amount_niet_is_complete(self) -> None:
        rijen = [_tx(open_bedrag=250.0), _tx(open_bedrag=0.0), _tx(open_bedrag=-12.5, rekening="Spaarrekening")]
        uit = open_bankregels(rijen)
        assert len(uit) == 2
        assert {r.extra["rekening"] for r in uit} == {"Betaalrekening", "Spaarrekening"}
        assert uit[0].bedrag == Decimal("250.00")
        assert "NL91ABNA0417164300" in uit[0].bevinding

    def test_dubbele_iban_noemt_beide_rekeningen(self) -> None:
        rijen = [
            _rekening(naam="Betaalrekening", iban="NL91 ABNA 0417 1643 00"),
            _rekening(naam="Spaarrekening", iban="NL91ABNA0417164300", archief=True),
            _rekening(naam="Kas", iban=None, type_=3),
            _rekening(naam="Andere", iban="NL02RABO0123456789"),
        ]
        uit = dubbele_iban(rijen)
        assert len(uit) == 2
        assert all("Betaalrekening + Spaarrekening" in r.bevinding for r in uit)
        assert any(r.entity.endswith("(gearchiveerd)") for r in uit)


# ---- maak_schoonlijst -------------------------------------------------------------------------------------


class TestMaakSchoonlijst:
    def test_lege_administratie(self) -> None:
        client = NepClient(_basis())
        lijst = maak_schoonlijst(client, administratie_id="a", rlz_admin_id="rlz")
        assert lijst.tellers == {
            "concepten": 0,
            "dubbelen": 0,
            "open_bankregels": 0,
            "dubbele_iban": 0,
            "zonder_relatie_met_bijlage": 0,
        }
        assert lijst.fouten == []
        assert any("Receipts" in o for o in lijst.overgeslagen)  # optionele collectie: 404 = overgeslagen, geen fout
        md = als_markdown(lijst, administratie_naam="Leeg")
        assert "| Concepten in RLZ (Status 1) | 0 | — | — |" in md
        assert "_geen_" in md

    def test_pagineert_met_top_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lezen, "PAGINA_GROOTTE", 2)
        data = _basis()
        data["PurchaseInvoices"] = [_doc(boekstuk=f"RLZ-04-{i}", status=1, bedrag=float(i)) for i in range(5)]
        client = NepClient(data)
        lijst = maak_schoonlijst(client)
        assert lijst.tellers["concepten"] == 5
        skips = [p["$skip"] for pad, p in client.calls if pad == "PurchaseInvoices"]
        assert skips == ["0", "2", "4"]
        assert all(p["$top"] == "2" for pad, p in client.calls if pad == "PurchaseInvoices")
        assert client.calls[0][1]["$expand"] == "Entity"

    def test_403_op_een_route_is_zichtbare_regel_geen_crash(self) -> None:
        data = _basis()
        data["PaymentAccounts"] = [
            _rekening(naam="Betaal", iban="NL91ABNA0417164300"),
            _rekening(naam="Spaar", iban="NL91ABNA0417164300"),
        ]
        client = NepClient(
            data, fouten={"PaymentTransactions": RlzApiError(403, "GET", "PaymentTransactions", "Forbidden")}
        )
        lijst = maak_schoonlijst(client)
        assert [(f.route, f.status) for f in lijst.fouten] == [("PaymentTransactions", 403)]
        assert lijst.tellers["dubbele_iban"] == 1  # de andere categorieën lopen door
        md = als_markdown(lijst)
        assert "#### Fouten" in md and "| PaymentTransactions | 403 |" in md

    def test_expand_geweigerd_valt_terug_zonder_expand(self) -> None:
        data = _basis()
        data["SalesInvoices"] = [_doc(boekstuk="RLZ-01-1", status=1)]
        client = NepClient(data, expand_weigeren={"SalesInvoices"})
        lijst = maak_schoonlijst(client)
        assert lijst.tellers["concepten"] == 1
        assert any("SalesInvoices: $expand geweigerd" in o for o in lijst.overgeslagen)
        sales_calls = [p for pad, p in client.calls if pad == "SalesInvoices"]
        assert "$expand" in sales_calls[0] and "$expand" not in sales_calls[-1]

    def test_receipts_ontdubbeld_tegen_salesinvoices(self) -> None:
        data = _basis()
        receipt = _doc(boekstuk="RLZ-01-9", status=1, entity=None)
        data["SalesInvoices"] = [receipt]
        data["Receipts"] = [receipt, _doc(boekstuk="RLZ-01-10", status=1, entity=None)]
        client = NepClient(data)
        lijst = maak_schoonlijst(client)
        assert sorted(r.boekstuk for r in lijst.rijen["concepten"]) == ["RLZ-01-10", "RLZ-01-9"]
        assert lijst.gelezen["Receipts"] == 2

    def test_zonder_relatie_met_bijlage_en_grens(self) -> None:
        data = _basis()
        met = _doc(boekstuk="RLZ-06-1", entity=None, omschrijving="Aankoop Kerkstraat 44")
        zonder = _doc(boekstuk="RLZ-06-2", entity=None, datum="2026-08-14T00:00:00")
        oud = _doc(boekstuk="RLZ-06-0", entity=None, datum="2025-01-01T00:00:00")
        met_relatie = _doc(boekstuk="RLZ-04-1")
        data["ManualJournals"] = [oud, met, zonder]
        data["PurchaseInvoices"] = [met_relatie]
        client = NepClient(data, uploads={met["id"]: [{"id": "u1", "FileName": "nota.pdf"}], oud["id"]: [{"id": "u0"}]})
        lijst = maak_schoonlijst(client, max_bijlage_checks=2)
        # nieuwste eerst: `met` (15-08) en `zonder` (14-08) gecontroleerd, `oud` buiten de grens
        assert lijst.bijlage_checks == 2 and lijst.bijlage_niet_gecontroleerd == 1
        rijen = {r.boekstuk: r for r in lijst.rijen["zonder_relatie_met_bijlage"]}
        assert rijen["RLZ-06-1"].extra["bijlage"] is True and "suggereert een factuur" in rijen["RLZ-06-1"].bevinding
        assert "RLZ-06-2" not in rijen  # geen bijlage = geen bevinding
        assert "NIET gecontroleerd" in rijen["RLZ-06-0"].bevinding
        assert lijst.tellers["zonder_relatie_met_bijlage"] == 1
        upload_calls = [pad for pad, p in client.calls if pad.endswith("/Uploads")]
        assert len(upload_calls) == 2 and all(pad.startswith("ManualJournals/") for pad in upload_calls)
        assert not any(met_relatie["id"] in pad for pad in upload_calls)

    def test_verwacht_naast_gevonden_en_json_stabiel(self) -> None:
        data = _basis()
        data["PurchaseInvoices"] = [
            _doc(boekstuk="RLZ-04-2", status=1, bedrag=20000.0),
            _doc(boekstuk="RLZ-04-1", status=1, bedrag=20000.0),
        ]
        client = NepClient(data)
        lijst = maak_schoonlijst(
            client, verwacht={"concepten": 17, "dubbelen": 1}, administratie_id="x", rlz_admin_id="r"
        )
        md = als_markdown(lijst, administratie_naam="VGG")
        assert "| Concepten in RLZ (Status 1) | 2 | 17 | -15 |" in md
        assert "| Vermoedelijke dubbelen (zelfde collectie, bedrag, datum, relatie) | 1 | 1 | gelijk |" in md
        d = json.loads(lijst.als_json())
        assert d["verwacht"] == {
            "concepten": 17,
            "dubbelen": 1,
            "open_bankregels": None,
            "dubbele_iban": None,
            "zonder_relatie_met_bijlage": None,
        }
        assert [r["boekstuk"] for r in d["categorieen"]["concepten"]] == ["RLZ-04-1", "RLZ-04-2"]
        assert d["categorieen"]["concepten"][0]["bedrag"] == "20000.00"
        # twee runs op dezelfde data → identieke JSON (op gegenereerd_op na)
        lijst2 = maak_schoonlijst(
            NepClient(data), verwacht={"concepten": 17, "dubbelen": 1}, administratie_id="x", rlz_admin_id="r"
        )
        d2 = json.loads(lijst2.als_json())
        d.pop("gegenereerd_op"), d2.pop("gegenereerd_op")
        assert d == d2

    def test_geen_writes_alleen_get(self) -> None:
        """De client kent alleen `get`; elke andere methode zou een AttributeError geven — de lijst is lees-only."""
        data = _basis()
        data["PurchaseInvoices"] = [_doc(boekstuk="RLZ-04-1", status=1)]
        client = NepClient(data)
        assert isinstance(maak_schoonlijst(client), Schoonlijst)
        assert not hasattr(client, "put") and not hasattr(client, "post_action")
