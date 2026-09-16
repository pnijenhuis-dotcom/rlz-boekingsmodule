> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-omzet-profx.md

# OPDRACHT 16-09 — Coffeeshop-omzet (ProfX Journaal) automatisch splitsen per artikelgroep + bruto/netto-schakelaar op bedragvelden (feedback Peter 16-09, screenshot De Bazar Apeldoorn)

**Feedback Peter (16-09, screenshot controlescherm):** "in dit scherm wordt de omzet niet auto gesplitst, dat moet natuurlijk
wel. Punt van aandacht is dat hij de artikelgroepen splitst, niet de artikellijst — scheelt weer veel invulwerk" en "in het
veld moet het netto bedrag (excl. btw) ingevuld worden terwijl dat hier juist bruto is. Gelieve netto/bruto selecteerbaar
(klikken = switch) zodat de gebruiker makkelijk kan kiezen om bruto of netto in te vullen."

**Wat Cowork in de screenshot ziet (wortel, hoort bij dezelfde run):** het document is een **ProfX Journaal** (kassarapport
coffeeshop: Kassa 1/Kassa 2, rapportperiode 11-09 05:00 t/m 12-09 05:00, 604 klanten, artikelgroepen Dranken/Edible/Hash/
Headshop/Joints/Snacks/Wiet, bruto omzet € 10.998,16, kortingen/vouchers 0, netto omzet € 10.998,16; 4 pagina's) uit mail
`debazarapeldoorn@gmail.com` met onderwerp "Facturen - Inboeking journaal en marge raport". Het staat in het INKOOP-
controlescherm (crediteur/referentie/factuurdatum verplicht, één regel, "AI 70 %") — de intake heeft het als inkoopfactuur
geclassificeerd i.p.v. als kassarapport. Daar ligt het echte gat: de omzetmodule (BESLISSINGEN "Omzetmodule — GEBOUWD +
GETEST", BLOW Margerapport, entity-loze Receipts, cannabis = "NL, Geen BTW (Vrijgesteld)") bestaat, maar dit rapport komt er
niet in. Het splitsen zelf is dáár al het model (omzet per categorie → omzet-GB + btw-code per categorie).

Pre-feature-ritueel: BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST", "OMZET-AUTOBOEKEN", "OMZETBRON ZONNESTUDIO DAGSTAAT (Peter
15-09)", "OMZETBRONNEN — BESLUITEN PETER 16-09" (tegenzijde per betaalwijze, bron-instellingen, Beheerder-blok), "E-mail-
intake + verzamelbak", "DUPLICATEN HOOFDMODEL" (kassarapport-dedupe per periode), api-verkenning "Omzetmodule STAP 0" +
"Receipts-verkenning"; `app/omzet/bronnen/` (Grid-laag 15-09), `app/intake/` classificatie, `frontend/src/omzet/`.

## Blok A — Intake: ProfX Journaal = kassarapport (deterministisch, geen AI-gok)
1. Herkenning op inhoud vóór de AI-classificatie: PDF-tekst mét "ProfX Journaal" + "Rapportperiode" + "Artikelgroepen" →
   documenttype kassarapport, `bron='profx_journaal'`. Idem de bestaande BLOW-herkenning als die er nog niet is — één
   registry `omzet/bronnen/herkenning.py` (fail-closed sweep: elke bron heeft een herkenningsregel + test). Afzender/onderwerp
   zijn alleen hint (regel 15-08: routering nooit op afzender).
2. Al verkeerd geclassificeerde exemplaren (dit document en eerdere van dezelfde afzender): lees-only rapport per
   administratie "kassarapporten in de inkoopstroom" + herclassificatie via de bestaande verplaats-/type-wissel-route (geen
   nieuwe status; audit + tijdlijn). Geen automatische herclassificatie van al GEBOEKTE documenten — melden.
3. Meerdere rapporten in één mail ("journaal en marge raport"): het margerapport is een tweede bron of een bijlage van
   dezelfde dag → bundelen per administratie × periode zoals dagstaat + kascheck (15-09), nooit twee omzetboekingen.

## Blok B — Parser ProfX Journaal (deterministisch, pure functie op de Grid/tekst, geen AI)
- Kop: kassa's, rapportperiode (van/tot — een periode 05:00→05:00 = één kassadag; boekdatum = startdag), aantal klanten,
  datum uitdraai. Tabel "Artikelgroepen": omschrijving, aantal, bedrag, retour-aantal, retour-bedrag, korting; regel
  "Bruto omzet", "Kortingen", "Vouchers", "Netto omzet". Bedragen zijn INCL. btw (kassa) — netto per groep deterministisch
  afgeleid uit het tarief van de categorie, cent-exact sluitend op het rapporttotaal (restcent op de grootste regel,
  bestaande `regelsom`-conventie). Retouren en kortingen per groep als negatieve component van dezelfde regel.
- Sluitcontroles als check-rijen: Σ groepen (bedrag − retour − korting) = Bruto omzet; Bruto − Kortingen − Vouchers = Netto
  omzet; pagina's 2–4 (artikellijst, betaalwijzen, kassa-afsluiting) alleen lezen voor de tegenzijde (blok D) — de
  ARTIKELLIJST wordt NIET geboekt (Peter: groepen, niet artikelen).
- Dedupe: administratie × rapportperiode × kassa-set (bestaande periode-duplicaatbewaking), tweede upload = "al geboekt"
  rood zoals bij pilates.

## Blok C — Categorie-mapping per artikelgroep (leerbaar, defaults, mens wint)
- Artikelgroep → categorie → omzetrekening + btw-code uit het RLZ-schema van de administratie (nooit hardgecodeerd). Defaults
  per naam (herkomst-chip "default"): Wiet/Hash/Joints → cannabisomzet "NL, Geen BTW (Vrijgesteld)" (BLOW-besluit, bewust géén
  0 %); Edible → **beslispunt**: cannabis-edibles (spacecake) zijn vrijgesteld, gewone edibles 9 % — default vrijgesteld
  mét oranje chip "controleer: edibles"; Dranken/Snacks → laag tarief; Headshop → hoog tarief. Eerste boeking per
  administratie: mens bevestigt (oranje), daarna groen uit het geheugen (bestaand patroon); onbekende nieuwe groep = oranje
  "nieuwe artikelgroep, kies categorie", nooit blokkerend voor de rest.
- Mapping beheerbaar in het Beheerder-blok "Omzetbronnen" van 16-09 (zelfde tabel als de pilates-categorieën, bron-kolom).

## Blok D — Tegenzijde en boeking
- Zelfde model als zonnestudio/pilates 16-09: omzet per categorie tegen tussenrekening per betaalwijze (kas / PIN) uit de
  betaalwijzen-pagina van het journaal als die er is; ontbreekt die → alles op kas mét oranje signaal. Receipt entity-loos
  (besluit 08-08), `BookDate` = kassadag. Omzet-autoboeken volgt de bestaande opt-in per administratie.
- Controlescherm OMZET (niet inkoop): regels per artikelgroep voorgevuld (netto, btw, bruto, categorie, herkomst-chip), check-
  rijen zichtbaar, blok "Bron" (15-09) mét kassa's/klanten/periode.

## Blok E — Bruto/netto-schakelaar op bedragvelden (Peter, generiek)
- In het omzet-controlescherm én in de boekingsregels van het inkoop-controlescherm: het kolomlabel NETTO is klikbaar en
  wisselt per regel-tabel naar BRUTO (incl.) — de gebruiker typt in de gekozen modus, de andere waarde wordt deterministisch
  afgeleid uit de btw-code van de regel (cent-exact, `regelsom`), de andere waarde NIET onder het veld getoond (besluit Peter 16-09: kost breedte; wisselen via het kopje volstaat).
  Voorkeur onthouden per gebruiker (localStorage — geen server-state; PWA-regel n.v.t., dit is kantoor-web). Zonder btw-code
  = geen omrekening mogelijk → veld blijft netto mét tooltip. Kolomminima (184/168/200) ongewijzigd; overflow-sweep.
- Gouden set: casus c/w (Spot Services, LHG) tonen dat de netto-waarden en checks byte-gelijk blijven als de schakelaar
  niet gebruikt wordt (export deterministisch).

## Tests / af
- Nieuwe gouden-set-casus `ad_omzet_profx_journaal` (geanonimiseerd JSON-raster/pdf_tekst uit dit document, PII = afzender-
  mail weglaten) door intake → herkenning → parser → categorieën → checks → omzet-DTO; keten-guard raakt intake/documenten.
  Parser-unit-tests (groepen, retouren, kortingen, sluitcontroles rood/groen, periode 05:00→05:00). Frontend: schakelaar
  (omrekening, voorkeur, zonder btw-code), omzet-scherm regels per groep.
- Herclassificatie-rapport lees-only als CLI `kassarapporten-in-inkoopstroom` (nameting-allowlist). Migratie alleen als
  `bron`-enum/instellingen-JSON niet volstaan.
- BESLISSINGEN "OMZETBRON COFFEESHOP PROFX JOURNAAL + BRUTO/NETTO-SCHAKELAAR (Peter 16-09)", CLAUDE.md-verwijsregel,
  WAT_IS_NIEUW, rapport `docs/rapporten/2026-09-16-omzet-profx.md` + INDEX mét meetrecept (dit document van De Bazar ná
  deploy herclassificeren → omzet-controlescherm toont 7 groepen, netto+btw sluit op € 10.998,16). Beslispunten mét default:
  Edible-tarief; boekdatum = startdag van de periode; margerapport = bundelen of negeren (default: bundelen als bijlage,
  niet boeken). Werkt in productie: niet gemeten.

## Blok F — Eén scherm, twee boekingen: margerapport = kostprijs/inkoop (aanvulling Peter 16-09 11:50)
**Peter:** "nu moet de omzet aan de ene zijde geboekt worden bij de coffeeshops en dat exact zelfde document ook bij inkoop
als inkoop. Idealiter verwerken wij dat in 1 scherm waarbij de module 2 boekingen doorschiet."
- Dit is exact het bestaande omzetmodel (BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST": Receipt/verkoop + gekoppelde
  KOSTPRIJSMEMORIAAL per productgroep als één transactie, storno bij half). Voor coffeeshops is de inkoop van softdrugs
  contant en zonder factuur; de fiscaal aanvaarde bron voor de inkoopwaarde is het **margerapport** (inkoopwaarde per
  artikelgroep). Dus: het margerapport uit dezelfde mail parsen (deterministisch, zelfde Grid-laag), per artikelgroep
  inkoopwaarde → kostprijsregel (kostprijs-GB + tegenrekening: voorraad softdrugs óf direct kas-inkoop — instelling per
   administratie, default de bestaande mapping-kolom "kostprijs-GB"), gebundeld met het journaal van dezelfde periode
  (blok A3) tot ÉÉN kassarapport-document → één controlescherm mét twee blokken (Omzet · Kostprijs), één "Boeken" = twee
  RLZ-documenten in één transactie (bestaande motor). Journaal zonder margerapport = omzet boeken, kostprijs-blok oranje
  "margerapport ontbreekt" (geen blokkade; kostprijs later nakomen via dezelfde bundel). Marge-plausibiliteitscheck
  (bestaand, vs eigen historie) blijft de harde check.
- Géén losse "inkoopfactuur" meer voor dit document: de inkoopstroom-route in blok A2 herclassificeert ze.

## Blok G — Administratieprofiel "Winkel / kassa" (vraag Peter: "winkel-label")
- Geen los label (een label doet niets), maar een **profiel** dat een bundel instellingen zet én zichtbaar maakt:
  kassarapport-bronnen actief (ProfX/BLOW/zonnestudio/pilates), omzet-autoboeken-opt-in (default UIT, bestaand), kostprijs-
  memoriaal aan/uit + tegenrekening, tegenzijde per betaalwijze (16-09), kasboek-controle, categorie-mapping-tabel.
  Het profiel wordt AFGELEID (minimale mens): een administratie met ≥ 1 herkend kassarapport krijgt automatisch profiel
  "Winkel / kassa" mét chip in de administratielijst + filter; Beheerder kan het uit-/aanzetten en de defaults overrulen op
  Instellingen › Administraties › ‹administratie› › Boeken & AI (het bestaande "Omzetbronnen"-blok wordt het profiel-blok).
  Zelfde patroon als `is_vastgoed` en de uren-opt-in — geen nieuwe pagina, geen tegel. Migratie alleen als een kolom
  `profiel` nodig is (voorkeur: afgeleid + override-kolom).
- Werkvoorraad: bij een winkel-administratie staat de omzet-tab/soortkeuze voorop; het controlescherm opent op het
  omzet-scherm voor kassarapporten (gebeurt al via soort, nu ook de intake-verwachting).

## UX-norm voor blok D/F/G: `mockup/omzet-kassarapport-v2.html` — AKKOORD Peter 16-09 12:20 = BOUWNORM
- Eén tabel per artikelgroep mét omzet (netto/bruto-kopje klikbaar) · btw · inkoopwaarde · marge; strook "Ontvangen kas/PIN
  → tegenzijde"; twee kaartjes "Verkoop → Reeleezee" / "Kostprijs → memoriaal" mét uitklapbare regels; één knop "Boeken
  (2 documenten)"; stand "margerapport ontbreekt" (alleen omzet, kostprijs volgt automatisch). Ontwerpnotities 1–7 onderaan =
  onderdeel van het akkoord. Akkoord gegeven mét twee correcties (verwerkt in de mockup): géén grijze tegenwaarde onder de bedragcellen (kost breedte;
  de schakelaar op het kopje volstaat) en de totaalregel exact uitgelijnd op de kolomcellen (€ links, getal rechts, vaste
  breedte). Dat geldt óók voor blok E op het inkoop-controlescherm: geen tegenwaarde-regel. Alle blokken A–G bouwen; mockup
  naar designpass-v2-klassen brengen (inhoud ongewijzigd) en committen als bouwnorm.

## Aanvulling Peter 16-09 12:05 — periodes lopen niet gelijk
"We krijgen soms de omzet per dag en inkoop per week. We zullen vragen of we dat elke dag mogen ontvangen, maar periode moet
dus wel in de gaten gehouden worden." → Blok F: bundeling op PERIODE-DEKKING, niet op gelijke datum. Een margerapport met
periode week N koppelt aan álle dagjournalen binnen die week; de kostprijsboeking is dan één memoriaal per margerapport-periode
(boekdatum = laatste dag), de marge-plausibiliteit wordt op die periode getoetst (Σ dagomzet vs inkoopwaarde week). Elk
dagscherm toont "kostprijs: weekrapport N verwacht / gekoppeld / geboekt". Dekkingscontroles als check-rij (niet blokkerend):
dagen in de week zonder journaal, week zonder margerapport (ná +3 werkdagen oranje in de reconciliatie), margerapport dat
dagen dekt die al in een ander margerapport zaten (= dubbel, rood). Andersom (dagelijks margerapport) blijft 1-op-1.
Mockup-notitie 7 beschrijft dit.
