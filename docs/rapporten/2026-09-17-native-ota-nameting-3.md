# Rapport 17-09 — Native app OTA: productienameting 3 ná de deploy van `7418cd5` (bucket bestaat; runtime 1.2) — bundel geserveerd, downloadlink was http

Opdracht: `opdrachten/gedaan/2026-09-17-native-ota-nameting-3.md`. Lees-only + de manifest-url-fix (zie het Apple-rapport van dezelfde run).
**Werkt in productie: OTA-registratie + manifest + zip-download ja; 426 ja; downloadlink-schema NEE (http → gefixt, meetbaar ná deploy); toestel niet gemeten.**

## Stap 0 — voldaan
- `gh run list --workflow=deploy.yml --limit 1`: run 35213422172 (`7418cd5`, 11:00Z) GROEN incl. stap 10, log letterlijk "OTA-bundel 7418cd5-20260917-1104 (runtime 1.2, 1478710 bytes, sha fb276f511c90) geregistreerd".
- Klikpunt objectViewer voor `run-backend@`: `GET /app/bundels/7418cd5-20260917-1104.zip` = **200**, 1.478.710 bytes (Peter, owner-sessie 17-09 ~13:50).

## Stap 1 — meting
| Meting | Uitkomst |
|---|---|
| `gh workflow run nameting -f onderdeel=app-bundels` (run 35233576305, 14:26Z) | meting gedraaid; **bot-commit rood** op de pathspec-bug (`verkenning/lezen-*.txt`) → geen `verkenning/nameting-app-bundels-17-09.txt` op main; bug gefixt in deze run (nullglob) |
| `GET /app/update-manifest?runtime=1.2&platform=ios` | `{"geen_update":false,"bundel_id":"7418cd5-20260917-1104","sha256":"fb276f511c906df756434a2b81f2c804db9e26306fa57b8213987998635c8c5f","bytes":1478710,"verplicht":false,"runtime":"1.2"}` |
| idem `platform=android` | dezelfde bundel_id/sha |
| `url` in het manifest | **`http://…`** — proxy-hop; iOS (ATS) weigert → de schil zou de bundel nooit laden. Fix `publieke_basis_url` (X-Forwarded-Proto) |
| 426-probe (schil 0.9) | HTTP 426 mét `min_versie 1.1` + `store_url` |
| Toestel (1.2-schil, Toegang › Diagnose `bundel <sha7>`) | **niet gemeten** — geen 1.2-schil beschikbaar vanuit CC (Xcode Cloud ≥ 145 / Android vc6 = klikpunt Peter) |

## Stap 2 — afronding
BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA) …" alinea "Nameting 17-09 (3)"; vervolg = `opdrachten/inbox/2026-09-17-herstellink-nameting.md` (manifest-`https` + toestelstap).

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/accordering-native-app.md` (264 regels)
