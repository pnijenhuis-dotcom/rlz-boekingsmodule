uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-claude-md-regels-per-domein.md

# OPDRACHT 17-09 — CLAUDE.md: volledige regels per domein in `docs/regels/`, verplicht gelezen vóór werk; CLAUDE.md = harde kern + leesplicht

**Aanleiding:** CLAUDE.md ~142k tekens tegen de limiet van 150k (stille afkap). **Eis Peter 17-09:** NIET alleen "zie BESLISSINGEN"
— dat ging eerder mis (CC bouwde/adviseerde zonder de volledige tekst te lezen; verwijzingen naar een 1,3 MB register worden niet
gevolgd). De volledige tekst moet bewaard, vindbaar én gegarandeerd gelezen worden vóór iemand aan dat domein werkt. CLAUDE.md zelf
groter maken kan niet (technische limiet) en helpt niet (alles wat erin staat kost bij élke sessie context, ook voor werk aan een ander
domein).

## Oplossing (bouwen, geen beslispunt)
1. **`docs/regels/<domein>.md` per domein** (bijv. `accordering.md`, `bank.md`, `omzet.md`, `vgg-migratie.md`, `reconciliatie.md`,
   `native-app.md`, `werkloop.md`, `duplicaten.md`, `btw.md`, …): de VOLLEDIGE, woordelijke CLAUDE.md-tekst van dat domein (niets
   samenvatten, niets weglaten), mét datum/migratie/BESLISSINGEN-sectie per alinea, chronologisch. Ook de 07-09-verplaatste teksten uit
   BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" komen hierheen (kopie blijft in BESLISSINGEN als historie).
2. **CLAUDE.md** houdt: Kernprincipes, Stack, RLZ-API-feiten, harde werkregels (git, productie, feiten eerst, migraties, bash, pre-commit),
   referenties — en per domein PRECIES één blok van 3–6 regels: wat het is, de bindende hoofdregels, en de regel
   **"LEESPLICHT: lees `docs/regels/<domein>.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet
   beginnen."** Doel ≤ 90k tekens.
3. **Afdwingen, niet hopen:**
   a. `scripts/cc_inbox.sh` + `rlz cc`: een opdracht draagt een kopregel `Domeinen: a, b` (Cowork schrijft die); de startprompt aan CC
      injecteert "Lees eerst volledig: docs/regels/a.md, docs/regels/b.md" en het eindrapport MOET een sectie "Gelezen regels" bevatten
      mét de bestandsnamen + regelaantallen; guard `tests/unit/test_rapporten_gelezen_regels.py` (rapport zonder die sectie = rood).
      Ontbreekt de kopregel → CC leidt de domeinen af uit de geraakte paden (`app/<pakket>` → domein-map in `docs/regels/INDEX.md`) en
      noemt dat expliciet.
   b. `docs/regels/INDEX.md`: domein → bestand → code-paden (`app/accordering/**`, `frontend/src/accordeur/**`, …). Guard
      `tests/unit/test_regels_index.py`: élk pakket onder `backend/app/` en élke map onder `frontend/src/` is aan een domein gekoppeld;
      élke CLAUDE.md-verwijsregel wijst naar een bestaand regelsbestand.
   c. Capture-at-acceptance blijft: een nieuw besluit → volledige tekst in `docs/regels/<domein>.md` + BESLISSINGEN-rij + hooguit één
      regel in CLAUDE.md; guard op CLAUDE.md-omvang: > 90k = waarschuwing in het rapport, > 120k = rood.
4. Rapport (mét oude/nieuwe omvang, aantal regelsbestanden, bewijs dat geen tekst verloren is: woordtelling vóór = ná over CLAUDE.md +
   regels-bestanden) + INDEX; BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT (Peter 17-09)"; WERKWIJZE-regel.
   Geen functionele code, geen migratie.
