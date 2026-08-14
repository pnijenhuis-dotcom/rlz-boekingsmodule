#!/usr/bin/env bash
# =============================================================================
# F1 — Data (docs/GCP_UITROL.md §F1): Cloud SQL, Secret Manager, KMS, bucket.
#
# WIE DRAAIT DIT: Peter (org-owner-account, Cloud Shell of lokale gcloud).
# Code voert niets uit; na deze run volgen scripts/gcp/f1_migratie.sh (Alembic
# tegen de nieuwe instantie) en scripts/gcp/f1_verificatie.py (GCS + KMS).
#
# IDEMPOTENT (F0-les 2026-08-15): describe-vóór-create op élke resource —
# herdraaien na een deelfout is altijd veilig; bestaande resources worden
# overgeslagen, secrets krijgen nooit stil een tweede versie.
#
# SECRETS (besluit 0012): waarden komen NOOIT in code/logs/chat. Dit script
# genereert wachtwoorden/sleutels zelf (nooit geëchood) of vraagt ze
# interactief (stil, read -s). Alles landt uitsluitend in Secret Manager.
#
# Verwachte duur: de Cloud SQL-instantie-aanmaak is de lange pool (10–20 min).
# Dat is normaal — niet afbreken.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"                       # koppelcontract §2b, niet wijzigen

# --- Gedocumenteerde F1-keuzes (aanpasbaar, maar dit zijn de defaults) -------
SQL_INSTANCE="rlz-sql"                      # instantienaam
SQL_TIER="db-custom-1-3840"                 # 1 vCPU / 3,75 GB — kleinste HA-waardige
                                            # Enterprise-tier; verticaal schalen kan
                                            # later zonder herbouw (kort herstart-moment)
DB_NAAM="boekhouding"                       # zelfde naam als lokaal
BUCKET="rlz-boekhouding-documenten"         # documentenbucket (globaal uniek)
KEYRING="rlz"                               # KMS-keyring
KMS_KEY="masterkey"                         # CryptoKey voor de envelope-masterkey
RETENTIE_SECONDEN="220903200s"              # 7 jaar (7 × 365,25 dagen — bewaarplicht),
                                            # beslispunt 7: UNLOCKED (nooit `lock` draaien)

RUN_BACKEND="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"
RUN_JOBS="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}" --quiet

echo "== F1 voor project ${PROJECT_ID}, regio ${REGION} =="

# ----------------------------------------------------------------------------
# 0. API's (stonden al aan sinds F0 — her-verzekeren is gratis en idempotent)
# ----------------------------------------------------------------------------
gcloud services enable sqladmin.googleapis.com secretmanager.googleapis.com \
  cloudkms.googleapis.com storage.googleapis.com --quiet

# ----------------------------------------------------------------------------
# 1. SECRET MANAGER — helpers
#    Replicatie MOET user-managed europe-west4 zijn: 'automatic' repliceert
#    wereldwijd en botst met de EU-locatie-org-policy (én met de regio-pin).
# ----------------------------------------------------------------------------

secret_bestaat() { gcloud secrets describe "$1" >/dev/null 2>&1; }

secret_heeft_versie() {
  [[ -n "$(gcloud secrets versions list "$1" --filter="state=ENABLED" \
       --format="value(name)" --limit=1 2>/dev/null)" ]]
}

maak_secret_leeg() { # alleen de container, nog geen waarde
  secret_bestaat "$1" || gcloud secrets create "$1" \
    --replication-policy="user-managed" --locations="${REGION}"
}

zet_secret_waarde_indien_leeg() { # $1=naam, waarde via stdin — nooit als argument
  if secret_heeft_versie "$1"; then
    echo "   ${1}: heeft al een versie — ongemoeid gelaten (rotatie = bewuste actie)."
  else
    gcloud secrets versions add "$1" --data-file=- >/dev/null
    echo "   ${1}: versie gezet."
  fi
}

