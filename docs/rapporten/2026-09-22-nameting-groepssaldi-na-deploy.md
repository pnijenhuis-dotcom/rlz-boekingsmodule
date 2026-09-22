# Nameting groepssaldi "Kempen groep" ná de deploy van de fix van 21-09 — detector werkt, fix half: tweede enum-veld `Status` gevonden en gefixt (22-09)

**Opdracht:** `opdrachten/gedaan/2026-09-22-nameting-groepssaldi-na-deploy-kempen-groep.md` (`niet vóór: 2026-09-22 09:00`; gestart 09:01 NL).
**Context:** rapport `2026-09-21-groepssaldi-fix.md`, BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)".

## Uitkomst in één alinea
- **Regressie-detector `groep_saldo_fout` — werkt in productie: JA.** De scheduler-run van 22-09 06:30 (run `e315ceae`, image `fb63be5`) schreef
  precies één LET-OP (35 leden, stand 21-09) + één audit `automatisering_regressie` `categorie: groep_saldo_fout` — exact de verwachting van 21-09.
- **Fix 21-09 — werkt in productie: DEELS.** De Ledgers-call (AccountType) en de Odoo-lezer werken: de stand van 22-09 heeft geen Ledgers-400 meer en
  de twee Odoo-leden staan `ok`. Maar 29 van 35 leden zijn opnieuw `fout` op de VOLGENDE call: `saldi.ic_open` filterde `Status eq 2` op
  Sales-/PurchaseInvoices → 400 "'Reeleezee.DTO.DocumentStatus' and 'Edm.Int32'". `Status` is óók een enum. **Codefout → in deze run gefixt**
  (client-side Status-toets, guard uitgebreid, stub speelt de 400 na). Werkt in productie ná de fix van 22-09: **NIET GEMETEN** — de eerste groene
  stand komt uit `sync-alles` 23-09 07:00; vervolg-opdracht `opdrachten/inbox/2026-09-23-nameting-groepssaldi-status-enum-fix-kempen-groep.md`.
- **Peters antwoord van 16-09 (saldo debiteuren/crediteuren Kempengroep) is dus nog niet af**; de 6 leden zonder IC-entity's hebben wél een saldo
  (sectie "Live-meting" hieronder).

## Stap 0 — deploy-check (09:01 NL)
- `git rev-list --count main..origin/main` = 0 (geen divergentie, geen merge nodig).
- Service `rlz-backend` én alle 17 jobs op image `…backend:fb63be5c…`; fix-commit `cd89ad4` is voorouder van `fb63be5` (`git merge-base --is-ancestor`).
- Laatste deploy-run 35632649146 (21-09 17:32 UTC) groen. `sync-alles` (job `rlz-sync`, executie `dwfpj`) 22-09 05:00→06:19 UTC geslaagd — 1 u 19 min
  (21-09: 47 min; het verschil is waarschijnlijk de groepssaldi-lezing die nu wél tot de JournalEntryLines komt — zie beslispunt 2).
- Reconciliatie-run `j652c` 04:30→04:46 UTC, exit 1 = afwijkingen-conventie (782 bevindingen vastgelegd, run `e315ceae` status `klaar`).

## Stap 1 — stand (leesreplica, `groep_saldo_stand`, als Beheerder via `scripts/gcp/db_lezen.sh`)

| datum | status | n | detail (eerste 90 tekens) |
|---|---|---|---|
| 17-09 … 21-09 | fout | 35 per dag | `GET /…/Ledgers -> 400: {"Message":"The query specified …` (AccountType-bug) |
| 22-09 | fout | 29 | `GET /…/PurchaseInvoices -> 400: {"Message":"A binary operator with incompatible types …` |
| 22-09 | ok | 6 | Bonte Hoeve, Camping "Nieuwenhoven", Caravanpark "De Visotter", Mantelzorgwoningen Oost Nederland, RB Infra, Recreatiecentrum Dijkstel |

