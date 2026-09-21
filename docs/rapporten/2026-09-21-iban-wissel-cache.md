# IBAN-wissel bleef "Blokkerend" ná het vier-ogen-akkoord — checks-cache-invalidatie op de bron (21-09)

Opdracht `opdrachten/gedaan/2026-09-21-BUG-iban-wissel-blijft-blokkerend-na-vier-ogen-akkoord-checks-cache.md` (screenshot Peter 21-09
~09:30, Beleggingsmaatschappij Meyer B.V., Belastingdienst voorlopige aanslag Vpb 2025 0015.21.664.V.51.0112, € 34, IBAN
NL04RABO0200112244). Gebouwd + getest; geen migratie, geen RLZ-write, geen AI. **Werkt in productie: niet gemeten** — de code deployt ná
deze run; nazorg-CLI + meetrecept onderaan. Peter keek niet mee; keuzes staan in "Keuzes" hieronder.

**Één regel voor Peter:** de check "IBAN-wissel" en het aanbieden-paneel lazen uit twee bronnen — een 15 minuten oud gecacht rapport
versus de live vertrouwde set. Het akkoord maakt die cache nu direct ongeldig (ook voor de knop "Boeken in RLZ"), de vingerafdruk van de
cache draagt de vertrouwde set zelf als tweede slot, en het scherm heeft een "Opnieuw controleren"-knop zodat niemand op de klok wacht.
Ná de deploy: één keer `checks-cache-legen --alles` op de job-image en het Meyer-document herladen.

## Feit en oorzaak

- **Scherm:** "IBAN-wissel" = **Blokkerend** "wijkt af van de vertrouwde rekening(en) … · gecontroleerd 09:15 (ongewijzigd)"; het
  aanbieden eronder gaf LIVE de 409 "Dit IBAN staat al in de vertrouwde set van deze crediteur". "Ter accordering →" bleef de enige knop.
- **Code (gelezen):** `checks_extern.vingerafdruk` hashte crediteur/cluster, referentie, datum, bedrag, factuur-IBAN, boek_cyclus en
  backend — de vertrouwde IBAN-set niet. Het gecachte `ExternRapport` droeg `vertrouwde_ibans` van 09:15 en was 15 min geldig
  (`checks_extern_cache_minuten`). `iban_accordering.accordeer` voegde het IBAN inline toe en herstelde de status; de docstring zei "de
  harde checks draaien bij de boekactie sowieso opnieuw" — waar vóór 0165, sinds 18-09 hergebruikt óók `boeken` (modus AUTO) het
  rapport. Zelfde gat voor `bevestig_iban`, seed/baseline (`_voeg_toe`) en crediteur-samenvoegen (`verhuis_ibans`).

## Gebouwd

1. **Invalidatie op de bron** — `checks_extern.maak_ongeldig_voor_vendor(session, administratie_id, vendor_id)`: markeert de
   `check_extern_cache`-rijen van álle documenten van de crediteur + identiteitscluster (`duplicaat_module.identiteit_vendor_ids`)
   ongeldig met prefix `ongeldig:` op de vingerafdruk (de tabel heeft bewust geen DELETE-grant, 0165; het rapport blijft leesbaar
   voor diagnose, de volgende verse run overschrijft de rij). Aangeroepen in DEZELFDE sessie/transactie als de mutatie:
   `iban_accordering.accordeer` (audit `leverancier_iban_toegevoegd` draagt `checks_cache_ongeldig` = aantal),
   `leverancier_iban._voeg_toe` (dekt `bevestig_iban`, `seed_uit_rlz`, `leg_baseline_vast`) en `crediteuren/service.verhuis_ibans`
   (voorkeur én bron). De wachtrij-claim leest de cache ná commit en ziet de oude stand nooit meer. Idempotent (al-ongeldige rijen
   tellen niet opnieuw).
2. **Tweede slot in de vingerafdruk** — `vingerafdruk(…, vertrouwde_ibans=)` neemt de gesorteerde, genormaliseerde set op (lokale
   query, geen RLZ-call). `voer_checks_uit` leest de live set vóór de vingerafdruk; de cache-rij wordt geschreven met de vingerafdruk
   van de stand NÁ de verse run (`_vingerafdruk_na_run`), zodat een seed/baseline die de set net vulde niet één extra externe run kost.
