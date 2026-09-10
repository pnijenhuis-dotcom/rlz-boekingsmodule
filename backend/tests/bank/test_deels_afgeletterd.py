"""Deels afgeletterde bankmutaties — het OPEN bedrag is de maat (blok 3 nachtrun 10/11-09; bug Peter 10-09 avond,
Zilver Beheer: mutatie 01-07 +5.023,09 in RLZ gekoppeld aan verkoopfactuur 2024840 € 2.512,04 (RLZ-01-00000800),
open 2.511,05 — de module toonde, toetste en boekte het totaal).

Geldlogica, dus volledig getest vóór UI-werk:
- matchmotor: bedrag-exact en teken toetsen het open bedrag;
- boeken: dekking = open bedrag (409-tekst begint met het contract-voorvoegsel), verse RLZ-afwijking = weigeren;
- vaste regel / historie-regel / autoflow: boekregels op het open bedrag;
- splitsen: delen verdelen het open bedrag;
- sync: verversronde haalt OpenAmount én de koppelingen (PaymentReferenceList) op; batch zonder leesspoor wist ze niet;
- DTO + CLI: `deels_afgeletterd`, `rlz_koppelingen`, `5023.09/open 2511.05`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import boeken, matchmotor, splitsen, sync, voorstellen
from app.bank.boeken import DEKKING_FOUT_PREFIX, BankBoekRegelInput
from app.bank.matchmotor import MutatieGegevens, OpenPost, VoorstelSoort
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_payment_item

TOTAAL = Decimal("5023.09")
OPEN = Decimal("2511.05")
GEKOPPELD = Decimal("2512.04")
DEBITEUR = "Debiteur Z Beheer B.V."
KOPPELING_RLZ = {
    "id": "11111111-0000-4000-8000-000000000001",
    "Sequence": 1,
    "Amount": -2512.04,
    "PaymentReconciliationSource": 1,
    "Document": {
        "id": "eeeeeeee-0000-4000-8000-000000000800",
        "ReceiptNumber": "RLZ-01-00000800",
        "Reference": "2024840",
        "DocumentType": 10,
        "Status": 3,
        "Description": "Verkoopfactuur 2024840",
        "IsSystemGenerated": False,
    },
}
KOPPELING_CACHE = {
    "document_id": "eeeeeeee-0000-4000-8000-000000000800",
    "boekstuknummer": "RLZ-01-00000800",
    "referentie": "2024840",
    "bedrag": "2512.04",
    "document_type": 10,
    "omschrijving": "Verkoopfactuur 2024840",
}


def _mutatie(bedrag: str = "5023.09", open_bedrag: str | None = "2511.05") -> MutatieGegevens:
    return MutatieGegevens(
        id=uuid.uuid4(),
        bedrag=Decimal(bedrag),
        open_bedrag=Decimal(open_bedrag) if open_bedrag is not None else None,
        tegenpartij_naam=DEBITEUR,
        omschrijving="Factuur 2024840 en 2024841",
        tegenrekening_iban="NL83RABO0198765432",
        rlz_voorstel_item_id=None,
    )


def _post(bedrag: str, referentie: str = "2024841") -> OpenPost:
    return OpenPost(
        id=uuid.uuid4(),
        bedrag=Decimal(bedrag),
        referentie=referentie,
        referentie2=None,
        rlz_document_id=uuid.uuid4(),
        tegenpartij_naam=DEBITEUR,
        documentsoort="Verkoopfactuur",
    )


def _tx(
    mutatie_id: uuid.UUID, *, bedrag: Decimal = TOTAAL, open_bedrag: Decimal = OPEN, met_koppeling: bool = True
) -> dict:
    return {
        "id": str(mutatie_id),
        "Amount": float(bedrag),
        "OpenAmount": float(open_bedrag),
        "BookDate": "2026-07-01T00:00:00",
        "CreateDate": "2026-07-01T06:00:00",
        "Name": DEBITEUR,
        "Reference": "Factuur 2024840 en 2024841",
        "CounterAccount": "NL83RABO0198765432",
        "PaymentReferenceList": [KOPPELING_RLZ] if met_koppeling else [],
    }


def _regels(bedrag: Decimal, ledger_id: uuid.UUID | None = None) -> list[BankBoekRegelInput]:
    return [BankBoekRegelInput(ledger_id=ledger_id or uuid.uuid4(), netto_bedrag=bedrag, btw_bedrag=None)]


# --- pure helpers + matchmotor ------------------------------------------------------------------------------------


class TestOpenBedragIsDeMaat:
    def test_te_verwerken_bedrag_is_open_met_terugval_totaal(self) -> None:
        assert _mutatie().te_verwerken_bedrag == OPEN
        assert _mutatie(open_bedrag=None).te_verwerken_bedrag == TOTAAL
        assert matchmotor.open_bedrag_van(None, None) is None

    def test_is_deels_afgeletterd(self) -> None:
        assert matchmotor.is_deels_afgeletterd(TOTAAL, OPEN) is True
        assert matchmotor.is_deels_afgeletterd(TOTAAL, TOTAAL) is False
        assert matchmotor.is_deels_afgeletterd(TOTAAL, Decimal("0")) is False  # dicht, niet "deels"
        assert matchmotor.is_deels_afgeletterd(TOTAAL, None) is False
        assert matchmotor.is_deels_afgeletterd(None, OPEN) is False

    def test_exacte_match_toetst_het_open_bedrag_niet_het_totaal(self) -> None:
        """Zilver Beheer: een verkoopfactuur van 2.511,05 (het restant) is een groene match; een post van 5.023,09
        (het totaal) is dat NIET meer — die zou dubbel koppelen wat RLZ al deels gekoppeld heeft."""
        mutatie = _mutatie()
        op_restant = matchmotor.bepaal_voorstel(mutatie, open_posten=[_post("2511.05")], vaste_regels=[])
        assert op_restant.soort == VoorstelSoort.EXACTE_MATCH and op_restant.bron == "naam + nummer + bedrag"
        op_totaal = matchmotor.bepaal_voorstel(mutatie, open_posten=[_post("5023.09")], vaste_regels=[])
        assert op_totaal.soort == VoorstelSoort.DEEL_MATCH, op_totaal  # naam + nummer, bedrag wijkt af → bevestigen
        assert "bedrag wijkt af" in op_totaal.bron

    def test_teken_toets_op_open_bedrag(self) -> None:
        assert matchmotor.teken_toets(_mutatie(), _post("2511.05")) == matchmotor.TEKEN_OK
        # Open bedrag negatief (retour) tegen een verkoop-post = mismatch, ook al is het totaal positief.
        assert matchmotor.teken_toets(_mutatie("100.00", "-40.00"), _post("40.00")) == matchmotor.TEKEN_MISMATCH


# --- boeken -------------------------------------------------------------------------------------------------------


class TestBoekenOpHetOpenBedrag:
    def test_totaal_boeken_weigert_met_leesbare_reden(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05",
            tegenpartij_naam=DEBITEUR, rlz_koppelingen=[KOPPELING_CACHE],
        )
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        with pytest.raises(boeken.RegelsDekkenMutatieNiet) as exc:
            boeken.boek_mutatie_direct(
                administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                regels=_regels(TOTAAL), actor_id=beheerder_id, client=client,
            )
        tekst = str(exc.value)
        assert tekst.startswith(DEKKING_FOUT_PREFIX)
        assert "5023.09" in tekst and "2511.05" in tekst and "2512.04 gekoppeld" in tekst
        assert client.direct_bookings == {}  # geen byte richting RLZ

    def test_open_bedrag_boeken_lukt_en_sluit_de_mutatie(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05",
            tegenpartij_naam=DEBITEUR, rlz_koppelingen=[KOPPELING_CACHE],
        )
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        resultaat = boeken.boek_mutatie_direct(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            regels=_regels(OPEN), actor_id=beheerder_id, client=client,
        )
        document = client.direct_bookings[str(resultaat.rlz_document_id)]
        assert document["DocumentLineList"][0]["NetAmount"] == 2511.05
        assert client.transacties[str(mutatie_id)]["OpenAmount"] == 0
        with admin_engine.connect() as conn:
            open_bedrag = conn.execute(
                text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}
            ).scalar_one()
        assert open_bedrag == Decimal("0")

    def test_verouderde_lokale_stand_weigert_tegen_verse_rlz(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        """Lokaal nog 'volledig open' (sync liep achter), RLZ zegt open 2.511,05: nooit 5.023,09 boeken."""
        mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="5023.09")
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        with pytest.raises(boeken.MutatieAlAfgeletterd) as exc:
            boeken.boek_mutatie_direct(
                administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                regels=_regels(TOTAAL), actor_id=beheerder_id, client=client,
            )
        assert str(exc.value).startswith(DEKKING_FOUT_PREFIX) and "ververs" in str(exc.value)
        assert client.direct_bookings == {}

    def test_deel_mag_niet_groter_zijn_dan_het_open_bedrag(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05"
        )
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        with pytest.raises(boeken.RegelsDekkenMutatieNiet) as exc:
            boeken.boek_mutatie_direct(
                administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                regels=_regels(Decimal("3000.00")), actor_id=beheerder_id, client=client,
                deel=boeken.DeelBoeking(deel_id=uuid.uuid4(), bedrag=Decimal("3000.00")),
            )
        assert str(exc.value).startswith(DEKKING_FOUT_PREFIX)

    def test_regels_uit_vaste_regel_en_historie_dekken_het_open_bedrag(self) -> None:
        from types import SimpleNamespace

        regel = SimpleNamespace(ledger_id=uuid.uuid4(), taxrate_id=None, project_id=None, omschrijving=None)
        via_regel = boeken.regel_naar_boekregels(
            regel=regel, mutatie_bedrag=_mutatie().te_verwerken_bedrag, btw_percentage=Decimal("0.21")
        )
        assert sum(r.netto_bedrag + (r.btw_bedrag or 0) for r in via_regel) == OPEN
        voorstel = matchmotor.Voorstel(
            soort=VoorstelSoort.HISTORIE_REGEL, kleur="groen", bron="historie", reden="", ledger_id=uuid.uuid4()
        )
        via_historie = boeken.historie_naar_boekregels(voorstel=voorstel, mutatie=_mutatie(), btw_percentage=None)
        assert via_historie[0].netto_bedrag == OPEN


# --- splitsen -----------------------------------------------------------------------------------------------------


class TestSplitsenOpHetOpenBedrag:
    def test_delen_verdelen_het_open_bedrag(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05",
            tegenpartij_naam=DEBITEUR,
        )
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        gb_a, gb_b = uuid.uuid4(), uuid.uuid4()
        delen = [
            splitsen.DeelInvoer(
                soort="grootboek", bedrag=Decimal("2000.00"),
                spec={"regels": [{"ledger_id": str(gb_a), "netto_bedrag": "2000.00"}]},
            ),
            splitsen.DeelInvoer(
                soort="grootboek", bedrag=Decimal("511.05"),
                spec={"regels": [{"ledger_id": str(gb_b), "netto_bedrag": "511.05"}]},
            ),
        ]
        r = splitsen.start_splitsing(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, delen=delen,
            actor_id=beheerder_id, client=client,
        )
        assert r.status == "verwerkt" and r.mutatie_bedrag == OPEN
        assert client.transacties[str(mutatie_id)]["OpenAmount"] == 0

    def test_delen_op_het_totaal_weigeren_met_uitleg(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
    ) -> None:
        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05"
        )
        client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
        delen = [
            splitsen.DeelInvoer(
                soort="grootboek", bedrag=Decimal("2511.05"),
                spec={"regels": [{"ledger_id": str(uuid.uuid4()), "netto_bedrag": "2511.05"}]},
            ),
            splitsen.DeelInvoer(
                soort="grootboek", bedrag=Decimal("2512.04"),
                spec={"regels": [{"ledger_id": str(uuid.uuid4()), "netto_bedrag": "2512.04"}]},
            ),
        ]
        with pytest.raises(splitsen.SplitsingOngeldig) as exc:
            splitsen.start_splitsing(
                administratie_id=administratie_id, payment_transaction_id=mutatie_id, delen=delen,
                actor_id=beheerder_id, client=client,
            )
        assert "te verdelen is het open bedrag 2511.05" in str(exc.value) and "2512.04 gekoppeld" in str(exc.value)
        assert client.direct_bookings == {}


# --- sync ---------------------------------------------------------------------------------------------------------


class TestSyncVerversrondeMetKoppelingen:
    def test_koppelingen_uit_record_filtert_hulzen_en_kent_geen_leesspoor(self) -> None:
        record = _tx(uuid.uuid4())
        record["PaymentReferenceList"].append(
            {"id": "x", "Amount": -2511.05, "Document": {"id": str(uuid.uuid4()), "DocumentType": 19, "Status": 1}}
        )
        assert sync._koppelingen_uit_record(record) == [KOPPELING_CACHE]
        assert sync._koppelingen_uit_record({"id": "y", "Amount": 1.0}) is None  # lijst-GET zonder expand
        assert sync._koppelingen_uit_record({"id": "z", "PaymentReferenceList": []}) == []

    def test_verversronde_haalt_open_bedrag_en_koppelingen_op_en_batch_wist_ze_niet(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Ronde 1: mutatie komt volledig open binnen (lijst-GET, geen leesspoor). Peter koppelt in RLZ 2.512,04.
        Ronde 2: verversronde → open 2.511,05 + koppeling. Ronde 3: de batch levert 'm zonder leesspoor opnieuw
        (ge-overlap) → koppelingen blijven staan. Ronde 4: RLZ boekt het restant weg → open 0, uit de lijst."""
        mutatie_id = uuid.uuid4()
        record = _tx(mutatie_id, open_bedrag=TOTAAL, met_koppeling=False)
        lijst_record = {k: v for k, v in record.items() if k != "PaymentReferenceList"}

        class Client(FakeBankClient):
            def list_payment_transactions(self, *, params=None):  # lijst-GET zonder leesspoor, zoals RLZ
                rijen = super().list_payment_transactions(params=params)
                return [{k: v for k, v in r.items() if k != "PaymentReferenceList"} for r in rijen]

        client = Client(transacties={str(mutatie_id): {**record}})
        sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
        assert client.transacties  # sanity
        assert _rij(admin_engine, mutatie_id) == (TOTAAL, TOTAAL, None)

        client.transacties[str(mutatie_id)].update({"OpenAmount": float(OPEN), "PaymentReferenceList": [KOPPELING_RLZ]})
        telling = sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
        assert telling.open_ververst == 1
        assert _rij(admin_engine, mutatie_id) == (TOTAAL, OPEN, [KOPPELING_CACHE])

        # Ronde 3: zelfde CreateDate → de batch (ge-filter) levert 'm zonder leesspoor; deels-afgeletterd → tóch
        # nagelezen in de verversronde, koppelingen blijven.
        sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
        assert _rij(admin_engine, mutatie_id) == (TOTAAL, OPEN, [KOPPELING_CACHE])
        assert lijst_record["Amount"] == float(TOTAAL)

        # Ronde 4 (Delta Energie/VHK-geval 10-09): in RLZ weggeboekt → OpenAmount 0 → uit de open lijst.
        client.transacties[str(mutatie_id)]["OpenAmount"] = 0
        sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
        assert _rij(admin_engine, mutatie_id)[1] == Decimal("0")
        assert voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id) == []

    def test_verversronde_expand_draagt_het_leesspoor(self) -> None:
        assert "PaymentReferenceList($expand=Document)" in sync.VERVERS_EXPAND


