# Rapport 21-09 — Groepssaldi: productiefout 16→21-09 gefixt (RLZ-enumfilter + Odoo `deprecated`), regressie-detector, nameting-onderdeel

**Opdracht:** `opdrachten/gedaan/2026-09-21-BUG-groepssaldi-alle-35-administraties-fout-rlz-enumfilter-en-odoo-deprecated.md`
(Cowork 21-09 ~09:00, Peters sessie: `GET /groepen/97c51913-…/saldi` → 35 × `status: fout`, totalen leeg). Geen migratie, geen
RLZ-write. **Werkt in productie: niet gemeten** — de fix komt pas mét de deploy van deze commit live (push = Stop-hook, deploy ≈ 15 min);
de meting staat als vervolg-opdracht in `opdrachten/inbox/` mét `niet vóór: 2026-09-22 09:00` (live-meting + nachtelijke stand van de
`sync-alles` van 07:00) en als dispatch-onderdeel `groep-saldi` in `.github/workflows/nameting.yml`. Het bot-bestand
`verkenning/nameting-groep-saldi-<dd-mm>.txt` is dan Peters antwoord op zijn vraag van 16-09.

## Oorzaak (twee, beide in `app/groepen/saldi.py`)
1. **33 × RLZ:** `RlzBron._alle_ledgers` stuurde `$filter=IsTotalAccount eq false and (AccountType eq 3 or AccountType eq 4)`. `AccountType`
   is in RLZ's OData-model een enum (`Reeleezee.DTO.AccountTypeEnum`); een int-literal geeft **400** "A binary operator with incompatible
   types was detected. Found operand types 'Reeleezee.DTO.AccountTypeEnum' and 'Edm.Int32'" (letterlijk RLZ-antwoord uit Peters sessie).
   Nergens anders in de code stond een `AccountType eq <int>` in een `$filter` (sweep: alle andere Ledgers-filters zijn booleans/strings).
2. **2 × Odoo (Bonte Hoeve + tweede Odoo-lid):** `OdooBron.rekeningen` filterde `[["deprecated","=",False]]` → **500** "Invalid field
   account.account.deprecated". Odoo 19 kent dat veld niet; `app/odoo/sync.py::lees_grootboek` wist dat al sinds 03-09 (`active = True`).

Beide fouten landden per administratie als status `fout` in de cache — precies zoals ontworpen ("óók bij rood") — maar het enige
zichtbare gevolg was een grijze kaart "meting mislukt" en het rapport 16-09 zei "werkt in productie: niet gemeten". Vijf dagen niets.

## Gedaan
- **A. RLZ-filter** (`saldi.py::RlzBron._alle_ledgers`): `$filter` = alleen `IsTotalAccount eq false`, `$expand=SystemAccountList`,
  gepagineerd `$top=200/$skip` (begrensd op `MAX_PAGINAS`, zoals `saldo()`) i.p.v. de aanname `$top=500`; de balanszijde toetst de
  bestaande `vind_rekeningen_rlz` client-side (`int(AccountType) in (3, 4)`). Geen enum-literal-syntax geprobeerd (geen STAP-0-bewijs).
  Het rekeningaantal van Universal is niet lokaal meetbaar; de paginering maakt de vraag irrelevant.
- **B. Odoo-domein** (`saldi.py::OdooBron.rekeningen`): `[["company_ids","in",[company]], ["account_type","=",…], ["active","=",True]]`
  — identiek aan `odoo/sync.py` (incl. `company_ids`: rekeningen zijn in Odoo 19 bedrijfsgedeeld). Sweep `grep -rn deprecated backend/app`:
  de enige domein-treffer was deze; de twee andere zijn commentaarregels in `odoo/sync.py` die het juist uitleggen.
