> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-accordeur-uitnodiging-web-vs-app.md

# OPDRACHT 16-09 (avond) — Accordeur-uitnodiging: link op een browser verbruikt de uitnodiging, native app vraagt daarna een wachtwoord dat niet bestaat (melding Peter 16-09)

**Melding Peter (16-09):** accordeurs krijgen één mail met (a) "download de app" en (b) een link "account aanmaken". Wie (b) opent en
de activatiecode invult komt direct in de WEB-app zonder wachtwoord; wil die persoon daarna in de NATIVE app inloggen, dan vraagt die
om een wachtwoord dat er niet is.

**Diagnose Cowork (uit code + draaiboek, door CC te bevestigen):**
1. `app/auth/app_activatie.py`: activatie is éénmalig per toestel (`FOUT_AL_GEBRUIKT` 409). Een link geopend in een browser (laptop,
   of Safari op de telefoon i.p.v. de universal link naar de app) koppelt de PWA op dát apparaat en verbruikt de uitnodiging. De
   native app kan de code daarna niet meer gebruiken — en de gebruiker ziet niet dat dat de oorzaak is.
2. De wachtwoordvraag = oude auth. App-auth zonder passkey (0029) zit in versie 1.1; App Store = 1.0 (oude inlog, passkey/
   wachtwoord), 1.1 is gebouwd maar niet ingediend (TESTFLIGHT_DRAAIBOEK §0f); Android vc4 (app-auth) staat op de interne track.
   Een iPhone-accordeur uit de App Store krijgt dus altijd een onbeantwoordbare wachtwoordvraag. Indienen = klikwerk Peter, niet CC.
3. Mail: twee acties naast elkaar zonder volgorde; de link is niet gemarkeerd als "op je telefoon openen".

Pre-feature-ritueel: BESLISSINGEN "APP-AUTH ZONDER PASSKEY — TOESTELBINDING + TOEGANGSCODE (besluit Peter 08-09)", "BOUWRUN 28-08
AVOND" blok B (activatie mobiel-first + atomair), "NATIVE APP — EERSTE LOGIN OP EEN NIET-GEACTIVEERD ACCOUNT", "BUGFIX 10-09 (2) —
ACTIVATIEFLOW", "APPLE 1.0 GOEDGEKEURD 09-09 — 1.1 MET APP-AUTH VOLGT", KP7 (geen stille no-op; minimale mens), HARD PRINCIPE
"maillinks zijn deep-links, geen one-click-token". Bestanden: `app/auth/app_activatie.py`, `app/auth/router.py`, uitnodigingsmail-
sjabloon, `frontend/src/accordeur/` (activatiescherm, `koudeStart.ts`, `appVersie.ts`), `native/TESTFLIGHT_DRAAIBOEK.md`.

## Blok A — Activatielink in een browser: eerst kiezen, niet stil koppelen
- Activatiepagina detecteert de omgeving: (1) in de native schil → activeren zoals nu; (2) mobiele browser → "Open in de app"
  (universal link/app-link) mét terugval "Ik heb de app niet — ga verder in de browser"; (3) desktop-browser → "Open deze link op je
  telefoon" mét QR-code van dezelfde link + de 8-tekens activatiecode leesbaar, en een kleine tekstknop "Ik gebruik de web-versie op
  dit apparaat" (expliciete keuze, mét één regel wat dat betekent). Pas ná die keuze wordt de uitnodiging verbruikt; alleen tonen van
  de pagina verbruikt niets en telt niet als poging.
- Geen nieuwe auth-mechaniek; geen one-click; QR = dezelfde deep-link.

## Blok B — "Ook de app koppelen" vanuit een geactiveerde web-sessie (zelfservice, geen kantoor)
- In de accordeur-PWA (Toegang-instellingen): knop "Telefoon/app koppelen" → server maakt een nieuwe toestel-activatie voor DEZELFDE
  gebruiker (nieuwe code + QR, geldig 15 min, alleen vanuit een levende, recent geverifieerde sessie — toegangscode opnieuw invoeren),
  audit `toestel_koppeling_aangemaakt`. De bestaande web-koppeling blijft (géén herstelpad, dus geen intrekken van oude toestellen —
  dat pad blijft voor "Herstel-link sturen"). Maximaal N actieve toestellen per gebruiker (default 3), kill-switch per toestel blijft.
- Spiegel: in de native app "Ook op de computer gebruiken?" → zelfde mechaniek de andere kant op (QR tonen die de web-PWA koppelt).
- Fout 409 "al op een ander toestel gebruikt" in de app krijgt de actie erbij: "Log in op de web-versie en kies 'Telefoon koppelen',
  of vraag het kantoor om een nieuwe uitnodiging" (signaal zonder handeling is niet af).

## Blok C — Mail + oude-app-versie
- Uitnodigingsmail voor app-rollen: één genummerde volgorde: 1 installeer de app (store-link alleen als de store-versie ≥ 1.1 is —
  lees `STORE_LINK_IOS`/`_ANDROID` + een nieuwe env `STORE_MIN_APPAUTH_VERSIE`; anders TestFlight-/interne-track-instructie), 2 open
  déze link op je telefoon, 3 kies een toegangscode. Activatiecode als terugval eronder. Guard-test op de mailvorm.
- App 1.0 (oude auth, `appVersie` < 1.1) die tegen een account zonder wachtwoord aanloopt: server antwoordt herkenbaar
  (`account_zonder_wachtwoord` → legacy-route geeft 410-achtige tekst "Update de app naar 1.1 of gebruik de web-versie") in plaats
  van "wachtwoord onjuist". Legacy-routes blijven tot 2026-10-08.

## Blok D — Draaiboek + klikpunten Peter
- `TESTFLIGHT_DRAAIBOEK.md` §0f: checklist "1.1 indienen" bovenaan als het eerste klikpunt, mét de reden uit deze melding.
- Rapport noemt expliciet: tot 1.1 live is, is de werkbare route voor iOS-accordeurs TestFlight 1.1 óf de web-versie.

## Afronding
- Migratie alleen als blok B een kolom nodig heeft (koppeling-aanleiding op de toestel-rij); anders geen.
- Gouden set n.v.t. (auth), wél `tests/security/test_rol_endpoint_gates.py` voor de nieuwe route(s), tests op eenmaligheid
  (tonen ≠ verbruiken), N-toestellen-limiet, 15-min-verval, sessie-eis.
- WAT_IS_NIEUW; BESLISSINGEN "ACCORDEUR-UITNODIGING — WEB VS APP: KIEZEN VÓÓR KOPPELEN + ZELF EEN TWEEDE TOESTEL KOPPELEN (Peter 16-09)";
  CLAUDE.md één verwijsregel onder Auth.
- Rapport `docs/rapporten/2026-09-1x-accordeur-uitnodiging-web-vs-app.md` + INDEX; meetrecept ná deploy: open een testuitnodiging op
  de laptop → QR-pagina, uitnodiging NIET verbruikt; scan op de telefoon → app activeert; daarna in de PWA "Telefoon koppelen" → tweede
  toestel actief, beide zichtbaar in Toegang; "werkt in productie: ja/nee".
