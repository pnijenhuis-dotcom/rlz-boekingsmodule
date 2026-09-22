"""Activa-instelling per administratie (migratie 0168, `boekhouding.activa_instelling`) — lezen mét defaults,
Beheerder-PUT
mét audit oud→nieuw, en de twee bron-lezers die de nachtelijke sync aanroept: `ververs_rlz_grens` (RLZ
`AdministrationSettings.FixedAssetAlertAmount`, bron wint als gevuld) en `probe_register` (`FixedAssets` leesbaar? 403 =
recht ontbreekt — zichtbaar, nooit stil).

Ontbreekt de rij, dan gelden de ontwerp-defaults (§8): opt-in UIT, grens € 450 excl., termijnen per categorie, geen
afschrijvingsrekeningen (de mens kiest op de kaart), probe onbekend. Autoboek-patroon: de opt-in
`automatisch_aanmaken_ingeschakeld` start UIT; guard-test op het afwezig-pad in tests/activa/test_service.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activa import categorie as cat
from app.activa import register
from app.activa.models import ActivaInstelling
from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.rlz.client import RlzApiError

logger = logging.getLogger(__name__)

SOORT_ACTIVA = 3


class OngeldigeInstelling(Exception):
    """Validatiefout in de PUT (422): grens < 0, termijn buiten 12..600/geen veelvoud van 12, onbekende categorie of
    onbekende afschrijvingsrekening."""


@dataclass(frozen=True)
class InstellingStand:
    """Effectieve stand — altijd gevuld, ook zonder DB-rij."""

    administratie_id: uuid.UUID
    automatisch_aanmaken_ingeschakeld: bool = False
    activeringsgrens: Decimal = cat.STANDAARD_GRENS
    grens_rlz: Decimal | None = None
    grens_rlz_gelezen_op: datetime | None = None
    termijnen: dict[str, int] = field(default_factory=dict)
    afschrijving_ledgers: dict[str, uuid.UUID] = field(default_factory=dict)
    register_leesbaar: bool | None = None
    register_geprobeerd_op: datetime | None = None
    register_fout: str | None = None

    @property
    def effectieve_grens(self) -> Decimal:
        return self.grens_rlz if self.grens_rlz is not None else self.activeringsgrens

    @property
    def grens_bron(self) -> str:
        return "rlz" if self.grens_rlz is not None else "instelling"

    def termijn_voor(self, categorie: str) -> int:
        return cat.termijn_voor(categorie, self.termijnen)

    def afschrijving_ledger_voor(self, categorie: str) -> uuid.UUID | None:
        return self.afschrijving_ledgers.get(categorie)


def _termijnen_uit(rij: dict | None) -> dict[str, int]:
    uit: dict[str, int] = {}
    for k, v in (rij or {}).items():
        try:
            uit[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return uit


def _ledgers_uit(rij: dict | None) -> dict[str, uuid.UUID]:
    uit: dict[str, uuid.UUID] = {}
    for k, v in (rij or {}).items():
        try:
            uit[str(k)] = uuid.UUID(str(v))
        except (TypeError, ValueError):
            continue
    return uit


def stand_uit_rij(administratie_id: uuid.UUID, rij: ActivaInstelling | None) -> InstellingStand:
    if rij is None:
        return InstellingStand(administratie_id=administratie_id)
    return InstellingStand(
        administratie_id=administratie_id,
        automatisch_aanmaken_ingeschakeld=bool(rij.automatisch_aanmaken_ingeschakeld),
        activeringsgrens=Decimal(rij.activeringsgrens).quantize(Decimal("0.01")),
        grens_rlz=Decimal(rij.grens_rlz).quantize(Decimal("0.01")) if rij.grens_rlz is not None else None,
        grens_rlz_gelezen_op=rij.grens_rlz_gelezen_op,
        termijnen=_termijnen_uit(rij.termijnen),
        afschrijving_ledgers=_ledgers_uit(rij.afschrijving_ledgers),
        register_leesbaar=rij.register_leesbaar,
        register_geprobeerd_op=rij.register_geprobeerd_op,
        register_fout=rij.register_fout,
    )


def lees_stand(session: Session, administratie_id: uuid.UUID) -> InstellingStand:
    return stand_uit_rij(administratie_id, session.get(ActivaInstelling, administratie_id))


def is_automatisch_ingeschakeld(session: Session, administratie_id: uuid.UUID) -> bool:
    """De poort van het autoboek-pad (b) in `service.verwerk_na_boeken` — leest uitsluitend deze vlag; geen eigenaar,
    geen toewijzing (geen stille no-op: een lege optionele voorwaarde bestaat hier niet)."""
    return lees_stand(session, administratie_id).automatisch_aanmaken_ingeschakeld


def _rij_of_nieuw(session: Session, administratie_id: uuid.UUID) -> ActivaInstelling:
    rij = session.get(ActivaInstelling, administratie_id)
    if rij is None:
        rij = ActivaInstelling(administratie_id=administratie_id)
        session.add(rij)
        session.flush()
    return rij


def mva_rekeningen(session: Session, administratie_id: uuid.UUID) -> list[Grootboekrekening]:
    return list(
        session.scalars(
            select(Grootboekrekening)
            .where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                Grootboekrekening.is_totaalrekening.is_(False),
                Grootboekrekening.is_activa.is_(True),
            )
            .order_by(Grootboekrekening.code)
        )
    )


def afschrijving_ledger_opties(session: Session, administratie_id: uuid.UUID) -> list[Grootboekrekening]:
    """Alle niet-verdwenen rekeningen soort 3 (activa) mét code 0xxx — "afschrijving" in de naam eerst, dan op code."""
    rijen = session.scalars(
        select(Grootboekrekening).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            Grootboekrekening.is_totaalrekening.is_(False),
            Grootboekrekening.soort == SOORT_ACTIVA,
            Grootboekrekening.code.startswith("0"),
        )
    ).all()
    return sorted(rijen, key=lambda r: (0 if "afschrijving" in (r.naam or "").lower() else 1, r.code))


def heeft_mva_rekeningen(session: Session, administratie_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(Grootboekrekening.ledger_id)
            .where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                Grootboekrekening.is_activa.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _als_grens(waarde: object) -> Decimal:
    try:
        grens = Decimal(str(waarde)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OngeldigeInstelling(f"activeringsgrens is geen bedrag: {waarde!r}") from exc
    if grens < 0:
        raise OngeldigeInstelling("activeringsgrens moet ≥ 0 zijn")
    return grens


def valideer(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    activeringsgrens: object,
    termijnen: dict,
    afschrijving_ledgers: dict,
) -> tuple[Decimal, dict[str, int], dict[str, str]]:
    grens = _als_grens(activeringsgrens)
    t_uit: dict[str, int] = {}
    for k, v in (termijnen or {}).items():
        if k not in cat.PER_CODE:
            raise OngeldigeInstelling(f"onbekende categorie in termijnen: {k!r}")
        if not cat.termijn_geldig(v):
            raise OngeldigeInstelling(f"termijn voor {k!r} moet 12..600 maanden zijn, veelvoud van 12 (kreeg {v!r})")
        t_uit[k] = int(v)
    l_uit: dict[str, str] = {}
    if afschrijving_ledgers:
        bekend = {
            r.ledger_id
            for r in session.scalars(
                select(Grootboekrekening).where(
                    Grootboekrekening.administratie_id == administratie_id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                )
            )
        }
        for k, v in afschrijving_ledgers.items():
            if k not in cat.PER_CODE:
                raise OngeldigeInstelling(f"onbekende categorie in afschrijving_ledgers: {k!r}")
            if v is None or v == "":
                continue
            try:
                lid = uuid.UUID(str(v))
            except ValueError as exc:
                raise OngeldigeInstelling(f"afschrijvingsrekening voor {k!r} is geen geldig id") from exc
            if lid not in bekend:
                raise OngeldigeInstelling(
                    f"afschrijvingsrekening {lid} voor {k!r} is geen rekening van deze administratie"
                )
            l_uit[k] = str(lid)
    return grens, t_uit, l_uit


def zet(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    automatisch_aanmaken_ingeschakeld: bool,
    activeringsgrens: object,
    termijnen: dict,
    afschrijving_ledgers: dict,
) -> InstellingStand:
    """Upsert (Beheerder) + audit `activa_instelling_gewijzigd` oud→nieuw. Validatie vóór het schrijven (422)."""
    grens, t_uit, l_uit = valideer(
        session,
        administratie_id=administratie_id,
        activeringsgrens=activeringsgrens,
        termijnen=termijnen,
        afschrijving_ledgers=afschrijving_ledgers,
    )
    rij = _rij_of_nieuw(session, administratie_id)
    oud = {
        "automatisch_aanmaken_ingeschakeld": bool(rij.automatisch_aanmaken_ingeschakeld),
        "activeringsgrens": str(rij.activeringsgrens),
        "termijnen": dict(rij.termijnen or {}),
        "afschrijving_ledgers": dict(rij.afschrijving_ledgers or {}),
    }
    rij.automatisch_aanmaken_ingeschakeld = bool(automatisch_aanmaken_ingeschakeld)
    rij.activeringsgrens = grens
    rij.termijnen = t_uit
    rij.afschrijving_ledgers = l_uit
    rij.gewijzigd_door = actor_id
    rij.gewijzigd_op = datetime.now(UTC)
    nieuw = {
        "automatisch_aanmaken_ingeschakeld": bool(automatisch_aanmaken_ingeschakeld),
        "activeringsgrens": str(grens),
        "termijnen": t_uit,
        "afschrijving_ledgers": l_uit,
    }
    if oud != nieuw:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="activa_instelling",
            record_id=administratie_id,
            actie="activa_instelling_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
    session.flush()
    return stand_uit_rij(administratie_id, rij)


def ververs_rlz_grens(session: Session, client, administratie_id: uuid.UUID) -> Decimal | None:  # noqa: ANN001
    """RLZ `AdministrationSettings.FixedAssetAlertAmount` → `grens_rlz` (None als het veld ontbreekt; dan geldt de
    instelling). Een leesfout laat de vorige waarde staan en wordt gelogd — de sync stopt er nooit op."""
    try:
        grens = register.lees_grens(client)
    except RlzApiError as exc:
        logger.warning(
            "activa: AdministrationSettings niet leesbaar voor %s: HTTP %s", administratie_id, exc.status_code
        )
        return None
    rij = _rij_of_nieuw(session, administratie_id)
    rij.grens_rlz = grens
    rij.grens_rlz_gelezen_op = datetime.now(UTC)
    session.flush()
    return grens


def probe_register(
    session: Session,
    client,  # noqa: ANN001
    administratie_id: uuid.UUID,
    *,
    schrijf: bool = True,
) -> bool:
    """Is `FixedAssets` leesbaar met deze login? Schrijft `register_leesbaar` + `register_fout` + tijdstip. Andere
    fouten dan 403 (netwerk, 500) worden als `register_fout` genoteerd zonder de leesbaar-stand te veranderen naar
    False (onbekend blijft onbekend als er nog niets gemeten was).

    `schrijf=False` (nameting 22-09): alleen de GET, niets in `activa_instelling` — de lees-only reconciliatie
    (`reconciliatie-alles --lees-only`) beloofde "niets vastgelegd" maar schreef tot 22-09 wél de probe-stand."""
    if not schrijf:
        try:
            client.get_fixed_assets(params={"$top": "1"})
        except RlzApiError as exc:
            if exc.status_code == 403:
                return False
            # andere fout: de opgeslagen stand (indien aanwezig) blijft leidend, onbekend = niet leesbaar
            return bool(lees_stand(session, administratie_id).register_leesbaar)
        return True
    rij = _rij_of_nieuw(session, administratie_id)
    rij.register_geprobeerd_op = datetime.now(UTC)
    try:
        client.get_fixed_assets(params={"$top": "1"})
    except RlzApiError as exc:
        if exc.status_code == 403:
            rij.register_leesbaar = False
            rij.register_fout = "recht ontbreekt (403) — RLZ-recht 'Vaste activa' op de webservice-login zetten"
        else:
            rij.register_fout = f"HTTP {exc.status_code} bij het lezen van FixedAssets"
        session.flush()
        return bool(rij.register_leesbaar)
    rij.register_leesbaar = True
    rij.register_fout = None
    session.flush()
    return True
