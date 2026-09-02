# AVG-voorbereidingspakket — RLZ Boekingsmodule

> ✅ **Getoetst — jurist-akkoord 2026-08-12** (alle 9 toetsvragen; volledige status onderaan
> dit bestand). Intern opgesteld, juridische toetsing afgerond.

Besluit Peter 2026-08-11: dit pakket (documenten + register + activatiechecklist, géén code) is de
poort vóór AI-extractie op echte klantdata en vóór klantdata in de cloud (GCP-uitrol, gepland
september 2026).

| # | Document | Inhoud |
|---|---|---|
| 0 | [00-toetsingsmemo-jurist.md](00-toetsingsmemo-jurist.md) | Toetsingsmemo voor de jurist: leeswijzer, context en concrete toetsvragen per document |
| 1 | [01-verwerkingsregister.md](01-verwerkingsregister.md) | Verwerkingsregister (art. 30 AVG) voor het kantoor als gebruiker van de module |
| 2 | [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md) | Per partij (PDL, Anthropic, Google Cloud, Reeleezee/Exact, Workspace, Apple, Play/FCM): welke verwerkersovereenkomst/DPA nodig is, status en acties — sinds 2026-08-19 op de PDL-keten (alleen Exact rechtstreeks) |
| 3 | [03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md) | Rolbepaling per dienst + getoetst tekstblok voor de klantovereenkomst — §3 sinds 2026-08-19 op de PDL-keten (rolbepaling + tekstblok ongewijzigd) |
| 4 | [04-dpia-lichte-toets-ai-extractie.md](04-dpia-lichte-toets-ai-extractie.md) | DPIA-lichte toets op de AI-extractie: risico's, geborgde mitigaties, restrisico's |
| 5 | [05-activatie-checklist.md](05-activatie-checklist.md) | Volgorde waarin de gates aangezet mogen worden en wat er per gate rond moet zijn — stap 1 sinds 2026-08-19 op de PDL-keten (PDL-VWO-tekening = stap-1-voorwaarde) |
| 6 | [06-datalek-procedure.md](06-datalek-procedure.md) | Datalek-procedure (meldplicht art. 33/34 AVG), kantoorbreed, incl. rollen en meldstappen — meldketen §5 sinds 2026-08-19 via PDL (24 u, artikel 9 VWO) |
| 7 | [07-verwerkersovereenkomst-pdl.md](07-verwerkersovereenkomst-pdl.md) | Intra-groep verwerkersovereenkomst kantoor ↔ PDL Powerhouse B.V. (jurist-vraag 9; **GETEKEND 2026-08-19** — in tweevoud te Arnhem, beide partijen P.W. Nijenhuis; getekend exemplaar `Verwerkersovereenkomst-PDL-getekend-2026-08-18.pdf` + bijlagen-docx `Bijlagen-A-B-C-…-2026-08-18.docx`; Bijlage B op de feitelijke accountstructuur: Anthropic/GCP/Workspace/Apple/Play onder PDL, Reeleezee rechtstreeks; documenten 1–3 en 5–6 op die keten aangepast 2026-08-19; KvK kantoor 72504412 ingevuld) |
| 8 | [08-f5-poortdossier.md](08-f5-poortdossier.md) | Afvinkbaar bewijsdossier voor de F5-go-live-poort (= stap 2 van doc 5): per punt bewijs/vindplaats + wie + status |
| 9 | [09-zdr-beslisnotitie.md](09-zdr-beslisnotitie.md) | **Blok A 02-09 — CONCEPT ter besluit Peter:** zero data retention bij Anthropic — wat het is, geen gepubliceerd tarief, Covered-Models-uitsluiting, opties A/B/C, advies A + C, invulblok voor het besluit |
| 10 | [10-model-check.md](10-model-check.md) | **Blok A 02-09 — UITGEVOERD:** modellen in code vs productie-kostenmeter vs register/DPA (sonnet-5 + haiku-4-5; ZDR-compatibel GROEN, register-dekking ORANJE: voorraad-normalisatie + contract-ontleding zonder V-rij; prijstabel = fail-closed allowlist; audit-gaten gate-default) |
| 11 | [11-klantinformatietekst-concept.md](11-klantinformatietekst-concept.md) | **Blok A 02-09 — CONCEPT (Peter/jurist redigeert + verstuurt):** klantleesbare A4 "Zo gebruiken wij AI bij uw administratie" — wat gaat er naar de AI, waarom, waarborgen, verwerkersrol, keuze; twee bewaar-varianten afhankelijk van doc 9 |
| 12 | [12-beoordelingskader-gevoelige-administraties.md](12-beoordelingskader-gevoelige-administraties.md) | **Blok A 02-09 — VOORSTEL ter besluit Peter:** criteria A–E (+R) + classificatie van alle 31 administraties met feitelijke gate-stand (cloud-DB 02-09): 2× UIT tot bevestiging, 1× UIT (test), 27× AAN; verzendlog klantinfo per rij |

