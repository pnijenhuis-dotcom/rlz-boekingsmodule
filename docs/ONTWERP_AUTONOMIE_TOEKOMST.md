# Ontwerpnotitie — Autonomie-toekomstlijn (vijf richtingen Peter/agent 10-09-2026)

> **Status: ontwerpnotitie, geen bouw; wacht op akkoord Peter.** Datum 10-09-2026, bundel 10-09 blok E.
> Register: `docs/BESLISSINGEN.md` sectie "ONTWERPNOTITIE AUTONOMIE-TOEKOMSTLIJN". Elke richting hieronder
> krijgt pas een bouwopdracht ná een expliciet akkoord op de beslispunten in §7; schermimpact = mockup vóór bouw
> (WERKWIJZE §UX-review). Dit document is de canonieke uitwerking; het register draagt alleen status + verwijzing.

**Kernprincipes die élke richting onverkort moet halen (CLAUDE.md § Kernprincipes):** (1) RLZ (of Odoo, via de adapter)
is de boekhoudkundige bron van waarheid — deze module is een verwerkingslaag; (2) **code voor cijfers, AI voor taal, mens
voor de knop op geld** — geen LLM in een geldberekening, AI alleen voor extractie/segmentatie/taaloordeel, altijd met een
deterministische toets eroverheen; (3) nooit verwijderen in RLZ of een ander extern systeem — storno (actie 19) is de
terugweg; (4) niets verdwijnt stil — elke weigering, overgeslagen automatisering of AI-uitval is zichtbaar mét reden en
append-only geauditeerd; (5) idempotentie overal (UUIDv5, eigen duplicaatquery, idempotency-keys); (6) secrets buiten code
en git; (7) minimale mens, maximale autonomie — administratie is een filter, signaal zonder handeling is niet af, opt-ins
zijn testfase-drempels, alles schaalt van 2 naar 2000 administraties, en **geen stille no-op**: een lege optionele
voorwaarde = doorlopen, alleen harde voorwaarden (credential, API-key, geldpoort, noodrem) blokkeren — zichtbaar.

Twee afgeleide regels die in dit document telkens terugkomen en die ik als **harde ontwerpgrens** hanteer:

- **AI kiest nooit een rekening.** Een AI-uitkomst is óf een *voorstel* dat een deterministische toets (backtest, checks,
  geheugen) moet passeren, óf een *poort* (ja/nee op iets wat code al bepaald heeft). Nooit een boekhandeling.
- **AI-uitval = doorlopen zonder AI, zichtbaar.** Elk AI-pad valt bij AVG-gate uit / geen API-key / kostengrens / fout
  terug op het deterministische pad met een `overgeslagen`-reden die de reconciliatie-tellers tellen
  (`app/reconciliatie/automatiseringen.py::categoriseer_reden`). Geen enkele richting hieronder maakt een boeking
  afhankelijk van AI-beschikbaarheid.

---

## §0 Samenvatting + volgorde-advies

### De vijf richtingen in één regel elk

| # | Richting | Kern | Aard van de AI-rol |
|---|---|---|---|
| 1 | Boekhouden op uitzondering | Verwachtingsmodel per administratie; wat ontbreekt of afwijkt is het werk, wat klopt loopt door | geen (code); AI alleen in de tekst van het signaal |
| 2 | AI schrijft deterministische regels + backtest | Regel-DSL (JSON) → backtest op 12 maanden mens-boekingen → activatie alleen bij bewezen precisie | AI = regelschrijver (taal → DSL); code = toets en uitvoering |
| 3 | Leren over administraties heen op RGS-niveau | Patronen op RGS-code geaggregeerd, vertaling lokaal per administratie via een mens-bevestigde mapping | geen (code); AI hooguit als mapping-voorsteller |
| 4 | Nachtelijke AI-onderzoeker | Legt bij elk open item deterministisch verzamelde feiten + een AI-samenvatting; nooit een handeling | AI = samenvatter van feiten die code verzamelde |
| 5 | AI-auditor op een steekproef | Beoordeelt blind een aselecte, gestratificeerde steekproef automatische boekingen; foutkans (code) stuurt de autonomie | AI = tweede lezer ("klopt/twijfel"); code = statistiek en sturing |

### Volgorde-advies: **2 → 5 → 3 → 4 → 1**

