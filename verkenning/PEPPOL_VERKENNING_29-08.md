# Peppol / e-facturatie — verkenning (29-08-2026, Cowork)

Akkoord Peter 29-08 (benchmark-aanbeveling 3). Doel: weten wat er op ons afkomt en welke
aansluitroute past, zodat we op tijd kunnen beslissen — geen bouw nu.

## Tijdlijn en verplichtingen

- **EU (ViDA)**: e-facturatie verplicht voor **grensoverschrijdende** B2B-transacties per
  **1 juli 2030**. Binnenlands mogen lidstaten zelf kiezen.
- **Nederland**: nog géén binnenlands besluit. Verwacht pad: wetsvoorstel/consultatie
  ~2027, wet ~2028, gefaseerde invoering vanaf ~2030 (grote bedrijven eerst). Peppol is
  in NL het aangewezen netwerk (overheid gebruikt het al via Digipoort).
- **België**: B2B-verplichting al per 1 jan 2026 — relevant als klanten Belgische
  afnemers/leveranciers krijgen; sommige NL-leveranciers gaan daardoor nu al via Peppol
  versturen.

## Wat het voor de module betekent

1. **Ontvangen (eerst)**: Peppol wordt een extra intake-kanaal naast facturen@ — een
   accesspoint levert inkomende UBL's af (API/webhook), die exact ons bestaande
   UBL-intakepad in kunnen (tenaamstelling-routing, NLCIUS-validatie, verzamelbak-
   failsafe). Bouwtechnisch klein zodra de provider er is.
2. **Versturen (later)**: onze verkoop-/doorbelastingsfacturen (Vastly-facturen komen al
   als UBL binnen) via Peppol versturen i.p.v. mail/PDF. Pas relevant richting 2030 of
   als afnemers erom vragen.
3. **Registratie**: per administratie een Peppol-participant-ID (KvK-nummer-gebaseerd);
   registratie loopt via het accesspoint. Onze administraties hebben de KvK-gegevens al.

## Aansluitroute

Zelf accesspoint worden is onzinnig (certificering NPa, beheer). Route = **aansluiten op
een bestaand NPa-gecertificeerd accesspoint mét API** (per-document- of maandprijs;
prijzen variëren sterk per provider — vergelijken bij besluit). Selectiecriteria: REST-API
+ webhook voor inkomend, prijs per document, NPa-certificering, multi-entiteit
(20+ administraties onder één contract), NLCIUS/Peppol BIS 3.0.

## Advies

- **Nu**: niets bouwen; dit document is de beslisbasis.
- **Trigger om te starten**: (a) een klant krijgt Peppol-facturen van leveranciers,
  (b) Belgische handelsrelaties, of (c) NL-wetsvoorstel wordt concreet (~2027).
- **Dan**: provider kiezen → ontvangen-kanaal eerst (klein), verzenden later.

Bronnen: peppol.nl (kosten/eindgebruiker), peppol.nu (ViDA-tijdlijn NL, accesspoints
vergelijken), Wolters Kluwer (e-invoicing vóór 2030), wefact/acumulus (VIDA 2030),
bedrijfssoftwaregids.nl (Peppol 2026 — NB: de "verplicht 2026"-claim geldt België, niet NL).
