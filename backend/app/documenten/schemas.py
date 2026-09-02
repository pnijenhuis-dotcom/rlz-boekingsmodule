from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.schemas_basis import StrikteInvoer


def _naar_decimal_met_komma(waarde: object) -> object:
    """Accepteert zowel '1234.56' als NL-notatie '1.234,56' — de frontend normaliseert vóór
    verzending altijd naar punt-decimaal (design-pass taak P2), maar deze validator maakt de API
    zelf ook robuust voor directe aanroepen (curl/scripts/oude clients) met een komma-decimaal.
    Een komma in de string is het onderscheidende signaal: zonder komma nemen we de waarde als
    al-genormaliseerd punt-decimaal aan (geen giswerk over duizendtal-punten)."""
    if isinstance(waarde, str) and "," in waarde:
        schoon = waarde.strip().replace(".", "").replace(",", ".")
        try:
            Decimal(schoon)
        except InvalidOperation:
            return waarde  # laat pydantic zelf de oorspronkelijke waarde afwijzen met een nette fout
        return schoon
    return waarde


DecimalMetKomma = Annotated[Decimal, BeforeValidator(_naar_decimal_met_komma)]


class DuplicaatReferentieResponse(BaseModel):
    """Genoeg om in de UI een klikbare link te tonen (design-pass taak 5) — bestandsnaam +
    uploaddatum van het vermoedelijke origineel, nooit een kale UUID."""

    document_id: uuid.UUID
    bestandsnaam: str
    aangemaakt_op: datetime


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None


class VerwijderenInput(StrikteInvoer):
    """Reden VERPLICHT (werkstroom-run 27/28-08, punt 4 — herziet design-pass taak 4 "optioneel"):
    verwijderen zit sindsdien achter het ⋯-rijmenu mét bevestiging en volgt het afwijs-patroon
    (verplichte reden), zodat een zware actie nooit meer op één onbeschermde klik gebeurt. De reden
    landt in tijdlijn + audit_event. De servicelaag blijft reden=None toestaan voor interne
    aanroepers; de HTTP-poort niet."""

    reden: str = Field(min_length=1, max_length=500)

    @field_validator("reden")
    @classmethod
    def _reden_niet_leeg(cls, waarde: str) -> str:
        if not waarde.strip():
            raise ValueError("Een reden is verplicht bij verwijderen")
        return waarde.strip()


class DocumentActieResponse(BaseModel):
    document_id: uuid.UUID
    status: str


class AfwijzingInfoDto(BaseModel):
    """Open afwijzing bij een document (mockup werkvoorraad: chip "Afgewezen — ter controle"
    mét reden en wie afwees; controlescherm: banner + heropenen-knop)."""

    id: uuid.UUID
    reden: str
    afgewezen_door: uuid.UUID
    afgewezen_op: datetime
    toegewezen_aan: uuid.UUID
    status_voor_afwijzing: str


class FactuurmatchKortDto(BaseModel):
    """Compacte matchstand voor de werkvoorraad-chip (factuurmatch fase 2, besluit 3 —
    duplicaat-patroon: losse vlag bovenop de normale flow, geen status)."""

    uitkomst: str
    verschil_bedrag: Decimal | None = None
    verschil_uren: Decimal | None = None
    tarief_ontbreekt: bool = False


class FactuurmatchDto(BaseModel):
    """Volledige matchstand (controlescherm-banner + fase-3-match-sectie)."""

    document_id: uuid.UUID
    veldwerker_naam: str | None = None
    uitkomst: str
    staten_som_uren: Decimal
    staten_som_bedrag: Decimal | None = None
    factuur_bedrag: Decimal | None = None
    factuur_uren: Decimal | None = None
    verschil_bedrag: Decimal | None = None
    verschil_uren: Decimal | None = None
    tarief_ontbreekt: bool = False
    details: dict | None = None
    berekend_op: datetime
    afwijking_bevestigd: bool = False
    afwijking_bevestigd_op: datetime | None = None


class FactuurmatchHerberekenInput(StrikteInvoer):
    """Expliciete herberekening ("periode-keuze"): optioneel een handmatige staten-selectie
    (gevalideerd in de motor — alleen goedgekeurde, onverrekende staten van de betrokken
    ZZP'ers) en/of een mens-opgave van de factuur-uren."""

    weekstaat_ids: list[uuid.UUID] | None = None
    factuur_uren: DecimalMetKomma | None = None


