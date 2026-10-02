# Boeken moet weer prettig (1) — bijlagen bij de factuur, rustig scherm, samenvoegen, project, overhead, balans (opdracht 02-10, uitgevoerd 02-10-2026)

**Opdracht:** `opdrachten/gedaan/2026-10-02-boeken-prettig-1-bijlagen-bij-factuur-controlescherm-rustig-overhead-automatisch.md`
(besluit Peter 02-10 "nu: 1, 2, 3, 4, 5, 6 — daarna de rest"; feedback letterlijk in `docs/feedback/2026-10-02-controlescherm-feedback-peter.md`,
gesprek `docs/gesprekken/2026-10-02.md`). Handmatige CC-sessie 02-10: punt 1 door de coördinator in de hoofdwerkboom, punten 2, 3 en 4–6
door drie fork-agenten in eigen worktrees (recept 25-09), één commit per punt in Peters volgorde. Migratie **0174** (punt 1).
**Werkt in productie: niet gemeten** — meetlat punt 1 = dispatch-onderdeel `bijlagen-factuur` (`bijlagen-nabundelen --dry-run` kantoorbreed
als bot-bestand; de ÉCHTE nazorgrun pas ná Peters "ja" via Cowork), punten 2–6 = klikpunt Peter op f00117f4 ná deploy; vervolg-opdracht
`opdrachten/inbox/2026-10-03-nameting-boeken-prettig-1.md` (niet vóór 03-10 09:00, hoogstens drie pogingen). BESLISSINGEN-sectie "BOEKEN PRETTIG 1 —
BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)"; regeltekst in `docs/regels/intake-extractie.md` (punt 1),
`werkvoorraad-controlescherm.md` (2, 3) en `verplichtingen-projecten-voorraad.md` (4, 5, 6), alinea's 02-10.

## Samenvatting

1. **Eén mail = één document.** Een niet-factuur-bijlage uit dezelfde mail (huurstaat, specificatie, werkbon, foto, xlsx/csv) wordt geen
   eigen werkvoorraad-rij meer maar hangt aan de factuur: tabbladen in het bijlage-paneel, chip "N bijlagen" in de lijst, extra `/Uploads`
   bij boeken. Herkenning deterministisch vóór élke AI-stap (UBL = factuur; PDF mét tekstlaag mét/zonder factuursignalen; scan = kandidaat
   voor de bestaande AI-route). Meerdere facturen → sleutel-match op factuur-/werknummer, anders bij álle mét "niet eenduidig". Nazorg-CLI
   `bijlagen-nabundelen` (dry-run default) koppelt de al gesplitste documenten; dagteller `bijlagen_gebundeld`.
2. **Rustig scherm.** Groen = niets tonen; alleen een afwijking als één regel onder het veld; "Herkomst tonen" per blok.
3. **Samenvoeg-vinkje terug** — ook onder projectplicht (f00117f4: twee regels → 751,15 / 157,74).
4. **Project nooit uit de historie zonder factuurverwijzing** (wordt aangevuld — zie "Punt 4–6").
5. **Overhead automatisch via de omzetsleutel** (sleutelmaand = maand van de factuurdatum; "Verdelen" overrult).
6. **Balansrekeningen zonder project** (projecteis en verdeling alleen op kostenrekeningen).

## Punt 1 — bijlagen bij de factuur (coördinator)

