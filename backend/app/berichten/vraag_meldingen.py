"""Melding "vraag van het kantoor" aan de klant-accordeur (blok B5 26-08): bij élke beurt-wissel
naar een accordeur (vraag gesteld / kantoor antwoordt) via de bestaande push-anders-mail-kanalen,
mét de stille uren van de bundelmelding (20:00–08:00 Europe/Amsterdam). Idempotent per beurt:
`vraag.accordeur_gemeld_op >= vraag.aan_de_beurt_sinds` = al gemeld. Aanroep direct vanuit de
dialoog (buiten de transactie) én vanuit de 10-min-job `rlz-nieuwe-facturen` (vangt de stille
uren en mislukte pogingen op). Deep-link = `/accordeur?vraag=<id>` — antwoorden gebeurt ín de app."""

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
from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Vraag, VraagStatus

logger = logging.getLogger(__name__)


@dataclass
class VraagMeldingRapport:
    stille_uren: bool = False
    kandidaten: int = 0
    verzonden_push: int = 0
    verzonden_mail: int = 0
    overgeslagen_geen_kanaal: int = 0
    mislukt: int = 0
    fouten: list[str] = field(default_factory=list)


def bericht_teksten(vraag_id: uuid.UUID, *, eerste_keer: bool) -> tuple[str, str, str, str]:
    pad = f"/accordeur?vraag={vraag_id}"
    onderwerp = "Vraag van het kantoor over een factuur" if eerste_keer else "Reactie van het kantoor op uw vraag"
    pushtekst = (
        "Het kantoor heeft een vraag over een factuur — u bent aan de beurt."
        if eerste_keer
        else "Het kantoor heeft gereageerd in uw vraag-dialoog — u bent aan de beurt."
    )
    link = f"{settings.app_basis_url.rstrip('/')}{pad}"
    mailtekst = (
        "Beste,\n\n"
        + ("Het kantoor heeft een vraag over een factuur.\n\n" if eerste_keer else "Het kantoor heeft gereageerd in uw vraag-dialoog.\n\n")
        + f"Open de app om te antwoorden:\n{link}\n\n"
        "Deze link opent alleen de app — antwoorden gebeurt ín de app, na ontgrendelen.\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst, pad


def _kandidaten(
    vraag_id: uuid.UUID | None, administratie_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool]]:
    """(vraag_id, administratie_id, accordeur_id, eerste_keer) voor open vragen waarvan de beurt bij
    een actieve klant-accordeur ligt en die voor deze beurt nog niet gemeld zijn. Per administratie
    gescoopt (RLS-les 25-08: `vraag` heeft RLS, een scope-loze sessie ziet als niet-Beheerder
    niets) — zelfde patroon als de bundelmelding."""
    if administratie_id is not None:
        administratie_ids = [administratie_id]
    else:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    uit: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool]] = []
    for aid in administratie_ids:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            query = (
                select(Vraag, Gebruiker)
                .join(Gebruiker, Gebruiker.id == Vraag.aan_de_beurt)
                .where(
                    Vraag.administratie_id == aid,
                    Vraag.status == VraagStatus.OPEN.value,
                    Gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR,
                    Gebruiker.status == GebruikerStatus.ACTIEF,
                    Vraag.aan_de_beurt_sinds.isnot(None),
                )
            )
            if vraag_id is not None:
                query = query.where(Vraag.id == vraag_id)
            for vraag, gebruiker in session.execute(query):
                if vraag.accordeur_gemeld_op is not None and vraag.accordeur_gemeld_op >= vraag.aan_de_beurt_sinds:
                    continue
                uit.append((vraag.id, aid, gebruiker.id, vraag.accordeur_gemeld_op is None))
    return uit


def verstuur_vraag_meldingen(
    *, nu: datetime | None = None, vraag_id: uuid.UUID | None = None, administratie_id: uuid.UUID | None = None
) -> VraagMeldingRapport:
    rapport = VraagMeldingRapport()
    if in_stille_uren(nu):
        rapport.stille_uren = True
        return rapport
    kandidaten = _kandidaten(vraag_id, administratie_id)
    rapport.kandidaten = len(kandidaten)
    # Badge-count (D4, 01-09): het aantal openstaande accorderingen per accordeur reist mee in de push.
    from app.berichten.herinneringen import open_aantallen_per_accordeur

    try:
        badges = open_aantallen_per_accordeur()
    except Exception:  # noqa: BLE001 — badge is gemak; een telfout mag de melding niet blokkeren
        badges = {}
    for v_id, administratie_id, accordeur_id, eerste_keer in kandidaten:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            gebruiker = session.get(Gebruiker, accordeur_id)
            session.expunge(gebruiker)
        onderwerp, pushtekst, mailtekst, pad = bericht_teksten(v_id, eerste_keer=eerste_keer)
        try:
            uitkomst = verzending.verstuur_push_anders_mail(
                gebruiker,
                onderwerp=onderwerp,
                pushtekst=pushtekst,
                mailtekst=mailtekst,
                url=pad,
                extra_payload={"badge": badges.get(accordeur_id, 0)},
            )
        except Exception as exc:  # noqa: BLE001 — nooit stil, job herkanst
            rapport.mislukt += 1
            rapport.fouten.append(f"vraag {v_id}: {exc}")
            continue
        if uitkomst.status == HerinneringStatus.VERZONDEN:
            if uitkomst.kanaal == HerinneringKanaal.PUSH:
                rapport.verzonden_push += 1
            else:
                rapport.verzonden_mail += 1
        elif uitkomst.status == HerinneringStatus.OVERGESLAGEN:
            rapport.overgeslagen_geen_kanaal += 1
        else:
            rapport.mislukt += 1
            rapport.fouten.append(f"vraag {v_id}: {uitkomst.detail}")
            continue
        # Gemeld (of geen kanaal — dan blijft herhalen zinloos tot de volgende beurt): vastleggen.
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            vraag = session.get(Vraag, v_id)
            if vraag is None:
                continue
            vraag.accordeur_gemeld_op = datetime.now(UTC)
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="vraag",
                record_id=v_id,
                actie="vraag_accordeur_gemeld",
                correlatie_id=v_id,
                nieuwe_waarde={
                    "accordeur": str(accordeur_id),
                    "status": uitkomst.status.value,
                    "kanaal": uitkomst.kanaal.value if uitkomst.kanaal else None,
                    "eerste_keer": eerste_keer,
                },
                administratie_id=administratie_id,
            )
    return rapport
