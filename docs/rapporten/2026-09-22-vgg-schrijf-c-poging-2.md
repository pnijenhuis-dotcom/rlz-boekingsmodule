# Rapport 22-09 (avond) — VGG → Odoo: SCHRIJF c poging 2 ná de deploy van de pand-analytic-fix — bewijspaar RLZ-01-00000082 GEPOST als F/2026/00001 (werkt in productie: ja) · reconcile niet uitgevoerd (IBAN BNK1 leeg) · per-pand-sluit-eis NIET gehaald → GO-vraag SCHRIJF d mét voorwaarden

Opdracht: `opdrachten/gedaan/2026-09-22-vgg-schrijf-c-poging-2-na-deploy-pand-analytic.md` (vervolg op `docs/rapporten/2026-09-22-vgg-toewijzing-schoffelstraat-schrijf-c.md`
§3–§4; BESLISSINGEN "VGG — BESLISPUNT 1 BESLIST: TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)"). Geen migratie, geen code.
Poging 1 van deze opdracht (20:32) haalde de poort niet en liet alleen de verplaatsing van het opdrachtbestand achter op branch
`wip/2026-09-22-vgg-schrijf-c-poging-2-na-deploy-pand-analytic` (`689172b`); deze poging begon met `git merge --squash` van die branch (geen inhoudelijk werk erin).
**Odoo-writes in deze run (company 6, kill-switch als executie-override, executie `rlz-reconciliatie-8j7ch`, 20:58 NL): 1 analytic account aangemaakt (851),
1 regel van een bestaand concept hersteld (3370 regel 7392), 1 boeking gepost (3370 → F/2026/00001, € 400.000,00), 0 partners, 0 concepten, 0 statement lines.**
Alles op de gedeployde job-image `cc9936b` (service = job); nooit lokaal tegen productie.

**Werkt in productie: SCHRIJF c JA** (analytic lookup-vóór-create + herstel van het kapotte concept + `action_post` — de fix van 22-09 middag werkt op het échte anker) ·
**reconcile NIET UITGEVOERD** (stap 4/5 overgeslagen: IBAN op dagboek BNK1 in company 6 is leeg — klikpunt Peter, ongewijzigd) ·
**per-pand-sluit-eis (7d) NIET gehaald** — niet door de IBAN, maar door de data: pand Schoffelstraat 29 sluit niet (Δ € 349.047,91, aankoop-memorialen op
ongemapte ledgers 1100/1601 = beslispunt 2) en de migratie-dry-run telt 41 panden "sluit niet" → **`SCHRIJF d` zou vandaag NIETS posten** (toets B rood = niets posten, bedoeld gedrag).
Achtste meting (replay, nameting-run 35770964986 onderdeel c): zie §4.

## 0. Stap 0 — deploy-check (20:34 NL)
`git fetch origin && git rev-list --count main..origin/main` = 0 (en `origin/main..main` = 0). Service `rlz-backend` én job `rlz-reconciliatie` op
`backend:cc9936b6f2be…` — `git merge-base --is-ancestor cb9ba7d cc9936b` = ja, dus het image draagt `backend/app/migratie/odoo_schrijf.py::PandAnalyticOplosser`
(commit `cb9ba7d`, 14:52). Deploy-runs `cc9936b` (35766756542), `11b1544`, `142f33c`, `a3f6f94` (bevat `cb9ba7d`) alle `success`. Voorwaarde gehaald, geen terugleg.

