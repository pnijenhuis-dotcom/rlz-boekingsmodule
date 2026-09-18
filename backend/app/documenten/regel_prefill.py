"""Regel-verrijking van de boekvoorstel-PREFILL (nog niet opgeslagen voorstel) — medewerker-wensen 04-09,
mockup `projectverdeling-en-regelvoorstellen.html` blok 2 + 3, ontwerpnotities ⑦ en ⑧.

Twee onafhankelijke verrijkingen, één aanroep vanuit `boekvoorstel.haal_boekvoorstel_op`:

- **Blok D — grootboek per regel** (`app/geheugen/regel_gb.py`): alleen voor regels zónder `ledger_id`:
  deterministisch regel-geheugen (groen / oranje-seed / oranje-conflict) → persistente AI-classificatie
  (oranje) → leeg (de bestaande kop-niveau-engine-prefill in de UI blijft zoals nu). Op de samengevoegde
  regel nooit: die synthetische omschrijving is geen regel-sleutel.
- **Blok E — btw-default per administratie** (`administratie.standaard_taxrate_id`, migratie 0108): de
  invulvolgorde is ONVERANDERD en expliciet: uit factuur (scan, `btw_bron='factuur'`, al gezet door
  `_regels_prefill`) → leverancier-geheugen (de engine-btw die de UI via `/boekingsgeheugen/voorstel`
  invult — hier alleen GETOETST: heeft de engine een btw-waarde, dan blijft het veld leeg voor de UI) →
  administratie-default (`btw_bron='standaard'`, chip "standaard administratie") → leeg. De default vult
  UITSLUITEND velden waarvoor scan én geheugen niets hadden (besluit Peter 04-09, blok A3): een regel die de
  scan BEWUST leeg liet — 0 % is ambigu (verlegd/vrijgesteld/0 %), meerduidige tariefmatch of een btw-bedrag
  dat op geen tarief past (`BoekvoorstelRegelData.btw_bewust_leeg`) — blijft leeg voor de mens, mét de
  bestaande hint-chips. De harde checks blijven onverkort de poort en het buitenland-signaal blijft staan.
  Geldt ook voor de samengevoegde regel (leverancier-niveau-engine; één bewust-lege regel = bewust leeg).

- **Leverancier-geheugen server-side (blok A10 07-09, stale-check-fix):** het kop-niveau-engine-voorstel
  (`app/geheugen/engine.py`, chip "Geheugen N %") vulde tot 07-09 UITSLUITEND in de browser (`bepaalPrefill` in
  `geheugenVoorstel.ts`) — de checks (`voer_checks_uit` herleest de server-prefill) zagen dat niet en meldden
  "grootboekrekening (regel 1) ontbreekt" terwijl het veld gevuld stond. Sinds 07-09 vult de server dezelfde
  velden volgens dezelfde regel (alleen lege velden, project alleen bij projectplicht, élke engine-waarde — ook
  oranje/seed-only: de chip blijft dan oranje, maar de check "ontbreekt" vuurt niet meer). Volgorde per regel:
  regel-geheugen (D) → AI-classificatie (D) → leverancier-geheugen → btw-default (E) → leeg. Geen `gb_bron`/
  `btw_bron` voor deze vulling: de UI toont de bestaande GeheugenChipBlok op waarde-gelijkheid.
- **Herkomst per veld** (`BoekvoorstelRegelData.prefill_herkomst`, {"grootboek"|"btw"|"project": bron}) reist
  intern mee zodat `boekvoorstel.persisteer_prefill_bij_openen` weet wélke velden deterministisch gevuld zijn
  (autosave-trigger) en de herkomst-chips ná het persisteren kan herstellen.

- **Project uit de factuur (blok 10 07-09, casus Spot Services — óns projectnummer staat op de factuur):** de
  extractie leest `proj` op kop- én regelniveau voor (`BoekvoorstelRegelData.project_tekst`: regel wint van kop,
  kop = default voor regels zonder eigen tekst). Déze code matcht deterministisch (`app/projecten/match.py::
  bepaal_project_uit_factuur`): exacte projectcode → GROEN ("factuur"); leverancier-werknummer-mapping → groen als
  bevestigd, anders ORANJE ("factuur_onbevestigd" — boeken bevestigt 'm, `app_bevestigd`-patroon); fuzzy op
  plaats/opdrachtgever → altijd oranje; meerduidig → NIETS ingevuld, chip met de kandidaten ("factuur_meerduidig").
  Alleen lege projectvelden, alleen bij projectplicht (zelfde regel als het leverancier-geheugen — de projectkolom
  bestaat alleen dáár); het leverancier-geheugen blijft de terugval als de factuur niets zegt. Deze herkomst
  triggert de A10-autosave (boekvoorstel._PROJECT_FACTUUR_HERKOMSTEN).

- **Btw verlegd uit de factuur (blok 4c bundel 08-09, casus Spot Services 2026-608):** `leid_btw_af` is puur
  rekenkundig (netto × tarief ≈ btw) en laat 0 % bewust leeg; de verleggings-vermelding ("Btw verlegd" in kop/
  totaalblok, `btw_verlegd_vermelding`, deterministisch getoetst) was tot 08-09 alleen een HINT-chip. Nu: draagt de
  factuur die vermelding ÉN is de factuur-btw 0 (`boekvoorstel._factuur_is_verlegd`), dan krijgt élke regel zonder
  btw-code én zonder regel-btw het verlegd-tarief van de administratie (`verlegd_taxrate_voor`: `IsRelayed`-tarieven
  uit `taxrate_cache`, niet verdwenen; precies één → die; anders de NL-tarieven (naam-prefix "NL," — EU-verlegd is
  óók relayed); anders precies één RLZ-favoriet; anders NIETS = meerduidig, de hint-chip blijft) mét
  `btw_bron='factuur_verlegd'` — ORANJE tot het leverancier-geheugen de waarde bevestigt (seed-only-regel).
  **HERZIEN blok 6 herstelrun 08-09 (Universal: 12 IsRelayed-tarieven zonder favoriet → None → toevallig kloppende
  administratie-default):** wélk verlegd-tarief = `bepaal_verlegd_taxrate` (keuzevolgorde in die docstring:
  voorkeur Beheerder → meest gebruikt in de RLZ-historie → één/NL/favoriet → administratie-default als die verlegd is →
  leeg). Het gekozen tarief draagt zijn herkomst als `btw_bron_detail` (chip-tekst: "voorkeur beheerder" /
  "meest gebruikt in RLZ-historie (n×)" / "administratie-default" / …) — nooit toeval.

  **WINNAARSVOLGORDE btw-code (één plek, bindend):**
    1. opgeslagen keuze van de MENS (nooit geraakt — alleen het prefill-pad komt hier);
    2. uit de factuur BEREKEND (`btw_bron='factuur'`, netto × tarief ≈ btw, groen) — `_regels_prefill`;
    3. leverancier-GEHEUGEN (kop-niveau-engine, ook oranje/seed) — `_met_leverancier_geheugen`;
    4. uit de factuur VERLEGD (`btw_bron='factuur_verlegd'`, oranje) — `_met_factuur_verlegd`;
    5. GROOTBOEK-DEFAULT uit de bron (`btw_bron='grootboek'`, grijs, chip "standaard grootboek") —
       `_met_grootboek_default` (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele telefonie"): het
       standaard-btw-tarief dat RLZ op de gekozen rekening draagt (`Account.PreferentialTaxRate` →
       `grootboekrekening.standaard_taxrate_id`, migratie 0142; Odoo `account.account.tax_ids`). Alleen als de
       regel een grootboek HEEFT; het tarief moet in de actuele `taxrate_cache` staan (niet verdwenen). De
       A3-regel "0 %/ambigu bewust leeg = leeg laten" geldt NIET voor deze stap: de default is een expliciete
       keuze in RLZ, geen afleiding uit de scan. Wisselt de mens in het controlescherm van grootboek, dan volgt
       de btw dezelfde default client-side (`BoekvoorstelPanel.wijzigRegel`) zolang de btw niet van de mens is.
    5b. GROOTBOEK-DEFAULT uit de HISTORIE (`btw_bron='grootboek_historie'`, ORANJE, chip "meestal op deze rekening
       (n×)") — `_met_grootboek_historie_default` (vervolg-opdracht Cowork/Peter 14-09, migratie 0143): RLZ draagt
       in de praktijk géén PreferentialTaxRate, dus de module leidt per rekening zelf af uit de inkoopregels in het
       boekingsgeheugen (≥ 5 regels én één tarief op ≥ 90 % in 24 maanden — `app/geheugen/grootboek_btw_historie.py`).
       Alleen ná stap 5 (een échte RLZ-default wint), alleen op een regel mét grootboek, tarief in de actuele cache,
       geheugen wint; `btw_bewust_leeg` remt deze stap WÉL (het is een afleiding, geen expliciete RLZ-keuze — zelfde
       A3-regel als de administratie-default). Oranje volgens de seed-only-regel: pas een app-bevestiging via het
       leverancier-geheugen maakt 'm groen — geen nieuwe kleurregel. `btw_bron_detail` draagt "meestal op deze
       rekening (n×)". De grootboek-wissel in het controlescherm volgt dezelfde default client-side.
    6. administratie-DEFAULT (`btw_bron='standaard'`, grijs) — `_met_btw_default`;
    7. leeg = de mens kiest.
  Elke stap vult uitsluitend een nog leeg veld; de harde checks blijven de poort.

Opgeslagen keuzes van de mens worden hier nooit geraakt: de aanroeper roept dit uitsluitend op het
prefill-pad aan (zelfde regel als de btw-chip "uit factuur").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Administratie, Grootboekrekening
from app.documenten.checks import is_buitenland_tarief
from app.documenten.regelsom import zet_btw_in_kosten
from app.geheugen import regel_gb
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.geheugen.service import laad_engine_observaties
from app.projecten import match as project_match
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache
from app.tijd import vandaag_nl

if TYPE_CHECKING:  # boekvoorstel.py importeert deze module (lazy) — geen runtime-cyclus
    from app.documenten.boekvoorstel import BoekvoorstelRegelData

BTW_BRON_STANDAARD = "standaard"
# Opdracht Peter 14-09: btw-code uit het standaard-tarief van de grootboekrekening (RLZ PreferentialTaxRate).
BTW_BRON_GROOTBOEK = "grootboek"
# Vervolg 14-09 (migratie 0143): btw-code afgeleid uit de eigen boekingshistorie van de rekening — oranje tot bevestigd.
BTW_BRON_GROOTBOEK_HISTORIE = "grootboek_historie"
GROOTBOEK_HISTORIE_DETAIL = "meestal op deze rekening"  # + " (n×)"


def grootboek_historie_detail(n: int) -> str:
    """Chip-tekst van de historie-default: "meestal op deze rekening (12×)"."""
    return f"{GROOTBOEK_HISTORIE_DETAIL} ({n}×)"
# Blok 4c (08-09): btw-code uit de verleggings-vermelding op de factuur — oranje tot het geheugen bevestigt.
BTW_BRON_FACTUUR_VERLEGD = "factuur_verlegd"
#: Opdracht Peter 18-09 (casus Rituals 88-186308, BUA — migratie 0163): de grootboekrekening is aftrek-uitgesloten
#: (representatie, relatiegeschenken, personeelsvoorzieningen, kantine) → tarief 0 %/geen btw én de factuur-btw in de
#: kosten (netto := netto + btw, btw := 0,00). Wint van "factuur berekend" (stap 0), verliest alleen van de mens.
BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN = "grootboek_aftrek_uitgesloten"


def aftrek_uitgesloten_detail(code: str | None) -> str:
    return f"aftrek uitgesloten ({code})" if code else "aftrek uitgesloten"


# Herkomst-labels van de verlegd-keuze (blok 6 herstelrun 08-09) — reizen als `btw_bron_detail` mee naar de UI-chip.
VERLEGD_HERKOMST_VOORKEUR = "voorkeur beheerder"
VERLEGD_HERKOMST_HISTORIE = "meest gebruikt in RLZ-historie"  # + " (n×)"
VERLEGD_HERKOMST_ENIGE = "enige verlegd-code van de administratie"
VERLEGD_HERKOMST_ENIGE_NL = "enige NL-verlegd-code van de administratie"
VERLEGD_HERKOMST_FAVORIET = "RLZ-favoriet onder de verlegd-codes"
VERLEGD_HERKOMST_DEFAULT = "administratie-default"
# Venster van de RLZ-historie-telling: laatste 400 dagen (zelfde horizon als de rlz_dubbel-toets); is er in dat venster
# níéts, dan telt alles wat er is.
VERLEGD_HISTORIE_DAGEN = 400


@dataclass(frozen=True)
class VerlegdKeuze:
    """Uitkomst van `bepaal_verlegd_taxrate`: het gekozen verlegd-tarief + leesbare herkomst (chip-tekst) +
    het aantal historische boekingen waarop de historie-stap steunde (0 buiten die stap)."""

    taxrate_id: uuid.UUID
    herkomst: str
    aantal: int = 0

    @property
    def detail(self) -> str:
        return f"{self.herkomst} ({self.aantal}×)" if self.herkomst == VERLEGD_HERKOMST_HISTORIE else self.herkomst


def _verlegd_sorteersleutel(rij: TaxRateCache) -> tuple[int, int, str]:
    """Gelijkspel-volgorde (bindend, nooit toeval): NL vóór EU/Ex-EU, dan hoog vóór laag, dan naam-alfabetisch."""
    naam = rij.naam or ""
    return (1 if is_buitenland_tarief(naam) else 0, 0 if "hoog" in naam.lower() else 1, naam.lower())


def _historie_telling(
    session: Session, *, administratie_id: uuid.UUID, kandidaat_ids: set[uuid.UUID], vandaag: date
) -> dict[uuid.UUID, int]:
    """Aantal boekingen per verlegd-tarief in het boekingsgeheugen van déze administratie (`boeking_observatie`:
    RLZ-historie-seed + app-bevestigingen), eerst binnen `VERLEGD_HISTORIE_DAGEN`, anders alles wat er is."""
    if not kandidaat_ids:
        return {}
    basis = (
        select(BoekingObservatie.btw_id, func.count())
        .where(
            BoekingObservatie.administratie_id == administratie_id,
            BoekingObservatie.btw_id.in_(kandidaat_ids),
        )
        .group_by(BoekingObservatie.btw_id)
    )
    recent = basis.where(BoekingObservatie.bron_datum >= vandaag - timedelta(days=VERLEGD_HISTORIE_DAGEN))
    telling = {btw_id: int(n) for btw_id, n in session.execute(recent).all()}
    if telling:
        return telling
    return {btw_id: int(n) for btw_id, n in session.execute(basis).all()}


def bepaal_verlegd_taxrate(
    session: Session, *, administratie_id: uuid.UUID, vandaag: date | None = None
) -> VerlegdKeuze | None:
    """WELK verlegd-tarief krijgt een regel op een verlegd-factuur (blok 4c) — deterministisch, in deze volgorde
    (blok 6 herstelrun 08-09; elke stap alleen over `IsRelayed`-tarieven van de administratie die niet uit de sync
    verdwenen zijn):

      1. de expliciete VOORKEUR van de Beheerder (`administratie.voorkeurs_verlegd_taxrate_id`, tab Boeken & AI) —
         alleen als dat tarief nog een niet-verdwenen IsRelayed-tarief is (anders valt de stap door, nooit een
         stale id);
      2. het verlegd-tarief dat in de RLZ-HISTORIE van deze administratie (boekingsgeheugen `boeking_observatie`:
         RLZ-seed + app-bevestigingen, laatste 400 dagen — is dat venster leeg, dan alles wat er is) het MEEST
         gebruikt is; gelijkspel: NL-variant boven EU/Ex-EU, dan hoog boven laag, dan naam-alfabetisch;
      3. het bestaande pad zonder historie: precies één IsRelayed-tarief → die; anders precies één NL-tarief
         (naam-prefix "NL," — EU-verlegd is óók relayed) → die; anders precies één RLZ-favoriet (`IsFavorite`)
         daarbinnen → die;
      4. de administratie-default (`standaard_taxrate_id`, blok E) — alleen als die zélf een IsRelayed-tarief is;
      5. None = meerduidig, de mens kiest (hint-chip blijft).

    De uitkomst draagt haar herkomst (`VerlegdKeuze.detail`) zodat het controlescherm toont waaróm dit tarief
    voorstaat. Geen AI, geen toeval."""
    vandaag = vandaag or vandaag_nl()
    rijen = list(
        session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
            )
        )
    )
    verlegd = sorted((rij for rij in rijen if taxrate_vlaggen(rij.brondata)[0]), key=_verlegd_sorteersleutel)
    if not verlegd:
        return None
    per_id = {rij.id: rij for rij in verlegd}
    administratie = session.get(Administratie, administratie_id)

    # 1. voorkeur Beheerder
    voorkeur = administratie.voorkeurs_verlegd_taxrate_id if administratie is not None else None
    if voorkeur is not None and voorkeur in per_id:
        return VerlegdKeuze(taxrate_id=voorkeur, herkomst=VERLEGD_HERKOMST_VOORKEUR)

    # 2. meest gebruikt in de RLZ-historie (gelijkspel via de vaste sorteervolgorde van `verlegd`)
    telling = _historie_telling(session, administratie_id=administratie_id, kandidaat_ids=set(per_id), vandaag=vandaag)
    if telling:
        hoogste = max(telling.values())
        winnaar = next(rij for rij in verlegd if telling.get(rij.id) == hoogste)
        return VerlegdKeuze(taxrate_id=winnaar.id, herkomst=VERLEGD_HERKOMST_HISTORIE, aantal=hoogste)

    # 3. bestaand pad: één / NL / favoriet
    if len(verlegd) == 1:
        return VerlegdKeuze(taxrate_id=verlegd[0].id, herkomst=VERLEGD_HERKOMST_ENIGE)
    nl = [rij for rij in verlegd if rij.naam and "," in rij.naam and not is_buitenland_tarief(rij.naam)]
    if len(nl) == 1:
        return VerlegdKeuze(taxrate_id=nl[0].id, herkomst=VERLEGD_HERKOMST_ENIGE_NL)
    kandidaten = nl or verlegd
    favorieten = [rij for rij in kandidaten if bool((rij.brondata or {}).get("IsFavorite"))]
    if len(favorieten) == 1:
        return VerlegdKeuze(taxrate_id=favorieten[0].id, herkomst=VERLEGD_HERKOMST_FAVORIET)

    # 4. administratie-default, alleen als die zelf verlegd is
    default = administratie.standaard_taxrate_id if administratie is not None else None
    if default is not None and default in per_id:
        return VerlegdKeuze(taxrate_id=default, herkomst=VERLEGD_HERKOMST_DEFAULT)
    return None


def verlegd_taxrate_ids(session: Session, *, administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """Alle `IsRelayed`-tarieven van de administratie (ook uit de sync verdwenen — historie-boekingen dragen ze nog)."""
    rijen = session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
    return {rij.id for rij in rijen if taxrate_vlaggen(rij.brondata)[0]}


def leverancier_verlegd_boekingen(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, vandaag: date | None = None
) -> int:
    """Peter 15-09 (c): hoeveel boekingen van déze leverancier in het boekingsgeheugen (RLZ-seed + app-bevestigingen,
    laatste `VERLEGD_HISTORIE_DAGEN`, anders alles) op een verlegd-tarief staan — ≥ 1 = de leverancier is voor deze
    administratie een verlegd-leverancier (bouw-onderaannemer)."""
    ids = verlegd_taxrate_ids(session, administratie_id=administratie_id)
    if not ids:
        return 0
    vandaag = vandaag or vandaag_nl()
    basis = select(func.count()).where(
        BoekingObservatie.administratie_id == administratie_id,
        BoekingObservatie.vendor_id == vendor_id,
        BoekingObservatie.btw_id.in_(ids),
    )
    recent = int(
        session.scalar(basis.where(BoekingObservatie.bron_datum >= vandaag - timedelta(days=VERLEGD_HISTORIE_DAGEN)))
        or 0
    )
    return recent if recent else int(session.scalar(basis) or 0)


def verlegd_taxrate_voor(session: Session, *, administratie_id: uuid.UUID) -> uuid.UUID | None:
    """Compat-vorm van `bepaal_verlegd_taxrate` (alleen het tarief-id; None = meerduidig, de mens kiest)."""
    keuze = bepaal_verlegd_taxrate(session, administratie_id=administratie_id)
    return None if keuze is None else keuze.taxrate_id


def _met_factuur_verlegd(
    regel: BoekvoorstelRegelData, *, verlegd: VerlegdKeuze | None, basis_detail: str | None = None
) -> BoekvoorstelRegelData:
    """Stap 4 van de winnaarsvolgorde: alleen een nog leeg btw-veld op een regel zonder regel-btw (0 of niet gelezen),
    alleen als de factuur verlegd is (aanroeper geeft dan de keuze mee) — oranje `factuur_verlegd`, mét de herkomst
    van de keuze als `btw_bron_detail` (blok 6). `basis_detail` (Peter 15-09): waaróm de factuur verlegd is als dat
    niet de vermelding is ('kolomcode "V"', 'leverancier eerder verlegd (3×)', 'KvK SBI 43…') — vóór de tariefkeuze."""
    if verlegd is None or regel.taxrate_id is not None:
        return regel
    if regel.btw_bedrag is not None and regel.btw_bedrag != 0:
        return regel  # deze regel draagt wél btw — verlegd geldt niet voor haar
    detail = f"{basis_detail} · {verlegd.detail}" if basis_detail else verlegd.detail
    return _met_herkomst(
        replace(
            regel,
            taxrate_id=verlegd.taxrate_id,
            btw_bron=BTW_BRON_FACTUUR_VERLEGD,
            btw_bron_detail=detail,
            btw_bewust_leeg=False,
        ),
        **{VELD_BTW: BTW_BRON_FACTUUR_VERLEGD},
    )


# Herkomst-waarden per veld in `BoekvoorstelRegelData.prefill_herkomst` (blok A10 07-09). Grootboek: de
# `gb_bron`-waarden van blok D ("geheugen" / "geheugen_seed" / "geheugen_conflict" / "ai") óf
# HERKOMST_LEVERANCIER_GEHEUGEN; btw: "factuur" / HERKOMST_LEVERANCIER_GEHEUGEN / "standaard"; project:
# HERKOMST_LEVERANCIER_GEHEUGEN.
HERKOMST_LEVERANCIER_GEHEUGEN = regel_gb.HERKOMST_LEVERANCIER_GEHEUGEN  # één definitie (regel_gb leest 'm ook)
HERKOMST_FACTUUR = "factuur"
# BUG 18-09 (Zilver Horeca): btw-code uit de btw-KOLOM van de factuurregel ("9%"/"0%") — regelniveau, wint van het
# geheugen (dat vult alleen een lege btw). Zelfde herkomst-tag als "factuur" (chip "factuur 0 %", geen autosave-trigger).
BTW_BRON_FACTUUR_REGEL = "factuur_regel"
FACTUUR_BTW_BRONNEN = frozenset({HERKOMST_FACTUUR, BTW_BRON_FACTUUR_REGEL})
VELD_GROOTBOEK = "grootboek"
VELD_BTW = "btw"
VELD_PROJECT = "project"


def _met_herkomst(regel: BoekvoorstelRegelData, **velden: str) -> BoekvoorstelRegelData:
    return replace(regel, prefill_herkomst={**(regel.prefill_herkomst or {}), **velden})


def _met_leverancier_geheugen(
    regel: BoekvoorstelRegelData,
    *,
    engine_observaties: list[Observatie],
    regel_sleutel: str | None,
    project_verplicht: bool,
    vandaag: date,
) -> BoekvoorstelRegelData:
    """Server-side spiegel van `frontend/src/document/geheugenVoorstel.ts::bepaalPrefill`: uitsluitend lege
    velden, project alleen bij projectplicht, élke engine-waarde (ook oranje — de chip blijft oranje)."""
    if not engine_observaties:
        return regel
    voorstel = bepaal_voorstel(engine_observaties, regel_sleutel=regel_sleutel, vandaag=vandaag)
    wijzigingen: dict[str, uuid.UUID] = {}
    herkomst: dict[str, str] = {}
    if regel.ledger_id is None and voorstel.gb.waarde is not None:
        wijzigingen["ledger_id"] = voorstel.gb.waarde
        herkomst[VELD_GROOTBOEK] = HERKOMST_LEVERANCIER_GEHEUGEN
    if regel.taxrate_id is None and voorstel.btw.waarde is not None:
        wijzigingen["taxrate_id"] = voorstel.btw.waarde
        herkomst[VELD_BTW] = HERKOMST_LEVERANCIER_GEHEUGEN
    if project_verplicht and regel.project_id is None and voorstel.project.waarde is not None:
        wijzigingen["project_id"] = voorstel.project.waarde
        herkomst[VELD_PROJECT] = HERKOMST_LEVERANCIER_GEHEUGEN
    if not wijzigingen:
        return regel
    return _met_herkomst(replace(regel, **wijzigingen), **herkomst)


def _met_factuur_project(
    regel: BoekvoorstelRegelData,
    *,
    kandidaten: list[project_match.ProjectKandidaat],
    werknummers: list[project_match.WerknummerKoppeling],
    project_verplicht: bool,
) -> BoekvoorstelRegelData:
    """Blok 10: project uit de op de factuur gelezen tekst — alleen een leeg projectveld bij projectplicht.
    Meerduidig vult niets maar draagt de kandidaten als chip-detail; geen tekst = ongemoeid."""
    if not project_verplicht or regel.project_id is not None or not regel.project_tekst or not kandidaten:
        return regel
    uitkomst = project_match.bepaal_project_uit_factuur(regel.project_tekst, kandidaten, werknummers)
    herkomst = uitkomst.herkomst
    if herkomst is None:
        return regel
    regel = replace(regel, project_bron=herkomst, project_bron_detail=uitkomst.detail)
    if uitkomst.project_id is None:
        return regel  # meerduidig: niets invullen, wél zichtbaar maken
    return _met_herkomst(replace(regel, project_id=uitkomst.project_id), **{VELD_PROJECT: herkomst})


def _engine_observaties(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> list[Observatie]:
    """Exact dezelfde invoer als `geheugen.service.voorstel_voor` (vendor-niveau, geen kenmerk-groep) —
    via dezélfde lader, incl. de Odoo-rekening-mapping-vertaling van een overgestapte administratie (blok A
    04-09): de toets "heeft het leverancier-geheugen een btw-voorstel?" moet hetzelfde antwoord geven als
    wat de UI straks via die route invult."""
    return laad_engine_observaties(session, administratie_id=administratie_id, vendor_id=vendor_id)


def _engine_heeft_btw(engine_observaties: list[Observatie], *, regel_sleutel: str | None) -> bool:
    if not engine_observaties:
        return False
    voorstel = bepaal_voorstel(engine_observaties, regel_sleutel=regel_sleutel, vandaag=vandaag_nl())
    return voorstel.btw.waarde is not None


def aftrek_uitgesloten_voor(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """{ledger_id: code} van de aftrek-uitgesloten rekeningen van déze administratie (migratie 0163) die nog in de bron
    staan — de Beheerder zette het kenmerk expliciet (nooit afgeleid)."""
    rijen = session.execute(
        select(Grootboekrekening.ledger_id, Grootboekrekening.code).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.btw_aftrek_uitgesloten.is_(True),
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
        )
    ).all()
    return {ledger_id: code for ledger_id, code in rijen}


def nul_taxrate_voor(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    grootboek_defaults: dict[uuid.UUID, uuid.UUID],
    ledger_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Het 0 %-tarief voor "btw in kosten": de RLZ-default van de rekening als dat een NL-0 %-tarief is, anders de
    RLZ-favoriet onder de NL-0 %-tarieven (niet verlegd/vrijgesteld/buitenland), anders de eerste op naam; None als de
    administratie er geen heeft (dan blijft het tarief leeg — de mens kiest, de check blijft de poort)."""
    from app.documenten.checks import TariefInfo, nul_tarief_voor

    rijen = session.execute(
        select(TaxRateCache.id, TaxRateCache.naam, TaxRateCache.percentage, TaxRateCache.brondata).where(
            TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
        )
    ).all()
    tarieven = {}
    for r in rijen:
        verlegd, vrijgesteld = taxrate_vlaggen(r.brondata)
        tarieven[r.id] = TariefInfo(
            percentage=r.percentage,
            naam=r.naam,
            verlegd=verlegd,
            vrijgesteld=vrijgesteld,
            favoriet=bool((r.brondata or {}).get("IsFavorite")),
            buitenland=is_buitenland_tarief(r.naam),
        )
    huidig = grootboek_defaults.get(ledger_id) if ledger_id is not None else None
    return nul_tarief_voor(tarieven, huidig=huidig)


