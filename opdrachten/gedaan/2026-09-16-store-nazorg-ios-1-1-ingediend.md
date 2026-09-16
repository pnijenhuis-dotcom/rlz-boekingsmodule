> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-store-nazorg.md

# OPDRACHT 16-09 (avond) — Store-nazorg: iOS 1.1 (build 140) ingediend 22:24; Android vc4 in review; docs + envs bijwerken (klein, docs + deploy.yml)

**Feiten (Cowork via App Store Connect / Play Console, 16-09 avond):**
- App Store Connect: versie 1.1 aangemaakt, build **1.1 (140)** gekoppeld (Xcode Cloud 21:54, bevat de uitnodigingsfix van
  vanavond), "What's New" NL ingevuld, App Review Information herschreven naar de activatiecode-flow (§1 stap 6-tekst, geen
  passkey/wachtwoord meer), Password-veld = de review-activatiecode (dezelfde als in Play "Demo-account review (7 Sep 2026)"),
  automatisch vrijgeven ná goedkeuring. **Ingediend 22:24 → "Waiting for Review".**
- Google Play: release 2 (vc2, oude passkey-login) staat LIVE sinds 13-09 19:22 (inzending 2 werd níét geannuleerd — correctie op
  de aanname van 13-09); release 4 (vc4, app-auth) "wordt beoordeeld" sinds 13-09 19:09, 0 installaties.

## Te doen (één docs/config-commit)
1. `native/TESTFLIGHT_DRAAIBOEK.md` §0f: status "1.1 (140) INGEDIEND 16-09 22:24, wacht op review"; train-regel: ná goedkeuring
   marketingversie → 1.2 vóór de volgende push (pbxproj ×2, `versionName`/vc6, `appVersie.ts`, guard). §0c/§0e-verwijzingen naar
   "build 90/99" als historie markeren.
2. `native/PLAY_DRAAIBOEK.md`: stand "release 2 (vc2) live 13-09, release 4 (vc4) in review" + les "een nieuwe inzending annuleert
   de lopende NIET; controleer ná indienen de Inzendingsactiviteit"; ná goedkeuring vc4: `STORE_LINK_ANDROID` vullen + vc5 (1.1)
   bouwen/uploaden (PLAY §3/§4).
3. `.github/workflows/deploy.yml`: `STORE_APP_VERSIE_IOS=1.1` pas zetten **ná** Apple-goedkeuring (nu nog 1.0 — anders wijst de
   uitnodigingsmail naar een store-versie die nog de oude login heeft). Voeg een commentaarregel toe met die voorwaarde; bewaking:
   reconciliatie-LET-OP "store-versie iOS < min-runtime" bestaat niet → alleen als het in één regel kan in de bestaande
   automatiseringen-lijst, anders parkeren.
4. BESLISSINGEN "APPLE 1.0 GOEDGEKEURD 09-09 — 1.1 MET APP-AUTH VOLGT": aanvulling "1.1 ingediend 16-09"; registerrij Play
   bijwerken; memory/rapport: `docs/rapporten/2026-09-16-store-nazorg.md` + INDEX ("werkt in productie: n.v.t.").