## 1. Stap 1 — `plan` (vier lees-only dry-runs, `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"`, 20:36–20:56 NL): fix LIVE, bewijspaar vertaalbaar
| Executie | CLI | Uitkomst |
|---|---|---|
| `rlz-reconciliatie-n7gpp` | `odoo-koppeling-migratiedoel --dry-run` | AL MIGRATIEDOEL — ongewijzigd (idempotent); probe groen: analytic_plan ok, BNK1 id 53, LF 49, F 48, MEM, outstanding_payments 135000 (id 132) |
| `rlz-reconciliatie-cwj6p` | `vgg-rekeningen` | vijf rollen + Overhead (848) bestaand, niets te maken |
| `rlz-reconciliatie-c2xv2` | `vgg-odoo-stap0 --dry-run --stap 0-6 --boekstuk RLZ-01-00000082` | replay 2180 moves, selectie 2026-03: in_invoice 1 · out_invoice 1 · paar RLZ-01-00000082 ↔ 1 bankregel (2026-03-20); stap 3 "ZOU aanmaken: RLZ-01-00000082 … → ZOU POSTEN (bewijspaar)" **gevolgd door "analytic pand:schoffelstraat-29 → ZOU aanmaken (Schoffelstraat 29, plan 1)"**; stap 4/5 "IBAN op dagboek BNK1 is LEEG — klikpunt Peter" |
| `rlz-reconciliatie-2nmpn` | `vgg-odoo-migratie --dry-run` | 229 vertaalbare documenten, 1034 bankregels, 908 niet vertaalbaar; fase A tellers documenten 229 · zonder partner 0 · **pand-analytics 39** (39 × "ZOU aanmaken (…, plan 1)", incl. schoffelstraat-29); **fase B pand-eis afwijkingen 41** (alle "SIGNAAL: sluit niet"); C/D "ZOU … als B GROEN is" |

Verwachting uit de opdracht gehaald: de analytic-regel staat er (plan-id 1 = het Project-plan van de doelkoppeling), `pand-analytics` ≥ 1, geen "STOP — geen
analytic_plan_id". De stand van de dry-run is gelijk aan die van 13:12–13:32 (229 vertaalbaar, 41 pand-afwijkingen) plús de analytic-regels: de deploy draagt de fix.

## 2. Stap 2 — SCHRIJF c (executie `rlz-reconciliatie-8j7ch`, 20:58 NL, exit 0): GEPOST
| # | Stap | Werkt | Detail (letterlijk uit het rapport) |
|---|---|---|---|
| 0 | partners | **ja** | hergebruikt partner **275** (Gimple B.V.) — gevonden op naam; hergebruikt partner **276** (Ouwerkerk Notariaat) — gevonden op iban |
| 1 | inkoopfactuur concept | **ja** | concept **3369**: RLZ-04-00000431 (rlz c897b7ac-…) anker ac177712-… — 1 regels (bestaand, blijft draft: de paar-factuur is de verkoop) |
| 2 | memoriaal | niet uitgevoerd | geen vertaalbaar document van dit type |
| 3 | verkoopfactuur = bewijspaar | **ja** | concept **3370**: RLZ-01-00000082 (rlz 8b079e5c-…) anker 957f690d-… — 1 regels · **1 regel(s) analytic hersteld (bestaand concept droeg de pseudo-sleutel) → GEPOST als F/2026/00001 (state posted)** |
| 4–5 | statement line / reconcile | niet uitgevoerd | IBAN op dagboek BNK1 is LEEG — klikpunt Peter; stap 5 ook overgeslagen |
| 6 | terugweg | niet uitgevoerd | niets om terug te draaien (geen concept (2), geen reconcile) |

Kopregels: "analytic pand:schoffelstraat-29 → 851 (aangemaakt)" en "KLIKPUNT PETER: IBAN op BNK1 is leeg — stap 4 en 5 overgeslagen, rest doorgelopen".
Stand company 6 ná de run: partners aangemaakt 0 / hergebruikt 2, geposte boekingen (deze run) 1, concepten (deze run) 1 (= 3369, ongewijzigd), statement lines 0,
`account.move` totaal niet-cancel 2, `account.bank.statement.line` totaal 0. Het script toonde het rapport (procesfix 22-09 werkt óók op een geslaagde executie).

Afwijking van de verwachtingstekst: de opdracht schreef "GEPOST als F/2026/03/…"; Odoo company 6 nummert dagboek F als `F/2026/00001` (jaar-reeks zonder maand).
Geen fout — de boeking is de éérste geposte in dat dagboek, het nummer klopt met de journaalinstelling.

