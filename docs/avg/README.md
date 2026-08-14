# AVG-voorbereidingspakket — RLZ Boekingsmodule

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**

Besluit Peter 2026-08-11: dit pakket (documenten + register + activatiechecklist, géén code) is de
poort vóór AI-extractie op echte klantdata en vóór klantdata in de cloud (GCP-uitrol, gepland
september 2026).

| # | Document | Inhoud |
|---|---|---|
| 0 | [00-toetsingsmemo-jurist.md](00-toetsingsmemo-jurist.md) | Toetsingsmemo voor de jurist: leeswijzer, context en concrete toetsvragen per document |
| 1 | [01-verwerkingsregister.md](01-verwerkingsregister.md) | Verwerkingsregister (art. 30 AVG) voor het kantoor als gebruiker van de module |
| 2 | [02-subverwerkers-checklist.md](02-subverwerkers-checklist.md) | Per partij (Anthropic, Google Cloud, Reeleezee/Exact): welke verwerkersovereenkomst/DPA nodig is, status en acties |
| 3 | [03-verwerker-vs-verantwoordelijke.md](03-verwerker-vs-verantwoordelijke.md) | Rolbepaling per dienst + concept-tekstblok voor de klantovereenkomst |
| 4 | [04-dpia-lichte-toets-ai-extractie.md](04-dpia-lichte-toets-ai-extractie.md) | DPIA-lichte toets op de AI-extractie: risico's, geborgde mitigaties, restrisico's |
| 5 | [05-activatie-checklist.md](05-activatie-checklist.md) | Volgorde waarin de gates aangezet mogen worden en wat er per gate rond moet zijn |
| 6 | [06-datalek-procedure.md](06-datalek-procedure.md) | Datalek-procedure (meldplicht art. 33/34 AVG), kantoorbreed, incl. rollen en meldstappen |

Word-bundel voor verzending aan de jurist: `AVG-pakket-ter-toetsing-2026-08-11.docx`
(memo + alle documenten in één bestand).

Gearchiveerde brondocumenten (aangeleverd door Peter, 2026-08-14): de Anthropic
**Commercial Terms of Service** (effective 17-06-2025) en het **Data Processing Addendum**
(effective 24-02-2025) als PDF-webprints — kernpunten en status in checklist A van
[02-subverwerkers-checklist.md](02-subverwerkers-checklist.md).

**De .md-bestanden zijn canoniek; de .docx-bestanden zijn gegenereerde verzend-artefacten**
— verversen via `backend/.venv/bin/python scripts/genereer_avg_docx.py <bron.md> <doel.docx>`,
nooit met de hand in Word bewerken (2026-08-13: een Word-hersave van de
verwerkersovereenkomst-docx introduceerde precies zo'n zwevende binary-wijziging, incl.
per ongeluk getikte tekst; opgelost door regeneratie uit de ongewijzigde md).

Status: **concept — wacht op juridische toetsing Peter** (zie `docs/BESLISSINGEN.md`, onderwerp
"AVG-compliance"). Bronverificatie van de externe links: 2026-08-11 (web).
