# OPDRACHT 17-09 — Herstel-link app-rol: nameting ná deploy (keuzescherm bij herstel, mailvolgorde, app-versie-chip, manifest https)

Domeinen: auth-toegang, accordering-native-app

Vervolg op `docs/rapporten/2026-09-17-herstellink-app-versie-update-eerst.md` en `2026-09-17-native-ota-nameting-3.md`. Lees-only, geen mail-writes
zonder Peter.

## Stap 0
- Deploy van de commits van 17-09 (herstel-link-fix, manifest-`https`) groen; service = jobs.

## Stap 1 — meting
- `curl "https://app.administratiekantoornijenhuis.nl/app/update-manifest?runtime=1.2&platform=ios"` → `url` begint met `https://` (was `http://`).
- Peter (klikpunt, één keer): verse herstel-link naar het review-/testaccount → (a) open in een mobiele BROWSER: eerst het keuzescherm "Toestel opnieuw
  koppelen" mét "In de app op deze telefoon" / "verder in de browser", niets verzilverd tot de knop (request-log: geen `POST /auth/app/activeren` vóór de
  keuze); (b) open in de app 1.1: activeren → toegangscode → ingelogd; (c) de herstelmail toont "1. Download eerst de app … versie 1.1 of hoger nodig",
  "2. Open déze link …", "3. … nieuwe toegangscode" mét App Store-link.
- Gebruikers & toegang: bij Romy's toestel de detailregel "app 1.1" (X-App-Versie); een 1.0-toestel toont "app-versie onbekend (≤ 1.0?)".
- OTA-toestel (1.2-schil, Xcode Cloud ≥ 145): Toegang › Diagnose toont `bundel <sha7>` ná één herstart.

## Stap 2 — afronding
BESLISSINGEN "HERSTEL-LINK APP-ROL — LANDT OP WEB (SPOED 17-09" + OTA-sectie: "werkt in productie: ja/nee"; rapport + INDEX; opdracht → gedaan.
