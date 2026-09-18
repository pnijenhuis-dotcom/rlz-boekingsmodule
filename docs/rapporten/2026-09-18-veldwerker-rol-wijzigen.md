# Rapport 18-09 — Gebruikers & toegang › Veldwerkers: rol wijzigen (ZZP'er ↔ uitvoerder ↔ detacheerder) zonder heruitnodiging

Opdracht: `opdrachten/gedaan/2026-09-18-veldwerker-rol-wijzigen.md`. Domeinen: auth-toegang, uren-planning-veldwerkers. Geen
migratie. Gebouwd + getest 18-09-2026 in de inbox-run.

**Werkt in productie: NIET GEMETEN** — klikpunt voor Peter ná de deploy: Gebruikers & toegang › Veldwerkers → rol van Irfan Ogur
(uitvoerder@universal-steigerbouw.nl) van ZZP'er naar Uitvoerder → Bevestigen (204); de app van Irfan toont bij de volgende
verversing "🏗 Projecten · ⏱ Mijn uren · ✓ Te keuren" (uitvoerder-weergave), `/veldwerkers` toont "Uitvoerder". Meetrecept toegevoegd
aan de inbox-opdracht `2026-09-18-veldapp-uitvoerder-nameting.md` (punt 8; alleen ná Peter's klik meetbaar).

## Feiten vooraf (code gelezen)

| Vraag | Bevinding |
|---|---|
| Waarom kon het niet? | De rol-select stond alleen op de tab Kantoor (`GebruikersScreen.tsx`, opties boekhouding/boekhouding_projecten/beheerder); op Veldwerkers was de rol een `Badge`. De server (`PATCH /auth/gebruikers/{id}/rol`) accepteerde élke rol zonder groepstoets. |
| Audit `rol_gewijzigd`? | Bestaat als DB-trigger `trg_audit_gebruiker_rol_wijziging` (migratie 0002) mét actie **`rol_wijziging`** (niet `rol_gewijzigd`), oud→nieuw JSON — hergebruikt, geen tweede schrijver. |
| Rol uit `/auth/me`? | Er is géén `/auth/me`: de app leest de rol als JWT-claim (`AuthContext.rolUitToken`); de server leest per request de DB-rol (`deps.get_current_gebruiker`). De refresh-rotatie zet `gebruiker.rol` uit de DB in het nieuwe access-token → de app volgt bij de eerstvolgende verversing, zonder heractivatie. |

## Gebouwd

- **Server:** `app/auth/rollen.py::rolgroep` (kantoor / veld / accordeur); `service.wijzig_rol` weigert een wissel tussen groepen
  met `RolWisselNietToegestaan` (leesbare reden incl. beide rollen + groepen en de route "nodig uit voor de nieuwe rol en
  archiveer het oude account"); router vertaalt naar **409** (AuthError blijft 403). Binnen de groep wijzigt alleen `gebruiker.rol`:
  scope-rijen, toestellen (`webauthn_credential soort='toestel'`), toegangscode (lokaal anker), weekstaten en keuringen blijven.
- **UI:** tab Veldwerkers → `Select` met ZZP'er / Uitvoerder / Detacheerder (gearchiveerd = badge), `aria-label "Rol van <naam>"`;
  bevestigdialoog `rolWijzigingBericht`: basiszin + "geen heruitnodiging nodig …", "lopende weekstaten en keuringen blijven …",
  en per doelrol een extra zin (ZZP-dossier/crediteurkoppeling inactief; detacheerder-koppelingen; uitvoerder ziet alles en
  keurt). Een 409 blijft leesbaar in de dialoog (bestaande `actieFout`).
- **`/veldwerkers`:** ongewijzigd — leest de rol uit de DTO en toont de nieuwe rol bij laden.

## Tests

| Suite | Uitkomst |
|---|---|
| `tests/auth/test_rol_wijzigen_veld_18_09.py` (eigen test-DB) | 11 groen: rolgroep-indeling; ZZP'er → uitvoerder mét scope-behoud + audit `rol_wijziging` oud→nieuw; uitvoerder → ZZP'er → detacheerder; volgende tokenverversing draagt de nieuwe rol; API 204; 5 × groepswissel geweigerd (service) + API 409 mét reden |
| `tests/auth/test_self_mutation.py`, `test_archiveren.py`, `test_veldwerkerbeheer.py` | 35 groen (bestaand gedrag ongewijzigd) |
| Frontend `vitest run src/gebruikers` | 8 bestanden / 75 tests groen (+2 nieuw: select + dialoogtekst + PATCH; 409 leesbaar) |
| `tsc -b` | groen |

## Beslispunten (gekozen)

1. **Kantoor ↔ veld/accordeur blijft geweigerd**, óók beheerder → veld (ander inlogmodel; opdracht). De 409-tekst geeft de route.
2. **Gearchiveerde veldwerker = badge**, geen select (server weigert toch: "dearchiveer eerst").
3. **Geen extra melding aan de veldwerker** bij een rolwissel — de app wisselt stil van weergave bij de volgende verversing;
   wil Peter een push "je rol is gewijzigd", dan is dat één regel op het bestaande push-kanaal.

## Gelezen regels

- `docs/regels/auth-toegang.md` (160 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/uren-planning-veldwerkers.md` (300 regels) — volledig, vóór de start (Domeinen-kopregel).
