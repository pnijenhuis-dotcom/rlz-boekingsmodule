# Nameting feedbackrun A (negen blokken 25-09) ná deploy — werkt in productie: ja/nee per blok

niet vóór: 2026-09-26 09:00
Domeinen: werkvoorraad-controlescherm, intake-extractie, duplicaten-crediteuren, btw, verplichtingen-projecten-voorraad, werkloop-productie

Bron: rapport `docs/rapporten/2026-09-25-feedbackrun-a-factuurverwerking.md` (negen blokken, alle "werkt in productie: niet gemeten"),
BESLISSINGEN-secties van 25-09 (negen), gespreksverslag 25-09. Regel 21-09: "niet gemeten" is een schuld mét vervaldatum.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij divergentie, nooit rebase); service ÉN jobs op de docs-commit van 25-09 of later
(`gcloud run services describe rlz-backend` + `gcloud run jobs describe … spec.template.spec.template.spec.containers[0].image`). Niet live =
opdracht terugleggen mét `niet vóór:` +1 dag (hoogstens drie pogingen).

## Stap 1 — negen dispatch-onderdelen (lees-only, elk als bot-bestand op main)
`gh workflow run nameting -f onderdeel=<x>` voor: `xml-documenten`, `crediteuren-naamclusters`, `project-bronvolgorde`, `aangifteperiode`,
`crediteur-paneel`, `btw-netto`, `tabwissel`, `lijst-alles`, `comfort-controlescherm`. Zet `SINDS_FEEDBACKRUN_A` niet — de default (25-09 18:00Z)
volstaat; de deploy-tijd noteren in het rapport. Wacht per run op de bot-commit (`git fetch` + `git show origin/main:verkenning/nameting-<x>-<dd-mm>.txt`).

## Stap 2 — oordeel per blok
Per blok "werkt in productie: ja / nee / niet gemeten (ongebruikt)" mét het bot-bestand als bron; "ongebruikt" = klikpunt Peter noemen
(blok 1: document 250895e8 openen; blok 2: cluster bevestigen; blok 5: crediteur bewerken; blok 8: knop "Alles"/zoeken; blok 9: kop → regels).
Rood = fix + guard in dezelfde run (regel 19-09 poging 2), meetlat opnieuw ná deploy als vervolg.

## Definitie van af
Rapport `docs/rapporten/2026-09-26-nameting-feedbackrun-A-na-deploy.md` + INDEX + "Gelezen regels", BESLISSINGEN-alinea "Gemeten 26-09" per
sectie, regels-alinea's waar het oordeel verandert, gespreksverslag 26-09, opdracht → gedaan/. Poort: guards (`test_rapporten_*`,
`test_nameting_workflow`) groen.
