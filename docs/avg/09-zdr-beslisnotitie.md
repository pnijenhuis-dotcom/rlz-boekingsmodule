# Beslisnotitie — Zero Data Retention (ZDR) bij Anthropic

> **Status: CONCEPT ter besluit (opgesteld 2026-09-02, blok A AVG-afronding). Besluit = Peter
> (eventueel mét jurist). Niets in deze notitie is afgevinkt; de checklist-regel "ZDR" in
> `05-activatie-checklist.md` blijft open tot het besluit hier is ingevuld.**
>
> Context: het ZDR-verzoek is op 2026-08-14 ingediend (BESLISSINGEN "Anthropic-dossier"), de
> uitkomst is niet gearchiveerd. Intussen staat de AI-gate in productie AAN voor alle 30 actieve
> administraties (feitelijke stand 02-09, `05-activatie-checklist.md` §"Feitelijke stand"). Dat
> maakt dit besluit achterstallig: óf ZDR wordt bevestigd, óf de default-retentie wordt nu
> bewust en gemotiveerd geaccepteerd.

## 1. Wat ZDR is

Bron: Anthropic Privacy Center, artikel "I have a zero retention agreement with Anthropic — what
products does it apply to?" (laatst bijgewerkt 9 juni 2026) en "How long do you store personal
data?" (laatst bijgewerkt 1 juli 2026), beide web-geraadpleegd 2026-09-02.

| | Default (zonder ZDR) | Mét ZDR-overeenkomst |
|---|---|---|
| Bewaring van API-invoer en -uitvoer | Anthropic verwijdert invoer/uitvoer automatisch **binnen 30 dagen** | Anthropic slaat invoer/uitvoer **niet op**, behalve waar wettelijk verplicht of nodig tegen misbruik |
| Trust & safety | Bij een Usage-Policy-schending: bewaring tot 2 jaar; classificatiescores tot 7 jaar | Ongewijzigd: "we still retain User Safety classifier results in order to enforce our Usage Policy" |
| Training op onze data | Nee (Commercial Terms §B, gearchiveerd 17-06-2025) | Nee |
| Waar geldt het | — | "eligible Anthropic APIs" en producten op de organisatie-API-key; per organisatie beoordeeld en toegepast |
| Uitzondering per model | — | **"Covered Models"**: daarvoor eist Anthropic beperkte bewaring + review als onderdeel van het veiligheidswerk — die modellen zijn onder ZDR niet bruikbaar (request faalt met `400 invalid_request_error`) |
| Hoe aanvragen | — | Via Anthropic Sales; goedkeuring per organisatie; controle achteraf in de Console: *Settings › Privacy Controls › Data retention period* |
| Kosten | — | **Geen gepubliceerd tarief.** Het Privacy Center noemt geen prijs en geen harde drempel; ZDR is een contractuele afspraak voor gekwalificeerde commerciële klanten, geen betaald product. Eventuele voorwaarden (minimumafname, Enterprise-plan) blijken pas in het Sales-gesprek — vastleggen zodra bekend. |

