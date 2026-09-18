uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-bug-offerte-verbruik-telt-onderweg-facturen.md (nazorg + nameting: opdrachten/inbox/2026-09-18-offerte-verbruik-onderweg-nameting.md)

Domeinen: verplichtingen-projecten-voorraad, accordering-native-app, werkvoorraad-controlescherm

# BUG 18-09 — Offerte-match telt alleen GEBOEKTE facturen; facturen die nog in de accordering zitten tellen niet mee
# (Peter 18-09 20:04, accordeur-app, Bouwadvies Oost Nederland, offerte "zonder nummer" € 1.192.922,50)

**Peter (letterlijk):** "ik heb net een factuur geaccordeerd van deze partij voor € 20.000, deze boeking zegt nu binnen offerte (50.000
van bedrag), maar dat moet nu 20.000 + 50.000 (70.000) zijn, hij moet wel doortellen."

**Scherm:** factuur 32949 (03-09-2026, Bouwadvies, "2e termijn werkzaamheden", € 50.000 verlegd, laag 1) → kaart "✓ Binnen de
goedgekeurde offerte zonder nummer · € 50.000,00 van € 1.192.922,50 · akkoord Systeem (achtergrondverwerking), 18-09-2026". De eerder
door Peter geaccordeerde factuur van € 20.000 (dezelfde leverancier/offerte, laag 1 akkoord, lagen 2–3 nog open) ontbreekt in de teller.

## Oorzaak (code)
`verplichting/match_pipeline.py::verreken_in_sessie` schrijft het verbruik (`Verplichting.verbruikt_bedrag_excl`) pas bij in de
GEBOEKT-transactie (`documenten/boeken.py`). `match.py::Kandidaat.verbruikt_bedrag_excl` = alleen geboekt. Een factuur die ter
accordering staat (3 lagen = dagen tot weken) telt dus nergens mee; twee facturen kunnen tegelijk "binnen offerte" zijn terwijl de som
erbuiten valt. Bij 3 lagen is dat de normale situatie, geen randgeval.

## Regel (bindend; volledige tekst naar `docs/regels/verplichtingen-projecten-voorraad.md`)
1. **Verbruik = geboekt + onderweg.** Onderweg = Σ `VerplichtingMatch.bedrag_excl` van documenten met uitkomst BINNEN/BUITEN op dezelfde
   verplichting, status niet terminaal en niet GEBOEKT (ter_accordering, klaar_om_te_boeken, wordt_geboekt, boeken_mislukt, in controle),
   het eigen document uitgezonderd. `verbruikt_bedrag_excl` blijft de boekstand (auditspoor bij boeken ongewijzigd); `onderweg` wordt
   per toets berekend (één query), nooit opgeslagen.
2. **Toets en tekst**: binnen/buiten op (geboekt + onderweg + eigen bedrag) ≤ offertebedrag. Kaart: "€ 70.000,00 van € 1.192.922,50 ·
   waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)" — in de accordeur-app én het kantoor-controlescherm (zelfde DTO).
   Balk: geboekt vol, onderweg gearceerd, eigen factuur gemarkeerd. Termijnnummer telt onderweg mee ("3e termijn").
3. **Volgorde-effect**: wordt een onderweg-factuur afgewezen, dan zakt het verbruik en wordt een eerder "buiten" mogelijk "binnen" —
   herbereken de match van de andere open documenten op dezelfde verplichting bij elke statuswissel (bestaande herberekenroute), mét
   tijdlijnregel; nooit stil. Buiten offerte blijft niet-blokkerend (bestaande regel: bevestiging bij boeken).
4. Kantoorbreed `/verplichtingen` en de verplichting-detail tonen dezelfde drie getallen (geboekt / onderweg / restant).

## Bouw & tests
`match.py`: `Kandidaat.onderweg_bedrag_excl` + toets op de som; `match_pipeline.py`: query onderweg (index op `verplichting_document_id`
bestaat?), herberekening bij statuswissel van een gematcht document (hook in de statusmachine-overgangen ter_accordering/afgewezen/
geboekt); DTO-velden `verbruik_geboekt`, `verbruik_onderweg`, `onderweg_aantal`; accordeur-app kaart + kantoor-MatchSectie + balk;
kantoorbreed-overzicht. Tests: 20k ter accordering + 50k nieuw op offerte 60k → BUITEN; afwijzen 20k → herberekening → 50k BINNEN;
geboekt 20k + onderweg 0 = bestaande gedrag; eigen document nooit dubbel; termijnnummer telt onderweg mee. WAT_IS_NIEUW ("Offertes
tellen nu ook facturen mee die nog in de goedkeuring zitten"). Rapport + INDEX + Gelezen regels; nameting: Bouwadvies offerte zonder
nummer toont 70.000 (20.000 onderweg) op factuur 32949 — "werkt in productie: ja/nee".
