"""DTO's voor de uren-&-meerwerk-veld-API (fase 2, mockup uren-uitvoerder.html): de native
app-endpoints voor ZZP'er / uitvoerder / detacheerder. De kantoor-DTO's (meerwerklijst,
beoordeel-paneel, beheer) volgen in fase 3 op dezelfde schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class DagDto(BaseModel):
    id: uuid.UUID
    datum: date
    uren: Decimal
    m2: Decimal | None = None
    opmerking: str | None = None
    ingevuld_door_naam: str | None = None
    namens: bool
    # Correctievoorstel van de laatste afkeuring (hybride keuring, besluit 22-08) — de app
    # toont ze alleen in status `corrigeren`.
    voorstel_uren: Decimal | None = None
    voorstel_m2: Decimal | None = None
    voorstel_opmerking: str | None = None
    # Planning-dekking (planning-agenda, besluit 22-08): uren zonder planningstoewijzing op
    # (persoon, project, dag) = oranje "buiten planning" bij de keuring — nooit een blokkade.
    buiten_planning: bool = False
    # Signaal >N uur per dag (steigerbouw-run A6): som van de uren van deze persoon op deze
    # kalenderdag over álle weekstaten heen; boven de administratie-drempel = oranje vlag bij
    # de keuring + zichtbaar voor kantoor. Nooit een blokkade.
    dag_totaal_uren: Decimal = Decimal("0")
    boven_dagmax: bool = False
    dagmax_uren: Decimal | None = None
    # Geofence-stempels (blok C 28-08): gestempelde aanwezigheid — None = geen stempels (toets
    # zwijgt); afwijking > 1,0 u = oranje vlag; onvolledig paar = markering. Nooit een blokkade.
    gestempeld_uren: Decimal | None = None
    stempel_van: time | None = None
    stempel_tot: time | None = None
    stempel_onvolledig: bool = False
    stempel_afwijking: bool = False


class StempelInvoerDto(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    tijdstip: datetime
    soort: Literal["in", "uit"]
    bron: Literal["app", "os_geofence"] = "app"


class StempelsInvoerDto(StrikteInvoer):
    stempels: list[StempelInvoerDto] = Field(min_length=1, max_length=200)


class StempelsOntvangenDto(BaseModel):
    nieuw: int


class StempelZoneDto(BaseModel):
    """Projectzone voor de OS-geofence-registratie (geofence-native): uit de weekplanning van de
    veldwerker zelf, alleen projecten mét zone, max 20."""

    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    lat: Decimal
    lon: Decimal
    straal_m: int


class StempelDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    tijdstip: datetime
    soort: str
    bron: str


class WeekstaatDto(BaseModel):
    # m²-toetsbron (steigerbouw-run D6): geleverde m² (materiaalstand) naast gebouwde m² op het
    # project (goedgekeurde staten + deze staat); meer gebouwd dan geleverd = signaal bij de keuring.
    m2_geleverd_project: Decimal | None = None
    m2_gebouwd_project: Decimal | None = None
    meer_gebouwd_dan_geleverd: bool = False
    id: uuid.UUID
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    dagen: list[DagDto]
    ingediend_op: datetime | None = None
    ingediend_door_naam: str | None = None
    ingediend_namens: bool = False
    goedgekeurd_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    afgekeurd_op: datetime | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class ProjectKaartDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None
    open_weken: int
    laatste_invoer: date | None = None


class WeekKaartDto(BaseModel):
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    status: str  # 'nieuw' = nog geen staat
    weekstaat_id: uuid.UUID | None = None
    dagen_ingevuld: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class IngediendeWeekDto(BaseModel):
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    ingediend_namens: bool = False
    goedgekeurd_door_naam: str | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class ZzperKaartDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    aantal_projecten: int
    open_weken: int
    laatste_invoer: date | None = None
    # A3 (04-09): handelingen — 0 = niets te doen, de app toont de ZZP'er dan niet in de werklijst.
    te_doen: int = 0


class WeekOverzichtKaartDto(BaseModel):
    """Planning-gestuurd beginscherm (A2, 04-09): de weken die er toe doen voor deze ZZP'er."""

    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    is_huidige: bool
    geplande_projecten: int
    te_doen: int
    status: str  # open | ingediend | goedgekeurd | nieuw
    totaal_uren: Decimal
    totaal_m2: Decimal


