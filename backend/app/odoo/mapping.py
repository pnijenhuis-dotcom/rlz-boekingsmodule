"""Boekingsgeheugen-mapping RLZ → Odoo bij een overstap (blok A Odoo-afrondingsrun 04-09; besluit Peter
04-09, beslispunt 1 van "ODOO-ADAPTER BLOK E"; migratie 0111).

Waarom: het boekingsgeheugen (`boeking_observatie`) en de nog open boekvoorstellen dragen RLZ-UUID's
(grootboek `ledger_id`, btw `taxrate_id`). Ná een overstap hebben de Odoo-stamgegevens andere lokale
UUID's (`odoo_uuid(company, model, id)`) — zonder vertaling valt het geheugen, en daarmee élke
autoboek-opt-in, stil dood. Daarom is de mapping een VERPLICHTE stap van de overstap-wizard (ingang B):

1. `voorbereid_overstap` — dezelfde voorvalidaties + probe als `koppel_overstap`, leest LIVE (read-only)
   het Odoo-grootboek en de Odoo-inkooptarieven, bepaalt de in-gebruik-RLZ-rijen en een DETERMINISTISCH
   voorstel (code voor cijfers — geen AI, geen gok). Niets persistent.
2. De mens bevestigt de HELE tabel; `koppel_overstap(..., mapping=)` valideert (`valideer_mapping`: élke
   in-gebruik-rij MOET een Odoo-tegenhanger hebben) en schrijft de rijen (`schrijf_mapping`, versie 1) ín
   dezelfde transactie als de koppeling + audit.
3. Runtime: `geldende_mapping` + `vertaal_observaties` vertalen de observaties VÓÓR de engine weegt —
   anders zouden oude RLZ-stemmen en nieuwe Odoo-stemmen voor dezelfde rekening de stem splitsen.
   `app_bevestigd`/bron/bron_datum blijven ongewijzigd: de mens bevestigde het bóékgedrag, niet het
   rekeningnummer. `project_id` wordt op een vertaalde observatie None (RLZ-projecten ≠ Odoo-analytic-
   accounts; projectmapping = beslispunt Peter).
4. Correctie per rij = nieuwe versie (`corrigeer_rij`, append-only, audit oud→nieuw).

Voorstelregels grootboek (RLZ 4-cijferig, Odoo 6-cijferig — een letterlijke match levert bij Universal
weinig op): (1) exact gelijke code = `zelfde_code` (groen); (2) RLZ-code + "00" == Odoo-code
(4808 ↔ 480800) = `code_verlengd` (oranje, "bevestig" — regel 2 is een beslispunt voor Peter); méér dan
één Odoo-rekening met dezelfde code = geen voorstel. Btw (`tarief`): verlegd → de Odoo-verlegd-tarieven
(bij meerdere: op het percentage uit de RLZ-naam, "21%"), 0 %/vrijgesteld → synthetische "Geen btw (0%)"
(`GEEN_BTW_ODOO_ID`, = géén tax_ids), anders het Odoo-inkooptarief met exact gelijk percentage — telkens
precies één kandidaat, anders None (favoriet weegt niet: geen gok)."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Gebruiker, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentStatus
from app.geheugen.engine import Observatie
from app.geheugen.models import BoekingObservatie
from app.geheugen.regel_gb import RegelObservatie
from app.odoo import sync as odoo_sync
from app.odoo.credentials import GeenOdooKoppeling
from app.odoo.ids import GEEN_BTW_ODOO_ID, odoo_uuid
from app.odoo.models import OdooIdKoppeling, OdooKoppeling, OdooRekeningMapping
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache

logger = logging.getLogger(__name__)

SOORT_GROOTBOEK = "grootboek"
SOORT_BTW = "btw"
SOORTEN: tuple[str, ...] = (SOORT_GROOTBOEK, SOORT_BTW)

BRON_ZELFDE_CODE = "zelfde_code"
BRON_CODE_VERLENGD = "code_verlengd"
BRON_TARIEF = "tarief"
BRON_HANDMATIG = "handmatig"

#: Documentstatussen waarin een boekvoorstel-regel NIET meer "open" is: geboekt (het geheugen heeft 'm al),
#: afgewezen/verwijderd/gesplitst/samengevoegd/geaccordeerd (er volgt geen boeking meer). Alle overige
#: statussen tellen als open werk waarvan de RLZ-grootboek-/btw-keuzes ná de overstap nog vertaald moeten.
TERMINALE_STATUSSEN: tuple[DocumentStatus, ...] = (
    DocumentStatus.GEBOEKT,
    DocumentStatus.AFGEWEZEN,
    DocumentStatus.VERWIJDERD,
    DocumentStatus.GESPLITST,
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.GEACCORDEERD,
)

_PCT_IN_NAAM = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


# ----------------------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class RlzRekening:
    rlz_id: uuid.UUID
    code: str | None
    naam: str | None
    in_gebruik_observaties: int
    in_gebruik_open_regels: int


@dataclass(frozen=True)
class RlzTarief:
    rlz_id: uuid.UUID
    naam: str | None
    percentage: Decimal | None  # canonieke FRACTIE (0.21), zoals taxrate_cache.percentage
    verlegd: bool
    vrijgesteld: bool
    in_gebruik_observaties: int
    in_gebruik_open_regels: int


@dataclass(frozen=True)
class OdooRekening:
    odoo_id: int
    lokaal_id: uuid.UUID
    code: str
    naam: str
    soort: int | None = None


@dataclass(frozen=True)
class OdooTarief:
    odoo_id: int
    lokaal_id: uuid.UUID
    naam: str
    percentage: Decimal  # canonieke FRACTIE; verlegd = het Odoo-`amount`/100 (21% R → 0.21); synthetisch = 0
    verlegd: bool
    favoriet: bool
    synthetisch: bool


@dataclass(frozen=True)
class MappingVoorstelRij:
    rlz: RlzRekening
    voorstel: OdooRekening | None
    reden: str | None  # 'zelfde_code' | 'code_verlengd' | None


@dataclass(frozen=True)
class BtwMappingVoorstelRij:
    rlz: RlzTarief
    voorstel: OdooTarief | None
    reden: str | None  # 'tarief' | None


@dataclass(frozen=True)
class OverstapVoorbereiding:
    company_naam: str | None
    probe: dict[str, str]
    grootboek: list[MappingVoorstelRij]
    btw: list[BtwMappingVoorstelRij]
    odoo_grootboek: list[OdooRekening]
    odoo_btw: list[OdooTarief]


@dataclass(frozen=True)
class MappingRijInvoer:
    """Wat de mens per rij bevestigt: RLZ-id → Odoo-int-id (0 = synthetisch geen-btw, alleen btw)."""

    rlz_id: uuid.UUID
    odoo_id: int


@dataclass(frozen=True)
class MappingInvoer:
    grootboek: list[MappingRijInvoer] = field(default_factory=list)
    btw: list[MappingRijInvoer] = field(default_factory=list)


@dataclass(frozen=True)
class MappingRij:
    """Een gevalideerde, te schrijven rij (of een gelezen geldende rij)."""

    soort: str
    rlz_id: uuid.UUID
    rlz_code: str | None
    rlz_naam: str | None
    odoo_lokaal_id: uuid.UUID
    odoo_id: int
    odoo_code: str | None
    odoo_naam: str | None
    bron: str
    versie: int = 1
    bevestigd_op: datetime | None = None
    bevestigd_door: uuid.UUID | None = None
    bevestigd_door_naam: str | None = None


@dataclass(frozen=True)
class RekeningMapping:
    """Geldende vertaling RLZ-UUID → Odoo-lokale-UUID per soort. Leeg = geen mapping = geen vertaling."""

    grootboek: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    btw: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    @property
    def leeg(self) -> bool:
        return not self.grootboek and not self.btw


@dataclass(frozen=True)
class MappingStand:
    grootboek: list[MappingRij]
    btw: list[MappingRij]
    odoo_grootboek: list[OdooRekening]
    odoo_btw: list[OdooTarief]
    laatst_bevestigd_op: datetime | None
    laatst_bevestigd_door_naam: str | None


# ----------------------------------------------------------------------------- Odoo-lijsten


def _decimal(waarde: Any) -> Decimal | None:
    if waarde is None or waarde == "":
        return None
    try:
        return Decimal(str(waarde))
    except (InvalidOperation, ValueError):
        return None


def odoo_rekeningen_uit_sync(records: list[dict[str, Any]]) -> list[OdooRekening]:
    """`odoo_sync.lees_grootboek`-records (dezelfde vorm die de cache-sync schrijft) → dataclasses."""
    return [
        OdooRekening(
            odoo_id=int(r["odoo_id"]),
            lokaal_id=uuid.UUID(str(r["id"])),
            code=str(r["code"]).strip(),
            naam=str(r["naam"]),
            soort=r.get("soort"),
        )
        for r in records
    ]


def odoo_tarieven_uit_sync(records: list[dict[str, Any]]) -> list[OdooTarief]:
    """`odoo_sync.lees_btw`-records → dataclasses. Het verlegd-tarief draagt in de cache `Percentage` 0
    (RLZ-conventie voor `IsRelayed`); voor de mapping is het Odoo-`amount` (21) informatiever → 0.21."""
    uit: list[OdooTarief] = []
    for r in records:
        verlegd = bool(r.get("IsRelayed"))
        synthetisch = bool(r.get("synthetisch")) or int(r["odoo_id"]) == GEEN_BTW_ODOO_ID
        if synthetisch:
            pct = Decimal("0")
        elif verlegd:
            amount = _decimal(r.get("odoo_amount")) or Decimal("0")
            pct = amount / Decimal(100)
        else:
            pct = _decimal(r.get("Percentage")) or Decimal("0")
        uit.append(
            OdooTarief(
                odoo_id=int(r["odoo_id"]),
                lokaal_id=uuid.UUID(str(r["id"])),
                naam=str(r["Name"]),
                percentage=pct.normalize() if pct != 0 else Decimal("0"),
                verlegd=verlegd,
                favoriet=bool(r.get("IsFavorite")),
                synthetisch=synthetisch,
            )
        )
    return uit


def lees_live_odoo_stamgegevens(
    *, odoo_url: str, api_key: str, company_id: int
) -> tuple[list[OdooRekening], list[OdooTarief]]:
    """LIVE, read-only: het Odoo-grootboek + de inkooptarieven van deze company met een losse `_Vertaler`
    (niets in de DB — de lokale UUID's zijn deterministisch, dus vóór de sync al te berekenen). Test-seam."""
    from app.odoo import service  # lokaal: service importeert deze module in koppel_overstap

    vertaler = odoo_sync._Vertaler(int(company_id))  # noqa: SLF001 — bewust dezelfde id-afleiding als de sync
    with service._client(odoo_url, api_key, int(company_id)) as client:  # noqa: SLF001
        grootboek = odoo_sync.lees_grootboek(client, vertaler)
        btw = odoo_sync.lees_btw(client, vertaler)
    return odoo_rekeningen_uit_sync(grootboek), odoo_tarieven_uit_sync(btw)


# ----------------------------------------------------------------------------- RLZ in gebruik


def rlz_in_gebruik(session: Session, administratie_id: uuid.UUID) -> tuple[list[RlzRekening], list[RlzTarief]]:
    """De rijen die de mens moet mappen: RLZ-grootboek-ids uit `boeking_observatie.gb_id` ∪ de `ledger_id`'s
    van boekvoorstel-regels van documenten in een NIET-terminale status (idem btw: `btw_id` ∪ `taxrate_id`).
    Code/naam uit de cache — óók verdwenen rijen (de Odoo-sync markeert ze ná de overstap); staat een id
    niet (meer) in de cache, dan code/naam None ("onbekende RLZ-rekening"), tóch te mappen."""
    obs_gb = dict(
        session.execute(
            select(BoekingObservatie.gb_id, func.count())
            .where(BoekingObservatie.administratie_id == administratie_id)
            .group_by(BoekingObservatie.gb_id)
        ).all()
    )
    obs_btw = dict(
        session.execute(
            select(BoekingObservatie.btw_id, func.count())
            .where(BoekingObservatie.administratie_id == administratie_id, BoekingObservatie.btw_id.is_not(None))
            .group_by(BoekingObservatie.btw_id)
        ).all()
    )
    open_basis = (
        select(BoekvoorstelRegel)
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(Document.administratie_id == administratie_id, Document.status.not_in(list(TERMINALE_STATUSSEN)))
    )
    open_gb = dict(
        session.execute(
            open_basis.with_only_columns(BoekvoorstelRegel.ledger_id, func.count())
            .where(BoekvoorstelRegel.ledger_id.is_not(None))
            .group_by(BoekvoorstelRegel.ledger_id)
        ).all()
    )
    open_btw = dict(
        session.execute(
            open_basis.with_only_columns(BoekvoorstelRegel.taxrate_id, func.count())
            .where(BoekvoorstelRegel.taxrate_id.is_not(None))
            .group_by(BoekvoorstelRegel.taxrate_id)
        ).all()
    )

    gb_ids = sorted(set(obs_gb) | set(open_gb), key=str)
    btw_ids = sorted(set(obs_btw) | set(open_btw), key=str)
    gb_cache: dict[uuid.UUID, Grootboekrekening] = {}
    if gb_ids:
        gb_cache = {
            r.ledger_id: r
            for r in session.scalars(
                select(Grootboekrekening).where(
                    Grootboekrekening.administratie_id == administratie_id, Grootboekrekening.ledger_id.in_(gb_ids)
                )
            )
        }
    btw_cache: dict[uuid.UUID, TaxRateCache] = {}
    if btw_ids:
        btw_cache = {
            r.id: r
            for r in session.scalars(
                select(TaxRateCache).where(
                    TaxRateCache.administratie_id == administratie_id, TaxRateCache.id.in_(btw_ids)
                )
            )
        }

    rekeningen = [
        RlzRekening(
            rlz_id=i,
            code=(gb_cache[i].code.strip() if i in gb_cache else None),
            naam=(gb_cache[i].naam if i in gb_cache else None),
            in_gebruik_observaties=int(obs_gb.get(i, 0)),
            in_gebruik_open_regels=int(open_gb.get(i, 0)),
        )
        for i in gb_ids
    ]
    # Sorteer op code (onbekende achteraan), zodat de tabel voor de mens leesbaar is.
    rekeningen.sort(key=lambda r: (r.code is None, r.code or "", str(r.rlz_id)))

    tarieven: list[RlzTarief] = []
    for i in btw_ids:
        rij = btw_cache.get(i)
        verlegd, vrijgesteld = taxrate_vlaggen(rij.brondata) if rij is not None else (False, False)
        tarieven.append(
            RlzTarief(
                rlz_id=i,
                naam=rij.naam if rij is not None else None,
                percentage=rij.percentage if rij is not None else None,
                verlegd=verlegd,
                vrijgesteld=vrijgesteld,
                in_gebruik_observaties=int(obs_btw.get(i, 0)),
                in_gebruik_open_regels=int(open_btw.get(i, 0)),
            )
        )
    tarieven.sort(key=lambda t: (t.naam is None, t.naam or "", str(t.rlz_id)))
    return rekeningen, tarieven


# ----------------------------------------------------------------------------- pure voorstellen


def bepaal_grootboek_voorstel(rlz: list[RlzRekening], odoo: list[OdooRekening]) -> list[MappingVoorstelRij]:
    """Deterministisch per RLZ-rekening: exact gelijke code wint (`zelfde_code`); anders RLZ-code + "00"
    (`code_verlengd`); méér dan één Odoo-rekening met die code → geen voorstel (mens kiest)."""
    per_code: dict[str, list[OdooRekening]] = {}
    for o in odoo:
        per_code.setdefault(o.code.strip(), []).append(o)

    uit: list[MappingVoorstelRij] = []
    for r in rlz:
        voorstel: OdooRekening | None = None
        reden: str | None = None
        code = (r.code or "").strip()
        if code:
            exact = per_code.get(code, [])
            if len(exact) == 1:
                voorstel, reden = exact[0], BRON_ZELFDE_CODE
            elif not exact:
                verlengd = per_code.get(code + "00", [])
                if len(verlengd) == 1:
                    voorstel, reden = verlengd[0], BRON_CODE_VERLENGD
        uit.append(MappingVoorstelRij(rlz=r, voorstel=voorstel, reden=reden))
    return uit


def _pct_uit_naam(naam: str | None) -> Decimal | None:
    m = _PCT_IN_NAAM.search(naam or "")
    if not m:
        return None
    return (Decimal(m.group(1).replace(",", ".")) / Decimal(100)).normalize()


def _norm(d: Decimal | None) -> Decimal | None:
    if d is None:
        return None
    return d.normalize() if d != 0 else Decimal("0")


def bepaal_btw_voorstel(rlz: list[RlzTarief], odoo: list[OdooTarief]) -> list[BtwMappingVoorstelRij]:
    """Deterministisch per RLZ-tarief (reden 'tarief'): verlegd → de Odoo-verlegd-tarieven (RLZ zet het
    percentage van een verlegd tarief op 0 — bij meerdere kandidaten beslist het percentage in de RLZ-naam,
    "BTW verlegd 21%"); percentage 0 / vrijgesteld en niet verlegd → de synthetische "Geen btw (0%)";
    anders de Odoo-inkooptarieven (niet verlegd, niet synthetisch) met exact gelijk percentage. Telkens
    precies één kandidaat = voorstel, anders None — favoriet weegt niet mee (geen gok)."""
    uit: list[BtwMappingVoorstelRij] = []
    for t in rlz:
        kandidaten: list[OdooTarief]
        if t.verlegd:
            kandidaten = [o for o in odoo if o.verlegd and not o.synthetisch]
            pct = _norm(t.percentage) if t.percentage else _pct_uit_naam(t.naam)
            if pct is not None and pct != 0 and len(kandidaten) > 1:
                kandidaten = [o for o in kandidaten if _norm(o.percentage) == pct]
        elif t.vrijgesteld or (t.percentage is not None and t.percentage == 0):
            kandidaten = [o for o in odoo if o.synthetisch]
        elif t.percentage is None:
            kandidaten = []  # onbekend percentage (rij niet meer in de cache): nooit gokken
        else:
            pct = _norm(t.percentage)
            kandidaten = [o for o in odoo if not o.verlegd and not o.synthetisch and _norm(o.percentage) == pct]
        voorstel = kandidaten[0] if len(kandidaten) == 1 else None
        uit.append(BtwMappingVoorstelRij(rlz=t, voorstel=voorstel, reden=BRON_TARIEF if voorstel else None))
    return uit


# ----------------------------------------------------------------------------- validatie + schrijven


def valideer_mapping(
    *,
    grootboek: list[MappingVoorstelRij],
    btw: list[BtwMappingVoorstelRij],
    odoo_grootboek: list[OdooRekening],
    odoo_btw: list[OdooTarief],
    invoer: MappingInvoer | None,
) -> list[MappingRij]:
    """Élke in-gebruik-rij MOET een odoo_id hebben dat in de live Odoo-lijst voorkomt (btw: incl. 0 =
    synthetisch geen-btw); ontbrekend/onbekend → `OdooKoppelFout` "Rekening-mapping onvolledig … niets
    opgeslagen". Bron per rij = de voorstel-reden als de mens het voorstel volgde, anders 'handmatig'.
    Een invoer-rij voor een RLZ-id dat niet in gebruik is, wordt geweigerd (de tabel is wat de mens zag)."""
    from app.odoo.service import OdooKoppelFout  # lokaal: service importeert deze module

    inv = invoer or MappingInvoer()
    gekozen_gb = {r.rlz_id: int(r.odoo_id) for r in inv.grootboek}
    gekozen_btw = {r.rlz_id: int(r.odoo_id) for r in inv.btw}
    odoo_gb_per_id = {o.odoo_id: o for o in odoo_grootboek}
    odoo_btw_per_id = {o.odoo_id: o for o in odoo_btw}

    onbekend_gb = sorted(set(gekozen_gb) - {r.rlz.rlz_id for r in grootboek}, key=str)
    onbekend_btw = sorted(set(gekozen_btw) - {r.rlz.rlz_id for r in btw}, key=str)
    if onbekend_gb or onbekend_btw:
        raise OdooKoppelFout(
            f"Rekening-mapping bevat {len(onbekend_gb)} grootboekrekening(en) en {len(onbekend_btw)} btw-tarief(en) "
            "die niet in gebruik zijn bij deze administratie — herlaad het voorstel; niets opgeslagen"
        )

    rijen: list[MappingRij] = []
    mist_gb = 0
    mist_btw = 0
    for rij in grootboek:
        odoo_id = gekozen_gb.get(rij.rlz.rlz_id)
        doel = odoo_gb_per_id.get(odoo_id) if odoo_id is not None else None
        if doel is None:
            mist_gb += 1
            continue
        bron = rij.reden if (rij.voorstel is not None and rij.voorstel.odoo_id == doel.odoo_id) else BRON_HANDMATIG
        rijen.append(
            MappingRij(
                soort=SOORT_GROOTBOEK,
                rlz_id=rij.rlz.rlz_id,
                rlz_code=rij.rlz.code,
                rlz_naam=rij.rlz.naam,
                odoo_lokaal_id=doel.lokaal_id,
                odoo_id=doel.odoo_id,
                odoo_code=doel.code,
                odoo_naam=doel.naam,
                bron=bron or BRON_HANDMATIG,
            )
        )
    for brij in btw:
        odoo_id = gekozen_btw.get(brij.rlz.rlz_id)
        tdoel = odoo_btw_per_id.get(odoo_id) if odoo_id is not None else None
        if tdoel is None:
            mist_btw += 1
            continue
        bron = brij.reden if (brij.voorstel is not None and brij.voorstel.odoo_id == tdoel.odoo_id) else BRON_HANDMATIG
        rijen.append(
            MappingRij(
                soort=SOORT_BTW,
                rlz_id=brij.rlz.rlz_id,
                rlz_code=None,
                rlz_naam=brij.rlz.naam,
                odoo_lokaal_id=tdoel.lokaal_id,
                odoo_id=tdoel.odoo_id,
                odoo_code=None,
                odoo_naam=tdoel.naam,
                bron=bron or BRON_HANDMATIG,
            )
        )
    if mist_gb or mist_btw:
        raise OdooKoppelFout(
            f"Rekening-mapping onvolledig: {mist_gb} grootboekrekening(en) en {mist_btw} btw-tarief(en) zonder "
            "Odoo-tegenhanger — niets opgeslagen"
        )
    return rijen


def _compact(rijen: list[MappingRij]) -> list[str]:
    uit: list[str] = []
    for r in rijen:
        links = r.rlz_code or r.rlz_naam or str(r.rlz_id)
        rechts = r.odoo_code or r.odoo_naam or str(r.odoo_id)
        uit.append(f"{r.soort}:{links}→{rechts}")
    return uit


def schrijf_mapping(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    company_id: int,
    rijen: list[MappingRij],
    actor_id: uuid.UUID,
    versie: int = 1,
) -> int:
    """De gevalideerde rijen als versie `versie` + audit `odoo_rekening_mapping_vastgelegd` (tellingen per
    soort/bron + de rijen compact rlz_code→odoo_code; nooit de key). Retourneert het aantal rijen."""
    per_bron: dict[str, int] = {}
    for r in rijen:
        per_bron[r.bron] = per_bron.get(r.bron, 0) + 1
        session.add(
            OdooRekeningMapping(
                administratie_id=administratie_id,
                soort=r.soort,
                rlz_id=r.rlz_id,
                rlz_code=r.rlz_code,
                rlz_naam=r.rlz_naam,
                odoo_lokaal_id=r.odoo_lokaal_id,
                odoo_id=r.odoo_id,
                odoo_code=r.odoo_code,
                odoo_naam=r.odoo_naam,
                bron=r.bron,
                versie=versie,
                bevestigd_door=actor_id,
            )
        )
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="odoo_rekening_mapping",
        record_id=administratie_id,
        actie="odoo_rekening_mapping_vastgelegd",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "company_id": int(company_id),
            "versie": versie,
            "grootboek": sum(1 for r in rijen if r.soort == SOORT_GROOTBOEK),
            "btw": sum(1 for r in rijen if r.soort == SOORT_BTW),
            "per_bron": per_bron,
            "rijen": _compact(rijen),
        },
        administratie_id=administratie_id,
    )
    return len(rijen)


