# Inbox afgewerkt — run 15-09 (opdracht Peter "WERK DE INBOX AF")

**In gewone taal.** Alle tien opdrachten uit `opdrachten/inbox/` zijn in volgorde uitgevoerd, getest, gedocumenteerd en gecommit; de
inbox en `lopend/` zijn leeg, `mislukt/` en de `.pogingen`-bestanden zijn opgeruimd. Er is in deze run niets in productie geschreven
(geen Odoo-/RLZ-writes; productie alleen lees-only via `scripts/gcp/nameting.sh`). Alles wat Peter moet beslissen staat op één lijst:
`docs/rapporten/2026-09-15-beslispunten-peter.md`. Deploy volgt op de Stop-hook; per opdracht staat hieronder het meetrecept dat
Peter of Cowork ná deploy uitvoert — "werkt in productie" is daarom overal **niet gemeten** (of niet van toepassing).

| # | Opdracht | Gedaan | Commits | Werkt in productie | Rapport |
|---|---|---|---|---|---|
| 1 | reconciliatie-nazorg | ja | `cf210f3`, `854a6ad` | niet gemeten | `2026-09-15-reconciliatie-nazorg.md` |
| 2 | bank-match-klantreferentie | ja (STAP-0 lees-only op productie gedaan) | `3581790`, `7a01c5b` | niet gemeten | `2026-09-15-bank-match-klantreferentie.md` |
| 3 | btw-verlegd-herkenning-bouw | ja (STAP-0 projectvraag lees-only gedaan) | `600a71f`, `33b3daf`, `526fc62` | niet gemeten | `2026-09-15-btw-verlegd-herkenning.md` |
| 4 | offerte-match-olieman-stil | ja | `4e2eede`, `50ccef8` | niet gemeten | `2026-09-15-offerte-match-olieman.md` |
| 5 | gebruikers-klantaccordeurs-ui-bugs | ja | `de9c402`, `8dd4255` | niet gemeten | `2026-09-15-gebruikers-ui-bugs.md` |
| 6 | planning-urenstatus-en-terugwerkend (migratie 0145) | ja | `b110668`, `d351216` | niet gemeten | `2026-09-15-planning-urenstatus.md` |
| 7 | planning-ploegen-mockup (alleen mockup + commit) | ja, geen bouw | `ad94b8a` | n.v.t. (mockup) | `2026-09-15-planning-ploegen-mockup.md` |
| 8 | accordeur-app-pdf-zoom | ja (toesteltest iOS/Android open) | `abad48f`, `d7d1e0c` | niet gemeten | `2026-09-15-accordeur-pdf-zoom.md` |
| 9 | omzet-zonnestudio-dagstaat (migratie 0146) | ja; tegenzijde per betaalwijze + Beheerder-UI bron-instellingen bewust open | `e521828`, `30fe164`, `63f9c3f` | niet gemeten | `2026-09-15-omzet-zonnestudio.md` |
| 10 | omzet-pilates-betalingsexport | ja; kruispost PSP + bankmatch bewust open (ná PSP-beslispunt) | `e521828`, `30fe164`, `63f9c3f` | niet gemeten | `2026-09-15-omzet-pilates.md` |

Ook in deze run: `7921427` (afronding VGG → Odoo blok 8 uit de afgebroken vorige inbox-run) en `459642d` (cc-inbox: geen twee runs
tegelijk) — stonden niet in de tien, wel in de werkboom.

## Wat niet gedaan is (bewust, met reden)

- **Opdracht 9:** Cash → kas / PIN → kruispost / storting → kruispost als eigen boekingen en Points Redeemed → omzet vanaf de balans:
  wachten op de drie STAP-0-antwoorden van de klant (puntenwaarde, tweede store, rekeningen per studio). Beheerder-UI voor de
  bron-instellingen: alleen de route `GET/PUT /administraties/{id}/omzet/bron-instellingen`.
