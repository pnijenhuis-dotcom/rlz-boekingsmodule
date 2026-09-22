# Ter accordering — dagelijkse bestaanscheck "intussen buiten de module geboekt": bevinding mét handeling i.p.v. een geblokkeerde boekstap ná het laatste akkoord (22-09)

Opdracht `opdrachten/gedaan/2026-09-22-ter-accordering-dagelijkse-rlz-bestaanscheck-intussen-buiten-de-module-geboekt.md` (Peter 21-09 19:15,
Bouwadvies Oost Nederland B.V. / Beter Assemblage B.V., F/2026/01235 € 173,84, document 8c558b35). Gebouwd + getest; geen migratie, geen
RLZ-write, geen AI. **Poging 2:** poging 1 (inbox-run 22-09 17:46) haalde de poort niet — de run eindigde terwijl de volledige suites nog
liepen (les "inbox-run eindigt niet wachtend op suite"); het ongecommitte werk stond als WIP-commit `513853b` op branch
`wip/2026-09-22-ter-accordering-dagelijkse-rlz-bestaanscheck-intussen-buiten-de-module-geboekt` en is in deze poging via `git merge --squash`
teruggehaald (één conflict: `docs/rapporten/INDEX.md`, beide regels behouden), afgemaakt en ná de volledige poort gecommit; de branch blijft ter
controle staan. **Werkt in productie: niet gemeten** — de code deployt ná deze run; de meetlat staat onderaan en als vervolg-opdracht
`opdrachten/inbox/2026-09-23-nameting-ter-accordering-bestaanscheck-na-deploy.md` (`niet vóór: 2026-09-23 09:00`). Peter keek niet mee; keuzes
staan in "Keuzes".

**Één regel voor Peter:** de module wist pas ná het derde akkoord dat F/2026/01235 al vijf dagen als RLZ-04-00000518 in Reeleezee stond. Vanaf de
eerste run ná de deploy toetst de dagelijkse reconciliatie élk document dat nog op klant, IBAN-akkoord of kantoor wacht vers tegen Reeleezee/
Odoo; een treffer staat dezelfde ochtend op Inzicht › Reconciliatie mét boekstuk, bedrag en datum en twee knoppen ("Afwijzen — al geboekt als …"
/ "Toch verschillend — doorgaan"), de accordeurs zien "kantoor beoordeelt; akkoord niet nodig" en krijgen geen herinnering meer. Vooraf gemeten:
op de stand van vandaag staan **10 van de 39 open RLZ-documenten al in Reeleezee** — Bouwadvies 8 van 13.

## Feit en oorzaak (code gelezen)

- **Casus:** harde checks doorstaan 16-09 09:13 → lagen Peter N. (16-09), Sophia Gerritsen (21-09 10:52), Kempen (21-09 19:15) → boeken ná het
  laatste akkoord geblokkeerd door de harde check Duplicaatcheck: RLZ-04-00000518, zelfde crediteur + referentie, buiten de module.
