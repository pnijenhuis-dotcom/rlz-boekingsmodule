# Feedbackrun A — factuurverwerking (gebruikersfeedback Universal 25-09): negen blokken — GEBOUWD

**Opdracht:** `opdrachten/gedaan/2026-09-25-feedbackrun-A-factuurverwerking-universal-bugs-en-scherm.md` (bron:
`docs/feedback/2026-09-25-verbeteringen-factuurverwerking-universal.md`, items FV-xx; besluit Peter 25-09 "deze punten mogen mits ze
binnen onze lijn en beslissingen vallen en echt verbeteringen zijn" — de vorm van de opdracht is bindend, niet de feedbacktekst).
Handmatige CC-sessie (Peter start), coördinator + negen parallelle bouwagenten (fork, elk in een eigen git-worktree mét eigen test-DB;
squash-merge per blok = één commit per blok; hot files door de coördinator). Geen migratie in enig blok. Niets in productie gewijzigd;
élke productielezing lees-only (job-image `db-lezen`, Cloud Logging, `rlz-lezen`).
**Bronnen gelezen:** LEESPLICHT (sectie "Gelezen regels"), `docs/gesprekken/2026-09-25.md`, mockups `controlescherm-v2.html` +
`projecten-invoer.html`, `Platform/WERKWIJZE.md` v1.16.

## Uitkomst in één alinea
Alle negen blokken zijn gebouwd, per blok gecommit, en groen op de gouden set (tests/keten + keten-guard + alle nieuwe bloktests: **342
passed, 1 skipped** op de samengevoegde main; pixel-sweep 13/13, baselines bewust ververst voor de gewilde schermwijzigingen). Twee bugs
bleken anders dan gemeld: FV-01 (de XML wás gelezen — het bijlage-paneel toonde de ruwe XML omdat de PDF-tweeling ontbrak) en FV-18 (een
tabwissel start géén server-request — de vastloop-ervaring kwam van een `/auth/administraties`-fetch per wissel én een 3-s-poll die
herstartte, stapelde en de hele lijst her-tekende). FV-16 is als ORANJE check zonder blokkade gebouwd, FV-02 als bronvolgorde mét het
geheugen als zichtbare laatste bron, FV-21 als oranje naam-cluster dat nooit automatisch samenvoegt. FV-17 is niet gebouwd (besluit 21-09
blijft); FV-03/FV-04 wachten op run B. **Werkt in productie: niet gemeten** voor álle negen blokken — negen dispatch-onderdelen in
`nameting.yml` + vervolg-opdracht `niet vóór: 2026-09-26 09:00`.

## Commits (één per blok, op `da72dfe`)
| blok | commit | onderwerp |
|---|---|---|
| 6 | `4f1cdd1` | FV-09 btw herrekent óók bij nettowijziging |
| 5 | `b7cc315` | FV-14/15 crediteur-zijpaneel + bewerken |
| 2 | `d478389` | FV-21 crediteur-naamclusters oranje |
| 3 | `85427f1` | FV-02 project-bronvolgorde |
| 8 | `aa448d1` | FV-20 "Open (N)" + "Alles (N)" + zoeken over alles |
| 4 | `7124ecd` | FV-16 factuurdatum in ingediende aangifte = oranje |
| 9 | `c32b487` | comfort FV-05/07/08/10/11/12/13 |
| 7 | `41539f4` | FV-18 tabwissel gemeten + gefixt |
| 1 | `930443d` | FV-01 UBL zonder beeld = kaart, onleesbare XML = handmatig afmaken |
| docs | (deze commit) | rapport, BESLISSINGEN, regels, CLAUDE.md, WAT_IS_NIEUW, feedback-status, nameting-onderdelen |

## Procesnotitie — tegoedlimiet en stalls
Alle negen agenten strandden twee keer (429 "out of usage credits" direct ná de start en opnieuw ná ~40 min) en zes keer op een
stream-stall van 600 s; élke keer hervat met SendMessage ("lees je rapport + git status, niets dubbel"). Worktree-isolatie maakte dat
verliesloos: het werk stond ongecommit in de worktree, de deliverables in de scratchpad. Squash-merge per blok gaf vier conflicten
(`overflow_sweep.sh` harnaslijst B5/B8, `BoekvoorstelPanel.tsx` import B5/B9, `DocumentenDeelscherm.tsx` + harnas B7/B8, `ubl.py` +
keten-export B1/B3 — beide lazen `cbc:Note`), alle vier handmatig samengevoegd en daarna getoetst. Eén latente botsing die geen
conflict gaf: B9's kop-combobox "Btw-code voor alle regels" matchte de `getAllByLabelText('Btw-code')`-query van 21 bestaande tests →
label hernoemd naar "Alle regels — btw/project".

## Blok 1 — FV-01 · RLZ-UBL "als ruwe code getoond" (commit `930443d`)
**Vaststelling (lees-only, vóór de fix).** Intake-job-log 02-09 16:05 UTC, bericht `c4743e14` (27 bijlagen): `…RLZ-2080142898 - 2026-07-20.xml
= verzamelbak` en `….pdf = splitsingsvoorstel` — UBL en PDF zijn níét gebundeld. `db-lezen documenten-open` (job-executie
`rlz-reconciliatie-n5b4g`): document `250895e8-c341-4e28-96fc-1e4949b973d8`, Universal Steigerbouw, te_controleren, XML-hoofdbestand,
`bron_bestandsnaam` leeg, referentie RLZ-2080142898, totaal 938,06, veldvoorstel totaal_excl 775,26, 1 opgeslagen regel → de UBL wás
deterministisch gelezen. Oorzaak van "ruwe code": `DocumentDetailScreen` rendert voor een XML zonder PDF-beeld `<pre class="xml-bron">`
(beeld.py stap 3 = hoofdbestand; de RLZ-export draagt géén ingesloten PDF). De reconciliatie meldt dagelijks `ic_ontbreekt_bij_ontvanger`
voor 2080142898 — consistent met "nog niet geboekt".
**Gebouwd.** Route `GET …/documenten/{id}/ubl-samenvatting` + `UblSamenvattingKaart` (XML-bron alleen achter "XML-bron tonen"); élke
XML die geen (volledige) UBL is → `handmatig_afmaken` mét leesbare reden (gzip/zip/PDF-met-xml-naam/leeg, kapotte XML, vreemd
root-element op lokale naam, UBL zonder nummer/totaal/regels) + chip "XML niet leesbaar: ‹reden›" in scherm en tijdlijn; `cbc:Note`
"Werk: …" → kop-`project_tekst` (RLZ-export 26084 = groen; samengevoegd mét blok 3); lees-only CLI `xml-documenten-rapport`.
**Tests.** `test_ubl_rlz_export` + `test_xml_niet_leesbaar` (CLI in élke meetrecept-vorm) + gouden-set-casus a2 + harnas-casus
`a_ubl_zonder_beeld` (nieuwe baseline), vitest 70. **Keten-baseline verversen: ja** (a_universal_nederland detail: project uit de Note).
**Werkt in productie: niet gemeten.** Meetrecept = onderdeel `xml-documenten`: `xml-documenten-rapport --alles --detail` (TOTAAL-regel),
`db-lezen documenten-open --administratie "Universal Steigerbouw" --param bestandsnaam=2080142898`, request-log `/ubl-samenvatting` ≥ 1 × 200.
**Klikpunt Peter:** document `250895e8` (RLZ-2080142898, € 938,06, 2026-07-20; bron `db-lezen documenten-open` executie n5b4g) ná deploy
openen → kaart i.p.v. XML; PDF-tweeling koppelen via de bestaande `verzamelbak-nabundelen --ook-toegewezen` (niet in deze run gedraaid).

## Blok 2 — FV-21 · Crediteurnamen in meerdere schrijfwijzen (commit `d478389`)
**Vaststelling.** De naam-sleutel was al hoofdletterongevoelig; het gat zat in `afhandeling.classificeer`: een naam-only cluster gold als
EENDUIDIG (nachtelijke auto-afhandeling bij ≤ 3 boekingen, anders stille twijfel zonder chip). Productie (`rlz-lezen Vendors`, namen
geanonimiseerd tot initialen): twee Floor-Bouwliften-records + één Universal-Nederland-record actief.
**Gebouwd.** `crediteuren/naam.py` (één normalisatie: casefold, diakrieten, rechtsvorm weg, "Holding" blijft onderscheidend, leestekens/
spaties weg) voor de dubbelen-motor én de extractie-match; alleen-naam = NOOIT eenduidig (`auto_afhandelen` slaat 'm over — nooit
automatisch samenvoegen op naam), chip "gelijkende naam — bevestig" (oranje), KvK-conflict = afmelden primair; ná bevestiging bestaande
voorkeur-mechaniek; lees-only CLI `crediteuren-naamclusters`. **Tests** 274 targeted + 20 nieuw + keten-b `TestSchrijfwijzeFloor`,
vitest 11. Baseline: nee. **Werkt in productie: niet gemeten** (onderdeel `crediteuren-naamclusters`; verwacht bij Universal
Steigerbouw ≥ 1 open Floor-cluster; bevestigen = mens in Inzicht › Crediteuren).

## Blok 3 — FV-02 · Project: bronvolgorde i.p.v. "laatste project van de leverancier" (commit `85427f1`)
**Vaststelling.** Het geheugen vulde het project stil zodra het `proj`-veld leeg was; een nummer in de regeltekst of in de RLZ-export-
`cbc:Note` telde niet; het autoboek-pad overschreef het regel-project altijd met de geheugen-waarde.
**Gebouwd.** `match.ProjectcodeFormaat` (nummerlengtes + jaarvoorvoegsels uit de projectcache — nooit hardcoded Universal), stap 2
klant-loze cachecode in proj-tekst/regelomschrijving/UBL-Note, geheugen als LAATSTE bron mét chip "voorstel uit historie", conflict
factuur ≠ geheugen = niets + chip "factuur noemt een ander project — kies zelf", afgesloten alleen bij exacte verwijzing, autoboek
weigert bij conflict; query `project-prefill-herkomst`. **Tests** 10 nieuw + gouden set 182 (+2 casus i) + vitest 20. Baseline: ja (a).
**Werkt in productie: niet gemeten** (onderdeel `project-bronvolgorde`: 0 regels mét herkomst leverancier_geheugen zonder project_bron).
Beslispunt: een exacte code op de factuur wijst nu óók een inactief/afgesloten project aan (opdrachtregel); RLZ-weigering blijft zoals
de bestaande chip "inactief".

## Blok 4 — FV-16 · Factuurdatum in een ingediende btw-periode = ORANJE, geen blokkade (commit `7124ecd`)
**Gebouwd.** Check-rij "Factuurdatum valt in een ingediende aangifteperiode" via `app/rlz/aangifte.py` op de factuurdatum (= BookDate)
in het EXTERNE deel (parallel, gecachet; `server_timing` stap `checks.aangifte`), oranje mét "RLZ verschuift de btw naar het
eerstvolgende open tijdvak" + handeling "Boeken (btw in volgend tijdvak)" (`POST …/boekvoorstel/aangifte-periode-bevestigen` →
tijdlijn-notitie + audit); boeken zonder keuze mag mét tijdlijnregel; autoboek weigert op deze rij; doorbelasting: `GET …/aangifte-letop`
→ LET-OP-banner als één kant ingediend is. Odoo = n.v.t., RLZ-fout = oranje niet toetsbaar. **Tests** 726 + 228 targeted, gouden-set-
casus ao, vitest 114. Baseline: ja (extra groene check-rij in élke detail-casus). **Werkt in productie: niet gemeten** (onderdeel
`aangifteperiode`). Beslispunten: alleen déze oranje rij weigert het autoboek-pad in code (de andere oranje signalen niet — bestond al
zo); cache-rijen van vóór de deploy tonen tot de eerste verse run "niet getoetst".

