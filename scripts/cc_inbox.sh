#!/usr/bin/env bash
# Werkloop automatisch 14-09 (besluit Peter 14-09: Cowork schrijft opdrachten, launchd start Claude Code, Peter test en meldt).
#   scripts/cc_inbox.sh            → neemt het OUDSTE .md-bestand uit opdrachten/inbox/, verplaatst het naar opdrachten/lopend/,
#                                    start `claude -p` met de inhoud als prompt vanuit de repo-root, logt naar
#                                    opdrachten/log/<datum>-<slug>.log en stuurt een macOS-melding "CC klaar: <slug> — <laatste regel>".
# Eén tegelijk: lock opdrachten/.lock (mét pid). Staat er een lock van een levend proces → niets doen (exit 0). Een lock
# van een dood proces (crash/reboot) wordt gemeld en opgeruimd — anders zou de inbox voor altijd stilstaan.
# Permissies: --permission-mode ${CC_INBOX_PERMISSION_MODE:-auto} + de bestaande .claude/settings.local.json van de
# repo (deny-lijst geldt: geen git push door de agent, geen secrets; de Stop-hook pusht ná de run zoals altijd).
# Default `auto` sinds 14-09 middag (Cowork, vóór de eerste echte inbox-opdracht): de classifier keurt veilige acties goed
# zodat CC zelf kan committen/verplaatsen/testen; `acceptEdits` liet elke Bash-aanroep buiten de allow-lijst onbeantwoord
# → geweigerd (geen mens om te antwoorden). Zet CC_INBOX_PERMISSION_MODE=acceptEdits om terug te vallen. Vastgelegd in
# CLAUDE.md § Werkwijze "Werkloop automatisch (14-09)" + BESLISSINGEN "WERKLOOP AUTOMATISCH …" aandachtspunt (0).
# Afronding: exit 0 van claude én het bestand staat nog in lopend/ → het script verplaatst het naar gedaan/ mét kopregel
# "uitgevoerd <datum>, rapport: docs/rapporten/<bestand>" (nieuwste rapport dat tijdens de run is bijgekomen, anders "geen").
# Exit ≠ 0 → bestand blijft in lopend/ (zichtbaar), melding "CC MISLUKT".
#
# ELKE STOP = LOGREGEL + MELDING (herstel 14-09 avond, incident 15:17: de veldwerkers-run stierf ná 22 min op
# "You've hit your monthly spend limit" — claude -p exit 1; het opdrachtenlog droeg 22 minuten alleen de startregel en de
# opdracht bleef in lopend/ staan zonder herstart). Sinds dit herstel:
#   (a) hartslag: zolang claude loopt schrijft het script elke CC_INBOX_HARTSLAG_S seconden (default 300) een regel
#       ">> cc_inbox: loopt nog (N min)" in het opdrachtenlog — een log met alleen een startregel is dus nooit meer normaal;
#   (b) signaal-/onverwacht einde: TERM/INT/HUP (launchd-stop, kill, logout) en élk ander einde zonder afronding geven een
#       logregel ">> cc_inbox: GESTOPT …" + melding "CC GESTOPT"; het claude-kind wordt mee beëindigd;
#   (c) limiet-herkenning: bevat de claude-uitvoer "spend limit"/"usage limit"/"rate limit"/"credits", dan zegt log en
#       melding letterlijk "LIMIET — claude.ai/admin-settings/usage" in plaats van een kale exitcode;
#   (d) melding-resultaat in het log ("melding verstuurd" / "melding mislukt (osascript rc=N)") — een stille melding is
#       anders onzichtbaar; buiten launchd/GUI mislukt osascript soms, het log blijft de waarheid;
#   (e) verweesde lopend-opdracht: staat er bij een tick ZONDER levende lock een .md in lopend/, dan is die run gestopt
#       zonder afronding → terug naar inbox/ (poging N/CC_INBOX_MAX_POGINGEN, default 3; teller in
#       opdrachten/log/<slug>.pogingen) mét logregel + melding "CC HERSTART", en direct opnieuw opgepakt door dezelfde
#       tick. Ná de laatste poging → opdrachten/mislukt/ mét kopregel "MISLUKT ná N pogingen — <laatste logregel>" +
#       melding "CC MISLUKT DEFINITIEF" — nooit stil, nooit oneindig herstarten (een budgetlimiet zou anders elke 5 min
#       een nieuwe poging starten). Peter zet 'm terug in inbox/ als de oorzaak weg is (de teller wordt dan gewist).
#       Een run die met code ≠ 0 eindigt laat het bestand bewust in lopend/ — de volgende tick past (e) toe.
# Lokale pull (werkloop-nazorg 14-09): vóór het oppakken van een opdracht én bij elke launchd-tick zonder werk doet het
# script `git pull --ff-only origin main` in de repo-root — zodat bot-commits (nameting-workflow) op de Mac landen — maar
# ALLEEN als er geen levende lock is (die stopt het script al eerder) én de werkboom SCHOON is wat betreft
# TRACKED bestanden — `git status --porcelain --untracked-files=no` leeg; een nieuwe opdracht in inbox/ is untracked en
# mag de pull niet tegenhouden, git weigert een ff-pull die een untracked bestand zou overschrijven toch zelf). Anders,
# of als de branch gedivergeerd is (ff-only faalt), wordt de pull OVERGESLAGEN mét logregel — nooit rebase, merge of
# stash; een gedivergeerde stand is voor Peter (of de CC-run zelf) om te beoordelen. Een tick zonder werk logt alleen
# als er iets binnenkwam of overgeslagen is (geen "Already up to date" om de vijf minuten). CC_INBOX_GEEN_PULL=1 slaat
# de pull over (handmatige start/test).
# Handmatige CC actief = wachten (nazorg 15-09, Cowork; incident 15-09 ochtend: een handmatige CC-sessie (administratienaam)
# en de launchd-inbox-run liepen parallel in dezelfde werkboom → pytest-setup-errors op de gedeelde test-DB en het risico op
# vervlochten commits / een Stop-hook die de commits van de ander pusht). Sinds deze nazorg: vóór het herstel van verweesde
# opdrachten, vóór de pull en vóór het oppakken van een opdracht kijkt het script of er al een `claude`-proces draait met
# zijn cwd IN deze repo (repo-root of een submap; `pgrep -x claude` + cwd via `lsof -a -p <pid> -d cwd -Fn`, op macOS
# altijd aanwezig als /usr/sbin/lsof — geen /proc). Zo ja: NIETS doen (geen herstel, geen pull, geen start), logregel
# ">> cc_inbox: wacht — handmatige CC actief (pid N, cwd …)", exit 0; de volgende tick (≤ 5 min) kijkt opnieuw. Een claude
# in een ándere map (ander project) telt niet. Is de cwd van een claude-proces niet te lezen (lsof ontbreekt of faalt), dan
# telt dat proces WÉL als actief (fail-closed: liever een tick wachten dan twee runs door elkaar) — mét de reden in de
# logregel. Seam voor de guard-test: CC_INBOX_CLAUDE_NAAM (procesnaam, default `claude`); de test start een symlink naar
# /bin/sleep onder de naam `claude` mét cwd in de wegwerp-repo — geen echte claude.
# Geen TTY nodig (launchd). PATH wordt door de plist gezet; hier als vangnet ACHTERAAN aangevuld voor een handmatige start
# (achteraan: een expliciet gezet PATH — plist, test-stubs — wint van het vangnet).
set -uo pipefail
export PATH="${PATH:-/usr/bin:/bin}:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
INBOX="$REPO/opdrachten/inbox"; LOPEND="$REPO/opdrachten/lopend"; GEDAAN="$REPO/opdrachten/gedaan"; LOGMAP="$REPO/opdrachten/log"
MISLUKT="$REPO/opdrachten/mislukt"
LOCK="$REPO/opdrachten/.lock"
MAX_POGINGEN="${CC_INBOX_MAX_POGINGEN:-3}"
HARTSLAG_S="${CC_INBOX_HARTSLAG_S:-300}"
mkdir -p "$INBOX" "$LOPEND" "$GEDAAN" "$LOGMAP" "$MISLUKT"

