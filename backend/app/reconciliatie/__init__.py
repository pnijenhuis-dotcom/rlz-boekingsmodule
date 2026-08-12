"""Gedeelde laag boven de drie reconciliaties (documenten, bank, omzet): de geauditeerde
acceptatie van een afwijking die beoordeeld is en bewust blijft staan.

Bewust géén eigen reconciliatie-logica hier — die blijft in app/documenten/reconciliatie.py,
app/bank/reconciliatie.py en app/omzet/reconciliatie.py. Deze module kent alleen de drieslag
(bron, record, vingerafdruk) en is daardoor los te testen én bruikbaar voor een latere UI."""
