"""Nieuwe-facturen-bundelmelding (besluit Peter 2026-08-16: expliciet GEEN melding per factuur).

Periodieke job (CLI `nieuwe-facturen-melden`, Cloud Scheduler ~elke 10 min) die per accordeur
het NIEUW klaargezette werk sinds de vorige melding bundelt tot één bericht:
"Er staan N facturen voor u klaar." — N is het totale aantal dat nu op de accordeur wacht
(dat is wat hij/zij in de app ziet); de trigger is ≥1 nog niet gemeld document.

Regels:
- Geen bericht bij 0 nieuw (een al gemeld openstaand document triggert nooit opnieuw).
- Idempotent per (accordeur, document) via platform.accordeur_nieuw_gemeld (uniek, migratie
  0054, claim-vóór-verzenden): nooit dubbel voor hetzelfde document — ook niet over
  her-aanbiedingen heen. 'mislukt'/'overgeslagen' (aantoonbaar niets bezorgd) probeert een
  volgende run opnieuw; een 'bezig'-blijver nooit automatisch (zichtbaar via exit 1).
- Stille uren: tussen 20:00 en 08:00 Europe/Amsterdam verstuurt de job níéts (en claimt ook
  niets) — wat 's nachts binnenkomt telt gewoon mee in de eerstvolgende run ná 08:00 én in de
  ongewijzigde 09:00-herinnering (die telt altijd integraal).
- Kanaal: push-anders-mail (gedeelde helper app/berichten/verzending.py), deep-link /accordeur.
- Volumerem: settings.nieuwe_facturen_max_berichten_per_run per run, daarboven zichtbaar stoppen.

HARD PRINCIPE: deep-link naar de PWA — goedkeuren-zonder-inloggen bestaat bewust niet."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.accordering import service as accordering_service
from app.berichten import verzending
from app.berichten.herinneringen import _actieve_accordeurs
from app.berichten.models import AccordeurNieuwGemeld, HerinneringKanaal, HerinneringStatus
from app.config import settings
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

TIJDZONE = ZoneInfo("Europe/Amsterdam")
STILLE_UREN_START = 20  # vanaf 20:00 lokale tijd geen meldingen …
STILLE_UREN_EIND = 8  # … tot 08:00 (besluit Peter 2026-08-16)


@dataclass
class NieuweFacturenRapport:
    """Job-uitkomst — elke teller zichtbaar in de joblog; is_fout bepaalt de exit-code."""

    stille_uren: bool = False
    verzonden_push: int = 0
    verzonden_mail: int = 0
    gemelde_documenten: int = 0
    accordeurs_zonder_nieuw: int = 0
    overgeslagen_geen_kanaal: int = 0
    mislukt: int = 0
    onafgemaakt: int = 0  # bezig-blijvers — mens beoordeelt, nooit automatisch opnieuw
    subscripties_vervallen: int = 0
    volumerem_bereikt: bool = False
    fouten: list[str] = field(default_factory=list)

    @property
    def is_fout(self) -> bool:
        return bool(self.mislukt or self.onafgemaakt or self.volumerem_bereikt)


def in_stille_uren(moment: datetime | None = None) -> bool:
    lokaal = (moment or datetime.now(UTC)).astimezone(TIJDZONE)
    return lokaal.hour >= STILLE_UREN_START or lokaal.hour < STILLE_UREN_EIND


def bericht_teksten(totaal: int) -> tuple[str, str, str]:
    """(onderwerp, pushtekst, mailtekst) — N = het totale aantal dat nu op de accordeur wacht."""
    kern = "Er staat 1 factuur voor u klaar." if totaal == 1 else f"Er staan {totaal} facturen voor u klaar."
    onderwerp = f"Goedkeuren: {kern[0].lower()}{kern[1:]}".rstrip(".")
    link = f"{settings.app_basis_url.rstrip('/')}/accordeur"
    mailtekst = (
        f"Beste,\n\n"
        f"{kern}\n\n"
        f"Open de app om te beoordelen:\n{link}\n\n"
        f"Deze link opent alleen de app — goedkeuren gebeurt altijd ín de app, na ontgrendelen.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    return onderwerp, kern, mailtekst


def _documenten_per_accordeur() -> dict[uuid.UUID, set[uuid.UUID]]:
    """Alle administraties langs (RLS: één scope per transactie), documenten aan de beurt per
    accordeur — exact de wachtrij-definitie (accordering_service.documenten_aan_de_beurt)."""
    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    totaal: dict[uuid.UUID, set[uuid.UUID]] = {}
    for administratie_id in administratie_ids:
        for accordeur_id, document_ids in accordering_service.documenten_aan_de_beurt(
            administratie_id=administratie_id
        ).items():
            totaal.setdefault(accordeur_id, set()).update(document_ids)
    return totaal


@dataclass(frozen=True)
class _Claim:
    rij_ids: list[uuid.UUID]
    nieuw: int
    onafgemaakt: int


def _claim_nieuwe(gebruiker_id: uuid.UUID, document_ids: set[uuid.UUID]) -> _Claim:
    """Claim (of herclaim) de nog-niet-gemelde documenten vóór er iets verstuurd wordt."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaande = {
            rij.document_id: rij
            for rij in session.scalars(
                select(AccordeurNieuwGemeld).where(
                    AccordeurNieuwGemeld.gebruiker_id == gebruiker_id,
                    AccordeurNieuwGemeld.document_id.in_(document_ids),
                )
            )
        }
        rij_ids: list[uuid.UUID] = []
        nieuw = 0
        onafgemaakt = 0
        for document_id in sorted(document_ids, key=str):
            rij = bestaande.get(document_id)
            if rij is None:
                aanmaak = AccordeurNieuwGemeld(id=uuid.uuid4(), gebruiker_id=gebruiker_id, document_id=document_id)
                session.add(aanmaak)
                rij_ids.append(aanmaak.id)
                nieuw += 1
            elif rij.status in (HerinneringStatus.MISLUKT.value, HerinneringStatus.OVERGESLAGEN.value):
                rij.status = HerinneringStatus.BEZIG.value
                rij_ids.append(rij.id)
                nieuw += 1
            elif rij.status == HerinneringStatus.BEZIG.value:
                onafgemaakt += 1
            # 'verzonden': al gemeld — nooit opnieuw.
        try:
            session.flush()
        except IntegrityError:
            # Parallelle run won de race op de unique (gebruiker, document) — deze run meldt
            # dan niets voor deze accordeur; de winnende run doet dat al.
            return _Claim([], 0, onafgemaakt)
    return _Claim(rij_ids, nieuw, onafgemaakt)


