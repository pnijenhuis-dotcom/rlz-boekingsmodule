uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-planning-v3-dag-eerst.md

Domeinen: uren-planning-veldwerkers, kantoor-frontend, werkloop-productie

# OPDRACHT 18-09 — BOUW Planning personeel v3 "dag-eerst" (mockup `mockup/planning-v3-dag-eerst.html` AKKOORD Peter 18-09)

**Status:** mockup AKKOORD Peter 18-09 ("ziet er goed uit, geef de opdracht voor alles") → dit is de BOUWopdracht. De mockup is de
bouwnorm, incl. de ontwerpnotities ①–⑨ op de tab "Notities" en de twee beslispunten (kaart zonder ploeg = JA, grijs "gereserveerd";
vulhandvat over de weekgrens = NEE, per week). `mockup/planning-steigerbouw.html` (22-08) wordt historie: kop aanpassen "VERVANGEN door
planning-v3-dag-eerst.html (18-09)". Kop van de v3-mockup: "TER AKKOORD" → "AKKOORD Peter 18-09 · BOUWNORM".

**Peter 18-09 (letterlijk, op screenshot van de huidige Personeel-tab):**
1. "Projecten mag hier weg [linkerkolom], dat moet hetzelfde zijn als transport: dat wij projecten kunnen slepen naar de verschillende
   dagen in de week."
2. "Als er een project op maandag wordt gesleept: makkelijke manier om dat project over de hele week te slepen (vergelijkbaar met Excel
   cellen slepen)."
3. "Als ik op maandag een project heb ingevuld en ik klik op dat project, dan wil ik de hele lijst met ZZP'ers om te selecteren wie er die
   dag ingepland worden. Als ik dan sleep zoals in punt 2, slepen de ZZP'ers ook mee."

**Analyse Cowork (kader):** huidig grid = project-rij × dag; sterk voor "wie staat waar op dit project", onleesbaar bij 83 actieve
projecten (Universal). Peter's model = dag-kolom met projectkaarten (zoals Transport v2), sluit aan bij de uitvoerder-app (project-eerst
18-09). Tegenmaatregel voor het verloren weekbeeld per project: projectbalk boven het grid + toggle "Per project" als lees-/controleweergave.

## Feiten uit de code (Cowork 18-09 — verifieer, bouw hierop voort)
- `frontend/src/planning/PlanningScreen.tsx` (1.441 r.) + `planningApi.ts`: `PlanningWeekDto` = `projecten[]` (rij per project mét
  `per_datum: Record<datum, PlanningKaartDto[]>`, `is_actief`, `week_uren`, werkopdrachten), `pool[]` (`geplande_dagen`), `dubbele_dagen`,
  `dubbele_dag_tellers`, `buiten_planning`, `wachtrisico`. De leesroute `GET /uren/kantoor/planning` levert al ALLE actieve projecten
  (V3 23-08) — de data voor dag-eerst is er dus; alleen de weergave draait. **Geen nieuwe leesroute** nodig, wél een `dag_totalen`-veld
  (man per dag) mag erbij als het client-side te duur wordt (het is het niet: som over kaarten).
- Schrijfroutes (`backend/app/uren/router.py` r. 1003–1080): `POST /kantoor/planning` (één persoon × project × datum × dagdeel),
  `/verwijderen`, `/verplaatsen`, `/dagdeel`. Alle per (persoon, dag) mét audit (`planning.py`, bron 'planning', `achteraf`-vlag 15-09).
  **Vulhandvat en ploeg-opslaan zijn dus N aanroepen of één nieuwe bulkroute** — kies de bulkroute (zie 2/3 hieronder) omdat 16
  persoon-dagen in 16 requests met tussenstanden onaanvaardbaar is (half gelukt = half-planning zichtbaar).
- Planning ís de weekstaat-koppeling (`planning.py` r. 221: toewijzing maakt de koppeling aan) — blijft zo; niets aan de weekstaat-kant.
- **Afwezigheid bestaat NIET in het datamodel** (grep `afwezig|verlof` in `app/uren`, `app/veldwerkers` = leeg). De mockup toont
  "afwezig (verlof)" als beschikbaarheidsstand. Zie slice 5.

## Bouw (één run, in deze volgorde; elke slice apart committen)

### 1. Weekgrid dag-eerst (vervangt de Personeel-tab-weergave)
- Vijf dagkolommen ma–vr (za/zo inklapbaar, alleen tonen als er iets op staat), **sticky dagkop** (aparte fix van vandaag hergebruiken)
  mét datum en dagtotaal ("12 man · 3 projecten"); vandaag gemarkeerd.