Wat ZDR **niet** doet: het verandert niets aan de doorgifte zelf (verwerking blijft in de VS, de
SCC's in de DPA blijven de grondslag), het schakelt de veiligheidsclassifiers niet uit en het is
geen vervanging van de DPA. Het verkleint uitsluitend het venster waarin documentinhoud bij
Anthropic opgeslagen staat: van maximaal 30 dagen naar nul (behoudens de genoemde uitzonderingen).

## 2. Wat het voor onze module betekent

- **Welke modellen wij gebruiken** (bewezen op code + productie-kostenmeter, zie
  `10-model-check.md`): `claude-sonnet-5` voor álle extractiepaden, `claude-haiku-4-5` voor de
  uurlijkse bewakings-call. Geen van beide is een "Covered Model" (dat zijn de Fable-/Mythos-
  generatie; bron: Claude-API-referentie, stand 24-06-2026). **ZDR is dus functioneel direct
  toepasbaar zonder codewijziging.**
- **Fail-closed borging bestaat al impliciet:** de AI-kostenpoort blokkeert élk model dat niet in
  de gepinde prijstabel staat (`ai_kosten_prijzen_usd_per_mtok`: sonnet-5, opus-5, opus-4-8,
  haiku-4-5). Een Covered Model kán dus nu al niet per ongeluk in productie draaien. Voorstel
  (klein, na het besluit): die tabel expliciet als ZDR-allowlist benoemen + een test die faalt
  zodra er een Covered Model in wordt gepind.
- **Wat er níét onder valt:** de Files API gebruiken wij niet (PDF gaat base64 mee in de call),
  Batch API niet, geen Managed Agents. Er is geen "langere bewaring onder klantbeheer" die ZDR
  zou omzeilen.
- **Wie de aanvrager is:** het API-organisatieaccount staat op naam van **PDL Powerhouse**
  (document 7, Bijlage B). De ZDR-overeenkomst komt dus tussen Anthropic en PDL; het kantoor
  legt in de PDL-verwerkersovereenkomst (Bijlage B, kolom "Contractuele grondslag") vast dat
  ZDR van toepassing is zodra bevestigd.
- **Aantoonbaarheid:** een screenshot/print van *Console › Settings › Privacy Controls › Data
  retention period* mét datum is het bewijsstuk voor de checklist en het F5-poortdossier; de
  eventuele ZDR-overeenkomst zelf als PDF in `docs/avg/`.

## 3. Opties

| Optie | Inhoud | Voordeel | Nadeel / risico |
|---|---|---|---|
| **A. ZDR doorzetten (advies)** | Verzoek van 14-08 najagen via Anthropic Sales namens PDL; bevestiging archiveren; Bijlage B + checklist bijwerken | Sterkste mitigatie voor de VS-doorgifte van documentinhoud (DPIA R1/R2/R6 rekenen er al op); geen functionele prijs; sluit aan op wat het AVG-pakket de jurist heeft voorgelegd (toetsvraag 3 noemt "Anthropic met zero-data-retention") | Doorlooptijd Sales; Covered Models blijven uitgesloten (nu geen bezwaar — bij een latere wens voor Fable/Mythos ontstaat een nieuw besluitpunt) |
| **B. Default-retentie bewust accepteren** | Vastleggen dat ≤ 30 dagen bewaring bij Anthropic Ireland/VS aanvaardbaar is, mét motivering | Direct rond, geen afhankelijkheid van Anthropic | Wijkt af van wat het getoetste pakket veronderstelt (DPIA-mitigaties noemen ZDR); klantinformatie moet dan eerlijk "maximaal 30 dagen" zeggen; zwakkere positie bij een Schrems-achtige koerswijziging |
| **C. Tussenstand (nu nodig, ongeacht A/B)** | Zolang ZDR niet bevestigd is: optie B **tijdelijk** en expliciet vastleggen, omdat de gate feitelijk al aan staat | Maakt de huidige productiesituatie aantoonbaar bewust i.p.v. stilzwijgend | Geen — dit is de minimale opruimactie |

**Advies:** A + C. Concreet: (1) vandaag de tijdelijke acceptatie (C) tekenen in §4; (2) het
ZDR-verzoek najagen; (3) bij bevestiging §4 afsluiten, checklist afvinken, Bijlage B en doc 2
(checklist A) bijwerken, klantinformatietekst (doc 11) op "wordt niet bewaard" zetten.

## 4. Besluit (in te vullen door Peter)

```
[ ] Optie A — ZDR doorzetten. Aanvrager: PDL Powerhouse (accounthouder). Actie: ............
    Bevestiging ontvangen op: ..........  Bewijs: docs/avg/............ (console-print/overeenkomst)

[ ] Optie C — tijdelijke acceptatie default-retentie (≤ 30 dagen) totdat ZDR bevestigd is.
    Motivering: documentinhoud (facturen, mail-tekst zonder BSN, regelteksten) gaat uitsluitend
    onder DPA + SCC's naar Anthropic; geen training; BSN-filter; kostenpoort; mens-in-de-lus;
    bewaring ≤ 30 dagen uitsluitend voor misbruikbestrijding. Restrisico geaccepteerd tot: ..........

[ ] Optie B — default-retentie definitief accepteren (dan doc 3 §4 / doc 11 aanpassen: "max. 30 dagen").

Naam / datum / paraaf: .......................................................
```

Ná invulling: deze notitie is de canonieke vindplaats van het ZDR-besluit; `05-activatie-
checklist.md` stap 1 en `02-subverwerkers-checklist.md` checklist A verwijzen hiernaar.
