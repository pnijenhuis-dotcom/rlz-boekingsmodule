# Slotrapport 16-09 — inbox afgewerkt (opdracht Peter 16-09: drie opdrachten in volgorde + één tijdens de run binnengekomen)

**Werkt in productie: niet gemeten** voor alle vier (geen deploy binnen de run — de push loopt via de Stop-hook; meetrecept per
opdracht hieronder). Geen enkele write naar RLZ of Odoo; productie is alleen lees-only geraakt via `scripts/gcp/nameting.sh
rlz-lezen` en `gcloud logging read`. Migraties 0147 en 0148 volgens de afsluitroutine (dev-upgrade, `alembic check`, live 401/200
op een lokale uvicorn, schema-dump ververst @ head 0148). Volledige backend-suite ná opdracht 2: 6132 groen (één blokvolgorde-
assert bijgewerkt); ná opdracht 4: 6169 groen (zie de laatste regel). `tsc -b` groen op élke commit (pre-commit-hook).

## Per opdracht

| # | Opdracht | Gedaan | Commits | Rapport | Productie |
|---|---|---|---|---|---|
| 1 | Duplicaat Zenvoices (Hello Kitchen, Kempen Facilities) + dubbele betaling + bewust verwijderd | JA — wortel bewezen (referentie mét spaties vs Zenvoices zonder; twee verschillende vergelijkingen, geen van beide vond het paar), één normalisatie + `boekvoorstel.referentie_norm` (0147), bestaanscheck over de crediteur-identiteit in een datumvenster als signaal én harde poort op het boekmoment, lees-only `duplicaat-extern-rapport`, bank-bevinding + chip `dubbele_betaling_vermoed`, knop "Bewust verwijderd in RLZ" (zonder Afwijzing-rij — DB-CHECK, beslispunt), gouden-set-casus aa; terugvorderingsdossier € 28.850,00 | `0aa060f` `247a586` `9c3714e` `678e326` `1c87cb0` | `2026-09-16-duplicaat-zenvoices.md` | niet gemeten |
| 2 | Intercompany-factuurmatch + rekening-courant-aansluiting | JA — identiteit uit RLZ `AdministrationSettings`/Odoo `res.company`, IC-relaties en RC-koppelingen AFGELEID (Beheerder bevestigt/sluit uit; blok op Instellingen › Boeken), reconciliatieblokken `intercompany` en `rekening_courant` mét mensentaal-bevindingen in de actiemail, spiegelparen als systeemfout-bewijs, webfilter = meting ongeldig (0148) | `1a07424` `305d178`(deels) `73caa5c` `b51f242` `3a572a1` `63022dd` | `2026-09-16-intercompany-rc.md` | niet gemeten |
| 3 | Activa/MVA STAP-0 + ontwerp (geen bouw) | JA — RLZ FixedAssets-DTO/actie-route/enumeraties root-only/vlag te breed/Universal 403, Odoo `account_asset` ongebruikt (0 activa), `docs/ONTWERP_ACTIVA_MVA.md` ter akkoord, lees-only `rlz-lezen --root` + `activa-nulmeting` (nameting-allowlist); nulmeting over alle 76 = meetrecept ná deploy | `305d178` `73caa5c` | `2026-09-16-activa-stap0.md` | n.v.t. (lees-only) |
| 4 | Omzetbronnen — besluiten Peter 16-09 (binnengekomen tijdens de run) | JA — punten = omzet, tegenzijde per betaalwijze (RLZ-vorm aflettering, default), bank-matchmotor omzetbatch-post, `tussenrekening_open`, pilates btw + combi pro rato, Stripe verlegd, Beheerder-blok Omzetbronnen | `c58f865` `23ab9b4` | `2026-09-16-omzetbronnen-besluiten.md` | niet gemeten |

## Niet gedaan in deze run (in `opdrachten/inbox/`, later binnengekomen — de inbox-runner pakt ze op zodra deze sessie eindigt)

