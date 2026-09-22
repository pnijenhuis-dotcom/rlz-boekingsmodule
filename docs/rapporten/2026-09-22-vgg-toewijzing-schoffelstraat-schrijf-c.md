# Rapport 22-09 — VGG → Odoo: toewijzing pand Schoffelstraat 29 + soort `verkoop` op RLZ-01-00000082 UITGEVOERD (werkt in productie: ja) → `plan` = bewijspaar VERTAALBAAR → SCHRIJF c GESTRAND op de pand-analytic-pseudo-sleutel (niets gepost; instrumentfout gefixt + guard; poging 2 ná deploy)

Opdracht: `opdrachten/gedaan/2026-09-22-vgg-toewijzing-schoffelstraat-29-plus-schrijf-c.md` (beslispunt 1 Peter 21-09). Geen migratie.
**Odoo-writes in deze run (company 6, kill-switch als executie-override): 2 partners + 2 concepten aangemaakt, 0 gepost, 0 statement lines
(§3).** Alles op de gedeployde job-image `51555f6` (service = job); nooit lokaal tegen productie.

**Werkt in productie: toewijzing JA (dry-run → `--schrijf` → tweede `--schrijf` "ongewijzigd", audit + registerrijen op de leesreplica) ·
`plan` JA (vier lees-only executies; bewijspaar vertaalbaar) · SCHRIJF c NEE (gestrand op stap 3, systeemfout van de bouw — fix + guard in
deze run, poging 2 = vervolg-opdracht ná deploy) · zevende meting (replay ná de toewijzing): JA gemeten (bot `a3b2455`): bewijspaar = de ene vertaalbare out_invoice, herclassificatie `ongemapt:8000 → 3608` € −400.000,00, per pand Schoffelstraat 29 Verkoop € 400.000,00 (sluit niet: aankoop-memorialen op ongemapte 1100/1601 = beslispunt 2).**

## 0. Stap 0 — deploy-check (13:00 NL)
`git rev-list --count main..origin/main` = 0; service `rlz-backend` én job `rlz-reconciliatie` op `backend:51555f69…` (= HEAD, bevat `81f65d9`
mét `backend/app/panden/toewijzen_cli.py`); job-startcommando `python`. Deploy-run van `51555f6` stond nog op `in_progress` (smoketest-stap)
terwijl beide images al `51555f6` meldden — het image is het criterium, niet de workflow-status.

## 1. Stap 1–2 — `pand-toewijzen` dry-run → schrijven → idempotentie (werkt in productie: JA)
| Executie | Aanroep | Uitkomst |
|---|---|---|
| `rlz-reconciliatie-czbjf` | dry-run | "DRY-RUN — niets geschreven"; RLZ-document RLZ-01-00000082 in **Receipts**, id `8b079e5c-aeba-4776-9097-31d2686184f6`, datum 2026-03-19, bedrag € 400000.00, relatie "Ouwekerk Notariaat"; pand `schoffelstraat-29` — Schoffelstraat 29, Purmerend · dossier 2026.079950.01 → **nieuw**; pand_boeking soort verkoop · herkomst mens · zekerheid hoog · bron rlz:8b079e5c… → **nieuw**; actor `b679290f…` (Peter); audit teruggedraaid |
| `rlz-reconciliatie-czxnd` | `--schrijf` | **GESCHREVEN** — zelfde regels, pand nieuw, pand_boeking nieuw, audit `pand_toegewezen_mens`, `pand_boeking_toegewezen_mens` |
| `rlz-reconciliatie-7v2lm` | `--schrijf` (2e) | pand → **bestaand**, pand_boeking → **ongewijzigd**, audit **geen (ongewijzigd)** — idempotent |

Verwachting uit de opdracht (precies één treffer, € 400.000,00, 19-03-2026, pand nieuw/verkocht/verkoopdatum 19-03-2026, boeking nieuw/verkoop/mens/hoog):
**exact gehaald.** Kleine afwijking t.o.v. de opdrachttekst: RLZ spelt de relatie "Ouwekerk Notariaat" (zonder r), de bankomschrijving zegt
"Ouwerkerk Notariaat" — zelfde partij (IBAN NL71RABO0360567371), geen handeling.

