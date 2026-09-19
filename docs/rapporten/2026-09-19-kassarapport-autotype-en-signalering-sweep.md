# Kassarapport automatisch typeren + sweep "signalering zonder handeling" (19-09)

Opdracht `opdrachten/gedaan/2026-09-19-kassarapport-automatisch-type-wijzigen-en-reconciliatie-acties-automatiseren.md` (Peter 19-09,
screenshot Inzicht › Reconciliatie Van Boxtel Horeca Exploitatie, Journaal 1-9/2-9/3-9: "dit zijn meldingen waar ik dus niks mee doe.
Als de module weet dat het verkoopboekingen zijn, wijzig het dan automatisch"). Deel A gebouwd + getest; deel B = lees-only sweep op
de leesreplica, niets gebouwd. Geen migratie, geen RLZ-write, geen AI. **Werkt in productie: niet gemeten** — de code deployt ná
deze run; meetrecept + nazorg onderaan, vervolg-opdracht in de inbox.

**Één regel voor Peter:** van de 340 "aandacht nodig" van vandaag verdwijnen er door deel A **4** direct (de vier ProfX-journalen van
Van Boxtel; de vijfde melding is het zachte signaal "alle regels op omzetrekeningen" en blijft mét knop); de 8 "omzet als
inkoopfactuur geboekt" bij Van Boxtel blijven mens-werk (storno achter de aangiftepoort). De sweep zegt: **de 174 "fouten" zijn één
systeemfout** (intercompany-blok vindt bij 174 doorbelastingsparen Kempen Facilities → 5 doelentiteiten de verkoopfactuur niet bij de
bron-administratie — sinds de eerste run van het blok op 18-09, geen mens kan er iets mee → opdracht in de inbox); de **492 "in
meting"** zijn vier soorten die bewust nog niet in de actiemail zitten (205 IC-ontbreekt-bij-ontvanger, 194 dubbele betaling
vermoed, 91 RC sluit niet, 2 dubbel projectnummer). Automatiseren volgens het patroon van deel A: alleen `kassarapport_in_werkvoorraad`
mét parser-treffer (gedaan). Alles anders blijft melding of is een systeemfout — tabel in deel B.

## Deel A — gebouwd

**Regel (herziet omzet-regel 3 van 16-09 avond):** een parser-treffer is eenduidig, dus doet het systeem het zelf. Eén motor
`backend/app/omzet/autotype.py`:

- **Herkenning** = exact de bestaande bron-parsers (`herken`: ProfX Journaal/Margerapport op de PDF-tekstlaag, zonnestudio-dagstaat/
  -kascheck en pilates-export op het raster; géén AI, geen AVG-gate). Het zachte signaal "alle boekingsregels op een omzetrekening"
  (geen parser) is NIET eenduidig en blijft de bevinding mét knop "Type wijzigen → kassarapport".
- **Bij intake/upload** (`documenten/service.py::upload_document`, dus upload-zone, klantpagina, bulk-upload en splitsing): een
  INKOOPFACTUUR mét treffer krijgt vóór de extractie soort `kassarapport`, tijdlijnregel "type automatisch gewijzigd: inkoopfactuur →
  kassarapport (ProfX-journaal herkend)", audit `soort_automatisch_gewijzigd` (bron, afzender, ingang). De ProfX-verwerking is
  deterministisch → het document staat direct in het omzet-controlescherm.
- **Dagelijkse reconciliatie** (échte run, niet lees-only): `autotype.verwerk_werkvoorraad` draait vóór de omzet-toets en zet élk
  werkvoorraad-document mét treffer om via de bestaande soort-wissel (`documenten/soort.py::wijzig_documentsoort(automatisch=…)` →
  ONTVANGEN, extractie opnieuw via het omzetpad); één audit-rij `kassarapport_autotype_run` per administratie (verwacht/gedaan/
  overgeslagen mét reden). Wat overblijft is een melding die zegt waaróm: "al eerder teruggezet naar inkoopfactuur", "status liet de
  wissel niet toe", "systeemfout — automatisch gemeld". Lees-only (`--lees-only`, losse CLI) schrijft niets en labelt treffers
  "automatisch bij de dagelijkse run".
