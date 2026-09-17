> uitgevoerd 2026-09-17 (leveranciersroute vervangt de administratieroute: datamodel 0156, routebepaling op identiteit, herberekening, routes-CRUD, Beheerder-blok LeverancierRoutes; werkt in productie: niet gemeten), rapport: docs/rapporten/2026-09-17-accordering-laag-per-leverancier.md

# OPDRACHT 17-09 — Klant-accordering: accorderingslaag beperkt tot één of meer LEVERANCIERS (vraag Peter 17-09: "kan 1 accordeur facturen van 1 specifieke leverancier zien, de rest niet?")

**Vraag Peter 17-09.** Antwoord Cowork: nog niet gebouwd — een `AccorderingLaag` kent alleen `bedrag_drempel` en optioneel `afdeling_id`
(migratie 0084). Doel: een laag met voorwaarde "alleen voor leverancier(s) X, Y" → de accordeur(s) van die laag krijgen uitsluitend
facturen van die crediteur-identiteit(en) in hun wachtrij en zien de rest niet (server-side; app + PWA volgen de wachtrij).

Pre-feature-ritueel: BESLISSINGEN "Klant-accorderingsflow — GEBOUWD + GETEST", "ACCORDERINGSRONDE HERBEREKENEN I.P.V. VERVALLEN",
"BOUWRUN 28-08 AVOND" blok A (afdelingen), "KLANT-ACCORDEURS — SCOPE VANUIT DE ACCORDEUR", "CREDITEUREN-DUBBELEN SCHAALBAAR"
(crediteur-identiteit over records heen via `crediteuren/voorkeur.py`), "INTERCOMPANY SLAAT KLANT-ACCORDERING OVER";
`app/accordering/models.py`, `service.py` (routebepaling + `wachtrij_voor_accordeur` set-based), `herberekening.py`; frontend
Instellingen › Administraties › ‹BV› › Klant-accordering (laag-dialoog). UX-review verplicht (schermimpact): één extra veld in de
bestaande laag-dialoog, geen nieuw scherm.

> **Verduidelijking Peter 17-09 (bindend):** "1 losse accordeur aanmaken die alleen de aangevinkte leveranciers ziet — dus NIET langs
> de andere accordeurs." Semantiek = **leveranciersroute VERVANGT de administratieroute** voor de aangevinkte leveranciers (zelfde
> patroon als de afdelingsroute, migratie 0084): facturen van leverancier X gaan uitsluitend door de lagen van de X-route; de gewone
> accordeurs zien ze niet; alle andere facturen volgen de gewone route zonder de X-accordeur. Binnen de X-route zijn meerdere lagen
> mét bedragdrempel mogelijk (bv. > € 5.000 óók de directeur). Een leverancier kan in maar één route zitten (unieke index; 409 mét
> reden). Voorrang bij samenloop: afdelingsroute > leveranciersroute > administratieroute — dat is een beslispunt (default zo), noteer.

## Blok A — Datamodel + route (leveranciersroute, vervangend)
- `accordering_laag_leverancier` (laag_id, vendor_id, herkomst, audit; migratie) — meerdere leveranciers per laag; leeg = laag geldt
  voor alles (huidig gedrag). Matching op crediteur-IDENTITEIT (alle crediteurrecords van dezelfde KvK/btw via `voorkeur.py`), niet op
  één record.
- Routebepaling: een laag mét leveranciersfilter telt alleen voor documenten van die leverancier; documenten van andere leveranciers
  slaan de laag over (geen "wacht op laag die nooit komt" — KP7 p6). Combineerbaar met bedragdrempel en afdeling (én-voorwaarden).
- Wachtrij: `wachtrij_voor_accordeur` filtert set-based op de lagen waarin de accordeur zit; RLS ongewijzigd (scope = administratie),
  de zichtbaarheidsbeperking is de laag, server-side afgedwongen in élke accordeur-route (wachtrij, detail, PDF, besluit → 404/403
  buiten de eigen lagen). Guard in `tests/security/test_rol_endpoint_gates.py`-stijl: accordeur buiten de leverancierslaag ziet niets.
- Configuratiewijziging → bestaande herberekening (blok 2 bundel 09-09) verwerkt ook het leveranciersfilter.

## Blok B — UI
- Laag-dialoog: veld "Alleen voor leveranciers" (crediteur-combobox, meervoudig, chips; leeg = alle), samenvatting in de lagenlijst
  ("laag 2 · > € 5.000 · alleen Firma X"). Accordeur-app: geen wijziging nodig (wachtrij is al de bron); wel de lege stand "Geen facturen
  voor jou" als de laag leeg is.

## Blok C — Casus
- Peter noemt (nog) geen klant/leverancier; gouden-set-casus synthetisch: administratie mét laag A (alles, drempel € 1.000) + laag B
  (alleen leverancier Q, accordeur Sophia) → factuur Q € 2.500 gaat door A én B, factuur R € 2.500 alleen A; Sophia ziet alleen Q.

## Afronding
Migratie-afsluitroutine; WAT_IS_NIEUW ("Een accordeur kan nu alleen de facturen van bepaalde leveranciers krijgen"); BESLISSINGEN
"KLANT-ACCORDERING — LAAG PER LEVERANCIER (Peter 17-09)"; CLAUDE.md verwijsregel onder Klant-autorisatie; rapport + INDEX; beslispunt:
leverancierslaag ook voor omzet-/verkoopdocumenten? default: alleen inkoopfacturen.
