# Activatie-checklist — volgorde van de gates

> ✅ **Getoetst — jurist-akkoord 2026-08-12** (intern opgesteld, juridische toetsing afgerond
> — zie `docs/BESLISSINGEN.md` "AVG-compliance"); sindsdien de operationele leidraad.
> Harde regel (besluit Peter 2026-08-11): dit pakket is de poort vóór AI op echte klantdata
> en vóór klantdata in de cloud. Een gate gaat pas AAN als alle vinkjes van zijn stap staan.
> **Bijgewerkt 2026-08-19:** stap 1 op de PDL-keten (document 7, Bijlage B) — het
> Anthropic-API-organisatieaccount staat op naam van PDL, dus de Anthropic-DPA hangt in de
> keten PDL ↔ Anthropic en de getekende PDL-verwerkersovereenkomst is zelf een
> stap-1-voorwaarde.

## Stap 0 — nu (fundament, geen gate)

- [x] Dit AVG-pakket juridisch getoetst (alle vijf documenten) — **gedaan: jurist-akkoord
      2026-08-12**, statusupdate in `docs/BESLISSINGEN.md` "AVG-compliance" staat.
- [ ] Datalek-procedure kantoorbreed beschreven (meldplicht 72 u; wie meldt, wie beoordeelt).
- [ ] Privacyverklaring kantoor actueel (verwijzing naar register + tekstblok doc 3).

## Stap 1 — vóór `intake_ai_ingeschakeld` AAN (AI-extractie op echte klantdata)

Volgorde: eerst contracten, dan documenten, dan de knop.

- [x] **PDL-verwerkersovereenkomst getekend** — **gedaan 2026-08-19**: in tweevoud
      getekend te Arnhem (beide partijen P.W. Nijenhuis, Directie; KvK kantoor 72504412
      ingevuld), gearchiveerd als
      `Verwerkersovereenkomst-PDL-getekend-2026-08-18.pdf` (incl. Bijlagen A/B/C).
      Dit is de keten-schakel waarbinnen de Anthropic-DPA hangt (het
      API-organisatieaccount staat op naam van PDL, Bijlage B).