class FactuurmatchResponse(BaseModel):
    """None-vormig antwoord kan niet in FastAPI's response_model zonder wrapper — de match is
    None wanneer die niet van toepassing is (geen gekoppelde crediteur)."""

    factuurmatch: FactuurmatchDto | None = None


class KandidaatStaatDto(BaseModel):
    """Selecteerbare weekstaat voor de periode-keuze in de match-sectie (fase 3)."""

    weekstaat_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str | None = None
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    uren: Decimal
    in_match: bool


class KandidaatStatenResponse(BaseModel):
    staten: list[KandidaatStaatDto]


class BoekenInput(StrikteInvoer):
    """Optionele body van de boek-route (factuurmatch fase 2, besluit 2): de expliciete
    bevestiging "boeken ondanks match-afwijking" — zonder deze vlag antwoordt de server bij
    een afwijking met 409 + de match-cijfers."""

    match_afwijking_bevestigd: bool = False
    # Steigerbouw-run D6: expliciete "boeken ondanks materiaal-afwijking"-bevestiging.
    materiaal_afwijking_bevestigd: bool = False


class MatchMailConceptResponse(BaseModel):
    ontvanger_naam: str | None = None
    ontvanger_e_mail: str
    onderwerp: str
    tekst: str


class MatchMailVerzendenInput(StrikteInvoer):
    onderwerp: str
    tekst: str


class MatchMailVerzondenResponse(BaseModel):
    verzonden_aan: str


class AlBetaaldTrefferDto(BaseModel):
    """Al-betaald-signaal (25-08, deel 2 punt 1): één onafgeletterde bankmutatie uit de lokale
    cache met exact het factuurbedrag; `redenen` = de matchreden(en), nooit blokkerend."""

    mutatie_id: uuid.UUID
    boekdatum: date
    bedrag: Decimal
    rekening_naam: str | None
    rekening_iban: str | None
    tegenpartij_naam: str | None
    omschrijving: str | None
    redenen: list[str]


class AlBetaaldSignaalResponse(BaseModel):
    toetsbaar: bool
    treffers: list[AlBetaaldTrefferDto]


class AanbetalingTrefferDto(BaseModel):
    boeking_id: uuid.UUID
    payment_transaction_id: uuid.UUID
    bedrag: Decimal
    boekdatum: date | None
    geboekt_op: datetime
    rlz_boekstuknummer: str | None
    entity_naam: str | None
    vooruit_ledger_id: uuid.UUID
    herkenning: str


class AanbetalingSignaalResponse(BaseModel):
    """Aanbetaling-open-signaal (feedbackronde 25-08 deel 4 punt 3): open relatie-koppelingen van
    deze crediteur (Entity-match, IBAN als extra herkenning) — signaal, geen blokkade."""

    toetsbaar: bool
    treffers: list[AanbetalingTrefferDto]


class DuplicaatSignaalKortDto(BaseModel):
    """Gecachete RLZ-duplicaatuitkomst (25-08, deel 2 punt 6): 'geen' | 'mogelijk_duplicaat' |
    'niet_toetsbaar' | 'onbekend'. Signalering — de live check bij boeken is bindend."""

    uitkomst: str
    aantal_treffers: int
    berekend_op: datetime


class AccordeurAanDeBeurtDto(BaseModel):
    """C2 26-08: wie bij een ter-accordering-document nu aan de beurt is (kolom "Toegewezen")."""

    gebruiker_id: uuid.UUID
    naam: str
    laag: int


class AfdelingKortDto(BaseModel):
    """Blok A 28-08: de afdeling van het document in de lijst (MI-dimensie, filter later)."""

    id: uuid.UUID
    naam: str


class GeboektInRlzDto(BaseModel):
    """Blok C 02-09: 'Geboekt in RLZ · boekstuk <nr> · <crediteur/debiteur>' + vindplaats-hint
    (Elissen-casus: verkoopfacturen staan in RLZ níét onder Verkopen → Facturen). Uit de boek-events/
    kolommen, geen RLZ-call. `regel` is de kant-en-klare tekst voor tooltip/chip."""

    regel: str
    boekstuknummer: str | None = None
    rlz_document_id: str | None = None
    tegenpartij: str | None = None
    # 'crediteur' | 'debiteur' | None
    tegenpartij_rol: str | None = None
    geboekt_op: datetime
    memoriaal_boekstuknummer: str | None = None
    vindplaats_hint: str | None = None


