"""Leesbare reconciliatie-teksten (fixrun 07-09 blok A8): per blok en per soort een titel (≤ 60 tekens),
één zin "wat is er" en één zin "wat doe je" met NAMEN — nooit een GUID of vingerafdruk in titel/wat/doe;
technische sleutels in `details`. Defensieve terugval op de CLI-regel als naamvelden ontbreken (oude runs),
default-tekst voor onbekende soorten (contract A↔A8), NL-bedragen en DD-MM-JJJJ-datums. Pure module: geen DB."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from app.reconciliatie import teksten
from app.reconciliatie.teksten import MAX_TITEL, bevat_technische_sleutel, datum, euro, leesbaar, zonder_guids

DOC = "aaaaaaaa-1111-2222-3333-444444444444"
RLZ = "bbbbbbbb-1111-2222-3333-444444444444"
ADM = "cccccccc-1111-2222-3333-444444444444"


@dataclass
class B:
    blok: str
    soort: str
    tekst: str
    detail: dict | None = None
    vingerafdruk: str = "0123456789abcdef"
    administratie_naam: str | None = None
    extra: dict = field(default_factory=dict)


def _afwijking(blok: str, afwijking_soort: str, detail_tekst: str, **namen) -> B:
    return B(
        blok=blok,
        soort="afwijking",
        tekst=f"document={DOC} rlz_document={RLZ} soort={afwijking_soort} [vaf:0123456789abcdef]: {detail_tekst}",
        detail={
            "bron": blok,
            "record_id": DOC,
            "afwijking_soort": afwijking_soort,
            "detail": detail_tekst,
            "geaccepteerd": False,
            "uitsluiting": None,
            "document_id": DOC,
            **namen,
        },
    )


def _schoon(lb: teksten.Leesbaar) -> None:
    assert lb.titel and lb.wat and lb.doe
    assert len(lb.titel) <= MAX_TITEL, lb.titel
    for zin in (lb.titel, lb.wat, lb.doe):
        assert not bevat_technische_sleutel(zin), zin
    assert lb.details and lb.details[0] == ("vingerafdruk", "0123456789abcdef")


class TestFormatters:
    def test_euro_nl_notatie(self) -> None:
        assert euro("274.89") == "€ 274,89"
        assert euro(Decimal("1234.5")) == "€ 1.234,50"
        assert euro("-85.2") == "€ -85,20"
        assert euro("1234567.891") == "€ 1.234.567,89"
        assert euro(None) is None and euro("") is None and euro("abc") is None

    def test_datum_dd_mm_jjjj(self) -> None:
        assert datum("2026-09-03") == "03-09-2026"
        assert datum("2026-09-03T04:31:00+00:00") == "03-09-2026"
        assert datum(date(2026, 1, 9)) == "09-01-2026"
        assert datum(None) is None

    def test_zonder_guids_en_vaf(self) -> None:
        assert zonder_guids(f"document {DOC} [vaf:abc123] op 2026-09-03") == "document … op 03-09-2026"


class TestDocumenten:
    def test_bedrag_wijkt_af_is_het_voorbeeld_van_peter(self) -> None:
        lb = leesbaar(
            _afwijking(
                "documenten",
                "bedrag_wijkt_af",
                "eigen=€274.89 rlz=€279.51",
                leverancier_naam="Kader Consultancy",
                factuurnummer="F212604921",
                rlz_boekstuk="RLZ-01-00000241",
                bedrag_lokaal="274.89",
                bedrag_extern="279.51",
                backend="rlz",
            )
        )
        _schoon(lb)
        # Titel ≤ 60: het boekstuk valt als eerste weg (nooit half afgekapt), de rest blijft intact.
        assert lb.titel == "Bedrag afwijkt in RLZ — Kader Consultancy F212604921"
        assert lb.wat == "Wij boekten € 274,89, RLZ toont € 279,51."
        assert lb.doe == "Controleer de wijziging in RLZ; klopt die, accepteer met reden."
        assert ("record", DOC) in lb.details and ("soort", "bedrag_wijkt_af") in lb.details
        assert any(label == "ruwe regel" and "[vaf:" in waarde for label, waarde in lb.details)

    def test_ontbreekt_in_rlz_met_bedrag_en_datum(self) -> None:
        lb = leesbaar(
            _afwijking(
                "documenten",
                "ontbreekt_in_rlz",
                "404 NotFound",
                leverancier_naam="Labo Derva",
                factuurnummer="2026-118",
                bedrag_lokaal="1234.5",
                boekdatum="2026-09-03",
            )
        )
        _schoon(lb)
        assert lb.titel == "RLZ-document verdwenen — Labo Derva 2026-118"
        assert lb.wat == "Wij boekten € 1.234,50 op 03-09-2026, in RLZ bestaat het boekstuk niet meer."
        assert lb.doe == "Boek opnieuw via de actie op deze rij, of accepteer met reden."

    def test_odoo_soorten_gebruiken_odoo_als_systeem(self) -> None:
        niet = leesbaar(
            _afwijking(
                "documenten",
                "niet_geboekt_in_odoo",
                "state=draft",
                backend="odoo",
                extern_state="draft",
                leverancier_naam="Bouwmaat",
                factuurnummer="88",
            )
        )
        _schoon(niet)
        assert niet.titel == "Niet geboekt in Odoo — Bouwmaat 88" and "op 'draft'" in niet.wat
        terug = leesbaar(_afwijking("documenten", "teruggedraaid_in_odoo", "reversal", backend="odoo"))
        _schoon(terug)
        assert terug.titel == "Teruggedraaid in Odoo" and "tegenboeking" in terug.wat
        weg = leesbaar(_afwijking("documenten", "ontbreekt_in_odoo", "404", backend="odoo", leverancier_naam="X"))
        _schoon(weg)
        assert weg.titel.startswith("Odoo-document verdwenen") and "in Odoo bestaat" in weg.wat

    @pytest.mark.parametrize(
        ("soort", "detail_tekst", "titel_kop", "wat_fragment"),
        [
            ("status_wijkt_af", "RLZ-status=1", "Boeking teruggezet in RLZ", "status 1 (concept)"),
            ("status_niet_definitief", "RLZ-status=1", "Boeking teruggezet in RLZ", "status 1 (concept)"),
            ("boekstuknummer_wijkt_af", "eigen='RLZ-01-1' rlz='RLZ-01-2'", "Boekstuknummer afwijkt", "'RLZ-01-1'"),
            ("controle_mislukt", "500 Server Error", "Controle mislukt", "zegt dat niets"),
        ],
    )
    def test_overige_documenten_soorten(self, soort, detail_tekst, titel_kop, wat_fragment) -> None:
        lb = leesbaar(_afwijking("documenten", soort, detail_tekst, leverancier_naam="Kempen", factuurnummer="1"))
        _schoon(lb)
        assert lb.titel.startswith(titel_kop) and wat_fragment in lb.wat

    def test_terugval_zonder_naamvelden_oude_run(self) -> None:
        """Oude runs: geen leverancier/factuurnummer/bedragen in detail — de bedragen komen uit de vrije
        tekst, GUID's verdwijnen, de titel blijft leesbaar."""
        lb = leesbaar(_afwijking("documenten", "bedrag_wijkt_af", "eigen=€100 rlz=€90"))
        _schoon(lb)
        assert lb.titel == "Bedrag afwijkt in RLZ" and lb.wat == "Wij boekten € 100,00, RLZ toont € 90,00."

    def test_onbekende_soort_krijgt_default_tekst_zonder_guids(self) -> None:
        lb = leesbaar(
            _afwijking("documenten", "iets_nieuws_van_agent_a", f"vreemde toestand {RLZ}", leverancier_naam="Bouwmaat")
        )
        _schoon(lb)
        assert lb.titel == "Afwijking in RLZ — Bouwmaat" and lb.wat == "vreemde toestand …"
        assert "accepteer met reden" in lb.doe

    def test_geaccepteerd_zelfde_titel_andere_doe(self) -> None:
        b = _afwijking("documenten", "bedrag_wijkt_af", "eigen=€1 rlz=€2", leverancier_naam="Kempen")
        b.soort = "geaccepteerd"
        b.detail["geaccepteerd"] = True
        lb = leesbaar(b)
        _schoon(lb)
        assert lb.titel == "Bedrag afwijkt in RLZ — Kempen" and "intrekken" in lb.doe.lower()

    def test_uitgesloten_afwijking_meldt_uitsluiting(self) -> None:
        b = _afwijking("documenten", "bedrag_wijkt_af", "eigen=€1 rlz=€2", leverancier_naam="Kempen")
        b.soort = "uitgesloten"
        b.detail["uitsluiting"] = "testadministratie"
        lb = leesbaar(b)
        _schoon(lb)
        assert "uitgesloten van de teller (testadministratie)" in lb.doe