def _met_aftrek_uitgesloten(
    regel: BoekvoorstelRegelData,
    *,
    uitgesloten: dict[uuid.UUID, str],
    nul_taxrate_id: uuid.UUID | None,
) -> BoekvoorstelRegelData:
    """Stap 0 (Peter 18-09, BUA): staat de (al gevulde) grootboekrekening op aftrek-uitgesloten, dan wint dat van
    "factuur berekend": tarief := het 0 %-tarief van de administratie, de factuur-btw gaat in de kosten (netto + btw,
    btw 0,00), chip "aftrek uitgesloten (4510)". Zonder kenmerk gebeurt er niets (bestaande volgorde). Zonder 0 %-tarief
    in de cache blijft het tarief leeg mét de chip — de mens kiest, de check blijft de poort."""
    if regel.ledger_id is None or regel.ledger_id not in uitgesloten:
        return regel
    netto, btw = regel.netto_bedrag, regel.btw_bedrag
    if netto is not None and btw is not None and btw != 0:
        netto, btw = zet_btw_in_kosten(netto, btw)
    elif netto is not None and btw is None:
        btw = Decimal("0.00")
    return _met_herkomst(
        replace(
            regel,
            taxrate_id=nul_taxrate_id,
            netto_bedrag=netto,
            btw_bedrag=btw,
            btw_bron=BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN,
            btw_bron_detail=aftrek_uitgesloten_detail(uitgesloten[regel.ledger_id]),
            btw_in_kosten=True,
            btw_bewust_leeg=False,
        ),
        **{VELD_BTW: BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN},
    )