# ----------------------------------------------------------------------------- lezen + vertalen


def _geldende_rijen(session: Session, administratie_id: uuid.UUID) -> list[OdooRekeningMapping]:
    """Hoogste versie per (soort, rlz_id). Bewust géén module-cache (RLS/actualiteit): gewoon per aanroep."""
    rijen = session.scalars(
        select(OdooRekeningMapping)
        .where(OdooRekeningMapping.administratie_id == administratie_id)
        .order_by(OdooRekeningMapping.soort, OdooRekeningMapping.rlz_id, OdooRekeningMapping.versie)
    ).all()
    geldend: dict[tuple[str, uuid.UUID], OdooRekeningMapping] = {}
    for r in rijen:
        geldend[(r.soort, r.rlz_id)] = r  # oplopend op versie → de laatste wint
    return list(geldend.values())


def geldende_mapping(session: Session, administratie_id: uuid.UUID) -> RekeningMapping:
    grootboek: dict[uuid.UUID, uuid.UUID] = {}
    btw: dict[uuid.UUID, uuid.UUID] = {}
    for r in _geldende_rijen(session, administratie_id):
        (grootboek if r.soort == SOORT_GROOTBOEK else btw)[r.rlz_id] = r.odoo_lokaal_id
    return RekeningMapping(grootboek=grootboek, btw=btw)


