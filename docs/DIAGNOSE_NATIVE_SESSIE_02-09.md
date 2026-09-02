# Diagnose — "app-slot/sessie verdwenen ná de vc2-update" (native Android, screenshot Peter 02-09)

> **Status: DIAGNOSE mét bewijs, niets gefixt (opdracht B6b: oorzaak eerst).** Bronnen: Cloud Logging
> (Cloud Run-requestlogs `rlz-backend`, 6 dagen), cloud-DB read-only (`platform.refresh_token`,
> `platform.webauthn_credential`, `platform.audit_event`, `platform.gebruiker`), code
> (`AppSlotScherm.tsx`, `AccordeurApp.tsx`, `nativeSessie.ts`, `auth/service.py::vernieuw_token`,
> `auth/router.py::token_vernieuwen`) en de git-historie. Tijden UTC (NL = +2).

## Conclusie in één zin

**Op het toestel waarop de nieuwe build is geïnstalleerd (Xiaomi `25028RN03Y`, Android 15) heeft vóór
02-09 10:26 UTC nooit een native sessie bestaan** — er was dus geen slot en geen refresh-token dat de
update had kúnnen overleven. De 401 bij het openen was "geen refresh-token aangeleverd", niet een
door de update gewiste of door de server ingetrokken sessie. De sessie die Peter zich herinnert was
de **PWA in Samsung Browser op een ander Android-toestel** met het testaccount `haci@…` (31-08), en
die sessie is op **31-08 08:06 UTC door Peter zelf beëindigd** (account geblokkeerd → alle
refresh-tokens ingetrokken → gearchiveerd).

## Bewijs

### 1. Het Xiaomi-toestel verschijnt pas op 02-09 in de logs

Cloud Logging, User-Agent `… Android 15; 25028RN03Y … wv)` (Capacitor-webview), 6 dagen terug:
alle 50 requests vallen op **02-09**; geen enkele op 28-08 t/m 01-09. Alle webview-UA's over 6
dagen: alleen dit toestel (02-09) en `OnePlus8Pro` vanaf Google-IP's (Play pre-launch-/review-bots,
30-08 en 02-09). Een WebView-update kan de UA niet "verplaatst" hebben: er is geen ander
webview-UA in de periode.

### 2. Eerste requestreeks van het toestel (02-09, UTC)

| Tijd | Request | Status | Betekenis |
|---|---|---|---|
| 10:26:00.6 | `OPTIONS` + `POST /auth/token/vernieuwen` | **401** | stille refresh bij app-start; **geen audit-rij** (zie 3) → server-tak "Geen refresh-token aangeleverd" (of ondecodeerbaar) |
| 10:26:00.8 | `GET /auth/webauthn/config` | 200 | loginscherm laadt |
| 10:27:54 | `POST /auth/accordeur/passkey-login/opties` | **409** | geen passkey voor het ingevulde e-mailadres → stil terug naar wachtwoord |
| 10:28:14–10:28:51 | `POST /auth/accordeur/login` ×3 | **401** | wachtwoord-login mislukt (3×), telkens gevolgd door een vernieuwen-401 |
| 11:25:08 | (kantoor-web, actor Peter) `scope_toegevoegd` voor `p.nijenhuis+applereview@kempengroep.nl` op de passkey-test-seed | — | Peter richt het applereview-account in |
| 11:41:07 | `activatie_afgerond` (`zonder_wachtwoord: false`) + `passkey_geregistreerd` "Android-toestel" | — | nieuwe activatie op dit toestel |
| 11:42:04 | `passkey_assertie_ok` + `login_geslaagd`; refresh-token-keten start (3 rijen, rotatie 12:49 ✓) | 200 | vanaf hier werkt de sessie normaal, incl. rotatie |

### 3. De 401 om 10:26 kwam niet door een ingetrokken of hergebruikt token

`vernieuw_token` schrijft bij hergebruik/intrekking een audit-rij (`refresh_token_hergebruik_gedetecteerd`,
`…_binnen_grace`) en bij een ingetrokken apparaat zet het `ingetrokken_op`. **Sinds 30-08 bestaan
alleen zes hergebruik-rijen van 31-08 (account `db1be59c`, Windows-pc), niets op 02-09.** De
router geeft vóór de service-laag een 401 zonder audit als er géén cookie en géén
`X-Refresh-Token`-header meekomt (`_lees_refresh_token` → `"Geen refresh-token aangeleverd"`); de
native client zet die header alleen als `haalNatiefRefreshToken()` iets teruggeeft. Op een toestel
zonder eerdere sessie is de Keystore leeg → precies deze tak. (JWT-secret niet geroteerd: één
versie sinds 14-08; andere gebruikers roteerden op 02-09 ononderbroken door.)

