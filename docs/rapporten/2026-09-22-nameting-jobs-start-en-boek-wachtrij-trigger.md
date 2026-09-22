# Nameting ná deploy — F3-jobs `command: python`, job-smoketest, scheduler-vangnetten, wordt_geboekt-LET-OP (22-09)

Opdracht `opdrachten/gedaan/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md` (vervolg op de BUG-run van 21-09; bouwrapport
`docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md`, BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN
DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)"). Lees-only nameting; niets geschreven in RLZ, Odoo of de productiedatabase.
Peter keek niet mee; keuzes staan onder "Keuzes". Alle tijden UTC tenzij "NL".

**Werkt in productie — per onderdeel:**

| Onderdeel | Uitkomst | Bewijs |
|---|---|---|
| `--command python` op élke F3-job | **JA** | bot-bestand `verkenning/nameting-jobs-start-22-09.txt` (commit `a786e53`): 16 jobs `python`, `rlz-migratie` `alembic`, alle 17 op image `142f33c` |
| Job-smoketest ná de F3-lus | **JA** | deploy `fb63be5` (run 35632649146) én deploy `142f33c` (run 35731434648): 15 × "job-smoketest ‹job›: start ok", stap 9 groen, 0 `::error` |
| Scheduler-vangnetten ENABLED | **JA** | owner-sessie: `rlz-boek-wachtrij` `*/2` · `rlz-extractie-wachtrij` `*/10` · `rlz-bewaking` `*/15` · `rlz-webhook-afleveraar` `*/5` allemaal ENABLED; `rlz-bank-sync` heeft bewust géén scheduler (on-demand) |
| Job `rlz-boek-wachtrij` start en draait | **JA** | Cloud Logging sinds de deploy: exact 30 executies per uur (elke 2 min), 0 × "Application exec likely failed", 0 × severity ≥ ERROR; laatste 8 executies `succeededCount 1` |
| Kwartier-probe `boek_wachtrij_gestrand` | **JA** | `rlz-bewaking` 22-09 11:15–13:00: élke meting `boek_wachtrij_gestrand=ok` |
| Regressie-LET-OP `boek_wachtrij_gestrand` in de reconciliatie | **JA (afwezig-pad)** | run `e315ceae` 22-09 04:30–04:46: 0 × `boek_wachtrij_gestrand`, 0 fouten; de enige LET-OP is `groep_saldo_fout` (andere nameting) |
| Oude `wordt_geboekt_verouderd` automatisch gesloten | **JA** | audit `reconciliatie_auto_gesloten` 22-09 04:46:28: soort `wordt_geboekt_verouderd` / afwijking / blok documenten / aantal 1; `samenvatting.delta.verdwenen_afwijkingen` 13 |
| Trigger-pad (klik → job binnen 2 min, niet via het vangnet) | **NIET GEMETEN** | geen enkele `boek_wachtrij_ingediend` ná de deploy (laatste indiening 21-09 07:53); request-log: 0 × POST `/boeken` 202, 0 × `opnieuw-indienen` |

**Trigger-pad: niet gemeten — vraagt één klik 'Boeken in RLZ' van Peter op de RLZ-testadministratie (RLZ-adminId
8dbfb856-d75b-4ec3-9124-c8b739fe3bc5, TEST-referentie); daarna `gh workflow run nameting -f onderdeel=jobs-start` opnieuw.** Let op: die
administratie ("Administratiekantoor Nijenhuis (test)", platform-id `faae29c5`) staat sinds 30-08 gearchiveerd, boeken uit, 0 credentials
(leesreplica, deze run) — de klik vraagt dus éérst dearchiveren mét de TESTADMIN-login (stappen in
`docs/rapporten/2026-09-22-nameting-corrigeren-testadministratie.md`). Een gewone indiening op een klantadministratie door het kantoor meet
het pad óók (lees-only, niets extra nodig); daarom staat poging 2 als vervolg-opdracht mét `niet vóór: 2026-09-23 09:00` in de inbox
(hoogstens drie pogingen, daarna `mislukt/` mét het klikpunt — regel 22-09).

## Stap 0 — deploy-check (service ÉN jobs)