def vertaal_observaties(observaties: list[Observatie], mapping: RekeningMapping) -> list[Observatie]:
    """Puur: gb_id ∈ mapping.grootboek → vertaald; die observatie krijgt btw_id via mapping.btw (niet
    vertaalbaar → None) en project_id None (RLZ-project ≠ Odoo-analytic-account). gb_id ∉ mapping =
    ongewijzigd (Odoo-era-observatie). bron/bron_datum/regel_sleutel — en daarmee `app_bevestigd` in de
    engine — blijven exact wat ze waren."""
    if mapping.leeg:
        return observaties
    uit: list[Observatie] = []
    for o in observaties:
        doel = mapping.grootboek.get(o.gb_id)
        if doel is None:
            uit.append(o)
            continue
        uit.append(
            replace(
                o,
                gb_id=doel,
                btw_id=mapping.btw.get(o.btw_id) if o.btw_id is not None else None,
                project_id=None,
            )
        )
    return uit


def vertaal_regel_observaties(observaties: list[RegelObservatie], mapping: RekeningMapping) -> list[RegelObservatie]:
    """Idem voor het regel-niveau-geheugen (`regel_gb.RegelObservatie` draagt alleen gb_id)."""
    if mapping.leeg:
        return observaties
    return [replace(o, gb_id=mapping.grootboek[o.gb_id]) if o.gb_id in mapping.grootboek else o for o in observaties]


