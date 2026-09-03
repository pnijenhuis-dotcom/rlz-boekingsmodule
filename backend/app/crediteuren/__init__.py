"""Crediteuren-dubbelen v2 — kantoorbrede dubbel-signalering MÉT actie (design-ronde 03-09, mockup
`crediteuren-dubbelen-v2.html` = bouwnorm, migratie 0100). Hergebruikt de bestaande motor
`app.documenten.crediteur_kenmerk.dubbele_crediteuren`; voegt afmelden, de RLZ-werklijst (STAP-0 03-09:
archiveren via de API kan niet — pad "API werkt niet" uit notitie ④) en het verhuizen van
boekingsgeheugen + crediteur_kenmerk naar de voorkeurs-crediteur toe. Geen RLZ-writes, nooit verwijderen."""
