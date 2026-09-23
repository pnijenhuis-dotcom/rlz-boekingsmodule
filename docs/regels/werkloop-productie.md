# Regels — Werkloop, nametingen, deploy en productie-toegang

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Gouden set als poort, cc-inbox (launchd), nameting-workflow + `nameting.sh`, rapporten + INDEX, deploy.yml-lessen, productie alleen via gedeployde jobs, Feiten eerst (querybibliotheek, leesreplica), migratie-guards, database/RLS-lessen.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Herstelrun "Basis eerst" 08-09 (besluit Peter: nieuwe definitie van "af" = gouden set groen + productie-nameting + rapportregel "werkt in productie: ja/nee"; geen nieuwe functies, elf blokken; migraties 0123–0124):** overzicht + per-blok-secties — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — OVERZICHT".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Gouden set = verplichte poort (blok 0):** `backend/tests/keten/` + `frontend/scripts/keten_sweep.sh`, guard `tests/unit/test_keten_guard.py` — zie BESLISSINGEN "GOUDEN SET — KETENTEST OP ECHTE DOCUMENTEN" en § Werkwijze hieronder.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Gouden set — export deterministisch, referentiedatum bevroren (blok 5 vervolgrun 10-09 avond; geen migratie):** `b_floor.json` dreef op de afwijsreden "… van <ontvangstdatum> …" (`aangemaakt_op` = DB-`now()`); de `Keten`-fixture bevriest ná élke intake-stap het ontvangstmoment op `REFERENTIE_TIJDSTIP` 2026-09-08T12:00Z (ties blijven ties), guard `tests/keten/test_export_deterministisch.py` (export = gecommitte fixture, herhaling byte-gelijk, geen datum-van-vandaag in de exports) + dezelfde toets in `keten_sweep.sh`; detail-baselines 10-09 ververst — zie BESLISSINGEN "GOUDEN SET — EXPORT DETERMINISTISCH, REFERENTIEDATUM BEVROREN".

<!-- uit CLAUDE.md § Werkwijze -->
- **Deploy-les 10-09 (regressie 09-09 → 10-09, 13 deploys):** een `^<t>^`-scheidingsteken in `--set/--update-env-vars` mag nooit in een waarde voorkomen (`^@^` + e-mailadres brak de workflow ná de service-stap → F3-jobs 1,5 dag op oud beeld, `INTAKE_POSTVAK_ADRES` weg van de service); guard `tests/unit/test_deploy_yml_envvar_delimiters.py` — zie BESLISSINGEN "NAMETINGEN-RUN 10-09 — SERVICEACCOUNT, DEPLOY-REGRESSIE, METINGEN". **Aanvulling 11-09: zeven rode deploys #173–#179 bleven onopgemerkt → bewakingsprobe `deploy_drift` (service-beeld ≠ job-beeld > 30 min = alert + audit + LET-OP "systeemfout — automatisch gemeld"), smoketest toetst zelfde beeld + publiek 200, `--allow-unauthenticated` weg, `if: failure()` → mail via job `rlz-bewaking deploy-mislukt`, guard `test_deploy_yml_image_uniform.py` (één `IMAGE`-variabele); IAM `roles/run.viewer` op run-jobs@ = één owner-commando (`scripts/gcp/bewaking_deploy_drift_iam.sh`).** **Aanvulling 16-09 (melding Peter "Mailkanaal niet geconfigureerd" bij een herstel-link): service én élke job krijgen hun VOLLEDIGE envset + secrets in de ENE deploy-stap (gedeelde `MAIL_ENVS`/`MAIL_SECRETS`/`PUSH_*` in het workflow-`env:`-blok), de losse `services update`/`jobs update`-stappen zijn weg, smoketest eist lees-only de mailkanaal-config op de servicetemplate; guard `test_deploy_yml_envset_compleet.py` — zie BESLISSINGEN "DEPLOY — VOLLEDIGE ENVSET IN ÉÉN STAP (Peter 16-09)".**

<!-- uit CLAUDE.md § Werkwijze -->
- **Ochtendrun 11-09 — eerste échte productiemeting van bundel 09-09/10-09 + vervolgrun op deploy #180 (`58feacb`):** rlz_dubbel 954 paren → 42 clusters (6-Steps waarschijnlijk dubbel; BP Express/Food service uitgesloten), drempel 5 → 3, leren-rapport 68 administraties (5 kwalificerend), matchmotor-labels live, historie-regel/AI-poort niet meetbaar (cache leeg → `bank-historie-backfill --dry-run` gebouwd), tellers zichtbaar, RLZ-check-knop ontbrak in de UI — zie BESLISSINGEN "OCHTENDRUN 11-09 — NAMETINGEN + DEPLOY-DRIFT".

