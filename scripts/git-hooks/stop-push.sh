#!/usr/bin/env bash
# Stop-hook-push mét retry (rij (j4) 19-09; BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)").
#   gebruik: scripts/git-hooks/stop-push.sh <repo-dir> [<label>]      (aangeroepen door de Stop-hook in .claude/settings.local.json,
#            één keer voor deze repo ($CLAUDE_PROJECT_DIR) en één keer voor ../Platform — twee onafhankelijke hook-entries)
# Vóór 19-09 deed de hook één `git push origin main`; bij `! [rejected] main -> main (fetch first)` alleen "push handmatig" op stderr
# (exit 1) — onzichtbaar in `claude -p`, en de deploy stond op 19-09 drie uur stil. Sinds 19-09:
#   1. niets te pushen (origin/main..main = 0) → exit 0, stil;
#   2. push → geslaagd → exit 0 (regel in opdrachten/log/push.log als die map er is);
#   3. geweigerd → `git fetch origin main`; is origin vooruit (main..origin/main > 0) én de werkboom schoon wat tracked bestanden
#      betreft, dan ÉÉN `git merge --no-ff --no-edit origin/main` + ÉÉN retry-push. GEEN rebase: de opdracht van 19-09 noemt
#      "pull --rebase", maar de regel van 19-09 ochtend (werkloop-productie "Stop-hook-push non-fast-forward") zegt nooit rebase —
#      de lokale hashes staan in het zojuist geschreven rapport/BESLISSINGEN en zouden verdwijnen; een merge houdt ze. Nooit force.
#   4. blijft het falen (merge-conflict → `git merge --abort`; werkboom vuil; netwerk) → LUIDE blokkade: stderr mét de exacte
#      commando's, macOS-melding (osascript), regel in opdrachten/log/push.log én opdrachten/.push-geblokkeerd (tijd / oorzaak /
#      herstelcommando) zodat `rlz inbox status` "PUSH GEBLOKKEERD" toont; exit 1. Een geslaagde push ruimt dat bestand op.
# Guard: backend/tests/unit/test_stop_hook_push.py (bare origin + divergerende commit: merge+retry; conflict: blokkade; geen
# rebase-/force-woord in dit script).
set -uo pipefail
REPO="${1:?gebruik: stop-push.sh <repo-dir> [label]}"
LABEL="${2:-$(basename "$REPO")}"
LOGMAP="$REPO/opdrachten/log"; BLOKKADE="$REPO/opdrachten/.push-geblokkeerd"
NU() { date +%FT%T; }
log() { echo "$1" >&2; [[ -d "$LOGMAP" ]] && echo "$(NU) $1" >> "$LOGMAP/push.log"; return 0; }
melding() {
  local titel="${1//\"/\'}" tekst="${2//\"/\'}"
  osascript -e "display notification \"${tekst:0:200}\" with title \"${titel:0:60}\"" >/dev/null 2>&1 || true
}
blokkade() {  # blokkade <oorzaak> <herstel>
  log "PUSH GEBLOKKEERD ($LABEL): $1 — herstel: $2"
  echo "Auto-push $LABEL naar origin/main mislukt en niet automatisch te herstellen: $1" >&2
  echo "Doe zelf (nooit force, nooit rebase): cd \"$REPO\" && $2" >&2
  [[ -d "$REPO/opdrachten" ]] && printf '%s\n%s\n%s\n' "$(NU) $LABEL" "$1" "$2" > "$BLOKKADE"
  melding "PUSH GEBLOKKEERD: $LABEL" "$1 — rlz inbox status toont het herstel"
  exit 1
}

ahead="$(git -C "$REPO" rev-list --count origin/main..main 2>/dev/null || echo 0)"
[[ "$ahead" -gt 0 ]] || exit 0

if uit="$(git -C "$REPO" push origin main 2>&1)"; then
  rm -f "$BLOKKADE"; log "push $LABEL ok ($ahead commit(s))"; exit 0
fi
log "push $LABEL geweigerd: $(printf '%s' "$uit" | grep -m1 -E 'rejected|error|fatal' | cut -c1-160)"
if ! git -C "$REPO" fetch -q origin main 2>/dev/null; then
  blokkade "push geweigerd en fetch mislukt (netwerk/rechten?)" "git fetch origin && git merge --no-ff origin/main && git push origin main"
fi
remote="$(git -C "$REPO" rev-list --count main..origin/main 2>/dev/null || echo 0)"
lokaal="$(git -C "$REPO" rev-list --count origin/main..main 2>/dev/null || echo 0)"
if [[ "$remote" -eq 0 ]]; then
  blokkade "push geweigerd zonder divergentie ($lokaal lokaal / 0 remote — rechten of netwerk): $(printf '%s' "$uit" | tail -1 | cut -c1-120)" "git push origin main"
fi
if [[ -n "$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
  blokkade "origin gedivergeerd ($lokaal lokaal / $remote remote) en de werkboom heeft ongecommitte tracked wijzigingen — merge niet veilig" "git status && git commit -am '…' && git merge --no-ff origin/main && git push origin main"
fi
binnenkomend="$(git -C "$REPO" log --format='%h %an: %s' main..origin/main 2>/dev/null | cut -c1-100 | head -5 | tr '\n' ';')"
if ! git -C "$REPO" merge --no-ff --no-edit origin/main -m "merge(origin/main — automatisch door de Stop-hook ná een non-fast-forward-push, $(NU); $remote remote commit(s): ${binnenkomend%;}; $lokaal lokale commit(s) blijven op hun hash — nooit rebase)" >/dev/null 2>&1; then
  git -C "$REPO" merge --abort >/dev/null 2>&1 || true
  blokkade "origin gedivergeerd ($lokaal lokaal / $remote remote) en de merge geeft conflicten — afgebroken, werkboom als vóór" "git merge --no-ff origin/main   # los de conflicten op, commit, dan: git push origin main"
fi
log "merge origin/main ($remote remote commit(s): ${binnenkomend%;}) — retry push"
if uit="$(git -C "$REPO" push origin main 2>&1)"; then
  rm -f "$BLOKKADE"; log "push $LABEL ok ná merge ($lokaal + $remote commit(s))"
  echo "Stop-hook $LABEL: origin was gedivergeerd ($lokaal lokaal / $remote remote) → merge --no-ff + push geslaagd" >&2
  exit 0
fi
blokkade "retry-push ná merge opnieuw geweigerd: $(printf '%s' "$uit" | grep -m1 -E 'rejected|error|fatal' | cut -c1-120)" "git fetch origin && git merge --no-ff origin/main && git push origin main"
