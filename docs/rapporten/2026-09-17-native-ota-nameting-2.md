# Rapport 17-09 (middag, inbox-run) — Native app OTA: productienameting ná de bucket — stap 0 NIET voldaan (geen deploy sinds de bucket), gemeten wat lees-only kon

Opdracht: `opdrachten/gedaan/2026-09-17-native-ota-nameting-2.md`. Lees-only, geen writes.
**Werkt in productie: OTA-bundel niet gemeten (stap 0 niet voldaan); 426-poort ja (rapport 17-09 ochtend).**

## Stap 0 — voorwaarden (stoppen mét melding)

| Voorwaarde | Uitkomst (bron) |
|---|---|
| Laatste deploy groen t/m stap 10 | **Nee.** `gh run list --workflow=deploy.yml --limit 2`: 35189339460 `fb54c58` failure (06:19:42Z) en 35188489798 `ea859d6` failure (06:07:35Z) — beide rood op stap 10 `gs://rlz-boekhouding-app-bundels not found: 404`. Er is ná het aanmaken van de bucket (07:48:59Z, Peter) **geen deploy meer gelopen** — deze run pusht pas bij het einde. |
| Bucket | Bestaat (europe-west4, uniform, versioning aan); IAM deploy@/run-jobs@ objectViewer, deploy@ objectCreator; **service-SA `run-backend@` ontbreekt** → klikpunt in `2026-09-17-apple-1-1-live-xcode-cloud.md`. |
| Manifest (lees-only, `curl`) | `runtime=1.1&platform=ios` → `{"geen_update":true,"reden":"geen bundel voor deze runtime"}`; idem `runtime=1.2` — verwacht: de OTA-stap heeft nog nooit een bundel geregistreerd. |
| `gh auth status` | groen |

Conform de opdracht ("nog rood op stap 10 → melden en stoppen") is het workflow-onderdeel `app-bundels` niet gedraaid.

## Wat de eerstvolgende deploy doet
De push van deze run (o.a. `601fd54` marketingversie 1.2, `1eccc8b` bucket-script) start de deploy; stap 10 registreert de bundel onder
**runtime 1.2** (`APP_MARKETING_VERSIE` = 1.2 sinds vanochtend). De live 1.1-schil krijgt dus géén OTA-bundel (train-regel: OTA volgt de
gebouwde schil — beslispunt 3 van opdracht 1); een 1.2-schil (Xcode Cloud-build ≥ 145) wél.

## Klikpunten Peter
1. IAM-binding `roles/storage.objectViewer` voor `run-backend@rlz-boekhouding.iam.gserviceaccount.com` op `gs://rlz-boekhouding-app-bundels`
   (bron: `get-iam-policy` 17-09; commando in `2026-09-17-apple-1-1-live-xcode-cloud.md`) — zonder binding kan de service de zip niet serveren.

## Vervolg
`opdrachten/inbox/2026-09-17-native-ota-nameting-3.md`: ná de deploy van deze run `gh workflow run nameting -f onderdeel=app-bundels`
→ manifest `runtime=1.2&platform=ios` mét bundel_id + bundellijst actief; toestel pas met een 1.2-schil.
