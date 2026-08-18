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
| 2 | [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md) | Per partij (Anthropic, Google Cloud, Reeleezee/Exact): welke verwerkersovereenkomst/DPA nodig is, status en acties |
| 3 | [03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md) | Rolbepaling per dienst + getoetst tekstblok voor de klantovereenkomst |
| 4 | [04-dpia-lichte-toets-ai-extractie.md](04-dpia-lichte-toets-ai-extractie.md) | DPIA-lichte toets op de AI-extractie: risico's, geborgde mitigaties, restrisico's |
| 5 | [05-activatie-checklist.md](05-activatie-checklist.md) | Volgorde waarin de gates aangezet mogen worden en wat er per gate rond moet zijn |
| 6 | [06-datalek-procedure.md](06-datalek-procedure.md) | Datalek-procedure (meldplicht art. 33/34 AVG), kantoorbreed, incl. rollen en meldstappen |
| 7 | [07-verwerkersovereenkomst-pdl.md](07-verwerkersovereenkomst-pdl.md) | Intra-groep verwerkersovereenkomst kantoor ↔ PDL Powerhouse B.V. (jurist-vraag 9; getoetst, concept tot ondertekening) |
| 8 | [08-f5-poortdossier.md](08-f5-poortdossier.md) | Afvinkbaar bewijsdossier voor de F5-go-live-poort (= stap 2 van doc 5): per punt bewijs/vindplaats + wie + status |

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
— verversen via `backend/.venv/bin/python scripts/genereer_avg_docx.py <bron.md> <doel.docx>`,
nooit met de hand in Word bewerken (2026-08-13: een Word-hersave van de
verwerkersovereenkomst-docx introduceerde precies zo'n zwevende binary-wijziging, incl.
per ongeluk getikte tekst; opgelost door regeneratie uit de ongewijzigde md).

Status: **juridische toetsing afgerond — jurist-akkoord 2026-08-12** (alle 9 toetsvragen; zie
`docs/BESLISSINGEN.md`, onderwerp "AVG-compliance"). De activatie-checklist (doc 5) is sindsdien
de operationele leidraad; het F5-poortdossier (doc 8) is de afvinkplek voor de go-live-poort.
Bronverificatie van de externe links: 2026-08-11 (web); cloudconfiguratie-feiten: 2026-08-14
(read-only describe).
