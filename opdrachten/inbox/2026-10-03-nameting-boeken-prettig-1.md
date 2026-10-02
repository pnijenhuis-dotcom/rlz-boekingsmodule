# Nameting "Boeken prettig 1" ná deploy — bijlagen bij de factuur, rustig scherm, samenvoegen, project/overhead/balans (poging 1)

niet vóór: 2026-10-03 09:00

Domeinen: intake-extractie, werkvoorraad-controlescherm, verplichtingen-projecten-voorraad, werkloop-productie

Bouw: commits van 02-10 (zes punten, één commit per punt; BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM,
OVERHEAD AUTOMATISCH (Peter 02-10)"; rapport `docs/rapporten/2026-10-02-boeken-prettig-1.md`). Hoogstens drie pogingen (regel 22-09 (3));
daarna `mislukt/` mét het klikpunt.

## Stap 0 — deploy-check (service ÉN jobs), pas daarna meten
- `git rev-list --count main..origin/main` > 0 → `git merge --no-ff origin/main` (nooit rebase). Deploy-check op het image van service én
  jobs (`spec.template.spec.template.spec.containers[0].image`) = de laatste commit van 02-10 of later. Niet live → de opdracht terug in
  inbox/ mét `niet vóór:` +1 dag.

## Meetrecept (lees-only; Peters "ja" is de enige poort naar een schrijvende stap)
1. **Punt 1 — bijlagen bij de factuur:** `gh workflow run nameting -f onderdeel=bijlagen-factuur` (= `bijlagen-nabundelen --dry-run`
   kantoorbreed + `db-lezen documenten-open --administratie "Universal Steigerbouw"`). Lees het bot-bestand `verkenning/nameting-bijlagen-factuur-<dd-mm>.txt`
   van main: de TOTAAL-regel ("N e-mails, K kandidaten, …") + de lijst "factuur ← bijlagen" per administratie. Verwacht: tientallen
   kandidaten bij Universal Steigerbouw (de verhuurmails van Universal Nederland), 0 mislukt. Schrijf de dry-run-uitkomst letterlijk in het
   rapport. **De échte run is géén onderdeel van deze nameting**: Cowork legt de dry-run-lijst aan Peter voor; pas ná zijn "ja" draait
   `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|bijlagen-nabundelen|--uitvoeren"` in een
   owner-sessie (terminal-opdracht aanmaken in `opdrachten/terminal/`).
   Request-log sinds de deploy: `GET …/bijlagen/{id}/bestand` (tabblad gebruikt?) + intake-berichten mét uitkomst `bijlage` (job-log
   rlz-intake-imap). Dagteller `bijlagen_gebundeld` in de reconciliatiemail van 03-10 06:30 (verwacht/gedaan/overgeslagen).
2. **Punten 2–6 — klikpunt Peter** op `/documenten/3ee6edf0…/f00117f4…?soort=inkoopfactuur` ná deploy: (2) geen chips onder crediteur/
   kopgegevens/regels, "Herkomst tonen" per blok klapt ze uit; (3) vinkje "Splitsen per regel" boven de twee regels, uitvinken = één regel
   751,15 / 157,74; (4) projectveld leeg (niet "Afgesloten 25147 …" uit de historie); (5) projectverdeling staat klaar voor het volledige
   bedrag volgens de omzetsleutel van de maand van de factuurdatum (juni 2026), check "Projectverdeling" groen, boeken kan; (6) een
   voorraad-/activaregel (3xxx/0xxx) heeft geen projectveld en telt niet mee in de verdeling. Request-log: `GET …/boekvoorstel` op
   f00117f4 ná de deploy = bewijs dat het scherm geopend is; `db-lezen project-prefill-herkomst --administratie "Universal Steigerbouw"`
   (herkomst `leverancier_geheugen` op het project mag niet meer voorkomen).
3. Rapport `docs/rapporten/2026-10-03-nameting-boeken-prettig-1.md` + INDEX + "Gelezen regels" + per punt "werkt in productie: ja/nee/niet
   gemeten"; BESLISSINGEN-sectie alinea "Gemeten 03-10"; opdracht → gedaan mét kopregel.
