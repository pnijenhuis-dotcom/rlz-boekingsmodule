# F4-activatie-runbook — koppelvlak vastgoed

> **Doel:** de volledige activatie van het webhook-koppelvlak met vastgoed in ≤ 1 werkdag,
> zodra vastgoed hun cutover-moment heeft (hun backend live op `api.vastly.software`).
> Alles hieronder t/m stap 0 is voorbereid; de stappen 1–8 zijn de cutover-dag zelf.
>
> **Canoniek:** dit runbook (uitvoering) + `docs/GCP_UITROL.md` §F4 (fasering) +
> Platform/OPEN_ITEMS.md "F4-cutover-pakket" (wat vastgoed aanlevert).
> Geschreven 2026-08-14 (F4-voorbereiding); beslispunt 9 (alleen Rubicon) verwerkt.

## UITVOERING MA 24-08-2026 — VOLLEDIG AFGEROND (avondsessie 24-08 ~21:20)

**Uitgevoerd door Code (opdracht Peter 24-08, ochtend + avond); details + eindrapport in
BESLISSINGEN "F4-CUTOVER 24-08".** Stand per stap:

- **Stap 8 (deploy-editie) UITGEVOERD, aangepast aan de SA-grant-route + tranche 2:**
  `PROJECTAANVRAAG_HMAC_SECRET` gemount op de service; afleveraar-job uit de F3-lus met
  eigen blok — `WEBHOOK_HMAC_SECRET` = cross-project-verwijzing naar Vastly's slot
  `WEBHOOK_RLZ_SECRET` in `vastly-504108` + `WEBHOOK_DOEL_URL=https://api.vastly.software/
  webhooks/rlz` alléén op die job. ⚠️ LES: cross-project-secretpaden vereisen het
  projectNÚMMER (755625271889), het project-id weigert gcloud. Config óók direct via
  gcloud live gezet (de hook-push vuurt pas ná de run; eerstvolgende deploy is idempotent).
  De stappen 2/3 (.env-route lokale afleveraar) zijn met tranche 2 VERVALLEN.
- **Kanaaltest inkomend (stap 7) GROEN** tegen het productiedomein: geldig secret → 404
  `administratie_onbekend`, fout secret → 401, oude timestamp → 400.
- **Backlog (stap 4): 3 rijen** (alle `factuur_geboekt`, TEST-administratie, schema ≤1.1)
  — **alle 3 AFGELEVERD** (één na een read-timeout-retry). NB volgorde-afwijking: de
  is_vastgoed-vlag van stap 7 is vóór de eerste run aangezet, anders had de afleveraar de
  TEST-backlog zichtbaar geweigerd ("geen vastgoed-administratie") en landde er niets.
- **Stap-4-negatieftest (dummy-secret) VERVALLEN (besluit in de opdracht 24-08):** de
  HMAC-weigering aan Vastly-kant is al bewezen (ongetekende POST → 401, hun poortcheck)
  en een dummy-waarde in het gemounte vastly-secret is niet aan de orde via de SA-grant-route.
- **Stap 5 (toggle) AAN** (beheerder p.nijenhuis@kempengroep.nl, geauditeerd).
- **Stap 7 uitgaand — AFGEROND (avondsessie 24-08, ná vastgoeds 1.2-fix dezelfde dag):**
  TEST-boeking geslaagd (`TEST-F4-CUTOVER-2408`, outbox `factuur_geboekt` volgnummer 1,
  schema 1.2); de ochtend-weigering ("Onbekende schema_version '1.2'") liep na 8 pogingen
  in dead-letter → **redrive + afleveraar-job-run = 200 afgeleverd** (1 poging,
  19:14:40 UTC). **Storno-deel uitgevoerd**: actie 19 via de echte bouwstenen
  (aangifte-poort vrij → `correct_purchase_invoice` → RLZ-status 1 geverifieerd) →
  `factuur_gestorneerd` volgnummer 2 op hetzelfde rlz_document_id, bron `module_storno`,
  reden "F4-cutover-verificatie" (eigen schema 1.0) → **200 afgeleverd** (1 poging,
  19:17:48 UTC). Het gestorneerde TEST-document blijft staan (nooit verwijderen);
  `is_vastgoed` TEST-administratie terug **UIT** (geauditeerd, actor Peters beheerder-id).
