#!/usr/bin/env bash
# Eenmalige, geauditeerde IC-rij Universal Nederland B.V. → administratie Universal Steigerbouw B.V. (nachtrun 08/09-09
# blok 2; BESLISSINGEN "INTERCOMPANY-LEVERANCIERS INSTELBAAR + EENMALIGE RIJ UNIVERSAL"). Productie-regel Peter 08-09:
# alleen via de bestaande Cloud Run-job-image (zelfde CLI-entrypoint als de andere backfills) — dus ná de deploy van de
# commit die `intercompany-leverancier-markeren` draagt. Eerst dry-run, dan echt. Geen lokale backend, geen proxy.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
JOB="${JOB:-rlz-reconciliatie}"
ACTOR="${ACTOR:-p.nijenhuis@kempengroep.nl}"
ADMINISTRATIE="${ADMINISTRATIE:-Universal Steigerbouw B.V.}"
CREDITEUR="${CREDITEUR:-Universal Nederland B.V.}"
REDEN="${REDEN:-besluit 08-09 intercompany Universal}"
MODUS="${1:-dry-run}"   # dry-run | echt

ARGS="-m,app.cli,intercompany-leverancier-markeren,--administratie,${ADMINISTRATIE},--crediteur,${CREDITEUR},--actor-email,${ACTOR},--reden,${REDEN}"
if [[ "$MODUS" == "dry-run" ]]; then ARGS="${ARGS},--dry-run"; elif [[ "$MODUS" != "echt" ]]; then echo "gebruik: $0 [dry-run|echt]" >&2; exit 2; fi

echo ">> gcloud run jobs execute ${JOB} (${MODUS}) — commando's met komma in een argumentwaarde: gcloud's ^|^-scheidingsteken"
gcloud run jobs execute "$JOB" --project "$PROJECT" --region "$REGION" --wait \
  --args="^|^$(echo "$ARGS" | tr ',' '|')"
echo ">> Meetrecept: (a) Instellingen › Administraties › ${ADMINISTRATIE} › Klant-accordering toont de rij mét chip 'handmatig' +"
echo "   historie; (b) een open ${CREDITEUR}-document toont hint 'intercompany' en knop 'Boeken in RLZ ✓' (geen 'Ter accordering');"
echo "   ná boeken: tijdlijnregel 'Intercompany — klant-accordering overgeslagen (leveranciersregel)', 0 rondes."
