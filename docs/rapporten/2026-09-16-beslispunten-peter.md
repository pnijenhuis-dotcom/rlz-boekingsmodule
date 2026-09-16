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
   gebouwen 30–50 jr tot bodemwaarde (WOZ). **Steigermateriaal: vraag — fiscaal minimaal 5 jaar (20 %), praktijk 7–10 jaar.**
4. Automatisch aanmaken van het activum ná boeken = opt-in per administratie (default UIT).
5. Bijkomende kosten toevoegen aan een bestaand activum: voorstel + mens bevestigt in de testfase.
6. Bouwvolgorde: RLZ eerst, op een administratie mét activa; Odoo (Universal Verkoop) pas als daar asset-modellen zijn ingericht.
7. MVA-rekening = `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx (de vlag alleen is bij Universal te breed).

## Opdracht 4 — omzetbronnen: besluiten Peter 16-09 verwerkt (`2026-09-16-omzetbronnen-besluiten.md`)

1. **Sunshine Island eigen administratie/BV?** Default: zelfde administratie als Elderveld (beide namen in `stores` via het blok).
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
   nooit. Alternatief: Beheerder-only.
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

