Domeinen: werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-23 09:00

# Nameting "Corrigeren…" — bewijs ná het klikpunt van Peter op de RLZ-testadministratie (onderdeel `corrigeren`)

**Context:** rapport `docs/rapporten/2026-09-22-nameting-corrigeren-testadministratie.md` (poging 2, 22-09): de storno-cyclus kon niet
gedraaid worden omdat de RLZ-testadministratie "Administratiekantoor Nijenhuis (test)" (`faae29c5`) gearchiveerd staat zonder credential;
de schrijvende stappen zijn een klikpunt van Peter (tien stappen in dat rapport, sectie "Klikpunt Peter"). De lees-only meetlat staat sinds
de commit van 22-09 als dispatch-onderdeel `corrigeren` in `.github/workflows/nameting.yml` (+ querybibliotheek `correcties`). Deze opdracht
schrijft NIETS naar RLZ en dearchiveert NIETS — ze leest alleen wat Peter intussen deed. Kan gcloud/gh in deze run niet inloggen: NIET stil —
klikpunt Peter mét de letterlijke commando's.

## Stap 0 — deploy-check (service ÉN jobs op een image ≥ de commit van 22-09 mét `app/lezen/queries/correcties.sql`; `git rev-list --count
main..origin/main` toetsen en `merge --no-ff` als > 0)
```
gcloud run services describe rlz-backend --region europe-west4 --format='value(spec.template.spec.containers[0].image)'
gcloud run jobs list --region europe-west4 --format='value(name,spec.template.spec.template.spec.containers[0].image)'
```

## Stap 1 — het onderdeel draaien en het bot-bestand lezen
`gh workflow run nameting -f onderdeel=corrigeren` → `gh run watch <id>` → `git fetch origin && git show origin/main:verkenning/nameting-corrigeren-<dd-mm>.txt`
(een meting telt pas als het bot-bestand op main staat). Lees de oordeelregel `Oordeel: POST corrigeren 200 = N, 409 = M, 5xx beide routes = K — …`.

## Stap 2 — beslisboom
- **N ≥ 1 (Peter heeft geklikt):** (a) uit het bot-bestand: rlz-lezen TEST-CORRIGEREN-stukken → verwacht het oude GUID (cyclus 0) `Status` 1 en
  het herboekte GUID (cyclus 1) `Status` 2 (ná de terugweg óók 1); `db-lezen correcties` → ≥ 2 audits `document_gecorrigeerd` mét reden, oud
  boekstuk en oud extern id, huidige stand `boek_cyclus` 2, status klaar_om_te_boeken; request-log: per correctie precies één `POST …/corrigeren`
  200 én (stap 5 van het klikpunt) één 409; 0 × 5xx. (b) Bonus-toets `KLIKTEST-ACC-1` (`GET …/corrigeer-toets` 200 in het request-log; blokkade
  `verdwenen` is niet uit het log af te lezen — vraag het Peter niet, noteer "niet meetbaar via log"). (c) Rapport
  `docs/rapporten/<datum>-nameting-corrigeren-na-klikpunt.md` + INDEX + "## Gelezen regels"; alinea "Gemeten <datum>" onder BESLISSINGEN
  "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)" + `docs/regels/werkvoorraad-controlescherm.md`; registerrij-status
  → "werkt in productie: ja/nee"; CLAUDE.md werkvoorraad rij 8 bijwerken (één regel).
- **N = 0 en K = 0 (nog geen klik):** géén leeg rapport. Zet bovenin dít bestand `niet vóór: <morgen> 09:00` (rij (k)) en leg het terug in
  `opdrachten/inbox/` mét één logregel in `opdrachten/log/`; hoogstens drie keer (tel de pogingen in een regel "herlegd: N×" onder de kopregel),
  daarna naar `opdrachten/mislukt/` mét kopregel "klikpunt Peter niet uitgevoerd — zie rapport 22-09, sectie Klikpunt". Geen commit nodig behalve
  de verplaatsing zelf.
- **K ≥ 1 (5xx op een corrigeer-route):** dat is een productiefout — reconstrueer de request(s) uit Cloud Logging (`jsonPayload`, `textPayload`
  rond het tijdstip), lees de `document_correctie_mislukt`-audit via `db-lezen correcties`, en schrijf een BUG-rapport mét fix + guard in dezelfde
  run (regel 19-09: NameError/5xx op een gebouwde route = systeemfout van de bouw).

## Stap 3 — poort en afronding
Volledige poort alleen als er code wijzigt (vervolg-tak K ≥ 1); anders de docs-guards (`tests/unit/test_rapporten_*`, `test_claude_md_*`,
`test_regels_index`). Opdracht → `gedaan/` mét kopregel; committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat). Peter kijkt niet
mee: vragen stellen kan niet, kies zelf en leg keuzes vast in het rapport.
