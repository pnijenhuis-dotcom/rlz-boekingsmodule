# Verwerkingsregister (art. 30 AVG) — RLZ Boekingsmodule

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**
> Opgesteld 2026-08-11. Dit register beschrijft de verwerkingen die Administratiekantoor
> Nijenhuis uitvoert **via de RLZ-boekingsmodule**. Verwerkingen buiten de module (papieren
> dossier, e-mailverkeer buiten de intake, loonadministratie in andere pakketten) vallen erbuiten
> en horen in het kantoorbrede register.

## 0. Verantwoordelijke en algemene gegevens

| Veld | Waarde |
|---|---|
| Verwerkingsverantwoordelijke | Administratiekantoor Nijenhuis (rolbepaling: zie [03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md) — het kantoor is voor de administratievoering zelfstandig verwerkingsverantwoordelijke) |
| Contactpersoon | P. Nijenhuis |
| Functionaris gegevensbescherming | n.v.t. (geen FG-plicht verwacht; juridisch toetsen) |
| Verwerkers (via de module) | Anthropic Ireland, Limited (Claude API — AI-extractie; contractspartij EEA), Exact Reeleezee (boekhoudpakket, bron van waarheid), PDL Powerhouse B.V. (eigenaar software + hosting — intra-groep verwerkersovereenkomst, concept [07-verwerkersovereenkomst-pdl.md](07-verwerkersovereenkomst-pdl.md), jurist-akkoord vraag 9 2026-08-12), Google Cloud EMEA Ltd. (hosting/database/documentopslag — subverwerker ván PDL; cloudomgeving staat sinds 2026-08-14, klantdata pas ná de F5-poort), e-mailprovider intake-postvak (volgt bij IMAP-activatie, checklist D) — details en contractstatus: [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md) |
| Doorgifte buiten de EER | Ja, naar de VS (Anthropic Claude API). Zie §9 (doorgifte-/CLOUD Act-notitie) |

## 1. Overzicht verwerkingen

| # | Verwerking | AI betrokken | Status |
|---|---|---|---|
| V1 | Inkoopfactuurverwerking (intake → extractie → controle → boeken in RLZ) | Ja (achter gate, default UIT) | gebouwd |
| V2 | E-mail-intake en toewijzing (verzamelbak, multi-factuur-splitsing) | Ja (zelfde gate) | gebouwd |
| V3 | Omzet-/kassarapportverwerking | Ja (zelfde gate) | gebouwd |
| V4 | Verkoopfactuurverwerking (Vastly-huurfacturen, debiteuren = huurders) | Nee (deterministische UBL-verwerking) | gebouwd |
| V5 | Bankmutatieverwerking en afletteren | Nee | gebouwd |
| V6 | Klant-accordering (accordeurs per administratie) | Nee | gebouwd (PWA volgt) |
| V7 | Gebruikers- en toegangsbeheer + audit log | Nee | gebouwd |

## 2. V1 — Inkoopfactuurverwerking

| Veld | Beschrijving |
|---|---|
| Doel | Verwerken van inkoopfacturen van klant-administraties in Reeleezee: extractie van factuurgegevens, menselijke controle, boeking |
| Grondslag | Uitvoering overeenkomst met de klant (art. 6 lid 1 sub b AVG) en wettelijke verplichting administratie-/bewaarplicht (art. 6 lid 1 sub c AVG jo. art. 52 AWR / art. 2:10 BW) |
| Categorieën betrokkenen | Contactpersonen en eenmanszaak-eigenaren van leveranciers; medewerkers van klanten (namen op facturen/urenstaten); klant-eigenaren |
| Categorieën gegevens | Naam, (bedrijfs)adres, e-mail, telefoonnummer, IBAN, KvK-/btw-nummer, factuur- en betaalgegevens; op urenstaten: namen + gewerkte uren. **BSN's worden nooit geëxtraheerd, geïndexeerd of in AI-output opgenomen** (hard principe; prompt-verbod + deterministisch post-filter `app/extractie/bsn.py`, preview maskeert; brondocument blijft wél bewaard i.v.m. WKA) |
| Ontvangers/verwerkers | Anthropic (alleen bij AI-extractie: documentinhoud gaat naar de Claude API — model `claude-sonnet-5`, config `ai_extractie_model`); Exact Reeleezee (boeking); Google Cloud (na uitrol: opslag/verwerking); Belastingdienst (indirect, via aangiften) |
| Bewaartermijn | 7 jaar (fiscale bewaarplicht), documenten in archief terugvindbaar mét PDF; **PII wordt gepseudonimiseerd ná relatie-einde + 7 jaar, nooit hard verwijderd** (platformbesluit 0004 — AVG-verwijderverzoek = pseudonimiseren) |
| Beveiliging | Zie §8 |