class TestBank:
    def _bank(self, soort: str, detail_tekst: str, **namen) -> B:
        b = _afwijking("bank", soort, detail_tekst, **namen)
        b.tekst = f"record={DOC} mutatie={RLZ} soort={soort} [vaf:0123456789abcdef]: {detail_tekst}"
        b.detail["payment_transaction_id"] = RLZ
        return b

    def test_boeking_teruggedraaid_met_namen(self) -> None:
        lb = leesbaar(
            self._bank(
                "boeking_teruggedraaid_in_rlz",
                "RLZ-documentstatus=1 (verwacht 3) — vermoedelijk",
                tegenpartij_naam="Shell",
                mutatie_bedrag="-85.20",
                mutatie_datum="2026-08-30",
                rekening_naam="Rabo zakelijk",
            )
        )
        _schoon(lb)
        assert lb.titel == "Bankboeking teruggedraaid in RLZ — Shell · € -85,20"  # datum valt weg (> 60)
        assert lb.wat.startswith("Wij boekten de bankmutatie van 30-08-2026 (Shell, € -85,20) op Rabo zakelijk;")
        assert "status 1 (concept)" in lb.wat and "bankscherm" in lb.doe
        assert ("RLZ-mutatie", RLZ) in lb.details

    @pytest.mark.parametrize(
        ("soort", "detail_tekst", "titel", "doe_fragment"),
        [
            ("document_ontbreekt_in_rlz", "404", "Bankboeking verdwenen uit RLZ", "opnieuw in het bankscherm"),
            ("mutatie_ontbreekt_in_rlz", "404", "Bankmutatie verdwenen uit RLZ", "bankafschrift"),
            (
                "aflettering_teruggedraaid_in_rlz",
                "OpenAmount=120.5 terwijl …",
                "Aflettering teruggedraaid in RLZ",
                "Letter opnieuw af",
            ),
            ("controle_mislukt", "502", "Controle mislukt", "credentials"),
            ("onbekend", "x", "Afwijking in de bank", "accepteer met reden"),
        ],
    )
    def test_bank_soorten_zonder_namen_terugval(self, soort, detail_tekst, titel, doe_fragment) -> None:
        lb = leesbaar(self._bank(soort, detail_tekst))
        _schoon(lb)
        assert lb.titel == titel and doe_fragment in lb.doe

    def test_aflettering_open_bedrag_uit_detailtekst(self) -> None:
        lb = leesbaar(
            self._bank("aflettering_teruggedraaid_in_rlz", "OpenAmount=120.5 terwijl …", referentie="F-2026-9")
        )
        assert "op F-2026-9" in lb.wat and "€ 120,50 open" in lb.wat


