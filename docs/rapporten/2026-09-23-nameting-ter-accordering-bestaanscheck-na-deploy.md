# Nameting ná deploy — dagelijkse bestaanscheck "intussen buiten de module geboekt" (23-09, poging 1)

Opdracht `opdrachten/gedaan/2026-09-23-nameting-ter-accordering-bestaanscheck-na-deploy.md` (vervolg op de bouw van 22-09; bouwrapport
`docs/rapporten/2026-09-22-ter-accordering-bestaanscheck-intussen-extern-geboekt.md`, BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK
'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)"). Lees-only nameting (nameting@ via impersonatie, leesreplica `rlz-sql2-lees`, Cloud Logging,
bot-bestand op main); niets geschreven in RLZ, Odoo of de productiedatabase. Peter keek niet mee; keuzes onder "Keuzes". Tijden UTC tenzij "NL".

**Werkt in productie — per onderdeel:**

| Onderdeel | Uitkomst | Bewijs |
|---|---|---|
| Hercontrole in de échte run van 06:30 NL | **JA** | run `40b5d45c` (executie `rlz-reconciliatie-hhhj7`, 04:30:23–04:48:41): 12 `HERCONTROLE`-regels, 82 open documenten vers getoetst, **0 overgeslagen**, geen `OVERGESLAGEN document`-regel |
| Bevindingssoort `intussen_extern_geboekt` | **JA — 11 stuks, exact de verwachting van 22-09 + 1** | Bouwadvies 8, Molenhof Beheer 1, Rubicon 1 (alle tien boekstukken uit de meting van 22-09) + Universal Steigerbouw 1 van 43 (RLZ-04-00003305) |
| Stand `actie`, geen meetfase | **JA** | registry `soort_stand.py`: `default=ACTIE` + `direct_actie_reden`; 11 < explosie-rem 50; het kantoor opende `GET /reconciliatie/bevindingen?soort=aandacht` 4 × (200) |
| Actiemail | **JA** | `reconciliatie_run.mail_status` = `actie=verzonden;systeem=uitgeschakeld`, `mail_verzonden_op` 04:48:44; delta `nieuwe_afwijkingen` 49, `nieuwe_let_op` 12, `verdwenen_afwijkingen` 11, `blokken_fout` [] |
| Meetlat `nameting.sh reconciliatie-alles --lees-only` (bot-bestand) | **JA** | `verkenning/nameting-reconciliatie-23-09.txt` (commit `3e358ba`, run 35866385279, 13:20 op image `3e17648`): 15 `HERCONTROLE`-regels (119 open), dezelfde 11 treffers, 0 overgeslagen |
| Server als poort (akkoord = 409 `WachtOpKantoor`) | **JA** | 32 × `POST …/accordering/documenten/4d25c900…/akkoord` → 409, 09:18:45–09:20:07, één iPhone (iOS 18.7, WKWebView-user-agent), latency 0,09–0,19 s; 0 × 5xx |
| Herinnering 09:00 NL slaat extern-geboekte documenten over | **JA — cent-exact nagerekend** | job 07:00:35: "0 push, 2 e-mail, 6 accordeur(s) zonder open werk"; `accordeur_herinnering` 23-09: 13 en 45; reconstructie aan-de-beurt om 07:00:30 uit de stappen: 15 en 46 → precies min de 2 (Molenhof + Rubicon) resp. 1 (Universal) extern-geboekte documenten |
| Wachtrij accordeur-app (`GET /accordering/wachtrij`) | **JA (server)** | sinds de run 35 × 200, 2 × 401 (verlopen sessie), 0 × 5xx; items mét `extern_geboekt` uit dezelfde bron `open_treffers`: 3 (Molenhof, Rubicon, Universal — de 8 Bouwadvies-documenten hebben geen open ronde) |
| Banner in de app op het toestel | **NIET GEMETEN** | de laag-2-accordeur van Universal tikte 32 × "Akkoord" op een document mét open treffer — in de bundel mét de banner bestaat die knop niet; welke bundel het toestel draaide is niet leesbaar (geen toestel-registratie per bundel); bundel `8fb41a9-20260922-2105` mét de feature stond klaar sinds 22-09 21:06 (toepassen bij de volgende start) |
| Handelingen "Afwijzen — al geboekt als …" / "Toch verschillend" | **NIET GEMETEN (ongebruikt)** | 0 × `POST …/extern-geboekt/afwijzen|toch-verschillend` sinds de deploy; audits `document_afgewezen` / `extern_duplicaat_toch_verschillend` / `accordering_vervallen` sinds 22-09 21:00 = 0; `reconciliatie_acceptatie` sinds de deploy = 0 |
| Boekfout ná laatste akkoord mét `extern_geboekt`-kern | **NIET GEMETEN** | de 8 Bouwadvies-boekfouten dateren van 21-09 17:15 (vóór de deploy) en dragen alleen de tekst, geen kern; er was sinds de deploy geen nieuwe boekpoging ná een laatste akkoord |

