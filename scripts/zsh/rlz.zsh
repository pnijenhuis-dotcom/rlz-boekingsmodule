# Werkloop automatisch 14-09 — terminalfunctie `rlz`. Installeren (één regel in ~/.zshrc):
#   source "/Users/mr.x/Claude/Projects/Rlz boekings module/scripts/zsh/rlz.zsh"
#   rlz plan     → scripts/gcp/vgg_blok7_odoo_writes.sh plan (alleen dry-runs, schrijft niets)
#   rlz meting [onderdeel]  → nameting-workflow op GitHub starten (gh workflow run nameting.yml; default alles)
#   rlz status   → git status + de laatste 5 rapporten uit docs/rapporten/INDEX.md + de stand van de inbox-lock
#   rlz inbox    → scripts/cc_inbox.sh nu draaien (zonder op launchd te wachten)
#   rlz inbox status | stop → lock + lopend/ tonen (loopt / af / gestrand — 18-09) / de lopende inbox-run netjes stoppen (TERM →
#                             GESTOPT-regel, opdracht terug via (e))
#   rlz inbox vrijgeven [pid] → (17-09, rij (h3)) déze handmatige claude-sessie houdt de inbox niet meer tegen: schrijft
#                             opdrachten/.vrijgave mét de pid (default: de claude met cwd in deze repo); bewust parallel = risico
#                             van twee schrijvers in één werkboom aanvaard — alleen als de sessie stil staat of eigen paden raakt
#   rlz cc [claude-args…]   → HANDMATIGE Claude Code in deze repo mét inbox-lock (guard 16-09 nacht, "nooit twee schrijvers"):
#                             weigert als er een inbox-run loopt ("inbox-run actief sinds …, wacht of `rlz inbox stop`"), zet anders
#                             opdrachten/.lock = pid / handmatig / starttijd zodat launchd-ticks zichtbaar wachten (ook als de cwd
#                             van claude buiten de repo ligt of pgrep/lsof niets zien), en ruimt de lock op als claude stopt.
#   rlz          → naar de repo-map
# Seam voor de guard-test (backend/tests/unit/test_cc_inbox_parallel.py): RLZ_REPO overschrijft de repo-map.
rlz() {
  local repo="${RLZ_REPO:-/Users/mr.x/Claude/Projects/Rlz boekings module}"
  local lock="$repo/opdrachten/.lock"
  cd "$repo" || return 1
  case "${1:-}" in
    "") ;;
    plan)   shift; "$repo/scripts/gcp/vgg_blok7_odoo_writes.sh" plan "$@" ;;
    meting) shift; gh workflow run nameting.yml -f "onderdeel=${1:-alles}" && echo ">> gestart — volgen: gh run list --workflow nameting.yml --limit 3" ;;
    status) git -C "$repo" status --short --branch; echo; echo "laatste 5 rapporten:"; grep -m5 '^- \[' "$repo/docs/rapporten/INDEX.md"; echo; _rlz_lock_stand "$lock" ;;
    inbox)
      case "${2:-}" in
        "")     "$repo/scripts/cc_inbox.sh" ;;
        status) _rlz_lock_stand "$lock"; _rlz_vrijgave_stand "$repo"; _rlz_lopend_stand "$repo" "$lock" ;;
        stop)   _rlz_inbox_stop "$lock" ;;
        vrijgeven) _rlz_inbox_vrijgeven "$repo" "${3:-}" ;;
        *)      echo "gebruik: rlz inbox [status|stop|vrijgeven [pid]]" >&2; return 2 ;;
      esac ;;
    cc)     shift; _rlz_cc "$repo" "$lock" "$@" ;;
    *)      echo "gebruik: rlz [plan|meting [alles|a|b|c|d|e|reconciliatie]|status|inbox [status|stop|vrijgeven [pid]]|cc [claude-args…]]" >&2; return 2 ;;
  esac
}

