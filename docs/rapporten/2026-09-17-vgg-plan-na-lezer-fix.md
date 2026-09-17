# VGG → Odoo: `plan` ná deploy van de lezer-fix (blok 12) — 17-09 avond, lees-only, geen Odoo-writes

**Uitkomst in één zin:** de lezer-fix uit commit `519d2a0` **werkt in productie: ja** (stap0- én migratierapport dragen "replay-mapping: Odoo-rekeningen gelezen uit company 6 via de doelkoppeling: 361"; 224 vertaalbare documenten i.p.v. 58; pand-eis 39 meetbare "SIGNAAL: sluit niet" i.p.v. 94× "niet meetbaar"), maar het bewijspaar RLZ-01-00000082 blijft **"niet vertaalbaar (grootboek zonder Odoo-rekening: 8000 …)"** → **SCHRIJF c NIET uitgevoerd** (stop-regel van de opdracht). Beslispunt 1 (Toewijzing pand + soort `verkoop` en/of mapping 8000) staat open bij Peter. **Werkt in productie: lezer-fix ja · SCHRIJF c nee (niet uitgevoerd, bewust) · IBAN BNK1 niet gemeten (stap 4 niet bereikt).**

## 1. Stap 0 — deploy-stand
- `gh run list --workflow=deploy.yml --limit 1`: run `35247836292` **success** (headSha `8549d3c…`, klaar 2026-09-17T16:43:35Z). `8549d3c` is de docs-commit ná de fix-commit `519d2a0`; beide zitten in de image.
- `deploy_check` in `vgg_blok7_odoo_writes.sh`: service `rlz-backend` = job `rlz-reconciliatie` = `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:8549d3c26c3b9a56fec477b283ee8af7f30a7b02` → ok, geen drift.
- `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"` gezet (bron-key; Universal Steigerbouw heeft in productie geen Odoo-koppeling, blok 8).
- gcloud-sessie: `info@vastly.software`, project `rlz-boekhouding`, token geldig.

## 2. Stap 1 — `plan` (vier job-executies op de gedeployde image, ~19:05–19:25 CEST; logboek `.scratch/vgg-plan-17-09-avond2.log`, exit 0)
| Stap | Executie | Uitkomst | Meetrecept |
|---|---|---|---|
| `odoo-koppeling-migratiedoel --dry-run` | `rlz-reconciliatie-6zc9f` | AL MIGRATIEDOEL — ongewijzigd (idempotent, probe groen); doel `cc07e461…` (VGG), bron-koppeling `0d66ff75…` (Universal Verkoop); dagboeken BNK1 53 / MEM / LF 49 / F 48; outstanding_payments 135000 "Payments in transit" id 132 | gelijk aan de vorige run |
| `vgg-rekeningen` | `rlz-reconciliatie-6p9tg` | vijf rollen bestaand/hergebruikt: 3606·325000, 3607·326000, 3608·803100, 3609·701300, 3610·159100; koppeling-rij 0138 incl. analytic_overhead 848 | gelijk |
| `vgg-odoo-stap0 --dry-run --stap 0-6 --max-per-type 1 --boekstuk RLZ-01-00000082` | `rlz-reconciliatie-m2hst` | **"replay-mapping: Odoo-rekeningen gelezen uit company 6 via de doelkoppeling: 361"** ✔; replay 2145 moves, selectie 2025-07: in_invoice 1 · entry 0 · out_invoice 0; **bewijspaar RLZ-01-00000082: niet vertaalbaar (grootboek zonder Odoo-rekening: 8000; partner nieuw (res.partner) [iban: Ouwerkerk Notariaat] — uit bankmutatie 00112) — niets te posten, stap 4/5 niet uitvoerbaar**; stap 0/1 ZOU: RLZ-04-00000256 Gimple B.V. (1 regel); stap 2/3 geen vertaalbaar document juli 2025; stap 4 (IBAN-klikpunt) en 5 overgeslagen: geen bewijspaar | mapping ✔ · bewijspaar ✘ (verwacht, beslispunt 1) |
| `vgg-odoo-migratie --dry-run` | `rlz-reconciliatie-gblm7` | Oordeel DRY-RUN; **mapping 361** ✔; **224 vertaalbare documenten**, 1020 bankregels, 892 niet vertaalbaar (blijven buiten); fase A ZOU: documenten 224, bankregels 1020, zonder partner 0; fase B: **pand-eis afwijkingen 39** — meetbare regels "pand appollolaan-644 — Appollolaan 644: SIGNAAL: sluit niet (Δ −38.423,39)", Azielaan 334 (Δ −34.357,91), Bleijeheiderstraat 123B (Δ −21.760,99), Bordeauxdreef 79 (Δ −3.000,00), Croesinckplein 135 (Δ −31.762,09), Duifhuis 11, … (eerste 40 in het rapport); C/D niet uitgevoerd (dry-run) | 224 ✔ (≈ 224) · 39 meetbaar ✔ (39) |

