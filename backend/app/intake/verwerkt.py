"""Verwerkt-administratie van de intake-postvakken op Message-ID (migratie 0171; Peter 22-09 "er zijn facturen gemaild
die niet in onze module staan"; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE +
POSTVAKBEWAKING (Peter 22-09)").

Les: een gelezen-vlag is geen verwerkt-administratie. Wat de module verwerkt heeft staat hier per (kanaal, sleutel) —
sleutel = Message-ID, anders `uid:<map>:<uid>` — mét uitkomst (verwerkt / al_bekend / niet_verwerkbaar), postvak-map
(INBOX of spam) en de koppeling naar het `intake_bericht`. `bekend_toets(kanaal)` is de toets die de fetch vóór het
ophalen van de body doet: staat de sleutel hier óf als `intake_bericht.message_id` (welk kanaal dan ook — een via de
oude forward al verwerkte mail is hetzelfde bericht), dan wordt het bericht overgeslagen.

Alles hier is administratie-loos (`scoped_session(None)`); `intake_bericht` en deze tabel kennen geen RLS."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.betaalstatus import KANAAL_FACTUREN_KEMPENGROEP
from app.intake.models import IntakeBericht, IntakeBerichtVerwerkt

UITKOMST_VERWERKT = "verwerkt"
UITKOMST_AL_BEKEND = "al_bekend"
UITKOMST_NIET_VERWERKBAAR = "niet_verwerkbaar"
#: Audit-actie per job-run per kanaal — bron van de dagtellers "postvak" in de reconciliatiemail
#: (`app/reconciliatie/automatiseringen.py`, sleutel INTAKE_POSTVAK).
AUDIT_RUN = "intake_postvak_run"
AUDIT_NU_VERWERKEN = "intake_postvak_nu_verwerken"


def bekende_sleutels(kanaal: str) -> set[str]:
    """Alle sleutels die voor dit kanaal al verwerkt zijn: de verwerkt-tabel van dít kanaal ∪ élke `intake_bericht.
    message_id` (alle kanalen, alle bronnen — de .eml-upload van hetzelfde bericht telt óók als bekend)."""
    with scoped_session(None) as session:
        eigen = set(
            session.scalars(
                select(IntakeBerichtVerwerkt.message_id).where(IntakeBerichtVerwerkt.kanaal == kanaal)
            ).all()
        )
        berichten = set(
            session.scalars(select(IntakeBericht.message_id).where(IntakeBericht.message_id.is_not(None))).all()
        )
    return eigen | {m for m in berichten if m}


def bekend_toets(kanaal: str) -> Callable[[str], bool]:
    """Eén DB-lees per run (set), daarna O(1) per kop."""
    sleutels = bekende_sleutels(kanaal)
    return lambda sleutel: sleutel in sleutels


def registreer(
    *,
    kanaal: str,
    sleutel: str,
    uid: str | None,
    postvak_map: str,
    uitkomst: str,
    intake_bericht_id: uuid.UUID | None,
    detail: dict | None = None,
) -> None:
    """Idempotent op (kanaal, sleutel): een tweede registratie werkt de rij bij (uitkomst/bericht) i.p.v. te falen."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.scalars(
            select(IntakeBerichtVerwerkt).where(
                IntakeBerichtVerwerkt.kanaal == kanaal, IntakeBerichtVerwerkt.message_id == sleutel
            )
        ).first()
        if rij is None:
            session.add(
                IntakeBerichtVerwerkt(
                    kanaal=kanaal,
                    message_id=sleutel,
                    uid=uid,
                    postvak_map=postvak_map,
                    uitkomst=uitkomst,
                    intake_bericht_id=intake_bericht_id,
                    detail=detail,
                )
            )
        else:
            rij.uitkomst = uitkomst
            rij.uid = uid
            rij.postvak_map = postvak_map
            rij.intake_bericht_id = intake_bericht_id or rij.intake_bericht_id
            rij.detail = detail if detail is not None else rij.detail
            rij.verwerkt_op = datetime.now(UTC)


def dubbel_via_forward(intake_bericht_id: uuid.UUID) -> bool:
    """Overgangsperiode (forward nog aan): kwam dezelfde bijlage (sha256, `detail.bijlage_hashes`) al binnen via een
    ÁNDER kanaal? Dan is dit bericht een forward-dubbel — de duplicaat-afvoer handelt de documenten af (byte-identiek =
    `mogelijk_duplicaat_van` → afvoer; zelfde referentie+bedrag = duplicaat-afvoer), deze teller maakt het zichtbaar
    in de reconciliatiemail. Leest uitsluitend `intake_bericht` (platformbreed leesbaar, geen RLS-doorbraak)."""
    with scoped_session(None) as session:
        bericht = session.get(IntakeBericht, intake_bericht_id)
        if bericht is None:
            return False
        eigen = set((bericht.detail or {}).get("bijlage_hashes") or [])
        if not eigen:
            return False
        anderen = session.scalars(
            select(IntakeBericht.detail).where(
                IntakeBericht.kanaal != bericht.kanaal,
                IntakeBericht.id != intake_bericht_id,
                IntakeBericht.detail["bijlage_hashes"].is_not(None),
            )
        ).all()
    return any(eigen & set((d or {}).get("bijlage_hashes") or []) for d in anderen)


