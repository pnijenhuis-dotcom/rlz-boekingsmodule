# Rapport 22-09 — Btw-plichtig per administratie: niet-plichtig = btw in de kosten, harde check (BUG Peter 22-09, casus VGG / Studio Lacy Lion 2026-042 → RLZ-04-00000925)

**Opdracht:** `opdrachten/gedaan/2026-09-22-BUG-niet-btw-plichtige-administratie-btw-gesplitst-vgg-lacy-lion-te-weinig-betaald.md`
**Status:** GEBOUWD + GETEST · **werkt in productie: niet gemeten** (het kenmerk staat overal op true tot de data-stap; vervolg-opdracht
`opdrachten/inbox/2026-09-23-nameting-btw-plichtig-vgg-data-stap-en-lacy-lion.md`, `niet vóór: 2026-09-23 09:00`).
**BESLISSINGEN:** "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)".
**Migratie:** 0170 (`platform.administratie.btw_plichtig` + bron + RLZ-signaal; schema-only) — `make migrate` op de dev-DB gedraaid
(`Running upgrade 0169 -> 0170`), `scripts/dump_schema.sh` ververst (head 0170), live 200 op `GET /administraties/{id}/btw-plichtig`
(eigen uvicorn 8017, Beheerder-token).

## 1. Wat er misging (feiten)

Vastgoedgroep Nederland B.V. is niet btw-plichtig (besluit Peter 13-09; de kennis zat alleen in `odoo/rj220.py` en
`migratie/vertaling.py`). De module kende geen administratie-kenmerk "btw-plichtig" en splitste Studio Lacy Lion 2026-042 (11-09-2026,
€ 1.857,51) in netto 1.535,13 + 21 % 322,38 op 4106 Schoonmaakkosten; drie akkoorden later (Sophia Gerritsen 16-09, Kempen 18-09) boekte
RLZ RLZ-04-00000925 mét een crediteurpost van 1.535,13 — RLZ wikkelt in die administratie geen btw af — en de betaling volgde de open
post: € 322,38 te weinig aan de leverancier. De harde check "Btw-bedrag past bij tarief" was groen: die toetst het tarief, niet of de
administratie überhaupt mag splitsen.

## 2. STAP-0 (lees-only, `nameting.sh rlz-lezen`, 22-09) — vastgelegd in api-verkenning "AdministrationSettings.EnableTaxReporting"

| Administratie | `AdministrationSettings.EnableTaxReporting` |
|---|---|
| Vastgoedgroep Nederland B.V. | **false** |
| Kempen Facilities B.V. | true |
| Rubicon Investments B.V. | true |
| Arvum B.V. (RLZ-naam; "ARVUM" matcht niet) | true |

Geen ander leesbaar btw-status-veld op `Administrations/{id}` of `AdministrationSettings`. De tarievenset van VGG is de RLZ-standaardset
(22 tarieven, incl. "NL, Geen BTW (Vrijgesteld)" IsExcempt favoriet, "NL, Nul tarief") — de tarieven zeggen dus niets over de status; de
detector uit de opdracht ("administratie zonder TaxRates > 0 %") vangt VGG niet, het RLZ-signaal wél. Niet gemeten: hoe RLZ een PUT mét
TaxRate 21 % + TaxAmount in zo'n administratie verwerkt (de casus zegt: TaxAmount niet in de crediteurpost) — het nazorgrapport leest dat
per document terug.

## 3. Gebouwd

1. **Kenmerk** `btw_plichtig` (default true), `btw_plichtig_bron` ('rlz' | 'mens' | NULL), `btw_plichtig_gewijzigd_op`,
   `btw_plichtig_rlz_signaal` + `_gezien_op` (0170). Eén schrijver `backend/app/beheer/btw_plichtig.py`. Beheerder-rij "Btw-plichtig" op
   Instellingen › Administraties › ‹administratie› › Boeken & AI (`frontend/src/instellingen/BtwPlichtigRij.tsx`, anker `btw-plichtig`,
   registry-entry): schakelaar, herkomst-chip, chip "Reeleezee: btw-aangifte aan/uit", bij uit de "geen btw"-code, bij een kandidaat een
   oranje regel mét "Blijft btw-plichtig" / "Niet btw-plichtig". Routes `GET/PUT /administraties/{id}/btw-plichtig` (Beheerder), audit
   `administratie_btw_plichtig_gewijzigd` oud→nieuw; de administratie-lijst draagt `btw_plichtig`/`_bron`/`_rlz_signaal`.
