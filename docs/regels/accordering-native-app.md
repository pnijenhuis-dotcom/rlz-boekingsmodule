# Regels — Klant-accordering, accordeur-/veldwerker-app, native store-apps en OTA

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Sequentiële lagen mét drempels (administratie-, afdelings- en leveranciersroute), herberekening bij configuratiewijziging, staande goedkeuring alleen bij een periodiek patroon, wachtrij set-based, PWA + iOS/Android-schil, OTA self-hosted per runtime, 426-poort, store-draaiboeken.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Wachtrij accordeur-app doorbelasting in bulk (blok 1):** `verdeling_per_doelentiteit_bulk`, statement-aantal constant per administratie — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 1".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Klant-accordeurs: scope vanuit de accordeur (blok 5):** "Administraties toevoegen…" over `POST /accordering/bulk-instellen`, verwijderen mét vervallen-rondes- en laatste-laag-waarschuwing (`aanleiding` in audit + tijdlijn), gearchiveerde administraties als naam mét status — zie BESLISSINGEN "KLANT-ACCORDEURS — SCOPE VANUIT DE ACCORDEUR".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Activatieflow: mislukte eerste opslag van de toegangscode eerlijk gemeld (bugfix 10-09 (2), blok F bundel 10-09):** `stelCodeIn` → false = fase `slot_fout` (melding + diagnoseregel + "Opnieuw proberen" op hetzelfde activatieresultaat — `POST /auth/app/activeren` is éénmalig, nooit een tweede server-activatie), geen `naGeactiveerd`/wachtrij; zelfde patroon op het legacy-pad in `AccordeurApp`; `stelCodeIn` laat bij false het anker uit het geheugen en een plain token plain — zie BESLISSINGEN "BUGFIX 10-09 (2) — ACTIVATIEFLOW: MISLUKTE OPSLAG TOEGANGSCODE EERLIJK GEMELD".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Accordeur-app koude start + niet-geactiveerd account** (`accordeur/standCache.ts`, `voorlader.ts`,
  `koudeStart.ts`; E1-wortel `@capacitor/app`) — zie BESLISSINGEN "KOUDE START ACCORDEUR-APP" + "NATIVE APP — EERSTE
  LOGIN OP EEN NIET-GEACTIVEERD ACCOUNT".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Accordeur-app vervolgrun 07-09 (blok 12+13):** diagnoseregel "Laatste koude start" in Toegang-instellingen (lokaal, nooit naar de server), geen boot-refresh-POST in native zonder leesbaar refresh-token, eerlijke Play-melding bij ontbrekende passkey-beheerder (variant B, geen 0020-impact), build 45 klaargezet (iOS via Xcode Cloud bij push, Android-AAB versionCode 3); Cloud Run min-instances staat al op 1 — zie BESLISSINGEN "ACCORDEUR-APP — DIAGNOSEREGEL".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Accordeur-app — inzoomen op de factuur (Peter 15-09; geen migratie, geen backend):** eigen zoomlaag in `PdfWeergave` (pure gebaar-wiskunde `pdfZoom.ts`: knijp 1×–4× mét focuspunt, dubbeltik 2×, pannen binnen het vak, `touch-action: none` zodra ingezoomd zodat de rest van het scherm niet meescrolt; scherp door hertekenen op de hoogst gebruikte zoomstap, alleen zichtbare pagina's ±1) + knop "⤢ Volledig scherm" (vaste overlay, ✕/Escape/terug-gebaar); één component voor factuur én werkbonnen/offertes; toesteltest iOS/Android open — zie BESLISSINGEN "ACCORDEUR-APP — INZOOMEN OP DE FACTUUR (Peter 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Native app — live updates (OTA) + minimum-versie-poort + Android in-app-update (Peter 16-09 "zsm af van TestFlight"; migratie 0152):** `@capgo/capacitor-updater` SELF-HOSTED (geen Capgo-cloud) + `@capawesome/capacitor-app-update`; deploy bouwt de frontend `--mode native`, zipt, upload naar bucket `rlz-boekhouding-app-bundels` en registreert per RUNTIME (= `APP_MARKETING_VERSIE`) via `app-bundel-registreren`; manifest `GET /app/update-manifest` geeft nooit een bundel van een andere runtime, kill-switch env `OTA_UITGESCHAKELD` + Beheerder-blok "App-updates" (cohort-%, noodrem, bundels, toestellen), toepassen bij de VOLGENDE start (verplicht = direct), rollback = audit `ota_rollback`; schil < `APP_MIN_RUNTIME_VERSIE` (aangekondigd via `X-App-Versie`) = 426 → scherm "Update nodig" mét winkelknop/Google in-app-update; native-dep = winkelrelease + marketingversie ophogen; eerste écht effect vereist een winkelrelease mét de plugins + bucket (klikpunten) — zie BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA), MINIMUM-VERSIE-POORT, IN-APP-UPDATE (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Accordeur-app diagnose 08-09 (blok 2 bundel 08-09):** iOS-melding bij mislukte passkey-registratie eerlijk (`passkeyFouten.ts::isIosPasskeyMislukt`), `BackendOnbereikbaarError.oorzaak` (timeout/netwerk/server) op het slot + laatste verbindingsfout lokaal in de diagnoseregel, uitnodigingslink-in-Safari-analyse in TESTFLIGHT §0c — zie BESLISSINGEN "DIAGNOSE-RUN 08-09 — BLOK 2".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Wachtrij accordeur-app set-based + uploads van de event-loop + lees-timeout 30 s + élke AI-extractie op de achtergrond (blok 1 spoedrun 08-09, 1c verbreed):** `wachtrij_voor_accordeur` constant aantal queries per administratie (`WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE`, gedeelde aan-de-beurt-bron `_open_rondes_met_volgende_stap`); `async def`-uploadroutes draaien blokkerend werk via `run_in_threadpool`; élke upload die AI-extractie krijgt gaat via `extractie_wachtrij` (201 < 2 s, worker = Cloud Run-job `rlz-extractie-wachtrij`; seam `ai_extractie_in_request`); app toont bij een trage/mislukte verversing nooit een kale fout zolang er een stand staat — zie BESLISSINGEN "WACHTRIJ ACCORDEUR-APP 10 S — SET-BASED HERBOUW, UPLOADS VAN DE EVENT-LOOP, LEES-TIMEOUT 30 S".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Afdelingen binnen een administratie** (`afdelingen_ingeschakeld`, harde check "Afdeling", accorderingsroute per
  afdeling; migratie 0084) — zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok A, mockup `afdelingen.html`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). Klant-app = PWA + store-apps (iOS TestFlight LIVE
  23-08, interne Play-testrelease LIVE 30-08; bundle-id `nl.aknijenhuis.goedkeuren`). **HARD PRINCIPE: maillinks
  zijn deep-links naar de PWA (`/accordeur?document=<id>`) — goedkeuren-zonder-inloggen/one-click-token bestaat bewust
  NIET.** Configuratiewijziging HERBEREKENT lopende rondes (blok 2 bundel 09-09, besluit Peter 08-09 — herziet 01-09 "vervallen": gegeven akkoorden blijven als de accordeur in dezelfde/eerdere laag staat en de drempel niet strenger werd, ontbrekende lagen worden aangevraagd, vervallen alleen als geen enkel akkoord meer past; `app/accordering/herberekening.py`, audit `accordering_ronde_herberekend`, gouden-set-casus p — zie BESLISSINGEN "ACCORDERINGSRONDE HERBEREKENEN I.P.V. VERVALLEN"); ná het laatste akkoord BLIJFT het document op
  ter_accordering tot de boeking staat (`boek_fout`); compleet klant-akkoord kan NIET opnieuw ter accordering. Zie
  BESLISSINGEN "Klant-accorderingsflow — GEBOUWD + GETEST", "Accordeur-PWA + auth-cadans — GEBOUWD", "GECOMBINEERDE RUN
  26-08" blok B, "VERZAMELRUN 27-08", "WERKSTROOM- + UI-RUN 27/28-08", "BUGFIX-RUN 28-08", "OPRUIMRUN 28-08",
  "GECOMBINEERDE RUN 01-09" blok A, "NATIVE-APP FASE 1–5", "NATIVE KLIKTEST RONDE 1/2", "XCODE CLOUD",
  "ANDROID-BOUWRONDE 28-08", "PLAY-NAZORG 30-08", "STORE-LINK-NAZORG", "ACCORDEUR-NOTIFICATIES",
  "NIEUWE-FACTUREN-BUNDELMELDING", "APPLE REVIEW 2.1"; `verkenning/17_NATIVE_STORE_APP_ACCORDEUR.md`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Klant-accordering — laag per leverancier (Peter 17-09 "1 losse accordeur die alleen de aangevinkte leveranciers ziet"; migratie 0156):** leveranciersroute VERVANGT de administratieroute voor de aangevinkte leveranciers (afdelingsroute > leveranciersroute > administratieroute), meerdere lagen mét drempel per route, matching op crediteur-identiteit (voorkeur-records), één route per leverancier (409), herberekening bij aan-/afvinken/deactiveren, wachtrij scherp via de stappen; Beheerder-blok "Leveranciersroutes" in de Klant-accordering-kaart, routes `…/accordering/leverancier-routes` — zie BESLISSINGEN "KLANT-ACCORDERING — LAAG PER LEVERANCIER (Peter 17-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Google Play-afwijzing 07-09 (blok PLAY):** wortel ≠ Apple — reviewers logden in en strandden op de passkey-registratie (kale emulator zonder Google-account: "No create options available"); reviewer-instructies voor beide stores in `native/PLAY_DRAAIBOEK.md` §10–11 + `TESTFLIGHT_DRAAIBOEK.md` §1 — zie BESLISSINGEN "GOOGLE PLAY AFWIJZING 07-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Apple 1.0 goedgekeurd 09-09 → versie 1.1 met app-auth (mini-run 09-09; geen migratie):** train-regel = ná élke goedkeuring de marketingversie ophogen vóór de volgende push (build 98 geweigerd ITMS-90186/90062); 1.1 op pbxproj ×2 / `versionName` (vc5) / `appVersie.ts` mét guard `test_app_marketingversie_consistent.py`; `STORE_LINK_IOS` gevuld in deploy.yml (id6803862748), Android-link leeg tot Google goedkeurt; niets ingediend — zie BESLISSINGEN "APPLE 1.0 GOEDGEKEURD 09-09 — 1.1 MET APP-AUTH VOLGT" + TESTFLIGHT_DRAAIBOEK §0f.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **OTA + Apple 1.2 nameting 17-09 middag (lees-only):** deploy `7418cd5` groen incl. stap 10 (bundel `7418cd5-20260917-1104`, runtime 1.2), zip 200 ná klikpunt objectViewer, 426 ja; **manifest-`url` was `http://` achter de proxy (iOS weigert) → `publieke_basis_url` volgt X-Forwarded-Proto**; Xcode Cloud ≥ 145 niet meetbaar vanuit CC — zie BESLISSINGEN "APPLE 1.1 GOEDGEKEURD 17-09" alinea "Nameting 17-09 middag" en "NATIVE APP — LIVE UPDATES (OTA)" alinea "Nameting 17-09 (3)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Apple 1.1 goedgekeurd 17-09 → 1.2 klaargezet, Xcode Cloud Package.resolved-guard, nameting via gh (SPOED 17-09; geen migratie):** 1.1 live (store-lookup 16-09 23:23Z) → `STORE_APP_VERSIE_IOS=1.1` service + jobs, marketingversie 1.2 (vc6), build 144 rood op verouderd Package.resolved → `xcodebuild -resolvePackageDependencies` + guard `test_ios_package_resolved_actueel.py` (plugin toevoegen = resolved committen), bucket-script mét default-SA-fallback (klikpunt: objectViewer voor `run-backend@`), `nameting.sh` `NAMETING_VIA_GH` (niet-interactief = gh workflow run) — zie BESLISSINGEN "APPLE 1.1 GOEDGEKEURD 17-09 — 1.2 VOLGT; XCODE CLOUD PACKAGE.RESOLVED-GUARD; NAMETING VIA GH".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Docs-nazorg store-draaiboeken 08-09 (blok 8 bundel 08-09):** eerstvolgende iOS-build = 89 (Xcode Cloud telt per push), resubmit via "Update Review" op de versiepagina, interne testers = ASC-teamleden, Play-veld "Andere informatie" ≤ 500 tekens, dode kolom `duplicaat_autoafvoer_ingeschakeld` = vervallen (geen drop) — zie BESLISSINGEN "FIXRUN 08-09 — BLOK 8: DOCS-NAZORG".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Staande goedkeuring: voorstel alleen bij een PERIODIEK patroon (blok 7 run 11-09 middag; casus Lusso 12 chalets = 12× de vraag; migratie 0134):** één gedeelde motor `terugkerend/service.py::classificeer_reeks` (periodiek = ≥ 3 gelijke facturen, tussenpozen ≥ 21 d, maand-/kwartaalpatroon; batch = twee gelijke facturen < 21 d óf ≥ 2 binnen 30 d zonder patroon → nooit een voorstel), de vraag één keer per leverancier+patroon (eerste in de wachtrij), "niet nu" = 90 dagen stil, "nooit voor deze leverancier" (accordeur zelf in de app, Beheerder administratiebreed in kantoor-web; tabel `staande_goedkeuring_voorstel_stil`, RLS, opheffen = actief=False), antwoord reist mee in de akkoord-call, DTO-veld `staande_regel_patroon`, lees-only CLI `staande-goedkeuring-voorstellen-lezen` in `nameting.sh`; bestaande staande goedkeuringen ongewijzigd — zie BESLISSINGEN "STAANDE GOEDKEURING — PERIODIEK VS BATCH (blok 7 run 11-09 middag)"

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Accordeur-app koude start + niet-geactiveerd account (CLAUDE.md `ed6d176` r. 690–699)