@dataclass(frozen=True)
class RunTelling:
    kanaal: str
    gezien: int = 0
    gezien_spam: int = 0
    verwerkt: int = 0
    al_bekend: int = 0
    niet_verwerkbaar: int = 0
    uit_spam: int = 0
    dubbel_via_forward: int = 0
    overgeslagen_bekend: int = 0
    venster_vanaf: str | None = None

    def als_dict(self) -> dict:
        return {
            "kanaal": self.kanaal,
            "gezien": self.gezien,
            "gezien_spam": self.gezien_spam,
            "verwerkt": self.verwerkt,
            "al_bekend": self.al_bekend,
            "niet_verwerkbaar": self.niet_verwerkbaar,
            "uit_spam": self.uit_spam,
            "dubbel_via_forward": self.dubbel_via_forward,
            "overgeslagen_bekend": self.overgeslagen_bekend,
            "venster_vanaf": self.venster_vanaf,
        }


def schrijf_run_audit(telling: RunTelling, *, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID) -> None:
    """Eén audit-rij per job-run per kanaal (administratie-loos) — de dagtellers verwacht/gedaan/overgeslagen in de
    reconciliatiemail lezen deze rij (principe 7 (6): geen stille no-op, ook een lege run laat een spoor)."""
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_bericht_verwerkt",
            record_id=uuid.uuid4(),  # administratie-loze run-rij: eigen id, geen tabelrecord
            actie=AUDIT_RUN,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=telling.als_dict(),
            administratie_id=None,
        )


@dataclass(frozen=True)
class SpamTreffer:
    kanaal: str
    sleutel: str
    afzender: str | None
    onderwerp: str | None
    verwerkt_op: datetime
    intake_bericht_id: uuid.UUID | None
    uitkomst: str


def spam_treffers(*, sinds: datetime) -> list[SpamTreffer]:
    """Berichten die uit de spam-map verwerkt zijn sinds `sinds` — voeding van de LET-OP `intake_uit_spam` (afzender +
    domein, zodat Peter de afzender in Workspace kan whitelisten)."""
    with scoped_session(None) as session:
        rijen = session.execute(
            select(IntakeBerichtVerwerkt, IntakeBericht.afzender, IntakeBericht.onderwerp)
            .outerjoin(IntakeBericht, IntakeBericht.id == IntakeBerichtVerwerkt.intake_bericht_id)
            .where(IntakeBerichtVerwerkt.postvak_map != "INBOX", IntakeBerichtVerwerkt.verwerkt_op >= sinds)
            .order_by(IntakeBerichtVerwerkt.verwerkt_op)
        ).all()
    uit: list[SpamTreffer] = []
    for rij, afzender, onderwerp in rijen:
        d = rij.detail or {}
        uit.append(
            SpamTreffer(
                kanaal=rij.kanaal,
                sleutel=rij.message_id,
                afzender=afzender or d.get("afzender"),
                onderwerp=onderwerp or d.get("onderwerp"),
                verwerkt_op=rij.verwerkt_op,
                intake_bericht_id=rij.intake_bericht_id,
                uitkomst=rij.uitkomst,
            )
        )
    return uit


def verwerkt_sinds(kanaal: str, *, sinds: datetime) -> dict[str, IntakeBerichtVerwerkt]:
    """Verwerkt-rijen van een kanaal sinds `sinds` op sleutel (bewaking: postvak-telling ↔ verwerkt)."""
    with scoped_session(None) as session:
        rijen = session.scalars(
            select(IntakeBerichtVerwerkt).where(
                IntakeBerichtVerwerkt.kanaal == kanaal, IntakeBerichtVerwerkt.verwerkt_op >= sinds
            )
        ).all()
        session.expunge_all()
    return {r.message_id: r for r in rijen}


def laatste_run_moment(kanaal: str) -> datetime | None:
    with scoped_session(None) as session:
        return session.scalar(
            select(func.max(IntakeBerichtVerwerkt.verwerkt_op)).where(IntakeBerichtVerwerkt.kanaal == kanaal)
        )


def is_kempengroep(kanaal: str) -> bool:
    return kanaal == KANAAL_FACTUREN_KEMPENGROEP


def gisteren_begin_utc(nu: datetime | None = None) -> datetime:
    """Begin van de NL-kalenderdag van gisteren, als UTC-tijdstip (bewakingsvenster 'sinds gisteren')."""
    from zoneinfo import ZoneInfo

    ams = ZoneInfo("Europe/Amsterdam")
    lokaal = (nu or datetime.now(UTC)).astimezone(ams)
    begin = (lokaal - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return begin.astimezone(UTC)
