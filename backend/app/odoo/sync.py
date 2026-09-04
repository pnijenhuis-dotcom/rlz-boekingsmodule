"""Stamgegevens-sync Odoo → de BESTAANDE caches (blok A, fase 1): `platform.grootboekrekening`,
`boekhouding.taxrate_cache`/`vendor_cache`/`project_cache` — zelfde upsert + verdwenen-markering als de
RLZ-sync (`app/sync/service.py::_upsert_en_markeer_verdwenen`; lokaal = cache, Odoo = waarheid), plus de
id-vertaaltabel `odoo_id_koppeling` (UUID ↔ Odoo-int per model).

Mapping (STAP-0 §1.5–1.9):
- account.account → grootboek: `code`/`name`, `soort` = RLZ-AccountType-equivalent (1 opbrengsten, 2 kosten,
  3 activa, 4 passiva) afgeleid uit `account_type`; off-balance- en inactieve rekeningen = overgeslagen
  (verdwenen; Odoo 19 kent geen `deprecated`-veld meer — live 03-09); rekeningen zijn bedrijfsgedeeld
  (`company_ids`) — filter op de company.
- account.tax (alleen `type_tax_use = purchase`, fase 1 = inkoop) → taxrate-cache: `percentage` als FRACTIE
  (21.0 → 0.21, canonieke eenheid app/sync/btw.py), brondata mét RLZ-vlagnamen zodat de bestaande
  controlescherm-logica ongewijzigd werkt: `IsRelayed` (verlegd = reverse-charge-repartition: tax-regel mét
  negatieve factor — company 1: "21% R"), `IsFavorite` (de kale "21%"/"9%" — tiebreak in leid_btw_af),
  `IsExcempt` False. Plus één synthetische rij "Geen btw (0%)" (odoo_id 0): 0 %-inkoop = géén tax_ids
  (besluit Peter 02-09; Odoo company 1 heeft geen inkoop-0 %-code).
- res.partner (supplier_rank > 0, company_id in (X, False)) → vendor-cache: `naam`, `is_gearchiveerd` =
  not active, brondata incl. `vat`/`company_registry` (het natuurlijke thuis voor crediteur_kenmerk).
- account.analytic.account (plan "Project", company in (X, False)) → project-cache: `naam` = "[code] name".
Alles per company; nooit hardcoden (tarief-id's verschillen per company — §1.6 (c))."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.odoo.client import OdooClient
from app.odoo.credentials import OdooVerbinding, koppeling_voor, odoo_client_voor
from app.odoo.ids import GEEN_BTW_ODOO_ID, odoo_uuid
from app.odoo.models import OdooIdKoppeling
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from app.sync.service import SyncResultaat, SyncTelling, _upsert_en_markeer_verdwenen

logger = logging.getLogger(__name__)

MODEL_ACCOUNT = "account.account"
MODEL_TAX = "account.tax"
MODEL_PARTNER = "res.partner"
MODEL_ANALYTIC = "account.analytic.account"
MODEL_MOVE = "account.move"
MODEL_PRODUCT = "product.product"

_SOORT_PER_PREFIX: tuple[tuple[str, int], ...] = (
    ("income", 1),
    ("expense", 2),
    ("asset", 3),
    ("liability", 4),
    ("equity", 4),
)


def soort_voor_account_type(account_type: str | None) -> int | None:
    """Odoo `account_type` → RLZ-AccountType-equivalent; None = niet meesyncen (off_balance/onbekend)."""
    if not account_type:
        return None
    for prefix, soort in _SOORT_PER_PREFIX:
        if account_type.startswith(prefix):
            return soort
    return None


def is_verlegd_tarief(tax: dict[str, Any], repartition: dict[int, dict[str, Any]]) -> bool:
    """Reverse charge (STAP-0 §1.6 (b)): de invoice-repartition draagt tax-regels mét een negatieve
    factor (21 % af te dragen én 21 % terug als voorbelasting → netto 0)."""
    for rid in tax.get("invoice_repartition_line_ids") or []:
        regel = repartition.get(int(rid))
        if regel and regel.get("repartition_type") == "tax" and float(regel.get("factor_percent") or 0) < 0:
            return True
    return False


def is_favoriet_tarief(naam: str | None) -> bool:
    """De kale percentage-codes ("21%", "9%") zijn de standaard-inkoopcodes — tiebreak voor leid_btw_af
    tussen tarieven met hetzélfde percentage ("21%", "21% S", "21% O")."""
    n = (naam or "").strip()
    return n.endswith("%") and n[:-1].replace(",", ".").replace(".", "", 1).isdigit()


class _Vertaler:
    """Verzamelt (model, odoo_id, lokaal_uuid, naam) voor odoo_id_koppeling."""

    def __init__(self, company_id: int) -> None:
        self.company_id = company_id
        self.rijen: list[tuple[str, int, uuid.UUID, str | None]] = []

    def lokaal(self, model: str, odoo_id: int, naam: str | None) -> uuid.UUID:
        lokaal_id = odoo_uuid(self.company_id, model, odoo_id)
        self.rijen.append((model, int(odoo_id), lokaal_id, naam))
        return lokaal_id


def _naam(m2o: Any) -> str | None:
    """many2one komt als [id, display_name] (of False)."""
    if isinstance(m2o, list) and len(m2o) == 2:
        return str(m2o[1])
    return None


def _id(m2o: Any) -> int | None:
    if isinstance(m2o, list) and len(m2o) == 2:
        return int(m2o[0])
    return None


# --- lezen --------------------------------------------------------------------------------------


def lees_grootboek(client: OdooClient, vertaler: _Vertaler) -> list[dict[str, Any]]:
    rijen = client.search_read_alles(
        MODEL_ACCOUNT,
        # Odoo 19 kent op account.account geen `deprecated` meer (live 03-09: ValueError "Invalid field") — alleen
        # `active`; de STAP-0-veldenlijst (§1.5) was op dat punt onjuist. Inactieve rekeningen = verdwenen.
        [["company_ids", "in", [client.company_id]], ["active", "=", True]],
        ["code", "name", "account_type", "reconcile", "active", "internal_group"],
        order="code",
    )
    records: list[dict[str, Any]] = []
    for rij in rijen:
        soort = soort_voor_account_type(rij.get("account_type"))
        if soort is None or not rij.get("active", True):
            continue
        records.append(
            {
                "id": str(vertaler.lokaal(MODEL_ACCOUNT, rij["id"], f"{rij['code']} {rij['name']}")),
                "code": str(rij["code"]),
                "naam": str(rij["name"]),
                "soort": soort,
                "odoo_id": int(rij["id"]),
                "account_type": rij.get("account_type"),
            }
        )
    return records


def lees_btw(client: OdooClient, vertaler: _Vertaler) -> list[dict[str, Any]]:
    taxes = client.search_read_alles(
        MODEL_TAX,
        [["company_id", "=", client.company_id], ["type_tax_use", "=", "purchase"], ["active", "=", True]],
        ["name", "amount", "amount_type", "type_tax_use", "invoice_label", "invoice_repartition_line_ids", "active"],
        order="sequence, id",
    )
    rep_ids = sorted({int(r) for t in taxes for r in (t.get("invoice_repartition_line_ids") or [])})
    repartition: dict[int, dict[str, Any]] = {}
    if rep_ids:
        for rij in client.read("account.tax.repartition.line", rep_ids, ["repartition_type", "factor_percent"]):
            repartition[int(rij["id"])] = rij
    records: list[dict[str, Any]] = []
    for t in taxes:
        if t.get("amount_type") != "percent":
            continue  # vaste bedragen/groepen: geen deterministische afleiding — bewust buiten fase 1
        verlegd = is_verlegd_tarief(t, repartition)
        percentage = Decimal(str(t.get("amount") or 0)) / Decimal(100)
        records.append(
            {
                "id": str(vertaler.lokaal(MODEL_TAX, t["id"], t["name"])),
                "Name": t["name"],
                # RLZ-vlagnamen bewust behouden: taxrate_vlaggen()/TaxRateKandidaat lezen déze sleutels.
                "Percentage": str(Decimal("0") if verlegd else percentage),
                "IsRelayed": verlegd,
                "IsExcempt": False,
                "IsFavorite": is_favoriet_tarief(t["name"]) and not verlegd,
                "IsMixed": False,
                "odoo_id": int(t["id"]),
                "odoo_amount": t.get("amount"),
                "type_tax_use": t.get("type_tax_use"),
                "invoice_label": t.get("invoice_label"),
                "backend": "odoo",
            }
        )
    # Synthetische "Geen btw (0%)" — de adapter stuurt hiervoor géén tax_ids (besluit 02-09).
    records.append(
        {
            "id": str(vertaler.lokaal(MODEL_TAX, GEEN_BTW_ODOO_ID, "Geen btw (0%)")),
            "Name": "Geen btw (0%)",
            "Percentage": "0",
            "IsRelayed": False,
            "IsExcempt": False,
            "IsFavorite": True,
            "IsMixed": False,
            "odoo_id": GEEN_BTW_ODOO_ID,
            "synthetisch": True,
            "type_tax_use": "purchase",
            "backend": "odoo",
        }
    )
    return records


def lees_crediteuren(client: OdooClient, vertaler: _Vertaler) -> list[dict[str, Any]]:
    rijen = client.search_read_alles(
        MODEL_PARTNER,
        [
            ["supplier_rank", ">", 0],
            ["company_id", "in", [client.company_id, False]],
            ["active", "in", [True, False]],
        ],
        ["name", "vat", "company_registry", "active", "is_company", "company_id", "ref", "country_id"],
        order="name",
    )
    return [
        {
            "id": str(vertaler.lokaal(MODEL_PARTNER, rij["id"], rij["name"])),
            "Name": rij["name"],
            "IsArchived": not rij.get("active", True),
            "odoo_id": int(rij["id"]),
            "vat": rij.get("vat") or None,
            "company_registry": rij.get("company_registry") or None,
            "gedeeld": not rij.get("company_id"),
            "backend": "odoo",
        }
        for rij in rijen
    ]


def lees_projecten(client: OdooClient, vertaler: _Vertaler, *, plan_id: int | None) -> list[dict[str, Any]]:
    if plan_id is None:
        return []
    rijen = client.search_read_alles(
        MODEL_ANALYTIC,
        [
            ["plan_id", "=", plan_id],
            ["company_id", "in", [client.company_id, False]],
            # Alleen ACTIEVE analytic accounts (live keten-cyclus 04-09: Odoo weigert `action_post` op een
            # gearchiveerde analytische rekening — "Je kunt geen boeking maken met een gearchiveerde analytische
            # rekening"); gearchiveerd = verdwenen uit de bron, zoals bij account.account.
            ["active", "=", True],
        ],
        ["name", "code", "active", "company_id"],
        order="code, name",
    )
    records = []
    for rij in rijen:
        code = rij.get("code") or None
        naam = f"[{code}] {rij['name']}" if code else rij["name"]
        records.append(
            {
                "id": str(vertaler.lokaal(MODEL_ANALYTIC, rij["id"], naam)),
                "Name": naam,
                "IsActive": bool(rij.get("active", True)),
                "odoo_id": int(rij["id"]),
                "code": code,
                "backend": "odoo",
            }
        )
    return records


# --- schrijven (lokale caches) --------------------------------------------------------------------


def _schrijf_id_koppelingen(session, *, administratie_id: uuid.UUID, rijen: Iterable[tuple], now: datetime) -> None:
    bestaande = {
        (r.model, r.odoo_id): r
        for r in session.scalars(select(OdooIdKoppeling).where(OdooIdKoppeling.administratie_id == administratie_id))
    }
    for model, odoo_id, lokaal_id, naam in rijen:
        rij = bestaande.get((model, odoo_id))
        if rij is None:
            session.add(
                OdooIdKoppeling(
                    administratie_id=administratie_id,
                    model=model,
                    odoo_id=odoo_id,
                    lokaal_id=lokaal_id,
                    naam=naam,
                    laatst_gezien_op=now,
                )
            )
        else:
            rij.naam = naam
            rij.laatst_gezien_op = now


def _grootboek_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"code": record["code"], "naam": record["naam"], "soort": record["soort"], "is_totaalrekening": False}


def _taxrate_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"naam": record["Name"], "percentage": Decimal(record["Percentage"]), "brondata": record}


def _vendor_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"naam": record["Name"], "is_gearchiveerd": record["IsArchived"], "brondata": record}


def _project_waarden(record: dict[str, Any]) -> dict[str, Any]:
    return {"naam": record["Name"], "is_actief": record["IsActive"], "brondata": record}


def sync_alles_voor_odoo_administratie(
    *, administratie_id: uuid.UUID, client: OdooClient | None = None, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID
) -> SyncResultaat:
    """Alle vier de stamgegevensbronnen voor één Odoo-administratie mét één verbinding; schrijft de
    caches + de id-koppelingen in één lokale transactie ná het lezen (Odoo-leesfout = niets gewijzigd)."""
    verbinding: OdooVerbinding = koppeling_voor(administratie_id)
    eigen = client is None
    client = client or odoo_client_voor(administratie_id)
    vertaler = _Vertaler(verbinding.company_id)
    try:
        grootboek = lees_grootboek(client, vertaler)
        btw = lees_btw(client, vertaler)
        crediteuren = lees_crediteuren(client, vertaler)
        projecten = lees_projecten(client, vertaler, plan_id=verbinding.analytic_plan_id)
    finally:
        if eigen:
            client.close()

    now = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        resultaat = SyncResultaat(
            ledgers=_upsert_en_markeer_verdwenen(
                session,
                model=Grootboekrekening,
                id_kolom="ledger_id",
                administratie_id=administratie_id,
                verse_rijen=grootboek,
                kolom_waarden=_grootboek_waarden,
                now=now,
            ),
            taxrates=_upsert_en_markeer_verdwenen(
                session,
                model=TaxRateCache,
                id_kolom="id",
                administratie_id=administratie_id,
                verse_rijen=btw,
                kolom_waarden=_taxrate_waarden,
                now=now,
            ),
            vendors=_upsert_en_markeer_verdwenen(
                session,
                model=VendorCache,
                id_kolom="id",
                administratie_id=administratie_id,
                verse_rijen=crediteuren,
                kolom_waarden=_vendor_waarden,
                now=now,
            ),
            projects=_upsert_en_markeer_verdwenen(
                session,
                model=ProjectCache,
                id_kolom="id",
                administratie_id=administratie_id,
                verse_rijen=projecten,
                kolom_waarden=_project_waarden,
                now=now,
            ),
        )
        _schrijf_id_koppelingen(session, administratie_id=administratie_id, rijen=vertaler.rijen, now=now)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="odoo_id_koppeling",
            record_id=administratie_id,
            actie="odoo_stamgegevens_gesynct",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "company_id": verbinding.company_id,
                "grootboek": resultaat.ledgers.__dict__,
                "btw": resultaat.taxrates.__dict__,
                "crediteuren": resultaat.vendors.__dict__,
                "projecten": resultaat.projects.__dict__,
            },
            administratie_id=administratie_id,
        )
    return resultaat


def registreer_id_koppeling(
    session, *, administratie_id: uuid.UUID, company_id: int, model: str, odoo_id: int, naam: str | None
) -> uuid.UUID:
    """Eén nieuwe Odoo-rij (bv. een zojuist aangemaakte partner/product/project) meteen vertaalbaar maken
    zonder volledige sync — zelfde deterministische UUID als de sync zou geven."""
    lokaal_id = odoo_uuid(company_id, model, odoo_id)
    rij = session.get(OdooIdKoppeling, (administratie_id, model, odoo_id))
    if rij is None:
        session.add(
            OdooIdKoppeling(
                administratie_id=administratie_id, model=model, odoo_id=odoo_id, lokaal_id=lokaal_id, naam=naam
            )
        )
    else:
        rij.naam = naam
    return lokaal_id


class OnbekendeOdooId(Exception):
    """Een lokale UUID die niet in odoo_id_koppeling staat — sync eerst; nooit een gok."""


def odoo_id_voor(session, *, administratie_id: uuid.UUID, model: str, lokaal_id: uuid.UUID) -> int:
    rij = session.scalars(
        select(OdooIdKoppeling).where(
            OdooIdKoppeling.administratie_id == administratie_id,
            OdooIdKoppeling.model == model,
            OdooIdKoppeling.lokaal_id == lokaal_id,
        )
    ).one_or_none()
    if rij is None:
        raise OnbekendeOdooId(
            f"{model} {lokaal_id} is niet bekend in de Odoo-koppeling van deze administratie — sync de stamgegevens"
        )
    return rij.odoo_id


def sync_telling_als_dict(telling: SyncTelling) -> dict[str, int]:
    return {"aangemaakt": telling.aangemaakt, "bijgewerkt": telling.bijgewerkt, "verdwenen": telling.verdwenen}
