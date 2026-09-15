uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-accordeur-pdf-zoom.md

VERBETERING ACCORDEUR-APP (Peter 15-09) — inzoomen op de factuur

Nu: `frontend/src/accordeur/PdfWeergave.tsx` rendert pagina's als canvas (pdf.js) op containerbreedte × devicePixelRatio en vertrouwt op "native paginazoom". In de native app (Capacitor WebView, viewport niet schaalbaar) en in de PWA-standalone werkt knijpen op de pagina niet of scrollt de hele app mee → gebruikers kunnen kleine lettertjes niet lezen.
1. Eigen zoom in de PDF-weergave: knijpzoom (pointer events, 1×–4×) + dubbeltik = 2× op de tikplek + pannen binnen het canvas; de rest van het scherm scrolt niet mee; knop "⤢ Volledig scherm" opent de factuur fullscreen (alle pagina's, zoom + pannen, sluitknop + terug-gebaar), zodat het goedkeurscherm zelf compact blijft. Renderen op de hoogste gebruikte schaal (scherp blijven bij 3–4×, geheugen begrensd: hoogstens de zichtbare pagina ±1 op hoge schaal).
2. Zelfde component voor de veldwerker-weergaven die PDF's tonen (werkbonnen/offertes in de app) — één bron.
3. Test op iOS (Safari/WebView) én Android via de bestaande kliktest-recepten; vitest op de gebaar-wiskunde (schaal, clamp, focuspunt). Mockup niet nodig (bestaand scherm, één knop erbij); UX-notitie in het rapport.
4. Rapport docs/rapporten/2026-09-15-accordeur-pdf-zoom.md + INDEX; WAT_IS_NIEUW ("je kunt nu inzoomen op de factuur"); BESLISSINGEN-regel onder accordeur-app; app-build: markeringsversie ongewijzigd, build volgt Xcode Cloud/AAB-flow uit de draaiboeken (noteer welke build het bevat). Dit bestand naar gedaan/.
