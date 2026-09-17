#!/usr/bin/env bash
# Lees-only productie-nameting op de gedeployde job-image (regel Peter 08-09; §F7 route A, blok 1 nametingen-run 10-09).
#   scripts/gcp/nameting.sh <cli-commando> [args…]
# Voorbeelden:
#   scripts/gcp/nameting.sh reconciliatie-alles --alleen rlz_dubbel --lees-only
#   scripts/gcp/nameting.sh autoboek-leren-rapport --administratie <uuid>
#   scripts/gcp/nameting.sh reconciliatie-alles --alleen intercompany --lees-only        # Peter 16-09: IC-factuurmatch (meetlat)
#   scripts/gcp/nameting.sh reconciliatie-alles --alleen rekening_courant --lees-only   # Peter 16-09: RC-aansluiting (meetlat)
#   scripts/gcp/nameting.sh activa-nulmeting [--administratie <naamdeel>]                 # 16-09: STAP-0 activa, lees-only
#   scripts/gcp/nameting.sh groep-saldi --groep "Kempen groep"                                    # 16-09: groepssaldi deb/cred (lees-only, live)
#   scripts/gcp/nameting.sh rlz-lezen --administratie "Kempen Facilities" --pad AssetTypes --root   # 16-09: RLZ-brede enumeraties
#   scripts/gcp/nameting.sh btw-default-rapport --administratie "L.H.G. Holding"   # lees-only, 14-09 (0143)
#   scripts/gcp/nameting.sh bank-voorstellen-lezen --administratie "Administratiekantoor Nijenhuis" --met-ai-toets
#   scripts/gcp/nameting.sh rlz-lezen --administratie "Administratiekantoor Nijenhuis C.V." --pad PaymentTransactions --filter "PaymentBatchId ne null" --expand "Batch,PaymentReferenceList(\$expand=Document)" --top 5
# Alleen commando's uit de allowlist hieronder (lees-only); schrijvende nazorg blijft een expliciete opdracht van Peter
# via de bestaande scripts. Argumenten mét komma's zijn veilig: gcloud's ^|^-scheidingsteken.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HIER/nameting_env.sh"
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
JOB="${JOB:-rlz-reconciliatie}"
# rlz-lezen (blok 10 11-09): één OData-GET op de RLZ-API van één administratie — het commando weigert zelf élke
# niet-GET en elk Actions-/Download-pad (app/rlz/lezen_cli.py), --top ≤ 50, uitvoer altijd geanonimiseerd.
ALLOWLIST="reconciliatie-alles autoboek-leren-rapport btw-default-rapport administratie-naam-bron-backfill bank-voorstellen-lezen bank-historie-backfill boeken-status reconciliatie-acceptaties migratie-schoonlijst pandenregister-afleiden staande-goedkeuring-voorstellen-lezen rlz-lezen werkvoorraad-tellers-herrekenen vgg-rekeningen vgg-replay duplicaat-extern-rapport referentie-norm-backfill activa-nulmeting groep-saldi kassarapporten-in-inkoopstroom omzet-binder-rapport omzet-stores-migreren doorbelasting-aansluiting app-bundels bevindingssoort-stand"  # run 2 VGG blok 6: vgg-replay = dry-run, lees-only; 16-09: duplicaat-extern-rapport lees-only, referentie-norm-backfill alleen --dry-run
CMD="${1:-}"; [[ -n "$CMD" ]] || { echo "gebruik: $0 <cli-commando> [args…]" >&2; exit 2; }
# run 2 VGG blok 5: de Odoo-migratie-commando's SCHRIJVEN (DB-koppeling resp. concepten op company 6) — nooit een nameting.
for schrijvend in odoo-koppeling-migratiedoel vgg-odoo-stap0; do
  [[ "$CMD" == "$schrijvend" ]] && { echo "FOUT: $CMD is een schrijvend commando — expliciete opdracht Peter via gcloud run jobs execute, niet via nameting.sh" >&2; exit 2; }
done
grep -qw -- "$CMD" <<<"$ALLOWLIST" || { echo "FOUT: '$CMD' staat niet in de lees-only allowlist ($ALLOWLIST)" >&2; exit 2; }
if [[ "$CMD" == "reconciliatie-alles" ]]; then
  printf '%s\n' "$@" | grep -qx -- "--lees-only" || { echo "FOUT: reconciliatie-alles alleen mét --lees-only via dit script (de echte run is de scheduler/'Nu draaien')" >&2; exit 2; }
