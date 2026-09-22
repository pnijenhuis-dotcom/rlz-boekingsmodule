uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-nameting-activa-fase1-en-bua.md

Domeinen: activa, btw, reconciliatie, werkloop-productie
niet vóór: 2026-09-22 09:00

# Nameting activa fase 1 (is_activa-sync, register-probe, reconciliatieblok `activa`) + lees-only `bua-kandidaten` ná de deploy van 21-09

**Context:** rapport `docs/rapporten/2026-09-21-activa-fase1-bua-vgg-toewijzing-universal-overhead.md` (secties A en B), BESLISSINGEN
"ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)" en "BUA-KENMERK — LEES-ONLY METING + BULK-VOORSTEL (Peter 21-09)". De kolom `is_activa` en de
RLZ-grens/probe worden gevuld door de `sync-alles` van 22-09 07:00 op de nieuwe image; daarom `niet vóór: 2026-09-22 09:00`.

## Stap 0 — deploy-check (service ÉN jobs ≥ de commits van 21-09; `git rev-list --count main..origin/main` = 0 anders `merge --no-ff`).

## Stap 1 — is_activa + instelling (query-onderdeel, lees-only)
```
gh workflow run nameting -f onderdeel=query -f query="…"   # of scripts/gcp/db_lezen.sh op de replica, per administratie (RLS)
```
Verwacht (nulmeting 21-09 als meetlat): Pilates Bloom B.V. 4 rekeningen `is_activa` (0101/0107/0111/0113), `activa_instelling` mét
`grens_rlz` 450,00 en `register_leesbaar` true; Universal Steigerbouw `register_leesbaar` false mét `register_fout` "recht ontbreekt (403)";
platformbreed ≈ 344 `is_activa`-rekeningen over 75 administraties. Afwijking = systeemfout in de sync → fix in dezelfde run.

## Stap 2 — reconciliatieblok `activa` (lees-only)
```
scripts/gcp/nameting.sh reconciliatie-alles --alleen activa --lees-only
```
Verwacht: blok draait per RLZ-administratie mét ≥ 1 `is_activa`-rekening; soorten `activa_register_niet_leesbaar` (Universal, Rubicon),
`afschrijving_niet_gelopen`/`activum_zonder_boeking`/`mva_boeking_zonder_activum` in stand `meten` (facet "in meting", géén actiemail);
explosie-rem < 50 per soort. Tel per soort en leg de eerste tien bevindingen (administratie, tekst) in het rapport.

## Stap 3 — kaart in productie (klikpunt, geen mens = "niet gemeten"): open bij Pilates Bloom een inkoopfactuur mét een regel op 0107/0111/0113
≥ € 450 → kaart "Activum aanmaken?" zichtbaar; request-log `GET …/activa-voorstel` 200. Geen zo'n factuur = eerlijk "niet gemeten".

## Stap 4 — BUA (lees-only): `scripts/gcp/nameting.sh bua-kandidaten` (dispatch-onderdeel `bua-kandidaten`) → tabel moet de replica-meting van 21-09
bevestigen (4014/4503/4508/4510 over 74–75 administraties, kenmerk nergens aan, module 2026 alleen 4510 2 × € 34). `bua-kenmerk-zetten` NIET
draaien — dat wacht op Peters "ja" op het rapport (dan: `gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|bua-kenmerk-zetten|--alles|--dry-run"`, daarna zonder `--dry-run`).

## Stap 5 — rapport `docs/rapporten/2026-09-22-nameting-activa-fase1-en-bua.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee/niet
gemeten" per onderdeel; alinea "Gemeten 22-09" onder beide BESLISSINGEN-secties en in `docs/regels/activa.md` / `docs/regels/btw.md`.
