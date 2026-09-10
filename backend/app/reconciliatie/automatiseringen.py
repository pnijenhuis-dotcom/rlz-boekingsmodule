"""Tellers per automatisering in de reconciliatie (herstelrun 07-09 blok C, besluit Peter "geen stille no-op").

Waarom: kernprincipe 7 — een automatisering wacht nooit op een menselijke instelling en mag nooit stil niets
doen. De dagelijkse reconciliatie-run is het vangnet dat dat controleert: per automatisering per etmaal
"verwacht / gedaan / overgeslagen mét reden", plus twee soorten LET-OP-bevindingen:
  1. overgeslagen wegens een ONTBREKENDE HARDE VOORWAARDE (credential, API-key, geldpoort/kill-switch,
     volumerem, noodrem) — mét handeling op de rij (deeplink naar de instelling);
  2. een automatisering die AAN staat en zeven dagen lang 0 gedaan / 0 overgeslagen meldt terwijl er wél
     kandidaten waren ("stil").
Een UITGESCHAKELDE automatisering is één regel "uit" — geen bevinding (bewuste Beheerder-keuze).

Bron = uitsluitend bestaande sporen: `platform.audit_event` (acties per automatisering, zie `_ACTIES`),
`bank_sync_run.resultaat`, `terugkerend_herbereken_run`, `autoboek_instelling.laatste_run_op` en de opt-in-
kolommen. Geen nieuwe tabel, geen migratie: de uitkomst landt in `reconciliatie_run.samenvatting` onder de
sleutel `automatiseringen` (0114 JSONB) en de LET-OPs zijn gewone bevindingen (blok `automatisering`).

Twee lagen, bewust gescheiden:
- `verzamel_feiten()` leest de DB (per administratie in een gescoopte sessie — RLS op audit_event én de
  run-tabellen blijft de waarheid; administratie-loze rijen in de scope-loze sessie);
- `bereken()` + `bevindingen()` zijn PUUR (geen DB) en deterministisch — dáár zitten de tests op.

De categorie "geen eigenaar" blijft zichtbaar als vaste teller (0): sinds blok B (07-09) loopt een automatisering
zonder eigenaar/toewijzing/ontvanger dóór — komt hij tóch voor, dan is dat een regressie die je hier ziet.
Geen AI, geen RLZ-/Odoo-calls."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

BLOK = "automatisering"
VENSTER_UREN = 24
STIL_DAGEN = 7
_VINGERAFDRUK_LENGTE = 16

# --- reden-categorieën (machine-sleutels; labels in REDEN_LABEL) -------------------------------------
GEEN_EIGENAAR = "geen_eigenaar"
VOLUMEREM = "volumerem"
GELDPOORT = "geldpoort"
CREDENTIAL = "credential"
API_KEY = "api_key"
NOODREM = "noodrem"
HARDE_CHECKS = "harde_checks"
MENS_BEOORDEELT = "mens_beoordeelt"
EXTRACTIE_ONVOLLEDIG = "extractie_onvolledig"
GEHEUGEN_ORANJE = "geheugen_oranje"
URENMATCH = "urenmatch"
DUPLICAATSIGNAAL = "duplicaatsignaal"
BOEKFOUT = "boekfout"
HALF_GEBOEKT = "half_geboekt"
TWIJFEL = "twijfel"
FOUT = "fout"
REGEL_OVERGESLAGEN = "regel_overgeslagen"
ZACHT_SIGNAAL = "zacht_signaal"
STIL_7_DAGEN = "stil_7_dagen"
#: Extractie-wachtrij (herstelrun "Basis eerst" 08-09, blok 2): de per-upload-trigger van de Cloud Run-job
#: `rlz-extractie-wachtrij` mislukte → het scheduler-vangnet (elke 10 min) verwerkt het document (LET-OP: de
#: wachttijd is dan tot 10 min en de wortel is meestal IAM `run.invoker`).
VANGNET_SCHEDULER = "vangnet_scheduler"
#: Extractie-wachtrij: document in de wachtrij gezet zonder trigger-spoor — geen job-resource geconfigureerd
#: (lokale dev: in-process thread) of een overgang van vóór het spoor (08-09).
LOKAAL_THREAD = "lokaal_thread"
#: Bank-sync (blok 1 bundel 08-09): Odoo-administratie — bank loopt niet via Reeleezee (zichtbaar, geen LET-OP).
ODOO_ADMINISTRATIE = "odoo_administratie"
#: Bank-sync: geen webservice-login geregistreerd (store noch .env) = niet onboarded — zichtbaar overgeslagen, geen
#: LET-OP (zelfde lijn als sync-alles/F3: de cloud-seed-testadministratie mag niet dagelijks rood staan). Een
#: WEL geregistreerde maar kapotte login (401) valt via de run-fout onder `credential` (harde voorwaarde).
GEEN_CREDENTIAL_GEREGISTREERD = "geen_credential_geregistreerd"
#: Bank-sync: administratie mét RLZ-verbinding maar zonder enige run (klaar óf fout) in het venster — de nachtelijke
#: `sync-alles` heeft 'm niet bereikt (job niet gedraaid/afgebroken): LET-OP, platformbreed (administratie-loos).
GEEN_SYNC_RUN = "geen_sync_run"
#: AI-plausibiliteitstoets (blok B bundel 10-09) overgeslagen omdat de intake-AI (AVG-gate) uit staat resp. de
#: AI-kostengrens bereikt is — beide een menselijke instelling (harde voorwaarde, deeplink Instellingen › Intake-AI).
AVG_GATE = "avg_gate"
KOSTENGRENS = "kostengrens"
#: Blok 4 (10-09 avond): een automatische boeking liep door terwijl de AI-plausibiliteitstoets TECHNISCH uitviel
#: (avg_gate | api_key | kostengrens | ai_fout). Geen poort meer, wél een LET-OP "controleer steekproefsgewijs" op de
#: eigen teller `ai_toets_overgeslagen`; de oorzaak (avg_gate/api_key/kostengrens/ai_fout uit het audit-veld `oorzaak`)
#: is daar de categorie — `ai_fout` heeft alleen een label (categoriseer_reden blijft `fout` geven op vrije tekst).
ZONDER_AI_TOETS = "zonder_ai_toets"
AI_FOUT = "ai_fout"
#: Blok 3.2 vervolgrun 10-09 avond: de platformbrede opt-out `ai_toets_facturen_ingeschakeld` = UIT — categorie van de
#: LET-OP op de teller `ai_toets_uit` ("AI-toets staat platformbreed uit sinds <datum>"); geen uitval, een keuze die
#: zichtbaar blijft. Doel = Instellingen › Boeken (de schakelaar).
TOETS_UIT = "ai_toets_uit"

#: Categorieën die een ONTBREKENDE HARDE VOORWAARDE markeren → LET-OP mét handeling.
#: "geen eigenaar" hoort hier óók bij: sinds blok B (07-09) is een ontbrekende eigenaar/toewijzing géén poort meer —
#: komt de reden tóch voor, dan wacht een automatisering op een menselijke instelling (regressie, zichtbaar mét actie).
#: `vangnet_scheduler` (08-09): ≥ 1 mislukte job-trigger in het etmaal = LET-OP (platformbreed, administratie-loos).
HARDE_VOORWAARDEN = frozenset(
    {
        CREDENTIAL,
        API_KEY,
        GELDPOORT,
        VOLUMEREM,
        NOODREM,
        GEEN_EIGENAAR,
        VANGNET_SCHEDULER,
        GEEN_SYNC_RUN,
        AVG_GATE,
        KOSTENGRENS,
    }
)

#: Bundel 09-09 blok 1 (feedback Peter over de reconciliatiemail). Drie klassen LET-OP op dit blok:
#: - REGRESSIE: "dit mag sinds … niet meer voorkomen" — een BUG-signaal, geen handeling voor het kantoor. De run
#:   schrijft er een audit-event `automatisering_regressie` voor (idempotent per run + vingerafdruk) waarop de
#:   bewaking alarmeert; in mail en UI staat één regel REGRESSIE_TEKST — nooit "meld de regressie" aan de gebruiker.
#: - BEHEER: de handeling ligt bij het beheer (Cloud Run/IAM/jobs/storing), niet bij het kantoor → alleen systeemmail.
#: - de rest (credential, API-key, geldpoort, noodrem, volumerem) = een instelling die het kantoor zelf herstelt →
#:   actiemail.
REGRESSIE_CATEGORIEEN = frozenset({GEEN_EIGENAAR})
#: Blok 1 nametingen-run 10-09 (§F7 route A): jaarlijkse rotatie van de key van het nameting-serviceaccount — beheer-signaal
#: (systeemmail), 30 dagen vóór 12 maanden ná `settings.nameting_sa_aangemaakt_op`.
SA_KEY_ROTATIE = "nameting_sa_key_rotatie"
SA_KEY_ROTATIE_MAANDEN = 12
SA_KEY_ROTATIE_WAARSCHUWING_DAGEN = 30
#: Ochtendrun 11-09 blok 2.1: de bewakingsprobe `deploy_drift` (app/bewaking/deploy_drift.py) heeft een OPEN
#: storing — Cloud Run-jobs draaien op een ander beeld dan de service. Beheer-signaal (systeemmail), tekst
#: "systeemfout — automatisch gemeld": de bewaking alarmeert zelf, de reconciliatie maakt het alleen zichtbaar op
#: /reconciliatie.
DEPLOY_DRIFT = "deploy_drift"
BEHEER_CATEGORIEEN = frozenset({VANGNET_SCHEDULER, GEEN_SYNC_RUN, STIL_7_DAGEN, SA_KEY_ROTATIE, DEPLOY_DRIFT})
REGRESSIE_TEKST = "systeemfout — automatisch gemeld"

REDEN_LABEL: dict[str, str] = {
    GEEN_EIGENAAR: "geen eigenaar/toewijzing",
    VOLUMEREM: "volumerem bereikt",
    GELDPOORT: "boeken staat uit (kill-switch/administratie)",
    CREDENTIAL: "geen werkende credential",
    API_KEY: "geen API-key",
    NOODREM: "noodrem staat uit",
    HARDE_CHECKS: "harde checks blokkeren",
    MENS_BEOORDEELT: "mens beoordeelt",
    EXTRACTIE_ONVOLLEDIG: "extractie onvolledig",
    GEHEUGEN_ORANJE: "geheugen niet bevestigd (oranje)",
    URENMATCH: "urenmatch niet groen",
    DUPLICAATSIGNAAL: "duplicaatsignaal op het document",
    BOEKFOUT: "boekfout in RLZ/Odoo",
    HALF_GEBOEKT: "half geboekt",
    TWIJFEL: "twijfel (niet eenduidig)",
    FOUT: "fout",
    REGEL_OVERGESLAGEN: "regel overgeslagen (transport/dienst/geen aantal)",
    ZACHT_SIGNAAL: "zacht signaal — mens beoordeelt",
    STIL_7_DAGEN: "zeven dagen stil",
    VANGNET_SCHEDULER: "job-trigger mislukt — scheduler-vangnet (≤ 10 min)",
    LOKAAL_THREAD: "geen job-trigger (lokaal/thread)",
    ODOO_ADMINISTRATIE: "Odoo-administratie (bank niet via Reeleezee)",
    GEEN_CREDENTIAL_GEREGISTREERD: "geen webservice-login geregistreerd (niet onboarded)",
    GEEN_SYNC_RUN: "geen bank-sync-run in het venster (sync-alles niet gedraaid?)",
    AVG_GATE: "AI staat uit (AVG-gate intake-AI)",
    KOSTENGRENS: "AI-kostengrens bereikt",
    ZONDER_AI_TOETS: "geboekt zonder AI-toets — controleer steekproefsgewijs",
    AI_FOUT: "AI-fout/timeout",
    TOETS_UIT: "AI-toets facturen staat platformbreed uit (opt-out)",
}

# --- de automatiseringen ------------------------------------------------------------------------------
DUPLICAAT_AFVOER = "duplicaat_afvoer"
CREDITEUREN = "crediteuren_afhandeling"
AUTOBOEK_INKOOP = "autoboeken_inkoop"
AUTOBOEK_KANDIDATEN = "autoboek_kandidaten"
#: Blok A bundel 10-09: de administratie-schakelaar "Autoboeken (leren en boeken)" — per administratie mét schakelaar
#: leveranciers lerend/actief/uitgezonderd + automatisch geboekt vandaag (detail-veld), activaties/resets in het etmaal.
AUTOBOEK_LEREN = "autoboek_leren"
#: Verzoek blok B (10-09): de AI-plausibiliteitstoets als eigen teller — bron audit `ai_plausibiliteitstoets` (bank én
#: factuur); stand = AVG-gate intake-AI; gedaan = plausibel + twijfel; overgeslagen per oorzaak. Geen eigen LET-OP (die
#: hangt al op het pad dat overgeslagen werd).
AI_PLAUSIBILITEIT = "ai_plausibiliteit"
#: Blok 4 (10-09 avond, besluit Peter "uitval = doorlopen, zichtbaar"): automatische boekingen (bank én factuur) die
#: doorliepen terwijl de AI-toets technisch uitviel — bron audit `automatisch_geboekt_zonder_ai_toets`; per dag per
#: oorzaak; > 0 in het etmaal = LET-OP "N automatische boekingen zonder AI-toets (oorzaak …) — controleer
#: steekproefsgewijs" mét deeplink naar de bankrekening/documentenlijst. Stand = aan zodra er in de week iets telde.
AI_TOETS_OVERGESLAGEN = "ai_toets_overgeslagen"
#: Blok 3.2 vervolgrun 10-09 avond (besluit Peter): de platformbrede opt-out van de factuur-AI-toets is niet meer stil —
#: stand "aan" = de opt-out is actief (schakelaar UIT sinds `boeken_instelling.gewijzigd_op`), gedaan = automatische
#: factuurboekingen die met de toets uit doorliepen (audit `automatisch_geboekt` veld `ai_toets_uit`), LET-OP
#: "AI-toets staat platformbreed uit sinds <datum>" mét deeplink naar de schakelaar. Schakelaar AAN = teller uit.
AI_TOETS_UIT = "ai_toets_uit"
#: Verzoek blok C (10-09): eerste-sync-run (onboarding) met een RLZ-weigering 401/403 = harde voorwaarde `credential`
#: mét deeplink naar de administratie; bron `administratie_sync_run` (status fout, onderdelen.*.http_status).
EERSTE_SYNC = "eerste_sync"
AUTOBOEK_OMZET = "autoboeken_omzet"
AUTOBOEK_VERKOOP = "autoboeken_verkoop"
BANK = "bank_autoboeken"
BANK_SYNC = "bank_sync"
NABUNDEL = "nabundel"
TERUGKEREND = "terugkerend"
MINI_VOORRAAD = "mini_voorraad"
EXTRACTIE_WACHTRIJ = "extractie_wachtrij"

#: Vaste volgorde in mail en scherm (geldpaden eerst).
VOLGORDE: tuple[str, ...] = (
    AUTOBOEK_INKOOP,
    AUTOBOEK_OMZET,
    AUTOBOEK_VERKOOP,
    BANK_SYNC,
    BANK,
    AI_PLAUSIBILITEIT,
    AI_TOETS_OVERGESLAGEN,
    AI_TOETS_UIT,
    EERSTE_SYNC,
    DUPLICAAT_AFVOER,
    CREDITEUREN,
    AUTOBOEK_KANDIDATEN,
    AUTOBOEK_LEREN,
    TERUGKEREND,
    NABUNDEL,
    MINI_VOORRAAD,
    EXTRACTIE_WACHTRIJ,
)

LABEL: dict[str, str] = {
    EXTRACTIE_WACHTRIJ: "Extractie-wachtrij (job-trigger)",
    DUPLICAAT_AFVOER: "Duplicaat-afvoer",
    CREDITEUREN: "Crediteuren-dubbelen (auto)",
    AUTOBOEK_INKOOP: "Autoboeken inkoop",
    AUTOBOEK_KANDIDATEN: "Autoboek-kandidaten (nominatie)",
    AUTOBOEK_LEREN: "Autoboeken per administratie (leren en boeken)",
    AUTOBOEK_OMZET: "Autoboeken omzet",
    AUTOBOEK_VERKOOP: "Autoboeken verkoop",
    BANK: "Bank-autoboeken/afletteren",
    BANK_SYNC: "Bank-sync (dagelijks, alle administraties)",
    AI_PLAUSIBILITEIT: "AI-plausibiliteitstoets (poort vóór autoboeken)",
    AI_TOETS_OVERGESLAGEN: "Automatisch geboekt zonder AI-toets (vangnet)",
    AI_TOETS_UIT: "AI-toets facturen uit (platform-opt-out)",
    EERSTE_SYNC: "Eerste sync (onboarding)",
    NABUNDEL: "Nabundel (UBL+PDF, dubbelen)",
    TERUGKEREND: "Terugkerende facturen (herberekening)",
    MINI_VOORRAAD: "Mini-voorraad instroom",
}

#: Waar de mens de harde voorwaarde herstelt (deeplink); per-administratie-varianten vullen `{aid}`.
DOEL_PAD: dict[str, str] = {
    CREDENTIAL: "/instellingen/administraties/{aid}",
    GEEN_EIGENAAR: "/instellingen/administraties/{aid}",
    API_KEY: "/instellingen/intake-ai",
    GELDPOORT: "/instellingen/boeken",
    NOODREM: "/instellingen/boeken",
    VOLUMEREM: "/instellingen/autoboeken",
    AVG_GATE: "/instellingen/intake-ai",
    KOSTENGRENS: "/instellingen/intake-ai",
    # Geen instelling in de app: de wortel zit in Cloud Run/IAM; de rij op Inzicht › Reconciliatie ís de plek.
    VANGNET_SCHEDULER: "/reconciliatie",
    GEEN_SYNC_RUN: "/reconciliatie",
    TOETS_UIT: "/instellingen/boeken",
}

#: Vaste categorieën die per automatisering ALTIJD zichtbaar zijn (ook als 0) — kernprincipe 7-cross-check.
VASTE_CATEGORIEEN: dict[str, tuple[str, ...]] = {
    AUTOBOEK_INKOOP: (GEEN_EIGENAAR, HARDE_CHECKS),
    AUTOBOEK_OMZET: (GEEN_EIGENAAR, HARDE_CHECKS),
    AUTOBOEK_VERKOOP: (GEEN_EIGENAAR, HARDE_CHECKS),
    AUTOBOEK_LEREN: (HARDE_CHECKS, TWIJFEL),
    DUPLICAAT_AFVOER: (VOLUMEREM,),
    CREDITEUREN: (TWIJFEL,),
    BANK: (VOLUMEREM,),
    BANK_SYNC: (FOUT,),
    TERUGKEREND: (FOUT,),
}

#: Alle audit-acties die deze motor leest — één query per administratie.
_ACTIES: tuple[str, ...] = (
    "duplicaat_afgevoerd",
    "duplicaat_afvoer_geweigerd",
    "duplicaat_module_gesignaleerd",
    "crediteur_dubbel_auto_run",
    "automatisch_geboekt",
    "autoboeken_geweigerd",
    "autoboeken_half_geboekt",
    "autoboek_leverancier_geactiveerd",
    "autoboek_leverancier_gereset",
    "ai_plausibiliteitstoets",
    "automatisch_geboekt_zonder_ai_toets",
    "document_nagebundeld",
    "document_dubbel_samengevouwen",
    "mini_voorraad_instroom",
    "extractie_wachtrij_trigger",
)


# --- feiten (ruwe invoer, DB-vrij te construeren) --------------------------------------------------------


@dataclass(frozen=True)
class AuditFeit:
    actie: str
    tijdstip: datetime
    administratie_id: uuid.UUID | None
    nieuwe_waarde: dict | None = None


@dataclass(frozen=True)
class BankRunFeit:
    administratie_id: uuid.UUID
    beeindigd_op: datetime
    resultaat: dict | None


@dataclass(frozen=True)
class BankSyncRunFeit:
    """Blok 1 (08-09): élke afgeronde `bank_sync_run` (klaar óf fout, on-demand óf sync_alles) — de basis van de
    teller `bank_sync`: is er per administratie per etmaal ten minste één geslaagde verversing?"""

    administratie_id: uuid.UUID
    beeindigd_op: datetime
    status: str  # klaar | fout
    fout_reden: str | None = None
    bron: str | None = None
    # Verzoek blok B (10-09): historie-cache-vulling — niet-lege `resultaat["historie_fouten"]` telt als `fout` op
    # bank_sync.
    historie_fouten: int = 0


@dataclass(frozen=True)
class EersteSyncFeit:
    """Verzoek blok C (10-09): één afgeronde eerste-sync-run (onboarding) — `geweigerd` = ≥ 1 onderdeel met
    HTTP 401/403."""

    administratie_id: uuid.UUID
    tijdstip: datetime
    status: str  # klaar | fout
    geweigerd: bool = False
    fout_reden: str | None = None


@dataclass(frozen=True)
class TerugkerendRunFeit:
    klaar_op: datetime
    aantal_administraties: int
    aantal_verwerkt: int
    aantal_fouten: int


@dataclass
class Feiten:
    """Alles wat `bereken()` nodig heeft. `administraties` = actieve administraties (id → naam)."""

    administraties: dict[uuid.UUID, str] = field(default_factory=dict)
    audit: list[AuditFeit] = field(default_factory=list)
    bank_runs: list[BankRunFeit] = field(default_factory=list)
    # Bank-sync (blok 1, 08-09): alle afgeronde runs (klaar/fout), de Odoo-administraties en de administraties MÉT
    # geregistreerde RLZ-login (positieve set: wie er niet in staat is "niet onboarded", nooit een LET-OP).
    bank_sync_runs: list[BankSyncRunFeit] = field(default_factory=list)
    bank_odoo: set[uuid.UUID] = field(default_factory=set)
    bank_rlz_verbinding: set[uuid.UUID] = field(default_factory=set)
    terugkerend_runs: list[TerugkerendRunFeit] = field(default_factory=list)
    # Verzoek blok C (10-09): eerste-sync-runs (klaar/fout) van de afgelopen week.
    eerste_sync_runs: list[EersteSyncFeit] = field(default_factory=list)
    # Verzoek blok B (10-09): AVG-gate intake-AI (de stand van de AI-plausibiliteitstoets).
    intake_ai_aan: bool = False
    # Blok 3.2 vervolgrun 10-09 avond: platformbrede schakelaar factuur-AI-toets (boeken_instelling) + moment van de
    # laatste wijziging (= "uit sinds" zolang de schakelaar uit staat). Geen rij = AAN (migratie-default).
    ai_toets_facturen_aan: bool = True
    ai_toets_facturen_gewijzigd_op: datetime | None = None
    autoboek_kandidaten_laatste_run: datetime | None = None
    duplicaat_noodrem_aan: bool = True
    # opt-ins
    leverancier_optins: dict[uuid.UUID, int] = field(default_factory=dict)  # administratie → n leveranciers aan
    veldwerker_optins: dict[uuid.UUID, int] = field(default_factory=dict)
    omzet_aan: set[uuid.UUID] = field(default_factory=set)
    # Blok A bundel 10-09: administraties mét de schakelaar "Autoboeken (leren en boeken)" aan (Kempen-regel al
    # toegepast) en per zo'n administratie de leveranciers-stand {lerend, actief, uitgezonderd}.
    autoboek_leren_aan: set[uuid.UUID] = field(default_factory=set)
    autoboek_leren_detail: dict[uuid.UUID, dict[str, int]] = field(default_factory=dict)
    verkoop_aan: set[uuid.UUID] = field(default_factory=set)  # is_vastgoed
    bank_aan: set[uuid.UUID] = field(default_factory=set)
    mini_voorraad_aan: set[uuid.UUID] = field(default_factory=set)
    # Extractie-wachtrij (08-09): tijdstippen van élke overgang → `extractie_wachtrij` die géén herstel-overgang
    # is (upload/intake/herextractie), per administratie; de "verwacht"-kant van de trigger-teller.
    extractie_wachtrij_overgangen: list[tuple[uuid.UUID, datetime]] = field(default_factory=list)
    # Staat er een Cloud Run-job-resource op de service (productie) of draait de wachtrij lokaal (thread)?
    extractie_job_resource: str | None = None


# --- uitkomst ---------------------------------------------------------------------------------------------


@dataclass
class Venster:
    verwacht: int = 0
    gedaan: int = 0
    overgeslagen: dict[str, int] = field(default_factory=dict)

    @property
    def overgeslagen_totaal(self) -> int:
        return sum(self.overgeslagen.values())

    def tel_overgeslagen(self, categorie: str, n: int = 1) -> None:
        self.overgeslagen[categorie] = self.overgeslagen.get(categorie, 0) + n
        self.verwacht += n

    def tel_gedaan(self, n: int = 1) -> None:
        self.gedaan += n
        self.verwacht += n


@dataclass(frozen=True)
class HardeVoorwaarde:
    """Eén groep overgeslagen stukken wegens een ontbrekende harde voorwaarde (laatste 24 u). Blok 4 (10-09 avond,
    additief): `soort` (bank_* | factuur_autoboeking) en `doel_pad` voor de vangnet-teller `ai_toets_overgeslagen` —
    dáár is de categorie de oorzaak van de uitval en het doel de plek waar de mens de boekingen steekproefsgewijs
    controleert (bankrekening / documentenlijst), niet een instelling."""

    categorie: str
    aantal: int
    administratie_id: uuid.UUID | None
    voorbeeld: str | None = None
    soort: str | None = None
    doel_pad: str | None = None


@dataclass
class Teller:
    sleutel: str
    label: str
    stand: str  # aan | uit | deels | altijd | op_aanvraag
    stand_detail: str | None
    bron: str
    dag: Venster = field(default_factory=Venster)
    week: Venster = field(default_factory=Venster)
    harde_voorwaarden: list[HardeVoorwaarde] = field(default_factory=list)
    stil: bool = False  # 7 dagen: aan, kandidaten, 0 gedaan, 0 overgeslagen
    # Additief (blok A bundel 10-09): automatisering-specifieke standen (autoboek_leren: lerend/actief/uitgezonderd,
    # geactiveerd_24u, gereset_24u, per_administratie[]). None voor tellers zonder detail — FE sleutel-agnostisch.
    detail: dict[str, Any] | None = None

    @property
    def is_uit(self) -> bool:
        return self.stand == "uit"


def _json(teller: Teller) -> dict:
    d = asdict(teller)
    for hv in d["harde_voorwaarden"]:
        hv["administratie_id"] = str(hv["administratie_id"]) if hv["administratie_id"] else None
    return d


def als_samenvatting(tellers: Sequence[Teller], *, nu: datetime) -> dict:
    """De JSON-vorm voor `reconciliatie_run.samenvatting["automatiseringen"]` (spiegel: reconciliatieApi.ts)."""
    return {
        "venster_uren": VENSTER_UREN,
        "stil_dagen": STIL_DAGEN,
        "berekend_op": nu.isoformat(),
        "tellers": [_json(t) for t in tellers],
    }


# --- reden-categorisatie (deterministisch op tekst) ------------------------------------------------------


def categoriseer_reden(reden: str | None) -> str:
    """Vertaal een vrije weiger-/overslaan-reden uit het audit-spoor naar één categorie-sleutel. Bewust op
    tekstfragmenten uit de bestaande code (autoboeken.py, omzet/verkoop/autoboeken.py, duplicaat_afvoer.py):
    een nieuwe reden valt terug op 'mens_beoordeelt' (nooit stil weg)."""
    t = (reden or "").lower()
    if not t:
        return MENS_BEOORDEELT
    # AI-plausibiliteitstoets (blok B bundel 10-09): "overgeslagen: api_key/avg_gate/kostengrens/ai_fout — …".
    if "avg_gate" in t or "avg-gate" in t or "ai staat platformbreed uit" in t:
        return AVG_GATE
    if "kostengrens" in t or "maandlimiet" in t:
        return KOSTENGRENS
    if "api_key" in t:
        return API_KEY
    if "eigenaar" in t or ("toegewezen" in t and "geen" in t):
        return GEEN_EIGENAAR
    if "volumerem" in t or "dagelijkse limiet" in t:
        return VOLUMEREM
    if "kill switch" in t or "kill-switch" in t or "boeken staat uit" in t:
        return GELDPOORT
    if "credential" in t or "webservice-login" in t:
        return CREDENTIAL
    if "api-key" in t or "api key" in t or "apikey" in t:
        return API_KEY
    if "noodrem" in t:
        return NOODREM
    if "half geboekt" in t:
        return HALF_GEBOEKT
    if "geen harde duplicaat-match" in t:
        return MENS_BEOORDEELT  # duplicaat_afvoer: de groep viel uiteen vóór de afvoer — de mens kijkt
    if "boekfout" in t or "boeken_mislukt" in t:
        return BOEKFOUT
    if "harde checks" in t:
        return HARDE_CHECKS
    if "duplicaat" in t:
        return DUPLICAATSIGNAAL
    if "urenmatch" in t or "weekstaten" in t:
        return URENMATCH
    if "geheugen" in t:
        return GEHEUGEN_ORANJE
    if "extractie" in t or "ubl leverde" in t or "geen boekbare regels" in t or "nettobedrag" in t:
        return EXTRACTIE_ONVOLLEDIG
    if "twijfel" in t:
        return TWIJFEL
    if "fout" in t:
        return FOUT
    return MENS_BEOORDEELT


# --- berekening (puur) -------------------------------------------------------------------------------------


def _nw(f: AuditFeit) -> dict:
    return f.nieuwe_waarde or {}


def _stand_per_administratie(aan: set[uuid.UUID], alle: dict[uuid.UUID, str]) -> tuple[str, str | None]:
    n, m = len(aan & set(alle)), len(alle)
    if n == 0:
        return "uit", f"0 van {m} administraties"
    if n == m:
        return "aan", f"alle {m} administraties"
    return "deels", f"{n} van {m} administraties"


def bereken(feiten: Feiten, *, nu: datetime) -> list[Teller]:
    """Per automatisering de tellers over het etmaal én de week, plus harde-voorwaarde-groepen en de
    stil-vlag. Puur en deterministisch: dezelfde feiten → dezelfde uitkomst."""
    dag_vanaf = nu - timedelta(hours=VENSTER_UREN)
    week_vanaf = nu - timedelta(days=STIL_DAGEN)
    tellers: dict[str, Teller] = {}

    def maak(sleutel: str, stand: str, detail: str | None, bron: str) -> Teller:
        t = Teller(sleutel=sleutel, label=LABEL[sleutel], stand=stand, stand_detail=detail, bron=bron)
        for cat in VASTE_CATEGORIEEN.get(sleutel, ()):
            t.dag.overgeslagen.setdefault(cat, 0)
            t.week.overgeslagen.setdefault(cat, 0)
        tellers[sleutel] = t
        return t

    def vensters(t: Teller, tijdstip: datetime):
        """Welke vensters een feit raakt (week omvat de dag)."""
        if tijdstip < week_vanaf:
            return ()
        return (t.dag, t.week) if tijdstip >= dag_vanaf else (t.week,)

    hard: dict[tuple[str, str, uuid.UUID | None], list[str]] = {}

    def tel_over(
        t: Teller,
        tijdstip: datetime,
        categorie: str,
        aid: uuid.UUID | None,
        voorbeeld: str | None,
        *,
        hard_registreren: bool = True,
    ) -> None:
        vs = vensters(t, tijdstip)
        for v in vs:
            v.tel_overgeslagen(categorie)
        if hard_registreren and categorie in HARDE_VOORWAARDEN and tijdstip >= dag_vanaf:
            hard.setdefault((t.sleutel, categorie, aid), []).append(voorbeeld or "")

    # --- opt-in-standen
    adm = feiten.administraties
    lev_aan = {a for a, n in feiten.leverancier_optins.items() if n} | {
        a for a, n in feiten.veldwerker_optins.items() if n
    }
    n_lev = sum(feiten.leverancier_optins.values()) + sum(feiten.veldwerker_optins.values())
    inkoop = maak(
        AUTOBOEK_INKOOP,
        "uit" if n_lev == 0 else ("aan" if lev_aan >= set(adm) else "deels"),
        f"{n_lev} leverancier(s)/koppeling(en) aan in {len(lev_aan & set(adm))} van {len(adm)} administraties",
        "audit automatisch_geboekt / autoboeken_geweigerd (bron leverancier_opt_in, veldwerker_opt_in)",
    )
    omzet = maak(AUTOBOEK_OMZET, *_stand_per_administratie(feiten.omzet_aan, adm), "audit (bron omzet_opt_in)")
    verkoop = maak(
        AUTOBOEK_VERKOOP,
        *_stand_per_administratie(feiten.verkoop_aan, adm),
        "audit (bron verkoop_opt_in; poort is_vastgoed)",
    )
    bank_sync = maak(
        BANK_SYNC,
        "altijd",
        f"dagelijks in sync-alles (07:00) + bij openen bankscherm — {len(adm)} actieve administraties",
        "bank_sync_run (status klaar/fout) + administratie-kenmerken (Odoo / credential)",
    )
    bank = maak(BANK, *_stand_per_administratie(feiten.bank_aan, adm), "bank_sync_run.resultaat")
    ai_toets = maak(
        AI_PLAUSIBILITEIT,
        "aan" if feiten.intake_ai_aan else "uit",
        "AVG-gate intake-AI " + ("aan" if feiten.intake_ai_aan else "UIT — élke toets wordt overgeslagen (avg_gate)"),
        "audit ai_plausibiliteitstoets (bank én factuur; gedaan = plausibel + twijfel)",
    )
    # Blok 4 (10-09 avond): stand volgt uit de feiten (aan zodra er in de week een boeking zonder toets was) — een
    # vangnet-rij zonder inhoud verdwijnt zo achter "uit-regels niet tonen", een rij mét inhoud is altijd zichtbaar.
    zonder_toets = maak(
        AI_TOETS_OVERGESLAGEN,
        "uit",
        "geen automatische boeking zonder AI-toets in de laatste 7 dagen",
        "audit automatisch_geboekt_zonder_ai_toets (bank én factuur; oorzaak avg_gate/api_key/kostengrens/ai_fout)",
    )
    zonder_groepen: dict[tuple[uuid.UUID | None, str, str], list[str]] = {}
    zonder_detail: dict[str, Any] = {"bank_24u": 0, "factuur_24u": 0, "per_oorzaak_24u": {}}
    # Blok 3.2 (10-09 avond): opt-out zichtbaar — stand "aan" betekent hier "de opt-out is actief" (schakelaar UIT).
    uit_sinds = feiten.ai_toets_facturen_gewijzigd_op
    uit_sinds_tekst = f"sinds {uit_sinds:%d-%m-%Y}" if uit_sinds is not None else "sinds onbekend moment"
    toets_uit = maak(
        AI_TOETS_UIT,
        "uit" if feiten.ai_toets_facturen_aan else "aan",
        "AI-toets facturen staat aan"
        if feiten.ai_toets_facturen_aan
        else f"AI-toets facturen staat platformbreed UIT {uit_sinds_tekst} — élke automatische factuurboeking "
        "draagt chip 'AI-toets uit (platform)'",
        "boeken_instelling.ai_toets_facturen_ingeschakeld + audit automatisch_geboekt (veld ai_toets_uit)",
    )
    eerste_sync = maak(
        EERSTE_SYNC,
        "op_aanvraag",
        "onboarding-wizard / herstart per administratie",
        "administratie_sync_run (status klaar/fout; onderdelen.*.http_status 401/403 = credential)",
    )
    dup = maak(
        DUPLICAAT_AFVOER,
        "aan" if feiten.duplicaat_noodrem_aan else "uit",
        "platformbrede noodrem " + ("aan" if feiten.duplicaat_noodrem_aan else "UIT"),
        "audit duplicaat_afgevoerd / duplicaat_afvoer_geweigerd / duplicaat_module_gesignaleerd",
    )
    cred = maak(CREDITEUREN, "altijd", "alle actieve administraties (sync-alles)", "audit crediteur_dubbel_auto_run")
    kand = maak(
        AUTOBOEK_KANDIDATEN,
        "altijd" if feiten.autoboek_kandidaten_laatste_run is not None else "uit",
        "dagelijks in sync-alles" if feiten.autoboek_kandidaten_laatste_run is not None else "nog nooit gedraaid",
        "autoboek_instelling.laatste_run_op (1 run/dag verwacht)",
    )
    # Blok A bundel 10-09: de schakelaar per administratie; "gedaan" = automatisch geboekt (bron leverancier_opt_in) in
    # een administratie mét schakelaar, "overgeslagen" = de weigeringen dáár (zonder dubbele LET-OP: de
    # harde-voorwaarde-
    # bevinding staat al op `autoboeken_inkoop`). Detail = leveranciers lerend/actief/uitgezonderd + activaties/resets.
    leren_detail: dict[str, Any] = {
        "lerend": sum(
            d.get("lerend", 0) for a, d in feiten.autoboek_leren_detail.items() if a in feiten.autoboek_leren_aan
        ),
        "actief": sum(
            d.get("actief", 0) for a, d in feiten.autoboek_leren_detail.items() if a in feiten.autoboek_leren_aan
        ),
        "uitgezonderd": sum(
            d.get("uitgezonderd", 0) for a, d in feiten.autoboek_leren_detail.items() if a in feiten.autoboek_leren_aan
        ),
        "geactiveerd_24u": 0,
        "gereset_24u": 0,
        "per_administratie": [
            {
                "administratie_id": str(a),
                "naam": adm.get(a),
                **{
                    k: int(feiten.autoboek_leren_detail.get(a, {}).get(k, 0))
                    for k in ("lerend", "actief", "uitgezonderd")
                },
                "automatisch_geboekt_24u": 0,
            }
            for a in sorted(feiten.autoboek_leren_aan & set(adm), key=lambda x: adm.get(x) or "")
        ],
    }
    leren = maak(
        AUTOBOEK_LEREN,
        *_stand_per_administratie(feiten.autoboek_leren_aan, adm),
        "administratie.autoboeken_leren_ingeschakeld + leverancier_voorkeur/autoboek_kandidaat_stand + audit "
        "automatisch_geboekt / autoboek_leverancier_geactiveerd / autoboek_leverancier_gereset",
    )
    leren.detail = leren_detail
    per_adm_leren = {r["administratie_id"]: r for r in leren_detail["per_administratie"]}
    terug = maak(TERUGKEREND, "altijd", "alle actieve administraties (sync-alles)", "terugkerend_herbereken_run")
    nab = maak(
        NABUNDEL, "op_aanvraag", "intake + nazorg-CLI", "audit document_nagebundeld / document_dubbel_samengevouwen"
    )
    mini = maak(MINI_VOORRAAD, *_stand_per_administratie(feiten.mini_voorraad_aan, adm), "audit mini_voorraad_instroom")
    job = feiten.extractie_job_resource
    extractie = maak(
        EXTRACTIE_WACHTRIJ,
        "altijd",
        f"Cloud Run-job {job.rsplit('/', 1)[-1]} per upload + scheduler-vangnet 10 min"
        if job
        else "geen job-resource — lokaal/thread",
        "audit extractie_wachtrij_trigger + tijdlijn-overgangen naar extractie_wachtrij",
    )

    # --- audit-feiten
    for f in feiten.audit:
        if f.tijdstip < week_vanaf:
            continue
        nw = _nw(f)
        bron = str(nw.get("bron") or "")
        in_leren = f.administratie_id in feiten.autoboek_leren_aan
        if f.actie == "automatisch_geboekt":
            t = omzet if bron == "omzet_opt_in" else verkoop if bron == "verkoop_opt_in" else inkoop
            for v in vensters(t, f.tijdstip):
                v.tel_gedaan()
            if nw.get("ai_toets_uit") is True:
                # Blok 3.2 (10-09 avond): factuurboeking die doorliep met de toets bewust uit — telt op de opt-out-rij.
                for v in vensters(toets_uit, f.tijdstip):
                    v.tel_gedaan()
            if t is inkoop and bron == "leverancier_opt_in" and in_leren:
                for v in vensters(leren, f.tijdstip):
                    v.tel_gedaan()
                if f.tijdstip >= dag_vanaf and str(f.administratie_id) in per_adm_leren:
                    per_adm_leren[str(f.administratie_id)]["automatisch_geboekt_24u"] += 1
        elif f.actie in ("autoboeken_geweigerd", "autoboeken_half_geboekt"):
            t = omzet if bron == "omzet_opt_in" else verkoop if bron == "verkoop_opt_in" else inkoop
            cat = HALF_GEBOEKT if f.actie == "autoboeken_half_geboekt" else categoriseer_reden(nw.get("reden"))
            tel_over(t, f.tijdstip, cat, f.administratie_id, str(nw.get("reden") or ""))
            if t is inkoop and in_leren and bron != "veldwerker_opt_in":
                tel_over(leren, f.tijdstip, cat, f.administratie_id, str(nw.get("reden") or ""), hard_registreren=False)
        elif f.actie == "ai_plausibiliteitstoets":
            uitkomst = str(nw.get("uitkomst") or "")
            if uitkomst in ("plausibel", "twijfel"):
                for v in vensters(ai_toets, f.tijdstip):
                    v.tel_gedaan()
            elif uitkomst == "overgeslagen":
                # De LET-OP hangt al op het pad dat overgeslagen werd (bank/inkoop) — hier alleen de teller.
                tel_over(
                    ai_toets,
                    f.tijdstip,
                    categoriseer_reden(nw.get("reden")),
                    f.administratie_id,
                    str(nw.get("reden") or ""),
                    hard_registreren=False,
                )
        elif f.actie == "automatisch_geboekt_zonder_ai_toets":
            # Blok 4 (10-09 avond): één rij per boeking die doorliep zonder AI-oordeel. gedaan = de boeking (die is
            # er), overgeslagen[oorzaak] = de toets die uitviel; verwacht = aantal boekingen (één toets per boeking).
            oorzaak = str(nw.get("oorzaak") or "") or categoriseer_reden(nw.get("reden"))
            soort = str(nw.get("soort") or "")
            for v in vensters(zonder_toets, f.tijdstip):
                v.gedaan += 1
                v.tel_overgeslagen(oorzaak)
            if f.tijdstip >= dag_vanaf:
                zonder_groepen.setdefault((f.administratie_id, soort, oorzaak), []).append(str(nw.get("reden") or ""))
                zonder_detail["factuur_24u" if soort == "factuur_autoboeking" else "bank_24u"] += 1
                zonder_detail["per_oorzaak_24u"][oorzaak] = zonder_detail["per_oorzaak_24u"].get(oorzaak, 0) + 1
        elif f.actie == "autoboek_leverancier_geactiveerd":
            if f.tijdstip >= dag_vanaf:
                leren_detail["geactiveerd_24u"] += 1
        elif f.actie == "autoboek_leverancier_gereset":
            if f.tijdstip >= dag_vanaf:
                leren_detail["gereset_24u"] += 1
        elif f.actie == "duplicaat_afgevoerd":
            if nw.get("automatisch"):
                for v in vensters(dup, f.tijdstip):
                    v.tel_gedaan()
        elif f.actie == "duplicaat_afvoer_geweigerd":
            tel_over(
                dup, f.tijdstip, categoriseer_reden(nw.get("reden")), f.administratie_id, str(nw.get("reden") or "")
            )
        elif f.actie == "duplicaat_module_gesignaleerd":
            # Zacht signaal: het document blijft staan mét oranje chip — een kandidaat die de mens beoordeelt.
            # Staat de noodrem UIT, dan is dit precies de kandidaat die wacht op een menselijke instelling.
            cat = ZACHT_SIGNAAL if feiten.duplicaat_noodrem_aan else NOODREM
            tel_over(dup, f.tijdstip, cat, f.administratie_id, str(nw.get("categorie") or ""))
        elif f.actie == "crediteur_dubbel_auto_run":
            for v in vensters(cred, f.tijdstip):
                v.tel_gedaan(int(nw.get("afgehandeld") or 0))
                v.tel_overgeslagen(TWIJFEL, int(nw.get("twijfel") or 0))
                if int(nw.get("fouten") or 0):
                    v.tel_overgeslagen(FOUT, int(nw.get("fouten") or 0))
        elif f.actie in ("document_nagebundeld", "document_dubbel_samengevouwen"):
            for v in vensters(nab, f.tijdstip):
                v.tel_gedaan()
        elif f.actie == "mini_voorraad_instroom":
            for v in vensters(mini, f.tijdstip):
                v.tel_gedaan()
                regels_over = nw.get("overgeslagen") or []
                if regels_over:
                    v.overgeslagen[REGEL_OVERGESLAGEN] = v.overgeslagen.get(REGEL_OVERGESLAGEN, 0) + len(regels_over)
        elif f.actie == "extractie_wachtrij_trigger":
            if nw.get("uitkomst") == "geslaagd":
                for v in vensters(extractie, f.tijdstip):
                    v.tel_gedaan()
            else:
                # Platformbrede voorwaarde (IAM/job) → administratie-loos in de LET-OP; de administratie staat
                # in het voorbeeld zodat de rij wél naar het document leidt.
                tel_over(
                    extractie,
                    f.tijdstip,
                    VANGNET_SCHEDULER,
                    None,
                    f"{nw.get('fout') or 'trigger mislukt'} (administratie {f.administratie_id})",
                )

    # --- extractie-wachtrij: overgangen zonder trigger-spoor = lokaal/thread (of van vóór het spoor)
    for venster_obj, vanaf in ((extractie.dag, dag_vanaf), (extractie.week, week_vanaf)):
        n_over = sum(1 for _aid, t in feiten.extractie_wachtrij_overgangen if t >= vanaf)
        rest = n_over - venster_obj.gedaan - venster_obj.overgeslagen_totaal
        if rest > 0:
            venster_obj.tel_overgeslagen(LOKAAL_THREAD, rest)

    # --- bank (run-tabel)
    for r in feiten.bank_runs:
        if r.beeindigd_op < week_vanaf:
            continue
        res = r.resultaat or {}
        n_gedaan = int(res.get("automatisch_afgeletterd") or 0) + int(res.get("automatisch_geboekt") or 0)
        for v in vensters(bank, r.beeindigd_op):
            v.tel_gedaan(n_gedaan)
        for fout in res.get("fouten") or []:
            tel_over(bank, r.beeindigd_op, categoriseer_reden(str(fout)), r.administratie_id, str(fout))
        # Verzoek blok B (10-09): kandidaten die de AI-plausibiliteitstoets NIET boekte ("twijfel: …" /
        # "overgeslagen: avg_gate|api_key|kostengrens|ai_fout — …") — verwacht = gedaan + overgeslagen.
        for regel in res.get("overgeslagen") or []:
            tel_over(bank, r.beeindigd_op, categoriseer_reden(str(regel)), r.administratie_id, str(regel))

    # --- bank-sync (blok 1, 08-09): per administratie per venster precies één uitkomst
    #     (verwacht = alle actieve administraties; gedaan = ≥ 1 geslaagde run in het venster)
    for aid in adm:
        if aid in feiten.bank_odoo:
            for v in (bank_sync.dag, bank_sync.week):
                v.tel_overgeslagen(ODOO_ADMINISTRATIE)
            continue
        if aid not in feiten.bank_rlz_verbinding:
            for v in (bank_sync.dag, bank_sync.week):
                v.tel_overgeslagen(GEEN_CREDENTIAL_GEREGISTREERD)
            continue
        runs = sorted((r for r in feiten.bank_sync_runs if r.administratie_id == aid), key=lambda r: r.beeindigd_op)
        for v, vanaf in ((bank_sync.dag, dag_vanaf), (bank_sync.week, week_vanaf)):
            in_venster = [r for r in runs if r.beeindigd_op >= vanaf]
            historie_fouten = sum(r.historie_fouten for r in in_venster)
            if historie_fouten:
                # Verzoek blok B (10-09): mislukte historie-cache-vulling is zichtbaar als `fout`, geen LET-OP.
                v.overgeslagen[FOUT] = v.overgeslagen.get(FOUT, 0) + historie_fouten
            if any(r.status == "klaar" for r in in_venster):
                v.tel_gedaan()
            elif in_venster:
                # Alleen mislukte runs: een kapotte login (401) is een harde voorwaarde → LET-OP mét deeplink
                # naar de administratie; elke andere fout is zichtbaar als "fout" (reden op de run-rij + in het
                # bankscherm) zonder LET-OP — RLZ-storingen dekken het blok `bank` en de bewaking.
                reden = in_venster[-1].fout_reden or ""
                cat = CREDENTIAL if categoriseer_reden(reden) == CREDENTIAL else FOUT
                v.tel_overgeslagen(cat)
                if cat == CREDENTIAL and v is bank_sync.dag:
                    hard.setdefault((BANK_SYNC, CREDENTIAL, aid), []).append(reden)
            else:
                # Mét RLZ-verbinding maar zonder enige run: sync-alles heeft deze administratie niet bereikt.
                # Platformbreed (administratie-loos) → één LET-OP-rij, niet één per administratie.
                v.tel_overgeslagen(GEEN_SYNC_RUN)
                if v is bank_sync.dag:
                    hard.setdefault((BANK_SYNC, GEEN_SYNC_RUN, None), []).append(f"administratie {aid}")

    # --- eerste sync / onboarding (verzoek blok C, 10-09): klaar = gedaan; fout mét 401/403 = harde voorwaarde
    #     `credential` (LET-OP mét deeplink naar de administratie, tekst = fout_reden); andere fout = `fout`.
    for es in feiten.eerste_sync_runs:
        if es.tijdstip < week_vanaf:
            continue
        if es.status == "klaar":
            for v in vensters(eerste_sync, es.tijdstip):
                v.tel_gedaan()
        elif es.geweigerd:
            tel_over(eerste_sync, es.tijdstip, CREDENTIAL, es.administratie_id, es.fout_reden)
        else:
            tel_over(eerste_sync, es.tijdstip, FOUT, es.administratie_id, es.fout_reden)

    # --- terugkerend (run-tabel, platformbreed)
    for r in feiten.terugkerend_runs:
        if r.klaar_op < week_vanaf:
            continue
        for v in vensters(terug, r.klaar_op):
            v.verwacht += r.aantal_administraties
            v.gedaan += r.aantal_verwerkt
            if r.aantal_fouten:
                v.overgeslagen[FOUT] = v.overgeslagen.get(FOUT, 0) + r.aantal_fouten

    # --- autoboek-kandidaten: één run per etmaal verwacht
    lr = feiten.autoboek_kandidaten_laatste_run
    if lr is not None:
        kand.dag.verwacht = 1
        kand.week.verwacht = STIL_DAGEN
    if lr is not None and lr >= dag_vanaf:
        kand.dag.gedaan = 1
    if lr is not None and lr >= week_vanaf:
        kand.week.gedaan = 1  # minimaal één; de instelling bewaart alleen de laatste run

    # --- blok 4 (10-09 avond): vangnet-teller "zonder AI-toets" — stand + LET-OP-groepen per (administratie, soort,
    #     oorzaak) mét deeplink naar de plek van de boekingen (geen instelling: de mens controleert steekproefsgewijs).
    if zonder_toets.week.gedaan > 0:
        zonder_toets.stand = "aan"
        zonder_toets.stand_detail = (
            f"{zonder_toets.dag.gedaan} in het etmaal, {zonder_toets.week.gedaan} in {STIL_DAGEN} dagen — "
            "vangnet, geen poort"
        )
    zonder_toets.detail = zonder_detail
    if not feiten.ai_toets_facturen_aan:
        # Blok 3.2 (10-09 avond): LET-OP zolang de opt-out actief is — óók bij 0 boekingen (de keuze zelf is het
        # signaal); platformbreed (administratie-loos), deeplink naar de schakelaar.
        toets_uit.detail = {
            "uit_sinds": uit_sinds.isoformat() if uit_sinds else None,
            "factuur_24u": toets_uit.dag.gedaan,
        }
        toets_uit.harde_voorwaarden.append(
            HardeVoorwaarde(
                categorie=TOETS_UIT,
                aantal=toets_uit.dag.gedaan,
                administratie_id=None,
                voorbeeld=uit_sinds_tekst,
                soort="factuur_autoboeking",
                doel_pad=DOEL_PAD[TOETS_UIT],
            )
        )
    for (aid, soort, oorzaak), redenen in zonder_groepen.items():
        zonder_toets.harde_voorwaarden.append(
            HardeVoorwaarde(
                categorie=oorzaak,
                aantal=len(redenen),
                administratie_id=aid,
                voorbeeld=next((r for r in redenen if r), None),
                soort=soort,
                doel_pad=doel_pad_zonder_ai_toets(soort=soort, administratie_id=aid),
            )
        )

    # --- harde voorwaarden + stil
    for (sleutel, cat, aid), voorbeelden in hard.items():
        tellers[sleutel].harde_voorwaarden.append(
            HardeVoorwaarde(
                categorie=cat,
                aantal=len(voorbeelden),
                administratie_id=aid,
                voorbeeld=next((v for v in voorbeelden if v), None),
            )
        )
    for t in tellers.values():
        t.harde_voorwaarden.sort(key=lambda h: (h.categorie, str(h.administratie_id or "")))
        if (
            t.stand in ("aan", "deels", "altijd")
            and t.week.verwacht > 0
            and t.week.gedaan == 0
            and t.week.overgeslagen_totaal == 0
        ):
            t.stil = True
    return [tellers[s] for s in VOLGORDE]


# --- bevindingen (puur) --------------------------------------------------------------------------------------


def vingerafdruk_automatisering(*, sleutel: str, categorie: str, administratie_id: uuid.UUID | None) -> str:
    ruw = f"automatisering|{sleutel}|{categorie}|{administratie_id or ''}".encode()
    return hashlib.sha256(ruw).hexdigest()[:_VINGERAFDRUK_LENGTE]


def doel_pad_zonder_ai_toets(*, soort: str, administratie_id: uuid.UUID | None) -> str:
    """Waar de mens de boekingen-zonder-AI-toets steekproefsgewijs controleert: bank → het bankscherm van de
    administratie; factuur → de documentenlijst gefilterd op "automatisch geboekt"; zonder administratie → de
    kantoorbrede werkvoorraad."""
    if administratie_id is None:
        return "/?status=__automatisch_geboekt"
    if soort == "factuur_autoboeking":
        return f"/?administratie={administratie_id}&status=__automatisch_geboekt"
    return f"/bank/{administratie_id}"


def _doel_pad(hv: HardeVoorwaarde) -> str:
    if hv.doel_pad:
        return hv.doel_pad
    pad = DOEL_PAD.get(hv.categorie, "/instellingen")
    if "{aid}" in pad:
        return pad.replace("{aid}", str(hv.administratie_id)) if hv.administratie_id else "/instellingen/administraties"
    return pad


def bevindingen(tellers: Sequence[Teller], *, namen: dict[uuid.UUID, str] | None = None) -> list[dict[str, Any]]:
    """LET-OP-bevindingen als kwargs voor `Verzamelaar.bevinding(...)` (blok `automatisering`): één per
    (automatisering, harde voorwaarde, administratie) en één per stille automatisering. De vingerafdruk is
    stabiel zolang de situatie gelijk blijft — de delta-motor mailt 'm dus één keer, niet elke dag."""
    namen = namen or {}
    uit: list[dict[str, Any]] = []
    for t in tellers:
        for hv in t.harde_voorwaarden:
            waar = f" in administratie {hv.administratie_id}" if hv.administratie_id else ""
            if t.sleutel == AI_TOETS_UIT:
                # Blok 3.2 (10-09 avond): de opt-out zelf is het signaal — tekst draagt het moment en het etmaal-aantal.
                uit.append(
                    {
                        "soort": "let_op",
                        "administratie_id": None,
                        "blok": BLOK,
                        "vingerafdruk": vingerafdruk_automatisering(
                            sleutel=t.sleutel, categorie=TOETS_UIT, administratie_id=None
                        ),
                        "tekst": (
                            f"LET-OP     automatisering {t.sleutel}: AI-toets staat platformbreed uit {hv.voorbeeld} — "
                            f"{hv.aantal} automatische factuurboekingen zonder toets in het etmaal"
                        ),
                        "detail": {
                            "automatisering": t.sleutel,
                            "automatisering_label": t.label,
                            "reden": TOETS_UIT,
                            "uit_sinds": (t.detail or {}).get("uit_sinds"),
                            "aantal": hv.aantal,
                            "voorbeeld": hv.voorbeeld,
                            "administratie_naam": None,
                            "doel_pad": _doel_pad(hv),
                        },
                    }
                )
                continue
            if t.sleutel == AI_TOETS_OVERGESLAGEN:
                # Blok 4 (10-09 avond): geen ontbrekende voorwaarde maar een vangnet — de boekingen zijn er, zonder
                # AI-oordeel; de handeling is een steekproef op de plek van de boekingen (deeplink).
                soort_tekst = "factuur" if hv.soort == "factuur_autoboeking" else "bank"
                uit.append(
                    {
                        "soort": "let_op",
                        "administratie_id": hv.administratie_id,
                        "blok": BLOK,
                        "vingerafdruk": vingerafdruk_automatisering(
                            sleutel=t.sleutel,
                            categorie=f"{ZONDER_AI_TOETS}:{hv.categorie}:{hv.soort or ''}",
                            administratie_id=hv.administratie_id,
                        ),
                        "tekst": (
                            f"LET-OP     automatisering {t.sleutel}: {hv.aantal} automatische {soort_tekst}boekingen "
                            f"zonder AI-toets (oorzaak {hv.categorie}){waar} — controleer steekproefsgewijs"
                        ),
                        "detail": {
                            "automatisering": t.sleutel,
                            "automatisering_label": t.label,
                            "reden": ZONDER_AI_TOETS,
                            "oorzaak": hv.categorie,
                            "boeking_soort": soort_tekst,
                            "aantal": hv.aantal,
                            "voorbeeld": hv.voorbeeld,
                            "administratie_naam": namen.get(hv.administratie_id) if hv.administratie_id else None,
                            "doel_pad": _doel_pad(hv),
                        },
                    }
                )
                continue
            uit.append(
                {
                    "soort": "let_op",
                    "administratie_id": hv.administratie_id,
                    "blok": BLOK,
                    "vingerafdruk": vingerafdruk_automatisering(
                        sleutel=t.sleutel, categorie=hv.categorie, administratie_id=hv.administratie_id
                    ),
                    "tekst": (
                        f"LET-OP     automatisering {t.sleutel}: {hv.aantal} overgeslagen wegens ontbrekende harde "
                        f"voorwaarde [{hv.categorie}]{waar}"
                    ),
                    "detail": {
                        "automatisering": t.sleutel,
                        "automatisering_label": t.label,
                        "reden": hv.categorie,
                        "aantal": hv.aantal,
                        "voorbeeld": hv.voorbeeld,
                        "administratie_naam": namen.get(hv.administratie_id) if hv.administratie_id else None,
                        "doel_pad": _doel_pad(hv),
                    },
                }
            )
        if t.stil:
            uit.append(
                {
                    "soort": "let_op",
                    "administratie_id": None,
                    "blok": BLOK,
                    "vingerafdruk": vingerafdruk_automatisering(
                        sleutel=t.sleutel, categorie=STIL_7_DAGEN, administratie_id=None
                    ),
                    "tekst": (
                        f"LET-OP     automatisering {t.sleutel}: {STIL_DAGEN} dagen 0 gedaan / 0 overgeslagen bij "
                        f"{t.week.verwacht} kandidaten"
                    ),
                    "detail": {
                        "automatisering": t.sleutel,
                        "automatisering_label": t.label,
                        "reden": STIL_7_DAGEN,
                        "aantal": t.week.verwacht,
                        "stand": t.stand,
                        "doel_pad": "/instellingen/autoboeken" if t.sleutel.startswith("autoboek") else "/instellingen",
                    },
                }
            )
    return uit


