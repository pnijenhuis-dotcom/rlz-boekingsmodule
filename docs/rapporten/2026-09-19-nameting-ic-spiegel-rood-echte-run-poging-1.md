# Nameting ic_spiegel_rood ná de échte run van 20-09 — POGING 1 (19-09 avond, te vroeg): stap 4 en 6 gemeten, stap 1–3 wachten op de run; bijvangst: verdwenen FOUTEN verdwenen stil (gefixt) + "niet vóór"-poort in de inbox-runner

**Opdracht:** `opdrachten/gedaan/2026-09-20-nameting-ic-spiegel-rood-echte-run-en-aansluiting-alleen.md` (vervolg op
`docs/rapporten/2026-09-19-nameting-ic-spiegel-rood-na-deploy.md`). Gestart 19-09 18:57 CEST — de inbox-runner claimt op mtime en kent
geen datum; de opdracht "ná de run van 20-09 06:30" lag er sinds 17:30 en werd dus dezelfde avond opgepakt.
**Werkt in productie: JA** voor stap 4 (`reconciliatie-alles --alleen doorbelasting_aansluiting --lees-only` op de job-image, geen
argparse-fout, 1 bron / 8 doelen) en de deploy-stand (stap 0); **NIET GEMETEN** voor stap 1–3 (auto-sluiting 174 × `ic_spiegel_rood`,
aandacht 340 → ≤ 166, herstelregel) — de échte run is pas 20-09 04:30 UTC en een run forceren is verboden (regel 19-09: actiemail buiten het
dagritme); **niet meetbaar** stap 5 (`trigger_gebundeld`: geen bulk-upload sinds de deploy); **klikpunt blijft** stap 6 (BLOW c9ba6d8d nog
`te_controleren`). Vervolg = `opdrachten/inbox/2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md` mét `niet vóór: 2026-09-20 07:15`.
Geen migratie, geen RLZ-write.

## Stap 0 — deploy-check (groen)

- `git rev-list --count main..origin/main` = 0 (18:57); HEAD = origin/main = `aef301f`. De `--alleen`-fix `471da9d` ∈ `aef301f`.
- deploy.yml run 35456298610 (`aef301f`) success 16:52 UTC; service `rlz-backend` én job `rlz-reconciliatie` op
  `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:aef301f1d5fd…` (beide via `--format=value(spec.template…image)`).

## Stap 4 — `--alleen doorbelasting_aansluiting` werkt op de job-image (executie `rlz-reconciliatie-j6kgg`, ~17:05 UTC)

`NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen doorbelasting_aansluiting --lees-only` (impersonatie `nameting@`):
geen "invalid choice" meer (19-09 middag: argparse-exit 2 op executie `2w5wh`). Uitvoer: "Venster 2025-08-15 t/m 2026-09-19 (400 dagen);
**1 bron-administratie(s) mét whitelist**" · "AFWIJKING Kempen Facilities B.V.: **8 doelentiteit(en)**, 1758 verkoop / 1660 inkoop gelezen,
1652 sluiten; 108 afwijking(en), 0 geaccepteerd" · "1 bron-administratie(s) getoetst, 108 afwijking(en) totaal (0 geaccepteerd), 0 fout(en)"
· "LEES-ONLY afgerond — niets vastgelegd" · container-exit 1 (= afwijkingen, verwacht). Per soort identiek aan 19-09 middag:

| Soort | Doel | N |
|---|---|---|
| `da_ontbreekt_in_doel` | Molenhof Beheer | 99 |
| `da_ontbreekt_in_doel` | Oirschot Recreatie | 3 |
| `da_inkoop_zonder_verkoop` | Veldhoven Recreatie | 3 |
| `da_bedrag_afwijkt` | Veldhoven Recreatie | 2 |
| `da_inkoop_zonder_verkoop` | Molenhof Verhuur | 1 |

Ruwe uitvoer: `.scratch/nameting-da-alleen-2026-09-19.txt` (133 regels, niet gecommit) en Cloud Logging op de executienaam.

## Stap 6 — BLOW c9ba6d8d: klikpunt blijft

Leesreplica (scope BLOW `5419878c`): `c9ba6d8d-ad7f-4c3c-a37b-111257b8643b` "2023-12-13_div. crediteuren_20230872.pdf" status
**`te_controleren`**, `laatst_gewijzigd_op` 2026-09-18 11:05:14 UTC — onveranderd sinds het rapport van 19-09 middag; het origineel
`0bbb1a1d-9650-…` idem `te_controleren` (10:39:56). Niemand heeft geklikt en er is bewust geen schrijvende job gedraaid.

## Stap 5 — extractie-wachtrij-tellers

