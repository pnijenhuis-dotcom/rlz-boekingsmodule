# Koppelvlak Vastgoedbeheer ↔ Reeleezee API-integratie (v2, 2026-07-03)

> **Doel:** het Reeleezee API-integratieproject volledig op de hoogte brengen van de vastgoedbeheer-
> module en het **contract** tussen beide vastleggen. Deze v2 bevat de afstemming ná jullie antwoord
> (`10_ANTWOORD_KOPPELING_REELEEZEE.md`) + de platformbeslissing. **Dit is de meest recente versie.**

## 1. Wat de vastgoedbeheer-module is (context)

Maatwerkvervanging van Bloxs voor ~200 objecten over ~8 eigenaar-entiteiten. Vier lagen:
- **Laag 0** PostgreSQL-datamodel (entiteit ↔ object ↔ eenheid ↔ huurder ↔ contract ↔ posten).
- **Laag 1** deterministische Python (indexatie, pro-rata facturatie, bankmatch, afschrijving) — getest.
- **Laag 2** integraties (PDOK, Kadaster/BAG, CBS-CPI, KvK, Mollie, AISP-bank, DocuSign, **Reeleezee**).
- **Laag 3** AI-agent (interface, MI-duiding) — later.

**Kernprincipes (hard):** code voor cijfers / AI voor taal / mens op de knop; Reeleezee = boekhoudbron,
wij boeken niets dubbel; object-identiteit = BAG-VBO-ID; mens-in-de-lus bij elke financiële actie en
twijfel-allocatie; geheimen via `.env`/secret-store.

## 2. De brug: pand = Reeleezee-project
- **Elk pand (object) = precies één RLZ-project.** Mapping staat aan **vastgoed-kant**:
  `object.reeleezee_project_id` (RLZ project-**GUID**, uniek, nullable tot gekoppeld).
- RLZ-project `Name` is vrije tekst → **geen BAG-id daarin**. RLZ kan projecten aanmaken en levert
  de GUID synchroon terug; die bewaren wij op het object.

## 3. Inbound — inkoopfacturen op pandniveau (push, geen polling)
RLZ **pusht** bij status "geboekt" een bericht (webhook/queue). Wij bouwen een beveiligd ontvangst-
endpoint dat per factuur(regel) verwerkt:
| Veld | Toelichting |
|---|---|
| `reeleezee_project_id` | bepaalt bij welk pand de kosten horen |
| `reeleezee_factuur_id` (GUID) | idempotentie-sleutel (UNIQUE) |
| `datum` | boekings-/factuurdatum |
| `bedrag` (excl/incl btw) | per regel |
| `grootboek` (Account+Description) + `kostensoort` | KPI-splitsing (onderhoud/GWE) |
| `leverancier`, `omschrijving` | context |

- **Allocatie:** project bekend → automatisch aan object; ontbreekt project of op entiteit → **mens bevestigt**.
- Voedt onderhoudslasten / afschrijving / KPI "onderhoud ÷ jaarhuur". Groot onderhoud → optioneel aan
  `onderhoud_uitvoering` (afschrijving); regulier = direct kosten.

## 4. Outbound — wat de vastgoedmodule naar RLZ schrijft
- **Huurfacturen → RLZ `SalesInvoices`** (regels met eigen grootboek + btw-code per regel; PDF-bijlage mogelijk).
- **Waarborgsom → RLZ `ManualJournals`** (memoriaal, balans, saldo 0, géén omzet).
- **Grootboek-mapping per administratie** via `Ledgers` (schema verschilt per administratie — niet hardcoden).
- **`Reference`-prefix `VGB-`** op ALLE documenten die wij schrijven → boekingsmodule herkent ze als
  reeds geboekt, pakt ze niet dubbel op. **Verplicht.**
- **Idempotent outbound:** deterministische GUID (UUIDv5 van contract+periode) + `Reference`.

## 5. Schrijfverdeling & eigenaarschap
- Vastgoed schrijft: huurfacturen, waarborg-memoriaal. Boekingsmodule schrijft: inkoop, bank, omzet.
- **Niemand muteert documenten van de ander** (correcties via de eigenaar van het document).
- **GB → kostensoort** (onderhoud/GWE-categorisering) is **onze** verantwoordelijkheid — niet in RLZ dupliceren.
- **Auth:** Basic Auth per administratie (8 entiteiten ≈ 8 logins), volledige boekhoudtoegang →
  credentials versleuteld in secret-store/.env.

## 6. Platform-fundament — BESLOTEN (2026-07-03)
**Gedeeld fundament, losse modules.** Vastgoedmodule en RLZ-boekingsmodule delen **één auth/identiteit,
één credential-store en één entiteiten-/klantregister**, maar blijven **apart deploybare modules** die via
dit koppelvlak communiceren. Reden: gedeelde data (8 entiteiten + RLZ-logins) op één plek = geen drift;
boekhoud-credentials op één versleutelde plek; beide projecten op één lijn; apart deploybaar = geen
monoliet. Geldt richting productie (fase 3/4); fase 1 draait standalone.

→ **VRAAG TERUG AAN RLZ-PROJECT:** wat houdt jullie "MI-dashboard-platformbeslissing" concreet in
(welke stack/host, welke identiteit- en credential-store)? De vastgoedmodule is
**Vite + React + FastAPI + PostgreSQL** — past dat op het gedeelde fundament, of moeten we iets verzoenen?

## 7. Datamodel-haken (gereserveerd aan vastgoed-kant)
- `object.reeleezee_project_id` (RLZ project-GUID, uniek).
- `inkoopfactuur` (id, object_id, `reeleezee_factuur_id` UNIQUE, datum, bedrag, btw, grootboek_code,
  kostensoort, leverancier, omschrijving, status, gekoppeld_op) → optioneel FK `onderhoud_uitvoering`.
- `grootboek_mapping` (administratie_id, grootboek_code ↔ rlz_ledger_guid) — config per administratie.
- `Reference`-conventie `VGB-<...>` op uitgaande documenten.

## 8. Nog te verifiëren (RLZ-kant)
Schrijfroute `Projects` (PUT), exacte rate limits, event-mechanisme (`CodeEventSubscriptions`), en de
waarborg-grootboekrekening (passief) per vastgoed-administratie vóór de eerste boeking.

## 9. Fasering
Koppeling = ná de verhuur-pilot. Nu alleen mapping + contract gereserveerd. Bloxs draait schaduw tot
fase 3 bewezen; Reeleezee blijft de boekhouding.
