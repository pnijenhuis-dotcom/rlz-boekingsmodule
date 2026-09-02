<!--
  "Wat is nieuw" — hand-gecureerd changelog voor kantoorgebruikers (best-practice-punt D1, 01-09).
  REGELS: één blok per release, kop "## JJJJ-MM-DD — Titel", daaronder bullets in KLANTLEESBARE taal
  (geen bestandsnamen, geen migratienummers, geen jargon). Nieuwste release bovenaan. Code vult dit
  bestand bij élke feature-commit aan (de dialoog in de topbar leest het; changelog.test.ts bewaakt de
  vorm). Geen AI.
-->

## 2026-09-02 — Verzamelbak: facturen van één pagina worden weer herkend

- Facturen van één pagina kwamen sinds eind augustus vaak ten onrechte in de verzamelbak terecht zonder tenaamstelling, terwijl de AI die wél had gelezen. Dat is opgelost: het aantal pagina's gaat nu als feit mee en een klein foutje in het paginabereik gooit niet langer de hele lezing weg.
- De verzamelbak toont per rij nu de echte reden waarom een document daar ligt (bijvoorbeeld "AI-lezing mislukt" of "tenaamstelling matcht geen administratie"); "geen tenaamstelling gelezen" staat er alleen nog als er werkelijk niets gelezen is.
- Bij een splitsingsvoorstel met een ongeldig paginabereik zie je welk deel het betreft; alleen dat deel wordt afgekeurd, de rest blijft staan.
- De bewaking slaat nu ook alarm als de intake-AI binnen een uur bij de helft van de documenten faalt.

## 2026-09-02 — Bankscherm: rustiger en duidelijker

- De knoppen "Verversen uit Reeleezee" en "Nu verifiëren" zijn weg: verversen gebeurt automatisch bij het openen; "laatst ververst" staat nu vast bovenin de tabel met een klein ⟳ als je toch direct wilt verversen.
- Uitkomsten van het verversen verschijnen kort als melding onderin; de tabel verspringt niet meer.
- Elk afletter-voorstel toont nu de gegevens van de openstaande post: tegenpartij, factuurnummer, boekstuknummer, factuurdatum en het open bedrag — en of het een exacte match is (groen) of dat je even moet bevestigen (oranje, met de reden).
- Bij een deelbetaling zie je vooraf welk bedrag open blijft en heet de knop "Afletteren (deel)".
- Voorbereid: zodra de goedkeur-app in de App Store en Google Play staat, verschijnt automatisch een "Download eerst de app"-verwijzing in de uitnodigingsmail en op het activatiescherm.

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
