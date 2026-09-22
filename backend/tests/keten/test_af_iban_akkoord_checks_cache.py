"""Casus (af) — BUG Peter 21-09 (Beleggingsmaatschappij Meyer / Belastingdienst 0015.21.664.V.51.0112): "IBAN-wissel"
bleef Blokkerend "gecontroleerd 09:15 (ongewijzigd)" terwijl het IBAN ná 09:15 via de vier-ogen-accordering al vertrouwd
was — het gecachte externe rapport (0165) droeg de oude vertrouwde set en bleef 15 min geldig, óók voor boeken.

Gespeeld op de échte BDO-UBL (casus h, IBAN NL95KETN1000000010 in de XML) mét een ANDERE vertrouwde baseline op de
crediteur: de check blokkeert en cachet (zoals om 09:15), het vier-ogen-akkoord maakt de cache in dezelfde transactie
ongeldig, de eerstvolgende controle is OK zonder op de klok te wachten en boeken slaagt direct."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken, boekvoorstel, checks_extern, iban_accordering, leverancier_iban
from app.documenten.models import DocumentStatus, IbanSoort
from tests.documenten.test_vragen import _extra_gebruiker
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)
#: De vertrouwde rekening van vóór deze factuur (geanonimiseerd, syntactisch geldig) — de UBL draagt een ándere.
OUDE_VERTROUWDE_IBAN = "NL91ABNA0417164300"
FACTUUR_IBAN = "NL95KETN1000000010"


def _iban_rij(dto: dict) -> dict:
    return next(r for r in dto["resultaten"] if r["naam"] == "IBAN-wissel")


def _cache_vingerafdruk(admin_engine: Engine, document_id: uuid.UUID) -> str | None:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT vingerafdruk FROM boekhouding.check_extern_cache WHERE document_id = :d"), {"d": document_id}
        ).first()
    return rij.vingerafdruk if rij else None


@pytest.fixture
def bdo_geblokkeerd(keten: Keten) -> uuid.UUID:
    """BDO mét een oudere vertrouwde rekening; de UBL-factuur draagt een ander IBAN → de externe controle blokkeert
    en cachet het rapport (de stand van 09:15 op Peters scherm)."""
    leverancier_iban.leg_baseline_vast(
        administratie_id=keten.administratie_id,
        vendor_id=keten.vendors["bdo"],
        iban=OUDE_VERTROUWDE_IBAN,
        actor_id=keten.actor,
    )
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
    keten.open_controlescherm(document_id)
    eerste = keten.checks_dto(document_id)
    rij = _iban_rij(eerste)
    assert not rij["ok"] and "wijkt af" in rij["melding"], rij
    assert eerste["extern_uit_cache"] is False
    # Tweede controle binnen de 15 min: uit de cache ("ongewijzigd") — en nog steeds Blokkerend.
    tweede = keten.checks_dto(document_id)
    assert tweede["extern_uit_cache"] is True and not _iban_rij(tweede)["ok"]
    return document_id


def _vier_ogen_akkoord(keten: Keten, document_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    accordeur = _extra_gebruiker(keten.admin_engine, met_scope_op=keten.administratie_id, beheerder_id=beheerder_id)
    iban_accordering.zet_accordeurs(
        administratie_id=keten.administratie_id, actor_id=beheerder_id, accordeurs=[accordeur]
    )
    aanvraag = iban_accordering.bied_aan(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        nieuw_iban=FACTUUR_IBAN,
        soort=IbanSoort.REGULIER,
    )
    assert keten.status(document_id) == DocumentStatus.WACHT_OP_IBAN_ACCORDERING
    data = iban_accordering.accordeer(
        administratie_id=keten.administratie_id, accordering_id=aanvraag.id, actor_id=accordeur
    )
    assert data.document_status == DocumentStatus.TE_CONTROLEREN
    return accordeur


class TestAkkoordWerktDirectDoor:
    def test_akkoord_maakt_de_cache_ongeldig_en_de_controle_is_direct_ok(
        self, keten: Keten, bdo_geblokkeerd: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        oud = _cache_vingerafdruk(keten.admin_engine, bdo_geblokkeerd)
        assert oud is not None and not oud.startswith(checks_extern.ONGELDIG_PREFIX)
        _vier_ogen_akkoord(keten, bdo_geblokkeerd, beheerder_id)
        # Slot 1: de akkoord-transactie heeft de cache-rij ongeldig gemarkeerd.
        nieuw = _cache_vingerafdruk(keten.admin_engine, bdo_geblokkeerd)
        assert nieuw is not None and nieuw.startswith(checks_extern.ONGELDIG_PREFIX)
        # Dezelfde route als het controlescherm, ver binnen de 15 min: vers gedraaid, IBAN-wissel OK.
        dto = keten.checks_dto(bdo_geblokkeerd)
        assert dto["extern_uit_cache"] is False
        assert _iban_rij(dto)["ok"], _iban_rij(dto)["melding"]
        # Het aanbieden-paneel en de check-rij kunnen elkaar niet meer tegenspreken: opnieuw aanbieden = 409-tekst.
        with pytest.raises(iban_accordering.IbanAlVertrouwd, match="al in de vertrouwde set"):
            iban_accordering.bied_aan(
                administratie_id=keten.administratie_id,
                document_id=bdo_geblokkeerd,
                actor_id=keten.actor,
                nieuw_iban=FACTUUR_IBAN,
                soort=IbanSoort.REGULIER,
            )
        # Daarna cachet de verse run weer gewoon — de vingerafdruk mét de nieuwe set is stabiel.
        assert keten.checks_dto(bdo_geblokkeerd)["extern_uit_cache"] is True

    def test_elk_pad_naar_de_vertrouwde_set_auditeert_het_aantal_ongeldig_gemaakte_rapporten(
        self, keten: Keten, bdo_geblokkeerd: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        """Nameting 22-09 (productie 21-09: drie set-mutaties via bevestig/baseline/seed, nul akkoorden — en alleen het
        akkoord-pad schreef `checks_cache_ongeldig`): het veld staat nu op ÉLK `leverancier_iban_toegevoegd`-audit.
        De baseline uit de fixture (nog geen cache-rij) telt 0, het vier-ogen-akkoord ≥ 1."""
        _vier_ogen_akkoord(keten, bdo_geblokkeerd, beheerder_id)
        with keten.admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'leverancier_iban_toegevoegd' "
                    "AND administratie_id = :a ORDER BY tijdstip"
                ),
                {"a": keten.administratie_id},
            ).all()
        waarden = [rij.nieuwe_waarde for rij in rijen]
        assert [w["bron"] for w in waarden] == ["baseline", "bevestigd"], waarden
        assert all("checks_cache_ongeldig" in w for w in waarden), waarden
        assert waarden[0]["checks_cache_ongeldig"] == 0  # baseline vóór de eerste controle: nog niets te invalideren
        assert waarden[-1]["checks_cache_ongeldig"] >= 1  # het akkoord trof de gecachte rij van de fixture

    def test_boeken_direct_na_het_akkoord_slaagt_binnen_de_15_min(
        self, keten: Keten, bdo_geblokkeerd: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        voorstel = keten.prefill(bdo_geblokkeerd)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=keten.administratie_id,
            document_id=bdo_geblokkeerd,
            actor_id=keten.actor,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=GB_ADVIES,
                    taxrate_id=TAXRATE_HOOG,
                    project_id=PROJECT_26084,
                    netto_bedrag=Decimal("5500.00"),
                    btw_bedrag=Decimal("1155.00"),
                    omschrijving="Samenstellen jaarrekening 2025",
                )
            ],
        )
        # Vóór het akkoord blokkeert de boekknop op de IBAN-wissel (rapport uit de cache, modus AUTO).
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boeken.boek_document(
                administratie_id=keten.administratie_id, document_id=bdo_geblokkeerd, actor_id=keten.actor
            )
        assert keten.rlz.puts == []
        _vier_ogen_akkoord(keten, bdo_geblokkeerd, beheerder_id)
        resultaat = boeken.boek_document(
            administratie_id=keten.administratie_id, document_id=bdo_geblokkeerd, actor_id=keten.actor
        )
        assert resultaat.rlz_boekstuknummer
        assert keten.status(bdo_geblokkeerd) == DocumentStatus.GEBOEKT
        assert len(keten.rlz.puts) == 1 and keten.rlz.puts[0]["reference"] == "6088744"