## Blok 5 — FV-14 + FV-15 · Crediteur aanmaken als zijpaneel + bewerken (commit `b7cc315`)
**Gebouwd.** `ui/basis/Zijpaneel` (niet-modaal, geen overlay, factuur blijft leesbaar/scrollbaar), `CrediteurPaneel` modus nieuw/bewerken
(naam/KvK/btw/IBAN/adres uit UBL, chips per veld, geen IBAN = waarschuwing), `put_vendor(FullAddress, City)` fail-open (4xx → PUT zonder
adres + waarschuwing), `GET/PUT …/crediteuren/{vendor_id}` (kenmerk 'handmatig', audit `crediteur_gewijzigd`, IBAN op de PUT = 422 — IBAN
alleen via de vier-ogen-route, lees-only in het paneel mét link), Odoo bewerken = 409 niet ondersteund; query `crediteur-mutaties`;
harnas `?crediteurpaneel=1`. **Tests** 92 + rol-gate-sweep, vitest 463, overflow-sweep 8/8. Baseline: nee. **Werkt in productie: niet
gemeten** (onderdeel `crediteur-paneel`). Beslispunt: RLZ-schrijfbaarheid van `FullAddress`/`City` niet live bewezen (fail-open dekt het;
bewijs = eerste echte mutatie ná deploy via `rlz-lezen Vendors`).

