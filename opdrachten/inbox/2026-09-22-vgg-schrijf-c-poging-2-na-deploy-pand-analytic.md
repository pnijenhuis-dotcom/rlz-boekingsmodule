Domeinen: vgg-odoo-migratie, werkloop-productie
niet vóór: 2026-09-22 16:00

# VGG — SCHRIJF c poging 2 ná de deploy van de pand-analytic-fix (22-09) → GO-vraag SCHRIJF d

**Context:** rapport `docs/rapporten/2026-09-22-vgg-toewijzing-schoffelstraat-schrijf-c.md` §3–§4, BESLISSINGEN "VGG — BESLISPUNT 1 BESLIST:
TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)" alinea "Uitgevoerd 22-09". Poging 1 (executie `rlz-reconciliatie-zp7xs`)
strandde op stap 3: `action_post` op concept **3370** (het bewijspaar RLZ-01-00000082, draft) → Odoo 500 `invalid literal for int(): 'pand:schoffelstraat-29'`.
Stand company 6: partners 275/276, concepten 3369 (in_invoice Gimple) + 3370 (out_invoice bewijspaar, mét pseudo-sleutel in zijn regel), 0 gepost.
De fix (`odoo_schrijf.PandAnalyticOplosser` + `herstel_regels` + guard) is pas live ná de deploy van de commit van 22-09 middag.
**Klikpunt Peter (open):** IBAN op dagboek BNK1 in Odoo company 6 is leeg → stap 4/5 (statement line + reconcile) worden overgeslagen; zonder IBAN
post SCHRIJF c het bewijspaar wél, maar reconcilieert niet en is de per-pand-sluit-eis (7d) niet toetsbaar.

## Stap 0 — deploy-check
`git fetch origin && git rev-list --count main..origin/main` = 0 (anders `merge --no-ff`); service `rlz-backend` ÉN job `rlz-reconciliatie` op een
image ≥ de commit van 22-09 mét `backend/app/migratie/odoo_schrijf.py::PandAnalyticOplosser` (`gh run list --workflow=deploy.yml`; jobs-image-pad
`spec.template.spec.template.spec.containers[0].image`). Niet aan de voorwaarde → dit bestand terug in `inbox/` mét een nieuwe `niet vóór:`-regel
(+1 uur, max 3×).

## Stap 1 — `plan` (lees-only): `ODOO_BRON_ADMINISTRATIE="Universal Verkoop" scripts/gcp/vgg_blok7_odoo_writes.sh plan`
Verwacht in het stap0-rapport, stap 3: "ZOU aanmaken: RLZ-01-00000082 … → ZOU POSTEN (bewijspaar)" gevolgd door
"analytic pand:schoffelstraat-29 → ZOU aanmaken (Schoffelstraat 29, plan N)" (of "→ bestaand N (hergebruik)" als de analytic intussen bestaat);
migratie-dry-run fase A teller `pand-analytics` ≥ 1. Ontbreekt de analytic-regel → de deploy draagt de fix niet (stap 0 herhalen), STOP.
"STOP — geen analytic_plan_id in de doelkoppeling" → `odoo-koppeling-migratiedoel --dry-run` lezen, rapport, STOP (geen mapping verzinnen).

## Stap 2 — SCHRIJF c: `scripts/gcp/vgg_blok7_odoo_writes.sh "SCHRIJF c"` (kill-switch als executie-override)
Verwacht: stap 0 partners 275/276 hergebruikt; stap 1 concept 3369 bestaand; stap 3 "concept 3370 … · 1 regel(s) analytic hersteld (bestaand
concept droeg de pseudo-sleutel) → GEPOST als F/2026/03/…"; melding "analytic pand:schoffelstraat-29 → <id> (aangemaakt)"; stap 4/5 overgeslagen
mét het IBAN-klikpunt (tenzij Peter de IBAN intussen zette — dan statement line + reconcile route i/ii/iii + stap 6 terugweg). Exit ≠ 0 = de
uitkomst staat in het rapport (het script toont sinds 22-09 het log altijd): letterlijk overnemen, STOP, niets herstellen in Odoo.
Audit-toets op de replica (`db_lezen.sh … --administratie cc07e461-3288-4065-85ed-9005495a22ea`): `odoo_migratie_analytic_aangemaakt` 1,
`odoo_migratie_regel_analytic_hersteld` ≥ 1 (oud = pseudo-sleutel), `odoo_migratie_move_gepost` 1.

## Stap 3 — terug-lezen + achtste meting
`gh workflow run nameting -f onderdeel=c` (replay: saldibalans 803100 Opbrengst verkoop panden = € 400.000,00 aan de Odoo-kant, per pand
Schoffelstraat 29 verkoop € 400.000,00); bot-bestand `verkenning/nameting-vgg-replay-<dd-mm>.txt`.

## Stap 4 — rapport `docs/rapporten/<datum>-vgg-schrijf-c-poging-2.md` + INDEX + "## Gelezen regels"; "werkt in productie: ja/nee" letterlijk;
**dit rapport = de GO-vraag aan Peter vóór `SCHRIJF d`**, mét de per-pand-sluit-eis (7d) letterlijk en het IBAN-klikpunt als voorwaarde voor
de reconcile-kant; alinea "Poging 2 <datum>" onder de BESLISSINGEN-sectie van 21-09 en in `docs/regels/vgg-odoo-migratie.md`.