## 3. Audit-toets op de leesreplica (`db_lezen.sh`, als Beheerder, scope `cc07e461-…`, `platform.audit_event` actie `odoo_migratie_%` ná 18:00 UTC)
| actie | tijdstip (UTC) | oud → nieuw |
|---|---|---|
| `odoo_migratie_partner_hergebruikt` ×2 | 18:58:55 | 275 Gimple B.V. [naam], 276 Ouwerkerk Notariaat [iban] (search_read) |
| `odoo_migratie_move_bestaat` ×2 | 18:58:56 / :57 | 3369 (anker ac177712-…, draft), 3370 (anker 957f690d-…, draft) |
| **`odoo_migratie_analytic_aangemaakt`** (1) | 18:58:57 | nieuw `{code: schoffelstraat-29, naam: Schoffelstraat 29, model: account.analytic.account, company: 6, methode: create, odoo_id: 851, plan_id: 1}` |
| **`odoo_migratie_regel_analytic_hersteld`** (1) | 18:58:58 | oud `{analytic_distribution: {"pand:schoffelstraat-29": 100.0}}` → nieuw `{model: account.move.line, move_id: 3370, odoo_id: 7392, methode: write, analytic_distribution: {"851": 100.0}}` |
| **`odoo_migratie_move_gepost`** (1) | 18:58:59 | oud `{name: false, state: draft}` → nieuw `{name: "F/2026/00001", state: posted, date: 2026-03-19, amount_total: 400000.0, odoo_id: 3370, methode: action_post}` |

Precies de drie verwachte tellers (1 / ≥ 1 / 1), oud = de pseudo-sleutel; 7 rijen totaal, geen `_meerduidig`, geen fout.

## 4. Stap 3 — achtste meting (replay ná het posten; nameting-run 35770964986, onderdeel c, lees-only)
Run `gh workflow run nameting -f onderdeel=c` (35770964986, gestart 21:00 NL, `success`); bot-commit `0d5e374` "nameting 22-09 c — Oordeel: ROOD" op origin/main,
bot-bestand `verkenning/nameting-vgg-replay-22-09.txt` (zelfde datumnaam als de zevende meting — de bot overschrijft; `git show 0d5e374` toont de diff).
- **Diff t.o.v. de zevende meting (bot `a3b2455`, 13:xx): 2 regels — uitsluitend het tijdstip (`…T19:08:29+00:00`) en de webfilter-wachttijd (267,5 s i.p.v. 250,2 s).**
  Alle inhoud identiek: Oordeel ROOD op uitsluitend de 3 afletter-groepen, 906 niet vertaalbaar, herclassificatie `ongemapt:8000 → 3608` € −400.000,00 (1 document),
  per pand `schoffelstraat-29`: Verkoop € 400.000,00 / Aanbetalingen € 20.000,00 / Notaris-ontvangst € 50.952,09 → "SIGNAAL: sluit niet (Δ 349047.91)";
  RLZ-06-00000110 (31-12-2025, € 365.000,00) en RLZ-06-00000174 (20-03-2026, € 365.000,00) niet vertaalbaar "grootboek zonder Odoo-rekening: 1100, 1601".
- **Wat de meting wél en niet bewijst:** onderdeel c is de RLZ → Odoo-move-vorm-replay (lees-only op RLZ; "berekend Odoo" = uit RLZ afgeleid, de replay leest de
  Odoo-boekhouding niet — het bestand zegt zelf "dry-run leest Odoo niet"). De verwachting uit de opdracht ("saldibalans 803100 = € 400.000,00 aan de Odoo-kant")
  is dus geen uitkomst van dit onderdeel; die stand is bewezen door de terug-lees in SCHRIJF c zelf (`state posted`, `amount_total 400000.0`, `name F/2026/00001` in de
  audit-rij `odoo_migratie_move_gepost`, §3). De achtste meting bewijst wél dat het posten in Odoo de RLZ-kant niet raakt (identieke replay) en dat de pand-eis voor
  Schoffelstraat 29 ongewijzigd rood is — de basis van §5. Een lees-only Odoo-kant-meting (saldibalans company 6 per rekening) bestaat niet als dispatch-onderdeel;
  bouwen ervan is een aparte opdracht (niet in deze run gestart: de opdracht vroeg alleen onderdeel c).

