uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-ter-accordering-bestaanscheck-intussen-extern-geboekt.md

Domeinen: accordering-native-app, duplicaten-crediteuren, reconciliatie, werkvoorraad-controlescherm

# OPDRACHT 22-09 — Documenten `ter_accordering` dagelijks opnieuw toetsen op "intussen buiten de module geboekt in RLZ/Odoo";
# bevinding mét handeling i.p.v. een geblokkeerde boekstap ná het laatste akkoord

**Casus (Peter 21-09 19:15, Bouwadvies Oost Nederland B.V., Beter Assemblage B.V., F/2026/01235, € 173,84, factuurdatum 26-08,
document 8c558b35-8b43-4f93-8cce-db00fb7de4ea):** harde checks doorstaan 16-09 09:13 → drie lagen akkoord (Peter N. 16-09, Sophia
Gerritsen 21-09 10:52, Kempen 21-09 19:15) → boeken geblokkeerd: RLZ-04-00000518 zelfde crediteur + referentie, "buiten de module".
Tussen 16-09 en 21-09 is de factuur rechtstreeks in Reeleezee geboekt. De module deed het juiste (geen dubbele boeking), maar drie
accordeurs hebben voor niets geklikt en Peter zag het pas als "Bug"-melding ná het laatste akkoord. Signaal kwam vijf dagen te laat.

## Opdracht
1. **Dagelijkse hercontrole (reconciliatieblok `documenten`, bestaande run):** voor élk document in `ter_accordering` (én
   `wacht_op_iban_accordering`, `klaar_om_te_boeken` ouder dan 1 dag) de RLZ-/Odoo-bestaanscheck opnieuw draaien (bestaande
   `extern_bestaan.zoek_extern_bestaand`, hergebruik van de checks-cache is hier NIET toegestaan — dit is juist de vers-toets).
   Treffer buiten de module → bevinding `intussen_extern_geboekt` (start in `meten`? NEE: dit is een bestaande harde-check-soort met
   een bestaand boekstuk als bewijs, dus direct actie-bevinding mét actiemail) mét op de rij: boekstuk, bedrag, datum, en twee
   knoppen: **"Afwijzen — al geboekt als ‹RLZ-04-…›"** (= bestaande afwijs-route mét voorgevulde reden, accordering intrekken mét
   tijdlijnregel naar de accordeurs "niet meer nodig: al geboekt in Reeleezee") en **"Toch verschillend — doorgaan"** (bestaande
   duplicaat-bevestiging, audit). Rate-limit: één RLZ-call per document per dag, gebundeld per administratie (throttling client).
2. **Accordeur-app:** een document waarvan de bevinding openstaat toont in de app de banner "Al geboekt in Reeleezee (RLZ-04-…) —
   kantoor beoordeelt; akkoord niet nodig" en verdwijnt uit "Te accorderen" tot het kantoor kiest (nooit stil: telt in "Wachten op
   kantoor"). Push-/mailherinnering voor dat document wordt onderdrukt (guard-test).
3. **Bij boeken ná het laatste akkoord** blijft de blokkade (regel accordering 1), maar de foutmelding krijgt dezelfde twee knoppen
   i.p.v. proza ("Los de oorzaak op en boek opnieuw"), en het woord "Bug" komt nergens in klanttekst voor (copy-check).
4. **Meting (lees-only, leesreplica + RLZ GET onder nameting@):** hoeveel documenten staan nu `ter_accordering` waarvan de referentie
   al in RLZ/Odoo staat (alle administraties)? Rapporttabel administratie × crediteur × referentie × bedrag × RLZ-boekstuk × sinds.
   Voor Bouwadvies óók: wie boekte RLZ-04-00000518 (RLZ `CreatedBy`/`ModifiedBy` als leesbaar; anders "niet leesbaar via API") —
   Peter wil weten of een collega buiten de module om werkt.
5. Tests: hercontrole vindt treffer → bevinding + intrekking; geen treffer → niets; storing = geen bevinding en zichtbaar overgeslagen;
   app-banner; herinnering onderdrukt. Rapport + INDEX + Gelezen regels; BESLISSINGEN "TER ACCORDERING — DAGELIJKSE
   BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)"; regels accordering + duplicaten; WAT_IS_NIEUW; CLAUDE.md één regel.