- **Accordeur-app koude start + niet-geactiveerd account (mini-run 06-09 blokken D/E — BESLISSINGEN "KOUDE START
  ACCORDEUR-APP" + "NATIVE APP — EERSTE LOGIN OP EEN NIET-GEACTIVEERD ACCOUNT"):** cache-first stand per gebruiker
  (`accordeur/standCache.ts`, localStorage `accordeur-stand:<sub>`, gewist bij uitloggen/dode sessie), regel "laatst
  ververst HH:MM", wachtrij + vragen parallel (`voorlader.ts`), besluit-knoppen pas actief op de verse stand; timing-log
  `koudeStart.ts` (`window.__koudeStart`, dev/native) + `Server-Timing`-header op de twee accordeur-leesroutes.
  E1-wortel casus 04-09: `@capacitor/app` ontbrak in `native/` — het `appUrlOpen`-event kwam nooit, de universal link
  opende de app op het login-scherm; fix = plugin + `getLaunchUrl`-vangnet (store-build versionCode 3 = klikpunt).
  Login toont ná élke mislukte poging het generieke uitlegblok "Nog niet geactiveerd?" (mail-app openen, link plakken
  door dezelfde token-poort) — bewust GEEN server-detectie per e-mail (enumeratie, 0022-lijn); kantoor stuurt een verse
  link via "Opnieuw mailen".

### Domeinbeslissingen — Afdelingen binnen een administratie (CLAUDE.md `ed6d176` r. 937–947)

- **Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup `afdelingen.html`,
  migratie 0084, casus Kempen Facilities):** toggle `afdelingen_ingeschakeld` op het
  project_verplicht-patroon — AAN = afdeling verplicht op élk inkoopdocument (harde check
  "Afdeling", óók als poort bij ter accordering vanaf klaar_om_te_boeken) + accorderingsroute per
  afdeling (`accordering_laag.afdeling_id`, vervángt de administratie-route; terugval "Algemeen"
  ontstaat automatisch en volgt de administratie-route; afdeling zonder route = expliciete fout);
  afdelingen archiveren, nooit verwijderen; keuze handmatig per document mét prefill uit het
  leverancier-geheugen (`leverancier_afdeling`, chip "vorige keuze bij …", nooit auto-toewijzing);
  staande goedkeuringen tellen alleen binnen de afdeling waar afgegeven; afdeling wijzigen ná
  aanbieden = ronde vervalt mét reden; accordeur-app = één kaart per (administratie, afdeling).
  Geen backfill. `app/afdelingen/`; BESLISSINGEN "BOUWRUN 28-08 AVOND" blok A.