## Blok 6 — FV-09 · Btw-bedrag herrekenen bij wijziging van het netto (commit `4f1cdd1`)
**Vaststelling (vitest op de ongewijzigde code).** Tarief wijzigen herrekende (18-09); netto wijzigen NIET op een geladen regel mét btw,
niet in de samengevoegde modus en niet ná een mens-btw — `btwHandmatig = Boolean(btw_bedrag)` bij het laden maakte élke geladen regel
"van de mens". **Gebouwd.** `btwHandmatig` = alleen zelf getypt in de sessie; netto-tak herrekent cent-exact via `regelsom.ts::
btwUitTarief`; mens-btw wint tot het netto wijzigt → chip "btw herrekend (netto gewijzigd)" + tijdlijnregel mét `aanleiding: netto`;
tarief onbekend = chip; check + marge 18-09 ongewijzigd; query `btw-herrekend`. **Tests** 40 backend + vitest 414. Baseline: nee.
**Werkt in productie: niet gemeten** (onderdeel `btw-netto`). Beslispunt: mens-btw is een sessie-begrip (geen persistente per-regel-override).

## Blok 7 — FV-18 · Scherm loopt vast bij wisselen tabblad — eerst gereproduceerd (commit `41539f4`)
**Reproductie mét meting (vóór de fix).** Meetinstrument: harnas `?docs=N&tabwissel=K&latency=ms&poll=1&strict=0` + CDP-driver mét
échte klok (`--virtual-time-budget` meet 0 ms tijdens lange taken). 20 wissels: 400 rijen max 298 / gem 85 ms, 2000 rijen max 638 /
gem 429 ms, **0 lijst-requests per wissel** (een tabwissel is client-side — "polling per tabwissel" en "checks-cache per rij" zijn geen
oorzaak). Wél: mét klant-accordering aan 36 × `GET /auth/administraties` in 20 wissels (bulk-balk mount per wissel; productie tot
14/min per client), en een poll-storm: het 3-s-effect hing aan `documenten` → herstart ná élk antwoord, stapeling bij een trage server,
volledige re-render per antwoord (95–333 ms). Productie-request-log 24-09 12:04–12:14 (Universal Steigerbouw): tien lijst-requests op rij,
4,1–5,7 s uiteen = 3 s + latency 1,1–2,6 s; lijstroute p50 1,56 s / p95 2,51 s (n = 59), 219 open documenten.
**Fix.** Bulk-balk krijgt de administraties van het ouder; één `AbortController` per lading (laatste lading wint, abort bij wissel/unmount);
poll op een boolean mét vaste 3-s-tik, overslaan zolang een request loopt, geen state-update bij een byte-gelijk antwoord; zij-fetches op
een `AbortController`; sortering op de string-param; tellers in één Map. Ná de fix: fetches per wissel 0 (poll-tik hoogstens 1, nooit
gestapeld), renderkost per wissel ± gelijk (lineair in het aantal rijen). **Tests** `DocumentenDeelscherm.tabwissel.test.tsx` (rood op de
code van vóór 25-09), vitest 318, overflow-sweep 48/48, `tabwissel_meting.sh` groen. Baseline: nee.
**Niet gedaan (beslispunt):** rij-memoïsatie/virtualisatie (renderkost lineair in rijen; ~65 ms bij 130, ~270 ms bij 640 rijen zonder
StrictMode) en de lijstroute-latency van 1,6–2,5 s bij 219 documenten. **Werkt in productie: niet gemeten** (onderdeel `tabwissel`).

