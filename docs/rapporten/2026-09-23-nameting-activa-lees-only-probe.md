# Nameting activa 23-09 — lees-only reconciliatie schrijft de register-probe niet meer (fix 22-09) + activa-kaart in productie gebruikt (BLOw)

**Opdracht:** `opdrachten/gedaan/2026-09-23-nameting-activa-lees-only-probe-na-deploy.md` (`niet vóór: 2026-09-23 09:00`).
**Context:** rapport `2026-09-22-nameting-activa-fase1-en-bua.md` (bijvangst 3), BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)"
alinea "Gemeten 22-09", fix-commit `c263182` (22-09 20:22 NL): `probe_register(…, schrijf=False)` bij `verzamelaar is None`.
**Pogingen:** de eerste cyclus (17:48 NL, drie starts binnen 20 s) stierf drie keer direct op de gebruikslimiet zonder één regel werk en
eindigde in `mislukt/`; Peter zette de opdracht terug. Poging 1 van de tweede cyclus (19:16–19:48 NL) deed stap 1–3 (bot-bestanden op main) en
schreef de BUG-opdracht van stap 4, maar eindigde vóór de poort → WIP-branch `wip/2026-09-23-nameting-activa-lees-only-probe-na-deploy`
(`d8bd175`, alleen de inbox-verplaatsing). Deze poging 2 begon met `git merge --squash` van die branch, herhaalde de nastand kantoorbreed,
mat stap 4 opnieuw uit de bron en haalde de poort. De WIP-branch blijft ter controle staan.

## Uitkomst in één alinea
- **Fix 22-09 — een lees-only reconciliatie schrijft de register-probe niet meer: werkt in productie JA.** Ná de lees-only executie
  `rlz-reconciliatie-5sqzm` (17:25–17:47 UTC, image `1ca9471`, blok `activa` 75 administraties getoetst) staat `register_geprobeerd_op` bij
  **75/75** RLZ-administraties mét `activa_instelling` nog op het sync-moment van 07:00 NL (05:00:43–05:03:00 UTC, `rlz-sync r5td7`) — ook op
  het 403-pad (Universal Steigerbouw, Rubicon). Op 22-09 verschoof datzelfde veld bij 75 administraties naar het meetmoment.
- **Activa-kaart — kaart + "Aanmaken ná boeken" JA, activum in RLZ NEE.** De kaart is op 23-09 twee keer écht gebruikt (BLOw B.V, inkoopfacturen
  23619 en 06052 op 0107 Kantoorinventaris): `POST …/activa-voorstel/1/aanmaken` 200, koppeling `gepland` (herkomst `mens`), boeking geslaagd
  (RLZ-04-00000400 / RLZ-04-00000459) — en daarna `activum_aanmaken_mislukt` "geen afschrijvingsrekening", géén `PUT FixedAssets`, RLZ-register
  BLOw leeg. Het blok `activa` meldt de twee rijen als `activum_aanmaken_mislukt` in `meten` (geen actiemail). BUG-opdracht staat in
  `opdrachten/inbox/2026-09-24-BUG-activa-kaart-aanmaken-mislukt-geen-afschrijvingsrekening-blow.md` (voorvullen conventie code + 1, 422 zonder
  rekening, `mislukt` ná mens-klik = actie).

## Stap 0 — deploy-check (poging 2, 19:55 NL)
- `git rev-list --count main..origin/main` = 0 bij start; tijdens de run kwamen drie bot-commits binnen (`f87b1c9`, `c0c8aa4` — eigen queries) →
  `git merge --no-ff origin/main` (`67b7a4a`), geen rebase.
- Service `rlz-backend` én alle 18 jobs op image `…backend:1ca9471…` (deploy-run 17:16→~17:22 UTC groen); fix-commit `c263182` is voorouder van
  `1ca9471` én van `ac7639b` (de image van de `sync-alles` van 05:00 UTC) — `git merge-base --is-ancestor`. De lees-only executie `5sqzm` liep op
  digest `sha256:4739849a…` = de tag `1ca9471` (`gcloud artifacts docker images describe`).

## Stap 1 — nulstand vóór de lees-only run (bot-bestanden, poging 1)
| administratie | bot-commit (UTC) | `register_probe` | `tijdstip` |
|---|---|---|---|
| Pilates Bloom B.V. | `3cab2fe` 17:22:58 | `leesbaar` | 2026-09-23 05:01:45.738542+00 |
| Universal Steigerbouw B.V. | `8169f02` 17:24:32 | `niet_leesbaar` — recht ontbreekt (403) | 2026-09-23 05:02:43.561762+00 |

