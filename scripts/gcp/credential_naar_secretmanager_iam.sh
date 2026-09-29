#!/usr/bin/env bash
# =============================================================================
# Jarvis-logins (opdracht Peter 29-09): IAM op de 18 secrets RLZ_WS_USER_<PREFIX> /
# RLZ_WS_PASSWORD_<PREFIX> in rlz-boekhouding.
#
# WIE DRAAIT DIT: owner-sessie (eenmalig; uitgevoerd 29-09 door CC). IDEMPOTENT
# (add-iam-policy-binding is idempotent; F0-les zoals registersync_secret.sh).
#
# Rollen, least privilege, secret-scoped (nooit op projectniveau):
#   run-jobs@        secretmanager.viewer + secretmanager.secretVersionAdder — de job-executie
#                    `credential-naar-secretmanager` leest de versiestand en voegt een versie toe;
#                    zij kan de waarde NIET terug-lezen (geen accessor).
#   jarvis-run-jobs@ secretmanager.secretAccessor — Jarvis leest de login.
# De containers bestaan al (user-managed, europe-west4) — dit script maakt ze niet aan en
# zet géén versie (dat doet uitsluitend de job-executie, besluit 0012: waarde nooit in een
# terminal). Waarden komen in geen enkele uitvoer voor.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
RUN_JOBS="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
JARVIS="jarvis-run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
PREFIXEN=(UNIVERSAL_NEDERLAND UNIVERSAL_VERKOOP UNIVERSAL_MATERIAAL UNIVERSAL_STEIGERBOUW BWC_STEIGERS
  BRADWOLFF_CONSTRUCTIE INPENSAS_BEHEER BRADWOLFF_HOLDING DE_WIT_BEHEER_OSS)

bind() { # secret, member, rol
  gcloud secrets add-iam-policy-binding "$1" --project="${PROJECT_ID}" \
    --member="serviceAccount:$2" --role="$3" --quiet >/dev/null
}

echo "== IAM Jarvis-logins in ${PROJECT_ID}: 18 secrets =="
for P in "${PREFIXEN[@]}"; do
  for S in "RLZ_WS_USER_${P}" "RLZ_WS_PASSWORD_${P}"; do
    gcloud secrets describe "${S}" --project="${PROJECT_ID}" >/dev/null 2>&1 \
      || { echo "FOUT: ${S} bestaat niet — containers horen al te bestaan (opdracht 29-09)" >&2; exit 2; }
    bind "${S}" "${RUN_JOBS}" roles/secretmanager.viewer
    bind "${S}" "${RUN_JOBS}" roles/secretmanager.secretVersionAdder
    bind "${S}" "${JARVIS}" roles/secretmanager.secretAccessor
    echo "   ${S}: run-jobs@ viewer+versionAdder, jarvis-run-jobs@ accessor"
  done
done
echo "Klaar. Versies zetten = job-executie: gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait \\"
echo "  --args=\"^|^-m|app.cli|credential-naar-secretmanager\"   (ná deploy van de commit die het commando draagt)"
