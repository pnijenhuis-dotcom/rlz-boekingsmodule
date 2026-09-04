"""Boekdatum-verschuiving Odoo (slotstuk 04-09, blok A2 — live bewijs company 1: Odoo weigert een factuurdatum in een
vergrendelde periode NIET maar verschuift `date` stil naar het maandeinde). Wij bepalen de boekdatum zelf:

- puur (`fouten.bepaal_boekdatum`): geen lock geraakt = factuurdatum; op de lock date zelf = verschoven (inclusief);
  dag erna niet; meerdere locks → hoogste + 1 dag; None-locks tellen niet; leesbare reden mét label + datums;
- adapter (`OdooInkoopPort.boek_inkoopfactuur` met fake client): create-vals dragen `date` = verschoven boekdatum en
  `invoice_date` = factuurdatum; detail `boekdatum_verschoven {van, naar, lock_veld, lock_datum, reden}` alleen bij
  verschuiving; post-write: Odoo-`date` ≠ ons besluit → `detail["waarschuwing"]`, boeking staat (geen raise);
  concept-verversen op een hergebruikt draft krijgt dezelfde boekdatum; de tegenboeking houdt de lock-WEIGERING;
- "Geboekt in Odoo": `boekdatum_verschoven_regel` uit het GEBOEKT-detail + DTO-veld additief (RLZ = None)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.backends.port import BackendBoekFout
from app.documenten.boekvoorstel import BoekvoorstelData
from app.documenten.geboekt_in_rlz import GeboektInRlz, boekdatum_verschoven_regel
from app.documenten.schemas import GeboektInRlzDto
from app.odoo import inkoop
from app.odoo.credentials import OdooVerbinding
from app.odoo.fouten import LOCK_LABELS, BoekdatumBesluit, bepaal_boekdatum, lock_date_melding
from app.odoo.inkoop import OdooInkoopPort, _Regel

LOCK_2025 = {
    "fiscalyear_lock_date": date(2025, 12, 31),
    "tax_lock_date": date(2025, 12, 31),
    "purchase_lock_date": None,
    "hard_lock_date": None,
}


class TestBepaalBoekdatumPuur:
    def test_geen_lock_geraakt_boekdatum_is_factuurdatum(self) -> None:
        b = bepaal_boekdatum(factuurdatum=date(2026, 3, 5), lock_dates=LOCK_2025)
        assert b == BoekdatumBesluit(
            boekdatum=date(2026, 3, 5), verschoven_van=None, lock_veld=None, lock_datum=None, reden=None
        )
        assert not b.verschoven

    def test_op_de_lock_date_zelf_is_verschoven_dag_erna_niet(self) -> None:
        op = bepaal_boekdatum(factuurdatum=date(2025, 12, 31), lock_dates=LOCK_2025)
        assert op.verschoven and op.boekdatum == date(2026, 1, 1) and op.verschoven_van == date(2025, 12, 31)
        erna = bepaal_boekdatum(factuurdatum=date(2026, 1, 1), lock_dates=LOCK_2025)
        assert not erna.verschoven and erna.boekdatum == date(2026, 1, 1)

    def test_live_geval_a2_15_12_2025_wordt_01_01_2026(self) -> None:
        b = bepaal_boekdatum(factuurdatum=date(2025, 12, 15), lock_dates=LOCK_2025)
        assert b.boekdatum == date(2026, 1, 1) and b.verschoven_van == date(2025, 12, 15)
        assert b.lock_veld in ("fiscalyear_lock_date", "tax_lock_date") and b.lock_datum == date(2025, 12, 31)
        assert b.reden == (
            f"Factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode ({LOCK_LABELS[b.lock_veld]} t/m "
            "31-12-2025; btw-aangifte al gedaan) — boekdatum verschoven naar 01-01-2026, factuurdatum ongewijzigd"
        )

    def test_meerdere_locks_hoogste_wint(self) -> None:
        locks = {
            "fiscalyear_lock_date": date(2025, 12, 31),
            "tax_lock_date": date(2026, 3, 31),
            "purchase_lock_date": date(2026, 1, 31),
            "hard_lock_date": None,
        }
        b = bepaal_boekdatum(factuurdatum=date(2026, 1, 10), lock_dates=locks)
        assert b.boekdatum == date(2026, 4, 1) and b.lock_veld == "tax_lock_date" and b.lock_datum == date(2026, 3, 31)
        assert "btw-lock date t/m 31-03-2026" in (b.reden or "")
        # Alleen de locks die de factuurdatum écht raken tellen: factuurdatum ná de btw-lock, vóór niets anders.
        b2 = bepaal_boekdatum(factuurdatum=date(2026, 4, 15), lock_dates=locks)
        assert not b2.verschoven

    def test_alle_locks_none_of_leeg_geen_verschuiving(self) -> None:
        assert not bepaal_boekdatum(factuurdatum=date(2020, 1, 1), lock_dates={"hard_lock_date": None}).verschoven
        assert not bepaal_boekdatum(factuurdatum=date(2020, 1, 1), lock_dates={}).verschoven

    def test_tegenboek_poort_blijft_weigeren(self) -> None:
        """De reversal (boekdatum vandaag) behoudt de leesbare WEIGERING — geen stille verschuiving van correcties."""
        assert lock_date_melding(boekdatum=date(2025, 12, 31), lock_dates=LOCK_2025) is not None
        assert lock_date_melding(boekdatum=date(2026, 1, 1), lock_dates=LOCK_2025) is None


# --------------------------------------------------------------------------- adapter met fake client


class _FakeOdoo:
    """Minimale account.move-simulatie: create → read_een; action_post zet posted en (optioneel) een afwijkende
    `date` — het live A2-gedrag "Odoo verschuift stil naar het maandeinde" als `odoo_datum_override` gezet is."""

    company_id = 1

    def __init__(self, *, lock_dates: dict[str, date | None], odoo_datum_override: str | None = None) -> None:
        self.lock_dates = lock_dates
        self.odoo_datum_override = odoo_datum_override
        self.creates: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, list[int], dict]] = []
        self.calls: list[tuple[str, str]] = []
        self.moves: dict[int, dict[str, Any]] = {}
        self._volgende = 3049

    def read_een(self, model: str, rid: int, velden: list[str]) -> dict | None:
        if model == "res.company":
            return {k: (v.isoformat() if v else False) for k, v in self.lock_dates.items()}
        return dict(self.moves.get(rid)) if rid in self.moves else None

    def create(self, model: str, vals: dict) -> int:
        self.creates.append((model, vals))
        if model != inkoop.MODEL_MOVE:
            return 900
        mid = self._volgende
        self._volgende += 1
        self.moves[mid] = {
            "id": mid,
            "name": "/",
            "state": "draft",
            "payment_state": "not_paid",
            "company_id": [1, "Universal Steigerbouw"],
            "partner_id": [vals["partner_id"], "Leverancier"],
            "amount_total": 121.0,
            "amount_residual": 121.0,
            "date": vals["date"],
            "invoice_date": vals["invoice_date"],
            "ref": vals.get("ref"),
            "invoice_origin": vals.get("invoice_origin"),
            "move_type": "in_invoice",
        }
        return mid

    def search_read(self, model: str, domain: list, velden: list[str], **kw: Any) -> list[dict]:
        return []  # geen bestaande marker-move, geen tax-regels, geen bestaande bijlage

    def write(self, model: str, ids: list[int], vals: dict) -> None:
        self.writes.append((model, ids, vals))
        if model == inkoop.MODEL_MOVE:
            for mid in ids:
                self.moves[mid].update({k: v for k, v in vals.items() if k in ("date", "invoice_date", "ref")})

    def call(self, model: str, methode: str, *, ids: list[int], **kw: Any) -> Any:
        self.calls.append((model, methode))
        if methode == "action_post":
            for mid in ids:
                self.moves[mid]["state"] = "posted"
                self.moves[mid]["name"] = "BILL/2026/01/0001"
                if self.odoo_datum_override:
                    self.moves[mid]["date"] = self.odoo_datum_override
        return None

    def close(self) -> None:
        return None


def _voorstel(factuurdatum: date) -> BoekvoorstelData:
    return BoekvoorstelData(
        document_id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        referentie="F-2025-1215",
        factuurdatum=factuurdatum,
        totaalbedrag=Decimal("121.00"),
        rlz_boekstuknummer=None,
        opgeslagen=True,
        regels=[],
    )


def _port(monkeypatch: pytest.MonkeyPatch, client: _FakeOdoo) -> OdooInkoopPort:
    verbinding = OdooVerbinding(
        administratie_id=uuid.uuid4(),
        odoo_url="https://x.odoo.com",
        company_id=1,
        company_naam="Universal Steigerbouw",
        journal_purchase_id=7,
        journal_general_id=8,
        journal_sale_id=9,
        analytic_plan_id=2,
        overgangsdatum=date(2026, 9, 1),
    )
    port = OdooInkoopPort(verbinding.administratie_id, verbinding, client=client)  # type: ignore[arg-type]
    regel = _Regel(
        naam="Diesel",
        account_id=11,
        tax_id=21,
        netto=Decimal("100.00"),
        btw=Decimal("21.00"),
        analytic_account_id=None,
        product_id=None,
        quantity=Decimal("1"),
        price_unit=Decimal("100.00"),
        product_uom_id=None,
    )
    # DB-rakende stappen (id-mapping, koppelingsrij, bijlage) buiten de test — de boekdatum-logica is het onderwerp.
    monkeypatch.setattr(port, "partner_id_voor", lambda vendor_id: 5)
    monkeypatch.setattr(port, "_vertaal_regels", lambda document_id, voorstel: [regel])
    monkeypatch.setattr(port, "_verlegde_taxrates", lambda: set())
    monkeypatch.setattr(port, "_odoo_id", lambda model, lokaal_id: 21)
    monkeypatch.setattr(port, "_leg_koppeling_vast", lambda **kw: None)
    monkeypatch.setattr(port, "_bestaande_move", lambda document_id, boek_cyclus, soort: None)
    monkeypatch.setattr(port, "_zorg_voor_bijlage", lambda move_id, bestand, naam: "aanwezig (1)")
    return port


class TestAdapterBoekdatum:
    def test_factuur_in_afgesloten_periode_boekt_met_verschoven_date_en_zichtbaar_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _FakeOdoo(lock_dates=LOCK_2025)
        port = _port(monkeypatch, client)
        voorstel = _voorstel(date(2025, 12, 15))
        uitkomst = port.boek_inkoopfactuur(
            document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf"
        )
        [(model, vals)] = client.creates
        assert model == inkoop.MODEL_MOVE
        assert vals["invoice_date"] == "2025-12-15" and vals["date"] == "2026-01-01"  # nooit Odoo's maandeinde
        assert uitkomst.boekstuknummer == "BILL/2026/01/0001"
        d = uitkomst.detail
        assert d["boekdatum_verschoven"] == {
            "van": "2025-12-15",
            "naar": "2026-01-01",
            "lock_veld": d["boekdatum_verschoven"]["lock_veld"],
            "lock_datum": "2025-12-31",
            "reden": d["boekdatum_verschoven"]["reden"],
        }
        assert d["boekdatum_verschoven"]["lock_veld"] in ("fiscalyear_lock_date", "tax_lock_date")
        assert "verschoven naar 01-01-2026" in d["boekdatum_verschoven"]["reden"]
        assert "waarschuwing" not in d and d["odoo_boekdatum"] == "2026-01-01"

    def test_factuur_in_open_periode_geen_verschuiving_geen_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _FakeOdoo(lock_dates=LOCK_2025)
        port = _port(monkeypatch, client)
        voorstel = _voorstel(date(2026, 6, 5))
        uitkomst = port.boek_inkoopfactuur(
            document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf"
        )
        [(_, vals)] = client.creates
        assert vals["date"] == vals["invoice_date"] == "2026-06-05"
        assert "boekdatum_verschoven" not in uitkomst.detail and "waarschuwing" not in uitkomst.detail

    def test_odoo_zet_toch_een_andere_datum_zichtbare_waarschuwing_boeking_staat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live A2-gedrag: zou Odoo ons `date` alsnog naar het maandeinde schuiven, dan is dat een waarschuwing op de
        boeking (die stáát in Odoo) — nooit een stil verschil, nooit een boeken_mislukt op een geposte boeking."""
        client = _FakeOdoo(lock_dates=LOCK_2025, odoo_datum_override="2026-01-31")
        port = _port(monkeypatch, client)
        voorstel = _voorstel(date(2025, 12, 15))
        uitkomst = port.boek_inkoopfactuur(
            document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf"
        )
        assert uitkomst.detail["boekdatum_verschoven"]["naar"] == "2026-01-01"
        assert (
            "Odoo zette de boekdatum op 2026-01-31 i.p.v. de door ons bepaalde 2026-01-01"
            in (uitkomst.detail["waarschuwing"])
        )
        assert uitkomst.detail["odoo_boekdatum"] == "2026-01-31"

    def test_bijlage_waarschuwing_overschrijft_boekdatum_waarschuwing_niet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _FakeOdoo(lock_dates=LOCK_2025, odoo_datum_override="2026-01-31")
        port = _port(monkeypatch, client)

        def kapot(move_id, bestand, naam):
            raise RuntimeError("upload kapot")

        monkeypatch.setattr(port, "_zorg_voor_bijlage", kapot)
        voorstel = _voorstel(date(2025, 12, 15))
        uitkomst = port.boek_inkoopfactuur(
            document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf"
        )
        w = uitkomst.detail["waarschuwing"]
        assert "Odoo zette de boekdatum" in w and "bijlage niet gekoppeld" in w

    def test_hergebruikt_concept_krijgt_dezelfde_verschoven_boekdatum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Een achtergebleven concept (eerdere poging) wordt ververst mét het actuele boekdatum-besluit."""
        client = _FakeOdoo(lock_dates=LOCK_2025)
        port = _port(monkeypatch, client)
        voorstel = _voorstel(date(2025, 12, 15))
        # Concept van een eerdere poging, mét de toen (foute) factuurdatum als boekdatum.
        concept_id = client.create(
            inkoop.MODEL_MOVE,
            {"partner_id": 5, "date": "2025-12-15", "invoice_date": "2025-12-15", "ref": "F-2025-1215"},
        )
        client.creates.clear()
        monkeypatch.setattr(port, "_bestaande_move", lambda document_id, boek_cyclus, soort: client.moves[concept_id])
        uitkomst = port.boek_inkoopfactuur(
            document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf"
        )
        assert client.creates == []  # geen tweede document
        [(model, ids, vals)] = [w for w in client.writes if w[0] == inkoop.MODEL_MOVE]
        assert ids == [concept_id] and vals["date"] == "2026-01-01" and vals["invoice_date"] == "2025-12-15"
        assert uitkomst.detail["odoo_concept_ververst"] is True
        assert uitkomst.detail["boekdatum_verschoven"]["naar"] == "2026-01-01"

    def test_tegenboeking_in_vergrendelde_periode_wordt_nog_steeds_geweigerd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """De reversal draagt boekdatum vandaag; ligt vandaag op/vóór een lock date, dan blijft dat een weigering."""
        vandaag = date.today()
        client = _FakeOdoo(lock_dates={"fiscalyear_lock_date": vandaag, "hard_lock_date": None})
        port = _port(monkeypatch, client)
        with pytest.raises(BackendBoekFout, match="vergrendelde periode"):
            port._toets_lock_dates(vandaag)


# --------------------------------------------------------------------------- "Geboekt in Odoo"


class TestGeboektInOdooRegel:
    def test_regel_uit_detail(self) -> None:
        detail = {
            "backend": "odoo",
            "boekdatum_verschoven": {"van": "2025-12-15", "naar": "2026-01-01", "lock_veld": "tax_lock_date"},
        }
        assert boekdatum_verschoven_regel(detail) == (
            "boekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode"
        )

    @pytest.mark.parametrize(
        "detail",
        [None, {}, {"backend": "rlz"}, {"boekdatum_verschoven": None}, {"boekdatum_verschoven": {"van": "x"}}],
    )
    def test_zonder_verschuiving_none(self, detail) -> None:
        assert boekdatum_verschoven_regel(detail) is None

    def test_dto_additief_rlz_byte_identiek(self) -> None:
        from datetime import UTC, datetime

        rlz = GeboektInRlz(
            boekstuknummer="RLZ-01-00000442",
            rlz_document_id=None,
            tegenpartij="Universal Nederland B.V.",
            tegenpartij_rol="crediteur",
            geboekt_op=datetime.now(UTC),
        )
        assert rlz.boekdatum_verschoven is None
        dto = GeboektInRlzDto(regel=rlz.als_regel(), geboekt_op=rlz.geboekt_op)
        assert dto.boekdatum_verschoven is None
        odoo = GeboektInRlzDto(
            regel="Geboekt in Odoo · BILL/2026/01/0001 · Universal Steigerbouw",
            geboekt_op=rlz.geboekt_op,
            backend="odoo",
            boekdatum_verschoven=boekdatum_verschoven_regel(
                {"boekdatum_verschoven": {"van": "2025-12-15", "naar": "2026-01-01"}}
            ),
        )
        assert odoo.model_dump()["boekdatum_verschoven"].startswith("boekdatum 01-01-2026")
