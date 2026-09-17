uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-apple-1-2-xcode-cloud-nameting.md

# OPDRACHT 17-09 — Nameting ná de SPOED-run Apple 1.1/1.2: Xcode Cloud-build 1.2 groen, deploy groen incl. stap 10, manifest 1.2, uitnodigingsmail App Store-link (lees-only)

Vervolg op `docs/rapporten/2026-09-17-apple-1-1-live-xcode-cloud.md`. Geen writes.

## Stap 0 — voorwaarden
- Deploy van de commits van de SPOED-run 17-09 groen (`gh run list --workflow=deploy.yml --limit 1`), stap 10 "OTA-webbundel …" groen mét
  log "OTA-bundel <id> (runtime 1.2 …) geregistreerd". Rood op stap 10 → oorzaak letterlijk in het rapport (bucket-IAM? zie klikpunt 1).
- Klikpunt 1 (objectViewer voor `run-backend@` op `gs://rlz-boekhouding-app-bundels`) door Peter gedaan? Lees-only toetsbaar via
  `GET /app/bundels/<id>.zip` (200 = binding staat; 500/403 in de service-log = niet).

## Stap 1 — meting
- `gh workflow run nameting -f onderdeel=app-bundels` → bot-bestand `verkenning/nameting-app-bundels-<dd-mm>.txt`: manifest runtime 1.2 ios/android mét bundel_id, 426-probe.
- Xcode Cloud: build ≥ 145 op `main` = versie 1.2 groen (mail "processing completed"); rood → letterlijke fouttekst + fix-voorstel.
- Uitnodigingsmail: Peter stuurt een verse uitnodiging naar een testaccount (app-rol) → mail toont "iPhone / iPad — App Store" i.p.v. TestFlight.

## Stap 2 — oordeel + afronding
BESLISSINGEN "APPLE 1.1 GOEDGEKEURD 17-09 — …": alinea "Nameting" + "werkt in productie: ja/nee"; rapport + INDEX; opdracht → gedaan.
