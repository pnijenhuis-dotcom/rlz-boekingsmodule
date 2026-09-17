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

## Opdracht 2 — SPOED dubbele betaling 1.214 valse bevindingen (`2026-09-17-dubbele-betaling-herdefinitie.md`)

1. **Crediteur in géén enkele cache bekend = geen uitspraak (geen bevinding, wél geteld als `zonder_factuurbron`).** De opdracht
   zegt "betalingen > facturen → bevinding"; zonder factuurbron zou élke tweede betaling aan een onbekende tegenpartij (loon,
   belastingdienst, privé) weer een valse bevinding zijn. Alternatief: onbekende crediteur = bevinding mét label "geen facturen
   bekend" — dat is de 16-09-regel in vermomming; niet gebouwd.
2. **Factuurbronnen = eigen caches, geen live RLZ-call** (module-documenten, RLZ-open-postencache incl. verdwenen, RLZ-koppelingen
   van de mutaties). De opdracht noemde "RLZ/Odoo, alle crediteurrecords"; de open-postencache ís de RLZ-bron (dagelijkse sync).
   Een live PurchaseInvoices-call per kandidaat komt terug als de nameting laat zien dat de cache facturen mist.
3. **Stand-opslag = JSONB-kolom op de bestaande singleton (migratie 0153)** i.p.v. een losse JSON-setting (die bestaat niet als
   generiek mechanisme). Code-defaults in de registry; DB-override wint.
4. **Titels "Automatisering wacht op voorwaarde"/"Automatisering stil" hernoemd** naar "Wacht op instelling"/"Stil sinds zeven
   dagen": door de per-administratie-begrenzing komen platformbrede LET-OP's eerder in de top-10 en de actiemail-guard verbiedt
   het blokwoord. UI-tekst wijzigt daardoor licht.
5. **Promotie van `dubbele_betaling_vermoed` naar de actiemail NIET gedaan** — pas ná de productiemeting (Hello Kitchen wél,
   periodieke tegenpartijen niet). Default blijft `meten`.
