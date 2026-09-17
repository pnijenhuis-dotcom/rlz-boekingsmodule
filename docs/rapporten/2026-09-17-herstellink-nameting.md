# Rapport 17-09 — Herstel-link app-rol: nameting ná deploy `ef48eec` (keuzescherm bij herstel, mailvolgorde, app-versie-chip, manifest https) — lees-only

Opdracht: `opdrachten/gedaan/2026-09-17-herstellink-nameting.md`. Vervolg op `2026-09-17-herstellink-app-versie-update-eerst.md` en
`2026-09-17-native-ota-nameting-3.md`. Lees-only: geen mail-writes, geen activatie, geen login-pogingen (ook geen "bogus" legacy-login —
die zou een audit-/pogingsrij schrijven).
**Werkt in productie: manifest-`https` JA; fix-code (keuzescherm bij herstel, app-versie-chip) staat aantoonbaar in de geserveerde
frontend én in de OTA-bundel JA; 426-poort + App Store-link JA; klikpunten (a) keuzescherm-gedrag in een mobiele browser, (b) app 1.1
→ toegangscode → ingelogd, (c) herstelmail-tekst, chip "app 1.1" bij Romy, OTA-toestel `bundel <sha7>`: NIET GEMETEN — geen verse
herstel-link verstuurd sinds de deploy (request-log leeg), geen kantoor-login en geen 1.2-schil vanuit CC.**

## Stap 0 — voldaan
- Deploy-run 35239577138 (`ef48eec`, 15:20Z) GROEN; stap 10 letterlijk: "OTA-bundel ef48eec-20260917-1524 (runtime 1.2, 1479192 bytes,
  sha 7e1eb1583aab) geregistreerd" (15:25:01Z). `ef48eec` bevat `f20f377` (herstel-link-fix) en `5093010` (manifest-https).
- Service `rlz-backend` = image `backend:ef48eecc…`; álle 15 Cloud Run-jobs (herinneringen, bank-sync, bewaking, eerste-sync,
  extractie-wachtrij, intake-imap, kantoor-digest, migratie, nieuwe-facturen, projecten-cijfers, reconciliatie, smoketest, sync,
  terugkerend-herbereken, webhook-afleveraar) = dezelfde image → service = jobs.

## Stap 1 — meting (17-09 ~15:26–15:35Z)

| Meting | Uitkomst |
|---|---|
| `GET /app/update-manifest?runtime=1.2&platform=ios` | 200, `url` = **`https://app.administratiekantoornijenhuis.nl/app/bundels/ef48eec-20260917-1524.zip`** (was `http://` in nameting 3) — **JA** |
| idem `platform=android` | dezelfde bundel_id/sha/https-url |
| `runtime=1.1` en `runtime=1.0` | `{"geen_update":true,"reden":"geen bundel voor deze runtime"}` — nooit een bundel van een andere runtime, conform regel |
| `GET /app/bundels/ef48eec-20260917-1524.zip` | 200, 1.479.192 bytes, sha256 `7e1eb158…095e22` = manifest-sha; zip bevat `index.html`, `assets/`, `accordeur-sw.js`, `accordeur.webmanifest` |
| Fix-teksten in de **geserveerde kantoor-/accordeur-frontend** (index → 20 lazy chunks gedownload, grep) | "Toestel opnieuw koppelen", "In de app op deze telefoon", "verder in de browser", "deze herstel-link koppelt het toestel" in `AccordeurApp-C79wLmss.js`; "app-versie onbekend (≤ 1.0?)" in `KantoorApp-DlgPJZ-z.js` — de fix van `f20f377` staat live |
| Fix-teksten in de **OTA-bundel** (uitgepakt) | "Toestel opnieuw koppelen" + herstel-tekst in `assets/AccordeurApp-CXbqwxm7.js` — een 1.2-schil krijgt via OTA dezelfde fix |
| `GET /auth/webauthn/config` (publiek) | `store_link_ios` = `https://apps.apple.com/app/nijenhuis-boekingsmodule/id6803862748`, `store_link_android` = null → herstelmail-stap 1 en `legacy_login_app_hint()` dragen de App Store-link (code op de gedeployde image; mailtekst zelf niet gemeten) |
| 426-probe (`X-Native-Client: 1`, `X-App-Versie: 0.9`, `X-App-Platform: ios` op `/accordering/wachtrij`) | **426** `{"code":"app_update_nodig","min_versie":"1.1","huidige_versie":"0.9","store_url":"https://apps.apple.com/…id6803862748"}` |
| Request-log `POST /auth/app/activeren` sinds 10:00Z | precies de vijf hits van de casus Romy (10:35:20Z 200 CriOS, 10:47:04Z 200 CriOS, 11:03:00Z 409 native, 11:06:04Z 200 native + OPTIONS); **niets ná de deploy van 15:25Z** → klikpunt (a)/(b) niet gebeurd |
| Herstel-link-mails sinds 15:20Z | geen `…/herstel-link`-request in het log → geen verse herstelmail, (c) niet meetbaar |

