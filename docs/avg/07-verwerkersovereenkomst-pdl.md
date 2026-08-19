# Verwerkersovereenkomst (intra-groep) — Administratiekantoor Nijenhuis ↔ PDL Powerhouse B.V.

> ✅ **Ondertekenklaar — versie 2026-08-18** (jurist-akkoord op het concept 2026-08-12,
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
   KvK [INVULLEN: KvK-nummer kantoor], hierna: *Verantwoordelijke*;
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

**Bijlage A — Verwerkingen en gegevens**: de verwerkingen zoals beschreven in het
verwerkingsregister van Verantwoordelijke (document 1), beperkt tot hosting/opslag/verwerking
binnen de RLZ Boekingsmodule.

**Bijlage B — Subverwerkers van PDL** (accounthouder is telkens Verwerker):

| Subverwerker | Dienst | Datalocatie & doorgifte | Contract/grondslag |
|---|---|---|---|
| Google Cloud EMEA Ltd. | Hosting, database, documentopslag en achtergrondjobs — Google Cloud-project `rlz-boekhouding` in de PDL Powerhouse-organisatie | EU, regio `europe-west4` (EU-organisatiebeleid; CMEK, platformbesluit 0021) | Cloud Data Processing Addendum (versie 8 juni 2026, gearchiveerd) incl. EU SCC's; Google is DPF-gecertificeerd |
| Google Workspace (Google Cloud EMEA Ltd.) | E-mailvoorziening: intake-postvak `facturen@ak-nijenhuis.nl` (IMAP) en uitgaande systeemmail (uitnodigingen, herinneringen) — Workspace-omgeving van PDL | EU/doorgifte conform CDPA | Zelfde CDPA; Workspace expliciet in scope (geverifieerd 2026-08-15) |
| Anthropic Ireland, Limited | AI-extractie van documentgegevens (Claude API) — API-organisatieaccount van PDL; alleen actief achter de AVG-gate `intake_ai_ingeschakeld` | Verwerking en opslag in de VS; doorgifte op de EU SCC's in de DPA (niet DPF-gecertificeerd); geen training op klantdata (Commercial Terms 17-06-2025); Zero Data Retention aangevraagd 2026-08-14, uitkomst open | Commercial Terms of Service (17-06-2025) + Data Processing Addendum (24-02-2025), beide gearchiveerd |
| Apple Inc. / Apple Distribution International Ltd. | Distributie van de accordeur-app (App Store/TestFlight) en pushmeldingen via APNs — Apple Developer-account van PDL; pushberichten bevatten apparaat-tokens maar geen financiële gegevens of documentinhoud | Doorgifte VS mogelijk (APNs) | [INVULLEN: Apple-DPA/doorgiftecheck archiveren — uitbreiding verwerkers-checklist, vóór livegang van de iOS-app] |
| Google Ireland Ltd. (Google Play + Firebase Cloud Messaging) | Distributie van de Android-app (Play Console van PDL) en pushmeldingen via FCM — **vanaf activering van de Android-app** (nu nog niet live) | Doorgifte conform Google-voorwaarden | [INVULLEN: FCM-/Play-DPA-check archiveren — AVG-afweging Firebase is een open beslispunt, vóór livegang van de Android-app] |

*Geen subverwerker van PDL:* **Exact Reeleezee (Exact Group B.V.)** — rechtstreeks
gecontracteerd door Verantwoordelijke (bestaande relatie; VWO 1.5/1.6, EU/EER-datalocatie
en API-toegang bevestigd — zie de verwerkers-checklist, document 2).

**Bijlage C — Beveiligingsmaatregelen**: de maatregelen zoals beschreven in
verwerkingsregister §8 (document 1), die hier als herhaald en ingelast gelden.

*Aldus overeengekomen en ondertekend in tweevoud te Arnhem:*

| Administratiekantoor Nijenhuis C.V. | PDL Powerhouse B.V. |
|---|---|
| Naam: [INVULLEN] | Naam: [INVULLEN] |
| Functie: [INVULLEN: beherend vennoot / gevolmachtigde] | Functie: [INVULLEN: bestuurder / gevolmachtigde] |
| Datum: | Datum: |
| Handtekening: | Handtekening: |
