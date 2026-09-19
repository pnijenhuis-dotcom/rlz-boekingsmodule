Domeinen: omzet, reconciliatie, werkloop-productie

> **niet vóór: 2026-09-20 07:15** — meet ná de scheduler-run van 20-09 04:30 UTC (06:30 NL). Toegevoegd 19-09 avond (poging 1 van de
> ic_spiegel_rood-nameting werd om 18:57 al opgepakt; sinds rij (k) claimt de inbox-runner een opdracht pas ná dit moment).

# OPDRACHT 20-09 — Nameting kassarapport automatisch typeren ná de ÉCHTE reconciliatie-run van 20-09 06:30 + kantoorbrede nazorg-CLI ná de fix
# (vervolg op docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-2.md — daar staan alle tellingen van 19-09 18:00)

**Stap 0 (voorwaarde, in deze volgorde):** (a) `git fetch origin && git rev-list --count main..origin/main` = 0 — anders eerst `git merge --no-ff
origin/main` (nooit rebase/force) en de run NIET verder laten meten; (b) `gh run list --workflow=deploy.yml --limit 3` groen op een commit die de
fix-commit van poging 2 bevat (`git log --oneline --grep="scoped_session" -1` geeft de hash; `git merge-base --is-ancestor <fix> <sha>`); (c) service
`rlz-backend` én job `rlz-reconciliatie` op datzelfde image. (d) De reconciliatie-run van 20-09 06:30 UTC+2 is AFGEROND (leesreplica:
`SELECT id, gestart_op, afgerond_op FROM boekhouding.reconciliatie_run ORDER BY gestart_op DESC LIMIT 2`). Niet gedeployd / run niet gelopen = terug in de inbox mét reden bovenin.

## Meetrecept (verwachtingen uit poging 2)
1. Kantoorbreed `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,kassarapport-autotype-nazorg,--dry-run"`
   → **exit 0** (op 19-09 exit 1 = NameError), "N administratie(s), 0 kandidaat/kandidaten" — of de kandidaten die de run van 06:30 al omzette
   (dan de audit `kassarapport_autotype_run` van die run lezen). Log via `gcloud logging read` op de executienaam.
2. Leesreplica (`scripts/gcp/db_lezen.sh … --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5 --administratie cd973c86-5b06-43b2-9fc9-81ffb8461e08`):
   de vier profx-bevindingen `kassarapport_in_werkvoorraad` van Van Boxtel (Journaal 31-8/1-9/2-9/3-9) gesloten mét audit `reconciliatie_auto_gesloten`;
   open blijft 1 × Journaal 4-9 (omzetrekeningen) + 8 × `omzet_in_inkoopstroom`; audit `kassarapport_autotype_run` van de run van 06:30 voor Van Boxtel:
   verwacht 0 / gedaan 0 (alles was al omgezet) — en voor élke andere administratie mét een parser-treffer: gedaan > 0.
3. Inzicht › Reconciliatie aandacht-teller: 340 (run `772e6c3c` 19-09 06:44) → ≤ 336 (leesreplica: open bevindingen van de laatste afgeronde run, per soort);
   systeemmail/Instellingen › Boeken teller `kassarapport_autotype` 20-09: gedaan = aantal omgezette documenten in de run van 06:30 (0 bij Van Boxtel).
4. Stand van de vier documenten: nog `vraag_open` (kantoor heeft de categorie-mapping nog niet gezet) óf verder — alleen rapporteren, niets forceren.
5. Rapportregel "werkt in productie: ja/nee" voor aandacht-teller, auto-sluiting, dagteller en kantoorbrede CLI + INDEX; BESLISSINGEN-rij "poging 2"
   aanvullen (sectie "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)").
Lees-only behalve stap 1 (dry-run = 0 writes).
---
LEESPLICHT (Domeinen-kopregel): lees EERST volledig, vóór je iets anders doet: docs/regels/omzet.md, docs/regels/reconciliatie.md, docs/regels/werkloop-productie.md — niet gelezen = niet beginnen.
Werkloop automatisch (CLAUDE.md § Werkwijze "Werkloop automatisch (14-09)"): sluit af met (1) het eindrapport als docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md + regel bovenaan in docs/rapporten/INDEX.md (incl. "werkt in productie: ja/nee/niet gemeten" én een sectie "## Gelezen regels"), (2) dit opdrachtbestand naar opdrachten/gedaan/ mét kopregel "uitgevoerd <datum>, rapport: docs/rapporten/<bestand>", (3) committen zoals gebruikelijk (nooit pushen). Peter kijkt niet mee: kies zelf en leg keuzes vast in het rapport.
