Domeinen: werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-24 09:00

# Nameting checks-cache (IBAN-wissel) — poging 3 (laatste): al-vertrouwd = 409 → checks vers, Meyer, vier-ogen-akkoord

**Context:** rapport `docs/rapporten/2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md` (poging 2, 23-09). Gemeten: `server_timing` komt aan, audit-veld op élke set-mutatie. Nog niet gemeten:
(a) Meyer 0015.21.664.V.51.0112 (administratie 876d5515-9f8a-42f8-a33a-0022981342d6, document 2f9c342c-0aeb-4881-b53d-6e65455c5c8b)
geboekt/herladen, (b) een vier-ogen-akkoord mét `checks_cache_ongeldig` ≥ 1, (c) de één-bron-route: `POST …/iban-accordering` **409**
gevolgd binnen ~10 s door `POST …/boekvoorstel/checks?extern=vers` op hetzelfde document (de fix van 23-09: 400 → 409 + scherm herkent
beide). Regel 22-09 (3): dit is de DERDE en laatste poging — opnieuw "niet gemeten" = opdracht naar `opdrachten/mislukt/` mét het
klikpunt voor Peter (zelf een afwijkend IBAN aanbieden op een testdocument), geen vierde run.

## Stap 0 — deploy-check (service ÉN `rlz-reconciliatie` op een image ≥ de fix-commit van 23-09; `git rev-list --count main..origin/main`, merge --no-ff als > 0).

## Stap 1 — metingen (lees-only)
1. `gh workflow run nameting -f onderdeel=checks-cache` → bot-bestand `verkenning/nameting-checks-cache-<dd-mm>.txt` op main
   (request-log checks/`extern=vers`, `POST …/iban-accordering` per status, `server_timing` p50/p95). Bewijs (c) = een 409-regel mét
   ≤ 10 s later een `extern=vers` op hetzelfde document-id.
2. Meyer via `scripts/gcp/db_lezen.sh` mét `--administratie` (status, gebeurtenissen ná 23-09 10:00 NL, `rlz_boekstuknummer`).
3. Audit-sweep per administratie (recept `.scratch/audit-iban-sweep-23-09-b.log`-vorm: stderr LOGGEN, één proxy tegelijk, telling
   `leverancier_iban` ernaast) sinds 2026-09-23T09:00:00Z: `iban_accordering_*`-akkoord + `checks_cache_ongeldig` ≥ 1.

## Stap 2 — rapport
`docs/rapporten/2026-09-24-nameting-iban-wissel-cache-poging-3.md` + INDEX + "## Gelezen regels"; per meting "werkt in productie:
ja/nee/niet gemeten"; alinea "Gemeten 24-09" onder de BESLISSINGEN-sectie van 21-09. Niet gemeten → `mislukt/` mét klikpunt (zie boven).
