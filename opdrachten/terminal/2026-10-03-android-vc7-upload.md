# Terminal/klik 03-10 — Android 1.3 (vc7) uploaden naar Play (Productie-release, zoals 30-09)

Niets hiervan voert Claude Code uit: de AAB is al gebouwd (run D 02-10 blok F); de upload doet Peter in de Play Console
(bestand > 10 MB, store-upload is klikwerk). Repo-root: /Users/mr.x/Claude/Projects/Rlz boekings module

## Wat er klaarstaat (gebouwd 02-10 20:59, worktree run D, commit = de blok-F-commit van run D)
```
native/android/app/release/nijenhuis-goedkeuren-1.3-vc7-20261002-2059.aab                      (17 MB)
native/android/app/release/nijenhuis-goedkeuren-1.3-vc7-20261002-2059-native-debug-symbols.zip (10 kB)
native/android/app/release/nijenhuis-goedkeuren-1.3-vc7-20261002-2059-mapping.txt              (losse kopie; zit óók in de AAB)
```
SHA-256 van de .aab: `3bb5afc31f91adce9f0d8b79ab4180a322818b056f0d18390cfb375640742582`.
Gevalideerd door het bouwscript: signatuur = upload-key (`4A:B4:3C:…:8F:A1`), bundletool validate ✓, package
`nl.aknijenhuis.goedkeuren` · versionCode 7 · versionName 1.3 ✓, `capacitor.plugins.json` noemt `CapacitorUpdater` + `AppUpdate`,
manifest `allowBackup="false"` + `dataExtractionRules` + `fullBackupContent` ✓ (bundletool dump manifest).

## Stap 0 — controle vóór je uploadt (optioneel, 1 min)
```
shasum -a 256 "/Users/mr.x/Claude/Projects/Rlz boekings module/native/android/app/release/nijenhuis-goedkeuren-1.3-vc7-20261002-2059.aab"
```
Verwacht: `3bb5afc3…742582`. Anders: niet uploaden, melden aan Cowork.

## Stap 1 — Play Console: Productie-release (zoals 30-09 met vc6)
1. https://play.google.com/console → PDL Powerhouse → **Nijenhuis Boekingsmodule** → Test and release → **Production** →
   **Create new release**.
2. App bundles: sleep de `.aab` erin → Play toont versionCode 7, "Signed by Google Play".
3. Release name: `1.3 (7)`. Release notes (nl-NL):
   ```
   De app herstelt zijn eigen beveiligde opslag. Lukt het activeren niet omdat de opslag op het toestel onleesbaar is geworden (bijvoorbeeld na een back-up of overdracht), dan biedt de app nu "App-opslag opnieuw instellen" aan; daarna kies je opnieuw je toegangscode. Ook maakt de app geen back-up meer van zijn beveiligde opslag, zodat dit niet meer kan gebeuren.
   ```
4. **Next → Save → Review release → Start rollout to Production** (volledige uitrol, zoals 30-09; wil je gefaseerd: 20 % en
   na een dag 100 %).
5. Ná de upload: **App bundle explorer → versie 7 → Downloads → Native debug symbols** → upload de
   `-native-debug-symbols.zip`. De mapping zit al ín de AAB.

## Stap 2 — controle ná publicatie (Google-review 1–7 dagen; daarna)
- Play Console → Production → release `1.3 (7)` = "Live"/"Volledig uitgerold".
- Op het toestel van de foto (IMG_2512): app updaten via Play → openen → als het activeren opnieuw strandt op de opslag, toont
  de app nu **"App-opslag opnieuw instellen"** → tik de knop → activatie mét een verse uitnodiging/koppelcode van het kantoor
  (de kluis is daarna leeg; het oude toestel-token staat nog in Gebruikers & toegang en mag ingetrokken worden).
- Meetlat (Cowork/CC, lees-only): request-log `POST /auth/app/activeren` + `POST /auth/app/toestel-koppeling` ná de
  publicatie vanaf Android-user-agents mét `X-App-Versie: 1.3`; lokale audit op het toestel: ⚙ Toegang › Diagnose toont
  `app 1.3 (7)` en de audit-regel `app_opslag_hersteld` als de knop gebruikt is.
- Pas ná een publieke 1.3-listing: `STORE_APP_VERSIE_ANDROID` (deploy.yml) — en `APP_MIN_RUNTIME_VERSIE` blijft 1.1 tot
  Peter anders beslist (TESTFLIGHT §6: nooit vóór de winkelversie live is).

## iOS 1.3
Xcode Cloud bouwt ná de push van run D automatisch de eerste 1.3-build (MARKETING_VERSION 1.3 op beide pbxproj-plekken;
`herstel` zit óók in de iOS-plugin). Indienen in App Store Connect pas als Peter dat wil: + Versie 1.3 → build koppelen →
"What's New" = de releasenotes hierboven → Indienen. Niets hiervan is in run D gedaan.
