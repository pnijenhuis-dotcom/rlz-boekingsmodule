> uitgevoerd 2026-09-29, rapport: docs/rapporten/2026-09-29-vastly-verkoop-automatisch.md (één run, handmatige CC-sessie; migratie 0172; werkt in productie: niet gemeten — dry-run + échte run 23 + 9 = vervolg 2026-09-30-nameting-vastly-verkoop-na-deploy-en-echte-run.md ná Peters "ja")

# Vastly-verkoopfacturen volledig automatisch — geen verzamelbak, geen werkvoorraad, geen drempels (Peter 28/29-09: "moet gewoon als omzet geboekt worden, punt" / "ik wil dit nu opgelost hebben")

Handmatige CC-sessie, Peter start hem zelf. Eén run. Herziet de opt-in/drempels van 15-08 (verkoop-autoboeken) en 30-08 (v2).
LEESPLICHT: CLAUDE.md, docs/regels/omzet.md (Vastly-verkoopfactuur-boekpad §2d), intake-extractie.md, autoboeken-ai.md,
reconciliatie.md, werkloop-productie.md; Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md §2d + §8 (registersync);
docs/gesprekken/2026-09-28.md (13:xx Vastly) en 2026-09-29.md.

## Feiten (Cowork 28-09, productie)
29 Vastly-UBL's in de module: 6 geboekt (Elissen 4, Rubicon 2), 23 `te_controleren` sinds 23-09 (Rubicon 8, Meyer 4, Elissen 4,
ARVUM 3, Shuto 3, Inpensas 1) + 9 in de verzamelbak `vastly_verkoop_zonder_eenduidige_entiteit` (B. van Rooijen / G. Schaalje,
BG-2026-0026…0033+, afzender bvrooijen1983@gmail.com, tenaamstelling "B. van Rooijen"). `app/verkoop/autoboeken.py` weigerde (audit
`autoboeken_geweigerd`, bron `verkoop_opt_in`) met twee redenen: "regel 1: geen grootboekcode in de UBL — mens kiest" en "factuur-btw is
ambigu (meerdere dekkende RLZ-tarieven) en er is nog geen onthouden keuze voor deze administratie". Bijvangst: RUB-2026-0034 kreeg op
24-09 07:11 een AI-herextractie (`veldvoorstel.bron = "ai"`) via de heraanbied-motor — UBL hoort deterministisch te blijven.

## Te bouwen
1. **Entiteit → administratie uitsluitend via het entiteitenregister** (Vastly-entiteit-id/KvK in de UBL, registersync §8), nooit op
   tenaamstelling. Onbekende entiteit = kantoorbrede reconciliatiebevinding `vastly_entiteit_niet_gekoppeld` (stand `actie`) mét handeling
   "Koppel aan administratie…" (schrijft de registerkoppeling; daarna verwerkt de heraanbieding het document automatisch). Geen
   verzamelbak-rij meer voor Vastly-verkoop. De 9 Van Rooijen/Schaalje: entiteit koppelen aan administratie "B. van Rooijen / G. Schaalje"
   (Peter bevestigt de koppeling éénmalig in de bevinding), daarna automatisch.
2. **Omzetrekening deterministisch per administratie**: (a) `AccountingCost`/grootboekcode uit de UBL als aanwezig én bekend; (b) anders
   de vaste Vastly-omzetrekening per (administratie, regelsoort huur/servicekosten/waarborg/overig) — initieel afgeleid uit de 6 geboekte
   Vastly-facturen + RLZ-historie (verkoopregels op 8xxx per administratie), zichtbaar én wijzigbaar in Instellingen › Administratie ›
   Vastgoed-koppeling; (c) geen rekening afleidbaar = bevinding `vastly_omzetrekening_ontbreekt` mét handeling "Rekening kiezen"
   (per administratie éénmalig). Nooit meer "mens kiest" per document.
3. **Btw deterministisch**: het standaardtarief van de administratie voor het UBL-percentage (zelfde regel als inkoop: administratie-
   default → meest gebruikt in historie), geen "onthouden keuze"-drempel; 0 %/vrijgesteld volgens de UBL-categorie.
4. **Autoboek zonder drempels**: `probeer_verkoop_autoboeken_na_intake` boekt zodra 1–3 vaststaan; harde checks blijven blokkerend
   (duplicaat, regelsom, debiteur = échte huurder per v1.11), volumerem blijft; élke uitkomst geauditeerd; geblokkeerd = bevinding mét
   handeling in de kantoorbrede reconciliatie, NIET in de werkvoorraad-tellers van de administratie.
5. **UBL nooit door de AI**: heraanbied-motor en herlezen slaan de AI-extractie over voor XML/UBL-documenten (deterministisch herlezen).
6. **Nazorg-CLI `vastly-verkoop-heraanbieden [--dry-run]`** op de job-image: de 23 + 9 door het nieuwe pad (dry-run = telling per
   administratie en per uitkomst; echte run ná Peters "ja"); geboekte documenten krijgen dezelfde webhook als handmatig boeken.
7. **Reconciliatieblok `vastly_verkoop`**: élk Vastly-verkoopdocument > 1 dag zonder boeking = actie-bevinding mét reden; dagteller
   verwacht/gedaan/overgeslagen in de reconciliatiemail.
8. **Platform/OPEN_ITEMS**: vraag aan Vastly of `AccountingCost` per regel gevuld wordt (koppelcontract §2d v1.10) — geen blokkade.

## Niet doen
Geen verzamelbak-rij, geen werkvoorraad-status voor een Vastly-verkoopdocument dat automatisch verwerkt kan worden; geen wijziging aan
het inkooppad; geen AI in dit pad; geen verwijderen.

## Definitie van af
Gouden set groen; deploy; dry-run-telling in het rapport; ná Peters "ja" de echte run: verzamelbak Vastly = 0, `te_controleren`
Vastly-UBL's = 0 of elk mét een actie-bevinding; nameting `vastly-verkoop` (dispatch-onderdeel) op de eerstvolgende Vastly-batch;
rapport `docs/rapporten/2026-09-29-vastly-verkoop-automatisch.md` + INDEX + "werkt in productie"; BESLISSINGEN-rij; omzet.md;
WAT_IS_NIEUW; gespreksverslag 29-09; opdracht naar gedaan/.
