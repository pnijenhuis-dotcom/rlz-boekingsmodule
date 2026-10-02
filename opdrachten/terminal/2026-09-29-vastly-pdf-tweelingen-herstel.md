# Terminal 29-09 — Vastly-PDF-tweelingen herstellen (de PDF als beeld bij de UBL; Peter zei 25-09 "1. ja", run nooit uitgevoerd)

Waarom: de 23 Vastly-UBL's tonen "geen factuur" omdat hun PDF-tweeling nog als los inkoopdocument staat (bv. `factuur-RUB-2026-0034.pdf`
naast `factuur-RUB-2026-0034-ubl.xml`). De herstel-CLI koppelt de PDF als beeld aan het UBL-document en zet de PDF op `samengevoegd`.
Claude Code voert uit mét toestemming per commando; niets wordt verwijderd.

## Stap 1 — dry-run (lees-only)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|vastly-pdf-tweelingen-herstel|--dry-run"
```
Verwacht in het log: 23 kandidaten (Rubicon 10 / Elissen 4 / ARVUM 3 / Meyer 3 / Shuto 3), 0 twijfel. Wijkt het af: uitvoer aan Cowork.

## Stap 2 — uitvoeren (schrijvend in onze database; geboekte UBL RUB-0031 krijgt de PDF óók als RLZ-bijlage)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|vastly-pdf-tweelingen-herstel|--uitvoeren"
```
Verwacht: 23 hersteld. Daarna in de module: de UBL toont de PDF als factuurbeeld; de losse PDF-rijen zijn weg uit "Open".
