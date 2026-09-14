#!/usr/bin/env bash
# Run 2 VGG blok 7 — STAP 1: lees-only nametingen productie (opdracht Peter 12-09), ná een groene deploy.
#   scripts/gcp/vgg_blok7_nameting.sh [a|b|c|d|e|alles]      (default: alles; e = STAP-0 memoriaalregels, blok 7d)
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
# Blok 7d 14-09 — STAP 0 memoriaalregels (punt 1) + JournalEntryLines-waarheid per rekening: lees-only via
# `rlz-lezen --record-via-filter` (geen GUID's nodig — de uitvoer is geanonimiseerd). Eén bestand, alle calls achter
# elkaar; letterlijk overnemen in api-verkenning "Memoriaalregels — teken per regel, STAP-0 14-09".
# Datumfilters = NL-kalenderdag in UTC uitgedrukt (nazorg 14-09): RLZ slaat BookDate op als lokale middernacht (Europe/
# Amsterdam) en toont 'm zonder offset; `ge <dag>T00:00:00Z` schuift daardoor één dag (nameting 14-09: 31-12 gaf alleen
# posten van 01-01, 30-06 en 09-08 gaven 0). Een literal zónder `Z` is een 400 (api-verkenning "Filters/paging":
# DateTimeOffset-format) — daarom hier de bewezen `Z`-vorm, verschoven naar 23:00Z (CET) / 22:00Z (CEST) van de dag ervóór.
run_e() {
  local bestand; bestand="$(uit memoriaalregels)"
  : > "$bestand"
  local nr
  for nr in RLZ-06-00000001 RLZ-06-00000106 RLZ-06-00000038 RLZ-60-00000003 RLZ-06-00000122 RLZ-06-00000123; do
    printf '\n##### %s — document-vorm (DocumentLineList: Account/CreditOrDebit/DebitAmount/CreditAmount/NetAmount)\n' "$nr" | tee -a "$bestand"
    "$HIER/nameting.sh" rlz-lezen --administratie "$ADMIN" --pad ManualJournals \
      --record-via-filter "ReceiptNumber eq '$nr'" --expand 'DocumentLineList($expand=Account)' 2>&1 | tee -a "$bestand" || true
  done
  printf '\n##### JournalEntryLines-waarheid per rekening/datum (RLZ-kolom)\n' | tee -a "$bestand"
  local f
  for f in \
    "Account/AccountNumber eq '0500'" \
    "(Account/AccountNumber eq '1601' or Account/AccountNumber eq '1100') and JournalEntry/BookDate ge 2025-12-30T23:00:00Z and JournalEntry/BookDate lt 2025-12-31T23:00:00Z" \
    "(Account/AccountNumber eq '1710' or Account/AccountNumber eq '8199' or Account/AccountNumber eq '1605' or Account/AccountNumber eq '4000') and JournalEntry/BookDate ge 2025-06-29T22:00:00Z and JournalEntry/BookDate lt 2025-06-30T22:00:00Z" \
    "Account/AccountNumber eq '1602' and JournalEntry/BookDate ge 2025-08-08T22:00:00Z and JournalEntry/BookDate lt 2025-08-09T22:00:00Z" \
    "Account/AccountNumber eq '8000' and JournalEntry/BookDate ge 2025-12-30T23:00:00Z and JournalEntry/BookDate lt 2026-01-01T23:00:00Z" \
    "Account/AccountNumber eq '4900'"; do
    printf '\n##### JournalEntryLines $filter=%s\n' "$f" | tee -a "$bestand"
    "$HIER/nameting.sh" rlz-lezen --administratie "$ADMIN" --pad JournalEntryLines --filter "$f" \
      --expand "Account,JournalEntry" --top 50 --count 2>&1 | tee -a "$bestand" || true
  done
  echo "STATUS memoriaalregels: uitkomst weggeschreven naar $bestand" >&2
}

case "$KEUZE" in
  a) run_a ;; b) run_b ;; c) run_c ;; d) run_d ;; e) run_e ;;
  alles) run_a; run_b; run_c; run_d; run_e ;;
  *) echo "gebruik: $0 [a|b|c|d|e|alles]" >&2; exit 2 ;;
esac
echo ">> klaar — uitvoer in verkenning/nameting-vgg-*-$DATUM.txt (committen)" >&2
