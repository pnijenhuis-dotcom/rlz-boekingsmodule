"""Volumerem — ÉÉN helper voor álle boekpaden (SPOED Peter 18-09, "Dagelijkse limiet van 20 boekingen bereikt").

Regel (bindend, `docs/regels/autoboeken-ai.md`, BESLISSINGEN "VOLUMEREM — ALLEEN AUTOMATISCH (Peter 18-09)"):
1. De 20/dag-rem (`settings.max_boekingen_per_dag_per_administratie`) geldt UITSLUITEND voor automatische boekingen —
   autoboek-opt-ins, autoboek-kandidaten-activering, bank-auto-afletteren/-boeken, verkoop/Vastly-autoboek, omzet-auto,
   waarborg via systeem-actor, doorbelasting-spiegel uit een automatische bron. Teller = alleen overgangen → geboekt mét
   de 'automatisch'-markering (`automatisch_geboekt` in het tijdlijn-detail; bank: `geboekt_door` = systeem-actor).
2. Handmatig boeken (kantoor-actor op de knop, incl. bulk) krijgt een eigen HOGE noodrem
   `settings.max_handmatige_boekingen_per_dag_per_administratie` (500, env-overschrijfbaar) — dat is nog steeds een
   noodrem tegen een runaway, geen bedrijfsvoeringslimiet.
3. Boekingen ná een compleet klant-akkoord (punt 23, 28-08) vallen sinds 18-09 onder DEZELFDE 500-noodrem als
   handmatig (één mens-teller: alle niet-automatische overgangen) — eenvoudigste vorm, de 200-setting is vervallen.
4. Élke melding noemt de rem, de teller én de handeling — nooit alleen "limiet bereikt".

Puur: geen DB-writes, geen LLM. De tellers zijn per boekpad (documenten / bank / doorbelasting) omdat elke geldstroom zijn
eigen tabel heeft; de limiet en de melding komen uit deze ene module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.tijd import TIJDZONE_NL, vandaag_nl

Herkomst = Literal["mens", "automatisch", "na_klant_akkoord"]

MENS: Herkomst = "mens"
AUTOMATISCH: Herkomst = "automatisch"
NA_KLANT_AKKOORD: Herkomst = "na_klant_akkoord"

#: Tijdlijn-/overgangsdetail-sleutel die een automatische boeking markeert (bestaand sinds 2026-08-09,
#: `documenten/autoboeken.py`, `omzet/autoboeken.py`, `verkoop/autoboeken.py`, `bank/boeken.py` bron automatisch).
AUTOMATISCH_MARKERING = "automatisch_geboekt"


class VolumeremBereikt(Exception):
    """Basisfout van de helper. De boekpaden hebben hun eigen subklasse (documenten `boeken.VolumeremBereikt`,
    bank `BankVolumeremBereikt`) — `toets()` raise-t het type dat de aanroeper meegeeft, zodat bestaande
    except-clauses en routers ongewijzigd blijven."""


@dataclass(frozen=True)
class Stand:
    herkomst: Herkomst
    teller: int
    limiet: int
    soort: str = "boekingen"

    @property
    def bereikt(self) -> bool:
        return self.teller >= self.limiet

    @property
    def melding(self) -> str:
        return melding(herkomst=self.herkomst, teller=self.teller, limiet=self.limiet, soort=self.soort)


def bepaal_herkomst(
    *,
    actor_id: uuid.UUID | None,
    overgang_detail: dict | None = None,
    na_klant_akkoord: bool = False,
) -> Herkomst:
    """Herkomst van een boekpoging, nooit geraden: (1) compleet klant-akkoord in deze gang → `na_klant_akkoord`;
    (2) de 'automatisch'-markering in het overgangsdetail → `automatisch`; (3) de systeem-actor zonder markering is
    óók automatisch (er zat geen mens op de knop) — een pad zonder markering hoort die markering alsnog te krijgen,
    maar telt nooit als mens; (4) anders `mens`."""
    if na_klant_akkoord:
        return NA_KLANT_AKKOORD
    if overgang_detail and overgang_detail.get(AUTOMATISCH_MARKERING):
        return AUTOMATISCH
    if actor_id is not None and actor_id == SYSTEEM_ACTOR_ID:
        return AUTOMATISCH
    return MENS


def is_automatisch(herkomst: Herkomst) -> bool:
    return herkomst == AUTOMATISCH


def limiet_voor(herkomst: Herkomst) -> int:
    if is_automatisch(herkomst):
        return settings.max_boekingen_per_dag_per_administratie
    return settings.max_handmatige_boekingen_per_dag_per_administratie


def env_naam_voor(herkomst: Herkomst) -> str:
    """De env-var waarmee de Beheerder de rem voor déze herkomst zet (herstel-CLI-tekst)."""
    if is_automatisch(herkomst):
        return "MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE"
    return "MAX_HANDMATIGE_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE"


def melding(*, herkomst: Herkomst, teller: int, limiet: int, soort: str = "boekingen") -> str:
    """Regel 4: rem + teller + handeling. De reconciliatie (`automatiseringen.classificeer_reden`) herkent
    'volumerem' → categorie VOLUMEREM (actiemail) en 'noodrem' → NOODREM (LET-OP) — de woorden hieronder zijn
    dus onderdeel van het contract."""
    if is_automatisch(herkomst):
        return (
            f"Volumerem automatisch boeken: {teller} van {limiet} automatische {soort} vandaag in deze "
            "administratie · handmatig boeken kan gewoon door"
        )
    if herkomst == NA_KLANT_AKKOORD:
        return (
            f"Noodrem ná klant-akkoord: {teller} van {limiet} handmatige {soort} (incl. boekingen ná klant-akkoord) "
            "vandaag in deze administratie — neem contact op met de Beheerder"
        )
    return (
        f"Noodrem: {teller} van {limiet} handmatige {soort} vandaag in deze administratie — "
        "neem contact op met de Beheerder"
    )


def stand(*, herkomst: Herkomst, teller: int, extra: int = 0, soort: str = "boekingen") -> Stand:
    """`extra` = het aantal boekingen dat deze gang nog gaat doen (doorbelasting: één per doelentiteit) — de rem
    toetst teller + extra > limiet als 'zou overschreden worden'."""
    return Stand(herkomst=herkomst, teller=teller + extra, limiet=limiet_voor(herkomst), soort=soort)


def toets(
    session: Session,
    administratie_id: uuid.UUID,
    *,
    herkomst: Herkomst,
    teller: int,
    extra: int = 0,
    soort: str = "boekingen",
    fout: type[Exception] = VolumeremBereikt,
) -> Stand:
    """Dé toets: raise-t `fout(melding)` zodra de rem voor déze herkomst bereikt is; geeft anders de stand terug.
    `session`/`administratie_id` zijn de context (voor de leesbaarheid van de aanroep en latere audit); het tellen
    doet de aanroeper met `documentboekingen_vandaag`/`bankboekingen_vandaag` of een eigen teller — elke geldstroom
    telt zijn eigen tabel, maar de rem staat op één plek."""
    del session, administratie_id  # context-parameters; de tellers zijn al per pad geteld
    s = stand(herkomst=herkomst, teller=teller, extra=extra, soort=soort)
    if extra:
        if s.teller > s.limiet:
            raise fout(s.melding.replace("vandaag", "vandaag (deze gang meegeteld)", 1))
        return s
    if s.bereikt:
        raise fout(s.melding)
    return s


def _vandaag_begin() -> datetime:
    return datetime.combine(vandaag_nl(), time.min, tzinfo=TIJDZONE_NL)


def documentboekingen_vandaag(session: Session, *, administratie_id: uuid.UUID, herkomst: Herkomst) -> int:
    """Teller documenten (inkoop/omzet/verkoop/waarborg — alle documentsoorten delen de tijdlijn): alleen ÉCHTE
    statusovergangen niet-geboekt → geboekt vandaag (teller-bug punt 23, 28-08, blijft gefixt), gesplitst op de
    'automatisch'-markering in het overgangsdetail: `automatisch` telt alleen gemarkeerde overgangen, `mens` en
    `na_klant_akkoord` tellen alle NIET-gemarkeerde."""
    from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus

    markering = DocumentGebeurtenis.detail[AUTOMATISCH_MARKERING].as_boolean()
    if is_automatisch(herkomst):
        herkomst_filter = markering.is_(True)
    else:
        herkomst_filter = or_(DocumentGebeurtenis.detail.is_(None), markering.is_not(True))
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .join(Document, DocumentGebeurtenis.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                or_(
                    DocumentGebeurtenis.van_status.is_(None),
                    DocumentGebeurtenis.van_status != DocumentStatus.GEBOEKT,
                ),
                DocumentGebeurtenis.tijdstip >= _vandaag_begin(),
                herkomst_filter,
            )
        )
        or 0
    )


def toets_documentboekingen(
    session: Session,
    administratie_id: uuid.UUID,
    *,
    herkomst: Herkomst,
    fout: type[Exception] = VolumeremBereikt,
) -> Stand:
    """Documenten-boekpaden (inkoop, omzet, verkoop, waarborg): tellen + toetsen in één aanroep."""
    return toets(
        session,
        administratie_id,
        herkomst=herkomst,
        teller=documentboekingen_vandaag(session, administratie_id=administratie_id, herkomst=herkomst),
        fout=fout,
    )


def bankboekingen_vandaag(session: Session, *, administratie_id: uuid.UUID, herkomst: Herkomst) -> int:
    """Teller bank (direct-op-grootboek + relatie-/aanbetalingsboekingen samen, zoals vóór 18-09): automatisch =
    `geboekt_door` systeem-actor, mens = elke andere actor."""
    from app.bank.models import BankBoeking, BankRelatieBoeking

    def _filter(kolom):
        return kolom == SYSTEEM_ACTOR_ID if is_automatisch(herkomst) else kolom != SYSTEEM_ACTOR_ID

    begin = _vandaag_begin()
    direct = (
        session.scalar(
            select(func.count())
            .select_from(BankBoeking)
            .where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.geboekt_op >= begin,
                _filter(BankBoeking.geboekt_door),
            )
        )
        or 0
    )
    relatie_kolom = getattr(BankRelatieBoeking, "geboekt_door", None)
    relatie_query = (
        select(func.count())
        .select_from(BankRelatieBoeking)
        .where(BankRelatieBoeking.administratie_id == administratie_id, BankRelatieBoeking.geboekt_op >= begin)
    )
    if relatie_kolom is not None:
        relatie_query = relatie_query.where(_filter(relatie_kolom))
    elif is_automatisch(herkomst):
        # Relatieboekingen kennen geen automatisch pad (altijd een mens op de knop) — tellen niet als automatisch.
        return direct
    relatie = session.scalar(relatie_query) or 0
    return direct + relatie


def toets_bankboekingen(
    session: Session,
    administratie_id: uuid.UUID,
    *,
    herkomst: Herkomst,
    fout: type[Exception] = VolumeremBereikt,
) -> Stand:
    return toets(
        session,
        administratie_id,
        herkomst=herkomst,
        teller=bankboekingen_vandaag(session, administratie_id=administratie_id, herkomst=herkomst),
        soort="bankboekingen",
        fout=fout,
    )
