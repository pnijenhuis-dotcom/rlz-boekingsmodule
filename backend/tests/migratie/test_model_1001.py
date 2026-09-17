"""Blok 9 run 2 VGG (16-09) — SCHRIJF b: het 1001-model in de replay (`app/migratie/model_1001.py`), zonder RLZ/Odoo/DB.

Bouwt voort op de mini-VGG uit `test_replay.py` mét een extra bankgrootboek 1001 (`UseForPaymentAccount`) en
memorialen die rechtstreeks op 1001 boeken: (a) gekoppeld via PaymentReferenceList, (b) gekoppeld via bedrag + datum
(vrije mutatie, Δ 2 d), (c) geen kandidaat → tussenrekening, (d) meerduidig → tussenrekening + teller, (e) verkeerde
tekenrichting = geen match, (f) balansguard blijft ROOD-bepalend, (g) outstanding-rekening bekend → echte Odoo-id, (h)
statusregel. De bankgroep sluit ná het model op 0,00 voor zover 1001 de oorzaak was; wat overblijft krijgt een
restcategorie mét regel."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

from app.migratie import model_1001, replay
from app.migratie.cli_replay import statusregel
from app.migratie.rekening_mapping import DoelGegevens, OutstandingUitkomst
from app.migratie.vertaling import IMPLICIET_TUSSENREKENING
from tests.migratie.test_replay import (
    _JR_DOCTYPE,
    ADMIN,
    L_KOSTEN,
    L_NOTARIS,
    ODOO_ACCOUNTS,
    NepClient,
    _doc,
    _jr,
    _regel,
    _run,
    _tx,
    mini_vgg,
)

L_1001 = str(uuid.uuid4())
LEDGER_1001 = {
    "id": L_1001,
    "AccountNumber": "1001",
    "Description": "ING Bank",
    "AccountType": 3,
    "IsTotalAccount": False,
    "UseForPaymentAccount": True,
}
ODOO_MET_1001 = [*ODOO_ACCOUNTS, {"id": 1001, "code": "1001", "name": "ING Bank"}]

MJ_KOPPELING, MJ_DATUM, MJ_GEEN, MJ_MEER, MJ_TEKEN, MJ_BALANS = (str(uuid.uuid4()) for _ in range(6))
TX_KOPPELING, TX_DATUM, TX_MEER_A, TX_MEER_B, TX_TEKEN = (str(uuid.uuid4()) for _ in range(5))


def _memoriaal(rlz_id: str, nr: str, datum: str, bedrag: float) -> dict:
    return _doc(
        rlz_id, nr, datum, bedrag, dt=11, Description=f"Memoriaal {nr}", JournalEntryDiary={"Name": "Memoriaal"}
    )


def scenario() -> tuple[dict, dict, dict]:
    collecties, regels, statements = mini_vgg()
    _JR_DOCTYPE.update(dict.fromkeys((MJ_KOPPELING, MJ_DATUM, MJ_GEEN, MJ_MEER, MJ_TEKEN, MJ_BALANS), 11))
    collecties["Ledgers"] = [*collecties["Ledgers"], LEDGER_1001]
    mj_k = _memoriaal(MJ_KOPPELING, "RLZ-06-00000200", "2025-09-01", 5000.0)
    mj_d = _memoriaal(MJ_DATUM, "RLZ-06-00000201", "2025-09-10", 1200.0)
    mj_g = _memoriaal(MJ_GEEN, "RLZ-06-00000202", "2025-09-20", 777.0)
    mj_m = _memoriaal(MJ_MEER, "RLZ-06-00000203", "2025-10-01", 300.0)
    mj_t = _memoriaal(MJ_TEKEN, "RLZ-06-00000204", "2025-10-15", 450.0)
    mj_b = _memoriaal(MJ_BALANS, "RLZ-06-00000205", "2025-11-01", 100.0)
    collecties["ManualJournals"] = [*collecties["ManualJournals"], mj_k, mj_d, mj_g, mj_m, mj_t, mj_b]
    collecties["PaymentTransactions"] = [
        *collecties["PaymentTransactions"],
        # (a) RLZ heeft de mutatie tegen het memoriaal afgeletterd (PaymentReferenceList → ManualJournal)
        _tx(TX_KOPPELING, "00200", "2025-09-01", 5000.0, refs=[(mj_k, 5000.0)], naam="Huurder A"),
        # (b) vrije mutatie, twee dagen later, cent-exact — geen koppeling in RLZ
        _tx(TX_DATUM, "00201", "2025-09-12", -1200.0, open_bedrag=-1200.0, naam="Leverancier B"),
        # (d) twee vrije kandidaten voor één 1001-regel van 300
        _tx(TX_MEER_A, "00202", "2025-10-01", 300.0, open_bedrag=300.0, naam="Huurder C"),
        _tx(TX_MEER_B, "00203", "2025-10-02", 300.0, open_bedrag=300.0, naam="Huurder D"),
        # (e) zelfde bedrag, zelfde dag, maar de memoriaalregel is CREDIT (geld eruit) en de mutatie +
        _tx(TX_TEKEN, "00204", "2025-10-15", 450.0, open_bedrag=450.0, naam="Huurder E"),
    ]
    collecties["JournalEntryLines"] = [
        *collecties["JournalEntryLines"],
        _jr(L_1001, MJ_KOPPELING, "2025-09-01", debet=5000.0),
        _jr(L_NOTARIS, MJ_KOPPELING, "2025-09-01", credit=5000.0),
        _jr(L_KOSTEN, MJ_DATUM, "2025-09-10", debet=1200.0),
        _jr(L_1001, MJ_DATUM, "2025-09-10", credit=1200.0),
        _jr(L_1001, MJ_GEEN, "2025-09-20", debet=777.0),
        _jr(L_NOTARIS, MJ_GEEN, "2025-09-20", credit=777.0),
        _jr(L_1001, MJ_MEER, "2025-10-01", debet=300.0),
        _jr(L_NOTARIS, MJ_MEER, "2025-10-01", credit=300.0),
        _jr(L_KOSTEN, MJ_TEKEN, "2025-10-15", debet=450.0),
        _jr(L_1001, MJ_TEKEN, "2025-10-15", credit=450.0),
        _jr(L_1001, MJ_BALANS, "2025-11-01", debet=100.0),
        _jr(L_NOTARIS, MJ_BALANS, "2025-11-01", credit=100.0),
    ]
    regels.update(
        {
            MJ_KOPPELING: [_regel(L_1001, debet=5000.0, omschrijving="Ontvangst"), _regel(L_NOTARIS, credit=5000.0)],
            MJ_DATUM: [_regel(L_KOSTEN, debet=1200.0), _regel(L_1001, credit=1200.0, omschrijving="Betaling")],
            MJ_GEEN: [_regel(L_1001, debet=777.0), _regel(L_NOTARIS, credit=777.0)],
            MJ_MEER: [_regel(L_1001, debet=300.0), _regel(L_NOTARIS, credit=300.0)],
            MJ_TEKEN: [_regel(L_KOSTEN, debet=450.0), _regel(L_1001, credit=450.0)],
            # (f) uit balans: 100 debet op 1001 tegenover 90 credit — de balansguard van 7d blijft bepalend
            MJ_BALANS: [_regel(L_1001, debet=100.0), _regel(L_NOTARIS, credit=90.0)],
        }
    )
    return collecties, regels, statements


def _rij(rapport, boekstuk: str) -> dict:  # noqa: ANN001
    rijen = [r for r in rapport.model_1001["regels"] if r["boekstuk"] == boekstuk]
    assert len(rijen) == 1, rijen
    return rijen[0]


def _move(rapport, boekstuk: str):  # noqa: ANN001, ANN202
    return next(m for m in rapport.moves if m.boekstuk == boekstuk)


def _groep(rapport, naam: str) -> dict:  # noqa: ANN001
    return next(g for g in rapport.afletter_groepen if g["groep"] == naam)


@pytest.fixture(scope="module")
def rapport():  # noqa: ANN201
    collecties, regels, statements = scenario()
    return _run(NepClient(collecties, regels, statements), odoo_accounts=ODOO_MET_1001)


class TestModel1001:
    def test_tellers(self, rapport) -> None:  # noqa: ANN001
        t = rapport.model_1001["tellers"]
        assert t["regels_1001"] == 6
        assert (t["gekoppeld"], t["via_koppeling"], t["via_bedrag_datum"]) == (2, 1, 1)
        assert (t["geen_bankmutatie"], t["meerduidig"]) == (3, 1)  # geen: MJ_GEEN, MJ_TEKEN, MJ_BALANS
        assert t["outstanding_bekend"] is False and t["outstanding_sleutel"] == model_1001.IMPLICIET_OUTSTANDING
        assert rapport.model_1001["bank_ledger_codes"] == ["1001"]

    def test_a_gekoppeld_via_paymentreferencelist(self, rapport) -> None:  # noqa: ANN001
        r = _rij(rapport, "RLZ-06-00000200")
        assert r["uitkomst"] == model_1001.UITKOMST_GEKOPPELD
        assert r["bestemming"] == model_1001.BESTEMMING_OUTSTANDING
        assert r["bewijs"] == model_1001.BEWIJS_KOPPELING
        assert r["mutatie"] == "00200" and r["dagen_verschil"] == 0 and r["bedrag"] == Decimal("5000.00")
        mv = _move(rapport, "RLZ-06-00000200")
        # memoriaalregel → outstanding (pseudo-sleutel zolang de rekening in Odoo niet is ingesteld), account_id None
        assert mv.vals["line_ids"][0][2]["account_id"] is None
        assert "outstanding BNK1" in mv.vals["line_ids"][0][2]["model_1001"]
        assert mv.vals["line_ids"][1][2]["account_id"] == 1650  # de andere kant ongewijzigd
        # statement line reconcilieert ertegen: tegenregel van tussenrekening → outstanding
        bank = _move(rapport, "00200")
        assert bank.bank["reconcile"][0]["via_outstanding"] == model_1001.IMPLICIET_OUTSTANDING
        assert bank.bank["reconcile"][0]["model_1001"] == model_1001.BEWIJS_KOPPELING

    def test_b_gekoppeld_via_bedrag_en_datum(self, rapport) -> None:  # noqa: ANN001
        r = _rij(rapport, "RLZ-06-00000201")
        assert r["uitkomst"] == model_1001.UITKOMST_GEKOPPELD and r["bewijs"] == model_1001.BEWIJS_BEDRAG_DATUM
        assert r["mutatie"] == "00201" and r["dagen_verschil"] == 2 and r["bedrag"] == Decimal("-1200.00")
        bank = _move(rapport, "00201")
        assert bank.bank["reconcile"] == [
            {
                "anker": _move(rapport, "RLZ-06-00000201").anker,
                "boekstuk": "RLZ-06-00000201",
                "move_type": "entry",
                "bedrag": Decimal("-1200.00"),
                "via_outstanding": model_1001.IMPLICIET_OUTSTANDING,
                "model_1001": model_1001.BEWIJS_BEDRAG_DATUM,
            }
        ]
        assert bank.bank["restant_berekend"] == 0

    def test_c_geen_kandidaat_blijft_op_de_tussenrekening_met_reden(self, rapport) -> None:  # noqa: ANN001
        r = _rij(rapport, "RLZ-06-00000202")
        assert r["uitkomst"] == model_1001.UITKOMST_GEEN and r["kandidaten"] == 0
        assert r["bestemming"] == model_1001.BESTEMMING_TUSSENREKENING and r["reden"] == model_1001.REDEN_GEEN
        mv = _move(rapport, "RLZ-06-00000202")
        assert mv.vals["line_ids"][0][2]["account_id"] is None
        assert "geen bankmutatie binnen ± 3 d" in mv.reden

    def test_d_meerduidig_niet_toegewezen_eigen_teller(self, rapport) -> None:  # noqa: ANN001
        r = _rij(rapport, "RLZ-06-00000203")
        assert r["uitkomst"] == model_1001.UITKOMST_MEERDUIDIG and r["kandidaten"] == 2
        assert r["bestemming"] == model_1001.BESTEMMING_TUSSENREKENING and r["mutatie"] is None
        assert "00202" in r["reden"] and "00203" in r["reden"]
        # géén van beide mutaties is geclaimd: allebei nog vrij (op de tussenrekening)
        for nr in ("00202", "00203"):
            assert _move(rapport, nr).bank["reconcile"] == []

    def test_e_tekenrichting_telt(self, rapport) -> None:  # noqa: ANN001
        r = _rij(rapport, "RLZ-06-00000204")
        assert r["uitkomst"] == model_1001.UITKOMST_GEEN and r["bedrag"] == Decimal("-450.00")
        assert _move(rapport, "00204").bank["reconcile"] == []

    def test_f_balansguard_blijft_rood_bepalend(self, rapport) -> None:  # noqa: ANN001
        assert rapport.memoriaal_uit_balans == 1
        assert [x["boekstuk"] for x in rapport.uit_balans] == ["RLZ-06-00000205"]
        assert _rij(rapport, "RLZ-06-00000205")["uitkomst"] == model_1001.UITKOMST_GEEN
        assert rapport.oordeel == "ROOD"

    def test_groepstoets_bank_sluit_voor_zover_1001_de_oorzaak_was(self, rapport) -> None:  # noqa: ANN001
        bank = _groep(rapport, "bank")
        assert model_1001.IMPLICIET_OUTSTANDING in bank["rekeningen"]
        # Odoo-bank = statement lines; de twee gekoppelde 1001-regels (5000 in, 1200 uit) tellen niet meer dubbel.
        # Wat overblijft: open mutaties zonder RLZ-journaal (+300 +300 +450) en 1001-regels die op de tussenrekening
        # bleven (RLZ wél op 1001: 777 + 300 + 100 − 450 = 727) → Odoo − RLZ = 1050 − 727.
        assert bank["verschil_tot"] == Decimal("323.00")
        cats = {r["categorie"]: r for r in bank["rest"]}
        assert (
            cats[replay.REST_OPEN_BANK]["aantal"] == 4
        )  # 00202, 00203, 00204 + de open huls-mutatie (ná `tot`, telt € 0)
        assert cats[replay.REST_OPEN_BANK]["bedrag_tot"] == Decimal("1050.00")
        assert cats[replay.REST_1001_GEEN]["aantal"] == 3 and cats[replay.REST_1001_GEEN]["bedrag_tot"] == Decimal(
            "-427.00"
        )
        assert cats[replay.REST_1001_MEERDUIDIG]["bedrag_tot"] == Decimal("-300.00")
        assert replay.REST_OPRUIMPUNT not in cats  # restant 0 → geen loze categorie
        assert sum((r["bedrag_tot"] for r in bank["rest"]), Decimal("0")) == bank["verschil_tot"]
        tussen = _groep(rapport, "tussenrekening")
        assert tussen["verschil_tot"] == Decimal("-323.00")  # spiegelbeeld van de bankgroep
        cats = {r["categorie"]: r for r in tussen["rest"]}
        assert cats[replay.REST_1001_GEEN]["aantal"] == 3
        assert cats[replay.REST_1001_GEEN]["bedrag_tot"] == Decimal("427.00")  # 777 − 450 + 100
        assert cats[replay.REST_1001_MEERDUIDIG]["aantal"] == 1
        assert cats[replay.REST_1001_MEERDUIDIG]["bedrag_tot"] == Decimal("300.00")
        assert cats[replay.REST_OPEN_BANK]["bedrag_tot"] == Decimal("-1050.00")
        assert sum((r["bedrag_tot"] for r in tussen["rest"]), Decimal("0")) == tussen["verschil_tot"]
        # nooit "onverklaard": élk restant draagt een regel
        for g in rapport.afletter_groepen:
            for r in g["rest"]:
                assert r["regel"] and r["categorie"]

    def test_outstanding_pseudo_sleutel_nettoot_binnen_de_bankgroep(self, rapport) -> None:  # noqa: ANN001
        rij = next(r for r in rapport.saldibalans if r["rekening"] == model_1001.IMPLICIET_OUTSTANDING)
        assert rij["odoo_tot"] == 0 and rij["rlz_tot"] == 0 and rij["groep"] == "bank"

    def test_let_op_klikpunt_en_rapportvormen(self, rapport) -> None:  # noqa: ANN001
        assert any("1001-model" in lo and "KLIKPUNT PETER" in lo for lo in rapport.let_op)
        md = rapport.als_markdown()
        assert "#### 1001-model (blok 9, SCHRIJF b" in md
        assert (
            "| RLZ-06-00000200 | 1 | 2025-09-01 | € 5.000,00 | gekoppeld | outstanding | PaymentReferenceList |" in md
        )
        assert "- Rest bankgroep — open/ongekoppelde bankmutaties (4×): € 1.050,00 per 2025-12-31 / € 1.050,00" in md
        assert (
            "- Rest tussenrekeninggroep — 1001 zonder bankmutatie (tussenrekening) (3×): € 427,00 per 2025-12-31" in md
        )
        data = json.loads(rapport.als_json())
        assert data["model_1001"]["tellers"]["gekoppeld"] == 2
        assert "1001-model 2 gekoppeld / 3 zonder mutatie / 1 meerduidig" in statusregel(rapport)


class TestOutstandingBekend:
    def test_echte_odoo_id_op_regel_en_tegenregel(self) -> None:
        collecties, regels, statements = scenario()
        gevonden = OutstandingUitkomst(999, "135000", "Payments in transit", "route", "gevonden (test)")

        def lezer(_a, _j, _c):  # noqa: ANN001, ANN202
            return DoelGegevens(odoo_accounts=ODOO_MET_1001, outstanding=gevonden)

        rapport = _run(NepClient(collecties, regels, statements), odoo_accounts=None, odoo_lezer=lezer)
        t = rapport.model_1001["tellers"]
        assert t["outstanding_bekend"] is True and t["outstanding_sleutel"] == "999"
        mv = _move(rapport, "RLZ-06-00000200")
        assert mv.vals["line_ids"][0][2]["account_id"] == 999
        assert _move(rapport, "00200").bank["reconcile"][0]["via_outstanding"] == "999"
        bank = _groep(rapport, "bank")
        assert "999" in bank["rekeningen"] and model_1001.IMPLICIET_OUTSTANDING not in bank["rekeningen"]
        assert not any("KLIKPUNT PETER" in lo and "1001-model" in lo for lo in rapport.let_op)
        rij = next(r for r in rapport.saldibalans if r["rekening"] == "999")
        assert rij["odoo_tot"] == 0  # +5000 (memoriaal) − 5000 (statement line) − 1200 + 1200


class TestZonderBankgrootboek:
    def test_mini_vgg_zonder_1001_is_ongewijzigd(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.model_1001["tellers"]["regels_1001"] == 0
        assert rapport.oordeel == "GROEN"
        assert "_geen memoriaalregels op een bankgrootboek_" in rapport.als_markdown()
        assert all(g["rest"] == [] for g in rapport.afletter_groepen)


def test_richting_en_bedrag_cent_exact() -> None:
    f = model_1001._zelfde_richting_en_bedrag
    assert f(Decimal("100.00"), Decimal("100.00")) and f(Decimal("-100.00"), Decimal("-100.00"))
    assert not f(Decimal("100.00"), Decimal("-100.00"))
    assert not f(Decimal("100.00"), Decimal("100.01"))
    assert not f(Decimal("0.00"), Decimal("0.00"))


def test_pseudo_sleutel_in_de_bankgroep_zonder_outstanding() -> None:
    from app.migratie.vertaling import Context, Doel, RolRekeningen

    ctx = Context(administratie_id=ADMIN, doel=Doel(), grootboek={}, ledgers={}, rollen=RolRekeningen(), panden={})
    groepen = replay.afletter_groepen(ctx, lambda lid: f"ongemapt:{lid}")
    assert model_1001.IMPLICIET_OUTSTANDING in groepen["bank"]["sleutels"]
    assert IMPLICIET_TUSSENREKENING in groepen["tussenrekening"]["sleutels"]


# ---- blok 10 (17-09): één regel, één bestemming — RJ-220-rol op de TEGENzijde, nooit op de 1001-regel -----------------

MJ_ONTVANGEN = str(uuid.uuid4())
TX_ONTVANGEN = str(uuid.uuid4())


def scenario_ontvangen_aanbetaling() -> tuple[dict, dict, dict, dict]:
    """Casus RLZ-28-00000061 (vierde meting 16-09): ontvangen aanbetaling als memoriaal 1001 D 135.000 / 1603 C 135.000
    mét pand-toewijzing soort aanbetaling (mens). Vóór blok 10 kreeg de 1001-regel de rol 3606 (activa met de grootste debet)
    én ging hij via het 1001-model naar outstanding → 3606 −363.300 in de saldibalans."""
    from app.migratie.vertaling import PandToewijzing
    from tests.migratie.test_replay import PANDEN

    collecties, regels, statements = mini_vgg()
    _JR_DOCTYPE.update({MJ_ONTVANGEN: 11})
    collecties["Ledgers"] = [*collecties["Ledgers"], LEDGER_1001]
    mj = _memoriaal(MJ_ONTVANGEN, "RLZ-28-00000061", "2025-11-07", 135000.0)
    collecties["ManualJournals"] = [*collecties["ManualJournals"], mj]
    collecties["PaymentTransactions"] = [
        *collecties["PaymentTransactions"],
        _tx(TX_ONTVANGEN, "00061", "2025-11-07", 135000.0, refs=[(mj, 135000.0)], naam="Midden Nederland"),
    ]
    collecties["JournalEntryLines"] = [
        *collecties["JournalEntryLines"],
        _jr(L_1001, MJ_ONTVANGEN, "2025-11-07", debet=135000.0),
        _jr(L_NOTARIS, MJ_ONTVANGEN, "2025-11-07", credit=135000.0),
    ]
    regels[MJ_ONTVANGEN] = [
        _regel(L_1001, debet=135000.0, omschrijving="Ontvangst aanbetaling MN"),
        _regel(L_NOTARIS, credit=135000.0, omschrijving="Aanbetaling 1603"),
    ]
    panden = {
        **PANDEN,
        uuid.UUID(MJ_ONTVANGEN): PandToewijzing("gelderstraat-60", "Gustaaf Gelderstraat 60, Almere", "aanbetaling", "hoog", "mens"),
    }
    return collecties, regels, statements, panden


class TestBlok10EenRegelEenBestemming:
    def test_rol_op_de_tegenzijde_1001_naar_outstanding_geen_overlap(self) -> None:
        collecties, regels, statements, panden = scenario_ontvangen_aanbetaling()
        rapport = _run(NepClient(collecties, regels, statements), odoo_accounts=ODOO_MET_1001, panden=panden)
        mv = _move(rapport, "RLZ-28-00000061")
        assert "vooruitbetaald_voorraad (3010)" in mv.reden and "regel 2 → vooruitbetaald_voorraad" in mv.reden
        assert "regel 1 → vooruitbetaald_voorraad" not in mv.reden, "de 1001-regel mag nooit de rol krijgen"
        # herclassificatie komt van de TEGENzijde (notaris-/1603-ledger), nooit van 1001
        herc = {(h["van"], h["naar"]): h for h in rapport.herclassificaties}
        assert all(not van.endswith("1001") for van, _ in herc), herc
        assert any(naar == "3010" and h["bedrag"] == Decimal("-135000.00") for (_, naar), h in herc.items()), herc
        r = _rij(rapport, "RLZ-28-00000061")
        assert r["uitkomst"] == model_1001.UITKOMST_GEKOPPELD and r["bestemming"] == model_1001.BESTEMMING_OUTSTANDING
        assert r["rj220_tegenzijde"] and "→ 3010" in r["rj220_tegenzijde"]
        assert rapport.model_1001["tellers"]["overlappen"] == 0 and rapport.model_1001["overlappen"] == []
        assert rapport.overlappen_1001 == 0
        md = rapport.als_markdown()
        assert "RJ-220-tegenzijde → rol" in md and "geen overlap tussen 1001-model en RJ-220-rol" in md

    def test_geforceerde_overlap_is_rood_en_zichtbaar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.migratie import vertaling

        collecties, regels, statements, panden = scenario_ontvangen_aanbetaling()
        monkeypatch.setattr(vertaling, "_kies_rolregel", lambda regels, bedragen, ctx, soort: 0)  # de 1001-regel (oud gedrag)
        rapport = _run(NepClient(collecties, regels, statements), odoo_accounts=ODOO_MET_1001, panden=panden)
        ov = rapport.model_1001["overlappen"]
        assert len(ov) >= 1 and any(o["boekstuk"] == "RLZ-28-00000061" and o["regel"] == 1 for o in ov)
        assert rapport.overlappen_1001 >= 1 and not rapport.groen and not rapport.groen_zonder_doel
        assert rapport.oordeel.startswith("ROOD")
        md = rapport.als_markdown()
        assert "TWEE bestemmingen" in md and "één regel, één bestemming" in md
