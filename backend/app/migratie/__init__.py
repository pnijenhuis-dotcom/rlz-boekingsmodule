"""Migratie-hulpmiddelen voor de overstap van een administratie RLZ → Odoo (bundel 10-09 blok D1).

Alleen LEES-rapporten: geen RLZ-writes, geen Odoo-writes, geen DB-mutaties. De Odoo-overstap zelf leeft in
`app/odoo/` (ODOO-SLOTSTUK 04-09); dit pakket levert de schoonlijst waarmee een mens de RLZ-kant opruimt vóór de
kanteldatum."""
