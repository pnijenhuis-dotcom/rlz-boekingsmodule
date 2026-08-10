"""Verkoopvoorstel-servicelaag (Vastly-verkoopfactuur-boekpad, koppelcontract §2d):
het reviewscherm-voorstel per verkoopfactuur-document — prefill deterministisch uit het
UBL-veldvoorstel (geen AI: de UBL ís de gestructureerde bron), GB-code→ledger-resolutie per
administratie, btw-code-match op percentage, opslaan, en de orkestratie van de harde checks
(app/verkoop/checks.py). Zelfde opzet als app/omzet/voorstel.py."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport
from app.documenten.models import Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.documenten.service import DocumentNietGevonden
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync import btw as btw_eenheid
from app.sync.models import TaxRateCache
from app.verkoop import checks as verkoop_checks
from app.verkoop.models import (
    VerkoopBoeking,
    VerkoopBoekingStatus,
    VerkoopBtwVoorkeur,
    VerkoopVoorstel,
    VerkoopVoorstelRegel,
)

logger = logging.getLogger(__name__)

_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class VerkoopVoorstelFout(Exception):
    """Domeinfout in de verkoopvoorstel-servicelaag."""


class GeenVerkoopfactuur(VerkoopVoorstelFout):
    """Het verkoopvoorstel bestaat alleen voor documenten met soort 'verkoopfactuur'."""


@dataclass(frozen=True)
class VerkoopRegelData:
    volgnummer: int
    omschrijving: str | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    gb_code: str | None
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    # 'bekend' (code → ledger geresolved), 'onbekend' (code niet in het rekeningschema —
    # blokkerend, §2d), 'ontbreekt' (geen AccountingCost — mens kiest, geen fout).
    gb_code_status: str
    # Herkomst voor de UI-chips: 'ubl' (deterministisch uit de UBL geresolved) of 'opgeslagen'.
    herkomst: str
    # Factuur-btw (blok A 2026-08-10): de UBL-brongegevens + het resolutieresultaat. Btw is
    # nooit een vrije menselijke waardekeuze — vergrendeld zodra de factuur 'm bepaalt;
    # `btw_kandidaten` draagt bij echte ambiguïteit de toegestane keuzeset (eenmalige keuze,
    # daarna onthouden per administratie).
    btw_categorie: str | None = None
    btw_percentage_ubl: Decimal | None = None
    btw_vergrendeld: bool = False
    # 'factuur' (eenduidige match) of 'onthouden' (ambigu, eerder gekozen) — None = niet
    # deterministisch bepaald (mens kiest).
    btw_bron: str | None = None
    btw_kandidaten: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class BtwResolutie:
    """Uitkomst van de deterministische factuur-btw → RLZ-tarief-afleiding voor één regel."""

    taxrate_id: uuid.UUID | None
    vergrendeld: bool
    bron: str | None  # 'factuur' | 'onthouden' | None
    kandidaten: tuple[uuid.UUID, ...]
    categorie: str | None
    percentage_ubl: Decimal | None


@dataclass(frozen=True)
class VerkoopVoorstelData:
    document_id: uuid.UUID
    debiteur_naam: str | None
    factuurnummer: str | None
    factuurdatum: date | None
    totaalbedrag_incl: Decimal | None
    is_creditnota: bool
    gecrediteerd_factuurnummer: str | None
    regels: list[VerkoopRegelData]
    opgeslagen: bool
    rlz_boekstuknummer: str | None = None


def _laad_verkoopfactuur(session: Session, *, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != DocumentSoort.VERKOOPFACTUUR.value:
        raise GeenVerkoopfactuur(f"Document {document_id} is geen verkoopfactuur (soort: {document.soort})")
    return document


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    return next(
        (
            g.detail["veldvoorstel"]
            for g in reversed(
                list(
                    session.scalars(
                        select(DocumentGebeurtenis)
                        .where(DocumentGebeurtenis.document_id == document_id)
                        .order_by(DocumentGebeurtenis.tijdstip)
                    )
                )
            )
            if g.detail and "veldvoorstel" in g.detail
        ),
        None,
    )


def _als_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _als_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde)
    except ValueError:
        return None


def _resolve_gb_code(
    session: Session, *, administratie_id: uuid.UUID, code: str | None
) -> tuple[uuid.UUID | None, str]:
    """Code → ledger-GUID via de bestaande sync-cache (platform.grootboekrekening, §2d-regel:
    deterministisch lezen, bestaan per administratie controleren). Totaalrekeningen en uit de
    bron verdwenen rekeningen tellen als onbekend — daar mag nooit op geboekt worden."""
    if not (code or "").strip():
        return None, "ontbreekt"
    rijen = session.scalars(
        select(Grootboekrekening).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.code == code.strip(),
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            Grootboekrekening.is_totaalrekening.is_(False),
        )
    ).all()
    if len(rijen) == 1:
        return rijen[0].ledger_id, "bekend"
    return None, "onbekend"


def _resolve_btw(
    session: Session, *, administratie_id: uuid.UUID, categorie: str | None, percentage: str | None
) -> BtwResolutie:
    """Factuur-btw (ClassifiedTaxCategory.ID {S/E/Z/AE} + Percent) → RLZ-tarief, deterministisch
    en NOOIT op percentage alleen (blok A 2026-08-10; eenhedennormalisatie in app/sync/btw.py —
    de cache draagt de fractie, de UBL een percentage). Uitkomsten:

    - precies één actief tarief dekt categorie + percentage → vergrendeld (bron 'factuur');
    - meerdere tarieven dekken 'm (echte ambiguïteit, bv. hoog vs hoog-vooruit) → de per
      administratie onthouden keuze (verkoop_btw_voorkeur) als die nog in de kandidatenset zit
      (bron 'onthouden'), anders kiest de mens één keer uit de kandidaten;
    - geen categorie/onbekende categorie of geen dekkend tarief → niet vergrendeld, mens kiest
      (de harde btw-check blijft de poort: een keuze die de factuur-btw niet dekt blokkeert)."""
    pct = _als_decimal(percentage)
    code = btw_eenheid.normaliseer_categorie(categorie)
    fractie = btw_eenheid.factuur_fractie(code, pct)
    if code is None or fractie is None:
        return BtwResolutie(
            taxrate_id=None, vergrendeld=False, bron=None, kandidaten=(), categorie=code, percentage_ubl=pct
        )
    rijen = session.scalars(
        select(TaxRateCache).where(
            TaxRateCache.administratie_id == administratie_id,
            TaxRateCache.verdwenen_uit_bron_op.is_(None),
        )
    ).all()
    kandidaten = tuple(
        rij.id
        for rij in rijen
        if btw_eenheid.taxrate_dekt_factuur_btw(
            categorie=code,
            factuur_pct=pct,
            taxrate_percentage=rij.percentage,
            is_verlegd=btw_eenheid.taxrate_vlaggen(rij.brondata)[0],
            is_vrijgesteld=btw_eenheid.taxrate_vlaggen(rij.brondata)[1],
        )
    )
    if len(kandidaten) == 1:
        return BtwResolutie(
            taxrate_id=kandidaten[0], vergrendeld=True, bron="factuur",
            kandidaten=kandidaten, categorie=code, percentage_ubl=pct,
        )
    if len(kandidaten) > 1:
        voorkeur = session.get(VerkoopBtwVoorkeur, (administratie_id, code, fractie))
        if voorkeur is not None and voorkeur.taxrate_id in kandidaten:
            return BtwResolutie(
                taxrate_id=voorkeur.taxrate_id, vergrendeld=True, bron="onthouden",
                kandidaten=kandidaten, categorie=code, percentage_ubl=pct,
            )
        return BtwResolutie(
            taxrate_id=None, vergrendeld=False, bron=None,
            kandidaten=kandidaten, categorie=code, percentage_ubl=pct,
        )
    return BtwResolutie(
        taxrate_id=None, vergrendeld=False, bron=None, kandidaten=(), categorie=code, percentage_ubl=pct
    )


def verkoop_omschrijving_vastly(factuurnummer: str, *, is_creditnota: bool) -> str:
    """Deterministische duplicaat-marker van de RLZ-verkoopboeking — functie van het
    Vastly-factuurnummer (niet ons document): een tweede document met hetzelfde nummer raakt
    dezelfde marker en valt daarmee door de Receipts-duplicaatcheck (de collectie ziet óók
    API-documenten — Receipts-verkenning). ⚠️ De marker staat als PREFIX in regel 1 van de
    boeking en de check filtert op startswith: RLZ negeert de document-Description en leidt 'm
    af uit de éérste regel-Description (verkoop-STAP-0 2026-08-09). Twee botsing-waarborgen in
    de vorm zelf: (a) een disjuncte soortprefix (VERKOOP vs CREDIT — startswith op de factuur-
    marker mag nooit de creditnota van hetzelfde nummer matchen), en (b) het afsluitende "·"
    ná het factuurnummer (anders zou VF-1 óók VF-10 matchen)."""
    soort = "CREDIT" if is_creditnota else "VERKOOP"
    return f"VASTLY-{soort} {factuurnummer} ·"


def haal_verkoop_voorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> VerkoopVoorstelData:
    """Het opgeslagen verkoopvoorstel, of — zolang er niets opgeslagen is — een deterministische
    prefill uit het UBL-veldvoorstel: bedragen per regel, GB-code → ledger via het rekeningschema
    van deze administratie, btw-percentage → taxrate bij een ondubbelzinnige match. Btw-bedrag
    per regel wordt in code berekend (netto × pct, afgerond op centen) wanneer de UBL alleen het
    percentage draagt."""
    with scoped_session(administratie_id) as session:
        _laad_verkoopfactuur(session, document_id=document_id)
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}

        ubl_per_volgnummer: dict[int, dict] = {}
        for i, ubl_regel in enumerate(veldvoorstel.get("ubl_regels") or [], start=1):
            if isinstance(ubl_regel, dict):
                ubl_per_volgnummer[int(ubl_regel.get("volgnummer") or i)] = ubl_regel

        bestaand = session.get(VerkoopVoorstel, document_id)
        if bestaand is not None:
            regels_orm = session.scalars(
                select(VerkoopVoorstelRegel)
                .where(VerkoopVoorstelRegel.document_id == document_id)
                .order_by(VerkoopVoorstelRegel.volgnummer)
            ).all()
            regels = []
            for r in regels_orm:
                # gb_code_status wordt bij het lezen opnieuw bepaald (het rekeningschema kan
                # gesynct zijn sinds het opslaan) — maar een gekozen ledger telt als bekend.
                if r.ledger_id is not None:
                    status = "bekend"
                else:
                    _, status = _resolve_gb_code(session, administratie_id=administratie_id, code=r.gb_code)
                # De btw-resolutie draait óók over opgeslagen regels opnieuw (de UBL blijft de
                # bron): een vergrendelde regel toont ALTIJD het geresolvede tarief — ook als
                # een ouder opgeslagen voorstel (vóór de vergrendeling) iets anders droeg.
                ubl_regel = ubl_per_volgnummer.get(r.volgnummer, {})
                resolutie = _resolve_btw(
                    session,
                    administratie_id=administratie_id,
                    categorie=ubl_regel.get("btw_categorie"),
                    percentage=ubl_regel.get("btw_percentage"),
                )
                regels.append(
                    VerkoopRegelData(
                        volgnummer=r.volgnummer,
                        omschrijving=r.omschrijving,
                        netto_bedrag=r.netto_bedrag,
                        btw_bedrag=r.btw_bedrag,
                        gb_code=r.gb_code,
                        ledger_id=r.ledger_id,
                        taxrate_id=resolutie.taxrate_id if resolutie.vergrendeld else r.taxrate_id,
                        gb_code_status=status,
                        herkomst="opgeslagen",
                        btw_categorie=resolutie.categorie,
                        btw_percentage_ubl=resolutie.percentage_ubl,
                        btw_vergrendeld=resolutie.vergrendeld,
                        btw_bron=resolutie.bron,
                        btw_kandidaten=resolutie.kandidaten,
                    )
                )
            return VerkoopVoorstelData(
                document_id=document_id,
                debiteur_naam=bestaand.debiteur_naam,
                factuurnummer=bestaand.factuurnummer,
                factuurdatum=bestaand.factuurdatum,
                totaalbedrag_incl=bestaand.totaalbedrag_incl,
                is_creditnota=bestaand.is_creditnota,
                gecrediteerd_factuurnummer=bestaand.gecrediteerd_factuurnummer,
                regels=regels,
                opgeslagen=True,
                rlz_boekstuknummer=bestaand.rlz_boekstuknummer,
            )

        regels = []
        for r in veldvoorstel.get("ubl_regels") or []:
            if not isinstance(r, dict):
                continue
            ledger_id, status = _resolve_gb_code(
                session, administratie_id=administratie_id, code=r.get("gb_code")
            )
            netto = _als_decimal(r.get("netto_bedrag"))
            pct = _als_decimal(r.get("btw_percentage"))
            btw = None
            if netto is not None and pct is not None:
                # NB pct is hier het UBL-percentage (21.00) — bewust /100, niet de fractie.
                btw = (netto * pct / Decimal(100)).quantize(Decimal("0.01"))
            resolutie = _resolve_btw(
                session,
                administratie_id=administratie_id,
                categorie=r.get("btw_categorie"),
                percentage=r.get("btw_percentage"),
            )
            regels.append(
                VerkoopRegelData(
                    volgnummer=int(r.get("volgnummer") or len(regels) + 1),
                    omschrijving=r.get("omschrijving"),
                    netto_bedrag=netto,
                    btw_bedrag=btw,
                    gb_code=r.get("gb_code"),
                    ledger_id=ledger_id,
                    taxrate_id=resolutie.taxrate_id,
                    gb_code_status=status,
                    herkomst="ubl",
                    btw_categorie=resolutie.categorie,
                    btw_percentage_ubl=resolutie.percentage_ubl,
                    btw_vergrendeld=resolutie.vergrendeld,
                    btw_bron=resolutie.bron,
                    btw_kandidaten=resolutie.kandidaten,
                )
            )
        gecrediteerd = veldvoorstel.get("gecrediteerde_factuurnummers") or []
        return VerkoopVoorstelData(
            document_id=document_id,
            debiteur_naam=veldvoorstel.get("klant_naam"),
            factuurnummer=veldvoorstel.get("factuurnummer"),
            factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
            totaalbedrag_incl=_als_decimal(veldvoorstel.get("totaal_incl")),
            is_creditnota=bool(veldvoorstel.get("is_creditnota")),
            gecrediteerd_factuurnummer=gecrediteerd[0] if gecrediteerd else None,
            regels=regels,
            opgeslagen=False,
        )


def _onthoud_btw_keuze(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    resolutie: BtwResolutie,
    taxrate_id: uuid.UUID,
) -> None:
    """Bij echte ambiguïteit wordt de eerste menselijke keuze per administratie onthouden
    (boekingsgeheugen-patroon) — de volgende factuur met dezelfde categorie + hetzelfde
    percentage vult automatisch én vergrendeld (bron 'onthouden'). Elke zetting geauditeerd."""
    fractie = btw_eenheid.factuur_fractie(resolutie.categorie, resolutie.percentage_ubl)
    if resolutie.categorie is None or fractie is None:  # pragma: no cover — kandidaten impliceert beide
        return
    voorkeur = session.get(VerkoopBtwVoorkeur, (administratie_id, resolutie.categorie, fractie))
    oude_waarde = None
    if voorkeur is None:
        session.add(
            VerkoopBtwVoorkeur(
                administratie_id=administratie_id,
                btw_categorie=resolutie.categorie,
                percentage_fractie=fractie,
                taxrate_id=taxrate_id,
            )
        )
    elif voorkeur.taxrate_id != taxrate_id:
        oude_waarde = {"taxrate_id": str(voorkeur.taxrate_id)}
        voorkeur.taxrate_id = taxrate_id
    else:
        return  # ongewijzigd — geen nieuwe audit-rij (waarde aanwezig ≠ gewijzigd)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="verkoop_btw_voorkeur",
        record_id=administratie_id,
        actie="verkoop_btw_voorkeur_onthouden",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oude_waarde,
        nieuwe_waarde={
            "btw_categorie": resolutie.categorie,
            "percentage_fractie": str(fractie),
            "taxrate_id": str(taxrate_id),
        },
        administratie_id=administratie_id,
    )


@dataclass(frozen=True)
class VerkoopRegelInput:
    omschrijving: str | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    gb_code: str | None
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None


def sla_verkoop_voorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    debiteur_naam: str | None,
    factuurnummer: str | None,
    factuurdatum: date | None,
    totaalbedrag_incl: Decimal | None,
    regels: list[VerkoopRegelInput],
) -> VerkoopVoorstelData:
    """Slaat het reviewscherm-voorstel op. `is_creditnota`/`gecrediteerd_factuurnummer` komen
    deterministisch uit de UBL en zijn bewust NIET door de controleur te muteren — het
    documenttype (380/381) is een brongegeven, geen keuze."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_verkoopfactuur(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN:
            raise VerkoopVoorstelFout(
                f"Document {document_id} kan niet meer gewijzigd worden (status: {document.status.value})"
            )
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
        gecrediteerd = veldvoorstel.get("gecrediteerde_factuurnummers") or []

        bestaand = session.get(VerkoopVoorstel, document_id)
        if bestaand is None:
            bestaand = VerkoopVoorstel(document_id=document_id)
            session.add(bestaand)
        bestaand.debiteur_naam = debiteur_naam
        bestaand.factuurnummer = factuurnummer
        bestaand.factuurdatum = factuurdatum
        bestaand.totaalbedrag_incl = totaalbedrag_incl
        bestaand.is_creditnota = bool(veldvoorstel.get("is_creditnota"))
        bestaand.gecrediteerd_factuurnummer = gecrediteerd[0] if gecrediteerd else None

        ubl_per_volgnummer: dict[int, dict] = {}
        for i, ubl_regel in enumerate(veldvoorstel.get("ubl_regels") or [], start=1):
            if isinstance(ubl_regel, dict):
                ubl_per_volgnummer[int(ubl_regel.get("volgnummer") or i)] = ubl_regel

        session.execute(delete(VerkoopVoorstelRegel).where(VerkoopVoorstelRegel.document_id == document_id))
        for i, regel in enumerate(regels, start=1):
            # Btw is nooit een vrije menselijke waardekeuze (blok A 2026-08-10, factuur is
            # wettelijk leidend): de server herleidt per regel opnieuw en is de poort —
            # een client die een vergrendelde regel toch anders instuurt is een bug/bypass.
            ubl_regel = ubl_per_volgnummer.get(i, {})
            resolutie = _resolve_btw(
                session,
                administratie_id=administratie_id,
                categorie=ubl_regel.get("btw_categorie"),
                percentage=ubl_regel.get("btw_percentage"),
            )
            taxrate_id = regel.taxrate_id
            if resolutie.vergrendeld:
                if taxrate_id is not None and taxrate_id != resolutie.taxrate_id:
                    raise VerkoopVoorstelFout(
                        f"Regel {i}: de btw-code volgt uit de factuur (categorie "
                        f"{resolutie.categorie}, {resolutie.percentage_ubl}%) en is vergrendeld "
                        "— een andere btw-code kiezen kan niet"
                    )
                taxrate_id = resolutie.taxrate_id
            elif resolutie.kandidaten:
                if taxrate_id is not None and taxrate_id not in resolutie.kandidaten:
                    raise VerkoopVoorstelFout(
                        f"Regel {i}: de gekozen btw-code dekt de factuur-btw (categorie "
                        f"{resolutie.categorie}, {resolutie.percentage_ubl}%) niet — kies één "
                        "van de passende tarieven"
                    )
                if taxrate_id is not None:
                    _onthoud_btw_keuze(
                        session,
                        administratie_id=administratie_id,
                        actor_id=actor_id,
                        resolutie=resolutie,
                        taxrate_id=taxrate_id,
                    )
            session.add(
                VerkoopVoorstelRegel(
                    document_id=document_id,
                    volgnummer=i,
                    omschrijving=regel.omschrijving,
                    netto_bedrag=regel.netto_bedrag,
                    btw_bedrag=regel.btw_bedrag,
                    gb_code=regel.gb_code,
                    ledger_id=regel.ledger_id,
                    taxrate_id=taxrate_id,
                )
            )

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verkoop_voorstel",
            record_id=document_id,
            actie="verkoop_voorstel_opgeslagen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "factuurnummer": factuurnummer,
                "debiteur_naam": debiteur_naam,
                "aantal_regels": len(regels),
            },
            administratie_id=administratie_id,
        )

    return haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)


