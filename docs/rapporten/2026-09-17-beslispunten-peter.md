# Beslispunten voor Peter — run 17-09 (defaults gekozen, werk is doorgegaan)

Per opdracht de keuzes waar de opdracht ruimte liet of waar de bouw afweek. Default = wat nu gebouwd is; een ander besluit is een
vervolg-opdracht via `opdrachten/inbox/`. Werkt in productie: n.v.t. (beslispuntenlijst) — per opdracht in het eigen rapport.

## Opdracht 1 — SPOED Xcode Cloud / Apple 1.1 live (`2026-09-17-apple-1-1-live-xcode-cloud.md`)

1. **`STORE_LINK_IOS` + `STORE_APP_VERSIE_IOS` óók in `BASIS_ENVS` van de jobs.** De opdracht noemde alleen deploy.yml; de
   herinnerings-/uitnodigingsmails lopen ook uit jobs (rlz-accordeur-herinneringen). Alternatief: alleen de service.
2. **Nameting-via-gh dekt alleen commando's mét een workflow-onderdeel** (doorbelasting-aansluiting, app-bundels, reconciliatie,
   btw-default, a/b/c). Een ad-hoc `rlz-lezen` zonder onderdeel weigert (exit 3) i.p.v. stil op de gebruikerssessie terug te vallen;
   argumenten worden niet doorgegeven (het onderdeel draagt zijn vaste recept). Alternatief: een generiek `workflow_dispatch`-onderdeel
   "cli" mét vrije argumenten (allowlist blijft) — komt terug in opdracht 3 (feiten eerst).
3. **OTA-bundel volgt de gebouwde schil.** De deploy registreert de bundel per RUNTIME = `APP_MARKETING_VERSIE`; ná de bump naar 1.2
   krijgt de live 1.1-schil dus geen OTA-bundel meer (manifest 1.1 = "geen bundel"). Alternatief: de bundel óók onder de store-versie
   registreren (`STORE_APP_VERSIE_IOS`) zolang de schil-code niet veranderde — vergt een compatibiliteitsregel; niet gebouwd.
4. **Service-SA-binding niet zelf gezet** (owner-IAM = Peter, conform de opdracht); klikpunt mét het exacte commando in het rapport.
