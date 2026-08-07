"""Harde checks voor omzetboekingen (kassarapporten) — CLAUDE.md: "harde checks blijven áltijd
blokkerend". Pure functies op primitieven, zonder DB of RLZ-sessie (zelfde ontwerp als
app/documenten/checks.py); de orkestratie in app/omzet/voorstel.py levert de invoer aan.

Vier checks, vaste volgorde (de UI toont ze altijd alle vier, nooit stil overslaan):
1. Verplichte velden (periode, regels, bedragen, voorraad-tegenrekening bij kostprijs).
2. Categorie-mapping compleet — een categorie zonder omzet-GB/btw (of zonder kostprijs-GB
   terwijl er wél kostprijs is) blokkeert per regel (CLAUDE.md-omzetbesluit).
3. Regelsom vs rapport-totaal (omzet én kostprijs apart).
4. Memoriaal-saldo-0 — de nieuwe generieke harde check (CLAUDE.md-checkstatus: "→ fase 2"):
   totaal debet moet exact gelijk zijn aan totaal credit. RLZ weigert een niet-sluitend
   memoriaal zelf óók bij actie 17 (STAP 0 §4) — deze check is de fail-fast vóór de API-call,
   de RLZ-weigering het vangnet erachter.
Daarnaast twee checks met context van buiten (aangeleverd door de orkestratie):
5. Duplicaat per periode — lokaal overlap-onderzoek (STAP 0 §2: de SalesInvoices-collectie
   ziet API-facturen niet, dus lokaal is hier de primaire waarborg) + de RLZ-side
   memoriaal-Reference-hit die de orkestratie aanlevert (fail-closed bij een RLZ-fout).
6. Marge-plausibiliteit vs eigen historie (mockup-membanner) — blokkerend buiten de bandbreedte.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.documenten.checks import CheckRapport, CheckResultaat

# Zelfde afrondingstolerantie als de inkoop-regeltelling: centen-afronding per regel mag, een
# echte bedragfout niet.
_ROND_TOLERANTIE = Decimal("0.01")


@dataclass(frozen=True)
class OmzetCheckRegel:
    """Eén categorie-regel zoals de checks 'm nodig hebben (los van het ORM-model)."""

    categorie: str
    omzet_bedrag: Decimal | None
    kostprijs_bedrag: Decimal | None
    omzet_ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    kostprijs_ledger_id: uuid.UUID | None


@dataclass(frozen=True)
class MemoriaalRegel:
    """Eén memoriaalregel voor de saldo-0-check: precies één van beide bedragen gevuld
    (CreditOrDebit-vorm van RLZ, STAP 0 §3)."""

    debet_bedrag: Decimal = Decimal(0)
    credit_bedrag: Decimal = Decimal(0)


def check_verplichte_velden_omzet(
    *,
    periode_start: date | None,
    periode_eind: date | None,
    regels: list[OmzetCheckRegel],
    voorraad_ledger_id: uuid.UUID | None,
) -> CheckResultaat:
    ontbrekend: list[str] = []
    if periode_start is None:
        ontbrekend.append("periode-begindatum")
    if periode_eind is None:
        ontbrekend.append("periode-einddatum")
    if periode_start is not None and periode_eind is not None and periode_start > periode_eind:
        ontbrekend.append("geldige periode (begindatum ligt ná de einddatum)")
    if not regels:
        ontbrekend.append("minstens één categorie-regel")
    heeft_kostprijs = False
    for i, regel in enumerate(regels, start=1):
        if regel.omzet_bedrag is None:
            ontbrekend.append(f"omzetbedrag (regel {i})")
        if regel.kostprijs_bedrag is not None and regel.kostprijs_bedrag != 0:
            heeft_kostprijs = True
    if heeft_kostprijs and voorraad_ledger_id is None:
        ontbrekend.append("voorraad-tegenrekening (instelling voor het kostprijsmemoriaal)")

    if ontbrekend:
        return CheckResultaat("Verplichte velden", False, f"Ontbrekend: {', '.join(ontbrekend)}")
    return CheckResultaat("Verplichte velden", True, "Alle verplichte velden zijn ingevuld")


