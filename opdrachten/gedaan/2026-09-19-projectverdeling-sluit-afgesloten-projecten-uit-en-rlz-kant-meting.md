uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md

Domeinen: verplichtingen-projecten-voorraad, reconciliatie, werkloop-productie

# OPDRACHT 19-09 — Pro-rato projectverdeling sluit AFGESLOTEN projecten uit + RLZ-kant-meting facturen zonder project (nazorg 18-09)

**Aanleiding (rapport `2026-09-18-facturen-zonder-project.md`, beslispunt 3):** Universal Steigerbouw heeft geen OVH-project; overhead
loopt via de omzet-gewogen verdeelsleutel over álle projecten mét omzet — óók over twee projecten met de naam "Afgesloten …". Sinds 18-09
(migratie 0160) kent de module een projectstatus; de verdeelsleutel gebruikt die nog niet. Kosten op afgesloten projecten vervuilen
het projectresultaat en zijn later niet meer te corrigeren zonder storno.

## A. Verdeelsleutel: alleen actieve projecten
1. `projectverdeling`: de omzet-gewogen sleutel (medewerker-wens 04-09) neemt uitsluitend projecten met `is_actief = true` op het moment
   van boeken; een project met naam die begint met "Afgesloten"/"afgesloten" maar `is_actief = true` = LET-OP-bevinding "naam zegt
   afgesloten, status actief — afsluiten?" (actie: Projecten › afsluiten), nooit stil uitsluiten op naam.
2. Bij het afsluiten van een project (0160-flow): nog niet geboekte verdelingen die dat project bevatten worden herberekend (tijdlijn
   "verdeling herberekend: ‹project› afgesloten"), geboekte verdelingen blijven staan (boekstand). Terugdraaien van afsluiten = idem.
3. Lees-only nazorg-CLI `projectverdeling-afgesloten-rapport --administratie …`: geboekte verdelingsregels op projecten die nú afgesloten
   zijn of "Afgesloten" heten (document, boekstuk, project, bedrag, datum) — voorstel per rij (storno+herverdeling / laten staan), niets
   uitvoeren. Universal als eerste; lijst in het rapport, beslispunt Peter.
4. **OVH-project Universal (beslispunt Peter, niet zelf aanmaken):** de regel "overhead → intern OVH-project" bestaat, Universal heeft er
   geen. Rapporteer wat er nu over de sleutel loopt dat overhead is (grootboek 4xxx algemeen, geen projectreferentie op de factuur) en
   wat een OVH-project zou vangen; Peter kiest: OVH-project aanmaken (via de Projecten-module, synct naar RLZ) of sleutel houden.

## B. RLZ-kant-meting facturen zonder project (ná deploy van cfa6d42)
`scripts/gcp/nameting.sh facturen-zonder-project --administratie "Universal Steigerbouw" --jaar 2026 --rlz` (lees-only, GET) → lijst +
tellingen in een aanvulling op het 18-09-rapport; per rij de herstelroute; beslispunt Peter bulk-herstel ja/nee. Zelfde meting voor de
andere vier project-verplichte administraties (`--alle-projectverplicht --rlz`).

## Afronding
Tests (sleutel zonder afgesloten; herberekening bij afsluiten; naam-LET-OP), regels-tekst `verplichtingen-projecten-voorraad.md`,
BESLISSINGEN-rij, WAT_IS_NIEUW ("Kosten worden niet meer over afgesloten projecten verdeeld"); rapport + INDEX + Gelezen regels;
nameting ná deploy: Universal-verdeling van een nieuwe factuur bevat geen "Afgesloten"-project — "werkt in productie: ja/nee".
Één regel voor Peter mét de drie beslispunten (herverdeling geboekte rijen, OVH-project, bulk-herstel RLZ-kant).
