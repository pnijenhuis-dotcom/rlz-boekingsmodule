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
# Twee schrijvers in één werkboom (guard 16-09 nacht; incident 16-09 avond: de inbox-run "omzet-store" (20:24–21:39) en een
# handmatige CC-sessie (gestart ná 20:24, VGG blok 9 / accordeur-uitnodiging) werkten parallel — de een committe het werk
# van de ander (57ca852, c1df300). De detectie hierboven was niet stuk (om 21:44 zag de tick pid 36860 wél): ze kijkt
# alleen bij de START van een inbox-run; een mens die daarná `claude` start ziet niets. Sinds 16-09 nacht:
#   (g1) de lock `opdrachten/.lock` draagt DRIE regels: pid, soort (`inbox` | `handmatig`), starttijd. Een levende lock van
#        soort `handmatig` (gezet door de terminal-wrapper `rlz cc`, scripts/zsh/rlz.zsh) = logregel ">> cc_inbox: wacht —
#        handmatige CC (rlz cc) actief (pid N, sinds T)" + exit 0; een levende `inbox`-lock blijft stil (er loopt al een run).
#        Een lock mét een pid die niet leeft wordt zoals eerder gemeld en opgeruimd. Een lock zonder soort = `inbox` (oud).
#   (g2) `.git/index.lock` aanwezig = een ander proces zit in git (commit/stage bezig) → wachten mét logregel, óók zonder
#        claude-proces; ouder dan CC_INBOX_INDEX_LOCK_MAX_S (default 1800 s) = verweesd van een gecrashte git → gemeld en
#        genegeerd (nooit verwijderd — dat doet een mens).
#   (g3) is de werkboom bij het oppakken niet schoon (tracked wijzigingen zonder levende lock/claude), dan is dat werk van een
#        gestopte run: logregel "LET OP — werkboom niet schoon bij start (N bestanden)" zodat het in het opdrachtenlog staat;
#        de CC-run zelf beslist (committen als eigen commit, zoals 57ca852) — geen blokkade, anders staat de inbox voorgoed stil.
#   Omgekeerd (mens start terwijl de inbox draait): `rlz cc` weigert bij een levende `inbox`-lock mét "inbox-run actief sinds …,
#   wacht of `rlz inbox stop`"; `rlz inbox stop` stuurt TERM naar de inbox-run (trap → GESTOPT-regel, opdracht terug via (e)).
#   Guard: backend/tests/unit/test_cc_inbox_parallel.py.
# Wachten is nooit stil (rij (h), 17-09; incident 17-09: van 08:19 tot ná 15:20 startte geen enkele van zes klaarliggende
# opdrachten — élke tick logde "wacht — handmatige CC actief (pid 82714, …)": een interactieve `claude` in de repo-root, gestart
# 08:19:00 (tijdens de laatste inbox-run, dus niet via `rlz cc`), bleef zeven uur open terwijl Peter op de inbox wachtte. De
# regel (f) werkte precies zoals ontworpen; het gat was dat niemand het zag). Sinds 17-09:
#   (h1) de wachtregel draagt de duur en het werk: "… sinds HH:MM:SS (N min), M opdracht(en) klaar in inbox/";
#   (h2) ná CC_INBOX_WACHT_MELDING_S (default 1800 s) aaneengesloten wachten op dezelfde pid één macOS-melding "CC-inbox wacht
#        al N min op handmatige CC (pid …) — M opdrachten klaar; sluit die sessie of `rlz inbox vrijgeven`", daarna hoogstens
#        elke CC_INBOX_WACHT_HERHAAL_S (default 3600 s) opnieuw; stand in opdrachten/log/.wacht-<pid> (eerste tick, laatste
#        melding), opgeruimd zodra er niet meer gewacht wordt;
#   (h3) bewuste vrijgave: `rlz inbox vrijgeven [pid]` schrijft opdrachten/.vrijgave mét de pid van de handmatige sessie —
#        die pid houdt de inbox dan niet meer tegen (logregel "vrijgegeven door Peter … — twee schrijvers in één werkboom,
#        risico bewust aanvaard"); het bestand vervalt zodra die pid niet meer leeft. Nooit automatisch: de 16-09-guard
#        blijft de default, alleen een mens kiest voor parallel.
#   Guard: backend/tests/unit/test_cc_inbox_herstel.py (h1–h3) + test_cc_inbox_parallel.py (`rlz inbox vrijgeven`).
#   (i) 18-09 avond (inbox-hygiëne): een .md in lopend/ die óók in gedaan/ staat mét kopregel "uitgevoerd …" is AF —
#       de tick ruimt de lopend-kopie op (logregel, teller weg) en start NIETS opnieuw; `rlz inbox status` somt lopend/ op
#       als loopt (levende lock) / af (kopie in gedaan/) / gestrand (geen levende lock). Guard: test_cc_inbox_herstel.py
#       `test_lopend_kopie_van_afgeronde_opdracht_*`.
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

