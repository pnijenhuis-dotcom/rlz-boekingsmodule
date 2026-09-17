# Beslispunten voor Peter — run 17-09 (defaults gekozen, werk is doorgegaan)

Per opdracht de keuzes waar de opdracht ruimte liet of waar de bouw afweek. Default = wat nu gebouwd is; een ander besluit is een
vervolg-opdracht via `opdrachten/inbox/`. Werkt in productie: n.v.t. (beslispuntenlijst) — per opdracht in het eigen rapport.

## Opdracht 1 — SPOED Xcode Cloud / Apple 1.1 live (`2026-09-17-apple-1-1-live-xcode-cloud.md`)

1. **`STORE_LINK_IOS` + `STORE_APP_VERSIE_IOS` óók in `BASIS_ENVS` van de jobs.** De opdracht noemde alleen deploy.yml; de
   herinnerings-/uitnodigingsmails lopen ook uit jobs (rlz-accordeur-herinneringen). Alternatief: alleen de service.
2. **Nameting-via-gh dekt alleen commando's mét een workflow-onderdeel** (doorbelasting-aansluiting, app-bundels, reconciliatie,
   btw-default, a/b/c). Een ad-hoc `rlz-lezen` zonder onderdeel weigert (exit 3) i.p.v. stil op de gebruikerssessie terug te vallen;
   argumenten worden niet doorgegeven (het onderdeel draagt zijn vaste recept). Alternatief: een generiek `workflow_dispatch`-onderdeel
   "cli" mét vrije argumenten (allowlist blijft) — komt terug in opdracht 3 (feiten eerst).
3. **OTA-bundel volgt de gebouwde schil.** De deploy registreert de bundel per RUNTIME = `APP_MARKETING_VERSIE`; ná de bump naar 1.2
   krijgt de live 1.1-schil dus geen OTA-bundel meer (manifest 1.1 = "geen bundel"). Alternatief: de bundel óók onder de store-versie
   registreren (`STORE_APP_VERSIE_IOS`) zolang de schil-code niet veranderde — vergt een compatibiliteitsregel; niet gebouwd.
4. **Service-SA-binding niet zelf gezet** (owner-IAM = Peter, conform de opdracht); klikpunt mét het exacte commando in het rapport.

## Opdracht 2 — SPOED dubbele betaling 1.214 valse bevindingen (`2026-09-17-dubbele-betaling-herdefinitie.md`)

1. **Crediteur in géén enkele cache bekend = geen uitspraak (geen bevinding, wél geteld als `zonder_factuurbron`).** De opdracht
   zegt "betalingen > facturen → bevinding"; zonder factuurbron zou élke tweede betaling aan een onbekende tegenpartij (loon,
   belastingdienst, privé) weer een valse bevinding zijn. Alternatief: onbekende crediteur = bevinding mét label "geen facturen
   bekend" — dat is de 16-09-regel in vermomming; niet gebouwd.
2. **Factuurbronnen = eigen caches, geen live RLZ-call** (module-documenten, RLZ-open-postencache incl. verdwenen, RLZ-koppelingen
   van de mutaties). De opdracht noemde "RLZ/Odoo, alle crediteurrecords"; de open-postencache ís de RLZ-bron (dagelijkse sync).
   Een live PurchaseInvoices-call per kandidaat komt terug als de nameting laat zien dat de cache facturen mist.
3. **Stand-opslag = JSONB-kolom op de bestaande singleton (migratie 0153)** i.p.v. een losse JSON-setting (die bestaat niet als
   generiek mechanisme). Code-defaults in de registry; DB-override wint.
4. **Titels "Automatisering wacht op voorwaarde"/"Automatisering stil" hernoemd** naar "Wacht op instelling"/"Stil sinds zeven
   dagen": door de per-administratie-begrenzing komen platformbrede LET-OP's eerder in de top-10 en de actiemail-guard verbiedt
   het blokwoord. UI-tekst wijzigt daardoor licht.
5. **Promotie van `dubbele_betaling_vermoed` naar de actiemail NIET gedaan** — pas ná de productiemeting (Hello Kitchen wél,
   periodieke tegenpartijen niet). Default blijft `meten`.

## Opdracht 3 — Feiten eerst: lees-toegang + klikpunt-guard (`2026-09-17-feiten-eerst-lees-toegang.md`)

1. **`rlz-lezen --alles` niet gebouwd.** `rlz-feiten` leest zelf volledig gepagineerd (bank in een datumvenster); een kaal
   `--alles` op élk OData-pad is een webfilter-risico (blok 7b) zonder eigen doel. Alternatief: `--alles` mét verplicht
   `--filter` toevoegen als een analyse dat vraagt.
