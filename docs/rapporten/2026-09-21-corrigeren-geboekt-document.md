# "Corrigeren…" op een geboekt document — storno (actie 19) + opnieuw klaarzetten vanuit de module (21-09)

Opdracht `opdrachten/gedaan/2026-09-21-corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten.md` (Peter 21-09: twee
BLOW-boekingen met een fout btw-bedrag — RLZ-04-00000357 Fac-25-023465 48,18 i.p.v. 56,93; RLZ-04-00000358 "cb" 3,37 i.p.v. 7,87 —
"ik kan de storno-knop niet meer vinden"; "laten we die terugboeken meenemen"). Gebouwd + getest; geen migratie, geen AI. **Werkt in
productie: niet gemeten** — de code deployt ná deze run; de nameting (TEST-referentie op de RLZ-testadministratie, nooit een
klantadministratie) staat als vervolg-opdracht in de inbox mét `niet vóór: 2026-09-22 09:00`. Peter keek niet mee; keuzes staan onder
"Keuzes".

**Één regel voor Peter:** op een geboekt inkoop-, verkoop- of kassarapport-document staat nu "Corrigeren…" in het ⋯-menu: reden
invullen → de module zet het stuk in Reeleezee terug naar concept (actie 19, hetzelfde document, geen creditnota) en het document komt
terug als "klaar om te boeken" met de regels zoals ze waren, mét een gele balk die reden en vorige boeking noemt. Je past alleen de fout
aan en boekt opnieuw. Kan het niet (aangifte ingediend, al betaald, doorbelasting-kant vast, Odoo), dan zegt de dialoog vooraf wat de
weg dan wél is.

## Feit en gat

- `storno_detectie.py` (docstring, tot 21-09): "GEBOEKT is lokaal terminaal … een storno gebeurt dáár uitsluitend via actie 19 in de
  RLZ-UI". De statusmachine kende wél uitgangen uit GEBOEKT (tegenboek-pad 'vervang' → te_controleren; herboeken ná verdwenen →
  klaar_om_te_boeken), maar geen kale storno vanuit de module. Kernprincipe 7: een fout die de module boekte moet de module herstellen.
- Bestaand en hergebruikt: `herboek_als_omzet` (aangiftepoort → actie 19 → boek_cyclus +1 → neveneffecten terug) was het dichtstbijzijnde
  patroon; `tegenboeken.py` de duplicaat-keten-uitzondering (`boekvoorstel.py` `keten` sluit álle vorige cycli al uit); `herboeken.py` de
  webhook-idempotentie per boekstand-reeks; `storno_doorbelasting_boeking` + `storno_toets_voor_document` de beide-kanten-motor.

## Gebouwd

1. **`app/backends/port.py`** — `InkoopPort.storneer(document_id, boek_cyclus) -> StornoUitkomst` (gestorneerd | al_concept |
   verdwenen). RLZ-adapter: GET → Status 1 = al concept (niets schrijven), 404 = verdwenen, 2/3 → actie 19 + terug-lezen Status 1
   (niet 1 = `BackendBoekFout`, niets lokaal). Odoo-adapter: `NietOndersteund` (capability-contract 0016 §4; `button_draft` blijft
   ongebruikt, besluit Peter 02-09).
