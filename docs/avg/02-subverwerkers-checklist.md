# Subverwerkers-checklist — verwerkersovereenkomsten per partij

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**
> Links en voorwaarden geverifieerd via web op **2026-08-11**; DPA-voorwaarden wijzigen —
> her-verifieer bij ondertekening.

Terminologie: omdat het kantoor voor de administratievoering **zelfstandig
verwerkingsverantwoordelijke** is (zie [03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md)),
zijn de partijen hieronder formeel **verwerkers** van het kantoor (geen "subverwerkers").
De checklist-acties zijn identiek: met elke partij moet een verwerkersovereenkomst/DPA
(art. 28 AVG) staan vóór er persoonsgegevens naartoe gaan.

## Overzicht

| Partij | Rol | Wanneer nodig | Status |
|---|---|---|---|
| Anthropic (contractspartij EEA: Anthropic Ireland, Limited) | Verwerker (AI-extractie, Claude API) | Vóór `intake_ai_ingeschakeld` AAN op echte klantdata | 🔶 lopend — ToS + DPA gearchiveerd (2026-08-14), ZDR-verzoek ingediend |
| Google Cloud (Google Cloud EMEA Ltd.) | Verwerker (hosting, DB, documentopslag) | Vóór de GCP-uitrol (klantdata in de cloud) | ⬜ open |
| Exact Reeleezee (Exact Group B.V.) | Verwerker (boekhoudpakket) | Loopt al — bestaande relatie; status formeel bevestigen | ⬜ te bevestigen |
| E-mailprovider intake-postvak | Verwerker (IMAP-postvak) | Vóór activering live IMAP-fetch (GCP-uitrol) | ⬜ leverancierskeuze open |

---

## A. Anthropic (Claude API)

**Gearchiveerde brondocumenten (aangeleverd door Peter, 2026-08-14 — in deze map):**

- `Commercial Terms of Service _ Anthropic.pdf` — webprint 14-08-2026 van
  <https://www.anthropic.com/legal/commercial-terms>, versie **effective 17 juni 2025**
  (datum uit de PDF geverifieerd).
- `Data Processing Addendum _ Anthropic.pdf` — webprint 14-08-2026 van
  <https://www.anthropic.com/legal/data-processing-addendum>, versie
  **effective 24 februari 2025** (datum uit de PDF geverifieerd).
- Kernpunten uit de gearchiveerde versies (opgave Peter bij aanlevering):
  - **Contractspartij voor EEA-klanten is Anthropic Ireland, Limited** (per de Commercial
    Terms). NB: de contractuele wederpartij is daarmee een EU-entiteit, maar de verwerking
    zelf vindt nog steeds in de VS plaats — de SCC's/doorgifte-analyse hieronder blijft
    onverkort relevant.
  - **Geen training op Customer Content** — Commercial Terms **§B (Customer Content)**.
    Daarmee is de verifieer-opdracht bij punt 1 hieronder ingevuld voor de gearchiveerde
    versie van 17-06-2025; her-verifiëren bij een nieuwe Terms-versie.
  - **ZDR-verzoek is ingediend en loopt** (status 2026-08-14); uitkomst + eventuele
    ZDR-overeenkomst hier archiveren zodra rond.

**Hoe de DPA werkt (geverifieerd 2026-08-11):**

- Anthropics DPA — inclusief de EU Standard Contractual Clauses (2021, module 2
  controller→processor en module 3 processor→processor) — is **automatisch onderdeel van de
  Commercial Terms of Service**: wie de Commercial Terms accepteert (betaald API-account),
  accepteert daarmee de DPA. Er is geen aparte handtekening nodig.
- Officiële DPA: <https://www.anthropic.com/legal/data-processing-addendum>
- Uitleg Anthropic Privacy Center: <https://privacy.claude.com/en/articles/7996862-how-do-i-view-and-sign-your-data-processing-addendum-dpa>
- Verwerking vindt plaats in de **VS** (geen EU-regio voor de standaard API); doorgifte rust op
  de SCC's in de DPA. Controleer bij ondertekening of Anthropic in het EU-U.S.
  Data-Privacy-Framework-register staat (extra grondslag).

**Zero data retention / data-handling — exact wat te kiezen:**

1. **Default (zonder ZDR):** Anthropic bewaart API-in- en output een beperkte periode voor
   misbruik-/veiligheidsmonitoring (volgens Anthropics documentatie doorgaans max. 30 dagen);
   Anthropic traint volgens de Commercial Terms **niet** op API-data van zakelijke klanten —
   geverifieerd in de gearchiveerde Terms-versie van 17-06-2025 (§B Customer Content, zie
   "Gearchiveerde brondocumenten" hierboven); her-verifiëren bij een nieuwe Terms-versie.
2. **Zero Data Retention (ZDR) — aan te vragen:** voorkomt dat prompts/responses überhaupt
   worden opgeslagen. ZDR is een aparte afspraak voor gekwalificeerde commerciële
   API-klanten; aanvragen via Anthropic sales/support (verwijzing in het Privacy Center:
   "I have a zero data retention agreement with Anthropic"). **Aanbeveling: aanvragen** —
   het is de sterkste mitigatie voor de VS-doorgifte van documentinhoud.
3. **Model-restrictie onder ZDR (belangrijk):** sommige Anthropic-modellen (o.a. Claude
   Fable 5) vereisen 30 dagen retentie en zijn **niet beschikbaar onder ZDR** — requests
   falen dan met een 400. De module gebruikt `claude-sonnet-5` (setting
   `ai_extractie_model`), dat wél onder ZDR werkt. Borging: bij een toekomstige modelwissel
   eerst de ZDR-compatibiliteit checken (opgenomen in de activatie-checklist).

