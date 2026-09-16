# Rapport 16-09 — Groep in één keer aan meerdere administraties toewijzen

**Opdracht:** `opdrachten/gedaan/2026-09-16-groep-bulk-toewijzen.md` (Peter 16-09: "nu moet ik 1 voor 1 doen"). Geen migratie.
**Werkt in productie: niet gemeten** — meetrecept: Peter wijst "Kempen groep" in één dialoog toe (hieronder).

## Gedaan
1. **Blok "Groepen" › "Administraties toevoegen…"** per actieve groep → `GroepLedenDialoog` op de bestaande `ScopeLijst`
   (scope-dialoog-lijst), uitgebreid met een optionele stille chip per rij (`notitie`): al-toegewezen aangevinkt, leden van
   een andere groep mét "groep: X" (aanvinken = verhuizen, bevestiging "N administraties verhuizen van groep X"),
   gearchiveerde onderaan, Opslaan "+N −M".
2. **Administratielijst › bulkbalk › "Toewijzen aan groep…"** — `GroepVeld` (combobox + inline "+ Nieuwe groep…"), groep = één
   bulk-PUT, "— geen groep —" = per administratie de bestaande route; uitkomst per rij in de bestaande foutlijst.
3. **Backend `PUT /groepen/{groep_id}/administraties`** (`groepen.zet_groep_bulk`): Beheerder-only, één transactie, audit
   `administratie_groep_gewijzigd` oud→nieuw per administratie (één correlatie-id), 409 gearchiveerd (verwijderen mag wél),
   404 onbekende groep/administratie mét rollback, al lid = overgeslagen (idempotent), andere groep = verhuisd mét oude naam,
   verwijderen alleen uit deze groep.
4. **Tests:** backend `TestBulk` (4) + hele `test_groepen.py` 20 groen, rol-endpoint-sweep 446 groen (matrix uitgebreid);
   frontend `GroepLedenDialoog.test.tsx` (3), `BulkBediening.test.tsx` (+2), ScopeLijst/ScopeModal/registry/InstellingenScreen
   ongewijzigd groen (88), `tsc -b` groen; overflow-sweep: zie onder.
5. Docs: BESLISSINGEN subkop "Bulk-toewijzing 16-09" onder "GROEPSKENMERK OP ADMINISTRATIE" (beslispunt "bulk niet gebouwd"
   afgehandeld), CLAUDE.md-verwijsregel, WAT_IS_NIEUW.

## Overflow-sweep
Volledige sweep (168 metingen): 87 groen, daarna vanaf `harness-gebruikers.html?breed=1 donker 768px` 81 × "badge niet gevonden"
(render mislukt — de Chrome-metingen liepen ná het zware gebruikers-harnas op de timeout; geen overflow-melding, `overflow_sweep_vite.log`
toont alleen de verwachte proxy-fouten zonder backend). Herhaald voor het geraakte harnas `HARNASSEN_ALLEEN=harness-instellingen.html`
(GroepenBeheer + GroepLedenDialoog + administratielijst, alle paden/breedtes/thema's): **56/56 groen**, twee keer (ook ná de
profiel-filter-wijziging van opdracht 9).

## Meetrecept ná deploy
Instellingen › Administraties › "groepen (N)" › Kempen groep › "Administraties toevoegen…" → leden aanvinken → "Opslaan (+10)" →
bevestigen. Verwacht: ledental 10 in de groepenlijst, klantenlijst-filter "Groep: Kempen groep" toont die 10, `audit_event`
bevat 10 × `administratie_groep_gewijzigd` met dezelfde correlatie-id. Daarna `groep-saldi --groep "Kempen groep"` (opdracht 3).

## Beslispunten (default gekozen)
- Verwijderen uit een groep via de dialoog raakt alleen leden van díe groep; een administratie in een andere groep wordt
  nooit stil losgemaakt (overgeslagen mét reden).
- "— geen groep —" in de bulkbalk loopt per administratie over de enkelvoudige route (N calls) — de bulk-route is
  groep-gebonden; bij 71 administraties is dat aanvaardbaar.
- Geen groep-veld in de Odoo-wizard (beslispunt 11-09 blijft open).
