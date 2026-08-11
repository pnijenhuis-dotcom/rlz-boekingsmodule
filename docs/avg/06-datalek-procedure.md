# Datalek-procedure (meldplicht art. 33/34 AVG) — Administratiekantoor Nijenhuis

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**
> Opgesteld 2026-08-11 als invulling van restpunt §5.3 uit de DPIA-lichte toets. Kantoorbreed:
> geldt voor incidenten in de RLZ-boekingsmodule, Reeleezee, e-mail en papier.

## 1. Wat is een datalek (werkdefinitie)

Elke inbreuk op de beveiliging die per ongeluk of onrechtmatig leidt tot vernietiging, verlies,
wijziging, of ongeoorloofde verstrekking van of toegang tot persoonsgegevens. Voorbeelden in
onze context: een verkeerd geadresseerde e-mail met factuurbijlagen, een kwijtgeraakte/gestolen
(ontgrendelde) telefoon of laptop met toegang, een gecompromitteerd account (ondanks
2FA/passkeys), onbevoegde toegang tot een administratie door een scoping-fout, een inbraak bij
een verwerker (Anthropic, Google, Exact), of ransomware op een kantoormachine.

## 2. Rollen

| Rol | Wie | Taak |
|---|---|---|
| Meldpunt & coördinator | P. Nijenhuis (Beheerder) | Ontvangt interne meldingen, leidt de afhandeling, besluit over AP-/betrokkenen-melding |
| Plaatsvervanger | [invullen] | Bij afwezigheid coördinator |
| Alle medewerkers + klant-accordeurs | — | Meldplicht: elk vermoeden direct (zelfde dag) melden bij het meldpunt — ook "bijna-lekken"; melden wordt nooit bestraft |

## 3. Procedure (de klok van 72 uur start bij ontdekking)

**Stap 1 — Direct beperken (uur 0).** Toegang dichtzetten met de bestaande middelen:
kill-switch accordeur-apparaat, sessies intrekken (revoke-all), credential roteren
(RLZ-webservice-login, API-keys), gate uitzetten (`intake_ai`, boeken-kill-switch). Niets
verwijderen — bewijs en audit-trail bewaren (append-only audit_event helpt hier).

**Stap 2 — Vastleggen (uur 0–4).** In het datalekregister (§4): wat is er gebeurd, welke
gegevens/betrokkenen (welke administraties!), sinds wanneer, hoe ontdekt, welke maatregelen
genomen. De audit-log en tijdlijnen van de module zijn de primaire bron.

**Stap 3 — Beoordelen risico (uur 4–24).** Coördinator beoordeelt: is er een risico voor de
rechten en vrijheden van betrokkenen? Vuistregels: alleen-intern + direct hersteld en
aantoonbaar geen toegang → registreren, mogelijk geen AP-melding; persoonsgegevens bij een
onbevoegde derde (verkeerde ontvanger, diefstal, inbraak) → melden; financiële gegevens/IBAN's
of BSN's betrokken → melden, en bij waarschijnlijk hoog risico óók betrokkenen informeren.
Twijfel = melden (de meldplicht kent geen boete op te voorzichtig melden).

**Stap 4 — AP-melding (binnen 72 uur na ontdekking).** Via het Meldloket datalekken van de
Autoriteit Persoonsgegevens. Nog niet alles bekend → voorlopige melding doen en aanvullen
(dat is expliciet toegestaan; de 72 uur niet laten verlopen omdat het beeld incompleet is).

**Stap 5 — Betrokkenen informeren (onverwijld, bij waarschijnlijk hoog risico).** In begrijpelijke
taal: wat is er gelekt, wat zijn de mogelijke gevolgen, wat doen wij, wat kunnen zij doen
(bv. alert zijn op phishing/spookfacturen — relevant bij gelekte IBAN's/factuurdata). Bij
klantadministraties: óók de klant (opdrachtgever) informeren, conform het tekstblok §4.7 in
document 3.

**Stap 6 — Evalueren (binnen 2 weken).** Oorzaak, structurele fix (regel/test/gate),
lessen vastleggen (verbeteringen-register), register-entry afronden.

## 4. Datalekregister (art. 33 lid 5 — verplicht, óók voor niet-gemelde lekken)

Bijhouden als doorlopend register (map `docs/avg/datalekregister/`, één bestand per incident):
datum ontdekking, omschrijving, betrokken gegevens/personen/administraties, risico-beoordeling
+ motivering wel/niet melden, AP-meldnummer, betrokkenen-communicatie, maatregelen, evaluatie.

## 5. De verwerker-keten

Anthropic, Google Cloud en Exact zijn contractueel (DPA) verplicht óns onverwijld te informeren
bij een inbreuk aan hun kant; onze 72-uursklok start dan bij hún melding aan ons. Controlepunt
bij DPA-acceptatie (checklist document 2): staat de meldtermijn van de verwerker erin en is het
meldkanaal bekend? Andersom geldt: een lek bij een verwerker ontslaat ons niet van onze eigen
melding aan AP/betrokkenen — wij blijven verantwoordelijke.

## 6. Oefening

Eén keer per jaar een tafeloefening (scenario: gestolen ontgrendelde accordeur-telefoon —
doorloop kill-switch, register, beoordeling). Datum laatste oefening: [nog niet gedaan].
