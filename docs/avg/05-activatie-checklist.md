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

> ➡️ **Deze stap is de F5-poort.** Het afvinkbare bewijsdossier (per punt:
> bewijs/vindplaats + wie + status) is **[08-f5-poortdossier.md](08-f5-poortdossier.md)**
> — status dáár bijhouden, dit lijstje blijft de normtekst.
> **Stand 2026-08-15: de poort is DICHT (8/8 ✅ in het dossier)** — datamigratie
> tranche 2 is vrijgegeven zodra Peter het go-live-moment kiest.

- [ ] **Google Cloud CDPA** geaccepteerd; versie + datum gearchiveerd (checklist B).
- [ ] **Regio-borging**: alle services in `europe-west4`; Organization Policy op EU-locaties.
- [ ] **Herzieningsmoment CLOUD Act uitgevoerd** (besluit 0003): CMEK en/of client-side
      documentversleuteling beoordeeld; uitkomst als nieuw platformbesluit vastgelegd.
- [ ] **Retentie geconfigureerd**: Cloud Storage-bucketretentie 7 jaar op documenten;
      back-up/PITR-instellingen gedocumenteerd.
- [ ] **Exact Reeleezee**: actuele verwerkersovereenkomst bevestigd en gearchiveerd
      (checklist C) — formeel losstaand van GCP, maar vóór livegang afronden.
- [ ] **IMAP-postvak**: providerkeuze gemaakt + DPA rond (checklist D) — vóór activering van
      de live e-mail-fetch (`app/intake/postvak.py`).
- [ ] Verwerkingsregister §8/§9 bijgewerkt op de werkelijke cloudconfiguratie.

## Stap 3 — opt-ins per administratie (ná stap 1 en 2)

Deze gates zijn functioneel, maar raken de AVG-verantwoording (meer automatisering = meer
gewicht op de gedocumenteerde waarborgen):

| Gate | Voorwaarde bovenop stap 1/2 |
|---|---|
| `bank_autoboeken_ingeschakeld` (per administratie) | Geen extra AVG-actie — deterministisch, geen AI; klant geïnformeerd via tekstblok |
| Autoboeken per leverancier (Beheerder-only, default UIT) | Stap 1 volledig; werkt alleen op app-bevestigd geheugen + harde checks (gebouwd) |
| Klant-accordering + accordeur-accounts | Tekstblok doc 3 bij de klant rond (accordeur-gegevens in register V6/V7) + activeringsflow-akkoord (zie hieronder) |
| `afgeletterd_event_ingeschakeld` / webhooks naar vastgoed | Platform-intern (HMAC); geen aparte DPA — wel benoemd in het register (V4) |
| Accordeur-PWA + push (fase 3) | Bij bouw: register aanvullen (pushtokens = persoonsgegevens) + providerkeuze push |

### Accordeur-activeringsflow — voorwaarden + privacyverklaring ter akkoord (toegevoegd 2026-08-11)

> ℹ️ **Informatielaag BÓVENOP het AVG-pakket, géén vervanging**: dit akkoord-scherm vervangt
> geen DPA's (stap 1/2), niet het verwerkingsregister en niet de DPIA-toets — het vult
> uitsluitend de **informatieplicht** richting de accordeur zelf in. Voor de
> accordeur-accountgegevens is het kantoor **verwerkingsverantwoordelijke** (rolbepaling
> doc 3); daarom hoort deze informatie- en akkoordstap bij ons, niet bij de klant.

- [ ] De **activeringsflow van een accordeur-account** (eenmalige uitnodigingslink) toont de
      **opdracht-/gebruiksvoorwaarden + privacyverklaring** en vraagt expliciet akkoord vóór
      het eerste gebruik; het akkoord (wie, wanneer, welke tekstversie) landt in het
      append-only audit log.
- [ ] De **concept-akkoordtekst (bijlage A)** is juridisch getoetst vóórdat de eerste échte
      accordeur live gaat.

## Samenvatting: wat blokkeert wat

```
AVG-pakket getoetst (stap 0)
   └─► Anthropic-DPA + ZDR + register + DPIA + klantinfo (stap 1)
          └─► intake_ai_ingeschakeld AAN  ──► AI-extractie / splitsing / rapport-extractie
   └─► Google CDPA + regio + CMEK-herziening + retentie (stap 2)
          └─► GCP-uitrol (klantdata in de cloud) ──► live IMAP-intake (na eigen DPA)
                 └─► opt-ins per administratie (stap 3)
```

## Bijlage A — concept-akkoordtekst activeringsflow accordeur

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.** Vóór gebruik door
> een jurist laten toetsen (zelfde disclaimer als de rest van dit pakket). Placeholders
> tussen [ ] worden per klant/administratie ingevuld; de getoonde tekstversie + datum worden
> bij elk akkoord vastgelegd.

---

*Welkom bij de goedkeuringsapp van Administratiekantoor Nijenhuis. Je bent door
**[klantnaam]** aangewezen om inkoopfacturen van **[administratie]** goed te keuren.
Lees dit even door voordat je begint.*

***1. Gebruiksvoorwaarden.** Je gebruikt deze app uitsluitend om facturen van [klantnaam]
te beoordelen: goedkeuren, of afwijzen met een verplichte reden. Je account is persoonlijk —
deel je inloggegevens of apparaat-toegang niet met anderen. [Klantnaam] en het kantoor
kunnen je toegang op elk moment intrekken.*

***2. Jouw gegevens.** Voor je account verwerken wij: je naam, e-mailadres, inloggegevens
(wachtwoord versleuteld, eventuele passkey), apparaat- en sessiegegevens en een logboek van
je handelingen (welke factuur, akkoord of afwijzing met reden, datum en tijd). Doel: veilige
toegang en een controleerbaar goedkeuringsspoor bij de administratie. Het logboek bewaren
wij 7 jaar (wettelijke administratieplicht). Administratiekantoor Nijenhuis is voor deze
accountgegevens de verwerkingsverantwoordelijke; in de privacyverklaring **[link]** lees je
hoe wij met je gegevens omgaan en welke rechten je hebt (inzage, correctie, bezwaar).*

***3. Staande goedkeuringen.** Stel je een staande goedkeuring in ("akkoord voor deze en
alle volgende facturen van deze leverancier met exact dit bedrag"), dan wordt zo'n volgende
factuur automatisch namens jou goedgekeurd. Elke automatische toepassing is zichtbaar in het
logboek en je kunt de regel in de app altijd intrekken.*

*☐ Ik heb de gebruiksvoorwaarden en de privacyverklaring gelezen en ga akkoord.*

*(het akkoord wordt vastgelegd met naam, datum, tijdstip en tekstversie)*
