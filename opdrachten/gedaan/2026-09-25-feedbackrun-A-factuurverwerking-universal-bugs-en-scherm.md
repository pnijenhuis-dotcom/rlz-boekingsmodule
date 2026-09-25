> uitgevoerd 2026-09-25, rapport: docs/rapporten/2026-09-25-feedbackrun-a-factuurverwerking.md (negen blokken, negen commits + docs; werkt in productie: niet gemeten — vervolg 2026-09-26-nameting-feedbackrun-A-na-deploy.md)

# Feedbackrun A — factuurverwerking (gebruikersfeedback Universal 25-09): bugs en scherm

Bron: `docs/feedback/2026-09-25-verbeteringen-factuurverwerking-universal.md` (letterlijke gebruikerstekst, items FV-xx). Besluit Peter
25-09: "deze punten mogen mits ze binnen onze lijn en beslissingen vallen en echt verbeteringen zijn" — de items hieronder zijn door
Cowork getoetst; de vorm hier is bindend, niet de tekst in het feedbackbestand. Niet in deze run: FV-03/Bijlage A, FV-04 (run B, wacht
op testset + voorbeeldfacturen) en FV-17 (vervalt: besluit 21-09 "Corrigeren → klaar_om_te_boeken mét gele balk" blijft).
Handmatige CC-sessie, Peter start hem zelf. Één commit per blok, één rapport, per blok "werkt in productie: ja/nee/niet gemeten".

LEESPLICHT (volledig): CLAUDE.md, docs/regels/werkvoorraad-controlescherm.md, intake-extractie.md, duplicaten-crediteuren.md, btw.md,
verplichtingen-projecten-voorraad.md, kantoor-frontend.md, accordering-native-app.md, werkloop-productie.md; docs/gesprekken/2026-09-25.md;
de mockups controlescherm-v2.html en projecten-invoer.html (bouwnorm). Regel 22-08: geen eigen interpretatie buiten de blokken.

## Blok 1 — FV-01 · RLZ-UBL wordt als ruwe code getoond (P1, bug)
Factuur `RLZ-2080142898` (RLZ-export van een andere administratie, vermoedelijk Universal Nederland → Universal Steigerbouw) komt als
tekstblok in het scherm. Vaststellen aan het echte bestand (document zoeken op referentie; lees-only) waarom `app/documenten/ubl.py`
het niet als UBL herkent (namespace/root-element/`CustomizationID` van de RLZ-export, BOM, encoding, gzip?). Fix: de RLZ-UBL-variant
deterministisch lezen (kop, crediteur, regels, btw, datums — géén AI); elke XML die niet als UBL herkend wordt krijgt status
`handmatig_afmaken` mét chip "XML niet leesbaar: ‹reden›" en de PDF/beeld als bijlage — nooit ruwe XML in een tekstveld. Tests: RLZ-UBL-
fixture (geanonimiseerd), kapotte XML, UBL zonder regels. Nazorg: alle documenten met een `.xml`-bron én `ai_extractie_fout`/ruwe tekst
tellen (lees-only CLI) en opnieuw aanbieden via het bestaande heraanbied-pad.

## Blok 2 — FV-21 · Crediteurnamen in meerdere schrijfwijzen (P1, oorzaak achter "geheugen doet niets bij Floor")
`Floor Bouwliftenservice` / `Floor bouwliftenservice`, `Universal Nederland B.V.` / `Universal nederland B.V.` = twee RLZ-Vendor-records
zonder gemeenschappelijke KvK/btw → buiten de dedup-clusters, historie versnipperd. Bouw: naam-genormaliseerde kandidaat-clusters
(casefold, rechtsvorm en leestekens weg, `app/crediteuren/` naast de bestaande btw/KvK-clusters) als ORANJE cluster in het bestaande
dubbelen-scherm — mens bevestigt, NOOIT automatisch samenvoegen op naam (verschillende entiteiten met gelijkende naam bestaan). Ná
bevestiging: bestaande voorkeur-mechaniek (`crediteuren/voorkeur.py`), geheugen leest over het cluster. Nieuwe factuur met afwijkende
schrijfwijze → koppelt aan het bevestigde cluster, geen nieuwe crediteur. Lees-only CLI `crediteuren-naamclusters` kantoorbreed (telling
per administratie). Tests: casus Floor, gelijkende-maar-andere naam = géén cluster, KvK-conflict = nooit.

