uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-nameting-ic-spiegel-rood-na-deploy.md

Domeinen: reconciliatie, doorbelasting-intercompany, werkloop-productie

# OPDRACHT 19-09 — Nameting ná deploy: 174 × ic_spiegel_rood → 0, aansluitingsblok leeft, wachtrij-trigger gebundeld — vervolg op
# docs/rapporten/2026-09-19-ic-spiegel-rood-174-wachtrij-trigger-en-tellers.md

**Voorwaarde (stap 0):** de commit met `factuurmatch.VERKOOP_COLLECTIES` en `service._claim_status` is gedeployd op service ÉN jobs
(`gh run view` deploy.yml groen; `gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'` =
image van de service). Niet gedeployd = wachten, nooit een lokaal proces tegen productie.

## Meetrecept (lees-only)
1. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen intercompany --lees-only` → verwacht 0 × `ic_spiegel_rood`;
   Kempen Facilities → Veldhoven/Oirschot Recreatie/Molenhof Verhuur/Molenhof Beheer/Mantelzorgwoningen: "spiegelparen N/N groen",
   Mantelzorgwoningen "51 verkoop / 51 inkoop gelezen, 51 gematcht" (was 44/51/44). Tel ook `ic_ontbreekt_bij_verkoper` (in meting): moet
   met de 174 spiegels dalen.
2. `… --alleen doorbelasting_aansluiting --lees-only` → "1 bron-administratie(s) mét whitelist" (was 0), KF: 8 doelen gelezen; bevindingen
   per soort noteren (verwacht 0; Kempen Chalets/Rubicon zonder boekingen in het venster = geen bevinding).
3. Leesreplica ná de run van 06:30 (`db_lezen.sh`, NULL-scope): `reconciliatie_bevinding` blok intercompany soort fout = 0; audit
   `reconciliatie_auto_gesloten` voor de 174; Inzicht › Reconciliatie aandacht 340 → ≤ 166.
4. Tellers: reconciliatiemail-regel "Extractie-wachtrij" — bij de eerstvolgende bulk-upload `trigger_gebundeld` > 0, `vangnet_scheduler` 0;
   `gcloud run jobs executions list --job rlz-extractie-wachtrij` ≈ 6/uur + 1 per batch (was 118 op 18-09 11:00).
5. Nazorg BLOW (klikwerk of CLI): document c9ba6d8d ("2023-12-13_div. crediteuren_20230872.pdf") staat op te_controleren maar was om
   11:05:20 als duplicaat van 20230872 afgevoerd — opnieuw afvoeren via de duplicaten-knop (nooit verwijderen).
6. Rapportregel "werkt in productie: ja/nee" + INDEX; BESLISSINGEN-rij "Systeemfout ic_spiegel_rood 174×" van "niet gemeten" naar
   "gemeten <datum>".