# _rlz_leeft <pid> → rc 0 als het proces leeft (een zombie — beëindigd, nog niet opgeruimd door zijn ouder — telt als dood)
_rlz_leeft() {
  [[ -n "$1" ]] && kill -0 "$1" 2>/dev/null || return 1
  [[ "$(ps -o stat= -p "$1" 2>/dev/null | tr -d ' ')" != Z* ]]
}

# _rlz_lock_lees <lock> → zet RLZ_LOCK_PID / RLZ_LOCK_SOORT / RLZ_LOCK_SINDS; rc 0 = levende lock, 1 = geen (of dood)
_rlz_lock_lees() {
  RLZ_LOCK_PID=""; RLZ_LOCK_SOORT=""; RLZ_LOCK_SINDS=""
  [[ -f "$1" ]] || return 1
  RLZ_LOCK_PID="$(sed -n 1p "$1" 2>/dev/null)"
  RLZ_LOCK_SOORT="$(sed -n 2p "$1" 2>/dev/null)"; RLZ_LOCK_SOORT="${RLZ_LOCK_SOORT:-inbox}"
  RLZ_LOCK_SINDS="$(sed -n 3p "$1" 2>/dev/null)"
  _rlz_leeft "$RLZ_LOCK_PID"
}

_rlz_lock_stand() {
  if _rlz_lock_lees "$1"; then
    echo "inbox-lock: $RLZ_LOCK_SOORT actief (pid $RLZ_LOCK_PID, sinds ${RLZ_LOCK_SINDS:-?})"
  elif [[ -f "$1" ]]; then
    echo "inbox-lock: verweesd (pid ${RLZ_LOCK_PID:-?} leeft niet) — de volgende tick ruimt 'm op"
  else
    echo "inbox-lock: geen (niets loopt)"
  fi
}

_rlz_inbox_stop() {
  if ! _rlz_lock_lees "$1"; then echo "geen levende inbox-run om te stoppen"; return 0; fi
  if [[ "$RLZ_LOCK_SOORT" != "inbox" ]]; then
    echo "de lock is van een handmatige sessie (pid $RLZ_LOCK_PID, sinds ${RLZ_LOCK_SINDS:-?}) — sluit die sessie zelf af" >&2; return 1
  fi
  kill -TERM "$RLZ_LOCK_PID" 2>/dev/null || { echo "TERM naar pid $RLZ_LOCK_PID mislukt" >&2; return 1; }
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do _rlz_leeft "$RLZ_LOCK_PID" || break; sleep 0.5; done
  if _rlz_leeft "$RLZ_LOCK_PID"; then
    echo "inbox-run pid $RLZ_LOCK_PID kreeg TERM maar leeft nog — kijk in ~/Library/Logs/cc-inbox.log"; return 1
  fi
  echo "inbox-run pid $RLZ_LOCK_PID gestopt (GESTOPT-regel in het opdrachtenlog; de opdracht gaat bij de volgende tick terug naar inbox/)"
}

_rlz_cc() {
  local repo="$1" lock="$2"; shift 2
  if _rlz_lock_lees "$lock"; then
    if [[ "$RLZ_LOCK_SOORT" == "inbox" ]]; then
      echo "inbox-run actief sinds ${RLZ_LOCK_SINDS:-?} (pid $RLZ_LOCK_PID) — wacht of \`rlz inbox stop\`; nooit twee schrijvers in één werkboom" >&2
    else
      echo "er loopt al een handmatige CC via rlz cc (pid $RLZ_LOCK_PID, sinds ${RLZ_LOCK_SINDS:-?}) — sluit die eerst af" >&2
    fi
    return 1
  fi
  [[ -f "$lock" ]] && rm -f "$lock"  # dode lock — zelfde opruiming als de tick
  mkdir -p "$(dirname "$lock")"
  printf '%s\nhandmatig\n%s\n' "$$" "$(date +%FT%T)" > "$lock"
  echo ">> rlz cc: inbox-lock gezet (pid $$, handmatig) — launchd-ticks wachten tot deze sessie stopt" >&2
  local rc=0
  {
    claude "$@" || rc=$?
  } always {
    if [[ "$(sed -n 1p "$lock" 2>/dev/null)" == "$$" ]]; then rm -f "$lock"; echo ">> rlz cc: inbox-lock opgeruimd" >&2; fi
  }
  return $rc
}