Beide `instelling`-rijen: grens 450,00 / `grens_rlz` 450,0 / `grens_rlz_gelezen_op` 05:01:45 resp. 05:02:43 UTC (de sync). De eerste dispatch
(`bdae089`) strandde op argparse ("unrecognized arguments: Bloom'") — de workflow splitst de query-input op woorden, aanhalingstekens komen
letterlijk mee; `--administratie Pilates` / `Steigerbouw` / `BLOw` (één woord, naamdeel) werkt.

## Stap 2 — lees-only run
- Executie `rlz-reconciliatie-5sqzm`, args `-m app.cli reconciliatie-alles --lees-only`, 17:25:35→17:47:11 UTC, exit 0. **Afwijking van het
  recept:** het dispatch-onderdeel `reconciliatie` draait álle blokken lees-only, niet `--alleen activa`; het blok `activa` zit erin en probet
  precies zoals `--alleen activa` zou doen (zelfde `cli_blok`, `verzamelaar is None`).
- Bot-bestand `verkenning/nameting-reconciliatie-23-09.txt` (`8e3404a`), sectie `=== activa-reconciliatie (lees-only) ===`:
  **75 administratie(s) mét MVA-rekeningen getoetst, 24 afwijking(en)** — `activa_register_niet_leesbaar` 2 (Rubicon Investments, Universal
  Steigerbouw), `mva_boeking_zonder_activum` 0, `activum_zonder_boeking` 19, `afschrijving_niet_gelopen` 1 (Beauty by Tessa Elst), **`activum_
  aanmaken_mislukt` 2 (BLOw, nieuw t.o.v. 22-09)**; 3 Odoo-administraties OVERGESLAGEN. Alle soorten in `meten`, < 50 per soort.
  Register 2 = Peter heeft het RLZ-recht "Vaste activa" nog niet gezet (klikpunt blijft).

## Stap 3 — nastand (oordeel)
| administratie | bot-commit (UTC) | `register_probe.tijdstip` ná de run | t.o.v. stap 1 |
|---|---|---|---|
| Pilates Bloom B.V. | `b6a93be` 17:49:24 | 2026-09-23 05:01:45.738542+00 | **ongewijzigd** |
| Universal Steigerbouw B.V. (403-pad) | `f87b1c9` 17:59:25 | 2026-09-23 05:02:43.561762+00 | **ongewijzigd** |

**Kantoorbreed (leesreplica, `db_lezen.sh` per administratie in eigen RLS-scope, 18:00–18:02 UTC, exitcode per iteratie gelogd — les 23-09):**
80 administraties gelopen, 75 mét `activa_instelling`-rij: `register_geprobeerd_op` bij alle 75 tussen 05:00:43 en 05:03:00 UTC (= binnen de
`sync-alles` `r5td7` 05:00→06:21 UTC), **0 in het venster 17:25–17:47 UTC**; `register_leesbaar` 73 × true, 2 × false (Universal, Rubicon);
`grens_rlz_gelezen_op` idem het sync-moment. 5 zonder rij = 3 Odoo (fase 1 RLZ-only), de gearchiveerde testadministratie en de passkey-
testadministratie — verwacht. **Werkt in productie: JA.** (Poging 1's replica-loop van 19:48 NL greep per ongeluk de actor-regel van
`set_config` i.p.v. de resultaatrij en is weggegooid; deze loop zet een markerkolom `RIJ` vóór de waarden.)

## Stap 4 — activa-kaart (gemeten uit de bron; geen klikpunt meer nodig)
Request-log service sinds 21-09: `GET …/activa-voorstel` **1.267 × 200** (5 × 401 = token-vernieuwing), `POST …/activa-voorstel/1/aanmaken`
**2 × 200** + 1 × 401, 0 × 5xx, 0 × `/overslaan`. Beide POSTs op BLOw B.V (`5419878c`):

| document | referentie | factuur | geboekt als | POST aanmaken | koppeling | audit |
|---|---|---|---|---|---|---|
| `58b588e8` | 23619 | 10-10-2025, € 1.131,35 incl. | RLZ-04-00000400 (09:44:27 UTC) | 09:43:59 UTC 200 | `mislukt`, `mens`, inventaris 60 mnd, aanschaf € 935,00, balans 0107, afschrijving NULL, `rlz_fixed_asset_id` NULL | `activum_gepland` 09:43:59 → `activum_aanmaken_mislukt` 09:44:28 |
| `4fbda583` | 06052 | 31-05-2025, € 822,80 incl. | RLZ-04-00000459 (11:53:41 UTC) | 11:52:54 UTC 200 | idem, aanschaf € 680,00 | `activum_gepland` 11:52:54 → `activum_aanmaken_mislukt` 11:53:42 |