- **Stap 6 (tier-vlag) UITGEVOERD ná de geslaagde stap 7: `afgeletterd_event_ingeschakeld`
  AAN — alleen Rubicon** (`35d106f2-…`, beslispunt 9; geauditeerd). ⚠️ Events ontstaan pas
  bij de eerstvolgende bank-sync-detectie én zolang Rubicon `is_vastgoed=False` staat
  vuurt er niets: de is_vastgoed-omschakeling per administratie is het **S2-klikwerk van
  Peter mét Vastly** (koppeling entiteiten + kostenintake aan hun kant) — bewust geen
  onderdeel van deze run.
- **Restpunt (geen blocker):** Vastly's mailbox-afzenderlijst per verhuurder (hun 4a) —
  open in Platform/OPEN_ITEMS.

## De twee kanalen

| | Uitgaand (webhooks) | Inkomend (route A) |
|---|---|---|
| Endpoint | vastgoeds `POST /webhooks/rlz` | ons `POST /koppelvlak/vastgoed/projectaanvragen` |
| Events | `factuur_geboekt` (schema 1.1), `factuur_gestorneerd` (1.0), `factuur_afgeletterd` (2.0, tier-vlag) | `projectaanvraag` (schema 1.0, synchroon antwoord) |
| Secret | `WEBHOOK_HMAC_SECRET` — **vastgoed levert** | `PROJECTAANVRAAG_HMAC_SECRET` — **wij genereren** (f4_koppelvlak.sh) |
| Wie tekent | wij (afleveraar, per verzendpoging) | vastgoed |
| Draait waar | de webhook-afleveraar bij de **werk-DB** — tot datamigratie-tranche 2 is dat de **lokale** backend (uitgaande https volstaat); de cloud-job `rlz-webhook-afleveraar` neemt het over bij tranche 2 | de **cloud-service** `rlz-backend` (moet publiek bereikbaar zijn — lokaal is geen optie) |
| Failsafe zonder config | outbox-rijen blijven openstaand, geen fout (`haal_aflever_config_op` → None) | endpoint weigert zichtbaar met 503 `niet_geconfigureerd` (fail-closed, getest) |

De secrets zijn bewust twee verschillende (config.py): compromittering van de één raakt de
ander niet. **Nooit hergebruiken.**

## Wat al klaarstaat (geverifieerd 2026-08-14)

- Secret Manager: `WEBHOOK_HMAC_SECRET`-container bestaat (0 versies — bewust), accessors
  run-backend@ + run-jobs@. `PROJECTAANVRAAG_HMAC_SECRET`-container ontbrak nog —
  `scripts/gcp/f4_koppelvlak.sh` (stap 0) dicht dat gat.
- Config-paden: `settings.webhook_hmac_secret`/`settings.webhook_doel_url` →
  afleveraar; `settings.projectaanvraag_hmac_secret` → inkomend endpoint. Buiten dev géén
  fallback: afleveraar-run zonder secret/URL = rijen blijven openstaand; inkomend endpoint
  zonder secret = 503 (fail-closed-tests in `tests/projecten/test_koppelvlak.py`).
- Kanaaltest-gereedschap: `scripts/f4_kanaaltest.py` (stdlib, tekent zelf conform §5) —
  hmac-modus zonder side-effects live geverifieerd tegen de dev-backend.
- Tier-vlag-CLI: `make afgeletterd-event-aan/-uit`; toggle-CLI `make
  webhook-aflevering-aan/-uit`; herstel `make webhook-redrive`.

## Cutover-moment (DEFINITIEF — bevestiging Peter mét Vastly 21-08)

**F4-cutover = maandag 24-08-2026** (uitloop di 25-08), ná datamigratie-tranche 2 op
za 22 / zo 23-08 (`docs/TRANCHE2_DRAAIBOEK.md`; freeze za 22-08 09:00). De eerder door
vastgoed gesignaleerde datum-mismatch is opgelost met lezing A (weekdagen leidend).
Facturatiestart vastgoed blijft de kalendergrens 1 september.

## Update vastgoed 21-08 (OPEN_ITEMS "Bevestigingsronde 21-08" + vastgoed-antwoord — verwerkt)

