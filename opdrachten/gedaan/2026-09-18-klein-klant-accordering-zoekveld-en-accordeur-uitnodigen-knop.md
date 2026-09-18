uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-accordering-zoekveld-uitnodigen-bovenop.md

Domeinen: accordering-native-app, kantoor-frontend, werkvoorraad-controlescherm

# KLEIN 18-09 — Instellingen › Klant-accordering: zoekveld + teller, en "geen accordeurs" krijgt een knop (Peter 18-09 live meegekeken)

**Aanleiding:** Peter zocht het blok Leveranciersroutes en zag het niet: de pagina toont 77 ingeklapte administratieregels zonder zoekveld,
zonder teller en zonder indicatie welke administraties accordering aan hebben. Bij BLOW staat ná openklappen de melding "Geen klant-
accordeurs met toegang tot deze administratie — nodig eerst een gebruiker uit …" zonder knop — signalering zonder handeling.

## Bouw
1. **Zoekveld + filter** bovenaan `AccorderingInstellingen.tsx`: zoeken op administratienaam (zelfde normalisatie/`?zoek=`/`/`-focus als
   het zoekveld op de klantenlijst van vandaag — hergebruik die component), filterchips "Accordering aan (N)" · "Met leveranciersroute (N)"
   · "Zonder accordeur (N)"; per regel een compacte samenvatting rechts: "aan · 2 lagen · 1 route" of "uit", zodat je niet hoeft open te
   klappen om te weten wat er staat. Deeplink `?administratie=<id>` klapt die regel open en scrollt ernaartoe (gebruikt vanuit de
   klantpagina).
2. **Melding "Geen klant-accordeurs …"** krijgt twee acties: **"Accordeur uitnodigen →"** (naar Gebruikers & toegang, uitnodigingsformulier
   voorgevuld met rol Klant-accordeur + deze administratie in scope) en **"Bestaande accordeur koppelen →"** (lijst van klant-accordeurs
   van het kantoor mét vinkje voor deze administratie; scope-wijziging = audit, Beheerder-only zoals nu). Zelfde melding/acties in de
   leveranciersroute-editor als de accordeurlijst leeg is.
3. Leveranciersroute-editor: leverancierskeuze als zoekbare combobox (regel kantoor-frontend: geen kale select), gepland eerst = crediteuren
   mét open documenten in deze administratie bovenaan.
4. Guards: overflow-sweep, contrast, vitest op filter/teller, "geen accordeurs" → beide knoppen aanwezig, deeplink opent de juiste regel.
   WAT_IS_NIEUW ("Klant-accordering: zoeken en filteren, en direct een accordeur uitnodigen"). Rapport + INDEX + Gelezen regels; nameting:
   `/instellingen/accordering?zoek=blow` toont één regel, opengeklapt via deeplink — "werkt in productie: ja/nee".

## 0. BUG (eerst, live gezien 18-09 bij Bouwadvies Oost Nederland op 1385 px breed)
Het paneel Klant-accordering is breder dan het venster: "+ Laag toevoegen", "Opslaan", "+ Leveranciersroute" en "Toegang intrekken"
staan rechts BUITEN beeld (pagina scrollt horizontaal). Peter kon "+ Leveranciersroute" daardoor niet vinden — het blok leek te ontbreken.
Oorzaak zoeken in `AccorderingInstellingen.tsx`/`LeverancierRoutes.tsx`/toestellentabel (vaste breedtes of `white-space: nowrap` op de
lange hint-teksten; de `.actions`-rij staat rechts uitgelijnd op een te brede container). Fix volgens de overflow-regel (geen horizontale
pagina-overflow; tabel scrollt bínnen `.tabel-scroll`), knoppen links onder het blok of in beeld; overflow-sweep-test op 1280 en 1385 px.

## 5. Leveranciersroute "bovenop de gewone route" (Peter 18-09, casus Bouwadvies Oost Nederland: 3 lagen + een 4e alleen voor 2 leveranciers)
Nu vervangt een leveranciersroute de hele route → Peter moet de drie bestaande lagen kopiëren in de nieuwe route, en die kopie loopt
stil uit de pas als de gewone route wijzigt. Bouw in de route-editor een keuze **"Vervangt de gewone route"** (huidig gedrag, default)
of **"Bovenop de gewone route"** mét positie van de extra laag/lagen (vóór laag 1 · ná de laatste laag). Motor (`accordering/service`):
bij "bovenop" = de gewone lagen van de administratie op het moment van de ronde + de extra lagen op de gekozen positie; herberekening bij
configuratiewijziging zoals nu (herberekenen i.p.v. vervallen); voorrang afdelingsroute > leveranciersroute blijft; tijdlijn toont
"route: gewoon + extra laag ‹naam› (leveranciersroute ‹naam›)". Migratie: kolom `modus` + `positie` op de leveranciersroute; bestaande
routes = 'vervangt'. Tests: bovenop-vóór, bovenop-ná, wijziging gewone route werkt door in lopende ronden, drempels per laag blijven
werken. Regels-tekst naar `docs/regels/accordering-native-app.md`; BESLISSINGEN-rij; WAT_IS_NIEUW.
