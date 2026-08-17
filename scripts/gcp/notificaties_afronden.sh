#!/usr/bin/env bash
# =============================================================================
# Accordeur-notificaties — GEBUNDELDE afronding (opdracht Peter 2026-08-15:
# geen losse terminal-stappen meer). Eén interactief, idempotent script dat
# álles doet; alleen het SMTP-app-wachtwoord wordt aan jou gevraagd.
#
# WIE DRAAIT DIT: het org-owner-account (Peter) — zelfde grondhouding als
# notificaties_infra.sh (dat script blijft bestaan voor wie alleen de slots
# wil; dit script omvat het volledig).
#
# WAT ER GEBEURT, IN VOLGORDE (elke stap meldt zichzelf en slaat over wat al
# gedaan is — het script is veilig opnieuw te draaien):
#   1. secret-slots + accessors (idempotent, als notificaties_infra.sh);
#   2. VAPID-sleutelpaar: zelf genereren en direct in de slots zetten —
#      bestaan er al versies, dan worden die GERESPECTEERD (nooit dubbel;
#      een half paar = stoppen met uitleg, want de twee helften moeten
#      bij elkaar horen);
#   3. SMTP-app-wachtwoord: alleen gevraagd als het slot nog leeg is
#      (stille invoer, komt nergens in logs/chat);
#   4. deploy triggeren (gh workflow run; geen gh = duidelijke instructie)
#      zodat de nieuwe revisie de secrets mount;
#   5. één handmatige run van rlz-accordeur-herinneringen (--wait);
#   6. scheduler hervatten — pas nádat jij bevestigt dat je 1 push op de
#      iPhone-PWA óf 1 mail hebt gezien (groene-verificatie-poort).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
JOBS_SA="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_SA="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VAPID_PY="${REPO_ROOT}/backend/.venv/bin/python"
VAPID_SCRIPT="${REPO_ROOT}/scripts/genereer_vapid_sleutels.py"

gcloud config set project "${PROJECT_ID}" --quiet

heeft_versie() {
  # 0 = het secret heeft minstens één ENABLED versie (bestaande waarden respecteren).
  [ -n "$(gcloud secrets versions list "$1" --filter='state=enabled' --format='value(name)' --limit=1 2>/dev/null)" ]
}

echo "== Stap 1/6: secret-slots + accessors (idempotent) =="
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
maak_slot BERICHTEN_SMTP_WACHTWOORD
geef_accessor BERICHTEN_SMTP_WACHTWOORD "${JOBS_SA}"
geef_accessor BERICHTEN_SMTP_WACHTWOORD "${BACKEND_SA}"
maak_slot PUSH_VAPID_PRIVATE_KEY
geef_accessor PUSH_VAPID_PRIVATE_KEY "${JOBS_SA}"
# HERZIEN 2026-08-17 (bewijs-push-502): óók run-backend@ — de handmatige herinner-knop
# (migratie 0053) pusht per direct vanuit de service; "alléén de job" liet webpush daar stil
# wegvallen. deploy.yml mount de private key sindsdien ook op de service.
geef_accessor PUSH_VAPID_PRIVATE_KEY "${BACKEND_SA}"
maak_slot PUSH_VAPID_PUBLIC_KEY
geef_accessor PUSH_VAPID_PUBLIC_KEY "${JOBS_SA}"
geef_accessor PUSH_VAPID_PUBLIC_KEY "${BACKEND_SA}"
echo "   accessors staan (jobs én backend: alle drie)."

echo
echo "== Stap 2/6: VAPID-sleutelpaar (zelf genereren, bestaande versies respecteren) =="
PRIV_BESTAAT=false; PUB_BESTAAT=false
heeft_versie PUSH_VAPID_PRIVATE_KEY && PRIV_BESTAAT=true
heeft_versie PUSH_VAPID_PUBLIC_KEY && PUB_BESTAAT=true
if $PRIV_BESTAAT && $PUB_BESTAAT; then
  echo "   beide sleutel-slots hebben al een versie — ongemoeid gelaten (bestaande"
  echo "   push-subscripties blijven zo geldig)."
elif $PRIV_BESTAAT || $PUB_BESTAAT; then
  echo "   FOUT: er staat maar één helft van het sleutelpaar (private: ${PRIV_BESTAAT},"
  echo "   public: ${PUB_BESTAAT}). De helften moeten bij elkaar horen — een verse helft"
  echo "   ernaast maakt push stuk. Oplossen: óf de ontbrekende helft van hetzelfde paar"
  echo "   alsnog toevoegen, óf beide versies disablen en dit script opnieuw draaien."
  exit 1
else
  SLEUTELS="$("${VAPID_PY}" "${VAPID_SCRIPT}" --kaal)"
  PRIV="$(echo "${SLEUTELS}" | sed -n 1p)"
  PUB="$(echo "${SLEUTELS}" | sed -n 2p)"
  printf '%s' "${PRIV}" | gcloud secrets versions add PUSH_VAPID_PRIVATE_KEY --data-file=- >/dev/null
  printf '%s' "${PUB}"  | gcloud secrets versions add PUSH_VAPID_PUBLIC_KEY  --data-file=- >/dev/null
  unset PRIV PUB SLEUTELS
  echo "   nieuw paar gegenereerd en in beide slots gezet (private key alleen in Secret"
  echo "   Manager — nergens anders)."
