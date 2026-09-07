# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Documenten-reconciliatie backend-agnostisch (A12, fixrun 07-09):

- Odoo-port-toets met gefakete client: posted zonder reversal = groen; draft/cancel = niet_geboekt_in_odoo; ONBEKENDE
  reversal = teruggedraaid_in_odoo, maar onze EIGEN tegenboeking (odoo_document_koppeling) níét; amount_total ≠ eigen
  totaal = bedrag_wijkt_af; move verdwenen / geen koppeling+marker = ontbreekt_in_odoo; RLZ-boekstuk zonder
  Odoo-spoor = niet van toepassing (overgeslagen, geen bevinding); OdooFout = controle_mislukt;
- bank/omzet/doorbelasting blijven RLZ-only: een Odoo-administratie wordt zichtbaar OVERGESLAGEN (CLI-regel), nooit
  als fout geteld;
- de CLI zet de naam-context op élke documenten-afwijking (contract A↔A8)."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.backends.port import Backend, ToetsMislukt
from app.backends.registry import RLZ_ONLY_OVERGESLAGEN, actieve_administraties_per_backend
from app.bank import reconciliatie as bank_reconciliatie
from app.documenten import reconciliatie
from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport
from app.doorbelasting import reconciliatie as doorbelasting_reconciliatie
from app.odoo.client import OdooFout
from app.odoo.credentials import OdooVerbinding
from app.odoo.inkoop import OdooInkoopPort
from app.omzet import reconciliatie as omzet_reconciliatie
from app.reconciliatie import run as run_service
from app.reconciliatie.service import Beoordeeld
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

COMPANY = 1


def _move(mid: int, **extra: Any) -> dict[str, Any]:
    basis = {
        "id": mid,
        "name": f"BILL/2026/09/{mid:04d}",
        "state": "posted",
        "payment_state": "not_paid",
        "company_id": [COMPANY, "Universal Steigerbouw B.V."],
        "amount_total": 121.0,
        "reversed_entry_id": False,
        "reversal_move_ids": [],
        "move_type": "in_invoice",
        "invoice_origin": "",
    }
    basis.update(extra)
    return basis


class _FakeOdoo:
    company_id = COMPANY

    def __init__(self, moves: dict[int, dict[str, Any]], *, faal: bool = False) -> None:
        self.moves = moves
        self.faal = faal
        self.gesloten = False

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        if self.faal:
            raise OdooFout(500, "InternalError", "storing (simulatie)", model=model, methode="read")
        return self.moves.get(int(odoo_id))

    def search_read(self, model: str, domain: list, fields: list[str]) -> list[dict[str, Any]]:
        if self.faal:
            raise OdooFout(500, "InternalError", "storing (simulatie)", model=model, methode="search_read")
        marker = next(d[2] for d in domain if d[0] == "invoice_origin")
        return [m for m in self.moves.values() if m.get("invoice_origin") == marker]

    def close(self) -> None:
        self.gesloten = True


def _port(administratie_id: uuid.UUID, fake: _FakeOdoo) -> OdooInkoopPort:
    verbinding = OdooVerbinding(
        administratie_id=administratie_id,
        odoo_url="https://universal-steigers.odoo.com",
        company_id=COMPANY,
        company_naam="Universal Steigerbouw B.V.",
        journal_purchase_id=9,
        journal_general_id=8,
        journal_sale_id=7,
        analytic_plan_id=2,
    )
    return OdooInkoopPort(administratie_id, verbinding, fake)  # type: ignore[arg-type]


def _doc(**extra: Any) -> reconciliatie._Geboekt:
    basis = dict(
        document_id=uuid.uuid4(),
        totaalbedrag=Decimal("121.00"),
        rlz_boekstuknummer="BILL/2026/09/3101",
        boek_cyclus=0,
        referentie="F-1",
        leverancier_naam="TEST Leverancier",
    )
    basis.update(extra)
    return reconciliatie._Geboekt(**basis)


