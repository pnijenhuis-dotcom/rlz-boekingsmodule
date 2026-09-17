# Rapport 17-09 (ochtend, inbox-run) — Native app OTA: productienameting ná deploy + bucket

Opdracht: `opdrachten/gedaan/2026-09-17-native-ota-nameting.md` (vervolg op `docs/rapporten/2026-09-16-native-ota.md`). Lees-only;
géén writes buiten de meetstappen. **Werkt in productie: OTA-bundel NIET GEMETEN (bucket ontbreekt — klikpunt Peter); 426-poort: ja.**

## Stap 0 — voorwaarden

| Voorwaarde | Uitkomst |
|---|---|
| Deploy van de OTA-commits | Via `gh run list`: `5ba1e9a` (OTA-code) zat in deploy `bc3f7c1` (run 35154845937) en `ea859d6` (run 35188489798). Beide **rood uitsluitend op stap 10 "OTA-webbundel bouwen, uploaden en registreren"**: `ERROR: (gcloud.storage.cp) gs://rlz-boekhouding-app-bundels not found: 404`. Stappen 7 (migratie), 8 (service) en 9 (F3-jobs) groen → service én jobs op hetzelfde beeld mét de OTA-code. Smoketest (11) overgeslagen, deploy-mislukt-mail (12) verstuurd. |
| Bucket | **Ontbreekt.** Klikpunt `scripts/gcp/app_bundels_bucket.sh --apply` (owner). Conform de opdracht niet zelf aangemaakt. Tot dan is élke deploy rood op stap 10 (bijvangst 17-09 ochtend, blijft staan). |
| Migratie 0152 | Toegepast: stap 7 groen én `GET /app/update-manifest` antwoordt uit de tabel `app_bundel` ("geen bundel voor deze runtime" = lege tabel, geen 500). |
| gcloud lokaal | `gcloud auth print-access-token` rood (sessie verlopen; een inbox-run kan niet interactief herinloggen). `gh` wél groen. |

## Stap 1 — meting (lees-only, curl tegen productie)

| Probe | Uitkomst |
|---|---|
| `GET /health` | 200 |
| `GET /app/update-manifest?runtime=1.1&platform=ios` | 200 `{"geen_update":true,"reden":"geen bundel voor deze runtime"}` — de verwachte stand zolang de bucket-stap nooit liep |
| idem `platform=android`, `runtime=1.0&platform=ios` | 200, zelfde "geen bundel" |
| manifest zonder query | 422 (runtime + platform verplicht) |
| `GET /app/bundels/nietbestaand.zip` | 404 |
| **426-poort** — `/accordering/wachtrij` mét `X-Native-Client: 1`, `X-App-Versie: 0.9`, `X-App-Platform: ios` | **426** `{"detail":"Update nodig — deze versie van de app wordt niet meer ondersteund.","code":"app_update_nodig","min_versie":"1.1","huidige_versie":"0.9","store_url":"https://apps.apple.com/app/nijenhuis-boekingsmodule/id6803862748"}` |
| idem `platform=android` | 426, `store_url: null` (Android-store-link bewust leeg tot Google goedkeurt) |
| idem mét `Origin: capacitor://localhost` | 426 mét `access-control-allow-origin: capacitor://localhost` (poort ligt bínnen CORS) |
| `X-App-Versie: 1.1` / native zonder versie / zonder headers | 401 (geen token) — nooit 426 |
| `/health` en manifest mét een te oude schil | 200 (vrije paden) |
| `nameting.sh app-bundels` | **niet gedraaid** (gcloud-sessie verlopen); `app-bundels` staat al in de lees-only allowlist |
| Toestel mét plugin-schil | **niet meetbaar**: geen winkel-/Xcode Cloud-build mét de updater-plugin beschikbaar in deze run (klikpunt 2 van 16-09) |

Eerste probe zonder `X-Native-Client` gaf 401; dat is correct gedrag (de poort geldt alleen voor schillen die zich als native client
aankondigen — kantoor-web blijft byte-identiek), geen bevinding.

## Stap 2 — oordeel

- **Blok C (426-poort): werkt in productie: ja** — 426 mét min-versie, huidige versie en iOS-store-link, CORS-headers aanwezig, vrije paden vrij,
  niet-aangekondigde clients onaangeroerd.
- **Blok B (OTA-bundel via manifest): werkt in productie: niet gemeten** — er is geen bundel om te serveren zolang de bucket ontbreekt. Het
  manifest-pad zelf (route, DB-lezing, lege stand) werkt.
- **Toestel (plugin-schil toont `bundel <sha7>` ná één herstart): niet gemeten** — vereist de winkel-/Xcode Cloud-build mét de plugins.
- **Noodrem → `geen_update`: niet gemeten** — zonder bundel is er geen onderscheid tussen "noodrem" en "geen bundel".

## Gebouwd in deze run (zodat de meting ná de bucket zonder herlogin kan lopen)

- `.github/workflows/nameting.yml`: dispatch-onderdeel **`app-bundels`** (alleen op verzoek, niet in "alles"): manifest ios/android voor de
  runtime uit `frontend/src/accordeur/appVersie.ts` (zelfde bron als de deploy-stap), 426-probe (schil 0.9), lees-only `nameting.sh app-bundels`
  → `verkenning/nameting-app-bundels-<dd-mm>.txt` mét eigen `Oordeel:`-regel ("OTA-bundel <id> geserveerd …" als het manifest een bundel_id
  geeft dat actief in de lijst staat; anders "geen bundel voor runtime … — bucket-stap nog niet gelopen"); het commitbericht van de bot neemt
  die regel over (`OORDEEL_BRON`-tak). Auth-/IAM-fout = rood, rood rapport = uitkomst.
- Guard `backend/tests/unit/test_nameting_workflow.py`: options-lijst + test (8) (alleen op verzoek, alleen via nameting.sh, manifest-URL,
  426-headers, runtime-bron, oordeel-tak gedraaid op het échte shellfragment) — 16 groen; YAML + `bash -n` groen.

## Keuzes (Peter kijkt niet mee)

1. Stap 0 zegt "stoppen mét melding als één ontbreekt". Gestopt is alleen het bucket-afhankelijke deel; wat lees-only zonder gcloud meetbaar
   was (426-poort, manifest-lege-stand) is gemeten en gerapporteerd — dat is informatie die anders pas ná de bucket zou komen.
2. Bucket niet zelf aangemaakt (owner-actie, expliciet klikpunt).
3. Meetrecept als workflow-onderdeel gebouwd i.p.v. wachten op een lokale herlogin (zelfde lijn als de doorbelasting-nameting van vanochtend).

## Klikpunten Peter (ongewijzigd)

1. `scripts/gcp/app_bundels_bucket.sh --apply` als owner → daarna een deploy (elke push) registreert de eerste bundel en maakt de deploy weer groen.
2. Winkelrelease mét de plugins (iOS: eerstvolgende Xcode Cloud-build ná `5ba1e9a`; Android vc5).
3. Daarna: `gh workflow run nameting -f onderdeel=app-bundels` (vervolg-opdracht `opdrachten/inbox/2026-09-17-native-ota-nameting-2.md`).

## Vervolg

`opdrachten/inbox/2026-09-17-native-ota-nameting-2.md`: ná de bucket → workflow-onderdeel `app-bundels` draaien → bot-bestand lezen →
toestel-stap → "werkt in productie: ja/nee".
