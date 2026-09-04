from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.documenten.checks import (
    CheckRegel,
    check_duplicaat,
    check_iban_wissel,
    check_regeltelling,
    check_verplichte_velden,
    voer_harde_checks_uit,
)
from app.rlz.client import RlzApiError


class _NepRlzClient:
    """Stub voor de duplicaatcheck — geen echte HTTP-aanroep, alleen de vorm die
    check_duplicaat() nodig heeft (find_purchase_invoices_by_reference)."""

    def __init__(self, gevonden: list[dict]) -> None:
        self.gevonden = gevonden
        self.aanroepen: list[dict] = []

    def find_purchase_invoices_by_reference(self, *, vendor_id, reference, total_amount=None, expand_entity=False):
        self.aanroepen.append({"vendor_id": vendor_id, "reference": reference, "total_amount": total_amount})
        if vendor_id is None:  # punt 14: cross-crediteur-zoektocht — eigen lijst, default leeg
            return list(getattr(self, "gevonden_andere", []))
        return self.gevonden


class _FoutRlzClient:
    """Stub die altijd de meegegeven exception opgooit — simuleert een falende RLZ-aanroep
    tijdens de duplicaatquery."""

    def __init__(self, fout: Exception) -> None:
        self.fout = fout

    def find_purchase_invoices_by_reference(self, *, vendor_id, reference, total_amount=None):
        raise self.fout


def _regel(**overrides) -> CheckRegel:
    basis = dict(
        ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")
    )
    basis.update(overrides)
    return CheckRegel(**basis)


class TestVerplichteVelden:
    def test_alles_ingevuld_is_ok(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
        )
        assert resultaat.ok

    def test_geen_regels_blokkeert(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[],
        )
        assert not resultaat.ok
        assert "minstens één boekingsregel" in resultaat.melding

    def test_ontbrekende_crediteur_en_regelvelden_blokkeert(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            regels=[_regel(ledger_id=None, taxrate_id=None, netto_bedrag=None)],
        )
        assert not resultaat.ok
        for verwacht in [
            "crediteur",
            "referentie",
            "factuurdatum",
            "totaalbedrag",
            "grootboekrekening",
            "btw-code",
            "netto bedrag",
        ]:
            assert verwacht in resultaat.melding