## Blok 8 — FV-20 · "Alle" toont niet alles (commit `aa448d1`)
**Vaststelling.** "Alle (N)" = kantoorwerk zonder "Wachten op anderen" (regel werkvoorraad 1, blijft) en het zoekveld filterde client-side
over die geladen lijst → de Exact-factuur op ter_accordering en geboekte documenten waren onvindbaar. **Gebouwd.** Label "Open (N)"
(URL `alle` blijft, `open` synoniem), echte "Alles (N)" = server-side `groep=alles` (kantoor ∪ wachten ∪ afgehandeld, limit 200/max 500,
`totaal`, statuschip per rij, paginabalk), server-side `q` over leverancier/referentie/bestandsnaam/bedrag (ook uit het veldvoorstel),
zoekterm vanaf binnenkomst/Open/Alles → alles; op een expliciet gekozen signaaltab blijft zoeken binnen de tab (duplicaat-bulk).
Bestaande aanroepen byte-gelijk. **Tests** 5 nieuw + keten `TestAllesEnZoeken` + 564 targeted, vitest 198, overflow-sweep 48/48
(variant `?alles=1`). Baseline: lijst-baselines ververst (label). **Werkt in productie: niet gemeten** (onderdeel `lijst-alles`).

## Blok 9 — comfort binnen de UX-norm (commit `c32b487`)
FV-05 bijlageverwijzing van de staart gestript (chip "ingekort", nooit midden in een zin, nooit op handmatig); FV-07 comboboxen "Alle
regels — project/btw" (≥ 2 regels) → per regel doorgezet, tijdlijn "Kop → regels"; FV-08 eigen parser `bedragExpressie.ts` (geen eval,
centen-integers, half-up) bij blur/Enter mét chip "= 20+30"; FV-10/11 geen pagina-overflow op 1440/1385/1280/1170/1024/768, splitter
42/58 mét pointer capture, opgeslagen voorkeur wint; FV-12 knop "Verdelen over projecten" mét `standaard_sleutel` (instelling → meest
gebruikt in geboekte verdelingen 12 mnd → omzet_maand; Universal via de historie, nooit hardcoded) + "Anders…"; FV-13 vastgesteld =
kopveld "Periode (weken)" op het controlescherm (screenshots harnas), chip "1 jul – 31 jul 2026 (wk 27–31)" + terugval letterlijk
"week van de factuurdatum (aanname)". **Tests** kop 47 + periode 68 + kop_doorgezet 3 + projectverdeling 16, gouden set 181, vitest 190.
Baseline: ja (alle detail-casussen door 42/58 + comboboxen + knop + chip). **Werkt in productie: niet gemeten** (onderdeel `comfort-controlescherm`).