class WeekProjectKaartDto(BaseModel):
    """Projecten in één week (A1, 04-09): ingepland én/of met een bestaande staat."""

    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None
    gepland: bool
    geplande_dagen: int
    status: str  # nieuw | concept | ingediend | goedgekeurd | corrigeren
    te_doen: bool
    weekstaat_id: uuid.UUID | None = None
    dagen_ingevuld: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class ProjectKeuzeDto(BaseModel):
    """Uitwijk "+ ander project" (A1): actieve projecten in de scope, doorzoekbaar in de app."""

    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None


class WeekstaatZoekDto(BaseModel):
    """Lookup (ZZP'er, project, week) → de staat of null als die nog niet bestaat."""

    weekstaat: WeekstaatDto | None = None


class TeKeurenItemDto(BaseModel):
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    zzper_id: uuid.UUID
    zzper_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    ingediend_namens: bool = False
    ingediend_door_naam: str | None = None


class MeerwerkDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    omschrijving: str
    aantal: Decimal
    eenheid: str
    datum_uitgevoerd: date
    in_opdracht_van: str | None = None
    heeft_foto: bool
    foto_bestandsnaam: str | None = None
    gemeld_door_naam: str | None = None
    gemeld_op: datetime
    status: str
    prijs_per_eenheid: Decimal | None = None
    bedrag: Decimal | None = None
    facturatie_notitie: str | None = None
    beoordeeld_op: datetime | None = None
    beoordeeld_door_naam: str | None = None
    afwijs_reden: str | None = None
    doorbelast_op: datetime | None = None
    verkoopfactuur_referentie: str | None = None
    vraag_tekst: str | None = None
    vraag_gesteld_op: datetime | None = None
    vraag_antwoord: str | None = None
    vraag_beantwoord_op: datetime | None = None


class ProjectDocumentKaartDto(BaseModel):
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None = None
    bestandsnaam: str


class ProjectDetailDto(BaseModel):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    gebouwd_m2: Decimal
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None
    documenten: list[ProjectDocumentKaartDto]
    meerwerk: list[MeerwerkDto]


class UitvoerderProjectKaartDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    gebouwd_m2: Decimal
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    meerwerk_gemeld: int
    te_keuren: int


# --- requests ---------------------------------------------------------------------------------


class DagZettenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    jaar: int
    weeknummer: int
    datum: date
    uren: Decimal
    m2: Decimal | None = None
    opmerking: str | None = None
    # Detacheerder-namens-flow (besluit 21-08): de ZZP'er van wie de staat is. Weglaten = de
    # actor zelf (moet dan een ZZP'er zijn).
    namens_zzper_id: uuid.UUID | None = None


class WeekIndienenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    jaar: int
    weeknummer: int
    namens_zzper_id: uuid.UUID | None = None


class DagCorrectieDto(StrikteInvoer):
    """Correctievoorstel per bestaande dagregel bij het afkeuren (hybride keuring, besluit
    22-08): minstens één van uren/m²/opmerking gevuld — de service valideert hard."""

    datum: date
    uren: Decimal | None = None
    m2: Decimal | None = None
    opmerking: str | None = None


class WeekAfkeurenRequest(StrikteInvoer):
    reden: str
    correcties: list[DagCorrectieDto] = []


class VraagAntwoordRequest(StrikteInvoer):
    tekst: str


# --- kantoor (fase 3) ---------------------------------------------------------------------------


class UrenStandDto(BaseModel):
    meerwerk_te_beoordelen: int
    meerwerk_nog_doorbelasten: int
    meerwerk_te_lang_niet_doorbelast: int
    urenstaten_wachten_op_keuring: int
    # ZZP-dossier (A1) — werkvoorraad-signaal op de klantpagina-stand.
    dossier_veldwerkers_met_signaal: int = 0
    dossier_ter_controle: int = 0
    dossier_geblokkeerd: int = 0


class StaffelRegelDto(BaseModel):
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None = None


class MeerwerkGoedkeurenRequest(StrikteInvoer):
    prijs_per_eenheid: Decimal
    bedrag: Decimal
    facturatie_notitie: str | None = None


class MeerwerkAfwijzenRequest(StrikteInvoer):
    reden: str


class MeerwerkDoorbelastRequest(StrikteInvoer):
    verkoopfactuur_referentie: str


class ToewijzingDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    # Afgeleide herkomst (C2 04-09, geen kolom): 'planning' = er bestaat een planningstoewijzing,
    # 'weekstaat' = alleen uren, 'handmatig' = historische Beheerder-koppeling (blijft staan).
    bron: str = "handmatig"


class GekoppeldeZzperDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    # Bureau-tarief per detacheerder↔zzp'er-koppeling (besluit 1, 21-08 — het hoofdmechanisme
    # van de bureaufactuurmatch). None = "geen tarief bekend" (match alleen op uren, oranje).
    uurtarief: Decimal | None = None


class CrediteurKoppelingDto(BaseModel):
    """Veldwerker↔RLZ-crediteur per administratie (factuurmatch fase 3) + het losse
    ZZP-uurtarief op die koppeling."""

    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    vendor_id: uuid.UUID
    vendor_naam: str | None = None
    uurtarief: Decimal | None = None
    # Autoboek-opt-in per koppeling (factuurmatch fase 4, besluit 4 — default UIT).
    autoboeken_ingeschakeld: bool = False


class DossierSamenvattingDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    aantal_verplicht: int
    aantal_aanwezig: int
    aantal_ontbrekend: int
    aantal_verlopen: int
    aantal_verloopt_binnenkort: int
    aantal_ter_controle: int
    herinneringen_teller: int
    geblokkeerd: bool
    compleet: bool


class VeldgebruikerDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    e_mail: str
    rol: str
    status: str
    projecten: list[ToewijzingDto]
    zzpers: list[GekoppeldeZzperDto]
    crediteuren: list[CrediteurKoppelingDto] = []
    # Afwijkings-logging (besluit 22-08, kantoor-only — de veld-API exposeert dit nooit):
    # afkeuringen mét correctievoorstel + opgetelde uren-delta (ingediend − goedgekeurd).
    uren_afwijking_aantal: int = 0
    uren_afwijking_som: Decimal = Decimal("0")
    # ZZP-dossier per administratie (A1): teller + signalen voor de dossier-badge op het paneel.
    dossiers: list[DossierSamenvattingDto] = []


class ProjectKoppelingRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_id: uuid.UUID


class DetacheerderKoppelingRequest(StrikteInvoer):
    detacheerder_id: uuid.UUID
    zzper_id: uuid.UUID


class VeldwerkerCrediteurRequest(StrikteInvoer):
    """Crediteur-koppeling + los ZZP-uurtarief (upsert per veldwerker; Beheerder-only)."""

    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    vendor_id: uuid.UUID
    uurtarief: Decimal | None = None


class VeldwerkerCrediteurVerwijderRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID


class VeldwerkerAutoboekenRequest(StrikteInvoer):
    """Autoboek-opt-in per veldwerker-koppeling (factuurmatch fase 4, default UIT)."""

    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    ingeschakeld: bool


class DetacheerderTariefRequest(StrikteInvoer):
    """Bureau-tarief op een bestaande detacheerder↔zzp'er-koppeling; None wist het tarief."""

    detacheerder_id: uuid.UUID
    zzper_id: uuid.UUID
    uurtarief: Decimal | None = None


# --- planning-agenda steigerbouw (akkoord Peter 22-08, mockup planning-steigerbouw.html) --------


class PlanningKaartDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str | None = None
    rol: str
    dagdeel: str  # 'heel' | 'half' (½-label op het kaartje)


class PlanningProjectRijDto(BaseModel):
    """V3 (besluit Peter 23-08): de leesroute levert ÁLLE actieve projecten als rij — de UI
    splitst op per_datum (mét planning bovenaan, de rest compact en direct beplanbaar).
    is_actief=False alleen bij een gedeactiveerd project dat mét planning zichtbaar blijft."""

    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    soort_werk: str | None = None
    looptijd_tot: date | None = None
    is_actief: bool = True
    week_man: int  # "deze week: N man"
    per_datum: dict[str, list[PlanningKaartDto]]  # ISO-datum → kaartjes
    # Werkopdrachten (31-08): actuele opdrachten die de week raken (chip) + dag-overrides
    # binnen de week (ISO-datum → afwijkende teksten in de dagcel).
    werkopdrachten: list[WerkopdrachtKortDto] = []
    werkopdracht_overrides: dict[str, list[WerkopdrachtDagTekstDto]] = {}


class PlanningPoolPersoonDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    rol: str
    geplande_dagen: Decimal  # heel = 1, half = 0,5 — besluit C: > 5 kleurt als zacht signaal


class BuitenPlanningMeldingDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str | None = None
    datum: date
    project_naam: str | None = None
    uren: Decimal


class DubbeleDagMeldingDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str | None = None
    datum: date
    project_namen: list[str]
    ongedekte_project_namen: list[str]


class DubbeleDagTellerDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str | None = None
    aantal: int  # ongedekte dubbele dagen in de laatste 30 dagen


class WachtrisicoKortDto(BaseModel):
    """D5-kruissignaal op de personeelsplanning: ploeg gepland zonder bevestigde levering."""

    project_id: uuid.UUID
    project_naam: str | None = None
    datum: date
    aantal_personen: int
    transport_id: uuid.UUID | None = None
    leverancier_naam: str | None = None
    samenvatting: str


class PlanningWeekDto(BaseModel):
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    projecten: list[PlanningProjectRijDto]
    pool: list[PlanningPoolPersoonDto]
    buiten_planning: list[BuitenPlanningMeldingDto]
    dubbele_dagen: list[DubbeleDagMeldingDto]
    dubbele_dag_tellers: list[DubbeleDagTellerDto]
    wachtrisico: list[WachtrisicoKortDto] = []


class PlanningToewijzingRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_id: uuid.UUID
    datum: date
    dagdeel: str = "heel"


class PlanningVerwijderRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_id: uuid.UUID
    datum: date


class PlanningVerplaatsRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    van_project_id: uuid.UUID
    van_datum: date
    naar_project_id: uuid.UUID
    naar_datum: date


class PlanningDagdeelRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_id: uuid.UUID
    datum: date
    dagdeel: str


class MijnPlanningDagDto(BaseModel):
    """Alleen-lezen veld-weergave (besluit B): waar moet ik heen deze week."""

    datum: date
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    dagdeel: str
    # Werkopdracht(en) geldend op deze dag (31-08): override wint, afwijkend=True voor die dag.
    werkopdrachten: list[WerkopdrachtDagTekstDto] = []


# --- werkopdrachten per project × periode (akkoord Peter 31-08, migratie 0091) ------------------


class WerkopdrachtDagTekstDto(BaseModel):
    groep_id: uuid.UUID
    tekst: str
    afwijkend: bool  # True = dag-override ("di afwijkend: …")


class WerkopdrachtKortDto(BaseModel):
    groep_id: uuid.UUID
    van: date
    tot_en_met: date
    tekst: str


class WerkopdrachtDagOverrideDto(BaseModel):
    datum: date
    tekst: str


class WerkopdrachtHistorieRegelDto(BaseModel):
    tijdstip: datetime
    door_naam: str
    omschrijving: str


class WerkopdrachtDto(BaseModel):
    """Actuele stand van één werkopdracht-groep mét historie (append-only) en dag-overrides."""

    groep_id: uuid.UUID
    project_id: uuid.UUID
    versie: int
    van: date
    tot_en_met: date
    tekst: str
    dag_overrides: list[WerkopdrachtDagOverrideDto] = []
    historie: list[WerkopdrachtHistorieRegelDto] = []


class WerkopdrachtAanmakenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    van: date
    tot_en_met: date
    tekst: str = Field(min_length=1, max_length=4000)


class WerkopdrachtWijzigenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    van: date
    tot_en_met: date
    tekst: str = Field(min_length=1, max_length=4000)


class WerkopdrachtDagOverrideRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    datum: date
    tekst: str = Field(min_length=1, max_length=4000)


class ModuleRechtRequest(StrikteInvoer):
    gebruiker_id: uuid.UUID
    ingeschakeld: bool


class ModuleRechtDto(BaseModel):
    gebruiker_id: uuid.UUID
    ingeschakeld: bool


class ModuleRechtHoudersDto(BaseModel):
    gebruiker_ids: list[uuid.UUID]


# --- ZZP-dossier per veldwerker (steigerbouw-run blok A, migratie 0072) ------------------------------


class DossierDocumenttypeDto(StrikteInvoer):
    code: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    naam: str = Field(min_length=1, max_length=80)
    verplicht: bool = True
    geldig_tot_vereist: bool = True
    bsn_gevoelig: bool = False
    volgorde: int = Field(ge=0, le=999)
    actief: bool = True


class DossierDocumenttypenDto(BaseModel):
    typen: list[DossierDocumenttypeDto]
    is_standaard: bool


class DossierDocumenttypenZettenRequest(StrikteInvoer):
    typen: list[DossierDocumenttypeDto] = Field(min_length=1, max_length=50)


