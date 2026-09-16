> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-native-ota.md

# OPDRACHT 16-09 (avond) — Accordeur-/veldwerker-app: live updates (OTA) van de web-laag + minimum-versie-poort + Android in-app-update (besluit Peter 16-09: "zsm af van TestFlight, de native app moet gewoon werken")

**Besluit Peter 16-09:** updates van de native app moeten standaard vanzelf landen; TestFlight is geen distributiekanaal meer voor
gebruikers. Vastly doet dit al (Expo EAS Update, `runtimeVersion = appVersion`, les 23-08 "native-dep-check"). De RLZ-app is een
Capacitor-schil om dezelfde web-code als de PWA — het equivalent is een Capacitor live-update-plugin met een eigen update-server.

**Stand winkels (Play Console gezien 16-09):** Google Play release 2 (vc2, oude passkey-login) LIVE sinds 13-09 19:22; release 4
(vc4, app-auth) "wordt beoordeeld" sinds 13-09. Apple 1.0 live (oude login), 1.1 gebouwd, niet ingediend (klikpunt Peter, §0f).

Pre-feature-ritueel: BESLISSINGEN "NATIVE-APP FASE 1–5", "XCODE CLOUD", "ANDROID-BOUWRONDE 28-08", "APP-AUTH ZONDER PASSKEY",
"ACCORDEUR-APP — DIAGNOSEREGEL", "ACCORDEUR-UITNODIGING — WEB VS APP"; `native/`, `frontend/src/accordeur/appVersie.ts`,
`koudeStart.ts`, `.github/workflows/deploy.yml`, Vastly-repo `app/app.json` + EAS-lessen (`Platform/registers/verbeteringen.md`
23-08) als referentie voor de runtime-versie-discipline. Harde grenzen: geen secrets in de bundel; update-server = onze eigen
Cloud Run/Cloud Storage (geen derde partij op de code-levering, AVG-lijn); Apple 3.3.2: OTA alleen web-code, nooit een andere
app-functie.

## Blok A — STAP-0 (lees-only, in het rapport vóór de bouw)
- Kies de plugin: `@capgo/capacitor-updater` (open source, MIT, self-hosted mogelijk) vs `@capacitor/live-updates` (vereist Ionic
  Appflow, betaald, geen self-host). Verwachting: Capgo self-hosted. Onderbouw in twee alinea's mét versie-compatibiliteit met onze
  Capacitor-versie en iOS/Android-minima. Geen Capgo-cloud-account.
- Inventariseer wat NIET via OTA kan (native plugins, permissions, deep-link-config, app-auth-schilwijzigingen) → dat blijft de
  winkelroute; leg de regel vast: "native-dep = winkelrelease + runtime-versie ophogen" (zelfde les als Vastly 23-08).

## Blok B — Update-server + bundel-pijplijn
- Deploy-workflow bouwt ná de webbuild een OTA-bundel (zip van `dist/` voor de app-shell-target), zet 'm in Cloud Storage
  (`rlz-boekhouding-app-bundels`, versie = git-sha + `APP_MARKETING_VERSIE`) en publiceert een manifest via de service:
  `GET /app/update-manifest?runtime=<marketingversie>&platform=ios|android&huidig=<bundel-id>` → `{bundel_id, url, sha256,
  verplicht: bool}` of `{geen_update}`. Manifest kiest alleen bundels die bij de RUNTIME-versie horen (1.1-schil krijgt nooit een
  bundel die een 1.2-native nodig heeft). Signering: sha256 in het manifest + HTTPS; geen ondertekende bundels-plugin nodig in
  fase 1 (rapporteer wel de optie).
- Cohort-uitrol: manifest kent `percentage` (default 100) en een kill-switch (`OTA_UITGESCHAKELD=true` → altijd `geen_update`
  én de app valt terug op de ingebouwde bundel). Beheerder-blok "App-updates" op Instellingen › Boeken platformbreed: huidige
  bundel, percentage, kill-switch, laatste 20 toestellen mét bundel-id (uit de bestaande toestel-rij + diagnoseregel).
- App: bij koude start én bij terugkeer naar de voorgrond (max 1× per 15 min) manifest ophalen, downloaden op de achtergrond,
  toepassen bij de VOLGENDE start (nooit midden in een goedkeuring); `verplicht: true` = direct toepassen mét melding "App
  bijgewerkt". Mislukte bundel (crash bij start, geen `notifyAppReady` binnen 10 s) → automatische rollback naar de vorige bundel +
  audit `ota_rollback` via de bestaande diagnose-melding. Diagnoseregel toont `app 1.1 (99) · bundel <sha7>`.

## Blok C — Minimum-versie-poort + Android in-app-update
- Server: `APP_MIN_RUNTIME_VERSIE` (nu 1.1). Een schil < minimum krijgt op élke API-call een 426 mét `{min_versie, store_url}`; de
  app toont één scherm "Update nodig" mét winkelknop — geen kale fout, geen wachtwoordvraag (dit vervangt de legacy-410-hint uit
  de uitnodigingsopdracht als dezelfde route; niet dubbel bouwen).
- Android: `@capawesome/capacitor-app-update` (of Capgo-equivalent) → Google In-App Updates IMMEDIATE als de winkelversie <
  minimum, FLEXIBLE anders. iOS heeft geen API: winkelknop.
- Guards: test "manifest geeft nooit een bundel van een andere runtime", test kill-switch, test rollback-pad, test 426-pad;
  `test_app_marketingversie_consistent.py` uitbreiden met de OTA-runtime-koppeling.

## Blok D — Draaiboeken
- `native/TESTFLIGHT_DRAAIBOEK.md` en `PLAY_DRAAIBOEK.md`: nieuwe §"Wanneer winkel, wanneer OTA" + release-checklist; TestFlight
  alleen nog voor Peters eigen pre-check van een NATIVE wijziging, nooit voor gebruikers. GCP_UITROL: bucket + envs.

## Afronding
- Geen migratie verwacht (bundel-registratie kan in een JSON-setting; wél een migratie als de toestel-rij een `bundel_id`-kolom
  krijgt — dan de afsluitroutine).
- WAT_IS_NIEUW ("De app werkt zichzelf bij"); BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA), MINIMUM-VERSIE-POORT, IN-APP-UPDATE
  (Peter 16-09)"; CLAUDE.md één verwijsregel onder Klant-autorisatie/app.
- Rapport `docs/rapporten/2026-09-1x-native-ota.md` + INDEX; meetrecept: ná deploy op een 1.1-toestel de diagnoseregel → nieuwe
  bundel-sha binnen één herstart; kill-switch aan → `geen_update`; "werkt in productie: ja/nee". Eerste ECHTE effect vereist een
  winkelrelease mét de plugin (1.1 iOS / vc5 Android) — benoem dat expliciet als klikpunt Peter.
