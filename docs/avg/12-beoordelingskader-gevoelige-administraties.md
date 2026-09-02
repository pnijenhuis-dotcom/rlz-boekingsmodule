# Beoordelingskader gevoelige administraties — criteria + voorstel-classificatie

> **Status: BESLOTEN 2026-09-02 (Peter, vervolgronde 02-09): ALLE administraties AAN — inclusief
> Mantelzorgwoningen Midden Nederland en Stichting Shuto.** Motivering Peter: in deze administraties
> zit geen zorg-/gevoelig-gerelateerd materiaal — de facturen zijn zakelijk (B2B-inkoop); doel is
> menselijk werk besparen, automatisering is de norm. Beide rijen zijn daarmee categorie D (geen A);
> de fail-closed twijfelregel uit §1 is voor deze twee rijen door het klantoordeel van Peter
> beslecht. Alleen de test-seed blijft het advies UIT (hygiëne, geen besluitpunt). Oorspronkelijk
> voorstel (2× UIT tot bevestiging) blijft hieronder leesbaar als historie. Invulling van DPIA doc 4 §5.4
> ("per administratie beoordelen of de AI-gate uit moet blijven zolang geen aanvullende afspraak
> met de klant bestaat") en van de checklist-regel "Gevoelige administraties gemarkeerd". De
> sector per administratie is afgeleid uit naam, registers en verkenningen — **waar dat een
> aanname is staat "te bevestigen"**; de classificatie wordt pas definitief door Peters paraaf in
> de laatste kolom. Feitelijke gate-stand = cloud-DB 02-09 (doc 5 "Feitelijke stand").

## 1. Criteria

| Code | Criterium | Uitwerking | Gevolg voor de AI-gate |
|---|---|---|---|
| **A** | **Bijzondere categorieën (art. 9/10 AVG) te verwachten in de documentstroom** | Zorg/gezondheid, levensbeschouwing/religie, strafrecht/advocatuur, vakbond, seksuele gerichtheid, etnische afkomst. Toets: kunnen inkoopfacturen, mail-teksten of contracten van deze klant *structureel* zulke gegevens over herkenbare personen bevatten (bv. zorgfacturen op naam van een bewoner, facturen van een kerkgenootschap met ledenlijsten, advocaatdeclaraties met dossiernaam)? | **UIT** tot er een aanvullende afspraak met de klant is (schriftelijk, mét de klantinformatietekst doc 11) én de DPIA §6-heroverweging is gedaan. Handmatige verwerking blijft mogelijk. |
| **B** | **Consumenten als betrokkenen op schaal** | Huurders, recreatiegasten, particuliere afnemers: veel natuurlijke personen die geen partij zijn bij onze opdracht. Geen bijzondere categorieën, wel volume en informatieplicht (doc 3 §4 punt 5: klant informeert zijn betrokkenen). | **AAN mág**, mits klant geïnformeerd (doc 11) en dataminimalisatie geborgd (alleen documentinhoud; BSN-filter). Extra: bij Vastly-koppeling gaan huurdersnamen óók via de UBL-route — dat pad is deterministisch, geen AI. |
| **C** | **Veldwerkers-/persoonsdossiers in de keten** | Steigerbouw: urenstaten met namen van ZZP'ers, ZZP-dossiers (kopie ID, VCA, KvK-uittreksel). | **AAN mág** voor facturen; **dossierdocumenten gaan nooit door de AI** (BSN-regel, `app/uren/dossier` — kopie ID nooit extraheren/indexeren; borging bevestigd in BESLISSINGEN "STEIGERBOUW-RUN 25-08 blok A"). Controlepunt bij elke nieuwe upload-ingang: dossier-uploads mogen niet in `upload_document` landen. |
| **D** | **Standaard zakelijk (B2B)** | Inkoopfacturen tussen ondernemingen; betrokkenen = contactpersonen/eenmanszaak-eigenaren. Het basisscenario van DPIA doc 4. | **AAN** binnen het getoetste pakket. |
| **E** | **Eigen entiteit / test** | Kantoor-administratie, seed-/testadministraties zonder echte klantdata. | AAN toegestaan; testadministraties bij voorkeur UIT (hygiëne: geen onnodige calls). |
| **+R** | **Reputatiegevoelige branche (modifier)** | Geen AVG-categorie, wel een klantverwachting (bv. coffeeshop: personeel en leveranciers hechten aan discretie). | Geen gate-gevolg; wel expliciet informeren (doc 11) en desgewenst de klant de keuze "handmatig" bieden. |

Beslisregel: hoogste letter wint (A > B/C > D > E). Bij twijfel tussen A en B: **A** (twijfel =
UIT) tot Peter de aard van de klant bevestigt — dezelfde fail-closed-lijn als overal in de module.

## 2. Voorstel-classificatie per administratie (stand cloud-DB 02-09, 31 rijen)

Kolom "gate nu" = `platform.administratie.ai_extractie_ingeschakeld` op 02-09. Kolom "voorstel"
= wat dit kader adviseert. Kolom "actie" = het klikwerk als Peter het voorstel overneemt.
Kolom "geïnformeerd" is de logplek voor doc 11 (datum/kanaal) — leeg tot verzending.

| Administratie | Sector (bron) | Cat. | Gate nu | Voorstel | Actie / opmerking | Geïnformeerd | Besluit Peter |
|---|---|---|---|---|---|---|---|
| Mantelzorgwoningen Midden Nederland | Verhuur van mantelzorgwoningen (naam; doorbelasting-doel Kempen) | **D** (was A?/B) | AAN | **AAN** | Voorstel was "UIT tot bevestiging"; Peter bevestigde 02-09: géén documenten met bewoner-/zorggegevens — de inkoopstroom is zakelijk (facturen aan de BV), geen zorgcontext van herkenbare personen. Blijft: klantinfo (doc 11) sturen. | | ☑ 02-09 AAN |
| Stichting Shuto | Stichting; documentstroom zakelijk (bevestigd Peter 02-09) | **D** (was A?/D) | AAN | **AAN** | Voorstel was "UIT tot bevestiging"; Peter bevestigde 02-09: geen levensbeschouwelijk/zorg-materiaal, facturen zijn zakelijk. Vastly-kandidaat (register). | | ☑ 02-09 AAN |
| BLOw B.V | Coffeeshop (register) | D +R | AAN | AAN | Kassarapporten zonder derden-PII (V3); inkoop B2B. Reputatie-modifier: expliciet informeren, keuze bieden. | | ☐ |
| B. van Rooijen / G. Schaalje | Natuurlijke personen als naam (VOF/maatschap? te bevestigen) | D (B?) | AAN | AAN | Betrokkenen zijn de eigenaren zelf; controleren dat er geen privé-/medische facturen meelopen (dan A). Vastly-vlag staat AAN in de DB → mogelijk verhuur → B. | | ☐ |
| Caravanpark "De Visotter" B.V. | Recreatie/camping (Odoo-verkenning) | B | AAN | AAN mét info | Gasten = consumenten; inkoopfacturen zelf zijn B2B. | | ☐ |
| Kempen Facilities B.V. | Groepsentiteit, doorbelasting-bron (recreatie/vastgoedgroep) | B/D | AAN | AAN mét info | Doorbelasting → documenten raken meerdere entiteiten; klantinfo dekt de groep in één brief. | | ☐ |
| Molenhof Beheer B.V. | Groepsentiteit (recreatie/vastgoed) | B | AAN | AAN mét info | idem | | ☐ |
| Molenhof Verhuur B.V. | Verhuur (recreatie) | B | AAN | AAN mét info | huurders/gasten | | ☐ |
| Oirschot Recreatie B.V. | Recreatie | B | AAN | AAN mét info | gasten | | ☐ |
| Oirschot Vastgoed Beheer B.V. | Vastgoedbeheer | B | AAN | AAN mét info | huurders | | ☐ |
| Veldhoven Recreatie B.V. | Recreatie | B | AAN | AAN mét info | gasten | | ☐ |
| Rubicon Investments B.V. | Eigen vastgoed, Vastly (register) | B | AAN | AAN mét info | huurders via Vastly-UBL (deterministisch) + inkoop-PDF's (AI) | | ☐ |
| ARVUM B.V. | Kantoorklant, Vastly-kandidaat (register) | B/D | AAN | AAN mét info | | | ☐ |
| Beleggingsmaatschappij Meyer BV | Vastly-kandidaat (register) | B/D | AAN | AAN mét info | | | ☐ |
| J.G.M. Elissen Holding BV | Vastly-kandidaat (register) | B/D | AAN | AAN mét info | | | ☐ |
| Universal Steigerbouw B.V. | Steigerbouw, projectadministratie, voorraad, uren & meerwerk | C | AAN | AAN | Dossierdocumenten buiten AI (borging bestaand); voorraad-normalisatie + contract-ontleding → registeraanvulling doc 10 §4 vóór klantinfo. | | ☐ |
| Universal Nederland B.V. | Universal-groep, voorraad | C/D | AAN | AAN | | | ☐ |
| Universal Verkoop B.V. | Universal-groep, voorraad (ook Odoo) | C/D | AAN | AAN | | | ☐ |
| Bradwolff Constructie B.V. | Constructie/steigerbouw, voorraad | C/D | AAN | AAN | | | ☐ |
| BWC Steigers B.V. | Steigers, voorraad | C/D | AAN | AAN | | | ☐ |
| 6-Steps Projectbeheersing | Zakelijke dienstverlening | D | AAN | AAN | | | ☐ |
| Bouwadvies Oost Nederland B.V. | Bouwadvies | D | AAN | AAN | | | ☐ |
| T&J Hoveniers | Hoveniersbedrijf | D | AAN | AAN | particuliere klanten van de hovenier verschijnen hooguit op zíjn verkoopfacturen, niet in onze inkoopstroom | | ☐ |
| Adda Import-Export | Handel | D | AAN | AAN | | | ☐ |
| Abbegaa B.V. | Onbekend (geen facturatiemodule in RLZ) | D? | AAN | AAN | sector te bevestigen | | ☐ |
| A.Y. Holding BV | Holding | D | AAN | AAN | | | ☐ |
| A.Y. Holding 2 B.V. | Holding (geen facturatiemodule) | D | AAN | AAN | | | ☐ |
| Zilver Beheer B.V. | Beheer/holding | D | AAN | AAN | | | ☐ |
| Administratiekantoor Nijenhuis C.V. | Eigen kantoor-administratie | E (D) | AAN | AAN | kantoorfacturen kunnen klantnamen dragen; geen aanvullende afspraak nodig (eigen entiteit) | n.v.t. | ☐ |
| Test-administratie (passkey-test) | Seed, `rlz_admin_id = SEED-PASSKEYTEST` | E | AAN | **UIT** | geen echte data; gate uit = hygiëne (geen calls, geen ruis in de kostenmeter) | n.v.t. | ☐ |
| Administratiekantoor Nijenhuis (test) | Gearchiveerd 30-08 | E | UIT | UIT | al uit; gearchiveerd | n.v.t. | — |

Telling voorstel (02-09 ochtend): 2× UIT tot bevestiging (A?), 1× UIT (test-seed), 27× AAN, 1×
gearchiveerd/uit. **Telling ná besluit Peter (02-09 avond): 29× AAN (alle actieve
klantadministraties, waarvan 13 "mét info" wegens consument-betrokkenen), 1× UIT-advies (test-seed,
hygiëne), 1× gearchiveerd/uit — geen enkele administratie UIT om AVG-redenen.** De overige rijen
zijn met dit besluit impliciet bevestigd op "AAN" (Peter: automatisering is de norm); de kolom
"Besluit Peter" per rij blijft de plek voor een eventuele latere herziening.

## 3. Wat er gebeurt ná Peters besluit

1. Per rij "UIT": n.v.t. ná het besluit van 02-09 (alle klantadministraties AAN — de feitelijke
   cloud-stand van 02-09 is dus al de besloten stand; geen toggle-klikwerk). Zou een rij later
   alsnog UIT moeten: Beheerder-toggle op de administratie-detailpagina (tab Boeken & AI) → audit
   oud→nieuw; documenten gaan dan naar `handmatig_afmaken` (bestaand gedrag). Geen migratie, geen code.
2. Per rij "AAN mét info": brief doc 11 versturen, datum/kanaal in kolom "geïnformeerd".
3. Kolom "Besluit Peter" afvinken; daarna in `05-activatie-checklist.md` de regel "Gevoelige
   administraties gemarkeerd" afvinken met verwijzing naar dit document + datum.
4. **Structurele borging (voorstel, code — buiten dit blok):** de wizard toont bij "Administratie
   toevoegen" één verplichte keuze "Gevoelige documentstroom? (zorg/religie/advocatuur/…)"; ja =
   AI-extractie default UIT + chip "AI uit — gevoelig", nee = de huidige default AAN. Daarmee
   blijft dit kader ook voor de volgende administratie gelden zonder handmatige nazorg.
5. Heroverweging DPIA §6: zodra één A-administratie AAN gaat (na aanvullende afspraak) is de
   heroverwegingstrigger geraakt → jurist.
