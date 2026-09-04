"""Projectverdeling pro rato omzet (medewerker-wensen 04-09 blok C, mockup
`projectverdeling-en-regelvoorstellen.html` blok 1 + ontwerpnotities ①–⑥).

Projectverdeling BINNEN de administratie — géén Kempen-doorbelasting (`app/doorbelasting/`), wél dezelfde
pure verdeelmotor-bouwstenen (`verdeelhulp.verdeel_naar_gewicht`, grootste-rest-centen, negatief-veilig).
Casussen: Floorbeheer, Derks-management — kosten zónder projectnummer in project-administraties zoals
Universal.

Modules:
- `data.py`     pure logica (geen I/O): verdelen, splitsen per regel (RLZ), analytic-percentages (Odoo);
- `models.py`   `boekhouding.projectverdeling` (migratie 0107);
- `omzet.py`    omzetstand per project uit de projectcijfers-cache (verkoop, kalendermaand, OVH uit);
- `service.py`  voorstel/prefill/opslaan/bevriezen + instellingen + lijst-chipdata + herverdelen;
- `hercontrole.py` maandelijkse herberekening tegen de actuele omzetstand (⑥);
- `flankerend.py` tijd-gebonden "inkoop zonder omzet"-signaal;
- `router.py`/`schemas.py` API."""
