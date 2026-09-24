uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-bundelrun-zeven-punten.md

Domeinen: werkvoorraad-controlescherm, omzet, kantoor-frontend

# BUG 23-09 — "Open document" vanuit een vraag opent een KASSARAPPORT in het inkoop-controlescherm (leeg crediteurformulier)

**Feit (Peter 23-09, Van Boxtel Horeca Exploitatie, Journaal 19-9.pdf e7d89765-c4f5-42f3-82d9-71f8a11f5f7f, soort `kassarapport`,
status `vraag_open` — vraag 21-09 06:10 "Nieuwe rapportcategorie(ën) zonder GB/btw-mapping: Dranken, Edible, Hash, Headshop, Joints,
Snacks, Wiet … stel op het omzetreview-scherm …"):** Peter opende het document vanuit de vraag en kreeg het INKOOP-controlescherm
(crediteur-zoekveld, lege kopgegevens, 7 lege boekingsregels) — met de vraag die hem naar "het omzetreview-scherm" verwijst dat hij dus
niet te zien krijgt. Peter: "boeking van Van Boxtel staat onder inkoop maar is kassarapport, hoe verhuizen we die nu?" — er hoeft
niets verhuisd te worden (autotype 19-09 werkte: alle 10 Journaal-documenten staan op `kassarapport`), de link is fout.

**Oorzaak:** `frontend/src/vragen/VraagThread.tsx:242` linkt hard naar `/documenten/${administratieId}/${vraag.document_id}`;
`werkvoorraad/format.ts::documentRoute` en `zoeken/reviewPad.ts` kennen de soort-afhankelijke route (`/omzet/…` voor kassarapport,
verkoop-route voor verkoopfactuur) maar de vraag-thread gebruikt ze niet. Zelfde klasse van fout mogelijk in: kantoorbrede vragenlijst
(`vraagDeeplink` → `?sectie=vragen&document=` → VragenScreen → welke link?), accordeur-app-links, reconciliatie-acties, e-mail-deeplinks
in de vraag-mail, "volgende document"-doorloop ná boeken (`DocumentDetailScreen` 589/745/755 gebruikt wél `documentRoute`).

## Opdracht
1. Eén routefunctie voor "open dit document" (`documentRoute`/`reviewPad` samenvoegen tot één bron in `werkvoorraad/format.ts`) en
   álle plekken die een documentlink bouwen ernaartoe (grep `/documenten/${` over `frontend/src`, ook mails in `backend/app/berichten`
   en de accordeur-app). Guard-test: geen letterlijke `/documenten/${` buiten die ene functie.
2. `DocumentDetailScreen` zelf: opent iemand toch `/documenten/<id>` van een kassarapport/verkoopfactuur → redirect naar de juiste
   review-route (nooit een leeg inkoopformulier tonen voor een niet-inkoopdocument).
3. Van Boxtel-nazorg (lees-only meting in het rapport): naast de 10 Journaal-documenten staan `InboekDienst2 <dag>.pdf` (7×),
   `MargeRapport5 week 38.pdf` en `weekstaten week 38.pdf` als `inkoopfactuur te_controleren`. Bepaal per bestandstype of het een
   kassarapport-variant is die de ProfX-parser zou moeten kennen (dan parser + autotype uitbreiden), een bijlage bij het Journaal van
   dezelfde dag (dan bundelen/afvoeren "geen boekstuk" mét reden), of iets anders — voorstel per type, niet raden; Peter beslist.
4. Copy: de vraag-tekst "Stel op het omzetreview-scherm …" krijgt een knop "Naar omzetreview →" in de thread zelf.
5. Tests + rapport + INDEX + Gelezen regels; BESLISSINGEN "DOCUMENTLINK VOLGT DE SOORT — VRAAG-THREAD OPENDE KASSARAPPORT IN
   INKOOPSCHERM (23-09)"; WAT_IS_NIEUW; CLAUDE.md één regel.
