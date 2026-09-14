#!/usr/bin/env bash
# Werkloop automatisch 14-09 — launchd-agent die scripts/cc_inbox.sh start zodra er iets in opdrachten/inbox/ verschijnt
# (WatchPaths) én elke 5 minuten als vangnet (StartInterval 300). Aan/uit-knop:
#   scripts/cc_inbox_install.sh              → (her)installeren, idempotent (plist herschreven + herladen)
#   scripts/cc_inbox_install.sh --uninstall  → agent uitladen + plist weg (de inbox blijft, er start niets meer)
# launchd kent geen zsh-profiel: PATH staat expliciet in de plist; dit script verifieert dat claude, git en gcloud
# op dat PATH gevonden worden en meldt de gevonden paden.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="nl.aknijenhuis.cc-inbox"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGBESTAND="$HOME/Library/Logs/cc-inbox.log"
CC_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
DOMEIN="gui/$(id -u)"

uitladen() { launchctl bootout "$DOMEIN/$LABEL" 2>/dev/null || true; }

if [[ "${1:-}" == "--uninstall" ]]; then
  uitladen
  rm -f "$PLIST"
  echo ">> $LABEL uitgeladen en $PLIST verwijderd — de inbox wordt niet meer opgepikt (aanzetten: $0)"
  exit 0
fi

echo ">> toolcheck op het launchd-PATH ($CC_PATH):"
ontbreekt=0
for tool in claude git gcloud osascript; do
  pad="$(PATH="$CC_PATH" command -v "$tool" || true)"
  if [[ -n "$pad" ]]; then echo "   ✓ $tool → $pad"; else echo "   ✗ $tool NIET gevonden"; ontbreekt=1; fi
done
[[ $ontbreekt -eq 0 ]] || { echo "FOUT: pas CC_PATH in dit script aan" >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/opdrachten/inbox"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!-- Werkloop automatisch 14-09 (RLZ-boekingsmodule): start scripts/cc_inbox.sh bij een nieuw bestand in opdrachten/inbox/
     (WatchPaths) en elke 300 s als vangnet. Beheer: scripts/cc_inbox_install.sh [--uninstall]. -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/cc_inbox.sh</string>
  </array>
  <key>WatchPaths</key>
  <array>
    <string>$REPO/opdrachten/inbox</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOGBESTAND</string>
  <key>StandardErrorPath</key><string>$LOGBESTAND</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$CC_PATH</string>
    <key>HOME</key><string>$HOME</string>
    <key>LANG</key><string>nl_NL.UTF-8</string>
  </dict>
</dict>
</plist>
PLIST
plutil -lint "$PLIST" >/dev/null
uitladen
launchctl bootstrap "$DOMEIN" "$PLIST"
launchctl enable "$DOMEIN/$LABEL" 2>/dev/null || true
echo ">> $LABEL geladen: $(launchctl print "$DOMEIN/$LABEL" 2>/dev/null | grep -E 'state =|path =' | head -2 | tr -s ' ' | tr '\n' ';')"
echo ">> plist: $PLIST — log: $LOGBESTAND — inbox: $REPO/opdrachten/inbox"
