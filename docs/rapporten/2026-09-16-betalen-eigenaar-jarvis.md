# Rapport 16-09 (nacht) — Betalen via Ponto: eigenaar Jarvis, RLZ levert feiten en ontvangt status (docs-only)

Opdracht: `opdrachten/gedaan/2026-09-16-ponto-betalen-stap0-en-ontwerp.md` (HERZIEN 22:00). **Werkt in productie: n.v.t.** — geen code,
geen migratie, geen sandbox-STAP-0.

## Besluit (Peter 16-09 22:00)

"Ik wil dit niet in de N-module maar in Jarvis hebben, dat onderscheid moet er wel zijn." Ponto-connector, betaalvoorbereiding,
autorisatieflow en betaalscherm zijn Jarvis-werk (J-010-procedure, Cowork schrijft het besluitvoorstel). Kantoor betaalt als
gevolmachtigde/vertegenwoordiger op de klantrekening; SCA blijft bankzijde.

## Vastgelegd

| # | Wat | Waar |
|---|---|---|
| 1 | Registerrij "BETALEN — EIGENAAR JARVIS, RLZ LEVERT FEITEN EN ONTVANGT STATUS": rolverdeling (RLZ = enige schrijver naar RLZ/Odoo; Jarvis initieert bij de bank en meldt terug; RLZ → `QuickPaymentSelection` "Betaald per bank" + afletteren via de batch-stap met de end-to-end-id als batchsleutel), koppelvlak-schets (a)/(b), beslispunten; de capture van 19-08 blijft staan als historie, de plek-keuze daarin is vervallen | `docs/BESLISSINGEN.md` (ná de Ponto-capture-rij van 19-08) |
| 2 | Koppelvlak-schets als voorstel RLZ → Jarvis (F5/0023-vorm): feitenset `betaalbaar` (velden uitgeschreven) + events `betaling_geinitieerd`/`_uitgevoerd`/`_geweigerd` (HMAC + timestamp + nonce, `schema_version`); het bestaande Ponto-item van vastgoed/Cowork gemarkeerd als HERZIEN 22:00 (plek "RLZ-bankmodule" vervallen) | `../Platform/OPEN_ITEMS.md` (Platform-repo, eigen commit) |
| 3 | Eén verwijsregel onder Bank | `CLAUDE.md` |

## Spanning die het 0006-besluit moet oplossen

Besluit 0028 punt 2 zegt "Jarvis schrijft nooit terug naar een bron". Betalingen initiëren bij de bank is schrijven naar een systeem
waaruit Jarvis (via AIS) ook leest. Het formele besluit moet die uitzondering expliciet benoemen mét de grens "Jarvis muteert nooit een
boekhoudbron (RLZ/Odoo)". Zo genoteerd in de registerrij en het OPEN_ITEMS-item; niet zelf beslist.

## Beslispunten Peter (defaults, notitie)

1. Interne vier-ogen: voorbereider ≠ autorisator — default AAN (Jarvis-voorstel).
2. Batch-/daglimieten per administratie — default: voorstel Jarvis, niet in RLZ.
3. Particuliere rekeningen via Ponto (vraag Vastly) blijft open zoals in het OPEN_ITEMS-item.
