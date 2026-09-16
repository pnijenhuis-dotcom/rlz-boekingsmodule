# Slotrapport inbox rij 3 (16-09 avond) — vier opdrachten afgewerkt

**Run:** interactieve Claude Code-sessie 16-09 20:36–22:00, parallel aan de cc-inbox-run van opdracht 2 (zelfde werkboom).
**Werkt in productie:** overal **niet gemeten** — de code staat vóór de deploy; de gcloud-sessie was verlopen (blok C van
opdracht 3 kon daarom ook lees-only niet meten). Meetrecepten per rapport; de VGG-vierde-meting staat als vervolg in de inbox.

## Stand bij de start (vastgesteld, niet aangenomen)
- De vorige cc-inbox-run (`2026-09-16-verplichting-projectveld-combobox`, 16:52–20:19) eindigde **zonder commit**: het werk stond
  ongecommit in de werkboom, de sweeps liepen nog. De cc-inbox-run van opdracht 2 (gestart 20:24, pid 34827) heeft dat werk om
  20:43 als `57ca852` gecommit ná een verse `tsc -b`; de sweeps stonden in het rapport als "lopen in de vervolgrun".
- Twee Claude-processen in dezelfde werkboom en op dezelfde `boekhouding_test`: losse pytest-runs gaven fantoomfouten
  (deadlock, "schema platform does not exist", "Onbekende gebruiker"). De herhaalde runs ná het einde van de andere pytest zijn de
  maatstaf (hieronder). Gedeelde docs (BESLISSINGEN, CLAUDE.md, INDEX, beslispunten, WAT_IS_NIEUW) zijn per commit alleen mét de
  eigen hunks gestaged (index-versie = HEAD + eigen blokken, geverifieerd op andermans markers).

## Per opdracht

| # | Opdracht | Uitkomst | Commits | Rapport |
|---|---|---|---|---|
| 1 | Capture besluiten Peter (avond) — docs-only | Steigermateriaal 5 jr (ONTWERP §3 termijnentabel + §8, registerrij), "Afgehandeld namens" bevestigd, Sunshine Island = eigen BV gemarkeerd | `f3dee5c` | `2026-09-16-besluiten-capture-avond.md` |
| 2 | Omzet store → administratie + Van Boxtel + dagelijkse bevinding | **Uitgevoerd door de parallelle cc-inbox-run** (niet door deze sessie — twee agenten op dezelfde bestanden was onverantwoord); gecommit als `c1df300` (migratie 0151, opdracht → gedaan) | `c1df300` (cc-inbox) | `2026-09-16-omzet-store-routering.md` (van die run) |
| 3 | VGG run 2 blok 9 — SCHRIJF b 1001-model + vierde meting | Blok A gebouwd (`app/migratie/model_1001.py`, restcategorieën, rapportsectie), blok B bewijspaar RLZ-01-00000082 als recept, blok C **niet gemeten** (gcloud verlopen + code vóór deploy) → `opdrachten/inbox/2026-09-17-vgg-vierde-meting-na-deploy.md` | `94a2887`, `ea024aa` | `2026-09-16-vgg-schrijf-b.md` |
| 4 | Accordeur-uitnodiging web vs app (toegevoegd tijdens de run) | Blok A keuzescherm + web-keuze, blok B zelfservice tweede toestel (`POST /auth/app/toestel-koppeling`, 15 min, max 3, geen migratie), blok C mail in volgorde mét store-versiepoort + legacy-hint, blok D TESTFLIGHT §0f klikpunt "1.1 indienen" | `12ced32`, `b1a88e3` | `2026-09-16-accordeur-uitnodiging-web-vs-app.md` |
| nazorg | `SWEEPS_PLACEHOLDER` in het verplichting-rapport | ingevuld: veldwerkers 16/16 + keten 11/11 groen; volledige overflow-run afgebroken op 77/168 (2 ❓ Chrome-timeout gebruikers-harnas) | slotcommit | `2026-09-16-verplichting-projectveld.md` |

## Testbeeld (herhaalde runs ná het einde van de parallelle pytest)
- Backend opdracht 3: `tests/migratie` + docs-guards **272 groen** (`test_model_1001.py` 13 nieuw; `test_blok7d` STAP-0-fixture mét
  bankmutaties; `test_rekening_mapping` tekst).