### 4. Het applereview-account had vóór 02-09 nooit een sessie of passkey

`platform.refresh_token` en `platform.webauthn_credential` voor `20102192…`
(`p.nijenhuis+applereview@kempengroep.nl`): **eerste rij 02-09 11:41:07** — all-time. Er was niets
om te bewaren.

### 5. De sessie die wél verdween: haci-test in Samsung Browser, door Peter beëindigd op 31-08

- 31-08 07:35–07:49 UTC: activatie + passkey "Android-toestel" + zeven rotaties voor
  `haci@universal-steigerbouw.nl` (`eb1d3f6f`, uitvoerder) — **User-Agent `Android 10; K …
  SamsungBrowser/30.0`** (PWA in de browser, géén webview, ander toestel dan de Xiaomi).
- 31-08 08:06:21: `gebruiker_geblokkeerd` door Peter (`2f2262cd`) → `_intrek_alle_sessies`: álle
  negen refresh-tokens van dat account dragen `ingetrokken_op = 08:06:21.508`; 08:06:26 e-mail →
  `haci.test@…`; 08:06:32 `gebruiker_gearchiveerd`.
- Dat toestel/die browser heeft ná 31-08 08:06 nooit meer een vernieuwen-call gedaan.

### 6. Wat de code doet bij een échte update (ter volledigheid)

- Opslag: iOS Keychain (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, service = bundle-id),
  Android `EncryptedSharedPreferences` met Keystore-MasterKey — beide overleven een app-update op
  hetzelfde toestel; geen versie-/migratielogica in `appSlot.ts`/`nativeSessie.ts` die iets wist.
- Legacy-pad is aanwezig: een plain (niet-`slot.v1.`) refresh-token wordt gewoon meegestuurd
  (`haalNatiefRefreshToken`), en `AccordeurApp` toont bij `slotStatus === 'geen'` de code-keuze
  ("legacy-toestel van vóór 31-08").
- **Eén echte zwakte gevonden (geen oorzaak hier, wél een risico):** `AppSlotScherm.haalSessie`
  wist bij élke niet-OK refresh het slot lokaal (`wisAppSlotLokaal`) — óók bij een tijdelijke
  server-fout die geen `BackendOnbereikbaarError` wordt (bv. een 500 op `/auth/token/vernieuwen`
  tijdens een deploy). Voorstel: alleen wissen op 401 (sessie echt dood), bij 5xx het slot laten
  staan en opnieuw proberen. Apart klein fixje, buiten deze diagnose.

## Antwoord op de vraag "hoort Keychain/refresh-token een update te overleven?"

Ja, en dat is niet weerlegd: er is in de data geen enkel geval van een native sessie die door de
02-09-build verloren ging. De waargenomen "verdwenen sessie" is de combinatie van (a) een ander
toestel/andere app-vorm (PWA in Samsung Browser) en (b) een door het kantoor zelf geblokkeerd
testaccount. Een vervolgtest die het wél zou bewijzen: op de Xiaomi nu (sessie 02-09 11:42 actief,
rotatie werkt) de volgende build installeren en controleren dat de app zonder login opent — dat is
de echte "update overleeft"-test, en die kon vóór 02-09 nooit plaatsvinden.

## Bijvangst

1. **500 op `GET /administraties/2d42b0f2…/documenten/{id}/bestand`** (4×, 02-09 12:49–12:50, Xiaomi):
   de passkey-test-seed-administratie heeft documenten zonder opgeslagen bestand → de accordeur-app
   krijgt een 500 i.p.v. een nette 404 met melding. Klein fixje in de bestand-route (ontbrekend
   bestand = 404 "bestand niet aanwezig"), plus seed-nazorg.
2. **Google Play-review-bots** (`OnePlus8Pro`, IP 74.125.x/66.249.x) produceren tientallen 401's op
   `/auth/token/vernieuwen` — verwacht gedrag (geen sessie), maar vervuilt het 401-beeld; bij een
   toekomstige alert op 401-pieken deze UA's uitsluiten.
3. De 02-09-AAB (`…-versie-vcgradle-20260902-1159.aab`) is gebouwd zónder `-PversionCode`, dus met
   versionCode **2** — gelijk aan de vc2-AAB van 30-08. Play accepteert geen tweede upload met
   dezelfde versionCode; volgende build = `-PversionCode=3` (draaiboek §"elke volgende upload +1").