def _odoo_lijsten_uit_cache(
    session: Session, administratie_id: uuid.UUID
) -> tuple[list[OdooRekening], list[OdooTarief]]:
    """De Odoo-keuzelijsten uit de gesyncte cache (niet-verdwenen rijen mét een `odoo_id_koppeling`)."""
    koppelingen = {
        (k.model, k.lokaal_id): k
        for k in session.scalars(
            select(OdooIdKoppeling).where(
                OdooIdKoppeling.administratie_id == administratie_id,
                OdooIdKoppeling.model.in_([odoo_sync.MODEL_ACCOUNT, odoo_sync.MODEL_TAX]),
            )
        )
    }
    rekeningen: list[OdooRekening] = []
    for g in session.scalars(
        select(Grootboekrekening)
        .where(
            Grootboekrekening.administratie_id == administratie_id, Grootboekrekening.verdwenen_uit_bron_op.is_(None)
        )
        .order_by(Grootboekrekening.code)
    ):
        k = koppelingen.get((odoo_sync.MODEL_ACCOUNT, g.ledger_id))
        if k is None:
            continue  # RLZ-rij (nog niet verdwenen gemarkeerd) — geen Odoo-rekening
        rekeningen.append(
            OdooRekening(odoo_id=k.odoo_id, lokaal_id=g.ledger_id, code=g.code, naam=g.naam, soort=g.soort)
        )
    tarieven: list[OdooTarief] = []
    for t in session.scalars(
        select(TaxRateCache)
        .where(TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None))
        .order_by(TaxRateCache.naam)
    ):
        k = koppelingen.get((odoo_sync.MODEL_TAX, t.id))
        if k is None:
            continue
        verlegd, _ = taxrate_vlaggen(t.brondata)
        synthetisch = k.odoo_id == GEEN_BTW_ODOO_ID
        if synthetisch:
            pct = Decimal("0")
        elif verlegd:
            pct = (_decimal((t.brondata or {}).get("odoo_amount")) or Decimal("0")) / Decimal(100)
        else:
            pct = t.percentage if t.percentage is not None else Decimal("0")
        tarieven.append(
            OdooTarief(
                odoo_id=k.odoo_id,
                lokaal_id=t.id,
                naam=t.naam or "",
                percentage=_norm(pct) or Decimal("0"),
                verlegd=verlegd,
                favoriet=bool((t.brondata or {}).get("IsFavorite")),
                synthetisch=synthetisch,
            )
        )
    return rekeningen, tarieven