# (i) 18-09 avond (inbox-hygiëne): lopend/ per bestand — "loopt" ALLEEN bij een levende lock; een kopie die al in gedaan/ staat
# (kopregel "uitgevoerd …") is "af" en wordt door de volgende tick opgeruimd; zonder levende lock = "gestrand" (tick zet 'm
# terug in inbox/). Nooit "loopt" tonen voor werk dat af is.
_rlz_lopend_stand() {
  local repo="$1" lock="$2" f naam stand
  local -a bestanden
  bestanden=("$repo"/opdrachten/lopend/*.md(N))
  if (( ${#bestanden} == 0 )); then echo "lopend/: leeg"; return 0; fi
  local levend=0; _rlz_lock_lees "$lock" && levend=1
  for f in "${bestanden[@]}"; do
    naam="$(basename "$f")"
    if [[ -f "$repo/opdrachten/gedaan/$naam" ]] && head -1 "$repo/opdrachten/gedaan/$naam" | grep -q '^uitgevoerd '; then
      stand="af (staat in gedaan/ — de volgende tick ruimt de kopie in lopend/ op)"
    elif (( levend )); then
      stand="loopt ($RLZ_LOCK_SOORT, pid $RLZ_LOCK_PID, sinds ${RLZ_LOCK_SINDS:-?})"
    else
      stand="gestrand (geen levende lock — de volgende tick zet 'm terug in inbox/)"
    fi
    echo "lopend/: $naam — $stand"
  done
}

# rij (h3) 17-09: bewuste vrijgave van een handmatige claude-sessie — de inbox-tick behandelt die pid niet meer als blokkade.
_rlz_vrijgave_stand() {
  local v="$1/opdrachten/.vrijgave" vpid
  [[ -f "$v" ]] || return 0
  vpid="$(sed -n 1p "$v" 2>/dev/null)"
  if _rlz_leeft "$vpid"; then echo "vrijgave: handmatige CC pid $vpid houdt de inbox niet tegen (rlz inbox vrijgeven, $(sed -n 2p "$v" 2>/dev/null))"
  else echo "vrijgave: verlopen (pid ${vpid:-?} leeft niet) — de volgende tick ruimt 'm op"; fi
}
_rlz_inbox_vrijgeven() {
  local repo="$1" pid="${2:-}" naam="${CC_INBOX_CLAUDE_NAAM:-claude}" kandidaat cwd echt
  echt="$(cd "$repo" && pwd -P)"
  if [[ -z "$pid" ]]; then
    for kandidaat in $(pgrep -x "$naam" 2>/dev/null); do
      cwd="$(/usr/sbin/lsof -w -a -p "$kandidaat" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
      if [[ "$cwd" == "$echt" || "$cwd" == "$echt/"* ]]; then pid="$kandidaat"; break; fi
    done
  fi
  [[ -n "$pid" ]] || { echo "geen handmatige claude in deze repo gevonden — geef de pid mee: rlz inbox vrijgeven <pid>" >&2; return 1; }
  _rlz_leeft "$pid" || { echo "pid $pid leeft niet — niets vrij te geven" >&2; return 1; }
  mkdir -p "$repo/opdrachten"
  printf '%s\n%s\n' "$pid" "$(date +%FT%T)" > "$repo/opdrachten/.vrijgave"
  echo ">> rlz inbox vrijgeven: pid $pid vrijgegeven — de eerstvolgende tick (≤ 5 min) start de oudste inbox-opdracht náást deze sessie; twee schrijvers in één werkboom = alleen eigen paden stagen, geen rebase/stash"
}
