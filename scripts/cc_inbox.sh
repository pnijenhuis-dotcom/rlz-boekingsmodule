#!/usr/bin/env bash
# Werkloop automatisch 14-09 (besluit Peter 14-09: Cowork schrijft opdrachten, launchd start Claude Code, Peter test en meldt).
#   scripts/cc_inbox.sh            → neemt het OUDSTE .md-bestand uit opdrachten/inbox/, verplaatst het naar opdrachten/lopend/,
#                                    start `claude -p` met de inhoud als prompt vanuit de repo-root, logt naar
#                                    opdrachten/log/<datum>-<slug>.log en stuurt een macOS-melding "CC klaar: <slug> — <laatste regel>".
# Eén tegelijk: lock opdrachten/.lock (mét pid). Staat er een lock van een levend proces → niets doen (exit 0). Een lock
# van een dood proces (crash/reboot) wordt gemeld en opgeruimd — anders zou de inbox voor altijd stilstaan.
# Permissies: --permission-mode ${CC_INBOX_PERMISSION_MODE:-acceptEdits} + de bestaande .claude/settings.local.json van de
# repo (deny-lijst geldt: geen git push door de agent, geen secrets; de Stop-hook pusht ná de run zoals altijd).
# Afronding: exit 0 van claude én het bestand staat nog in lopend/ → het script verplaatst het naar gedaan/ mét kopregel
# "uitgevoerd <datum>, rapport: docs/rapporten/<bestand>" (nieuwste rapport dat tijdens de run is bijgekomen, anders "geen").
# Exit ≠ 0 → bestand blijft in lopend/ (zichtbaar), melding "CC MISLUKT".
# Geen TTY nodig (launchd). PATH wordt door de plist gezet; hier als vangnet aangevuld voor een handmatige start.
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
INBOX="$REPO/opdrachten/inbox"; LOPEND="$REPO/opdrachten/lopend"; GEDAAN="$REPO/opdrachten/gedaan"; LOGMAP="$REPO/opdrachten/log"
LOCK="$REPO/opdrachten/.lock"
mkdir -p "$INBOX" "$LOPEND" "$GEDAAN" "$LOGMAP"

melding() {  # melding <titel> <tekst>
  local titel="$1" tekst="$2"
  titel="${titel//\"/\'}"; tekst="${tekst//\"/\'}"
  osascript -e "display notification \"${tekst:0:200}\" with title \"${titel:0:60}\"" >/dev/null 2>&1 || true
}

# ---- lock --------------------------------------------------------------------------------------------------------
if [[ -f "$LOCK" ]]; then
  pid="$(head -1 "$LOCK" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    exit 0  # er loopt al een run — stil niets doen (launchd probeert over ≤ 5 min opnieuw)
  fi
  echo ">> cc_inbox: verweesde lock (pid ${pid:-?} leeft niet) opgeruimd" >&2
  rm -f "$LOCK"
fi
# oudste bestand (mtime) — niets in de inbox = niets doen
OPDRACHT="$(find "$INBOX" -maxdepth 1 -type f -name '*.md' -print0 2>/dev/null | xargs -0 stat -f '%m %N' 2>/dev/null | sort -n | head -1 | cut -d' ' -f2-)"
[[ -n "$OPDRACHT" ]] || exit 0
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

SLUG="$(basename "$OPDRACHT" .md)"
DATUM="$(date +%Y-%m-%d)"
LOG="$LOGMAP/$DATUM-$SLUG.log"; [[ "$SLUG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}- ]] && LOG="$LOGMAP/$SLUG.log"  # slug mét datum: niet dubbel
LOPEND_BESTAND="$LOPEND/$(basename "$OPDRACHT")"
mv "$OPDRACHT" "$LOPEND_BESTAND"
echo ">> cc_inbox: start $SLUG ($(date +%FT%T)) — log $LOG" | tee -a "$LOG" >&2

for tool in claude git; do
  command -v "$tool" >/dev/null || { echo "FOUT: $tool niet gevonden op PATH=$PATH" | tee -a "$LOG" >&2; melding "CC MISLUKT: $SLUG" "$tool niet gevonden op PATH"; exit 1; }
done

PROMPT="$(cat "$LOPEND_BESTAND")
---
Werkloop automatisch (CLAUDE.md § Werkwijze \"Werkloop automatisch (14-09)\"): deze opdracht komt uit opdrachten/inbox/ en staat nu als opdrachten/lopend/$(basename "$OPDRACHT"). Sluit af met (1) het eindrapport als docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md + regel bovenaan in docs/rapporten/INDEX.md (incl. \"werkt in productie: ja/nee/niet gemeten\"), (2) dit opdrachtbestand naar opdrachten/gedaan/ mét bovenin de kopregel \"uitgevoerd <datum>, rapport: docs/rapporten/<bestand>\", (3) committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat). Peter kijkt niet mee: vragen stellen kan niet, kies zelf en leg keuzes vast in het rapport."

RAPPORTEN_VOOR="$(ls -1 "$REPO/docs/rapporten"/*.md 2>/dev/null | sort || true)"
cd "$REPO"
rc=0
claude -p "$PROMPT" --permission-mode "${CC_INBOX_PERMISSION_MODE:-acceptEdits}" </dev/null 2>&1 | tee -a "$LOG"
rc="${PIPESTATUS[0]:-1}"
echo ">> cc_inbox: claude eindigde met code $rc ($(date +%FT%T))" | tee -a "$LOG" >&2

LAATSTE="$(grep -v '^>> cc_inbox' "$LOG" | grep -v '^[[:space:]]*$' | tail -1 | cut -c1-160)"
RAPPORT="$(comm -13 <(printf '%s\n' "$RAPPORTEN_VOOR") <(ls -1 "$REPO/docs/rapporten"/*.md 2>/dev/null | sort) | grep -v INDEX.md | tail -1 || true)"
[[ -n "$RAPPORT" ]] && RAPPORT="docs/rapporten/$(basename "$RAPPORT")" || RAPPORT="geen"

if [[ $rc -eq 0 ]]; then
  if [[ -f "$LOPEND_BESTAND" ]]; then  # CC verplaatste zelf niet (bv. Bash geweigerd in acceptEdits) → het script doet het
    { echo "uitgevoerd $DATUM, rapport: $RAPPORT"; echo; cat "$LOPEND_BESTAND"; } > "$GEDAAN/$(basename "$OPDRACHT")"
    rm -f "$LOPEND_BESTAND"
    echo ">> cc_inbox: $SLUG → opdrachten/gedaan/ (kopregel door het script, rapport: $RAPPORT)" | tee -a "$LOG" >&2
  fi
  melding "CC klaar: $SLUG" "${LAATSTE:-klaar (geen uitvoer)}"
else
  melding "CC MISLUKT: $SLUG (code $rc)" "${LAATSTE:-zie $LOG}"
fi
exit "$rc"
