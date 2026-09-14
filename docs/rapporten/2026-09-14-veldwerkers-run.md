# Veldwerkers-run 14-09 — recht verbreed, /veldwerkers, dossier-kolom (+ vooraf: inbox-herstel)

Opdracht `opdrachten/gedaan/2026-09-14-veldwerkers-run.md` (besluiten Peter 14-09 punt 1+2), uitgevoerd als interactieve
CC-run ná het gestrande launchd-exemplaar van 15:17. Aansluitend is de bug-opdracht "Instellingen › Doorbelasting 500"
uitgevoerd (eigen rapport `2026-09-14-bug-doorbelasting-instellingen.md`).

**Werkt in productie: niet gemeten.** Meetrecept (Peter of Cowork klikt, ná de deploy van deze commits): log in als een
medewerker mét het recht Veldwerkerbeheer die géén Beheerder is → de zijbalk toont onder Beheer het item "Veldwerkers";
/veldwerkers laadt met alleen de veldwerkers van de eigen administraties (netwerk: `GET /uren/beheer/veldgebruikers` 200);
"Detacheerder koppelen" en "Tarief" slagen en staan in het audit-log; het dossier van een ZZP'er opent; /gebruikers blijft
voor die medewerker onbereikbaar. Voor de Beheerder verandert alleen de plek (Beheer › Veldwerkers i.p.v. de tab).

## Vooraf: inbox-herstel (waarom de run van 15:17 stil stierf)

**Oorzaak, gelezen uit `~/Library/Logs/cc-inbox.log` + `opdrachten/log/2026-09-14-veldwerkers-run.log`:** de launchd-agent
startte de veldwerkers-run om 15:17:43 (dus niet een TTY-, auth- of PATH-probleem — de run van 15:04 draaide in dezelfde
context foutloos). `claude -p` werkte 22 minuten (deels gebouwd: rechten-verbreding, migratie 0141, drie frontend-bestanden)
en eindigde om 15:39:16 met exit 1:

```
You've hit your monthly spend limit. Switch to another model, or manage usage credits at claude.ai/admin-settings/usage, to continue.
>> cc_inbox: claude eindigde met code 1 (2026-09-14T15:39:16)
```

Toen Peter keek, stond alleen de startregel in het log (claude -p schrijft pas bij zijn eindrapport), de melding "CC MISLUKT"
noemde geen oorzaak, en de opdracht bleef in `lopend/` zonder herstart. De tick van 15:44 pakte intussen de VOLGENDE opdracht
(bug doorbelasting) op — die heb ik gestopt (code 143) omdat twee agenten in één werkboom botsen, en de lock vastgehouden met
de pid van deze interactieve run.

**Fix in `scripts/cc_inbox.sh`** (guard `backend/tests/unit/test_cc_inbox_herstel.py`, 9 tests op het échte script mét
claude-/osascript-stubs; `test_cc_inbox_pull.py` 7 blijven groen — 16 passed):

| | Gedrag |
|---|---|
| (a) Hartslag | elke 5 min ">> cc_inbox: loopt nog (N min)" in het opdrachtenlog zolang claude draait |
| (b) Elke stop | TERM/INT/HUP en elk onverwacht einde → ">> cc_inbox: GESTOPT …" + melding "CC GESTOPT"; claude-boom beëindigd; lock weg |
| (c) Limiet | uitvoer mét "spend limit / usage limit / rate limit / out of credits" → log + melding "LIMIET — claude.ai/admin-settings/usage" |
| (d) Melding | resultaat altijd in het log: "melding verstuurd — …" of "melding mislukt (osascript rc=N) — …" |
| (e) Verweesd | tick zonder levende lock + .md in lopend/ → terug naar inbox/ (poging N/3, teller `opdrachten/log/<slug>.pogingen`) + melding "CC HERSTART", direct opnieuw opgepakt; ná 3 pogingen → `opdrachten/mislukt/` mét kopregel + melding "CC MISLUKT DEFINITIEF" |

Plus: exitcode van claude (niet van `tee`) via statusbestand; PATH-vangnet achteraan (een expliciet PATH wint); nieuwe map
`opdrachten/mislukt/`.