**Één regel voor Peter:** de dagelijkse hercontrole werkt in productie en vond vanochtend 11 documenten die bij ons op klant-akkoord wachten
maar al in Reeleezee staan; de accordeurs krijgen er geen herinnering meer voor en de server weigert een akkoord erop (vanochtend 32 keer bij
Universal). Niemand op kantoor heeft de knoppen nog gebruikt — de 11 rijen staan op Inzicht › Reconciliatie klaar.

## Stap 0 — deploy-check (service ÉN jobs)

- `git fetch` + `git rev-list --count main..origin/main` = 0 (en `origin/main..main` = 0) bij de start; geen merge nodig.
- Feat-commit `ac87d02` + docs `8fb41a9` gedeployd door run 35783956239 (22-09 21:00–21:15, groen); daarna groen: `63a0499`, `ac7639b`
  (00:51), `3e17648` (07:47); `a30a857` (bot-merges) liep tijdens deze run (16:11).
- Op het meetmoment (16:10): service `rlz-backend` én de jobs `rlz-reconciliatie`, `rlz-accordeur-herinneringen`, `rlz-nieuwe-facturen`,
  `rlz-boek-wachtrij` allemaal op image `3e17648` (`spec.template.spec.template.spec.containers[0].image`). De échte run van 04:30 liep op de
  image van deploy `ac7639b` (de laatste groene deploy vóór 04:30; bevat `ac87d02`).

## Stap 1 — de échte run van 23-09 06:30 NL (run `40b5d45c`)

