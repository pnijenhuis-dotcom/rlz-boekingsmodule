# Beslispunten voor Peter — run 16-09 (defaults gekozen, werk is doorgegaan)

Per opdracht de keuzes waar de opdracht ruimte liet of waar de bouw van de opdracht afweek. Default = wat nu gebouwd is; een ander
besluit is een vervolg-opdracht via `opdrachten/inbox/`. Werkt in productie: n.v.t. (beslispuntenlijst, geen bouw) — per opdracht
staat de productiestand in het eigen rapport (overal: niet gemeten).

## Opdracht 1 — duplicaat Zenvoices / dubbele betaling / bewust verwijderd (`2026-09-16-duplicaat-zenvoices.md`)

1. **Zelfde bedrag + datum, ánder nummer → oranje signaal, geen blokkade.** De opdracht vroeg blokkerend; twee gelijke facturen van
   één leverancier binnen dertig dagen komen legitiem voor en er is voor een externe treffer geen mens-override — blokkeren blijft
   voor de genormaliseerde referentie (met of zonder gelijk bedrag). Alternatief: ook blokkeren + "Geen duplicaat"-afmelding voor
   externe treffers bouwen.
2. **Extern CONCEPT** (bv. een Zenvoices-concept) blokkeert het boeken maar wordt niet direct afgevoerd (dagrem, blok 4 08-09
   beslispunt 1 blijft open).
3. **Normalisatie**: spaties tussen cijfergroepen = groepering ("2 4594 001722" ≡ "24594001722"); een spatie ná een woord blijft een
   nummerdeel-scheider ("document 03" ≡ "document 3") — gevolg: een IBAN mét spaties ≠ zonder spaties (IBAN-referenties zijn sowieso
   uitgesloten).
4. **`duplicaat-extern-rapport` is RLZ-only** (Odoo zichtbaar overgeslagen). Dubbele-betaling-venster 60 dagen en horizon 400 dagen
   zijn constanten; geen actie "terugvordering aanvragen" op de rij (signaal + acceptatie).
5. **Blok D zonder `Afwijzing`-rij**: de DB-CHECK `afwijzing_herkomst_herstelbaar` laat herkomst `geboekt` niet toe en migraties waren
   voor dat blok niet beschikbaar; gebouwd met een eigen tijdlijn-marker + "Terugdraaien…" in Inzicht › Reconciliatie (trekt ook de
   acceptatie in). Alternatief: migratie die de CHECK verbreedt, daarna over op `wijs_af`/`heropen` (heropen-knop op het document).
6. **Eigen-DB-lezing productie** was in deze run niet mogelijk (Cloud-Shell-SQL geweigerd door de auto-mode-classifier); de
   documenthistorie is uit Cloud Logging gereconstrueerd. Wil je zulke lezingen structureel, dan een lees-only CLI `document-inspect`
   in de nameting-allowlist (vervolg-opdracht).

## Opdracht 2 — intercompany-factuurmatch + RC-aansluiting (`2026-09-16-intercompany-rc.md`)

1. **Venster 400 dagen** (default) i.p.v. "vanaf boekjaar 2025".
2. **RC-datumtolerantie ± 5 dagen** (default); 10 dagen als bank-overboekingen rond maandeinde structureel later landen.
3. **Naam-only-relaties alleen rapporteren** (status afgeleid, basis naam, oranje "vermoedelijk — bevestigen") tot een Beheerder
   bevestigt; pas dan tellen ze mee in de factuurmatch.
4. **IC-status-verschil pas ná 7 dagen** (default) — niet direct.
5. **RC-herkenning zonder "≥ 2 tokens"-eis**: "Kempen B.V." (één woord "kempen") wordt als heel woord herkend in
   "Rekening-courant Kempen B.V."; langste treffer wint, meerduidig = niet invullen. Blijkt dit te ruim (valse koppelingen), dan
   de token-eis alsnog of Beheerder-afkortingen als enige bron voor korte namen.
6. **Handmatige IC-leveranciers zonder doorbelasting-mapping** (instelling 08/09-09) krijgen geen relatie — de oude IC-vlag
   blijft voor hen gelden; een KvK-nummer op die crediteur in RLZ maakt de kvk-match mogelijk.