def check_categorie_mapping(*, regels: list[OmzetCheckRegel]) -> CheckResultaat:
    """Elke categorie moet een omzet-GB + btw-code dragen, en een kostprijs-GB zodra er een
    kostprijsbedrag is — "nieuwe categorie zonder mapping → regel blokkerend". De regelwaarden
    zijn de mapping (voorgevuld) of een handmatige override; leeg = niet gemapt."""
    zonder: list[str] = []
    for regel in regels:
        redenen = []
        if regel.omzet_ledger_id is None:
            redenen.append("omzet-GB")
        if regel.taxrate_id is None:
            redenen.append("btw-code")
        if regel.kostprijs_bedrag is not None and regel.kostprijs_bedrag != 0 and regel.kostprijs_ledger_id is None:
            redenen.append("kostprijs-GB")
        if redenen:
            zonder.append(f"‘{regel.categorie}’ ({', '.join(redenen)})")
    if zonder:
        return CheckResultaat(
            "Categorie-mapping",
            False,
            f"Categorie(ën) zonder complete mapping: {'; '.join(zonder)} — stel de mapping in, "
            "die wordt voor volgende rapporten onthouden",
        )
    return CheckResultaat("Categorie-mapping", True, "Elke categorie heeft een complete mapping")


def _som(bedragen: list[Decimal | None]) -> Decimal | None:
    aanwezig = [b for b in bedragen if b is not None]
    if not aanwezig:
        return None
    return sum(aanwezig, Decimal(0))


def check_regelsom_omzet(
    *,
    regels: list[OmzetCheckRegel],
    rapport_totaal_omzet: Decimal | None,
    rapport_totaal_kostprijs: Decimal | None,
) -> CheckResultaat:
    """Som van de categorie-regels vs de rapport-totalen, per kolom. Geen rapport-totaal gelezen
    terwijl er wél regels zijn = blokkerend: zonder controlegetal is de volledigheid van de
    regelset niet te toetsen (zelfde fail-closed-lijn als de inkoop-regeltelling)."""
    fouten: list[str] = []
    som_omzet = _som([r.omzet_bedrag for r in regels])
    if rapport_totaal_omzet is None:
        fouten.append("geen rapport-totaal omzet om tegen te controleren")
    elif som_omzet is None:
        fouten.append("geen omzetbedragen op de regels")
    elif abs(som_omzet - rapport_totaal_omzet) > _ROND_TOLERANTIE:
        fouten.append(f"som omzetregels (€ {som_omzet}) wijkt af van het rapport-totaal (€ {rapport_totaal_omzet})")

    som_kostprijs = _som([r.kostprijs_bedrag for r in regels])
    if som_kostprijs is not None or rapport_totaal_kostprijs is not None:
        # Kostprijs is optioneel (rapport zonder kostprijskolom), maar half aangeleverd is fout.
        if rapport_totaal_kostprijs is None:
            fouten.append("kostprijs op de regels maar geen rapport-totaal kostprijs")
        elif som_kostprijs is None:
            fouten.append("rapport-totaal kostprijs maar geen kostprijsbedragen op de regels")
        elif abs(som_kostprijs - rapport_totaal_kostprijs) > _ROND_TOLERANTIE:
            fouten.append(
                f"som kostprijsregels (€ {som_kostprijs}) wijkt af van het rapport-totaal "
                f"(€ {rapport_totaal_kostprijs})"
            )

    if fouten:
        return CheckResultaat("Regelsom vs rapport-totaal", False, "; ".join(fouten).capitalize())
    return CheckResultaat("Regelsom vs rapport-totaal", True, "Regelsommen komen overeen met de rapport-totalen")