3. **Boeken-pad = live toets** — `check_iban_wissel` krijgt in `voer_checks_uit` `live ∪ seed-uitkomst`; alleen de RLZ-seed en de
   duplicaatquery's komen uit de cache. `boeken.py` is ongewijzigd (modus AUTO blijft; de live set maakt de retry-/autoboek-uitzondering
   voor de IBAN-check overbodig). Regel aangescherpt in `autoboeken-ai.md`: "extern gecachet = RLZ-roundtrips; álle lokale toetsen
   draaien vers".
4. **Scherm — één bron** — `IbanAanbiedenVorm.onAlVertrouwd`: een 409 waarvan de tekst "al in de vertrouwde set" bevat (contract met
   `bied_aan`, getoetst in de backend-test) toont "intussen vertrouwd — de controles worden opnieuw uitgevoerd" en roept `checksVers`
   aan (`POST …/boekvoorstel/checks?extern=vers`); de rij wordt groen en het paneel verdwijnt. Nieuwe regel onder de controles-tabel:
   "Reeleezee/Odoo geraadpleegd om HH:MM (ongewijzigd sinds de vorige controle)" + `linkbtn` **"Opnieuw controleren"** (disabled
   + "wordt geraadpleegd…" tijdens de run; `externLoopt` telt `versBezig` mee zodat de externe rijen "Loopt…" tonen).
5. **Nazorg-CLI** `checks-cache-legen --administratie <UUID|NAAMDEEL> | --alles [--dry-run]` — telt/markeert per administratie in
   `scoped_session`, één regel per administratie mét rijen + totaalregel; exit 2 zonder `--administratie`/`--alles`.

## Tests

- `tests/unit/test_leverancier_iban_invalidatie_guard.py` (3): élke module die `LeverancierIban(` construeert roept
  `maak_ongeldig_voor_vendor(` aan; de set bekende schrijvers is expliciet (leverancier_iban, iban_accordering, crediteuren/service);
  set-hash aanwezig in `vingerafdruk` en doorgegeven in `voer_checks_uit`.
- `tests/documenten/test_checks_cache_invalidatie.py` (9): vingerafdruk mét set (volgorde/normalisatie); akkoord → cache ongeldig →
  volgende run OK (niet uit cache) → daarna weer gecachet; `bevestig_iban` idem; oude geldige rij teruggezet (gesimuleerd vergeten
  pad) → set-hash wint; alleen documenten van die crediteur + idempotent; 409-tekstcontract; **boeken direct ná bevestiging slaagt
  binnen de 15 min** (vóór: `BoekenGeblokkeerdDoorChecks`, ná: 1 PUT); CLI dry-run / echt / tweede run 0 / exit 2.
- **Gouden-set-casus af** `tests/keten/test_af_iban_akkoord_checks_cache.py` (2, poging 2): de échte BDO-UBL (casus h, IBAN
  NL95KETN1000000010) op een crediteur mét een ándere vertrouwde baseline → via de controlescherm-route (`POST …/checks`) eerst
  Blokkerend en vers, tweede keer uit de cache en nog steeds Blokkerend; vier-ogen-akkoord (aanbieden + accordeur) → cache-rij
  gemarkeerd `ongeldig:`, eerstvolgende controle vers en OK, opnieuw aanbieden = `IbanAlVertrouwd` (de 409-tekst), daarna weer
  gecachet; en boeken vóór het akkoord = `BoekenGeblokkeerdDoorChecks`, direct ná het akkoord één PUT + GEBOEKT.
- vitest `BoekvoorstelPanel.ibanCache.test.tsx` (2): 409 → `extern=vers` → IBAN-wissel OK + aanbieden-paneel weg; linkbtn
  "Opnieuw controleren" → `extern=vers` → OK zonder "ongewijzigd".
- Groen: `test_checks_cache_invalidatie` + guard + `test_checks_extern` + `test_iban_wissel` + `test_iban_accordering` = 57 passed;
  `tests/crediteuren` + `test_duplicaat_module` + docs-guards = 65 passed; frontend 9 passed, `tsc -b` exit 0. Bredere run
  (`tests/documenten tests/unit tests/crediteuren tests/keten`): zie de slotregel hieronder.

## Keuzes (Peter keek niet mee)

- **Markeren i.p.v. verwijderen:** de cache-tabel heeft bewust geen DELETE-grant (0165); een prefix op de vingerafdruk is dezelfde
  semantiek ("matcht nooit meer") zonder grant-wijziging of migratie, en houdt het oude rapport leesbaar.
- **Cluster-breed invalideren:** de RLZ-duplicaatquery loopt over het identiteitscluster, dus de invalidatie ook — een dubbel
  crediteurrecord mag een akkoord niet verbergen.
