uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-ontwerp-vastly-odoo-toets.md

Domeinen: vgg-odoo-migratie, bank, omzet, administraties-instellingen, werkloop-productie

# OPDRACHT 19-09 — Ontwerp "Vastly-klant op Odoo" toetsen aan de bronnen + lees-only pilotmeting ARVUM/Rubicon (GEEN bouw)

`docs/ONTWERP_VASTLY_ODOO.md` (Cowork 19-09, TER AKKOORD Peter) beschrijft verkoop/waarborg/bank-afletteren/webhooks voor een
Vastly-administratie op Odoo, met een verhuurder (ARVUM B.V. of Rubicon Investments) als pilot — nadrukkelijk NIET VGG.

1. **Bron-vs-realiteit-toets** van het ontwerp: elke bewering in §1 (wat klaar/half/te bouwen is) tegen de code (`app/backends/*`,
   `app/odoo/*`, `app/verkoop/boeken.py`, `app/waarborg/boeken.py`, `app/bank/*`) en tegen odoo-verkenning §2.4/§3/§11/§12 en het
   koppelcontract v1.20 (§2c/§2d/§3/§8). Fouten in het ontwerp corrigeren ín het document (mét "gecorrigeerd door CC 19-09: …"),
   niets bouwen. Hetzelfde voor de aanname over `amount_residual`/`payment_state` als afgeletterd-signaal (fields_get, lees-only).
2. **Pilotmeting (lees-only, leesreplica + RLZ GET):** voor ARVUM B.V. en Rubicon Investments B.V. per administratie: aantal
   VASTLY-VERKOOP-facturen en creditnota's per maand (laatste 6 mnd), waarborgberichten, bankmutaties per maand en per rekening, open
   posten (aantal/bedrag), accordering-inrichting, staat de administratie in Vastly's entiteitenregister (`../Platform/registers/
   entiteiten.md`) en registersync §8-koppeling, aantal huurders/objecten. Tabel in het rapport + advies welke de kleinste volledige
   pilot is. Geen Odoo-writes; geen Odoo-koppeling aanmaken.
3. **Contract-check:** wat in de webhooks en §2c aan Vastly's kant een RLZ-aanname is (4-cijferige codes, `rlz_document_id`-naam) —
   concept-addendum v1.21 als voorstel in `../Platform/OPEN_ITEMS.md` (niet in het contract zelf zonder akkoord van beide projecten).
4. Rapport `docs/rapporten/2026-09-19-ontwerp-vastly-odoo-toets.md` + INDEX + Gelezen regels; BESLISSINGEN-rij "VASTLY OP ODOO —
   ONTWERP TER AKKOORD (Peter 19-09)" mét verwijzing naar het ontwerp en de vijf beslispunten; CLAUDE.md één verwijsregel onder
   VGG/Odoo. Werkt in productie: n.v.t. Één regel voor Peter: pilot-advies + de vijf beslispunten.
