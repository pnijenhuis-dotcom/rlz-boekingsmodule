uitgevoerd 2026-09-18 (run A; run B = inbox-opdracht 2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md), rapport: docs/rapporten/2026-09-18-veldapp-ux-run-a.md

Domeinen: uren-planning-veldwerkers, accordering-native-app

# OPDRACHT 18-09 — Veld-app uitvoerder/ZZP'er: 12 UX-verbeteringen (akkoord Peter 18-09 "alle punten")

**Aanleiding:** Peter vroeg 18-09 om een kritische UX-blik op de veld-app (bouwplaats: handschoenen, zon, één hand, haast, slecht
bereik). Cowork stelde twaalf punten voor; Peter: "geef de opdracht voor alle punten". Bouwnorm: `mockup/uren-uitvoerder-v2.html`
(project-eerst-flow) + de punten hieronder; CC werkt de mockup bij (v3) vóór de bouw en toetst aan designpass v2 / KP7. Volgorde:
ná `veldapp-project-eerst-flow` (zelfde componenten). Twee runs: A (direct, zelfde schermen) en B (groter: offline, push).

## Run A — direct
1. **"Zelfde als gisteren"** op elke projectkaart: kopieert uren, m², omschrijving én doorfactureren-keuze van de laatste dag mét
   regels op dat project naar de gekozen dag; één tik, daarna direct opgeslagen; audit `bron=kopie`.
2. **Uren als tikknoppen**: 4 · 6 · 8 · 10 + −/+ per half uur; toetsenbord alleen via "ander aantal". Geen cijfertoetsenbord als default.
3. **Omschrijving als chips**: opbouwen · afbreken · ombouwen · transport · overig (vrij tekstveld alleen bij overig); chips per
   administratie configureerbaar door Beheerder (Instellingen › Uren), default deze vijf; opslag als tekst (geen enum in de DB).
6. **Tikdoelen ≥ 48 px**; "+ Uren" primair, "Meerwerk melden" als tekstlink eronder (één primaire knop per kaart, KP7).
7. **Leesbaarheid buiten**: geen tekst < 14 px in de veld-app, hulptekst minimaal `--muted` op wit met contrast ≥ 4,5:1 (contrast-test
   uitbreiden met de veld-app-tokens).
8. **Week indienen met samenvatting**: "5 dagen · 38 u · 3 projecten · 1 regel zonder m² · 2 niet doorfactureren" + bevestigen;
   ontbrekende werkdag (ma–vr zonder uren) als waarschuwing, niet blokkerend.
9. **Vergeten dag zichtbaar**: dag t/m gisteren zonder uren = oranje rand in de dagbalk.
10. **Terugkoppeling van kantoor in de app**: per week status goedgekeurd (groen vinkje) / afgekeurd mét reden + knop "Aanpassen"
    (heropent de week als concept, audit); melding bij afkeuring.
11. **Doorfactureren ingeklapt**: alleen de vooringevulde chip + "wijzigen"; dropdown pas ná tikken.
12. **Velden verbergen als niet relevant**: m² en omschrijving onder "meer" als het project volgens contract-ontleding geen
    m²-project is (`contract_m2` leeg); anders zichtbaar.

## Run B — groter (eigen opdracht, ná run A; hier alvast gespecificeerd)
4. **Dag-einde herinnering**: push om 16:30 (instelbaar per administratie) "Nog geen uren voor vandaag" — alleen op werkdagen, alleen
   als er die dag geen regel is, één per dag, via de bestaande push-infra; opt-out in ⚙ Toegang.
5. **Offline werkt**: regels lokaal opslaan (IndexedDB) en verzenden zodra er netwerk is; bolletje "nog niet verzonden" per regel en
   per week; conflict (kantoor keurde intussen) = melding, nooit stil overschrijven; `navigator.storage.persist()`; tests met
   netwerk-uit.

## Afronding (per run)
Mockup v3 vóór de bouw + kort UX-review-blok in het rapport; gouden set/veld-app-tests groen; querytelling-meetlat kaartenlijst;
WAT_IS_NIEUW per punt één regel; `docs/regels/uren-planning-veldwerkers.md` + BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter
18-09)"; rapport + INDEX + Gelezen regels; nameting ná deploy op het testaccount (kopie-knop, tikknoppen, indienen zonder m²) —
"werkt in productie: ja/nee".
