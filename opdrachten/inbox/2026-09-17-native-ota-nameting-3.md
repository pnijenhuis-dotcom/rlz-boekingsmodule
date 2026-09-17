# OPDRACHT 17-09 — Native app OTA: productienameting ná de deploy van de run van 17-09 (bucket bestaat; runtime 1.2) — lees-only

Vervolg op `docs/rapporten/2026-09-17-native-ota-nameting-2.md` (stap 0 niet voldaan: geen deploy sinds de bucket).

## Stap 0
- `gh run list --workflow=deploy.yml --limit 1` GROEN incl. stap 10 "OTA-webbundel …" mét log "OTA-bundel <id> (runtime 1.2, …) geregistreerd".
  Rood op stap 10 → letterlijke fouttekst in het rapport (IAM? bucket?), stoppen.
- Klikpunt objectViewer voor `run-backend@` gedaan? (`GET /app/bundels/<id>.zip` 200 = ja.)

## Stap 1
- `gh workflow run nameting -f onderdeel=app-bundels` → `verkenning/nameting-app-bundels-<dd-mm>.txt`: manifest 1.2 ios/android mét bundel_id, 426-probe, bundellijst actief.
- `curl "https://app.administratiekantoornijenhuis.nl/app/update-manifest?runtime=1.2&platform=ios"` = zelfde bundel_id.
- Toestel alleen met een 1.2-schil (Xcode Cloud ≥ 145 / Android vc6): Toegang › Diagnose `bundel <sha7>` ná één herstart.

## Stap 2
BESLISSINGEN OTA-sectie alinea "Nameting <datum>" + "werkt in productie: ja/nee"; rapport + INDEX; opdracht → gedaan.
