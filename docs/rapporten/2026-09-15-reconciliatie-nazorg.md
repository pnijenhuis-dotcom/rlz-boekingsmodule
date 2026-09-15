# Reconciliatie-nazorg 15-09 — afronding ≤ 0,05, cent-fix aan de bron, korte referenties, systeemmail alleen bij LET-OP

**In gewone taal:** De dagelijkse reconciliatie meldde bij Kempen Facilities elke ochtend verschillen van 2–3 cent op geboekte
Lusso- en Booking-Experts-facturen (Reeleezee rekent btw per regel, de leverancier per totaal), plus een "mogelijk dubbel" op Abbegaa
door de referentie "01". Peter leest de technische systeemmail niet. Het systeem beslist nu zelf: centverschillen tot 5 cent worden
automatisch geaccepteerd (mét audit en teller) én bij het boeken meteen aan de bron gecorrigeerd zodat ze niet meer ontstaan; referenties
korter dan drie tekens tellen niet meer mee in de dubbel-toets; de systeemmail gaat alleen nog bij een LET-OP, systeemfout of omgevallen
blok en staat voor deze installatie standaard uit. De actiemail voor het kantoor is ongewijzigd.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; meetrecept hieronder).

## Wat is gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1 | Bedragverschil ≤ € 0,05 op een geboekt document = automatische acceptatie door het systeem (`reconciliatie_auto_geaccepteerd`, reden "afronding ≤ 0,05", systeem-actor), dagteller "N automatisch geaccepteerd" in het systeemrapport; groter blijft een actie-bevinding; ingetrokken door een Beheerder = wint blijvend | `app/documenten/reconciliatie.py::afrondingsverschil`, `app/reconciliatie/service.py::auto_accepteer`, `app/cli.py::_auto_accepteer_afrondingen` |
| 2 | Cent-fix aan de bron: verschil van 1–5 cent tussen Σ regels en factuurtotaal gaat in de laatste btw-dragende regel van wat naar RLZ gaat (boeking én tegenboeking); module-regels blijven ongewijzigd; hergebruik `regelsom.py` (Huvanco-patroon 04-09) | `app/documenten/regelsom.py::corrigeer_btw_centen`, `app/backends/rlz_inkoop.py::btw_per_regel_sluitend` |
| 3 | Genormaliseerde referentie < 3 tekens = placeholder → uitgesloten van `rlz_dubbel` mét teller | `app/reconciliatie/rlz_dubbel.py::MIN_REFERENTIE_LENGTE` |
| 4 + 6 | Systeemmail alleen bij LET-OP / systeemfout / blok-fout (`systeemmail_nodig`); code-default ontvangerslijst leeg → kanaalstatus `uitgeschakeld` (één logregel, teller `samenvatting.mail.systeem_uitgeschakeld`, frontend-label "uit (geen ontvangers)"); `deploy-mislukt` valt terug op het bewakingskanaal | `app/reconciliatie/run.py`, `app/config.py`, `app/cli.py::_deploy_mislukt`, `frontend/src/reconciliatie/reconciliatieApi.ts` |

## Tests

- Nieuw: `tests/reconciliatie/test_auto_acceptatie_afronding.py` (17), `tests/documenten/test_rlz_lines_centen.py` (4),
  `tests/documenten/test_regelsom.py::TestCorrigeerBtwCenten` (7), gouden-set-casus x `tests/keten/test_x_btw_centen_sluitend.py`,
  `tests/unit/test_cli_deploy_mislukt.py` (+2), `test_actiemail_guard.py::TestTweeKanalen` (drempel, uitgeschakeld, mailfout).
- Aangepast: `test_rlz_dubbel.py` (fixture-referentie "42" → "4242" omdat twee tekens nu placeholder zijn; parametrize "001" → "100":
  de grens geldt op de genormaliseerde vorm zonder leidende nullen), `test_run.py` (beheer-ontvanger expliciet gezet).
- Gedraaid: tests/reconciliatie + documenten (regelsom, rlz-lines, herboeken, reconciliatie-backend, betaalstatus) + projectverdeling +
  keten x + export-deterministisch + guards (keten, rapporten-index, CLAUDE.md-verwijzingen, vaste testconfig, opt-in afwezig-pad):
  zie de regel "Testresultaat" onderaan. Frontend `src/reconciliatie` 35 groen; `tsc -b` groen.

## Systeemmail uit voor Peter — instelling, geen job-stap

De code-default van `reconciliatie_beheer_ontvangers` is leeg. `deploy.yml` zet `RECONCILIATIE_BEHEER_ONTVANGERS` nergens en de
`--set-env-vars` in de job-lus vervangt de volledige env van elke job, dus **de eerstvolgende deploy zet de systeemmail uit**; een
losse job-update is niet nodig en volgens de regel van 08-09 ook niet toegestaan. Controle ná deploy (lees-only):

```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --project rlz-boekhouding --format=yaml | grep -c RECONCILIATIE_BEHEER_ONTVANGERS
```

Verwacht `0`. Weer aan: de env-var `RECONCILIATIE_BEHEER_ONTVANGERS=<adres,adres>` op de job `rlz-reconciliatie` in `deploy.yml`.

## Meetrecept (nameting-reconciliatie van de eerstvolgende ochtend ná deploy)

1. `verkenning/nameting-reconciliatie-<datum>.txt`: Kempen Facilities `bedrag_wijkt_af` ≤ 0,05 → 0 open; regel
   "N automatisch geaccepteerd (afronding ≤ 0,05)" op het documenten-blok; Booking Experts 20260205347 Δ 0,97 blijft open.
2. `rlz_dubbel`: Abbegaa "01" niet meer als cluster; placeholder-teller +1.
3. /reconciliatie, laatste run: mailstatus "… · systeemmail uit (geen ontvangers)"; geen "[systeem]"-mail in Peters postvak.
4. Eerste nieuwe Lusso-/Booking-Experts-boeking ná deploy: RLZ-documenttotaal = factuurtotaal cent-exact (geen nieuwe afwijking de ochtend erna).

## Beslispunt (default gekozen)

- Grens van drie tekens sluit óók echte korte volgnummers ("42") uit van de dubbel-toets. Default: aanvaard (zeldzaam; bedrag + datum
  blijven getoetst). Staat ook in `docs/rapporten/2026-09-15-beslispunten-peter.md`.

## Kanttekening

De inbox-run van 15-09 ochtend had dit werk al grotendeels in de werkboom staan en strandde drie keer op een DNS-storing; het is in deze
run beoordeeld, aangevuld (RLS-scope in de audit-test, fixtures, regelbreedte, docs) en gecommit. `opdrachten/mislukt/…reconciliatie-nazorg.md`
en de `.pogingen`-bestanden zijn verwijderd.

Testresultaat: backend 389 groen (tests/reconciliatie + regelsom + rlz-lines + keten x + guards), eerdere brede run 495 groen ná de fixes; frontend src/changelog + src/reconciliatie 40 groen; tsc -b groen.
