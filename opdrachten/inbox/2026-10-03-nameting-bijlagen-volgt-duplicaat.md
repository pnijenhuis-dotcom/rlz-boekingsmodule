# Nameting "bijlage volgt het duplicaat naar het origineel" ná deploy (poging 1)

niet vóór: 2026-10-03 14:00

Domeinen: intake-extractie (LEESPLICHT `docs/regels/intake-extractie.md`), werkloop-productie (LEESPLICHT).
Lees-only; Peters "ja" is de enige poort naar een schrijvende stap. Hoogstens drie pogingen (regel 22-09 (3)); daarna `mislukt/` mét het
klikpunt.

Bouw: commit van 03-10 (BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)" subkop
"Bijlage volgt het duplicaat naar het origineel (03-10)"; rapport `docs/rapporten/2026-10-03-bijlagen-volgt-duplicaat.md`).

## Stap 0 — deploy-check (service ÉN jobs), pas daarna meten
- `git rev-list --count main..origin/main` > 0 → `git merge --no-ff origin/main` (nooit rebase). Deploy-check op het image van service én
  jobs (`spec.template.spec.template.spec.containers[0].image`) = de commit van 03-10 of later. Niet live → de opdracht terug in inbox/
  mét `niet vóór:` +1 dag.

## Meetrecept
1. `gh workflow run nameting -f onderdeel=bijlagen-factuur` (= `bijlagen-nabundelen --dry-run` kantoorbreed + `db-lezen documenten-open
   --administratie "Universal Steigerbouw"`). Lees het bot-bestand `verkenning/nameting-bijlagen-factuur-<dd-mm>.txt` van main:
   - TOTAAL-regel mét de nieuwe teller `… K via duplicaat — DRY-RUN`. Heeft Peter de terminal-opdracht
     `opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md` nog niet gedraaid: K ≥ 6 en per Steigerbouw-mail de regel
     "Factuur RLZ-20801430xx … ← factuurdetails-….pdf […]: kandidaat — via duplicaat → Factuur RLZ-20801430xx …" (3088, 3092, 3093, 3094,
     3125, 3131). Wél gedraaid: K = 0 en in `db-lezen documenten-open` staan die zeven `factuurdetails-….pdf` niet meer open.
   - RLZ-2080143044: "via afgewezen factuur → …" óf "overgeslagen · factuur afgewezen (…) — bijlage ook afwijzen?: 1". Schrijf letterlijk
     over welke van de twee het is.
   - 0 mislukt; "geen factuur-document in deze mail" mag alleen nog voorkomen bij mails zonder énige factuur (ook niet afgevoerd/afgewezen).
2. Heeft Peter de échte run gedraaid: request-log `GET …/documenten/<id>` 200 op een losse Steigerbouw-bijlage ná de run → is
   `factuur_afgewezen_in_mail` gevuld (3044-casus) = de chip is getoond; audit `bijlage_gekoppeld` mét `herkomst = nazorg
   bijlagen-nabundelen` ≥ 6 sinds de run (`db_lezen.sh --sql` op `platform.audit_event`), audit `bijlage_naar_origineel` (verhuizingen,
   verwacht 0 bij Steigerbouw — alle zeven stonden los).
3. Live-pad (alleen meten als het zich voordeed): job-log `rlz-intake-imap`/`-kempengroep` sinds de deploy: een intake-bericht mét
   uitkomst `dubbel` én in hetzelfde bericht `bijlage` → het bijlage-`document_id` = het ORIGINEEL (niet het exemplaar). Niet
   voorgekomen = "niet gemeten", geen rode vlag.
4. Rapport `docs/rapporten/2026-10-03-nameting-bijlagen-volgt-duplicaat.md` + INDEX + "Gelezen regels" + "werkt in productie:
   ja/nee/niet gemeten" per punt; BESLISSINGEN subkop alinea "Gemeten <dd-mm>"; opdracht → gedaan mét kopregel.
