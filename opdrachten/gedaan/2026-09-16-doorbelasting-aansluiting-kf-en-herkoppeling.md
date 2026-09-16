> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-doorbelasting-aansluiting.md

# OPDRACHT 16-09 (nacht) — Doorbelasting Kempen Facilities: (1) doelentiteit-herkoppeling bij onboarding, (2) lees-only aansluiting KF-verkoop 2026 ↔ KF-inkoop in álle doelentiteiten + reconciliatieblok, (3) Kempen Chalets koppelen (vraag Peter 12-09, ná VGG run 2)

**Vraag Peter (12-09):** zeker weten dat álle verkoopfacturen van Kempen Facilities 2026 als inkoopfactuur in álle doelentiteiten
staan (incl. Mantelzorg) — ook wat via Zenvoices of handmatig ging. De bestaande doorbelasting-reconciliatie toetst alleen
module-doorbelastingen; het nieuwe `intercompany`-blok (16-09) toetst verkoop↔inkoop per IC-paar op nummer/bedrag maar rapporteert
niet per doelentiteit-whitelist en kent geen "doel niet in module".

**Gat (12-09, Cowork):** whitelist-rij Kempen Chalets is 15-08 geseed zónder `doel_administratie_id`; de administratie is later
onboarded en nooit herkoppeld (alleen naam-match op seed-moment, geen hook, geen UI; "+ Doelentiteit toevoegen" toont alleen admins
buiten de whitelist). Zelfde klasse als Mantelzorg 01-09 = stille no-op (KP7 punt 6).

Pre-feature-ritueel: `verkenning/16_DOORBELASTING_KEMPEN.md`, BESLISSINGEN "KEMPEN-DOORBELASTING", "INTERCOMPANY-FACTUURMATCH +
RC-AANSLUITING (Peter 16-09)", "INTERCOMPANY-LEVERANCIERS INSTELBAAR", "HERSTELRUN 07-09 — GEEN STILLE NO-OP", `app/doorbelasting/`,
`app/intercompany/`, `app/reconciliatie/`, nameting-allowlist `scripts/gcp/nameting.sh`.

## Blok 1 — Herkoppeling doelentiteit (geen stille no-op)
- Bij onboarding van een administratie én dagelijks in `sync-alles`: whitelist-rijen zonder `doel_administratie_id` matchen op
  genormaliseerde naam (KvK als die er is wint) → exact = koppelen + audit `doelentiteit_gekoppeld`; bijna-match = LET-OP mét
  handeling "Koppel administratie…" (combobox op de niet-gekoppelde whitelist-rij in Instellingen › Doorbelasting). Nooit raden.
- Teller in de automatiseringen-lijst; guard-test afwezig-pad.

## Blok 2 — Lees-only CLI `doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` + reconciliatieblok
- KF-verkoop (geboekt + concept, RLZ SalesInvoices) → doelentiteit uit `Entity` (via whitelist/IC-relatie/naam) → inkoop in de
  doeladministratie mét crediteur = KF-identiteit (álle crediteurrecords, KvK) + genormaliseerd factuurnummer (`referentie.py`),
  terugval bedrag cent-exact + datum ± 5 d. Tabellen: sluit / ontbreekt in doel / bedrag afwijkt / doel niet in module / status
  verschilt; omgekeerd KF-inkoop zonder KF-verkoop. Odoo-doelen via de adapter. Webfilter = meting ongeldig. In de nameting-allowlist.
- Hergebruik `app/intercompany/` waar het kan (één matchmotor); verschil met het IC-blok = whitelist-volledigheid ("hoort er een
  inkoop te zijn?") en "doel niet in module". Daarna reconciliatieblok `doorbelasting_aansluiting` (dagelijks, per bronadministratie
  mét actieve whitelist) mét actie per rij ("Open verkoopfactuur", "Boek inkoop in doel" = bestaande inhaalpad).

## Blok 3 — Kempen Chalets + nameting
- Chalets koppelen via blok 1 (exact op naam verwacht), provisie-GB conform de whitelist-rij; open spiegel-taken rapporteren (aantal +
  bedrag). Ná deploy: `nameting.sh doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` → tabellen in het rapport
  (verwachting Peter: alles sluit; elke afwijking letterlijk benoemd mét boekstuk).

## Afronding
Migratie alleen als blok 1 een kolom nodig heeft; gouden set n.v.t. tenzij `app/documenten` geraakt; WAT_IS_NIEUW; BESLISSINGEN
"DOORBELASTING — AANSLUITING KF ↔ DOELENTITEITEN + HERKOPPELING (Peter 12-09/16-09)"; CLAUDE.md één verwijsregel onder
Kempen-doorbelasting; rapport + INDEX mét "werkt in productie: ja/nee/niet gemeten"; beslispunten (bijna-match-drempel, venster
± 5 d) als defaults in `2026-09-16-beslispunten-peter.md`.