2. **`app/documenten/corrigeren.py`** — `toets()` (leesroute: per poort een `Blokkade` mét `code`/`melding`/`actie`/`actie_pad`) en
   `corrigeer()`: één transactie mét `SELECT … FOR NO KEY UPDATE` op de documentrij → status ≠ GEBOEKT = `AlGecorrigeerd` (409
   `al_gecorrigeerd`, tweede klik) → toets (RLZ-reads binnen de lock) → blokkade = `CorrigerenNietToegestaan` (409 mét `blokkades`) →
   doorbelasting-spiegels terug via de bestaande motor (spiegel → bron-verkoop) → storno eigen stuk (inkoop via de port; verkoop
   `correct_sales_invoice`; kassarapport memoriaal éérst, dan Receipt; steeds terug-lezen Status 1) → lokaal: inkoop `boek_cyclus += 1`,
   `rlz_boekstuknummer` None, `_schrijf_overgang` → KLAAR_OM_TE_BOEKEN mét detail `gecorrigeerd` (reden, oud extern id, oud
   boekstuk, gestorneerd/al_concept, doorbelasting_teruggedraaid), `draai_verbruik_terug_in_sessie`, `registreer_storno`
   (mini-voorraad), `reset_na_correctie_in_sessie` ("correctie"), webhook `factuur_gestorneerd` bron `module_storno` (vastgoed,
   zelfde boekstand-reeks), audit `document_gecorrigeerd`; verkoop: `VerkoopBoeking` → gestorneerd (+ `gestorneerd_op/door`,
   DB-CHECK) en kop-boekstuknummer leeg; kassarapport: `OmzetBoeking` → gestorneerd. Poorten: aangifte (`AangiftePoort`, fail-closed:
   niet leesbaar = `niet_leesbaar`), afgeletterd (`BasePaidAmount` ≠ 0 → `/bank/{administratie}?zoek=<ref>`; niet voor een
   kassarapport — entity-loze Receipt zonder open post), doorbelasting (één kant vast = alles vast), verdwenen (→ `/reconciliatie`),
   Odoo (`niet_ondersteund` → tegenboeken). Mislukt een externe stap: lokaal álles blijft staan, de fout benoemt wat wél al terug is,
   audit `document_correctie_mislukt`; kassarapport mét memoriaal terug maar Receipt niet → `OmzetBoeking.HALF_GEBOEKT` mét
   `half_geboekt_detail.bron = "correctie"` (bestaande zichtbare foutstatus).
3. **Routes** `GET …/documenten/{id}/corrigeer-toets` en `POST …/documenten/{id}/corrigeren` (`schemas.CorrigeerToetsResponse`,
   `CorrigerenInput{reden}`, `CorrigerenResponse`); 409 mét `{code, bericht, blokkades}` of `{code: al_gecorrigeerd}`, 502 bij een
   backend-fout, 503 zonder credential; router-brede kantoorrol + administratie-scope.
4. **`app/verkoop/boeken.py`** — een bestaande registratierij (ná een correctie `gestorneerd`) wordt bij de herboeking weer de actieve
   geboekte rij (nummer/boekstuk/debiteur bijgewerkt, storno-velden leeg). Was: alleen INSERT als er nog geen rij was → de registratie
   zou ná een correctie voor altijd `gestorneerd` blijven.
5. **Frontend** — `document/corrigerenApi.ts`, `document/CorrigerenActie.tsx`: `corrigerenMogelijk`, `useCorrigerenDialoog`
   (`?corrigeren=1`), `CorrigerenMenuItem`, `CorrigerenMenu` (eigen ⋯ voor verkoop/omzet), `CorrigerenDialog` (toets → blokkades mét
   route-knoppen "Tegenboeken…"/"Naar de bankmodule →"/"Naar Inzicht › Reconciliatie →", of reden + "Storneren en opnieuw
   klaarzetten"; 409 `al_gecorrigeerd` = klaar, 409 mét blokkades ná indienen = tonen), `CorrectieBalk` (gele balk uit de laatste
   `gecorrigeerd`-tijdlijnregel, weg ná een nieuw GEBOEKT), `correctieTijdlijnTekst`. Ingehaakt: `DocumentDetailScreen` (menu-item ná
   "Verplaats…", dialoog mét `onTegenboeken` → `?tegenboeken=1`, balk boven de panelen, tijdlijnregel, toast + `laadDetail`),
   `VerkoopReviewScreen`/`OmzetReviewScreen` (⋯ naast de geboekt-regel, balk, herladen via teller), `ArchiefScreen` (⋯ "Corrigeren…" op
   geboekte rijen van de drie soorten → `reviewPad?corrigeren=1`). Types in `api/types.ts`.
6. **Sweep** — `storno_detectie.py` docstring, `statusmachine.py` commentaar (GEBOEKT niet meer terminaal-zonder-uitweg),
   `verplaatsen.py`/`verplaatsen.ts` (reden verwijst naar "Corrigeren…"), `BoekvoorstelPanel.tsx` + test, verkoop-/omzet-teksten
   "alleen via stornering in Reeleezee" vervangen. Niet aangeraakt: `WaarborgReviewScreen.tsx` (waarborg = memoriaal buiten scope) en
   `TegenboekSectie.tsx` (de "niet aan de orde"-tekst blijft juist: storno is dan de route).