LOG=""  # opdrachtenlog van de lopende opdracht; leeg = alleen het launchd-log (stderr)
log() {  # log <regel>  → stderr (launchd-log) + opdrachtenlog als dat er is
  if [[ -n "$LOG" ]]; then echo "$1" | tee -a "$LOG" >&2; else echo "$1" >&2; fi
}

melding() {  # melding <titel> <tekst> — resultaat altijd in het log (d)
  local titel="$1" tekst="$2" rc
  titel="${titel//\"/\'}"; tekst="${tekst//\"/\'}"
  tekst="${tekst//$'\n'/ }"
  if osascript -e "display notification \"${tekst:0:200}\" with title \"${titel:0:60}\"" >/dev/null 2>&1; then
    log ">> cc_inbox: melding verstuurd — ${titel:0:60}"
  else
    rc=$?
    log ">> cc_inbox: melding mislukt (osascript rc=$rc) — ${titel:0:60}: ${tekst:0:120}"
  fi
}

# ---- lock --------------------------------------------------------------------------------------------------------
if [[ -f "$LOCK" ]]; then
  pid="$(head -1 "$LOCK" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    exit 0  # er loopt al een run — stil niets doen (launchd probeert over ≤ 5 min opnieuw)
  fi
  log ">> cc_inbox: verweesde lock (pid ${pid:-?} leeft niet) opgeruimd"
  rm -f "$LOCK"
