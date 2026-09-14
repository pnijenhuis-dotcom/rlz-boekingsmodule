uitgevoerd 2026-09-14, rapport: docs/rapporten/2026-09-14-werkloop-nazorg.md

OPDRACHT — WERKLOOP NAZORG: LOKALE PULL + COMMITBERICHT PER ONDERDEEL (Cowork, 14-09; eerste echte workflow-run f4c702c was groen)

1. scripts/cc_inbox.sh: vóór het oppakken van een opdracht én bij elke launchd-tick zonder werk (StartInterval) een `git pull --ff-only origin main` in de repo-root, alleen als er geen lock is en de werkboom schoon is (`git status --porcelain` leeg); anders overslaan met logregel. Doel: bot-commits van de nameting-workflow landen automatisch op deze Mac zodat Cowork ze kan lezen. Nooit rebase/merge, nooit stash.
2. .github/workflows/nameting.yml: het commitbericht neemt de oordeelregel uit het rapport van het GEDRAAIDE onderdeel (reconciliatie → nameting-reconciliatie-<dd-mm>.txt, anders replay), niet altijd uit de replay. Run f4c702c droeg "Oordeel: GROEN ZONDER DOEL …" bij een reconciliatie-meting — misleidend. Geen oordeelregel gevonden = "geen oordeelregel".
3. Guard test_nameting_workflow.py uitbreiden op punt 2; test voor punt 1 (pull wordt overgeslagen bij vuile werkboom) als shell-test of via een klein Python-wrapper.
4. Rapport docs/rapporten/2026-09-14-werkloop-nazorg.md + INDEX, dit bestand naar gedaan/. Ook vastleggen: workflow-run 34845170512 groen, commit f4c702c door nameting-bot → "Werkloop automatisch: werkt in productie: ja". Geen migratie.
