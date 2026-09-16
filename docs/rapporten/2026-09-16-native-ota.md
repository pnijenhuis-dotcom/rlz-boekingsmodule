# Rapport 16-09 (nacht) — Accordeur-/veldwerker-app: live updates (OTA) van de web-laag, minimum-versie-poort (426), Android in-app-update

Opdracht: `opdrachten/gedaan/2026-09-16-native-app-live-updates-ota.md` (besluit Peter 16-09: "zsm af van TestFlight, de native app moet
gewoon werken"). Migratie 0152 (routine rond). **Werkt in productie: niet gemeten** — de code staat vóór de deploy én het eerste echte
effect vereist een winkelrelease mét de plugins plus de bundel-bucket (klikpunten Peter).

## Blok A — STAP-0 (lees-only)

| Vraag | Uitkomst |
|---|---|
| Plugin | `@capgo/capacitor-updater` 8.51.16, MPL-2.0, peer `@capacitor/core ^8.0.0` — past op onze Capacitor 8.5.0; self-hosted (`autoUpdate: false`, geen Capgo-account). iOS-target 15.0 / Android minSdk 24 liggen boven de plugin-minima. |
| Afgewezen | `@capacitor/live-updates` (Ionic Appflow, betaald, geen self-host); Capacitor `server.url` (remote webview = reviewrisico, eerder al afgewezen). |
| Android in-app-update | `@capawesome/capacitor-app-update` 8.0.5, MIT, peer `@capacitor/core >=8.0.0`. |
| Niet via OTA | native plugins + Swift/Kotlin, permissions/entitlements, deep-link-config in de app, app-auth-schil (VeiligeOpslag/AppSlot/NatievePasskey), Capacitor-versie, icoon/splash/naam → winkelroute + marketingversie ophogen (regel "native-dep = winkelrelease + runtime-versie ophogen"). |

## Blok B — update-server + bundel-pijplijn

- Migratie 0152: `platform.app_bundel`, singleton `platform.app_update_instelling` (percentage 100, uitgeschakeld false), drie kolommen op
  `webauthn_credential` (app_versie, bundel_id, bundel_gezien_op). Routine: `alembic upgrade head` dev-DB → 0152, `alembic check` schoon,
  live 200 op `/app/update-manifest`, 426 op een te oude aangekondigde schil, 401 op het Beheerder-blok zonder token, schema-dump ververst.
- Deploy-stap "OTA-webbundel bouwen, uploaden en registreren": frontend `--mode native` → zip → `gs://rlz-boekhouding-app-bundels/bundels/<runtime>/<id>.zip`
  → `app-bundel-registreren` op de job-image; runtime = `APP_MARKETING_VERSIE`. Envs `APP_BUNDEL_GCS_BUCKET`, `APP_MIN_RUNTIME_VERSIE`,
  `OTA_UITGESCHAKELD` in service én jobs.
- Manifest kiest uitsluitend bundels van de gevraagde runtime + platform; kill-switch env óf DB; cohort deterministisch; `verplicht` reist mee;
  download via de backend (bucket privé, immutable-cache, `X-Bundel-Sha256`).
- App (`ota.ts`): koude start `notifyAppReady` + `updateFailed`-luisteraar + check; voorgrond max 1× per 15 min; `next` (volgende start) of
  `set` (verplicht, melding "App bijgewerkt"); rollback → `POST /app/update-melding` → audit `ota_rollback`; diagnoseregel `· bundel <id>`.
- Beheerder-blok "App-updates" op Instellingen › Boeken: bundels per runtime (terugtrekken), cohort-%, noodrem (+ env-stand), laatste 20
  toestellen mét bundel. Registry-anker `#app-updates`.
- Native: beide plugins geïnstalleerd (`native/package.json` + lock), `cap sync` gedraaid (Package.swift + gradle-wiring bijgewerkt),
  `capacitor.config.ts` `plugins.CapacitorUpdater {autoUpdate:false, appReadyTimeout:10000, resetWhenUpdate:true}`.

## Blok C — minimum-versie-poort + Android in-app-update

- App kondigt zich aan met `X-App-Versie`/`X-App-Platform`/`X-Bundel-Id` (alleen slotmodus; kantoor-web byte-identiek, guard).
- `MinimumAppVersiePoort` (ASGI, bínnen CORS, vóór routing): aangekondigde schil < `APP_MIN_RUNTIME_VERSIE` → 426 met `min_versie`,
  `store_url`; `/health`, manifest en bundelpad vrij. Per request landen versie/bundel op de toestel-rij (alleen bij verandering).
- Scherm "Update nodig" (winkelknop; Android IMMEDIATE via Google In-App Updates als de plugin er is); FLEXIBLE bij voorgrond max 1×/24 u.
- Eerlijk benoemd: bestaande installaties (1.0, 1.1 build 140) kondigen zich niet aan en blijven onder de legacy-Sunset-route + de
  uitnodigingsmail-poort; de 426-poort is de ene versiepoort vanaf de eerste schil mét deze webcode.

## Tests

| Poort | Uitkomst |
|---|---|
| `tests/appupdate/test_ota.py` | 9 groen (manifest runtime/platform, kill-switch env+DB, cohort + verplicht, registreren idempotent/terugtrekken, route + download + 404, rollback-audit + toestelstand, 426-pad incl. vrije paden, Beheerder-routes + 403, CLI) |
| `test_app_marketingversie_consistent` | +1: `APP_MIN_RUNTIME_VERSIE` ≤ marketingversie (code + deploy.yml) en de OTA-stap aanwezig |
| Frontend vitest (ota 7, AppUpdatesBlok 1, client 426-event, koudeStart bundel, registry, appBundelGuard, AccordeurApp, appslot, changelog) | 120 groen; `tsc -b` groen |
| Backend regressie (auth, security-gates, unit-guards, beheer) | zie slotrapport |

## Klikpunten Peter (eerste echte effect)

1. `scripts/gcp/app_bundels_bucket.sh --apply` als owner (bucket + IAM); tot dan is de OTA-deploystap rood maar draait de service.
2. Winkelrelease mét de plugins: iOS = eerste Xcode Cloud-build ná deze push (1.1 (141+); ná goedkeuring van 140 → 1.2 volgens de train-regel),
   Android = vc5 (`bouw_android_release.sh 5 1.1`) ná goedkeuring van vc4.
3. `APP_MIN_RUNTIME_VERSIE` pas ophogen als die winkelversie live is.

## Meetrecept (vervolg-opdracht `opdrachten/inbox/2026-09-17-native-ota-nameting.md`)

Deploy-check → `curl …/app/update-manifest?runtime=1.1&platform=ios` = bundel van de laatste deploy → op een toestel mét plugin-schil:
diagnoseregel `bundel <sha7>` binnen één herstart → noodrem aan → `geen_update` → Instellingen › Boeken › App-updates toont bundel + toestel →
"werkt in productie: ja/nee".