**Acties Peter:**

- [ ] Betaald Anthropic-API-account (organisatie) — Commercial Terms accepteren = DPA rond;
      de Terms-versie (effective 17-06-2025) en DPA-versie (effective 24-02-2025) zijn
      gearchiveerd (2026-08-14); acceptatiedatum van het account nog vastleggen.
- [x] ZDR aanvragen — **verzoek ingediend, loopt** (status 2026-08-14); ⬜ uitkomst
      vastleggen + eventuele ZDR-overeenkomst archiveren zodra rond.
- [ ] DPF-register checken op Anthropic (extra doorgiftegrondslag) en noteren.
- [ ] Subverwerkerslijst van Anthropic (in de DPA) doorlopen en archiveren.

---

## B. Google Cloud

**Hoe de DPA werkt (geverifieerd 2026-08-11):**

- Het **Cloud Data Processing Addendum (CDPA)** is automatisch in de Google
  Cloud-overeenkomst opgenomen ("incorporated into the Agreement"); acceptatie gebeurt bij
  het aangaan van het account/de overeenkomst. Officiële tekst:
  <https://cloud.google.com/terms/data-processing-addendum>
- Doorgifte: het CDPA bevat de EU SCC's (appendix "Specific Privacy Laws"); daarnaast is
  Google sinds september 2023 gecertificeerd onder het **EU-U.S. Data Privacy Framework**
  als "Alternative Transfer Solution". Achtergrond:
  <https://services.google.com/fh/files/misc/gc_new_eu_scc.pdf>
- Data-locatie: `europe-west4` (besluit 0003) vastleggen per service (Cloud SQL, Cloud
  Storage, Cloud Run) — de locatietoezegging loopt via de Service Specific Terms.

**CLOUD Act-mitigatie (verwijst naar het contractuele herzieningsmoment, besluit 0003):**

- CLOUD Act-risico is geaccepteerd op 2026-07-04 **mét herzieningsmoment vóór go-live**.
  Op dat moment beoordelen: **CMEK** (customer-managed encryption keys via Cloud KMS,
  eventueel met externe key via Cloud EKM) voor Cloud SQL en Cloud Storage, en/of
  **client-side versleuteling** van klantdocumenten vóór upload. CMEK is een
  productinstelling (geen contractwijziging); client-side encryptie is een bouwkeuze.
- Uitkomst van het herzieningsmoment vastleggen in `Platform/besluiten/` (nieuw besluit dat
  0003 aanvult).

**Acties Peter:**

- [ ] Google Cloud-organisatie/billing opzetten; CDPA-versie + acceptatiedatum vastleggen.
- [ ] Data-locatie `europe-west4` per service configureren en een Organization Policy
      (resource location restriction) op EU zetten.
- [ ] Herzieningsmoment CMEK/client-side encryptie uitvoeren vóór go-live (besluit 0003) en
      de uitkomst als platformbesluit vastleggen.
- [ ] Googles subverwerkerslijst (via het CDPA) archiveren.

---

## C. Reeleezee (Exact Reeleezee)

**Feiten (geverifieerd 2026-08-11):**

- Reeleezee is sinds 2017 onderdeel van Exact en heet formeel **Exact Reeleezee**
  (<https://www.exact.com/nl/reeleezee>). Juridische documenten lopen via Exact
  (privacy statement / voorwaarden / trust-informatie onderaan die pagina).
- Exact publiceert een standaard **verwerkersovereenkomst** met bijlage
  (subverwerkers/beveiligingsmaatregelen), o.a.:
  - Verwerkersovereenkomst (versie 1.5, 2021): <https://files.exact.com/static/downloads/information-security/E-MKB-VWO-VERWERKING-VAN-PERSOONSGEGEVENS-2021.pdf>
  - Bijlage bij verwerkersovereenkomst (versie 1.6, 2022): <https://files.exact.com/static/downloads/information-security/E-MKB-BIJLAGE-VERWERKERSOVEREENKOMST-202207.pdf>
- ⚠️ Deze documenten zijn op de Exact-MKB/Exact Online-lijn geschreven; **welke versie
  formeel op Reeleezee-abonnementen van toepassing is, moet bij Exact Reeleezee worden
  nagevraagd** — de gevonden PDF's zijn mogelijk niet de actuele of niet de Reeleezee-variant.
- Kanttekening bij de rol: als het kantoor zelfstandig verantwoordelijke is en Reeleezee de
  software levert waarin het kantoor de administratie voert, is Reeleezee verwerker van het
  kantoor. De webservice-logins per administratie (waarmee déze module in RLZ schrijft)
  vallen onder diezelfde relatie.

**Acties Peter:**

- [ ] Bij Exact Reeleezee de actuele, op Reeleezee toepasselijke verwerkersovereenkomst
      opvragen (of bevestigen dat die al in de bestaande abonnementsvoorwaarden zit) en
      archiveren, incl. subverwerkerslijst en datalocatie (EU-hosting bevestigen).
- [ ] Controleren of de API-toegang (webservice-logins) onder dezelfde voorwaarden valt.

---

## D. E-mailprovider intake-postvak (PM)

De live IMAP-fetch is een gemarkeerde seam die pas bij de GCP-uitrol wordt geactiveerd. De
leverancier van het centrale intake-adres is dan een verwerker (e-mail bevat facturen met
persoonsgegevens). Bij de leverancierskeuze: EU-hosting of DPA met SCC's vereisen; keuze en
DPA-status hier aanvullen vóór activering.