fi

# ---- handmatige CC actief in deze werkboom → wachten (zie kop) ---------------------------------------------------------
REPO_REAL="$(cd "$REPO" && pwd -P)"
cwd_van_pid() {  # cwd_van_pid <pid> → echte cwd, of leeg als niet leesbaar
  local lsof_bin
  lsof_bin="$(command -v lsof 2>/dev/null || true)"; [[ -z "$lsof_bin" && -x /usr/sbin/lsof ]] && lsof_bin=/usr/sbin/lsof
  [[ -n "$lsof_bin" ]] || return 0
  "$lsof_bin" -w -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
}
handmatige_cc() {  # → "pid<TAB>cwd-of-reden" van het eerste claude-proces in deze werkboom, anders leeg (rc 1)
  local naam="${CC_INBOX_CLAUDE_NAAM:-claude}" pid cwd
  for pid in $(pgrep -x "$naam" 2>/dev/null); do
    [[ "$pid" == "$$" ]] && continue
    cwd="$(cwd_van_pid "$pid")"
    if [[ -z "$cwd" ]]; then
      printf '%s\t%s\n' "$pid" "cwd niet leesbaar (lsof ontbreekt of faalt) — telt als actief"; return 0
    fi
    if [[ "$cwd" == "$REPO_REAL" || "$cwd" == "$REPO_REAL/"* ]]; then
      printf '%s\t%s\n' "$pid" "$cwd"; return 0
    fi
  done
  return 1
}
if actief="$(handmatige_cc)"; then
  log ">> cc_inbox: wacht — handmatige CC actief (pid ${actief%%$'\t'*}, ${actief#*$'\t'}) — geen herstel, geen pull, geen start; volgende tick opnieuw ($(date +%FT%T))"
  exit 0
fi

# ---- verweesde lopend-opdrachten (e): geen levende lock → elke .md in lopend/ is gestrand ----------------------------
laatste_logregel() {  # laatste_logregel <slug> → laatste inhoudelijke regel uit het opdrachtenlog (zonder >>-regels)
  local l="$LOGMAP/$1.log"
  [[ -f "$l" ]] || { echo ""; return; }
  grep -v '^>> cc_inbox' "$l" | grep -v '^[[:space:]]*$' | tail -1 | cut -c1-160
}
herstel_verweesd() {
  local bestand slug teller tellerbestand laatste
  while IFS= read -r -d '' bestand; do
    slug="$(basename "$bestand" .md)"
    tellerbestand="$LOGMAP/$slug.pogingen"
    teller="$(cat "$tellerbestand" 2>/dev/null || echo 0)"; [[ "$teller" =~ ^[0-9]+$ ]] || teller=0
    laatste="$(laatste_logregel "$slug")"
    LOG="$LOGMAP/$slug.log"
    if (( teller >= MAX_POGINGEN )); then
      { echo "MISLUKT ná $teller pogingen ($(date +%FT%T)) — laatste: ${laatste:-geen uitvoer}"; echo; cat "$bestand"; } > "$MISLUKT/$(basename "$bestand")"
      rm -f "$bestand" "$tellerbestand"
      log ">> cc_inbox: $slug verweesd in lopend/ ná $teller pogingen → opdrachten/mislukt/ (geen herstart meer; terug in inbox/ zetten = opnieuw proberen)"
      melding "CC MISLUKT DEFINITIEF: $slug" "${laatste:-na $teller pogingen, zie opdrachten/mislukt/}"
    else
      mv "$bestand" "$INBOX/$(basename "$bestand")"
      log ">> cc_inbox: $slug verweesd in lopend/ (run gestopt zonder afronding) → terug naar inbox/, poging $((teller + 1))/$MAX_POGINGEN ($(date +%FT%T))"
      melding "CC HERSTART: $slug (poging $((teller + 1))/$MAX_POGINGEN)" "${laatste:-vorige run stopte zonder afronding}"
    fi
    LOG=""
  done < <(find "$LOPEND" -maxdepth 1 -type f -name '*.md' -print0 2>/dev/null)
}
herstel_verweesd

