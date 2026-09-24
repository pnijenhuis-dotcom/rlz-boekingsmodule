uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-ai-limiet-heraanbieden.md

# BUG + FIX 24-09 — AI-limiet: sticky banner, geen heraanbieding ná verhoging, dubbelencheck vóór de AI-stap

Opdracht Peter 24-09 ("dat AI limiet voor alle nieuwe facturen is nog steeds niet opgelost, dat wil ik nu als eerste … medewerkers
lopen daar tegenaan en waarschijnlijk vist die er nog wel redelijk wat dubbele uit" → "doe eerst die opdracht maar, dat moet nu gefixt
worden"). Handmatige CC-sessie, Peter start hem zelf. Prioriteit boven alles wat in opdrachten/inbox staat.

LEESPLICHT vóór je begint: docs/regels/intake-extractie.md, docs/regels/werkvoorraad-controlescherm.md,
docs/regels/duplicaten-crediteuren.md, docs/regels/kantoor-frontend.md, docs/regels/reconciliatie.md (dagtellers), docs/regels/
werkloop-productie.md; docs/gesprekken/2026-09-23.md (sectie "Herstelrun" + "Aanvulling 22:0x") en 2026-09-24.md (10:xx AI-limiet).

## Feiten (gemeten 24-09 10:4x door Cowork, productie, lees-only)
- `/instellingen/ai-kosten`: maand 2026-09, verbruik € 102,23, limiet € 150,00 (Peter verhoogde 23-09 21:2x van € 100), percentage 68,
  `geblokkeerd=false`, `limiet_bereikt=true`, 1.277 AI-extracties + 82 template-extracties deze maand.
- Verzamelbak: 208 rijen, waarvan 202 × reden `ai_limiet_bereikt`, ALLE aangemaakt 2026-09-23 19:11 (herstelrun kempengroep-postvak
  `--sinds 2026-09-01`); 0 nieuwe vandaag. De poort (`app/aikosten/service.py::controleer_poort`) toetst live verbruik ≥ limiet en laat
  sinds de verhoging weer door — nieuwe uploads/intake krijgen dus extractie. Het probleem is wat de medewerkers ZIEN en wat er is blijven
  liggen.

## Oorzaken
1. **Sticky banner.** `app/beheer/router.py:915` zet `limiet_bereikt = status_.limiet_bereikt_op is not None`; `AiKostenMaandstatus.
   limiet_bereikt_op` wordt éénmaal per maand gezet (`registreer_verbruik`, regel 229) en nooit teruggezet. `frontend/src/werkvoorraad/
   WerkvoorraadScreen.tsx:93-98` toont daarop de rode banner "AI-verwerking is geblokkeerd; nieuwe documenten volgen het handmatige pad" —
   de hele rest van de maand, ook ná een verhoging. Zelfde vlag in `InstellingenScreen.tsx`.
2. **Geen heraanbieding.** Twee populaties blijven liggen ná een verhoging (of een nieuwe maand):
   a. verzamelbak-rijen `ai_limiet_bereikt` — de splitsingsdetectie (`app/intake/verwerking.py:606`) sloeg af VÓÓR toewijzing, dus ook
      facturen met eenduidige tenaamstelling staan daar; toewijzen kan alleen met de hand, per stuk;
   b. documenten mét administratie met tijdlijn-detail `ai_extractie_overgeslagen: "ai_limiet_bereikt"` (`app/documenten/service.py:943,
      1009, 1047`) — status te_controleren/handmatig_afmaken zonder voorstel.
   `heraanbied_gefaalde_extracties` (`service.py:724`, CLI `app/cli.py:195`) filtert uitsluitend op `ai_extractie_fout` en draait alleen
   handmatig.
3. **Dubbelen kosten AI-geld.** De byte-identieke/referentie-dubbelencheck loopt ná de extractie; in het verzamelbak-pad (bericht →
   splitsingsdetectie → AI) wordt een reeds bekende bijlage dus opnieuw door de AI gehaald. Peter: "waarschijnlijk vist die er nog wel
   redelijk wat dubbele uit" — de herstelrun las het kempengroep-postvak vanaf 01-09 inclusief mail die eerder al via de forward binnenkwam.

## Te bouwen
A. **Banner = werkelijke stand.** `WerkvoorraadScreen` en `InstellingenScreen` tonen "geblokkeerd" uitsluitend op `geblokkeerd` (= verbruik
   ≥ limiet, live). `limiet_bereikt(_op)` blijft als historisch feit zichtbaar in Instellingen ("limiet bereikt op … bij € …; limiet daarna
   verhoogd naar € …") maar stuurt geen blokkade-tekst meer. Ná verhoging toont de banner één regel "AI-verwerking weer actief sinds
   <moment>; N documenten wachten op heraanbieding" mét linkbtn naar de verzamelbak. Test op beide vlaggen los van elkaar.
B. **Heraanbieding automatisch, geen stille no-op (kernprincipe 7.6).** Eén motor `app/aikosten/heraanbieden.py`:
   - selecteert (a) verzamelbak-documenten met reden `ai_limiet_bereikt` en (b) documenten mét administratie waarvan de LAATSTE
     extractie-gebeurtenis `ai_extractie_overgeslagen == ai_limiet_bereikt` draagt en status ∈ {te_controleren, handmatig_afmaken};
   - draait per intake-job-run (beide postvak-jobs) én in de dagelijkse run, alleen als `geblokkeerd=false`; verwerkt in volgorde
     oud → nieuw, stopt zodra de poort weer dichtgaat (dan tijdlijn "wacht op AI-budget", geen fout);
   - (a) loopt opnieuw door het NORMALE intake-pad (splitsingsdetectie → toewijzing op tenaamstelling → extractie) met dezelfde
     `intake_bericht_id`/afzender-hint, zodat toewijzing en verzamelbak-leren gewoon werken; (b) loopt door de bestaande extractie-route
     van het document (zelfde AVG-gate, klein/groot-routing, template-terugval);
   - élke heraanbieding = tijdlijnregel + audit `ai_heraanbieding` (oude reden → uitkomst), dagteller `ai_heraanbiedingen`
     verwacht/gedaan/overgeslagen in de reconciliatiemail; volumerem: max 300 per run (LET-OP als de rest blijft staan, nooit stil);
   - knop op de verzamelbak "Opnieuw verwerken (N)" (Beheerder/Boekhouder) = dezelfde motor, 202 → resultaat per rij in een uitkomstlijst
     zoals bulk-upload (toegewezen / verzamelbak-andere-reden / dubbel / wacht op budget);
   - nazorg-CLI `ai-heraanbieden [--dry-run] [--max N]` op de job-image voor de 202 van 23-09 (uitvoering ná deploy, Peter's "ja").
C. **Dubbelencheck vóór de AI-stap.** In het intake-pad (én in de heraanbieding) vóór de splitsingsdetectie: byte-identieke hash over
   álle bestaande documenten kantoorbreed → bestaat al = `samengevoegd`/`afgevoerd_duplicaat` volgens de bestaande regels (docs/regels/
   duplicaten-crediteuren.md), géén AI-call, tijdlijn "dubbel vóór extractie herkend (bespaard)". Referentie-dubbelen kunnen pas ná
   extractie — die blijven waar ze zijn. Dagteller `ai_bespaard_dubbel`.
D. **Guard-tests:** (1) banner-test: `limiet_bereikt_op` gezet + `geblokkeerd=false` → géén blokkade-tekst; (2) heraanbieding stopt
   zodra de poort dichtgaat en laat de rest zichtbaar staan; (3) verzamelbak-rij ná heraanbieding → toegewezen met dezelfde
   `intake_bericht_id`; (4) byte-identiek exemplaar in het intake-pad → 0 AI-calls (mock-teller); (5) heraanbieding bij `geblokkeerd=true`
   = overgeslagen mét teller, geen exception; (6) `test_regels_index` / `WAT_IS_NIEUW.md` bijgevuld.

## Niet doen
- Geen ophoging van de limiet in code; de limiet blijft een instelling (Peter zet zelf tijdelijk € 250 voor september — advies Cowork).
- Geen verwijderen van verzamelbak-rijen; een rij die ná heraanbieding een andere reden krijgt, krijgt die reden mét tijdlijn.
- Geen tweede extractiepad — alles via de bestaande wachtrij (201 < 2 s-regel).

## Definitie van af
Gouden set groen; migratie-routine als er een migratie is; deploy; daarna nameting (recept vooraf): `/instellingen/ai-kosten` toont
`geblokkeerd=false` en de banner is weg (screenshot Peter of visueel harnas); `ai-heraanbieden --dry-run` op productie noemt 202 + N(b);
ná Peters "ja" de echte run: verzamelbak `ai_limiet_bereikt` → 0, uitkomstverdeling in het rapport (toegewezen / andere reden / dubbel /
wacht op budget), AI-kosten vóór/ná; dagtellers in de eerstvolgende reconciliatiemail. Rapport `docs/rapporten/2026-09-24-ai-limiet-
heraanbieden.md` + INDEX + "Gelezen regels" + regel "werkt in productie: ja/nee/niet gemeten" per onderdeel. Gespreksverslag
docs/gesprekken/2026-09-24.md aanvullen (0024).
