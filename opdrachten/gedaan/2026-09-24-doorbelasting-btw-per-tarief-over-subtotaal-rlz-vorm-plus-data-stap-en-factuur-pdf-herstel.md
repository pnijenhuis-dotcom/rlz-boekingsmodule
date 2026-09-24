uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-doorbelasting-btw-rlz-vorm.md

# Doorbelasting — btw per tarief over het subtotaal (RLZ-vorm) + data-stap + factuur-PDF-herstel (akkoord Peter 24-09 "3. ja")

Handmatige CC-sessie, Peter start hem zelf, ná de deploy van de bundelrun (blok 4 lees-only, rapport
`docs/rapporten/2026-09-24-bundelrun-zeven-punten.md`). Dit raakt GELDLOGICA: elke stap eerst bewijzen, dan bouwen; niets in RLZ
corrigeren of opnieuw boeken; RLZ is de bron van waarheid (kernprincipe 1).

LEESPLICHT: CLAUDE.md, docs/regels/doorbelasting-intercompany.md, btw.md, reconciliatie.md, werkloop-productie.md;
docs/gesprekken/2026-09-24.md; verkenning/api-verkenning.md (secties btw/regels/BookDate); `app/doorbelasting/geld.py`, `factuur.py`,
`app/documenten/regelsom.py::corrigeer_btw_centen`.

## Feit (bundelrun blok 4, uitkomst B)
Lusso 261004 (KF → Molenhof Verhuur B.V., netto € 4.741,55 + provisie € 237,08 = € 4.978,63): RLZ heeft op de verkoop
`RLZ-01-00002726` (KF) én de spiegel-inkoop `RLZ-04-00000614` (Molenhof) € 6.024,14 vastgelegd (btw € 1.045,51 = 21 % × 4.978,63);
de motor boekte en registreerde € 6.024,15 (Σ per-regel-afronding). RLZ herrekent de btw per tarief over het subtotaal van de regels
mét dat tarief en negeert daarbij het cent-verschil in onze `TaxAmount`-regels. Gevolg: (a) onze module-registratie wijkt 1 ct af van
de RLZ-boeking (module = tweede waarheid — fout), (b) de factuur-PDF-toets faalt → `factuur_pdf_status = ontbreekt` → Molenhof heeft
geen factuur op naam als bijlage (art. 35a-eis), (c) de Vastly-webhook droeg 6.024,15.

## Stap 1 — bewijs de RLZ-rekenregel (lees-only, vóór elke codewijziging)
Lees uit RLZ (nameting-SA, GET) ≥ 30 bestaande doorbelastingsverkopen + spiegels kantoorbreed mét meerdere regels, waaronder gevallen
mét twee tarieven (21 + 9 / 21 + 0 / verlegd), negatieve regels (creditregel) en provisie-regel. Per document: Σ onze regels, RLZ
`TotalAmount`/`TaxAmount` per TaxRate, en de journaalregels. Formuleer de regel exact (per tarief: btw = round_half_up(Σ netto × tarief, 2)?
of per regel gewogen? afronding half-up of bankers?) en bewijs hem op 100 % van de gevallen; één afwijking = stop + rapport, geen fix.
Zelfde meting voor 30 GEWONE inkoopfacturen uit de module (regelsom-pad) — rapporteer of het gewone inkooppad hetzelfde cent-gat kent
(alleen tellen; fix dáár is een aparte beslissing van Peter).

## Stap 2 — fix in de doorbelastingsmotor
`app/doorbelasting/geld.py`: btw per tarief over het subtotaal van de regels met dat tarief, exact volgens de bewezen regel; de
regel-`TaxAmount`s die naar RLZ gaan sommeren per tarief naar dat bedrag (grootste-rest over de regels van hetzelfde tarief); beide
kanten (verkoop + spiegel) identiek; `FactuurVerwachting` uit dezelfde functie. Tests: het Lusso-geval (4.741,55 + 237,08 → 1.045,51 /
6.024,14), twee tarieven, creditregel, één regel (ongewijzigd gedrag), provisie 0. Property-test: Σ regel-btw == btw per tarief.
Geen wijziging aan `regelsom.py` (gewoon inkooppad) in deze run.

## Stap 3 — data-stap bestaande boekingen (schrijvend in ONZE database, nooit in RLZ)
CLI `doorbelasting-bedragen-gelijktrekken [--dry-run] [--administratie]`: per geboekte doorbelasting de RLZ-bedragen (verkoop én spiegel)
lezen, vergelijken met onze registratie; verschil ≤ € 0,05 → onze registratie op de RLZ-waarde zetten mét audit
`doorbelasting_bedrag_gelijkgetrokken` (oud → nieuw, bron RLZ-document-id), tijdlijnregel op beide documenten; verschil > € 0,05 of
verkoop ≠ spiegel in RLZ = NIET aanpassen, bevinding `doorbelasting_bedrag_afwijking` (actie) in de reconciliatie. Dry-run default; de
echte run ná Peters "ja" op de dry-run-telling. Webhook: voor spiegels in vastgoed-doeladministraties waarvan het bedrag verandert een
boekstand-event (v1.14) met het gecorrigeerde bedrag; niet-vastgoed = alleen audit.

## Stap 4 — factuur-PDF-herstel
Ná stap 3: `make doorbelasting-facturen-herstel` (bestaand) op de rijen `factuur_pdf_status = ontbreekt` mét reden "onvolledig"; de
toets moet nu slagen. Rapporteer per rij: hersteld / nog ontbreekt mét reden. Blijft er een "onvolledig" over die géén cent-geval is →
apart benoemen (échte lay-out-fout). Reconciliatieblok `doorbelasting`: een geboekte doorbelasting zonder factuur-PDF > 1 dag =
bevinding mét actie "Factuur-PDF herstellen".

## Niet doen
- Geen actie 19/storno op bestaande RLZ-documenten; geen herboeking; geen wijziging in het gewone inkooppad.
- Geen fix vóór stap 1 een 100 %-bewijs geeft.

## Definitie van af
Gouden set groen; deploy; nameting ná deploy: één nieuwe doorbelasting (Peter kiest een echt geval of de testadministratie) →
module = RLZ cent-exact aan beide kanten én factuur-PDF `aanwezig` op de spiegel; dry-run-telling data-stap in het rapport, echte run
ná Peters "ja"; rapport `docs/rapporten/<datum>-doorbelasting-btw-rlz-vorm.md` + INDEX + "Gelezen regels" + "werkt in productie",
BESLISSINGEN-rij, `docs/regels/doorbelasting-intercompany.md` (regel 5 vervangen door de bewezen rekenregel), WAT_IS_NIEUW,
gespreksverslag aanvullen, opdracht naar gedaan/.