def grootboek_defaults_voor(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    """{ledger_id: standaard_taxrate_id} van déze administratie — alleen rekeningen mét een default die nog in de
    bron staan, en alleen tarieven die in de actuele `taxrate_cache` staan (een verdwenen tarief vult nooit)."""
    actieve_tarieven = set(
        session.scalars(
            select(TaxRateCache.id).where(
                TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
            )
        )
    )
    rijen = session.execute(
        select(Grootboekrekening.ledger_id, Grootboekrekening.standaard_taxrate_id).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.standaard_taxrate_id.is_not(None),
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
        )
    ).all()
    return {ledger_id: taxrate_id for ledger_id, taxrate_id in rijen if taxrate_id in actieve_tarieven}


def grootboek_historie_defaults_voor(
    session: Session, *, administratie_id: uuid.UUID
) -> dict[uuid.UUID, tuple[uuid.UUID, int]]:
    """{ledger_id: (historie_taxrate_id, n)} van déze administratie (migratie 0143) — zelfde filters als
    `grootboek_defaults_voor`: rekening nog in de bron, tarief nog in de actuele `taxrate_cache`."""
    actieve_tarieven = set(
        session.scalars(
            select(TaxRateCache.id).where(
                TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
            )
        )
    )
    rijen = session.execute(
        select(
            Grootboekrekening.ledger_id, Grootboekrekening.historie_taxrate_id, Grootboekrekening.historie_taxrate_n
        ).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.historie_taxrate_id.is_not(None),
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
        )
    ).all()
    return {
        ledger_id: (taxrate_id, int(n or 0)) for ledger_id, taxrate_id, n in rijen if taxrate_id in actieve_tarieven
    }


