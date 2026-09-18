uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-veldwerker-rol-wijzigen.md

Domeinen: auth-toegang, uren-planning-veldwerkers

# OPDRACHT 18-09 — Gebruikers & toegang › Veldwerkers: rol wijzigen (ZZP'er ↔ uitvoerder ↔ detacheerder) zonder heruitnodiging

**Peter 18-09:** "Hoe kan ik de rol van Irfan veranderen van ZZP'er naar uitvoerder?" — kan nu niet: de rol-select staat alleen op de
tab Kantoor (`GebruikersScreen.tsx` ~r. 803, opties boekhouding/boekhouding_projecten/beheerder); op de tab Veldwerkers is de rol een
vaste badge. Casus: Irfan Ogur (uitvoerder@universal-steigerbouw.nl), nu ZZP'er, actief, moet uitvoerder worden.

## Bouw
- Tab Veldwerkers: dezelfde rol-select als op Kantoor, mét opties ZZP'er / Uitvoerder / Detacheerder; bevestigdialoog toont wat
  verandert (rechten in de app; ZZP-dossier en crediteurkoppeling blijven staan maar zijn als uitvoerder inactief; als detacheerder
  → koppelingen detacheerder↔ZZP'er relevant). Server-side (`service.wijzig_rol`): wissel BINNEN de veldrollen toegestaan; wissel
  kantoor ↔ veld blijft geweigerd (ander auth-model: toestelbinding vs wachtwoord+TOTP/passkey) mét leesbare 409 — bewijs met
  test. Toestel(len), toegangscode en scope blijven; lopende weekstaten/keuringen blijven aan de gebruiker hangen (geen data-verlies);
  audit `rol_gewijzigd` oud→nieuw (bestaat).
- App: ná rolwissel toont de volgende verversing de juiste schermen (rol komt uit `/auth/me`; geen heractivatie). Test.
- Kantoor-veldwerkersoverzicht (`/veldwerkers`) toont de nieuwe rol direct.
- WAT_IS_NIEUW één regel; docs/regels/auth-toegang.md; rapport + INDEX + Gelezen regels; nameting ná deploy: Irfan → uitvoerder via
  de UI, `/auth/me` geeft de nieuwe rol, app toont uitvoerder-weergave ("werkt in productie: ja/nee").
