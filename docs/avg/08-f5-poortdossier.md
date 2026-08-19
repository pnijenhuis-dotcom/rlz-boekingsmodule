# F5-poortdossier — go-live-gate vóór echte klantdata (afvinkbaar)

> **Doel:** dit is het bewijsdossier voor de F5-poort uit `docs/GCP_UITROL.md` §F5
> (= AVG-activatie-checklist **stap 2, integraal** — `05-activatie-checklist.md`).
> Er gaat **geen enkele echte klantadministratie** de cloud in vóór álle acht punten
> hieronder op ✅ staan (besluit Peter 2026-08-12). Per punt: bewijs/vindplaats + wie +
> status. Aangemaakt 2026-08-14 (F5-voorbereiding); dit bestand is de canonieke
> afvinkplek — status hier bijwerken, niet in kopieën.

## Statusoverzicht

| # | Poortpunt | Wie | Status |
|---|---|---|---|
| 1 | Google Cloud CDPA geaccepteerd, versie + datum gearchiveerd | Peter | ✅ 2026-08-15 — versie 8 juni 2026, `nl-cloud-data-processing-addendum-customers.pdf` |
| 2 | Regio-borging aantoonbaar (`europe-west4` + EU-org-policy) | Code | ✅ 2026-08-14 |
| 3 | Herzieningsmoment CLOUD Act (besluit 0003): CMEK/client-side beoordeeld, uitkomst als platformbesluit | Code (memo) + Peter (besluit) + beiden (uitvoering) | ✅ besluit 0021 (akkoord 2026-08-14) + uitgevoerd 2026-08-14 |
| 4 | Retentie/PITR-instellingen gedocumenteerd | Code | ✅ 2026-08-14 |
| 5 | Verwerkersovereenkomst Exact Reeleezee bevestigd + gearchiveerd | Peter | ✅ 2026-08-15 — bevestiging Exact 2026-08-14, `Bevestiging versie RLZ.pdf` |
| 6 | IMAP-provider-DPA rond (checklist D) | Peter | ✅ 2026-08-15 — Google Workspace; geldende DPA = de al gearchiveerde CDPA (punt 1, dekt Workspace expliciet) |
| 7 | Verwerkingsregister §8/§9 bijgewerkt op de werkelijke cloudconfiguratie | Code | ✅ 2026-08-14 |
| 8 | Identiteit-eerst-check afgerond genoteerd (uit F0) | Peter (uitgevoerd) + Code (genoteerd) | ✅ 2026-08-14 |

**DE POORT IS DICHT: 8/8 ✅ (2026-08-15, met het afvinken van punt 6).** Daarmee is
**datamigratie tranche 2 (GCP_UITROL §F1.6) formeel vrijgegeven** — uitvoering zodra Peter
het go-live-moment kiest — gevolgd door de omschakeling van het kantoor naar het
productiedomein. De volgorde-afhankelijkheid van punt 3 met tranche 2 (CMEK-herbouw vóór de
dump/restore — CMEK kan alleen bij instantie-aanmaak) is **opgelost**: `rlz-sql2` staat mét
CMEK, vóór tranche 2. NB de poort borgt de AVG-kant; open restpunten die géén poortpunt
zijn (subverwerkerslijsten, checklist-C-subchecks) staan per punt hieronder en in
`02-subverwerkers-checklist.md`.

---

## 1. Google Cloud CDPA — ✅ versie + datum gearchiveerd (2026-08-15)

Het CDPA is automatisch onderdeel van de Google Cloud-overeenkomst (acceptatie bij het
aangaan van het account/de overeenkomst — geen aparte handtekening).

- ✅ **Gearchiveerd 2026-08-15** (aangeleverd door Peter):
  `docs/avg/nl-cloud-data-processing-addendum-customers.pdf` — Nederlandse webprint van
  <https://cloud.google.com/terms/data-processing-addendum>, **"Versie: 8 juni 2026"**
  (versieregel uit de PDF zelf geverifieerd).
- **Acceptatie:** loopt via de Google Cloud-overeenkomst van de PDL Powerhouse-organisatie;
  voor dit project geëffectueerd bij de F0-uitvoering (project `rlz-boekhouding` aangemaakt
  + billing gekoppeld, **2026-08-14**). De versie van 8 juni 2026 is de op dat moment én bij
  archivering geldende CDPA-versie.
