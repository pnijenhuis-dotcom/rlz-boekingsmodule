"""AI-kostenmeter (besluit Peter 2026-08-14): deterministische maandgrens op intake-AI-kosten.

Conform "code voor cijfers": de kosten van élke Anthropic-aanroep worden in code berekend uit de
gepinde prijstabel per model (settings.ai_kosten_prijzen_usd_per_mtok) × de gepinde USD→EUR-koers
(settings.ai_kosten_usd_eur_koers, conservatief 1,00) — geen schattingen, geen AI in de
berekening. Elke aanroep landt append-only in platform.ai_gebruik (migratie 0047), met de
wérkelijke token-usage uit de API-response (input/output/cache-schrijf/cache-lees).

De harde poort (controleer_poort) draait vóór élke AI-call: maandcumulatief ≥ limiet → de call
wordt niet gedaan (AiKostenLimietBereikt). Een model zonder gepinde prijs is fail-closed
(AiKostenModelOnbekend): liever een zichtbaar geblokkeerde extractie dan ongemeten kosten.

Maandgrenzen zijn kalendermaanden in Europe/Amsterdam — de `maand`-kolom wordt bij het schrijven
in code bepaald (eerste dag van de lokale maand), zodat cumulatie en poort nooit van een
timezone-berekening in SQL afhangen.

Meldingen (80%-waarschuwing en limiet-bereikt) zijn éénmalig per kalendermaand
(platform.ai_kosten_maandstatus) en landen in het audit_event onder de systeem-actor; het
zichtbare kanaal is de werkvoorraad-banner + het verbruiksblok op Instellingen (beheer-API).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import AiGebruik, AiKostenInstelling, AiKostenMaandstatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

TIJDZONE = ZoneInfo("Europe/Amsterdam")

# Cache-prijsmultipliers t.o.v. de inputprijs (Anthropic-prijsmodel, geverifieerd 2026-08-14):
# cache-schrijven 1,25× (5-minuten-TTL — wat de client gebruikt), cache-lezen 0,10×. Gepind in
# code, niet in env: dit is het prijsmodel zelf, geen omgevingskeuze.
CACHE_SCHRIJF_FACTOR = Decimal("1.25")
CACHE_LEES_FACTOR = Decimal("0.10")

_MTOK = Decimal(1_000_000)
_EUR_PRECISIE = Decimal("0.000001")  # Numeric(12,6) in platform.ai_gebruik
_WAARSCHUWING_FRACTIE = Decimal("0.8")

# Vast record-id voor audit_events over de ai_kosten-instelling/-meldingen (singleton zonder
# eigen uuid) — zelfde conventie als de instelling-singletons in app/beheer/service.py.
AI_KOSTEN_INSTELLING_RECORD_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class AiKostenFout(Exception):
    """Basisklasse voor kostenmeter-fouten."""


class AiKostenLimietBereikt(AiKostenFout):
    """De maandcumulatie heeft de limiet bereikt — de AI-call wordt niet gedaan. Het document
    verdwijnt niet stil: de aanroepers routeren naar het bestaande handmatige pad met de
    zichtbare reden `ai_limiet_bereikt`."""


class AiKostenModelOnbekend(AiKostenFout):
    """Het geconfigureerde model staat niet in de gepinde prijstabel — fail-closed: zonder prijs
    geen meting, zonder meting geen call."""


@dataclass(frozen=True)
class AiVerbruikReferentie:
    """Waar een AI-aanroep bij hoort, voor de append-only log: het document (extractie) of het
    intake-bericht (splitsingsdetectie vóór toewijzing), plus de bron-aanduiding."""

    bron: str
    document_id: uuid.UUID | None = None
    intake_bericht_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AiKostenStatus:
    """Momentopname voor de beheer-API/UI: maand, verbruik, limiet, percentage, meldingen."""

    maand: date
    verbruik_eur: Decimal
    limiet_eur: Decimal
    percentage: int
    waarschuwing_80_op: datetime | None
    limiet_bereikt_op: datetime | None
    geblokkeerd: bool


def huidige_maand(nu: datetime | None = None) -> date:
    """Eerste dag van de kalendermaand in Europe/Amsterdam. `nu` moet tz-aware zijn (default:
    huidige UTC-tijd) — de maandgrens valt dus op middernacht lokale tijd, incl. zomer-/
    wintertijd, nooit op UTC-middernacht."""
    moment = nu if nu is not None else datetime.now(tz=UTC)
    lokaal = moment.astimezone(TIJDZONE)
    return date(lokaal.year, lokaal.month, 1)


def _prijzen_voor(model: str) -> dict[str, Decimal]:
    prijzen = settings.ai_kosten_prijzen_usd_per_mtok.get(model)
    if prijzen is None:
        raise AiKostenModelOnbekend(
            f"Model '{model}' staat niet in de gepinde prijstabel (ai_kosten_prijzen_usd_per_mtok) — "
            "AI-aanroepen met dit model zijn geblokkeerd tot de prijs is gepind (fail-closed)."
        )
    return prijzen


def bereken_kosten_eur(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_schrijf_tokens: int = 0,
    cache_lees_tokens: int = 0,
) -> Decimal:
    """Deterministische kostenberekening in Decimal: tokens × gepinde USD-prijs per Mtok ×
    gepinde USD→EUR-koers, afgerond NAAR BOVEN op 6 decimalen (de meter overschat eerder dan dat
    hij onderschat). `input_tokens` is conform de API het níet-gecachte deel — cache-schrijf en
    cache-lees komen apart binnen en worden apart geprijsd."""
    prijzen = _prijzen_voor(model)
    usd = (
        Decimal(input_tokens) * prijzen["input"]
        + Decimal(output_tokens) * prijzen["output"]
        + Decimal(cache_schrijf_tokens) * prijzen["input"] * CACHE_SCHRIJF_FACTOR
        + Decimal(cache_lees_tokens) * prijzen["input"] * CACHE_LEES_FACTOR
    ) / _MTOK
    return (usd * settings.ai_kosten_usd_eur_koers).quantize(_EUR_PRECISIE, rounding=ROUND_UP)


def _maandlimiet_eur(session: Session) -> Decimal:
    instelling = session.get(AiKostenInstelling, True)
    if instelling is None:
        # Migratie 0047 nog niet toegepast (bv. los script tegen een oude database) — de
        # env-default (100) geldt dan, zelfde fallback-conventie als intake_instelling.
        return settings.ai_kosten_maandlimiet_eur
    return instelling.maandlimiet_eur


def _maand_verbruik_eur(session: Session, maand: date) -> Decimal:
    som = session.execute(
        select(func.coalesce(func.sum(AiGebruik.kosten_eur), 0)).where(AiGebruik.maand == maand)
    ).scalar_one()
    return Decimal(som)


def controleer_poort(*, model: str, nu: datetime | None = None) -> None:
    """De harde poort vóór élke AI-call: maandcumulatief ≥ limiet → AiKostenLimietBereikt (de
    call wordt niet gedaan). Onbekend model → AiKostenModelOnbekend (fail-closed). Draait in de
    client (app/extractie/client.py) zodat geen enkel aanroeppad eromheen kan."""
    _prijzen_voor(model)  # fail-closed vóór de limiettoets: zonder prijs geen meting
    maand = huidige_maand(nu)
    with scoped_session(None) as session:
        limiet = _maandlimiet_eur(session)
        verbruik = _maand_verbruik_eur(session, maand)
    if verbruik >= limiet:
        raise AiKostenLimietBereikt(
            f"AI-maandlimiet bereikt (€ {verbruik:.2f} van € {limiet:.2f} in {maand:%Y-%m}) — "
            "AI-verwerking is geblokkeerd tot de nieuwe maand of een hogere limiet; "
            "documenten volgen het handmatige pad."
        )


def registreer_verbruik(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_schrijf_tokens: int = 0,
    cache_lees_tokens: int = 0,
    referentie: AiVerbruikReferentie | None = None,
    nu: datetime | None = None,
) -> Decimal:
    """Logt één Anthropic-aanroep append-only (wérkelijke usage uit de API-response) en zet —
    éénmalig per kalendermaand — de 80%-waarschuwing en de limiet-bereikt-melding, elk met een
    audit_event onder de systeem-actor. Retourneert de berekende kosten in EUR.

    Bewust twee losse if's (geen elif): één grote call kan in één klap van <80% naar ≥100%
    springen — dan horen béíde meldingen vastgelegd te worden."""
    kosten = bereken_kosten_eur(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_schrijf_tokens=cache_schrijf_tokens,
        cache_lees_tokens=cache_lees_tokens,
    )
    moment = nu if nu is not None else datetime.now(tz=UTC)
    maand = huidige_maand(moment)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(
            AiGebruik(
                maand=maand,
                model=model,
                bron=referentie.bron if referentie else "onbekend",
                document_id=referentie.document_id if referentie else None,
                intake_bericht_id=referentie.intake_bericht_id if referentie else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_schrijf_tokens=cache_schrijf_tokens,
                cache_lees_tokens=cache_lees_tokens,
                kosten_eur=kosten,
            )
        )
        session.flush()

        limiet = _maandlimiet_eur(session)
        verbruik = _maand_verbruik_eur(session, maand)
        status = session.get(AiKostenMaandstatus, maand)
        if status is None:
            status = AiKostenMaandstatus(maand=maand)
            session.add(status)

        if limiet > 0 and verbruik >= limiet * _WAARSCHUWING_FRACTIE and status.waarschuwing_80_op is None:
            status.waarschuwing_80_op = moment
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="platform",
                tabel="ai_kosten_maandstatus",
                record_id=AI_KOSTEN_INSTELLING_RECORD_ID,
                actie="ai_kosten_waarschuwing_80",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"maand": maand.isoformat(), "verbruik_eur": str(verbruik), "limiet_eur": str(limiet)},
            )
        if limiet > 0 and verbruik >= limiet and status.limiet_bereikt_op is None:
            status.limiet_bereikt_op = moment
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="platform",
                tabel="ai_kosten_maandstatus",
                record_id=AI_KOSTEN_INSTELLING_RECORD_ID,
                actie="ai_kosten_limiet_bereikt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"maand": maand.isoformat(), "verbruik_eur": str(verbruik), "limiet_eur": str(limiet)},
            )
    return kosten


def haal_status_op(nu: datetime | None = None) -> AiKostenStatus:
    """Momentopname voor Instellingen/werkvoorraad: verbruik en limiet van de lopende
    kalendermaand (Europe/Amsterdam), percentage (afgekapt op hele procenten, kan boven 100
    uitkomen) en de eenmalige meldingstijdstippen."""
    maand = huidige_maand(nu)
    with scoped_session(None) as session:
        limiet = _maandlimiet_eur(session)
        verbruik = _maand_verbruik_eur(session, maand)
        status = session.get(AiKostenMaandstatus, maand)
        waarschuwing_op = status.waarschuwing_80_op if status else None
        bereikt_op = status.limiet_bereikt_op if status else None
    percentage = int(verbruik / limiet * 100) if limiet > 0 else 100
    return AiKostenStatus(
        maand=maand,
        verbruik_eur=verbruik,
        limiet_eur=limiet,
        percentage=percentage,
        waarschuwing_80_op=waarschuwing_op,
        limiet_bereikt_op=bereikt_op,
        geblokkeerd=verbruik >= limiet,
    )
