from __future__ import annotations

import dataclasses
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activa.categorie import is_mva_rekening
from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_vendor_id
from app.rlz import leesroutes
from app.rlz.client import RlzApiError, RlzClient, adres_als_regel
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id
from app.sync.models import ProjectCache, TaxRateCache, VendorCache

# Voor het controlescherm (GB-/btw-/crediteur-/project-comboboxen, CLAUDE.md-taak 2.1): verdwenen
# en (voor grootboek) totaalrekeningen horen niet in de keuzelijst, conform het filterpatroon dat
# vastgoed al toepast op dezelfde grootboekrekening-tabel (Platform/OPEN_ITEMS.md, "Grootboek-
# koppeling"-item, kanttekening (b)). Gearchiveerde/inactieve crediteuren/projecten worden hier
# NIET uitgefilterd — een al geboekte historische regel kan naar een inmiddels gearchiveerde
# crediteur/project wijzen, en de controleur moet die nog kunnen zien/kiezen bij het narekenen.


#: Sync-pad per eerste-sync-onderdeel — één bron met de rechten-probe (app/rlz/leesroutes.py, blok C 10-09).
_sync_pad = leesroutes.pad_voor_sync_onderdeel
_sync_params = leesroutes.params_voor_sync_onderdeel


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
    #: Administratienaam volgt de bron (Peter 15-09, 0144): uitkomst van `administratienaam.volg_*` — 'gevolgd' |
    #: 'gelijk' | 'afwijkend_mens' | 'bezet' | 'onbekend'; None = niet gelezen (los onderdeel, eerste sync).
    naam: str | None = None


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


def standaard_taxrate_uit_ledger(record: dict[str, Any]) -> uuid.UUID | None:
    """Het standaard-btw-tarief van een RLZ-rekening: `PreferentialTaxRate` = navigatie naar een VatRate, alleen
    aanwezig mét `$expand=PreferentialTaxRate` (leesroutes.LEDGERS.params). Ontbreekt de sleutel, is hij null of
    draagt hij geen leesbaar id → None = geen default (fail-safe: hetzelfde gedrag als vóór 14-09)."""
    nav = record.get("PreferentialTaxRate")
    if not isinstance(nav, dict):
        return None
    try:
        return uuid.UUID(str(nav["id"]))
    except (KeyError, ValueError, TypeError):
        return None


def _grootboek_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(record["AccountNumber"]),
        "naam": record["Description"],
        "soort": int(record["AccountType"]),
        "is_totaalrekening": bool(record["IsTotalAccount"]),
        # Opdracht Peter 14-09: btw-default uit de grootboekrekening (migratie 0142) — elke sync herschrijft 'm.
        "standaard_taxrate_id": standaard_taxrate_uit_ledger(record),
        # Activa fase 1 (Peter 21-09, migratie 0168): MVA = IsFixedAssetAccount ÉN AccountType 3 ÉN code 0xxx (STAP-0 a9).
        "is_activa": is_mva_rekening(record),
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
    params: dict[str, str] | None = None,
) -> SyncTelling:
    # `params` = de exacte query van de Leesroute (14-09: Ledgers mét $expand=PreferentialTaxRate) — één bron met de
    # rechten-probe, zodat de probe hetzelfde antwoord ziet als de sync.
    verse_rijen = (client.get(pad, params=params) if params else client.get(pad)).get("value", [])
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


def _is_odoo(administratie_id: uuid.UUID) -> bool:
    """Registry-lookup (0016): Odoo-administraties syncen via app/odoo/sync.py naar dezélfde caches. De
    sync-laag is infrastructuur — dit is de enige vertakking, en hij loopt via de registry."""
    from app.backends.registry import Backend, OnbekendeBackend, backend_voor

    try:
        return backend_voor(administratie_id) is Backend.ODOO
    except OnbekendeBackend:
        return False  # onbekende administratie: het RLZ-pad geeft de bestaande SyncFout


def _odoo_sync(administratie_id: uuid.UUID) -> SyncResultaat:
    from app.odoo.sync import sync_alles_voor_odoo_administratie

    return sync_alles_voor_odoo_administratie(administratie_id=administratie_id)


