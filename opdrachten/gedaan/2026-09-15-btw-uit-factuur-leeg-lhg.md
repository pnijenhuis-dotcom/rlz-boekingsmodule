uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-btw-uit-factuur-leeg.md

BUG-ONDERZOEK — btw-code bleef leeg terwijl de factuur btw draagt (Peter 14/15-09, L.H.G. Holding, rekening "Kosten mobiele telefonie")

Peters punt: "de AI leest toch alles" — terecht: de factuur is al de EERSTE bron in de winnaarsvolgorde (btw_bron='factuur'). Dat het veld toch leeg bleef is dus een bug of een bewuste "bewust leeg"-drempel die hier te streng is.
1. Zoek het document (LHG Holding, geboekt 14-09 op de mobiele-telefonie-rekening; lees-only via de bestaande routes/DB-lees, geen productie-writes) en herleid per regel waarom `leid_btw_af` / de UBL-/AI-extractie geen tarief gaf: geen regels herkend? btw-bedrag paste op geen tarief (afronding)? 0 %-ambiguïteit? meerdere regels met één btw-totaal?
2. Fix de wortel in het extractie-/afleidingspad (deterministisch: netto × tarief ≈ btw met tolerantie per regel én factuur-totaal als tweede bewijs; bij één btw-percentage op de factuur geldt dat voor álle regels zonder eigen btw). Geen AI-keuze van een btw-code — de AI levert bedragen/percentages, code kiest.
3. Gouden-set-casus met de LHG-factuur (geanonimiseerd, pdf_tekst.json + ai_antwoord.json). Rapport docs/rapporten/2026-09-15-btw-uit-factuur-leeg.md + INDEX (oorzaak in twee zinnen bovenaan); dit bestand naar gedaan/.
