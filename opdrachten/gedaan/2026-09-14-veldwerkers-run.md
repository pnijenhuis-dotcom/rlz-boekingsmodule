uitgevoerd 2026-09-14, rapport: docs/rapporten/2026-09-14-veldwerkers-run.md

OPDRACHT — VELDWERKERS-RUN (besluiten Peter 14-09, punten 1 + 2; geen migratie)

Lees eerst BESLISSINGEN "STEIGERBOUW-RUN 25-08", "PLANNING-UITBREIDING 31-08" (recht veldwerkerbeheer), "FIXRUN 07-09 — BLOK C3" en de UX-patronen ("UX-PATRONEN ALS NORM"). UX-review vooraf verplicht: dit heeft schermimpact — beschrijf in het rapport waar het in de IA landt (nav-regel, geen tegel) en of een mockup-aanpassing nodig was; bij twijfel over vorm eerst een mockup onder mockup/ en tóch bouwen volgens die mockup (Peter beoordeelt achteraf; besluit 14-09 "alles auto").

Aanleiding: een kantoormedewerker (Universal) met het recht 'veldwerkerbeheer' kan nu alleen veldwerkers aanmaken/archiveren. Zij moet ook detacheerders aan ZZP'ers koppelen en het ZZP-dossier bewaken; het dossier is nu alleen bereikbaar via 📁 in VeldwerkersPanel en het werkvoorraad-signaal in KlantStanden.

A. Recht verbreden (backend/app/auth/deps.py `require_beheerder_of_veldwerkerbeheer`; backend/app/uren/router.py r.1394–1599):
   1. Onder veldwerkerbeheer óf Beheerder: GET /uren/beheer/veldgebruikers, POST /beheer/detacheerderkoppelingen (+/verwijderen, +/tarief — besluit: tarief ook, mét audit oud→nieuw), POST /beheer/veldwerkercrediteuren (+/verwijderen, +/autoboeken), /beheer/projectkoppelingen(/verwijderen).
   2. Beheerder-only blijft: /beheer/module-recht, /beheer/veldwerkerbeheer-recht, /beheer/dossier-documenttypen (PUT).
   3. Dossier lezen/uploaden/bedrijfsgegevens (GET/POST /uren/kantoor/dossier/…) onder veldwerkerbeheer ÓF het bestaande meerwerk-urenstaten-recht; scope-check op administratie blijft (RLS + server-side).
   4. tests/security/test_rol_endpoint_gates.py-matrix bijwerken: rol boekhouding zonder recht = 403 op álles hierboven; mét veldwerkerbeheer = 200 op A1/A3, 403 op A2. Fail-closed sweep moet groen blijven.

B. Frontend — eigen pagina /veldwerkers:
   1. Nav-item "Veldwerkers" zichtbaar voor Beheerder én houders van veldwerkerbeheer (frontend/src/shell/Shell.tsx r.87 toont /gebruikers nu alleen voor beheerder; rechten via de bestaande module-recht-DTO, fail-closed in frontend/src/auth/rollen.ts). registry-entry verplicht (instellingenRegistry / nav-guard).
   2. Inhoud: het bestaande VeldwerkersPanel (kantoorbreed, administratie = filter, doorzoekbare AdministratieCombobox), mét kolom "Dossier" (compleet / N ontbreekt / verlopen — uit de bestaande dossier-DTO, geen nieuwe berekening) en filter "dossier onvolledig"; per rij ⋯-menu met Dossier openen, Detacheerder koppelen, Crediteur koppelen, Tarief. Eén primaire knop + ⋯, linkbtn/btn-regels, kolomminima uit één bron, overflow-sweep-variant toevoegen.
   3. /gebruikers blijft Beheerder-only en verwijst voor veldwerkers naar /veldwerkers (linkbtn), geen dubbele tabellen.
   4. Werkvoorraad-signaal in KlantStanden linkt naar /veldwerkers?filter=dossier_onvolledig&administratie=<id>.

C. Docs: BESLISSINGEN-sectie "VELDWERKERS-RUN 14-09 — RECHT VERBREED + /VELDWERKERS + DOSSIER-KOLOM" (besluiten Peter 14-09 punt 1+2, tarief onder het recht mét audit), CLAUDE.md één verwijsregel onder Uren & meerwerk, WAT_IS_NIEUW-regel (klantleesbaar).

D. Af: gouden set + keten_sweep groen (schermimpact), rol-matrix groen, tsc -b, overflow-sweep; rapport docs/rapporten/2026-09-14-veldwerkers-run.md + INDEX; "werkt in productie": ná deploy toetsen dat een medewerker met veldwerkerbeheer (niet Beheerder) /veldwerkers ziet en GET /uren/beheer/veldgebruikers 200 krijgt — beschrijf het meetrecept (Peter of Cowork klikt), tot dan "niet gemeten". Dit bestand naar gedaan/.
