# Nameting checks-cache (IBAN-wissel) — mens-afhankelijke metingen + eerste `server_timing`-regels ná de deploy van 22-09 (23-09, poging 2)

Opdracht `opdrachten/gedaan/2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md` (inbox-run, `niet vóór: 2026-09-23 09:00`;
gestart 23-09 ~10:15 NL). Vorige meting: `docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md`; bouwrapport
`docs/rapporten/2026-09-21-iban-wissel-cache.md`; BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09" (alinea
"Gemeten 23-09" toegevoegd). Peter keek niet mee; keuzes staan in "Keuzes".

**Één regel voor Peter:** de snelheidsmeting komt sinds gisteren aan (126 logregels; de Reeleezee-controles duren doorgaans 0,7 s) en het
audit-veld staat op élke rekeningnummer-mutatie. Maar de route die op 21-09 gebouwd werd voor "rekeningnummer is intussen al vertrouwd →
controles direct opnieuw" heeft in productie nooit gewerkt: de server antwoordde 400 waar het scherm 409 verwachtte. Vanochtend 09:50
liep een collega bij Kempen Facilities daar precies tegenaan (kale foutmelding, rode controle bleef staan). Gefixt in deze run (server zegt
409, scherm herkent beide); de fix staat ná de deploy live. Het Meyer-document wacht nog steeds op de derde accordeur.

## Werkt in productie — per meting

| Meting | Uitkomst | Werkt in productie |
|---|---|---|
| 0 deploy-check | service `rlz-backend` én job `rlz-reconciliatie` op `3e17648` (HEAD); `80aa473` (`app/logboek.py`, audit-veld) live sinds deploy `1018bcf` klaar 22-09 08:43Z = 10:43 NL; `main..origin/main` = 0 | ja |
| 1 Meyer 0015.21.664.V.51.0112 | onveranderd `ter_accordering` sinds 21-09 10:17:59 NL, laag 1+2 akkoord, laag 3 (klant-accordeur) open, `rlz_boekstuknummer` leeg, `boek_cyclus` 0; 0 requests op het document sinds de deploy; cache-rij `ongeldig:…` (nazorg 22-09) | niet gemeten (niemand raakte het document) |
| 2 `POST …/checks?extern=vers` | 0 × in 76 checks-requests sinds 22-09 08:40Z (44 op 22-09, 32 op 23-09 tot 10:00 NL; 41 × `voorverwarm=1`) | niet gemeten voor de knop |
| 2b al-vertrouwd-route (409 → vers) | **ROOD:** 23-09 07:50:37Z `POST …/documenten/40ef6c53…/iban-accordering` → **400** (Kempen Facilities `66e1e296`); het scherm herkende alleen 409 → geen `extern=vers`, kale fout; document bleef `te_controleren` | **nee** — gefixt in deze run (409 + scherm herkent 400/409) |
| 3 audit `checks_cache_ongeldig` | 9 × `leverancier_iban_toegevoegd` sinds de deploy (3 administraties), álle mét `checks_cache_ongeldig: 0` (geen geldige cache-rij op dat moment); 0 vier-ogen-akkoorden | ja voor het veld; akkoord-pad (≥ 1) niet gemeten |
| 4 `server_timing` | 126 regels 22-09 08:52Z → 23-09 07:55Z; `checks.extern` mens-route n=20 p50 661 ms / p95 1.826 ms | **ja** (logregel komt aan) |

## Stap 0 — deploy-check

```
git fetch origin main; git rev-list --count main..origin/main → 0
gcloud run services describe rlz-backend  → …/backend:3e176482c83d…
gcloud run jobs describe rlz-reconciliatie → …/backend:3e176482c83d…   (spec.template.spec.template.spec.containers[0].image)
git merge-base --is-ancestor 80aa473 1018bcf → ja   (deploy-run 1018bcf: 22-09 08:37:34Z → 08:43:31Z)
```
Twaalf deploys sinds de fix (`1018bcf` … `3e17648`, laatste 23-09 07:54Z), alle groen.

## Stap 1 — metingen (lees-only)

### 1.1 Meyer-document (`scripts/gcp/db_lezen.sh --administratie 876d5515-…`, leesreplica, poort 5441)