# ---- lokale pull (ff-only, alleen schoon + geen lock — zie kop) -------------------------------------------------------
pull_ff_only() {
  [[ "${CC_INBOX_GEEN_PULL:-}" == "1" ]] && return 0
  local vuil; vuil="$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null || echo '?')"
  if [[ -n "$vuil" ]]; then
    echo ">> cc_inbox: pull overgeslagen — werkboom niet schoon ($(printf '%s\n' "$vuil" | wc -l | tr -d ' ') gewijzigd bestand(en))" >&2
    return 0
  fi
  local voor na uitvoer
  voor="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
  if ! uitvoer="$(git -C "$REPO" pull --ff-only origin main 2>&1)"; then
    echo ">> cc_inbox: pull overgeslagen — ff-only mislukt (gedivergeerd of geen netwerk): $(printf '%s' "$uitvoer" | tail -1 | cut -c1-200)" >&2
    return 0
  fi
  na="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
  [[ "$voor" != "$na" ]] && echo ">> cc_inbox: pull ff-only $(git -C "$REPO" rev-list --count "$voor..$na" 2>/dev/null || echo '?') commit(s) binnen → ${na:0:7} ($(date +%FT%T))" >&2
  return 0
}
pull_ff_only
# oudste bestand (mtime) — niets in de inbox = niets doen
OPDRACHT="$(find "$INBOX" -maxdepth 1 -type f -name '*.md' -print0 2>/dev/null | xargs -0 stat -f '%m %N' 2>/dev/null | sort -n | head -1 | cut -d' ' -f2-)"
[[ -n "$OPDRACHT" ]] || exit 0
echo $$ > "$LOCK"