- `git fetch` + `git rev-list --count main..origin/main` = 0 bij de start; tijdens de run kwam de bot-commit `a786e53` op origin →
  `git merge --no-ff origin/main` (nooit rebase), daarna pas de rapportage.
- Deploy van de fix-commit `fc27528` + docs `fb63be5` (run 35632649146, 21-09 17:32–17:38): alle stappen groen; stap 9 "F3-jobs bijwerken … +
  job-smoketest" logt 15 × `job-smoketest ‹job›: start ok` (17:36:44–17:36:46, parallel; rlz-migratie en rlz-smoketest bewijzen zichzelf in
  de workflow). De deploy van `142f33c` (run 35731434648, tijdens deze run) herhaalt dat: 15 × start ok, 0 `::error`.
- `gcloud run jobs describe rlz-boek-wachtrij`: image `142f33c`, command `python`. Service `rlz-backend` revisie `rlz-backend-00669-csg` op
  `142f33c` → service = jobs.

## Stap 1 — meetlat `jobs-start` (bot-bestand op main)

`gh workflow run nameting -f onderdeel=jobs-start` → run 35732117028 → bot-commit `a786e53` = `verkenning/nameting-jobs-start-22-09.txt`:

- Oordeelregel: **"alle jobs dragen command python (rlz-migratie: alembic) — job-exit 0"**; 17 jobs op `backend:142f33c`.
- Laatste 8 executies `rlz-boek-wachtrij` (13:02–13:14): allemaal `succeededCount 1`, geen `failedCount`.
- Scheduler-stand: 5 × "niet leesbaar" — `nameting@` heeft geen `cloudscheduler.viewer` (verwacht gedrag, geen fout). Gemeten in de
  owner-sessie (`gcloud scheduler jobs list`): 11 schedulers, allemaal ENABLED; de vier vangnetten mét cadans zoals in de tabel hierboven.
  `rlz-bank-sync` staat NIET in Cloud Scheduler: het is een on-demand job (bank-verversing bij openen, f3_jobs.sh stap 7) — de vangnet-lus in
  `f3_jobs.sh` vangt dat als "geen scheduler (on-demand only …) — overgeslagen", geen bug.
- `db-lezen boek-wachtrij` (7 dagen, per administratie): **150 rijen over 3 administraties, 0 × `wordt_geboekt_nu`**; 5 × `ingediend`
  (Administratiekantoor Nijenhuis C.V. 19-09 06:55 en 21-09 10:46, Belastingbutler 21-09 07:20, Old Dutch 21-09 07:53 ×2), 140 × `trigger`
  `geslaagd`, 5 × `afgerond` `geboekt` verwerker `job` 21-09 15:31:28–15:31:40 — exact de stand van het bouwrapport; **geen indiening ná de
  deploy**. Leesreplica-controle: `document.status = 'wordt_geboekt'` → 0.

## Stap 2 — trigger-pad

- Request-log `rlz-backend` sinds 21-09 17:38: precies één POST op een `/boeken`-route — 22-09 08:52:57, **409**, 1,1 s, administratie
  Bouwadvies Oost Nederland B.V., document `8c558b35`; geen audit op dat record, geen 5xx, geen app-logregel. Een 409 is een poort
  (accordering/aanbiedbaarheid/dubbel indienen) vóór het indienen — geen `wordt_geboekt`, geen trigger. 0 × 202, 0 × `boek-wachtrij/opnieuw-indienen`.
- Cloud Logging job-kant sinds de deploy: 0 × "N boeking(en) afgerond" mét N > 0 (alle 590 regels "0 boeking(en) afgerond"), 6 ×
  `job-smoketest ok` (de deploys van 22-09).
- Conclusie letterlijk: **trigger-pad: niet gemeten** — zie de vetgedrukte alinea bovenaan. Er is in deze run niets ingediend (regel: nooit zelf
  een boeking indienen op een klantadministratie; de testadministratie is zonder credential).

## Stap 3 — bewaking + reconciliatie

- `rlz-bewaking` (elk kwartier) 22-09 11:15:33 → 13:00:36: acht metingen, élke keer `boek_wachtrij_gestrand=ok`; `automatisering_regressie=fout`
  = de bekende `groep_saldo_fout`-LET-OP (nameting groepssaldi 22-09), niet deze feature.
