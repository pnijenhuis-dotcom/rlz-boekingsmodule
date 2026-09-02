"""'Geboekt in RLZ' zichtbaar (blok C 02-09, aanleiding Elissen-casus: een geboekte verkoopfactuur is in
RLZ níét te vinden onder Verkopen → Facturen — die lijst toont alleen in RLZ zelf gemaakte facturen — en
dat verwart élke gebruiker opnieuw).

Eén bron voor lijst-tooltip, detailkop en de reviewschermen: per GEBOEKT document het boekstuknummer,
de tegenpartij (crediteur/debiteur) en een vindplaats-hint per documentsoort. Alles komt uit wat de app
al heeft — de GEBOEKT-overgang in de tijdlijn (élke motor legt daar `rlz_document_id` +
boekstuknummer vast), het boekvoorstel + de vendor-cache (inkoop), het verkoopvoorstel (debiteur), de
omzetboeking (verkoop + memoriaal) — NOOIT een RLZ-call. Gebatcht per lijst (geen N+1)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

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

    def als_regel(self) -> str:
        """Eén leesbare regel: 'Geboekt in RLZ · boekstuk RLZ-01-00000442 · Universal Nederland B.V.'."""
        delen = ["Geboekt in RLZ"]
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
        resultaat[d.id] = GeboektInRlz(
            boekstuknummer=boekstuk,
            rlz_document_id=_tekst(detail, "rlz_document_id"),
            tegenpartij=crediteur,
            tegenpartij_rol="crediteur" if crediteur else None,
            geboekt_op=geboekt_op,
            vindplaats_hint=None,
        )
    return resultaat