**Conclusie meetrecept §3 van het vorige rapport: alle drie de verwachtingen gehaald.** De instrumentfout uit blok 12 is in productie weg; wat overblijft is uitsluitend de domeinblokkade.

## 3. Stap 2 — SCHRIJF c: NIET uitgevoerd (bewust)
De opdracht zegt: bewijspaar "niet vertaalbaar" → STOPPEN en rapporteren. Er is **niets** naar company 6 geschreven (alle vier de executies zonder kill-switch, `--dry-run`/lees-only). SCHRIJF d blijft achter de GO van Peter op een geslaagd SCHRIJF-c-rapport.

Waarom het bewijspaar nog niet vertaalbaar is (ongewijzigd t.o.v. §2b van het vorige rapport, nu bevestigd MÉT mapping):
1. RLZ **8000 "Omzet verkopen"** heeft geen Odoo-rekening in company 6 (een van de 58 ongemapte rekeningen; "mens beslist", blok 8 punt 1b).
2. Het document draagt **geen pand-toewijzing** met soort `verkoop` → de RJ-220-rol `opbrengst_panden` (803100, id 3608) grijpt niet. Daardoor Verkoop € 0,00 op álle panden en 39× "SIGNAAL: sluit niet" (notaris-ontvangst zonder geboekte verkoop) → de pand-eis van SCHRIJF d is óók rood.

## 4. Beslispunten Peter (onveranderd open; niets gekozen — geld op company 6)
1. **Bewijspaar / RLZ 8000 (42 documenten):** (A) Toewijzing pand + soort `verkoop` op RLZ-01-00000082 (advies: één toewijzing, direct toetsbaar via `plan`) en/of (B) expliciete mapping 8000 → 803100 of aanmaken 800000 income. Klikpunt vooraf: RLZ-01-00000082 in RLZ openen (regel op 8000, project/adres) — lees-only niet ophaalbaar (Receipts hebben geen record-route).
2. **IBAN op BNK1 (company 6):** niet gemeten — stap 4 wordt pas bereikt ná beslispunt 1. Blijft KLIKPUNT.
3. Project-dekking 37,2 % en de 58 ongemapte rekeningen: zie het vorige rapport (§5 punt 2–3), ongewijzigd.

**Volgorde ná beslispunt 1:** nieuwe inbox-opdracht → `plan` (bewijspaar moet "out_invoice RLZ-01-00000082 ↔ N bankregel(s)" tonen, IBAN-stand zichtbaar) → `SCHRIJF c` → rapport → GO Peter → `SCHRIJF d`. Deze run maakt géén nieuwe inbox-opdracht aan: de volgende stap is menselijk (Toewijzing/mapping), niet automatiseerbaar.

## 5. Afronding
- BESLISSINGEN "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)": nieuwe alinea "Plan ná deploy van de lezer-fix 17-09 avond — werkt in productie: lezer-fix ja, SCHRIJF c niet uitgevoerd".
- `docs/regels/vgg-odoo-migratie.md`: blok-12-alinea aangevuld met de productiestand (ja, executies m2hst/gblm7).
- Dit rapport + INDEX-regel; opdracht `2026-09-17-vgg-plan-na-lezer-fix.md` → `opdrachten/gedaan/`. Geen code, geen migratie, geen WAT_IS_NIEUW (geen klantzichtbare functie).

## Gelezen regels
- `docs/regels/vgg-odoo-migratie.md` (53 regels) — volledig gelezen vóór de start (Domeinen-kopregel).
- `docs/regels/werkloop-productie.md` (55 regels) — via CLAUDE.md-blok + geheugen (productie alleen via gedeployde jobs, deploy-check service = jobs, rapport + INDEX + "werkt in productie").
