uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md (sectie "Nameting ná deploy")

Domeinen: verplichtingen-projecten-voorraad, werkloop-productie

# NAMETING 19-09 — projectverdeling × afgesloten projecten ná deploy (vervolg op rapport 2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md)

**Stap 0 — deploy-check (les 10-09, service ÉN jobs):** de commit mét `app/projectverdeling/afgesloten.py` moet live staan op
`rlz-backend` én de F3-jobs (`gcloud run services describe` / `gcloud run jobs describe rlz-reconciliatie --format="value(template.template.containers[0].image)"`
zelfde beeld; `gh run list --workflow deploy.yml --limit 3` groen). Loopt de deploy nog: wachten, niet meten.

**Stap 1 — meetrecept (lees-only, allowlist):**
```
scripts/gcp/nameting.sh projectverdeling-afgesloten-rapport --administratie "Universal Steigerbouw"
scripts/gcp/nameting.sh reconciliatie-alles --alleen projecten --lees-only
```
Verwacht: 8 actieve projecten mét "Afgesloten"-naam (LET-OP `project_naam_afgesloten_status_actief`, facet "in meting", nooit
actiemail), 10 geboekte verdelingsdelen = € 1.239,05 mét voorstel "laten staan tot afgesloten", overhead € 12.229,32 geboekt,
"OVH-project aanwezig: nee". Geen TTY → het onderdeel `projecten-afgesloten` via `gh workflow run nameting -f onderdeel=projecten-afgesloten`
(bot-bestand `verkenning/nameting-projecten-afgesloten-<dd-mm>.txt` op main lezen).

**Stap 2 — "werkt in productie":** heeft Peter intussen één van de 8 projecten afgesloten (Projecten › Afsluiten…), toets dan op de
leesreplica (`scripts/gcp/db_lezen.sh … --als <beheerder> --administratie 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`) dat het document
Exact RLZ-2026053923 (16616342-ee4c-4711-af7c-99afc0e11e5c) een tijdlijnregel "verdeling herberekend: … afgesloten" draagt en het
project uit `projectverdeling.verdeling` is → "werkt in productie: ja". Niets afgesloten → "niet gemeten (wacht op afsluiten door Peter)",
nooit zelf een project afsluiten.

**Afronding:** aanvulling op het rapport 2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md (sectie "Nameting ná deploy") + INDEX-regel bijwerken, BESLISSINGEN-status "werkt in
productie" invullen, opdracht → gedaan, committen.