- Per dag **projectkaarten**: projectnummer + naam, opdrachtgever, initialen ploeg (uitvoerder groen omrand = `--ok`, conflict oranje
  omrand = `--warn`), aantal, urenstatus-stip per kaart (bestaande `UREN_STATUS_KLEUR`; kaartniveau = laagste status van de ploeg, tooltip
  per persoon), starttijd/werkopdracht-tekst als die er is (bestaande `werkopdracht_overrides`), chip "achteraf gepland" blijft.
- Kaart zonder ploeg = **"gereserveerd"** (grijs, dashed) — nieuw concept: een `UrenProjectToewijzing`-rij zonder persoon bestaat niet;
  bouw het als aparte tabel `planning_reservering (administratie, project, datum, aangemaakt_door, aangemaakt_op)`, migratie 0160,
  RLS als de planning-tabellen, audit. Zodra er één persoon op staat verdwijnt de reservering (of blijft als lege drager — kies het
  eenvoudigste dat de UI één kaart per project × dag laat tonen; documenteer).
- **Projectbalk** boven het grid: alle actieve projecten (uit dezelfde respons), zoekveld (nummer/plaats/opdrachtgever, diakriet-loos zoals
  `bankZoek.ts`), sortering: gepland deze week eerst, dan alfabetisch; chip "niet gepland deze week"; horizontaal scrollbaar, "+ N"
  achteraan opent de volledige lijst. **Slepen van een projecttegel naar een dagkolom = reservering (lege kaart)**; zelfde drag-mechaniek
  als de Transport-tab (hergebruik, geen tweede implementatie).
- **Conflictenbalk** boven het grid: "N conflicten deze week" uit `dubbele_dagen` (dubbel op één dag), afwezigheid (slice 5), > 5 op één
  kaart (besluit C), ZZP'er zonder dossier (bestaand signaal) — elk item klikbaar → scrollt naar de kaart en licht die op. Nooit blokkerend.
- Rechter **ZZP-pool** blijft: "N dg" wordt "N dg" + "vrij"/"afwezig t/m …"; filter "alleen vrij"; drag pool → kaart = toevoegen aan die
  dag (bestaande `planToewijzing`); drag initiaal → andere kaart = verplaatsen (`verplaatsToewijzing`), mét Alt/Option = kopiëren.
- Bestaand gedrag ongewijzigd: `?uren=`-filters (kaart-filter i.p.v. rij-filter), signalen-links vanuit Beoordelen/planning-signalen
  landen op de juiste kaart, meldingen per veldwerker × week, Transport- en Werkopdrachten-tabs.

### 2. Vulhandvat (Peter punt 2 + 3b)
- Kaart selecteren → handvat rechts → slepen over dagen binnen de week kopieert kaart + ploeg; tijdens het slepen ghost-kaarten mét
  conflicten al oranje (client-side toets tegen de weekdata: al gepland elders die dag / afwezig); bestaande kaart van hetzelfde
  project op een doeldag = overslaan (nooit dubbel, nooit vervangen).
- Loslaten → **één bulkroute** `POST /uren/kantoor/planning/bulk` met `{ items: [{gebruiker_id, project_id, datum, dagdeel}], bron:
  'vulhandvat' | 'ploeg' | 'ongedaan' }` — atomisch (één transactie), bestaande helper per item hergebruiken (audit per (persoon, dag),
  `achteraf`-vlag, weekstaat-koppeling), respons = per item `gedaan | overgeslagen (reden) | conflict (project/afwezig)`. Limiet 200 items.
- Toast onderin: "Gekopieerd naar di–vr · 16 persoon-dagen · 1 conflict — Ongedaan maken · Toon conflict" (10 s); **Ongedaan maken** =
  dezelfde bulkroute met `verwijderen: true` voor exact de aangemaakte items (server geeft de aangemaakte set terug; client onthoudt die);
  Cmd/Ctrl-Z doet hetzelfde zolang de toast staat. Audit-rij van het ongedaan maken verwijst naar de bulk-correlatie-id.
- Weekgrens: het handvat stopt bij vrijdag (beslispunt ⑥ = nee).