def _namen(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {g.id: g.naam for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(list(ids))))}


def mapping_stand(administratie_id: uuid.UUID) -> MappingStand:
    """Voor `GET …/odoo/mapping`: geldende rijen (mét naam van de bevestiger) + de Odoo-keuzelijsten uit de
    cache + laatst bevestigd. Geen koppeling → `GeenOdooKoppeling` (router: 404)."""
    with scoped_session(administratie_id) as session:
        if session.get(OdooKoppeling, administratie_id) is None:
            raise GeenOdooKoppeling("Deze administratie heeft geen Odoo-koppeling")
        geldend = _geldende_rijen(session, administratie_id)
        namen = _namen(session, {r.bevestigd_door for r in geldend})
        rijen = [
            MappingRij(
                soort=r.soort,
                rlz_id=r.rlz_id,
                rlz_code=r.rlz_code,
                rlz_naam=r.rlz_naam,
                odoo_lokaal_id=r.odoo_lokaal_id,
                odoo_id=r.odoo_id,
                odoo_code=r.odoo_code,
                odoo_naam=r.odoo_naam,
                bron=r.bron,
                versie=r.versie,
                bevestigd_op=r.bevestigd_op,
                bevestigd_door=r.bevestigd_door,
                bevestigd_door_naam=namen.get(r.bevestigd_door),
            )
            for r in geldend
        ]
        odoo_gb, odoo_btw = _odoo_lijsten_uit_cache(session, administratie_id)
        laatste = max(geldend, key=lambda r: r.bevestigd_op) if geldend else None
    grootboek = sorted(
        (r for r in rijen if r.soort == SOORT_GROOTBOEK),
        key=lambda r: (r.rlz_code is None, r.rlz_code or "", str(r.rlz_id)),
    )
    btw = sorted((r for r in rijen if r.soort == SOORT_BTW), key=lambda r: (r.rlz_naam or "", str(r.rlz_id)))
    return MappingStand(
        grootboek=grootboek,
        btw=btw,
        odoo_grootboek=odoo_gb,
        odoo_btw=odoo_btw,
        laatst_bevestigd_op=laatste.bevestigd_op if laatste else None,
        laatst_bevestigd_door_naam=namen.get(laatste.bevestigd_door) if laatste else None,
    )


