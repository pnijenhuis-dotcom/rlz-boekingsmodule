<!--
  "Wat is nieuw" — hand-gecureerd changelog voor kantoorgebruikers (best-practice-punt D1, 01-09).
  REGELS: één blok per release, kop "## JJJJ-MM-DD — Titel", daaronder bullets in KLANTLEESBARE taal
  (geen bestandsnamen, geen migratienummers, geen jargon). Nieuwste release bovenaan. Code vult dit
  bestand bij élke feature-commit aan (de dialoog in de topbar leest het; changelog.test.ts bewaakt de
  vorm). Geen AI.
-->

## 2026-09-10 — Reconciliatie zonder ruis, overzichtelijker gebruikersscherm, autoboeken leert sneller, AI-controle valt niet meer stil

<!-- vervolgrun-10-09-avond:1 -->
- De controle "mogelijk dubbel geboekt in Reeleezee" meldt nu één regel per leverancier en factuurnummer met álle boekstuknummers erbij, in plaats van elke combinatie apart — en zwijgt over referenties die geen factuurnummer zijn (een IBAN of een klantnummer dat op elke factuur staat).
- Twee concept-facturen met dezelfde referentie, dezelfde datum en hetzelfde bedrag staan nu bovenaan als "Waarschijnlijk dubbel"; de overige gevallen heten "Zelfde referentie, controleer".
- Eerder geaccepteerde beoordelingen blijven gelden; een cluster waar een nieuw, nog niet beoordeeld exemplaar bij zit komt wél opnieuw ter controle.

<!-- vervolgrun-10-09-avond:2 -->
- Gebruikers & toegang: de tabellen op de tabs Kantoor, Veldwerkers en Klant-accordeurs zijn opnieuw ingedeeld — elke kolom heeft een vaste minimumbreedte, de koppen worden nooit meer afgekapt en de beveiligings- en statuslabels staan netjes op één regel.
- Per gebruiker staat nog maar één knop direct in beeld (Opnieuw mailen of Herstel-link); de overige handelingen (e-mail wijzigen, scope, blokkeren, archiveren) vind je achter het ⋯-menu op de rij.

<!-- vervolgrun-10-09-avond:3 -->
- Autoboeken leert sneller: een leverancier wordt automatisch geboekt zodra een medewerker drie keer op rij exact hetzelfde heeft geboekt — de eerste boeking telt nu ook mee (voorheen waren er in de praktijk vier nodig).
- De stand per leverancier heet nu "N identieke boekingen" in plaats van "N op rij ongewijzigd"; de teller "leert (n/3)" volgt dezelfde telling.

<!-- nametingen-run-10-09:3.1 -->
- Het boekingsgeheugen kijkt nu vooral naar wat een medewerker de laatste keren koos: zijn de laatste drie boekingen van een leverancier identiek, dan is dat voorstel groen — ook als er lang geleden één keer iets anders geboekt is. Die oudere keuze blijft zichtbaar als "eerder ook: …" onder het voorstel.
- Automatisch geboekte facturen tellen daarbij niet mee als bevestiging; alleen boekingen door een medewerker doen dat.

<!-- vervolgrun-10-09-avond:4 -->
- Een storing of ontbrekende instelling van de AI-controle zet het automatisch boeken niet meer stil: de vaste controles (rekening, btw, project, geheugen) blijven de eis, en een boeking die zonder AI-controle doorliep krijgt het label "zonder AI-toets" op de rij en in de tijdlijn.
- In de reconciliatie ziet u per dag hoeveel boekingen zonder AI-controle doorliepen en waarom, met een melding "controleer steekproefsgewijs" en een directe link naar de bankrekening of documentenlijst.
- Een AI-twijfel blijft zoals het was: die boeking wacht op een medewerker.

## 2026-09-10 — Autoboeken per administratie, slimmere bankvoorstellen met AI-controle, eerlijke activatie

<!-- bundel-10-09:A -->
- Per administratie kunt u nu één schakelaar "Autoboeken (leren en boeken)" aanzetten. Het systeem leert dan zelf: heeft u van een leverancier drie keer op rij precies dezelfde boeking gemaakt (zelfde grootboekrekening, btw en project), dan boekt de volgende factuur van die leverancier automatisch — mits alle controles groen zijn. U hoeft geen lijst met leveranciers meer bij te houden.
- De lijst per leverancier op de tab Boeken & AI is nu een uitzonderingenlijst: u ziet per leverancier "leert (n/3)", "boekt automatisch" of "uitgezonderd". Wilt u een leverancier nooit automatisch laten boeken, dan zondert u hem uit met een reden; vrijgeven kan altijd.
- Draait u een automatische boeking terug (tegenboeken of opnieuw boeken), dan begint het leren voor die leverancier opnieuw bij 0 van 3; dat staat in de tijdlijn van de factuur.
- Een administratie die kosten doorbelast aan andere entiteiten kan deze schakelaar niet aanzetten: daar blijft de verdeling mensenwerk en het systeem zegt dat er ook bij.
- In het overzicht Automatiseringen (Instellingen › Boeken en Inzicht › Reconciliatie) ziet u per administratie hoeveel leveranciers leren, automatisch boeken of zijn uitgezonderd, en hoeveel facturen vandaag automatisch zijn geboekt.

<!-- bundel-10-09:B -->
- Terugkerende bankafschrijvingen zonder factuur (huur, abonnementen, verzekeringen) krijgen nu automatisch een boekvoorstel uit de eigen historie: staat dezelfde tegenrekening met dezelfde omschrijving al minstens drie keer op één grootboekrekening, dan ziet u "historie-regel — 3 van 3 op …" en boekt het systeem die mutatie zelf zodra automatisch boeken voor de administratie aan staat. Wijkt de historie af, dan staat er "k van n" en bevestigt u zelf.
- Vóór elke automatische bankboeking kijkt een AI-controle mee of het voorstel plausibel is voor deze omschrijving, tegenpartij en bedrag. De AI kiest nooit zelf een rekening; bij twijfel blijft de mutatie gewoon open in uw werkvoorraad met de reden als label. Is de AI niet beschikbaar, dan wordt er niet geboekt en ziet u dat ook. (Herzien later op 10-09: zie de release hierboven — een storing van de AI-controle zet het boeken niet meer stil.)
- Dezelfde plausibiliteitscontrole staat als extra poort op automatisch geboekte inkoopfacturen; een beheerder kan die onder Instellingen › Boeken uitzetten (standaard aan).

<!-- bundel-10-09:F -->
- Lukt het bij het activeren van de goedkeur-app een keer niet om uw nieuwe toegangscode veilig op het toestel op te slaan, dan zegt de app dat nu eerlijk en gaat hij niet door naar uw facturen. U ziet de melding, een korte diagnoseregel om naar het kantoor te sturen (zonder uw code) en een knop "Opnieuw proberen" — u hoeft de activatiecode of link niet opnieuw in te voeren.

## 2026-09-10 — Toegangscode wijzigen in de app werkt weer betrouwbaar

<!-- bugfix 10-09: toegangscode wijzigen Android (ZTE), één codepad native + PWA -->
- In de goedkeur-app kunt u uw toegangscode weer wijzigen zonder de melding "niet gelukt": na het invoeren van uw huidige code wordt de nieuwe code direct vastgelegd en pas bevestigd als hij aantoonbaar is opgeslagen. Lukt het opslaan op uw toestel een keer niet, dan blijft uw oude code gewoon werken en zegt de app dat eerlijk.

## 2026-09-09 — De dagelijkse mail zegt alleen nog wat u moet doen; gegeven akkoorden blijven staan

<!-- bundel 09-09: blok 1 actiemail + systeemmail, blok 2 accorderingsronde herberekenen -->
### De dagelijkse mail zegt alleen nog wat u moet doen
- De dagelijkse controlemail van de boekhouding is herschreven: u krijgt alleen nog een bericht als er echt iets te doen is, met bovenaan "N zaken vragen je aandacht" en per zaak één regel: welke administratie, welke leverancier of boeking, en wat er afwijkt.
- Eén link brengt u naar Inzicht › Reconciliatie, waar u elke zaak direct afhandelt. Meer dan tien zaken? Dan staan de eerste tien in de mail en ziet u de rest in het overzicht.
- Alle technische details (standen per controle, tellers, automatiseringen) zitten niet meer in uw mail; die gaan apart naar het beheer en blijven zichtbaar op Instellingen › Boeken en Inzicht › Reconciliatie.
- Een melding die op een fout in het systeem wijst, ziet u nu als "Systeemfout — automatisch gemeld": het beheer wordt automatisch gewaarschuwd, u hoeft er niets mee.
### Een accordering die al gegeven is blijft staan bij het wijzigen van accordeurs
- Past u de accordeurs, lagen of bedraggrenzen van een klant aan terwijl er facturen bij de klant liggen, dan gaan die facturen niet meer terug naar "Klaar om te boeken". De lopende goedkeuring wordt opnieuw berekend: akkoorden die al gegeven zijn blijven staan, en alleen de ontbrekende stap wordt bij de juiste accordeur aangevraagd.
- Is na de wijziging alles al akkoord, dan gaat de factuur meteen door naar het boeken, precies zoals na een laatste akkoord.
- Alleen als geen enkel gegeven akkoord meer past (bijvoorbeeld omdat de enige accordeur die al akkoord gaf is weggehaald) vervalt de ronde nog; dat ziet u dan zoals voorheen, met reden en de melding op de documentenlijst.
- Vooraf ziet u wat er gebeurt: "N lopende accorderingsrondes worden herberekend, waarvan M vervallen" — in het instellingenscherm van de klant, in de bulk-actie en bij het verwijderen van een accordeur.
- In de tijdlijn van de factuur staat leesbaar wat er is gebeurd: hoeveel akkoorden behouden bleven, welke stap opnieuw is aangevraagd en wie de wijziging deed.

## 2026-09-09 — Goedkeur-app versie 1.1 (App Store en Google Play)

<!-- mini-run 09-09: Apple keurde 1.0 goed, 1.1 draagt de nieuwe activatie -->
- **De goedkeur-app is door Apple goedgekeurd en heet vanaf nu versie 1.1.** Apple heeft de eerste versie van de app (1.0) op 9 september goedgekeurd. De versie met de nieuwe manier van activeren (activatiecode en 5-cijferige code, geen passkey of wachtwoord meer) wordt als versie 1.1 ingediend bij Apple en Google. Onder "Toegang tot de app" toont de regel "Laatste koude start" nu ook in de browser-versie welke app-versie u gebruikt.
- **Download-knop voor iPhone en iPad.** In de uitnodigingsmail voor accordeurs en veldwerkers en op het scherm dat u op een computer ziet als u een uitnodigingslink opent, staat nu het blok "Download eerst de app" met de knop "iPhone / iPad — App Store". De Android-knop volgt zodra Google de app heeft goedgekeurd.

## 2026-09-09 — Intercompany-leveranciers zelf instellen

<!-- nachtrun 08/09-09 blok 1 -->
- **Intercompany-facturen hoeven niet meer langs de accordeur — en u bepaalt nu zelf welke leveranciers dat zijn.** Onder Instellingen › Administraties › ‹administratie› › Klant-accordering staat het blok "Intercompany — accordering overslaan". Kies daar een crediteur (typ om te zoeken), geef eventueel een reden op en klik "Markeren als intercompany". Facturen van die leverancier worden in die administratie gewoon gecontroleerd en direct geboekt, zonder de stap bij de klant-accordeur. Alleen een Beheerder kan dit instellen.
- **Verwijderen kan altijd.** Achter een zelf toegevoegde leverancier staat een kruisje; daarna gaan zijn facturen weer gewoon ter accordering. Leveranciers die uit de doorbelasting komen staan er met het label "doorbelasting" bij en zijn alleen te lezen — die volgen de doorbelasting-instellingen.
- **Alles blijft terug te vinden.** Onder het blok staat een historie: wie welke leverancier wanneer heeft toegevoegd of verwijderd, met de opgegeven reden.

## 2026-09-08 — Bank dagelijks automatisch, betere bankvoorstellen, declaraties en betaalstatus