# --- mail-/CLI-regels (puur) ----------------------------------------------------------------------------------

_STAND_LABEL = {"aan": "aan", "uit": "uit", "deels": "deels aan", "altijd": "aan", "op_aanvraag": "op aanvraag"}


def regels(tellers: Sequence[Teller]) -> list[str]:
    """Het compacte blok "Automatiseringen (laatste 24 u)" voor de mail en de CLI-uitvoer."""
    uit = [f"Automatiseringen (laatste {VENSTER_UREN} u):"]
    for t in tellers:
        if t.is_uit:
            uit.append(f"  {t.label:<38} uit" + (f" ({t.stand_detail})" if t.stand_detail else ""))
            continue
        over = ", ".join(
            f"{REDEN_LABEL.get(k, k)}: {n}" for k, n in sorted(t.dag.overgeslagen.items()) if n or k == GEEN_EIGENAAR
        )
        stand = _STAND_LABEL.get(t.stand, t.stand)
        regel = (
            f"  {t.label:<38} {stand:<10} verwacht {t.dag.verwacht}, gedaan {t.dag.gedaan}, "
            f"overgeslagen {t.dag.overgeslagen_totaal}"
        )
        if over:
            regel += f" ({over})"
        if t.stand_detail and t.stand in ("deels",):
            regel += f" — {t.stand_detail}"
        if t.stil:
            regel += f" — LET-OP: {STIL_DAGEN} dagen stil bij {t.week.verwacht} kandidaten"
        if t.harde_voorwaarden and t.sleutel == AI_TOETS_UIT:
            regel += " — LET-OP: " + "; ".join(
                f"AI-toets staat platformbreed uit {h.voorbeeld} ({h.aantal} factuurboeking(en) zonder toets)"
                for h in t.harde_voorwaarden
            )
        elif t.harde_voorwaarden and t.sleutel == AI_TOETS_OVERGESLAGEN:
            regel += " — LET-OP: " + "; ".join(
                f"{h.aantal}× geboekt zonder AI-toets ({REDEN_LABEL.get(h.categorie, h.categorie)}) — "
                "controleer steekproefsgewijs"
                for h in t.harde_voorwaarden
            )
        elif t.harde_voorwaarden:
            regel += " — LET-OP: " + "; ".join(
                f"{h.aantal}× {REDEN_LABEL.get(h.categorie, h.categorie)}" for h in t.harde_voorwaarden
            )
        uit.append(regel)
    return uit