- Backend opdracht 4: `tests/auth` (activatie, toestel-koppeling, atomair, pincode, cadans) + `tests/berichten` + rol-gate-sweep +
  vaste testconfig **561 groen, 2 rood → gefixt** (TeVeelToestellen → 409 in `/auth/app/activeren`; generieke-login-test op de
  hint aangepast) → herhaald 48 groen op de geraakte bestanden.
- Docs-guards (`test_claude_md_beslissingen_verwijzingen`, `test_rapporten_index`) groen ná élke docs-commit; changelog-vormtest
  groen.
- Frontend: `tsc -b` groen (pre-commit-hook, twee keer); vitest `src/accordeur` + `src/auth` **245 groen** (1 rood → aangepast:
  universal-link-test klikt nu door het keuzescherm).
- Ruff schoon op alle eigen bestanden (pre-existente drift in `service.py`/`config.py`/`replay.py` bewust niet meegeformatteerd).
- Sweeps (nazorg verplichting): overflow-sweep: volledige run in deze sessie (20:37–21:50) afgebroken op 77 van 168 metingen omdat het gebruikers-harnas ~5 min per meting kostte — 75 ✅ (harness, harness?project, werkvoorraad ×4 varianten, gebruikers, gebruikers?breed=1 en ?breed=1&groep=veldwerkers volledig, groep=accordeurs deels) en 2 ❓ op de bekende Chrome-timeout (harness-gebruikers ?breed=1 donker 1440 en ?breed=1&groep=accordeurs donker 1440 — blok 4b 11-09, geen overflow-melding); daarna gericht `HARNASSEN_ALLEEN=harness-veldwerkers` 16/16 ✅; het instellingen-harnas (56 metingen) is door de parallelle cc-inbox-run op dezelfde werkboomstand groen gedraaid (commit c1df300). Keten-sweep: 11/11 ✅ (0 nieuwe baselines) in deze sessie ná de verversing van zes baselines door die run.

## Beslispunten voor Peter (nieuw in deze rij)
- Opdracht 13 (VGG blok 9): meerduidig/geen-kandidaat op de tussenrekening; bewijs 1 zonder datumeis; één outstanding-rekening in/uit;
  status ongewijzigd; restcategorieën; bewijspaar zonder pand-code; meting als vervolg.
- Opdracht 14 (uitnodiging): zelfservice zonder migratie; N = 3; één hint-tekst (geen enumeratie); geen code op het web-scherm;
  store-versie als setting; mail-app-knop i.p.v. app-switch; lokale codeverificatie.
- Besluiten van 16-09 avond zijn vastgelegd (opdracht 1); Sunshine Island is door de parallelle run gebouwd.

## Klikpunten Peter (checklist)
1. **App Store 1.1 indienen** (TESTFLIGHT §0f, eerste klikpunt) → daarna `STORE_APP_VERSIE_IOS=1.1` in deploy.yml (+ envset-guard).
2. **gcloud opnieuw inloggen** zodat de VGG-vierde-meting (inbox `2026-09-17-vgg-vierde-meting-na-deploy.md`) kan draaien.
3. VGG vóór SCHRIJF c: outstanding-payments-rekening op BNK1, IBAN BNK1, drie RLZ-opruimpunten.
4. Sunshine Island als administratie (wizard) — zie het rapport van de parallelle run.

## Meetrecepten ná deploy
Zie de vier rapporten; kort: deploy-check service én jobs → (3) `vgg_blok7_nameting.sh c` → `-cc`-bestand, oordeel drie standen;
(4) testuitnodiging op laptop → stop-scherm + webkeuze, niets verbruikt; QR op telefoon → app; Toegang › "Telefoon/app koppelen" →
tweede toestel zonder intrekking; mail genummerd zonder App Store-link; app 1.0 login → update-hint.

## Inbox-stand bij afronding
- `opdrachten/inbox/2026-09-17-vgg-vierde-meting-na-deploy.md` (vervolg van opdracht 3, door deze sessie geplaatst).
- Nieuw binnengekomen tijdens de run, niet in deze rij en niet aangeraakt: `2026-09-16-native-app-live-updates-ota.md`,
  `2026-09-16-ponto-betalen-stap0-en-ontwerp.md` — de cc-inbox pakt ze op ná deze sessie.