## 3. V2 — E-mail-intake en toewijzing

| Veld | Beschrijving |
|---|---|
| Doel | Centraal ontvangen van boekhoudstukken, splitsen van multi-factuur-PDF's, toewijzen aan de juiste administratie (tenaamstelling leidend) |
| Grondslag | Als V1 |
| Betrokkenen | Afzenders van e-mail (leveranciers, klanten); personen genoemd in bijlagen |
| Gegevens | E-mailadres afzender, Message-ID, bijlagen (facturen/UBL/PDF); niet-PDF/XML-bijlagen worden geregistreerd maar niet verwerkt |
| Ontvangers/verwerkers | Anthropic alléén bij PDF-extractie/splitsingsvoorstel en alléén als de AVG-gate `intake_ai_ingeschakeld` AAN staat (Beheerder-instelling, default UIT, elke wijziging in het audit log); e-mailprovider van het intake-postvak (IMAP — leverancier te bepalen bij GCP-uitrol, zie checklist) |
| Bewaartermijn | Als V1; berichten die "niet bij ons horen" worden afgewezen met reden en blijven zichtbaar geregistreerd (niets verdwijnt stil) |

## 4. V3 — Omzet-/kassarapportverwerking

Als V1, met als bijzonderheid: kassarapporten (bijv. BLOW-margerapporten) bevatten doorgaans
géén persoonsgegevens van derden; de AI leest periode/categorieën/bedragen voor, een
deterministische controlelaag rekent alles na (geen LLM in geldberekeningen). Boeking als
entity-loze Receipt + kostprijsmemoriaal in RLZ.

## 5. V4 — Verkoopfactuurverwerking (Vastly, §2d koppelcontract)

| Veld | Beschrijving |
|---|---|
| Doel | Boeken van Vastly-huurfacturen als SalesInvoice op de échte huurder als RLZ-debiteur (idempotente debiteur-aanmaak uit de UBL) |
| Grondslag | Als V1 |
| Betrokkenen | **Huurders van vastgoed-administraties** (ook consumenten — consument-facturen landen met vlag "consument-afnemer") |
| Gegevens | Naam, adres, factuurbedragen, betaalstatus van huurders; waarborg-gegevens (VASTLY-WAARBORG-berichten) |
| Ontvangers/verwerkers | Exact Reeleezee; vastgoedmodule (webhook `factuur_geboekt`/`factuur_afgeletterd` — platform-intern, HMAC-beveiligd); **géén AI** (deterministische UBL-verwerking) |
| Bewaartermijn | Als V1 |

## 6. V5 — Bankmutatieverwerking en afletteren

| Veld | Beschrijving |
|---|---|
| Doel | Ophalen van bankmutaties uit RLZ (PaymentTransactions), matchen/afletteren tegen open posten, direct-op-grootboek boeken |
| Grondslag | Als V1 |
| Betrokkenen | Rekeninghouders van tegenrekeningen (betalers/ontvangers van klanten, incl. particulieren, bijv. huurders) |
| Gegevens | Tegenrekening-IBAN, tenaamstelling, omschrijving (kan vrije-tekst-PII bevatten), bedrag, datum. **G-rekening-/WKA-context**: gesplitste betalingen zijn standaard-case |
| Ontvangers/verwerkers | Exact Reeleezee (bron van de mutaties); **géén AI** — matching is deterministisch (exacte match, regels, geheugen) |
| Bewaartermijn | Als V1 |

## 7. V6 + V7 — Accordering, gebruikers- en toegangsbeheer, audit

