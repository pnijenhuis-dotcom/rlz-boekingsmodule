# Slotrapport 17-09 (dag, interactieve run) — inbox afgewerkt: negen opdrachten, 16 commits, migraties 0153–0156

Volgorde en uitkomst per opdracht (rapport per opdracht in deze map; beslispunten gebundeld in `2026-09-17-beslispunten-peter.md`).
Regels gevolgd: geen RLZ-/Odoo-writes; productie uitsluitend lees-only via `scripts/gcp/nameting.sh` (interactief mét geldige gcloud-sessie,
`NAMETING_VIA_GH=0`) of `gh workflow run nameting`; migratie-afsluitroutine per migratie; `git pull --ff-only`/rebase vóór de commitreeks;
klikpunten mét bron-id + datum + bedrag (guard).

| # | Opdracht | Commits | Kern | Werkt in productie |
|---|---|---|---|---|
| 1 | SPOED Xcode Cloud / Apple 1.1 live | `07aa2d1` `2f93577` `eef3100` | Package.resolved bijgewerkt + guard; marketingversie 1.2 (vc6); `STORE_APP_VERSIE_IOS=1.1` service + jobs; bucket-script mét default-SA-fallback; `nameting.sh` via gh voor niet-interactieve runs | niet gemeten (ná push/deploy) — `2026-09-17-apple-1-1-live-xcode-cloud.md` |
| 2 | SPOED dubbele betaling 1.214 | `7a67cb5` `3c33c0a` | lees-only telling (67 administraties; Belastingdienst/KF/Nijenhuis/Floor/Lusso = periodiek, IC, batch); herdefinitie = betalingen > facturen; soort-stand `meten`/`actie` + explosie-rem + actiemail ≤ 3/administratie; auto-sluiten mét audit; migratie 0153 | niet gemeten (eerste run ná deploy) — `2026-09-17-dubbele-betaling-herdefinitie.md` |
| 3 | Feiten eerst | `5128934` `033d562` (+ guard-fix) | `db-lezen` querybibliotheek + rol `rlz_lezer` (0154); vrije SELECT replica-only (`POST /lezen/sql`, `db_lezen.sh`); `rlz-feiten rlz|bank`; klikpunt-guard + `bank_toets`; workflow-onderdeel `query`; WERKWIJZE v1.17; replica = owner-klikpunt | niet gemeten (ná deploy) — `2026-09-17-feiten-eerst-lees-toegang.md` |
| 4 | VGG schoonlijst dubbelen | `5b7de8b` `71cbf69` | dubbel = richting + tegenrekening (regels) + bankbevestigd, ± 3 d, beide bankregels + `bank_toets`; RLZ-01-00000006 = Receipt-concept € 43.666,14 13-08-2025; bankregel "test" = € −1,00 15-08-2026 Koppe open | blok A niet gemeten; B/C ja — `2026-09-17-vgg-schoonlijst-dubbelen-richting-bank.md` |
| 5 | VGG blok 11 pand = project | `3dc4f62` `10a386a` | STAP-0: 83 projecten, project op de inkoopregel, niet op bank/journaal; instrument Project-dekking in `vgg-replay`; `pand.rlz_project_id` + `--bron project` (0155) | samples ja, dekking/CLI niet gemeten — `2026-09-17-vgg-blok-11-pand-uit-rlz-project.md` |
| 6 | VGG blok 10 één regel, één bestemming | `990a6ad` `2ee2616` | rol nooit op 10xx, aanbetaling = tegenzijde, overlap-guard ROOD, kolom RJ-220-tegenzijde; 24 regels herleid (kruisposten 1011 / spaar 1002); vijfde meting ná deploy | nee (niet gedeployd) — `2026-09-17-vgg-blok-10-een-regel-een-bestemming.md` |
| 7 | Accordering laag per leverancier | `811f471` | leveranciersroute vervangt de administratieroute (0156), identiteit, 409, herberekening, routes-CRUD, Beheerder-blok | niet gemeten — `2026-09-17-accordering-laag-per-leverancier.md` |
| 8 | OTA nameting-2 | `ba06b6b` | stap 0 niet voldaan (geen deploy sinds de bucket) → gestopt mét melding; vervolg -3 | niet gemeten — `2026-09-17-native-ota-nameting-2.md` |
| 9 | Doorbelasting-aansluiting nameting-2 | `ba06b6b` | via workflow: herkoppeling Kempen Chalets GEKOPPELD; 928 sluit / 59 / 2 / 166 — structurele beslispunten | **ja** — `2026-09-17-doorbelasting-aansluiting-nameting-2.md` |

## Testbeeld
Backend gerichte suites per opdracht groen (o.a. reconciliatie+bank+keten 830, migratie 273+16, lezen 17 + gates 511, panden 284 + replay 56,
accordering 607); frontend `tsc -b` groen, vitest reconciliatie 43 / instellingen 261 + 3 / changelog 5; doc-guards (CLAUDE.md-verwijzingen,
rapporten-index, klikpunten) groen. Geen volledige backend-suite in één run gedraaid (tijd); de per-blok-suites dekken alle geraakte modules.

## Migraties (afsluitroutine gedaan per stuk)
0153 `reconciliatie_instelling.soort_standen` · 0154 rol `rlz_lezer` · 0155 `pand.rlz_project_id` · 0156 leveranciersroute — dev-DB op 0156,
`alembic check` schoon, `schema_referentie.sql` op head 0156, live 200 per geraakte route (0155: geen route → CLI/tests).

## Klikpunten Peter (compleet, met bron)
1. IAM `roles/storage.objectViewer` voor `run-backend@rlz-boekhouding.iam.gserviceaccount.com` op `gs://rlz-boekhouding-app-bundels` (IAM-policy 17-09; commando in rapport 1).
2. Leesreplica + IAM-DB-gebruiker: `scripts/gcp/leesreplica.sh --apply` → `GRANT rlz_lezer TO "nameting@rlz-boekhouding.iam"` → env `LEES_DATABASE_URL` (rapport 3, GCP_UITROL §F7.4).
3. Bankregel "test": mutatie `aa06acac…`, 15-08-2026, € −1,00, open, J. Koppe en/of W.L.J.F. Koppe (rapport 4) — boeken of terugboeken.
4. RLZ-01-00000006: Receipt-concept `e37e36fb…`, 13-08-2025, € 43.666,14, Rijswijkseweg 409 (rapport 4) — beoordelen.
5. Nulfactuur 24712873 Veldhoven Recreatie 28-05-2026 € 0,00 ↔ 24712869 € 69,82 (rapport 9).

## Vervolg in de inbox (door deze run aangemaakt)
`2026-09-17-apple-1-2-xcode-cloud-nameting.md`, `2026-09-17-vgg-vijfde-meting.md`, `2026-09-17-native-ota-nameting-3.md`.
**Niet aangeraakt (door Cowork tijdens de run toegevoegd, niet in de opgegeven volgorde):** `2026-09-17-mockup-betalingen-tab.md`,
`2026-09-17-SPOED-herstellink-accordeur-landt-op-web.md` — volgende run.

## Aandachtspunten
- CLAUDE.md staat op ~142k tekens (limiet 150k, guard) — bij een volgende run tekst naar BESLISSINGEN verhuizen.
- Cloud Logging laat regels vallen bij grote `rlz-lezen`-uitvoer (bankvensters 22–27 van 40–115 leesbaar) — `rlz-feiten bank --bedrag` ná deploy is de compacte route (rapport 6).
- De OTA-bundel registreert onder runtime 1.2 ná deze push; de live 1.1-schil krijgt geen bundel (beslispunt opdracht 1).
