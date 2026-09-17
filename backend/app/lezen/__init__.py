"""Feiten eerst (Peter 17-09: "Vragen en opmerkingen uit halve informatie zijn levensgevaarlijk en pertinent verboden.
We doen zaken op basis van volledige data en anders niet."): lees-only toegang tot de eigen productiedata voor analyses.

- `bibliotheek.py`  — gereviewde, versieneerde queries (`queries/*.sql`, Jarvis-patroon): één query = één bestand mét kop.
- `sql_poort.py`    — SELECT-only-poort voor vrije SQL (één statement, geen schrijf-/DDL-/systeemfuncties).
- `service.py`      — uitvoering: bibliotheek-queries per administratie-scope (RLS, systeem-actor), vrije SELECT alleen op
                      de LEESREPLICA (`settings.lees_database_url`) als een Beheerder; audit `db_lezen` per aanroep.
- `uitvoer.py`      — markdown-tabel + JSON, PII geanonimiseerd (naam → initialen, IBAN → laatste 4), rijenplafond mét teller.
- `router.py`       — Beheerder-only routes `GET /lezen/queries`, `POST /lezen/query/{naam}`, `POST /lezen/sql` (Cowork via de
                      Chrome-extensie onder Peters login).
Geen writes: de poort weigert alles wat geen SELECT is, de transactie is READ ONLY, en de replica kán niet schrijven."""