def uit_samenvatting(samenvatting: dict) -> list[Teller]:
    """De JSON uit `reconciliatie_run.samenvatting["automatiseringen"]` terug naar tellers (mail ná opslag)."""
    uit: list[Teller] = []
    for d in samenvatting.get("tellers") or []:
        t = Teller(
            sleutel=str(d.get("sleutel") or ""),
            label=str(d.get("label") or d.get("sleutel") or ""),
            stand=str(d.get("stand") or "aan"),
            stand_detail=d.get("stand_detail"),
            bron=str(d.get("bron") or ""),
            dag=_venster(d.get("dag")),
            week=_venster(d.get("week")),
            stil=bool(d.get("stil")),
            detail=d.get("detail") if isinstance(d.get("detail"), dict) else None,
        )
        for h in d.get("harde_voorwaarden") or []:
            aid = h.get("administratie_id")
            t.harde_voorwaarden.append(
                HardeVoorwaarde(
                    categorie=str(h.get("categorie") or ""),
                    aantal=int(h.get("aantal") or 0),
                    administratie_id=uuid.UUID(str(aid)) if aid else None,
                    voorbeeld=h.get("voorbeeld"),
                    soort=h.get("soort"),
                    doel_pad=h.get("doel_pad"),
                )
            )
        uit.append(t)
    return uit