| Onderdeel | Gebouwd |
|---|---|
| Herkenning | `app/intake/bijlage_herkenning.py`: FACTUUR / KANDIDAAT / BIJLAGE per bijlage (zie regels-alinea 02-10 in `intake-extractie.md`); sleutels uit UBL `cbc:ID` + `cbc:Note`, uit de AI-gelezen factuurnummer van een PDF-factuur (`BijlageResultaat.sleutels`). |
| Mail-regel | `verwerking._verwerk_items_met_bijlagen`: één factuur → alle bijlagen eraan; meerdere → sleutel-match in bestandsnaam/tekstlaag, anders bij álle mét rol `bijlage_niet_eenduidig`; nul facturen → bestaand gedrag; koppelen mislukt → oude route + uitkomst `bijlage_koppelen_mislukt` (nooit stil). Bundeling-stap 3 (24-09) maakt een PDF zonder factuursignalen nooit meer het factuurbeeld. |
| Datamodel | Migratie 0174: `document.samenvoeg_rol` (CHECK 'bijlage'/'bijlage_niet_eenduidig'), `verplaats_document` + policy `document_verplaatsing` nemen bijlage-rijen mee; statusmachine ontvangen/klaar_om_te_boeken → samengevoegd en terug. `app/documenten/bijlagen.py` = enige schrijver (registreer, koppel bestaand document, lijst, bestand, verhuis mee, extra bijlagen voor boeking, ongedaan). |
| Zichtbaar | `DocumentDetailResponse.bijlagen` + `samenvoeg_rol`; route `GET …/documenten/{factuur}/bijlagen/{id}/bestand`; lijst `bijlagen` (chip) + `samenvoeg_rol` ("→ bijlage van …"); bijlagen tellen niet als exemplaren. Frontend `document/BijlageTabs.tsx` (tablist "Factuur en bijlagen"; PDF inline, foto, overig = download), `DocumentDetailScreen.tsx`, `DocumentenDeelscherm.tsx`. |
| Boeken | `InkoopPort.boek_inkoopfactuur(extra_bijlagen=…)` (`ExtraBijlage` in `backends/port.py`); RLZ-port: extra `/Uploads` per bijlage (`rlz_bijlage_upload_id`, aanwezigheid op bestandsnaam; fout = waarschuwing in het detail, nooit boekfout); Odoo-port: extra `ir.attachment` (niet main). |
| Nazorg | `bijlagen-nabundelen [--dry-run] [--uitvoeren] [--administratie] [--sinds] [--ongedaan <id> --reden]` — per intake-bericht dezelfde regel op de opgeslagen bytes; alleen open bijlage-statussen; geboekte factuur → RLZ-upload; dry-run "factuur ← bijlagen" + TOTAAL. Nameting-allowlist (alleen `--dry-run`), `via_gh_onderdeel` → `bijlagen-factuur`, workflow-onderdeel in `nameting.yml`. |
| Dagteller | `bijlagen_gebundeld` uit audit `bijlage_gekoppeld` (`niet_eenduidig` zacht). |
| Tests | `tests/intake/test_bijlagen_bij_factuur.py` (15: herkenning, één factuur mét tijdlijn/audit/intake-bericht/idempotentie, detail + bestand + lijst-routes, meerdere facturen, nul facturen, scan = AI-route → tweede factuur, verzamelbak → toewijzen neemt bijlagen mee, boeken mét drie uploads, RLZ-fout zichtbaar, nazorg dry-run mét álle CLI-vormen uit het meetrecept, echte run idempotent + ongedaan, mens-oordeel overgeslagen, geboekt → upload, dagteller); gouden-set-casus **ap** `tests/keten/test_ap_bijlagen_bij_factuur.py` (3); vitest `DocumentDetailScreen.test.tsx` (+2), `WerkvoorraadScreen.test.tsx` (+1). |

**Migratie 0174 (afsluit-routine):** (1) `make migrate` tegen de dev-database `boekhouding`: `Running upgrade 0173 -> 0174` (02-10 12:0x, < 2 s);
(2) live op een eigen uvicorn (poort 8017, dev-DB): `GET /health` 200, `GET /administraties/…/documenten/{id}` → **200** mét veld `bijlagen`;
(3) `scripts/dump_schema.sh` vanuit de repo-root: `schema_referentie.sql ververst vanaf boekhouding_test (head 0174)`.

**Keuzes zonder Peter:** scan zonder tekstlaag = kandidaat (nooit raden dat het een bijlage is); foto's alleen bijlage als de mail een
factuur draagt; csv/doc(x)/txt als whitelist; ongedaan als CLI-vorm (geen nieuwe knop); bijlage als `samengevoegd`-rij i.p.v. een nieuwe
tabel. **Beperking:** een splitsingsvoorstel-bron krijgt de bijlagen; de kinderen ná bevestiging niet (de nazorg-CLI vangt ze).

## Punt 2 — rustig scherm (agent P2)