- **Uitgaand: de SA-grant-route is de werkende route.** Vastgoeds slot heet
  **`WEBHOOK_RLZ_SECRET`** in `vastly-504108` (⚠️ naamverschil met ons env-label
  `WEBHOOK_HMAC_SECRET` — zelfde waarde); accessor-grants voor onze `run-backend@` +
  `run-jobs@rlz-boekhouding` STAAN én zijn door vastgoed geverifieerd (herbevestigd in de
  definitieve bevestigingsronde 21-08; één enabled versie).
  Deploy-editie (stap 8) draagt dus
  `projects/vastly-504108/secrets/WEBHOOK_RLZ_SECRET:latest`. Waardevrij te controleren:
  `gcloud secrets get-iam-policy WEBHOOK_RLZ_SECRET --project=vastly-504108`. NB tot
  tranche 2 draait de afleveraar lokaal → de .env-waarde blijft dan nodig (stap 2).
- **Inkomend: slotnaam definitief — zelfde naam aan beide kanten, wij leveren de
  VOLLEDIGE waarde (geen helften te combineren).** Vastgoed maakt op de cutover-dag
  `PROJECTAANVRAAG_HMAC_SECRET` aan in `vastly-504108` (user-managed `europe-west4`,
  accessor `run-backend@vastly-504108`); het slot bestaat daar 21-08 nog níét. Ons
  store-naar-store-plakcommando is **getoetst en goedgekeurd** (byte-veilig:
  f4_koppelvlak.sh schrijft met `printf '%s'`, geen newline):
  `gcloud secrets versions access latest --secret=PROJECTAANVRAAG_HMAC_SECRET
  --project=rlz-boekhouding | gcloud secrets versions add PROJECTAANVRAAG_HMAC_SECRET
  --project=vastly-504108 --data-file=-` — controle zonder waarde tonen: SHA-256 van
  `versions access` in beide projecten vergelijken; **vastgoed heeft die
  SHA-256-vergelijking als newline-vangnet klaarstaan** (bevestigd 21-08).
- **Poort-beginstand vastgoed live geverifieerd 21-08:** `/health` → 200; ongetekende
  `POST /webhooks/rlz` → 401.
- **Vastgoeds ochtend-draaiboek** = checklist **3.3c-RLZ** in
  `Vastgoed software/docs/HOSTING_SEPTEMBER.md` (losgetrokken van hun september-go-live).
- **Datum-mismatch OPGELOST (bevestiging Peter mét Vastly 21-08):** lezing A geldt —
  tranche 2 za 22 / zo 23-08, **F4-cutover ma 24-08** (uitloop di 25-08). Zie de kop
  "Cutover-moment" hierboven.

## Stap 0 — kan vandaag al (Peter, ~5 min)

```
bash scripts/gcp/f4_koppelvlak.sh
```

Idempotent: maakt de `PROJECTAANVRAAG_HMAC_SECRET`-container + accessor (alleen
run-backend@ — least privilege, geen enkele job leest dit secret), genereert desgewenst
meteen onze inkomende secret-waarde, en biedt het `WEBHOOK_HMAC_SECRET`-versieveld aan
(Enter = overslaan tot de uitwisseling). Slot print welke slots een versie hebben.

## Cutover-dag

### Stap 1 — ontvangst van vastgoed (~checklist, zie OPEN_ITEMS "F4-cutover-pakket")

1. Definitieve endpoint-URL (verwacht: `https://api.vastly.software/webhooks/rlz` — exact
   bevestigen).