2. **Bron RLZ + detector.** De nachtelijke identiteit-sync (`intercompany/identiteit.py`, zelfde AdministrationSettings-call) leest
   `EnableTaxReporting`: true → bevestigt btw-plichtig mét bron 'rlz' (alleen zonder mens-keuze); **false → alleen signaal, nooit zelf op
   false** (zie keuze a). Detector `btw_plichtig.kandidaten()` → per kandidaat één LET-OP `btw_status_bevestigen` in het blok
   `automatisering` (`reconciliatie/automatiseringen.btw_status_bevindingen`) mét deeplink naar de instelling; geen regressie, geen
   `meten`-fase (een LET-OP is geen bevindingssoort). CLI `btw-plichtig-kandidaten` = de kandidatenlijst voor Peter.
3. **Gedrag bij `false`** (btw bestaat niet): prefill `regel_prefill._met_niet_btw_plichtig` als LAATSTE stap — élke regel + de
   samengevoegde regel bruto (netto + factuur-btw, btw 0, `btw_in_kosten`) mét de "geen btw"-code (vrijgesteld > NL 0 % > geen → PUT
   zonder `TaxRate`, `rlz_inkoop.regels_naar_rlz_lines`/`tegenboek_lines`), `btw_bron='administratie_niet_btw_plichtig'`, chip
   "administratie niet btw-plichtig — btw zit in de kosten"; het controlescherm verbergt de btw-keuzelijst (`BoekvoorstelPanel`,
   `btw_plichtig` + `geen_btw_taxrate_id` op de boekvoorstel-response). **Harde check "Btw in niet-btw-plichtige administratie"**
   (`checks.check_btw_niet_plichtig`, lokaal, beide rapport-takken, autoboek-pad, direct ná de tarief-check die dan "n.v.t." meldt):
   btw ≠ 0 / tarief > 0 % / verlegd / buitenland / onbekend = blokkerend mét één actie "Btw in de kosten zetten (alle regels)"
   (`ACTIE_BTW_IN_KOSTEN_ALLES`; de frontend herrekent élke regel en slaat op). Verplichte velden eist geen btw-code meer; regeltelling blijft
   Σ bruto = totaal incl. **Verkoop** (Vastly 380/381): `verkoop/voorstel._niet_btw_plichtig_toepassen` (bruto/0, vergrendeld, UBL-categorie
   weg) + rij `check_btw_niet_plichtig_verkoop`. **Kassarapport:** `omzet/boeken._taxrate_percentages` → 0 voor élke code + check-rij op
   een categorie mét tarief > 0 %/verlegd. **Doorbelasting:** spiegel-inkoop in een niet-plichtig doel incl. btw als kosten (`_spec_voor_doel`,
   één spec voor RLZ-regels én webhook) mét de doel-"geen btw"-code of zonder TaxRate; de bron-verkoop blijft mét btw.
4. **Nazorg** — lees-only CLI `btw-in-niet-plichtige-administratie --administratie … --jaar 2026 [--rlz] [--json-uit]`
   (`app/beheer/btw_plichtig_cli.py`, nameting-allowlist, dispatch-onderdeel `btw-niet-plichtig` in nameting.yml): module-geboekte
   inkoopfacturen mét btw ≠ 0 → boekstuk/leverancier/referentie/datum/netto/btw/bruto; `--rlz` (uitsluitend GET op het eigen client-GUID)
   → crediteurpost `BaseInvoiceAmount`, `TotalTaxAmount`, betaald, open en kolom **TE WEINIG** = bruto module − crediteurpost RLZ, plus
   RLZ-inkoopfacturen van het jaar mét `TotalTaxAmount` ≠ 0 zonder module-spoor en het aantal ingediende aangiften (aangiftepoort n.v.t.
   bij 0). Schrijvende CLI `btw-plichtig-zetten --administratie … --uit|--aan [--dry-run]` (weigerlijst nameting.sh; job-image ná deploy).
5. **Vastly/Odoo:** `docs/ONTWERP_VASTLY_ODOO.md` §2.1 — niet-btw-plichtige company = geen btw-mapping (`tax_ids = []`); ARVUM erft het
   kenmerk (true → mét mapping). Geen code (ontwerp ter akkoord).

## 4. Keuzes zonder Peter

- **(a) RLZ false ≠ automatisch false.** `EnableTaxReporting` betekent letterlijk "btw-aangifte in RLZ aan/uit"; een administratie die de
  aangifte buiten RLZ doet zou óók false geven — stil alle btw in de kosten zetten is de spiegelbeeld-fout van de casus. Daarom: false =
  detector-LET-OP, mens bevestigt; true = bevestiging mét bron 'rlz'. VGG op false is een data-stap (stap 1 vervolg-opdracht; besluit
  13-09 bestaat al).
- **(b) "Geen btw"-code = vrijgesteld boven NL 0 %** (BLOW-lijn: 0 % landt in aangifterubriek 1e, vrijgesteld niet); geen van beide → PUT
  zonder TaxRate mét TaxAmount 0 (risico: RLZ rekent zonder tarief soms 21 % — bank-aanbetalings-PoC; in een EnableTaxReporting=false-
  administratie niet gemeten → het nazorgrapport maakt het zichtbaar).
