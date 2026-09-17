# Rapport 17-09 (ochtend) — Doorbelasting-aansluiting Kempen Facilities: productienameting ná deploy — NIET GEMETEN (gcloud-sessie verlopen), meting als workflow-onderdeel klaargezet

Opdracht: `opdrachten/gedaan/2026-09-17-doorbelasting-aansluiting-nameting.md` (vervolg op
`docs/rapporten/2026-09-16-doorbelasting-aansluiting.md`). Lees-only opdracht; geen RLZ-/Odoo-writes, geen migratie, gouden set niet
geraakt. **Werkt in productie: niet gemeten** — stap 0 struikelt op de gcloud-sessie (zie hieronder); de code stáát wél in productie.

## Stap 0 — voorwaarden

| Voorwaarde | Uitkomst |
|---|---|
| `gcloud auth print-access-token` | **ROOD**: "Reauthentication failed. cannot prompt during non-interactive execution" — de gebruikerssessie (info@vastly.software) is verlopen en een inbox-run kan niet interactief herinloggen. Geen enkele productie-lezing via gcloud mogelijk in deze run. |
| Deploy van de commits 16-09 nacht | Via `gh` (werkt wél) gecontroleerd: deploy-run 35154023394 op `66e567a` (doorbelasting-aansluiting) **groen**. De laatste run 35154845937 op `bc3f7c1` (bevat ook `5ba1e9a` native OTA + `bc3f7c1` docs) is **rood**, maar de stappen 8 "Cloud Run-revisie uitrollen" en 9 "F3-jobs bijwerken" waren groen; alleen stap 10 "OTA-webbundel bouwen, uploaden en registreren" faalde: `ERROR: (gcloud.storage.cp) gs://rlz-boekhouding-app-bundels not found: 404`. Stap 11 (smoketest, incl. de "zelfde beeld"-toets) is daardoor overgeslagen; de mail "deploy mislukt" is verstuurd. |
| Service én álle jobs op hetzelfde beeld | Niet met `gcloud run … describe` te toetsen (sessie). Indirect: service en jobs komen uit dezelfde `IMAGE`-variabele (guard `test_deploy_yml_image_uniform.py`) en beide stappen waren groen in dezelfde run → beide op het beeld van `bc3f7c1`, dat de doorbelasting-code van `66e567a` bevat. Formele drift-toets staat in het vervolg. |

Conclusie stap 0: **stoppen mét melding** conform de opdracht — meting (stap 1) en oordeel (stap 2) zijn niet uitgevoerd.

## Wat er wél is gedaan (zodat het vervolg zonder gcloud-login kan)

| # | Onderdeel | Uitkomst |
|---|---|---|
| 1 | **Nameting-workflow uitgebreid** (`.github/workflows/nameting.yml`) met dispatch-onderdeel `doorbelasting-aansluiting`: draait `scripts/gcp/nameting.sh doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` (lees-only allowlist, exit 3 = webfilter = meting ongeldig) naar `verkenning/nameting-doorbelasting-aansluiting-<dd-mm>.txt`, en hangt daarachter de Cloud-Logging-regels "herkoppeling doelentiteiten … / GEKOPPELD / LET-OP" van de job `rlz-sync` (laatste 7 dagen; `logging.viewer` op `nameting@`). Bewust NIET in "alles" (het dagelijkse reconciliatieblok `doorbelasting_aansluiting` doet dezelfde toets al). Commit door de nameting-bot; oordeelregel = "geen oordeelregel (N rapport(en))" — het CLI-rapport kent geen `Oordeel:`-regel, de tabellen zijn de uitkomst. | GEBOUWD |
| 2 | Guard `tests/unit/test_nameting_workflow.py`: options-lijst + nieuwe test (alleen op verzoek, alleen via nameting.sh, juiste bestandsnaam, Cloud Logging op `rlz-sync`) — 15 groen; YAML geparsed, `bash -n` op het run-blok groen. | GROEN |
| 3 | Vervolg-opdracht `opdrachten/inbox/2026-09-17-doorbelasting-aansluiting-nameting-2.md`: stap 0 = deploy van déze commit groen + `gh run list`-drift-check; stap 1 = `gh workflow run nameting -f onderdeel=doorbelasting-aansluiting` + `gh run watch` + `git pull --ff-only` → het bot-bestand lezen; stap 2/afronding = het oordeel uit de oorspronkelijke opdracht. Alternatief voor Peter: één `gcloud auth login`, dan kan de vervolg-opdracht óók het lokale recept draaien. | IN INBOX |

## Bevindingen bijvangst (niet gebouwd, wel gemeld)

1. **Elke deploy is rood tot de bucket bestaat.** Stap 10 (OTA-webbundel) faalt op de ontbrekende bucket `gs://rlz-boekhouding-app-bundels`
   en slaat daarmee de post-deploy-smoketest (publiek 200, health, schema-zelftest, zelfde beeld) over — ook voor commits die niets met OTA
   te maken hebben. Klikpunt Peter (owner): `scripts/gcp/app_bundels_bucket.sh --apply`. Beslispunt: de OTA-stap `continue-on-error`
   maken mét een zichtbare LET-OP, zodat de smoketest altijd draait; default níét gedaan (opdracht 16-09 zette de stap bewust hard —
   "niets verdwijnt stil").
2. **Inbox-runs kunnen nooit gcloud-interactief herinloggen.** Elke "meting ná deploy" die op de gebruikerssessie leunt, strandt zodra
   die sessie (dagelijks) verloopt — 16-09 (VGG vierde meting) en nu weer. De workflow-route (WIF als `nameting@`, via `gh workflow run`)
   is de structurele weg; dit rapport zet de KF-aansluiting daarop. Suggestie voor volgende metingen: elk nieuw lees-only meetrecept direct
   als dispatch-onderdeel in `nameting.yml` toevoegen bij de bouw, niet pas bij de nameting.

## Keuzes in deze run (Peter kijkt niet mee)

- Niet gewacht op of gevraagd om een herlogin; de opdracht zegt "stoppen mét melding" bij een ontbrekende voorwaarde — gedaan, plus de
  meting automatiseerbaar gemaakt zodat het vervolg niet wéér op dezelfde muur loopt.
- Geen wijziging aan `deploy.yml` (buiten scope, gemeld als beslispunt).
- BESLISSINGEN-rij blok 3 aangevuld met de stand "niet gemeten 17-09 + workflow-onderdeel"; "werkt in productie" blijft open tot het vervolg.

## Tests

| Poort | Uitkomst |
|---|---|
| `tests/unit/test_nameting_workflow.py` | 15 groen |
| `tests/unit/test_rapporten_index.py`, `test_claude_md_beslissingen_verwijzingen.py` | groen (zie commit) |

**Werkt in productie: niet gemeten.**