# Wachtwoorden URL-safe genereren (komen in verbindings-URL's terecht — geen
# '+', '/' of '=' die percent-encoding zouden vergen). NB bewust geen `head -c`
# in de pipeline: SIGPIPE + pipefail zou het script onterecht laten stoppen.
genereer_urlsafe() {
  local ruw
  ruw="$(openssl rand -base64 48 | tr '+/' '-_' | tr -d '=')"
  printf '%s' "${ruw:0:$1}"
}

# 1.1 DB-wachtwoorden: genereren als het secret nog geen versie heeft.
#     DB_OWNER_WACHTWOORD = de postgres-rol (DDL/migraties, alleen migratie-job
#     + beheer); APP_DB_PASSWORD = boekhouding_app (least privilege + RLS; de
#     ROL zelf wordt door Alembic-migratie 0001 aangemaakt met dit wachtwoord).
for s in DB_OWNER_WACHTWOORD APP_DB_PASSWORD; do
  maak_secret_leeg "$s"
  if ! secret_heeft_versie "$s"; then
    genereer_urlsafe 32 | zet_secret_waarde_indien_leeg "$s"
  else
    echo "   ${s}: bestond al met versie."
  fi
done

# 1.2 App-secrets met verse waarden (JWT_SECRET: NOOIT de dev-waarde hergebruiken;
#     TOTP_MASTER_KEY: vers, base64 van 32 bytes — met KMS actief (beslispunt 8)
#     is dit alleen het fallback-slot van app/security/envelope.py, maar het mag
#     nooit leeg-of-dev zijn zodra ENVIRONMENT=production).
maak_secret_leeg JWT_SECRET
secret_heeft_versie JWT_SECRET || openssl rand -base64 48 | zet_secret_waarde_indien_leeg JWT_SECRET
maak_secret_leeg TOTP_MASTER_KEY
secret_heeft_versie TOTP_MASTER_KEY || openssl rand -base64 32 | zet_secret_waarde_indien_leeg TOTP_MASTER_KEY

# 1.3 Interactieve secrets — waarde alleen als Peter 'm nu heeft; Enter = overslaan.
#     WEBHOOK_HMAC_SECRET: gedeeld met vastgoed, vastgoed levert (F4) — de
#     container staat vast klaar; alternatief blijft de F4-ontvangstvoorkeur
#     (secret in vastly-504108 met accessor voor onze SA's).
#     ANTHROPIC_API_KEY: uit de Anthropic-console.
for s in WEBHOOK_HMAC_SECRET ANTHROPIC_API_KEY; do
  maak_secret_leeg "$s"
  if secret_heeft_versie "$s"; then
    echo "   ${s}: bestond al met versie."
  else
    read -r -s -p "   Waarde voor ${s} (Enter = nu overslaan, later toevoegen): " waarde; echo
    if [[ -n "${waarde}" ]]; then
      printf '%s' "${waarde}" | zet_secret_waarde_indien_leeg "$s"
    else
      echo "   ${s}: overgeslagen — container bestaat, versie volgt later."
    fi
    unset waarde
  fi
done

# 1.4 Secret-bindings (draaiboek F0.4-naschrift: per-resource, dus hier in F1).
#     Runtime-SA's lezen de app-secrets; DB_OWNER_WACHTWOORD is alléén voor de
#     migratie-job (run-jobs@) — run-backend@ krijgt 'm bewust niet.
for s in JWT_SECRET TOTP_MASTER_KEY WEBHOOK_HMAC_SECRET ANTHROPIC_API_KEY APP_DB_PASSWORD; do
  for sa in "${RUN_BACKEND}" "${RUN_JOBS}"; do
    gcloud secrets add-iam-policy-binding "$s" \
      --member="serviceAccount:${sa}" \
      --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
  done
done
gcloud secrets add-iam-policy-binding DB_OWNER_WACHTWOORD \
  --member="serviceAccount:${RUN_JOBS}" \
  --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
echo "== Secrets + bindings staan =="
gcloud secrets list --format="table(name,replication.userManaged.replicas[0].location)"

