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

## Android — `assetlinks.json` (volgt in de Android-ronde)

Zelfde map, pad `/.well-known/assetlinks.json` — kan pas als de upload-keystore bestaat
(sha256-vingerafdruk van de signing-key). Zie verkenning/17 kliktest-blok punt 5.
