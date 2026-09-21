Domeinen: werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-22 09:00

# Nameting "Corrigeren…" (storno + opnieuw klaarzetten) ná de deploy van 21-09 — TEST-referentie op de RLZ-testadministratie

**Context:** rapport `docs/rapporten/2026-09-21-corrigeren-geboekt-document.md`, BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO +
OPNIEUW KLAARZETTEN (Peter 21-09)". De feature is alleen live ná de deploy; élke schrijfactie naar RLZ loopt uitsluitend tegen de
RLZ-TESTADMINISTRATIE mét een `TEST-`-referentie (CLAUDE.md "Testdata (v1.3-afspraak)") — nooit BLOW of een andere klantadministratie.
"Werkt in productie: niet gemeten" is een schuld mét vervaldatum; deze opdracht lost 'm in. Kan gcloud/nameting.sh in deze run niet
inloggen: NIET stil — klikpunt Peter mét de letterlijke stappen.

## Stap 0 — deploy-check (service ÉN jobs op een image ≥ de commit van 21-09; `git rev-list --count main..origin/main` toetsen, `merge --no-ff` als > 0)
```
gcloud run services describe rlz-backend --region europe-west4 --format='value(spec.template.spec.containers[0].image)'
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format='value(template.template.containers[0].image)'
```

## Stap 1 — inkoop op de testadministratie (schrijvend, alleen TEST)
1. Upload in de web-app op de RLZ-testadministratie een klein test-PDF, referentie `TEST-CORRIGEREN-2026-09-22`, één regel € 100 + € 21,
   boek ("Boeken in RLZ") → boekstuknummer A, GUID = `rlz_herboeking_id(document_id, 0)`.
2. ⋯-menu → "Corrigeren…" → reden "TEST nameting corrigeren 22-09" → verwacht: dialoog toont vooraf "beschikbaar" (geen blokkades:
   aangifte testadministratie open, niet betaald, geen doorbelasting); ná bevestigen toast + gele balk "Gecorrigeerd — reden … · vorige
   boeking A gestorneerd (actie 19)", status klaar_om_te_boeken.
3. Lees-only bewijs: `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh rlz-lezen PurchaseInvoices/<GUID cyclus 0>` → `Status` 1;
   audit `document_gecorrigeerd` op het document (querybibliotheek `document-feiten` / audit-recept) mét reden, oud extern id, oud boekstuk.
4. Pas het btw-bedrag aan (bv. € 20) en boek opnieuw → boekstuknummer B ≠ A; `rlz-lezen PurchaseInvoices/<GUID cyclus 1>` → `Status` 2;
   de duplicaatcheck was groen (oud concept uitgezonderd).
5. Terugweg testdata: het geboekte TEST-stuk (cyclus 1) storneren via "Corrigeren…" (tweede keer) zodat de testadministratie geen geboekt
   TEST-stuk overhoudt — nooit verwijderen in RLZ; het achtergebleven concept mag blijven (opruimlijst-gedrag).

## Stap 2 — idempotentie + blokkade-route (lees-only waar mogelijk)
- Direct ná stap 1.2 nog eens `POST …/corrigeren` (curl mét token, of tweede klik) → 409 `al_gecorrigeerd`; request-log toont precies één
  `POST …/corrigeren` mét 200 per correctie.
- Op een geboekt TEST-stuk mét een boekdatum in een ingediende periode van de testadministratie (als die er is): `GET …/corrigeer-toets` →
  `beschikbaar` false, blokkade `aangifte`, `tegenboeken_beschikbaar` true. Geen ingediende aangifte op de testadministratie = "niet
  meetbaar" opschrijven, geen storno forceren.

## Stap 3 — request-log + rapport
`POST …/documenten/*/corrigeren` in Cloud Logging ≥ 1 mét 200 (de testcasus); 0 × 5xx. Rapport
`docs/rapporten/2026-09-22-nameting-corrigeren-testadministratie.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee/niet
gemeten" letterlijk per stap; alinea "Gemeten 22-09" onder de BESLISSINGEN-sectie van 21-09 en in
`docs/regels/werkvoorraad-controlescherm.md`. De BLOW-stukken RLZ-04-00000357/358 zelf zijn klikwerk van Peter (klantadministratie).