Zie `docs/regels/werkvoorraad-controlescherm.md` alinea 02-10 punt 2. Gebouwd: `herkomstZichtbaarheid.ts` (één regel uit de chip-klasse),
`HerkomstChip.tsx` (provider per blok, `HerkomstBlokKop` mét `linkbtn` "Herkomst tonen"/"Herkomst verbergen", sessionStorage),
`BoekvoorstelPanel.tsx` (alle herkomst-chips via `HerkomstChip`); vitest `herkomstZichtbaarheid.test.ts` (5), `BoekvoorstelPanel.rustig.test.tsx`
(4), bestaande chip-tests via `testHerkomst.toonHerkomst()` (27 plekken). Keten-sweep: 6 detail-baselines gewild ververst. Open punt: drie
knoppen per blok vs. één scherm-brede knop (één state-regel).

## Punt 3 — samenvoeg-vinkje (agent P3)

Oorzaak: `boekvoorstel._samenvoeg_velden` zette bij projectplicht hard `samenvoegen_toegestaan=False` (fix 3, 10-07) en de opslag negeerde
daar de keuze — Universal Steigerbouw (projectplicht) kreeg dus nooit een vinkje. Gebouwd: projectplicht is geen uitsluiting meer; de
één-regel-variant volgt 18-09/23-09; `project_id` van de samengevoegde regel = het gemeenschappelijke project, anders leeg (→ verdeling,
punt 5); keuze onthouden als leverancier-voorkeur. **Beslispunt:** de DEFAULT zonder voorkeur blijft onder projectplicht gesplitst (default
"samengevoegd" flipte 9 gouden-set-casussen en wisselt bij openen de prefill van élk open Universal-document; Peters punt "waarom splitst
die automatisch?" is punt 4 van de lijst van 22, niet deze opdracht — omschakelen is één regel). Tests `test_boekvoorstel_samenvoegen_23_09.py`
(+3, f00117f4 751,15 / 157,74), `test_boekvoorstel.py` (2 omgekeerd), keten ae, vitest `samenvoegen23` (+1); 6 keten-exports.

## Punt 4 — project nooit uit de historie (agent P4)

**Commit (worktree-branch `worktree-agent-a82d7ad5017c18c6b`):** `a238f77` — `feat(project nooit uit de historie zonder factuurverwijzing — punt 4 …)`.
Geen migratie. Geen nieuwe instelling.

#### Gebouwd
- `backend/app/documenten/regel_prefill.py::_met_leverancier_geheugen`: het leverancier-geheugen vult `project_id` NIET meer in
  (vóór 02-10: "voorstel uit historie", gevuld). De historie reist alleen nog als herkomst-informatie mee: `project_bron = geheugen`
  + `project_bron_detail` "De historie van deze leverancier wijst naar een project, maar de factuur zelf noemt geen projectnummer —
  niet ingevuld …" zónder `project_id` en zónder `prefill_herkomst.project` (dus geen autosave-trigger, geen chip "Geheugen N %").
  `factuur_conflict` en `geheugen_afgesloten` ongewijzigd (niets invullen). Grootboek/btw uit het geheugen ongewijzigd (punt 8 van
  Peters lijst = niet in deze opdracht).
- `app/projecten/match.py`: commentaar op `HERKOMST_GEHEUGEN` ("NIET gevuld — alleen herkomst-info").
- Autoboek-pad `app/documenten/autoboeken.py`: `_geheugen_veld_geblokkeerd` eist geen geheugen-project meer, `_vul_regel_uit_geheugen`
  laat `project_id` zoals de factuur/cachecode 'm gaf. Een regel zonder project onder projectplicht loopt dan via de automatische
  verdeling (punt 5) óf de harde check "Verplichte velden" blokkeert → `autoboeken_geweigerd` (bestaand, zichtbaar). De conflict-toets
  (factuur noemt een ánder nummer dan het geheugen-project → weigeren) blijft.
- Frontend `document/geheugenVoorstel.ts::bepaalPrefill`: vult `projectId` nooit (ook niet bij projectplicht). `regelVoorstelChips.ts::
  bepaalProjectFactuurChip('geheugen')`: chip "historie noemt een project — niet ingevuld" alleen zolang het veld LEEG is (uitleg), weg
  zodra er iets gekozen is. (Agent P2 bepaalt waar die chip zichtbaar is — standaard onder "Herkomst tonen".)
- `BoekvoorstelPanel`: de hint "kies per regel een project (de factuur noemt een projectnummer)" negeert `projectBron === 'geheugen'`
  (anders zou de Verdelen-link verdwijnen zodra de historie iets noemt) — zit in commit 2 (punt 5) omdat die regel daar geraakt is.

#### Tests
- `tests/documenten/test_project_bronvolgorde.py`: casus "geen bron → geheugen vult" herschreven naar "geheugen vult NIETS maar
  blijft zichtbaar" (project None, `project_bron='geheugen'`, gb/btw wél uit het geheugen), conflict-casus (andere regel leeg i.p.v.
  Tilburg), persist-casus; nieuw: `test_geheugen_project_zonder_factuurverwijzing_boekt_nooit_automatisch` (guard afwezig-pad autoboek:
  groen app-bevestigd geheugen-project zonder factuurverwijzing → regel leeg, `autoboeken_geweigerd`, niet geboekt).
