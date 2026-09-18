# Regels — Auth, rollen, scope, RLS, app-auth en gebruikersbeheer

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Kantoor: e-mailuitnodiging + wachtwoord + TOTP, passkeys eerste lijn (0020); app-rollen: toestelbinding + toegangscode zonder passkey (0029); RLS + `vereis_kantoorrol`-poorten; Gebruikers & toegang; herstel-links; mails en push.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Stack & platform -->
- **Autorisatie (hard, bevestigd 2026-07-06):** klanten-scope per medewerker via koppeltabel
  gebruiker↔administraties, afgedwongen door RLS (DB-niveau) + server-side checks — geen scope =
  geen data, ook niet via bugs in de app-laag. Rol- en scope-wijzigingen exclusief door de
  Beheerder-rol (initieel alleen Peter), server-side gecontroleerd. **Niemand kan zijn eigen rol
  of scope muteren, ook een Beheerder niet** (tweede beheerder aanwijzen kan alleen door een
  andere beheerder). Elke rol-/scope-wijziging in het append-only audit_event.
  **RLS-les scope-toetsen (bugfix 2026-08-25, BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" rij
  A-BUGFIX): een scope-lookup op `gebruiker_administratie` (zelf RLS) leest ALTIJD
  `scoped_session(<te toetsen administratie>, actor_id=actor)` — in `scoped_session(None)`
  zonder actor ziet een niet-Beheerder nul rijen en lijkt elke scope leeg (Beheerder-bypass
  verbergt dat); tests verplicht met een echte niet-Beheerder MÉT scope (groen pad), zie
  Platform `conventies.md` §RLS.**
  **Rolniveau-poorten kantoor-console (rollen-gate-fix 2026-08-21, BESLISSINGEN "ROLLEN-GATE-BUG
  WEB"):** administratie-scope is GEEN rolpoort — externe app-rollen (accordeur + veldrollen)
  hebben reguliere scope-rijen. Élk kantoor-endpoint draagt daarom `vereis_kantoorrol`
  (router-breed waar mogelijk) of `vereis_kantoor_of_accordeur` (PDF-bestand,
  accorderingsbesluiten) uit `app/auth/deps.py`; frontend-routing fail-closed via allowlists
  (`frontend/src/auth/rollen.ts`). Vangnet: `tests/security/test_rol_endpoint_gates.py` —
  rol×endpoint-matrix + fail-closed sweep over álle routes (nieuw endpoint zonder poort = rood).
  **Platformbesluit 0019 (2026-08-08): identiteit gedeeld, autorisatie per module** — elke
  module een eigen rollen-/rechtenstructuur (nooit één gedeelde enum); gebouwd als
  `platform.gebruiker_module_rol` + `platform.gebruiker_entiteit` (migratie 0034, RLS dwingt
  de mutatieregels ook op DB-niveau af); RLZ's eigen rol-enum ongewijzigd, convergentie t.z.t.
  op eigen tempo.

<!-- uit CLAUDE.md § Stack & platform -->
- Auth: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + **TOTP-2FA verplicht**, JWT-sessies.
  Rollen: Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur (scope: eigen administratie).
  **App-auth zonder passkey (besluit Peter 08-09, platformbesluit 0029 = amendement op 0020; migratie 0125): native
  accordeur-/veldwerker-app + accordeur-PWA = toestelbinding (apparaat-gebonden token, rij `webauthn_credential`
  `soort='toestel'`, kill-switch per toestel, 7-dagen sliding TTL) + 5-cijferige toegangscode (lokaal anker, nooit
  server-side); activatie via universal link óf 8-tekens activatiecode uit dezelfde uitnodigingsmail; passkey/TOTP/
  wachtwoord uit de app; legacy-app-routes `Deprecation`/`Sunset`, 410 ná 2026-10-08; kantoor-web ongewijzigd (0020)
  — zie BESLISSINGEN "APP-AUTH ZONDER PASSKEY — TOESTELBINDING + TOEGANGSCODE (besluit Peter 08-09)". Historie
  accordeur-passkeys (2026-08-11, migratie 0040), 24-uurs-cadans 27-08 en pincode-activatie 31-08: archief "Auth"
  (aanvulling 08-09).**
  **Toegangscode wijzigen zonder her-verificatie + salt/wrap als één bewezen geschreven sleutel (bugfix 10-09, ZTE) — zie
  BESLISSINGEN "BUGFIX 10-09 — TOEGANGSCODE WIJZIGEN ANDROID".** **Herstel-link app-rol landt op web (SPOED 17-09, casus Romy;
  geen migratie): wortel = het keuzescherm van 16-09 werd voor `herstel=1` overgeslagen → in een mobiele browser (Chrome-iOS uit
  WhatsApp) verzilverde de web-PWA het eenmalige token, de native app kreeg 409; fix: keuze óók bij herstel, herstelmail in
  dezelfde genummerde volgorde mét versie-eis "≥ 1.1, update via de store", legacy-401 mét store-link, chip "app 1.1"/"app-versie
  onbekend (≤ 1.0?)" per toestel in Gebruikers & toegang; AASA/assetlinks dekken `/activeren*` al — zie BESLISSINGEN "HERSTEL-LINK
  APP-ROL — LANDT OP WEB (SPOED 17-09".** **Accordeur-uitnodiging web vs app (Peter 16-09; geen
  migratie): een link in een browser laat eerst KIEZEN (app op deze telefoon / web-versie op dit apparaat) vóór er iets
  verbruikt wordt; zelfservice tweede toestel via `POST /auth/app/toestel-koppeling` (15 min, max 3 toestellen, bestaande
  toestellen blijven; ⚙ Toegang › "Telefoon/app koppelen"); uitnodigingsmail = genummerde volgorde mét store-link alleen als de
  store-versie ≥ 1.1 (anders TestFlight-instructie); legacy-login-401 mét update-hint; TESTFLIGHT §0f eerste klikpunt "1.1
  indienen" — zie BESLISSINGEN "ACCORDEUR-UITNODIGING — WEB VS APP: KIEZEN VÓÓR KOPPELEN + ZELF EEN TWEEDE TOESTEL KOPPELEN (Peter 16-09)".** Verder (volledige tekst: archief "Auth"): Wachtwoord kwijt = Beheerder-knop "Herstel-link
  sturen" (app-rollen sinds 08-09 mét activatiecode), bewust géén selfservice "wachtwoord vergeten" ("RLZ-FEEDBACKRONDE
  25-08 DEEL 2" punt 7); E-mail wijzigen zonder carrousel ("OPRUIMRUN 28-08" punt 22); activatie externe rollen
  MOBIEL-FIRST + ATOMAIR ("BOUWRUN 28-08 AVOND" blok B, géén eigen push-login; de telefoonroute mondt sinds 08-09 uit in
  de app-activatie); **Platformbesluit 0020 (2026-08-14): passkeys worden de EERSTE authenticatielijn voor álle
  rollen; wachtwoord + TOTP wordt terugval/herstel — sinds 0029 alleen nog voor de kantoor-web**; kantoor-passkeys
  GEBOUWD + GETEST 2026-08-15 ("KANTOOR-PASSKEYS").

<!-- uit CLAUDE.md § Werkwijze -->
- **Scope-dialoog: lijst in plaats van chips (nachtrun 10/11-09 blok 2; kliktest Peter 71 administraties; geen backend):** één doorzoekbare lijst mét vinkjes (`gebruikers/ScopeLijst.tsx`, ook de accordeur-variant), teller/filter/Alles-Geen (Geen mét bevestiging), gearchiveerd onderaan, alfabetisch blijft, Opslaan toont "+3 −1" — zie BESLISSINGEN "SCOPE-DIALOOG: LIJST IN PLAATS VAN CHIPS".

<!-- toegevoegd 18-09-2026, opdracht "veldwerker-rol-wijzigen" -->
- **Rol wijzigen zonder heruitnodiging — veldrollen (Peter 18-09 "Hoe kan ik de rol van Irfan veranderen van ZZP'er naar
  uitvoerder?"; geen migratie; BESLISSINGEN "ROL WIJZIGEN VELDWERKERS — ZZP'ER ↔ UITVOERDER ↔ DETACHEERDER (Peter 18-09)"):**
  Gebruikers & toegang › Veldwerkers draagt dezelfde rol-select als Kantoor, mét de opties ZZP'er / Uitvoerder / Detacheerder
  (gearchiveerd = vaste badge); de bevestigdialoog zegt wat verandert (rechten in de app) en wat blijft (toestel(len),
  toegangscode, scope, lopende weekstaten en keuringen; ZZP-dossier + crediteurkoppeling blijven bewaard maar zijn als
  niet-ZZP'er inactief; detacheerder → koppelingen detacheerder ↔ ZZP'er op Veldwerkers). Server-side (`service.wijzig_rol`):
  een wissel BINNEN een auth-model-groep (`app/auth/rollen.py::rolgroep`: kantoor / veld / accordeur) is toegestaan; een
  wissel TUSSEN groepen (kantoor ↔ veld/accordeur = wachtwoord + TOTP/passkey vs. toestelbinding + toegangscode) wordt
  geweigerd mét leesbare reden (`RolWisselNietToegestaan` → HTTP 409, geen 403: het is geen rechtenkwestie). Beheerder-only
  en "niemand muteert zijn eigen rol" blijven onverkort; audit = de bestaande DB-trigger `trg_audit_gebruiker_rol_wijziging`
  (actie `rol_wijziging`, oud→nieuw). De app heeft géén heractivatie nodig: server-side geldt de nieuwe rol per request
  (`deps.get_current_gebruiker` leest rol/status uit de DB), de app-UI volgt bij de eerstvolgende token-verversing (de
  refresh-rotatie zet `gebruiker.rol` uit de DB in het nieuwe access-token; er is geen `/auth/me` — de rol reist als
  JWT-claim). Kantoor-veldwerkersoverzicht (`/veldwerkers`) leest de rol uit de DTO en toont de nieuwe rol bij laden. Tests:
  `tests/auth/test_rol_wijzigen_veld_18_09.py` (wissel + scope + audit, tokenverversing, 5 × geweigerde groepswissel, API 204/409),
  `gebruikers/GebruikersScreen.test.tsx` (select, dialoogtekst, PATCH, 409 leesbaar).

<!-- toegevoegd 18-09-2026, opdracht "SPOED-webapp-edge-android-logt-uit" -->
- **Web-toestel (browsertab/PWA) — "logt steeds uit" (SPOED Peter 18-09, Edge op een Android-tablet; geen migratie; BESLISSINGEN
  "WEB-TOESTEL — 'LOGT STEEDS UIT' (SPOED 18-09)"):** Diagnose op data (Cloud Run-request-log + audit + refresh-keten op de
  leesreplica): het toestel werd server-side NOOIT afgewezen — élke `POST /auth/token/vernieuwen` gaf 200, geen 401/410/426;
  wat de gebruiker zag waren vijf volledige paginaherladingen van `/accordeur` in drie minuten, elk gevolgd door het
  toegangscode-scherm, omdat het ontgrendelde anker alleen in het JS-geheugen leefde (browser-terugknop uit de app,
  pull-to-refresh, tabblad-herstel). De échte uitlog om 09:27:21 was het blokkeren + archiveren van het account door het
  kantoor (workaround voor "rol wijzigen", zie de rol-wijzigen-alinea hierboven) — dat trekt álle refresh-tokens in. Regels
  sinds 18-09: (1) **ontgrendel-venster over herladen**: op een web-toestel leeft het ontgrendelde anker mét het documenteerde
  5-minutenvenster ("direct vergrendelen" uit) óók in `sessionStorage` van dát tabblad (`appSlot.herstelOntgrendeldVenster`;
  weg bij vergrendelen, sluiten van het tabblad, verlopen venster of "direct vergrendelen" aan) — het browser-equivalent van
  het procesgeheugen van de native app; (2) **Android-terugknop** verlaat de web-app niet meer: één history-entry bij binnenkomst,
  popstate → event `acc-terug` → één scherm terug in de flow (`accordeur/androidTerug.ts`, `UrenFlow.terugVan`); (3) geen
  pull-to-refresh op body-niveau (`overscroll-behavior-y: none` op html/body binnen de app-oppervlakte); (4)
  `navigator.storage.persist()` bij web-activatie, uitkomst in de diagnose; (5) **opslag gewist ≠ stil uitloggen**: slot-vlag
  zonder IndexedDB-inhoud → activatiescherm mét `OPSLAG_GEWIST_MELDING` (wat er gebeurde + koppelcode van een ander toestel of
  herstel-link); (6) diagnoseregel ⚙ Toegang draagt "modus: browsertab/PWA/app · opslag persistent ja/nee/niet gevraagd ·
  laatste tokenverlenging" (lokaal, nooit naar de server); (7) kaart "Zet deze app op je beginscherm" in een browsertab
  (Edge-/Chrome-stappen, weg te klikken); (8) app-uitnodigings-/herstelmail zegt voor Android zonder geschikte Play-versie in één
  zin hoe je de web-versie op het beginscherm zet (`uitnodigingsmail.android_web_regel`). Server-side blijft alles onverkort
  (sliding TTL 7 d, rotatie, hergebruik-detectie, kill-switch). Les werkloop: `weekstaat`/`meerwerk`/`refresh_token`-lezen op de
  replica altijd mét de juiste actor/scope; het request-log + `platform.audit_event` + `platform.refresh_token` samen geven de
  volledige tijdlijn van een toestel.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Stack & platform — Auth (TOTP, accordeur-passkeys, herstel-link, e-mail wijzigen, activatie mobiel-first, pincode/app-lock, platformbesluit 0020, kantoor-passkeys) (CLAUDE.md `ed6d176` r. 95–155)

- Auth: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + **TOTP-2FA verplicht**, JWT-sessies.
  Rollen: Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur (scope: eigen administratie).
  **Uitzondering klant-accordeur (besluit + gebouwd 2026-08-11, migratie 0040): passkey/WebAuthn
  i.p.v. TOTP** — publieke sleutel per gebruiker+apparaat (py_webauthn), volledige login alleen
  bij eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit (sliding 7-dagen-refresh-TTL),
  passkey-assertion bij app-opening — **sinds 27-08 HOOGUIT 1× per 24 uur per apparaat
  (besluit Peter, server-side venster op `webauthn_credential.laatst_gebruikt_op`, veld
  `ontgrendeling_nodig` op de stille refresh; geen migratie — BESLISSINGEN "VERZAMELRUN 27-08"
  punt 3)**, GEEN biometrie per actie; kantoor-kill-switch per
  apparaat (bijt per request + bij rotatie + bij assertion); dev-stub `auth_biometrie_dev_stub`
  voor LAN-kliktests (WebAuthn vereist https/localhost), hard onwerkzaam buiten dev. Zie
  BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD". **Wachtwoord kwijt (bv. ná een
  kill-switch): Beheerder-knop "Herstel-link sturen" (feedbackronde 25-08 deel 2 punt 7,
  migratie 0068 — `platform.uitnodiging.soort`): eenmalige 72-uurslink, zelfde token-mechaniek
  als de uitnodiging; nieuw wachtwoord → direct passkey-setup-token voor apparaat-registratie;
  status/passkeys/akkoorden blijven staan, sessies vervallen, alle oudere links ongeldig, audit
  beide kanten. Bewust géén selfservice "wachtwoord vergeten" — kantoor blijft poortwachter;
  alleen externe app-rollen.** **E-mail wijzigen zonder carrousel (opruimrun 28-08 punt 22, casus
  Haci): Beheerder-knop "E-mail wijzigen" op álle drie de /gebruikers-tabs (óók Kantoor) en óók bij
  geblokkeerd/gearchiveerd — een gearchiveerd account krijgt nooit een uitnodigingsmail (open links
  vervallen, alleen adres + audit oud→nieuw); uitnodigen op een adres van een bestaand (ook
  gearchiveerd) account = leesbare 409 i.p.v. UniqueViolation→500 (`EMailAlInGebruik`). Zie
  BESLISSINGEN "OPRUIMRUN 28-08" punt 22.**
  **Activatie externe rollen MOBIEL-FIRST + ATOMAIR (bouwrun 28-08 blok B, mockup
  `activatie-mobiel.html`, casus Haci, migratie 0083):** de wachtwoordstap parkeert de hash op de
  link (`uitnodiging.wachtwoord_hash_in_wacht`) en legt níéts vast; pas de geslaagde
  passkey-registratie maakt in dezelfde transactie wachtwoord + account definitief en verbruikt de
  link (mislukt = niets half, link blijft 72 u). `/activeren` op een desktop = stop-scherm mét QR
  van dezelfde link (capability-check + UA-vangnet, twijfel = stop); telefoon →
  `/accordeur/activeren?uitnodiging=` (3 stappen). Half-geactiveerde accounts (wachtwoord zonder
  passkey) zijn zichtbaar op /gebruikers; Herstel-link ruimt ze op. **Géén eigen push-login
  (besluit Peter 28-08)** — kantoor-web toont ná een cross-device-login éénmalig "Passkey
  toevoegen op dit apparaat?". Zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok B.
  **PINCODE-ACTIVATIE + APP-LOCK NATIVE APP (besluit Peter 31-08, ING-patroon, mockup
  `app-lock-pincode.html` = norm; herziet de 28-08-flow UITSLUITEND voor de native app — de
  PWA/web houdt wachtwoord → passkey én de 24-uurs-Ontgrendel):** mail-link (universal link
  opent de app; iOS applinks + Android App Links op het app-domein) → 5-cijferige code kiezen →
  bevestigen → Face ID-vraag + voorwaarden (passkey onder water) → klaar. De wachtwoordstap
  vervalt voor app-rollen (account houdt `wachtwoord_hash = NULL`; endpoint
  `/auth/uitnodigingen/activatie-zonder-wachtwoord` legt níéts vast — zelfde atomiciteit). De
  code is een puur LOKAAL anker (nooit server-side): PBKDF2-wrap ontgrendelt de sleutel die het
  refresh-token in Keychain/Keystore versleutelt (`frontend/src/api/appSlot.ts`); biometrie =
  gemakskopie via plugin `AppSlot` — HARDE EIS nageleefd: iOS `.biometryAny` (géén
  biometryCurrentSet), Android `setInvalidatedByBiometricEnrollment(false)` — biometrie-falen
  valt altijd stil terug op de code. Het slot vervangt in native de 24-uurs-assertion bij
  openen (sliding-refresh + kill-switch ongewijzigd); her-login = e-mail → passkey-assertion
  (`/auth/accordeur/passkey-login/*`, 0020-lijn) en reset het slot (nieuwe code). 5 foute
  codes = lokaal gewist + `POST /auth/app-lock/uitgesloten` (kill-switch eigen apparaat +
  audit) — herstel = verse kantoor-link; scherm "Toegang tot de app": Face ID-switch, code
  wijzigen, direct vergrendelen (anders 5 min), toestel ontkoppelen
  (`/auth/app-lock/ontkoppelen`). Zie BESLISSINGEN "PINCODE-ACTIVATIE + APP-LOCK".
  **Platformbesluit 0020 (2026-08-14, samen met vastgoed): passkeys worden de EERSTE
  authenticatielijn voor álle rollen; wachtwoord + TOTP wordt terugval/herstel.**
  **Kantoor-passkeys: GEBOUWD + GETEST (2026-08-15)** — tweede afnemer van de 0040-bouwstenen,
  geen nieuwe migratie: registratie ná login op Instellingen → beveiliging (élke kantoor-rol,
  meerdere apparaten, zonder platform-pin, géén nieuw token-paar), éénstaps-login e-mail →
  assertion mét UV (usernameless mag niet, 0022-lijn; geen passkey = generiek 409 → stil terug
  naar wachtwoord+TOTP, dat pad is ongewijzigd), standaard kantoor-JWT-semantiek maar wél
  apparaat-gebonden (kill-switch bijt per request); intrekken = eigenaar-of-Beheerder (niet-eigen
  = 404), laatste passkey intrekken sluit nooit buiten; kantoor-endpoints weigeren accordeurs
  (403 — hun eigen flow houdt de wachtwoordstap). Zie BESLISSINGEN "KANTOOR-PASSKEYS".

**Aanvulling 08-09-2026 — woordelijk verhuisd uit CLAUDE.md (stand commit `1c33796`, r. 79–95) bij het inkorten van de
auth-alinea voor besluit 0029 ("APP-AUTH ZONDER PASSKEY — TOESTELBINDING + TOEGANGSCODE"). Inhoudelijk HERZIEN door dat
besluit voor de native app en de accordeur-PWA (passkey-uitzondering klant-accordeur, 24-uurs-cadans, pincode-activatie
mét passkey onder water, her-login via passkey-assertion); de kantoor-passages (0020, kantoor-passkeys, herstel-link,
e-mail wijzigen) blijven geldig:**

  **Uitzondering klant-accordeur (besluit + gebouwd 2026-08-11, migratie 0040): passkey/WebAuthn
  i.p.v. TOTP** — publieke sleutel per gebruiker+apparaat (py_webauthn), volledige login alleen
  bij eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit (sliding 7-dagen-refresh-TTL),
  passkey-assertion bij app-opening — **sinds 27-08 HOOGUIT 1× per 24 uur per apparaat
  (besluit Peter, server-side venster op `webauthn_credential.laatst_gebruikt_op`, veld
  `ontgrendeling_nodig` op de stille refresh; geen migratie — BESLISSINGEN "VERZAMELRUN 27-08"
  punt 3)**, GEEN biometrie per actie; kantoor-kill-switch per
  apparaat (bijt per request + bij rotatie + bij assertion); dev-stub `auth_biometrie_dev_stub`
  voor LAN-kliktests (WebAuthn vereist https/localhost), hard onwerkzaam buiten dev. Zie
  BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD". Verder (volledige tekst: archief "Auth"): Wachtwoord
  kwijt = Beheerder-knop "Herstel-link sturen", bewust géén selfservice "wachtwoord vergeten" ("RLZ-FEEDBACKRONDE
  25-08 DEEL 2" punt 7); E-mail wijzigen zonder carrousel ("OPRUIMRUN 28-08" punt 22); activatie externe rollen
  MOBIEL-FIRST + ATOMAIR ("BOUWRUN 28-08 AVOND" blok B, géén eigen push-login); PINCODE-ACTIVATIE + APP-LOCK
  NATIVE APP (besluit Peter 31-08, herziet de 28-08-flow UITSLUITEND voor de native app — "PINCODE-ACTIVATIE +
  APP-LOCK"); **Platformbesluit 0020 (2026-08-14): passkeys worden de EERSTE authenticatielijn voor álle
  rollen; wachtwoord + TOTP wordt terugval/herstel**; kantoor-passkeys GEBOUWD + GETEST 2026-08-15
  ("KANTOOR-PASSKEYS").
