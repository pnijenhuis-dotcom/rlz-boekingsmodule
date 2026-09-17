"""Eenmalige data-stap 17-09 (opdracht "CLAUDE.md: volledige regels per domein in docs/regels/, verplicht gelezen vóór werk"):
verhuist de domeinblokken van CLAUDE.md WOORDELIJK naar docs/regels/<domein>.md, laat per domein één compact blok mét
LEESPLICHT achter, en kopieert de op 07-09 naar BESLISSINGEN verplaatste CLAUDE.md-tekst naar dezelfde regelsbestanden
(de kopie in BESLISSINGEN blijft staan als historie). Bewijs dat geen tekst verloren ging: élke verhuisde alinea is als
substring terug te vinden in het doelbestand én de woordtelling sluit (vóór = ná − nieuwe blokken + verhuisde tekst).

Draaien vanuit de repo-root: `python3 scripts/eenmalig/claude_md_regels_splitsen_17-09.py` (idempotent: weigert als
docs/regels/INDEX.md al bestaat). Bewaard als bewijsstuk van de splitsing, niet als terugkerend gereedschap."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE = REPO / "CLAUDE.md"
BESLISSINGEN = REPO / "docs" / "BESLISSINGEN.md"
REGELS = REPO / "docs" / "regels"

# ---- domeinen: slug → (titel, wat het is, hoofdregels (3–5 regels), code-paden) ------------------------------------------
DOMEINEN: dict[str, dict] = {
    "werkvoorraad-controlescherm": {
        "titel": "Werkvoorraad, documentenlijst en controlescherm",
        "wat": "Klantenlijst met tellers → documentenlijst → controlescherm; boekingsgeheugen, vragen, afwijzen, doorloop na boeken, kalenderdag, zoeken/archief.",
        "regels": [
            "Administratie is een FILTER, nooit een poort; de standaardlijst is kantoorwerk (`geboekt`/afgehandeld onder één toggle, \"Wachten op anderen\" apart).",
            "Boekingsgeheugen: seed-only = oranje, eerste app-bevestiging = groen, recency wint (drie identieke mens-boekingen); automatische boekingen schrijven geen observatie.",
            "Controlescherm auto-first: kop-omschrijving, projectnummer en prefill deterministisch en direct persistent; mens wint altijd als tijdlijn-override.",
            "Vraag = dialoog die boeken blokkeert tot \"Afgehandeld\"; afwijzen = verplichte reden; niets verdwijnt stil; datums/dagtellers = NL-kalenderdag via `app/tijd.py`.",
        ],
        "paden": ["backend/app/werkvoorraad/**", "backend/app/documenten/**", "backend/app/geheugen/**", "backend/app/vragen/**", "backend/app/zoeken/**", "backend/app/tijd.py", "frontend/src/werkvoorraad/**", "frontend/src/document/**", "frontend/src/vragen/**", "frontend/src/zoeken/**", "frontend/src/api/**"],
    },
    "kantoor-frontend": {
        "titel": "Kantoor-frontend: IA, designpass, componenten, changelog",
        "wat": "Tailwind v4 + tokens, designpass v2 (teal = actie, groen = status), instellingenRegistry fail-closed, Gebruikers & toegang-tabel, overflow-sweep, \"Wat is nieuw\".",
        "regels": [
            "Élk nav-item/élke tab heeft een registry-entry; nieuwe module = nav-regel en/of tab, nooit een tegel; geen horizontale pagina-overflow (sweep).",
            "Contrast is een test (beide modi); tekstknop = `linkbtn`, echte knop = `btn`/`btn secondary`; nooit een kale `<button>`; comboboxen i.p.v. kale selects.",
            "\"Wat is nieuw\" (`WAT_IS_NIEUW.md`) VERPLICHT bijvullen bij élke feature-commit, klantleesbaar, nieuwste bovenaan.",
        ],
        "paden": ["frontend/src/shell/**", "frontend/src/ui/**", "frontend/src/styles/**", "frontend/src/changelog/**", "frontend/src/dev/**", "frontend/src/*.tsx", "frontend/src/*.ts", "frontend/src/*.css", "mockup/**"],
    },
    "administraties-instellingen": {
        "titel": "Administraties, RLZ-/Odoo-koppelingen, sync en instellingen",
        "wat": "Instellingen › Administraties (archiveren, nooit verwijderen), wizard mét rechten-probe, eerste sync, RLZ-check, groepen, administratienaam volgt de bron, Odoo-koppelwizard, terugkerend-signaal, verplaatsen.",
        "regels": [
            "Rechten-probe = de eerste-sync-routes (één bron `app/rlz/leesroutes.py`), altijd óók met de OPGESLAGEN login; 403 ná groene probe = herproberen (max 24 u), nooit stil.",
            "Dubbele Odoo-koppeling is een failsafe in drie lagen; VGG company 6 = migratiedoel, nooit een nieuwe administratie; URL-normalisatie via `app/odoo/ids.py`.",
            "Groep = filter (hoogstens één per administratie); naam met `naam_bron` ≠ mens volgt de bron; verplaatsen loopt via de SECURITY DEFINER-functie mét expliciete RLS-policy.",
        ],
        "paden": ["backend/app/beheer/**", "backend/app/groepen/**", "backend/app/sync/**", "backend/app/rlz/**", "backend/app/odoo/**", "backend/app/backends/**", "backend/app/integraties/**", "backend/app/registersync/**", "backend/app/credentialstore/**", "backend/app/terugkerend/**", "frontend/src/instellingen/**", "frontend/src/terugkerend/**"],
    },
    "auth-toegang": {
        "titel": "Auth, rollen, scope, RLS, app-auth en gebruikersbeheer",
        "wat": "Kantoor: e-mailuitnodiging + wachtwoord + TOTP, passkeys eerste lijn (0020); app-rollen: toestelbinding + toegangscode zonder passkey (0029); RLS + `vereis_kantoorrol`-poorten; Gebruikers & toegang; herstel-links; mails en push.",
        "regels": [
            "Niemand muteert zijn eigen rol/scope; élke rol-/scope-wijziging in het audit_event; geen scope = geen data (RLS + server-side); élk kantoor-endpoint draagt een rolpoort (fail-closed sweep).",
            "Scope-lookups op `gebruiker_administratie` altijd in `scoped_session(<administratie>, actor_id=actor)`; SECURITY DEFINER omzeilt FORCE RLS niet — expliciete policy-uitzondering + niet-eigenaar-test.",
            "Maillinks zijn deep-links naar de app-flow; goedkeuren-zonder-inloggen bestaat niet; een activatie-/herstel-link laat in een browser EERST kiezen (app op deze telefoon / web) vóór er iets verzilverd wordt; versie-eis (≥ 1.1) letterlijk in de mail.",
            "Wachtwoord kwijt = Beheerder-knop \"Herstel-link sturen\" (nooit selfservice); legacy-app-routes 410 ná 2026-10-08.",
        ],
        "paden": ["backend/app/auth/**", "backend/app/security/**", "backend/app/berichten/**", "frontend/src/auth/**", "frontend/src/gebruikers/**"],
    },
    "btw": {
        "titel": "Btw: codes, defaults, verlegd, buitenland",
        "wat": "Btw-code uit de scan en het factuurtotaal, defaults uit de RLZ-grootboekrekening en de eigen historie, verlegd-herkenning (vermelding, kolomcode, onderaannemer), buitenland-signaal, verlegd-tarief deterministisch.",
        "regels": [
            "Winnaarsvolgorde btw (`regel_prefill.py`): mens > factuur berekend > geheugen > factuur verlegd > grootboek-default (RLZ) > grootboek-historie > administratie-default > leeg; 0/onbepaalbaar/meerduidig = NOOIT invullen.",
            "Verlegd = (vermelding óf kolomcode óf verlegd-leverancier) ÉN factuur-btw 0; 0 % zonder basis blijft leeg (vrijgesteld ≠ verlegd); verlegd-tarief: voorkeur per administratie → meest gebruikt in historie → bestaand pad → default, mét herkomst-chip.",
            "Cent-fix aan de bron (`regelsom.py::corrigeer_btw_centen`) alleen in wat naar RLZ gaat; foutvertaling `vertaal_rlz_boekfout` voor buitenlandse crediteuren.",
        ],
        "paden": ["backend/app/extractie/controle.py"],
    },
    "duplicaten-crediteuren": {
        "titel": "Duplicaten en crediteuren",
        "wat": "Harde check \"Duplicaat (module)\", auto-afvoer, status `afgevoerd_duplicaat`, RLZ-/Odoo-bestaanscheck, referentie-normalisatie, nabundel-motor, crediteur-dedup en dubbelen-clusters, bulk-afvoer, medewerker-wensen 04-09.",
        "regels": [
            "Duplicaten eruit, geen lijst: cent-exact/genormaliseerde referentie over álle crediteurrecords; UBL+PDF = bundel, nooit duplicaat; byte-identieke exemplaren uit één bericht = `samengevoegd`; nooit verwijderen, altijd terugdraaibaar met reden.",
            "Al geboekt in RLZ/Odoo (zelfde referentie) = blokkerend mét boekstuk; zelfde bedrag+datum = oranje; geen credential = zichtbaar overgeslagen.",
            "Eenduidige crediteur-clusters (btw/KvK; N = 3) handelt het systeem af; verliezers zijn in de module onbruikbaar via `crediteuren/voorkeur.py`; alles telt in geen werkvoorraad-teller maar blijft terugvindbaar (Archief/Zoeken).",
        ],
        "paden": ["backend/app/crediteuren/**", "frontend/src/crediteuren/**"],
    },
    "intake-extractie": {
        "titel": "E-mail-intake, verzamelbak, splitsing en AI-extractie",
        "wat": "Eén intake-adres, splitsen op factuurgrenzen, toewijzen op tenaamstelling, verzamelbak \"Niet toegewezen\", één extractiepad achter de AVG-/API-key-/kostengrens-gates, deterministische templates, UBL deterministisch, wachtrij-trigger, union-limiet.",
        "regels": [
            "Nooit auto-toewijzen bij twijfel; tenaamstelling leidend, afzender = hint; \"hoort niet bij ons\" met reden; verzamelbak leert van handmatige toewijzingen.",
            "AI alleen voor extractie/segmentatie, altijd met deterministische checks eroverheen; kostengrens € 100/maand is een harde poort, boven de grens nooit stil; schema's ≤ 16 unions, nieuwe velden sentinel-gebaseerd.",
            "UBL is deterministisch (kop, crediteur, regels, datums uit de XML); template-terugval per bekende leverancier: één rood = volledig verworpen; élke extractie loopt via de wachtrij (201 < 2 s).",
        ],
        "paden": ["backend/app/intake/**", "backend/app/extractie/**", "backend/app/aikosten/**", "frontend/src/intake/**"],
    },
    "autoboeken-ai": {
        "titel": "Automatisch boeken, autoboek-kandidaten en de AI-plausibiliteitstoets",
        "wat": "Opt-in per leverancier en per administratie (leren ná drie identieke mens-boekingen), harde checks blijven blokkerend, volumerem, AI-toets als extra poort mét uitval = doorlopen zichtbaar, autonomie-toekomstlijn.",
        "regels": [
            "Automatisering-first: mens-op-de-knop is een testfase-drempel; elk deterministisch pad krijgt een autoboek-opt-in volgens het vaste patroon (default UIT, harde checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg).",
            "Geen LLM in geldberekeningen; AI kiest nooit een rekening zonder deterministische toets; AI-uitval = doorlopen zonder AI, zichtbaar (chip + LET-OP); `twijfel` = niet boeken.",
            "Status per harde check is canoniek in BESLISSINGEN \"Harde/blokkerende checks\" — gedocumenteerd ≠ gebouwd.",
        ],
        "paden": ["backend/app/autoboek_kandidaten/**", "backend/app/aitoets/**"],
    },
    "reconciliatie": {
        "titel": "Reconciliatie, bewaking en meldingen",
        "wat": "Dagelijkse reconciliatie-blokken (documenten, bank, omzet, doorbelasting, intercompany, RC, rlz_dubbel, dubbele betaling), tellers per automatisering, actiemail + systeemmail, synthetische bewaking, bevindingssoorten in `meten`.",
        "regels": [
            "Signalering zonder handeling is niet af: élke bevinding draagt een actie; kantoor krijgt alleen een ACTIEMAIL bij bevindingen mét handeling; systeemmail alleen bij LET-OP/systeemfout; regressies = \"systeemfout — automatisch gemeld\" + audit.",
            "Élke nieuwe bevindingssoort start in `meten` (facet \"in meting\", nooit actiemail/KPI) tot Beheerder-promotie; explosie-rem > 50/run → terug naar meten; verdwenen bevindingen sluiten mét audit.",
            "Verdwenen extern document = `ontbreekt_in_rlz/odoo` mét \"Opnieuw boeken\" achter de aangiftepoort (suppletie-pad, Beheerder); bedragverschil ≤ € 0,05 = automatisch geaccepteerd mét audit.",
        ],
        "paden": ["backend/app/reconciliatie/**", "backend/app/bewaking/**", "frontend/src/reconciliatie/**"],
    },
    "verplichtingen-projecten-voorraad": {
        "titel": "Verplichtingen/offertes, projecten, projectverdeling, contract-ontleding en voorraad",
        "wat": "Documenttype `verplichting` + factuur↔offerte-match (nooit blokkerend), projectenmodule en projectcode-generatie, Inzicht › Projecten/Projectverdeling, pro rato, contract-ontleding auto-first, mini-voorraad en voorraad-aansluiting (mi-schema, nooit RLZ-writes).",
        "regels": [
            "Project verplicht = hard blokkerend zonder \"geen project\"-optie; overhead → intern OVH-project; projectcode volgt de naamconventie van de klant en synct naar RLZ.",
            "Match-motor deterministisch; wachtende verplichting = `niet_toetsbaar` mét verwijzing, nooit stil `geen_verplichting`; goedkeuring matcht ook geboekte facturen achteraf (tijdlijn + audit).",
            "Contract-ontleding schrijft specs/staffels direct met herkomst `contract` (correctie → `mens`); voorraadstand = Σ append-only mutaties, mens-manipulatie onmogelijk.",
        ],
        "paden": ["backend/app/verplichting/**", "backend/app/projecten/**", "backend/app/projectverdeling/**", "backend/app/mini_voorraad/**", "backend/app/voorraad/**", "frontend/src/verplichting/**", "frontend/src/projecten/**", "frontend/src/projectverdeling/**", "frontend/src/voorraad/**"],
    },
    "uren-planning-veldwerkers": {
        "titel": "Uren & meerwerk, planning, werkopdrachten, veldwerkers",
        "wat": "Steigerbouw-tak (opt-in per administratie): weekstaat per project, hybride keuring, factuurmatch, ZZP-dossier + KvK, planning-agenda mét urenstatus, transport, werkopdrachten, Beheer › Veldwerkers, materiaal.",
        "regels": [
            "Nieuwe module-code roept nooit `RlzClient` aan (seam-eis; adapter-grepen in BESLISSINGEN \"ODOO-ADAPTER — GREPEN\"); geofence-native alleen op `feat/geofence-native`, nooit mergen/releasen.",
            "Recht 'veldwerkerbeheer' dekt overzicht, koppelingen en dossier binnen de eigen scope (server-side + RLS); rechten toekennen blijft Beheerder-only.",
            "Planning in een verstreken/lopende week = audit `achteraf` + één gebundelde melding per veldwerker × week; urenstatus in het grid uit de weekstaat.",
        ],
        "paden": ["backend/app/uren/**", "backend/app/materiaal/**", "frontend/src/uren/**", "frontend/src/meerwerk/**", "frontend/src/planning/**", "frontend/src/veldwerkers/**", "frontend/src/materiaal/**"],
    },
    "omzet": {
        "titel": "Omzetboekingen, omzetbronnen en het verkoopfactuur-boekpad",
        "wat": "Kassarapporten (ProfX, dagstaat/kascheck, pilates-export) als entity-loze Receipts mét binder Inkomsten + kostprijsmemoriaal, stores → administratie platformbreed, tegenzijde per betaalwijze, Vastly-verkoopfacturen (§2d), waarborg.",
        "regels": [
            "Kasomzet = losse boeking (geen dummy-debiteur); categorie op BINDER Inkomsten, niet op naam; bron-parsers deterministisch (géén AI, geen AVG-gate); harde bron-controles als check-rijen.",
            "BLOW cannabisomzet = \"NL, Geen BTW (Vrijgesteld)\", bewust géén 0 %-tarief; punten = omzet 21 %; Stripe = EU-dienst verlegd; combi pro rato oranje.",
            "Onbekende store → verzamelbak `omzetbron_store_onbekend` + \"Stores koppelen →\"; kassarapport in de inkoopstroom = dagelijkse bevinding mét \"Type wijzigen → kassarapport\".",
        ],
        "paden": ["backend/app/omzet/**", "backend/app/verkoop/**", "backend/app/waarborg/**", "frontend/src/omzet/**", "frontend/src/verkoop/**", "frontend/src/waarborg/**"],
    },
    "bank": {
        "titel": "Bank: sync, matchmotor, afletteren, splitsen, batches",
        "wat": "Bank-sync automatisch (07:00) zonder knoppen, voorstel-volgorde exact → gedeeltelijk → vaste regel/historie-regel → RLZ-voorstel → handmatig, afletteren via actie 15 op de PaymentTransaction, batch-stap, open bedrag als maat, zoekveld, Ponto = Jarvis.",
        "regels": [
            "GROEN (auto-afletteren) = teken + naam/IBAN + nummer (heel token; RLZ-volgnummer óf klantreferentie) + bedrag cent-exact; ORANJE = geen teken-mismatch + twee van drie; label `bron` zegt wat matchte.",
            "Open bedrag stuurt alles (voorstellen, boeken = dekking exact, splitsen); afgeletterd toets je op `OpenAmount`, nooit op `IsComplete`; terugdraaien = storno 19 (type 16 ontkoppelt nooit).",
            "Historie-regel (IBAN + omschrijvingskern, ≥ 6 mnd, ≥ 3 boekingen) alleen automatisch bij 100 % en zonder open posten; afletteren gaat NIET door de klant-accorderingsflow.",
        ],
        "paden": ["backend/app/bank/**", "frontend/src/bank/**"],
    },
    "doorbelasting-intercompany": {
        "titel": "Kempen-doorbelasting en intercompany",
        "wat": "Tweezijdige motor bron-verkoop + spiegel-inkoop (\"Boeken + doorbelasten\"), whitelist + doelentiteiten, IC-vlag, tegenboek-pad ná ingediende aangifte, aansluiting KF ↔ doelentiteiten, herkoppeling, intercompany slaat klant-accordering over.",
        "regels": [
            "Storno-blokkade ná een ingediende aangifte (`app/rlz/aangifte.py`) → TEGENBOEK-PAD; `DoorbelastingInstelling.standaard()` is de ENIGE bron voor de niet-opgeslagen standaardstand.",
            "Herkoppeling van whitelist-rijen zonder doel alleen op exacte genormaliseerde naam; bijna-match/meerdere = LET-OP, nooit raden; doorbelastingspaar rood in de reconciliatie = systeemfout.",
            "IC-leverancier (actieve rij in `intercompany_tegenpartij` van de administratie van het document) in een administratie mét klant-accordering → géén ronde, direct de boekstap, tijdlijn + audit.",
        ],
        "paden": ["backend/app/doorbelasting/**", "backend/app/intercompany/**", "frontend/src/doorbelasting/**"],
    },
    "accordering-native-app": {
        "titel": "Klant-accordering, accordeur-/veldwerker-app, native store-apps en OTA",
        "wat": "Sequentiële lagen mét drempels (administratie-, afdelings- en leveranciersroute), herberekening bij configuratiewijziging, staande goedkeuring alleen bij een periodiek patroon, wachtrij set-based, PWA + iOS/Android-schil, OTA self-hosted per runtime, 426-poort, store-draaiboeken.",
        "regels": [
            "Ná het laatste akkoord blijft het document op ter_accordering tot de boeking staat; harde checks draaien opnieuw; compleet klant-akkoord kan niet opnieuw ter accordering.",
            "Voorrang afdelingsroute > leveranciersroute > administratieroute; één route per leverancier (409); herberekenen i.p.v. vervallen.",
            "Train-regel: ná élke store-goedkeuring de marketingversie ophogen vóór de volgende push; OTA registreert per RUNTIME; `APP_MIN_RUNTIME_VERSIE` nooit vóór de winkelversie live is; native dependency = winkelrelease.",
            "App-auth zonder passkey (0029): toestelbinding + 5-cijferige toegangscode, éénmalige activatie per toestel; mislukte opslag eerlijk gemeld, nooit een tweede server-activatie.",
        ],
        "paden": ["backend/app/accordering/**", "backend/app/afdelingen/**", "backend/app/appupdate/**", "frontend/src/accordering/**", "frontend/src/accordeur/**", "frontend/src/afdelingen/**", "native/**"],
    },
    "vgg-odoo-migratie": {
        "titel": "Vastgoedgroep Nederland → Odoo (run 1 + run 2) en het pandenregister",
        "wat": "Schoonlijst, pandenregister (`pand`/`pand_boeking`, pand = RLZ-project), replay RLZ → Odoo-move-vorm (lees-only), rekeningmapping, 1001-model, RJ-220-rollen op company 6, bewijscyclus `vgg-odoo-stap0`, `vgg-odoo-migratie` (concepten → toets → auto-posten), metingen via de nameting-workflow.",
        "regels": [
            "Company-pin in de code, kill-switch alleen als executie-override, elke write terug-gelezen, audit per call; nooit unlink (annuleren = button_cancel); nooit via `nameting.sh` (weigert de schrijvende commando's hard).",
            "Memoriaalregels uitsluitend uit `DebitAmount`/`CreditAmount` (nooit `NetAmount`/`CreditOrDebit`); liquide middelen nooit in de rol-pool; één regel, één bestemming (overlap 1001-model ↔ rol = ROOD).",
            "Toets vóór het onomkeerbare moment: concepten → cent-exacte toets (Odoo-regels, per pand sluit) → pas dán posten; rood = niets posten; GO Peter op het SCHRIJF-c-rapport vóór de volledige run; RLZ-webfilter-blokkering = meting ongeldig.",
        ],
        "paden": ["backend/app/migratie/**", "backend/app/panden/**", "scripts/gcp/vgg_*.sh"],
    },
    "activa": {
        "titel": "Activa / MVA",
        "wat": "Ontwerp ter akkoord (Peter 16-09, geen bouw): register in RLZ `FixedAssets`/Odoo, detectie + voorvullen bij boeken, fiscale toetsing zonder zelf rekenen, reconciliatieblok `activa`; lees-only nulmeting `activa-nulmeting`.",
        "regels": [
            "MVA = `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx (de vlag alleen is te breed); enumeraties root-only (`rlz-lezen --root`); Universal 403 = probe verplicht.",
            "Geen bouw vóór akkoord Peter op `docs/ONTWERP_ACTIVA_MVA.md`.",
        ],
        "paden": ["backend/app/activa/**"],
    },
    "werkloop-productie": {
        "titel": "Werkloop, nametingen, deploy en productie-toegang",
        "wat": "Gouden set als poort, cc-inbox (launchd), nameting-workflow + `nameting.sh`, rapporten + INDEX, deploy.yml-lessen, productie alleen via gedeployde jobs, Feiten eerst (querybibliotheek, leesreplica), migratie-guards, database/RLS-lessen.",
        "regels": [
            "Definitie van \"af\": gouden set groen + productiegedrag ná deploy nagemeten met een vooraf genoemd meetrecept + rapportregel \"werkt in productie: ja/nee/niet gemeten\"; een meting telt pas als het bot-bestand op main staat óf het run-log is gelezen.",
            "Nooit een lokaal proces tegen de productiedatabase; schrijvende nazorg = `gcloud run jobs execute` op de gedeployde image ná deploy; nametingen onder `nameting@` (lees-only allowlist); deploy-check toetst service ÉN jobs.",
            "Een `^<t>^`-scheidingsteken staat nooit in een waarde; volledige envset per service/job in één stap; élk CC-eindrapport als `docs/rapporten/<datum>-<slug>.md` + INDEX-regel + sectie \"Gelezen regels\".",
            "Wachten van de inbox op een handmatige CC is nooit stil (duur, aantal, melding ná 30 min, `rlz inbox vrijgeven` als bewuste keuze).",
        ],
        "paden": ["backend/app/db/**", "backend/app/lezen/**", "backend/app/cli.py", "backend/app/main.py", "backend/app/config.py", "backend/migrations/**", "scripts/**", ".github/**", "opdrachten/**", "docs/rapporten/**"],
    },
}

# ---- bullet-titel → domein (eerste treffer wint) --------------------------------------------------------------------------
TOEWIJZING: list[tuple[str, str]] = [
    (r"^Werkvoorraad$", "werkvoorraad-controlescherm"),
    (r"^Na boeken direct door", "werkvoorraad-controlescherm"),
    (r"^Doorloop na boeken", "werkvoorraad-controlescherm"),
    (r"^Kantoor-frontend-modernisering", "kantoor-frontend"),
    (r"^Gebruikers & toegang — tabel-layout", "kantoor-frontend"),
    (r"^Btw", "btw"),
    (r"^Vervaldatum inkoopfactuur", "werkvoorraad-controlescherm"),
    (r"^RLZ-betaalstatus inkoopfactuur", "werkvoorraad-controlescherm"),
    (r"^Crediteur", "duplicaten-crediteuren"),
    (r"^Medewerker-wensen 04-09", "duplicaten-crediteuren"),
    (r"^Bulk-afvoer", "duplicaten-crediteuren"),
    (r"^Duplicaten", "duplicaten-crediteuren"),
    (r"^Duplicaat-poort", "duplicaten-crediteuren"),
    (r"^Herstelrun 07-09 blok A", "duplicaten-crediteuren"),
    (r"^Documentenlijst — bulk-acties", "werkvoorraad-controlescherm"),
    (r"^Afgehandelde documenten", "werkvoorraad-controlescherm"),
    (r'^Herstelrun "Basis eerst"', "werkloop-productie"),
    (r"^Gouden set", "werkloop-productie"),
    (r"^Wachtrij accordeur-app doorbelasting in bulk", "accordering-native-app"),
    (r"^Extractie-wachtrij-trigger", "intake-extractie"),
    (r"^UBL is deterministisch", "intake-extractie"),
    (r"^RLZ-bestaanscheck", "duplicaten-crediteuren"),
    (r"^Klant-accordeurs: scope", "accordering-native-app"),
    (r"^Verlegd-tarief deterministisch", "btw"),
    (r"^Reconciliatie", "reconciliatie"),
    (r"^Rapport verwijderde documenten", "duplicaten-crediteuren"),
    (r"^Hercontrole projectverdeling", "verplichtingen-projecten-voorraad"),
    (r"^Lijst-aanvulling", "werkvoorraad-controlescherm"),
    (r"^Verplichting", "verplichtingen-projecten-voorraad"),
    (r"^Offerte-match", "verplichtingen-projecten-voorraad"),
    (r"^Boekingsgeheugen", "werkvoorraad-controlescherm"),
    (r"^Prefill-autosave", "werkvoorraad-controlescherm"),
    (r"^Controlescherm", "werkvoorraad-controlescherm"),
    (r"^Factuurperiode", "werkvoorraad-controlescherm"),
    (r"^Periode-backfill", "werkvoorraad-controlescherm"),
    (r"^Automatisch boeken", "autoboeken-ai"),
    (r"^Vragenworkflow", "werkvoorraad-controlescherm"),
    (r"^Leeg = doorlopen", "werkvoorraad-controlescherm"),
    (r"^Afwijzen", "werkvoorraad-controlescherm"),
    (r"^Verzamelbak", "intake-extractie"),
    (r"^Nabundel-motor", "duplicaten-crediteuren"),
    (r"^E-mail intake", "intake-extractie"),
    (r"^AI-kostengrens", "intake-extractie"),
    (r"^AI-schema", "intake-extractie"),
    (r"^Deterministische extractie-terugval", "intake-extractie"),
    (r"^Best-practice-punten", "kantoor-frontend"),
    (r"^Synthetische bewaking", "reconciliatie"),
    (r"^Tellers per automatisering", "reconciliatie"),
    (r"^Automatiserings-tellers", "reconciliatie"),
    (r"^Activatieflow", "accordering-native-app"),
    (r"^Activa / MVA", "activa"),
    (r"^Vastgoedgroep Nederland", "vgg-odoo-migratie"),
    (r"^VGG — concept", "vgg-odoo-migratie"),
    (r"^Schoonlijst", "vgg-odoo-migratie"),
    (r"^Odoo-koppelwizard", "administraties-instellingen"),
    (r"^Rechten-probe", "administraties-instellingen"),
    (r"^Bank: historie-regel", "autoboeken-ai"),
    (r"^AI-plausibiliteitstoets", "autoboeken-ai"),
    (r"^Autoboeken", "autoboeken-ai"),
    (r"^AI-toets", "autoboeken-ai"),
    (r"^Autonomie-toekomstlijn", "autoboeken-ai"),
    (r"^Intercompany-factuurmatch", "reconciliatie"),
    (r"^Dubbele betaling", "reconciliatie"),
    (r"^Mini-voorraad", "verplichtingen-projecten-voorraad"),
    (r'^Kantoor-signaal "geplande week', "uren-planning-veldwerkers"),
    (r"^Inzicht › Projectverdeling", "verplichtingen-projecten-voorraad"),
    (r"^Pro-rato-periode", "verplichtingen-projecten-voorraad"),
    (r"^Accordeur-app", "accordering-native-app"),
    (r"^Native app", "accordering-native-app"),
    (r"^Wachtrij accordeur-app set-based", "accordering-native-app"),
    (r"^OTA \+ Apple", "accordering-native-app"),
    (r"^Omzet", "omzet"),
    (r"^Verkoopfactuur-boekpad", "omzet"),
    (r"^Bank", "bank"),
    (r"^Nameting-instrument matchmotor", "bank"),
    (r"^Matchmotor", "bank"),
    (r"^Bankscherm", "bank"),
    (r"^Betalen via Ponto", "bank"),
    (r"^Kempen-doorbelasting", "doorbelasting-intercompany"),
    (r"^Doorbelasting", "doorbelasting-intercompany"),
    (r"^Bugfix 14-09 — Instellingen › Doorbelasting", "doorbelasting-intercompany"),
    (r"^Afdelingen", "accordering-native-app"),
    (r"^Klant-autorisatie", "accordering-native-app"),
    (r"^Klant-accordering", "accordering-native-app"),
    (r"^Intercompany slaat", "doorbelasting-intercompany"),
    (r"^Intercompany-leveranciers", "doorbelasting-intercompany"),
    (r"^Google Play", "accordering-native-app"),
    (r"^Apple", "accordering-native-app"),
    (r"^Docs-nazorg store", "accordering-native-app"),
    (r"^Projecten$", "verplichtingen-projecten-voorraad"),
    (r"^Projectcode-generatie", "verplichtingen-projecten-voorraad"),
    (r"^Inzicht › Projecten", "verplichtingen-projecten-voorraad"),
    (r"^Contract-ontleding", "verplichtingen-projecten-voorraad"),
    (r"^Uren & meerwerk", "uren-planning-veldwerkers"),
    (r"^Planning", "uren-planning-veldwerkers"),
    (r"^Veldwerker", "uren-planning-veldwerkers"),
    (r"^Voorraad-aansluiting", "verplichtingen-projecten-voorraad"),
    (r"^Zoeken", "werkvoorraad-controlescherm"),
    (r"^Archief", "werkvoorraad-controlescherm"),
    (r"^Kalenderdag", "werkvoorraad-controlescherm"),
    (r"^Beginscherm kantoor-web", "werkvoorraad-controlescherm"),
    (r"^Groepskenmerk", "administraties-instellingen"),
    (r"^Groepssaldi", "administraties-instellingen"),
    (r"^Administratienaam", "administraties-instellingen"),
    (r"^Incasso-/betaalbatches", "bank"),
    (r"^Staande goedkeuring", "accordering-native-app"),
    (r"^Verplaatsen naar een andere administratie", "administraties-instellingen"),
    (r"^Eerste sync ná groene probe", "administraties-instellingen"),
    # Stack & platform
    (r"^Instellingen › Administraties", "administraties-instellingen"),
    (r"^Terugkerende-facturen-signaal", "administraties-instellingen"),
    (r"^Administratie toevoegen via de UI", "administraties-instellingen"),
    (r"^Autorisatie", "auth-toegang"),
    # Werkwijze
    (r"^Productie-nametingen structureel", "werkloop-productie"),
    (r"^Werkloop automatisch", "werkloop-productie"),
    (r"^Ochtendrun 11-09", "werkloop-productie"),
    (r"^RLZ-check als knop", "administraties-instellingen"),
    (r"^Scope-dialoog", "auth-toegang"),
    (r"^Bank — deels afgeletterde", "bank"),
    (r"^Deploy-les 10-09", "werkloop-productie"),
    (r"^Feiten eerst", "werkloop-productie"),
    (r"^Leesreplica afgerond", "werkloop-productie"),
]

# 07-09 verplaatste subkoppen (BESLISSINGEN) → domein
HISTORIE_TOEWIJZING: list[tuple[str, str]] = [
    (r"Instellingen › Administraties|Terugkerende-facturen|Administratie toevoegen", "administraties-instellingen"),
    (r"— Auth ", "auth-toegang"),
    (r"Na boeken direct door", "werkvoorraad-controlescherm"),
    (r"Kantoor-frontend-modernisering", "kantoor-frontend"),
    (r"Btw-", "btw"),
    (r"Vervaldatum", "werkvoorraad-controlescherm"),
    (r"Crediteur-dedup|Medewerker-wensen", "duplicaten-crediteuren"),
    (r"Verplichtingen", "verplichtingen-projecten-voorraad"),
    (r"Automatisch boeken", "autoboeken-ai"),
    (r"Vragenworkflow", "werkvoorraad-controlescherm"),
    (r"Verzamelbak|E-mail intake|AI-kostengrens|extractie-terugval", "intake-extractie"),
    (r"Best-practice", "kantoor-frontend"),
    (r"Synthetische bewaking|Reconciliatie-melding", "reconciliatie"),
    (r"Mini-voorraad|Projectverdeling|Catalogus-leesroute|Projectcode-generatie|Voorraad-aansluiting", "verplichtingen-projecten-voorraad"),
    (r"geplande week|Uren & meerwerk", "uren-planning-veldwerkers"),
    (r"Accordeur-app|Klant-autorisatie|Afdelingen", "accordering-native-app"),
    (r"Omzetboekingen|Verkoopfactuur-boekpad", "omzet"),
    (r"— Bank ", "bank"),
    (r"Kempen-doorbelasting", "doorbelasting-intercompany"),
    (r"Zoeken", "werkvoorraad-controlescherm"),
    (r"Koppelvlak vastgoedmodule", "omzet"),
    (r"Referenties — controlescherm-v2", "werkvoorraad-controlescherm"),
    (r"Referenties — verkenning/odoo-verkenning", "administraties-instellingen"),
    (r"Referenties — docs/DIAGNOSE_INTAKE", "intake-extractie"),
    (r"Referenties — docs/avg/", "intake-extractie"),
]

BULLET_START = re.compile(r"^- \*\*(.+?)\*\*", re.M)


def woorden(t: str) -> int:
    return len(t.split())


def domein_voor(titel: str, tabel: list[tuple[str, str]]) -> str | None:
    for patroon, dom in tabel:
        if re.search(patroon, titel):
            return dom
    return None


def bullets_van(sectie: str) -> list[tuple[int, int, str]]:
    """(start, einde, titel) van élke top-level bullet `- **…**` mét zijn inspringende vervolgregels."""
    uit: list[tuple[int, int, str]] = []
    posities = [m.start() for m in re.finditer(r"^- ", sectie, flags=re.M)]
    for i, st in enumerate(posities):
        einde = posities[i + 1] if i + 1 < len(posities) else len(sectie)
        blok = sectie[st:einde]
        m = re.match(r"- \*\*(.+?)\*\*", blok, flags=re.S)  # de vette titel kan over een regeleinde lopen
        titel = re.sub(r"\s+", " ", m.group(1)).strip() if m else blok[2:80].strip()
        uit.append((st, einde, titel))
    return uit


def sectie_grenzen(tekst: str, kop_prefix: str) -> tuple[int, int, int]:
    """(kop_start, body_start, einde) van een `## `-sectie."""
    m = re.search(r"^## " + re.escape(kop_prefix) + r".*$", tekst, flags=re.M)
    assert m, kop_prefix
    nxt = re.search(r"^## ", tekst[m.end():], flags=re.M)
    einde = m.end() + nxt.start() if nxt else len(tekst)
    return m.start(), m.end() + 1, einde


def compact_blok(slug: str, d: dict) -> str:
    regels = "\n".join(f"  {i}. {r}" for i, r in enumerate(d["regels"], 1))
    return (
        f"- **{d['titel']}** — {d['wat']}\n"
        f"{regels}\n"
        f"  **LEESPLICHT: lees `docs/regels/{slug}.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**\n"
    )


def main() -> int:
    if (REGELS / "INDEX.md").exists():
        print("docs/regels/INDEX.md bestaat al — splitsing is al gedaan (idempotent: niets gedaan)")
        return 0
    claude_voor = CLAUDE.read_text(encoding="utf-8")
    w0 = woorden(claude_voor)
    verhuisd: dict[str, list[tuple[str, str]]] = {slug: [] for slug in DOMEINEN}  # slug → [(sectie-naam, tekst)]
    tekst = claude_voor
    onbekend: list[str] = []

    # 1. Domeinbeslissingen: álle bullets verhuizen, sectie = compacte blokken
    ks, bs, einde = sectie_grenzen(tekst, "Domeinbeslissingen")
    body = tekst[bs:einde]
    intro_einde = body.find("\n- ")
    intro = body[: intro_einde + 1]
    bullets_tekst = body[intro_einde + 1 :]
    for st, en, titel in bullets_van(bullets_tekst):
        dom = domein_voor(titel, TOEWIJZING)
        if dom is None:
            onbekend.append(titel)
            continue
        verhuisd[dom].append(("Domeinbeslissingen", bullets_tekst[st:en]))
    assert not onbekend, f"bullets zonder domein: {onbekend}"
    nieuwe_intro = (
        "\n> **Regels per domein met LEESPLICHT (Peter 17-09, BESLISSINGEN \"CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT (Peter 17-09)\"):**\n"
        "> de volledige, woordelijke tekst van élk domein staat in `docs/regels/<domein>.md` (chronologisch, mét datum/migratie/\n"
        "> BESLISSINGEN-sectie per alinea; index + code-paden in `docs/regels/INDEX.md`). Hieronder per domein alleen wat het is, de\n"
        "> bindende hoofdregels en de leesplicht. Een nieuw besluit → volledige tekst in `docs/regels/<domein>.md` + BESLISSINGEN-rij +\n"
        "> hooguit één regel hier. Guards: `tests/unit/test_regels_index.py`, `tests/unit/test_rapporten_gelezen_regels.py`.\n\n"
    )
    blokken = "\n".join(compact_blok(slug, d) for slug, d in DOMEINEN.items())
    tekst = tekst[:bs] + intro + nieuwe_intro + blokken + "\n" + tekst[einde:]

    # 2. Stack & platform: de vier domein-bullets verhuizen (Instellingen, Terugkerend, Administratie toevoegen, Autorisatie) +
    #    de Auth-bullet (herkenbaar aan "Auth: e-mailuitnodiging")
    ks, bs, einde = sectie_grenzen(tekst, "Stack & platform")
    body = tekst[bs:einde]
    nieuw_body = body
    for st, en, titel in reversed(bullets_van(body)):
        blok = body[st:en]
        dom = domein_voor(titel, TOEWIJZING)
        if blok.startswith("- Auth: e-mailuitnodiging"):
            dom = "auth-toegang"
        if dom in ("administraties-instellingen", "auth-toegang"):
            verhuisd[dom].append(("Stack & platform", blok))
            vervanging = (
                f"- Auth, autorisatie, RLS en app-auth: volledige tekst in `docs/regels/auth-toegang.md` (LEESPLICHT) — kern: passkeys eerste lijn (0020), app-rollen toestelbinding + toegangscode (0029), geen scope = geen data, niemand muteert zijn eigen rol/scope, élk kantoor-endpoint een rolpoort.\n"
                if dom == "auth-toegang" and blok.startswith("- Auth")
                else ("" if dom == "auth-toegang" else "")
            )
            if dom == "administraties-instellingen":
                vervanging = ""
            nieuw_body = nieuw_body[:st] + vervanging + nieuw_body[en:]
    nieuw_body = nieuw_body.replace(
        "- DB-schema's: `platform`",
        "- Administraties/koppelingen/sync-instellingen: volledige tekst in `docs/regels/administraties-instellingen.md` (LEESPLICHT).\n- DB-schema's: `platform`",
        1,
    )
    tekst = tekst[:bs] + nieuw_body + tekst[einde:]

    # 3. Werkwijze: domein-bullets verhuizen naar werkloop-productie/administraties/auth/bank; harde werkregels blijven
    ks, bs, einde = sectie_grenzen(tekst, "Werkwijze")
    body = tekst[bs:einde]
    nieuw_body = body
    for st, en, titel in reversed(bullets_van(body)):
        dom = domein_voor(titel, TOEWIJZING)
        if dom is None:
            continue
        verhuisd[dom].append(("Werkwijze", body[st:en]))
        nieuw_body = nieuw_body[:st] + nieuw_body[en:]
    nieuw_body = nieuw_body.replace(
        "- **`docs/BESLISSINGEN.md` is de verplichte eerste check",
        "- **Werkloop, nametingen, deploy, productie-toegang en Feiten eerst: volledige tekst in `docs/regels/werkloop-productie.md` (LEESPLICHT).** Kern: gouden set + nameting + \"werkt in productie: ja/nee/niet gemeten\" = de definitie van af; productie alleen via gedeployde jobs of het nameting-SA; élk rapport in `docs/rapporten/` + INDEX + sectie \"Gelezen regels\".\n- **`docs/BESLISSINGEN.md` is de verplichte eerste check",
        1,
    )
    tekst = tekst[:bs] + nieuw_body + tekst[einde:]

    # 4. Historie 07-09 uit BESLISSINGEN kopiëren
    besl = BESLISSINGEN.read_text(encoding="utf-8")
    i = besl.find("\n## VERPLAATST UIT CLAUDE.md (07-09-2026)")
    j = besl.find("\n## ", i + 4)
    hist = besl[i:j]
    historie: dict[str, list[str]] = {slug: [] for slug in DOMEINEN}
    for m in re.finditer(r"^### (.+)$", hist, flags=re.M):
        st = m.start()
        nx = hist.find("\n### ", st + 1)
        nx = nx if nx != -1 else len(hist)
        dom = domein_voor(m.group(1), HISTORIE_TOEWIJZING)
        assert dom, f"historie-subkop zonder domein: {m.group(1)}"
        historie[dom].append(hist[st:nx].rstrip("\n") + "\n")

    # 5. Regelsbestanden schrijven
    REGELS.mkdir(exist_ok=True)
    wm = 0
    for slug, d in DOMEINEN.items():
        delen = verhuisd[slug]
        regels_md = [
            f"# Regels — {d['titel']}",
            "",
            f"> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).",
            f"> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht \"CLAUDE.md: volledige regels per domein\"); niets samengevat,",
            f"> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,",
            f"> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +",
            f"> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.",
            "",
            f"**Wat het is:** {d['wat']}",
            "",
            "## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)",
            "",
        ]
        for sectie_naam, blok in delen:
            regels_md.append(f"<!-- uit CLAUDE.md § {sectie_naam} -->")
            regels_md.append(blok.rstrip("\n"))
            regels_md.append("")
            wm += woorden(blok)
        if historie[slug]:
            regels_md.append("## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN \"VERPLAATST UIT CLAUDE.md (07-09-2026)\" blijft de historische vindplaats)")
            regels_md.append("")
            for h in historie[slug]:
                regels_md.append(h.replace("\n### ", "\n### ", 1))
        (REGELS / f"{slug}.md").write_text("\n".join(regels_md).rstrip("\n") + "\n", encoding="utf-8")

    # 6. INDEX
    rijen = ["# Regels per domein — index (Peter 17-09)", "",
             "Élk domein heeft één regelsbestand mét de volledige, woordelijke CLAUDE.md-tekst en een LEESPLICHT. De kolom code-paden koppelt",
             "élk pakket onder `backend/app/` en élke map onder `frontend/src/` (plus scripts/native/docs) aan precies één domein — de",
             "guard `backend/tests/unit/test_regels_index.py` eist dat élk pakket/élke map hier staat en dat élke LEESPLICHT-verwijzing in",
             "CLAUDE.md naar een bestaand bestand wijst. Een opdracht in `opdrachten/inbox/` draagt de kopregel `Domeinen: a, b`; ontbreekt die,",
             "dan leidt CC de domeinen af uit de geraakte paden via deze tabel en noemt dat expliciet in het rapport (sectie \"Gelezen regels\").",
             "", "| Domein | Bestand | Code-paden |", "|---|---|---|"]
    for slug, d in DOMEINEN.items():
        rijen.append(f"| {d['titel']} | `docs/regels/{slug}.md` | {', '.join('`' + p + '`' for p in d['paden'])} |")
    (REGELS / "INDEX.md").write_text("\n".join(rijen) + "\n", encoding="utf-8")

    # 7. CLAUDE.md schrijven + bewijs
    CLAUDE.write_text(tekst, encoding="utf-8")
    w1 = woorden(tekst)
    # nieuwe blokken = alles in CLAUDE.md ná dat niet in CLAUDE.md vóór stond: bereken als w1 - (w0 - wm)
    wn = w1 - (w0 - wm)
    # verbatim-toets
    ontbrekend = 0
    for slug in DOMEINEN:
        inhoud = (REGELS / f"{slug}.md").read_text(encoding="utf-8")
        for _, blok in verhuisd[slug]:
            if blok.rstrip("\n") not in inhoud:
                ontbrekend += 1
                print("NIET VERBATIM:", blok[:80])
    print(f"woorden CLAUDE.md vóór: {w0}; ná: {w1}; verhuisd: {wm}; nieuwe blokken/leesplicht: {wn}; identiteit w1 + wm - wn == w0: {w1 + wm - wn == w0}")
    print(f"tekens CLAUDE.md vóór: {len(claude_voor.encode())}; ná: {len(tekst.encode())}; regelsbestanden: {len(DOMEINEN)}; verhuisde blokken: {sum(len(v) for v in verhuisd.values())}; niet-verbatim: {ontbrekend}")
    return 1 if ontbrekend else 0


if __name__ == "__main__":
    sys.exit(main())
