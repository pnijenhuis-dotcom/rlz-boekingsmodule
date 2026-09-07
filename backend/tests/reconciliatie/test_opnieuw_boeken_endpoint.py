# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""`POST /reconciliatie/bevindingen/{id}/opnieuw-boeken` (A11, 07-09): kantoorrol binnen scope, alleen op een
documenten-afwijking `ontbreekt_in_*`, poort via de adapter (backend kent het stuk niet meer), 200 mét status +
boek_cyclus + doel_pad; 403 buiten scope; 409 als het stuk nog bestaat; 422 op een andere afwijkingssoort;
404 op een onbekende bevinding."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.backends.rlz_inkoop import RlzInkoopPort
from app.beheer import service as beheer_service
from app.berichten import mail
from app.documenten import boeken, boekvoorstel, herboeken, service
from app.documenten.rlz_ids import rlz_herboeking_id
from app.main import app
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)
REDEN = "document op 16-08 per abuis in de RLZ-UI verwijderd (kliktest-erfenis)"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _geen_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: None)


@pytest.fixture
def geboekt(gescoopte_gebruiker, administratie_id, beheerder_id, opslag, monkeypatch) -> tuple[uuid.UUID, FakeBoekClient]:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    r = service.upload_document(
        administratie_id=administratie_id, bestandsnaam="f.pdf", inhoud=b"%PDF-1.4 x", actor_id=gescoopte_gebruiker, opslag=opslag
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=r.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie="202632704",
        factuurdatum=date(2026, 6, 22),
        totaalbedrag=Decimal("121.00"),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), project_id=None,
                netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"), omschrijving=None,
            )
        ],
    )
    fake = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    boeken.boek_document(administratie_id=administratie_id, document_id=r.document_id, actor_id=gescoopte_gebruiker)
    # De router-service opent zijn eigen port: laat die op dezelfde fake wijzen.
    monkeypatch.setattr(herboeken, "_port_voor", lambda aid: RlzInkoopPort(fake))
    return r.document_id, fake


def _run_met(aid: uuid.UUID, document_id: uuid.UUID, soort: str, detail: str) -> None:
    def blok(args, verzamelaar=None) -> int:  # noqa: ANN001
        [b] = acceptatie_service.beoordeel(bron="documenten", administratie_id=aid, afwijkingen=[(document_id, soort, detail)])
        verzamelaar.bevinding(
            soort="afwijking",
            administratie_id=aid,
            vingerafdruk=b.vingerafdruk,
            tekst=f"document={document_id} soort={soort} [vaf:{b.vingerafdruk}]: {detail}",
            detail={
                "bron": "documenten",
                "record_id": str(document_id),
                "afwijking_soort": soort,
                "detail": detail,
                "geaccepteerd": False,
                "document_id": str(document_id),
                "leverancier_naam": "BOOT organiserend ingenieursburo B.V.",
                "factuurnummer": "202632704",
                "backend": "rlz",
            },
        )
        return 1

    run_service.voer_uit(blokken=[("documenten", blok)], args=argparse.Namespace(), bron="cli", stdout=lambda t: None)


def _bevinding_id(headers: dict[str, str]) -> str:
    d = client.get("/reconciliatie/bevindingen", headers=headers).json()
    [rij] = d["rijen"]
    return rij["id"]


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}).scalar_one()


class TestOpnieuwBoekenEndpoint:
    def test_kantoorrol_binnen_scope_zet_document_terug(self, geboekt, administratie_id, gescoopte_gebruiker, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]  # verwijderd in de RLZ-UI
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "GET PurchaseInvoices/x -> 404: NotFound")
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        bid = _bevinding_id(h)
        # te korte reden → 422 (service-poort)
        r = client.post(f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken", json={"administratie_id": str(administratie_id), "reden": "ok"}, headers=h)
        assert r.status_code == 422
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken",
            json={"administratie_id": str(administratie_id), "reden": REDEN},
            headers=h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["document_id"] == str(document_id) and d["status"] == "klaar_om_te_boeken" and d["boek_cyclus"] == 1
        assert d["doel_pad"] == f"/?administratie={administratie_id}&document={document_id}"
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        # tweede keer: het document is niet meer geboekt → 422, niets dubbel
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken",
            json={"administratie_id": str(administratie_id), "reden": REDEN},
            headers=h,
        )
        assert r.status_code == 422 and "alleen een geboekt document" in r.json()["detail"]

    def test_bestaat_nog_409_en_andere_soort_422_en_onbekend_404(self, geboekt, administratie_id, beheerder_id) -> None:
        document_id, _fake = geboekt
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "GET PurchaseInvoices/x -> 404: NotFound")
        h = _bearer(beheerder_id, rol="beheerder")
        bid = _bevinding_id(h)
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken", json={"administratie_id": str(administratie_id), "reden": REDEN}, headers=h
        )
        assert r.status_code == 409 and "bestaat nog" in r.json()["detail"]
        _run_met(administratie_id, document_id, "bedrag_wijkt_af", "eigen=€121.00 rlz=€120.00")
        bid2 = _bevinding_id(h)
        r = client.post(
            f"/reconciliatie/bevindingen/{bid2}/opnieuw-boeken", json={"administratie_id": str(administratie_id), "reden": REDEN}, headers=h
        )
        assert r.status_code == 422 and "verdwenen" in r.json()["detail"]
        r = client.post(
            f"/reconciliatie/bevindingen/{uuid.uuid4()}/opnieuw-boeken", json={"administratie_id": str(administratie_id), "reden": REDEN}, headers=h
        )
        assert r.status_code == 404

    def test_buiten_scope_403_en_accordeur_403(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        bid = _bevinding_id(_bearer(beheerder_id, rol="beheerder"))
        buiten = maak_gebruiker(admin_engine, "boekhouding", "Buiten scope")  # geen scope-rij
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken",
            json={"administratie_id": str(administratie_id), "reden": REDEN},
            headers=_bearer(buiten, rol="boekhouding"),
        )
        assert r.status_code == 403
        accordeur = maak_gebruiker(admin_engine, "klant_accordeur", "Accordeur")
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/opnieuw-boeken",
            json={"administratie_id": str(administratie_id), "reden": REDEN},
            headers=_bearer(accordeur, rol="klant_accordeur"),
        )
        assert r.status_code == 403
        assert _status(admin_engine, document_id) == "geboekt"
