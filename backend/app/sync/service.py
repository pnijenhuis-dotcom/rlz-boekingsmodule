from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_vendor_id
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id
from app.sync.models import ProjectCache, TaxRateCache, VendorCache

# Voor het controlescherm (GB-/btw-/crediteur-/project-comboboxen, CLAUDE.md-taak 2.1): verdwenen
# en (voor grootboek) totaalrekeningen horen niet in de keuzelijst, conform het filterpatroon dat
# vastgoed al toepast op dezelfde grootboekrekening-tabel (Platform/OPEN_ITEMS.md, "Grootboek-
# koppeling"-item, kanttekening (b)). Gearchiveerde/inactieve crediteuren/projecten worden hier
# NIET uitgefilterd — een al geboekte historische regel kan naar een inmiddels gearchiveerde
# crediteur/project wijzen, en de controleur moet die nog kunnen zien/kiezen bij het narekenen.


class SyncFout(Exception):
    """Domeinfout in de sync-laag (bv. onbekende administratie)."""


@dataclass(frozen=True)
class SyncTelling:
    aangemaakt: int
    bijgewerkt: int
    verdwenen: int


@dataclass(frozen=True)
class SyncResultaat:
    ledgers: SyncTelling
    taxrates: SyncTelling
    vendors: SyncTelling
    projects: SyncTelling


def _rlz_admin_id_voor(administratie_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise SyncFout(f"Onbekende administratie: {administratie_id}")
        return administratie.rlz_admin_id


def _upsert_en_markeer_verdwenen(
    session: Session,
    *,
    model: type,
    id_kolom: str,
    administratie_id: uuid.UUID,
    verse_rijen: Iterable[dict[str, Any]],
    kolom_waarden: Callable[[dict[str, Any]], dict[str, Any]],
    now: datetime,
) -> SyncTelling:
    """Generieke upsert + verdwenen_uit_bron_op-markering (koppelcontract §2c): een rij die niet
    meer in de verse respons voorkomt wordt gemarkeerd (nooit hard verwijderen); komt hij terug,
    gaat de kolom terug naar NULL. Werkt voor elke sync-tabel met dezelfde vorm (grootboek + de
    drie caches) — één plek voor dit patroon i.p.v. het viermaal te herhalen."""
    bestaande = {
        getattr(rij, id_kolom): rij
        for rij in session.scalars(select(model).where(model.administratie_id == administratie_id))
    }

    verse_ids: set[uuid.UUID] = set()
    aangemaakt = 0
    bijgewerkt = 0
    for record in verse_rijen:
        record_id = uuid.UUID(str(record["id"]))
        verse_ids.add(record_id)
        waarden = kolom_waarden(record)
        bestaande_rij = bestaande.get(record_id)
        if bestaande_rij is None:
            session.add(
                model(
                    **{id_kolom: record_id},
                    administratie_id=administratie_id,
                    laatst_gesynchroniseerd=now,
                    verdwenen_uit_bron_op=None,
                    **waarden,
                )
            )
            aangemaakt += 1
        else:
            for veld, waarde in waarden.items():
                setattr(bestaande_rij, veld, waarde)
            bestaande_rij.laatst_gesynchroniseerd = now
            bestaande_rij.verdwenen_uit_bron_op = None
            bijgewerkt += 1

    verdwenen = 0
    for record_id, rij in bestaande.items():
        if record_id not in verse_ids and rij.verdwenen_uit_bron_op is None:
            rij.verdwenen_uit_bron_op = now
            verdwenen += 1

    return SyncTelling(aangemaakt=aangemaakt, bijgewerkt=bijgewerkt, verdwenen=verdwenen)


def _grootboek_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(record["AccountNumber"]),
        "naam": record["Description"],
        "soort": int(record["AccountType"]),
        "is_totaalrekening": bool(record["IsTotalAccount"]),
    }


def _vendor_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"naam": record.get("Name"), "is_gearchiveerd": record.get("IsArchived"), "brondata": record}


def _project_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"naam": record.get("Name"), "is_actief": record.get("IsActive"), "brondata": record}


