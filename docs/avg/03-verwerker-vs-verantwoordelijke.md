# Verwerker vs. verwerkingsverantwoordelijke — rolbepaling per dienst

> ✅ **Getoetst — jurist-akkoord 2026-08-12** (intern opgesteld, juridische toetsing afgerond
> — zie `docs/BESLISSINGEN.md` "AVG-compliance"). De rolbepaling volgt de
> branche-richtsnoeren; de conclusie én het tekstblok in §4 zijn juridisch getoetst en
> bruikbaar richting klanten.

## 1. Kader

De brancheorganisaties (NBA, NOB, RB, NOAB, NIRPA) hebben in de "Richtsnoeren AVG voor
accountants, belastingadviseurs en salarisprofessionals" per dienst uitgewerkt wanneer een
kantoor **zelfstandig verwerkingsverantwoordelijke** dan wel **verwerker** is:

- Richtsnoeren (PDF, versie oktober 2019): <https://www.nob.net/wp-content/uploads/2023/09/richtsnoeren_verwerkingsverantwoordelijke_of_verwerker_versie_1_oktober_2019-3.pdf>
- NBA-toelichting + modelovereenkomst: <https://www.nba.nl/tools-en-voorbeelden/model-bewerkersovereenkomst/>
- Samenvatting: <https://privacyzeker.nl/avg-privacy-kennisbank/richtsnoeren-avg-voor-accountants-belastingadviseurs-en-salarisprofessionals/>

Kernredenering: wie zelf — binnen wettelijke en beroepsnormen — doel en middelen van de
verwerking bepaalt, is verantwoordelijke. Een administratiekantoor dat de administratie voert,
samenstelt en aangiften verzorgt, doet dat onder eigen vakinhoudelijke verantwoordelijkheid en
wettelijke normen (AWR, beroepsregels) en is daarmee doorgaans **geen** verwerker van de klant.

## 2. Rolbepaling per dienst van het kantoor

| Dienst | Rol kantoor | Toelichting |
|---|---|---|
| Administratievoering / boekhouding (dít is wat de module doet: inkoop, omzet, verkoop, bank, accordering) | **Zelfstandig verwerkingsverantwoordelijke** | Het kantoor bepaalt binnen wettelijke/professionele normen hoe de administratie wordt gevoerd; de klant geeft geen instructies over middelen. Conform de richtsnoeren |
| Fiscale aangiften | **Zelfstandig verwerkingsverantwoordelijke** | Eigen wettelijke taak en vaktechnische verantwoordelijkheid |
| Salarisverwerking (buiten deze module) | Afhankelijk van de invulling: puur uitvoerend op instructie → **verwerker**; met eigen advies-/beoordelingsruimte → verantwoordelijke | Per klant beoordelen volgens de richtsnoeren; alleen bij de verwerker-variant is een verwerkersovereenkomst mét de klant nodig |
| Klant-accordeurs die in de module inloggen | Kantoor blijft verantwoordelijke | De accordeur handelt namens de klant binnen het proces van het kantoor |

## 3. Consequenties

1. **Geen verwerkersovereenkomst met klanten nodig** voor de administratievoering — het
   kantoor is daarvoor geen verwerker. Wél geldt de normale informatieplicht
   (art. 13/14 AVG): klanten en hun betrokkenen moeten weten wat het kantoor met de gegevens
   doet. Dat regelt het tekstblok in §4 (opnemen in de opdrachtvoorwaarden/-bevestiging) plus
   een privacyverklaring van het kantoor.
2. **Anthropic, Google Cloud en Exact Reeleezee zijn verwerkers ván het kantoor** (art. 28
   AVG) — met elk van hen moet een DPA staan (zie
   [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md)). Ze zijn formeel geen
   "subverwerkers", want het kantoor is geen verwerker; hun eigen onderaannemers zijn dat wel
   (hun subverwerkerslijsten archiveren).
3. **Eigen verplichtingen van het kantoor als verantwoordelijke**: verwerkingsregister
   (document 1), beveiliging (art. 32 — grotendeels gebouwd, zie register §8), meldplicht
   datalekken (procedure kantoorbreed beleggen — nog niet in dit pakket), rechten van
   betrokkenen, en een DPIA-afweging voor de AI-extractie (document 4).
4. **Als het kantoor voor een specifieke dienst tóch verwerker is** (bv. pure
   salarisverwerking): dan verwerkersovereenkomst met die klant sluiten (NBA-model als basis)
   en zijn Anthropic/Google op dat deel subverwerkers — die moeten dan in de
   verwerkersovereenkomst met de klant als subverwerker zijn toegestaan. Die dienst loopt nu
   niet door deze module.

## 4. Concept-tekstblok voor de klantovereenkomst (bijlage bij de opdrachtvoorwaarden)

> ✅ Getoetst — jurist-akkoord 2026-08-12 (toetsvraag 2); bruikbaar richting klanten.

---

**Bijlage: Verwerking van persoonsgegevens**

1. **Rol.** Opdrachtnemer (Administratiekantoor Nijenhuis) verwerkt bij de uitvoering van de
   opdracht (administratievoering, verwerking van in- en verkoopfacturen, bankmutaties en
   aangiften) persoonsgegevens als zelfstandig verwerkingsverantwoordelijke in de zin van de
   AVG. Er is voor deze dienstverlening dan ook geen verwerkersovereenkomst tussen partijen
   vereist.
2. **Doel en grondslag.** De gegevens worden uitsluitend verwerkt voor het voeren van de
   administratie van opdrachtgever, het voldoen aan wettelijke (fiscale) verplichtingen en de
   daarbij horende verantwoording.
3. **Hulpmiddelen en dienstverleners.** Opdrachtnemer gebruikt daarbij:
   (a) het boekhoudpakket Exact Reeleezee;
   (b) beveiligde cloudinfrastructuur van Google Cloud in de regio Nederland/EU;
   (c) AI-ondersteunde documentherkenning (Anthropic, Verenigde Staten) voor het voorlezen
   van factuurgegevens — uitsluitend ter voorbereiding; iedere boeking wordt door een
   medewerker gecontroleerd en er worden geen burgerservicenummers door de AI verwerkt of
   opgeslagen. Met alle dienstverleners zijn verwerkersovereenkomsten met passende waarborgen
   (waaronder EU-modelcontractbepalingen) gesloten.
4. **Bewaartermijn.** Administratieve gegevens worden bewaard gedurende de wettelijke
   bewaartermijn van zeven jaar. Na afloop van de relatie en die termijn worden
   persoonsgegevens gepseudonimiseerd.
5. **Betrokkenen.** Opdrachtgever staat ervoor in dat hij de personen van wie hij gegevens
   aanlevert (medewerkers, leveranciers, afnemers/huurders) waar nodig informeert over deze
   verwerking. Verzoeken van betrokkenen (inzage, correctie, bezwaar) kunnen via
   opdrachtnemer worden ingediend; wettelijke bewaarplichten kunnen aan verwijdering in de
   weg staan.
6. **Beveiliging.** Opdrachtnemer treft passende technische en organisatorische maatregelen,
   waaronder tweefactorauthenticatie, versleutelde opslag van toegangsgegevens,
   toegangsbeperking per administratie en een volledig controlespoor van alle handelingen.
7. **Datalekken.** Opdrachtnemer informeert opdrachtgever onverwijld over een inbreuk in
   verband met persoonsgegevens die (mede) gegevens van opdrachtgever betreft.

---
