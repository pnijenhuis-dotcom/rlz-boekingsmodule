"""Opbouw van de registersnapshot (koppelcontract §8 v1.18): read-only, deterministisch, geen
LLM, geen filtering behalve de actuele-rijen-semantiek.

- Administraties: ONGEFILTERD — álle rijen uit platform.administratie, óók niet-is_vastgoed en
  niet-actief (kip-ei: Vastly's koppelscherm komt vóór onze toggle; `actief` reist mee als veld).
- Grootboek: uitsluitend ACTUELE rijen (`verdwenen_uit_bron_op IS NULL`) voor álle
  administraties. Afwezigheid in de snapshot = verdwenen in de bron; Vastly markeert/archiveert
  daarop, verwijdert nooit hard.

RLS-les (Platform/OPEN_ITEMS S2-levering 27-08): `grootboekrekening_scope` heeft FORCE RLS zónder
Beheerder-bypass — ook de app-rol ziet zonder scope nul rijen. De export leest daarom per
administratie met de transactie-lokale scope `app.current_administratie_id` (set_config
is_local=true, het SET LOCAL-equivalent), exact het patroon van de S2-exportscripts. Bewust ÉÉN
transactie voor de hele snapshot, `REPEATABLE READ` + `READ ONLY`: alle registerdelen komen uit
dezelfde snapshot van de database (een gelijktijdige sync kan geen half-bijgewerkte levering
veroorzaken) en de DB weigert elke schrijfactie hard — "geen mutaties" is zo niet alleen een
belofte in code maar een eigenschap van de transactie. De scope wisselt binnen die transactie
per administratie (herhaald set_config), wat hier veilig is omdat de transactie niets anders
doet dan lezen.

Sorteervolgorde is vast (administraties op naam+id, grootboek op administratie_id+code+ledger_id)
zodat twee snapshots van dezelfde stand byte-voor-byte gelijk zijn op generated_at na."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import app.db.session as db_session
from app.config import settings
from app.db.models import Administratie, Grootboekrekening
from app.registersync.schemas import (
    AdministratieRij,
    GrootboekrekeningRij,
    Registerdeel,
    RegisterSnapshot,
)

logger = logging.getLogger(__name__)


def _zet_scope(session: Session, administratie_id) -> None:
    session.execute(
        text("SELECT set_config('app.current_administratie_id', :value, true)"),
        {"value": str(administratie_id)},
    )


def bouw_snapshot() -> tuple[RegisterSnapshot, int]:
    """Levert (snapshot, opbouwduur in ms). Read-only: een schrijfpoging binnen deze transactie
    faalt op DB-niveau (READ ONLY)."""
    start = time.perf_counter()
    generated_at = datetime.now(UTC)
    session: Session = db_session.SessionLocal()
    try:
        # Moet het éérste statement van de transactie zijn (PostgreSQL-eis) — daarom niet via
        # scoped_session(), dat eerst set_config uitvoert.
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))

        # v1.19 (30-08): gearchiveerde administraties reizen niet mee — afwezigheid = verdwenen (§8-
        # semantiek, Vastly markeert, verwijdert niets); niet-gearchiveerde actief=false-rijen wél
        # (kip-ei koppelscherm, ongewijzigd).
        administraties = session.execute(
            select(Administratie.id, Administratie.rlz_admin_id, Administratie.naam, Administratie.actief)
            .where(Administratie.gearchiveerd_op.is_(None))
            .order_by(Administratie.naam, Administratie.id)
        ).all()
        # inbox_adres (v1.19-notitie (2), verzoek Vastly 31-08): het éne centrale intake-adres
        # (config `intake_postvak_adres`, geen per-administratie datamodel) reist mee op élke
        # ACTIEVE rij; op een niet-actieve rij en zonder geconfigureerd adres blijft het veld
        # wég (= geen uitspraak, Vastly raakt de cache niet aan — nooit een onbedoelde "leeg").
        inbox_adres = (settings.intake_postvak_adres or "").strip() or None
        admin_rijen = [
            AdministratieRij(
                id=r.id,
                rlz_admin_id=r.rlz_admin_id,
                naam=r.naam,
                actief=r.actief,
                **({"inbox_adres": inbox_adres} if inbox_adres and r.actief else {}),
            )
            for r in administraties
        ]

        gb_rijen: list[GrootboekrekeningRij] = []
        jongste_sync: datetime | None = None
        for adm in administraties:
            _zet_scope(session, adm.id)
            rijen = session.execute(
                select(
                    Grootboekrekening.ledger_id,
                    Grootboekrekening.administratie_id,
                    Grootboekrekening.code,
                    Grootboekrekening.naam,
                    Grootboekrekening.soort,
                    Grootboekrekening.is_totaalrekening,
                    Grootboekrekening.laatst_gesynchroniseerd,
                )
                .where(
                    Grootboekrekening.administratie_id == adm.id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                )
                .order_by(Grootboekrekening.code, Grootboekrekening.ledger_id)
            ).all()
            for r in rijen:
                gb_rijen.append(
                    GrootboekrekeningRij(
                        ledger_id=r.ledger_id,
                        administratie_id=r.administratie_id,
                        code=r.code,
                        naam=r.naam,
                        soort=r.soort,
                        is_totaalrekening=r.is_totaalrekening,
                    )
                )
                if r.laatst_gesynchroniseerd is not None and (
                    jongste_sync is None or r.laatst_gesynchroniseerd > jongste_sync
                ):
                    jongste_sync = r.laatst_gesynchroniseerd
        session.rollback()  # read-only: niets te committen, scope-instellingen opruimen
    finally:
        session.close()

    snapshot = RegisterSnapshot(
        generated_at=generated_at,
        bron_laatst_gesynchroniseerd_op=jongste_sync,
        administraties=Registerdeel[AdministratieRij](aantal=len(admin_rijen), rijen=admin_rijen),
        grootboekrekeningen=Registerdeel[GrootboekrekeningRij](aantal=len(gb_rijen), rijen=gb_rijen),
    )
    duur_ms = int((time.perf_counter() - start) * 1000)
    return snapshot, duur_ms
