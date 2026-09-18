# Rapport 18-09 — Inbox afgewerkt (zes opdrachten in volgorde, Peter 18-09 ochtend)

Opdracht Peter: "Verwerk alle opdrachten in opdrachten/inbox/ in deze volgorde, één voor één … Sluit af met
docs/rapporten/2026-09-18-inbox-afgewerkt.md." Regels nageleefd: geen git push (Stop-hook), geen secrets, productie alleen
lees-only (replica als nameting@, Cloud Logging), elk klikpunt mét bron+datum+bedrag, per rapport "werkt in productie: …".

**Vooraf gevonden:** de vorige run (`veldapp-uitvoerder-feedback`, migratie 0158) stond **ongecommit** in de werkboom mét een
open placeholder voor de backend-suite. Die suite is in deze run alsnog volledig gedraaid (6487 groen, 1 skipped, 1 u 26 min) en
ingevuld; het werk gaat mét deze run mee naar main.

| # | Opdracht | Uitkomst | Rapport | Werkt in productie |
|---|---|---|---|---|
| 1 | veldapp-uitvoerder-nameting | **gestopt op stap 0**: service én jobs op `47cf967` zonder 0158 (deploy volgt pas ná deze run) → opdracht terug in de inbox mét wacht-op-deploy-aanwijzing en de meetrecepten van álle opdrachten hieronder (punten 6–10) | `2026-09-18-veldapp-uitvoerder-nameting-stap0.md` | niet gemeten |
| 2 | veldapp-project-eerst-flow | gebouwd: week = projectkaarten (gepland ∪ mét uren ∪ mét meerwerk ∪ zelf toegevoegd), dagbalk, "+ Uren"/"Meerwerk melden" per kaart, "+ Ander project" (`?alles=true`), "Week indienen"; set-based (bijvangst N+1 in `_planning_stand` weg) | `2026-09-18-veldapp-project-eerst.md` | niet gemeten |
| 3 | veldwerker-rol-wijzigen | gebouwd: rol-select op tab Veldwerkers, `rolgroep`-poort (binnen kantoor/veld/accordeur ok, tussen groepen 409), audit via bestaande trigger, app volgt bij tokenverversing | `2026-09-18-veldwerker-rol-wijzigen.md` | niet gemeten (klikpunt Peter: Irfan → uitvoerder) |
| 4 | BUG chip meerwerk/urenstaten | databewijs: 14 weekstaten `ingediend` (W37, Universal), 0 meerwerk; fix = Beoordelen mét tabs Urenstaten (N) · Meerwerk (M) uit dezelfde definitie als de chip (guard), kantoor-keuring, **uitvoerder keurt álle ingediende urenstaten in scope** (koppeling = alleen "gepland bovenaan"), overflow-sweep groen | `2026-09-18-beoordelen-urenstaten-meerwerk.md` | niet gemeten |
| 5 | SPOED web-app Edge Android | diagnose op data: server wees nooit af (4 × vernieuwen 200), 5 herladingen → toegangscode-scherm; de echte uitlog 09:27:21 = blokkade/archivering door het kantoor (workaround rol wijzigen); fix = acht client-waarborgen (ontgrendel-venster 5 min, Android-terugknop, geen body-pull-to-refresh, persist(), eerlijke melding, diagnose, beginscherm-kaart, mailzin) | `2026-09-18-webtoestel-edge-android.md` | niet gemeten |
| 6 | veldapp-ux-verbeteringen-12-punten | mockup v3 → run A gebouwd (punten 1–3, 6–12; migratie 0159 chips); run B (4, 5) klaargezet als `2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md` | `2026-09-18-veldapp-ux-run-a.md` | niet gemeten |

**Nieuw in de inbox, NIET in Peters volgorde en niet verwerkt (aangekomen tijdens de run):** `2026-09-18-mockup-factuuropdracht-per-project.md`,
`2026-09-18-projecten-status-afsluiten-en-nummer-uniek.md` — voor de volgende inbox-tick. Plus de twee die deze run klaarzette:
`2026-09-18-veldapp-uitvoerder-nameting.md` (ná deploy) en `2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md`.

## Eén regel voor Peter

Op de tablet van de uitvoerder: app in Chrome/Edge openen → menu → "Toevoegen aan startscherm/telefoon" en vanaf het beginscherm
starten; ná de deploy vraagt de app binnen vijf minuten ná verversen of terugknop geen code meer. Het account dat vandaag "Orfan
Ogur" heet is het nieuwe uitvoerder-account (typo in de naam — klikpunt); het oude ZZP'er-account staat gearchiveerd (0 weekstaten).
Rol wijzigen kan vanaf nu zonder nieuw account.

## Tests en poorten

| Poort | Uitkomst |
|---|---|
| Volledige backend-suite (stand feedback-run, start 10:07) | 6487 groen, 1 skipped |
| `tests/uren` + `tests/security/test_rol_endpoint_gates.py` + `tests/auth/test_rol_wijzigen_veld_18_09.py` (eigen DB, herrun ná de bouw van 2–5) | 749 groen ná 3 fixture-reparaties (scope voor de keurende uitvoerder), zie rapport 4 |
| Backend run A (bouwagent, eigen DB) | <<RUN_A_BACKEND>> |
| Volledige frontend-suite (`vitest run`, 11:27, ná opdracht 5) | 217 bestanden / 1732 tests groen; ná run A: <<VITEST_EIND>> |
| `tsc -b` | groen |
| Docs-guards (CLAUDE.md↔BESLISSINGEN, regels-index, rapporten-index/gelezen-regels/klikpunten, cc-inbox) | 24 groen (aparte guards-DB) |
| Overflow-sweep `?beoordelen=1` | 8 metingen groen |

**Eerlijk:** de pre-existing klikpunt-guard-fout in `2026-09-17-vgg-plan-na-lezer-fix.md` (regel 29 zonder datum/bedrag) is in
deze run gerepareerd met de feiten uit `verkenning/nameting-vgg-replay-13-09.txt` r. 1274; Playwright-emulatie (opdracht 5) is niet
gebouwd (geen Playwright in de repo); per-opdracht-commits waren voor gedeelde bestanden (UrenFlow, BESLISSINGEN, INDEX, CLAUDE.md)
niet meer te scheiden — de commits zijn per laag gegroepeerd en noemen alle opdrachten.

## Commits

<<COMMITS>>

## Lessen (geheugen bijgewerkt)

- `db_lezen.sh`: `weekstaat`/`meerwerk` hebben geen Beheerder-RLS-clausule — altijd `--administratie <uuid>`; bekende actor `2f2262cd…`.
- Ook op een eigen test-DB nooit twee pytest-sessies tegelijk (17 min verloren): één DB per gelijktijdige run, guards op een derde DB.

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (300 regels), `docs/regels/werkloop-productie.md` (55), `docs/regels/accordering-native-app.md` (264),
  `docs/regels/auth-toegang.md` (160), `docs/regels/werkvoorraad-controlescherm.md` (185), `docs/regels/kantoor-frontend.md` (106) — volledig, vóór de
  start van de betreffende opdrachten (Domeinen-kopregels).
