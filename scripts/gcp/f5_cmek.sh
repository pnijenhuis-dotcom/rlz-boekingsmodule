#!/usr/bin/env bash
# =============================================================================
# F5 — CMEK-uitvoering (platformbesluit 0021, akkoord Peter 2026-08-15):
# twee CMEK-keys op keyring `rlz`, Cloud SQL-herbouw als `rlz-sql2` mét
# --disk-encryption-key, en de default-CMEK-key op de bestaande documentenbucket.
#
# WIE DRAAIT DIT: het org-owner-account (Peter / owner-gcloud) — zelfde recept
# als f1_data.sh. Na deze run volgen (Code): f1_migratie.sh (Alembic tegen
# rlz-sql2), f1_verificatie.py (GCS+KMS), bootstrap + accordeur-seed, service/
# jobs omhangen, en pas ná groene verificatie: f5_cmek_opruimen.sh (oude rlz-sql).
#
# IDEMPOTENT (F0-les): describe-vóór-create op élke resource — herdraaien na
# een deelfout is altijd veilig. Secrets blijven volledig ongemoeid (JWT/TOTP/
# DB-wachtwoorden/KMS-masterkey zijn instantie-onafhankelijk, memo §3 stap 5).
#
# WAAROM HERBOUW: CMEK op Cloud SQL kan uitsluitend bij instantie-aanmaak
# (besluit 0021 §3). Nieuwe naam rlz-sql2: een verwijderde instantienaam is
# tot ~1 week gereserveerd — zo hoeft de oude pas wég ná groene verificatie.
#
# Verwachte duur: de Cloud SQL-aanmaak is de lange pool (10–20 min) — normaal,
# niet afbreken.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
PROJECT_NUMBER="652591056217"
REGION="europe-west4"                       # koppelcontract §2b, niet wijzigen

SQL_INSTANCE="rlz-sql2"                     # herbouw-instantie (besluit 0021 §4)
SQL_TIER="db-custom-1-3840"                 # identiek aan f1_data.sh (F1-keuzes)
DB_NAAM="boekhouding"
BUCKET="rlz-boekhouding-documenten"
KEYRING="rlz"                               # bestaat al (F1, draagt masterkey)
KEY_SQL="cmek-sql"                          # aparte keys per service: apart
KEY_DOC="cmek-documenten"                   # intrekbaar, kleinere blast-radius

KEY_SQL_PAD="projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KEY_SQL}"
KEY_DOC_PAD="projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KEY_DOC}"

gcloud config set project "${PROJECT_ID}" --quiet
echo "== F5-CMEK (besluit 0021) voor project ${PROJECT_ID}, regio ${REGION} =="

# ----------------------------------------------------------------------------
# 1. CMEK-KEYS op de bestaande keyring `rlz` — jaarrotatie zoals masterkey
#    (oude versies blijven ontsleutelbaar; NOOIT `destroy` draaien: key weg =
#    data + backups definitief weg — memo §2).
# ----------------------------------------------------------------------------
for KEY in "${KEY_SQL}" "${KEY_DOC}"; do
  if gcloud kms keys describe "${KEY}" --keyring="${KEYRING}" --location="${REGION}" >/dev/null 2>&1; then
    echo "   KMS-key ${KEY}: bestaat al — overgeslagen."
  else
    if date -u -d '+365 days' +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
      VOLGENDE_ROTATIE="$(date -u -d '+365 days' +%Y-%m-%dT%H:%M:%SZ)"   # GNU (Cloud Shell)
    else
      VOLGENDE_ROTATIE="$(date -u -v+365d +%Y-%m-%dT%H:%M:%SZ)"          # BSD (macOS)
    fi
    gcloud kms keys create "${KEY}" \
      --keyring="${KEYRING}" --location="${REGION}" \
      --purpose=encryption \
      --rotation-period=365d \
      --next-rotation-time="${VOLGENDE_ROTATIE}"
    echo "   KMS-key ${KEY}: aangemaakt (jaarrotatie)."
  fi
done

# ----------------------------------------------------------------------------
# 2. SERVICE-AGENTS + BINDINGS — dit zijn Google-beheerde agents per project
#    (níét onze run-SA's): Cloud SQL resp. GCS versleutelen er de disk/objecten
#    mee. `services identity create` is idempotent en garandeert dat de agent
#    bestaat; binding op de KEY, niet projectbreed (least privilege).
# ----------------------------------------------------------------------------
SQL_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
# NB: fout hier NIET wegslikken (les eerste run 2026-08-14: een gefaalde
# identity-create + weggeslikte fout = "does not exist" bij de binding).
gcloud beta services identity create --service=sqladmin.googleapis.com \
  --project="${PROJECT_ID}"
# GCS: --authorize-cmek provisioneert de agent én zet de key-binding in één
# stap (les tweede run: de agent bestaat pas na provisioning; een kale
# add-iam-policy-binding faalt dan op "does not exist").
gcloud storage service-agent --project="${PROJECT_ID}" --authorize-cmek="${KEY_DOC_PAD}"

