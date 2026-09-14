#!/usr/bin/env bash
# Werkloop automatisch 14-09 (besluit Peter 14-09) — WIF-binding voor de nameting-workflow (.github/workflows/nameting.yml).
# Eenmalig door Peter als OWNER draaien (deploy@ en nameting@ hebben geen IAM-rechten; Claude Code zet geen IAM).
#
#   scripts/gcp/nameting_wif_iam.sh            → --dry-run (default): alleen lezen en rapporteren, schrijft NIETS
#   scripts/gcp/nameting_wif_iam.sh --apply    → zet (a) en — alleen als de conditie ontbreekt — (b)
#
# (a) roles/iam.workloadIdentityUser op nameting@ voor de principalSet van de GitHub-pool met attribute.repository ==
#     deze repo (zelfde vorm als f0_fundament.sh stap 5.3 voor deploy@). Daarmee kan de workflow via
#     google-github-actions/auth@v2 als nameting@ werken; het beslispunt "SA-key" van 10-09 (org-policy blokkeert
#     keys) vervalt — géén key nodig.
# (b) Controle dat de OIDC-provider `github-oidc` een attribute-condition op de repository/organisatie draagt. Die
#     provider is GEDEELD met deploy@ (deploy.yml gebruikt dezelfde) — ontbreekt de conditie, dan kan élke GitHub-repo
#     tokens ruilen bij de pool; dat raakt dus óók deploy@ en wordt hier expliciet gemeld. Met --apply wordt de
#     conditie gezet als hij ontbreekt (nooit gewijzigd als er al één staat: dat is een bewust besluit van Peter).
# (c) Toont de huidige rollen van nameting@ (projectbreed + job-scoped) en vergelijkt met wat de scripts nodig hebben
#     (run.viewer, logging.viewer, nametingUitvoerder job-scoped op rlz-reconciliatie). Voegt NIETS toe buiten (a).
# Idempotent: staat (a) al, dan geen mutatie; exit 0. Exit 1 = ontbrekende items in dry-run (zichtbaar, geen fout van
# het script), exit 2 = gebruiksfout.
set -euo pipefail
MODUS="${1:---dry-run}"
case "$MODUS" in --dry-run|--apply) ;; *) echo "gebruik: $0 [--dry-run|--apply]" >&2; exit 2 ;; esac
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
JOB="${JOB:-rlz-reconciliatie}"
POOL="${POOL:-github}"
PROVIDER="${PROVIDER:-github-oidc}"
GITHUB_REPO="${GITHUB_REPO:-pnijenhuis-dotcom/rlz-boekingsmodule}"
SA="nameting@${PROJECT}.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
PRINCIPALSET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}"
ROL_WIF="roles/iam.workloadIdentityUser"
ONTBREEKT=0

echo "# nameting_wif_iam.sh $MODUS — project $PROJECT ($PROJECT_NUMBER), repo $GITHUB_REPO, SA $SA"
echo

# ---- (a) workloadIdentityUser op nameting@ voor de repo-principalSet ---------------------------------------------
heeft_wif_binding() {
  gcloud iam service-accounts get-iam-policy "$SA" --project "$PROJECT" \
    --flatten="bindings[].members" --filter="bindings.role:${ROL_WIF} AND bindings.members:${PRINCIPALSET}" \
    --format="value(bindings.members)" | grep -Fxq -- "$PRINCIPALSET"
}
echo "(a) ${ROL_WIF} op ${SA} voor ${PRINCIPALSET}"
if heeft_wif_binding; then
  echo "    ✓ staat al (geen wijziging)"
elif [[ "$MODUS" == "--apply" ]]; then
  gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
    --member="$PRINCIPALSET" --role="$ROL_WIF" --format=none
  heeft_wif_binding && echo "    ✓ gezet" || { echo "    FOUT: binding niet terug te lezen ná add-iam-policy-binding" >&2; exit 1; }
else
  echo "    ✗ ONTBREEKT — --apply zet 'm (gcloud iam service-accounts add-iam-policy-binding $SA --member=\"$PRINCIPALSET\" --role=$ROL_WIF)"
  ONTBREEKT=1
fi
echo

