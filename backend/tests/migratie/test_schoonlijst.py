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
        assert parse_verwacht("systeemhulzen_open_bank=44,concept_kopie_van_geboekt=11,bank_bevestigd=3") == {
            "systeemhulzen_open_bank": 44,
            "concept_kopie_van_geboekt": 11,
            "bank_bevestigd": 3,
        }
        assert parse_verwacht("zelfde_bedrag_verschillend_kenmerk=40") == {"zelfde_bedrag_verschillend_kenmerk": 40}


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
            "systeemhulzen_open_bank": 0,
            "concept_kopie_van_geboekt": 0,
            "dubbelen": 0,
            "zelfde_bedrag_verschillend_kenmerk": 0,
            "bank_bevestigd": 0,
            "open_bankregels": 0,
            "dubbele_iban": 0,
            "zonder_relatie_met_bijlage": 0,
        }
        assert lijst.bank_gelezen is True and lijst.bank_mutaties == 0 and lijst.bank_reeksen == {}
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
        assert (
            "| Vermoedelijke dubbelen (zelfde collectie, bedrag, datum, relatie; bank-tekort) | 1 | 1 | gelijk |" in md
        )
        d = json.loads(lijst.als_json())
        assert d["verwacht"] == {
            "concepten": 17,
            "systeemhulzen_open_bank": None,
            "concept_kopie_van_geboekt": None,
            "dubbelen": 1,
            "zelfde_bedrag_verschillend_kenmerk": None,
            "bank_bevestigd": None,
            "open_bankregels": None,
            "dubbele_iban": None,
            "zonder_relatie_met_bijlage": None,
        }
        assert d["bank"] == {"gelezen": True, "mutaties": 0, "reeksen": {}}
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


# ---- run 2 VGG 12-09 blok 1: ontknip, systeemhulzen, kopieën, verschillend kenmerk, bank leidend ----------------


def _d(
    boekstuk: str | None,
    bedrag: float,
    datum: str,
    omschrijving: str | None = None,
    *,
    status: int = 2,
    entity: tuple[str, str] | None = None,
) -> dict:
    """VGG-rij met de LETTERLIJKE RLZ-vorm: `Description` als `\\n`-regels van 32 tekens (blok 0 12-09)."""
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"vgg/{boekstuk}/{bedrag}/{datum}/{omschrijving}")),
        "ReceiptNumber": boekstuk,
        "BaseInvoiceAmount": bedrag,
        "Date": f"{datum}T00:00:00",
        "BookDate": f"{datum}T00:00:00",
        "Entity": {"id": entity[0], "Name": entity[1]} if entity else None,
        "Status": status,
        "Description": omschrijving,
        "Reference": None,
    }


def _btx(bedrag: float, datum: str, reference: str | None, *, open_: bool, tx_id: str, naam: str = "X") -> dict:
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"vgg-tx/{tx_id}")),
        "TransactionId": tx_id,
        "BookDate": f"{datum}T00:00:00",
        "Amount": bedrag,
        "OpenAmount": bedrag if open_ else 0.0,
        "IsComplete": not open_,
        "Name": naam,
        "Reference": reference,
        "CounterAccount": "NL71RABO0360567371",
        "PaymentAccount": {"id": "pa", "Name": "Vastgoedgroep Nederland BV"},
    }


VERHAGEN = (str(uuid.uuid5(uuid.NAMESPACE_URL, "verhagen")), "V.V.B. B.V.")
FULL_HOUSE = (str(uuid.uuid5(uuid.NAMESPACE_URL, "fullhouse")), "F.H.M.")
CONSTEN = (str(uuid.uuid5(uuid.NAMESPACE_URL, "consten")), "C.V. B.V.")
OOSTERDIEPSWAL = "Aanbetaling volgens afspraak: Oo\nsterdiepswal 7 te Kollum"


