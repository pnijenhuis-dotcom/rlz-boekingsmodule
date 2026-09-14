# Btw-default per grootboekrekening afgeleid uit RLZ-historie (vervolg 14-09, migratie 0143) — eindrapport

**Opdracht:** `opdrachten/gedaan/2026-09-14-btw-default-uit-historie.md` (besluit Cowork/Peter 14-09: geen invulwerk in
RLZ — STAP-0 liet zien dat `Account.PreferentialTaxRate` overal null is, dus de 0142-default vult niets). Canoniek:
BESLISSINGEN "BTW-DEFAULT UIT HISTORIE PER GROOTBOEKREKENING (Cowork/Peter 14-09)".

**Werkt in productie: niet gemeten.** De bouw gaat vóór de deploy; het meetrecept staat onderaan en draait vanaf morgen
05:30 UTC automatisch mee in de dagelijkse nameting-workflow (nieuw onderdeel `btw-default`, uitkomst in
`verkenning/nameting-btw-default-l-h-g-holding-<dd-mm>.txt` en `…-universal-steigerbouw-<dd-mm>.txt`). De vraag "staat op
LHG 4404 nu een historie-default?" wordt daar beantwoord — mét de kanttekening dat de kolom pas gevuld is ná de eerste
`sync-alles` (07:00) ná de deploy; de eerste meting van 05:30 kan daarom nog "geen (nog niet afgeleid; n regels nu)" zeggen,
en dat aantal regels zegt dan al of de nacht erna 'm gaat vullen.

## 1. Afleiding uit historie (migratie 0143, `app/geheugen/grootboek_btw_historie.py`)

- Bron = `boekhouding.boeking_observatie` (RLZ-seed + app-boekingen — beide echte boekingen; dezelfde cache die de
  boekingsgeheugen-seed vult, dus **geen extra RLZ-verkeer**), `bron_datum` in de laatste 24 maanden (24 × 31 dagen).
- Regel: per administratie × grootboekrekening **n ≥ 5 regels én het meest voorkomende tarief ≥ 90 %** →
  `grootboekrekening.historie_taxrate_id`. `historie_taxrate_n` en `historie_taxrate_aandeel` (NUMERIC(5,4)) worden
  áltijd vastgelegd, ook zonder default ("geen — 10 regels, hoogste 80 %"); `historie_berekend_op` = laatste afleiding.
  Regels zonder btw-tarief tellen niet. Deterministisch, geen AI.
- Alleen gewijzigde rijen worden geschreven; een rekening zonder regels in het venster gaat terug naar NULL.
- Loopt **nachtelijk in `sync-alles`** (direct ná de Ledgers-sync; regel "OK btw-historie <administratie>: x/y rekeningen
  mét default, … gewijzigd, n inkoopregels" + eigen exit-telling) en **ná de eerste sync** (alleen als Ledgers "klaar";
  puur code, buiten de onderdelen/herprobeer-logica; een fout maakt de eerste sync nooit rood).
- Keuzes zonder Peter: (a) twee typed kolommen `_n`/`_aandeel` i.p.v. één JSON-"dekking" (queryable, zelfde betekenis);
  (b) rlz_seed én app-observaties tellen beide; (c) drempels zijn constanten (`MIN_REGELS`/`MIN_AANDEEL`), geen instelling.
- Bevinding: de boekingsgeheugen-seed voor een nieuwe administratie is een los CLI-commando (`seed-boekingsgeheugen`),
  niet in de onboarding — direct ná de eerste sync is de historie leeg en de afleiding terecht "geen". Beslispunt onder.

## 2. Winnaarsvolgorde (`regel_prefill.py`, één plek)

1 mens · 2 factuur berekend · 3 leverancier-geheugen · 4 factuur verlegd · 5 grootboek-default RLZ (`grootboek`, grijs) ·
**5b grootboek-default historie (`grootboek_historie`, ORANJE chip "meestal op deze rekening (n×)")** · 6
administratie-default · 7 leeg.

