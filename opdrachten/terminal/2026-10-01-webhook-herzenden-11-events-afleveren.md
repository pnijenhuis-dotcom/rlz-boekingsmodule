# Terminal 01-10 — elf `factuur_geboekt`-kostenevents herzenden MÉT directe aflevering (OPEN_ITEMS regel 16/17; verzoek Vastly 01-10)

Vastly heeft de kostenintake voor Rubicon en ARVUM aangezet (fixrun 25-09) en vraagt één job-executie per referentie met
`--uitvoeren --afleveren`, zodat het antwoord van Vastly per event in het log staat. Claude Code voert uit mét toestemming per commando.
De rijen zijn op 24-09 al eens herzonden (antwoord toen `kostenintake_uit`); de CLI zet afgeleverde rijen opnieuw op openstaand — dat is
de bedoeling. Beheerder-id = Peter (`2f2262cd-0423-4910-b7b5-335ba37a6ef5`).

## Stap 0 — job-image (lees-only)
```
gcloud run jobs describe rlz-webhook-afleveraar --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Verwacht: `fff721c` of nieuwer (ouder dan `5a9be94` = stoppen).

## Stap 1 — Rubicon Investments (6), één executie per referentie
```
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,24713213,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,24713354,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,265050202128,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,26753012,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,26734257,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,2026-017,--uitvoeren,--afleveren,--reden,Kostenintake Rubicon staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
```

## Stap 2 — ARVUM B.V. (5), één executie per referentie
```
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,183727,--uitvoeren,--afleveren,--reden,Kostenintake ARVUM staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,26747235,--uitvoeren,--afleveren,--reden,Kostenintake ARVUM staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,26752091,--uitvoeren,--afleveren,--reden,Kostenintake ARVUM staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,522500062785,--uitvoeren,--afleveren,--reden,Kostenintake ARVUM staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,537500100925,--uitvoeren,--afleveren,--reden,Kostenintake ARVUM staat sinds fixrun 25-09 aan; herzending op verzoek Vastly 01-10 (OPEN_ITEMS regel 16)"
```

## Stap 3 — log lezen (lees-only), per executie-naam uit de uitvoer
```
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-webhook-afleveraar" AND timestamp>="2026-10-01T00:00:00Z"' --project rlz-boekhouding --format="value(textPayload)" --order=asc --limit=400
```
Verwacht per referentie: `200 {"resultaat":"verwerkt", … "kostenvoorstellen":{"resultaat":"voorstellen", …}}`. Nog `kostenintake_uit` = Vastly-vlag
staat tóch niet aan → uitvoer aan Cowork, niet opnieuw proberen.

## Stap 4 — stand Vastly-verkoop in RLZ (lees-only; nodig voor OPEN_ITEMS regel 14, de 39 her-aanleveringen)
```
gh workflow run nameting -f onderdeel=vastly-verkoop
```
Uitkomst = bot-commit op main (rapport + meetlat); daarna `git -C "/Users/mr.x/Claude/Projects/Rlz boekings module" pull --ff-only` zodat
Cowork kan lezen welke Vastly-verkoopdocumenten geboekt / open / geweigerd zijn, per administratie.
