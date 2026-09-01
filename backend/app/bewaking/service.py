"""Synthetische bewaking + alerting (best-practice-besluit 1, 31-08).

Aanleiding: twee stille productie-incidenten in het weekend van 30/31-08 — de AI-extractie lag
ruim een dag plat op Anthropic's schema-limiet en het Anthropic-tegoed raakte leeg; beide zijn
toevallig ontdekt. Deze motor draait elk kwartier als Cloud Run-job (`rlz-bewaking`) en toetst:

- health        — de publieke /health-route van de service (synthetisch, via de echte URL);
- database      — verbinding + migratieversie (repo-head == DB);
- documentopslag— leesproef op een bestaand document (GCS/lokaal, nooit schrijven — retentie);
- mailkanaal    — SMTP-configuratie aanwezig (het kanaal waarover de alerts zelf lopen);
- rlz           — lichte leesroute op de TEST-administratie (alleen mét
                  BEWAKING_RLZ_ADMINISTRATIE_ID; nooit een write — kernprincipe 3);
- ai            — 1× per uur: schema-zelftest (union-limiet, de 30-08-klasse) + een minimale
                  échte Claude-call op het goedkoopste gepinde model, onder de bestaande
                  kostenmeter (poort + registratie in app/aikosten);
- extractie_foutratio — 1× per uur: het aandeel gefaalde AI-extracties in het afgelopen uur
                  boven de drempel (default 50 % bij ≥ 3 pogingen) — dít had de schema-bug
                  binnen een uur gemeld i.p.v. na een dag.

Alerting: eigen SMTP-mail (app/berichten/mail) naar `bewaking_alert_ontvanger` — pas bij de
2e opeenvolgende fout van hetzelfde type (geen ruis bij één hik), idempotent per storing
(kolom-is-None-patroon), en een expliciete herstelmelding zodra de probe weer groen is.

Exit-contract van de job: probes die falen zijn een UITKOMST (vastgelegd + gealert), geen
job-failure — anders zou de GCP-job-failure-alert (F3.2) bij élke eerste hik dubbel mailen.
Exit 1 alleen als de bewaking zélf niet kon draaien (bv. DB plat) — dan is F3.2 het vangnet."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select

from app.bewaking.models import BewakingProbeRun, BewakingStoring
from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

logger = logging.getLogger(__name__)

# Minimaal structured-output-schema voor de AI-probe — bewust union-vrij; staat in
# schema_poort.live_schemas() zodat de union-limiet-testpoort 'm meebewaakt.
AI_PROBE_SCHEMA: dict = {
    "type": "object",
    "properties": {"antwoord": {"type": "string"}},
    "required": ["antwoord"],
    "additionalProperties": False,
}

#: Ná hoeveel opeenvolgende fouten van hetzelfde type de alert-mail uitgaat.
ALERT_NA_FOUTEN = 2

#: Venster waarbinnen de uur-probes (AI + foutratio) niet opnieuw draaien (55 min: één tel
#: speling op het kwartierrooster, zodat ze echt élk uur raken en nooit dubbel).
AI_VENSTER = timedelta(minutes=55)

FOUTRATIO_VENSTER = timedelta(hours=1)


@dataclass(frozen=True)
class ProbeUitkomst:
    soort: str
    status: str  # 'ok' | 'fout' | 'overgeslagen'
    detail: str | None = None
    duur_ms: int = 0


def _meet(soort: str, actie) -> ProbeUitkomst:  # noqa: ANN001 — callable zonder args
    """Voert één probe uit; élke exception wordt een 'fout'-uitkomst (nooit de run breken)."""
    start = time.monotonic()
    try:
        uitkomst = actie()
    except Exception as exc:  # noqa: BLE001 — bewust breed: een kapotte probe is de bevinding
        logger.exception("Bewakingsprobe %s faalde", soort)
        uitkomst = ProbeUitkomst(soort=soort, status="fout", detail=str(exc)[:500])
    duur_ms = int((time.monotonic() - start) * 1000)
    return ProbeUitkomst(soort=uitkomst.soort, status=uitkomst.status, detail=uitkomst.detail, duur_ms=duur_ms)


# ---- de probes -----------------------------------------------------------------------------------


def _probe_health() -> ProbeUitkomst:
    url = f"{settings.app_basis_url.rstrip('/')}/health"
    resp = httpx.get(url, timeout=15)
    if resp.status_code == 200 and resp.json().get("status") == "ok":
        return ProbeUitkomst(soort="health", status="ok")
    return ProbeUitkomst(soort="health", status="fout", detail=f"{url} → {resp.status_code}")


def _probe_database() -> ProbeUitkomst:
    from app.db import session as db_session
    from app.db.migratie_guard import _huidige_migratie_in_database, _laatste_migratie_in_repo

    huidige = _huidige_migratie_in_database(db_session.engine)
    laatste = _laatste_migratie_in_repo()
    if huidige != laatste:
        return ProbeUitkomst(
            soort="database", status="fout", detail=f"migratieversie DB={huidige} ≠ repo-head={laatste}"
        )
    return ProbeUitkomst(soort="database", status="ok")


def _probe_documentopslag() -> ProbeUitkomst:
    """Leesproef (bestaat-check — nooit schrijven: de bucket draagt 7-jaars-retentie) op het
    jongste document van de eerste administratie die er één heeft. Geen documenten = ok mét
    detail (een lege omgeving is geen storing)."""
    from app.db.models import Administratie
    from app.documenten.models import Document
    from app.documenten.storage import standaard_opslag

    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id)))
    opslag = standaard_opslag()
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            pad = session.scalars(
                select(Document.opslag_pad).order_by(Document.aangemaakt_op.desc()).limit(1)
            ).first()
        if pad is None:
            continue
        if opslag.bestaat(pad=pad):
            return ProbeUitkomst(soort="documentopslag", status="ok")
        return ProbeUitkomst(soort="documentopslag", status="fout", detail=f"document onleesbaar: {pad}")
    return ProbeUitkomst(soort="documentopslag", status="ok", detail="geen documenten")


def _probe_mailkanaal() -> ProbeUitkomst:
    from app.berichten import mail

    if mail.is_geconfigureerd():
        return ProbeUitkomst(soort="mailkanaal", status="ok")
    return ProbeUitkomst(
        soort="mailkanaal", status="fout", detail="SMTP niet geconfigureerd (BERICHTEN_SMTP_*)"
    )


def _probe_rlz() -> ProbeUitkomst:
    """Lichte leesroute op de TEST-administratie (GET Ledgers $top=1) — strikt read-only.
    Zonder geconfigureerde test-administratie: overgeslagen (dev/lokaal)."""
    rlz_admin_id = settings.bewaking_rlz_administratie_id
    if not rlz_admin_id:
        return ProbeUitkomst(soort="rlz", status="overgeslagen", detail="geen BEWAKING_RLZ_ADMINISTRATIE_ID")
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id

    try:
        client = client_voor_rlz_admin_id(rlz_admin_id)
    except GeenRlzCredentials as exc:
        # Zichtbaar in de statusrij maar geen alert: zonder store-credentials valt er niets te
        # proben — dat is een inrichtingskwestie (test-administratie in de credential-store
        # zetten), geen storing.
        return ProbeUitkomst(soort="rlz", status="overgeslagen", detail=str(exc))
    with client:
        client.get("Ledgers", params={"$top": 1})
    return ProbeUitkomst(soort="rlz", status="ok")


def _probe_ai() -> ProbeUitkomst:
    """Schema-zelftest (goedkoop, vangt de 30-08-klasse) + minimale échte Claude-call op het
    goedkoopste gepinde model. De call loopt door de bestaande kostenpoort en telt mee in de
    maandmeter (bron 'bewaking'); onze éigen maandlimiet = fout mét duidelijk
    handelingsperspectief (de intake-AI ligt dan immers plat), geen API-key = overgeslagen."""
    from app.aikosten.service import AiKostenLimietBereikt, AiVerbruikReferentie
    from app.extractie.client import AiExtractieNietGeconfigureerd, ClaudeExtractieClient
    from app.extractie.schema_poort import controleer_live_schemas

    overtredingen = controleer_live_schemas()
    if overtredingen:
        return ProbeUitkomst(soort="ai", status="fout", detail=f"schema-zelftest: {'; '.join(overtredingen)}")
    try:
        client = ClaudeExtractieClient(
            model=settings.bewaking_ai_model,
            verbruik_referentie=AiVerbruikReferentie(bron="bewaking"),
        )
    except AiExtractieNietGeconfigureerd:
        return ProbeUitkomst(soort="ai", status="overgeslagen", detail="geen ANTHROPIC_API_KEY")
    try:
        antwoord = client.vraag_json(
            system="Je bent een bewakingsprobe. Antwoord uitsluitend met de gevraagde JSON.",
            opdracht='Antwoord met exact {"antwoord": "pong"}.',
            json_schema=AI_PROBE_SCHEMA,
        )
    except AiKostenLimietBereikt as exc:
        return ProbeUitkomst(
            soort="ai",
            status="fout",
            detail=f"AI-maandlimiet bereikt — intake-AI ligt plat tot de limiet is verhoogd: {exc}",
        )
    if not isinstance(antwoord.data, dict) or not antwoord.data.get("antwoord"):
        return ProbeUitkomst(soort="ai", status="fout", detail=f"onbruikbaar antwoord: {antwoord.data!r}")
    return ProbeUitkomst(soort="ai", status="ok")


def _probe_extractie_foutratio(nu: datetime) -> ProbeUitkomst:
    """Foutpiek-signaal: aandeel `ai_extractie_fout` in álle AI-uitkomsten van het afgelopen
    uur, over alle administraties (RLS: per administratie gescoped lezen). Onder de
    minimum-pogingen zwijgt de toets (geen ruis op stille uren)."""
    from app.db.models import Administratie
    from app.documenten.models import DocumentGebeurtenis
    from app.documenten.service import _AI_UITKOMST_KEYS

    sinds = nu - FOUTRATIO_VENSTER
    totaal = fouten = 0
    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id)))
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            rijen = session.scalars(
                select(DocumentGebeurtenis.detail).where(
                    DocumentGebeurtenis.tijdstip >= sinds,
                    or_(*[DocumentGebeurtenis.detail.has_key(k) for k in _AI_UITKOMST_KEYS]),  # noqa: W601
                )
            ).all()
        for detail in rijen:
            # 'overgeslagen' (gate uit, limiet, geen key) is geen póging — telt niet mee.
            if detail is not None and "ai_extractie_overgeslagen" in detail:
                continue
            # Een template-extractie (deterministische terugval, 01-09) is geen AI-poging.
            if detail is not None and detail.get("extractie_bron") == "template":
                continue
            totaal += 1
            if detail is not None and "ai_extractie_fout" in detail:
                fouten += 1
    if totaal < settings.bewaking_extractie_min_pogingen:
        return ProbeUitkomst(soort="extractie_foutratio", status="ok", detail=f"{fouten}/{totaal} (onder minimum)")
    ratio = fouten / totaal
    if ratio >= settings.bewaking_extractie_foutratio_drempel:
        return ProbeUitkomst(
            soort="extractie_foutratio",
            status="fout",
            detail=f"{fouten}/{totaal} extracties faalden in het afgelopen uur ({ratio:.0%})",
        )
    return ProbeUitkomst(soort="extractie_foutratio", status="ok", detail=f"{fouten}/{totaal}")


# ---- storing-administratie + alerts --------------------------------------------------------------


def _verzend_alert(*, onderwerp: str, tekst: str) -> bool:
    from app.berichten import mail

    ontvanger = settings.bewaking_alert_ontvanger
    if not ontvanger:
        logger.warning("Bewakingsalert niet verzonden — geen BEWAKING_ALERT_ONTVANGER: %s", onderwerp)
        return False
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=onderwerp, tekst=tekst)
        return True
    except mail.MailFout:
        # Fail-zichtbaar in de log; de kolom blijft None zodat de volgende run het opnieuw
        # probeert — een alert verdwijnt nooit stil.
        logger.exception("Bewakingsalert kon niet worden verzonden: %s", onderwerp)
        return False


def _verwerk_uitkomst(uitkomst: ProbeUitkomst, *, nu: datetime) -> None:
    """Storing-statemachine per probesoort. 'overgeslagen' raakt de staat niet."""
    if uitkomst.status == "overgeslagen":
        return
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        open_storing = session.scalars(
            select(BewakingStoring)
            .where(BewakingStoring.soort == uitkomst.soort, BewakingStoring.hersteld_op.is_(None))
            .with_for_update()
        ).one_or_none()

        if uitkomst.status == "fout":
            if open_storing is None:
                open_storing = BewakingStoring(
                    id=uuid.uuid4(),
                    soort=uitkomst.soort,
                    opeenvolgende_fouten=1,
                    laatste_fout_op=nu,
                    laatste_detail=uitkomst.detail,
                )
                session.add(open_storing)
                return
            open_storing.opeenvolgende_fouten += 1
            open_storing.laatste_fout_op = nu
            open_storing.laatste_detail = uitkomst.detail
            if open_storing.opeenvolgende_fouten >= ALERT_NA_FOUTEN and open_storing.alert_verzonden_op is None:
                verzonden = _verzend_alert(
                    onderwerp=f"⛔ RLZ-bewaking: {uitkomst.soort} faalt "
                    f"({open_storing.opeenvolgende_fouten}× op rij)",
                    tekst=(
                        f"De bewakingsprobe '{uitkomst.soort}' faalt sinds "
                        f"{open_storing.begonnen_op:%d-%m-%Y %H:%M} UTC "
                        f"({open_storing.opeenvolgende_fouten} opeenvolgende metingen).\n\n"
                        f"Laatste detail:\n{uitkomst.detail or '(geen detail)'}\n\n"
                        f"Er komt automatisch een herstelmelding zodra de probe weer groen is.\n"
                        f"Statusrij: platform.bewaking_probe_run / platform.bewaking_storing.\n\n"
                        f"Administratiekantoor Nijenhuis — automatisch bericht (rlz-bewaking)"
                    ),
                )
                if verzonden:
                    open_storing.alert_verzonden_op = nu
            return

        # status == 'ok'
        if open_storing is None:
            return
        open_storing.hersteld_op = nu
        if open_storing.alert_verzonden_op is not None and open_storing.herstel_gemeld_op is None:
            verzonden = _verzend_alert(
                onderwerp=f"✅ RLZ-bewaking: {uitkomst.soort} hersteld",
                tekst=(
                    f"De bewakingsprobe '{uitkomst.soort}' is weer groen "
                    f"(storing sinds {open_storing.begonnen_op:%d-%m-%Y %H:%M} UTC, "
                    f"{open_storing.opeenvolgende_fouten} gefaalde metingen).\n\n"
                    f"Administratiekantoor Nijenhuis — automatisch bericht (rlz-bewaking)"
                ),
            )
            if verzonden:
                open_storing.herstel_gemeld_op = nu


def _ai_beurt(nu: datetime) -> bool:
    """True als de laatste run mét uur-probes ouder is dan het venster (of ontbreekt)."""
    with scoped_session(None) as session:
        laatste = session.scalars(
            select(BewakingProbeRun.gestart_op)
            .where(BewakingProbeRun.met_ai.is_(True))
            .order_by(BewakingProbeRun.gestart_op.desc())
            .limit(1)
        ).first()
    return laatste is None or nu - laatste > AI_VENSTER


def voer_probes_uit(nu: datetime | None = None) -> dict[str, str]:
    """Eén bewakingsrun (kwartiercadans). Geeft {soort: status} terug voor de CLI-samenvatting."""
    nu = nu or datetime.now(UTC)
    met_ai = _ai_beurt(nu)

    uitkomsten = [
        _meet("health", _probe_health),
        _meet("database", _probe_database),
        _meet("documentopslag", _probe_documentopslag),
        _meet("mailkanaal", _probe_mailkanaal),
        _meet("rlz", _probe_rlz),
    ]
    if met_ai:
        uitkomsten.append(_meet("ai", _probe_ai))
        uitkomsten.append(_meet("extractie_foutratio", lambda: _probe_extractie_foutratio(nu)))
    else:
        uitkomsten.append(ProbeUitkomst(soort="ai", status="overgeslagen", detail="uurvenster"))
        uitkomsten.append(ProbeUitkomst(soort="extractie_foutratio", status="overgeslagen", detail="uurvenster"))

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(
            BewakingProbeRun(
                id=uuid.uuid4(),
                gestart_op=nu,
                beeindigd_op=datetime.now(UTC),
                met_ai=met_ai,
                uitkomsten={
                    u.soort: {"status": u.status, "detail": u.detail, "duur_ms": u.duur_ms} for u in uitkomsten
                },
                alles_ok=all(u.status != "fout" for u in uitkomsten),
            )
        )

    for uitkomst in uitkomsten:
        _verwerk_uitkomst(uitkomst, nu=nu)

    return {u.soort: u.status for u in uitkomsten}
