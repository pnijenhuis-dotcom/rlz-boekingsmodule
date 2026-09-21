uitgevoerd 2026-09-21, rapport: docs/rapporten/2026-09-21-groepssaldi-fix.md

Domeinen: administraties-instellingen, reconciliatie, werkloop-productie

# BUG 21-09 — Groepssaldi debiteuren/crediteuren: álle 35 administraties van "Kempen groep" status `fout` in productie
# (RLZ `$filter AccountType eq 3` = enum-vs-int 400; Odoo `deprecated` bestaat niet in Odoo 19)

**Feit (Cowork 21-09 ~09:00, `GET /groepen/97c51913-30d8-4250-89eb-5c7d7a1355c5/saldi` in Peters sessie, bron `stand`, datum
2026-09-21, 35 leden / 35 in scope / 0 zonder stand):** 35 × `status: fout`, 0 rijen met een saldo, `totalen` leeg. Twee oorzaken:

1. **33 × RLZ:** `GET /<admin>/Ledgers?$filter=IsTotalAccount eq false and (AccountType eq 3 or AccountType eq 4)` → **400**
   `A binary operator with incompatible types was detected. Found operand types 'Reeleezee.DTO.AccountTypeEnum' and 'Edm.Int32'`.
   `AccountType` is in RLZ's OData-model een enum; een int-literal in `$filter` is ongeldig. `app/groepen/saldi.py::RlzBron._alle_ledgers`
   (regel ~180). Elk ander pad in de code filtert Ledgers alléén op booleans/strings (`IsTotalAccount eq false`, `IsFixedAssetAccount eq true`,
   `AccountNumber ge …`) — dat werkt; nergens anders staat een `AccountType eq <int>`.
2. **2 × Odoo (Bonte Hoeve + de tweede Odoo-lid):** `account.account.search_read` → 500 `Invalid field account.account.deprecated`.
   `saldi.py::OdooBron.rekeningen` (regel ~258) filtert `[["deprecated","=",False]]`; in Odoo 19 is dat veld weg — `app/odoo/sync.py:126`
   gebruikt al de juiste vorm `["active","=",True]`.

Gevolg: de kaart op de klantenlijst en `groep-saldi` leveren sinds de deploy van 16-09 niets; het rapport 16-09 zei "werkt in
productie: niet gemeten" en dat is er nooit van gekomen. Peters vraag van 16-09 ("huidig saldo debiteuren/crediteuren Kempengroep")
is dus nog steeds onbeantwoord.

## Opdracht
A. **RLZ-filter:** verwijder het `AccountType`-deel uit `$filter` (alleen `IsTotalAccount eq false` blijft, `$expand=SystemAccountList`,
   `$top` mét paginering als `@odata.nextLink` komt — 500 is een aanname, Universal heeft meer rekeningen? meet het) en toets `AccountType`
   client-side (`int(r["AccountType"]) in (3, 4)`, bestaande `vind_rekeningen_rlz`). Geen enum-literal-syntax proberen
   (`Reeleezee.DTO.AccountTypeEnum'…'`) zonder STAP-0-bewijs — client-side filteren is deterministisch en bewezen.
B. **Odoo-domein:** `deprecated` → `active = True` (identiek aan `odoo/sync.py`). Sweep: `grep -rn deprecated backend/app` — élke
   treffer in een Odoo-domein gaat mee.
C. **Waarom vingen de tests dit niet:** de suite mockt de client en toetst nooit de letterlijke `$filter`-string tegen bekend RLZ-gedrag.
   Voeg een guard toe die élke `$filter` in `backend/app` op `AccountType eq <cijfer>` afkeurt (regex over de code, patroon
   `tests/unit/test_regels_index.py`), plus een test dat het Odoo-domein van `OdooBron` geen velden gebruikt buiten de lijst die
   `odoo/sync.py` gebruikt. Les naar `Platform/registers/verbeteringen.md` (21-09): "een 16-09-feature mét 'werkt in productie: niet
   gemeten' stond vijf dagen kapot in productie zonder signaal" → **fout-status op de groepssaldi-stand = LET-OP in het reconciliatieblok**
   (systeemmail), niet alleen een grijze kaart: als ≥ 1 lid `fout` heeft ná de nachtelijke meting, bevinding `groep_saldo_fout` (start in
   `meten`? NEE — dit is een regressie-detector, geen nieuwe domeinbevinding: direct LET-OP, regel reconciliatie 1 "regressies =
   systeemfout — automatisch gemeld").
D. **Nameting ná deploy (workflow-onderdeel toevoegen, `niet vóór:` de deploy):** `nameting.sh groep-saldi --groep "Kempen groep"` live
   én de nachtelijke stand van de volgende ochtend: verwacht 35 × `ok` (of `geen_rekening`/`overgeslagen` mét reden), totalen bruto =
   zonder-IC + IC. Rapportregel per lid: naam, status, debiteuren, crediteuren, IC-deel — dat rapport is Peters antwoord. Geen namen van
   debiteuren/crediteuren (PII-regel uit saldi.py blijft).
E. Rapport `docs/rapporten/2026-09-21-groepssaldi-fix.md` + INDEX + Gelezen regels; BESLISSINGEN-rij "GROEPSSALDI — PRODUCTIEFOUT
   16→21-09 (enumfilter + deprecated)"; WAT_IS_NIEUW één klantleesbare regel; CLAUDE.md hooguit één verwijsregel.