## Blok 3 — FV-02 · Project: bronvolgorde i.p.v. "laatste project van de leverancier" (P1, aangepaste vorm)
Geheugen blijft (auto-first, autoboeken), maar voor het PROJECT geldt de volgorde: (1) projectreferentie/werknummer op de factuur of
bijlage (bestaande werknummer-mapping leverancier ↔ project, praktijkles CLAUDE.md), (2) klant-loze projectcode-herkenning op het
formaat van de administratie (Universal: 100–189 of JJnnn — uit de projectcache, nooit vrije tekst), (3) geheugen — zichtbaar als chip
"voorstel uit historie", nooit stil. Bij project_verplicht en geen bron: verplichte keuze (bestaande harde check), geen prefill uit
geheugen als de factuur een ánder projectnummer noemt (conflict = chip + keuze). Afgesloten projecten nooit voorstellen tenzij de
factuur ernaar verwijst (bestaande `is_actief`-regel). Tests: factuur mét werknummer wint van geheugen; conflict; geen bron.

## Blok 4 — FV-16 · Factuurdatum in een ingediende btw-periode (aangepaste vorm: ORANJE, geen blokkade)
Nieuwe check "Factuurdatum valt in een ingediende aangifteperiode (‹periode›)" via de bestaande aangiftelezer (`app/rlz/aangifte.py`,
`GET TaxDeclarations`, status 2/3): ORANJE mét uitleg "RLZ verschuift de btw naar het eerstvolgende open tijdvak" en bewuste keuze
"Boeken (btw in volgend tijdvak)"; audit + tijdlijn. Géén blokkade (nagekomen facturen zijn legitiem). Doorbelasting/intercompany:
als één van beide kanten in een ingediende periode valt → LET-OP in de doorbelastingspreview (beide kanten zelfde tijdvak).
Autoboek-pad: ORANJE = niet automatisch boeken (bestaande regel). Tests: open periode = geen check; ingediend = oranje; IC-paar.

## Blok 5 — FV-14 + FV-15 · Crediteur aanmaken en bewerken
FV-14: "Nieuwe crediteur" wordt een zijpaneel naast de factuur (factuur blijft leesbaar en scrollbaar), KvK, btw-nummer, IBAN, naam en
adres voorgevuld uit de extractie (we extraheren IBAN/btw-nummer al voor de IBAN-check), chips "uit factuur"; opslaan = bestaande
Vendor-PUT. FV-15: crediteur achteraf bewerkbaar vanuit het controlescherm (naam/adres/KvK/btw); IBAN toevoegen/wijzigen ALTIJD via
de bestaande IBAN-wissel/vier-ogen-route, nooit als vrij veld; ontbrekende IBAN = waarschuwing bij opslaan, niet blokkerend
(incasso/buitenland). Tests: prefill, paneel-variant, IBAN via de wisselroute.

## Blok 6 — FV-09 · Btw-bedrag herrekenen bij wijziging van het netto (bug)
Sinds 18-09 volgt het btw-bedrag het tarief; controleer of het óók herrekent bij wijziging van het nettobedrag en bij samenvoegen; zo
niet: fixen in `regel_prefill`/`BoekvoorstelPanel` (deterministisch, marge-regel 18-09 ongewijzigd). Mens-ingevoerd btw-bedrag blijft
winnen zolang het netto niet wijzigt (tijdlijn-override). Tests: netto wijzigen → btw mee; tarief wijzigen → btw mee; mens-btw + netto
wijzigen → herrekend mét chip.

