> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-omzet-store-routering.md

# OPDRACHT 16-09 (avond) — Zonnestudio: "Store Used" routeert naar een ÁNDERE administratie (Sunshine Island = eigen BV) + Van Boxtel-kassarapport herkend vóór de AI + dagelijkse bevinding "kassarapport in de inkoopstroom"

**Besluit Peter 16-09 (avond):** Sunshine Island is een **eigen BV**, dus een eigen administratie — niet dezelfde als Elderveld.
Beslispunt 1 van opdracht 4 (`2026-09-16-beslispunten-peter.md`, "default: zelfde administratie") is daarmee **ANDERS beslist**.

**Bevinding Cowork uit opdracht 8 (omzet-binder):** de Van Boxtel-"omzetrapporten" waren door de AI als inkoopfactuur geclassificeerd
en via het inkoopscherm geboekt. De herkenning-op-inhoud vóór de AI (opdracht 6, `omzet/bronnen/herkenning.py`) dekt alleen ProfX.
Zonder uitbreiding landt het volgende Van Boxtel-rapport opnieuw als inkoopfactuur en klikt Peter opnieuw per document.

Pre-feature-ritueel: BESLISSINGEN "OMZETBRON ZONNESTUDIO DAGSTAAT (Peter 15-09)", "OMZETBRONNEN — BESLUITEN PETER 16-09",
"OMZETBRON COFFEESHOP PROFX JOURNAAL …", "OMZET-RECEIPTS — BINDER INKOMSTEN, NIET NAAM (Peter 16-09, Van Boxtel)", "Verzamelbak"
(tenaamstelling leidend, afzender = hint, nooit auto-toewijzen bij twijfel), "E-mail-intake + verzamelbak"; `app/omzet/bronnen/`,
`app/intake/`, `omzet_instelling.bron_instellingen.stores`, CLI `kassarapporten-in-inkoopstroom`, `app/reconciliatie/`.

## Blok A — Store → administratie (platformbreed, niet per administratie)
- De store-routering staat nu per administratie (`bron_instellingen.stores`). Dat kan een dagstaat niet naar een ándere
  administratie sturen. Nieuw: één platformbrede tabel `omzet_store_routering` (store-naam genormaliseerd → administratie_id,
  actief, audit; migratie), Beheerder-blok "Stores" op Instellingen › Boeken (naast Omzetbronnen) mét administratie-combobox per
  store. De per-administratie-lijst blijft bestaan als afgeleide weergave ("stores die hier landen"), niet als tweede bron.
- Intake: een herkende zonnestudio-dagstaat/kascheck mét "Store Used: X" → routering-tabel → administratie, ongeacht in welke
  administratie/mailbox hij binnenkwam (tenaamstelling van de mail blijft hint, store is bij dit brontype leidend omdat het rapport
  zelf de store noemt). Onbekende store → verzamelbak mét reden "store 'X' niet gekoppeld" + link naar het Stores-blok (lege stand =
  actie). Twee administraties voor dezelfde store = onmogelijk (unieke index).
- Bundeling dagstaat + kascheck per dag (opdracht 15-09) werkt over de routering heen: beide delen landen in dezelfde administratie.
- Sunshine Island bestaat mogelijk nog niet als administratie in de module: CC controleert lees-only (administratielijst) en zet in
  het rapport "bestaat / ontbreekt — Peter voegt toe via de wizard". Niets aanmaken.
- Datastap: bestaande `stores`-inhoud (Elderveld) éénmalig overgezet naar de tabel (CLI, dry-run default, idempotent).

## Blok B — Van Boxtel-kassarapport herkend vóór de AI
- STAP-0 lees-only: wat staat er in de PDF-tekstlaag van RLZ-04-00000683..686 (via het opgeslagen document in de module, niet via
  RLZ)? Vaste koptekst/kassasysteem-naam → vingerafdruk in `herkenning.py`, zelfde patroon als ProfX (inhoud, geen AI, geen afzender).
  Geen bruikbare tekstlaag (scan) → rapporteren, niet raden; dan blijft blok C het vangnet.
- Gouden-set-casus (geanonimiseerde kerntekst) + xfail-discipline.

## Blok C — Dagelijkse bevinding i.p.v. alleen een CLI
- `kassarapporten-in-inkoopstroom` wordt óók een reconciliatieblok (`omzet_in_inkoopstroom` bestaat al voor GEBOEKTE documenten —
  uitbreiden naar ONGEBOEKTE documenten in de werkvoorraad: bevinding "Kassarapport staat als inkoopfactuur in de werkvoorraad"
  mét actie "Type wijzigen → kassarapport" (bestaande route uit de bulk-acties)). Alleen op de herkende bronnen (ProfX, Van Boxtel,
  zonnestudio, pilates) en op het bestaande lokale signaal "alle regels op een omzetrekening" — geen dagelijkse PDF-lezing van
  alles. Teller in de automatiseringen-lijst.

## Afronding (vaste eisen)
- Migratie-afsluitroutine, gouden set groen, `tsc -b`, vitest, overflow-sweep instellingen.
- WAT_IS_NIEUW; BESLISSINGEN "OMZET — STORE → ADMINISTRATIE PLATFORMBREED + VAN BOXTEL-HERKENNING (Peter 16-09 avond)"; CLAUDE.md
  één verwijsregel onder Omzetbronnen; beslispunt 1 van opdracht 4 in `2026-09-16-beslispunten-peter.md` markeren als "BESLIST
  Peter 16-09: eigen BV".
- Rapport `docs/rapporten/2026-09-16-omzet-store-routering.md` + INDEX mét "werkt in productie: ja/nee/niet gemeten"; meetrecept:
  ná deploy een Sunshine Island-dagstaat via de mailbox → landt in de Sunshine Island-administratie (of in de verzamelbak mét de
  store-reden zolang de administratie ontbreekt), en `kassarapporten-in-inkoopstroom --dagen 120` toont de Van Boxtel-documenten
  als `herkend (van_boxtel)`.
