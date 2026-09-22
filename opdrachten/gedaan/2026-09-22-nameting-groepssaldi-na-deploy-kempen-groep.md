uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-nameting-groepssaldi-na-deploy.md

Domeinen: administraties-instellingen, reconciliatie, werkloop-productie
niet vóór: 2026-09-22 09:00

# Nameting groepssaldi "Kempen groep" ná de deploy van de fix van 21-09 (RLZ-enumfilter + Odoo `deprecated`) — Peters antwoord van 16-09

**Context:** rapport `docs/rapporten/2026-09-21-groepssaldi-fix.md`, BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)". De fix (commit van 21-09) is
alleen live ná de deploy; de eerste groene nachtelijke stand komt uit de `sync-alles` van 22-09 07:00. Daarom `niet vóór: 2026-09-22 09:00`.

## Stap 0 — deploy-check (service ÉN jobs op een image ≥ de fix-commit; `git rev-list --count main..origin/main` toetsen en `merge --no-ff` als > 0).

## Stap 1 — live + stand (dispatch-onderdeel; geen lokaal proces tegen productie)
```
gh workflow run nameting -f onderdeel=groep-saldi        # → verkenning/nameting-groep-saldi-22-09.txt (bot-commit op main)
```
Verwacht: 35 leden, 35 × `ok` (of `geen_rekening`/`overgeslagen` mét reden), **0 × `fout`**; TOTAAL-regel; bruto = zonder-IC + IC per kolom
(cent-exact); in de `--stand`-sectie 0 "zonder nachtelijke stand". Rapportregel per lid: naam, status, debiteuren, crediteuren, IC-deel — dat
rapport is Peters antwoord op "huidig saldo debiteuren/crediteuren Kempengroep" (16-09). Géén debiteur-/crediteurnamen.

## Stap 2 — regressie-detector (verwachting vooraf, audit-spoor in de code aangewezen: `run._registreer_regressies`)
De reconciliatie-run van 22-09 06:30 las nog de stand van 21-09 (oude image → 35 × `fout`) → verwacht precies één LET-OP `groep_saldo_fout`
(blok `automatisering`, administratie NULL) + één audit `automatisering_regressie` mét `categorie: groep_saldo_fout` + bewakingsalert.
Toets via `nameting -f onderdeel=query -f query="reconciliatie-bevindingen …"` of `/reconciliatie`. Op 23-09 06:30 moet de LET-OP weg zijn
(stand 22-09 groen) — als de run van 23-09 nog vóór deze opdracht ligt, beide meten.

## Stap 3 — rapport
`docs/rapporten/2026-09-22-nameting-groepssaldi-na-deploy.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee" letterlijk; een
alinea "Gemeten 22-09" onder de BESLISSINGEN-sectie van 21-09 en in `docs/regels/administraties-instellingen.md`. Rood (≥ 1 `fout`) = de
letterlijke melding in het rapport + fix in dezelfde run als het een codefout is.