1. **Richting 2 eerst.** Blok A van deze run activeert leveranciers op een *tel-drempel* ("3 op rij ongewijzigd", CONTRACT_A) en
   blok B introduceert voor bank een *historie-regel* ("100 % zelfde (ledger, taxrate) op ≥ 3 boekingen bij ≥ 6 maanden
   dekking", CONTRACT_B §B1). Beide zijn feitelijk primitieve backtests met een zeer kleine n. Richting 2 vervangt de
   tel-drempel door een echte backtest (precision/recall per regel over 12 maanden) en generaliseert de bank-historie-regel
   naar facturen. Dat levert bovendien **het object waar richting 5 op toetst**: een expliciete, leesbare regel met een
   gemeten precisie — zonder regels is er niets om een foutkans aan te hangen behalve "de leverancier".
2. **Richting 5 als tweede.** De foutkans per administratie/leverancier/regel is de enige eerlijke maat voor "hoeveel
   autonomie is verantwoord". Zij vervangt op termijn ook de per-boeking AI-plausibiliteitstoets van blok B (B2/B3) door een
   steekproef: goedkoper en statistisch sterker. Zonder 5 blijft élke verruiming van de autonomie een gevoelsbesluit.
3. **Richting 3 als derde.** Pas als regels (2) en foutkansen (5) per administratie bestaan, heeft aggregatie op RGS-niveau
   zin: je aggregeert dan *regelpatronen en precisies*, niet ruwe boekingen. Het schaalt de leercurve van ~33 administraties
   nu naar de ~80 die Peter noemt — een nieuwe administratie start niet meer op nul.
4. **Richting 4 als vierde.** Dit is het duurste AI-gebruik (één call per open item per nacht) met het kleinste
   deterministische aandeel. De feitenverzameling (het deel dat code doet) is wél waardevol en kan eerder; de AI-samenvatting
   wacht op een kosten-/nutsmeting.
5. **Richting 1 als laatste.** "Boekhouden op uitzondering" vergt een verwachtingsmodel dat pas betrouwbaar is als de
   regels (2) en de foutkans (5) bestaan; anders is élk "ontbrekend"-signaal een gok met hoog false-positive-risico — precies
   het patroon dat Peter op 09-09 afkeurde ("veel te veel input"). De bouwstenen (`app/terugkerend/`, reconciliatie,
   actiemail) staan er al; wat ontbreekt is de betrouwbaarheid.

### Waar Peters voorstel wringt — en de oplossing

| Wringpunt | Waarom het wringt | Oplossing in dit ontwerp |
|---|---|---|
| "AI schrijft regels" klinkt als AI die de rekening kiest | Kernprincipe 2 | De AI levert een **regelvoorstel in een DSL**; de regel wordt uitsluitend actief als de **backtest in code** de drempel haalt. De AI heeft geen andere uitweg dan via die toets. Een regel zonder backtest-treffers is per definitie inactief. |
| Backtest op "12 maanden historie" botst met de regel dat RLZ-historie niet telt (besluit Peter 10-09, CONTRACT_A; seed-only = oranje sinds 14-07) | Twee besluiten die elkaar raken | Backtest **meet** op alle mens-boekingen (module + RLZ-seed — het zijn allemaal menskeuzes), maar **activatie** vereist ≥ K module-bevestigde treffers (K ≥ 3 conform 10-09). De RLZ-historie vergroot de n van de precisiemeting, zonder dat een regel op RLZ-historie alleen actief wordt. Beslispunt 2. |
| "Blind beoordelen" (richting 5) | Als de auditor de rekening niet ziet, kiest hij er impliciet één — dat is AI die een rekening kiest | De auditor ziet document **én** boeking en oordeelt alleen "klopt/twijfel" mét reden. Blind = *onwetend van wie of wat boekte* (mens/automaat, welke regel) en van eerdere oordelen; niet onwetend van de boeking. |
| "Foutkans stuurt de autonomie" kan méér autonomie loslaten dan de platformdrempels | Volumerem 20/dag, noodrem, harde checks zijn bewuste grenzen | De foutkans kan de autonomie **alleen verkleinen** ten opzichte van de platformdrempels (volumerem per leverancier omlaag, regel terug naar "leert"); nooit vergroten. Beslispunt 5. |
| "AI-onderzoeker legt een conclusie bij elk open item" | Een AI-"conclusie" stuurt de mens; bij een fout oordeel is de mens de verkeerde kant op gestuurd | Naam en vorm: **"Onderzoek"**, geen "conclusie". Feiten (code) staan gescheiden en bovenaan; de AI-tekst is herkenbaar als samenvatting mét chip "AI-samenvatting — controleer de feiten". Nooit een knop op de AI-tekst. |
| Leren over administraties heen raakt de RLS-/AVG-grens | Klantdata mag niet over administraties heen lekken | Uitsluitend **geaggregeerde regelpatronen op RGS-niveau + leverancierskenmerk (btw/KvK)** — geen bedragen, documenten, omschrijvingen. Precedent: `extractie_template` pooled al op kenmerk-sleutel zonder klantdata (BESLISSINGEN "EXTRACTIE-TERUGVAL TEMPLATES"). |
| "Boekhouden op uitzondering" kan gelezen worden als "boek wat je verwacht, ook zonder document" | RLZ = bron van waarheid; een boeking zonder brondocument is fictie | Harde grens: het verwachtingsmodel **signaleert**; het boekt nooit. Een verwachte-maar-ontbrekende factuur is een actie voor de mens (leverancier vragen), nooit een concept in RLZ. |

### Grove omvang (totaal)

| Richting | Blokken | Agent-dagen (indicatie) | Migraties | Jobs/CLI |
|---|---|---|---|---|
| 2 | 4 (DSL+backtest, regelvoorsteller, activatie/UI, tellers) | 8–10 | 2 | 1 job-stap in `sync-alles`, 2 CLI |
| 5 | 3 (steekproef+auditor, foutkans+sturing, UI/mail) | 6–8 | 1 | 1 job (nachtelijk), 1 CLI |
| 3 | 3 (STAP-0 + mapping, aggregatie, lokaal gebruik) | 5–7 | 2 | 1 job-stap, 1 CLI |
| 4 | 2 (feitenverzameling, AI-samenvatting+UI) | 5–6 | 1 | 1 job (nachtelijk) |
| 1 | 3 (verwachtingsmodel bank/omzet, signalen+actie, bewaking via 5) | 6–8 | 1–2 | job-stappen in bestaande runs |

Schattingen op basis van vergelijkbare blokken (autoboek-kandidaten-motor 01-09 ≈ 2 agent-dagen incl. UI; matchmotor-
herziening 08-09 ≈ 1,5). Elk blok volgt de gouden-set-poort (CLAUDE.md § Werkwijze): gouden set groen + productie-nameting
+ rapportregel "werkt in productie: ja/nee".

---

## §1 Richting 1 — Boekhouden op uitzondering (verwachtingsmodel per administratie)

### Wat
- **Invoer:** per administratie (a) het bestaande terugkerende-facturen-signaal (`boekhouding.terugkerend_signaal`: patroon
  maand/kwartaal, `verwacht_op`, `uiterlijk_op`, `ontbreekt_sinds`, prijsstijging), (b) een nieuw *bank-verwachtingsmodel*
  (terugkerende mutaties per tegenrekening-IBAN + omschrijvingskern — dezelfde sleutel als de historie-regel van blok B), (c) een
  *omzet-verwachtingsmodel* voor kassarapport-administraties (verwacht rapport per periode, bandbreedte uit de marge-historie
  die de omzetmodule al kent), (d) de regels uit richting 2 (een regel met precisie ≥ drempel is een verwachting: "deze
  leverancier boekt altijd zo").
- **Motor (code):** dagelijks in `sync-alles`: per verwachting de stand `voldaan` / `ontbreekt` (ná `uiterlijk_op`) /
  `afwijkend` (bedrag buiten bandbreedte, andere rekening dan de regel, nieuwe leverancier zonder regel). "Wat klopt" krijgt
  geen rij; alleen uitzonderingen worden bevindingen.
- **Uitvoer:** bevindingen in de reconciliatie (`reconciliatie_bevinding`, blok `verwachting`) met leesbare titel/wat/doe via
  `app/reconciliatie/teksten.py`, in de **actiemail** ("N zaken vragen je aandacht") uitsluitend die mét handeling; Inzicht ›
  Reconciliatie toont ze met één primaire actie per rij: "Leverancier vragen (conceptmail)" (bestaat al voor terugkerend:
  `terugkerend/kantoorbreed.py::bouw_conceptmail`), "Afmelden — patroon beëindigd" (bestaand `zet_afgemeld`), "Naar de
  boeking", "Regel herzien" (→ richting 2).
- **Waar landt het in de UI:** géén nieuw scherm. Inzicht › Reconciliatie (bestaand) + actiemail + de klantenlijst-KPI
  "uitzonderingen" (tellers-conventie: alleen bij N > 0).

### Waarom
- Vandaag is de werkvoorraad "alles wat binnenkwam"; wat níét binnenkwam ziet niemand behalve via het terugkerend-signaal
  voor facturen (BESLISSINGEN "OPDRACHT 30-08 (2)" blok B, kantoorbreed sinds "INZICHT-KANTOORBREED B1"). Voor bank en omzet
  bestaat geen verwachting: een gemiste huurincasso of een ontbrekend weekrapport valt pas op bij de jaarafsluiting.
- Peters 09-09-feedback ("veel te veel input") en de actiemail-splitsing (BESLISSINGEN "RECONCILIATIEMAIL = ACTIEMAIL +
  SYSTEEMMAIL") geven precies de plek waar uitzonderingen thuishoren: één regel per zaak mét handeling.

### Hergebruik
- `backend/app/terugkerend/service.py` — `detecteer_patroon` (mediaan-tussenpoos ±35 %, `MIN_FACTUREN = 3`), `verwachting`,
  `prijsstijging_pct`, `herbereken_administratie`; tabel `terugkerend_signaal` (migratie 0090) met `verwacht_op`/`uiterlijk_op`/
  `ontbreekt_sinds`/`snooze_tot`/`afgemeld_op`; kantoorbreed overzicht + conceptmail (`kantoorbreed.py`).
- Bank: `app/bank/historie_regel.py::omschrijvingskern` (blok B, deze run) als sleutel; cache `bank_historie_boeking` (0129) als
  bron van de reeks; `bank_relatie_iban` (0127) voor de tegenpartij.
- Omzet: periode-duplicaatbewaking + marge-plausibiliteitscheck in `app/omzet/` (BESLISSINGEN "OMZET-AUTOBOEKEN").
- Reconciliatie: `run.py::Verzamelaar.bevinding`, `BLOKKEN`, vingerafdruk-/delta-motor, `teksten.py::leesbaar`, actiemail
  `bouw_actiemail` (max 10 regels + "en N andere"); tellers `automatiseringen.py` (nieuwe sleutel `verwachting`).

### Nieuw
- Tabel `boekhouding.verwachting` (administratie, soort ∈ {factuur, bank, omzet, regel}, sleutel (vendor_id | iban+kern |
  periode | regel_id), patroon, `verwacht_op`, `uiterlijk_op`, bandbreedte laag/hoog (Numeric), stand, `ontbreekt_sinds`,
  `afgemeld_op`+door, `snooze_tot`, `berekend_op`; RLS; DELETE-grant zoals `terugkerend_signaal` — afgeleide laag). Migratie 1.
- Motor `app/verwachting/` (puur: `bepaal_stand(verwachting, waarnemingen, vandaag)`; DB-laag herbereken per administratie).
- Reconciliatie-blok `verwachting` + teksten + `DOEL_PAD`. Actie "Leverancier vragen" voor bank/omzet = hergebruik conceptmail-
  patroon (schermimpact klein; mockup-aanvulling `inzicht-kantoorbreed.html` één rijvariant).

### Risico's en grenzen
- **Nooit boeken op verwachting.** Een ontbrekend document is een vraag aan de mens/leverancier, geen concept in RLZ.
- **False positives** zijn het hoofdrisico: beëindigde contracten, seizoenspatronen, jaarfacturen die als kwartaal gelezen
  worden. Mitigatie: (a) `uiterlijk_op` met tolerantie 35 % (bestaand), (b) afmelden mét reden blijft de uitweg, (c) een
  patroon dat 2× onterecht "ontbreekt" gaf (afgemeld met reden "beëindigd/onjuist") wordt nooit meer gesignaleerd zonder
  nieuwe waarneming, (d) **bewaking via richting 5**: de auditor-steekproef trekt óók verwachtingssignalen en meet het
  aandeel onterecht → per soort een precisie; onder de drempel gaat die soort terug naar "alleen systeemmail".
- AI-rol: geen. Alleen `teksten.py` (deterministische tekst). Bij AI-uitval verandert er niets.
- Schaal: één rij per verwachting, herberekening per administratie in de bestaande run (één kapotte administratie stopt de
  rest niet — patroon terugkerend).

### Grove bouwomvang
3 blokken, 6–8 agent-dagen, 1–2 migraties, geen nieuwe job (stappen in `sync-alles` + `reconciliatie-alles`).

### Afhankelijkheden
Blok B (omschrijvingskern, `bank_historie_boeking`), richting 2 (regels als verwachting), richting 5 (bewaking precisie).
Zonder 2 en 5 bouwbaar voor facturen/bank/omzet, maar dan zonder betrouwbaarheidsbewaking — daarom als laatste geadviseerd.

### Meetrecept
- Teller `verwachting` in de reconciliatie: verwacht/voldaan/ontbreekt/afwijkend per etmaal en 7 dagen.
- Precisie per soort = 1 − (afgemeld als onterecht / gesignaleerd) over 30 dagen; doel ≥ 0,8 vóór een soort in de actiemail mag.
- Productie: `gcloud run jobs execute rlz-sync --args="-m,app.cli,verwachting-herbereken,--dry-run"` → aantal per soort; na
  deploy de eerste nacht: systeemmail-blok "Verwachtingen" met N gesignaleerd; rapportregel "werkt in productie: ja/nee".

---

## §2 Richting 2 — AI schrijft deterministische regels + backtest (i.p.v. tellen)

### Wat
- **Invoer:** per (administratie, leverancier) de mens-boekingen van 12 maanden (module: `boekvoorstel` + regels + GEBOEKT-
  overgangen; RLZ-seed: `boeking_observatie` bron `rlz_seed`, 36 maanden beschikbaar), voor bank de `bank_historie_boeking`-
  cache (blok B) en de module-bankboekingen.
- **Motor:** (1) een **regel-DSL** (JSON, deterministisch uitvoerbaar); (2) een **backtest** in code die een regel op de
  historie toepast en precision/recall/dekking meet; (3) een **regelvoorsteller**: eerst deterministisch (de bestaande
  motoren leveren al de kandidaat: geheugen-meerderheid, historie-regel k-van-n), daarná optioneel AI voor de gevallen die
  code niet kan verwoorden (omschrijvingskern-varianten, bedragbereiken, "alles van deze leverancier behalve creditnota's");
  (4) **activatie** uitsluitend door code op basis van de backtest; (5) **uitvoering** door het bestaande autoboek-pad.
- **Uitvoer:** regels in `boekhouding.boekregel` met stand `voorgesteld` / `actief` / `leert` / `uitgezonderd` / `vervallen`,
  zichtbaar op het Autoboeken-nav-item (tab "Regels") en op de administratie-detailpagina tab Boeken & AI; elke automatische
  boeking draagt `regel_id` in het overgang-detail (naast `automatisch_geboekt`).

### Regel-DSL (voorstel, deterministisch, JSON)

```json
{
  "versie": 1,
  "id": "uuid5(administratie, leverancier_kenmerk, voorwaarden-canoniek)",
  "administratie_id": "…",
  "bereik": "factuur | bank",
  "voorwaarden": {
    "leverancier": { "vendor_id": "…", "kenmerk": { "btw": "NL001234567B01", "kvk": null } },
    "tegenrekening_iban": null,
    "omschrijvingskern": { "bevat_alle": ["huur", "kantoor"], "bevat_geen": ["credit"] },
    "bedrag": { "min": "0.01", "max": "2500.00", "teken": "af" },
    "regelniveau": false
  },
  "uitkomst": {
    "grootboek_id": "…", "grootboek_code": "4400",
    "taxrate_id": "…", "taxrate_naam": "21% (verlegd: nee)",
    "project_id": null,
    "project_regel": "geen | vast:<id> | uit_factuur"
  },
  "backtest": {
    "venster_maanden": 12, "treffers": 14, "juist": 14, "onjuist": 0,
    "module_bevestigd": 5, "rlz_seed": 9, "recall_leverancier": "0.93",
    "gemeten_op": "2026-09-10T03:12:00+02:00", "historie_hash": "sha256:…"
  },
  "herkomst": "deterministisch | ai_voorstel | mens",
  "stand": "voorgesteld | actief | leert | uitgezonderd | vervallen",
  "stand_reden": "backtest 14/14, module-bevestigd 5 ≥ 3"
}
```

Vaste eigenschappen van de DSL:
- **Gesloten grammatica.** Alleen de velden hierboven; geen vrije expressies, geen regex (alleen `bevat_alle`/`bevat_geen` op
  de genormaliseerde omschrijvingskern), geen rekenwerk in de regel. Elke regel is te printen als één leesbare zin
  ("Alles van Huurmaatschappij X tussen € 0,01 en € 2.500 met 'huur' en zonder 'credit' → 4400 Huur, 21 %").
- **Uitkomst = bestaande RLZ-/Odoo-id's** uit de caches (`platform.grootboekrekening`, `taxrate_cache`, `project_cache`); een
  id dat niet in de cache staat of `verdwenen_uit_bron_op` draagt = regel `vervallen` (zichtbaar).
- **Regelniveau bewust beperkt** tot "één regel = kop" of "project uit de factuur" (`app/projecten/match.py`); regelsplitsing
  per factuurregel blijft geheugen-/AI-regel-GB (`geheugen/regel_gb.py`) met mens.
- **Idempotent id** (UUIDv5 over administratie + leverancierskenmerk + canonieke voorwaarden): dezelfde regel twee keer
  voorstellen = dezelfde rij.

### Backtest (code)

- **Populatie:** alle mens-boekingen (niet `automatisch_geboekt`) van het bereik in de laatste 12 maanden; per boeking de
  feitelijke uitkomst (GB, btw, project) — voor RLZ-seed uit `boeking_observatie`, voor module-boekingen uit het geboekte
  boekvoorstel.
- **Treffer** = boeking waarvoor de voorwaarden gelden; **juist** = uitkomst gelijk aan de regel (GB, btw én — bij projectplicht
  — project); **onjuist** = afwijkend. `precision = juist / treffers`; `recall_leverancier = treffers / alle boekingen van de
  leverancier` (hoeveel van de leverancier dekt de regel).
- **Activatiedrempel (voorstel):** `precision == 1.0` **én** `treffers ≥ N` (N = platformbrede Beheerder-instelling, default 10)
  **én** `module_bevestigd ≥ K` (K default 3 — de 10-09-regel "RLZ-historie telt niet" blijft zo voor de activatie gelden)
  **én** dekking ≥ 6 maanden (oudste treffer ≥ 183 dagen terug, conform B1). Eén `onjuist` = niet actief; de regel blijft
  `voorgesteld` mét de afwijkende boeking als link ("waarom niet: 13/14, afwijking dd-mm").
- **Waarom 100 % en niet "≥ 95 %":** een regel met bekende fouten in de historie zou die fouten reproduceren; de mens heeft ze
  destijds bewust anders geboekt. Bij 100 % over N = 10 is de Wilson-ondergrens (95 %) ≈ 0,72 — dat is statistisch dun, wat
  precies de reden is dat richting 5 erop moet toetsen en dat N instelbaar is (Beslispunt 1).
- **Hertoets:** nachtelijk over het rollende venster; een nieuwe mens-correctie op een actieve regel = `onjuist` +1 → regel
  terug naar `leert` (zelfde reset-semantiek als CONTRACT_A "storno/correctie → 0/3"), audit `boekregel_gereset`, tijdlijn op
  het document. Storno van een automatische boeking idem.
- **Historie-hash** in de regel: de backtest is reproduceerbaar; een gewijzigde populatie (nieuwe boekingen) = nieuwe meting.

### AI als regelschrijver (optioneel, ná de deterministische voorsteller)

- Stap 1 is code: uit de geheugen-meerderheid + omschrijvingskernen worden kandidaat-regels *gegenereerd* (één per (leverancier,
  meest voorkomende uitkomst); bank: per (IBAN, kern)). Dat dekt naar verwachting het grootste deel.
- Stap 2 (AI, alleen achter de AVG-gate `intake_ai_ingeschakeld` + API-key + kostengrens): voor leveranciers waar de
  deterministische kandidaat < 100 % haalt maar ≥ 80 %, krijgt de AI de **geanonimiseerde** treffer-lijst (omschrijvingskern,
  bedragklasse, uitkomst-code — geen bedragen op de cent, geen documenten) en de opdracht: "splits in regels binnen deze DSL
  die elk 100 % halen". Schema: sentinel-gebaseerd, 0 unions (regels als array van objecten met verplichte string-velden;
  `""` = niet van toepassing) — registreren in `extractie/schema_poort.py::live_schemas()`.
- **De AI-uitkomst is nooit actief zonder backtest.** Code parseert de DSL strikt (onbekend veld = verworpen), draait de backtest,
  en pas dan geldt dezelfde drempel. Een AI-regel die de backtest niet haalt = zichtbaar "AI-voorstel verworpen: 11/14" in de
  systeemmail-tellers, geen rij in de werkvoorraad.
- Kosten: één call per leverancier-met-restruis per maand; bij ~80 administraties × ~10 zulke leveranciers ≈ 800 calls/maand.
  Prijs volgens de gepinde tabel in `app/config.py::ai_kosten_prijzen_usd_per_mtok` (in deze notitie niet extern
  geverifieerd) — valt onder dezelfde maandgrens van € 100; als apart sub-budget zichtbaar in het verbruiksblok.

### Relatie tot blok A en blok B van deze run

| Bestaand (deze run) | Wat richting 2 ermee doet |
|---|---|
| Blok A: activatie op "≥ 3 op rij exact hetzelfde door een mens" (`autoboek_kandidaten/motor.py::analyseer_reeks`, drempel `autoboek_instelling.drempel_op_rij`) | Wordt de **eerste, snelle** poort ("leert n/3") voor leveranciers zónder 12 maanden historie; zodra historie ≥ 6 maanden bestaat, wint de backtest: regel actief = leverancier actief. De reeks-telling blijft de terugval voor nieuwe leveranciers. Eén schrijver blijft `zet_leverancier_autoboeken` (audit `autoboek_leverancier_geactiveerd` met onderbouwing = regel-id + backtest). |
| Blok A: reset ná storno/correctie (`autoboeken_gereset_op`) | Zelfde hook; reset zet óók de regel op `leert`. |
| Blok B1: historie-regel bank (100 % k = n ≥ 3, dekking ≥ 6 mnd, sleutel IBAN + omschrijvingskern) | Is een DSL-regel met `bereik: bank` en N = 3. Richting 2 maakt N instelbaar, bewaart de regel expliciet (nu wordt hij elke nacht opnieuw afgeleid) en geeft hem een stand + audit. `historie_regel.py` blijft de puur-functie die de backtest voor bank uitvoert. |
| Blok B2/B3: AI-plausibiliteitstoets als poort per automatische boeking | Blijft de poort zolang een regel jong is (precisie gemeten op weinig treffers); richting 5 mag 'm per regel loslaten zodra de foutkans-bovengrens onder de drempel is (Beslispunt 6). |
| Kandidaten-scherm (`AutoboekKandidaten.tsx`, tabs Kandidaten/Actief/Heroverwegen) | Krijgt tab "Regels" (voorgesteld/actief/leert) mét de backtest-chips "14/14 · 5 module · 12 mnd"; "Uitzonderen…" en "Vrijgeven" uit CONTRACT_A gelden per regel én per leverancier. Mockup-aanvulling `autoboek-kandidaten.html` vóór bouw. |

### Hergebruik
`app/geheugen/engine.py::bepaal_voorstel` (gewogen meerderheid, `app_bevestigd`), `geheugen/models.py::BoekingObservatie`
(seed 36 mnd, `regel_omschrijving_raw`), `geheugen/leerlus.py::leg_boeking_vast`, `autoboek_kandidaten/motor.py`
(`analyseer_reeks`, `kwalificeer`, chips), `autoboek_kandidaten/service.py` (`herbereken_administratie`, `hertoets_vendor`,
`zet_drempel`), `documenten/autoboeken.py::probeer_autoboeken_na_extractie` (alle poorten onverkort), `bank/historie_regel.py`
+ `bank/matchmotor.py` (stap 3b), `crediteuren/voorkeur.py` (dubbelen samenvouwen), `documenten/duplicaat_afvoer.py::
normaliseer_referentie`, `extractie/client.py::ClaudeExtractieClient.vraag_json`, `aikosten/service.py::controleer_poort/
registreer_verbruik`, `extractie/schema_poort.py`, tellers `reconciliatie/automatiseringen.py`.

### Nieuw
- Migratie 1: `boekhouding.boekregel` (kolommen conform DSL; JSONB `definitie` + gedenormaliseerde uitkomst-id's voor de
  autoboek-poort; stand + reden; backtest-velden; RLS 0095-patroon; GRANT zonder DELETE — vervallen = stand) +
  `boekhouding.boekregel_backtest_run` (per administratie per nacht: aantallen, duur, historie-hash).
- Migratie 2: `platform.boekregel_instelling` (singleton: N, K, venster; herstel-INSERT in `tests/conftest.py::_clean_tables`).
- Pakket `app/boekregels/` (`dsl.py` parse/valideer/print, `backtest.py` puur, `voorsteller.py` deterministisch, `ai_voorsteller.py`
  achter de gates, `service.py`, `router.py`, `cli_cmd.py`: `boekregels-backtest [--administratie] [--dry-run]`,
  `boekregels-voorstellen`).
- Autoboek-poort: `probeer_autoboeken_na_extractie` toetst eerst een actieve regel (voorwaarden + uitkomst = voorstel), pas dan
  de geheugen-poort; regel-id in het overgang-detail en de audit `automatisch_geboekt`.
- UI: tab "Regels" + regel-chip op het controlescherm ("regel actief: 14/14"); registry-entry; RTL-tests.
- Tellers: sleutel `boekregels` (aan N van M, actief/voorgesteld/leert, AI-voorstellen gedaan/verworpen/overgeslagen).

### Risico's en grenzen
- AI kiest nooit een rekening: de uitkomst van een AI-voorstel is alleen geldig als de backtest bewijst dat mensen die rekening
  al kozen. Een regel kan nooit een uitkomst dragen die nooit door een mens geboekt is (backtest-treffers = 0 → verworpen).
- Harde checks, duplicaat/vraag, volumerem, accordering, kill-switch blijven in de boekmotor (`documenten/boeken.py`) — een regel
  omzeilt niets.
- **Overfitting-risico** bij AI-gesplitste regels (regel die precies één historische boeking beschrijft): daarom `treffers ≥ N`
  én `recall_leverancier` zichtbaar; een regel met recall < 0,2 krijgt de chip "smal — dekt weinig".
- Sentinel-schema's ≤ 16 unions (`tests/extractie/test_schema_unionlimiet.py` dwingt registratie af).
- RLS: backtest per administratie in `scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID)`; nooit over administraties heen (dat is
  richting 3, en dan alleen geaggregeerd).
- AI-uitval: de deterministische voorsteller draait altijd; AI-stap = `overgeslagen` mét reden in de tellers.
- Storno = terugweg; reset naar `leert` zichtbaar in tijdlijn + audit.

### Grove bouwomvang
4 blokken, 8–10 agent-dagen, 2 migraties, job-stap in `sync-alles`, 2 CLI's. Gouden set: casus "q_autoboek_leren" (blok A)
uitbreiden met een 12-maanden-historie-fixture; nieuwe casus "r_boekregel_backtest".

### Afhankelijkheden
Blok A (activatie-schrijver, reset-hook, uitzonderingenlijst) en blok B (omschrijvingskern, `bank_historie_boeking`,
`aitoets`-gates als voorbeeld). Geen afhankelijkheid van 3/4/5; levert het object voor 5.

### Meetrecept
- Autoboek-aandeel per administratie: automatisch geboekt / alle inkoopboekingen (30 dagen), vóór en ná (doel: stijgt).
- Correctie-percentage ná automatische boeking (storno/herboeking binnen 60 dagen) per regel — moet ≤ het percentage van blok
  A's tel-drempel blijven (anders is de backtest niet beter dan tellen).
- Regels: aantal actief / voorgesteld / verworpen per nacht in de systeemmail; AI-voorstellen gedaan/verworpen/overgeslagen.
- Productie: `gcloud run jobs execute rlz-sync --args="-m,app.cli,boekregels-backtest,--dry-run"` → per administratie
  "kandidaat-regels N, waarvan activeerbaar M"; verwachte uitkomst bij Universal Nederland: de vaste-leveranciers-set (BDO,
  Kader, BOOT) als activeerbaar; rapportregel "werkt in productie: ja/nee".

---

## §3 Richting 3 — Leren over administraties heen op RGS-niveau, vertaling lokaal

### Wat is er al (grep 10-09)
- **Geen RGS in de code.** Repo-brede grep (`rgs`, `rgs_code`, `Referentie Grootboek`) geeft één documentaire treffer:
  `docs/BOUWPLAN.md` r. 759 (fase 5, MI-consolidatie: "gemeenschappelijke grootboek-referentie/mapping (kandidaat RGS)").
- `platform.grootboekrekening` (`app/db/models.py` r. 578–601): `ledger_id`, `administratie_id`, `code`, `naam`, `soort` (RLZ
  AccountType 1–4), `is_totaalrekening`, `verdwenen_uit_bron_op` — **geen RGS-kolom**.
- Het enige bestaande mapping-mechanisme: `boekhouding.odoo_rekening_mapping` (migratie 0111, `app/odoo/models.py::
  OdooRekeningMapping`: rlz_id/code/naam → odoo_id/code/naam, `soort` grootboek|btw|project, `bron`, `versie`, `bevestigd_door/op`,
  append-only) — toegepast vóór het wegen in `geheugen/service.py` via `odoo/mapping.py::vertaal_observaties`. **Dat is exact
  het patroon** voor een RGS-laag: mapping als vertaaltabel vóór de engine, mens bevestigt één keer.
- Precedent voor pooling zonder klantdata: `extractie_template` op kenmerk-sleutel (btw/KvK), bewust zonder RLS omdat de rij
  alleen layout-metadata draagt (BESLISSINGEN "EXTRACTIE-TERUGVAL TEMPLATES").

### Wat
- **STAP-0 (verplicht vóór bouw):** levert de RLZ-API de RGS-code per Ledger (veld op `GET Ledgers`, of alleen in de RLZ-UI)?
  Odoo 19 kent per account geen RGS-veld standaard (l10n_nl-module wél `l10n_nl_rgs`-achtige velden — verifiëren). Uitkomst
  bepaalt of de mapping grotendeels automatisch gevuld kan worden of mensenwerk per administratie is (eenmalig, ~100–300
  rekeningen per administratie; met voorstel op code-prefix en naam is dat een half uur per administratie).
- **Mapping lokaal:** `platform.rgs_mapping` (administratie_id, ledger_id → `rgs_code`, `rgs_versie` (bv. 3.7), `bron`
  ∈ {rlz_api, voorstel_code, voorstel_naam, mens}, `bevestigd_door/op`, `versie`, append-only). Een niet-bevestigde mapping
  telt niet mee in de aggregatie (fail-closed). Beheerder-scherm: tab "Rekeningschema" op de administratie-detailpagina met
  bulk-bevestigen van voorstellen (mockup vóór bouw).
- **Aggregatie (code, nachtelijk, platformbreed):** per (leverancierskenmerk btw/KvK, RGS-code, btw-categorie) het aantal
  administraties en het aantal actieve regels (richting 2) met precisie ≥ drempel. Géén bedragen, géén documenten, géén
  omschrijvingen, géén administratie-id's in de geaggregeerde rij — alleen tellingen. Tabel `platform.rgs_patroon`
  (kenmerk, rgs_code, btw_categorie, `aantal_administraties`, `aantal_regels_actief`, `laatst_bijgewerkt`).
- **Lokaal gebruik:** bij een leverancier zónder lokale historie vertaalt code het RGS-patroon terug naar de lokale ledger via
  de mapping en biedt het als **oranje** prefill aan met herkomst-chip "uit kantoorpatroon (N administraties) — nog niet
  bevestigd". Eerste lokale mens-bevestiging maakt het groen — exact de seed-only-regel van 14-07. Nooit autoboeken op een
  kantoorpatroon alleen.

### Waarom
- ~33 productie-administraties nu, ~80 in zicht: elke nieuwe administratie start op nul en leert dezelfde leveranciers
  opnieuw (KPN, Google, Shell, BDO). Het kantoor wéét al hoe die geboekt worden; de module niet.
- Zonder gemeenschappelijke referentie is aggregatie onmogelijk: rekening 4400 is bij de ene administratie huur, bij de andere
  autokosten. RGS is de enige breed gedragen Nederlandse referentie (ook de MI-fase in BOUWPLAN wacht erop).

### Hergebruik
`odoo_rekening_mapping`-patroon + `odoo/mapping.py::vertaal_observaties` (vertaling vóór de engine), `crediteur_kenmerk`
(btw/KvK, migratie 0082) als leveranciers-sleutel over administraties heen, `crediteuren/voorkeur.py`, geheugen-engine
(`Observatie.bron` uitbreiden met `kantoorpatroon`, gewicht laag, nooit `app_bevestigd`), herkomst-chip-patroon
(`AiChip`/`bron`), Beheerder-tab-patroon Instellingen v3 (`instellingenRegistry.ts`).

### Nieuw
- Migratie 1: `platform.rgs_mapping` (+ `rgs_versie`), migratie 2: `platform.rgs_patroon` (geen RLS nodig: bevat geen klantdata —
  expliciet te toetsen door de AVG-jurist, zie compliance).
- Pakket `app/rgs/` (`voorstel.py` puur: code-prefix/naam → RGS-voorstel; `aggregatie.py`; `service.py`; `router.py`; `cli_cmd.py`:
  `rgs-mapping-voorstellen --administratie`, `rgs-patronen-herbereken`).
- Engine-bron `kantoorpatroon` in `geheugen/engine.py` (gewicht bv. 0,5; altijd oranje).
- UI: tab "Rekeningschema" (Beheerder), chip "uit kantoorpatroon". Tellers: `rgs_patronen` (mappings bevestigd N van M
  administraties; prefills geleverd/bevestigd/gecorrigeerd).

### Risico's en grenzen
- **Privacy-grens (hard):** over administraties heen reizen uitsluitend geaggregeerde tellingen op (kenmerk, RGS-code,
  btw-categorie). Een aggregaat met `aantal_administraties = 1` wordt **niet** gebruikt (heridentificeerbaar) — minimum 2,
  Beslispunt 8. Geen bedragen, geen data van klant-accordeurs. AVG-pakket (`docs/avg/`) krijgt een regel.
- RLS: aggregatie leest per administratie in `scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID)` en schrijft alleen tellingen in de
  platformtabel; lokaal gebruik leest alleen `rgs_patroon` + de eigen mapping.
- **Kantoorpatroon is nooit groen** en boekt nooit automatisch; het versnelt alleen het lokale leren (de eerste bevestiging).
  Dat is bewust conservatiever dan Peters formulering ("leren over administraties heen") — de seed-only-regel van 14-07
  geldt onverkort. Beslispunt 7.
- RGS-versies wijzigen jaarlijks; `rgs_versie` per mapping + hercontrole-signaal bij versie-sprong.
- AI-rol: hoogstens als mapping-voorsteller op rekeningnaam (taal → RGS-omschrijving) achter de gates; de mens bevestigt élke
  mapping. Zonder AI: voorstel op code-prefix + naamwoordenlijst (deterministisch) — voldoende voor de meeste RLZ-standaard-
  schema's.

### Grove bouwomvang
STAP-0 (0,5 dag) + 3 blokken, 5–7 agent-dagen, 2 migraties, job-stap in `sync-alles`, 2 CLI's, één nieuw Beheerder-tabblad
(mockup).

### Afhankelijkheden
Richting 2 (aggregatie van regels i.p.v. losse boekingen), richting 5 (alleen regels met gemeten lage foutkans tellen mee in het
patroon). Bouwbaar zonder 2 op basis van geheugen-meerderheden, maar dan zwakker.

### Meetrecept
- "Eerste-boeking-groen-aandeel" bij nieuwe leveranciers: percentage eerste boekingen waarbij de mens het kantoorpatroon
  ongewijzigd bevestigde (doel ≥ 0,8; onder 0,6 = patroon-bron uit).
- Mapping-dekking per administratie (bevestigd / totaal actieve ledgers) op het tabblad + teller.
- Productie: `gcloud run jobs execute rlz-sync --args="-m,app.cli,rgs-patronen-herbereken,--dry-run"` → aantal patronen met
  ≥ 2 administraties; verwachting: de gedeelde nutsleveranciers verschijnen als eerste.

---

## §4 Richting 4 — Nachtelijke AI-onderzoeker met leesrechten legt onderzoek bij elk open item

### Wat
- **Scope van "open item":** documenten in `te_controleren`/`vraag_open`/`afgewezen` (ter controle) ouder dan X uur, bank-
  mutaties zonder groen voorstel, reconciliatie-bevindingen zonder acceptatie, verzamelbak-rijen. Server-side gepagineerd,
  urgentste eerst, dagelijks gemaximeerd (Beslispunt 9).
- **Feitenverzameling (code, deterministisch):** per item de relevante feiten uit de eigen DB en caches — tijdlijn, geheugen-
  voorstel + `app_bevestigd`, actieve regel (richting 2) en backtest, open vragen, duplicaatsignalen, terugkerend-/verwachting-
  stand, open posten van de tegenpartij (`payment_item_cache`), IBAN-relatie, doorbelasting-context, RLZ-bestaanscheck-uitkomst,
  eerdere correcties van deze leverancier. Alles gelezen in `scoped_session(<administratie van het item>, actor_id=
  SYSTEEM_ACTOR_ID)` — RLS-respecterend; geen aparte lees-only DB-rol bestaat (alleen `boekhouding_app`), dus de leesrol is
  **de systeem-actor met een code-pad dat uitsluitend SELECT's doet** (test: sweep dat `app/onderzoek/` geen schrijvende
  session-calls bevat behalve de eigen onderzoek-tabel + audit).
- **AI-samenvatting (optioneel, achter de gates):** de feitenlijst (geanonimiseerd waar mogelijk: geen IBAN's op de cijfer,
  geen persoonsnamen buiten de tegenpartij) → één call → tekst van ≤ 600 tekens "wat zie ik, wat is waarschijnlijk aan de hand,
  welke van de bestaande acties past" — de AI kiest uit een **gesloten lijst** actie-labels (schema: `enum`, 0 unions), nooit
  een rekening of bedrag.
- **Uitvoer + UI:** uitklap **"Onderzoek"** op de rij in de documentenlijst/bankscherm/reconciliatie: bovenaan de feiten (tabel,
  code), daaronder de AI-tekst met chip "AI-samenvatting — controleer de feiten" en tijdstip; de aanbevolen actie is een
  *gemarkeerde bestaande knop*, geen nieuwe. Nooit een handeling door de onderzoeker zelf. Mockup vóór bouw (rij-uitklap in
  `controlescherm-v2.html`/documentenlijst).

### Waarom
- De controleur besteedt bij een oud open item het meeste tijd aan *context verzamelen* (waar staat de vraag, wat boekten we
  vorige keer, is er een open post). Die context is deterministisch beschikbaar maar verspreid over zes schermen.
- Het past bij kernprincipe 7 (signaal draagt actie) en bij de actiemail: een zaak in de mail kan verwijzen naar een item mét
  klaargezet onderzoek.

### Hergebruik
Tijdlijn (`document_gebeurtenis`), `geheugen/service.py::voorstel_voor`, `terugkerend/service.py::signaal_voor_document`,
`bank/voorstellen.py::laad_matchcontext`, `documenten/checks.py` (uitkomsten), `reconciliatie/teksten.py` (leesbare
feiten-regels — zelfde tekstbron), `extractie/client.py::vraag_json`, `aikosten` (poort + verbruik mét `AiVerbruikReferentie`
per item), `schema_poort`, audit `record_audit_event`, werkvoorraad-DTO-verrijking (`documenten/service.py` lijst-DTO).

### Nieuw
- Migratie: `boekhouding.onderzoek` (soort item, record_id, administratie_id, `feiten` JSONB, `ai_samenvatting` text null,
  `ai_actie_label` text null, `ai_uitkomst` ∈ {gedaan, overgeslagen, uit} + reden, `model`, `kosten_eur`, `geldig_tot`,
  `aangemaakt_op`; RLS; append-only). Item verandert (nieuwe gebeurtenis) → nieuw onderzoek, oude blijft historie.
- Pakket `app/onderzoek/` (`feiten.py` per soort, `samenvatting.py` achter de gates, `service.py`, `router.py` GET per item), job
  `rlz-onderzoek` (nachtelijk, ná `sync-alles`), CLI `onderzoek-draaien [--dry-run] [--max]`.
- UI-uitklap "Onderzoek" op drie lijsten; tellers `onderzoek` (items/gedaan/AI overgeslagen per reden/kosten).

### Risico's en grenzen
- **Nooit een handeling.** De onderzoeker schrijft alleen zijn eigen tabel + audit. Guard-test sweept op schrijvende calls.
- **Sturingsrisico:** een foute AI-samenvatting stuurt de mens. Mitigatie: feiten eerst en gescheiden; taalgebruik "lijkt", nooit
  "is"; actie alleen als label op een bestaande knop; steekproef door richting 5 op "AI-samenvatting klopte niet" (mens klikt
  "onjuist" → telt in een precisie per soort; onder 0,7 = AI-deel uit voor die soort, feiten blijven).
- **Kosten** zijn het hoofdrisico: per open item één call per (verandering) — bij honderden open items per nacht kan dit de
  € 100-maandgrens alleen al opsouperen. Daarom: (a) eigen sub-budget (Beheerder-instelling, default € 25/maand) binnen de
  bestaande meter, (b) alleen items ouder dan X uur en alleen bij een gewijzigde feiten-hash, (c) dagmaximum, (d) het kleinste
  model dat de kwaliteitstoets haalt (de bewakingsprobe gebruikt al `bewaking_ai_model`), (e) prompt-caching op het vaste deel.
  Kosten per item worden gemeten in `ai_gebruik` (bestaand) — vooraf niet geraden; de eerste week draait met dagmaximum 50.
- AVG: dezelfde gate als intake-AI (`intake_ai_ingeschakeld`); documenten zelf gaan niet mee, alleen de feitenlijst.
- AI-uitval: feiten worden altijd gelegd; `ai_uitkomst = overgeslagen` + reden zichtbaar in de uitklap en de tellers.
- Sentinel-schema ≤ 16 unions; gesloten enum voor actie-labels.

### Grove bouwomvang
2 blokken, 5–6 agent-dagen, 1 migratie, 1 nachtelijke job, 1 CLI, mockup-aanvulling.

### Afhankelijkheden
Richting 2 (regel + backtest als feit), richting 5 (bewaking kwaliteit AI-tekst), blok B (gates-patroon `aitoets`).
De feitenverzameling (blok 1) is los bouwbaar en nuttig zonder AI.

### Meetrecept
- Doorlooptijd open items (mediaan uren van binnenkomst tot boeking/afwijzing) vóór/ná per administratie.
- Aandeel items waarbij de mens de gemarkeerde actie koos (doel ≥ 0,6) en aandeel "onjuist"-klikken (≤ 0,1).
- AI-kosten per onderzocht item en per boeking (uit `ai_gebruik`), sub-budget-stand in het verbruiksblok.
- Productie: `gcloud run jobs execute rlz-onderzoek --args="-m,app.cli,onderzoek-draaien,--dry-run,--max,50"` → aantal
  items + geschatte feiten; ná deploy eerste nacht: teller `onderzoek` in de systeemmail.

---

## §5 Richting 5 — AI-auditor beoordeelt een steekproef automatische boekingen → foutkans stuurt de autonomie

### Wat
- **Populatie:** alle automatische boekingen (`automatisch_geboekt` in het overgang-detail; inkoop, bank-vaste-regel/historie-
  regel, omzet, verkoop) van de afgelopen 24 uur, plús — voor kalibratie — een kleine controlegroep mens-boekingen.
- **Steekproef (code):** aselect mét stratificatie per (administratie, leverancier/regel, bereik): elke stratum met ≥ 1
  boeking krijgt minimaal 1 trekking; verder proportioneel tot een dagmaximum (Beheerder-instelling, default 40); zaad =
  sha256(run-datum + stratum) zodat de trekking reproduceerbaar is en niemand (ook geen bug) de selectie kan sturen. Nieuwe
  regels (< 30 treffers sinds activatie) krijgen een hogere trekkans (bv. 1 op 3) dan gevestigde (1 op 20).
- **Auditor (AI, achter de gates):** krijgt per trekking het document (tekstlaag/UBL-kern, zoals de extractie-prompt) + de
  boeking (rekeningcode+naam, btw-omschrijving, project, bedrag) en oordeelt `klopt | twijfel` met een reden uit een gesloten
  lijst + vrije toelichting. **Blind** = hij ziet niet of een mens of automaat boekte, niet welke regel, niet eerdere oordelen,
  niet de leveranciershistorie — zodat "het staat zo in de historie" geen argument kan zijn. Hij ziet **wél de gekozen
  rekening**: zou hij die niet zien, dan zou hij er een moeten kiezen — dat is precies wat kernprincipe 2 verbiedt, en het
  maakt de toets ook zwakker (een tweede lezer die de keuze toetst is betrouwbaarder dan één die opnieuw kiest). Schema
  sentinel/enum, 0 unions. Zelfde client, gates en meter als B2/B3 (`app/aitoets/`).
- **Adjudicatie (mens):** `twijfel` is geen fout. Elke twijfel wordt een rij in een kantoorbrede lijst "Steekproef — te
  beoordelen" (Inzicht, lijstpatroon) met de bestaande acties: "Klopt toch" (reden) / "Onjuist → Tegenboeken…"/"Herboeken…".
  Alleen een **door een mens bevestigde fout** (of een storno/herboeking binnen 60 dagen) telt als fout in de foutkans.
  Ook fouten die buiten de steekproef ontdekt worden (storno van een automatische boeking) tellen mee — dat is het al bestaande
  reset-signaal van blok A.
- **Foutkans-model (code, geen AI):** per (administratie, leverancier/regel) `k` fouten op `n` beoordeelde/gevolgde automatische
  boekingen → **Wilson-scoreinterval** (95 %) bovengrens `p_hoog`; eenvoudig, zonder priors, uitlegbaar in één zin ("van de 40
  gecontroleerde boekingen was er 1 fout; met 95 % zekerheid is de foutkans hoogstens 12 %"). Bayesiaans (Beta-prior uit het
  kantoorbrede gemiddelde) is een latere verfijning voor kleine n — Beslispunt 4. Geen fout en n = 0 = "onbekend", nooit "0 %".
- **Sturing (code, alleen vernauwend):**

| `p_hoog` (95 % bovengrens) | Autonomie-stand van de regel/leverancier | Wat er gebeurt |
|---|---|---|
| onbekend (n < 5) | `actief — onder toezicht` | trekkans hoog (1 op 3); B3-plausibiliteitstoets per boeking blijft aan |
| ≤ 2 % | `actief` | trekkans laag (1 op 20); B3 per boeking mag uit voor deze regel (Beslispunt 6) |
| 2–5 % | `actief — verhoogd toezicht` | trekkans 1 op 5; volumerem per leverancier = ½ van platform (nooit hoger dan 20/dag) |
| 5–10 % | `beperkt` | volumerem per leverancier 3/dag; B3 aan; LET-OP in de reconciliatie mét deeplink |
| > 10 % of ≥ 2 bevestigde fouten in 7 dagen | `leert` | opt-in uit via de bestaande schrijver (`zet_leverancier_autoboeken`), reset conform blok A, audit `autoboek_leverancier_gereset` reden `foutkans`; terug naar actief alleen via de normale leerregel/backtest |

  De sturing kan de autonomie **nooit boven de platformdrempels** brengen (volumerem 20/dag, noodrem, harde checks, AVG-gate).
- **Uitvoer:** stand per regel/leverancier (chip "foutkans ≤ 2 % (n = 63)") op het Autoboeken-scherm; per administratie een
  samengestelde stand in de administratie-lijst; systeemmail: blok "Steekproef: N getrokken, M twijfel, K bevestigd fout";
  actiemail alleen bij "te beoordelen"-rijen ("3 automatische boekingen vragen een blik").

### Waarom
- Vandaag is de enige terugkoppeling op automatische boekingen de toevallige storno/correctie (blok A-reset) en de per-boeking
  AI-toets van blok B (die zichzelf niet meet). Er bestaat geen maat voor "hoe goed boekt de automaat bij deze leverancier" —
  en dus geen verantwoorde basis om de autonomie te vergroten of te verkleinen.
- Een steekproef is goedkoper dan een toets op élke boeking en statistisch sterker, omdat een mens adjudiceert.

### Hergebruik
`app/aitoets/plausibiliteit.py` (client, gates, audit `ai_plausibiliteitstoets`, stub-seam `_client_factory`, schema-registratie),
`documenten/autoboeken.py` (audit `automatisch_geboekt` + `bron`), `autoboek_kandidaten/service.py` (stand per leverancier,
`zet_leverancier_autoboeken`, reset-hook uit CONTRACT_A), `documenten/tegenboeken*.py`/`herboeken.py` (acties), lijstpatroon
kantoorbreed (`AutoboekKandidaten.tsx`/`router.py`), tellers, `reconciliatie/teksten.py`, `aikosten`.

### Nieuw
- Migratie: `boekhouding.steekproef_trekking` (run-datum, document/mutatie-id, administratie, leverancier/regel, bereik, zaad,
  `ai_uitkomst` klopt|twijfel|overgeslagen + reden, `mens_besluit` klopt|fout|null + reden + actor + op, `kosten_eur`; RLS;
  append-only) + `boekhouding.foutkans_stand` (per administratie × leverancier/regel: n, k, `p_hoog`, stand, `berekend_op`;
  afgeleide laag) + `platform.steekproef_instelling` (dagmaximum, trekkansen, drempels; singleton, herstel-INSERT conftest).
- Pakket `app/steekproef/` (`trekking.py` puur, `foutkans.py` puur — Wilson, `sturing.py` puur, `auditor.py` achter de gates,
  `service.py`, `router.py`, `cli_cmd.py`: `steekproef-draaien [--dry-run] [--datum]`), job `rlz-steekproef` (nachtelijk).
- Volumerem per leverancier: kleine uitbreiding van `boeken.py::toets_volumerem` (min(platform, leverancier-limiet)).
- UI: lijst "Steekproef — te beoordelen" (Inzicht), chips op Autoboeken-scherm, tellers `steekproef`. Mockup vóór bouw.

### Risico's en grenzen
- De AI oordeelt over een keuze die code + mens al maakten; hij kiest nooit een rekening en zijn `twijfel` is nooit een
  handeling — alleen een rij voor de mens. Storno/herboeking blijft mensenwerk via de bestaande knoppen (aangiftepoort onverkort).
- Alleen mens-bevestigde fouten voeden de foutkans; anders zou een slecht gekalibreerde auditor de autonomie sturen.
- Kalibratie: de controlegroep mens-boekingen (bv. 5/dag) meet hoe vaak de auditor "twijfel" zegt bij boekingen die het kantoor
  zelf deed — stijgt dat boven ~20 %, dan is de prompt/het model het probleem, niet de automaat (LET-OP beheer).
- Kosten: dagmaximum 40 + 5 controle × prijs per call (gepinde tabel; documenttekst maakt de call groter dan B2/B3) — sub-budget
  default € 20/maand, zichtbaar in het verbruiksblok; boven het sub-budget = kleinere steekproef, nooit stil.
- AI-uitval: trekking + foutkans uit mens-signalen (storno/herboeking) blijven werken; `ai_uitkomst = overgeslagen` mét reden;
  stand wordt dan "onbekend", nooit ten gunste van de automaat.
- AVG: documenttekst gaat mee zoals bij de extractie — dezelfde gate; geen BSN's (bestaande maskering), klant-accordeur-data niet.
- Storno = terugweg; elke sturing (stand-wissel) = audit oud→nieuw + tijdlijnregel op het laatst geraakte document.

### Grove bouwomvang
3 blokken, 6–8 agent-dagen, 1 migratie (drie tabellen), 1 job, 1 CLI, één lijstscherm (mockup). Gouden set: casus met drie
automatische boekingen + één gestubde "twijfel" + mens-adjudicatie → stand-wissel.

### Afhankelijkheden
Blok A (activatie/reset-schrijver), blok B (`aitoets`-gates), richting 2 (regel als eenheid van foutkans — zonder 2 is de
eenheid "leverancier", wat ook werkt).

### Meetrecept
- Bevestigde foutkans per administratie (k/n + `p_hoog`) in de systeemmail, wekelijkse trend; doel kantoorbreed `p_hoog` ≤ 3 %.
- Aandeel automatische boekingen onder "actief" zonder per-boeking-AI-toets (kostenbesparing t.o.v. B3), AI-kosten per
  automatische boeking (steekproef + resterende B3) — moet dalen bij gelijke of lagere foutkans.
- Kalibratie: twijfel-percentage op de mens-controlegroep.
- Productie: `gcloud run jobs execute rlz-steekproef --args="-m,app.cli,steekproef-draaien,--dry-run"` → getrokken N per
  stratum; ná deploy eerste nacht: "Steekproef"-blok in de systeemmail; rapportregel "werkt in productie: ja/nee".

---

## §6 Samenhang — hoe de vijf elkaar voeden

```
mens-boekingen (module + RLZ-seed)         ──►  [2] regels + backtest  ──►  autoboek-pad (bestaand)
                                                     │ regel-id                 │ automatisch_geboekt
                                                     ▼                          ▼
[3] RGS-mapping lokaal ◄── aggregatie regels ◄── [5] foutkans per regel ◄── steekproef + mens-adjudicatie
        │ oranje prefill nieuwe administratie              │ stuurt (alleen vernauwend)
        ▼                                                  ▼
   geheugen-engine (bron kantoorpatroon)         volumerem/regel-stand/B3 aan-uit
                                                           │
[1] verwachtingsmodel (terugkerend + bank + omzet + regels) ──► reconciliatie-bevindingen ──► actiemail
                                                           ▲
[4] onderzoek per open item (feiten code + AI-samenvatting) ─┘  (leest alles, schrijft alleen zichzelf)
```

Gedeelde bouwstenen die één keer gebouwd en door meerdere richtingen gebruikt worden: de `aitoets`-gates + stub-seam (blok B),
de tellers-per-automatisering (sleutel per richting), `teksten.py` als enige tekstbron, het lijstpatroon kantoorbreed, de
reset-/activatie-schrijver van blok A, `scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID)` als leesrol.

---

## §7 Beslispunten Peter

1. **Volgorde 2 → 5 → 3 → 4 → 1 — akkoord?** Advies: ja; alternatief "1 eerst" (Peters intuïtieve volgorde) levert signalen
   zonder betrouwbaarheidsmaat en herhaalt het 09-09-probleem ("te veel input"). Bouw wél de feitenverzameling van 4 (blok 1,
   geen AI) vroeg mee als ze goedkoop meelift met 2 — dat is puur code.
2. **Backtest-populatie en activatiedrempel (richting 2).** Advies: meten op module + RLZ-seed (12 maanden), activeren bij
   precision 100 % ∧ treffers ≥ N (default 10) ∧ module-bevestigd ≥ K (default 3) ∧ dekking ≥ 6 maanden. Alternatief strikt
   10-09 ("RLZ-historie telt niet" ook voor de meting) maakt de n te klein om ooit iets te bewijzen; alternatief soepel
   (K = 0) breekt de seed-only-regel van 14-07. N en K worden Beheerder-instellingen.
3. **AI als regelschrijver (richting 2 stap 2) — nu of later?** Advies: later; eerst meten hoeveel leveranciers de
   deterministische voorsteller níét op 100 % krijgt. Is dat < 15 %, dan is de AI-stap het niet waard.
4. **Foutkans-model (richting 5).** Advies: Wilson-interval 95 % (uitlegbaar, geen priors); Bayesiaans met kantoorbrede prior
   pas als de n's structureel klein blijven. Drempels (2/5/10 %) als Beheerder-instelling, defaults zoals in de tabel.
5. **Sturing alleen vernauwend — akkoord?** De foutkans mag de autonomie nooit boven volumerem 20/dag, noodrem, harde checks of
   AVG-gate brengen. Advies: ja, zonder uitzondering; verruiming van platformdrempels blijft een menselijk Beheerder-besluit.
6. **B3-plausibiliteitstoets per boeking uitzetten bij `p_hoog` ≤ 2 %?** Advies: ja, per regel/leverancier en automatisch weer
   aan bij stand-verslechtering — dat is de kostenwinst van 5. Alternatief: B3 altijd aan (duurder, dubbel werk).
7. **Kantoorpatroon (richting 3) altijd oranje, nooit autoboeken — akkoord?** Advies: ja (consistent met seed-only = oranje).
   Alternatief "groen bij ≥ 10 administraties" zou een boeking rechtvaardigen die in déze administratie nog nooit een mens
   bevestigde — dat wringt met "vertrouwen wordt in de app verdiend".
8. **Privacy-minimum aggregatie (richting 3):** patronen alleen bij ≥ 2 administraties (advies) of ≥ 3? Én: AVG-jurist laten
   toetsen dat (leverancierskenmerk, RGS-code, telling) geen persoonsgegeven is (leveranciers zijn overwegend rechtspersonen;
   eenmanszaken zijn het aandachtspunt — advies: eenmanszaken op KvK-rechtsvorm uitsluiten van aggregatie).
9. **Sub-budgetten AI (richtingen 4 en 5)** binnen de € 100-maandgrens: advies € 25 (onderzoek) en € 20 (steekproef), Beheerder-
   instelbaar, of de maandgrens verhogen? Zonder sub-budget kan de onderzoeker de intake-extractie verdringen.
10. **Dagmaximum onderzoek (richting 4) en definitie "open item ouder dan X uur":** advies 50 items/nacht, X = 24 uur, alleen
    bij gewijzigde feiten-hash.
11. **RGS STAP-0 uitvoeren (richting 3)** — mag de agent bij de eerstvolgende gelegenheid `GET Ledgers` op de TEST-administratie
    op een RGS-veld onderzoeken (read-only) en het Odoo-l10n_nl-veld op company 1 lezen? Advies: ja, kost een half uur, bepaalt
    de omvang van 3.
12. **Verwachtingsmodel bank/omzet (richting 1) pas ná 5** — akkoord, of wil Peter het bank-deel eerder omdat blok B de sleutel
    al levert? Advies: het bank-deel mag als klein blok met 2 meebouwen (zelfde kern), maar alleen naar de systeemmail tot 5
    de precisie bewaakt.

---

## §8 Aangrenzende gaten

**Lifecycle**
- Regels (2) en mappings (3) hebben een einde nodig: leverancier gearchiveerd/samengevouwen (`crediteuren/voorkeur.py`) →
  regel `vervallen` mét reden; ledger `verdwenen_uit_bron_op` → regel/mapping vervallen + LET-OP; RGS-versiesprong → hercontrole.
  Nooit DELETE; stand + reden.
- Onderzoeken (4) en trekkingen (5) verouderen: `geldig_tot`/run-datum; opruimen = niet (append-only, 7 jaar mee met het
  document); UI toont alleen het jongste.
- Administratie gearchiveerd (migratie 0089-patroon): alle vijf slaan haar zichtbaar over ("gearchiveerd") — geen fout, geen stilte.
- Overstap RLZ → Odoo (`boekhoud_backend`): regels dragen uitkomst-id's van één backend; bij overstap vertaalt de bestaande
  `odoo_rekening_mapping` de regel of zet 'm op `leert` mét reden — consistent met A12 (backend-agnostisch via ports).

**Consistentie**
- Drie tel-/leerdrempels bestaan straks naast elkaar (kandidaten-drempel `drempel_op_rij`, B1's k = n ≥ 3, backtest-N): één
  instellingenblok "Leren en autoboeken" met alle drie en hun onderlinge relatie, anders drift.
- `teksten.py` blijft de enige tekstbron voor UI, actiemail en systeemmail (guard `test_actiemail_guard.py` uitbreiden met de
  nieuwe soorten).
- Tellers-sleutels in `automatiseringen.VOLGORDE` (geldpaden eerst): `boekregels`, `steekproef` vóór `verwachting`, `onderzoek`,
  `rgs_patronen`; elke opt-in krijgt een `afwezig_pad`-guardtest (`test_optin_afwezig_pad_guard.py`).
- Eén schrijver voor de leverancier-opt-in blijft `zet_leverancier_autoboeken` — ook de foutkans-sturing gaat daardoorheen.

**UX / branding**
- Nieuwe standen vragen consistente chips: teal = actie, groen = status (`actief`), oranje = `onder toezicht`/`beperkt`, grijs =
  `leert`/`uitgezonderd` — één `standChip`-component voor Autoboeken-scherm, administratie-detail en controlescherm.
- Schermimpact: tab "Regels" (2), lijst "Steekproef — te beoordelen" (5), tab "Rekeningschema" (3), rij-uitklap "Onderzoek" (4),
  rijvariant reconciliatie (1) — vijf mockup-aanvullingen, allemaal binnen de bestaande IA (geen tegels, geen nav-items behalve
  eventueel Inzicht › Steekproef).
- De actiemail moet klein blijven: nieuwe soorten komen er pas in ná bewezen precisie (5); tot die tijd systeemmail.

**Compliance**
- AVG: aggregatie (3) en de feitenlijst (4) vragen een regel in `docs/avg/` (verwerkingsdoel, geen nieuwe verwerker; dezelfde
  Anthropic-verwerkersgrondslag als de intake-AI; ZDR-status uit "VERVOLGRONDE 02-09" blok E geldt).
- Audit: elke stand-wissel, activatie, reset, adjudicatie en AI-call krijgt een `audit_event` oud→nieuw; nooit de prompt of
  documenttekst in de audit (patroon B2).
- Bewaarplicht: onderzoeken/trekkingen horen bij het document (7 jaar); geen aparte retentie.
- Kernprincipe 3 blijft: geen enkele richting verwijdert iets in RLZ/Odoo; de enige terugwegen zijn storno (19), tegenboeken,
  herboeken — alle bestaand en mét aangiftepoort.
- Kostenbeheersing: sub-budgetten binnen de bestaande meter; boven de grens nooit stil (chip + teller), conform "AI-KOSTENGRENS
  INTAKE".

---

*Einde ontwerpnotitie — geen bouw; wacht op akkoord Peter op §7.*
