# Rapport 18-09 — MOCKUP "Factuuropdracht per project" (steigerbouw → verkoopfactuur klaarzetten in RLZ/Odoo) — TER AKKOORD, geen bouw

Opdracht: `opdrachten/gedaan/2026-09-18-mockup-factuuropdracht-per-project.md` (Peter 18-09, letterlijk: "Vanuit onze module moeten
wij een factuuropdracht klaar kunnen zetten voor steigerbouw (per project), waarop wij onderdelen, termijnen etc. kunnen selecteren,
waarna de factuur in RLZ (en straks Odoo) wordt klaargezet."). Domeinen: verplichtingen-projecten-voorraad, omzet, kantoor-frontend.
**Alleen de mockup — geen code, geen migratie, geen route.** Bouw start pas ná akkoord Peter (UX-review-regel 15-08).

**Werkt in productie: n.v.t.** (niets gedeployed; er is niets te meten).

## Pre-feature-ritueel — wat bestaat al, wat is nieuw (BESLISSINGEN + code gelezen)

| Bouwsteen | Stand | Bron |
|---|---|---|
| SalesInvoice-motor (PUT + client-GUID, BookDate, debiteur idempotent UUIDv5, harde checks, storno/tegenboek) | **bestaat** — `customer_id` optioneel (omzet entity-loos) / gevuld (Vastly, Kempen) | BESLISSINGEN "Vastly-verkoopfactuur-boekpad", `app/verkoop/boeken.py` r. 142–324 |
| Contract-ontleding: kopvelden (soort werk, contract-m², looptijd, doorlopende huur) + staffels mét herkomst contract/mens | **bestaat** (auto-first, migratie 0118) | BESLISSINGEN "CONTRACT-ONTLEDING: KOPVELDEN + AUTO-FIRST" |
| Termijnschema (30/40/30, voorwaarde "bereikt") op het project | **nieuw** — de ontleding kent géén termijnen; "termijn" bestaat alleen aan de INKOOPKANT (offerte-match, `app/verplichting/match.py`) | grep `termijn` in `app/projecten`, `app/extractie/contract.py` = leeg |
| Meerwerk-statusflow gemeld → goedgekeurd → doorbelast (+ signaal "goedgekeurd + 14 d niet op verkoopfactuur") | **bestaat** | `MeerwerkStatus` (`app/uren/models.py` r. 64), BESLISSINGEN "Ontwerpronde uren & uitvoerder + meerwerk-kantoor" |
| Doorbelastingscontrole op ITEM-niveau (inhuur-items uit inkoopregels vs contract/verkoop) | **nieuw** — praktijkles in CLAUDE.md, geen code | grep `inhuur`/`item` in `app/doorbelasting` = alleen entiteit-doorbelasting |
| Kempen-doorbelasting (bron-verkoop + spiegel-inkoop op dezelfde motor) | **bestaat** — andere bron, géén spiegel bij de factuuropdracht | BESLISSINGEN "Kempen-doorbelasting"-secties |
| Odoo-adapter | **alleen INKOOP-port** (`InkoopPort`: `boek_inkoopfactuur`, `boek_tegenboeking`); `out_invoice` alleen als LEESBRON (voorraad-uitstroom) | `app/backends/port.py`, `app/odoo/verkoop_uitstroom.py` |
| Kantoorbreed lijstpatroon (Inzicht › Projecten/Verplichtingen), projectdetail mét tabs, restant-balk, KeuzeKaarten | **bestaat** | BESLISSINGEN "INZICHT › PROJECTEN KANTOORBREED", "UX-PATRONEN ALS NORM" |

Nieuw te bouwen (ná akkoord): entiteit factuuropdracht + regels mét bronverwijzing (termijn/meerwerk/item/vrij), termijnschema +
bereikt-signaal, `VerkoopPort` (RLZ = bestaande motor, Odoo = `out_invoice` draft → `action_post`), verrekenbare-items-lezer, tab
Facturatie op het projectdetail, wizard, Inzicht › Facturatie-kandidaten + KPI-kaart, bronrij-terugkoppeling + 409-poort, storno-pad.

## Wat de mockup toont — `mockup/factuuropdracht-project.html` (desktop kantoor, designpass v2, licht thema, tokens = planning-v3)

1. **① Projectdetail › tab "Facturatie"** — KPI-rij (contractsom · gefactureerd · klaargezet · factureerbaar nu), restant-balk
   (gefactureerd/klaargezet/restant; meerwerk + items bóven de contractsom), termijnschema uit contract (bereikt-chip mét bron
   weekstaat/planning, geboekte termijnen mét RLZ-nummer, factureerbare termijn mét "Op factuur →"), meerwerk goedgekeurd-nog-
   doorbelasten (bestaande flow), verrekenbare inhuur-items (staffelprijs of oranje "prijs ontbreekt"), zijpaneel "Factureerbaar nu"
   + eerdere facturen op het project (gelezen uit RLZ/Odoo — geen tweede waarheid). Één primaire knop "Factuuropdracht maken" + ⋯.
2. **② Wizard in één scherm** — regels mét vinkje, omschrijving, aantal, eenheid (termijn/m²/m¹/stuks/uur/week), prijs mét
   herkomst-chip contract/staffel/handmatig, vrije regel; btw per regel (verlegd voorgekozen uit het debiteur-geheugen, nooit 0 %
   zonder basis); kop mét project vooringevuld, debiteur = opdrachtgever (RLZ Customer / "+ Nieuwe debiteur" idempotent),
   factuurdatum (= BookDate), referentie opdrachtgever/PO **verplicht als de projectspec dat eist** (harde check, knop disabled),
   samenvatting + restant-balk ná deze factuur. "Klaarzetten" = concept in RLZ, niets geboekt.
3. **③ Resultaat & status** — statusflow klaargezet → geboekt (17) → verzonden → betaald (laatste twee = gelezen standen), harde
   checks van het bestaande verkoop-boekpad + nieuwe check "Duplicaat (module): bronrij al in een factuuropdracht", bronrijen-tabel
   (termijn → gefactureerd, meerwerk → doorbelast, item → doorbelast), 409-melding bij dubbel gebruik mét verwijzing, tijdlijn,
   PDF-preview (uit RLZ, de module rendert niets zelf), Odoo-blok (zelfde scherm, andere port).
4. **④ Inzicht › Facturatie-kandidaten** — kantoorbreed lijstpatroon, tellers "7 projecten · € … · over 3 administraties",
   administratie = filter, urgentie-sortering, per rij de reden (termijn bereikt / meerwerk N dagen / items niet doorbelast) mét
   primaire knop "Factuuropdracht maken" + ⋯ (eigen rekening mét reden, termijn nog niet bereikt, project openen); lege stand = actie.
5. **Notities ①–⑥** letterlijk uit de opdracht mét uitwerking; **beslispunten ④ en ⑥** expliciet (hieronder).

## Beslispunten voor Peter (expliciet)

- **④ Verzenden van de factuur (mail aan de opdrachtgever): RLZ/Odoo zelf of de module?** Voorstel **RLZ/Odoo verzendt (optie A)**;
  de module leest "verzonden" terug en signaleert "geboekt maar ná 3 dagen niet verzonden". Argumenten: RLZ = bron van waarheid
  én eigenaar van de PDF/lay-out/Peppol-uitgaand; een tweede mailkanaal = tweede waarheid. Optie B (module mailt via het bestaande
  SMTP-kanaal mét de RLZ-PDF) blijft bouwbaar als opt-in per administratie, mail-first, audit.
- **⑥ Klant-accordering vóór verzenden?** Voorstel **nee (default) — kantoor boekt**; de accorderingsflow is een inkoopmechanisme.
  Vier-ogen intern zit al in concept → geboekt. Wil Universal zelf meekijken, dan als opt-in per administratie op de bestaande
  accordeur-kaart (soort "verkoopfactuur ter accordering") — pas op vraag.
- Overige uitwerkingen (①②③⑤) staan op de tab Notities; ③ vraagt een `VerkoopPort` náást de `InkoopPort` (0016-patroon).

## Klikpunten Peter

- Mockup openen: `mockup/factuuropdracht-project.html` (vijf tabs) → akkoord / aanpassingen per scherm; keuze op ④ en ⑥.
- Ná akkoord: bouwopdracht via de inbox (migratie factuuropdracht + termijnschema; VerkoopPort; Facturatie-tab; Inzicht-lijst).

## Gelezen regels

- `docs/regels/verplichtingen-projecten-voorraad.md` (178 regels) — volledig, vóór de start.
- `docs/regels/omzet.md` (232 regels) — volledig, vóór de start.
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig, vóór de start.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig (run-brede werkloop).