# De agent-aanmaak is eventueel-consistent — korte retry op de binding.
for poging in $(seq 1 6); do
  if gcloud kms keys add-iam-policy-binding "${KEY_SQL}" \
    --keyring="${KEYRING}" --location="${REGION}" \
    --member="serviceAccount:${SQL_AGENT}" \
    --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" --quiet >/dev/null 2>&1; then
    break
  fi
  [[ "${poging}" -lt 6 ]] || { echo "STOP: binding op ${KEY_SQL} blijft falen (agent nog niet zichtbaar?)." >&2; exit 1; }
  echo "   binding ${KEY_SQL}: agent nog niet zichtbaar — opnieuw over 10 s (${poging}/6)…"
  sleep 10
done
echo "   Bindings gezet: ${KEY_SQL} → Cloud SQL-agent, ${KEY_DOC} → GCS-agent (via --authorize-cmek)."

# ----------------------------------------------------------------------------
# 3. CLOUD SQL rlz-sql2 — identiek f1_data.sh-recept, plus --disk-encryption-key.
#    PG16 gepind, REGIONAL (HA) + PITR 7 dagen + backups 02:00, publiek IP
#    zonder authorized networks (alleen Auth Proxy/connector).
# ----------------------------------------------------------------------------
if gcloud sql instances describe "${SQL_INSTANCE}" >/dev/null 2>&1; then
  echo "== Cloud SQL-instantie ${SQL_INSTANCE} bestaat al — aanmaak overgeslagen =="
else
  echo "== Cloud SQL-instantie ${SQL_INSTANCE} aanmaken mét CMEK (10–20 min, niet afbreken) =="
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
    --maintenance-window-hour=4 \
    --disk-encryption-key="${KEY_SQL_PAD}"
fi
echo "-- CMEK-bewijs (diskEncryptionConfiguration moet de key tonen):"
gcloud sql instances describe "${SQL_INSTANCE}" \
  --format="value(databaseVersion,settings.availabilityType,settings.backupConfiguration.pointInTimeRecoveryEnabled,diskEncryptionConfiguration.kmsKeyName)"

# 3.1 postgres-wachtwoord uit het BESTAANDE secret (idempotent — zelfde waarde
#     opnieuw zetten verandert niets; secrets zijn instantie-onafhankelijk).
OWNER_PW="$(gcloud secrets versions access latest --secret=DB_OWNER_WACHTWOORD)"
gcloud sql users set-password postgres --instance="${SQL_INSTANCE}" --password="${OWNER_PW}" --quiet
unset OWNER_PW
echo "   postgres-wachtwoord gezet vanuit secret DB_OWNER_WACHTWOORD."

# 3.2 Database (schema's + rol boekhouding_app komen uit de Alembic-keten —
#     f1_migratie.sh, géén handwerk hier).
gcloud sql databases describe "${DB_NAAM}" --instance="${SQL_INSTANCE}" >/dev/null 2>&1 || \
  gcloud sql databases create "${DB_NAAM}" --instance="${SQL_INSTANCE}"

# ----------------------------------------------------------------------------
# 4. BUCKET default-CMEK-key — kan wél op de bestaande bucket; geldt voor alle
#    NIEUWE objecten (dus vóór tranche 2 gezet = alle klantdocumenten CMEK).
#    Het bestaande F1-verificatie-testobject blijft Google-default versleuteld
#    (retentie verbiedt verwijderen; geen klantdata — gedocumenteerd, memo §3).
# ----------------------------------------------------------------------------
gcloud storage buckets update "gs://${BUCKET}" --default-encryption-key="${KEY_DOC_PAD}"
echo "-- Bucket-bewijs (default_kms_key):"
gcloud storage buckets describe "gs://${BUCKET}" --format="value(default_kms_key)"

# ----------------------------------------------------------------------------
# 5. SLOT — waarden voor Code (resourcenamen, geen secrets)
# ----------------------------------------------------------------------------
CONNECTION_NAME="$(gcloud sql instances describe "${SQL_INSTANCE}" --format='value(connectionName)')"
cat <<EOF

================================================================================
F5-CMEK-RESOURCES STAAN (besluit 0021 §6 stap 1/2/5-Peter-kant).

  SQL-instantie (connection name) = ${CONNECTION_NAME}
  CMEK Cloud SQL                  = ${KEY_SQL_PAD}
  CMEK documenten (bucket-default)= ${KEY_DOC_PAD}

Volgende stappen (Code, besluit 0021 §6 stap 3/4/5):
  1. scripts/gcp/f1_migratie.sh          — Alembic 0001→head + metadata-guard (wijst nu naar ${SQL_INSTANCE})
  2. backend/.venv/bin/python scripts/gcp/f1_verificatie.py
  3. bootstrap-beheerder + accordeur-seed (nieuwe activeerlinks)
  4. Cloud Run-service + jobs omhangen naar ${SQL_INSTANCE} (deploy.yml is al om;
     eenmalige gcloud-update overbrugt tot de volgende push-deploy)
  5. PAS NÁ groene verificatie: scripts/gcp/f5_cmek_opruimen.sh (oude rlz-sql)
================================================================================
EOF