<!-- bundel-08-09-avond blokken 1–6 -->
- **De bank wordt elke nacht automatisch bijgewerkt.** Voor álle administraties haalt de app rond 07:00 uur de nieuwe bankmutaties, open posten en saldi uit Reeleezee — u hoeft een klant niet meer te openen om "de eerste bank-sync te starten". Het openen van een bankscherm ververst daarnaast nog steeds direct.
- **Laatste sync per klant zichtbaar.** In Bank controleren ziet u per administratie wanneer de bank voor het laatst is bijgewerkt (datum en tijd). Is een administratie nog nooit bijgewerkt, dan staat er "nog niet gesynchroniseerd — vannacht automatisch".
- **Versheid als duidelijke chip.** Boven de lijst met onverwerkte bankmutaties staat nu een goed zichtbare chip: "laatst ververst 07:02", "⟳ verversen uit Reeleezee…" terwijl de app bezig is, en "zojuist ververst" (groen) zodra de lijst is bijgewerkt — de lijst laadt dan vanzelf opnieuw.
- **Dagelijkse controle op de bank-sync.** In de dagelijkse reconciliatie-mail en onder Instellingen staat een regel "Bank-sync": hoeveel administraties verwacht, bijgewerkt en overgeslagen zijn, met de reden (bijvoorbeeld een administratie die op Odoo draait of waarvoor nog geen webservice-login is geregistreerd). Blijft een administratie een dag zonder bijwerking terwijl dat wél kon, dan staat dat als aandachtspunt in de lijst.
- **Oude afletteringen opgeruimd uit het zicht.** In het bankscherm staan afletteringen die langer dan dertig dagen geleden zijn afgerond niet meer standaard in de lijst "Afletteren via Reeleezee — levenscyclus". Met "Toon verwerkte mutaties ouder dan 30 dagen (N)" haalt u ze erbij; het aantal staat er altijd bij. Opdrachten die nog wachten op een handeling blijven altijd zichtbaar.
### Bankvoorstellen alleen nog bij naam/rekening + nummer + bedrag
- Een bankmutatie krijgt alleen nog een groen afletter-voorstel als álles klopt: de richting van het geld (een verkoopfactuur bij een bijschrijving, een inkoopfactuur bij een afschrijving), de naam of het rekeningnummer van de tegenpartij, het factuurnummer als los nummer in de omschrijving én het bedrag op de cent. Alleen zo'n groen voorstel komt in aanmerking voor automatisch afletteren.
- Klopt het factuurnummer en het bedrag maar is de naam anders, of klopt naam en nummer maar wijkt het bedrag af (deelbetaling)? Dan zie je een oranje voorstel om te bevestigen, met erbij wat wél en wat niet klopte — bijvoorbeeld "nummer + bedrag, naam onbekend".
- Een factuurnummer dat toevallig als reeks cijfers in een langer betalingskenmerk voorkomt telt niet meer. Een bijschrijving wordt nooit meer aan een inkoopfactuur gekoppeld, een afschrijving nooit aan een verkoopfactuur.
- De module leert rekeningnummers: bevestig je een aflettering, dan onthoudt de module dat dit rekeningnummer bij die relatie hoort. Betaalt die relatie de volgende keer onder een andere naam (bijvoorbeeld een privérekening voor een B.V.), dan herkent de module dat aan het rekeningnummer.
- **Declaraties doorsturen naar declaraties@ak-nijenhuis.nl.** Heeft een medewerker een factuur of bon al zelf betaald (declaratie), stuur die dan naar declaraties@ in plaats van facturen@. Zo'n document komt in dezelfde werkvoorraad, maar staat op het controlescherm meteen op "Betaald per bank": na het boeken blijft de post in Reeleezee open tot de bankafschrijving hem sluit, zonder dat hij in de betaallijst verschijnt — dus geen dubbele betaling.
- **Betaalstatus op het controlescherm.** Bij de kopgegevens staat een nieuw veld "Betaalstatus (Reeleezee)" met dezelfde acht keuzes als in Reeleezee (Nog te betalen, Wordt automatisch geïncasseerd, Betaald per bank, Betaald met PIN, Betaald met Creditcard, Betaald - contant, Verrekend met prive, Verrekend met Rekening Courant). Wat u hier kiest, gaat bij het boeken mee naar Reeleezee. Een label bij het veld laat zien waar de waarde vandaan komt: "uit kanaal (declaratie)", "uit factuur (incasso)" of "handmatig".
- **Incasso-facturen worden herkend.** Zegt een factuur dat het bedrag automatisch wordt geïncasseerd (bijvoorbeeld "wordt automatisch geïncasseerd op of rond 25 september" of een digitale factuur met SEPA-incasso als betaalwijze), dan staat de betaalstatus vanzelf op "Wordt automatisch geïncasseerd" en onthouden we de verwachte afschrijfdatum. Het herkennen gebeurt in vaste regels, niet door AI; de gelezen zin ziet u als toelichting bij het label. Klopt het niet, kies dan gewoon een andere waarde — uw keuze wint en wordt nooit meer overschreven.
- **Een declaratie boekt niet zonder betaalstatus.** Voor documenten die via declaraties@ binnenkwamen is een betaalstatus verplicht; ontbreekt die (of staat er "Nog te betalen"), dan blokkeert de controle "Betaalstatus (declaraties)" het boeken met een duidelijke melding.
- **Administraties op Odoo.** Odoo kent geen vergelijkbaar veld dat een factuur open houdt maar uit de betaallijst haalt; daar gaat de betaalstatus niet mee. U ziet dat als melding in de tijdlijn van het document, het boeken zelf gaat gewoon door.
- **Facturen van een eigen groepsbedrijf gaan niet meer langs de klant-accordeur.** Staat voor een administratie de klant-goedkeuring aan, dan werd tot nu élke factuur eerst aan de accordeur voorgelegd — ook facturen van een bedrijf uit dezelfde groep (intercompany). Die stap wordt nu overgeslagen: de factuur wordt gewoon gecontroleerd (alle harde controles blijven) en direct geboekt, ook bij automatisch boeken. Op het controlescherm heet de knop dan "Boeken" in plaats van "Ter accordering", met de uitleg "intercompany — klant-accordering wordt overgeslagen".
- **Zichtbaar in de historie.** Op het document staat in de tijdlijn en bij "Klant-accordering" de regel "overgeslagen — intercompany" met de naam van de leverancier; er is niets te doen. De accordeur krijgt de factuur niet in zijn wachtrij.
- **Welke leveranciers tellen als intercompany?** Dezelfde lijst die de doorbelasting al gebruikt (de groepsbedrijven per administratie). Staat een leverancier daar niet in, dan verandert er niets: de factuur gaat zoals altijd ter accordering.
- **Ligt een factuur al bij de accordeur?** Dan blijft die ronde gewoon lopen; het kantoor kan de factuur terughalen en direct boeken.
### Overzicht van automatische verwerking verhuisd naar Instellingen
- Het overzicht "Automatiseringen" (hoeveel is er automatisch verwerkt, wat werd overgeslagen en waarom) staat niet meer bovenaan Inzicht › Reconciliatie, maar bij Instellingen › Boeken platformbreed. Op Inzicht › Reconciliatie ziet u alleen nog meldingen waar u iets mee kunt doen.
- Het overzicht is standaard ingeklapt tot één regel, bijvoorbeeld "9 aan · 1 let-op". Het klapt vanzelf open als er iets is dat aandacht vraagt, met per regel een knop "Naar de instelling →". Uitgeschakelde onderdelen worden niet getoond.
- In de dagelijkse e-mail over de reconciliatie staat het volledige overzicht alleen nog als er iets afwijkt; anders één regel "Automatiseringen: alles gelopen".
- Zoek in Instellingen op "automatiseringen" of "tellers" om het overzicht direct te vinden.

## 2026-09-08 — Inloggen in de app is eenvoudiger geworden

<!-- app-auth-zonder-passkey-08-09 blok C -->
- De goedkeur-app (iPhone, Android én de webversie op je telefoon) vraagt geen passkey, Face ID of wachtwoord meer om in te loggen. Je activeert de app één keer op je eigen toestel en kiest een 5-cijferige code; daarna opent de app met die code.
- Activeren gaat met de link uit de uitnodigingsmail van het kantoor, of — als de link niet opent of je op een ander toestel zit — met de activatiecode die in dezelfde mail staat (acht tekens, bijvoorbeeld ABCD-2345). De code is 72 uur geldig en werkt één keer.
- Face ID of vingerafdruk blijft mogelijk als gemak: zet het aan onder ⚙ Toegang tot de app. De code werkt altijd, ook als de herkenning een keer niet lukt.
- Onder ⚙ Toegang tot de app kun je je code wijzigen (met je huidige code) en dit toestel loskoppelen. Je ziet daar ook wanneer je de code voor het laatst hebt gewijzigd.
- Vijf keer een verkeerde code: de app wist de toegang op dit toestel en meldt dat bij het kantoor. Opnieuw activeren kan met een nieuwe uitnodiging; de knop "Kantoor vragen om nieuwe uitnodiging" staat in het scherm.
- Kantoor: na "Uitnodigen", "Opnieuw mailen" of "Herstel-link sturen" voor een app-gebruiker staat de activatiecode naast de link, met een kopieerknop. Bij Gebruikers zie je gekoppelde toestellen ("Toestel · iPhone van Jan") en kun je een toestel intrekken; oude passkeys staan er grijs bij als "niet meer gebruikt".
- Wie de app al gebruikt, hoeft niets te doen zolang de huidige toegang loopt; is die verlopen, dan vraagt de app één keer om opnieuw te activeren met een nieuwe uitnodiging van het kantoor.
- De kantoor-webapp verandert niet: daar log je in zoals je gewend bent (passkey, of wachtwoord met verificatiecode).
- Een activatiecode kan niet worden geraden: na vijf mislukte pogingen (per uitnodiging én per netwerkadres) blokkeert het activeren een uur, en het kantoor kan altijd een nieuwe uitnodiging sturen.
- Een toestel opnieuw koppelen (bijvoorbeeld ná een nieuwe telefoon of vijf keer een foute toegangscode) gaat via de bekende herstel-link van het kantoor; oude toestellen worden daarbij automatisch losgekoppeld.
- De oude inlogroutes van de app (passkey en wachtwoord) blijven tot 8 oktober 2026 werken voor wie de app nog niet heeft bijgewerkt; daarna geven ze een duidelijke melding om de app te activeren met de activatiecode.
- Ook in de browser-versie (app op het beginscherm). De browser-versie werkt nu precies zoals de app uit de App Store / Google Play: activeren met code of link, daarna je toegangscode. Gebruikte je de browser-versie al? Dan vraag je het kantoor één keer om een nieuwe uitnodiging.
- Toegang verlopen of ingetrokken? Dan zie je het activatiescherm met een melding en de knop "Kantoor vragen om nieuwe uitnodiging" — één tik, het kantoor weet het.
- De knop rechtsboven heet nu "Vergrendelen" (was "Uitloggen") en zet de app op slot. Het toestel blijft gekoppeld; bij de volgende keer openen voer je je toegangscode in. Echt loskoppelen doe je via ⚙ Toegang tot de app.
<!-- app-auth-zonder-passkey-08-09 blok D (kantoor) -->
- **Activatiecode bij elke app-uitnodiging.** Nodigt u een accordeur of veldwerker uit, mailt u een uitnodiging opnieuw of stuurt u een herstel-link, dan ziet u naast de link nu ook de activatiecode (bijvoorbeeld `K7PQ-3WXM`) met een knop "Kopiëren". Die code staat ook in de mail en is bedoeld voor wie de link niet kan openen of op een ander toestel wil activeren; hij is even lang geldig als de link (72 uur) en eenmalig te gebruiken. Kantoormedewerkers krijgen geen code — voor hen verandert er niets.
- **Apparatenlijst toont toestellen.** Bij klant-accordeurs (Gebruikers & toegang en Instellingen › Klant-accordering) ziet u per gekoppeld toestel de naam, het platform (iOS/Android/browser), wanneer het gekoppeld is en wanneer het voor het laatst gebruikt is. Een oude passkey die niet meer in gebruik is, blijft grijs zichtbaar met de aanduiding "passkey — niet meer gebruikt" — er verdwijnt niets.
- **Kill-switch werkt voor toestellen én passkeys.** "Kill-switch" en "Toegang intrekken" blokkeren een toestel per direct, met dezelfde bevestiging als voorheen. De gebruiker kan daarna alleen verder met een nieuwe uitnodiging of herstel-link.
- **Activatiepagina zonder passkey-uitleg.** Opent een accordeur of veldwerker de uitnodigingslink op een pc, dan ziet hij een QR-code voor zijn telefoon en de tip om anders de activatiecode uit de mail in de app in te voeren. Op een telefoon gaat de link direct door naar de app. Voor kantoormedewerkers blijft de activatie (wachtwoord + tweede factor) precies zoals die was.


## 2026-09-08 — Basis eerst: UBL direct gevuld, lijst = kantoorwerk, duplicaten en verlegd-btw deterministisch

