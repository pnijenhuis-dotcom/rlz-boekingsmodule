# Rapport 16-09 (avond) — Capture besluiten Peter op de beslispunten van vandaag (docs-only)

**Opdracht:** `opdrachten/gedaan/2026-09-16-besluiten-peter-avond-capture.md` (capture-at-acceptance, WERKWIJZE). Geen code,
geen migratie, één docs-commit. **Werkt in productie: n.v.t.**

## Vastgelegd

| # | Besluit Peter (16-09 avond, chat met Cowork) | Waar gemarkeerd |
|---|---|---|
| 1 | **Activa / MVA — steigermateriaal 5 jaar, lineair, restwaarde 0; fiscale ondergrens = default.** Eén parameter, het ontwerp blijft TER AKKOORD (geen bouw-GO). | `docs/rapporten/2026-09-16-beslispunten-peter.md` opdracht 3 punt 3 ("BESLIST Peter 16-09"); `docs/ONTWERP_ACTIVA_MVA.md` §3 nieuwe termijnentabel mét rij "Steigermateriaal — 5 jr (besluit Peter 16-09)" + §8 punt 3; BESLISSINGEN registerrij "ACTIVA / MVA — STAP-0 + ONTWERP (Peter 16-09)" |
| 2 | **Vragen-dialoog — "Afgehandeld namens" door iedere kantoorrol binnen de scope (niet Beheerder-only), mét audit `vraag_afgehandeld_namens`.** | beslispunten opdracht 10 punt 2 ("BESLIST … bevestigd"); BESLISSINGEN "VRAGEN-DIALOOG OPEN TOT AFGEHANDELD (Peter 16-09)" rij "Afgehandeld namens" → "Bevestigd Peter 16-09 avond" |
| 3 | **Zonnestudio — Sunshine Island = eigen BV / eigen administratie.** De bouw zit in de aparte opdracht `2026-09-16-omzet-store-naar-administratie-en-vanboxtel-herkenning.md` (liep op het moment van deze capture nog via de cc-inbox). | beslispunten opdracht 4 punt 1 ("BESLIST Peter 16-09: eigen BV"); BESLISSINGEN "OMZETBRONNEN — BESLUITEN PETER 16-09" beslispunt 1 |

## Niet gedaan (bewust)
- Geen code, geen mockup-wijziging: de activa-parameter verandert niets aan de bouwscope (ontwerp TER AKKOORD), de vragen-dialoog is al
  zo gebouwd (blok van 16-09 middag), de store-routering is een eigen opdracht.

## Testbeeld
- Docs-guards: `tests/unit/test_claude_md_beslissingen_verwijzingen.py` en `tests/unit/test_rapporten_index.py` — zie het slotrapport
  `2026-09-16-inbox-afgewerkt-3.md` voor de gezamenlijke uitkomst van deze inbox-rij.
