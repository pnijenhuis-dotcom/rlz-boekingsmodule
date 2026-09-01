<!--
  "Wat is nieuw" — hand-gecureerd changelog voor kantoorgebruikers (best-practice-punt D1, 01-09).
  REGELS: één blok per release, kop "## JJJJ-MM-DD — Titel", daaronder bullets in KLANTLEESBARE taal
  (geen bestandsnamen, geen migratienummers, geen jargon). Nieuwste release bovenaan. Code vult dit
  bestand bij élke feature-commit aan (de dialoog in de topbar leest het; changelog.test.ts bewaakt de
  vorm). Geen AI.
-->

## 2026-09-01 — Instellingen vernieuwd, slimme autoboek-adviezen en omzetrapporten automatisch

- Instellingen heeft nu een vaste navigatie links (Administraties · Platform · Kantoor) mét een zoekveld: typ bijvoorbeeld "accordering arvum" en spring direct naar de juiste instelling.
- Elke administratie heeft een eigen instellingenpagina met tabs (Algemeen, Boeken & AI, Klant-accordering, Doorbelasting, Uren & materiaal, Voorraad) — deelbaar via de adresbalk.
- Crediteuren-dubbelsignalering staat nu onder Inzicht.
- Autoboeken: het systeem nomineert zelf leveranciers die er klaar voor zijn (minimaal 5 keer op rij ongewijzigd geboekt, bevestigd geheugen, geen open vragen). Zet ze in bulk aan; "Heroverwegen" laat zien waar het ná activatie toch misging.
- Omzetrapporten (kassarapporten) kunnen per administratie automatisch geboekt worden zodra álles groen is — staat standaard uit.
- Nieuw: dit venster. Een stipje op de knop betekent dat er iets bijgekomen is sinds je laatste keer.
- Maandagochtend om 07:30 ontvang je een korte weekmail met de standen per administratie (alleen als er iets te melden is; uitzetten kan onder Beveiliging).
- Veldwerkers uitnodigen: toon de uitnodigingslink als QR-code om op de bouwplaats te scannen.
- De goedkeur-app toont het aantal openstaande facturen als badge op het app-icoon (vanaf de volgende app-versie).

## 2026-08-31 — Bewaking, extractie-terugval en planning

- Elk kwartier controleert het systeem zichzelf (database, opslag, mail, Reeleezee, AI) en mailt bij een storing; herstel wordt óók gemeld.
- Facturen van bekende leveranciers worden ná drie bevestigde exemplaren zonder AI gelezen (lokaal, deterministisch) — sneller, goedkoper en ook beschikbaar als de AI-limiet bereikt is.
- Planning: werkopdrachten per project en periode, plus een transport-dag-agenda met statusflow (gereserveerd → bevestigd → definitief → geleverd).
- De native app kent een pincode-activatie en app-lock (Face ID als gemak, code als anker).
