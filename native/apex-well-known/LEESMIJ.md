# Well-known-bestanden voor de WordPress-apex

De apex `administratiekantoornijenhuis.nl` is de passkey-rp_id (besluit 0022) maar draait
bewust de WordPress-site en routeert NIET naar Cloud Run (productiedomein-besluit
GCP_UITROL). iOS/Android valideren de app↔domein-koppeling tegen de apex — daarom staan
de well-known-bestanden dáár als STATISCHE bestanden op de WordPress-hosting. De backend
serveert dezelfde inhoud op het app-subdomein (`app/auth/wellknown.py`) — dat is alleen
referentie/vergelijkingsmateriaal, iOS kijkt er niet naar.

## iOS — `apple-app-site-association` (fase 2, signing-ronde 2026-08-17)

- **Bron in deze map:** `apple-app-site-association` (team VRQP26CX43 + bundle
  `nl.aknijenhuis.goedkeuren`).
- **Doelpad op de hosting:** `/.well-known/apple-app-site-association` — map `.well-known`
  in de webroot (naast wp-content e.d.), bestandsnaam ZONDER extensie (dus geen `.json`).
- **Eisen:** bereikbaar via HTTPS **zonder redirect** (ook geen www-redirect op dit pad),
  HTTP 200, liefst `Content-Type: application/json` (Apple accepteert in de praktijk ook
  text/plain zolang de body pure JSON is). Geen HTML-errorpagina, geen caching-plugin die
  er iets omheen wikkelt.
- **Verificatie:**
  `curl -si https://administratiekantoornijenhuis.nl/.well-known/apple-app-site-association`
  → 200, JSON-body exact `{"webcredentials":{"apps":["VRQP26CX43.nl.aknijenhuis.goedkeuren"]}}`.
  NB Apple's CDN cachet dit bestand tot ~een dag na de eerste app-installatie; het bestand
  moet er dus stáán vóór de eerste device-install (of: app verwijderen + opnieuw
  installeren dwingt een verse fetch af).

## Android — `assetlinks.json` (Play App Signing live, 30-08)

- **Bron in deze map:** `assetlinks.json` — GEGENEREERD, nooit met de hand bewerken:
  ```bash
  cd backend && .venv/bin/python -m app.auth.android_signing \
    "<SHA256-app-signing-key>" "<SHA256-upload-key>" --schrijf ../native/apex-well-known/assetlinks.json
  ```
  Dezelfde generator (`app/auth/android_signing.py`) voedt de backend-route op het
  app-subdomein én leidt de WebAuthn-origins `android:apk-key-hash:<b64url>` af; de test
  `tests/auth/test_android_signing.py` eist dat dit bestand exact gelijk is aan de uitvoer voor
  de certificaten in `deploy.yml` (`ANDROID_CERT_SHA256_VINGERAFDRUKKEN`) — drift = rode suite.
- **Twee certificaten, beide verplicht:** [0] Google's app-signing-key (élke install via Play —
  Play Console → Test and release → Setup → App signing → "App signing key certificate"),
  [1] onze upload-key (lokale bundletool-/apk-installs, `android_keystore.sh`). Package
  `nl.aknijenhuis.goedkeuren`, relaties `handle_all_urls` + `get_login_creds`.
- **Doelpad op de hosting:** `/.well-known/assetlinks.json` — zelfde `.well-known`-map als de
  AASA, bestandsnaam MÉT `.json`.
- **Eisen:** HTTPS zonder redirect, HTTP 200, `Content-Type: application/json` (Android is hier
  strenger dan Apple — `text/plain` wordt geweigerd; op Apache/nginx-hosting volgt dat uit de
  `.json`-extensie, controleer het). Geen caching-plugin/HTML eromheen.
- **Verificatie:**
  `curl -si https://administratiekantoornijenhuis.nl/.well-known/assetlinks.json` → 200 +
  `application/json`, body = dit bestand; daarna Google's checker (moet BEIDE statements geven):
  `https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://administratiekantoornijenhuis.nl&relation=delegate_permission/common.get_login_creds`
  Referentie op het app-subdomein (zelfde inhoud, ná de deploy):
  `curl -s https://app.administratiekantoornijenhuis.nl/.well-known/assetlinks.json`.
- **Stand 30-08:** bestand hier gegenereerd + deploy.yml bijgewerkt; de apex gaf op 30-08 nog
  `404 File not found` op dit pad → **uploaden naar de WordPress-hosting is klikwerk Peter**
  (PLAY_DRAAIBOEK §5 stap 1). Zonder dit bestand op de apex weigert Android de passkey-prompt in
  de Play-build, óók als de backend al klopt.
