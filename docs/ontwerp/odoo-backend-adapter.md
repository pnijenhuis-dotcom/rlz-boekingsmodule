# Ontwerp — Odoo-backend-adapter (verkenning, GEPARKEERD)

> **Status: verkenning / geparkeerd — bouwen bij de eerste concrete Odoo-klant** (register:
> `docs/BESLISSINGEN.md`). Architectuurfundament: **Platform-besluit 0016** ("Boekhoud-backend
> als port/adapters; per administratie een koppeling-type",
> `Platform/besluiten/0016-boekhoud-backend-port-adapters.md`) — de administratie ís de
> backend-grens, `backend_type` is uitsluitend een routeringssleutel voor de adapter-registry,
> het domein vertakt nooit op backend_type, en elke adapter draagt een capability-contract
> (zichtbare "niet ondersteund"-fout, nooit een stille no-op) + rechten-probe bij setup.
> Dit document legt de geverifieerde Odoo-feiten vast zodat de adapter-bouw straks niet met een
> lege verkenning begint.

## Geverifieerde Odoo 19.0-feiten (bron: officiële Odoo-docs, geraadpleegd 2026-07-15)

- **Doel-API = JSON-2**: `POST /json/2/<model>/<method>` met bearer-API-key en uitsluitend
  benoemde argumenten. **XML-RPC en JSON-RPC zijn uitgefaseerd**: verdwijnen in Odoo 22
  (najaar 2028) en op Odoo Online al bij 21.1 (winter 2027) — een nieuwe adapter begint dus
  direct op JSON-2, niet op de legacy-RPC's.
- **Beschikbaarheid externe API is plan-afhankelijk**: alleen op het **Custom** Odoo-plan
  (niet op One App Free of Standard). → Bij elke kandidaat-Odoo-klant vóóraf checken welk plan
  er loopt; zonder Custom-plan is er geen koppeling mogelijk (rechten-probe uit besluit 0016
  vangt dit bij setup zichtbaar af).
- **API-keys hebben een maximale looptijd van 3 maanden** → kwartaalrotatie opnemen in het
  credential-beheer (credential-store, besluit 0012; koppeling+credential-model, besluit 0016).
  Rotatie moet een beheerde, zichtbare handeling zijn — geen stil verlopende koppeling.
- **`create` geeft een server-side integer-id terug**: geen client-GUID zoals RLZ's
  PUT-met-client-GUID, en **geen ingebouwde idempotentie**. → Eigen duplicaatquery vóór elke
  write, parallel aan de RLZ-conclusie over actie 138 (CLAUDE.md kernprincipe 5: idempotentie
  is volledig onze verantwoordelijkheid, bij élke backend).
- **Geen atomiciteit over meerdere calls**: elke JSON-2-call draait in zijn eigen
  SQL-transactie. Een meerregelig document (factuur + regels + bijlage) is dus niet atomair
  via losse calls. → Twee opties voor de adapter, te kiezen bij bouw: (a) een **custom
  atomaire ORM-methode** in een eigen Odoo-module (server-side alles-of-niets), of (b)
  partial-failure-afhandeling + reconciliatie (zichtbare foutstatus + herstelpad — nooit een
  half document zonder spoor).

## Nog te verifiëren vóór de bouw (staat niet in de externe-API-docs)

1. **Attachments**: PDF-bijlagen via `ir.attachment` (base64) aan een factuur hangen — werkwijze
   en limieten live verifiëren (parallel aan RLZ's `/Uploads`-verkenning).
2. **Rate- en size-limits** van de JSON-2-API — client bouwt sowieso met throttling +
   retry/backoff (zelfde patroon als de RLZ-client).
3. **`ir.model.data`-externe-id's als idempotentie-anker**: kan een eigen externe id per
   document dienen als deterministische duplicaatsleutel (surrogaat voor de client-GUID)?

## Semantiekverschillen met RLZ (adapter-huiswerk, geen domein-vertakking)

- **Storno**: Odoo kent reverse/credit-move (een tegenboeking als nieuw document), níét RLZ's
  actie 19 "terug naar concept op hetzelfde document". De port-semantiek moet dit verschil
  absorberen; het domein mag het niet zien (guardrail besluit 0016).
- **Documentstatus**: Odoo hanteert draft/posted/cancel, geen RLZ-enumeratie 1/2/3
  (Tentative/Open/Closed). Mapping is adapter-verantwoordelijkheid; de afgeletterd-lading van
  RLZ-status 3 heeft in Odoo een ander anker (betaalstatus per move).

## Relatie met bestaande besluiten

- **Besluit 0016** — port/adapters + koppeling-record per administratie (canoniek fundament).
- **Besluit 0015** — backend-agnostische lees-operaties op de boekhoud-port (reporting-overlay).
- **Besluit 0012** — secrets uitsluitend via de credential-store, nooit inline in het
  koppeling-record.
- **CLAUDE.md kernprincipes** blijven backend-onafhankelijk gelden: boekhoudpakket = bron van
  waarheid, niets verwijderen in externe systemen, idempotentie overal, niets verdwijnt stil.
