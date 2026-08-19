# Verwerkersovereenkomst (intra-groep) — Administratiekantoor Nijenhuis ↔ PDL Powerhouse B.V.

> ✅✍️ **GETEKEND — 2026-08-19** (in tweevoud te Arnhem; beide partijen P.W. Nijenhuis,
> Directie). Getekend exemplaar gearchiveerd:
> `Verwerkersovereenkomst-PDL-getekend-2026-08-18.pdf` (hoofdtekst + Bijlagen A/B/C,
> KvK kantoor 72504412 ingevuld); de bijlagen zijn ook los als docx bewaard
> (`Bijlagen-A-B-C-Verwerkersovereenkomst-PDL-2026-08-18.docx`). Daarmee zijn de open
> punten "KvK-nummer + ondertekenblok" gedicht en is de stap-1-voorwaarde
> "PDL-verwerkersovereenkomst getekend" (document 5) vervuld. Dit md-bestand blijft de
> canonieke tékst; het getekende PDF is het bindende exemplaar.
>
> **Bijlagen gesynchroniseerd (2026-08-19):** de Bijlagen A/B/C hieronder zijn 1-op-1 de
> tekst uit de getekende versie (de nette Cowork-docx hierboven) — de getekende bijlagen
> dragen exact deze bewoordingen, inclusief de term "Verwerkingsverantwoordelijke" (waar
> de hoofdtekst de verkorte definitie "Verantwoordelijke" hanteert; zelfde partij).
> Artikelverwijzing gecontroleerd: de meldprocedure waarnaar Bijlage B verwijst is
> inderdaad artikel 6 (Subverwerkers, lid 2 — vooraf informeren + 14 dagen bezwaar).
> Verzend-/teken-artefacten (docx/PDF) blijven ongemoeid.
>
> Historie: **ondertekenklaar — versie 2026-08-18** (jurist-akkoord op het concept 2026-08-12,
> vraag 9 van het toetsingsmemo). Het door de jurist meegetoetste invulpunt is in deze
> versie ingevuld conform de **feitelijke accountstructuur**: het Anthropic-API-account
> (organisatie), het Google Cloud-project, de Google Workspace-omgeving én de Apple
> Developer- en Google Play-accounts staan op naam van **PDL Powerhouse B.V.** — die
> partijen staan daarom in Bijlage B als subverwerkers ván PDL. Alleen **Exact Reeleezee**
> contracteert het kantoor rechtstreeks (bestaande relatie, webservice-logins per
> administratie) en blijft dus búíten deze overeenkomst (verwerker van Verantwoordelijke,
> documenten 1–2). ✅ De jurist-notitie-actie is uitgevoerd (2026-08-19): documenten 1–2
> (verwerkingsregister + verwerkers-checklist) zijn aangepast op de verhuizing van Anthropic
> en Google Workspace naar de PDL-keten. De teken-docx
> (`Verwerkersovereenkomst-PDL-definitief-2026-08-18.docx`) is de **schone tekenversie
> zónder deze statusnoot** (gegenereerd met `--zonder-statusnoot`).

**Partijen**

1. **Administratiekantoor Nijenhuis C.V.**, gevestigd te Arnhem (Turfstraat 1, 6811 HL),
   KvK 72504412, hierna: *Verantwoordelijke*;
2. **PDL Powerhouse B.V.**, gevestigd te Arnhem (Turfstraat 1-3, 6811 HL), KvK 42063059,
   hierna: *Verwerker*.

Overwegende dat Verwerker eigenaar en beheerder is van de programmatuur "RLZ Boekingsmodule"
en de bijbehorende cloudinfrastructuur (Google Cloud, regio `europe-west4`), en deze aan
Verantwoordelijke ter beschikking stelt voor het voeren van klantadministraties, komen
partijen het volgende overeen.

## Artikel 1 — Onderwerp, aard en doel

