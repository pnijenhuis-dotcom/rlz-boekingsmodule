uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-gebruikers-ui-bugs.md

UI-BUGS — Beheer › Gebruikers › tab Klant-accordeurs (screenshot Peter 15-09, 1440-breed)

1. Kolom ADMINISTRATIES loopt over in kolom APPARATEN: bij "App-review (demo)" en "Passkey-test accordeur" staat de chip "Test-administratie (passkey-test, verdwijnt bij tranche-…) · gearchiveerd" over de apparaten-cel heen ("Kill-switch"/"geen actieve apparaten" onleesbaar). Fix: lange administratienamen in de chip afkappen met ellipsis + title-tooltip, chip max-width = kolombreedte (kolomminima uit `gebruikersKolommen.ts`, geen tabel-overflow); bij >1 administratie blijft de teller-chip "N administraties". Overflow-sweep-variant met een lange naam toevoegen (harnas `?breed=1` bestaat).
2. "herstel-link verloopt over 633724 uur" (App-review demo, verloopt 2099-01-01): onzinnige tekst. Regel: > 30 dagen → "verloopt niet" (demo-herbruikbaar) of datum "verloopt op dd-mm-jjjj"; ≤ 30 dagen → dagen; < 48 u → uren. Zelfde helper voor "verloopt over 72 uur" (Olaf Tupker).
3. Controleer de hele tab op 1440 én 1170 met de bestaande sweep (sticky acties, geen horizontale pagina-overflow).
Rapport docs/rapporten/2026-09-15-gebruikers-ui-bugs.md + INDEX; geen migratie; dit bestand naar gedaan/. Meetrecept: screenshot van dezelfde tab ná deploy zonder overlap.
