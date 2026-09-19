# Inbox afgewerkt 19-09 (drie opdrachten, één sessie + parallelle inbox-run)

Opdracht Peter 19-09: de inbox in volgorde afwerken (1 kassarapport automatisch typeren + sweep, 2 nameting Afsluiten?-tab ná deploy,
3 ontwerp Vastly-op-Odoo toetsen), één rapport per opdracht, regels vooraf gelezen. Dit is het overzichtsrapport; de inhoud staat
per opdracht in de genoemde rapporten.

| # | Opdracht | Gedaan | Werkt in productie | Rapport |
|---|---|---|---|---|
| 1 | Kassarapport automatisch type wijzigen (deel A bouwen) + sweep signalering zonder handeling (deel B lees-only) | **ja** — deel A gebouwd + getest (motor `app/omzet/autotype.py`, upload-hook, dagelijkse run, terugweg "Tóch inkoopfactuur…", leren ná 2 correcties, dagteller, nazorg-CLI); deel B = tabel mét voorstel per bevindingssoort, niets gebouwd | **niet gemeten** (deploy ná deze run; nazorg + meetrecept in de inbox: `2026-09-19-nameting-kassarapport-autotype-na-deploy.md`) | `docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md` |
| 2 | Nameting Projecten › Afsluiten? (N) ná deploy | **nee — bewust gewacht:** de code (migratie 0167, `app/projecten/afsluiten.py`, tab) stond bij de start van deze run ONGECOMMIT in de werkboom (de vorige inbox-run eindigde vóór zijn suite klaar was — voor de derde keer, zie geheugen "inbox-run eindigt niet wachtend op suite"); deze run heeft het werk alsnog door zijn poort gehaald (suite + overflow-sweep, zie onder) en gecommit. Deploy volgt ná de push van de Stop-hook; een deploy binnen een run is onmogelijk, dus de nameting kan hier niet | **niet gemeten** — opdracht blijft in de inbox mét stap 0 deploy-check | `docs/rapporten/2026-09-19-projecten-afsluiten-tab-bulk.md` (sectie "Suite/sweep" nu ingevuld) |
| 3 | Ontwerp Vastly-klant op Odoo toetsen + pilotmeting ARVUM/Rubicon (lees-only) | **ja — door de parallelle cc-inbox-run** (sessie rlz-boekings-module-5a, commit `0bad465` RLZ + `c2e8bba` Platform); mijn agent werkte gelijktijdig aan dezelfde opdracht, de sessies hebben elkaar via berichten gevonden, de rijkste versie is samengevoegd (mijn §1–§4 pilotmeting + hun §5), één sessie committe. Advies ARVUM B.V. als kleinste volledige pilot; concept-addendum v1.21 als OPEN_ITEM in Platform | n.v.t. (lees-only) | `docs/rapporten/2026-09-19-ontwerp-vastly-odoo-toets.md` |

## Poort van deze run (gouden set + volledige suite + overflow-sweep)

- Backend-suite (volledig, eigen test-DB `boekhouding_test_autotype` omdat de gedeelde `boekhouding_test` door de eerste run bezet
  was): **6791 passed, 0 failed, 21 deselected in 1:09:02 (EXIT 0)** — eindstand van de werkboom, gestart ná de laatste codewijziging
- Overflow-sweep frontend: **groen — 232 metingen zonder horizontale pagina-overflow (EXIT 0)**, incl. de projecten-harnassen mét de tab Afsluiten?
- `tsc -b` schoon; vitest `src/omzet` 14/14, `src/projecten` 25/25, `src/changelog` 5/5; ruff op de eigen bestanden schoon (bestaande
  E501's in `cli.py`/`teksten.py`/`automatiseringen.py` ongewijzigd).
- Gouden set: nieuwe casus `tests/keten/test_ad2_autotype_inkoopfactuur_wordt_kassarapport.py` + tegenproef over álle inkoop-casussen.
- Les uit deze run: de eerste volledige suite draaide op de werkboom terwijl ik code wijzigde (gemengde run, op 76 % afgebroken);
  de gate is de tweede run op de eindstand.

## Klikpunten en beslispunten voor Peter

1. **Kassarapport-autotype ná deploy** (opdracht in de inbox): nazorg-CLI Van Boxtel dry-run → echte run via `gcloud run jobs execute`
   (schrijvend, dus expliciet), dan 340 → 336 "aandacht nodig". Verder geen klik: het systeem doet het bij élke nieuwe upload/mail.
2. **174 "fouten" = één systeemfout** (`ic_spiegel_rood`, Kempen Facilities → 5 doelentiteiten, "verkoopfactuur niet gevonden bij de
   bron-administratie", sinds 18-09) — opdracht in de inbox; tot de fix staan ze rood zonder handeling. Beslispunt: mag die opdracht
   vóór de nametingen lopen (ja, is mijn advies — het is de helft van het scherm).
3. **492 "in meting"** blijven bewust uit de actiemail (205 IC-ontbreekt, 194 dubbele betaling, 91 RC, 2 projectnummer). Beslispunt
   per soort of en wanneer promotie naar `actie` volgt — mijn voorstel: pas ná een meting per administratie, nooit op dag één.
4. **Afsluiten?-tab** (Universal): ná deploy zelf afvinken; de 8 "Afgesloten …"-projecten staan klaar. Beslispunt uit het
   verdeelsleutel-rapport blijft: herverdeling van de € 1.239,05 op afgesloten projecten ja/nee.
5. **Vastly op Odoo:** advies ARVUM B.V. + de beslispunten in het Vastly-rapport (Odoo-company, boekhoudmail-stroom, addendum v1.21
   met Vastly afstemmen vóór activatie).
6. **Procesles (twee keer vandaag):** een inbox-run die stopt vóór zijn suite klaar is laat werk ongecommit achter, en twee runs op
   één opdracht gebeurde óók vandaag. Voorstel: `cc_inbox.sh` wacht op de suite-notification vóór hij eindigt en claimt de opdracht
   (lock per opdracht) — aparte opdracht als je dat wilt.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/omzet.md` (232 regels bij het lezen), `docs/regels/intake-extractie.md`
(270), `docs/regels/reconciliatie.md` (94), `docs/regels/werkvoorraad-controlescherm.md` (297), `docs/regels/werkloop-productie.md`
(76). Voor opdracht 2 (`verplichtingen-projecten-voorraad.md`, `kantoor-frontend.md`) en 3 (`vgg-odoo-migratie.md`, `bank.md`,
`administraties-instellingen.md`): gelezen door respectievelijk de vorige inbox-run (rapport Afsluiten?-tab) en de parallelle
inbox-run/mijn agent (rapport Vastly) — deze run heeft aan die domeinen niets gewijzigd behalve het committen.