def _lokale_duplicaat_hits(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, factuurnummer: str, is_creditnota: bool
) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(VerkoopBoeking)
            .where(
                VerkoopBoeking.administratie_id == administratie_id,
                VerkoopBoeking.document_id != document_id,
                VerkoopBoeking.factuurnummer == factuurnummer,
                VerkoopBoeking.is_creditnota == is_creditnota,
                VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
            )
        )
        or 0
    )


def _origineel_geboekt(session: Session, *, administratie_id: uuid.UUID, factuurnummer: str | None) -> bool:
    if not (factuurnummer or "").strip():
        return False
    return (
        session.scalar(
            select(func.count())
            .select_from(VerkoopBoeking)
            .where(
                VerkoopBoeking.administratie_id == administratie_id,
                VerkoopBoeking.factuurnummer == factuurnummer,
                VerkoopBoeking.is_creditnota.is_(False),
                VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
            )
        )
        or 0
    ) > 0


def _naar_check_regels(
    regels: list[VerkoopRegelData], taxrates: dict[uuid.UUID, TaxRateCache]
) -> list[verkoop_checks.VerkoopCheckRegel]:
    check_regels = []
    for r in regels:
        rij = taxrates.get(r.taxrate_id) if r.taxrate_id is not None else None
        is_verlegd, is_vrijgesteld = btw_eenheid.taxrate_vlaggen(rij.brondata if rij is not None else None)
        check_regels.append(
            verkoop_checks.VerkoopCheckRegel(
                volgnummer=r.volgnummer,
                omschrijving=r.omschrijving,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                gb_code=r.gb_code,
                ledger_id_bekend=r.ledger_id is not None,
                taxrate_id_bekend=r.taxrate_id is not None,
                gb_code_status=r.gb_code_status,
                btw_categorie=r.btw_categorie,
                btw_percentage_ubl=r.btw_percentage_ubl,
                taxrate_percentage=rij.percentage if rij is not None else None,
                taxrate_is_verlegd=is_verlegd,
                taxrate_is_vrijgesteld=is_vrijgesteld,
                taxrate_in_cache=rij is not None,
            )
        )
    return check_regels


