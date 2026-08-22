# Tranche-2-draaiboek — datamigratie za 22-08 / zo 23-08-2026

> **✅ UITGEVOERD za 22-08-2026 — alle stappen groen, afgesloten met de her-intake
> (bewijs groen).** Werkelijke uitkomsten + lessen: zie "Uitvoering — uitkomsten en
> lessen" onderaan; formele vastlegging in GCP_UITROL §F1.6-uitvoering en de
> BESLISSINGEN-rij "TRANCHE 2 UITGEVOERD". Dit draaiboek is daarmee historie.
>
> **Klaargezet 2026-08-21** (na de Vastly-bevestiging van het cutover-schema; zie
> BESLISSINGEN "VASTLY-BEVESTIGING CUTOVER-SCHEMA"). Normtekst = `docs/GCP_UITROL.md`
> §F1.6 (volgorde bindend); dit is de uitvoeringsversie. Op de dag zelf dicteert de
> sessie dit stap voor stap — elke stap heeft een expliciete verificatie vóór de
> volgende begint, en elke afwijking wordt gemeld, nooit stil hersteld.
>
> **Schema (DEFINITIEF — bevestiging Peter mét Vastly 21-08, lezing A/weekdagen):**
> **za 22 / zo 23-08 tranche 2 → ma 24-08 F4-cutover** (`docs/F4_ACTIVATIE_RUNBOOK.md`,
> uitloop di 25-08) → nazorgweek. Facturatiestart vastgoed = kalendergrens 1 september.
> De eerder gemarkeerde datum-mismatch (dag-labels vs datums) is hiermee opgelost.
> **Freeze: za 22-08 09:00** — Peter meldt zich dan voor dit draaiboek.
> De F5-poort is dicht (8/8, 2026-08-15) — tranche 2 is vrijgegeven.

## Vooraf (vrijdagavond 21-08 / zaterdagochtend 22-08, vóór de freeze)

Deze drie punten komen uit de gereedheidscheck en zijn **blokkerend** voor de start:

1. **Alertmail-bevestiging (F3.2-restpunt) — ✅ AFGEVINKT (Peter, 2026-08-22 bij de
   start):** de alertmail is 21-08 's avonds ontvangen op `peter@ak-nijenhuis.nl`,
   onderwerp "RLZ Cloud Run job-failure (F3.2)". Het alertkanaal is bewezen; geen
   nieuwe geforceerde failure nodig. (Ná stap 7 zijn de cloud-jobs het enige vangnet.)
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
3. **Freeze-afspraak.** VASTGELEGD: **za 22-08 09:00** (afspraak Peter 21-08).
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
   NB de webhook-aflever-toggle blijft UIT tot de F4-activatie op ma 24-08.

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
  F4-activatie ma 24-08, niet bij dit weekend.
- Vastleggen: BESLISSINGEN-rij + GCP_UITROL §F1.6-uitvoering + dit draaiboek
  bijwerken met de werkelijke uitkomsten. ✅ Gedaan 22-08 — zie hieronder.

## Uitvoering — uitkomsten en lessen (UITGEVOERD za 22-08-2026)

Alle zeven stappen zijn op zaterdag 22-08 groen doorlopen (geen uitloop naar zondag
nodig); het sluitstuk was de **her-intake** van het vóór de restore veiliggestelde
intake-verkeer — groen, waarmee tranche 2 formeel af is. Afwijkingen van het plan en
lessen, per stap:

1. **Restore-smaak (stap 2): TOC-gestuurde full restore i.p.v. data-only met
   `--disable-triggers`.** De geplande smaak "data-only + `--disable-triggers`" is op
   Cloud SQL niet uitvoerbaar: triggers uitzetten vereist superuser-rechten en de
   `postgres`-rol is daar géén superuser. Gekozen en uitgevoerd: **full restore
   gestuurd via de pg_restore-TOC-lijst** (`pg_restore -l` → gefilterde lijst →
   `pg_restore -L`), waarmee de bestaande cloud-inhoud expliciet en controleerbaar
   vervangen is i.p.v. stil gemengd. `alembic_version` op het doel geverifieerd
   (= lokale head, 0058). Norm voor een eventuele volgende restore: TOC-smaak is dé
   smaak op Cloud SQL.
2. **LES — RLS-blindheid bij élke cloud-telling als `postgres`.** Tellingen/
   inventarissen op de cloud-DB die als `postgres` draaien zien **0 rijen** op alle
   FORCE-ROW-LEVEL-SECURITY-tabellen (geen scope-context, en `postgres` heeft op
   Cloud SQL geen BYPASSRLS) — een tabel die "leeg" lijkt is dat dus niet
   noodzakelijk. Elke verificatie-/inventaristelling moet RLS expliciet adresseren;
   nooit een kale `psql`-count als postgres vertrouwen.
3. **Masterkey-continuïteit: herversleuteling groen** (dry-run 0 mislukt →
   `--uitvoeren`), TOTP-login op het doel bewezen. **Aanscherping t.o.v. het plan
   ("oude key weg ná groene stap 6"): de oude lokale `TOTP_MASTER_KEY` blijft staan
   tot ná de nazorgweek** — de lokale omgeving is tot dan de rollback-bron en moet
   zelfstandig kunnen draaien; pas daarna opruimen (bewuste, expliciete stap).
4. **Her-intake-bewijs (vooraf-punt 2 + functionele proef):** het intake-verkeer dat
   sinds de IMAP-activatie in de cloud-DB was geland (en door de restore overschreven
   werd) is ná de restore opnieuw en **idempotent** verwerkt — her-intake groen, geen
   verlies, geen duplicaten. De vergankelijke cloud-testdata (SEED-PASSKEYTEST,
   review-demo, Universal-cloud-test-onboarding 21-08) is conform besluit verdwenen.
5. **Outbox-hertelling: 3 rijen** (ongewijzigd t.o.v. de stand van 15-08) — genoteerd
   als input voor de **backlogmelding aan vastgoed op de F4-cutover-dag ma 24-08**
   (F4-runbook stap 4).
6. **Cutover (stap 7) uitgevoerd:** cloud-schedulers hervat, lokale cron definitief
   uit. De **rlz-sync-cadans is live verzet naar `0 7 * * *` (Europe/Amsterdam)**;
   config-as-code (`scripts/gcp/f3_jobs.sh`) is gelijkgetrokken zodat een herdeploy/
   her-run niets terugzet — NB `deploy.yml` raakt scheduler-cadansen sowieso niet.
   `rlz-accordeur-herinneringen` + `rlz-nieuwe-facturen` blijven gepauzeerd (eigen
   gate: notificatie-live-verificatie); webhook-aflevering blijft UIT tot F4 (ma
   24-08).
