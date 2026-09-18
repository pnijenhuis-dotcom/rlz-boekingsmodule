# Rapport 18-09 — Nameting veld-app uitvoerder feedback 18-09: stap 0 (deploy-check) → NIET LIVE, opdracht terug in de inbox

Opdracht: `opdrachten/inbox/2026-09-18-veldapp-uitvoerder-nameting.md` (poging 1, 18-09 ochtend). Domeinen:
uren-planning-veldwerkers, werkloop-productie. Lees-only; geen schrijfhandeling uitgevoerd (de test-weekstaat is NIET aangemaakt).

**Werkt in productie: NIET GEMETEN** — stap 0 van het meetrecept stopt de run: de code van de feedback-run (migratie 0158,
"Mijn uren"-tab, doorfactureren-dropdown, kantoor-weekstaatpaneel) stond op het moment van deze run nog **ongecommit in de
werkboom** (de vorige run eindigde zonder commit; het rapport droeg nog de placeholder `<<BACKEND_SUITE>>`). Zonder commit +
push is er geen deploy-run, dus niets te meten.

## Stap 0 — deploy-check (service ÉN jobs), lees-only

| Toets | Uitkomst |
|---|---|
| Laatste deploy-run (`gh run list --workflow deploy.yml --limit 1`) | run 35250353272 op `47cf967` (17-09 17:03Z), `success` — dat is de commit VÓÓR de feedback-run; migratie 0158 zit er niet in |
| `origin/main` | `47cf967` — `backend/migrations/versions/0158_weekstaat_dag_doorfactureren.py` staat niet in git (`git ls-files` = 0 regels) |
| Service-image `rlz-backend` | `…/rlz/backend:47cf9677297b85d7690283f577f85043ecc019d7` |
| Job-image `rlz-migratie` | idem `47cf967…` |
| Job-image `rlz-reconciliatie` | idem `47cf967…` — service en jobs lopen gelijk, maar op de OUDE code |

Conclusie stap 0: **niet live → stoppen, melden, opdracht terug in de inbox** (letterlijk de stop-regel uit de opdracht).

## Wat deze run wél deed

1. De ongecommitte feedback-run (0158 + app + docs) is in deze inbox-run alsnog **gecommit** (zie `2026-09-18-inbox-afgewerkt.md`);
   de Stop-hook pusht ná de run → deploy-run volgt automatisch. De backend-suite is alsnog volledig gedraaid en in het
   feedback-rapport ingevuld.
2. De nameting-opdracht staat terug in `opdrachten/inbox/` mét een toegevoegde stap-0-aanwijzing: wacht tot de deploy-run op de
   commit mét 0158 groen is (`gh run watch`), pas dan meten — anders draait de cc-inbox 'm direct ná de push opnieuw tegen het
   oude beeld.

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (300 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/werkloop-productie.md` (55 regels) — volledig, vóór de start (Domeinen-kopregel).