- ✅ Restpunt gedicht (2026-08-15): **Googles subverwerkerslijsten gearchiveerd** —
  `Google Cloud Platform Subprocessors | Google Cloud.pdf` (GCP, "Current") én
  `Google Workspace Terms Of Service – Subprocessors.pdf` (Workspace, 23-07-2026);
  checklist B/D.

## 2. Regio-borging — ✅ aantoonbaar (Code, 2026-08-14)

Alle resources staan in `europe-west4` én een Organization Policy op EU-locaties is
effectief op het project. Read-only geverifieerd met het org-beheerspoor, 2026-08-14:

```
$ gcloud org-policies describe constraints/gcp.resourceLocations \
    --project=rlz-boekhouding --effective
name: projects/652591056217/policies/gcp.resourceLocations
spec:
  rules:
  - values:
      allowedValues:
      - eu-locations
      - europe-west4
      - … (uitsluitend EU-locatiegroepen/-regio's)
```

Per resource (describe 2026-08-14): Cloud SQL `rlz-sql` region `europe-west4`; bucket
`rlz-boekhouding-documenten` location `EUROPE-WEST4`; KMS-keyring `rlz` `europe-west4`;
Cloud Run-service + jobs + Artifact Registry `europe-west4` (F0/F2/F3-uitvoering,
GCP_UITROL). Secrets met user-managed replicatie `europe-west4` (F1 — 'automatic' botst
bewust met deze org-policy, dat is de policy die zijn werk doet).

## 3. Herzieningsmoment CLOUD Act (besluit 0003) — ✅ besloten + uitgevoerd

- **Memo opgesteld 2026-08-14** (beslispunt 6): platformbesluit
  **`Platform/besluiten/0021-cmek-clientside-documentversleuteling.md`** — lean-lijn:
  **CMEK aan bij go-live**, **client-side documentversleuteling alleen op expliciet
  klantverzoek**. Eerlijke weging in het memo: zeggenschap/intrekbaarheid/audit — geen
  extra cryptografische sterkte, beperkt CLOUD-Act-verweer zolang de key in Cloud KMS leeft.
- ✅ **Akkoord Peter (2026-08-14)** — INDEX-regel 0021 gezet, memo-status BESLOTEN
  (eerder abusievelijk als 2026-08-15 gestempeld; datumcorrectie Peter 2026-08-14).
- ✅ **Uitvoeringsplan §6 uitgevoerd (2026-08-14, `scripts/gcp/f5_cmek.sh`):** twee keys op
  keyring `rlz` (jaarrotatie, nooit destroy) mét service-agent-bindings; Cloud SQL herbouwd
  als **`rlz-sql2`** mét CMEK (Alembic 0001→head = 0049, metadata-guard 69==69, GCS/KMS-
  verificatie GESLAAGD, `/health` 200 op run.app + productiedomein, handmatige `rlz-sync`-run
  exit 0); bucket-default-key gezet; service + 5 jobs omgehangen; oude `rlz-sql` verwijderd
  ná groene verificatie (`f5_cmek_opruimen.sh`, gemotiveerd: eigen lege testinstantie —
  schema + bootstrap/seed, géén klantdata, geen extern systeem).

  Describe-bewijs (2026-08-14):

  ```
  $ gcloud sql instances describe rlz-sql2 --format="yaml(...)"
  diskEncryptionConfiguration:
    kmsKeyName: projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/cmek-sql
  settings: {availabilityType: REGIONAL, backupConfiguration: {pointInTimeRecoveryEnabled: true,
             startTime: "02:00", transactionLogRetentionDays: 7}}

  $ gcloud storage buckets describe gs://rlz-boekhouding-documenten --format="value(default_kms_key)"
  projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/cmek-documenten

  $ gcloud storage objects describe gs://…/verificatie/f1-20260814-162915-c73e5404.txt --format="value(kms_key)"
  projects/…/cryptoKeys/cmek-documenten/cryptoKeyVersions/1   ← nieuw object daadwerkelijk CMEK
  ```

  NB het oudere F1-verificatie-testobject blijft Google-default versleuteld (retentie
  verbiedt verwijderen; geen klantdata — gedocumenteerd in besluit 0021 §3). Alle
  klantdocumenten komen ná tranche 2 dus onder CMEK binnen.

## 4. Retentie/PITR gedocumenteerd — ✅ (Code, 2026-08-14)

Staat technisch sinds F1 (GCP_UITROL §"F1 — UITGEVOERD" is de canonieke uitvoerings-
beschrijving); hier de instellingen als poortbewijs (describe 2026-08-14):

