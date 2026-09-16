"""LEES-ONLY nulmeting activa (opdracht Peter 16-09, blok C): per RLZ-administratie de MVA-rekeningen (RLZ-vlag
`IsFixedAssetAccount` ÉN AccountType 3 ÉN code in de 0xxx-reeks — de vlag alleen is te breed, STAP-0 a9), het saldo
per rekening (Σ Debit − Σ Credit over `JournalEntryLines`, gepagineerd), het aantal FixedAssets in het register en het
aantal door de MODULE geboekte inkoopfactuurregels op die rekeningen in de laatste N dagen (mét bedrag). Antwoord op
"hoeveel activa staan er wél op de balans maar niet in de activamodule". Geen writes; een 403 op FixedAssets (recht
ontbreekt, casus Universal) is een uitkomst, geen fout; Odoo-administraties zichtbaar overgeslagen (rapport RLZ-only).
Nameting: `scripts/gcp/nameting.sh activa-nulmeting [--dagen 400] [--administratie <uuid|naamdeel>]`. Calls per
administratie: 1 (Ledgers) + 1 (FixedAssets) + ≤ 5 per MVA-rekening."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.backends.registry import Backend, backend_voor
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.rlz.client import RlzApiError, RlzClient, bedrag_cent_exact
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.tijd import vandaag_nl

STANDAARD_DAGEN = 400
MAX_PAGINAS_PER_REKENING = 10


def is_mva_rekening(rij: dict[str, Any]) -> bool:
    """De drie voorwaarden uit STAP-0 a9: vlag + balans-activa (AccountType 3) + code in de 0xxx-reeks."""
    code = str(rij.get("AccountNumber") or "")
    return (
        bool(rij.get("IsFixedAssetAccount"))
        and rij.get("AccountType") == 3
        and code.startswith("0")
        and not rij.get("IsTotalAccount")
    )


@dataclass
class RekeningMeting:
    ledger_id: str
    code: str
    naam: str
    saldo: Decimal | None = None
    regels_gelezen: int = 0
    module_regels: int = 0
    module_bedrag: Decimal = Decimal("0.00")
    fout: str | None = None


@dataclass
class AdministratieMeting:
    administratie_id: uuid.UUID
    naam: str
    overgeslagen: str | None = None
    fout: str | None = None
    fixed_assets: int | None = None
    fixed_assets_fout: str | None = None
    rekeningen: list[RekeningMeting] = field(default_factory=list)
    calls: int = 0


def saldo_rlz(client: RlzClient, ledger_id: str) -> tuple[Decimal, int, int]:
    """(saldo Debit−Credit, regels gelezen, calls) — gepagineerd, begrensd."""
    saldo = Decimal("0.00")
    regels = calls = 0
    for pagina in range(MAX_PAGINAS_PER_REKENING):
        params = {"$filter": f"Account/id eq {ledger_id}", "$top": "200", "$skip": str(pagina * 200)}
        deel = client.get("JournalEntryLines", params=params).get("value", [])
        calls += 1
        for r in deel:
            saldo += (bedrag_cent_exact(r.get("DebitAmount")) or Decimal(0)) - (
                bedrag_cent_exact(r.get("CreditAmount")) or Decimal(0)
            )
        regels += len(deel)
        if len(deel) < 200:
            break
    return saldo, regels, calls


def meet_administratie(
    administratie_id: uuid.UUID, *, dagen: int = STANDAARD_DAGEN, client: RlzClient | None = None
) -> AdministratieMeting:
    with scoped_session(None) as session:
        adm = session.get(Administratie, administratie_id)
        naam = adm.naam if adm is not None else str(administratie_id)
    m = AdministratieMeting(administratie_id=administratie_id, naam=naam)
    if backend_voor(administratie_id) == Backend.ODOO:
        m.overgeslagen = "Odoo-administratie — nulmeting is RLZ-only (Odoo company 3: 0 activa, STAP-0 §13)"
        return m
    eigen_client = client is None
    if client is None:
        try:
            rid = rlz_admin_id_voor(administratie_id)
            client = client_voor_rlz_admin_id(rid).for_administration(rid)
        except Exception as exc:  # noqa: BLE001 — geen credential = zichtbare uitkomst
            m.overgeslagen = f"geen RLZ-verbinding: {exc}"
            return m
    try:
        try:
            ledgers = client.get("Ledgers", params={"$filter": "IsFixedAssetAccount eq true"}).get("value", [])
            m.calls += 1
        except RlzApiError as exc:
            m.fout = f"Ledgers niet leesbaar: HTTP {exc.status_code}"
            return m
        for rij in ledgers:
            if is_mva_rekening(rij):
                m.rekeningen.append(
                    RekeningMeting(
                        ledger_id=str(rij.get("id")),
                        code=str(rij.get("AccountNumber")),
                        naam=str(rij.get("Description")),
                    )
                )
        try:
            fa = client.get("FixedAssets", params={"$count": "true", "$top": "1"})
            m.calls += 1
            m.fixed_assets = int(fa.get("@odata.count") or len(fa.get("value", [])))
        except RlzApiError as exc:
            m.fixed_assets_fout = "recht ontbreekt (403)" if exc.status_code == 403 else f"HTTP {exc.status_code}"
        for rek in m.rekeningen:
            try:
                rek.saldo, rek.regels_gelezen, calls = saldo_rlz(client, rek.ledger_id)
                m.calls += calls
            except RlzApiError as exc:
                rek.fout = f"saldo niet leesbaar: HTTP {exc.status_code}"
    finally:
        if eigen_client:
            client.close()
    if m.rekeningen:
        vanaf = vandaag_nl() - timedelta(days=dagen)
        ids = {uuid.UUID(r.ledger_id): r for r in m.rekeningen}
        with scoped_session(administratie_id) as session:
            rijen = session.execute(
                select(
                    BoekvoorstelRegel.ledger_id,
                    func.count(),
                    func.coalesce(func.sum(BoekvoorstelRegel.netto_bedrag), 0),
                )
                .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
                .join(Document, Document.id == Boekvoorstel.document_id)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                    Document.status == DocumentStatus.GEBOEKT,
                    Boekvoorstel.factuurdatum >= vanaf,
                    BoekvoorstelRegel.ledger_id.in_(list(ids)),
                )
                .group_by(BoekvoorstelRegel.ledger_id)
            ).all()
        for ledger_id, n, som in rijen:
            rek = ids[ledger_id]
            rek.module_regels = int(n)
            rek.module_bedrag = Decimal(str(som)).quantize(Decimal("0.01"))
    return m


def meet(
    *, dagen: int = STANDAARD_DAGEN, administratie_ids: list[uuid.UUID] | None = None
) -> list[AdministratieMeting]:
    with scoped_session(None) as session:
        q = select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
        if administratie_ids:
            q = q.where(Administratie.id.in_(administratie_ids))
        ids = list(session.scalars(q))
    uit: list[AdministratieMeting] = []
    for aid in ids:
        try:
            uit.append(meet_administratie(aid, dagen=dagen))
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de meting niet
            uit.append(AdministratieMeting(administratie_id=aid, naam=str(aid), fout=str(exc)))
    return uit


def print_rapport(metingen: list[AdministratieMeting], *, dagen: int, stdout=print) -> None:
    met_rek = [m for m in metingen if m.rekeningen]
    stdout(
        f"activa-nulmeting (lees-only, module-regels laatste {dagen} dagen): {len(metingen)} administratie(s), "
        f"{len(met_rek)} met MVA-rekeningen, {sum(len(m.rekeningen) for m in metingen)} MVA-rekeningen, "
        f"{sum(m.fixed_assets or 0 for m in metingen)} activa in de RLZ-registers, "
        f"{sum(r.module_regels for m in metingen for r in m.rekeningen)} module-regels op MVA-rekeningen"
    )
    for m in metingen:
        if m.overgeslagen:
            stdout(f"  OVERGESLAGEN {m.naam}: {m.overgeslagen}")
            continue
        if m.fout:
            stdout(f"  FOUT         {m.naam}: {m.fout}")
            continue
        register = f"{m.fixed_assets} activa" if m.fixed_assets is not None else f"register: {m.fixed_assets_fout}"
        stdout(f"  {m.naam}: {len(m.rekeningen)} MVA-rekening(en), {register}, {m.calls} calls")
        for r in m.rekeningen:
            saldo = f"€ {r.saldo}" if r.saldo is not None else (r.fout or "?")
            stdout(
                f"    - {r.code} {r.naam}: saldo {saldo} ({r.regels_gelezen} regels), "
                f"module {r.module_regels} regel(s) € {r.module_bedrag}"
            )
