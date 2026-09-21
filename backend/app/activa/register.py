"""Lezen van het RLZ-activaregister (`FixedAssets`), de afschrijvingsmethodes (`DepreciationMethodHeaders`) en de
activeringsgrens (`AdministrationSettings.FixedAssetAlertAmount`) — lees-only (STAP-0 21-09, Pilates Bloom: 20 activa).

Kernprincipe 1: het register leeft in RLZ. Een 403 op `FixedAssets` (recht "Vaste activa" ontbreekt op de webservice-
login — casus Universal Steigerbouw, Rubicon) is een UITKOMST (`RegisterNietLeesbaar`), nooit een stille fout: de
probe schrijft 'm op `activa_instelling.register_*` en het reconciliatieblok meldt 'm mét handeling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.rlz.client import RlzApiError, bedrag_cent_exact

PAGINA = 200
MAX_PAGINAS = 50  # 10.000 activa — ruim boven élke klant-administratie
TYPE_FIXED = 1


class RegisterNietLeesbaar(Exception):
    """`FixedAssets` gaf 403: het recht ontbreekt op de webservice-login."""


@dataclass(frozen=True)
class Activum:
    id: uuid.UUID
    receipt_number: str | None
    omschrijving: str
    invoice_reference: str | None
    aanschafwaarde: Decimal | None
    aanschafdatum: date | None
    boekwaarde: Decimal | None
    afschrijving_cumulatief: Decimal | None
    type: int | None
    status: int | None
    methode_id: uuid.UUID | None
    methode_naam: str | None
    methode_maanden: int | None


@dataclass(frozen=True)
class Methode:
    id: uuid.UUID
    naam: str
    maanden: int | None
    basis: int | None


def _datum(waarde: Any) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(str(waarde)[:10])
    except ValueError:
        return None


def _uuid(waarde: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def naar_activum(rij: dict[str, Any]) -> Activum:
    methode = rij.get("DepreciationMethod") if isinstance(rij.get("DepreciationMethod"), dict) else {}
    maanden = methode.get("NumberOfMonths")
    return Activum(
        id=uuid.UUID(str(rij["id"])),
        receipt_number=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") is not None else None,
        omschrijving=str(rij.get("Description") or ""),
        invoice_reference=str(rij["InvoiceReference"]) if rij.get("InvoiceReference") else None,
        aanschafwaarde=bedrag_cent_exact(rij.get("TotalAmountPurchase")),
        aanschafdatum=_datum(rij.get("PurchaseDate")),
        boekwaarde=bedrag_cent_exact(rij.get("CurrentBookValue")),
        afschrijving_cumulatief=bedrag_cent_exact(rij.get("CurrentDepreciationValue")),
        type=int(rij["Type"]) if rij.get("Type") is not None else None,
        status=int(rij["Status"]) if rij.get("Status") is not None else None,
        methode_id=_uuid(methode.get("id")),
        methode_naam=str(methode["Description"]) if methode.get("Description") else None,
        methode_maanden=int(maanden) if maanden is not None else None,
    )


def naar_methode(rij: dict[str, Any]) -> Methode:
    maanden = rij.get("NumberOfMonths")
    basis = rij.get("DepreciationBaseMethod")
    if isinstance(basis, dict):
        basis = basis.get("id") if not isinstance(basis.get("id"), str) else None
    return Methode(
        id=uuid.UUID(str(rij["id"])),
        naam=str(rij.get("Description") or ""),
        maanden=int(maanden) if maanden is not None else None,
        basis=int(basis) if isinstance(basis, int) else None,
    )


def lees_activa(client) -> list[Activum]:  # noqa: ANN001 — RlzClient of duck-typed fake
    """Alle activa, gepagineerd ($top 200) mét `$expand=DepreciationMethod`. 403 → RegisterNietLeesbaar."""
    uit: list[Activum] = []
    for pagina in range(MAX_PAGINAS):
        params = {"$expand": "DepreciationMethod", "$top": str(PAGINA), "$skip": str(pagina * PAGINA)}
        try:
            deel = client.get_fixed_assets(params=params)
        except RlzApiError as exc:
            if exc.status_code == 403:
                raise RegisterNietLeesbaar("recht ontbreekt (403) op FixedAssets") from exc
            raise
        for rij in deel:
            uit.append(naar_activum(rij))
        if len(deel) < PAGINA:
            break
    return uit


def lees_methoden(client) -> list[Methode]:  # noqa: ANN001
    return [naar_methode(rij) for rij in client.get_depreciation_method_headers()]


def methode_voor_termijn(methoden: list[Methode], termijn_maanden: int) -> Methode | None:
    """Lineaire RLZ-methode mét exact dit aantal maanden; 'lineair' in de naam óf basis 1. Geen match → None
    (de service zet de koppeling dan zichtbaar op `mislukt`)."""
    kandidaten = [
        m
        for m in methoden
        if m.maanden == termijn_maanden and (m.basis == 1 or "lineair" in m.naam.lower() or m.basis is None)
    ]
    kandidaten.sort(key=lambda m: (0 if "lineair" in m.naam.lower() else 1, m.naam))
    return kandidaten[0] if kandidaten else None


def lees_grens(client) -> Decimal | None:  # noqa: ANN001
    """`AdministrationSettings` (één rij, $top=1) → `FixedAssetAlertAmount`; ontbrekend veld of lege collectie =
    None."""
    rijen = client.get_administration_settings()
    if not rijen:
        return None
    waarde = rijen[0].get("FixedAssetAlertAmount")
    return bedrag_cent_exact(waarde) if waarde is not None else None


def lees_activum(client, activum_id: uuid.UUID) -> Activum | None:  # noqa: ANN001
    """Record-GET ná een PUT (204 zonder body); 404 = None (mislukt)."""
    rij = client.get_fixed_asset(activum_id)
    return naar_activum(rij) if rij else None
