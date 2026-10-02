# Terminal 24-09 — webhook-herzenden 11 kostenevents Vastly (Rubicon 6, ARVUM 5) — OPEN_ITEMS regel 13

Afspraak 23-09: Cowork schrijft terminal-commando's in dit bestand; Peter laat Claude Code ze uitvoeren mét toestemming per commando
(of plakt ze zelf). Bron: `opdrachten/inbox/2026-09-24-webhook-herzenden-11-events-uitvoeren-na-deploy.md` (CC 23-09) en rapport
`docs/rapporten/2026-09-23-webhook-herzenden-11-kostenevents-vastly.md`. Voorwaarde: deploy van commit `58c0b78` is live (job-image bevat
`webhook-herzenden`) — controle in stap 0.

## Stap 0 — is de deploy live? (lees-only)
```
gcloud run jobs describe rlz-webhook-afleveraar --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Verwacht: image eindigt op `58c0b78…` (of nieuwer). Anders: wachten, niets doen.

## Stap 1 — dry-run (lees-only, schrijft niets)
```
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,24713213,--referentie,24713354,--referentie,265050202128,--referentie,26753012,--referentie,26734257,--referentie,2026-017"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,183727,--referentie,26747235,--referentie,26752091,--referentie,522500062785,--referentie,537500100925"
```
Verwacht in het log: 6 resp. 5 regels "zou herzenden (dry-run)", 0 "niet gevonden". Anders stoppen en de uitvoer aan Cowork geven.

## Stap 2 — uitvoeren (schrijvend; alleen deze elf)
```
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,24713213,--referentie,24713354,--referentie,265050202128,--referentie,26753012,--referentie,26734257,--referentie,2026-017,--uitvoeren,--reden,Vastly negeerde deze events vóór de matchsleutel-fix van 20-09 (OPEN_ITEMS regel 13)"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,183727,--referentie,26747235,--referentie,26752091,--referentie,522500062785,--referentie,537500100925,--uitvoeren,--reden,Vastly negeerde deze events vóór de matchsleutel-fix van 20-09 (OPEN_ITEMS regel 13)"
```
Verwacht: "TOTAAL: herzonden 6" resp. "5". De scheduler `rlz-webhook-afleveraar` (*/5) verstuurt daarna zelf.

## Stap 3 — controle ≥ 10 min later (lees-only)
```
gh workflow run nameting -f onderdeel=query -f query="webhook-outbox --administratie Rubicon"
gh workflow run nameting -f onderdeel=query -f query="webhook-outbox --administratie ARVUM"
```
Uitkomst komt als bot-bestand `verkenning/lezen-24-09-webhook-outbox.txt`; Cowork leest en meldt per referentie GOED/FOUT.
