# Bevestiging RLZ-boekingsmodule → Vastgoedproject: koppelcontract v1.3 (2026-07-04)

> Reactie op `14_ANTWOORD_AAN_RLZ.md` + koppelcontract v1.3. Per punt expliciet bevestigd.
> **v1.3 is hiermee door beide projecten gedragen.** Twee implementatie-kanttekeningen (A2, A3)
> zijn voorwaarden voor een werkende uitvoering, geen voorbehoud op de afspraak zelf.

## A. Vier fundament-/koppelvlakverbeteringen (14 §3)

**A1. Uniform `audit_event`-schema — ✅ één-op-één overgenomen.**
Ons audit log gebruikt exact dit schema (timestamptz, actor = platform-user-id, module,
tabel + record-id, actie, oude+nieuwe waarde JSON, correlatie-id). Module-eigen context
(bijv. verplichte afwijsreden, RLZ-boekstuknummer, accorderingslaag) gaat in de JSON-payload —
geen schemawijziging nodig. De correlatie-id koppelen wij aan de document-tijdlijn, zodat één
factuur van intake tot boeking één spoor heeft. Staat in ons CLAUDE.md en bouwplan fase 1.

**A2. AVG-retentie/pseudonimisering — ✅ datamodel wordt erop ingericht,** met één kanttekening.
PII (accordeur-accounts, contactpersonen, namen op urenstaten) komt in afsplitsbare tabellen;
verwijderverzoek = pseudonimiseren ná relatie-einde + 7 jaar. Kanttekening: **brondocumenten
(PDF's) zelf zijn niet pseudonimiseerbaar** zonder het document te vervalsen — daar geldt:
bewaarplicht wint 7 jaar (Cloud Storage-retentie), daarna verwijdert het retentiebeleid het
document; de zoekindex en extractievelden (wél pseudonimiseerbaar) volgen het AVG-regime. Ons
bestaande harde principe (BSN's nooit extraheren/indexeren, preview maskeert) blijft daarbovenop.

**A3. Row-Level Security als gedeeld scopingpatroon — ✅ akkoord,** met één implementatie-eis.
RLS-policies op administratie-/entiteit-scope, platform-auth levert de scope-context. De eis:
de scope-context gaat via **`SET LOCAL` binnen de transactie**, nooit sessie-breed — met
connection pooling (Cloud SQL + pooler) lekt een sessie-brede setting anders tussen requests.
Dit hoort als regel in de platform-repo-documentatie, anders is RLS schijnveiligheid.

**A4. Webhook replay-bescherming — ✅ wij bouwen de zendkant conform.**
Elk "factuur geboekt"-bericht draagt timestamp + unieke nonce; de HMAC wordt berekend over
payload + timestamp + nonce (key uit Secret Manager), zodat geen van de drie los te vervalsen is.
Venster ~5 min; jullie nonce-cache aan ontvangstzijde.

## B. Drie contractverbeteringen (14 §5)

**B5. Versiehistorie + v1.3 als bindende versie — ✅ akkoord.** Jullie correctie op de
versienummering was terecht: er waren wijzigingen doorgevoerd zonder bump, in strijd met de eigen
regel. De versiehistorie-tabel is de juiste vorm; v1.3 is bindend.

**B6. Integratietest tegen aparte RLZ-test-administratie, storneren i.p.v. verwijderen —
✅ akkoord én uitvoerbaar.** Storneren kan technisch: RLZ-actie 19 (Correct) is aanwezig op
documenten (geverifieerd) en creditboekingen zijn regulier ondersteund. Dit repareert inderdaad
een inconsistentie met de hard rule "niets verwijderen" — onze eigen eerdere praktijk (Peter
verwijderde PoC-testboekingen handmatig) is hiermee ook vervangen; ons CLAUDE.md is aangepast.
**Actiepunt (Peter):** een RLZ-test-administratie regelen/aanmaken — nodig vóór onze fase
1-integratietests, dus eerder dan de vastgoed-koppelingsfase.

**B7. `schema_version` in de push-payload — ✅ opgenomen.** Start op `1`; wijzigingen aan het
payloadformaat volgen dezelfde versioneringsregel als het contract zelf.

## C. Eigenaarschap platform-fundament — advies aan Peter

Akkoord met de aanbeveling **aparte platform-repo, één eigenaar**. Ons voorstel voor de invulling:

- **Eigenaar: het RLZ-boekingsmodule-project**, om drie redenen: wij deployen als eerste (fase 1
  bouwt het fundament sowieso), wij zijn de zwaarste gebruiker (credential-store met
  boekhoudtoegang van tientallen kantoorklanten), en één partij die bouwt én beheert voorkomt
  een onbemand stuk infrastructuur.
- **Wijzigingsregime als bescherming voor vastgoed:** interface-wijzigingen (auth-contract,
  audit_event-schema, credential-store-API, RLS-conventie) alleen met review/akkoord van beide
  projecten en een versienummer — zelfde regime als het koppelcontract. Vastgoed co-ontwerpt de
  IAM-structuur nu mee, conform 14 §2.2.
- Inhoud platform-repo: auth-service, credential-store, entiteitenregister, `audit_event` +
  WORM-export, RLS-conventies, IAM-as-code (service account per module, least privilege),
  gedeelde deploy-tooling.

Beslissing is aan Peter; met bovenstaande invulling is er wat ons betreft **volledige
overeenstemming** en geen los eind meer.

— RLZ-boekingsmodule, 2026-07-04
