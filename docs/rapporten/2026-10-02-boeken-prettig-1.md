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

## Punt 4–6 (agent P4)

_Wordt ingevuld zodra de drie commits van agent P4 zijn samengevoegd._

## Gelezen regels

- `docs/regels/intake-extractie.md` — 430 regels (vóór deze run)
- `docs/regels/werkvoorraad-controlescherm.md` — 605 regels (vóór deze run)
- `docs/regels/verplichtingen-projecten-voorraad.md` — 453 regels
- `docs/regels/kantoor-frontend.md` — 134 regels
- `docs/regels/werkloop-productie.md` — 350 regels
- BESLISSINGEN "SAMENVOEGEN-BUG … (Peter 18-09)", "SAMENVOEGEN — BRON = OPGESLAGEN REGELS … (23-09)", "PROJECT-BRONVOLGORDE … (Peter 25-09)",
  "COMFORT CONTROLESCHERM … (Peter 25-09)", "UNIVERSAL — OVERHEAD VIA DE OMZETSLEUTEL … (Peter 21-09)", "NABUNDEL-NAZORG 03-09".

## Poort

_Wordt ingevuld ná de volledige suite (zie de commit-berichten per punt voor de gerichte runs)._
