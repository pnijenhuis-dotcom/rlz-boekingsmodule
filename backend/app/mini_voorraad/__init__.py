"""Mini-voorraad speciale producten (blok F mini-run 06-09, mockup mini-voorraad.html ①–⑧).

Controle-laag in het `mi`-schema náást de voorraad-aansluiting: producten die buiten de standaard-
materiaalcatalogus vallen ontstaan automatisch uit geboekte inkoopfacturen (omschrijving × aantal) en hun
stand is uitsluitend Σ van append-only, brongebonden mutaties (⑧ — mens-manipulatie onmogelijk). Nooit
RLZ-/Odoo-writes; niets verwijderen — archiveren."""