def check_memoriaal_saldo_0(*, regels: list[MemoriaalRegel]) -> CheckResultaat:
    """De generieke harde check "memoriaal-saldo-0" (CLAUDE.md-checkstatus): totaal debet moet
    exact gelijk zijn aan totaal credit — géén afrondingstolerantie: het memoriaal wordt door
    onze eigen code opgebouwd, elke afwijking is een bug of datavervuiling, nooit legitieme
    afronding. RLZ weigert een niet-sluitend memoriaal zelf ook bij actie 17 (STAP 0 §4) —
    dit is de fail-fast vóór de API-call."""
    if not regels:
        return CheckResultaat("Memoriaal-saldo 0", False, "Geen memoriaalregels om te toetsen")
    debet = sum((r.debet_bedrag for r in regels), Decimal(0))
    credit = sum((r.credit_bedrag for r in regels), Decimal(0))
    if debet != credit:
        return CheckResultaat(
            "Memoriaal-saldo 0",
            False,
            f"Memoriaal sluit niet: debet € {debet} ≠ credit € {credit} (verschil € {abs(debet - credit)})",
        )
    return CheckResultaat("Memoriaal-saldo 0", True, f"Memoriaal sluit: debet = credit = € {debet}")


def check_duplicaat_periode(
    *,
    periode_start: date | None,
    periode_eind: date | None,
    bestaande_periodes: list[tuple[date, date]],
    rlz_memoriaal_hits: int | None,
) -> CheckResultaat:
    """Duplicaatbewaking per periode. `bestaande_periodes` = de niet-gestorneerde omzet-boekingen
    van deze administratie (exclusief dit document zelf) — élke overlap blokkeert, niet alleen een
    exacte match. `rlz_memoriaal_hits` = het aantal vreemde ManualJournals in RLZ met onze
    deterministische periode-referentie (None = de RLZ-check kon niet uitgevoerd worden →
    fail-closed, zelfde lijn als de inkoop-duplicaatcheck). De verkoopfactuur-kant is via de API
    niet te bevragen (STAP 0 §2: de collectie ziet API-facturen niet) — vandaar lokaal primair."""
    if periode_start is None or periode_eind is None:
        return CheckResultaat("Duplicaat per periode", False, "Kan niet controleren zonder complete periode")
    overlappend = [
        (start, eind) for start, eind in bestaande_periodes if start <= periode_eind and periode_start <= eind
    ]
    if overlappend:
        beschrijving = ", ".join(f"{start} t/m {eind}" for start, eind in overlappend)
        return CheckResultaat(
            "Duplicaat per periode",
            False,
            f"Periode overlapt met al geboekte omzetperiode(s): {beschrijving}",
        )
    if rlz_memoriaal_hits is None:
        return CheckResultaat(
            "Duplicaat per periode",
            False,
            "RLZ-duplicaatcheck op het kostprijsmemoriaal kon niet uitgevoerd worden — probeer opnieuw",
        )
    if rlz_memoriaal_hits > 0:
        return CheckResultaat(
            "Duplicaat per periode",
            False,
            f"{rlz_memoriaal_hits} bestaand(e) memoriaal/memorialen in RLZ met de referentie van deze periode",
        )
    return CheckResultaat("Duplicaat per periode", True, "Periode nog niet geboekt — geen duplicaat")


def bereken_marge_pct(*, totaal_omzet: Decimal | None, totaal_kostprijs: Decimal | None) -> Decimal | None:
    """Marge zoals het kantoor 'm hanteert (mockup: "marge 160%"): omzet / kostprijs × 100."""
    if totaal_omzet is None or totaal_kostprijs is None or totaal_kostprijs == 0:
        return None
    return (totaal_omzet / totaal_kostprijs * 100).quantize(Decimal("0.1"))


