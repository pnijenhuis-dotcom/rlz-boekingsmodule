# Terminal 03-10 — dubbele projectnummers Universal Steigerbouw samenvoegen (26149, 26053, 26064, 26084)

Besluit Peter 02-10 17:1x ("Ik volg jouw advies", besluit 3 — BESLISSINGEN "RUN A 02-10 — BOEKEN, PROJECTEN, MELDINGEN, KLEINE BUGS
(Peter 02-10)" punt 11 alinea "BESLIST 02-10"): samenvoegregel = **"oudste project mét boekingen blijft"** (de blijver-keuze van
`project-dubbel-samenvoegen`: module-audit → RLZ `BeginDate` → onbekend; gelijk → meeste koppelingen) voor de vier nummers. Peter heeft het
"ja" voor de echte run VOORAF gegeven ONDER VOORWAARDE dat de dry-run per nummer eenduidig is. Cowork leest stap 1 en geeft stap 2 vrij per
nummer; niet-eenduidig = dat nummer terug naar Peter, de andere nummers lopen gewoon door. Niets wordt verwijderd: de verliezer gaat op
afgesloten via de 0160-flow (RLZ `IsActive:false` mét terugleesverificatie), alle koppelingen hangen om volgens het REGISTER mét audit per rij.

Administratie: Universal Steigerbouw `3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`. Actor voor de echte run = Peter (`2f2262cd-0423-4910-b7b5-335ba37a6ef5`).
Bekende stand (leesreplica 02-10, run-A-rapport punt 11): 26149 = `42b27746…` (module, 18 planning/5 reserveringen/2 meerwerk/specificatie)
vs `0b394b0d…` (kale RLZ-UI-naam "26149", 0 koppelingen) → verwachte blijver `42b27746…`. 26053/26064/26084: 19-09 gemeten als
`project_nummer_dubbel`; 26064 = "Afgesloten 26064 Apeldoorn (Ben Kuijer)" (10 RLZ-factuurregels) náást "26064 Harskamp (vd Brandhof)" (0) —
**let op:** RLZ-factuurregels hangen NIET om (de factuur staat in RLZ op dat project, herboeken = mens); de blijver-regel kijkt naar
module-koppelingen én leeftijd, niet naar de RLZ-factuurregel-cache. Valt de blijver op een "Afgesloten …"-naam, dan is dat géén reden om te
stoppen (de naam is Universals afsluitmarkering, de status in de module is lopend), maar wél iets om in de melding aan Peter te noemen.

## Stap 0 — job-image (lees-only)
```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Verwacht: de image van de deploy van 02-10 avond (commit mét `app/projecten/samenvoegen.py`, run A punt 11 `fa7…`/later) of nieuwer; ouder
dan de run-A-merge van 02-10 = stoppen (de CLI bestaat dan niet op de job-image: argparse-exit 2).

## Stap 1 — dry-run per nummer (lees-only, nameting-allowlist; één job-executie per nummer)
```
scripts/gcp/nameting.sh project-dubbel-samenvoegen --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873 --nummer 26149 --dry-run
scripts/gcp/nameting.sh project-dubbel-samenvoegen --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873 --nummer 26053 --dry-run
scripts/gcp/nameting.sh project-dubbel-samenvoegen --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873 --nummer 26064 --dry-run
scripts/gcp/nameting.sh project-dubbel-samenvoegen --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873 --nummer 26084 --dry-run
```
(Zonder TTY kiest `nameting.sh` zelf `gh workflow run`; het dispatch-onderdeel `project-dubbel` draait alleen 26149 + `projecten-dubbele-nummers`
— voor 26053/26064/26084 is deze terminalstap dus de enige lees-only route. Uitvoer per nummer: één regel per kandidaat (`BLIJFT` / `verliezer`,
naam, status, aangemaakt, bron, koppelingen), per verliezer per tabel "N rij(en) zou omhangen, M blijven staan", `archief: zou afsluiten`, en de
slotregel `TOTAAL: nummer N — blijft <id> '<naam>' · K verliezer(s) · R rij(en) omgehangen in T tabel(len) · B rij(en) blijven staan (mens) · modus dry-run`.)

**Eenduidig (Cowork toetst per nummer, alle vier voorwaarden):**
1. precies TWEE kandidaten (één `BLIJFT`, één `verliezer`) — drie of meer = terug naar Peter;
2. `B rij(en) blijven staan (mens)` = **0** — een rij die bij de blijver al bestaat (zelfde unieke sleutel: conflict in koppelingen) = terug naar Peter mét de `·`-redenregels;
3. `archief: zou afsluiten` (niet "bron weigert: …" en niet "al samengevoegd");
4. geen regel `niets samen te voegen` en geen FOUT/traceback in de uitvoer.
Een blijver mét "Afgesloten …"-naam voldoet aan de regel (zie boven) — melden, niet stoppen.

## Stap 2 — échte run per EENDUIDIG nummer (schrijvend, job-executie op de gedeployde image; alleen de nummers die stap 1 doorstaan)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,project-dubbel-samenvoegen,--administratie,3ee6edf0-5cb8-4f98-bba1-16fb97ae6873,--nummer,26149,--uitvoeren,--actor,2f2262cd-0423-4910-b7b5-335ba37a6ef5"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,project-dubbel-samenvoegen,--administratie,3ee6edf0-5cb8-4f98-bba1-16fb97ae6873,--nummer,26053,--uitvoeren,--actor,2f2262cd-0423-4910-b7b5-335ba37a6ef5"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,project-dubbel-samenvoegen,--administratie,3ee6edf0-5cb8-4f98-bba1-16fb97ae6873,--nummer,26064,--uitvoeren,--actor,2f2262cd-0423-4910-b7b5-335ba37a6ef5"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,project-dubbel-samenvoegen,--administratie,3ee6edf0-5cb8-4f98-bba1-16fb97ae6873,--nummer,26084,--uitvoeren,--actor,2f2262cd-0423-4910-b7b5-335ba37a6ef5"
```
Verwacht per nummer: dezelfde kandidaten als in stap 1, `… omgehangen …`, `archief: afgesloten (rlz)`, slotregel `· modus UITGEVOERD`. Zegt de
uitvoer `bron weigert: …` (RLZ bevestigt `IsActive:false` niet), dan staan de koppelingen wél om maar blijft het project in RLZ actief — de run is
herhaalbaar (idempotent): één keer opnieuw, blijft het → terug naar Peter mét de letterlijke reden. Log lezen als `--wait` zonder uitvoer eindigt:
```
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-reconciliatie" AND timestamp>="2026-10-03T00:00:00Z"' --project rlz-boekhouding --format="value(textPayload)" --order=asc --limit=400
```

## Stap 3 — nameting (lees-only): dubbelen weg?
```
gh workflow run nameting -f onderdeel=project-dubbel
```
Bot-bestand `verkenning/nameting-project-dubbel-<dd-mm>.txt` op main: de dry-run 26149 zegt nu "al samengevoegd" en `projecten-dubbele-nummers
--administratie "Universal Steigerbouw"` toont de samengevoegde nummers niet meer; de reconciliatie-run van de volgende ochtend sluit
`project_nummer_dubbel` per nummer mét audit `reconciliatie_auto_gesloten`. Daarna `git -C "/Users/mr.x/Claude/Projects/Rlz boekings module"
pull --ff-only` zodat Cowork de uitkomst kan lezen en in `docs/gesprekken/` + BESLISSINGEN punt 11 ("UITGEVOERD 03-10: …") vastlegt.
