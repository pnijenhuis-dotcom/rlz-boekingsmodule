# Rapport 18-09 — SPOED: volumerem alleen automatisch (handmatig boeken 500-noodrem)

**Opdracht:** `opdrachten/gedaan/2026-09-18-SPOED-volumerem-alleen-automatisch.md` (Peter 18-09: "Dagelijkse limiet van 20
boekingen bereikt" ná 20 handmatig geboekte BLOW-bonnen). **Werkt in productie: niet gemeten** — deploy volgt via de Stop-hook; het
meetrecept staat onderaan.

## Samenvatting (één regel voor Peter)
Handmatig boeken loopt niet meer tegen de 20/dag-rem aan: die telt sinds deze commit alleen automatische boekingen; handmatig (en ná
klant-akkoord) heeft een eigen noodrem van 500 per dag per administratie, en elke melding zegt welke rem, hoe ver de teller staat en
wat je kunt doen.

## Gedaan / niet gedaan
| # | Regel uit de opdracht | Gedaan |
|---|---|---|
| 1 | 20/dag uitsluitend automatisch; teller = overgangen mét 'automatisch'-markering | ja — `volumerem.documentboekingen_vandaag(…, herkomst)` filtert op `detail.automatisch_geboekt`; bank op `geboekt_door` = systeem-actor; een systeem-actor zonder markering telt als automatisch (nooit als mens) |
| 2 | Handmatig = eigen noodrem 500, env-overschrijfbaar, tekst mét Beheerder-verwijzing, zichtbaar in scherm én reconciliatiemail | ja — `max_handmatige_boekingen_per_dag_per_administratie = 500`; router blijft 429 mét de tekst; reconciliatie classificeert de tekst als `noodrem` (LET-OP) — getoetst in `test_volumerem.py` |
| 3 | Ná klant-akkoord: 200 óf dezelfde 500 — eenvoudigste kiezen | gekozen: **dezelfde 500, één mens-teller**; `max_boekingen_na_klant_akkoord_per_dag_per_administratie` blijft als veld (oude env-sets) maar stuurt niets meer |
| 4 | Melding noemt rem, teller en handeling | ja — "Volumerem automatisch boeken: 20 van 20 automatische boekingen vandaag in deze administratie · handmatig boeken kan gewoon door" / "Noodrem: N van 500 handmatige boekingen … — neem contact op met de Beheerder" |
| 5 | Alle remmen via één helper | ja — `backend/app/documenten/volumerem.py`; aangesloten: documenten, omzet, verkoop, waarborg, doorbelasting (+ orkestratie geeft de herkomst door), bank direct, bank relatie, bank auto-afletteren, herstel-CLI, CLI-dry-run-tekst |

Niet gedaan: geen aparte UI-wijziging (de melding komt via de bestaande 429-afhandeling in het controlescherm); geen migratie nodig.

## Feiten
- Grep `VolumeremBereikt|max_boekingen_per_dag` vóór de fix: acht rem-plekken (documenten, omzet, verkoop, waarborg, doorbelasting, bank
  direct, bank relatie, bank afletteren) + herstel-CLI + CLI-tekst — allemaal omgezet.
- De 'automatisch'-markering bestond al op álle automatische documentpaden (`automatisch_geboekt` in het overgangsdetail: autoboeken,
  omzet-auto, verkoop-auto; bank: `bron = automatisch` + systeem-actor). Doorbelasting-boekingen dragen geen actor-kolom: de eigen
  dagteller blijft over álle doorbelastings-boekingen (conservatief), de limiet volgt de herkomst van de gang.
- **Env-var op de service (klikpunt uit de opdracht):** `gcloud run services describe rlz-backend` 18-09 ~15:45 → 43 env-regels,
  géén `MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE` — Peter had de tijdelijke ophoging niet gezet. Niet in deploy.yml opgenomen.

## Tests
- Nieuw `tests/documenten/test_volumerem.py` (9): herkomst nooit geraden; limiet per herkomst; meldingsteksten; reconciliatie-classificatie
  volumerem/noodrem; extra-telling (doorbelasting-gang); boekpad: automatische rem vol maar handmatig gaat door; teller splitst op herkomst
  én telt alleen échte overgangen (geboekt→geboekt-notitie telt niet); handmatige noodrem bijt zichtbaar; vervallen setting stuurt niets.
- Aangepast: `test_boeken.py`, `bank/test_boeken.py`, `doorbelasting/test_boeken.py`, `omzet/test_boeken.py`, `verkoop/test_boeken.py`
  (mens-paden patchen nu de handmatige noodrem), `accordering/test_boeken_na_akkoord.py` (noodrem = handmatige setting, env-naam
  `MAX_HANDMATIGE_BOEKINGEN`), `accordering/test_opruimrun_28_08.py` (`test_autoboekpad_blijft_onder_de_20_rem` → twee nieuwe tests:
  handmatig valt niet onder de 20-rem; handmatige noodrem bijt mét leesbare melding). Autoboek-tests (documenten/verkoop autoboeken,
  afletteren) blijven op de 20-rem.
- Uitkomst: zie de sectie "Tests" in `2026-09-18-inbox-afgewerkt-3.md` (volledige suite door de coördinator).

## Klikpunten Peter
- Geen verplicht klikpunt. Optioneel vóór de deploy live is: `gcloud run services update rlz-backend --region europe-west4
  --update-env-vars MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE=500` (tijdelijk; de volgende deploy zet de envset weer volledig).

## Beslispunten
- Regel 3 gekozen als "één teller, één limiet (500)". Wil Peter ná klant-akkoord toch een aparte (lagere) rem: één regel in
  `volumerem.limiet_voor`.

## Nameting-recept (ná deploy, lees-only)
1. Deploy-check service én jobs op de commit van deze run (`gcloud run services/jobs describe … image`).
2. BLOW: Peter boekt handmatig door ná de 20e boeking van de dag; request-log `POST …/documenten/<id>/boeken` → 200 (geen 429).
   Tegenbewijs lees-only: `db_lezen.sh "SELECT count(*) FROM boekhouding.document_gebeurtenis g JOIN boekhouding.document d ON d.id=g.document_id
   WHERE d.administratie_id='<BLOW>' AND g.naar_status='geboekt' AND coalesce(g.van_status,'')<>'geboekt' AND g.tijdstip >= current_date"
   --als 2f2262cd-… --administratie <BLOW>` → > 20.
3. Reconciliatiemail van de volgende ochtend: geen LET-OP "noodrem" voor BLOW; automatische paden ongewijzigd (teller `volumerem`).
"werkt in productie: ja/nee" volgt in het rapport van de nameting.

## Gelezen regels
- `docs/regels/autoboeken-ai.md` (122 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/btw.md` (150 regels), `docs/regels/kantoor-frontend.md` (123 regels), `docs/regels/intake-extractie.md` (270 regels), `docs/regels/accordering-native-app.md` (321 regels), `docs/regels/duplicaten-crediteuren.md` (119 regels), `docs/regels/uren-planning-veldwerkers.md` (472 regels)
