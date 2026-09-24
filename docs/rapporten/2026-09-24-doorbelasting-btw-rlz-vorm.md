# Doorbelasting — btw per tarief over het subtotaal (RLZ-vorm) + data-stap + factuur-PDF-herstel (24-09-2026, avond)

**Opdracht:** `opdrachten/gedaan/2026-09-24-doorbelasting-btw-per-tarief-over-subtotaal-rlz-vorm-plus-data-stap-en-factuur-pdf-herstel.md`
(akkoord Peter 24-09 "3. ja"; handmatige CC-sessie). Geldlogica: stap 1 (bewijs) vóór élke codewijziging; niets in RLZ gecorrigeerd of
herboekt; het gewone inkooppad alleen geteld.

**Werkt in productie: NIET GEMETEN** (de code staat pas ná deploy op de job-image; de data-stap schrijft pas ná Peters "ja" op de
dry-run-telling). Stap 1 is wél een productiemeting (lees-only, 183 RLZ-records) en die is 100 % groen. Meetrecept en vervolg-opdracht
onderaan.

## Samenvatting

| Stap | Uitkomst |
|---|---|
| 1 — bewijs RLZ-rekenregel (lees-only) | **166/166 meetbare productiedocumenten volgen exact één regel** (85 doorbelastingsverkopen KF, 49 spiegels in 5 doelen, 32 gewone inkoopfacturen KF + BLOw waarvan 15 mét twee tarieven); 0 afwijkingen → fix mag. Volledige tabel: `verkenning/stap0-doorbelasting-btw-rekenregel-24-09.tsv` (183 rijen). |
| 2 — fix motor | `geld.btw_rlz_vorm` (+ `btw_rlz_vorm_per_tarief`), motor + spiegel-alsnog + preview uit dezelfde functie; 34 geld-tests incl. property-test; Lusso 4.741,55 + 237,08 → 995,72 / 49,79 = **1.045,51 / 6.024,14** (was 995,73 + 49,79 = 1.045,52). |
| 3 — data-stap | CLI `doorbelasting-bedragen-gelijktrekken [--dry-run] [--uitvoeren] [--administratie]` — alleen onze database, RLZ alleen GET. **Verwachte dry-run-telling (uit stap 1): 188 geboekte doorbelastingen, 133 gelijk, 55 cent-verschil ≤ € 0,05 (54 × 1 ct, 1 × 2 ct), 0 afwijkingen, 0 boekstand-events** (geen enkel cent-geval ligt in een vastgoed-doel). Echte run = ná Peters "ja". |
| 4 — factuur-PDF | `doorbelasting-facturen-herstel` blijft het herstelpad (verwachting ná stap 3: 55 + 2 nooit-geprobeerd hersteld; **1 échte lay-out-/formaatfout blijft: de creditdoorbelasting 24713270, zie §4**); nieuwe bevinding `doorbelasting_factuur_pdf_ontbreekt` (> 1 dag, meten) mét knop "Factuur-PDF herstellen". |
| Extra | Reconciliatieblok `doorbelasting` toetst nu ook de bedragen module ↔ RLZ (verkoop én spiegel): > € 0,05 of verkoop ≠ spiegel = `doorbelasting_bedrag_afwijking` (actie, besluit Peter in de opdracht); ≤ € 0,05 = INFO-regel + data-stap. |

## Stap 1 — de RLZ-rekenregel, bewezen op productie (lees-only)

**Bron:** `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh rlz-lezen --pad <Collectie>/<guid> --expand 'DocumentLineList($expand=TaxRate)'`
op de gedeployde job-image `1995edd` (183 job-executies, alleen GET, ~45 s per stuk, 8 parallel). De GUID's kwamen uit onze eigen
registratie (leesreplica `db_lezen.sh`, RLS-scope Kempen Facilities: `doorbelasting_boeking.verkoop_rlz_id`/`spiegel_rlz_id`; gewone
inkoop: `uuid5(namespace, document_id)` bij `boek_cyclus` 0) — zo hoefde de anonimisering van `rlz-lezen` niet omzeild te worden.
Percentages: doorbelasting = het vlakke 21 %-tarief van de instelling; inkoop = `taxrate_cache.percentage` van de module.

