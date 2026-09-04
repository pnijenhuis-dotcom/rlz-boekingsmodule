"""Flankerend signaal (ontwerpnotitie ⑥, tweede helft): het weekanalyse-signaal "inkoop zonder omzet"
(`app/projecten/cijfers.py::kosten_zonder_omzet_weken`) wordt TIJD-GEBONDEN — een project dat net gestart is heeft
per definitie nog geen omzet; pas signaleren als de projectlooptijd ≥ N weken is (Beheerder-instelling
`inkoop_zonder_omzet_wachtweken`, default 4). Looptijd = vanaf de startdatum uit de projectspecificatie
(`looptijd_van`) als die bestaat, anders vanaf de eerste kostenweek. Pure functie, `vandaag` injecteerbaar.

NB de contract-ontleding kent géén soort 'termijn' (OntledingRegelSoort: contract_m2, looptijd, huurtijd,
doorlopende_huur, opdrachtgever, werknummer, staffel, boete) — de "eerste termijndatum" uit de opdracht bestaat
dus (nog) niet als gegeven; `looptijd_van` is wat de ontleding (soort LOOPTIJD) wél deterministisch vult.
Beslispunt Peter in BESLISSINGEN."""

from __future__ import annotations

from datetime import date, timedelta

from app.projecten.cijfers import ProjectCijfers, kosten_zonder_omzet_weken


def _eerste_kostenweek_start(cijfers: ProjectCijfers) -> date | None:
    """Maandag van de eerste ISO-week met kosten (geboekt of onderweg)."""
    for week in cijfers.weken:
        if week.kosten_geboekt != 0 or week.kosten_onderweg != 0 or week.onderweg_onbepaalbaar_uren != 0:
            return date.fromisocalendar(week.jaar, week.weeknummer, 1)
    return None


def looptijd_weken(cijfers: ProjectCijfers, *, vandaag: date, looptijd_van: date | None) -> int | None:
    """Volle weken sinds de projectstart (specificatie) of anders sinds de eerste kostenweek; None zonder beide."""
    start = looptijd_van or _eerste_kostenweek_start(cijfers)
    if start is None:
        return None
    dagen = (vandaag - start).days
    if dagen < 0:
        return 0
    return dagen // 7


def inkoop_zonder_omzet_weken(
    cijfers: ProjectCijfers, *, vandaag: date, wachtweken: int, looptijd_van: date | None = None
) -> int:
    """Het bestaande trailing-weken-signaal, maar 0 (zwijgt) zolang de looptijd korter is dan `wachtweken`.
    `wachtweken = 0` = het oude gedrag (altijd signaleren)."""
    weken = kosten_zonder_omzet_weken(cijfers)
    if weken == 0 or wachtweken <= 0:
        return weken
    looptijd = looptijd_weken(cijfers, vandaag=vandaag, looptijd_van=looptijd_van)
    if looptijd is None or looptijd < wachtweken:
        return 0
    return weken


def wacht_tot(*, looptijd_van: date | None, eerste_kosten: date | None, wachtweken: int) -> date | None:
    """Informatief: vanaf welke datum het signaal mag gaan spreken."""
    start = looptijd_van or eerste_kosten
    return start + timedelta(weeks=wachtweken) if start else None
