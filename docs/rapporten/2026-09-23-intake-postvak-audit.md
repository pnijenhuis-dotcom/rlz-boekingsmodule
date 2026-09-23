# Intake-postvak-audit — facturen@kempengroep.nl → facturen@ak-nijenhuis.nl → module (Peter 22-09 avond: "dubbele controle welke facturen wel en niet zijn doorgekomen")

**Datum:** 23-09-2026 · **Status: MEETRECEPT + SKELET — de meting zelf volgt als bot-bestand** `verkenning/nameting-intake-postvak-audit-<dd-mm>.txt` (dispatch-onderdeel `intake-postvak-audit`, vervolg-opdracht `opdrachten/inbox/2026-09-23-nameting-intake-postvak-audit-herstelrun-en-forward-uit.md`). **Werkt in productie: niet gemeten.** Hoofdrapport: `docs/rapporten/2026-09-23-intake-tweede-postvak-kempengroep-message-id-postvakbewaking.md`; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)".

## Waarom dit rapport nu geen cijfers draagt

De audit leest beide postvakken (IMAP, BODY.PEEK) én de module-tabellen. Dat kan alleen op een job-image die beide IMAP-credentials draagt; die image bestaat pas ná de deploy van de commit die dit rapport bevat. `nameting@` heeft geen secrets, en een lokaal proces tegen productie is verboden (regel Peter 08-09). De opdracht vroeg dit rapport "vóór de bouw van A–C" — de CLI is als eerste gebouwd en getest (`tests/intake/test_postvak_audit.py`, 10), de meting is als eerste stap van de vervolg-opdracht ingepland (niet vóór 23-09 09:00). Dat is een bewuste keuze: liever één dag later een échte tabel dan nu een lege.

## Meetrecept (lees-only)

- `gh workflow run nameting -f onderdeel=intake-postvak-audit` (of `scripts/gcp/nameting.sh intake-postvak-audit --sinds 2026-07-01 --detail`) → executie op `rlz-reconciliatie` (INTAKE-envset) → bot-bestand op main.
- Het rapport bevat: mappen gelezen per postvak (INBOX / [Gmail]/Spam / [Gmail]/All Mail; -1 = map niet leesbaar), tellers, `UITVAL per bronbericht` (datum · afzender · onderwerp · bestanden → doorgifte (map, gelezen, koppelvorm) → module → oorzaak · Message-ID), `RECHTSTREEKS zonder module-spoor`, en mét `--detail` alle bronberichten; slot `Oordeel: GROEN|ROOD — …`.

## Rapporttabel (in te vullen uit het bot-bestand)

| | Aantal |
|---|---|
| Bronberichten mét factuurbijlage in facturen@kempengroep.nl sinds 01-07-2026 | … |
| Aangekomen in facturen@ak-nijenhuis.nl (INBOX + Spam + Alle e-mail) | … |
| Met module-spoor (intake-bericht en/of document) | … |
| (a) nooit doorgestuurd | … |
| (b) aangekomen in Spam en daardoor overgeslagen | … |
| (c) aangekomen in INBOX maar niet verwerkt (gelezen-vlag / andere oorzaak) | … |
| Omgekeerd: rechtstreeks in ak-nijenhuis mét factuurbijlage zonder module-spoor | … |

Per bronbericht (kolommen zoals de CLI ze print): ontvangen kempengroep → aangekomen ak-nijenhuis (map, gelezen, koppelvorm) → verwerkt module (documentstatus · administratie · boekstuk) → oorzaak. Koppelvormen: `message_id` (forward behield de Message-ID), `references` (bron-Message-ID in References/In-Reply-To), `bijlage_sha256` (handmatige Fwd, zelfde bytes), `bestandsnaam` (laatste redmiddel, zichtbaar gelabeld).

## Wat er daarna gebeurt met wat mist

Alles wat in het rapport zonder module-spoor staat gaat mét de bestaande dedup alsnog de intake in (herstelrun B): `intake-postvak-kempengroep-verwerken --sinds 2026-07-25` en `intake-postvak-verwerken --sinds 2026-07-25` op de job-image (owner-sessie Peter, `gcloud run jobs execute … --wait`); de logregels VERWERKT / AL-VERWERKT / NIET-VERWERKBAAR / DUBBEL-VIA-FORWARD zijn het bewijs per bericht; byte-identieke dubbelen worden `mogelijk_duplicaat_van` → duplicaat-afvoer, zelfde Message-ID = AL-VERWERKT. Berichten ouder dan het venster van 60 dagen die in de audit als uitval staan, verwerkt Peter via de .eml-upload of een langer `--sinds`.

## Gelezen regels

- `docs/regels/intake-extractie.md` (322 regels)
- `docs/regels/reconciliatie.md` (282 regels)
- `docs/regels/werkloop-productie.md` (306 regels)
