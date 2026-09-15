uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-administratienaam.md

OPDRACHT — administratienaam volgt de Odoo-companynaam (Peter 15-09; casus Camping "Nieuwenhoven" → in Odoo hernoemd naar "Strandpark Zilverduynen" ná het koppelen)

1. Bij de bestaande Odoo-sync per administratie ook `res.company.name` lezen (één leesbron, adapter). Is de administratienaam in de module NIET door een mens gewijzigd sinds het koppelen (nieuw veld `naam_bron` = 'odoo'|'rlz'|'mens' of vergelijk met de bij koppeling vastgelegde naam; migratie als nodig), dan volgt de module de Odoo-naam automatisch (audit `administratie_naam_gevolgd` oud→nieuw, zichtbaar in de tijdlijn/administratiedetail). Is de naam door een mens gezet: niet overschrijven, wél chip "in Odoo heet deze company nu ‹naam›" + linkbtn "Naam overnemen". Zelfde patroon voor RLZ-administraties (`Administrations` naam) als dat nu nog niet gebeurt.
2. Eenmalig ná deploy: Camping Nieuwenhoven → "Strandpark Zilverduynen" via die sync (meetrecept: administratielijst toont de nieuwe naam; audit-regel aanwezig).
3. Af: tests, BESLISSINGEN-sectie "ADMINISTRATIENAAM VOLGT DE BRON (Peter 15-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW-regel; rapport docs/rapporten/2026-09-15-odoo-companynaam.md + INDEX; dit bestand naar gedaan/.
