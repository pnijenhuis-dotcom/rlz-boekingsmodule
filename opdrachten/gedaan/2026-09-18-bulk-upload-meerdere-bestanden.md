uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-bulk-upload-meerdere-bestanden.md

Domeinen: intake-extractie, werkvoorraad-controlescherm, kantoor-frontend

# OPDRACHT 18-09 — Bulk-upload: meerdere bestanden tegelijk slepen/kiezen (Peter 18-09: "180 documenten bij BLOW, gaat niet")

**Feit (Cowork, code 18-09):** `frontend/src/werkvoorraad/UploadZone.tsx` r. 43/90 leest `files?.[0]` — één bestand per drop/kies,
geen `multiple`. Peter sleepte 180 bestanden → één ging omhoog. Backend `POST /administraties/{id}/documenten` is per bestand en
loopt al via de extractie-wachtrij (201 < 2 s), dus de server kan dit aan; alleen de zone is enkelvoudig.

## Bouw
1. **Meerdere bestanden**: `<input multiple>` + alle `dataTransfer.files` (ook een gesleepte MAP: `webkitGetAsEntry` recursief);
   soort-keuze (inkoopfactuur/kassarapport/verplichting) geldt voor de hele batch. Toegestane typen zoals nu (PDF, UBL/XML, .eml, foto).
2. **Wachtrij met begrenzing**: max 4 gelijktijdige uploads, rest in de rij; per bestand status wachten → bezig → klaar/fout mét reden
   (409 duplicaat = "al aanwezig: ‹document›" en géén fout, 413 = "te groot", netwerkfout = "opnieuw"); voortgang "37 van 180 · 2 fouten";
   knoppen "Mislukte opnieuw" en "Stoppen" (lopende ronden af, rest niet gestart). Pagina verlaten tijdens een batch = waarschuwing.
   Bestaande dedupe (sha256/UBL-bundel/nabundel) blijft per bestand werken — 180 × dezelfde PDF geeft 1 document + 179 "al aanwezig".
3. **Na afloop**: samenvatting "180 aangeboden · 176 nieuw · 3 al aanwezig · 1 fout" + de lijst ververst één keer (niet per bestand);
   extractie loopt zoals nu via de wachtrij; AI-kostengrens blijft de harde poort (bij bereiken: zichtbaar, rest wacht, nooit stil).
4. **Server**: geen nieuwe route; wel toets dat 180 × POST binnen de Cloud Run-limieten past (request-grootte 32 MB per bestand,
   concurrency) en dat de extractie-wachtrij niet verstopt (meetlat: 180 uploads → alle jobs binnen X min, rapporteer X). Rate-limit-
   melding leesbaar als die er is.
5. Zelfde component op álle upload-plekken (klantpagina, verzamelbak, documentenlijst); guard-test op `multiple` + wachtrij-logica;
   overflow-sweep; WAT_IS_NIEUW ("Je kunt nu honderden bestanden tegelijk slepen").

## Afronding
Gouden set groen (intake-guard); rapport + INDEX + Gelezen regels; nameting ná deploy: 20 testbestanden in één drop op het testaccount
→ 20 documenten, samenvatting klopt ("werkt in productie: ja/nee"). Één regel voor Peter: hoe hij de 180 BLOW-bestanden alsnog in één
keer aanbiedt.