- Gouden set casus i `TestBronvolgordeProject::test_geheugen_vult_nooit_zonder_factuurbron_maar_zichtbaar`; casus a ongewijzigd groen.
- Gouden set casus q (autoboek leren) en r (AI-toets) steunden op het geheugen-project voor het vierde exemplaar → in commit 2 (punt 5)
  op factuurmaand-omzet gezet: het vierde exemplaar boekt nu automatisch via de automatische verdeling (bevroren, regels per project).
- Vitest `geheugenVoorstel.test.ts`, `regelVoorstelChips.test.ts` herschreven.

#### Meetlat (ná deploy)
Bibliotheekquery `db-lezen project-prefill-herkomst --administratie <Universal Steigerbouw>`: rijen mét `herkomst_project =
leverancier_geheugen` mogen in snapshots ná de deploy niet meer voorkomen; rijen mét `project_bron = geheugen` dragen `project_id`
NULL. Casus f00117f4: openen ná deploy → projectkolom leeg (geen "Afgesloten 25147"), uitleg onder "Herkomst tonen".
Werkt in productie: niet gemeten.

#### Beslispunten / bijvangst (niet gebouwd)
- Het regel-grootboekgeheugen (7005 Inhuur steiger voor brandstof — Cowork-waarneming) is punt 8 en bewust niet geraakt.

## Punt 5 — overhead automatisch (agent P4)

**Commit:** `9ee8ede` — `feat(overhead automatisch via de omzetsleutel — punt 5 …)`. Geen migratie, geen instelling.

#### Gebouwd
- `app/projectverdeling/service.py::lees`: onder PROJECTPLICHT staat de verdeling bij openen KLAAR voor élke regel zonder project
  (= overhead) — zonder leverancier-opt-in (`_opt_in_pro_rato` is geen voorwaarde meer onder projectplicht; buiten projectplicht
  blijft de opt-in-prefill het pad). Sleutel = `standaard_sleutel(administratie)` (Universal = omzetsleutel uit de historie, nooit
  hardcoded). Niets wordt opgeslagen: de live stand (`prefill=True, opgeslagen=False`) is wat checks én boekmotor zien; boeken kan
  direct (`bevries_bij_boeking` bevriest de live stand; RLZ/Odoo splitsen per project). Aanpassen blijft bestaand gedrag.
- `service.automatische_periode`: sleutelmaand = MAAND VAN DE FACTUURDATUM (besluit 02-10, herziet `default_periode(vandaag)` =
  vorige afgesloten maand). `omzet_jaar` → jaar van de factuurdatum (geldig) anders vorig jaar; `omzet_maand`/`vaste_regels` →
  factuurmaand als die omzet heeft (of de cache nooit gevuld is); geen omzet in de factuurmaand / geen factuurdatum / maand in de
  toekomst → zichtbare terugval op de vorige afgesloten maand (`periode_herkomst = vorige_maand_terugval` + tekst). Nooit stil.
- `pv.ProjectverdelingData`: `periode_herkomst` (`factuurmaand` | `vorige_maand_terugval` | `opgeslagen`), `periode_herkomst_tekst`,
  `regels_zonder_project`, `regels_totaal`; DTO + router idem (ook in de 'geen'-stand de tellers).
