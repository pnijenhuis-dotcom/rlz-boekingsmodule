uitgevoerd 2026-09-21, rapport: docs/rapporten/2026-09-21-iban-wissel-cache.md

Domeinen: werkvoorraad-controlescherm, autoboeken-ai, duplicaten-crediteuren

# BUG 21-09 — IBAN-wissel blijft "Blokkerend" ná het vier-ogen-akkoord: de checks-cache (0165) draagt de oude vertrouwde set

**Feit (screenshot Peter 21-09 ~09:30, Beleggingsmaatschappij Meyer B.V., Belastingdienst voorlopige aanslag Vpb 2025
0015.21.664.V.51.0112, € 34, IBAN NL04RABO0200112244):** de check "IBAN-wissel" staat op **Blokkerend** — "wijkt af van de
vertrouwde rekening(en) … · gecontroleerd 09:15 (ongewijzigd)" — terwijl het IBAN-paneel eronder LIVE zegt: **"Dit IBAN staat al in de
vertrouwde set van deze crediteur"**. Peter heeft het IBAN ná 09:15 via de vier-ogen-accordering laten goedkeuren; het scherm spreekt
zichzelf tegen en "Ter accordering →" blijft de enige knop.

**Oorzaak (code gelezen):**
- `app/documenten/checks_extern.py::vingerafdruk` hasht crediteur/cluster, referentie, datum, bedrag, factuur-IBAN, boek_cyclus,
  backend — de VERTROUWDE IBAN-SET zit er niet in. Het gecachte `ExternRapport` draagt `vertrouwde_ibans` (de seed van 09:15) en is
  15 min geldig (`checks_extern_cache_minuten`).
- `app/documenten/iban_accordering.py::accordeer` voegt het IBAN inline aan `leverancier_iban` toe en zet het document terug naar de
  herkomst-status; de docstring zegt "de harde checks draaien bij de boekactie sowieso opnieuw" — dat was waar vóór 0165. Sinds
  18-09 hergebruikt óók `boeken` het rapport (modus AUTO) → het akkoord werkt tot 15 min lang nergens door, ook niet bij boeken.
- Zelfde gat voor `leverancier_iban.bevestig_iban` (directe bevestiging) en voor élke andere mutatie van de vertrouwde set (seed,
  baseline, crediteur-samenvoegen via `crediteuren/voorkeur.py`).

## Opdracht
1. **Cache-invalidatie op de bron, niet op tijd:** één helper `checks_extern.maak_ongeldig_voor_vendor(administratie_id, vendor_id)`
   (verwijdert/markeert álle `check_extern_cache`-rijen van documenten van die crediteur + identiteitscluster) — aanroepen in
   `iban_accordering.accordeer`, `leverancier_iban.bevestig_iban`, `_voeg_toe` (seed/baseline) en bij crediteur-samenvoegen. Dezelfde
   sessie/transactie als de mutatie (geen race met een lopende boekactie: de wachtrij-claim leest de cache ná commit).
2. **Vingerafdruk verbreden als tweede slot:** neem een hash van de gesorteerde vertrouwde set (uit `vertrouwde_ibans()`, lokaal, geen
   RLZ-call) op in `vingerafdruk` — dan is een verouderd rapport per definitie ongeldig, ook als een invalidatie-pad ooit vergeten wordt.
   Kosten: één lokale query per checks-run, geen externe call.
3. **Boeken-pad:** de IBAN-check bij `boeken` toetst ALTIJD tegen de live vertrouwde set (lokaal), alleen de RLZ-seed mag uit de cache.
   Regel scherp in `docs/regels/autoboeken-ai.md` rij 5: "extern gecachet = RLZ-roundtrips; álle lokale toetsen (IBAN-set, duplicaat
   module, btw) draaien vers".
4. **Scherm:** zolang een check en het paneel eronder elkaar tegenspreken is er een bug — voeg een frontend-test toe op het patroon
   "check blokkerend + paneel 'staat al in de vertrouwde set'" = onmogelijk (of één bron voor beide). De regel "gecontroleerd 09:15
   (ongewijzigd)" krijgt een `linkbtn` "Opnieuw controleren" (modus VERS) zodat een mens nooit op de klok hoeft te wachten.
5. **Tests:** akkoord → cache ongeldig → volgende checks-run OK; bevestig_iban idem; boeken direct ná akkoord slaagt binnen de
   15-min-termijn; guard dat élk schrijfpad naar `leverancier_iban` de invalidatie aanroept (grep-test over de module).
6. **Nazorg productie (ná deploy, job-image):** CLI `checks-cache-legen --administratie <id>|--alles` (schrijvend, één keer via
   `gcloud run jobs execute`) zodat bestaande stale rapporten weg zijn; meetrecept: het Meyer-document (referentie
   0015.21.664.V.51.0112) toont ná herladen IBAN-wissel = OK en "Boeken in RLZ" beschikbaar.
7. Rapport `docs/rapporten/2026-09-21-iban-wissel-cache.md` + INDEX + Gelezen regels; BESLISSINGEN-rij "CHECKS-CACHE — INVALIDATIE OP
   DE BRON (IBAN-akkoord) 21-09"; WAT_IS_NIEUW één regel; CLAUDE.md één verwijsregel (werkvoorraad rij 7 aanvullen); les
   `Platform/registers/verbeteringen.md`: een cache op tijd zonder invalidatie op de muterende handelingen maakt elk mens-akkoord
   tijdelijk onzichtbaar — bij élke nieuwe cache eerst de lijst "welke handelingen maken dit ongeldig".
