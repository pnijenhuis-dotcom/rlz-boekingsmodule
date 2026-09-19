uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-projectnummer-uit-afgesloten-naam.md (nameting ná deploy = vervolg-opdracht opdrachten/inbox/2026-09-19-nameting-projectnummer-afgesloten-na-deploy.md)

Domeinen: verplichtingen-projecten-voorraad, reconciliatie

# Projectnummer óók lezen uit "Afgesloten NNNNN …"-namen (bijvangst nameting 19-09)

**Aanleiding (rapport `docs/rapporten/2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md`, sectie "Nameting ná
deploy", bijvangst):** de leesreplica toont bij Universal Steigerbouw "26064 Harskamp (vd Brandhof)" én "Afgesloten 26064 Apeldoorn
(Ben Kuijer)" (beide lopend/actief). `reconciliatie-alles --alleen projecten` meldt 26053/26084/26149 als `project_nummer_dubbel`, maar
NIET 26064: `app/projecten/nummer.py::_NUMMER_PREFIX` (`^\s*(\d{3,6})(?!\d)`) leest het nummer alleen aan het begin van de naam, dus een
"Afgesloten 26064 …" telt als naamloos. Dezelfde blinde vlek zit in de 409-poort bij aanmaken (`RlzClient.find_projects_by_name_prefix`
= `startswith(Name,'26064 ')`): een nieuw "26064 …" naast een bestaand "Afgesloten 26064 …" wordt niet geblokkeerd — precies het
dubbele-nummer-scenario dat Peter 18-09 geblokkeerd wilde hebben. Universal zet het woord "Afgesloten" vóór de naam als afsluitmarkering
(94 van 170 projecten), dus dit is de normale situatie, geen randgeval.

**Opdracht (deterministisch, geen AI, geen RLZ-write):**
1. `nummer.py`: nummer-extractie = cijfer-prefix ná een optioneel "Afgesloten"-voorvoegsel (hergebruik `omzet.naam_zegt_afgesloten`:
   eerste woord, hoofdletterongevoelig) — één functie, gebruikt door `project_nummer_dubbel`, `vereis_nummer_vrij` (409-poort),
   `projecten-dubbele-nummers` en `volgende_projectnummer`. RLZ-kant: naast `startswith(Name,'26064 ')` óók `startswith(Name,'Afgesloten
   26064 ')` (twee filters óf `contains` + lokale toets — kies op basis van een STAP-0 op de RLZ-OData-filter, `rlz-lezen --root`).
2. Tests: `tests/projecten/test_status_en_nummer.py` — "Afgesloten 26064 Apeldoorn" + "26064 Harskamp" = dubbel; aanmaken "26064 X"
   naast "Afgesloten 26064 Y" = 409 mét het bestaande project; "261270" blijft geen treffer; "Afgesloten" zonder nummer = None.
3. Nameting ná deploy: `scripts/gcp/nameting.sh reconciliatie-alles --alleen projecten --lees-only` → verwacht 4 × `project_nummer_dubbel`
   bij Universal (26053, 26064, 26084, 26149) en `projecten-dubbele-nummers --administratie "Universal Steigerbouw"` toont 26064 mét
   beide kanten + voorstel "blijft" (meeste activiteit). Klikpunt Peter erbij in het rapport: Harskamp (vd Brandhof) komt drie keer voor
   (26064 + 2 × 26084) — samenvoegen is mens-werk, nooit verwijderen.
4. Rapport + INDEX + BESLISSINGEN-rij onder "PROJECTEN — STATUS AFGESLOTEN + PROJECTNUMMER UNIEK (Peter 18-09)" + regels-alinea
   `verplichtingen-projecten-voorraad.md`; committen zoals gebruikelijk.