class DocumentListItemResponse(BaseModel):
    id: uuid.UUID
    bestandsnaam: str
    status: str
    bron: str
    # 'inkoopfactuur' | 'kassarapport' (migratie 0027) — de werkvoorraad routeert een
    # kassarapport naar het omzetreview-scherm en toont de omzetboeking-chip.
    soort: str = "inkoopfactuur"
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime
    # Alleen gevuld bij status 'afgewezen' met een open afwijzing-rij.
    afwijzing: AfwijzingInfoDto | None = None
    # Kopgegevens uit boekvoorstel/extractie (mockup #klantpagina: kolommen Leverancier +
    # Bedrag) — None zolang de extractie nog loopt of niets gevonden is.
    leverancier: str | None = None
    totaalbedrag: Decimal | None = None
    factuurdatum: date | None = None
    # Autoboeken (blok 2, 2026-08-09): geboekt zonder menselijke boek-klik (opt-in leverancier)
    # — voedt de werkvoorraad-chip "automatisch" en het filter "automatisch geboekt".
    automatisch_geboekt: bool = False
    # Blok C 02-09: alleen gevuld bij status geboekt.
    geboekt_in_rlz: GeboektInRlzDto | None = None
    # Factuurmatch (fase 2): matchstand van een veldwerker-factuur — voedt de chip
    # "urenmatch wijkt af" (besluit 3, duplicaat-patroon). None = geen match van toepassing.
    factuurmatch: FactuurmatchKortDto | None = None
    # Accordeur aan de beurt (C2 26-08): alleen bij status ter_accordering — de kolom "Toegewezen"
    # toont "<naam> · laag N" i.p.v. "—"; interne toewijzing blijft voor de overige statussen.
    accordeur_aan_de_beurt: AccordeurAanDeBeurtDto | None = None
    # Bugfix-run 28-08: alle lagen akkoord maar het boeken ná het laatste akkoord faalde — de
    # fouttekst (kolom "Toegewezen" toont de chip "boeken ná akkoord mislukt"). None = geen.
    accordering_boek_fout: str | None = None
    # Punt 24 (opruimrun 28-08): klant-akkoord compleet én nog niet geboekt — opnieuw aanbieden is
    # server-side geweigerd (409); de bulk-selectie zet de checkbox uit mét uitleg "boek direct".
    klant_akkoord_compleet: bool = False
    # Duplicaatsignaal (25-08, deel 2 punt 6): voedt de chip "mogelijk duplicaat in RLZ" + filter.
    duplicaatsignaal: DuplicaatSignaalKortDto | None = None
    # Afdeling (blok A 28-08) — None bij administraties zonder afdelingen of documenten zonder keuze.
    afdeling: AfdelingKortDto | None = None


class LeverancierAutoboekenDto(BaseModel):
    vendor_id: uuid.UUID
    naam: str | None
    autoboeken_ingeschakeld: bool


class LeverancierAutoboekenLijstResponse(BaseModel):
    leveranciers: list[LeverancierAutoboekenDto]


class LeverancierAutoboekenInput(StrikteInvoer):
    ingeschakeld: bool