- **Terugweg + leren:** chip "automatisch getypeerd" + "Tóch inkoopfactuur…" (verplichte reden ≥ 5 tekens,
  `frontend/src/omzet/TochInkoopfactuurModal.tsx`) → `POST /administraties/{id}/omzet/documenten/{doc}/toch-inkoopfactuur`:
  soort-wissel terug naar de inkoopstroom + observatie `typering_correctie` op administratie × bron × afzender. Ná 2 correcties
  binnen 180 dagen op die sleutel meldt het systeem i.p.v. doen — bij upload, bij de intake-herkenning van 16-09
  (`soort_door_systeem=True`; een mens-keuze "kassarapport" wordt nooit overruled) en in de dagelijkse run. Geen LLM.
- **Dagteller** `kassarapport_autotype` (reconciliatiemail + Instellingen › Boeken): gedaan per document (intake/upload) + de run-rij;
  overgeslagen per reden (`autotype_correcties` / `autotype_status` / `autotype_fout`).
- **Nazorg-CLI** `kassarapport-autotype-nazorg [--administratie] [--dry-run]` — dry-run = 0 writes, idempotent; NIET in de
  nameting-allowlist (schrijvend commando: eenmalig via `gcloud run jobs execute` ná deploy).

**Tests.** `tests/omzet/test_autotype.py` (12): herkenning; upload → kassarapport + tijdlijn/audit + chip-bron; gewone factuur
ongemoeid; mens-keuze nooit overruled; ná 2 correcties melden bij upload/intake mét leesbare reden + venster 180 d; dagelijkse run zet
treffer om en laat omzetrekeningen-signaal als melding, idempotent; overgeslagen `correcties` mét tekst; status-weigering =
`status`; nazorg-CLI dry-run 0 writes/echte run/idempotent/onbekende administratie 2; route 422/200/409/403 + drempel; dagteller.
Gouden set `tests/keten/test_ad2_autotype_inkoopfactuur_wordt_kassarapport.py` (2): ProfX-upload als inkoopfactuur → kassarapport
zonder AI; tegenproef: géén inkoop-casus van de gouden set geeft een parser-treffer. `test_inkoopstroom_werkvoorraad.py` +
`test_profx.py` simuleren de pre-19-09-stand (soort via admin-engine teruggezet). Vitest `OmzetReviewScreen.test.tsx` (+2: chip +
modal + navigatie naar `doel_pad`; zonder typering geen chip). `tsc -b` schoon; ruff op de eigen bestanden schoon. Volledige suite
+ overflow-sweep: zie de regel "Suite/sweep" onderaan.

## Deel B — sweep signalering zonder handeling (lees-only, leesreplica 19-09 ~10:45, laatste afgeronde run 19-09 04:30 UTC)

Methode: `scripts/gcp/db_lezen.sh` per administratie (RLS op `reconciliatie_bevinding` heeft geen Beheerder-clausule: zonder
`--administratie` zie je alleen de administratie-loze rijen — de 174 fouten + 2 automatiserings-LET-OPs), gegroepeerd op blok ×
soort × afwijkingssoort × stand; "sinds" = eerste afgeronde run mét die vingerafdruk. Platformbrede rijen (administratie NULL) telden
81× mee en zijn teruggerekend. Facet-totalen sluiten op het scherm van Peter: aandacht 339–340 (74 afwijkingen + 91 LET-OP + 174
fouten), **in meting 492**, **fouten 174**, geaccepteerd 10.