## 5. GO-vraag aan Peter vóór `SCHRIJF d` — mét de per-pand-sluit-eis (7d) letterlijk
**Wat SCHRIJF c heeft bewezen:** het schrijfpad partners → concept → analytic (lookup-vóór-create) → herstel van een kapot concept → `action_post` werkt op company 6
op het échte anker, idempotent (partners/concepten hergebruikt, niets dubbel), elke write terug-gelezen en geaudit (§3). De boeking staat als
`F/2026/00001` (19-03-2026, € 400.000,00, partner 276, analytic 851 Schoffelstraat 29 op 803100 via rol `opbrengst_panden`).

**Wat SCHRIJF c NIET heeft bewezen:**
1. **Reconcile (stap 4/5).** Niet uitgevoerd: IBAN op dagboek BNK1 in company 6 is leeg (klikpunt sinds 13:12, ongewijzigd). Zonder statement line ↔ factuur
   is routes i/ii/iii én de terugweg (stap 6) niet getoetst. SCHRIJF d fase D ("statement lines ↔ documenten via PaymentReferenceList") zou op dezelfde lege IBAN
   stranden of overslaan.
2. **De per-pand-sluit-eis (7d), letterlijk uit de regels:** blok 7d (14-09): *"per-pand 'sluit' = GO-eis bij SCHRIJF c"*; 17-09: *"`vgg-odoo-migratie` = concepten →
   cent-exacte toets uit Odoo (Σ debet = Σ credit, tegenzijde = Σ factuurregels, per pand sluit) → bulk `action_post` in dezelfde run → reconcile; toets rood = niets
   gepost, concepten blijven staan"*. Stand vandaag: **pand `schoffelstraat-29` sluit NIET** — zevende meting (13:xx, bot `a3b2455`): Verkoop € 400.000,00 /
   Aanbetalingen € 20.000,00 / Notaris-ontvangst € 50.952,09 → "SIGNAAL: sluit niet (Δ 349.047,91)", omdat de AANKOOP in memorialen `RLZ-06-00000110` +
   `RLZ-06-00000174` (€ 365.000,00) op ledgers 1100/1601 staat die in company 6 geen Odoo-rekening hebben (beslispunt 2, 17-09 avond). De migratie-dry-run
   van vanavond telt **41 panden "sluit niet"** (fase B). Dat is géén IBAN-kwestie: ook mét IBAN blijft toets B rood.

**Consequentie voor `SCHRIJF d` als Peter nu GO geeft:** `vgg-odoo-migratie --schrijf` maakt fase A aan (229 concepten, 1034 statement lines — die laatste alleen mét IBAN,
39 pand-analytics), toetst in fase B rood op 41 panden en **post NIETS** (bedoeld gedrag: "toets rood = niets gepost, concepten blijven staan"). De run is dan een grote
concept-aanmaak zonder posten — niet zinloos (idempotent op anker, concepten zichtbaar in Odoo), maar niet het "alles definitief" van 17-09.

**Advies (CC, ter beslissing Peter):** GO voor SCHRIJF d pas ná twee stappen, in deze volgorde:
1. **Beslispunt 2 beslissen — mapping van RLZ 1100 en 1601 (en de overige ongemapte ledgers achter de 41 pand-afwijkingen) naar Odoo-rekeningen in company 6**, via
   `odoo-koppeling-migratiedoel`/de voorstel-kolom van de replay — geen CC-run mag die mapping verzinnen. Daarna `plan` opnieuw: fase B moet per pand groen tonen
   (of de resterende afwijkingen benoemd als RLZ-opruimpunt). Pas dan is de sluit-eis toetsbaar en heeft SCHRIJF d een kans om te posten.
2. **IBAN op dagboek BNK1 in Odoo company 6 zetten** (het bestaande klikpunt) — daarna éérst `SCHRIJF c` nogmaals (idempotent: partners/concept/analytic hergebruikt,
   F/2026/00001 blijft gepost; stap 4/5/6 draaien dan wél: statement line 20-03-2026 € 52.142,09 Ouwerkerk ↔ F/2026/00001, reconcile-route, terugweg) zodat de
   reconcile-kant bewezen is vóór de bulk.
Een GO zónder stap 1 is toegestaan maar levert aantoonbaar 0 geposte boekingen; een GO zónder stap 2 levert concepten zonder reconcile. Beide standen zijn
terugdraaibaar (concepten: `button_cancel`, nooit unlink; gepost: `button_cancel → button_draft`).

