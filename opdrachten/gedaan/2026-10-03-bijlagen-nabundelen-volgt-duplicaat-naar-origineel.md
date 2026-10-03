> uitgevoerd 03-10-2026 (CC-inbox-run), rapport: docs/rapporten/2026-10-03-bijlagen-volgt-duplicaat.md — suite 7974 groen, keten-sweep 13/13; terminal-opdracht opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md (Peter, ná deploy); nameting: opdrachten/inbox/2026-10-03-nameting-bijlagen-volgt-duplicaat.md

# BUG 03-10 — bijlagen-nabundelen laat de bijlage los staan als de factuur in dezelfde mail een afgevoerd duplicaat of afgewezen is (Peter 03-10: "werkdetails zonder factuur kan niet")

Domeinen: intake-extractie (LEESPLICHT `docs/regels/intake-extractie.md`), werkvoorraad-controlescherm (LEESPLICHT), werkloop-productie (LEESPLICHT).
Geen bijvangst (regel Peter 30-09). Niets schrijvends in productie vanuit CC; de nazorg-run doet Peter (terminal-opdracht aanmaken).

## Feiten (productie, leesreplica 03-10 ~10:55, scope Universal Steigerbouw `3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`)
De échte run `bijlagen-nabundelen --uitvoeren --administratie "Universal Steigerbouw"` (executie `rlz-reconciliatie-z8dj8`): 94 e-mails,
24 gekoppeld, 0 mislukt, 7 × "overgeslagen — geen factuur-document in deze mail". In álle 7 mails zit de factuur wél (`b.detail->'bijlagen'`):

| Mail (onderwerp) | Bijlage (te_controleren, los) | Factuur in dezelfde mail | Status factuur |
|---|---|---|---|
| Factuur RLZ-2080143044 (24-09) | factuurdetails-3445-2026-7.pdf | …3044 1-8-2026.pdf (gebundeld) + .xml | **afgewezen** (beide) |
| Factuur RLZ-2080143088 (28-09) | factuurdetails-3501-2026-8.pdf | …3088 19-8-2026.pdf | afgevoerd_duplicaat |
| Factuur RLZ-2080143092 (28-09) | factuurdetails-3428-2026-7.pdf | …3092 21-8-2026.pdf | afgevoerd_duplicaat |
| Factuur RLZ-2080143093 (28-09) | factuurdetails-3673-2026-7.pdf | …3093 21-8-2026.pdf | afgevoerd_duplicaat |
| Factuur RLZ-2080143094 (28-09) | factuurdetails-3160-2026-7.pdf | …3094 21-8-2026.pdf | afgevoerd_duplicaat |
| Factuur RLZ-2080143125 (28-09) | factuurdetails-3531-2026-7.pdf | …3125 28-8-2026.pdf | afgevoerd_duplicaat |
| Factuur RLZ-2080143131 (28-09) | factuurdetails-3335-2026-7.pdf | …3131 31-8-2026.pdf | (uitvoer afgekapt; zelfde patroon verwacht) |

Oorzaak in code: `app/intake/bijlagen_nabundelen.py` filtert `facturen` op `status not in _FACTUUR_UITGESLOTEN` (verwijderd/samengevoegd/
afgevoerd_duplicaat) en op afgewezen; blijft er niets over → "geen factuur-document in deze mail" en de bijlage blijft los. De mail zei
wél bij welke factuur de bijlage hoort — die kennis gooien we weg.

## Wat er moet gebeuren
1. **Volg het duplicaat naar het origineel.** Is de enige factuur in de mail `afgevoerd_duplicaat`, neem dan het origineel
   (`afwijzing.duplicaat_van_document_id` van die afvoer, anders `mogelijk_duplicaat_van_id`, anders hetzelfde factuurnummer —
   `bh`-sleutels — binnen dezelfde administratie met een niet-uitgesloten status) als doel; geboekt origineel = ook doel (bijlage mag
   bij een geboekt document hangen, bestaand gedrag "(geboekt)"). Chip/regel in de uitvoer: "via duplicaat → ‹origineel›".
2. **Afgewezen factuur in de mail:** zoek op dezelfde manier een niet-afgewezen document met hetzelfde factuurnummer in de
   administratie; gevonden → doel; niet gevonden → de bijlage blijft los mét uitkomst "factuur afgewezen (‹reden›) — bijlage ook afwijzen?"
   en in het controlescherm van de bijlage een chip met de link naar de afgewezen factuur. Nooit stil, nooit automatisch afwijzen.
3. Zelfde regel in het live-intakepad (`verwerking.py`, "één mail = één document" 02-10): een mail waarvan de factuur als duplicaat wordt
   afgevoerd, hangt zijn bijlagen aan het origineel i.p.v. ze los te laten vallen.
4. Dry-run-uitvoer: de 7 tonen daarna als `kandidaat — via duplicaat → Factuur RLZ-20801430xx …`; TOTAAL-regel krijgt een teller
   `via_duplicaat`.
5. Tests: unit op de drie bronnen (afwijzing-link, vlag, factuurnummer), afgewezen-pad zonder origineel, gouden set intake ongewijzigd groen.

## Af
Suites groen; BESLISSINGEN-rij onder "BOEKEN PRETTIG 1 — …" (nieuwe subkop "Bijlage volgt het duplicaat naar het origineel (03-10)");
regels-alinea in `docs/regels/intake-extractie.md`; rapport `docs/rapporten/2026-10-03-bijlagen-volgt-duplicaat.md` + INDEX; terminal-
opdracht `opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md` (dry-run Steigerbouw → verwacht 7 kandidaten via duplicaat →
échte run → kantoorbreed) ná deploy; "werkt in productie: niet gemeten" + nameting-opdracht `niet vóór:` deploy + 1 u.
