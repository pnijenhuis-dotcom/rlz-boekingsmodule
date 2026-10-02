"""Reconciliatieblok `webhooks` (run A 02-10 punt 17, Peter 02-10; BESLISSINGEN "RUN A 02-10 — BOEKEN, PROJECTEN,
MELDINGEN, KLEINE BUGS (Peter 02-10)"): élke outbox-rij die op de ontvanger wacht is één bevinding mét handeling.

Aanleiding: Vastly antwoordt sinds 24-09 `409 niet_koppelbaar` als een event (nog) niet te koppelen is (koppelcontract
§3c, voorstel-3c-409); tot 02-10 viel dat onder de gewone retry en stond het event ná ≈ 2 uur stil als dead-letter
`mislukt`. Er is geen outbox-scherm in de kantoor-UI; de zichtbaarheid is dit blok (Inzicht › Reconciliatie) plus de
querybibliotheek `db-lezen webhook-outbox`.

Twee bevindingssoorten (lees-only, geen HTTP-call — de afleveraar doet het werk):
- `webhook_wacht_op_ontvanger` — per rij met status `wacht_op_ontvanger`: event, referentie, reden uit de body,
  sinds (eerste 409), volgende poging, aantal pogingen. Stand `meten` (facet "in meting", geen actiemail): het systeem
  herhaalt zelf volgens de cadans; de handeling "Nu opnieuw" op de rij is voor wie weet dat Vastly de koppeling
  intussen hersteld heeft. Een dagelijkse actiemail over iets dat het systeem zelf oplost zou precies de ruis zijn die
  Peter 02-10 ("geen mails meer") niet wil.
- `webhook_niet_koppelbaar_verlopen` — per rij die ná 14 dagen wachten alsnog `mislukt` is (`laatste_fout` begint met
  `WACHT_VERLOPEN_PREFIX`, `wacht_op_ontvanger_sinds` gevuld): direct in `actie` — hier is wél een mens nodig (melden
  bij Vastly waarom de koppeling er ná 14 dagen nog niet is; daarna "Nu opnieuw"). Besluit Peter in de opdracht
  (punt 17: "daarna pas `mislukt` mét reden"), het bewijs is de reden uit Vastly's eigen antwoord; explosie-rem blijft.
Per administratie in eigen RLS-scope (coalesce administratie_id/document.administratie_id, zoals de afleveraar)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Document, WebhookStatus, WebhookUitgaand
from app.documenten.webhook_afleveraar import WACHT_MAX, WACHT_PREFIX, WACHT_VERLOPEN_PREFIX

BLOK = "webhooks"
SOORT_WACHT = "webhook_wacht_op_ontvanger"
SOORT_VERLOPEN = "webhook_niet_koppelbaar_verlopen"


def _vingerafdruk(*delen: str) -> str:
    return f"{BLOK}:" + hashlib.sha256("|".join(delen).encode()).hexdigest()[:16]


def _reden_uit(laatste_fout: str | None) -> str | None:
    """Reden van de ontvanger uit `laatste_fout` ("ontvanger kan nog niet koppelen (<reden>) — wacht" |
    "ontvanger kon niet koppelen binnen 14 dagen: <reden>")."""
    if not laatste_fout:
        return None
    if laatste_fout.startswith(WACHT_VERLOPEN_PREFIX):
        return laatste_fout.split(":", 1)[1].strip() if ":" in laatste_fout else None
    if laatste_fout.startswith(WACHT_PREFIX) and "(" in laatste_fout:
        return laatste_fout[laatste_fout.index("(") + 1 : laatste_fout.rindex(")")] if ")" in laatste_fout else None
    return laatste_fout


def _bevinding(verzamelaar, **kw) -> None:  # noqa: ANN001, ANN003
    if verzamelaar is not None:
        verzamelaar.bevinding(**kw)


def _rijen(administratie_id: uuid.UUID) -> list[WebhookUitgaand]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(WebhookUitgaand)
            .outerjoin(Document, WebhookUitgaand.document_id == Document.id)
            .where(
                func.coalesce(WebhookUitgaand.administratie_id, Document.administratie_id) == administratie_id,
                (WebhookUitgaand.status == WebhookStatus.WACHT_OP_ONTVANGER.value)
                | (
                    (WebhookUitgaand.status == WebhookStatus.MISLUKT.value)
                    & WebhookUitgaand.wacht_op_ontvanger_sinds.is_not(None)
                    & WebhookUitgaand.laatste_fout.like(f"{WACHT_VERLOPEN_PREFIX}%")
                ),
            )
            .order_by(WebhookUitgaand.aangemaakt_op)
        ).all()
        session.expunge_all()
        return list(rijen)


def cli_blok(  # noqa: ANN001
    args, verzamelaar=None, *, stdout: Callable[[str], None] = print, nu: datetime | None = None
) -> int:
    """Blokfunctie voor `reconciliatie-alles`. Exit 1 zodra er een bevinding is (ook een wachtende rij: het blok meldt,
    de stand van de soort bepaalt of het een actiemail wordt)."""
    nu = nu or datetime.now(UTC)
    with scoped_session(None) as session:
        administraties = [(a.id, a.naam) for a in session.scalars(select(Administratie))]
    n_wacht = 0
    n_verlopen = 0
    gecontroleerd = 0
    for administratie_id, naam in administraties:
        for rij in _rijen(administratie_id):
            gecontroleerd += 1
            data = rij.payload.get("data") or {}
            referentie = str(data.get("referentie") or rij.id)
            reden = _reden_uit(rij.laatste_fout) or "geen reden in het antwoord"
            sinds = rij.wacht_op_ontvanger_sinds
            verlopen = rij.status == WebhookStatus.MISLUKT.value
            soort = SOORT_VERLOPEN if verlopen else SOORT_WACHT
            if verlopen:
                n_verlopen += 1
                tekst = (
                    f"AFWIJKING  webhooks {naam}: {rij.event} {referentie} ná {WACHT_MAX.days} dagen wachten op de "
                    f"ontvanger mislukt — {reden} ({rij.wacht_pogingen} pogingen sinds "
                    f"{sinds:%d-%m %H:%M} UTC)"
                )
            else:
                n_wacht += 1
                volgende = f"{rij.volgende_poging_op:%d-%m %H:%M} UTC" if rij.volgende_poging_op else "nu"
                tekst = (
                    f"AFWIJKING  webhooks {naam}: {rij.event} {referentie} wacht op de ontvanger — {reden} "
                    f"(poging {rij.wacht_pogingen} sinds {sinds:%d-%m %H:%M} UTC, volgende {volgende})"
                )
            stdout(tekst)
            _bevinding(
                verzamelaar,
                soort="afwijking",
                administratie_id=administratie_id,
                vingerafdruk=_vingerafdruk(soort, str(rij.id)),
                tekst=tekst[:1000],
                detail={
                    "afwijking_soort": soort,
                    "outbox_id": str(rij.id),
                    "event": rij.event,
                    "referentie": referentie,
                    "rlz_document_id": str(data.get("rlz_document_id")) if data.get("rlz_document_id") else None,
                    "volgnummer": data.get("volgnummer"),
                    "reden": reden[:200],
                    "sinds": sinds.isoformat() if sinds else None,
                    "volgende_poging_op": rij.volgende_poging_op.isoformat() if rij.volgende_poging_op else None,
                    "wacht_pogingen": rij.wacht_pogingen,
                    "max_dagen": WACHT_MAX.days,
                    "doel_pad": "/reconciliatie",
                },
                blok=BLOK,
            )
    if verzamelaar is not None:
        verzamelaar.gecontroleerd(gecontroleerd)
    stdout(
        f"WEBHOOKS   {gecontroleerd} outbox-rij(en) in wacht of verlopen getoetst: {n_wacht} wacht op de ontvanger "
        f"(409 niet_koppelbaar, cadans 1 u / 6 u / 24 u / dagelijks), {n_verlopen} ná {WACHT_MAX.days} dagen mislukt"
    )
    return 1 if (n_wacht or n_verlopen) else 0