def _soorten(doc: reconciliatie._Geboekt, uitkomst) -> list[str]:  # noqa: ANN001
    return [a.soort for a in reconciliatie.beoordeel_uitkomst(doc, uitkomst, backend=Backend.ODOO, administratie_naam="X")]


class TestOdooToets:
    def test_posted_zonder_reversal_is_groen(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({3101: _move(3101)}))
        u = port.beoordeel_move(_move(3101), eigen_tegenboekingen=set())
        assert u.bestaat and u.geboekt and not u.teruggedraaid
        assert u.bedrag == Decimal("121.00") and u.boekstuknummer == "BILL/2026/09/3101" and u.extern_state == "posted"
        assert _soorten(_doc(), u) == []

    @pytest.mark.parametrize("state", ["draft", "cancel"])
    def test_niet_posted_is_niet_geboekt(self, administratie_id, state: str) -> None:
        port = _port(administratie_id, _FakeOdoo({}))
        u = port.beoordeel_move(_move(3101, state=state, name=False), eigen_tegenboekingen=set())
        assert u.bestaat and not u.geboekt
        soorten = _soorten(_doc(rlz_boekstuknummer=None), u)
        assert "niet_geboekt_in_odoo" in soorten

    def test_onbekende_reversal_is_teruggedraaid_maar_eigen_tegenboeking_niet(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({}))
        move = _move(3101, payment_state="reversed", reversal_move_ids=[3102])
        onbekend = port.beoordeel_move(move, eigen_tegenboekingen=set())
        assert onbekend.teruggedraaid and "3102" in (onbekend.reden or "")
        assert _soorten(_doc(), onbekend) == ["teruggedraaid_in_odoo"]
        eigen = port.beoordeel_move(move, eigen_tegenboekingen={3102})
        assert not eigen.teruggedraaid
        assert _soorten(_doc(), eigen) == []

    def test_bedrag_en_boekstuk_afwijking(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({}))
        u = port.beoordeel_move(_move(3101, amount_total=120.5, name="BILL/2026/09/9999"), eigen_tegenboekingen=set())
        afw = reconciliatie.beoordeel_uitkomst(_doc(), u, backend=Backend.ODOO, administratie_naam="X")
        assert [a.soort for a in afw] == ["bedrag_wijkt_af", "boekstuknummer_wijkt_af"]
        assert afw[0].detail == "eigen=€121.00 odoo=€120.50"
        assert afw[0].context["extern_id"] == "3101" and afw[0].context["backend"] == "odoo"

    def test_company_mismatch_is_toets_mislukt(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({}))
        with pytest.raises(ToetsMislukt, match="KRITIEK"):
            port.beoordeel_move(_move(3101, company_id=[3, "Andere"]), eigen_tegenboekingen=set())

    def test_toets_geboekt_via_koppeling_marker_en_ontbreekt(
        self, administratie_id, gescoopte_gebruiker, opslag
    ) -> None:
        from app.documenten import service

        # Een echt document: de koppeling-tabel draagt een FK naar boekhouding.document.
        doc = service.upload_document(
            administratie_id=administratie_id, bestandsnaam="f.pdf", inhoud=b"%PDF-1.4 x",
            actor_id=gescoopte_gebruiker, opslag=opslag,
        ).document_id
        marker = f"AKN:{doc}:0:boeking"
        fake = _FakeOdoo({3101: _move(3101, invoice_origin=marker)})
        port = _port(administratie_id, fake)
        # (a) geen koppeling, wél onze marker → gevonden
        u = port.toets_geboekt(document_id=doc, boek_cyclus=0, boekstuknummer="BILL/2026/09/3101")
        assert u.bestaat and u.extern_id == "3101"
        # (b) eigen koppeling → read_een; move weg → ontbreekt
        port._leg_koppeling_vast(document_id=doc, boek_cyclus=0, soort="boeking", move=_move(3101))
        del fake.moves[3101]
        u = port.toets_geboekt(document_id=doc, boek_cyclus=0, boekstuknummer="BILL/2026/09/3101")
        assert not u.bestaat and "bestaat niet meer" in (u.reden or "")
        assert [a.soort for a in reconciliatie.beoordeel_uitkomst(_doc(document_id=doc), u, backend=Backend.ODOO, administratie_naam="X")] == [
            "ontbreekt_in_odoo"
        ]
        # (c) eigen tegenboeking-koppeling → reversal is bekend
        fake.moves[3101] = _move(3101, reversal_move_ids=[3102], payment_state="reversed")
        port._leg_koppeling_vast(
            document_id=doc, boek_cyclus=0, soort="tegenboeking", move=_move(3102, move_type="in_refund"), reversal_van=3101
        )
        u = port.toets_geboekt(document_id=doc, boek_cyclus=0)
        assert u.bestaat and not u.teruggedraaid and u.ruw["eigen_tegenboekingen"] == [3102]

    def test_rlz_verleden_is_niet_van_toepassing_en_zonder_spoor_ontbreekt(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({}))
        u = port.toets_geboekt(document_id=uuid.uuid4(), boek_cyclus=0, boekstuknummer="RLZ-04-00002006")
        assert not u.van_toepassing and "vóór de overstap" in (u.reden or "")
        u2 = port.toets_geboekt(document_id=uuid.uuid4(), boek_cyclus=0, boekstuknummer=None)
        assert u2.van_toepassing and not u2.bestaat

    def test_odoo_fout_is_toets_mislukt(self, administratie_id) -> None:
        port = _port(administratie_id, _FakeOdoo({}, faal=True))
        with pytest.raises(ToetsMislukt):
            port.toets_geboekt(document_id=uuid.uuid4(), boek_cyclus=0, boekstuknummer=None)


