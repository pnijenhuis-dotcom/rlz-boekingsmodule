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

  **WINNAARSVOLGORDE btw-code (één plek, bindend):**
    1. opgeslagen keuze van de MENS (nooit geraakt — alleen het prefill-pad komt hier);
    2. uit de factuur BEREKEND (`btw_bron='factuur'`, netto × tarief ≈ btw, groen) — `_regels_prefill`;
    3. leverancier-GEHEUGEN (kop-niveau-engine, ook oranje/seed) — `_met_leverancier_geheugen`;
    4. uit de factuur VERLEGD (`btw_bron='factuur_verlegd'`, oranje) — `_met_factuur_verlegd`;
    5. administratie-DEFAULT (`btw_bron='standaard'`, grijs) — `_met_btw_default`;
    6. leeg = de mens kiest.
  Elke stap vult uitsluitend een nog leeg veld; de harde checks blijven de poort.

Opgeslagen keuzes van de mens worden hier nooit geraakt: de aanroeper roept dit uitsluitend op het
prefill-pad aan (zelfde regel als de btw-chip "uit factuur").
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Administratie
from app.documenten.checks import is_buitenland_tarief
from app.geheugen import regel_gb
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.geheugen.service import laad_engine_observaties
from app.projecten import match as project_match
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache

if TYPE_CHECKING:  # boekvoorstel.py importeert deze module (lazy) — geen runtime-cyclus
    from app.documenten.boekvoorstel import BoekvoorstelRegelData

BTW_BRON_STANDAARD = "standaard"
# Blok 4c (08-09): btw-code uit de verleggings-vermelding op de factuur — oranje tot het geheugen bevestigt.
BTW_BRON_FACTUUR_VERLEGD = "factuur_verlegd"


def verlegd_taxrate_voor(session: Session, *, administratie_id: uuid.UUID) -> uuid.UUID | None:
    """Het ene verlegd-tarief van de administratie, deterministisch: `IsRelayed`-tarieven (niet verdwenen) →
    precies één = die; anders alleen de NL-tarieven (naam-prefix vóór de komma "NL" — EU-verlegd is óók relayed,
    api-verkenning 31-08) → precies één = die; anders precies één RLZ-favoriet (`IsFavorite`) daarbinnen = die;
    anders None (hoog/laag verlegd zonder favoriet = meerduidig — nooit raden, de mens kiest)."""
    rijen = list(
        session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
            )
        )
    )
    verlegd = [rij for rij in rijen if taxrate_vlaggen(rij.brondata)[0]]
    if len(verlegd) == 1:
        return verlegd[0].id
    if not verlegd:
        return None
    nl = [rij for rij in verlegd if rij.naam and "," in rij.naam and not is_buitenland_tarief(rij.naam)]
    kandidaten = nl or verlegd
    if len(kandidaten) == 1:
        return kandidaten[0].id
    favorieten = [rij for rij in kandidaten if bool((rij.brondata or {}).get("IsFavorite"))]
    if len(favorieten) == 1:
        return favorieten[0].id
    return None


def _met_factuur_verlegd(
    regel: BoekvoorstelRegelData, *, verlegd_taxrate_id: uuid.UUID | None
) -> BoekvoorstelRegelData:
    """Stap 4 van de winnaarsvolgorde: alleen een nog leeg btw-veld op een regel zonder regel-btw (0 of niet gelezen),
    alleen als de factuur verlegd is (aanroeper geeft dan het tarief mee) — oranje `factuur_verlegd`."""
    if verlegd_taxrate_id is None or regel.taxrate_id is not None:
        return regel
    if regel.btw_bedrag is not None and regel.btw_bedrag != 0:
        return regel  # deze regel draagt wél btw — verlegd geldt niet voor haar
    return _met_herkomst(
        replace(regel, taxrate_id=verlegd_taxrate_id, btw_bron=BTW_BRON_FACTUUR_VERLEGD, btw_bewust_leeg=False),
        **{VELD_BTW: BTW_BRON_FACTUUR_VERLEGD},
    )

# Herkomst-waarden per veld in `BoekvoorstelRegelData.prefill_herkomst` (blok A10 07-09). Grootboek: de
# `gb_bron`-waarden van blok D ("geheugen" / "geheugen_seed" / "geheugen_conflict" / "ai") óf
# HERKOMST_LEVERANCIER_GEHEUGEN; btw: "factuur" / HERKOMST_LEVERANCIER_GEHEUGEN / "standaard"; project:
# HERKOMST_LEVERANCIER_GEHEUGEN.
HERKOMST_LEVERANCIER_GEHEUGEN = regel_gb.HERKOMST_LEVERANCIER_GEHEUGEN  # één definitie (regel_gb leest 'm ook)
HERKOMST_FACTUUR = "factuur"
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
    voorstel = bepaal_voorstel(engine_observaties, regel_sleutel=regel_sleutel, vandaag=datetime.now(UTC).date())
    return voorstel.btw.waarde is not None


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
) -> tuple[list[BoekvoorstelRegelData], BoekvoorstelRegelData | None]:
    """Geeft (regels, samengevoegde_regel) terug mét regel-GB-voorstel (blok D), project uit de factuur (blok 10),
    leverancier-geheugen (A10), btw verlegd uit de factuur (blok 4c) en btw-default (blok E); élk gevuld veld draagt
    zijn herkomst in `prefill_herkomst`. `kop_project_tekst` = het kop-`proj` (voor de samengevoegde regel; de losse
    regels dragen hun eigen tekst al). `factuur_verlegd` = de factuur vermeldt "btw verlegd" én de factuur-btw is 0."""
    administratie = session.get(Administratie, administratie_id)
    standaard_taxrate_id = administratie.standaard_taxrate_id if administratie is not None else None
    vandaag = datetime.now(UTC).date()
    verlegd_taxrate_id = verlegd_taxrate_voor(session, administratie_id=administratie_id) if factuur_verlegd else None
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
        if regel.btw_bron == HERKOMST_FACTUUR and regel.taxrate_id is not None:
            regel = _met_herkomst(regel, **{VELD_BTW: HERKOMST_FACTUUR})
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
        regel = _met_factuur_verlegd(regel, verlegd_taxrate_id=verlegd_taxrate_id)
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
        samengevoegde_regel = _met_factuur_verlegd(samengevoegde_regel, verlegd_taxrate_id=verlegd_taxrate_id)
        samengevoegde_regel = _met_btw_default(
            samengevoegde_regel,
            standaard_taxrate_id=standaard_taxrate_id,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
        )
    return verrijkt, samengevoegde_regel
