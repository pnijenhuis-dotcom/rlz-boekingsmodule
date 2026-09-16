# Rapport 16-09 (nacht) — Store-nazorg: iOS 1.1 (build 140) ingediend, Android vc4 in review; docs + deploy.yml bijgewerkt

Opdracht: `opdrachten/gedaan/2026-09-16-store-nazorg-ios-1-1-ingediend.md`. Eén docs/config-commit, geen code, geen migratie.
**Werkt in productie: n.v.t.** (store-status + documentatie).

## Feiten (Cowork via App Store Connect / Play Console, 16-09 avond)

- App Store Connect: versie 1.1 mét build **1.1 (140)** (Xcode Cloud 21:54, bevat de uitnodigingsfix van 16-09) **ingediend 16-09
  22:24 → "Waiting for Review"**. App Review Information = activatiecode-flow (Password = review-activatiecode, dezelfde als in Play
  "Demo-account review (7 Sep 2026)"), automatisch vrijgeven ná goedkeuring.
- Google Play: release 2 (vc2, oude passkey-login) LIVE sinds 13-09 19:22 — inzending 2 werd níét geannuleerd (correctie op de
  aanname van 13-09); release 4 (vc4, app-auth) "wordt beoordeeld" sinds 13-09 19:09, 0 installaties.

## Gedaan

| # | Wat | Waar |
|---|---|---|
| 1 | §0f: blok "STAND 16-09 22:24 — 1.1 (140) INGEDIEND" mét de resterende stappen (STORE_APP_VERSIE_IOS ná goedkeuring; train-regel → 1.2: pbxproj ×2, `versionName`/vc6, `appVersie.ts`, guard); §0c/§0e/§0f-buildnummers 90/99 als historie gemarkeerd (notitie onder de koppen) | `native/TESTFLIGHT_DRAAIBOEK.md` |
| 2 | Blok "STAND 16-09": release 2 live / release 4 in review; les "een nieuwe inzending annuleert de lopende NIET — Inzendingsactiviteit controleren"; ná goedkeuring vc4: `STORE_LINK_ANDROID` + vc5 (1.1) bouwen/uploaden (§3/§4) + `STORE_APP_VERSIE_ANDROID` pas bij publieke 1.1-listing | `native/PLAY_DRAAIBOEK.md` §3 |
| 3 | Commentaarregel bij de store-envs: `STORE_APP_VERSIE_IOS` pas op 1.1 NÁ Apple-goedkeuring (nu code-default 1.0 — anders wijst de uitnodigingsmail naar een store-versie mét de oude login); geen env-waarde gewijzigd | `.github/workflows/deploy.yml` |
| 4 | Sectie "APPLE 1.0 GOEDGEKEURD 09-09 — 1.1 MET APP-AUTH VOLGT": rij "1.1 INGEDIEND 16-09"; registerrij Klant-autorisatie mét de Play-/iOS-stand | `docs/BESLISSINGEN.md` |

## Geparkeerd

- Bewaking "store-versie iOS < min-runtime" als reconciliatie-LET-OP: de automatiseringen-lijst (`app/reconciliatie/automatiseringen.py`)
  werkt met audit-/run-sporen per etmaal; een settings-vergelijking past er niet in één regel bij. Geparkeerd; ligt logisch bij de
  minimum-versie-poort van de OTA-opdracht (`2026-09-16-native-app-live-updates-ota.md`, blok C).

## Klikwerk Peter (ná review)

1. Apple keurt 1.1 goed → `STORE_APP_VERSIE_IOS=1.1` in deploy.yml (+ sleutel in `test_deploy_yml_envset_compleet.py`) → deploy →
   uitnodigingsmail toont weer de App Store-link. Daarna marketingversie → 1.2 vóór de volgende app-rakende push.
2. Google keurt vc4 goed → `STORE_LINK_ANDROID` vullen, vc5 (1.1) bouwen/uploaden; Inzendingsactiviteit controleren.

## Tests

- `tests/unit/test_claude_md_beslissingen_verwijzingen.py`, `test_rapporten_index.py`, `test_deploy_yml_envset_compleet.py`,
  `test_deploy_yml_envvar_delimiters.py`, `test_app_marketingversie_consistent.py` — zie slotrapport voor de uitkomst.