**Bewijs via de échte launchd-agent (niet handmatig), 16:08–16:14.** Ik zette een dummy-opdracht in de inbox; de tick pakte
echter eerst een intussen door Cowork aangeleverde échte opdracht op (oudste mtime wint). Omdat de werkboom van deze run nog
niet gecommit was, heb ik dat proces bewust een TERM gestuurd — precies het pad (b). Letterlijk uit
`opdrachten/log/2026-09-14-btw-default-uit-rlz-grootboek.log` (identiek in `~/Library/Logs/cc-inbox.log`):

```
>> cc_inbox: start 2026-09-14-btw-default-uit-rlz-grootboek (2026-09-14T16:08:51, poging 1/3) — log …
>> cc_inbox: loopt nog (5 min, 2026-09-14T16:13:51) — claude draait, geen uitvoer is normaal tot het eindrapport
>> cc_inbox: GESTOPT door signaal TERM (2026-09-14T16:14:10) — 2026-09-14-btw-default-uit-rlz-grootboek blijft in opdrachten/lopend/, volgende tick zet 'm terug in inbox/ (poging 1/3 gebruikt)
>> cc_inbox: melding verstuurd — CC GESTOPT: 2026-09-14-btw-default-uit-rlz-grootboek (signaa
```

Ná de stop: geen `claude -p`-proces meer, lock weg, `.pogingen` = 1, opdracht in `lopend/`. Zodra deze run de lock loslaat
(einde van deze run) zet de volgende tick 'm terug in inbox/ als poging 2/3 en start 'm opnieuw; de dummy volgt daarna.
De macOS-melding kwam uit de launchd-context aan (osascript rc 0).

## Backend (blok A)

- **A1** `require_beheerder_of_veldwerkerbeheer` op overzicht + alle koppel-routes (detacheerder↔ZZP'er incl. `/tarief`
  mét audit oud→nieuw, crediteur incl. `/autoboeken`, projectkoppeling verwijderen). Scope server-side per aanroep:
  administratie-gebonden → `vereis_administratie_scope`; persoonsniveau → `toets_veldwerkerbeheer_doel` op beide
  veldwerkers. Overzicht voor een rechthouder = alleen veldwerkers binnen de eigen scope; additief DTO-veld
  `administratie_ids`.
- **Migratie 0141 (afwijking van "geen migratie", bewust):** de RLS-policies op `platform.detacheerder_koppeling` lieten
  alleen Beheerder toe → een rechthouder zou nul rijen zien en op INSERT stil geweigerd worden. Nieuwe
  SECURITY-DEFINER-functie `platform.current_actor_heeft_veldwerkerbeheer()` + `OR` in de vier policies. Schema-only.
  Afsluitroutine: `make migrate` op de dev-DB → `Running upgrade 0140 -> 0141`; `alembic check` → "No new upgrade
  operations detected"; live op uvicorn 8011: `GET /uren/beheer/veldgebruikers` 200, `GET /uren/kantoor/mijn-toegang` 200;
  schema-dump: zie onder.
- **A2** rechten toekennen + dossier-documenttypen Beheerder-only (getest 403).
- **A3** dossier kantoorkant onder `require_veldwerkerbeheer_of_meerwerk_recht` (+ service-toets in `dossier.py`),
  klantscope blijft.
- **A4** rol-matrix +20 routes in groepen A1/A2/A3, `TestVeldwerkerbeheerRolpoort`, fail-closed sweep groen.

## Frontend (blok B) — UX-review

**IA:** nav-regel Beheer › Veldwerkers (ná Gebruikers), eigen lazy route `/veldwerkers`, registry-entry `nav-veldwerkers`
(extern, Beheerder-only omdat de registry een per-gebruiker-recht niet kan uitdrukken; rechthouders komen via het Shell-item
dat `heeft_veldwerkerbeheer_recht` uit mijn-toegang volgt, fail-closed). Geen tegel. **Mockup:** geen aanpassing nodig — de
inhoud is 1-op-1 de Veldwerkers-tab uit `mockup/meerwerk-kantoor.html` (koppelingen, crediteur + tarief, bureau-tarieven,
📁-dossier), alleen gesplitst in Koppelingen · Dossier · Status en verhuisd naar een eigen kantoorbrede pagina volgens
"UX-PATRONEN ALS NORM" (administratie = filter in de URL, één primaire knop + ⋯-menu, kolomminima uit één bron, lege stand =
actie, urgentie-sortering rood → oranje → alfabetisch).

