# Btw-code uit de RLZ-grootboekrekening (opdracht Peter 14-09) — eindrapport

**Opdracht:** `opdrachten/gedaan/2026-09-14-btw-default-uit-rlz-grootboek.md` (bug/wens Peter 14-09, casus L.H.G. Holding:
inkoopfactuur, grootboek "mobiele kosten" gekozen → btw-veld leeg). Canoniek: BESLISSINGEN "BTW-DEFAULT UIT DE
RLZ-GROOTBOEKREKENING (Peter 14-09)"; RLZ-feiten: api-verkenning "Ledgers — standaard btw-code, STAP-0 14-09".

**Werkt in productie: niet gemeten** (bouw vóór deploy; meetrecept onderaan). **Belangrijkste bevinding vooraf:** het
RLZ-veld bestaat, maar op de rekening uit de casus staat in RLZ géén standaard btw-tarief — de module kan dus pas iets
overnemen zodra dat tarief in Reeleezee is gezet (beslispunt Peter, zie onder).

## 1. STAP 0 — welk veld draagt de standaard btw-code (lees-only, productie)

Zestien `rlz-lezen`-calls via `scripts/gcp/nameting.sh` (impersonatie `nameting@`), administraties L.H.G. Holding B.V.,
Universal Steigerbouw B.V., Administratiekantoor Nijenhuis C.V., Kempen Facilities B.V., Zilver Beheer B.V.

- **Veld gevonden: `Account.PreferentialTaxRate`** (type `VatRate`, navigatie) — genoemd in de publieke Help-modellen
  van `PUT/GET {adminId}/Ledgers`, zichtbaar alleen mét `$expand=PreferentialTaxRate`. Op de record-vorm
  `Ledgers/{id}?$expand=PreferentialTaxRate` verschijnt de sleutel; op de collectie verschijnt een null-navigatie niet
  (andere navigaties zoals `BalanceAccount` wél). Onbekende expand-namen worden stil genegeerd (bekend).
- **Casus-rekening: LHG 4404 "Kosten mobiele telefonie" → `PreferentialTaxRate: null`.** RLZ draagt op die rekening via
  de API géén standaard btw-tarief. `TaxReturnComponent` (btw-rubriek) is óók null; RGS-koppeling `WBedKanTef`.
- **Geen positief geval gevonden:** `$filter=PreferentialTaxRate ne null` (en `/id ne null`, `/Percentage ge 0`) geeft
  in alle vijf administraties `[]`; `eq null` geeft rijen (het filter wordt geëvalueerd). Dat de collectie-vorm een
  GEVULDE waarde als `{id}` meegeeft is daarmee niet live bewezen — open bewijspunt, de sync is fail-safe (geen sleutel
  = geen default = gedrag van vóór vandaag).
- Randbevinding: `rlz-lezen` matcht de administratienaam op `ilike` — "LHG Holding" = 0 treffers, de rij heet "L.H.G.
  Holding B.V."; een niet-eenduidige term geeft de kandidatenlijst (handig als naamzoeker).

**Keuze zonder Peter:** de opdracht zei "bestaat zo'n veld niet, dan stoppen". Het veld bestaat; alleen de waarde
ontbreekt in de casus. Daarom gebouwd zoals gevraagd, en de waarneming "RLZ heeft daar een standaard btw-code" eerlijk
als beslispunt teruggelegd in plaats van iets te verzinnen.

## 2. Datalaag (migratie 0142)

- `platform.grootboekrekening.standaard_taxrate_id` UUID NULL; model `Grootboekrekening.standaard_taxrate_id`. Geen FK
  naar `taxrate_cache` (zelfde overweging als 0108).
- Eén leesroute: `leesroutes.LEDGERS` draagt nu `params=(("$expand","PreferentialTaxRate"),)`; probe én sync sturen
  dezelfde query (`_sync_generiek(params=…)`, `voer_probe_uit`). `sync/service.py::standaard_taxrate_uit_ledger`:
  `{id}` → UUID, sleutel ontbreekt/null/rommel → None. Elke sync herschrijft de kolom; backfill = eerstvolgende
  `sync-alles`, geen aparte job.
- DTO `GrootboekOptieResponse.standaard_taxrate_id` op `GET /administraties/{id}/grootboek`.
- Afsluitroutine: `make migrate` dev-DB `0141 -> 0142`, `alembic check` "No new upgrade operations detected", live 200
  op de grootboek-route (uvicorn 8011, Beheerder-token), `schema_referentie.sql` ververst (head 0142).

## 3. Winnaarsvolgorde btw-code (regel_prefill.py, bindend)