def _vgg() -> dict[str, list[dict]]:
    """Representatieve nabootsing van de nameting 11-09 (geen 1002 rijen): 5 systeemhulzen (RLZ-09), 7 kopieën,
    4 echte concepten, 3 dubbelen mét bank-tekort, 7 groepen verschillend kenmerk, 4 bank-bevestigde groepen."""
    return {
        "PurchaseInvoices": [
            # kopie over collecties heen (|bedrag|): concept € 65.000 ↔ memoriaal RLZ-06-00000070 € −65.000
            _d("RLZ-04-00000062", 65000.0, "2025-08-22", OOSTERDIEPSWAL, status=1),
            # kopie mét Entity, zelfde collectie
            _d("RLZ-04-00000243", 56.18, "2025-11-10", "25010051 RLZ-04-00000216 1-11-2025", status=1, entity=VERHAGEN),
            _d("RLZ-04-00000244", 56.18, "2025-11-10", "25010051 RLZ-04-00000216 1-11-2025", entity=VERHAGEN),
            _d(
                "RLZ-04-00000338",
                10600.0,
                "2026-01-19",
                "Aanbetaling volgens afspraak Gou\ndreinetgaard 59, Arnhem",
                status=1,
            ),
            _d("RLZ-04-00000339", 10600.0, "2026-01-19", "Aanbetaling volgens afspraak Gou\ndreinetgaard 59, Arnhem"),
            # kopie + derde exemplaar met ander ordernummer → 445/446 verschillend kenmerk
            _d(
                "RLZ-04-00000444",
                7.4,
                "2026-03-03",
                "3774900 8030664778822344 Kadaste\nr webwinkel producten",
                status=1,
            ),
            _d("RLZ-04-00000445", 7.4, "2026-03-03", "3774900 8030664778822344 Kadaste\nr webwinkel producten"),
            _d("RLZ-04-00000446", 7.4, "2026-03-03", "3774961 8030204464031738 Kadaste\nr webwinkel producten"),
            # concept zonder omschrijving, precies één geboekt exemplaar zelfde dag/bedrag/collectie → kopie
            _d("RLZ-04-00000732", 20000.0, "2026-07-06", None, status=1),
            _d("RLZ-04-00000737", 20000.0, "2026-07-06", "Aanbetaling volgens afspraak: Ri\netvelderf 44, Amersfoort"),
            # drie × € 20.000 op 15-08: 845 kopie van 846; 846 vs 847 verschillend adres
            _d(
                "RLZ-04-00000845",
                20000.0,
                "2026-08-15",
                "Aanbetaling volgens afspraak: Ba\nrendrechtstraat 30, Tilburg",
                status=1,
            ),
            _d(
                "RLZ-04-00000846",
                20000.0,
                "2026-08-15",
                "Aanbetaling volgens afspraak: Ba\nrendrechtstraat 30, Tilburg",
            ),
            _d("RLZ-04-00000847", 20000.0, "2026-08-15", "Aanbetaling volgens afspraak: Mu\nizenberglaan 83,Breda"),
            # verschillend factuurnummer
            _d("RLZ-04-00000208", 299.95, "2025-10-27", "2522781", entity=FULL_HOUSE),
            _d("RLZ-04-00000209", 299.95, "2025-10-27", "2522771", entity=FULL_HOUSE),
            # drie adressen (Koraalerf/Heidebeemd-achtig: geen straat-suffix → terugval-adresherkenning)
            _d("RLZ-04-00000162", 749.99, "2025-10-03", "Molenstraat 13", entity=CONSTEN),
            _d("RLZ-04-00000163", 749.99, "2025-10-03", "Dautzenbergstraat 18F", entity=CONSTEN),
            _d("RLZ-04-00000164", 749.99, "2025-10-03", "Koraalerf 45", entity=CONSTEN),
            # zelfde straat, ander huisnummer/toevoeging
            _d("RLZ-04-00000127", 56.18, "2025-09-01", "Fazantstraat 77 en 79", entity=VERHAGEN),
            _d("RLZ-19-00000106", 56.18, "2025-09-01", "Fazantstraat 79a Rotterdam Vve k\nosten", entity=VERHAGEN),
            # RLZ-25 = bank-directe reeks (vaste lasten uit de bank): 312/313 en 177/182 bank-bevestigd, 568 kopie
            _d("RLZ-25-00000312", 415.0, "2025-12-19", "Vaste lasten Gustaaf Gelderstraa\nt 60, Almere"),
            _d("RLZ-25-00000313", 415.0, "2025-12-19", "Vaste lasten Gustaaf Gelderstraa\nt 60, Almere"),
            _d("RLZ-25-00000177", 758.74, "2025-10-04", "Vaste lasten: Schoonegge 98, Rot\nterdam"),
            _d("RLZ-25-00000182", 758.74, "2025-10-04", "Vaste lasten volgens afspraak: S\nchoonegge 98, Rotterdam"),
            _d("RLZ-25-00000568", 230.99, "2026-05-04", "Vaste lasten: Dwartsweg 22, Zeis\nt maand mei", status=1),
            _d("RLZ-25-00000569", 230.99, "2026-05-04", "Vaste lasten: Dwartsweg 22, Zeis\nt maand mei"),
        ],
        "SalesInvoices": [
            _d(
                "RLZ-01-00000006",
                43666.14,
                "2025-08-13",
                "Overdracht Rijswijkseweg 409 te \nDen Haag, ons dossier: 2025.0787\n58.01",
                status=1,
            ),
            # concept mét tekst naast geboekt exemplaar ZONDER tekst → geen kopie (tekst-lookup), wél dubbel-kandidaat
            _d("RLZ-01-00000077", 770.83, "2026-02-25", "Haringvlietstraat 44 Dordrecht R\nente", status=1),
            _d("RLZ-29-00000731", 770.83, "2026-02-25", None),
        ],
        "ManualJournals": [
            _d("RLZ-06-00000070", -65000.0, "2025-08-22", OOSTERDIEPSWAL),
            _d("RLZ-06-00000026", -20000.0, "2025-09-02", "Aanbetaling Kapershoek 34 Rotter\ndam"),
            _d("RLZ-06-00000074", -20000.0, "2025-09-02", "Aanbetaling Rhijnauwensingel 93 \nRotterdam"),
            _d("RLZ-06-00000076", -20000.0, "2025-09-02", "Aanbetaling Heidebeemd 3 Weert"),
            _d("RLZ-06-00000033", 3000.0, "2025-09-10", "Rc"),
            _d("RLZ-06-00000035", 3000.0, "2025-09-10", "Afbetaling RC"),
            _d("RLZ-06-00000057", 185000.0, "2025-10-23", "rc"),
            _d("RLZ-46-00000124", 185000.0, "2025-10-23", "lening volgens afspraak"),
            _d(
                "RLZ-06-00000137",
                1434.0,
                "2026-02-13",
                "TEVEELBET. NR. 868049025L015100 \nLOONH. OKT. 2025 (VASTGOEDGROE)",
            ),
            _d(
                "RLZ-06-00000147",
                1434.0,
                "2026-02-13",
                "TEVEELBET. NR. 868049025L015110 \nLOONH. NOV. 2025 (VASTGOEDGROE)",
            ),
            _d("RLZ-28-00000054", 85.49, "2025-10-20", "Voorschot tanken", status=1),  # bank AFGELETTERD → géén huls
            _d("RLZ-28-00000055", 8000.0, "2025-10-17", "rc"),
            _d("RLZ-28-00000061", 135000.0, "2025-11-07", "rc"),
            _d("RLZ-28-00000062", 135000.0, "2025-11-07", "rc"),
            _d("RLZ-46-00000166", 70000.0, "2026-02-20", "Lening"),
            _d("RLZ-46-00000167", 70000.0, "2026-02-20", "Lening"),
            _d(None, 0.0, "2025-09-24", "Betreft:", status=1),
        ],
        "Receipts": [
            # RLZ-09 = systeemhulzen van open bankmutaties (concept, geen Entity, bedrag+datum = open tx)
            _d("RLZ-09-00000582", -187144.23, "2026-02-21", None, status=1),
            _d("RLZ-09-00001056", 21388.37, "2026-08-03", None, status=1),
            _d("RLZ-09-00001104", -2500.0, "2026-08-21", None, status=1),
            _d("RLZ-09-00001105", -2500.0, "2026-08-21", None, status=1),
            _d("RLZ-09-00001173", -140.0, "2026-09-04", "407683 7R-4729303687348224-NGZMC", status=1),
            _d("RLZ-09-00000900", -973.97, "2026-05-31", None),
            _d("RLZ-09-00000901", 2674.0, "2026-05-26", None),
            _d("RLZ-09-00000902", -67.0, "2026-05-25", None),
        ],
        "PaymentTransactions": [
            _btx(-187144.23, "2026-02-21", "hypotheekgelden dossier 2026.080\n038.01", open_=True, tx_id="00100"),
            _btx(
                21388.37,
                "2026-08-03",
                "Overdracht hogevecht 123 te Amst\nerdam, ons dossier: 2026.080369.\n01",
                open_=True,
                tx_id="00112a",
            ),
            _btx(
                -2500.0, "2026-08-21", "Maandelijkse aanbetaling: Nachte\ngaallaan 47, Goes", open_=True, tx_id="00112b"
            ),
            _btx(
                -2500.0,
                "2026-08-21",
                "Extra aanbetaling volgens afspra\nak: Mgr. Hanssenlaan 38, Hoensbr\noek",
                open_=True,
                tx_id="00112c",
            ),
            _btx(
                -140.0,
                "2026-09-04",
                "MBC6F9CD9K7J3WF38G3AO 7180435016\n407683 7R-4729303687348224-NGZMC\n3MJ9R5",
                open_=True,
                tx_id="00106",
            ),
            _btx(-973.97, "2026-05-31", None, open_=False, tx_id="c1"),
            _btx(2674.0, "2026-05-26", None, open_=False, tx_id="c2"),
            _btx(-67.0, "2026-05-25", None, open_=False, tx_id="c3"),
            _btx(85.49, "2025-10-20", "Voorschot tanken", open_=False, tx_id="c4"),
            _btx(8000.0, "2025-10-17", "rc", open_=False, tx_id="c5"),
            _btx(135000.0, "2025-11-07", "rc", open_=False, tx_id="c6"),
            _btx(135000.0, "2025-11-07", "rc", open_=False, tx_id="c7"),
            _btx(70000.0, "2026-02-20", "Lening", open_=False, tx_id="c8"),
            _btx(70000.0, "2026-02-20", "Lening", open_=False, tx_id="c9"),
            _btx(185000.0, "2025-10-23", "lening", open_=False, tx_id="c10"),  # één tegenover 06-57 + 46-124
            _btx(-415.0, "2025-12-19", "Vaste lasten Gustaaf Gelderstraa\nt 60, Almere", open_=False, tx_id="c11"),
            _btx(-415.0, "2025-12-19", "Vaste lasten Gustaaf Gelderstraa\nt 60, Almere", open_=False, tx_id="c12"),
            _btx(-758.74, "2025-10-04", "Schoonegge 98", open_=False, tx_id="c13"),
            _btx(-758.74, "2025-10-04", "Schoonegge 98", open_=False, tx_id="c14"),
            _btx(-230.99, "2026-05-04", "Dwartsweg 22", open_=False, tx_id="c15"),
            _btx(770.83, "2026-08-31", "Haringvlietstraat 44 Dordrecht R\nente", open_=True, tx_id="00112d"),
        ],
        "PaymentAccounts": [],
    }


