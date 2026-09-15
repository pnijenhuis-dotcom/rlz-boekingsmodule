# UI-bugs Beheer › Gebruikers › Klant-accordeurs — chip-overloop en "verloopt over 633724 uur" (Peter 15-09)

**In gewone taal:** Op de tab Klant-accordeurs liep de chip met een lange, gearchiveerde administratienaam over de kolom Apparaten
heen, en bij het demo-account stond "herstel-link verloopt over 633724 uur". De chip blijft nu binnen zijn kolom (puntjes, volledige
naam als tooltip) en de vervaltekst is leesbaar: uren, dagen, datum of "verloopt niet".

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook). Meetrecept: screenshot van dezelfde tab ná deploy op 1440 zonder
overlap; "App-review (demo)" toont "herstel-link verloopt niet".

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1 | Administratie-chip (Badge) krijgt `className="admin-badge"` + `title` = volledige naam; CSS `.gebruikers-tabel .admin-badge` = inline-block, max-width 100 %, ellipsis, nowrap — binnen het kolomminimum (196 px) uit `gebruikersKolommen.ts`; > 2 administraties blijft de teller-chip "N administraties" | `frontend/src/gebruikers/AccordeurAdministraties.tsx`, `frontend/src/styles/components.css` |
| 2 | `formatVerloop(iso, nu)`: < 48 u → uren (≤ 1 u "binnen een uur"), ≤ 30 dagen → dagen, > 30 dagen → "verloopt op dd-mm-jjjj", jaar ≥ 2099 → "verloopt niet", verstreken → "verlopen"; één helper voor uitnodiging én herstel-link | `frontend/src/gebruikers/gebruikersApi.ts` |
| 3 | Overflow-sweep-variant: harnas `?breed=1&groep=accordeurs` heeft nu het demo-account mét de lange gearchiveerde naam en de 2099-link; sweep op 1440/1170/1024/768 licht + donker | `frontend/src/dev/visueelHarnasGebruikers.tsx` |

## Tests

`gebruikersApi.test.ts` (3, nieuw), `GebruikersScreen.test.tsx` (+1: ellipsis-chip mét title, "verloopt niet", geen "633724 uur");
src/gebruikers + gebruikersCss 77 groen; `tsc -b` groen (pre-commit).

Overflow-sweep (`HARNASSEN_ALLEEN="groep=accordeurs" scripts/overflow_sweep.sh`, headless Chrome, met screenshots): 8 metingen groen (licht + donker × 1440/1170/1024/768), geen horizontale pagina-overflow; screenshot 1440 licht: de lange gearchiveerde chip blijft binnen de kolom Administraties, "geen actieve apparaten" leesbaar, "herstel-link verloopt niet" bij App-review (demo). Op 1170 scrolt de tabel intern mét sticky acties (bestaand gedrag).

## Geen migratie, geen backend.
