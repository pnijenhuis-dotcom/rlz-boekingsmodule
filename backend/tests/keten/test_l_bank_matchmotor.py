"""Casus (l) — bankmatchmotor Administratiekantoor Nijenhuis C.V. 08-09 (blok 2 bundel 08-09).

Productie 08-09 toonde twee foute voorstellen van de oude substring-matchmotor (geval A: € 12.500 BIJ van een
privépersoon → verkoopfactuur 2352 Tupker Beheer omdat "2352" in het betalingskenmerk zat; geval B: afschrijving
DNA Notaris → verkoopfactuur 2337 Kempen Chalets, tekenfout). De twee goede matches (TransIP 24-08, NPG 2026053)
moeten groen blijven. Deze test draait de motor via de SERVICELAAG (`voorstellen.open_mutaties_met_voorstellen`,
mét de DB-caches `bank_mutatie` + `payment_item_cache` zoals de sync ze vult) op de fixture-set
`fixtures/l_bank_cv_08-09/` — geen RLZ-call, geen AI."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import tijd
from app.bank import voorstellen
from app.bank.boeken import DEKKING_FOUT_PREFIX
from app.bank.matchmotor import VoorstelSoort
from app.main import app
from app.security.tokens import create_access_token
from tests.bank.conftest import FakeBankClient, boeken_aan, maak_bank_mutatie, maak_payment_item  # noqa: F401
from tests.keten import casussen
from tests.keten.casussen import Casus, normaliseer_voor_export
from tests.keten.conftest import FRONTEND_KETEN_DIR, REFERENTIE_DATUM, REFERENTIE_TIJDSTIP, echte_vandaag_nl

CASUS = Casus(casussen.L_BANK_CV)
CV_NAAM = "Administratiekantoor Nijenhuis C.V."
#: Blok 3 nachtrun 10/11-09: rekening + mutaties A/B (Zilver Beheer 10-09, geanonimiseerd) —
#: fixtures/l_bank_cv_08-09/deels_afgeletterd.json.
DEELS = json.loads((CASUS.map / "deels_afgeletterd.json").read_text(encoding="utf-8"))
REKENING_ID = uuid.UUID(DEELS["rekening"]["id"])
#: Placeholder-id van de administratie in élke frontend-fixture (zelfde als Keten.exporteer).
EXPORT_ADMINISTRATIE_ID = "aaaaaaaa-0000-4000-8000-000000000001"


@pytest.fixture
def bevroren_vandaag(monkeypatch: pytest.MonkeyPatch) -> date:
    """`app.tijd._klok` = het referentietijdstip van de gouden set (blok 2, 11-09: één anker voor élke kalenderdag —
    `vandaag_nl()` in matchmotor, historie-regel en boeken volgt vanzelf): de historie-regel (dekking ≥ 183 dagen,
    `vandaag`) en de export blijven zo deterministisch — geen datum van de echte klok in de fixture (guard
    test_export_deterministisch)."""
    monkeypatch.setattr(tijd, "_klok", lambda: REFERENTIE_TIJDSTIP)
    assert tijd.vandaag_nl() == REFERENTIE_DATUM
    return REFERENTIE_DATUM


@pytest.fixture
def cv_bank(
    administratie_id: uuid.UUID, admin_engine: Engine, bevroren_vandaag: date
) -> dict[str, dict[str, uuid.UUID]]:
    """De testadministratie als de C.V., mét de bankrekening (blok 3: alle mutaties hangen eraan zodat het bankscherm
    ze via GET …/rekeningen/{id}/mutaties ziet), de vier onverwerkte mutaties en vier open posten uit de fixture."""
    rekening = DEELS["rekening"]
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = :naam WHERE id = :id"),
            {"naam": CV_NAAM, "id": administratie_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.payment_account_cache "
                "(id, administratie_id, naam, iban, rekening_type, saldo, saldo_datum, is_gearchiveerd, "
                "laatste_import, brondata) VALUES (:id, :aid, :naam, :iban, :type, :saldo, "
                "CAST(:saldo_datum AS date), false, CAST(:import AS jsonb), '{}')"
            ),
            {
                "id": REKENING_ID,
                "aid": administratie_id,
                "naam": rekening["naam"],
                "iban": rekening["iban"],
                "type": rekening["rekening_type"],
                "saldo": rekening["saldo"],
                "saldo_datum": rekening["saldo_datum"],
                "import": json.dumps(rekening["laatste_import"]),
            },
        )
    mutaties = {
        m["sleutel"]: maak_bank_mutatie(
            admin_engine,
            administratie_id=administratie_id,
            mutatie_id=uuid.UUID(m["id"]),
            payment_account_id=REKENING_ID,
            bedrag=m["bedrag"],
            tegenpartij_naam=m["tegenpartij_naam"],
            omschrijving=m["omschrijving"],
            tegenrekening_iban=m["tegenrekening_iban"],
            boekdatum=m["boekdatum"],
        )
        for m in CASUS.bank_mutaties()
    }
    posten = {
        p["sleutel"]: maak_payment_item(
            admin_engine,
            administratie_id=administratie_id,
            item_id=uuid.UUID(p["id"]),
            bedrag=p["bedrag"],
            referentie=p["referentie"],
            documentsoort=p["documentsoort"],
            entity_naam=p["entity_naam"],
            entity_guid=uuid.UUID(p["entity_guid"]),
            boekdatum=p["boekdatum"],
            rlz_document_id=uuid.UUID(p["rlz_document_id"]),
        )
        for p in CASUS.bank_open_posten()
    }
    return {"mutaties": mutaties, "posten": posten}


def _per_sleutel(administratie_id: uuid.UUID, cv_bank: dict) -> dict[str, voorstellen.MutatieMetVoorstel]:
    op_id = {m.mutatie.id: m for m in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)}
    return {sleutel: op_id[mutatie_id] for sleutel, mutatie_id in cv_bank["mutaties"].items()}


class TestProductiegevallenGevenGeenOpenPostVoorstel:
    def test_geval_a_bijschrijving_privepersoon_matcht_niet_op_substring_van_het_kenmerk(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["A"]
        assert rij.mutatie.bedrag == Decimal("12500.00")
        assert rij.voorstel.soort == VoorstelSoort.HANDMATIG, rij.voorstel
        assert rij.voorstel.payment_item_id is None and rij.open_post is None
        assert "naam + referentie" not in rij.voorstel.bron

    def test_geval_b_afschrijving_matcht_nooit_een_verkoopfactuur(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["B"]
        assert rij.mutatie.bedrag == Decimal("-99.99")
        assert rij.voorstel.soort == VoorstelSoort.HANDMATIG, rij.voorstel
        assert rij.voorstel.payment_item_id is None

    def test_de_verkoopfacturen_2352_en_2337_blijven_onaangeroerd_open(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        voorgesteld = {
            rij.voorstel.payment_item_id
            for rij in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if rij.voorstel.payment_item_id is not None
        }
        assert cv_bank["posten"]["2352"] not in voorgesteld
        assert cv_bank["posten"]["2337"] not in voorgesteld


class TestGoedeMatchesBlijvenGroen:
    def test_transip_24_08_is_groen_op_naam_nummer_bedrag(self, administratie_id: uuid.UUID, cv_bank: dict) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["TRANSIP"]
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH, rij.voorstel
        assert rij.voorstel.kleur == "groen"
        assert rij.voorstel.bron == "naam + nummer + bedrag"
        assert rij.voorstel.payment_item_id == cv_bank["posten"]["TRANSIP"]
        assert rij.open_post is not None and rij.open_post.documentsoort == "Inkoopfactuur"

    def test_npg_2026053_is_groen_op_naam_nummer_bedrag(self, administratie_id: uuid.UUID, cv_bank: dict) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["NPG"]
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH, rij.voorstel
        assert rij.voorstel.bron == "naam + nummer + bedrag"
        assert rij.voorstel.payment_item_id == cv_bank["posten"]["NPG"]

    def test_alleen_de_groene_gevallen_zijn_auto_afletter_kandidaat(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        """Wat `afletteren.verwerk_exacte_matches_automatisch` zou oppakken (achter de opt-in): exact TransIP + NPG."""
        kandidaten = {
            sleutel
            for sleutel, rij in _per_sleutel(administratie_id, cv_bank).items()
            if rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH and rij.voorstel.payment_item_id is not None
        }
        assert kandidaten == {"TRANSIP", "NPG"}


# --- blok B bundel 10-09: historie-regel (stap 3b) op de C.V.-casus -----------------------------------------------


@pytest.fixture
def cv_historie(administratie_id: uuid.UUID, admin_engine: Engine, cv_bank: dict) -> uuid.UUID:
    """Vijfde open mutatie (huur, geen open post) + drie eerdere RLZ-grootboekboekingen in de historie-cache
    (`fixtures/l_bank_cv_08-09/historie.json`). De vier bestaande mutaties blijven ongewijzigd. Datums relatief aan de
    BEVROREN referentiedag (blok 3 nachtrun 10/11-09) — de export mag niet met de kalender meelopen."""
    vandaag = REFERENTIE_DATUM
    data = CASUS.bank_historie()
    gb = data["grootboek"]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.grootboekrekening "
                "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                "VALUES (:id, :aid, :code, :naam, 2, false)"
            ),
            {"id": uuid.UUID(gb["ledger_id"]), "aid": administratie_id, "code": gb["code"], "naam": gb["naam"]},
        )
        for b in data["boekingen"]:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.bank_historie_boeking "
                    "(id, administratie_id, payment_transaction_id, datum, "
                    "tegenrekening_iban, omschrijving, tegenpartij_naam, ledger_id, taxrate_id, bron) VALUES "
                    "(:id, :aid, :tx, :datum, :iban, :oms, :naam, :ledger, NULL, :bron)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "tx": uuid.UUID(b["payment_transaction_id"]),
                    "datum": vandaag - timedelta(days=b["dagen_terug"]),
                    "iban": data["mutatie"]["tegenrekening_iban"],
                    "oms": b["omschrijving"],
                    "naam": data["mutatie"]["tegenpartij_naam"],
                    "ledger": uuid.UUID(gb["ledger_id"]),
                    "bron": b["bron"],
                },
            )
    m = data["mutatie"]
    return maak_bank_mutatie(
        admin_engine,
        administratie_id=administratie_id,
        mutatie_id=uuid.UUID(m["id"]),
        payment_account_id=REKENING_ID,
        bedrag=m["bedrag"],
        tegenpartij_naam=m["tegenpartij_naam"],
        omschrijving=m["omschrijving"],
        tegenrekening_iban=m["tegenrekening_iban"],
        boekdatum=(vandaag - timedelta(days=m["dagen_terug"])).isoformat(),
    )


class TestHistorieRegelOpDeCv:
    def test_huur_zonder_open_post_krijgt_groene_historie_regel_3_van_3(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        rij = next(
            r
            for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_historie
        )
        assert rij.voorstel.soort == VoorstelSoort.HISTORIE_REGEL, rij.voorstel
        assert rij.voorstel.kleur == "groen"
        assert rij.voorstel.bron == "historie: 3 van 3 op 4400 Huur onroerend goed"
        assert (rij.voorstel.historie_k, rij.voorstel.historie_n) == (3, 3)
        assert rij.voorstel.ledger_id == uuid.UUID(CASUS.bank_historie()["grootboek"]["ledger_id"])
        # Concrete boekregels (btw-splitsing in code): één regel die het mutatiebedrag exact dekt.
        assert len(rij.regel_boekregels) == 1 and rij.regel_boekregels[0].netto_bedrag == Decimal("-1815.00")
        assert rij.ai_toets is None  # nog niet getoetst — de nachtelijke autoflow doet dat

    def test_de_vier_bestaande_cv_mutaties_krijgen_geen_historie_voorstel(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        """A/B blijven handmatig, TransIP/NPG groen op de open post — de historie raakt ze niet (andere IBAN/kern)."""
        per_sleutel = _per_sleutel(administratie_id, cv_bank)
        assert per_sleutel["A"].voorstel.soort == VoorstelSoort.HANDMATIG
        assert per_sleutel["B"].voorstel.soort == VoorstelSoort.HANDMATIG
        assert per_sleutel["TRANSIP"].voorstel.soort == VoorstelSoort.EXACTE_MATCH
        assert per_sleutel["NPG"].voorstel.soort == VoorstelSoort.EXACTE_MATCH

    def test_dto_draagt_historie_velden_en_ai_toets_kolommen(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        """Wat de frontend (VoorstelKaart/BankDetailScreen) krijgt: soort historie_regel, historie_k/n, ai_toets_*."""
        from app.bank import schemas
        from app.bank.router import _voorstel_response

        rij = next(
            r
            for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_historie
        )
        dto = _voorstel_response(rij)
        assert (dto.soort, dto.historie_k, dto.historie_n) == ("historie_regel", 3, 3)
        assert dto.ledger_id is not None and dto.regels[0].ledger_id == dto.ledger_id
        assert set(schemas.MutatieResponse.model_fields) >= {"ai_toets_uitkomst", "ai_toets_reden", "ai_toets_op"}


# --- blok 3 nachtrun 10/11-09: deels afgeletterde mutaties (Zilver Beheer 10-09) ------------------------------------


@pytest.fixture
def cv_deels(administratie_id: uuid.UUID, admin_engine: Engine, cv_bank: dict) -> dict[str, uuid.UUID]:
    """Mutatie A (01-07 +5.023,09, in RLZ gekoppeld 2.512,04 aan verkoopfactuur 2024840 RLZ-01-00000800, open 2.511,05)
    en mutatie B (08-09 −2.511,05 'retour dubbele betaling', zelfde tegenpartij), zoals de sync-verversronde ze in
    `bank_mutatie` zet (open_bedrag + rlz_koppelingen, migratie 0131). Geen open post voor het restant."""
    return {
        m["sleutel"]: maak_bank_mutatie(
            admin_engine,
            administratie_id=administratie_id,
            mutatie_id=uuid.UUID(m["id"]),
            payment_account_id=REKENING_ID,
            bedrag=m["bedrag"],
            open_bedrag=m["open_bedrag"],
            tegenpartij_naam=m["tegenpartij_naam"],
            omschrijving=m["omschrijving"],
            tegenrekening_iban=m["tegenrekening_iban"],
            boekdatum=m["boekdatum"],
            rlz_koppelingen=m["rlz_koppelingen"],
        )
        for m in DEELS["mutaties"]
    }


def _rlz_record(m: dict) -> dict:
    """De verse RLZ-staat van een fixture-mutatie zoals `GET PaymentTransactions/{id}?$expand=PaymentReferenceList(...)`
    'm geeft — de FakeBankClient speelt 'm af voor de duplicaatcheck vóór de PUT."""
    return {
        "id": m["id"],
        "Amount": float(m["bedrag"]),
        "OpenAmount": float(m["open_bedrag"]),
        "BookDate": f"{m['boekdatum']}T00:00:00",
        "Name": m["tegenpartij_naam"],
        "Reference": m["omschrijving"],
        "CounterAccount": m["tegenrekening_iban"],
        "PaymentReferenceList": list(m["rlz_payment_reference_list"]),
    }


@pytest.fixture
def bank_api(
    gescoopte_gebruiker: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, dict, FakeBankClient]:
    """De kantoor-frontend-kant: TestClient mét een gescoopte boekhouding-gebruiker; de RLZ-client van de bankrouter is
    de FakeBankClient met de verse staat van A en B (nooit een echte RLZ-call in de gouden set)."""
    from app.bank import router as bank_router

    rlz = FakeBankClient(transacties={m["id"]: _rlz_record(m) for m in DEELS["mutaties"]})
    monkeypatch.setattr(bank_router, "_rlz_client_voor", lambda administratie_id: rlz)
    headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
    return TestClient(app), headers, rlz


def _mutaties_dto(api: TestClient, headers: dict, administratie_id: uuid.UUID) -> dict:
    resp = api.get(f"/administraties/{administratie_id}/bank/rekeningen/{REKENING_ID}/mutaties", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _direct_boeken(api: TestClient, headers: dict, administratie_id: uuid.UUID, mutatie_id: str, bedrag: str):
    return api.post(
        f"/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/direct-boeken",
        json={
            "regels": [{"ledger_id": "ffffffff-0000-4000-8000-000000001300", "netto_bedrag": bedrag}],
            "omschrijving": "Dubbele betaling — te verrekenen",
            "bron": "handmatig",
        },
        headers=headers,
    )


class TestDeelsAfgeletterdeMutatie:
    def test_a_voorstel_toetst_het_open_bedrag_en_is_handmatig_zonder_open_post(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_deels: dict
    ) -> None:
        rij = next(
            r for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_deels["A_ZILVER"]
        )
        assert (rij.mutatie.bedrag, rij.mutatie.open_bedrag) == (Decimal("5023.09"), Decimal("2511.05"))
        assert rij.mutatie.te_verwerken_bedrag == Decimal("2511.05")  # dé maat voor voorstel én boeken
        assert rij.deels_afgeletterd is True
        assert rij.rlz_koppelingen == DEELS["mutaties"][0]["rlz_koppelingen"]
        # Geen open post voor het restant (2024840 is in RLZ al gekoppeld) → handmatig, en zeker geen
        # 'handmatig 5.023,09'.
        assert rij.voorstel.soort == VoorstelSoort.HANDMATIG and rij.voorstel.payment_item_id is None
        assert rij.regel_boekregels == []

    def test_a_met_open_post_voor_het_restant_matcht_op_2511_05_niet_op_het_totaal(
        self, administratie_id: uuid.UUID, admin_engine: Engine, cv_bank: dict, cv_deels: dict
    ) -> None:
        """Bewijs dat de motor 2.511,05 toetst: een verkoopfactuur 2024841 van precies het restant = groen; het totaal
        (5.023,09) als post zou hooguit oranje 'bedrag wijkt af' zijn."""
        a = DEELS["mutaties"][0]
        post = maak_payment_item(
            admin_engine, administratie_id=administratie_id, bedrag="2511.05", referentie="2024841",
            documentsoort="Verkoopfactuur", entity_naam=a["tegenpartij_naam"],
        )
        rij = next(
            r for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_deels["A_ZILVER"]
        )
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH and rij.voorstel.payment_item_id == post
        assert rij.voorstel.bron == "naam + nummer + bedrag"

    def test_b_retour_is_handmatig_en_de_vier_cv_gevallen_blijven_gelijk(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_deels: dict
    ) -> None:
        per_id = {r.mutatie.id: r for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)}
        b = per_id[cv_deels["B_ZILVER"]]
        assert b.voorstel.soort == VoorstelSoort.HANDMATIG and b.deels_afgeletterd is False and b.rlz_koppelingen == []
        assert per_id[cv_bank["mutaties"]["TRANSIP"]].voorstel.soort == VoorstelSoort.EXACTE_MATCH
        assert per_id[cv_bank["mutaties"]["NPG"]].voorstel.soort == VoorstelSoort.EXACTE_MATCH
        assert per_id[cv_bank["mutaties"]["A"]].voorstel.soort == VoorstelSoort.HANDMATIG
        assert per_id[cv_bank["mutaties"]["B"]].voorstel.soort == VoorstelSoort.HANDMATIG

    def test_dto_draagt_open_bedrag_chipvelden_en_koppeling(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_deels: dict, bank_api: tuple
    ) -> None:
        api, headers, _ = bank_api
        per_id = {m["id"]: m for m in _mutaties_dto(api, headers, administratie_id)["mutaties"]}
        a = per_id[str(cv_deels["A_ZILVER"])]
        assert (a["bedrag"], a["open_bedrag"], a["deels_afgeletterd"]) == ("5023.09", "2511.05", True)
        assert a["rlz_koppelingen"] == [
            {
                "document_id": "eeeeeeee-0000-4000-8000-000000000800",
                "boekstuknummer": "RLZ-01-00000800",
                "referentie": "2024840",
                "bedrag": "2512.04",
                "document_type": 10,
                "omschrijving": "Verkoopfactuur 2024840",
            }
        ]
        b = per_id[str(cv_deels["B_ZILVER"])]
        assert (b["bedrag"], b["open_bedrag"], b["deels_afgeletterd"], b["rlz_koppelingen"]) == (
            "-2511.05", "-2511.05", False, [],
        )

    def test_boeken_van_het_totaal_is_409_met_leesbare_reden_en_open_bedrag_boekt(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_deels: dict, bank_api: tuple, boeken_aan: None  # noqa: F811
    ) -> None:
        api, headers, rlz = bank_api
        a_id = str(cv_deels["A_ZILVER"])
        fout = _direct_boeken(api, headers, administratie_id, a_id, "5023.09")
        assert fout.status_code == 409, fout.text
        assert fout.json()["detail"].startswith(DEKKING_FOUT_PREFIX), fout.json()["detail"]
        assert "2511.05" in fout.json()["detail"] and "2512.04" in fout.json()["detail"]
        assert rlz.direct_bookings == {}  # geen byte richting RLZ

        ok = _direct_boeken(api, headers, administratie_id, a_id, "2511.05")
        assert ok.status_code == 200, ok.text
        assert ok.json()["rlz_boekstuknummer"] and ok.json()["al_eerder_geboekt"] is False
        assert rlz.transacties[a_id]["OpenAmount"] == 0
        # De mutatie is dicht en uit de open lijst; B staat er nog (handmatig — verrekening is blok 3.4).
        ids_open = {m["id"] for m in _mutaties_dto(api, headers, administratie_id)["mutaties"]}
        assert a_id not in ids_open and str(cv_deels["B_ZILVER"]) in ids_open


# --- export voor het frontend-harnas (keten_sweep.sh, scherm=bank) -------------------------------------------------


def _exporteer_bank(api: TestClient, headers: dict, administratie_id: uuid.UUID, *, doel: Path) -> Path:
    """Schrijft de drie DTO's die het bankscherm bij openen ophaalt in de vorm die `visueelHarnasKeten.tsx`
    (scherm=bank) leest: `{casus, administratie_id, administratie_naam, bank: {rekening_id, rekeningen, mutaties,
    afletter_opdrachten}}`.
    Zelfde normalisatie als `Keten.exporteer` (UUID's → placeholders, tijdstippen → EXPORT_TIJDSTIP); de fixture-id's
    (mutaties, posten, rekening, grootboek, koppeling-document) zijn al vast en blijven staan."""
    basis = f"/administraties/{administratie_id}/bank"
    rekeningen = api.get(f"{basis}/rekeningen", headers=headers)
    mutaties = api.get(f"{basis}/rekeningen/{REKENING_ID}/mutaties", headers=headers)
    opdrachten = api.get(f"{basis}/rekeningen/{REKENING_ID}/afletter-opdrachten", headers=headers)
    for resp in (rekeningen, mutaties, opdrachten):
        assert resp.status_code == 200, resp.text
    vaste = {str(administratie_id).lower(): EXPORT_ADMINISTRATIE_ID}
    vaste_ids = [REKENING_ID, uuid.UUID(CASUS.bank_historie()["grootboek"]["ledger_id"])]
    vaste_ids += [uuid.UUID(m["id"]) for m in CASUS.bank_mutaties() + DEELS["mutaties"]]
    vaste_ids += [uuid.UUID(CASUS.bank_historie()["mutatie"]["id"])]
    for p in CASUS.bank_open_posten():
        vaste_ids += [uuid.UUID(p["id"]), uuid.UUID(p["rlz_document_id"]), uuid.UUID(p["entity_guid"])]
    for m in DEELS["mutaties"]:
        vaste_ids += [uuid.UUID(k["document_id"]) for k in m["rlz_koppelingen"]]
    vaste.update({str(x).lower(): str(x).lower() for x in vaste_ids})
    payload = {
        "casus": CASUS.naam,
        "administratie_id": EXPORT_ADMINISTRATIE_ID,
        "administratie_naam": CV_NAAM,
        "bank": {
            "rekening_id": str(REKENING_ID),
            "rekeningen": rekeningen.json(),
            "mutaties": mutaties.json(),
            "afletter_opdrachten": opdrachten.json(),
        },
    }
    doel.mkdir(exist_ok=True, parents=True)
    pad = doel / f"{CASUS.naam}.json"
    pad.write_text(
        json.dumps(normaliseer_voor_export(payload, vaste_ids=vaste), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return pad


class TestExportBankscherm:
    def test_export_is_deterministisch_en_vervangt_de_contract_fixture(
        self,
        administratie_id: uuid.UUID,
        cv_bank: dict,
        cv_historie: uuid.UUID,
        cv_deels: dict,
        bank_api: tuple,
        tmp_path: Path,
    ) -> None:
        """De volledige C.V.-stand (vier 08-09-gevallen + huur/historie-regel + A/B Zilver) als frontend-fixture: twee
        exports byte-gelijk, geen datum van de echte klok (de referentiedag is gepind), en — als de frontend-map in deze
        checkout staat — geschreven naar frontend/src/dev/keten/l_bank_cv_08-09.json (vervangt N3b's
        contract-fixture)."""
        api, headers, _ = bank_api
        eerste = _exporteer_bank(api, headers, administratie_id, doel=tmp_path / "1")
        tweede = _exporteer_bank(api, headers, administratie_id, doel=tmp_path / "2")
        assert eerste.read_bytes() == tweede.read_bytes()
        tekst = eerste.read_text(encoding="utf-8")
        if echte_vandaag_nl() != REFERENTIE_DATUM:
            assert echte_vandaag_nl().isoformat() not in tekst
        data = json.loads(tekst)
        assert data["administratie_id"] == EXPORT_ADMINISTRATIE_ID and data["bank"]["rekening_id"] == str(REKENING_ID)
        mutaties = {m["id"]: m for m in data["bank"]["mutaties"]["mutaties"]}
        assert len(mutaties) == 7
        a = mutaties[DEELS["mutaties"][0]["id"]]
        assert a["deels_afgeletterd"] is True and a["open_bedrag"] == "2511.05" and len(a["rlz_koppelingen"]) == 1
        assert mutaties[CASUS.bank_historie()["mutatie"]["id"]]["voorstel"]["soort"] == "historie_regel"
        assert data["bank"]["rekeningen"]["rekeningen"][0]["open_mutaties"] == 7
        if FRONTEND_KETEN_DIR.parent.exists():
            geschreven = _exporteer_bank(api, headers, administratie_id, doel=FRONTEND_KETEN_DIR)
            assert geschreven.read_bytes() == eerste.read_bytes()