Reden in beide koppelingen én audits: "geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa";
`activa_instelling.afschrijving_ledgers` BLOw = `{}`, `automatisch_aanmaken_ingeschakeld` false. `rlz-lezen --administratie BLOw --pad FixedAssets`
(executie `47shn`, lees-only): **`value: []`** — niets aangemaakt; 0 × "FixedAssets" in service-/job-logs sinds 21-09 buiten de STAP-0-lezing van
21-09. **Werkt in productie: kaart tonen + plannen + boeken JA; activum aanmaken in RLZ NEE** (deterministisch te voorkomen: BLOw heeft per
balansrekening een "Afschrijving …"-rekening code + 1: 0101→0102, 0103→0104, 0105→0106, 0107→0108, 0109→0110, 0111→0112, 0113→0114,
0115→0116 — de mens sloeg de optionele combobox over). Fix + herstel-klikpunt: de BUG-opdracht in `opdrachten/inbox/` (geschreven door poging 1,
in deze commit meegenomen). **Bijvangst:** van BLOw's acht 0xxx-balansrekeningen dragen er vier `is_activa` (0101/0107/0111/0113); 0103 Verbouwing,
0105 Machines, 0109 Bedrijfsinventaris, 0115 Vervoermiddelen niet — `IsFixedAssetAccount` staat in RLZ kennelijk niet op die rekeningen (de vlag is
klant-instelling in RLZ; geen module-fout, wél een aandachtspunt voor de BUG-opdracht: een factuur op 0109 krijgt géén kaart).

## Keuzes in deze run
1. Stap 2 niet opnieuw gedraaid: de lees-only executie van poging 1 (`5sqzm`) staat als bot-bestand op main en liep op de fix-image; een tweede
   lees-only run zou alleen een tweede identieke nulmeting geven.
2. De nastand van Universal Steigerbouw is alsnog als dispatch-query gedaan (bot `f87b1c9`), plus kantoorbreed via de replica — het oordeel rust niet
   op één administratie.
3. Stap 4 is uit de bron herleid (request-log, `activum_koppeling`, `audit_event`, `boekvoorstel`, RLZ `FixedAssets`) i.p.v. "niet gemeten":
   de klik is intussen door een medewerker gedaan.
4. De stale `mislukt/`-kopie van deze opdracht (17:48, cyclus 1) is opgeruimd — de opdracht staat nu in `gedaan/`; de `mislukt/`-kopie van de
   Vastly-opdracht en de inbox-opdracht `2026-09-24-nameting-intake-postvak-…` zijn van andere runs en blijven staan (untracked).
5. Keten-sweep: de eerste volledige run gaf 2/11 rood (`a_universal_nederland__detail`, `b_floor__detail`, 14,6 % pixels — PDF-viewer nog niet
   gerenderd terwijl pytest parallel draaide); herdraai per casus mét `KETEN_ALLEEN` 2 × groen (66 resp. 0 pixels), baseline niet ververst
   (memory "keten-sweep PDF-viewer-flake").

## Poort (poging 2)
- pytest volledige suite: **7252 passed, 2 skipped** (1:00:58, gestart 19:57 NL); docs-guards (rapporten-index, gelezen-regels, klikpunten, regels-index,
  CLAUDE.md↔BESLISSINGEN) 15 passed ná het schrijven van de docs.
- vitest 255 bestanden / 1935 tests groen; `tsc -b` schoon; keten-sweep 11/11 groen (9 in de volledige run + 2 herdraai).
- Geen code geraakt (alleen docs + opdrachten + bot-bestanden via merge).

## Vervolg
- Fix + nameting van de kaart: `opdrachten/inbox/2026-09-24-BUG-activa-kaart-aanmaken-mislukt-geen-afschrijvingsrekening-blow.md` (bouw, dan
  herstel BLOw 2 activa als klikpunt, dispatch-onderdeel `activa-kaart`).
- Klikpunt Peter (ongewijzigd sinds 21-09): RLZ-recht "Vaste activa" op de webservice-logins van Universal Steigerbouw en Rubicon Investments.
- Verwacht in de échte run van 24-09 06:30: de 2 × `activum_aanmaken_mislukt` blijven staan (`meten`) tot de BUG-fix ze naar `actie` brengt of
  het herstel-klikpunt ze sluit.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/activa.md` (56 regels — stand vóór de run)
- `docs/regels/reconciliatie.md` (306 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (332 regels — stand vóór de run)