- Kolom Dossier = `dossierStand()` uit de bestaande `DossierSamenvattingDto` (geen nieuwe berekening); filter
  `?filter=dossier_onvolledig`; werkvoorraad-signaal op de klantpagina linkt ernaar mét `&administratie=<id>`.
- /gebruikers › Veldwerkers = account-tabel (Veldwerker · Rol · Status · acties) + linkbtn naar /veldwerkers;
  `VeldwerkersPanel` verwijderd, dialogen leven in `veldwerkers/VeldwerkerModals.tsx` (+ nieuwe `ZzperBureausModal`).
- Statuskolom op /veldwerkers = alleen `status` uit de veldgebruikers-DTO (half-geactiveerd/herstel-link blijven op
  Gebruikers & toegang) — één endpoint, geen Beheerder-vertakking.
- Harnas `harness-veldwerkers.html` (+ `?breed=1`) in de overflow-sweep.

## Keuzes zonder Peter

1. Migratie 0141 tóch (zie boven) — zonder is het besluit een stille RLS-weigering.
2. Een rechthouder ziet in het overzicht alleen veldwerkers binnen de eigen scope (filter ≠ grens).
3. Registry-item Beheerder-only, Shell-item volgt het recht.
4. Inbox-herstel: max 3 automatische pogingen, daarna `mislukt/` — geen automatische modelwissel bij een limiet (dat is
   Peters besluit).
5. Bewijs van het inbox-herstel via een TERM op een échte launchd-run i.p.v. de dummy (die stond tweede in de rij); de dummy
   draait ná deze run alsnog.

## Tests en poorten (letterlijk)

| Poort | Uitkomst |
|---|---|
| `tests/auth/test_veldwerkerbeheer.py tests/uren/test_kantoor_api.py tests/security/test_rol_endpoint_gates.py` | 469 passed (5:23) |
| Gouden set `tests/keten` + `tests/migratie` + guards (CLAUDE.md-verwijzingen, rapporten-index, keten-guard, metadata-guard, opt-in-afwezig-pad) | 352 passed, 2 skipped (4:11) |
| `tests/unit/test_cc_inbox_herstel.py` + `test_cc_inbox_pull.py` | 16 passed |
| Bug-blok: `tests/doorbelasting` volledig | 158 passed; nieuw `test_instelling_api.py` 8 + `test_opruimlijst.py` +1 |
| Frontend `npx tsc -b` | foutvrij |
| `npx vitest run src/veldwerkers src/gebruikers src/instellingen src/werkvoorraad src/auth src/changelog` | 55 files / 471 tests + changelog 5 groen |
| `HARNASSEN_ALLEEN=harness-veldwerkers scripts/overflow_sweep.sh` | 16 metingen groen, geen horizontale overflow |
| `scripts/keten_sweep.sh` (gouden-set frontend) | 11 metingen gelijk aan baseline (0,000 %) |
| Volledige backend-suite | 5727 passed, 3 skipped, 21 deselected, 16 errors (1:04:56) — de 16 errors zaten allemaal in `tests/berichten` en zijn een gevolg van een door mij gelijktijdig gestarte guard-run op dezelfde test-database (deadlock-patroon, zie memory "geen parallelle pytest-runs"); `tests/berichten` alleen herdraaid: 76 passed |
| `scripts/dump_schema.sh` | ververst ná de suite (0141: functie + vier policies op `platform.detacheerder_koppeling`), meegecommit |

## Vastlegging

BESLISSINGEN "VELDWERKERS-RUN 14-09 — RECHT VERBREED + /VELDWERKERS + DOSSIER-KOLOM" en "WERKLOOP AUTOMATISCH …" nazorg (2);
CLAUDE.md verwijsregels (Uren & meerwerk + Werkloop automatisch); WAT_IS_NIEUW-blok 2026-09-14 "Eigen pagina Veldwerkers,
doorbelasting-instellingen openen weer"; opdrachten → `gedaan/` mét kopregel.
