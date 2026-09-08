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
from datetime import UTC, datetime, timedelta
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

#: Categorieën die een ONTBREKENDE HARDE VOORWAARDE markeren → LET-OP mét handeling.
#: "geen eigenaar" hoort hier óók bij: sinds blok B (07-09) is een ontbrekende eigenaar/toewijzing géén poort meer —
#: komt de reden tóch voor, dan wacht een automatisering op een menselijke instelling (regressie, zichtbaar mét actie).
#: `vangnet_scheduler` (08-09): ≥ 1 mislukte job-trigger in het etmaal = LET-OP (platformbreed, administratie-loos).
HARDE_VOORWAARDEN = frozenset(
    {CREDENTIAL, API_KEY, GELDPOORT, VOLUMEREM, NOODREM, GEEN_EIGENAAR, VANGNET_SCHEDULER, GEEN_SYNC_RUN}
)

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
}

# --- de automatiseringen ------------------------------------------------------------------------------
DUPLICAAT_AFVOER = "duplicaat_afvoer"
CREDITEUREN = "crediteuren_afhandeling"
AUTOBOEK_INKOOP = "autoboeken_inkoop"
AUTOBOEK_KANDIDATEN = "autoboek_kandidaten"
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
    DUPLICAAT_AFVOER,
    CREDITEUREN,
    AUTOBOEK_KANDIDATEN,
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
    AUTOBOEK_OMZET: "Autoboeken omzet",
    AUTOBOEK_VERKOOP: "Autoboeken verkoop",
    BANK: "Bank-autoboeken/afletteren",
    BANK_SYNC: "Bank-sync (dagelijks, alle administraties)",
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
    # Geen instelling in de app: de wortel zit in Cloud Run/IAM; de rij op Inzicht › Reconciliatie ís de plek.
    VANGNET_SCHEDULER: "/reconciliatie",
    GEEN_SYNC_RUN: "/reconciliatie",
}

#: Vaste categorieën die per automatisering ALTIJD zichtbaar zijn (ook als 0) — kernprincipe 7-cross-check.
VASTE_CATEGORIEEN: dict[str, tuple[str, ...]] = {
    AUTOBOEK_INKOOP: (GEEN_EIGENAAR, HARDE_CHECKS),
    AUTOBOEK_OMZET: (GEEN_EIGENAAR, HARDE_CHECKS),
    AUTOBOEK_VERKOOP: (GEEN_EIGENAAR, HARDE_CHECKS),
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
    autoboek_kandidaten_laatste_run: datetime | None = None
    duplicaat_noodrem_aan: bool = True
    # opt-ins
    leverancier_optins: dict[uuid.UUID, int] = field(default_factory=dict)  # administratie → n leveranciers aan
    veldwerker_optins: dict[uuid.UUID, int] = field(default_factory=dict)
    omzet_aan: set[uuid.UUID] = field(default_factory=set)
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
    """Eén groep overgeslagen stukken wegens een ontbrekende harde voorwaarde (laatste 24 u)."""

    categorie: str
    aantal: int
    administratie_id: uuid.UUID | None
    voorbeeld: str | None = None


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

    def tel_over(t: Teller, tijdstip: datetime, categorie: str, aid: uuid.UUID | None, voorbeeld: str | None) -> None:
        vs = vensters(t, tijdstip)
        for v in vs:
            v.tel_overgeslagen(categorie)
        if categorie in HARDE_VOORWAARDEN and tijdstip >= dag_vanaf:
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
        if f.actie == "automatisch_geboekt":
            t = omzet if bron == "omzet_opt_in" else verkoop if bron == "verkoop_opt_in" else inkoop
            for v in vensters(t, f.tijdstip):
                v.tel_gedaan()
        elif f.actie in ("autoboeken_geweigerd", "autoboeken_half_geboekt"):
            t = omzet if bron == "omzet_opt_in" else verkoop if bron == "verkoop_opt_in" else inkoop
            cat = HALF_GEBOEKT if f.actie == "autoboeken_half_geboekt" else categoriseer_reden(nw.get("reden"))
            tel_over(t, f.tijdstip, cat, f.administratie_id, str(nw.get("reden") or ""))
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


def _doel_pad(hv: HardeVoorwaarde) -> str:
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
        if t.harde_voorwaarden:
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
        )
        for h in d.get("harde_voorwaarden") or []:
            aid = h.get("administratie_id")
            t.harde_voorwaarden.append(
                HardeVoorwaarde(
                    categorie=str(h.get("categorie") or ""),
                    aantal=int(h.get("aantal") or 0),
                    administratie_id=uuid.UUID(str(aid)) if aid else None,
                    voorbeeld=h.get("voorbeeld"),
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

    from app.autoboek_kandidaten.models import AutoboekInstelling
    from app.bank.models import BankSyncRun, BankSyncRunStatus
    from app.config import settings
    from app.db.models import Administratie, DuplicaatAfvoerInstelling
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
            if a.is_vastgoed:
                feiten.verkoop_aan.add(a.id)
            if a.bank_autoboeken_ingeschakeld:
                feiten.bank_aan.add(a.id)
            if a.mini_voorraad_ingeschakeld:
                feiten.mini_voorraad_aan.add(a.id)
        noodrem = session.get(DuplicaatAfvoerInstelling, True)
        feiten.duplicaat_noodrem_aan = bool(noodrem is not None and noodrem.platformbreed_ingeschakeld)
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
                feiten.bank_sync_runs.append(
                    BankSyncRunFeit(
                        administratie_id=aid,
                        beeindigd_op=_utc(r.beeindigd_op),
                        status=r.status,
                        fout_reden=r.fout_reden,
                        bron=(r.resultaat or {}).get("bron") if isinstance(r.resultaat, dict) else None,
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


def registreer(verzamelaar, *, nu: datetime | None = None, stdout=None) -> dict:  # noqa: ANN001
    """Ingang vanuit de run-motor: feiten lezen, tellers berekenen, LET-OPs als bevindingen op de
    verzamelaar zetten en de JSON-samenvatting teruggeven (die `Verzamelaar.samenvatting()` onder
    `automatiseringen` meeneemt). Print het compacte blok óók naar de CLI-uitvoer."""
    nu = nu or datetime.now(UTC)
    feiten = verzamel_feiten(nu=nu)
    tellers = bereken(feiten, nu=nu)
    for kw in bevindingen(tellers, namen=feiten.administraties):
        verzamelaar.bevinding(**kw)
    if stdout is not None:
        for regel in regels(tellers):
            stdout(regel)
    return als_samenvatting(tellers, nu=nu)
