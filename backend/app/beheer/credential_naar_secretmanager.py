"""`credential-naar-secretmanager` — kopieer de Reeleezee-webservice-logins van een vaste set administraties uit de
credential-store (`platform.rlz_credential`, envelope-versleuteld) naar Secret Manager in `rlz-boekhouding` als
`RLZ_WS_USER_<PREFIX>` / `RLZ_WS_PASSWORD_<PREFIX>` — opdracht Peter 29-09 (Jarvis leest de negen Universal-/Bradwolff-
administraties rechtstreeks uit RLZ; de containers bestaan al, leeg).

Patroon = `scripts/gcp/registersync_secret.sh` (besluit 0012): machine-naar-machine, de waarde komt NOOIT in log,
uitvoer, audit of chat — alleen de secretnaam en het aantal tekens. Kopiëren van de store naar Secret Manager is het
bestaande patroon (SM → SM), nieuw is alleen dat de bron de envelope-store is. Lees-only voor de module: geen RLZ-
call, geen DB-write behalve één audit_event per administratie (`credential_naar_secretmanager`, zonder waarde).

Draait UITSLUITEND als Cloud Run-job-executie op de gedeployde image (regel 08-09; het KMS-masterkey-recht en de
Secret-Manager-rechten zitten op `run-jobs@`):

    gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait \
        --args="^|^-m|app.cli|credential-naar-secretmanager[|--dry-run]"

Idempotent (F0-les, zelfde als registersync_secret.sh): een secret dat al een ENABLED versie heeft wordt nooit stil
overschreven — regel "heeft al versie N — niet overschreven"; rotatie = bewuste herrun mét `--overschrijven`.
IAM (eenmalig, owner-sessie): `scripts/gcp/credential_naar_secretmanager_iam.sh` — `run-jobs@` krijgt
`secretmanager.viewer` + `secretmanager.secretVersionAdder` op precies deze 18 secrets, `jarvis-run-jobs@` alleen
`secretmanager.secretAccessor`. Niet in de nameting-allowlist: `nameting@` heeft geen secrets-rechten en dit commando
schrijft in Secret Manager.
"""

from __future__ import annotations

import argparse
import base64
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TextIO

COMMANDO = "credential-naar-secretmanager"
PROJECT_DEFAULT = "rlz-boekhouding"
ACTIE_AUDIT = "credential_naar_secretmanager"

#: (administratie-naam zoals de credential-store 'm kent — term voor `_zoek_administratie`, PREFIX in de secretnaam).
#: Opdracht Peter 29-09, letterlijk; volgorde = de opdracht.
DOELEN: tuple[tuple[str, str], ...] = (
    ("Universal Nederland", "UNIVERSAL_NEDERLAND"),
    ("Universal Verkoop", "UNIVERSAL_VERKOOP"),
    ("Universal Materiaal", "UNIVERSAL_MATERIAAL"),
    ("Universal Steigerbouw", "UNIVERSAL_STEIGERBOUW"),
    ("BWC Steigers", "BWC_STEIGERS"),
    ("Bradwolff Constructie", "BRADWOLFF_CONSTRUCTIE"),
    ("Inpensas Beheer", "INPENSAS_BEHEER"),
    ("Bradwolff Holding", "BRADWOLFF_HOLDING"),
    ("De Wit Beheer Oss", "DE_WIT_BEHEER_OSS"),
)


def secretnamen(prefix: str) -> tuple[str, str]:
    return f"RLZ_WS_USER_{prefix}", f"RLZ_WS_PASSWORD_{prefix}"


class SecretManagerPoort(Protocol):
    """Twee calls, allebei zonder de waarde in een foutmelding."""

    def laatste_versie(self, naam: str) -> str | None:
        """Hoogste ENABLED versienummer ('1', '2', …) of None als het secret nog geen versie heeft.
        Een ontbrekende container = fout (de opdracht zegt: containers bestaan al)."""

    def voeg_versie_toe(self, naam: str, waarde: str) -> str:
        """Nieuwe versie; geeft het versienummer terug."""


