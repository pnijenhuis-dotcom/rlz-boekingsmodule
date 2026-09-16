# Rapport 16-09 — Projectveld in het verplichting-scherm: lege stand zichtbaar, laden ≠ fout ≠ leeg, projectcode, "+ Nieuw project…"

**Feedback Peter 16-09:** "projectveld gaat niet goed, kan niks selecteren en zie niet welke projecten reeds bestaan"
(screenshot Offerte S00642 Energy Matrix, Bouwadvies Oost Nederland).

**Wortel in twee zinnen:** de combobox zette de tekst "Geen resultaten" bínnen de gevirtualiseerde container met hoogte
`aantal opties × 32 px` — bij nul opties 0 px — en de scrollende listbox knipte 'm weg tot een sliver; dat gold voor élke
combobox in de app. Daarbovenop gebruikte het verplichting-scherm alleen `opties` uit de project-hook, zodat "laden", een
401/403/500 en "deze administratie heeft geen projecten" er identiek uitzagen — en bij Bouwadvies Oost Nederland is de lijst
écht leeg: RLZ heeft daar 0 projecten (lees-only gemeten).

**Opdracht:** `opdrachten/gedaan/2026-09-16-verplichting-projectveld-combobox.md`. Geen migratie.
**Werkt in productie: niet gemeten** (bouw wacht op deploy; de diagnose van blok D wél lees-only gemeten op productie-RLZ).

## Gedaan
1. **Blok A — combobox app-breed** (`frontend/src/document/SearchableCombobox.tsx`): de lege/laad-/fout-stand rendert als eigen
   blok `combobox-leeg` (role status, `minHeight` = rijhoogte) BUITEN de hoogte-container. Nieuwe optionele props `laden`,
   `laadFout`, `onOpnieuw`, `leegTekst`. Teksten: "Laden…" · "Kon de lijst niet laden — ‹reden›" + tekstknop "Opnieuw" ·
   zonder filter "Geen ‹meervoud van label› in deze administratie" (expliciete tabel, onbekend label = "opties") · mét filter
   "Geen resultaten voor '‹term›'". Optie-rij kent `inactief` → chip "inactief". Vitest +4 (DOM-structuur: geen voorouder met
   height 0; drie tekstvarianten; code + chip; zoeken op code); bestaande test op "Geen resultaten" aangepast.
2. **Blok B — aanroepers**: grep-sweep over álle 23 comboboxen op `useProjectOpties`/`useVendorOpties`/`useGrootboekOpties`/
   `useTaxrateOpties` (verplichting ×2, bank ×5, doorbelasting ×3, omzet ×4, verkoop ×2, waarborg, materiaal, projectverdeling,
   boekvoorstel ×4): `laden` + `laadFout` gaan overal mee; `onOpnieuw` waar al een herlaadsleutel bestond (verplichting,
   boekvoorstel, projectverdeling). Verplichting-scherm: hint "Geen projecten in deze administratie — Project aanmaken →"
   (`/projecten?administratie=‹id›`, de projectenmodule maakt via route A in RLZ aan), aparte fout-hint mét "Opnieuw", de rode
   check "Verplichte velden … project" draagt dezelfde link, voetoptie "+ Nieuw project…" (alleen kantoorrol mét projectrecht
   én bewerkbare status) opent de bestaande `NieuwProjectModal`; ná aanmaken herlaadt de lijst en staat het project
   geselecteerd. Zonder rol = geen voetoptie (fail-closed). Vitest +4.
3. **Blok C — projectcode**: STAP-0 lees-only (api-verkenning "Projects — codeveld (STAP-0 16-09)"): RLZ heeft géén
   `Code`/`Number`/`Reference` op Projects — de code is de cijfer-prefix van `Name` volgens de naamconventie.
   `ProjectOptieResponse` krijgt `code` + `is_actief` (afgeleid in `app/sync/service.py::splits_projectcode`, geen migratie),
   `naam` = rest; sortering actief eerst, dan naam; combobox toont de code links (zoals grootboek) en zoekt erop; inactief
   onderaan mét chip, nooit verborgen. Tests `tests/sync/test_router.py` +2, gouden set `tests/keten/test_u_project_opties_code.py`.
