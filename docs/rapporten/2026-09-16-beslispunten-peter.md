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
