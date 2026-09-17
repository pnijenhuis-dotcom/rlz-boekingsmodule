"""Blok C 16-09 + HERDEFINITIE 17-09 — dubbele betaling = betaling ZONDER tegenoverstaande factuur (casus Kempen
Facilities → Hello Kitchen Duiven: € 12.600,00 op 18-08 én 14-09 aan dezelfde tegenrekening, één echte factuur; de
1.214 valse positieven van 17-09 waren periodieke betalingen mét factuur). Pure motor + DB-variant via `reconcilieer_bank`
zonder RLZ-client (factuurbronnen: leverancier_iban/boekvoorstel, bank_relatie_iban/payment_item_cache, rlz_koppelingen)."""

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
        # Pure motor zonder factuurbron: alleen de RLZ-koppelingen tellen (0 facturen) → de zin draagt de telling.
        assert motor.tekst(d) == (
            "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09), terwijl er geen factuur van dat "
            "bedrag tegenover staat."
        )
        assert d.bank_toets == "bevestigd" and d.facturen == () and d.factuur_bronnen == ("rlz_koppeling",)

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


def _koppel_iban_aan_entity(admin_engine: Engine, administratie_id: uuid.UUID, iban: str, entity_guid: uuid.UUID) -> None:
    from sqlalchemy import text

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_relatie_iban (id, administratie_id, iban, entity_guid, entity_naam, aantal_bevestigingen) "
                "VALUES (:id, :aid, :iban, :entity, 'Hello Kitchen Duiven', 1)"
            ),
            {"id": uuid.uuid4(), "aid": administratie_id, "iban": iban, "entity": entity_guid},
        )


