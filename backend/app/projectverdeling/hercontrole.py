"""Hercontrole van geboekte pro-rato-verdelingen (ontwerpnotitie ⑥): de omzetstand van DEZELFDE maand kan ná het
boeken nog wijzigen (nagekomen verkoopfactuur, creditnota). De job rekent de verdeling opnieuw uit tegen de
actuele omzetstand; afwijking = max |deel_nieuw − deel_oud| / restant (in %). Boven de administratie-drempel
(`projectverdeling_drempel_pct`, default 5) = SIGNAAL mét actie: `hercontrole_verdeling` gevuld, tijdlijnregel
`projectverdeling_afwijking` (eenmalig per signaal — idempotent), audit; de rij-chip "verdeling wijkt x % af" en
de banner "Herverdelen…" lezen hieruit. Onder de drempel wordt alleen `hercontrole_op` + het percentage ververst.

Cadans (deterministisch, idempotent): maandelijks meeliftend in `sync-alles` — doorrekenen op de 1e–7e van de maand,
óf als `hercontrole_op` ouder is dan de laatste geslaagde cijfers-sync van de administratie, óf geforceerd (los
CLI-commando `projectverdeling-hercontrole`). Puur code, geen RLZ-/Odoo-calls."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus, Tegenboeking
from app.projectverdeling import data as pv
from app.projectverdeling.models import Projectverdeling
from app.projectverdeling.omzet import laatste_cijfers_sync, omzet_per_project, projectnamen

logger = logging.getLogger(__name__)

MAANDVENSTER_DAGEN = 7  # 1e–7e van de maand: de maandelijkse ronde


def moet_herrekenen(
    *, hercontrole_op: datetime | None, laatste_sync: datetime | None, vandaag: date, forceer: bool
) -> bool:
    """Pure cadans-regel: geforceerd; nog nooit gecontroleerd; in het maandvenster nog niet deze maand
    gecontroleerd; óf er zijn sindsdien verse cijfers."""
    if forceer or hercontrole_op is None:
        return True
    if vandaag.day <= MAANDVENSTER_DAGEN and (hercontrole_op.year, hercontrole_op.month) != (
        vandaag.year,
        vandaag.month,
    ):
        return True
    return laatste_sync is not None and hercontrole_op < laatste_sync


def _al_tegengeboekt(session: Session, row: Projectverdeling) -> bool:
    if row.boek_cyclus is None:
        return False
    return session.get(Tegenboeking, (row.document_id, row.boek_cyclus)) is not None


def herbereken_administratie(
    *, administratie_id: uuid.UUID, vandaag: date | None = None, forceer: bool = False
) -> dict:
    vandaag = vandaag or date.today()
    nu = datetime.now(UTC)
    tellers = {"beoordeeld": 0, "herrekend": 0, "signalen": 0, "overgeslagen": 0}
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        drempel = administratie.projectverdeling_drempel_pct if administratie else Decimal("5.00")
        laatste_sync = laatste_cijfers_sync(session, administratie_id=administratie_id)
        rijen = session.scalars(
            select(Projectverdeling)
            .join(Document, Document.id == Projectverdeling.document_id)
            .where(
                Projectverdeling.administratie_id == administratie_id,
                Projectverdeling.status == pv.STATUS_GEBOEKT,
                Projectverdeling.pro_rato_periode.is_not(None),
                Document.status == DocumentStatus.GEBOEKT,
            )
        ).all()
        omzet_cache: dict[date, list[pv.Omzetstand]] = {}
        for row in rijen:
            tellers["beoordeeld"] += 1
            if not moet_herrekenen(
                hercontrole_op=row.hercontrole_op, laatste_sync=laatste_sync, vandaag=vandaag, forceer=forceer
            ):
                tellers["overgeslagen"] += 1
                continue
            if _al_tegengeboekt(session, row) or row.pro_rato_bedrag is None or row.pro_rato_periode is None:
                tellers["overgeslagen"] += 1
                continue
            periode = row.pro_rato_periode
            if periode not in omzet_cache:
                omzet_cache[periode] = omzet_per_project(
                    session, administratie_id=administratie_id, periode=periode
                ).standen
            standen = omzet_cache[periode]
            oud = pv.delen_uit_json(row.verdeling)
            vast = [d for d in oud if d.wijze == pv.WIJZE_VAST]
            if not standen:
                # Geen enkel project mét omzet meer in die maand: er is geen nieuwe verdeling te berekenen — niet
                # stil, maar ook geen vals signaal met een halve verdeling (log + overgeslagen-teller).
                logger.warning("Hercontrole %s: geen omzet meer in %s — overgeslagen", row.document_id, periode)
                tellers["overgeslagen"] += 1
                continue
            try:
                nieuw_pro_rato = pv.verdeel_pro_rato(row.pro_rato_bedrag, standen)
            except Exception as exc:  # noqa: BLE001 — één kapotte rij stopt de ronde niet
                logger.warning("Hercontrole overgeslagen voor %s: %s", row.document_id, exc)
                tellers["overgeslagen"] += 1
                continue
            nieuw = [*vast, *nieuw_pro_rato]
            pct = pv.afwijking_pct(oud, nieuw, row.pro_rato_bedrag)
            was_signaal = row.hercontrole_verdeling is not None
            vorige_pct = row.hercontrole_afwijking_pct
            row.hercontrole_op = nu
            row.hercontrole_afwijking_pct = pct
            tellers["herrekend"] += 1
            if pct > drempel:
                row.hercontrole_verdeling = pv.delen_naar_json(nieuw)
                tellers["signalen"] += 1
                if not was_signaal or vorige_pct != pct:
                    _signaleer(
                        session, administratie_id=administratie_id, row=row, pct=pct, drempel=drempel, standen=standen
                    )
            else:
                row.hercontrole_verdeling = None
                if was_signaal:
                    _signaal_weg(session, administratie_id=administratie_id, row=row, pct=pct, drempel=drempel)
    return tellers


def _signaleer(
    session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, pct, drempel, standen: list[pv.Omzetstand]
) -> None:
    document = session.get(Document, row.document_id)
    assert document is not None
    namen = projectnamen(session, administratie_id=administratie_id, project_ids={s.project_id for s in standen})
    periode = pv.periode_label(row.pro_rato_periode) if row.pro_rato_periode else "?"
    reden = (
        f"hercontrole: omzet {periode} is ná het boeken gewijzigd — de projectverdeling wijkt nu {pct} % af "
        f"(drempel {drempel} %); herverdelen = tegenboeken + nieuwe verdeling, mens bevestigt"
    )
    detail = {
        "projectverdeling_afwijking": {
            "afwijking_pct": str(pct),
            "drempel_pct": str(drempel),
            "periode": row.pro_rato_periode.isoformat() if row.pro_rato_periode else None,
            "nieuwe_verdeling": row.hercontrole_verdeling,
            "omzetstanden_nu": [
                {"project_id": str(s.project_id), "omzet": str(s.omzet), "naam": namen.get(s.project_id)}
                for s in standen
            ],
        },
        "reden": reden,
    }
    session.add(
        DocumentGebeurtenis(
            document_id=row.document_id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=SYSTEEM_ACTOR_ID,
            detail=detail,
        )
    )
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_afwijking",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verdeling": row.verdeling},
        nieuwe_waarde=detail["projectverdeling_afwijking"],
        administratie_id=administratie_id,
    )


def _signaal_weg(session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, pct, drempel) -> None:
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=row.document_id,
        actie="projectverdeling_afwijking_vervallen",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"afwijking_pct": str(pct), "drempel_pct": str(drempel)},
        administratie_id=administratie_id,
    )


def herbereken_alle(*, vandaag: date | None = None, forceer: bool = False) -> dict[uuid.UUID, dict | str]:
    """Alle actieve administraties; één kapotte administratie stopt de rest niet (fout = leesbare string)."""
    with scoped_session(None) as session:
        ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    resultaten: dict[uuid.UUID, dict | str] = {}
    for administratie_id in ids:
        try:
            resultaten[administratie_id] = herbereken_administratie(
                administratie_id=administratie_id, vandaag=vandaag, forceer=forceer
            )
        except Exception as exc:  # noqa: BLE001 — zichtbaar in het rapport, nooit stil
            logger.exception("Projectverdeling-hercontrole mislukt voor %s", administratie_id)
            resultaten[administratie_id] = str(exc)
    return resultaten
