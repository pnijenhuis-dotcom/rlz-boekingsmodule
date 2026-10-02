# Nameting run D 02-10 (blokken A, B, C, D, F) — ná deploy

niet vóór: 2026-10-03 12:00
Domeinen: btw, autoboeken-ai, reconciliatie, verplichtingen-projecten-voorraad, werkvoorraad-controlescherm, doorbelasting-intercompany, accordering-native-app, werkloop-productie

Hoogstens drie pogingen (regel 22-09 (3)); te vroeg = terugleggen mét `niet vóór:` +1 dag. Niets schrijvends in productie.

## Stap 0
Deploy-check: service ÉN jobs op een image ≥ commit `1500c1f` (blok G; bouwblokken 4ab3506 … bdbb3b7); `main..origin/main` toetsen en zo nodig `merge --no-ff`.

## Meetlatten (lees-only)
1. **Blok A** — `gh workflow run nameting -f onderdeel=btw-afronding` → bot-bestand `verkenning/nameting-btw-afronding-<dd-mm>.txt`: `db-lezen btw-afronding --administratie "Kempen Facilities" --param dagen=14` (ook BLOW, Universal Steigerbouw) — verwacht ≥ 1 rij `check_groen_met_verschil` voor Lusso 260987 (netto 4.349,18, btw_factuur 913,27, btw_tarief 913,33) zodra het document geboekt is; ná de échte reconciliatierun ≥ 1 `acceptatie_btw_afronding` óf `rlz_lager_dan_factuur`; job-log `rlz-reconciliatie` "btw-afronding RLZ"; request-log `POST …/boeken` 5xx = rood; 0 rijen én 0 × 5xx = "niet gemeten (geen casus)" (geen fout, benoemen).
2. **Blok B** — `gh workflow run nameting -f onderdeel=project-match` → `db-lezen project-prefill-herkomst --administratie "Universal Steigerbouw"` ongefilterd + `--param project_bron=factuur_plaats_opdrachtgever` + `--param project_bron=factuur_meerduidig` (kolom `project_kandidaten`); klikpunt Peter: Hoogwerkservice-factuur openen → alle regels 25170 oranje "op plaats + opdrachtgever"; Huvanco boeken → de volgende zes groen "uit factuur". Vóór die klik 0 rijen = geen fout.
3. **Blok C** — request-log `POST …/administraties/<adm>/documenten/<id>/afwijzen` 201 ná de deploy + `scripts/gcp/db_lezen.sh --sql "SELECT d.soort, count(*) FROM boekhouding.afwijzing a JOIN boekhouding.document d ON d.id = a.document_id WHERE a.afgewezen_op >= '<deploy-tijdstip>' GROUP BY d.soort"` (één proxy tegelijk; per administratie-scope indien RLS dat eist) — rijen mét verkoopfactuur/kassarapport = de knop is gebruikt; 0 = nog niet gebruikt, geen fout.
4. **Blok D** — `gh workflow run nameting -f onderdeel=ic-aansluiting` → `reconciliatie-alles --alleen intercompany --lees-only` (12 richtingen voor de vier Universal-BV's, slotregel `N/M richting(en) getoetst (K zonder records)`, Nederland → Steigerbouw méér "onderweg in de module", Verkoop → Steigerbouw: F/2026/00066 géén `ic_verkoop_ontbreekt`) + `ic-aansluiting-rapport --administratie "Universal Steigerbouw"`; sync-log `rlz-sync` 07:00: "auto-bevestigd … : N" + "ic-tegenpartijen: kandidaten=… nieuw=…"; ná de échte run 04:30 van 04-10: `db-lezen ic-aansluiting --administratie <Steigerbouw>`, audit `reconciliatie_auto_gesloten` voor de oude `ic_ontbreekt_bij_*`, stand `ic_inkoop_ontbreekt` (explosie-rem verwacht) via `bevindingssoort-stand`; request-log `POST /reconciliatie/intercompany/*/factuur-opvragen`.
5. **Blok F** — klikpunt Peter (`opdrachten/terminal/2026-10-03-android-vc7-upload.md`): Play Console `1.3 (7)` live; lees-only: request-log `POST /auth/app/activeren` mét `X-App-Versie: 1.3` vanaf Android-user-agents; OTA-bundel voor runtime 1.3 ná de eerste deploy (`app-bundel-registreren`, Beheerder-blok App-updates). Vóór de upload = "niet gemeten (wacht op winkelrelease)".

## Af
Rapport `docs/rapporten/2026-10-03-nameting-run-d.md` + INDEX + "Gelezen regels" + per blok "werkt in productie: ja/nee/niet gemeten"; BESLISSINGEN-sectie "RUN D 02-10 — BTW < € 0,10, PROJECTMATCH, AFWIJZEN, IC 12 RICHTINGEN, PO STAP-0, NATIVE 1.3 (Peter 02-10)" alinea "Gemeten 03-10" per blok. Niets schrijvends in productie.