def _met_grootboek_historie_default(
    regel: BoekvoorstelRegelData,
    *,
    historie_defaults: dict[uuid.UUID, tuple[uuid.UUID, int]],
    engine_observaties: list[Observatie],
    regel_sleutel: str | None,
) -> BoekvoorstelRegelData:
    """Stap 5b: de uit de historie afgeleide default van de (al gevulde) grootboekrekening — vult alleen een leeg
    btw-veld, ná de échte RLZ-default (stap 5). `btw_bewust_leeg` remt WÉL (afleiding, geen expliciete RLZ-keuze);
    het leverancier-geheugen wint. Oranje chip mét "meestal op deze rekening (n×)" als `btw_bron_detail`."""
    if regel.taxrate_id is not None or regel.ledger_id is None:
        return regel
    default = historie_defaults.get(regel.ledger_id)
    if default is None:
        return regel
    if regel.btw_bewust_leeg:
        return regel  # de scan liet 'm bewust leeg (0 %/ambigu) — de mens kiest (A3)
    if _engine_heeft_btw(engine_observaties, regel_sleutel=regel_sleutel):
        return regel
    taxrate_id, n = default
    return _met_herkomst(
        replace(
            regel,
            taxrate_id=taxrate_id,
            btw_bron=BTW_BRON_GROOTBOEK_HISTORIE,
            btw_bron_detail=grootboek_historie_detail(n),
        ),
        **{VELD_BTW: BTW_BRON_GROOTBOEK_HISTORIE},
    )


