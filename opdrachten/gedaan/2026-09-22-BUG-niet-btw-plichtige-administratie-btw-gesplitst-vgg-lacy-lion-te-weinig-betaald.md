uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-btw-plichtig-per-administratie-vgg-lacy-lion.md

Domeinen: btw, administraties-instellingen, werkvoorraad-controlescherm, bank, reconciliatie

# BUG 22-09 — Niet-btw-plichtige administratie (VGG): module splitst bruto/btw, RLZ boekt alleen het netto → openstaande post
# en betaling € 322,38 te laag (Studio Lacy Lion 2026-042, RLZ-04-00000925)

**Feiten (screenshot Peter 22-09):** Vastgoedgroep Nederland, Studio Lacy Lion, factuur 2026-042 d.d. 11-09-2026, totaal € 1.857,51
(1.535,13 + 21 % 322,38), aangeboden 15-09, akkoord Sophia Gerritsen 16-09 + Kempen 18-09, geboekt RLZ-04-00000925 als regel 4106
Schoonmaakkosten bruto 1.535,13 / btw 322,38 / 21 % NL Hoog. VGG is NIET btw-plichtig (besluit Peter 13-09, `odoo/rj220.py`,
`migratie/vertaling.py`): RLZ heeft in die administratie geen btw-afwikkeling en boekt de crediteurpost op 1.535,13 → de
betaling volgt de open post → € 322,38 te weinig betaald aan de leverancier. De harde check "Btw-bedrag past bij tarief" was groen
(21 % van 1.535,13 klopt) — de check toetst het tarief, niet of de administratie überhaupt btw mag splitsen. De module kent GEEN
administratie-kenmerk "btw-plichtig"; de kennis zat alleen in de VGG-migratiecode.

## Opdracht
1. **Kenmerk `btw_plichtig` op de administratie** (migratie; default `true`; bron = RLZ-instelling als die leesbaar is — STAP-0:
   `Administrations/{id}` / instellingen-route op `rlz-lezen --root` naar een veld dat de btw-status draagt; niet leesbaar =
   mens-instelling in Instellingen › Administraties mét herkomst-chip, en dan óók een detector: administratie zonder enige
   `TaxRates` mét percentage > 0 of zonder btw-aangifteperiodes = kandidaat "niet btw-plichtig" → LET-OP "bevestig btw-status").
   VGG op `false` (besluit 13-09, capture); Peter geeft de rest van de lijst (verhuurders zonder optie belaste verhuur:
   ARVUM? Rubicon? Mantelzorgwoningen? — het rapport levert de kandidatenlijst uit de detector, Peter beslist).
2. **Gedrag bij `btw_plichtig = false`** — btw bestaat niet in die administratie: prefill zet élke regel op bruto = factuurbedrag
   incl., btw 0, btw-code = de "geen btw"-code van die administratie (of leeg als RLZ er geen kent — dan géén `TaxRate` in de PUT);
   de btw-keuzelijst is verborgen mét chip "administratie niet btw-plichtig — btw zit in de kosten"; harde check
   **"Btw in niet-btw-plichtige administratie"**: btw-bedrag ≠ 0 of tarief > 0 % = blokkerend, actie "Btw in de kosten zetten"
   (één klik, herrekent alle regels). Regelsom-check blijft: Σ bruto = factuurtotaal incl. Geldt voor inkoop, verkoop (Vastly
   380/381: huur vrijgesteld — zelfde regel), kassarapport en doorbelasting-spiegel in zo'n doeladministratie (spiegel-inkoop
   incl. btw als kosten — check `doorbelasting/boeken.py`, IC-facturen "met btw" per besluit Peter blijven aan de BRON-kant mét btw).
3. **Nazorg (lees-only CLI `btw-in-niet-plichtige-administratie --administratie … --jaar 2026`, job-image/leesreplica + RLZ GET):**
   álle module-boekingen én RLZ-documenten 2026 in VGG mét TaxAmount ≠ 0 op regelniveau; per document: boekstuk, leverancier,
   referentie, netto/btw/bruto module vs. bedrag crediteurpost RLZ vs. betaald (bank `OpenAmount`/afgeletterd) → kolom
   "te weinig betaald". Dat is Peters lijst om na te betalen. Herstel per document = "Corrigeren…" (gebouwd 21-09) mét de regel op
   bruto 1.857,51 / btw 0; aangiftepoort n.v.t. (geen aangifte in VGG) — bevestigen in het rapport. Lacy Lion eerst als bewijs
   (Peter klikt Corrigeren; verwacht daarna crediteurpost 1.857,51, restant 322,38 open voor de nabetaling).
4. **Vastly-/Odoo-raakvlak:** VGG-replay houdt al `tax_ids = []`; ARVUM-pilot (parallel-modus) erft het kenmerk → Odoo-company zonder
   btw-mapping als `btw_plichtig = false`. Noteer in `docs/ONTWERP_VASTLY_ODOO.md` §2.1.
5. Tests (prefill, harde check + actie, PUT zonder TaxRate, doorbelasting-doel, detector, CLI); rapport + INDEX + Gelezen regels;
   BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)"; regels btw +
   administraties; WAT_IS_NIEUW; CLAUDE.md één regel onder btw.
