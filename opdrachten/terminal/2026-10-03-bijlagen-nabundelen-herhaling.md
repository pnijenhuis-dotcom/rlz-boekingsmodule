# Terminal 03-10 — bijlagen-nabundelen herhalen: bijlage volgt het duplicaat naar het origineel (Universal Steigerbouw → kantoorbreed)

Waarom: de échte run van vanochtend (`rlz-reconciliatie-z8dj8`) liet 7 `factuurdetails-….pdf` los staan omdat de factuur in die mails als
duplicaat was afgevoerd (6×) of afgewezen (1×). Sinds de fix van 03-10 volgt de nazorg zo'n factuur naar het origineel. Schrijft alleen in
onze eigen database (status `samengevoegd` mét verwijzing; geboekt origineel → bijlage óók als extra RLZ-upload, nooit een boeking);
terugdraaibaar per bijlage (`--ongedaan <bijlage-id> --reden …`). Machine kan dit niet omdat: een schrijvende nazorg draait uitsluitend als
`gcloud run jobs execute` in de owner-sessie ná deploy (regel 08-09).

## Stap 0 — deploy live? (service ÉN jobs)
```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --project rlz-boekhouding --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Het image moet de commit van 03-10 ("bijlage volgt het duplicaat naar het origineel") of later dragen. Zo niet: 20 min wachten.

## Stap 1 — dry-run Steigerbouw (schrijft niets)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|bijlagen-nabundelen|--dry-run|--administratie|Universal Steigerbouw"
```

## Stap 2 — uitkomst lezen
```
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-reconciliatie" AND timestamp>="2026-10-03T10:00:00Z"' --project rlz-boekhouding --format="value(textPayload)" --order=asc --limit=400
```
Verwacht:
- per mail een regel `Factuur RLZ-20801430xx ….pdf ← factuurdetails-….pdf […]: kandidaat — via duplicaat → Factuur RLZ-20801430xx … — zou koppelen aan …`
  (zes: 3088, 3092, 3093, 3094, 3125, 3131; staat er "(geboekt)" achter, dan gaat de bijlage ook naar RLZ);
- voor RLZ-2080143044 (afgewezen): óf `via afgewezen factuur → …` (er is een tegenhanger mét dat nummer), óf
  `overgeslagen — factuur afgewezen (‹reden›) — bijlage ook afwijzen?` — dan blijft die bijlage los en beslis jij ná stap 3 in het
  controlescherm (chip mét link naar de afgewezen factuur);
- TOTAAL-regel eindigt op `… 6 via duplicaat — DRY-RUN` (of 7).
Staat er iets geks (een origineel dat niet het origineel is) → niet uitvoeren, uitvoer aan Cowork.

## Stap 3 — échte run Steigerbouw
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|bijlagen-nabundelen|--uitvoeren|--administratie|Universal Steigerbouw"
```
Daarna in de werkvoorraad van Universal Steigerbouw: de factuurdetails staan niet meer los maar onder de factuur (tabblad Bijlagen van het
origineel). Een tweede dry-run geeft 0 kandidaten.

## Stap 4 — kantoorbreed
Dry-run zonder `--administratie`, lezen zoals stap 2, dan de échte run zonder `--administratie`:
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|bijlagen-nabundelen|--dry-run"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|bijlagen-nabundelen|--uitvoeren"
```
