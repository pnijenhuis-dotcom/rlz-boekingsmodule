# ruff: noqa: F811 — pytest-fixtures als parameters
"""Intercompany-factuurmatch (Peter 16-09, blok B): pure match-motor (nummer > bedrag+datum > bedrag-only),
creditnota's/verrekenparen als één, de vier bevinding-soorten, "onderweg in de module" ≠ bevinding, status-verschil
pas ná 7 dagen, spiegelparen groen/rood, handelsrelaties uit IC-paren (beide richtingen = één), lezers RLZ/Odoo op
gemockte clients (server-side filter op Entity-id's + venster), RLZ↔Odoo-paar door de blokfunctie, querytelling
(calls per administratie onafhankelijk van het aantal facturen), webfilter = meting ongeldig, geen credential =
zichtbaar overgeslagen. Geen enkele echte RLZ-/Odoo-call."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.intercompany import factuurmatch as fm
from app.intercompany.factuurmatch import (
    SOORT_BEDRAG_VERSCHILT,
    SOORT_ONTBREEKT_BIJ_ONTVANGER,
    SOORT_ONTBREEKT_BIJ_VERKOPER,
    SOORT_STATUS_VERSCHILT,
    IcFactuur,
    bouw_handelsrelaties,
    maak_factuur,
    match_facturen,
    match_paar,
    toets_spiegelparen,
    vouw_verrekenparen,
)
from app.intercompany.relaties import Paar
from app.reconciliatie import run as run_service
from app.rlz.client import RlzWebfilterError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

A = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")  # verkoper (Universal Verkoop)
B = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")  # ontvanger (Universal Nederland)
ENT_B_IN_A = uuid.UUID("11111111-0000-4000-8000-000000000001")  # debiteur-record van B in A
ENT_A_IN_B = uuid.UUID("22222222-0000-4000-8000-000000000002")  # crediteur-record van A in B
NU = date(2026, 9, 16)
ARGS = argparse.Namespace()


def _f(
    kant: str,
    nummer: str | None,
    bedrag: str,
    datum: str = "2026-08-14",
    *,
    status: int = 2,
    fid: str | None = None,
    adm: uuid.UUID | None = None,
) -> IcFactuur:
    return maak_factuur(
        id=fid or str(uuid.uuid4()),
        administratie_id=adm or (A if kant == "verkoop" else B),
        kant=kant,
        nummer=nummer,
        bedrag=Decimal(bedrag),
        datum=date.fromisoformat(datum),
        status=status,
        boekstuk=f"BS-{nummer}" if nummer else None,
    )


def _paar(**kw) -> Paar:
    basis = {
        "administratie_a_id": A,
        "entity_in_a": ENT_B_IN_A,
        "administratie_b_id": B,
        "richting": "debiteur",
        "basis": "kvk",
        "status": "afgeleid",
        "entity_in_b": ENT_A_IN_B,
    }
    return Paar(**{**basis, **kw})


def _match(verkoop, inkoop, *, onderweg=frozenset(), nu=NU):
    return match_facturen(
        verkoper_id=A,
        ontvanger_id=B,
        verkoop=verkoop,
        inkoop=inkoop,
        module_onderweg=set(onderweg),
        nu=nu,
        verkoper_naam="Universal Verkoop",
        ontvanger_naam="Universal Nederland",
    )


# ---- puur: match-volgorde ---------------------------------------------------------------------------------------


class TestMatchVolgorde:
    def test_nummer_als_heel_token_wint_boven_bedrag(self) -> None:
        v = _f("verkoop", "2026-0123", "4500.00")
        # Inkoop-referentie "Factuur 2026-0123 augustus" bevat het nummer als heel token; een andere inkoop met exact
        # hetzelfde bedrag+datum maar zonder nummer mag NIET winnen.
        i_nummer = _f("inkoop", "Factuur 2026-0123 augustus", "4500.00", "2026-08-20")
        i_bedrag = _f("inkoop", "iets anders", "4500.00", "2026-08-14")
        u = _match([v], [i_nummer, i_bedrag])
        assert [(m.regel, m.inkoop.leidend.id) for m in u.matches] == [(fm.REGEL_NUMMER, i_nummer.id)]
        # i_bedrag blijft over → inkoop zonder verkoop
        assert [b.soort for b in u.bevindingen] == [SOORT_ONTBREEKT_BIJ_VERKOPER]

    def test_zelfde_nummer_na_normalisatie(self) -> None:
        v = _f("verkoop", "24594001722", "100.00")
        i = _f("inkoop", "2 4594 001722", "100.00", "2026-09-01")
        u = _match([v], [i])
        assert len(u.matches) == 1 and u.matches[0].regel == fm.REGEL_NUMMER and not u.bevindingen

    def test_bedrag_plus_datum_binnen_7_dagen(self) -> None:
        v = _f("verkoop", "2026-0200", "250.00", "2026-08-01")
        i = _f("inkoop", "onherkenbaar", "250.00", "2026-08-08")
        u = _match([v], [i])
        assert [m.regel for m in u.matches] == [fm.REGEL_BEDRAG_DATUM] and u.matches[0].zeker and not u.bevindingen

    def test_bedrag_zonder_datum_is_match_zonder_zekerheid_en_zonder_bevinding(self) -> None:
        v = _f("verkoop", "2026-0200", "250.00", "2026-01-01")
        i = _f("inkoop", "onherkenbaar", "250.00", "2026-08-08")
        u = _match([v], [i])
        assert [m.regel for m in u.matches] == [fm.REGEL_BEDRAG] and not u.matches[0].zeker
        assert u.bevindingen == ()

    def test_dichtstbijzijnde_datum_wint_bij_meerdere_kandidaten(self) -> None:
        v = _f("verkoop", "X-1", "10.00", "2026-08-10")
        i_ver = _f("inkoop", "a", "10.00", "2026-08-17", fid="ver")
        i_dicht = _f("inkoop", "b", "10.00", "2026-08-11", fid="dicht")
        u = _match([v], [i_ver, i_dicht])
        assert u.matches[0].inkoop.leidend.id == "dicht"


class TestVerrekenparen:
    def test_factuur_plus_credit_zelfde_stam_is_een_groep(self) -> None:
        f = _f("verkoop", "2026-0123", "4500.00", "2026-08-14", fid="f")
        c = _f("verkoop", "2026-0123-C", "-4500.00", "2026-08-30", fid="c")
        groepen = vouw_verrekenparen([f, c])
        assert len(groepen) == 1 and groepen[0].ids == {"f", "c"} and groepen[0].bedrag == 0
        assert groepen[0].nummer == "2026-0123"  # de factuur leidt

    def test_credit_som_nul_binnen_7_dagen_zonder_stam(self) -> None:
        f = _f("verkoop", "2026-0123", "300.00", "2026-08-14", fid="f")
        c = _f("verkoop", "CN-9", "-300.00", "2026-08-19", fid="c")
        assert len(vouw_verrekenparen([f, c])) == 1

    def test_credit_zonder_partner_blijft_los_en_negatief(self) -> None:
        c = _f("verkoop", "CN-9", "-300.00", "2026-08-19", fid="c")
        f = _f("verkoop", "2026-0999", "300.00", "2026-05-01", fid="f")  # > 7 dagen, andere stam
        groepen = vouw_verrekenparen([f, c])
        assert len(groepen) == 2 and {g.bedrag for g in groepen} == {Decimal("300.00"), Decimal("-300.00")}

    def test_creditnota_telt_negatief_mee_in_de_match(self) -> None:
        # Verkoop: factuur 4500 + credit -4500 (verrekend, netto 0). Inkoop: alleen de factuur → bedrag verschilt
        # (verkoop netto 0 ≠ inkoop 4500) op nummer.
        vf = _f("verkoop", "2026-0123", "4500.00", fid="vf")
        vc = _f("verkoop", "2026-0123-C", "-4500.00", "2026-08-20", fid="vc")
        i = _f("inkoop", "2026-0123", "4500.00")
        u = _match([vf, vc], [i])
        assert [b.soort for b in u.bevindingen] == [SOORT_BEDRAG_VERSCHILT]
        assert u.bevindingen[0].extra["bedrag_verkoop"] == "0.00" and u.bevindingen[0].extra["verrekend"] is True

    def test_verrekend_paar_zonder_tegenkant_is_teller_geen_bevinding(self) -> None:
        vf = _f("verkoop", "2026-0123", "4500.00", fid="vf")
        vc = _f("verkoop", "2026-0123-C", "-4500.00", "2026-08-20", fid="vc")
        u = _match([vf, vc], [])
        assert u.bevindingen == () and len(u.verrekend_zonder_tegenkant) == 1


# ---- puur: bevinding-soorten --------------------------------------------------------------------------------------


class TestBevindingen:
    def test_ontbreekt_bij_ontvanger_handeling_bij_b(self) -> None:
        v = _f("verkoop", "2026-0123", "4500.00", "2026-08-14")
        u = _match([v], [])
        (b,) = u.bevindingen
        assert b.soort == SOORT_ONTBREEKT_BIJ_ONTVANGER and b.administratie_id == B
        assert b.extra["nummer"] == "2026-0123" and b.extra["bedrag_verkoop"] == "4500.00"
        assert b.extra["verkoper_naam"] == "Universal Verkoop" and b.extra["ontvanger_naam"] == "Universal Nederland"
        assert b.detail == f"paar={A}>{B} nummer=2026-0123 bedrag=4500.00 datum=2026-08-14"

    def test_ontbreekt_bij_verkoper_handeling_bij_a(self) -> None:
        i = _f("inkoop", "2026-0123", "4500.00")
        u = _match([], [i])
        (b,) = u.bevindingen
        assert b.soort == SOORT_ONTBREEKT_BIJ_VERKOPER and b.administratie_id == A

    def test_bedrag_verschilt_met_beide_bedragen_en_delta(self) -> None:
        v = _f("verkoop", "2026-0124", "4500.00")
        i = _f("inkoop", "2026-0124", "4050.00", fid="i-guid-onleesbaar")
        u = _match([v], [i])
        (b,) = u.bevindingen
        assert b.soort == SOORT_BEDRAG_VERSCHILT and b.administratie_id == B
        assert (b.extra["bedrag_verkoop"], b.extra["bedrag_inkoop"], b.extra["delta"]) == (
            "4500.00",
            "4050.00",
            "450.00",
        )
        assert b.extra["boekstuk_a"] == "BS-2026-0124" and b.extra["boekstuk_b"] == "BS-2026-0124"
        # record_id: factuur-id van de handelende kant (B) als het een uuid is, anders uuid5 — hier onleesbaar → uuid5.
        assert isinstance(b.record_id, uuid.UUID)

    def test_record_id_is_inkoopfactuur_id_bij_b(self) -> None:
        i_id = str(uuid.uuid4())
        v = _f("verkoop", "2026-0124", "4500.00")
        i = _f("inkoop", "2026-0124", "4050.00", fid=i_id)
        (b,) = _match([v], [i]).bevindingen
        assert str(b.record_id) == i_id

    def test_status_verschilt_alleen_ouder_dan_7_dagen(self) -> None:
        v = _f("verkoop", "2026-0125", "120.00", "2026-09-12", status=2)
        i = _f("inkoop", "2026-0125", "120.00", "2026-09-12", status=1)
        assert _match([v], [i], nu=date(2026, 9, 16)).bevindingen == ()  # 4 dagen: nog niets
        (b,) = _match([v], [i], nu=date(2026, 9, 20)).bevindingen  # 8 dagen
        assert b.soort == SOORT_STATUS_VERSCHILT and b.administratie_id == B
        assert (b.extra["status_a"], b.extra["status_b"], b.extra["concept_kant"]) == ("2", "1", "inkoop")

    def test_beide_geboekt_of_beide_concept_geen_statusbevinding(self) -> None:
        v = _f("verkoop", "2026-0125", "120.00", "2026-01-12", status=1)
        i = _f("inkoop", "2026-0125", "120.00", "2026-01-12", status=1)
        assert _match([v], [i]).bevindingen == ()

    def test_onderweg_in_module_is_geen_bevinding(self) -> None:
        v = _f("verkoop", "2026-0123", "4500.00")
        u = _match([v], [], onderweg={"2026123"})  # normaliseer_referentie("2026-0123") == "2026123"
        assert u.bevindingen == () and len(u.onderweg) == 1
        # Zodra het nummer níét meer onderweg is (geboekt → komt uit RLZ als inkoop) verschijnt het gewoon.
        assert len(_match([v], [], onderweg=set()).bevindingen) == 1

    def test_vingerafdruk_stabiel_per_paar_zonder_datum_van_vandaag(self) -> None:
        v = _f("verkoop", "2026-0123", "4500.00", fid="v1")
        b1 = _match([v], [], nu=date(2026, 9, 16)).bevindingen[0]
        v2 = _f("verkoop", "2026-0123", "4500.00", fid="v2")  # ander id, zelfde paar/nummer/bedrag
        b2 = _match([v2], [], nu=date(2026, 10, 1)).bevindingen[0]
        assert b1.vingerafdruk == b2.vingerafdruk and b1.record_id == b2.record_id
        # Ander bedrag = andere werkelijkheid = nieuw signaal.
        b3 = _match([_f("verkoop", "2026-0123", "4501.00")], []).bevindingen[0]
        assert b3.vingerafdruk != b1.vingerafdruk

    def test_match_paar_contractvorm(self) -> None:
        v = _f("verkoop", "2026-0123", "4500.00")
        uit = match_paar(_paar(), verkoop=[v], inkoop=[], module_onderweg=set(), nu=NU)
        assert [b.soort for b in uit] == [SOORT_ONTBREEKT_BIJ_ONTVANGER] and uit[0].administratie_id == B
        # Omgekeerde richting (B ziet A als crediteur): dezelfde handelsrelatie A → B.
        omgekeerd = _paar(
            administratie_a_id=B,
            entity_in_a=ENT_A_IN_B,
            administratie_b_id=A,
            richting="crediteur",
            entity_in_b=ENT_B_IN_A,
        )
        uit2 = match_paar(omgekeerd, verkoop=[v], inkoop=[], module_onderweg=set(), nu=NU)
        assert uit2[0].administratie_id == B and uit2[0].vingerafdruk == uit[0].vingerafdruk


class TestHandelsrelaties:
    def test_beide_richtingen_worden_een_relatie_met_entity_sets(self) -> None:
        dubbel = uuid.UUID("33333333-0000-4000-8000-000000000003")  # tweede crediteur-record van A in B
        paren = [
            _paar(),
            _paar(
                administratie_a_id=B,
                entity_in_a=ENT_A_IN_B,
                administratie_b_id=A,
                richting="crediteur",
                entity_in_b=ENT_B_IN_A,
            ),
            _paar(
                administratie_a_id=B, entity_in_a=dubbel, administratie_b_id=A, richting="crediteur", entity_in_b=None
            ),
        ]
        (rel,) = bouw_handelsrelaties(paren)
        assert rel.verkoper_id == A and rel.ontvanger_id == B
        assert rel.verkoop_entity_ids == {ENT_B_IN_A} and rel.inkoop_entity_ids == {ENT_A_IN_B, dubbel}

    def test_zonder_tegenrelatie_blijft_de_inkoopkant_leeg(self) -> None:
        (rel,) = bouw_handelsrelaties([_paar(entity_in_b=None)])
        assert rel.inkoop_entity_ids == frozenset()


class TestSpiegelparen:
    def _paar(self, v: str, s: str) -> fm.Spiegelpaar:
        return fm.Spiegelpaar(
            boeking_id=uuid.uuid4(),
            bron_administratie_id=A,
            doel_administratie_id=B,
            verkoop_rlz_id=v,
            spiegel_rlz_id=s,
            verkoop_invoice_number="24713188",
        )

    def test_groen_als_beide_gelezen_en_cent_exact_gelijk(self) -> None:
        v, s = str(uuid.uuid4()), str(uuid.uuid4())
        uit = toets_spiegelparen(
            [self._paar(v, s)],
            verkoop=[_f("verkoop", "24713188", "1210.00", fid=v)],
            inkoop=[_f("inkoop", "24713188", "1210.00", fid=s.upper())],
        )
        assert [u.groen for u in uit] == [True]

    @pytest.mark.parametrize(
        ("inkoop_bedrag", "inkoop_aanwezig", "reden_fragment"),
        [("1210.01", True, "≠ spiegel"), ("1210.00", False, "spiegel-inkoopfactuur niet gevonden")],
    )
    def test_rood_met_reden(self, inkoop_bedrag, inkoop_aanwezig, reden_fragment) -> None:
        v, s = str(uuid.uuid4()), str(uuid.uuid4())
        inkoop = [_f("inkoop", "24713188", inkoop_bedrag, fid=s)] if inkoop_aanwezig else []
        (u,) = toets_spiegelparen(
            [self._paar(v, s)], verkoop=[_f("verkoop", "24713188", "1210.00", fid=v)], inkoop=inkoop
        )
        assert not u.groen and reden_fragment in (u.reden or "")


# ---- lezers op gemockte clients ---------------------------------------------------------------------------------------


class FakeRlzClient:
    """Speelt SalesInvoices/PurchaseInvoices met server-side filter na: honoreert $filter op Entity-id's,
    $top/$skip-paginering en telt élke call."""

    def __init__(self, sales: list[dict], purchases: list[dict], *, webfilter: bool = False) -> None:
        self.sales, self.purchases, self.webfilter = sales, purchases, webfilter
        self.calls: list[tuple[str, dict]] = []
        self.gesloten = False

    def _filter(self, rijen: list[dict], filter_: str) -> list[dict]:
        ids = {deel.split("Entity/id eq ")[1].strip(" )") for deel in filter_.split(" and ")[0].split(" or ")}
        return [r for r in rijen if str(r["Entity"]["id"]) in ids]

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = params or {}
        self.calls.append((path, params))
        if self.webfilter:
            raise RlzWebfilterError(403, "GET", path, "<html>Access Denied</html>")
        assert "Date ge " in params["$filter"] and "T00:00:00Z" in params["$filter"], params["$filter"]
        assert params["$expand"] == "Entity"
        bron = self.sales if path == "SalesInvoices" else self.purchases
        rijen = self._filter(bron, params["$filter"])
        top, skip = int(params["$top"]), int(params["$skip"])
        return {"value": rijen[skip : skip + top]}

    def find_purchase_invoices_kandidaten(self, *, vendor_ids, van, tot, per_pagina=200, max_paginas=5):
        ids = {str(v) for v in vendor_ids}
        rijen = [r for r in self.purchases if str(r["Entity"]["id"]) in ids]
        uit: list[dict] = []
        for pagina in range(max_paginas):
            self.calls.append(("PurchaseInvoices", {"$skip": pagina * per_pagina}))
            if self.webfilter:
                raise RlzWebfilterError(403, "GET", "PurchaseInvoices", "Access Denied")
            deel = rijen[pagina * per_pagina : (pagina + 1) * per_pagina]
            uit.extend(deel)
            if len(deel) < per_pagina:
                break
        return uit

    def close(self) -> None:
        self.gesloten = True


def _sales_rij(
    nummer: int, bedrag: float, datum: str = "2026-08-14", *, entity=ENT_B_IN_A, credit=False, status=2, rid=None
):
    return {
        "id": rid or str(uuid.uuid4()),
        "InvoiceNumber": nummer,
        "Reference": str(nummer),
        "BaseInvoiceAmount": bedrag,
        "Date": f"{datum}T00:00:00",
        "Status": status,
        "IsCreditInvoice": credit,
        "Entity": {"id": str(entity), "Name": "Universal Nederland"},
    }


def _purchase_rij(
    ref: str, bedrag: float, datum: str = "2026-08-14", *, entity=ENT_A_IN_B, credit=False, status=2, rid=None
):
    return {
        "id": rid or str(uuid.uuid4()),
        "Reference": ref,
        "BaseInvoiceAmount": bedrag,
        "Date": f"{datum}T00:00:00Z",
        "Status": status,
        "IsCreditInvoice": credit,
        "ReceiptNumber": f"RLZ-04-{ref}",
        "Entity": {"id": str(entity), "Name": "Universal Verkoop"},
    }


class FakeOdooClient:
    def __init__(self, moves: list[dict], company_id: int = 3, partners: tuple[int, ...] = (42, 99)) -> None:
        self.moves, self.company_id, self.partners = moves, company_id, partners
        self.calls: list[list] = []

    def search_read(self, model, domain, fields, *, limit=None, offset=0, order=None):
        self.calls.append(domain)
        if model == "res.partner":
            return [{"id": p} for p in self.partners]
        assert model == "account.move"
        d = {tuple(x[:2]): x[2] for x in domain}
        assert d[("company_id", "=")] == self.company_id
        types, partners = set(d[("move_type", "in")]), set(d[("partner_id", "in")])
        van, tot = d[("invoice_date", ">=")], d[("invoice_date", "<=")]
        rijen = [
            m
            for m in self.moves
            if m["move_type"] in types
            and m["partner_id"][0] in partners
            and van <= m["invoice_date"] <= tot
            and m["state"] != "cancel"
        ]
        return rijen[offset : offset + (limit or len(rijen))]

    def close(self) -> None:
        return None


class FakeOdooPort:
    def __init__(self, client: FakeOdooClient, partners: dict[uuid.UUID, int]) -> None:
        self.client, self._partners = client, partners

    def partner_id_voor(self, vendor_id: uuid.UUID) -> int:
        return self._partners[vendor_id]


class TestOdooEntityVertaling:
    def test_debiteur_partner_uuid5_wordt_teruggerekend_in_een_call(self) -> None:
        """Blok A slaat een Odoo-debiteur op als odoo_uuid(company, 'res.partner', id); de bron rekent 'm terug via
        één res.partner-call per administratie (gecachet) — nooit een filterloze account.move-read."""
        from app.odoo.ids import odoo_uuid

        client = FakeOdooClient([_move(1, "INV/1", None, 10.0, "2026-08-14", move_type="out_invoice", partner=42)])
        bron = fm.OdooBron(B, FakeOdooPort(client, {}))  # geen vendor-koppeling: eerste route faalt
        debiteur = odoo_uuid(3, "res.partner", 42)
        # Tweede route (odoo_id_voor) vergt een DB-scope — hier stubben op 'onbekend' zodat route 3 aan bod komt.
        bron.administratie_id = B
        uit = bron.verkoop([debiteur], date(2026, 1, 1), NU)
        assert [f.nummer for f in uit] == ["INV/1"]
        # Cache: tweede aanroep leest res.partner niet opnieuw.
        n = len(client.calls)
        bron.verkoop([debiteur], date(2026, 1, 1), NU)
        assert len(client.calls) == n + 1  # alleen de account.move-call

    def test_onbekende_entity_is_let_op_geen_filterloze_read(self) -> None:
        client = FakeOdooClient([])
        bron = fm.OdooBron(B, FakeOdooPort(client, {}))
        with pytest.raises(fm.EntityNietVertaalbaar):
            bron.inkoop([uuid.uuid4()], date(2026, 1, 1), NU)
        # Geen enkele account.move-call (move_type-filter) is gedaan.
        assert not any(any(isinstance(x, list) and x[0] == "move_type" for x in d) for d in client.calls)


def _move(
    mid: int,
    name: str,
    ref: str | None,
    bedrag: float,
    datum: str,
    *,
    move_type: str,
    partner: int,
    state="posted",
    payment_state="not_paid",
):
    return {
        "id": mid,
        "name": name,
        "ref": ref,
        "invoice_date": datum,
        "amount_total": bedrag,
        "state": state,
        "payment_state": payment_state,
        "move_type": move_type,
        "partner_id": [partner, "Universal Nederland"],
    }


class TestLezers:
    def test_rlz_verkoop_normaliseert_creditnota_negatief_en_nummer_als_str(self) -> None:
        client = FakeRlzClient([_sales_rij(20260123, 4500.0), _sales_rij(20260124, 100.0, credit=True)], [])
        uit = fm.lees_verkoop_rlz(client, [ENT_B_IN_A], date(2026, 1, 1), NU, administratie_id=A)
        assert [(f.nummer, f.bedrag, f.kant) for f in uit] == [
            ("20260123", Decimal("4500.00"), "verkoop"),
            ("20260124", Decimal("-100.00"), "verkoop"),
        ]
        assert uit[0].nummer_norm == "20260123" and uit[0].boekstuk == "20260123"

    def test_rlz_verkoop_filtert_server_side_op_entity_en_venster(self) -> None:
        client = FakeRlzClient([_sales_rij(1, 1.0), _sales_rij(2, 2.0, entity=uuid.uuid4())], [])
        uit = fm.lees_verkoop_rlz(client, [ENT_B_IN_A], date(2026, 1, 1), NU, administratie_id=A)
        assert [f.nummer for f in uit] == ["1"]
        ((pad, params),) = client.calls
        assert pad == "SalesInvoices" and f"Entity/id eq {ENT_B_IN_A}" in params["$filter"]
        assert "Date ge 2026-01-01T00:00:00Z and Date le 2026-09-16T23:59:59Z" in params["$filter"]

    def test_rlz_inkoop_via_kandidaten_route(self) -> None:
        client = FakeRlzClient(
            [], [_purchase_rij("2026-0123", 4500.0, credit=False), _purchase_rij("CN-1", 50.0, credit=True)]
        )
        uit = fm.lees_inkoop_rlz(client, [ENT_A_IN_B], date(2026, 1, 1), NU, administratie_id=B)
        assert [(f.nummer, f.bedrag, f.boekstuk) for f in uit] == [
            ("2026-0123", Decimal("4500.00"), "RLZ-04-2026-0123"),
            ("CN-1", Decimal("-50.00"), "RLZ-04-CN-1"),
        ]

    def test_odoo_verkoop_en_inkoop(self) -> None:
        client = FakeOdooClient(
            [
                _move(1, "INV/2026/0007", None, 4500.0, "2026-08-14", move_type="out_invoice", partner=42),
                _move(2, "RINV/2026/0001", None, 500.0, "2026-08-20", move_type="out_refund", partner=42),
                _move(
                    3,
                    "BILL/2026/0003",
                    "2026-0123",
                    4500.0,
                    "2026-08-15",
                    move_type="in_invoice",
                    partner=42,
                    state="draft",
                ),
                _move(4, "BILL/2026/0004", "x", 1.0, "2026-08-15", move_type="in_invoice", partner=99),
            ]
        )
        verkoop = fm.lees_verkoop_odoo(client, [42], date(2026, 1, 1), NU, administratie_id=A)
        inkoop = fm.lees_inkoop_odoo(client, [42], date(2026, 1, 1), NU, administratie_id=B)
        assert [(f.nummer, f.bedrag) for f in verkoop] == [
            ("INV/2026/0007", Decimal("4500.00")),
            ("RINV/2026/0001", Decimal("-500.00")),
        ]
        assert [(f.nummer, f.bedrag, f.status, f.boekstuk) for f in inkoop] == [
            ("2026-0123", Decimal("4500.00"), 1, "BILL/2026/0003")
        ]
        assert len(client.calls) == 2 and all(["partner_id", "in", [42]] in d for d in client.calls)


# ---- blokfunctie mét DB (acceptatie, module-onderweg, verzamelaar) -------------------------------------------------------


@pytest.fixture
def twee_administraties(admin_engine, administratie_id):  # noqa: ANN001
    """A = de bestaande fixture-administratie (RLZ), B = een tweede (Odoo-sentinel niet nodig: de bron wordt geïnjecteerd)."""
    b = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Universal Nederland (test)', :rlz)"
            ),
            {"id": b, "rlz": f"rlz-{b}"},
        )
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'Universal Verkoop (test)' WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id, b


def _run(bronnen: dict, paren: list, *, verzamelaar=None, args=ARGS) -> tuple[int, list[str], list[str]]:
    uit: list[str] = []
    err: list[str] = []

    def factory(aid: uuid.UUID) -> fm.Bron:
        bron = bronnen[aid]
        if isinstance(bron, Exception):
            raise bron
        return bron

    code = fm.cli_blok(
        args, verzamelaar, bron_factory=factory, paren=paren, nu=NU, stdout=uit.append, stderr=err.append
    )
    return code, uit, err


class TestBlokfunctie:
    def _paar_db(self, a: uuid.UUID, b: uuid.UUID) -> Paar:
        return Paar(
            administratie_a_id=a,
            entity_in_a=ENT_B_IN_A,
            administratie_b_id=b,
            richting="debiteur",
            basis="kvk",
            status="bevestigd",
            entity_in_b=ENT_A_IN_B,
        )

    def test_rlz_verkoper_odoo_ontvanger_bevinding_landt_bij_b(self, twee_administraties) -> None:
        a, b = twee_administraties
        rlz = FakeRlzClient([_sales_rij(20260123, 4500.0), _sales_rij(20260124, 100.0)], [])
        odoo = FakeOdooClient(
            [_move(3, "BILL/1", "20260123", 4500.0, "2026-08-15", move_type="in_invoice", partner=42)]
        )
        bronnen = {a: fm.RlzBron(a, rlz), b: fm.OdooBron(b, FakeOdooPort(odoo, {ENT_A_IN_B: 42}))}
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, err = _run(bronnen, [self._paar_db(a, b)], verzamelaar=verzamelaar)
        assert code == 1 and err == []
        afwijkingen = [x for x in verzamelaar.bevindingen if x.soort == "afwijking"]
        assert len(afwijkingen) == 1 and afwijkingen[0].administratie_id == b
        d = afwijkingen[0].detail
        assert d["bron"] == "intercompany" and d["afwijking_soort"] == SOORT_ONTBREEKT_BIJ_ONTVANGER
        assert d["nummer"] == "20260124" and d["verkoper_naam"] == "Universal Verkoop (test)"
        assert d["ontvanger_naam"] == "Universal Nederland (test)" and "verkoop_ids" not in d
        assert verzamelaar.blokken[fm.BLOK].gecontroleerd == 3  # 2 verkoop + 1 inkoop
        assert any(x.startswith("AFWIJKING ") and "1 gematcht (1 op nummer" in x for x in uit), uit
        assert rlz.gesloten

    def test_acceptatie_met_reden_maakt_regel_geaccepteerd(self, twee_administraties, beheerder_id) -> None:
        from app.reconciliatie import service as acceptatie_service

        a, b = twee_administraties
        rlz = FakeRlzClient([_sales_rij(20260123, 4500.0)], [])
        bronnen = {a: fm.RlzBron(a, rlz), b: fm.RlzBron(b, FakeRlzClient([], []))}
        v1 = run_service.Verzamelaar()
        v1.start_blok(fm.BLOK)
        _run(bronnen, [self._paar_db(a, b)], verzamelaar=v1)
        (afw,) = [x for x in v1.bevindingen if x.soort == "afwijking"]
        acceptatie_service.accepteer(
            bron="intercompany",
            administratie_id=b,
            record_id=uuid.UUID(afw.detail["record_id"]),
            soort=afw.detail["afwijking_soort"],
            detail=afw.detail["detail"],
            reden="bewust: interne verrekening",
            beheerder_id=beheerder_id,
        )
        v2 = run_service.Verzamelaar()
        v2.start_blok(fm.BLOK)
        code, uit, _ = _run(
            {a: fm.RlzBron(a, FakeRlzClient([_sales_rij(20260123, 4500.0)], [])), b: bronnen[b]},
            [self._paar_db(a, b)],
            verzamelaar=v2,
        )
        assert code == 0 and [x.soort for x in v2.bevindingen] == ["geaccepteerd"]
        assert any("GEACCEPTEERD" in x and "bewust: interne verrekening" in x for x in uit)

    def test_querytelling_calls_onafhankelijk_van_aantal_facturen(self, twee_administraties) -> None:
        a, b = twee_administraties

        def calls_voor(n: int) -> int:
            sales = [_sales_rij(1000 + i, 10.0) for i in range(n)]
            purchases = [_purchase_rij(str(1000 + i), 10.0) for i in range(n)]
            rlz_a, rlz_b = FakeRlzClient(sales, []), FakeRlzClient([], purchases)
            code, _, _ = _run({a: fm.RlzBron(a, rlz_a), b: fm.RlzBron(b, rlz_b)}, [self._paar_db(a, b)])
            assert code == 0
            return len(rlz_a.calls) + len(rlz_b.calls)

        assert calls_voor(5) == calls_voor(150) == 2  # één verkoop-call bij A, één inkoop-call bij B
        assert calls_voor(500) == 6  # alleen paginering (3 pagina's van 200 per kant), geen call per factuur

    def test_webfilter_is_meting_ongeldig_geen_bevindingen(self, twee_administraties) -> None:
        a, b = twee_administraties
        bronnen = {
            a: fm.RlzBron(a, FakeRlzClient([], [], webfilter=True)),
            b: fm.RlzBron(b, FakeRlzClient([], [_purchase_rij("1", 1.0)])),
        }
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, err = _run(bronnen, [self._paar_db(a, b)], verzamelaar=verzamelaar)
        assert code == 1
        assert any(fm.WEBFILTER_ONGELDIG in e and str(a) in e for e in err), err
        assert [x.soort for x in verzamelaar.bevindingen] == ["fout"] and verzamelaar.bevindingen[
            0
        ].administratie_id == a
        assert not any(x.startswith("AFWIJKING") for x in uit)

    def test_geen_credential_is_zichtbaar_overgeslagen(self, twee_administraties) -> None:
        a, b = twee_administraties
        bronnen = {a: fm.BronOvergeslagen(fm.GEEN_CREDENTIAL), b: fm.RlzBron(b, FakeRlzClient([], []))}
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, err = _run(bronnen, [self._paar_db(a, b)], verzamelaar=verzamelaar)
        assert code == 0 and err == [] and verzamelaar.bevindingen == []
        assert any(x.startswith(f"OVERGESLAGEN {a}: {fm.GEEN_CREDENTIAL}") for x in uit), uit

    def test_tegenrelatie_onbekend_is_let_op_en_leest_niets_zonder_filter(self, twee_administraties) -> None:
        a, b = twee_administraties
        rlz_a, rlz_b = FakeRlzClient([_sales_rij(1, 1.0)], []), FakeRlzClient([], [])
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        paar = Paar(
            administratie_a_id=a,
            entity_in_a=ENT_B_IN_A,
            administratie_b_id=b,
            richting="debiteur",
            basis="kvk",
            status="afgeleid",
            entity_in_b=None,
        )
        code, uit, _ = _run({a: fm.RlzBron(a, rlz_a), b: fm.RlzBron(b, rlz_b)}, [paar], verzamelaar=verzamelaar)
        assert code == 0 and rlz_a.calls == [] and rlz_b.calls == []
        assert [x.soort for x in verzamelaar.bevindingen] == ["let_op"]
        assert verzamelaar.bevindingen[0].detail["reden"] == "ic_tegenrelatie_onbekend"

    def test_geen_paren_is_ok(self, twee_administraties) -> None:
        code, uit, _ = _run({}, [])
        assert code == 0 and any(x.startswith("OK         geen actieve intercompany-relaties") for x in uit)

    def test_spiegelpaar_rood_is_systeemfout_zonder_administratie_met_audit(
        self, twee_administraties, monkeypatch
    ) -> None:
        a, b = twee_administraties
        v_id, s_id = str(uuid.uuid4()), str(uuid.uuid4())
        paar = fm.Spiegelpaar(
            boeking_id=uuid.uuid4(),
            bron_administratie_id=a,
            doel_administratie_id=b,
            verkoop_rlz_id=v_id,
            spiegel_rlz_id=s_id,
            verkoop_invoice_number="24713188",
        )
        monkeypatch.setattr(fm, "lees_spiegelparen", lambda aid, *, vanaf: [paar])
        rlz_a = FakeRlzClient([_sales_rij(24713188, 1210.0, rid=v_id)], [])
        rlz_b = FakeRlzClient([], [_purchase_rij("24713188", 1210.01, rid=s_id)])
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(fm.BLOK)
        code, uit, err = _run(
            {a: fm.RlzBron(a, rlz_a), b: fm.RlzBron(b, rlz_b)}, [self._paar_db(a, b)], verzamelaar=verzamelaar
        )
        assert code == 1
        fouten = [x for x in verzamelaar.bevindingen if x.soort == "fout"]
        assert len(fouten) == 1 and fouten[0].administratie_id is None and fm.SPIEGEL_SYSTEEMFOUT in fouten[0].tekst
        assert fouten[0].detail["afwijking_soort"] == fm.SOORT_SPIEGEL_ROOD
        # Beheer-signaal: systeemmail, nooit actiemail.
        assert run_service.is_beheer_signaal(fouten[0])
        # De gewone bedrag-verschilt-bevinding van dit paar is onderdrukt (motor-bug is geen kantoor-handeling).
        assert not any(x.soort == "afwijking" for x in verzamelaar.bevindingen)
        with scoped_session(None) as session:
            audit = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.actie == "automatisering_regressie", AuditEvent.record_id == paar.boeking_id
                )
            ).all()
        assert len(audit) == 1 and audit[0].nieuwe_waarde["categorie"] == fm.SOORT_SPIEGEL_ROOD
        assert audit[0].nieuwe_waarde["vingerafdruk"] == fouten[0].vingerafdruk

    def test_spiegelpaar_groen_telt_in_slotregel(self, twee_administraties, monkeypatch) -> None:
        a, b = twee_administraties
        v_id, s_id = str(uuid.uuid4()), str(uuid.uuid4())
        paar = fm.Spiegelpaar(
            boeking_id=uuid.uuid4(),
            bron_administratie_id=a,
            doel_administratie_id=b,
            verkoop_rlz_id=v_id,
            spiegel_rlz_id=s_id,
            verkoop_invoice_number="24713188",
        )
        monkeypatch.setattr(fm, "lees_spiegelparen", lambda aid, *, vanaf: [paar])
        rlz_a = FakeRlzClient([_sales_rij(24713188, 1210.0, rid=v_id)], [])
        rlz_b = FakeRlzClient([], [_purchase_rij("24713188", 1210.0, rid=s_id)])
        code, uit, _ = _run({a: fm.RlzBron(a, rlz_a), b: fm.RlzBron(b, rlz_b)}, [self._paar_db(a, b)])
        assert code == 0 and any("spiegelparen 1 groen / 0 rood" in x for x in uit), uit

    def test_module_onderweg_leest_alleen_open_documenten_van_b(self, twee_administraties) -> None:
        a, b = twee_administraties
        assert fm.module_onderweg(b) == set()


class TestTeksten:
    def test_leesbaar_per_soort_zonder_ids(self) -> None:
        from app.reconciliatie import teksten
        from tests.reconciliatie.test_teksten import B as Bev
        from tests.reconciliatie.test_teksten import _schoon

        d = {
            "bron": "intercompany",
            "record_id": str(uuid.uuid4()),
            "afwijking_soort": SOORT_ONTBREEKT_BIJ_ONTVANGER,
            "detail": f"paar={A}>{B} nummer=2026-0123 bedrag=4500.00 datum=2026-08-14",
            "geaccepteerd": False,
            "uitsluiting": None,
            "verkoper_naam": "Universal Verkoop",
            "ontvanger_naam": "Universal Nederland",
            "nummer": "2026-0123",
            "bedrag_verkoop": "4500.00",
            "datum": "2026-08-14",
        }
        lb = teksten.leesbaar(Bev(blok="intercompany", soort="afwijking", tekst="AFWIJKING x", detail=d))
        _schoon(lb)
        assert lb.titel.startswith("Onderlinge factuur ontbreekt bij ontvanger")
        assert lb.wat == (
            "Universal Verkoop factureerde 2026-0123 € 4.500,00 van 14-08-2026 aan Universal Nederland; "
            "bij Universal Nederland staat die inkoop niet."
        )
        assert (
            lb.doe
            == "Controleer bij Universal Nederland of de factuur is ontvangen en boek 'm, of accepteer met reden."
        )
        for soort, extra in (
            (SOORT_ONTBREEKT_BIJ_VERKOPER, {"bedrag_inkoop": "4500.00"}),
            (SOORT_BEDRAG_VERSCHILT, {"bedrag_inkoop": "4050.00", "delta": "450.00"}),
            (
                SOORT_STATUS_VERSCHILT,
                {"bedrag_inkoop": "4500.00", "status_a": "2", "status_b": "1", "concept_kant": "inkoop"},
            ),
        ):
            lb = teksten.leesbaar(
                Bev(
                    blok="intercompany",
                    soort="afwijking",
                    tekst="AFWIJKING x",
                    detail={**d, "afwijking_soort": soort, **extra},
                )
            )
            _schoon(lb)
            assert "intercompany" not in (lb.titel + lb.wat + lb.doe).lower()
        assert (
            "verschil € 450,00"
            in teksten.leesbaar(
                Bev(
                    blok="intercompany",
                    soort="afwijking",
                    tekst="x",
                    detail={
                        **d,
                        "afwijking_soort": SOORT_BEDRAG_VERSCHILT,
                        "bedrag_inkoop": "4050.00",
                        "delta": "450.00",
                    },
                )
            ).wat
        )
