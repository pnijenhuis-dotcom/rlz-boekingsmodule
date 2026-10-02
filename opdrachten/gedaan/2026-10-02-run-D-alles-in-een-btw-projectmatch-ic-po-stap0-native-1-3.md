> uitgevoerd 02-10-2026 avond (handmatige CC-sessie, zes fork-agenten + coördinator), rapport: docs/rapporten/2026-10-02-run-d.md — blok A–G alle groen; nameting: opdrachten/inbox/2026-10-03-nameting-run-d.md

# Opdracht 02-10 avond — Run D "alles in één" (besluit Peter 02-10 20:1x: "gooi alles maar in 1 run")

Eén run, zeven blokken in deze volgorde, COMMIT PER BLOK (een rood blok stopt alleen dát blok: melden in het rapport, doorgaan met het
volgende). Regel Peter 30-09 blijft: geen bijvangst buiten wat hier staat; wat werkt moet blijven werken (volledige suites per blok).
Bewust NIET in deze run (wachten op input Peter): punten 27/28 verhuur-productgroepen (rekeningvraag open), run B Universal-feedback
(materiaal ontbreekt), Ponto (Jarvis), drift-audit C/E.

LEESPLICHT per blok (volledig lezen vóór dat blok): A btw.md + autoboeken-ai.md + reconciliatie.md; B verplichtingen-projecten-voorraad.md
+ werkvoorraad-controlescherm.md; C werkvoorraad-controlescherm.md + omzet.md; D doorbelasting-intercompany.md + reconciliatie.md +
administraties-instellingen.md; E administraties-instellingen.md + verkenning/odoo-verkenning.md; F accordering-native-app.md +
auth-toegang.md + native/PLAY_DRAAIBOEK.md + native/TESTFLIGHT_DRAAIBOEK.md; G werkloop-productie.md. Altijd: werkloop-productie.md.

## Blok A — btw-verschil < € 0,10 nooit blokkeren (besluit Peter 29-09, casus Lusso 260987: factuur-btw 913,27, tarief 913,33)
Peter 29-09 (letterlijk): "de btw vermeld op factuur is altijd leidend (altijd, wettelijk bepaald). dan moet er geen blokkade komen" en
"als het verschil onder de € 0,10 cent is lekker boeken en niet te druk om maken (wel dan altijd in ons voordeel uiteraard)".
1. Harde check "Btw-bedrag past bij tarief" (18-09): verschil tussen factuur-btw en tarief-berekening per document (Σ regels)
   < € 0,10 = GROEN zonder melding; ≥ € 0,10 = ORANJE mét de twee bestaande acties, NOOIT rood zolang netto + btw = factuurtotaal.
   De factuur-btw blijft wat naar RLZ gaat (geen netto-verschuiving — het netto is ook een factuurfeit; herziet de 25-09-vorm).
2. Autoboek-pad: groen = doorlopen; oranje = weigeren mét reden (bestaand patroon).
3. Reconciliatie: een bedragverschil module ↔ RLZ dat uitsluitend uit RLZ's btw-herrekening per tarief komt (|Δ btw| < € 0,10,
   netto gelijk) = automatisch geaccepteerd mét audit `btw_afronding_rlz` (verbreding van de ≤ € 0,05-regel, alleen voor deze oorzaak).
   "In ons voordeel": als RLZ méér voorbelasting boekt dan de factuur is dat geen bevinding; boekt RLZ MINDER (voorbelasting lager dan de
   factuur), dan LET-OP `btw_rlz_lager_dan_factuur` in `meten` mét bedrag — nooit stil.
4. Test: Lusso-casus (4.349,18 netto, 913,27 factuur-btw) → groen, autoboek door; 0,10-grensgeval beide kanten; reconciliatie-acceptatie.

