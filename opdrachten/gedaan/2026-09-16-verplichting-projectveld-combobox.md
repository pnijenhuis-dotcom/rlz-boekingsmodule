> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-verplichting-projectveld.md

# OPDRACHT 16-09 — Projectveld in het verplichting-scherm: lege lijst zonder uitleg + afgeknepen "Geen resultaten" (feedback Peter 16-09, screenshot Offerte S00642 Energy Matrix, Bouwadvies Oost Nederland)

**Feedback Peter (16-09):** "projectveld gaat niet goed, kan niks selecteren en zie niet welke projecten reeds bestaan."
Screenshot: `VerplichtingReviewScreen`, veld Project met placeholder "Kies project…", daaronder een sliver van een paar pixels
waarin nog net "Geen resultaten" te lezen is, half onder het label "Totaalbedrag excl. btw".

**Diagnose Cowork (uit de code, vóór de bouw door CC te bevestigen):**
1. **Zichtbare bug — lege stand wordt afgeknepen.** `SearchableCombobox.tsx` zet de opties in een container met
   `height: gefilterd.length * RIJHOOGTE` (dus 0 bij nul opties) en de listbox heeft `overflow-y: auto`
   (`components.css .combobox-listbox`). De `.combobox-leeg`-div hangt daardoor uit een 0-px-container en wordt door de
   scrollcontainer weggeknipt: de lijst is een sliver van padding + rand. Dat geldt voor élke combobox in de app zodra een
   filter of een lege lijst nul opties oplevert — niet alleen hier.
2. **Inhoudelijke bug — leeg ≠ laden ≠ fout.** `useProjectOpties` levert `{opties, laden, fout}`, maar het
   verplichting-scherm gebruikt alleen `opties` (regel ~567). Tijdens het laden én bij een 401/403/500 op
   `GET /administraties/{id}/projecten` ziet de gebruiker exact hetzelfde als bij "deze administratie heeft geen projecten":
   "Geen resultaten". `grep projecten\.(fout|laden) frontend/src` = nul treffers, dus dit geldt ook voor het inkoop-
   controlescherm en elk ander scherm dat deze hook gebruikt.
3. **Waarschijnlijke oorzaak dat de lijst écht leeg is bij Bouwadvies Oost Nederland:** `lijst_projects` leest alleen
   `project_cache` (niet-verdwenen). Kandidaten: (a) de administratie heeft in RLZ geen projecten; (b) de Projects-sync is
   nooit groen geweest (eerste sync `rechten_onderweg`/403 op de Projects-route — BESLISSINGEN "EERSTE SYNC NÁ GROENE PROBE");
   (c) projecten bestaan alleen als `is_actief = false`. CC stelt dit lees-only vast via de gedeployde routes/CLI (regel
   Peter 08-09: nooit lokaal tegen productie) en zet de uitkomst letterlijk in het rapport.
4. **Ontbrekend:** de optie draagt alleen `naam` (`ProjectOptieResponse(id, naam)`), geen projectcode. Zoeken op "26xxx"
   werkt alleen als de code in de naam zit. `brondata` heeft het RLZ-veld (`Code`/`Number` — STAP-0 in `rlz-lezen`, niet
   aannemen). En er is in dit scherm geen weg naar "project aanmaken", terwijl het inkoop-controlescherm dat patroon al kent
   voor crediteuren ("+ Nieuwe crediteur in RLZ" als vaste voetoptie — BESLISSINGEN "FIXRUN 07-09 — BLOK 6").

Pre-feature-ritueel: BESLISSINGEN "VERPLICHTINGEN + FACTUUR↔OFFERTE-MATCH 04-09", "OFFERTE-MATCH — WACHTENDE VERPLICHTING
ZICHTBAAR …", "PROJECTENMODULE KANTOOR", "Systeemanker route A" (projectaanmaak-naar-RLZ), "FIXRUN 07-09 — BLOK 6",
"UX-PATRONEN ALS NORM" (lege stand = actie); mockup `offerte-matching.html`; `frontend/src/document/SearchableCombobox.tsx`,
`document/useSyncOpties.ts`, `verplichting/VerplichtingReviewScreen.tsx`, `app/sync/router.py::project_lijst`,
`app/sync/service.py::lijst_projects` / `_project_waarden`.

## Blok A — Combobox: lege stand altijd zichtbaar (app-breed)
- De lege/laad-/fout-stand rendert BUITEN de gevirtualiseerde hoogte-container (eigen blok in de listbox mét minimale hoogte),
  zodat de tekst nooit meer wordt weggeknipt. Geldt voor alle comboboxen.
