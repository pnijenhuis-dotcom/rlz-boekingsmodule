uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-projecten-status-afsluiten-nummer-uniek.md

Domeinen: verplichtingen-projecten-voorraad, uren-planning-veldwerkers

# OPDRACHT 18-09 — Projecten (steigerbouw): status "afgesloten" + projectnummer uniek (Peter 18-09)

**Peter 18-09:** (1) "Bij steigerbouw moeten projecten een status krijgen; als een project afgesloten is kan het uit de lijst."
(2) "Per abuis 2× hetzelfde projectnummer aangemaakt — moet geblokkeerd worden."

**Feiten (Cowork, code 18-09):** `projecten/kantoor.py::maak_project_aan` toetst alleen de EXACTE naam ("26127 Tilburg (Heijmans)")
op naamgenoten; hetzelfde nummer met andere plaats/opdrachtgever glipt erdoor. RLZ kent geen codeveld — nummer = cijfer-prefix van de
naam (STAP-0 16-09). RLZ `Project.IsActive` bestaat (put_project zet true); inactief wordt in de combobox al onderaan mét chip getoond.

## Blok A — Projectstatus
- Status per project in de module: `lopend` (default) · `afgesloten`; afsluiten = knop op het projectdetail (kantoorrol
  Boekhouding+Projecten/Beheerder) mét datum + reden optioneel, audit, terugweg "Heropenen". Afsluiten zet RLZ `IsActive=false`
  (klant-loze PUT, terugleesverificatie, RLZ wint bij conflict) en Odoo `active=False`/archived op de analytic account waar van
  toepassing — via de bestaande adapter-seam, nooit direct.
- Gevolg: afgesloten projecten verdwijnen uit álle keuzelijsten (weekstaat, planning, verplichting, controlescherm, betaallijst),
  blijven zichtbaar in Inzicht › Projecten onder een toggle "Toon afgesloten (N)" en in historie/zoeken. Een factuur die ná afsluiting
  op een afgesloten project landt = oranje signaal "project afgesloten op <datum>" (nooit blokkerend — nagekomen facturen bestaan).
- Voorstel afsluit-kandidaten (automatisering-first): geen uren, planning, verplichting of factuur in 90 dagen én verkoop = contract-
  som → chip "kandidaat afsluiten" in Inzicht › Projecten; nooit automatisch afsluiten.
- Bestaande gearchiveerde Peter-opruimpunten: welke van de 83 actieve VGG/Universal-projecten voldoen aan het kandidaat-criterium —
  lees-only rapport mét bron, geen actie.

## Blok B — Projectnummer uniek
- Bij aanmaken: nummer (cijfer-prefix) uniek binnen de administratie over ALLE projecten (actief + inactief, cache én RLZ-lookup
  `Projects?$filter=startswith(Name,'26127 ')`); bestaat het → 409 mét het bestaande project ("26127 bestaat al: 26127 Tilburg
  (Heijmans), lopend — openen?"), nooit stil een tweede aanmaken. Volgnummer-voorstel: eerstvolgende vrije nummer in de reeks van het
  jaar, voorgevuld in het formulier.
- Herstel van de bestaande dubbeling (Peter's casus): lees-only rapport van alle dubbele nummers in Universal Steigerbouw
  (nummer, beide RLZ-id's, aantal facturen/uren/planningregels per kant); voorstel "samenvoegen" = klikpunt Peter mét bron (welke
  blijft, wat verhuist), nooit automatisch; RLZ-project nooit verwijderen — verliezer op IsActive=false ná verhuizing.
- Reconciliatie-soort `project_nummer_dubbel` (start in `meten`) voor dubbele nummers die buiten de module om in RLZ ontstaan.

## Afronding
Migratie (status-kolom + index), afsluitroutine; gouden set groen; WAT_IS_NIEUW ("Projecten kun je afsluiten", "Een projectnummer kan
maar één keer bestaan"); docs/regels/verplichtingen-projecten-voorraad.md; rapport + INDEX + Gelezen regels; nameting ná deploy:
aanmaken met bestaand nummer = 409 in productie (testnummer, niets aangemaakt), afsluiten + heropenen van een testproject werkt.