- **C. Guards + regressie-detector:**
  - `tests/unit/test_rlz_filter_enum_guard.py`: regex over álle Python-bronnen onder `backend/app` op `AccountType (eq|ne|gt|ge|lt|le) <cijfer|{naam}>`
    (patroon `test_regels_index.py`), mét zelftest die de productiebug én de f-string-vorm herkent. De guard ving direct een letterlijke
    weergave in mijn eigen docstring — herformuleerd. Lijst `ENUM_VELDEN` uitbreiden alleen mét bewijs.
  - `tests/groepen/test_saldi.py::TestOdooDomein`: de velden van het `OdooBron`-domein + leesvelden ⊆ de tekens in `odoo/sync.py::lees_grootboek`
    (uit de broncode gelezen, fail-closed op `active`/`company_ids`/`account_type`, `deprecated` verboden).
  - `TestRlzLedgersFilter`: paginering over drie pagina's (debiteurenrekening op de laatste), geen `AccountType` in de filter, en een 400
    blijft zichtbaar als `fout` mét de RLZ-tekst. De stubs `NepClient`/`NepOdooClient` spelen nu het RLZ-/Odoo-gedrag na (assert op de filter,
    assert op het domein) — de suite mockte tot vandaag de client zonder de letterlijke query te toetsen.
  - **Regressie-detector** `app/reconciliatie/automatiseringen.py::groep_saldi_bevinding` (in `registreer`): ≥ 1 lid van een actieve groep
    mét status `fout` in zijn LAATSTE nachtelijke stand (`saldi.standen_met_fout`, gelezen per administratie in de eigen scope — de
    cache-policy is scope/Beheerder, les 19-09 "nooit in scoped_session(None)") → één platformbrede LET-OP, categorie `groep_saldo_fout`
    in `REGRESSIE_CATEGORIEEN` → `is_regressie` → systeemmail + audit `automatisering_regressie` + bewakingsprobe (regel reconciliatie 1),
    NIET via `meten` (het is een detector, geen domeinbevinding). Tekst: aantal leden/groepen, eerste vijf "naam: melding", deeplink
    `/?groep=<id>` (klantenlijst mét Groep-filter). Vingerafdruk stabiel per SET falende leden (mailt één keer per nieuwe set, blijft op
    /reconciliatie tot de stand groen is). `ongeldig` (webfilter) en `geen_rekening` zijn bewust geen regressie.
  - **CLI `groep-saldi --stand`** (`app/cli.py`): dezelfde tabel uit de nachtelijke cache (`saldi.lees_stand_systeem`, bron `stand`,
    "N administratie(s) zonder nachtelijke stand"); nodig omdat de kaart-route een lezer-scope vereist en de nameting geen login heeft.
    Beide CLI-vormen uit het meetrecept (live én `--stand`, plus de onbekende-groep-tak) lopen in de test letterlijk via `cli.main([...])`
    (les 19-09 poging 2).
- **D. Nameting-onderdeel `groep-saldi`** (`.github/workflows/nameting.yml`: `options:` + if-tak + `OORDEEL_BRON`; `scripts/gcp/nameting.sh`:
  `via_gh_onderdeel`): live + `--stand` voor "Kempen groep" → `verkenning/nameting-groep-saldi-<dd-mm>.txt`, Oordeelregel = TOTAAL-regel +
  niet-ok-teller + aantal `fout`-regels. Alleen op verzoek (niet in `alles`). Guard `test_nameting_workflow.py` bijgewerkt (options-regex).
  Bash-blokken `bash -n`-schoon.
- **E. Docs:** dit rapport + INDEX, BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)" (+ statusregel in de sectie van 16-09), CLAUDE.md één
  verwijsregel (domein Administraties), `docs/regels/administraties-instellingen.md`, `reconciliatie.md`, `werkloop-productie.md`,
  WAT_IS_NIEUW, `verkenning/api-verkenning.md` (feit "AccountType is een enum in $filter"), `Platform/registers/verbeteringen.md` (les 21-09).

## Keuzes (Peter kijkt niet mee)
- **Detector alleen op `fout`, niet op "geen stand".** Reconciliatie draait 06:30 vóór `sync-alles` (07:00); een lid dat gistermiddag aan een
  groep is toegevoegd heeft om 06:30 nog geen stand — dat als regressie melden zou vals zijn. Een ontbrekende stand blijft zichtbaar op de
  kaart ("nog geen stand") en in `--stand` ("N zonder nachtelijke stand").
