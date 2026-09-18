Domeinen: uren-planning-veldwerkers, accordering-native-app

# OPDRACHT 18-09 — Veld-app UX run B (groter): dag-einde herinnering (push) + offline werken (akkoord Peter 18-09 "alle punten")

Vervolg op `opdrachten/gedaan/2026-09-18-veldapp-ux-verbeteringen-12-punten.md` (run A gebouwd 18-09; bouwnorm
`mockup/uren-uitvoerder-v3.html` notitie 11). Lees eerst `docs/regels/uren-planning-veldwerkers.md` en
`docs/regels/accordering-native-app.md` volledig. Zelfde regels als altijd: gouden set/veld-app-tests groen, WAT_IS_NIEUW per
punt één regel, docs/regels + BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter 18-09)" aanvullen (alinea "Run B"), rapport +
INDEX + Gelezen regels, nameting ná deploy op het testaccount, "werkt in productie: ja/nee".

## Punt 4 — Dag-einde herinnering
Push om 16:30 (instelbaar per administratie: `administratie.uren_herinnering_tijd`, default 16:30, Instellingen › administratie ›
Uren & materiaal) "Nog geen uren voor vandaag" — alleen op werkdagen (ma–vr, NL-kalenderdag via `app/tijd.py`), alleen als er
die dag geen dagregel is (som over álle weekstaten van de veldwerker), één per dag per veldwerker (idempotent: tabel of
dagrij-claim zoals `planning_signaal`), via de bestaande push-infra (`app/berichten/push.py`, push-anders-mail volgens het
bestaande patroon), stille uren respecteren. Opt-out in ⚙ Toegang (per toestel/gebruiker: `gebruiker.uren_herinnering_uit`, GET/PUT
`/uren/zzp/herinnering`). Job: Cloud Run-job in deploy.yml + Cloud Scheduler (elk kwartier tussen 15:00 en 19:00, de job toetst
zelf de administratie-tijd) — envset volledig in de ENE deploy-stap (guard `test_deploy_yml_envset_compleet.py`). Guard-test op
het afwezig-pad (geen opt-in/tijd = default doorlopen), dagtellers verwacht/gedaan/overgeslagen in de reconciliatiemail.

## Punt 5 — Offline werkt
Dagregels lokaal opslaan (IndexedDB-wachtrij naast het slot, versleuteld achter hetzelfde anker) en verzenden zodra er netwerk is
(`online`-event + bij app-opening + ná elke geslaagde verversing); bolletje "nog niet verzonden" per regel en per week; conflict
(kantoor/uitvoerder keurde intussen → 409/`WeekstaatBevroren`) = melding mét beide standen, nooit stil overschrijven;
`navigator.storage.persist()` staat sinds run A al aan bij web-activatie. Tests met netwerk-uit (fetch → TypeError) in vitest;
querytelling ongewijzigd; indienen blijft online-only (met duidelijke melding).

## Afronding
Beslispunten vooraf noteren (herinneringstijd default 16:30; opt-out per gebruiker of per toestel — voorstel: per gebruiker);
mockup v3 uitbreiden met scherm ⑤ (offline-bolletjes) en ⑥ (herinnering-instelling) vóór de bouw.