class TestReconcilieerViaPort:
    def test_rapport_met_overgeslagen_en_controle_mislukt(self, administratie_id, monkeypatch) -> None:
        """Eén administratie, drie 'documenten' via een gefakete port: van_toepassing=False → overgeslagen;
        ToetsMislukt → controle_mislukt; bestaat=False → ontbreekt_in_odoo."""
        from app.backends.port import ToetsUitkomst

        docs = [
            _doc(rlz_boekstuknummer="RLZ-04-00002006"),
            _doc(rlz_boekstuknummer=None),
            _doc(rlz_boekstuknummer="BILL/1"),
        ]
        monkeypatch.setattr(reconciliatie, "_geboekte_documenten", lambda aid: docs)

        class Port:
            backend = Backend.ODOO

            def toets_geboekt(self, *, document_id, boek_cyclus, boekstuknummer=None):  # noqa: ANN001
                if boekstuknummer and boekstuknummer.startswith("RLZ-"):
                    return ToetsUitkomst(backend=Backend.ODOO, van_toepassing=False, reden="RLZ-verleden")
                if boekstuknummer is None:
                    raise ToetsMislukt("storing")
                return ToetsUitkomst(backend=Backend.ODOO, bestaat=False, reden="geen Odoo-document bekend")

            def __exit__(self, *exc) -> None:
                return None

        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, port=Port())  # type: ignore[arg-type]
        assert rapport.aantal_gecontroleerd == 3 and rapport.aantal_overgeslagen == 1 and rapport.backend == "odoo"
        assert sorted(a.soort for a in rapport.afwijkingen) == ["controle_mislukt", "ontbreekt_in_odoo"]


@pytest.fixture
def odoo_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boekhoud_backend, doorbelasting_ingeschakeld) "
                "VALUES (:id, 'Steigerbouw (Odoo)', :rlz, 'odoo', true)"
            ),
            {"id": aid, "rlz": f"odoo:test.odoo.com:{uuid.uuid4().int % 100000}"},
        )
    return aid


