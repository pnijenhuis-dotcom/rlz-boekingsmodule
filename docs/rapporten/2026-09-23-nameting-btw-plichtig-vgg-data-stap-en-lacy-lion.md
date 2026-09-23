# Nameting ná deploy — btw-plichtig per administratie: data-stap VGG, sync-signaal, detector, nazorgrapport TE WEINIG (23-09, poging 1)

Opdracht `opdrachten/gedaan/2026-09-23-nameting-btw-plichtig-vgg-data-stap-en-lacy-lion.md` (vervolg op de bouw van 22-09; bouwrapport
`docs/rapporten/2026-09-22-btw-plichtig-per-administratie-vgg-lacy-lion.md`, BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG =
BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)"). Eén SCHRIJVENDE stap (de data-stap VGG uit het besluit van Peter 13-09, op de job-image via
`gcloud run jobs execute` in de owner-sessie — regel 08-09); alle metingen lees-only (leesreplica `rlz-sql2-lees` als `nameting@`, Cloud Logging,
`rlz-lezen`, dispatch-onderdeel `btw-niet-plichtig` → bot-bestand op main). Niets geschreven in RLZ. Peter keek niet mee; keuzes onder "Keuzes".
Tijden UTC tenzij "NL".

**Werkt in productie — per onderdeel:**

| Onderdeel | Uitkomst | Bewijs |
|---|---|---|
| Data-stap VGG (`btw-plichtig-zetten --administratie Vastgoedgroep --uit`) | **JA** | dry-run executie `rlz-reconciliatie-lmh8k`: "DRY-RUN Vastgoedgroep Nederland B.V.: zou True (bron geen) → False zetten … niets geschreven"; echt `rlz-reconciliatie-wjtzn` 16:45:26: "GEZET … btw_plichtig=False bron=mens — audit administratie_btw_plichtig_gewijzigd (cli btw-plichtig-zetten (besluit Peter 22-09)); geen-btw-code: NL, Geen BTW (Vrijgesteld)"; leesreplica `platform.administratie` cc07e461: `btw_plichtig` f, bron `mens`, `gewijzigd_op` 16:45:26; audit precies 1 rij (actor `00000000-…-0001` = systeem, oud `{"bron": null, "btw_plichtig": true}` → nieuw `{"bron": "mens", "btw_plichtig": false}`) |
| Nachtelijke identiteit-sync leest `EnableTaxReporting` | **JA** | `rlz-sync` executie `r5td7` (`sync-alles` 23-09 05:03, image `ac7639b`): 75 regels — 74 × "btw-plichtig bevestigd uit RLZ (EnableTaxReporting)", 1 × "Vastgoedgroep Nederland B.V.: RLZ EnableTaxReporting=false — kandidaat 'niet btw-plichtig', bevestig de btw-status" (05:03:42), 0 × "niet verwerkt"; leesreplica vóór de data-stap: 74 RLZ-administraties `btw_plichtig` t / bron `rlz` / signaal t, VGG t / NULL / **f**, 3 Odoo-administraties NULL/NULL |
| Detector `btw_status_bevestigen` — afwezig-pad (run 06:30 NL vóór de sync) | **JA (0, verwacht 0)** | run `40b5d45c` (04:30–04:48): 0 bevindingen mét `detail.automatisering = btw_status` in de VGG-scope én platformbreed — de stand van 22-09 droeg nog geen RLZ-signaal en VGG heeft tarieven > 0 % in de cache |
| Detector — aanwezig-pad (LET-OP voor VGG) | **NIET GEMETEN** | de eerste run mét signaal zou 24-09 06:30 zijn; de data-stap van 16:45 zet bron `mens` en haalt VGG uit de kandidatenlijst vóór die run. De invoerkant is wél gemeten (sync-regel "kandidaat"), de pure regel `kandidaat_reden` zit in de suite; `btw-plichtig-kandidaten` ná de data-stap = 0 administraties (bot-bestand) — geen andere kandidaat in productie, dus dit pad heeft in productie geen casus meer |
| Nazorgrapport `btw-niet-plichtig` (dispatch) | **JA** | run 35891104307 → bot-commit `207bae7`, `verkenning/nameting-btw-niet-plichtig-23-09.txt`: MODULE-tabel **3 documenten**, RLZ-kolommen gevuld via GET, TOTAAL te weinig betaald **€ 1.401,43**, RLZ zonder module-spoor 0, kandidaten 0, job-exit 0 |
| Casus Lacy Lion 2026-042 in dat rapport | **JA — exact de casus** | RLZ-04-00000925 · netto 1535.13 · btw 322.38 · bruto 1857.51 · RLZ post 1535.13 · betaald 1535.13 · open 0.00 · **TE WEINIG 322.38** |
| Herstel Lacy Lion via "Corrigeren…" (klikpunt Peter) | **NIET GEMETEN (klikpunt)** | request-log service sinds de deploy (00:51): 0 × `POST …/corrigeren`, 0 × `PUT …/btw-plichtig`; document `0b1f8c00` staat nog `geboekt`, boek_cyclus 0 |
| Aangiftepoort n.v.t. voor VGG | **JA voor 2026, mét nuance** | de CLI telt "ingediende btw-aangiften in RLZ: 3" (verwacht 0) — `rlz-lezen TaxDeclarations` (lees-only): drie NIHIL-aangiften 2025 Q1/Q2/Q3 (RLZ-05-00000001…03, `TotalVatAmount` 0.0, Status 3 afgehandeld), **geen aangifte over 2026** → de september-documenten vallen buiten élke ingediende periode, de storno-blokkade (`app/rlz/aangifte.py`) grijpt niet, "Corrigeren…" is het pad (geen tegenboek-pad) |

