# Nameting groepssaldi "Kempen groep" ná de deploy van de `Status`-enum-fix van 22-09 — 35/35 leden `ok`, detector meldde 29 zoals verwacht (23-09)

**Opdracht:** `opdrachten/gedaan/2026-09-23-nameting-groepssaldi-status-enum-fix-kempen-groep.md` (`niet vóór: 2026-09-23 09:00`; gestart 09:02 NL).
**Context:** rapport `2026-09-22-nameting-groepssaldi-na-deploy.md`, BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)"
alinea "Gemeten 22-09". Poging 2 van Peters antwoord van 16-09 ("huidig saldo debiteuren/crediteuren Kempengroep").

## Uitkomst in één alinea
- **Fix 22-09 (tweede enum-veld `Status` client-side) — werkt in productie: JA.** De `sync-alles` van 23-09 07:00 NL (job `rlz-sync`, executie
  `r5td7`, image `ac7639b`) schreef de stand van 23-09 als **35 × `ok`, 0 × `fout`** (leesreplica); 22 van 35 leden dragen nu een IC-kolom ≠ 0
  (op 22-09 was IC alleen leesbaar voor de 6 leden zónder IC-entity's). Live-lezing via het dispatch-onderdeel `groep-saldi`: zie stap 1b.
- **Regressie-detector `groep_saldo_fout` — werkt in productie: JA (tweede bewijs).** De scheduler-run van 23-09 06:30 (run `40b5d45c`) las nog de
  stand van 22-09 en schreef precies één LET-OP mét `aantal` 29, `stand_datum` 2026-09-22 en een NIEUWE vingerafdruk (`c5d03e2307a75d02` ≠
  `2f7ca2665112abc9` van 22-09) + één audit `automatisering_regressie` (04:48:43 UTC) — exact de verwachting van 22-09. Op 24-09 moet de LET-OP
  weg zijn (stand 23-09 groen); die run ligt ná deze opdracht — verwachting vastgelegd, géén derde vervolg-opdracht (de detector is twee keer bewezen).
- **Peters antwoord van 16-09 staat nu in het bot-bestand `verkenning/nameting-groep-saldi-23-09.txt` (35 leden, TOTAAL-regel).** Géén debiteur-/
  crediteurnamen. Drie inhoudelijke aandachtspunten voor Peter (geen codefout): negatieve of bruto-overstijgende IC-kolommen bij vijf leden,
  Odoo-crediteurenrekening `159000 VAT tax liabilities`, beide Odoo-leden € 0,00 — sectie "Beslispunten".

## Stap 0 — deploy-check (09:02 NL)
- `git rev-list --count main..origin/main` = 0 (geen divergentie, geen merge nodig).
- Service `rlz-backend` én alle 18 jobs (incl. de nieuwe `rlz-intake-imap-kempengroep`) op image `…backend:ac7639b…`; fix-commit `afd3aca`
  (22-09 10:10 NL) is voorouder van `ac7639b` (`git merge-base --is-ancestor`). Laatste deploy-run groen: 23-09 00:51→00:57 UTC.
- `sync-alles` (job `rlz-sync`, executie `r5td7`) 23-09 05:00→06:21 UTC geslaagd op `ac7639b` — **1 u 21 min** (22-09: 1 u 19 min; 21-09: 47 min).
  De groepssaldi-stap zelf liep 05:04→05:37 UTC (`gemeten_op` eerste/laatste lid), ≈ 33 min binnen die run.
- Reconciliatie-run `hhhj7` 04:30→04:48 UTC op `ac7639b`, run-rij `40b5d45c` status `klaar`, exit 1 = afwijkingen-conventie.

## Stap 1 — stand (leesreplica `groep_saldo_stand`, als Beheerder via `scripts/gcp/db_lezen.sh --als 2f2262cd-…`)

| datum | status | n |
|---|---|---|
| 21-09 | fout | 35 |
| 22-09 | fout / ok | 29 / 6 |
| **23-09** | **ok** | **35** |

Verwachting van de opdracht (35 × ok, 0 × fout in de stand): **gehaald — groen.** Per lid 23-09 (bedragen in €, bruto = grootboeksaldo 1200/1600
resp. Odoo `asset_receivable`/`liability_payable`; IC = Σ `BaseRemainingAmount` van open posten (Status 2, client-side) op IC-entity's; zonder-IC =
bruto − IC per definitie cent-exact — `saldi.py::debiteuren_zonder_ic`):

| lid | backend | Deb. bruto | Deb. IC | Cred. bruto | Cred. IC |
|---|---|---|---|---|---|
| ARVUM B.V. | rlz | 7.445,57 | 0,00 | 348.445,86 | 333.250,00 |
| ARVUM Holding B.V. | rlz | 0,00 | 0,00 | 0,00 | 0,00 |
| Beleggingsmaatschappij Meyer BV | rlz | 0,00 | 0,00 | 3.544,00 | 0,00 |
| Bonte Hoeve B.V. | odoo | 0,00 | 0,00 | 0,00 | 0,00 |
| Bouwadvies Oost Nederland B.V. | rlz | 8.866.167,50 | 1.497.267,50 | 7.498.437,60 | 2.246,49 |
| BWC Steigers B.V. | rlz | 2.469,14 | 0,00 | 22,00 | 0,00 |
| Camping "Nieuwenhoven" B.V. | odoo | 0,00 | 0,00 | 0,00 | 0,00 |
| Caravanpark "De Visotter" B.V. | rlz | 423,20 | 0,00 | 6.982,70 | 0,00 |
| Hotel Pax | rlz | 14.810,40 | 0,00 | 2.733,98 | 0,00 |
| Inpensas Beheer BV | rlz | 55.962,50 | 40.837,50 | 8.507,33 | 1.097,02 |
| J.G.M. Elissen Holding BV | rlz | 47.176,82 | 0,00 | 486.574,81 | 223.850,00 |
| Kempen B.V. | rlz | 24.200,00 | **−24.200,00** | 0,00 | 0,00 |
| Kempen Chalets B.V. | rlz | 22.990,50 | 0,00 | 640.025,78 | 578.961,94 |
| Kempen Facilities B.V. | rlz | 568.736,52 | 354.034,65 | 126.408,92 | 0,00 |
| Mantelzorgwoningen Midden Nederland | rlz | 179.069,00 | 0,00 | 340.857,47 | 335.629,12 |
| Mantelzorgwoningen Oost Nederland B.V. | rlz | 0,00 | 0,00 | 0,00 | 0,00 |
| Midden Nederland Beheer BV | rlz | 272.847,36 | **335.726,24** | 41.940,36 | 0,00 |
| Molenhof Beheer B.V. | rlz | 998.100,00 | **−187.700,00** | 424.218,19 | 49.916,23 |
| Molenhof Verhuur B.V. | rlz | 3.308.205,20 | 2.919.650,00 | 628.527,66 | 628.453,24 |
| Necol Beheer BV | rlz | 62.617,50 | 62.617,50 | 10.161,46 | 0,00 |
| Necol Energie B.V. | rlz | 54.781,56 | 54.781,56 | 57.630,30 | 0,00 |
| Novitas Holding B.V. | rlz | 12.239,15 | 0,00 | 0,00 | 0,00 |
| Oirschot Recreatie B.V. | rlz | −2.627,21 | 0,00 | 710.161,22 | 652.299,94 |
| Oirschot Vastgoed Beheer B.V. | rlz | 381.775,15 | 381.775,15 | 1.992.848,17 | 1.991.687,50 |
| Old Dutch BV | rlz | 0,00 | 0,00 | −5.326,77 | 0,00 |
| RB Infra B.V. | rlz | 38.443,76 | 0,00 | 1.139,49 | 0,00 |
| Recreatiecentrum Dijkstel B.V. | rlz | 0,00 | 0,00 | 3.590,05 | 0,00 |
| Rubicon Investments B.V. | rlz | 14.593,06 | 0,00 | 160.719,30 | 156.360,71 |
| Stichting Shuto | rlz | 504,41 | 0,00 | 387,70 | 0,00 |
| Universal Materiaal B.V. | rlz | 21.401,57 | **−21.401,57** | −8.573,54 | −8.573,54 |
| Universal Nederland B.V. | rlz | 441.931,50 | 268.336,70 | 262.058,53 | 48.400,00 |
| Universal Steigerbouw B.V. | rlz | 468.151,82 | 0,00 | 76.879,85 | 14.901,63 |
| Universal Verkoop B.V. | rlz | 289.225,38 | 29.484,52 | 59.917,52 | 0,00 |
| Veldhoven Recreatie B.V. | rlz | 96.372,67 | 0,00 | 210.618,56 | 119.980,35 |
| Zilver Beheer B.V. | rlz | 78.259,68 | 0,00 | 424.034,08 | 393.250,00 |
| **TOTAAL (35, stand 23-09)** | | **16.326.273,71** | **5.711.209,75** | **14.513.472,58** | **5.521.710,63** |

Afgeleid: debiteuren zonder IC € 10.615.063,96, crediteuren zonder IC € 8.991.761,95 (bruto − IC). Rekeningen: 33 × RLZ `1200 Debiteuren` /
`1600 Crediteuren` (uit RGS-binder, niet op code); 2 × Odoo `110000 Debtors, 110100 Debtors (PoS)` / `130000 Creditors, 159000 VAT tax liabilities`.
De 6 leden die op 22-09 al `ok` waren (Bonte Hoeve, Nieuwenhoven, Visotter, Mantelzorgwoningen Oost, RB Infra, Dijkstel) hebben op 23-09 cent-exact
dezelfde cijfers als op 22-09 — de fix veranderde niets aan het pad dat al werkte.

## Stap 1b — live-meting (dispatch-onderdeel `groep-saldi`, workflow-run 35829640488, job-executie `rlz-reconciliatie-fftpl`)
Workflow-run 35829640488 groen (07:02→07:45 UTC), bot-commit `4e263ec` op main (hier ge-merged `--no-ff`): `verkenning/nameting-groep-saldi-23-09.txt`
(155 regels, beide secties). Bot-oordeel: **"TOTAAL (35 geldig) · alle leden in het totaal · 0 regel(s) status fout — job-exit 0"**.
- **Live: 35 × `ok`, 0 × `fout`.** De live-executie `rlz-reconciliatie-fftpl` duurde **40 min** (07:03:03→07:43:31 UTC; jobtimeout 3600 s — 20 min
  marge, 22-09: 41 min). De `--stand`-executie: seconden. Verwachting van de opdracht (35 × ok in BEIDE secties, TOTAAL-regel, IC-kolommen gevuld):
  **gehaald — groen.**
- **Live ≡ stand op één lid na:** Beleggingsmaatschappij Meyer BV crediteuren bruto live € 9.896,50 vs stand € 3.544,00 (Δ € 6.352,50, IC 0) —
  de stand is van 05:04 UTC, de live-lezing van ~07:10 UTC; het verschil is één of meer inkoopfacturen die vanochtend in RLZ zijn geboekt (geen
  meetfout: de TOTAAL-regel crediteuren bruto verschilt exact hetzelfde bedrag: live € 14.519.825,08 vs stand € 14.513.472,58). Alle andere 34 leden
  en alle IC-kolommen cent-identiek.
- **TOTAAL live (35 geldig):** debiteuren bruto € 16.326.273,71 = zonder-IC € 10.615.063,96 + IC € 5.711.209,75; crediteuren bruto € 14.519.825,08 =
  zonder-IC € 8.998.114,45 + IC € 5.521.710,63 — bruto = zonder-IC + IC cent-exact per kolom en per lid (de CLI berekent zonder-IC als bruto − IC).
- IC-kolommen zijn nu voor álle leden gelezen: 22 leden ≠ 0 (op 22-09 live: alleen de 6 zonder IC-entity's leesbaar). Geen debiteur-/crediteurnamen
  in de uitvoer (alleen rekeninglabels). **Dit bot-bestand + de tabel in stap 1 is Peters antwoord op "huidig saldo debiteuren/crediteuren
  Kempengroep" (16-09).**

## Stap 2 — regressie-detector (verwachting vooraf uit het rapport van 22-09: LET-OP mét `aantal` 29 + nieuwe vingerafdruk + één audit)
Leesreplica, `reconciliatie_bevinding` ⋈ `reconciliatie_run` op `detail->>'reden' = 'groep_saldo_fout'`, laatste 3 dagen:

| run | gestart (UTC) | soort / blok / administratie | `aantal` | `stand_datum` | vingerafdruk |
|---|---|---|---|---|---|
| `e315ceae` (22-09) | 04:30:26 | let_op / automatisering / NULL | 35 | 2026-09-21 | `2f7ca2665112abc9` |
| **`40b5d45c` (23-09)** | 04:30:23 | let_op / automatisering / NULL | **29** | **2026-09-22** | **`c5d03e2307a75d02`** |

Tekst 23-09: "LET-OP automatisering groepssaldi: 29 administratie(s) in 1 groep(en) (Kempen groep) hebben in de nachtelijke groepssaldi-stand van
22-09-2026 status fout — …". Audit `automatisering_regressie` (`platform.audit_event`, `categorie: groep_saldo_fout`): 22-09 04:46:28 UTC
(`aantal` 35, vingerafdruk `2f7ca266…`) en **23-09 04:48:43 UTC (`aantal` 29, vingerafdruk `c5d03e23…`, `run_id` 40b5d45c)** — precies één per run.
Run-rij `40b5d45c`: `samenvatting.delta` = nieuwe_let_op 12, nieuwe_afwijkingen 49, verdwenen_afwijkingen 11, nieuwe_fouten 0, blokken_fout [];
`mail_status` `actie=verzonden;systeem=uitgeschakeld` (systeemmail-ontvangers leeg, bewuste keuze 15-09 — de bewakingsprobe is het mailende kanaal).
**Verwachting gehaald: JA.** De run van 24-09 06:30 heeft op het moment van schrijven nog niet gelopen (23-09 09:xx NL) → verwachting: géén
`groep_saldo_fout`-bevinding in run 24-09, de LET-OP van 23-09 verdwijnt als `let_op` uit de actuele set (LET-OP's krijgen géén
`reconciliatie_auto_gesloten`-audit — `_audit_verdwenen_bevindingen` dekt afwijkingen + fouten; dat is bestaand, gedocumenteerd gedrag van 19-09
avond). Geen derde vervolg-opdracht: de detector is op 22-09 en 23-09 twee keer exact volgens verwachting gemeten; wie 24-09 wil toetsen leest
`reconciliatie_bevinding` op `reden = groep_saldo_fout` voor die run (verwacht 0 rijen).

## Beslispunten (uit 22-09 meegenomen + nieuw)
1. **NIEUW — IC-kolom negatief of groter dan bruto bij vijf leden** (vet in de tabel): Kempen B.V. Deb. IC −24.200 op bruto 24.200 (zonder-IC
   48.400), Molenhof Beheer Deb. IC −187.700, Universal Materiaal Deb. IC −21.401,57 op bruto 21.401,57 én Cred. bruto/IC −8.573,54,
   Midden Nederland Beheer Deb. IC 335.726,24 > bruto 272.847,36 (zonder-IC −62.878,88), Oirschot Recreatie Deb. bruto −2.627,21. Oorzaak in de
   motor: IC = Σ open posten op de IC-entity's (`BaseRemainingAmount`, creditfacturen negatief), bruto = grootboeksaldo — twee bronnen die alleen
   gelijklopen als álle IC-facturen zijn geboekt én afgeletterd; een open IC-creditnota of een nog-niet-afgeletterde betaling geeft precies dit beeld.
   Dit is een BOEKHOUDKUNDIG signaal (open IC-posten die niet meer bij het grootboeksaldo passen), geen codefout; de kolommen tonen wat de bron zegt
   (kernprincipe 1). Voorstel: Peter loopt deze vijf na in RLZ; als gewenst een LET-OP-regel "IC-open-posten passen niet bij het saldo" in het
   reconciliatieblok (nieuwe bevindingssoort → start in `meten`). Niet gebouwd.
2. **Looptijd (beslispunt 2 van 22-09):** `sync-alles` 1 u 21 min, de live-executie 40 min (jobtimeout 3600 s, 20 min marge). Ná de fix leest `ic_open` de hele collectie per
   IC-entity (concepten en gesloten facturen komen mee, `Date lt` blijft als filter) — jobtimeout `rlz-reconciliatie` 3600 s. Voorstel ongewijzigd:
   `--stand` als nameting-instrument; live-lezing alleen op verzoek; op termijn STAP-0 op een RLZ-balansroute/`$apply`. Peters keuze.
3. **Odoo `liability_payable` omvat `159000 VAT tax liabilities`** (Bonte Hoeve, Nieuwenhoven; beslispunt 3 van 22-09): crediteurensaldo =
   handelscrediteuren + btw-schuld. Voorstel: beperken tot rekeningen mét `reconcile = True` (bron-kenmerk, geen naam) ná Peters ja. Niet gebouwd.
4. **Beide Odoo-leden € 0,00 in álle kolommen** (beslispunt 4 van 22-09): ongewijzigd op 23-09; toetsen in Odoo (company 9/10) of dat de werkelijke
   stand is — één blik van Peter.

## Keuzes (Peter kijkt niet mee)
1. Geen codewijziging: 0 × `fout`, dus geen `$filter`-sweep nodig (die is op 22-09 al gedaan en staat in dat rapport). Beslispunt 1 is een
   bron-/boekhoudsignaal, geen motorfout — bouwen zonder Peters oordeel zou een nieuwe bevindingssoort op een aanname zijn.
2. Geen derde vervolg-opdracht voor 24-09: de detector is twee keer exact gemeten; de resterende verwachting (0 rijen op 24-09) staat hier letterlijk.
3. De stand-tabel per lid staat volledig in dit rapport (35 rijen): dat ís Peters antwoord van 16-09, naast het bot-bestand.

## Tests / poort
Geen code geraakt (alleen docs + opdrachtbestand) → geen pytest/vitest/tsc-poort van toepassing; docs-guards (`test_rapporten_index.py`,
`test_rapporten_gelezen_regels.py`, `test_rapporten_klikpunten.py`, `test_regels_index.py`, `test_claude_md_beslissingen_verwijzingen.py`) los gedraaid: 15 passed.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/administraties-instellingen.md` (151 regels — stand vóór de run)
- `docs/regels/reconciliatie.md` (282 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (306 regels — stand vóór de run)