def _rij(admin_engine: Engine, mutatie_id: uuid.UUID) -> tuple:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT bedrag, open_bedrag, rlz_koppelingen FROM boekhouding.bank_mutatie WHERE id = :id"),
            {"id": mutatie_id},
        ).one()
    return (rij[0], rij[1], rij[2])


# --- servicelaag, DTO en CLI --------------------------------------------------------------------------------------


class TestDtoEnCli:
    def test_servicelaag_en_dto_dragen_deels_afgeletterd_en_koppelingen(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.bank import schemas
        from app.bank.router import _koppeling_response

        mutatie_id = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="5023.09", open_bedrag="2511.05",
            tegenpartij_naam=DEBITEUR, omschrijving="Factuur 2024840 en 2024841", rlz_koppelingen=[KOPPELING_CACHE],
        )
        # Een verkoop-post van 2.511,05 van dezelfde debiteur: de servicelaag toetst het OPEN bedrag → groen.
        post_id = maak_payment_item(
            admin_engine, administratie_id=administratie_id, bedrag="2511.05", referentie="2024841",
            documentsoort="Verkoopfactuur", entity_naam=DEBITEUR,
        )
        rij = next(
            r for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == mutatie_id
        )
        assert rij.deels_afgeletterd is True and rij.rlz_koppelingen == [KOPPELING_CACHE]
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH and rij.voorstel.payment_item_id == post_id
        dto = _koppeling_response(rij.rlz_koppelingen[0])
        assert (dto.boekstuknummer, dto.referentie, dto.bedrag, dto.document_type) == (
            "RLZ-01-00000800", "2024840", Decimal("2512.04"), 10,
        )
        assert dto.document_id == uuid.UUID("eeeeeeee-0000-4000-8000-000000000800")
        assert set(schemas.MutatieResponse.model_fields) >= {"deels_afgeletterd", "rlz_koppelingen"}
        assert schemas.MutatieResponse.model_fields["deels_afgeletterd"].default is False

    def test_cli_toont_totaal_slash_open(
        self, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from types import SimpleNamespace

        from app import cli

        aid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
                {"id": aid, "naam": "Zilver Beheer (test)", "rlz": f"rlz-{aid}"},
            )
        rij = SimpleNamespace(
            mutatie=_mutatie(), boekdatum="2026-07-01", open_post=None, deels_afgeletterd=True,
            rlz_koppelingen=[KOPPELING_CACHE],
            voorstel=SimpleNamespace(soort=VoorstelSoort.HANDMATIG, bron="handmatig", kleur="oranje"),
        )
        monkeypatch.setattr(voorstellen, "open_mutaties_met_voorstellen", lambda **kw: [rij])
        assert cli.main(["bank-voorstellen-lezen", "--administratie", "Zilver Beheer"]) == 0
        uit = capsys.readouterr().out
        assert "5023.09/open 2511.05" in uit and "Debiteur Z Beheer" in uit
