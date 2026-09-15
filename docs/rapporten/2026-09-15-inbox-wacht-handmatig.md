# 2026-09-15 — Nazorg inbox: geen twee Claude Code-runs tegelijk in dezelfde werkboom

**In gewone taal:** het inbox-script kijkt nu eerst of er al een Claude Code-sessie in deze map bezig is. Is dat zo, dan doet het
niets en probeert het over vijf minuten opnieuw. Zo lopen een handmatige sessie en een automatische run nooit meer door elkaar.

**Werkt in productie: niet van toepassing** (lokaal script op de Mac, geen Cloud Run-onderdeel). Lokaal bewezen: tijdens deze run
draaide écht een tweede claude-sessie in deze werkboom (pid 23215); de fail-closed-test zag die als eerste proces en wachtte.

## Aanleiding
15-09 ochtend liepen een handmatige CC-sessie (administratienaam, migratie 0144) en de launchd-inbox-run parallel in dezelfde
werkboom: pytest-setup-errors op de gedeelde `boekhouding_test` en het risico op vervlochten commits (de Stop-hook van de één
pusht de commits van de ander). De lock `opdrachten/.lock` beschermt alleen tegen een tweede INBOX-run, niet tegen een
interactieve sessie.

## Gebouwd
1. **`scripts/cc_inbox.sh` — poort "handmatige CC actief".** Ná de lock-check en vóór het herstel van verweesde opdrachten, de
   pull en het oppakken: `pgrep -x claude` → per pid de cwd via `lsof -a -p <pid> -d cwd -Fn` (lsof op PATH, terugval
   `/usr/sbin/lsof`; macOS heeft geen /proc). Cwd = repo-root of een submap → logregel
   `>> cc_inbox: wacht — handmatige CC actief (pid N, cwd …) — geen herstel, geen pull, geen start; volgende tick opnieuw`, exit 0.
   Een claude in een andere map (ander project) telt niet. Cwd niet leesbaar (lsof ontbreekt of faalt) telt WÉL als actief:
   fail-closed, mét de reden in de logregel. Seam `CC_INBOX_CLAUDE_NAAM` (procesnaam, default `claude`).
2. **Guard-tests** (`backend/tests/unit/test_cc_inbox_herstel.py`, 9 → 13, plus de documentatie-guard eist `handmatige_cc` en de
   wacht-regel in het script). Gesimuleerd proces = symlink naar `/bin/sleep` onder de naam `claude`, gestart mét cwd in de
   wegwerp-repo — `pgrep -x` ziet de procesnaam, `lsof` de cwd; nooit een echte claude. Casussen: submap-cwd → wacht, opdracht
   blijft in inbox/, verweesde lopend-opdracht blijft staan, geen lock/log/melding/pull-poging, tweede tick wacht opnieuw, ná het
   einde van het proces gewoon door; claude in een andere map houdt niet op; lsof faalt → fail-closed; seam-naam zonder match →
   gewoon oppakken. Suite cc_inbox (herstel + pull) 22 groen, ruff schoon.

## Keuzes (Peter keek niet mee)
- **Check vóór herstel (e), niet alleen vóór start/pull.** De handmatige sessie kan zelf aan de lopend-opdracht werken (zoals deze
  run nu); terugzetten naar inbox/ zou die onder haar handen weghalen.
- **Fail-closed bij onleesbare cwd.** Liever één tick te laat dan twee runs door elkaar; de logregel zegt waarom. Op deze Mac is
  `/usr/sbin/lsof` altijd aanwezig, dus het pad is een vangnet.
- **Logregel elke tick** (≤ 5 min) in het launchd-log zolang de sessie leeft — zichtbaar, niet stil; geen macOS-melding (dat zou
  bij een lange handmatige sessie elke vijf minuten een melding geven).
- **Eigen proces uitgesloten** (`$$`) — niet nodig omdat het script geen `claude` heet, maar kost niets.
- Het pid-in-lock-recept uit het geheugen van 15-09 (interactieve sessie zet de lock zelf) is hiermee overbodig; geheugen bijgewerkt.

## Niet gedaan
Geen migratie, geen backend-code. Geen wijziging aan de launchd-plist (tick-cadans blijft 300 s / WatchPaths).

## Vastgelegd
BESLISSINGEN "WERKLOOP AUTOMATISCH …" herstel-tabel rij (f); CLAUDE.md § Werkwijze "Werkloop automatisch (14-09)" één zin;
kopcommentaar `scripts/cc_inbox.sh`.
