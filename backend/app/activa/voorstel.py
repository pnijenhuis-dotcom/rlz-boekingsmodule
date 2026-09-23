"""Detectie bij boeken (ontwerp §2, auto-first): welke boekvoorstelregels van een inkoopfactuur een activum worden.

Puur op de eigen database — geen RLZ-call, geen AI: regel op een `is_activa`-rekening (uit de bron gesynct) mét netto ≥
de effectieve activeringsgrens = KANDIDAAT (kaart "Activum aanmaken?" mét voorgevulde velden); een regel op een
activarekening ónder de grens = oranje signaal ("kleine aanschaf direct ten laste van het resultaat?"). De bestaande
koppeling van dezelfde `boek_cyclus` reist mee als stand per kandidaat. De regels zijn de OPGESLAGEN boekvoorstelregels
(`boekvoorstel_regel`; het openen van het controlescherm persisteert de prefill, A10 07-09) — zonder boekvoorstel is de
kaart leeg."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activa import afschrijving as afschrijving_service
from app.activa import categorie as cat
from app.activa import instelling as instelling_service
from app.activa.instelling import InstellingStand
from app.activa.models import ActivumKoppeling
from app.db.models import Grootboekrekening
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.documenten.service import DocumentNietGevonden
from app.sync.models import VendorCache
from app.tijd import vandaag_nl

RESTWAARDE = Decimal("0.00")


@dataclass(frozen=True)
class Kandidaat:
    regel_volgnummer: int
    ledger_id: uuid.UUID
    ledger_code: str
    ledger_naam: str
    omschrijving: str
    aanschafwaarde: Decimal
    aanschafdatum: date
    categorie: str
    termijn_maanden: int
    restwaarde: Decimal
    afschrijving_ledger_id: uuid.UUID | None
    afschrijving_ledger_code: str | None
    #: Herkomst van de voorgevulde afschrijvingsrekening: `koppeling` (vastgelegd bij plannen), `instelling` (per
    #: categorie), `conventie` (code + 1 mét naam "Afschrijving…", BUG 24-09) of None (leeg → verplicht op de kaart).
    afschrijving_bron: str | None
    signalen: list[cat.Signaal]
    koppeling: ActivumKoppeling | None

    @property
    def categorie_label(self) -> str:
        return cat.label_voor(self.categorie)

    @property
    def methode_naam(self) -> str:
        return cat.methode_naam(self.termijn_maanden)


@dataclass(frozen=True)
class OnderGrens:
    regel_volgnummer: int
    ledger_code: str
    ledger_naam: str
    netto: Decimal
    tekst: str


@dataclass(frozen=True)
class VoorstelData:
    administratie_id: uuid.UUID
    document_id: uuid.UUID
    document_geboekt: bool
    boek_cyclus: int
    referentie: str | None
    stand: InstellingStand
    kandidaten: list[Kandidaat] = field(default_factory=list)
    onder_grens: list[OnderGrens] = field(default_factory=list)
    afschrijving_ledger_opties: list[Grootboekrekening] = field(default_factory=list)

    @property
    def leeg(self) -> bool:
        return not self.kandidaten and not self.onder_grens

    def kandidaat(self, regel_volgnummer: int) -> Kandidaat | None:
        return next((k for k in self.kandidaten if k.regel_volgnummer == regel_volgnummer), None)


def koppelingen_voor(session: Session, *, document_id: uuid.UUID, boek_cyclus: int) -> dict[int, ActivumKoppeling]:
    return {
        k.regel_volgnummer: k
        for k in session.scalars(
            select(ActivumKoppeling).where(
                ActivumKoppeling.document_id == document_id, ActivumKoppeling.boek_cyclus == boek_cyclus
            )
        )
    }


def _omschrijving(regel: BoekvoorstelRegel, *, leverancier: str | None, referentie: str | None) -> str:
    tekst = (regel.omschrijving or "").strip()
    if tekst:
        return tekst[:200]
    delen = [d for d in (leverancier, referentie) if d]
    return (" ".join(delen) or "Activum")[:200]


def bepaal_afschrijving(
    *,
    koppeling: ActivumKoppeling | None,
    stand: InstellingStand,
    categorie: str,
    balans: Grootboekrekening,
    rekeningen: dict[uuid.UUID, Grootboekrekening],
) -> tuple[uuid.UUID | None, str | None]:
    """Winnaarsvolgorde afschrijvingsrekening: vastgelegd op de koppeling > instelling per categorie > conventie
    code + 1 mét naam "Afschrijving…" (BUG 24-09) > leeg. Geeft (ledger_id, bron)."""
    if koppeling is not None and koppeling.afschrijving_ledger_id:
        return koppeling.afschrijving_ledger_id, afschrijving_service.BRON_KOPPELING
    uit_instelling = stand.afschrijving_ledger_voor(categorie)
    if uit_instelling is not None:
        return uit_instelling, afschrijving_service.BRON_INSTELLING
    treffer = afschrijving_service.conventie_rekening(balans, rekeningen.values())
    if treffer is not None:
        return treffer.ledger_id, afschrijving_service.BRON_CONVENTIE
    return None, None


def bepaal(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> VoorstelData:
    document = session.get(Document, document_id)
    if document is None or document.administratie_id != administratie_id:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    stand = instelling_service.lees_stand(session, administratie_id)
    voorstel = session.get(Boekvoorstel, document_id)
    geboekt = document.status == DocumentStatus.GEBOEKT
    boek_cyclus = voorstel.boek_cyclus if voorstel is not None else 0
    opties = instelling_service.afschrijving_ledger_opties(session, administratie_id)
    data = VoorstelData(
        administratie_id=administratie_id,
        document_id=document_id,
        document_geboekt=geboekt,
        boek_cyclus=boek_cyclus,
        referentie=voorstel.referentie if voorstel is not None else None,
        stand=stand,
        afschrijving_ledger_opties=opties,
    )
    if voorstel is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
        return data
    rekeningen = {
        r.ledger_id: r
        for r in session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
        )
    }
    regels = session.scalars(
        select(BoekvoorstelRegel)
        .where(BoekvoorstelRegel.document_id == document_id)
        .order_by(BoekvoorstelRegel.volgnummer)
    ).all()
    koppelingen = koppelingen_voor(session, document_id=document_id, boek_cyclus=boek_cyclus)
    leverancier: str | None = None
    if voorstel.vendor_id is not None:
        vc = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
        leverancier = vc.naam if vc is not None else None
    aanschafdatum = voorstel.factuurdatum or vandaag_nl()
    grens = stand.effectieve_grens
    for regel in regels:
        rek = rekeningen.get(regel.ledger_id) if regel.ledger_id is not None else None
        if rek is None or not rek.is_activa or regel.netto_bedrag is None or regel.netto_bedrag <= 0:
            continue
        netto = Decimal(regel.netto_bedrag).quantize(Decimal("0.01"))
        if netto < grens:
            data.onder_grens.append(
                OnderGrens(
                    regel_volgnummer=regel.volgnummer,
                    ledger_code=rek.code,
                    ledger_naam=rek.naam,
                    netto=netto,
                    tekst=(
                        f"{rek.code} {rek.naam} € {netto} staat op een activarekening onder de grens € {grens} — "
                        "kleine aanschaf direct ten laste van het resultaat?"
                    ),
                )
            )
            continue
        koppeling = koppelingen.get(regel.volgnummer)
        categorie = koppeling.categorie if koppeling is not None else cat.bepaal_categorie(rek.code, rek.naam)
        termijn = koppeling.termijn_maanden if koppeling is not None else stand.termijn_voor(categorie)
        afschrijving_id, afschrijving_bron = bepaal_afschrijving(
            koppeling=koppeling, stand=stand, categorie=categorie, balans=rek, rekeningen=rekeningen
        )
        afschrijving_rek = rekeningen.get(afschrijving_id) if afschrijving_id is not None else None
        if afschrijving_rek is None:
            afschrijving_bron = None
        data.kandidaten.append(
            Kandidaat(
                regel_volgnummer=regel.volgnummer,
                ledger_id=rek.ledger_id,
                ledger_code=rek.code,
                ledger_naam=rek.naam,
                omschrijving=(
                    koppeling.omschrijving
                    if koppeling is not None
                    else _omschrijving(regel, leverancier=leverancier, referentie=voorstel.referentie)
                ),
                aanschafwaarde=koppeling.aanschafwaarde if koppeling is not None else netto,
                aanschafdatum=koppeling.aanschafdatum if koppeling is not None else aanschafdatum,
                categorie=categorie,
                termijn_maanden=termijn,
                restwaarde=koppeling.restwaarde if koppeling is not None else RESTWAARDE,
                afschrijving_ledger_id=afschrijving_id if afschrijving_rek is not None else None,
                afschrijving_ledger_code=afschrijving_rek.code if afschrijving_rek is not None else None,
                afschrijving_bron=afschrijving_bron,
                signalen=cat.fiscale_signalen(
                    categorie=categorie, termijn_maanden=termijn, aanschafwaarde=netto, grens=grens
                ),
                koppeling=koppeling,
            )
        )
    return data
