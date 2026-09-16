> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-betalen-eigenaar-jarvis.md

# OPDRACHT 16-09 (avond, HERZIEN 22:00) — Betalen via Ponto hoort NIET in de RLZ-module maar in Jarvis (besluit Peter 16-09); RLZ-kant = alleen koppelvlak-capture (docs-only, geen code)

**Besluit Peter 16-09 22:00 (vervangt de eerdere versie van dit bestand):** "ik wil dit niet in de N-module maar in Jarvis hebben,
dat onderscheid moet er wel zijn." Ponto-connector, betaalvoorbereiding, autorisatieflow en het betaalscherm zijn dus Jarvis-werk
(`Projects/Jarvis`, eigen bouwopdracht via Jarvis' J-010-procedure — Cowork schrijft daar het besluitvoorstel). Deze module bouwt
GEEN Ponto-client, GEEN betaalmodule, GEEN sandbox-STAP-0. Autorisatie van betalingen: door het kantoor als gevolmachtigde/
vertegenwoordiger op de klantrekening (besluit Peter 16-09 "wij gaan vertegenwoordiger laten betalen") — SCA blijft bankzijde.

## Wat de RLZ-module WEL doet (docs-only in deze run)
1. **BESLISSINGEN-registerrij** "BETALEN — EIGENAAR JARVIS, RLZ LEVERT FEITEN EN ONTVANGT STATUS (besluit Peter 16-09)": de
   RLZ-module blijft de ENIGE schrijver naar RLZ/Odoo (kernprincipe 1 + Jarvis-regel "schrijft nooit terug naar een bron"); Jarvis
   initieert betalingen bij de bank via Ponto en meldt de uitkomst terug; de RLZ-module vertaalt die naar `QuickPaymentSelection`
   "Betaald per bank" + verwachte afletterdag en lettert af via de bestaande bank-sync + matchmotor-stap "batch" (onze end-to-end-id
   = batchsleutel).
2. **Koppelvlak-schets voor het MI-uitleverkontract (F5, 0023-vorm) — als voorstel in `Platform/OPEN_ITEMS.md` (RLZ → Jarvis):**
   (a) RLZ → Jarvis feitenset `betaalbaar`: geboekte inkoopfacturen mét vervaldatum, bedrag open, crediteur-IBAN + IBAN-historie
   (wisselsignaal), G-rekeningdeel, betaalstatus, open vraag/duplicaat-signaal, administratie + betaalrekening; snapshot mét
   telling + `generated_at`, versheidsklasse. (b) Jarvis → RLZ event `betaling_geinitieerd` / `betaling_uitgevoerd` /
   `betaling_geweigerd` (document-id, end-to-end-id, Ponto-id, bedrag, datum, geautoriseerd door) — HMAC + nonce zoals de
   Vastly-webhooks. Geen code, alleen de contractschets; het formele besluit loopt via 0006 met Jarvis als eigenaar.
3. **CLAUDE.md** één verwijsregel onder Bank; `docs/rapporten/2026-09-1x-betalen-eigenaar-jarvis.md` + INDEX ("werkt in productie:
   n.v.t."). Beslispunt Peter noteren: interne vier-ogen (voorbereider ≠ autorisator) en batch-/daglimieten — defaults in het
   Jarvis-voorstel.