### Domeinbeslissingen — Klant-autorisatie / accordeur-app / native store-apps / notificaties (CLAUDE.md `ed6d176` r. 948–1100)

- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). **Configuratiewijziging (lagen/toggle)
  laat lopende rondes expliciet VERVALLEN (werkstroom-run 27/28-08 punt 2a, casus 34 facturen):
  status `vervallen`, document terug naar klaar_om_te_boeken, tijdlijn mét reden
  "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist" + batch-id, eenmalige banner op de
  documentenlijst (`GET …/accordering/vervallen-meldingen`); herstelroute = bulk "Ter accordering
  aanbieden" op de tab Klaar om te boeken (`POST …/accordering/documenten/bulk-aanbieden`, zelfde
  poorten per document, overgeslagen mét reden — punt 2b).** **Bulk instellen (01-09, mockup
  `bulk-accordering.html` = norm): de bulk-selectie van administraties-v2 draagt
  "Klant-accordering instellen…" — één dialoog past de lagen toe op álle geselecteerde BV's
  (Beheerder-only endpoints; orkestratie over de bestaande configuratieroute, geen tweede
  schrijver): ontbrekende accordeur-scope aangemaakt mét expliciete vink (trigger-audit; zonder
  vink = BV overgeslagen mét reden), bestaande config VERVANGEN mét vooraf de telling vervallen
  rondes (bestaand vervallen-patroon), toggle aan waar uit; preview = resultaat-weergave,
  deelfout per BV zichtbaar. Zie BESLISSINGEN "GECOMBINEERDE RUN 01-09" blok A.** **Ná het laatste akkoord BLIJFT het
  document op ter_accordering tot de boeking staat (bugfix-run 28-08 — vóór de fix ging het éérst
  naar klaar_om_te_boeken en bleef het dáár stil hangen zodra de boekpoging faalde; casus Kempen
  Facilities 27-08, ±42 documenten): elke mislukking = persistente `boek_fout` op de ronde +
  tijdlijnreden + audit, controlescherm-sectie mét "Opnieuw boeken (klant-akkoord compleet)", lijst-chip
  "boeken ná akkoord mislukt"; poort telt alleen de LAATSTE ronde én het bedrag mag niet gewijzigd zijn;
  élke ⚙-systeemovergang draagt een `reden` (vangnet in `_schrijf_overgang`); herstel bestaande gevallen
  = `make accordering-herstel-boeken DRY_RUN=1` eerst, uitvoeren alleen op Peters go — BESLISSINGEN
  "BUGFIX-RUN 28-08".** **Opruimrun 28-08 (punten 24 + 23): een compleet, nog niet verzilverd
  klant-akkoord (laatste ronde afgerond, bedrag ongewijzigd, sinds die afronding niet geboekt) kan
  NIET opnieuw ter accordering — losse route 409 `KlantAkkoordAlCompleet` "boek het direct", bulk =
  overgeslagen mét reden, lijst-checkbox uit mét uitleg (`klant_akkoord_compleet`); boeken kan wél.
  Volumerem: de teller telt alleen échte overgangen niet-geboekt→geboekt; boekingen ná een compleet
  klant-akkoord (accorderingspad, herstel-CLI, meelopende doorbelasting in dezelfde gang) vallen
  onder een eigen NOODREM `max_boekingen_na_klant_akkoord_per_dag_per_administratie` = 200 i.p.v. de
  20/dag-automatiseringsrem — de mens heeft al per document op de knop gedrukt; autoboek-paden
  (opt-ins, bank, verkoop) blijven onverkort onder de 20-rem. BESLISSINGEN "OPRUIMRUN 28-08".**
  Klant-app = PWA + store-apps
  (besluit Peter 2026-08-14: de accordeur-app wordt óók uitgebracht als native App Store- én
  Google Play-app; de gebouwde PWA/webcode is de basis via een native schil, bv. Capacitor —
  PWA blijft interim + terugval; aandachtspunten native passkey-integratie (WebAuthn in een
  webview is beperkt) en store-accounts onder de juiste entiteit; planning ná GCP —
  **voorverkenning UITGEVOERD 2026-08-16: Capacitor-schil staat in `native/` (webcode niet
  geraakt), beslispuntenrapport `verkenning/17_NATIVE_STORE_APP_ACCORDEUR.md` = basis voor
  het go/no-go-bouwbesluit; GO Peter 2026-08-16 (aanbevolen route: native-passkey-plugin +
  APNs/FCM + gebundelde assets + bearer-refresh Keychain/Keystore, bundle-id
  `nl.aknijenhuis.goedkeuren`) — bouwstatus per fase: verkenning/17 "Bouwstatus" +
  BESLISSINGEN "NATIVE-APP FASE 1–5" (alle vijf 2026-08-17): fase 1 snelheidslaag PWA
  GEBOUWD+GETEST (optimistisch akkoord/afwijzen via achtergrond-verzendrij met begrensde
  retry, definitief mislukt = zichtbaar terug in de rij; prefetch/prerender eerstvolgende
  factuur; backend-idempotente besluit-herhaling `_herhaald_besluit`; dubbeltik-vangnet);
  fase 2 native passkey-plugin (eigen dunne Swift/Java-plugin, webcode-seam getest,
  well-known-routes fail-closed); fase 3 native push (migratie 0055 subscriptie-soort
  apns/fcm, adapters, kill-switch dekt web én native); fase 4 (VITE_API_BASE,
  bearer-refresh via X-Refresh-Token + Keychain/Keystore-plugins, web-contract ongewijzigd
  + bewaakt); fase 5 VOORBEREID (`native/STORE_GEREEDHEID.md`, assets uit één SVG-bron).**
  **Kliktests echt iPhone-toestel rondes 1+2 (2026-08-17) VOLLEDIG GROEN — fases 1–4
  BEWEZEN OP TOESTEL** (passkey-Face-ID, koude-herstart-Keychain-refresh, safe-area,
  meldingen-flow + APNs-push + deep-link, PWA-passkey in native, kill-switch — BESLISSINGEN
  "NATIVE KLIKTEST RONDE 1/2"); **TestFlight LIVE via Xcode Cloud (23-08, workflow main →
  TestFlight intern) mét `APNS_SANDBOX=false` afgerond — native push op productie-APNs,
  web-push/VAPID ongewijzigd (BESLISSINGEN "XCODE CLOUD")**; **Android-bouwronde 28-08
  VOORBEREID (BESLISSINGEN "ANDROID-BOUWRONDE 28-08", draaiboek `native/PLAY_DRAAIBOEK.md`):
  Firebase in HETZELFDE GCP-project (Analytics UIT), `google-services.json` gecommit,
  google-services-plugin hard, `POST_NOTIFICATIONS` + monochroom statusbalk-icoon; FCM-verzendkant
  LIVE via Application Default Credentials van run-backend@/run-jobs@ (IAM
  `roles/firebasecloudmessaging.admin`, alleen `FCM_PROJECT_ID` — géén server-key-secret;
  `scripts/gcp/fcm_afronden.sh`); Gradle-signing leest `keystore.properties` (gitignored,
  keystore buiten de repo — `native/scripts/android_keystore.sh`), release-AAB via
  `bouw_android_release.sh`. **UITGEVOERD 29-08 (besluit Peter "installs toegestaan"): JDK 21 +
  SDK via CLI (openjdk@21 keg-only → JAVA_HOME/ANDROID_HOME per shell, draaiboek §1), `assembleDebug`
  groen (Java-plugins compileren zonder fix), upload-keystore in `~/Sleutels/` (wachtwoord alleen
  dáár), release-AAB vc1/1.0 gevalideerd, drie Play-screenshots uit de emulator. Android-fixes uit
  die run: pdf.js LEGACY-build in beide viewers (hoofdbuild vereist `Uint8Array.toHex`, Chromium ≥
  140 — WebView 133 brak het factuurbeeld) + ⏻-glyph → `UitlogIcoon` (SVG). Debug-only
  cleartext-overlay `app/src/debug/` + env-vlag `NATIVE_LOKALE_BACKEND` voor lokale
  emulator-builds; release-script bewaakt dat beide NIET in de AAB zitten.** **Interne
  Play-testrelease LIVE (30-08); assetlinks + WebAuthn-origins (BESLISSINGEN "PLAY-NAZORG 30-08"):
  `ANDROID_CERT_SHA256_VINGERAFDRUKKEN` in deploy.yml draagt BEIDE certificaten (Google
  app-signing-key + upload-key) en is de ENIGE bron — `app/auth/android_signing.py` leidt daaruit
  de assetlinks-statement (route + gegenereerd statisch apex-bestand
  `native/apex-well-known/assetlinks.json`) én de `android:apk-key-hash:`-origins af
  (`toegestane_webauthn_origins`; nooit met de hand in `WEBAUTHN_ORIGINS`), settings-validator
  fail-loud, drift-test deploy↔apex-bestand; R8 in identiteitsmodus + mapping/debug-symbols als
  upload-artefact naast de AAB. Klikwerk Peter: assetlinks.json naar de WordPress-apex (30-08 nog
  404) → Google's checker → kliktest §8.** Eerder klikwerk: wachtwoordmanager → AAB naar Internal
  testing → App signing: BEIDE certificaten → screenshots.**).
  **Store-link-nazorg voorbereid (blok F 01/02-09, BESLISSINGEN "STORE-LINK-NAZORG"): settings
  `STORE_LINK_IOS`/`STORE_LINK_ANDROID` (default leeg = niets tonen); gevuld → blok "Download eerst de
  app" in de uitnodigingsmail voor app-rollen, op het desktop-stop-scherm van /activeren en op het
  web-fallback van de universal link (`auth/StoreLinks.tsx`); nazorg ná Apple/Google = alleen de
  env-vars zetten.** Factuurbeeld
  centraal, akkoord → volgende, dagelijkse push 09:00 alleen bij >0 open.
  **Bouwstatus: backend + kantoor-UI GEBOUWD + GETEST (2026-08-09)** — migratie 0033 +
  `backend/app/accordering/` + kantoor-UI (Instellingen-sectie, "Ter accordering"-knop,
  accorderingssectie controlescherm, "Bij klant"-teller); incl. staande goedkeuring (besluit
  2026-08-08: per accordeur+leverancier+exact bedrag, automatisch akkoord mét audit+tijdlijn,
  intrekbaar — harde checks blijven onverkort) en direct-boeken-blokkade zodra de toggle aan
  staat. Details BESLISSINGEN "Klant-accorderingsflow — GEBOUWD + GETEST".
  **De accordeur-PWA zelf: GEBOUWD + GETEST (2026-08-11, kliktest Peter open)** —
  `frontend/src/accordeur/` op /accordeur (eigen lazy chunk, geen kantoor-bundels; mockup
  `mockup/accordeur.html` 1-op-1; ≥16px-velden + visualViewport-sheets + dark default;
  PDF lazy via pdfjs-dist; installeerbaar zónder service worker), activeringsflow
  wachtwoord → passkey → voorwaarden/privacyverklaring-akkoord (server-side afgedwongen,
  `platform.accordeur_akkoord` + audit), apparatenbeheer/kill-switch op Instellingen.
  Zie BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD".
  **Accordeur-app-ronde 26-08 (blok B gecombineerde run, mockup `accordeur-vragen.html` = norm,
  migratie 0079 — BESLISSINGEN "GECOMBINEERDE RUN 26-08" blok B is canoniek):** compacte header
  zónder administratienamen; PDF-weergave mét laadstate/retry/tijdslimiet (oorzaak wit vlak:
  verborgen prerender op breedte 0 → `PdfWeergave.actief`); 🔔-hoekje + popup + wachtrij-kaart
  VERVALLEN (meldingskeuze alleen éénmalig in de activeringsflow, daarna telefooninstellingen);
  native `.then is not a function` gefikst (bridge-shim geeft een plain listener-handle,
  `nativePush.alsHandle`); doorbelast-blok = één regel + uitklap; **vragen-dialoog naar de
  accordeur**: vraag aan een klant-accordeur laat de documentstatus staan (ter_accordering/
  geboekt), akkoord blijft mogelijk, boeken wacht ná het laatste akkoord zichtbaar op de open
  vraag (`vraag_open` + boek_fout); accordeur ziet uitsluitend eigen threads (`GET
  /accordering/vragen`, `WachtrijItem.vraag`, antwoord-POST), afgehandeld alleen vraagsteller;
  push-anders-mail per beurt mét stille uren (`app/berichten/vraag_meldingen.py`).
  **Accordeur-app-ronde 2 (VERZAMELRUN 27-08, besluiten Peter 27-08, mockup scherm 0 "Uw
  administraties" = norm — BESLISSINGEN "VERZAMELRUN 27-08" is canoniek):** de app opent met
  één kaart per administratie MÉT werk (teller, chip "💬 vragen aan u", oudste-wacht-regel; geen
  ✓-bij-rijen; alles bij = "✓ Alles is bij" mét verversknop), klik = wachtrij per BV, één BV met
  werk = direct die wachtrij, ná akkoord de volgende van dezelfde BV, deep-links landen in de
  juiste BV (`accordeur/administraties.ts`, geen nieuw endpoint); pull-to-refresh + automatisch
  stil verversen bij terugkeer naar de voorgrond (`PullToRefresh.tsx`, `verversen.ts`);
  ontgrendeling hooguit 1× per 24 u per apparaat (zie Auth). Open beslispunt: teal Akkoord-knop.
  **Notificaties: GEBOUWD + GETEST (2026-08-15, BESLISSINGEN "ACCORDEUR-NOTIFICATIES")** —
  gedeeld SMTP-mailkanaal (`app/berichten/`, Google Workspace, fail-zichtbaar; bedient óók de
  uitnodigingsmail), dagelijkse 09:00-herinnering (job `rlz-accordeur-herinneringen`, alleen
  bij >0 open, idempotent per dag per accordeur, migratie 0050), Web Push via
  `public/accordeur-sw.js` (scope /accordeur, UITSLUITEND push — geen fetch-handler/caching,
  installatie-/updatepad ongewijzigd; subscriptie per apparaat, kill-switch trekt push mee in;
  permissie alleen vanuit expliciete klik). **Meldingen-kaart eenmalig (UX-besluit Peter
  2026-08-17, HERZIEN 26-08 blok B3): voorstel éénmalig in de activeringsflow (ná
  voorwaarden-akkoord), keuze per apparaat onthouden (óók "nee"; mislukt = eerlijke fout + één
  herkansing) — het 🔔-hoekje en de meldingen-popup zijn sinds 26-08 weg; om-/uitzetten =
  telefooninstellingen; kill-switch ongewijzigd.** **HARD PRINCIPE: maillinks zijn deep-links naar de
  PWA (`/accordeur?document=<id>`) — goedkeuren-zonder-inloggen/one-click-token bestaat bewust
  NIET** (zou de passkey-laag omzeilen). **Afzenderadres beslist (Peter 2026-08-15):
  facturen@ak-nijenhuis.nl (géén aparte gebruiker/licentie) mét Reply-To
  p.nijenhuis@kempengroep.nl — menselijke antwoorden blijven zo buiten de intake; auto-replies
  op facturen@ zijn geaccepteerde zichtbare ruis.** Live-verificatie loopt via het gebundelde
  interactieve `scripts/gcp/notificaties_afronden.sh` (slots + VAPID-generatie +
  wachtwoord-invoer + deploy + job-run + verificatie-gegate scheduler-resume in één gang;
  open TEST-accordering voor het passkeytest-account is geseed in de cloud-DB,
  `backend/scripts/cloud_seed_accordering.py`). Open: die live-verificatie (scheduler
  gepauzeerd tot dan).
  **Handmatige herinner-knop: GEBOUWD + GETEST (2026-08-16, migratie 0053)** — kantoor
  stuurt per direct een extra herinnering aan de accordeur die aan de beurt is
  (klantpagina-paneel + accorderingssectie, "laatst herinnerd" zichtbaar; max 1 per
  document per dag, audit + tijdlijn). **Nieuwe-facturen-bundelmelding: GEBOUWD + GETEST
  (2026-08-16, besluit Peter 16-08 — expliciet géén melding per factuur; migratie 0054)**:
  job `rlz-nieuwe-facturen` (~elke 10 min) bundelt nieuw klaargezet werk per accordeur tot
  één bericht ("Er staan N facturen voor u klaar", N = totaal openstaand); idempotent per
  (accordeur, document) — nooit dubbel; stille uren 20:00–08:00 Europe/Amsterdam; de
  09:00-herinnering blijft ongewijzigd en telt integraal; scheduler start gepauzeerd tot de
  notificatie-live-verificatie. Zie BESLISSINGEN "NIEUWE-FACTUREN-BUNDELMELDING" +
  GCP_UITROL §F3.6.
