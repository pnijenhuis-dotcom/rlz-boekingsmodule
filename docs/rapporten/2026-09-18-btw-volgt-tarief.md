# Rapport 18-09 — Btw-bedrag volgt het tarief; 0 % op een factuur mét btw = btw in de kosten; harde check mét acties; BUA-kenmerk; btw-keuzelijst NL-eerst (Peter 18-09, casus Rituals 88-186308)

Opdracht: `opdrachten/gedaan/2026-09-18-btw-bedrag-volgt-tarief-harde-check.md` (DEEL A + DEEL B). Domeinen: btw,
werkvoorraad-controlescherm, autoboeken-ai, kantoor-frontend. Migratie **0163** (`platform.grootboekrekening.btw_aftrek_uitgesloten`
+ `btw_aftrek_uitgesloten_op`). Gebouwd + getest 18-09-2026 (inbox-run 3, agent B, eigen test-DB `boekhouding_test_a3`).

**Werkt in productie: NIET GEMETEN** — een deploy binnen de run bestaat niet; meetrecept onderaan.

## Samenvatting (één regel voor Peter)
Kies je nu 0 % op een regel mét btw, dan gaat de btw in de kosten (116,60 / 0,00) en past het btw-bedrag altijd bij de code; past het niet,
dan blokkeert de nieuwe controle "Btw-bedrag past bij tarief" mét twee knoppen; rekeningen als 4510 kun je in Beheer als "btw niet
aftrekbaar" aanvinken (voorstel staat klaar, jij bevestigt), en bij een Nederlandse leverancier zie je alleen de NL-btw-codes.

## Feiten eerst (lees-only, leesreplica `rlz-sql2-lees` via `scripts/gcp/db_lezen.sh`, per administratie — RLS)
- **Rituals 88-186308 (BLOW, document `e726bcf6-642a-4f34-8802-30201903efb0`)**: geüpload 18-09 11:07 (mail, "tenaamstelling niet
  eenduidig" → verzamelbak → toegewezen), extractie 11:08 (6 regels, alle `btw_afleiding_reden: onbepaalbaar`, regels zijn
  bruto-bedragen, totaal_incl 116,60), kop-omschrijving handmatig 11:37:37, klaar_om_te_boeken 11:38:23, **geboekt 11:38:24 in RLZ
  als boekstuk RLZ-04-00000362** mét de gewenste stand: 4510, "NL, Nul tarief", netto 116,60, btw 0,00 (samengevoegd, 6 regels).
  **Herkomst van de 0 %:** géén prefill-snapshot-gebeurtenis (geen geheugen-/default-trigger), géén boekingsobservatie vóór 18-09 (de
  enige observatie Rituals is Peters boeking zelf, RLZ-04-00000362), 4510 "Representatiekosten (beperkt aftrekbaar)" zonder RLZ- én
  zonder historie-default → **de mens koos 0 % en het scherm herrekende niet** (frontend: `btwHandmatig` stond vast op een geladen
  regel mét btw → tariefwijziging liet 96,36/20,24 staan) — precies de bug van regel 1; Peter corrigeerde daarna zelf naar 116,60/0,00.
  Tweede Rituals-bon in BLOW: `c0182d2a-02dd-4942-8f8b-d20d81a0a1df` (143-266923, 19-12-2025), klaar_om_te_boeken, 4510 NL Nul
  tarief, 59,00 / 0,00 (samengevoegd, 4 regels).
- **BLOW btw-codes** (22): 10 EU/Ex-EU (alle `IsRelayed`), 2× NL verlegd, NL Nul tarief, NL Geen BTW (Vrijgesteld), Hoog/Laag (+
  achteraf/vooruit-varianten), Auto tarief 12 %, "BTW-bedrag zelf specificeren" — de nameting verwacht dus "Buitenland-tarieven tonen (10)".