def _actieve_taxrates(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, TaxRateCache]:
    return {
        rij.id: rij
        for rij in session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == administratie_id,
                TaxRateCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    }


def voer_verkoop_checks_uit(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> CheckRapport:
    """Herleest het actuele voorstel en toetst alle harde verkoop-checks. `client=None` opent een
    eigen RLZ-verbinding; lukt dat niet, dan wordt uitsluitend de RLZ-side duplicaatcheck een
    blokkerend "kon niet uitgevoerd worden"-resultaat (fail-closed) — de lokale checks draaien
    gewoon door, nooit een kale 500 (zelfde patroon als de inkoop- en omzetchecks)."""
    voorstel = haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(administratie_id) as session:
        document = _laad_verkoopfactuur(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN:
            raise VerkoopVoorstelFout(
                f"Document {document_id} kan niet meer gecontroleerd worden (status: {document.status.value})"
            )
        taxrates = _actieve_taxrates(session, administratie_id=administratie_id)
        lokale_hits = 0
        origineel = False
        if voorstel.factuurnummer:
            lokale_hits = _lokale_duplicaat_hits(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                factuurnummer=voorstel.factuurnummer,
                is_creditnota=voorstel.is_creditnota,
            )
        if voorstel.is_creditnota:
            origineel = _origineel_geboekt(
                session,
                administratie_id=administratie_id,
                factuurnummer=voorstel.gecrediteerd_factuurnummer,
            )

    rlz_hits: int | None = None
    if voorstel.factuurnummer:
        omschrijving = verkoop_omschrijving_vastly(voorstel.factuurnummer, is_creditnota=voorstel.is_creditnota)
        eigen_client = client is None
        try:
            if client is None:
                rlz_admin_id = rlz_admin_id_voor(administratie_id)
                client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
            from app.documenten.rlz_ids import rlz_sales_invoice_id

            gevonden = client.find_receipts_by_description_prefix(prefix=omschrijving)
            eigen_id = str(rlz_sales_invoice_id(document_id))
            rlz_hits = len([r for r in gevonden if r.get("id") != eigen_id])
        except Exception as exc:  # noqa: BLE001 — fail-closed: check wordt blokkerend, crasht nooit
            logger.warning("RLZ-duplicaatcheck verkoop kon niet uitgevoerd worden: %s", exc)
            rlz_hits = None
        finally:
            if eigen_client and client is not None:
                client.close()
    else:
        # Zonder factuurnummer is er geen deterministische omschrijving om op te toetsen; de
        # verplichte-velden-check blokkeert dan al — de RLZ-check telt als 0, niet als fout.
        rlz_hits = 0

    return verkoop_checks.voer_verkoop_checks_uit(
        debiteur_naam=voorstel.debiteur_naam,
        factuurnummer=voorstel.factuurnummer,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag_incl=voorstel.totaalbedrag_incl,
        regels=_naar_check_regels(voorstel.regels, taxrates),
        lokale_duplicaat_hits=lokale_hits,
        rlz_duplicaat_hits=rlz_hits,
        is_creditnota=voorstel.is_creditnota,
        gecrediteerd_factuurnummer=voorstel.gecrediteerd_factuurnummer,
        origineel_geboekt=origineel,
    )