<!-- herstelrun-basis-eerst-08-09 -->
- Achter de schermen: elke wijziging aan het inlezen van facturen, het controlescherm en de documentenlijst wordt nu eerst getoetst op een vaste set échte (geanonimiseerde) facturen uit de praktijk — onder meer een factuur die twee keer binnenkwam, een factuur met UBL én PDF, een scan met tariefregels, een gesplitste meervoudige PDF en een creditnota. Pas als die set klopt én het gedrag na de uitrol in de praktijk is nagekeken, geldt een verbetering als klaar.
- Het controlescherm en de documentenlijst worden voor die facturen ook als plaatje vergeleken met de vorige versie, zodat een onbedoelde wijziging in het scherm direct opvalt.
- De wachtrij in de goedkeur-app laadt weer snel, ook als veel facturen een doorbelasting hebben: de verdeling per bedrijf wordt nu in één keer voor de hele lijst opgehaald in plaats van per factuur. Wat u op de kaart ziet (bedrijf, aandeel, bedrag, provisie) is ongewijzigd.
- In de samenvatting van de dagelijkse controle staat nu ook of de directe verwerking van geüploade facturen goed is gestart; mislukt dat een keer, dan ziet u dat als aandachtspunt (de factuur wordt dan binnen tien minuten alsnog verwerkt).
- Een digitale factuur (UBL/XML) is nu direct compleet bij binnenkomst: leverancier (herkend op KvK-, btw-nummer, IBAN of naam), factuurnummer, factuur- en vervaldatum, totaal en factuurregels mét btw-code staan al klaar vóór u het document opent — zonder AI en zonder wachten op "Wordt verwerkt…".
- "+ Nieuwe crediteur in RLZ" is bij zo'n factuur voorgevuld met naam, KvK-nummer, btw-nummer, IBAN en het adres uit de factuur (gemarkeerd "uit UBL"); bij een gescande PDF die nog verwerkt wordt zegt het venster dat de velden nog volgen, in plaats van leeg te blijven.
- De duplicaatcontrole zegt precies wat er nog ontbreekt ("kies of maak de crediteur; het factuurnummer is bekend") en niet meer "zonder crediteur en referentie" terwijl het factuurnummer er al staat.
- Staat een factuur al geboekt in Reeleezee (buiten de app om), dan wordt het binnengekomen exemplaar direct afgevoerd met de reden "Al geboekt in RLZ (buiten de module)" én het boekstuknummer — zodra leverancier en factuurnummer bekend zijn, dus bij een UBL al bij binnenkomst en bij een PDF direct na de uitlezing. Terug te vinden via "Toon afgehandelde documenten".
- Kan die controle niet draaien (geen Reeleezee-koppeling), dan staat dat als regel in de tijdlijn van het document; de factuur blijft gewoon in de werkvoorraad.
- Op het echte document ziet u nu "N exemplaren samengevoegd/afgevoerd" — ook de als duplicaat afgevoerde exemplaren tellen mee.
- Bij Gebruikers › Klant-accordeurs kun je per accordeur de administraties nu direct beheren: "beheren" opent het lijstje met per administratie een link naar de accorderingsinstellingen van die klant.
- "Administraties toevoegen…" kiest een of meer klanten en zet de accordeur in één keer in de klant-accordering van die klanten, met vooraf een overzicht van wat er verandert.
- "Verwijderen…" haalt de accordeur uit de accordering en de toegang van die klant, met vooraf de waarschuwing welke lopende accorderingen daardoor vervallen.
- Een gearchiveerde klant heet nu gewoon bij zijn naam met "— gearchiveerd" erachter, in plaats van een technische code.
- Facturen met "btw verlegd" krijgen nu altijd een eenduidige verlegd-code voorgesteld: eerst uw eigen voorkeur per administratie, anders de code die in de Reeleezee-historie van die administratie het meest gebruikt is — nooit meer toeval. Het controlescherm laat bij de btw-code zien waaróm die code gekozen is ("voorkeur beheerder", "meest gebruikt in RLZ-historie (12×)", "administratie-default").
- Instellingen › Administraties › Boeken & AI heeft een nieuwe rij "Verlegd-tarief bij btw verlegd": kies een vaste verlegd-code of laat de historie beslissen; de rij toont wat er nu gekozen wordt en waarom.
- De dagelijkse controle "mogelijk dubbel geboekt in Reeleezee" kijkt nu alleen nog naar facturen van dezelfde leverancier met hetzelfde factuurnummer. Facturen met alleen hetzelfde bedrag op dezelfde dag (bijvoorbeeld reeksfacturen) worden niet meer gemeld, en algemene teksten als "Ingescand document" tellen niet als factuurnummer.
- De hercontrole van de projectverdeling gaf bij pas geboekte facturen een vals signaal ("0 % afwijking", nieuwe verdeling € 0,00). Dat is opgelost: een verdeling wordt pas gecontroleerd als de omzetmaand voorbij is, nooit in de maand van boeken, en hooguit één keer per maand.
- Ontbreken de omzetcijfers voor een maand, dan ziet u dat nu als aparte melding "omzetcijfers ontbreken voor ‹maand›" met de knop "Cijfers-sync starten" — in plaats van een herverdeling met lege bedragen.
- De documentenlijst van een klant toont nu alleen nog wat het kantoor zelf moet doen: controleren, boeken, afmaken, mislukte boekingen en twijfelgevallen. "Alle" telt precies dat.
- Documenten die bij de klant ter accordering liggen of waar een vraag over openstaat, staan bij elkaar onder één knop "Wachten op anderen (N)". Ze tellen niet mee in "Alle".
- Geboekte documenten staan niet meer tussen het werk. Zet "Toon afgehandelde documenten" aan en ze verschijnen grijs, met het boekstuknummer en "Open in Reeleezee" (of Odoo). Zoeken en Archief vinden ze zoals altijd.
- Oude links naar een status (bijvoorbeeld "bij klant" of "geboekt") blijven werken.

## 2026-09-08 — Snellere accordeur-app, controlescherm scherper, duplicaten uit het zicht

<!-- bundel-08-09 blok 1 -->
- De goedkeur-app laadt de wachtrij nu in een fractie van de tijd, ook als u bij veel administraties meekijkt — de "wachtrij kon niet geladen worden"-melding door een trage server is daarmee weg.
- Duurt het verversen toch even, dan blijven uw kaarten gewoon staan en ziet u "verversen duurt lang…"; mislukt het, dan staat er "verversen mislukt — stand van HH:MM" met een knop Opnieuw in plaats van een leeg scherm.
- Een factuur die op kantoor wordt geüpload of gesleept vertraagt andere gebruikers niet meer.
- Een factuur uploaden is nu direct klaar: het bestand staat binnen een paar seconden in de lijst met het label "Wordt verwerkt…" en de automatische uitlezing loopt op de achtergrond door — geen wachten meer en geen foutmelding terwijl de upload eigenlijk gelukt was.
- Duurt een upload toch onverwacht lang, dan zegt het scherm dat u de lijst even moet controleren in plaats van "geen verbinding" — en vraagt het u nadrukkelijk het bestand niet nog eens te uploaden.

<!-- bundel-08-09 blok 7 -->
- Kantoor: al geboekte inkoopfacturen kunnen in één keer hun factuurperiode (weeknummers) krijgen, zodat kosten per week ook voor oudere boekingen kloppen; een handmatig ingevulde periode blijft altijd staan.

<!-- bundel-08-09 blok 6 -->
- De dagelijkse controle (Inzicht › Reconciliatie) kijkt nu ook in Reeleezee zelf naar mogelijk dubbel ingevoerde inkoopfacturen: twee facturen van dezelfde leverancier met hetzelfde factuurnummer, of met hetzelfde bedrag op dezelfde datum, waarvan er minstens één met de hand in Reeleezee is ingevoerd.
- Zo'n paar staat als één regel in de lijst met beide boekstuknummers, de bedragen en de datums; klik op een boekstuknummer om het te kopiëren en zoek het op in Reeleezee. Beoordelen en corrigeren doe je in Reeleezee — de app verwijdert er nooit iets.
- Klopt het toch (twee echte facturen)? Dan accepteer je de melding met een reden; ze komt daarna niet opnieuw in de mail.
- Nog-niet-geboekte concepten tellen mee en staan als "nog concept" gemarkeerd; wat de app zelf boekte wordt niet tegen zichzelf gemeld.

<!-- bundel-08-09 blok 5 -->
- Materiaalcatalogus (Instellingen): "geen crediteur-koppeling", "transport-contact: nog niet ingevuld" en "materiaal-contact: nog niet ingevuld" zijn nu direct klikbaar — je hoeft niet meer apart naar de knop "wijzig leverancier" te zoeken.

<!-- bundel-08-09 blok 4 -->
- Tariefregels zonder bedrag (aantal 0, € 0) op een factuur worden niet meer als boekingsregel getoond — ze blijven wel zichtbaar in het gelezen voorstel.
- Staat er één projectnummer op de factuur, dan krijgen álle regels dat project voorgesteld, ook als het nummer maar op één regel staat.
- Zegt de factuur "btw verlegd" en staat er geen btw op, dan wordt de verlegd-btw-code voorgesteld (oranje, ter controle) in plaats van de standaard btw-code van de administratie.
- Controlescherm rustiger: uitlegchips passen op één regel (volledige tekst bij aanwijzen), kolommen voor grootboek en project zijn breder, en de melding over ontbrekende velden zegt "grootboek ontbreekt op alle 3 regels" in plaats van elke regel apart.
- "Verdelen over projecten…" verschijnt alleen nog als de factuur zelf geen projectnummer noemt.

<!-- bundel-08-09 blok 3 -->
- Afgehandelde documenten (samengevoegd, als duplicaat afgevoerd, verwijderd of afgewezen) staan niet meer tussen het werk en tellen niet mee in "Alle". Eén knop "Toon afgehandelde documenten (aantal)" laat ze grijs zien, met de reden en een link "→ samengevoegd in …" of "→ duplicaat van …" naar het echte document. Het menu op zo'n rij biedt alleen nog Openen en Toon origineel — verwijderen of boeken kan daar niet meer per ongeluk.
- Op het echte document zie je een label "2 exemplaren samengevoegd", zodat duidelijk is dat de dubbelen al verwerkt zijn. Het aantal afgewezen documenten blijft als knop zichtbaar; een klik toont ze.
- Kantoor: de factuurperiode (weeknummers) is voor alle al geboekte inkoopfacturen ingevuld (117 documenten), en de laatste als duplicaat afgevoerde documenten hebben nu overal dezelfde status "Afgevoerd als duplicaat".
- Een als duplicaat afgevoerd document telt niet meer mee als "Afgewezen — ter controle" en staat niet meer tussen de mogelijke duplicaten — het heeft nu een eigen, duidelijke status "Afgevoerd als duplicaat".
- Zo'n document blijft gewoon terugvindbaar: in het Archief/Zoeken (filter "Afgevoerd als duplicaat") en via de nieuwe knop "Toon afgevoerde documenten" in de documentenlijst. Terughalen kan nog steeds met één klik ("Terug naar werkvoorraad").
- Op het controlescherm van zo'n document staat nu duidelijk wie/wat het afvoerde, met reden en een link naar het origineel — bij een automatische afvoer staat er "automatisch (duplicaatregel)" in plaats van de verwarrende "onbekende medewerker".
- De Mogelijk-duplicaat-tab toont voortaan alleen nog rijen waarvan de tegenhanger nog echt bestaat (niet zelf al afgevoerd, afgewezen of verwijderd) — geen verouderde meldingen meer.

<!-- bundel-08-09 blok 2 -->
- Accordeur-app: als het aanmaken van een passkey op een iPhone of iPad niet lukt, zegt de app nu wat je kunt doen (iCloud-sleutelhanger aanzetten, toegangscode instellen) in plaats van een technische Apple-melding.
- Accordeur-app: de melding "Geen verbinding met de server" op het code-slot vertelt nu de oorzaak (geen antwoord binnen 10 seconden, netwerkfout, of een storing bij de server).
- Accordeur-app: Instellingen › Toegang › Diagnose toont ook de laatste verbindingsfout met tijdstip — handig om aan het kantoor te laten zien; blijft op je toestel.


## 2026-09-07 — Niets blijft stil liggen: automatisering wacht niet op instellingen, controlemail telt mee

### Automatisch, ook zonder eigenaar of behandelaar

- Een administratie zonder vaste eigenaar houdt niets meer tegen: automatisch afgevoerde dubbele facturen, automatische vragen en afwijzingen worden gewoon verwerkt en verschijnen kantoorbreed in de lijsten, met de vermelding "niet toegewezen".
- In Inzicht › Open vragen en in de werkvoorraad zie je nu expliciet "niet toegewezen" bij een vraag of afwijzing zonder behandelaar — zo valt er niets stil weg.
- Een automatische vraag zonder behandelaar kan door iedere collega met toegang tot die administratie worden afgehandeld.
- Bij het verplaatsen van een document naar een administratie zonder eigenaar blijft een open vraag zichtbaar voor het hele kantoor in plaats van ongemerkt bij de verplaatser te landen.

### Dagelijkse controlemail en Inzicht › Reconciliatie

- **De dagelijkse controlemail en het scherm Inzicht › Reconciliatie tonen nu per automatisering wat er de afgelopen dag gebeurde:** hoeveel er te doen was, hoeveel er automatisch is gedaan en hoeveel er is overgeslagen — met de reden erbij (bijvoorbeeld "harde checks blokkeren" of "volumerem bereikt"). Een automatisering die uit staat, staat er als één regel "uit" bij.
- **Wacht een automatisering op iets wat een mens moet instellen — een verlopen koppeling, een ontbrekende sleutel, een uitgezette boekknop — dan zie je dat als aandachtspunt mét een knop "Naar de instelling".** Zo blijft er niets stil liggen. Het aandachtspunt komt één keer in de mail, niet elke dag opnieuw.
- **Staat een automatisering aan maar deed ze zeven dagen niets terwijl er wel werk was, dan krijg je daar een aandachtspunt over.**

### Duplicaten en tegenboeken

- Een factuur die al als UBL + PDF gebundeld in de werkvoorraad staat, wordt niet meer voor de tweede keer aangeboden als hetzelfde PDF-bestand later nog eens los binnenkomt — dat exemplaar gaat automatisch naar het archief als duplicaat, met een verwijzing naar de gebundelde factuur. Een PDF met dezelfde naam maar andere inhoud blijft gewoon staan.
- Delen van een gesplitste factuur-PDF worden nooit onbedoeld als duplicaat van elkaar afgevoerd zolang hun factuurnummer en bedrag nog niet gelezen zijn.
- Op een administratie die in Odoo boekt gaven de controles een foutmelding als de leverancier nog niet aan een Odoo-relatie gekoppeld was. Dat is nu een duidelijke, blokkerende controle-uitkomst met wat je moet doen (leverancier in Odoo aanmaken en stamgegevens synchroniseren, of een gekoppelde leverancier kiezen).

- **Dubbel geboekt? Direct tegenboeken.** Staat een factuur per ongeluk twee keer geboekt, dan toont het controlescherm van beide exemplaren nu meteen de knop "Tegenboeken…" — ook als de btw-aangifte van die periode nog open staat. Het paneel laat zien van welke factuur (met boekstuknummer) het een dubbele is.
- **Geen stille "er gebeurt niets" meer vanuit het archief.** Kiest u in het archief "Tegenboeken…" bij een factuur waar dat niet aan de orde is, dan legt het scherm uit waarom en wat de route dan wél is.
- **Duplicaatcontrole tegen Reeleezee nog strenger op bedragen.** Bedragen worden nu op de cent exact vergeleken, zodat een afrondingsverschil in de koppeling nooit een bestaande factuur kan verbergen.
- **Omschrijving van de factuur komt aan in Reeleezee.** De automatische kop-omschrijving gaat nu mee in het veld dat Reeleezee daadwerkelijk bewaart (en wordt netjes afgekort als hij te lang is).

## 2026-09-07 — Duplicaten automatisch weg, omschrijving en project uit de factuur, herboeken beschermd tegen dubbele btw

### Duplicaten en dubbele exemplaren

