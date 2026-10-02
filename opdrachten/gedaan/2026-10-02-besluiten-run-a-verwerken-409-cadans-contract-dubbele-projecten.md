uitgevoerd 2026-10-02, rapport: docs/rapporten/2026-10-02-besluiten-run-a.md

# Opdracht 02-10 avond — besluiten Peter op run A verwerken (geen nieuwe functies)

Peter 02-10 17:1x: "Ik volg jouw advies" op de vier beslispunten uit het run-A-rapport. Verwerk ze; klein houden, geen bijvangst.
LEESPLICHT: docs/regels/reconciliatie.md, docs/regels/werkvoorraad-controlescherm.md, docs/regels/verplichtingen-projecten-voorraad.md,
docs/regels/werkloop-productie.md; rapport docs/rapporten/2026-10-02-run-a.md; `docs/gesprekken/2026-10-02.md` (regel 17:1x).

## Besluiten (capture-at-acceptance → BESLISSINGEN "RUN A 02-10 …" per punt "BESLIST 02-10")
1. Punt 7: compacte regelweergave onder 738 px = definitief. Geen code.
2. Punt 8: recency-consensus (laatste drie app-bevestigde boekingen identiek) telt als "zeker" voor het grootboek-geheugen, náást
   ≥ 90 %. Geen code; alleen vastleggen + regels-alinea.
3. Punt 11: samenvoegregel = "oudste project mét boekingen blijft" voor 26149, 26053, 26064 en 26084; Peter heeft het "ja" voor de
   echte run vooraf gegeven ONDER VOORWAARDE dat de dry-run van 03-10 per nummer eenduidig is (precies twee kandidaten, geen conflict
   in koppelingen). Bouw: terminalbestand `opdrachten/terminal/2026-10-03-project-dubbel-samenvoegen.md` met stap 0 (image), stap 1
   dry-run per nummer (lees-only) en stap 2 `--uitvoeren` per nummer; Cowork leest stap 1 en geeft stap 2 vrij; niet-eenduidig = terug
   naar Peter. Niets zelf uitvoeren.
4. Punt 17: (a) de 7-dagen-cadans (1 u → 6 u → 24 u → dagelijks, max 7 dagen) geldt óók voor andere niet-2xx-antwoorden van Vastly
   (5xx, timeout, 429) — ná 7 dagen `mislukt` mét reden + bevinding `actie`; 4xx ≠ 409 blijft direct `mislukt` (payloadfout, herhalen
   zinloos); (b) voorstel-3c-409 is daarmee geaccordeerd: §3c in het koppelcontract definitief (versiebump v1.22, wijzigingslog),
   OPEN_ITEMS-item "voorstel-3c-409" afmelden met verwijzing; Platform apart committen.

## Bijvangst toegestaan (alleen dit)
- CLAUDE.md staat op ~95k tekens (> 90k waarschuwing): verplaats de per-run-detail van de regels 7–16 onder "Werkvoorraad …",
  12–13 onder "Uren & meerwerk …" en 6 onder "Reconciliatie …" WOORDELIJK naar `docs/regels/<domein>.md` (ze staan daar al grotendeels —
  dedupliceer) en laat in CLAUDE.md per punt één regel + verwijzing staan. Guard `test_claude_md_beslissingen_verwijzingen.py` groen,
  doel < 85k tekens. Geen inhoudelijke wijziging.

## Af
Suite + vitest + doc-guards groen; BESLISSINGEN-rijen; regels-alinea's; koppelcontract v1.22 + OPEN_ITEMS; terminalbestand voor 3;
rapport docs/rapporten/2026-10-02-besluiten-run-a.md + INDEX + "Gelezen regels" (kort, ≤ 25 regels); "werkt in productie: niet gemeten"
voor 4a (dispatch-onderdeel `webhook-wacht` dekt het). Committen; de Stop-hook pusht beide repo's.
