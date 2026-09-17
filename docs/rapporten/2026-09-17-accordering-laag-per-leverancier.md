# Rapport 17-09 (inbox-run) — Klant-accordering: accorderingsroute per LEVERANCIER (leveranciersroute vervangt de administratieroute)

Opdracht: `opdrachten/gedaan/2026-09-17-accordering-laag-per-leverancier.md`. Migratie 0156 (afsluitroutine gedaan); geen RLZ-/Odoo-writes.
**Werkt in productie: niet gemeten** — meetrecept: ná deploy maakt Peter op Instellingen › Administraties › ‹BV› › Klant-accordering een
leveranciersroute; de accordeur van die route ziet in de app uitsluitend facturen van die leverancier, de gewone accordeurs zien die niet.

## Antwoord op de vraag
Ja: een Beheerder maakt een **leveranciersroute** (naam, aangevinkte leveranciers, één of meer lagen mét bedragdrempel). Facturen van die
leveranciers gaan uitsluitend door die route; alle andere facturen volgen de gewone route zonder deze accordeur. Voorrang:
afdelingsroute > leveranciersroute > administratieroute (beslispunt, default zo). Eén leverancier in maar één route (409 mét de naam
van de andere route). Matching op crediteur-identiteit (een dubbel-record van dezelfde leverancier volgt dezelfde route).

## Blok A — datamodel + route (`app/accordering/`, migratie 0156)
Tabellen `accordering_leverancier_route` + `accordering_leverancier_route_vendor` (partiële unieke index administratie × vendor waar
actief) + `accordering_laag.leverancier_route_id`; RLS per administratie, GRANT zonder DELETE. `leverancier_route_voor_vendor`
(identiteit via `crediteuren/voorkeur.py`), routebepaling in `bied_ter_accordering_aan` (ronde draagt `leverancier_route_id/_naam`),
route zonder lagen = zichtbare fout, herberekening via `_ronde_in_filter` (afdeling + route + leverancier): administratieroute-wijziging
raakt route-rondes niet, route opslaan herberekent route-rondes + rondes van nieuw aangevinkte leveranciers, verwijderen/deactiveren →
terug naar de administratieroute; audit oud→nieuw. Routes GET/POST/PUT/DELETE `…/accordering/leverancier-routes` (Beheerder wijzigt,
kantoor leest; fail-closed sweep groen). Wachtrij en besluit blijven op de stappen → server-side scherp zonder extra code.

## Blok B — UI
`frontend/src/instellingen/LeverancierRoutes.tsx` in de bestaande Klant-accordering-kaart: lijst mét samenvatting ("laag 1 Sophia →
laag 2 D. Directeur · > € 5.000,00 · alleen Firma Q B.V."), lege stand = "+ Leveranciersroute", inline editor (naam, leveranciers als chips,
lagen zoals de administratieroute), rondes-telling na opslaan, "Route uitzetten" mét bevestiging, 409-tekst letterlijk; niet-Beheerder
alleen lezen. Accordeur-app ongewijzigd.

## Blok C — casus (synthetisch)
`tests/accordering/test_leverancier_route.py`: route A (accordeur_1, > € 100) + route Q [Sophia; directeur > € 5.000] → factuur Q € 2.500 =
alleen Sophia, factuur R € 2.500 = alleen A, wachtrijen scherp, Sophia op R = fout, Q € 7.500 = Sophia + directeur; identiteit + 409;
herberekening toevoegen/verwijderen/deactiveren; route zonder lagen; routes-CRUD + gates. 5 groen; accordering-suite + gates + keten-casus p
607 groen; frontend 3 + 261 groen, `tsc -b` groen.

## Migratie 0156 (afsluitroutine)
`alembic upgrade head` dev-DB: `Running upgrade 0155 -> 0156` · `alembic check` schoon · live `GET …/accordering/leverancier-routes` 200
op uvicorn 8012 · dump ververst (head 0156).

## Klikpunten Peter
Geen (feature; Peter noemt nog geen klant/leverancier — configuratie via de UI ná deploy).

## Beslispunten (default — `2026-09-17-beslispunten-peter.md` opdracht 7)
1. Voorrang afdelingsroute > leveranciersroute > administratieroute.
2. Alleen inkoopfacturen én verplichtingen (documenten mét crediteur) volgen een leveranciersroute; omzet-/verkoopdocumenten niet.
3. Casus synthetisch in de accordering-suite (gouden set = échte documenten; er is geen écht document met deze configuratie).
4. Route-vendor-rijen append-only (deactiveren); deactiveren van een route zonder administratieroute laat rondes vervallen mét reden.

## Meetrecept
Ná deploy: route aanmaken (UI) → factuur van die leverancier ter accordering → app van de route-accordeur toont 'm, app van de gewone
accordeur niet; `GET …/leverancier-routes` toont de samenvatting; audit `accordering_leveranciersroute_gewijzigd`.