## Blok B — projectmatch op plaats/opdrachtgever uit de héle factuurtekst, één project per document
Casussen 29-09 (gesprek 29-09, screenshots Peter): Huvanco 7 facturen mét hetzelfde werknummer kregen geen/verkeerd project;
Hoogwerkservice kreeg per REGEL een ander project (regel-geheugen, sinds 02-10 weg). `app/projecten/match.py` kent al code → werknummer →
fuzzy plaats/opdrachtgever, maar werkt op het `proj`-veld van de extractie.
1. De factuur-motor leest de volledige tekst: kop-omschrijving, "betreft"/"werk"/"project"-regels, UBL `cbc:Note`, én de regelomschrijvingen;
   niveau 1–2 ongewijzigd; niveau 3 (plaats + opdrachtgever) wordt deterministisch: plaats-token én opdrachtgever-token moeten BEIDE in
   de projectnaam voorkomen (genormaliseerd), precies één kandidaat = oranje voorstel mét chip "op plaats + opdrachtgever"; meerdere =
   niets + kandidaten in het scherm; alleen plaats of alleen opdrachtgever = niets.
2. Eén project per document is de regel: het kop-project geldt voor alle regels; alleen als regelomschrijvingen zelf verschillende
   werknummers/projectcodes dragen krijgt een regel een eigen project (niveau 1–2 per regel, nooit fuzzy per regel).
3. Werknummer-mapping (`leverancier_werknummer`): een onbevestigde mapping die 3× op rij door een mens bevestigd is wordt bevestigd
   (bestaand app_bevestigd-patroon) — toets dat dit voor Huvanco werkt (zelfde werknummer, zeven facturen).
4. Test op de twee casussen (fixtures uit de gelezen teksten; geen AI).

## Blok C — "Afwijzen…" in het ⋯-menu van het verkoop- en kassarapport-controlescherm
Zelfde dialoog (verplichte reden) en route als de bulkbalk/inkoop; ook op een `klaar_om_te_boeken` ná "Corrigeren…". Gesignaleerd
02-10 (Vastly-nazorg: afwijzen kon alleen via de lijst).

## Blok D — IC-controle Universal: alle 12 richtingen, Verkoop uit Odoo, lees-only + reconciliatieblok
Bron: `docs/rapporten/2026-09-28-ic-universal-stand.md` + `2026-09-28-ic-universal-ontbrekende-inkoop.xlsx` (niet in git) + gesprek 28-09
(Peter: "de verkoop lijkt mij de waarheid"). Vier BV's: Universal Nederland, Steigerbouw, Verkoop (Odoo sinds 01-09, RLZ ervoor), Materiaal.
1. `intercompany_relatie`: alle 12 geordende paren actief, afgeleid uit de identiteiten (KvK) van de vier — automatisch, geen klik;
   `intercompany_tegenpartij`-rijen per administratie voor de drie andere (accordering overslaan) idem automatisch. Audit per rij.
2. Aansluiting per richting (lees-only, dagelijks in blok `intercompany`): verkoopkant = RLZ `SalesInvoices` ∪ `Receipts` (vóór 01-09 voor
   Verkoop) / Odoo `account.move` out_invoice (Verkoop ná 01-09); inkoopkant = RLZ `PurchaseInvoices` / Odoo in_invoice; sleutel =
   genormaliseerd factuurnummer mét én zonder `RLZ-`-prefix (gat B 28-09) + bedrag; uitkomst per richting: verkoop zonder inkoop
   (`ic_inkoop_ontbreekt`, direct `actie`, mét nummer/datum/bedrag en handeling "Factuur opvragen bij ‹BV›" = mail-concept aan de
   boekhoudmail van de verkopende BV voor de ontbrekende PDF/UBL), inkoop zonder verkoop (`ic_verkoop_ontbreekt`, `meten`), bedrag ≠
   (`ic_bedrag_afwijking`, `meten`). Meetlat: querybibliotheek `ic-aansluiting --richting`; CLI lees-only `ic-aansluiting-rapport`.
3. Geen automatische boekingen in dit blok; IC-spiegel (Nederland → Steigerbouw automatisch inboeken) = apart voorstel in het rapport.

