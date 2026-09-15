# Goedkeur-app: inzoomen op de factuur (Peter 15-09)

**In gewone taal:** In de app kon je niet inzoomen op de factuur: knijpen werkte niet in de native app en in de PWA scrolde het hele
scherm mee. De factuurweergave heeft nu een eigen zoomlaag (knijpen tot 4×, dubbeltik = 2×, slepen om te schuiven; de rest van het
scherm blijft staan) en een knop "⤢ Volledig scherm". Dezelfde weergave geldt voor werkbonnen en offertes in de veld-app.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; toesteltest iOS/Android nog te doen — meetrecept hieronder).

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1 | Gebaar-wiskunde puur en getest: schaal-clamp 1×–4×, zoom rond een focuspunt, knijp, dubbeltik, pan, verschuiving binnen het vak, renderstap | `frontend/src/accordeur/pdfZoom.ts` (+ 6 tests) |
| 1 | Component: pointer events op een klippend vak, `transform` op de inhoud, `touch-action: none` zodra ingezoomd (de rest scrolt niet mee), "N % · terug", hertekenen op de hoogst gebruikte zoomstap × devicePixelRatio (alleen zichtbare pagina's ±1 op hoge stap — geheugen begrensd); "⤢ Volledig scherm" = vaste overlay met dezelfde component, sluiten via ✕, Escape of de terug-gebaar (history) | `PdfWeergave.tsx`, `accordeur.css` (+ 3 tests, pdf.js gemockt) |
| 2 | Eén component: GoedkeurenFlow (factuur) én UrenFlow (werkbonnen/offertes) gebruiken `PdfWeergave` ongewijzigd | bestaande aanroepers |
| 3 | Toesteltest iOS/Android: NIET uitgevoerd in deze run (geen toestel/simulator); recept hieronder. Vitest op de gebaar-wiskunde en de component groen | — |

## UX-notitie

Bestaand scherm, één knop erbij; het goedkeurscherm blijft compact (vak max 55 vh) en fullscreen is de leeshouding. Bewust geen
+/−-knoppen: op een telefoon zijn knijpen en dubbeltik de norm, muisgebruikers hebben de browserzoom. Op 1× blijft het vak gewoon
verticaal scrollen (pan-y); pas ingezoomd neemt de zoomlaag de gebaren over.

## App-build

Marketingversie ongewijzigd (1.1). De wijziging zit in de web-bundel: de PWA heeft 'm direct ná de deploy; de native schil krijgt 'm
bij de eerstvolgende Xcode Cloud-build (start automatisch bij de push van main — het buildnummer volgt uit CI_BUILD_NUMBER, zie
TESTFLIGHT_DRAAIBOEK §0f) en bij een nieuwe Android-AAB volgens PLAY_DRAAIBOEK. In deze run is geen build gestart.

## Meetrecept (Peter, ná deploy)

1. PWA op de telefoon: factuur openen → knijpen zoomt tot 4×, de pagina schuift mee onder de vingers, kop en knoppen blijven staan;
   dubbeltik = 2× op die plek, nog een dubbeltik = terug; "⤢ Volledig scherm" → hele scherm, ✕ of de terug-gebaar sluit.
2. Native app (TestFlight/Play) ná de volgende build: zelfde gedrag in de WebView; tekst blijft scherp op 3–4×.
3. Veld-app: werkbon/offerte openen → zelfde zoom + fullscreen.
