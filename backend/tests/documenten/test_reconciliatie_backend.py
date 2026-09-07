# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Documenten-reconciliatie backend-agnostisch (A12, fixrun 07-09):

- Odoo-port-toets met gefakete client: posted zonder reversal = groen; draft/cancel = niet_geboekt_in_odoo; ONBEKENDE
  reversal = teruggedraaid_in_odoo, maar onze EIGEN tegenboeking (odoo_document_koppeling) níét; amount_total ≠ eigen
  totaal = bedrag_wijkt_af; move verdwenen / geen koppeling+marker = ontbreekt_in_odoo; OdooFout = controle_mislukt;
- RLZ-VERLEDEN (besluit Peter 07-09 op A12 beslispunt 1, blok 4 vervolgrun): in één Odoo-administratie gaat een
  document mét Odoo-koppeling naar de Odoo-port en een `RLZ-…`-document zónder Odoo-spoor naar een RLZ-port op de
  bewaarde credential (`client_voor_rlz_verleden`); ontbreekt het daar = `ontbreekt_in_rlz`; geen bewaarde
  credential = zichtbare `controle_mislukt` "RLZ-verleden niet toetsbaar …" per document; tellingen in rapport + CLI;
- bank/omzet/doorbelasting blijven RLZ-only: een Odoo-administratie wordt zichtbaar OVERGESLAGEN (CLI-regel), nooit
  als fout geteld;
- de CLI zet de naam-context op élke documenten-afwijking (contract A↔A8)."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.backends.port import Backend, ToetsMislukt
from app.backends.registry import RLZ_ONLY_OVERGESLAGEN, actieve_administraties_per_backend
from app.backends.rlz_inkoop import RlzInkoopPort
from app.bank import reconciliatie as bank_reconciliatie
from app.db.models import RlzCredential
from app.db.session import scoped_session
from app.documenten import reconciliatie
from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport
from app.documenten.rlz_ids import rlz_herboeking_id
from app.doorbelasting import reconciliatie as doorbelasting_reconciliatie
from app.odoo.client import OdooFout
from app.odoo.credentials import OdooVerbinding
from app.odoo.inkoop import OdooInkoopPort
from app.odoo.models import OdooDocumentKoppeling
from app.omzet import reconciliatie as omzet_reconciliatie
from app.reconciliatie import run as run_service
from app.reconciliatie import teksten
from app.reconciliatie.service import Beoordeeld
from app.rlz.credentials import RLZ_VERLEDEN_NIET_TOETSBAAR, GeenRlzCredentials, client_voor_rlz_verleden
from app.security.envelope import wrap_secret
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_duplicaat_historie import _maak_overgestapt
from tests.documenten.test_reconciliatie import _boek_een_document

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
        self.gelezen: list[int] = []

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        if self.faal:
            raise OdooFout(500, "InternalError", "storing (simulatie)", model=model, methode="read")
        self.gelezen.append(int(odoo_id))
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
    def test_rapport_met_overgeslagen_controle_mislukt_en_rlz_verleden(self, administratie_id, monkeypatch) -> None:
        """Eén Odoo-administratie, vier 'documenten': `RLZ-…` zonder Odoo-spoor → de RLZ-verleden-port (07-09, besluit
        Peter — niet meer overgeslagen); een port die van_toepassing=False geeft → overgeslagen (échte n.v.t.);
        ToetsMislukt → controle_mislukt; bestaat=False → ontbreekt_in_odoo."""
        from app.backends.port import ToetsUitkomst

        docs = [
            _doc(rlz_boekstuknummer="RLZ-04-00002006"),
            _doc(rlz_boekstuknummer="NVT/1"),
            _doc(rlz_boekstuknummer=None),
            _doc(rlz_boekstuknummer="BILL/1"),
        ]
        monkeypatch.setattr(reconciliatie, "_geboekte_documenten", lambda aid: docs)
        odoo_gezien: list[str | None] = []
        rlz_gezien: list[str | None] = []

        class Port:
            backend = Backend.ODOO

            def toets_geboekt(self, *, document_id, boek_cyclus, boekstuknummer=None):  # noqa: ANN001
                odoo_gezien.append(boekstuknummer)
                if boekstuknummer and boekstuknummer.startswith("NVT/"):
                    return ToetsUitkomst(backend=Backend.ODOO, van_toepassing=False, reden="niets te toetsen")
                if boekstuknummer is None:
                    raise ToetsMislukt("storing")
                return ToetsUitkomst(backend=Backend.ODOO, bestaat=False, reden="geen Odoo-document bekend")

            def __exit__(self, *exc) -> None:
                return None

        class VerledenPort:
            backend = Backend.RLZ
            gesloten = False

            def toets_geboekt(self, *, document_id, boek_cyclus, boekstuknummer=None):  # noqa: ANN001
                rlz_gezien.append(boekstuknummer)
                return ToetsUitkomst(backend=Backend.RLZ, bestaat=False, reden="GET -> 404")

            def __exit__(self, *exc) -> None:
                self.gesloten = True

        verleden = VerledenPort()
        rapport = reconciliatie.reconcilieer_administratie(
            administratie_id=administratie_id, port=Port(), rlz_verleden_port_factory=lambda aid: verleden  # type: ignore[arg-type]
        )
        assert rapport.aantal_gecontroleerd == 4 and rapport.aantal_overgeslagen == 1 and rapport.backend == "odoo"
        assert rapport.aantal_in_odoo == 3 and rapport.aantal_in_rlz_verleden == 1
        assert sorted(a.soort for a in rapport.afwijkingen) == ["controle_mislukt", "ontbreekt_in_odoo", "ontbreekt_in_rlz"]
        assert odoo_gezien == ["NVT/1", None, "BILL/1"] and rlz_gezien == ["RLZ-04-00002006"]
        assert verleden.gesloten
        [verleden_afwijking] = [a for a in rapport.afwijkingen if a.soort == "ontbreekt_in_rlz"]
        assert verleden_afwijking.context["backend"] == "rlz" and verleden_afwijking.context["rlz_verleden"] == "true"


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
        rapport = ReconciliatieRapport(
            administratie_id=aid, aantal_gecontroleerd=1, afwijkingen=(afwijking,), aantal_overgeslagen=2, backend="odoo",
            aantal_in_odoo=1, aantal_in_rlz_verleden=0,
        )
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
        assert "(1 getoetst in Odoo, 0 in Reeleezee-verleden) (2 niet van toepassing: niets te toetsen in deze backend)" in uit
        [b] = verzamelaar.bevindingen
        assert b.soort == "afwijking" and b.blok == "documenten"
        assert b.detail["afwijking_soort"] == "ontbreekt_in_rlz" and b.detail["document_id"] == str(doc)
        assert b.detail["leverancier_naam"] == "BOOT organiserend ingenieursburo B.V."
        assert b.detail["factuurnummer"] == "202632704" and b.detail["rlz_boekstuk"] == "RLZ-04-00004038"
        assert b.detail["administratie_naam"] == "Kempen Facilities B.V." and b.detail["backend"] == "rlz"
        assert b.detail["bedrag_lokaal"] == "1775.98" and b.detail["bedrag_extern"] is None


