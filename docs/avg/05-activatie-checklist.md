# Activatie-checklist — volgorde van de gates

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**
> Harde regel (besluit Peter 2026-08-11): dit pakket is de poort vóór AI op echte klantdata
> en vóór klantdata in de cloud. Een gate gaat pas AAN als alle vinkjes van zijn stap staan.

## Stap 0 — nu (fundament, geen gate)

- [ ] Dit AVG-pakket juridisch getoetst (alle vijf documenten) — statusupdate in
      `docs/BESLISSINGEN.md` "AVG-compliance".
- [ ] Datalek-procedure kantoorbreed beschreven (meldplicht 72 u; wie meldt, wie beoordeelt).
- [ ] Privacyverklaring kantoor actueel (verwijzing naar register + tekstblok doc 3).

## Stap 1 — vóór `intake_ai_ingeschakeld` AAN (AI-extractie op echte klantdata)

Volgorde: eerst contracten, dan documenten, dan de knop.

- [ ] **Anthropic-DPA rond**: betaald API-account, Commercial Terms geaccepteerd (= DPA incl.
      SCC's), versie + datum gearchiveerd (checklist A in doc 2).
- [ ] **Zero data retention** aangevraagd en bevestigd, óf de default-retentie bewust
      geaccepteerd en vastgelegd (met motivering).
- [ ] **Model-check**: `ai_extractie_model` is ZDR-compatibel (nu `claude-sonnet-5` — bij
      elke modelwissel opnieuw checken; sommige modellen vereisen 30 dagen retentie).
- [ ] **Verwerkingsregister** V1/V2/V3 (doc 1) vastgesteld en actueel.
- [ ] **DPIA-lichte toets** (doc 4) vastgesteld; restrisico's expliciet geaccepteerd.
- [ ] **Klanten geïnformeerd**: tekstblok (doc 3 §4) in de opdrachtvoorwaarden of als
      addendum verzonden — in elk geval voor de administraties waar de AI voor gaat draaien.
- [ ] **Gevoelige administraties gemarkeerd**: per administratie beoordeeld of de AI-gate
      daar uit blijft (doc 4 §5.4).
- [ ] Technische borging aanwezig (is gebouwd — alleen verifiëren): BSN-filtertests groen,
      gate default UIT, audit op gate-wijziging.
- ➡️ Daarna: `make intake-ai-aan` (of de Instellingen-knop) — de wijziging zelf wordt
  geauditeerd.

**NB:** de AI-extractie voor inkoopfacturen, rapport-extractie (omzet) en
multi-factuur-splitsing zitten allemaal achter dezelfde platform-brede gate — stap 1 dekt ze
alle drie. Testen kan zonder deze stap uitsluitend met niet-klantdata (eigen testdocumenten,
TEST-administratie).

## Stap 2 — vóór de GCP-uitrol (klantdata in de cloud, gepland september 2026)

- [ ] **Google Cloud CDPA** geaccepteerd; versie + datum gearchiveerd (checklist B).
- [ ] **Regio-borging**: alle services in `europe-west4`; Organization Policy op EU-locaties.
- [ ] **Herzieningsmoment CLOUD Act uitgevoerd** (besluit 0003): CMEK en/of client-side
      documentversleuteling beoordeeld; uitkomst als nieuw platformbesluit vastgelegd.
- [ ] **Retentie geconfigureerd**: Cloud Storage-bucketretentie 7 jaar op documenten;
      back-up/PITR-instellingen gedocumenteerd.
- [ ] **Exact Reeleezee**: actuele verwerkersovereenkomst bevestigd en gearchiveerd
      (checklist C) — formeel losstaand van GCP, maar vóór livegang afronden.
- [ ] **IMAP-postvak**: providerkeuze gemaakt + DPA rond (checklist D) — vóór activering van
      de live e-mail-fetch (de seam in `app/intake/postvak.py`).
- [ ] Verwerkingsregister §8/§9 bijgewerkt op de werkelijke cloudconfiguratie.

## Stap 3 — opt-ins per administratie (ná stap 1 en 2)

Deze gates zijn functioneel, maar raken de AVG-verantwoording (meer automatisering = meer
gewicht op de gedocumenteerde waarborgen):

| Gate | Voorwaarde bovenop stap 1/2 |
|---|---|
| `bank_autoboeken_ingeschakeld` (per administratie) | Geen extra AVG-actie — deterministisch, geen AI; klant geïnformeerd via tekstblok |
| Autoboeken per leverancier (Beheerder-only, default UIT) | Stap 1 volledig; werkt alleen op app-bevestigd geheugen + harde checks (gebouwd) |
| Klant-accordering + accordeur-accounts | Tekstblok doc 3 bij de klant rond (accordeur-gegevens in register V6/V7) |
| `afgeletterd_event_ingeschakeld` / webhooks naar vastgoed | Platform-intern (HMAC); geen aparte DPA — wel benoemd in het register (V4) |
| Accordeur-PWA + push (fase 3) | Bij bouw: register aanvullen (pushtokens = persoonsgegevens) + providerkeuze push |

## Samenvatting: wat blokkeert wat

```
AVG-pakket getoetst (stap 0)
   └─► Anthropic-DPA + ZDR + register + DPIA + klantinfo (stap 1)
          └─► intake_ai_ingeschakeld AAN  ──► AI-extractie / splitsing / rapport-extractie
   └─► Google CDPA + regio + CMEK-herziening + retentie (stap 2)
          └─► GCP-uitrol (klantdata in de cloud) ──► live IMAP-intake (na eigen DPA)
                 └─► opt-ins per administratie (stap 3)
```