Per lid (22-09): 17 × `SalesInvoices -> 400`, 12 × `PurchaseInvoices -> 400` (welke van de twee eerst faalt hangt af van welke IC-kant entity's heeft).
De 6 `ok`-leden hebben geen `intercompany_relatie`-tegenpartij in de groep → `ic_open` wordt niet aangeroepen (vroege `NUL`). De letterlijke RLZ-melding:

```
GET /<admin>/PurchaseInvoices -> 400: {"Message":"A binary operator with incompatible types was detected. Found operand types 'Reeleezee.DTO.DocumentStatus' and 'Edm.Int32'."}
```

**Bruto = zonder-IC + IC en de TOTAAL-regel zijn op 22-09 niet toetsbaar** (29 leden zonder saldo). Verwachting van de opdracht (35 × ok, 0 × fout):
**NIET gehaald — rood.**

## Stap 1b — live-meting (dispatch-onderdeel `groep-saldi`, run 35697712380, job-executie `rlz-reconciliatie-hqsbk`)
Workflow-run 35697712380 groen (bot-commit `c94515e` op main, hier ge-merged `--no-ff`): `verkenning/nameting-groep-saldi-22-09.txt`. De live-executie
duurde **41 min** (07:04→07:45 UTC; jobtimeout 3600 s — 19 min marge), de `--stand`-executie seconden. Live ≡ stand: **6 ok / 29 fout**, identieke
RLZ-melding, `TOTAAL (6 geldig)`; het bot-oordeel: "TOTAAL (6 geldig) · LET OP: 29 administratie(s) niet in het totaal · 58 regel(s) status fout".

| lid (6 geldig) | Deb. bruto | Deb. IC | Cred. bruto | Cred. IC | rekeningen (bron) |
|---|---|---|---|---|---|
| Bonte Hoeve B.V. (Odoo) | € 0,00 | € 0,00 | € 0,00 | € 0,00 | 110000/110100 Debtors · 130000 Creditors, **159000 VAT tax liabilities** |
| Camping "Nieuwenhoven" B.V. (Odoo) | € 0,00 | € 0,00 | € 0,00 | € 0,00 | idem |
| Caravanpark "De Visotter" B.V. | € 423,20 | € 0,00 | € 6.982,70 | € 0,00 | 1200 · 1600 |
| Mantelzorgwoningen Oost Nederland B.V. | € 0,00 | € 0,00 | € 0,00 | € 0,00 | 1200 · 1600 |
| RB Infra B.V. | € 38.443,76 | € 0,00 | € 1.139,49 | € 0,00 | 1200 · 1600 |
| Recreatiecentrum Dijkstel B.V. | € 0,00 | € 0,00 | € 3.590,05 | € 0,00 | 1200 · 1600 |
| **TOTAAL (6 geldig)** | **€ 38.866,96** | € 0,00 | **€ 11.712,24** | € 0,00 | bruto = zonder-IC + IC klopt cent-exact (IC 0 — deze 6 hebben geen IC-entity's) |

Geen debiteur-/crediteurnamen in de uitvoer (alleen rekeninglabels). Dit is dus een ANTWOORD OP 6 VAN 35 — niet Peters antwoord van 16-09.

**Bijvangst (niet gefixt, beslispunten 3 en 4):** (a) bij de twee Odoo-leden telt `159000 VAT tax liabilities` als crediteurenrekening — Odoo typeert die
rekening in deze companies als `liability_payable` (de regel "rekeningen uit de bron, nooit op naam" volgt dat trouw, maar een btw-schuld is geen
handelscrediteur); (b) beide Odoo-leden staan op € 0,00 in álle kolommen — plausibel als die companies nog (bijna) geen posted moves hebben, maar
niet bewezen; Peter kan dat in één blik in Odoo toetsen.

## Stap 2 — regressie-detector (verwachting vooraf: één LET-OP + één audit; audit-spoor `run._registreer_regressies`)
Leesreplica, run `e315ceae` (gestart 04:30:26 UTC, status `klaar`):

| veld | waarde |
|---|---|
| soort / blok / administratie | `let_op` / `automatisering` / NULL |
| `detail.reden` / `aantal` / `stand_datum` | `groep_saldo_fout` / 35 / 2026-09-21 |
| tekst | "LET-OP automatisering groepssaldi: 35 administratie(s) in 1 groep(en) (Kempen groep) hebben in de nachtelijke groepssaldi-stand van 21-09-2026 status fout — voorbeelden: ARVUM B.V.: GET /…/Ledgers -> 400 …" |
| audit | `automatisering_regressie` 04:46:28 UTC, `nieuwe_waarde` = `{"aantal": 35, "run_id": "e315ceae-…", "categorie": "groep_saldo_fout", "vingerafdruk": "2f7ca2665112abc9", "automatisering": "groep_saldi", "administratie_id": null}` |
| aantal rijen | precies 1 bevinding, precies 1 audit (query over 3 dagen op `reden`/tekst) |

Bijvangst voor élk meetrecept op deze detector: de LET-OP staat **niet** in de job-stdout (`registreer` print alleen de tellerregels) — je leest de tabel of
`/reconciliatie`. Systeemmail bleef `uitgeschakeld` (`mail_status` `actie=verzonden;systeem=uitgeschakeld`), de bewakingsprobe is het mailende kanaal.
**Verwachting 23-09:** de run van 06:30 leest de stand van 22-09 (29 fout) → LET-OP nog één keer, mét NIEUWE vingerafdruk (andere set) en `aantal` 29;
weg op 24-09 (stand 23-09 groen mét de fix hieronder). De run van 23-09 ligt ná deze opdracht; staat in de vervolg-opdracht.

## Fix in dezelfde run (codefout): `Status` client-side, guard + stub uitgebreid
- `backend/app/groepen/saldi.py::RlzBron.ic_open`: `$filter` = alleen `Entity/id eq …` (+ datumgrens), `$select` mét `Status`, per rij
  `_status_int(rij["Status"]) == STATUS_OPEN` (2). Concept (1) draagt óók een `BaseRemainingAmount` (het hele bedrag) en telt terecht niet; gesloten (3) = 0.
  Nieuwe constanten `STATUS_OPEN`, helper `_status_int` (int of string, onleesbaar = nooit open). Module-docstring bijgewerkt.
- `backend/tests/unit/test_rlz_filter_enum_guard.py`: `ENUM_VELDEN = ("AccountType", "Status")`; een regel die het 400-gedrag zelf beschrijft (mét de
  statuscode, zoals de docstrings van `schoonlijst.py`/`rlz_dubbel.py`) telt niet als filter; zelftest op de letterlijke 21-09-regel, `RecordStatus` (ander
  veld, `\b`-grens) en een `$select` mét Status.
- `backend/tests/groepen/test_saldi.py`: `NepClient` weigert `Status eq <int>` mét de productiemelding (RLZ-gedrag nagespeeld — dezelfde les als 21-09 rij 3),
  eist `Status` in `$select` en pagineert; testdata mét Status 1/2/3 en Status als string; nieuwe `TestRlzOpenPostenFilter` (3 tests: filter zonder Status +
  alleen 2 telt (350,10 / 1.200,00), meer entiteiten + datumgrens, 400 blijft zichtbaar als `fout`).
- `verkenning/api-verkenning.md`: de 21-09-bullet "Status eq 2 geeft in productie geen 400" was FOUT (die call werd vóór de fix nooit bereikt; drie secties
  hoger stond al de STAP-0-tabel "Status is een enum-type") — doorgehaald + gecorrigeerd; nieuwe sectie "Status is een enum in `$filter` — 22-09".
- Sweep: `grep -rn "Status eq" backend/app` → alleen `saldi.py:229` (de andere twee treffers zijn docstrings die het 400-gedrag beschrijven);
  `DocumentType eq` komt in geen enkele `$filter` voor (factuurmatch toetst client-side). Alle `$filter`-strings van `saldi.py` nagelopen: Ledgers
  (`IsTotalAccount eq false`, boolean — bewezen), JournalEntryLines (`Account/id eq <guid>`, `JournalEntry/BookDate lt <datum>` — GUID/datum, in de stand
  van 22-09 bewezen: de 6 ok-leden hebben een saldo), Sales-/PurchaseInvoices (nu alleen `Entity/id eq` + `Date lt`).
- Geen migratie, geen frontend-wijziging, geen RLZ-write.

## Keuzes (Peter kijkt niet mee)
1. **Client-side i.p.v. de string-literal `Status eq '2'`.** De STAP-0-tabel bewijst `'1'`/`'Tentative'` op één concept; `'2'` is niet getest en de
   guard-regel van 21-09 zegt "geen enum-literal-syntax zonder STAP-0-bewijs". Client-side is deterministisch en dezelfde lijn als de Ledgers-fix.
   Kosten: de collectie levert ook concepten en gesloten facturen van IC-entity's mee (gepagineerd, `MAX_PAGINAS` 200 × 200) — acceptabel voor
   IC-tegenpartijen (tientallen documenten per entity), en `Date lt` blijft als filter staan.
2. **Geen aanpassing van de live-CLI-looptijd in deze run** (zie beslispunt 2 hieronder): dat is geen codefout maar een capaciteitsvraag.
3. **Vervolg-opdracht i.p.v. "af"**: Peters vraag van 16-09 wordt pas beantwoord door het bot-bestand van 23-09; de opdracht van 22-09 eindigt eerlijk rood.

## Beslispunten
1. **Systeemmail-ontvangers zijn leeg** (`RECONCILIATIE_BEHEER_ONTVANGERS`): de regressie-LET-OP van vanochtend heeft dus alleen via de bewakingsprobe
   `automatisering_regressie` een mail kunnen sturen (`bewaking_alert_ontvanger`). Bewuste keuze van 15-09 — hier alleen benoemd omdat het de reden is dat
   de meting via de leesreplica moest.
2. **Looptijd van de live groep-saldi-lezing.** `sync-alles` duurde 22-09 1 u 19 min (21-09: 47 min) en de live job-executie liep bij het schrijven van
   dit rapport > 30 min zonder uitvoer (de CLI print de tabel pas aan het einde; jobtimeout `rlz-reconciliatie` = 3600 s). `JournalEntryLines` wordt per
   rekening in pagina's van 200 gelezen; voor grote administraties (Universal Steigerbouw, Kempen Facilities) zijn dat honderden calls mét throttling.
   Voorstel (niet gebouwd): saldo via een RLZ-balansroute of `$apply`-aggregatie (STAP-0 nodig), of de live-CLI beperken tot `--stand` als nameting-
   instrument en de nachtelijke lezing per administratie streamen naar stdout — Peters keuze.
3. **Odoo `liability_payable` omvat hier de btw-schuldrekening 159000** (Bonte Hoeve, Nieuwenhoven): crediteurensaldo = handelscrediteuren + btw. Opties:
   Odoo-kant corrigeren (rekeningtype `liability_current` — dat is de Odoo-norm voor btw), of de module beperkt tot rekeningen mét `reconcile = True`
   (handelscrediteuren zijn afletterbaar, btw niet — een bron-kenmerk, geen naam). Voorstel: het tweede, ná Peters ja; nu alleen zichtbaar in de
   rekeningregel van het rapport.
4. **Beide Odoo-leden op € 0,00 in alle kolommen** — controleren in Odoo (company 9/10) of dat de werkelijke stand is.

## Tests / poort
- Gericht: `tests/groepen/test_saldi.py` + `tests/unit/test_rlz_filter_enum_guard.py` + `tests/reconciliatie/test_automatiseringen.py` → 73 groen (ná de
  fix), daarna 21 groen op de twee eerste bestanden ná de regelknip; ruff check + format schoon op de drie geraakte Python-bestanden (format-diff alleen in
  eigen regels).
- **Volledige suite (achtergrond, alleen): pytest 7107 passed / 2 skipped / 21 deselected in 50:49, exit 0.** Geen frontend-code geraakt (alleen
  `WAT_IS_NIEUW.md`) → `tsc -b`/keten-sweep niet van toepassing; de changelog-vormtest en de docs-guards (rapporten-INDEX, gelezen regels, regels-index,
  CLAUDE.md-verwijzingen) zijn ná het schrijven van de docs nog eens los gedraaid (uitkomst hieronder in de commit).
- Procesnotitie: in deze run is één keer per ongeluk `git stash` gedraaid (bij een lint-controle) en binnen dezelfde minuut mét `git stash pop` hersteld;
  de suite draaide op dat moment al mét de modules in het geheugen — de gerichte tests zijn daarna opnieuw groen gedraaid. Les: geen stash, ook niet
  "even kijken" (memory bestond al).

## Vervolg
- `opdrachten/inbox/2026-09-23-nameting-groepssaldi-status-enum-fix-kempen-groep.md` (`niet vóór: 2026-09-23 09:00`): stand 23-09 = 35 × ok, live
  idem, LET-OP 23-09 mét `aantal` 29 + nieuwe vingerafdruk, weg op 24-09.
- Les vastgelegd in `docs/regels/werkloop-productie.md` (22-09): ná een bron-fout op één call álle calls van de motor nalopen + het patroon in de guard;
  een "kennelijk Edm.Int32"-claim zonder STAP-0 is geen feit — eerst de api-verkenning grep'en.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/administraties-instellingen.md` (129 regels — stand vóór de run)
- `docs/regels/reconciliatie.md` (216 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (220 regels — stand vóór de run)
