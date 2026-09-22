"""Btw-plichtig per administratie (BUG Peter 22-09, casus Vastgoedgroep Nederland / Studio Lacy Lion 2026-042 →
RLZ-04-00000925; migratie 0170; BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE
CHECK (Peter 22-09)").

De module kende geen kenmerk "btw-plichtig": de kennis "VGG is niet btw-plichtig" zat alleen in de VGG-migratiecode
(`odoo/rj220.py`, `migratie/vertaling.py`). Deze module is de ENE schrijver van `administratie.btw_plichtig`:

- `zet(...)` — Beheerder zet het kenmerk (bron 'mens', audit `administratie_btw_plichtig_gewijzigd` oud→nieuw);
- `volg_rlz_signaal(...)` — de nachtelijke identiteit-sync levert `AdministrationSettings.EnableTaxReporting`
  (STAP-0 22-09: VGG false; Kempen Facilities, Rubicon, Arvum true). `true` bevestigt btw-plichtig mét bron 'rlz'
  (alleen als er nog geen mens-keuze staat); `false` zet het kenmerk NOOIT zelf op false — een administratie kan de
  aangifte buiten RLZ doen en stil alle btw in de kosten zetten is de spiegelbeeld-fout van de casus. Het signaal
  wordt opgeslagen en voedt de detector;
- `kandidaten(...)` — detector "niet btw-plichtig?": kenmerk staat (nog) op true zonder mens-bevestiging én (RLZ-signaal
  false óf geen enkel tarief met percentage > 0 in de cache) → LET-OP "bevestig btw-status" in de reconciliatie
  (`reconciliatie/automatiseringen.py::btw_status_bevinding`) mét deeplink naar Instellingen › Administraties;
- `geen_btw_taxrate_voor(...)` — de "geen btw"-code van een niet-btw-plichtige administratie: het vrijgestelde
  NL-tarief (`IsExcempt`, VGG: "NL, Geen BTW (Vrijgesteld)", favoriet) > het NL-0 %-tarief ("NL, Nul tarief") > None
  (dan géén `TaxRate` in de PUT — zichtbaar in de prefill-chip).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.checks import TariefInfo, is_buitenland_tarief, nul_tarief_voor
from app.schemas_basis import StrikteInvoer
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache

BRON_RLZ = "rlz"
BRON_MENS = "mens"
AUDIT_ACTIE = "administratie_btw_plichtig_gewijzigd"
BTW_BRON_NIET_PLICHTIG = "administratie_niet_btw_plichtig"
CHIP_TEKST = "administratie niet btw-plichtig — btw zit in de kosten"


class BtwPlichtigFout(Exception):
    """Onbekende administratie (404)."""


class BtwPlichtigDto(BaseModel):
    administratie_id: uuid.UUID
    btw_plichtig: bool
    bron: str | None
    gewijzigd_op: datetime | None
    rlz_signaal: bool | None
    rlz_gezien_op: datetime | None
    #: De "geen btw"-code die de prefill in een niet-btw-plichtige administratie kiest (None = geen → zonder TaxRate).
    geen_btw_taxrate_id: uuid.UUID | None = None
    geen_btw_taxrate_naam: str | None = None
    #: Detector-uitkomst: staat deze administratie als kandidaat "niet btw-plichtig — bevestig" (zie `kandidaten`).
    kandidaat: bool = False
    kandidaat_reden: str | None = None


class BtwPlichtigInput(StrikteInvoer):
    btw_plichtig: bool


@dataclass(frozen=True)
class Kandidaat:
    administratie_id: uuid.UUID
    naam: str
    reden: str  # 'rlz_signaal' | 'geen_tarief_met_percentage'
    rlz_signaal: bool | None


def _tarieven(session, administratie_id: uuid.UUID) -> dict[uuid.UUID, TariefInfo]:  # noqa: ANN001
    rijen = session.execute(
        select(TaxRateCache.id, TaxRateCache.naam, TaxRateCache.percentage, TaxRateCache.brondata).where(
            TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None)
        )
    ).all()
    uit: dict[uuid.UUID, TariefInfo] = {}
    for r in rijen:
        verlegd, vrijgesteld = taxrate_vlaggen(r.brondata)
        uit[r.id] = TariefInfo(
            percentage=r.percentage,
            naam=r.naam,
            verlegd=verlegd,
            vrijgesteld=vrijgesteld,
            favoriet=bool((r.brondata or {}).get("IsFavorite")),
            buitenland=is_buitenland_tarief(r.naam),
        )
    return uit


def geen_btw_taxrate_uit(tarieven: dict[uuid.UUID, TariefInfo]) -> uuid.UUID | None:
    """Pure keuze: NL-vrijgesteld (IsExcempt, niet verlegd/buitenland; favoriet eerst, dan naam) > NL 0 % > None."""
    vrijgesteld = [(tid, t) for tid, t in tarieven.items() if t.vrijgesteld and not t.verlegd and not t.buitenland]
    if vrijgesteld:
        vrijgesteld.sort(key=lambda kt: (not kt[1].favoriet, kt[1].naam or "", str(kt[0])))
        return vrijgesteld[0][0]
    return nul_tarief_voor(tarieven)


def geen_btw_taxrate_voor(session, administratie_id: uuid.UUID) -> uuid.UUID | None:  # noqa: ANN001
    return geen_btw_taxrate_uit(_tarieven(session, administratie_id))


def heeft_tarief_met_percentage(tarieven: dict[uuid.UUID, TariefInfo]) -> bool:
    return any(t.percentage is not None and t.percentage > Decimal(0) for t in tarieven.values())


def is_btw_plichtig(administratie_id: uuid.UUID) -> bool:
    """Lezer voor prefill/checks/boekpaden: onbekende administratie = True (bestaand gedrag, nooit stil in kosten)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie.btw_plichtig if administratie is not None else True