`gcloud run jobs executions list --job rlz-extractie-wachtrij`: élk uur exact 6 executies van 18-09 12:00 UTC t/m 19-09 16:00 UTC (18-09 11:00
UTC = 118, de BLOW-bulk; 14:00 UTC = 9). Sinds de deploy van de bundel-fix geen bulk-upload → `trigger_gebundeld`/"geen 429" niet meetbaar.

## Stap 1–3 — stand op de leesreplica VÓÓR de run van 20-09 (NULL-scope-rijen; de 174 fouten hebben `administratie_id` NULL)

- Laatste run `klaar` = `772e6c3c` (scheduler 19-09 04:30:20 → 04:44:27 UTC, exit 1, `mail_status` = `actie=verzonden;systeem=uitgeschakeld`);
  bevindingen NULL-scope: **174 × `intercompany`/`fout`** + 2 × `automatisering`/`let_op`. `soort_standen` = `{rc_sluit_niet: meten,
  ic_ontbreekt_bij_ontvanger: meten}` (nog geen `da_ontbreekt_in_doel`). Audit `reconciliatie_auto_gesloten`: 66 rijen, alle 18-09,
  `dubbele_betaling_vermoed` (som `aantal` 1199) — géén andere soort ooit.
- **Bevinding tijdens het lezen van het meetrecept (bron-vs-realiteit):** de run van 20-09 zou de 174 fouten ZONDER SPOOR laten verdwijnen.
  `bepaal_delta` kende alleen `verdwenen_afwijkingen` (soort `afwijking`); een verdwenen `fout` stond niet in de delta, niet onder "Hersteld"
  in de systeemmail, en `_audit_verdwenen_dubbele_betaling` schreef `reconciliatie_auto_gesloten` uitsluitend voor `dubbele_betaling_vermoed`.
  De regel in CLAUDE.md (reconciliatie 2 "verdwenen bevindingen sluiten mét audit") en het meetrecept (stap 1 "audit … 174 verdwenen") waren
  generieker dan de code — gedocumenteerd ≠ gebouwd, en in strijd met kernprincipe 4 ("niets verdwijnt stil"). Meten zonder fix = een
  gegarandeerde 0.

## Gebouwd in deze run

1. **Verdwenen fouten tellen mee (`app/reconciliatie/run.py`):** `Delta.verdwenen_fouten` (zelfde regel als afwijkingen: concept weg =
   verdwenen; concept terug als andere soort = verschoven, niet verdwenen), `Delta.verdwenen` (afwijkingen + fouten), `is_leeg` telt ze mee;
   systeemmail krijgt "Hersteld — N fout(en) uit de vorige run niet meer gezien:" naast de afwijkingen-regel.