- **Verwacht ná deploy, één keer:** de run van 22-09 06:30 leest nog de stand van 21-09 07:00 (oude image → 35 × `fout`) en produceert dus
  precies één keer de LET-OP `groep_saldo_fout` + audit `automatisering_regressie` + bewakingsalert — dat is het signaal dat vijf dagen
  ontbrak, nu alsnog. De `sync-alles` van 22-09 07:00 schrijft de eerste groene stand; op 23-09 verdwijnt de LET-OP. In de vervolg-opdracht
  staat dit als verwachting (audit-spoor eerst in de code aangewezen: `run._registreer_regressies`, les 20-09).
- **Odoo-domein mét `company_ids`** (de opdracht zei alleen `active`): `sync.py` gebruikt 'm live bewezen; zonder die clausule zouden
  gedeelde rekeningen van andere companies meekomen (het saldo filtert op `company_id` en blijft correct, maar de rekeninglabels niet).
- **Geen frontend-wijziging:** de kaart toonde "meting mislukt" correct; het probleem was dat niemand 'm las — de fix is een signaal mét
  handeling (systeemmail + audit + /reconciliatie), niet een rodere kaart.

## Tests
- `tests/groepen/test_saldi.py` 16 groen (10 bestaand + 6 nieuw), `tests/unit/test_rlz_filter_enum_guard.py` 2 groen.
- Gerichte run: `test_nameting_workflow.py`, `reconciliatie/test_automatiseringen.py`, `test_soort_stand.py`, `test_regels_index.py`,
  `test_rapporten_index.py`, `test_rapporten_gelezen_regels.py`, `test_claude_md_beslissingen_verwijzingen.py`, `bewaking/test_rls_weigering.py`
  → 105 groen (poging 2 opnieuw: 103 groen incl. klikpunten-guard).
- **Volledige poort (poging 2, 21-09):** pytest 6860 passed / 2 skipped / 21 deselected (1:05:18, exit 0); vitest 241 bestanden / 1862 tests
  groen; `tsc -b` schoon; gouden set `keten_sweep.sh` groen (11 metingen, 0 nieuwe baselines); `bash -n scripts/gcp/nameting.sh` schoon.
- Ruff schoon op de eigen bestanden (`saldi.py`, beide testbestanden); `automatiseringen.py`/`cli.py` houden hun bestaande E501's.

## Meetrecept ná deploy (vervolg-opdracht, `niet vóór: 2026-09-22 09:00`)
```
gh workflow run nameting -f onderdeel=groep-saldi      # of: scripts/gcp/nameting.sh groep-saldi --groep "Kempen groep" [--stand]
```
Verwacht in `verkenning/nameting-groep-saldi-22-09.txt`: 35 leden, 35 × `ok` (of `geen_rekening`/`overgeslagen` mét reden), 0 × `fout`,
TOTAAL-regel mét bruto = zonder-IC + IC per kolom (cent-exact), per lid naam/status/debiteuren/crediteuren/IC — geen debiteur-/
crediteurnamen. Daarnaast: `reconciliatie-bevindingen`-query of `/reconciliatie` op 22-09 toont één LET-OP `groep_saldo_fout` (stand
21-09) + audit `automatisering_regressie` categorie `groep_saldo_fout`; op 23-09 weg.

## Poging 1 → 2 (procesnotitie)
Poging 1 (09:14–09:31) bouwde alles hierboven maar eindigde met "de suite draait nog; ik commit pas als die groen is" (exit 0) terwijl de
suite nog liep — precies het incident van 18/19-09 (rij j3). De inbox zette het werk als WIP-commit `8d2ca0246c0f` op branch
`wip/2026-09-21-BUG-groepssaldi-alle-35-administraties-fout-rlz-enumfilter-en-odoo-deprecated` (blijft ter controle staan; opruimen =
`git branch -D`). Poging 2 begon met `git merge --squash` van die branch, herlas de regels, draaide de volledige poort (pytest + vitest +
`tsc -b` + gouden set — uitkomsten hieronder) en committe pas daarna op main. Inhoudelijk is er in poging 2 niets aan de fix veranderd.

## Klikpunten (login nodig)
- Klantenlijst mét Groep-filter "Kempen groep" ná de `sync-alles` van 22-09 07:00: kaart "Groepssaldi" toont drie kolommen i.p.v. "meting mislukt".

## Gelezen regels
- `docs/regels/administraties-instellingen.md` — 114 regels
- `docs/regels/reconciliatie.md` — 166 regels
- `docs/regels/werkloop-productie.md` — 184 regels
