Domeinen: werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-23 09:00

# Nameting checks-cache (IBAN-wissel) — de drie mens-afhankelijke metingen + eerste `server_timing`-regels ná de deploy van 22-09

**Context:** rapport `docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md` (nazorg uitgevoerd, bevestig-pad bewezen in
productie). Drie metingen bleven "niet gemeten" omdat geen mens de route raakte, en de `server_timing`-logregel bestond in productie
niet (fix `app/logboek.py` gaat mét de commit van 22-09 live). Alles lees-only; geen klikpunt nodig behalve dat een mens intussen
gewerkt heeft.

## Stap 0 — deploy-check (service ÉN `rlz-reconciliatie` op een image ≥ de commit van 22-09 mét `app/logboek.py`; `git rev-list --count
main..origin/main` toetsen en `merge --no-ff` als > 0).

## Stap 1 — metingen (lees-only)
1. **Meyer 0015.21.664.V.51.0112** (administratie 876d5515-9f8a-42f8-a33a-0022981342d6, document 2f9c342c-0aeb-4881-b53d-6e65455c5c8b):
   `scripts/gcp/db_lezen.sh` mét `--administratie` → status (was ter_accordering laag 3/3 open op 22-09), tijdlijn ná 22-09 10:40 NL,
   `rlz_boekstuknummer`. Geboekt = sterkste meting (boekstuknummer in het rapport). Niet aangeraakt = "niet gemeten", nooit "werkt niet".
2. **Request-log** `POST …/boekvoorstel/checks?extern=vers` sinds 2026-09-22T08:40:00Z (Cloud Logging, rlz-backend) — ≥ 1 = knop
   "Opnieuw controleren"/409-route gebruikt; 0 = niet gemeten.
3. **Audit** `leverancier_iban_toegevoegd` sinds 2026-09-22T08:40:00Z per administratie (RLS: loop over de administraties, recept
   `.scratch/audit-iban-sweep-22-09.sh` in het rapport van 22-09) — het VELD `checks_cache_ongeldig` moet op élke rij staan (ook bron
   baseline/bevestigd/rlz_seed), waarde ≥ 0; bij een vier-ogen-akkoord mét gecacht rapport ≥ 1.
4. **`server_timing`** in Cloud Logging: `jsonPayload.message="server_timing" jsonPayload.route="boekvoorstel_checks"` ≥ 1 regel ná de
   deploy = de logregel komt aan (werkt in productie: ja/nee); p50/p95 van `stappen_ms.extern` als er ≥ 20 regels zijn, anders aantal
   noemen. Terugval blijft `httpRequest.latency` (hele route).

## Stap 2 — rapport
`docs/rapporten/2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md` + INDEX + "## Gelezen regels"; per meting letterlijk
"werkt in productie: ja/nee/niet gemeten"; alinea "Gemeten 23-09" onder de BESLISSINGEN-sectie van 21-09. Rood (IBAN-wissel Blokkerend
ná een verse run terwijl het IBAN in `leverancier_iban` staat; of `server_timing` 0 regels terwijl er checks-requests waren) = letterlijke
melding + fix in dezelfde run.
