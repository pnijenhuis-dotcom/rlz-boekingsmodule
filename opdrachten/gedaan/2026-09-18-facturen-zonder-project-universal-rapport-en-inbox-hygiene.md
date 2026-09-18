uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-facturen-zonder-project.md

Domeinen: verplichtingen-projecten-voorraad, werkloop-productie, reconciliatie

# OPDRACHT 18-09 (avond) — Lees-only rapport "geboekte facturen zonder project" (Universal Steigerbouw + alle project-verplichte
# administraties) + inbox-hygiëne

## A. Rapport facturen zonder projectreferentie (TODO Peter 23-08: "eerst rapport, dan beslissen")
1. Lees-only CLI `facturen-zonder-project --administratie <naam|id> [--jaar 2026] [--alle-projectverplicht]` (nameting-allowlist,
   leesreplica): álle in de module GEBOEKTE inkoopfacturen waarvan één of meer regels géén project dragen, in administraties met
   `project_verplicht = true` — én, ter controle, dezelfde toets op de RLZ-kant via de gesyncte `JournalEntryLines` (regel zonder
   Project-ref op een kostenrekening 4xxx/7xxx). Per rij: administratie, boekstuk RLZ, referentie, leverancier, factuurdatum,
   boekdatum, regelnummer, grootboek, netto, btw, geboekt door (mens/automatisch), en of de btw-periode al ingediend is
   (`app/rlz/aangifte.py`). Twee tellingen: module-kant en RLZ-kant, met het verschil verklaard (facturen van vóór de module tellen
   alleen RLZ-kant).
2. **Herstelroute voorstellen, niet uitvoeren**: per rij de route die past — (a) periode open → storno 19 → project op de regels →
   her-PUT → 17 (idempotent, zelfde client-GUID's), (b) periode ingediend → tegenboek-pad; plus een schatting van het aantal per route.
   Voor Universal apart: welke facturen matchen deterministisch op een project via het bestaande werknummer-/projectcode-geheugen
   (voorstel "project X, herkomst geheugen 3× bevestigd") en welke een mens nodig hebben.
3. Rapport `docs/rapporten/2026-09-18-facturen-zonder-project.md` mét de volledige lijst (bron-id's, datums, bedragen), de twee tellingen,
   de routeverdeling en het voorstel; INDEX; Gelezen regels. Géén RLZ-write, géén statuswissel. Beslispunt Peter aan het eind: herstellen
   in bulk (nieuwe opdracht) of laten staan; en of "regel zonder project op een project-verplichte administratie" een dagelijkse
   reconciliatie-bevinding wordt (start in `meten`).

## B. Inbox-hygiëne
`opdrachten/lopend/` bevat vijf bestanden van vandaag die al lang afgerond zijn (veldapp-ux-run-b, veldwerker-rol-wijzigen,
volumerem-handmatig, webtoestel-edge-android, zoekveld-klantenlijst-dagkop-sticky) terwijl de rapporten ervan bestaan en de
opdrachten óók in `gedaan/` horen. Verplaats ze naar `gedaan/` (of verwijder de dubbele kopie als het duplicaten zijn — controleer
eerst), en zoek de oorzaak in `scripts/cc_inbox.sh` (waarschijnlijk: parallelle agenten verplaatsen naar lopend maar alleen de
hoofdagent ruimt op; of een run die zonder commit eindigde). Fix zodat `rlz inbox status` nooit "loopt" toont voor werk dat af is;
guard-test in de inbox-tests. Rapportregel in het A-rapport volstaat.

## Afronding
Rapport + INDEX + Gelezen regels; geen migratie; "werkt in productie: n.v.t. (lees-only)". Één regel voor Peter: aantal facturen zonder
project bij Universal, hoeveel automatisch herstelbaar, hoeveel achter de aangiftepoort.