| Instelling | Waarde | Bewijs |
|---|---|---|
| Cloud SQL HA | `REGIONAL` (PostgreSQL 16) | `gcloud sql instances describe rlz-sql` |
| PITR | aan, transactielogs **7 dagen** | idem (`pointInTimeRecoveryEnabled: True`) |
| Automatische backups | dagelijks **02:00** | idem |
| Bucket-retentie | **220.903.200 s = 7 jaar**, *unlocked* (beslispunt 7 — nooit `retention lock` draaien; heroverwegen bij het WORM-export-besluit) | `gcloud storage buckets describe gs://rlz-boekhouding-documenten` |
| Bucket-versioning | aan | idem |
| Public access prevention | `enforced` | idem |
| Uniform bucket-level access | aan | idem |

Bewaartermijn-samenhang: de 7-jaarsretentie op de bucket implementeert de fiscale
bewaarplicht uit het verwerkingsregister (doc 1, per-verwerking "Bewaartermijn").

## 5. Verwerkersovereenkomst Exact Reeleezee — ✅ bevestigd + gearchiveerd (2026-08-15)

- ✅ Gearchiveerd (2026-08-14, aangeleverd door Peter, in `docs/`):
  `E-MKB-VWO-VERWERKING-VAN-PERSOONSGEGEVENS-2021.pdf` (VWO versie 1.5, 2021),
  `E-MKB-BIJLAGE-VERWERKERSOVEREENKOMST-202207.pdf` (bijlage versie 1.6, 2022),
  `Exact-Online-Voorwaarden-Nederland.pdf`.
- ✅ **Bevestiging Exact Reeleezee ontvangen + gearchiveerd**: Exact-support
  (Nele Lannoo, supportcase@exact.com) bevestigt per e-mail van **2026-08-14** op de
  expliciete vraag van Peter dat verwerkersovereenkomst **versie 1.5/1.6 de juiste
  versie** is voor de Reeleezee-abonnementen — mail-PDF gearchiveerd 2026-08-15 als
  `docs/avg/Bevestiging versie RLZ.pdf`.
- ✅ **Restpunten gedicht (bevestiging 2026-08-15, gearchiveerd 2026-08-16):**
  Exact-support (Nele Lannoo, zelfde support-case) bevestigt op Peters twee
  vervolgvragen ("Beide vragen kan ik bevestigen") dat (1) opslag en verwerking van de
  Reeleezee-administratiedata volledig binnen de EU/EER plaatsvinden én (2) de
  API-/webservice-toegang onder dezelfde verwerkersovereenkomst en voorwaarden valt —
  mail-PDF: `docs/avg/Bevestiging Exact EU-datalocatie en API-toegang 2026-08-15.pdf`. Checklist C is daarmee volledig ✅.

## 6. IMAP-provider-DPA (checklist D) — ✅ rond (2026-08-15)

- ✅ Providerkeuze: **bestaande kantoor-mailprovider = Google Workspace** (de
  ak-nijenhuis.nl-Workspace; GCP-beslispunt 5, 2026-08-12).
- ✅ Mailbox aangemaakt: **`facturen@ak-nijenhuis.nl`** (bewuste adreskeuze Peter
  2026-08-15 — korter; nadrukkelijk niet het app-domein administratiekantoornijenhuis.nl).
- ✅ **DPA-check**: de geldende verwerkersvoorwaarden voor Google Workspace zijn sinds
  Googles samenvoeging het **Cloud Data Processing Addendum (CDPA)** — exact het document
  dat voor poortpunt 1 al is gearchiveerd
  (`nl-cloud-data-processing-addendum-customers.pdf`, versie 8 juni 2026); de CDPA-tekst
  benoemt Google Workspace expliciet in scope (definities, datacenterlocaties,
  subverwerkers, certificeringen — tekstueel geverifieerd 2026-08-15). Aanvullend
  gearchiveerd (aangeleverd Peter 2026-08-15):
  `Google Workspace Terms of Service – Google Workspace.pdf` — dit is de **oude, losse
  Workspace-"Data Processing Amendment"** (last modified 24-09-2021), door Google zelf
  gemarkeerd als archiefversie en vervangen door de CDPA; bewaard als context, de CDPA is
  het geldende document. De oude losse DPA-URL bestaat niet meer (404-check 2026-08-15).
