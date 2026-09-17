> uitgevoerd 2026-09-17 (ochtend; bucket ontbreekt → OTA-bundel niet gemeten, 426-poort werkt in productie: ja; meting als workflow-onderdeel app-bundels klaargezet), rapport: docs/rapporten/2026-09-17-native-ota-nameting.md

# OPDRACHT 17-09 — Native app OTA: productienameting ná deploy + bucket (lees-only; géén writes buiten de meetstappen)

Vervolg op `opdrachten/gedaan/2026-09-16-native-app-live-updates-ota.md` (rapport `docs/rapporten/2026-09-16-native-ota.md`).

## Stap 0 — voorwaarden (stoppen mét melding als één ontbreekt)
- Deploy van de commits van 16-09 nacht groen; service én jobs op hetzelfde beeld. Is de deploy ROOD op de stap "OTA-webbundel …"
  (bucket ontbreekt): dat is het klikpunt `scripts/gcp/app_bundels_bucket.sh --apply` (owner) — melden, niet zelf aanmaken.
- Migratie 0152 toegepast (health/manifest antwoordt).

## Stap 1 — meting (lees-only)
- `curl "https://app.administratiekantoornijenhuis.nl/app/update-manifest?runtime=1.1&platform=ios"` → verwacht `bundel_id` = laatste
  deploy (of `geen bundel voor deze runtime` als de bucket-stap nog niet liep).
- `nameting.sh app-bundels` (lees-only; toevoegen aan de allowlist als dat nog niet is gebeurd) → geregistreerde bundels.
- Toestel: pas mogelijk mét een schil die de plugin draagt (Xcode Cloud-build ná de push / vc5) — Toegang › Diagnose → `bundel <sha7>`.

## Stap 2 — oordeel
- "werkt in productie: ja" = manifest geeft de bundel van de laatste deploy én een plugin-schil toont 'm ná één herstart; noodrem aan →
  `geen_update`. Anders "nee/niet gemeten" mét reden.

## Afronding
- BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA) …": rij klikpunten → uitkomst + "werkt in productie"; rapport + INDEX.
