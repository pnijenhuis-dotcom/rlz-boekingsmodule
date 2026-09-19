uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-projectnummer-uit-afgesloten-naam.md (sectie "Nameting ná deploy")

Domeinen: verplichtingen-projecten-voorraad, reconciliatie, werkloop-productie

# OPDRACHT 19-09 — Nameting ná deploy: projectnummer óók uit "Afgesloten NNNNN …"-namen (vervolg op
# docs/rapporten/2026-09-19-projectnummer-uit-afgesloten-naam.md)

**Voorwaarde (stap 0):** de commit "projectnummer uit Afgesloten-naam" (nummer.py `zonder_afgesloten_voorvoegsel`, client
`find_projects_by_name_prefixes`, nameting.yml-onderdeel uitgebreid) is gedeployd op service ÉN jobs (`gh run view` van deploy.yml
groen; `gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'` = dezelfde image als de
service). Een LOPENDE deploy op de juiste sha = wachten (`gh run watch`); rood/afwezig = terug in de inbox mét gewiste `.pogingen`.
Nooit een lokaal proces tegen productie.

## Meetrecept (lees-only)
1. `gh workflow run nameting.yml -f onderdeel=projecten-afgesloten` → `git fetch` → `git show origin/main:verkenning/nameting-projecten-afgesloten-<datum>.txt`.
   Het onderdeel draait sinds 19-09 óók `reconciliatie-alles --alleen projecten --lees-only` en
   `projecten-dubbele-nummers --administratie "Universal Steigerbouw"`.
2. Verwacht in het reconciliatie-deel bij Universal Steigerbouw: **4 × `project_nummer_dubbel`** — 26053, **26064** (nieuw: "26064 Harskamp
   (vd Brandhof)" + "Afgesloten 26064 Apeldoorn (Ben Kuijer)"), 26084, 26149 (op 19-09 vóór deploy: 3, zonder 26064). LET-OP's
   `project_naam_afgesloten_status_actief` blijven 8 (of minder als Peter/Haci al hebben afgesloten).
3. Verwacht in `projecten-dubbele-nummers`: nummer 26064 mét beide project-id's (RLZ `4dfd2322…` Harskamp en `36d04825…` Apeldoorn),
   tellers facturen/weekstaten/planning per kant en "voorstel: blijft" bij de kant met de meeste activiteit (beide hadden op 19-09 geen
   activiteit in de module → voorstel valt op de eerste; benoem dat expliciet — geen voorkeur, mens beslist).
4. Optioneel 409-proef (alleen als Peter het wil, schrijft NIETS bij succes): nieuw project "26064 TEST (Nijenhuis)" via de UI → verwacht 409
   "26064 bestaat al: 26064 Harskamp (vd Brandhof), lopend — openen?" (de cache-treffer gaat vóór de RLZ-treffer). Niet vanuit de run.
5. Rapport: sectie "Nameting ná deploy" in `docs/rapporten/2026-09-19-projectnummer-uit-afgesloten-naam.md` + INDEX-regel bijwerken
   ("werkt in productie: ja/nee"), BESLISSINGEN rij B4 van "niet gemeten" naar "gemeten <datum>", regels-alinea aanvullen.

**Klikpunt Peter (uit het rapport, niet voor de run):** Harskamp (vd Brandhof) komt drie keer voor (26064 + 2 × 26084) — samenvoegen is
mens-werk, de verliezers ná verhuizing op afgesloten (IsActive uit), nooit verwijderen.