| Veld | Beschrijving |
|---|---|
| Doel | Toegangsbeheer medewerkers en klant-accordeurs; klant-accordering van boekingen; verantwoording (append-only audit log als bron voor de WORM-export) |
| Grondslag | Uitvoering overeenkomst (accordeurs), gerechtvaardigd belang beveiliging/verantwoording (art. 6 lid 1 sub f), wettelijke verplichting (administratieve verantwoording) |
| Betrokkenen | Medewerkers kantoor; klant-accordeurs |
| Gegevens | Naam, e-mailadres, wachtwoord-hash, TOTP-secret (versleuteld), rol- en scope-toekenningen, sessies (JWT/refresh-tokens), audit-events (wie/wat/wanneer/oud→nieuw, correlatie-id) |
| Ontvangers | Google Cloud (na uitrol); niemand extern |
| Bewaartermijn | Accounts: duur dienstverband/relatie + pseudonimisering conform besluit 0004. Audit log: append-only, bewaartermijn gelijk aan de administratie (7 jaar); **PII gescheiden van financiële data** zodat pseudonimisering het audit-spoor niet breekt |

## 8. Technische en organisatorische maatregelen (gebouwd)

- **Toegang**: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + verplichte TOTP-2FA;
  rollenmodel per module (platformbesluit 0019); klanten-scope per medewerker via
  koppeltabel, afgedwongen door Row-Level Security op DB-niveau (`SET LOCAL` per transactie)
  + server-side checks — geen scope = geen data, ook niet via bugs in de app-laag. Niemand
  kan zijn eigen rol/scope muteren.
- **Audit**: append-only `audit_event` op elke handeling (uniform platformschema, besluit 0004),
  bron voor de WORM-export; rol-/scope-wijzigingen en gate-wijzigingen altijd gelogd.
- **Secrets/credentials**: RLZ-credentials server-side versleuteld (envelope encryption, master
  key buiten de database; op GCP: KMS-gewrapte data-keys via Secret Manager); secrets nooit in
  code, git of logs (platformbesluit 0012).
- **AI-specifiek**: AVG-gate `intake_ai_ingeschakeld` default UIT (Beheerder-instelling,
  migratie 0029, bevestigdialoog + audit); BSN-hardregel (prompt-verbod + deterministisch
  post-filter vóór persistentie + preview-maskering); mens-in-de-lus op elke boeking
  (automatisch boeken = opt-in per leverancier/administratie met harde blokkerende checks);
  code voor cijfers — geen LLM in geldberekeningen.
- **Dataminimalisatie richting AI**: alleen documentinhoud die voor extractie nodig is;
  zoeken gebruikt uitsluitend lokaal aanwezige extractietekst (bewust geen nieuwe AI-calls).
