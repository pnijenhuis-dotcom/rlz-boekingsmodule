# Rapport 16-09 — Omzetboekingen (Receipts) onder "Uitgaven" bij Van Boxtel: diagnose, categorie op binder, herstelroute

**Diagnose in twee zinnen:** de RLZ-UI-mappen Inkomsten/Uitgaven volgen de `DocumentBinder` van de *categorie* (alleen zichtbaar
mét `$expand=DocumentBinder`), en bij Van Boxtel draagt "Verkoopfactuur (Omzet)" de binder Inkomsten — de omzetmotor was niet de
oorzaak. De "omzetrapporten" zijn PurchaseInvoices (DocumentType 1, categorie Overige kosten onder Uitgaven, mét crediteur,
referenties "11-09/12-09", "12-09/13-09", …, omschrijving "Samengevoegd (N regels)", o.a. € 10.998,15 = het ProfX-journaal van
11-09): kassarapporten die via de inkoopstroom geboekt zijn — dezelfde wortel als de ProfX-opdracht (order 6).

**Opdracht:** `opdrachten/gedaan/2026-09-16-omzet-receipts-onder-uitgaven.md`. Geen migratie.
**Werkt in productie: niet gemeten** (de diagnose wél: vijf lees-only metingen op productie, zie api-verkenning).

## Gedaan
1. **Blok A — diagnose lees-only** via `scripts/gcp/nameting.sh rlz-lezen` op Van Boxtel: `DocumentCategories` zonder/mét
   `$expand=DocumentBinder`, `Receipts` (top 5, `Date desc`), `PurchaseInvoices` (top 8). Vastgelegd in api-verkenning
   "Receipts — binder Inkomsten/Uitgaven (STAP-0 16-09)" incl. de API-lessen (`DocumentType` = enum, niet filterbaar met een
   getal; Receipts sorteren op `Date`).
2. **Blok B — categorie op binder** (`app/omzet/categorie.py`): DocumentType 10 + binder Inkomsten (voorkeursnaam, anders de
   enige); harde check "Omzetcategorie (Inkomsten)" (rood bij geen/meerduidig/RLZ onleesbaar); legacy-op-naam-cache wordt
   geïnvalideerd; mens-keuze wint; leesroute `DOCUMENT_CATEGORIES` als één bron (niet in de probe-set — beslispunt).
3. **Blok B2 — zichtbaar + corrigeerbaar:** regel "Boekt in Reeleezee als: ‹binder› · ‹categorie›" mét herkomst-chip en keuzelijst
   (gegroepeerd op binder, Uitgaven mét waarschuwing) in het omzet-controlescherm; `PUT …/omzet/verkoop-categorie` = default van de
   administratie (bron 'mens', audit oud→nieuw, tijdlijn); kaart "Verkoop → Reeleezee" noemt binder · categorie.
4. **Blok C — herstel:** lees-only CLI `omzet-binder-rapport` (A: Receipts niet onder Inkomsten, B: geboekte inkoopfacturen die omzet
   zijn; `--met-pdf` = ook PDF-herkenning), reconciliatie-soorten `verkoop_categorie_afwijkt` en `omzet_in_inkoopstroom`, actie
   "Herboeken als omzet…" op Inzicht › Reconciliatie (storno actie 19 achter de aangiftepoort, Beheerder-doorzet mét reden,
   document → kassarapport in de werkvoorraad; de mens boekt als Receipt onder Inkomsten). Geen automatische massale herboeking.

## Tests
- Backend: `tests/omzet/test_categorie_binder.py` 8, `test_boeken.py`/`test_bronnen.py` aangepast, omzet + reconciliatie + keten-guard
  + leesroutes 507 groen; rol-endpoint-sweep — zie slotrapport.
- Frontend: `OmzetReviewScreen.test.tsx` +1 (categorie-regel, PUT met `categorie_id` + `document_id`), `HerboekenAlsOmzetActie.test.tsx` 2
  (herkenning van de soort, reden → 409-blokkade → Beheerder-doorzet → link "als omzet boeken"), reconciliatie-suite groen, `tsc -b` groen.

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md` opdracht 11)
Leesroute buiten de probe-set · reconciliatie-detectie alleen op "alle regels op omzetrekening" (PDF-herkenning alleen in de CLI) ·
herstel = storno + herclassificatie (geen categorie-PUT op een geboekte SalesInvoice zonder STAP-0) · mens-keuze mag een
niet-Inkomsten-binder zijn (oranje signaal, geen blokkade).

## Meetrecept ná deploy
1. `scripts/gcp/nameting.sh omzet-binder-rapport --administratie "Van Boxtel"` → B-regels voor de als inkoop geboekte kassarapporten
   (o.a. RLZ-04-00000683..686) mét aangiftepoort-stand; A = 0 (geen module-Receipt buiten Inkomsten).
2. Volgende nachtelijke reconciliatie: bevindingen "Omzet als inkoopfactuur geboekt · ‹bestand› · ‹boekstuk›" bij Van Boxtel op
   Inzicht › Reconciliatie mét knop "Herboeken als omzet…".
3. Peter klikt per document "Herboeken als omzet…" (reden) → inkoopfactuur gestorneerd (actie 19, RLZ-UI: concept), document als
   kassarapport in de werkvoorraad → omzet-controlescherm toont "Boekt in Reeleezee als: Inkomsten · Verkoopfactuur (Omzet)" →
   boeken → de Receipt staat in RLZ onder Verkopen/Boekingen (Inkomsten). Valt de factuurdatum in een ingediende aangifte, dan
   de Beheerder-stap.
4. Ná herstel: `omzet-binder-rapport --administratie "Van Boxtel"` → A 0 · B 0.
