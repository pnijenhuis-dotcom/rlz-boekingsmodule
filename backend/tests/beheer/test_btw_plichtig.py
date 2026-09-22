# ruff: noqa: F811 — pytest-fixtures als parameters
"""Btw-plichtig per administratie (BUG Peter 22-09, casus VGG / Studio Lacy Lion 2026-042 → RLZ-04-00000925; migratie 0170):
pure keuzes ("geen btw"-code, detector-regel), service zet/volg_rlz_signaal mét audit (false zet nooit zelf op false),
Beheerder-routes GET/PUT (403 voor boekhouding, 404 onbekend), detector over twee administraties in eigen scope,
identiteit-sync-hook (EnableTaxReporting → signaal/bevestiging), LET-OP `btw_status_bevestigen`, CLI's (kandidaten,
zetten dry-run/echt, rapport zonder en mét RLZ-stub)."""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.beheer import btw_plichtig, btw_plichtig_cli
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.checks import TariefInfo
from app.intercompany import identiteit
from app.main import app
from app.reconciliatie import automatiseringen
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)
LIJST_ROUTE = "/instellingen/administraties"
HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
VRIJ = uuid.UUID("55555555-0000-0000-0000-000000000010")
NUL = uuid.UUID("55555555-0000-0000-0000-000000000000")
VERLEGD = uuid.UUID("55555555-0000-0000-0000-000000000099")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict, dict]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = :a AND record_id = :r "
                "ORDER BY tijdstip"
            ),
            {"a": btw_plichtig.AUDIT_ACTIE, "r": administratie_id},
        ).all()
    return [(r[0], r[1]) for r in rijen]


@pytest.fixture
def tarieven_vgg(administratie_id: uuid.UUID) -> None:
    """De RLZ-standaardset zoals VGG (STAP-0 22-09): hoog, vrijgesteld (favoriet), nul, verlegd."""
    with scoped_session(administratie_id) as session:
        session.add_all(
            [
                TaxRateCache(
                    id=HOOG,
                    administratie_id=administratie_id,
                    naam="NL, Hoog Tarief",
                    percentage=Decimal("0.21"),
                    brondata={"IsFavorite": True},
                ),
                TaxRateCache(
                    id=VRIJ,
                    administratie_id=administratie_id,
                    naam="NL, Geen BTW (Vrijgesteld)",
                    percentage=Decimal("0"),
                    brondata={"IsExcempt": True, "IsFavorite": True},
                ),
                TaxRateCache(
                    id=NUL,
                    administratie_id=administratie_id,
                    naam="NL, Nul tarief",
                    percentage=Decimal("0"),
                    brondata={},
                ),
                TaxRateCache(
                    id=VERLEGD,
                    administratie_id=administratie_id,
                    naam="NL, BTW verlegd (hoog)",
                    percentage=Decimal("0"),
                    brondata={"IsRelayed": True},
                ),
            ]
        )


class TestPureRegels:
    def test_geen_btw_code_vrijgesteld_boven_nul_boven_niets(self) -> None:
        t = {
            HOOG: TariefInfo(Decimal("0.21"), "NL, Hoog Tarief", favoriet=True),
            VRIJ: TariefInfo(Decimal("0"), "NL, Geen BTW (Vrijgesteld)", vrijgesteld=True, favoriet=True),
            NUL: TariefInfo(Decimal("0"), "NL, Nul tarief"),
            VERLEGD: TariefInfo(Decimal("0"), "NL, BTW verlegd (hoog)", verlegd=True),
        }
        assert btw_plichtig.geen_btw_taxrate_uit(t) == VRIJ
        del t[VRIJ]
        assert btw_plichtig.geen_btw_taxrate_uit(t) == NUL
        del t[NUL]
        assert btw_plichtig.geen_btw_taxrate_uit(t) is None  # verlegd/hoog zijn nooit "geen btw"
        assert btw_plichtig.heeft_tarief_met_percentage(t) is True
        assert btw_plichtig.heeft_tarief_met_percentage({VERLEGD: t[VERLEGD]}) is False

    def test_kandidaat_regel(self) -> None:
        f = btw_plichtig.kandidaat_reden
        assert f(btw_plichtig=True, bron=None, rlz_signaal=False, tarief_met_pct=True) == "rlz_signaal"
        assert f(btw_plichtig=True, bron=None, rlz_signaal=None, tarief_met_pct=False) == "geen_tarief_met_percentage"
        assert f(btw_plichtig=True, bron=None, rlz_signaal=True, tarief_met_pct=True) is None
        assert f(btw_plichtig=True, bron="rlz", rlz_signaal=True, tarief_met_pct=True) is None
        assert f(btw_plichtig=True, bron="rlz", rlz_signaal=True, tarief_met_pct=False) is None  # RLZ bevestigde al
        # Nog niets gesynct = geen kandidaat (sync-gat, geen btw-signaal).
        assert f(btw_plichtig=True, bron=None, rlz_signaal=None, tarief_met_pct=False, tarieven_gesynct=False) is None
        # Een mens-keuze laat de detector zwijgen — ook bij een tegengesteld RLZ-signaal.
        assert f(btw_plichtig=True, bron="mens", rlz_signaal=False, tarief_met_pct=False) is None
        assert f(btw_plichtig=False, bron="mens", rlz_signaal=False, tarief_met_pct=True) is None


