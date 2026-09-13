#!/usr/bin/env bash
# Run 2 VGG blok 7 — STAP 1: lees-only nametingen productie (opdracht Peter 12-09), ná een groene deploy.
#   scripts/gcp/vgg_blok7_nameting.sh [a|b|c|d|alles]        (default: alles)
# Voorwaarde (voorwaarde-regel blok 7): service én álle jobs draaien hetzelfde image; anders stoppen en melden.
# Uitvoer: verkenning/nameting-vgg-<onderdeel>-<datum>.txt (committen). Alles via scripts/gcp/nameting.sh (allowlist,
# nameting-SA/impersonatie) — niets schrijft.
# Blok 7b 13-09 (punt 9): een niet-groen dry-run-RAPPORT is een UITKOMST (statusregel), geen storing — élk onderdeel
# schrijft zijn rapport altijd weg en het script loopt door naar het volgende (ook ná een rode job-executie); alleen de
# deploy-check (service ≠ jobs) stopt vooraf. SERVICE default = rlz-backend (de échte servicenaam uit deploy.yml).
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HIER/../.." && pwd)"
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
SERVICE="${SERVICE:-rlz-backend}"
ADMIN="${VGG_ADMINISTRATIE:-Vastgoedgroep}"
DATUM="$(date +%d-%m)"
KEUZE="${1:-alles}"

deploy_check() {
  echo ">> deploy-check: service én jobs op hetzelfde image?" >&2
  local svc; svc="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)')"
  echo "   service: $svc" >&2
  local drift=0 j img
  while read -r j; do
    [[ -n "$j" ]] || continue
    img="$(gcloud run jobs describe "$j" --project "$PROJECT" --region "$REGION" \
      --format='value(spec.template.spec.template.spec.containers[0].image)')"
    if [[ "$img" != "$svc" ]]; then echo "   ❌ $j: $img" >&2; drift=1; else echo "   ✓ $j" >&2; fi
  done < <(gcloud run jobs list --project "$PROJECT" --region "$REGION" --format='value(metadata.name)')
  [[ $drift -eq 0 ]] || { echo "STOP: deploy-drift (service ≠ jobs) — eerst de workflow groen, dan opnieuw" >&2; exit 3; }
  echo "$svc"
}

uit() { echo "$REPO/verkenning/nameting-vgg-$1-$DATUM.txt"; }

IMAGE="$(deploy_check)"
{
  echo "# nameting VGG blok 7 — $(date -u +%FT%TZ) — image $IMAGE"
} >&2

# stap <naam> <nameting-args…>: rapport altijd weggeschreven; exit-code van de job = statusregel, nooit een stop.
stap() {
  local naam="$1"; shift
  local bestand; bestand="$(uit "$naam")"
  local rc=0
  "$HIER/nameting.sh" "$@" | tee "$bestand" || rc=$?
  if [[ $rc -eq 0 ]]; then
    echo "STATUS $naam: uitkomst weggeschreven naar $bestand" >&2
  else
    echo "STATUS $naam: job-executie eindigde met code $rc — rapport (voor zover gelogd) staat in $bestand; " \
         "een ROOD rapport is een uitkomst, geen storing — verder met de volgende stap" >&2
  fi
}
run_a() {  # schoonlijst — meetlat: hulzen 44 apart, concepten ~18 waarvan ≥ 11 kopie, dubbelen zonder de 3 bankparen
  stap schoonlijst migratie-schoonlijst --administratie "$ADMIN" \
    --verwacht "systeemhulzen_open_bank=44,concepten=18,concept_kopie_van_geboekt=11,dubbelen=0,open_bankregels=44,dubbele_iban=1"
}
run_b() {  # pandenregister dry-run — meetlat: < 80 clusters, verkopen Heidebeemd 3 / Verschoorstraat 70-2 / 6× Ouwerkerk
  stap panden pandenregister-afleiden --administratie "$ADMIN" --dry-run
}
run_c() {  # replay dry-run — meetlat 13-09: 0 regels ontbrekend, 0 leesfouten, saldibalans mét echte RLZ-kolom, per pand mét verkopen
  stap replay vgg-replay --dry-run --administratie "$ADMIN"
}
run_d() {  # rlz_dubbel lees-only over ALLE administraties — --lees-only zet snede 2 aan; meetlat 13-09: nieuwe tellers (periodiek uitgesloten)
  stap rlz-dubbel-snede2 reconciliatie-alles --alleen rlz_dubbel --lees-only
}

case "$KEUZE" in
  a) run_a ;; b) run_b ;; c) run_c ;; d) run_d ;;
  alles) run_a; run_b; run_c; run_d ;;
  *) echo "gebruik: $0 [a|b|c|d|alles]" >&2; exit 2 ;;
esac
echo ">> klaar — uitvoer in verkenning/nameting-vgg-*-$DATUM.txt (committen)" >&2
