# Nameting + nazorg kassarapport automatisch typeren — poging 1 (19-09, ~16:00): NIET GEMETEN, deploy geblokkeerd door een stille push-fout

**Opdracht:** `opdrachten/gedaan/2026-09-19-nameting-kassarapport-autotype-na-deploy.md` (vervolg op
`docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md`). Domeinen: omzet, reconciliatie, werkloop-productie.

**Werkt in productie: niet gemeten.** Stap 0 (deploy-check) faalde: de commit `a5c0663` mét `app/omzet/autotype.py` stond bij de start van
deze run niet op origin en dus niet in productie. Service `rlz-backend` én job `rlz-reconciliatie` draaien beide op image
`backend:0bad465…` (gecontroleerd 19-09 ~15:55 via `gcloud run services list` / `jobs describe`; laatste groene deploy-run
35432683380 = `0bad465`). Op dat image bestaat de nazorg-CLI `kassarapport-autotype-nazorg` niet; stap 1–3 zijn daarom NIET uitgevoerd
(geen job-executie, geen lokaal proces tegen productie). De echte meting staat als nieuwe opdracht in de inbox (poging 2).

## Wat er aan de hand was (oorzaak, met bewijs)

| Tijd (CEST) | Gebeurtenis |
|---|---|
| 10:39 | `0bad465` gecommit en gepusht → deploy 35432683380 groen (service + jobs op `0bad465`). |
| 12:18 | nameting-bot commit `78aca7a` ("nameting 19-09 alles — Oordeel: ROOD", 8 bestanden onder `verkenning/nameting-*-19-09.txt`) rechtstreeks op origin/main. |
| 12:44 | `86ecbad` (Afsluiten?-tab) lokaal gecommit; de Stop-hook-push was vanaf hier **non-fast-forward** en faalde. De hook schrijft alleen een stderr-regel + exit 1 — in een `claude -p`-inbox-run ziet niemand dat. |
| 12:44–15:42 | Vijf verdere commits (`a5c0663`, `64b45b5`, `6a7215c`, `27c0950`, `d589972`) elk mét falende push. De cc-inbox-tick slaat een gedivergeerde branch bewust over ("pull overgeslagen — ff-only mislukt"), dus niets herstelde zich. |
| 15:47 | Deze run start; `git rev-list origin/main..main` = 6, `main..origin/main` = 1. |

Gevolg: drie uur lang géén deploy, terwijl vier "nameting ná deploy"-opdrachten (kassarapport-autotype, ic-spiegel-rood, projecten-afsluiten-tab,
projectnummer-afgesloten) in de inbox op die deploy wachtten. Zonder ingreep had élke volgende run hetzelfde gedaan.

## Wat ik gedaan heb

1. **Merge `origin/main` in `main`** (`6dafb0f`, `--no-ff`, alleen 8 nieuwe tekstbestanden onder `verkenning/`, geen conflict). Bewust een
   merge en géén rebase: de hashes `a5c0663`/`6a7215c`/`27c0950`/`d589972` staan letterlijk in rapporten, BESLISSINGEN en de INDEX en moeten
   blijven kloppen. Ná de merge: ahead 7, behind 0 → de Stop-hook kan pushen → deploy volgt (~15 min) → pas dán is stap 1 mogelijk.