- NB het app-wachtwoord in het secret-slot `INTAKE_IMAP_WACHTWOORD` is een
  **activatiestap (F3.4)**, geen poortpunt: tot dat moment draait de fetch simpelweg niet
  en is de .eml-upload het kanaal. Activatie-uitvoering: GCP_UITROL §F3.4-uitvoering.

## 7. Verwerkingsregister §8/§9 bijgewerkt — ✅ (Code, 2026-08-14)

`01-verwerkingsregister.md` §8 beschrijft de **werkelijke** cloudconfiguratie
(project, org-policy, Cloud SQL HA/PITR, bucketinstellingen, KMS/Secret Manager,
least-privilege-SA's) en §9 de actuele doorgiftestatus: Anthropic Ireland-contractspartij
+ gearchiveerde ToS (17-06-2025)/DPA (24-02-2025), ZDR aangevraagd/lopend, verwerking VS
→ SCC-grondslag; Google CDPA + DPF + herzieningsmoment-uitkomst (voorstel 0021);
mailprovider-punt toegevoegd. Verwerkersoverzicht §0 aangevuld met PDL Powerhouse
(jurist-akkoord vraag 9). Consistent gemaakt met `02-subverwerkers-checklist.md`.

## 8. Identiteit-eerst-check — ✅ afgerond + genoteerd (F0, 2026-08-14)

Project, billing, domein en secrets hangen onder de juiste **juridische entiteit**:
project `rlz-boekhouding` (nummer 652591056217) staat in de **PDL Powerhouse-organisatie**
met het org-billing-account, aangemaakt door het org-beheeraccount (beslispunt 2 — zelfde
account als `vastly-504108`); read-only geverifieerd bij de F0-uitvoering (GCP_UITROL
§"F0 — UITGEVOERD": billing aan, org-policy effectief, SA's/WIF onder het project).
Domein `administratiekantoornijenhuis.nl` is in eigen bezit (beslispunt 3). De
eigendomsverhouding software/hosting (PDL) ↔ verwerkingsverantwoordelijke (kantoor) is
juridisch belegd via de intra-groep verwerkersovereenkomst
(`07-verwerkersovereenkomst-pdl.md`, jurist-akkoord vraag 9, 2026-08-12) —
✅ **GETEKEND 2026-08-19** (in tweevoud te Arnhem, beide partijen P.W. Nijenhuis,
Directie; KvK kantoor 72504412): getekend exemplaar gearchiveerd als
`docs/avg/Verwerkersovereenkomst-PDL-getekend-2026-08-18.pdf` (incl. Bijlagen A/B/C, ook
los als `Bijlagen-A-B-C-…-2026-08-18.docx`). Daarmee is de laatste
livegang-administratie-actie van dit poortpunt afgerond én de stap-1-voorwaarde
"PDL-VWO getekend" uit `05-activatie-checklist.md` vervuld.

---

## Peters openstaande klikken, verzameld (kopieerbaar lijstje)

1. ~~CDPA-versie + acceptatiedatum archiveren~~ — **gedaan** (punt 1 ✅);
   ~~Googles subverwerkerslijst~~ — **gedaan 2026-08-15** (GCP + Workspace gearchiveerd,
   checklist B/D).
2. ~~Akkoord op CMEK-voorstel 0021~~ — **gedaan**: akkoord 2026-08-14, uitgevoerd (punt 3 ✅).
3. ~~DPF-registercheck Anthropic~~ — **gedaan 2026-08-15, uitkomst negatief** (geen
   DPF-vermelding; SCC's dragen de doorgifte alleen — checklist A + register §9);
   **Anthropic-subverwerkerslijst archiveren staat nog open** (checklist A).
4. ~~Reeleezee-bevestiging toepasselijke VWO-versie~~ — **gedaan**: bevestiging Exact
   2026-08-14, gearchiveerd 2026-08-15 (punt 5 ✅); ~~restpunten EU-hosting +
   API-voorwaarden~~ — **gedaan**: beide bevestigd 2026-08-15, gearchiveerd 2026-08-16
   (`Bevestiging Exact EU-datalocatie en API-toegang 2026-08-15.pdf` — checklist C volledig ✅).
5. ~~facturen@-mailbox + DPA-check mailprovider~~ — **gedaan** (punt 6 ✅ 2026-08-15:
   `facturen@ak-nijenhuis.nl`, DPA = CDPA). ~~Activatieklik F3.4 (app-wachtwoord in het
   secret-slot)~~ — **gedaan 2026-08-15**: de live IMAP-fetch draait
   (GCP_UITROL §F3.4-uitvoering).
