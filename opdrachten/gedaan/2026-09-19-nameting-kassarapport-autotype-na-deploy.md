uitgevoerd 2026-09-19 (poging 1 — NIET GEMETEN, deploy geblokkeerd; poging 2 in de inbox), rapport: docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-1-deploy-geblokkeerd.md

Domeinen: omzet, reconciliatie, werkloop-productie

# OPDRACHT 19-09 — Nameting + nazorg ná deploy: kassarapport automatisch typeren (Van Boxtel Journaal 1-9/2-9/3-9) — vervolg op
# docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md

**Voorwaarde (stap 0):** de commit met `app/omzet/autotype.py` is gedeployd op service ÉN jobs (`gh run view` deploy.yml groen;
`gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'` = image van de service). Niet
gedeployd = wachten, nooit een lokaal proces tegen productie.

## Nazorg + meetrecept
1. Dry-run Van Boxtel op de job-image: `gcloud run jobs execute rlz-reconciliatie --args="-m,app.cli,kassarapport-autotype-nazorg,--dry-run,--administratie,Van Boxtel"`
   → verwacht "1 administratie(s), 4 kandidaat/kandidaten, zou omzetten 4" (Journaal 1-9/2-9/3-9 + één profx-treffer). Dan de echte run
   (zonder `--dry-run`) — of de reconciliatie van 06:30 die hetzelfde doet — en daarna kantoorbreed `--dry-run` = 0 kandidaten.
2. Leesreplica (`db_lezen.sh --administratie ‹Van Boxtel›`): de vier documenten op soort `kassarapport`, tijdlijnregel "type
   automatisch gewijzigd", audit `soort_automatisch_gewijzigd` 4× + `kassarapport_autotype_run` 1× (verwacht 4 / gedaan 4).
3. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen omzet --lees-only` → Van Boxtel: 1 × `kassarapport_in_werkvoorraad`
   (signaal omzetrekeningen), 0 × profx; Inzicht › Reconciliatie 340 → 336 aandacht. Reconciliatiemail: teller `kassarapport_autotype`.
4. Rapportregel "werkt in productie: ja/nee" + INDEX; BESLISSINGEN-status van "niet gemeten" naar "gemeten <datum>".
Lees-only behalve de nazorg-CLI (stap 1 = expliciete schrijvende nazorg via `gcloud run jobs execute`).