## Blok E — Universal Verkoop: leveranciersfactuur ↔ Odoo-inkooporder, STAP-0 (lees-only)
Peter 28-09: "is het dan niet makkelijker de inkooporder gewoon in odoo te blijven maken en de [leveranciers]factuur van onze module te
koppelen aan die inkooporder? … human error eruit". Uitsluitend GET/search_read op company 3: `purchase.order` (+ lines, state, partner,
product), `stock.picking`/`stock.move` (ontvangsten), `account.move` in_invoice mét `purchase_line_ids`/`invoice_origin`; bewijs hoe Odoo
19 een leveranciersfactuur aan een PO koppelt (3-way match: PO-regel → ontvangst → factuurregel, `qty_received`/`qty_invoiced`). Schrijf
`verkenning/odoo-verkenning.md` sectie "PO-koppeling STAP-0 02-10" + ontwerpvoorstel (één pagina, drie opties mét risico's) in het
rapport. GEEN bouw, GEEN write.

## Blok F — native 1.3 (vc7): Android-kluis zelfherstel (bug Peter 02-10, foto IMG_2512: `Opslag-verwijderfout: null`)
1. `AndroidManifest.xml`: `android:allowBackup="false"` + `dataExtractionRules`/`fullBackupContent` die `veilige_opslag` uitsluiten.
2. `VeiligeOpslagPlugin.java`: faalt `opslag()` (MasterKey/EncryptedSharedPreferences-exception) → één keer `deleteSharedPreferences
   ("veilige_opslag")` + opnieuw aanmaken (de inhoud is toch onleesbaar), daarna pas rejecten; foutmelding nooit "null" (`klasse: message`);
   nieuwe methode `herstel` die de kluis expliciet wist (voor de knop).
3. Webcode (`api/appSlot.ts` + SlotOpslagFout-scherm): patroon "verwijder … Opslag-verwijderfout" → melding "App-opslag opnieuw
   instellen" mét knop (roept `herstel` aan, daarna activatieflow), i.p.v. "neem contact op met het kantoor".
4. Versie: marketingversie 1.3 / Android versionCode 7 (train-regel; iOS pbxproj ×2 + `appVersie.ts` + guard), `APP_MIN_RUNTIME_VERSIE`
   ongewijzigd. Bouw de AAB met `native/scripts/bouw_android_release.sh 7 1.3` (JDK/SDK zoals 30-09) en zet het terminal-/klikbestand
   `opdrachten/terminal/2026-10-03-android-vc7-upload.md` klaar (Productie-release zoals 30-09, debug-symbols). Store-upload = Peter
   (bestand > 10 MB). Xcode Cloud bouwt iOS 1.3 automatisch ná de push; indienen pas als Peter dat wil.

## Blok G — CLAUDE.md < 85.000 tekens
Zoals in de besluiten-opdracht beschreven (per-run-details woordelijk naar `docs/regels/<domein>.md`, één regel + verwijzing hier;
guard groen). Geen inhoudelijke wijziging.

## Af (per blok)
Tests + guard op het afwezig-pad; volledige backend-suite, vitest, tsc, doc-guards groen; WAT_IS_NIEUW voor A/B/C/F; BESLISSINGEN-sectie
"RUN D 02-10 — BTW < € 0,10, PROJECTMATCH, AFWIJZEN, IC 12 RICHTINGEN, PO STAP-0, NATIVE 1.3 (Peter 02-10)"; regels-alinea's per domein;
CLAUDE.md één verwijsregel per domein; rapport docs/rapporten/2026-10-02-run-d.md + INDEX + "Gelezen regels" + per blok "werkt in
productie: ja/nee/niet gemeten" + vervolg-nameting `2026-10-03-nameting-run-d.md` (niet vóór 03-10 12:00; dispatch-onderdelen
`btw-afronding`, `project-match`, `ic-aansluiting`). Committen per blok; de Stop-hook pusht beide repo's.