**Één regel voor Peter:** VGG staat nu op "niet btw-plichtig" (bron mens, audit staat); de nabetaallijst is drie documenten, samen € 1.401,43
(E.M.S Onroerend Goed 20260014 € 735,00; Studio Lacy Lion 2026-041 € 344,05 en 2026-042 € 322,38) — élk te herstellen met ⋯ › "Corrigeren…" op het
geboekte document (regel komt bruto / btw 0 / "NL, Geen BTW (Vrijgesteld)"), daarna "Boeken in RLZ" en het verschil nabetalen. De twaalf open
VGG-documenten die ter accordering staan hebben al btw 0 (tarief "NL, Nul tarief") en lopen door de nieuwe check heen.

## Stap 0 — deploy-check (service ÉN jobs)

- `git rev-list --count main..origin/main` = 0 bij de start; ná de bot-commit `207bae7` (dispatch) één `merge --no-ff` (`51533d3`) — regel 19-09.
- Feature-commit `9854c4c` (migratie 0170, `app/beheer/btw_plichtig.py`, 23-09 00:36 NL) is voorouder van deploy `ac7639b` (workflow groen 00:51)
  en van `196b0fe` (deploy `in_progress` bij de start, image al uitgerold). Service `rlz-backend`, jobs `rlz-reconciliatie` en `rlz-boek-wachtrij`:
  alle drie `backend:196b0fe…`. Er is géén job `rlz-sync-alles` — `sync-alles` draait als job `rlz-sync` (executie `r5td7`).
- Alembic-head in productie: bewakingsprobe `database` 16:45:21 = `ok` ("repo-head == DB"; repo-head is 0171 ≥ 0170). De sync van 05:03 schreef al
  in de 0170-kolommen (`btw_plichtig_rlz_signaal` gevuld op 75 administraties), dus 0170 stond vóór 05:00.

## 1. Data-stap VGG (SCHRIJVEND, job-image, owner-sessie)

```
gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|btw-plichtig-zetten|--administratie|Vastgoedgroep|--uit|--dry-run"
→ rlz-reconciliatie-lmh8k: DRY-RUN  Vastgoedgroep Nederland B.V.: zou True (bron geen) → False zetten [NIET btw-plichtig (btw in de kosten, harde check)] — niets geschreven
gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|btw-plichtig-zetten|--administratie|Vastgoedgroep|--uit"
→ rlz-reconciliatie-wjtzn: GEZET    Vastgoedgroep Nederland B.V.: btw_plichtig=False bron=mens — audit administratie_btw_plichtig_gewijzigd (cli btw-plichtig-zetten (besluit Peter 22-09)); geen-btw-code: NL, Geen BTW (Vrijgesteld)
```

Leesreplica ná de stap (`db_lezen.sh`, VGG-scope `cc07e461-3288-4065-85ed-9005495a22ea`):

| kolom | waarde |
|---|---|
| `btw_plichtig` / `btw_plichtig_bron` / `btw_plichtig_rlz_signaal` | f / mens / f |
| `btw_plichtig_gewijzigd_op` | 2026-09-23 16:45:26 |
| audit `administratie_btw_plichtig_gewijzigd` | 1 rij, 16:45:26, actor systeem, `administratie_id` VGG, oud→nieuw zoals verwacht |

