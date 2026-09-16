"""RLZ-/Odoo-bestaanscheck genormaliseerd (Peter 16-09, Zenvoices-casus Hello Kitchen / Kempen Facilities) — pure
motor `app/documenten/extern_bestaan.py` + de RLZ-client-filtervorm."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.documenten import extern_bestaan as eb
from app.rlz.client import RlzClient
from tests.documenten.fake_rlz_client import FakeBoekClient

VENDOR = uuid.UUID("5fda3d7d-0000-4000-8000-000000000001")
VENDOR_DUBBEL = uuid.UUID("7b4b3ed8-0000-4000-8000-000000000002")


def _rij(ref: str | None, bedrag: float, datum: str, *, status: int = 3, entity: uuid.UUID | None = None, **extra):
    return {
        "id": str(uuid.uuid4()),
        "Reference": ref,
        "BaseInvoiceAmount": bedrag,
        "Date": f"{datum}T00:00:00",
        "Status": status,
        "ReceiptNumber": extra.pop("boekstuk", "RLZ-04-00004314"),
        "Entity": {"id": str(entity or VENDOR), "Name": "H.K.D.B."},
        **extra,
    }


def _zoek(client, **kw):
    basis = dict(
        vendor_ids=[VENDOR],
        referentie="2 4594 001722",
        totaalbedrag=Decimal("12600.00"),
        factuurdatum=date(2026, 8, 10),
    )
    basis.update(kw)
    return eb.zoek_extern_bestaand(client, **basis)


class TestZenvoicesCasus:
    def test_spaties_in_onze_referentie_vinden_het_zenvoices_exemplaar(self) -> None:
        """De letterlijke `Reference eq '2 4594 001722'` treft niets; de kandidaten in het datumvenster wél."""
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001722", 12600.0, "2026-08-10")]
        (treffer,) = _zoek(client)
        assert treffer["match_basis"] == eb.BASIS_REFERENTIE
        assert treffer["ReceiptNumber"] == "RLZ-04-00004314"

    def test_concept_telt_mee(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001722", 12600.0, "2026-08-10", status=1)]
        (treffer,) = _zoek(client)
        assert treffer["match_basis"] == eb.BASIS_REFERENTIE and eb.status_van(treffer) == 1

    def test_dubbel_crediteurrecord_zelfde_identiteit(self) -> None:
        """Blok B (b): het exemplaar staat op een ánder crediteurrecord van dezelfde identiteit (KvK/btw)."""
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001722", 12600.0, "2026-08-10", entity=VENDOR_DUBBEL)]
        assert _zoek(client) == []  # alleen het eigen record → onzichtbaar (dát was de bug-familie)
        (treffer,) = _zoek(client, vendor_ids=[VENDOR, VENDOR_DUBBEL])
        assert treffer["match_basis"] == eb.BASIS_REFERENTIE

    def test_zelfde_referentie_ander_bedrag_is_blokkerende_basis_geen_harde(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001722", 12000.0, "2026-08-10")]
        (treffer,) = _zoek(client)
        assert treffer["match_basis"] == eb.BASIS_REFERENTIE_ANDER_BEDRAG
        assert treffer["match_basis"] in eb.BLOKKERENDE_BASES and treffer["match_basis"] not in eb.HARDE_BASES

    def test_zelfde_bedrag_en_datum_ander_nummer_is_signaal(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001799", 12600.0, "2026-08-20")]
        (treffer,) = _zoek(client)
        assert treffer["match_basis"] == eb.BASIS_BEDRAG_DATUM
        assert treffer["match_basis"] not in eb.BLOKKERENDE_BASES

    def test_zelfde_bedrag_buiten_dertig_dagen_is_geen_treffer(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001799", 12600.0, "2026-09-25")]
        assert _zoek(client) == []

    def test_eigen_keten_telt_nooit_mee_en_dedup_op_id(self) -> None:
        client = FakeBoekClient()
        eigen = _rij("24594001722", 12600.0, "2026-08-10")
        client.duplicaten = [eigen]
        client.kandidaten = [eigen]
        assert _zoek(client, uitgezonderd_ids=[eigen["id"]]) == []
        assert len(_zoek(client)) == 1

    def test_exacte_route_zonder_reference_veld_blijft_een_treffer(self) -> None:
        """Server-side `Reference eq` is gezaghebbend — een rij zonder Reference-veld (oude fakes, kale antwoorden)
        wordt niet weggenormaliseerd."""
        client = FakeBoekClient(duplicaten=[{"id": str(uuid.uuid4())}])
        (treffer,) = _zoek(client, factuurdatum=None)
        assert treffer["match_basis"] == eb.BASIS_REFERENTIE

    def test_zonder_factuurdatum_alleen_de_exacte_route(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [_rij("24594001722", 12600.0, "2026-08-10")]
        assert _zoek(client, factuurdatum=None) == []

    def test_volgorde_hard_dan_blokkerend_dan_signaal_geboekt_voor_concept(self) -> None:
        client = FakeBoekClient()
        client.kandidaten = [
            _rij("24594001799", 12600.0, "2026-08-12"),
            _rij("24594001722", 12600.0, "2026-08-10", status=1),
            _rij("24594001722", 12600.0, "2026-08-10", status=3),
            _rij("24594001722", 12000.0, "2026-08-10"),
        ]
        bases = [(t["match_basis"], eb.status_van(t)) for t in _zoek(client)]
        assert bases == [
            (eb.BASIS_REFERENTIE, 3),
            (eb.BASIS_REFERENTIE, 1),
            (eb.BASIS_REFERENTIE_ANDER_BEDRAG, 3),
            (eb.BASIS_BEDRAG_DATUM, 3),
        ]


class TestOmschrijving:
    def test_mensentaal_met_boekstuk_en_referentie(self) -> None:
        rij = {**_rij("24594001722", 12600.0, "2026-08-10"), "match_basis": eb.BASIS_REFERENTIE}
        assert eb.omschrijf_treffer(rij) == (
            "al geboekt in Reeleezee: RLZ-04-00004314 (referentie 24594001722, buiten de module)"
        )
        concept = {**_rij("24594001722", 12600.0, "2026-08-10", status=1), "match_basis": eb.BASIS_REFERENTIE}
        assert eb.omschrijf_treffer(concept).startswith("als concept aanwezig in Reeleezee: RLZ-04-00004314")


class TestRlzClientFilter:
    def test_kandidatenfilter_over_identiteit_en_datumvenster(self, monkeypatch) -> None:
        client = RlzClient(username="u", password="p", admin_id="a")
        aanroepen: list[dict] = []

        def _get(path, *, params=None):
            aanroepen.append({"path": path, **(params or {})})
            return {"value": [{"id": "x"}]}

        monkeypatch.setattr(client, "get", _get)
        rijen = client.find_purchase_invoices_kandidaten(
            vendor_ids=[VENDOR, VENDOR_DUBBEL], van=date(2026, 6, 11), tot=date(2026, 10, 9)
        )
        assert rijen == [{"id": "x"}]
        (call,) = aanroepen
        assert call["path"] == "PurchaseInvoices"
        assert call["$filter"] == (
            f"(Entity/id eq {VENDOR} or Entity/id eq {VENDOR_DUBBEL}) and Date ge 2026-06-11 and Date le 2026-10-09"
        )
        assert call["$expand"] == "Entity" and call["$top"] == "200" and call["$skip"] == "0"

    def test_pagineert_tot_de_laatste_halve_pagina(self, monkeypatch) -> None:
        client = RlzClient(username="u", password="p", admin_id="a")
        paginas = iter([[{"id": str(i)} for i in range(200)], [{"id": "laatste"}]])
        monkeypatch.setattr(client, "get", lambda path, *, params=None: {"value": next(paginas)})
        rijen = client.find_purchase_invoices_kandidaten(
            vendor_ids=[VENDOR], van=date(2026, 1, 1), tot=date(2026, 2, 1)
        )
        assert len(rijen) == 201

    def test_zonder_crediteur_geen_call(self, monkeypatch) -> None:
        client = RlzClient(username="u", password="p", admin_id="a")
        monkeypatch.setattr(client, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("geen call")))
        assert client.find_purchase_invoices_kandidaten(vendor_ids=[], van=date(2026, 1, 1), tot=date(2026, 2, 1)) == []
