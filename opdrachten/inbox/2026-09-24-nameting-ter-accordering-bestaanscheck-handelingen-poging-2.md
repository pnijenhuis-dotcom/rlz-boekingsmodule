Domeinen: reconciliatie, accordering-native-app, werkloop-productie
niet vóór: 2026-09-24 09:00

# NAMETING 24-09 — bestaanscheck "intussen buiten de module geboekt": handelingen + banner (poging 2 van hoogstens 3)

**Context:** poging 1 (`docs/rapporten/2026-09-23-nameting-ter-accordering-bestaanscheck-na-deploy.md`) mat hercontrole, bevindingssoort, actiemail,
server-poort (32 × 409) en herinnering-onderdrukking = WERKT IN PRODUCTIE JA; **niet gemeten:** de twee kantoor-handelingen (0 × POST, ongebruikt),
de banner op het toestel en de boekfout-kern ná een laatste akkoord. BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK 'INTUSSEN BUITEN DE
MODULE GEBOEKT' (Peter 22-09)" alinea "Gemeten 23-09". Alles lees-only (nameting@).

Stap 0 — `git rev-list --count main..origin/main` → `merge --no-ff` bij divergentie; deploy-check service ÉN jobs op het beeld van de commit mét het
dispatch-onderdeel `extern-geboekt` (23-09 avond).

1. **Dispatch-onderdeel** `gh workflow run nameting -f onderdeel=extern-geboekt` (of `scripts/gcp/nameting.sh` zonder TTY) → bot-bestand
   `verkenning/nameting-extern-geboekt-24-09.txt` op main: oordeelregel "POST afwijzen 200 = A, toch-verschillend 200 = B, 5xx = C, accordeur-409 = D,
   bevindingsregels job-log = E". A + B ≥ 1 en C = 0 → handelingen "werkt in productie: ja"; anders opnieuw "niet gemeten (ongebruikt)".
2. **Bij een handeling:** audits `document_afgewezen` (reden "Al geboekt in Reeleezee als …"), `accordering_vervallen` mét marker
   `accordering_vervallen_extern_geboekt` (leesreplica per administratie), tijdlijnregel "niet meer nodig: al geboekt in Reeleezee (…)"; bij "Toch
   verschillend": audit `extern_duplicaat_toch_verschillend` + de bevinding verdwijnt uit de volgende run (`reconciliatie_auto_gesloten` of acceptatie).
3. **Échte run 24-09 06:30:** dezelfde 11 (minus afgewezen) in `reconciliatie_bevinding`; `HERCONTROLE`-regels; geen explosie-rem.
4. **Banner:** request-log `GET /accordering/wachtrij` + eventuele 409 op akkoord; een accordeur die ná een app-herstart géén akkoord meer probeert
   op `4d25c900` (Universal) is het indirecte bewijs; blijft "niet gemeten" zonder toestel.
5. Rapport + INDEX + Gelezen regels; BESLISSINGEN-alinea "Gemeten 24-09"; opdracht → gedaan. Blijft het "niet gemeten (ongebruikt)": poging 3 mét
   `niet vóór: 2026-09-25 09:00` is de laatste vóór `mislukt/` mét het klikpunt (regel 22-09 (3)).
