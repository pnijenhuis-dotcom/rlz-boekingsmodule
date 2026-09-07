"""Blok D 07-09 (4d): `POST …/boekvoorstel/checks` op een Odoo-administratie gaf een kale 500 als de crediteur van het
voorstel nog geen Odoo-partner-koppeling had — de IBAN-seed via de compat-`get` (`Vendors/{id}/BankRelations`) gooide
`OnbekendeOdooId`. Nu: een leesbare, BLOKKERENDE checkuitkomst mét handelingsperspectief (fail-closed), nooit een 500;
de lokale checks en de module-check draaien gewoon door."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.backends.port import CrediteurNietGekoppeld
from app.documenten import boekvoorstel, service
from app.documenten.checks import NAAM_DUPLICAAT_MODULE
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.odoo import sync as odoo_sync
from app.odoo.inkoop import OdooLeesFacade
from app.security.tokens import create_access_token


class _PortZonderPartner:
    """Odoo-port waarvan de crediteur geen `res.partner`-koppeling heeft — precies de productiesituatie van 03-09."""

    class _Client:
        company_id = 1

        def search_read(self, *args: object, **kwargs: object) -> list[dict]:
            raise AssertionError("er mag geen Odoo-call volgen op een ontbrekende partner-koppeling")

    def __init__(self) -> None:
        self.client = self._Client()
        self.aanroepen: list[uuid.UUID] = []

    def partner_id_voor(self, vendor_id: uuid.UUID) -> int:
        self.aanroepen.append(vendor_id)
        raise odoo_sync.OnbekendeOdooId(
            f"res.partner {vendor_id} is niet bekend in de Odoo-koppeling van deze administratie — sync de stamgegevens"
        )


class _FakeInkoopPort:
    def __init__(self, facade: OdooLeesFacade) -> None:
        self._facade = facade

    def leesclient(self) -> OdooLeesFacade:
        return self._facade

    def __exit__(self, *exc: object) -> None:
        return None

    def __enter__(self) -> _FakeInkoopPort:
        return self


def _document_met_voorstel(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_id: uuid.UUID
) -> uuid.UUID:
    document_id = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="odoo-factuur.pdf",
        inhoud=b"%PDF-1.4 odoo " + uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    ).document_id
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie="ODOO-2026-001",
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[],
    )
    return document_id


def test_facade_vertaalt_onbekende_partner_naar_domeinfout_op_beide_leesroutes() -> None:
    facade = OdooLeesFacade(_PortZonderPartner())  # type: ignore[arg-type]
    vendor = uuid.uuid4()
    with pytest.raises(CrediteurNietGekoppeld) as exc:
        facade.get(f"Vendors/{vendor}/BankRelations")
    assert "nog niet gekoppeld in Odoo" in str(exc.value) and "koppel de crediteur" in str(exc.value)
    with pytest.raises(CrediteurNietGekoppeld):
        facade.find_purchase_invoices_by_reference(vendor_id=vendor, reference="X", total_amount=1.0)


def test_checks_geven_leesbare_blokkerende_uitkomst_ipv_500(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    port = _PortZonderPartner()
    document_id = _document_met_voorstel(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
    )
    rapport = boekvoorstel.voer_checks_uit(
        administratie_id=administratie_id,
        document_id=document_id,
        client=OdooLeesFacade(port),  # type: ignore[arg-type]
    )
    assert rapport.geblokkeerd is True
    per_naam = {r.naam: r for r in rapport.resultaten}
    iban = per_naam["IBAN-wissel"]
    assert iban.ok is False and "Crediteur nog niet gekoppeld in Odoo" in iban.melding
    assert "koppel de crediteur aan een Odoo-partner" in iban.melding
    dup = per_naam["Duplicaatcheck"]
    assert dup.ok is False and "kon niet uitgevoerd worden" in dup.melding and "nog niet gekoppeld" in dup.melding
    # Lokale checks + module-check draaien gewoon door (nooit stil wegvallen).
    assert per_naam["Verplichte velden"].ok is not None
    assert NAAM_DUPLICAAT_MODULE in per_naam and per_naam[NAAM_DUPLICAAT_MODULE].ok is True
    assert len(port.aanroepen) == 1  # ná de IBAN-seed geen tweede poging op de duplicaatquery


def test_http_checks_endpoint_geeft_200_met_blokkade(
    monkeypatch: pytest.MonkeyPatch,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
) -> None:
    document_id = _document_met_voorstel(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
    )
    facade = OdooLeesFacade(_PortZonderPartner())  # type: ignore[arg-type]
    monkeypatch.setattr(
        boekvoorstel, "inkoop_port_voor", lambda administratie_id, rlz_client_factory: _FakeInkoopPort(facade)
    )
    client = TestClient(app)
    resp = client.post(
        f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks",
        headers={"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["geblokkeerd"] is True
    iban = next(r for r in body["resultaten"] if r["naam"] == "IBAN-wissel")
    assert iban["ok"] is False and "Crediteur nog niet gekoppeld in Odoo" in iban["melding"]