- **(c) De check-rij verschijnt alleen bij `false`** (zoals de projectafgesloten-rij) — geen "n.v.t."-ruis op 78 administraties.
- **(d) Verlegd/EU-tarieven zijn in zo'n administratie óók rood** (ze maken aangifterubrieken aan).
- **(e) Detector-tarievensignaal telt pas bij een gesyncte cache** — een administratie vóór haar eerste sync is een sync-gat, geen kandidaat.
- **(f) LET-OP i.p.v. bevindingssoort in `meten`** — regel 2 van reconciliatie geldt voor afwijkingssoorten; dit is een instellings-LET-OP
  mét handeling, zelfde lijn als `werkvoorraad_tellers`.

## 5. Tests

- Backend nieuw: `tests/beheer/test_btw_plichtig.py` (12: pure regels, service + audit, routes 200/403/404 + lijst-DTO, detector over twee
  administraties + LET-OP, identiteit-sync-hook, CLI kandidaten/zetten/rapport mét RLZ-stub), `tests/documenten/test_btw_niet_plichtig.py`
  (9: check + actie, verplichte velden, tarief n.v.t., volgorde in `voer_harde_checks_uit`, PUT zonder TaxRate, prefill door de keten mét
  Σ bruto = 1.857,51, storings-tak groen, mens splitst → rood mét actie), `tests/doorbelasting/test_btw_niet_plichtig_doel.py` (2),
  `tests/verkoop/test_btw_niet_plichtig.py` (2), `tests/omzet/test_btw_niet_plichtig.py` (1); `test_nameting_workflow.py` bijgewerkt
  (onderdeel `btw-niet-plichtig`). Gericht: 26 passed.
- Frontend: vitest `BtwPlichtigRij.test.tsx` (4), `BoekvoorstelPanel.btwPlichtig.test.tsx` (2: chip + verborgen keuzelijst, actie herrekent
  alle regels → PUT bruto/0/vrijgesteld); volledige vitest 254 bestanden / 1930 passed; `tsc -b` schoon.
- Gouden-set-casus **ak** `tests/keten/test_ak_niet_btw_plichtige_administratie.py` (2: Rituals-document in een niet-btw-plichtige
  administratie → prefill bruto/vrijgesteld, DTO `btw_plichtig=false`, checks groen, RLZ-regels TaxAmount 0; mens splitst → rood mét
  actie alle regels → groen). Keten-guard groen.
- Volledige backend-suite (22/23-09 nacht, 50 min): 7196 passed, 1 skipped, 1 rood = de keten-guard (gouden set nog niet aangeraakt) →
  casus ak toegevoegd, herdraai casus ak + keten-guard + docs-guards (rapporten-index, gelezen regels, CLAUDE.md-verwijzingen,
  regels-index): 16 passed.

## 6. Werkt in productie

**Niet gemeten.** Meetrecept in de vervolg-opdracht: (1) data-stap `btw-plichtig-zetten --administratie Vastgoedgroep --uit` op de job-image
(dry-run → echt, audit 1 rij); (2) sync-alles 23-09 07:00 → `btw_plichtig_rlz_signaal` gevuld, bron 'rlz' op de true-administraties;
(3) detector-LET-OP/kandidatenlijst leeg ná stap 1; (4) dispatch-onderdeel `btw-niet-plichtig` → MODULE-tabel mét Lacy Lion TE WEINIG
322.38 en "ingediende btw-aangiften: 0"; (5) klikpunt Peter: "Corrigeren…" op RLZ-04-00000925 → herboeking bruto 1.857,51 / btw 0 →
crediteurpost 1.857,51, restant 322,38 open → TE WEINIG 0.00.

## 7. Open punten / beslispunten Peter

1. Kandidatenlijst "verhuurders zonder optie belaste verhuur": per STAP-0 zijn ARVUM en Rubicon géén kandidaat (EnableTaxReporting true);
   de nachtelijke sync levert de volledige lijst (78 administraties) — Peter beslist per administratie, `btw-plichtig-zetten` of de UI.
2. RLZ-gedrag bij een PUT zonder `TaxRate` in een niet-btw-plichtige administratie is niet gemeten (VGG heeft de vrijgestelde code, dus
   het pad "zonder TaxRate" treedt daar niet op).
3. Bank-direct-boekingen (`bank/boeken.py`) en de bank-formulieren volgen de grootboek-default en zijn niet aangepast — in VGG lopen
   bankboekingen via de Odoo-migratie; bij een tweede niet-btw-plichtige RLZ-administratie is dat een vervolgpunt.

## Gelezen regels

- `docs/regels/btw.md` (206 regels)
- `docs/regels/administraties-instellingen.md` (137 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (401 regels)
- `docs/regels/bank.md` (116 regels)
- `docs/regels/reconciliatie.md` (255 regels)