def check_marge_plausibiliteit(
    *,
    totaal_omzet: Decimal | None,
    totaal_kostprijs: Decimal | None,
    historische_marges: list[Decimal],
    bandbreedte_procentpunt: Decimal,
) -> CheckResultaat:
    """Marge vs eigen historie (mockup-membanner: "marge 160%, historisch gemiddeld 157% —
    binnen bandbreedte"). Zonder historie of zonder kostprijs is er niets te toetsen — dan OK
    mét dat voorbehoud in de melding (de eerste boeking van een administratie kán niet anders).
    Buiten de bandbreedte = blokkerend: eerst een mens die het rapport verklaart (en zo nodig
    de bandbreedte-instelling aanpast), dan pas boeken."""
    marge = bereken_marge_pct(totaal_omzet=totaal_omzet, totaal_kostprijs=totaal_kostprijs)
    if marge is None:
        return CheckResultaat(
            "Marge-plausibiliteit", True, "Geen kostprijs in dit rapport — geen margecontrole mogelijk"
        )
    if not historische_marges:
        return CheckResultaat(
            "Marge-plausibiliteit",
            True,
            f"Marge {marge}% — nog geen geboekte historie om tegen te toetsen (eerste boeking)",
        )
    gemiddelde = (sum(historische_marges, Decimal(0)) / len(historische_marges)).quantize(Decimal("0.1"))
    afwijking = abs(marge - gemiddelde)
    if afwijking > bandbreedte_procentpunt:
        return CheckResultaat(
            "Marge-plausibiliteit",
            False,
            f"Marge {marge}% wijkt {afwijking} procentpunt af van het historisch gemiddelde "
            f"({gemiddelde}%) — buiten de bandbreedte van {bandbreedte_procentpunt} procentpunt",
        )
    return CheckResultaat(
        "Marge-plausibiliteit",
        True,
        f"Marge {marge}% (historisch gemiddeld {gemiddelde}%) — binnen bandbreedte",
    )


def voer_omzet_checks_uit(
    *,
    periode_start: date | None,
    periode_eind: date | None,
    regels: list[OmzetCheckRegel],
    voorraad_ledger_id: uuid.UUID | None,
    memoriaal_regels: list[MemoriaalRegel],
    rapport_totaal_omzet: Decimal | None,
    rapport_totaal_kostprijs: Decimal | None,
    bestaande_periodes: list[tuple[date, date]],
    rlz_memoriaal_hits: int | None,
    historische_marges: list[Decimal],
    bandbreedte_procentpunt: Decimal,
) -> CheckRapport:
    """Alle harde omzet-checks, in vaste volgorde (consistente UI-rijen). Zonder kostprijsregels
    is het memoriaal leeg en wordt de saldo-check als OK-zonder-memoriaal gerapporteerd."""
    saldo_check = (
        check_memoriaal_saldo_0(regels=memoriaal_regels)
        if memoriaal_regels
        else CheckResultaat("Memoriaal-saldo 0", True, "Geen kostprijsmemoriaal (geen kostprijs in dit rapport)")
    )
    return CheckRapport(
        (
            check_verplichte_velden_omzet(
                periode_start=periode_start,
                periode_eind=periode_eind,
                regels=regels,
                voorraad_ledger_id=voorraad_ledger_id,
            ),
            check_categorie_mapping(regels=regels),
            check_regelsom_omzet(
                regels=regels,
                rapport_totaal_omzet=rapport_totaal_omzet,
                rapport_totaal_kostprijs=rapport_totaal_kostprijs,
            ),
            saldo_check,
            check_duplicaat_periode(
                periode_start=periode_start,
                periode_eind=periode_eind,
                bestaande_periodes=bestaande_periodes,
                rlz_memoriaal_hits=rlz_memoriaal_hits,
            ),
            check_marge_plausibiliteit(
                totaal_omzet=rapport_totaal_omzet,
                totaal_kostprijs=rapport_totaal_kostprijs,
                historische_marges=historische_marges,
                bandbreedte_procentpunt=bandbreedte_procentpunt,
            ),
        )
    )
