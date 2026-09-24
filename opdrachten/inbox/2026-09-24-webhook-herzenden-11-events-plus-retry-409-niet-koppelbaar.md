Domeinen: werkvoorraad-controlescherm, reconciliatie, werkloop-productie

# OPDRACHT (RLZ-boekingsmodule, 24-09-2026): 11 factuur_geboekt-events opnieuw afleveren aan Vastly + retry op niet-2xx

> Peter 24-09 (tijdens de bundelrun): "na de huidige run deze oppakken". Bouwt voort op commit bd2c5a0/58c0b78 (herzend-actie
> `webhook-herzenden`, "200 genegeerd = mislukt") en op `opdrachten/inbox/2026-09-24-webhook-herzenden-11-events-uitvoeren-na-deploy.md`
> (uitvoering ná deploy). Nieuw hier: retry-cadans op niet-2xx (409 `niet_koppelbaar`) + registers.

Lees eerst: CLAUDE.md van dit project, Platform/OPEN_ITEMS.md regel 13 (verzoek vastgoed 21-09 met de elf referenties)
en het nieuwe item van 24-09 (409 niet_koppelbaar + retry-cadans), Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md §3,
app/documenten/webhook_afleveraar.py, outbox-migraties 0009/0025/0046.

Wat: de elf factuur_geboekt-events die vóór 20-09 door Vastly met 200 "genegeerd" zijn beantwoord opnieuw afleveren.
Referenties: Rubicon Investments B.V. 24713213, 24713354, 265050202128, 26753012, 26734257, 2026-017; ARVUM B.V. 183727,
26747235, 26752091, 522500062785, 537500100925.
Hoe: zoek de outbox-rijen (referentie/document binnen deze twee administraties, event factuur_geboekt); zet ze terug op
"te verzenden" via een herbruikbare herzendactie (beheerscript of kantooractie per outbox-rij, met audit; geen losse SQL),
zodat de normale afleveraar ze verstuurt met verse timestamp en nonce en hetzelfde rlz_document_id/volgnummer; payload
ongewijzigd. Ontvanger is idempotent op (rlz_document_id, regelindex).
Vastly antwoordt sinds 24-09 met 409 niet_koppelbaar als iets niet koppelt: implementeer in dezelfde run de retry op
niet-2xx in de afleveraar (cadans 1m/10m/1h/6h/daags tot 7 dagen, daarna melding in de RLZ-werkvoorraad), conform het
OPEN_ITEMS-voorstel; koppelcontract §3 als versiebump voorstellen, niet eigenmachtig wijzigen.
Controle: per event de respons loggen; goed = 200 met "kostenvoorstel" of "al_verwerkt"; 409 = wacht op retry; alleen deze
elf herzenden. Dry-run eerst (toon de elf rijen), dan uitvoeren. Rapporteer per referentie de uitkomst.
Registers: OPEN_ITEMS regel 13 afvinken met datum en uitkomst, 24-09-item beantwoorden; eigen BESLISSINGEN/parkeerposten;
les in Platform/registers/verbeteringen.md als de payload aan RLZ-kant moest veranderen.
Afsluiting volgens de pre-commit-keten van dit project. Tijdsindicatie: 30-45 min (incl. retry-logica).
