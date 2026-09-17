# Regels — Btw: codes, defaults, verlegd, buitenland

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Btw-code uit de scan en het factuurtotaal, defaults uit de RLZ-grootboekrekening en de eigen historie, verlegd-herkenning (vermelding, kolomcode, onderaannemer), buitenland-signaal, verlegd-tarief deterministisch.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-tarief buitenland** (casus Labo Derva: crediteur-datakwaliteit, onvoorwaardelijk oranje signaal + foutvertaling
  `vertaal_rlz_boekfout`) — zie BESLISSINGEN "VERZAMELRUN 31-08 AVOND" blok A.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-code uit de scan** (`extractie/controle.py::leid_btw_af`; 0/onbepaalbaar/meerduidig = NOOIT invullen) — zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08" punt 3.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-default uit de RLZ-grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele telefonie"; migratie 0142):** RLZ `Account.PreferentialTaxRate` (alleen mét `Ledgers?$expand=PreferentialTaxRate`, één leesroute voor probe én sync) → `grootboekrekening.standaard_taxrate_id` (Odoo: de enige inkoop-belasting in `account.account.tax_ids`); winnaarsvolgorde btw in `regel_prefill.py` nu mens > factuur berekend > geheugen > factuur verlegd > **grootboek-default (`btw_bron='grootboek'`, chip "standaard grootboek")** > administratie-default > leeg, A3-"bewust leeg" remt deze stap niet; grootboek-wissel in het controlescherm laat een lege/default-btw de rekening volgen, mens/factuur/geheugen winnen. STAP-0: het veld bestaat maar is op LHG 4404 én in vijf administraties overal null — zie BESLISSINGEN "BTW-DEFAULT UIT DE RLZ-GROOTBOEKREKENING (Peter 14-09)" + api-verkenning "Ledgers — standaard btw-code, STAP-0 14-09". **Vervolg (besluit Cowork/Peter 14-09 "geen invulwerk in RLZ"; migratie 0143): dezelfde default AFGELEID uit de eigen historie** — per administratie × rekening de tariefverdeling over de inkoopregels in `boeking_observatie` (24 maanden; ≥ 5 regels én één tarief ≥ 90 % → `historie_taxrate_id` + `_n`/`_aandeel`; `app/geheugen/grootboek_btw_historie.py`, nachtelijk in `sync-alles` + ná de eerste sync), winnaarsvolgorde stap 5b `btw_bron='grootboek_historie'` (ORANJE "meestal op deze rekening (n×)", ná de RLZ-default, vóór de administratie-default, bewust-leeg remt WÉL), zelfde grootboek-wissel, lees-only CLI `btw-default-rapport` in de nameting-allowlist — zie BESLISSINGEN "BTW-DEFAULT UIT HISTORIE PER GROOTBOEKREKENING (Cowork/Peter 14-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw uit het factuurtotaal + bankformulier volgt de rekening (bug-onderzoek 15-09; casus LHG bleek een BANK-direct-boeking van een KPN-incasso, geen document; geen migratie):** `controle.py::leid_btw_af_uit_totaal` = tweede bewijs op factuurniveau (regels excl. btw + één btw-totaal → restant-netto × tarief ≈ restant-btw, één cent speling per regel, regel-btw deterministisch berekend en cent-exact sluitend, `btw_bron='factuur'` groen, top-level `btw_factuur_totaal`; 0 %/geen match/meerduidig blijft leeg), één-regel-terugval neemt 'm over; bank `HandmatigBoekenForm`/`SplitsenForm` volgen de grootboek-default (RLZ > historie, één bron `document/grootboekBtwDefault.ts`, mens wint); historie-default 0143 telt óók GEBOEKTE niet-automatische bank-direct-boekingen; gouden-set-casus w — zie BESLISSINGEN "BTW UIT HET FACTUURTOTAAL + BANKFORMULIER VOLGT DE REKENING (bug-onderzoek 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw verlegd — herkenning op kolomcode en onderaannemer (Peter 15-09, casus Olieman 32948 "V" in de BTW-kolom; geen migratie):** verlegd = (a) vermelding (bestaand) óf (b) verlegd-kolomcode ("V"/"VL"/"verl.") op álle regels mét bedrag (AI leest alleen de kolomtekst, regel-key `bc`, sentinel; `controle.is_verlegd_kolomcode`) óf (c) verlegd-leverancier (eerdere boekingen op een `IsRelayed`-tarief in het leverancier-geheugen, anders KvK-SBI 41/42/43 via de bestaande lookup, nooit vanuit de testomgeving) — telkens ÉN factuur-btw 0 (`boekvoorstel.bepaal_verlegd_basis`); uitkomst = verlegd-tarief oranje `factuur_verlegd` mét basis in `btw_bron_detail`; 0 % zonder basis blijft leeg (vrijgesteld ≠ verlegd); gouden-set-casus z — zie BESLISSINGEN "BTW VERLEGD — HERKENNING OP KOLOMCODE EN ONDERAANNEMER (Peter 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verlegd-tarief deterministisch (blok 6; migratie 0123):** `voorkeurs_verlegd_taxrate_id` per administratie (Beheerder) → meest gebruikt in RLZ-historie → bestaand pad → default, mét herkomst-chip — zie BESLISSINGEN "VERLEGD-TARIEF DETERMINISTISCH KIEZEN".

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Btw-tarief buitenland (CLAUDE.md `ed6d176` r. 354–360)

- **Btw-tarief buitenland (verzamelrun 31-08 blok A, casus Labo Derva):** RLZ weigert de
  boekactie (17) van een EU-/buitenland-tarief met 400 "ongeldig belastingtarief" zolang de
  crediteurkaart in RLZ geen land/btw-nummer draagt — crediteur-datakwaliteit, geen tarief-fout;
  land/btw-nummer zijn via de API níét leesbaar (api-verkenning "EU-tarieven op
  PurchaseInvoice-Actions"). Daarom: onvoorwaardelijk oranje signaal "Btw-tarief buitenland"
  bij élk buitenland-tarief (naam-prefix ≠ NL) + foutvertaling `vertaal_rlz_boekfout` mét
  handelingsperspectief op controlescherm/boek_fout/herstel-CLI.

### Domeinbeslissingen — Btw-code uit de scan (CLAUDE.md `ed6d176` r. 361–366)

- **Btw-code uit de scan (feedbackronde 26-08 punt 3):** ná AI-extractie leidt CODE per regel het
  tarief af (`extractie/controle.py::leid_btw_af`: netto × tarief ≈ btw ±1 ct tegen de gesyncte
  TaxRates; gelijk percentage → RLZ-favoriet `IsFavorite` wint; verlegd/vrijgesteld/gemengd doen
  niet mee) → vooraf ingevuld mét chip "uit factuur (21%)"; 0/onbepaalbaar/meerduidig = NOOIT
  invullen (0% is ambigu: geheugen per leverancier wint, anders mens); "btw verlegd"-vermelding
  = alleen een hint-chip. Harde checks blijven de poort.