class TestRlzOnlyBlokkenSlaanOdooOver:
    def test_registry_splitst_per_backend(self, administratie_id, odoo_administratie) -> None:
        rlz, odoo = actieve_administraties_per_backend()
        assert administratie_id in rlz and odoo_administratie in odoo and odoo_administratie not in rlz

    def test_bank_omzet_doorbelasting_markeren_overgeslagen(self, administratie_id, odoo_administratie) -> None:
        bank = bank_reconciliatie.reconcilieer_bank_alle_administraties()
        assert bank[odoo_administratie] == RLZ_ONLY_OVERGESLAGEN
        omzet = omzet_reconciliatie.reconcilieer_alle_omzet()
        assert omzet.overgeslagen == {odoo_administratie: RLZ_ONLY_OVERGESLAGEN}
        assert odoo_administratie not in omzet.fouten
        db = doorbelasting_reconciliatie.reconcilieer_alle_doorbelasting()
        assert db.overgeslagen == {odoo_administratie: RLZ_ONLY_OVERGESLAGEN}
        assert odoo_administratie not in db.fouten
        opruim = doorbelasting_reconciliatie.verzamel_alle_opruimlijsten()
        assert not any(str(odoo_administratie) in f for f in opruim.fouten)

    def test_cli_print_overgeslagen_en_telt_niet_als_fout(self, odoo_administratie, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            cli.bank_reconciliatie,
            "reconcilieer_bank_alle_administraties",
            lambda: {odoo_administratie: RLZ_ONLY_OVERGESLAGEN},
        )
        exit_code = cli._bank_reconciliatie(argparse.Namespace())
        uit = capsys.readouterr().out
        assert exit_code == 0
        assert f"OVERGESLAGEN {odoo_administratie}: {RLZ_ONLY_OVERGESLAGEN}" in uit
        assert "1/1 administraties gecontroleerd" in uit


class TestCliContextVerrijking:
    def test_documenten_detail_draagt_naamvelden(self, monkeypatch, capsys) -> None:
        aid = uuid.uuid4()
        doc = uuid.uuid4()
        afwijking = ReconciliatieAfwijking(
            document_id=doc,
            rlz_document_id=uuid.uuid4(),
            soort="ontbreekt_in_rlz",
            detail="GET PurchaseInvoices/x -> 404",
            context={
                "leverancier_naam": "BOOT organiserend ingenieursburo B.V.",
                "factuurnummer": "202632704",
                "rlz_boekstuk": "RLZ-04-00004038",
                "administratie_naam": "Kempen Facilities B.V.",
                "bedrag_lokaal": "1775.98",
                "bedrag_extern": None,
                "backend": "rlz",
                "extern_id": "guid",
                "extern_state": None,
                "boek_cyclus": "0",
            },
        )
        rapport = ReconciliatieRapport(administratie_id=aid, aantal_gecontroleerd=1, afwijkingen=(afwijking,), aantal_overgeslagen=2)
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {aid: rapport})
        monkeypatch.setattr(cli.acceptatie_service, "uitgesloten_administraties", lambda: {})
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kw: [Beoordeeld(record_id=a[0], soort=a[1], detail=a[2], vingerafdruk="vaf", acceptatie=None) for a in kw["afwijkingen"]],
        )
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok("documenten")
        exit_code = cli._reconciliatie(argparse.Namespace(), verzamelaar=verzamelaar)
        uit = capsys.readouterr().out
        assert exit_code == 1
        assert "(2 niet van toepassing: geboekt in Reeleezee vóór de overstap)" in uit
        [b] = verzamelaar.bevindingen
        assert b.soort == "afwijking" and b.blok == "documenten"
        assert b.detail["afwijking_soort"] == "ontbreekt_in_rlz" and b.detail["document_id"] == str(doc)
        assert b.detail["leverancier_naam"] == "BOOT organiserend ingenieursburo B.V."
        assert b.detail["factuurnummer"] == "202632704" and b.detail["rlz_boekstuk"] == "RLZ-04-00004038"
        assert b.detail["administratie_naam"] == "Kempen Facilities B.V." and b.detail["backend"] == "rlz"
        assert b.detail["bedrag_lokaal"] == "1775.98" and b.detail["bedrag_extern"] is None
