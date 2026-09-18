uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-zoekveld-klantenlijst-dagkop-sticky.md

Domeinen: werkvoorraad-controlescherm, uren-planning-veldwerkers, kantoor-frontend

# OPDRACHT 18-09 — Twee kleine fixes: zoekveld klantenlijst + dagkop planning blijft staan bij scrollen (Peter 18-09, screenshots)

## A — Zoekveld op de klantenlijst (Werkvoorraad › Overzicht per klant)
Peter: "graag zoekveld bij administraties, zodat je niet de hele lijst door hoeft te scrollen." 71+ administraties, alfabetisch, alleen
een Groep-filter. Bouw: zoekveld links van "Groep: alle" (`?zoek=`, client-side op naam/code/groep, dezelfde `bankZoek.ts`-achtige
normalisatie zonder diakrieten, teller "N van M"), focus met `/`, leeg = alles; onthoud de laatste zoekterm per sessie; werkt samen
met het Groep-filter. Geen server-call (lijst staat al in de tellers-cache-respons). Overflow-sweep, test op filter+groep-combinatie.

## B — Planning: dagkoppen (MA 14-9 … VR 18-9) verdwijnen bij verticaal scrollen
Screenshot: ná scrollen is de kopregel weg, de kolommen zijn niet meer te lezen. Bouw: `position: sticky; top: <hoogte kop>` op de
dag-kopregel binnen de scrollcontainer (de rechter ZZP-kolom is al sticky, r. 1240), inclusief de projectkolom-kop; de kop krijgt een
achtergrond + onderrand zodat kaartjes eronder niet doorschijnen; test in de overflow-sweep (scrollpositie 800 px → kop zichtbaar).
Idem voor de Transport-dagagenda als die hetzelfde patroon heeft.

## Afronding
WAT_IS_NIEUW twee regels; rapport + INDEX + Gelezen regels; nameting ná deploy: zoekveld filtert "Univ" → 3 rijen, dagkop blijft
staan (screenshot in rapport) — "werkt in productie: ja/nee".