## Niet gebouwd (conform "Niet doen")
FV-17 (vervalt — besluit 21-09 "Corrigeren → klaar_om_te_boeken mét gele balk" blijft), FV-03/Bijlage A en FV-04 (run B: wacht op
`crediteuren-historie-schoon.csv` + voorbeeldfacturen Universal Nederland), geen harde periodeblokkade, geen automatische
crediteur-samenvoeging op naam, geen hardcoded Universal-rubrieken, geen geldlogica buiten blok 6.

## Poort
- Gouden set + alle nieuwe bloktests op de samengevoegde main (eigen DB `boekhouding_test_guards2`): **342 passed, 1 skipped** (3:04 min).
- Pixel-sweep `KETEN_UPDATE_BASELINE=1 scripts/keten_sweep.sh`: **13 metingen groen**, baselines ververst (a_ubl_zonder_beeld nieuw;
  detail-casussen a/b/c/h/m gewild gewijzigd: 42/58-split, kop-comboboxen, Verdelen-knop, periode-chip, extra aangifte-check-rij;
  lijst-casussen: label "Open (N)").
- Vitest document+ui 512 passed, werkvoorraad 202 passed ná de merges; `tsc -b` groen bij élke commit (pre-commit).
- Volledige backend-suite: zie de laatste sectie "Volledige suite".
- Geen migratie; `alembic check` n.v.t.

## Meetrecepten / dispatch-onderdelen (nameting.yml, nameting.sh, guard)
Negen nieuwe onderdelen (`xml-documenten`, `crediteuren-naamclusters`, `project-bronvolgorde`, `aangifteperiode`, `crediteur-paneel`,
`btw-netto`, `tabwissel`, `lijst-alles`, `comfort-controlescherm`) mét de vier plekken (if-tak + options + `via_gh_onderdeel` + OORDEEL-else-tak),
allowlist-uitbreiding `xml-documenten-rapport` + `crediteuren-naamclusters` (beide lees-only), guard
`test_nameting_workflow.py::test_feedbackrun_25_09_*`. Élk onderdeel leest de deploy-tijd via `SINDS_FEEDBACKRUN_A` (default
2026-09-25T18:00Z). Vervolg-opdracht `opdrachten/inbox/2026-09-26-nameting-feedbackrun-A-na-deploy.md` (`niet vóór: 2026-09-26 09:00`).

