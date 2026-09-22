Domeinen: btw, administraties-instellingen, reconciliatie, werkloop-productie
niet vóór: 2026-09-23 09:00

# NAMETING 23-09 — Btw-plichtig per administratie ná de deploy van 22-09: data-stap VGG op "niet btw-plichtig", detector-LET-OP,
# nazorgrapport TE WEINIG (Studio Lacy Lion 2026-042) — rapport 22-09

Bouw: `docs/rapporten/2026-09-22-btw-plichtig-per-administratie-vgg-lacy-lion.md`; BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE —
NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)". Poging 1 van hoogstens 3.

Stap 0 — deploy-check: de commit van 22-09 (migratie 0170, `app/beheer/btw_plichtig.py`) staat op origin/main, deploy groen, service ÉN
jobs op die image (`gcloud run jobs describe … image`); `main..origin/main` leeg (bot-commits mergen `--no-ff`). Alembic-head in productie
= 0170 (health/migratieversie via de bewakingsprobe).

1. **Data-stap VGG (besluit Peter 13-09 "VGG is niet btw-plichtig", capture in de opdracht van 22-09; SCHRIJVEND, job-image):**
   `gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|btw-plichtig-zetten|--administratie|Vastgoedgroep|--uit|--dry-run"` →
   verwacht "DRY-RUN … True (bron geen) → False"; daarna zonder `--dry-run` → "GEZET … btw_plichtig=False bron=mens … geen-btw-code:
   NL, Geen BTW (Vrijgesteld)". Audit `administratie_btw_plichtig_gewijzigd` op de leesreplica (1 rij, actor systeem). Alleen VGG —
   andere administraties pas ná Peters besluit op de kandidatenlijst (stap 3).
2. **Nachtelijke identiteit-sync (sync-alles 23-09 07:00)**: log-regels "btw-plichtig bevestigd uit RLZ (EnableTaxReporting)" (verwacht:
   het merendeel van de 78) en "RLZ EnableTaxReporting=false — kandidaat" (verwacht: VGG als die vóór stap 1 al gelezen is; ná stap 1 =
   "mens"-stand, geen melding). Leesreplica: `btw_plichtig_rlz_signaal` gevuld op élke RLZ-administratie, `btw_plichtig_bron='rlz'` waar
   true; Odoo-administraties NULL.
3. **Detector-LET-OP `btw_status_bevestigen`** (run 23-09 06:30 draait vóór de sync van 07:00 — op de stand van 22-09 dus nog zonder
   RLZ-signaal → alleen kandidaten "geen tarief met percentage" bij een gesyncte cache zonder >0 %-tarief; verwacht 0). Ná de sync van
   07:00 + de run van 24-09 06:30: kandidatenlijst = `nameting.sh btw-plichtig-kandidaten` (dispatch-onderdeel `btw-niet-plichtig` draait
   'm mee) — verwacht leeg als stap 1 gedaan is, anders exact VGG. Lijst = Peters beslispunt "verhuurders zonder optie belaste verhuur"
   (ARVUM en Rubicon zijn per STAP-0 géén kandidaat: EnableTaxReporting true).
4. **Nazorgrapport (dispatch-onderdeel `btw-niet-plichtig`, `gh workflow run nameting.yml -f onderdeel=btw-niet-plichtig`)**: bot-bestand
   `verkenning/nameting-btw-niet-plichtig-23-09.txt` mét de MODULE-tabel (verwacht ≥ 1 rij: Studio Lacy Lion 2026-042, RLZ-04-00000925,
   bruto 1857.51, btw 322.38), de RLZ-kolommen (crediteurpost 1535.13 als de casus klopt → TE WEINIG 322.38) en "ingediende
   btw-aangiften in RLZ: 0" (aangiftepoort n.v.t.). Elk ander document in die tabel = Peters nabetaallijst; ook de RLZ-rijen zonder
   module-spoor benoemen.
5. **Klikpunt Peter — Lacy Lion herstellen**: ⋯ › "Corrigeren…" op het geboekte document (reden bv. "btw in kosten — administratie niet
   btw-plichtig"), daarna staat de regel ná de prefill op bruto 1.857,51 / btw 0 / "NL, Geen BTW (Vrijgesteld)" mét chip; check "Btw in
   niet-btw-plichtige administratie" groen → "Boeken in RLZ". Verwacht in RLZ: crediteurpost 1.857,51, `BaseRemainingAmount` 322,38 ná de
   eerdere betaling van 1.535,13 (nabetaling). Meting = onderdeel `btw-niet-plichtig` opnieuw → TE WEINIG 0.00 voor dit document +
   request-log `POST …/corrigeren` 200. Geen klik = "niet gemeten (klikpunt)", nooit "werkt niet".
6. Rapport + INDEX + Gelezen regels; BESLISSINGEN-alinea "Gemeten 23-09" + "werkt in productie: ja/nee/niet gemeten" per onderdeel
   (data-stap, sync-signaal, detector, nazorgrapport, herstel); regels-alinea's btw.md/administraties-instellingen.md bijwerken; bij niet
   gemeten: vervolg-opdracht poging 2 (`niet vóór` de volgende run).
