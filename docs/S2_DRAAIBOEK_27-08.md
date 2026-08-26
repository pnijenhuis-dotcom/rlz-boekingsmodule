# S2-draaiboek — kostenflow-omkering met Vastly, donderdag 27-08-2026

Doel: per vastgoed-administratie schakelt Vastly de eigen kostenintake om naar
auto-bevestiging op onze `factuur_geboekt`-events, en zetten wij `is_vastgoed` +
`project_verplicht` aan. Volgorde per administratie is HARD (afspraak 25-08):
éérst Vastly's kant, dán onze vlaggen. Eén administratie tegelijk, nooit parallel.
Rubicon Investments eerst (Vastly's V7-criterium is op Rubicon gemeten).

Contractbasis: koppelcontract v1.17 §3/§3a/§3b (factuur_geboekt 1.2 incl.
volgnummer + corrigeert_document_id; factuur_gestorneerd 1.0; creditnota-norm).
De keten is live bewezen op 24-08 (F4-cutover: 1.2-event én gestorneerd-event
beide 200 afgeleverd na redrive).

---

## Vooraf — woensdag 26-08 (vandaag)

- [ ] **Warme start geverifieerd** (`scripts/gcp/warme_start_verificatie.sh`
      groen; minScale 1 + /health < 2 s) — geen koude backend tijdens de
      omschakeling.
- [ ] **Deploy-freeze afgesproken**: donderdag geen deploys tijdens het
      omschakelvenster; de steigerbouw-deploy is al geland (25-08) — eventuele
      volgende runs pas ná S2 laten pushen.
- [ ] **Webhook-kanaal gezond**: outbox leeg, geen dead-letters, laatste
      afleveringen 200 (Instellingen/audit of CLI).
- [ ] **Met Vastly bevestigd** (één bericht):
      tijdslot + contactpersoon donderdag; startadministratie = Rubicon;
      hun V7-criterium groen (≥ 95% schaduw-dekking Rubicon én nul afwijkingen
      voorsortering vs menskeuze over de laatste 25 voorstellen);
      1.2- en gestorneerd-verwerker live (bewezen 24-08, alleen herbevestigen).
- [ ] **Lijst administraties voor deze ronde vastgesteld** (Rubicon zeker;
      volgende alleen als Vastly de entiteiten-koppeling + pand↔project-dekking
      daar al rond heeft).

## Donderdag — per administratie (herhaal integraal per administratie)

### Fase V — Vastly (hun klikwerk, wij wachten op "klaar")
- [ ] V1. Entiteiten-koppeling gelegd: `administratie_id` ↔ hun entiteit.
- [ ] V2. Pand↔project-koppelingen op orde (dekking conform hun schaduwmeting;
      ontbrekende koppelingen vangt hun leer-lus, maar lage dekking = uitstellen).
- [ ] V3. Kostenintake omgeschakeld: eigen intake uit, auto-bevestiging aan.

### Fase R — onze kant (klikwerk Peter, PAS ná V3)
- [ ] R1. Instellingen → Administraties → kolom "Vastgoed-koppeling (Vastly)" → schakelaar AAN
      → bevestigingsdialoog benoemt de consequenties → Bevestigen (Beheerder-toggle sinds de
      avondrun 26-08, geauditeerd `is_vastgoed_gewijzigd`; terugval bij een UI-probleem:
      `cd backend && make is-vastgoed-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>` tegen de cloud-DB)
      → vanaf dit moment vuren `factuur_geboekt`-events voor deze administratie.
      NB UIT zetten neemt "Autoboeken Vastly-verkoop" zichtbaar mee uit (409-regel).
- [ ] R2. `project_verplicht` AAN voor deze administratie
      (Beheerder-instelling; de blokkerende check leest live — inkoopfacturen
      zonder project weigeren vanaf nu te boeken).
- [ ] R3. Alleen Rubicon: `afgeletterd_event`-tier staat al AAN (beslispunt 9,
      24-08) — geen actie, wél weten: 2.0-afgeletterd-events beginnen nu te
      lopen zodra de bank-sync afletteringen detecteert.

### Fase T — verificatie samen (pas door naar de volgende administratie als ALLES groen)
- [ ] T1. Eén inkoopfactuur mét TEST-referentie boeken, mét project en
      boekdatum in een open btw-periode → check bij ons: webhook 200 afgeleverd
      (tijdlijn/audit); check bij Vastly: kostregel zichtbaar, pand via
      `project_id` per regel correct, bedragen exact.
- [ ] T2. Diezelfde TEST-boeking storneren (actie 19, reden
      "S2-verificatie") → `factuur_gestorneerd` afgeleverd, Vastly markeert de
      kost gecorrigeerd. NB alléén de TEST-boeking storneren, nooit echte.
- [ ] T3. Echte eerste factuur van de dag gewoon verwerken en het event
      meekijken — de praktijktoets.
- [ ] T4. Bij élke afwijking: STOP voor deze administratie, blocker vastleggen
      (wie/wat/verwacht/gezien), niet doorgaan naar de volgende. Terugdraaien
      kan altijd: R1/R2 weer UIT — events stoppen, niets gaat verloren.

## Aandachtspunten (vooraf doornemen, kost geen klikwerk)

1. **Doorbelasting-spiegels**: zodra een dóél-administratie van de
   Kempen-doorbelasting (Molenhof B/V, Oirschot Recreatie, OVB, Veldhoven)
   `is_vastgoed` aan gaat, vuren spiegel-inkoopfacturen dáár óók
   `factuur_geboekt` (v1.13 §3, bewezen). Vastly moet die verwachten als
   gewone kostregels (leverancier = Kempen Facilities). Benoemen in het
   vooraf-bericht als een van die doelen in deze ronde zit.
2. **project_verplicht-neveneffecten** (door Vastly akkoord bevonden 13-08):
   samenvoegen uit, AI-extractie-restwerk handmatig bij ontbrekend project —
   de werkvoorraad kan die dag iets meer handwerk tonen; dat is verwacht gedrag.
3. **Storno-detectielatentie**: storno's die iemand rechtstreeks in de RLZ-UI
   doet, detecteert de dagelijkse reconciliatie (≤ 24 u, contractueel §3b).
   Directe events komen alleen uit module-storno's.
4. **Aangifte-poort**: storneren van een boeking in een ingediende
   btw-periode is geblokkeerd — daarom T1 expliciet in een open periode.
5. **Idempotentie**: events dragen `volgnummer` per document; Vastly verwerkt
   hoogste-wint. Een eventuele redrive is dus altijd veilig.

## Ná afloop (donderdag)

- [ ] Per administratie de uitkomst vastleggen: BESLISSINGEN-rij "S2" +
      Platform/OPEN_ITEMS.md bijwerken (capture-at-acceptance).
- [ ] Vastly schriftelijk bevestigen welke administraties om zijn.
- [ ] Vrijdag + maandag: dagelijkse reconciliatie-uitkomsten en de
      werkvoorraad-signalen even bewust nakijken (eerste levende dagen).

*Opgesteld 26-08 (Cowork); klikwerk = Peter, Vastly-kant = Vastly.
Bij twijfel tijdens de dag: stoppen en overleggen — er is geen enkele stap
die niet kan wachten of terug kan.*
