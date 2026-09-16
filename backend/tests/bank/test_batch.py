# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok C 16-09 (Peter, screenshot Bouwadvies Oost Nederland: batch −560.925,88 "TOTAAL 14 VZ betaalkenmerk: PREF",
deels afgeletterd, open 40.723,85): de matchmotor-stap "batch" uit STAP-0 batches 11-09 — bankregel en facturen dragen
dezelfde RLZ-sleutel (`PaymentBatchId` == `PaymentTermList.PaymentBatchInformation`). Motor puur (groen som cent-exact /
oranje mét verschil / R-transactie nooit / geen sleutel → stap 1–5), servicelaag via de DB-caches (brondata), N × actie
15 via `letter_batch_af` (idempotent per post, stop ná API-fout) en de route."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.bank import afletteren, doelpost, sync, voorstellen
from app.bank.matchmotor import MutatieGegevens, OpenPost, VoorstelSoort, bepaal_voorstel
from app.main import app
from app.rlz.client import RlzApiError
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_payment_item

SLEUTEL = "RLZEE_CT_20260915_101500_4471_0001"
D = Decimal


def _mutatie(
    *, bedrag: str, open_bedrag: str | None = None, sleutel: str | None = SLEUTEL, return_reason: str | None = None
):
    return MutatieGegevens(
        id=uuid.uuid4(),
        bedrag=D(bedrag),
        open_bedrag=D(open_bedrag if open_bedrag is not None else bedrag),
        tegenpartij_naam="TOTAAL 14 VZ",
        omschrijving="TOTAAL 14 VZ betaalkenmerk: PREF",
        tegenrekening_iban=None,
        rlz_voorstel_item_id=None,
        payment_batch_id=sleutel,
        return_reason=return_reason,
    )


def _post(
    bedrag: str, *, sleutel: str | None = SLEUTEL, soort: str = "Inkoopfactuur", ref: str = "92953485"
) -> OpenPost:
    return OpenPost(
        id=uuid.uuid4(),
        bedrag=D(bedrag),
        referentie=ref,
        referentie2=None,
        rlz_document_id=uuid.uuid4(),
        tegenpartij_naam="Leverancier",
        documentsoort=soort,
        klantreferentie=ref,
        batch_sleutel=sleutel,
    )


class TestMotor:
    def test_som_cent_exact_is_groen_met_alle_posten(self) -> None:
        posten = [_post("-1053.71", ref="92953485"), _post("-2000.00", ref="92953490"), _post("-0.29", ref="92953491")]
        v = bepaal_voorstel(
            _mutatie(bedrag="-3054.00"), open_posten=posten + [_post("-99.00", sleutel="ANDER")], vaste_regels=[]
        )
        assert v.soort == VoorstelSoort.BATCH and v.kleur == "groen"
        assert v.bron == f"betaalbatch {SLEUTEL}, 3 facturen"
        assert v.batch is not None and v.batch.aantal == 3 and v.batch.som == D("3054.00") and v.batch.sluit
        # Posten gesorteerd op factuurnummer (stabiel voor kaart en export).
        assert [p.klantreferentie for p in v.batch.posten] == ["92953485", "92953490", "92953491"]

    def test_som_ongelijk_is_oranje_met_verschil(self) -> None:
        v = bepaal_voorstel(
            _mutatie(bedrag="-3054.00"), open_posten=[_post("-1053.71"), _post("-2000.00")], vaste_regels=[]
        )
        assert v.soort == VoorstelSoort.BATCH and v.kleur == "oranje"
        assert v.batch is not None and v.batch.verschil == D("0.29") and not v.batch.sluit
        assert "verschil € 0,29" in v.bron and "2 facturen" in v.bron

    def test_deels_afgeletterde_batch_toetst_het_open_bedrag(self) -> None:
        # De casus: −560.925,88 totaal, open 40.723,85 — alleen de nog open posten van de batch tellen.
        v = bepaal_voorstel(
            _mutatie(bedrag="-560925.88", open_bedrag="-40723.85"),
            open_posten=[_post("-40000.00"), _post("-723.85")],
            vaste_regels=[],
        )
        assert v.kleur == "groen" and v.batch is not None and v.batch.open_bedrag == D("-40723.85")

    def test_r_transactie_of_geen_sleutel_of_geen_post_gaat_door_naar_stap_1_5(self) -> None:
        posten = [_post("-3054.00")]
        assert (
            bepaal_voorstel(
                _mutatie(bedrag="-3054.00", return_reason="AC04"), open_posten=posten, vaste_regels=[]
            ).soort
            != VoorstelSoort.BATCH
        )
        assert (
            bepaal_voorstel(_mutatie(bedrag="-3054.00", sleutel=None), open_posten=posten, vaste_regels=[]).soort
            != VoorstelSoort.BATCH
        )
        assert (
            bepaal_voorstel(_mutatie(bedrag="-3054.00", sleutel="  "), open_posten=posten, vaste_regels=[]).soort
            != VoorstelSoort.BATCH
        )
        geen = bepaal_voorstel(
            _mutatie(bedrag="-3054.00"), open_posten=[_post("-3054.00", sleutel="BETALER-KEY")], vaste_regels=[]
        )
        assert geen.soort == VoorstelSoort.HANDMATIG

    def test_tekenmismatch_post_telt_niet_mee(self) -> None:
        # Een verkoopfactuur (positief) met dezelfde sleutel hoort niet bij een afschrijvingsbatch.
        v = bepaal_voorstel(
            _mutatie(bedrag="-100.00"),
            open_posten=[_post("-100.00"), _post("55.00", soort="Verkoopfactuur")],
            vaste_regels=[],
        )
        assert v.kleur == "groen" and v.batch is not None and v.batch.aantal == 1

    def test_sleutel_uit_document(self) -> None:
        assert doelpost.batch_sleutel_uit({"PaymentTermList": [{"PaymentBatchInformation": f" {SLEUTEL} "}]}) == SLEUTEL
        assert doelpost.batch_sleutel_uit({"PaymentTermList": [{"PaymentBatchInformation": None}, {}]}) is None
        assert doelpost.batch_sleutel_uit({}) is None and doelpost.batch_sleutel_uit(None) is None


