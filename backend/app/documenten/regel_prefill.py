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

Opgeslagen keuzes van de mens worden hier nooit geraakt: de aanroeper roept dit uitsluitend op het
prefill-pad aan (zelfde regel als de btw-chip "uit factuur").
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.models import Administratie
from app.geheugen import regel_gb
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.geheugen.service import laad_engine_observaties

if TYPE_CHECKING:  # boekvoorstel.py importeert deze module (lazy) — geen runtime-cyclus
    from app.documenten.boekvoorstel import BoekvoorstelRegelData

BTW_BRON_STANDAARD = "standaard"

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
) -> tuple[list[BoekvoorstelRegelData], BoekvoorstelRegelData | None]:
    """Geeft (regels, samengevoegde_regel) terug mét regel-GB-voorstel (blok D), leverancier-geheugen (A10) en
    btw-default (blok E); élk gevuld veld draagt zijn herkomst in `prefill_herkomst`."""
    administratie = session.get(Administratie, administratie_id)
    standaard_taxrate_id = administratie.standaard_taxrate_id if administratie is not None else None
    vandaag = datetime.now(UTC).date()

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
        regel = _met_leverancier_geheugen(
            regel,
            engine_observaties=engine_observaties,
            regel_sleutel=sleutel,
            project_verplicht=project_verplicht,
            vandaag=vandaag,
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
        samengevoegde_regel = _met_leverancier_geheugen(
            samengevoegde_regel,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
            project_verplicht=project_verplicht,
            vandaag=vandaag,
        )
        samengevoegde_regel = _met_btw_default(
            samengevoegde_regel,
            standaard_taxrate_id=standaard_taxrate_id,
            engine_observaties=engine_observaties,
            regel_sleutel=None,
        )
    return verrijkt, samengevoegde_regel