def _taxrate_waarden(record: dict[str, Any]) -> dict[str, Any]:
    # TaxRate's officiële resource-model-documentatie gaf herhaaldelijk een serverfout (geen
    # bevestigd veldnamen) — best-effort op de gebruikelijke naam-velden, brondata is het vangnet.
    # Percentage is inmiddels wél empirisch geverifieerd (design-pass taak 3, migratie 0011): komt
    # betrouwbaar mee als fractie (0.21 voor 21%).
    naam = record.get("Name") or record.get("Description")
    percentage = record.get("Percentage")
    return {
        "naam": naam,
        "percentage": Decimal(str(percentage)) if percentage is not None else None,
        "brondata": record,
    }


def _sync_generiek(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient,
    pad: str,
    model: type,
    id_kolom: str,
    kolom_waarden: Callable[[dict[str, Any]], dict[str, Any]],
) -> SyncTelling:
    verse_rijen = client.get(pad).get("value", [])
    now = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        return _upsert_en_markeer_verdwenen(
            session,
            model=model,
            id_kolom=id_kolom,
            administratie_id=administratie_id,
            verse_rijen=verse_rijen,
            kolom_waarden=kolom_waarden,
            now=now,
        )


def _open_client_indien_nodig(administratie_id: uuid.UUID, client: RlzClient | None) -> tuple[RlzClient, bool]:
    """Opent zelf een RlzClient (via de .env-credential-resolutie, app/rlz/credentials.py) als de
    aanroeper er geen meegeeft. Het tweede returnwaarde-lid zegt of de aanroeper 'm zelf moet
    sluiten (alleen als deze functie 'm heeft geopend — een meegegeven client blijft van de
    aanroeper, bv. één gedeelde login voor alle vier de bronnen in sync_alles_voor_administratie)."""
    if client is not None:
        return client, False
    return client_voor_rlz_admin_id(_rlz_admin_id_voor(administratie_id)), True


def sync_ledgers(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad="Ledgers", model=Grootboekrekening,
            id_kolom="ledger_id", kolom_waarden=_grootboek_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_taxrates(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad="TaxRates", model=TaxRateCache,
            id_kolom="id", kolom_waarden=_taxrate_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_vendors(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad="Vendors", model=VendorCache,
            id_kolom="id", kolom_waarden=_vendor_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_projects(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad="Projects", model=ProjectCache,
            id_kolom="id", kolom_waarden=_project_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_alles_voor_administratie(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncResultaat:
    """Alle vier de bronnen voor één administratie, met één gedeelde RlzClient-verbinding
    (efficiënter dan vier losse logins)."""
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return SyncResultaat(
            ledgers=_sync_generiek(
                administratie_id=administratie_id, client=client, pad="Ledgers", model=Grootboekrekening,
                id_kolom="ledger_id", kolom_waarden=_grootboek_waarden,
            ),
            taxrates=_sync_generiek(
                administratie_id=administratie_id, client=client, pad="TaxRates", model=TaxRateCache,
                id_kolom="id", kolom_waarden=_taxrate_waarden,
            ),
            vendors=_sync_generiek(
                administratie_id=administratie_id, client=client, pad="Vendors", model=VendorCache,
                id_kolom="id", kolom_waarden=_vendor_waarden,
            ),
            projects=_sync_generiek(
                administratie_id=administratie_id, client=client, pad="Projects", model=ProjectCache,
                id_kolom="id", kolom_waarden=_project_waarden,
            ),
        )
    finally:
        if eigen_client:
            client.close()


def lijst_grootboek(*, administratie_id: uuid.UUID) -> list[Grootboekrekening]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(Grootboekrekening)
                .where(
                    Grootboekrekening.administratie_id == administratie_id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                    Grootboekrekening.is_totaalrekening.is_(False),
                )
                .order_by(Grootboekrekening.code)
            )
        )


def lijst_taxrates(*, administratie_id: uuid.UUID) -> list[TaxRateCache]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(TaxRateCache)
                .where(TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None))
                .order_by(TaxRateCache.naam)
            )
        )


def lijst_vendors(*, administratie_id: uuid.UUID) -> list[VendorCache]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(VendorCache)
                .where(VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None))
                .order_by(VendorCache.naam)
            )
        )


def lijst_projects(*, administratie_id: uuid.UUID) -> list[ProjectCache]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(ProjectCache)
                .where(ProjectCache.administratie_id == administratie_id, ProjectCache.verdwenen_uit_bron_op.is_(None))
                .order_by(ProjectCache.naam)
            )
        )