## Tests

- `tests/documenten/test_corrigeren.py` (16): storno + klaarzetten (RLZ Status 1, cyclus 1, boekstuk leeg, tijdlijn `gecorrigeerd`, audit
  oud→nieuw), statusmachine, herboeking op het nieuwe GUID ná correctie (oud concept blijft), toets beschikbaar, reden verplicht,
  tweemaal klikken = één storno + toets zegt `status`, al concept in de RLZ-UI → lokaal wél klaar; poorten: aangifte → `aangifte` +
  tegenboeken (niets gewijzigd), aangiften niet leesbaar → `niet_leesbaar` fail-closed, afgeletterd → `bank` mét pad, verdwenen →
  `opnieuw_boeken`, RLZ-fout bij actie 19 → alles blijft staan + audit mislukt; Odoo-stub → `niet_ondersteund` + échte
  `OdooInkoopPort.storneer` raise-t `NietOndersteund` zonder Odoo-call; doorbelasting: spiegel eerst dan inkoop (volgorde-assert),
  geblokkeerde kant blokkeert alles (geen storno-call), mislukte spiegel-storno = zichtbaar + lokaal ongewijzigd; webhook vastgoed
  `factuur_gestorneerd` volgnummer 2 bron `module_storno` / niet-vastgoed geen event; HTTP toets 200 + corrigeren 200 + tweede 409
  `al_gecorrigeerd` + blokkade 409 mét `blokkades`.
- `tests/verkoop/test_corrigeren.py` (4): storno + registratie gestorneerd + kop leeg + herboeking maakt registratie weer geboekt;
  aangifte-blokkade zonder tegenboek-knop ("creditnota"); betaald → bank-link; vastgoed-webhook.
- `tests/omzet/test_corrigeren.py` (4): beide stukken (memoriaal éérst), registratie gestorneerd, herboeking op dezelfde GUID's →
  tweede geboekte rij; aangifte op het memoriaal blokkeert alles; géén afgeletterd-poort voor een Receipt; Receipt-storno faalt ná het
  memoriaal → `HALF_GEBOEKT` mét detail + audit.
- Fakes uitgebreid: `FakeBoekClient.correct_purchase_invoice`, `FakeOmzetClient(aangiften=)` + `list_tax_declarations`.
- Vitest `document/CorrigerenActie.test.tsx` (9): dialoog (reden-drempel, POST-body, uitkomst), aangifte-blokkade → "Tegenboeken…",
  afgeletterd → bank-link mét href, doorbelasting benoemd, 409 `al_gecorrigeerd` = klaar, 409-blokkades ná indienen, `CorrectieBalk`
  toont/verdwijnt; `BoekvoorstelPanel.test.tsx` tekst bijgewerkt.
- Gouden set: casus **ah** `tests/keten/test_ah_corrigeren_geboekt_document.py` (3) — zie "Poort — poging 2".
- Poort: zie "Poort — poging 2" onderaan.

## Keuzes (Peter keek niet mee)

1. **Rijvergrendeling i.p.v. tussenstatus** voor de idempotentie: `FOR NO KEY UPDATE` op de documentrij gedurende de RLZ-calls (een
   handmatige, zeldzame actie; ~1–3 s). `FOR UPDATE` niet: de doorbelasting-motor schrijft in eigen transacties tijdlijn-/webhookrijen
   mét FK op het document (KEY SHARE) — dat zou deadlocken. Tweede klik wacht en krijgt 409 `al_gecorrigeerd`; de dialoog behandelt dat
   als "klaar" (herladen), niet als fout.
2. **Doorbelasting éérst, dan het eigen stuk.** Andersom zou een mislukte spiegel-storno een RLZ-concept achterlaten bij een lokaal nog
   GEBOEKT document (de reconciliatie ziet dat pas de volgende ochtend). Nu: faalt de eigen storno ná de spiegels, dan zegt de fout
   letterlijk welke doelen al terug zijn (de doorbelasting-run staat zichtbaar op `gestorneerd`).
