#!/usr/bin/env bash
# =============================================================================
# Native push (fase 3, iOS/APNs) — GEBUNDELDE afronding, zelfde grondhouding als
# notificaties_afronden.sh: één interactief, idempotent script dat álles doet.
#
# WIE DRAAIT DIT: het org-owner-account (Peter), NÁ het aanmaken van de
# APNs-sleutel (.p8) in het Apple Developer-portaal — de stappen daarvoor:
#   developer.apple.com → Account → Certificates, Identifiers & Profiles →
#   Keys → (+) → naam "RLZ Goedkeuren APNs" → vink "Apple Push Notifications
#   service (APNs)" aan → Configure: Environment "Sandbox & Production" →
#   Continue → Register → DOWNLOAD de .p8 (kan maar ÉÉN keer!) → noteer de
#   Key ID (10 tekens, staat ook in de bestandsnaam AuthKey_<KEYID>.p8).
#   NB: dit is het Developer-portaal, níét App Store Connect (daar leven alleen
#   de App Store Connect-API-keys). Team ID = VRQP26CX43 (staat al in deploy.yml).
#
# WAT ER GEBEURT, IN VOLGORDE (idempotent — veilig opnieuw te draaien):
#   1. secret-slots + accessors: APNS_KEY_P8 en APNS_KEY_ID, leesbaar voor
#      run-jobs@ (notificatie-jobs) én run-backend@ (registratie-endpoint is
#      fail-closed 409 zonder config; handmatige herinner-knop verstuurt vanuit
#      de service). Het Key ID is geen geheim, maar leeft bewust als slot zodat
#      deploy.yml waarde-vrij blijft (config-as-code zonder klikwaarden).
#   2. .p8 + Key ID in de slots — alleen als ze nog leeg zijn (stdin-patroon,
#      komt nergens in logs/chat; bewaar de .p8 daarna zelf in de wachtwoord-
#      kluis — Apple geeft 'm nooit opnieuw).
#   3. dezelfde service-/job-updates als de deploy.yml-stappen, maar per direct
#      (geen deploy-run nodig; de eerstvolgende deploy herbevestigt exact
#      dezelfde config). APNS_SANDBOX=false sinds 2026-08-23 (Xcode Cloud →
#      TestFlight is de doel-build, aps-environment 'production'); alleen voor
#      een dev-signed kabel-build-test tijdelijk true zetten (hier én in
#      deploy.yml, twee plekken) en daarna terugdraaien.
#   4. verificatiepoort: jij zet in de app meldingen aan (registratie mag nu
#      niet meer 409 geven) en dit script draait daarna één handmatige run van
#      rlz-accordeur-herinneringen — de push op het toestel is het bewijs.
#      De scheduler wordt hier NIET hervat (dat blijft de aparte groene poort
#      van notificaties_afronden.sh).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
JOBS_SA="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_SA="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}" --quiet

heeft_versie() {
  [ -n "$(gcloud secrets versions list "$1" --filter='state=enabled' --format='value(name)' --limit=1 2>/dev/null)" ]
}

echo "== Stap 1/4: secret-slots + accessors (idempotent) =="
maak_slot() {
  local NAAM="$1"
  if gcloud secrets describe "${NAAM}" >/dev/null 2>&1; then
    echo "   slot ${NAAM} bestaat al."
  else
    gcloud secrets create "${NAAM}" --replication-policy=user-managed --locations="${REGION}"
    echo "   slot ${NAAM} aangemaakt."
  fi
}
geef_accessor() {
  gcloud secrets add-iam-policy-binding "$1" \
    --member="serviceAccount:$2" \
    --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
}
maak_slot APNS_KEY_P8
geef_accessor APNS_KEY_P8 "${JOBS_SA}"
geef_accessor APNS_KEY_P8 "${BACKEND_SA}"
maak_slot APNS_KEY_ID
geef_accessor APNS_KEY_ID "${JOBS_SA}"
geef_accessor APNS_KEY_ID "${BACKEND_SA}"
echo "   accessors staan (jobs + backend — beide versturen; backend gate't ook de registratie)."

echo
echo "== Stap 2/4: .p8-sleutel + Key ID (alleen gevraagd als de slots leeg zijn) =="
P8_BESTAAT=false; ID_BESTAAT=false
heeft_versie APNS_KEY_P8 && P8_BESTAAT=true
heeft_versie APNS_KEY_ID && ID_BESTAAT=true
if $P8_BESTAAT && $ID_BESTAAT; then
  echo "   beide slots hebben al een versie — ongemoeid gelaten (sleutel en Key ID horen"
  echo "   bij elkaar; roteren = beide slots een nieuwe versie geven)."
elif $P8_BESTAAT || $ID_BESTAAT; then
  echo "   FOUT: er staat maar één helft (p8: ${P8_BESTAAT}, key-id: ${ID_BESTAAT})."
  echo "   De .p8 en het Key ID horen bij elkaar — vul de ontbrekende helft van dezelfde"
  echo "   sleutel aan, óf disable beide versies en draai dit script opnieuw."
  exit 1
