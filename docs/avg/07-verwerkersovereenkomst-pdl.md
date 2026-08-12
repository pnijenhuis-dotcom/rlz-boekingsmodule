# Verwerkersovereenkomst (intra-groep) — Administratiekantoor Nijenhuis ↔ PDL Powerhouse B.V.

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld** (vraag 9 van het
> toetsingsmemo). Opgesteld 2026-08-12. Aanname die de jurist moet bevestigen: PDL is
> verwerker voor **hosting en software-exploitatie**; Google Cloud is subverwerker ván PDL;
> het kantoor contracteert **Anthropic en Exact Reeleezee rechtstreeks** (accounts op naam
> van het kantoor) zodat documenten 1–3 ongewijzigd kloppen. Staan die accounts feitelijk op
> naam van PDL, dan verhuizen die partijen naar Bijlage B en moeten documenten 1–2 daarop
> worden aangepast — dit is een invulpunt bij ondertekening.

**Partijen**

1. **Administratiekantoor Nijenhuis** ([rechtsvorm + KvK invullen]), hierna: *Verantwoordelijke*;
2. **PDL Powerhouse B.V.** ([KvK invullen]), hierna: *Verwerker*.

Overwegende dat Verwerker eigenaar en beheerder is van de programmatuur "RLZ Boekingsmodule"
en de bijbehorende cloudinfrastructuur (Google Cloud, regio `europe-west4`), en deze aan
Verantwoordelijke ter beschikking stelt voor het voeren van klantadministraties, komen
partijen het volgende overeen.

## Artikel 1 — Onderwerp, aard en doel

1. Verwerker verwerkt persoonsgegevens uitsluitend ten behoeve van Verantwoordelijke in het
   kader van: (a) hosting en technisch beheer van de RLZ Boekingsmodule en de bijbehorende
   database en documentopslag; (b) onderhoud, updates en incidentafhandeling.
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
EU Standard Contractual Clauses of EU-U.S. Data Privacy Framework). Voor Google Cloud loopt
dit via het Cloud Data Processing Addendum; dataopslag is geconfigureerd in `europe-west4`.

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

**Bijlage B — Subverwerkers van PDL**: Google Cloud EMEA Ltd. (hosting, database,
documentopslag; regio `europe-west4`; CDPA incl. SCC's/DPF). *(Invulpunt: staan het
Anthropic-API-account en/of het Exact Reeleezee-abonnement op naam van PDL in plaats van het
kantoor, dan hier toevoegen en documenten 1–2 overeenkomstig aanpassen.)*

**Bijlage C — Beveiligingsmaatregelen**: de maatregelen zoals beschreven in
verwerkingsregister §8 (document 1), die hier als herhaald en ingelast gelden.

*Aldus overeengekomen en ondertekend in tweevoud:*

| Administratiekantoor Nijenhuis | PDL Powerhouse B.V. |
|---|---|
| Naam: | Naam: |
| Functie: | Functie: |
| Datum: | Datum: |
| Handtekening: | Handtekening: |
