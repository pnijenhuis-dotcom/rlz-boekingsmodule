"""Guard (Peter 16-09, BESLISSINGEN "DEPLOY — VOLLEDIGE ENVSET IN ÉÉN STAP"): de service en élke job krijgen hun
VOLLEDIGE envset + secrets in de ENE deploy-stap. Aanleiding 16-09 09:00: de herstel-link voor een klant-accordeur
meldde "Mailkanaal niet geconfigureerd" — `--set-env-vars` in `gcloud run deploy rlz-backend` verving de hele envset,
en BERICHTEN_SMTP_* kwam pas in een latere `services update`-stap terug (venster van minuten bij élke deploy; blijvend
kwijt als de run ná de service-stap rood ging, zoals op 10-09 en bij `a23042e`). Fail-closed: een nieuwe `services
update`/`jobs update` op envs of secrets is rood; de mail-envset heeft één bron (workflow-`env:` MAIL_ENVS/MAIL_SECRETS)
voor service én jobs."""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_deploy_yml_envvar_delimiters import expandeer, paren, workflow_env

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"

#: Sleutels die de service in productie draagt — élke sleutel die vóór 16-09 in een losse update-stap stond, staat hier.
SERVICE_ENV_SLEUTELS = {
    "ENVIRONMENT",
    "CLOUD_SQL_VERBINDING",
    "LEES_CLOUD_SQL_VERBINDING",  # 17-09: leesreplica rlz-sql2-lees (Feiten eerst)
    "WEBAUTHN_RP_ID",
    "WEBAUTHN_ORIGINS",
    "ANDROID_CERT_SHA256_VINGERAFDRUKKEN",
    "CORS_ALLOWED_ORIGINS",
    "APPLE_TEAM_ID",
    "DOCUMENT_GCS_BUCKET",
    "KMS_MASTERKEY_SLEUTEL",
    "CIJFERS_SYNC_JOB_RESOURCE",
    "BANK_SYNC_JOB_RESOURCE",
    "EXTRACTIE_WACHTRIJ_JOB_RESOURCE",
    "BOEK_WACHTRIJ_JOB_RESOURCE",  # boeken sneller 18-09
    "EERSTE_SYNC_JOB_RESOURCE",
    "TERUGKEREND_HERBEREKEN_JOB_RESOURCE",
    "RECONCILIATIE_JOB_RESOURCE",
    "INTAKE_IMAP_JOB_RESOURCE",  # 23-09: "Nu verwerken" op de postvak-bevinding start de intake-job
    "INTAKE_KEMPENGROEP_IMAP_JOB_RESOURCE",
    "KVK_BASE_URL",
    # tot 16-09 in losse `services update`-stappen:
    "INTAKE_POSTVAK_ADRES",
    "STORE_LINK_IOS",
    "STORE_APP_VERSIE_IOS",  # 17-09: Apple 1.1 live
    "BERICHTEN_SMTP_HOST",
    "BERICHTEN_SMTP_POORT",
    "BERICHTEN_SMTP_GEBRUIKER",
    "BERICHTEN_AFZENDER",
    "BERICHTEN_REPLY_TO",
    "APP_BASIS_URL",
    "APNS_SANDBOX",
    "FCM_PROJECT_ID",
    # OTA (16-09): bundel-bucket, minimale schilversie en de deploy-zijdige kill-switch
    "APP_BUNDEL_GCS_BUCKET",
    "APP_MIN_RUNTIME_VERSIE",
    "OTA_UITGESCHAKELD",
}
SERVICE_SECRET_SLEUTELS = {
    "APP_DB_WACHTWOORD",
    "JWT_SECRET",
    "TOTP_MASTER_KEY_B64",
    "PROJECTAANVRAAG_HMAC_SECRET",
    "ANTHROPIC_API_KEY",
    "REGISTERSYNC_HMAC_SECRET",
    "KVK_API_KEY",
    # tot 16-09 in losse `services update`-stappen:
    "BERICHTEN_SMTP_WACHTWOORD",
    "PUSH_VAPID_PRIVATE_KEY",
    "PUSH_VAPID_PUBLIC_KEY",
    "APNS_KEY_P8",
    "APNS_KEY_ID",
}
#: Jobs die mailen (app.berichten.mail) — hun case-tak in de lus draagt de gedeelde mail-envset.
MAILENDE_JOBS = {
    "rlz-reconciliatie",
    "rlz-bewaking",
    "rlz-accordeur-herinneringen",
    "rlz-nieuwe-facturen",
    "rlz-uren-herinneringen",  # run B 18-09: push-anders-mail
    "rlz-kantoor-digest",
}


