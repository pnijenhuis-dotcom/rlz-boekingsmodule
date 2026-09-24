Domeinen: doorbelasting-intercompany, btw, reconciliatie, werkloop-productie
niet vóór: 2026-09-25 07:15

# NAMETING — doorbelasting btw in de RLZ-vorm (24-09 avond) ná deploy én ná de reconciliatie-run van 06:30

**Context:** rapport `docs/rapporten/2026-09-24-doorbelasting-btw-rlz-vorm.md` ("werkt in productie: niet gemeten"), BESLISSINGEN "DOORBELASTING — BTW PER
TARIEF OVER HET SUBTOTAAL (RLZ-VORM) + DATA-STAP + FACTUUR-PDF-HERSTEL (Peter 24-09)". Stap 0: `git rev-list --count main..origin/main` → bij
divergentie `git merge --no-ff origin/main`; deploy-check service ÉN job `rlz-reconciliatie` op het beeld van de commit van 24-09 avond
(`doorbelasting-bedragen-gelijktrekken` moet op de job-image bestaan: `--smoketest`/`--help`). Te vroeg → `niet vóór:` +1 uur bovenin en terug in
inbox/ (max 3×, regel 22-09 (3)).

## Opdracht (lees-only; de schrijvende stappen zijn Peters klikpunten — nooit vanuit deze run)
1. `gh workflow run nameting -f onderdeel=doorbelasting-btw` → bot-bestand `verkenning/nameting-doorbelasting-btw-<dd-mm>.txt`:
   (a) dry-run data-stap — **verwacht TOTAAL 188 (+ doorbelastingen ná 24-09 avond, die gelijk horen te zijn) · gelijk 133 · cent-verschil ≤ 0,05: 55
   (zou gelijktrekken) · afwijking 0 · niet leesbaar 0 · boekstand-events 0**; élke afwijking eerst verklaren (RLZ-UI-wijziging? credential?);
   (b) `doorbelasting-factuur-pdf-toets` → 58 (54 cent + 1 × 2 ct + 2 overig + credit 24713270) vóór de herstelrun; (c) bevindingen KF:
   `doorbelasting_bedrag_afwijking` (verwacht 0) en `doorbelasting_factuur_pdf_ontbreekt` (verwacht 58 in meting ná de run van 06:30).
2. Cloud Logging job `rlz-reconciliatie` (scheduler-run 06:30): regel `INFO … 55 doorbelasting(en) mét een cent-verschil ≤ € 0,05` in het
   doorbelasting-blok; geen `AFWIJKING … doorbelasting_bedrag_afwijking`.
3. **Klikpunt Peter (owner-sessie, niet hier) — ná zijn "ja" op de telling van 1a:**
   `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|doorbelasting-bedragen-gelijktrekken|--uitvoeren"`
   → verwacht "GELIJKGETROKKEN" 55×, TOTAAL … gelijkgetrokken 55; daarna
   `… --args="^|^-m|app.cli|doorbelasting-facturen-herstel|--dry-run"` (57 kandidaten) en zonder `--dry-run` (verwacht 57 hersteld, 1 mislukt:
   24713270 negatieve bedragen — apart benoemen). Dan het onderdeel opnieuw: dry-run 188 gelijk / 0 cent; PDF-toets ≤ 1; bevindingen
   `doorbelasting_factuur_pdf_ontbreekt` sluiten in de volgende run mét `reconciliatie_auto_gesloten`.
4. **Eén nieuwe doorbelasting (Peter kiest: echt geval of testadministratie ná dearchiveren):** `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh rlz-lezen
   --administratie "Kempen Facilities" --pad "SalesInvoices/<verkoop_rlz_id>" --expand 'DocumentLineList($expand=TaxRate)'` en
   `--administratie <doel> --pad "PurchaseInvoices/<spiegel_rlz_id>"` (GUID's via `db_lezen.sh` op `doorbelasting_boeking`, RLS-scope KF) →
   `TotalTaxAmount` = `btw_bedrag` én regel-`TaxAmount` = wat wij stuurden (Cloud Logging PUT-body of de fake-vorm) én `factuur_pdf_status = aanwezig`.
5. Audit: `db-lezen`/replica `platform.audit_event` actie `doorbelasting_bedrag_gelijkgetrokken` = 55 rijen (ná 3), `doorbelasting_factuur_hersteld` = 57.

Rapport `docs/rapporten/2026-09-25-nameting-doorbelasting-btw-rlz-vorm.md` + INDEX + "Gelezen regels"; per stap "werkt in productie: ja/nee/niet
gemeten"; BESLISSINGEN-alinea "Gemeten 25-09" in de sectie; `docs/regels/doorbelasting-intercompany.md` alinea aanvullen; opdracht → gedaan mét
kopregel. Wacht stap 3 nog op Peters "ja", dan de lees-only stappen rapporteren en de opdracht terug in inbox/ mét `niet vóór:` +1 dag (max 3×).