- Dubbele facturen kunnen niet meer geboekt worden: naast de controle tegen Reeleezee kijkt de module nu ook in de eigen administratie — hetzelfde bestand, hetzelfde factuurnummer met hetzelfde bedrag, of dezelfde leverancier met hetzelfde factuurnummer blokkeert boeken tot het duplicaat is afgevoerd of door een medewerker mét reden als "geen duplicaat" is afgemeld.
- Duplicaten verdwijnen vanzelf uit de werkvoorraad: een tweede exemplaar (zelfde bestand, of zelfde factuurnummer + bedrag — ook met een andere schrijfwijze of een andere leverancierskaart) wordt direct afgevoerd met een verwijzing naar het origineel; een al geboekt exemplaar blijft altijd het origineel. Een UBL-bestand met zijn PDF is géén duplicaat.
- Afgevoerde duplicaten zijn terug te vinden in het Archief (kiezer "Tonen: Afgevoerd als duplicaat") en via Zoeken, met een link naar het origineel en de knop "Terug naar werkvoorraad".
- Dubbele exemplaren van dezelfde factuur uit één e-mail (letterlijk hetzelfde bestand, twee keer aangeleverd) worden bij het nabundelen automatisch samengevouwen: één exemplaar blijft het document, het andere staat als "Samengevoegd" mét verwijzing — niets wordt verwijderd en het is terug te draaien.
- Een afgewezen dubbel exemplaar telt niet meer mee als tegenhanger: afwijzen maakt het overgebleven UBL+PDF-paar alsnog eenduidig, zodat het systeem het kan samenvoegen.
- Universal Steigerbouw: 26 resterende UBL+PDF-paren van de mailreeks van 2 september zijn samengevoegd tot één document per factuur.

### Controlescherm: automatisch ingevuld, u corrigeert alleen

- Het controlescherm vult de omschrijving van de boeking nu automatisch: bij één boekingsregel de tekst van die regel, anders de betreft-regel van de factuur, en anders leverancier plus factuurnummer. Een klein label eronder laat zien waar de tekst vandaan komt.
- De omschrijving gaat mee naar de boekhouding (Reeleezee én Odoo), ook bij opnieuw boeken en tegenboeken.
- Typ je zelf een omschrijving, dan blijft die staan — ook na heropenen of een nieuwe uitlezing van de factuur. Veld leegmaken zet 'm weer op automatisch. Wijzigingen staan in de tijdlijn.
- Bij het uitlezen van een factuur leest het systeem nu ook de betreft-/onderwerpregel mee.
- Staat uw projectnummer op de inkoopfactuur (in de kop of per regel), dan vult het controlescherm het project nu zelf in — groen "uit factuur" als het nummer precies overeenkomt met een van uw projecten.
- Gebruikt een leverancier zijn eigen werknummer, dan is het voorstel de eerste keer oranje ("uit factuur, nog niet bevestigd"); boekt u de factuur met dat project, dan onthoudt de module de koppeling en is de volgende factuur van die leverancier direct groen.
- Past een nummer op meerdere projecten, dan wordt er niets ingevuld en ziet u welke projecten in aanmerking komen — u kiest zelf.
- Een nieuwe crediteur aanmaken in Reeleezee kan nu altijd met één klik in het controlescherm — de knop verdween voorheen als het crediteurveld al (automatisch) was ingevuld; die is nu ook zichtbaar in de crediteurenlijst zelf, als laatste keuze onderaan.
- Na het boeken (of afwijzen, of ter accordering aanbieden) van een document opent nu automatisch het eerstvolgende openstaande document zoals het in de lijst staat — niet meer altijd eerst hetzelfde documenttype.
- Een datum intypen en dan wegklikken of Tab drukken wist de invoer niet meer stil: een onvolledige of ongeldige datum blijft gewoon staan met een duidelijke melding erbij, en ook 7-9-2026, 7/9/2026 of 07.09.2026 worden nu herkend.
- Het controlescherm leest nu ook de periode van een inkoopfactuur voor (bijvoorbeeld "week 34-35" of "18 t/m 22 augustus") en zet die automatisch om naar weeknummers, met een label dat vertelt of dit van de factuur komt of uit de factuurdatum is afgeleid. Staat er niets op de factuur, dan geldt de week van de factuurdatum.
- Klopt de periode niet, dan past u die direct aan in het kopveld "Periode (weken)" — uw keuze wint en wordt nooit meer automatisch overschreven.
- Bij de urenmatch van een veldwerkersfactuur ziet u een oranje melding als de periode op de factuur niet overeenkomt met de weken van de goedgekeurde weekstaten; het blokkeert niets.

### Reconciliatie en crediteuren

- Opnieuw boeken van een document dat uit de boekhouding verdwenen is, wordt nu tegengehouden als de btw van dat document al in een ingediende btw-aangifte zat — anders zou de btw dubbel geclaimd worden. U ziet dan de melding "btw mogelijk al aangegeven — suppletie-pad".
- Alleen een Beheerder kan zo'n herboeking toch doorzetten, met een uitdrukkelijke bevestiging dat de btw niet in die aangifte zat en een verplichte reden; beide komen in de tijdlijn van het document.
- Reconciliatie van een administratie die van Reeleezee naar Odoo is overgestapt: facturen die vóór de overstap in Reeleezee zijn geboekt worden nu ook echt tegen Reeleezee gecontroleerd (met de bewaarde Reeleezee-login) in plaats van overgeslagen; facturen van ná de overstap tegen Odoo.
- De controleregel per administratie laat zien hoeveel facturen in Odoo en hoeveel in het Reeleezee-verleden zijn gecontroleerd.
- Is er geen bewaarde Reeleezee-login meer, dan verschijnt per factuur een zichtbare melding "Reeleezee-verleden niet controleerbaar" met wat je moet doen — niets wordt stil overgeslagen.
- Dubbele crediteuren met hetzelfde KvK-nummer worden nu automatisch samengevoegd, ook als de handelsnaam verschilt — één KvK-nummer is één bedrijf. Crediteuren die alleen een btw-nummer delen (fiscale eenheid) blijven ter beoordeling staan.
- De oude "archiveer in Reeleezee"-werklijst is eenmalig afgerond: de daar gekozen voorkeuren zijn omgezet in dezelfde markeringen als bij "Voorkeur kiezen…", op naam van degene die de keuze maakte, en zijn terug te draaien in Inzicht › Crediteuren onder "Afgehandeld".

### Goedkeur-app

- Goedkeur-app: onder "Toegang tot de app" staat nu een regel "Laatste koude start" met de starttijden en het versienummer van de app — start de app traag, stuur dan een screenshot of kopie naar het kantoor. De gegevens blijven op je toestel.
- Goedkeur-app (telefoon-app): het openen met een gesloten slot doet één verbinding minder, waardoor het ontgrendelscherm iets sneller verschijnt.
- Goedkeur-app op Android: lukt het aanmaken van de passkey niet omdat het toestel geen Google-account of schermvergrendeling heeft, dan zegt de app dat nu duidelijk en wat je eraan kunt doen.

## 2026-09-07 — Reconciliatie leesbaar en ook voor Odoo, duplicaten in bulk afvoeren, dubbele crediteuren automatisch, projecten in één overzicht

### Reconciliatie: verdwenen boekingen opnieuw boeken, ook voor Odoo-administraties

- **Verdwenen boeking? Opnieuw boeken met één klik.** Staat een factuur in de app als geboekt, maar kent Reeleezee (of Odoo) het stuk niet meer — bijvoorbeeld omdat het daar per ongeluk is verwijderd — dan meldt Inzicht › Reconciliatie dat nu als zwaarste afwijking, met leverancier en factuurnummer erbij. Op die regel staat de knop "Opnieuw boeken…": u geeft een reden, het document gaat terug naar "klaar om te boeken" met dezelfde gegevens en u boekt het daarna opnieuw op het controlescherm (alle controles draaien opnieuw). Er wordt niets tegengeboekt; reden en oude boekstuknummer staan in de tijdlijn.
- **Reconciliatie werkt ook voor administraties op Odoo.** De dagelijkse controle van geboekte documenten kijkt nu in het boekhoudpakket van de administratie zelf: in Odoo controleert ze of de factuur bestaat, geboekt is, hetzelfde totaal heeft en niet buiten de app om is teruggedraaid. Bank-, omzet- en doorbelastingscontroles blijven voor Reeleezee-administraties; bij een Odoo-administratie staan die zichtbaar als "niet van toepassing" in plaats van als fout.

### Reconciliatie leesbaar

