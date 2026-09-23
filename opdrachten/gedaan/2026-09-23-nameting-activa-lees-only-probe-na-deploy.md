uitgevoerd 2026-09-23, rapport: docs/rapporten/2026-09-23-nameting-activa-lees-only-probe.md

Domeinen: activa, reconciliatie, werkloop-productie
niet vóór: 2026-09-23 09:00

# Nameting: lees-only reconciliatieblok `activa` schrijft de register-probe niet meer (fix 22-09) + activa-kaart-klikpunt

**Context:** rapport `docs/rapporten/2026-09-22-nameting-activa-fase1-en-bua.md` (bijvangst 3), BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD
(Peter 21-09)" alinea "Gemeten 22-09". Op 22-09 verplaatste `reconciliatie-alles --alleen activa --lees-only` bij 75 administraties
`activa_instelling.register_geprobeerd_op` naar het meetmoment (10:18–10:19 UTC) terwijl de run "niets vastgelegd" meldde. Fix: `probe_register(…,
schrijf=False)` bij `verzamelaar is None`. De fix gaat mét de commit van 22-09 live; de `sync-alles` van 23-09 07:00 NL zet het probe-tijdstip
weer op het sync-moment.

## Stap 0 — deploy-check (service ÉN jobs ≥ de commit van 22-09 mét `test_lees_only_run_schrijft_de_probe_stand_niet`;
`git rev-list --count main..origin/main` = 0 anders `merge --no-ff`).

## Stap 1 — nulstand vóór de lees-only run
```
gh workflow run nameting -f onderdeel=query -f query="activa-stand --administratie 'Pilates Bloom'"
```
Noteer rij `register_probe` → `tijdstip` (verwacht: 2026-09-23 ~05:01 UTC = de sync van 07:00 NL) en `sleutel` `leesbaar`.

## Stap 2 — lees-only run
```
scripts/gcp/nameting.sh reconciliatie-alles --alleen activa --lees-only
```
Verwacht: "75 administratie(s) mét MVA-rekeningen getoetst", soorten in `meten`, register 2 (Universal Steigerbouw, Rubicon) tenzij Peter het
RLZ-recht "Vaste activa" intussen zette.

## Stap 3 — nastand
Zelfde query als stap 1. **Oordeel:** `register_probe.tijdstip` ONGEWIJZIGD t.o.v. stap 1 = werkt in productie JA; verschoven naar het
meetmoment van stap 2 = ROOD (fix niet live of niet werkend → BUG-opdracht). Doe dezelfde toets op Universal Steigerbouw (403-pad):
`activa-stand --administratie 'Universal Steigerbouw'`.

## Stap 4 — activa-kaart (klikpunt, geen mens = "niet gemeten"): staat er intussen een module-document mét een boekvoorstelregel op een
`is_activa`-rekening ≥ € 450 (rij `koppeling` in `activa-stand`, of request-log `POST …/activa-voorstel/aanmaken`)? Dan de kaart-flow meten
(koppeling `aangemaakt` + `rlz_fixed_asset_id` gevuld + `PUT FixedAssets` in het log). Anders eerlijk "niet gemeten" + klikpunt herhalen.

## Stap 5 — rapport `docs/rapporten/2026-09-23-nameting-activa-lees-only-probe.md` + INDEX + "## Gelezen regels"; "werkt in productie:
ja/nee/niet gemeten"; alinea onder BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)" en in `docs/regels/activa.md`. Is de meting
niet uitvoerbaar (deploy niet live): opdracht terugleggen mét `niet vóór:` +1 dag (rij (k)), max 3×.