**Selectie (183 records):** álle 55 geboekte KF-doorbelastingen mét een verschil per-regel ↔ factuurniveau, alle 5 exacte-halve-gevallen,
de creditdoorbelasting, alle 19 verkopen mét ≥ 3 regels en 5 consistente controlegevallen (= 85 verkopen); 49 spiegels daarvan in
Veldhoven Recreatie (14), Oirschot Recreatie (14), Molenhof Verhuur (13), Molenhof Beheer (5), Mantelzorgwoningen Midden (2), Rubicon (1);
49 gewone module-inkoopfacturen mét ≥ 2 regels (KF 30, BLOw 19: alle 30 mét ≥ 2 tarieven, alle mét een per-regel/per-tarief-verschil,
alle 5 mét een negatieve regel, 6 controlegevallen).

**De regel (geformuleerd en getoetst):**

1. **Document-btw per tarief** = `ROUND_HALF_UP(Σ netto van de regels mét dat tarief × tarief)`; document-btw = Σ over de tarieven.
   Getoetst: 85/85 verkopen, 49/49 spiegels, 32/32 inkoopfacturen mét bekende percentages (17 inkoopfacturen hebben een regel zonder
   percentage in onze cache — verlegd/0 %-code of één regel meer in RLZ dan bij ons — en zijn buiten de telling gelaten, niet
   tegengesproken: hun 0 %-regels dragen in RLZ `TaxAmount` 0,00).
2. **Afronding = half-up, geen bankers:** 10 exacte-halve-gevallen (subtotaal × 21 % eindigt op ,xx5: 682,50 → 143,325; 1.942,50;
   2.362,50; 234,50; 2.026,50; 974,50 + 339,18 à 9 %) — RLZ legt telkens de half-up-waarde vast (143,33; half-even zou 143,32 geven).
3. **RLZ negeert de meegegeven regel-`TaxAmount` en herrekent per regel:** élke regel krijgt `ROUND_HALF_UP(netto × tarief)`, behalve de
   **grootste regel** (|netto|; bij gelijke grootte de eerste) van dat tarief, die het verschil met de document-btw draagt. Lusso: wij
   stuurden 995,73 + 49,79; RLZ legde 995,72 + 49,79 vast (verkoop `RLZ-01-00002726` én spiegel `RLZ-04-00000614`, beide 6.024,14).
   Getoetst tegen drie alternatieven: "eerste regel draagt het verschil" faalt op 5 verkopen + 4 inkoopfacturen (bv. V-24713352:
   375 / **3.840** / 409,50 / 221 / 242,28 → RLZ 78,75 / **806,39** / 86,00 / 46,41 / 50,88); "grootste-rest-methode" faalt op 23
   verkopen + 7 inkoopfacturen; "laatste regel" faalt op 55 + 6. **Grootste-regel klopt op 166/166.** Gelijke grootste regels
   (139,50 + 139,50, boekstuk RLZ-04-00004327): RLZ 29,29 + 29,30 = 58,59 → de eerste draagt het verschil; ook bij −0,02 op één regel
   (V-24713368, 8 regels: 1.986,96 → 417,24 waar 417,26 "hoort").
4. **Negatief:** creditdoorbelasting V-24713270 (−300 + −15) → −63,00 / −3,15 = −66,15; correctieregels (−1,00 / −2,00 / −0,70 / −0,80 à
   21 %) → −0,21 / −0,42 / −0,15 / −0,17 en de grootste (positieve) regel draagt het verschil — 6/6. Een exacte negatieve helft kwam niet
   voor; `ROUND_HALF_UP` van `Decimal` (weg van nul) is de aanname.
5. **Spiegel = verkoop:** in 49/49 paren zijn regel-`TaxAmount`, `TotalTaxAmount` en `TotalPayableAmount` van de spiegel identiek aan de
   verkoop.

