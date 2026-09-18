uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-webtoestel-edge-android.md

Domeinen: auth-toegang, accordering-native-app

# SPOED 18-09 — Web-app (Edge op Android-tablet) "logt steeds uit" bij een net uitgenodigde uitvoerder

**Melding Peter 18-09 (letterlijk):** "web app edge logt steeds uit?" Context: vandaag een uitvoerder uitgenodigd, geactiveerd als
WEB-toestel op een Android-tablet in Microsoft Edge (geen store-app: Play-versie met app-auth nog in review).

## Blok A — Diagnose op DATA eerst (lees-only; geen oorzaak zonder logregel)
1. Vind de gebruiker: laatste `POST /auth/app/activeren` van vandaag met een Edge/Android User-Agent (audit + request-log).
2. Reconstrueer de tijdlijn van dat toestel: activatie → elke `/auth/app/…`-refresh/verlenging → élke 401/410/426 mét reden
   (`toestel_onbekend`, `token_verlopen`, `kill_switch`, legacy-route) → nieuwe activatie-/koppelpogingen. Wordt de sessie
   SERVER-side afgewezen (dan staat de reden in onze log) of komt de client zonder token terug (dan is de opslag op het toestel weg
   — Edge "browsegegevens wissen bij afsluiten", tracking-preventie strikt, tabblad-opslag i.p.v. geïnstalleerde PWA, storage
   eviction)? Tel hoe vaak per dag en na hoeveel minuten sinds de laatste activiteit.
3. Toets de client-kant in code: waar bewaart de web-flow het toestel-token en het toegangscode-anker (localStorage/IndexedDB),
   werkt dat in Edge-Android als gewoon tabblad vs. geïnstalleerde PWA, en wat doet de app als `navigator.storage.persist()` weigert.
   Reproduceer in een Edge-Android-emulatie (Playwright, UA + storage-partitionering) — bewijs met een test, geen vermoeden.
4. Rapporteer per punt mét bron (audit-id/tijdstip/UA/statuscode). Als de oorzaak Edge-instellingen zijn: exact welke instelling.

## Blok B — Fix (afhankelijk van A)
- Server-side reden (TTL, sliding niet verlengd, refresh-race, kill-switch onbedoeld) → fix + guard-test.
- Client-side opslagverlies → (1) `navigator.storage.persist()` aanvragen bij activatie en een zichtbare waarschuwing als het
  weigert; (2) na activatie in een browser de gebruiker actief naar "Zet op je beginscherm" (PWA-installatie) leiden, mét
  Edge-/Chrome-specifieke instructie; (3) verlies van het token = géén stil uitloggen maar een scherm "Je toestel is niet meer
  gekoppeld — opnieuw koppelen" met de zelfservice-koppelcode van een ander toestel of "kantoor om een herstel-link vragen";
  (4) diagnoseregel in ⚙ Toegang: opslag persistent ja/nee, laatste tokenverlenging, browser/PWA-modus (lokaal, nooit naar de server).
- Herstel-/uitnodigingsmail voor Android zonder store-link: één zin "Zet de web-versie op je beginscherm" met de stappen.

## Afronding
Gouden set/veld-app-tests groen; WAT_IS_NIEUW alleen als gebruikersgedrag wijzigt; docs/regels/auth-toegang.md; rapport + INDEX +
"Gelezen regels"; nameting ná deploy: het toestel van deze uitvoerder blijft ≥ 24 u ingelogd (audit toont verlengingen zonder
heractivatie) — "werkt in productie: ja/nee". Eén regel voor Peter: wat de uitvoerder nu op de tablet moet doen.
