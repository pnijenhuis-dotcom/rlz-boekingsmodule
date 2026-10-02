# Terminal 29-09 — Vastly-verkoop heraanbieden (23 open UBL's + 9 Van Rooijen) ná deploy van a920b1c

Volgorde: stap 0 → stap 1 → Cowork leest de telling → Peter "ja" → stap 2. Claude Code voert uit mét toestemming per commando.

## Stap 0 — deploy live? (lees-only)
```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Verwacht: image eindigt op `a920b1c` of `8e58df9` (of nieuwer). Anders wachten.

## Stap 1 — dry-run (lees-only)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args=-m,app.cli,vastly-verkoop-heraanbieden
```
Verwacht: 32 kandidaten — 23 te boeken (Rubicon 8, Meyer 4, Elissen 4, ARVUM 3, Shuto 3, Inpensas 1) + 9 "verhuurder niet gekoppeld"
(Van Rooijen) — plus per administratie of de omzetrekening/btw afleidbaar is. Uitvoer aan Cowork.

## Stap 2 — uitvoeren (schrijvend: boekt in RLZ) — pas ná Peters "ja"
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args=-m,app.cli,vastly-verkoop-heraanbieden,--uitvoeren
```
Daarna in de module (Reconciliatie, blok Vastly-verkoop): bevinding "Vastly-verhuurder niet gekoppeld: B. van Rooijen" → "Koppel aan
administratie…" → B. van Rooijen / G. Schaalje → de 9 boeken direct.
