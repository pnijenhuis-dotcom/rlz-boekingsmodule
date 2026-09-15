"""Gedoseerd printen van grote rapporten op een Cloud Run-job (blok 8 nazorg 15-09).

Bevinding derde meting 15-09: `vgg-replay` print het markdown-rapport (~1.700 regels) in één `print()`; Cloud Logging
hield van executie `rlz-reconciliatie-k2tpm` maar 1.208 stdout-regels over — het blok "Niet vertaalbaar" (26 rijen),
"Expliciete rekeningmapping" en "Ongemapte RLZ-rekeningen" (~500 regels) ontbraken volledig, ook bij een tweede
`gcloud logging read` (entries per logNaam: stdout 1208, stderr 13). De ochtendcaptures van 14-09/15-09 misten op
dezelfde manier 3 van de 1.096 rijen. Oorzaak: de Cloud Run-logagent laat regels vallen bij een burst; de logs zijn het
enige kanaal naar de nameting (regel Peter 08-09). Remedie: regel voor regel schrijven mét flush en een korte pauze per
blok — deterministisch, geen schema-/API-impact. De pauze is alleen actief als er echt veel regels zijn; kleine
rapporten en tests merken er niets van."""

from __future__ import annotations

import sys
import time
from typing import TextIO

#: Vanaf dit aantal regels wordt gedoseerd (kleinere rapporten gaan in één keer, zoals voorheen).
GEDOSEERD_VANAF = 200
#: Blokgrootte en pauze: 100 regels per ~0,2 s ≈ 500 regels/s — 1.700 regels in ~3,5 s, ruim onder wat de logagent
#: aankan.
BLOK_REGELS = 100
PAUZE_SECONDEN = 0.2


def print_gedoseerd(
    tekst: str,
    *,
    bestand: TextIO | None = None,
    blok: int = BLOK_REGELS,
    pauze: float = PAUZE_SECONDEN,
    slaap=time.sleep,  # noqa: ANN001 — injecteerbaar voor tests
) -> int:
    """Schrijf `tekst` regel voor regel naar `bestand` (default stdout), flush per regel en pauzeer elke `blok` regels.
    Geeft het aantal geschreven regels terug. Onder `GEDOSEERD_VANAF` regels: geen pauzes (gedrag als één print)."""
    uit = bestand if bestand is not None else sys.stdout
    regels = tekst.split("\n")
    doseren = len(regels) >= GEDOSEERD_VANAF
    for i, regel in enumerate(regels, start=1):
        uit.write(regel + "\n")
        uit.flush()
        if doseren and i % blok == 0 and i < len(regels):
            slaap(pauze)
    return len(regels)