# ---- wachten op een handmatige CC is nooit stil (h1–h3) ---------------------------------------------------------------
VRIJGAVE="$REPO/opdrachten/.vrijgave"
WACHT_MELDING_S="${CC_INBOX_WACHT_MELDING_S:-1800}"
WACHT_HERHAAL_S="${CC_INBOX_WACHT_HERHAAL_S:-3600}"
klaar_in_inbox() { find "$INBOX" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' '; }
vrijgegeven() {  # vrijgegeven <pid> → rc 0 als Peter déze pid bewust vrijgaf (rlz inbox vrijgeven); dood = bestand weg
  [[ -f "$VRIJGAVE" ]] || return 1
  local vpid; vpid="$(sed -n 1p "$VRIJGAVE" 2>/dev/null || true)"
  if [[ -z "$vpid" ]] || ! kill -0 "$vpid" 2>/dev/null; then rm -f "$VRIJGAVE"; return 1; fi
  [[ "$vpid" == "$1" ]]
}
wacht_op_handmatig() {  # wacht_op_handmatig <pid> <omschrijving> — logregel mét duur + werk, melding ná de drempel, exit 0
  local pid="$1" omschr="$2" nu stand eerste laatste_melding duur_s duur_min klaar
  nu=$(date +%s); stand="$LOGMAP/.wacht-$pid"
  eerste="$(sed -n 1p "$stand" 2>/dev/null || true)"; laatste_melding="$(sed -n 2p "$stand" 2>/dev/null || true)"
  [[ "$eerste" =~ ^[0-9]+$ ]] || { eerste=$nu; laatste_melding=0; }
  [[ "$laatste_melding" =~ ^[0-9]+$ ]] || laatste_melding=0
  duur_s=$(( nu - eerste )); duur_min=$(( duur_s / 60 )); klaar="$(klaar_in_inbox)"
  log ">> cc_inbox: wacht — $omschr — geen herstel, geen pull, geen start; sinds $(date -r "$eerste" +%T 2>/dev/null || echo '?') ($duur_min min), $klaar opdracht(en) klaar in inbox/; volgende tick opnieuw ($(date +%FT%T))"
  if (( duur_s >= WACHT_MELDING_S )) && (( nu - laatste_melding >= WACHT_HERHAAL_S )); then
    melding "CC-inbox wacht al $duur_min min op handmatige CC (pid $pid)" "$klaar opdracht(en) klaar in inbox/ — sluit die sessie af of \`rlz inbox vrijgeven\` als ze parallel mag"
    laatste_melding=$nu
  fi
  printf '%s\n%s\n' "$eerste" "$laatste_melding" > "$stand"
  exit 0
}
ruim_wachtstand_op() { rm -f "$LOGMAP"/.wacht-* 2>/dev/null || true; }

