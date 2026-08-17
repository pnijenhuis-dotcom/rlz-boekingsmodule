# Store-gereedheid "RLZ Goedkeuren" (fase 5)

**Status 2026-08-17:** alles tot aan de kliktest-blokken is klaar (iconen/splash uit één
SVG-bron via `scripts/genereer_assets.sh`, naamgeving, dit dossier). **De store-accounts
BESTAAN al (correctie Peter 2026-08-17): Apple Developer én Play Console onder PDL
Powerhouse zijn actief (Vastly-app draait eronder), incl. D-U-N-S — geen kritiek pad bij
derden.** Publicatie wacht alleen nog op de kliktest-blokken (verkenning/17) + de
app-registraties onder het bestaande PDL-team. Bundle-id definitief:
`nl.aknijenhuis.goedkeuren` (akkoord Peter bij het GO-besluit 16-08 — permanent, nooit meer
wijzigen; registreren onder het bestaande team).

## 1. Wat de app is (voor reviewnotities en listing)

Interne zakelijke app voor klanten van Administratiekantoor Nijenhuis: accordeurs keuren
inkoopfacturen van hun eigen administratie goed of wijzen ze af (met verplichte reden).
Alleen op uitnodiging — er is géén open registratie. Auth: e-mailuitnodiging → wachtwoord →
passkey per apparaat (Face ID/Touch ID); daarna ontgrendelt de app per opening met een
passkey-assertion.

## 2. App Store — privacy nutrition labels (in te vullen in App Store Connect)

| Categorie | Verzameld? | Gekoppeld aan identiteit | Tracking |
|---|---|---|---|
| Contact Info → Email Address | Ja (accountbasis: login/uitnodiging/mail-terugval) | Ja | Nee |
| Contact Info → Name | Ja (gebruikersnaam in het platform) | Ja | Nee |
| Financial Info → Other Financial Info | Ja (facturen van de eigen administratie worden getoond/beoordeeld; verwerking op onze servers) | Ja | Nee |
| Identifiers → User ID | Ja (platform-gebruikers-id; apparaat-gebonden sessie/push-token) | Ja | Nee |
| Usage Data / Diagnostics | Nee (geen analytics/tracking-SDK's) | — | — |

- **Tracking (ATT):** geen — geen advertenties, geen tracking over apps/sites heen, geen
  third-party-SDK's behalve Capacitor zelf. ATT-prompt niet nodig.
- **Verwerking:** EU (Google Cloud europe-west4, CMEK — platformbesluit 0021). Push via APNs
  (Apple) en, op Android, FCM (Google) — payload bevat uitsluitend een aantal + deep-link,
  nooit factuur- of financiële gegevens (dataminimalisatie, zie app/berichten/).
- **Account-verwijdering (App Store-eis bij accounts):** accounts bestaan alleen op
  uitnodiging van het kantoor; verwijdering loopt via het kantoor (AVG-proces:
  pseudonimiseren ná relatie-einde + 7 jaar bewaarplicht — koppelcontract/platformafspraak).
  In de reviewnotities benoemen + contactadres geven; raakvlak platformbesluit 0010.

## 3. Google Play — Data safety-formulier

Zelfde inhoud als §2 in Play-vorm: verzamelt e-mail, naam, gebruikers-id, financiële info
(facturen); alles versleuteld in transit (https); verwijdering via het kantoor; geen data
gedeeld met derden (FCM = verwerker voor bezorging); geen advertenties.

## 4. Reviewnotities (Apple én Play — demo-toegang)

- App vereist een uitnodiging; voor review een **demo-accordeur op de TEST-administratie**
  aanmaken (bestaand patroon: passkeytest-account + geseede TEST-accordering,
  `backend/scripts/cloud_seed_accordering.py`). Inloggegevens + korte flow-uitleg in het
  reviewnotitieveld; expliciet vermelden dat de passkey-stap ná de wachtwoordstap komt en
  dat de reviewer bij "Voorwaarden" moet accepteren.
- Uitleggen waarom pushpermissie gevraagd wordt (dagelijkse herinnering + nieuwe facturen,
  alleen bij openstaand werk) en dat goedkeuren nooit vanuit de melding zelf kan.
- Guideline 4.2 (minimal functionality): benoemen dat de app gebundelde assets, native
  passkeys, native push en deep-links gebruikt — geen remote-loading wrapper.

## 5. Checklist tot publicatie (volgorde)

1. **Peter:** ~~accounts aanmaken~~ **VERVALLEN** (bestaan al onder PDL Powerhouse, actief —
   correctie 2026-08-17). Rest: nieuwe app-registratie in App Store Connect (bundle-id
   `nl.aknijenhuis.goedkeuren` onder het bestaande team) + nieuwe app in Play Console.
2. Xcode installeren → fase 2/3/4-kliktest-blokken (verkenning/17): compile, passkeys op
   toestel, push-ontvangst, koude-herstart-ontgrendeling. Dáár horen ook:
   `apple_team_id`/AASA live, APNs .p8 + secrets, VITE_API_BASE-domein bevestigen.
3. `npm run bouw-web && npx cap sync` → archive/upload naar **TestFlight** (interne testers:
   Peter + kantoor); Android: upload-keystore aanmaken (Play App Signing aan), **interne/
   gesloten test** (de ≥ 12 testers/14 dagen-eis geldt alleen persoonlijke accounts — het
   PDL-organisatieaccount valt daarbuiten; de accordeurs blijven de testgroep) +
   `assetlinks.json` met de definitieve signing-hash + `android:apk-key-hash:`-origin in
   `webauthn_origins`.
4. Store-listing (NL): naam "RLZ Goedkeuren", ondertitel "Facturen goedkeuren —
   Administratiekantoor Nijenhuis", screenshots van wachtrij/review/lege staat (donker
   thema), privacy-URL (bestaande accordeur-privacyverklaring — zelfde tekst als het
   voorwaarden-scherm in de app, moet als publieke URL beschikbaar zijn: klein taakje).
5. Ná review-akkoord: gefaseerde uitrol; PWA blijft parallel live als terugval (besluit
   14-08) — accordeurs migreren op eigen tempo, passkeys blijven geldig (zelfde rp_id).

## 6. Versiebeleid

MARKETING_VERSION/versionName starten op 1.0; elke webcode-wijziging in de bundel vergt een
store-release (review: uren–dagen) — de PWA blijft daarom het snelste kanaal; een
live-update-dienst (Appflow e.d.) is een latere, aparte afweging (kosten/AVG).