def _met_grootboek_default(
    regel: BoekvoorstelRegelData,
    *,
    grootboek_defaults: dict[uuid.UUID, uuid.UUID],
    engine_observaties: list[Observatie],
    regel_sleutel: str | None,
) -> BoekvoorstelRegelData:
    """Stap 5 van de winnaarsvolgorde: het standaard-btw-tarief van de (al gevulde) grootboekrekening. Vult alleen
    een leeg btw-veld; het leverancier-geheugen wint (de UI vult 'm dan mét geheugen-chip); `btw_bewust_leeg` is
    hier bewust GEEN rem (de default is een expliciete RLZ-keuze op de rekening, geen scan-afleiding)."""
    if regel.taxrate_id is not None or regel.ledger_id is None:
        return regel
    default = grootboek_defaults.get(regel.ledger_id)
    if default is None:
        return regel
    if _engine_heeft_btw(engine_observaties, regel_sleutel=regel_sleutel):
        return regel
    return _met_herkomst(
        replace(regel, taxrate_id=default, btw_bron=BTW_BRON_GROOTBOEK), **{VELD_BTW: BTW_BRON_GROOTBOEK}
    )


def _met_btw_default(
    regel: BoekvoorstelRegelData,
    *,
    standaard_taxrate_id: uuid.UUID | None,
    engine_observaties: list[Observatie],
    regel_sleutel: str | None,
) -> BoekvoorstelRegelData:
    if standaard_taxrate_id is None or regel.taxrate_id is not None:
        return regel
    if regel.btw_bewust_leeg:
        return regel  # de scan liet 'm bewust leeg (0 %/ambigu) — de mens kiest, de default zwijgt (A3)
    if _engine_heeft_btw(engine_observaties, regel_sleutel=regel_sleutel):
        return regel  # leverancier-geheugen wint: de UI vult 'm mét geheugen-chip
    return _met_herkomst(
        replace(regel, taxrate_id=standaard_taxrate_id, btw_bron=BTW_BRON_STANDAARD), **{VELD_BTW: BTW_BRON_STANDAARD}
    )