# ----------------------------------------------------------------------------- overstap-voorbereiding


def voorbereid_overstap(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, odoo_url: str, api_key: str, company_id: int
) -> OverstapVoorbereiding:
    """Stap vóór de overstap: dezelfde voorvalidaties als `koppel_overstap` (RLZ-administratie, actief, geen
    koppeling, company vrij) + probe groen (anders `OdooKoppelFout` mét rapport) → LIVE read-only Odoo-
    grootboek/-btw → RLZ in-gebruik-rijen → deterministisch voorstel. Niets persistent, geen sync."""
    from app.odoo import service  # lokaal: service importeert deze module in koppel_overstap

    url = odoo_url.rstrip("/")
    service.toets_overstap_voorwaarden(administratie_id=administratie_id, url=url, company_id=int(company_id))
    p = service.probe_voor(odoo_url=url, api_key=api_key, company_id=int(company_id))
    if not p.groen:
        raise service.OdooKoppelFout(
            f"Rechten-probe niet groen — overstap niet voorbereid. company {company_id} ({p.company_naam or '?'}): "
            f"{p.rode_regels()}",
            rapport=p.rapport,
        )
    odoo_gb, odoo_btw = lees_live_odoo_stamgegevens(odoo_url=url, api_key=api_key, company_id=int(company_id))
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rlz_gb, rlz_btw = rlz_in_gebruik(session, administratie_id)
    return OverstapVoorbereiding(
        company_naam=p.company_naam,
        probe=p.rapport,
        grootboek=bepaal_grootboek_voorstel(rlz_gb, odoo_gb),
        btw=bepaal_btw_voorstel(rlz_btw, odoo_btw),
        odoo_grootboek=odoo_gb,
        odoo_btw=odoo_btw,
    )