else
  STANDAARD_P8="$(ls -t "${HOME}"/Downloads/AuthKey_*.p8 2>/dev/null | head -1 || true)"
  if [ -n "${STANDAARD_P8}" ]; then
    read -r -p "   Pad naar de .p8 [${STANDAARD_P8}]: " P8_PAD
    P8_PAD="${P8_PAD:-${STANDAARD_P8}}"
  else
    read -r -p "   Pad naar de gedownloade .p8 (AuthKey_<KEYID>.p8): " P8_PAD
  fi
  if [ ! -f "${P8_PAD}" ]; then echo "   FOUT: '${P8_PAD}' bestaat niet — gestopt."; exit 1; fi
  if ! grep -q "BEGIN PRIVATE KEY" "${P8_PAD}"; then
    echo "   FOUT: '${P8_PAD}' ziet er niet uit als een .p8 (PEM 'BEGIN PRIVATE KEY' ontbreekt)."
    exit 1
  fi
  BESTAND="$(basename "${P8_PAD}")"
  AFGELEID_ID="$(printf '%s' "${BESTAND}" | sed -n 's/^AuthKey_\([A-Z0-9]\{10\}\)\.p8$/\1/p')"
  if [ -n "${AFGELEID_ID}" ]; then
    read -r -p "   Key ID [${AFGELEID_ID}]: " KEY_ID
    KEY_ID="${KEY_ID:-${AFGELEID_ID}}"
  else
    read -r -p "   Key ID (10 tekens, uit het Developer-portaal): " KEY_ID
  fi
  if ! printf '%s' "${KEY_ID}" | grep -Eq '^[A-Z0-9]{10}$'; then
    echo "   FOUT: '${KEY_ID}' is geen geldig Key ID (10 tekens A–Z/0–9) — gestopt."
    exit 1
  fi
  cat "${P8_PAD}" | gcloud secrets versions add APNS_KEY_P8 --data-file=- >/dev/null
  printf '%s' "${KEY_ID}" | gcloud secrets versions add APNS_KEY_ID --data-file=- >/dev/null
  echo "   sleutel + Key ID in de slots gezet."
  echo "   ⚠️  Bewaar ${BESTAND} nu zelf in de wachtwoordkluis en haal 'm uit Downloads —"
  echo "   Apple geeft de .p8 nooit opnieuw; Secret Manager is vanaf nu de werk-kopie."
fi

echo
echo "== Stap 3/4: service + notificatie-jobs per direct bijwerken (spiegel van deploy.yml) =="
# APNS_SANDBOX=false: TestFlight-/App Store-builds zijn production-signed (zie kop; spiegel
# van deploy.yml — een her-run mag de live config nooit terug naar sandbox zetten).
gcloud run services update rlz-backend \
  --region "${REGION}" \
  --update-env-vars "APNS_SANDBOX=false" \
  --update-secrets "APNS_KEY_P8=APNS_KEY_P8:latest,APNS_KEY_ID=APNS_KEY_ID:latest" \
  --quiet
echo "   rlz-backend bijgewerkt (registratie-endpoint is nu open i.p.v. 409)."
for NJOB in rlz-accordeur-herinneringen rlz-nieuwe-facturen; do
  gcloud run jobs update "${NJOB}" \
    --region "${REGION}" \
    --update-env-vars "APNS_SANDBOX=false,APPLE_TEAM_ID=VRQP26CX43" \
    --update-secrets "APNS_KEY_P8=APNS_KEY_P8:latest,APNS_KEY_ID=APNS_KEY_ID:latest" \
    --quiet
  echo "   ${NJOB} bijgewerkt."
done

echo
echo "== Stap 4/4: bewijs-push (verificatiepoort) =="
echo "   DOE NU OP HET TOESTEL: open de Nijenhuis-app (nieuwe build!), ontgrendel, en zet"
echo "   de meldingen AAN via de meldingen-kaart op de wachtrij (iOS vraagt toestemming)."
echo "   Vereist: een OPEN accordering voor dit account — staat er geen (bv. weggewerkt"
echo "   in een eerdere kliktest), seed 'm eerst opnieuw met"
echo "   backend/scripts/cloud_seed_accordering.py (aanwijzingen in de docstring)."
read -r -p "   Meldingen staan aan op het toestel? Dan stuur ik nu de herinnering-job [j/N]: " ANTWOORD
if [[ "${ANTWOORD}" =~ ^[jJ]$ ]]; then
  gcloud run jobs execute rlz-accordeur-herinneringen --region="${REGION}" --wait
  echo
  echo "   Job-run klaar. Kwam de push binnen (banner 'Herinnering…', tap opent de app op"
  echo "   het document)? Dan is fase 3-iOS bewezen — leg het vast in de kliktest-checklist."
  echo "   GEEN push gezien? Twee bekende oorzaken:"
  echo "     • vandaag is er al een herinnering voor deze accordeur verstuurd (idempotent"
  echo "       per dag) — gebruik dan de handmatige herinner-knop in de kantoor-UI"
  echo "       (klantpagina → accorderingssectie; max 1 per document per dag), of test morgen;"
  echo "     • logs: gcloud logging read 'resource.labels.job_name=rlz-accordeur-herinneringen' --limit=20"
  echo "       (BadDeviceToken bij sandbox/productie-mismatch: APNS_SANDBOX staat op false"
  echo "       — TestFlight/App Store; een dev-signed kabel-build vergt tijdelijk true)."
else
  echo "   Overgeslagen — draai dit script later opnieuw (alles hierboven is idempotent),"
  echo "   of stuur de bewijs-push via de handmatige herinner-knop in de kantoor-UI."
fi
echo
echo "KLAAR. De 09:00-scheduler blijft zoals hij stond (de groene-verificatie-poort van"
echo "notificaties_afronden.sh gaat over het hervatten — dit script raakt 'm niet aan)."
