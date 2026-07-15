# Ontwerp — IBAN-wissel vier-ogen-accordering (goedgekeurd, PART A gebouwd)

> **Status: goedgekeurd (Cowork-mockup 2026-07-15, akkoord Peter) — PART A (backend + tests)
> gebouwd 2026-07-15; PART B (UI) volgt** (register: `docs/BESLISSINGEN.md`). Er is geen
> mockup-bestand voor deze flow; dit document is de canonieke vastlegging van de goedgekeurde
> flow (capture-at-acceptance, WERKWIJZE v1.4). Bouwt voort op de bestaande
> IBAN-wissel-fraudecontrole: `checks.py::check_iban_wissel`, `leverancier_iban.py`
> (vertrouwde set: rlz_seed/baseline/bevestigd), migratie 0019.

## Goedgekeurde flow

- **Instelling per administratie "IBAN-wissel accorderen door"**: één of meer medewerkers
  binnen de scope van de administratie; lege instelling → valt terug op de (actieve)
  beheerder(s). Wijzigen is Beheerder-only, elke wijziging in het audit_event.
- **Accordering-record** (`boekhouding.iban_accordering`, migratie 0024): administratie,
  crediteur, document, nieuw IBAN, soort (`regulier` | `g_rekening`), aangevraagd_door/-op,
  status (`open` | `geaccordeerd` | `afgewezen`), besloten_door/-op, afwijs_reden, en
  `status_voor_accordering` (herkomst-herstel, zelfde `status_voor_*`-patroon als
  vragen/afwijzen). RLS per administratie; append-only historie (geen DELETE-grant); één open
  accordering per document (partiële unique index).
- **Aanbieden** (aanvrager, na een IBAN-wissel-blokkade): maakt een open accordering en zet het
  document op **`wacht_op_iban_accordering`** (statusmachine-uitbreiding) — boeken is daaruit
  geblokkeerd; de herkomst-status wordt onthouden.
- **Accorderen** — vier-ogen, server-side afgedwongen: alleen door een medewerker die (a) in de
  ingestelde accordeur-set zit (of een actieve beheerder is bij lege instelling) én (b) níét
  de aanvrager is. Gevolg: het nieuwe IBAN gaat de vertrouwde set in
  (`leverancier_iban`, bron `bevestigd`, met besluter als bevestiger; aanvrager én besluter
  staan op het accordering-record en in het audit_event), het document gaat terug naar exact
  de herkomst-status en boeken is weer bereikbaar via de normale route (harde checks draaien
  sowieso opnieuw bij de boekactie).
- **Afwijzen** (zelfde accordeur-eisen, dus óók vier-ogen): reden **verplicht** (schema +
  service + DB-CHECK); de accordering gaat naar `afgewezen`, het document **blijft op
  `wacht_op_iban_accordering`** (geblokkeerd) en is via de afgewezen accordering (mét reden)
  gemarkeerd als verdacht. Geen automatische vervolgactie.
- **audit_event** op aanbieden (`iban_accordering_aangeboden`), accorderen
  (`iban_accordering_geaccordeerd`) en afwijzen (`iban_accordering_afgewezen`); de
  accordeur-instelling audit als `iban_accordeurs_gewijzigd`.

## Bewuste keuzes bij de bouw (PART A, ter review)

1. **Direct-bevestig-endpoint verwijderd.** Het bestaande
   `POST /administraties/{id}/crediteuren/{vendor}/ibans` liet élke gescoopte gebruiker een
   IBAN eigenhandig aan de vertrouwde set toevoegen — dat maakt vier-ogen omzeilbaar en is dus
   met deze flow in tegenspraak. Het endpoint had nog geen frontend-gebruiker en geen eigen
   endpoint-tests; de servicefunctie `leverancier_iban.bevestig_iban` blijft bestaan en wordt
   nu uitsluitend door de accordering (na vier ogen) aangeroepen.
2. **Opnieuw aanbieden ná een afwijzing kan.** Een afgewezen accordering laat het document op
   `wacht_op_iban_accordering` staan; zonder uitweg zou dat een doodlopende status zijn (ook
   verwijderen+herstellen komt er weer op terug). Daarom mag er vanuit die status een níéuwe
   aanvraag gedaan worden zolang er geen open accordering is (bv. na telefonisch navragen bij
   de leverancier); de herkomst-status reist mee van de vorige accordering. Elke ronde is een
   volledige nieuwe vier-ogen-beoordeling met eigen audit-spoor.
3. **Al-vertrouwd IBAN wordt geweigerd bij aanbieden** — een accordering over een IBAN dat al
   in de vertrouwde set zit is per definitie ruis (zichtbare fout, geen stille no-op).
4. **`soort` komt van de aanvrager** (regulier/G-rekening, WKA-context zichtbaar voor de
   accordeur) — het is informatie voor het vier-ogen-besluit en het dossier; de bevestiging
   zelf maakt de rekening vertrouwd, er is geen aparte G-rekening-klasse in de vertrouwde set
   (consistent met `bevestig_iban`).
