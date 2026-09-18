# Rapport 18-09 — SPOED "web app edge logt steeds uit?" (Edge op Android-tablet): diagnose op data + acht client-waarborgen

Opdracht: `opdrachten/gedaan/2026-09-18-SPOED-webapp-edge-android-logt-uit.md`. Domeinen: auth-toegang, accordering-native-app.
Geen migratie, geen server-wijziging. Gebouwd + getest 18-09-2026 in de inbox-run.

**Werkt in productie: NIET GEMETEN** — meetrecept in `opdrachten/inbox/2026-09-18-veldapp-uitvoerder-nameting.md` (punt 10): het
huidige toestel van de uitvoerder (account `6420642a`, Chrome-tablet + gekoppelde telefoon) blijft ≥ 24 u ingelogd — de
refresh-keten op de replica toont alleen rotaties (`gebruikt_op` gevuld, `ingetrokken_op` leeg), geen nieuwe
`toestel_geactiveerd` voor dat account.

**Eén regel voor Peter — wat de uitvoerder nu op de tablet doet:** open de app in Chrome of Edge, tik menu → "Toevoegen aan
startscherm" (Chrome) / "Toevoegen aan telefoon" (Edge) en start hem vanaf het beginscherm; ná de deploy vraagt de app binnen
vijf minuten ná een verversing of terugknop niet opnieuw de toegangscode en gaat de terugknop één scherm terug i.p.v. de app uit.

## Blok A — diagnose op DATA (lees-only)

Bronnen: Cloud Run-request-log (`gcloud logging read`, service `rlz-backend`), `platform.audit_event` en `platform.refresh_token`
op de leesreplica (`scripts/gcp/db_lezen.sh` als nameting@, actor Beheerder `2f2262cd…`). Tijden NL.

| Tijd | Bron | Feit |
|---|---|---|
| 09:11:47 | audit `uitnodiging_opnieuw_gemaild` (actor Peter) | gebruiker `6a6379ce` = Irfan Ogur, rol ZZP'er, e-mail uitvoerder@universal-steigerbouw.nl |
| 09:18:04 | log | `GET /activeren?token=4r8-…` — UA `Mozilla/5.0 (X11; Linux x86_64) … Chrome/139 … Edg/139.0.3405.102` (Edge, desktop-modus), IP 92.70.252.226 |
| 09:18:05 | log | `POST /auth/token/vernieuwen` **401** — verwacht: nog geen sessie (verse browser) |
| 09:18:16 | log + audit `toestel_geactiveerd` | `POST /auth/app/activeren` 200; toestel `5fc655b9`, platform web, apparaat_naam "Onbekend apparaat" (Edge-UA niet herkend), app_versie 1.2 |
| 09:18:36–09:18:36 | log | voorwaarden-akkoord 204, `/uren/zzp/weken-overzicht`, `/auth/administraties`, `/uren/dossier` 200 — de app werkt |
| 09:22:00 | log `GET /accordeur` | **volledige paginaherlaad 1** |
| 09:22:21 | log + refresh-keten | `POST /auth/token/vernieuwen` **200** (token `f9d35971` gebruikt → `bed07d75`) — ontgrendeld mét toegangscode |
| 09:23:22 · 09:23:33 · 09:23:45 · 09:24:14 | log `GET /accordeur` | **herlaad 2, 3, 4, 5** |
| 09:23:31 · 09:23:48 · 09:24:41 | log + keten | `vernieuwen` **200** ×3 (`bed07d75 → c93d0815 → e5216997 → 8c8bd478`) |
| 09:24:45–09:24:55 | log | `/uren/zzp/week-projecten`, `/uren/zzp/weekstaat` 200 — laatste request van het Edge-toestel |
| 09:27:18 | audit `e_mail_gewijzigd` (Peter) | adres van `6a6379ce` → uitvoerder.oud@… |
| **09:27:21** | audit `gebruiker_geblokkeerd` (Peter) + `refresh_token.ingetrokken_op` op **alle vijf** tokens | **dé uitlog**: blokkeren trekt de hele keten in (kill-switch-semantiek, bedoeld gedrag) |
| 09:27:25 | audit `gebruiker_gearchiveerd` | oude account weg uit de lijsten (0 weekstaten — geen datavlies) |
| 09:27:50 → 09:28:27 | audit | nieuw account `6420642a` "Orfan Ogur" (uitvoerder) uitgenodigd; op de tablet in **Chrome** (UA `Linux; Android 10; K … Chrome/153`) geactiveerd — toestel `e07f54ed` "Android-toestel" |
| 10:06:12 / 10:06:26 | audit `toestel_koppeling_aangemaakt` / `toestel_gekoppeld_zelfservice` | telefoon (IPv6) via zelfservice gekoppeld — 3 toestellen actief mogelijk |

**Antwoorden op de vier vragen van blok A.**
1. Gebruiker/toestel: `6a6379ce` / `5fc655b9` (Edge), later `6420642a` / `e07f54ed` (Chrome) + `0c026dd4` (telefoon).
2. Server-side afgewezen? **Nee.** Voor het Edge-toestel 0 × 401/410/426 ná activatie; élke verlenging 200; sliding-TTL 7 d
   (`verloopt_op` 25-09). De enige intrekking (09:27:21) is de blokkade door het kantoor. Frequentie van het "uitloggen": 5
   herladingen in 2 min 14 s, elk ná 22–70 s gebruik.
