"""OTA-manifest, bundelregister, kill-switch/cohort en de minimum-versie-poort (Peter 16-09, migratie 0152).

Regels (BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA), MINIMUM-VERSIE-POORT, IN-APP-UPDATE"):
- het manifest geeft UITSLUITEND bundels van de gevraagde RUNTIME (marketingversie van de schil) en van het platform
  (of 'alle') — een 1.1-schil krijgt nooit een bundel die een 1.2-native nodig heeft;
- kill-switch: env `OTA_UITGESCHAKELD=true` óf `app_update_instelling.uitgeschakeld` → altijd `geen_update`;
- cohort: `percentage` < 100 → deterministische hash van het toestel (of de huidige bundel) modulo 100;
- `verplicht` = direct toepassen (app herstart mét melding), anders bij de VOLGENDE start;
- sha256 in het manifest + HTTPS; geen ondertekende bundels in fase 1 (optie gerapporteerd);
- rollback-melding (`notifyAppReady` niet binnen 10 s / crash) → audit `ota_rollback`, nooit stil.
Minimum-versie: `_versie_tuple(X-App-Versie) < _versie_tuple(app_min_runtime_versie)` → 426 op élke API-call.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.berichten.uitnodigingsmail import _versie_tuple
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import AppBundel, AppUpdateInstelling, WebauthnCredential
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

logger = logging.getLogger(__name__)

HEADER_APP_VERSIE = "X-App-Versie"
HEADER_BUNDEL_ID = "X-Bundel-Id"
HEADER_APP_PLATFORM = "X-App-Platform"
HEADER_NATIVE_CLIENT = "X-Native-Client"
PLATFORMS = ("ios", "android", "alle")
_VERSIE_RE = re.compile(r"^\d+(\.\d+){0,3}$")


def is_versie(tekst: str | None) -> bool:
    """Strikte versievorm (1.1, 1.2.0) — `_versie_tuple` zelf is tolerant en geeft voor rommel (0,)."""
    return bool(tekst) and bool(_VERSIE_RE.match(tekst.strip()))
_INSTELLING_RECORD_ID = uuid.UUID("00000000-0000-0000-0000-00000000a152")


class AppUpdateFout(Exception):
    """Leesbare fout (CLI/route)."""


@dataclass(frozen=True)
class Manifest:
    geen_update: bool
    reden: str | None = None
    bundel_id: str | None = None
    url: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    verplicht: bool = False
    runtime: str | None = None

    def als_dict(self) -> dict:
        if self.geen_update:
            return {"geen_update": True, "reden": self.reden}
        return {
            "geen_update": False,
            "bundel_id": self.bundel_id,
            "url": self.url,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "verplicht": self.verplicht,
            "runtime": self.runtime,
        }


# ---- instelling --------------------------------------------------------------------------------------------------


def haal_instelling_op() -> AppUpdateInstelling:
    with scoped_session(None) as session:
        rij = session.get(AppUpdateInstelling, True)
        if rij is None:
            raise AppUpdateFout("platform.app_update_instelling heeft geen rij — migratie 0152 niet toegepast?")
        session.expunge(rij)
        return rij


def zet_instelling(*, actor_id: uuid.UUID, percentage: int | None = None, uitgeschakeld: bool | None = None) -> AppUpdateInstelling:
    if percentage is not None and not 0 <= percentage <= 100:
        raise AppUpdateFout("percentage moet tussen 0 en 100 liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(AppUpdateInstelling, True)
        if rij is None:
            raise AppUpdateFout("platform.app_update_instelling heeft geen rij — migratie 0152 niet toegepast?")
        oud = {"percentage": rij.percentage, "uitgeschakeld": rij.uitgeschakeld}
        if percentage is not None:
            rij.percentage = percentage
        if uitgeschakeld is not None:
            rij.uitgeschakeld = uitgeschakeld
        rij.gewijzigd_door = actor_id
        rij.gewijzigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="app_update_instelling",
            record_id=_INSTELLING_RECORD_ID,
            actie="app_update_instelling_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"percentage": rij.percentage, "uitgeschakeld": rij.uitgeschakeld},
        )
        session.flush()
        session.expunge(rij)
        return rij


def ota_uitgeschakeld() -> bool:
    if settings.ota_uitgeschakeld:
        return True
    try:
        return bool(haal_instelling_op().uitgeschakeld)
    except AppUpdateFout:
        return True  # geen singleton = fail-closed: geen updates uitdelen


# ---- register ----------------------------------------------------------------------------------------------------


def registreer_bundel(
    *,
    bundel_id: str,
    runtime: str,
    pad: str,
    sha256: str,
    bytes_: int,
    platform: str = "alle",
    verplicht: bool = False,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
) -> AppBundel:
    """Idempotent op `bundel_id` (de deploy kan herhalen): bestaande rij blijft, alleen `actief` wordt weer true."""
    if platform not in PLATFORMS:
        raise AppUpdateFout(f"platform moet ios|android|alle zijn, niet {platform!r}")
    if not is_versie(runtime):
        raise AppUpdateFout(f"runtime is geen versie: {runtime!r}")
    if len(sha256) != 64:
        raise AppUpdateFout("sha256 moet 64 hex-tekens zijn")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.scalar(select(AppBundel).where(AppBundel.bundel_id == bundel_id))
        if rij is None:
            rij = AppBundel(
                bundel_id=bundel_id, runtime=runtime, platform=platform, pad=pad, sha256=sha256.lower(), bytes=bytes_,
                verplicht=verplicht, actief=True, aangemaakt_door=actor_id,
            )
            session.add(rij)
            actie = "app_bundel_geregistreerd"
        else:
            rij.actief = True
            actie = "app_bundel_herregistratie"
        session.flush()
        record_audit_event(
            session, actor_id=actor_id, module="platform", tabel="app_bundel", record_id=rij.id, actie=actie,
            correlatie_id=rij.id,
            nieuwe_waarde={"bundel_id": bundel_id, "runtime": runtime, "platform": platform, "sha256": sha256.lower(), "bytes": bytes_, "verplicht": verplicht},
        )
        session.expunge(rij)
        return rij


def zet_bundel_actief(*, bundel_id: str, actief: bool, actor_id: uuid.UUID) -> AppBundel:
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.scalar(select(AppBundel).where(AppBundel.bundel_id == bundel_id))
        if rij is None:
            raise AppUpdateFout(f"onbekende bundel {bundel_id!r}")
        oud = rij.actief
        rij.actief = actief
        record_audit_event(
            session, actor_id=actor_id, module="platform", tabel="app_bundel", record_id=rij.id,
            actie="app_bundel_actief_gewijzigd", correlatie_id=rij.id, oude_waarde={"actief": oud}, nieuwe_waarde={"actief": actief},
        )
        session.flush()
        session.expunge(rij)
        return rij


def bundels(*, runtime: str | None = None, limiet: int = 50) -> list[AppBundel]:
    with scoped_session(None) as session:
        q = select(AppBundel).order_by(AppBundel.aangemaakt_op.desc()).limit(limiet)
        if runtime:
            q = q.where(AppBundel.runtime == runtime)
        rijen = list(session.scalars(q))
        for r in rijen:
            session.expunge(r)
        return rijen


def nieuwste_bundel(*, runtime: str, platform: str) -> AppBundel | None:
    with scoped_session(None) as session:
        rij = session.scalar(
            select(AppBundel)
            .where(AppBundel.runtime == runtime, AppBundel.actief.is_(True), AppBundel.platform.in_([platform, "alle"]))
            .order_by(AppBundel.aangemaakt_op.desc())
            .limit(1)
        )
        if rij is not None:
            session.expunge(rij)
        return rij


# ---- manifest ------------------------------------------------------------------------------------------------------


def in_cohort(sleutel: str, percentage: int) -> bool:
    """Deterministisch: hetzelfde toestel valt bij hetzelfde percentage altijd in dezelfde helft."""
    if percentage >= 100:
        return True
    if percentage <= 0:
        return False
    h = int(hashlib.sha256(sleutel.encode("utf-8")).hexdigest()[:8], 16)
    return h % 100 < percentage


def manifest(
    *,
    runtime: str,
    platform: str,
    huidig: str | None,
    toestel: str | None = None,
    basis_url: str = "",
) -> Manifest:
    if platform not in ("ios", "android"):
        return Manifest(geen_update=True, reden="platform onbekend")
    if not is_versie(runtime):
        return Manifest(geen_update=True, reden="runtime onbekend")
    if ota_uitgeschakeld():
        return Manifest(geen_update=True, reden="uitgeschakeld")
    bundel = nieuwste_bundel(runtime=runtime, platform=platform)
    if bundel is None:
        return Manifest(geen_update=True, reden="geen bundel voor deze runtime")
    if huidig and huidig == bundel.bundel_id:
        return Manifest(geen_update=True, reden="actueel")
    percentage = haal_instelling_op().percentage
    if not in_cohort(toestel or huidig or "", percentage):
        return Manifest(geen_update=True, reden=f"buiten cohort ({percentage} %)")
    return Manifest(
        geen_update=False,
        bundel_id=bundel.bundel_id,
        url=f"{basis_url}/app/bundels/{bundel.bundel_id}.zip",
        sha256=bundel.sha256,
        bytes=bundel.bytes,
        verplicht=bundel.verplicht,
        runtime=bundel.runtime,
    )


def bundel_bytes(bundel_id: str) -> tuple[AppBundel, bytes]:
    from app.appupdate.opslag import bundel_opslag

    with scoped_session(None) as session:
        rij = session.scalar(select(AppBundel).where(AppBundel.bundel_id == bundel_id, AppBundel.actief.is_(True)))
        if rij is None:
            raise AppUpdateFout("onbekende of teruggetrokken bundel")
        session.expunge(rij)
    return rij, bundel_opslag().lezen(pad=rij.pad)


# ---- rollback-melding + toestelstand ----------------------------------------------------------------------------------


def meld_rollback(*, apparaat_id: uuid.UUID | None, bundel_id: str, reden: str | None, app_versie: str | None) -> None:
    """Audit `ota_rollback` (nooit stil): de schil viel terug op de vorige/ingebouwde bundel."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="platform",
            tabel="webauthn_credential",
            record_id=apparaat_id or _INSTELLING_RECORD_ID,
            actie="ota_rollback",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"bundel_id": bundel_id[:80], "reden": (reden or "")[:200], "app_versie": (app_versie or "")[:40]},
        )


