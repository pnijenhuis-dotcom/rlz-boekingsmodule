# Rapport 16-09 — Coffeeshop-omzet (ProfX Journaal) per artikelgroep + margerapport als kostprijs + bruto/netto-schakelaar + profiel "Winkel / kassa"

**Opdracht:** `opdrachten/gedaan/2026-09-16-omzet-coffeeshop-profx-journaal.md` (Peter 16-09, screenshot De Bazar Apeldoorn; blokken A–G;
bouwnorm `mockup/omzet-kassarapport-v2.html` = akkoord 12:20 mét twee correcties). Migratie 0150 (`administratie.kassa_profiel`).
**Werkt in productie: niet gemeten** — meetrecept hieronder.

## Gedaan
1. **Blok A — intake.** Herkenning op inhoud vóór de AI-classificatie (`herkenning.herken_pdf` op de tekstlaag): ProfX Journaal/Margerapport →
   documentsoort kassarapport, `bron` = `profx_journaal` / `profx_margerapport`, géén AI-call. Routering op `Bedrijf:` uit het journaal; het
   margerapport (zonder bedrijfsnaam) volgt het journaal uit dezelfde mail (`_profx_mail_tenaamstelling`) — de ketentest legde dat gat bloot.
   Lees-only CLI `kassarapporten-in-inkoopstroom` (nameting-allowlist) voor de al verkeerd geclassificeerde exemplaren; geboekt = alleen melden.
2. **Blok B — parser** (`app/omzet/bronnen/profx.py`): kop, artikelgroepen (bedrag − retour − korting), totalen, betaalwijzen (blad 3),
   sluitcontroles als check-rijen; artikellijst niet geboekt; dedupe via de bestaande periode-bewaking.
3. **Blok C — mapping/defaults:** Wiet/Hash/Joints/Edible vrijgesteld (Edible = niet-blokkerende controle "eerste keer bevestigen"),
   Dranken/Snacks laag, Headshop hoog — rekening/btw altijd uit het RLZ-schema van de administratie.
4. **Blok D — tegenzijde:** kas/PIN uit blad 3 via `bepaal_tegenzijde`; blad 3 ontbreekt = alles kas mét signaal.
5. **Blok E — bruto/netto:** `document/bedragModus.ts` + `BedragModusInput.tsx`; klikbaar kopje in `BoekvoorstelPanel` (inkoopregels, bron
   netto) en in het omzetscherm (bron bruto); voorkeur `rlz.bedragmodus`; zonder btw-code geen omrekening (tooltip); geen tegenwaarde onder de cel.
6. **Blok F — één scherm, twee boekingen:** `OmzetReviewScreen.tsx` herbouwd naar de mockup (tabel omzet · btw · inkoopwaarde · marge, strook
   betaalwijzen → tegenzijde, kaarten Verkoop/Kostprijs, knop "Boeken in RLZ (2 documenten)"/"(alleen omzet)"); zelfde kassadag → marge
   gebundeld in het journaal; weekrapport = eigen document mét periode-dekkingscontrole; dagscherm toont live `bron_detail.marge.stand`.
7. **Blok G — profiel "Winkel / kassa":** afgeleid (≥ 1 kassarapport, per administratie in `scoped_session(aid)` — `document` heeft geen
   Beheerder-bypass) + override `kassa_profiel` (0150), routes `GET/PATCH /administraties/{id}/kassa-profiel`, chip + filter in de
   administratielijst, profiel-regel bovenaan het Omzetbronnen-blok.
8. **Mockup** `mockup/omzet-kassarapport-v2.html` naar designpass-v2-klassen (paginakop, knop/knop.stil, status+dot, paneel .kop; inhoud
   ongewijzigd) en gecommit als bouwnorm.

## Tests
- Backend: `tests/omzet/test_profx.py` 12 groen; gouden set `tests/keten/test_ad_omzet_profx.py` 1 groen (casus `ad_omzet_profx_journaal`);
  keten-guard groen; rol-endpoint-sweep + omzet/intake/documenten/keten/beheer/unit — zie slotrapport voor de uitkomst van de laatste run.
- Frontend: `bedragModus.test.ts` 3, `BedragModusInput.test.tsx` 3, `OmzetReviewScreen.test.tsx` 10 (+2 ProfX), `AdministratiesV2.test.tsx` +1,
  `OmzetBronnenBlok.test.tsx` 4, changelog-guard 5; `tsc -b` groen; overflow-sweep instellingen 56/56 groen (omzetscherm heeft geen harnas).
- Migratie-routine: `make migrate` 0149→0150 dev-DB, live 200 op `GET`/`PATCH …/kassa-profiel` én `GET /instellingen/administraties`
  (uvicorn 8011, Beheerder-token), `schema_referentie.sql` ververst (head 0150).

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md` opdracht 9)
Edible vrijgesteld mét bevestig-chip · boekdatum = startdag kassadag · margerapport zelfde dag = bundelen (niet apart boeken), weekrapport =
eigen document · marge-kleur 35–70 % in het scherm (harde marge-check ongewijzigd) · kostprijs-tegenrekening = bestaande mapping-kolom.

## Meetrecept ná deploy
1. `scripts/gcp/nameting.sh kassarapporten-in-inkoopstroom --dagen 120` → het De Bazar-document (en eventuele eerdere van dezelfde afzender)
   staat in de lijst als `profx_journaal · herclassificeren` (of `melden (geboekt)`).
2. Documentenlijst De Bazar Apeldoorn → selecteer het document → ⋯ Type wijzigen → kassarapport → het omzet-controlescherm toont 7
   artikelgroepen, Σ omzet = € 10.998,16 (bruto), netto + btw sluit per regel; kopje "Omzet netto" klikken toont bruto; marge-chip
   "Margerapport ontbreekt · kostprijs later" zolang het margerapport niet is aangeboden.
3. Margerapport van dezelfde dag uploaden → chip "Margerapport gekoppeld · zelfde dag", kaart "Kostprijs → memoriaal" gevuld, knop
   "Boeken in RLZ (2 documenten)".
4. Instellingen › Administraties: chip "Winkel / kassa" op De Bazar Apeldoorn, filter "Profiel: Winkel / kassa" toont 'm; Boeken & AI ›
   Omzetbronnen: profiel-regel "aan · afgeleid".
5. Volgende mail "journaal en marge raport" van de coffeeshop → beide bijlagen toegewezen als kassarapport zonder AI-call, marge samengevoegd.
