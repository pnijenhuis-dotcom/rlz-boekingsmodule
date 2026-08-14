"""Projectnaam-vorming voor de route-A-aanmaak (koppelcontract §5 v1.15): vastgoed levert de
pand-/projectnaam-INVOER, wíj vormen de definitieve RLZ-projectnaam — RLZ-writes zijn van ons,
dus ook de naamgeving is van ons. Deterministisch en zonder verzinsels: normaliseren + harde
poorten; wat niet door de poorten komt is een zichtbare fout naar vastgoed (400), nooit een
stil aangepaste naam.

§2.1-constraint (hard): RLZ-projectnamen bevatten GÉÉN BAG-id — het BAG-id blijft uitsluitend
in de vastgoedmodule. Een BAG-identificatie is exact 16 cijfers; elke reeks van 16 of meer
aaneengesloten cijfers in de invoer wordt daarom geweigerd (fail-closed: liever een expliciete
afwijzing dan een contract-schending in RLZ)."""

from __future__ import annotations

import re

# RLZ's harde kolomlimiet (PRJNAM): 50 tekens → 204, 51 → 400 "te lang" (hertest 2026-08-14,
# poc_projects_toplevel.py). De poort zit hiermee exact op RLZ's grens, zodat een te lange
# invoer een deterministische 400 naar vastgoed is i.p.v. een 502-RLZ-fout achteraf.
MAX_NAAM_LENGTE = 50

_BAG_ID_PATROON = re.compile(r"\d{16,}")


class OngeldigeProjectnaam(Exception):
    """De naam-invoer komt niet door de naamconventie-poorten — zichtbare 400 naar vastgoed."""


def vorm_projectnaam(naam_invoer: str) -> str:
    """Definitieve projectnaam uit de aanvraag-invoer: whitespace genormaliseerd (splits/join —
    ook tabs/newlines), verder ongewijzigd. Poorten: niet leeg, geen BAG-id-achtige
    cijferreeks (§2.1), niet langer dan MAX_NAAM_LENGTE (weigeren, nooit stil afkappen)."""
    naam = " ".join(naam_invoer.split())
    if not naam:
        raise OngeldigeProjectnaam("naam_invoer is leeg")
    if _BAG_ID_PATROON.search(naam):
        raise OngeldigeProjectnaam(
            "naam_invoer bevat een 16-cijferige reeks (BAG-id?) — RLZ-projectnamen mogen geen "
            "BAG-id bevatten (koppelcontract §2.1); lever een naam zonder het BAG-id aan"
        )
    if len(naam) > MAX_NAAM_LENGTE:
        raise OngeldigeProjectnaam(
            f"naam_invoer is te lang ({len(naam)} tekens, maximum {MAX_NAAM_LENGTE}) — "
            "wij kappen nooit stil af"
        )
    return naam
