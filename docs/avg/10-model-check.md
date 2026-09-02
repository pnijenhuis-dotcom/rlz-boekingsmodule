# Model-check — welke AI-modellen roept de code feitelijk aan, en dekken register/DPA dat?

> **Status: UITGEVOERD 2026-09-02 (blok A AVG-afronding).** Bron A = code (`grep` over
> `backend/app`, exclusief tests), bron B = de productie-kostenmeter `platform.ai_gebruik`
> (read-only query op de cloud-DB via de Auth Proxy, 02-09 ±20:30 NL), bron C = de AVG-documenten
> (register doc 1, checklist doc 2, DPIA doc 4, PDL-VWO doc 7 Bijlage B). Afwijkingen staan in §4
> — **niet stil hersteld**, wél benoemd met voorstel. Herhalen bij élke modelwissel of nieuw AI-pad
> (opgenomen als vaste regel in `05-activatie-checklist.md` stap 1).

## 1. Modellen en aanroepplekken in de code

Eén client (`app/extractie/client.py::ClaudeExtractieClient`), model = constructor-argument of
`settings.ai_extractie_model`. Twee settings bepalen álle modellen:

| Setting | Default | Gebruikt door |
|---|---|---|
| `ai_extractie_model` | `claude-sonnet-5` | alle extractie-/normalisatiepaden hieronder |
| `bewaking_ai_model` | `claude-haiku-4-5` | uitsluitend de uurlijkse bewakings-zelftest |

Aanroepplekken (elk mét een `AiVerbruikReferentie(bron=…)` — dat is de sleutel waarop de
kostenmeter logt):

| bron (kostenmeter) | Code | Wat gaat er naar de API | Gate | Register-dekking |
|---|---|---|---|---|
| `inkoop_extractie` | `documenten/service.py:681` → `extractie/service.py` | inkoopfactuur-PDF (base64) + mail-body-hint (BSN-gefilterd) | per administratie `ai_extractie_ingeschakeld` + platformgate + kostenpoort | **V1** (model expliciet genoemd) |
| `rapport_extractie` | `documenten/service.py:750` → `extractie/rapport.py` | kassarapport-PDF | idem | **V3** |
| `intake_splitsing` | `intake/verwerking.py:486` → `extractie/splitsing.py` | nog niet toegewezen mail-PDF (tenaamstelling + factuurgrenzen) | platformgate `intake_ai_ingeschakeld` + kostenpoort | **V2** |
| `intake_herlezen` | `intake/herlezen.py:184` (nazorg-CLI 02-09) | idem als splitsing, opnieuw | idem | V2 (zelfde verwerking, nieuwe bron-label) |
| `contract_ontleding` | `projecten/ontleding.py:90` → `extractie/contract.py` | contract-/offerte-PDF van een project (steigerbouw) | per administratie `ai_extractie_ingeschakeld` + kostenpoort | **ONTBREEKT** (§4.1) |
| `voorraad_normalisatie` | `voorraad/normalisatie.py:375` (`vraag_json`, tekst-only) | regelteksten van inkoop-/verkoopfactuurregels (artikelomschrijvingen, batches van 40) | per administratie `ai_extractie_ingeschakeld` + kostenpoort | **ONTBREEKT** (§4.2) |
| `bewaking` | `bewaking/service.py:181` (`vraag_json`, haiku) | synthetische zelftest-prompt, géén klant- of persoonsgegevens | kostenpoort | n.v.t. — geen persoonsgegevens (§4.3) |

Geen andere `anthropic.Anthropic(`-instantie in de code; geen Files API, Batch API of
Managed Agents. Het inkoopschema is sentinel-gebaseerd (bugfix 31-08), de schema-poort telt
live ≤ 16 union-parameters.

## 2. Wat de productie feitelijk aanriep (kostenmeter, cloud-DB, stand 02-09)

| model | bron | calls | periode | kosten (meter) |
|---|---|---|---|---|
| `claude-sonnet-5` | `inkoop_extractie` | 525 | 18-08 → 02-09 | € 21,57 |
| `claude-sonnet-5` | `intake_splitsing` | 733 | 25-08 → 02-09 | € 13,64 |
| `claude-sonnet-5` | `voorraad_normalisatie` | 226 | 29-08 → 02-09 | € 2,84 |
| `claude-sonnet-5` | `intake_herlezen` | 3 | 02-09 | € 0,04 |
| `claude-haiku-4-5` | `bewaking` | 13 | 02-09 | € 0,00 |

Per maand: augustus 510 calls / € 9,71 (alleen sonnet-5); september t/m 02-09 977 sonnet-calls
/ € 28,38 + 13 haiku-calls. **Nog nooit in productie aangeroepen:** `rapport_extractie` (omzet)
en `contract_ontleding` (projecten). Geen enkel ander model dan de twee uit §1 — de
config-defaults zijn dus ook de werkelijkheid.

## 3. Wat de AVG-documenten dekken

- **Register (doc 1):** V1 noemt `claude-sonnet-5` expliciet als model bij Anthropic; V2 en V3
  verwijzen naar dezelfde gate/verwerker. Geen V-rij voor de projectenmodule (contract-ontleding)
  en geen V-rij voor de voorraad-aansluiting (`mi`-schema, normalisatie van artikelregels).
- **DPA / Commercial Terms (doc 2, checklist A):** model-agnostisch — de DPA geldt voor de
  API als geheel. Er is dus geen contractuele afwijking door het gebruik van `claude-haiku-4-5`
  náást `claude-sonnet-5`; wel noemt checklist A alleen sonnet.
