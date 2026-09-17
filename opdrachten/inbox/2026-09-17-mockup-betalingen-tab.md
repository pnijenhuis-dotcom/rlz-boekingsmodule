# OPDRACHT 17-09 — MOCKUP "Betalingen" (kantoor-tab + accordeur-app), GEEN bouw

**Proces Peter 17-09 (bindend, letterlijk):**
1. "In de Nijenhuis-module een tabje Betalingen. Daar moet ik over alle boekhoudingen kunnen selecteren wie we wanneer gaan betalen
   (volg de openstaande facturen uit de boekhouding). Ik wil hier eerst een mockup van."
2. "Daarna moet iedereen betalingen kunnen klaarzetten (ook kantoormedewerkers)."
3. "Daarna moet de betreffende accordeur (of accordeurs) de betalingen goedkeuren in de app."
4. "Als de laatste laag heeft goedgekeurd moeten betalingen automatisch per bankrekening worden betaald. Niet meer inloggen via
   Mijn ING. Alles centraal."

**Kader (besluit 16-09 22:00 + BESLISSINGEN "BETALEN — EIGENAAR JARVIS …"):** schermen in deze module; betaalmotor + Ponto-client in
Jarvis; deze module blijft de enige schrijver naar RLZ/Odoo, levert `betaalbaar` en ontvangt betaal-events. Bankzijde: PSD2 eist per
bulk een SCA tenzij de bank een zakelijke vrijstelling geeft — dat is een OPEN VRAAG aan Ponto (mail 17-09 in Jarvis
`docs/besluitvoorstellen/MAIL-ponto-sales-activering-2026-09-17.md`). De mockup neemt daar géén standpunt in: toon de flow t/m
"aangeboden aan bank" en één ontwerpnotitie mét twee varianten (a) volautomatisch, (b) één bevestiging per bulk door een gemachtigde.

Pre-feature-ritueel: BESLISSINGEN "RLZ-BETAALSTATUS INKOOPFACTUUR" (`QuickPaymentSelection`), "INCASSO-/BETAALBATCHES UIT RLZ —
STAP-0" (`PaymentBatchInformation`), "BANKSCHERM — ZOEKVELD, BATCH-STAP", "Klant-accorderingsflow", "ACCORDERINGSRONDE
HERBEREKENEN", "GROEPSKENMERK OP ADMINISTRATIE", "GROEPSSALDI", KP7 (administratie = filter, kantoorbreed = norm, één primaire knop
+ ⋯, lege stand = actie). Designpass V2-tokens. UX-review verplicht: past het als nav-regel "Betalingen" naast Bank?

## Op te leveren (alleen mockup, klikbaar, geen backend/frontend-code)
- `mockup/betalingen-kantoor.html` — desktop:
  - **Tab Betalingen, kantoorbreed**: alle open inkoopfacturen (RLZ `PaymentItems` open / Odoo open moves) over álle administraties in
    scope; kolommen administratie · crediteur · factuurnr · factuurdatum · vervaldatum · bedrag · open · bankrekening (afzender, uit
    `PaymentAccounts`) · IBAN begunstigde · status (betaalbaar / klaargezet / ter goedkeuring laag n/m / goedgekeurd / aangeboden /
    uitgevoerd / geweigerd / al betaald in RLZ) · signalen (dubbel-betaald-vermoeden, G-rekening-splitsing, ontbrekende IBAN, na
    vervaldatum). Filters: groep, administratie, vervalt vóór ‹datum›, status; zoekveld; sorteer op urgentie (vervaldatum) default.
  - Selectie + "Klaarzetten (n) · € …" mét gewenste uitvoerdatum (default vervaldatum, min. morgen); systeem groepeert per
    administratie × afzend-bankrekening tot één bulk; restant-balk "n facturen · € … in m bulks".
  - Detail bulk: regels, totaal, uitvoerdatum, tijdlijn (klaargezet door · laag 1 akkoord · laag 2 akkoord · aangeboden · status
    bank), audit-verwijzing, "Intrekken…" mét reden zolang niet aangeboden.
  - Lege stand: "Geen open facturen" + link naar werkvoorraad.
- `mockup/betalingen-accordeur.html` — mobiel ≤ 430 px in de bestaande accordeur-app-stijl (`mockup/accordeur.html`): wachtrij
  "Betalingen goedkeuren" per bulk (administratie, aantal, totaal, uitvoerdatum), uitklap per factuur mét PDF-link, knoppen Goedkeuren
  / Afkeuren mét reden / Factuur uit bulk halen; lagen zichtbaar ("jij bent laag 2 van 2"); ná laatste akkoord tekst "wordt op
  ‹datum› aangeboden aan ‹bank›".
- Ontwerpnotities onderin (onderdeel van het akkoord): ① goedkeuringslagen = hergebruik accorderingsroutes per administratie (incl.
  leverancierslaag 17-09) of eigen betaalroute? — beslispunt; ② wie mag klaarzetten (alle kantoorrollen) en wie intrekken; ③ dubbel-
  betaald-poort: al `QuickPaymentSelection` ≠ open óf bankmutatie gevonden = niet selecteerbaar; ④ G-rekening = twee regels in de bulk;
  ⑤ SCA-variant (a)/(b) zie kader; ⑥ terugkoppeling: event `betaling_uitgevoerd` → RLZ "Betaald per bank" + afletteren via batch-stap.
- Rapport `docs/rapporten/2026-09-17-mockup-betalingen.md` + INDEX; BESLISSINGEN registerrij "BETALINGEN — MOCKUP (Peter 17-09)"
  status TER AKKOORD; geen migratie, geen code.