class TestService:
    def test_default_true_zonder_bron(self, administratie_id, tarieven_vgg) -> None:
        stand = btw_plichtig.haal_op(administratie_id=administratie_id)
        assert stand.btw_plichtig is True and stand.bron is None and stand.rlz_signaal is None
        assert stand.geen_btw_taxrate_id == VRIJ and stand.geen_btw_taxrate_naam == "NL, Geen BTW (Vrijgesteld)"
        assert stand.kandidaat is False
        assert btw_plichtig.is_btw_plichtig(administratie_id) is True
        assert btw_plichtig.is_btw_plichtig(uuid.uuid4()) is True  # onbekend = bestaand gedrag

    def test_zet_uit_met_audit_en_idempotent(self, administratie_id, beheerder_id, admin_engine, tarieven_vgg) -> None:
        stand = btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=False)
        assert stand.btw_plichtig is False and stand.bron == "mens" and stand.gewijzigd_op is not None
        assert btw_plichtig.is_btw_plichtig(administratie_id) is False
        # Idempotent: dezelfde stand nog eens = geen tweede audit.
        btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=False)
        assert _audit(admin_engine, administratie_id) == [
            ({"btw_plichtig": True, "bron": None}, {"btw_plichtig": False, "bron": "mens"})
        ]
        # Herbevestiging "aan" door een mens ná een lege bron = wél een audit (de bron verandert).
        btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=True)
        assert _audit(admin_engine, administratie_id)[-1] == (
            {"btw_plichtig": False, "bron": "mens"},
            {"btw_plichtig": True, "bron": "mens"},
        )
        with pytest.raises(btw_plichtig.BtwPlichtigFout):
            btw_plichtig.zet(actor_id=beheerder_id, administratie_id=uuid.uuid4(), btw_plichtig=False)

    def test_rlz_signaal_true_bevestigt_false_zet_nooit_zelf_uit(self, administratie_id, admin_engine) -> None:
        # false = alleen opslaan → kandidaat; het kenmerk blijft true (geld: nooit stil in de kosten).
        stand = btw_plichtig.volg_rlz_signaal(
            administratie_id=administratie_id, enable_tax_reporting=False, actor_id=SYSTEEM_ACTOR_ID
        )
        assert stand == "signaal_opgeslagen"
        dto = btw_plichtig.haal_op(administratie_id=administratie_id)
        assert dto.btw_plichtig is True and dto.bron is None and dto.rlz_signaal is False
        assert dto.kandidaat is True and dto.kandidaat_reden == "rlz_signaal"
        assert _audit(admin_engine, administratie_id) == []
        # true = bevestigt btw-plichtig mét bron 'rlz' + audit; tweede keer = alleen signaal (geen audit).
        assert (
            btw_plichtig.volg_rlz_signaal(
                administratie_id=administratie_id, enable_tax_reporting=True, actor_id=SYSTEEM_ACTOR_ID
            )
            == "bevestigd_rlz"
        )
        assert (
            btw_plichtig.volg_rlz_signaal(
                administratie_id=administratie_id, enable_tax_reporting=True, actor_id=SYSTEEM_ACTOR_ID
            )
            == "signaal_opgeslagen"
        )
        dto = btw_plichtig.haal_op(administratie_id=administratie_id)
        assert dto.bron == "rlz" and dto.kandidaat is False
        assert len(_audit(admin_engine, administratie_id)) == 1
        assert _audit(admin_engine, administratie_id)[0][1]["signaal"] == "EnableTaxReporting"
        # None = geen signaal, niets aangeraakt.
        assert (
            btw_plichtig.volg_rlz_signaal(
                administratie_id=administratie_id, enable_tax_reporting=None, actor_id=SYSTEEM_ACTOR_ID
            )
            == "geen_signaal"
        )

    def test_mens_keuze_wint_van_rlz_signaal(self, administratie_id, beheerder_id) -> None:
        btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=False)
        assert (
            btw_plichtig.volg_rlz_signaal(
                administratie_id=administratie_id, enable_tax_reporting=True, actor_id=SYSTEEM_ACTOR_ID
            )
            == "mens"
        )
        dto = btw_plichtig.haal_op(administratie_id=administratie_id)
        assert dto.btw_plichtig is False and dto.bron == "mens" and dto.rlz_signaal is True


