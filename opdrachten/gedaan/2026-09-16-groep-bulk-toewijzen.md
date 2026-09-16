> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-groep-bulk.md

# OPDRACHT 16-09 — Groep in één keer aan meerdere administraties toewijzen (Peter 16-09: "nu moet ik 1 voor 1 doen")

**Aanleiding:** Peter wil "Kempen groep" aanmaken en aan ~10 administraties koppelen; het groepskenmerk (BESLISSINGEN
"GROEPSKENMERK OP ADMINISTRATIE", migratie 0135) kent alleen het veld per administratie. Vóór `groepssaldi` (opdracht
`2026-09-16-groepssaldi-debiteuren-crediteuren.md`) — dit eerst.

## Te doen (geen migratie)
1. Blok "Groepen" op Instellingen › Administraties: per groep een knop "Administraties toevoegen…" → dezelfde doorzoekbare
   vinkjeslijst als de scope-dialoog (`gebruikers/ScopeLijst.tsx`, BESLISSINGEN "SCOPE-DIALOOG: LIJST IN PLAATS VAN CHIPS"):
   alle actieve administraties, al-toegewezen aangevinkt, administraties die in een ANDERE groep zitten getoond mét die
   groepsnaam (aanvinken = overzetten, met bevestiging "N administraties verhuizen van groep X"), Opslaan toont "+N −M".
   Gearchiveerde onderaan.
2. Administratielijst: checkbox per rij + "alle N" (bestaand patroon bulk-afvoer) → actie "Toewijzen aan groep…" (combobox
   groepen + inline "Nieuwe groep…", zelfde component als op het detailscherm).
3. Backend: `PUT /groepen/{id}/administraties` (body: toevoegen[], verwijderen[]) — Beheerder-only, per administratie
   dezelfde audit `administratie_groep_gewijzigd` oud→nieuw als de enkelvoudige route, één transactie, 409 bij een
   gearchiveerde groep. Rolpoort-test + `test_rol_endpoint_gates` sweep.
4. Tests: frontend dialoog (+N −M, verhuizen-bevestiging), backend bulk (audit per rij, transactie, 409), registry/overflow-
   sweep ongewijzigd groen.
5. BESLISSINGEN aanvulling onder "GROEPSKENMERK OP ADMINISTRATIE" ("bulk-toewijzing 16-09"), WAT_IS_NIEUW, rapport
   `docs/rapporten/2026-09-16-groep-bulk.md` + INDEX. Werkt in productie: niet gemeten (meetrecept: Peter wijst Kempen groep
   in één dialoog toe).
