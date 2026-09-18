# BUG accordeur 18-09 — toegang is geen laag: "Administraties toevoegen…" vervangt geen lagen meer, verwijderen = twee vinkjes

**Opdracht:** `opdrachten/gedaan/2026-09-18-BUG-accordeur-administratie-toevoegen-overschrijft-lagen.md` (Peter 18-09, 19:30 live).
**Status:** GEBOUWD + GETEST 18-09; geen migratie. **Werkt in productie: niet gemeten** (deploy volgt via de Stop-hook ná deze run);
de nameting van de casus (Romy/Bouwadvies) ís gedaan op de leesreplica — zie §Nameting.
**BESLISSINGEN:** "TOEGANG IS GEEN LAAG — KLANT-ACCORDEUR TOEGANG GEVEN VERANDERT DE GOEDKEURINGSROUTE NIET (Peter 18-09)".

## Wat er mis was
Gebruikers › Klant-accordeurs › ‹accordeur› › "Administraties toevoegen…" liep over `POST /accordering/bulk-instellen` mét
`lagen = [accordeur laag 1]` en verving daarmee de bestaande lagen van de gekozen administratie (én herberekende lopende rondes).
"Verwijderen" deed PUT zonder de accordeur + DELETE scope: toegang weg → niet meer kiesbaar voor een leveranciersroute. Toegang en
laag zaten aan elkaar vast. BESLISSINGEN blok 5 (08-09) beslispunt 2 had dit gedrag al als open vraag gemarkeerd.

## Wat er gebouwd is
| # | Regel (opdracht) | Bouw |
|---|---|---|
| 1 | Toegang ≠ laag: toevoegen = scope-only + expliciete keuze per administratie, preview nu/wordt | `frontend/src/gebruikers/AccordeurAdministraties.tsx`: ScopeLijst → keuze-stap per administratie ("Nu: klant-accordering aan, 3 lagen: Peter N. → Sophia Gerritsen → Kempen" / "Wordt: …"), `Select` met **Alleen toegang** (default, alleen `POST /auth/gebruikers/{id}/scope`), **Ook als laag: vóór laag 1 / ná de laatste laag** (scope + PUT mét de bestaande lagen plús deze accordeur, hernummerd, `ingeschakeld` ongewijzigd, aanleiding "laag toegevoegd via Klant-accordeurs"), **Alleen in een leveranciersroute** (scope + link "Route-editor openen →"). Resultaat per administratie, deelfout zichtbaar. Pure functies `huidigeStandTekst`, `lagenNaToevoegen`, `wordtTekst`. De bulk-route wordt vanuit dit venster niet meer aangeroepen. |
| 2 | Verwijderen = twee gescheiden vragen | Eigen dialoog (`accordeur-verwijderen-dialoog`): vinkje "Uit de accorderingslagen halen" (default aan als hij erin staat, mét de herberekend-/vervallen-telling uit het preview-endpoint; uit + vergrendeld als hij er niet in staat) en vinkje "Toegang intrekken" (default UIT, mét uitleg). Intrekken zet "uit de lagen" vast aan (een laag zonder toegang kan niet goedkeuren). Laatste laag = de aparte uitschakel-bevestiging (08-09) blijft en zegt of de toegang blijft. Gearchiveerd = alleen toegang (voorgevinkt). |
| 3 | Bulk vervangt alleen ná expliciete bevestiging per administratie mét de huidige stand | Backend: `BulkInstelUitkomst.bestaande_lagen` (namen op volgnummer, in preview én resultaat), `BulkInstellenInput.vervangen_bevestigd`, `service.bulk_instellen(vervangen_bevestigd=…)` → niet-bevestigde administratie mét lagen = `overgeslagen` mét reden `VERVANGEN_NIET_BEVESTIGD_REDEN`, lagen blijven (fail-closed in code). Frontend `BulkAccorderingDialog.tsx`: in de overschrijf-waarschuwing per administratie een vinkje "vervangt 3 lagen bij Bouwadvies: Peter N. → Sophia Gerritsen → Kempen" + hint "niet aangevinkt = overgeslagen"; de vink reist mee bij toepassen (niet in de preview). |
| 4 | Keuzelijst: "Andere klant-accordeur toegang geven…" ook mét accordeurs | `GeenAccordeursMelding.tsx::AndereAccordeurKoppelen` (dezelfde koppel-dialoog, scope-only, Beheerder-only) onder de lagen op de klant-accorderingstab (`AccorderingInstellingen.tsx`) en in de route-editor (`LeverancierRoutes.tsx`); de dialoogtekst zegt nu expliciet "Toegang is geen laag". |