def _boekstukken(lijst: Schoonlijst, categorie: str) -> list[str]:
    return sorted(r.boekstuk or "—" for r in lijst.rijen[categorie])


class TestVggNameting:
    """De nameting 11-09 als testcasus: 62 concepten → hulzen + kopieën + echte concepten; 51 dubbelen → kenmerk +
    bank."""

    def test_tellers(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        assert lijst.fouten == []
        assert lijst.tellers == {
            "concepten": 4,
            "systeemhulzen_open_bank": 5,
            "concept_kopie_van_geboekt": 7,
            "dubbelen": 3,
            "zelfde_bedrag_verschillend_kenmerk": 7,
            "bank_bevestigd": 4,
            "open_bankregels": 6,
            "dubbele_iban": 0,
            "zonder_relatie_met_bijlage": 0,
        }
        assert lijst.bank_gelezen is True and lijst.bank_mutaties == 21
        assert lijst.bank_reeksen == {"RLZ-09": (8, 8), "RLZ-25": (6, 5), "RLZ-28": (4, 4), "RLZ-46": (3, 3)}

    def test_omschrijving_ontknipt_niet_meer_gesplitst_op_positie_32(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        alle = {r.boekstuk: r for k in lijst.rijen for r in lijst.rijen[k] if r.boekstuk}
        assert alle["RLZ-04-00000062"].omschrijving == "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum"
        assert alle["RLZ-25-00000312"].omschrijving == "Vaste lasten Gustaaf Gelderstraat 60, Almere"
        assert alle["RLZ-01-00000006"].omschrijving == (
            "Overdracht Rijswijkseweg 409 te Den Haag, ons dossier: 2025.078758.01"
        )
        # bankregel via `ontknip(Reference)`
        bank = {r.boekstuk: r for r in lijst.rijen["open_bankregels"]}
        assert bank["00112a"].omschrijving == "Overdracht hogevecht 123 te Amsterdam, ons dossier: 2026.080369.01"

    def test_systeemhulzen_zijn_de_open_bankmutaties_buiten_de_conceptenteller(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        assert _boekstukken(lijst, "systeemhulzen_open_bank") == [
            "RLZ-09-00000582",
            "RLZ-09-00001056",
            "RLZ-09-00001104",
            "RLZ-09-00001105",
            "RLZ-09-00001173",
        ]
        hulzen = {r.boekstuk: r for r in lijst.rijen["systeemhulzen_open_bank"]}
        # twee × € −2.500 op 21-08 → twee hulzen op twee VERSCHILLENDE mutaties
        assert hulzen["RLZ-09-00001104"].extra["bank_tx_id"] != hulzen["RLZ-09-00001105"].extra["bank_tx_id"]
        # omschrijving ⊂ ontknipte bank-Reference
        assert "verdwijnt bij afletteren" in hulzen["RLZ-09-00001173"].bevinding
        assert "MBC6F9CD9K7J3WF38G3AO" in hulzen["RLZ-09-00001173"].extra["bank_reference"]
        # de concept "Voorschot tanken" heeft een AFGELETTERDE tegenhanger → geen huls, echt concept
        assert "RLZ-28-00000054" in _boekstukken(lijst, "concepten")
        assert not any(r.boekstuk and r.boekstuk.startswith("RLZ-09") for r in lijst.rijen["concepten"])

    def test_kopieen_van_geboekt_verdwijnen_uit_concepten_en_dubbelen(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        assert _boekstukken(lijst, "concept_kopie_van_geboekt") == [
            "RLZ-04-00000062",
            "RLZ-04-00000243",
            "RLZ-04-00000338",
            "RLZ-04-00000444",
            "RLZ-04-00000732",
            "RLZ-04-00000845",
            "RLZ-25-00000568",
        ]
        kopie = {r.boekstuk: r for r in lijst.rijen["concept_kopie_van_geboekt"]}
        assert kopie["RLZ-04-00000062"].bevinding.startswith(
            "niet migreren, kopie van RLZ-06-00000070 (ManualJournals)"
        )
        assert kopie["RLZ-04-00000062"].extra["kopie_van"] == ["RLZ-06-00000070"]
        assert kopie["RLZ-04-00000243"].bevinding.startswith("niet migreren, kopie van RLZ-04-00000244 —")
        assert "omschrijving leeg" in kopie["RLZ-04-00000732"].bevinding
        assert kopie["RLZ-04-00000732"].extra["kopie_van"] == ["RLZ-04-00000737"]
        # echte concepten die blijven
        assert _boekstukken(lijst, "concepten") == ["RLZ-01-00000006", "RLZ-01-00000077", "RLZ-28-00000054", "—"]
        # kopieën en hulzen staan nergens meer als dubbel
        dubbel_ids = {
            r.boekstuk
            for k in ("dubbelen", "zelfde_bedrag_verschillend_kenmerk", "bank_bevestigd")
            for r in lijst.rijen[k]
        }
        assert not dubbel_ids & set(kopie) and not dubbel_ids & set(_boekstukken(lijst, "systeemhulzen_open_bank"))

    def test_verschillend_kenmerk_drie_panden_ordernummers_factuurnummers(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        rijen = lijst.rijen["zelfde_bedrag_verschillend_kenmerk"]
        assert sorted(r.boekstuk for r in rijen) == [
            "RLZ-04-00000127",
            "RLZ-04-00000162",
            "RLZ-04-00000163",
            "RLZ-04-00000164",
            "RLZ-04-00000208",
            "RLZ-04-00000209",
            "RLZ-04-00000445",
            "RLZ-04-00000446",
            "RLZ-04-00000846",
            "RLZ-04-00000847",
            "RLZ-06-00000026",
            "RLZ-06-00000074",
            "RLZ-06-00000076",
            "RLZ-06-00000137",
            "RLZ-06-00000147",
            "RLZ-19-00000106",
        ]
        per = {r.boekstuk: r for r in rijen}
        assert "adres barendrechtstraat-30" in per["RLZ-04-00000846"].bevinding
        assert "zelfde bedrag als RLZ-04-00000846 op 2026-08-15" in per["RLZ-04-00000847"].bevinding
        assert "nr 2522781" in per["RLZ-04-00000208"].bevinding
        assert "nr 3774961/8030204464031738" in per["RLZ-04-00000446"].bevinding
        assert "adres koraalerf-45" in per["RLZ-04-00000164"].bevinding  # terugval zonder straat-suffix
        # 445 + 446 delen de groep (7,40 op 03-03) maar niet het kenmerk → géén 'dubbelen'-rij
        assert not any(r.boekstuk in ("RLZ-04-00000445", "RLZ-04-00000446") for r in lijst.rijen["dubbelen"])

    def test_bank_bevestigd_de_drie_paren_van_peter_en_bank_direct(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        assert _boekstukken(lijst, "bank_bevestigd") == [
            "RLZ-25-00000177",
            "RLZ-25-00000182",
            "RLZ-25-00000312",
            "RLZ-25-00000313",
            "RLZ-28-00000061",
            "RLZ-28-00000062",
            "RLZ-46-00000166",
            "RLZ-46-00000167",
        ]
        per = {r.boekstuk: r for r in lijst.rijen["bank_bevestigd"]}
        assert "bank-directe boekingen (reeks RLZ-25)" in per["RLZ-25-00000312"].bevinding
        assert per["RLZ-28-00000061"].extra["bank_direct"] is True
        assert not {"RLZ-25-00000312", "RLZ-28-00000061", "RLZ-46-00000166"} & set(_boekstukken(lijst, "dubbelen"))

    def test_dubbelen_alleen_bij_bank_tekort_met_n_en_k(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()))
        assert _boekstukken(lijst, "dubbelen") == [
            "RLZ-01-00000077",
            "RLZ-06-00000033",
            "RLZ-06-00000035",
            "RLZ-06-00000057",
            "RLZ-29-00000731",
            "RLZ-46-00000124",
        ]
        per = {r.boekstuk: r for r in lijst.rijen["dubbelen"]}
        assert per["RLZ-06-00000057"].bevinding == (
            "2× € 185000.00 op 2025-10-23: RLZ-06-00000057, RLZ-46-00000124 — 2 boekingen, 1 bankmutaties (±3 d)"
        )
        assert per["RLZ-06-00000033"].bevinding.endswith("— 2 boekingen, 0 bankmutaties (±3 d)")
        assert per["RLZ-01-00000077"].bevinding.endswith("(concept) — 2 boekingen, 0 bankmutaties (±3 d)")
        assert (
            per["RLZ-06-00000057"].extra["bank_mutaties"] == 1 and per["RLZ-06-00000057"].extra["bank_boekingen"] == 2
        )

    def test_markdown_ingeklapte_tabellen_en_bankkop(self) -> None:
        lijst = maak_schoonlijst(NepClient(_vgg()), verwacht={"systeemhulzen_open_bank": 5, "concepten": 4})
        md = als_markdown(lijst, administratie_naam="VGG")
        assert "| Systeemhulzen open bank (concept-huls per open bankmutatie) | 5 | 5 | gelijk |" in md
        assert "| Concepten in RLZ (Status 1) | 4 | 4 | gelijk |" in md
        assert "Bank leidend: 21 bankmutaties gelezen; bank-directe reeksen" in md
        assert "RLZ-25 (5/6)" in md and "RLZ-09 (8/8)" in md
        for titel in (
            "Zelfde bedrag, verschillend kenmerk — 7",
            "Bank-bevestigd (evenveel of meer bankmutaties dan boekingen) — 4",
        ):
            assert f"<details><summary>{titel}</summary>\n\n| Boekstuk |" in md
        assert md.count("</details>") == 3
        assert "#### Vermoedelijke dubbelen (zelfde collectie, bedrag, datum, relatie; bank-tekort) — 3" in md
        assert "BANK NIET GELEZEN" not in md

    def test_json_stabiel_met_nieuwe_categorieen(self) -> None:
        a, b = (json.loads(maak_schoonlijst(NepClient(_vgg())).als_json()) for _ in range(2))
        a.pop("gegenereerd_op"), b.pop("gegenereerd_op")
        assert a == b
        assert set(a["categorieen"]) == {k for k, _ in schoonlijst.CATEGORIEEN}
        assert a["bank"]["reeksen"]["RLZ-25"] == [6, 5]


class TestBankLeidendGuards:
    """CONTRACT_RUN2 §Tests A: gelijk → niet gemeld; minder → gemeld; niet gelezen → gemeld mét markering;
    bank-directe reeks → nooit dubbel."""

    def _twee(self, *, entity: tuple[str, str] | None = FULL_HOUSE) -> dict[str, list[dict]]:
        data = _basis()
        data["PurchaseInvoices"] = [
            _d("RLZ-04-00000500", 1595.0, "2026-03-24", "Kerkstraat 44", entity=entity),
            _d("RLZ-04-00000501", 1595.0, "2026-03-24", "Kerkstraat 44", entity=entity),
        ]
        return data

    def test_evenveel_bankmutaties_niet_gemeld_wel_geteld(self) -> None:
        data = self._twee()
        data["PaymentTransactions"] = [
            _btx(-1595.0, "2026-03-25", "FH", open_=False, tx_id="a"),
            _btx(-1595.0, "2026-03-27", "FH", open_=False, tx_id="b"),  # +3 dagen: binnen het venster
        ]
        lijst = maak_schoonlijst(NepClient(data))
        assert lijst.tellers["dubbelen"] == 0 and lijst.tellers["bank_bevestigd"] == 1
        assert all("bank-bevestigd: 2 boekingen, 2 bankmutaties" in r.bevinding for r in lijst.rijen["bank_bevestigd"])

    def test_minder_bankmutaties_gemeld_met_n_en_k(self) -> None:
        data = self._twee()
        data["PaymentTransactions"] = [
            _btx(-1595.0, "2026-03-25", "FH", open_=False, tx_id="a"),
            _btx(-1595.0, "2026-03-28", "FH", open_=False, tx_id="te-laat"),  # +4 dagen: buiten het venster
            _btx(1595.0, "2026-03-24", "FH", open_=False, tx_id="verkeerd-teken"),
        ]
        lijst = maak_schoonlijst(NepClient(data))
        assert lijst.tellers["dubbelen"] == 1 and lijst.tellers["bank_bevestigd"] == 0
        assert all(r.bevinding.endswith("— 2 boekingen, 1 bankmutaties (±3 d)") for r in lijst.rijen["dubbelen"])

    def test_bank_niet_gelezen_alles_gemeld_met_markering_en_geen_hulzen(self) -> None:
        data = _vgg()
        client = NepClient(
            data, fouten={"PaymentTransactions": RlzApiError(403, "GET", "PaymentTransactions", "Forbidden")}
        )
        lijst = maak_schoonlijst(client)
        assert [(f.route, f.status) for f in lijst.fouten] == [("PaymentTransactions", 403)]
        assert lijst.bank_gelezen is False and lijst.bank_reeksen == {}
        assert lijst.tellers["systeemhulzen_open_bank"] == 0  # hulzen niet herkenbaar zonder bank
        assert lijst.tellers["concepten"] == 4 + 5  # de RLZ-09-hulzen staan nu zichtbaar als concept
        # alleen Receipts blijft per definitie bank-direct (het paar RLZ-09-00001104/1105 is nu geen huls meer)
        assert lijst.tellers["bank_bevestigd"] == 1
        assert all(
            "bank-directe boekingen (reeks RLZ-09)" in r.bevinding and r.extra["bank_gelezen"] is False
            for r in lijst.rijen["bank_bevestigd"]
        )
        # niets gefilterd: 25-312/313, 28-61/62, 46-166/167 staan nu WEL als dubbel — gemarkeerd
        dubbel = {r.boekstuk: r for r in lijst.rijen["dubbelen"]}
        assert {"RLZ-25-00000312", "RLZ-28-00000061", "RLZ-46-00000166", "RLZ-06-00000057"} <= set(dubbel)
        assert all(r.bevinding.endswith("— BANK NIET GELEZEN — niet gefilterd") for r in dubbel.values())
        assert all(r.extra["bank_gelezen"] is False for r in dubbel.values())
        md = als_markdown(lijst)
        assert "**BANK NIET GELEZEN**" in md and "| PaymentTransactions | 403 |" in md
        # kenmerk-poort werkt onafhankelijk van de bank
        assert lijst.tellers["zelfde_bedrag_verschillend_kenmerk"] == 7

    def test_reeks_onder_de_dekkingsgrens_wordt_niet_afgeleid_gewone_bankdekking(self) -> None:
        """3 van 4 Entity-loze documenten op de bank = 0,75 < 0,8 → géén bankdagboek-reeks; het paar 205/206 valt
        dan onder de gewone dekking (1 mutatie voor 2 boekingen) en wordt gemeld."""
        data = _basis()
        data["PurchaseInvoices"] = [
            _d("RLZ-25-00000177", 758.74, "2025-10-04", "Vaste lasten Schoonegge 98"),
            _d("RLZ-25-00000205", 500.0, "2025-10-30", "Vaste lasten Molenstraat 13"),
            _d("RLZ-25-00000206", 500.0, "2025-10-30", "Vaste lasten Molenstraat 13"),
            _d("RLZ-25-00000739", 1000.0, "2026-07-07", "Vaste lasten Papaverstraat 44"),
        ]
        data["PaymentTransactions"] = [
            _btx(-758.74, "2025-10-04", None, open_=False, tx_id="1"),
            _btx(-500.0, "2025-10-30", None, open_=False, tx_id="2"),
            _btx(-1000.0, "2026-07-07", None, open_=False, tx_id="3"),
        ]
        lijst = maak_schoonlijst(NepClient(data))
        assert lijst.bank_reeksen == {}
        assert lijst.tellers["bank_bevestigd"] == 0 and lijst.tellers["dubbelen"] == 1
        assert all(r.bevinding.endswith("— 2 boekingen, 1 bankmutaties (±3 d)") for r in lijst.rijen["dubbelen"])

    def test_bank_directe_reeks_afgeleid_en_receipts_per_definitie(self) -> None:
        data = _basis()
        data["PurchaseInvoices"] = [
            _d("RLZ-25-00000177", 758.74, "2025-10-04", "Vaste lasten Schoonegge 98"),
            _d("RLZ-25-00000205", 500.0, "2025-10-30", "Vaste lasten Molenstraat 13"),
            _d("RLZ-25-00000206", 500.0, "2025-10-30", "Vaste lasten Molenstraat 13"),
            _d("RLZ-25-00000739", 1000.0, "2026-07-07", "Vaste lasten Papaverstraat 44"),
            _d("RLZ-25-00000740", 1000.0, "2026-07-07", "Vaste lasten Papaverstraat 44"),
        ]
        data["Receipts"] = [
            _d("RLZ-09-00000001", -9.0, "2026-01-01", "x"),
            _d("RLZ-09-00000002", -9.0, "2026-01-01", "x"),
        ]
        data["PaymentTransactions"] = [
            _btx(-758.74, "2025-10-04", None, open_=False, tx_id="1"),
            _btx(-500.0, "2025-10-30", None, open_=False, tx_id="2"),
            _btx(-1000.0, "2026-07-07", None, open_=False, tx_id="3"),
            _btx(-1000.0, "2026-07-07", None, open_=False, tx_id="4"),
        ]
        lijst = maak_schoonlijst(NepClient(data))
        assert lijst.bank_reeksen == {"RLZ-25": (5, 4)}
        assert lijst.tellers["dubbelen"] == 0 and lijst.tellers["bank_bevestigd"] == 3
        per = {r.boekstuk: r for r in lijst.rijen["bank_bevestigd"]}
        assert "bank-directe boekingen (reeks RLZ-25)" in per["RLZ-25-00000205"].bevinding  # 1 mutatie, toch echt
        assert "bank-directe boekingen (reeks RLZ-09)" in per["RLZ-09-00000001"].bevinding  # Receipts, geen bank nodig


class TestKenmerk:
    @pytest.mark.parametrize(
        ("a", "b", "conflict"),
        [
            ("Aanbetaling Kapershoek 34 Rotterdam", "Aanbetaling Rhijnauwensingel 93 Rotterdam", True),
            ("Aanbetaling Heidebeemd 3 Weert", "Aanbetaling Kapershoek 34 Rotterdam", True),
            ("2522781", "2522771", True),
            ("Fazantstraat 77 en 79", "Fazantstraat 79a Rotterdam Vve kosten", True),
            ("Kouvenderstraat34b Hoensbroek", "Groningenstraat 203 leeuwarden", True),
            (
                "TEVEELBET. NR. 868049025L015100 LOONH. OKT. 2025",
                "TEVEELBET. NR. 868049025L015110 LOONH. NOV. 2025",
                True,
            ),
            (
                "Vaste lasten: Schoonegge 98, Rotterdam",
                "Vaste lasten volgens afspraak: Schoonegge 98, Rotterdam",
                False,
            ),
            ("Rc", "Afbetaling RC", False),
            ("rc", "lening volgens afspraak", False),
            (None, "Aanbetaling volgens afspraak: Rietvelderf 44, Amersfoort", False),
            ("maart 2026", "maart 2026", False),  # jaartal is geen kenmerk
            ("Dossiernummer: 118261", "Dossiernummer: 118261", False),
            ("Dossiernummer: 118261", "Dossiernummer: 118262", True),
        ],
    )
    def test_conflict(self, a: str | None, b: str | None, conflict: bool) -> None:
        assert schoonlijst.kenmerk_van(a).conflicteert_met(schoonlijst.kenmerk_van(b)) is conflict

    def test_terugval_adres_zonder_straat_suffix_en_jaartal_niet(self) -> None:
        assert schoonlijst._adres_codes_terugval("Aanbetaling Heidebeemd 3 Weert") == {"heidebeemd-3"}
        assert schoonlijst._adres_codes_terugval("Koraalerf 45 - Heerlen") == {"koraalerf-45"}
        assert schoonlijst._adres_codes_terugval("Klinkenbergerweg 84D Ede") == {"klinkenbergerweg-84-d"}
        assert schoonlijst._adres_codes_terugval("25010051 RLZ-04-00000216 1-11-2025") == set()
        assert schoonlijst._adres_codes_terugval("Maandelijkse aanbetaling: maand mei 2026") == set()

    def test_normaliseer_omschrijving(self) -> None:
        assert schoonlijst.normaliseer_omschrijving("Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum") == (
            "aanbetalingvolgensafspraakoosterdiepswal7tekollum"
        )
        assert schoonlijst.normaliseer_omschrijving("  ") is None and schoonlijst.normaliseer_omschrijving(None) is None
