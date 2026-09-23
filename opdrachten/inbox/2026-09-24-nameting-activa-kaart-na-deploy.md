Domeinen: activa, reconciliatie, werkloop-productie

niet vóór: 2026-09-24 07:15

# Nameting activa-kaart ná deploy (BUG 24-09: afschrijvingsrekening conventie + 422 + `activum_aanmaken_mislukt_mens` actie + 404-aanmaakroute) — poging 1

**Context:** bouwrapport `docs/rapporten/2026-09-23-activa-kaart-afschrijvingsrekening-conventie-422-actie-stap0.md`; BESLISSINGEN "ACTIVA / MVA —
FASE 1 GEBOUWD (Peter 21-09)" alinea "BUG 24-09"; api-verkenning "FixedAssets — aanmaakroute STAP-0". Regel 21-09: "niet gemeten" = vervolg-
opdracht mét `niet vóór:` + dispatch-onderdeel. Hoogstens drie pogingen (regel 22-09 (3)), daarna `mislukt/` mét de klikpunten.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij > 0, nooit rebase); service `rlz-backend` ÉN alle jobs (`spec.template.spec.template.spec.containers[0].image`)
op een image mét de bouw-commit van 23-09 avond als voorouder. Niet live → deze opdracht terug in `inbox/` mét `niet vóór:` +1 uur.

## Stap 1 — échte run van 24-09 06:30 (04:30 UTC)
`gh workflow run nameting -f onderdeel=activa-kaart` → bot-bestand `verkenning/nameting-activa-kaart-24-09.txt`. Verwacht:
- `db-lezen reconciliatie-bevindingen --administratie BLOw --param afwijking_soort=activum_aanmaken_mislukt_mens` → **2 rijen** (23619 € 935,00 en
  06052 € 680,00 — of 3 als MK22507863 € 1.078,10 óók als `mislukt` mét herkomst mens staat), stand `actie` (registry-default; facet NIET "in meting");
  `mail_status` van de run `actie=verzonden`; de oude `activum_aanmaken_mislukt`-rijen gesloten mét audit `reconciliatie_auto_gesloten`
  (`samenvatting.delta.verdwenen_afwijkingen` ≥ 2). Een 0 zonder scope is stil 0 (RLS) — altijd mét `--administratie`.
- `db-lezen activa-stand --administratie BLOw` rij `koppeling`: `mislukt` 2–3, `aangemaakt` 0 (herstel is een klikpunt, zie onder).
- request-log POST `…/activa-voorstel/*/aanmaken` sinds de deploy: 200/422 = gebruik; 5xx = ROOD.

## Stap 2 — klikpunten Peter (niet door CC)
1. **STAP-0 deel 2 (schrijvend) op de RLZ-testadministratie** "Administratiekantoor Nijenhuis (test)" `faae29c5`: dearchiveren mét TESTADMIN-login,
   Boeken AAN, één TEST-inkoopfactuur (TEST-ACTIVA-…, regel 0107 ≥ € 450) boeken, daarna de drie PUT-varianten V0/V1/V2 (+ V3 kostenrekening)
   uit api-verkenning "FixedAssets — aanmaakroute STAP-0" deel 2 — uitkomst in api-verkenning; pas dán `maak_aan_in_rlz` aanpassen (bouw-opdracht).
2. **Herstel BLOw (ná deel 2):** open BLOw B.V → inkoopfacturen 23619 (RLZ-04-00000400, € 935,00, 23-09), 06052 (RLZ-04-00000459, € 680,00, 23-09)
   en MK22507863 (€ 1.078,10, 18-12-2025) → kaart "Activum aanmaken?" → afschrijvingsrekening staat voorgevuld (0108, chip "conventie (code + 1)") →
   "Activum aanmaken". Verwacht ná de routefix: koppeling `aangemaakt`, RLZ-register BLOw 0 → 3 (`rlz-lezen --administratie BLOw --pad FixedAssets`,
   `InvoiceReference` 23619/06052/MK22507863). Vóór de routefix geeft de knop opnieuw de nette 404-reden — dat is de verwachte stand.

## Stap 3 — rapport
`docs/rapporten/2026-09-24-nameting-activa-kaart-na-deploy.md` + INDEX + "## Gelezen regels"; BESLISSINGEN-alinea "Gemeten 24-09" onder
"ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)"; `docs/regels/activa.md` alinea; regel "werkt in productie: ja/nee/niet gemeten" per onderdeel
(soort-promotie/actiemail, 422-pad, kaart-voorvulling, aanmaken in RLZ). Alles lees-only; geen RLZ-write door CC.