**Niet gemeten (klikpunten Peter, één keer):**
1. Verse herstel-link naar het review-/testaccount → in een mobiele BROWSER: eerst het keuzescherm "Toestel opnieuw koppelen" mét
   "In de app op deze telefoon" / "Ik heb de app niet — verder in de browser"; request-log mag vóór de knop geen `POST /auth/app/activeren`
   tonen. Meetrecept ná het klikpunt:
   `gcloud logging read 'resource.type="cloud_run_revision" AND httpRequest.requestUrl:"/auth/app/activeren" AND timestamp>="<klikmoment>"'`.
2. Dezelfde link in de app 1.1 → activeren → toegangscode → ingelogd (verwacht één `POST /auth/app/activeren` 200 vanuit `Mobile/15E148`
   zonder `CriOS`/`Safari`).
3. De herstelmail toont "1. Download eerst de app … versie 1.1 of hoger nodig", "2. Open déze link …", "3. … nieuwe toegangscode" mét
   App Store-link (tekst uit `uitnodigingsmail.app_activatie_stappen(herstel=True)`; unit-tests groen, live mail alleen door Peter te lezen).
4. Gebruikers & toegang: bij Romy's toestel de detailregel "app 1.1" (het toestel van 11:06Z is gekoppeld door app 1.1 ná `X-App-Versie`-
   registratie 0152 → verwacht "app 1.1"); een 1.0-toestel toont "app-versie onbekend (≤ 1.0?)". Vereist een kantoor-login; niet vanuit CC.
5. OTA-toestel (1.2-schil, Xcode Cloud ≥ 145): Toegang › Diagnose `bundel 7e1eb15` ná één herstart. Geen 1.2-schil vanuit CC; Xcode Cloud
   niet meetbaar (zie de Apple-sectie van 17-09).

## Keuzes in deze run
- Geen "bogus" legacy-login tegen productie om de 401-hint te zien: dat is een schrijvende poging (audit/pogingsrij) en de opdracht is lees-only;
  de store-link is via de publieke config-route bewezen, de hinttekst via de unit-test op de gedeployde commit.
- De frontend-fix is bewezen door de geserveerde chunks én de OTA-zip te grep'en op de exacte UI-teksten — dat bewijst dat de code live is,
  niet het gedrag op een toestel; dat blijft het klikpunt.

## Stap 2 — afronding
BESLISSINGEN "HERSTEL-LINK APP-ROL — LANDT OP WEB (SPOED 17-09 …)" alinea "Nameting 17-09 avond" + "NATIVE APP — LIVE UPDATES (OTA) …"
alinea "Nameting 17-09 (4)"; dit rapport + INDEX; opdracht → gedaan. Geen vervolg-opdracht in de inbox: de rest is klikwerk Peter mét het
meetrecept hierboven; wordt het klikpunt gedaan, dan volstaat één lees-only log-check.

## Gelezen regels
- `docs/regels/auth-toegang.md` (160 regels)
- `docs/regels/accordering-native-app.md` (264 regels)