# ---- (b) attribute-condition op de gedeelde provider --------------------------------------------------------------
echo "(b) attribute-condition op provider ${POOL}/${PROVIDER} (GEDEELD met deploy@ — deploy.yml gebruikt dezelfde provider)"
STATE_EN_CONDITIE="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" --project "$PROJECT" \
  --location=global --workload-identity-pool="$POOL" --format='value(state,attributeCondition)')"
STATE="${STATE_EN_CONDITIE%%$'\t'*}"; CONDITIE="${STATE_EN_CONDITIE#*$'\t'}"
[[ "$CONDITIE" == "$STATE_EN_CONDITIE" ]] && CONDITIE=""
echo "    state: ${STATE:-?}"
echo "    conditie: ${CONDITIE:-(GEEN)}"
GEWENST="assertion.repository == '${GITHUB_REPO}'"
if [[ -n "$CONDITIE" ]] && grep -Eq "assertion\.repository(_owner)? *==" <<<"$CONDITIE"; then
  echo "    ✓ conditie beperkt tot repository/organisatie"
  grep -Fq -- "$GITHUB_REPO" <<<"$CONDITIE" || echo "    let op: de conditie noemt niet letterlijk ${GITHUB_REPO} — controleer dat deze repo erdoor mag (anders faalt de workflow op STS)"
elif [[ "$MODUS" == "--apply" && -z "$CONDITIE" ]]; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --project "$PROJECT" \
    --location=global --workload-identity-pool="$POOL" --attribute-condition="$GEWENST" --format=none
  echo "    ✓ conditie GEZET: ${GEWENST} — geldt óók voor deploy@ (dezelfde provider); deploy.yml blijft werken (zelfde repo)"
else
  echo "    ✗ ONTBREEKT of beperkt niet op repository — geldt óók voor deploy@ (dezelfde provider)!"
  echo "      --apply zet: gcloud iam workload-identity-pools providers update-oidc $PROVIDER --location=global --workload-identity-pool=$POOL --attribute-condition=\"$GEWENST\""
  ONTBREEKT=1
fi
echo

# ---- (c) huidige rollen van nameting@ — alleen tonen en vergelijken, niets toevoegen --------------------------------
echo "(c) rollen van ${SA} (verwacht: roles/run.viewer + roles/logging.viewer projectbreed; projects/${PROJECT}/roles/nametingUitvoerder job-scoped op ${JOB}; geen cloudsql/secretmanager/IAM)"
PROJECT_ROLLEN="$(gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SA}" --format="value(bindings.role)" | sort -u)"
echo "    projectbreed:"; sed 's/^/      - /' <<<"${PROJECT_ROLLEN:-(geen)}"
JOB_ROLLEN="$(gcloud run jobs get-iam-policy "$JOB" --project "$PROJECT" --region "$REGION" --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SA}" --format="value(bindings.role)" | sort -u)"
echo "    job ${JOB}:"; sed 's/^/      - /' <<<"${JOB_ROLLEN:-(geen)}"
for verwacht in roles/run.viewer roles/logging.viewer; do
  grep -Fxq -- "$verwacht" <<<"$PROJECT_ROLLEN" || { echo "    ✗ ${verwacht} ontbreekt projectbreed (wordt hier NIET gezet — zie GCP_UITROL §F7.3 A3/A4)"; ONTBREEKT=1; }
done
grep -Fxq -- "projects/${PROJECT}/roles/nametingUitvoerder" <<<"$JOB_ROLLEN" || { echo "    ✗ nametingUitvoerder ontbreekt op ${JOB} (wordt hier NIET gezet — zie §F7.3 A5)"; ONTBREEKT=1; }
EXTRA="$(grep -Ev '^roles/(run\.viewer|logging\.viewer)$' <<<"$PROJECT_ROLLEN" || true)"
[[ -z "$EXTRA" ]] || { echo "    let op: extra projectbrede rollen op nameting@ (buiten de scripts): "; sed 's/^/      - /' <<<"$EXTRA"; }
echo
if [[ $ONTBREEKT -eq 0 ]]; then
  echo "KLAAR: alles staat — de nameting-workflow kan draaien (GitHub → Actions → nameting → Run workflow)."
else
  [[ "$MODUS" == "--dry-run" ]] && echo "DRY-RUN: ontbrekende items hierboven (✗). Zetten: $0 --apply" || echo "LET OP: niet alles staat (✗ hierboven) — (c)-items zet dit script bewust niet."
  exit 1
fi