- **RLZ (lees-only, `rlz-lezen` Bouwadvies, `ReceiptNumber eq 'RLZ-04-00000518'`):** Date 26-08-2026, Status 2 (Open), Origin 1, Description
  "Segers", InvoiceReference/Reference F/2026/01235, BaseInvoiceAmount 173,84, Entity "B.A.B." (een tweede crediteurrecord — de identiteitscluster
  van de check vond 'm daardoor wél). **Wie boekte: niet leesbaar via de API** — `PurchaseInvoices` kent geen `CreatedBy`/`ModifiedBy`; een
  `$expand=CreatedBy,ModifiedBy,Uploads` wordt door RLZ stil genegeerd (identiek antwoord). Of een collega buiten de module om werkt is dus
  alleen in de RLZ-UI (documenthistorie) na te gaan; de API geeft het niet prijs.
- **Code:** `app/documenten/reconciliatie.py` toetste uitsluitend `GEBOEKT`-documenten (A11/A12); de bestaanscheck `extern_bestaan.
  zoek_extern_bestaand` liep alleen als signaal bij intake en als harde check op het boekmoment (16-09), sinds 18-09 gecachet (0165). Een
  document dat dagen bij de klant ligt werd tussendoor nergens opnieuw getoetst — precies het gat.

## Gebouwd

1. **Hercontrole in het documenten-blok** (`app/documenten/reconciliatie.py::hercontroleer_open_documenten`, aangeroepen in
   `reconcilieer_administratie` op dezelfde port/client): élk inkoopdocument op `ter_accordering`, `wacht_op_iban_accordering` of
   `klaar_om_te_boeken` (> 1 dag stil, `HERCONTROLE_KLAAR_MINIMUM`) krijgt de bestaande bestaanscheck (alle crediteurrecords van de identiteit,
   ± 60 d, genormaliseerde referentie), bewust ZONDER checks-cache. Eerste blokkerende treffer (zelfde referentie, met of zonder gelijk bedrag,
   ook een RLZ-concept) buiten de eigen boekketen en buiten de "toch verschillend"-afmeldingen → afwijking **`intussen_extern_geboekt`**, detail
   `omschrijf_treffer` (deterministisch → acceptatie-vingerafdruk), context extern_boekstuk/extern_id/extern_stand/bedrag_extern/extern_datum/
   document_status/sinds/backend. **Storing/geen credential = géén bevinding, wél zichtbaar overgeslagen** (`hercontrole_overgeslagen`, CLI-regels
   `HERCONTROLE <adm>: N vers getoetst, K overgeslagen` + `OVERGESLAGEN document=…: reden`). Rate-limit: één client per administratie, één
   `zoek_extern_bestaand` per document per dagelijkse run.
2. **Soort direct in `actie`** (besluit Peter in de opdracht: "start in meten? NEE"): `SoortDefinitie.direct_actie_reden` + guard
   (`test_soort_stand.py`: reden ≥ 20 tekens, lijst exact `["intussen_extern_geboekt"]`); explosie-rem blijft. Tekst (`teksten.py`): "Al geboekt in
   RLZ buiten de module — ‹lev› ‹nr›" / "Dit document wacht bij ons op het klant-akkoord, maar dezelfde factuur staat al geboekt in RLZ als
   RLZ-04-… (€ …, dd-mm-jjjj) — buiten de module om." / "Wijs het document af als 'al geboekt' …, of kies 'Toch verschillend — doorgaan' …".
   Urgentie 1 in de kantoorbrede lijst; actiemail-fixture en tekst-guard groen.
3. **Twee handelingen** (`app/documenten/intussen_extern_geboekt.py`; routes `POST /reconciliatie/documenten/{id}/extern-geboekt/afwijzen` en
   `…/toch-verschillend`, élke kantoorrol binnen scope, accordeur 403):
   - **Afwijzen — al geboekt als ‹boekstuk›:** open vragen aan de accordeur sluiten (slotbericht), ronde vervalt via
     `laat_ronde_vervallen_wegens_extern_geboekt` met de tijdlijnregel **"niet meer nodig: al geboekt in Reeleezee (RLZ-04-…)"** (marker
     `accordering_vervallen_extern_geboekt`, geen "opnieuw aanbieden"-banner), daarna de bestaande `afwijzen.wijs_af` mét voorgevulde reden "Al
     geboekt in Reeleezee als ‹boekstuk› (buiten de module)" + kruisverwijzing. `wacht_op_iban_accordering` = 409 mét route (IBAN-accordering
     eerst); geboekt/andere status = 409.
   - **Toch verschillend — doorgaan:** reden ≥ 5 (422), tijdlijnregel `extern_duplicaat_toch_verschillend` + audit, checks-cache van de crediteur
     ongeldig; het externe id telt niet meer als treffer in de hercontrole én in de harde check (`afgemelde_extern_ids` → `keten`). Tweede keer
     409. Beheerder accepteert mét `bevinding_id` óók de bevinding; andere rol niet (bevinding verdwijnt bij de volgende run, gemeld).
4. **Accordeur-app:** `WachtrijItem.extern_geboekt` uit één leesbron `open_treffers` (laatste afgeronde run, live acceptatie-stand); banner
   letterlijk "Al geboekt in Reeleezee (RLZ-04-…) — kantoor beoordeelt; akkoord niet nodig"; item uit "te accorderen" (teller, "N van M",
   doorloop) en in de sectie **"Wachten op kantoor · N"** (kaart mét banner, review zonder actiebalk), BV-kaart-chip "N wacht(en) op kantoor".
   Server = poort: akkoord/afwijzing accordeur 409 `WachtOpKantoor`; `documenten_aan_de_beurt`/`aantallen_aan_de_beurt` (09:00-herinnering,
   bundelmelding) slaan het document over; handmatige herinnerknop 409 mét banner-tekst (guard-tests).
