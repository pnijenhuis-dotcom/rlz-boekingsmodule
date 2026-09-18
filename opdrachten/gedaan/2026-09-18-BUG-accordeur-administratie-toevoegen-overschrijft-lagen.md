uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-bug-accordeur-toegang-is-geen-laag.md

Domeinen: accordering-native-app, auth-toegang, kantoor-frontend

# BUG 18-09 — Gebruikers › Klant-accordeurs › "Administraties toevoegen" vervangt de bestaande lagen van die administratie door alleen
# deze accordeur in laag 1; "Verwijderen" haalt ook de toegang weg → toegang en laag zitten vast aan elkaar (Peter 18-09, live)

**Casus (Peter 18-09, 19:30):** Bouwadvies Oost Nederland heeft 3 lagen (Peter N. → Sophia Gerritsen → Kempen). Peter wil Romy v.
Lambalgen ALLEEN voor twee leveranciers (leveranciersroute 'bovenop'). Romy stond niet in de accordeur-keuzelijst van Bouwadvies (geen
scope). De enige UI-weg om haar scope te geven — Gebruikers › Klant-accordeurs › Romy › "Administraties toevoegen…" — loopt via
`/accordering/bulk-instellen` mét `lagen = [Romy laag 1]` en vervangt daarmee de drie bestaande lagen van Bouwadvies (én herberekent
lopende rondes). "Verwijderen" bij die administratie doet PUT instellingen zonder haar + DELETE scope → toegang weg → niet meer kiesbaar.
Kringetje. Cowork heeft het omzeild met de bestaande kale scope-route `POST /auth/gebruikers/{id}/scope` (204, geen laag, audit via
DB-trigger) — dat hoort een knop te zijn, geen omweg.

## Regels
1. **Toegang ≠ laag.** Een klant-accordeur toegang geven tot een administratie maakt NOOIT stil een laag aan en vervangt NOOIT bestaande
   lagen. "Administraties toevoegen…" bij een accordeur = alleen scope (`POST /auth/gebruikers/{id}/scope`), mét daarna een expliciete,
   aparte keuze per administratie: "Alleen toegang" (default) · "Ook als laag toevoegen: vóór laag 1 / ná laatste laag" (nooit vervangen;
   bestaande lagen blijven) · "Alleen in een leveranciersroute (opent de route-editor)". Preview toont per administratie wat er nu staat
   ("3 lagen: Peter N. → Sophia → Kempen") en wat het wordt.
2. **Verwijderen bij een administratie** = twee gescheiden vragen: uit de lagen halen (herberekening-telling zoals nu) en/of de toegang
   intrekken. Default: uit de lagen, toegang blijft; toegang intrekken is een tweede vinkje mét uitleg.
3. Bulk-instellen (Instellingen › Klant-accordering › bulk) blijft "lagen zetten" — maar vervangt bestaande lagen alleen ná een
   expliciete bevestiging per administratie mét de huidige stand zichtbaar ("vervangt 3 lagen bij Bouwadvies").
4. Klant-accordering › administratie › accordeur-keuzelijst: staat de gewenste accordeur er niet, toon onder de lijst "Andere klant-
   accordeur toegang geven…" (bestaande `GeenAccordeursMelding`-koppelknop, nu ook als er al accordeurs zijn) — scope-only, dan herladen.

## Bouw & tests
Frontend `AccordeurAdministraties.tsx` (keuze-stap, preview, gescheiden verwijderen), `AccorderingInstellingen.tsx`/`LeverancierRoutes.tsx`
(koppelknop altijd zichtbaar), bulk-dialoog bevestiging. Backend: geen nieuwe route nodig (scope-route bestaat); wel test dat scope-only
géén `accordering_schema_gewijzigd`-audit en géén ronde-herberekening geeft. Vitest: toevoegen zonder laag laat 3 lagen staan;
verwijderen-uit-lagen laat scope staan; bulk toont "vervangt N lagen". Regels naar `docs/regels/accordering-native-app.md` +
`auth-toegang.md`; BESLISSINGEN; WAT_IS_NIEUW ("Toegang geven aan een accordeur verandert de goedkeuringsroute niet meer"). Nameting:
Romy heeft scope Bouwadvies (gezet 18-09 ~19:35 door Peter via Cowork) mét 3 ongewijzigde lagen — controleer dat de audit dat toont.