fi

echo
echo "== Stap 3/6: SMTP-app-wachtwoord (alleen gevraagd als het slot leeg is) =="
if heeft_versie BERICHTEN_SMTP_WACHTWOORD; then
  echo "   BERICHTEN_SMTP_WACHTWOORD heeft al een versie — ongemoeid gelaten."
else
  echo "   Nodig: het app-wachtwoord van facturen@ak-nijenhuis.nl (Google-account →"
  echo "   Beveiliging → App-wachtwoorden → nieuw wachtwoord met label 'RLZ berichten')."
  echo "   NB: dit is een ánder app-wachtwoord dan dat van de IMAP-intake — apart label,"
  echo "   zodat roteren onafhankelijk kan. Spaties uit de Google-weergave mag je laten"
  echo "   staan, die worden hier verwijderd. Invoer blijft onzichtbaar."
  read -r -s -p "   App-wachtwoord (label RLZ berichten): " SMTP_WW; echo
  SMTP_WW="${SMTP_WW// /}"
  if [ -z "${SMTP_WW}" ]; then echo "   FOUT: lege invoer — gestopt, niets gezet."; exit 1; fi
  printf '%s' "${SMTP_WW}" | gcloud secrets versions add BERICHTEN_SMTP_WACHTWOORD --data-file=- >/dev/null
  unset SMTP_WW
  echo "   wachtwoord in het slot gezet."
fi

echo
echo "== Stap 4/6: deploy (mount de secrets op job + service) =="
# De job-/service-config komt uit .github/workflows/deploy.yml — een verse deploy-run
# pakt de zojuist gezette versies op (de eerdere runs faalden dáár bewust zacht op).
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "   deploy-workflow gestart via gh (workflow_dispatch op main)…"
  gh workflow run deploy --ref main --repo pnijenhuis-dotcom/rlz-boekingsmodule
  echo "   wachten tot de run klaar is…"
  sleep 10
  RUN_ID="$(gh run list --workflow=deploy --repo pnijenhuis-dotcom/rlz-boekingsmodule --limit 1 --json databaseId --jq '.[0].databaseId')"
  gh run watch "${RUN_ID}" --repo pnijenhuis-dotcom/rlz-boekingsmodule --exit-status || {
    echo "   FOUT: de deploy-run faalde — bekijk 'm met: gh run view ${RUN_ID} --log-failed"
    echo "   (dit script is idempotent: na een fix gewoon opnieuw draaien)."
    exit 1
  }
  echo "   deploy groen."
else
  echo "   gh (GitHub CLI) niet beschikbaar/ingelogd — trigger de deploy zelf:"
  echo "     • push een commit naar main, of start 'deploy' handmatig op GitHub → Actions."
  read -r -p "   Druk op Enter zodra de deploy-run GROEN is (of Ctrl-C om te stoppen)… " _
fi

echo
echo "== Stap 5/6: één handmatige run van de herinnering-job =="
echo "   (verwacht: 1 herinnering voor het passkeytest-account — push als de PWA"
echo "   push aan heeft staan, anders mail; de open TEST-accordering is geseed.)"
gcloud run jobs execute rlz-accordeur-herinneringen --region="${REGION}" --wait
echo "   job-run klaar (exit 0 = verzonden of aantoonbaar niets te doen — zie de log)."

echo
echo "== Stap 6/6: scheduler hervatten (pas ná jouw groene verificatie) =="
echo "   CONTROLEER NU: kwam er 1 push binnen op de iPhone-PWA, óf 1 mail aan"
echo "   accordeur-passkeytest@ak-nijenhuis.nl (afzender facturen@, Reply-To Peter)?"
read -r -p "   Gezien? Dan hervat ik de dagelijkse 09:00-cadans [j/N]: " ANTWOORD
if [[ "${ANTWOORD}" =~ ^[jJ]$ ]]; then
  gcloud scheduler jobs resume rlz-accordeur-herinneringen --location="${REGION}"
  echo "   scheduler hervat — vanaf morgen dagelijks 09:00 Europe/Amsterdam."
  echo
  echo "KLAAR. Wat je vanaf nu mag verwachten: elke ochtend 09:00 één herinnering per"
  echo "accordeur mét open werk (push waar aangezet, anders mail) — geen open werk ="
  echo "geen bericht. De TEST-accordering kan na de verificatie blijven staan (verdwijnt"
  echo "bij de tranche-2-restore) of via de kantoor-UI worden ingetrokken."
else
  echo "   scheduler blijft GEPAUZEERD (bewust — geen groene verificatie, geen cadans)."
  echo "   Niets gezien? Check: gcloud logging read 'resource.labels.job_name=rlz-accordeur-herinneringen' --limit=20"
  echo "   en draai dit script daarna gewoon opnieuw — het slaat alles over wat al staat."
fi
