# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/voorraad)
"""Odoo-adapter blok D (03-09, migratie 0102): Odoo als LEESBRON voor de voorraad-uitstroom van een
RLZ-administratie (casus Universal Verkoop, company 3).

- alleen-lezen koppeling via de Beheerder-endpoints (leesprobe groen vereist; `odoo_client_voor` levert er ALTIJD
  een read-only client voor), knip zetten/wijzigen mét audit;
- Odoo-leesroute: alleen geposte out_invoice/out_refund vanaf de knip, creditnota = negatief (teken uit het
  documenttype), artikelcode = `default_code`, secties/notities tellen niet, annulering ruimt op, idempotent,
  incrementeel venster nooit vóór de knip, dubbel-vangnet op factuurnummer, read-only-poort fail-loud;
- RLZ-route: facturen mét Date ≥ knip niet registreren én eerder geregistreerde regels opruimen;
- gecombineerde run (`sync_voorraad_uitstroom`) + CLI-rapportage + herreken zonder Odoo-calls.
Fake Odoo-client — geen netwerk."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.main import app
from app.odoo import service as odoo_service
from app.odoo import verkoop_uitstroom
from app.odoo.client import OdooAlleenLezen
from app.odoo.credentials import GeenOdooKoppeling, koppeling_voor, odoo_client_voor
from app.odoo.ids import odoo_uuid
from app.security.tokens import create_access_token
from app.voorraad import rlz_uitstroom, service
from app.voorraad.models import VoorraadRegel
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.voorraad.test_rlz_uitstroom import F_CREDIT, F_IN_APP, fake_rlz  # noqa: F401
from tests.voorraad.test_voorraad import _FakeAi, fake_ai, voorraad_aan  # noqa: F401

client = TestClient(app)

COMPANY = 3
KNIP = date(2026, 8, 1)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _move(mid: int, naam: str, datum: str, *, state: str = "posted", move_type: str = "out_invoice", lines: list[int]):
    return {
        "id": mid,
        "name": naam,
        "state": state,
        "move_type": move_type,
        "invoice_date": datum,
        "date": datum,
        "partner_id": [77, "Bouwbedr.Gebr. Kanters BV"],
        "invoice_line_ids": lines,
        "company_id": [COMPANY, "Universal Verkoop B.V."],
    }


def _line(
    lid: int,
    naam: str,
    qty: float,
    prijs: float,
    subtotal: float,
    *,
    product: int | None = None,
    seq: int = 10,
    display_type: str = "product",
):
    return {
        "id": lid,
        "name": naam,
        "quantity": qty,
        "price_unit": prijs,
        "price_subtotal": subtotal,
        "product_id": [product, f"[P{product}] x"] if product else False,
        "product_uom_id": [1, "Units"],
        "display_type": display_type,
        "sequence": seq,
    }


class _FakeOdoo:
    """Duck-typed OdooClient voor de leesroute: alleen search_read_alles/read (+ close). Elke schrijf- of
    onbekende aanroep = AssertionError (read-only-garantie)."""

    read_only = True

    def __init__(
        self, moves: list[dict[str, Any]], lines: list[dict[str, Any]], producten: list[dict[str, Any]]
    ) -> None:
        self.moves, self.lines, self.producten = moves, lines, producten
        self.aanroepen: list[tuple[str, Any]] = []
        self.gesloten = False

    def search_read_alles(self, model: str, domain: list, fields: list[str], *, pagina: int = 500, order: str = "id"):
        self.aanroepen.append((f"search_read_alles:{model}", domain))
        assert model == "account.move"
        company = next(d[2] for d in domain if d[0] == "company_id")
        vanaf = date.fromisoformat(next(d[2] for d in domain if d[0] == "invoice_date"))
        types = next(d[2] for d in domain if d[0] == "move_type")
        return [
            m
            for m in self.moves
            if m["company_id"][0] == company
            and m["move_type"] in types
            and date.fromisoformat(m["invoice_date"]) >= vanaf
        ]

    def read(self, model: str, ids: list[int], fields: list[str]):
        self.aanroepen.append((f"read:{model}", ids))
        bron = {"account.move.line": self.lines, "product.product": self.producten}[model]
        return [r for r in bron if r["id"] in ids]

    def close(self) -> None:
        self.gesloten = True

    def __getattr__(self, naam: str) -> Any:
        raise AssertionError(f"Odoo-write of onbekende aanroep in de leesroute: {naam}")


class _FakeProbeClient:
    """Voor de leesprobe bij het koppelen (alleen leesacties)."""

    def __init__(self, company_id: int, *, leesrecht: bool = True) -> None:
        self.company_id = company_id
        self.leesrecht = leesrecht

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def versie(self):
        return {"server_version": "19.0+e"}

    def read_een(self, model, odoo_id, fields):
        return {"id": odoo_id, "name": "Universal Verkoop B.V."} if odoo_id == COMPANY else None

    def has_access(self, model, operatie):
        assert operatie == "read"
        return self.leesrecht

    def search_count(self, model, domain):
        return 20


@pytest.fixture
def fake_odoo() -> _FakeOdoo:
    moves = [
        _move(3001, "F/2026/00027", "2026-08-15", lines=[1, 2, 3, 4]),
        _move(3002, "RF/2026/00003", "2026-08-20", move_type="out_refund", lines=[5]),
        _move(3003, False, "2026-08-22", state="draft", lines=[6]),
        _move(3004, "F/2026/00001", "2026-07-15", lines=[7]),  # vóór de knip: RLZ-terrein
        _move(3005, "50212199", "2026-08-25", lines=[8]),  # nummer bestaat al als RLZ-referentie → dubbel
    ]
    lines = [
        _line(1, "Steigerbuis 4 mtr incl. tube-connect", 10, 20.1, 201.0, product=501, seq=10),
        _line(2, "Transportkosten", 1, 150.0, 150.0, seq=20),
        _line(3, "Levering week 33", 0, 0, 0, seq=5, display_type="line_section"),
        _line(4, "Koppeling draaibaar 48", 2000, 4.5, 9000.0, product=502, seq=30),
        _line(5, "Koppeling draaibaar 48", 30, 65.0, 1950.0, product=502),
        _line(6, "Koppeling draaibaar 48", 1, 1.0, 1.0),
        _line(7, "Koppeling draaibaar 48", 5, 1.0, 5.0),
        _line(8, "Koppeling draaibaar 48", 7, 1.0, 7.0),
    ]
    producten = [{"id": 501, "default_code": "550100.210"}, {"id": 502, "default_code": False}]
    return _FakeOdoo(moves, lines, producten)


@pytest.fixture
def leesbron(administratie_id, beheerder_id, monkeypatch) -> uuid.UUID:
    """Alleen-lezen koppeling via het Beheerder-endpoint (leesprobe gefaked, geen netwerk)."""
    monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: _FakeProbeClient(cid))
    resp = client.post(
        f"/administraties/{administratie_id}/odoo/leesbron",
        json={
            "odoo_url": "https://universal-steigers.odoo.com/",
            "api_key": "GEHEIM-SLEUTEL-123",
            "company_id": COMPANY,
            "voorraad_knip_datum": KNIP.isoformat(),
        },
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 201, resp.text
    return administratie_id


def _odoo_regels(administratie_id: uuid.UUID) -> list[VoorraadRegel]:
    from app.db.session import scoped_session

    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.bron == verkoop_uitstroom.BRON
                )
            )
        )
        session.expunge_all()
        return sorted(rijen, key=lambda r: (str(r.rlz_document_id), r.regel_volgnummer))


class TestPuur:
    def test_teken_en_regelvertaling(self) -> None:
        assert verkoop_uitstroom.teken_voor("out_invoice") == 1
        assert verkoop_uitstroom.teken_voor("out_refund") == -1
        move = _move(1, "RF/1", "2026-08-20", move_type="out_refund", lines=[1, 2, 3])
        lines = [
            _line(2, "B", 2, 5.0, 10.0, seq=20),
            _line(1, "A", 3, 1.5, 4.5, product=9, seq=10),
            _line(3, "sectie", 0, 0, 0, seq=1, display_type="line_section"),
        ]
        regels = verkoop_uitstroom.externe_regels(move, lines, {9: "560140.4"})
        assert [r.tekst for r in regels] == ["A", "B"]  # sectie weg, volgorde op sequence
        assert regels[0].aantal == Decimal("-3") and regels[0].netto_bedrag == Decimal("-4.5")
        assert (
            regels[0].prijs == Decimal("1.5") and regels[0].artikelcode == "560140.4" and regels[0].eenheid == "Units"
        )
        assert regels[1].artikelcode is None
        # Factuur: positief, zoals geleverd.
        factuur = verkoop_uitstroom.externe_regels(_move(2, "F/1", "2026-08-20", lines=[2]), [lines[0]], {})
        assert factuur[0].aantal == Decimal("2") and factuur[0].netto_bedrag == Decimal("10.0")


class TestKoppeling:
    def test_zonder_koppeling_zichtbaar_overgeslagen(self, administratie_id, voorraad_aan) -> None:
        telling = verkoop_uitstroom.sync_odoo_verkoopregels(administratie_id=administratie_id)
        assert telling.vanaf is None and telling.overgeslagen_reden == "geen Odoo-koppeling"
        with pytest.raises(GeenOdooKoppeling):
            koppeling_voor(administratie_id)

    def test_leesbron_koppelen_stand_en_read_only_client(self, leesbron, beheerder_id, gescoopte_gebruiker) -> None:
        aid = leesbron
        resp = client.get(f"/administraties/{aid}/odoo", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["alleen_lezen"] is True and resp.json()["voorraad_knip_datum"] == KNIP.isoformat()
        assert resp.json()["company_id"] == COMPANY and resp.json()["probe_groen"] is True
        assert "ciphertext" not in resp.text and "GEHEIM" not in resp.text  # nooit de sleutel
        # De credential-resolutie accepteert een alleen-lezen koppeling bij een RLZ-administratie …
        verbinding = koppeling_voor(aid)
        assert verbinding.alleen_lezen and verbinding.voorraad_knip_datum == KNIP
        # … en levert er ALTIJD een read-only client voor, ongeacht het argument (poort "nooit een write op company 3").
        with odoo_client_voor(aid, read_only=False) as odoo:
            assert odoo.read_only is True and odoo.company_id == COMPANY
            with pytest.raises(OdooAlleenLezen):
                odoo.create("account.move", {"x": 1})
        # Tweede keer koppelen = leesbare fout; niet-Beheerder = 403.
        resp = client.post(
            f"/administraties/{aid}/odoo/leesbron",
            json={
                "odoo_url": "https://universal-steigers.odoo.com",
                "api_key": "GEHEIM-SLEUTEL-123",
                "company_id": COMPANY,
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422 and "al een Odoo-koppeling" in resp.text
        resp = client.put(
            f"/administraties/{aid}/odoo/leesbron",
            json={"voorraad_knip_datum": "2026-09-01"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403

    def test_leesprobe_rood_slaat_niets_op(self, administratie_id, beheerder_id, monkeypatch) -> None:
        monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: _FakeProbeClient(cid, leesrecht=False))
        resp = client.post(
            f"/administraties/{administratie_id}/odoo/leesbron",
            json={"odoo_url": "https://x.odoo.com", "api_key": "GEHEIM-SLEUTEL-123", "company_id": COMPANY},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422 and "geen leesrecht" in resp.text
        with pytest.raises(GeenOdooKoppeling):
            koppeling_voor(administratie_id)

    def test_knip_wijzigen_met_audit(self, leesbron, beheerder_id, admin_engine) -> None:
        resp = client.put(
            f"/administraties/{leesbron}/odoo/leesbron",
            json={"voorraad_knip_datum": "2026-09-01"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200 and resp.json()["voorraad_knip_datum"] == "2026-09-01"
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text(
                    "SELECT oude_waarde::text, nieuwe_waarde::text FROM platform.audit_event "
                    "WHERE actie = 'odoo_leesbron_knip_gewijzigd' AND record_id = :id"
                ),
                {"id": leesbron},
            ).one()
        assert "2026-08-01" in rij[0] and "2026-09-01" in rij[1]


class TestLeesroute:
    def test_geposte_credit_concept_knip_dubbel_en_idempotent(
        self, leesbron, gescoopte_gebruiker, voorraad_aan, fake_ai, fake_rlz, fake_odoo, admin_engine
    ) -> None:
        aid = leesbron
        # Eerst de RLZ-route: F_CREDIT (19-08, referentie 50212199) valt NÁ de knip 01-08 → Odoo-terrein, overgeslagen.
        rlz = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=aid)
        assert rlz.knip_datum == KNIP and rlz.overgeslagen_na_knip == 4 and rlz.facturen_verwerkt == 0
        # Simuleer een RLZ-registratie van vóór de knip mét het nummer dat ook in Odoo voorkomt (dubbel-vangnet).
        rlz_uitstroom.registreer_externe_factuur(
            administratie_id=aid,
            bron=rlz_uitstroom.BRON,
            extern_document_id=uuid.UUID(F_CREDIT),
            referentie="50212199",
            datum=date(2026, 7, 20),
            relatie_naam="X",
            regels=[
                rlz_uitstroom.ExterneRegel(
                    tekst="Koppeling draaibaar 48", aantal=Decimal(1), prijs=None, netto_bedrag=None
                )
            ],
        )

        telling = verkoop_uitstroom.sync_odoo_verkoopregels(administratie_id=aid, client=fake_odoo)
        assert telling.vanaf == KNIP and telling.knip_datum == KNIP and telling.company_id == COMPANY
        assert telling.facturen_gelezen == 4  # 3004 (vóór de knip) komt door het domein-filter niet mee
        assert (
            telling.facturen_verwerkt == 2
            and telling.overgeslagen_niet_geboekt == 1
            and telling.overgeslagen_dubbel == 1
        )
        assert telling.regels == 4  # 3 productregels (sectie telt niet) + 1 creditregel
        assert fake_odoo.gesloten is False  # meegegeven client wordt niet gesloten
        # Read-only: alleen search_read_alles + read; het domein filtert op company én invoice_date ≥ knip.
        domein = fake_odoo.aanroepen[0][1]
        assert ["company_id", "=", COMPANY] in domein and ["invoice_date", ">=", KNIP.isoformat()] in domein
        assert all(a.startswith(("search_read_alles:", "read:")) for a, _ in fake_odoo.aanroepen)

        rijen = _odoo_regels(aid)
        assert len(rijen) == 4 and all(r.document_id is None and r.richting == "uit" for r in rijen)
        factuur = [r for r in rijen if r.rlz_document_id == odoo_uuid(COMPANY, "account.move", 3001)]
        factuur.sort(key=lambda r: r.regel_volgnummer)
        assert [r.artikeltekst for r in factuur] == [
            "Steigerbuis 4 mtr incl. tube-connect",
            "Transportkosten",
            "Koppeling draaibaar 48",
        ]
        assert factuur[0].aantal == Decimal("10.000") and factuur[0].prijs == Decimal("20.1000")
        assert factuur[0].netto_bedrag == Decimal("201.00") and factuur[0].eenheid == "Units"
        assert factuur[0].artikelcode == "550100.210"  # expliciet uit default_code
        assert factuur[0].rlz_referentie == "F/2026/00027" and factuur[0].relatie_naam == "Bouwbedr.Gebr. Kanters BV"
        assert factuur[0].datum == date(2026, 8, 15)
        assert factuur[1].soort == "transport"  # dienst-regex, geen AI
        assert factuur[2].artikelcode is None and factuur[2].artikelgroep_id is not None
        credit = next(r for r in rijen if r.rlz_document_id == odoo_uuid(COMPANY, "account.move", 3002))
        assert credit.aantal == Decimal("-30.000") and credit.netto_bedrag == Decimal("-1950.00")
        assert credit.rlz_referentie == "RF/2026/00003"
        assert credit.artikelgroep_id == factuur[2].artikelgroep_id  # zelfde tekst → zelfde regel, geen 2e AI-call

        # Aansluiting: Odoo-verkoop telt mee als 'uit' (2000 − 30), bron benoemd.
        groep = next(g for g in service.groepen(administratie_id=aid) if g.naam == "Koppelingen 48mm")
        a = service.aansluiting(administratie_id=aid, van=date(2026, 1, 1), tot=date(2026, 12, 31))
        g = next(x for x in a.groepen if x.artikelgroep_id == groep.id)
        assert g.verkoop == Decimal("1971.000")  # 2000 − 30 + 1 (RLZ-regel van vóór de knip, aantal 1)
        assert "verkoop_odoo" in a.bronnen

        # Idempotent + incrementeel: nogmaals = vervangen per factuur; vanaf = max(datum) − 14 d, nooit vóór de knip.
        telling2 = verkoop_uitstroom.sync_odoo_verkoopregels(administratie_id=aid, client=fake_odoo)
        assert telling2.regels == 4 and len(_odoo_regels(aid)) == 4
        assert telling2.vanaf == max(KNIP, date(2026, 8, 20) - timedelta(days=14))
        # Annulering in Odoo: de factuur wordt cancel → haar regels verdwijnen bij de volgende run.
        fake_odoo.moves[0]["state"] = "cancel"
        telling3 = verkoop_uitstroom.sync_odoo_verkoopregels(administratie_id=aid, client=fake_odoo, volledig=True)
        assert (
            telling3.vanaf == KNIP
            and telling3.verwijderd_na_annulering == 3
            and telling3.overgeslagen_niet_geboekt == 2
        )
        assert {r.rlz_referentie for r in _odoo_regels(aid)} == {"RF/2026/00003"}

        # Herreken (UI-knop) hernormaliseert de Odoo-regels lokaal — géén Odoo-calls.
        n_voor = len(fake_odoo.aanroepen)
        herreken = service.herreken_administratie(administratie_id=aid, actor_id=gescoopte_gebruiker)
        assert herreken["odoo_regels"] == 1 and len(fake_odoo.aanroepen) == n_voor
        resp = client.get(
            f"/administraties/{aid}/voorraad/regels",
            params={"van": "2026-01-01", "tot": "2026-12-31"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200
        rij = next(r for r in resp.json()["rijen"] if r["bron"] == "odoo_verkoop")
        assert rij["rlz_referentie"] == "RF/2026/00003" and rij["document_id"] is None

    def test_schrijvende_client_geweigerd(self, leesbron, voorraad_aan, fake_odoo) -> None:
        fake_odoo.read_only = False
        with pytest.raises(verkoop_uitstroom.OdooLeesbronOngeldig):
            verkoop_uitstroom.sync_odoo_verkoopregels(administratie_id=leesbron, client=fake_odoo)

    def test_rlz_route_ruimt_op_na_gezette_knip(
        self, administratie_id, beheerder_id, voorraad_aan, fake_ai, fake_rlz, monkeypatch
    ) -> None:
        # Zonder knip registreert de RLZ-route F_GEBOEKT (28-08) en F_CREDIT (19-08).
        telling = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id)
        assert telling.facturen_verwerkt == 3 and telling.knip_datum is None
        # Knip 25-08 gezet: F_GEBOEKT valt ná de knip → niet meer registreren, eerdere regels weg; F_CREDIT blijft.
        monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: _FakeProbeClient(cid))
        resp = client.post(
            f"/administraties/{administratie_id}/odoo/leesbron",
            json={
                "odoo_url": "https://x.odoo.com",
                "api_key": "GEHEIM-SLEUTEL-123",
                "company_id": COMPANY,
                "voorraad_knip_datum": "2026-08-25",
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 201
        telling2 = rlz_uitstroom.sync_rlz_verkoopregels(administratie_id=administratie_id, volledig=True)
        assert telling2.knip_datum == date(2026, 8, 25)
        # F_GEBOEKT én F_CONCEPT (beide 28-08) vallen ná de knip; alleen F_GEBOEKT had regels (3).
        assert (
            telling2.overgeslagen_na_knip == 2 and telling2.verwijderd_na_knip == 3 and telling2.facturen_verwerkt == 2
        )
        from app.db.session import scoped_session

        with scoped_session(administratie_id) as session:
            ids = set(
                session.scalars(
                    select(VoorraadRegel.rlz_document_id).where(VoorraadRegel.administratie_id == administratie_id)
                )
            )
        assert ids == {uuid.UUID(F_CREDIT), uuid.UUID(F_IN_APP)}

    def test_gecombineerde_run_en_cli_rapportage(
        self, leesbron, voorraad_aan, fake_ai, fake_rlz, fake_odoo, monkeypatch, capsys
    ) -> None:
        from app import cli

        monkeypatch.setattr(verkoop_uitstroom, "odoo_client_voor", lambda aid, read_only=False: fake_odoo)
        resultaten = rlz_uitstroom.sync_alle_voorraad_administraties()
        telling = resultaten[leesbron]
        assert isinstance(telling, rlz_uitstroom.RlzUitstroomTelling)
        assert (
            telling.odoo is not None
            and telling.odoo["facturen_verwerkt"] == 3  # hier geen RLZ-referentie '50212199' → geen dubbel
            and telling.odoo["company_id"] == COMPANY
        )
        assert fake_odoo.gesloten is True  # eigen client wordt gesloten
        assert cli._rapporteer_voorraad_rlz(resultaten) == 0
        uit = capsys.readouterr().out
        assert "ná de Odoo-knip 2026-08-01" in uit and "Odoo (company 3)" in uit and "3 verwerkt" in uit
        # Alleen-lezen zonder knip = geen voorraadrol → zichtbaar overgeslagen in de Odoo-regel.
        odoo_service.wijzig_leesbron(actor_id=SYSTEEM_ACTOR_ID, administratie_id=leesbron, voorraad_knip_datum=None)
        telling2 = rlz_uitstroom.sync_voorraad_uitstroom(administratie_id=leesbron)
        assert telling2.odoo is not None and "zonder voorraad-knip" in telling2.odoo["overgeslagen_reden"]
        assert telling2.knip_datum is None  # RLZ-route weer volledig de bron
        cli._rapporteer_voorraad_rlz({leesbron: telling2})
        assert "Odoo: overgeslagen" in capsys.readouterr().out