- **Historie-lijst (regel 5)** — geboekte inkoopdocumenten sinds 25-08 mét |btw − netto × p| > 0,05 over alle 77 actieve
  administraties: **alleen BLOW, twee documenten** (zie Klikpunten). Alle overige administraties: 0 regels.
- **BUA-voorstellijst** — in álle 77 actieve administraties dezelfde drie rekeningen zonder RLZ-default: 4014 Kantinekosten,
  4508 Relatiegeschenken (beperkt aftrekbaar), 4510 Representatiekosten (beperkt aftrekbaar) (Veldhoven Recreatie: alleen 4508).
  Niets is aangezet — Peter bevestigt per administratie in Beheer (of via het beslispunt bulk).

## Gedaan / niet gedaan

| # | Onderdeel | Stand |
|---|---|---|
| A1 | Btw-bedrag volgt het tarief (altijd herrekenen, tijdlijnregel) | GEBOUWD — `regelsom.py` (`btw_uit_tarief`, `marge_voor`, `btw_past_bij_tarief`, `zet_btw_in_kosten`, `splits_bruto`, `bruto_uit_netto`, `verklarende_percentages`) + spiegel `document/regelsom.ts`; `BoekvoorstelPanel.wijzigRegel` tak `taxrateId` herrekent ALTIJD (`herrekenBtwBijTarief`); server tijdlijn-notitie `btw_herrekend` (`boekvoorstel._btw_herrekend_notities`, niet op autosave) + rendering `btwHerrekendTijdlijn.ts` in het detailscherm |
| A2 | 0 % op een regel mét btw = btw in de kosten; terug naar 21 % splitst weer; verlegd blijft verlegd | GEBOUWD — `RegelState.btwInKosten` + chip "btw in kosten (niet aftrekbaar)", DTO `btw_in_kosten` (regel + snapshot-herstel), `splitsBruto` cent-exact |
| A3 | Harde check "Btw-bedrag past bij tarief" mét acties "Btw in kosten (0 %)" / "Zet N %"; hint weg | GEBOUWD — `checks.check_btw_past_bij_tarief` + `TariefInfo`/`CheckActie`/`nul_tarief_voor`, in `voer_harde_checks_uit` én de storings-tak (lokaal; autoboek-pad rood = niet boeken); DTO `acties`; frontend knoppen in de controles-tabel (`voerCheckActieUit`); `regel-btw-berekend-hint` + `BTW_AFRONDINGSMARGE` verwijderd, guard in casus ae |
| A4 | BUA-kenmerk + Beheer-scherm + prefill-stap | GEBOUWD — migratie 0163 (kolom op `platform.grootboekrekening`; motivatie in de migratie-docstring), `app/beheer/btw_aftrek.py` + `GET/PUT /administraties/{id}/btw-aftrek-uitgesloten` (Beheerder, audit oud→nieuw, 422), blok `instellingen/BtwAftrekUitgeslotenBlok.tsx` op tab Boeken & AI (anker `btw-aftrek`, registry-entry, harness-mock), prefill-stap `grootboek_aftrek_uitgesloten` vóór factuur-berekend (`regel_prefill._met_aftrek_uitgesloten`, chip "aftrek uitgesloten (4510)") |
| A5 | Historie (lees-only) | GEBOUWD — CLI `btw-tarief-afwijking-rapport` (nameting-allowlist) + de lijst hierboven via de leesreplica |
| B1 | `leverancier_land` + bron op de boekvoorstel-respons | GEBOUWD — `app/documenten/btw_keuzelijst.py` (kenmerk → factuur-btw-nummer → IBAN factuur → vertrouwde IBAN-set → onbekend); chip in de crediteur-kaart. **Factuuradres-land NIET gebouwd** (geen adresveld in het inkoop-extractieschema; nieuw AI-veld = schema-uitbreiding — beslispunt) |
| B2 | Keuzelijst NL → NL-tarieven, buitenland ingeklapt "Buitenland-tarieven tonen (N)"; ≠ NL alles mét land/EU bovenaan; onbekend alles; gekozen buitenland-tarief blijft | GEBOUWD — `SearchableCombobox.ingeklapteGroep` (toggle-rij, Enter/klik, pijltjes slaan over, zoeken doorzoekt alles) |
| B3 | Volgorde op gebruik 12 mnd, rest alfabetisch; nul-tarieven op naam | GEBOUWD — `GET …/btw-codes` levert `gebruik_12m` + vlaggen (één statement uit `boeking_observatie`), `useTaxrateOptiesGefilterd.filterEnSorteerTaxrates` |
| B4 | Eén hook op álle tarief-comboboxen | GEBOUWD — inkoop (mét land), verkoop-review, omzet-review, doorbelasting-instellingen, bank-detail en bank-splitsen (zonder land = alleen sortering); prefill/autoboek onveranderd; `check_buitenland_tarief_crediteurkaart` ongewijzigd |

