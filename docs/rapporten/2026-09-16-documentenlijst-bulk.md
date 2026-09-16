# Rapport 16-09 — Documentenlijst: bulk-acties (verwijderen, type wijzigen, verplaatsen, afwijzen)

**Opdracht:** `opdrachten/gedaan/2026-09-16-documentenlijst-bulk-acties.md` (Peter 16-09: "nu moet dat 1 voor 1"). Geen migratie.
**Werkt in productie: niet gemeten** — meetrecept onderaan.

## Gedaan
1. **Backend** `POST /administraties/{id}/documenten/bulk` (`app/documenten/bulk.py`): N × de bestaande per-document-route, één
   transactie per document, uitkomst per rij (gelukt / overgeslagen mét reden / geen_toegang), één reden voor de selectie, max 500
   id's, validatie per actie (422). Poorten = de enkelvoudige (geboekt/ter_accordering = overgeslagen); scope server-side + RLS.
2. **Type wijzigen** — nieuw `app/documenten/soort.py::wijzig_documentsoort` (er bestond geen enkelvoudige route): soort gezet,
   → ONTVANGEN mét tijdlijn + audit, extractie opnieuw via `start_extractie_na_toewijzing`; idempotent bij dezelfde soort.
3. **Frontend** `DocumentenBulkActies.tsx` + generieke selectie in `DocumentenDeelscherm.tsx`: checkbox per niet-eindstatus-rij,
   kop-checkbox "alle N in deze weergave", shift-klik-bereik, balk mét teller, Verwijderen… + ⋯ (Type wijzigen…, Verplaatsen…,
   Afwijzen…), dialoog met reden/soort/doel, uitkomst per rij, selectie leeg ná afloop. Accordering-bulk en duplicaat-bulk
   houden hun eigen balk; de verzamelbak had al bulk (blok B 02-09).
4. **Rol-matrix** uitgebreid (sweep 506 groen).
5. **Tests:** `tests/documenten/test_bulk.py` 6; gouden set `test_u_bulk_acties.py` 2 (+ keten-guard); documenten-buren groen;
   frontend `DocumentenBulkActies.test.tsx` 4, werkvoorraad-suite 118, tsc groen.
6. Docs: BESLISSINGEN "DOCUMENTENLIJST — BULK-ACTIES (Peter 16-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW.

## Overflow-sweep
De volledige overflow-sweep van 16-09 (gestart ná opdracht 2) liep bij afronding van deze opdracht nog; de selectiebalk hergebruikt
de bestaande `bulk-balk`- en `selectie`-kolomstijlen van de accordering-bulk (zelfde rijhoogte). Uitkomst in het slotrapport.

## Meetrecept ná deploy
De Bazar Apeldoorn › documenten › selecteer de ProfX-rijen (of kop-checkbox) › ⋯ › Type wijzigen → Kassarapport (omzetboeking).
Verwacht: uitkomst per rij "gelukt", rijen komen terug als kassarapport en openen het omzet-controlescherm; een geboekte rij =
"overgeslagen — geboekt". Daarna Verwijderen… op een testselectie mét reden → rijen achter "Toon afgehandelde documenten", herstelbaar.

## Beslispunten (default gekozen)
- "Alle N in deze weergave" = de zichtbare (client-side gefilterde) rijen als id-lijst; geen server-side selectie (anders dan de
  duplicaat-tab, waar de tab een vaste serverdefinitie heeft).
- Kiesbare soorten bij Type wijzigen: inkoopfactuur / kassarapport / verplichting.
- ter_accordering-rijen zijn selecteerbaar; de server slaat ze over mét reden (geen dubbele client-poort).