Job-log executie `rlz-reconciliatie-hhhj7`, 04:33:58 (documenten-blok) t/m 04:48:44 (RUN-slotregel "828 bevinding(en); mail:
actie=verzonden;systeem=uitgeschakeld"). `HERCONTROLE`-regels (alleen administraties mét open werk; 0 overgeslagen bij élke):

| Administratie | Open vers getoetst | Treffers |
|---|---|---|
| Bouwadvies Oost Nederland B.V. (`a265c010`) | 13 | 8 |
| Universal Steigerbouw B.V. (`3ee6edf0`) | 43 | 1 |
| Kempen Facilities B.V. (`66e1e296`) | 11 | 0 |
| Rubicon Investments B.V. (`35d106f2`) | 6 | 1 |
| BLOw B.V (`5419878c`) | 2 | 0 |
| Molenhof Beheer B.V. (`f13f30c2`) | 1 | 1 |
| Meyer, Midden Nederland Beheer, Oirschot Recreatie, Oirschot Vastgoed Beheer, Veldhoven Recreatie, Zilver Beheer | 1 elk | 0 |
| **Totaal** | **82** | **11** |

Bevindingen in `reconciliatie_bevinding` (leesreplica per administratie, run `40b5d45c`, blok `documenten`, soort `afwijking`,
`afwijking_soort` = `intussen_extern_geboekt`, `geaccepteerd` false, `match_basis` `referentie` behalve waar vermeld):

| Administratie | Document | Status | Referentie | Bedrag module | Extern boekstuk | Extern datum | Ronde |
|---|---|---|---|---|---|---|---|
| Bouwadvies | `1d0c5e75` | ter_accordering | F/2026/00053 | 2.381,75 | RLZ-04-00000516 (`referentie_ander_bedrag`) | 01-09 | afgerond 18-09, boek_fout |
| Bouwadvies | `8c558b35` (casus) | ter_accordering | F/2026/01235 | 173,84 | RLZ-04-00000518 | 26-08 | afgerond 21-09, boek_fout |
| Bouwadvies | `38b1401d` | ter_accordering | F/2026/01238 | 15.623,57 | RLZ-04-00000519 | 26-08 | afgerond 21-09, boek_fout |
| Bouwadvies | `7598432f` | ter_accordering | F/2026/01237 | 12.566,10 | RLZ-04-00000520 | 26-08 | afgerond 21-09, boek_fout |
| Bouwadvies | `df0ced2a` | ter_accordering | F2615113 | 2.297,43 | RLZ-04-00000521 | 28-08 | afgerond 21-09, boek_fout |
| Bouwadvies | `798be678` | ter_accordering | VF2607986 | 27.337,77 | RLZ-04-00000523 | 02-09 | afgerond 21-09, boek_fout |
| Bouwadvies | `3ea1aac3` | ter_accordering | C2615322 | −617,20 | RLZ-04-00000524 | 04-09 | afgerond 21-09, boek_fout |
| Bouwadvies | `4997f2c4` | ter_accordering | VCB260464 | −135,34 | RLZ-04-00000526 | 08-09 | afgerond 21-09, boek_fout |
| Molenhof Beheer | `07bec3b5` | ter_accordering | 200161832 | 107,69 | RLZ-17-00001131 | 08-09 | open, laag 3 aan de beurt |
| Rubicon Investments | `62639fbf` | ter_accordering | F239153280 | 61,24 | RLZ-04-00002358 | 29-07 | open, laag 3 aan de beurt |
| Universal Steigerbouw | `4d25c900` | ter_accordering | 26191 (Floor Bouwliftenservice) | 802,23 | RLZ-04-00003305 (Status 2, € 802,23) | 13-08 | open, laag 1 akkoord 21-09, laag 2 aan de beurt |

- **Exact de verwachting van 22-09** (Bouwadvies 8 mét dezelfde acht boekstukken, Molenhof 1, Rubicon 1) plus de vooraf niet meetbare
  Universal-kant: 1 van 43. **Correctie op het bouwrapport van 22-09:** Universal Steigerbouw draait in productie op `boekhoud_backend` `rlz`
  (leesreplica), niet op Odoo — de 43 zijn dus gewoon tegen RLZ getoetst; de Odoo-overstap bestaat alleen op de dev-administratie.
- De Universal-treffer is echt: Floor Bouwliftenservice, factuurnummer 26191, € 802,23 aan beide kanten, factuurdatum 13-08; het document
  kwam 21-09 09:37 in de module en RLZ-04-00003305 stond er al (Status 2, Open).
- Stand: het detail draagt geen `stand`-veld — de stand komt uit de registry (`default=ACTIE`, `direct_actie_reden` gepind door
  `test_soort_stand.py`); 11 < 50 dus de explosie-rem bleef stil. Actiemail verzonden om 04:48:44; de systeemmail bleef `uitgeschakeld`
  (onderwerp zou zijn "[systeem] RLZ reconciliatie 23-09-2026: 708 afwijking(en) · 61 nieuwe aandachtspunt(en)").
- **De 8 Bouwadvies-rondes zijn afgerond** (alle lagen akkoord, 18-09 / 21-09) mét `boek_fout` van 21-09 17:15 "Boeken geblokkeerd door harde
  checks: 1 bestaande factuur/facturen in RLZ met dezelfde crediteur en referentie — al geboekt in Reeleezee: RLZ-04-00000518 …" — van vóór
  de deploy, dus zónder `extern_geboekt`-kern: het controlescherm toont voor die acht nog de oude boekfout-tekst tot iemand opnieuw boekt;
  de rij op Inzicht › Reconciliatie draagt de twee knoppen wél (`ExternGeboektActies` op de bevinding). De drie andere staan in een open
  ronde en dus in een wachtrij mét banner-kern.

## Stap 2 — meetlat `reconciliatie` (bot-bestand op main)

`verkenning/nameting-reconciliatie-23-09.txt` (commit `3e358ba` door nameting-bot, workflow-run 35866385279 onderdeel `alles`, 13:20 op image
`3e17648`; lees-only, geen run-rij): 15 `HERCONTROLE`-regels (119 open — meer dan om 04:30 omdat het kantoor overdag 12 VGG-, 4
Mantelzorgwoningen- en 2 Necol-documenten aanbood en Kempen Facilities 11 → 22 groeide), 0 × `OVERGESLAGEN document`, dezelfde 11
`intussen_extern_geboekt`-regels als de échte run (identieke vingerafdrukken). Er is dus geen extra dispatch nodig geweest; de meting telt als
bot-bestand op main.

## Stap 3 — accordeur-kant

- **Wachtrij:** `GET /accordering/wachtrij` sinds 04:48: 35 × 200, 2 × 401 (10:33, verlopen sessie — geen app-fout), 0 × 5xx; eerste
  aanroep 07:24. Het aantal items mét `extern_geboekt` staat niet in het request-log (body) en volgt uit dezelfde bron `open_treffers`: 3
  (Molenhof `07bec3b5`, Rubicon `62639fbf`, Universal `4d25c900`); de 8 Bouwadvies-documenten hebben geen open ronde en staan in geen wachtrij.
- **Server als poort — bewezen:** 09:18:45–09:20:07 kwamen **32 × `POST …/administraties/3ee6edf0…/accordering/documenten/4d25c900…/akkoord`
  → 409** binnen, in drie salvo's (7, 18, 7) mét tussendoor `GET /accordering/wachtrij` 200, allemaal vanaf één iPhone (iOS 18.7,
  WKWebView-user-agent zonder Safari-token = de native app), latency 0,09–0,19 s. In het akkoord-pad is 409 uitsluitend `WachtOpKantoor`
  (`NietAanDeBeurt` = 403, `GeenOpenAccordering` = 404); de actor was de laag-2-accordeur van dat document (`8d7df5fe`, die vandaag 36
  Universal-documenten akkoord gaf). De besluit-wachtrij van de app herhaalt alleen bij ≥ 500 (`besluitQueue.ts::isTijdelijkeFout`), dus dit
  waren 32 handmatige tikken — de knop stond dus op dat toestel nog in beeld, wat in de bundel mét de banner niet kan (review-actiebalk
  alleen als `!huidige.extern_geboekt`). Welke bundel het toestel draaide is niet leesbaar (`platform.app_bundel` registreert bundels, geen
  toestellen); de bundel mét de feature (`8fb41a9-20260922-2105`) stond klaar sinds 22-09 21:06 en wordt bij de volgende start toegepast.
  Uitkomst: **poort JA, banner op dat toestel niet gemeten**. Geen 5xx op de accordering- of reconciliatie-routes sinds de run.
