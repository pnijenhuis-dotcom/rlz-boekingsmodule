"""Blok C 16-09 — dubbele betaling signaleren (casus Kempen Facilities → Hello Kitchen Duiven: € 12.600,00 op 18-08
én 14-09 aan dezelfde tegenrekening, één echte factuur). Pure motor + DB-variant via `reconcilieer_bank` zonder
RLZ-client."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from app.bank import dubbele_betaling as motor
from app.bank.reconciliatie import SOORT_DUBBELE_BETALING, reconcilieer_bank
from app.reconciliatie import teksten
from tests.bank.conftest import maak_bank_mutatie

IBAN = "NL91 ABNA 0417 1646 32"  # genormaliseerd: NL91ABNA0417164632
IBAN_KAAL = "NL91ABNA0417164632"


@dataclass
class M:
    boekdatum: date
    bedrag: Decimal
    tegenrekening_iban: str | None = IBAN
    tegenpartij_naam: str | None = "Hello Kitchen Duiven"
    omschrijving: str | None = None
    rlz_koppelingen: list | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _k(referentie: str | None, document_type: int = 2) -> dict:
    return {"document_id": str(uuid.uuid4()), "referentie": referentie, "document_type": document_type}


class TestPureMotor:
    def test_twee_gelijke_uitgaande_betalingen_binnen_venster_is_een_signaal_met_leesbare_tekst(self) -> None:
        a = M(date(2026, 8, 18), Decimal("-12600.00"))
        b = M(date(2026, 9, 3), Decimal("-12600.00"), tegenrekening_iban=IBAN_KAAL)
        uit = motor.vind_dubbele_betalingen([b, a])
        assert len(uit) == 1
        d = uit[0]
        assert d.mutatie_ids == (a.id, b.id)  # chronologisch
        assert d.datums == (date(2026, 8, 18), date(2026, 9, 3))
        assert d.bedrag == Decimal("12600.00") and d.tegenrekening_iban == IBAN_KAAL
        assert d.jongste_mutatie_id == b.id
        assert motor.tekst(d) == (
            "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09) voor wat één factuur lijkt — "
            "controleer of terugvordering nodig is."
        )

    def test_casus_hello_kitchen_twee_bedragen_twee_signalen(self) -> None:
        ms = [
            M(date(2026, 8, 18), Decimal("-12600.00")),
            M(date(2026, 9, 14), Decimal("-12600.00")),
            M(date(2026, 8, 18), Decimal("-16250.00")),
            M(date(2026, 9, 14), Decimal("-16250.00")),
            M(date(2026, 8, 18), Decimal("-999.00")),  # enkel → niets
        ]
        analyse = motor.analyseer_dubbele_betalingen(ms)
        assert [d.bedrag for d in analyse.signalen] == [Decimal("12600.00"), Decimal("16250.00")]
        assert analyse.sleutels_getoetst == 2

    def test_drie_maandelijkse_gelijke_betalingen_periodiek_geen_signaal(self) -> None:
        ms = [M(date(2026, m, 1), Decimal("-1500.00")) for m in (6, 7, 8)]
        assert motor.vind_dubbele_betalingen(ms) == []
        # …maar de sleutel is wél getoetst (teller).
        assert motor.analyseer_dubbele_betalingen(ms).sleutels_getoetst == 1

    def test_koppelingen_naar_twee_verschillende_referenties_geen_signaal(self) -> None:
        a = M(date(2026, 8, 18), Decimal("-12600.00"), rlz_koppelingen=[_k("2026-0042")])
        b = M(date(2026, 9, 3), Decimal("-12600.00"), rlz_koppelingen=[_k("2026-0057")])
        assert motor.vind_dubbele_betalingen([a, b]) == []

    def test_koppelingen_naar_dezelfde_referentie_of_alleen_systeemhulzen_blijven_een_signaal(self) -> None:
        a = M(date(2026, 8, 18), Decimal("-12600.00"), rlz_koppelingen=[_k("Factuur 2026-0042")])
        b = M(date(2026, 9, 3), Decimal("-12600.00"), rlz_koppelingen=[_k("2026-42")])
        assert len(motor.vind_dubbele_betalingen([a, b])) == 1
        c = M(date(2026, 8, 18), Decimal("-12600.00"), rlz_koppelingen=[_k(None, document_type=19)])
        d = M(date(2026, 9, 3), Decimal("-12600.00"), rlz_koppelingen=[_k(None, document_type=19)])
        assert len(motor.vind_dubbele_betalingen([c, d])) == 1

    def test_buiten_venster_geen_signaal(self) -> None:
        a = M(date(2026, 5, 1), Decimal("-12600.00"))
        b = M(date(2026, 9, 3), Decimal("-12600.00"))
        assert motor.vind_dubbele_betalingen([a, b]) == []
        assert len(motor.vind_dubbele_betalingen([a, b], venster_dagen=200)) == 1

    def test_inkomend_en_ander_bedrag_of_andere_iban_geen_signaal(self) -> None:
        ms = [
            M(date(2026, 8, 18), Decimal("12600.00")),
            M(date(2026, 9, 3), Decimal("12600.00")),
            M(date(2026, 8, 18), Decimal("-100.00")),
            M(date(2026, 9, 3), Decimal("-100.01")),
            M(date(2026, 8, 18), Decimal("-200.00")),
            M(date(2026, 9, 3), Decimal("-200.00"), tegenrekening_iban="NL02RABO0123456789"),
            M(date(2026, 8, 18), Decimal("-300.00"), tegenrekening_iban=None),
            M(date(2026, 9, 3), Decimal("-300.00"), tegenrekening_iban=None),
        ]
        assert motor.vind_dubbele_betalingen(ms) == []

    def test_facturen_per_sleutel_dekt_de_betalingen_geen_signaal(self) -> None:
        a = M(date(2026, 8, 18), Decimal("-12600.00"))
        b = M(date(2026, 9, 3), Decimal("-12600.00"))
        sleutel = (IBAN_KAAL, Decimal("12600.00"))
        assert motor.vind_dubbele_betalingen([a, b], facturen_per_sleutel={sleutel: 2}) == []
        assert len(motor.vind_dubbele_betalingen([a, b], facturen_per_sleutel={sleutel: 1})) == 1

    def test_drie_keer_zonder_patroon_en_naamloze_tegenpartij(self) -> None:
        ms = [M(date(2026, 8, 18), Decimal("-50.00"), tegenpartij_naam=None) for _ in range(3)]
        uit = motor.vind_dubbele_betalingen(ms)
        assert len(uit) == 1 and uit[0].aantal == 3
        assert motor.tekst(uit[0]).startswith(
            "Aan tegenrekening …4632 is € 50,00 drie keer betaald (18-08, 18-08 en 18-08)"
        )

    def test_euro_nl(self) -> None:
        assert motor.euro_nl(Decimal("12600")) == "€ 12.600,00"
        assert motor.euro_nl(Decimal("-1234567.5")) == "€ 1.234.567,50"
        assert motor.euro_nl(Decimal("0.5")) == "€ 0,50"


class TestReconciliatieZonderRlz:
    def test_twee_rijen_in_de_db_geven_een_niet_blokkerende_afwijking_zonder_client(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        oud = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-12600.00", tegenrekening_iban=IBAN,
            tegenpartij_naam="Hello Kitchen Duiven", boekdatum="2026-08-18",
        )
        jong = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-12600.00", tegenrekening_iban=IBAN_KAAL,
            tegenpartij_naam="Hello Kitchen Duiven", boekdatum="2026-09-03",
        )
        # Een periodieke huurreeks ernaast: geen signaal.
        for dag in ("2026-06-01", "2026-07-01", "2026-08-01"):
            maak_bank_mutatie(
                admin_engine, administratie_id=administratie_id, bedrag="-1500.00",
                tegenrekening_iban="NL02RABO0123456789", tegenpartij_naam="Verhuurder", boekdatum=dag,
            )

        # Geen boekingen/afletteringen én geen client: de controle draait op de eigen DB.
        rapport = reconcilieer_bank(administratie_id=administratie_id, client=None)
        assert rapport.dubbele_betalingen_gecontroleerd == 2
        assert len(rapport.afwijkingen) == 1
        a = rapport.afwijkingen[0]
        assert a.soort == SOORT_DUBBELE_BETALING
        assert a.record_id == jong and a.payment_transaction_id == jong
        assert a.detail.startswith("Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09)")
        assert a.detail.endswith(" [mutaties: 18-08, 03-09]")
        assert a.extra == {
            "dubbele_betaling_datums": ["2026-08-18", "2026-09-03"],
            "dubbele_betaling_aantal": 2,
            "dubbele_betaling_bedrag": "12600.00",
        }
        assert oud in motor.vind_dubbele_betalingen_voor_administratie(administratie_id)[0].mutatie_ids

        # Verrijking + leesbare tekst: dezelfde zin, zonder id's.
        from app.reconciliatie import verrijking

        detail = {
            "bron": "bank", "afwijking_soort": a.soort, "detail": a.detail, **a.extra,
            **verrijking.bank(
                administratie_id=administratie_id,
                record_id=a.record_id,
                payment_transaction_id=a.payment_transaction_id,
            ),
        }
        assert detail["tegenpartij_naam"] == "Hello Kitchen Duiven" and detail["mutatie_datum"] == "2026-09-03"
        assert detail["mutatie_bedrag"] == "-12600.00" and detail["controle"] == "mutatie"
        velden = {"blok": "bank", "soort": "afwijking", "tekst": a.detail, "detail": detail, "administratie_naam": None}
        bevinding = type("B", (), velden)()
        lb = teksten.leesbaar(bevinding)
        assert lb.titel.startswith("Mogelijk dubbel betaald")
        assert lb.wat == a.detail.split(" [mutaties")[0]
        assert "terugvordering" in lb.doe and "accepteer met reden" in lb.doe
        assert not teksten.bevat_technische_sleutel(lb.wat)