## Blok 7 — FV-18 · Scherm loopt vast bij wisselen tabblad (P1, bug — eerst reproduceren)
Reproduceer met het visuele harnas + productie-achtige lijstgrootte (Universal Steigerbouw: honderden documenten): 20 × wisselen
te_controleren ↔ klaar_om_te_boeken. Verdachten: polling/SSE-herlaad in `DocumentenDeelscherm` bij tabwissel, checks-cache-fetch per
rij, geen abort van lopende fetches, state-explosie bij grote lijsten. Oorzaak vastleggen (console/log/profile) vóór de fix; fix +
regressietest (20 wissels, geen hangende promises, AbortController). Niet reproduceerbaar = rapporteren mét wat wél gemeten is, geen
blinde fix.

## Blok 8 — FV-20 · "Alle" toont niet alles
"Alle" sluit "Wachten op anderen" bewust uit (regel werkvoorraad 1). Fix: filterlabel hernoemen naar "Open (N)" en een echte "Alles
(N)" toevoegen die óók wachten_op_anderen, geboekt en afgehandeld toont (server-side, paginering); zoeken vanuit de klantpagina zoekt
altijd over alles mét statuschip. Bestaande toggle geboekt/afgehandeld blijft. Tests: Exact-factuur `wachten_op_anderen` vindbaar.

## Blok 9 — comfort binnen de UX-norm (P2/P3, klein houden)
- FV-05: verwijzingen naar bijlagen ("conform bijgevoegd overzicht", "zie bijlage") uit de kop-omschrijving strippen (deterministische
  lijst, chip "ingekort"), nooit inhoud verzinnen.
- FV-07: project en btw-code op factuurniveau zetten → doorgezet naar álle regels, per regel overschrijfbaar (tijdlijn "kop → regels").
- FV-08: bedragvelden accepteren een rekenexpressie (`20+30`, `+ - * /`, komma-decimalen), deterministisch geëvalueerd bij blur,
  resultaat zichtbaar; geen eval — eigen parser + tests.
- FV-10/FV-11: controlescherm zonder horizontale overflow (overflow-sweep), boekingskolom standaard breder dan het factuurbeeld,
  sleepgrens soepel (pointer events) en breedte per gebruiker onthouden (bestaande voorkeuren-opslag).
- FV-12: knop "Verdelen" gebruikt standaard de verdeelsleutel van de administratie (Universal = omzetsleutel, besluit 21-09) mét
  "Anders…" voor de overige methodes; verdeling achteraf aanpasbaar (bestaand); knop bij het regelblok.
- FV-13: "Periode toont slechts één week" — eerst vaststellen welk scherm (vraag in het rapport mét screenshot uit het harnas); als
  het de periodekop van het controlescherm is: "van … tot …" uit de extractie.

## Niet doen
- FV-17 niet bouwen. Geen harde blokkade op periodes. Geen automatische crediteur-samenvoeging op naam. Geen hardcoded
  Universal-rubrieken (dat is run B als templates per administratie). Geen wijziging aan geldlogica buiten blok 6.

## Definitie van af
Gouden set groen; deploy; nameting per blok (recept in het rapport, dispatch-onderdelen waar zinvol); rapport
`docs/rapporten/2026-09-25-feedbackrun-a-factuurverwerking.md` + INDEX + "Gelezen regels" + per blok "werkt in productie";
BESLISSINGEN-rij per blok, regels-bestanden bijgewerkt, WAT_IS_NIEUW klantleesbaar (de indiener leest mee), gespreksverslag 25-09
aanvullen; het feedbackbestand in `docs/feedback/` krijgt per FV-item een statusregel (gedaan / aangepaste vorm / run B / vervalt mét
reden) — het bestand zelf blijft letterlijk. Opdracht naar gedaan/.
