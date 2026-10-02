# Nameting run B 02-10 (punten 24, 25, 20, 26) — ná deploy

niet vóór: 2026-10-03 09:00
Domeinen: uren-planning-veldwerkers, accordering-native-app, werkloop-productie

Hoogstens drie pogingen (regel 22-09 (3)); te vroeg = terugleggen mét `niet vóór:` +1 dag.

## Stap 0
Deploy-check: service ÉN jobs op een image ≥ commit `af26ab5` (punt 26); `main..origin/main` toetsen en zo nodig `merge --no-ff`.

## Meetlatten (lees-only)
1. **Punt 20** — `gh workflow run nameting -f onderdeel=planning-v4` → `db-lezen planning-v4` toont rijen mét bron `kopie_dag` zodra het kantoor de week-41-planning kopieert (vóór die klik: 0 = geen fout; noem dat expliciet).
2. **Punten 24, 25** — klikpunt Peter: tab Personeel week 41 — vrachtwagen-icoon op een project mét transport (tooltip, klik → Transport-tab op die dag), kleur per rij, lege cel "+". Request-log `GET /uren/kantoor/planning` 200 mét `transporten` (Cloud Logging, geen payload — alleen status).
3. **Punt 26** — klikpunt Peter in de uitvoerder-app ná OTA (tab Planning, swipe, vandaag, "+ Uren" via de kaart); lees-only meetlat: request-log `GET /uren/uitvoerder/dagplanning` 200 ná de OTA-uitrol (uitvoerder-accounts), 0 × 403/500.

## Af
Rapport `docs/rapporten/2026-10-03-nameting-run-b.md` + INDEX + "Gelezen regels" + per punt "werkt in productie: ja/nee/niet gemeten"; BESLISSINGEN-sectie "RUN B 02-10 — …" alinea "Gemeten 03-10". Niets schrijvends in productie.