class RestSecretManager:
    """Secret Manager REST v1 via Application Default Credentials (run-jobs@ in de job; lokaal nooit tegen productie).
    Bewust geen extra dependency (`google-cloud-secret-manager`): google-auth + httpx zitten al in de image."""

    _BASIS = "https://secretmanager.googleapis.com/v1"
    _SCOPE = "https://www.googleapis.com/auth/cloud-platform"

    def __init__(self, project: str) -> None:
        self.project = project
        self._credentials = None

    def _headers(self) -> dict[str, str]:
        import google.auth
        from google.auth.transport.requests import Request

        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=[self._SCOPE])
        if not getattr(self._credentials, "valid", False):
            self._credentials.refresh(Request())  # type: ignore[union-attr]
        return {"Authorization": f"Bearer {self._credentials.token}"}  # type: ignore[union-attr]

    def _url(self, naam: str, staart: str = "") -> str:
        return f"{self._BASIS}/projects/{self.project}/secrets/{naam}{staart}"

    def laatste_versie(self, naam: str) -> str | None:
        import httpx

        antwoord = httpx.get(
            self._url(naam, "/versions"),
            params={"filter": "state:ENABLED", "pageSize": 100},
            headers=self._headers(),
            timeout=20.0,
        )
        if antwoord.status_code == 404:
            raise RuntimeError(f"{naam}: container bestaat niet in project {self.project}")
        if antwoord.status_code >= 400:
            raise RuntimeError(f"{naam}: versies lezen mislukt (HTTP {antwoord.status_code})")
        nummers = [int(v["name"].rsplit("/", 1)[-1]) for v in antwoord.json().get("versions", []) if "name" in v]
        return str(max(nummers)) if nummers else None

    def voeg_versie_toe(self, naam: str, waarde: str) -> str:
        import httpx

        antwoord = httpx.post(
            self._url(naam, ":addVersion"),
            json={"payload": {"data": base64.b64encode(waarde.encode()).decode()}},
            headers=self._headers(),
            timeout=20.0,
        )
        if antwoord.status_code >= 400:
            # Bewust alleen de status: de responsetekst zou de payload kunnen echoën.
            raise RuntimeError(f"{naam}: versie toevoegen mislukt (HTTP {antwoord.status_code})")
        return str(antwoord.json()["name"].rsplit("/", 1)[-1])


@dataclass
class Uitkomst:
    prefix: str
    administratie: str | None = None
    regels: list[str] = field(default_factory=list)
    gezet: int = 0
    overgeslagen: int = 0
    fout: bool = False


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Kopieer de RLZ-webservice-logins van de negen Jarvis-administraties (opdracht Peter 29-09) uit de "
        "credential-store naar Secret Manager RLZ_WS_USER_/RLZ_WS_PASSWORD_<PREFIX>. Waarde nooit in de uitvoer "
        "(besluit 0012): alleen naam + aantal tekens. Bestaande versie = niet overschreven. Alleen als job-executie.",
    )
    p.add_argument("--project", default=PROJECT_DEFAULT, help=f"GCP-project (default {PROJECT_DEFAULT}).")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tonen wat gezet zou worden.")
    p.add_argument(
        "--overschrijven",
        action="store_true",
        help="Ook een nieuwe versie zetten als het secret al een versie heeft (rotatie = bewuste actie).",
    )
    p.add_argument("--prefix", default=None, help="Beperk tot één PREFIX uit de vaste lijst.")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run(args)


def _credential_voor(administratie_id: uuid.UUID) -> tuple[str, str] | None:
    from app.db.session import scoped_session
    from app.rlz.credentials import _store_credential_voor

    with scoped_session(None) as session:
        return _store_credential_voor(session, administratie_id)


def _schrijf_audit(administratie_id: uuid.UUID, *, prefix: str, gezet: dict[str, int]) -> None:
    """Eén audit_event per administratie mét secretnamen + aantal tekens — nooit de waarde. In de administratie-
    scope (audit_event mét administratie_id vereist scope; systeem-actor)."""
    from app.db.audit import record_audit_event
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="platform",
            tabel="rlz_credential",
            record_id=administratie_id,
            actie=ACTIE_AUDIT,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"prefix": prefix, "secrets": gezet, "doel": "secretmanager"},
            administratie_id=administratie_id,
        )


