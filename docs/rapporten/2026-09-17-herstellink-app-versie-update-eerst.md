# Rapport 17-09 — Herstel-link/uitnodiging: "update eerst de app" afdwingen (casus Romy) — blok A diagnose op data, blok B fix

Opdracht: `opdrachten/gedaan/2026-09-17-herstellink-app-versie-update-eerst.md`. Geen migratie. Bronnen: Cloud Logging request-log `rlz-backend` (lees-only, `gcloud logging read`), Cloud Run-revisies, AASA/assetlinks via curl, code.
**Werkt in productie: niet gemeten** (fix meetbaar ná deploy — vervolg `opdrachten/inbox/2026-09-17-herstellink-nameting.md`). **Wat Peter voor Romy moet doen: niets meer** — haar toestel is om 11:06:04Z gekoppeld (derde herstel-link, native app 1.1).

## Blok A — diagnose op DATA (gebruiker `1ffdbcc9-22d7-40a1-bce5-2bb83ec692a5`)

| Tijd (UTC) | Request | Status | Client | Bevinding |
|---|---|---|---|---|
| 16-09 08:06:43 | `POST /auth/gebruikers/1ffdbcc9…/herstel-link` | 200 | Peter | herstel-link 1 (token fFv4…) |
| 16-09 08:17:01 | `GET /activeren?token=fFv4…&herstel=1` | 206 | `WhatsApp/2.23.20.0` | link doorgestuurd via WhatsApp (preview) |
| 17-09 10:35:14 → 10:35:20 | `/activeren…&herstel=1` → info → **`POST /auth/app/activeren` 200** | 200 | iPhone iOS 26.6.1 **Chrome (CriOS/153)** | herstel-link in de BROWSER verzilverd: de web-PWA werd het toestel, token verbruikt |
| 17-09 10:36:47 | info | 400 | CriOS | token al gebruikt |
| 17-09 10:46:32 | `POST …/herstel-link` | 200 | Peter | herstel-link 2 (LSrm…) — revisie 00626 (zonder `STORE_APP_VERSIE_IOS`) → TestFlight-instructie, géén App Store-link |
| 17-09 10:46:51 → 10:46:53 → **10:47:04** | `/activeren…` → `/accordeur/activeren?uitnodiging=…&herstel=1` → **`POST /auth/app/activeren` 200** | 200 | CriOS | binnen 2 s door naar de web-flow (géén keuzescherm), opnieuw in de browser verzilverd |
| 17-09 10:47:08 | `/activeren…` + info | 400 | Peter (Mac Chrome) | al gebruikt |
| 17-09 11:01:32 | `/activeren…` + info | 400 | CriOS | al gebruikt |
| 17-09 11:03:00 | **`POST /auth/app/activeren`** | **409** | `iPhone OS 18_7 … Mobile/15E148` (WKWebView = **native app**) | app 1.1 probeert dezelfde link: token al door de web verbruikt |
| 17-09 11:05:33 | `POST …/herstel-link` | 200 | Peter | herstel-link 3 — revisie 00627 (`STORE_APP_VERSIE_IOS=1.1` sinds 11:02:47Z) → App Store-link |
| 17-09 11:06:04 | **`POST /auth/app/activeren` 200** | 200 | native app | toestel gekoppeld |

1. **Oorzaak (bewezen):** `AppActiveren.tsx::beginKeuze` sloeg het keuzescherm van 16-09 over voor `herstel=1` ("Native, herstel-links en een al gemaakte keuze slaan het scherm over") → in een mobiele browser verzilverde de web-flow het eenmalige token (10:35Z en 10:47Z); de native app kreeg 409.
2. **Universal/app-link:** AASA op `app.administratiekantoornijenhuis.nl` = `applinks … "/accordeur*", "/activeren*"` (apex alleen `webcredentials`); Apple-CDN `app-site-association.cdn-apple.com/a/v1/app.administratiekantoornijenhuis.nl` = dezelfde inhoud (ververst); `assetlinks.json` op de app-host mét `handle_all_urls` + beide vingerafdrukken → **geen fix nodig**. Een link die uit WhatsApp in Chrome-iOS opent volgt geen universal link (platformgedrag, niet onze config).
3. **Web-fallback-scherm:** het desktop-stop-scherm bestaat; op een TELEFOON-browser ging `activatieOpDitApparaat` altijd "doorgaan" én herstel omzeilde de keuze → geen keuzemoment. Gefixt (B1).
4. **Legacy-pad:** vóór de update draaide Romy 1.0 (legacy passkey/wachtwoord, kent de app-auth niet); ná de update 1.1 werkte de derde link direct.

## Blok B — fix
1. **Keuzescherm óók bij herstel** (`beginKeuze`: alleen native of `&web=1` slaat over); kop "Toestel opnieuw koppelen", herstel-tekst; keuze "In de app op deze telefoon" toont de **versie-eis** (≥ 1.1, update via de store). Tests `AppActiveren.test.tsx` (+2; 46 groen in het bestand).
2. **Herstelmail = dezelfde genummerde volgorde als de uitnodiging** (`app_activatie_stappen(…, herstel=True)`: 1 download/update mét store-link + versie-eis, 2 link op je telefoon — koppelt het toestel opnieuw, 3 nieuwe toegangscode; activatiecode-blok); uitnodiging draagt de versie-eis óók; de eis noemt alleen de geschikte winkel(s). Tests `test_uitnodigingsmail_vorm.py::TestHerstelmailVolgorde` (14 groen in het bestand + store_links).
3. **Legacy-401 mét store-link** (`legacy_login_app_hint()`); test in `test_toestel_koppeling.py`.
4. **Gebruikers & toegang toont per toestel de laatst geziene app-versie** (`ApparaatResponse.app_versie`/`bundel_gezien_op`; detailregel "app 1.1" of "app-versie onbekend (≤ 1.0?)"); test `GebruikersScreen.test.tsx`.
5. WAT_IS_NIEUW-blok "Herstel-link voor de app: eerst kiezen, en de app moet up-to-date zijn"; BESLISSINGEN "HERSTEL-LINK APP-ROL — LANDT OP WEB (SPOED 17-09 …)"; CLAUDE.md-regel.

## Tests
backend berichten/auth/appupdate 70 groen; frontend AppActiveren + GebruikersScreen 46 groen; `tsc -b` groen.

## Nameting (vervolg-opdracht)
Verse herstel-link naar het testaccount → mobiele browser: eerst het keuzescherm, geen `POST /auth/app/activeren` vóór de keuze; app 1.1 → toegangscode → ingelogd; mailtekst mét "versie 1.1 of hoger nodig" + App Store-link; chip "app 1.1" bij Romy's toestel.

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/auth-toegang.md` (160 regels)
- `docs/regels/accordering-native-app.md` (264 regels)
