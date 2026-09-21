# ruff: noqa: F811 — pytest-fixtures als parameters
"""CLI `pand-toewijzen` (VGG beslispunt 1, Peter 21-09): mens-toewijzing van het bewijspaar RLZ-01-00000082 aan pand
Schoffelstraat 29 (Purmerend) mét soort `verkoop`. FakeRlz beantwoordt `Receipts?$filter=ReceiptNumber eq '…'`; dry-run
schrijft niets, `--schrijf` maakt pand + pand_boeking (herkomst mens, zekerheid hoog, bevestigd_*), idempotent, ánder
pand = STOP exit 2, audit-rijen mét opdracht/namens; ná de toewijzing geeft `vertaling.pand_telt` True en
`pand_per_document` levert het document mét soort verkoop / herkomst mens. Nameting.sh weigert het commando hard."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import cli
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.migratie import vertaling
from app.panden import service
from app.panden import toewijzen_cli as tc
from app.panden.models import Pand, PandBoeking
from app.rlz import credentials
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parents[3]
BOEKSTUK = "RLZ-01-00000082"
RLZ_ID = uuid.uuid5(uuid.NAMESPACE_URL, "test-vgg-bewijspaar-82")
NOTARIS = {"id": str(uuid.uuid4()), "EntityKind": 1, "Name": "O.N.", "SearchName": "O.N."}


def _receipt(boekstuk: str = BOEKSTUK, *, rlz_id: uuid.UUID = RLZ_ID) -> dict:
    """De productievorm van 21-09 (STAP-0 `stap0-vgg-receipt-82.log`): Receipt € 400.000, 19-03-2026, relatie O.N."""
    return {
        "id": str(rlz_id),
        "BaseInvoiceAmount": 400000.0,
        "TotalPayableAmount": 400000.0,
        "Date": "2026-03-19T00:00:00",
        "ReceiptNumber": boekstuk,
        "Reference": "171384",
        "Status": 3,
        "DocumentType": 10,
        "Entity": NOTARIS,
    }


class FakeRlz:
    """Dict-client: `collecties[pad]` = rijen; alleen `$filter=ReceiptNumber eq '<x>'` wordt begrepen (contract C)."""

    def __init__(self, collecties: dict[str, list[dict]], *, fouten: dict[str, RlzApiError] | None = None) -> None:
        self.collecties = collecties
        self.fouten = fouten or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def for_administration(self, admin_id: str) -> FakeRlz:
        return self

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        if path in self.fouten:
            raise self.fouten[path]
        filter_ = params.get("$filter", "")
        assert filter_.startswith("ReceiptNumber eq '") and filter_.endswith("'"), filter_
        nummer = filter_[len("ReceiptNumber eq '") : -1]
        rijen = [r for r in self.collecties.get(path, []) if r.get("ReceiptNumber") == nummer]
        return {"value": rijen[: int(params.get("$top", 200))]}

    def close(self) -> None:
        self.closed = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    tc.register_pand_toewijzen(parser.add_subparsers(dest="commando"))
    return parser


def _args(*extra: str) -> argparse.Namespace:
    return _parser().parse_args(
        [
            tc.PAND_TOEWIJZEN_COMMANDO,
            "--administratie",
            "Scope-test",
            "--boekstuk",
            BOEKSTUK,
            "--soort",
            "verkoop",
            "--adres",
            "Schoffelstraat 29",
            "--plaats",
            "Purmerend",
            "--dossier",
            "2026.079950.01",
            *extra,
        ]
    )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID) -> FakeRlz:
    client = FakeRlz({"Receipts": [_receipt()], "SalesInvoices": [], "PurchaseInvoices": []})
    monkeypatch.setattr(credentials, "client_voor_rlz_admin_id", lambda rid: client)
    return client


def _panden(aid: uuid.UUID) -> tuple[list[Pand], list[PandBoeking], list[AuditEvent]]:
    with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as s:
        panden = s.scalars(select(Pand).where(Pand.administratie_id == aid)).all()
        boekingen = s.scalars(select(PandBoeking).where(PandBoeking.administratie_id == aid)).all()
        audits = s.scalars(
            select(AuditEvent).where(AuditEvent.administratie_id == aid, AuditEvent.tabel.in_(["pand", "pand_boeking"]))
        ).all()
        s.expunge_all()
        return list(panden), list(boekingen), list(audits)


class TestZoekRlzDocument:
    def test_een_treffer_in_receipts(self) -> None:
        c = FakeRlz({"Receipts": [_receipt()]})
        d = tc.zoek_rlz_document(c, BOEKSTUK)
        assert d.rlz_id == RLZ_ID and d.collectie == "Receipts" and d.boekstuk == BOEKSTUK
        assert d.datum == date(2026, 3, 19) and d.bedrag == Decimal("400000.00") and d.entity_naam == "O.N."
        assert c.calls == [("Receipts", {"$filter": f"ReceiptNumber eq '{BOEKSTUK}'", "$top": 2, "$expand": "Entity"})]

    def test_geen_treffer_is_stop_met_alle_collecties(self) -> None:
        c = FakeRlz({"Receipts": [], "SalesInvoices": [], "PurchaseInvoices": []})
        with pytest.raises(tc.ToewijzingStop, match="niet gevonden .*Receipts 0, SalesInvoices 0, PurchaseInvoices 0"):
            tc.zoek_rlz_document(c, BOEKSTUK)
        assert [p for p, _ in c.calls] == ["Receipts", "SalesInvoices", "PurchaseInvoices"]

    def test_twee_treffers_is_stop_meerduidig(self) -> None:
        c = FakeRlz({"Receipts": [_receipt(), _receipt(rlz_id=uuid.uuid4())]})
        with pytest.raises(tc.ToewijzingStop, match="meerduidig in Receipts \\(2 treffers\\)"):
            tc.zoek_rlz_document(c, BOEKSTUK)

    def test_terugval_naar_salesinvoices(self) -> None:
        c = FakeRlz({"Receipts": [], "SalesInvoices": [_receipt("RLZ-02-00000001")]})
        d = tc.zoek_rlz_document(c, "RLZ-02-00000001")
        assert d.collectie == "SalesInvoices"

    def test_rlz_fout_is_stop_niet_crash(self) -> None:
        c = FakeRlz({"Receipts": []}, fouten={"Receipts": RlzApiError(403, "GET", "Receipts", "geen rechten")})
        with pytest.raises(tc.ToewijzingStop, match="Receipts niet leesbaar \\(403\\)"):
            tc.zoek_rlz_document(c, BOEKSTUK)


class TestPandSleutel:
    def test_zelfde_code_als_de_afleiding(self) -> None:
        s = tc.pand_sleutel("Schoffelstraat 29", "Purmerend", None)
        assert (s.code, s.adres, s.plaats, s.postcode) == ("schoffelstraat-29", "Schoffelstraat 29", "Purmerend", None)
        assert tc.pand_sleutel("Kerkstraat 44A", None, "6711 AB").code == "kerkstraat-44-a"

    def test_onherkenbaar_adres_is_stop(self) -> None:
        with pytest.raises(tc.ToewijzingStop, match="niet als straat \\+ huisnummer herkend"):
            tc.pand_sleutel("Purmerend", None, None)


class TestCli:
    def test_dry_run_schrijft_niets(self, administratie_id: uuid.UUID, fake: FakeRlz, capsys) -> None:  # noqa: ANN001
        assert tc.run_pand_toewijzen(_args()) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN — niets geschreven" in uit and "schoffelstraat-29" in uit and str(RLZ_ID) in uit
        assert "→ nieuw" in uit and "soort verkoop · herkomst mens · zekerheid hoog" in uit
        assert fake.closed is True
        assert _panden(administratie_id) == ([], [], [])

    def test_schrijf_maakt_pand_en_boeking_met_audit(self, administratie_id: uuid.UUID, fake: FakeRlz, capsys) -> None:  # noqa: ANN001
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        assert "GESCHREVEN" in capsys.readouterr().out
        panden, boekingen, audits = _panden(administratie_id)
        (pand,), (rij,) = panden, boekingen
        assert (pand.code, pand.adres, pand.plaats) == ("schoffelstraat-29", "Schoffelstraat 29", "Purmerend")
        assert pand.herkomst == "mens" and pand.status == "verkocht" and pand.verkoopdatum == date(2026, 3, 19)
        assert pand.notaris_dossiernummers == ["2026.079950.01"]
        assert rij.pand_id == pand.id and rij.rlz_document_id == RLZ_ID and rij.bron_sleutel == f"rlz:{RLZ_ID}"
        assert (rij.soort, rij.herkomst, rij.zekerheid) == ("verkoop", "mens", "hoog")
        assert rij.rlz_boekstuknummer == BOEKSTUK and rij.rlz_collectie == "Receipts"
        assert rij.datum == date(2026, 3, 19) and rij.bedrag == Decimal("400000.00")
        assert rij.bevestigd_door == SYSTEEM_ACTOR_ID and rij.bevestigd_op is not None
        assert rij.reden == tc.STANDAARD_REDEN
        assert sorted(a.actie for a in audits) == ["pand_boeking_toegewezen_mens", "pand_toegewezen_mens"]
        boeking_audit = next(a for a in audits if a.tabel == "pand_boeking")
        assert boeking_audit.oude_waarde is None and boeking_audit.record_id == rij.id
        assert boeking_audit.nieuwe_waarde["opdracht"] == tc.OPDRACHT_REFERENTIE
        assert boeking_audit.nieuwe_waarde["namens"] == "P. Nijenhuis (opdracht 21-09)"
        assert boeking_audit.nieuwe_waarde["pand_code"] == "schoffelstraat-29"
        assert boeking_audit.nieuwe_waarde["rlz_document_id"] == str(RLZ_ID)
        assert {a.actor_id for a in audits} == {SYSTEEM_ACTOR_ID}
        assert len({a.correlatie_id for a in audits}) == 1

    def test_idempotent_tweede_run_ongewijzigd(self, administratie_id: uuid.UUID, fake: FakeRlz, capsys) -> None:  # noqa: ANN001
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        capsys.readouterr()
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        uit = capsys.readouterr().out
        assert "→ bestaand" in uit and "→ ongewijzigd" in uit and "audit: geen (ongewijzigd)" in uit
        panden, boekingen, audits = _panden(administratie_id)
        assert len(panden) == 1 and len(boekingen) == 1 and len(audits) == 2

    def test_ander_pand_voor_hetzelfde_document_is_stop(
        self,
        administratie_id: uuid.UUID,
        fake: FakeRlz,
        capsys,  # noqa: ANN001
    ) -> None:
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        capsys.readouterr()
        args = _args("--schrijf")
        args.adres, args.plaats = "Kerkstraat 44", "Ede"
        assert tc.run_pand_toewijzen(args) == 2
        err = capsys.readouterr().err
        assert f"STOP  document {BOEKSTUK} al toegewezen aan schoffelstraat-29 (mens/verkoop) — eerst beoordelen" in err
        panden, boekingen, audits = _panden(administratie_id)
        assert [p.code for p in panden] == ["schoffelstraat-29"] and len(boekingen) == 1 and len(audits) == 2

    def test_voorstel_op_zelfde_pand_wordt_mens_met_audit_oud_nieuw(
        self, administratie_id: uuid.UUID, fake: FakeRlz
    ) -> None:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            pand = Pand(administratie_id=administratie_id, code="schoffelstraat-29", adres="Schoffelstraat 29")
            s.add(pand)
            s.flush()
            s.add(
                PandBoeking(
                    administratie_id=administratie_id,
                    pand_id=pand.id,
                    rlz_document_id=RLZ_ID,
                    rlz_boekstuknummer=BOEKSTUK,
                    rlz_collectie="Receipts",
                    bron_sleutel=f"rlz:{RLZ_ID}",
                    soort="kosten",
                    herkomst="voorstel",
                    zekerheid="laag",
                )
            )
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        panden, boekingen, audits = _panden(administratie_id)
        (pand,), (rij,) = panden, boekingen
        assert (rij.soort, rij.herkomst, rij.zekerheid) == ("verkoop", "mens", "hoog") and rij.bevestigd_op is not None
        # bestaand pand wordt hergebruikt, niet herschreven
        assert pand.status == "voorstel" and pand.herkomst == "afgeleid"
        assert pand.notaris_dossiernummers == ["2026.079950.01"] and pand.verkoopdatum == date(2026, 3, 19)
        b = next(a for a in audits if a.tabel == "pand_boeking")
        assert b.oude_waarde["soort"] == "kosten" and b.nieuwe_waarde["soort"] == "verkoop"
        p = next(a for a in audits if a.tabel == "pand")
        assert p.oude_waarde["notaris_dossiernummers"] == []
        assert p.nieuwe_waarde["notaris_dossiernummers"] == ["2026.079950.01"]

    def test_actor_per_e_mail(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake: FakeRlz) -> None:
        assert tc.run_pand_toewijzen(_args("--schrijf", "--actor", f"{beheerder_id}@TEST.local")) == 0
        _, (rij,), audits = _panden(administratie_id)
        assert rij.bevestigd_door == beheerder_id
        assert {a.actor_id for a in audits} == {beheerder_id} and all("namens" not in a.nieuwe_waarde for a in audits)

    def test_onbekende_actor_is_stop(self, administratie_id: uuid.UUID, fake: FakeRlz, capsys) -> None:  # noqa: ANN001
        assert tc.run_pand_toewijzen(_args("--schrijf", "--actor", "niemand@nergens.test")) == 2
        assert "STOP  actor 'niemand@nergens.test' onbekend" in capsys.readouterr().err
        assert _panden(administratie_id) == ([], [], [])

    def test_boekstuk_niet_gevonden_is_exit_2(self, administratie_id: uuid.UUID, fake: FakeRlz, capsys) -> None:  # noqa: ANN001
        args = _args("--schrijf")
        args.boekstuk = "RLZ-01-99999999"
        assert tc.run_pand_toewijzen(args) == 2
        assert "STOP  boekstuk RLZ-01-99999999 niet gevonden" in capsys.readouterr().err
        assert _panden(administratie_id) == ([], [], [])

    def test_json_uit(self, administratie_id: uuid.UUID, fake: FakeRlz, tmp_path: pathlib.Path) -> None:
        import json

        pad = tmp_path / "uit.json"
        assert tc.run_pand_toewijzen(_args("--json-uit", str(pad))) == 0
        data = json.loads(pad.read_text(encoding="utf-8"))
        assert data["document"]["rlz_id"] == str(RLZ_ID) and data["schrijf"] is False
        assert data["pand"]["code"] == "schoffelstraat-29"

    def test_dispatch_via_main_en_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gezien: list[argparse.Namespace] = []
        monkeypatch.setattr(cli, "run_pand_toewijzen", lambda args: gezien.append(args) or 0)
        basis = ["--administratie", "VGG", "--boekstuk", BOEKSTUK, "--soort", "verkoop", "--adres", "Schoffelstraat 29"]
        assert cli.main([tc.PAND_TOEWIJZEN_COMMANDO, *basis]) == 0
        a = gezien[0]
        assert a.schrijf is False and a.actor is None and a.reden == tc.STANDAARD_REDEN and a.plaats is None
        assert cli.main([tc.PAND_TOEWIJZEN_COMMANDO, *basis, "--schrijf", "--actor", "p@x.nl"]) == 0
        assert gezien[1].schrijf is True and gezien[1].actor == "p@x.nl"
        with pytest.raises(SystemExit):
            cli.main([tc.PAND_TOEWIJZEN_COMMANDO, *basis[:-2], "--soort", "onzin"])

    def test_nameting_sh_weigert_hard(self) -> None:
        script = REPO / "scripts" / "gcp" / "nameting.sh"
        tekst = script.read_text(encoding="utf-8")
        assert tc.PAND_TOEWIJZEN_COMMANDO not in next(r for r in tekst.splitlines() if r.startswith("ALLOWLIST="))
        uitkomst = subprocess.run(
            ["bash", str(script), tc.PAND_TOEWIJZEN_COMMANDO, "--administratie", "VGG", "--boekstuk", BOEKSTUK],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "NAMETING_ENV": "/nonexistent/nameting.env"},
        )
        assert uitkomst.returncode == 2
        assert f"FOUT: {tc.PAND_TOEWIJZEN_COMMANDO} is een schrijvend commando" in uitkomst.stderr


class TestVertaling:
    """Contract C: ná de toewijzing telt het pand in de vertaling (herkomst mens) en levert `pand_per_document` het
    RLZ-id mét soort verkoop — precies wat de rol 803100 in `vertaling` nodig heeft (`pand_telt` + soort)."""

    def test_pand_per_document_en_pand_telt(self, administratie_id: uuid.UUID, fake: FakeRlz) -> None:
        assert service.pand_per_document(administratie_id) == {}
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        per_doc = service.pand_per_document(administratie_id)
        assert set(per_doc) == {RLZ_ID}
        t = per_doc[RLZ_ID]
        assert (t.pand_code, t.adres, t.soort, t.zekerheid, t.herkomst) == (
            "schoffelstraat-29",
            "Schoffelstraat 29",
            "verkoop",
            "hoog",
            "mens",
        )
        geladen = vertaling.laad_panden(administratie_id)
        assert vertaling.pand_telt(geladen[RLZ_ID]) is True and geladen[RLZ_ID].soort == "verkoop"
        assert vertaling.ROL_PER_SOORT["verkoop"] == "opbrengst_panden"  # de rol die 803100 draagt

    def test_mens_wint_van_een_later_voorstel(self, administratie_id: uuid.UUID, fake: FakeRlz) -> None:
        assert tc.run_pand_toewijzen(_args("--schrijf")) == 0
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            ander = Pand(administratie_id=administratie_id, code="kerkstraat-44", adres="Kerkstraat 44")
            s.add(ander)
            s.flush()
            s.add(
                PandBoeking(
                    administratie_id=administratie_id,
                    pand_id=ander.id,
                    rlz_document_id=RLZ_ID,
                    rlz_boekstuknummer=BOEKSTUK,
                    bron_sleutel=f"rlz:{RLZ_ID}",
                    soort="kosten",
                    herkomst="voorstel",
                    zekerheid="hoog",
                )
            )
        t = service.pand_per_document(administratie_id)[RLZ_ID]
        assert (t.pand_code, t.soort, t.herkomst) == ("schoffelstraat-29", "verkoop", "mens")