5. **Boeken ná het laatste akkoord:** `CheckResultaat.data["extern_geboekt"]` → `boek_fout.extern_geboekt` → `boek_fout_extern_geboekt` in de
   accordering-DTO → `AccorderingSectie` toont de twee knoppen (component `ExternGeboektActies`) i.p.v. "Los de oorzaak op en boek opnieuw" (die
   tekst blijft voor andere oorzaken). **Copy-check** `tests/unit/test_geen_bug_in_klanttekst.py` (frontend-klanttekst + backend-strings; drie
   bestaande strings herschreven: cli-help, `soort_stand.meting`, bewaking "fout in de app-laag").

## Meting 22-09 (lees-only, vooraf — leesreplica per administratie + `rlz-lezen` met een `Reference eq`-or-keten per administratie, nameting@)

Open inkoopdocumenten kantoorbreed: **82** (70 ter_accordering, 10 klaar_om_te_boeken, 2 wacht_op_iban_accordering) over 14 administraties;
Universal Steigerbouw 43 (Odoo — niet via `rlz-lezen` te toetsen, volgt uit de hercontrole zelf ná deploy). Van de **39 in RLZ-administraties**
staan **10 al in Reeleezee** (match op letterlijke referentie; de hercontrole normaliseert en toetst óók op crediteur-identiteit, dus dit is een
ondergrens voor spaties-varianten en een bovengrens voor toevallige referentie-gelijkheid):

| Administratie | Status | Referentie | Bedrag module | RLZ-boekstuk | RLZ-status | RLZ-datum | Sinds (laatst gewijzigd) |
|---|---|---|---|---|---|---|---|
| Bouwadvies Oost Nederland B.V. | ter_accordering | F/2026/00053 | 2.381,75 | RLZ-04-00000516 | 3 (gesloten) | 01-09 | 01-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | F/2026/01235 (de casus) | 173,84 | RLZ-04-00000518 | 2 | 26-08 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | F/2026/01238 | 15.623,57 | RLZ-04-00000519 | 2 | 26-08 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | F/2026/01237 | 12.566,10 | RLZ-04-00000520 | 2 | 26-08 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | F2615113 | 2.297,43 | RLZ-04-00000521 | 2 | 28-08 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | VF2607986 | 27.337,77 | RLZ-04-00000523 | 2 | 02-09 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | C2615322 | −617,20 | RLZ-04-00000524 | 2 | 04-09 | 16-09 |
| Bouwadvies Oost Nederland B.V. | ter_accordering | VCB260464 | −135,34 | RLZ-04-00000526 | 2 | 08-09 | 16-09 |
| Molenhof Beheer B.V. | ter_accordering | 200161832 | 107,69 | RLZ-17-00001131 | 2 | 08-09 | 16-09 |
| Rubicon Investments B.V. | ter_accordering | F239153280 | 61,24 | RLZ-04-00002358 | 2 | 29-07 | 16-09 |

Niet in RLZ (0 treffers): Bouwadvies 33122/32949/32948/910047/20608574, BLOW 2, Meyer 1, Kempen Facilities 11, Midden Nederland 1, Oirschot
Recreatie 1, Oirschot Vastgoed 1, Rubicon 5, Veldhoven 1, Zilver 1. **Bouwadvies is dus geen incident maar een werkwijze: 8 van de 13
wachtende facturen zijn buiten de module om geboekt** (RLZ-04-00000516–526, een aaneengesloten reeks van 26-08 t/m 08-09, meest "sinds 16-09" =
de dag waarop Peter de eerste laag akkoord gaf). Wie dat deed is via de API niet leesbaar (zie boven) — dat is een vraag voor Peter aan het
kantoor of aan Bouwadvies zelf.

## Poort

