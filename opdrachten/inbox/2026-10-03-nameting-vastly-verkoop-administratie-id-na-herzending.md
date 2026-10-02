# Nameting 03-10 — Vastly-verkoop ná deploy van 02-10: administratie-id uit de UBL, terugval uit (poging 1 van 3)

niet vóór: 2026-10-03 09:00

Vervolg op `opdrachten/gedaan/2026-10-01-vastly-verkoop-administratie-id-uit-ubl-terugval-uit.md` (rapport
`docs/rapporten/2026-10-01-vastly-verkoop-administratie-id-terugval-uit.md`, "werkt in productie: niet gemeten"). Regel 21-09: "niet
gemeten" is een schuld mét vervaldatum. Lees-only; niets committen behalve het rapport.

LEESPLICHT: docs/regels/omzet.md (alinea 02-10), docs/regels/werkloop-productie.md, docs/regels/reconciliatie.md.

## Stap 0 — deploy-stand
`git rev-list --count main..origin/main` toetsen en zo nodig `merge --no-ff`; daarna service én job-image (`gcloud run jobs describe
rlz-reconciliatie … containers[0].image`) ≥ de commit van 02-10 (BESLISSINGEN "VASTLY-VERKOOP — ADMINISTRATIE-ID UIT DE UBL ALS EERSTE
BRON, TERUGVAL EN HISTORIE-AFLEIDING UIT (Peter 01-10)"). Niet live → opdracht terug in inbox mét `niet vóór:` +1 dag (max 3 pogingen).

## Stap 1 — is er al een herzonden UBL mét `RLZ-ADMINISTRATIE:`?
`gh workflow run nameting -f onderdeel=vastly-verkoop` → bot-bestand `verkenning/nameting-vastly-verkoop-<dd-mm>.txt`. Lees:
- `db-lezen vastly-verkoop`: koppelingen mét bron `ubl` (verwacht ≥ 1 zodra Vastly de her-aanlevering van de 39 heeft gedraaid; 0 ervóór);
  niet-gekoppelde documenten mét reden `administratie_id=…` (verwacht 0 — een onbekend id zou een bug aan één van beide kanten zijn);
- dry-run-telling: ná de her-aanlevering verwacht `TOTAAL: 0 kandidaten` of alleen `geweigerd` mét een reden die Vastly moet oplossen;
  vóór de her-aanlevering ongewijzigd 14 × `omzetrekening_ontbreekt` mét de NIEUWE redentekst "geen grootboekcode (cbc:AccountingCost) in
  de UBL — melden bij Vastly" (= bewijs dat de nieuwe code live is);
- request-log: 404 op `/reconciliatie/vastly/entiteit-koppelen`, `/vastly-instellingen` en `/vastly-omzetrekeningen` (niemand raakt de
  vervallen routes nog), eventuele POSTs `opnieuw-aanbieden`.
Geen her-aanlevering gezien → rapport mét "werkt in productie: niet gemeten (her-aanlevering Vastly nog niet gelopen — r.14)" en deze
opdracht terug in inbox mét `niet vóór:` +1 dag; derde keer → `opdrachten/mislukt/` mét het klikpunt (Cowork: seintje aan Vastly).

## Stap 2 — rapport
`docs/rapporten/<datum>-nameting-vastly-verkoop-administratie-id.md` + INDEX + "Gelezen regels"; regel "werkt in productie: ja/nee/niet
gemeten" voor (a) id-route (koppeling bron `ubl` + geboekt zonder mens), (b) weigering zonder code mét de nieuwe tekst, (c) vervallen routes
404. BESLISSINGEN-sectie van 01-10 alinea "Gemeten <datum>" + omzet.md.
