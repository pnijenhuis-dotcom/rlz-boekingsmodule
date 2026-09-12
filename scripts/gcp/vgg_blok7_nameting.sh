#!/usr/bin/env bash
# Run 2 VGG blok 7 — STAP 1: lees-only nametingen productie (opdracht Peter 12-09), ná een groene deploy.
#   scripts/gcp/vgg_blok7_nameting.sh [a|b|c|d|alles]        (default: alles)
# Voorwaarde (voorwaarde-regel blok 7): service én álle jobs draaien hetzelfde image; anders stoppen en melden.
# Uitvoer: verkenning/nameting-vgg-<onderdeel>-<datum>.txt (committen). Alles via scripts/gcp/nameting.sh (allowlist,
# nameting-SA/impersonatie) — niets schrijft.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HIER/../.." && pwd)"
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
SERVICE="${SERVICE:-rlz-boekhouding}"
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

run_a() {  # schoonlijst — meetlat: hulzen 44 apart, concepten ~18 waarvan ≥ 11 kopie, dubbelen zonder de 3 bankparen
  "$HIER/nameting.sh" migratie-schoonlijst --administratie "$ADMIN" \
    --verwacht "systeemhulzen_open_bank=44,concepten=18,concept_kopie_van_geboekt=11,dubbelen=0,open_bankregels=44,dubbele_iban=1" \
    | tee "$(uit schoonlijst)"
}
run_b() {  # pandenregister dry-run — meetlat: < 80 clusters, verkopen Heidebeemd 3 / Verschoorstraat 70-2 / 6× Ouwerkerk
  "$HIER/nameting.sh" pandenregister-afleiden --administratie "$ADMIN" --dry-run | tee "$(uit panden)"
}
run_c() {  # replay dry-run — reconciliatierapport saldibalans RLZ vs berekend, top-10, niet-vertaalbaar, zonder pand, per pand
  "$HIER/nameting.sh" vgg-replay --dry-run --administratie "$ADMIN" | tee "$(uit replay)"
}
run_d() {  # rlz_dubbel lees-only over ALLE administraties — --lees-only zet snede 2 aan (rlz_dubbel.py: snede2=lees_only)
  "$HIER/nameting.sh" reconciliatie-alles --alleen rlz_dubbel --lees-only | tee "$(uit rlz-dubbel-snede2)"
}

case "$KEUZE" in
  a) run_a ;; b) run_b ;; c) run_c ;; d) run_d ;;
  alles) run_a; run_b; run_c; run_d ;;
  *) echo "gebruik: $0 [a|b|c|d|alles]" >&2; exit 2 ;;
esac
echo ">> klaar — uitvoer in verkenning/nameting-vgg-*-$DATUM.txt (committen)" >&2
