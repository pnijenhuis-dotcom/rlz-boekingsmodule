# BESLISSINGEN — statusregister RLZ-boekingsmodule

> **Verplichte eerste check vóór elk feature-voorstel en elke bouwstart** (pre-feature-ritueel,
> `Platform/WERKWIJZE.md` v1.4). Doel: geaccordeerde besluiten nooit verliezen of her-litigeren.
> Dit register **verwijst** — de canonieke vindplaats blijft de bron (mockup, BOUWPLAN, CLAUDE.md,
> verkenning, Platform/besluiten). Staat iets hier op *goedgekeurd*: 1-op-1 voortbouwen, niet
> opnieuw uitvragen.
>
> **Capture-at-acceptance:** elk akkoord van Peter komt op het moment van akkoord híér bij (regel
> toevoegen/status ophogen) én op de canonieke plek. Een akkoord dat alleen in een chat bestaat,
> bestaat niet.
>
> **Statusladder** (cumulatief): `besproken` → `goedgekeurd` (akkoord Peter, bv. mockup-ronde) →
> `uitgewerkt` (ontwerp/spec af) → `gebouwd` → `getest`. Daarnaast: `geparkeerd`, `vervallen`,
> `geverifieerd` (API-/domeinfeit). Mockup-anchors verwijzen naar `mockup/index.html#<id>`.
> Projectoverstijgende besluiten staan uitsluitend in `Platform/besluiten/INDEX.md`.

## Kernflow inkoop (fase 1)

| Onderwerp | Status | Canonieke vindplaats |
|---|---|---|
| Werkvoorraad = klantenlijst met tellers → klantpagina → controlescherm | goedgekeurd; UI gebouwd | mockup `#werkvoorraad`/`#klantpagina`/`#review`; BOUWPLAN fase 1 punt 8 |
| Sync-laag per administratie (Ledgers/TaxRates/Vendors/Projects) | gebouwd + getest (2026-07-08) | BOUWPLAN fase 1 punt 4 |
| Document-pipeline / statusmachine | gebouwd + getest (2026-07-08) | BOUWPLAN fase 1 punt 5; `backend/app/documenten/statusmachine.py` |
| Boeken (PUT+client-GUID, actie 17, idempotentie, failsafes) | gebouwd + getest (2026-07-09) | BOUWPLAN fase 1 punt 6; `backend/app/documenten/boeken.py` |
| Controlescherm (kopgegevens + regels + harde checks + boekactie) | gebouwd (2026-07-09); geheugen-UI erbij (2026-07-14) | BOUWPLAN fase 1 punt 8; `frontend/src/document/BoekvoorstelPanel.tsx` |
| Webhook "factuur geboekt" (outbox + vastgoed-scope-filter) | gebouwd + getest (outbox 2026-07-09, scope 2026-07-13); afleveraar + HMAC-per-verzendpoging open | BOUWPLAN fase 1 punt 7; migratie 0018 `is_vastgoed`; Platform OPEN_ITEMS |
| Boekingsgeheugen (seed uit RLZ-historie + leerlus + voorstel + UI-chips; correcties > historie; seed-only = oranje tot eerste app-bevestiging) | gebouwd + getest (B1–B6, 2026-07-13/14) | BOUWPLAN fase 1 punt 7b; CLAUDE.md "Boekingsgeheugen"; `backend/app/geheugen/` |
| — openstaand daarbij: live visuele verificatie groen/oranje chips + voorstel-op-blur voor handmatige regels | goedgekeurd (follow-up) | BOUWPLAN punt 7b follow-ups (2026-07-14) |

## Harde/blokkerende checks (checkstatus-audit 2026-07-13 — actueel houden, ook in CLAUDE.md)

