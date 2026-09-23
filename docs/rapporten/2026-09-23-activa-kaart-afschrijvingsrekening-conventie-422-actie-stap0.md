# BUG activa-kaart (BLOw 23-09) — afschrijvingsrekening conventie code + 1, 422 zonder rekening, `mislukt` ná mens-klik = actie, 404-aanmaakroute STAP-0 deel 1

**Opdracht:** `opdrachten/gedaan/2026-09-24-BUG-activa-kaart-aanmaken-mislukt-geen-afschrijvingsrekening-blow.md` (incl. aanvulling Cowork 23-09 18:3x:
derde fout `PUT FixedAssets/{client-guid}` → 404 `NotFound_FixedAsset`). Uitgevoerd 23-09 avond, interactieve CC-sessie.
**Context:** rapport `2026-09-23-nameting-activa-lees-only-probe.md` stap 4 (BLOw 23619 € 935,00 + 06052 € 680,00 → `mislukt` "geen
afschrijvingsrekening", niemand zag het), BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)".

## Uitkomst in één alinea
De vier punten zijn gebouwd zonder migratie. (1) De afschrijvingsrekening wordt deterministisch voorgevuld: vastgelegd op de koppeling > instelling
per categorie > conventie "code + 1 in dezelfde 0xxx-reeks én naam begint met Afschrijving" (BLOw 0107 → 0108), mét herkomst-chip. (2) Zonder
bekende rekening bestaat "gepland" niet meer: server 422 "Kies een afschrijvingsrekening — RLZ vereist er één per activum", kaart = verplichte combobox
mét rode rand + knop uit. (3) Een `mislukt` ná een mens-klik is de nieuwe bevindingssoort `activum_aanmaken_mislukt_mens`, direct in `actie`, mét
"Opnieuw aanmaken" op de rij (de kaart-route zonder body). (4) De 404 op de PUT toont op de kaart een nette reden; de lees-only STAP-0 op de
aanmaakroute is gedaan en levert twee harde feiten (Help kent alleen `PUT FixedAssets/{id}`; het échte RLZ-activum draagt een KOSTENrekening als
`DepreciationAccount` en start mét een Manual-mutatie) plús een beslispunt; de schrijvende STAP-0 en het herstel van BLOw zijn klikpunten van Peter.
**Werkt in productie: niet gemeten** (vervolg-opdracht `2026-09-24-nameting-activa-kaart-na-deploy.md`, `niet vóór: 2026-09-24 07:15`; dispatch-onderdeel `activa-kaart`).

## Wat er stond (feiten uit de nameting van 23-09, niet opnieuw gemeten)
| document | BLOw | POST aanmaken | koppeling | reden |
|---|---|---|---|---|
| `58b588e8` | 23619, € 935,00 netto op 0107, RLZ-04-00000400 | 23-09 09:43:59 UTC 200 | `mislukt`, mens, `afschrijving_ledger_id` NULL | geen afschrijvingsrekening |
| `4fbda583` | 06052, € 680,00 netto op 0107, RLZ-04-00000459 | 23-09 11:52:54 UTC 200 | idem | idem |
| MK22507863 (Peter, Cowork) | € 1.078,10, 0107, aanschaf 18-12-2025 | kaart liep dóór tot de PUT | `mislukt` | `PUT …/FixedAssets/619639aa-… -> 404 {"Message":"NotFound_FixedAsset"}` |

`activa_instelling.afschrijving_ledgers` BLOw = `{}`; de keuzelijst had acht "Afschrijving …"-rekeningen (0102 … 0116), de mens sloeg de optionele
combobox over; de soort `activum_aanmaken_mislukt` stond in `meten`.

## Gebouwd
1. **Conventie** — `backend/app/activa/afschrijving.py`: `volgende_code` (0107→0108, 0001→0002, 01100→01101; 0999/4400/niet-numeriek → None) +
   `conventie_rekening(balans, rekeningen)`: zelfde administratie, niet verdwenen, geen totaalrekening, soort 3, code = code + 1, naam
   `startswith("afschrijving")` (hoofdletterongevoelig); precies één treffer, anders None. `voorstel.bepaal_afschrijving` = de winnaarsvolgorde
   koppeling > instelling > conventie > leeg; `Kandidaat.afschrijving_bron` + DTO `KandidaatDto.afschrijving_bron` (frontend `activaApi.ts`). Kaart:
   chip "voorgevuld: conventie (code + 1)" / "voorgevuld: uit de instelling" zolang de mens de voorvulling niet overschrijft.
2. **422** — `service.AfschrijvingsrekeningVereist(OngeldigeInvoer)` mét `TEKST_AFSCHRIJVING_VEREIST` (letterlijk in de route-test
   `test_router.py::test_422_…` en in de vitest); geen koppeling, geen audit. Kaart: `SearchableCombobox vereist fout` (rode rand, `aria-required`),
   `role=alert`-tekst, knop `disabled` mét `title`; "Niet activeren…" blijft aan. Vangnet in `maak_aan_in_rlz`: koppeling → instelling → conventie
   (`_conventie_afschrijving`), dus de twee BLOw-koppelingen mét NULL krijgen bij "Opnieuw aanmaken" 0108 mee.
3. **Actie-bevinding** — `reconciliatie.SOORT_AANMAKEN_MISLUKT_MENS` (`MislukteKoppeling.herkomst`; toets kiest de soort per herkomst; detail
   `herkomst`/`koppeling_id`/`document_id`/`regel_volgnummer`), `soort_stand` `activum_aanmaken_mislukt_mens` sinds 24-09 default `actie` mét
   `direct_actie_reden` (derde uitzondering; guard-lijst in `test_soort_stand.py` bijgewerkt), tekst in `teksten.py` ("Activum niet aangemaakt ná uw
   klik"), `kantoorbreed._doel_pad` kent blok activa, frontend `OpnieuwAanmakenActie.tsx` (+ `isActivumAanmakenMislukt`, ook voor de
   automatisch-soort — zelfde handeling) gemonteerd in `ReconciliatieScreen.actieVoor`, `BevindingBlok` + `BLOK_LABEL.activa` = "Activa".
4. **404-route** — `maak_aan_in_rlz` vangt `RlzApiError` 404 op de PUT → `mislukt` mét `REDEN_AANMAAKROUTE_ONBEKEND` ("aanmaken in Reeleezee nog
   niet mogelijk — wordt onderzocht (…404 NotFound_FixedAsset…)"), ruwe fout in `audit.nieuwe_waarde.rlz_body.rlz_fout`; `FakeBoekClient
   faal_op="fixed_asset_put_404"`. De kaart toont `kop.reden` (nette zin, geen `RlzApiError`) en houdt "Opnieuw aanmaken".
5. **Meetlat** — dispatch-onderdeel `activa-kaart` in `.github/workflows/nameting.yml` (if-tak, `options:`, VGG-uitsluiting, `OORDEEL_BRON`) +
   `nameting.sh via_gh_onderdeel` + guard `test_nameting_workflow.py::test_onderdeel_activa_kaart_…`.
6. **Docs** — api-verkenning "FixedAssets — aanmaakroute STAP-0", `docs/regels/activa.md` alinea "BUG 24-09 GEBOUWD", BESLISSINGEN alinea 6 +
   registerrij, CLAUDE.md regel 4 onder Activa, `WAT_IS_NIEUW.md` 23-09, vervolg-opdracht in `opdrachten/inbox/`.

## STAP-0 deel 1 — aanmaakroute FixedAssets (lees-only; volledige tabel in api-verkenning)
- **Help (publiek, 591 kB):** alleen `PUT FixedAssets/{id}` bestaat, beschreven als "Create or Update"; geen collectie-PUT/POST, geen
  `FixedAssets/Actions`, geen aanmaak-`ActionKind` (112 = `DepreciateFixedAsset`). Hypothesen (a) en (b) uit de opdracht vervallen.
- **Record-vorm van een écht activum** (Pilates Bloom nr 1, executie `rlz-reconciliatie-mnjhk`, `--record-via-filter "ReceiptNumber eq '1'"`):
  `BalanceAccount` 0113 (AccountType 3) én **`DepreciationAccount` 4706 Afschrijvingskosten computersoftware (AccountType 2 = kosten)**;
  `FixedAssetMutationList` begint mét **Type 6 Manual, MutationAmount 10.000, BookDate = PurchaseDate**, daarna Type 5 Depreciate à 167/maand;
  `JournalEntryList` één post per maand mét `EventID` 61. `FixedAssetMutation` kent `DocumentReference` (Document) en `Type` 1 Purchase;
  `AssetMutationTypes` heeft óók 7 OpenBalance / 8 StockCorrection.
- **Conclusie/hypothese:** de 404 komt het meest waarschijnlijk doordat een FixedAsset zonder mutatie niet gematerialiseerd wordt (de 21-09-conclusie
  "PUT … respons 204" was nooit getest). Deel 2 (schrijvend) = V0 controle / V1 Purchase-mutatie mét `DocumentReference` / V2 Manual-mutatie / V3
  kostenrekening als `DepreciationAccount`.

## Beslispunten
1. **Welke rekening is `DepreciationAccount`?** De opdracht (en de gebouwde conventie) wijst op de cumulatieve-afschrijvingsrekening op de balans (0xxx,
   BLOw 0107 → 0108 Afschrijving kantoormeubilair); het enige échte activum in een leesbaar register gebruikt een KOSTENrekening (4706). Bewust niet
   geraden: de conventie is exact zoals opgedragen gebouwd, er gaat vóór deel 2 geen write naar RLZ, en V3 in deel 2 beantwoordt het. Valt het
   antwoord op "kosten", dan wordt de conventie "code + 1" vervangen door "4xxx mét naam Afschrijving(skosten) …" én de keuzelijst uitgebreid — een
   losse bouwopdracht.

## Klikpunten Peter
1. STAP-0 deel 2 (schrijvend) op de RLZ-testadministratie `faae29c5` (gearchiveerd sinds 30-08, 0 credentials — dearchiveren mét TESTADMIN-login,
   Boeken AAN, één TEST-ACTIVA-inkoopfactuur ≥ € 450 op 0107 van 2026-09-24): recept in api-verkenning "FixedAssets — aanmaakroute STAP-0" deel 2;
   bron = `rlz-lezen --administratie "Nijenhuis (test)" --pad FixedAssets`.
2. Herstel BLOw ná deploy én ná deel 2: 23619 (RLZ-04-00000400, € 935,00, 23-09, document `58b588e8`), 06052 (RLZ-04-00000459, € 680,00, 23-09,
   document `4fbda583`) en MK22507863 (€ 1.078,10, aanschaf 18-12-2025, PUT-id `619639aa`) → kaart → "Activum aanmaken" (0108 staat voorgevuld);
   meetlat `db-lezen activa-stand --administratie BLOw` rij `koppeling` = `aangemaakt` 3 + `rlz-lezen --administratie BLOw --pad FixedAssets`.
   Vóór de routefix geeft "Opnieuw aanmaken" opnieuw de nette 404-reden (verwacht).
3. Ongewijzigd sinds 21-09: RLZ-recht "Vaste activa" op de webservice-logins van Universal Steigerbouw en Rubicon Investments (register 2 × niet
   leesbaar, `activa_register_niet_leesbaar` in `meten`).

## Verwacht ná deploy (run 24-09 06:30)
Blok `activa` BLOw: 2 (of 3) × `activum_aanmaken_mislukt_mens` in `actie` → actiemail "N zaken vragen je aandacht" mét de rij + knop "Opnieuw
aanmaken"; de oude `activum_aanmaken_mislukt`-rijen sluiten mét audit `reconciliatie_auto_gesloten`. "Opnieuw aanmaken" vóór deel 2 → 200 mét
koppeling opnieuw `mislukt` (nette 404-reden) — zichtbaar op de rij, nooit stil.

## Poort
- pytest volledige suite (tweede run, ná herstel uit de WIP-branch — zie "Procesincident"): 7275 passed / 2 skipped / 1 failed (0:59:58); de ene rode = guard `test_geen_bug_in_klanttekst` op het woord "BUG" in `direct_actie_reden` → tekst aangepast in de vervolg-commit; eerste run (7251 passed) telde niet: die draaide op HEAD ná de reset
- vitest: volledige suite groen (EXIT 0; nieuwe ActivaVoorstelKaart +4, OpnieuwAanmakenActie 4); `tsc -b` schoon (23-09 20:5x).
- gouden set: casus ag draagt de conventie-assert + POST zonder body; keten-sweep: 11/11 groen in één run (0 nieuwe baselines).
- Nieuwe tests: `tests/activa/test_afschrijving.py` (14), `test_service.py::TestBug24_09` (4), `test_reconciliatie.py` (+1, 2 aangepast),
  `test_router.py` (422 letterlijk), `test_soort_stand.py` (guard-lijst), `test_nameting_workflow.py` (+1); vitest `ActivaVoorstelKaart.test.tsx`
  (+4), `OpnieuwAanmakenActie.test.tsx` (4).

## Procesincident tijdens de run (les vastgelegd in memory)
Om 20:59 eindigde de parallel lopende cc-inbox-run "nameting-activa-lees-only-probe poging 2" (gestart vóór deze sessie); zijn poort-stap zag een
vuile werkboom, veegde ÁLLE ongecommitte wijzigingen — mijn backend-edits van dat moment, 16 bestanden incl. het nieuwe
`afschrijving.py` — in `wip/2026-09-23-nameting-activa-lees-only-probe-na-deploy` (`e6ec982`) en deed `reset --hard HEAD`. De eerste volledige
suite draaide daardoor op HEAD (7251 passed, 2 rood op mijn latere test-edits) en was waardeloos. Herstel: `git checkout e6ec982 -- <16 bestanden>` +
`git reset -q`; targeted tests 178 groen; daarna vroeg gecommit (bescherming tegen een tweede sweep) en de suite opnieuw gedraaid. Les: de
inbox-runner neemt bij "poort niet gehaald" ook werk van een interactieve sessie mee (cwd-detectie blind voor een run die al liep) —
`rlz inbox status` bij sessiestart, vroeg committen, en ná een onverklaarbare regressie eerst `git reflog` + `git branch --list 'wip/*'`.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/activa.md` (71 regels — stand vóór de run)
- `docs/regels/reconciliatie.md` (306 regels — stand vóór de run)
- `docs/regels/werkvoorraad-controlescherm.md` (413 regels — stand vóór de run)
- `docs/regels/kantoor-frontend.md` (144 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (332 regels — stand vóór de run)