Word-bundel voor verzending aan de jurist: `AVG-pakket-ter-toetsing-2026-08-11.docx`
(memo + alle documenten in één bestand).

Gearchiveerde brondocumenten (PDF-webprints, aangeleverd door Peter; kernpunten en status
per partij in [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md)):

- **Anthropic** (2026-08-14/15): Commercial Terms of Service (effective 17-06-2025),
  Data Processing Addendum (effective 24-02-2025), Privacy Center "Where are your servers
  located?" (16-06-2026, opslag VS) en de DPF-registercheck (15-08-2026, géén treffer —
  niet DPF-gecertificeerd).
- **Google** (2026-08-15): Cloud Data Processing Addendum NL (versie 8 juni 2026 — geldt
  voor GCP én Workspace, dus ook voor het intake-postvak), GCP-subverwerkerslijst,
  Workspace-subverwerkerslijst (23-07-2026) en de oude losse Workspace-DPA (24-09-2021,
  door Google vervangen — alleen context).
- **Exact Reeleezee** (2026-08-14/15): VWO 1.5 + bijlage 1.6 (in `docs/`) en de
  supportbevestiging `Bevestiging versie RLZ.pdf`.

**De .md-bestanden zijn canoniek; de .docx-bestanden zijn gegenereerde verzend-artefacten**
— verversen via `backend/.venv/bin/python scripts/genereer_avg_docx.py <bron.md> <doel.docx>`
(vlag `--zonder-statusnoot` laat het status-blockquote onder de H1 weg — de schone
teken-/printversie, gebruikt voor de definitieve PDL-docx), nooit met de hand in Word bewerken (2026-08-13: een Word-hersave van de
verwerkersovereenkomst-docx introduceerde precies zo'n zwevende binary-wijziging, incl.
per ongeluk getikte tekst; opgelost door regeneratie uit de ongewijzigde md).

**Stand 02-09 (blok A AVG-afronding):** de AI-gate staat in productie AAN voor alle 30 actieve
administraties terwijl vier stap-1-punten open staan; documenten 9–12 maken die vier punten
beslisklaar/aantoonbaar (ZDR, model-check, klantinformatie, gevoelige administraties). Niets is
afgevinkt zonder besluit — zie doc 5 stap 1 en "Feitelijke stand".

Status: **juridische toetsing afgerond — jurist-akkoord 2026-08-12** (alle 9 toetsvragen; zie
`docs/BESLISSINGEN.md`, onderwerp "AVG-compliance"). De activatie-checklist (doc 5) is sindsdien
de operationele leidraad; het F5-poortdossier (doc 8) is de afvinkplek voor de go-live-poort.
Bronverificatie van de externe links: 2026-08-11 (web); cloudconfiguratie-feiten: 2026-08-14
(read-only describe).
