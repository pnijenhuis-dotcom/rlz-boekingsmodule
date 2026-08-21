# Tranche-2-draaiboek — datamigratie za 23-08 / zo 24-08-2026

> **Klaargezet 2026-08-21** (na de Vastly-bevestiging van het cutover-schema; zie
> BESLISSINGEN "VASTLY-BEVESTIGING CUTOVER-SCHEMA"). Normtekst = `docs/GCP_UITROL.md`
> §F1.6 (volgorde bindend); dit is de uitvoeringsversie. Op de dag zelf dicteert de
> sessie dit stap voor stap — elke stap heeft een expliciete verificatie vóór de
> volgende begint, en elke afwijking wordt gemeld, nooit stil hersteld.
>
> **Schema (vast, Vastly 21-08):** za 23 / zo 24-08 tranche 2 → **ma 25-08 F4-cutover**
> (`docs/F4_ACTIVATIE_RUNBOOK.md`, uitloop di 26-08) → nazorgweek. Facturatiestart
> vastgoed = kalendergrens 1 september. De F5-poort is dicht (8/8, 2026-08-15) —
> tranche 2 is vrijgegeven.

## Vooraf (vrijdagavond 22-08 / zaterdagochtend, vóór de freeze)

Deze drie punten komen uit de gereedheidscheck en zijn **blokkerend** voor de start:

1. **Alertmail-bevestiging (F3.2-restpunt).** Peter bevestigt dat de alertmail van de
   geforceerde-failure-test (F3, 14-08) daadwerkelijk is ontvangen op
   `Peter@ak-nijenhuis.nl`. Ná stap 7 zijn de cloud-jobs het **enige** vangnet (de
   lokale dagelijkse run stopt) — zonder bewezen alertkanaal geen cutover.
   Zo nodig op de dag een nieuwe geforceerde failure draaien (F3-recept).
2. **Cloud-DB-inventaris + IMAP-check.** Sinds F3.4 landt intake-mail op
   `facturen@ak-nijenhuis.nl` in de **cloud-DB**; de restore overschrijft die.
   Vóór de dump: (a) scheduler `rlz-intake-imap` **pauzeren**; (b) inventaris draaien
   van cloud-rijen die lokaal niet bestaan — intake-berichten/documenten sinds de
   IMAP-activatie (15-08): échte klantfacturen eerst veiligstellen/lokaal verwerken
   (verwachting: alleen testverkeer); (c) de **vergankelijke cloud-testdata expliciet
   benoemen en accepteren** die verdwijnt: SEED-PASSKEYTEST + TEST-accordering,
   review-demo-seed, de Universal-cloud-test-onboarding van 21-08 (veldwerkers,
   koppelingen, weekstaten), en cloud-zijdig geregistreerde accounts/passkeys (de
   lokale gebruikerstabel wint — cloud-only-passkeys worden wees, herregistratie is
   de normale flow). Alles bewuste besluiten; hier alleen herbevestigen.
3. **Freeze-afspraak.** Tijdstip afspreken met Peter (voorstel: za 23-08 09:00).
   Vanaf dat moment tot en met de groene functionele proef (stap 6): lokale backend +
   dagelijkse run uit, geen boekingen, geen syncs, geen deploys/pushes naar main
   (de deploy-workflow migreert de cloud-DB — mag niet middenin de restore landen).
   RLZ zelf draait gewoon door (bron van waarheid, geen probleem).

Daarnaast op de ochtend zelf: alembic-stand bron en doel gelijk (beide head, nu 0058)
en een verse controle dat er geen migratie klaarstaat die nog niet gedeployed is.

## Stappen (volgorde bindend — GCP_UITROL §F1.6)

1. **Freeze bron.** Lokale backend + dagelijkse run stoppen (afspraak hierboven).
   Verificatie: geen actieve verbindingen op de lokale `boekhouding`.
2. **Dump + restore.** `pg_dump --format=custom` van de lokale `boekhouding` →
   `pg_restore` in Cloud SQL (`rlz-sql2`, via de Auth Proxy op 5434).
   **Smaakbeslispunt op de dag** (F1.6 stap 2): data-only met `--disable-triggers`
   op het bestaande schema, óf schoon-en-full-restore; één smaak kiezen en de
   `alembic_version` op het doel verifiëren (= lokale head). NB de cloud-DB is niet
   leeg (seeds, IMAP-intake, Universal-test) — de gekozen smaak moet dat expliciet
   adresseren, nooit stil mengen.
3. **Documenten.** `gsutil -m rsync -r ./.data/documenten gs://<documentenbucket>` —
   eerst `-n` (droogloop) en de aantallen vergelijken met `boekhouding.document`;
   pas daarna echt. Nieuwe objecten krijgen automatisch de CMEK-default-key.
4. **Masterkey-continuïteit.** `scripts/herversleutel_masterkey.py --van lokaal
   --naar kms` — eerst dry-run (verwacht: 0 mislukt), dan `--uitvoeren`.
   De oude lokale TOTP_MASTER_KEY pas weggooien **ná** groene stap 6.
5. **Verificatie.** `scripts/gcp/datamigratie_check.py` met BRON=lokaal,
   DOEL=Cloud SQL — **exit 0 vereist** (rijtellingen + per-administratie-tellingen +
   alembic-versie).
6. **Functionele proef op het doel** (app.administratiekantoornijenhuis.nl):
   kantoor-login mét TOTP (= herversleuteling bewezen), RLZ-sync van één
   administratie (= credential-store bewezen), één documentweergave uit de bucket
   (= GCS-pad bewezen).
7. **Cutover.** Cloud Scheduler-jobs hervatten (`rlz-sync`, `rlz-reconciliatie`,
   `rlz-webhook-afleveraar`, `rlz-intake-imap` weer aan); lokale cron definitief uit.
   **Gepauzeerd blijven** (eigen gate, los van tranche 2):
   `rlz-accordeur-herinneringen` + `rlz-nieuwe-facturen` — tot de
   notificatie-live-verificatie (`scripts/gcp/notificaties_afronden.sh`).
   NB de webhook-aflever-toggle blijft UIT tot de F4-activatie op ma 25-08.

## Ná afloop (zelfde weekend)

- **Outbox-hertelling** voor de backlog-melding aan vastgoed op de cutover-dag
  (F4-runbook stap 4; stand 15-08 was 3 rijen, hertellen op de dag zelf).
- **Kantoor-omschakeling**: Peter werkt vanaf nu op het productiedomein; de lokale
  omgeving blijft dev (en is tot het einde van de nazorgweek de rollback-bron —
  lokale database + documentenmap **niet opruimen**; PITR staat op 7 dagen).
- **Universal uren & meerwerk**: de restore zet de lokale stand terug — opt-in en
  cloud-veldwerkers van de 21-08-test zijn weg; heractiveren (opt-in + uitnodigingen)
  is een bewuste vervolgstap als de kliktest doorloopt.
- **Route A wordt end-to-end mogelijk** (werk-DB staat nu in de cloud) — hoort bij de
  F4-activatie ma 25-08, niet bij dit weekend.
- Vastleggen: BESLISSINGEN-rij + GCP_UITROL §F1.6-uitvoering + dit draaiboek
  bijwerken met de werkelijke uitkomsten.
