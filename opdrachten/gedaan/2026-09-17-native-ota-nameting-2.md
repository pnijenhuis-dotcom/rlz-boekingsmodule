> uitgevoerd 2026-09-17 (stap 0 niet voldaan: geen deploy sinds de bucket; manifest lees-only vastgelegd; vervolg native-ota-nameting-3 ná de deploy van deze run; werkt in productie: niet gemeten), rapport: docs/rapporten/2026-09-17-native-ota-nameting-2.md

# OPDRACHT 17-09 — Native app OTA: productienameting via de nameting-workflow ná de bucket (lees-only; géén writes)

Vervolg op `opdrachten/gedaan/2026-09-17-native-ota-nameting.md` (rapport `docs/rapporten/2026-09-17-native-ota-nameting.md`): de
bucket `gs://rlz-boekhouding-app-bundels` ontbrak → geen bundel te meten; de 426-poort werkt al in productie. De meting staat nu als
dispatch-onderdeel `app-bundels` in `.github/workflows/nameting.yml` (WIF als `nameting@`, geen lokale gcloud nodig).

## Stap 0 — voorwaarden (stoppen mét melding als één ontbreekt)
- Peter heeft `scripts/gcp/app_bundels_bucket.sh --apply` gedraaid: de laatste deploy (`gh run list --workflow=deploy.yml --limit 1`) is
  GROEN t/m stap 10 "OTA-webbundel …" en de log toont "OTA-bundel <id> (runtime 1.1, …) geregistreerd". Nog rood op stap 10 mét
  `gs://… not found: 404` → bucket nog niet aangemaakt → melden en stoppen.
- `gh auth status` groen; werkboom schoon (voor de pull van het bot-bestand).

## Stap 1 — meting (lees-only)
- `gh workflow run nameting -f onderdeel=app-bundels` → `gh run watch <id>` (≤ 10 min). De nameting-bot commit
  `verkenning/nameting-app-bundels-<dd-mm>.txt` → `git pull --ff-only origin main` en lees: manifest ios/android mét `bundel_id` van de laatste
  deploy (id = `<sha7>-<jjjjmmdd-hhmm>`), 426-probe HTTP 426, bundellijst mét die bundel `actief`, `Oordeel: OTA-bundel … geserveerd`.
- Direct ook: `curl "https://app.administratiekantoornijenhuis.nl/app/update-manifest?runtime=1.1&platform=ios"` = zelfde bundel_id.
- Toestel (alleen als een schil mét de updater-plugin beschikbaar is — Xcode Cloud-build ná `5ba1e9a` / Android vc5): Toegang › Diagnose →
  `bundel <sha7>` ná één herstart; Instellingen › Boeken › App-updates toont bundel + toestel. Niet beschikbaar → "toestel: niet gemeten" mét reden.
- Noodrem: NIET zelf aanzetten in productie (dat is een Beheerder-handeling van Peter); rapporteer de stand uit de bundellijst
  (`kill-switch: env=uit`).

## Stap 2 — oordeel
- "werkt in productie: ja" = manifest geeft de bundel van de laatste deploy én (als meetbaar) een plugin-schil toont 'm ná één herstart.
  Anders "deels" (manifest ja, toestel niet gemeten) of "nee" mét reden.

## Afronding
- BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA) …": alinea "Nameting 17-09" aanvullen + rij klikpunten → uitkomst; rapport + INDEX; opdracht → gedaan.

## Aanvulling Cowork 17-09 ochtend — bucket-script door Peter gedraaid
- `app_bundels_bucket.sh` toonde `service-sa=?`: `gcloud run services describe rlz-backend … serviceAccountName` gaf niets terug
  (Peter-sessie), dus de IAM-binding voor de service-SA is NIET gezet → de backend kan de bundel-zip niet lezen. Stap 0 van deze
  nameting: service-SA achterhalen (of default compute-SA benoemen) en de ontbrekende `objectViewer`-binding als één owner-commando in
  het rapport zetten (Peter draait 'm); script robuust maken (fallback op de default-SA + duidelijke melding i.p.v. `?`).
- Bucket-create vroeg gcloud-reauth; Peter heeft mogelijk alleen de create gedaan → script idempotent laten controleren (bestaat →
  doorgaan met versioning/IAM) en dat in het rapport bevestigen.