def verrijk_prefill(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    regels: list[BoekvoorstelRegelData],
    samengevoegde_regel: BoekvoorstelRegelData | None,
    project_verplicht: bool = False,
    kop_project_tekst: str | None = None,
    factuur_verlegd: bool = False,
    verlegd_basis_detail: str | None = None,
) -> tuple[list[BoekvoorstelRegelData], BoekvoorstelRegelData | None]:
    """Geeft (regels, samengevoegde_regel) terug mét regel-GB-voorstel (blok D), project uit de factuur (blok 10),
    leverancier-geheugen (A10), btw verlegd uit de factuur (blok 4c) en btw-default (blok E); élk gevuld veld draagt
    zijn herkomst in `prefill_herkomst`. `kop_project_tekst` = het kop-`proj` (voor de samengevoegde regel; de losse
    regels dragen hun eigen tekst al). `factuur_verlegd` = de factuur vermeldt "btw verlegd" én de factuur-btw is 0."""
    administratie = session.get(Administratie, administratie_id)
    standaard_taxrate_id = administratie.standaard_taxrate_id if administratie is not None else None
    grootboek_defaults = grootboek_defaults_voor(session, administratie_id=administratie_id)
    historie_defaults = grootboek_historie_defaults_voor(session, administratie_id=administratie_id)
    # 18-09 (BUA): aftrek-uitgesloten rekeningen + het 0 %-tarief waarmee "btw in kosten" gezet wordt.
    uitgesloten = aftrek_uitgesloten_voor(session, administratie_id=administratie_id)
    nul_per_ledger: dict[uuid.UUID | None, uuid.UUID | None] = {}

    def nul_voor(ledger_id: uuid.UUID | None) -> uuid.UUID | None:
        if ledger_id not in nul_per_ledger:
            nul_per_ledger[ledger_id] = nul_taxrate_voor(
                session, administratie_id=administratie_id, grootboek_defaults=grootboek_defaults, ledger_id=ledger_id
            )
        return nul_per_ledger[ledger_id]

    vandaag = vandaag_nl()
    verlegd = (
        bepaal_verlegd_taxrate(session, administratie_id=administratie_id, vandaag=vandaag) if factuur_verlegd else None
    )
    if samengevoegde_regel is not None and samengevoegde_regel.project_tekst is None and kop_project_tekst:
        samengevoegde_regel = replace(samengevoegde_regel, project_tekst=kop_project_tekst)

    # Blok 10: kandidaten + werknummer-geheugen één keer per document laden, alleen als er iets te matchen is.
    projectkandidaten: list[project_match.ProjectKandidaat] = []
    werknummers: list[project_match.WerknummerKoppeling] = []
    if project_verplicht and (
        any(r.project_tekst for r in regels) or (samengevoegde_regel is not None and samengevoegde_regel.project_tekst)
    ):
        projectkandidaten = project_match.laad_projectkandidaten(session, administratie_id=administratie_id)
        if vendor_id is not None and projectkandidaten:
            werknummers = project_match.laad_werknummers(
                session, administratie_id=administratie_id, vendor_id=vendor_id
            )

    regel_observaties: list[regel_gb.RegelObservatie] = []
    engine_observaties: list[Observatie] = []
    classificaties: dict[int, regel_gb.RegelGbClassificatie] = {}
    if vendor_id is not None:
        groep = regel_gb.vendor_groep(session, administratie_id=administratie_id, vendor_id=vendor_id)
        regel_observaties = regel_gb.laad_observaties(session, administratie_id=administratie_id, vendor_ids=groep)
        engine_observaties = _engine_observaties(session, administratie_id=administratie_id, vendor_id=vendor_id)
        classificaties = regel_gb.classificaties_voor(session, document_id=document_id)

    verrijkt: list[BoekvoorstelRegelData] = []
    for volgnummer, regel in enumerate(regels, start=1):
        sleutel = normaliseer_regel_sleutel(regel.omschrijving)
        if regel.btw_bron in FACTUUR_BTW_BRONNEN and regel.taxrate_id is not None:
            regel = _met_herkomst(regel, **{VELD_BTW: regel.btw_bron})
        if regel.ledger_id is None and vendor_id is not None:
            voorstel = regel_gb.bepaal_regel_gb(regel_observaties, regel_sleutel=sleutel)
            if voorstel is not None:
                regel = _met_herkomst(
                    replace(
                        regel, ledger_id=voorstel.ledger_id, gb_bron=voorstel.bron, gb_voorstel_detail=voorstel.detail
                    ),
                    **{VELD_GROOTBOEK: voorstel.bron},
                )
            else:
                classificatie = regel_gb.geldige_classificatie(
                    classificaties, volgnummer=volgnummer, omschrijving=regel.omschrijving
                )
                if classificatie is not None and classificatie.ledger_id is not None:
                    regel = _met_herkomst(
                        replace(
                            regel,
                            ledger_id=classificatie.ledger_id,
                            gb_bron=regel_gb.BRON_AI,
                            gb_voorstel_detail=regel_gb.ai_detail(classificatie.kandidaten_n),
                        ),
                        **{VELD_GROOTBOEK: regel_gb.BRON_AI},
                    )
        if uitgesloten and regel.ledger_id in uitgesloten:
            regel = _met_aftrek_uitgesloten(regel, uitgesloten=uitgesloten, nul_taxrate_id=nul_voor(regel.ledger_id))
        regel = _met_factuur_project(
            regel, kandidaten=projectkandidaten, werknummers=werknummers, project_verplicht=project_verplicht
        )
        regel = _met_leverancier_geheugen(
            regel,
            engine_observaties=engine_observaties,
            regel_sleutel=sleutel,
            project_verplicht=project_verplicht,
            vandaag=vandaag,
        )
        regel = _met_factuur_verlegd(regel, verlegd=verlegd, basis_detail=verlegd_basis_detail)
        regel = _met_grootboek_default(
            regel, grootboek_defaults=grootboek_defaults, engine_observaties=engine_observaties, regel_sleutel=sleutel
        )
        regel = _met_grootboek_historie_default(
            regel, historie_defaults=historie_defaults, engine_observaties=engine_observaties, regel_sleutel=sleutel
        )
        regel = _met_btw_default(
            regel,
            standaard_taxrate_id=standaard_taxrate_id,
            engine_observaties=engine_observaties,
            regel_sleutel=sleutel,
        )
        verrijkt.append(regel)

    if samengevoegde_regel is not None:
        # Leverancier-niveau: de synthetische samenvoeg-omschrijving is geen regel-sleutel (zelfde
        # redenering als in autoboeken.py).
        if samengevoegde_regel.btw_bron == HERKOMST_FACTUUR and samengevoegde_regel.taxrate_id is not None:
            samengevoegde_regel = _met_herkomst(samengevoegde_regel, **{VELD_BTW: HERKOMST_FACTUUR})
        if uitgesloten and samengevoegde_regel.ledger_id in uitgesloten:
            samengevoegde_regel = _met_aftrek_uitgesloten(
                samengevoegde_regel, uitgesloten=uitgesloten, nul_taxrate_id=nul_voor(samengevoegde_regel.ledger_id)
            )
        samengevoegde_regel = _met_factuur_project(
            samengevoegde_regel,
            kandidaten=projectkandidaten,
            werknummers=werknummers,
            project_verplicht=project_verplicht,
        )
        samengevoegde_regel = _met_leverancier_geheugen(
            samengevoegde_regel,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
            project_verplicht=project_verplicht,
            vandaag=vandaag,
        )
        samengevoegde_regel = _met_factuur_verlegd(
            samengevoegde_regel, verlegd=verlegd, basis_detail=verlegd_basis_detail
        )
        samengevoegde_regel = _met_grootboek_default(
            samengevoegde_regel,
            grootboek_defaults=grootboek_defaults,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
        )
        samengevoegde_regel = _met_grootboek_historie_default(
            samengevoegde_regel,
            historie_defaults=historie_defaults,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
        )
        samengevoegde_regel = _met_btw_default(
            samengevoegde_regel,
            standaard_taxrate_id=standaard_taxrate_id,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
        )
    return verrijkt, samengevoegde_regel