def _tekst() -> str:
    return DEPLOY_YML.read_text(encoding="utf-8")


def _commando_regels(tekst: str) -> str:
    return "\n".join(r for r in tekst.splitlines() if not r.lstrip().startswith("#"))


def _service_stap(tekst: str) -> str:
    blokken = re.split(r"gcloud run deploy rlz-backend\b", _commando_regels(tekst))
    assert len(blokken) == 2, "precies één `gcloud run deploy rlz-backend`"
    return blokken[1].split("--quiet", 1)[0]


def _vlag(blok: str, naam: str) -> str:
    m = re.search(r"--" + naam + r'\s+"((?:[^"\\]|\\.)*)"', blok)
    assert m, f"--{naam} ontbreekt"
    return expandeer(m.group(1), workflow_env(_tekst()))


def _sleutels(lijst: str, scheider: str) -> set[str]:
    d = re.match(r"\^(.)\^(.*)$", lijst, flags=re.S)
    if d:
        scheider, lijst = d.group(1), d.group(2)
    return {p.split("=", 1)[0] for p in paren(scheider, lijst)}


def test_geen_losse_update_stappen_op_envs_of_secrets() -> None:
    """Fail-closed: élke `services update`/`jobs update` met env-/secret-vlaggen is een venster zonder config."""
    cmd = _commando_regels(_tekst())
    assert "gcloud run services update" not in cmd, (
        "service-config hoort in de ene `gcloud run deploy rlz-backend`-stap"
    )
    assert "gcloud run jobs update" not in cmd, "job-config hoort in de ene `gcloud run jobs deploy`-aanroep per job"
    assert "--update-env-vars" not in cmd and "--update-secrets" not in cmd


def test_service_stap_draagt_de_volledige_envset_en_alle_secrets() -> None:
    stap = _service_stap(_tekst())
    envs = _sleutels(_vlag(stap, "set-env-vars"), ",")
    secrets = _sleutels(_vlag(stap, "set-secrets"), ",")
    assert envs >= SERVICE_ENV_SLEUTELS, f"service-stap mist envs: {SERVICE_ENV_SLEUTELS - envs}"
    assert secrets >= SERVICE_SECRET_SLEUTELS, f"service-stap mist secrets: {SERVICE_SECRET_SLEUTELS - secrets}"


def test_mailkanaal_staat_in_de_service_stap() -> None:
    stap = _service_stap(_tekst())
    envs = _vlag(stap, "set-env-vars")
    assert "BERICHTEN_SMTP_HOST=smtp.gmail.com" in envs and "BERICHTEN_SMTP_GEBRUIKER=facturen@ak-nijenhuis.nl" in envs
    assert "BERICHTEN_SMTP_WACHTWOORD=BERICHTEN_SMTP_WACHTWOORD:latest" in _vlag(stap, "set-secrets")


def test_scheidingsteken_staat_in_geen_waarde_van_de_service_stap() -> None:
    stap = _service_stap(_tekst())
    ruw = _vlag(stap, "set-env-vars")
    d = re.match(r"\^(.)\^(.*)$", ruw, flags=re.S)
    assert d and d.group(1) == "|", "service-stap hoort het ^|^-scheidingsteken te dragen"
    for paar in paren("|", d.group(2)):
        assert re.match(r"^[A-Z][A-Z0-9_]*=", paar), f"fragment zonder KEY= (scheider in een waarde?): {paar[:80]!r}"
    # secrets: default ','-scheider — geen komma in naam of pad
    for paar in paren(",", _vlag(stap, "set-secrets")):
        assert re.match(r"^[A-Z][A-Z0-9_]*=[A-Za-z0-9_/-]+:latest$", paar), paar