# ----------------------------------------------------------------------------
# 2. CLOUD SQL — PostgreSQL 16 (PG16 gepind: lokaal draait bewust ook 16,
#    nooit een nieuwere major dan lokaal), HA (REGIONAL) + PITR + backups.
#    Netwerkkeuze: publiek IP ZONDER authorized networks — verbinden kan
#    uitsluitend via de Cloud SQL Auth Proxy/connector (IAM + TLS); privé-IP
#    zou een VPC-connector voor Cloud Run vergen — bewust niet (geen extra
#    bewegende delen, zelfde afweging als frontend-hosting beslispunt 4).
# ----------------------------------------------------------------------------

if gcloud sql instances describe "${SQL_INSTANCE}" >/dev/null 2>&1; then
  echo "== Cloud SQL-instantie ${SQL_INSTANCE} bestaat al — aanmaak overgeslagen =="
else
  echo "== Cloud SQL-instantie ${SQL_INSTANCE} aanmaken (duurt 10–20 min, niet afbreken) =="
  gcloud sql instances create "${SQL_INSTANCE}" \
    --database-version=POSTGRES_16 \
    --edition=enterprise \
    --tier="${SQL_TIER}" \
    --region="${REGION}" \
    --availability-type=REGIONAL \
    --backup-start-time=02:00 \
    --enable-point-in-time-recovery \
    --retained-transaction-log-days=7 \
    --storage-type=SSD \
    --storage-size=10GB \
    --storage-auto-increase \
    --maintenance-window-day=SUN \
    --maintenance-window-hour=4
fi
# Verificatie: versie/HA/PITR zichtbaar.
gcloud sql instances describe "${SQL_INSTANCE}" --format="value(databaseVersion,settings.availabilityType,settings.backupConfiguration.pointInTimeRecoveryEnabled)"

# 2.1 postgres-wachtwoord (owner-rol) uit het secret — altijd zetten is
#     idempotent (zelfde waarde opnieuw zetten verandert niets) en herstelt
#     een eerdere half-gelukte run.
OWNER_PW="$(gcloud secrets versions access latest --secret=DB_OWNER_WACHTWOORD)"
gcloud sql users set-password postgres --instance="${SQL_INSTANCE}" --password="${OWNER_PW}" --quiet
unset OWNER_PW
echo "   postgres-wachtwoord gezet vanuit secret DB_OWNER_WACHTWOORD."

# 2.2 Database boekhouding (schema's platform+boekhouding + rol boekhouding_app
#     komen uit de Alembic-keten — f1_migratie.sh, géén handwerk hier).
gcloud sql databases describe "${DB_NAAM}" --instance="${SQL_INSTANCE}" >/dev/null 2>&1 || \
  gcloud sql databases create "${DB_NAAM}" --instance="${SQL_INSTANCE}"
gcloud sql databases list --instance="${SQL_INSTANCE}" --format="value(name)"

# ----------------------------------------------------------------------------
# 3. KMS (beslispunt 8: Cloud KMS meteen — koppelcontract §2b-norm).
#    De KmsMasterKeyProvider (app/security/envelope.py) bestaat al; hier alleen
#    de resource + bindings. Automatische rotatie 1×/jaar: oude key-versies
#    blijven bestaan, dus eerder gewrapte data-keys blijven ontsleutelbaar —
#    geen herversleutel-actie nodig bij KMS-interne rotatie.
# ----------------------------------------------------------------------------

gcloud kms keyrings describe "${KEYRING}" --location="${REGION}" >/dev/null 2>&1 || \
  gcloud kms keyrings create "${KEYRING}" --location="${REGION}"

if ! gcloud kms keys describe "${KMS_KEY}" --keyring="${KEYRING}" --location="${REGION}" >/dev/null 2>&1; then
  if date -u -d '+365 days' +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    VOLGENDE_ROTATIE="$(date -u -d '+365 days' +%Y-%m-%dT%H:%M:%SZ)"   # GNU (Cloud Shell)
  else
    VOLGENDE_ROTATIE="$(date -u -v+365d +%Y-%m-%dT%H:%M:%SZ)"          # BSD (macOS)
  fi
  gcloud kms keys create "${KMS_KEY}" \
    --keyring="${KEYRING}" --location="${REGION}" \
    --purpose=encryption \
    --rotation-period=365d \
    --next-rotation-time="${VOLGENDE_ROTATIE}"