def _open_client_indien_nodig(administratie_id: uuid.UUID, client: RlzClient | None) -> tuple[RlzClient, bool]:
    """Opent zelf een RlzClient (via de .env-credential-resolutie, app/rlz/credentials.py) als de
    aanroeper er geen meegeeft. Het tweede returnwaarde-lid zegt of de aanroeper 'm zelf moet
    sluiten (alleen als deze functie 'm heeft geopend — een meegegeven client blijft van de
    aanroeper, bv. één gedeelde login voor alle vier de bronnen in sync_alles_voor_administratie)."""
    if client is not None:
        return client, False
    return client_voor_rlz_admin_id(_rlz_admin_id_voor(administratie_id)), True


def sync_ledgers(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    if client is None and _is_odoo(administratie_id):
        return _odoo_sync(administratie_id).ledgers
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad=_sync_pad("ledgers"), model=Grootboekrekening,
            id_kolom="ledger_id", kolom_waarden=_grootboek_waarden, params=_sync_params("ledgers"),
        )
    finally:
        if eigen_client:
            client.close()


def sync_taxrates(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    if client is None and _is_odoo(administratie_id):
        return _odoo_sync(administratie_id).taxrates
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad=_sync_pad("taxrates"), model=TaxRateCache,
            id_kolom="id", kolom_waarden=_taxrate_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_vendors(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    if client is None and _is_odoo(administratie_id):
        return _odoo_sync(administratie_id).vendors
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad=_sync_pad("vendors"), model=VendorCache,
            id_kolom="id", kolom_waarden=_vendor_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_projects(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncTelling:
    if client is None and _is_odoo(administratie_id):
        return _odoo_sync(administratie_id).projects
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        return _sync_generiek(
            administratie_id=administratie_id, client=client, pad=_sync_pad("projects"), model=ProjectCache,
            id_kolom="id", kolom_waarden=_project_waarden,
        )
    finally:
        if eigen_client:
            client.close()


def sync_alles_voor_administratie(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> SyncResultaat:
    """Alle vier de bronnen voor één administratie, met één gedeelde RlzClient-verbinding
    (efficiënter dan vier losse logins). Odoo-administraties (0101) gaan via de Odoo-sync naar
    dezelfde caches."""
    if client is None and _is_odoo(administratie_id):
        return _odoo_sync(administratie_id)
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        resultaat = SyncResultaat(
            ledgers=_sync_generiek(
                administratie_id=administratie_id, client=client, pad=_sync_pad("ledgers"), model=Grootboekrekening,
                id_kolom="ledger_id", kolom_waarden=_grootboek_waarden, params=_sync_params("ledgers"),
            ),
            taxrates=_sync_generiek(
                administratie_id=administratie_id, client=client, pad=_sync_pad("taxrates"), model=TaxRateCache,
                id_kolom="id", kolom_waarden=_taxrate_waarden,
            ),
            vendors=_sync_generiek(
                administratie_id=administratie_id, client=client, pad=_sync_pad("vendors"), model=VendorCache,
                id_kolom="id", kolom_waarden=_vendor_waarden,
            ),
            projects=_sync_generiek(
                administratie_id=administratie_id, client=client, pad=_sync_pad("projects"), model=ProjectCache,
                id_kolom="id", kolom_waarden=_project_waarden,
            ),
        )
        # Activa fase 1 (Peter 21-09): ná de Ledgers-sync — heeft de administratie ≥ 1 MVA-rekening, dan de RLZ-grens
        # (`AdministrationSettings.FixedAssetAlertAmount`) verversen en het register proben (403 = recht ontbreekt,
        # zichtbaar op de instelling + reconciliatieblok `activa`). Nooit blokkerend voor de sync.
        _activa_na_ledgers_sync(administratie_id=administratie_id, client=client)
        # Administratienaam volgt de bron (Peter 15-09, 0144): dezelfde login, root-vorm `Administrations`; een
        # leesfout maakt de sync nooit rood (uitkomst 'onbekend', zichtbaar in de sync-regel).
        from app.beheer import administratienaam

        return dataclasses.replace(resultaat, naam=administratienaam.volg_uit_rlz(administratie_id, client))
    finally:
        if eigen_client:
            client.close()


def _activa_na_ledgers_sync(*, administratie_id: uuid.UUID, client: RlzClient) -> None:
    """Activa fase 1: grens + register-probe, alleen als er MVA-rekeningen zijn; élke fout gelogd, nooit een stop."""
    try:
        from app.activa import instelling as activa_instelling

        with scoped_session(administratie_id) as session:
            if not activa_instelling.heeft_mva_rekeningen(session, administratie_id):
                return
            activa_instelling.ververs_rlz_grens(session, client, administratie_id)
            activa_instelling.probe_register(session, client, administratie_id)
    except Exception:  # noqa: BLE001 — zichtbaar in de log, de sync loopt door
        import logging

        logging.getLogger(__name__).exception("activa: grens/register-probe mislukt voor %s", administratie_id)


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
    """Keuzelijst crediteuren (controlescherm-combobox): actueel en géén verliezer van een afgehandeld
    dubbel-cluster (B13 07-09 — een verliezer is in de module onbruikbaar)."""
    from app.crediteuren.voorkeur import BRUIKBAAR

    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(VendorCache)
                .where(
                    VendorCache.administratie_id == administratie_id,
                    VendorCache.verdwenen_uit_bron_op.is_(None),
                    BRUIKBAAR,
                )
                .order_by(VendorCache.naam)
            )
        )


_PROJECTCODE_PREFIX = re.compile(r"^\s*(\d[\w.-]{1,14})\s+(\S.*)$")


def splits_projectcode(naam: str | None) -> tuple[str | None, str | None]:
    """Blok C 16-09: RLZ heeft géén codeveld op Projects (STAP-0 16-09: DTO = id, Name, Description, IsActive,
    IsBillable, dates, budget); de code zit vóór in de naam volgens de naamconventie
    ("26140 Koningstraat (Kempen)" → ("26140", "Koningstraat (Kempen)")). Deterministisch: alleen een eerste token
    dat met een cijfer begint telt als code; anders (None, naam) — nooit raden."""
    if not naam:
        return None, naam
    m = _PROJECTCODE_PREFIX.match(naam)
    if not m:
        return None, naam
    return m.group(1), m.group(2).strip()


def lijst_projects(*, administratie_id: uuid.UUID) -> list[ProjectCache]:
    """Niet-verdwenen projecten; actieve eerst, inactieve (`is_actief = False`) onderaan mét behoud van de
    naamsortering (blok C 16-09: inactief blijft ZICHTBAAR — de gebruiker moet zien wat er bestaat)."""
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(ProjectCache)
                .where(ProjectCache.administratie_id == administratie_id, ProjectCache.verdwenen_uit_bron_op.is_(None))
                .order_by(ProjectCache.is_actief.is_(False), ProjectCache.naam)
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
    kvk_opgeslagen: bool = False
    btw_opgeslagen: bool = False
    iban_vertrouwd: bool = False
    waarschuwingen: tuple[str, ...] = ()


def maak_crediteur_aan(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    naam: str,
    client: RlzClient | None = None,
    kvk_nummer: str | None = None,
    btw_nummer: str | None = None,
    iban: str | None = None,
    document_id: uuid.UUID | None = None,
    adres: dict[str, str] | None = None,
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

    adres_waarschuwing: str | None = None
    if client is None and _is_odoo(administratie_id):
        # Odoo-adapter (0016): res.partner groepsgedeeld, lookup-vóór-create op btw → KvK → naam (besluit 02-09);
        # de UUID is de deterministische odoo_uuid van de partner (id-koppeling meteen geschreven).
        from app.odoo.partners import zorg_voor_crediteur

        partner = zorg_voor_crediteur(
            administratie_id=administratie_id, naam=naam, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer
        )
        vendor_id = partner.vendor_id
        brondata_bron = {"odoo_id": partner.odoo_id, "backend": "odoo", "bron": "app_aangemaakt"}
        if adres and adres_als_regel(adres):
            adres_waarschuwing = "adres niet naar Odoo geschreven (partner-adres via deze route niet ondersteund)"
    else:
        vendor_id = rlz_vendor_id(administratie_id, naam)
        client, eigen_client = _open_client_indien_nodig(administratie_id, client)
        try:
            adres_waarschuwing = _put_vendor_fail_open(client, vendor_id, naam=naam, adres=adres)
        finally:
            if eigen_client:
                client.close()
        brondata_bron = {"bron": "app_aangemaakt"}
        if adres and adres_als_regel(adres) and adres_waarschuwing is None:
            brondata_bron["FullAddress"] = adres_als_regel(adres)
            brondata_bron["adres_velden"] = _schoon_adres(adres)

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
                    brondata={"id": str(vendor_id), "Name": naam, **brondata_bron},
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
    # Controlescherm v2 ⑥ (02-09): kenmerken uit de scan meteen vastleggen — KvK/btw in
    # crediteur_kenmerk (bron 'factuur', audit), het IBAN als vertrouwd (bron bevestigd: de mens
    # maakt bewust déze crediteur mét dít IBAN aan — zo ontstaat geen valse IBAN-wissel-blokkade
    # op de eerste factuur van een nieuwe entiteit). Nooit stil: elke overgeslagen waarde is een
    # waarschuwing in het resultaat.
    waarschuwingen: list[str] = []
    if adres_waarschuwing:
        waarschuwingen.append(adres_waarschuwing)
    kvk_ok = btw_ok = iban_ok = False
    if not iban:
        # FV-14 (25-09): ontbrekend IBAN = WAARSCHUWING, geen blokkade (incasso/buitenland) — later via de IBAN-route.
        waarschuwingen.append(IBAN_ONTBREEKT_WAARSCHUWING)
    if kvk_nummer or btw_nummer:
        from app.documenten.crediteur_kenmerk import neem_over_uit_veldvoorstel
        from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer

        kvk_norm = normaliseer_kvk_nummer(kvk_nummer) if kvk_nummer else None
        btw_val = valideer_btw_nummer(btw_nummer) if btw_nummer else None
        if kvk_nummer and kvk_norm is None:
            waarschuwingen.append(f"KvK-nummer '{kvk_nummer}' heeft geen geldige vorm — niet opgeslagen")
        if btw_nummer and btw_val is None:
            waarschuwingen.append(f"Btw-nummer '{btw_nummer}' heeft geen geldige vorm — niet opgeslagen")
        if kvk_norm or btw_val:
            with scoped_session(administratie_id, actor_id=actor_id) as session:
                neem_over_uit_veldvoorstel(
                    session,
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    veldvoorstel={
                        "kvk_nummer": kvk_norm,
                        "btw_nummer": btw_val.genormaliseerd if btw_val else None,
                        "btw_nummer_geverifieerd": bool(btw_val and btw_val.geverifieerd),
                    },
                    document_id=document_id or vendor_id,
                    actor_id=actor_id,
                )
            kvk_ok = kvk_norm is not None
            btw_ok = btw_val is not None
    if iban:
        from app.documenten.leverancier_iban import OngeldigIban, bevestig_iban

        try:
            bevestig_iban(administratie_id=administratie_id, vendor_id=vendor_id, iban=iban, actor_id=actor_id)
            iban_ok = True
        except OngeldigIban:
            waarschuwingen.append(f"IBAN '{iban}' doorstaat de controle niet — niet als vertrouwd vastgelegd")
    return NieuweCrediteur(
        id=vendor_id,
        naam=naam,
        kvk_opgeslagen=kvk_ok,
        btw_opgeslagen=btw_ok,
        iban_vertrouwd=iban_ok,
        waarschuwingen=tuple(waarschuwingen),
    )


IBAN_ONTBREEKT_WAARSCHUWING = (
    "geen IBAN vastgelegd — incasso of buitenland? Toevoegen kan later via de IBAN-route (vier ogen)"
)
ADRES_NIET_GEACCEPTEERD = "adres niet door Reeleezee geaccepteerd — alleen de naam is opgeslagen"


def _schoon_adres(adres: dict[str, str] | None) -> dict[str, str]:
    return {k: " ".join(str(v).split()) for k, v in (adres or {}).items() if v and str(v).strip()}


def _put_vendor_fail_open(
    client: RlzClient, vendor_id: uuid.UUID, *, naam: str, adres: dict[str, str] | None
) -> str | None:
    """Vendor-PUT mét adres; weigert RLZ de body (4xx) dan nog één keer ZONDER adres — de naam gaat altijd, het
    adres alleen als RLZ het accepteert (blok 5 feedbackrun 25-09: schrijfbaarheid van `FullAddress`/`City` niet
    live bewezen). Terug: de waarschuwing (adres verworpen) of None. Een fout op de naam-PUT zelf gooit gewoon."""
    if not (adres and adres_als_regel(adres)):
        client.put_vendor(vendor_id, name=naam)
        return None
    try:
        client.put_vendor(vendor_id, name=naam, adres=adres)
        return None
    except RlzApiError as exc:
        if not 400 <= exc.status_code < 500:
            raise
        client.put_vendor(vendor_id, name=naam)
        return f"{ADRES_NIET_GEACCEPTEERD} ({exc.status_code})"


class CrediteurNietGevonden(SyncFout):
    """Geen (niet-verdwenen) crediteur mét dit id in de cache van deze administratie."""


class CrediteurBewerkenNietOndersteund(SyncFout):
    """Odoo-administratie: partnergegevens wijzigen via deze route is niet gebouwd — zichtbaar, nooit stil."""


@dataclass(frozen=True)
class CrediteurDetail:
    """Bewerk-modus van het crediteur-zijpaneel (FV-15): huidige stand uit cache + kenmerk + vertrouwde IBAN's
    (lees-only in het paneel — IBAN's wijzigen loopt ALTIJD via de IBAN-wissel/vier-ogen-route)."""

    id: uuid.UUID
    naam: str | None
    kvk_nummer: str | None
    btw_nummer: str | None
    adres: dict[str, str | None]
    vertrouwde_ibans: tuple[str, ...]
    backend: str


def _adres_uit_brondata(brondata: dict | None) -> dict[str, str | None]:
    """RLZ-sync levert `FullAddress`/`City` (Vendor-DTO); onze eigen writes bewaren daarnaast `adres_velden`."""
    b = brondata or {}
    velden = b.get("adres_velden") if isinstance(b.get("adres_velden"), dict) else {}
    return {
        "straat": velden.get("straat") or None,
        "postcode": velden.get("postcode") or None,
        "plaats": velden.get("plaats") or b.get("City") or None,
        "land": velden.get("land") or None,
        "regel": b.get("FullAddress") or None,
    }


def crediteur_detail(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> CrediteurDetail:
    from app.documenten.leverancier_iban import vertrouwde_ibans
    from app.documenten.models import CrediteurKenmerk

    with scoped_session(administratie_id) as session:
        rij = session.get(VendorCache, (vendor_id, administratie_id))
        if rij is None or rij.verdwenen_uit_bron_op is not None:
            raise CrediteurNietGevonden(f"Onbekende crediteur: {vendor_id}")
        kenmerk = session.get(CrediteurKenmerk, (administratie_id, vendor_id))
        detail = CrediteurDetail(
            id=rij.id,
            naam=rij.naam,
            kvk_nummer=kenmerk.kvk_nummer if kenmerk else (rij.brondata or {}).get("ChamberOfCommerceNumber"),
            btw_nummer=kenmerk.btw_nummer if kenmerk else None,
            adres=_adres_uit_brondata(rij.brondata),
            vertrouwde_ibans=(),
            backend="odoo" if _is_odoo(administratie_id) else "rlz",
        )
    return dataclasses.replace(
        detail, vertrouwde_ibans=tuple(sorted(vertrouwde_ibans(administratie_id=administratie_id, vendor_id=vendor_id)))
    )


def _zet_kenmerk_handmatig(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    kvk_nummer: str | None,
    btw_nummer: str | None,
    actor_id: uuid.UUID,
) -> tuple[dict, dict, list[str]]:
    """KvK/btw uit het bewerk-paneel = MENS-keuze (bron 'handmatig' — wint voortaan van de factuur, bestaande regel
    in `neem_over_uit_veldvoorstel`). Ongeldige vorm = waarschuwing, niet opgeslagen; leeg laten = ongewijzigd."""
    from app.documenten.models import CrediteurKenmerk
    from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer

    waarschuwingen: list[str] = []
    rij = session.get(CrediteurKenmerk, (administratie_id, vendor_id))
    oud = {"kvk_nummer": rij.kvk_nummer if rij else None, "btw_nummer": rij.btw_nummer if rij else None}
    nieuw = dict(oud)
    btw_geverifieerd = False
    if kvk_nummer:
        kvk = normaliseer_kvk_nummer(kvk_nummer)
        if kvk is None:
            waarschuwingen.append(f"KvK-nummer '{kvk_nummer}' heeft geen geldige vorm — niet opgeslagen")
        else:
            nieuw["kvk_nummer"] = kvk
    if btw_nummer:
        btw = valideer_btw_nummer(btw_nummer)
        if btw is None:
            waarschuwingen.append(f"Btw-nummer '{btw_nummer}' heeft geen geldige vorm — niet opgeslagen")
        else:
            nieuw["btw_nummer"] = btw.genormaliseerd
            btw_geverifieerd = bool(btw.geverifieerd)
    if nieuw != oud:
        if rij is None:
            rij = CrediteurKenmerk(administratie_id=administratie_id, vendor_id=vendor_id)
            session.add(rij)
        if nieuw["kvk_nummer"] != oud["kvk_nummer"]:
            rij.kvk_nummer = nieuw["kvk_nummer"]
            rij.kvk_nummer_bron = "handmatig"
        if nieuw["btw_nummer"] != oud["btw_nummer"]:
            rij.btw_nummer = nieuw["btw_nummer"]
            rij.btw_nummer_geverifieerd = btw_geverifieerd
            rij.btw_nummer_bron = "handmatig"
        rij.laatst_uit_document_id = vendor_id
        rij.bijgewerkt_door = actor_id
        rij.bijgewerkt_op = datetime.now(UTC)
    return oud, nieuw, waarschuwingen


def wijzig_crediteur(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID,
    naam: str,
    kvk_nummer: str | None = None,
    btw_nummer: str | None = None,
    adres: dict[str, str] | None = None,
    client: RlzClient | None = None,
) -> NieuweCrediteur:
    """FV-15 (blok 5 feedbackrun 25-09): crediteur achteraf bewerken vanuit het controlescherm — naam + adres naar RLZ
    (`put_vendor` op het BESTAANDE id, fail-open op het adres), KvK/btw als mens-kenmerk ('handmatig'), cache-rij bij,
    audit `crediteur_gewijzigd` oud→nieuw. Dezelfde schrijf-failsafe-poort als aanmaken. Géén IBAN-veld: IBAN's lopen
    uitsluitend via de IBAN-wissel/vier-ogen-route. Odoo = zichtbaar niet ondersteund (409), nooit een stille no-op."""
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
                "Crediteuren bewerken in RLZ staat uit voor deze administratie "
                "(schrijf-failsafe: zelfde toggle als boeken, plus de globale kill switch)"
            )
    with scoped_session(administratie_id) as session:
        rij = session.get(VendorCache, (vendor_id, administratie_id))
        if rij is None or rij.verdwenen_uit_bron_op is not None:
            raise CrediteurNietGevonden(f"Onbekende crediteur: {vendor_id}")
        oude_naam = rij.naam
        oud_adres = _adres_uit_brondata(rij.brondata)
        andere = session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
                VendorCache.id != vendor_id,
                func.lower(VendorCache.naam) == naam.lower(),
            )
        ).first()
        if andere is not None:
            raise CrediteurBestaatAl(andere.id, andere.naam or naam)
    if client is None and _is_odoo(administratie_id):
        raise CrediteurBewerkenNietOndersteund(
            "Crediteurgegevens bewerken is voor een Odoo-administratie niet ondersteund — pas de partner in Odoo aan"
        )
    client, eigen_client = _open_client_indien_nodig(administratie_id, client)
    try:
        adres_waarschuwing = _put_vendor_fail_open(client, vendor_id, naam=naam, adres=adres)
    finally:
        if eigen_client:
            client.close()
    waarschuwingen: list[str] = []
    if adres_waarschuwing:
        waarschuwingen.append(adres_waarschuwing)
    now = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(VendorCache, (vendor_id, administratie_id))
        assert rij is not None
        brondata = dict(rij.brondata or {})
        brondata["Name"] = naam
        if adres is not None and adres_waarschuwing is None:
            schoon = _schoon_adres(adres)
            brondata["adres_velden"] = schoon
            regel = adres_als_regel(adres)
            if regel:
                brondata["FullAddress"] = regel
            else:
                brondata.pop("FullAddress", None)
            if schoon.get("plaats"):
                brondata["City"] = schoon["plaats"]
        rij.naam = naam
        rij.brondata = brondata
        rij.laatst_gesynchroniseerd = now
        oud_k, nieuw_k, kenmerk_w = _zet_kenmerk_handmatig(
            session,
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            kvk_nummer=kvk_nummer,
            btw_nummer=btw_nummer,
            actor_id=actor_id,
        )
        waarschuwingen.extend(kenmerk_w)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vendor_cache",
            record_id=vendor_id,
            actie="crediteur_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"naam": oude_naam, "adres": oud_adres, **oud_k},
            nieuwe_waarde={"naam": naam, "adres": _adres_uit_brondata(brondata), **nieuw_k, "bron": "controlescherm"},
            administratie_id=administratie_id,
        )
    from app.documenten.leverancier_iban import vertrouwde_ibans

    if not vertrouwde_ibans(administratie_id=administratie_id, vendor_id=vendor_id):
        waarschuwingen.append(IBAN_ONTBREEKT_WAARSCHUWING)
    return NieuweCrediteur(
        id=vendor_id,
        naam=naam,
        kvk_opgeslagen=nieuw_k["kvk_nummer"] is not None and nieuw_k["kvk_nummer"] != oud_k["kvk_nummer"],
        btw_opgeslagen=nieuw_k["btw_nummer"] is not None and nieuw_k["btw_nummer"] != oud_k["btw_nummer"],
        iban_vertrouwd=False,
        waarschuwingen=tuple(waarschuwingen),
    )