def kandidaat_reden(
    *,
    btw_plichtig: bool,
    bron: str | None,
    rlz_signaal: bool | None,
    tarief_met_pct: bool,
    tarieven_gesynct: bool = True,
) -> str | None:
    """Pure detector-regel. None = geen kandidaat; alleen zolang het kenmerk op true staat zonder bevestiging (mens óf
    RLZ EnableTaxReporting true). Het tarieven-signaal telt alleen als er überhaupt tarieven gesynct zijn (een
    administratie vóór haar eerste sync is geen kandidaat, maar een sync-gat)."""
    if not btw_plichtig or bron in (BRON_MENS, BRON_RLZ):
        return None
    if rlz_signaal is False:
        return "rlz_signaal"
    if tarieven_gesynct and not tarief_met_pct:
        return "geen_tarief_met_percentage"
    return None


def kandidaten() -> list[Kandidaat]:
    """Detector over álle actieve administraties (per administratie in eigen scope voor de tarieven-cache — RLS)."""
    with scoped_session(None) as session:
        rijen = session.execute(
            select(
                Administratie.id,
                Administratie.naam,
                Administratie.btw_plichtig,
                Administratie.btw_plichtig_bron,
                Administratie.btw_plichtig_rlz_signaal,
            )
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    uit: list[Kandidaat] = []
    for aid, naam, plichtig, bron, signaal in rijen:
        if not plichtig or bron == BRON_MENS:
            continue
        with scoped_session(aid) as session:
            tarieven = _tarieven(session, aid)
        reden = kandidaat_reden(
            btw_plichtig=plichtig,
            bron=bron,
            rlz_signaal=signaal,
            tarief_met_pct=heeft_tarief_met_percentage(tarieven),
            tarieven_gesynct=bool(tarieven),
        )
        if reden is not None:
            uit.append(Kandidaat(administratie_id=aid, naam=naam, reden=reden, rlz_signaal=signaal))
    return uit


def _dto(session, administratie: Administratie) -> BtwPlichtigDto:  # noqa: ANN001
    tarieven = _tarieven(session, administratie.id)
    geen_id = geen_btw_taxrate_uit(tarieven)
    reden = kandidaat_reden(
        btw_plichtig=administratie.btw_plichtig,
        bron=administratie.btw_plichtig_bron,
        rlz_signaal=administratie.btw_plichtig_rlz_signaal,
        tarief_met_pct=heeft_tarief_met_percentage(tarieven),
        tarieven_gesynct=bool(tarieven),
    )
    return BtwPlichtigDto(
        administratie_id=administratie.id,
        btw_plichtig=administratie.btw_plichtig,
        bron=administratie.btw_plichtig_bron,
        gewijzigd_op=administratie.btw_plichtig_gewijzigd_op,
        rlz_signaal=administratie.btw_plichtig_rlz_signaal,
        rlz_gezien_op=administratie.btw_plichtig_rlz_gezien_op,
        geen_btw_taxrate_id=geen_id,
        geen_btw_taxrate_naam=tarieven[geen_id].naam if geen_id in tarieven else None,
        kandidaat=reden is not None,
        kandidaat_reden=reden,
    )


def haal_op(*, administratie_id: uuid.UUID) -> BtwPlichtigDto:
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BtwPlichtigFout(f"Onbekende administratie: {administratie_id}")
        return _dto(session, administratie)


def zet(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, btw_plichtig: bool, bron: str = BRON_MENS
) -> BtwPlichtigDto:
    """Beheerder (router) of de schrijvende CLI `btw-plichtig-zetten`: zet het kenmerk mét bron 'mens'. Audit oud→nieuw
    uitsluitend bij een wijziging (ook een herbevestiging van dezelfde stand zonder bron krijgt een audit: de bron
    verandert dan van NULL naar 'mens' — dát is de bevestiging die de detector laat zwijgen)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BtwPlichtigFout(f"Onbekende administratie: {administratie_id}")
        oud = {"btw_plichtig": administratie.btw_plichtig, "bron": administratie.btw_plichtig_bron}
        nieuw = {"btw_plichtig": btw_plichtig, "bron": bron}
        if oud != nieuw:
            administratie.btw_plichtig = btw_plichtig
            administratie.btw_plichtig_bron = bron
            administratie.btw_plichtig_gewijzigd_op = datetime.now(UTC)
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie=AUDIT_ACTIE,
                correlatie_id=uuid.uuid4(),
                oude_waarde=oud,
                nieuwe_waarde=nieuw,
                administratie_id=administratie_id,
            )
            session.flush()
        return _dto(session, administratie)


def volg_rlz_signaal(*, administratie_id: uuid.UUID, enable_tax_reporting: bool | None, actor_id: uuid.UUID) -> str:
    """Nachtelijke identiteit-sync: slaat het RLZ-signaal op; `true` bevestigt btw-plichtig (bron 'rlz') als er nog geen
    mens-keuze staat; `false` verandert het kenmerk nooit (detector). Geeft de stand terug: 'bevestigd_rlz' |
    'signaal_opgeslagen' | 'mens' | 'geen_signaal'."""
    if enable_tax_reporting is None:
        return "geen_signaal"
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BtwPlichtigFout(f"Onbekende administratie: {administratie_id}")
        nu = datetime.now(UTC)
        administratie.btw_plichtig_rlz_signaal = enable_tax_reporting
        administratie.btw_plichtig_rlz_gezien_op = nu
        if administratie.btw_plichtig_bron == BRON_MENS:
            return "mens"
        if enable_tax_reporting and (not administratie.btw_plichtig or administratie.btw_plichtig_bron != BRON_RLZ):
            oud = {"btw_plichtig": administratie.btw_plichtig, "bron": administratie.btw_plichtig_bron}
            administratie.btw_plichtig = True
            administratie.btw_plichtig_bron = BRON_RLZ
            administratie.btw_plichtig_gewijzigd_op = nu
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie=AUDIT_ACTIE,
                correlatie_id=uuid.uuid4(),
                oude_waarde=oud,
                nieuwe_waarde={"btw_plichtig": True, "bron": BRON_RLZ, "signaal": "EnableTaxReporting"},
                administratie_id=administratie_id,
            )
            return "bevestigd_rlz"
        return "signaal_opgeslagen"