| Check | Status | Canonieke vindplaats |
|---|---|---|
| Duplicaat (Entity+Referentie+bedrag) | gebouwd + getest | `backend/app/documenten/checks.py::check_duplicaat`; besluit 0013 (actie 138 vervallen) |
| Regeltelling vs totaal | gebouwd + getest | `checks.py::check_regeltelling` |
| Verplichte velden incl. projectplicht | gebouwd + getest | `checks.py::check_verplichte_velden` |
| IBAN-wissel (vertrouwde meerwaardige set per crediteur, G-rekening/WKA = norm) | gebouwd + getest (2026-07-13) | `checks.py::check_iban_wissel`; `app/documenten/leverancier_iban.py`; migratie 0019; Platform OPEN_ITEMS (afgehandeld) |
| Vraag blokkeert boeken | **gebouwd + getest** (2026-07-14, backend/PART A) | `app/documenten/vragen.py`; migraties 0021/0022; `tests/documenten/test_vragen.py` |
| Afwijzen-met-verplichte-reden | half: status bestaat en blokkeert boekpad; workflow/endpoint/reden-afdwinging niet | CLAUDE.md checkstatus; BOUWPLAN fase 1 punt 8-vervolg |
| Memoriaal saldo = 0 | nog niet gebouwd → fase 2 | CLAUDE.md checkstatus |
| VGB-prefixfilter (nooit als werkvoorraad tonen) | nog niet gebouwd → vóór lezen uit gedeelde administraties | CLAUDE.md checkstatus; koppelcontract |
| Autoboeken opt-in per leverancier | nog niet gebouwd → vóór eerste autoboek-functie | CLAUDE.md checkstatus |
| Webhook-HMAC per verzendpoging (niet bij aanmaak) | nog niet gebouwd → mét de afleveraar | Platform OPEN_ITEMS (webhook-item, actiepunt 2) |

## Goedgekeurd ontwerp, nog te bouwen

| Onderwerp | Status | Canonieke vindplaats |
|---|---|---|
| Vragenworkflow (vraag blokkeert boeken, eigenaar per administratie, antwoord voedt geheugen, status in werkvoorraad — geen apart menu) | **backend gebouwd + getest** (2026-07-14, PART A: record + endpoints + eigenaar-instelling + afdwinging; beantwoorden/intrekken herstellen exact de herkomst-status via `vraag.status_voor_vraag` — nooit hardgecodeerd te_controleren; "antwoord voedt geheugen" v1 via de boek-leerlus, doorzoekbare Q&A-kennisbank per crediteur = genoteerde latere verrijking); UI = PART B, nog te bouwen op mockup | mockup `#vragen` + `#vraagmodal`; CLAUDE.md "Vragenworkflow"; BOUWPLAN fase 1 punt 6 checkstatus + punt 8-vervolg; `app/documenten/vragen.py` |
| — **Bewuste uitbreidingen op de goedgekeurde mockup** (akkoord Peter 2026-07-14): (1) **vraag intrekken** (status `ingetrokken`, reden optioneel, document terug naar herkomst) — zonder intrekken dwingt een per ongeluk gestelde vraag een pro-forma nep-antwoord af dat als échte kennis in de historie zou staan; (2) **vraag stellen vanuit `klaar_om_te_boeken`** (statusmachine-uitbreiding, incl. herstel terug naar `klaar_om_te_boeken`) — ook uit een boekklaar document kan een vraag rijzen, anders moest de controleur kunstmatig terug naar te_controleren. Boeken blijft vanuit `vraag_open` geblokkeerd | **gebouwd + getest** (2026-07-14) | `app/documenten/vragen.py`; `statusmachine.py`; migratie 0022; `tests/documenten/test_vragen.py` |
| Afwijzen = verplichte reden, blijft zichtbaar | goedgekeurd | mockup `#afwijsmodal`; CLAUDE.md |
| Verzamelbak "Niet toegewezen" (tenaamstelling leidend, leert, nooit auto-toewijzen bij twijfel) | goedgekeurd | mockup `#tenaamstellingmodal`/`#verdeelmodal`; CLAUDE.md |
| E-mail intake (één adres, multi-factuur-PDF splitsen) | goedgekeurd → fase 3 | CLAUDE.md; BOUWPLAN fase 3 |
| Omzetboekingen (SalesInvoice + kostprijsmemoriaal als één transactie; BLOW vrijgesteld, géén 0%) | goedgekeurd → fase 2 | mockup `#omzetreview`; CLAUDE.md "Omzetboekingen"; BOUWPLAN fase 2 |
| Bank/afletteren (voorstel-volgorde 1–5, niet door klant-accorderingsflow; G-rekening-split = standaardcase) | goedgekeurd → fase 2 | mockup `#bank`/`#bankdetail`; CLAUDE.md "Bank"; BOUWPLAN fase 2 |
| Klant-autorisatie à la Zenvoices (sequentiële lagen, drempels, PWA) | goedgekeurd → fase 3 | mockup `#autorisatie`; CLAUDE.md; BOUWPLAN fase 3 |
| Projectenmodule (projectplicht hard, OVH-project, werksoort-mapping, signalen, doorbelastingscontrole op item-niveau) | goedgekeurd → fase 4 | mockup `#projecten`/`#projectdetail`; CLAUDE.md "Projecten"; BOUWPLAN fase 4; verkenning/16_DOORBELASTING_KEMPEN.md |
| Zoeken + tijdlijn + archief (7 jaar) | goedgekeurd | mockup `#zoeken`; CLAUDE.md |
| Responsive-fix controlescherm-rechterkolom (<~1560px klipt; doel 1440/1536) | goedgekeurd (follow-up 2026-07-14) | BOUWPLAN punt 7b follow-ups |