class WerkvoorraadKlantResponse(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    te_controleren: int
    klaar_om_te_boeken: int
    vragen: int
    afgewezen: int
    bij_klant: int
    iban_wachtend: int
    # Factuurmatch (fase 2, besluit 3): signaal-teller — open documenten met een
    # match-afwijking (de documenten zelf zitten al in een status-teller hierboven).
    match_afwijkingen: int = 0
    # Duplicaatsignaal (25-08, deel 2 punt 6): open documenten met gecachet 'mogelijk_duplicaat'.
    duplicaat_signalen: int = 0
    # Terugkerende facturen (blok B 30-08): leveranciers met een actief "verwachte factuur ontbreekt".
    terugkerend_signalen: int = 0


class WerkvoorraadOverzichtResponse(BaseModel):
    klanten: list[WerkvoorraadKlantResponse]


class DocumentListResponse(BaseModel):
    documenten: list[DocumentListItemResponse]


class DocumentGebeurtenisResponse(BaseModel):
    van_status: str | None
    naar_status: str
    actor_id: uuid.UUID
    # True als de overgang door de systeem-actor is gezet (achtergrondworker, migratie 0016) —
    # de tijdlijn toont dan herkenbaar "systeem" i.p.v. een menselijke handeling.
    actor_is_systeem: bool = False
    detail: dict | None
    tijdstip: datetime


class HerkomstMailDto(BaseModel):
    """Blok "Uit de e-mail" (feedbackronde 25-08 deel 3 punt 1b): herkomst van een document met
    mail-herkomst. `body_tekst` None = geen tekstdeel óf bericht van vóór migratie 0069."""

    afzender: str | None = None
    onderwerp: str | None = None
    ontvangen_op: datetime | None = None
    body_tekst: str | None = None
    bron: str


class DocumentDetailResponse(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID | None
    bestandsnaam: str
    status: str
    bron: str
    soort: str = "inkoopfactuur"
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime
    veldvoorstel: dict | None = None
    afwijzing: AfwijzingInfoDto | None = None
    # Factuurmatch (fase 2): actuele matchstand voor de controlescherm-banner; None = geen
    # match van toepassing (crediteur niet aan een veldwerker gekoppeld).
    factuurmatch: FactuurmatchDto | None = None
    # Alleen bij documenten met mail-herkomst (intake_bericht_id gezet).
    herkomst_mail: HerkomstMailDto | None = None
    # Aangeleverd origineel als het document een omgezette afbeelding is (punt 2, migratie 0070).
    bron_bestandsnaam: str | None = None
    # Gelezen tenaamstelling uit de intake (verzamelbak-sleutel) — voedt de "onthoud"-optie in de
    # verplaats-modal (punt 6a); None bij directe uploads zonder tenaamstelling.
    tenaamstelling: str | None = None
    # Blok C 02-09: alleen gevuld bij status geboekt.
    geboekt_in_rlz: GeboektInRlzDto | None = None
    tijdlijn: list[DocumentGebeurtenisResponse]


class BoekvoorstelRegelDto(BaseModel):
    # DB-id van de opgeslagen regel — sleutel voor de doorbelasting-verdeling (bron_regel_id);
    # None voor prefill-regels die nog niet opgeslagen zijn.
    id: uuid.UUID | None = None
    ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    netto_bedrag: DecimalMetKomma | None = None
    btw_bedrag: DecimalMetKomma | None = None
    omschrijving: str | None = None
    # Herkomst btw-code (punt 3, 26-08): "factuur" = deterministisch uit netto/btw afgeleid
    # (prefill); None = leeg/mens/geheugen. Alleen informatief — de server negeert 'm bij opslaan.
    btw_bron: str | None = None


class BoekvoorstelResponse(BaseModel):
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    # Vervaldatum (C1 26-08) + oranje signaal bij een implausibele termijn (> 90 dagen, geen blokkade).
    vervaldatum: date | None = None
    vervaldatum_signaal: str | None = None
    totaalbedrag: DecimalMetKomma | None = None
    rlz_boekstuknummer: str | None = None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelDto]
    # Fix 3 (2026-07-10): effectieve samenvoeg-stand voor dit document (voorkeur per crediteur,
    # default AAN), of samenvoegen überhaupt kan (False bij projectplicht — hard per-regel) en
    # de deterministisch berekende één-regel-variant voor de samengevoegde weergave.
    regels_samenvoegen: bool = True
    samenvoegen_toegestaan: bool = True
    samengevoegde_regel: BoekvoorstelRegelDto | None = None
    # Letterlijke "btw verlegd"-vermelding uit de extractie (punt 3, 26-08) — hint bij 0%-regels.
    btw_verlegd_vermelding: str | None = None
    # Afdeling (blok A 28-08): de keuze op het document + prefill uit het leverancier-geheugen
    # (alleen zolang er nog geen keuze staat; herkomst-chip "vorige keuze bij <leverancier>").
    afdeling_id: uuid.UUID | None = None
    afdeling_prefill_id: uuid.UUID | None = None
    afdeling_prefill_leverancier: str | None = None


class BoekvoorstelInput(StrikteInvoer):
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    vervaldatum: date | None = None
    afdeling_id: uuid.UUID | None = None
    totaalbedrag: DecimalMetKomma | None = None
    regels: list[BoekvoorstelRegelDto] = []
    # Fix 3: de weergavekeuze van de controleur bij opslaan — wordt als voorkeur per
    # (administratie, crediteur) onthouden. None = niet meegegeven, voorkeur ongemoeid.
    regels_samenvoegen: bool | None = None


class CheckResultaatDto(BaseModel):
    naam: str
    ok: bool
    melding: str
    # Punt 14 (28-08): oranje signaal — ok maar kijken (controlescherm toont 'm oranje).
    signaal: bool = False


class CheckRapportResponse(BaseModel):
    geblokkeerd: bool
    resultaten: list[CheckResultaatDto]


class BoekvoorstelMetChecksResponse(BaseModel):
    boekvoorstel: BoekvoorstelResponse
    checks: CheckRapportResponse
    # Factuurmatch (fase 2): de vers herberekende matchstand na deze opslag — de
    # auto-checks-lus van het controlescherm houdt de banner er actueel mee.
    factuurmatch: FactuurmatchDto | None = None
    # Steigerbouw-run D6: materiaalmatch (verhuur-crediteur) — None zonder koppeling.
    materiaalmatch: dict | None = None


class BoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None = None
    # "Boeken + doorbelasten" (besluit 25-08): resultaat per doelentiteit van de klaargezette
    # doorbelasting (None = er was geen), en een zichtbare fout als de doorbelasting ná de
    # geslaagde inkoopboeking (deels) mislukte — nooit stil.
    doorbelasting_run_id: uuid.UUID | None = None
    doorbelasting: dict[str, str] | None = None
    doorbelasting_fout: str | None = None


class VraagStellenInput(StrikteInvoer):
    """Vraagmodal (mockup #vraagmodal): tekst verplicht (lege vraag wordt óók in de servicelaag
    geweigerd — deze schema-eis is de eerste poort, geen vervanging), toewijzing optioneel
    (default: de administratie-eigenaar, "krijgt vragen")."""

    vraag_tekst: str
    toegewezen_aan: uuid.UUID | None = None


class VraagBerichtInput(StrikteInvoer):
    """Bijdrage in de dialoog (besluit Peter 25-08): tekst verplicht, de vraag blijft open."""

    tekst: str


class VraagAfhandelenInput(StrikteInvoer):
    """ "Afgehandeld" — alleen de vraagsteller; optioneel slotbericht in de thread."""

    slotbericht: str | None = None


class VraagIntrekkenInput(StrikteInvoer):
    """Intrekken (bewuste uitbreiding op de mockup, docs/BESLISSINGEN.md): reden optioneel,
    maar wordt hoe dan ook in het audit_event vastgelegd."""

    reden: str | None = None


class VraagBerichtResponse(BaseModel):
    id: uuid.UUID
    auteur_id: uuid.UUID
    tekst: str
    geplaatst_op: datetime


class VraagResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_bestandsnaam: str
    document_status: str
    totaalbedrag: Decimal | None = None
    vraag_tekst: str
    status: str
    status_voor_vraag: str
    gesteld_door: uuid.UUID
    gesteld_op: datetime
    toegewezen_aan: uuid.UUID
    antwoord_tekst: str | None = None
    beantwoord_door: uuid.UUID | None = None
    beantwoord_op: datetime | None = None
    ingetrokken_door: uuid.UUID | None = None
    ingetrokken_op: datetime | None = None
    ingetrokken_reden: str | None = None
    # Dialoog (migratie 0064): wie aan zet is, afhandeling, de thread (oudste eerst) en de
    # server-side poort-uitkomst voor de "Afgehandeld"-knop (UI-hint; de server hertoetst).
    aan_de_beurt: uuid.UUID
    afgehandeld_door: uuid.UUID | None = None
    afgehandeld_op: datetime | None = None
    berichten: list[VraagBerichtResponse] = []
    mag_afhandelen: bool = False


class VraagLijstResponse(BaseModel):
    vragen: list[VraagResponse]


class AfwijzenInput(StrikteInvoer):
    """Afwijsmodal (mockup #afwijsmodal): reden verplicht (lege reden wordt óók in de service-
    én DB-laag geweigerd — deze schema-eis is de eerste poort, geen vervanging), toewijzing
    "Ter controle naar" optioneel (default: de administratie-eigenaar)."""

    reden: str
    toegewezen_aan: uuid.UUID | None = None


class AfwijzingResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_status: str
    reden: str
    status: str
    status_voor_afwijzing: str
    afgewezen_door: uuid.UUID
    afgewezen_op: datetime
    toegewezen_aan: uuid.UUID
    heropend_door: uuid.UUID | None = None
    heropend_op: datetime | None = None


class IbanAanbiedenInput(StrikteInvoer):
    """IBAN-wissel vier-ogen-accordering (docs/ontwerp/iban-wissel-accordering.md): het nieuwe
    rekeningnummer reist in de request-body, nooit in de URL (privacy — URL's belanden in
    access-logs). `soort` is context voor de accordeur (G-rekening/WKA is de norm-casus)."""

    nieuw_iban: str
    soort: Literal["regulier", "g_rekening"]


class IbanAfwijzenInput(StrikteInvoer):
    """Afwijzen van een IBAN-aanvraag: reden verplicht (schema is de eerste poort; service- en
    DB-laag weigeren een lege reden ook)."""

    reden: str


class IbanAccorderingResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_status: str
    vendor_id: uuid.UUID
    nieuw_iban: str
    soort: str
    status: str
    status_voor_accordering: str
    aangevraagd_door: uuid.UUID
    aangevraagd_op: datetime
    besloten_door: uuid.UUID | None = None
    besloten_op: datetime | None = None
    afwijs_reden: str | None = None


class IbanAccorderingLijstResponse(BaseModel):
    accorderingen: list[IbanAccorderingResponse]


class IbanAccordeursResponse(BaseModel):
    """Instelling "IBAN-wissel accorderen door" — lege lijst betekent: de actieve beheerder(s)
    zijn de accordeurs."""

    accordeurs: list[uuid.UUID]


class IbanAccordeursInput(StrikteInvoer):
    accordeurs: list[uuid.UUID]


# --- tegenboek-pad (mockup tegenboek-mockup.html, akkoord Peter 22-08) --------------------------


class TegenboekVoorbeeldRegelDto(BaseModel):
    """Eén regel van het voorbeeld van de tegenboeking (mockup-tabel: negatieve netto/btw)."""

    grootboek_code: str | None = None
    grootboek_naam: str | None = None
    omschrijving: str
    netto_bedrag: Decimal
    btw_bedrag: Decimal


class TegenboekBetaalstatusDto(BaseModel):
    """Betaalstatus origineel — de waarschuwing "open creditpost" verschijnt alléén als er
    (deels) betaald/afgeletterd is."""

    betaald_bedrag: Decimal
    open_bedrag: Decimal
    volledig_afgeletterd: bool


class TegenboekingInfoDto(BaseModel):
    soort: str
    reden: str
    boek_cyclus: int
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None = None
    origineel_betaald_bedrag: Decimal | None = None
    aangemaakt_op: datetime


class TegenboekToetsResponse(BaseModel):
    """Leesroute voor de sectie op het controlescherm en het ⋯-menu in het archief: de knop
    "Tegenboeken…" verschijnt alléén bij storno_geblokkeerd (en zonder bestaande tegenboeking).
    `betaalstatus` is None als het origineel in RLZ niet leesbaar was."""

    document_id: uuid.UUID
    storno_geblokkeerd: bool
    blokkade_melding: str | None = None
    tegenboeking: TegenboekingInfoDto | None = None
    betaalstatus: TegenboekBetaalstatusDto | None = None
    voorbeeld: list[TegenboekVoorbeeldRegelDto]
    referentie: str | None = None
    tegenboek_referentie: str
    leverancier_naam: str | None = None
    totaal_netto: Decimal
    totaal_btw: Decimal


class TegenboekenInput(StrikteInvoer):
    soort: Literal["volledig", "vervang"]
    reden: str


class TegenboekenResponse(BaseModel):
    document_id: uuid.UUID
    soort: str
    status: str
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None = None


class VerplaatsInput(StrikteInvoer):
    """Addendum kantoor-run 27-08 punt 5: "Verplaats naar andere administratie…" — alleen het doel;
    de bron staat in het pad. Reden is bewust niet verplicht (de verhuizing zelf is de correctie
    en staat volledig in tijdlijn + audit)."""

    doel_administratie_id: uuid.UUID
    # Punt 6a (werkstroom-run 27/28-08): optioneel "onthoud: deze tenaamstelling hoort bij <doel>"
    # — dicht het register-match-gat (toewijzing die uit de administratienaam-match kwam en dus geen
    # leer-regel had). Default UIT; géén automatische leer-regel.
    onthoud_tenaamstelling: bool = False


class DocumentVerplaatsResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    van_administratie_id: uuid.UUID
    van_administratie_naam: str
    naar_administratie_id: uuid.UUID
    naar_administratie_naam: str
    """Leer-regels (tenaamstelling/afzender) die van de oude naar de nieuwe administratie zijn
    gecorrigeerd — leeg = de toewijzing kwam niet uit het geheugen (alleen verplaatst)."""
    leerregels_gecorrigeerd: list[str]
    vragen_verhuisd: int
    vragen_hertoegewezen: int
    # Punt 6a: True als op verzoek een tenaamstelling-regel naar het doel is geleerd.
    tenaamstelling_geleerd: bool = False