**Wat dit voor de module betekent:** een `TaxAmount` die wij meesturen heeft géén effect op wat RLZ vastlegt. De fix maakt dus niet RLZ
anders, maar ónze registratie, factuur-PDF-toets en webhook gelijk aan RLZ — en wat wij sturen is voortaan ook letterlijk wat RLZ
berekent (nooit meer een afgekeurde eerste regel).

### Het gewone inkooppad — alleen geteld (fix = aparte beslissing Peter)

49 module-inkoopfacturen mét ≥ 2 regels (KF 30, BLOw 19) gelezen:

| Vergelijking | Aantal |
|---|---|
| RLZ-btw = onze registratie (Σ `boekvoorstel_regel.btw_bedrag`) | 35 |
| RLZ-btw ≠ onze registratie, **1 ct** (per-regel-afronding, zelfde patroon als de doorbelasting) | **10** (9 × RLZ 1 ct lager, 1 × hoger) |
| RLZ-btw ≠ onze registratie, méér dan 1 ct | 4 (−0,03; −0,25; +0,96; +47,13 — onze regel-btw was daar handmatig/onvolledig geregistreerd: `null`-btw op twee regels, een afgeronde regel van 762,00 i.p.v. 762,96; RLZ rekende gewoon door) |
| RLZ-totaal incl. = het factuurtotaal van de module | 40 |
| RLZ-totaal incl. ≠ factuurtotaal, **1 ct** | **7** (6 × RLZ 1 ct lager, 1 × hoger) |
| RLZ-totaal incl. ≠ factuurtotaal, méér | 2 (−0,25 en +0,97: RLZ-89-00004398, factuur 20.959,79 vs RLZ 20.960,76) |

**Bevinding voor Peters beslissing:** het gewone inkooppad kent hetzelfde cent-gat (≈ 1 op 7 multi-regel-facturen), én de cent-fix aan de
bron (`regelsom.py::corrigeer_btw_centen`, 15-09 — verschuift het verschil in de laatste btw-dragende regel) **kan per definitie niet
werken**: RLZ negeert onze `TaxAmount`. Wil je dat het RLZ-totaal exact het factuurtotaal is, dan kan dat alleen via het NETTO van een
regel (bruto-splitsing), óf je accepteert het 1-cent-verschil zoals nu (automatische acceptatie ≤ € 0,05 in de reconciliatie, 15-09).
Niets gewijzigd in `regelsom.py` (opdracht). De vier grotere gevallen zijn registratiekwaliteit van oude regels, geen motorfout.

## Stap 2 — fix in de doorbelastingsmotor

- `app/doorbelasting/geld.py`: `btw_rlz_vorm(nettos, pct) → (document_btw, btw_per_regel)` exact de bewezen regel (half-up, grootste
  regel draagt het verschil); `btw_rlz_vorm_per_tarief` voor gemengde tarieven (algemene vorm, 15/15 inkoopfacturen); `btw_over` blijft
  voor één regel (valt samen). Moduledocstring = de regel + bewijsverwijzing.
- `app/doorbelasting/boeken.py`: de motor berekent ÉÉN keer `btw_rlz_vorm([kostenregels…, provisie])` en gebruikt die voor de
  verkoopregels, de spiegelregels (`_spiegel_regelspec(btw_per_regel=…)`), de registratie (`btw_bedrag`), de `FactuurVerwachting` én de
  webhook-regelspec; het inhaalpad `boek_spiegel_alsnog` idem. `service.review_data` (preview op het scherm) uit dezelfde functie.
- Chip-tekst: ontbreken alleen bedragen in de PDF-toets, dan zegt de reden "de RLZ-factuur toont andere centen dan de module
  registreerde … eerst doorbelasting-bedragen-gelijktrekken" i.p.v. "lay-out aanvullen" (`factuur.factuur_herstel_advies`);
  `factuur_pdf_toets` leest beide adviesvormen.