# ---- RLZ-verleden van een overgestapte administratie (besluit Peter 07-09, A12 beslispunt 1) ----------------------


def _leg_rlz_credential_vast(administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    ciphertext, wrapped = wrap_secret(b"rlz-wachtwoord")
    with scoped_session(None, actor_id=beheerder_id) as session:
        session.add(
            RlzCredential(
                administratie_id=administratie_id,
                webservice_username="ws-testadmin",
                wachtwoord_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                aangemaakt_door=beheerder_id,
            )
        )


def _oud_rlz_id(admin_engine: Engine, administratie_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT rlz_admin_id_voor_overstap FROM platform.odoo_koppeling WHERE administratie_id = :id"),
            {"id": administratie_id},
        ).scalar_one()


class _RlzMetSpoor(FakeBoekClient):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.paden: list[str] = []

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.paden.append(path)
        return super().get(path, params=params)


def _leesbaar(a: ReconciliatieAfwijking) -> teksten.Leesbaar:
    detail = cli._afwijking_detail(
        "documenten",
        Beoordeeld(record_id=a.document_id, soort=a.soort, detail=a.detail, vingerafdruk="vaf", acceptatie=None),
        None,
        document_id=a.document_id,
        **a.context,
    )
    return teksten.leesbaar(SimpleNamespace(blok="documenten", soort="afwijking", tekst="", detail=detail, vingerafdruk="vaf"))


class TestRlzVerleden:
    @pytest.fixture
    def overgestapt(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch, admin_engine: Engine
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Eén administratie mét twee GEBOEKTE documenten, daarna overgestapt naar Odoo: `doc_rlz` houdt zijn
        `RLZ-…`-boekstuk zonder Odoo-spoor (RLZ-verleden), `doc_odoo` krijgt een odoo_document_koppeling + BILL-boekstuk."""
        kw = dict(
            gescoopte_gebruiker=gescoopte_gebruiker, administratie_id=administratie_id, opslag=opslag,
            beheerder_id=beheerder_id, monkeypatch=monkeypatch,
        )
        doc_rlz = _boek_een_document(**kw)
        doc_odoo = _boek_een_document(**kw)
        _maak_overgestapt(admin_engine, administratie_id, beheerder_id)
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                OdooDocumentKoppeling(
                    administratie_id=administratie_id, document_id=doc_odoo, boek_cyclus=0, soort="boeking",
                    odoo_move_id=3101, odoo_naam="BILL/2026/09/3101", odoo_move_type="in_invoice", company_id=COMPANY,
                    state="posted",
                )
            )
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.boekvoorstel SET rlz_boekstuknummer = 'BILL/2026/09/3101' WHERE document_id = :id"),
                {"id": doc_odoo},
            )
        return doc_rlz, doc_odoo

    def test_geboekte_documenten_dragen_odoo_spoor_en_routeren(self, overgestapt, administratie_id) -> None:
        doc_rlz, doc_odoo = overgestapt
        per_id = {d.document_id: d for d in reconciliatie._geboekte_documenten(administratie_id)}
        assert per_id[doc_odoo].heeft_odoo_koppeling and not reconciliatie.is_rlz_verleden(per_id[doc_odoo])
        assert not per_id[doc_rlz].heeft_odoo_koppeling and reconciliatie.is_rlz_verleden(per_id[doc_rlz])
        assert per_id[doc_rlz].rlz_boekstuknummer.startswith("RLZ-")

    def test_odoo_document_naar_odoo_port_rlz_verleden_naar_rlz_port_alles_groen(
        self, overgestapt, administratie_id
    ) -> None:
        doc_rlz, doc_odoo = overgestapt
        fake_odoo = _FakeOdoo({3101: _move(3101)})
        rlz_id = rlz_herboeking_id(doc_rlz, 0)
        fake_rlz = _RlzMetSpoor(
            bestaande_invoices={str(rlz_id): {"Status": 3, "ReceiptNumber": "RLZ-TEST-00001", "BaseInvoiceAmount": 121.0}}
        )
        factory_aanroepen: list[uuid.UUID] = []

        def factory(aid: uuid.UUID) -> RlzInkoopPort:
            factory_aanroepen.append(aid)
            return RlzInkoopPort(fake_rlz)  # type: ignore[arg-type]

        rapport = reconciliatie.reconcilieer_administratie(
            administratie_id=administratie_id, port=_port(administratie_id, fake_odoo), rlz_verleden_port_factory=factory
        )
        assert rapport.afwijkingen == ()
        assert rapport.backend == "odoo" and rapport.aantal_gecontroleerd == 2
        assert rapport.aantal_in_odoo == 1 and rapport.aantal_in_rlz_verleden == 1 and rapport.aantal_overgeslagen == 0
        # Elke port zag precies zijn eigen document.
        assert fake_odoo.gelezen == [3101]
        assert fake_rlz.paden == [f"PurchaseInvoices/{rlz_id}"]
        assert factory_aanroepen == [administratie_id] and fake_rlz.gesloten

    def test_rlz_verleden_verdwenen_in_rlz_is_ontbreekt_in_rlz_met_reeleezee_tekst(
        self, overgestapt, administratie_id
    ) -> None:
        doc_rlz, _ = overgestapt
        fake_rlz = _RlzMetSpoor()  # niets bekend in RLZ
        rapport = reconciliatie.reconcilieer_administratie(
            administratie_id=administratie_id,
            port=_port(administratie_id, _FakeOdoo({3101: _move(3101)})),
            rlz_verleden_port_factory=lambda aid: RlzInkoopPort(fake_rlz),  # type: ignore[arg-type]
        )
        [a] = rapport.afwijkingen
        assert a.soort == "ontbreekt_in_rlz" and a.document_id == doc_rlz
        assert a.context["backend"] == "rlz" and a.context["rlz_verleden"] == "true"
        assert a.context["rlz_boekstuk"] == "RLZ-TEST-00001"
        lb = _leesbaar(a)
        assert lb.titel.startswith("RLZ-document verdwenen") and "in RLZ bestaat het boekstuk niet meer" in lb.wat
        assert "vóór de overstap" in lb.wat and not lb.titel.startswith("Odoo")
        assert ("systeem", "rlz") in lb.details

    def test_zonder_bewaarde_credential_is_controle_mislukt_zichtbaar_per_document(
        self, overgestapt, administratie_id
    ) -> None:
        """Default-factory (geen test-seam): geen rlz_credential-rij en geen .env-prefix voor het oude id →
        GeenRlzCredentials → één zichtbare controle_mislukt per verleden-document, het Odoo-document blijft groen."""
        doc_rlz, _ = overgestapt
        fake_odoo = _FakeOdoo({3101: _move(3101)})
        rapport = reconciliatie.reconcilieer_administratie(
            administratie_id=administratie_id, port=_port(administratie_id, fake_odoo)
        )
        [a] = rapport.afwijkingen
        assert a.soort == "controle_mislukt" and a.document_id == doc_rlz
        assert a.detail.startswith(RLZ_VERLEDEN_NIET_TOETSBAAR)
        assert a.context["backend"] == "rlz" and a.context["rlz_verleden"] == "true"
        assert rapport.aantal_in_rlz_verleden == 1 and rapport.aantal_in_odoo == 1 and rapport.aantal_overgeslagen == 0
        assert fake_odoo.gelezen == [3101]
        lb = _leesbaar(a)
        assert lb.titel.startswith("Reeleezee-verleden niet controleerbaar")
        assert "geen bewaarde Reeleezee-login" in lb.wat and "Odoo gaf" not in lb.wat
        assert "webservice-login" in lb.doe

    def test_client_voor_rlz_verleden_gebruikt_bewaarde_credential_op_het_oude_id(
        self, overgestapt, administratie_id, beheerder_id, admin_engine: Engine
    ) -> None:
        _leg_rlz_credential_vast(administratie_id, beheerder_id)
        oud = _oud_rlz_id(admin_engine, administratie_id)
        assert oud.startswith("rlz-")  # het fixture-id van vóór de overstap, niet de Odoo-sentinel
        client = client_voor_rlz_verleden(administratie_id)
        try:
            assert client._path("PurchaseInvoices/x") == f"/{oud}/PurchaseInvoices/x"
        finally:
            client.close()

    def test_client_voor_rlz_verleden_zonder_credential_of_zonder_oud_id_is_fail_loud(
        self, overgestapt, administratie_id, admin_engine: Engine
    ) -> None:
        with pytest.raises(GeenRlzCredentials, match="geen bewaarde RLZ-credential"):
            client_voor_rlz_verleden(administratie_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.odoo_koppeling SET rlz_admin_id_voor_overstap = NULL WHERE administratie_id = :id"),
                {"id": administratie_id},
            )
        with pytest.raises(GeenRlzCredentials, match="geen bewaard RLZ-administratie-id"):
            client_voor_rlz_verleden(administratie_id)

    def test_default_factory_opent_rlz_port_op_de_verleden_client(
        self, overgestapt, administratie_id, beheerder_id, monkeypatch
    ) -> None:
        """Zonder seam loopt het productiepad: `client_voor_rlz_verleden(administratie_id)` → RlzInkoopPort."""
        doc_rlz, _ = overgestapt
        _leg_rlz_credential_vast(administratie_id, beheerder_id)
        rlz_id = rlz_herboeking_id(doc_rlz, 0)
        fake_rlz = _RlzMetSpoor(
            bestaande_invoices={str(rlz_id): {"Status": 2, "ReceiptNumber": "RLZ-TEST-00001", "BaseInvoiceAmount": 121.0}}
        )
        gevraagd: list[uuid.UUID] = []

        def fake_client_voor_rlz_verleden(aid: uuid.UUID) -> _RlzMetSpoor:
            gevraagd.append(aid)
            return fake_rlz

        monkeypatch.setattr(reconciliatie, "client_voor_rlz_verleden", fake_client_voor_rlz_verleden)
        rapport = reconciliatie.reconcilieer_administratie(
            administratie_id=administratie_id, port=_port(administratie_id, _FakeOdoo({3101: _move(3101)}))
        )
        assert rapport.afwijkingen == () and gevraagd == [administratie_id]
        assert fake_rlz.paden == [f"PurchaseInvoices/{rlz_id}"] and fake_rlz.gesloten

    def test_cli_regel_toont_verdeling_odoo_en_reeleezee_verleden(self, monkeypatch, capsys) -> None:
        aid = uuid.uuid4()
        rapport = ReconciliatieRapport(
            administratie_id=aid, aantal_gecontroleerd=9, afwijkingen=(), backend="odoo",
            aantal_in_odoo=3, aantal_in_rlz_verleden=6,
        )
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {aid: rapport})
        monkeypatch.setattr(cli.acceptatie_service, "uitgesloten_administraties", lambda: {})
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        exit_code = cli._reconciliatie(argparse.Namespace())
        uit = capsys.readouterr().out
        assert exit_code == 0
        assert f"OK         {aid}: 9 gecontroleerd, geen afwijkingen (3 getoetst in Odoo, 6 in Reeleezee-verleden)" in uit
        assert "niet van toepassing" not in uit

    def test_rlz_administratie_regel_ongewijzigd(self, monkeypatch, capsys) -> None:
        aid = uuid.uuid4()
        rapport = ReconciliatieRapport(administratie_id=aid, aantal_gecontroleerd=4, afwijkingen=())
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {aid: rapport})
        monkeypatch.setattr(cli.acceptatie_service, "uitgesloten_administraties", lambda: {})
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        cli._reconciliatie(argparse.Namespace())
        uit = capsys.readouterr().out
        assert f"OK         {aid}: 4 gecontroleerd, geen afwijkingen\n" in uit