def verwerk(
    *,
    poort: SecretManagerPoort,
    doelen: Sequence[tuple[str, str]] = DOELEN,
    dry_run: bool = False,
    overschrijven: bool = False,
    zoek_administratie: Callable[[str], tuple[uuid.UUID, str] | None] | None = None,
    lees_credential: Callable[[uuid.UUID], tuple[str, str] | None] = _credential_voor,
    schrijf_audit: Callable[..., None] = _schrijf_audit,
) -> list[Uitkomst]:
    if zoek_administratie is None:
        from app.geheugen.btw_default_cli import _zoek_administratie

        zoek_administratie = _zoek_administratie
    uitkomsten: list[Uitkomst] = []
    for naam_term, prefix in doelen:
        u = Uitkomst(prefix=prefix)
        uitkomsten.append(u)
        gevonden = zoek_administratie(naam_term)
        if gevonden is None:
            u.fout = True
            u.regels.append(f"{prefix}: administratie '{naam_term}' niet (eenduidig) gevonden — overgeslagen")
            continue
        administratie_id, u.administratie = gevonden
        login = lees_credential(administratie_id)
        if login is None:
            u.fout = True
            u.regels.append(f"{prefix}: '{u.administratie}' heeft geen credential in de store — overgeslagen")
            continue
        gezet: dict[str, int] = {}
        for secretnaam, waarde in zip(secretnamen(prefix), login, strict=True):
            try:
                bestaand = poort.laatste_versie(secretnaam)
            except Exception as exc:  # noqa: BLE001 — zichtbaar per secret, de rest loopt door
                u.fout = True
                u.regels.append(f"{secretnaam}: FOUT {exc}")
                continue
            if bestaand is not None and not overschrijven:
                u.overgeslagen += 1
                u.regels.append(
                    f"{secretnaam}: heeft al versie {bestaand} — niet overschreven (rotatie = --overschrijven)"
                )
                continue
            if dry_run:
                u.regels.append(f"{secretnaam}: ZOU versie zetten ({len(waarde)} tekens) — dry-run")
                continue
            try:
                versie = poort.voeg_versie_toe(secretnaam, waarde)
            except Exception as exc:  # noqa: BLE001
                u.fout = True
                u.regels.append(f"{secretnaam}: FOUT {exc}")
                continue
            u.gezet += 1
            gezet[secretnaam] = len(waarde)
            u.regels.append(f"{secretnaam}: versie {versie} gezet ({len(waarde)} tekens)")
        if gezet:
            schrijf_audit(administratie_id, prefix=prefix, gezet=gezet)
    return uitkomsten


def run(args: argparse.Namespace, *, uit: TextIO | None = None, poort: SecretManagerPoort | None = None) -> int:
    uit = uit or sys.stdout
    doelen = DOELEN if not args.prefix else tuple(d for d in DOELEN if d[1] == args.prefix)
    if not doelen:
        print(f"{COMMANDO}: --prefix {args.prefix!r} staat niet in de vaste lijst", file=sys.stderr)
        return 2
    poort = poort or RestSecretManager(args.project)
    print(
        f"{COMMANDO}: {len(doelen)} administratie(s) → project {args.project}"
        + (" — DRY-RUN, niets gezet" if args.dry_run else "")
        + (" — OVERSCHRIJVEN aan" if args.overschrijven else ""),
        file=uit,
    )
    uitkomsten = verwerk(poort=poort, doelen=doelen, dry_run=args.dry_run, overschrijven=args.overschrijven)
    for u in uitkomsten:
        for regel in u.regels:
            print(f"  {regel}", file=uit)
    gezet = sum(u.gezet for u in uitkomsten)
    overgeslagen = sum(u.overgeslagen for u in uitkomsten)
    fouten = sum(1 for u in uitkomsten if u.fout)
    print(
        f"{COMMANDO}: klaar — {gezet} versie(s) gezet, {overgeslagen} al aanwezig, {fouten} administratie(s) mét fout"
        " (waarden nooit getoond — besluit 0012)",
        file=uit,
    )
    return 1 if fouten else 0
