> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-omzet-binder.md

# OPDRACHT 16-09 — Omzetboekingen (Receipts) landen in RLZ onder "Uitgaven" i.p.v. "Inkomsten/Verkopen" (melding Peter 16-09, casus Van Boxtel)

**Melding Peter (16-09):** "we hebben nu omzetrapporten van Van Boxtel geboekt, alleen komen deze in RLZ terug onder Uitgaven
(wél op de omzet-grootboekrekeningen). Dit moet onder Verkopen/boekingen komen te staan."

**Context (pre-feature-ritueel):** de omzetmotor boekt sinds 08-08 entity-loze Receipts = `PUT SalesInvoices` zonder `Entity`
mét de administratie-specifieke `DocumentCategory` "Verkoopfactuur (Omzet)" (DocumentType 10), gekozen op NAAM binnen de
DocumentType-10-categorieën (api-verkenning "Receipts-verkenning" §1 + aanvulling 09-08; `app/omzet/boeken.py`
`VERKOOP_OMZET_CATEGORIE_NAAM`, cache `omzet_instelling.verkoop_categorie_id`). De rosetta-Receipt uit de RLZ-UI droeg
`DocumentBinder` "Inkomsten" (`invoice`). Dat onze documenten bij Van Boxtel onder "Uitgaven" verschijnen betekent dat de
binder/categorie dáár anders uitpakt dan op de testadministratie — categorieën zijn per administratie configureerbaar en
de naam-selectie is kennelijk niet voldoende. BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST", "OMZET-AUTOBOEKEN",
"TEGENBOEK-PAD", "Reconciliatie-herzieningen vervolgrun 07-09" (aangiftepoort).

## Blok A — Diagnose lees-only (eerst, in het rapport in twee zinnen)
1. `rlz-lezen` op Van Boxtel: één door de module geboekt omzetdocument als record (`SalesInvoices/{id}` mét `$expand=
   DocumentCategory,DocumentBinder,DocumentLineList($expand=Account,TaxRate)`) + `GET DocumentCategories` van deze
   administratie (alle DocumentType-10-categorieën mét naam, `DocumentBinder`, `HasSystemId`). Vergelijk met dezelfde
   lezing op de testadministratie (rosetta) en met een door de klant/RLZ-UI gemaakte "Inkomsten"-boeking bij Van Boxtel
   als die er is.
2. Vaststellen wat de plaatsing in de RLZ-UI ("Uitgaven" vs "Inkomsten") bepaalt: `DocumentBinder` op de categorie, een
   apart binder-veld op het document, of het teken van de regels. Documenteer in api-verkenning "Receipts — binder
   Inkomsten/Uitgaven (STAP-0 16-09)".

## Blok B — Fix
- Categorie-selectie deterministisch op BINDER + type, niet op naam: kies de DocumentType-10-categorie mét `DocumentBinder`
  "Inkomsten" (systeem-id als die er is, anders de enige/naam "Verkoopfactuur (Omzet)" binnen die binder); meerduidig =
  blokkerende check "omzetcategorie niet eenduidig — kies in Instellingen › Omzetbronnen" (Beheerder-combobox uit de
  gesynchroniseerde categorieën, herkomst-chip). Als de binder een los PUT-veld is: expliciet meegeven. Rechten-probe/sync
  leest de categorieën mét binder (`app/rlz/leesroutes.py`, één bron). Cache `verkoop_categorie_id` per administratie
  invalideren als de binder niet "Inkomsten" is.
- Guard-test: elke administratie-fixture mét twee DocumentType-10-categorieën (één Uitgaven, één Inkomsten) → motor kiest
  Inkomsten; alleen-Uitgaven → blokkerende check, geen boeking.

## Blok B2 — Zichtbaar + corrigeerbaar in het omzet-controlescherm (Peter 16-09: "medewerker ziet hoe de boeking
gelezen wordt en kan wijzigen")
- Regel in de kop van het omzet-controlescherm (mockup omzet-kassarapport-v2, blok "Bron"/kopvelden): "Boekt in Reeleezee
  als: **Inkomsten** · Verkoopfactuur (Omzet)" mét herkomst-chip (automatisch / administratie-instelling / mens). Klikbaar →
  combobox mét de gesynchroniseerde DocumentType-10-categorieën van déze administratie, gegroepeerd op binder (Inkomsten /
  Uitgaven), Uitgaven-opties mét oranje waarschuwing "verschijnt in RLZ onder Uitgaven". Keuze = mens wint voor dit document
  ÉN wordt de nieuwe default voor deze administratie (`omzet_instelling.verkoop_categorie_id` + bron 'mens', audit
  oud→nieuw, tijdlijn) — de volgende rapporten hoeven niet meer gecorrigeerd. Omzet-autoboeken (opt-in) gebruikt dezelfde
  default; is die niet Inkomsten en niet door een mens gezet → geen autoboeking, oranje in de wachtrij (KP6: zichtbaar,
  geen stille no-op). Zelfde regel op de kaartjes "Verkoop → Reeleezee" in de v2-mockup. Geen tegel, geen nieuwe pagina.

## Blok C — Herstel van de al geboekte Van Boxtel-documenten
- Lees-only lijst (CLI `omzet-binder-rapport`, nameting-allowlist): alle door de module geboekte Receipts per administratie
  waarvan de categorie/binder ≠ Inkomsten, mét boekdatum en of de btw-periode al is ingediend (`app/rlz/aangifte.py`).
- Herstel = het bestaande tegenboek-/herboekpad: storno (actie 19) + opnieuw boeken mét de juiste categorie, alleen als de
  aangiftepoort open is; ingediende periode → 409 "suppletie-pad", alleen Beheerder mét reden (bestaand). Geen
  automatische massale herboeking: knop "Herboeken met juiste categorie (N)" op Inzicht › Reconciliatie als bevinding
  `omzet_categorie_afwijkt` per document, Peter klikt de bulk. Nooit iets verwijderen in RLZ (KP3); een categorie-wijziging
  op een geboekt document via PUT alleen als STAP-0 bewijst dat RLZ dat toestaat en het journaal ongewijzigd laat — anders
  storno + herboeken.

## Af
- Tests (categorie-selectie, blokkade, rapport), gouden set niet geraakt behalve omzet-casussen (ab/ac/ad: fixture-categorie
  mét binder). BESLISSINGEN "OMZET-RECEIPTS — BINDER INKOMSTEN, NIET NAAM (Peter 16-09, Van Boxtel)", CLAUDE.md-verwijsregel
  bij "Omzetboekingen", WAT_IS_NIEUW, rapport `docs/rapporten/2026-09-16-omzet-binder.md` + INDEX (diagnose bovenaan;
  meetrecept: `omzet-binder-rapport` ná deploy → aantal afwijkende documenten bij Van Boxtel; ná herboeken 0). Werkt in
  productie: niet gemeten. Geen migratie tenzij `verkoop_categorie_id` een binder-kolom nodig heeft.
