Domeinen: intake-extractie, administraties-instellingen, doorbelasting-intercompany, btw, activa, werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-25 07:15

# NAMETING — bundelrun zeven punten (24-09) ná deploy én ná de reconciliatie-run van 06:30

**Context:** rapport `docs/rapporten/2026-09-24-bundelrun-zeven-punten.md` (élk blok "werkt in productie: niet gemeten"). Stap 0:
`git rev-list --count main..origin/main` → bij divergentie `git merge --no-ff origin/main`; deploy-check service ÉN jobs (`rlz-reconciliatie`,
`rlz-sync`, `rlz-intake-imap`) op het beeld van de laatste bundelrun-commit. Te vroeg → `niet vóór:` +1 uur bovenin en terug in inbox/ (max 3×).

## Opdracht (lees-only; niets uitvoeren dat schrijft — de klikpunten zijn Peters)
1. `gh workflow run nameting -f onderdeel=vastly-tweelingen` → bot-bestand: dry-run TOTAAL (verwacht 23 kandidaten: Rubicon 10 / Elissen 4 /
   ARVUM 3 / Meyer 3 / Shuto 3; afwijking eerst verklaren — JGM-0038/0039 en INP-0025 kwamen als dubbelpaar), `documenten-open` per
   administratie, bevindingen `ubl_pdf_ongebundeld` (meten) in de run van 06:30. Ná Peters "ja" (owner-sessie, niet hier):
   `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --args="^|^-m|app.cli|vastly-pdf-tweelingen-herstel|--uitvoeren"` → dan het
   onderdeel opnieuw (0 kandidaten) + `rlz-lezen --administratie Rubicon --pad SalesInvoices --record-via-filter "Reference eq 'RUB-2026-0031'"
   --expand UploadList` (2 bijlagen).
2. `gh workflow run nameting -f onderdeel=odoo-taal` → `engels` = 0 bij Bonte Hoeve/Nieuwenhoven/Universal Verkoop ná de `sync-alles` van 07:00
   (of ná Peters hersync-executie). Cloud Logging job `rlz-sync`: regel `ledgers=… bijgewerkt=N` voor de Odoo-administraties.
3. `gh workflow run nameting -f onderdeel=dearchiveren-odoo` → request-log POST …/dearchiveren (200 ná Peters klik) + `administratie-stand`
   Recreatief: 8ea9d28b actief/probe_op ≥ deploy/company 13, 59bf1f7f gearchiveerd.
4. `gh workflow run nameting -f onderdeel=doorbelasting-pdf` → kantoorbrede telling per klasse (Peters vraag (c): allemaal 1-cent-gevallen?) +
   Lusso `--pdf`: record-regelsom vs render → A/B; uitkomst in het rapport + OPEN_ITEM aan Vastly als de telling > 0 `onvolledig_cent` geeft
   (webhook-payload 1 cent te veel). Geen fix zonder akkoord Peter.
5. `gh workflow run nameting -f onderdeel=bua-jaarrapport` → TOTAAL-regel `fouten 0` + ≥ 1 administratie "RLZ-kant: gemeten".
6. `gh workflow run nameting -f onderdeel=activa-conventie` → pas zinvol ná een kaart-klik (BLOw herstel = klikpunt); tot dan "niet gemeten".
7. Blok 7a/7b: request-log GET `/omzet/<Van Boxtel>/e7d89765-c4f5-42f3-82d9-71f8a11f5f7f` en GET `…/documenten/3405157f-5a1c-46e8-ba16-980e03d79ee4/boekvoorstel`
   (BLOW) ná Peters klik; `documenten-open --administratie "Van Boxtel" --param soort=inkoopfactuur` (9 rijen tot de bulk-typewissel).

Rapport `docs/rapporten/2026-09-25-nameting-bundelrun-zeven-punten.md` + INDEX + "Gelezen regels"; per blok "werkt in productie: ja/nee/niet gemeten";
BESLISSINGEN-alinea "Gemeten 25-09" per sectie; opdracht → gedaan mét kopregel. Hoogstens drie pogingen (regel 22-09 (3)).
