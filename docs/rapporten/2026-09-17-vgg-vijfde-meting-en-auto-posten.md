# Rapport 17-09 — VGG → Odoo run 2: VIJFDE METING (blok 10 + 11) + aanvulling Peter "1 boeking testen, dan alles definitief": SCHRIJF c niet uitvoerbaar op de gedeployde image, instrument `vgg-odoo-migratie` gebouwd

Opdracht: `opdrachten/gedaan/2026-09-17-vgg-vijfde-meting.md` (incl. aanvulling). Geen migratie; **geen Odoo-writes in deze run**.
**Werkt in productie: blok 10 ja (3606/3607 Δ 0,00, overlap 0); blok 11 nee (project-dekking niet meetbaar door een instrumentfout — gefixt); SCHRIJF c / auto-posten niet gemeten (niet gedeployd).**

## Vijfde meting (nameting-workflow run 35227253545, onderdeel c, job `rlz-reconciliatie-7hv8c`, replay 2026-09-17T13:35:49Z)
De bot-commit faalde op de pathspec-bug (gefixt in deze run) → uitkomst uit het run-log (2.177 regels, replay-sectie 761 regels; rijtellingen tegen de koppen: 1001-tabel 164 rijen, saldibalans-, herclassificatie- en project-dekkingtabel volledig aanwezig).

| Onderdeel | Uitkomst | Oordeel |
|---|---|---|
| Replay | **ROOD — 3 verschil(len)**, 892 niet vertaalbaar (vierde: 888, +4 nieuwe documenten), 0 leesfouten, 0 zonder regels, memoriaal uit balans 0, resultaatposten sluiten, betalingsverschillen 1 (€ 0,02), geblokkeerd (partner) 2: RLZ-04-00000109 € 182.442,39 en RLZ-25-00000111 € 239.202,65 (2025-09-02); RLZ-calls 1176, webfilter 0 | verwacht |
| **3606 / 3607** | saldibalans Odoo € 986.569,81 / € 658.861,82 mét **Verschil € 0,00** (beide peildata); herclassificaties **133 → 3607 € 658.861,82 (60 documenten)** en **3180 → 3606 € 986.569,81 (4 documenten)** — vanuit de tegenzijde, niet meer `ongemapt:1001` | **blok 10 werkt** |
| Één regel, één bestemming | "geen overlap tussen 1001-model en RJ-220-rol (0 memorialen dragen de rol op de tegenzijde)"; `overlappen` 0; 1001-model 164 regels: 140 → outstanding BNK1 (id 132), 24 tussenrekening, 0 meerduidig | groen |
| Kolom "RJ-220-tegenzijde → rol" | **0 van 164 rijen gevuld** (verwacht 14) terwijl de herclassificatie wél op de tegenzijde landt — leesbaarheidsafwijking, geen saldo-effect; nazorg: kolomvulling ↔ `rol_regel_index` | afwijking |
| ROOD-groepen | crediteuren Δ € −5.879.086,77 / € −11.145.509,26; debiteuren Δ € 4.644.333,67 / € 8.811.303,25; tussenrekening Δ € −153.750,00 / € −513.125,61 (componenten: 24× 1001 zonder bankmutatie € 386.451,35; 24× open bankmutaties € −185.545,68; afletterstand SCHRIJF c € −714.031,28); **bankgroep € 0,00** | alleen afletter-groepen = verwacht tot SCHRIJF c |
| **Project-dekking (blok 11)** | **0,000 op álle groepen** (1.125 documenten, 0 regels mét Project; kruistoets 0) | **instrumentfout**: `DOCUMENTVORM_EXPAND` droeg geen `Project` — gefixt (`Account,TaxRate,Project`) + guard `test_project_dekking.py::test_documentvorm_expand_leest_project_mee`; dekking = niet gemeten, zesde meting ná deploy |

## Aanvulling Peter — SCHRIJF c + auto-posten
- **SCHRIJF c NIET uitgevoerd.** Dry-run `scripts/gcp/vgg_blok7_odoo_writes.sh plan` (job-executies ~14:30Z, deploy-check ok op `7418cd5`): `vgg-odoo-stap0` meldt "selectie juli 2025: in_invoice 0 · entry 0 · out_invoice 0 — geen factuur in 2025-07 met gekoppelde bankregel(s)". Het bewijspaar RLZ-01-00000082 (blok 9: verkoopfactuur notaris 2026-03-19, € 400.000) ligt buiten de vaste STAP-0-maand; de juli-facturen staan op ledgers zonder Odoo-rekening in company 6 (niet vertaalbaar). De gedeployde CLI kan het paar niet kiezen → niets te posten. IBAN-klikpunt op BNK1: niet gemeten (stap 4 niet bereikt). (`odoo-koppeling-migratiedoel` dry-run: "bron-administratie heeft geen Odoo-koppeling" = de bekende bron-key-les: `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"`.)
- **Gebouwd:** `vgg-odoo-stap0 --boekstuk RLZ-01-00000082` (+ `--maand`), `VGG_BEWIJSPAAR` in het schrijfscript (default RLZ-01-00000082) — tests `TestSelectie` (+2), CLI-dispatch.
- **Gebouwd (stap 2 van de aanvulling): `vgg-odoo-migratie`** (`app/migratie/odoo_migratie_run.py`): A concepten (partners zoek-vóór-create, concept-moves idempotent op anker, statement lines) → B toets uit Odoo (Σ debet = Σ credit cent-exact; factuur-tegenzijde = Σ factuurregels; aantal = verwacht; per pand "sluit") → C bulk `action_post` (batches 50, terug-gelezen, audit) alleen bij GROEN → D reconcile via de route-registry (restpunt, geen ROOD). Rood in B = niets gepost, concepten blijven zichtbaar. Kill-switch + default dry-run; `nameting.sh` weigert; schrijfscript `SCHRIJF d` + `plan`. Tests `tests/migratie/test_odoo_migratie_run.py` 12 groen (groen post alles; toets rood post niets; pand-eis rood; `--geen-posten`; kill-switch; dispatch; weigering).
- BESLISSINGEN: nieuwe sectie "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)"; alinea "Vijfde meting 17-09" onder RUN 2 BLOK 10 en BLOK 11; CLAUDE.md-regel.

## Volgorde ná deploy (vervolg-opdracht `2026-09-17-vgg-schrijf-c-na-deploy.md`)
`plan` (IBAN zichtbaar) → zesde meting (dekking mét Project) → `SCHRIJF c` (bewijspaar gepost + gereconcilieerd, move-ids + saldocontrole) → rapport = GO-moment Peter → `SCHRIJF d` als nieuwe inbox-opdracht.

## Beslispunten (defaults gekozen)
1. De aanvulling zegt "ná een GROENE vijfde meting": de replay is per definitie ROOD tot SCHRIJF c (afletter-groepen); "groen" is gelezen als "groen op de blok-10-criteria" — én zelfs dan was SCHRIJF c op de gedeployde image niet uitvoerbaar.
2. `vgg-odoo-migratie` post álles in één run als de toets groen is (Peter: geen klikwerk) — de GO van Peter zit vóór het starten van `SCHRIJF d`, niet per document.
3. De 0-gevulde kolom "RJ-220-tegenzijde → rol" is gerapporteerd, niet gerepareerd (geen saldo-effect; eerst de zesde meting).

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/vgg-odoo-migratie.md` (50 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