7. **Verrekend paar (factuur + credit, netto € 0) zonder tegenkant** = alleen een teller, geen bevinding; bedrag-only-match = stil.
8. **RC-verklaring zonder boekstuknummer** op RLZ-mutaties (JournalEntry geeft alleen id/BookDate/DocumentType/EventID); wil
   Peter het boekstuk, dan één extra leesroute per restmutatie.
9. **Doorbelastingspaar rood = systeemfout** (audit `automatisering_regressie`, systeemmail, bewakingsprobe) — geen gewone
   kantoor-bevinding.

## Opdracht 3 — activa / MVA STAP-0 + ontwerp (`2026-09-16-activa-stap0.md`, `docs/ONTWERP_ACTIVA_MVA.md`)

1. Activeringsgrens € 450 excl. btw; RLZ-instelling `FixedAssetAlertAmount` (staat op 450) is de bron als die gevuld is.
2. Methode default lineair, restwaarde 0.
3. Termijnen per rekeningcategorie: inventaris 5 jr, vervoermiddelen 5 jr, computers/software 3 jr, machines 5 jr (5–10),
   gebouwen 30–50 jr tot bodemwaarde (WOZ). ~~Steigermateriaal: vraag — fiscaal minimaal 5 jaar (20 %), praktijk 7–10 jaar.~~
   **BESLIST Peter 16-09 (avond): steigermateriaal 5 jaar, lineair, restwaarde 0 — de fiscale ondergrens is de default.**
   Vastgelegd in `docs/ONTWERP_ACTIVA_MVA.md` §3 (termijnentabel) + §8; het ontwerp zelf blijft TER AKKOORD (één parameter,
   geen bouw-GO).