Alleen VGG gezet; er zijn geen andere kandidaten (stap 3). Meetles: de audit-rij is alleen zichtbaar mét `--administratie` (RLS op `audit_event`
mét administratie_id — memory "audit_event mét administratie_id vereist scope"); platformbreed gaf de query 0 rijen.

## 2. Sync-signaal (`sync-alles` 23-09 07:00 NL, executie `rlz-sync-r5td7`, image `ac7639b`)

Cloud Logging, filter `btw-plichtig|EnableTaxReporting|btw-status-signaal`: 75 regels, 74 "bevestigd uit RLZ", 1 "kandidaat" (VGG 05:03:42),
0 fouten. Leesreplica vóór de data-stap:

| backend | `btw_plichtig` | bron | RLZ-signaal | aantal |
|---|---|---|---|---|
| rlz | t | rlz | t | 74 |
| rlz | t | NULL | f | 1 (VGG) |
| odoo | t | NULL | NULL | 3 |

Exact de verwachting: élke RLZ-administratie draagt het signaal, bron `rlz` waar true, Odoo NULL.

## 3. Detector `btw_status_bevestigen`

- Run 23-09 04:30 (`40b5d45c`) draaide vóór de sync: 0 LET-OP's `btw_status` (VGG-scope én platformbreed) = verwacht 0.
- Kandidatenlijst ná de data-stap (bot-bestand): "btw-plichtig-kandidaten — 0 administratie(s)". Er is dus geen verhuurder-kandidaat buiten VGG;
  het beslispunt "verhuurders zonder optie belaste verhuur" is voor nu leeg (ARVUM/Rubicon true, conform STAP-0).
- Het aanwezig-pad (LET-OP-rij voor VGG in de run van 24-09) is in productie niet meer te meten: de data-stap van vandaag haalt VGG uit de
  kandidaten vóór die run. Bewust zo gelaten (keuze b).

## 4. Nazorgrapport (bot-bestand `verkenning/nameting-btw-niet-plichtig-23-09.txt`, commit `207bae7`)

| boekstuk | leverancier | referentie | datum | netto | btw | bruto | RLZ post | betaald | open | TE WEINIG |
|---|---|---|---|---|---|---|---|---|---|---|
| RLZ-04-00000924 | E.M.S Onroerend Goed | 20260014 | 2026-09-01 | 3500.00 | 735.00 | 4235.00 | 3500.00 | 3500.00 | 0.00 | **735.00** |
| RLZ-04-00000926 | Studio Lacy Lion | 2026-041 | 2026-09-10 | 1638.35 | 344.05 | 1982.40 | 1638.35 | 1638.35 | 0.00 | **344.05** |
| RLZ-04-00000925 | Studio Lacy Lion | 2026-042 | 2026-09-11 | 1535.13 | 322.38 | 1857.51 | 1535.13 | 1535.13 | 0.00 | **322.38** |

TOTAAL € 1.401,43. RLZ-inkoopfacturen 2026 mét `TotalTaxAmount` ≠ 0 zonder module-spoor: 0 — alle btw-splitsingen in VGG komen uit de module
(alle drie geboekt mét tarief "NL, Hoog Tarief" 21 %, leesreplica `taxrate_cache`). De casus is dus geen eenling: hetzelfde patroon raakte twee
eerdere documenten (01-09 en 10-09), die Peter niet in beeld had. Alle drie zijn volledig betaald op de RLZ-post (open 0.00), het verschil is
nooit aan de leverancier betaald.

**Aangiftepoort:** de CLI-regel "ingediende btw-aangiften in RLZ: 3" zou volgens het meetrecept 0 zijn. `rlz-lezen TaxDeclarations` (lees-only,
executie via `nameting.sh`): RLZ-05-00000001 (2025-01-01→03-31), -02 (04-01→06-30), -03 (07-01→09-30), alle `TotalVatAmount` 0.0, `Status` 3,
`IsSupplement` false — nihil-aangiften uit de RLZ-inrichting van 2025; niets over 2026. De storno-blokkade toetst per document op de periode
(`app/rlz/aangifte.py`), dus de drie september-documenten zijn corrigeerbaar zonder tegenboek-pad. De CLI-tekst "aangiftepoort n.v.t. als 0" is
te kort door de bocht: het getal telt óók nihil-aangiften van eerdere jaren — in het rapport is het een lees-signaal, de poort zelf beslist.

## 5. Klikpunten Peter (herstel = nabetaallijst)