# ----------------------------------------------------------------------------- correctie per rij


def corrigeer_rij(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, soort: str, rlz_id: uuid.UUID, odoo_id: int
) -> MappingStand:
    """Correctie ná de overstap: toetst `odoo_id` tegen de gesyncte `odoo_id_koppeling` (account.account /
    account.tax van déze administratie; 0 = synthetisch geen-btw, alleen bij soort btw), schrijft een nieuwe
    rij versie+1 mét bron 'handmatig' en audit `odoo_rekening_mapping_gecorrigeerd` oud→nieuw. Bestaat er
    nog geen rij voor (soort, rlz_id) — een RLZ-rekening die pas ná de overstap in gebruik bleek — dan
    wordt versie 1 geschreven (additief; nooit stil)."""
    from app.odoo.service import OdooKoppelFout  # lokaal

    if soort not in SOORTEN:
        raise OdooKoppelFout(f"Onbekende mapping-soort '{soort}' — kies 'grootboek' of 'btw'")
    odoo_id = int(odoo_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        koppeling = session.get(OdooKoppeling, administratie_id)
        if koppeling is None:
            raise GeenOdooKoppeling("Deze administratie heeft geen Odoo-koppeling")
        model = odoo_sync.MODEL_ACCOUNT if soort == SOORT_GROOTBOEK else odoo_sync.MODEL_TAX
        odoo_code: str | None = None
        odoo_naam: str | None
        if odoo_id == GEEN_BTW_ODOO_ID:
            if soort != SOORT_BTW:
                raise OdooKoppelFout("Odoo-id 0 (geen btw) bestaat alleen voor btw-tarieven, niet voor grootboek")
            lokaal = odoo_uuid(koppeling.company_id, model, GEEN_BTW_ODOO_ID)
            odoo_naam = "Geen btw (0%)"
        else:
            idk = session.get(OdooIdKoppeling, (administratie_id, model, odoo_id))
            if idk is None:
                raise OdooKoppelFout(
                    f"Odoo-{'rekening' if soort == SOORT_GROOTBOEK else 'btw-code'} {odoo_id} is niet bekend in de "
                    "gesyncte stamgegevens van deze administratie — sync de stamgegevens eerst"
                )
            lokaal = idk.lokaal_id
            odoo_naam = idk.naam
            if soort == SOORT_GROOTBOEK:
                g = session.get(Grootboekrekening, (lokaal, administratie_id))
                if g is not None:
                    odoo_code, odoo_naam = g.code, g.naam
            else:
                t = session.get(TaxRateCache, (lokaal, administratie_id))
                if t is not None and t.naam:
                    odoo_naam = t.naam

        huidig = next(
            (r for r in _geldende_rijen(session, administratie_id) if r.soort == soort and r.rlz_id == rlz_id), None
        )
        rlz_code = huidig.rlz_code if huidig is not None else None
        rlz_naam = huidig.rlz_naam if huidig is not None else None
        if huidig is None:
            if soort == SOORT_GROOTBOEK:
                g_rlz = session.get(Grootboekrekening, (rlz_id, administratie_id))
                if g_rlz is not None:
                    rlz_code, rlz_naam = g_rlz.code, g_rlz.naam
            else:
                t_rlz = session.get(TaxRateCache, (rlz_id, administratie_id))
                if t_rlz is not None:
                    rlz_naam = t_rlz.naam
        versie = (huidig.versie + 1) if huidig is not None else 1
        session.add(
            OdooRekeningMapping(
                administratie_id=administratie_id,
                soort=soort,
                rlz_id=rlz_id,
                rlz_code=rlz_code,
                rlz_naam=rlz_naam,
                odoo_lokaal_id=lokaal,
                odoo_id=odoo_id,
                odoo_code=odoo_code,
                odoo_naam=odoo_naam,
                bron=BRON_HANDMATIG,
                versie=versie,
                bevestigd_door=actor_id,
            )
        )
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="odoo_rekening_mapping",
            record_id=administratie_id,
            actie="odoo_rekening_mapping_gecorrigeerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=(
                {
                    "soort": soort,
                    "rlz_id": str(rlz_id),
                    "rlz_code": huidig.rlz_code,
                    "odoo_id": huidig.odoo_id,
                    "odoo_code": huidig.odoo_code,
                    "odoo_naam": huidig.odoo_naam,
                    "bron": huidig.bron,
                    "versie": huidig.versie,
                }
                if huidig is not None
                else None
            ),
            nieuwe_waarde={
                "soort": soort,
                "rlz_id": str(rlz_id),
                "rlz_code": rlz_code,
                "odoo_id": odoo_id,
                "odoo_code": odoo_code,
                "odoo_naam": odoo_naam,
                "bron": BRON_HANDMATIG,
                "versie": versie,
            },
            administratie_id=administratie_id,
        )
    return mapping_stand(administratie_id)