- Backend: `tests/reconciliatie/test_intussen_extern_geboekt.py` 18 groen (hercontrole treffer/geen treffer/storing/geen credential/klaar > 1
  dag/afgemeld; app-banner + herinneringsbron + 409's; boekfout-kern; afwijzen + toch verschillend + poorten; registry + actiemail + urgentie);
  gerichte set 343 groen (documenten-reconciliatie, checks, accordering, berichten, reconciliatie, boek-wachtrij, duplicaat-afvoer); gouden set
  `tests/keten` 171 groen; `test_wachtrij_querytelling.py::test_payload_lijst_dto_blijft_compact` versoepeld van ≤ 8 naar ≤ 9 `null`s (het
  nieuwe optionele veld); copy-check 2 groen.
- Frontend: `tsc -b` schoon; vitest `ExternGeboektActies` 4, `administraties.externGeboekt` 3, `GoedkeurenFlow.externGeboekt` 3,
  `AccorderingSectie.externGeboekt` 3, `ReconciliatieScreen` +1, bestaande accordeur-/sectie-/changelog-tests groen (59 in de geraakte set).
- Poging 2 (22-09 avond): 13 ruff-bevindingen in eigen regels handmatig gefixt (12 × E501 wraps, 1 × dode variabele `extern_geboekt`
  in het directe boekpad van `accordering/service.py` — de échte kern reist via `_boek_na_laatste_akkoord`); geen gedragswijziging.
- Gouden-set-casus **aj** `tests/keten/test_aj_ter_accordering_intussen_extern_geboekt.py` (poging 2; de keten-guard eiste 'm terecht: poging 1
  raakte `app/documenten` zonder de gouden set aan te raken): BDO-UBL via de mail-intake → boekvoorstel → twee lagen, laag 1 akkoord → dezelfde
  factuur verschijnt in RLZ als RLZ-04-00000518 → de échte dagelijkse run (CLI-plumbing) maakt de bevinding mét boekstuk/stand/status, de
  wachtrij van laag 2 draagt de banner-kern en een akkoord = `WachtOpKantoor`, "Afwijzen — al geboekt als …" over de API → ronde vervallen mét
  de letterlijke reden + marker, document afgewezen mét kruisverwijzing, wachtrij leeg, 0 PUT's naar RLZ, uit de standaardlijst; tegenproef
  zonder extern stuk = wachtrij gewoon open.
- Volledige suites poging 2 (22-09 avond): backend `pytest tests` 7165 passed / 1 failed / 1 skipped in 47:51 — de ene rode was de
  keten-guard (`test_keten_guard.py`, terecht: geen gouden-set-aanraking), opgelost mét casus aj; daarna herdraai gouden set + accordering +
  reconciliatie + doc-guards 358 passed (2:32); frontend `vitest run` 1923 passed (252 bestanden), `tsc -b` schoon.

## Keuzes (Peter keek niet mee)

1. **Soort direct in `actie`** volgt de opdracht letterlijk en is een expliciete, gereden uitzondering in code + guard; de explosie-rem blijft.
2. **Treffers = blokkerende bases** (zelfde referentie, ook ander bedrag, ook een RLZ-concept) — exact wat de boekstap zou blokkeren;
   bedrag+datum-signalen bewust niet (legitiem bij gelijke facturen).
3. **`wacht_op_iban_accordering`** wordt getoetst en gemeld, maar de knop "Afwijzen" verwijst naar de IBAN-route (409 mét tekst): de
   afwijzing-tabel kent die herkomst niet (DB-check) en de vier-ogen-aanvraag verdient een eigen besluit.
4. **"Toch verschillend"** accepteert de bevinding alleen als de actor Beheerder is (acceptatie is Beheerder-werk); anders is de afmelding zelf
   de waarheid en verdwijnt de rij bij de volgende run — de melding zegt dat.
5. **Geen nieuwe CLI/meetinstrument:** de meetlat is het bestaande nameting-onderdeel `reconciliatie`; de `HERCONTROLE`-regels en de
   bevindingssoort zijn direct greppbaar.
6. **Vraag 4 "wie boekte":** niet leesbaar via de API; als feit vastgelegd, geen gok.

## Meetrecept ná deploy (vervolg-opdracht 23-09)

Stap 0 deploy-check (service én jobs); échte run 06:30 → bevindingen `intussen_extern_geboekt` per administratie (verwacht Bouwadvies 8, Molenhof
1, Rubicon 1 + Odoo-kant Universal), stand `actie`, actiemail; `nameting.sh reconciliatie-alles --lees-only` → `HERCONTROLE`-regels;
request-log wachtrij (`extern_geboekt`-items), herinneringen, handelingen-POSTs + audits; "niet gemeten (ongebruikt)" als het kantoor niet klikt.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/accordering-native-app.md` (361 regels bij het lezen; 388 ná deze run),
`docs/regels/duplicaten-crediteuren.md` (129 regels; 143 ná deze run), `docs/regels/reconciliatie.md` (238 regels; 255 ná deze run),
`docs/regels/werkvoorraad-controlescherm.md` (401 regels).