4. **Blok D — Bouwadvies Oost Nederland (lees-only, productie-RLZ via `nameting.sh rlz-lezen`)**:
   - RLZ heeft **0 projecten** (`Projects --count` → `@odata.count: 0`, status 200) — uitkomst **(a)**.
   - De sync-run-status per onderdeel en de `project_cache`-telling zijn **niet gemeten**: er is geen lees-only instrument voor
     de eigen DB in de nameting-allowlist (regel Peter 08-09). De route gaf 200 op de Projects-leesroute, dus (b) "rechten
     onderweg" is uitgesloten; met 0 bronrijen is (c) "alleen inactief" ook uitgesloten.
   - Gevolg: geen sync-/rechtenbevinding, dus terecht niets in de reconciliatie-LET-OP. Wel een beslispunt (hieronder).
5. **Docs**: api-verkenning-sectie, BESLISSINGEN "VERPLICHTING — PROJECTVELD: LEGE STAND ZICHTBAAR + PROJECTCODE (Peter 16-09)",
   CLAUDE.md-verwijsregel onder Verplichtingen, WAT_IS_NIEUW-blok, beslispunt in `2026-09-16-beslispunten-peter.md`.

## Testbeeld
- `tsc -b` groen; vitest volledige suite 1671 groen (vóór de laatste testfix: 2 rood → gefixt, 33/33 in de twee geraakte bestanden).
- Backend: `tests/keten` + `tests/sync` + `tests/verplichting` 294 groen, 1 skipped; guards `test_keten_guard`,
  `test_claude_md_beslissingen_verwijzingen`, changelog-vormtest groen. Ruff schoon op de eigen hunks (`service.py` draagt
  oudere format-drift buiten deze wijziging; bewust niet meegeformatteerd).
- Overflow-sweep en keten-sweep: zie de regel "Sweeps" onderaan (ingevuld ná afloop).

## Meetrecept ná deploy (werkt in productie: ja/nee)
1. Deploy-check service én jobs op hetzelfde beeld.
2. Open de verplichting S00642 bij Bouwadvies Oost Nederland → klik in het veld Project: de lijst toont de lege stand
   "Geen projecten in deze administratie" op volle rijhoogte, onder het veld staat "Project aanmaken →" naar
   `/projecten?administratie=…` — geen sliver meer. Voor een Beheerder/boekhouder staat onderin de lijst "+ Nieuw project…".
3. Open een inkoopfactuur bij Universal Steigerbouw → projectkolom: opties tonen "26049 · Hoofddorp (Grunsven)"-vorm, typen
   "2604" filtert op de code; inactieve projecten onderaan mét chip.
4. `GET /administraties/{Universal}/projecten` (via de service, ingelogd) → elke rij draagt `code`, `naam`, `is_actief`.

## Beslispunt (blok D uitkomst a)
Zie `docs/rapporten/2026-09-16-beslispunten-peter.md` — opdracht 12.

## Sweeps
overflow-sweep: volledige run in deze sessie (20:37–21:50) afgebroken op 77 van 168 metingen omdat het gebruikers-harnas ~5 min per meting kostte — 75 ✅ (harness, harness?project, werkvoorraad ×4 varianten, gebruikers, gebruikers?breed=1 en ?breed=1&groep=veldwerkers volledig, groep=accordeurs deels) en 2 ❓ op de bekende Chrome-timeout (harness-gebruikers ?breed=1 donker 1440 en ?breed=1&groep=accordeurs donker 1440 — blok 4b 11-09, geen overflow-melding); daarna gericht `HARNASSEN_ALLEEN=harness-veldwerkers` 16/16 ✅; het instellingen-harnas (56 metingen) is door de parallelle cc-inbox-run op dezelfde werkboomstand groen gedraaid (commit c1df300). Keten-sweep: 11/11 ✅ (0 nieuwe baselines) in deze sessie ná de verversing van zes baselines door die run. (ingevuld 16-09 22:00 in de vervolgsessie; slotrapport `2026-09-16-inbox-afgewerkt-3.md`.)
