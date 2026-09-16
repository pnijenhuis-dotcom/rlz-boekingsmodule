> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-vragen-dialoog.md

# OPDRACHT 16-09 — Vragen-dialoog: meerdere berichten achter elkaar, van beide kanten, tot "Afgehandeld" (feedback Peter 16-09)

**Aanleiding (Peter 16-09, casus Barbara → accordeur Sophia):** "Barbara heeft aan accordeur Sophia een vraag gesteld, die
heeft antwoord gegeven. Sophia wil daarop nog wat typen, maar dat kan pas als Barbara weer heeft gereageerd. Eigenlijk moet
die chat open blijven staan zodat meerdere berichten achter elkaar gestuurd kunnen worden (niet dicht na antwoord)."

Pre-feature-ritueel: BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt B (DIALOOG-model: een vraag is een thread, blokkeert boeken
tot "Afgehandeld" door de oorspronkelijke vraagsteller; migratie 0064), "GECOMBINEERDE RUN 26-08" blok B (vraag aan de
klant-accordeur, B5, migratie 0079), "LEEG = DOORLOPEN — TOEWIJZING OPTIONEEL", "ACCORDEUR-NOTIFICATIES",
"NIEUWE-FACTUREN-BUNDELMELDING"; mockup `accordeur-vragen.html`; `app/vragen/`, accordeur-app vraagscherm, kantoor-web
vraagpaneel in het controlescherm.

## Wortel (eerst vaststellen, dan fixen)
Ergens ligt een beurt-regel: ná een antwoord van de accordeur staat de thread op "wacht op kantoor" en is het invoerveld voor
de accordeur uit (of de route weigert een tweede bericht van dezelfde kant). Bepaal waar: statusmachine (`beantwoord`-status
die het veld sluit), route-guard ("laatste bericht is al van jou"), of alleen UI. Documenteer in het rapport; de fix is in
alle drie de lagen consistent.

## Te doen (geen migratie, tenzij een status-enum moet groeien)
1. **Thread blijft open voor beide kanten tot "Afgehandeld".** Iedere deelnemer (vraagsteller, geadresseerde, andere
   kantoormedewerkers mét scope) kan zoveel berichten achter elkaar plaatsen als hij wil; geen beurt-regel meer. Het enige
   dat de thread sluit is "Afgehandeld" door de oorspronkelijke vraagsteller (bestaand besluit 25-08, ongewijzigd) —
   kantoor kan een vraag ook namens de vraagsteller afhandelen als die afwezig is (Beheerder/zelfde administratie-scope,
   audit "afgehandeld namens").
2. **Status wordt afgeleid, niet gezet:** `open · wacht op <kant>` = wie het laatste bericht NIET schreef; het blijft één
   status `open` mét afgeleide badge "laatste bericht van Sophia · 12:14". Bestaande statussen `gesteld`/`beantwoord`
   samenvouwen naar open + afgeleide kant (data-stap: geen verlies — de tijdlijn houdt de berichten). Werkvoorraad-tab
   "Vragen"/"Wachten op anderen" telt op de afgeleide kant (kantoor aan zet vs klant aan zet), zodat de teller blijft
   kloppen.
3. **Meldingen bundelen:** meerdere berichten kort na elkaar van dezelfde kant = één push/mail ("Sophia: 3 nieuwe berichten
   over factuur …", bestaand bundelpatroon 10 min), nooit per bericht. Geen melding naar de schrijver zelf.
4. **UI kantoor + accordeur-app:** invoerveld altijd zichtbaar zolang open; berichten chronologisch mét naam/tijd, eigen
   berichten rechts; "Afgehandeld"-knop alleen voor de vraagsteller (+ "namens" voor Beheerder); ná afhandelen alleen-lezen
   mét "Heropenen" (bestaand? anders: heropenen = nieuwe status open, audit). Enter = nieuwe regel, Cmd/Ctrl-Enter = versturen;
   optimistisch tonen, foutstand zichtbaar (geen stil verlies van een getypt bericht — concept lokaal bewaren bij
   verbindingsfout, PWA-koude-start-regel).
5. **Boeken blijft geblokkeerd** zolang de vraag open is (harde check ongewijzigd); het antwoord voedt het geheugen zoals nu
   (alleen bij Afgehandeld).
6. Tests: statusmachine (meerdere berichten zelfde kant, afgeleide kant, afhandelen alleen door vraagsteller/namens),
   route-guards weg mét rolpoort-tests (accordeur mag alleen in eigen administratie-thread), bundelmelding, frontend beide
   apps (invoerveld blijft, badge), gouden-set-casus met vraag-thread (bestaande casus uitbreiden). Backfill-test voor de
   statusvouw.
7. BESLISSINGEN aanvulling onder "RLZ-FEEDBACKRONDE 25-08" punt B ("DIALOOG OPEN TOT AFGEHANDELD — Peter 16-09"), CLAUDE.md
   verwijsregel bijwerken, WAT_IS_NIEUW (klantleesbaar: "je kunt nu meerdere berichten achter elkaar sturen"), rapport
   `docs/rapporten/2026-09-16-vragen-dialoog.md` + INDEX (wortel in twee zinnen bovenaan; meetrecept: Barbara/Sophia-thread
   ná deploy — Sophia kan direct een tweede bericht plaatsen). Werkt in productie: niet gemeten. Accordeur-app-deel = nieuwe
   app-build via de bestaande flow (PWA direct).