2. Hun `WEBHOOK_HMAC_SECRET`-helft: als waarde (veilig kanaal via Peter) óf als Secret
   Manager-verwijzing in `vastly-504108` (accessor voor onze run-SA's).
3. Bevestiging dat hun ontvanger live staat mét: schema-**1.1**-verwerker (volgnummer),
   `factuur_gestorneerd`-verwerker, nonce-dedup + replay-venster actief.
4. Wij geven terug: onze inkomende URL
   (`https://app.administratiekantoornijenhuis.nl/koppelvlak/vastgoed/projectaanvragen`)
   + het gegenereerde `PROJECTAANVRAAG_HMAC_SECRET` (ophalen:
   `gcloud secrets versions access latest --secret=PROJECTAANVRAAG_HMAC_SECRET`; overdracht
   door Peter, nooit chat/git).

### Stap 2 — secrets zetten (Peter, ~15 min)

- **Uitgaand, eenvoudige route (aanbevolen zolang de afleveraar lokaal draait):** waarde in
  ons eigen secret (`bash scripts/gcp/f4_koppelvlak.sh` nogmaals, of `gcloud secrets
  versions add WEBHOOK_HMAC_SECRET --data-file=-`) **én** in de lokale
  `backend/.env`: `WEBHOOK_HMAC_SECRET=…` — de lokale afleveraar leest alleen .env.
- **Alternatief (ontvangstvoorkeur GCP_UITROL §F4.1):** verwijzing naar het secret in
  `vastly-504108` — dan draagt de deploy.yml-editie (stap 8) het volledige resource-pad
  `projects/vastly-504108/secrets/<naam>:latest`; lokaal blijft de .env-waarde nodig tot
  tranche 2.
- **Inkomend:** in stap 0 gegenereerd; niets lokaal nodig (het endpoint draait alleen in
  de cloud-service).

### Stap 3 — doel-URL zetten (lokaal, ~5 min)

`backend/.env`: `WEBHOOK_DOEL_URL=<URL uit stap 1>` → backend herstarten (`make run`).

### Stap 4 — backlog-inventarisatie + negatieftest uitgaand (aanbevolen, ~20 min)

⚠️ **De toggle staat sinds 2026-08-02 uit; alle sindsdien ontstane outbox-rijen worden bij
activatie alsnog afgeleverd** (bedoeld gedrag: tekenen gebeurt per verzendpoging, dus de
handtekeningen zijn vers). Vooraf: tel de openstaande rijen
(`SELECT status, count(*) FROM boekhouding.webhook_uitgaand GROUP BY status;`) en meld het
aantal aan vastgoed — de volgnummers ordenen de backlog aan hun kant.

Negatieftest (bewijst dat vastgoed écht verifieert én dat niets stil wegvalt): zet eerst
bewust een dummy-`WEBHOOK_HMAC_SECRET` in .env → `make webhook-aflevering-aan
BEHEERDER_ID=…` → `make webhook-afleveren` → verwacht: 401-antwoorden, rijen blijven
openstaand mét zichtbare foutstatus. Daarna het echte secret in .env → volgende run levert
alles alsnog geldig af.

### Stap 5 — toggle aan + eerste aflevering (~15 min)

```
make webhook-aflevering-aan BEHEERDER_ID=<uuid>
make webhook-afleveren
```

Rapport controleren: geslaagd/gefaald per rij; dead-letters herstellen met
`make webhook-redrive BEHEERDER_ID=<uuid>` (optioneel `OUTBOX_ID=`).

### Stap 6 — tier-vlag `afgeletterd_event_ingeschakeld` (~5 min)

**Alleen Rubicon** (beslispunt 9; uitbreiding per onboarding-moment, geen bulk):

```
make afgeletterd-event-aan ADMIN_ID=<Rubicon-administratie-id> BEHEERDER_ID=<uuid>
```

Pas zetten nadat vastgoed de 2.0-verwerker bevestigt (stap 1.3); events ontstaan daarna
bij de eerstvolgende bank-sync-detectie. NB open punt uit BESLISSINGEN: de detectie dekt
nu inkoopfacturen — huurontvangsten (verkoopdocumenten) zijn het benoemde vervolg.

### Stap 7 — verificatie per kanaal (~45 min)

**Uitgaand — één gecontroleerde boek/storno-cyclus dekt beide event-types:**
1. `is_vastgoed` tijdelijk AAN op de RLZ-TEST-administratie (patroon route-A-verificatie).
2. TEST-referentie-inkoopfactuur boeken → outbox-rij → aflevering 200; vastgoed bevestigt
   verwerking (`factuur_geboekt`, volgnummer klopt).
3. Storno (actie 19, reden verplicht) → `factuur_gestorneerd` (bron `module_storno`, direct)
   → vastgoed bevestigt.
4. `is_vastgoed` weer UIT; het gestorneerde TEST-document blijft staan (nooit verwijderen).
- HMAC-weigering uitgaand: gedekt door de stap-4-negatieftest. Nonce-replay-weigering aan
  hun kant: vastgoed bevestigt (hun ontvanger-tests dekken het; desgewenst één
  curl-herhaling van een door hen gelogd request).

**Inkomend — `scripts/f4_kanaaltest.py`:**
- Zonder side-effects, tegen de cloud (na stap 8):
  `PROJECTAANVRAAG_HMAC_SECRET=… python3 scripts/f4_kanaaltest.py --url
  https://app.administratiekantoornijenhuis.nl` — toetst geldig secret (→ 404
  administratie_onbekend), fout secret (→ 401) en replay-venster (→ 400).
- End-to-end (`--mode volledig --administratie-id <TEST-administratie>`) is al
  live geverifieerd op 2026-08-14 (route A) en herhaalt zinvol pas wanneer de
  werk-DB in de cloud draait (tranche 2) — zie de kanttekening hieronder.

### Stap 8 — cloud-config: deploy.yml-editie (Code, ~30 min)

**Voorwaarde: beide secrets hebben een versie** — een gemount secret zonder versie laat de
revisie-start/job-executie falen (dat is waarom dit een activatie-editie is en niet vooraf
klaargezet). Wijzigingen in `.github/workflows/deploy.yml`:

1. Service `rlz-backend`, `--set-secrets`: toevoegen
   `,PROJECTAANVRAAG_HMAC_SECRET=PROJECTAANVRAAG_HMAC_SECRET:latest`.
2. Job `rlz-webhook-afleveraar`: uit de F3-jobs-lus halen en een eigen deploy-blok geven
   met extra `--set-secrets …,WEBHOOK_HMAC_SECRET=WEBHOOK_HMAC_SECRET:latest` en
   `WEBHOOK_DOEL_URL=<URL>` in de env-vars (alleen déze job — least privilege).
3. Push naar main → deploy draait → kanaaltest hmac-modus tegen de cloud-URL (stap 7).

De cloud-afleveraar-job blijft functioneel een no-op zolang de cloud-DB de werk-DB niet is
(toggle daar staat UIT, er zijn geen outbox-rijen) — de editie zorgt dat 'm bij tranche 2
niets meer ontbreekt.

## Kanttekening: route A end-to-end vóór tranche 2

Het inkomende kanaal is pas écht in bedrijf als de aangeroepen backend de administratie
kent (is_vastgoed-rij + RLZ-credentials in de credential-store van díé database). Tot
datamigratie-tranche 2 heeft de cloud-DB alleen het schema. **Besluit bij cutover:** óf
route-A-livegang meekoppelen aan de kantoor-omschakeling naar de cloud (aanbeveling —
één werk-DB, geen split-brain), óf bewust de vastgoed-administraties vervroegd in de
cloud-DB onboarden (eigen kantoordata mag vóór F5). Secrets, kanaal-verificatie en
vastgoeds bouwwerk kunnen hoe dan ook nu al volledig af — vastgoed merkt het verschil
alleen aan een 404 `administratie_onbekend` tot de administratie er is, en precies
dat antwoord is veilig herhaalbaar (idempotent `bericht_id`, geen side-effects).

## Rollback

- Uitgaand: `make webhook-aflevering-uit BEHEERDER_ID=…` — rijen blijven openstaand,
  niets gaat verloren; dead-letters later herstellen met `make webhook-redrive`.
- Tier-vlag: `make afgeletterd-event-uit ADMIN_ID=… BEHEERDER_ID=…`.
- Inkomend: secret-versie disablen (`gcloud secrets versions disable`) = endpoint
  weigert fail-closed met 503 zodra de revisie herstart; netter is vastgoed de aanroepen
  laten pauzeren (herleveren met zelfde `bericht_id` is altijd veilig).
- Secret-rotatie: nieuwe versie + beide kanten op hetzelfde moment omzetten (het kanaal
  verifieert tegen exact één secret — er is bewust geen dual-key-venster gebouwd).

## Tijdsbegroting (≤ 1 werkdag)

| Stap | Wie | Duur |
|---|---|---|
| 0 (vooraf) | Peter | 5 min |
| 1 uitwisseling | Peter + vastgoed | 30 min |
| 2–3 secrets + URL | Peter | 20 min |
| 4 backlog + negatieftest | Code + Peter | 20 min |
| 5 toggle + eerste aflevering | Code | 15 min |
| 6 tier-vlag Rubicon | Code | 5 min |
| 7 verificatie beide kanalen | Code + vastgoed | 45 min |
| 8 deploy.yml-editie + cloud-check | Code | 30 min |
| **Totaal** | | **~3 uur** (ruim binnen 1 werkdag; marge voor vastgoed-afstemming) |