## Platform-besluiten die deze module raken (selectie — volledig register: `Platform/besluiten/INDEX.md`)

| Onderwerp | Status | Canonieke vindplaats |
|---|---|---|
| Groepsconsolidatie = pure reporting-overlay (MI-laag), nooit geboekt | **besloten** (2026-07-14) → MI-fase | **Platform-besluit 0015** (`besluiten/0015-groepsconsolidatie-reporting-overlay.md`); BOUWPLAN fase 5 |
| Actie 138 (RLZ-duplicaatcheck) zonder bruikbaar signaal — vervallen; idempotentie = eigen verantwoordelijkheid | geverifieerd/besloten | Platform-besluit 0013; verkenning/api-verkenning.md "Actie 138" |
| Actie 19 Correct = zelfde document terug naar concept, géén creditdocument | geverifieerd (2026-07-06) | verkenning/api-verkenning.md "Actie 19 Correct"; koppelcontract §7.3 |
| DocumentStatus-semantiek (1=concept, 2=open, 3=afgeletterd; geboekt = 2 óf 3) | geverifieerd (2026-07-13) | CLAUDE.md "Reeleezee API"; verkenning/api-verkenning.md |

## Geparkeerd / waarschuwing

| Onderwerp | Status | Canonieke vindplaats |
|---|---|---|
| KvK-crediteur-dedup (KvK-match wint, naam-fallback gemarkeerd, live RLZ-check vóór PUT, naam-normalisatie via KvK Basisprofiel, duplicaat-signalering zonder auto-samenvoegen) | **uitgewerkt, geparkeerd** — canoniek vastgelegd 2026-07-14 (na eerder sessie-verlies; aanleiding pre-feature-ritueel WERKWIJZE v1.4). Bouwen pas als de KvK-API voor RLZ beschikbaar is (rule-of-two → gedeelde platform-connector) én het RLZ-KvK-veld live geverifieerd is | `docs/ontwerp/kvk-crediteur-dedup.md` |

## Onderhoud

- Nieuwe regel of statusophoging **op het moment van akkoord/oplevering**, in dezelfde commit als
  het werk zelf waar mogelijk.
- Regels niet herschrijven bij koerswijziging: status → `vervallen` + verwijzing naar wat het
  vervangt (zelfde principe als het Platform-besluitenregister).
