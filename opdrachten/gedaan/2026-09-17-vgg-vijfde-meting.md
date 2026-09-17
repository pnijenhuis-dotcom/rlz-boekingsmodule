uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-vgg-vijfde-meting-en-auto-posten.md

# OPDRACHT 17-09 — VGG → Odoo run 2: VIJFDE METING ná deploy van blok 10 (één regel, één bestemming) + blok 11 (project-dekking) — lees-only, géén writes

Vervolg op `docs/rapporten/2026-09-17-vgg-blok-10-een-regel-een-bestemming.md` en `2026-09-17-vgg-blok-11-pand-uit-rlz-project.md`.

## Stap 0
- Deploy van de commits van 17-09 (blok 10 `990a6ad` e.v.) groen (`gh run list --workflow=deploy.yml --limit 1`), service = jobs.

## Stap 1 — meting
- `gh workflow run nameting -f onderdeel=c` → `verkenning/nameting-vgg-replay-<dd-mm>.txt` (of interactief `scripts/gcp/vgg_blok7_nameting.sh c`).
- Lees: saldibalans 3606/3607 = 0,00; sectie "1001-model": kolom "RJ-220-tegenzijde → rol" gevuld op de 14 aanbetalings-memorialen, `overlappen` 0;
  herclassificatietabel toont 16xx/1405 → 3606/3607 (niet meer `ongemapt:1001`); ROOD alleen nog op debiteuren/crediteuren (afletterstand SCHRIJF c);
  sectie "Project-dekking" (blok 11): aandeel pand-relevant, regels zonder project, kruistoets 83 projecten ↔ clusters.
- Rijtellingen tegen de JSON (print_gedoseerd).

## Stap 2 — oordeel + afronding
- BESLISSINGEN blok 10 + blok 11: alinea "Vijfde meting <datum>" mét uitkomsten + "werkt in productie: ja/nee"; rapport + INDEX; bij dekking ≥ 90 % → beslispunt "default `--bron project`".

## Aanvulling Peter 17-09 (bindend) — geen concept-berg, geen handwerk
Peter: "waarom alles in concept? Liever 1 boeking testen en als het goed gaat alles meteen definitief boeken (anders alsnog handmatig
werk)." Vertaling naar het plan, zonder de veiligheid weg te gooien:
1. Ná een GROENE vijfde meting: SCHRIJF c = het bewijspaar RLZ-01-00000082 écht POSTEN op company 6 (dat is de "1 boeking testen") +
   reconcilieren met de bankregel; rapport mét Odoo-move-ids en saldocontrole.
2. Volledige replay in ÉÉN run: concepten schrijven → automatische saldibalans-toets (cent-exact, per pand sluit) → **als groen: in
   dezelfde run alles posten** (bulk `action_post`), géén klikwerk. Als rood: niets posten, concepten laten staan mét rapport waarom.
   Zo blijft de toets vóór het onomkeerbare moment zitten, maar de mens hoeft niets meer aan te klikken.
3. GO van Peter = één woord op het rapport van stap 1; daarna start stap 2 automatisch als volgende inbox-opdracht. Wijzigt het besluit
   12-09 "alles concept" → BESLISSINGEN-rij "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)".
Klikpunt Peter blijft: IBAN op BNK1 (company 6) vóór stap 1.