- Tests: `test_geld.py` (34 — Lusso, verschil omhoog, grootste-niet-eerste, −0,02, gelijke grootste, 4 exacte halven, credit, één regel,
  provisie 0, property-test 2.000 willekeurige regelsets: Σ regel-btw == document-btw én élke niet-grootste regel exact afgerond, twee
  tarieven), `test_boeken.py::TestRlzVorm24_09` (Lusso end-to-end: gestuurd = RLZ = registratie = 1.045,51, factuur-PDF `aanwezig`; V-24713352
  vijf regels), de fake RLZ-client speelt het bewezen RLZ-gedrag na (regel-herrekening + kop-totalen; les 21-09 "een stub speelt het
  bewezen gedrag van de bron na"). Bestaande motor-tests ongewijzigd groen (100 + 5 → 22,05 valt samen).

## Stap 3 — data-stap `doorbelasting-bedragen-gelijktrekken` (alleen onze database)

`app/doorbelasting/bedragen_gelijktrekken.py`, CLI in `app.cli`, nameting-allowlist (alleen zónder `--uitvoeren`), dispatch-onderdeel
`doorbelasting-btw`. Per geboekte doorbelasting (`geboekt` + `spiegel_open`): GET verkoop (bron) + GET spiegel (doel) → `toets_bedragen`
(zelfde functie als het reconciliatieblok, tolerantie € 0,05, plus RLZ-netto = onze netto + provisie): gelijk / cent-verschil (→ met
`--uitvoeren`: `btw_bedrag` := RLZ-btw, audit `doorbelasting_bedrag_gelijkgetrokken` oud → nieuw mét beide RLZ-id's en boekstuknummers,
één tijdlijnregel op het bron-document die verkoop én spiegel noemt — de spiegel heeft in de module geen eigen documentrij —, en voor een
vastgoed-doel een nieuw `factuur_geboekt`-boekstand-event (volgnummer + 1) mét de regels in de RLZ-vorm) / afwijking (> € 0,05,
verkoop ≠ spiegel of netto ≠) = niet aangepast / niet leesbaar. Dry-run default. Nooit een write in RLZ (tests bewijzen 0 PUT's/acties).
Tests `test_bedragen_gelijktrekken.py` (dry-run schrijft niets; uitvoeren + audit + tijdlijn + idempotent; vastgoed-doel → event volgnummer 2
mét 21,00/1,05; afwijking blijft staan; 404 = niet leesbaar; élke CLI-argumentvorm letterlijk via `cli.main`; payload-helper).

**Verwachte dry-run-telling (afgeleid uit stap 1 — de échte telling komt van de job-image ná deploy):**

| | Aantal |
|---|---|
| Geboekte doorbelastingen Kempen Facilities (25-08 … 24-09) | 188 (+ 8 gestorneerd, niet in de stap) |
| Gelijk aan RLZ | 133 |
| Cent-verschil ≤ € 0,05 → zou gelijktrekken | **55** (54 × 1 ct, 1 × 2 ct: 24713368, 8 regels; Σ module − RLZ = + € 0,08) |
| Afwijking > € 0,05 of verkoop ≠ spiegel | 0 (49/49 gelezen spiegels = verkoop) |
| Boekstand-events vastgoed | 0 — de 3 Rubicon-doorbelastingen (het enige vastgoed-doel) zijn alle drie gelijk aan RLZ → **Vastly heeft nooit een payload met 1 cent te veel ontvangen**; het OPEN_ITEM uit blok 4 vervalt |
| Per doel (cent-gevallen) | Veldhoven Recreatie 26, Molenhof Verhuur 12, Oirschot Recreatie 11, Molenhof Beheer 4, Mantelzorgwoningen Midden 2 |

Betaalconsequentie (blok 4 punt 3 blijft): bij de 55 open spiegels is het RLZ-bedrag het te betalen bedrag (bv. Molenhof Verhuur
RLZ-04-00000614 € 6.024,14), niet het oude module-bedrag.

## Stap 4 — factuur-PDF-herstel

- Ná de data-stap zet `doorbelasting-facturen-herstel` (bestaand, dry-run eerst) de factuur alsnog op beide kanten: de toets vergelijkt met
  de dan gelijkgetrokken registratie. Kantoorbrede telling van vandaag (job-image, lees-only): **58 zonder factuur-PDF = 54 `onvolledig_cent`
  + 1 × 2 ct (`onvolledig_anders` 24713368) + 2 `overig` (nooit geprobeerd: 24713195 TEST-ONB Rubicon, 24713206 Veldhoven — boekingen van
  vóór blok A 26-08) + 1 échte niet-cent-fout.**
- **Échte lay-out-/formaatfout (apart benoemd):** creditdoorbelasting 24713270 (Veldhoven Recreatie, −300,00 + −15,00, btw −66,15 =
  factuurniveau): de toets zoekt "€ -66,15" en "€ -381,15" in de PDF-tekst en vindt ze niet — RLZ rendert negatieve bedragen kennelijk in
  een ander formaat (teken achter het bedrag of tussen € en getal). Geen cent-geval; herstel vraagt een aanpassing van de tekst-toets voor
  creditnota's (formaatvarianten toestaan) — niet in deze run gedaan (buiten de opdracht), klikpunt/vervolg.
- Reconciliatieblok `doorbelasting`: een geboekte doorbelasting zonder `factuur_pdf_status = aanwezig` ouder dan 1 dag =
  `doorbelasting_factuur_pdf_ontbreekt` (start in `meten`, regel 2) mét handeling **"Factuur-PDF herstellen"** op de rij
  (`POST /reconciliatie/doorbelasting/{boeking_id}/factuur-herstellen`, kantoorrol + scope; `factuur_herstel.herstel_boeking` = exact het
  bestaande herstelpad voor dít record; 422 = reden op de rij én op de boeking). Frontend `FactuurPdfHerstellenActie.tsx` (+ vitest 3),
  wiring in `ReconciliatieScreen`, leesbare tekst in `teksten.py`.

## Reconciliatie — bedragtoets in het dagelijkse blok

`reconcilieer_doorbelasting` leest bij dezelfde GET's nu ook `TotalPayableAmount`/`TotalTaxAmount`/`TotalNetAmount` van verkoop en
spiegel: > € 0,05 of verkoop ≠ spiegel = `doorbelasting_bedrag_afwijking` (**actie**, `direct_actie_reden` = besluit Peter in de opdracht;
guard-lijst in `test_soort_stand.py` bijgewerkt); ≤ € 0,05 = teller `centverschillen` + CLI-regel `INFO … nazorg
doorbelasting-bedragen-gelijktrekken` (geen bevinding — anders 55 rijen in de actiemail vóór Peters "ja"). Detail draagt
`rlz_verkoop_incl`/`rlz_spiegel_incl` voor de tekst. Tests `test_reconciliatie_bedragen.py` (pure toets, blok mét fake RLZ: gelijk /
cent-teller / afwijking mét tekst / verkoop ≠ spiegel / factuur-PDF > 1 dag).

## Poort

- **Volledige backend-suite: 7481 passed, 1 skipped, 1 failed (55:00)** — de ene rode was de guard `test_rapporten_gelezen_regels`
  op de vorm van de sectie "Gelezen regels" in dít rapport én in het rapport `2026-09-24-webhook-herzenden-uitgevoerd.md` van de andere
  sessie (beide zonder "`docs/regels/<domein>.md` (N regels)"); beide secties zijn in de vereiste vorm gezet (in het andere rapport alleen
  de vorm, inhoud ongewijzigd). Daarna opnieuw: guards (`test_rapporten_*`, `test_claude_md_*`, `test_regels_index`, `test_keten_guard`,
  `test_nameting_workflow`) + `test_soort_stand` + `tests/doorbelasting`: **331 passed** — dit dekt óók de lint-refactor van
  `bedragen_gelijktrekken.py`/`reconciliatie.py` die ná de start van de volledige suite is gedaan (alleen imports/één `if`).
- Eerder per map: `tests/doorbelasting` + `test_soort_stand` + `test_rol_endpoint_gates` + `test_cli_smoketest` + `test_run`: 818 passed;
  `test_nameting_workflow`: 60 passed; `test_deploy_drift` + `test_cli_smoketest`: 36 passed (bijvangst hieronder).
- frontend: `tsc -b` exit 0; vitest **264 files / 1979 tests passed** (incl. de nieuwe actie-test).
- Gouden set: `tests/keten` zit in de volledige suite; geen wijziging onder `app/intake`, `app/extractie`, `app/documenten` of
  `frontend/src/document` → de pixel-sweep is niet opnieuw gedraaid (ongewijzigde exports).
- Geen migratie.

## Bijvangst — deploy-drift-toets rood door Jarvis-jobs in hetzelfde GCP-project (gefixt)

De laatste twee deploys van vandaag (`8fc1cd3`, `5a9be94` — de webhook-herzenden-sessie) eindigden ROOD op de post-deploy-smoketest:
"service en jobs niet op hetzelfde beeld: 4 van 22 job(s) achter op de service … jarvis-bex-sync, jarvis-migratie, jarvis-signalen,
jarvis-uva-sync op edfc268" — Jarvis deployt sinds 24-09 zijn jobs (beeld `jarvis/backend:…`) in project `rlz-boekhouding`, en de
drift-toets (`app/bewaking/deploy_drift.py`, 11-09) vergeleek élke job in de locatie met het RLZ-servicebeeld. Gevolg: de RLZ-code zélf
stond wél live (jobs op `5a9be94`), maar de deploy meldde rood + mail naar beheer, en de kwartier-probe `deploy_drift` gaf sinds 20:30 UTC
`fout` (alert ná twee metingen). Fix in deze run (klein, met guard-test): `lees_stand` telt alleen jobs uit hetzelfde beeld-repo als de
service (`beeld_repo`: pad zonder tag/digest); jobs uit een ander repo staan als "buiten beschouwing: N job(s) uit een ander beeld-repo:
jarvis-…" in de samenvatting. Verwachting ná deploy: smoketest groen, probe `deploy_drift=ok`, herstelmelding. **Werkt in productie:
niet gemeten** (zichtbaar in de deploy-run van deze commit).

## Meetrecept ná deploy (dispatch-onderdeel `doorbelasting-btw`)

`gh workflow run nameting -f onderdeel=doorbelasting-btw` → bot-bestand `verkenning/nameting-doorbelasting-btw-<dd-mm>.txt`:
(1) `doorbelasting-bedragen-gelijktrekken --dry-run` kantoorbreed → **verwacht: TOTAAL 188 · gelijk 133 · cent-verschil 55 (zou
gelijktrekken) · afwijking 0 · niet leesbaar 0 · boekstand-events 0** (plus de doorbelastingen die ná 24-09 avond bijkomen: die horen
gelijk te zijn); (2) `doorbelasting-factuur-pdf-toets` → vóór de herstelrun 58 (54 cent + 1 × 2 ct + 2 overig + 1 credit), ná de
herstelrun ≤ 1 (de credit 24713270); (3) `db-lezen reconciliatie-bevindingen` KF op beide nieuwe soorten. Daarnaast (Peter):
**één nieuwe doorbelasting** (echt geval of testadministratie) → `rlz-lezen --pad SalesInvoices/<verkoop_rlz_id> --expand
DocumentLineList` en `PurchaseInvoices/<spiegel_rlz_id>` in het doel: `TotalTaxAmount` = `doorbelasting_boeking.btw_bedrag` én
`factuur_pdf_status = aanwezig` op de spiegel. Klikvolgorde: deploy → dry-run (dispatch) → Peters "ja" → `gcloud run jobs execute
rlz-reconciliatie --region europe-west4 --args="^|^-m|app.cli|doorbelasting-bedragen-gelijktrekken|--uitvoeren"` → `…|doorbelasting-facturen-herstel|--dry-run`
→ `…|doorbelasting-facturen-herstel` → dispatch opnieuw. Vervolg-opdracht: `opdrachten/inbox/2026-09-25-nameting-doorbelasting-btw-rlz-vorm-na-deploy.md`
(`niet vóór: 2026-09-25 07:15`).

## Klikpunten Peter

1. **"ja" op de dry-run-telling** (verwacht 55 gelijk te trekken, 0 afwijkingen) → echte run + herstelrun (commando's hierboven).
2. Betaling van de 55 open spiegels: het RLZ-bedrag aanhouden (het module-bedrag verschilt 1 ct tot de data-stap).
3. Gewone inkooppad: accepteren van het 1-cent-gat (nu: automatische acceptatie ≤ € 0,05) óf een bruto-splitsing-fix — aparte beslissing.
4. Creditdoorbelasting 24713270: toets voor negatieve bedragen (formaat RLZ-render) — vervolgpunt.

## Aangrenzende gaten (niet gebouwd, wel gezien)

- **`corrigeer_btw_centen` (inkooppad) is dood gewicht t.o.v. RLZ:** RLZ herrekent élke regel-`TaxAmount`; de cent-fix beïnvloedt alleen wat
  wij registreren. Beslispunt 3 hierboven.
- **"Btw in de kosten" in het inkooppad** werkt alleen via een 0 %-`TaxRate` (zo is het gebouwd: `nul_taxrate_voor`) — een `TaxAmount` 0 op
  een 21 %-code zou RLZ terugrekenen naar 21 %. Bevestigd door RLZ-04-00004512 (twee regels `null`-btw bij ons → RLZ 22,18 + 24,95).
- Een `spiegel_open`-boeking draagt tot de data-stap de oude btw; `boek_spiegel_alsnog` boekt de spiegel in de RLZ-vorm en toetst de PDF
  tegen de geregistreerde btw — draai de data-stap vóór een inhaalactie.
- 17 inkoopfacturen mét een regel zonder percentage in onze cache (verlegd/0 %-code of RLZ toont één regel méér: RLZ-89-00004484 12 regels
  vs 11 bij ons — een 0,02-regel) — RLZ zet daar `TaxAmount` 0; niet tegenstrijdig met de regel, wel een teken dat onze regel-cache niet
  altijd 1-op-1 RLZ is.

## Ongecommit werk van een andere sessie (niet aangeraakt)

Bij de start stond ongecommit werk in de werkboom van een andere (Vastly-)sessie: `webhook_afleveraar.py`, `test_webhook_herzenden.py`,
delen van `cli.py`, BESLISSINGEN (alinea 5 webhook-herzenden), gespreksverslag 24-09, `werkvoorraad-controlescherm.md`, WAT_IS_NIEUW
(blok webhook-herzenden). Dat werk is niet van deze opdracht en is bewust NIET gecommit (alleen de eigen hunks zijn gestaged, gedeelde
bestanden via HEAD-herbouw); het staat nog in de werkboom voor de eigenaar.

## Gelezen regels

- `docs/regels/doorbelasting-intercompany.md` (206 regels, stand vóór deze run; nu 220)
- `docs/regels/btw.md` (302 regels)
- `docs/regels/reconciliatie.md` (306 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
- CLAUDE.md; `docs/gesprekken/2026-09-24.md`; `verkenning/api-verkenning.md` (Omzetmodule STAP 0, Factuur-PDF-rendering, BookDate,
  Receipts/SalesInvoices-collectie, enum-filters, TaxRate.Percentage); `app/doorbelasting/geld.py`, `boeken.py`, `factuur.py`,
  `factuur_herstel.py`, `factuur_pdf_toets.py`, `reconciliatie.py`, `service.py`; `app/documenten/regelsom.py::corrigeer_btw_centen`;
  `app/documenten/webhook.py`, `boekstand.py`; `app/reconciliatie/soort_stand.py`, `teksten.py`, `router.py`;
  `docs/rapporten/2026-09-24-bundelrun-zeven-punten.md` blok 4.
