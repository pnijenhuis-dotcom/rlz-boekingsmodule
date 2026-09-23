uitgevoerd 2026-09-23, rapport: docs/rapporten/2026-09-23-nameting-ter-accordering-bestaanscheck-na-deploy.md

Domeinen: reconciliatie, accordering-native-app, duplicaten-crediteuren, werkloop-productie
niet vóór: 2026-09-23 09:00

# NAMETING 23-09 — Dagelijkse bestaanscheck "intussen buiten de module geboekt" ná de deploy van 22-09 (rapport 22-09)

Bouw: `docs/rapporten/2026-09-22-ter-accordering-bestaanscheck-intussen-extern-geboekt.md`; BESLISSINGEN "TER ACCORDERING — DAGELIJKSE
BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)". Alles lees-only (nameting@); poging 1 van hoogstens 3.

Stap 0 — deploy-check: de commit van 22-09 (hercontrole + soort `intussen_extern_geboekt`) staat op origin/main, deploy groen, service ÉN
jobs op die image (`gcloud run jobs describe … image`); `main..origin/main` leeg (bot-commits mergen `--no-ff`).

1. **Échte run van 23-09 06:30** (leesreplica `reconciliatie_bevinding` per administratie + `db-lezen reconciliatie-bevindingen`): hoeveel
   `intussen_extern_geboekt`-bevindingen, per administratie × crediteur × referentie × extern boekstuk; verwacht op de stand van 22-09:
   Bouwadvies 8 (RLZ-04-00000516/518/519/520/521/523/524/526), Molenhof Beheer 1 (RLZ-17-00001131), Rubicon 1 (RLZ-04-00002358) + de Odoo-kant
   van Universal Steigerbouw (43 open, vooraf niet meetbaar). Staan ze in `actie` (niet "in meting")? Actiemail verzonden (`mail_status`)?
2. **`nameting.sh` onderdeel `reconciliatie`** (`reconciliatie-alles --lees-only`, bot-bestand op main): `HERCONTROLE <adm>: N open document(en)
   vers getoetst …, K overgeslagen`-regels per administratie; `OVERGESLAGEN`-redenen (geen credential = zichtbaar, geen bevinding).
3. **Accordeur-kant** (request-log Cloud Logging): `GET /accordering/wachtrij` ná de run → items mét `extern_geboekt` (aantal), 0 × 5xx;
   herinneringen 09:00 (`rlz-accordeur-herinneringen`-log): documenten mét bevinding niet meegeteld; eventuele 409 `WachtOpKantoor`.
4. **Handelingen**: `POST …/extern-geboekt/afwijzen|toch-verschillend` in het request-log (aantal, status), audits `document_afgewezen` mét
   reden "Al geboekt in Reeleezee als …", `extern_duplicaat_toch_verschillend`, `accordering_vervallen` mét marker
   `accordering_vervallen_extern_geboekt`. Geen klik door het kantoor = "niet gemeten (ongebruikt)", nooit "werkt niet".
5. Rapport + INDEX + Gelezen regels; BESLISSINGEN-alinea "Gemeten 23-09" + "werkt in productie: ja/nee/niet gemeten" per onderdeel; bij
   niet gemeten: vervolg-opdracht poging 2 (`niet vóór` de volgende run).