## Klikpunten en beslispunten Peter (samengevat)
1. Blok 1: document `250895e8` openen ná deploy → kaart; PDF-tweeling koppelen via nabundelen.
2. Blok 2: Floor-/Universal-Nederland-clusters bevestigen in Inzicht › Crediteuren (nooit automatisch).
3. Blok 3: exacte code op de factuur wijst ook een afgesloten project aan — akkoord?
4. Blok 4: alleen de aangifte-rij weigert het autoboek-pad; generaliseren naar álle oranje signalen = apart besluit.
5. Blok 5: RLZ-adres-schrijfbaarheid bewijzen (eerste echte aanmaak of bewerking mét adres ná deploy, of een STAP-0 op de gedearchiveerde testadministratie); Odoo-partneradres.
6. Blok 6: persistente mens-btw per regel = aparte opdracht.
7. Blok 7: rij-virtualisatie en lijstroute-latency (1,6–2,5 s bij 219 documenten) = beslispunten.
8. Blok 8: zoeken op een expliciet gekozen signaaltab blijft binnen die tab (duplicaat-bulk) — bewust.

## Gelezen regels
- `docs/regels/werkvoorraad-controlescherm.md` (481 regels vóór deze run; nu 604)
- `docs/regels/intake-extractie.md` (409 regels vóór deze run; nu 430)
- `docs/regels/duplicaten-crediteuren.md` (153 regels vóór deze run; nu 189)
- `docs/regels/btw.md` (302 regels vóór deze run; nu 352)
- `docs/regels/verplichtingen-projecten-voorraad.md` (407 regels vóór deze run; nu 452)
- `docs/regels/kantoor-frontend.md` (144 regels)
- `docs/regels/accordering-native-app.md` (405 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
- `docs/regels/doorbelasting-intercompany.md` (220 regels vóór deze run; nu 232 — blok 4 raakt de preview)

## Volledige suite
Volledige backend-suite op de samengevoegde main (boekhouding_test, 1:41 h door CPU-contentie mét een worktree-run): **7636 passed,
6 failed, 1 skipped, 21 deselected**. De zes rood, alle in dezelfde run gedicht of verklaard:
- `test_router::test_document_detail_bevat_tijdlijn_en_veldvoorstel` — regressie blok 1 (een minimale UBL zonder regels/datum is
  sinds 25-09 "onvolledig" = handmatig_afmaken): verwachting bijgewerkt.
- `test_boekvoorstel::TestVoerChecksUit::test_geen_credentials_…` — regressie blok 4 (nieuwe check-rij in de storings-tak, exact-set):
  verwachting + tuple bijgewerkt (rij oranje "niet getoetst", nooit blokkerend).
- `test_template_terugval::TestHerkenCrediteur::test_kvk_dan_iban_dan_naam` — ÉCHTE regressie blok 2: de naam-sleutel kent geen
  spaties meer, maar `herken_crediteur` zocht op woordgrenzen (`" naam "` in de tekst) → nooit een treffer. Fix:
  `naam.normaliseer_crediteurnaam_woorden` (zelfde regels, spaties behouden) voor de tekst-zoeking; 259 tests over
  boekvoorstel/template/crediteuren/controle/router groen.
- `test_nameting_workflow::test_workflow_bestaat_…` — options-regex nog zonder de negen nieuwe onderdelen: bijgewerkt.
- `test_keten_guard` — de werkboom droeg tijdens de suite ongecommitte wijzigingen onder app/documenten (ruff-importfix) zonder
  tests/keten-aanraking; ná de commit is de werkboom schoon (guard slaat over). Geen gedragswijziging.
- `test_kantoor_passkeys::test_registratie_en_passkey_login_…` — kalender-artefact: de 30-dagen-refresh-TTL van vandaag (25-09)
  eindigt op 25-10 ná de wintertijdwissel → 29 d 23 h in lokale tijd; test rekent in wandkloktijd. Niet van deze run; tussen
  26-09 en 25-10 rood, structurele fix = TTL in UTC toetsen (klein blok, niet in deze run).
Daarna gerichte herrun van de geraakte suites: 259 passed; guards (`test_rapporten_*`, `test_claude_md_*`, `test_regels_index`,
`test_nameting_workflow`, `test_cc_inbox_claim_en_poort`): 114 passed. Vitest volledig: 274 files / 2053 tests passed; `tsc -b` groen.
