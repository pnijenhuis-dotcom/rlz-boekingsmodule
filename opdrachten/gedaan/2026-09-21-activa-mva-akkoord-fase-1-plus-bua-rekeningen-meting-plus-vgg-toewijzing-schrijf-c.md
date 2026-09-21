uitgevoerd 2026-09-21 (poging 2 ná WIP-branch `wip/2026-09-21-activa-mva-akkoord-fase-1-plus-bua-rekeningen-meting-plus-vgg-toewijzing-schrijf-c`), rapport: docs/rapporten/2026-09-21-activa-fase1-bua-vgg-toewijzing-universal-overhead.md

Domeinen: activa, btw, vgg-odoo-migratie, verplichtingen-projecten-voorraad

# OPDRACHT 21-09 — Drie besluiten Peter: (A) Activa/MVA AKKOORD → fase 1; (B) BUA-rekeningen: lees-only meting + bulk-voorstel;
# (C) VGG: Toewijzing pand + soort verkoop voor RLZ-01-00000082 → SCHRIJF c; (D) capture Universal overhead = géén OVH-project

## A. Activa / MVA — AKKOORD Peter 21-09 ("activa, JA") op `docs/ONTWERP_ACTIVA_MVA.md` mét alle defaults §8
Capture: status ONTWERP → AKKOORD 21-09 (BESLISSINGEN, `docs/regels/activa.md`, CLAUDE.md-regel "geen bouw vóór akkoord" vervangen).
Bouw fase 1 (ontwerp §7): register-lezer RLZ `FixedAssets` (root-only enumeraties, Universal 403 = probe), detectie bij boeken
(MVA-rekening = `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx, bedrag ≥ activeringsgrens € 450 excl. óf RLZ `FixedAssetAlertAmount`)
→ voorstel-kaart "Activum aanmaken?" op het controlescherm mét categorie/termijn uit §3 (steigermateriaal 5 jr lineair, restwaarde 0 —
besluit 16-09), mens bevestigt (opt-in "automatisch aanmaken" per administratie, default UIT, guard-test afwezig-pad), schrijven in RLZ
`FixedAssets` via de bestaande client (PUT client-GUID, terug-lezen), reconciliatieblok `activa` (start in `meten`): MVA-boeking zonder
activum, activum zonder boeking, afschrijving niet geboekt. Eerst op de administratie die de nulmeting (`activa-nulmeting`) als rijkste
aanwijst; Odoo later (§8 punt 6). Geen eigen fiscale rekenregels — toetsen en signaleren (§3).

## B. BUA — welke rekeningen krijgen het kenmerk `btw_aftrek_uitgesloten`? (vraag Peter 21-09)
Lees-only meting over álle administraties (leesreplica `grootboekrekening`-cache, geen RLZ-call): rekeningen 4xxx waarvan de naam matcht op
representatie | relatiegeschenk | geschenk | kantine | consumpties | eten en drinken | lunch | diner | horeca | personeelsfeest |
personeelsuitje | bedrijfsuitje | giften | sponsoring (+ RGS-stam `WBedRepKos…`/`WPerKan…` waar `SystemAccountList` er is). Rapporttabel:
rekening × aantal administraties × geboekt bedrag 2026 × huidige stand van het kenmerk. Daaruit een BULK-voorstel (Peters voorkeur nog
open: bulk vs per administratie — het rapport maakt de keuze concreet), als lees-only CLI `bua-kandidaten` + een schrijvende CLI
`bua-kenmerk-zetten --administratie|--alles --dry-run` (uitvoering pas ná Peters "ja" op het rapport, via job-image). Fiscale nuance in het
rapport (Peter is accountant, geen basisuitleg): horeca-btw is nooit aftrekbaar (art. 15 lid 5 Wet OB); BUA-verstrekkingen aan personeel/
relaties zijn aftrekbaar tot € 227 per begunstigde per jaar — het kenmerk is bewust CONSERVATIEF (altijd in de kosten), dus noem in het
rapport welke rekeningen daardoor mogelijk te veel btw in de kosten zetten en of een drempel-variant zinvol is (voorstel, geen bouw).

## C. VGG — beslispunt 1 BESLIST (Peter 21-09 "ik volg jouw advies"): Toewijzing pand + soort `verkoop` voor RLZ-01-00000082
Voer de toewijzing uit via het bestaande toewijzingspad (`pand_boeking`, herkomst `mens`, actor Peter via opdracht-referentie in de
audit) — ná deploy op de job-image, nooit lokaal tegen productie; daarna `vgg-odoo-stap0 --boekstuk RLZ-01-00000082` (SCHRIJF c,
bewijspaar posten + reconciliëren op company 6) volgens de regels van blok 12; het SCHRIJF-c-rapport is de GO-vraag aan Peter vóór
`SCHRIJF d` (volledige run). Blijft het bewijspaar niet vertaalbaar (8000 nog ongemapt ondanks rol 803100): STOP mét de exacte reden,
geen mapping verzinnen.

## D. Capture — Universal Steigerbouw: overhead blijft via de omzetsleutel over de actieve projecten, GÉÉN OVH-project (Peter 21-09
"Universal moet juist overhead verdelen over projecten, zo houden")
Regel verplichtingen-projecten 1 ("overhead → intern OVH-project") is voor Universal bewust NIET van toepassing: OVH-project alleen waar
de klant dat wil; de omzetsleutel-verdeling is het patroon voor Universal. Vastleggen in `docs/regels/verplichtingen-projecten-voorraad.md`
+ BESLISSINGEN-rij + CLAUDE.md-regel 1 nuanceren ("of pro rato over actieve projecten per klantkeuze"); beslispunt "OVH-project
Universal" sluiten in de open-puntenlijst; guard dat de `facturen-zonder-project`-CLI Universal-overhead niet als bevinding telt (is al zo
— bevestigen met een test).

Rapport per onderdeel of één gebundeld rapport mét vier secties; INDEX; Gelezen regels; WAT_IS_NIEUW voor A.
