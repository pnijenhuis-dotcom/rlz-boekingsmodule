"""Bank-leeskant: sync van PaymentAccounts, PaymentTransactions en PaymentItems per
administratie (verkenning/api-verkenning.md "Bankmodule STAP 0" — Reeleezee lezen, géén eigen
CAMT.053/MT940-import; optie-2-besluit).

Drie leesbronnen + de vervolgstappen die van verse data afhangen, in één run:
1. rekeningen (incl. kas Type 3) + versheid-probe LastBankImport (onboarding-check),
2. mutaties — incrementeel op CreateDate (pakt ook laat binnengekomen mutaties met een oudere
   boekdatum) + een verversronde over alle lokaal-nog-open mutaties (het open bedrag van een
   bestaande rij verandert wanneer er in RLZ afgeletterd wordt; ⚠️ altijd OpenAmount, nooit
   IsComplete — stale na storno, schrijf-PoC §6),
3. open posten (PaymentItems),
4. verificatie van klaargezette afletter-opdrachten (assist-model, app/bank/afletteren.py),
5. Vastly-terugkoppeling "factuur afgeletterd" (app/bank/vastly.py, alleen vastgoed-admins),
6. opt-in: vaste regels automatisch boeken (app/bank/boeken.py, alleen bij
   administratie.bank_autoboeken_ingeschakeld + de boeken-failsafes).

De caches dragen geen werkstaat (die leeft in eigen tabellen) — een upsert mag een cache-rij
dus altijd volledig overschrijven. Mutatie-rijen worden nooit als verdwenen gemarkeerd of
verwijderd (incrementele bron; RLZ's DELETE-route gebruiken we nooit, kernprincipe 3)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.bank import afletteren, vastly
from app.bank.models import BankMutatie, BankSyncStand, PaymentAccountCache, PaymentItemCache
from app.db.models import Administratie
from app.db.session import scoped_session
from app.rlz.client import RlzClient
from app.sync.service import (
    SyncFout,
    SyncTelling,
    _open_client_indien_nodig,
    _upsert_en_markeer_verdwenen,
)

logger = logging.getLogger(__name__)

# Batchgrootte voor de incrementele mutatie-sync: geverifieerde OData-parameters zijn $filter/
# $orderby/$top (STAP 0) — bewust géén $skip (nooit geverifieerd); de lus schuift de
# CreateDate-watermark zelf op en ontdubbelt op id (ge-filter overlapt de laatste rij).
_MUTATIE_BATCH = 500


def _decimal(waarde: Any) -> Decimal | None:
    return Decimal(str(waarde)) if waarde is not None else None


def _datum(waarde: Any) -> date | None:
    """RLZ-datums komen als ISO-(datetime-)string; alleen het datumdeel is relevant."""
    return date.fromisoformat(str(waarde)[:10]) if waarde else None


def _uuid_of_none(waarde: Any) -> uuid.UUID | None:
    return uuid.UUID(str(waarde)) if waarde else None


def _tijdstip(waarde: Any) -> datetime | None:
    """RLZ-datetimes komen zonder timezone-aanduiding; als UTC interpreteren zodat ze
    vergelijkbaar zijn met onze timestamptz-watermark (zelfde bron, dus consistent)."""
    if not waarde:
        return None
    parsed = datetime.fromisoformat(str(waarde))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _nav_id(record: dict[str, Any], veld: str) -> uuid.UUID | None:
    nav = record.get(veld)
    if isinstance(nav, dict) and nav.get("id"):
        return uuid.UUID(str(nav["id"]))
    return None


@dataclass(frozen=True)
class MutatieSyncTelling:
    aangemaakt: int
    bijgewerkt: int
    open_ververst: int


@dataclass(frozen=True)
class BankSyncResultaat:
    rekeningen: SyncTelling
    mutaties: MutatieSyncTelling
    open_posten: SyncTelling
    afletteren_geverifieerd: int
    vastly_gemeld: int
    automatisch_geboekt: int
    automatisch_fouten: list[str]
    # Voorstel-volgorde stap 1, écht automatisch sinds de seam-swap (capture-replay
    # 2026-08-09) — zelfde opt-in als het vaste-regels-autoboeken, eigen volumerem-teller.
    automatisch_afgeletterd: int = 0
    afletter_fouten: list[str] = field(default_factory=list)


# --- 1. rekeningen ---------------------------------------------------------------------------

# PaymentAccountTypes waarop een bankaanlevering aantoonbaar niet kán bestaan (live geverifieerd
# 2026-08-08, api-verkenning.md "LastBankImport per rekeningtype"): kas (3), verrekeningen (4)
# en RC/privé (5) geven altijd `400 _InvalidData` op de probe. Overige types (ook onbekende)
# worden wél geprobed — de client vertaalt 400 _InvalidData daar zelf naar None.
_REKENING_TYPES_ZONDER_AANLEVERPAD = {3, 4, 5}


@dataclass(frozen=True)
class _ProbeMislukt:
    """Versheid-probe faalde (failsafe kliktest-fix 2026-08-08): de fout wordt zichtbaar op de
    rekening-rij gezet en de rest van de sync draait door — een kapotte probe mag nooit de hele
    administratie-sync afbreken. De bestaande `laatste_import` blijft staan (stale versheid is
    informatiever dan geen)."""

    fout: str


def _account_waarden(
    record: dict[str, Any], laatste_imports: dict[uuid.UUID, dict | None | _ProbeMislukt]
) -> dict[str, Any]:
    record_id = uuid.UUID(str(record["id"]))
    waarden: dict[str, Any] = {
        "naam": record.get("Name") or record.get("Description"),
        "iban": record.get("IBAN"),
        "rekening_type": record.get("Type"),
        "saldo": _decimal(record.get("CurrentBalance")),
        "saldo_datum": _datum(record.get("LastBalanceDate")),
        "is_gearchiveerd": record.get("IsArchived"),
        "gateway_state": record.get("BankGatewayState"),
        "gateway_type": record.get("BankGatewayType"),
        "brondata": record,
    }
    probe = laatste_imports.get(record_id)
    if isinstance(probe, _ProbeMislukt):
        # `laatste_import` bewust weglaten: een bestaande rij houdt zijn laatst-bekende
        # versheid (een nieuwe rij start op de kolom-default NULL).
        waarden["laatste_import_probe_fout"] = probe.fout
    else:
        waarden["laatste_import"] = probe
        waarden["laatste_import_probe_fout"] = None
    return waarden


def sync_payment_accounts(*, administratie_id: uuid.UUID, client: RlzClient) -> SyncTelling:
    accounts = client.list_payment_accounts()

    # Versheid-probe per rekening (STAP 0 §3) — None = nooit een aanlevering gezien, dat is
    # juist het onboarding-signaal, geen fout. Alleen proben waar een aanlevering kán bestaan:
    # niet-gearchiveerd (gearchiveerd geeft 400) én geen kas/verrekeningen/RC-type.
    laatste_imports: dict[uuid.UUID, dict | None | _ProbeMislukt] = {}
    for record in accounts:
        record_id = uuid.UUID(str(record["id"]))
        if record.get("IsArchived") or record.get("Type") in _REKENING_TYPES_ZONDER_AANLEVERPAD:
            laatste_imports[record_id] = None
            continue
        try:
            laatste_imports[record_id] = client.get_last_bank_import(record_id)
        except Exception as exc:  # noqa: BLE001 — failsafe: één kapotte probe mag de sync niet afbreken
            logger.warning(
                "Bank-sync %s: versheid-probe mislukt voor rekening %s (Type=%s) — rekening "
                "gemarkeerd, sync draait door: %s",
                administratie_id,
                record_id,
                record.get("Type"),
                exc,
            )
            laatste_imports[record_id] = _ProbeMislukt(fout=str(exc))

    now = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        return _upsert_en_markeer_verdwenen(
            session,
            model=PaymentAccountCache,
            id_kolom="id",
            administratie_id=administratie_id,
            verse_rijen=accounts,
            kolom_waarden=lambda record: _account_waarden(record, laatste_imports),
            now=now,
        )


# --- 2. mutaties (incrementeel + open-ververs) -------------------------------------------------


def _mutatie_waarden(record: dict[str, Any]) -> dict[str, Any]:
    create_date = record.get("CreateDate")
    return {
        "payment_account_id": _nav_id(record, "PaymentAccount"),
        "boekdatum": _datum(record.get("BookDate")),
        "bedrag": _decimal(record.get("Amount")),
        "open_bedrag": _decimal(
            record.get("OpenAmount") if record.get("OpenAmount") is not None else record.get("BaseOpenAmount")
        ),
        "tegenrekening_iban": record.get("CounterAccount"),
        "tegenpartij_naam": record.get("Name"),
        "omschrijving": record.get("Reference"),
        "mutatie_type": record.get("Type"),
        "rlz_voorstel_item_id": _nav_id(record, "MatchedPaymentItem"),
        "rlz_create_date": _tijdstip(create_date),
        "brondata": record,
    }


def _upsert_mutatie(session, *, administratie_id: uuid.UUID, record: dict[str, Any], now: datetime) -> bool:
    """True = nieuw aangemaakt, False = bestaande rij bijgewerkt."""
    record_id = uuid.UUID(str(record["id"]))
    waarden = _mutatie_waarden(record)
    rij = session.get(BankMutatie, (record_id, administratie_id))
    if rij is None:
        session.add(
            BankMutatie(
                id=record_id,
                administratie_id=administratie_id,
                laatst_gesynchroniseerd=now,
                verdwenen_uit_bron_op=None,
                **waarden,
            )
        )
        return True
    for veld, waarde in waarden.items():
        setattr(rij, veld, waarde)
    rij.laatst_gesynchroniseerd = now
    return False


def sync_payment_transactions(*, administratie_id: uuid.UUID, client: RlzClient) -> MutatieSyncTelling:
    now = datetime.now(UTC)

    with scoped_session(administratie_id) as session:
        stand = session.get(BankSyncStand, administratie_id)
        watermark = stand.mutaties_watermark if stand else None

    aangemaakt = 0
    bijgewerkt = 0
    verwerkte_ids: set[uuid.UUID] = set()
    hoogste_create_date: datetime | None = watermark
    cursor = watermark

    while True:
        params: dict[str, Any] = {
            "$orderby": "CreateDate",
            "$top": _MUTATIE_BATCH,
            "$expand": "PaymentAccount,MatchedPaymentItem",
        }
        if cursor is not None:
            # `ge` (niet `gt` — nooit geverifieerd) overlapt bewust de laatste rij; de
            # id-ontdubbeling hieronder vangt dat af.
            params["$filter"] = f"CreateDate ge {cursor.isoformat()}"
        batch = client.list_payment_transactions(params=params)

        nieuwe_in_batch = [
            record for record in batch if uuid.UUID(str(record["id"])) not in verwerkte_ids
        ]
        with scoped_session(administratie_id) as session:
            for record in nieuwe_in_batch:
                record_id = uuid.UUID(str(record["id"]))
                verwerkte_ids.add(record_id)
                if _upsert_mutatie(session, administratie_id=administratie_id, record=record, now=now):
                    aangemaakt += 1
                else:
                    bijgewerkt += 1
                parsed = _tijdstip(record.get("CreateDate"))
                if parsed is not None and (hoogste_create_date is None or parsed > hoogste_create_date):
                    hoogste_create_date = parsed

        if len(batch) < _MUTATIE_BATCH:
            break
        if not nieuwe_in_batch:
            # Volledig overlappende batch (kan alleen bij > _MUTATIE_BATCH rijen met exact
            # dezelfde CreateDate) — afbreken is dan veiliger dan eeuwig dezelfde pagina lezen.
            logger.warning(
                "Bank-sync %s: batch zonder nieuwe mutaties bij cursor %s — lus afgebroken",
                administratie_id,
                cursor,
            )
            break
        cursor = hoogste_create_date

    # Verversronde: lokaal-open mutaties die niet in de verse batch zaten kunnen intussen in
    # RLZ afgeletterd zijn (OpenAmount veranderd) — per id opnieuw ophalen. Het volume is klein
    # (tientallen open mutaties), dus per-id GET's zijn hier de eenvoudige, betrouwbare vorm.
    with scoped_session(administratie_id) as session:
        open_ids = [
            rij_id
            for rij_id in session.scalars(
                select(BankMutatie.id).where(
                    BankMutatie.administratie_id == administratie_id,
                    BankMutatie.open_bedrag.isnot(None),
                    BankMutatie.open_bedrag != 0,
                )
            )
            if rij_id not in verwerkte_ids
        ]

    open_ververst = 0
    for rij_id in open_ids:
        record = client.get_payment_transaction(rij_id, expand="PaymentAccount,MatchedPaymentItem")
        with scoped_session(administratie_id) as session:
            _upsert_mutatie(session, administratie_id=administratie_id, record=record, now=now)
            open_ververst += 1

    with scoped_session(administratie_id) as session:
        stand = session.get(BankSyncStand, administratie_id)
        if stand is None:
            stand = BankSyncStand(administratie_id=administratie_id)
            session.add(stand)
        stand.mutaties_watermark = hoogste_create_date
        stand.laatste_sync_op = now

    return MutatieSyncTelling(aangemaakt=aangemaakt, bijgewerkt=bijgewerkt, open_ververst=open_ververst)


# --- 3. open posten ----------------------------------------------------------------------------


def _item_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "bedrag": _decimal(record.get("Amount")),
        "boekdatum": _datum(record.get("BookDate")),
        "vervaldatum": _datum(record.get("DueDate")),
        "referentie": record.get("Reference"),
        "referentie2": record.get("Reference2"),
        "rlz_document_id": _nav_id(record, "Document"),
        "payment_status": record.get("PaymentStatus"),
        "brondata": record,
    }


def sync_payment_items(*, administratie_id: uuid.UUID, client: RlzClient) -> SyncTelling:
    items = client.list_payment_items(params={"$expand": "Document"})
    now = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        return _upsert_en_markeer_verdwenen(
            session,
            model=PaymentItemCache,
            id_kolom="id",
            administratie_id=administratie_id,
            verse_rijen=items,
            kolom_waarden=_item_waarden,
            now=now,
        )


# --- orkestratie -------------------------------------------------------------------------------


def sync_bank_voor_administratie(
    *, administratie_id: uuid.UUID, client: RlzClient | None = None
) -> BankSyncResultaat:
    """Volledige bank-sync-run voor één administratie (on-demand trigger én CLI `bank-sync`).
    Verificatie/Vastly/autoboeken draaien ná de leesstappen, op de dan-verse cache."""
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        rekeningen = sync_payment_accounts(administratie_id=administratie_id, client=client)
        mutaties = sync_payment_transactions(administratie_id=administratie_id, client=client)
        open_posten = sync_payment_items(administratie_id=administratie_id, client=client)
        geverifieerd = afletteren.verifieer_openstaande_opdrachten(
            administratie_id=administratie_id, client=client
        )
        vastly_gemeld = vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client)

        automatisch_geboekt = 0
        automatisch_fouten: list[str] = []
        with scoped_session(None) as session:
            administratie = session.get(Administratie, administratie_id)
            if administratie is None:
                raise SyncFout(f"Onbekende administratie: {administratie_id}")
            autoboeken = administratie.bank_autoboeken_ingeschakeld
        automatisch_afgeletterd = 0
        afletter_fouten: list[str] = []
        if autoboeken:
            # Stap 1 (exacte match) éérst automatisch afletteren — dan pas de vaste regels:
            # een mutatie met een exacte open-post-match mag nooit door een vaste regel
            # direct-op-grootboek geboekt worden ("nooit óver een open-post-match heen").
            automatisch_afgeletterd, afletter_fouten = afletteren.verwerk_exacte_matches_automatisch(
                administratie_id=administratie_id, client=client
            )
            # Import hier i.p.v. bovenaan: boeken.py importeert de matchmotor die op deze
            # module-laag niets nodig heeft, maar een top-level import zou een kringetje
            # sync -> boeken -> voorstellen -> sync riskeren zodra voorstellen sync-standen leest.
            from app.bank.boeken import verwerk_vaste_regels_automatisch

            automatisch_geboekt, automatisch_fouten = verwerk_vaste_regels_automatisch(
                administratie_id=administratie_id, client=client
            )

        return BankSyncResultaat(
            rekeningen=rekeningen,
            mutaties=mutaties,
            open_posten=open_posten,
            afletteren_geverifieerd=geverifieerd,
            vastly_gemeld=vastly_gemeld,
            automatisch_geboekt=automatisch_geboekt,
            automatisch_fouten=automatisch_fouten,
            automatisch_afgeletterd=automatisch_afgeletterd,
            afletter_fouten=afletter_fouten,
        )
    finally:
        if eigen_client:
            client.close()


def sync_bank_alle_administraties() -> dict[uuid.UUID, BankSyncResultaat | str]:
    """CLI `bank-sync` zonder administratie-id (en straks de Cloud Scheduler-job): één kapotte
    administratie stopt de rest niet — zelfde patroon als sync_alle_administraties()."""
    with scoped_session(None) as session:
        administratie_ids = [row.id for row in session.scalars(select(Administratie))]

    resultaten: dict[uuid.UUID, BankSyncResultaat | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = sync_bank_voor_administratie(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed: één kapotte administratie mag de rest niet raken
            resultaten[administratie_id] = str(exc)
    return resultaten