4. Automatisch aanmaken van het activum ná boeken = opt-in per administratie (default UIT).
5. Bijkomende kosten toevoegen aan een bestaand activum: voorstel + mens bevestigt in de testfase.
6. Bouwvolgorde: RLZ eerst, op een administratie mét activa; Odoo (Universal Verkoop) pas als daar asset-modellen zijn ingericht.
7. MVA-rekening = `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx (de vlag alleen is bij Universal te breed).

## Opdracht 4 — omzetbronnen: besluiten Peter 16-09 verwerkt (`2026-09-16-omzetbronnen-besluiten.md`)

1. **Sunshine Island eigen administratie/BV?** ~~Default: zelfde administratie als Elderveld (beide namen in `stores` via het blok).~~
   **BESLIST Peter 16-09 (avond): eigen BV, dus een eigen administratie** — verwerkt in opdracht
   `2026-09-16-omzet-store-naar-administratie-en-vanboxtel-herkenning.md` (store → administratie platformbreed).
   **GEBOUWD 16-09 avond** (migratie 0151, rapport `2026-09-16-omzet-store-routering.md`): beide administraties bestaan al in
   productie (Zonnestudio Elderveld B.V., Sunshine Island B.V.); Peter koppelt de stores op Instellingen › Boeken › Stores.
2. **Eten/drinken 9 %** (default laag); alcohol/horeca → `eten_drinken_tarief = hoog` per administratie.
3. **Rittenkaart/abonnement = omzet bij verkoop** (default; fiscaal btw-correct).
4. **Tegenzijde in RLZ = AFLETTERING** (Receipt blijft open post; PIN/Stripe via actie 15, storting direct op kas). Het cash-deel
   van een zonnestudio-dag blijft in RLZ open op de Receipt tot de kas een RLZ-vorm heeft; alternatief = STAP-0 lees-only (waar
   landt een entity-loze Receipt, sluit QuickPaymentSelection "contant" een deel) en daarna een memoriaal-tussenrekening.
5. **Stripe-kosten in de aangifte:** als negatieve Receipt-regel met verlegd-tarief landen ze in rubriek 1e, niet 4b/5b;
   rubriek-correct is een maandelijkse inkoopfactuur op crediteur Stripe uit dezelfde export.
6. **PIN-venster 0…+5 d en PIN-kernen** (ccv/worldline/adyen) zijn aannames — bijstellen op de eerste echte PIN-afrekening.
7. **Blok Omzetbronnen op tab Boeken & AI**, geen eigen tab Omzet; "Herstel standaard" laat stores staan.
8. **Puntenwaarde** is geen beslispunt meer (punten = omzet bij verkoop, akkoord Peter 16-09).

## Opdracht 5 (rij 2, middag) — groep bulk-toewijzen (`2026-09-16-groep-bulk.md`)

1. **Verwijderen uit een groep via de dialoog raakt alleen leden van díe groep**; een administratie in een andere groep wordt nooit
   stil losgemaakt (uitkomst "overgeslagen: zit in groep X").
2. **"— geen groep —" in de bulkbalk** loopt per administratie over de bestaande enkelvoudige route (N calls); de bulk-route is
   groep-gebonden.
3. **Geen groep-veld in de Odoo-wizard** (beslispunt 11-09 blijft open).
4. **`||`-fallbacks in deploy.yml zijn weg** (opdracht 1): een ontbrekend secret-slot = rode deploy + mail, geen revisie zonder config.

## Opdracht 6 (rij 2, middag) — groepssaldi debiteuren/crediteuren (`2026-09-16-groepssaldi.md`)

1. **Rekeningdetectie via RGS (`BVorDeb…`/`BSchCre…`) met naam-terugval**, niet via `UseForSalesInvoiceDetails`/
   `UseForPurchaseInvoiceDetails` (die vlaggen markeren detailregel-rekeningen, geen subadministratie). Alternatief bij valse
   treffers: Beheerder-override per administratie (vervolg-opdracht).
2. **Intercompany = OPEN POSTEN (Status 2 / niet betaald)** op IC-entity's met tegenpartij in de groep — niet de journaalregels per
   entity (RLZ-journaalregels dragen geen Entity). Concept-IC-facturen (Status 1) tellen niet mee.
3. **Crediteuren als positieve schuld** (Credit − Debit); debiteuren Debit − Credit.
4. **Zonder `--datum` geen datumfilter** (alles t/m vandaag, incl. eventueel vooruitgedateerde boekingen); mét `--datum` de NL-dag
   als UTC-grens.
5. **Kaart leest uitsluitend de nachtelijke stand** (07:00 in sync-alles); wil Peter een "nu meten"-knop, dan een Cloud Run-job-
   trigger zoals bij de reconciliatie (vervolg).
6. **Odoo-IC alleen via de bestaande partner-vertaling** van de IC-run (vendor_cache → res.partner → uuid5); niet vertaalbaar =
   IC 0 voor die kant, zichtbaar via de statuskolom alleen als de hele meting faalt (open punt: aparte LET-OP per kant).

## Opdracht 7 (rij 2, middag) — bankscherm zoekveld + batch-stap (`2026-09-16-bank-zoekveld-batch.md`)

1. **Batch-stap vóór stap 1** (sleutel-gelijkheid wint van naam/nummer-heuristiek); tekenmismatch-posten tellen niet mee.
2. **Oranje batch is afletterbaar** (gevonden posten koppelen, verschil blijft open). Alternatief: alleen groen.
3. **Idempotentie via `rlz_koppelingen`** (document-id); geen extra RLZ-call vóór de N × actie 15 buiten de bestaande vooraf-toets.
4. **Sync-expand `Document($expand=Entity,PaymentTermList)` mét terugval bij 400** — ongeverifieerd op RLZ; blijkt het 400, dan is
   een per-document-leesronde voor batch-mutaties (begrensd) de volgende stap.
5. **Zoekveld client-side**, geen server-zoekroute; KPI-kaarten tellen over alle mutaties, de teller in de kop over het filter.

## Opdracht 8 (rij 2, middag) — documentenlijst bulk-acties (`2026-09-16-documentenlijst-bulk.md`)

1. **"Alle N in deze weergave" = client-side** (zichtbare rijen als id-lijst, ≤ 500); server-side "alle" alleen op de duplicaat-tab.
2. **Type wijzigen** kiest uit inkoopfactuur / kassarapport / verplichting; verkoopfactuur en waarborg blijven systeemsoorten.
3. **ter_accordering** blijft selecteerbaar; de server slaat 'm over mét reden (geen dubbele client-poort).
4. **Verzamelbak** ongewijzigd (had al bulk-toewijzen/hoort-niet-bij-ons, blok B 02-09).

## Opdracht 9 (rij 2, middag) — omzet coffeeshop ProfX Journaal (`2026-09-16-omzet-profx.md`)

1. **Edible-tarief = vrijgesteld** (cannabis-edibles) mét niet-blokkerende controle "eerste keer bevestigen" (oranje chip op de regel);
   gewone edibles 9 % = mens kiest de btw-code, de mapping onthoudt het daarna.
2. **Boekdatum = startdag van de rapportperiode** (05:00→05:00 = één kassadag); een periode over meerdere dagen = eerste dag.
3. **Margerapport zelfde dag = bundelen in het journaal** (kostprijs per groep gevuld, wederhelft `samengevoegd`), nooit apart boeken;
   afwijkende periode (weekrapport) = eigen document mét één kostprijsmemoriaal per rapportperiode en dekkingscontrole (niet blokkerend).
4. **Kostprijs-tegenrekening = de bestaande mapping-kolom** (voorraad-tegenrekening in de kaart "Kostprijs → memoriaal"); een aparte
   instelling "direct kas-inkoop" is niet gebouwd (mens kiest de rekening, mapping onthoudt).
5. **Marge-kleur in het scherm 35–70 %** (oranje buiten die band) is presentatie; de harde marge-plausibiliteitscheck vs eigen historie blijft
   de poort.
6. **Margerapport zonder journaal in dezelfde mail** → afzender-regel of verzamelbak (nooit gokken); een dagelijks los margerapport koppelt
   ná herclassificatie/toewijzing alsnog live via de periode-dekking.
7. **Profielchip in het omzetscherm** is afgeleid uit het herkende kassarapport zelf (de Beheerder-route `GET …/kassa-profiel` is
   Beheerder-only); de override-stand is alleen in Instellingen zichtbaar.

## Opdracht 10 (rij 2, middag) — vragen-dialoog open tot Afgehandeld (`2026-09-16-vragen-dialoog.md`)

1. **Legacy `beantwoord` niet omgezet** naar open (de opdracht noemt "samenvouwen"): die vragen zijn onder het oude model bewust gesloten en
   hun documenten al vrijgegeven — heropenen zou boeken opnieuw blokkeren. Ze blijven historie, wél heropenbaar via "Heropenen".
2. **"Afgehandeld namens" = élke kantoorrol binnen de scope** (niet alleen Beheerder), mét expliciete vlag en eigen audit-actie; klant-accordeurs
   nooit. ~~Alternatief: Beheerder-only.~~ **BESLIST Peter 16-09 (avond): bevestigd — iedere kantoorrol binnen de scope, mét audit
   `vraag_afgehandeld_namens`.**
3. **Heropenen alleen vanuit een herstelbare herkomst** (te_controleren / handmatig_afmaken / klaar_om_te_boeken) en nooit als er al een open
   vraag staat; een geboekt document heropent niet (tegenboeken is de route).
4. **Bundelvenster 10 minuten per beurt**: het eerste bericht van een nieuwe beurt meldt direct (bestaand gedrag), volgende berichten binnen
   10 min gaan mee in de 10-min-job als "N nieuwe berichten". Alternatief: alles altijd via de job (max 10 min vertraging).
5. **Werkvoorraad-groep op de afgeleide kant**: een open vraag met de beurt bij kantoor (of zonder toegewezene) telt als kantoorwerk in de
   standaardlijst — herziet blok 11 08-09 ("open vraag = wachten") conform de opdracht; tellers volgen `Document.toegewezen_aan`.
6. **Geen push naar kantoor** bij een accordeur-bericht (bestaand: signaal via `toegewezen_aan` + werkvoorraad); een kantoor-melding is een
   apart vervolg.

## Opdracht 11 (rij 2, middag) — omzet-Receipts onder Uitgaven bij Van Boxtel (`2026-09-16-omzet-binder.md`)

1. **Diagnose wijkt af van de aanname in de opdracht:** niet de binder van de Receipt-categorie was fout (die is Inkomsten), maar de
   documenten waren als INKOOPFACTUUR geboekt. Blok B is daarom defensief gebouwd (categorie op binder + check + keuze), blok C
   richt zich op de echte wortel (omzet in de inkoopstroom).
2. **Leesroute `DocumentCategories?$expand=DocumentBinder` NIET in de rechten-probe-set** (wizard-tekst "10 leesroutes" en de
   probe blijven ongewijzigd); de omzet-check meldt een 403 zelf als blokkerende check-rij. Alternatief: 11e probe-route.
3. **Reconciliatie-detectie alleen op "alle regels op een omzetrekening"** (lokaal, goedkoop); PDF-herkenning als tweede signaal
   alleen in de CLI (`--met-pdf`) — geen dagelijkse PDF-lezing van alle geboekte inkoopfacturen.
4. **Herstel = storno + herclassificatie, geen categorie-PUT op een geboekte SalesInvoice** (niet getest in STAP-0, geen writes in
   deze run); de mens boekt daarna zelf als omzet (harde checks opnieuw) — geen automatische massale herboeking.
5. **Een mens mag bewust een niet-Inkomsten-categorie kiezen** (oranje signaal in de check, geen blokkade); automatisch kiest de
   motor nooit buiten Inkomsten.
6. **Geen migratie:** herkomst en keuzelijst in `omzet_instelling.bron_instellingen` (JSON), id in de bestaande kolom.

## Opdracht 12 — verplichting-scherm projectveld (`2026-09-16-verplichting-projectveld.md`)

1. **Bouwadvies Oost Nederland heeft in Reeleezee 0 projecten** (lees-only gemeten, blok D uitkomst a). Vraag: wil deze administratie
   überhaupt op projecten boeken (projecten-toggle/projectplicht per administratie aanzetten en projecten aanmaken via
   Beheer › Projecten), of hoort het projectveld daar verborgen te zijn? **Default gebouwd:** veld zichtbaar, niet verplicht, lege
   stand mét "Project aanmaken →" en (voor kantoorrollen) "+ Nieuw project…" in de lijst.
2. **Projectcode = cijfer-prefix van de RLZ-naam** (RLZ kent geen codeveld). Een projectnaam zonder cijferprefix (bv. "Overhead")
   krijgt geen code en blijft op naam sorteren; geen eigen kolom, geen migratie. Alternatief: eigen kolom + sortering op code
   over álle administraties heen — alleen zinvol als er administraties zijn met een andere naamconventie.
3. **"Opnieuw" bij een laadfout** staat op de schermen die al een herlaadsleutel hadden (verplichting, boekvoorstel,
   projectverdeling); elders is de fout wél zichtbaar in de lijst maar herlaadt de gebruiker via de pagina.

## Opdracht 13 (avond) — VGG run 2 blok 9: SCHRIJF b, 1001-model (`2026-09-16-vgg-schrijf-b.md`)

1. **Geen kandidaat én meerduidig gaan allebei naar de TUSSENREKENING**, niet naar de Odoo-bankrekening (Odoo: bank uitsluitend via
   statement lines). De opdracht zei "meerduidig = niet toewijzen" — dat is zo (geen mutatie geclaimd, eigen teller); de bestemming van
   de regel is dan de suspense/tussenrekening mét de kandidaat-nummers in de reden. Alternatief: meerduidig op de bank laten staan.
2. **Bewijs 1 (PaymentReferenceList) zonder datumeis** — de koppeling ís het bewijs; Δ dagen wordt wél gerapporteerd. Bewijs 2 eist
   ± 3 kalenderdagen (`VENSTER_DAGEN`), zelfde tekenrichting en cent-exact; alleen VRIJE mutaties (zonder enige koppeling) doen mee.
3. **Eén outstanding-rekening voor in- én uitgaand** (de 1012-resolutie leest alleen de uitgaande betaalmethode-regels). Odoo kent
   Outstanding Receipts apart; stelt Peter twee verschillende rekeningen in, dan een tweede resolutie op `inbound_…` (kleine uitbreiding).
4. **Status/blokkades van het memoriaal ongewijzigd** — het model verplaatst alleen de bestemming van de 1001-regel; een memoriaal dat
   om een andere reden niet vertaalbaar is blijft dat.
5. **Restcategorie bank/tussenrekening: bekende componenten + één restant mét regel** ("RLZ-opruimpunten / afletterstand — SCHRIJF c")
   i.p.v. een regel-per-mutatie-verklaring; Σ categorieën = groepsverschil (getest). Fijner uitsplitsen = pas als de vierde meting laat
   zien dat het restant niet 0 is.
6. **Bewijspaar SCHRIJF c = RLZ-01-00000082** (verkoopfactuur notaris 2026-03-19, € 400.000) — gekozen uit het 15-09-rapport, zonder
   pand-code (het rapport toont panden niet op documentniveau); de vierde meting bevestigt pand + statement line vóór SCHRIJF c.
7. **Vierde meting niet in deze run** (gcloud-sessie verlopen én code vóór deploy) → vervolg-opdracht in de inbox; Peter logt eerst
   gcloud in.

## Opdracht 14 (avond) — accordeur-uitnodiging web vs app (`2026-09-16-accordeur-uitnodiging-web-vs-app.md`)

1. **Zelfservice-koppeling zonder migratie:** kenmerk = een uitnodiging die de gebruiker ZELF aanmaakte (`aangemaakt_door` =
   `gebruiker_id`), soort blijft `uitnodiging`. Alternatief: eigen soort `toestel_koppeling` (CHECK-constraint verbreden = migratie).
2. **Maximaal 3 actieve toestellen** per app-gebruiker (`app_max_toestellen`), getoetst bij aanmaken én op het koppelmoment.
3. **Legacy-login-hint voor iedereen dezelfde tekst** ("Update de app naar 1.1 of gebruik de web-versie") i.p.v. een apart
   `account_zonder_wachtwoord`-antwoord — dat zou verraden dat een account bestaat (0022). Alternatief: wél onderscheiden, alleen
   voor adressen mét een actieve toestel-rij.
4. **Het web-scherm toont de activatiecode niet** (de server bewaart alleen de hash); de tekst verwijst naar de mail. Alternatief:
   de code ook op de `/uitnodigingen/info`-route teruggeven = geheim lekken op een publieke route — bewust niet.
5. **Store-versie als setting** (`STORE_APP_VERSIE_IOS` default 1.0, Android leeg) i.p.v. een live store-lezing; Peter zet 'm bij ná
   goedkeuring (klikpunt in §0f). Gevolg nu: de mail toont géén App Store-link maar de TestFlight-instructie.
6. **"Open in de app" op een mobiele browser = instructie + Mail-app openen**, geen automatische app-switch: Safari/Chrome openen een
   universal link naar het eigen domein niet vanuit de pagina zelf; de link uit de mail-app (of de code in de app) wél.
7. **Toegangscode opnieuw invoeren = lokale verificatie** (de code bereikt de server nooit); de server eist een levende toestel-sessie
   (apparaat-claim, kill-switch bijt). Geen aparte "recent geverifieerd"-claim server-side.

## Opdracht 15 (nacht) — doorbelasting-aansluiting KF ↔ doelentiteiten + herkoppeling (`2026-09-16-doorbelasting-aansluiting-kf-en-herkoppeling.md`)

1. **Bijna-match-drempel** = de bestaande `_is_bijna_match` (prefix ≥ 4 tekens per token, één-op-één, rechtsvorm-tokens genegeerd) —
   uitkomst is altijd een LET-OP, nooit een automatische koppeling. Alternatief: Levenshtein-drempel — bewust niet (ondoorzichtig).
2. **KvK als koppelbasis** kan niet: de whitelist-rij draagt geen KvK (alleen naam + Customer-GUID in de bron). Alternatief: de
   RLZ-Customer in de bron lezen op `ChamberOfCommerceNumber` en tegen `administratie_identiteit.kvk` leggen — extra RLZ-call per rij;
   pas bouwen als exact-op-naam in productie een rij mist.
3. **Venster bedrag + datum = ± 7 d** (`factuurmatch.DATUM_TOLERANTIE_DAGEN`, één matchmotor voor IC-blok én aansluiting) i.p.v. de
   ± 5 d uit de opdracht. Alternatief: eigen tolerantie per blok — twee motoren, bewust niet.
4. **"Doel niet in module" = één bevinding per whitelist-rij** (aantal + som), niet per verkoopfactuur; de CLI-tabel toont wél elke factuur.
5. **Actie "Boek inkoop in doel" alleen bij een open spiegel-taak** (het inhaalpad `boek_spiegel_alsnog` werkt op een
   `DoorbelastingBoeking`); voor Zenvoices-/handmatige verkopen zegt de doe-tekst wat te doen — geen nieuwe boekroute gebouwd.
6. **Concept-verkoopfacturen tellen mee** (opdracht: "geboekt + concept"); een concept zonder inkoop is dus een afwijking mét status
   "concept" in de tabel — accepteren met reden als het bewust een concept is.
7. **Productienameting ná deploy** als vervolg-opdracht in de inbox (regel Peter 08-09: geen code vóór deploy tegen productie).