1 mens · 2 factuur berekend · 3 leverancier-geheugen · 4 factuur verlegd · **5 grootboek-default (`btw_bron='grootboek'`,
chip "standaard grootboek")** · 6 administratie-default · 7 leeg.

- Stap 5 vult alleen een leeg btw-veld op een regel mét grootboek; het tarief moet in de actuele `taxrate_cache` staan;
  geheugen mét btw wint. **A3 "bewust leeg" (0 %/ambigu) remt deze stap niet** — expliciete RLZ-keuze, geen
  scan-afleiding (conform opdrachttekst). Herkomst "grootboek" triggert de A10-autosave; de chip komt na heropenen terug.
- **Grootboek-wissel in het controlescherm** (`BoekvoorstelPanel.wijzigRegel`): kiest de mens een rekening, dan volgt de
  btw de default van die rekening mét chip — alleen als de btw leeg is óf zelf een grootboek-/administratie-default was.
  Mens, factuur (berekend/verlegd) en geheugen winnen (zelfde volgorde als server-side). Rekening zonder default: een
  eerder gevolgde grootboek-default gaat weg; het btw-bedrag rekent mee zolang het niet handmatig is.

## 4. Odoo

Geen parkeerpost: `account.account.tax_ids` (Default Taxes) wordt meegelezen; `verrijk_grootboek_met_btw_default` legt
'm tegen de gelezen inkoop-btw — precies één inkoop-belasting = default, nul/meerdere = None (meerduidig = nooit
invullen), de synthetische "Geen btw (0%)" telt nooit. Live tegen een Odoo-company niet gemeten.

## 5. Af — tests en poorten

| Poort | Uitkomst |
|---|---|
| Gouden set nieuwe casus (u) `tests/keten/test_u_btw_grootboek_default.py` | 3 groen (prefill/DTO/autosave/checks/heropenen; zonder default blijft leeg) |
| `frontend/scripts/keten_sweep.sh` | 11 metingen gelijk, 0 nieuwe baselines |
| `tests/documenten/test_btw_grootboek_default.py` | 6 groen (winnaarsvolgorde incl. bewust-leeg, verdwenen tarief, samengevoegd) |
| `tests/sync/test_service.py` +3, `tests/odoo/test_basis.py` +2, `tests/rlz/test_leesroutes.py` (probe mét query) | groen |
| Frontend `regelVoorstelChips.test.ts` +1, `BoekvoorstelPanel.btwgrootboek.test.tsx` 4 (server-chip, wissel volgt + bedrag + weg zonder default, mens wint, factuur wint) | 44 groen over 4 bestanden; `tsc -b` groen |
| Volledige backend-suite | 5750 groen, 8 rood (51 min) — alle acht fake-RLZ-clients in `tests/beheer`/`tests/credentialstore` zonder `params`-kwarg op `get()` (de probe stuurt nu `$expand` mee); fakes aangepast, de 81 tests van die bestanden + docs-guards daarna groen |

Docs: BESLISSINGEN nieuwe sectie, CLAUDE.md-verwijsregel (109.863 tekens), api-verkenning STAP-0-sectie, WAT_IS_NIEUW-blok
"Btw-code volgt de standaard van de grootboekrekening".

## 6. Meetrecept ná deploy (werkt in productie: ja/nee)

1. Ná de eerste `sync-alles` (of on-demand grootboek-sync van LHG): `GET /administraties/<LHG>/grootboek` toont per
   rekening `standaard_taxrate_id`; lees-only RLZ-kant: `scripts/gcp/nameting.sh rlz-lezen --administratie "L.H.G. Holding"
   --pad Ledgers --record-via-filter "AccountNumber eq '4404'" --expand PreferentialTaxRate`.
2. LHG Holding, nieuw document, kies "4404 Kosten mobiele telefonie" → btw gevuld mét chip "standaard grootboek".
3. **Vooraf nodig:** Peter zet in Reeleezee op 4404 het voorkeurs-btw-tarief (STAP-0: nu null). Blijft het veld dan nog
   leeg, dan is dat een echte fout (collectie geeft de gevulde navigatie niet mee → terugval record-vorm/filter, zie
   BESLISSINGEN beslispunt b).

## 7. Beslispunten Peter

- (a) Waar komt de "standaard btw-code" die Peter in RLZ ziet vandaan: voorkeurstarief op de rekening (→ zetten in RLZ),
  het favoriete tarief als UI-default, of de laatste boeking op de crediteur? Snelste alternatief voor LHG: de
  administratie-default (Instellingen › Boeken & AI) op "NL, Hoog Tarief".
- (b) Open bewijspunt: een GEVULDE `PreferentialTaxRate` op de collectie-vorm is live niet gezien; het meetrecept is de
  eerste positieve meting.