- [x] **Anthropic-DPA rond in de keten PDL ↔ Anthropic** — **gedaan 2026-08-14** (afgevinkt
      drift-audit-fix 02-09 op de registers): betaald API-organisatieaccount op naam van PDL
      Powerhouse (document 7, Bijlage B), Commercial Terms (effective 17-06-2025) + DPA (effective
      24-02-2025, incl. SCC's module 2 + 3) als PDF-webprints gearchiveerd in `docs/avg/` — DPA is
      automatisch onderdeel van de Commercial Terms (checklist A in doc 2; BESLISSINGEN
      "Anthropic-dossier"). Her-verifiëren bij een nieuwe Terms-versie.
- [ ] **Zero data retention** aangevraagd en bevestigd, óf de default-retentie bewust
      geaccepteerd en vastgelegd (met motivering). **VOORBEREID 02-09 — besluit open:**
      beslisnotitie `09-zdr-beslisnotitie.md` (wat ZDR is, geen gepubliceerd tarief, per
      organisatie via Sales namens PDL, Covered Models uitgesloten — wij gebruiken er geen;
      advies A + C: doorzetten én de tussenstand tijdelijk expliciet accepteren). **BESLOTEN
      02-09 (Peter, doc 9 §4): A + C — ZDR doorzetten via Sales (klikwerk Peter) én de
      default-retentie tijdelijk en gemotiveerd geaccepteerd tot ZDR actief is.** Afvinken pas
      ná de ZDR-bevestiging + gearchiveerd bewijs (console-print retentie-instelling).
- [ ] **Model-check**: `ai_extractie_model` is ZDR-compatibel (nu `claude-sonnet-5` — bij
      elke modelwissel opnieuw checken; sommige modellen vereisen 30 dagen retentie).
      **UITGEVOERD 02-09 (`10-model-check.md`):** code + productie-kostenmeter roepen uitsluitend
      `claude-sonnet-5` (alle extractiepaden) en `claude-haiku-4-5` (bewaking) aan; beide geen
      Covered Model → ZDR-compatibel GROEN; prijstabel werkt als fail-closed allowlist.
      Register-dekking: `voorraad_normalisatie` en `contract_ontleding` hadden geen V-rij —
      **V8 doorgevoerd 02-09 (doc 1 §7b), register-dekking GROEN.** Vinkje pas samen met de ZDR-bevestiging (de regel toetst
      compatibiliteit mét een bestaande ZDR-afspraak). Vaste regel: doc 10 herhalen bij élke
      modelwissel of nieuw AI-pad.
- [x] **Verwerkingsregister** V1/V2/V3 (doc 1) vastgesteld en actueel — **gedaan**: jurist-akkoord
      2026-08-12 (alle vijf documenten), §8/§9 bijgewerkt op de cloudconfiguratie 2026-08-14 (F5
      punt 7), doorgifte-notitie Anthropic-keten 2026-08-14. Open aanvulling (geen gate): dossier-
      documenten veldwerkers als gegevenscategorie (BESLISSINGEN "Parkeerposten blok A" punt 4).
- [x] **DPIA-lichte toets** (doc 4) vastgesteld — **gedaan**: jurist-akkoord 2026-08-12; restrisico's
      staan in doc 4 (acceptatie = het akkoord van Peter op het pakket 11/12-08).
- [ ] **Klanten geïnformeerd**: tekstblok (doc 3 §4) in de opdrachtvoorwaarden of als
      addendum verzonden — in elk geval voor de administraties waar de AI voor gaat draaien.
      **CONCEPT KLAAR 02-09:** `11-klantinformatietekst-concept.md` (één A4, klantleesbaar,
      twee bewaar-varianten afhankelijk van doc 9; redactie + verzending = Peter/jurist).
      **GEFINALISEERD 02-09 op de variant van het ZDR-besluit (doc 9 §4);** jurist-redactie +
      verzending = klikwerk Peter. Verzendlog per administratie = kolom "geïnformeerd" in doc 12.
      Op 02-09 draait de AI voor álle actieve administraties — de brief gaat naar alle klanten.
- [ ] **Gevoelige administraties gemarkeerd**: per administratie beoordeeld of de AI-gate
      daar uit blijft (doc 4 §5.4). **VOORSTEL KLAAR 02-09:**
      `12-beoordelingskader-gevoelige-administraties.md` — criteria A–E (+R) en een
      classificatie van alle 31 rijen; voorstel was 2× UIT tot bevestiging. **BESLOTEN 02-09
      (Peter): ALLE administraties AAN, inclusief Mantelzorgwoningen Midden Nederland en Stichting
      Shuto — geen zorg-/gevoelig materiaal in deze administraties, facturen zijn zakelijk;
      automatisering is de norm.** Alleen de test-seed houdt het UIT-advies (hygiëne). De
      feitelijke cloud-stand (alles AAN) ís daarmee de besloten stand — geen toggle-klikwerk.
- [x] Technische borging aanwezig — **geverifieerd 02-09 op code + registers**: BSN-filtertests
      groen in de suite, audit op élke gate-wijziging (platformgate `platform.intake_instelling`,
      Beheerder-only; per-administratie `ai_extractie_ingeschakeld`), AI-kostengrens € 100/mnd
      (14-08) en schema-poort (31-08) als extra lagen. **NB default gewijzigd (besluit Peter 29-08,
      opdracht 30-08 blok A):** voor NIEUWE administraties staat `ai_extractie_ingeschakeld` sinds
      30-08 default AAN (wizard); bestaande rijen behielden hun waarde. De platformgate
      `intake_ai_ingeschakeld` blijft de bovenliggende schakelaar.
- ➡️ Daarna: `make intake-ai-aan` (of de Instellingen-knop) — de wijziging zelf wordt
  geauditeerd.

> ⚠️ **Feitelijke stand 02-09 — GEVERIFIEERD op de cloud-DB (read-only query, Auth Proxy 5434,
> `boekhouding_app`, 02-09 ±20:30 NL; eerder die dag alleen op registers + code):** de AI-gate staat
> in productie AAN vóór deze stap volledig is afgevinkt.
>
> - **Platformgate** `platform.intake_instelling.ai_ingeschakeld = true` (audit
>   `intake_ai_ingeschakeld_gewijzigd` 16-08 13:04 UTC, actor Peter; de rij zelf draagt
>   `gewijzigd_op` 07-08 — cloud-seed).
> - **Per administratie** `ai_extractie_ingeschakeld`: **AAN voor alle 30 actieve administraties**,
>   UIT alleen voor de gearchiveerde "Administratiekantoor Nijenhuis (test)" (28-08 uitgezet,
>   30-08 gearchiveerd). Volledige tabel mét GUID's + sector + voorstel:
>   `12-beoordelingskader-gevoelige-administraties.md` §2. Hoe het aan ging (audit): 24-08
>   Universal Steigerbouw; 25-08 10:03 twaalf administraties in één bulk (ARVUM, Meyer, Elissen,
>   Kempen Facilities, Molenhof B/V, Oirschot R/OVB, Rubicon, Shuto, Veldhoven) + 15:00 Nijenhuis
>   C.V.; 27-08 6-Steps + Bouwadvies Oost; 30-08 Bradwolff, BWC, Universal Nederland/Verkoop;
>   sinds 30-08 wizard-default AAN (A.Y. Holding 1+2, Abbegaa, Adda, BLOw, B. van Rooijen/
>   G. Schaalje, T&J, Zilver Beheer, Caravanpark De Visotter, test-seed) — die default legt
>   géén gate-event vast (doc 10 §4.5); 01-09 10:05 een bulk van 23 no-op-events (true→true).
> - **Productieverbruik (kostenmeter):** 1.487 sonnet-5-calls (18-08 → 02-09, € 38,09) + 13
>   haiku-calls bewaking; bronnen inkoop_extractie 525, intake_splitsing 733,
>   voorraad_normalisatie 226, intake_herlezen 3 — modeltabel in `10-model-check.md` §2.
>
> **Nog open in deze stap en daarmee ACHTERSTALLIG (besluiten Peter/jurist, geen code):** ZDR
> (doc 9 §4), model-check-vinkje (hangt aan ZDR), klanten informeren (doc 11 versturen),
> gevoelige administraties (doc 12 paraferen). Alles is op 02-09 **voorbereid en aantoonbaar
> gemaakt**; niets is hier stil afgevinkt.

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

- [x] **Stap 2 integraal = de F5-poort: 8/8 ✅ (2026-08-15) in
      [08-f5-poortdossier.md](08-f5-poortdossier.md)** — CDPA, regio-borging, CLOUD-Act-herziening
      (besluit 0021), retentie/PITR, Exact-VWO, IMAP-provider-DPA, verwerkingsregister §8/§9 en de
      identiteit-eerst-check staan dáár per punt met bewijs/vindplaats + wie. De losse checkboxen die
      hier stonden zijn 02-09 (drift-audit-fix) vervangen door deze ene verwijsregel: één poort, één
      register — status uitsluitend in het dossier bijhouden. Uitgevoerd: tranche 2 (22-08), F4-cutover
      (24-08).

## Stap 3 — opt-ins per administratie (ná stap 1 en 2)

Deze gates zijn functioneel, maar raken de AVG-verantwoording (meer automatisering = meer
gewicht op de gedocumenteerde waarborgen):

| Gate | Voorwaarde bovenop stap 1/2 |
|---|---|
| `bank_autoboeken_ingeschakeld` (per administratie) | Geen extra AVG-actie — deterministisch, geen AI; klant geïnformeerd via tekstblok |
| Autoboeken per leverancier (Beheerder-only, default UIT) | Stap 1 volledig; werkt alleen op app-bevestigd geheugen + harde checks (gebouwd) |
| Klant-accordering + accordeur-accounts | Tekstblok doc 3 bij de klant rond (accordeur-gegevens in register V6/V7) + activeringsflow-akkoord (zie hieronder) |
| `afgeletterd_event_ingeschakeld` / webhooks naar vastgoed | Platform-intern (HMAC); geen aparte DPA — wel benoemd in het register (V4) |
| Accordeur-PWA + push (fase 3) | Bij bouw: register aanvullen (pushtokens = persoonsgegevens); providerkeuze gemaakt — APNs resp. FCM via de PDL-keten (subverwerkers ván PDL; DPA-checks E/F in doc 2 rond vóór app-livegang) |

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
- [x] De **akkoordtekst (bijlage A)** is juridisch getoetst vóórdat de eerste échte
      accordeur live gaat — **gedaan: jurist-akkoord 2026-08-12**.

## Samenvatting: wat blokkeert wat

```
AVG-pakket getoetst (stap 0)
   └─► PDL-VWO getekend + Anthropic-DPA (keten) + ZDR + register + DPIA + klantinfo (stap 1)
          └─► intake_ai_ingeschakeld AAN  ──► AI-extractie / splitsing / rapport-extractie
   └─► Google CDPA + regio + CMEK-herziening + retentie (stap 2)
          └─► GCP-uitrol (klantdata in de cloud) ──► live IMAP-intake (na eigen DPA)
                 └─► opt-ins per administratie (stap 3)
```

## Bijlage A — akkoordtekst activeringsflow accordeur

> ✅ **Getoetst — jurist-akkoord 2026-08-12** (meegetoetst met de rest van dit pakket).
> Placeholders tussen [ ] worden per klant/administratie ingevuld; de getoonde tekstversie +
> datum worden bij elk akkoord vastgelegd.

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

***4. Werkstempels (alleen veldwerkers: ZZP'ers en uitvoerders).** Werk je op projectlocaties, dan
kan de app op je telefoon je aankomst en vertrek op die locaties stempelen: uitsluitend het
tijdstip en het project, alleen bij het binnenkomen en verlaten van de projectzone die het
kantoor voor dat project heeft ingesteld — buiten die zones ontvangt de app niets en er wordt
niets gevolgd. De stempels zijn een hulpmiddel bij de controle van je weekstaat (het kantoor ziet
ze naast je opgegeven uren; een verschil is een gespreksonderwerp, nooit een automatische
korting) en zijn zichtbaar voor jou en voor de keurder van het kantoor — verder voor niemand. Ze
worden even lang bewaard als je weekstaten. Uitzetten kan altijd via de locatie-instelling van je
telefoon; de controle zwijgt dan.*

> Alinea 4 toegevoegd in tekstversie `2026-08-28-v2` (bouwrun 28-08 blok C, mockup
> `geofence-stempels.html`; jurist akkoord 28-08 — regeling via deze voorwaarden, géén apart
> instemmingsscherm; het OS toont daarnaast zijn eigen locatie-permissievraag). Bestaande
> gebruikers krijgen door de versieophoging opnieuw het akkoordscherm.

*☐ Ik heb de gebruiksvoorwaarden en de privacyverklaring gelezen en ga akkoord.*

*(het akkoord wordt vastgelegd met naam, datum, tijdstip en tekstversie)*
