uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-inbox-wacht-handmatig.md

NAZORG INBOX (Cowork 15-09, klein) — geen twee Claude Code-runs tegelijk in dezelfde werkboom

Vanochtend liepen een handmatige CC-sessie (administratienaam) en de launchd-inbox-run parallel in dezelfde werkboom → pytest-setup-errors en het risico op vervlochten commits.
1. scripts/cc_inbox.sh: vóór het starten van een opdracht controleren of er al een `claude`-proces draait met cwd in deze repo (pgrep + lsof/`proc_pidpath`, macOS-veilig); zo ja: niets starten, logregel "wacht — handmatige CC actief", volgende tick opnieuw. Ook de pull overslaan zolang dat proces leeft.
2. Guard-test in tests/unit/test_cc_inbox_herstel.py (gesimuleerd proces via env-override/seam, geen echte claude).
3. Rapport docs/rapporten/2026-09-15-inbox-wacht-handmatig.md + INDEX; dit bestand naar gedaan/. Geen migratie.