1. Verwerker verwerkt persoonsgegevens uitsluitend ten behoeve van Verantwoordelijke in het
   kader van: (a) hosting en technisch beheer van de RLZ Boekingsmodule en de bijbehorende
   database en documentopslag; (b) onderhoud, updates en incidentafhandeling; (c) de
   AI-extractie van documentgegevens via het Anthropic-API-account van Verwerker; (d) de
   e-mail- en notificatievoorzieningen van de programmatuur (intake-postvak, uitgaande
   systeemmail, pushmeldingen) en de distributie van de bijbehorende mobiele
   accordeur-applicatie via de store-accounts van Verwerker.
2. De verwerking omvat geen zelfstandig gebruik door Verwerker; Verwerker bepaalt doel noch
   middelen anders dan de technische inrichting binnen de instructies van Verantwoordelijke.
3. Duur: zolang de terbeschikkingstelling van de programmatuur voortduurt (zie artikel 10).

## Artikel 2 — Categorieën betrokkenen en persoonsgegevens (Bijlage A)

De verwerking betreft de gegevens zoals gespecificeerd in Bijlage A, waaronder gegevens van
leveranciers, afnemers/huurders, medewerkers en contactpersonen zoals die voorkomen op
boekhouddocumenten (namen, adressen, IBAN's, factuur- en betaalgegevens) en accountgegevens
van gebruikers (kantoormedewerkers en klant-accordeurs). Burgerservicenummers worden door de
programmatuur niet geëxtraheerd of geïndexeerd; brondocumenten kunnen BSN's bevatten en
worden uitsluitend als bestand bewaard (wettelijke bewaarplicht).

## Artikel 3 — Instructies

1. Verwerker verwerkt uitsluitend op schriftelijke instructie van Verantwoordelijke, behoudens
   afwijkende wettelijke verplichting; in dat geval informeert Verwerker Verantwoordelijke
   vooraf, tenzij de wet dat verbiedt.
2. Verwerker informeert Verantwoordelijke onmiddellijk indien een instructie naar zijn oordeel
   in strijd is met de AVG.

## Artikel 4 — Vertrouwelijkheid

Verwerker waarborgt dat personen die onder zijn gezag persoonsgegevens verwerken zich tot
vertrouwelijkheid hebben verbonden.

## Artikel 5 — Beveiliging (art. 32 AVG; Bijlage C)

Verwerker treft passende technische en organisatorische maatregelen, waaronder ten minste de
maatregelen in Bijlage C (o.a. toegangsbeperking per administratie met row-level security,
tweefactorauthenticatie/passkeys, versleutelde opslag van credentials, append-only audit-log,
dataregio `europe-west4`, back-ups met point-in-time recovery).

## Artikel 6 — Subverwerkers (Bijlage B)

1. Verantwoordelijke verleent algemene toestemming voor de subverwerkers in Bijlage B.
2. Verwerker informeert Verantwoordelijke vooraf over beoogde wijzigingen; Verantwoordelijke
   kan binnen 14 dagen gemotiveerd bezwaar maken.
3. Verwerker legt aan subverwerkers dezelfde verplichtingen op als in deze overeenkomst en
   blijft jegens Verantwoordelijke aansprakelijk voor hun nakoming.

## Artikel 7 — Doorgifte buiten de EER

Doorgifte vindt uitsluitend plaats met een passend doorgiftemechanisme (adequaatheidsbesluit,
EU Standard Contractual Clauses of EU-U.S. Data Privacy Framework); het toepasselijke
mechanisme staat per subverwerker in Bijlage B. Voor Google Cloud en Google Workspace loopt
dit via het Cloud Data Processing Addendum; dataopslag is geconfigureerd in `europe-west4`.
Voor Anthropic rust de doorgifte op de EU SCC's in Anthropics Data Processing Addendum
(verwerking en opslag in de VS; Anthropic is niet DPF-gecertificeerd — registercheck
2026-08-15).

## Artikel 8 — Bijstand aan Verantwoordelijke

Verwerker verleent redelijke bijstand bij: verzoeken van betrokkenen (art. 15–22), de
beveiligingsplicht, meldplicht datalekken, DPIA's en voorafgaande raadpleging, rekening
houdend met de aard van de verwerking en de beschikbare informatie.

## Artikel 9 — Inbreuken (datalekken)

Verwerker informeert Verantwoordelijke **zonder onredelijke vertraging en uiterlijk binnen
24 uur** na ontdekking van een inbreuk in verband met persoonsgegevens, met ten minste de
informatie die Verantwoordelijke nodig heeft voor de eigen meldplicht (aard, betrokken
gegevens/administraties, waarschijnlijke gevolgen, genomen maatregelen). Afhandeling volgens
de datalek-procedure van Verantwoordelijke (document 6).

## Artikel 10 — Einde van de overeenkomst

Bij beëindiging van de dienstverlening retourneert of verwijdert Verwerker alle
persoonsgegevens naar keuze van Verantwoordelijke, behoudens wettelijke bewaarplichten;
verwijdering geschiedt conform het pseudonimiserings-/bewaarbeleid van Verantwoordelijke
(7 jaar administratieplicht).

## Artikel 11 — Audit

Verwerker stelt alle informatie ter beschikking die nodig is om nakoming aan te tonen en
staat audits toe door of namens Verantwoordelijke, maximaal eenmaal per jaar behoudens
incidenten, tegen redelijke kosten en met redelijke aankondiging. Voor subverwerkers volstaan
hun certificeringen/auditrapporten (ISO 27001, SOC 2) waar beschikbaar.

## Artikel 12 — Aansprakelijkheid en rangorde

1. Aansprakelijkheid volgt de hoofdovereenkomst tussen partijen; bij ontbreken daarvan geldt
   de wettelijke regeling van art. 82 AVG.
2. Bij strijd tussen deze overeenkomst en andere afspraken prevaleert deze overeenkomst voor
   zover het de verwerking van persoonsgegevens betreft.

## Bijlage A — Verwerkingen en gegevens

De verwerking betreft de verwerkingen zoals beschreven in het verwerkingsregister van
Verwerkingsverantwoordelijke (document 1), beperkt tot hosting, opslag en verwerking binnen
de RLZ Boekingsmodule.

Categorieën betrokkenen: leveranciers, afnemers/huurders, medewerkers en contactpersonen van
klanten van Verwerkingsverantwoordelijke, alsmede gebruikers van de programmatuur
(kantoormedewerkers en klant-accordeurs).

Categorieën persoonsgegevens: gegevens zoals die voorkomen op boekhouddocumenten (namen,
adressen, IBAN's, factuur- en betaalgegevens) en accountgegevens van gebruikers (naam,
e-mailadres, authenticatiegegevens).

Burgerservicenummers worden door de programmatuur niet geëxtraheerd of geïndexeerd;
brondocumenten die een BSN bevatten worden uitsluitend als bestand bewaard in het kader van
de wettelijke bewaarplicht.

## Bijlage B — Overzicht van subverwerkers

Verwerker maakt bij de uitvoering van deze overeenkomst gebruik van de onderstaande
subverwerkers. Verwerker is telkens de accounthouder en contractspartij.
Verwerkingsverantwoordelijke verleent voor deze subverwerkers algemene schriftelijke
toestemming als bedoeld in artikel 28 lid 2 AVG; voor wijzigingen geldt de meldprocedure van
artikel 6 van de overeenkomst.

| Subverwerker | Dienstverlening | Datalocatie en doorgifte | Contractuele grondslag |
|---|---|---|---|
| Google Cloud EMEA Ltd. | Hosting, database, documentopslag en achtergrondverwerking (Google Cloud-project rlz-boekhouding binnen de organisatie van Verwerker) | EU, regio europe-west4, afgedwongen door organisatiebeleid; versleuteling met klant-beheerde sleutels (CMEK) | Cloud Data Processing Addendum d.d. 8 juni 2026 (gearchiveerd), inclusief EU-modelcontractbepalingen; Google is gecertificeerd onder het EU-U.S. Data Privacy Framework |
| Google Workspace (Google Cloud EMEA Ltd.) | E-mailvoorziening: ontvangst van administratiedocumenten (facturen@ak-nijenhuis.nl) en uitgaande systeemberichten (uitnodigingen, herinneringen) | EU; eventuele doorgifte conform het CDPA | Zelfde Cloud Data Processing Addendum; toepasselijkheid op Workspace geverifieerd op 15 augustus 2026 |
| Anthropic Ireland, Limited | AI-ondersteunde gegevensextractie uit administratiedocumenten (Claude API), via het API-organisatieaccount van Verwerker; uitsluitend actief na uitdrukkelijke activering door Verwerkingsverantwoordelijke (AVG-schakelaar per administratie) | Verwerking en opslag in de Verenigde Staten; doorgifte op grond van de EU-modelcontractbepalingen in de DPA (Anthropic is niet DPF-gecertificeerd); contractueel uitgesloten dat klantdata voor modeltraining wordt gebruikt; verzoek tot Zero Data Retention ingediend op 14 augustus 2026, uitkomst nog open | Commercial Terms of Service d.d. 17 juni 2025 en Data Processing Addendum d.d. 24 februari 2025 (beide gearchiveerd) |
| Apple Inc. / Apple Distribution International Ltd. | Distributie van de goedkeur-app (App Store, TestFlight) en aflevering van pushmeldingen (APNs) via het Apple Developer-account van Verwerker; pushberichten bevatten apparaat-tokens en aantallen, geen financiële gegevens of documentinhoud | Doorgifte naar de Verenigde Staten mogelijk (APNs) | [Aan te vullen vóór livegang van de iOS-app: Apple-verwerkersvoorwaarden en doorgiftegrondslag archiveren — zie verwerkers-checklist, sectie E] |
| Google Ireland Ltd. (Google Play en Firebase Cloud Messaging) | Distributie van de Android-app (Play Console van Verwerker) en aflevering van pushmeldingen (FCM); deze subverwerking vangt pas aan bij activering van de Android-app | Doorgifte conform de toepasselijke Google-voorwaarden | [Aan te vullen vóór livegang van de Android-app: FCM-/Play-verwerkersvoorwaarden archiveren — zie verwerkers-checklist, sectie F] |

Buiten deze bijlage valt Exact Reeleezee (Exact Group B.V.): deze partij is rechtstreeks
door Verwerkingsverantwoordelijke gecontracteerd en is derhalve geen subverwerker van
Verwerker. De toepasselijke verwerkersovereenkomst (versie 1.5/1.6), de bevestiging van
EU/EER-datalocatie en de toepasselijkheid op de API-toegang zijn vastgelegd in de
verwerkers-checklist (document 2).

## Bijlage C — Beveiligingsmaatregelen

Als technische en organisatorische maatregelen in de zin van artikel 32 AVG gelden de
maatregelen zoals beschreven in §8 van het verwerkingsregister (document 1), welke
beschrijving hier als herhaald en ingelast geldt. Daartoe behoren ten minste:
toegangsbeperking per administratie (row-level security), tweefactorauthenticatie en
passkeys, versleutelde opslag van credentials (envelope encryption met KMS-beheerde
sleutels), een append-only audit-log, dataopslag in de EU (regio europe-west4, met
klant-beheerde versleuteling), en back-ups met point-in-time recovery.

Wijzigingen in deze maatregelen die het beschermingsniveau verlagen, worden vooraf aan
Verwerkingsverantwoordelijke gemeld.

*Aldus overeengekomen en ondertekend in tweevoud te Arnhem op 19 augustus 2026:*

| Administratiekantoor Nijenhuis C.V. | PDL Powerhouse B.V. |
|---|---|
| Naam: P.W. Nijenhuis | Naam: P.W. Nijenhuis |
| Functie: Directie | Functie: Directie |
| Datum: 19 augustus 2026 | Datum: 19 augustus 2026 |
| Handtekening: zie het getekende exemplaar (`Verwerkersovereenkomst-PDL-getekend-2026-08-18.pdf`) | Handtekening: idem |
