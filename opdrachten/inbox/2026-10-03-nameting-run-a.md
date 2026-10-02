# Nameting run A 02-10 (punten 7–17) — ná deploy en de 06:30-run van 03-10

niet vóór: 2026-10-03 09:00
Domeinen: werkvoorraad-controlescherm, verplichtingen-projecten-voorraad, accordering-native-app, reconciliatie, werkloop-productie

Hoogstens drie pogingen (regel 22-09 (3)); elke poging die te vroeg is legt zichzelf terug mét `niet vóór:` +1 dag.

## Stap 0
Deploy-check: service ÉN jobs op een image ≥ commit `07f4a71` (punt 17, migratie 0175) — `gcloud run services describe` / `gcloud run jobs describe … spec.template.spec.template.spec.containers[0].image`; `main..origin/main` toetsen en zo nodig `merge --no-ff`. Niet live = terugleggen.

## Meetlatten (lees-only, bot-bestanden op main)
1. **Punt 11** — `gh workflow run nameting -f onderdeel=project-dubbel` → `verkenning/nameting-project-dubbel-<dd-mm>.txt`: dry-run `project-dubbel-samenvoegen --administratie "Universal Steigerbouw" --nummer 26149 --dry-run` (verwacht blijver 42b27746… "26149 Poeldijk, Anjerstraat 245 (Weboma)", verliezer 0b394b0d… "26149" met 0 koppelingen → "zou afsluiten") + `projecten-dubbele-nummers`. **De dry-run-uitvoer gaat naar Cowork; de ÉCHTE run (`--uitvoeren`) uitsluitend ná Peters "ja"** — commando staat in `docs/rapporten/2026-10-02-run-a.md` punt 11.
2. **Punt 14** — `gh workflow run nameting -f onderdeel=query -f query="accordeur-meldingen"` → 0 rijen `e-mail` voor `accordeur_nieuw_gemeld`/`accordeur_herinnering` ná de deploy; run-audits `accordeur_melding_run` aanwezig; teller-regel "Accordeur-meldingen push-only" in de 06:30-reconciliatiemail.
3. **Punt 17** — `gh workflow run nameting -f onderdeel=webhook-wacht` → `WEBHOOKS   0 outbox-rij(en) …` verwacht (niets in wacht); aanwezig-pad pas bij de eerstvolgende niet-koppelbare `factuur_geboekt`.
4. **Punten 7, 8, 9, 10, 12, 13, 15** — klikpunt Peter (f00117f4 op 1455 px: inklapregel + compacte regels; grootboek leeg mét chip; verplaatsen → volgende Steigerbouw-document; meerwerkbon ↔ project; Projecten zoeken "26149" → "2 van N"; dossier-upload met getypte datum) + request-log waar het rapport dat noemt. Punt 16 = suite-poort (geen productiegedrag).

## Af
Rapport `docs/rapporten/2026-10-03-nameting-run-a.md` + INDEX + "Gelezen regels" + per punt "werkt in productie: ja/nee/niet gemeten"; BESLISSINGEN-sectie "RUN A 02-10 — …" alinea "Gemeten 03-10"; CLAUDE.md ongewijzigd tenzij een regel verandert. Niets schrijvends in productie.
