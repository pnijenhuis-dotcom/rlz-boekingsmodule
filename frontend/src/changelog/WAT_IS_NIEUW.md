<!--
  "Wat is nieuw" — hand-gecureerd changelog voor kantoorgebruikers (best-practice-punt D1, 01-09).
  REGELS: één blok per release, kop "## JJJJ-MM-DD — Titel", daaronder bullets in KLANTLEESBARE taal
  (geen bestandsnamen, geen migratienummers, geen jargon). Nieuwste release bovenaan. Code vult dit
  bestand bij élke feature-commit aan (de dialoog in de topbar leest het; changelog.test.ts bewaakt de
  vorm). Geen AI.
-->

## 2026-09-02 — Verzamelbak: facturen uit Reeleezee-exports leesbaar en boekbaar

- Facturen die als UBL-bestand uit Reeleezee zelf komen (bijvoorbeeld de onderlinge facturen tussen Universal Nederland en Universal Steigerbouw) tonen nu wél voor wie ze zijn: de tenaamstelling wordt ook gelezen als die alleen als bedrijfsnaam in het bestand staat. Tientallen van zulke facturen stonden ten onrechte met "geen tenaamstelling gelezen" in de verzamelbak.
- Zit de factuur-PDF ín het UBL-bestand ingesloten, dan zie je die PDF nu overal waar het beeld hoort: in het voorbeeld van de verzamelbak, als bijlage op het controlescherm en als bijlage bij de boeking in Reeleezee. Het UBL-bestand zelf blijft naast het beeld downloadbaar.
- De bestaande nazorg-herlezing neemt zulke UBL-rijen nu ook mee (zonder AI): tenaamstelling en suggestie worden gezet en de ingesloten PDF wordt als beeld vastgelegd, zodat de rijen klaarstaan om toe te wijzen. Het toewijzings-geheugen leert daar niets van; dat gebeurt pas bij een menselijke toewijzing.
- Verzamelbak in bulk: vink meerdere rijen aan (of alles binnen het filterveld) en wijs ze in één keer toe aan één administratie — de keuze staat vooringevuld als alle geselecteerde rijen dezelfde suggestie dragen — of handel ze samen af als "hoort niet bij ons" met één reden. Je ziet per rij wat er gebeurd is; een rij die niet verwerkt kon worden komt met de reden terug in de lijst.

## 2026-09-02 — Doorbelasten, controlescherm en bank: minder scrollen, meer werkvolgorde

- Controlescherm opnieuw ingedeeld in werkvolgorde: crediteur → kopgegevens → regels → doorbelasten → boeken, met de knoppen altijd onderin in beeld. Staat alles op groen, dan zie je alleen nog een chip bovenin; alleen afwijkingen verschijnen als regel boven de knoppen. Het losse AI-blok, de e-mailtekst, de tijdlijn en de opmerkingen zijn inklapregels onderaan geworden.
- Crediteur: lijkt een naam op een bestaande crediteur maar wijkt het KvK- of btw-nummer af, dan wordt die niet meer stilletjes voorgesteld — je ziet een waarschuwing en kiest zelf. Met "+ Nieuwe crediteur in RLZ" maak je in één keer een crediteur aan, voorgevuld met naam, KvK, btw en IBAN uit de factuur (het IBAN telt direct als vertrouwd).
- Doorbelasten na boeken is opnieuw ontworpen: één restant-balk laat zien hoeveel van het regelbedrag al verdeeld is; per rij vul je een percentage óf een bedrag in en het andere rekent live mee. De verdeling wordt automatisch opgeslagen zodra die compleet is; de reden waarom de boekknop nog niet actief is staat in één zin onder de tabel.
- Het percentageveld accepteert alleen nog 0–100 met hooguit 2 decimalen (komma of punt); geplakte bedragen zoals "11.100,00" worden geweigerd met uitleg in plaats van doorgerekend.
- Verdeelsleutels zitten achter één menu ("Verdeelsleutel ▾": toepassen of opslaan als sleutel); de grootboekrekening in de doeladministratie staat vooringevuld en is per rij uit te klappen.
- Heeft een doeladministratie nog geen projecten in het systeem, dan staat er nu een knop "Nu synchroniseren" in plaats van een technische melding.
- Bankscherm: mutaties zonder voorstel dragen een klein chipje "handmatig" in plaats van een herhaalde tekstregel; per rij staat nu één knop (Afletteren, Akkoord of Boeken…) met de overige routes (koppelen aan relatie, splitsen, handmatig boeken, intrekken) achter ⋯. De tabel gebruikt de volledige breedte en de omschrijving staat op een eigen regel.
- Controlescherm: bij bladeren met ‹ › laadt de factuur-PDF nu altijd opnieuw (die bleef soms op het vorige document staan), en de uitleg bij de pijltjes verschijnt bij de knop zelf in plaats van linksboven in beeld.
- Goedkeur-app: op het inlogscherm zijn de knoppen "Inloggen met passkey" en "Inloggen met wachtwoord" nu even breed en netjes onder elkaar uitgelijnd.
- Verzamelbak: komt een factuur als UBL én als PDF in dezelfde e-mail binnen, dan wordt dat nu één rij en één document (de gegevens uit de UBL, de PDF als beeld). Een losse UBL toont in het voorbeeld een leesbare samenvatting in plaats van "geen paginabeeld".
- Verzamelbak: selecteer twee rijen en kies "Samenvoegen" als twee bestanden toch dezelfde factuur zijn; jij kiest welk bestand leidend is, niets wordt verwijderd en het is ongedaan te maken.
- Het toewijzings-geheugen leert geen regels meer van kantoor- en doorstuuradressen, en een afzender die steeds naar een andere administratie wijst wordt niet meer voorgesteld.

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