- Alleen op een regel mét grootboek, tarief in de actuele `taxrate_cache`, geheugen wint; **`btw_bewust_leeg` remt WÉL**
  (afleiding ≠ expliciete RLZ-keuze — zelfde A3-regel als de administratie-default; bij stap 5 remt 'm bewust niet).
- Oranje volgens de bestaande seed-only-regel: boeken bevestigt via het leverancier-geheugen, daarna groen — geen nieuwe
  kleurregel. Herkomst is een A10-autosave-trigger (checks zien dezelfde btw).
- Grootboek-wissel in het controlescherm: `GrootboekOptieDto.historie_taxrate_id`/`historie_taxrate_n`; de client-map neemt
  per rekening de RLZ-default en anders de historie-default; een gevolgde historie-btw gaat weg bij een rekening zonder
  default; mens/factuur/geheugen winnen (zelfde volgorde als server-side).

## 3. Meetrecept (lees-only CLI `btw-default-rapport`)

`btw-default-rapport --administratie <naam|uuid> [--alles]` (`app/geheugen/btw_default_cli.py`, allowlist `nameting.sh`):
kop mét observaties totaal + inkoopregels in het venster + laatste afleiding; per rekening RLZ-default / historie-default
(tarief, n×, aandeel) of "geen (n regels, hoogste x %)" + de verdeling. Naam-match ilike én zonder leestekens ("lhg
holding" vindt "L.H.G. Holding B.V.").

```
scripts/gcp/nameting.sh btw-default-rapport --administratie "L.H.G. Holding"
scripts/gcp/nameting.sh btw-default-rapport --administratie "Universal Steigerbouw"
```

Werkt in productie = de regel `4404  Kosten mobiele telefonie … NL, Hoog Tarief (n×, ≥ 90 %)` in het LHG-rapport. Zegt het
rapport "0 observaties totaal", dan heeft LHG geen boekingsgeheugen-seed en is de eerste stap `seed-boekingsgeheugen`
voor LHG als expliciete job-opdracht (beslispunt b).

## 4. Tests en afsluitroutine

- Backend nieuw: `tests/geheugen/test_grootboek_btw_historie.py` (9: drempels 4 = niets, 5/5 = ja, 9/10 = ja, 8/10 = nee,
  venster, regels zonder tarief, idempotent, vervallen default, terug naar NULL, fout-isolatie),
  `tests/documenten/test_btw_grootboek_historie_default.py` (5), `tests/beheer/test_eerste_sync_btw_historie.py` (2),
  `tests/geheugen/test_btw_default_cli.py` (1), gouden set casus (v) `tests/keten/test_v_btw_grootboek_historie.py` (3:
  prefill oranje mét detail, DTO/autosave/checks/heropenen + grootboek-lijst-DTO, 8/10 blijft leeg); casus (u) blijft
  groen. Guard `test_nameting_workflow.py` aangepast op het nieuwe onderdeel.
- Frontend: `regelVoorstelChips.test.ts` +1, `BoekvoorstelPanel.btwgrootboek.test.tsx` +2 (24 groen in de twee bestanden),
  changelog-guard 5 groen, `tsc -b` groen, `keten_sweep.sh` 11 metingen gelijk (geen baseline-wijziging).
- Backend-subset (tests/keten, documenten, sync, beheer, geheugen, unit, rlz, odoo): 2073 groen, 1 skipped, 1 rood —
  `test_nameting_workflow` op de oude guard-regel (de workflow kreeg het onderdeel `btw-default` tijdens de run); ná de
  guard-aanpassing 24/24 guard-tests groen (workflow, rapporten-index, CLAUDE.md-verwijzingen, keten-guard,
  migratie-metadata). Volledige suite niet gedraaid (subset dekt alle geraakte modules).
- Migratie-afsluitroutine: `make migrate` dev-DB `0142 -> 0143`, `alembic check` "No new upgrade operations detected", live
  `HTTP 200` op `GET /administraties/{id}/grootboek` (uvicorn 8011, Beheerder-token), CLI-smoke op de dev-DB,
  `schema_referentie.sql` ververst (head 0143).

## 5. Docs

BESLISSINGEN nieuwe sectie "BTW-DEFAULT UIT HISTORIE PER GROOTBOEKREKENING (Cowork/Peter 14-09)"; CLAUDE.md-verwijsregel
(vervolg bij de 0142-regel); WAT_IS_NIEUW-blok 14-09 aangevuld (de "Let op"-bullet over invullen in Reeleezee is vervangen
door de afleiding); nameting-workflow onderdeel `btw-default` (ook in `alles`).

## 6. Beslispunten Peter

- (a) Seed van het boekingsgeheugen automatisch in de onboarding (ná de eerste sync) zodat nieuwe administraties de
  historie-default de eerste nacht al krijgen — RLZ-verkeer N+1 Lines-calls, binnen het webfilter-budget te plannen.
- (b) Heeft LHG in productie geen observaties, dan eerst `seed-boekingsgeheugen` voor LHG als job-opdracht.
- (c) Drempels 5 regels / 90 % vast laten of instelbaar maken — pas ná de eerste productiecijfers.
