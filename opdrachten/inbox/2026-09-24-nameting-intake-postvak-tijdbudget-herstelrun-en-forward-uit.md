Domeinen: intake-extractie, reconciliatie, werkloop-productie
niet vóór: 2026-09-24 09:00

# NAMETING 24-09 — intake-postvakken: tijdbudget in de job-log, herstelrun `--sinds 2026-07-25` (klikpunt Peter), forward UIT, blok `intake` tweede dag

**Context:** rapport `docs/rapporten/2026-09-23-nameting-intake-postvak-audit-en-eerste-run.md` (poging 1 van deze meting; audit GEMETEN, eerste groene run JA,
blok `intake` JA, tijdbudget NIET GEMETEN — gebouwd 23-09 in dezelfde run: `intake_postvak_tijdbudget_s` 540, `--tijdbudget-s`, teller-reden
`postvak_tijdbudget`). BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)" alinea
"Gemeten 23-09". Stap 0: `git rev-list --count main..origin/main` → merge --no-ff bij divergentie; deploy-check service ÉN jobs
(`rlz-intake-imap`, `rlz-intake-imap-kempengroep`, `rlz-reconciliatie` op hetzelfde beeld als de commit mét het tijdbudget).

## Opdracht (lees-only, geen eigen schrijvende job-executie)
1. **Tijdbudget in productie:** Cloud Logging job `rlz-intake-imap-kempengroep` + `rlz-intake-imap` ná de deploy: (a) 0 × "Terminating task because it
   has reached the maximum timeout" en 0 mislukte executies (`gcloud run jobs executions list … --format='value(status.failedCount)'`); (b) als Peter
   de herstelrun (stap 2) draaide: de regel `TIJDBUDGET (… s) bereikt: N bericht(en) … nog niet verwerkt` in het log van die executies + audit
   `intake_postvak_run` mét `tijdbudget_bereikt`/`niet_gehaald` (leesreplica `db_lezen.sh`); zonder herstelrun = "afwezig-pad: 0 × TIJDBUDGET,
   alle executies groen" (dat is óók een uitkomst, geen "niet gemeten" — het aanwezig-pad staat in de suite).
2. **Herstelrun (handeling Peter, 23-09 in het rapport):** is `intake-postvak-kempengroep-verwerken --sinds 2026-07-25` (en idem `intake-postvak-verwerken`)
   gedraaid? Bewijs = `Postvak verwerkt (…)`-regels mét `venster vanaf 2026-07-25` in Cloud Logging + de groei van `intake_bericht_verwerkt` per kanaal
   (leesreplica). Niet gedraaid → klikpunt letterlijk herhalen, terug in de inbox mét `niet vóór:` +1 dag (dit is poging 2; poging 3 is de laatste vóór `mislukt/`).
3. **Forward UIT (handeling Peter):** `intake_bericht_verwerkt` kanaal `facturen` — al_bekend-rijen mét een Message-ID dat óók in kanaal `facturen_kempengroep`
   staat = de forward loopt nog; 0 zulke rijen ná de eerste groene run (23-09 06:55Z) + geen `dubbel_via_forward` > 0 = forward uit óf rewrite (dan de audit
   `intake-postvak-audit --sinds 2026-09-23` als bewijs: doorgifte 0 bij bron > 0).
4. **Blok `intake` tweede dag:** leesreplica `reconciliatie_run.samenvatting->'intake'` van de run van 24-09 06:30 (`gecontroleerd` 2, geen
   `intake_postvak_niet_geconfigureerd`), bevindingen `intake_postvak_verschil` (verwacht: alleen berichten van ná de laatste */10-run, of 0) en
   `intake_uit_spam`; de verdwenen afwijking van 23-09 (17 berichten) = `reconciliatie_auto_gesloten` in `platform.audit_event`.
5. Rapport `docs/rapporten/2026-09-24-nameting-intake-postvak-tijdbudget-herstelrun-en-forward-uit.md` + INDEX + Gelezen regels; BESLISSINGEN-alinea
   "Gemeten 24-09" onder de sectie; regels-alinea's bijwerken ("werkt in productie: ja/nee" voor het tijdbudget).
---
LEESPLICHT (Domeinen-kopregel): lees EERST volledig docs/regels/intake-extractie.md, docs/regels/reconciliatie.md, docs/regels/werkloop-productie.md.
Werkloop automatisch: opdracht → lopend/ → gedaan/ mét kopregel; committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat).
