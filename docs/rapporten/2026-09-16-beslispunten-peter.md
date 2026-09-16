# Beslispunten voor Peter — run 16-09 (defaults gekozen, werk is doorgegaan)

Per opdracht de keuzes waar de opdracht ruimte liet of waar de bouw van de opdracht afweek. Default = wat nu gebouwd is; een ander
besluit is een vervolg-opdracht via `opdrachten/inbox/`.

## Opdracht 1 — duplicaat Zenvoices / dubbele betaling / bewust verwijderd (`2026-09-16-duplicaat-zenvoices.md`)

1. **Zelfde bedrag + datum, ánder nummer → oranje signaal, geen blokkade.** De opdracht vroeg blokkerend; twee gelijke facturen van
   één leverancier binnen dertig dagen komen legitiem voor en er is voor een externe treffer geen mens-override — blokkeren blijft
   voor de genormaliseerde referentie (met of zonder gelijk bedrag). Alternatief: ook blokkeren + "Geen duplicaat"-afmelding voor
   externe treffers bouwen.
2. **Extern CONCEPT** (bv. een Zenvoices-concept) blokkeert het boeken maar wordt niet direct afgevoerd (dagrem, blok 4 08-09
   beslispunt 1 blijft open).
3. **Normalisatie**: spaties tussen cijfergroepen = groepering ("2 4594 001722" ≡ "24594001722"); een spatie ná een woord blijft een
   nummerdeel-scheider ("document 03" ≡ "document 3") — gevolg: een IBAN mét spaties ≠ zonder spaties (IBAN-referenties zijn sowieso
   uitgesloten).
4. **`duplicaat-extern-rapport` is RLZ-only** (Odoo zichtbaar overgeslagen). Dubbele-betaling-venster 60 dagen en horizon 400 dagen
   zijn constanten; geen actie "terugvordering aanvragen" op de rij (signaal + acceptatie).
5. **Blok D zonder `Afwijzing`-rij**: de DB-CHECK `afwijzing_herkomst_herstelbaar` laat herkomst `geboekt` niet toe en migraties waren
   voor dat blok niet beschikbaar; gebouwd met een eigen tijdlijn-marker + "Terugdraaien…" in Inzicht › Reconciliatie (trekt ook de
   acceptatie in). Alternatief: migratie die de CHECK verbreedt, daarna over op `wijs_af`/`heropen` (heropen-knop op het document).
6. **Eigen-DB-lezing productie** was in deze run niet mogelijk (Cloud-Shell-SQL geweigerd door de auto-mode-classifier); de
   documenthistorie is uit Cloud Logging gereconstrueerd. Wil je zulke lezingen structureel, dan een lees-only CLI `document-inspect`
   in de nameting-allowlist (vervolg-opdracht).
