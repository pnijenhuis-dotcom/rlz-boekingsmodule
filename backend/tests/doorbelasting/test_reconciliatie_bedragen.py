# ruff: noqa: F811 — pytest-fixtures als parameters
"""Doorbelasting-reconciliatieblok ná 24-09 (RLZ-vorm): bedragtoets module ↔ RLZ (verkoop én spiegel) en de bevinding
`doorbelasting_factuur_pdf_ontbreekt` (> 1 dag zonder factuur-PDF) — plus de leesbare teksten en de registry-stand."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db.session import scoped_session
from app.doorbelasting import reconciliatie
from app.doorbelasting.models import DoorbelastingBoeking
from app.doorbelasting.reconciliatie import RlzBedragen, toets_bedragen
from app.reconciliatie import soort_stand, teksten
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.doorbelasting.conftest import (  # noqa: F401
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    haal_boekingen,
    onboarded_opzet,
)
from tests.doorbelasting.test_boeken import _boek

D = Decimal


class TestToetsBedragen:
    def test_gelijk_en_niet_toetsbaar(self) -> None:
        v = RlzBedragen(incl=D("6024.14"), btw=D("1045.51"), netto=D("4978.63"))
        assert toets_bedragen(ons_incl=D("6024.14"), ons_btw=D("1045.51"), verkoop=v, spiegel=v) == (None, "gelijk aan RLZ")
        assert toets_bedragen(ons_incl=D("1"), ons_btw=D("0"), verkoop=None, spiegel=None)[0] is None

    def test_lusso_is_een_centverschil_geen_afwijking(self) -> None:
        v = RlzBedragen(incl=D("6024.14"), btw=D("1045.51"), netto=D("4978.63"))
        uitkomst, detail = toets_bedragen(ons_incl=D("6024.15"), ons_btw=D("1045.52"), verkoop=v, spiegel=v)
        assert uitkomst == "centverschil" and "0.01" in detail

    def test_meer_dan_tolerantie_of_verkoop_ongelijk_spiegel_is_afwijking(self) -> None:
        v = RlzBedragen(incl=D("6024.14"), btw=D("1045.51"), netto=D("4978.63"))
        assert toets_bedragen(ons_incl=D("6024.20"), ons_btw=D("1045.57"), verkoop=v, spiegel=v)[0] == "afwijking"
        s = RlzBedragen(incl=D("6024.15"), btw=D("1045.52"), netto=D("4978.63"))
        uitkomst, detail = toets_bedragen(ons_incl=D("6024.14"), ons_btw=D("1045.51"), verkoop=v, spiegel=s)
        assert uitkomst == "afwijking" and "verkoop en spiegel verschillen" in detail

    def test_alleen_verkoop_spiegel_open(self) -> None:
        v = RlzBedragen(incl=D("127.05"), btw=D("22.05"), netto=D("105.00"))
        assert toets_bedragen(ons_incl=D("127.06"), ons_btw=D("22.06"), verkoop=v, spiegel=None)[0] == "centverschil"


class _Rlz:
    """Fake voor client_voor_rlz_admin_id: per pad/guid een document-dict (Status + totalen) of een 404."""

    def __init__(self, docs: dict[str, dict]) -> None:
        self.docs = docs

    def for_administration(self, admin_id: str) -> _Rlz:
        return self

    def __enter__(self) -> _Rlz:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, pad: str) -> dict:
        if pad not in self.docs:
            raise RlzApiError(404, "GET", pad, "not found")
        return self.docs[pad]


def _doc(incl: str, btw: str, netto: str, status: int = 2) -> dict:
    return {"Status": status, "TotalPayableAmount": float(incl), "TotalTaxAmount": float(btw), "TotalNetAmount": float(netto), "ReceiptNumber": "RLZ-01-1"}


def _geboekt(opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> DoorbelastingBoeking:
    _boek(opzet, beheerder_id, bron=FakeDoorbelastingClient(), doel=FakeDoorbelastingClient())
    return haal_boekingen(opzet.administratie_id, opzet.run.id)[0]


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _Rlz) -> None:
    monkeypatch.setattr(reconciliatie, "rlz_admin_id_voor", lambda aid: str(aid))
    monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", lambda rid: fake)


class TestBlokDoorbelasting:
    def test_gelijk_geen_bevinding_geen_teller(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _geboekt(onboarded_opzet, beheerder_id)
        fake = _Rlz({f"SalesInvoices/{b.verkoop_rlz_id}": _doc("127.05", "22.05", "105.00"), f"PurchaseInvoices/{b.spiegel_rlz_id}": _doc("127.05", "22.05", "105.00")})
        _patch(monkeypatch, fake)
        afw, cent = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert afw == [] and cent == 0

    def test_centverschil_telt_maar_is_geen_bevinding(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _geboekt(onboarded_opzet, beheerder_id)
        with scoped_session(onboarded_opzet.administratie_id, actor_id=beheerder_id) as session:
            session.get(DoorbelastingBoeking, b.id).btw_bedrag = D("22.06")  # legacy per-regel-registratie
        fake = _Rlz({f"SalesInvoices/{b.verkoop_rlz_id}": _doc("127.05", "22.05", "105.00"), f"PurchaseInvoices/{b.spiegel_rlz_id}": _doc("127.05", "22.05", "105.00")})
        _patch(monkeypatch, fake)
        afw, cent = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert afw == [] and cent == 1
        alles = reconciliatie.reconcilieer_alle_doorbelasting()
        assert alles.centverschillen.get(onboarded_opzet.administratie_id) == 1 and alles.afwijkingen == []

    def test_groot_verschil_is_actie_bevinding_met_rlz_bedragen(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _geboekt(onboarded_opzet, beheerder_id)
        fake = _Rlz({f"SalesInvoices/{b.verkoop_rlz_id}": _doc("130.00", "25.00", "105.00"), f"PurchaseInvoices/{b.spiegel_rlz_id}": _doc("130.00", "25.00", "105.00")})
        _patch(monkeypatch, fake)
        afw, cent = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert cent == 0 and [a.soort for a in afw] == [reconciliatie.SOORT_BEDRAG_AFWIJKING]
        a = afw[0]
        assert a.extra == {"rlz_verkoop_incl": "130.00", "rlz_spiegel_incl": "130.00"} and "2.95" in a.detail
        assert soort_stand.code_default(reconciliatie.SOORT_BEDRAG_AFWIJKING) == soort_stand.ACTIE
        # leesbare tekst mét beide RLZ-bedragen
        lb = teksten.leesbaar(
            type("B", (), {"blok": "doorbelasting", "soort": "afwijking", "tekst": "AFWIJKING x", "vingerafdruk": "v",
                            "detail": {"afwijking_soort": a.soort, "detail": a.detail, "doelentiteit_naam": "Veldhoven Recreatie B.V.", "bedrag_lokaal": "127.05", **a.extra}})()
        )
        assert lb.titel.startswith("Doorbelasting: bedrag wijkt af van RLZ") and "€ 130,00" in lb.wat and "storno" in lb.doe

    def test_verkoop_ongelijk_spiegel_is_afwijking(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _geboekt(onboarded_opzet, beheerder_id)
        fake = _Rlz({f"SalesInvoices/{b.verkoop_rlz_id}": _doc("127.05", "22.05", "105.00"), f"PurchaseInvoices/{b.spiegel_rlz_id}": _doc("127.06", "22.06", "105.00")})
        _patch(monkeypatch, fake)
        afw, _ = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert [a.soort for a in afw] == [reconciliatie.SOORT_BEDRAG_AFWIJKING] and "verkoop en spiegel verschillen" in afw[0].detail

    def test_factuur_pdf_ontbreekt_ouder_dan_een_dag(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, admin_engine) -> None:  # noqa: ANN001
        b = _geboekt(onboarded_opzet, beheerder_id)
        fake = _Rlz({f"SalesInvoices/{b.verkoop_rlz_id}": _doc("127.05", "22.05", "105.00"), f"PurchaseInvoices/{b.spiegel_rlz_id}": _doc("127.05", "22.05", "105.00")})
        _patch(monkeypatch, fake)
        with scoped_session(onboarded_opzet.administratie_id, actor_id=beheerder_id) as session:
            rij = session.get(DoorbelastingBoeking, b.id)
            rij.factuur_pdf_status = "ontbreekt"
            rij.factuur_pdf_reden = "factuur-PDF onvolledig: btw-som € 22,06 — de RLZ-factuur toont andere centen …"
        # vers (< 1 dag): nog geen bevinding — de motor/herstel kan 'm nog oppakken
        afw, _ = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert afw == []
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.doorbelasting_boeking SET aangemaakt_op = :t WHERE id = :id"), {"t": datetime.now(UTC) - timedelta(days=2), "id": b.id})
        afw, _ = reconciliatie.reconcilieer_doorbelasting_met_tellers(onboarded_opzet.administratie_id)
        assert [a.soort for a in afw] == [reconciliatie.SOORT_FACTUUR_PDF_ONTBREEKT]
        assert afw[0].extra["factuur_pdf_reden"].startswith("factuur-PDF onvolledig")
        assert soort_stand.code_default(reconciliatie.SOORT_FACTUUR_PDF_ONTBREEKT) == soort_stand.METEN
        lb = teksten.leesbaar(
            type("B", (), {"blok": "doorbelasting", "soort": "afwijking", "tekst": "AFWIJKING x", "vingerafdruk": "v",
                            "detail": {"afwijking_soort": afw[0].soort, "detail": afw[0].detail, "doelentiteit_naam": "Veldhoven Recreatie B.V.", **afw[0].extra}})()
        )
        assert lb.titel.startswith("Doorbelasting zonder factuur-PDF") and "Factuur-PDF herstellen" in lb.doe