- Studio Lacy Lion 2026-042, RLZ-04-00000925, factuurdatum 11-09-2026, bruto € 1.857,51 (module-document id `0b1f8c00`, bron bot-bestand
  `verkenning/nameting-btw-niet-plichtig-23-09.txt`): ⋯ › "Corrigeren…" (reden bv. "btw in kosten — administratie niet btw-plichtig") → de regel
  staat ná de prefill op bruto 1.857,51 / btw 0 / "NL, Geen BTW (Vrijgesteld)" mét chip, check "Btw in niet-btw-plichtige administratie" groen →
  "Boeken in RLZ". Verwacht in RLZ: crediteurpost 1.857,51, `BaseRemainingAmount` 322,38 ná de eerdere betaling van 1.535,13 → nabetalen € 322,38.
- Studio Lacy Lion 2026-041, RLZ-04-00000926, 10-09-2026, bruto € 1.982,40 (document id `2488a20b`, zelfde bot-bestand): zelfde route,
  nabetaling € 344,05.
- E.M.S Onroerend Goed 20260014, RLZ-04-00000924, 01-09-2026, bruto € 4.235,00 (document id `7e864b9e`, zelfde bot-bestand): zelfde route,
  nabetaling € 735,00.
- Meting ná de klik(s): `gh workflow run nameting.yml -f onderdeel=btw-niet-plichtig` → TE WEINIG 0.00 per gecorrigeerd document + request-log
  `POST …/corrigeren` 200 — staat als vervolg-opdracht poging 2 (`opdrachten/inbox/2026-09-24-nameting-btw-plichtig-lacy-lion-herstel-poging-2.md`,
  `niet vóór: 2026-09-24 09:00`).

## 6. Bijvangst — de twaalf open VGG-documenten

Leesreplica (VGG-scope): 12 documenten `ter_accordering` (14-09 t/m 22-09, 12 regels), alle mét netto = totaal, btw 0.00, tarief "NL, Nul
tarief" (0 %). De nieuwe harde check (btw ≠ 0 / tarief > 0 % / verlegd / buitenland / onbekend = rood) is daarop groen; ze boeken ná het laatste
akkoord mét `TaxRate` Nul tarief en TaxAmount 0 — RLZ boekt dan bruto op de crediteurpost. Geen handeling nodig. Verder 3 `geboekt` (de tabel
hierboven) en 8 `afgevoerd_duplicaat`.

## Keuzes zonder Peter

- **(a) De data-stap is uitgevoerd** — besluit Peter 13-09 "VGG is niet btw-plichtig" is gecaptured in de bouwopdracht van 22-09 en de nameting-
  opdracht noemt de stap letterlijk mét dry-run-vóór-echt; het RLZ-signaal (false) én de casus bevestigen het. Alleen VGG.
- **(b) Geen kunstmatige meting van het detector-aanwezig-pad** (data-stap uitstellen tot ná 24-09 06:30 om één LET-OP-rij te zien): een dag langer
  met een kapotte prefill in VGG (12 open documenten, nieuwe facturen dagelijks) weegt zwaarder dan het bewijs van een regel die in de suite en op
  de invoerkant (sync-log) al vast staat. Het pad blijft "niet gemeten" mét deze reden; er is geen tweede kandidaat in productie.
- **(c) Aangiften 3 ≠ rood.** Nagelezen in RLZ (lees-only) in plaats van het meetrecept te volgen ("verwacht 0"): het zijn nihil-aangiften 2025. De
  CLI-tekst wordt niet aangepast in deze run (lees-only nameting; voorstel in de regels-alinea: periode-bereik erbij tonen).
- **(d) Geen `WAT_IS_NIEUW`-regel:** nameting zonder feature-commit.

## Vervolg

- Poging 2 (klikpunt-afhankelijk): `opdrachten/inbox/2026-09-24-nameting-btw-plichtig-lacy-lion-herstel-poging-2.md` — meet ná Peters
  "Corrigeren…" TE WEINIG 0.00 + `POST …/corrigeren` 200 + RLZ-restant 322,38 via `rlz-lezen`; legt zichzelf terug mét `niet vóór` +1 dag als er
  niet geklikt is (hoogstens drie pogingen, regel 22-09).
- Verbetervoorstel (niet gebouwd): `btw-in-niet-plichtige-administratie` toont bij de aangiften het periode-bereik en het jaar van de documenten,
  en `btw-plichtig-kandidaten` neemt Odoo-administraties zichtbaar als "geen RLZ-signaal" op (nu NULL, stil).

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT; regelaantallen = stand vóór deze run):
- `docs/regels/btw.md` (256 regels)
- `docs/regels/administraties-instellingen.md` (158 regels)
- `docs/regels/reconciliatie.md` (297 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