`boekhouding.document` 2f9c342c: `ter_accordering`, `laatst_gewijzigd_op` 2026-09-21 08:17:59Z. `boekvoorstel`: `rlz_boekstuknummer` NULL,
`boek_cyclus` 0. Laatste vier `document_gebeurtenis`-rijen = de bekende van 21-09 (checks doorstaan 08:17:58Z → ter_accordering 3 lagen →
akkoord laag 1 08:18:12Z → laag 2 08:54:04Z); geen rij ná 22-09 08:40Z. `check_extern_cache`: `ongeldig:eaf73e0a…`, `gecontroleerd_op` 21-09
08:17:56Z. Request-log op het document-id sinds de deploy: 0 regels. **Niet gemeten** — de meting hangt aan de klant-accordeur (laag 3).

### 1.2 Request-log `boekvoorstel/checks` (Cloud Logging, `rlz-backend`, sinds 2026-09-22T08:40:00Z)

76 requests: 44 op 22-09, 32 op 23-09 (tot ~10:00 NL); 41 × `?voorverwarm=1`, 35 gewoon, **0 × `extern=vers`**. De knop "Opnieuw
controleren" is door niemand gebruikt. **Niet gemeten voor de knop.**

### 1.2b De al-vertrouwd-route is wél geraakt — en werkte niet (ROOD)

Request-log 23-09 (UTC), Kempen Facilities B.V. (`66e1e296-6582-41bd-80d2-1be7316f5d52`), inkoopfactuur `40ef6c53-96a0-41ec-b73f-f83af30006fd`
(referentie 282834, UBL, factuur-IBAN NL61RABO0364625546, crediteur `82f817dc-…`):

```
07:46:46  POST …/boekvoorstel/checks?voorverwarm=1   200  2,40 s   ← cache-rij 07:46:47, vertrouwde_ibans ["NL68RABO0138812330"]
07:47:44  GET  …/boekvoorstel (+ 12 detail-routes)    200            ← mens opent het controlescherm
07:47:46  POST …/boekvoorstel/checks                  200  0,50 s   (uit cache)
07:48:52  POST …/boekvoorstel/checks                  200  1,17 s
07:49:51  PUT  …/boekvoorstel                         200  2,23 s   (audit boekvoorstel_opgeslagen 07:49:51)
07:50:37  POST …/iban-accordering                     400  0,08 s   ← het aanbieden
          (daarna niets meer op dit document; geen extern=vers, geen iban_accordering-rij, status te_controleren)
```

Welke 400? De route kent twee 400-oorzaken: `GeenCrediteurOpVoorstel` en `IbanAlVertrouwd`. Stand op de replica: crediteur gezet
(`82f817dc`), status `te_controleren` (geen 409-status-oorzaak), geen open accordering (0 rijen `iban_accordering` op het document en 0 in
de administratie sinds 22-09), IBAN geldig (anders 422). Dus `IbanAlVertrouwd`: het aangeboden IBAN stond al in de set — de set van deze
crediteur is alleen NL68RABO0138812330 (rlz_seed 26-08), de factuur-IBAN NL61RABO… niet; de mens heeft dus het bekende nummer in het veld
gezet (de body wordt niet gelogd; dit is de enige consistente lezing). Het scherm (`IbanAanbiedenVorm`) toetste `err.status === 409` →
de "intussen vertrouwd — controles opnieuw"-route van 21-09 vuurde niet, de mens zag de kale servertekst en de check-rij bleef staan.
Kanttekening: in dít geval had een verse run de IBAN-wissel óók blokkerend gelaten (factuur-IBAN ≠ set) — maar het contract "409 → vers"
had sowieso nooit kunnen werken: `router.py` gaf `IbanAlVertrouwd` als 400 sinds de bouw op 21-09; de service-test deed
`pytest.raises(IbanAlVertrouwd)` en de vitest mockte 409 — beide groen, geen test las de HTTP-status. **Werkt in productie: nee.**

### 1.3 Audit `checks_cache_ongeldig` (replica-sweep per administratie, 79; RLS zonder Beheerder-clausule)

Sinds 2026-09-22T08:40:00Z, `actie LIKE 'leverancier_iban%' OR 'iban_accord%'`:

| Administratie | Tijd (UTC) | Bron | IBAN | `checks_cache_ongeldig` |
|---|---|---|---|---|
| Kempen Facilities `66e1e296` | 23-09 07:43:14 | rlz_seed | NL51RABO0123875218 | 0 |
| Kempen Facilities `66e1e296` | 23-09 07:43:50 | rlz_seed | NL34RABO0313923841 | 0 |
| Kempen Facilities `66e1e296` | 23-09 07:51:09 | rlz_seed | NL47INGB0669965855 | 0 |
| Kempen Facilities `66e1e296` | 23-09 08:07:53 | bevestigd | NL22KNAB0413685012 | 0 |
| `5419878c` | 23-09 08:46:32 | bevestigd | NL02RABO0142998583 | 0 |
| `5419878c` | 23-09 08:48:10 | baseline | BE55310026942444 | 0 |
| `5419878c` | 23-09 08:50:08 | rlz_seed | NL07INGB0008167779 | 0 |
| `4e7732c5` | 23-09 08:45:59 | baseline | NL22INGB0007593366 | 0 |
| `4e7732c5` | 23-09 08:45:59 | rlz_seed | NL10RABO0192330020 | 0 |

Het veld staat op élke rij (bevestigd/baseline/rlz_seed — het gat van 22-09 is dicht), waarde 0 = er was op dat moment geen geldige
cache-rij voor die crediteur (seed/baseline vullen de set vóór de eerste externe run; de bevestiging van 08:07:53 kwam ná een al
ongeldig gemaakte/afwezige rij). 0 vier-ogen-akkoorden → **≥ 1 op het akkoord-pad blijft niet gemeten**; het veld werkt in productie: ja.
Kruistelling: `boekhouding.leverancier_iban` nieuw sinds de deploy = 4 + 3 + 2 = 9 rijen in dezelfde drie administraties — klopt.

**Meetfout onderweg (les, `werkloop-productie.md` 23-09):** de eerste sweep (`.scratch/audit-iban-sweep-23-09.sh`, `2>/dev/null`, parallel
aan een tweede `db_lezen.sh` op poort 5441) meldde "SWEEP KLAAR" mét 0 rijen; pas de telling op `leverancier_iban` ontmaskerde dat élke
iteratie stil gefaald was (transiente `gcloud sql instances describe`-fout → exit 3). De herhaling (`…-b.log`, stderr gelogd, exclusief)
gaf de 9 rijen.

### 1.4 `server_timing` (Cloud Logging `jsonPayload.message="server_timing"`, sinds 2026-09-22T08:40:00Z)

126 regels, eerste 22-09 08:52:59Z (9 min ná de deploy), laatste 23-09 07:55:37Z. **Werkt in productie: ja** — de logregel uit
`app/logboek.py` komt aan als JSON mét `route`, `document_id`, `stappen_ms`.

| Route | n | stap | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|---|
| `boekvoorstel_checks` (mens) | 35 | `checks.extern` | 20 | 661 | 1.826 | 3.291 |
| | | `checks.duplicaat` | 20 | 194 | 908 | 946 |
| | | `checks.kandidaten` | 20 | 373 | 779 | 1.615 |
| | | `checks.ibanseed` | 20 | 16 | 33 | 605 |
| | | `checks.lokaal` | 35 | 469 | 1.041 | 1.113 |
| | | `checks.cache` | 35 | 46 | 68 | 109 |
| `boekvoorstel_checks_voorverwarm` | 41 | `checks.extern` | 35 | 667 | 2.231 | 3.814 |
| | | `checks.lokaal` | 41 | 804 | 1.897 | 2.308 |
| `boekvoorstel_opslaan` | 50 | `checks.lokaal` | 50 | 466 | 1.771 | 2.229 |
| | | `checks.cache` | 50 | 16 | 92 | 722 |

15 van de 35 mens-checks liepen zonder externe run (cache/lokaal) — de cache doet zijn werk; op 23-09 (17 mens-checks) waren dat er 13.
De doelmeting van 18-09 ("externe rijen ≤ 1,5 s bij voorverwarmd, p95") haalt de p95 nog niet (1,8 s op n=20; de duplicaatquery +
kandidaten zijn de dragers, de IBAN-seed is verwaarloosbaar). Het beslispunt "15 min omhoog" kan nu op échte data wachten (een week
`checks-cache`-onderdeel). Geen `boeken`-route in de set: sinds de deploy 0 × `POST …/boeken` 202 (één 409 op 22-09 08:52Z) — het
trigger-pad meet de zuster-opdracht.

## Gebouwd in deze run