- Checks: `check_verplichte_velden(verdeling_reden=…)` — onder projectplicht verwijst "project ontbreekt" naar de verdeling mét reden
  ("niet gedekt door de projectverdeling (Geen omzetcijfers bekend voor juli 2026 — ⟳ …): vul de projectverdeling aan … óf kies per
  regel een project"); zonder verdeling de oude tekst. `service.check`: automatische prefill die niet compleet is = ORANJE signaal
  "Automatische verdeling niet mogelijk voor N regels zonder project — ‹reden›: …" (één oorzaak, één rode rij: Verplichte velden).
- "Verdelen over projecten" OVERRULT: `BoekvoorstelPanel.verdelenGevraagd` maakt de regelprojecten leeg (handmatig gemarkeerd zodat
  niets ze terugvult), de PUT draagt `verdelen_leeggemaakt {regels: n}` → server-tijdlijnregel `verdelen_leeggemaakt` (schema
  `VerdelenLeeggemaaktInput`, `boekvoorstel.VERDELEN_LEEGGEMAAKT_SLEUTEL`, nooit op autosave), daarna opent het blok (bestaand
  `onVerdelenGevraagd`); zonder regelprojecten alleen openen. Tijdlijntekst `verdelenLeeggemaaktTijdlijn.ts` ("Verdelen over projecten:
  project van 2 regels leeggemaakt — het hele bedrag verdeeld via de projectverdeling (…)").
- `ProjectverdelingBlok`: kop-chip "automatisch — ‹sleutel› · maand van de factuurdatum" (oranje bij terugval mét reden i.p.v. "voorstel —
  pro rato per leverancier aan"); `openVerzoek`/tekstknop nemen de server-periode over; uitleg "Alle regels dragen al een project — er is
  niets te verdelen. ‹Verdelen over projecten› … maakt de projecten van de regels leeg en verdeelt het hele bedrag" in de 'geen'-stand
  én onder de restant-balk (nooit meer "€ 0,00 · verdeeld 100 %" zonder uitleg).
- Bijvangst, noodzakelijk voor de keten: `tegenboeken._harde_checks_op_tegenboeking` eist geen project op regels die de bevroren
  verdeling dekt (zelfde dekkingsregel als het boekpad; vóór 02-10 kon een overhead-boeking niet tegengeboekt worden).
- Hint onder de regels: `projectBron === 'geheugen'` (punt 4) verbergt de Verdelen-link niet meer.

#### Tests
- `tests/projectverdeling/test_service.py`: drie bestaande tests herschreven naar "verdeling staat klaar vóór de mens iets doet";
  nieuw `TestOverheadAutomatisch` (klaar zonder opt-in op de factuurmaand terwijl vandaag oktober is; boeken direct = 3 gesplitste RLZ-
  regels + bevroren rij; factuurmaand zonder omzet = zichtbare terugval; afwezig-pad zonder omzetcijfers = Verplichte velden rood mét
  verwijzing + Projectverdeling-signaal; alle regels mét project = geen automatische verdeling; buiten projectplicht = opt-in blijft;
  `verdelen_leeggemaakt` → tijdlijnregel; DTO herkomst + tellers).
- Gouden set q + r: `omzet_factuurmaand`-fixture (juli 2026 op PROJECT_26049) — het vierde exemplaar boekt automatisch via de
  automatische verdeling; q asserteert bevroren rij `2026-07-01` + Project op élke RLZ-regel. Keten-exports `h_bdo.json`,
  `m_incasso_factuur.json` ververst (check-teksten). Keten k/c/i ongewijzigd groen.
- Vitest: `ProjectverdelingBlok.test.tsx` (+3: automatisch-chip, terugval oranje, niets-te-verdelen-uitleg, server-periode bij
  openVerzoek), `BoekvoorstelPanel.kopDoorzetten.test.tsx` (+2: overrule → regels leeg + `verdelen_leeggemaakt {regels:3}`; zonder
  regelprojecten geen leeg-PUT), `verdelenLeeggemaaktTijdlijn.test.ts`.

#### Meetlat (ná deploy) — werkt in productie: niet gemeten
- Casus f00117f4 (Universal Steigerbouw, factuurdatum 30-06): openen → blok "automatisch — pro rato omzet (maand) · maand van de
  factuurdatum" juni 2026 (of oranje terugval als juni geen omzet heeft), € 751,15 verdeeld 100 %, "Verplichte velden" groen zonder
  project; "Boeken in RLZ" direct → RLZ-regels per project.
- `db-lezen projectverdeling`-rijen ná de deploy: `pro_rato_periode` = eerste dag van de factuurmaand bij nieuwe boekingen; tijdlijn
  `verdelen_leeggemaakt` zodra iemand de knop op een regel mét project gebruikt. Request-log: `PUT …/boekvoorstel` mét
  `verdelen_leeggemaakt` in de body.

#### Beslispunten
- Factuurmaand zonder omzet valt terug op de vorige afgesloten maand (zichtbaar, oranje). Alternatief (blokkeren tot een mens kiest) is
  bewust niet gekozen: "boeken kan direct" + niets stil.
- Sleutel `vaste_regels` als standaard: de automaat verdeelt dan pro rato op de factuurmaand (vaste regels zijn mens-werk).

## Punt 6 — balansrekeningen zonder project (agent P4)

**Commit:** `9777a1a` — `feat(balansrekeningen zonder project — punt 6 …)`. Geen migratie, geen instelling, geen keuzelijst.

#### Gebouwd
- Nieuw `app/documenten/rekeningtype.py`: `SOORT_KOSTEN = 2`, `balans_ledger_ids(session, administratie_id)` (alle rekeningen met
  `grootboekrekening.soort != 2`, één query in RLS-scope), `project_van_toepassing(ledger_id, balans)` (None/onbekend = kosten,
  fail-closed richting de projectplicht). RLZ `AccountType` onvertaald (1 opbrengsten, 2 kosten, 3 activa, 4 passiva); Odoo-sync vult
  `soort` al via `soort_voor_account_type` (expense* → 2) — geen sync-wijziging nodig.
- `BoekvoorstelRegelData.project_van_toepassing` (default True, niet gepersisteerd), gezet in `boekvoorstel._met_projectverdeling`
  (het ene koppelpunt van álle leespaden). Gelezen door: `_regels_zonder_project`, `_naar_check_regels` → `CheckRegel.project_van_toepassing`
  → `check_verplichte_velden` (geen projecteis op een balansregel), `projectverdeling.verrijk_boekvoorstel` + `sla_op` (balansregels
  buiten het basisbedrag), RLZ-adapter `regels_naar_rlz_lines`/`tegenboek_lines` (balansregel nooit gesplitst, geen Project), Odoo-adapter
  (`analytic_distribution` alleen op kostenregels), `regel_prefill` (nooit een project op een balansregel, ook niet uit de factuur).
- Frontend: `useGrootboekOpties` geeft `soort` door (`ComboboxOptie.soort`); `BoekvoorstelPanel`: projectcel "— geen project
  (balansrekening)" mét title i.p.v. combobox, "N regels zonder project" en de Verdelen-hint tellen alleen kostenregels, "Alle regels —
  project" slaat balansregels over (en meldt het juiste aantal in `kop_doorgezet`), "Verdelen over projecten" telt alleen kostenregels
  mét project. Activa-kaart (0168) ongewijzigd.

#### Tests
- `tests/documenten/test_project_rekeningtype.py` (puur: helper + check zonder eis op balansregel; keten: voorraad/activa/tussenrekening
  zonder project → Verplichte velden groen, verdeling None, "Geen projectverdeling van toepassing"; mengvorm voorraad + kosten → alleen
  € 500 kosten verdeeld, RLZ 1 voorraadregel zonder Project + 3 gesplitste kostenregels, boeken direct; onbekende rekening = kosten
  (rood); prefill zet nooit een project op een voorraadregel, wél op de kostenregel).
- Gouden set ag: `test_ag_balansregel_zonder_project_geen_projecteis` (0107 zonder project + 4700 mét project → groen, verdeling None,
  activa-kaart ongewijzigd 1 kandidaat).
- Vitest `BoekvoorstelPanel.balans.test.tsx` (projectcel, telling, kop-doorzet slaat balansregel over).

#### Meetlat (ná deploy) — werkt in productie: niet gemeten
Universal Steigerbouw: een inkoopfactuur mét een regel op 3xxx (voorraad) zonder project → "Verplichte velden" groen, projectcel toont
"— geen project (balansrekening)". `db-lezen` over `boekvoorstel_regel` × `grootboekrekening.soort`: geboekte regels op soort 3/4 ná
de deploy dragen `project_id` NULL zonder verdelingsdeel.

#### Beslispunt
- Regels met een rekening die nog niet in de cache staat gedragen zich als kosten (projectplicht). Alternatief (balans) zou stil een
  project laten vallen — bewust niet.


## Gelezen regels

- `docs/regels/intake-extractie.md` — 430 regels (vóór deze run)
- `docs/regels/werkvoorraad-controlescherm.md` — 605 regels (vóór deze run)
- `docs/regels/verplichtingen-projecten-voorraad.md` — 453 regels
- `docs/regels/kantoor-frontend.md` — 134 regels
- `docs/regels/werkloop-productie.md` — 350 regels
- BESLISSINGEN "SAMENVOEGEN-BUG … (Peter 18-09)", "SAMENVOEGEN — BRON = OPGESLAGEN REGELS … (23-09)", "PROJECT-BRONVOLGORDE … (Peter 25-09)",
  "COMFORT CONTROLESCHERM … (Peter 25-09)", "UNIVERSAL — OVERHEAD VIA DE OMZETSLEUTEL … (Peter 21-09)", "NABUNDEL-NAZORG 03-09".

## Nazorg punt 3 (coördinator, commit a686312)

Ná de merge van punt 3 was `tests/documenten/test_project_bronvolgorde.py::TestAutoboekConflict` rood (geboekt i.p.v. geweigerd):
`autoboeken.zet_leverancier_autoboeken` (en twee andere aanmaakplekken) maakten een `LeverancierVoorkeur` mét `regels_samenvoegen=True`
hard; nu projectplicht samenvoegen niet meer uitsluit, boekte het autoboek-pad élke opt-in-leverancier onder projectplicht op de
SAMENGEVOEGDE regel en zag de factuur-conflict-toets (FV-02) de regelteksten niet meer. Fix: één bron
`boekvoorstel.standaard_samenvoegen_zonder_voorkeur` (projectplicht = gesplitst, anders de backend-capability).

## Commits (in Peters volgorde)

265fcf5 punt 1 · a5d6406 punt 2 · 4766515 punt 3 · a686312 nazorg punt 3 · 5eca102 punt 4 · 2ec46d1 punt 5 · 4e38aa5 punt 6 · docs-commit (dit rapport, regels 4–6, baselines).

## Poort

- Backend volledige suite ná de zes merges (DB `boekhouding_test_p1`, 64 min): **7758 groen, 1 skipped, 1 rood** = `tests/auth/test_kantoor_passkeys.py::test_registratie_en_passkey_login_met_bestaande_jwt_semantiek` — PRE-EXISTEND (refresh-TTL over de zomertijdwissel 25-10; al gemeld in het rapport van 01-10, auth-domein, niet geraakt in deze run; klikpunt/vervolg daar).
- Gouden set `tests/keten` ná alle merges: 204 groen (incl. casus ap); keten-guard, export-determinisme groen; exports ongewijzigd ná de laatste run.
- Vitest volledig: 279 bestanden / 2094 tests groen · `tsc -b`: exit 0.
- Keten-sweep: 6/13 rood vóór de baseline-update = exact de zes `*_detail`-schermen (5–6 % pixels: chips weg, "Herkomst tonen", vinkje, verdeling), lijst ×6 en bank gelijk → screenshot c_spot_services gecontroleerd (rustig scherm, vinkje, Verdelen-knop) → baselines van de zes detail-schermen ververst (`KETEN_UPDATE_BASELINE=1`), lijst/bank-baselines bewust teruggezet; sweep 13/13 groen.
- Doc-guards (rapporten-index, gelezen-regels, klikpunten, CLAUDE.md-verwijzingen, regels-index, nameting-workflow): 101 groen; changelog-guard groen.
- Agent-eindsuites: P2 `src/document` 472 groen; P3 keten + boekvoorstel 279 groen; P4 `tests/documenten tests/projectverdeling tests/keten tests/projecten` 1957 groen.