# ---- lock --------------------------------------------------------------------------------------------------------
if [[ -f "$LOCK" ]]; then
  pid="$(sed -n 1p "$LOCK" 2>/dev/null || true)"
  soort="$(sed -n 2p "$LOCK" 2>/dev/null || true)"; soort="${soort:-inbox}"
  sinds="$(sed -n 3p "$LOCK" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if [[ "$soort" == "handmatig" ]]; then  # (g1) rlz cc-wrapper actief → altijd zichtbaar wachten (h1–h3)
      if vrijgegeven "$pid"; then
        log ">> cc_inbox: handmatige CC (rlz cc, pid $pid) vrijgegeven door Peter (rlz inbox vrijgeven) — inbox start naast die sessie; twee schrijvers in één werkboom, risico bewust aanvaard ($(date +%FT%T))"
      else
        wacht_op_handmatig "$pid" "handmatige CC (rlz cc) actief (pid $pid, sinds ${sinds:-?})"
      fi
    else
      exit 0  # er loopt al een inbox-run — stil niets doen (launchd probeert over ≤ 5 min opnieuw)
    fi
  else
    log ">> cc_inbox: verweesde lock (pid ${pid:-?}, soort $soort, leeft niet) opgeruimd"
    rm -f "$LOCK"
  fi
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
  if vrijgegeven "${actief%%$'\t'*}"; then
    log ">> cc_inbox: handmatige CC (pid ${actief%%$'\t'*}, ${actief#*$'\t'}) vrijgegeven door Peter (rlz inbox vrijgeven) — inbox start naast die sessie; twee schrijvers in één werkboom, risico bewust aanvaard ($(date +%FT%T))"
  else
    wacht_op_handmatig "${actief%%$'\t'*}" "handmatige CC actief (pid ${actief%%$'\t'*}, ${actief#*$'\t'})"
  fi
fi
ruim_wachtstand_op  # niet (meer) aan het wachten → stand weg, zodat een volgende wachtperiode opnieuw telt

# ---- (g2) git bezig in deze werkboom (.git/index.lock) → wachten; verweesd (te oud) = melden en negeren ---------------
GIT_INDEX_LOCK="$REPO/.git/index.lock"
INDEX_LOCK_MAX_S="${CC_INBOX_INDEX_LOCK_MAX_S:-1800}"
if [[ -e "$GIT_INDEX_LOCK" ]]; then
  leeftijd=$(( $(date +%s) - $(stat -f '%m' "$GIT_INDEX_LOCK" 2>/dev/null || echo 0) ))
  if (( leeftijd < INDEX_LOCK_MAX_S )); then
    log ">> cc_inbox: wacht — git bezig in deze werkboom (.git/index.lock, ${leeftijd}s oud, eigenaar onbekend) — geen herstel, geen pull, geen start; volgende tick opnieuw ($(date +%FT%T))"
    exit 0
  fi
  log ">> cc_inbox: LET OP — .git/index.lock is ${leeftijd}s oud (> ${INDEX_LOCK_MAX_S}s): verweesd van een gestopte git, genegeerd (niet verwijderd — dat doet een mens; git zelf weigert intussen elke commit)"
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
    # (i) 18-09 avond (inbox-hygiëne): staat dezelfde opdracht al in gedaan/ mét de kopregel "uitgevoerd …" (een handmatige
    # of parallelle run kopieerde naar gedaan/ zonder lopend/ op te ruimen), dan is dit werk AF — kopie opruimen, teller weg,
    # NOOIT terug naar inbox/ (dat zou afgerond werk tot drie keer opnieuw laten draaien). `rlz inbox status` toont zo'n kopie
    # als "af (staat in gedaan/)", nooit als "loopt".
    if [[ -f "$GEDAAN/$(basename "$bestand")" ]] && head -1 "$GEDAAN/$(basename "$bestand")" | grep -q '^uitgevoerd '; then
      rm -f "$bestand" "$tellerbestand"
      log ">> cc_inbox: $slug stond nog in lopend/ maar is al afgerond (opdrachten/gedaan/ mét kopregel 'uitgevoerd') → kopie in lopend/ opgeruimd, geen herstart ($(date +%FT%T))"
      LOG=""
      continue
    fi
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
printf '%s\ninbox\n%s\n' "$$" "$(date +%FT%T)" > "$LOCK"  # (g1) pid, soort, sinds

