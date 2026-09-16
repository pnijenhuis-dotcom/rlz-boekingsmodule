# Slotrapport inbox nacht 16/17-09 — zes opdrachten afgewerkt

Opdracht Peter (16-09 avond): werk `opdrachten/inbox/` één voor één af. Regels: geen RLZ-/Odoo-writes, productie lees-only via
`nameting.sh`, migratie-afsluitroutine, gouden set groen, `pull --ff-only` vóór commits, rapport + INDEX per opdracht, beslispunten =
default + notitie. Handmatige sessie (pid 36860) via de interactieve CC; de cc-inbox-tick wachtte de hele nacht (rij (f)).

## Uitkomst per opdracht

| # | Opdracht | Commit | Werkt in productie | Rapport |
|---|---|---|---|---|
| 1 | Store-nazorg iOS 1.1 (140) ingediend, Play vc2 live / vc4 in review — docs + deploy.yml-voorwaarde | `e52670b` | n.v.t. | `2026-09-16-store-nazorg.md` |
| 2 | VGG blok 9 vierde meting ná deploy (lees-only) | `3b5ad89` | **ja** — 1001-model live (164 regels: 140 → outstanding BNK1 id 132, 24 tussenrekening, 0 meerduidig); oordeel ROOD 6 verschillen, 2 nieuw op 3606/3607 = herclassificatie vanaf 1001 → gerapporteerd, niets gebouwd | `2026-09-16-vgg-vierde-meting.md` |
| 3 | cc-inbox parallelle runs — oorzaak (rij (f) niet stuk, check alleen bij start; cwd buiten repo mogelijk) + guard (lock mét soort/pid/tijd, `.git/index.lock`, `rlz cc`, `rlz inbox status\|stop`) | `7c3fd35` | n.v.t. (lokale werkloop) | `2026-09-16-cc-inbox-parallel.md` |
| 4 | Doorbelasting KF: herkoppeling doelentiteit (exact = koppelen, bijna-match = LET-OP), lees-only CLI `doorbelasting-aansluiting` + reconciliatieblok `doorbelasting_aansluiting`, Kempen Chalets ná deploy | `66e567a` | niet gemeten → vervolg-opdracht `2026-09-17-doorbelasting-aansluiting-nameting.md` | `2026-09-16-doorbelasting-aansluiting.md` |
| 5 | Native app OTA (capgo self-hosted), 426-poort "Update nodig", Android in-app-update, Beheerder-blok App-updates; migratie 0152 | `5ba1e9a` | niet gemeten → klikpunten bucket (`app_bundels_bucket.sh --apply`) + winkelrelease mét plugins; vervolg-opdracht `2026-09-17-native-ota-nameting.md` | `2026-09-16-native-ota.md` |
| 6 | Betalen via Ponto = eigenaar Jarvis; RLZ levert feiten en ontvangt status (docs-only, registerrij + OPEN_ITEMS RLZ → Jarvis) | `d1884ac` (+ Platform `ae167d2`) | n.v.t. | `2026-09-16-betalen-eigenaar-jarvis.md` |

## Testbeeld

| Poort | Uitkomst |
|---|---|
| cc-inbox guards (parallel 10 + herstel 21 + pull) | groen |
| doorbelasting herkoppeling 11 + aansluiting 13 + teller 2; regressiebatch reconciliatie/intercompany/beheer/sync | 428 groen |
| appupdate 9 + marketingversie/envset/deploy-guards | groen (45 doc-/deploy-guards) |
| backend batch auth + security + unit + beheer (opdracht 5) | 1217 groen; 3 failed + 8 setup-errors in de rol-gate-sweep op routes buiten deze run (verzamelbak/intake/uren) — herrun apart 463/463 groen: flakes van de gedeelde test-DB, geen regressie |
| frontend `tsc -b` (pre-commit) + vitest reconciliatie/doorbelasting 101, accordeur/instellingen/api/changelog 120 | groen |
| migratie 0152 | dev-DB `alembic upgrade head` → 0152, `alembic check` schoon, live 200 (`/app/update-manifest`) / 426 / 401 op uvicorn 8012, `schema_referentie.sql` ververst |
| gouden set / keten-guard | niet geraakt (geen wijziging onder app/documenten, app/intake, app/extractie, frontend/src/document); `test_keten_guard` groen |
| overflow-sweep | niet gedraaid (Chrome-harnas; instellingen-harnas mét App-updates-mocks aangevuld) |

## Beslispunten Peter (defaults, `2026-09-16-beslispunten-peter.md` opdrachten 15/16 + per rapport)

- VGG: 3606/3607-verschil = schoning volgt het 1001-model nog niet → eerst lees-only rapportfix vóór een vijfde meting; geen SCHRIJF c.
- Doorbelasting: bijna-match nooit auto-koppelen; KvK-basis niet mogelijk zonder extra RLZ-call; venster ± 7 d (één motor) i.p.v. ± 5 d.
- OTA: migratie 0152 wél; bundel via de backend (bucket privé); geen signing fase 1; 426 alleen voor aangekondigde schillen — de
  geïnstalleerde 1.0/1.1(140) blijven onder de legacy-Sunset-route.
- Ponto: vier-ogen + limieten als defaults bij Jarvis; 0028-uitzondering voor het 0006-besluit.

## Klikpunten Peter

1. Apple: ná goedkeuring 1.1 → `STORE_APP_VERSIE_IOS=1.1` + train-regel → 1.2; Google: ná vc4 → `STORE_LINK_ANDROID` + vc5 (mét OTA-plugins).
2. `scripts/gcp/app_bundels_bucket.sh --apply` (owner) — anders blijft de OTA-deploystap rood (service draait door).
3. Handmatige CC vanaf nu via `rlz cc` (zet de inbox-lock; weigert bij een lopende inbox-run).
4. Platform-repo: niet-eigen wijzigingen (`CLAUDE.md`, `registers/conventies.md`, `registers/koppelingen.md`) stonden ongecommit en zijn
   met rust gelaten.

## Inbox ná deze run

`2026-09-17-doorbelasting-aansluiting-nameting.md`, `2026-09-17-native-ota-nameting.md` (beide ná deploy; lees-only).
