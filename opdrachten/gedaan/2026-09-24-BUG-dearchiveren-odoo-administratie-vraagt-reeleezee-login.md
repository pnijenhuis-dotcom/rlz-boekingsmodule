uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-bundelrun-zeven-punten.md

# BUG + FIX 24-09 — Dearchiveren van een Odoo-administratie eist een Reeleezee-webservice-login (onmogelijk) → Odoo-company blijft geclaimd

Opdracht Peter 24-09 (Cowork-Jarvis, verbatim: "Ik heb per abuis 2x dezelfde Odoo administratie aangemaakt voor dezelfde BV … beide
koppeling gearchiveerd in onze module … nu wil ik opnieuw koppelen maar dat gaat niet?"). Handmatige CC-sessie of inbox-run.

LEESPLICHT vóór je begint: docs/regels/administraties-instellingen.md, docs/regels/kantoor-frontend.md; app/odoo/models.py (docstring
`uq_odoo_koppeling_host_company` — "dearchiveren is de weg, nooit een tweede rij"), app/odoo/service.py (`company_claims`,
`CompanyClaim.reden`), app/beheer/service.py::dearchiveer_administratie, app/beheer/onboarding.py::probe_nieuwe_login,
frontend/src/instellingen/AdministratiesV2.tsx (Dearchiveren-dialoog).

## Feiten (gemeten 24-09 11:3x door Cowork, productie, lees-only via kantoor-web als Beheerder + Odoo-UI)
- Odoo `universal-steigers.odoo.com`: company **13** "Recreatief Vastgoed Nederland B.V." (actief, aangemaakt 24-09 09:18) en company
  **11** "Recreatief Vastgoed Nederland BV." (gearchiveerd, aangemaakt 18-09). Beide **0 `account.move`** (search_count met
  active_test=false) — niets geboekt, geen samenvoegvraag.
- Module: twee gearchiveerde administraties (24-09 door Peter): `8ea9d28b-e743-4566-96d7-bb7d81531368` "Recreatief Vastgoed Nederland
  B.V." → koppeling company **13**, probe groen 24-09 11:24, eerste sync volledig (grootboek 356 · btw 17 · relaties 30 · projecten 3),
  geen rekening-mapping (nieuwe Odoo-administratie zonder RLZ-verleden); `59bf1f7f-7460-4b04-bb27-b131691ccdf6` "Recreatief Vastgoed
  Nederland BV." → naar verwachting company 11 (niet geopend; verifiëren).
- Opnieuw koppelen op company 13 wordt terecht geweigerd door `company_claims` (gearchiveerde administratie houdt haar claim; hint
  "dearchiveer die administratie"). **Maar dearchiveren kan niet:** `dearchiveer_administratie` en de dialoog eisen een Reeleezee-
  webservice-login + `probe_nieuwe_login(rlz_admin_id=…)`; voor een Odoo-administratie is `rlz_admin_id` het sentinel `odoo:<host>:<company>`
  en bestaat er geen webservice-login → de enige aangewezen weg is dood. De frontend toont voor Odoo-rijen wél "Dearchiveren…" met de
  Reeleezee-tekst ("nieuwe webservice-login van Reeleezee; de rechten-probe (10 leesroutes)…").

## Oorzaak
Archiveren/dearchiveren (v2 30-08) dateert van vóór de Odoo-backend (blok E 03-09) en is niet backend-bewust gemaakt: archiveren trekt
de RLZ-credential in (voor Odoo: niets), dearchiveren eist een RLZ-credential. Besluit 0016 (alle pakketverschillen in de adapter, geen
vertakking in het domein) is hier geschonden in de andere richting: het domein kent maar één backend.

## Fix (kleinste correcte)
1. `dearchiveer_administratie`: bepaal de backend via de koppeling (0016-registry), niet via een `if odoo` in het domein — voeg aan de
   backend-port een operatie `heractiveer_probe(administratie_id)` toe: Reeleezee-adapter = huidige gedrag (nieuwe login + probe);
   Odoo-adapter = bestaande `OdooKoppeling` + versleutelde API-sleutel hergebruiken, **Odoo-probe opnieuw draaien** (rechten, company_id
   terug-gelezen == koppeling.company_id, dagboeken), groen → `actief=True`, `gearchiveerd_op/door=None`, audit_event
   `administratie.dearchiveren` mét probe-rapport; rood → 422 mét rapport, niets gewijzigd. Geen wachtwoordvelden nodig.
2. Router: `WebserviceGegevensDto` optioneel maken (Reeleezee vereist 'm, Odoo weigert 'm met 422 "niet van toepassing").
3. Frontend Dearchiveren-dialoog: op `boekhoud_backend === 'odoo'` geen loginvelden, tekst "Odoo-koppeling wordt opnieuw geprobed;
   company <id> moet ongewijzigd terugkomen", knop "Dearchiveren".
4. Archiveren van een Odoo-administratie: leg vast wat er met de API-sleutel gebeurt (blijft versleuteld staan — nodig voor 1; of
   ingetrokken zoals bij RLZ → dan bij dearchiveren sleutel opnieuw vragen). Kies en documenteer in administraties-instellingen.md.
5. Tests: dearchiveren Odoo groen (fixture-probe), rood bij company-mismatch, Reeleezee-pad onveranderd; frontend-test dialoogvariant.
6. Guard tegen de aanleiding: bij "Administratie toevoegen → Odoo" toont de wizard al "al gekoppeld (‹naam›)" grijs (punt 2c 14-09) —
   controleer of dat ook voor een gearchiveerde claim de rij grijs maakt mét "gearchiveerd — dearchiveer" i.p.v. een klikbare rij die
   pas bij opslaan 422 geeft.

## Na de deploy (Peter/Cowork)
Dearchiveer `8ea9d28b…` (company 13) via de nieuwe dialoog; `59bf1f7f…` (company 11, in Odoo gearchiveerd) blijft gearchiveerd.
Nameting: administratie actief, sync-alles groen, `company_claims` toont 13 → 8ea9d28b en 11 → 59bf1f7f (gearchiveerd).

Rapport ≤ 15 regels in docs/rapporten/, BESLISSINGEN-regel, regels-doc bijgewerkt.
