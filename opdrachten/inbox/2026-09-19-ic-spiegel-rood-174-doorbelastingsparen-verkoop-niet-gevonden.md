Domeinen: reconciliatie, doorbelasting-intercompany, intake-extractie

# SYSTEEMFOUT — 174 × `ic_spiegel_rood` "verkoopfactuur niet gevonden bij de bron-administratie" (sweep 19-09) + extractie-wachtrij 180× vangnet + tellers BLOW

**Aanleiding (rapport `docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md`, deel B):** sinds de eerste run van het
intercompany-blok (18-09 04:30 UTC) staan er 174 FOUT-rijen "Systeemfout — doorbelastingspaar niet sluitend Kempen Facilities B.V. →
‹doel› verkoop=‹UUIDv5› spiegel=‹UUIDv5› nummer=247133xx: verkoopfactuur niet gevonden bij de bron-administratie" (Veldhoven Recreatie 94,
Oirschot Recreatie 34, Molenhof Verhuur 28, Molenhof Beheer 11, Mantelzorgwoningen MN 7). Het blok `doorbelasting_aansluiting` geeft op
dezelfde paren 0 bevindingen. Niemand kan hier iets mee; het zijn 174 van de 340 "aandacht nodig" op Inzicht › Reconciliatie.

## Opdracht (lees-only diagnose eerst, dan fix; nooit een RLZ-write)
1. Diagnose op de leesreplica + `rlz-lezen`: neem 3 paren (bv. nummer 24713316/24713335/24713275) — bestaat het verkoop-GUID bij Kempen
   Facilities in RLZ (`SalesInvoices/{guid}`), en zo nee: welk GUID heeft de doorbelasting-verkoop wél (boek_cyclus/herboeking-GUID,
   `documenten/rlz_ids.py`)? Welk GUID/welke administratie gebruikt `app/intercompany/` bij de spiegel-toets t.o.v. `app/doorbelasting/`?
2. Fix in de IC-toets (waarschijnlijk: verkeerde GUID-afleiding of de bron-administratie-credential), test op de gouden set
   (casus n/o intercompany), meetlat `reconciliatie-alles --alleen intercompany --lees-only` → 0 × `ic_spiegel_rood` verwacht.
3. Zelfde run: automatiserings-LET-OP `extractie_wachtrij: 180 overgeslagen wegens ontbrekende harde voorwaarde [vangnet_scheduler]`
   (19-09) — de BLOW-bulk-upload van 18-09 liep via het 10-minuten-vangnet i.p.v. de directe job-trigger; Cloud Logging op
   `extractie_wachtrij_trigger` nalopen (429/quota bij 180 executies in enkele minuten?) en de trigger begrenzen (één executie per
   batch, dedupe binnen 30 s) — geen stille no-op. En de tellers-LET-OP BLOW te_controleren cache 151 ↔ telling 152: welk mutatiepad
   (bulk-upload 409 "al aanwezig"?) mist de cache-hook.
4. Rapport + INDEX + BESLISSINGEN-rij onder "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)";
   nameting ná deploy; committen zoals gebruikelijk.