class TestOmzet:
    def _omzet(self, soort: str, kant: str, **namen) -> B:
        b = _afwijking(
            "omzet", soort, f"Periode 2026-08-01 t/m 2026-08-31: {kant} {RLZ} staat in RLZ op Status 1", **namen
        )
        b.tekst = f"AFWIJKING  {ADM} boeking={DOC} soort={soort} [vaf:0123456789abcdef]: {b.detail['detail']}"
        return b

    def test_half_geboekt_met_periode_en_omzet(self) -> None:
        lb = leesbaar(self._omzet("half_geboekt", "verkoopfactuur", totaal_omzet="15230.10", rlz_boekstuk="VF-2026-8"))
        _schoon(lb)
        assert lb.titel == "Omzet half geboekt — 01-08-2026 t/m 31-08-2026 · VF-2026-8"
        assert lb.wat == (
            "De verkoopfactuur van periode 01-08-2026 t/m 31-08-2026 (€ 15.230,10) staat geboekt, "
            "het kostprijsmemoriaal niet."
        )
        assert "half-geboekt-route" in lb.doe

    def test_periode_uit_detailtekst_als_velden_ontbreken(self) -> None:
        lb = leesbaar(self._omzet("status_niet_definitief", "kostprijsmemoriaal"))
        _schoon(lb)
        assert lb.titel == "Omzetboeking teruggezet in RLZ — 01-08-2026 t/m 31-08-2026"
        assert "het kostprijsmemoriaal" in lb.wat and "status 1 (concept)" in lb.wat

    @pytest.mark.parametrize("soort", ["ontbreekt_in_rlz", "controle_mislukt", "onbekend"])
    def test_overige_omzet_soorten_schoon(self, soort) -> None:
        _schoon(leesbaar(self._omzet(soort, "verkoopfactuur")))