fi
if [[ "$CMD" == "bank-historie-backfill" ]]; then
  # Ochtendrun 11-09: de backfill schrijft in de eigen cache — als nameting alleen de telling (--dry-run).
  printf '%s\n' "$@" | grep -qx -- "--dry-run" || { echo "FOUT: bank-historie-backfill alleen mét --dry-run via dit script (de echte vulling is een expliciete opdracht van Peter)" >&2; exit 2; }
fi
if [[ "$CMD" == "referentie-norm-backfill" ]]; then
  # 16-09 (0147): de backfill schrijft de afgeleide kolom — als nameting alleen de telling (--dry-run).
  printf '%s\n' "$@" | grep -qx -- "--dry-run" || { echo "FOUT: referentie-norm-backfill alleen mét --dry-run via dit script (de echte vulling is de data-stap via gcloud run jobs execute)" >&2; exit 2; }
fi
if [[ "$CMD" == "omzet-stores-migreren" ]] && printf '%s\n' "$@" | grep -qx -- "--schrijf"; then
  # 0151 (16-09 avond): de data-stap schrijft de routeringstabel — als nameting alleen de dry-run-lijst.
  echo "FOUT: omzet-stores-migreren --schrijf is de data-stap (gcloud run jobs execute), geen nameting" >&2; exit 2
fi
if [[ "$CMD" == "werkvoorraad-tellers-herrekenen" ]]; then
  # Blok 6 11-09: de herberekening schrijft de tellers-cache — als nameting alleen de vergelijking (--dry-run).
  printf '%s\n' "$@" | grep -qx -- "--dry-run" || { echo "FOUT: werkvoorraad-tellers-herrekenen alleen mét --dry-run via dit script (de echte herberekening loopt in sync-alles)" >&2; exit 2; }
fi
if [[ "$CMD" == "pandenregister-afleiden" || "$CMD" == "administratie-naam-bron-backfill" ]] && printf '%s\n' "$@" | grep -qx -- "--schrijf"; then
  # administratie-naam-bron-backfill (15-09, 0144): dry-run = nameting; --schrijf = de data-stap, expliciet via gcloud run jobs execute.
  echo "FOUT: --schrijf is geen nameting" >&2; exit 2
fi
if [[ "$CMD" == "bevindingssoort-stand" ]] && printf '%s\n' "$@" | grep -qx -- "--stand"; then
  # SPOED 17-09 blok C: zonder --stand = lees-only overzicht (nameting); --stand = promotie/degradatie = expliciete stap Peter.
  echo "FOUT: bevindingssoort-stand --stand is een promotie/degradatie (schrijft de instelling) — expliciete opdracht via gcloud run jobs execute, geen nameting" >&2; exit 2
fi
if [[ "$CMD" == "vgg-rekeningen" ]] && printf '%s\n' "$@" | grep -qx -- "--maak-aan"; then
  # run 2 VGG blok 4: de rol-aanmaak is een Odoo-write (kill-switch + akkoord Peter) — geen nameting.
  echo "FOUT: --maak-aan is geen nameting (Odoo-write; alleen ná akkoord Peter via de expliciete job-opdracht)" >&2; exit 2
fi
if [[ "$CMD" == "vgg-replay" ]] && printf '%s\n' "$@" | grep -qx -- "--schrijf-concept"; then
  # run 2 VGG blok 6: --schrijf-concept is run 3 (Odoo-writes) — nooit via het nameting-instrument.
  echo "FOUT: vgg-replay --schrijf-concept is run 3 en geen nameting — alleen --dry-run via dit script" >&2; exit 2
fi
# SPOED 17-09 punt 4 (Workspace-reauth-beleid raakt de launchd-/cc-inbox-sessie: "Reauthentication failed … non-interactive"):
# een NIET-INTERACTIEVE run (geen TTY, of de gcloud-gebruikerssessie kan geen token meer geven) draait de meting niet lokaal maar
# via de nameting-workflow (`gh workflow run nameting -f onderdeel=<…>`, WIF als nameting@) — de bot commit het bestand naar main.
#   NAMETING_VIA_GH=auto (default) : GITHUB_ACTIONS → lokaal (runner IS het SA); anders gh zodra er geen TTY is óf het token faalt.
#   NAMETING_VIA_GH=1              : altijd via gh.       NAMETING_VIA_GH=0 : altijd lokaal (interactieve sessie mét geldig token).
# Alleen commando's met een workflow-onderdeel kunnen via gh; een ad-hoc lees-commando (rlz-lezen, groep-saldi, …) zonder onderdeel
# = exit 3 mét de reden — nooit stil terugvallen op een gcloud-sessie die niet werkt.
via_gh_onderdeel() {
  case "$1" in
    doorbelasting-aansluiting) echo doorbelasting-aansluiting ;;
    app-bundels) echo app-bundels ;;
    reconciliatie-alles) echo reconciliatie ;;
    btw-default-rapport) echo btw-default ;;
    migratie-schoonlijst) echo a ;;
    pandenregister-afleiden) echo b ;;
    vgg-replay) echo c ;;
    *) echo "" ;;
  esac
}
VIA_GH="${NAMETING_VIA_GH:-auto}"
if [[ "$VIA_GH" == "auto" ]]; then
  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then VIA_GH=0
  elif [[ ! -t 0 && ! -t 1 ]]; then VIA_GH=1; echo ">> nameting: geen TTY (niet-interactieve run) → via gh workflow run" >&2
  elif ! gcloud auth print-access-token "${NAMETING_GCLOUD_FLAGS[@]}" >/dev/null 2>&1; then VIA_GH=1; echo ">> nameting: gcloud-sessie geeft geen token (reauth nodig) → via gh workflow run" >&2
  else VIA_GH=0; fi