- Drie onderscheiden teksten via nieuwe optionele props `laden` / `fout`: "Laden…" · "Kon de lijst niet laden — <reden>"
  (mét `linkbtn` "Opnieuw") · lege lijst zonder filter: "Geen projecten in deze administratie" (label-afhankelijk: "Geen
  <label-meervoud> …") · lege lijst mét filter: "Geen resultaten voor '<term>'". `combobox-leeg` blijft de klasse.
- Vitest op `SearchableCombobox`: nul opties → lege-stand-element heeft een zichtbare hoogte (`getBoundingClientRect`
  is in jsdom 0 — toets op de DOM-structuur: het element staat níét in de 0-px-container) + de drie tekstvarianten.
- Overflow-sweep/keten-sweep opnieuw draaien; het keten-harnas raakt het controlescherm (guard `test_keten_guard`).

## Blok B — Verplichting-scherm (en de andere aanroepers) geven laden/fout door
- `VerplichtingReviewScreen`, inkoop-controlescherm en elk ander gebruik van `useProjectOpties`/`useVendorOpties`/
  `useGrootboekOpties`/`useTaxrateOpties` geven `laden` en `fout` door aan de combobox (grep-sweep, allemaal in één keer;
  nul blinde `opties`-only aanroepen laten staan — vitest of ts-guard die dit afdwingt is welkom maar geen eis).
- Lege projectlijst in het verplichting-scherm = lege stand mét actie (UX-norm): "Geen projecten in deze administratie —
  Project aanmaken →" (link naar de kantoor-projectenmodule van dezelfde administratie, `/projecten?administratie=<id>`,
  route A maakt 'm in RLZ aan). Projectverplicht-administratie zonder projecten = harde check blijft rood mét dezelfde link.
- Voetoptie "+ Nieuw project…" in de project-combobox (zelfde patroon als "+ Nieuwe crediteur in RLZ"), alleen voor
  kantoorrollen mét projecten-recht; opent de bestaande aanmaakdialoog/pagina van de projectenmodule voorgeselecteerd op de
  administratie, en ná aanmaken staat het nieuwe project geselecteerd (herlaadSleutel ophogen).

## Blok C — Projectcode in de optie
- STAP-0 lees-only (`rlz-lezen Projects --top 5`, geanonimiseerd) op een administratie mét projecten: welk veld draagt de
  code (`Code`, `Number`, `Reference`?). Uitkomst in api-verkenning "Projects — codeveld (STAP-0 16-09)".
- `ProjectOptieResponse` krijgt `code` (uit `brondata`, geen migratie nodig; wél als de code een eigen kolom verdient voor
  sortering: migratie + `_project_waarden`), combobox toont `code` links zoals bij grootboekrekeningen en zoekt erop.
  Sortering: code, dan naam. Inactieve projecten (`is_actief = false`) onderaan mét chip "inactief", niet standaard
  verborgen (de gebruiker moet zien wat er bestaat — dat was Peters vraag).

## Blok D — Waarom is de lijst leeg bij Bouwadvies Oost Nederland (lees-only nameting)
- Ná deploy, via de gedeployde service/CLI (nameting-allowlist): aantal rijen `project_cache` voor deze administratie,
  laatste sync-run-status per onderdeel (Projects), en `rlz-lezen Projects --top 1` op deze administratie. Drie uitkomsten
  → drie zinnen in het rapport: "RLZ heeft N projecten / sync stond op … / route gaf …". Is het (b) (sync nooit groen), dan
  is dat een bevinding voor de reconciliatie-LET-OP `rechten_na_24u`/eerste-sync en hoort het daar al zichtbaar te zijn —
  zo niet: waarom niet (rapport, geen tweede fix in deze run zonder overleg).

## Afronding (vaste eisen)
- Gouden set groen (controlescherm raakt `frontend/src/document` → tests/keten aanraken, keten_sweep + baseline waar de
  lege-stand-DOM wijzigt), `tsc -b`, vitest, overflow-sweep.
- WAT_IS_NIEUW: "Een keuzelijst zonder resultaten laat nu duidelijk zien waarom (laden, fout, of echt leeg) en biedt
  direct 'Project aanmaken'." BESLISSINGEN-sectie "VERPLICHTING — PROJECTVELD: LEGE STAND ZICHTBAAR + PROJECTCODE (Peter
  16-09)", CLAUDE.md één verwijsregel onder Verplichtingen.
- Rapport `docs/rapporten/2026-09-16-verplichting-projectveld.md` + INDEX, mét de blok-D-zinnen en "werkt in productie:
  ja/nee/niet gemeten" (meetrecept: open de verplichting S00642 bij Bouwadvies Oost Nederland ná deploy; de lijst toont
  óf projecten mét code, óf de lege stand mét "Project aanmaken →" — nooit meer een sliver).
- Beslispunt voor Peter in `docs/rapporten/2026-09-16-beslispunten-peter.md` alleen als blok D uitkomst (a) geeft: wil
  Bouwadvies Oost Nederland überhaupt op projecten boeken (projecten-toggle per administratie), of hoort het projectveld
  daar verborgen te zijn? Default: veld zichtbaar, niet verplicht.