## 6. Keuzes (Peter kijkt niet mee)
- **SCHRIJF c uitgevoerd mét het IBAN-klikpunt open** — conform de opdracht ("zonder IBAN post SCHRIJF c het bewijspaar wél") en het ontwerp van blok 7 ("IBAN leeg →
  stap 4/5 overgeslagen en gemeld, rest doorgelopen"). Het posten was de boeking-test van 17-09; die is geslaagd.
- **Geen herhaalde SCHRIJF c, geen SCHRIJF d** in deze run: de opdracht eindigt bij de GO-vraag; SCHRIJF d is expliciet Peters GO. Ook geen tweede `plan` ná het posten
  (de achtste meting via de nameting-workflow is de lees-only terug-lees, §4).
- **Verwachtingstekst "F/2026/03/…" niet als afwijking gemeld aan Odoo** — het nummer volgt de journaalinstelling van dagboek F in company 6; de audit-rij toont het
  letterlijk. Geen handeling.
- **Geen code in deze run**, dus de poort is een regressiepoort op ongewijzigde code (vitest/tsc/keten-sweep meegedraaid omdat de opdracht "volledige poort" zegt).
- **WIP-branch blijft staan** ter controle (`wip/2026-09-22-vgg-schrijf-c-poging-2-na-deploy-pand-analytic`, `689172b`): bevat uitsluitend `D opdrachten/inbox/…poging-2…md`.

## 7. Klikpunten Peter
1. **IBAN op dagboek BNK1 (Odoo company 6) zetten** — voorwaarde voor de reconcile-kant; daarna `SCHRIJF c` nogmaals (idempotent) om stap 4/5/6 te bewijzen op de
   bankregel 20-03-2026 € 52.142,09 Ouwerkerk Notariaat (TransactionId `00112`, bron `rlz-feiten bank` 21-09) ↔ `F/2026/00001` (Odoo-id 3370).
2. **Beslispunt 2 — mapping RLZ 1100/1601 → company 6** voor de aankoop-memorialen `RLZ-06-00000110` (31-12-2025) + `RLZ-06-00000174` (20-03-2026), samen € 365.000,00, bron: zevende meting
   22-09 `vgg-replay` bot `a3b2455`, letterlijk in `.scratch/vgg-schrijf-c/replay-22-09-zevende.txt`; RLZ-id verkoop `8b079e5c-aeba-4776-9097-31d2686184f6`) — zonder mapping sluit
   pand Schoffelstraat 29 niet (Δ € 349.047,91, stand 22-09) en blijft toets B rood op 41 panden.
3. **GO/NO-GO op `SCHRIJF d`** op basis van §5 — advies: pas ná 1 en 2.

## Poort (letterlijk)
- pytest volledige suite (achtergrond, alléén, ongewijzigde code): **1 failed, 7142 passed, 2 skipped, 21 deselected in 2857 s (47:37)** — de ene rode = deze run's
  eigen rapport-guard `test_rapporten_klikpunten` (klikpunt 2 droeg de datums van RLZ-06-00000110/174 op de tweede regel van de bullet; de guard leest per regel):
  gefixt (datums op de eerste regel), guard herdraaid **8 passed** (klikpunten + index + gelezen regels). Geen code-regressie: alle overige 7142 groen.
- Docs-guards ná de laatste docs-schrijf los herdraaid: `test_rapporten_index`, `test_rapporten_gelezen_regels`, `test_rapporten_klikpunten`,
  `test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, `test_cc_inbox_claim_en_poort` — 34 passed vóór de klikpunt-fix + 8 passed erna.
- `tsc -b`: exit 0. vitest: **248 bestanden, 1909 passed**, exit 0. Gouden set `frontend/scripts/keten_sweep.sh`: **11/11 gelijk**, exit 0.
- Geen ruff (geen Python gewijzigd), geen migratie, geen schema-dump.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT, kopregel "Domeinen"): `docs/regels/vgg-odoo-migratie.md` (59 regels bij het lezen; 62 regels ná deze run),
`docs/regels/werkloop-productie.md` (294 regels bij het lezen; 294 regels ná deze run — geen nieuwe regel: deze run leverde geen nieuwe werkloop-les).