Geen nieuwe route; de scope-route, de instellingen-PUT en de bulk-route zijn de enige schrijvers (twee nieuwe optionele velden op de
bulk). `vooringevuldeAccordeurId` op de bulk-dialoog blijft bestaan maar heeft geen aanroeper meer vanuit het accordeur-venster.

## Keuzes zonder Peter (opdracht: zelf kiezen)
1. **Server-side bevestiging** i.p.v. alleen een UI-vink: `vervangen_bevestigd` wordt in `bulk_instellen` afgedwongen — een oude tab of
   tweede client kan nooit stil vervangen. Bestaande tests die vervangen beogen geven de bevestiging nu expliciet mee.
2. **"Ook als laag" laat de toggle staan** (uit blijft uit, mét hint) — aanzetten blijft een bewuste handeling op de tab; de PUT-route
   weigert "aan zonder lagen" toch al.
3. **Toegang intrekken dwingt "uit de lagen" af** als de accordeur in de lagen staat (anders weigert de server later het aanbieden en
   staat er een dode laag).
4. **Eén `Select` per administratie** i.p.v. `KeuzeKaarten` (schaalt naar tientallen administraties in één stap; comboboxen-regel).
5. Blok-5-beslispunt 1 (afdelingsroutes automatisch opschonen bij verwijderen) blijft open; de dialoog benoemt het.

## Tests
- Backend nieuw: `tests/accordering/test_toegang_is_geen_laag_18_09.py` — (a) scope-only via de HTTP-route laat 3 lagen én de lopende
  ronde staan, géén `accordering_schema_gewijzigd`/`accordering_ronde_herberekend`-audit, wél precies één `scope_toegevoegd`, en de
  accordeur is daarna kandidaat; (b) preview draagt `bestaande_lagen` ("S. Bakker", "R. Jansen"), toepassen zonder bevestiging =
  `overgeslagen` mét reden en lagen + scope onaangeroerd, mét bevestiging = `vervangen`. Aangepast: `test_bulk_instellen.py`,
  `test_herberekenen.py` (bevestiging meegegeven). `tests/accordering` + `tests/security/test_rol_endpoint_gates.py` +
  `tests/auth/test_gebruikers_lijst.py` + rapport-guards: zie de regel onderaan.
