"""'Geboekt in RLZ' zichtbaar (blok C 02-09, aanleiding Elissen-casus: een geboekte verkoopfactuur is in
RLZ níét te vinden onder Verkopen → Facturen — die lijst toont alleen in RLZ zelf gemaakte facturen — en
dat verwart élke gebruiker opnieuw).

Eén bron voor lijst-tooltip, detailkop en de reviewschermen: per GEBOEKT document het boekstuknummer,
de tegenpartij (crediteur/debiteur) en een vindplaats-hint per documentsoort. Alles komt uit wat de app
al heeft — de GEBOEKT-overgang in de tijdlijn (élke motor legt daar `rlz_document_id` +
boekstuknummer vast), het boekvoorstel + de vendor-cache (inkoop), het verkoopvoorstel (debiteur), de
omzetboeking (verkoop + memoriaal) — NOOIT een RLZ-call. Gebatcht per lijst (geen N+1).

Odoo-adapter blok E (03-09, mockup `odoo-koppeling-ui.html` sectie 3): voor een document waarvan de jongste
GEBOEKT-overgang `backend: odoo` draagt, komt het nummer uit `odoo_document_koppeling` (boeking + eventuele
tegenboeking van de jongste boek_cyclus — kruisverwijzing "Reversal · RBILL/… ↔ BILL/…"), de company uit de
koppelstand (company-poort zichtbaar, ontwerpnotitie ④) en de btw-cent-override-chip uit het detail."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.sync.models import VendorCache

#: Vindplaats in de RLZ-UI per documentsoort. Inkoopfacturen staan gewoon onder Inkoop → Facturen (geen
#: hint nodig); alles wat als SalesInvoice/Receipt boekt (verkoop, omzet, doorbelasting-verkopen) NIET
#: onder Verkopen → Facturen — bewezen RLZ-collectie-gedrag (api-verkenning "DocumentCategory &
#: boekstuk-reeksen"; BESLISSINGEN "Doorbelasting-kliktest-nazorg").
VINDPLAATS_VERKOOP = (
    "In RLZ zichtbaar op de debiteurenkaart en in het verkoopboek (Verkoop → Boekingen/Journaal) — "
    "níét in Verkopen → Facturen: die lijst toont alleen facturen die in RLZ zelf zijn gemaakt."
)
VINDPLAATS_OMZET = (
    "In RLZ zichtbaar in het verkoopboek (entity-loze verkoopboeking/Receipt) en, bij een kostprijsregel, in het "
    "memoriaal — níét in Verkopen → Facturen en niet op een debiteurenkaart (kasomzet heeft geen debiteur)."
)
VINDPLAATS_WAARBORG = (
    "In RLZ zichtbaar als memoriaalboeking (dagboek Memoriaal) — geen factuur, dus niet onder Inkoop of Verkopen."
)
#: Odoo-administraties (0016/0101, mockup blok E sectie 3): inkoopfacturen staan onder Boekhouding → Leveranciers →
#: Facturen van de company; een correctie is een aparte creditnota (RBILL/…) mét kruisverwijzing — nooit een
#: gewijzigd origineel. `vindplaats_odoo_inkoop(company_naam)` vult de company in als die bekend is.
VINDPLAATS_ODOO_INKOOP = (
    "In Odoo: Boekhouding → Leveranciers → Facturen van de gekoppelde company (nummer BILL/…); een correctie staat "
    "als aparte creditnota (RBILL/…) met kruisverwijzing naar het origineel."
)
LABEL_PER_BACKEND = {"rlz": "RLZ", "odoo": "Odoo"}


def vindplaats_odoo_inkoop(company_naam: str | None) -> str:
    if not company_naam:
        return VINDPLAATS_ODOO_INKOOP
    return (
        f"In Odoo: Boekhouding → Leveranciers → Facturen van company {company_naam} (nummer BILL/…); een correctie "
        "staat als aparte creditnota (RBILL/…) met kruisverwijzing naar het origineel."
    )


@dataclass(frozen=True)
class GeboektInRlz:
    boekstuknummer: str | None
    rlz_document_id: str | None
    #: crediteur (inkoop), debiteur (verkoop) of None (kasomzet/waarborg: geen tegenpartij)
    tegenpartij: str | None
    tegenpartij_rol: str | None
    geboekt_op: datetime
    #: tweede boekstuk bij een omzetboeking (kostprijsmemoriaal)
    memoriaal_boekstuknummer: str | None = None
    vindplaats_hint: str | None = None
    #: boekhoud-backend van de boeking (uit het GEBOEKT-tijdlijndetail; ontbreekt = rlz, pre-0101)
    backend: str = "rlz"
    #: Odoo (blok E): de company van de koppeling (company-poort zichtbaar), het nummer van de creditnota bij een
    #: tegenboeking, de kruisverwijzing "Reversal · RBILL/… ↔ BILL/…" en of de btw-cent-override is toegepast.
    company_naam: str | None = None
    tegenboeking_boekstuknummer: str | None = None
    kruisverwijzing: str | None = None
    btw_override: bool = False
    #: Slotstuk 04-09 (A2): leesbare regel als de adapter de boekdatum ná een Odoo-lock date heeft verschoven —
    #: "boekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode". Uit het
    #: GEBOEKT-detail `boekdatum_verschoven`; RLZ-boekingen dragen 'm nooit (byte-identiek).
    boekdatum_verschoven: str | None = None

    def als_regel(self) -> str:
        """Eén leesbare regel: 'Geboekt in RLZ · boekstuk RLZ-01-00000442 · Universal Nederland B.V.' — of, voor
        een Odoo-administratie (mockup sectie 3): 'Geboekt in Odoo · BILL/2026/09/0001 · Universal Steigerbouw'
        (nummer zónder 'boekstuk'-prefix, company i.p.v. tegenpartij)."""
        delen = [f"Geboekt in {LABEL_PER_BACKEND.get(self.backend, self.backend)}"]
        if self.backend == "odoo":
            delen.append(self.boekstuknummer or "nummer onbekend")
            if self.company_naam:
                delen.append(self.company_naam)
            return " · ".join(delen)
        delen.append(f"boekstuk {self.boekstuknummer}" if self.boekstuknummer else "boekstuk onbekend")
        if self.memoriaal_boekstuknummer:
            delen.append(f"memoriaal {self.memoriaal_boekstuknummer}")
        if self.tegenpartij:
            delen.append(self.tegenpartij)
        return " · ".join(delen)


def _jongste_geboekt_overgangen(
    session: Session, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DocumentGebeurtenis]:
    if not document_ids:
        return {}
    rang = (
        func.row_number()
        .over(partition_by=DocumentGebeurtenis.document_id, order_by=DocumentGebeurtenis.tijdstip.desc())
        .label("rang")
    )
    sub = (
        select(DocumentGebeurtenis.id, rang)
        .where(
            DocumentGebeurtenis.document_id.in_(document_ids),
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            # Een tegenboeking is een geboekt→geboekt-gebeurtenis (detail `tegenboeking`), geen boeking — zonder
            # dit filter verloor een tegengeboekt Odoo-document zijn backend/nummer (live keten-cyclus 04-09).
            DocumentGebeurtenis.van_status.is_distinct_from(DocumentStatus.GEBOEKT),
        )
        .subquery()
    )
    ids = [r[0] for r in session.execute(select(sub.c.id).where(sub.c.rang == 1)).all()]
    if not ids:
        return {}
    return {
        g.document_id: g for g in session.scalars(select(DocumentGebeurtenis).where(DocumentGebeurtenis.id.in_(ids)))
    }


def _tekst(detail: dict | None, *sleutels: str) -> str | None:
    if not isinstance(detail, dict):
        return None
    for sleutel in sleutels:
        waarde = detail.get(sleutel)
        if isinstance(waarde, str) and waarde.strip():
            return waarde
    return None


def _datum_nl(iso: object) -> str | None:
    if not isinstance(iso, str) or len(iso) < 10:
        return None
    try:
        return date.fromisoformat(iso[:10]).strftime("%d-%m-%Y")
    except ValueError:
        return None


def boekdatum_verschoven_regel(detail: dict | None) -> str | None:
    """A2 (slotstuk 04-09): uit het GEBOEKT-detail `boekdatum_verschoven {van, naar, …}` één leesbare regel voor
    tooltip/detailkop — None als de boeking geen verschuiving draagt (alle RLZ-boekingen, Odoo zonder lock)."""
    if not isinstance(detail, dict):
        return None
    blok = detail.get("boekdatum_verschoven")
    if not isinstance(blok, dict):
        return None
    naar, van = _datum_nl(blok.get("naar")), _datum_nl(blok.get("van"))
    if naar is None or van is None:
        return None
    return f"boekdatum {naar} · factuurdatum {van} valt in een in Odoo afgesloten periode"


@dataclass(frozen=True)
class _OdooNummers:
    boeking: str | None
    tegenboeking: str | None


def _odoo_nummers(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, _OdooNummers]:
    """Per Odoo-geboekt document het `account.move`-nummer van de boeking én de eventuele tegenboeking
    (reversal) van de JONGSTE boek_cyclus — gebatcht uit `odoo_document_koppeling` (lokale mapping, geen
    Odoo-call). Geannuleerde concepten (state cancel) tellen niet."""
    if not document_ids:
        return {}
    from app.odoo.models import OdooDocumentKoppeling

    rijen = session.scalars(
        select(OdooDocumentKoppeling).where(
            OdooDocumentKoppeling.document_id.in_(document_ids), OdooDocumentKoppeling.state != "cancel"
        )
    ).all()
    per_document: dict[uuid.UUID, dict[int, dict[str, str | None]]] = {}
    for rij in rijen:
        per_document.setdefault(rij.document_id, {}).setdefault(rij.boek_cyclus, {})[rij.soort] = rij.odoo_naam
    resultaat: dict[uuid.UUID, _OdooNummers] = {}
    for document_id, cycli in per_document.items():
        met_boeking = [c for c, soorten in cycli.items() if "boeking" in soorten]
        cyclus = max(met_boeking) if met_boeking else max(cycli)
        soorten = cycli[cyclus]
        resultaat[document_id] = _OdooNummers(boeking=soorten.get("boeking"), tegenboeking=soorten.get("tegenboeking"))
    return resultaat


def _odoo_company_namen(administratie_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not administratie_ids:
        return {}
    from app.odoo.service import koppelstand

    return {aid: stand.company_naam for aid, stand in koppelstand(list(administratie_ids), met_details=False).items()}


def bepaal_geboekt_in_rlz(session: Session, documenten: list[Document]) -> dict[uuid.UUID, GeboektInRlz]:
    """Per GEBOEKT document (status geboekt, óók tegengeboekt blijft 'geboekt') de RLZ-stand. Andere
    statussen komen niet in het resultaat. Gebatcht: één query per bron."""
    geboekt = [d for d in documenten if d.status == DocumentStatus.GEBOEKT]
    if not geboekt:
        return {}
    ids = [d.id for d in geboekt]
    overgangen = _jongste_geboekt_overgangen(session, ids)

    # Inkoop: crediteur via boekvoorstel.vendor_id → vendor-cache (lokale cache, geen RLZ-call).
    inkoop_ids = [d.id for d in geboekt if d.soort == DocumentSoort.INKOOPFACTUUR.value]
    voorstellen: dict[uuid.UUID, Boekvoorstel] = {}
    vendor_namen: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
    if inkoop_ids:
        voorstellen = {
            v.document_id: v
            for v in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(inkoop_ids)))
        }
        vendor_ids = {v.vendor_id for v in voorstellen.values() if v.vendor_id is not None}
        if vendor_ids:
            for rij in session.scalars(select(VendorCache).where(VendorCache.id.in_(vendor_ids))):
                if rij.naam:
                    vendor_namen[(rij.administratie_id, rij.id)] = rij.naam

    # Verkoop (Vastly): debiteur = de échte huurder op het verkoopvoorstel.
    verkoop_ids = [d.id for d in geboekt if d.soort == DocumentSoort.VERKOOPFACTUUR.value]
    debiteuren: dict[uuid.UUID, str] = {}
    if verkoop_ids:
        from app.verkoop.models import VerkoopVoorstel

        for v in session.scalars(select(VerkoopVoorstel).where(VerkoopVoorstel.document_id.in_(verkoop_ids))):
            if v.debiteur_naam:
                debiteuren[v.document_id] = v.debiteur_naam

    # Odoo (blok E): nummers uit de document-koppeling + company uit de koppelstand — gebatcht.
    odoo_ids = [d.id for d in geboekt if d.id in overgangen and _tekst(overgangen[d.id].detail, "backend") == "odoo"]
    odoo_nummers = _odoo_nummers(session, odoo_ids)
    odoo_company = _odoo_company_namen(
        {d.administratie_id for d in geboekt if d.id in odoo_ids and d.administratie_id is not None}
    )

    resultaat: dict[uuid.UUID, GeboektInRlz] = {}
    for d in geboekt:
        overgang = overgangen.get(d.id)
        detail = overgang.detail if overgang is not None else None
        geboekt_op = overgang.tijdstip if overgang is not None else d.laatst_gewijzigd_op
        if d.soort == DocumentSoort.KASSARAPPORT.value:
            resultaat[d.id] = GeboektInRlz(
                boekstuknummer=_tekst(detail, "verkoop_boekstuknummer"),
                rlz_document_id=_tekst(detail, "verkoop_rlz_id"),
                tegenpartij=None,
                tegenpartij_rol=None,
                geboekt_op=geboekt_op,
                memoriaal_boekstuknummer=_tekst(detail, "memoriaal_boekstuknummer"),
                vindplaats_hint=VINDPLAATS_OMZET,
            )
            continue
        boekstuk = _tekst(detail, "rlz_boekstuknummer")
        if d.soort == DocumentSoort.VERKOOPFACTUUR.value:
            resultaat[d.id] = GeboektInRlz(
                boekstuknummer=boekstuk,
                rlz_document_id=_tekst(detail, "rlz_document_id"),
                tegenpartij=debiteuren.get(d.id),
                tegenpartij_rol="debiteur" if d.id in debiteuren else None,
                geboekt_op=geboekt_op,
                vindplaats_hint=VINDPLAATS_VERKOOP,
            )
            continue
        if d.soort == DocumentSoort.WAARBORG.value:
            resultaat[d.id] = GeboektInRlz(
                boekstuknummer=boekstuk,
                rlz_document_id=_tekst(detail, "rlz_document_id"),
                tegenpartij=None,
                tegenpartij_rol=None,
                geboekt_op=geboekt_op,
                vindplaats_hint=VINDPLAATS_WAARBORG,
            )
            continue
        voorstel = voorstellen.get(d.id)
        if boekstuk is None and voorstel is not None:
            boekstuk = voorstel.rlz_boekstuknummer
        crediteur = (
            vendor_namen.get((d.administratie_id, voorstel.vendor_id))
            if voorstel is not None and voorstel.vendor_id is not None and d.administratie_id is not None
            else None
        )
        backend = _tekst(detail, "backend") or "rlz"
        if backend == "odoo":
            nummers = odoo_nummers.get(d.id)
            boeking_nr = (nummers.boeking if nummers else None) or _tekst(detail, "odoo_naam", "rlz_boekstuknummer")
            if boeking_nr is None:
                boeking_nr = boekstuk
            tegen_nr = nummers.tegenboeking if nummers else None
            company_naam = odoo_company.get(d.administratie_id) if d.administratie_id is not None else None
            resultaat[d.id] = GeboektInRlz(
                boekstuknummer=boeking_nr,
                rlz_document_id=_tekst(detail, "rlz_document_id"),
                tegenpartij=crediteur,
                tegenpartij_rol="crediteur" if crediteur else None,
                geboekt_op=geboekt_op,
                vindplaats_hint=vindplaats_odoo_inkoop(company_naam),
                backend="odoo",
                company_naam=company_naam,
                tegenboeking_boekstuknummer=tegen_nr,
                kruisverwijzing=f"Reversal · {tegen_nr} ↔ {boeking_nr}" if tegen_nr else None,
                btw_override=bool(detail.get("btw_override")) if isinstance(detail, dict) else False,
                boekdatum_verschoven=boekdatum_verschoven_regel(detail),
            )
            continue
        resultaat[d.id] = GeboektInRlz(
            boekstuknummer=boekstuk,
            rlz_document_id=_tekst(detail, "rlz_document_id"),
            tegenpartij=crediteur,
            tegenpartij_rol="crediteur" if crediteur else None,
            geboekt_op=geboekt_op,
            vindplaats_hint=None,
            backend=backend,
        )
    return resultaat