class TestSyncExpand:
    def test_items_expand_draagt_paymenttermlist_met_terugval_op_400(self) -> None:
        class Client:
            def __init__(self, weiger: bool) -> None:
                self.weiger = weiger
                self.params: list[dict] = []

            def list_payment_items(self, *, params=None):  # noqa: ANN001, ANN202
                self.params.append(params)
                if self.weiger and "PaymentTermList" in params["$expand"]:
                    raise RlzApiError(400, "GET", "PaymentItems", "Property 'PaymentTermList' not found (simulatie)")
                return [{"id": "x"}]

        ok = Client(weiger=False)
        assert sync._lees_payment_items(ok) == [{"id": "x"}]
        assert ok.params == [{"$expand": sync.ITEMS_EXPAND}]
        weigert = Client(weiger=True)
        assert sync._lees_payment_items(weigert) == [{"id": "x"}]
        assert [p["$expand"] for p in weigert.params] == [sync.ITEMS_EXPAND, sync.ITEMS_EXPAND_TERUGVAL]


def _batch_in_db(
    admin_engine: Engine,
    administratie_id: uuid.UUID,
    *,
    bedragen: list[str],
    open_bedrag: str,
    al_gekoppeld: int | None = None,
) -> tuple[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]]:
    """Batch-mutatie (brondata mét PaymentBatchId) + N open posten met dezelfde sleutel + één post zonder sleutel.
    `al_gekoppeld` = index van een post waarvan het document al in `rlz_koppelingen` van de mutatie hangt."""
    docs = [uuid.uuid4() for _ in bedragen]
    koppelingen = None
    if al_gekoppeld is not None:
        koppelingen = [
            {
                "document_id": str(docs[al_gekoppeld]),
                "boekstuknummer": "RLZ-04-00000497",
                "referentie": f"9295348{al_gekoppeld}",
                "bedrag": bedragen[al_gekoppeld].lstrip("-"),
                "document_type": 1,
            }
        ]
    mutatie_id = maak_bank_mutatie(
        admin_engine,
        administratie_id=administratie_id,
        bedrag="-560925.88",
        open_bedrag=open_bedrag,
        tegenpartij_naam="TOTAAL 14 VZ",
        omschrijving="TOTAAL 14 VZ betaalkenmerk: PREF",
        brondata={
            "PaymentBatchId": SLEUTEL,
            "ReturnReason": None,
            "Batch": {"BatchId": SLEUTEL, "FileName": f"{SLEUTEL}.xml"},
        },
        rlz_koppelingen=koppelingen,
    )
    posten = []
    for n, (bedrag, doc) in enumerate(zip(bedragen, docs, strict=True)):
        item = maak_payment_item(
            admin_engine,
            administratie_id=administratie_id,
            bedrag=bedrag,
            referentie=str(700 + n),
            klantreferentie=f"9295348{n}",
            documentsoort="Inkoopfactuur",
            entity_naam=f"Leverancier {n}",
            rlz_document_id=doc,
            batch_sleutel=SLEUTEL,
        )
        posten.append((item, doc))
    # Een open post van een andere leverancier zonder sleutel — mag nooit in de batch.
    maak_payment_item(
        admin_engine,
        administratie_id=administratie_id,
        bedrag="-40000.00",
        referentie="999",
        documentsoort="Inkoopfactuur",
    )
    return mutatie_id, posten