- **Opdracht 10:** kruispost "PSP-uitbetaling" + bankmatch die de netto ontvangst groen maakt, contant → kas: ná het PSP-beslispunt.
  De opdracht noemde 22 uitbetalingen; de export bevat er 23 (de contant-betalingen vormen een eigen batch).
- **Opdracht 8:** toesteltest iOS/Android niet uitgevoerd (geen toestel in de run).
- **Productie:** niets gemeten — deploy gebeurt pas ná deze run (Stop-hook pusht, workflow deployt).

## Beslispunten voor Peter (defaults gekozen, run liep door)

Zie `2026-09-15-beslispunten-peter.md`: korte referenties reconciliatie; btw verlegd (btw-plicht, KvK-chip); planning (tijdlijnregel,
melding lopende week); zonnestudio (puntenwaarde, tweede store, rekeningen); pilates (btw-tarief lessen, combi-abonnement,
vooruitontvangen vs omzet, PSP/kosten-btw).

## Meetrecept ná deploy (Peter of Cowork)

0. Deploy-check: service én jobs op hetzelfde beeld (`gcloud run jobs describe … image`), smoketest groen.
1. **Reconciliatie-nazorg:** nameting-reconciliatie van de eerste ochtend: Kempen Facilities `bedrag_wijkt_af` ≤ 0,05 → 0 open,
   regel "N automatisch geaccepteerd (afronding ≤ 0,05)"; Booking Experts 20260205347 Δ 0,97 blijft open; `rlz_dubbel` Abbegaa "01"
   niet meer als cluster.
2. **Bank klantreferentie:** `scripts/gcp/nameting.sh bank-voorstellen-lezen --administratie "Clean Care Arnhem B.V."` → de drie
   bijschrijvingen (Department of Cosmetics, VA Climate, Secure2Go) GROEN "naam + nummer + bedrag", kaart toont de factuurdatum.
3. **Btw verlegd kolomcode:** tweede Olieman-termijn openen → btw-veld gevuld met het verlegd-tarief mét herkomst-chip, alleen
   "Boeken" nodig; project leeg tot Bouwadvies Oost Nederland een RLZ-project heeft.
4. **Offerte-match:** factuur 32948 Bouwadvies Oost Nederland toont "Offerte van deze leverancier gevonden — wacht op akkoord" zolang
   de offerte open staat; ná akkoord de match mét termijnen.
5. **Gebruikers UI:** screenshot Beheer › Gebruikers › Klant-accordeurs op 1440: geen chip-overloop; demo-account toont
   "herstel-link verloopt niet".
6. **Planning urenstatus:** `/planning?administratie=<Universal>&week=2026-W37` → statusstip + tekst per kaartje, weektotaal in de
   rijkop, `&uren=zonder` filtert; app veldwerker: chips "week 36 · week 37 · deze week".
7. **Planning ploegen:** geen meting (mockup ter beoordeling Peter/Haci).
8. **PDF-zoom:** PWA → factuur → knijpen tot 4×, dubbeltik 2×, "⤢ Volledig scherm"; native ná de volgende build.
9. **Zonnestudio:** "Elderveld" in de bron-instellingen zetten (PUT-route), `8-9-26.xls` + `kascheck-2026-09-08.xlsx` naar facturen@ →
   één kassarapport bij de studio mét regels 250,00 / 349,03 / 420,00, kascheck-blok, "Puntenwaarde bekend" rood, kasverschil 0,99
   oranje; kascheck "samengevoegd in …".
10. **Pilates:** `pilates-betalingen-2026-07.xlsx` uploaden als kassarapport → ouder "gesplitst" + 23 kinderen; kind
    `2026-7-9-ca834c16` netto 637,08 mét dispute-signaal; tweede upload → "Geen transactie al geboekt" rood.

## Werkt in productie: niet gemeten

Zie de tabel: alle code-opdrachten wachten op de deploy ná deze run; opdracht 7 is een mockup.
