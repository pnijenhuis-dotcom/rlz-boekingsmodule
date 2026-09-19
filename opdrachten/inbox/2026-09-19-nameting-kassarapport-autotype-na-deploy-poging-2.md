Domeinen: omzet, reconciliatie, werkloop-productie

# OPDRACHT 19-09 — Nameting + nazorg ná deploy: kassarapport automatisch typeren — POGING 2 (vervolg op
# docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-1-deploy-geblokkeerd.md; nulmeting Van Boxtel staat daar)

**Stap 0 (voorwaarde, in deze volgorde):** (a) `git fetch origin && git rev-list --count main..origin/main` = 0 — anders eerst
`git merge --no-ff origin/main` (nooit rebase/force) en de run NIET verder laten meten (push volgt pas bij de Stop-hook); (b) `gh run list
--workflow=deploy.yml --limit 3` groen op een commit dat `a5c0663` bevat (`git merge-base --is-ancestor a5c0663 <sha>`); (c) service
`rlz-backend` én job `rlz-reconciliatie` op datzelfde image (`gcloud run services list --region europe-west4` /
`gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format=json` → `spec.template.spec.template.spec.containers[0].image`).
Niet gedeployd = opdracht terug in de inbox mét de reden bovenin, nooit een lokaal proces tegen productie.

## Nazorg + meetrecept (verwachtingen uit de nulmeting van poging 1, leesreplica 19-09 ~15:58)
1. `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,kassarapport-autotype-nazorg,--dry-run,--administratie,Van Boxtel"`
   → verwacht "1 administratie(s), 4 kandidaat/kandidaten, zou omzetten 4" = Journaal **31-8**, 1-9, 2-9, 3-9 (`8631403e`, `37e1b23e`,
   `cbef27bc`, `0b571db4`); Journaal 4-9 (`4e120087`) is GEEN kandidaat (alleen het zachte signaal omzetrekeningen). Dan de echte run
   (zonder `--dry-run`; of de reconciliatie van 06:30 als die al gelopen is — dan de audit-rij `kassarapport_autotype_run` lezen), daarna
   kantoorbreed `--dry-run` = 0 kandidaten. Log via `gcloud logging read` op de executienaam.
2. Leesreplica (`scripts/gcp/db_lezen.sh … --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5 --administratie cd973c86-5b06-43b2-9fc9-81ffb8461e08`):
   de vier documenten soort `kassarapport` (status ONTVANGEN → extractie via het omzetpad), tijdlijnregel "type automatisch gewijzigd",
   audit `soort_automatisch_gewijzigd` 4× + `kassarapport_autotype_run` 1× (verwacht 4 / gedaan 4 / overgeslagen 0).
3. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen omzet --lees-only` → Van Boxtel: 1 × `kassarapport_in_werkvoorraad`
   (Journaal 4-9, signaal omzetrekeningen), 0 × profx, 8 × `omzet_in_inkoopstroom` ongewijzigd; Inzicht › Reconciliatie 340 → 336 aandacht
   (vergelijk mét de laatste afgeronde run, nulmeting run `772e6c3c` 19-09 06:44: omzet 13 afwijkingen). Systeemmail/Instellingen › Boeken:
   teller `kassarapport_autotype` gedaan 4.
4. Rapportregel "werkt in productie: ja/nee" + INDEX; BESLISSINGEN-status van "niet gemeten" naar "gemeten <datum>" (sectie "KASSARAPPORT
   AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)", statusalinea én de rij "poging 1").
Lees-only behalve de nazorg-CLI (stap 1 = expliciete schrijvende nazorg via `gcloud run jobs execute`).
