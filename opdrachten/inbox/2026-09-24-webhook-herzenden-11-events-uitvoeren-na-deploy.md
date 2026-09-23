Domeinen: werkvoorraad-controlescherm, doorbelasting-intercompany, werkloop-productie

niet vóór: 2026-09-24 00:30

# Webhook-herzenden 11 `factuur_geboekt`-events aan Vastly UITVOEREN ná deploy (OPEN_ITEMS regel 13) — poging 1

**Context:** bouwrapport `docs/rapporten/2026-09-23-webhook-herzenden-11-kostenevents-vastly.md` (CLI `webhook-herzenden`, "200 genegeerd = zichtbaar
mislukt", querybibliotheek `webhook-outbox`); Platform `OPEN_ITEMS.md` regel 13 (verzoek vastgoed 21-09, elf referenties); koppelcontract §3.
De dry-run op de leesreplica van 23-09 22:1x staat in het bouwrapport: alle elf rijen bestaan als `afgeleverd` (Rubicon 6, ARVUM 5, 1 poging).
Hoogstens drie pogingen (regel 22-09 (3)), daarna `mislukt/` mét klikpunt.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij > 0, nooit rebase); service `rlz-backend` ÉN job `rlz-webhook-afleveraar`
(`spec.template.spec.template.spec.containers[0].image`) op een image mét de bouw-commit van 23-09 avond als voorouder; scheduler
`rlz-webhook-afleveraar` ENABLED (*/5). Niet live → deze opdracht terug in `inbox/` mét `niet vóór:` +1 uur.

## Stap 1 — dry-run op de job-image (lees-only, schrijft niets)
```
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait \
  --args="-m,app.cli,webhook-herzenden,--administratie,Rubicon Investments,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,24713213,--referentie,24713354,--referentie,265050202128,--referentie,26753012,--referentie,26734257,--referentie,2026-017"
gcloud run jobs execute rlz-webhook-afleveraar --region europe-west4 --wait \
  --args="-m,app.cli,webhook-herzenden,--administratie,ARVUM B.V.,--beheerder-id,2f2262cd-0423-4910-b7b5-335ba37a6ef5,--referentie,183727,--referentie,26747235,--referentie,26752091,--referentie,522500062785,--referentie,537500100925"
```
(argumenten mét komma's/spaties: gcloud's `^|^`-scheidingsteken gebruiken als een waarde een komma bevat — hier niet nodig; "ARVUM B.V."
is één argument.) Verwacht: 6 + 5 regels "zou herzenden (dry-run)", 0 "niet gevonden", exit 0. Anders: stoppen en melden.

## Stap 2 — uitvoeren (schrijvend; alleen deze elf)
Dezelfde twee commando's mét `--uitvoeren,--reden,Vastly negeerde deze events vóór de matchsleutel-fix van 20-09 (OPEN_ITEMS regel 13)`.
Verwacht: "TOTAAL: herzonden 6" resp. "5", audit `webhook_herzonden` per rij. De job `rlz-webhook-afleveraar` (scheduler */5) verstuurt
daarna mét verse timestamp/nonce; niet zelf `webhook-afleveren` starten tenzij de scheduler niet loopt.

## Stap 3 — controle per referentie (lees-only, ≥ 10 min ná stap 2)
`gh workflow run nameting -f onderdeel=query -f query="webhook-outbox --administratie Rubicon"` en idem `--administratie ARVUM` →
`verkenning/lezen-24-09-webhook-outbox.txt`. Per referentie: `status` = afgeleverd, `laatste_audit_actie` = webhook_afgeleverd,
`laatste_resultaat` ∈ {verwerkt, voorstellen, al_verwerkt} = GOED; `webhook_genegeerd` mét `laatste_ontvanger_reden` = FOUT → melden mét de
reden, NIET opnieuw herzenden. Let op: de twee Rubicon-rijen RUB-2026-0025/0031 (23-09 20:21) vallen buiten scope en blijven ongemoeid.

## Stap 4 — registers + rapport
Platform `OPEN_ITEMS.md` regel 13 afvinken (`- [x]`, "herzonden 24-09 door RLZ/CC; uitkomst per referentie: …"); BESLISSINGEN "WEBHOOK-HERZENDEN
— 11 KOSTENEVENTS VASTLY (OPEN_ITEMS regel 13, 23-09)" alinea "Uitgevoerd 24-09"; `docs/regels/werkvoorraad-controlescherm.md` alinea; rapport
`docs/rapporten/2026-09-24-webhook-herzenden-uitgevoerd.md` + INDEX + "## Gelezen regels" mét per referentie de uitkomst en "werkt in productie: ja/nee".
Vastgoed herhaalt daarna de tegenproef (verwacht 0 nieuwe signalen, 11 documenten in de kostenintake) — dat is hún stap.