Leesreplica (`db_lezen.sh`, als Beheerder, scope `cc07e461-…`):
- `platform.audit_event`: precies 2 rijen `pand_toegewezen_mens` (record `57ff15d5-…`, nieuw = code schoffelstraat-29, status verkocht,
  herkomst mens, verkoopdatum 2026-03-19, dossier [2026.079950.01], opdracht "Peter 21-09 — VGG beslispunt 1 …", oud = null) en
  `pand_boeking_toegewezen_mens` (record `48771202-…`, nieuw = verkoop/mens/hoog, € 400000.00, 2026-03-19, reden "opdracht Peter 21-09 —
  Toewijzing pand + soort verkoop voor het bewijspaar (bankkoppeling 00112)"), beide 2026-09-22 11:08:32 UTC.
- `boekhouding.pand` 1 rij (code schoffelstraat-29, verkocht, mens, verkoopdatum 2026-03-19, `rlz_project_id` leeg), `boekhouding.pand_boeking`
  1 rij (verkoop, mens, hoog, 400000.00, 2026-03-19, `bevestigd_door` = Peters id, `bevestigd_op` 11:08:32 UTC). Het productieregister van
  VGG was leeg (0/0) en telt nu 1/1.
- Consistentie mét de afleiding: de nameting van die ochtend (`nameting-vgg-panden-22-09.txt`, dry-run adres-bron) stelde hetzelfde pand voor
  ("Schoffelstraat 29 | Purmerend | 2026-03-20 | dossier 2026.079950.01 | aankoop 1/1/0 … verkoop 1/0/0 | zou nieuw zijn") mét dezelfde code →
  een latere `pandenregister-afleiden --schrijf` hergebruikt dit pand; mens wint.

## 2. Stap 3 — `plan` (vier lees-only dry-runs, `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"`, 13:12–13:32 NL): bewijspaar VERTAALBAAR
| Commando | Executie | Uitkomst |
|---|---|---|
| `odoo-koppeling-migratiedoel --dry-run` | `rlz-reconciliatie-drn8g` | AL MIGRATIEDOEL — ongewijzigd (idempotent); dagboeken F 48 / LF 49 / MEM / BNK1 53; outstanding payments 135000 (id 132) |
| `vgg-rekeningen` | `-nrvt6` | vijf rollen bestaan en hergebruikt: 3606 · 325000, 3607 · 326000, **3608 · 803100 Opbrengst verkoop panden**, 3609 · 701300, 3610 · 159100; analytic Overhead 848 |
| `vgg-odoo-stap0 --dry-run --stap 0-6 --max-per-type 1 --boekstuk RLZ-01-00000082` | `-brj4t` | replay-mapping 361; "replay: 2180 moves, selectie 2026-03 (maand van bewijspaar): in_invoice 1 · entry 0 · out_invoice 1 · **paar: out_invoice RLZ-01-00000082 ↔ 1 bankregel(s) (2026-03-20)**"; stap 3 "ZOU aanmaken: RLZ-01-00000082 (rlz 8b079e5c…) anker 957f690d-… — 1 regels **→ ZOU POSTEN (bewijspaar)**"; stap 0 ZOU Gimple B.V. [naam] + Ouwerkerk Notariaat [iban]; stap 1 ZOU RLZ-04-00000431 (Gimple); **KLIKPUNT PETER: IBAN op BNK1 is leeg — stap 4 en 5 overgeslagen** |
| `vgg-odoo-migratie --dry-run` | `-d7smw` | mapping 361; **229 vertaalbare documenten** (17-09: 224), 1034 bankregels, 908 niet vertaalbaar; **pand-eis afwijkingen 41** (17-09: 39); C/D niet uitgevoerd |

Op 17-09 stond hier "niet vertaalbaar (grootboek zonder Odoo-rekening: 8000)". Ná de toewijzing (herkomst `mens` → `pand_telt`) herclassificeert
de 8000-regel naar rol `opbrengst_panden` (803100) en is het paar vertaalbaar — precies wat beslispunt 1 beoogde. De stap0-dry-run kon de
analytic-kant niet tonen (zie §3): dat is de instrumentfout van deze run.

**Bijvangst — klikpunt IBAN BNK1 (nu voor het eerst bereikt; op 17-09 kwam de run niet tot stap 4):** dagboek BNK1 in company 6 heeft geen IBAN
→ het script slaat statement line + reconcile over ("rest doorgelopen", ontwerp blok 7). Zonder IBAN post SCHRIJF c het bewijspaar wél, maar
reconcilieert niet: de per-pand-sluit-eis (7d) is dan niet toetsbaar. **Handeling Peter: IBAN van de VGG-bankrekening op dagboek BNK1 zetten in
Odoo (Boekhouding › Configuratie › Dagboeken › BNK1 › Bankrekening).**

## 3. Stap 4 — SCHRIJF c: GESTRAND op stap 3 (executie `rlz-reconciliatie-zp7xs`, 13:37 NL, exit 1; niets gepost)
| # | Stap | Werkt | Detail |
|---|---|---|---|
| 0 | partners | **ja** | aangemaakt partner **275** (Gimple B.V.) [naam]; aangemaakt partner **276** (Ouwerkerk Notariaat) [iban NL71RABO0360567371] |
| 1 | inkoopfactuur concept | **ja** | concept **3369**: RLZ-04-00000431 (rlz c897b7ac-…) anker ac177712-… — 1 regels (draft; de paar-factuur is de verkoop, dus stap 1 blijft concept) |
| 2 | memoriaal | niet uitgevoerd | geen vertaalbaar document van dit type |
| 3 | verkoopfactuur = bewijspaar | **nee** | **FOUT RLZ-01-00000082 (rlz 8b079e5c-…) anker 957f690d-… — 1 regels: `Odoo account.move.action_post -> 500 builtins.ValueError: invalid literal for int() with base 10: 'pand:schoffelstraat-29'`** (4 × HTTP 500 in het log = de retry) |
| 4–5 | statement line / reconcile | niet uitgevoerd | overgeslagen: stap 1–3 niet groen |
| 6 | terugweg | niet uitgevoerd | niets om terug te draaien |

Stand company 6 ná de run: partners 2 aangemaakt, geposte boekingen 0, **concepten 2** (`account.move` totaal niet-cancel 2), statement lines 0.
Audit (replica, tabel `odoo_migratie`, 11:37:55–58 UTC): `odoo_migratie_partner_aangemaakt` 275 + 276, `odoo_migratie_move_aangemaakt` **3369**
(in_invoice, ref 2026-0169, date 2026-03-01, journal 49) en **3370** (out_invoice, ref 171384, date 2026-03-19, journal 48, state draft) —
**3370 is het bewijspaar en draagt de pseudo-sleutel `pand:schoffelstraat-29` in zijn regel.** Beide concepten blijven staan (nooit unlink;
idempotent op anker `mig:<anker>`).

**Oorzaak (instrumentfout van de bouw, geen data-fout):** `vertaling.py` schrijft de analytic van een pand-regel als pseudo-sleutel
`{"pand:<code>": 100}` en zegt letterlijk "Company 6 kent nog geen pand-analytics: … run 3 zoekt/maakt de analytic aan — lookup-vóór-create".
Dat schrijfpad is nooit gebouwd; alle eerdere SCHRIJF-c-pogingen strandden vóór stap 3 ("niet vertaalbaar"), en de dry-run kon het niet laten
zien omdat Odoo de JSON van `analytic_distribution` bij `create` accepteert en pas bij `action_post` naar een analytic-id probeert te casten.
Vandaag was RLZ-01-00000082 het eerste document mét pand-analytic dat het schrijfpad bereikte.

**Waarom het script exit 1 gaf zonder rapport:** `vgg_blok7_odoo_writes.sh::execute` liep onder `set -euo pipefail` uit de functie zodra
`gcloud run jobs execute --wait` een mislukte executie meldde — vóór het Cloud-Logging-lees. Het rapport stond alleen in het log van `-zp7xs`
(`.scratch/vgg-schrijf-c/stap4-schrijf-c-log.txt`). Gefixt (§4, punt 6).

## 4. Fix + guard (dezelfde run; geen migratie, geen Odoo-writes)
1. **`odoo_schrijf.PandAnalyticOplosser`** — `pand:<code>` → écht `account.analytic.account`-id: lookup-vóór-create op (`code` = pand-code,
   `plan_id` = `analytic_plan_id` van de doelkoppeling (Project-plan uit de migratiedoel-probe), `company_id ∈ {6, False}`, incl. gearchiveerd):
   één actief = hergebruik (audit `odoo_migratie_analytic_hergebruikt`), méér = `AnalyticMeerduidig` (mens kiest), alleen gearchiveerd =
   `AnalyticNietOpgelost` ("heractiveer in Odoo"), géén = `create {name: <adres uit MoveVoorstel.pand>, code, plan_id, company_id}` + terug-lezen
   (company-toets) + audit `odoo_migratie_analytic_aangemaakt`; cache per run, één rapportmelding per pand ("analytic pand:<code> → N
   (aangemaakt|hergebruikt)"). Zonder plan-id: aanmaken = zichtbare blokkade per document, nooit een pseudo-sleutel naar Odoo.
2. **Guard aan de schrijfgrens:** `maak_concept_move` weigert élke vals waarvan een regel nog een `pand:`-sleutel draagt
   (`AnalyticNietOpgelost`) vóór er ook maar één Odoo-call gaat.
3. **Herstel van bestaande concepten:** `herstel_regels(move_id)` leest de regels van een gevonden concept (`account.move.line search_read`
   op `move_id`) en schrijft per regel mét pseudo-sleutel de opgeloste distributie (`write`, audit `odoo_migratie_regel_analytic_hersteld`
   oud→nieuw). Nodig omdat het anker idempotent is: poging 2 vindt concept 3370 terug en zou zonder herstel opnieuw op dezelfde 500 stranden.
4. **Beide schrijfpaden:** `vgg-odoo-stap0` (stap 1–3) en `vgg-odoo-migratie` (fase A) roepen `oplosser.vervang(vals, pand=…)` vóór
   `maak_concept_move` en `herstel_regels` erna; de dry-run toont per document "analytic pand:<code> → bestaand N (hergebruik) | → ZOU aanmaken
   (<adres>, plan P) | STOP — <reden>", de migratie-dry-run telt `pand-analytics`. Nieuw parameter `analytic_plan_id` (CLI-runners:
   `cli_odoo.analytic_plan_id_voor` = doelkoppeling).
5. **`MoveVoorstel.pand`** (code/adres/soort) reist mee vanuit de vertaling (voor de analytic-naam); contract `test_moves_vorm_contract` uitgebreid.
6. **`scripts/gcp/vgg_blok7_odoo_writes.sh::execute`:** exitcode vasthouden, log altijd tonen, code teruggeven — een gestrande executie is
   een uitkomst mét rapport, geen stille exit.
7. **Tests:** `tests/migratie/test_odoo_schrijf.py::TestPandAnalyticOplosser` (7: sleutels, guard, lookup-vóór-create + cache + hergebruik,
   niets-zonder-sleutel, meerduidig/gearchiveerd/geen plan, herstel_regels, dry-run lees-only) + `TestStap0PandAnalytic` (4: schrijf lost op
   en post; **reproductie concept 3370 mét pseudo-sleutel → "1 regel(s) analytic hersteld" + gepost**; dry-run "ZOU aanmaken (Schoffelstraat 29,
   plan 7)" zonder create; zonder plan zichtbaar en niets gepost) + `test_odoo_migratie_run.py::TestPandAnalytic` (2) + `test_replay.py`
   (contract + `pand` gevuld/None). Drie bestanden: 121 groen; ruff op eigen regels 0.

## 5. Zevende meting — replay ná de toewijzing (nameting-run 35724142036, onderdeel c, lees-only)
Bot-commit `a3b2455` ("nameting 22-09 c — Oordeel: ROOD", 12:03 UTC) → `verkenning/nameting-vgg-replay-22-09.txt` (1.799 regels; vervangt het
bestand van de ochtendrun 05:30 UTC, vóór de toewijzing, `08e7db4`). Lees-only; de replay las de pand-toewijzing uit de DB.
| Onderdeel | Ochtend (vóór toewijzing, `08e7db4`) | Zevende meting (ná toewijzing, `a3b2455`) | Oordeel |
|---|---|---|---|
| Replay-oordeel | ROOD — 3 verschillen (afletter-groepen), 907 niet vertaalbaar | **ROOD — 3 verschillen (dezelfde afletter-groepen), 906 niet vertaalbaar**, 0 leesfouten, memoriaal uit balans 0, geblokkeerd (partner) 2 | gelijk, −1 niet vertaalbaar = het bewijspaar |
| out_invoice vertaalbaar | 0 (71 niet vertaalbaar) | **1** (70 niet vertaalbaar) | het bewijspaar ✔ |
| RJ-220-herclassificatie | — | **`ongemapt:8000 → 3608` € −400.000,00, 1 regel**; saldibalansrij 3608 (803100 Opbrengst verkoop panden) draagt € −400.000,00 aan de RLZ-kant | rol grijpt ✔ |
| Per pand `schoffelstraat-29` | (niet als pand aanwezig) | Aankoop € 0,00 · Aanbetalingen € 20.000,00 · Kosten € 0,00 · **Verkoop € 400.000,00** · Notaris-ontvangst (bank) € 50.952,09 · Marge € 400.000,00 · **SIGNAAL: sluit niet (Δ 349.047,91)** · 2 midden-koppelingen wachten op Toewijzing | verkoop telt ✔; sluit-eis ✘ (verwacht, zie onder) |
| Bewijspaar in de JSON-bijlage | — | `RLZ-01-00000082 out_invoice 2026-03-19 … account_id 3608, "analytic_distribution": {"pand:schoffelstraat-29": 100}, price_unit 400000.00` | **bevestigt §3: de replay levert de pseudo-sleutel** |

**Waarom het pand nog niet sluit (géén nieuwe toewijzing doen — beslispunt 2):** de AANKOOP van Schoffelstraat 29 staat in twee memorialen die
de replay niet vertaalt: `RLZ-06-00000110` (entry, 31-12-2025, € 365.000,00, "grootboek zonder Odoo-rekening: 1100, 1601; balansboeking (pand
schoffelstraat-29) — geen analytic") en `RLZ-06-00000174` (entry, 20-03-2026, € 365.000,00, zelfde ledgers, "pand-voorstel schoffelstraat-29
zekerheid midden"). Twee open punten voor Peter, beide uit de bestaande lijst: (a) RLZ 1100/1601 hebben geen Odoo-rekening in company 6
(ongemapte ledgers = beslispunt 2 uit "VGG — CONCEPT → AUTO-POSTEN", niet een tweede toewijzing), (b) de aankoop-memoriaal is soort `balans`
(geen analytic) — of die als `aankoop` op het pand hoort is een Toewijzing-keuze in de module, niet iets wat een CC-run beslist. De
per-pand-sluit-eis (7d) voor SCHRIJF d blijft daarmee rood voor dit pand tot (a)+(b) beslist zijn; dat staat los van SCHRIJF c (één paar posten).

## 6. Keuzes (Peter kijkt niet mee)
- **SCHRIJF c tóch gestart mét het IBAN-klikpunt open:** de stop-voorwaarden van de opdracht (0/2 treffers, ander pand, niet vertaalbaar) waren
  niet geraakt; het ontwerp van blok 7 (12-09) zegt expliciet "IBAN leeg → stap 4/5 overgeslagen en gemeld, rest doorgelopen" en Peters
  17-09-lijn is "liever 1 boeking testen". Het posten is de boeking-test; de reconcile volgt ná de IBAN. Achteraf: de run strandde vóór het posten.
- **Geen herstel in Odoo:** concepten 3369/3370 en partners 275/276 blijven staan (nooit unlink; anker idempotent) — poging 2 hergebruikt ze en
  herstelt de regel van 3370 mét audit. Geen `button_cancel`: er is niets gepost en de fix maakt het concept juist bruikbaar.
- **Fix in dezelfde run i.p.v. alleen melden:** regel 19-09 poging 2 (systeemfout van de bouw = fix + guard + reproductietest, meetlat opnieuw ná
  deploy). Alternatief "analytic handmatig in Odoo aanmaken + `pand:`-mapping" verworpen: dat blijft klikwerk per pand en laat de guard weg.
- **Zevende meting nu gedispatcht** (lees-only, bot-commit op main → `stop-push.sh` merget): meet het effect van de toewijzing (803100, per pand)
  onafhankelijk van SCHRIJF c.
- **Vervolg-opdracht `niet vóór: 2026-09-22 16:00`:** commit ≈ 15:00 NL ná de suite, deploy ≈ 15:25, marge.

## 7. Klikpunten Peter
1. **IBAN op dagboek BNK1 (Odoo company 6) zetten** — anders blijft SCHRIJF c bij "gepost, niet gereconcilieerd" en is de per-pand-sluit-eis (7d)
   niet toetsbaar; het rapport van poging 2 is dan nog geen volwaardige GO-vraag voor SCHRIJF d.
2. **GO op het rapport van poging 2** (`2026-09-22-vgg-schrijf-c-poging-2-na-deploy-pand-analytic.md`) vóór `SCHRIJF d`.

## Poort (letterlijk)
- pytest volledige suite (achtergrond, alléén): **7130 passed, 2 skipped, 21 deselected in 3190 s (53:10)**, exit 0.
- Docs-guards ná de laatste docs-schrijf los herdraaid: `test_rapporten_index`, `test_rapporten_gelezen_regels`, `test_rapporten_klikpunten`,
  `test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, `test_cc_inbox_claim_en_poort` — 35 passed.
- ruff op de eigen gewijzigde regels (app/migratie ×4, tests/migratie ×3): 0 meldingen (de bestaande, niet-eigen E501's in die bestanden blijven).
- `bash -n scripts/gcp/vgg_blok7_odoo_writes.sh` ok; script-guard `test_writes_script_kent_schrijf_d` groen in de suite.
- vitest/tsc/keten-sweep niet gedraaid: geen frontend- of intake-/documenten-wijziging (keten-guard raakt `app/migratie` niet).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT, kopregel "Domeinen"): `docs/regels/vgg-odoo-migratie.md` (56 regels bij het lezen; 59 regels ná deze
run), `docs/regels/werkloop-productie.md` (260 regels bij het lezen; 276 regels ná deze run).
