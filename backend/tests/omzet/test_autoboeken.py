# ruff: noqa: F811 — pytest-fixtures als parameters
"""Omzet-autoboeken-opt-in (GO Peter 01-09, migratie 0096): het pad boekt uitsluitend wanneer álles
groen is — opt-in aan, onaangeraakt rapport, categorie-mapping volledig mens-bevestigd, harde checks
(incl. marge-plausibiliteit) groen, failsafes — elke weiger-reden getest; half-geboekt = audit + alert;
GEBOEKT draagt `automatisch_geboekt` + bron `omzet_opt_in`; toggle Beheerder-only mét audit."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken as documenten_boeken
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.main import app
from app.omzet import autoboeken
from app.omzet.mapping import onthoud_mapping
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus, OmzetInstelling
from app.security.tokens import create_access_token
from tests.omzet.conftest import (
    RAPPORT_VELDVOORSTEL,
    FakeOmzetClient,
    document_status,
    sla_compleet_voorstel_op,
)

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: FakeOmzetClient) -> None:
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)


def _audit(admin_engine: Engine, actie: str, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a AND record_id = :id"),
                {"a": actie, "id": document_id},
            )
        ]


def _weiger_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    return [r["nieuwe_waarde"]["reden"] for r in _audit(admin_engine, "autoboeken_geweigerd", document_id)]


@pytest.fixture
def optin_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_omzet_autoboeken_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


@pytest.fixture
def mapping_compleet(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, taxrate_vrijgesteld: uuid.UUID
) -> dict[str, uuid.UUID]:
    """Mens-bevestigde mapping voor álle rapportcategorieën + de voorraad-GB (memoriaal-kant) — zoals
    een controleur die bij een eerder rapport heeft vastgelegd — zónder een opgeslagen voorstel op
    dít document."""
    ids = {"omzet": uuid.uuid4(), "kostprijs": uuid.uuid4(), "voorraad": uuid.uuid4()}
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        for regel in RAPPORT_VELDVOORSTEL["regels"]:
            onthoud_mapping(
                session,
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                categorie=regel["categorie"],
                omzet_ledger_id=ids["omzet"],
                taxrate_id=taxrate_vrijgesteld,
                kostprijs_ledger_id=ids["kostprijs"],
            )
        session.add(OmzetInstelling(administratie_id=administratie_id, voorraad_ledger_id=ids["voorraad"]))
    return ids


class TestPoorten:
    def test_zonder_optin_gebeurt_niets_en_geen_audit_ruis(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        besluit = autoboeken.probeer_omzet_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert besluit is None
        assert _weiger_redenen(admin_engine, kassarapport_document) == []
        assert document_status(administratie_id, kassarapport_document) == "te_controleren"

    def test_categorie_zonder_mens_bevestigde_mapping_weigert(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, optin_aan: None, admin_engine: Engine
    ) -> None:
        besluit = autoboeken.probeer_omzet_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert besluit is not None and not besluit.geboekt
        redenen = _weiger_redenen(admin_engine, kassarapport_document)
        assert len(redenen) == 1
        assert "voorraad-grootboekrekening" in redenen[0] or "zonder mens-bevestigde mapping" in redenen[0]
        assert document_status(administratie_id, kassarapport_document) == "te_controleren"

    def test_door_mens_opgeslagen_voorstel_is_mensenwerk(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        taxrate_vrijgesteld: uuid.UUID,
        optin_aan: None,
        admin_engine: Engine,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=taxrate_vrijgesteld,
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        autoboeken.probeer_omzet_autoboeken_na_extractie(administratie_id=administratie_id, document_id=kassarapport_document)
        assert any("door een mens opgeslagen voorstel" in r for r in _weiger_redenen(admin_engine, kassarapport_document))

    def test_boeken_uit_en_kill_switch_weigeren_zichtbaar(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        optin_aan: None,
        mapping_compleet: dict,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        _patch_client(monkeypatch, FakeOmzetClient())
        autoboeken.probeer_omzet_autoboeken_na_extractie(administratie_id=administratie_id, document_id=kassarapport_document)
        redenen = _weiger_redenen(admin_engine, kassarapport_document)
        assert redenen and "Boeken staat uit" in redenen[-1]
        # De motor zette het document (checks groen) op klaar_om_te_boeken vóór de toggle-poort — het
        # blijft zichtbaar in de werkvoorraad, er is niets geboekt.
        assert document_status(administratie_id, kassarapport_document) == "klaar_om_te_boeken"

    def test_marge_buiten_bandbreedte_blokkeert_via_de_harde_check(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag,
        optin_aan: None,
        mapping_compleet: dict,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        # Historie mét een totaal andere marge (omzet ≈ kostprijs) → het rapport (marge ~160 %) valt buiten
        # de bandbreedte → de blokkerende check wint, ook zonder mens.
        ander = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="MargeRapport-wk30.pdf",
            inhoud=b"%PDF-1.4 ander rapport",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                OmzetBoeking(
                    administratie_id=administratie_id,
                    document_id=ander,
                    periode_start=date(2025, 7, 21),
                    periode_eind=date(2025, 7, 27),
                    totaal_omzet=Decimal("10000.00"),
                    totaal_kostprijs=Decimal("9800.00"),
                    verkoop_rlz_id=uuid.uuid4(),
                    status=OmzetBoekingStatus.GEBOEKT.value,
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        _patch_client(monkeypatch, FakeOmzetClient())
        besluit = autoboeken.probeer_omzet_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert besluit is not None and not besluit.geboekt
        assert "Marge-plausibiliteit" in besluit.reden and "harde checks blokkeren" in besluit.reden
        assert document_status(administratie_id, kassarapport_document) == "te_controleren"


class TestGroenPad:
    def test_alles_groen_boekt_automatisch_met_markering_en_audit(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        optin_aan: None,
        mapping_compleet: dict,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        fake = FakeOmzetClient()
        _patch_client(monkeypatch, fake)
        besluit = autoboeken.probeer_omzet_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert besluit is not None and besluit.geboekt
        assert document_status(administratie_id, kassarapport_document) == "geboekt"
        # Verkoop + memoriaal als één transactie in RLZ, mapping-GB's gebruikt.
        assert len(fake.sales_invoices) == 1 and len(fake.manual_journals) == 1
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d "
                    "AND naar_status = 'geboekt' ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"d": kassarapport_document},
            ).scalar_one()
            boeking_status = conn.execute(
                text("SELECT status FROM boekhouding.omzet_boeking WHERE document_id = :d"), {"d": kassarapport_document}
            ).scalar_one()
        assert detail["automatisch_geboekt"] is True and detail["bron"] == "omzet_opt_in"
        assert boeking_status == "geboekt"
        audit = _audit(admin_engine, "automatisch_geboekt", kassarapport_document)
        assert len(audit) == 1 and audit[0]["nieuwe_waarde"]["bron"] == "omzet_opt_in"
        assert _weiger_redenen(admin_engine, kassarapport_document) == []
        # Tweede aanroep (her-extractie): document is geen kandidaat meer → None, geen ruis.
        assert autoboeken.probeer_omzet_autoboeken_na_extractie(administratie_id=administratie_id, document_id=kassarapport_document) is None

    def test_half_geboekt_is_nooit_stil_audit_plus_alert(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        optin_aan: None,
        mapping_compleet: dict,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        fake = FakeOmzetClient(faal_op="memoriaal_boeken")

        def storno_faalt(invoice_id: uuid.UUID) -> None:
            from app.rlz.client import RlzApiError

            raise RlzApiError(500, "POST", f"SalesInvoices/{invoice_id}/Actions", "Storno mislukt (simulatie)")

        fake.correct_sales_invoice = storno_faalt  # type: ignore[method-assign]
        _patch_client(monkeypatch, fake)
        alerts: list[str] = []
        from app.bewaking import service as bewaking

        monkeypatch.setattr(bewaking, "_verzend_alert", lambda *, onderwerp, tekst: alerts.append(onderwerp) or True)

        besluit = autoboeken.probeer_omzet_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert besluit is not None and not besluit.geboekt and "HALF GEBOEKT" in besluit.reden
        assert document_status(administratie_id, kassarapport_document) == "boeken_mislukt"
        assert len(_audit(admin_engine, "autoboeken_half_geboekt", kassarapport_document)) == 1
        assert alerts and "HALF GEBOEKT" in alerts[0]


class TestToggleEnRolpoorten:
    def test_toggle_default_uit_audit_en_endpoint(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert beheer_service.haal_omzet_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is False
        headers = _bearer(beheerder_id, rol="beheerder")
        r = client.put(f"/administraties/{administratie_id}/omzet-autoboeken-instelling", headers=headers, json={"ingeschakeld": True})
        assert r.status_code == 200 and r.json() == {"ingeschakeld": True}
        assert client.get(f"/administraties/{administratie_id}/omzet-autoboeken-instelling", headers=headers).json() == {"ingeschakeld": True}
        lijst = client.get("/instellingen/administraties", headers=headers).json()["administraties"]
        assert next(a for a in lijst if a["id"] == str(administratie_id))["omzet_autoboeken_ingeschakeld"] is True
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'omzet_autoboeken_ingeschakeld_gewijzigd' AND record_id = :id"),
                {"id": administratie_id},
            ).scalar()
        assert n == 1

    def test_niet_beheerder_403(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.put(f"/administraties/{administratie_id}/omzet-autoboeken-instelling", headers=headers, json={"ingeschakeld": True}).status_code == 403
        assert client.get(f"/administraties/{administratie_id}/omzet-autoboeken-instelling", headers=headers).status_code == 403

    def test_cli_terugval(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        import argparse

        from app.cli import _zet_omzet_autoboeken

        args = argparse.Namespace(administratie_id=str(administratie_id), beheerder_id=str(beheerder_id))
        assert _zet_omzet_autoboeken(args, ingeschakeld=True) == 0
        assert beheer_service.haal_omzet_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is True
        assert _zet_omzet_autoboeken(args, ingeschakeld=False) == 0
        assert beheer_service.haal_omzet_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is False


class TestHookVolgorde:
    def test_na_extractie_hook_probeert_autoboeken_voor_de_mapping_autovraag(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        volgorde: list[str] = []
        from app.omzet import autovraag

        monkeypatch.setattr(
            autoboeken, "probeer_omzet_autoboeken_na_extractie", lambda **kw: volgorde.append("autoboek")
        )
        monkeypatch.setattr(autovraag, "stel_mapping_vraag_indien_nodig", lambda **kw: volgorde.append("autovraag"))
        documenten_service._na_extractie_hook(
            administratie_id=administratie_id, document_id=kassarapport_document, soort=DocumentSoort.KASSARAPPORT.value
        )
        assert volgorde == ["autoboek", "autovraag"]