2. **Audit generiek: `_audit_verdwenen_bevindingen`** (vervangt `_audit_verdwenen_dubbele_betaling`): per (soort × bevindingssoort ×
   administratie) één `reconciliatie_auto_gesloten` mét `soort` (= `detail.afwijking_soort`, anders `<blok>:<soort>`), `bevinding_soort`,
   `blok`, `administratie_id`, `aantal`, `vingerafdrukken` ≤ 200, `reden` ("niet meer geproduceerd door run <id> — fout uit de vorige run
   verdwenen (blok intercompany)"; `dubbele_betaling_vermoed` houdt zijn herdefinitie-reden). Idempotent: alleen de delta t.o.v. de vorige
   afgeronde run. Verwachting 20-09: één rij `ic_spiegel_rood` / `fout` / `intercompany` / NULL / 174.
3. **`samenvatting["delta"]` op de run-rij:** nieuwe_afwijkingen / nieuwe_let_op / nieuwe_geaccepteerd / nieuwe_fouten / verdwenen_afwijkingen /
   verdwenen_fouten / blokken_fout — de herstelregel is anders alleen leesbaar in een systeemmail die in productie `uitgeschakeld` is en
   dus nergens meetbaar. Geen migratie (0114-JSONB), frontend itereert de sleutels niet (`SamenvattingDto` is sleutel-agnostisch).
4. **"Niet vóór"-poort in de inbox-runner (`scripts/cc_inbox.sh` rij (k), `scripts/zsh/rlz.zsh`):** een opdracht mét een regel
   `niet vóór: JJJJ-MM-DD[ UU:MM]` (eerste 20 regels, ook "niet voor:", vet/blockquote mag; lokale tijd, zonder tijd = 00:00) wordt pas ná dat
   moment geclaimd; tot dan "wacht — X niet vóór … (nog N min); volgende kandidaat" hoogstens elk uur in het log (stand
   `opdrachten/log/.wacht-nietvoor-<slug>`, géén macOS-melding — verwacht wachten is geen incident), `rlz inbox status` toont
   "inbox/: X — wacht tot …". Reden: de regel van 19-09 ("een vervolg-opdracht in de inbox met de datum van die run") werkte niet — de
   runner las de datum niet, poging 1 startte 11,5 uur te vroeg en de kassarapport-vervolgopdracht van 20-09 zou vanavond hetzelfde doen.
   Die opdracht (`2026-09-20-nameting-kassarapport-autotype-na-echte-run.md`) heeft nu óók de `niet vóór: 2026-09-20 07:15`-regel.
5. **Tests:** `tests/reconciliatie/test_run.py` (+2: delta verdwenen fout / verschoven soort; herstelregel fouten in `bouw_mail`),
   `tests/reconciliatie/test_soort_stand.py` (+1 end-to-end: run mét 2 fouten `ic_spiegel_rood` + 1 afwijking → run zonder → 2 audits per soort,
   NULL-scope voor de fouten, derde run schrijft niets bij, `samenvatting["delta"]` beide runs; bestaande dubbele-betaling-test ongewijzigd
   groen), `tests/unit/test_cc_inbox_claim_en_poort.py` (+4: toekomst = geen claim + logregel eens per uur + status-regel + geen melding;
   verstreken = claim; oudste-mtime-maar-te-vroeg laat de volgende voorgaan; scripts documenteren rij (k)).

## Keuzes zonder Peter (vastgelegd)

- **Geen échte run geforceerd** (regel 19-09 letterlijk: actiemail buiten het dagritme) — poging 2 meet ná de scheduler.
- **Audit generiek i.p.v. alleen `ic_spiegel_rood`:** de regel was al generiek geformuleerd; een soort-specifieke tweede uitzondering zou
  dezelfde stille verdwijning voor de volgende gefixte systeemfout laten staan. De dubbele-betaling-reden blijft letterlijk (bestaande test).
- **Verdwenen fouten alléén maken géén systeemmail nodig** (`systeemmail_nodig` ongewijzigd: blok-fout / nieuwe fout / nieuwe LET-OP /
  regressie) — herstel is informatie, geen handeling; het spoor is het audit + `samenvatting["delta"]`.
- **Niet-vóór-poort als kopregel in het bestand, niet als bestandsnaam-conventie:** de datum in de naam is de opdrachtdatum (logbestand,
  rapport), niet het startmoment; en de opdracht kan zichzelf mét een nieuwe regel terugleggen (stap 0 van poging 2 zegt precies dat).
- **Tijd 07:15** voor de vervolg-opdrachten: run 04:30 UTC + ~15 min = 06:45 NL, marge voor een deploy van deze commit (Stop-hook-push →
  deploy ~6 min) en de nameting-bot van 05:30 UTC (07:30 NL — stap 0 van poging 2 merget een eventuele bot-commit).

## Klikpunten

1. BLOW: document "2023-12-13_div. crediteuren_20230872.pdf" (id c9ba6d8d, ontvangen 18-09-2026, status `te_controleren` op de
   leesreplica 19-09 19:00) alsnog afvoeren als duplicaat van 0bbb1a1d — dry-run op de job-image (19-09, executie `k57ql`) bewees exact 1.
2. Kempen Facilities → Molenhof Beheer: 99 verkoopfacturen zonder inkoop bij Molenhof Beheer (executie `j6kgg`, 15-08-2025 … 2026, € 53 – € 76.021)
   — worden die daar buiten de KF-crediteurrecords geboekt? Bepaalt of `da_ontbreekt_in_doel` ná de explosie-rem van 20-09 terug naar `actie` mag.
   Klikpunten 3–5 van het rapport van 19-09 middag (Oirschot ↔ Veldhoven 3 nummers, Veldhoven € 69,82 verwisseling, Molenhof Verhuur 24713191)
   staan ongewijzigd.

## Suite
`tests/reconciliatie/test_run.py` + `test_soort_stand.py` + `test_actiemail_guard.py` + `tests/unit/test_cc_inbox_*.py` (4 bestanden):
122 passed (1:20) vóór de `samenvatting["delta"]`-patch; **ná de patch volledige `tests/reconciliatie` + inbox-guard: 405 passed
(2:31)**; laatste ronde (drie reconciliatie-bestanden + inbox-guard + docs-guards CLAUDE.md↔BESLISSINGEN, regels-INDEX, rapporten-INDEX,
gelezen regels, klikpunten): 96 passed ná een INDEX-fix (vierkante haken in de linktekst breken de INDEX-regex). Vitest `src/changelog`: 5 passed.
Ruff: geen nieuwe meldingen in de eigen regels (E501 van bestaande regels ongewijzigd). Gouden set niet geraakt (geen wijziging onder app/intake, app/extractie, app/documenten of frontend/src/document).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/reconciliatie.md` (138 regels — stand vóór de run)
- `docs/regels/doorbelasting-intercompany.md` (163 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (174 regels — stand vóór de run)