SLUG="$(basename "$OPDRACHT" .md)"
DATUM="$(date +%Y-%m-%d)"
LOG="$LOGMAP/$DATUM-$SLUG.log"; [[ "$SLUG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}- ]] && LOG="$LOGMAP/$SLUG.log"  # slug mét datum: niet dubbel
TELLER="$LOGMAP/$SLUG.pogingen"
LOPEND_BESTAND="$LOPEND/$(basename "$OPDRACHT")"
POGING=$(( $(cat "$TELLER" 2>/dev/null || echo 0) + 1 )); echo "$POGING" > "$TELLER"
mv "$OPDRACHT" "$LOPEND_BESTAND"
log ">> cc_inbox: start $SLUG ($(date +%FT%T), poging $POGING/$MAX_POGINGEN) — log $LOG"
VUIL_N="$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${VUIL_N:-0}" != "0" ]]; then  # (g3) werk van een gestopte run — zichtbaar, geen blokkade
  log ">> cc_inbox: LET OP — werkboom niet schoon bij start ($VUIL_N tracked bestand(en) gewijzigd, geen levende lock/claude): werk van een gestopte run — de CC-run beslist (eigen commit of laten staan), zie opdracht-guard 16-09"
fi

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

# Regels per domein met LEESPLICHT (Peter 17-09, BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT"): een opdracht
# draagt de kopregel "Domeinen: a, b" (Cowork schrijft die) → de startprompt eist eerst het volledig lezen van
# docs/regels/a.md, docs/regels/b.md; ontbreekt de kopregel (of noemt hij een onbekend domein) → CC leidt de domeinen af uit
# de geraakte paden via docs/regels/INDEX.md en noemt dat expliciet. Het eindrapport MOET een sectie "## Gelezen regels" dragen
# (bestandsnamen + regelaantallen; guard backend/tests/unit/test_rapporten_gelezen_regels.py).
domeinen_uit_opdracht() {  # → lijst regelsbestanden (bestaand) uit de kopregel "Domeinen: a, b"; leeg = geen/onbekend
  local regel dom uit=()
  regel="$(grep -m1 -E '^Domeinen:' "$LOPEND_BESTAND" 2>/dev/null | sed -E 's/^Domeinen:[[:space:]]*//')"
  [[ -n "$regel" ]] || return 0
  for dom in $(printf '%s' "$regel" | tr ',' ' '); do
    dom="${dom//\`/}"; dom="${dom%.md}"; dom="${dom#docs/regels/}"
    [[ -f "$REPO/docs/regels/$dom.md" ]] && uit+=("docs/regels/$dom.md")
  done
  printf '%s\n' ${uit[@]+"${uit[@]}"}
}
LEESPLICHT="$(domeinen_uit_opdracht | tr '\n' ' ' | sed 's/ $//')"
if [[ -n "$LEESPLICHT" ]]; then
  LEESPLICHT_TEKST="LEESPLICHT (Domeinen-kopregel): lees EERST volledig, vóór je iets anders doet: ${LEESPLICHT// /, } — niet gelezen = niet beginnen."
  log ">> cc_inbox: leesplicht uit de kopregel Domeinen: ${LEESPLICHT// /, }"
else
  LEESPLICHT_TEKST="LEESPLICHT (geen of onbekende Domeinen-kopregel): leid de domeinen af uit de paden die je gaat raken via docs/regels/INDEX.md, lees die docs/regels/<domein>.md volledig VÓÓR je begint en noem in het rapport expliciet dat je ze zo hebt afgeleid."
  log ">> cc_inbox: geen (geldige) Domeinen-kopregel in de opdracht — CC leidt de domeinen af via docs/regels/INDEX.md"
fi
PROMPT="$(cat "$LOPEND_BESTAND")
---
$LEESPLICHT_TEKST
Werkloop automatisch (CLAUDE.md § Werkwijze \"Werkloop automatisch (14-09)\"): deze opdracht komt uit opdrachten/inbox/ en staat nu als opdrachten/lopend/$(basename "$OPDRACHT"). Sluit af met (1) het eindrapport als docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md + regel bovenaan in docs/rapporten/INDEX.md (incl. \"werkt in productie: ja/nee/niet gemeten\" én een sectie \"## Gelezen regels\" mét élk gelezen docs/regels/<domein>.md en zijn regelaantal — verplicht, guard test_rapporten_gelezen_regels.py), (2) dit opdrachtbestand naar opdrachten/gedaan/ mét bovenin de kopregel \"uitgevoerd <datum>, rapport: docs/rapporten/<bestand>\", (3) committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat). Peter kijkt niet mee: vragen stellen kan niet, kies zelf en leg keuzes vast in het rapport."

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
