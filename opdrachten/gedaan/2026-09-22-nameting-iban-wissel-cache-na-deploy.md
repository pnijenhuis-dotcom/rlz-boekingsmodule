uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md

Domeinen: werkvoorraad-controlescherm, autoboeken-ai, werkloop-productie
niet vóór: 2026-09-22 09:00

# Nameting checks-cache-invalidatie (IBAN-wissel ná vier-ogen-akkoord) ná de deploy van 21-09 + nazorg `checks-cache-legen`

**Context:** rapport `docs/rapporten/2026-09-21-iban-wissel-cache.md`, BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord)
21-09". De fix (commit van 21-09) is alleen live ná de deploy; de nazorg-CLI is SCHRIJVEND en mag uitsluitend als `gcloud run jobs
execute` op de gedeployde job-image draaien (regel Peter 08-09). Daarom `niet vóór: 2026-09-22 09:00`. "Werkt in productie: niet gemeten"
is een schuld mét vervaldatum (les verbeteringen.md 21-09) — deze opdracht lost 'm in.

## Stap 0 — deploy-check (service ÉN jobs op een image ≥ de fix-commit; `git rev-list --count main..origin/main` toetsen en `merge --no-ff` als > 0).
```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format='value(template.template.containers[0].image)'
```

## Stap 1 — nazorg: bestaande stale rapporten ongeldig maken (schrijvend, één keer, job-image)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,checks-cache-legen,--alles,--dry-run"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,checks-cache-legen,--alles"
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,checks-cache-legen,--alles,--dry-run"
```
Verwacht: dry-run 1 = "N geldig, 0 ongeldig gemaakt" (N = aantal documenten mét een extern rapport < 15 min oud op dat moment — kan 0
zijn buiten kantooruren; dan is de echte run een bewezen no-op, óók een uitkomst); echte run = "N ongeldig gemaakt"; dry-run 2 = 0 geldig.
Log via `gcloud logging read` op de executienaam (Cloud-Run-job-logs laten regels vallen — toets op de totaalregel). Kan gcloud in deze
run niet inloggen (bekend 16/17-09): NIET stil — klikpunt Peter mét de drie letterlijke commando's in het rapport.

## Stap 2 — meten (lees-only; dispatch-onderdeel of request-log)
1. **Meyer-document** 0015.21.664.V.51.0112 (Beleggingsmaatschappij Meyer B.V.): via `nameting -f onderdeel=query -f query="document-feiten
   --param referentie=0015.21.664.V.51.0112"` (of het dichtstbijzijnde querybibliotheek-recept) de status + laatste checks-stand; verwacht
   ná herladen door een mens: "IBAN-wissel" = OK en status niet meer `wacht_op_iban_accordering`. Is het document intussen geboekt: dat is
   de sterkste meting (boekstuknummer in het rapport).
2. **Request-log** (Cloud Logging, rlz-backend): `POST …/boekvoorstel/checks?extern=vers` ≥ 1 ná de deploy = de knop "Opnieuw controleren"
   of de 409-route is gebruikt; 0 = "niet gemeten (geen mens raakte de route)", nooit "werkt niet".
3. **Audit** `leverancier_iban_toegevoegd` mét `nieuwe_waarde.checks_cache_ongeldig` bij het eerstvolgende vier-ogen-akkoord/bevestiging
   (query lees-only) — ≥ 0 is correct (0 = geen gecacht rapport op dat moment), het VELD moet bestaan.
4. **Server-Timing** `checks.extern` p50/p95 op 22-09 t.o.v. 20-09: geen regressie verwacht (één extra lokale query per checks-run).

## Stap 3 — rapport
`docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee/niet
gemeten" letterlijk per stap; alinea "Gemeten 22-09" onder de BESLISSINGEN-sectie van 21-09 en in `docs/regels/werkvoorraad-controlescherm.md`.
Rood (IBAN-wissel nog Blokkerend ná een verse run terwijl het IBAN in `leverancier_iban` staat) = letterlijke melding + fix in dezelfde run.