| Soort (blok) | Open | Sinds | Actie op de rij | Deterministisch én altijd dezelfde? | Voorstel |
|---|---|---|---|---|---|
| `ic_spiegel_rood` (intercompany, FOUT) | **174** (KF → Veldhoven Recreatie 94, Oirschot Recreatie 34, Molenhof Verhuur 28, Molenhof Beheer 11, Mantelzorgwoningen MN 7) | 18-09 (eerste run van het blok) | geen — tekst "Systeemfout — doorbelastingspaar niet sluitend … verkoop=‹UUIDv5› spiegel=‹UUIDv5› nummer=247133xx: verkoopfactuur niet gevonden bij de bron-administratie" | n.v.t. | **systeemfout — opdracht** `opdrachten/inbox/2026-09-19-ic-spiegel-rood-174-doorbelastingsparen-verkoop-niet-gevonden.md`: het blok zoekt de verkoopfactuur op het module-GUID bij Kempen Facilities en vindt 'm niet, terwijl de doorbelasting-aansluiting (blok `doorbelasting_aansluiting`) 0 bevindingen geeft → waarschijnlijk zoekt de IC-toets op het verkeerde GUID/boek_cyclus of de verkeerde administratie; tot de fix zijn dit 174 rode rijen waar niemand iets mee kan |
| `ic_ontbreekt_bij_ontvanger` (intercompany, meten) | 205 (3 administraties) | 18-09 | "Boek de inkoop bij de ontvanger" | nee (mens beoordeelt of de factuur echt ontbreekt of nog onderweg is) | melding blijft; promotie naar `actie` pas ná een meting per paar (nu 205 op dag één = boven de explosie-rem) |
| `dubbele_betaling_vermoed` (bank, meten) | 194 (18 administraties) | 18-09 | "Beoordeel de betaling" | nee | melding blijft (herdefinitie 17-09, meting loopt); promotie per administratie ná nameting |
| `rc_sluit_niet` (rekening_courant, meten) | 91 (38 administraties) | 18-09 | "Zoek de ontbrekende mutatie" | nee | melding blijft; eerst meten of Δ ≤ afrondingsgrens vaker voorkomt (auto-accepteren ≤ € 0,05 zoals bij documenten = kandidaat, nu geen bewijs) |
| `rc_zonder_tegenrekening` (rekening_courant, LET-OP) | 84 (40 administraties) | 18-09 | "Koppel de tegenrekening" (Beheerder-blok) | ja voor het KOPPELEN? nee — de afleiding uit balansrekeningnamen is al automatisch; wat overblijft is precies wat niet afgeleid kon worden | melding blijft, maar bundelen tot één LET-OP per administratie ("N RC-rekeningen zonder tegenrekening") i.p.v. per rekening — schermwinst, geen automatisering |
| `dubbel_in_rlz` (rlz_dubbel) | 41 (20 administraties) | 10-09 | "Controleer in RLZ; accepteer met reden" | nee (nooit verwijderen in RLZ) | melding blijft (advies-blok, schrapbaar) |
| `bedrag_wijkt_af` (documenten) | 10 open + 8 geaccepteerd (4 administraties) | 06-09 | "Accepteer met reden / corrigeer in RLZ" | deels: ≤ € 0,05 is sinds 15-09 al automatisch geaccepteerd; de 10 open zijn > € 0,05 | melding blijft |
| `omzet_in_inkoopstroom` (omzet) | 8 (Van Boxtel) | 17-09 | "Herboeken als omzet…" (storno 19 achter de aangiftepoort) | nee (geldpoort + aangiftepoort, Beheerder-bevestiging) | melding blijft — bewust mens op de knop op geld |
| `kassarapport_in_werkvoorraad` (omzet) | 5 (Van Boxtel: 4 × `profx_journaal`, 1 × `omzetrekeningen`) | 17-09 | "Type wijzigen → kassarapport" | **ja** voor de parser-treffer (4); nee voor het zachte signaal (1) | **geautomatiseerd (deel A)** — 4 verdwijnen bij de eerste échte run ná deploy (of via de nazorg-CLI), 1 blijft mét knop |
| `ic_ontbreekt_bij_verkoper` (intercompany) | 6 (KF 5, AK Nijenhuis 1) | 18-09 | "Boek de verkoop bij de verkoper" | nee | melding blijft |
| intercompany LET-OP `ic_tegenrelatie_onbekend`-achtig | 6 (3 administraties) | 18-09 | "Bevestig de IC-relatie" (Beheerder-blok) | nee (naam-only-relaties vragen bevestiging, regel 16-09) | melding blijft |
| `boekstuknummer_wijkt_af` (documenten) | 2 (AK Nijenhuis) | 09-09 | "Controleer het boekstuk" | nee | melding blijft |
| `project_nummer_dubbel` (projecten, meten) | 2 (Universal) | 19-09 | "Kies welk project blijft" | nee (samenvoegen = mens-werk) | melding blijft; vervolg-opdracht "Afgesloten NNNNN" staat al in de inbox |
| `ic_bedrag_verschilt` (intercompany) | 2 (Veldhoven) | 18-09 | "Vergelijk de bedragen" | nee | melding blijft |
| doorbelasting LET-OP | 1 | 06-09 | deeplink | nee | melding blijft |
| automatisering LET-OP `extractie_wachtrij` | 1 (platformbreed) | 19-09 | "180 overgeslagen wegens ontbrekende harde voorwaarde [vangnet_scheduler]" | — | **systeemfout-signaal**: 180 uploads (BLOW-bulk 18-09) liepen via het 10-minuten-vangnet i.p.v. de directe job-trigger → in de opdracht hierboven als tweede punt (trigger-fout in Cloud Logging nalopen) |
| automatisering LET-OP `werkvoorraad_tellers` | 1 (BLOW, cache 151 ↔ telling 152) | 19-09 | "nachtelijke herberekening trekt gelijk" | — | melding blijft; terugkomend = mutatiepad zonder cache-hook (bulk-upload 18-09 is de verdachte) — meenemen in dezelfde opdracht |

