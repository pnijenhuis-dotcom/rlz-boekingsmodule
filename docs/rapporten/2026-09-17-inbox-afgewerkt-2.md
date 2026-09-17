# Slotrapport inbox 17-09 (middag/avond, handmatige sessie) — zes opdrachten + launchd-blok; drie vervolg-opdrachten in de inbox

Run van Peter 17-09 ("Verwerk alle opdrachten in opdrachten/inbox/ in deze volgorde … Daarna, als laatste blok: de launchd-agent …"). Alle opdrachten staan in `opdrachten/gedaan/` mét kopregel; per opdracht een rapport in deze map.

| # | Opdracht | Rapport | Werkt in productie |
|---|---|---|---|
| 1 | Apple 1.2 / Xcode Cloud nameting | `2026-09-17-apple-1-2-xcode-cloud-nameting.md` | deploy + OTA-registratie + 426 + App Store-link ja; Xcode Cloud niet gemeten; manifest-url http → gefixt |
| 2 | Herstel-link "update eerst de app" (casus Romy) | `2026-09-17-herstellink-app-versie-update-eerst.md` | niet gemeten (fix ná deploy); oorzaak bewezen uit het request-log; Romy zelf: gekoppeld 11:06:04Z |
| 3 | Leesreplica afronden (migratie 0157, deploy-envset, smoketest) | `2026-09-17-leesreplica-afronden.md` | niet gemeten (ná deploy) |
| 4 | Native OTA nameting-3 | `2026-09-17-native-ota-nameting-3.md` | manifest/zip/426 ja; downloadlink-schema nee (gefixt); toestel niet gemeten |
| 5 | VGG vijfde meting + aanvulling auto-posten | `2026-09-17-vgg-vijfde-meting-en-auto-posten.md` | blok 10 ja; blok 11 nee (instrumentfout gefixt); SCHRIJF c/auto-posten niet gemeten (niet uitvoerbaar op de gedeployde image; instrument gebouwd) |
| 6 | CLAUDE.md → docs/regels met leesplicht | `2026-09-17-claude-md-regels-per-domein.md` | n.v.t. — 145.479 → 50.514 tekens, 164 blokken verbatim, 18 regelsbestanden, guards |
| 7 | launchd/cc-inbox stond zeven uur stil | `2026-09-17-cc-inbox-wacht-nooit-stil.md` | n.v.t. (lokaal) — oorzaak: `wacht — handmatige CC actief (pid 82714, …)` = deze interactieve sessie sinds 08:19:00; fix rij (h) |

## Dwarsverbanden / gevonden bugs buiten de opdrachten
- **Nameting-workflow bot-commit rood op een lege pathspec** (`verkenning/lezen-*.txt`) — drie runs vandaag verloren hun bot-bestand; gefixt (nullglob) + guard.
- **OTA-manifest gaf `http://`-downloadlinks** (proxy-hop) — gefixt (`publieke_basis_url`).
- **`test_deploy_kvk_config.py` was op HEAD al rood** (regex stopte niet op `|` sinds de envset-consolidatie 16-09) — gerepareerd.
- **Project-dekking-instrument las nooit een project** (document-vorm-expand zonder `Project`) — gefixt + guard.
- VGG dry-run `plan` gebruikte de bron-key default "Universal Steigerbouw" → migratiedoel-dry-run "geen Odoo-koppeling" (bekend: `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"`); in de vervolg-opdracht opgenomen.

## Klikpunten Peter (bron + datum + wat)
1. **Xcode Cloud build ≥ 145 (1.2)**: mail "processing completed" groen? (bron: Xcode Cloud-mail 17-09; rood → letterlijke tekst in de inbox).
2. **VGG IBAN op BNK1 (company 6)**: staat 'm er? De `plan`-dry-run ná deploy toont het (stap 4); zonder IBAN geen SCHRIJF c (bron: `vgg-odoo-stap0` dry-run 17-09 ~14:30Z kwam niet bij stap 4).
3. **GO op SCHRIJF c-rapport** (ná deploy + `SCHRIJF c`) vóór `SCHRIJF d` (auto-posten van alles) — één woord.
4. **1.2-schil op een toestel** (TestFlight/Play intern) voor de OTA-toestelstap (Toegang › Diagnose `bundel <sha7>`).

## Testbeeld (deze run)
Backend gericht: appupdate 9, nameting-workflow 16, berichten/auth 70, config/deploy-guards 33, migratie 61 + 54, cc-inbox 36, regels-guards 4, CLAUDE.md-guard 3 — groen; brede selectie (unit/migratie/berichten/auth/appupdate/lezen/rlz) en de volledige frontend-suite: zie de laatste sectie van dit rapport. `tsc -b` groen. Migratie 0157: dev-DB head, `alembic check` schoon, dump ververst, health 200.

## Vervolg-opdrachten in `opdrachten/inbox/` (mét `Domeinen:`-kopregel)
1. `2026-09-17-leesreplica-nameting.md` — smoketest-replica-toets, `onderdeel=query`, `db_lezen.sh` SELECT/INSERT-bewijs.
2. `2026-09-17-herstellink-nameting.md` — keuzescherm bij herstel, mailvolgorde, app-versie-chip, manifest `https`, OTA-toestel.
3. `2026-09-17-vgg-schrijf-c-na-deploy.md` — `plan` (IBAN) → zesde meting (dekking mét Project) → `SCHRIJF c` → GO → `SCHRIJF d`.

## Aandachtspunten
- CLAUDE.md-omvang nu 50.514 tekens (< 90k); nieuwe besluiten gaan naar `docs/regels/<domein>.md` (capture-at-acceptance), hooguit één regel in CLAUDE.md.
- Cloud Logging laat regels vallen bij grote job-rapporten (bekend); de vijfde-meting-uitkomst is uit het GitHub-run-log gelezen (compleet: 2.177 regels).
- De kolom "RJ-220-tegenzijde → rol" (0/164) is een open leesbaarheidspunt voor de zesde meting.

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/accordering-native-app.md` (264 regels)
- `docs/regels/auth-toegang.md` (160 regels)
- `docs/regels/vgg-odoo-migratie.md` (50 regels)
- `docs/regels/administraties-instellingen.md` (114 regels)
- `docs/regels/kantoor-frontend.md` (106 regels)

## Testbeeld — uitkomst brede runs
- **Backend** `tests/unit tests/migratie tests/berichten tests/auth tests/appupdate tests/lezen tests/rlz` (achtergrond, 5:27): 1015 passed, 3 failed, 8 errors. De 8 errors + `test_uitnodiging_statusmachine` waren fantoomfouten van een parallelle pytest-aanroep van mijzelf op dezelfde `boekhouding_test` ("relation platform.gebruiker does not exist" — de guard-run van de rapporten reset de test-DB; bekende les: nooit twee pytest-runs tegelijk); sequentiële herhaling van die bestanden: **65 passed**. De twee echte roden: `test_proxy_prefixes_dump` (proxy-prefixes.json liep op HEAD al achter op `ota.ts` van 16-09 → geregenereerd) en `test_replay::test_documentvorm_geeft_kop_en_regels…` (verwachtte de oude expand zonder `Project` → bijgewerkt). Ná fixes: groen.
- **Frontend** volledige vitest: 1699 passed, 1 failed → `proxyDekking.test.ts` (`/app/update-manifest` niet in proxy-prefixes.json, óók op HEAD rood) → ná regeneratie 87/87 groen; `tsc -b` groen.
- Gouden set (`tests/keten`) niet geraakt: geen wijziging onder app/intake, app/extractie, app/documenten of frontend/src/document.