- **PDL-VWO Bijlage B (doc 7):** "AI-ondersteunde gegevensextractie uit administratiedocumenten
  (Claude API)" — dekt extractie en splitsing; "voorraad-normalisatie" en "contract-ontleding"
  vallen taalkundig onder "administratiedocumenten", maar staan niet benoemd.
- **DPIA (doc 4):** beoordeelt de AI-extractie op facturen; R7 ("uitbreiding van de
  AI-toepassing") is exact het heroverwegingscriterium dat door voorraad-normalisatie en
  contract-ontleding wordt geraakt.
- **ZDR (doc 9):** `claude-sonnet-5` en `claude-haiku-4-5` zijn géén "Covered Models"; beide
  blijven onder een ZDR-overeenkomst bruikbaar. De prijstabel `ai_kosten_prijzen_usd_per_mtok`
  (sonnet-5, opus-5, opus-4-8, haiku-4-5) werkt als fail-closed allowlist: een model buiten de
  tabel wordt door de kostenpoort geblokkeerd — een Covered Model kan dus niet stil in
  productie komen.

## 4. Afwijkingen (benoemd, niet stil hersteld)

1. **`contract_ontleding` ontbreekt in het register.** → **DOORGEVOERD 02-09 (V8, doc 1 §7b).** Contract-/offerte-PDF's bevatten
   contactpersonen, handtekeningen en prijsafspraken. Verwerking is AI-VOORSTEL per regel achter
   dezelfde per-administratie-gate (BESLISSINGEN "PROJECTENMODULE KANTOOR"). Nog 0 productie-
   calls. **Voorstel:** V8 "Projectadministratie steigerbouw (contract-ontleding, uren/meerwerk,
   planning, dossier)" toevoegen aan doc 1 — inclusief de veldwerker-dossiers die al als open
   aanvulling in de checklist staan (BESLISSINGEN "Parkeerposten blok A" punt 4). Eén rij,
   twee openstaande punten in één keer dicht. Besluit + redactie: Peter/jurist.
2. **`voorraad_normalisatie` ontbreekt in het register.** → **DOORGEVOERD 02-09 (onderdeel van de V8-rij, doc 1 §7b).** Naar de API gaan alleen
   artikelomschrijvingen (tekst, géén PDF, géén afzender/afnemer). Persoonsgegevens zijn hier
   niet te verwachten maar niet uit te sluiten (een regeltekst "uren J. Jansen wk 34" komt voor).
   226 productie-calls sinds 29-08 (Universal Steigerbouw). **Voorstel:** korte alinea in V1
   ("regelniveau-normalisatie voor de voorraad-controle, zelfde verwerker/gate") óf onderdeel van
   de V8-rij. Besluit: Peter/jurist.
3. **`claude-haiku-4-5` staat nergens in de documenten.** Inhoudelijk geen persoonsgegevens
   (synthetische prompt), dus geen registerplicht; wél opnemen in checklist A als tweede model
   zodat de model-check bij een ZDR-bevestiging klopt. **Extra aandachtspunt:** Anthropic vermeldt
   voor Haiku 4.5 "Retirement: not sooner than October 15, 2026" (models-overview, geraadpleegd
   02-09) — dat is de vroegst mogelijke datum, geen aankondiging; de bewaking valt bij retirement
   luid uit (kostenpoort/400), niet stil. Modelwissel voor de bewaking inplannen zodra Anthropic
   een datum aankondigt; kandidaat = het goedkoopste niet-Covered model in de prijstabel.
4. **Prijstabel overschat Sonnet 5.** Gepind $ 3,00 / $ 15,00 per Mtok (stickerprijs
   web-geverifieerd 14-08); Anthropic's models-overview toont op 02-09 $ 2,00 / $ 10,00 voor
   `claude-sonnet-5`. De meter rekent dus ~33 % te hoog — **conservatief, geen AVG-afwijking**,
   maar de € 100-grens wordt eerder geraakt dan nodig. Aanpassen = één config-regel + hertest;
   apart besluit (raakt de kostengrens-afspraak van 14-08).
5. **Audit-kwaliteit gate-wijzigingen (bijvangst van de cloud-query):** op 01-09 10:05 schreef
   een bulkactie 23 audit-events `ai_extractie_ingeschakeld_gewijzigd` met oude = nieuwe waarde
   (`true → true`); en de wizard-default AAN (30-08) legt voor nieuwe administraties géén
   gate-event vast (A.Y. Holding 2, Abbegaa, Adda, BLOw, B. van Rooijen/G. Schaalje, T&J,
   Zilver Beheer, Caravanpark De Visotter hebben alleen de aanmaak, geen "gate AAN"-event). Voor
   de aantoonbaarheid ("wie zette wanneer AI aan voor administratie X") is dat een gat.
   **Voorstel (code, klein):** bulk-schrijver slaat no-op-events over; wizard schrijft één
   expliciet event "gate AAN bij aanmaak (default)". Buiten dit blok.

## 5. Conclusie voor de checklist

- Model-check t.o.v. **ZDR-compatibiliteit: GROEN** (sonnet-5 + haiku-4-5, allowlist via
  prijstabel) — de checklist-regel kan pas op [x] als ook het ZDR-besluit (doc 9) is genomen,
  want de regel luidt "is ZDR-compatibel" en ZDR is nog niet bevestigd.
- Model-check t.o.v. **register/DPA-dekking: ORANJE** — twee AI-paden zonder registerregel
  (§4.1, §4.2). Geen contractuele afwijking (DPA model-agnostisch, PDL-Bijlage-B dekt de
  categorie), wel een documentatiegat dat vóór het "klanten geïnformeerd"-moment dicht moet,
  omdat de klantinformatietekst (doc 11) deze paden benoemt.