- **Vingerafdruk ná de run:** zonder herberekening zou élke nieuwe crediteur (seed/baseline vult de set tijdens de run) precies één
  extra externe run kosten; met herberekening blijft "tweede run = cache" gelden.
- **`boeken.py` niet aangepast:** de eis "IBAN-check toetst bij boeken altijd live" is in `voer_checks_uit` afgedwongen (één plek voor
  scherm én boeken), niet als extra modus in `extern_checks_modus`.
- **Frontend-test op het patroon:** "check blokkerend + paneel 'al vertrouwd' = onmogelijk" is als gedragstest gebouwd (de 409 wordt
  een verse herberekening), niet als statische assertie — het scherm kán de tegenspraak nu niet meer tonen.
- **Vervolg-opdracht in de inbox** `opdrachten/inbox/2026-09-22-nameting-iban-wissel-cache-na-deploy.md` (`niet vóór: 2026-09-22
  09:00`): deploy-check, de schrijvende nazorg `checks-cache-legen --alles` als `gcloud run jobs execute` op de job-image (dry-run →
  echt → dry-run 0), en de metingen hieronder — "niet gemeten" is een schuld mét vervaldatum (les verbeteringen.md 21-09), niet een
  belofte. Kan gcloud in die run niet inloggen, dan is het een klikpunt voor Peter mét de letterlijke commando's.

## Nazorg productie + meetrecept (ná deploy, job-image)

1. Deploy-check service ÉN jobs (`gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'`).
2. `gcloud run jobs execute rlz-reconciliatie --args="-m,app.cli,checks-cache-legen,--alles,--dry-run"` → "N geldig, 0 ongeldig
   gemaakt"; daarna zonder `--dry-run` → "N ongeldig gemaakt"; tweede echte run → 0.
3. Meyer-document 0015.21.664.V.51.0112 herladen → "IBAN-wissel" = OK, "Boeken in RLZ" beschikbaar (vóór stap 2: "Opnieuw
   controleren" klikken werkt ook).
4. Request-log: `POST …/boekvoorstel/checks?extern=vers` ná een klik op "Opnieuw controleren"; audit `leverancier_iban_toegevoegd` mét
   `checks_cache_ongeldig` ≥ 1 bij het eerstvolgende vier-ogen-akkoord.

## Documentatie

BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09"; regels-alinea's 21-09 in `werkvoorraad-controlescherm.md`,
`autoboeken-ai.md`, `duplicaten-crediteuren.md`; CLAUDE.md werkvoorraad rij 7 + autoboeken rij 5 aangevuld; WAT_IS_NIEUW 2026-09-21;
les Platform `registers/verbeteringen.md` 21-09 ("bij élke nieuwe cache eerst de lijst 'welke handelingen maken dit ongeldig'").

## Poort — poging 2 (21-09, inbox-run)

Poging 1 haalde de poort niet (rij j3: de run eindigde terwijl de suite nog liep; 19 bestanden ongecommit). Het werk stond als WIP-commit
`5fb3eaf` op branch `wip/2026-09-21-BUG-iban-wissel-blijft-blokkerend-na-vier-ogen-akkoord-checks-cache` — die branch blijft ter controle
staan. Poging 2 begon met `git merge --squash` van die branch (drie beide-kanten-toegevoegd-conflicten in BESLISSINGEN, rapporten/INDEX en
WAT_IS_NIEUW náást de groepssaldi-fix van dezelfde ochtend: beide zijden behouden), inhoudelijk niets aan de fix veranderd, de Platform-les
stond al gecommit (`verbeteringen.md` 21-09). Volledige poort: pytest volledig 6872 passed / 1 failed (45 min) — de ene rode was `test_keten_guard` ("wijziging in de keten zonder aanraking van tests/keten"), precies de poort waar poging 1 op strandde; opgelost met gouden-set-casus **af** (hieronder), daarna `tests/keten` + guard 166 passed; vitest 1864 passed (242 bestanden); `tsc -b` exit 0;
gouden set `keten_sweep.sh` 11/11 groen, 0 nieuwe baselines (eerste run: `c_spot_services__detail` 14,7 % afwijkend door een render-timing van de Chrome-PDF-viewer — de pagina links werd wél gerenderd, rechterkant pixelgelijk; herdraai van die casus 0,000 %). Pas daarna gecommit op main.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/werkvoorraad-controlescherm.md` (297 regels bij het lezen; 319 ná poging 2),
`docs/regels/autoboeken-ai.md` (122; 134 ná deze run), `docs/regels/duplicaten-crediteuren.md` (119; 129 ná deze run).
