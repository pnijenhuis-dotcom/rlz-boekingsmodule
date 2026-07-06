# Update RLZ-boekingsmodule → Vastgoedproject (2026-07-04)

> Reactie op koppelcontract v1.2 (hostwijziging Google Cloud, vastgoed-commit 1bc8658).
> Ter kennisname + drie afstemmingspunten. Koppelvlak ongewijzigd; niets blokkeert.

## 1. Bevestiging

De RLZ-boekingsmodule **gaat mee** naar Google Cloud `europe-west4`: eigen Cloud Run-service,
schema `boekhouding` in de gedeelde Cloud SQL-instance (HA + PITR), secrets via Google Secret
Manager. Bevestiging staat in `11_KOPPELCONTRACT_DEFINITIEF.md` v1.2 (§2b), met onze aanvullingen:

- **Cloud Storage** (europe-west4, retentiebeleid) voor documentopslag — facturen/PDF's, 7 jaar
  bewaarplicht. Relevant voor jullie: huurcontracten/DocuSign-documenten kunnen hetzelfde patroon
  gebruiken.
- **Cloud Scheduler + Cloud Run jobs** voor achtergrondwerk (Cloud Run-services zijn
  request-gedreven; dagelijkse signalering/sync draait anders nooit). Geldt ook voor jullie
  indexatieruns en bankimports.
- **CLOUD Act-herzieningsmoment**: onze inbreng genoteerd — de boekingsmodule bevat volledige
  boekhouddata van tientallen kantoorklanten; mitigaties CMEK / client-side documentversleuteling
  daar beoordelen.

## 2. Platform-verbeteringen die wij hebben vastgesteld (relevant voor het gedeelde fundament)

Volledige lijst met fasering in ons `docs/BOUWPLAN.md`. Drie zijn **platform-breed** en willen we
gelijk trekken zodat beide modules één patroon delen:

| # | Verbetering | Waarom gedeeld |
|---|-------------|----------------|
| 1 | **Audit log-export met bucket retention lock (WORM)** | het audit log is een gedeelde platformvoorziening; onvervalsbaarheid geldt voor beide modules (jullie financiële acties net zo goed) |
| 2 | **Schrijfacties naar externe systemen via Cloud Tasks-queue** (idempotency-key = taaknaam, dead-letter → zichtbare foutstatus) | jullie RLZ-outbound (huurfacturen, waarborg) heeft exact hetzelfde risico op dubbelboeken bij retries; één queue-patroon voor beide |
| 3 | **Secret-rotatieproces** voor RLZ-webservice-logins (halfjaarlijks, gelogd) | de credential-store is gedeeld; rotatie moet dat ook zijn |

Module-intern bij ons (ter info, geen actie jullie kant): staging-omgeving per module
(scale-to-zero), Cloud DLP als BSN-vangnet op documenten, extractiekwaliteit-meting uit menselijke
correcties, signed URLs voor documenttoegang, monitoring-alerts (RLZ-foutpercentage,
sync-achterstand, dead-letter, budget). Neem over wat bruikbaar is — met name signed URLs is voor
jullie huurdersportaal vermoedelijk net zo relevant.

Bewust afgewezen (niet opnieuw agenderen zonder nieuw argument): Kubernetes, microservices binnen
een module, multi-region, AlloyDB voor transactionele modules.

## 3. Gevraagde afstemming (geen blokkade)

1. Akkoord dat de drie platform-brede punten (WORM-audit, Cloud Tasks-patroon, secret-rotatie)
   in het gedeelde fundament landen i.p.v. per module verschillend?
2. Wie richt het GCP-project/IAM-basisstructuur in (service account per module, least privilege)?
   Voorstel: één keer gezamenlijk opzetten vóór onze fase 1-deploy.
3. Ons webhook-endpoint-contract ("factuur geboekt", §3 koppelcontract) krijgt request-signing
   (HMAC met key uit Secret Manager) — graag jullie ontvangst-endpoint daarop voorbereiden.

— RLZ-boekingsmodule, 2026-07-04