- Inzicht › Reconciliatie leest nu als tekst voor mensen: elke bevinding heeft een korte titel met leverancier, factuurnummer, boekstuk of tegenpartij, één zin "wat is er" en één zin "wat doe je" — bedragen in euro-notatie, datums als dag-maand-jaar. Technische codes staan alleen nog in een uitklapbaar "details"-blokje.
- De dagelijkse reconciliatie-mail gebruikt dezelfde leesbare zinnen als het scherm; de technische sleutel staat er als aparte regel onder.
- Opgelost: een geaccepteerde afwijking bleef tot de volgende nachtelijke controle in "aandacht nodig" staan. Accepteren haalt de rij nu direct uit de lijst en de teller (en intrekken zet 'm direct terug).
- In de reconciliatielijst kun je nu ook zoeken op leverancier, factuurnummer of tegenpartij, en verdwenen boekstukken staan bovenaan tussen de afwijkingen.

### Controlescherm: vooringevulde waarden direct opgeslagen

- Het controlescherm meldt niet langer "grootboekrekening ontbreekt" terwijl het veld al uit het geheugen gevuld staat: de controle kijkt nu naar precies dezelfde vooringevulde waarden als u ziet.
- Vooringevulde waarden uit het geheugen, een leverancier-template of de standaard btw van de administratie worden bij het openen direct opgeslagen — u hoeft niets meer aan te raken voordat "Doorbelasten na boeken" de regels ziet. De herkomst-labels blijven staan tot u een waarde wijzigt.
- Uw eigen keuzes winnen altijd: iets wat u al heeft aangepast wordt nooit door de automatische voorinvulling overschreven; opnieuw uitlezen van een nog onaangeraakt document vult de nieuwe waarden gewoon opnieuw in.
- In de tijdlijn van het document ziet u wanneer en waaruit het voorstel automatisch is vooringevuld.

### Duplicaten in bulk afvoeren

- **Duplicaten in één keer afvoeren.** Op het filter "Mogelijk duplicaat" van de documentenlijst staat nu een selectievakje per rij en een knop "Afvoeren als duplicaat (aantal)". Vink de rijen aan (of alles in één keer, ook wat door je zoekterm verborgen is), bevestig het aantal in het venster, en de gekozen facturen gaan als duplicaat naar Afgewezen — elk met een verwijzing naar het origineel, precies zoals de losse actie in het rijmenu.
- Wat niet kan (bijvoorbeeld een al geboekte factuur of een rij zonder echte match) wordt niet stil overgeslagen: je ziet na afloop per document waarom. Terughalen kan per document via Heropenen.
- Dit is een handeling van jou en telt daarom niet mee in de dagelijkse rem op het automatisch afvoeren van duplicaten.

### Dubbele crediteuren

- Dubbele crediteuren die duidelijk dezelfde zijn (zelfde naam of hetzelfde rekeningnummer, geen tegenstrijdig KvK- of btw-nummer, nauwelijks boekingen op de dubbel) handelt het systeem nu zelf af — u ziet vooraf per administratie wat er gebeurt en alleen twijfelgevallen vragen nog uw keuze.
- Een afgehandelde dubbel wordt nergens in de module meer voorgesteld of gekozen: boekingsgeheugen, btw-/KvK-kenmerk en vertrouwde rekeningnummers gaan naar de voorkeurscrediteur, ook op nog openstaande facturen.
- Elke afhandeling is terug te draaien (met reden) via ⋯ › Afgehandeld; in Reeleezee verandert er niets en er wordt niets verwijderd.
- De lijst "archiveer in Reeleezee" vraagt niet meer om aandacht: wie wil opruimen, downloadt hem als bestand via ⋯ › Exporteer RLZ-opruimlijst.

### Verzamelbak en veldwerkers

- Verzamelbak "Niet toegewezen": bij twijfel "factuur of offerte?" kies je nu met twee compacte knopjes (Factuur | Offerte) direct onder de twijfelmelding; de administratie-kiezer en de actieknoppen staan weer netjes in hun eigen kolom en elke rij heeft dezelfde hoogte — ook bij een lange tenaamstelling.
- Veldwerkers (Gebruikers & toegang): het dossier en "crediteur koppelen" openen direct met de juiste administratie voorgeselecteerd — de enige in je scope, anders die van de recentste planning of koppeling, anders de administratie met uren & meerwerk. Wisselen blijft mogelijk via de kiezer.

### Projecten in één overzicht

- **Projecten in één overzicht** — onder Inzicht staat nu "Projecten": alle lopende projecten van al je administraties in één lijst, met per project de stand van het resultaat, de offertes, de weekstaten en de gebouwde m². Projecten met een signaal (offerte overschreden, negatieve marge, ontbrekende weekstaat) staan bovenaan; filteren kan op administratie en status, zoeken op project, opdrachtgever of werknummer.
- **Sneller naar de projecten van een klant** — op de documentenlijst van een klant staat een chip "Projecten" die direct naar de projectenlijst van die administratie gaat.
- **Projectdetail toont nu de offertes en de weekstaten** — per project zie je de goedgekeurde offertes met een verbruiksbalk (hoeveel van het offertebedrag al geboekt is) en per week wat er gepland, ingediend en gekeurd is, met een link naar de planning van die week.

### Projectverdeling over een heel jaar

- Projectverdeling pro rato omzet kan nu ook over een heel jaar: naast de laatste twaalf maanden kies je "omzet <dit jaar> (t/m de laatste afgesloten maand)" of "omzet <vorig jaar>". De verdeling volgt dan de omzet per project over de afgesloten maanden van dat jaar, met dezelfde uitsluitingen als bij een maand.
- Bij het boeken wordt de jaarstand vastgelegd mét de dekking van dat moment (bijvoorbeeld "2026 (t/m juli)"); de maandelijkse hercontrole rekent tegen de actuele jaarstand, zodat een verschuiving boven de drempel gewoon als signaal mét "Herverdelen…" verschijnt.
- Een jaar in de toekomst of een jaar zonder afgesloten maand kun je niet kiezen; de melding zegt wat wél kan.

### Contract ontleden vult direct in

- Contract ontleden vult de projectgegevens nu direct in: soort werk, contract-m², looptijd, opdrachtgever, werknummer, doorlopende huur en de verrekenstaffels staan meteen in het project met het label "uit contract" — bevestigen per regel is niet meer nodig.
- Staat iets niet in het contract, dan zie je dat als uitkomst ("niet in contract aangetroffen"); wat niet eenduidig te plaatsen is (bijvoorbeeld een onbekende eenheid) wordt gemeld en niet ingevuld.
- Corrigeer je een ingevuld veld of staffelregel, dan wordt die "handmatig" en laat een nieuwe ontleding hem met rust; elke ontleding en correctie staat in het logboek.
- Doorlopende huur wordt waar mogelijk uit de huurstaffel afgeleid ("€ 150 per week uitgaande van 9 weken" wordt "vanaf week 10"). De prijs bij meerwerk blijft altijd een keuze van een medewerker; de staffel is alleen het voorstel.

### KvK-controle

- De KvK-controle in het ZZP-dossier en bij crediteuren werkt nu op echte KvK-nummers: bedrijfsnaam, rechtsvorm en vestigingsplaats komen uit het officiële Handelsregister in plaats van de KvK-testomgeving (die bij echte nummers altijd "niet gevonden" gaf).

## 2026-09-06 — Mini-voorraad, ontbrekende weekstaten, projectverdeling-overzicht en een snellere app

### Mini-voorraad speciale producten

- **Speciale producten ontstaan vanzelf bij het boeken.** Zet de Beheerder "Mini-voorraad speciale producten" aan voor een administratie (Instellingen › Administraties › administratie), dan worden bij het boeken van een inkoopfactuur de productregels — omschrijving × aantal — automatisch producten in de materiaalcatalogus, met de factuur als herkomst. Een omschrijving die het systeem al kent van die leverancier (op artikelcode of exact dezelfde tekst) wordt bijgeteld; een onbekende wordt een nieuw product met de oranje vlag "nieuw — controleer naam". Dienst- en transportregels tellen niet mee. Wordt de factuur later teruggeboekt, dan draait de voorraad automatisch mee terug.
- **Nieuwe tab "Mini-voorraad" in de materiaalcatalogus.** Eén overzicht over de volle breedte: product (met leverancier en code), de actuele stand en per regel de handelingen: "Naam bevestigen" (alleen bij de vlag — kiest de weergavenaam; de factuurtekst blijft bewaard als sleutel), "Voorraadlog ▸" en een ⋯-menu. Bovenaan ziet u hoeveel producten nog gecontroleerd moeten worden; met het filter en het zoekveld vindt u ze snel terug.
- **Voorraadlog per product.** Klik "Voorraadlog ▸" en u ziet elke mutatie op datum met het aantal (+ of −), de soort (instroom, storno, uitstroom, beschadiging), een link naar de bijbehorende factuur op het controlescherm, het project en — bij een melding — wie het meldde. Het log is alleen-lezen en volledig: de stand is niets anders dan de optelsom ervan.
- **Niemand kan standen corrigeren.** Er is bewust geen knop om aantallen aan te passen of producten samen te voegen. De enige menselijke ingang is "Beschadiging melden…" in het ⋯-menu: u vult het aantal in, kiest verplicht het project waar het gebeurde en eventueel een toelichting; de melding komt met uw naam en datum in het voorraadlog. Telverschillen blijven zichtbaar in de voorraad-aansluiting en worden niet "weggewerkt".
- **Archiveren in plaats van verwijderen.** De Beheerder kan een product met een reden archiveren (⋯-menu); stand en log blijven bewaard en komt het product opnieuw op een factuur voor, dan is het automatisch weer actief.
- **Zichtbaar op het controlescherm.** Direct ná het boeken verschijnt de melding "Mini-voorraad bijgewerkt — N regels", met de nieuwe producten bij naam; in de tijdlijn van het document staat dezelfde regel (en bij tegenboeken de regel "Mini-voorraad teruggedraaid").
- **Ook in planning en aansluiting.** De Materiaallijst bij een transport toont de speciale producten met hun stand in een eigen, alleen-lezen blok; de voorraad-aansluiting toont ze als groep "Speciale producten (mini-voorraad)" met de chip "mini-voorraad" — informatief, zonder telling.

### Geplande weken zonder weekstaat

- **Nieuw scherm "Weekstaten ontbreken".** De app van de veldwerkers toont geplande weken tot zes weken terug. Stond iemand ingepland maar is voor die week geen weekstaat ingediend, dan viel die week daarna uit beeld. Het kantoor ziet zulke weken nu in één lijst over al uw administraties met uren & meerwerk: de oudste week bovenaan, per regel de veldwerker, het project, het aantal geplande dagen en of er helemaal geen weekstaat is of alleen een niet-ingediend concept. Filteren op administratie kan, verplicht is het niet.
- **Per regel één handeling.** Met "Herinnering sturen" krijgt de veldwerker een bericht in de app (of per e-mail als hij geen meldingen heeft) en komt de week weer in zijn lijst te staan tot hij is ingediend; per week hooguit één herinnering per dag, en u ziet hoe vaak en wanneer er al herinnerd is. Hoefde er voor die week niets te komen (bijvoorbeeld ziek gemeld), dan meldt u het signaal af met een reden; het blijft terugvindbaar onder "afgemeld" en is met "Toch tonen" weer terug te halen. Alles wordt vastgelegd. Niets blokkeert.
- **Teller op de werkvoorraad.** Zodra er ergens zo'n week openstaat, verschijnt de kaart "Weekstaten ontbreken" bovenaan de werkvoorraad en een kolom met hetzelfde aantal in het overzicht per klant; klik erop voor de lijst. Is alles ingediend of afgemeld, dan ziet u ze niet.

### Inzicht › Projectverdeling

- **Nieuw scherm Inzicht › Projectverdeling.** Alle geboekte facturen waarvan de verdeling over projecten (naar rato van de omzet) ná het boeken is gaan afwijken — omdat er in die maand nog omzet bijkwam of wegviel — staan nu in één lijst over al uw administraties, de grootste afwijking bovenaan. Per regel ziet u de leverancier, het factuurnummer en -bedrag, de administratie, hoeveel procent de verdeling afwijkt en welke projecten verschuiven (oud → nieuw). U filtert op administratie of zoekt op leverancier of factuurnummer; het filter blijft staan als u doorbladert of terugkomt.
- **Herverdelen vanuit de lijst.** Met "Herverdelen…" opent dezelfde dialoog als op het controlescherm: de oude en nieuwe verdeling per project naast elkaar en een reden (vooringevuld). Bevestigen boekt de factuur tegen en zet 'm terug op "te controleren" mét de nieuwe verdeling als voorstel; u boekt daarna opnieuw. Met "Naar het document →" springt u direct naar de factuur.
- **Teller op de werkvoorraad.** Zodra er zo'n afwijking is, verschijnt bovenaan de werkvoorraad de kaart "Projectverdeling" met het aantal en over hoeveel administraties; klik erop voor de lijst. Zonder afwijkingen ziet u de kaart niet.

### Transport-tab

- **Transport-tab: leveranciers en catalogus weer zichtbaar voor iedereen die mag plannen.** Medewerkers met het recht "Meerwerk & urenstaten" zien op de Transport-tab weer de leveranciers en de materiaalcatalogus, zodat plannen vanuit het werkbakje, de materiaallijst definitief maken en bestelregels invullen gewoon werken. De catalogus is voor hen alleen-lezen; leveranciers en producten beheren blijft voorbehouden aan Beheerder en Boekhouding + Projecten.
- **Een laadfout is nu een echte melding.** Konden de leveranciers of de catalogus niet worden geladen (bijvoorbeeld door ontbrekende rechten), dan stond er eerder ten onrechte "Nog geen leveranciers". Nu ziet u een rode melding met de werkelijke reden — op de Transport-tab, in de materiaallijst en bij Instellingen › Materiaalcatalogus.

### Accordeur-app

- **De goedkeur-app opent sneller: uw laatste stand staat er direct.** Bij het openen ziet u meteen de administraties en facturen zoals die er bij uw vorige bezoek stonden, met een klein regeltje "stand van 08:15 · verversen…". Op de achtergrond haalt de app ondertussen de actuele stand op; die vervangt het beeld geruisloos en het regeltje wordt "laatst ververst 08:16" — precies zoals u dat van het bankscherm kent. Goedkeuren of afwijzen kan pas zodra de actuele stand er is (de knoppen tonen tot dan heel even "verversen…"): een besluit gaat altijd over de echte, actuele stand, nooit over een oud beeld. Bij uitloggen of een ingetrokken toestel wordt die bewaarde stand gewist; wat u ziet is altijd alleen uw eigen stand.
- **Minder wachten bij het laden.** De facturen en de vragen van het kantoor worden nu tegelijk opgehaald in plaats van na elkaar, en als u de app ontgrendelt, wordt de stand al vast klaargezet terwijl u dat doet.
- **Opent u de app vóór u geactiveerd bent, dan loopt u niet meer vast op het inlogscherm.** Lukt inloggen niet, dan legt de app uit wat er waarschijnlijk aan de hand is en wat u kunt doen: open de uitnodigingslink uit de e-mail van het kantoor op dít toestel — de app gaat dan vanzelf naar de activatie. Op de telefoon staan er twee knoppen bij: "Mail-app openen" en "Link plakken" (plak de link uit de e-mail en u komt direct in de activatie). Geen e-mail meer? Het kantoor stuurt met "Opnieuw mailen" een nieuwe uitnodiging; de oude link vervalt dan.
- **De uitnodigingslink opent de app weer echt.** In de app-versie ontbrak een onderdeel waardoor een aangetikte uitnodigingslink de app wel opende, maar niet naar de activatie ging (dat was de oorzaak van het vastlopen). Dat is hersteld en komt mee met de volgende app-update in de App Store en Google Play.

## 2026-09-06 — Dagelijkse controle tegen Reeleezee meldt zichzelf en staat in de app

- **U hoeft de dagelijkse controle niet meer zelf te draaien.** Elke ochtend vergelijkt het systeem de eigen boekingen, bankboekingen, omzetboekingen en doorbelastingen met de werkelijke stand in Reeleezee. De uitkomst wordt nu bewaard, en u krijgt alleen een e-mail als er iets nieuws is: een nieuwe afwijking, een nieuw aandachtspunt (bijvoorbeeld een concept dat na een storno in Reeleezee is blijven staan), iets dat nieuw als "beoordeeld" is gemarkeerd, een onderdeel dat niet gecontroleerd kon worden, of juist een afwijking die is opgelost. Staat alles gelijk aan gisteren, dan komt er geen mail. In de mail staat per onderdeel de stand, per bevinding de administratie bij naam en in één zin wat u ermee kunt doen.
- **Nieuw scherm Inzicht › Reconciliatie.** Alle bevindingen van de laatste controle over al uw administraties in één lijst, de dringendste bovenaan, met filters op administratie en soort en een zoekveld. Per regel staat de handeling erbij: een afwijking kunt u (als Beheerder) met een reden als "beoordeeld en blijvend" accepteren of die acceptatie weer intrekken; een achtergebleven Reeleezee-concept kunt u met een reden op "Gezien" zetten zodat het uit de teller en de mail verdwijnt (het komt na 90 dagen — of zodra de situatie verandert — vanzelf terug; de Beheerder kan die termijn aanpassen) en u springt met één klik naar de bijbehorende doorbelasting. Opruimen van zo'n concept blijft handwerk in Reeleezee — de app verwijdert daar nooit iets.
- **Teller op de werkvoorraad.** Zodra er iets openstaat, verschijnt de kaart "Reconciliatie" bovenaan de werkvoorraad met het aantal en het tijdstip van de laatste controle; klik erop voor de lijst. Is alles schoon, dan ziet u de kaart niet.
- **"Nu draaien".** De Beheerder kan de controle direct starten vanuit het scherm en ziet de voortgang en het resultaat; de nachtelijke ronde blijft gewoon doorgaan.
- **Duidelijker opruimlijst.** Een Reeleezee-concept dat via meerdere gestorneerde boekingen op dezelfde factuur werd gevonden, stond meerdere keren in de lijst; het staat nu één keer, met alle bijbehorende verkoopnummers erbij.

## 2026-09-04 — Odoo-overstap afgerond: nakomers boeken gewoon, projecten gaan mee, openstaande facturen vertaald

- **De overgangsdatum blokkeert niets meer.** Een factuur die ná de overstap binnenkomt maar een factuurdatum van vóór de overstap heeft, wordt gewoon in Odoo geboekt. Stond diezelfde factuur al in Reeleezee geboekt, dan ziet u dat direct: de duplicaatcontrole wordt rood mét het Reeleezee-boekstuknummer en het systeem voert de dubbele factuur automatisch af als duplicaat, met verwijzing naar het origineel. De datum heet nu "Overgangsdatum (kanteldatum)": hij zegt vanaf wanneer de administratie op Odoo werkt en kan altijd worden gewijzigd — de eerdere weigering bij het verschuiven is vervallen.
- **Boeken in een periode die in Odoo al is afgesloten.** Valt de factuurdatum in een periode waarvan de btw-aangifte al is gedaan, dan boekt de app op de eerste dag van de eerstvolgende open periode; de factuurdatum blijft de factuurdatum. U ziet dat als chip "boekdatum verschoven" bij "Geboekt in Odoo" en als regel in de tijdlijn met beide datums — er verschuift niets stil.
- **Projecten gaan mee bij de overstap.** In de stap "Rekeningen koppelen" staat nu ook een blok Projecten met de projecten die in gebruik zijn (geheugen, open facturen en open projectverdelingen). Per project een voorstel: groen als het projectnummer overeenkomt met een Odoo-project, oranje "bevestig" als alleen de naam overeenkomt, en anders kiest u zelf, laat u het project in Odoo aanmaken (bij een projectnummer; bestaat het al, dan wordt dát gekoppeld — nooit dubbel) of laat u de rij leeg. Projecten houden het opslaan nooit tegen. Na de overstap ziet u hoeveel projecten zijn aangemaakt en welke niet konden, met reden. Zo blijft het geheugen ná de overstap ook projecten voorstellen; corrigeren kan achteraf per project via "Mapping bekijken/corrigeren…".
- **Openstaande facturen bij de overstap.** Facturen die op dat moment nog in de werkvoorraad staan, krijgen hun grootboekrekening, btw-code en project automatisch omgezet naar de Odoo-tegenhangers uit de bevestigde koppeltabel. Per veld staat een oranje chip "vertaald bij overstap" met de vertaling in de tooltip; is er geen tegenhanger, dan is het veld leeg met een rode chip "niet vertaalbaar bij overstap — kies". Zodra u het veld zelf aanraakt, is het uw keuze en verdwijnt de chip. Het resultaatscherm van de overstap noemt hoeveel facturen en regels zijn omgezet.
- **Materiaalcatalogus: lezen en beheren volgen dezelfde rechten.** De leveranciers- en productenlijsten zijn zichtbaar voor precies de medewerkers die ze mogen beheren (Beheerder en Boekhouding + Projecten). Wie de catalogus mocht bewerken maar de lijst niet kon zien, ziet 'm nu wél; het losse recht "Meerwerk & urenstaten" geeft geen toegang meer tot de catalogus zelf. Bestellingen, transport en de materiaalstand werken zoals voorheen.

## 2026-09-04 — Overstap naar Odoo behoudt het boekingsgeheugen; materiaalcatalogus ook voor Odoo-administraties

- **Overstap naar Odoo behoudt het boekingsgeheugen.** Stapt een administratie over van Reeleezee naar Odoo, dan krijgt de Beheerder in de wizard een tabel met álle grootboekrekeningen en btw-codes die de administratie nog gebruikt (uit het geheugen en uit facturen die nog openstaan), met per rij een voorstel voor de Odoo-tegenhanger: groen bij een exact gelijke rekeningcode, oranje "bevestig" als alleen de code met twee nullen erachter overeenkomt (4808 → 480800) of hetzelfde btw-tarief gevonden is, en "kies" als het systeem het niet zeker weet. Een teller bovenaan toont hoeveel er nog open staan; met "alleen nog te kiezen" filter je op die rijen. De overstap gaat pas door als élke rij een keuze heeft — niets wordt stil gegokt. Is er niets te vertalen (nieuwe administratie zonder verleden), dan zegt de wizard dat en kun je direct door.
- **Voorstellen en automatisch boeken werken direct door in Odoo.** Alles wat het systeem van een leverancier had geleerd (welke rekening, welke btw-code) wordt na de overstap automatisch vertaald naar de Odoo-rekeningen die u bevestigde. Eerder door een mens bevestigde keuzes blijven bevestigd, dus ook automatisch boeken loopt gewoon door.
- **Mapping later corrigeren.** Op de administratie-pagina staat onder Boekhoud-backend de regel "Rekening-mapping" met de telling en wie 'm wanneer bevestigde, plus "Mapping bekijken/corrigeren…" om een rij later aan te passen. Elke wijziging wordt als nieuwe versie bewaard (zichtbaar als "v2") en vastgelegd in het logboek; eerder geboekte documenten veranderen niet.
- **Overgangsdatum veilig verschuiven.** Achter "overgestapt per …" staat nu "Overgangsdatum wijzigen…". Staat er al een factuur in Odoo geboekt met een eerdere factuurdatum, dan weigert het systeem de nieuwe datum en noemt het oudste boekstuk en de datum tot waar het wél kan — een boeking kan nooit "tussen twee pakketten" vallen.
- **Materiaalcatalogus ook voor Odoo-administraties.** De catalogus met leveranciers, categorieën en producten is nu beschikbaar zodra een administratie Uren & meerwerk aan heeft óf een Odoo-koppeling heeft — de steigerbouw-schakelaar hoeft daarvoor niet meer aan. Zo kan de productkoppeling naar Odoo (boeken op producten) ook worden gelegd voor administraties zonder weekstaten en planning. Bestellingen, transport en de materiaalstand blijven onderdeel van Uren & meerwerk. Op de administratie-pagina staat bij een Odoo-administratie zonder Uren & meerwerk een directe link naar de catalogus; de administratie-keuze op de catalogus-pagina toont deze administraties mee.
- **Universal Verkoop leest zijn verkoopfacturen nu uit Odoo.** Vanaf 1 september 2026 komen de verkoopregels van Universal Verkoop voor de voorraad-aansluiting uit Odoo (herkenbaar aan "Odoo-verkoopfactuur F/2026/…"); oudere facturen blijven uit Reeleezee komen en niets telt dubbel.

## 2026-09-04 — Open facturen zichtbaar op de offerte en projecten aanmaken vanuit de planning

- **Onder de verbruiksbalk van een goedgekeurde offerte zie je nu ook wat er nog aankomt.** Staan er facturen op die offerte die al wel herkend maar nog niet geboekt zijn, dan staat er één regel onder de balk: "2 open facturen op deze offerte (€ 8.300) — nog niet geboekt, telt niet mee". Zo zie je vooraf of de offerte straks vol raakt. De balk zelf blijft wat hij was: alleen geboekte facturen tellen als verbruik. Je vindt de regel op het offertescherm en in Inzicht › Verplichtingen.
- **"+ Project aanmaken" in de planning mag nu iedereen op kantoor, ook met de rol Boekhouding.** Dezelfde regel als bij het aanmaken vanuit de projectkeuze op het controlescherm. Projectgegevens wijzigen blijft voorbehouden aan Beheerder en Boekhouding+Projecten.

## 2026-09-04 — Offertes laten goedkeuren en elke factuur automatisch tegen de offerte gelegd

- **Offertes, prijsopgaven en opdrachtbevestigingen laat je nu goedkeuren, net als facturen.** Zo'n document komt binnen op een eigen tabblad in de werkvoorraad: je controleert leverancier, project, bedrag excl. btw en de geldigheid — met dezelfde chips die laten zien wat er automatisch is gelezen — en stuurt het daarna met één knop naar de accordeur van de klant. Er wordt niets geboekt: wat wordt vastgelegd is wíé op welke datum welk bedrag heeft goedgekeurd. Twijfelt de verwerking of iets een factuur of een offerte is, dan kies je dat zelf bij het toewijzen — het wordt nooit stil als factuur behandeld.
- **De accordeur ziet een offerte als een aparte kaart, met het werk en het bedrag.** Op de kaart staan het soort (offerte, prijsopgave of opdrachtbevestiging), de leverancier, het werk, het project, tot wanneer het geldig is en het bedrag exclusief btw. Goedkeuren of afwijzen gaat met dezelfde twee knoppen als bij een factuur.
- **Elke factuur wordt daarna automatisch tegen de goedgekeurde offerte gelegd — cumulatief.** Past de factuur binnen het goedgekeurde bedrag, dan zie je een groene melding met een balkje: "verbruik ná deze factuur € 27.150 van € 48.500". Komt het totaal erboven, of is er geen goedgekeurde offerte voor deze leverancier en dit project, dan is het een oranje melding met precies het bedrag dat eroverheen gaat. Boeken kan altijd nog: het is een signaal, geen blokkade. En de melding zegt ook wat je ermee doet — meerwerk rekt een offerte niet op, dat hoort een eigen offerte te krijgen.
- **Pakte de match de verkeerde offerte, of géén? Dan koppel je hem zelf, één keer.** Met "Koppel offerte…" kies je uit de lopende goedgekeurde offertes van die leverancier; die keuze wordt onthouden voor volgende facturen. Ontkoppelen zet de automatische match weer terug.
- **De klant-accordeur krijgt de melding ook te zien, met het vinkje "Conform offerte" al aangezet.** Het vinkje is een samenvatting van de controle — het akkoord geeft de accordeur nog altijd zelf, met de knop.
- **Nieuw overzicht: Inzicht › Verplichtingen.** Alle goedgekeurde offertes over al je administraties op één lijst, met de verbruiksstand: wat is er al aan facturen tegen weggeboekt en hoeveel ruimte is er nog. Wat eroverheen gaat staat bovenaan, met het bedrag erover. Per rij klap je de gekoppelde facturen uit, open je de offerte, of laat je hem vervallen als de opdracht niet doorgaat — met een reden, en zonder dat de facturen die er al aan hangen veranderen.
- **In de werkvoorraad zie je in één oogopslag wat buiten een offerte valt.** Bij de klant staat een teller "Buiten offerte", en op de documentenlijst een filter en een chip per regel — hetzelfde patroon als bij mogelijke duplicaten.

## 2026-09-04 — Keuzekaarten in de wizard, factuurbeeld op volle breedte en projecten aanmaken vanuit de regel

- **De keuze tussen Reeleezee en Odoo staat nu op twee klikbare kaarten.** Bij het toevoegen van een administratie (en bij het koppelen van Odoo aan een bestaande) kies je het pakket door op de kaart te klikken; de gekozen kaart licht op. Ook alle andere keuzerondjes in de app staan weer netjes op hun eigen formaat.
- **Het factuurbeeld opent meteen op volle breedte, zonder de strook met paginaminiaturen ernaast.** Je ziet de factuur nu direct zo groot mogelijk in het paneel. Heb je de miniaturen toch nodig, dan zet je ze met het menuknopje in de PDF-balk zelf weer aan.
- **Een project dat nog niet bestaat, maak je nu aan zonder het controlescherm te verlaten.** Onderaan de projectkeuze staat "+ Nieuw project aanmaken…": je vult nummer, plaats en opdrachtgever in, en het nieuwe project staat direct in de regel waar je mee bezig was. Dit mag vanaf nu iedereen op kantoor, ook met de rol Boekhouding — het aanpassen van projectgegevens blijft voorbehouden aan Beheerder en Boekhouding+Projecten.

## 2026-09-04 — Duplicaten standaard automatisch afgevoerd, ook bij de klant of met een open vraag

- **Duplicaten automatisch afvoeren staat nu voor alle administraties aan.** De schakelaar per administratie is weg. Een harde duplicaat (zelfde leverancier, factuurnummer én bedrag, origineel al geboekt of ouder in de werkvoorraad) gaat vanzelf naar Afgewezen met een link naar het origineel. Er verdwijnt niets; Heropenen haalt de kopie terug. Blijkt het mis te gaan, dan zet een beheerder de noodrem om op Instellingen › Boeken platformbreed ("Duplicaten automatisch afvoeren" uit) — dan blijven duplicaten overal als signaal staan en werkt alleen nog de knop "Afvoeren als duplicaat".
- **Ook een duplicaat dat bij de klant ligt of een open vraag heeft, wordt afgevoerd.** Ligt de kopie ter accordering, dan wordt die ronde beëindigd met de reden "afgevoerd als duplicaat van …"; de klant hoeft er niets meer mee te doen. Staat er een open vraag op de kopie, dan sluit die met dezelfde reden en zie je dat als laatste bericht in de vraag. Alleen een factuur waarvan de boeking al is gestart (of die al geboekt is) wordt nooit automatisch afgevoerd. Alles staat in de tijdlijn en het logboek.
- **De btw-standaard vult geen bewust leeg gelaten veld meer.** Laat de scan het btw-veld van een regel leeg omdat het onduidelijk is (0 % kan verlegd, vrijgesteld of nul-tarief zijn, of het bedrag past op geen enkele code), dan blijft die regel leeg en kies je zelf. De standaard-btw van de administratie vult alleen nog regels waarvoor de scan én het leveranciersgeheugen niets hadden.

## 2026-09-04 — Nieuwe gebruiker krijgt altijd de rol van de tab

- **"+ Veldwerker uitnodigen" maakt weer een veldwerker aan.** Op de pagina Gebruikers & toegang kon de knop op de tab Veldwerkers een kantoormedewerker aanmaken, omdat de rol uit een eerder geopende dialoog bleef staan. De dialoog start nu bij elke tab opnieuw met de juiste rolgroep en toont die expliciet bovenaan ("Rolgroep: Veldwerker …", "Kantoormedewerker …", "Klant-accordeur"). Ook de server weigert sindsdien een rol die niet bij de gebruikte tab past, en legt in het logboek vast vanaf welke tab of knop een account is aangemaakt.
- **Al fout aangemaakte accounts herstel je door te archiveren en opnieuw aan te maken.** Een rol wijzigen bestaat bewust niet. Archiveer het verkeerde account (🗑), wijzig zo nodig eerst het e-mailadres van dat account, en maak de veldwerker opnieuw aan via de tab Veldwerkers.

## 2026-09-04 — Controles volgen de opgeslagen projectverdeling direct

- **De controles zien je verdeling meteen.** Sloeg je een projectverdeling op, dan bleven "Verplichte velden" en "Projectverdeling" tot nu toe op de oude stand staan tot je iets in het boekvoorstel wijzigde. Nu draaien de controles direct opnieuw zodra de verdeling is opgeslagen — een geldige verdeling maakt beide controles groen, ook zonder dat de leverancier op "vooringevuld" staat.
- **De controle "Projectverdeling" vat samen wat er staat.** Bij een geldige verdeling lees je bijvoorbeeld "Verdeeld: € 630,00 over 8 projecten, pro rato omzet augustus 2026". Sluit de verdeling niet, dan blijft de controle rood met de reden. Ontbreekt een verdeling terwijl er regels zonder project zijn, dan zegt de controle dat ook (oranje) in plaats van "niet van toepassing".
- **Alleen een complete verdeling telt als dekking.** Een half ingevulde verdeling (restant nog niet verdeeld) maakt de projectplicht per regel niet groen; de melding blijft je naar "Verdelen over projecten…" wijzen. De regel onder de boekingsregels zegt bij een geldige verdeling "gedekt door de projectverdeling ✓" in plaats van de actie aan te bieden.

## 2026-09-04 — Verdelen over projecten op elke inkoopfactuur

- **Een factuur zonder eenduidig project kun je altijd verdelen.** Op elk inkoopdocument van een administratie met projectplicht (of met actieve projecten) staat het blok "Projectverdeling" klaar: een deel vast op een project en/of de rest pro rato de omzet van de vorige maand. Dat werkte al voor leveranciers met de instelling aan; nu is het blok op élke factuur bruikbaar, ook als het leeg begint.
- **De lege project-kolom wijst je de weg.** Staan er regels zonder project, dan zie je onder de boekingsregels "N regels zonder project — kies per regel een project óf Verdelen over projecten…". Eén klik opent het verdeelblok en zet het in beeld. Eén project blijft gewoon de kolom invullen; het blok is er voor de gevallen met meerdere projecten.
- **De controle "Project verplicht" zegt nu wat je kunt doen.** Ontbreekt een project op een regel, dan noemt de melding beide routes: een project per regel kiezen of het bedrag verdelen. Zodra elke regel via de kolom óf via de verdeling een project heeft, is de controle groen.
- **De instelling per leverancier is alleen nog een vooringevuld voorstel.** "Vooringevuld: pro rato omzet" aan betekent dat facturen van die leverancier met de verdeling klaarstaan; uit betekent een leeg maar bruikbaar blok. De maandelijkse hercontrole en het signaal "verdeling wijkt x% af" zijn ongewijzigd.

## 2026-09-04 — Uren-app: je planning bepaalt wat je ziet

- **Weken in plaats van projecten als startpunt.** De uren-app (ZZP'er én detacheerder-namens) opent nu met je weken: deze week plus de weken waarin je ingepland staat. Een oudere week met een half ingevulde of afgekeurde staat blijft staan tot hij is afgehandeld; de rest van de historie staat onder "Ingediend".
- **Per week alleen de projecten waar je die week gepland bent.** Open een week en je ziet precies de projecten uit de planning van het kantoor, met het aantal geplande dagen en wat er nog te doen is. Werkte je ergens anders? Kies "+ ander project": de volledige lijst, doorzoekbaar op nummer, plaats of opdrachtgever. Die uren blijven gewoon invoerbaar en krijgen bij de keuring de markering "buiten planning" (oranje, nooit een blokkade).
- **Werklijst detacheerder toont alleen wie nog iets te doen heeft.** Een ZZP'er verdwijnt uit de lijst zodra alle geplande weken zijn ingevuld of ingediend en er geen afgekeurde staat meer wacht. Is er voor niemand iets te doen, dan zie je "✓ Alles is bij" met een verversknop. Wie bij is blijft bereikbaar onder "Ook zonder werk", zodat je ook voor hem uren buiten de planning kunt invullen.
- **Projecttoegang volgt de planning.** Het kantoor koppelt ZZP'ers en uitvoerders niet meer met de hand aan projecten: de toegang ontstaat vanzelf zodra iemand wordt ingepland (of uren buiten de planning invult via "+ ander project"). Op de pagina Gebruikers & toegang zie je per veldwerker "actief op N projecten (via planning)" met een uitklap per project. Bestaande koppelingen blijven staan; rechten en scope zijn niet gewijzigd.

## 2026-09-04 — Duplicaten automatisch afgevoerd, slimmer splitsen, projectverdeling pro rato, grootboek per regel, btw-standaard en kortingsregels

- **Duplicaten verdwijnen automatisch uit je werklijst (per administratie aan te zetten).** Komt dezelfde inkoopfactuur twee keer binnen — zelfde leverancier, zelfde factuurnummer, zelfde bedrag — en is het origineel al geboekt of staat het al in de werkvoorraad, dan zet het systeem de kopie zelf op "Afgewezen" met de reden "Duplicaat van …" en een link naar het origineel. Er verdwijnt niets: je vindt de kopie terug in de afgewezen-lijst en haalt 'm met "Heropenen" zo weer terug. Een beheerder zet dit aan op de administratie-pagina, tab "Boeken & AI" ("Duplicaten automatisch afvoeren").
- **Nieuwe knop "Afvoeren als duplicaat".** Ziet het systeem een duplicaat, dan staat op de factuur en in het ⋯-menu van de lijst één knop die het document in één keer als duplicaat afvoert — je ziet eerst welk origineel het is, een eigen reden typen is niet nodig. Deze knop werkt altijd, ook als het automatisch afvoeren voor de administratie uit staat.
- **Kruisverwijzing aan twee kanten.** Op een afgevoerd duplicaat zie je "Afgevoerd als duplicaat → open origineel"; op het origineel zie je hoeveel kopieën er zijn afgevoerd en door wie (⚙ = automatisch). In de lijst staat bij zo'n document de chip "duplicaat afgevoerd".
- Alleen bij een harde match: zelfde leverancier (ook als die dubbel in Reeleezee staat, herkend op btw-nummer), zelfde factuurnummer én zelfde bedrag. Lijkt een factuur alleen maar op een andere (bijvoorbeeld hetzelfde nummer bij een andere leverancier), dan blijft dat een oranje signaal — daar wordt niets automatisch mee gedaan. Facturen die bij de klant liggen, een open vraag hebben of al geboekt zijn worden nooit automatisch afgevoerd.
- **Splitsvoorstellen kennen nu bijlagen.** Werkbonnen, urenstaten, specificaties en pakbonnen achter een factuur worden herkend als onderdeel van díe factuur; een nieuwe factuur begint alleen bij een nieuwe factuurkop. In de verzamelbak zie je per deel "factuur + 3 bijlagepagina's" of "factuur, 1 pagina", zodat je in één oogopslag ziet wat er geknipt zou worden.
- **"Is één factuur" kan het onthouden.** Wijs je een splitsvoorstel af, dan kun je aanvinken dat mails van deze afzender voor deze administratie nooit meer gesplitst worden. Vanaf de volgende mail komt zo'n factuur direct als één document binnen — zonder voorstel, zonder AI-kosten. De vink staat standaard uit; bij een upload zonder e-mail is er niets te onthouden en zegt het scherm dat ook.
- **Intake-regels op de administratie-pagina.** Onder Instellingen › Administraties › tab Algemeen staat het nieuwe blok "Intake-regels" met alle "nooit splitsen"-afspraken van die administratie (afzender, leverancier, sinds wanneer, door wie). Verwijderen kan daar met één bevestiging; de wijziging komt in het logboek.
- **Projectverdeling pro rato omzet.** Een inkoopfactuur zonder projectnummer kun je nu op het controlescherm over je projecten verdelen: een deel vast op een project, de rest automatisch naar rato van de omzet van de vorige maand — alleen projecten mét omzet tellen mee, het overhead-project doet niet mee. De centen sluiten altijd exact; je ziet vooraf per project het percentage en het bedrag ("Verdeling tonen").
- **Automatisch voorstel per leverancier.** Zet in de instellingen van een administratie per leverancier "verdelen: pro rato omzet" aan (Beheerder) en elke factuur van die leverancier komt vooringevuld met de verdeling binnen — je controleert en boekt zoals altijd; de controles blijven de poort.
- **Hercontrole met actie.** Verandert de omzet van die maand ná het boeken (nagekomen factuur, creditnota), dan rekent het systeem maandelijks na en zie je op de factuur en in de documentenlijst "verdeling wijkt x% af" mét de knop "Herverdelen…" (tegenboeken en opnieuw boeken met de nieuwe verdeling — u bevestigt, er wordt nooit stil herboekt). De drempel is per administratie instelbaar (standaard 5 %).
- **Rustiger signaal "inkoop zonder omzet".** Een net gestart project geeft geen vals alarm meer: het signaal spreekt pas als het project een instelbaar aantal weken loopt (standaard 4).
- **Grootboek per factuurregel wordt voorgesteld uit de omschrijving.** Bij het splitsen van een factuur in regels vult het systeem per regel het grootboek vooraf in. Is dezelfde omschrijving bij deze leverancier al eens door een collega geboekt, dan staat die rekening er met een groene chip "uit geheugen" (ook als de leverancier dubbel in Reeleezee staat — herkend op btw- of KvK-nummer). Komt de rekening alleen uit de oude Reeleezee-historie, dan zie je een oranje chip "uit historie, nog niet bevestigd". Na één keer boeken is dezelfde omschrijving voortaan groen; corrigeer je 'm, dan leert het geheugen de correctie.
- **Nieuwe omschrijvingen: AI kiest uit de rekeningen die deze leverancier al gebruikte.** Staat een regel nog niet in het geheugen, dan doet de AI één keer per factuur een voorstel — uitsluitend uit de grootboekrekeningen waarop deze leverancier eerder is geboekt, nooit een rekening verzinnen. Het voorstel staat oranje gemarkeerd ("AI-voorstel — bevestig"): jij bevestigt of kiest anders. Dit werkt alleen bij administraties waar AI-extractie aanstaat, telt mee in de AI-kostenmeter, en gebeurt niet als de leverancier maar één rekening kent (dan weet het geheugen het al). Automatisch boeken kijkt hier niet naar: een AI-voorstel maakt een factuur nooit vanzelf "groen".
- **Standaard btw-code per administratie (beheerder).** Op de administratie-pagina, tab "Boeken & AI", kies je een standaard btw-code — bijvoorbeeld "verlegd hoog" voor een steigerbouw-administratie. Die wordt alleen ingevuld op regels waar de factuur zelf én het leveranciers-geheugen niets opleveren, herkenbaar aan de grijze chip "standaard administratie". Staat er niets ingesteld, dan verandert er niets. De controles vóór het boeken blijven gewoon gelden — een verkeerde standaard boekt nooit stil door.
- **Kortingsregels worden herkend.** Een korting, rabat of creditregel die als eigen regel op een inkoopfactuur staat (bijvoorbeeld "Korting 10% −56,44"), komt nu als aparte regel met een negatief bedrag in het boekvoorstel — ook wanneer de leverancier het minteken achter het bedrag zet. Bij digitale (UBL-)facturen geldt hetzelfde voor een korting of toeslag op de hele factuur.
- **Controle "Regeltelling vs totaal" vergelijkt weer appels met appels.** Ontbreekt de btw per regel, dan worden de netto-regelbedragen tegen het gelezen totaal exclusief btw gehouden in plaats van tegen het totaal inclusief — dat gaf eerder een onterechte afwijking (casus Huvanco). De melding zegt nu altijd welke bedragen precies vergeleken zijn.
- **Duidelijke melding als er niets te vergelijken valt.** Staat er alleen een totaal inclusief btw en is de btw per regel leeg, dan zegt de controle dat expliciet ("vul de btw per regel of het totaal excl. in") in plaats van een verwarrend verschil te tonen. De aansluit-badge onder de boekingsregels volgt dezelfde logica.

## 2026-09-04 — Odoo-koppeling in de kantoor-UI, eerste echte Odoo-boeking en tellers gelijk

- Op de administratie-pagina (tab Algemeen) staat nu bovenaan het blok **Boekhoud-backend**: je ziet in één oogopslag of een administratie in Reeleezee of in Odoo boekt (paarse chip), welke Odoo-company gekoppeld is, of de verbinding groen is, wanneer de stamgegevens voor het laatst zijn gesynct — mét knoppen "Opnieuw testen", "Sleutel wijzigen…" en "⟳ Sync nu". De bestaande Reeleezee-rijen (webservice-login, eerste sync) staan in datzelfde blok.
- "+ Administratie toevoegen" vraagt als eerste stap het boekhoudpakket: Reeleezee (zoals altijd) of Odoo. Bij Odoo kies je de company uit de lijst — nooit een nummer typen — en wordt de koppeling pas opgeslagen als alle rechten groen zijn; een rode uitkomst legt leesbaar uit wat er in Odoo moet worden rechtgezet.
- Een bestaande Reeleezee-administratie kan via "Odoo koppelen…" op de detailpagina óf volledig overstappen naar Odoo (met een overgangsdatum), óf Odoo alleen gebruiken als leesbron voor de voorraad-uitstroom vanaf een knipdatum (die knipdatum is daarna ter plekke te wijzigen). De wizard vraagt die keuze altijd expliciet.
- Op geboekte documenten staat "Geboekt in Odoo · factuurnummer · company" op dezelfde plek als "Geboekt in RLZ"; een tegenboeking toont de kruisverwijzing tussen beide nummers en een cent-bijstelling van de btw krijgt de chip "btw-cent-override". Werkvoorraad en controlescherm zijn verder identiek voor beide pakketten.
- De eerste complete inkoopfactuur is via de app in Odoo geboekt én weer gecrediteerd (testfactuur op de lege company van Universal Steigerbouw): boekdatum gelijk aan de factuurdatum, bedragen op de cent, producten uit de materiaalcatalogus met aantal en prijs op de regel, project op elke regel en de PDF als bijlage. Wat we daarbij tegenkwamen is direct verbeterd: gearchiveerde Odoo-projecten worden niet meer aangeboden, en een mislukte boekpoging laat geen verouderd concept achter dat een tweede poging in de weg zit.
- **Teller "Vragen" per klant telt hetzelfde als de kaart "Open vragen".** In de werkvoorraad-klantenlijst telde de kolom "Vragen" alleen documenten die door een vraag geblokkeerd staan; de kaart "Open vragen" telde óók vragen op al geboekte documenten of documenten bij de klant. Beide tellen nu het aantal open vragen — een klant met alleen zo'n vraag staat nu ook in de lijst, en het weekoverzicht per mail gebruikt hetzelfde getal.

## 2026-09-03 — Odoo-koppeling: eerste stap voor Universal

- Een administratie kan nu naast Reeleezee ook op Odoo draaien. De Beheerder koppelt met de Odoo-sleutel, kiest de vestiging (company) uit een lijst en de app controleert vooraf of verbinding, rechten, dagboeken en btw-codes kloppen; pas als alles groen is wordt er iets opgeslagen. Grootboek, btw-codes, crediteuren en projecten komen daarna in dezelfde lijsten terecht als bij Reeleezee, dus het controlescherm werkt hetzelfde.
- Inkoopfacturen van zo'n administratie boeken in Odoo per regel, met product, aantal en prijs waar de materiaalcatalogus het product kent, en met het project op de regel. De boekdatum is de factuurdatum, de PDF hangt aan de boeking en een btw-verschil van een paar cent wordt zichtbaar gelijkgetrokken. Corrigeren gebeurt met een creditnota die naar het origineel verwijst; er wordt nooit iets verwijderd. Nieuw kopveld: het betalingskenmerk van de leverancier gaat mee.
- Voorraad Universal Verkoop: de verkoopfacturen die sinds de overstap in Odoo staan tellen vanaf een instelbare knipdatum mee in de voorraadaansluiting, alleen-lezen. Reeleezee blijft de bron tot die datum, zodat niets dubbel telt; de herkomst per regel staat erbij ("Odoo-verkoopfactuur F/…").

## 2026-09-03 — Dubbele crediteuren: één lijst over alle administraties, mét actie

- Inzicht › Crediteuren toont nu in één lijst alle waarschijnlijk-dubbele crediteuren van alle administraties waar je toegang toe hebt, met het zwaarste signaal bovenaan (zelfde btw-nummer, dan KvK, dan IBAN, dan alleen de naam). Je kunt filteren op administratie of soort signaal en zoeken op naam of nummer; de werkvoorraad krijgt een teller zodra er dubbelen zijn.
- Per cluster kies je met "Voorkeur kiezen & rest archiveren…" welke crediteur blijft. De andere komen op de RLZ-werklijst onderaan het scherm ("klaargezet — archiveer in Reeleezee"), omdat Reeleezee archiveren via de koppeling niet toestaat; de app vinkt de regel dagelijks vanzelf af zodra het in Reeleezee gebeurd is, en je kunt hem ook zelf afvinken. Staat er nog een open factuur op een crediteur die zou verdwijnen, dan blokkeert de dialoog met "eerst afletteren". Boekingsgeheugen en btw-/KvK-nummer gaan direct mee naar de voorkeur, zodat voorstellen blijven werken. Er wordt niets verwijderd.
- Lijken twee crediteuren alleen op naam op elkaar maar hebben ze een verschillend KvK-nummer, dan staat er "Geen dubbel — afmelden": met een reden verdwijnt het cluster uit de lijst en komt het voor die combinatie niet terug.

## 2026-09-03 — Terugkerende facturen: één overzicht voor het hele kantoor

- Inzicht › Terugkerende facturen toont nu alle signalen van al je administraties in één lijst, de meest urgente bovenaan: eerst de leveranciers waarvan de verwachte factuur het langst uitblijft, daarna de prijsstijgingen. Je filtert op administratie en status (aandacht nodig, gesnoozed, afgemeld) en zoekt op leverancier; de teller "Verwachte facturen" in de werkvoorraad opent de lijst direct gefilterd op die klant.
- Elke regel heeft één knop: bij een uitgebleven factuur "Navragen bij leverancier…" — je krijgt een kant-en-klare mailtekst met de laatste factuur en de verwachte periode, past die aan en verstuurt zelf (het adres komt uit de crediteurkaart als dat bekend is, anders vul je het in); bij een prijsstijging "Naar de boeking →". Snoozen en afmelden zitten in het ⋯-menu.
- "Herbereken alles" werkt nu in één keer voor alle administraties op de achtergrond; je ziet de voortgang en het resultaat, en een storing blijft zichtbaar met de reden.

## 2026-09-03 — Open vragen: één lijst over alle klanten

- Open vragen staan nu in één lijst over al je klanten, oudste eerst: klik op de kaart "Open vragen" op de werkvoorraad en je ziet per vraag de leverancier, het bedrag, wie aan de beurt is en hoeveel dagen de vraag al wacht (oranje vanaf een week). Filter op klant, op "aan mij" of op ouderdom, en klik "Beantwoorden" om direct in het gesprek te landen.
- De lijst laadt in één keer in plaats van klant voor klant, dus ook met veel administraties is hij meteen compleet. Het getal op de kaart "Open vragen" komt uit dezelfde bron als de lijst; vragen aan een klant-accordeur over een factuur die al bij de klant ligt of geboekt is tellen nu ook mee, met apart erbij hoeveel vragen het boeken echt tegenhouden.

## 2026-09-03 — Voorraad: één overzicht over alle administraties, teller op de werkvoorraad

- Inzicht › Voorraad opent nu met één lijst van alle artikelgroepen waarvan de telling buiten de tolerantie valt, over alle administraties met "Voorraad bijhouden" tegelijk — de grootste afwijking bovenaan, met een oranje of rode markering naar zwaarte. U hoeft niet meer eerst een administratie te kiezen; filteren op administratie of zoeken op artikelgroep kan wel. "Bekijk regels" opent direct de factuurregels achter dat verschil.
- Op de werkvoorraad staat per klant een teller "Voorraadverschil" zodra er iets buiten de tolerantie valt; een klik brengt u naar de lijst voor die klant. Het bestaande aansluitscherm per administratie blijft bereikbaar en toont bij een verschil nu ook een directe link naar de regels.
- De lijsten met factuurregels, diensten en artikelcodes laden nu per 25 regels met bladerknoppen, in plaats van alles in één keer.

## 2026-09-03 — Archief: over alle administraties tegelijk bladeren, met datumvenster en paginering

- Het archief opent nu meteen met de geboekte documenten van ál uw administraties in één lijst; een administratie kiezen is een filter geworden (leeg = alles) en de kolom Administratie staat bij elke rij. Kolomkoppen zijn sorteerbaar (leverancier, boekstuk, bedrag, factuurdatum, geboekt op, administratie) en de teller toont "N documenten over M administraties".
- De lijst laadt standaard de laatste twaalf maanden (op het moment van boeken) en toont 25 documenten per pagina; het datumvenster staat zichtbaar ingevuld en is vrij aan te passen, en het zoekveld filtert op leverancier, referentie, boekstuk of bedrag. Alle filters staan in de adresbalk, zodat een link naar het archief precies dezelfde weergave opent.
- Ook het archief per administratie (vanaf de klantpagina) laadt niet meer alle jaren in één keer, maar gepagineerd binnen hetzelfde datumvenster — de lijst blijft snel, ook bij duizenden geboekte stukken.

## 2026-09-03 — Autoboek-kandidaten in bulk verbergen; werklijst in de materiaalcatalogus

- Autoboeken › Kandidaten: meerdere kandidaten tegelijk verbergen gaat nu in één keer — je ziet daarna per leverancier wat er gebeurd is (verborgen, overgeslagen met de reden, of mislukt). Staat er meer in de lijst dan op de pagina, dan kun je na "selecteer alles" kiezen voor "Selecteer alle N resultaten"; de knop noemt altijd het aantal dat je aanzet of verbergt, en de bevestiging zegt erbij dat het om alle resultaten binnen je filter gaat.
- Materiaalcatalogus: leveranciers waarvoor nog een bestel-mailadres of crediteur-koppeling ontbreekt staan nu in één werklijst "Nog in te stellen" bovenaan het scherm; klik op een regel en je staat direct in het juiste veld. Bij meer dan vijftien leveranciers kun je de leverancier-chips doorzoeken.

## 2026-09-03 — Doorbelasten-blok: knoppen in de huisstijl

- De knop "+ Doelentiteit" in het blok "Doorbelasten na boeken" op het controlescherm ziet er nu hetzelfde uit als "+ Regel toevoegen" bij de boekingsregels erboven; hij deed het al, maar stond er als kale grijze knop. "Verdeelsleutel" ernaast heeft dezelfde vorm.
- Kleine tekstknoppen elders in de app (zoals "wijzigen", "annuleren" of "gearchiveerd tonen") tonen nu als tekstlink in de actiekleur in plaats van als standaard grijze knop. Er verandert niets aan wat ze doen.

## 2026-09-03 — Dubbele UBL- en PDF-documenten van dezelfde factuur samengevoegd; nazorg-runs bestand tegen een verbindingsstoring

- Stond dezelfde factuur twee keer in de werkvoorraad van een administratie, één keer als UBL-document en één keer als PDF-document uit dezelfde e-mail, dan voegt de nazorg-run die nu samen: het PDF-document blijft staan met de gegevens uit de UBL en de PDF als beeld, het UBL-document krijgt de status "Samengevoegd" en verdwijnt uit het openstaande werk. Niets wordt verwijderd en de tijdlijn van beide documenten vermeldt de stap.
- Dat gebeurt alleen als beide documenten nog te controleren zijn en niemand er een boekvoorstel op heeft opgeslagen. Is één van de twee al beoordeeld, geboekt, bij de klant of afgewezen, dan blijven beide staan met de reden in het rapport. Twijfel over welk paar bij elkaar hoort betekent overslaan.
- Samenvoegen is ongedaan te maken zolang het document nog niet geboekt is: het UBL-document komt dan terug in de status die het had.
- Valt tijdens een nazorg-run de databaseverbinding even weg, dan probeert de run dat ene document precies één keer opnieuw en gaat daarna door met de rest. Blijft de verbinding weg, dan stopt de run zichtbaar met een melding en kan hij later gewoon opnieuw worden gestart.

## 2026-09-03 — Verzamelbak: gescheiden UBL- en PDF-versies van dezelfde factuur alsnog samengevoegd

- Kwam een factuur eerder als UBL én als PDF in dezelfde e-mail binnen en is alleen de PDF al aan een administratie toegewezen (de UBL bleef in de verzamelbak met de chip "tegenhanger al toegewezen"), dan voegt het kantoor die twee nu alsnog samen via een nazorg-run: het bestaande document blijft staan, de gegevens komen uit de UBL en de PDF blijft het beeld. De verzamelbak-rij verdwijnt als "samengevoegd", niets wordt verwijderd.
- Dat gebeurt alleen bij documenten die nog te controleren zijn. Geboekte facturen, facturen bij de klant ter accordering, met een open vraag of afgewezen worden overgeslagen met de reden in het rapport, en een boekvoorstel dat je zelf al hebt opgeslagen wordt nooit overschreven (dan wordt alleen de UBL gekoppeld).
- Twijfelt het systeem over welke UBL bij welke PDF hoort, dan doet het niets en meldt het waarom. Samenvoegen is ongedaan te maken zolang het document nog niet geboekt is.

## 2026-09-02 — Verzamelbak: facturen uit Reeleezee-exports leesbaar en boekbaar

- Facturen die als UBL-bestand uit Reeleezee zelf komen (bijvoorbeeld de onderlinge facturen tussen Universal Nederland en Universal Steigerbouw) tonen nu wél voor wie ze zijn: de tenaamstelling wordt ook gelezen als die alleen als bedrijfsnaam in het bestand staat. Tientallen van zulke facturen stonden ten onrechte met "geen tenaamstelling gelezen" in de verzamelbak.
- Zit de factuur-PDF ín het UBL-bestand ingesloten, dan zie je die PDF nu overal waar het beeld hoort: in het voorbeeld van de verzamelbak, als bijlage op het controlescherm en als bijlage bij de boeking in Reeleezee. Het UBL-bestand zelf blijft naast het beeld downloadbaar.
- De bestaande nazorg-herlezing neemt zulke UBL-rijen nu ook mee (zonder AI): tenaamstelling en suggestie worden gezet en de ingesloten PDF wordt als beeld vastgelegd, zodat de rijen klaarstaan om toe te wijzen. Het toewijzings-geheugen leert daar niets van; dat gebeurt pas bij een menselijke toewijzing.
- Verzamelbak in bulk: vink meerdere rijen aan (of alles binnen het filterveld) en wijs ze in één keer toe aan één administratie — de keuze staat vooringevuld als alle geselecteerde rijen dezelfde suggestie dragen — of handel ze samen af als "hoort niet bij ons" met één reden. Je ziet per rij wat er gebeurd is; een rij die niet verwerkt kon worden komt met de reden terug in de lijst.
- Geboekte documenten laten nu zien wáár ze in Reeleezee staan: in de lijst (tooltip op de status), in de kop van het controlescherm en op de review-schermen staat "Geboekt in RLZ · boekstuk … · crediteur/debiteur". Bij verkoopfacturen en omzetboekingen staat erbij dat je ze in Reeleezee terugvindt op de debiteurenkaart of in het verkoopboek, en níét onder Verkopen → Facturen (die lijst toont alleen facturen die in Reeleezee zelf zijn gemaakt).
- Verzamelbak: is de PDF (of UBL) van dezelfde factuur uit dezelfde e-mail al toegewezen, dan draagt de rij nu een chip "tegenhanger al toegewezen" en valt hij buiten "selecteer alles" — toewijzen zou anders een tweede document van dezelfde factuur maken.

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
