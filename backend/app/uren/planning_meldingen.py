"""Bundelmelding "planning week N aangepast" aan veldwerkers (Peter/Haci 15-09, planning met terugwerkende kracht).

Het kantoor wijzigt de planning in een verstreken of lopende week → `planning.py` legt per (administratie, veldwerker,
week) één OPEN rij in `planning_wijziging_melding` (aantal_wijzigingen++). Deze job (stap in de bestaande 10-min-job
`rlz-nieuwe-facturen`, zelfde stille uren 20:00–08:00) bundelt per persoon × week tot één push-anders-mail
(`app/berichten/verzending.py`, deep-link `/accordeur?planning=<jaar>-W<week>` — de veld-app opent die week in de
planningweergave) en zet `gemeld_op` + `kanaal`. Geen kanaal / mislukt = rij blijft open, zichtbaar in de job-uitvoer.
Geen melding per kaartje, nooit voor een toekomstige week."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.berichten.nieuwe_facturen import in_stille_uren
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.uren.models import PlanningWijzigingMelding

logger = logging.getLogger(__name__)

MODULE = "boekhouding"


@dataclass
class PlanningMeldingRapport:
    stille_uren: bool = False
    kandidaten: int = 0  # open rijen
    berichten: int = 0  # gebundelde berichten (persoon × week)
    verzonden_push: int = 0
    verzonden_mail: int = 0
    overgeslagen_geen_kanaal: int = 0
    mislukt: int = 0
    fouten: list[str] = field(default_factory=list)


def bericht_teksten(jaar: int, week: int, *, aantal: int, administratie_namen: list[str]) -> tuple[str, str, str, str]:
    pad = f"/accordeur?planning={jaar}-W{week:02d}"
    onderwerp = f"Planning week {week} aangepast"
    waar = f" ({', '.join(administratie_namen)})" if administratie_namen else ""
    pushtekst = f"Je planning van week {week} is aangepast{waar} — bekijk de app."
    link = f"{settings.app_basis_url.rstrip('/')}{pad}"
    mailtekst = (
        "Beste,\n\n"
        f"Het kantoor heeft je planning van week {week} aangepast "
        f"({aantal} wijziging{'en' if aantal != 1 else ''}){waar}.\n\n"
        f"Open de app om de planning te bekijken:\n{link}\n\n"
        "Uren die al gekeurd zijn blijven staan; vul ontbrekende uren gewoon in op het juiste project.\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst, pad


def _open_rijen() -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, int, int, int]]:
    """(rij_id, administratie_id, gebruiker_id, administratie_naam, jaar, week, aantal) van alle open rijen — per
    administratie gescoopt (RLS), alleen actieve administraties."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        administraties = list(
            session.execute(select(Administratie.id, Administratie.naam).where(Administratie.actief.is_(True))).all()
        )
    uit: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, int, int, int]] = []
    for aid, naam in administraties:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            for rij in session.scalars(
                select(PlanningWijzigingMelding).where(
                    PlanningWijzigingMelding.administratie_id == aid, PlanningWijzigingMelding.gemeld_op.is_(None)
                )
            ):
                uit.append(
                    (rij.id, aid, rij.gebruiker_id, naam, rij.jaar, rij.weeknummer, int(rij.aantal_wijzigingen or 1))
                )
    return uit


def verstuur_planning_meldingen(*, nu: datetime | None = None) -> PlanningMeldingRapport:
    rapport = PlanningMeldingRapport()
    if in_stille_uren(nu):
        rapport.stille_uren = True
        return rapport
    rijen = _open_rijen()
    rapport.kandidaten = len(rijen)
    if not rijen:
        return rapport
    # Bundelen per (veldwerker, jaar, week) over administraties heen — één bericht.
    bundels: dict[tuple[uuid.UUID, int, int], list[tuple[uuid.UUID, uuid.UUID, str, int]]] = {}
    for rij_id, aid, gebruiker_id, adm_naam, jaar, week, aantal in rijen:
        bundels.setdefault((gebruiker_id, jaar, week), []).append((rij_id, aid, adm_naam, aantal))
    rapport.berichten = len(bundels)
    for (gebruiker_id, jaar, week), delen in bundels.items():
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            gebruiker = session.get(Gebruiker, gebruiker_id)
            if gebruiker is not None:
                session.expunge(gebruiker)
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
            # Geblokkeerd/gearchiveerd: niets sturen, rij afsluiten mét reden (geen eeuwige herkansing).
            _sluit_af(delen, kanaal="geen", detail="veldwerker niet actief")
            rapport.overgeslagen_geen_kanaal += 1
            continue
        onderwerp, pushtekst, mailtekst, pad = bericht_teksten(
            jaar, week, aantal=sum(a for _, _, _, a in delen), administratie_namen=sorted({n for _, _, n, _ in delen})
        )
        try:
            uitkomst = verzending.verstuur_push_anders_mail(
                gebruiker, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url=pad
            )
        except Exception as exc:  # noqa: BLE001 — nooit stil, job herkanst
            rapport.mislukt += 1
            rapport.fouten.append(f"planning-melding {gebruiker_id} week {week}: {exc}")
            continue
        if uitkomst.status == HerinneringStatus.VERZONDEN:
            if uitkomst.kanaal == HerinneringKanaal.PUSH:
                rapport.verzonden_push += 1
            else:
                rapport.verzonden_mail += 1
            _sluit_af(delen, kanaal=str(uitkomst.kanaal.value if uitkomst.kanaal else "?"), detail=None)
        elif uitkomst.status == HerinneringStatus.OVERGESLAGEN:
            rapport.overgeslagen_geen_kanaal += 1
            _sluit_af(delen, kanaal="geen", detail=str(uitkomst.detail))
        else:
            rapport.mislukt += 1
            rapport.fouten.append(f"planning-melding {gebruiker_id} week {week}: {uitkomst.detail}")
    return rapport


def _sluit_af(delen: list[tuple[uuid.UUID, uuid.UUID, str, int]], *, kanaal: str, detail: str | None) -> None:
    nu = datetime.now(UTC)
    for rij_id, aid, _naam, _aantal in delen:
        # RLS: de tabel is per administratie gescoopt — altijd in de scope van de eigen administratie schrijven.
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            rij = session.get(PlanningWijzigingMelding, rij_id)
            if rij is None or rij.gemeld_op is not None:
                continue
            rij.gemeld_op = nu
            rij.kanaal = kanaal
            rij.detail = {**(rij.detail or {}), **({"uitkomst": detail} if detail else {})}
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module=MODULE,
                tabel="planning_wijziging_melding",
                record_id=rij.id,
                actie="planning_wijziging_gemeld",
                correlatie_id=rij.gebruiker_id,
                nieuwe_waarde={
                    "gebruiker_id": str(rij.gebruiker_id),
                    "jaar": rij.jaar,
                    "weeknummer": rij.weeknummer,
                    "aantal_wijzigingen": rij.aantal_wijzigingen,
                    "kanaal": kanaal,
                    **({"detail": detail} if detail else {}),
                },
                administratie_id=aid,
            )
