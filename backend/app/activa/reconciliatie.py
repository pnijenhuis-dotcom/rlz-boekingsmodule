"""Reconciliatieblok `activa` (ontwerp §1, fase 1; contract als `projecten/nummer.cli_blok`): per RLZ-administratie mét
≥ 1 `is_activa`-rekening de aansluiting module-boekingen ↔ RLZ-activaregister.

Soorten (alle sinds 21-09 in stand `meten` — `soort_stand.REGISTRY`; promotie ná de meting, Beheerder):
- `activa_register_niet_leesbaar` — `FixedAssets` 403: actie "RLZ-recht 'Vaste activa' op de webservice-login zetten".
- `mva_boeking_zonder_activum` — module-geboekte inkoopregel op een MVA-rekening ≥ grens (factuurdatum ≥ 2026-01-01)
  zonder koppeling `aangemaakt` én zonder register-activum mét gelijk `TotalAmountPurchase` ± 30 dagen: actie "Activum
  aanmaken op het controlescherm".
- `activum_zonder_boeking` — register-activum (PurchaseDate ≥ 2026-01-01) zonder koppeling en zonder module-regel mét
  gelijk bedrag ± 30 dagen: actie "boeking controleren in RLZ".
- `afschrijving_niet_gelopen` — CurrentDepreciationValue 0, PurchaseDate ≤ vandaag − 12 maanden, boekwaarde > 0.
- `activum_aanmaken_mislukt` — koppelingen `mislukt` mét herkomst `automatisch` (opt-in-pad): actie "Opnieuw aanmaken".
- `activum_aanmaken_mislukt_mens` — koppelingen `mislukt` mét herkomst `mens` (BUG 24-09, BLOw 23-09): een mens koos
  bewust "Activum aanmaken" en de handeling is niet uitgevoerd → DIRECT in `actie` (actiemail, handeling "Opnieuw
  aanmaken" op de rij = de bestaande route `POST …/activa-voorstel/{regel}/aanmaken`), nooit `meten`.
Odoo-administraties: zichtbaar overgeslagen (fase 1 = RLZ). Geen credential = zichtbare FOUT-regel, nooit stil.
De vergelijking is pure code (`toets`) — testbaar zonder DB of RLZ.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activa import instelling as instelling_service
from app.activa import register
from app.activa.models import ActivumKoppeling, KoppelingHerkomst, KoppelingStatus
from app.activa.register import Activum
from app.db.models import Grootboekrekening
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

BLOK = "activa"
SOORT_REGISTER_NIET_LEESBAAR = "activa_register_niet_leesbaar"
SOORT_BOEKING_ZONDER_ACTIVUM = "mva_boeking_zonder_activum"
SOORT_ACTIVUM_ZONDER_BOEKING = "activum_zonder_boeking"
SOORT_AFSCHRIJVING_NIET_GELOPEN = "afschrijving_niet_gelopen"
SOORT_AANMAKEN_MISLUKT = "activum_aanmaken_mislukt"
SOORT_AANMAKEN_MISLUKT_MENS = "activum_aanmaken_mislukt_mens"
SOORTEN = (
    SOORT_REGISTER_NIET_LEESBAAR,
    SOORT_BOEKING_ZONDER_ACTIVUM,
    SOORT_ACTIVUM_ZONDER_BOEKING,
    SOORT_AFSCHRIJVING_NIET_GELOPEN,
    SOORT_AANMAKEN_MISLUKT,
    SOORT_AANMAKEN_MISLUKT_MENS,
)
#: Alleen boekingen/activa van dit boekjaar en later — het register van vóór de module is geen
#: module-verantwoordelijkheid.
VANAF = date(2026, 1, 1)
VENSTER = timedelta(days=30)
AFSCHRIJVING_NA = timedelta(days=365)

HANDELING = {
    SOORT_REGISTER_NIET_LEESBAAR: "RLZ-recht 'Vaste activa' op de webservice-login zetten",
    SOORT_BOEKING_ZONDER_ACTIVUM: "Activum aanmaken op het controlescherm",
    SOORT_ACTIVUM_ZONDER_BOEKING: "boeking controleren in RLZ",
    SOORT_AFSCHRIJVING_NIET_GELOPEN: "afschrijving in RLZ controleren (methode/startmaand)",
    SOORT_AANMAKEN_MISLUKT: "Opnieuw aanmaken op het controlescherm",
    SOORT_AANMAKEN_MISLUKT_MENS: "Opnieuw aanmaken (knop op deze rij of op het controlescherm)",
}


@dataclass(frozen=True)
class ModuleRegel:
    document_id: uuid.UUID
    regel_volgnummer: int
    boek_cyclus: int
    referentie: str | None
    leverancier_naam: str | None
    ledger_code: str
    ledger_naam: str
    netto: Decimal
    factuurdatum: date
    koppeling_status: str | None
    koppeling_rlz_id: uuid.UUID | None


@dataclass(frozen=True)
class MislukteKoppeling:
    koppeling_id: uuid.UUID
    document_id: uuid.UUID
    regel_volgnummer: int
    #: `mens` = bevestigde handeling niet uitgevoerd → soort `_mens`, direct actie (BUG 24-09); `automatisch` = meten.
    herkomst: str
    omschrijving: str
    aanschafwaarde: Decimal
    reden: str | None
    referentie: str | None
    leverancier_naam: str | None


@dataclass(frozen=True)
class Afwijking:
    soort: str
    sleutel: str
    tekst: str
    detail: dict = field(default_factory=dict)


def _binnen_venster(a: date | None, b: date | None) -> bool:
    return a is not None and b is not None and abs((a - b).days) <= VENSTER.days


def toets(
    *,
    module_regels: list[ModuleRegel],
    activa: list[Activum] | None,
    mislukt: list[MislukteKoppeling],
    vandaag: date,
) -> list[Afwijking]:
    """Pure vergelijking. `activa=None` = register niet gelezen (alleen de mislukt-toets)."""
    uit: list[Afwijking] = []
    gekoppelde_rlz_ids = {r.koppeling_rlz_id for r in module_regels if r.koppeling_rlz_id is not None}
    if activa is not None:
        for r in module_regels:
            if r.koppeling_status == KoppelingStatus.AANGEMAAKT.value:
                continue
            if any(a.aanschafwaarde == r.netto and _binnen_venster(a.aanschafdatum, r.factuurdatum) for a in activa):
                continue
            uit.append(
                Afwijking(
                    soort=SOORT_BOEKING_ZONDER_ACTIVUM,
                    sleutel=f"{r.document_id}:{r.regel_volgnummer}:{r.boek_cyclus}",
                    tekst=(
                        f"regel {r.regel_volgnummer} op {r.ledger_code} {r.ledger_naam} € {r.netto} "
                        f"({r.leverancier_naam or '?'} {r.referentie or ''}, {r.factuurdatum.isoformat()}) "
                        "zonder activum in RLZ"
                    ),
                    detail={
                        "document_id": str(r.document_id),
                        "regel_volgnummer": r.regel_volgnummer,
                        "leverancier_naam": r.leverancier_naam,
                        "factuurnummer": r.referentie,
                        "ledger_code": r.ledger_code,
                        "ledger_naam": r.ledger_naam,
                        "bedrag": str(r.netto),
                        "factuurdatum": r.factuurdatum.isoformat(),
                        "koppeling_status": r.koppeling_status,
                    },
                )
            )
        for a in activa:
            if a.aanschafdatum is None or a.aanschafdatum < VANAF or a.id in gekoppelde_rlz_ids:
                continue
            if any(
                r.netto == a.aanschafwaarde and _binnen_venster(a.aanschafdatum, r.factuurdatum) for r in module_regels
            ):
                continue
            uit.append(
                Afwijking(
                    soort=SOORT_ACTIVUM_ZONDER_BOEKING,
                    sleutel=str(a.id),
                    tekst=(
                        f"activum nr {a.receipt_number or '?'} '{a.omschrijving}' € {a.aanschafwaarde} "
                        f"({a.aanschafdatum.isoformat()}) zonder module-boeking"
                    ),
                    detail={
                        "rlz_fixed_asset_id": str(a.id),
                        "rlz_receipt_number": a.receipt_number,
                        "omschrijving": a.omschrijving,
                        "bedrag": str(a.aanschafwaarde) if a.aanschafwaarde is not None else None,
                        "aanschafdatum": a.aanschafdatum.isoformat(),
                        "invoice_reference": a.invoice_reference,
                    },
                )
            )
        for a in activa:
            if (
                a.afschrijving_cumulatief is not None
                and a.afschrijving_cumulatief == 0
                and a.aanschafdatum is not None
                and a.aanschafdatum <= vandaag - AFSCHRIJVING_NA
                and a.boekwaarde is not None
                and a.boekwaarde > 0
            ):
                uit.append(
                    Afwijking(
                        soort=SOORT_AFSCHRIJVING_NIET_GELOPEN,
                        sleutel=str(a.id),
                        tekst=(
                            f"activum nr {a.receipt_number or '?'} '{a.omschrijving}' "
                            f"(aanschaf {a.aanschafdatum.isoformat()}, "
                            f"boekwaarde € {a.boekwaarde}) — nog geen afschrijving geboekt"
                        ),
                        detail={
                            "rlz_fixed_asset_id": str(a.id),
                            "rlz_receipt_number": a.receipt_number,
                            "omschrijving": a.omschrijving,
                            "bedrag": str(a.boekwaarde),
                            "aanschafdatum": a.aanschafdatum.isoformat(),
                            "methode_naam": a.methode_naam,
                        },
                    )
                )
    for m in mislukt:
        mens = m.herkomst == KoppelingHerkomst.MENS.value
        uit.append(
            Afwijking(
                soort=SOORT_AANMAKEN_MISLUKT_MENS if mens else SOORT_AANMAKEN_MISLUKT,
                sleutel=str(m.koppeling_id),
                tekst=(
                    f"activum '{m.omschrijving}' € {m.aanschafwaarde} niet aangemaakt"
                    f"{' ná een mens-klik' if mens else ''}: {m.reden or 'onbekende reden'}"
                ),
                detail={
                    "document_id": str(m.document_id),
                    "regel_volgnummer": m.regel_volgnummer,
                    "koppeling_id": str(m.koppeling_id),
                    "herkomst": m.herkomst,
                    "omschrijving": m.omschrijving,
                    "bedrag": str(m.aanschafwaarde),
                    "reden": m.reden,
                    "leverancier_naam": m.leverancier_naam,
                    "factuurnummer": m.referentie,
                },
            )
        )
    return uit


def module_regels(session: Session, *, administratie_id: uuid.UUID, grens: Decimal) -> list[ModuleRegel]:
    """Module-geboekte inkoopfactuurregels op `is_activa`-rekeningen ≥ grens, factuurdatum ≥ VANAF, mét
    koppelingstand."""
    rekeningen = {
        r.ledger_id: r
        for r in session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id, Grootboekrekening.is_activa.is_(True)
            )
        )
    }
    if not rekeningen:
        return []
    rijen = session.execute(
        select(BoekvoorstelRegel, Boekvoorstel)
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status == DocumentStatus.GEBOEKT,
            Boekvoorstel.factuurdatum >= VANAF,
            BoekvoorstelRegel.ledger_id.in_(list(rekeningen)),
            BoekvoorstelRegel.netto_bedrag >= grens,
        )
        .order_by(Boekvoorstel.factuurdatum, BoekvoorstelRegel.volgnummer)
    ).all()
    if not rijen:
        return []
    koppelingen = {
        (k.document_id, k.regel_volgnummer, k.boek_cyclus): k
        for k in session.scalars(select(ActivumKoppeling).where(ActivumKoppeling.administratie_id == administratie_id))
    }
    vendor_ids = {v.vendor_id for _, v in rijen if v.vendor_id is not None}
    namen = (
        {
            vc.id: vc.naam
            for vc in session.scalars(
                select(VendorCache).where(
                    VendorCache.administratie_id == administratie_id, VendorCache.id.in_(list(vendor_ids))
                )
            )
        }
        if vendor_ids
        else {}
    )
    uit: list[ModuleRegel] = []
    for regel, voorstel in rijen:
        rek = rekeningen[regel.ledger_id]
        k = koppelingen.get((regel.document_id, regel.volgnummer, voorstel.boek_cyclus))
        uit.append(
            ModuleRegel(
                document_id=regel.document_id,
                regel_volgnummer=regel.volgnummer,
                boek_cyclus=voorstel.boek_cyclus,
                referentie=voorstel.referentie,
                leverancier_naam=namen.get(voorstel.vendor_id) if voorstel.vendor_id else None,
                ledger_code=rek.code,
                ledger_naam=rek.naam,
                netto=Decimal(regel.netto_bedrag).quantize(Decimal("0.01")),
                factuurdatum=voorstel.factuurdatum,
                koppeling_status=k.status if k is not None else None,
                koppeling_rlz_id=k.rlz_fixed_asset_id if k is not None else None,
            )
        )
    return uit


def mislukte_koppelingen(session: Session, *, administratie_id: uuid.UUID) -> list[MislukteKoppeling]:
    rijen = session.execute(
        select(ActivumKoppeling, Boekvoorstel)
        .join(Boekvoorstel, Boekvoorstel.document_id == ActivumKoppeling.document_id, isouter=True)
        .where(
            ActivumKoppeling.administratie_id == administratie_id,
            ActivumKoppeling.status == KoppelingStatus.MISLUKT.value,
        )
        .order_by(ActivumKoppeling.gewijzigd_op)
    ).all()
    uit: list[MislukteKoppeling] = []
    for k, v in rijen:
        naam = None
        if v is not None and v.vendor_id is not None:
            vc = session.get(VendorCache, (v.vendor_id, administratie_id))
            naam = vc.naam if vc is not None else None
        uit.append(
            MislukteKoppeling(
                koppeling_id=k.id,
                document_id=k.document_id,
                regel_volgnummer=k.regel_volgnummer,
                herkomst=k.herkomst,
                omschrijving=k.omschrijving,
                aanschafwaarde=Decimal(k.aanschafwaarde).quantize(Decimal("0.01")),
                reden=k.reden,
                referentie=v.referentie if v is not None else None,
                leverancier_naam=naam,
            )
        )
    return uit


def _standaard_client(administratie_id: uuid.UUID):  # noqa: ANN202
    rid = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rid).for_administration(rid)


def cli_blok(
    args,  # noqa: ANN001
    verzamelaar=None,  # noqa: ANN001 — app.reconciliatie.run.Verzamelaar | None
    *,
    stdout: Callable[[str], None] = print,
    client_voor: Callable[[uuid.UUID], object] | None = None,
) -> int:
    """Blokfunctie `activa` voor `reconciliatie-alles`. Exit 1 zodra er een afwijking of fout is."""
    from app.backends.registry import Backend, backend_voor
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.reconciliatie.models import BevindingSoort

    client_voor = client_voor or _standaard_client
    with scoped_session(None) as session:
        administraties = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    vandaag = vandaag_nl()
    exit_code = 0
    totaal = 0
    per_soort: dict[str, int] = dict.fromkeys(SOORTEN, 0)
    getoetst = 0

    def meld(*, soort: str, aid: uuid.UUID, naam: str, tekst: str, vingerafdruk: str, detail: dict) -> None:
        if verzamelaar is not None:
            verzamelaar.bevinding(
                soort=soort, administratie_id=aid, vingerafdruk=vingerafdruk, tekst=tekst, detail=detail, blok=BLOK
            )

    for aid, naam in administraties:
        with scoped_session(aid) as session:
            if not instelling_service.heeft_mva_rekeningen(session, aid):
                continue
            stand = instelling_service.lees_stand(session, aid)
            if backend_voor(aid) == Backend.ODOO:
                stdout(f"OVERGESLAGEN {naam}: Odoo-administratie — activa-aansluiting is in fase 1 RLZ-only")
                continue
            regels = module_regels(session, administratie_id=aid, grens=stand.effectieve_grens)
            mislukt = mislukte_koppelingen(session, administratie_id=aid)
        getoetst += 1
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(1)
        activa: list[Activum] | None = None
        try:
            client = client_voor(aid)
        except (GeenRlzCredentials, Exception) as exc:  # noqa: BLE001 — geen credential = zichtbare fout
            tekst = f"FOUT       {naam}: geen RLZ-verbinding voor de activa-toets: {exc}"
            stdout(tekst)
            exit_code = 1
            meld(
                soort=BevindingSoort.FOUT.value,
                aid=aid,
                naam=naam,
                tekst=tekst,
                vingerafdruk=f"{BLOK}:{aid}:verbinding",
                detail={"administratie_naam": naam, "fout": str(exc)},
            )
            client = None
        if client is not None:
            try:
                with scoped_session(aid) as session:
                    # lees-only (verzamelaar None) = niets vastleggen, ook de probe-stand niet (nameting 22-09)
                    leesbaar = instelling_service.probe_register(session, client, aid, schrijf=verzamelaar is not None)
                if leesbaar:
                    activa = register.lees_activa(client)
                else:
                    tekst = (
                        f"AFWIJKING  administratie={aid} soort={SOORT_REGISTER_NIET_LEESBAAR}: "
                        "activaregister in RLZ niet "
                        f"leesbaar (recht ontbreekt) — {HANDELING[SOORT_REGISTER_NIET_LEESBAAR]}"
                    )
                    stdout(f"{tekst}  [{naam}]")
                    exit_code = 1
                    totaal += 1
                    per_soort[SOORT_REGISTER_NIET_LEESBAAR] += 1
                    meld(
                        soort=BevindingSoort.AFWIJKING.value,
                        aid=aid,
                        naam=naam,
                        tekst=tekst,
                        vingerafdruk=f"{BLOK}:{aid}:{SOORT_REGISTER_NIET_LEESBAAR}",
                        detail={
                            "afwijking_soort": SOORT_REGISTER_NIET_LEESBAAR,
                            "administratie_naam": naam,
                            "handeling": HANDELING[SOORT_REGISTER_NIET_LEESBAAR],
                            "mva_regels_module": len(regels),
                        },
                    )
            except (register.RegisterNietLeesbaar, RlzApiError) as exc:
                tekst = f"FOUT       {naam}: activaregister niet gelezen: {exc}"
                stdout(tekst)
                exit_code = 1
                meld(
                    soort=BevindingSoort.FOUT.value,
                    aid=aid,
                    naam=naam,
                    tekst=tekst,
                    vingerafdruk=f"{BLOK}:{aid}:register",
                    detail={"administratie_naam": naam, "fout": str(exc)},
                )
            finally:
                with contextlib.suppress(Exception):
                    client.close()
        for afw in toets(module_regels=regels, activa=activa, mislukt=mislukt, vandaag=vandaag):
            totaal += 1
            per_soort[afw.soort] += 1
            exit_code = 1
            tekst = f"AFWIJKING  administratie={aid} soort={afw.soort}: {afw.tekst} — {HANDELING[afw.soort]}"
            stdout(f"{tekst}  [{naam}]")
            meld(
                soort=BevindingSoort.AFWIJKING.value,
                aid=aid,
                naam=naam,
                tekst=tekst,
                vingerafdruk=f"{BLOK}:{aid}:{afw.soort}:{afw.sleutel}",
                detail={
                    "afwijking_soort": afw.soort,
                    "administratie_naam": naam,
                    "handeling": HANDELING[afw.soort],
                    **afw.detail,
                },
            )
    stdout(
        f"activa-reconciliatie: {getoetst} administratie(s) mét MVA-rekeningen getoetst, {totaal} afwijking(en) — "
        + ", ".join(f"{soort} {n}" for soort, n in per_soort.items())
    )
    return exit_code