2. **Vrije SQL kent een optionele `administratie_id` i.p.v. een RLS-bypass.** Bank-tabellen (`bank_mutatie` e.d.) hebben een
   strikt administratie-beleid zonder Beheerder-clausule; zonder scope geven ze niets. RLS omzeilen (rol mét BYPASSRLS) is bewust
   niet gedaan. Alternatief: Beheerder-clausule toevoegen aan die policies (migratie, raakt de hele bankmodule).
3. **Bibliotheek-queries op de runtime-verbinding, alleen vrije SQL replica-only.** De bibliotheek is gereviewd en heeft dezelfde
   toegang als élke bestaande lees-only CLI; de replica-eis geldt waar de query vrij is.
4. **Odoo-variant van `rlz-feiten` niet gebouwd** (zichtbaar overgeslagen met reden). Alternatief: `odoo-feiten` via de adapter
   in een volgende opdracht.
5. **Downgrade 0154 laat de rol staan** (cluster-breed; DROP ROLE = owner-handeling).

## Opdracht 4 — VGG schoonlijst dubbelen richting + bank (`2026-09-17-vgg-schoonlijst-dubbelen-richting-bank.md`)

1. **Snede 2 zonder tegenrekening-toets.** Richting is bij inkoopfacturen per definitie gelijk; regels lezen per paar over álle
   administraties is een webfilter-risico (blok 7b). Alternatief: alleen voor clusters "waarschijnlijk dubbel" de regels lezen.
2. **Bankrekening in memorialen = RGS-groep 10xx** (1001, 1011, 1012, 1000). Alternatief: de grootboekkoppeling van PaymentAccounts lezen.
3. **Profiel-split ná de kenmerk-split**; een ongelijk profiel wint altijd.
4. **Klikpunt "bankregel test"** blijft staan als Peters keuze (boeken of terugboeken) — de module doet niets met een € 1-test.

## Opdracht 5 — VGG blok 11 pand = RLZ-project (`2026-09-17-vgg-blok-11-pand-uit-rlz-project.md`)

1. **Default `--bron adres`** tot de replay-meting "Project-dekking" ≥ 90 % toont; dan default omzetten (vervolg-opdracht).
2. **Per-pand-sluitcontrole op projectbasis** niet gebouwd: `JournalEntryLines` draagt geen Project (STAP-0) → alleen over de
   documentregels mogelijk, ná de meting.
3. **Pand-relevante groepen** in de meetlat = 7000 / 8xxx / 1405 / 46xx-70xx; 10xx bank/kas en overig (btw, resultaat) tellen niet.
4. **Meerdere projecten op één document** → koppeling aan élk project mét zichtbare reden; nooit raden.
5. **Bankmutaties** hebben geen project → altijd via de adres-terugval (notaris-ontvangsten blijven zo aan het pand hangen).

## Opdracht 6 — VGG blok 10 één regel, één bestemming (`2026-09-17-vgg-blok-10-een-regel-een-bestemming.md`)

1. **Overlap = ROOD-bepalend maar de herbestemming gaat door** (beide bestemmingen zichtbaar in het rapport) i.p.v. de replay te stoppen.
2. **Liquide middelen = RGS 10xx + de `bank_statement_lines`-codes uit de rekeningmapping**; een administratie met een bank op een ander
   nummer zou een `UseForPaymentAccount`-toets nodig hebben (niet in `ctx.ledgers`; beslispunt als dat voorkomt).
3. **Alleen bankregels in een memoriaal (bv. spaar ↔ betaal 1002/1001) = geen RJ-220-rol**, mét reden in de move.
4. **24 regels zonder bankmutatie**: geen bouw — herleid als kruisposten (1011) en interne overboekingen (1002); controle Peter in RLZ.
5. **Vijfde meting** pas ná deploy (vervolg-opdracht) — niets doorgerekend op basis van de vierde meting.

## Opdracht 7 — Klant-accordering laag per leverancier (`2026-09-17-accordering-laag-per-leverancier.md`)

1. **Voorrang afdelingsroute > leveranciersroute > administratieroute** (opdracht: default zo).
2. **Alleen documenten mét crediteur** (inkoopfacturen, verplichtingen) volgen een leveranciersroute; omzet-/verkoopdocumenten niet.
3. **Casus synthetisch** in `tests/accordering` (gouden set = échte documenten; geen écht document met deze configuratie).
4. **Deactiveren zonder administratieroute** laat lopende rondes vervallen mét reden (nooit stil); met administratieroute worden ze herberekend.
5. **UI = blok in de bestaande Klant-accordering-kaart** (opdracht: "één extra veld in de laag-dialoog" — door de verduidelijking
   "route vervangt" is het een route-niveau instelling met leveranciers + lagen geworden, geen veld per laag).