- **Integriteit**: idempotentie overal (client-GUID's, duplicaatchecks); niets verdwijnt stil
  (afwijzen = verplichte reden; API-fout = zichtbare foutstatus + retry).
- **Pseudonimisering**: PII gescheiden van financiële data; verwijderverzoek = pseudonimiseren
  ná relatie-einde + 7 jaar (besluit 0004).
- **Hosting (werkelijke cloudconfiguratie, geverifieerd 2026-08-14 — klantdata pas ná de
  F5-poort):** Google Cloud-project `rlz-boekhouding` (PDL Powerhouse-organisatie), alles in
  `europe-west4`, geborgd door een **Organization Policy op EU-locaties**
  (`constraints/gcp.resourceLocations`, effectief op het project — describe-bewijs in het
  F5-poortdossier). **Cloud SQL** PostgreSQL 16 REGIONAL (HA) met PITR (7 dagen
  transactielogs) + dagelijkse backups 02:00. **Cloud Storage-bucket**
  `rlz-boekhouding-documenten`: retentiebeleid 7 jaar (220.903.200 s, *unlocked* —
  GCP-beslispunt 7), versioning aan, public-access-prevention enforced, uniform
  bucket-level access. **Cloud KMS** keyring `rlz`, key `masterkey` (jaarrotatie): de
  envelope-encryptie van de credential-store draait op KMS-gewrapte data-keys
  (`KmsMasterKeyProvider`); overige secrets in **Secret Manager** (replicatie
  `europe-west4`). Toegang via least-privilege service-accounts (aparte runtime-SA's
  service/jobs, deploy via Workload Identity Federation zonder langlevende keys).
  Achtergrondwerk via Cloud Scheduler + Cloud Run-jobs mét job-failure-alerting.
  Lokale dev via Docker Compose. **CMEK: actief (besluit 0021, akkoord Peter 2026-08-14)** —
  Cloud SQL herbouwd als `rlz-sql2` mét CMEK-key `cmek-sql`, documentenbucket met
  default-CMEK-key `cmek-documenten` (beide op keyring `rlz`, jaarrotatie, nooit destroy);
  zie §9 punt 2 en het F5-poortdossier punt 3 voor het describe-bewijs.

## 9. Doorgifte- en CLOUD Act-notitie

1. **Anthropic (Claude API)** — contractspartij voor EEA-klanten is **Anthropic Ireland,
   Limited** (Commercial Terms of Service, versie effective 17-06-2025, gearchiveerd
   2026-08-14), maar de **verwerking zelf vindt plaats in de VS** (geen EU-verwerkingsregio
   voor de standaard API; stand webverificatie 2026-08-11). Grondslag doorgifte: de EU
   Standard Contractual Clauses (2021) in Anthropics DPA (versie effective 24-02-2025,
   gearchiveerd 2026-08-14; module 2 controller→processor). De gearchiveerde Terms
   bevestigen: **geen training op Customer Content** (§B). **Zero data retention:
   aangevraagd, loopt** (status 2026-08-14) — uitkomst archiveren in de checklist;
   DPF-registercheck op Anthropic staat nog open (actie Peter, checklist A). Mitigaties:
   gate default UIT, BSN-filter, dataminimalisatie, AI-kostengrens met fail-closed poort.
2. **Google Cloud** — verwerking in `europe-west4` (Nederland), maar Google LLC valt als
   Amerikaanse moeder onder de CLOUD Act: Amerikaanse autoriteiten kunnen in uitzonderlijke
   gevallen verstrekking vorderen, ook van EU-data. Dit risico is **geaccepteerd bij
   platformbesluit 0003 (2026-07-04) mét een contractueel herzieningsmoment vóór go-live.
   Dat herzieningsmoment is uitgevoerd:** platformbesluit 0021 (memo 2026-08-14, **akkoord
   Peter + uitvoering 2026-08-14** —
   `Platform/besluiten/0021-cmek-clientside-documentversleuteling.md`): **CMEK actief** —
   Cloud SQL herbouwd als `rlz-sql2` mét CMEK (key `cmek-sql`) vóór de klantdata-migratie,
   default-CMEK-key `cmek-documenten` op de documentenbucket (nieuwe objecten; alleen het
   F1-verificatie-testobject blijft Google-default — geen klantdata, gedocumenteerd);
   client-side documentversleuteling alleen op expliciet klantverzoek. NB het besluit
   benoemt eerlijk dat CMEK zeggenschap/intrekbaarheid en audit toevoegt, geen absolute
   CLOUD-Act-immuniteit (de key blijft in Cloud KMS).
   Doorgifte-grondslag voor eventuele support-toegang vanuit de VS: SCC's in Googles Cloud
   Data Processing Addendum + EU-U.S. Data Privacy Framework (Google is DPF-gecertificeerd
   sinds september 2023). CDPA-versie + acceptatiedatum archiveren = actie Peter
   (checklist B).
3. **Exact Reeleezee** — Nederlandse leverancier, hosting in de EU (bevestigen bij het
   opvragen van de actuele verwerkersovereenkomst — zie checklist; de Exact-MKB-PDF's
   versie 1.5/2021 + bijlage 1.6/2022 zijn gearchiveerd in `docs/`, toepasselijkheid op
   Reeleezee-abonnementen nog door Exact te bevestigen).
4. **E-mailprovider intake-postvak** — wordt pas verwerker bij activering van de live
   IMAP-fetch (keuze: bestaande kantoor-mailprovider, GCP-beslispunt 5); DPA-check
   (checklist D) is een harde voorwaarde vóór activering — tot die tijd is de .eml-upload
   het kanaal en is er geen doorgifte.

## 10. Rechten van betrokkenen

Inzage-, correctie- en bezwaarverzoeken lopen via het kantoor (verantwoordelijke).
Verwijderverzoeken: gegevens die onder de fiscale bewaarplicht vallen kunnen niet vernietigd
worden zolang die termijn loopt; na relatie-einde + 7 jaar wordt gepseudonimiseerd
(besluit 0004). De klantovereenkomst informeert betrokkenen via de klant (zie tekstblok in
[03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md)).
