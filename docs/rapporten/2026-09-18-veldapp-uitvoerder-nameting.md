# Rapport 18-09 — Nameting veld-app uitvoerder (feedback 18-09 + project-eerst + rol wijzigen + beoordelen + web-toestel + UX run A)

**Opdracht:** `opdrachten/gedaan/2026-09-18-veldapp-uitvoerder-nameting.md` (poging 3, inbox-run 3, 18-09 ~16:00). Lees-only; er is
géén weekstaat geschreven (zie stap 1). **Werkt in productie: deels — stap 0 ja; de app-flows niet gemeten (niemand gebruikte de
veld-app sinds de deploy en de nameting kan de native app/PWA niet zelf bedienen).**

## Stap 0 — deploy-check: VOLDAAN
- `gh run list --workflow deploy.yml`: run 35351108334 op `998336b` (13:35Z) GROEN (5m25s); eerdere run 35345406823 groen.
- Service `rlz-backend` én jobs `rlz-migratie`, `rlz-reconciliatie`, `rlz-extractie-wachtrij`, `rlz-uren-herinneringen` op image
  `…backend:998336bc87f8…` (service en jobs in de pas).
- Migratie-job-log: `Running upgrade 0157 -> 0158` en `0158 -> 0159` (09:55Z), `0159 -> 0160`, `0160 -> 0161`, `0161 -> 0162` (12:36Z).
  De 0158–0162-stand staat live.
- Scheduler `rlz-uren-herinneringen` bestaat: `0,15,30,45 15-18 * * 1-5`, ENABLED (klikpunt run B door Peter gedaan).

## Stap 1 — meetrecept, per punt
| Punt | Uitkomst | Werkt in productie |
|---|---|---|
| 1–6, 10 (app-flows uitvoerder: tabs, kaarten, + Uren, doorfactureren, indienen, zelfde-als-gisteren, tikknoppen, chips) | Request-log vandaag (`/uren/zzp/*`, `/uren/uitvoerder/*`, `/uren/beheer/*`): **0 requests** sinds middernacht — niemand heeft de veld-app vandaag gebruikt; de nameting kan het testaccount niet zelf bedienen (toestelbinding + toegangscode, geen browser-automatisering in de repo). | niet gemeten — klikpunt Peter/testaccount (recept hieronder) |
| 7 (rol wijzigen Irfan/Orfan Ogur → uitvoerder) | `platform.gebruiker` 6420642a "Orfan Ogur" = rol **uitvoerder**, status actief. Geen `rol_wijziging`-audit en geen `PATCH /auth/gebruikers/<id>/rol` in het request-log van vandaag → de rol stond al of is niet via de nieuwe knop gezet. Kantoor-web `/veldwerkers` toont dus Uitvoerder. | rol staat: ja; de rolwissel-knop: niet gemeten (niet geklikt) |
| 8 (Beoordelen-chip Universal) | Replica (`--administratie 3ee6edf0…`): weekstaat `ingediend` = **14**, `concept` = 11; meerwerk: 0 rijen. Chip verwacht "14 urenstaten · 0 meerwerk te beoordelen"; niemand keurde (14 ongewijzigd t.o.v. 18-09 ochtend). `GET /uren/uitvoerder/te-keuren` vandaag: 0 requests. | data ja; UI-klik niet gemeten |
| 9 (web-toestel "logt steeds uit") | Tokenketen 6420642a laatste 24 u: 4 tokens (07:28, 07:29 gebruikt = rotaties; 08:06:06 en 08:06:26 open), **0 ingetrokken**; `POST /auth/token/vernieuwen` vandaag 4 × 200, **geen 401**. Wél een `toestel_gekoppeld_zelfservice`/`toestel_geactiveerd` voor dit account om 08:06Z via link (platform web) — dat is VÓÓR de deploy van 13:41Z, dus geen tegenbewijs tegen de fix; ná de deploy geen nieuwe activatie voor dit account (kantoorbreed: 5 activaties vandaag, laatste 11:14Z, alle vóór de deploy). | geen 401/intrekkingen: ja; Peter's tablet-klikpunt (verversen binnen 5 min → geen toegangscode): niet gemeten |
| 11 | Geen test-weekstaat geschreven (app niet bedienbaar vanuit de nameting); niets verwijderd. | n.v.t. |

## Klikpunten Peter (testaccount uitvoerder, native app of PWA — ná deze deploy)
1. Inloggen → tabs "🏗 Projecten · ⏱ Mijn uren · ✓ Te keuren", géén Planning.
2. Mijn uren → deze week: projectkaarten (gepland/mét uren) mét dagbalk; "+ Ander project toevoegen aan mijn week" → keuzelijst.
3. Op een TEST-project "+ Uren": tikknoppen 4·6·8·10, chips opbouwen/afbreken/…, m² leeg laten, doorfactureren-chip "standaard voor dit
   project" → Opslaan (request-log `PUT /uren/zzp/dag` 200) → chip "1,0 u" zonder "· —".
4. "Week indienen (N u)" → samenvatting → "Ja, indienen" → `POST /uren/zzp/indienen` 200.
5. Kantoor-web klantpagina Universal: chip "14 urenstaten · 0 meerwerk te beoordelen" → Beoordelen › Urenstaten (14).
6. Tablet (Edge/Android): ná de deploy verversen binnen 5 min → geen toegangscode; ⚙ Toegang › Diagnose toont modus/opslag.
Daarna: `gh workflow run nameting.yml -f onderdeel=meting` of dit rapport aanvullen met "werkt in productie: ja/nee" per punt.

## Gelezen regels
- `docs/regels/uren-planning-veldwerkers.md` (472 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/autoboeken-ai.md` (122 regels), `docs/regels/werkvoorraad-controlescherm.md` (297 regels), `docs/regels/btw.md` (150 regels), `docs/regels/kantoor-frontend.md` (123 regels), `docs/regels/intake-extractie.md` (270 regels), `docs/regels/accordering-native-app.md` (321 regels), `docs/regels/duplicaten-crediteuren.md` (119 regels)
