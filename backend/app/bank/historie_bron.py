"""Bron van de historie-regel: cache `bank_historie_boeking` (migratie 0129) vullen en lezen.

Twee bronnen, één tabel (zie `models.BankHistorieBoeking`):
- MODULE: eigen `bank_boeking` (status geboekt, volledige boeking — geen deel van een splitsing) mét de
  eerste regel (grootboek/btw). Altijd volledig bijgewerkt, goedkoop (lokale query).
- RLZ: afgeletterde mutaties in de eigen `bank_mutatie`-cache (open_bedrag == 0) die nog niet in de
  historie-cache staan → per mutatie `GET PaymentTransactions/{id}?$expand=PaymentReferenceList($expand=Document)`
  (api-verkenning "Bankmodule schrijf-PoC" §5) en, als de koppeling naar een BankMutationDirectBooking
  (DocumentType 19, Status ≠ 1, niet IsSystemGenerated) wijst, `GET BankMutationDirectBookings/{id}` voor de
  regels. Géén GET-storm: max `MAX_RLZ_LEZINGEN_PER_RUN` per sync-run, de rest volgt de volgende nacht (telling in
  `HistorieVulling`); de eerste vulling ≥ 6 maanden terug is de CLI `bank-historie-backfill` (app/bank/cli_cmd.py).
  Een mutatie zonder grootboekboeking (afgeletterd tegen een factuur/aanbetaling) of met meer dan één rekening
  krijgt een MARKERINGSRIJ (`ledger_id NULL`, bron `rlz_geen_grootboek` / `rlz_gesplitst`) zodat ze nooit
  opnieuw opgehaald wordt. Nooit iets verwijderen; RLZ blijft de bron van waarheid — dit is een cache.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.bank.historie_regel import BRON_MODULE, BRON_RLZ, HistorieBoeking
from app.bank.models import (
    BankBoeking,
    BankBoekingRegel,
    BankBoekingStatus,
    BankHistorieBoeking,
    BankMutatie,
)
from app.db.session import scoped_session
from app.rlz.client import RlzApiError, RlzClient

logger = logging.getLogger(__name__)

BRON_RLZ_GEEN_GROOTBOEK = "rlz_geen_grootboek"
BRON_RLZ_GESPLITST = "rlz_gesplitst"

#: Maximaal aantal afgeletterde mutaties dat één sync-run bij RLZ naleest (1–2 GET's per mutatie).
MAX_RLZ_LEZINGEN_PER_RUN = 40
#: Hoe ver terug de vulling kijkt (ruim boven de 183-dagen-dekking van de regel; zelfde venster als `rlz_dubbel`).
HISTORIE_VENSTER_DAGEN = 400
#: BankMutationDirectBooking (schrijf-PoC §3: reeks RLZ-07).
_DOCUMENTTYPE_BMDB = 19


@dataclass(frozen=True)
class HistorieVulling:
    module_toegevoegd: int
    rlz_toegevoegd: int
    rlz_gemarkeerd: int
    rlz_resterend: int  # nog niet nagelezen afgeletterde mutaties (volgende run)
    fouten: list[str]


def _uuid(waarde: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _bestaande_mutatie_ids(session, *, administratie_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(BankHistorieBoeking.payment_transaction_id).where(
                BankHistorieBoeking.administratie_id == administratie_id
            )
        )
    )


def _vul_module(session, *, administratie_id: uuid.UUID, bestaand: set[uuid.UUID]) -> int:
    """Eigen geboekte, volledige bankboekingen → cache (bron 'module'). Idempotent op mutatie-id."""
    boekingen = list(
        session.scalars(
            select(BankBoeking).where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                BankBoeking.deel_id.is_(None),
                BankBoeking.payment_transaction_id.not_in(bestaand or [uuid.UUID(int=0)]),
            )
        )
    )
    if not boekingen:
        return 0
    regels = list(
        session.scalars(
            select(BankBoekingRegel)
            .where(BankBoekingRegel.bank_boeking_id.in_([b.id for b in boekingen]))
            .order_by(BankBoekingRegel.bank_boeking_id, BankBoekingRegel.volgnummer)
        )
    )
    eerste_regel: dict[uuid.UUID, BankBoekingRegel] = {}
    rekeningen_per_boeking: dict[uuid.UUID, set[tuple]] = {}
    for regel in regels:
        eerste_regel.setdefault(regel.bank_boeking_id, regel)
        rekeningen_per_boeking.setdefault(regel.bank_boeking_id, set()).add((regel.ledger_id, regel.taxrate_id))
    toegevoegd = 0
    for boeking in boekingen:
        regel = eerste_regel.get(boeking.id)
        if regel is None or len(rekeningen_per_boeking.get(boeking.id, ())) != 1:
            continue  # zonder regels of over meerdere rekeningen: geen eenduidige historie
        mutatie = session.get(BankMutatie, (boeking.payment_transaction_id, administratie_id))
        session.add(
            BankHistorieBoeking(
                administratie_id=administratie_id,
                payment_transaction_id=boeking.payment_transaction_id,
                datum=(mutatie.boekdatum if mutatie is not None else None) or boeking.geboekt_op.date(),
                tegenrekening_iban=mutatie.tegenrekening_iban if mutatie is not None else None,
                omschrijving=mutatie.omschrijving if mutatie is not None else None,
                tegenpartij_naam=mutatie.tegenpartij_naam if mutatie is not None else None,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                bron=BRON_MODULE,
            )
        )
        bestaand.add(boeking.payment_transaction_id)
        toegevoegd += 1
    return toegevoegd


def _rlz_grootboek_van_mutatie(client: RlzClient, mutatie_id: uuid.UUID) -> tuple[str, list[tuple]]:
    """(bron, [(ledger_id, taxrate_id), …]) uit de PaymentReferenceList van één afgeletterde mutatie."""
    vers = client.get_payment_transaction(mutatie_id, expand="PaymentReferenceList($expand=Document)")
    documenten = [
        ref.get("Document") or {}
        for ref in vers.get("PaymentReferenceList") or []
        if (ref.get("Document") or {}).get("DocumentType") == _DOCUMENTTYPE_BMDB
        and (ref.get("Document") or {}).get("Status") != 1
        and not (ref.get("Document") or {}).get("IsSystemGenerated")
    ]
    if not documenten:
        return BRON_RLZ_GEEN_GROOTBOEK, []
    rekeningen: set[tuple] = set()
    for document in documenten:
        doc_id = _uuid(document.get("id"))
        if doc_id is None:
            continue
        detail = client.get_bank_mutation_direct_booking(doc_id)
        for line in detail.get("DocumentLineList") or []:
            ledger_id = _uuid((line.get("Account") or {}).get("id"))
            if ledger_id is None:
                continue
            rekeningen.add((ledger_id, _uuid((line.get("TaxRate") or {}).get("id"))))
    if not rekeningen:
        return BRON_RLZ_GEEN_GROOTBOEK, []
    if len(rekeningen) > 1:
        return BRON_RLZ_GESPLITST, []
    return BRON_RLZ, sorted(rekeningen, key=str)


def vul_historie_cache(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient | None,
    max_rlz_lezingen: int = MAX_RLZ_LEZINGEN_PER_RUN,
    vandaag: date | None = None,
) -> HistorieVulling:
    """Incrementele vulling (bank-sync) én backfill (CLI, hogere `max_rlz_lezingen`). `client=None` = alleen de
    module-bron (geen RLZ-verbinding — zichtbaar in de telling, geen fout)."""
    vandaag = vandaag or datetime.now(UTC).date()
    vanaf = vandaag - timedelta(days=HISTORIE_VENSTER_DAGEN)
    fouten: list[str] = []

    with scoped_session(administratie_id) as session:
        bestaand = _bestaande_mutatie_ids(session, administratie_id=administratie_id)
        module_toegevoegd = _vul_module(session, administratie_id=administratie_id, bestaand=bestaand)
        kandidaten = list(
            session.scalars(
                select(BankMutatie)
                .where(
                    BankMutatie.administratie_id == administratie_id,
                    BankMutatie.open_bedrag == 0,
                    BankMutatie.boekdatum >= vanaf,
                    BankMutatie.id.not_in(bestaand or [uuid.UUID(int=0)]),
                )
                .order_by(BankMutatie.boekdatum.desc())
            )
        )
        te_lezen = [(m.id, m.boekdatum, m.tegenrekening_iban, m.omschrijving, m.tegenpartij_naam) for m in kandidaten]

    if client is None:
        return HistorieVulling(module_toegevoegd, 0, 0, len(te_lezen), fouten)

    rlz_toegevoegd = rlz_gemarkeerd = 0
    batch = te_lezen[:max_rlz_lezingen]
    for mutatie_id, boekdatum, iban, omschrijving, naam in batch:
        try:
            bron, rekeningen = _rlz_grootboek_van_mutatie(client, mutatie_id)
        except RlzApiError as exc:
            fouten.append(f"{mutatie_id}: {exc}")
            logger.warning("Historie-cache %s: RLZ-lezing mutatie %s mislukt: %s", administratie_id, mutatie_id, exc)
            continue
        with scoped_session(administratie_id) as session:
            if bron == BRON_RLZ:
                ledger_id, taxrate_id = rekeningen[0]
                session.add(
                    BankHistorieBoeking(
                        administratie_id=administratie_id,
                        payment_transaction_id=mutatie_id,
                        datum=boekdatum,
                        tegenrekening_iban=iban,
                        omschrijving=omschrijving,
                        tegenpartij_naam=naam,
                        ledger_id=ledger_id,
                        taxrate_id=taxrate_id,
                        bron=BRON_RLZ,
                    )
                )
                rlz_toegevoegd += 1
            else:
                session.add(
                    BankHistorieBoeking(
                        administratie_id=administratie_id,
                        payment_transaction_id=mutatie_id,
                        datum=boekdatum,
                        tegenrekening_iban=iban,
                        omschrijving=omschrijving,
                        tegenpartij_naam=naam,
                        ledger_id=None,
                        taxrate_id=None,
                        bron=bron,
                    )
                )
                rlz_gemarkeerd += 1
    return HistorieVulling(
        module_toegevoegd=module_toegevoegd,
        rlz_toegevoegd=rlz_toegevoegd,
        rlz_gemarkeerd=rlz_gemarkeerd,
        rlz_resterend=max(0, len(te_lezen) - len(batch)),
        fouten=fouten,
    )


def historie_voor(session, *, administratie_id: uuid.UUID) -> list[HistorieBoeking]:
    """Alle bruikbare historie-boekingen (markeringsrijen uitgesloten) als motor-invoer."""
    rijen = session.scalars(
        select(BankHistorieBoeking).where(
            BankHistorieBoeking.administratie_id == administratie_id,
            BankHistorieBoeking.ledger_id.isnot(None),
            BankHistorieBoeking.datum.isnot(None),
        )
    )
    return [
        HistorieBoeking(
            payment_transaction_id=rij.payment_transaction_id,
            datum=rij.datum,
            tegenrekening_iban=rij.tegenrekening_iban,
            omschrijving=rij.omschrijving,
            tegenpartij_naam=rij.tegenpartij_naam,
            ledger_id=rij.ledger_id,
            taxrate_id=rij.taxrate_id,
            bron=rij.bron,
        )
        for rij in rijen
        if rij.ledger_id is not None and rij.datum is not None
    ]
