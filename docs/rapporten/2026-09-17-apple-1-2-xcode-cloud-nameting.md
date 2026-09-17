# Rapport 17-09 (inbox-run middag/avond) — Nameting ná de SPOED-run Apple 1.1/1.2: deploy incl. stap 10 groen, manifest 1.2, App Store-link in de mail, Xcode Cloud niet meetbaar

Opdracht: `opdrachten/gedaan/2026-09-17-apple-1-2-xcode-cloud-nameting.md`. Lees-only meting + één bugfix (manifest-url) + één workflow-fix (nameting-bot-commit).
**Werkt in productie: deploy + OTA-registratie + 426 ja; App Store-link in de mail ja (revisie 00627); Xcode Cloud 1.2 niet gemeten; manifest-downloadlink NEE (http, gefixt — meetbaar ná deploy).**

## Feiten (alle lees-only, mét bron + tijd)

| Feit | Bron | Uitkomst |
|---|---|---|
| Deploy `7418cd5` | `gh run view 35213422172` (2026-09-17T11:00:33Z, 5m16s) | GROEN; stap 10 "OTA-webbundel bouwen, uploaden en registreren" groen mét log **"OTA-bundel 7418cd5-20260917-1104 (runtime 1.2, 1478710 bytes, sha fb276f511c90) geregistreerd"** (11:05:14Z); stap 11 smoketest groen |
| Klikpunt 1 objectViewer `run-backend@` | `curl -o /dev/null -w %{http_code} …/app/bundels/7418cd5-20260917-1104.zip` | **200**, 1.478.710 bytes → binding staat (Peter, owner-sessie ~13:50) |
| Manifest 1.2 ios/android | `GET /app/update-manifest?runtime=1.2&platform=…` | `bundel_id 7418cd5-20260917-1104`, sha256 `fb276f511c906df7…`, `verplicht:false`; runtime 1.1 = "geen bundel voor deze runtime" (train-regel) |
| **Manifest-`url`** | zelfde antwoord | **`http://app.administratiekantoornijenhuis.nl/app/bundels/….zip`** — `request.base_url` volgt de proxy-hop (TLS eindigt bij Cloud Run); iOS/ATS en de updater weigeren http → OTA zou stil uitblijven |
| 426-poort | `curl -H 'X-Native-Client: 1' -H 'X-App-Versie: 0.9' -H 'X-App-Platform: ios' …/accordering/wachtrij` | **426** `{"code":"app_update_nodig","min_versie":"1.1","store_url":"https://apps.apple.com/app/nijenhuis-boekingsmodule/id6803862748"}` |
| Store-versie | `itunes.apple.com/lookup?id=6803862748&country=nl` | 1.1, live sinds 2026-09-16T23:23:27Z |
| Uitnodigings-/herstelmail App Store-link | `gcloud run revisions describe rlz-backend-00627-n8q` (11:02:47Z) | `STORE_APP_VERSIE_IOS=1.1` aanwezig (00625/00626 niet) → mails ná 11:03Z tonen "iPhone/iPad (App Store)"; geen testmail verstuurd (geen mail-write vanuit CC) |
| Xcode Cloud build ≥ 145 (1.2) | — | **niet meetbaar vanuit CC**: geen App Store Connect-API-sleutel in de repo; de mail "processing completed" komt bij Peter |
| Workflow `app-bundels` | `gh run view 35233576305` | meting gedraaid, **bot-commit rood**: `fatal: pathspec 'verkenning/lezen-*.txt' did not match any files` (zie fix) |

## Gedaan
1. **Fix manifest-downloadlink**: `appupdate/router.py::publieke_basis_url` — `X-Forwarded-Proto` wint over het schema van `request.base_url`; test in `tests/appupdate/test_ota.py` (https mét header, http zonder). Meetbaar ná deploy: manifest-`url` begint met `https://`.
2. **Fix nameting-bot-commit**: `.github/workflows/nameting.yml` staget via een nullglob-array (`UITKOMSTEN=(verkenning/nameting-*.txt verkenning/lezen-*.txt)`; `git add` alleen mét treffers) — runs 35209089568 (schedule 10:10Z), 35227253545 (c) en 35233576305 (app-bundels) waren hierdoor rood ná een geslaagde meting; guard `test_nameting_workflow.py::test_commit_stap_raakt_alleen_verkenning_nameting_txt` herschreven (16 groen).
3. BESLISSINGEN "APPLE 1.1 GOEDGEKEURD 17-09 …" alinea "Nameting 17-09 middag"; CLAUDE.md-regel.

## Klikpunten Peter
1. **Xcode Cloud**: mail "processing completed" voor build ≥ 145 (1.2) = groen; rood → letterlijke fouttekst naar de inbox (bron: mail, datum).
2. Ná de deploy van deze run: `curl …/app/update-manifest?runtime=1.2&platform=ios` → `"url":"https://…"` (staat in `2026-09-17-herstellink-nameting.md`).

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/accordering-native-app.md` (264 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