1. **`router.py`** — `IbanAlVertrouwd` → **409** (conflict mét de huidige set); `GeenCrediteurOpVoorstel` blijft 400.
2. **`IbanAccorderingSectie.tsx`** — `isAlVertrouwdAntwoord(err)`: 409 **of** 400 mét de letterlijke tekst (overgangsveilig: oude
   server/nieuwe bundel en omgekeerd tijdens een deploy); `BoekvoorstelPanel.tsx` ongewijzigd.
3. **Tests:** `tests/documenten/test_iban_accordering.py::TestAanbiedenRouteStatuscode` (TestClient: al vertrouwd = 409 + tekst, zonder
   crediteur = 400), gouden-set-casus af `test_af_iban_akkoord_checks_cache.py` toetst nu óók de ROUTE (409) — `test_keten_guard` eiste
   de aanraking; vitest `BoekvoorstelPanel.ibanCache.test.tsx` → `it.each([409, 400])`.
4. **Dispatch-onderdeel `checks-cache`** in `.github/workflows/nameting.yml` (beschrijving, `options:`, uitsluiting VGG-tak, tak,
   `OORDEEL_BRON`) + `via_gh_onderdeel` in `nameting.sh` + guard-regex `test_nameting_workflow.py`: request-log checks/voorverwarm/
   `extern=vers`, `POST …/iban-accordering` per status (201/409/400), `server_timing` regels per route + p50/p95 per stap (python3 op de
   runner; lokaal gedraaid op de echte 126 regels, exit 0), venster 7 dagen, oordeelregel "server_timing N regel(s), extern=vers V,
   iban-accordering 409 A — werkt in productie: ja | ROOD".
5. **Docs:** BESLISSINGEN alinea "Gemeten 23-09", regels-alinea's werkvoorraad-controlescherm + werkloop-productie, CLAUDE.md rij 7
   (één clausule), WAT_IS_NIEUW (klantleesbaar), vervolg-opdracht `opdrachten/inbox/2026-09-24-nameting-iban-wissel-cache-poging-3.md`
   (`niet vóór: 2026-09-24 09:00`, derde en laatste poging vóór `mislukt/`).

Poort: zie de slotregel van de commit (pytest van de geraakte tests + docs-guards, vitest van de geraakte bestanden + changelog,
`tsc -b`, `bash -n` op `nameting.sh` en de meet-stap, YAML-parse). Geen migratie, geen RLZ-write, geen schrijvende productiestap.

## Keuzes (Peter keek niet mee)

- **409 aan de serverkant i.p.v. alleen het scherm op 400 zetten:** de regel van 21-09, BESLISSINGEN en de vitest zeggen letterlijk 409, en
  "IBAN staat al in de set" is een conflict mét de huidige stand (409), geen ongeldige invoer (400). Het scherm herkent tóch beide, zodat
  een bundel van vóór/ná de deploy nooit meer een route dooft op een statuscode; de tekst blijft het contract.
- **Meting 2b "nee" op één voorval zonder gelogde body:** de DB-stand sluit élke andere 400-oorzaak uit; dat de mens waarschijnlijk het al
  bekende IBAN invoerde verandert niets aan het defect (de code kon 409 nooit geven).
- **Dispatch-onderdeel nu wél gebouwd** (22-09 bewust nog niet): tweede "niet gemeten" op dezelfde drie metingen = regel 21-09 (1).
- **Geen Meyer-/audit-sweep in het onderdeel:** `audit_event` mét `administratie_id` heeft geen Beheerder-RLS-clausule (79 job-executies
  voor één sweep is geen meetlat); blijft een owner-sessie-recept. Meyer = klant-accordeur-afhankelijk.
- `.scratch/audit-iban-sweep-23-09*.{sh,log}` blijven untracked als recept/bewijs; `opdrachten/mislukt/2026-09-21-vastly-…` (untracked,
  niet van deze run) is niet aangeraakt.

## Vervolg

`opdrachten/inbox/2026-09-24-nameting-iban-wissel-cache-poging-3.md` (`niet vóór: 2026-09-24 09:00`): `gh workflow run nameting -f
onderdeel=checks-cache` (bewijs 409 → `extern=vers` ≤ 10 s op hetzelfde document), Meyer, akkoord-pad ≥ 1; opnieuw niet gemeten →
`mislukt/` mét klikpunt voor Peter.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/werkvoorraad-controlescherm.md` (401 regels; 413 ná deze run),
`docs/regels/werkloop-productie.md` (306 regels; 319 ná deze run).