3. **Verkoop/kassarapport her-PUTten op hetzelfde GUID** — die motoren kennen geen `boek_cyclus`; her-PUT op een concept vervangt de
   regels (api-verkenning "Her-PUT op een bestaand concept") en beide motoren sluiten hun eigen GUID al uit van de duplicaatcheck. Geen
   nieuwe id-afleiding, geen migratie.
4. **Kassarapport: geen afgeletterd-poort.** Een entity-loze Receipt mét tegenzijde heeft geen open post en geen PaymentItem; de
   huls-koppelingen-zorg (actie 15/19) geldt daar niet. Bewust getest (`test_geen_afgeletterd_poort_voor_een_receipt`).
5. **Verkoop/kassarapport ná ingediende aangifte: geen knop, alleen de route "creditnota in Reeleezee".** Het tegenboek-pad bestaat
   alleen voor inkoop; een verkoop-tegenboek-pad bouwen valt buiten deze opdracht (zou een eigen mockup vragen).
6. **Klant-accordering: géén nieuwe ronde** (regel accordering 1 — het akkoord gold de factuur). De tijdlijn draagt de correctie;
   een aparte push naar de accordeur-app is niet gebouwd (de accordeur ziet de tijdlijn al).
7. **Rechten: élke kantoorrol** (Medewerker+ = Boekhouding en hoger; externe app-rollen 403 via de router-brede poort). Geen
   Beheerder-stap — anders dan bij het suppletie-pad is hier geen btw-risico (de aangiftepoort blokkeert).
8. **Casus 357/358 niet gemeten** (geen productietoegang in deze run). Regel: `BookDate` = factuurdatum; is Fac-25-023465 een
   2025-factuur en die periode aangegeven, dan biedt de dialoog "Tegenboeken…" (het bestaande pad) — geen storno; valt de boekdatum in
   een open periode, dan corrigeren. De nameting bewijst het mechaniek op de testadministratie; de BLOW-stukken blijven klikwerk van
   Peter (TEST-referentie-regel).

## Nameting ná deploy (vervolg-opdracht `opdrachten/inbox/2026-09-22-nameting-corrigeren-testadministratie.md`)

Stap 0 deploy-check (service én jobs); stap 1 op de RLZ-TESTADMINISTRATIE: inkoopfactuur mét referentie `TEST-CORRIGEREN-<datum>` boeken →
"Corrigeren…" → verwacht: RLZ Status 1 op het oude GUID (`rlz-lezen PurchaseInvoices/{guid}` via nameting.sh), document
`klaar_om_te_boeken`, `boek_cyclus` 1, audit `document_gecorrigeerd`, gele balk; daarna opnieuw boeken → Status 2 op het NIEUWE GUID
(cyclus 1); stap 2 tweede klik tijdens/ná = 409 `al_gecorrigeerd`; stap 3 request-log `POST …/corrigeren` ≥ 1. Rapport
`2026-09-22-nameting-corrigeren-testadministratie.md` mét "werkt in productie: ja/nee/niet gemeten" per stap.

## Documentatie

BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)" + registerrij Kernflow inkoop;
`docs/regels/werkvoorraad-controlescherm.md` (alinea 21-09), `doorbelasting-intercompany.md` (spiegels mee), `reconciliatie.md`
(module_storno ≠ verdwenen); CLAUDE.md werkvoorraad rij 8; WAT_IS_NIEUW 2026-09-21; dit rapport + INDEX; opdracht → gedaan mét kopregel;
vervolg-opdracht nameting in de inbox.

## Poort — poging 2 (ná WIP-branch)

Poging 1 (inbox-run 21-09 ochtend) eindigde vóór de suites klaar waren (rij j3); het werk stond als WIP-commit `25be9fb` op branch
`wip/2026-09-21-corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten` (blijft ter controle staan). Poging 2 begon met
`git merge --squash` van die branch: drie beide-kanten-conflicten (`docs/BESLISSINGEN.md`, `docs/rapporten/INDEX.md`,
`frontend/src/changelog/WAT_IS_NIEUW.md` — de secties van de planning-/activa-runs náást de corrigeren-sectie) zijn opgelost door beide
kanten te behouden; geen inhoudelijke wijziging aan het WIP-werk zelf.

