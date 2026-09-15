# Beslispunten voor Peter — inbox-run 15-09

Eén regel per vraag, mét de default die de run gekozen heeft. Antwoorden hoeven alleen als je het anders wilt.

- **Btw verlegd — btw-plicht administratie:** geen eigen vlag; de poort is het bestaan van een verlegd-tarief in de administratie — default: zo laten.
- **Btw verlegd — KvK-lookup in de prefill:** één externe call per document als laatste terugval, uitval = stil leeg btw-veld — default: geen extra chip.
- **Planning achteraf — tijdlijnregel op het project:** er is geen project-tijdlijn; audit + chip "achteraf" zijn het spoor — default: zo laten.
- **Planning — melding ook bij een wijziging in de lopende week:** ja, gebundeld per week — default: aan.
- **Korte referenties (reconciliatie):** referenties korter dan drie tekens (ook "42") tellen niet mee in de dubbel-toets — default: aanvaard.
- **Zonnestudio — puntenwaarde:** wat is één punt waard en zijn "Points Redeemed 921" punten of euro's? (vraag aan de klant) — default: blokkerende controle tot bekend, niets geboekt op punten.
- **Zonnestudio — tweede store-naam:** hoe heet de tweede studio in "Store Used:"? — default: alleen "Elderveld" bekend, de andere landt in de verzamelbak mét reden.
- **Zonnestudio — rekeningen per studio (kas, kruispost pin, vooruitontvangen punten, kasverschil):** nodig vóór de tegenzijde-boekingen — default: niet gebouwd, aflettering via het bestaande RLZ-pad.
- **Pilates — btw-tarief sportlessen (9 % of 21 %):** default: volgt de categorie-mapping van de administratie, mens kiest bij de eerste boeking.
- **Pilates — "combi Abonnement":** Pilates, Yoga of vaste verdeelsleutel? — default: niet gecategoriseerd, blokkeert tot ingesteld.
- **Pilates — rittenkaarten/abonnementen:** omzet bij verkoop of vooruitontvangen? — default: omzet bij verkoop.
- **Pilates — betaalprovider en btw op de kosten (Mollie 21 % / Stripe verlegd):** default: leeg, kostenregel volgt de mapping "Transactiekosten PSP".

Werkt in productie: niet van toepassing (beslispuntenlijst, geen code).