3. Client-kant: het refresh-token staat versleuteld in IndexedDB (`webVeiligeOpslag.ts`, database `accordeur-slot`), het
   ontgrendelde anker alleen in JS-geheugen (`appSlot.ts`). Storage was **niet** weg (anders geen 200 op vernieuwen zonder
   heractivatie). Bij élke volledige herlaad is het geheugen weg → toegangscode-scherm → voelt als "uitgelogd". Aanleiding
   van de herladingen (niet uit het serverlog te bewijzen, wél consistent met het patroon 22–70 s gebruik → `GET /accordeur`):
   de Android-terugknop (de flow wisselt schermen zonder history-entries, "terug" verlaat de SPA), pull-to-refresh (de
   desktop-modus-UA geeft een layout waar de body scrolt; `overscroll-behavior: contain` stond alleen op `.acc-content`) of
   tabblad-herstel. `navigator.storage.persist()` werd nergens gevraagd.
4. Edge-instellingen: niets in de data wijst op "browsegegevens wissen" (de opslag bleef); wél staat Edge op de tablet in
   desktop-modus (UA `X11; Linux x86_64`).

Reproductie-eis "Playwright, UA + storage-partitionering": **niet gebouwd** — Playwright zit niet in de repo. De bewijzen zijn
de productiedata hierboven plus jsdom-tests op elk mechanisme (blok B). Dat is minder dan gevraagd; ik zeg het liever dan het
te suggereren.

## Blok B — fix (client, lokaal; server ongewijzigd)

| # | Waarborg | Code | Test |
|---|---|---|---|
| 1 | Ontgrendel-venster over herladen: web-toestel bewaart het ontgrendelde anker in `sessionStorage` van dít tabblad voor het documenteerde 5-minutenvenster ("direct vergrendelen" uit); weg bij vergrendelen, sluiten, verlopen, uitsluiting | `api/appSlot.ts::herstelOntgrendeldVenster`, `AccordeurApp` slot-init | `appSlot.test.ts` (+1) |
| 2 | Android-terugknop = één scherm terug: history-val + event `acc-terug`, `UrenFlow.terugVan` (vaste ouder per scherm, beginscherm blijft) | `accordeur/androidTerug.ts`, `UrenFlow.tsx` | `androidTerug.test.ts` 2, `terugVan.test.ts` 2 |
| 3 | Geen pull-to-refresh op body-niveau binnen de app-oppervlakte | `AccordeurApp` (overscroll-behavior-y none op html/body) | in 2 (effect) |
| 4 | `storage.persist()` bij web-activatie, uitkomst ja/nee/onbekend lokaal | `api/webToestel.ts`, `AppActiveren` | `webToestel.test.ts` |
| 5 | Opslag gewist ≠ stil uitloggen: slot-vlag zonder IndexedDB → `OPSLAG_GEWIST_MELDING` (koppelcode ander toestel / herstel-link / beginscherm) | `AccordeurApp`, `webVeiligeOpslag.webSlotVlagStaat` | `webToestel.test.ts` |
| 6 | Diagnoseregel ⚙ Toegang: "modus: browsertab/PWA/app · opslag persistent · laatste tokenverlenging" | `webDiagnoseStaart`, `client.ts` noteert de verlenging (alleen slot-sessie) | `webToestel.test.ts` |
| 7 | Kaart "Zet deze app op je beginscherm" (Edge/Chrome/Safari-stappen, weg te klikken) in een browsertab | `accordeur/BeginschermNudge.tsx` | `webToestel.test.ts` |
| 8 | Uitnodigings-/herstelmail: Android zonder geschikte Play-versie → één zin web-versie op het beginscherm | `uitnodigingsmail.android_web_regel` | `test_uitnodigingsmail_vorm.py` +2 |

## Tests

| Suite | Uitkomst |
|---|---|
| Frontend `webToestel`, `androidTerug`, `terugVan`, `appSlot` | 29 groen |
| Volledige frontend-suite (`vitest run`, 11:27) | 217 bestanden / 1732 tests groen |
| Backend `tests/berichten/test_uitnodigingsmail_vorm.py` (+2) | <<BERICHTEN>> |
| `tsc -b` | groen |

## Beslispunten (gekozen)

1. Het venster over herladen = het al gedocumenteerde 5-minutenvenster van de native app (ING-model, mockup scherm 7) en
   respecteert "direct vergrendelen"; `sessionStorage` is per tabblad en verdwijnt bij sluiten — hetzelfde dreigingsmodel als
   procesgeheugen. Wil Peter het strenger (altijd code ná herladen), dan is dat "direct vergrendelen" aan of één constante.
2. Geen server-wijziging: de server deed precies wat hij moet (rotatie, TTL, kill-switch bij blokkade).
3. Proces: de blokkade + nieuwe uitnodiging van 09:27 was een workaround voor "rol wijzigen" — sinds vandaag kan dat via
   Gebruikers & toegang › Veldwerkers (rapport `2026-09-18-veldwerker-rol-wijzigen.md`); het oude account `6a6379ce` staat
   gearchiveerd met 0 weekstaten, het nieuwe heet "Orfan Ogur" (typo in de naam — klikpunt Peter: naam corrigeren).

## Gelezen regels

- `docs/regels/auth-toegang.md` (160 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/accordering-native-app.md` (264 regels) — volledig, vóór de start (Domeinen-kopregel).