- Scheduler-run reconciliatie `e315ceae` (22-09 04:30:26–04:46:26, image `fb63be5`): bevindingen `let_op`/`fout` = precies één rij,
  `automatisering` / `groep_saldo_fout`; **0 × `boek_wachtrij_gestrand`** (afwezig-pad klopt: er hing niets). `samenvatting.delta` =
  `nieuwe_afwijkingen 16, nieuwe_let_op 1, nieuwe_fouten 0, verdwenen_afwijkingen 13, verdwenen_fouten 0, blokken_fout []`.
- Audit `reconciliatie_auto_gesloten` 22-09 04:46:28: zeven rijen, waaronder `wordt_geboekt_verouderd` / `afwijking` / `documenten` / aantal 1 /
  reden "niet meer geproduceerd door run e315ceae… — afwijking uit de vorige run verdwenen" — de oude in-meting-afwijking (document `75b35516`,
  19-09) is netjes gesloten, zoals de regel van 19-09 avond voorschrijft.

## Bijvangst — bouwfout in de meetlat zelf, in deze run gefixt

- **Commitbericht van de bot zei "Oordeel: ROOD" bij een groen rapport.** `a786e53` = "nameting 22-09 jobs-start — Oordeel: ROOD", terwijl het
  bestand zelf "alle jobs dragen command python" zegt. Oorzaak: de oordeelbron-keten in `nameting.yml` had voor `jobs-start` geen eigen tak en
  viel terug op `nameting-vgg-replay-22-09.txt` van de `alles`-run van vanochtend ("Oordeel: ROOD"). De regel van 19-09 ("nieuw onderdeel =
  if-tak + options + via_gh_onderdeel") miste het vierde onderdeel: de `OORDEEL_BRON`-tak. Gefixt: expliciete tak voor `jobs-start`; de
  else-tak leest nu `nameting-$ONDERDEEL-$DATUM.txt` en alleen `alles|a|b|c|d|e` lezen het replay-rapport; onbekend bestand = "geen
  oordeelregel", nooit de regel van een ander onderdeel. Guards `test_nameting_workflow.py`: reproductie jobs-start + generieke parametrische
  test over élk onderdeel mét eigen `UIT`-bestand + btw-default zonder bestand (35 passed). De meting zelf blijft geldig (het bot-bestand is
  de bron, niet het commitbericht).
- Meetlat-gat: `nameting@` kan de scheduler-stand niet lezen ("niet leesbaar"). Beslispunt Peter (owner-commando, niet in deze run):
  `gcloud projects add-iam-policy-binding rlz-boekhouding --member=serviceAccount:nameting@rlz-boekhouding.iam.gserviceaccount.com --role=roles/cloudscheduler.viewer`
  — dan meet `jobs-start` de vangnetten zelf.
- De opdrachttekst noemde de testadministratie bij haar RLZ-adminId (`8dbfb856…`); platform-id is `faae29c5`, gearchiveerd zonder credential
  (regel 22-09 "stand van de testadministratie éérst toetsen" — hier alsnog getoetst).

## Keuzes (Peter keek niet mee)

1. Niets ingediend: de enige toegestane plek (testadministratie) is gearchiveerd zonder credential; een klantadministratie is uitgesloten.
2. Poging 2 als vervolg-opdracht mét `niet vóór: 2026-09-23 09:00` (hoogstens 3 pogingen, daarna `mislukt/` mét klikpunt) — een echte kantoor-
   indiening van morgen meet het pad zonder klik.
3. De `rlz-bank-sync`-scheduler niet "gefixt": on-demand is bedoeld gedrag, `f3_jobs.sh` en `nameting.yml` vangen "geen scheduler" al zichtbaar.
4. IAM voor `cloudscheduler.viewer` niet zelf gezet (owner-terrein; alleen als beslispunt genoteerd).

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/werkloop-productie.md` (276 regels — stand vóór de run)
- `docs/regels/reconciliatie.md` (226 regels — stand vóór de run)
- `docs/regels/werkvoorraad-controlescherm.md` (391 regels — stand vóór de run)
