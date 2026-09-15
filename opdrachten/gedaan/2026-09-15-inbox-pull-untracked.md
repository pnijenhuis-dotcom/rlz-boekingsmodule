uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-inbox-pull-untracked.md

NAZORG INBOX (Cowork 15-09, klein) — pull wordt overgeslagen door untracked bestanden

Vanochtend 08:30: werkboom "vuil" door alleen `?? .claude/` en `?? opdrachten/gedaan/2026-09-14-dummy-inbox-herstel.md` → geen `git pull --ff-only` → de nameting-bot-commit van 07:30 staat niet lokaal en Cowork kan het rapport niet lezen.
1. scripts/cc_inbox.sh: "schoon" = geen gewijzigde/gestagede TRACKED bestanden (`git status --porcelain --untracked-files=no` leeg); untracked blokkeren een ff-only pull niet. Guard-test aanpassen/uitbreiden (tests/unit/test_cc_inbox_pull.py).
2. `opdrachten/gedaan/2026-09-14-dummy-inbox-herstel.md` committen (hoorde bij de herstel-run). `.claude/` in de repo-root: is dat een verdwaalde map (settings staan in `.claude/settings.local.json` die al bestond)? Alleen als het nieuw én leeg/junk is: in .gitignore; niets verwijderen zonder dat in het rapport te benoemen.
3. Daarna direct een pull draaien zodat `verkenning/nameting-*-15-09.txt` lokaal staat; rapport docs/rapporten/2026-09-15-inbox-pull-untracked.md + INDEX; dit bestand naar gedaan/. Geen migratie.