<!-- uit CLAUDE.md § Werkwijze -->
- **Werkloop automatisch (14-09; besluit Peter 14-09 "alles wat automatisch kan gaat automatisch; Peter test en meldt, geen plakwerk"):** (1) de nameting draait DAGELIJKS 05:30 UTC via `.github/workflows/nameting.yml` (WIF als `nameting@`, nooit `deploy@`, geen SA-key — het beslispunt "SA-key" van 10-09 vervalt; ook `workflow_dispatch` mét input `onderdeel` = `rlz meting`) en commit `verkenning/nameting-*.txt` als `nameting-bot`; een rood rapport is een uitkomst (exit 0), alleen deploy-drift en auth-fouten maken de run rood; het commitbericht draagt de `Oordeel:`-regel van het GEDRAAIDE onderdeel (reconciliatie → reconciliatie-rapport, anders replay; anders "geen oordeelregel" — nazorg 14-09); **werkt in productie: ja (run 34845170512 → `f4c702c` door nameting-bot, 14-09)**; eenmalige IAM door Peter: `scripts/gcp/nameting_wif_iam.sh --apply`; guard `tests/unit/test_nameting_workflow.py`. (2) Élk CC-eindrapport gaat als `docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md` + regel bovenaan in `docs/rapporten/INDEX.md` mee in de laatste commit van de run (zelfde inhoud als het chat-eindrapport, incl. "werkt in productie: ja/nee/niet gemeten"); guard `tests/unit/test_rapporten_index.py`. (3) Opdrachten komen als één .md via `opdrachten/inbox/` (Cowork schrijft), CC verplaatst bij start naar `lopend/` en bij afronding naar `gedaan/` mét kopregel "uitgevoerd <datum>, rapport: docs/rapporten/<bestand>"; launchd-agent `nl.aknijenhuis.cc-inbox` (WatchPaths + 300 s) start `scripts/cc_inbox.sh` (één tegelijk, lock, macOS-melding; sinds 14-09 middag `--permission-mode auto` als default (`CC_INBOX_PERMISSION_MODE` overschrijft) — de deny-lijst van `.claude/settings.local.json` blijft onverkort gelden: geen git push, geen secrets; de Stop-hook pusht; **nazorg 14-09: bij élke tick een `git pull --ff-only origin main` als de werkboom schoon is en er geen lock is, anders overslaan mét logregel — nooit rebase/merge/stash; guard `tests/unit/test_cc_inbox_pull.py`**; **herstel 14-09 avond (incident 15:17: `claude -p` stierf ná 22 min op de maandelijkse budgetlimiet, log alleen een startregel, opdracht bleef in lopend/): élke stop = logregel + macOS-melding mét geloged resultaat (exit ≠ 0, signaal TERM/INT/HUP, onverwacht einde), hartslag "loopt nog (N min)" elke 5 min in het opdrachtenlog, limiet-herkenning "LIMIET — claude.ai/admin-settings/usage", en een verweesde opdracht in lopend/ (geen levende lock) gaat bij de volgende tick terug naar inbox/ — max 3 pogingen (`opdrachten/log/<slug>.pogingen`), daarna `opdrachten/mislukt/` mét kopregel; guard `tests/unit/test_cc_inbox_herstel.py`**; **nazorg 15-09: een `claude`-proces mét cwd in deze repo (pgrep + lsof) = "wacht — handmatige CC actief": geen herstel, geen pull, geen start, volgende tick opnieuw; cwd onleesbaar = fail-closed — zie BESLISSINGEN "WERKLOOP AUTOMATISCH …" herstel-tabel rij (f)*; **guard 16-09 nacht (incident 16-09 avond: inbox-run + handmatige sessie parallel): lock `opdrachten/.lock` = pid / soort / starttijd, `.git/index.lock` = wachten, handmatige CC in deze repo start via `rlz cc` (zet de lock, weigert bij een lopende inbox-run: "wacht of `rlz inbox stop`") — herstel-tabel rij (g), guard `tests/unit/test_cc_inbox_parallel.py`**); aan/uit: `scripts/cc_inbox_install.sh [--uninstall]`; terminal `rlz plan|meting|status|inbox` (`scripts/zsh/rlz.zsh`); **rij (h) 17-09 (incident: zeven uur "wacht — handmatige CC actief (pid 82714)" zonder dat iemand het zag): de wachtregel draagt duur + aantal klare opdrachten, ná 30 min een macOS-melding (herhaald hoogstens elk uur), bewuste vrijgave `rlz inbox vrijgeven [pid]` (`opdrachten/.vrijgave`); nameting-bot-commit gefixt (nullglob i.p.v. fatale lege pathspec)** — zie BESLISSINGEN "WERKLOOP AUTOMATISCH — NAMETING-WORKFLOW, RAPPORTEN- EN OPDRACHTENMAP, CC-INBOX".

<!-- uit CLAUDE.md § Werkwijze -->
- **Productie-nametingen structureel — UITGEVOERD 10-09 (route A, besluit Peter):** SA `nameting@` + custom rol `nametingUitvoerder` job-scoped op `rlz-reconciliatie` + `run.viewer`/`logging.viewer`, géén cloudsql/secrets; **key geblokkeerd door org-policy `iam.managed.disableServiceAccountKeyCreation` → voorlopig impersonatie (herlogin blijft), beslispunt Peter**; rotatie-LET-OP via `settings.nameting_sa_aangemaakt_op`; `scripts/gcp/nameting_env.sh` + `nameting.sh` — zie BESLISSINGEN "NAMETINGEN-RUN 10-09 — SERVICEACCOUNT, DEPLOY-REGRESSIE, METINGEN" + GCP_UITROL §F7.3. Voorbereiding/routes: "PRODUCTIE-NAMETINGEN STRUCTUREEL — SERVICEACCOUNT OF LANGERE WORKSPACE-SESSIE".

<!-- uit CLAUDE.md § Werkwijze -->
- **Feiten eerst — lees-only DB-/RLZ-toegang voor analyses + klikpunt-guard (besluit Peter 17-09 "geen halve informatie"; migratie 0154; AMENDEMENT op de regel van 08-09):** querybibliotheek `db-lezen <query>` (`app/lezen/queries/*.sql`, RLS per administratie, audit) + SELECT-only rol `rlz_lezer`; vrije SELECT UITSLUITEND op de leesreplica `rlz-sql2-lees` (`LEES_DATABASE_URL`, READ ONLY, als Beheerder, poort `sql_poort.py`, plafond 5.000) via `POST /lezen/sql`, `db-lezen --sql --als` en `scripts/gcp/db_lezen.sh`; `rlz-feiten rlz|bank` = document + regels + bank (bewijs 1 koppeling / bewijs 2 cent-exact ± 3 d) in één tabel; guards: klikpunt zonder datum+bedrag+bron = rood (`test_rapporten_klikpunten.py`), dubbel-signaal draagt `bank_toets`; nameting-onderdeel `query` voor Cowork; replica + IAM-DB-gebruiker = owner-klikpunt `scripts/gcp/leesreplica.sh` — zie BESLISSINGEN "FEITEN EERST — LEES-ONLY DB-/RLZ-TOEGANG VOOR ANALYSES + KLIKPUNT-GUARD (Peter 17-09)".

<!-- uit CLAUDE.md § Werkwijze -->
- **Leesreplica afgerond 17-09 (migratie 0157 = voorwaardelijke GRANT `rlz_lezer` aan `nameting@…iam`; `CLOUD_SQL_LEES` + `LEES_CLOUD_SQL_VERBINDING` op service/jobs/smoketest in één envset-stap, `--set-cloudsql-instances` beide instanties, config composeert `lees_database_url`; smoketest `SELECT 1` READ ONLY op de replica; replica ENTERPRISE/ZONAL, CMEK geërfd — **werkt in productie: JA** (nameting 17-09 ~17:40 ná deploy `ef48eec`: smoketest-log "leesreplica antwoordt (SELECT 1, READ ONLY)", `db_lezen.sh` als `nameting@rlz-boekhouding.iam` mét rol `rlz_lezer` op `rlz-sql2-lees` READ ONLY/in recovery, grants uitsluitend SELECT, INSERT door de poort geweigerd, `nameting -f onderdeel=query -f query=sync-status` → `verkenning/lezen-17-09-sync-status.txt`; `POST /lezen/sql` als Beheerder = klikpunt Peter; les: de poort weigert een schrijfwoord ook als string-literal — rechten via `information_schema`))** — zie BESLISSINGEN "FEITEN EERST — LEES-ONLY DB-/RLZ-TOEGANG VOOR ANALYSES + KLIKPUNT-GUARD (Peter 17-09)" alinea "Afronding leesreplica 17-09" + GCP_UITROL §F7.4.

