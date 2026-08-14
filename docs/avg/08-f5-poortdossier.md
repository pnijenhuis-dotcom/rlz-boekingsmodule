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
| 1 | Google Cloud CDPA geaccepteerd, versie + datum gearchiveerd | Peter | ⬜ open |
| 2 | Regio-borging aantoonbaar (`europe-west4` + EU-org-policy) | Code | ✅ 2026-08-14 |
| 3 | Herzieningsmoment CLOUD Act (besluit 0003): CMEK/client-side beoordeeld, uitkomst als platformbesluit | Code (memo) + Peter (besluit) + beiden (uitvoering) | 🔶 memo klaar, wacht op akkoord |
| 4 | Retentie/PITR-instellingen gedocumenteerd | Code | ✅ 2026-08-14 |
| 5 | Verwerkersovereenkomst Exact Reeleezee bevestigd + gearchiveerd | Peter | 🔶 PDF's gearchiveerd, bevestiging open |
| 6 | IMAP-provider-DPA rond (checklist D) | Peter | 🔶 keuze gemaakt, DPA-check open |
| 7 | Verwerkingsregister §8/§9 bijgewerkt op de werkelijke cloudconfiguratie | Code | ✅ 2026-08-14 |
| 8 | Identiteit-eerst-check afgerond genoteerd (uit F0) | Peter (uitgevoerd) + Code (genoteerd) | ✅ 2026-08-14 |

**Poort dicht = 8/8 ✅.** Daarna pas: datamigratie tranche 2 (GCP_UITROL §F1.6) en de
omschakeling van het kantoor naar het productiedomein. NB punt 3 heeft een
volgorde-afhankelijkheid met tranche 2: bij akkoord op CMEK moet de Cloud SQL-herbouw
**vóór** de tranche-2-dump/restore gebeuren (CMEK kan alleen bij instantie-aanmaak).

---

## 1. Google Cloud CDPA — versie + datum gearchiveerd *(Peter — ⬜)*

Het CDPA is automatisch onderdeel van de Google Cloud-overeenkomst (acceptatie bij het
aangaan van het account). Vast te leggen: **welke CDPA-versie** gold bij acceptatie +
**acceptatiedatum**, gearchiveerd als PDF in `docs/avg/`.

- Route: Cloud Console → ondernemingsvoorwaarden, of
  <https://cloud.google.com/terms/data-processing-addendum> als PDF-print.
- Meteen meenemen (zelfde klik): **Googles subverwerkerslijst** archiveren
  (checklist B, laatste actiepunt).
- Vindplaats na afronding: PDF hier in de map + regel in `02-subverwerkers-checklist.md` B.

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

## 3. Herzieningsmoment CLOUD Act (besluit 0003) — 🔶 memo klaar, besluit open

- **Memo opgesteld 2026-08-14** (beslispunt 6): voorstel-platformbesluit
  **`Platform/besluiten/0021-cmek-clientside-documentversleuteling.md`** — aanbeveling
  conform de lean-lijn: **CMEK aan bij go-live** (Cloud SQL-herbouw mét CMEK vóór
  tranche 2 — becijferd op ~1 dagdeel zolang er geen klantdata staat — + default-KMS-key
  op de bestaande documentenbucket), **client-side documentversleuteling alleen op
  expliciet klantverzoek**. Het memo adresseert de technische realiteit (CMEK op Cloud SQL
  kan uitsluitend bij aanmaak; instantie draagt nu alleen schema + seed) en weegt eerlijk
  wat CMEK toevoegt (zeggenschap/intrekbaarheid/audit — geen extra cryptografische
  sterkte, beperkt CLOUD-Act-verweer zolang de key in Cloud KMS leeft).
- ⬜ **Akkoord Peter** op het voorstel (of gemotiveerd afwijken — ook dát is een geldig
  besluit 0003-herzieningsresultaat, dan als eigen INDEX-regel vastleggen).
- ⬜ Ná akkoord: uitvoeringsplan §6 van het memo (keys, `rlz-sql2`, bucket-default-key,
  verificaties) + INDEX-regel 0021 + register §9 en dit dossier bijwerken.

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

## 5. Verwerkersovereenkomst Exact Reeleezee — 🔶 (Peter)

- ✅ Gearchiveerd (2026-08-14, aangeleverd door Peter, in `docs/`):
  `E-MKB-VWO-VERWERKING-VAN-PERSOONSGEGEVENS-2021.pdf` (VWO versie 1.5, 2021),
  `E-MKB-BIJLAGE-VERWERKERSOVEREENKOMST-202207.pdf` (bijlage versie 1.6, 2022),
  `Exact-Online-Voorwaarden-Nederland.pdf`.
- ⬜ **Bevestiging Exact Reeleezee** dat déze documenten (of welke versie dan wél) op de
  Reeleezee-abonnementen van toepassing zijn — de PDF's zijn op de Exact-MKB/Exact
  Online-lijn geschreven (checklist C). Incl. EU-hostingbevestiging + check dat de
  API-toegang (webservice-logins) onder dezelfde voorwaarden valt.

## 6. IMAP-provider-DPA (checklist D) — 🔶 (Peter)

- ✅ Providerkeuze: **bestaande kantoor-mailprovider** (GCP-beslispunt 5, 2026-08-12).
- ⬜ facturen@-mailbox aanmaken + app-wachtwoord; ⬜ DPA/verwerkersvoorwaarden van de
  mailprovider checken + archiveren (checklist D).
- NB dit punt blokkeert **F3.4 (IMAP-activatie)** — de F5-poort zelf vermeldt het als
  poortpunt, maar tot activering is de .eml-upload het kanaal en gaat er geen
  klantdata door de provider heen. Technisch klaar: scheduler gepauzeerd, secret-slot
  `INTAKE_IMAP_WACHTWOORD` wacht op een versie (F3-uitvoering).

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
juridisch belegd via de intra-groep verwerkersovereenkomst (concept
`07-verwerkersovereenkomst-pdl.md`, jurist-akkoord vraag 9, 2026-08-12) — ondertekening
is onderdeel van de livegang-administratie.

---

## Peters openstaande klikken, verzameld (kopieerbaar lijstje)

1. **CDPA-versie + acceptatiedatum** archiveren (punt 1) + Googles subverwerkerslijst.
2. **Akkoord (of afwijzing) op CMEK-voorstel 0021** (punt 3) — daarna uitvoering samen.
3. **DPF-registercheck Anthropic** + Anthropic-subverwerkerslijst archiveren
   (checklist A — geen F5-poortpunt maar stap-1-punt, zelfde archiveersessie).
4. **Reeleezee-bevestiging** toepasselijke VWO-versie (punt 5).
5. **facturen@-mailbox + app-wachtwoord + DPA-check mailprovider** (punt 6).
