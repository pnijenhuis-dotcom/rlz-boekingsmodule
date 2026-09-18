uitgevoerd 2026-09-18 (poging 3, stap 0 voldaan; app-flows = klikpunten), rapport: docs/rapporten/2026-09-18-veldapp-uitvoerder-nameting.md

Domeinen: uren-planning-veldwerkers, werkloop-productie

# OPDRACHT 18-09 — Nameting ná deploy: veld-app uitvoerder feedback 18-09 (m² optioneel, doorfactureren, alle projecten, planning weg)

Vervolg op `docs/rapporten/2026-09-18-veldapp-uitvoerder-feedback.md` (werkt in productie: niet gemeten). Lees-only waar het kan;
de enige schrijfhandeling is één weekstaat-regel + indienen op het TESTACCOUNT (geen klantdata).

## Stap 0 — deploy-check (service ÉN jobs)
`gh run list --workflow deploy.yml --limit 3` → de run op de commit mét migratie 0158 moet groen zijn incl. migratie-job
(`Running upgrade 0157 -> 0158`) en smoketest; `gcloud run services describe` + `gcloud run jobs describe … --format='value(template.template.containers[0].image)'`
op dezelfde image. Niet live = stoppen, melden, opdracht terug in de inbox.

## Stap 1 — meetrecept (testaccount uitvoerder, native app of PWA)
1. Inloggen als uitvoerder-testaccount → tabs = "🏗 Projecten · ⏱ Mijn uren · ✓ Te keuren", GEEN "📅 Planning".
2. Mijn uren → deze week → lijst toont "Gepland deze week" + "Andere projecten" (chip "niet gepland"), zoekveld werkt, geen
   "+ ander project"-knop.
3. Kies een niet-gepland TEST-project → dag invullen: uren 1, m² LEEG, dropdown "Doorfactureren" toont "standaard voor dit
   project: …" → Opslaan = 200 (request-log Cloud Logging: `PUT /uren/zzp/dag` 200) → chip "1,0 u" zonder "· —".
4. Week indienen = 200 (`POST /uren/zzp/indienen`), toast "een andere uitvoerder … keurt".
5. Kantoor-web: planning-grid → klik op het kaartje → `/meerwerk?administratie=…&weekstaat=…` toont het weekstaatpaneel mét
   kolom Doorfactureren en filter "alleen niet doorfactureren".
6. **Project-eerst (opdracht `veldapp-project-eerst-flow`, gebouwd 18-09 in dezelfde deploy):** Mijn uren → deze week toont
   PROJECTKAARTEN (gepland/mét uren) mét dagbalk; "+ Ander project toevoegen aan mijn week" → keuzelijst (request-log:
   `GET /uren/zzp/week-projecten?…&alles=true` 200) → kaart erbij; op de kaart "+ Uren" → formulier mét project én dag al
   ingevuld → Opslaan 200; "Week indienen (N u)" → `POST /uren/zzp/indienen` 200; kaart "Meerwerk melden" zichtbaar voor de
   uitvoerder. Punt 2 hierboven ("lijst toont Gepland deze week + Andere projecten") is door project-eerst VERVANGEN door
   deze kaartenflow — meet de kaarten, niet de oude lijst.
7. **Rol wijzigen (opdracht `veldwerker-rol-wijzigen`, zelfde deploy) — alleen meetbaar ná Peter's klik:** heeft Peter Irfan
   Ogur via Gebruikers & toegang › Veldwerkers op Uitvoerder gezet, dan: audit_event `rol_wijziging` op zijn gebruiker-id
   (oud zzper → nieuw uitvoerder, lees-only via db-lezen/Cloud Logging `PATCH /auth/gebruikers/<id>/rol` 204), `/veldwerkers`
   toont Uitvoerder, en zijn app toont ná verversing "Projecten · Mijn uren · Te keuren". Niet geklikt = "niet gemeten",
   geen rolwissel door de nameting zelf (dat is een mensbesluit).
8. **Beoordelen (opdracht `BUG-chip-meerwerk-urenstaten-lege-pagina`, zelfde deploy):** klantpagina Universal Steigerbouw →
   chip zegt "N urenstaten · M meerwerk te beoordelen" (verwacht N = 14 zolang niemand keurde; lees-only tegenbewijs:
   `db_lezen.sh … boekhouding.weekstaat … status='ingediend' --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`) → klik →
   Beoordelen › Urenstaten (N) toont exact N rijen, tab Meerwerk (M) exact M; lege stand pas ná een keuring mét "laatste
   keuring <datum>". Irfan (uitvoerder, scope Universal): zijn app-tab "Te keuren" toont dezelfde N (minus eigen staten) zonder
   projectkoppeling — request-log `GET /uren/uitvoerder/te-keuren` 200. Niets keuren in de nameting (dat is kantoorwerk).