- **Herinnering 09:00 NL** (`rlz-accordeur-herinneringen` 07:00:35–07:00:37): "0 push, 2 e-mail, 0 al verzonden vandaag, 0 overgeslagen (geen
  kanaal), 6 accordeur(s) zonder open werk, 0 mislukt". `platform.accordeur_herinnering` 23-09: accordeur `b679290f` `aantal_open` 13,
  accordeur `8d7df5fe` 45. Reconstructie van "aan de beurt om 07:00:30" uit `document_accordering` × `accordering_stap` over hun volledige
  scope (rondes open op dat moment; eerste vereiste stap zonder besluit of mét besluit ná 07:00:30), per administratie in eigen RLS-scope,
  exitcode per iteratie gelogd, allemaal rc 0: `b679290f` 15 (Rubicon 6 incl. `62639fbf`, Bouwadvies 5, Molenhof 1 = `07bec3b5`, Meyer 1,
  Oirschot Vastgoed 1, Zilver 1) en `8d7df5fe` 46 (Universal 37 incl. `4d25c900`, Kempen Facilities 7, Oirschot Recreatie 1, Veldhoven 1).
  **15 − 2 = 13 en 46 − 1 = 45: de herinnering telde precies de extern-geboekte documenten niet mee.** De 09:00-herinnering kende geen 409
  (het is een job, geen route); de handmatige herinnerknop is niet gebruikt.
- **Nieuwe-facturen-bundelmelding** (`rlz-nieuwe-facturen`, elke 10 min): sinds de run steeds "0 document(en) nieuw gemeld" — er kwam geen
  nieuw werk voor een accordeur mét treffer bij, dus het skip-pad is hier niet apart meetbaar (zelfde bron als de herinnering).

## Stap 4 — handelingen door het kantoor

- Request-log sinds 22-09 21:00: **0 × `POST …/extern-geboekt/afwijzen`, 0 × `…/toch-verschillend`**.
- `platform.audit_event` sinds 22-09 21:00: 0 × `document_afgewezen`, 0 × `extern_duplicaat_toch_verschillend`, 0 × `accordering_vervallen`, 0 rijen
  mét "Al geboekt in Reeleezee" of de marker `accordering_vervallen_extern_geboekt` in de nieuwe waarde (de enige treffers op het patroon waren
  16 `uren_herinnering_*`-audits); `reconciliatie_acceptatie` sinds de deploy: 0.
- Het kantoor keek wél: `GET /reconciliatie/stand` 75 ×, `/reconciliatie/run/laatste` 4 ×, `/reconciliatie/bevindingen?pagina=1&soort=aandacht` 4 ×
  (alle 200). Geen klik = **niet gemeten (ongebruikt)**, niet "werkt niet".

