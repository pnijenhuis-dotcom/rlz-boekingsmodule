from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.config import settings
from app.db.session import scoped_session
from app.geheugen.models import BoekingObservatie, ObservatieBron, seed_observatie_id
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

# Seed-bron vastgesteld (Peter, 2026-07-13): GET PurchaseInvoices + /Lines per factuur — NIET
# JournalEntries (die missen de crediteur op regelniveau, geneste Entity-expand wordt genegeerd,
# en de collectie bleek jaren achter te lopen; bewaard voor memoriaal/bank-historie later, zie
# docs/BOUWPLAN.md). N+1 Lines-calls: bedoeld als achtergrond-batch (CLI/Cloud Run job), de
# RlzClient-throttling (retry/backoff + Retry-After) houdt het binnen de limieten. Idempotent en
# hervatbaar: deterministische observatie-id per RLZ-regel + commit per factuur — een afgebroken
# run kan gewoon opnieuw gestart worden en slaat bestaande observaties over.

_PAGINA_GROOTTE = 100


@dataclass(frozen=True)
class SeedRapport:
    administratie_id: uuid.UUID
    aantal_facturen_bekeken: int
    aantal_facturen_geseed: int
    observaties_nieuw: int
    observaties_bestonden_al: int
    overgeslagen_zonder_entity: int
    overgeslagen_zonder_bruikbare_regels: int


def _ref_id(waarde: object) -> uuid.UUID | None:
    """id uit een geëxpandeerde referentie ({'id': ...}) — defensief: None bij alles wat geen
    geldige UUID draagt (RLZ laat lege refs soms helemaal weg, soms als leeg object)."""
    if not isinstance(waarde, dict):
        return None
    ruw = waarde.get("id")
    if not ruw:
        return None
    try:
        return uuid.UUID(str(ruw))
    except ValueError:
        return None


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _facturen(client: RlzClient, *, vanaf: date) -> list[dict]:
    """Alle inkoopfacturen vanaf de recency-cap, gepagineerd. Server-side datumfilter
    (zelfde literal-vorm als geverifieerd op JournalEntries.BookDate)."""
    facturen: list[dict] = []
    skip = 0
    while True:
        batch = client.get(
            "PurchaseInvoices",
            params={
                "$filter": f"Date ge {vanaf.isoformat()}",
                "$expand": "Entity",
                "$top": str(_PAGINA_GROOTTE),
                "$skip": str(skip),
            },
        ).get("value", [])
        facturen.extend(batch)
        if len(batch) < _PAGINA_GROOTTE:
            return facturen
        skip += _PAGINA_GROOTTE


def _seed_factuur(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient,
    factuur: dict,
    vendor_id: uuid.UUID,
    factuurdatum: date,
) -> tuple[int, int, bool]:
    """(nieuw, bestond al, had bruikbare regels) voor één factuur — eigen transactie per factuur,
    zodat een afgebroken batch niets half achterlaat en een her-run daar verder gaat."""
    lines = client.get_lines("PurchaseInvoices", factuur["id"], expand="Account,TaxRate,Project")
    boekstuk_ref = factuur.get("ReceiptNumber") or factuur.get("Reference")
    nieuw = 0
    bestond_al = 0
    bruikbaar = False
    with scoped_session(administratie_id) as session:
        for line in lines:
            gb_id = _ref_id(line.get("Account"))
            if gb_id is None or not line.get("id"):
                continue  # regel zonder GB (bv. totaalregel) is geen observatie
            bruikbaar = True
            observatie_id = seed_observatie_id(administratie_id, line["id"])
            if session.get(BoekingObservatie, observatie_id) is not None:
                bestond_al += 1
                continue
            omschrijving = line.get("Description") or None
            session.add(
                BoekingObservatie(
                    id=observatie_id,
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    regel_sleutel=normaliseer_regel_sleutel(omschrijving),
                    regel_omschrijving_raw=omschrijving,
                    gb_id=gb_id,
                    btw_id=_ref_id(line.get("TaxRate")),
                    project_id=_ref_id(line.get("Project")),
                    bron=ObservatieBron.RLZ_SEED.value,
                    bron_datum=factuurdatum,
                    boekstuk_ref=boekstuk_ref,
                )
            )
            nieuw += 1
    return nieuw, bestond_al, bruikbaar


def seed_boekingsgeheugen(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient | None = None,
    maanden: int | None = None,
    vandaag: date | None = None,
) -> SeedRapport:
    """RLZ-seed van het boekingsgeheugen voor één administratie (bron='rlz_seed', bron_datum =
    factuurdatum). Alleen inkoopdocumenten; facturen zonder bruikbare Entity of regels worden
    geteld overgeslagen — nooit stil. Logt uitsluitend aantallen en id's, nooit omschrijvingen."""
    maanden = maanden if maanden is not None else settings.boekingsgeheugen_seed_maanden
    vandaag = vandaag or datetime.now(UTC).date()
    vanaf = vandaag - timedelta(days=maanden * 31)

    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        facturen = _facturen(client, vanaf=vanaf)
        nieuw_totaal = 0
        bestond_totaal = 0
        geseed = 0
        zonder_entity = 0
        zonder_regels = 0
        for factuur in facturen:
            vendor_id = _ref_id(factuur.get("Entity"))
            factuurdatum = _als_datum(factuur.get("Date")) or vanaf
            if vendor_id is None:
                zonder_entity += 1
                continue
            nieuw, bestond_al, bruikbaar = _seed_factuur(
                administratie_id=administratie_id,
                client=client,
                factuur=factuur,
                vendor_id=vendor_id,
                factuurdatum=factuurdatum,
            )
            if not bruikbaar:
                zonder_regels += 1
                continue
            geseed += 1
            nieuw_totaal += nieuw
            bestond_totaal += bestond_al
        rapport = SeedRapport(
            administratie_id=administratie_id,
            aantal_facturen_bekeken=len(facturen),
            aantal_facturen_geseed=geseed,
            observaties_nieuw=nieuw_totaal,
            observaties_bestonden_al=bestond_totaal,
            overgeslagen_zonder_entity=zonder_entity,
            overgeslagen_zonder_bruikbare_regels=zonder_regels,
        )
        logger.info(
            "Boekingsgeheugen-seed %s: %s facturen bekeken, %s geseed, %s nieuwe observaties, "
            "%s bestonden al, %s zonder entity, %s zonder bruikbare regels",
            administratie_id,
            rapport.aantal_facturen_bekeken,
            rapport.aantal_facturen_geseed,
            rapport.observaties_nieuw,
            rapport.observaties_bestonden_al,
            rapport.overgeslagen_zonder_entity,
            rapport.overgeslagen_zonder_bruikbare_regels,
        )
        return rapport
    finally:
        if eigen_client:
            client.close()