- Vitest: `GebruikersScreen.test.tsx` blok 5 herschreven/uitgebreid (toevoegen zonder laag = alleen POST scope en geen bulk-dialoog;
  laag ná = POST + PUT mét 4 lagen; vóór/route mét route-link; verwijderen default = PUT zonder DELETE; toegang intrekken = PUT +
  DELETE mét vergrendeld lagen-vinkje; niet in lagen = Bevestigen uit tot "Toegang intrekken", dan alleen DELETE; laatste laag =
  toggle uit zonder DELETE; annuleren; gearchiveerd = alleen DELETE), `BulkAccorderingDialog.test.tsx` (+1: "vervangt 3 lagen …",
  vink → `vervangen_bevestigd`, preview zonder), `AccorderingInstellingen.test.tsx` (+1 koppelknop mét accordeurs → scope-POST),
  `LeverancierRoutes.test.tsx` (+1). Volledige vitest-suite: 1847 groen, 1 rood in `BoekvoorstelPanel.test.tsx` ("B3-dekking …
  checksHerrunVersie") dat los wél groen is (49/49) — timing-flake onder parallelle last, niet door deze run geraakt (bestand
  ongewijzigd). `tsc -b` schoon. Doc-guards (`test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, changelog-test) groen.

## Nameting productie (lees-only, leesreplica `rlz-sql2-lees` via `scripts/gcp/db_lezen.sh` als nameting@; request-log Cloud Logging)
Opdracht: "Romy heeft scope Bouwadvies (gezet 18-09 ~19:35 via Cowork) mét 3 ongewijzigde lagen — controleer dat de audit dat toont."
Tijdlijn (CEST) uit request-log + `platform.audit_event` + `boekhouding.accordering_laag` (administratie `a265c010-…`):

| Tijd | Wat | Bewijs |
|---|---|---|
| 19:40–19:45 | 8× `POST /accordering/bulk-instellen/preview` 200 | request-log |
| 19:45:53 | `POST /accordering/bulk-instellen` 200 → audit `accordering_schema_gewijzigd`: drie lagen 46627c10 → 8d7df5fe → b679290f (= Peter N. → Sophia Gerritsen → Kempen), `rondes_herberekend 0` | de oude drie rijen (actief sinds 08-09 23:08) gedeactiveerd 19:45:53, drie nieuwe actieve rijen mét dezelfde accordeurs en volgorde |
| 19:52:25 | `POST /auth/gebruikers/1ffdbcc9-…/scope` 204 (Romy) → audit `scope_toegevoegd` {administratie a265c010} | **géén** schema-/herberekend-audit erbij |
| 19:59:04 | `POST …/accordering/leverancier-routes` 201 → "Route Romy - RvB Groep en Gebr. Olieman", modus `bovenop`, positie `na` + audit `accordering_ronde_herberekend` (lopende ronde nu 4 lagen: 3 gewone + Romy) | route-tabel + audit |

Stand nu: Bouwadvies heeft **3 actieve lagen Peter N. → Sophia Gerritsen → Kempen (inhoudelijk ongewijzigd t.o.v. 08-09)**, klant-accordeurs
mét scope = Kempen, Peter N., Romy v. Lambalgen, Sophia Gerritsen; Romy staat níét in de gewone lagen, wél in de bovenop-route.
Nuance: het request-log toont één bulk-toepassen om 19:45:53 waarvan het resultaat de drie gewone lagen is (dezelfde set als
daarvóór) — de bulk heeft dus wel het "vervangen"-pad gelopen (oude rijen gedeactiveerd, nieuwe aangemaakt, 0 rondes geraakt), maar
er is in productie geen moment geweest waarop Bouwadvies alleen "Romy laag 1" had; de scope om 19:52 (niet ~19:35) is scope-only
gebleven, precies wat de nieuwe regel afdwingt. Geen herstelactie nodig.

Klikpunt/les: `db-lezen --sql --als` op de job-image accepteert alleen een Beheerder-**e-mail**; `p.nijenhuis@kempengroep.nl` is
daar geen actieve Beheerder (exit 2, drie job-executies). `scripts/gcp/db_lezen.sh` mét Peters Beheerder-uuid werkte direct;
`boekhouding.accordering_laag` vereist daarbij `--administratie` (alleen scope-policy, geen Beheerder-clausule → anders 0 rijen).

## Nameting ná deploy (recept)
1. Gebruikers › Klant-accordeurs › een accordeur › "Administraties toevoegen…" → Verder → keuze-stap toont "Nu: … N lagen: …";
   Toepassen mét "Alleen toegang" → audit alleen `scope_toegevoegd`, `accordering_laag` van die administratie ongewijzigd (query Q2 uit
   dit rapport mét `--administratie`).
2. Idem mét "ná de laatste laag" → audit `accordering_schema_gewijzigd` mét `aanleiding: laag toegevoegd via Klant-accordeurs` en
   N+1 lagen waarvan de eerste N identiek.
3. Instellingen › Klant-accordering › bulk op een administratie mét lagen, zonder vink → uitkomst "overgeslagen · bestaande lagen niet
   bevestigd"; mét vink → "vervangen".

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/accordering-native-app.md` (321 regels)
- `docs/regels/auth-toegang.md` (202 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)

## Bijgewerkt
`docs/regels/accordering-native-app.md` (alinea "Toegang ≠ laag"), `docs/regels/auth-toegang.md` (alinea "Scope van een klant-accordeur
= toegang, nooit een laag"), `docs/BESLISSINGEN.md` (nieuwe sectie), `CLAUDE.md` (verwijsregels accordering 6 + auth 7),
`frontend/src/changelog/WAT_IS_NIEUW.md` (blok 18-09, vier punten), dit rapport + INDEX, opdracht → `opdrachten/gedaan/`.

Backend-testrun (accordering + rol-gates + gebruikerslijst + rapport-guards): 642 groen; de ene rode (`test_rapporten_index`) was de INDEX-regel die tijdens de run al bestond vóór dit rapportbestand — ná het schrijven van het rapport zijn de drie rapport-/CLAUDE.md-guards 9/9 groen.