def _rond_claims_af(
    rij_ids: list[uuid.UUID], *, status: HerinneringStatus, kanaal: HerinneringKanaal | None, detail: dict | None
) -> None:
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        for rij_id in rij_ids:
            rij = session.get(AccordeurNieuwGemeld, rij_id)
            if rij is None:
                continue
            rij.status = status.value
            rij.kanaal = kanaal.value if kanaal else None
            rij.detail = detail
            if status == HerinneringStatus.VERZONDEN:
                rij.verzonden_op = now


def verstuur_nieuwe_facturen_meldingen(*, nu: datetime | None = None) -> NieuweFacturenRapport:
    rapport = NieuweFacturenRapport()
    if in_stille_uren(nu):
        rapport.stille_uren = True
        return rapport

    per_accordeur = _documenten_per_accordeur()
    verzonden_deze_run = 0
    for gebruiker in _actieve_accordeurs():
        document_ids = per_accordeur.get(gebruiker.id, set())
        if not document_ids:
            continue
        if verzonden_deze_run >= settings.nieuwe_facturen_max_berichten_per_run:
            rapport.volumerem_bereikt = True
            rapport.fouten.append(
                f"volumerem: max {settings.nieuwe_facturen_max_berichten_per_run} berichten per run bereikt — "
                f"resterende accordeurs volgen in een latere run (claims nog niet gelegd, nooit dubbel)"
            )
            break
        claim = _claim_nieuwe(gebruiker.id, document_ids)
        if claim.onafgemaakt:
            rapport.onafgemaakt += claim.onafgemaakt
            rapport.fouten.append(
                f"{claim.onafgemaakt} gemeld-claim(s) voor {gebruiker.id} bleven op 'bezig' staan "
                f"(gecrashte run?) — niet automatisch opnieuw gemeld, handmatig beoordelen"
            )
        if claim.nieuw == 0:
            rapport.accordeurs_zonder_nieuw += 1
            continue
        totaal = len(document_ids)
        onderwerp, pushtekst, mailtekst = bericht_teksten(totaal)
        uitkomst = verzending.verstuur_push_anders_mail(
            gebruiker, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url="/accordeur"
        )
        rapport.subscripties_vervallen += uitkomst.subscripties_vervallen
        _rond_claims_af(claim.rij_ids, status=uitkomst.status, kanaal=uitkomst.kanaal, detail=uitkomst.detail)
        if uitkomst.status == HerinneringStatus.VERZONDEN:
            verzonden_deze_run += 1
            rapport.gemelde_documenten += claim.nieuw
            if uitkomst.kanaal == HerinneringKanaal.PUSH:
                rapport.verzonden_push += 1
            else:
                rapport.verzonden_mail += 1
        elif uitkomst.status == HerinneringStatus.OVERGESLAGEN:
            rapport.overgeslagen_geen_kanaal += 1
        else:
            rapport.mislukt += 1
            rapport.fouten.append(f"verzending mislukt voor {gebruiker.id}: {uitkomst.detail}")
    return rapport