def _venster(d: dict | None) -> Venster:
    d = d or {}
    return Venster(
        verwacht=int(d.get("verwacht") or 0),
        gedaan=int(d.get("gedaan") or 0),
        overgeslagen={str(k): int(v or 0) for k, v in (d.get("overgeslagen") or {}).items()},
    )


def regels_uit_samenvatting(samenvatting: dict) -> list[str]:
    return regels(uit_samenvatting(samenvatting))


# --- DB-laag ------------------------------------------------------------------------------------------------------


def verzamel_feiten(*, nu: datetime, administratie_ids: Sequence[uuid.UUID] | None = None) -> Feiten:
    """Lees de feiten uit de bestaande sporen — per administratie in een gescoopte sessie (RLS), de
    administratie-loze audit-rijen en de platformbrede run-tabellen in de scope-loze sessie."""
    from sqlalchemy import func, or_, select

    from app.autoboek_kandidaten.models import AutoboekInstelling, AutoboekKandidaatStand
    from app.bank.models import BankSyncRun, BankSyncRunStatus
    from app.beheer.eerste_sync import RECHTEN_STATUSSEN
    from app.beheer.models import AdministratieSyncRun
    from app.config import settings
    from app.db.models import Administratie, BoekenInstelling, DuplicaatAfvoerInstelling, IntakeInstelling
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus, LeverancierVoorkeur
    from app.odoo.ids import is_odoo_sentinel
    from app.rlz.credentials import heeft_rlz_credential_geregistreerd
    from app.terugkerend.models import HerberekenRunStatus, TerugkerendHerberekenRun
    from app.uren.models import VeldwerkerCrediteur

    week_vanaf = nu - timedelta(days=STIL_DAGEN)
    feiten = Feiten(extractie_job_resource=settings.extractie_wachtrij_job_resource or None)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie).where(Administratie.actief.is_(True))
        if administratie_ids is not None:
            q = q.where(Administratie.id.in_(list(administratie_ids)))
        for a in session.scalars(q):
            feiten.administraties[a.id] = a.naam
            # Bank-sync (blok 1, 08-09): RLZ-verbinding aanwezig? Odoo = geen RLZ-bank; anders store/.env-toets
            # zonder unwrap (goedkoop, geen KMS).
            if is_odoo_sentinel(a.rlz_admin_id):
                feiten.bank_odoo.add(a.id)
            elif heeft_rlz_credential_geregistreerd(a.id, a.rlz_admin_id):
                feiten.bank_rlz_verbinding.add(a.id)
            if a.omzet_autoboeken_ingeschakeld:
                feiten.omzet_aan.add(a.id)
            if a.autoboeken_leren_ingeschakeld and not a.doorbelasting_ingeschakeld:
                feiten.autoboek_leren_aan.add(a.id)
            if a.is_vastgoed:
                feiten.verkoop_aan.add(a.id)
            if a.bank_autoboeken_ingeschakeld:
                feiten.bank_aan.add(a.id)
            if a.mini_voorraad_ingeschakeld:
                feiten.mini_voorraad_aan.add(a.id)
        noodrem = session.get(DuplicaatAfvoerInstelling, True)
        feiten.duplicaat_noodrem_aan = bool(noodrem is not None and noodrem.platformbreed_ingeschakeld)
        intake = session.get(IntakeInstelling, True)
        feiten.intake_ai_aan = bool(intake is not None and intake.ai_ingeschakeld)
        # Blok 3.2 (10-09 avond): platformbrede opt-out factuur-AI-toets — geen rij = AAN (migratie-default).
        boeken_inst = session.get(BoekenInstelling, True)
        feiten.ai_toets_facturen_aan = boeken_inst is None or bool(boeken_inst.ai_toets_facturen_ingeschakeld)
        feiten.ai_toets_facturen_gewijzigd_op = (
            _utc(boeken_inst.gewijzigd_op) if boeken_inst is not None and boeken_inst.gewijzigd_op else None
        )
        kand = session.get(AutoboekInstelling, True)
        feiten.autoboek_kandidaten_laatste_run = kand.laatste_run_op if kand is not None else None
        for r in session.scalars(
            select(TerugkerendHerberekenRun).where(
                TerugkerendHerberekenRun.status == HerberekenRunStatus.KLAAR.value,
                TerugkerendHerberekenRun.klaar_op.is_not(None),
                TerugkerendHerberekenRun.klaar_op >= week_vanaf,
            )
        ):
            feiten.terugkerend_runs.append(
                TerugkerendRunFeit(
                    klaar_op=r.klaar_op,
                    aantal_administraties=r.aantal_administraties,
                    aantal_verwerkt=r.aantal_verwerkt,
                    aantal_fouten=r.aantal_fouten,
                )
            )
        feiten.audit.extend(_audit_feiten(session, None, week_vanaf))

    for aid in list(feiten.administraties):
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            feiten.audit.extend(_audit_feiten(session, aid, week_vanaf))
            feiten.leverancier_optins[aid] = int(
                session.scalar(
                    select(func.count()).where(
                        LeverancierVoorkeur.administratie_id == aid,
                        LeverancierVoorkeur.autoboeken_ingeschakeld.is_(True),
                    )
                )
                or 0
            )
            if aid in feiten.autoboek_leren_aan:
                voorkeuren = session.scalars(
                    select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == aid)
                ).all()
                uitgezonderd_ids = {v.vendor_id for v in voorkeuren if v.autoboeken_uitgezonderd}
                actief_ids = {v.vendor_id for v in voorkeuren if v.autoboeken_ingeschakeld}
                lerend_ids = set(
                    session.scalars(
                        select(AutoboekKandidaatStand.vendor_id).where(
                            AutoboekKandidaatStand.administratie_id == aid, AutoboekKandidaatStand.actief.is_(False)
                        )
                    )
                )
                feiten.autoboek_leren_detail[aid] = {
                    "lerend": len(lerend_ids - uitgezonderd_ids - actief_ids),
                    "actief": len(actief_ids),
                    "uitgezonderd": len(uitgezonderd_ids),
                }
            feiten.veldwerker_optins[aid] = int(
                session.scalar(
                    select(func.count()).where(
                        VeldwerkerCrediteur.administratie_id == aid,
                        VeldwerkerCrediteur.autoboeken_ingeschakeld.is_(True),
                    )
                )
                or 0
            )
            for r in session.scalars(
                select(BankSyncRun).where(
                    BankSyncRun.administratie_id == aid,
                    BankSyncRun.status.in_((BankSyncRunStatus.KLAAR.value, BankSyncRunStatus.FOUT.value)),
                    BankSyncRun.beeindigd_op.is_not(None),
                    BankSyncRun.beeindigd_op >= week_vanaf,
                )
            ):
                if r.status == BankSyncRunStatus.KLAAR.value:
                    feiten.bank_runs.append(
                        BankRunFeit(administratie_id=aid, beeindigd_op=_utc(r.beeindigd_op), resultaat=r.resultaat)
                    )
                res = r.resultaat if isinstance(r.resultaat, dict) else {}
                feiten.bank_sync_runs.append(
                    BankSyncRunFeit(
                        administratie_id=aid,
                        beeindigd_op=_utc(r.beeindigd_op),
                        status=r.status,
                        fout_reden=r.fout_reden,
                        bron=res.get("bron"),
                        historie_fouten=len(res.get("historie_fouten") or []),
                    )
                )
            # Eerste-sync-runs (verzoek blok C): afgerond in de week; 401/403 in een onderdeel = credential-weigering.
            for es in session.scalars(
                select(AdministratieSyncRun).where(
                    AdministratieSyncRun.administratie_id == aid,
                    AdministratieSyncRun.status.in_(("klaar", "fout")),
                    AdministratieSyncRun.beeindigd_op.is_not(None),
                    AdministratieSyncRun.beeindigd_op >= week_vanaf,
                )
            ):
                onderdelen = es.onderdelen if isinstance(es.onderdelen, dict) else {}
                geweigerd = any(
                    isinstance(o, dict) and o.get("http_status") in RECHTEN_STATUSSEN for o in onderdelen.values()
                )
                feiten.eerste_sync_runs.append(
                    EersteSyncFeit(
                        administratie_id=aid,
                        tijdstip=_utc(es.beeindigd_op),
                        status=es.status,
                        geweigerd=geweigerd,
                        fout_reden=es.fout_reden,
                    )
                )
            # Overgangen naar de extractie-wachtrij (upload/intake/herextractie) — herstel-overgangen
            # (`detail.herstel`: achtergebleven na herstart / gestrand op bezig) zijn geen nieuwe kandidaat.
            for (tijdstip,) in session.execute(
                select(DocumentGebeurtenis.tijdstip)
                .join(Document, Document.id == DocumentGebeurtenis.document_id)
                .where(
                    Document.administratie_id == aid,
                    DocumentGebeurtenis.naar_status == DocumentStatus.EXTRACTIE_WACHTRIJ,
                    DocumentGebeurtenis.tijdstip >= week_vanaf,
                    or_(DocumentGebeurtenis.detail.is_(None), ~DocumentGebeurtenis.detail.has_key("herstel")),
                )
            ).all():
                feiten.extractie_wachtrij_overgangen.append((aid, _utc(tijdstip)))
    return feiten


