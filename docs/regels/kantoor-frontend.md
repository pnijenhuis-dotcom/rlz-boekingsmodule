# Regels — Kantoor-frontend: IA, designpass, componenten, changelog

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Tailwind v4 + tokens, designpass v2 (teal = actie, groen = status), instellingenRegistry fail-closed, Gebruikers & toegang-tabel, overflow-sweep, "Wat is nieuw".

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Kantoor-frontend-modernisering** (platform-fundament Tailwind v4 + tokens; IA klant-centrisch, drie lagen, klant-klik
  landt DIRECT op de documentenlijst; Instellingen v3 twee-paneel + `instellingenRegistry.ts` fail-closed; `/gebruikers`
  mét archiveren/blokkeren) — zie BESLISSINGEN "Kantoor-frontend-modernisering", "RLZ-FEEDBACKRONDE 25-08" punt C,
  "INSTELLINGEN V3", "RLZ-FEEDBACKRONDE 26-08", "BEHEER-MINI", "Nazorg controls-review". Bindend blijft: GUARD: élk
  nav-item/élke tab heeft een registry-entry (`instellingenRegistry.test.ts`); schaalregel: nieuwe module = nav-regel
  en/of tab, nooit een tegel; regressie-vangnet `frontend/scripts/overflow_sweep.sh` (geen horizontale pagina-overflow).

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Gebruikers & toegang — tabel-layout met kolomminima en ⋯-menu (blok 2 vervolgrun 10-09 avond; kliktest Peter 10-09; geen migratie):** één bron `gebruikers/gebruikersKolommen.ts` (px-minima per tab, `<colgroup>` + `th` nowrap + tabel-min-width = som, fixed layout; past op 1440 zonder interne scroll, op 1170 scrolt de tabel intern mét sticky acties), Rol · scope en Rechten samengevoegd, Beveiliging-/statuschips op één regel, acties = één primaire knop (Opnieuw mailen / Herstel-link) + ⋯-rijmenu (`GebruikerRijMenu` op `AnkerPopup.rijmenu`), harnas `?breed=1` in de overflow-sweep + `gebruikersKolommen.test.tsx` — zie BESLISSINGEN "GEBRUIKERS & TOEGANG — TABEL-LAYOUT MET KOLOMMINIMA EN ⋯-MENU".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Best-practice-punten D1–D4** — zie BESLISSINGEN "BEST-PRACTICE-PUNTEN D1–D4". Bindend blijft (D1): "Wat is nieuw"
  = hand-gecureerd `frontend/src/changelog/WAT_IS_NIEUW.md` (klantleesbaar, nieuwste bovenaan — **VERPLICHT bijvullen
  bij élke feature-commit**, guard-test op vorm/jargon).

<!-- toegevoegd 18-09-2026, opdracht "BUG-chip-meerwerk-urenstaten-lege-pagina" -->
- **Beoordelen › Urenstaten-tabel (18-09):** tweede afnemer van het Gebruikers & toegang-tabelpatroon — kolomminima uit één
  bron (`meerwerk/beoordelenKolommen.ts` + test), `<colgroup>`/fixed layout/tabel-min-width = som, één primaire knop + ⋯
  (`GebruikerRijMenu` is generiek herbruikbaar), harnas `harness-werkvoorraad.html?beoordelen=1` in `overflow_sweep.sh`;
  een chip die op een pagina landt, leest zijn tellers uit dezelfde bron als de tabs van die pagina (`beoordelenChip.ts`) —
  zie BESLISSINGEN "BEOORDELEN — URENSTATEN EN MEERWERK OP ÉÉN PLEK; UITVOERDER KEURT ALLES IN SCOPE (Peter 18-09)".

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Kantoor-frontend-modernisering (IA klant-centrisch, Instellingen v3, gebruikersbeheer, blokkeren/archiveren, nazorg controls-review) (CLAUDE.md `ed6d176` r. 295–353)