<!-- uit CLAUDE.md § Werkwijze -->
- **Gouden set = verplichte poort (besluit Peter 08-09, herstelrun "Basis eerst" blok 0):** `backend/tests/keten/` is één
  ketentest op échte, geanonimiseerde productiedocumenten (Universal Nederland RLZ-2080143037, Floor 26219, Spot Services
  2026-608, Universal-Nederland-splitsing RLZ-2080143038/39, BOOT-creditnota 202633199, BDO 6088744, DCTE 202611050, Kader
  F212604921) door intake → bundeling/nabundel → extractie (deterministische stub speelt de bewaarde AI-uitkomst af, nooit
  een echte AI-call) → prefill → checks → lijst-DTO → afvoer/status, plus het frontend-harnas `harness-keten.html` +
  `frontend/scripts/keten_sweep.sh` (echte controlescherm en documentenlijst op exact de door de backend geëxporteerde
  DTO's, pixelvergelijking tegen `frontend/scripts/keten_baseline/`). **Definitie van "af" voor élk blok dat intake/
  controlescherm/lijst/accordeur-app raakt: (1) gouden set groen (doelgedrag dat nog niet staat is `xfail(strict, reason=
  "blok N — …")`, de eigenaar haalt zijn xfail weg — nooit de assert), (2) productiegedrag ná deploy nagemeten met een
  vooraf genoemd meetrecept, (3) het rapport zegt letterlijk "werkt in productie: ja/nee".** Guard:
  `tests/unit/test_keten_guard.py` — een werkboom-wijziging onder app/intake, app/extractie, app/documenten of
  frontend/src/document zonder aanraking van tests/keten is rood. Nieuwe echte casus toevoegen = fixture-map onder
  `tests/keten/fixtures/` (UBL geanonimiseerd, PDF nooit als echte bytes — kerntekst in `pdf_tekst.json`, AI-uitkomst als
  `ai_antwoord.json`, herkomst in `bron.json`); nooit BSN's — zie BESLISSINGEN "GOUDEN SET — KETENTEST OP ECHTE DOCUMENTEN
  (blok 0 herstelrun 08-09)".

<!-- toegevoegd 18-09-2026 avond, opdracht "facturen-zonder-project-universal-rapport-en-inbox-hygiene" -->
- **CC-inbox rij (i) — een lopend-kopie van afgerond werk is af, nooit "loopt" (18-09 avond; BESLISSINGEN "FACTUREN ZONDER PROJECT —
  LEES-ONLY RAPPORT + INBOX-HYGIËNE (18-09 avond)"):** staat een .md in `opdrachten/lopend/` terwijl dezelfde opdracht al in `gedaan/`
  staat mét kopregel "uitgevoerd …" (handmatige of parallelle run kopieerde naar gedaan/ zonder lopend/ op te ruimen), dan ruimt de tick
  de lopend-kopie op (logregel, pogingen-teller weg) en start NIETS opnieuw — vóór deze fix zette `herstel_verweesd` zo'n bestand terug
  in inbox/ en draaide afgerond werk tot drie keer opnieuw. `rlz inbox status` somt lopend/ op per bestand: "loopt" uitsluitend bij een
  levende lock, "af (staat in gedaan/ — de volgende tick ruimt de kopie op)", anders "gestrand (geen levende lock — terug naar inbox/)";
  leeg = "lopend/: leeg". Guards `tests/unit/test_cc_inbox_herstel.py::test_lopend_kopie_van_afgeronde_opdracht_*` (+ tegenproef zonder
  kopregel) en `tests/unit/test_cc_inbox_parallel.py::test_rlz_inbox_status_toont_lopend_*`.

<!-- toegevoegd 19-09-2026, opdracht "nameting-projectverdeling-afgesloten-na-deploy" -->
- **Nameting-workflow — een dispatch-onderdeel staat óók in de keuzelijst (19-09; BESLISSINGEN "PROJECTVERDELING SLUIT AFGESLOTEN PROJECTEN
  UIT + RLZ-KANT-METING FACTUREN ZONDER PROJECT (19-09)" alinea "Nameting ná deploy 19-09"):** `gh workflow run nameting -f
  onderdeel=projecten-afgesloten` gaf HTTP 422 — het onderdeel stond in de if-takken en de beschrijving van `.github/workflows/nameting.yml`,
  niet in `options:` van de choice-input; GitHub weigert dan élke dispatch, dus ook `nameting.sh` zonder TTY (via_gh) en de vervolg-opdracht
  ná deploy. Regel: een nieuw onderdeel = if-tak + `options:` + `via_gh_onderdeel` in `scripts/gcp/nameting.sh` in één commit; guard
  `tests/unit/test_nameting_workflow.py::test_elk_dispatch_onderdeel_staat_in_de_keuzelijst` (élke `"$ONDERDEEL" == …`-vergelijking ∈ options).
  Terugvalroute in een run die de workflow niet meer gefixt-gepusht krijgt: hetzelfde script lokaal mét `NAMETING_VIA_GH=0` (zelfde
  SA-impersonatie, zelfde job-executie op de gedeployde image — geen lokaal proces tegen productie) en de ruwe uitvoer in het rapport,
  want er komt dan geen bot-bestand op main.

<!-- toegevoegd 19-09-2026, opdracht "nameting-kassarapport-autotype-na-deploy" (poging 1) -->
- **Stop-hook-push non-fast-forward = stille deploy-blokkade (19-09; BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER
  HANDELING SWEEP (Peter 19-09)" rij "Nameting kassarapport-autotype poging 1"):** committe de nameting-bot op origin/main terwijl een run
  liep, dan faalt de Stop-hook-push van die run én van élke volgende run non-fast-forward; de hook meldt dat alleen op stderr (exit 1) en de
  inbox-tick slaat een gedivergeerde branch bewust over — op 19-09 stond de deploy daardoor drie uur stil (`86ecbad` 12:44 → 15:47) terwijl
  vier na-deploy-nametingen wachtten. Regel: (1) élke run mét een deploy-afhankelijke stap 0 toetst óók `git rev-list --count
  main..origin/main`; is die > 0, dan `git merge --no-ff origin/main` — nooit rebase (hashes staan in rapporten/BESLISSINGEN), nooit force —
  en pas daarna de deploy-check; (2) een deploy-check die "niet gedeployd" zegt terwijl de commit ouder is dan ~30 min is een signaal om de
  push-stand te lezen, niet om te wachten; (3) procesfix — GEBOUWD 19-09 (rij (j4) hieronder + opdracht "stop-hook-push-non-fast-forward-stille-
  deploy-blokkade", rapport `docs/rapporten/2026-09-19-stop-hook-push-non-fast-forward-procesfix.md`): de Stop-hook roept
  `scripts/git-hooks/stop-push.sh` aan (fetch + `merge --no-ff` + retry; blokkade luid: stderr, macOS-melding, `push.log`,
  `opdrachten/.push-geblokkeerd`), de inbox-tick meldt divergentie (hoogstens elk uur), `rlz inbox status` toont "origin gedivergeerd
  (N lokaal / M remote) — deploy staat stil". **Beslissingen 19-09 avond:** (a) GEEN bot-only-filter — een mens-commit op origin is even
  legitiem als een bot-commit; élke conflictvrije divergentie merget, een conflict blokkeert luid; (b) `.github/workflows/nameting.yml`
  blijft ONGEWIJZIGD: de bot-commit gaat niet naar een eigen branch (een meting telt pas als het bot-bestand op main staat) en wacht
  niet op een deploy-run (extra bewegend deel zonder winst — de kosten van een bot-commit tijdens een run zijn sinds (3) één
  merge-commit + één extra deploy, en de bot pusht vaak juist tijdens de run die 'm aanvroeg); de `pull --rebase` in de bot-stap raakt
  alleen de ene verse bot-commit en blijft; guard `test_nameting_workflow.py::test_bot_commit_blijft_op_main_en_wacht_niet_op_een_deploy`.
  Bewijs vóór/ná in een tijdelijke kloon (bare origin + bot-kloon): oude hook-regel `git push origin main` → `! [rejected] … (fetch
  first)`, exit 1, origin alleen de bot-commit; `stop-push.sh` → merge-commit mét beide ouders op origin/main, exit 0, geen
  blokkade-bestand, geen rebase in de reflog — als test `test_stop_hook_push.py::test_reproductie_bot_commit_tijdens_run_voor_en_na`;
  de settings-JSON-hookregels dragen zelf geen git-woord meer (zelfde guard).

<!-- toegevoegd 19-09-2026, opdracht "cc-inbox-lock-per-opdracht-en-wachten-op-suite" -->
- **CC-inbox rij (j) — lock per opdracht, één runner per repo, poort vóór einde, push-retry (19-09; BESLISSINGEN "CC-INBOX — LOCK PER
  OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)"; procesles inbox-run 19-09 12:46: twee runs op één opdracht, twee runs die vóór hun
  suite eindigden, een stil geweigerde Stop-hook-push):**
  1. **Lock per opdracht, atomisch.** Oppakken = `mv inbox/X lopend/X` (rename(2), slaagt voor precies één proces); de verliezer logt
     "claim verloren — X is intussen door een andere run opgepakt" en neemt de volgende kandidaat. Geen tweede mechanisme. Per claim
     staat `opdrachten/log/<slug>.claim` = pid / starttijd; `rlz inbox status` toont per lopend-bestand "loopt (claim pid N, sinds T)".
     Claim mét dode pid < `CC_INBOX_GESTRAND_S` (default 1800 s = 30 min) = "onzeker — nog geen herstel"; ≥ 30 min = "gestrand" →
     bestaand herstelpad (e) mét logregel + melding "CC HERSTART" — nooit stil herstarten. Een lopend-bestand ZONDER claim = de run
     sloot zelf af zonder afronding → herstelpad direct. Rij (i) (gedaan-kopie = af) blijft voorgaan.
  2. **Eén inbox-runner tegelijk per repo.** `opdrachten/.lock` is dé gedeelde runner-lock van de launchd-agent én `rlz cc` (de opdracht
     noemde `.runner.lock`/flock — macOS heeft geen flock en de bestaande lock IS al het ene mechanisme; keuze: bestaande naam houden,
     nu ATOMISCH nemen via O_EXCL/noclobber, een dode lock atomisch wegdraaien met `mv` zodat maar één proces 'm opruimt). Een tweede
     starter stopt zichtbaar: tick → "runner-lock net gepakt door pid N" of "wacht — inbox-run actief (pid N, sinds T, M min)" (vóór
     19-09 stil); `rlz cc` → "inbox-run actief sinds …, wacht of `rlz inbox stop`" / "runner-lock net gepakt door een andere start".
     Parallelle agenten BINNEN één run mogen, parallelle runs niet.
  3. **Een run eindigt pas ná zijn poort.** Ná `claude -p` toetst het script de werkboom (tracked wijzigingen + untracked buiten
     `opdrachten/`, `.scratch/`, `.claude/`). Niet schoon = de poort (pytest + vitest + tsc + gouden set → commit) is niet gehaald,
     ongeacht de exitcode: het werk gaat als WIP-commit op branch `wip/<slug>` (plumbing mét eigen tijdelijke index: `read-tree`/
     `add`/`write-tree`/`commit-tree`/`update-ref` — main en HEAD onaangeraakt, geen `.git/index.lock` nodig, nooit stash), de
     werkboom wordt schoon (`reset --hard HEAD` — alleen werk dat zojuist veilig op de branch staat), `opdrachten/log/<slug>.wip` =
     branch/commit, logregel "poort niet gehaald — WIP op branch wip/<slug>" + melding "CC POORT NIET GEHAALD", de opdracht blijft in
     `lopend/` → herstelpad (e), volgende poging; de startprompt van die poging zegt: begin met `git merge --squash wip/<slug>`, commit
     pas ná de poort, "eindig NOOIT terwijl een suite of achtergrondtaak nog loopt". Zette claude het bestand zelf al in `gedaan/`
     (untracked) mét ongecommit werk, dan gaat het terug naar `lopend/` zonder kopregel — "af" zonder commit bestaat niet. De
     wip/-branch blijft ná een geslaagde volgende poging ter controle staan (status toont 'm; opruimen `git branch -D`). **Exit 0
     zonder resultaat** (geen nieuw rapport, geen nieuwe commit, niet zelf naar `gedaan/`) = "GEEN RESULTAAT" → `lopend/` (herstel),
     nooit `gedaan/` — incident 19-09 16:12: de run "nameting-projecten-afsluiten-tab" eindigde met "ik wacht op de melding" (code 0)
     en het script zette 'm mét "rapport: geen" in `gedaan/`; die opdracht is in deze run teruggezet in `inbox/`. **Ongecommit werk
     in de werkboom bij de START = melding + stop** (vóór 19-09 alleen een LET-OP-regel (g3) en toch starten): logregel "STOP —
     werkboom niet schoon bij start (N bestand(en): …)", macOS-melding hoogstens elk uur, geen herstel/pull/start tot een mens het
     commit of wegzet. Voor de (stub-)tests betekent dit: een afgeronde run schrijft een rapport én commit.
  4. **Push-conflict = merge + retry, nooit alleen "push handmatig".** De Stop-hook (`.claude/settings.local.json`, lokaal, niet in
     git) roept nu voor beide repo's het TRACKED script `scripts/git-hooks/stop-push.sh <repo> <label>` aan: niets te pushen = stil;
     push ok = regel in `opdrachten/log/push.log`; geweigerd → `git fetch origin main` → is origin vooruit én de werkboom schoon
     (tracked), dan ÉÉN `git merge --no-ff --no-edit origin/main` (commitbericht noemt de binnengekomen commits) + ÉÉN retry-push, mét
     regel op stderr "origin was gedivergeerd (N lokaal / M remote) → merge --no-ff + push geslaagd". **Afwijking van de opdrachttekst
     ("pull --rebase"): bewust merge, geen rebase** — de regel van 19-09 ochtend hierboven zegt nooit rebase omdat de lokale hashes in
     het zojuist geschreven rapport/BESLISSINGEN staan; een rebase zou die herschrijven. Blijft het falen (merge-conflict → `merge
     --abort`, werkboom als vóór; vuile werkboom; geen divergentie = rechten/netwerk) → LUIDE blokkade: stderr mét de exacte
     commando's ("Doe zelf (nooit force, nooit rebase): cd … && git merge --no-ff origin/main …"), macOS-melding, `push.log`-regel én
     `opdrachten/.push-geblokkeerd` (tijd / oorzaak / herstel) → `rlz inbox status` toont "PUSH GEBLOKKEERD (…)" + "herstel: …"; een
     latere geslaagde push ruimt het bestand op. `rlz inbox status` toont ook altijd "origin gedivergeerd (N lokaal / M remote) —
     deploy staat stil …" zolang `main..origin/main` > 0 (stand van de laatste fetch) en de wip/-branches. De inbox-tick geeft bij
     "pull overgeslagen — ff-only mislukt" nu óók de tellers + een melding (hoogstens elk uur). Force blijft verboden (deny-lijst +
     guard op het script: geen rebase-/force-/stash-commando).
  5. **Guards:** `tests/unit/test_cc_inbox_claim_en_poort.py` (claim: twee processen, één wint; claim-bestand; onzeker/gestrand; twee
     ticks tegelijk; atomische runner-lock; twee `rlz cc`-starts → één loopt, één stopt mét melding = de nameting van de opdracht;
     WIP-branch + prompt van de volgende poging; gedaan-zonder-commit terug naar lopend; geen resultaat; vuile start = stop) en
     `tests/unit/test_stop_hook_push.py` (echte git: bare origin + bot-kloon; merge+retry, conflict-blokkade mét statusregel en
     opruiming ná herstel, vuile werkboom merget niet, geen rebase/force/stash-commando, lokale settings.local.json roept het script
     aan voor beide repo's — skip als het bestand ontbreekt). Bestaande guards aangepast: levende inbox-lock is niet meer stil
     (`test_cc_inbox_parallel.py`, `_pull.py`, `_herstel.py`), vuile werkboom bij start = stop i.p.v. LET-OP, stubs committen een
     rapport, `index.lock`-scenario eindigt in WIP + LET-OP. Rapport `docs/rapporten/2026-09-19-cc-inbox-lock-per-opdracht-en-poort.md`.

<!-- toegevoegd 19-09-2026, opdracht "nameting-ic-spiegel-rood-en-wachtrij-na-deploy" -->
- **Meetlat = bestaande CLI-keuze; een script wordt nooit bewerkt terwijl het draait (19-09; rapport `2026-09-19-nameting-ic-spiegel-rood-na-deploy.md`):**
  (1) een meetrecept noemt alleen CLI-vormen die op de gedeployde image bestaan — de `--alleen`-keuzelijst van `reconciliatie-alles` is sinds
  19-09 `run.BLOKKEN` (guard `tests/unit/test_reconciliatie_alleen_keuzelijst.py`); strandt een meetlat op argparse-exit 2, dan is de
  terugval de volledige `reconciliatie-alles --lees-only` (alle blokken, ~15 min) en de sectie uit Cloud Logging op de executienaam.
  (2) `scripts/gcp/nameting.sh` (en élk bash-script) NIET bewerken terwijl een run ervan loopt: bash leest incrementeel, een toegevoegde
  regel verschuift de offsets en het script strandt ná de job-executie mét "syntaxfout nabij ')'" (19-09 herhaling van 17-09); de
  job-uitkomst is dan alsnog te lezen met `gcloud logging read … labels."run.googleapis.com/execution_name"="<executie>"`. Script-edits
  wachten tot de achtergrondrun klaar is, of gaan in een kopie. (3) Een lees-only nameting legt niets vast: auto-sluiting van bevindingen,
  aandacht-tellers en dagtellers zijn pas meetbaar ná de eerstvolgende ÉCHTE run (scheduler 06:30) — een échte run forceren = actiemail
  buiten het dagritme, dus een vervolg-opdracht in de inbox met de datum van die run.

<!-- toegevoegd 19-09-2026, opdracht "nameting-kassarapport-autotype-na-deploy-poging-2" -->
- **Élke CLI-vorm die een meetrecept noemt is in de suite gedraaid (19-09 poging 2; rapport `2026-09-19-nameting-kassarapport-autotype-poging-2.md`):**
  het meetrecept noemde `kassarapport-autotype-nazorg --dry-run` kantoorbreed; de suite draaide alleen de zustervorm mét `--administratie`, en precies de
  ongeteste tak strandde op de job-image (`NameError: scoped_session` — import stond alleen in de helper van de andere tak). Regel: wie een nazorg-/meet-CLI
  bouwt, laat de test élke argumentvorm uit het meetrecept letterlijk aanroepen (mét en zónder filter, dry-run én echt); een meetrecept dat een vorm noemt
  die de suite niet kent is niet af. Een NameError/ImportError op een job-executie is een systeemfout van de bouw, geen productie-incident: fix + guard in
  dezelfde run, en de meetlat opnieuw ná deploy (vervolg-opdracht).

<!-- toegevoegd 19-09-2026 avond, opdracht "nameting-ic-spiegel-rood-echte-run-en-aansluiting-alleen" (poging 1) -->
- **CC-inbox rij (k) — "niet vóór"-poort: een opdracht voor ná een moment start niet eerder (19-09 avond; BESLISSINGEN "CC-INBOX — LOCK PER
  OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)" rij (k)):** de regel "(3) … een vervolg-opdracht in de inbox met de datum van die run" hierboven
  werkte niet — de runner claimt op mtime en leest geen datum; de opdracht "ná de échte run van 20-09 06:30" startte op 19-09 18:57. Een opdracht
  mét een regel `niet vóór: JJJJ-MM-DD[ UU:MM]` (eerste 20 regels; ook "niet voor:", vet/blockquote mag; lokale tijd, zonder tijd = 00:00) wordt pas
  ná dat moment geclaimd; tot dan "wacht — X niet vóór … (nog N min); volgende kandidaat" hoogstens elk uur in het log (geen macOS-melding),
  `rlz inbox status` toont "inbox/: X — wacht tot …". Een run die zelf vaststelt dat het te vroeg is (run nog niet gelopen, deploy niet live)
  zet die regel bovenin en legt de opdracht terug in inbox/ — geen tweede mechanisme. Bij een nameting ná een scheduler-run: run-tijd + duur +
  marge voor de deploy van de eigen commit (06:30 NL + ~15 min → `niet vóór: … 07:15`). Guards `test_cc_inbox_claim_en_poort.py::test_niet_voor_*`.

<!-- toegevoegd 21-09-2026, opdracht "BUG-groepssaldi-alle-35-administraties-fout-rlz-enumfilter-en-odoo-deprecated" -->
- **"Werkt in productie: niet gemeten" is een openstaande schuld mét vervaldatum, geen eindstand (21-09; BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)"):** de
  groepssaldi van 16-09 eindigden mét "niet gemeten" en een meetrecept dat niemand draaide; de feature stond vijf dagen kapot in productie
  (35/35 leden `fout`) zonder enig signaal, want de enige zichtbare uitkomst was een grijze kaart. Regel: (1) een bouwrapport mét "niet
  gemeten" levert in dezelfde run een vervolg-opdracht in `opdrachten/inbox/` mét `niet vóór:` (deploy + eerste scheduler-run) én het
  meetrecept als dispatch-onderdeel in `nameting.yml` (if-tak + `options:` + `via_gh_onderdeel`) — het antwoord komt dan als bot-bestand
  op main, niet als belofte; (2) élke nachtelijke stand/cache die een UI-kaart voedt en een fout-status kent, heeft een regressie-detector
  in het reconciliatieblok (LET-OP mét systeemmail + audit), zodat "kapot" een handeling wordt en geen kleur; (3) een test-stub voor een
  externe bron speelt het bewezen gedrag van die bron na (assert op de letterlijke query/het domein) — een stub die alles accepteert
  bewijst niets over de query. Les in `Platform/registers/verbeteringen.md` (21-09).

<!-- toegevoegd 21-09-2026, opdracht "BUG-rlz-boek-wachtrij-job-zonder-command-python-exec-failed-deploy-yml" -->
- **Een job die door de deploy wordt aangemaakt erft niets van het bootstrap-script — élke eigenschap die de start bepaalt staat in de
  deploy zelf (BUG 21-09; BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)"):** job `rlz-boek-wachtrij` (18-09) was de
  eerste job die `deploy.yml` zélf aanmaakte; de F3-lus gaf alleen `--args`, de Dockerfile heeft bewust geen ENTRYPOINT en
  `f3_jobs.sh` zag 'm daarna als "bestaat al — overgeslagen" → `command: leeg`, élke executie "Application exec likely failed"
  zonder één regel Python-uitvoer (Cloud Logging job-kant: honderden mislukte starts 18→21-09), vijf boekingen van 19-09 06:55
  tot 21-09 15:31 op `wordt_geboekt` (leesreplica: 140 trigger-audits `geslaagd`, 0 `mislukt` — de trigger werkte, de
  executie startte niet). Regels: (1) élke `gcloud run jobs deploy` in `deploy.yml` draagt een expliciet `--command`
  (F3-lus `python`, rlz-migratie `alembic`, rlz-smoketest `python`); GEEN `ENTRYPOINT ["python"]` in de Dockerfile — dat maakt
  de service-CMD `sh -c exec uvicorn …` tot `python sh -c …`; guard `tests/unit/test_deploy_yml_jobs_command.py`. (2)
  **Job-smoketest ná de F3-lus:** élke job uit de lus start één keer als `python -m app.cli --smoketest <cli>` (`execute --wait`,
  parallel; `app/cli.py::_job_smoketest` = argparse + imports + settings + `SELECT 1`, géén werk) — een job die niet start maakt
  de deploy rood en mailt het beheer (`if: failure()`); les 10-09 "service en jobs uit de pas" geldt ook voor start-baarheid;
  guard `tests/unit/test_cli_smoketest.py` roept élke CLI-vorm uit de lus letterlijk aan. (3) **`f3_jobs.sh`:** stap 4 "bestaat al"
  toetst het startcommando (`spec.template.spec.template.spec.containers[0].command`) en zet `--command python` bij als het
  ontbreekt; stap 6 zet de VANGNET-schedulers (`rlz-boek-wachtrij`, `rlz-extractie-wachtrij`, `rlz-bank-sync`, `rlz-bewaking`,
  `rlz-webhook-afleveraar`) op ENABLED (resume alleen bij PAUSED, notificatie-cadansen houden hun bewuste pauze); stap 12 eindigt
  LUID mét "GEPAUZEERD: …" + resume-commando en "ZONDER STARTCOMMANDO: …" + update-commando; guard
  `tests/unit/test_f3_jobs_sh.py` (incl. `bash -n`). (4) **Meetlat ná deploy:** nameting-onderdeel `jobs-start` (`gh workflow run
  nameting -f onderdeel=jobs-start`): startcommando per job, laatste executies rlz-boek-wachtrij, scheduler-stand vangnetten
  (nameting@ zonder cloudscheduler.viewer = "niet leesbaar", geen fout), `db-lezen boek-wachtrij` (querybibliotheek:
  wordt_geboekt_nu + ingediend/trigger/afgerond/opnieuw 7 dagen); oordeelregel "alle jobs dragen command python".
  Vervolg-opdracht `opdrachten/inbox/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md` (`niet vóór:`). Les in
  `Platform/registers/verbeteringen.md` (21-09). Rapport `docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-groepssaldi-na-deploy-kempen-groep" -->
- **Een fix op bron-gedrag dekt het hele pad van de motor, niet alleen de call die faalde; en de eigen verkenning eerst doorzoeken (22-09;
  BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)" alinea "Gemeten 22-09"):** de fix van 21-09 haalde het
  int-literal op het enum-veld `AccountType` uit de Ledgers-call en schreef in api-verkenning dat `Status eq 2` "in productie geen 400 geeft" —
  maar die call (`saldi.ic_open`) was vóór de fix nooit bereikt, en drie secties hoger stond al de STAP-0-tabel "Status is een enum-type,
  `Status eq 1` = 400". De nameting van 22-09 vond daardoor 29/35 leden opnieuw `fout`, één dag ná "GEFIXT". Regels: (1) ná een bron-fout
  op één call loop je élke call van dezelfde motor na op hetzelfde patroon (hier: alle `$filter`-strings in `saldi.py` — Ledgers,
  JournalEntryLines, Sales-/PurchaseInvoices) én zet je het patroon in de guard (`ENUM_VELDEN`), niet alleen het ene veld; (2) een uitspraak
  "veld X is kennelijk Edm.Int32" zonder eigen STAP-0 is geen feit — `grep` de api-verkenning op het veld vóór je 'm opschrijft; een claim
  die een eerdere STAP-0 tegenspreekt is een rode vlag, geen open vraag; (3) de meting die de bug vond deed precies wat de regel van 21-09
  voorschrijft ("niet gemeten" = schuld mét vervaldatum) — de nameting-opdracht mét `niet vóór:` + dispatch-onderdeel + regressie-detector
  hebben een vijfdaagse stilte tot één dag teruggebracht. Rapport `docs/rapporten/2026-09-22-nameting-groepssaldi-na-deploy.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-iban-wissel-cache-na-deploy" -->
- **Een meetrecept dat een logregel noemt is pas af als die regel in productie aantoonbaar aankomt (22-09; BESLISSINGEN "CHECKS-CACHE —
  INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09" alinea "Gemeten 22-09"):** het meetrecept van "Boeken sneller" (18-09) en het beslispunt
  "15 min omhoog ná een week `checks.extern` meten" steunden op `jsonPayload.message="server_timing"` — die regel heeft Cloud Logging
  nooit bereikt: `logger.info` van de `app`-loggers had geen handler (Python-root op WARNING), alleen uvicorn's access-log kwam aan als
  textPayload. Vier dagen lang was de meetlat leeg zonder dat iemand het zag. Regels: (1) wie een logregel als meetlat opvoert, leest 'm
  ná de eerste deploy één keer terug uit Cloud Logging (of laat de nameting-workflow dat doen) — "staat in de code" ≠ "komt aan"; (2) de
  app logt gestructureerd via `app/logboek.py` (JSON op stderr, root WARNING, `app` INFO; service én jobs) — nooit een tweede
  logconfiguratie ernaast; (3) terugvalmeting voor route-duur = `httpRequest.latency` in het request-log (hele route, incl. wachten),
  altijd mét vermelding dat het geen `checks.extern` is. Rapport `docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-corrigeren-testadministratie" (poging 2) -->
- **Een nameting die op de testadministratie schrijft, toetst éérst de stand van die administratie — in het bouwrapport, niet pas in de
  nameting (22-09; BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)" alinea "Gemeten 22-09"):** de
  nameting-opdracht van 21-09 zei "upload in de web-app op de RLZ-testadministratie", maar die administratie ("Administratiekantoor Nijenhuis
  (test)", `faae29c5`) stond sinds 30-08 gearchiveerd, boeken uit en zonder credential (archiveren trekt de login in — bedoeld gedrag); de
  schrijvende stappen waren dus voor niemand uitvoerbaar zonder dearchiveren mét de TESTADMIN-login, en poging 1 verbrandde vijf minuten
  sessielimiet zonder dat te zien. Regels: (1) een bouwrapport dat een schrijvende nameting op de testadministratie aankondigt, leest in
  dezelfde run haar stand van de leesreplica (`gearchiveerd_op`, `boeken_ingeschakeld`, `rlz_credential`-rij) en zet een eventueel klikpunt
  (dearchiveren/Boeken AAN) in de opdracht zelf; (2) een CC-run dearchiveert nooit zelf en zet nooit een credential — de webservice-login is
  secrets-terrein, de TEST-referentie-regel sluit élke andere administratie uit, dus de uitkomst is dan een klikpunt mét letterlijke stappen +
  de lees-only meetlat als dispatch-onderdeel (regel 21-09) zodat het bewijs ná de klik als bot-bestand komt; (3) een vervolg-opdracht die op
  een klik wacht legt zichzelf terug in de inbox mét `niet vóór:` +1 dag (rij (k)), hoogstens drie keer, daarna `mislukt/` mét het klikpunt —
  nooit een reeks lege "niet gemeten"-rapporten. Bijvangst: het jobs-image-pad uit de opdrachttekst (`template.template.containers[0].image`)
  geeft een lege waarde; het juiste veld is `spec.template.spec.template.spec.containers[0].image` (zoals `f3_jobs.sh`). Rapport
  `docs/rapporten/2026-09-22-nameting-corrigeren-testadministratie.md`.

<!-- toegevoegd 22-09-2026, opdracht "vgg-toewijzing-schoffelstraat-29-plus-schrijf-c" -->
- **Een gedocumenteerd "later"-gat in een schrijfpad is een guard aan de schrijfgrens, geen commentaarregel; en een gestrande job-executie
  toont altijd haar rapport (22-09; BESLISSINGEN "VGG — BESLISPUNT 1 BESLIST: TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)"
  alinea "Uitgevoerd 22-09"):** `vertaling.py` droeg sinds 12-09 de regel "de analytic-sleutel is in de dry-run `pand:<code>` (run 3 zoekt/
  maakt de analytic aan)"; het schrijfpad kwam er nooit, en het eerste document mét pand-analytic dat SCHRIJF c bereikte strandde op
  `action_post` (Odoo 500, pseudo-sleutel in `analytic_distribution`) — ná zes eerdere metingen en drie plan-runs die het niet kónden zien,
  want Odoo valideert de sleutel pas bij posten. Regels: (1) élke plaatshouder die een schrijfpad later moet oplossen krijgt in dezelfde
  commit een guard op de schrijffunctie (hier `maak_concept_move` → `AnalyticNietOpgelost`) én een dry-run-regel die de open stap benoemt
  ("→ ZOU aanmaken (…)"), zodat "nog niet gebouwd" zichtbaar is in élk plan-rapport en nooit pas in productie; (2) een fix op een schrijfpad
  dekt óók de sporen die de gestrande poging al achterliet (concept 3370 mét pseudo-sleutel → `herstel_regels` vóór het posten) — een
  idempotent anker dat een kapot concept hergebruikt, herhaalt anders dezelfde fout; (3) een wrapper-script onder `set -euo pipefail` houdt de
  exitcode van `gcloud run jobs execute --wait` vast en leest het log ALTIJD (`vgg_blok7_odoo_writes.sh::execute`): op 22-09 eindigde het
  script met exit 1 zonder één regel rapport, terwijl de uitkomst (2 partners, 2 concepten, stap 3 FOUT) alleen in Cloud Logging stond;
  (4) een gestrande SCHRIJF-stap is een systeemfout van de bouw (regel 19-09 poging 2): fix + guard + reproductietest in dezelfde run, de
  meetlat opnieuw ná deploy als vervolg-opdracht mét `niet vóór:`. Rapport `docs/rapporten/2026-09-22-vgg-toewijzing-schoffelstraat-schrijf-c.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-jobs-start-en-boek-wachtrij-trigger" -->
- **Gemeten 22-09 — F3-jobs `command python`, job-smoketest, vangnetten (BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST +
  WORDT_GEBOEKT LET-OP (21-09)" alinea "Gemeten 22-09"; rapport `docs/rapporten/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`):**
  **werkt in productie: JA** voor het startcommando (bot-bestand `verkenning/nameting-jobs-start-22-09.txt`, commit `a786e53`: 16 jobs `python`,
  `rlz-migratie` `alembic`, alle op image `142f33c`), de job-smoketest (deploys `fb63be5` en `142f33c`: 15 × "job-smoketest ‹job›: start ok"), de
  vangnet-schedulers (owner-sessie: `rlz-boek-wachtrij` */2, `rlz-extractie-wachtrij` */10, `rlz-bewaking` */15, `rlz-webhook-afleveraar` */5
  ENABLED; `rlz-bank-sync` heeft bewust géén scheduler — on-demand, f3_jobs.sh meldt "geen scheduler … overgeslagen") en de job zelf (exact 30
  executies/uur sinds de deploy, 0 × "exec likely failed"). **Trigger-pad niet gemeten** (geen `boek_wachtrij_ingediend` ná de deploy; poging 2 =
  `opdrachten/inbox/2026-09-23-nameting-boek-wachtrij-trigger-pad-poging-2.md`, `niet vóór: 2026-09-23 09:00`, hoogstens drie pogingen). Twee
  lessen: (1) **een nieuw dispatch-onderdeel heeft VIER plekken, niet drie** — if-tak + `options:` + `via_gh_onderdeel` (regel 19-09) én een
  `OORDEEL_BRON`-tak: de bot-commit `a786e53` droeg "Oordeel: ROOD" uit het VGG-replay-rapport van die dag terwijl het eigen rapport groen was;
  sinds 22-09 leest de else-tak `nameting-$ONDERDEEL-$DATUM.txt` en lezen alleen `alles|a|b|c|d|e` het replay-rapport, guard
  `test_nameting_workflow.py::test_elk_onderdeel_met_eigen_rapport_leest_zijn_eigen_oordeelregel` (parametrisch over élk `UIT`-bestand) — het
  bot-BESTAND blijft de bron van een meting, het commitbericht is een samenvatting; (2) `nameting@` leest de scheduler-stand niet
  (`cloudscheduler.viewer` ontbreekt → "niet leesbaar") — beslispunt Peter: één owner-binding, dan meet `jobs-start` de vangnetten zelf; tot dan
  meet de owner-sessie ze en noemt het rapport dat expliciet. De testadministratie in een opdrachttekst bij haar RLZ-adminId (`8dbfb856…`) is
  platform-id `faae29c5` — gearchiveerd zonder credential (zie de regel van 22-09 hierboven).

<!-- toegevoegd 23-09-2026, opdracht "intake-tweede-postvak-facturen-kempengroep-direct-plus-postvakbewaking-en-message-id" -->
- **Secrets: user-managed replicatie in europe-west4; IMAP-metingen alleen op een job mét de credentials (23-09; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)"):**
  (1) élk nieuw Secret Manager-secret wordt aangemaakt mét `--replication-policy=user-managed --locations=europe-west4` — de org-policy
  `gcp.resourceLocations` weigert `automatic`/global (Peter 22-09 bij `INTAKE_KEMPENGROEP_IMAP_WACHTWOORD`); `f3_jobs.sh` doet dat zo voor
  beide IMAP-secrets. Secret-VERSIES zet Peter zelf (`gcloud secrets versions add …`), nooit via CC/Cowork. (2) `nameting@` heeft geen
  secrets en kan dus geen postvak lezen; een IMAP-rakende meting (postvak-audit, herstelrun) draait uitsluitend op een job die de
  INTAKE-envset draagt — sinds 23-09 óók `rlz-reconciliatie`, zodat het lees-only `intake-postvak-audit` via `nameting.sh`/dispatch-onderdeel
  `intake-postvak-audit` als bot-bestand op main landt; de SCHRIJVENDE herstelrun (`intake-postvak-verwerken --sinds …`) is een
  `gcloud run jobs execute rlz-intake-imap[-kempengroep] --args=…` in Peters owner-sessie ná deploy (regel 08-09), nooit via nameting.sh.
  (3) Een job-alias (`intake-postvak-kempengroep-verwerken`) i.p.v. CLI-argumenten in de F3-lus: `deploy.yml` splitst `--args` op komma's
  en de smoketest op `^|^` — één CLI-woord per job houdt beide guards (`test_deploy_yml_jobs_command`, `test_cli_smoketest`) eenduidig.

<!-- toegevoegd 23-09-2026, opdracht "nameting-iban-wissel-cache-mens-en-server-timing" -->
- **Een replica-sweep mét `2>/dev/null` bewijst geen 0; en een status-contract scherm↔server hoort in een route-test (23-09;
  BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09" alinea "Gemeten 23-09"):** (1) de eerste audit-sweep van 23-09 (79 × `db_lezen.sh`, stderr weggegooid,
  parallel aan een tweede proxy op een andere poort) meldde "0 rijen sinds de deploy" terwijl er 9 stonden — de gcloud-describe in
  het script faalde transient en élke iteratie eindigde stil; pas de telling op `leverancier_iban` (4 + 3 + 2 nieuwe rijen) ontmaskerde
  de 0. Regel: een sweep-script logt per iteratie de exitcode én de eerste foutregel, draait nooit parallel aan een andere
  `db_lezen.sh` (één proxy tegelijk) en een "0" telt pas als een onafhankelijke telling (de brontabel) hetzelfde zegt. (2) De fix van
  21-09 hing aan "409 → checks vers", maar de router gaf 400 en geen test las de HTTP-status: de service-test deed `pytest.raises
  (IbanAlVertrouwd)`, de vitest mockte 409 — beide groen, productie kapot. Regel: élk contract tussen scherm en server op statuscode
  of tekst staat in één route-test (TestClient, letterlijke status + tekst) én de vitest gebruikt exact die status; het scherm
  herkent daarnaast de TEKST (patroon), zodat een statuswissel nooit stil een route dooft. (3) Een tweede "niet gemeten" op dezelfde
  meting → dispatch-onderdeel (hier `checks-cache`), poging 3 mét `niet vóór:` is de laatste vóór `mislukt/` (regel 22-09 (3)).

<!-- toegevoegd 23-09-2026, opdracht "nameting-ter-accordering-bestaanscheck-na-deploy" (poging 1) -->
- **Een teller die niet bewaard wordt, meet je door de stand op het tijdstip te reconstrueren; en een backend-claim in een rapport leest
  `boekhoud_backend` (23-09; BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)" alinea
  "Gemeten 23-09"):** (1) de herinneringsmail bewaart alleen `aantal_open`; de claim "extern-geboekte documenten tellen niet mee" is toch hard
  te bewijzen door de aan-de-beurt-stand op het jobmoment T uit `document_accordering` × `accordering_stap` te herleiden (rondes open op T:
  `aangeboden_op` < T en status open óf `afgerond_op` > T; eerste vereiste stap mét besluit NULL óf `besloten_op` > T), per administratie in
  eigen RLS-scope (loop over de scope van de accordeur, één proxy tegelijk, exitcode per iteratie in het logbestand) — 15 vs 13 en 46 vs 45
  sloten cent-exact op de extern-geboekte documenten. Een teller zonder bewaarde grondslag is dus geen reden voor "niet meetbaar" zolang de
  onderliggende rijen tijdstippen dragen. (2) Het bouwrapport van 22-09 schreef "Universal Steigerbouw (43, Odoo)"; in productie is
  `platform.administratie.boekhoud_backend` = `rlz` (de Odoo-overstap leeft alleen op de dev-administratie, memory "VGG Odoo bron-key"). Regel:
  een backend-claim per administratie in een rapport komt uit de leesreplica, niet uit het geheugen van een eerdere sessie. (3) `db_lezen.sh`
  weigert élke `;` — ook in een string-literal (`string_agg(x, '; ')` = "één statement per keer", exit 2); kies een ander scheidingsteken.
