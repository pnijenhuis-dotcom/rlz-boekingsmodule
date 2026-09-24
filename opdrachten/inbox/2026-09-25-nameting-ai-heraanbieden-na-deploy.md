Domeinen: intake-extractie, reconciliatie, werkloop-productie
niet vóór: 2026-09-24 14:00

# NAMETING — AI-heraanbieding ná limiet (BUG 24-09) ná deploy: banner weg, dry-run 202 + N, échte run (automatisch bij de intake-job) → 0, dagtellers

**Context:** rapport `docs/rapporten/2026-09-24-ai-limiet-heraanbieden.md`; BESLISSINGEN "AI-LIMIET — BANNER OP DE LIVE STAND, HERAANBIEDING NÁ
VERHOGING, DUBBELENCHECK VÓÓR DE AI-STAP (Peter 24-09)". Stap 0: `git rev-list --count main..origin/main` → merge --no-ff bij divergentie;
deploy-check service ÉN jobs (`rlz-intake-imap`, `rlz-intake-imap-kempengroep`, `rlz-reconciliatie`) op het beeld van de commit mét de motor.
Te vroeg (deploy niet live / eerste intake-run nog niet gelopen) → `niet vóór:` +1 uur bovenin en terug in inbox/ (hoogstens drie keer).

## Opdracht (lees-only; de échte heraanbieding loopt AUTOMATISCH in de intake-jobs — niets zelf uitvoeren)
1. `gh workflow run nameting -f onderdeel=ai-heraanbieden` → bot-bestand `verkenning/nameting-ai-heraanbieden-<dd-mm>.txt`: de
   dry-run-telling en `db-lezen ai-heraanbieding` (runs mét bron `intake_job:*`, gedaan/rest/overgeslagen/tellers; live telling
   `verzamelbak_ai_limiet_nu`; `ai_bespaard_dubbel`). Verwacht: ná ≥ 1 intake-job-run ná de deploy is `verzamelbak_ai_limiet_nu` gedaald
   (≤ 300 per run, tijdbudget 780 s); runs mét `kostengrens` = de poort ging dicht → klikpunt Peter (limiet, advies € 250 september).
2. `/instellingen/ai-kosten` via het request-log of Peters screenshot: `geblokkeerd=false`, `weer_actief_sinds` gevuld, banner zonder
   "geblokkeerd" (klikpunt Peter: screenshot werkvoorraad als Beheerder).
3. Cloud Logging job `rlz-intake-imap` / `rlz-intake-imap-kempengroep` sinds de deploy: regels "AI-heraanbieding ná limiet (intake_job:…)"
   mét kandidaten/gedaan/overgeslagen en de uitkomstregels per document; `GESTOPT:`-regels = zichtbaar stoppen (geen fout).
4. Reconciliatiemail/`reconciliatie_run.samenvatting.automatiseringen` van de volgende ochtend: tellers `ai_heraanbiedingen` en
   `ai_bespaard_dubbel` (verwacht/gedaan/overgeslagen), LET-OP alleen bij `kostengrens`/`volumerem`.
5. Rapport `docs/rapporten/<datum>-nameting-ai-heraanbieden-na-deploy.md` + INDEX + "Gelezen regels" + per onderdeel "werkt in productie:
   ja/nee/niet gemeten" (banner, heraanbieding automatisch, knop (alleen als iemand klikte — request-log POST /verzamelbak/ai-heraanbieden),
   dubbel vóór AI (audit-telling), dagtellers); BESLISSINGEN-alinea "Gemeten <datum>"; opdracht → gedaan mét kopregel.