## Beslispunten voor Peter (geen codefout gevonden)

1. **11 documenten wachten op één klik op Inzicht › Reconciliatie (stand 23-09, run `40b5d45c`, leesreplica): Bouwadvies 8 × RLZ-04-00000516 t/m 526 (26-08 t/m 08-09, € −617,20 … € 27.337,77, o.a. `8c558b35`), Molenhof 1 × RLZ-17-00001131 (08-09, € 107,69, `07bec3b5`), Rubicon 1 × RLZ-04-00002358 (29-07, € 61,24, `62639fbf`), Universal 1 × RLZ-04-00003305 (13-08, € 802,23, `4d25c900`)** — "Afwijzen — al geboekt als ‹boekstuk›" of "Toch verschillend — doorgaan"; tot die klik blijven de drie open rondes mét banner in de app staan (bewust: nooit stil weg).
2. **Universal / Floor Bouwliftenservice 26191 → RLZ-04-00003305 (13-08, € 802,23, document `4d25c900`, rlz_document `3f40c1fb`, leesreplica run `40b5d45c`):** buiten de module geboekt op 13-08 terwijl het document 21-09 via de module binnenkwam en laag 1 dezelfde dag akkoord gaf; de laag-2-accordeur tikte 32 × "Akkoord" en kreeg 32 × de servertekst — vraag aan Universal wie op 13-08 rechtstreeks in RLZ boekte (via de API niet leesbaar, zie het bouwrapport).
3. **Bouwadvies = werkwijze, geen incident (herbevestigd 23-09: 8 van 13 wachtende facturen, RLZ-04-00000516 t/m 526, 26-08 t/m 08-09, € −617,20 … € 27.337,77, documenten `1d0c5e75` e.a., leesreplica run `40b5d45c`):** de drie akkoorden van 16→21-09 waren voor niets; afspraak met het kantoor of Bouwadvies nodig over wie rechtstreeks in Reeleezee boekt.

## Keuzes (Peter keek niet mee)

1. **Geen extra dispatch `reconciliatie` gestart:** het bot-bestand van 13:20 (onderdeel `alles`) bevat het reconciliatie-onderdeel en de
   `HERCONTROLE`-regels; nog een run zou alleen RLZ-calls kosten.
2. **Herinnering-skip bewezen via reconstructie, niet via mailinhoud:** de mail wordt niet bewaard; de aan-de-beurt-stand op 07:00:30 is uit de
   stappen (besloten_op) herleidbaar en sluit cent-exact — in de regels als meetrecept vastgelegd.
3. **De 32 × 409 als "poort JA, banner niet gemeten" gelezen**, niet als fout: de server deed precies wat de regel zegt; welke bundel het toestel
   had is niet leesbaar en de feature-bundel bestond pas sinds 22-09 21:06.
4. **Handelingen = "niet gemeten (ongebruikt)"** → vervolg-opdracht poging 2 (`niet vóór: 2026-09-24 09:00`) én het meetrecept als
   dispatch-onderdeel `extern-geboekt` (regel 21-09: vier plekken — if-tak, `options:`, `via_gh_onderdeel`, `OORDEEL_BRON` — plus guard):
   request-log handelingen + accordeur-409 + job-log `HERCONTROLE` + `db-lezen reconciliatie-bevindingen` per administratie; oordeelregel "POST
   afwijzen 200 = A, toch-verschillend 200 = B, 5xx = C, accordeur-409 = D, bevindingsregels job-log = E".
5. **Bouwrapport-fout gecorrigeerd in de regels** (Universal = RLZ in productie), niet in het bouwrapport zelf (historisch document).

## Poort

- `tests/unit/test_nameting_workflow.py` 41 passed (incl. de twee nieuwe guards voor `extern-geboekt`); YAML parse + `bash -n` op de meet-stap en
  op `scripts/gcp/nameting.sh` schoon; docs-guards (rapporten-index, gelezen regels, klikpunten, CLAUDE.md-verwijzingen, regels-index) groen —
  zie de commit. Geen backend-/frontend-code geraakt.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT; regelaantallen = stand vóór deze run):
- `docs/regels/reconciliatie.md` (285 regels; 297 ná deze run)
- `docs/regels/accordering-native-app.md` (388 regels; 405 ná deze run)
- `docs/regels/duplicaten-crediteuren.md` (143 regels; 152 ná deze run)
- `docs/regels/werkloop-productie.md` (319 regels; 332 ná deze run)