class TestRoutes:
    def test_get_put_beheerder_en_403_boekhouding(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, tarieven_vgg
    ) -> None:
        resp = client.get(
            f"/administraties/{administratie_id}/btw-plichtig", headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 200, resp.text
        assert (
            resp.json()["btw_plichtig"] is True and resp.json()["geen_btw_taxrate_naam"] == "NL, Geen BTW (Vrijgesteld)"
        )
        resp = client.put(
            f"/administraties/{administratie_id}/btw-plichtig",
            json={"btw_plichtig": False},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["btw_plichtig"] is False and resp.json()["bron"] == "mens"
        resp = client.get(
            f"/administraties/{administratie_id}/btw-plichtig", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 403
        resp = client.get(
            f"/administraties/{uuid.uuid4()}/btw-plichtig", headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 404
        # De administratie-lijst draagt het kenmerk mee (frontend-chip).
        resp = client.get(LIJST_ROUTE, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        rij = next(r for r in resp.json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["btw_plichtig"] is False and rij["btw_plichtig_bron"] == "mens"


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Verhuur Twee B.V.', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


class TestDetectorEnSync:
    def test_kandidaten_over_administraties_en_let_op(
        self, administratie_id, tweede_administratie, tarieven_vgg
    ) -> None:
        # Eén: RLZ-signaal false (heeft wél tarieven > 0 %); twee: alleen een 0 %-tarief gesynct (geen percentage > 0).
        with scoped_session(tweede_administratie) as session:
            session.add(
                TaxRateCache(
                    id=NUL,
                    administratie_id=tweede_administratie,
                    naam="NL, Nul tarief",
                    percentage=Decimal("0"),
                    brondata={},
                )
            )
        btw_plichtig.volg_rlz_signaal(
            administratie_id=administratie_id, enable_tax_reporting=False, actor_id=SYSTEEM_ACTOR_ID
        )
        kandidaten = btw_plichtig.kandidaten()
        per_id = {k.administratie_id: k for k in kandidaten}
        assert per_id[administratie_id].reden == "rlz_signaal"
        assert per_id[tweede_administratie].reden == "geen_tarief_met_percentage"
        bevindingen = automatiseringen.btw_status_bevindingen(nu=datetime.now(UTC), kandidaten=kandidaten)
        assert len(bevindingen) == 2
        b = next(x for x in bevindingen if x["administratie_id"] == administratie_id)
        assert b["soort"] == "let_op" and b["blok"] == automatiseringen.BLOK
        assert "EnableTaxReporting=false" in b["tekst"] and "Bevestig de btw-status" in b["tekst"]
        assert b["detail"]["reden"] == automatiseringen.BTW_STATUS_BEVESTIGEN
        assert b["detail"]["doel_pad"] == f"/instellingen/administraties/{administratie_id}?tab=boeken-ai#btw-plichtig"
        # Niet als regressie (domein-LET-OP, geen codefout).
        assert automatiseringen.BTW_STATUS_BEVESTIGEN not in automatiseringen.REGRESSIE_CATEGORIEEN
        # Mens bevestigt → weg uit de detector.
        btw_plichtig.zet(actor_id=SYSTEEM_ACTOR_ID, administratie_id=administratie_id, btw_plichtig=False)
        btw_plichtig.zet(actor_id=SYSTEEM_ACTOR_ID, administratie_id=tweede_administratie, btw_plichtig=True)
        assert btw_plichtig.kandidaten() == []
        assert automatiseringen.btw_status_bevindingen(nu=datetime.now(UTC), kandidaten=[]) == []

    def test_identiteit_sync_leest_enable_tax_reporting(self, administratie_id, tweede_administratie) -> None:
        class Client:
            def __init__(self, etr) -> None:  # noqa: ANN001
                self.etr = etr

            def get(self, pad, params=None):  # noqa: ANN001, ANN201
                assert pad == "AdministrationSettings"
                return {
                    "value": [
                        {"CompanyName": "X B.V.", "ChamberOfCommerceNumber": "12345678", "EnableTaxReporting": self.etr}
                    ]
                }

        assert identiteit.lees_identiteit_rlz(Client(False)).enable_tax_reporting is False
        assert identiteit.lees_identiteit_rlz(Client(True)).enable_tax_reporting is True
        assert identiteit.lees_identiteit_rlz(Client(None)).enable_tax_reporting is None

        def lezer(aid: uuid.UUID) -> identiteit.Identiteit:
            return identiteit.lees_identiteit_rlz(Client(aid != administratie_id))

        uitkomsten = identiteit.sync_identiteiten([administratie_id, tweede_administratie], lezer=lezer)
        per_id = {u.administratie_id: u for u in uitkomsten}
        assert per_id[administratie_id].stand == "gelezen"
        assert "EnableTaxReporting=false" in (per_id[administratie_id].melding or "")
        assert per_id[tweede_administratie].melding == "btw-plichtig bevestigd uit RLZ (EnableTaxReporting)"
        assert btw_plichtig.haal_op(administratie_id=administratie_id).rlz_signaal is False
        assert btw_plichtig.haal_op(administratie_id=tweede_administratie).bron == "rlz"


class TestCli:
    def test_kandidaten_en_zetten(self, administratie_id, tarieven_vgg, capsys) -> None:
        btw_plichtig.volg_rlz_signaal(
            administratie_id=administratie_id, enable_tax_reporting=False, actor_id=SYSTEEM_ACTOR_ID
        )
        assert cli.main(["btw-plichtig-kandidaten"]) == 0
        uit = capsys.readouterr().out
        assert "1 administratie(s) kandidaat" in uit and "Scope-test" in uit and "EnableTaxReporting=false" in uit
        assert cli.main(["btw-plichtig-zetten", "--administratie", str(administratie_id), "--uit", "--dry-run"]) == 0
        assert "DRY-RUN" in capsys.readouterr().out
        assert btw_plichtig.is_btw_plichtig(administratie_id) is True
        assert cli.main(["btw-plichtig-zetten", "--administratie", "Scope-test", "--uit"]) == 0
        uit = capsys.readouterr().out
        assert "GEZET" in uit and "NL, Geen BTW (Vrijgesteld)" in uit
        assert btw_plichtig.haal_op(administratie_id=administratie_id).bron == "mens"
        assert cli.main(["btw-plichtig-zetten", "--administratie", "Scope-test", "--uit"]) == 0
        assert "ONGEWIJZIGD" in capsys.readouterr().out
        assert cli.main(["btw-plichtig-zetten", "--administratie", "bestaat-niet", "--aan"]) == 2

    def test_rapport_module_en_rlz_stub(self, administratie_id, gescoopte_gebruiker, tarieven_vgg, capsys) -> None:
        from app.documenten.models import (
            Boekvoorstel,
            BoekvoorstelRegel,
            Document,
            DocumentBron,
            DocumentSoort,
            DocumentStatus,
        )
        from app.documenten.rlz_ids import rlz_herboeking_id
        from app.sync.models import VendorCache

        vendor = uuid.uuid4()
        doc_id = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(VendorCache(id=vendor, administratie_id=administratie_id, naam="Studio Lacy Lion", brondata={}))
            session.add(
                Document(
                    id=doc_id,
                    administratie_id=administratie_id,
                    bestandsnaam="2026-042.pdf",
                    opslag_pad="x",
                    sha256_hash="a" * 64,
                    status=DocumentStatus.GEBOEKT,
                    soort=DocumentSoort.INKOOPFACTUUR.value,
                    bron=DocumentBron.UPLOAD,
                )
            )
            session.flush()
            session.add(
                Boekvoorstel(
                    document_id=doc_id,
                    vendor_id=vendor,
                    referentie="2026-042",
                    factuurdatum=date(2026, 9, 11),
                    totaalbedrag=Decimal("1857.51"),
                    rlz_boekstuknummer="RLZ-04-00000925",
                )
            )
            session.flush()
            session.add(
                BoekvoorstelRegel(
                    document_id=doc_id,
                    volgnummer=1,
                    ledger_id=uuid.uuid4(),
                    taxrate_id=HOOG,
                    netto_bedrag=Decimal("1535.13"),
                    btw_bedrag=Decimal("322.38"),
                    omschrijving="Schoonmaakkosten",
                )
            )
        rijen = btw_plichtig_cli.module_documenten(administratie_id, jaar=2026)
        assert len(rijen) == 1 and rijen[0].bruto == "1857.51" and rijen[0].btw == "322.38"
        assert btw_plichtig_cli.module_documenten(administratie_id, jaar=2025) == []
        assert cli.main(["btw-in-niet-plichtige-administratie", "--administratie", "Scope-test", "--jaar", "2026"]) == 0
        uit = capsys.readouterr().out
        assert "RLZ-04-00000925" in uit and "Studio Lacy Lion" in uit and "RLZ-kant niet gelezen" in uit

        class Stub:
            def get(self, pad, params=None):  # noqa: ANN001, ANN201
                if pad == f"PurchaseInvoices/{rlz_herboeking_id(doc_id, 0)}":
                    return {
                        "id": str(rlz_herboeking_id(doc_id, 0)),
                        "Status": 2,
                        "BaseInvoiceAmount": 1535.13,
                        "TotalTaxAmount": 0.0,
                        "BasePaidAmount": 0.0,
                        "BaseRemainingAmount": 1535.13,
                        "ReceiptNumber": "RLZ-04-00000925",
                    }
                assert pad == "PurchaseInvoices"
                return {
                    "value": [
                        {"id": str(rlz_herboeking_id(doc_id, 0)), "Date": "2026-09-11T00:00:00", "TotalTaxAmount": 0.0},
                        {
                            "id": str(uuid.uuid4()),
                            "Date": "2026-03-01T00:00:00",
                            "TotalTaxAmount": 21.0,
                            "BaseInvoiceAmount": 121.0,
                            "ReceiptNumber": "RLZ-04-00000100",
                            "Reference": "F-100",
                            "Entity": {"Name": "Anders B.V."},
                        },
                        {"id": str(uuid.uuid4()), "Date": "2027-01-05T00:00:00", "TotalTaxAmount": 5.0},
                    ]
                }

            def list_tax_declarations(self):  # noqa: ANN201
                return []

            def close(self) -> None:
                pass

        stub = Stub()
        gezien = btw_plichtig_cli.verrijk_met_rlz(stub, rijen)
        assert rijen[0].rlz_crediteurpost == "1535.13" and rijen[0].te_weinig_betaald == "322.38"
        extern = btw_plichtig_cli.rlz_documenten_met_btw(stub, jaar=2026, uitgezonderd=gezien)
        assert [r.boekstuk for r in extern] == ["RLZ-04-00000100"]  # 2027 valt buiten het jaar, eigen doc uitgezonderd
        # Volledige --rlz-vorm via cli.main mét de stub als client.
        import app.beheer.btw_plichtig_cli as mod

        mod._client_voor = lambda aid: stub  # type: ignore[assignment]
        try:
            assert cli.main(["btw-in-niet-plichtige-administratie", "--administratie", "Scope-test", "--rlz"]) == 0
        finally:
            del mod._client_voor
            import importlib

            importlib.reload(mod)
        uit = capsys.readouterr().out
        assert "TOTAAL te weinig betaald (bruto module − crediteurpost RLZ): € 322.38" in uit
        assert "ingediende btw-aangiften in RLZ: 0" in uit and "Anders B.V." in uit

    def test_dispatch_negeert_andere_commandos(self) -> None:
        assert btw_plichtig_cli.dispatch(argparse.Namespace(commando="iets-anders")) is None