def test_mail_envset_heeft_een_bron_voor_service_en_jobs() -> None:
    tekst = _tekst()
    constanten = workflow_env(tekst)
    assert set(paren("|", constanten["MAIL_ENVS"])) >= {
        "BERICHTEN_SMTP_HOST=smtp.gmail.com",
        "BERICHTEN_SMTP_GEBRUIKER=facturen@ak-nijenhuis.nl",
        "APP_BASIS_URL=https://app.administratiekantoornijenhuis.nl",
    }
    cmd = _commando_regels(tekst)
    # Geen letterlijke kopie van de mailhost buiten de constante: alles verwijst naar ${MAIL_ENVS}.
    letterlijk = [r for r in cmd.splitlines() if "BERICHTEN_SMTP_HOST=" in r and not r.startswith("  MAIL_ENVS:")]
    assert letterlijk == [], f"mailconfig letterlijk herhaald i.p.v. via ${{MAIL_ENVS}}: {letterlijk[:2]}"
    assert "${MAIL_ENVS}" in _service_stap(tekst)
    assert cmd.count("${MAIL_ENVS}") >= 4, "service + smoketest + case-takken van de jobs-lus"


def test_mailende_jobs_krijgen_de_mail_envset_in_hun_case_tak() -> None:
    cmd = _commando_regels(_tekst())
    lus = cmd.split('case "${NAAM}" in', 1)[1].split("esac", 1)[0]
    takken = re.findall(r"^\s*([a-z|-]+)\)\n((?:.*\n)*?)\s*.*;;", lus, flags=re.M)
    assert takken, "case-takken niet gevonden"
    met_mail: set[str] = set()
    for namen, body in takken:
        tak = body + lus.split(namen + ")", 1)[1].split(";;", 1)[0]
        if "${MAIL_ENVS}" in tak and "${MAIL_SECRETS}" in tak:
            met_mail.update(namen.split("|"))
    assert met_mail >= MAILENDE_JOBS, f"mailende jobs zonder mail-envset: {MAILENDE_JOBS - met_mail}"


def test_elke_job_een_deploy_met_set_env_vars_en_set_secrets() -> None:
    cmd = _commando_regels(_tekst())
    for blok in re.split(r"gcloud run jobs deploy ", cmd)[1:]:
        kop = blok.split("\n", 1)[0]
        vlaggen = blok.split("--quiet", 1)[0]
        assert "--set-env-vars" in vlaggen and "--set-secrets" in vlaggen, f"jobs-deploy zonder volledige config: {kop}"


def test_leesreplica_socket_en_env_op_service_en_alle_jobs_behalve_de_migratie() -> None:
    """Leesreplica afronden 17-09: zonder `--set-cloudsql-instances` mét de replica is er geen socket en geeft
    `POST /lezen/sql` 503 — service, F3-jobs én smoketest dragen beide instanties + LEES_CLOUD_SQL_VERBINDING; de
    migratie-job (owner-rol) blijft bewust alleen op de primary."""
    tekst = _tekst()
    lees = re.search(r"^\s*CLOUD_SQL_LEES:\s*(\S+)\s*$", tekst, flags=re.M)
    assert lees and lees.group(1) == "rlz-boekhouding:europe-west4:rlz-sql2-lees", "CLOUD_SQL_LEES ontbreekt in het env-blok"
    primary = re.search(r"^\s*CLOUD_SQL:\s*(\S+)\s*$", tekst, flags=re.M)
    assert primary
    env = {**workflow_env(tekst), "CLOUD_SQL_LEES": lees.group(1), "CLOUD_SQL": primary.group(1)}
    cmd = _commando_regels(tekst)
    instanties = re.findall(r'--set-cloudsql-instances\s+"([^"]+)"', cmd)
    assert len(instanties) >= 4, instanties
    met_lees = [expandeer(i, env) for i in instanties if "CLOUD_SQL_LEES" in i]
    zonder = [i for i in instanties if "CLOUD_SQL_LEES" not in i]
    assert len(zonder) == 1, f"alleen de migratie-job blijft op de primary alleen: {zonder}"
    for i in met_lees:
        assert i == "rlz-boekhouding:europe-west4:rlz-sql2,rlz-boekhouding:europe-west4:rlz-sql2-lees", i
    migratie = cmd.split("gcloud run jobs deploy rlz-migratie", 1)[1].split("--quiet", 1)[0]
    assert "CLOUD_SQL_LEES" not in migratie
    basis = re.search(r'BASIS_ENVS="([^"]+)"', cmd)
    assert basis and "LEES_CLOUD_SQL_VERBINDING=${CLOUD_SQL_LEES}" in basis.group(1)