class DossierDocumentDto(BaseModel):
    code: str
    naam: str
    verplicht: bool
    geldig_tot_vereist: bool
    bsn_gevoelig: bool
    status: str  # ontbreekt | ter_controle | afgewezen | goedgekeurd | verloopt_binnenkort | verlopen
    document_id: uuid.UUID | None = None
    geldig_tot: date | None = None
    verloopt_over_dagen: int | None = None
    bestandsnaam: str | None = None
    content_type: str | None = None
    geupload_op: datetime | None = None
    geupload_door_naam: str | None = None
    bron: str | None = None
    afwijs_reden: str | None = None
    beoordeeld_door_naam: str | None = None
    beoordeeld_op: datetime | None = None


class DossierDto(BaseModel):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str
    documenten: list[DossierDocumentDto]
    aantal_verplicht: int
    aantal_aanwezig: int
    aantal_ontbrekend: int
    aantal_verlopen: int
    aantal_verloopt_binnenkort: int
    aantal_ter_controle: int
    compleet: bool
    compleet_incl_ter_controle: bool
    herinneringen_teller: int
    herinneringen_max: int = 3
    laatste_herinnering_op: datetime | None = None
    geblokkeerd: bool
    geblokkeerd_op: datetime | None = None
    kan_herinneren_vandaag: bool
    kvk_nummer: str | None = None
    btw_nummer: str | None = None
    kvk_naam: str | None = None
    kvk_plaats: str | None = None
    kvk_rechtsvorm: str | None = None
    kvk_bevestigd_op: datetime | None = None
    kvk_bevestigd_door_naam: str | None = None
    signalen: list[str] = []


class DossierBeoordelenRequest(StrikteInvoer):
    goedgekeurd: bool
    reden: str | None = Field(default=None, max_length=1000)


class DossierHerinneringResultaatDto(BaseModel):
    gebruiker_id: uuid.UUID
    volgnummer: int
    kanaal: str
    verzonden_op: datetime
    geblokkeerd: bool


class KvkLookupDto(BaseModel):
    kvk_nummer: str
    gevonden: bool
    naam: str | None = None
    rechtsvorm: str | None = None
    adres: str | None = None
    postcode: str | None = None
    plaats: str | None = None
    uitgeschreven: bool = False
    datum_einde: str | None = None
    testomgeving: bool = False


class BedrijfsgegevensBevestigenRequest(StrikteInvoer):
    kvk_nummer: str | None = Field(default=None, max_length=8)
    btw_nummer: str | None = Field(default=None, max_length=20)
    naam: str | None = Field(default=None, max_length=200)
    plaats: str | None = Field(default=None, max_length=100)
    rechtsvorm: str | None = Field(default=None, max_length=100)


class MijnToegangDto(BaseModel):
    """Slimme landing + Planning-menu (steigerbouw-run C1/C2): heeft de ingelogde kantoormedewerker
    het module-recht 'Meerwerk & urenstaten' en op welke administraties in zijn scope staat de
    uren-&-meerwerk-opt-in aan. Fail-closed aan de client-kant: bij twijfel de gewone werkvoorraad."""

    heeft_meerwerk_recht: bool
    administraties_met_opt_in: list[uuid.UUID]
    aantal_administraties_in_scope: int
    is_beheerder: bool
    # 31-08: fijnmazig recht 'veldwerkerbeheer' (+ZZP'er/archiveren in de planning-zijbalk)
    # en de rolvlag voor "+ Project aanmaken"/leverancierbeheer (Beheerder óf B+P).
    heeft_veldwerkerbeheer_recht: bool = False
    is_beheerder_of_bp: bool = False
    # 04-09 (mee-lift-punt 0.2, besluit Peter): "+ Project aanmaken" op /planning volgt dezelfde
    # rolpoort als de combobox-ingang — óók Boekhouding (spiegel van `projecten.kantoor._AANMAAK_ROLLEN`).
    mag_project_aanmaken: bool = False
    # Odoo-afrondingsrun 04-09 blok B (besluit Peter): administraties in scope mét toegang tot de
    # MATERIAALCATALOGUS = uren-opt-in ÓF Odoo-backend ÓF Odoo-leesbron-koppeling (voeding voor de
    # administratie-kiezer op /instellingen/materiaal). `administraties_met_opt_in` blijft puur de
    # steigerbouw-opt-in (planning, weekstaten, bestellingen, transport).
    administraties_met_catalogus: list[uuid.UUID] = []