## Tests (eigen test-DB a3; volledige suite = coördinator)
- Backend: `tests/documenten/test_regelsom_btw_tarief.py` (15, pure), `tests/beheer/test_btw_aftrek.py` (4), gouden-set-casus **ae**
  `tests/keten/test_ae_rituals_btw_volgt_tarief.py` (4: zonder kenmerk 21 % groen; mét kenmerk 0 % + 116,60/0,00 + land NL; Rituals-
  stand rood mét twee acties → actie groen, regeltelling sluit, "Zet 21 %" groen; guard hint weg), `test_checks.py` (twee
  verwachtingen uitgebreid mét de nieuwe rij), rolpoort-matrix (+2 routes), `test_migratie_metadata_guard.py`, `test_btw_default_prefill.py`,
  `test_btw_default.py`, `test_boekvoorstel.py` — stand laatste run: zie regel "PYTEST-UITKOMST" onderaan.
- Frontend: `tsc -b` groen over de hele werkboom (18-09 16:24); vitest groen: `regelsomBtwTarief.test.ts`, `useTaxrateOptiesGefilterd.test.tsx`,
  `SearchableCombobox.inklap.test.tsx` (5) + bestaande `SearchableCombobox.test.tsx`, `BtwAftrekUitgeslotenBlok.test.tsx` (3),
  `instellingenRegistry.test.ts`; `BoekvoorstelPanel.test.tsx`: de twee 25-08-tests ("handmatig btw-bedrag nooit overschreven + hint",
  "afrondingsverschil geen hint") zijn HERSCHREVEN naar de 18-09-regel (tarief herrekent altijd; 0 % = in kosten + terug splitsen) en
  groen; `BoekvoorstelPanel.blok4.test.tsx` 4d herschreven (hint bestaat niet meer).
  **Rood, niet door B (vitest 16:25):** `BoekvoorstelPanel.test.tsx` 4 bestaande tests ("vult crediteur/GB/btw-comboboxen … groene
  checks", "fix 3 splitskeuze", "geheugen mislukte voorstel-call", "afdeling prefill") en `DocumentDetailScreen.test.tsx` 9 tests mét
  1–4 s timeouts — parallel werkte agent D aan `useAutoChecks.ts` (lokaal/extern-split, +57) en `DocumentDetailScreen.tsx` (+77);
  B raakte in die schermen alleen de tarief-handler/check-acties/land-chip en 6 regels tijdlijn-JSX. Gemeld in `verzoeken_D.md`;
  coördinator herdraait ná D.
- Overflow-sweep (POORT 5202): harnas `harness-instellingen.html?…&tab=boeken-ai` (2 varianten × 4 breedtes × licht/donker) = **16
  metingen groen** mét het nieuwe BUA-blok (harness-mock toegevoegd). Het controlescherm zit niet in `overflow_sweep.sh` maar in de
  keten-pixelsweep (`frontend/scripts/keten_sweep.sh`): de controles-tabel krijgt een extra rij → baselines bewust verversen door de
  coördinator (niet door B gedaan).
- Ruff: `ruff check` schoon op B's bestanden; `ruff format` alleen op de NIEUWE bestanden.

## Migratie-routine (door de coördinator af te ronden)
Migratie 0163 staat compleet (schema-only, pure DDL; model-kolommen in `app/db/models.py::Grootboekrekening`; `test_migratie_metadata_guard`
groen op a3). Nog te doen door de coördinator: `make migrate` tegen de dev-DB (upgrade-output tonen), live-200 op
`GET /administraties/{id}/btw-aftrek-uitgesloten` (Beheerder-token), `scripts/dump_schema.sh` vanuit de repo-root ná de volledige suite,
docs/INDEX/BESLISSINGEN/CLAUDE.md/WAT_IS_NIEUW uit `regels_B.md`, `beslissingen_B.md`, `claude_md_B.md`, `watisnieuw_B.md`.

## Geraakte bestanden (B)
Backend: `app/documenten/regelsom.py`, `checks.py`, `boekvoorstel.py` (`_taxrate_info`, `_samengevoegd_n`, `btw_in_kosten`, `_btw_herrekend_notities`, storings-tak), `regel_prefill.py` (BUA-stap), `router.py` (acties-DTO, `_met_leverancier_land`, `btw_in_kosten`), `schemas.py`, `btw_keuzelijst.py` (nieuw), `btw_tarief_cli.py` (nieuw), `app/beheer/btw_aftrek.py` (nieuw) + `beheer/router.py`, `app/sync/router.py` + `sync/schemas.py` (btw-codes vlaggen/gebruik), `app/db/models.py`, `app/cli.py` (2 regels), `migrations/versions/0163_…`, `scripts/gcp/nameting.sh` (allowlist); tests: `test_regelsom_btw_tarief.py`, `test_btw_aftrek.py`, `tests/keten/test_ae_rituals_btw_volgt_tarief.py` + fixture `ae_rituals_bua_0pct/` + `casussen.py`, `test_checks.py`, `test_boekvoorstel.py`, `test_rol_endpoint_gates.py`.
Frontend: `api/types.ts`, `document/regelsom.ts`, `regelVoorstelChips.ts`, `useSyncOpties.ts`, `SearchableCombobox.tsx`, `useTaxrateOptiesGefilterd.ts` (nieuw), `btwHerrekendTijdlijn.ts` (nieuw), `BoekvoorstelPanel.tsx`, `DocumentDetailScreen.tsx` (6 regels), `instellingen/BtwAftrekUitgeslotenBlok.tsx` (nieuw), `AdministratieDetailPagina.tsx`, `instellingenRegistry.ts`, `dev/visueelHarnasInstellingen.tsx`, `verkoop/VerkoopReviewScreen.tsx`, `omzet/OmzetReviewScreen.tsx`, `doorbelasting/DoorbelastingInstellingen.tsx`, `bank/Splitsen.tsx`, `bank/BankDetailScreen.tsx`; tests: `regelsomBtwTarief.test.ts`, `useTaxrateOptiesGefilterd.test.tsx`, `SearchableCombobox.inklap.test.tsx`, `BtwAftrekUitgeslotenBlok.test.tsx`, `BoekvoorstelPanel.test.tsx` (2 herschreven), `BoekvoorstelPanel.blok4.test.tsx` (2 aangepast).

## Klikpunten Peter
- Beheer › Instellingen › Administraties › **BLOw B.V** › Boeken & AI › blok "Btw niet aftrekbaar": "Voorstel overnemen (3)" (4014, 4508,
  4510) → Opslaan. Idem voor de andere administraties waar Peter dat wil (alle 77 hebben hetzelfde voorstel) — of het beslispunt bulk.
- Historie BLOW (regel 5, bron `db-lezen` leesreplica 18-09, beide geboekt 18-09, niets gecorrigeerd — Peter beslist: storno 19 →
  herboeken, achter de aangiftepoort):
  - RLZ-04-00000357 (18-09-2026 11:33, btw € 48,18 op netto € 632,52 — verwacht € 56,93, verschil € −8,75; bron leesreplica `db-lezen`):
    document `c9e69471-beb3-4e97-8008-279f8b40ec26`, referentie Fac-25-023465, regel 1 op 7049, "NL, Laag tarief" 9 %.
  - RLZ-04-00000358 (18-09-2026 11:35, btw € 3,37 op netto € 37,48 — verwacht € 7,87, verschil € −4,50; bron leesreplica `db-lezen`):
    document `dfaf9b6f-4b4b-4e74-8c74-dd0fef4c6cb8`, referentie "cb", regel 1 op 7049, "NL, Hoog Tarief" 21 %.

## Beslispunten
- Factuuradres-land als vierde land-bron (AI, lagere zekerheid) = nieuw AI-veld in het inkoopschema (sentinel-patroon, ≤ 16 unions) —
  niet gebouwd; de drie deterministische bronnen dekken NL-leveranciers mét btw-nummer of IBAN op de factuur.
- BUA-voorstel in bulk over álle administraties (Administraties-v2-bulkactie) i.p.v. per administratie — nu per administratie (3 vinkjes).
- De twee BLOW-afwijkingen (hierboven): stornering + herboeking of laten staan.

## Nameting ná deploy (letterlijk)
1. Deploy-check: service én jobs op de commit mét 0163 (`gcloud run services describe rlz-backend …image`, `gcloud run jobs describe
   rlz-migratie …image`), migratie-job-log `Running upgrade 0162 -> 0163`.
2. Controlescherm BLOW, Rituals 143-266923 (`c0182d2a-02dd-4942-8f8b-d20d81a0a1df`, klaar_om_te_boeken, 4510 NL Nul tarief 59,00/0,00):
   controles tonen "Btw-bedrag past bij tarief" GROEN; btw-code-combobox openen → alleen NL-codes + onderaan "Buitenland-tarieven tonen
   (10)"; crediteur-kaart toont "NL · uit btw-nummer factuur" (of IBAN) als de bon een btw-nummer/IBAN draagt, anders geen land-chip
   (dan staat de hele lijst zichtbaar — geen gok).
3. Zelfde document: zet netto 48,76 en btw 10,24 mét 0 % → check ROOD "regel 1: 0 % · NL, Nul tarief met btw € 10.24 op netto € 48.76 —
   verwacht € 0.00" mét knoppen "Btw in kosten (0 %) — regel 1: netto € 59.00, btw € 0,00" en "Zet 21 % — regel 1"; klik "Btw in kosten"
   → 59,00 / 0,00, check GROEN, chip "btw in kosten (niet aftrekbaar)"; tijdlijn toont "Btw herrekend uit tarief — regel 1: btw € 10,24 →
   € 0,00 (btw in de kosten: netto € 48,76 → € 59,00)". Niet boeken (nameting is lees-only op geld).
4. Beheer › BLOW › Boeken & AI › "Btw niet aftrekbaar" toont het voorstel (4014/4508/4510) mét chip "voorstel", teller "0 niet
   aftrekbaar"; ná Peters klik: audit `btw_aftrek_uitgesloten_gewijzigd` (Cloud Logging / `db-lezen`) en op een nieuwe Rituals-bon prefill
   0 % + btw in kosten mét chip "aftrek uitgesloten (4510)".
5. `scripts/gcp/nameting.sh btw-tarief-afwijking-rapport --administratie BLOw` (lees-only) → dezelfde twee regels als hierboven.
Rapportregel: "werkt in productie: ja/nee" per punt.

## Gelezen regels
- `docs/regels/btw.md` (150 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/autoboeken-ai.md` (122 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/intake-extractie.md` (270 regels), `docs/regels/accordering-native-app.md` (321 regels), `docs/regels/duplicaten-crediteuren.md` (119 regels), `docs/regels/uren-planning-veldwerkers.md` (472 regels)
