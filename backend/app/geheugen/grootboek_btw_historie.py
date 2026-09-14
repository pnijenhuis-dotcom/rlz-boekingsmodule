"""Btw-default per grootboekrekening AFGELEID UIT DE HISTORIE (vervolg-opdracht Cowork/Peter 14-09; migratie 0143).

Aanleiding: STAP-0 14-09 — RLZ's `Account.PreferentialTaxRate` (0142, `btw_bron='grootboek'`) is in álle gemeten
administraties null en Peter vult dat niet in RLZ voor 71 administraties. De module leidt de default daarom zelf af:

    per administratie × grootboekrekening de verdeling van het btw-tarief over de inkoopregels in het
    boekingsgeheugen (`boeking_observatie`: RLZ-seed + app-boekingen — beide zijn échte boekingen; bron_datum in de
    laatste `HISTORIE_MAANDEN` maanden). Regel (bindend, opdrachttekst):
        n ≥ MIN_REGELS (5)  én  het meest voorkomende tarief ≥ MIN_AANDEEL (90 %)  →  historie-default.
    Anders geen default; `n` en het hoogste aandeel worden wél vastgelegd (rapport "geen — 10 regels, hoogste 80 %").

Deterministisch (code, geen AI). Geen extra RLZ-verkeer: dezelfde cache die de boekingsgeheugen-seed vult. Regels
zonder btw-tarief (btw_id NULL) tellen niet mee — een leeg tarief is geen keuze. Loopt nachtelijk in `sync-alles`
(`herbereken_alle`) en ná de eerste sync van een administratie (`herbereken_voor`); alleen gewijzigde rijen worden
geschreven, een rekening zonder regels in het venster gaat terug naar NULL (nooit een stale default).

Winnaarsvolgorde (app/documenten/regel_prefill.py): … → grootboek-default uit RLZ (`grootboek`) → grootboek-default uit
historie (`grootboek_historie`, ORANJE "meestal op deze rekening (n×)") → administratie-default → leeg. Oranje volgens
de seed-only-regel: pas een app-bevestiging via het bestaande leverancier-geheugen maakt 'm groen — geen nieuwe kleurregel.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.geheugen.models import BoekingObservatie
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

#: Venster van de historie (opdrachttekst: "laatste 24 maanden") — als kalenderdagen, zelfde maand-benadering als de seed.
HISTORIE_MAANDEN = 24
HISTORIE_DAGEN = HISTORIE_MAANDEN * 31
#: Drempels (opdrachttekst): minstens vijf regels én één tarief op minstens 90 %.
MIN_REGELS = 5
MIN_AANDEEL = Decimal("0.90")
_AANDEEL_PRECISIE = Decimal("0.0001")


@dataclass(frozen=True)
class HistorieDefault:
    """Uitkomst per grootboekrekening: `taxrate_id` None = geen default; `n`/`aandeel` beschrijven de verdeling."""

    taxrate_id: uuid.UUID | None
    n: int
    aandeel: Decimal


def bepaal_default(tellingen: dict[uuid.UUID, int]) -> HistorieDefault | None:
    """Puur: {taxrate_id: aantal regels} → HistorieDefault (None als er geen regels zijn). Bij een gelijke stand tussen
    tarieven wint niemand op aandeel (< 90 % bij ≥ 2 tarieven), dus de tie-break is nooit bepalend voor de default —
    voor `aandeel` telt de hoogste, gesorteerd op id voor een stabiele uitkomst."""
    tellingen = {tid: int(n) for tid, n in tellingen.items() if tid is not None and n > 0}
    n = sum(tellingen.values())
    if n == 0:
        return None
    winnaar, hoogste = max(tellingen.items(), key=lambda kv: (kv[1], str(kv[0])))
    aandeel = (Decimal(hoogste) / Decimal(n)).quantize(_AANDEEL_PRECISIE, rounding=ROUND_HALF_UP)
    if n >= MIN_REGELS and Decimal(hoogste) / Decimal(n) >= MIN_AANDEEL:
        return HistorieDefault(taxrate_id=winnaar, n=n, aandeel=aandeel)
    return HistorieDefault(taxrate_id=None, n=n, aandeel=aandeel)


def tellingen_per_rekening(
    session: Session, *, administratie_id: uuid.UUID, vandaag: date
) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    """{gb_id: {taxrate_id: n}} over de inkoopregels in het venster — één groepsquery, geen N+1."""
    vanaf = vandaag - timedelta(days=HISTORIE_DAGEN)
    rijen = session.execute(
        select(BoekingObservatie.gb_id, BoekingObservatie.btw_id, func.count())
        .where(
            BoekingObservatie.administratie_id == administratie_id,
            BoekingObservatie.btw_id.is_not(None),
            BoekingObservatie.bron_datum >= vanaf,
        )
        .group_by(BoekingObservatie.gb_id, BoekingObservatie.btw_id)
    ).all()
    uit: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for gb_id, btw_id, n in rijen:
        uit.setdefault(gb_id, {})[btw_id] = int(n)
    return uit


@dataclass(frozen=True)
class HistorieRapport:
    administratie_id: uuid.UUID
    rekeningen: int  # rekeningen in de bron (niet verdwenen)
    met_default: int
    zonder_default_met_regels: int
    gewijzigd: int
    observaties: int  # inkoopregels mét tarief in het venster
    voorbeelden: list[str] = field(default_factory=list)


def herbereken_voor(administratie_id: uuid.UUID, *, vandaag: date | None = None) -> HistorieRapport:
    """Eén administratie: leest de tellingen, schrijft per rekening `historie_taxrate_*` — alleen bij een wijziging;
    rekeningen zonder regels in het venster gaan terug naar NULL. Puur code, geen RLZ-/Odoo-calls."""
    vandaag = vandaag or vandaag_nl()
    nu = datetime.now(UTC)
    met_default = zonder_met_regels = gewijzigd = observaties = 0
    voorbeelden: list[str] = []
    with scoped_session(administratie_id) as session:
        tellingen = tellingen_per_rekening(session, administratie_id=administratie_id, vandaag=vandaag)
        observaties = sum(sum(t.values()) for t in tellingen.values())
        rekeningen = list(
            session.scalars(
                select(Grootboekrekening).where(
                    Grootboekrekening.administratie_id == administratie_id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                )
            )
        )
        for rekening in rekeningen:
            uitkomst = bepaal_default(tellingen.get(rekening.ledger_id, {}))
            nieuw = (
                (uitkomst.taxrate_id, uitkomst.n, uitkomst.aandeel) if uitkomst is not None else (None, None, None)
            )
            if uitkomst is not None:
                if uitkomst.taxrate_id is not None:
                    met_default += 1
                else:
                    zonder_met_regels += 1
            oud = (rekening.historie_taxrate_id, rekening.historie_taxrate_n, rekening.historie_taxrate_aandeel)
            if oud != nieuw:
                rekening.historie_taxrate_id, rekening.historie_taxrate_n, rekening.historie_taxrate_aandeel = nieuw
                rekening.historie_berekend_op = nu
                gewijzigd += 1
                if len(voorbeelden) < 5 and uitkomst is not None and uitkomst.taxrate_id is not None:
                    voorbeelden.append(f"{rekening.code}: {uitkomst.n}× {uitkomst.aandeel * 100:.0f} %")
            elif rekening.historie_berekend_op is None and uitkomst is not None:
                rekening.historie_berekend_op = nu
    rapport = HistorieRapport(
        administratie_id=administratie_id,
        rekeningen=len(rekeningen),
        met_default=met_default,
        zonder_default_met_regels=zonder_met_regels,
        gewijzigd=gewijzigd,
        observaties=observaties,
        voorbeelden=voorbeelden,
    )
    logger.info(
        "Btw-default uit historie %s: %s rekeningen, %s met default, %s zonder (wel regels), %s gewijzigd, %s regels",
        administratie_id,
        rapport.rekeningen,
        rapport.met_default,
        rapport.zonder_default_met_regels,
        rapport.gewijzigd,
        rapport.observaties,
    )
    return rapport


def herbereken_alle(*, vandaag: date | None = None) -> dict[uuid.UUID, HistorieRapport | str]:
    """Alle actieve administraties (sync-alles, nachtelijk): één kapotte administratie stopt de rest niet — de fout
    is de leesbare waarde in het resultaat (zichtbaar in de job-uitvoer, exit 1)."""
    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    uit: dict[uuid.UUID, HistorieRapport | str] = {}
    for administratie_id in administratie_ids:
        try:
            uit[administratie_id] = herbereken_voor(administratie_id, vandaag=vandaag)
        except Exception as exc:  # noqa: BLE001 — per administratie zichtbaar, de rest gaat door
            logger.exception("Btw-default uit historie mislukt voor %s", administratie_id)
            uit[administratie_id] = f"{type(exc).__name__}: {exc}"
    return uit
