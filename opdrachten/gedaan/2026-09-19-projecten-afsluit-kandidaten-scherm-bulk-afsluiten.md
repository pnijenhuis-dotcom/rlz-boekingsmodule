uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-projecten-afsluiten-tab-bulk.md

Domeinen: verplichtingen-projecten-voorraad, kantoor-frontend

# OPDRACHT 19-09 — Projecten: tab "Afsluiten? (N)" mét bulk-afsluiten (Peter 19-09: "welk project is afgesloten? dat onderscheid
# maken wij nu nog niet") — voorwaarde voor de verdeelsleutel-opdracht van vanochtend

**Feit:** sinds 0160 bestaat de projectstatus, maar geen enkel project is afgesloten; de kandidatenmotor bestaat alleen als lees-only CLI
`projecten-afsluit-kandidaten`. De opdracht "projectverdeling sluit afgesloten projecten uit" (lopend) heeft dus pas effect als iemand
kan afsluiten zonder per project te klikken. Bij Universal heten twee projecten "Afgesloten …" terwijl ze actief zijn.

## Bouw
1. Projecten (per administratie én kantoorbreed) krijgt een tab **"Afsluiten? (N)"** uit dezelfde motor als de CLI. Kandidaat =
   één of meer redenen: geen inkoop/verkoop/uren/planning in de laatste 6 maanden (instelbaar per administratie), eindfactuur/
   eindafrekening geboekt, naam bevat "afgesloten", `looptijd_tot` verstreken. Per rij: reden(en), laatste activiteit (soort, datum,
   bedrag, boekstuk), open posten (inkoop nog niet geboekt / verplichting open / uren niet gekeurd = chip "let op", geen blokkade).
2. Vinkjes + **"Afsluiten (N)"** → de bestaande 0160-flow per project (RLZ `IsActive` uit → teruglezen, RLZ wint; Odoo archived waar van
   toepassing), audit + tijdlijn per project, uitkomst per rij (gelukt / RLZ weigerde mét reden / al inactief). Nooit automatisch.
3. **"Niet afsluiten"** per rij mét reden (verplicht) → rij verdwijnt uit de kandidaten tot er nieuwe activiteit is (onthouden per
   project, audit). Zichtbaar/bedienbaar voor Beheerder én kantoorgebruikers mét Projecten-recht (Haci/Iris bij Universal); veld-app niet.
4. Zoekveld + filter op reden; deeplink `?tab=afsluiten`; overflow-sweep; contrast; comboboxen; `linkbtn`/`btn`.
5. Rapport: de Universal-kandidatenlijst (aantal per reden, de twee "Afgesloten …"-projecten bovenaan) zodat Peter/Haci morgen kunnen
   afvinken. Regels-tekst `verplichtingen-projecten-voorraad.md`, BESLISSINGEN-rij, WAT_IS_NIEUW ("Projecten die klaar lijken staan
   onder 'Afsluiten?' — afvinken en klaar"). Tests: kandidaat-redenen, bulk-uitkomst per rij, "niet afsluiten" onthouden, rechten.
   Nameting ná deploy: Universal › Projecten › Afsluiten? toont N kandidaten — "werkt in productie: ja/nee".