class TestServiceEnRoute:
    def test_servicelaag_leest_sleutels_uit_de_caches(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        mutatie_id, posten = _batch_in_db(
            admin_engine, administratie_id, bedragen=["-40000.00", "-723.85"], open_bedrag="-40723.85"
        )
        rij = next(
            m
            for m in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if m.mutatie.id == mutatie_id
        )
        assert rij.mutatie.payment_batch_id == SLEUTEL
        assert rij.voorstel.soort == VoorstelSoort.BATCH and rij.voorstel.kleur == "groen"
        assert {p.id for p in rij.voorstel.batch.posten} == {item for item, _ in posten}

    def test_letter_batch_af_koppelt_n_keer_en_slaat_al_gekoppelde_over(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        mutatie_id, posten = _batch_in_db(
            admin_engine, administratie_id, bedragen=["-40000.00", "-723.85"], open_bedrag="-40723.85"
        )
        fake = FakeBankClient(
            transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -40723.85, "PaymentReferenceList": []}},
            items=[{"id": str(item)} for item, _ in posten],
            item_documenten={str(item): str(doc) for item, doc in posten},
        )
        uit = afletteren.letter_batch_af(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=fake
        )
        assert uit.sleutel == SLEUTEL and (uit.gekoppeld, uit.overgeslagen, uit.mislukt) == (2, 0, 0)
        assert [r.uitkomst for r in uit.rijen] == ["afgeletterd_via_api", "afgeletterd_via_api"]
        assert len(fake.links) == 2 and all(link["payment_correction_method"] == 1 for link in fake.links)
        assert sorted(abs(link["linked_amount"]) for link in fake.links) == [723.85, 40000.0]
        assert all(link["linked_amount"] < 0 for link in fake.links)  # teken van de mutatie

    def test_letter_batch_af_stopt_na_api_fout_en_meldt_de_rest_als_niet_uitgevoerd(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        mutatie_id, posten = _batch_in_db(
            admin_engine, administratie_id, bedragen=["-40000.00", "-723.85"], open_bedrag="-40723.85"
        )
        fake = FakeBankClient(
            transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -40723.85, "PaymentReferenceList": []}},
            items=[{"id": str(item)} for item, _ in posten],
            item_documenten={str(item): str(doc) for item, doc in posten},
            faal_op="link",
        )
        uit = afletteren.letter_batch_af(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=fake
        )
        assert [r.uitkomst for r in uit.rijen] == ["wacht_op_mens_in_rlz", "niet_uitgevoerd"]
        assert uit.mislukt == 2 and uit.gekoppeld == 0
        assert uit.rijen[0].fout and uit.rijen[1].fout == "niet uitgevoerd ná een eerdere API-fout"

    def test_route_batch_en_dto(
        self,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.bank import router as bank_router

        mutatie_id, posten = _batch_in_db(
            admin_engine, administratie_id, bedragen=["-40000.00", "-700.00"], open_bedrag="-40723.85"
        )
        fake = FakeBankClient(
            transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -40723.85, "PaymentReferenceList": []}},
            items=[{"id": str(item)} for item, _ in posten],
            item_documenten={str(item): str(doc) for item, doc in posten},
        )
        monkeypatch.setattr(bank_router, "_rlz_client_voor", lambda aid: fake)
        monkeypatch.setattr(afletteren, "_open_eigen_client", lambda aid: fake)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        # DTO: oranje batch mét verschil (som 40.700 vs open 40.723,85) en de posten voor de kaart.
        rekening_id = uuid.uuid4()
        admin_engine  # noqa: B018 — de mutatie hangt aan geen rekening; lees via de service-DTO-bouwer
        rijen = voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
        dto = bank_router._voorstel_response(next(r for r in rijen if r.mutatie.id == mutatie_id))
        assert dto.soort == "batch" and dto.kleur == "oranje" and dto.batch is not None
        assert (dto.batch.aantal, str(dto.batch.som), str(dto.batch.verschil), dto.batch.sluit) == (
            2,
            "40700.00",
            "23.85",
            False,
        )
        assert {p.klantreferentie for p in dto.batch.posten} == {"92953480", "92953481"}
        del rekening_id
        r = client.post(
            f"/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/afletteren-batch", headers=headers
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert (d["sleutel"], d["gekoppeld"], d["overgeslagen"], d["mislukt"]) == (SLEUTEL, 2, 0, 0)
        assert len(d["rijen"]) == 2

    def test_al_gekoppelde_post_wordt_overgeslagen_idempotent(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        # De deels-afgeletterde casus: post 0 hangt al aan de mutatie (leesspoor), alleen post 1 is nog te koppelen.
        mutatie_id, posten = _batch_in_db(
            admin_engine, administratie_id, bedragen=["-40000.00", "-723.85"], open_bedrag="-723.85", al_gekoppeld=0
        )
        fake = FakeBankClient(
            transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -723.85, "PaymentReferenceList": []}},
            items=[{"id": str(item)} for item, _ in posten],
            item_documenten={str(item): str(doc) for item, doc in posten},
        )
        uit = afletteren.letter_batch_af(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=fake
        )
        assert [r.uitkomst for r in uit.rijen] == ["overgeslagen", "afgeletterd_via_api"]
        assert (uit.gekoppeld, uit.overgeslagen, uit.mislukt) == (1, 1, 0)
        assert len(fake.links) == 1 and fake.links[0]["linked_amount"] == -723.85