class TestDoorbelasting:
    def _db(self, soort: str, detail_tekst: str, **namen) -> B:
        b = _afwijking("doorbelasting", soort, detail_tekst, **namen)
        b.tekst = f"AFWIJKING  {ADM} boeking={DOC} soort={soort} [vaf:0123456789abcdef]: {detail_tekst}"
        return b

    def test_spiegel_open_verouderd_met_doelnaam(self) -> None:
        lb = leesbaar(
            self._db(
                "spiegel_open_verouderd",
                "open spiegel-taak staat al 12 dagen open (doel niet onboarded?)",
                doelentiteit_naam="Kempen Facilities B.V.",
                verkoop_referentie="24713188",
            )
        )
        _schoon(lb)
        assert lb.titel == "Spiegelboeking wacht te lang — Kempen Facilities B.V."  # ref valt weg (> 60)
        assert lb.wat == (
            "De spiegel-inkoopfactuur bij Kempen Facilities B.V. staat al 12 dagen open — "
            "is de doel-administratie wel onboarded?"
        )

    def test_half_geboekt_sinds_datum_nl(self) -> None:
        lb = leesbaar(
            self._db(
                "half_geboekt", "half geboekt sinds 2026-08-20: {...}", doelentiteit_naam="Vastly", bedrag_lokaal="500"
            )
        )
        _schoon(lb)
        assert (
            lb.wat
            == "De verkoopfactuur aan Vastly (€ 500,00) staat geboekt, de spiegel-inkoopfactuur niet sinds 20-08-2026."
        )

    def test_controle_mislukt_zonder_credentials_doel(self) -> None:
        lb = leesbaar(
            self._db(
                "controle_mislukt",
                f"doel-administratie {ADM} heeft geen credentials (meer) — spiegel niet controleerbaar",
            )
        )
        _schoon(lb)
        assert "geen werkende RLZ-credentials" in lb.wat

    @pytest.mark.parametrize("soort", ["ontbreekt_in_rlz", "status_niet_definitief", "onbekend"])
    def test_overige_doorbelasting_soorten_schoon(self, soort) -> None:
        lb = leesbaar(self._db(soort, f"spiegel-inkoopfactuur {RLZ} staat in RLZ op Status 1", doelentiteit_naam="X"))
        _schoon(lb)
        if soort != "onbekend":
            assert "spiegel-inkoopfactuur in de doel-administratie" in lb.wat