Niet in de tabel omdat ze vandaag 0 zijn: `ontbreekt_in_rlz/odoo`, `status_*`, `half_geboekt`, `wordt_geboekt_verouderd`,
`tussenrekening_open`, `verkoop_categorie_afwijkt`, alle `da_*`, bank `document_ontbreekt_in_rlz`/`mutatie_ontbreekt_in_rlz`/
`*_teruggedraaid_in_rlz`, `project_naam_afgesloten_status_actief` (8 op 19-09 in de lees-only meting, niet in de run van 04:30 —
die draaide vóór deploy `1c7ae8c`).

**Conclusie sweep:** geen tweede kandidaat voor het patroon "vaststaande actie = systeem doet het" naast de kassarapport-typering.
De agenda voor de volgende run is (1) de 174 `ic_spiegel_rood` als systeemfout oplossen, (2) de extractie-wachtrij-trigger die bij
de bulk-upload 180× op het vangnet viel, (3) RC-LET-OPs bundelen per administratie.

## Nazorg + meetrecept ná deploy (vervolg-opdracht `opdrachten/inbox/2026-09-19-nameting-kassarapport-autotype-na-deploy.md`)

1. Deploy-check service én jobs (`gh run view`, `gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'`).
2. Nazorg op de job-image, Van Boxtel eerst: `gcloud run jobs execute rlz-reconciliatie --args="-m,app.cli,kassarapport-autotype-nazorg,--dry-run,--administratie,Van Boxtel"` →
   verwacht "1 administratie(s), 4 kandidaat/kandidaten, zou omzetten 4, overgeslagen —"; daarna zonder `--dry-run` (of wachten op de
   run van 06:30 die hetzelfde doet); daarna kantoorbreed `--dry-run` = 0 kandidaten.
3. Leesreplica: `document` van Van Boxtel Journaal 1-9/2-9/3-9 → soort `kassarapport`, tijdlijn "type automatisch gewijzigd"; audit
   `soort_automatisch_gewijzigd` 4×, `kassarapport_autotype_run` 1× (verwacht 4 / gedaan 4).
4. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen omzet --lees-only` → Van Boxtel: 1 × `kassarapport_in_werkvoorraad`
   (signaal omzetrekeningen), 0 × profx; Inzicht › Reconciliatie: 340 → 336 aandacht.
5. Rapportregel "werkt in productie: ja/nee" + BESLISSINGEN-status.

## Suite/sweep
Volledige backend-suite: **6791 passed, 0 failed, 21 deselected (1:09 u, eigen test-DB, eindstand werkboom)**; overflow-sweep
**groen, 232 metingen** — één poort voor het Afsluiten?-werk en dit werk samen (`docs/rapporten/2026-09-19-inbox-afgewerkt.md`).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/omzet.md` (232 regels bij het lezen; 266 ná deze run),
`docs/regels/intake-extractie.md` (270), `docs/regels/reconciliatie.md` (94; 107 ná deze run),
`docs/regels/werkvoorraad-controlescherm.md` (297), `docs/regels/werkloop-productie.md` (76).
