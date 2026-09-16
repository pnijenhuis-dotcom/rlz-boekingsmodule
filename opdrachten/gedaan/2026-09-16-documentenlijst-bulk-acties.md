> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-documentenlijst-bulk.md

# OPDRACHT 16-09 — Documentenlijst: meerdere documenten selecteren en in bulk verwijderen / herclassificeren / verplaatsen (Peter 16-09: "nu moet dat 1 voor 1")

**Aanleiding:** verkeerd geclassificeerde kassarapporten (ProfX Journaal, opdracht `2026-09-16-omzet-coffeeshop-profx-
journaal.md`) staan als "inkoopfacturen" in de werkvoorraad; Peter wil ze in bulk kunnen wegwerken. Er is al een bulk-
patroon: BESLISSINGEN "BULK-AFVOER OP DE MOGELIJK-DUPLICAAT-TAB" (checkbox + "alle N" server-side + uitkomst per rij) en de
verwijderd-status mét Herstellen (BESLISSINGEN "AFGEHANDELDE DOCUMENTEN — ÉÉN TOGGLE"). Dit generaliseert dat naar de hele
documentenlijst.

## Te doen (geen migratie; bulk = N × de bestaande per-document-route in één transactie per document, uitkomst per rij)
1. Checkbox per rij + "alle N in deze weergave" (server-side selectie mét de actieve filters, zoals de duplicaat-tab) op de
   klant-documentenlijst én de verzamelbak; selectiebalk bovenaan mét teller en acties (één primaire knop + ⋯):
   - **Verwijderen…** (verplichte reden, één reden voor de hele selectie; module-status `verwijderd`, herstelbaar via de
     bestaande Herstellen-actie; audit + tijdlijn per document). NOOIT op geboekte/ter-accordering-documenten: die rijen
     krijgen uitkomst "overgeslagen — geboekt" (409-pad), de rest gaat door. Er wordt niets in RLZ/Odoo geraakt (KP3).
   - **Type wijzigen…** (inkoopfactuur ↔ kassarapport ↔ offerte/verplichting): zelfde regels als de bestaande type-wissel
     (extractie opnieuw via het juiste pad, tijdlijn); alleen op niet-geboekte documenten.
   - **Verplaatsen naar administratie…** (bestaande `verplaatsen.py`-route per document, combobox).
   - **Afwijzen…** (verplichte reden) — bestaand per document, nu ook bulk.
2. Uitkomst-dialoog per rij (gelukt / overgeslagen mét reden), zoals bij bulk-afvoer; lijst ververst; selectie leeg ná
   afronding. Sneltoets: Shift-klik selecteert een bereik.
3. Rolpoorten: dezelfde als de enkelvoudige routes (`vereis_kantoorrol`, scope per document server-side + RLS); een
   selectie over administraties heen wordt per document getoetst — buiten scope = "overgeslagen — geen toegang".
4. Tests: bulk-route (mix geboekt/niet-geboekt → deel overgeslagen, audit per rij, één reden), scope-test mét niet-Beheerder
   (RLS-les 25-08), frontend selectie/"alle N"/uitkomst-dialoog, overflow-sweep mét selectiebalk (rijhoogte constant,
   kolomminima ongewijzigd), rol-endpoint-sweep.
5. BESLISSINGEN "DOCUMENTENLIJST — BULK-ACTIES (Peter 16-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW, rapport
   `docs/rapporten/2026-09-16-documentenlijst-bulk.md` + INDEX (meetrecept: Peter selecteert de ProfX-exemplaren bij De
   Bazar en kiest "Type wijzigen → kassarapport" — één handeling). Werkt in productie: niet gemeten.