class CrediteurAanmakenUitgeschakeld(Exception):
    """RLZ-schrijf-failsafe: crediteuren aanmaken valt onder dezelfde poort als boeken (toggle
    per administratie + globale kill switch) — het is een schrijfactie in de klantboekhouding."""


class CrediteurBestaatAl(Exception):
    """Er staat al een niet-verdwenen crediteur met exact deze naam in de cache."""

    def __init__(self, vendor_id: uuid.UUID, naam: str) -> None:
        self.vendor_id = vendor_id
        self.naam = naam
        super().__init__(f'Crediteur "{naam}" bestaat al in deze administratie')


@dataclass(frozen=True)
class NieuweCrediteur:
    id: uuid.UUID
    naam: str


def maak_crediteur_aan(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, naam: str, client: RlzClient | None = None
) -> NieuweCrediteur:
    """Maakt een crediteur aan in RLZ (fix 2, 2026-07-10: de AI las een leverancier die nog niet
    in de crediteuren-cache staat — het controlescherm biedt dan "nieuwe crediteur aanmaken in
    RLZ" met de geëxtraheerde naam voorgevuld, conform de mockup-onboarding).

    Idempotent en failsafe-gedekt: deterministisch client-GUID (UUIDv5 op administratie +
    genormaliseerde naam — een dubbele klik of retry raakt dezélfde RLZ-vendor), eigen
    duplicaatcheck op naam vóór de PUT, en dezelfde schrijf-poort als boeken (toggle per
    administratie + globale kill switch): zolang een administratie niet expliciet voor schrijven
    is opengezet, gaat er ook via deze route geen mutatie de klantboekhouding in. De cache-rij
    wordt direct bijgeschreven (het veld is meteen kiesbaar); de eerstvolgende vendors-sync
    overschrijft de minimale brondata met RLZ's volledige record."""
    naam = " ".join(naam.split())
    if not naam:
        raise SyncFout("Crediteurnaam mag niet leeg zijn")

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise SyncFout(f"Onbekende administratie: {administratie_id}")
        instelling = session.get(BoekenInstelling, True)
        if not administratie.boeken_ingeschakeld or instelling is None or not instelling.globaal_ingeschakeld:
            raise CrediteurAanmakenUitgeschakeld(
                "Crediteuren aanmaken in RLZ staat uit voor deze administratie "
                "(schrijf-failsafe: zelfde toggle als boeken, plus de globale kill switch)"
            )

    with scoped_session(administratie_id) as session:
        bestaande = session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
                func.lower(VendorCache.naam) == naam.lower(),
            )
        ).first()
        if bestaande is not None:
            raise CrediteurBestaatAl(bestaande.id, bestaande.naam or naam)

    vendor_id = rlz_vendor_id(administratie_id, naam)
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        client.put_vendor(vendor_id, name=naam)
    finally:
        if eigen_client:
            client.close()

    now = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(VendorCache, (vendor_id, administratie_id))
        if rij is None:
            session.add(
                VendorCache(
                    id=vendor_id,
                    administratie_id=administratie_id,
                    naam=naam,
                    is_gearchiveerd=False,
                    brondata={"id": str(vendor_id), "Name": naam, "bron": "app_aangemaakt"},
                    laatst_gesynchroniseerd=now,
                    verdwenen_uit_bron_op=None,
                )
            )
        else:
            rij.naam = naam
            rij.laatst_gesynchroniseerd = now
            rij.verdwenen_uit_bron_op = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vendor_cache",
            record_id=vendor_id,
            actie="crediteur_aangemaakt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"naam": naam},
            administratie_id=administratie_id,
        )
    return NieuweCrediteur(id=vendor_id, naam=naam)


def sync_alle_administraties() -> dict[uuid.UUID, SyncResultaat | str]:
    """Nachtelijke sync (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit aan; lokaal via
    `make sync-alles`/`python -m app.cli sync-alles`, zie Makefile). Eén administratie zonder
    (werkende) credentials laat de rest niet stuklopen — het resultaat-dict zet de foutmelding
    als string op die administratie_id, in plaats van de hele run af te breken."""
    with scoped_session(None) as session:
        administratie_ids = [row.id for row in session.scalars(select(Administratie))]

    resultaten: dict[uuid.UUID, SyncResultaat | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = sync_alles_voor_administratie(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed: één kapotte administratie mag de rest niet raken
            resultaten[administratie_id] = str(exc)
    return resultaten