class TestHerdefinitie17_09:
    """De kern van 17-09: periodiek = nooit; betalingen ≤ facturen = nooit; betalingen > facturen = bevinding."""

    def _toets(self, facturen: int):
        def f(iban: str, bedrag: Decimal, datums: tuple) -> motor.FactuurToets:
            return motor.FactuurToets(
                facturen=tuple(
                    motor.Factuur(bron="module", referentie=f"F-{i}", datum=datums[0], document_id=str(uuid.uuid4()))
                    for i in range(facturen)
                ),
                bronnen=("module",),
            )

        return f

    def test_google_cloud_twee_betalingen_twee_facturen_geen_bevinding(self) -> None:
        ms = [M(date(2026, 8, 1), Decimal("-40.59")), M(date(2026, 9, 1), Decimal("-40.59"))]
        analyse = motor.analyseer_dubbele_betalingen(ms, factuurtoets=self._toets(2))
        assert analyse.signalen == () and analyse.facturen_dekken == 1

    def test_hello_kitchen_twee_betalingen_een_factuur_bevinding_met_factuur_erbij(self) -> None:
        ms = [M(date(2026, 8, 18), Decimal("-12600.00")), M(date(2026, 9, 14), Decimal("-12600.00"))]
        uit = motor.vind_dubbele_betalingen(ms, factuurtoets=self._toets(1))
        assert len(uit) == 1
        d = uit[0]
        assert len(d.facturen) == 1 and d.facturen[0].referentie == "F-0" and "module" in d.factuur_bronnen
        assert motor.tekst(d) == (
            "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 14-09), terwijl er één factuur van dat "
            "bedrag tegenover staat."
        )

    def test_periodieke_maandreeks_met_dubbel_bedrag_nooit_een_bevinding(self) -> None:
        # Insify/Greenchoice-patroon: elke maand hetzelfde bedrag — 16-09 zag "twee ≤ 30 d" en mailde 1.214 keer.
        ms = [M(date(2025, 10 + i // 3 if False else 1, 1), Decimal("-245.30")) for i in range(0)]
        ms = [M(date(2026, m, 5), Decimal("-245.30")) for m in range(1, 10)]
        analyse = motor.analyseer_dubbele_betalingen(ms, factuurtoets=self._toets(0))
        assert analyse.signalen == () and analyse.periodiek_uitgesloten == 1
        ok, naam = motor.is_periodieke_reeks([m.boekdatum for m in ms])
        assert ok and naam == "maand"

    def test_weekpatroon_en_kwartaalpatroon_zijn_periodiek(self) -> None:
        week = [date(2026, 6, 1) + __import__("datetime").timedelta(days=7 * i) for i in range(5)]
        assert motor.is_periodieke_reeks(week) == (True, "week")
        kwartaal = [date(2026, 1, 15), date(2026, 4, 14), date(2026, 7, 16)]
        assert motor.is_periodieke_reeks(kwartaal) == (True, "kwartaal")
        # Twee betalingen zijn nooit een patroon; een zelfde-dag-dubbel breekt het patroon.
        assert motor.is_periodieke_reeks([date(2026, 6, 1), date(2026, 7, 1)]) == (False, None)
        assert motor.is_periodieke_reeks([date(2026, 6, 1), date(2026, 6, 1), date(2026, 7, 1)]) == (False, None)

    def test_bekende_periodieke_tegenpartij_incasso_geen_bevinding(self) -> None:
        ms = [M(date(2026, 8, 18), Decimal("-99.00")), M(date(2026, 9, 3), Decimal("-99.00"))]
        analyse = motor.analyseer_dubbele_betalingen(ms, periodieke_ibans=[IBAN], factuurtoets=self._toets(0))
        assert analyse.signalen == () and analyse.periodiek_uitgesloten == 1

    def test_crediteur_onbekend_in_de_caches_geen_uitspraak(self) -> None:
        ms = [M(date(2026, 8, 18), Decimal("-99.00")), M(date(2026, 9, 3), Decimal("-99.00"))]
        analyse = motor.analyseer_dubbele_betalingen(ms, factuurtoets=lambda *_: None)
        assert analyse.signalen == () and analyse.zonder_factuurbron == 1

    def test_aflettering_een_betaling_zonder_document_is_sterk_signaal(self) -> None:
        a = M(date(2026, 8, 18), Decimal("-12600.00"), rlz_koppelingen=[_k("24594001722")])
        b = M(date(2026, 9, 14), Decimal("-12600.00"), rlz_koppelingen=[])
        uit = motor.vind_dubbele_betalingen([a, b], factuurtoets=self._toets(0))
        assert len(uit) == 1 and uit[0].sterk
        # De gekoppelde factuur telt als de ene factuur die er wél tegenover staat (bron rlz_koppeling).
        assert len(uit[0].facturen) == 1 and uit[0].facturen[0].bron == "rlz_koppeling"
        assert motor.tekst(uit[0]).endswith("— een van de betalingen hangt in Reeleezee aan geen factuur.")

    def test_dedupliceer_dezelfde_factuur_uit_drie_bronnen(self) -> None:
        rlz_id = str(uuid.uuid4())
        fs = [
            motor.Factuur(bron="module", referentie="2026-0042", datum=None, document_id="d1"),
            motor.Factuur(bron="rlz_open_post", referentie="2026-0042", datum=None, rlz_document_id=rlz_id),
            motor.Factuur(bron="rlz_koppeling", referentie="Factuur 2026-0042", datum=None, rlz_document_id=rlz_id),
            motor.Factuur(bron="module", referentie="2026-0057", datum=None, document_id="d2"),
        ]
        assert len(motor.dedupliceer_facturen(fs)) == 2


class TestReconciliatieZonderRlz:
    def test_twee_rijen_in_de_db_een_factuur_in_de_open_postencache_geeft_een_afwijking(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from tests.bank.conftest import maak_payment_item

        entity = uuid.uuid4()
        _koppel_iban_aan_entity(admin_engine, administratie_id, IBAN_KAAL, entity)
        # Eén inkoopfactuur van € 12.600 van deze relatie (al betaald = verdwenen mag; hier nog in de cache).
        maak_payment_item(
            admin_engine, administratie_id=administratie_id, bedrag="12600.00", referentie="24594001722",
            entity_guid=entity, entity_naam="Hello Kitchen Duiven", documentsoort="Inkoopfactuur", boekdatum="2026-09-09",
            factuurdatum="2026-08-10",
        )
        oud = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-12600.00", tegenrekening_iban=IBAN,
            tegenpartij_naam="Hello Kitchen Duiven", boekdatum="2026-08-18",
        )
        jong = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-12600.00", tegenrekening_iban=IBAN_KAAL,
            tegenpartij_naam="Hello Kitchen Duiven", boekdatum="2026-09-03",
        )
        # Een periodieke huurreeks ernaast: geen signaal (ook zonder factuurbron).
        for dag in ("2026-06-01", "2026-07-01", "2026-08-01"):
            maak_bank_mutatie(
                admin_engine, administratie_id=administratie_id, bedrag="-1500.00",
                tegenrekening_iban="NL02RABO0123456789", tegenpartij_naam="Verhuurder", boekdatum=dag,
            )
        # Een tweede leverancier mét twee betalingen én twee facturen (Google Cloud-patroon): geen signaal.
        entity2 = uuid.uuid4()
        _koppel_iban_aan_entity(admin_engine, administratie_id, "NL03INGB0000000003", entity2)
        for ref, dag in (("GC-1", "2026-08-01"), ("GC-2", "2026-09-01")):
            maak_payment_item(
                admin_engine, administratie_id=administratie_id, bedrag="40.59", referentie=ref, entity_guid=entity2,
                documentsoort="Inkoopfactuur", boekdatum=dag,
            )
            maak_bank_mutatie(
                admin_engine, administratie_id=administratie_id, bedrag="-40.59", tegenrekening_iban="NL03INGB0000000003",
                tegenpartij_naam="Google Cloud", boekdatum=dag,
            )

        # Geen boekingen/afletteringen én geen client: de controle draait op de eigen DB.
        rapport = reconcilieer_bank(administratie_id=administratie_id, client=None)
        assert rapport.dubbele_betalingen_gecontroleerd == 3
        assert len(rapport.afwijkingen) == 1
        a = rapport.afwijkingen[0]
        assert a.soort == SOORT_DUBBELE_BETALING
        assert a.record_id == jong and a.payment_transaction_id == jong
        assert a.detail.startswith(
            "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09), terwijl er één factuur"
        )
        assert a.detail.endswith(" [mutaties: 18-08, 03-09]")
        assert a.extra is not None
        assert a.extra["dubbele_betaling_datums"] == ["2026-08-18", "2026-09-03"]
        assert a.extra["dubbele_betaling_aantal"] == 2 and a.extra["dubbele_betaling_bedrag"] == "12600.00"
        assert a.extra["dubbele_betaling_facturen_aantal"] == 1 and a.extra["bank_toets"] == "bevestigd"
        assert a.extra["dubbele_betaling_facturen"][0]["referentie"] == "24594001722"
        assert a.extra["dubbele_betaling_mutaties"] == [str(oud), str(jong)]
        assert "rlz_open_post" in a.extra["dubbele_betaling_factuur_bronnen"]
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
        assert lb.doe.startswith("Factuur ontbreekt") and "accepteer met reden" in lb.doe
        assert not teksten.bevat_technische_sleutel(lb.wat)

    def test_twee_rijen_zonder_enige_factuurbron_geen_uitspraak(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Crediteur onbekend in leverancier_iban én bank_relatie_iban → geen telling mogelijk → geen bevinding (geteld).
        for dag in ("2026-08-18", "2026-09-03"):
            maak_bank_mutatie(
                admin_engine, administratie_id=administratie_id, bedrag="-77.00", tegenrekening_iban=IBAN,
                tegenpartij_naam="Onbekend", boekdatum=dag,
            )
        analyse = motor.analyseer_voor_administratie(administratie_id)
        assert analyse.signalen == () and analyse.zonder_factuurbron == 1 and analyse.sleutels_getoetst == 1
