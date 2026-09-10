"""Bewakingsprobe `deploy_drift` (ochtendrun 11-09, blok 2.1).

Aanleiding: de deploy-workflow brak van 09-09 06:00 tot 10-09 17:56 af ná de service-stap (delimiter-fout) —
de service kreeg élke push, álle F3-jobs bleven 13 deploys lang op een oud beeld, en zeven rode deploy-runs
(#173–#179) zag niemand. Service en jobs horen hetzelfde beeld te dragen (deploy.yml: één `IMAGE:GITHUB_SHA`);
loopt dat uiteen, dan draait het achtergrondwerk (sync, reconciliatie, intake, bewaking …) op andere code dan
de app die de gebruiker ziet.

Wat de probe doet (lees-only, Cloud Run Admin API v2, runtime-SA van rlz-bewaking):
- leest het beeld van de service-template + de aanmaaktijd van de jongste gereed-revisie;
- leest het beeld van élke job in dezelfde locatie (alle jobs komen uit dezelfde deploy.yml-lus);
- jobs met een ander beeld dan de service = ACHTER. Binnen de gratieperiode (30 min ná de jongste
  service-revisie) is dat een lopende deploy → 'ok' mét detail; daarna → 'fout' (storing-statemachine van
  de bewaking: alert bij de 2e opeenvolgende fout, herstelmelding zodra gelijk) + audit `deploy_drift`
  (idempotent per drift-situatie) + LET-OP "systeemfout — automatisch gemeld" in de reconciliatie
  (`automatiseringen.deploy_drift_bevinding`, leest de open storing).
- geen `BEWAKING_SERVICE_RESOURCE` (dev/lokaal) → overgeslagen; geen leesrecht (403) → 'fout' mét de
  letterlijke API-melding (een ontbrekende harde voorwaarde is zichtbaar, nooit stil — kernprincipe 7(6)).

De post-deploy-smoketest (`deploy-smoketest`) toetst hetzelfde één keer direct ná de deploy, zónder gratie
(op dat moment móeten service en jobs gelijk zijn) — zie `cli._deploy_smoketest`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

RUN_API = "https://run.googleapis.com/v2"
METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

SOORT = "deploy_drift"
AUDIT_ACTIE = "deploy_drift"
#: Gratieperiode ná de jongste service-revisie: de F3-lus in deploy.yml zet ~15 jobs ná de service-stap bij
#: (meting 10-09: service 19:38–19:41Z, laatste job 19:40Z — ruim binnen een minuut; 30 min is de opdracht-grens).
GRATIE = timedelta(minutes=30)

#: Namespace voor het deterministische audit-record-id per drift-situatie (service-revisie + set achterlopende jobs).
_NS = uuid.UUID("7d6f1b1e-4b0a-4c1e-9a3e-0de910d21f70")


class DeployDriftLeesfout(RuntimeError):
    """De stand kon niet gelezen worden (API-fout, geen recht) — de PROBE maakt hier een 'fout'-uitkomst van."""


@dataclass(frozen=True)
class DeployStand:
    service_resource: str
    service_image: str
    service_revisie: str  # korte revisienaam
    service_revisie_op: datetime
    jobs: dict[str, str]  # korte jobnaam → image


@dataclass(frozen=True)
class DriftOordeel:
    achter: dict[str, str]  # korte jobnaam → image (≠ service)
    binnen_gratie: bool

    @property
    def is_drift(self) -> bool:
        return bool(self.achter) and not self.binnen_gratie


def metadata_token() -> str:
    """Toegangstoken van het runtime-serviceaccount (metadata-server) — zelfde route als de job-triggers."""
    resp = httpx.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get(pad: str, *, token: str) -> dict:
    resp = httpx.get(f"{RUN_API}/{pad}", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if resp.status_code >= 400:
        raise DeployDriftLeesfout(f"GET {pad} → {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _kort(resource_naam: str) -> str:
    return resource_naam.rsplit("/", 1)[-1]


def kort_beeld(image: str) -> str:
    """`…/backend:58feacb99ff2…` → `58feacb`; digest → `sha256:fe47a479…`."""
    if "@sha256:" in image:
        return "sha256:" + image.rsplit("@sha256:", 1)[1][:12]
    if ":" in image.rsplit("/", 1)[-1]:
        return image.rsplit(":", 1)[1][:7]
    return image.rsplit("/", 1)[-1]


def lees_stand(*, service_resource: str, token: str) -> DeployStand:
    """Cloud Run Admin API v2: service-template-beeld, aanmaaktijd van de jongste gereed-revisie en het beeld van
    élke job in dezelfde locatie (`projects/…/locations/…/jobs`, gepagineerd)."""
    svc = _get(service_resource, token=token)
    try:
        service_image = svc["template"]["containers"][0]["image"]
    except (KeyError, IndexError) as exc:
        raise DeployDriftLeesfout(f"service zonder container-beeld in de template: {exc}") from exc
    revisie = svc.get("latestReadyRevision") or svc.get("latestCreatedRevision")
    if not revisie:
        raise DeployDriftLeesfout("service zonder revisie")
    rev = _get(revisie, token=token)
    revisie_op = datetime.fromisoformat(str(rev["createTime"]).replace("Z", "+00:00"))
    ouder = service_resource.rsplit("/services/", 1)[0]
    jobs: dict[str, str] = {}
    pagina: str | None = None
    while True:
        pad = f"{ouder}/jobs?pageSize=100" + (f"&pageToken={pagina}" if pagina else "")
        antwoord = _get(pad, token=token)
        for job in antwoord.get("jobs") or []:
            try:
                jobs[_kort(job["name"])] = job["template"]["template"]["containers"][0]["image"]
            except (KeyError, IndexError):
                jobs[_kort(job.get("name", "?"))] = "(geen beeld in de template)"
        pagina = antwoord.get("nextPageToken")
        if not pagina:
            break
    return DeployStand(
        service_resource=service_resource,
        service_image=service_image,
        service_revisie=_kort(revisie),
        service_revisie_op=revisie_op,
        jobs=jobs,
    )


def beoordeel(stand: DeployStand, *, nu: datetime, gratie: timedelta = GRATIE) -> DriftOordeel:
    """Jobs met een ander beeld dan de service; binnen `gratie` ná de jongste service-revisie is dat een lopende
    deploy (geen storing)."""
    achter = {naam: image for naam, image in sorted(stand.jobs.items()) if image != stand.service_image}
    return DriftOordeel(achter=achter, binnen_gratie=(nu - stand.service_revisie_op) <= gratie)


def samenvatting(stand: DeployStand, oordeel: DriftOordeel) -> str:
    """Leesbare detailregel voor statusrij, alert en LET-OP (beelden verkort; geen GUID's)."""
    if not oordeel.achter:
        beeld = kort_beeld(stand.service_image)
        return f"service en {len(stand.jobs)} job(s) op {beeld} (revisie {stand.service_revisie})"
    delen = ", ".join(f"{naam} op {kort_beeld(image)}" for naam, image in oordeel.achter.items())
    kop = (
        f"{len(oordeel.achter)} van {len(stand.jobs)} job(s) achter op de service ({kort_beeld(stand.service_image)}, "
        f"revisie {stand.service_revisie} van {stand.service_revisie_op:%d-%m %H:%M} UTC)"
    )
    staart = " — deploy loopt nog (binnen de gratieperiode)" if oordeel.binnen_gratie else ""
    return f"{kop}: {delen}{staart}"[:1000]


def audit_record_id(stand: DeployStand, oordeel: DriftOordeel) -> uuid.UUID:
    """Deterministisch per drift-situatie: dezelfde service-revisie + dezelfde set achterlopende jobs = één event."""
    sleutel = stand.service_revisie + "|" + "|".join(f"{n}={i}" for n, i in sorted(oordeel.achter.items()))
    return uuid.uuid5(_NS, sleutel)


def registreer_audit(stand: DeployStand, oordeel: DriftOordeel, *, nu: datetime) -> bool:
    """Audit `deploy_drift` (administratie-loos, systeem-actor), idempotent per drift-situatie. True = nieuw."""
    from sqlalchemy import select

    from app.db.audit import record_audit_event
    from app.db.models import AuditEvent
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    record_id = audit_record_id(stand, oordeel)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaat = session.scalar(
            select(AuditEvent.id).where(AuditEvent.actie == AUDIT_ACTIE, AuditEvent.record_id == record_id).limit(1)
        )
        if bestaat is not None:
            return False
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="platform",
            tabel="bewaking_storing",
            record_id=record_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "service": _kort(stand.service_resource),
                "service_image": stand.service_image,
                "service_revisie": stand.service_revisie,
                "service_revisie_op": stand.service_revisie_op.astimezone(UTC).isoformat(),
                "jobs_achter": dict(oordeel.achter),
                "aantal_jobs": len(stand.jobs),
                "gemeten_op": nu.astimezone(UTC).isoformat(),
            },
        )
    return True
