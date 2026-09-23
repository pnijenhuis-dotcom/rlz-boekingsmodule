uitgevoerd 2026-09-23, rapport: docs/rapporten/2026-09-23-nameting-groepssaldi-status-enum-fix.md

Domeinen: administraties-instellingen, reconciliatie, werkloop-productie
niet vóór: 2026-09-23 09:00

# Nameting groepssaldi "Kempen groep" ná de deploy van de fix van 22-09 (tweede enum-veld `Status` op de open posten) — poging 2 van Peters antwoord van 16-09

**Context:** rapport `docs/rapporten/2026-09-22-nameting-groepssaldi-na-deploy.md`, BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09
(enumfilter + deprecated)" alinea "Gemeten 22-09". De nameting van 22-09 vond 29/35 leden opnieuw `fout` (`Status eq 2` in `$filter` op
Sales-/PurchaseInvoices = 400 `Reeleezee.DTO.DocumentStatus` vs Edm.Int32); de fix (client-side Status-toets, commit van 22-09) is alleen
live ná de deploy; de eerste groene nachtelijke stand komt uit de `sync-alles` van 23-09 07:00. Daarom `niet vóór: 2026-09-23 09:00`.

## Stap 0 — deploy-check (service ÉN jobs op een image ≥ de fix-commit van 22-09; `git rev-list --count main..origin/main` toetsen en
`merge --no-ff` als > 0).

## Stap 1 — live + stand (dispatch-onderdeel; geen lokaal proces tegen productie)
```
gh workflow run nameting -f onderdeel=groep-saldi        # → verkenning/nameting-groep-saldi-23-09.txt (bot-commit op main)
```
Verwacht: 35 leden, 35 × `ok` (of `geen_rekening`/`overgeslagen` mét reden), **0 × `fout`** in BEIDE secties (live én `--stand`); TOTAAL-regel;
bruto = zonder-IC + IC per kolom (cent-exact); IC-kolommen nu wél gevuld (op 22-09 live waren ze alleen voor de 6 leden zonder IC-entity's
te lezen). Dat rapport is Peters antwoord op "huidig saldo debiteuren/crediteuren Kempengroep" (16-09). Géén debiteur-/crediteurnamen.
Leesreplica-toets erbij: `SELECT datum, status, count(*) FROM boekhouding.groep_saldo_stand WHERE datum >= current_date - 2 GROUP BY 1,2`
via `scripts/gcp/db_lezen.sh … --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5` → 23-09: 35 × ok.

## Stap 2 — regressie-detector (verwachting vooraf; audit-spoor `run._registreer_regressies`)
De reconciliatie-run van 23-09 06:30 leest nog de stand van 22-09 (29 × `fout`) → verwacht één LET-OP `groep_saldo_fout` mét `aantal: 29`
en een NIEUWE vingerafdruk (andere set dan de 35 van 22-09) + één audit `automatisering_regressie` `categorie: groep_saldo_fout` op 23-09
~04:46 UTC. Toets via de leesreplica (`reconciliatie_bevinding` join `reconciliatie_run`, `detail->>'reden' = 'groep_saldo_fout'`;
de LET-OP staat NIET in de job-stdout). Op 24-09 06:30 moet de LET-OP weg zijn (stand 23-09 groen) — als de run van 24-09 al gelopen is
vóór deze opdracht start, beide meten; anders als verwachting in het rapport + geen derde vervolg-opdracht (de detector is bewezen).

**Let op looptijd:** de live-executie van 22-09 duurde 41 min (jobtimeout `rlz-reconciliatie` 3600 s) — ná de fix leest `ic_open` méér
(concepten/gesloten facturen van IC-entity's komen mee) → een timeout is een uitkomst om te rapporteren (beslispunt 2 van 22-09), geen reden om lokaal
te meten. Neem in het rapport óók beslispunten 3/4 van 22-09 mee (Odoo `159000 VAT tax liabilities` als crediteurenrekening; Odoo-leden € 0,00).

## Stap 3 — rapport
`docs/rapporten/2026-09-23-nameting-groepssaldi-status-enum-fix.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee" letterlijk;
een alinea "Gemeten 23-09" onder de BESLISSINGEN-sectie en in `docs/regels/administraties-instellingen.md`. Rood (≥ 1 `fout`) = de letterlijke
melding in het rapport + fix in dezelfde run als het een codefout is — en dan éérst álle `$filter`-strings van `saldi.py` naast de
api-verkenning leggen (les 22-09 in `werkloop-productie.md`).
