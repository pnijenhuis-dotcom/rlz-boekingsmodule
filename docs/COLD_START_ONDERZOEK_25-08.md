# Koude-start-onderzoek `rlz-backend` (steigerbouw-run C3, 2026-08-25)

**Vraag Peter (24-08):** de web-app is traag na inactiviteit. Meet de koude-start-tijd, rapporteer en doe
een kostenvoorstel voor `min-instances=1`. **Niet zelf aanzetten — besluit is aan Peter.**

## Bevindingen (Cloud Run-logs, gemeten 25-08)

Huidige service-config (`gcloud run services describe rlz-backend`, revisie `rlz-backend-00211`):
`minScale` **niet gezet (= 0, schaalt naar nul)**, `startup-cpu-boost` **aan**, CPU-throttling default
(request-based billing), 1 vCPU / 1 GiB, Cloud SQL via Auth-Proxy-socket.

| Meting | Waarde | Bron |
|---|---|---|
| Warme request (`/health`, SPA-index) | **60–115 ms** totaal vanaf NL | curl 3× 25-08 21:45 |
| App-startup ín de container ("Waiting for application startup" → "startup complete") | **≈ 0,9–1,0 s** | uvicorn-log 18:06:28, 18:06:55, 19:04:11 |
| **Volledige koude start** (eerste request op een nieuwe instance, incl. scheduling + image-pull + Python-imports + lifespan) | **14,6 – 16,9 s** | request-latency op statische bestanden die anders < 5 ms kosten: `/` 14,6 s (16:19), `/favicon.ico` 15,4 s (16:19), `/robots.txt` 16,1 s (17:52), `/beeldmerk-n.svg` 16,9 s (19:03) |
| Half-koude request (instance startend, request wacht mee) | 7,5 s (`/auth/token/vernieuwen` 17:03), 9,3 s (`/documenten` 14:45) | idem |
| Aantal koude starts vandaag (25-08, tot 21:45) | **≥ 4** (14:45, 16:19, 17:52, 19:03) — patroon: ná elke pauze van > ~15 min | uvicorn-startlogs + latency-uitschieters |

Conclusie: de "traagheid na inactiviteit" is een **koude start van ~15 s**, waarvan slechts ~1 s in
onze eigen app-startup zit. De rest is Cloud Run-infrastructuur (container plannen, image
trekken, Python-interpreter + dependency-imports vóór de lifespan) — met `startup-cpu-boost` al aan.
Bijzaak: de eerste RLZ-/DB-call ná de start bouwt óók nog connectie-pools op (de 2–6 s-uitschieters
op boeken/sync zijn géén koude starts maar RLZ-round-trips).

## Kostenvoorstel `min-instances=1` (europe-west4, tier-1-prijzen; controleren in de GCP-prijscalculator)

Twee smaken; beide houden precies één instance permanent warm zodat de koude start verdwijnt voor
het eerste gelijktijdige gebruik (een tweede parallelle instance kan nog koud starten — bij dit
kantoor zeldzaam).

| Variant | Wat | Indicatie per maand |
|---|---|---|
| **A. `--min-instances 1` met request-based billing (huidige CPU-throttling)** | idle-instance wordt tegen het **idle-tarief** afgerekend (vCPU idle ≈ $0,0000025/s, geheugen idle ≈ $0,00000025/GiB-s bij 1 vCPU / 1 GiB), requests blijven per gebruik | **≈ $7–8 (≈ € 7)** + ongewijzigd verbruik |
| B. `--min-instances 1` met `--no-cpu-throttling` (CPU altijd toegewezen) | volledig vCPU-tarief 24/7 (≈ $0,000018/vCPU-s + $0,000002/GiB-s) — alleen zinvol als er óók achtergrondwerk in de service zou draaien (dat doen we bewust in Cloud Run-jobs) | ≈ $50–55 (≈ € 48) |

**Aanbeveling: variant A.** Eén regel in `.github/workflows/deploy.yml` (`gcloud run deploy … --min-instances 1`)
— config-as-code, dus geen klikwerk buiten de repo; terugdraaien = regel weghalen. Kosten ~€ 7/maand;
opbrengst: geen 15-seconden-wachttijd bij de eerste klik na een pauze (meerdere keren per dag).

Alternatieven die **niet** volstaan: (1) een externe "keep-warm"-ping elke 5 min (Cloud Scheduler →
`/health`) is goedkoper (< € 1) maar hackerig, werkt niet gegarandeerd (Cloud Run mag toch
terugschalen) en telt als requests; (2) imports uitdunnen levert hooguit de ~1 s app-startup op,
niet de ~14 s infrastructuur.

## Besluit

**Open — aan Peter.** Bij akkoord: `--min-instances 1` toevoegen aan de deploy-stap
(`.github/workflows/deploy.yml`, "Cloud Run-revisie uitrollen") en het budget-alert (F0) met ~€ 10
ophogen. Dit onderzoek is vastgelegd in BESLISSINGEN "STEIGERBOUW-RUN 25-08 — BLOK C" (C3).