class TestLetOpFoutUitgesloten:
    def test_opruim_kandidaat(self) -> None:
        b = B(
            blok="doorbelasting",
            soort="let_op",
            tekst=f"LET-OP     opruim-kandidaat [gestorneerd] verkoop_bron {RLZ} in administratie {ADM} "
            f"(document {DOC}, ref 24713188) — x",
            detail={
                "kant": "verkoop_bron",
                "rlz_id": RLZ,
                "concept_administratie_id": ADM,
                "document_id": DOC,
                "referentie": "24713188",
                "reden": "gestorneerd",
                "detail": "x",
                "concept_administratie_naam": "Kempen Groep B.V.",
                "leverancier_naam": "Bouwmaat",
                "factuurnummer": "F1",
                "doelentiteit_naam": "Kempen Facilities B.V.",
            },
        )
        lb = leesbaar(b)
        _schoon(lb)
        assert lb.titel == "Achtergebleven concept in RLZ — Kempen Groep B.V."
        assert lb.wat.startswith(
            "Een verkoop-concept in de bron-administratie van een gestorneerde doorbelasting "
            "aan Kempen Facilities B.V. "
            "van Bouwmaat F1 (ref 24713188) staat nog in Reeleezee"
        )
        assert "klikwerk in Reeleezee" in lb.doe and "'Gezien'" in lb.doe
        assert ("RLZ-id", RLZ) in lb.details and ("administratie-id concept", ADM) in lb.details

    def test_opruim_kandidaat_oude_run_zonder_namen_gebruikt_administratienaam(self) -> None:
        b = B(
            blok="doorbelasting",
            soort="let_op",
            tekst=f"LET-OP     opruim-kandidaat [vervallen_run] spiegel_doel {RLZ} in administratie {ADM}",
            detail={"kant": "spiegel_doel", "rlz_id": RLZ, "reden": "vervallen_run"},
        )
        lb = leesbaar(b, administratie_naam="Bron BV")
        _schoon(lb)
        assert lb.titel == "Achtergebleven concept in RLZ — de doel-administratie"
        assert "spiegel-concept in de doel-administratie van een vervallen boekpoging" in lb.wat

    def test_opruimlijst_fout(self) -> None:
        lb = leesbaar(
            B(
                blok="doorbelasting",
                soort="let_op",
                tekst=f"LET-OP     opruimlijst: verkoop {RLZ} niet controleerbaar: 500",
                detail={"reden": "opruimlijst_fout"},
            )
        )
        _schoon(lb)
        assert lb.titel == "Opruimlijst niet compleet" and lb.wat == "verkoop … niet controleerbaar: 500"

    def test_fout_per_administratie_met_naam(self) -> None:
        lb = leesbaar(
            B(blok="bank", soort="fout", tekst=f"FOUT       {ADM}: GeenRlzCredentials: geen credentials", detail=None),
            administratie_naam="BLOW B.V.",
        )
        _schoon(lb)
        assert lb.titel == "Administratie niet gecontroleerd — BLOW B.V."
        assert lb.wat == "Het blok bank kon deze administratie niet controleren: GeenRlzCredentials: geen credentials."
        # verrijkt detail (nieuwe runs) heeft voorrang op de tekst-parsing
        lb2 = leesbaar(
            B(blok="bank", soort="fout", tekst="FOUT x", detail={"fout": "timeout", "administratie_naam": "BLOW B.V."})
        )
        assert lb2.wat.endswith(": timeout.") and lb2.titel.endswith("BLOW B.V.")

    def test_blok_viel_om_en_storno_detectie(self) -> None:
        lb = leesbaar(B(blok="omzet", soort="fout", tekst="FOUT       omzet-reconciliatie viel om: RuntimeError boem"))
        _schoon(lb)
        assert lb.titel == "Controle omzet viel om" and lb.wat == "Het blok omzet is niet gedraaid: RuntimeError boem."
        s = leesbaar(
            B(blok="documenten", soort="fout", tekst=f"FOUT       storno-detectie {ADM}: 401"),
            administratie_naam="X BV",
        )
        _schoon(s)
        assert s.titel == "Storno-detectie mislukt — X BV" and s.wat.endswith(": 401.")

    def test_uitgesloten_administratie(self) -> None:
        lb = leesbaar(
            B(
                blok="documenten",
                soort="uitgesloten",
                tekst=f"UITGESLOTEN {ADM}: credentials kapot (uitgesloten: testadministratie)",
            ),
            administratie_naam="Test BV",
        )
        _schoon(lb)
        assert lb.titel == "Uitgesloten van controle — Test BV"
        assert lb.wat == "credentials kapot — uitgesloten omdat: testadministratie."
        assert lb.doe == "Telt niet mee in de teller; geen handeling nodig."


class TestRobuustheid:
    def test_leeg_detail_en_lege_tekst_vallen_nooit_om(self) -> None:
        lb = leesbaar(B(blok="bank", soort="afwijking", tekst="", detail=None))
        assert lb.titel == "Afwijking in de bank" and lb.wat == "Zie de technische details."

    def test_uuid_objecten_in_detail(self) -> None:
        b = _afwijking("documenten", "ontbreekt_in_rlz", "404")
        b.detail["record_id"] = uuid.UUID(DOC)
        lb = leesbaar(b)
        _schoon(lb)
        assert ("record", DOC) in lb.details

    def test_alle_soorten_uit_contract_a_gedekt(self) -> None:
        """Contract A↔A8 punt 2: élke soort van agent A heeft een eigen (niet-default) tekst."""
        for soort in (
            "ontbreekt_in_rlz",
            "ontbreekt_in_odoo",
            "bedrag_wijkt_af",
            "status_wijkt_af",
            "controle_mislukt",
            "niet_geboekt_in_odoo",
            "teruggedraaid_in_odoo",
        ):
            lb = leesbaar(_afwijking("documenten", soort, "x", leverancier_naam="L", factuurnummer="1"))
            assert not lb.titel.startswith("Afwijking in"), soort