2. **Nulmeting Van Boxtel op de leesreplica** (`db_lezen.sh --administratie cd973c86-…`, READ ONLY, ~15:58) als "voor"-stand voor poging 2:
   - Open documenten (niet geboekt/afgewezen/afgevoerd): 5 × `Journaal *.pdf` soort `inkoopfactuur` status `te_controleren`, ontvangen 08-09 11:20:
     `8631403e` Journaal 31-8, `37e1b23e` Journaal 1-9, `cbef27bc` Journaal 2-9, `0b571db4` Journaal 3-9, `4e120087` Journaal 4-9; plus
     `64e46c8a` Kassacentrum.nl-factuur (18-09) en 7 × `verwijderd` (InboekDienst/weekstaten 14-09).
   - Laatste afgeronde run `772e6c3c` (19-09 06:44): blok omzet 13 afwijkingen = **4 × `kassarapport_in_werkvoorraad` signaal
     `profx_journaal`** (Journaal **31-8**, 1-9, 2-9, 3-9), **1 × signaal `omzetrekeningen`** (Journaal 4-9, 1/1 regels), **8 ×
     `omzet_in_inkoopstroom`** (RLZ-04-00000684…699, Journaal 5-9 t/m 13-9, geboekt als inkoop — mens-werk, storno achter de aangiftepoort).
   - Correctie op de opdrachttekst: de "vierde profx-treffer" is **Journaal 31-8**, niet een los document; Journaal 4-9 heeft géén
     parser-treffer (alleen het zachte signaal) en blijft dus terecht een melding mét knop.
3. Vervolg-opdrachten in de inbox: (a) `2026-09-19-nameting-kassarapport-autotype-na-deploy-poging-2.md` (zelfde meetrecept, stap 0 mét de
   concrete image-toets, verwachting geconcretiseerd: dry-run "1 administratie(s), 4 kandidaat/kandidaten" = 31-8/1-9/2-9/3-9; ná de echte
   run kantoorbreed 0; leesreplica 4 × soort `kassarapport` + 4 × audit `soort_automatisch_gewijzigd` + 1 × `kassarapport_autotype_run`
   verwacht 4/gedaan 4; `--alleen omzet --lees-only` → Van Boxtel 1 × `kassarapport_in_werkvoorraad` (4-9) + 8 × `omzet_in_inkoopstroom`;
   Inzicht › Reconciliatie 340 → 336 aandacht; teller `kassarapport_autotype` in de systeemmail); (b)
   `2026-09-19-stop-hook-push-non-fast-forward-stille-deploy-blokkade.md` (procesfix, zie hieronder).

## Bevinding voor de werkloop (niet gebouwd — vervolg-opdracht b)

De keten "Stop-hook pusht → deploy → nameting" heeft één stille faalmodus: een bot-commit op origin terwijl een run bezig is. Voorstel (te
toetsen in de vervolg-opdracht, niet hier besloten): de Stop-hook doet bij een non-fast-forward eerst `git fetch` + `git merge --no-ff
origin/main` **uitsluitend als de binnenkomende commits alleen `verkenning/nameting-*`/`verkenning/lezen-*`-bestanden raken** (bot-only),
en pusht daarna; anders blijft het een luide fout mét macOS-melding, óók in `claude -p`. De inbox-tick logt bij "ff-only mislukt" nu wel,
maar meldt niet; `rlz inbox status` zou "origin gedivergeerd (N lokaal / M remote) — deploy staat stil" moeten tonen. Nooit rebase, nooit
force. Regeltekst: `docs/regels/werkloop-productie.md` alinea "Stop-hook-push non-fast-forward = stille deploy-blokkade (19-09)".

## Keuzes die ik zelf gemaakt heb (Peter kijkt niet mee)

- Niet wachten in deze run op de deploy: de push gebeurt pas bij het einde van de run (Stop-hook; `git push` staat in de deny-lijst), dus
  wachten had niets opgeleverd. Wél de blokkade weggenomen zodat de deploy nu daadwerkelijk volgt.
- Merge in plaats van rebase (hashes in documentatie), `--no-ff` zodat de reden in de git-historie staat.
- Geen job-executie op het oude image "om te kijken": het commando bestaat daar niet, en een mislukte executie zou als ruis in de
  reconciliatie-job-logs komen.
- BESLISSINGEN-status blijft "niet gemeten" mét deze poging als rij; de omzetting naar "gemeten <datum>" gebeurt in poging 2.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/omzet.md` (266 regels)
- `docs/regels/reconciliatie.md` (130 regels)
- `docs/regels/werkloop-productie.md` (76 regels — stand vóór de run; ná de run 82)