def _audit_feiten(session, aid: uuid.UUID | None, vanaf: datetime) -> list[AuditFeit]:  # noqa: ANN001
    from sqlalchemy import select

    from app.db.models import AuditEvent

    q = select(AuditEvent.actie, AuditEvent.tijdstip, AuditEvent.administratie_id, AuditEvent.nieuwe_waarde).where(
        AuditEvent.actie.in_(_ACTIES), AuditEvent.tijdstip >= vanaf
    )
    q = q.where(AuditEvent.administratie_id.is_(None)) if aid is None else q.where(AuditEvent.administratie_id == aid)
    return [
        AuditFeit(actie=actie, tijdstip=_utc(tijdstip), administratie_id=adm, nieuwe_waarde=nw)
        for actie, tijdstip, adm, nw in session.execute(q).all()
    ]


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def sa_key_rotatie_bevinding(*, nu: datetime, aangemaakt_op: date | None) -> dict[str, Any] | None:
    """Blok 1 nametingen-run 10-09 (§F7 route A, rotatieregel jaarlijks): eenvoudige datum-check op
    `settings.nameting_sa_aangemaakt_op` — vanaf 30 dagen vóór 12 maanden ná aanmaak een platformbrede LET-OP
    (beheer-signaal → systeemmail) "roteer de key van het nameting-serviceaccount"; ná de vervaldatum blijft hij staan
    tot de nieuwe datum in de env staat. None = geen key geregistreerd → geen signaal (niets stil: de env is de bron)."""
    if aangemaakt_op is None:
        return None
    vervalt = date(aangemaakt_op.year + SA_KEY_ROTATIE_MAANDEN // 12, aangemaakt_op.month, min(aangemaakt_op.day, 28))
    vandaag = nu.date()
    dagen_tot = (vervalt - vandaag).days
    if dagen_tot > SA_KEY_ROTATIE_WAARSCHUWING_DAGEN:
        return None
    stand = f"vervalt over {dagen_tot} dagen" if dagen_tot >= 0 else f"{-dagen_tot} dagen over de rotatiedatum"
    return {
        "soort": "let_op",
        "administratie_id": None,
        "blok": BLOK,
        "vingerafdruk": vingerafdruk_automatisering(sleutel="nameting_sa", categorie=SA_KEY_ROTATIE, administratie_id=None),
        "tekst": (
            f"LET-OP     automatisering nameting_sa: key van nameting@ aangemaakt {aangemaakt_op:%d-%m-%Y}, "
            f"rotatie {vervalt:%d-%m-%Y} ({stand}) — roteer volgens GCP_UITROL §F7 (keys create → activeren → oude key "
            "delete → NAMETING_SA_AANGEMAAKT_OP bijwerken)"
        ),
        "detail": {
            "automatisering": "nameting_sa",
            "automatisering_label": "Nameting-serviceaccount (key-rotatie)",
            "reden": SA_KEY_ROTATIE,
            "aangemaakt_op": aangemaakt_op.isoformat(),
            "rotatie_op": vervalt.isoformat(),
            "dagen_tot": dagen_tot,
            "aantal": 1,
            "doel_pad": "/reconciliatie",
        },
    }


def deploy_drift_bevinding(*, nu: datetime) -> dict[str, Any] | None:
    """Ochtendrun 11-09 blok 2.1: staat er een OPEN bewakingsstoring `deploy_drift` (app/bewaking), dan één
    platformbrede LET-OP (beheer → systeemmail) "systeemfout — automatisch gemeld" mét het laatste detail van de
    probe (welke jobs op welk beeld achterlopen). Geen open storing = geen signaal. Stabiele vingerafdruk: de
    delta-motor mailt één keer, de rij verdwijnt zodra de probe weer groen is (storing hersteld)."""
    from sqlalchemy import select

    from app.bewaking.models import BewakingStoring
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        storing = session.scalars(
            select(BewakingStoring)
            .where(BewakingStoring.soort == DEPLOY_DRIFT, BewakingStoring.hersteld_op.is_(None))
            .order_by(BewakingStoring.begonnen_op.desc())
            .limit(1)
        ).first()
        if storing is None:
            return None
        begonnen = _utc(storing.begonnen_op)
        laatste_detail = storing.laatste_detail or "(geen detail)"
        fouten = int(storing.opeenvolgende_fouten or 0)
        gealarmeerd = storing.alert_verzonden_op is not None
    return {
        "soort": "let_op",
        "administratie_id": None,
        "blok": BLOK,
        "vingerafdruk": vingerafdruk_automatisering(sleutel="deploy", categorie=DEPLOY_DRIFT, administratie_id=None),
        "tekst": (
            f"LET-OP     automatisering deploy: Cloud Run-jobs draaien op een ander beeld dan de service sinds "
            f"{begonnen:%d-%m-%Y %H:%M} UTC ({fouten} metingen) — {laatste_detail} — {REGRESSIE_TEKST}"
        )[:1000],
        "detail": {
            "automatisering": "deploy",
            "automatisering_label": "Deploy (service ↔ jobs)",
            "reden": DEPLOY_DRIFT,
            "aantal": fouten,
            "sinds": begonnen.isoformat(),
            "laatste_detail": laatste_detail[:500],
            "gealarmeerd": gealarmeerd,
            "doel_pad": "/reconciliatie",
        },
    }


def registreer(verzamelaar, *, nu: datetime | None = None, stdout=None) -> dict:  # noqa: ANN001
    """Ingang vanuit de run-motor: feiten lezen, tellers berekenen, LET-OPs als bevindingen op de
    verzamelaar zetten en de JSON-samenvatting teruggeven (die `Verzamelaar.samenvatting()` onder
    `automatiseringen` meeneemt). Print het compacte blok óók naar de CLI-uitvoer."""
    from app.config import settings

    nu = nu or datetime.now(UTC)
    feiten = verzamel_feiten(nu=nu)
    tellers = bereken(feiten, nu=nu)
    for kw in bevindingen(tellers, namen=feiten.administraties):
        verzamelaar.bevinding(**kw)
    rotatie = sa_key_rotatie_bevinding(nu=nu, aangemaakt_op=settings.nameting_sa_aangemaakt_op)
    if rotatie is not None:
        verzamelaar.bevinding(**rotatie)
    drift = deploy_drift_bevinding(nu=nu)
    if drift is not None:
        verzamelaar.bevinding(**drift)
    if stdout is not None:
        for regel in regels(tellers):
            stdout(regel)
    return als_samenvatting(tellers, nu=nu)