fi
if [[ "$VIA_GH" == "1" ]]; then
  ONDERDEEL="$(via_gh_onderdeel "$CMD")"
  [[ -n "$ONDERDEEL" ]] || { echo "FOUT: '$CMD' heeft geen onderdeel in .github/workflows/nameting.yml — voeg het als dispatch-onderdeel toe (blok-bouw) of draai interactief mét NAMETING_VIA_GH=0 en een geldige gcloud-sessie" >&2; exit 3; }
  command -v gh >/dev/null || { echo "FOUT: gh ontbreekt" >&2; exit 3; }
  gh auth status >/dev/null 2>&1 || { echo "FOUT: gh niet ingelogd (gh auth login)" >&2; exit 3; }
  echo ">> gh workflow run nameting -f onderdeel=$ONDERDEEL  (argumenten '$*' worden NIET doorgegeven: het onderdeel draagt zijn eigen vaste recept)" >&2
  gh workflow run nameting -f "onderdeel=$ONDERDEEL" >&2
  sleep 8
  RUN_ID="$(gh run list --workflow=nameting --limit 1 --json databaseId --jq '.[0].databaseId')"
  [[ -n "$RUN_ID" ]] || { echo "FOUT: geen workflow-run gevonden" >&2; exit 3; }
  echo ">> run $RUN_ID — wachten (gh run watch)" >&2
  gh run watch "$RUN_ID" --exit-status >&2 || { echo "STATUS: workflow-run $RUN_ID niet groen (rood rapport = uitkomst; auth-/deploy-drift = fout) — gh run view $RUN_ID --log" >&2; exit 4; }
  echo ">> klaar — de nameting-bot committe verkenning/nameting-*.txt naar main: git pull --ff-only origin main en lees het bestand van vandaag" >&2
  exit 0
fi
ARGS="-m|app.cli"; for a in "$@"; do ARGS="$ARGS|$a"; done
echo ">> gcloud run jobs execute $JOB ($CMD) onder ${NAMETING_SA:-gebruikerssessie}" >&2
# Blok 7b 13-09 (punt 9): een niet-groene job-executie (het CLI gaf exit ≠ 0) is bij een dry-run/lees-only een UITKOMST —
# de logs worden ALTIJD gelezen en getoond; de exit-code van dit script volgt de executie, behalve voor vgg-replay
# (dry-run-rapport = uitkomst, exit 0 mét statusregel).
set +o pipefail
UITVOER="$(gcloud run jobs execute "$JOB" --project "$PROJECT" --region "$REGION" --wait --format="value(metadata.name)" \
  "${NAMETING_GCLOUD_FLAGS[@]}" --args="^|^$ARGS" 2>&1 | tee /dev/stderr | tail -1)"
RC="${PIPESTATUS[0]:-0}"
set -o pipefail
EXEC="$(grep -o 'rlz-[a-z-]*-[a-z0-9]\{5\}' <<<"$UITVOER" | tail -1)"
[[ -n "$EXEC" ]] || { echo "FOUT: geen executie-naam gevonden in de gcloud-uitvoer" >&2; exit 1; }
echo ">> uitvoer van $EXEC (Cloud Logging, chronologisch):" >&2
sleep 5
gcloud logging read "resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\"" \
  --project "$PROJECT" --limit 5000 --order=asc --format="value(textPayload)" "${NAMETING_GCLOUD_FLAGS[@]}"
if [[ "$RC" -ne 0 ]]; then
  if [[ "$CMD" == "vgg-replay" ]]; then
    echo "STATUS: vgg-replay-executie eindigde met code $RC — het rapport is de uitkomst (zie hierboven), geen storing" >&2
    exit 0
  fi
  echo "STATUS: job-executie eindigde met code $RC (uitvoer hierboven)" >&2
  exit "$RC"
fi