class TestRegeltelling:
    def test_som_gelijk_aan_totaal_is_ok(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=Decimal("121.00"), regels=[_regel()])
        assert resultaat.ok

    def test_klein_afrondingsverschil_is_nog_ok(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("121.01"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"))],
        )
        assert resultaat.ok

    def test_groot_verschil_blokkeert(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("200.00"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"))],
        )
        assert not resultaat.ok
        assert "wijkt" in resultaat.melding

    def test_meerdere_regels_worden_gesommeerd(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("242.00"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")) for _ in range(2)],
        )
        assert resultaat.ok

    def test_geen_totaalbedrag_blokkeert(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=None, regels=[_regel()])
        assert not resultaat.ok


class TestDuplicaat:
    def test_geen_hits_is_ok(self) -> None:
        client = _NepRlzClient(gevonden=[])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert resultaat.ok

    def test_hit_van_ander_document_blokkeert(self) -> None:
        ander_id = str(uuid.uuid4())
        client = _NepRlzClient(gevonden=[{"id": ander_id}])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok

    def test_hit_van_eigen_client_guid_is_geen_duplicaat(self) -> None:
        """Een retry na boeken_mislukt vindt het EIGEN, al eerder gelukte PUT-document terug —
        dat mag de duplicaatcheck niet laten blokkeren (anders kan een idempotente retry nooit
        meer slagen)."""
        eigen_id = uuid.uuid4()
        client = _NepRlzClient(gevonden=[{"id": str(eigen_id)}])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=eigen_id,
        )
        assert resultaat.ok

    def test_zonder_vendor_of_referentie_blokkeert_zonder_aanroep(self) -> None:
        client = _NepRlzClient(gevonden=[])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=None,
            referentie=None,
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok
        assert client.aanroepen == []

    def test_filtert_op_afgekapte_referentie_en_bedrag(self) -> None:
        client = _NepRlzClient(gevonden=[])
        lange_referentie = "F" * 40
        check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie=lange_referentie,
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert client.aanroepen[0]["reference"] == lange_referentie  # afkappen zit in RlzClient zelf
        assert client.aanroepen[0]["total_amount"] == 121.0

    def test_rlz_fout_geeft_blokkerend_checkresultaat_geen_exception(self) -> None:
        """Een falende RLZ-aanroep tijdens de duplicaatquery mag nooit als kale 500 bij de
        gebruiker komen (kliktest-bug) — zonder duplicaatcheck is boeken net zo onverantwoord als
        met een echte hit, dus dit blijft blokkerend, maar als een normaal checkresultaat."""
        client = _FoutRlzClient(RlzApiError(502, "GET", "PurchaseInvoices", "RLZ tijdelijk onbereikbaar"))
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok
        assert "kon niet uitgevoerd worden" in resultaat.melding
        assert "onbereikbaar" in resultaat.melding

    def test_onverwachte_fout_geeft_ook_blokkerend_checkresultaat(self) -> None:
        """Ook een fout die geen RlzApiError is (bv. een connectiefout dieper in httpx) mag niet
        als onafgevangen exception naar boven komen — bewust breed gevangen."""
        client = _FoutRlzClient(RuntimeError("onverwachte connectiefout"))
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok
        assert "kon niet uitgevoerd worden" in resultaat.melding


class TestVoerHardeChecksUit:
    def test_alle_checks_ok_geeft_niet_geblokkeerd(self) -> None:
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not rapport.geblokkeerd
        assert [r.naam for r in rapport.resultaten] == [
            "Verplichte velden",
            "Regeltelling vs totaal",
            "Vervaldatum",
            "Btw-tarief buitenland",
            "IBAN-wissel",
            "Duplicaatcheck",
            "Duplicaat bij andere crediteur",  # punt 14 (28-08): signaal/blokkade over crediteuren heen
        ]
        assert all(r.ok for r in rapport.resultaten)

    def test_een_falende_check_blokkeert_het_hele_rapport(self) -> None:
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("999.00"),
            regels=[_regel()],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert rapport.geblokkeerd
        assert not any(r.naam == "Regeltelling vs totaal" and r.ok for r in rapport.resultaten)

    def test_alle_checks_draaien_ook_als_de_eerste_al_faalt(self) -> None:
        """Geen stille kortsluiting — de UI moet alle vier de rijen kunnen tonen (CLAUDE.md,
        mockup-stijl groen/blokkerend per check)."""
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            regels=[],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert len(rapport.resultaten) == 7  # incl. Vervaldatum (C1 26-08) + buitenland-tarief (31-08) + cross-crediteur (punt 14, 28-08)


class TestIbanWissel:
    """Pure checkregels (app/documenten/checks.py::check_iban_wissel) — de DB-/seed-orkestratie
    eromheen wordt integraal getest in test_iban_wissel.py."""

    _VERTROUWD = "NL91ABNA0417164300"
    _ANDER = "BE68539007547034"

    def test_matchende_iban_passeert(self) -> None:
        resultaat = check_iban_wissel(factuur_iban=self._VERTROUWD, vertrouwde_ibans={self._VERTROUWD})
        assert resultaat.ok
        assert "vertrouwde rekening" in resultaat.melding

    def test_tweede_bevestigde_iban_passeert(self) -> None:
        """G-rekening/WKA-nuance: de set is meerwaardig — een tweede, bevestigde rekening is de
        norm, geen wissel-signaal."""
        resultaat = check_iban_wissel(
            factuur_iban=self._ANDER, vertrouwde_ibans={self._VERTROUWD, self._ANDER}
        )
        assert resultaat.ok

    def test_afwijkende_iban_blokkeert_hard(self) -> None:
        resultaat = check_iban_wissel(factuur_iban=self._ANDER, vertrouwde_ibans={self._VERTROUWD})
        assert not resultaat.ok
        assert "wijkt af" in resultaat.melding
        # Privacy: nooit het volledige IBAN in de melding — gemaskeerd tonen.
        assert self._ANDER not in resultaat.melding

    def test_lege_set_met_baseline_is_ok_en_benoemt_de_baseline(self) -> None:
        resultaat = check_iban_wissel(
            factuur_iban=self._VERTROUWD, vertrouwde_ibans=set(), baseline_vastgelegd=True
        )
        assert resultaat.ok
        assert "baseline" in resultaat.melding
        assert self._VERTROUWD not in resultaat.melding

    def test_lege_set_zonder_baseline_is_ok(self) -> None:
        resultaat = check_iban_wissel(factuur_iban=self._VERTROUWD, vertrouwde_ibans=set())
        assert resultaat.ok

    def test_mislukte_seed_blokkeert_fail_closed(self) -> None:
        """Lege set + mislukte RLZ-seed: de check blokkeert op eigen titel — een wissel is niet
        uit te sluiten zonder referentie; nooit leunen op een toevallig ook-blokkerende
        duplicaatcheck."""
        resultaat = check_iban_wissel(
            factuur_iban=self._VERTROUWD, vertrouwde_ibans=set(), seed_mislukt=True
        )
        assert not resultaat.ok
        assert "kon niet worden opgehaald" in resultaat.melding
        assert self._VERTROUWD not in resultaat.melding

    def test_mislukte_seed_blokkeert_niet_zonder_factuur_iban(self) -> None:
        """Zonder factuur-IBAN valt er ook bij een mislukte seed niets te wisselen — geen blok
        op ontbrekende data (oude extracties zonder iban-veld blijven boekbaar)."""
        resultaat = check_iban_wissel(factuur_iban=None, vertrouwde_ibans=set(), seed_mislukt=True)
        assert resultaat.ok

    def test_geen_iban_op_de_factuur_is_ok(self) -> None:
        resultaat = check_iban_wissel(factuur_iban=None, vertrouwde_ibans={self._VERTROUWD})
        assert resultaat.ok
        assert "Geen (geldig) IBAN" in resultaat.melding


class TestRegeltellingBasis:
    """Bugfix 04-09 (Huvanco-casus, mockup-notitie ⑨): de check vergeleek Σ(netto+btw) met het INCL-
    totaal terwijl de btw per regel ontbrak (feitelijk Σnetto = excl) → vals "wijkt € 117,95 af". Nu
    dezelfde beslisboom als de veldvoorstel-badge (app/documenten/regelsom.py) en altijd expliciet
    welke basis vergeleken is."""

    # Huvanco-vorm: regels zonder btw per regel + kortingsregel negatief; alleen incl gelezen als totaal.
    _REGELS = [
        _regel(netto_bedrag=Decimal("400.00"), btw_bedrag=None),
        _regel(netto_bedrag=Decimal("164.40"), btw_bedrag=None),
        _regel(netto_bedrag=Decimal("-56.44"), btw_bedrag=None),  # "Korting 10% −56,44"
    ]
    _INCL = Decimal("614.63")  # 507,96 + 21 % = 106,67 → 614,63
    _EXCL = Decimal("507.96")
    _BTW = Decimal("106.67")

    def test_oude_vorm_zou_vals_afwijken_nieuwe_code_toetst_netto_vs_excl(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=self._INCL, regels=self._REGELS, totaal_excl=self._EXCL)
        assert resultaat.ok
        assert "netto € 507.96" in resultaat.melding and "totaal excl." in resultaat.melding

    def test_met_factuur_btw_toetst_netto_plus_factuur_btw_vs_incl(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=self._INCL, regels=self._REGELS, factuur_btw=self._BTW)
        assert resultaat.ok
        assert "factuur-btw € 106.67" in resultaat.melding and "totaal incl." in resultaat.melding

    def test_zonder_excl_en_zonder_factuur_btw_is_een_expliciete_melding_nooit_excl_vs_incl(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=self._INCL, regels=self._REGELS)
        assert not resultaat.ok
        assert "Btw per regel ontbreekt (regel 1, 2, 3)" in resultaat.melding
        assert "geen totaal excl. btw gelezen" in resultaat.melding
        assert "netto € 507.96" in resultaat.melding and "614.63" in resultaat.melding
        # De oude, foute vergelijking (verschil 106,67) mag nérgens meer in de melding staan.
        assert "106.67" not in resultaat.melding and "wijkt" not in resultaat.melding

    def test_echte_afwijking_op_excl_basis_benoemt_de_basis(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=self._INCL, regels=self._REGELS, totaal_excl=Decimal("600.00"))
        assert not resultaat.ok
        assert "netto € 507.96" in resultaat.melding and "wijkt € 92.04 af" in resultaat.melding
        assert "totaal excl. (€ 600.00)" in resultaat.melding

    def test_btw_per_regel_compleet_blijft_netto_plus_btw_vs_incl_ook_met_excl_bekend(self) -> None:
        regels = [
            _regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")),
            _regel(netto_bedrag=Decimal("-10.00"), btw_bedrag=Decimal("-2.10")),  # kortingsregel mét btw
        ]
        resultaat = check_regeltelling(totaalbedrag=Decimal("108.90"), regels=regels, totaal_excl=Decimal("90.00"))
        assert resultaat.ok
        assert "netto + btw € 108.90" in resultaat.melding and "totaal incl." in resultaat.melding

    def test_negatieve_regel_komt_door_de_regeltelling(self) -> None:
        """Motoren accepteren negatieve regels al (creditnota-lijn) — de check ook: korting verlaagt de som."""
        regels = [_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")), _regel(
            netto_bedrag=Decimal("-56.44"), btw_bedrag=Decimal("-11.85")
        )]
        assert check_regeltelling(totaalbedrag=Decimal("52.71"), regels=regels).ok

    def test_alleen_excl_zonder_incl_toetst_netto_vs_excl(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=None, regels=self._REGELS, totaal_excl=self._EXCL)
        assert resultaat.ok  # verplichte-velden blokkeert het ontbrekende incl-totaal apart

    def test_netto_ontbreekt_op_een_regel_is_niet_toetsbaar(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("121.00"),
            regels=[_regel(netto_bedrag=None, btw_bedrag=None)],
            totaal_excl=Decimal("100.00"),
        )
        assert not resultaat.ok and "Netto bedrag ontbreekt" in resultaat.melding

    def test_geen_regels_blokkeert_leesbaar(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=Decimal("121.00"), regels=[])
        assert not resultaat.ok and "Geen boekingsregels" in resultaat.melding

    def test_voer_harde_checks_uit_geeft_de_gelezen_totalen_door(self) -> None:
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="HUV-1",
            factuurdatum=date.today(),
            totaalbedrag=self._INCL,
            regels=self._REGELS,
            eigen_rlz_document_id=uuid.uuid4(),
            totaal_excl=self._EXCL,
        )
        regeltelling = next(r for r in rapport.resultaten if r.naam == "Regeltelling vs totaal")
        assert regeltelling.ok and "totaal excl." in regeltelling.melding
