# Rapport 16-09 (avond) — Accordeur-uitnodiging: web vs app — kiezen vóór koppelen, zelf een tweede toestel koppelen, mail in volgorde, legacy-hint

**Melding Peter 16-09:** accordeurs krijgen één mail met "download de app" en een link "account aanmaken"; wie de link opent en de
activatiecode invult komt in de WEB-app zonder wachtwoord — in de NATIVE app vraagt de inlog daarna om een wachtwoord dat er niet is.

**Wortel in twee zinnen (bevestigd in code):** de activatie is éénmalig per toestel, dus een link die in een browser verzilverd
wordt koppelt de PWA op dát apparaat en de app kan de code daarna niet meer gebruiken — de melding zei alleen "vraag het kantoor".
De wachtwoordvraag komt uit de App Store-versie 1.0 (oude inlog); 1.1 met de app-auth zonder passkey is gebouwd maar niet ingediend
(klikwerk Peter, `native/TESTFLIGHT_DRAAIBOEK.md` §0f).

**Opdracht:** `opdrachten/gedaan/2026-09-16-accordeur-uitnodiging-web-vs-app.md`. Geen migratie (zelfservice-koppeling = bestaande
uitnodigingstabel, kenmerk `aangemaakt_door = de gebruiker zelf`).
**Werkt in productie: niet gemeten** (code vóór de deploy; meetrecept onderaan).

## Gedaan

| Blok | Wat |
|---|---|
| A — kiezen vóór koppelen | Desktop-stop-scherm van `/activeren`: QR blijft, plus tekstknop "Ik gebruik de web-versie op dit apparaat" (mét één regel wat dat betekent) → PWA-activatie mét `&web=1`. Mobiele browser: keuzescherm "In de app op deze telefoon" (instructie + Mail-app openen + store-links) / "Ik heb de app niet — verder in de browser" vóór "Welkom … Dit toestel activeren". Tonen verbruikt niets (de info-route deed dat al niet; nu getest); native/herstel/`web=1` slaan het keuzescherm over. |
| B — zelfservice tweede toestel | `POST /auth/app/toestel-koppeling` vanuit een levende toestel-sessie (app vraagt eerst de toegangscode opnieuw): link + code, 15 min, eenmalig, max 3 actieve toestellen (bij aanmaken én bij koppelen), bestaande toestellen blijven, audit zonder code. ⚙ Toegang › "Andere toestellen" → QR + code + geldigheid; native: "Ook op de computer gebruiken?". De 409 "al op een ander toestel gebruikt" verwijst nu naar dit pad. |
| C — mail + oude app | App-mail = genummerde volgorde (1 installeer — store-link alleen als de store-versie ≥ 1.1, anders TestFlight-instructie; 2 open déze link op je telefoon; 3 toegangscode) mét de code als terugval en de "per ongeluk op een computer"-regel. Legacy `/auth/accordeur/login` (app 1.0): 401 mét "Update de app naar versie 1.1 of gebruik de web-versie" — één tekst voor iedereen (geen account-enumeratie). |
| D — draaiboek | TESTFLIGHT §0f: "☐ EERSTE KLIKPUNT: 1.1 indienen" bovenaan mét reden + ná goedkeuring `STORE_APP_VERSIE_IOS=1.1` in deploy.yml. |

**Tot 1.1 live is, is de werkbare route voor iOS-accordeurs: TestFlight 1.1 óf de web-versie** (de mail zegt dat nu ook).

## Klikpunten Peter
1. App Store Connect: versie 1.1 aanmaken, build koppelen, indienen (TESTFLIGHT §0f checklist).
2. Ná goedkeuring: `STORE_APP_VERSIE_IOS=1.1` in `.github/workflows/deploy.yml` (service én jobs) + sleutel in
   `tests/unit/test_deploy_yml_envset_compleet.py`; Android idem zodra de 1.1-listing publiek is.
3. Bestaande accordeurs die nu vastzitten: laat ze de web-versie openen (deep-link uit een factuurmail) → Toegang › "Telefoon/app
   koppelen" zodra ze TestFlight 1.1 hebben — of stuur een herstel-link (bestaand).

## Testbeeld
- Backend: `tests/auth/test_toestel_koppeling.py` (10), `tests/berichten/test_uitnodigingsmail_vorm.py` (7), `test_store_links.py`
  aangepast; `test_app_activatie.py` + `test_activatie_atomair.py` + `test_activatie_pincode.py` + `test_vaste_testconfig.py` — uitkomst
  in het slotrapport `2026-09-16-inbox-afgewerkt-3.md` (tijdens deze run draaide een tweede CC-proces op dezelfde test-DB; een
  eerste run gaf deadlocks/"schema platform does not exist" op tests die los groen zijn).
- Frontend: `tsc -b` groen; vitest `ActivateScreen.test` (+1), `AppActiveren.test` (+2, twee bestaande tests krijgen `webKeuze`),
  `ToegangInstellingen.test` (+2) — 3 bestanden groen.
- Rol-gate-sweep: nieuwe route onder `/auth/` (eigen authenticatie: get_current_gebruiker + rol- en toestelpoort), bestaande
  prefix-uitzondering.

## Meetrecept ná deploy (werkt in productie: ja/nee)
1. Deploy-check service én jobs op hetzelfde beeld.
2. Testuitnodiging (klant-accordeur) → open de link op een laptop → stop-scherm mét QR + "Ik gebruik de web-versie op dit apparaat";
   de uitnodiging is NIET verbruikt (nogmaals openen werkt; `GET /auth/uitnodigingen/info` blijft 200).
3. Scan de QR op de telefoon mét de app (TestFlight 1.1) → keuze/activatie → toegangscode → wachtrij.
4. In de web-versie (tweede testaccount of ná "web-versie op dit apparaat"): Toegang › "Telefoon/app koppelen" → toegangscode → QR +
   code → activeer op de telefoon → beide toestellen zichtbaar in Gebruikers & toegang › apparaten, geen intrekking van het eerste.
5. Mail van een nieuwe app-uitnodiging: genummerd 1-2-3, géén App Store-link (store 1.0), wél de TestFlight-instructie.
6. App 1.0 uit de App Store: inloggen met e-mail + willekeurig wachtwoord → melding eindigt op "Update de app naar versie 1.1 of
   gebruik de web-versie".

## Beslispunten
Zie `docs/rapporten/2026-09-16-beslispunten-peter.md` — opdracht 14.