def sync_alle_administraties() -> dict[uuid.UUID, SyncResultaat | GeenRlzCredentials | str]:
    """Nachtelijke sync (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit aan; lokaal via
    `make sync-alles`/`python -m app.cli sync-alles`, zie Makefile). Eén administratie zonder
    (werkende) credentials laat de rest niet stuklopen — het resultaat-dict zet de foutmelding
    als string op die administratie_id, in plaats van de hele run af te breken.

    Een administratie zónder geregistreerde credential (store noch .env) is niet kapot maar
    niet-onboarded (bv. de cloud-seed-testadministratie, F3): die komt als GeenRlzCredentials
    terug zodat de CLI 'm zichtbaar OVERSLAAT zonder de exit-code te raken — een échte
    credential-/API-fout blijft een string en dus een fout."""
    with scoped_session(None) as session:
        administratie_ids = [
            row.id for row in session.scalars(select(Administratie).where(Administratie.actief.is_(True)))
        ]

    resultaten: dict[uuid.UUID, SyncResultaat | GeenRlzCredentials | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = sync_alles_voor_administratie(administratie_id=administratie_id)
        except GeenRlzCredentials as exc:
            resultaten[administratie_id] = exc
        except Exception as exc:  # noqa: BLE001 — bewust breed: één kapotte administratie mag de rest niet raken
            resultaten[administratie_id] = str(exc)
    return resultaten
