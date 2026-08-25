"""Al-betaald-signaal (besluit Peter 25-08, deel 2 punt 1): onafgeletterde mutaties uit de lokale
bank-cache met exact het factuurbedrag, versterkt door factuurnummer/crediteurnaam — signaal,
nooit blokkerend, geen live RLZ-call."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, text

from app.bank import betaald_signaal
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import VendorCache
from tests.bank.conftest import maak_bank_mutatie
from tests.documenten.conftest import _opslag_naar_tmp, opslag  # noqa: F401


def _rekening(admin_engine: Engine, administratie_id: uuid.UUID, naam: str, iban: str) -> uuid.UUID:
    rekening_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.payment_account_cache (id, administratie_id, naam, iban, rekening_type, brondata) "
                "VALUES (:id, :aid, :naam, :iban, 1, '{}')"
            ),
            {"id": rekening_id, "aid": administratie_id, "naam": naam, "iban": iban},
        )
    return rekening_id


class TestZoekAlBetaald:
    def test_exact_bedrag_met_factuurnummer_en_naam_wint_van_kaal_bedrag(
        self, admin_engine: Engine, administratie_id: uuid.UUID
    ) -> None:
        rekening = _rekening(admin_engine, administratie_id, "ING zakelijk", "NL22INGB0001238102")
        kaal = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-1512.50", tegenpartij_naam="Iemand anders",
            omschrijving="overboeking", payment_account_id=rekening,
        )
        sterk = maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-1512.50",
            tegenpartij_naam="Floor Bouwliften B.V.", omschrijving="Factuur 88122 augustus", payment_account_id=rekening,
        )
        # Ander bedrag én al afgeletterd (open 0) tellen nooit mee.
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-1512.49", omschrijving="Factuur 88122")
        maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-1512.50", open_bedrag="0", omschrijving="Factuur 88122"
        )
        treffers = betaald_signaal.zoek_al_betaald(
            administratie_id=administratie_id,
            totaalbedrag=Decimal("1512.50"),
            referentie="88122",
            vendor_naam="Floor Bouwliften",
        )
        assert [t.mutatie_id for t in treffers] == [sterk, kaal]
        assert treffers[0].redenen == (
            "bedrag incl. btw exact gelijk",
            "factuurnummer in omschrijving",
            "crediteurnaam herkend",
        )
        assert treffers[0].rekening_naam == "ING zakelijk" and treffers[0].rekening_iban == "NL22INGB0001238102"
        assert treffers[1].redenen == ("bedrag incl. btw exact gelijk",)

    def test_naamherkenning_negeert_rechtsvorm_en_korte_tokens(self) -> None:
        assert betaald_signaal.naam_herkend("Floor Bouwliften B.V.", "FLOOR BOUWLIFTEN BV", None)
        assert not betaald_signaal.naam_herkend("De B.V.", "Jansen B.V.", "huur")
        assert not betaald_signaal.naam_herkend(None, "Floor", "x")

    def test_deelbetaling_som_bewust_buiten_scope(self, admin_engine: Engine, administratie_id: uuid.UUID) -> None:
        """Parkeerpost (G-rekening/deelbetaling): twee mutaties die sámen het bedrag vormen geven
        geen signaal — alleen een exact enkelvoudig bedrag."""
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-1000.00", omschrijving="Factuur 1 deel")
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-210.00", omschrijving="Factuur 1 G-rek")
        assert (
            betaald_signaal.zoek_al_betaald(
                administratie_id=administratie_id, totaalbedrag=Decimal("1210.00"), referentie="1", vendor_naam=None
            )
            == []
        )


class TestSignaalVoorDocument:
    def test_niet_toetsbaar_zonder_crediteur_en_toetsbaar_met_kop(
        self,
        admin_engine: Engine,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        vendor_id = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(VendorCache(id=vendor_id, administratie_id=administratie_id, naam="Floor Bouwliften B.V.", brondata={}))
        resultaat = service.upload_document(
            administratie_id=administratie_id, bestandsnaam="f.pdf", inhoud=b"%PDF-1.4 f", actor_id=gescoopte_gebruiker, opslag=opslag
        )
        signaal = betaald_signaal.signaal_voor_document(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert signaal.toetsbaar is False and signaal.treffers == []

        maak_bank_mutatie(
            admin_engine, administratie_id=administratie_id, bedrag="-121.00",
            tegenpartij_naam="Floor Bouwliften", omschrijving="F-2026-0042",
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-2026-0042",
            factuurdatum=date(2026, 8, 20),
            totaalbedrag=Decimal("121.00"),
            regels=[],
        )
        signaal = betaald_signaal.signaal_voor_document(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert signaal.toetsbaar is True
        assert len(signaal.treffers) == 1
        assert set(signaal.treffers[0].redenen) == {
            "bedrag incl. btw exact gelijk",
            "factuurnummer in omschrijving",
            "crediteurnaam herkend",
        }