- `2026-09-16-bank-zoekveld-boekstuknummer-batch.md` (feedback Peter: zoekveld bank + RLZ-boekstuknummer als match-token + batch-stap).
- `2026-09-16-deploy-mailconfig-in-service-stap.md` (deploy.yml: envs van de service in één stap — géén venster zonder SMTP).
- `2026-09-16-groepssaldi-debiteuren-crediteuren.md` (lees-only groepssaldi debiteuren/crediteuren, bouwt op opdracht 2).

## Bewust niet gebouwd / afwijkingen (met reden)

- Opdracht 1: zelfde bedrag + datum met een ánder nummer is een oranje signaal, geen blokkade (legitieme gelijke facturen, geen
  mens-override voor externe treffers); blok D zonder `Afwijzing`-rij (DB-CHECK `afwijzing_herkomst_herstelbaar`) → eigen marker +
  "Terugdraaien…"; eigen-DB-lezing productie geweigerd door de classifier → reconstructie uit Cloud Logging.
- Opdracht 2: RC-herkenning zonder "≥ 2 tokens"-eis (anders wordt "Kempen B.V." nooit herkend); handmatige IC-leveranciers zonder
  mapping krijgen geen relatie; RC-mutaties zonder boekstuknummer (JournalEntry geeft er geen).
- Opdracht 3: enumeratie-waarden (AssetTypes/ActionKinds) pas leesbaar ná deploy van `--root`; of RLZ zelf afschrijft is op 0-activa-
  administraties niet vast te stellen; nulmeting-tabel is een meetrecept.
- Opdracht 4: geen memoriaal-tussenrekening (credit-kant entity-loze Receipt ongeverifieerd) → aflettering; Stripe-kosten als
  Receipt-regel landen in rubriek 1e (beslispunt); Sunshine Island niet in code.

## Beslispunten

Alle beslispunten mét gekozen default staan in `docs/rapporten/2026-09-16-beslispunten-peter.md` (opdracht 1: 6, opdracht 2: 9,
opdracht 3: 7, opdracht 4: 8).

## Meetrecept ná deploy (Peter of Cowork)

1. Deploy-check: service ÉN jobs op hetzelfde beeld (`gcloud run jobs describe … image`).
2. Opdracht 1: `nameting.sh reconciliatie-alles --alleen bank --lees-only` → Kempen Facilities twee "Mogelijk dubbel betaald — Hello
   Kitchen Duiven"; `nameting.sh duplicaat-extern-rapport` (eerst `--administratie "Kempen Facilities"`); `nameting.sh
   referentie-norm-backfill --dry-run` → daarna de echte vulling via `gcloud run jobs execute rlz-reconciliatie
   --args="-m,app.cli,referentie-norm-backfill"`; Peter klikt de drie `ontbreekt_in_rlz`-rijen weg met "Bewust verwijderd in RLZ".
3. Opdracht 2: `sync-alles`-log "identiteiten/relaties/rc-koppelingen"; `nameting.sh reconciliatie-alles --alleen intercompany
   --lees-only` (KF-spiegelparen 100 % groen) en `--alleen rekening_courant --lees-only`; Instellingen › Boeken toont de relaties.
4. Opdracht 3: `nameting.sh activa-nulmeting` (alle administraties) en `nameting.sh rlz-lezen --administratie "Kempen Facilities"
   --pad AssetTypes --root` (+ AssetMutationTypes, ActionKinds) → waarden in api-verkenning noteren; daarna akkoord Peter op het
   ontwerp.
5. Opdracht 4: eerste dagstaat Elderveld/Sunshine Island → tegenzijde + punten als omzet; eerste Stripe-payout → bankvoorstel
   "omzetbatch … · Stripe" groen; ná 14 d `--alleen omzet --lees-only` → `tussenrekening_open`.

## Volledige backend-suite ná opdracht 4

`pytest --ignore=tests/integration` op de eindstand van de run: **6169 passed, 3 skipped in 39:06** (EXIT 0).