- **Kantoor-frontend-modernisering (designronde Peter 2026-08-15, 4 iteratierondes —
  BESLISSINGEN "Kantoor-frontend-modernisering"):** de kantoor-UI migreert naar het
  platform-fundament (Vastly-generatie: Tailwind v4 + semantische tokens, shadcn-stijl-
  componenten op Radix, thema.ts-dark-mode "keuze wint, anders systeem") mét het bestaande
  RLZ-palet; `mockup/kantoor-modern.html` = de norm voor vormgeving, componenten en IA,
  `mockup/index.html` blijft de bron voor flows/inhoud. **IA-besluit klant-centrisch, drie
  lagen:** klantpagina = STANDEN (documenten per soort, bank per rekening — alleen tellers),
  deelscherm = WERKEN (één soort/rekening, segment-filters), controlescherm = één document
  — **HERZIEN 25-08 (besluit Peter, kliktest): de klant-klik landt DIRECT op de
  documentenlijst (`/?administratie=X`) mét tabs per soort (alleen teller > 0 + "Alle
  documenten") en een klikbare chip-rij met de overige standen; het standen-scherm blijft
  als `sectie=standen` bereikbaar (niets vervalt, alleen de verplichte tussenstop). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt C;**
  Vragen-/Bank-tabbladen vervallen, kantoorbrede dwarsdoorsneden via klikbare KPI-kaarten
  bovenaan de werkvoorraad; oude URL's redirecten. Toon-regel: bakken-/soorten-regels alleen
  bij teller > 0; AI-kosten alleen op Instellingen (Beheerder). **Instellingen v3 (mockup
  `instellingen-v3.html` = norm, akkoord Peter 01-09 — HERZIET D2 25-08 "landing met
  sectiekaarten" én 30-08 "detail-dialoog"): twee-paneel op élke `/instellingen`-route — vaste
  linker settings-nav in drie groepen (Administraties / Platform / Kantoor) mét stand-chips en een
  DETERMINISTISCHE zoeker (registry naam + synoniemen + doel; "accordering arvum" = deep-link naar
  de detailpagina-tab; geen AI), `/instellingen` zonder sectie redirect naar het eerste zichtbare
  item van de rol (Beheerder → administraties, Boekhouding → beveiliging, B+P → materiaal), álle
  oude sectie-URL's redirecten; administratie-detail = PAGINA `/instellingen/administraties/{id}`
  mét tabs (Algemeen · Boeken & AI · Klant-accordering · Doorbelasting (bron/doel) · Uren &
  materiaal · Voorraad (opt-in)) die de bestaande componenten gefilterd hergebruiken — één bron,
  twee ingangen; Crediteuren-dubbelsignalering → Inzicht (`/crediteuren`). Rol×sectie-matrix
  fail-closed in `instellingenRegistry.ts` (`zichtbareNavItems`; B+P ziet als enige
  niet-Beheerder-uitzondering de Materiaalcatalogus, spiegel van backend `require_beheerder_of_bp`);
  GUARD: élk nav-item/élke tab heeft een registry-entry (`instellingenRegistry.test.ts`);
  schaalregel: nieuwe module = nav-regel en/of tab, nooit een tegel. BESLISSINGEN "INSTELLINGEN
  V3".** De globale boeken-kill-switch heet in de UI/CLI "Boeken platformbreed" — aan =
  boeken kan, uit = boeken staat plat (D4, alleen presentatie). Deel 3 (25-08): `/gebruikers`
  = tabs Kantoor/Veldwerkers/Klant-accordeurs mét tellers, zoekveld + paginering (25) per tab,
  `?groep=` in de URL, actiekolom sticky rechts (`td.acties`) en compacte administraties-chip;
  Instellingen › Administraties: IBAN-accordeurs als chips + wijzig-dialoog (één regel per
  administratie).** Sleep-upload blijft op
  werkvoorraad (tenaamstelling) én klantpagina (direct toegewezen). **GEBOUWD + GETEST in 3
  fases (2026-08-16, kliktest Peter open):** fase 1 designsysteem (Tailwind v4 zónder
  preflight, tokens + `ui/thema.ts` + componentenset `ui/basis/`, controls gemigreerd), fase
  2 IA-verbouwing (KPI-dwarsdoorsneden, klantpagina-standen, deelschermen, redirects —
  verificatiepunt accordeur-multi-administratie bewezen met backend-test: wachtrij én
  09:00-herinnering voegen administraties samen), fase 3 Gebruikers & toegang
  (`/auth/gebruikers` + uitnodiging-opnieuw-endpoint, scherm `/gebruikers`) + bulkbediening
  Instellingen. **Gebruiker ARCHIVEREN/dearchiveren (feedbackronde 26-08 punt 1, migratie 0075,
  0052-patroon): status `gearchiveerd` = uit álle default-lijsten (filter "gearchiveerd (N)" per
  tab op /gebruikers), toegang dicht, niets verwijderd; dearchiveren = status van vóór terug; open
  werk = waarschuwing mét aantallen (`GET /auth/gebruikers/{id}/open-werk`), geen blokkade — zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08".** **Gebruiker blokkeren/heractiveren: GEBOUWD + GETEST (2026-08-16, migratie
  0052)** — blokkade bijt per direct op álle paden (sessies/refresh dood, passkeys onbruikbaar
  maar geregistreerd = omkeerbaar), guards server-side (eigen account/systeem-actor/laatste
  actieve Beheerder nooit), heractiveren zet de status van vóór de blokkade terug; audit op
  beide. Zie BESLISSINGEN "BEHEER-MINI". Details per fase: BESLISSINGEN "Kantoor-frontend-modernisering".
  **Nazorg controls-review UITGEVOERD (2026-08-16, bevindingen kliktest Peter):** switch/
  checkbox-inklap (specificiteitsbotsing legacy-CSS vs `.cb`/`.switch`), switch-track-contrast
  (mockup-norm mee bijgewerkt), paneel-clipping ~1170px (tabel-scroll), thema-toggle-race,
  systeem-actor uit gebruikersbeheer (mét server-side guard), dev-stub-apparaat-deduplicatie —
  zie BESLISSINGEN "Nazorg controls-review". Regressie-vangnet: `frontend/scripts/
  overflow_sweep.sh` (alle visuele harnassen × 1440/1170/1024/768 × licht/donker — geen
  horizontale pagina-overflow; vastgoed-sweep-patroon).

### Domeinbeslissingen — Best-practice-punten D1–D4 (CLAUDE.md `ed6d176` r. 620–631)

- **Best-practice-punten D1–D4 (01/02-09, BESLISSINGEN "BEST-PRACTICE-PUNTEN D1–D4"):** (D1) "Wat is
  nieuw" = hand-gecureerd `frontend/src/changelog/WAT_IS_NIEUW.md` (klantleesbaar, nieuwste bovenaan —
  **VERPLICHT bijvullen bij élke feature-commit**, guard-test op vorm/jargon), topbar-knop ✦ mét
  ongelezen-dot per gebruiker (localStorage, geen server-infra); (D2) maandagochtend-digest kantoor
  `app/berichten/digest.py` — weekmail per medewerker mét scope, alleen bij iets te melden, idempotent
  per ISO-week (`platform.kantoor_digest`, migratie 0097), opt-out `gebruiker.digest_opt_out` via
  `GET/PUT /auth/mijn/digest` + switch op Instellingen › Beveiliging, job `rlz-kantoor-digest` ma
  07:30 (CLI/make `kantoor-digest`); (D3) "Toon QR" = de bestaande uitnodigingslink als QR
  (`ui/QrLinkDialog.tsx`, /gebruikers + planning "+ ZZP'er"), geen nieuw auth-pad; (D4) badge-count
  app-icoon = open accorderingen in élke push-payload (APNs `aps.badge`, FCM `notification_count`) +
  reset/actualisatie in de app (`accordeur/appBadge.ts`, plugin `AppSlot.zetBadge`) — zichtbaar vanaf
  de volgende store-build.
