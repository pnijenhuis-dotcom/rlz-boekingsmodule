<!--
  "Wat is nieuw" — hand-gecureerd changelog voor kantoorgebruikers (best-practice-punt D1, 01-09).
  REGELS: één blok per release, kop "## JJJJ-MM-DD — Titel", daaronder bullets in KLANTLEESBARE taal
  (geen bestandsnamen, geen migratienummers, geen jargon). Nieuwste release bovenaan. Code vult dit
  bestand bij élke feature-commit aan (de dialoog in de topbar leest het; changelog.test.ts bewaakt de
  vorm). Geen AI.
-->

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
