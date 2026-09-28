# Nameting planning v4 ná deploy — werkt in productie: ja/nee (paneel, kopie naar volgende week, quick-add)

niet vóór: 2026-09-29 09:00
Domeinen: uren-planning-veldwerkers, werkloop-productie

Bron: rapport `docs/rapporten/2026-09-28-planning-v4.md` ("werkt in productie: niet gemeten"), BESLISSINGEN "PLANNING V4 — POOL WEG,
PROJECT × DAG-MATRIX, PLOEG-PANEEL ALS DÉ WERKWIJZE, QUICK-ADD, KOPIE NAAR VOLGENDE WEEK (Peter 28-09)", gespreksverslag 28-09.
Regel 21-09: "niet gemeten" is een schuld mét vervaldatum.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij divergentie, nooit rebase); service ÉN jobs op de planning-v4-commit van 28-09
of later (`gcloud run services describe rlz-backend` + `gcloud run jobs describe … spec.template.spec.template.spec.containers[0].image`).
Niet live = opdracht terugleggen mét `niet vóór:` +1 dag (hoogstens drie pogingen).

## Stap 1 — dispatch-onderdeel (lees-only, bot-bestand op main)
`gh workflow run nameting -f onderdeel=planning-v4` → `verkenning/nameting-planning-v4-<dd-mm>.txt`: request-log POST
/uren/kantoor/planning/* (200/5xx, latency) + POST /auth/uitnodigingen, en `db-lezen planning-v4 --administratie "Universal Steigerbouw"
--param dagen=14` (audit `planning_bulk`/`planning_gepland` mét bron `kopie_volgende_week`|`ploeg`, `veldwerker_aangemaakt` bron
`planning_paneel`). Oordeelregel: JA zodra er ≥ 1 kopie of quick-add in de audit staat; DEELS als alleen het paneel (bron `ploeg`) gebruikt is;
NIET GEMETEN (ongebruikt) = klikpunt.

## Stap 2 — klikpunt Peter/Haci (uitkomst in het rapport)
Week 40 plannen via het paneel (kaart of lege cel → vinkjes → Opslaan), één kaart "Kopiëren naar ‹weekdag› volgende week" (toast mét
"Naar week 41"), één keer "+ Veldwerker toevoegen…" uit het paneel (chip "dossier onvolledig" zichtbaar). Ongebruikt ná de tweede poging =
`niet vóór:` +1 dag, hoogstens drie pogingen, daarna `mislukt/` mét het klikpunt.

## Definitie van af
Rapport `docs/rapporten/<datum>-nameting-planning-v4-na-deploy.md` + INDEX + "Gelezen regels", BESLISSINGEN-alinea "Gemeten <datum>" in
de v4-sectie, regels-alinea als het oordeel iets verandert, gespreksverslag, opdracht → gedaan/. Poort: guards (`test_rapporten_*`,
`test_nameting_workflow`) groen.