| Poort | Uitkomst |
|---|---|
| `tsc -b` (volledige werkboom) | schoon |
| gerichte set (3 corrigeren-bestanden + docs-guards) | 61 passed |
| vitest volledig | 245 bestanden, 1897 tests groen (ná de activa-fix: `ActivaVoorstelKaart` + `CorrigerenActie` 20 groen) |
| gouden set frontend `scripts/keten_sweep.sh` | eerst 5/11 ROOD (zie bijvangst), ná de fix 11/11 groen zonder baseline-verversing |
| pytest volledig (incl. `tests/keten`), run 1 | 7066 passed, 1 skipped, **4 failed** (50:55) — zie hieronder |
| pytest gericht ná de drie fixes (casus ah, verplaatsen, keten-guard, cc-inbox, docs-guards) | 54 passed |
| `alembic check` | n.v.t. — geen migratie, geen modelwijziging |

**De vier rode tests van run 1 en wat ermee gebeurd is:** (1) `test_keten_guard` — wijzigingen onder `app/documenten` en
`frontend/src/document` zonder aanraking van `tests/keten`: de gouden set beweegt nu mee mét de nieuwe casus **ah**
(`tests/keten/test_ah_corrigeren_geboekt_document.py`: de échte BDO-UBL boeken → `corrigeren.toets` beschikbaar → `corrigeer` mét
standaard port-resolutie via de credential-seam → RLZ Status 1 op het oude GUID, klaar_om_te_boeken, cyclus 1, tijdlijnregel mét reden,
document terug in de standaardlijst; tweede klik = `AlGecorrigeerd` zonder tweede actie 19; checks vers en groen ná de correctie (oud concept
als eigen keten uitgezonderd) → herboeking op het nieuwe GUID, oud concept blijft staan); (2)+(3) `test_verplaatsen` (twee tests) toetsen
letterlijk op het woord "storno" in de 409-uitleg voor een geboekt document — de WIP-tekst noemde alleen "Corrigeren…"; de tekst zegt nu
"draai de boeking eerst terug via storno ("Corrigeren…" in het ⋯-menu, of "Tegenboeken…" ná een ingediende aangifte)", backend én
frontend (`verplaatsen.ts`); (4) `test_cc_inbox_claim_en_poort::test_run_schrijft_claim_met_pid_en_starttijd_en_ruimt_op` — groen in
isolatie (twee keer), raakt het echte `opdrachten/.lock`/claim-pad terwijl deze run zelf de inbox-lock hield: omgevingsflake van de
inbox-runner, geen regressie.

**Bijvangst — de gouden set stond op main al rood door de activa-kaart (commit 81f65d9 van vanmiddag, niet door dit werk):** alle vijf
detail-casussen renderden een LEEG controlescherm (≈ 51 % pixelverschil; `--dump-dom` toonde `<div id="root"></div>` mét
`data-keten-klaar="ja"`, console: `Uncaught TypeError: v.kandidaten is not iterable` in `ActivaVoorstelKaart.tsx`). Het keten-harnas
antwoordt `{}` op onbekende routes; `neemOver` itereerde daar over `v.kandidaten` in een render-effect → React ontkoppelt de hele root. Fix in
deze run: (1) `ActivaVoorstelKaart.neemOver` toetst het antwoord (beide lijsten aanwezig, anders geen kaart — de kop-commentaar beloofde al
"een fout bij het laden blokkeert het scherm nooit", maar een `catch` op de fetch vangt geen vorm-fout in de `then`); (2) het keten-harnas
mockt `GET …/activa-voorstel` mét een leeg voorstel; (3) vitest-guard "toont niets en crasht niet bij een antwoord zonder kandidaten-lijst".
Vastgelegd in `docs/regels/activa.md` (alinea 21-09) + BESLISSINGEN-alinea "Bijvangst poging 2". Geen WAT_IS_NIEUW-regel: in productie
levert de backend altijd de juiste vorm, dit is een robuustheidsfix.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT, kopregel "Domeinen"; in poging 2 opnieuw): `docs/regels/werkvoorraad-controlescherm.md` (319 regels bij het
lezen; 347 ná deze run), `docs/regels/doorbelasting-intercompany.md` (174 regels; 185 ná), `docs/regels/reconciliatie.md`
(180 regels; 191 ná); voor de bijvangst `docs/regels/activa.md` (30 regels bij het lezen; 37 ná).
