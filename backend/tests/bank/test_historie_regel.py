"""Historie-regel (blok B bundel 10-09) — pure geldlogica, dus volledig getest: kern-normalisatie, 100 % / k-van-n /
gelijkstand, dekking te kort, open posten gaan vóór, IBAN ontbreekt."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.bank import historie_regel as hr
from app.bank.matchmotor import IbanRelatie, MutatieGegevens, OpenPost

VANDAAG = date(2026, 9, 10)
IBAN = "NL91ABNA0417164300"
GB_HUUR, GB_LEASE = uuid.uuid4(), uuid.uuid4()
BTW_HOOG = uuid.uuid4()


def _mutatie(
    *,
    omschrijving: str = "Huur kantoor Deventer periode 09-2026 kenmerk 20260901",
    iban: str | None = IBAN,
    naam: str = "Vastgoed Beheer Oost B.V.",
    bedrag: str = "-1250.00",
) -> MutatieGegevens:
    return MutatieGegevens(
        id=uuid.uuid4(),
        bedrag=Decimal(bedrag),
        open_bedrag=Decimal(bedrag),
        tegenpartij_naam=naam,
        omschrijving=omschrijving,
        tegenrekening_iban=iban,
        rlz_voorstel_item_id=None,
    )


def _boeking(
    *,
    dagen_terug: int,
    omschrijving: str = "Huur kantoor Deventer periode 08-2026 kenmerk 20260801",
    ledger: uuid.UUID = GB_HUUR,
    taxrate: uuid.UUID | None = BTW_HOOG,
    iban: str | None = IBAN,
    bron: str = "rlz",
) -> hr.HistorieBoeking:
    return hr.HistorieBoeking(
        payment_transaction_id=uuid.uuid4(),
        datum=VANDAAG - timedelta(days=dagen_terug),
        tegenrekening_iban=iban,
        omschrijving=omschrijving,
        tegenpartij_naam="Vastgoed Beheer Oost B.V.",
        ledger_id=ledger,
        taxrate_id=taxrate,
        bron=bron,
    )


def _historie(n: int = 3) -> list[hr.HistorieBoeking]:
    return [_boeking(dagen_terug=30 * (i + 1) + 200) for i in range(n)]


def _bepaal(mutatie, historie, *, open_posten=(), iban_relaties=()):
    return hr.bepaal_historie_voorstel(
        mutatie, historie, open_posten=list(open_posten), iban_relaties=list(iban_relaties), vandaag=VANDAAG
    )


class TestOmschrijvingskern:
    @pytest.mark.parametrize(
        "omschrijving, kern",
        [
            ("Huur kantoor Deventer periode 09-2026 kenmerk 20260901", "huur kantoor deventer"),
            ("HUUR KANTOOR DEVENTER periode 10-2026 kenmerk 20261001", "huur kantoor deventer"),
            (
                "SEPA Incasso Machtiging 12345 Naam: KPN B.V. Omschrijving: Factuur F0024082026 abonnement",
                "kpn abonnement",
            ),
            ("Betaling 1.250,00 EUR aan NL91ABNA0417164300 op 01-09-2026 huur", "huur"),
            ("2026-09-01 12500,00", ""),
            ("", ""),
            (None, ""),
            ("Transactie 2026W36 lease auto 26-ABC-1", "lease auto abc"),
        ],
    )
    def test_kern_verwijdert_cijfers_datums_bedragen_ibans_en_bankwoorden(self, omschrijving, kern) -> None:
        assert hr.omschrijvingskern(omschrijving) == kern

    def test_sleutel_vereist_iban_en_kern(self) -> None:
        assert hr.historie_sleutel(None, "huur kantoor") is None
        assert hr.historie_sleutel(IBAN, "20260901") is None
        assert hr.historie_sleutel("nl91 abna 0417 1643 00", "Huur kantoor") == hr.HistorieSleutel(IBAN, "huur kantoor")


class TestVoorstel:
    def test_100_procent_is_groen_en_automatisch_kandidaat(self) -> None:
        uit = _bepaal(_mutatie(), _historie(3))
        assert uit.voorstel is not None
        assert uit.voorstel.kleur == "groen" and uit.voorstel.automatisch_kandidaat
        assert (uit.voorstel.k, uit.voorstel.n) == (3, 3)
        assert (uit.voorstel.ledger_id, uit.voorstel.taxrate_id) == (GB_HUUR, BTW_HOOG)
        assert uit.voorstel.label("4400 Huur") == "historie: 3 van 3 op 4400 Huur"

    def test_bedrag_is_vrij(self) -> None:
        uit = _bepaal(_mutatie(bedrag="-1375.50"), _historie(4))
        assert uit.voorstel is not None and uit.voorstel.kleur == "groen"

    def test_k_van_n_is_oranje_en_geen_kandidaat(self) -> None:
        historie = _historie(4) + [_boeking(dagen_terug=210, ledger=GB_LEASE)]
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is not None
        assert uit.voorstel.kleur == "oranje" and not uit.voorstel.automatisch_kandidaat
        assert (uit.voorstel.k, uit.voorstel.n) == (4, 5)
        assert uit.voorstel.ledger_id == GB_HUUR

    def test_andere_btw_behandeling_telt_als_andere_combinatie(self) -> None:
        historie = _historie(3) + [_boeking(dagen_terug=210, taxrate=None)]
        uit = _bepaal(_mutatie(), historie)
        assert (
            uit.voorstel is not None and uit.voorstel.kleur == "oranje" and (uit.voorstel.k, uit.voorstel.n) == (3, 4)
        )

    def test_gelijkstand_is_oranje_nooit_gokken(self) -> None:
        historie = _historie(2) + [
            _boeking(dagen_terug=210, ledger=GB_LEASE),
            _boeking(dagen_terug=240, ledger=GB_LEASE),
        ]
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is not None and uit.voorstel.kleur == "oranje"
        assert (uit.voorstel.k, uit.voorstel.n) == (2, 4) and "gelijkstand" in uit.reden

    def test_minder_dan_drie_op_de_sleutel_geen_voorstel(self) -> None:
        historie = _historie(2) + [_boeking(dagen_terug=300, omschrijving="Lease auto september", ledger=GB_LEASE)]
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is None and "2 eerdere boeking" in uit.reden

    def test_dekking_te_kort_geen_voorstel(self) -> None:
        historie = [_boeking(dagen_terug=30 * (i + 1)) for i in range(4)]  # oudste 120 dagen
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is None and "historie te kort" in uit.reden

    def test_dekking_op_de_grens_183_dagen_telt(self) -> None:
        historie = [_boeking(dagen_terug=183), _boeking(dagen_terug=90), _boeking(dagen_terug=30)]
        assert _bepaal(_mutatie(), historie).voorstel is not None

    def test_open_post_voor_tegenpartij_gaat_voor(self) -> None:
        post = OpenPost(
            id=uuid.uuid4(),
            bedrag=Decimal("-99.00"),
            referentie="F-1",
            referentie2=None,
            rlz_document_id=uuid.uuid4(),
            tegenpartij_naam="Vastgoed Beheer Oost B.V.",
            documentsoort="Inkoopfactuur",
        )
        uit = _bepaal(_mutatie(), _historie(3), open_posten=[post])
        assert uit.voorstel is None and "open-post-match gaat vóór" in uit.reden

    def test_geleerde_iban_relatie_gaat_voor(self) -> None:
        uit = _bepaal(
            _mutatie(),
            _historie(3),
            iban_relaties=[IbanRelatie(iban="NL91 ABNA 0417 1643 00", entity_guid=uuid.uuid4())],
        )
        assert uit.voorstel is None and "open-post-match gaat vóór" in uit.reden

    def test_open_post_van_andere_partij_stoort_niet(self) -> None:
        post = OpenPost(
            id=uuid.uuid4(),
            bedrag=Decimal("-99.00"),
            referentie="F-1",
            referentie2=None,
            rlz_document_id=uuid.uuid4(),
            tegenpartij_naam="TransIP B.V.",
            documentsoort="Inkoopfactuur",
        )
        assert _bepaal(_mutatie(), _historie(3), open_posten=[post]).voorstel is not None

    def test_iban_ontbreekt_geen_sleutel(self) -> None:
        uit = _bepaal(_mutatie(iban=None), _historie(3))
        assert uit.voorstel is None and "geen sleutel" in uit.reden

    def test_andere_iban_zelfde_kern_telt_niet_mee(self) -> None:
        historie = _historie(3) + [_boeking(dagen_terug=210, iban="NL20INGB0001234567", ledger=GB_LEASE)]
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is not None and uit.voorstel.kleur == "groen" and uit.voorstel.n == 3

    def test_module_en_rlz_bron_tellen_samen(self) -> None:
        historie = _historie(2) + [_boeking(dagen_terug=210, bron="module")]
        uit = _bepaal(_mutatie(), historie)
        assert uit.voorstel is not None and uit.voorstel.n == 3


def test_samenvatting_is_deterministisch_zonder_rijen() -> None:
    historie = _historie(3) + [_boeking(dagen_terug=210, ledger=GB_LEASE)]
    sleutel = hr.historie_sleutel(IBAN, "Huur kantoor Deventer")
    labels = {GB_HUUR: "4400 Huur", GB_LEASE: "4500 Lease"}
    tekst = hr.historie_samenvatting(historie, sleutel, rekening_label=lambda gb, btw: labels[gb])
    assert tekst == "4 eerdere mutaties, 3× 4400 Huur (75 %), 1× 4500 Lease (25 %)"
    assert hr.historie_samenvatting(historie, None, rekening_label=lambda gb, btw: "") == "geen historie-sleutel"