def registreer_toestelstand(*, apparaat_id: uuid.UUID, app_versie: str | None, bundel_id: str | None) -> None:
    """Per request (deps): alleen een UPDATE als de gemelde stand verandert — goedkoop, nooit een fout."""
    if not app_versie and not bundel_id:
        return
    try:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            session.execute(
                text(
                    "UPDATE platform.webauthn_credential SET app_versie = :v, bundel_id = :b, bundel_gezien_op = now() "
                    "WHERE id = :id AND (app_versie IS DISTINCT FROM :v OR bundel_id IS DISTINCT FROM :b)"
                ),
                {"id": apparaat_id, "v": (app_versie or None) and app_versie[:40], "b": (bundel_id or None) and bundel_id[:80]},
            )
    except Exception:  # noqa: BLE001 — registratie mag een request nooit laten omvallen
        logger.exception("toestelstand niet bijgewerkt voor %s", apparaat_id)


def laatste_toestellen(limiet: int = 20) -> list[dict]:
    with scoped_session(None) as session:
        rijen = session.execute(
            select(
                WebauthnCredential.id, WebauthnCredential.apparaat_naam, WebauthnCredential.platform,
                WebauthnCredential.app_versie, WebauthnCredential.bundel_id, WebauthnCredential.bundel_gezien_op,
                WebauthnCredential.laatst_gebruikt_op,
            )
            .where(WebauthnCredential.soort == "toestel", WebauthnCredential.ingetrokken_op.is_(None))
            .order_by(WebauthnCredential.bundel_gezien_op.desc().nullslast(), WebauthnCredential.laatst_gebruikt_op.desc().nullslast())
            .limit(limiet)
        ).all()
    return [
        {
            "apparaat_id": str(r[0]), "apparaat_naam": r[1], "platform": r[2], "app_versie": r[3], "bundel_id": r[4],
            "bundel_gezien_op": r[5].isoformat() if r[5] else None, "laatst_gebruikt_op": r[6].isoformat() if r[6] else None,
        }
        for r in rijen
    ]


# ---- minimum-versie-poort --------------------------------------------------------------------------------------------


def schil_te_oud(app_versie: str | None, *, minimum: str | None = None) -> bool:
    """True als een AANGEKONDIGDE schilversie onder het minimum ligt. Geen/ongeldige aankondiging = niet te oud
    (die schillen vallen onder de legacy-Sunset-route)."""
    minimum = minimum or settings.app_min_runtime_versie
    if not is_versie(app_versie) or not is_versie(minimum):
        return False
    return _versie_tuple(app_versie) < _versie_tuple(minimum)


def store_url(platform: str | None) -> str | None:
    if platform == "android":
        return settings.store_link_android.strip() or None
    if platform == "ios":
        return settings.store_link_ios.strip() or None
    return None
