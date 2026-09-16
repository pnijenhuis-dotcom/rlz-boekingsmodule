# Rapport 16-09 (nacht) — Doorbelasting Kempen Facilities: herkoppeling doelentiteit, lees-only aansluiting verkoop ↔ inkoop in álle doelentiteiten + reconciliatieblok, Kempen Chalets

Opdracht: `opdrachten/gedaan/2026-09-16-doorbelasting-aansluiting-kf-en-herkoppeling.md` (vraag Peter 12-09). Geen migratie, geen
RLZ-/Odoo-writes, gouden set niet geraakt (geen wijziging onder app/documenten, app/intake, app/extractie, frontend/src/document).
**Werkt in productie: niet gemeten** — de code staat vóór de deploy; meetrecept als vervolg-opdracht in de inbox.

## Wat er gebouwd is

| Blok | Uitkomst |
|---|---|
| 1 Herkoppeling | `app/doorbelasting/herkoppeling.py`: whitelist-rijen zonder doel-administratie worden bij onboarding én dagelijks (sync-alles, ná de intercompany-stap) op de genormaliseerde naam vergeleken met alle actieve administraties (administratienaam én bron-identiteitsnaam). Eén exacte treffer = koppelen (bestaande `wijzig_mapping`, audit oud→nieuw + `doelentiteit_gekoppeld`); bijna-match of meerdere kandidaten = niet koppelen, audit `doelentiteit_niet_gekoppeld` → LET-OP "Koppel administratie…" met deeplink; geen kandidaat = geteld. KvK kan niet als basis dienen: de whitelist-rij draagt geen KvK. Per bron een run-audit met tellers. |
| 1 UI + teller | Rij zonder doel op Instellingen › Administraties › ‹bron› › Doorbelasting: chip "niet gekoppeld" + combobox "Koppel administratie…" (bestaande PUT, bevestigingsdialoog, audit). Teller `doorbelasting_herkoppeling` in de automatiseringen-lijst: `doel_bijna_match` is een harde voorwaarde met deeplink, `doel_niet_onboarded` is zichtbaar zonder LET-OP. |
| 2 CLI | `doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` (lees-only, nameting-allowlist): per whitelist-rij verkoop van de bron aan de doel-debiteur (geboekt én concept) ↔ inkoop in het doel op álle crediteurrecords van de bron-identiteit (IC-relatie, KvK, naam), dezelfde matchmotor als het intercompany-blok. Tabellen: sluit / ontbreekt in doel / bedrag afwijkt / status verschilt / doel niet in module / inkoop zonder verkoop. Webfilter = meting ongeldig (exit 3). Odoo-doelen via de bestaande bronabstractie. |
| 2 Reconciliatieblok | `doorbelasting_aansluiting`, dagelijks ná `doorbelasting`, per bron-administratie met actieve whitelist; vijf soorten met leesbare titel/wat/doe; acceptatie met reden; actie "Boek inkoop in doel" reist mee als er een open spiegel-taak voor die verkoop bestaat (deeplink Doorbelasten), "doel niet in module" linkt naar de whitelist-rij. Bloklabel in de frontend. |
| 3 Kempen Chalets | Koppelt via blok 1 zodra de nachtelijke sync draait ná deploy (verwacht exact op "Kempen Chalets B.V."). Niet gemeten in deze run. |

## Tests

| Poort | Uitkomst |
|---|---|
| `tests/doorbelasting/test_herkoppeling.py` | 11 groen (puur + DB: exact/bijna/meerdere/geen, afwezig-pad, idempotent, bron nooit kandidaat, inactieve rij) |
| `tests/doorbelasting/test_aansluiting.py` | 13 groen (meting, tabellen, overgeslagen, webfilter, blokfunctie met Verzamelaar + acceptatie + inhaalpad + teksten-guard, CLI dispatch + allowlist, BLOKKEN-volgorde) |
| `tests/reconciliatie/test_automatiseringen_herkoppeling.py` | 2 groen |
| Regressiebatch (reconciliatie run/rlz_dubbel/teksten/automatiseringen, optin-afwezig-pad-guard, sync-alles-cli, intercompany factuurmatch, doorbelasting mapping, beheer) | 428 groen |
| Frontend `tsc -b` + vitest reconciliatie/doorbelasting | groen (101; de chiptekst-test bijgewerkt naar "niet gekoppeld" + koppel-combobox) |

## Beslispunten Peter (defaults, in `2026-09-16-beslispunten-peter.md` opdracht 15)

Bijna-match = bestaande `_is_bijna_match`, nooit auto-koppelen; KvK-basis niet mogelijk zonder extra RLZ-call; venster ± 7 d (één motor)
i.p.v. ± 5 d; "doel niet in module" één bevinding per rij; inhaalpad-actie alleen bij een open spiegel-taak; concepten tellen mee.

## Meetrecept ná deploy (vervolg-opdracht `opdrachten/inbox/2026-09-17-doorbelasting-aansluiting-nameting.md`)

1. Deploy-check: service én jobs op hetzelfde beeld.
2. `scripts/gcp/nameting.sh doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` → tabellen letterlijk in het rapport
   (verwachting Peter: alles sluit; elke afwijking benoemd mét boekstuk). Exit 3 = webfilter, niet doorrekenen.
3. Eerste `sync-alles`-log ná deploy: regel "herkoppeling doelentiteiten: open=… gekoppeld=…" (Kempen Chalets verwacht GEKOPPELD) +
   teller op Instellingen › Boeken; bij bijna-match de LET-OP met deeplink.
4. Inzicht › Reconciliatie: blok "Doorbelasting-aansluiting" toont de bevindingen mét doe-tekst; open spiegel-taken (aantal + bedrag) uit
   het CLI-rapport.