### 3. Ploeg kiezen (Peter punt 3a)
- Klik op kaart → **paneel rechts** (geen modaal; patroon MateriaalstandPaneel): kop project + dag + starttijd (wijzigen = bestaande
  dag-override), zoekveld, volledige lijst veldwerkers in scope mét vinkjes, per persoon beschikbaarheid voor DIE dag: "vrij" (groen),
  "al op ‹project›" (oranje, wél kiesbaar), "afwezig t/m …" (grijs, uitgeschakeld — slice 5), uitvoerder-chip. Knoppen "Zelfde ploeg als
  ‹vorige werkdag met planning op dit project›" en "Toepassen op hele week" (= vinkjesstand naar alle werkdagen van de week via de
  bulkroute, zelfde overslaan-regel).
- Opslaan (N) = diff tussen huidige kaart en vinkjes → bulkroute (toevoegen + verwijderen in één transactie). Verwijderen van iemand die al
  uren heeft ingevuld op die dag: bevestiging mét de urenstand ("Irfan heeft 8 u ingevuld op deze dag — toch van de planning halen?
  De uren blijven staan.") — nooit stil, uren nooit weg.

### 4. Toggle "Per project" (leesweergave)
- Zelfde respons, gedraaid: rij per project, cel = aantal + status-stip + conflict-chip, weekkolom "N mandagen · uren x/y · conflicten".
  Alleen projecten mét planning deze week; regel "N actieve projecten zonder planning · tonen". **Geen bewerkacties** — klik op cel =
  terug naar "Per dag" met die kaart geselecteerd. Toggle-stand onthouden per gebruiker (localStorage).

### 5. Afwezigheid (minimaal, nodig voor de beschikbaarheidsstand)
- Nieuwe tabel `veldwerker_afwezigheid (administratie, gebruiker, van, tot, reden vrije tekst, aangemaakt_door/op)`, migratie 0160 (samen
  met de reservering), RLS, audit. Invoer: Beheer › Veldwerkers › dossier, kaartje "Afwezig" (+ toevoegen / beëindigen; nooit verwijderen,
  wel "tot" vervroegen). **Géén verlofadministratie, géén saldo, géén goedkeuring** — alleen "op deze dagen niet plannen". In de planning:
  pool + paneel tonen "afwezig t/m …", plannen op zo'n dag = conflict (oranje, niet blokkerend), conflictenbalk telt het mee.
- Als Peter dit schrapt: bouw slice 1–4 zonder de afwezig-stand (chip-plek blijft), meld dat in het rapport.

### 6. Guards & regels
- Server-side: bulkroute onder `vereis_kantoorrol` + scope, RLS-test (NOLOGIN-rol) voor beide nieuwe tabellen, limiet 200, atomisch
  (één mislukt item = niets geschreven? NEE — overgeslagen/conflict is géén fout; alleen een echte fout (403/onbekend project) rolt alles
  terug). Idempotent: dubbel indienen van dezelfde set = overgeslagen.
- Frontend: vitest op de dag-eerst-transformatie (rij-grid → dag-kolommen, dagtotalen, kaartstatus = laagste), op de conflict-toets
  client-side, op het vulhandvat-overslaan; Playwright niet in de repo (18-09) → kliktest in het rapport mét screenshots. `tsc -b`,
  contrast-test (nieuwe chips), overflow-sweep (projectbalk scrollt horizontaal binnen de pagina, nooit de pagina zelf).
- Designpass v2: teal = actie (handvat, Opslaan, drop-zones), groen = status (uitvoerder, gekeurd), oranje = conflict; `btn`/`btn
  secondary`/`linkbtn`, geen kale `<button>`; comboboxen i.p.v. selects.
- Schaal: één request per week (bestaand), pool gevirtualiseerd boven 100 personen, geen N+1 in de bulkroute (één query per tabel).

## Afronding
Migratie-routine (make migrate op dev, live 200 op `/uren/kantoor/planning` + bulkroute, dump ververst). WAT_IS_NIEUW klantleesbaar
("Planning is nu per dag: sleep een project naar een dag, trek het over de week, kies de ploeg per kaart"). `docs/regels/
uren-planning-veldwerkers.md` volledige tekst (v3-besluit, reservering, afwezigheid, bulkroute) + BESLISSINGEN "PLANNING V3 — DAG-EERST
(Peter 18-09)" status GEBOUWD + CLAUDE.md één verwijsregel. Rapport `docs/rapporten/2026-09-18-planning-v3-dag-eerst.md` + INDEX +
Gelezen regels; nameting ná deploy (Universal week 39): projecttegel → dag = kaart; handvat ma→vr = 4 kopieën + toast; ploeg-paneel
opslaan; Per project toont dezelfde aantallen — "werkt in productie: ja/nee", screenshots. Één regel voor Peter: wat hij morgen anders
ziet en doet.