SLUG="$(basename "$OPDRACHT" .md)"
DATUM="$(date +%Y-%m-%d)"
LOG="$LOGMAP/$DATUM-$SLUG.log"; [[ "$SLUG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}- ]] && LOG="$LOGMAP/$SLUG.log"  # slug mét datum: niet dubbel
TELLER="$LOGMAP/$SLUG.pogingen"
LOPEND_BESTAND="$LOPEND/$(basename "$OPDRACHT")"
POGING=$(( $(cat "$TELLER" 2>/dev/null || echo 0) + 1 )); echo "$POGING" > "$TELLER"
mv "$OPDRACHT" "$LOPEND_BESTAND"
log ">> cc_inbox: start $SLUG ($(date +%FT%T), poging $POGING/$MAX_POGINGEN) — log $LOG"

# ---- elke stop = logregel + melding (b) --------------------------------------------------------------------------
AFGEROND=0; CLAUDE_PID=""; HARTSLAG_PID=""
kill_boom() {  # kill_boom <pid> — beëindigt de hele nakomelingenboom (kleinkinderen eerst), dan het proces zelf
  local kind
  for kind in $(pgrep -P "$1" 2>/dev/null); do kill_boom "$kind"; done
  kill -TERM "$1" 2>/dev/null
  return 0
}
stop_kinderen() {  # hartslag-subshel + claude-subshel mét hun hele boom (claude en zíjn kinderen, tee)
  [[ -n "$HARTSLAG_PID" ]] && kill_boom "$HARTSLAG_PID"
  [[ -n "$CLAUDE_PID" ]] && kill_boom "$CLAUDE_PID"
  return 0
}
bij_signaal() {  # bij_signaal <naam>
  AFGEROND=1
  stop_kinderen
  log ">> cc_inbox: GESTOPT door signaal $1 ($(date +%FT%T)) — $SLUG blijft in opdrachten/lopend/, volgende tick zet 'm terug in inbox/ (poging $POGING/$MAX_POGINGEN gebruikt)"
  melding "CC GESTOPT: $SLUG (signaal $1)" "run afgebroken; volgende tick herstart (poging $POGING/$MAX_POGINGEN gebruikt)"
  rm -f "$LOCK"
  exit 143
}
bij_exit() {
  local rc=$?
  stop_kinderen
  if [[ $AFGEROND -eq 0 ]]; then
    log ">> cc_inbox: GESTOPT onverwacht (exit $rc, $(date +%FT%T)) — $SLUG blijft in opdrachten/lopend/"
    melding "CC GESTOPT: $SLUG (onverwacht, exit $rc)" "zie $LOG"
  fi
  rm -f "$LOCK"
}
trap 'bij_signaal TERM' TERM
trap 'bij_signaal INT' INT
trap 'bij_signaal HUP' HUP
trap bij_exit EXIT

for tool in claude git; do
  command -v "$tool" >/dev/null || { AFGEROND=1; log "FOUT: $tool niet gevonden op PATH=$PATH"; melding "CC MISLUKT: $SLUG" "$tool niet gevonden op PATH"; exit 1; }
done

PROMPT="$(cat "$LOPEND_BESTAND")
---
Werkloop automatisch (CLAUDE.md § Werkwijze \"Werkloop automatisch (14-09)\"): deze opdracht komt uit opdrachten/inbox/ en staat nu als opdrachten/lopend/$(basename "$OPDRACHT"). Sluit af met (1) het eindrapport als docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md + regel bovenaan in docs/rapporten/INDEX.md (incl. \"werkt in productie: ja/nee/niet gemeten\"), (2) dit opdrachtbestand naar opdrachten/gedaan/ mét bovenin de kopregel \"uitgevoerd <datum>, rapport: docs/rapporten/<bestand>\", (3) committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat). Peter kijkt niet mee: vragen stellen kan niet, kies zelf en leg keuzes vast in het rapport."

RAPPORTEN_VOOR="$(ls -1 "$REPO/docs/rapporten"/*.md 2>/dev/null | sort || true)"
cd "$REPO"
START_S=$(date +%s)
# claude als achtergrondkind (pid bekend voor de traps) mét eigen tee; de exitcode van CLAUDE (niet van tee) gaat via
# het statusbestand $LOG.rc naar de voorgrond; hartslag (a) draait parallel.
rm -f "$LOG.rc"
(
  claude -p "$PROMPT" --permission-mode "${CC_INBOX_PERMISSION_MODE:-auto}" </dev/null 2>&1 | tee -a "$LOG"
  echo "${PIPESTATUS[0]}" > "$LOG.rc"
) &
CLAUDE_PID=$!
# hartslag zonder de stdout/stderr van het script (een achterblijvende `sleep` zou anders de launchd-/testpipe openhouden)
(
  while sleep "$HARTSLAG_S"; do
    echo ">> cc_inbox: loopt nog ($(( ($(date +%s) - START_S) / 60 )) min, $(date +%FT%T)) — claude draait, geen uitvoer is normaal tot het eindrapport" >> "$LOG"
  done
) </dev/null >/dev/null 2>&1 &
HARTSLAG_PID=$!
wait "$CLAUDE_PID"; rc=$?
kill_boom "$HARTSLAG_PID"; HARTSLAG_PID=""
CLAUDE_PID=""
if [[ -f "$LOG.rc" ]]; then rc="$(cat "$LOG.rc")"; rm -f "$LOG.rc"; fi  # claude's code; ontbreekt = subshel gedood
[[ "$rc" =~ ^[0-9]+$ ]] || rc=1
AFGEROND=1
log ">> cc_inbox: claude eindigde met code $rc ($(date +%FT%T), $(( ($(date +%s) - START_S) / 60 )) min)"

LAATSTE="$(laatste_logregel "$SLUG")"
LIMIET=""
if grep -v '^>> cc_inbox' "$LOG" | grep -qiE "spend limit|usage limit|rate limit|out of (usage )?credits|monthly limit"; then
  LIMIET="LIMIET — claude.ai/admin-settings/usage"
  log ">> cc_inbox: $LIMIET (claude weigerde op een gebruiks-/budgetlimiet; herstart heeft pas zin ná bijkopen/reset)"
fi
RAPPORT="$(comm -13 <(printf '%s\n' "$RAPPORTEN_VOOR") <(ls -1 "$REPO/docs/rapporten"/*.md 2>/dev/null | sort) | grep -v INDEX.md | tail -1 || true)"
[[ -n "$RAPPORT" ]] && RAPPORT="docs/rapporten/$(basename "$RAPPORT")" || RAPPORT="geen"

if [[ $rc -eq 0 ]]; then
  if [[ -f "$LOPEND_BESTAND" ]]; then  # CC verplaatste zelf niet (bv. Bash geweigerd in acceptEdits) → het script doet het
    { echo "uitgevoerd $DATUM, rapport: $RAPPORT"; echo; cat "$LOPEND_BESTAND"; } > "$GEDAAN/$(basename "$OPDRACHT")"
    rm -f "$LOPEND_BESTAND"
    log ">> cc_inbox: $SLUG → opdrachten/gedaan/ (kopregel door het script, rapport: $RAPPORT)"
  fi
  rm -f "$TELLER"
  melding "CC klaar: $SLUG" "${LAATSTE:-klaar (geen uitvoer)}"
else
  log ">> cc_inbox: $SLUG blijft in opdrachten/lopend/ — volgende tick: terug naar inbox/ als poging $POGING < $MAX_POGINGEN, anders opdrachten/mislukt/"
  melding "CC MISLUKT: $SLUG (code $rc${LIMIET:+, $LIMIET})" "${LIMIET:-${LAATSTE:-zie $LOG}}"
fi
exit "$rc"
