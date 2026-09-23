Domeinen: btw, administraties-instellingen, werkvoorraad-controlescherm, werkloop-productie
niet vóór: 2026-09-24 09:00

# NAMETING 24-09 — Btw-plichtig VGG: herstel Lacy Lion 2026-042 (+ 2026-041, E.M.S 20260014) ná Peters "Corrigeren…" — poging 2 van hoogstens 3

**Context:** poging 1 = `docs/rapporten/2026-09-23-nameting-btw-plichtig-vgg-data-stap-en-lacy-lion.md` (data-stap VGG GEZET 23-09 16:45 UTC,
sync-signaal JA, nazorgrapport JA: TE WEINIG € 1.401,43 over drie documenten; herstel NIET GEMETEN = klikpunt). BESLISSINGEN "BTW-PLICHTIG PER
ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)" alinea "Gemeten 23-09". Lees-only; geen eigen schrijvende stap.

Stap 0 — `git rev-list --count main..origin/main` → `merge --no-ff` bij divergentie; deploy-check service ÉN jobs (`rlz-reconciliatie`) op
hetzelfde beeld als origin/main.

1. **Is er geklikt?** Request-log service (Cloud Logging, `httpRequest.requestUrl:"/corrigeren"` sinds 2026-09-23T16:45Z) → verwacht
   `POST /administraties/cc07e461-…/documenten/0b1f8c00-…/corrigeren` 200 (en/of `2488a20b-…`, `7e864b9e-…`). Leesreplica (VGG-scope
   `--administratie cc07e461-3288-4065-85ed-9005495a22ea`): `document.status` van de drie (geboekt → klaar_om_te_boeken → geboekt), `boekvoorstel.boek_cyclus`
   1, `boekvoorstel_regel` netto = bruto / btw 0 / taxrate "NL, Geen BTW (Vrijgesteld)", audit `document_gecorrigeerd` (of de audit-actie uit
   `app/documenten/corrigeren.py`) mét reden.
2. **Geen klik** → deze opdracht terug in `opdrachten/inbox/` mét `niet vóór:` +1 dag bovenin (rij (k)); ná poging 3 → `opdrachten/mislukt/` mét
   het klikpunt (rapport poging 1 §5: drie documenten mét datum/bedrag/bron). Nooit "werkt niet".
3. **Wel geklikt** → `gh workflow run nameting.yml -f onderdeel=btw-niet-plichtig` → bot-bestand `verkenning/nameting-btw-niet-plichtig-24-09.txt`:
   het gecorrigeerde document verdwijnt uit de MODULE-tabel (btw = 0 op élke regel) óf staat er mét TE WEINIG 0.00; TOTAAL daalt met het
   herstelde bedrag (322,38 / 344,05 / 735,00). RLZ-kant lees-only via `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh rlz-lezen --administratie
   "Vastgoedgroep" --pad PurchaseInvoices --filter "Reference eq '2026-042'"` → `BaseInvoiceAmount` 1857.51, `BasePaidAmount` 1535.13,
   `BaseRemainingAmount` 322.38 (nabetaling open) — geen 21 %-regel meer (`TotalTaxAmount` 0).
4. **Check-gedrag:** request-log `GET …/documenten/0b1f8c00-…/checks` ná de correctie → geen rode "Btw in niet-btw-plichtige administratie"; als
   de boeking ná "Boeken in RLZ" via `rlz-boek-wachtrij` liep: `db-lezen boek-wachtrij` toont de indiening + afronding.
5. Rapport + INDEX + Gelezen regels; BESLISSINGEN-alinea "Gemeten 24-09" (herstel: ja/nee/niet gemeten); regels-alinea btw.md bijwerken.
---
LEESPLICHT (Domeinen-kopregel): lees EERST volledig, vóór je iets anders doet: docs/regels/btw.md, docs/regels/administraties-instellingen.md,
docs/regels/werkvoorraad-controlescherm.md, docs/regels/werkloop-productie.md — niet gelezen = niet beginnen.
Werkloop automatisch: sluit af met (1) rapport `docs/rapporten/<datum>-<slug>.md` + INDEX-regel + "## Gelezen regels", (2) opdrachtbestand naar
`opdrachten/gedaan/` mét kopregel, (3) committen (nooit pushen). Peter kijkt niet mee.