fi

# 3.1 Encrypt/decrypt voor de twee runtime-SA's — op de KEY, niet projectbreed.
for sa in "${RUN_BACKEND}" "${RUN_JOBS}"; do
  gcloud kms keys add-iam-policy-binding "${KMS_KEY}" \
    --keyring="${KEYRING}" --location="${REGION}" \
    --member="serviceAccount:${sa}" \
    --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" --quiet >/dev/null
done
# 3.2 Ook voor het uitvoerende account zelf: nodig voor f1_verificatie.py
#     (het KMS-wrap/unwrap-rondje via ADC) — owner-basisrol dekt KMS-datapad
#     niet gegarandeerd. Bewust en zichtbaar; desgewenst later intrekken.
HUIDIG_ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
gcloud kms keys add-iam-policy-binding "${KMS_KEY}" \
  --keyring="${KEYRING}" --location="${REGION}" \
  --member="user:${HUIDIG_ACCOUNT}" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" --quiet >/dev/null

echo "== KMS staat =="
gcloud kms keys describe "${KMS_KEY}" --keyring="${KEYRING}" --location="${REGION}" \
  --format="value(name,purpose,rotationPeriod)"

# ----------------------------------------------------------------------------
# 4. DOCUMENTENBUCKET — 7 jaar retentie UNLOCKED (beslispunt 7), versioning
#    aan, uniform bucket-level access, public access prevention. objectAdmin
#    zo smal mogelijk: bucket-scoped voor alléén de twee runtime-SA's.
# ----------------------------------------------------------------------------

gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention

# Idempotente updates (herhalen = zelfde eindtoestand). NOOIT `retention lock`
# draaien: beslispunt 7 is bewust unlocked tot het WORM-export-besluit.
gcloud storage buckets update "gs://${BUCKET}" \
  --versioning \
  --retention-period="${RETENTIE_SECONDEN}"

for sa in "${RUN_BACKEND}" "${RUN_JOBS}"; do
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${sa}" \
    --role="roles/storage.objectAdmin" >/dev/null
done

echo "== Bucket staat (retentie + versioning zichtbaar) =="
gcloud storage buckets describe "gs://${BUCKET}" \
  --format="value(location,retentionPolicy.retentionPeriod,retentionPolicy.isLocked,versioning.enabled)"

# ----------------------------------------------------------------------------
# 5. SLOT — waarden voor Code (resourcenamen, geen secrets)
# ----------------------------------------------------------------------------
CONNECTION_NAME="$(gcloud sql instances describe "${SQL_INSTANCE}" --format='value(connectionName)')"
cat <<EOF

================================================================================
F1-RESOURCES STAAN. Waarden voor Code / de Cloud Run-config (geen secrets):

  SQL-instantie (connection name) = ${CONNECTION_NAME}
  Database                        = ${DB_NAAM}
  KMS_MASTERKEY_SLEUTEL           = projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KMS_KEY}
  DOCUMENT_GCS_BUCKET             = ${BUCKET}

Volgende stappen (Code, zie docs/GCP_UITROL.md §F1-uitvoering):
  1. scripts/gcp/f1_migratie.sh   — Alembic 0001→head via de Cloud SQL Auth
                                    Proxy + alembic check (metadata-guard)
  2. backend/.venv/bin/python scripts/gcp/f1_verificatie.py
                                  — GCS-upload/teruglezen + KMS-wrap/unwrap
NB: WEBHOOK_HMAC_SECRET/ANTHROPIC_API_KEY zonder versie? Later toevoegen met:
  gcloud secrets versions add <NAAM> --data-file=-   (waarde via stdin)
================================================================================
EOF