9. **Web-toestel (opdracht `SPOED-webapp-edge-android-logt-uit`, zelfde deploy):** lees-only op de replica
   (`db_lezen.sh … platform.refresh_token WHERE gebruiker_id = '6420642a-…' … --als 2f2262cd-…`): de keten van het huidige
   uitvoerder-account toont ≥ 24 u alleen rotaties (`gebruikt_op` gevuld, `ingetrokken_op` leeg, laatste token open) en
   `platform.audit_event` geen nieuwe `toestel_geactiveerd` voor dat account; request-log: geen 401 op
   `POST /auth/token/vernieuwen` van zijn toestellen. Peter's klikpunt (niet door de nameting): op de tablet ná de deploy
   verversen/terugknop binnen 5 min → geen toegangscode; ⚙ Toegang › Diagnose toont "modus: … · opslag persistent: …".
10. **UX run A (opdracht `veldapp-ux-verbeteringen-12-punten`, zelfde deploy):** op het testaccount: kaart toont "⟲ Zelfde
    als gisteren" ná een eerdere regel → tik → request-log `PUT /uren/zzp/dag` 200 mét `bron=kopie` in het audit-event
    `weekstaat_dag_gezet` (replica, `--administratie`); "+ Uren" → tikknoppen 4·6·8·10 zichtbaar, chips "opbouwen …" uit
    `GET /uren/zzp/omschrijving-chips` 200; indienen zonder m² → samenvatting → "Ja, indienen" → `POST /uren/zzp/indienen` 200;
    ⚙ Instellingen › Universal › Uren & materiaal toont de chips-rij (`GET /uren/beheer/omschrijving-chips/<aid>` 200 als
    Beheerder). Migratie-job-log: `Running upgrade 0158 -> 0159`.
11. Rapportregel "werkt in productie: ja/nee" per punt; de test-weekstaat blijft staan (ingediend; niets verwijderen).

## Afronding
Rapport `docs/rapporten/<datum>-veldapp-uitvoerder-nameting.md` + INDEX + "Gelezen regels"; BESLISSINGEN-sectie "VELD-APP
UITVOERDER — FEEDBACK 18-09" aanvullen met alinea "Nameting"; deze opdracht → gedaan.

---
**Poging 1 (18-09 ochtend, inbox-run) — gestopt op stap 0:** service én jobs op `47cf967` (zonder 0158; de feedback-run stond
ongecommit en is in die inbox-run alsnog gecommit). Rapport `docs/rapporten/2026-09-18-veldapp-uitvoerder-nameting-stap0.md`.
**Aanwijzing stap 0 voor de volgende poging:** de deploy-run op de commit mét migratie 0158 moet GROEN en KLAAR zijn — is hij nog
bezig (`gh run list --workflow deploy.yml --limit 1` → `in_progress`), dan `gh run watch <id>` (max ~15 min) en daarna opnieuw
service + jobs toetsen; pas dán meten.

---
**Poging 2 (18-09 middag, inbox-run 2 — stap 0 uitgevoerd, lees-only):** deploy-run 35331867071 (`15566c4`, 09:53Z) GROEN; service
`rlz-backend-00633-mb2` én jobs `rlz-migratie`/`rlz-reconciliatie` op image `…backend:15566c4`; migratie-executie `rlz-migratie-j8mcr`
(09:55Z) logt `Running upgrade 0157 -> 0158` en `0158 -> 0159`. De 0158/0159-stand staat dus live. **Niet gemeten**, omdat de opdracht
"pas ná deploy van 1–5" zegt: de commits van opdrachten 1–5 (zoekveld/sticky, bulk-upload, projecten-status, planning v3, run B) gaan pas
ná deze run via de Stop-hook naar origin — een deploy binnen de run bestaat niet (push staat op de deny-lijst). Volgende tick: stap 0
opnieuw (deploy-run op de laatste commit van run 2 groen, incl. `Running upgrade 0159 -> 0160 -> 0161 -> 0162`), dán meten.
