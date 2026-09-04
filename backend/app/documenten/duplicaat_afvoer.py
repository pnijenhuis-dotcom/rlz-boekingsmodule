"""Duplicaat-afvoer — duplicaten automatisch uit de werklijst (medewerker-wens, besluit Peter 04-09;
kernprincipe 7 "minimale mens, maximale autonomie": signalering zonder handeling is niet af).

Bij een HARDE duplicaat-match voert het systeem een inkoopfactuur af naar Afgewezen met reden
"Duplicaat van ‹referentie› (…)" — mét persistente kruisverwijzing naar het origineel (beide kanten
zichtbaar), audit en tijdlijn. Nooit verwijderen, nooit stil; terughalen = de bestaande heropenen-route.

HARDE MATCH (geld in code, geen AI), alle drie tegelijk:
1. zelfde crediteur op btw-nummer — zelfde `vendor_id`, óf een andere vendor van dezelfde administratie
   met hetzelfde btw-nummer (`crediteur_kenmerk.btw_per_vendor`);
2. zelfde referentie — genormaliseerd op witruimte en afgekapt op 30 tekens (RLZ kapt `Reference` op
   30, zie `RlzClient.find_purchase_invoices_by_reference`);
3. zelfde totaalbedrag (cent-exact);
en het origineel is (a) GEBOEKT in RLZ/Odoo — de gecachete treffers van `duplicaatsignaal.py`
(uitkomst `mogelijk_duplicaat`; zelfde vendor + referentie + bedrag, eigen herboek-/tegenboek-keten al
uitgesloten) — óf (b) een ANDER app-document van dezelfde administratie met dezelfde kop (bron: de
`duplicaat_signaal`-kop, d.w.z. de kop zoals hij bij extractie/veldopslag getoetst is).

Wie is het origineel binnen zo'n groep? Deterministisch: eerst een in de app GEBOEKT document (oudste),
dan een RLZ-/Odoo-treffer zónder app-document, dan het document dat het verst in de flow staat
(ter_accordering / vraag_open / boeken_mislukt / wacht_op_iban_accordering), dan het OUDSTE
(`aangemaakt_op`, daarna id). Alle andere groepsleden in een afvoerbare status (te_controleren /
handmatig_afmaken / klaar_om_te_boeken) zijn duplicaten. Een document dat verder in de flow staat
(ter_accordering, geboekt, vraag_open, …) wordt NOOIT automatisch afgevoerd — beslispunt Peter.

ZACHTE signalen voeren nooit af: referentie + bedrag bij een andere crediteur zónder btw-match
(`checks.check_duplicaat_over_crediteuren`, oranje) en de eigen herboek-/tegenboek-keten.

Twee ingangen, één motor (`_voer_af`):
- automatisch (`verwerk_na_signaal_stil`, post-commit ná `bereken_duplicaatsignaal`): alléén bij de
  opt-in `administratie.duplicaat_autoafvoer_ingeschakeld`, systeem-actor, volumerem
  `max_duplicaat_afvoer_per_dag_per_administratie`, elke poging geauditeerd
  (`duplicaat_afgevoerd` / `duplicaat_afvoer_geweigerd` + reden);
- één-klik (`voer_af_als_duplicaat`, altijd — ook zonder opt-in): actor = de mens, `automatisch=False`,
  idempotent (al afgevoerd = zelfde data terug), 409 zonder harde match of bij een status die het niet
  toelaat.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import afwijzen
from app.documenten.crediteur_kenmerk import btw_per_vendor
from app.documenten.models import (
    Afwijzing,
    AfwijzingStatus,
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    DuplicaatSignaal,
    DuplicaatSignaalUitkomst,
)
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.vragen import GeenToewijzingMogelijk, ToegewezeneBuitenScope

logger = logging.getLogger(__name__)

# Statussen waaruit een duplicaat automatisch óf met één klik afgevoerd mag worden — exact de
# herstelbare herkomsten van afwijzen.py (heropenen keert er naar terug). Nooit ter_accordering,
# geboekt of vraag_open (beslispunt Peter voor ter_accordering; wij bouwen dat niet).
AFVOERBARE_STATUSSEN = frozenset(
    {DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN, DocumentStatus.KLAAR_OM_TE_BOEKEN}
)

# Statussen die een app-document uitsluiten als origineel én als duplicaat: het bestaat niet (meer) als
# zelfstandig werkstuk. Afgewezen hoort erbij: een al afgevoerd/afgewezen document is geen origineel
# meer (anders zou een heropend origineel nooit terugkomen).
_UITGESLOTEN_STATUSSEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.GESPLITST,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.NIET_TOEGEWEZEN,
    }
)

# Rangorde "wie is het origineel": lager = eerder origineel. Geboekt wint altijd; daarna het document
# dat al in een verwerkingsstap zit (mens of klant heeft er al iets mee gedaan); dan de rest op leeftijd.
_STATUS_RANG: dict[DocumentStatus, int] = {
    DocumentStatus.GEBOEKT: 0,
    DocumentStatus.TER_ACCORDERING: 1,
    DocumentStatus.BOEKEN_MISLUKT: 1,
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING: 1,
    DocumentStatus.VRAAG_OPEN: 1,
}

_REFERENTIE_MAX = 30  # RLZ kapt Reference op 30 tekens


class DuplicaatAfvoerFout(Exception):
    """Basis voor domeinfouten in de duplicaat-afvoer (router → 409 mét de tekst)."""


class GeenHardeMatch(DuplicaatAfvoerFout):
    """Geen (actuele) harde duplicaat-match voor dit document — of dit document is zélf het origineel."""


class AfvoerNietMogelijk(DuplicaatAfvoerFout):
    """De status van het document laat afvoeren niet toe (ter accordering, geboekt, open vraag, al
    afgewezen om een andere reden, …)."""


def normaliseer_referentie(referentie: str | None) -> str | None:
    """Vergelijkingsvorm van een factuurreferentie: witruimte genormaliseerd, afgekapt op 30 tekens
    (RLZ-gedrag). Leeg = None (niet toetsbaar)."""
    if not referentie:
        return None
    schoon = " ".join(referentie.split())
    return schoon[:_REFERENTIE_MAX] or None


@dataclass(frozen=True)
class Origineel:
    """Het origineel waarvan een document een duplicaat is — genoeg voor de reden-tekst, de
    kruisverwijzing en de UI (nooit een kale UUID zonder leesbare aanduiding)."""

    bron: str  # 'geboekt' (RLZ/Odoo of in de app geboekt) | 'werkvoorraad' (ouder app-document)
    referentie: str
    document_id: uuid.UUID | None = None
    rlz_document_id: uuid.UUID | None = None
    boekstuknummer: str | None = None
    bestandsnaam: str | None = None
    aangemaakt_op: datetime | None = None
    status: str | None = None

    def reden(self) -> str:
        """Deterministische afwijsreden — 'Duplicaat van ‹referentie› (…)'."""
        if self.document_id is not None and self.bestandsnaam:
            datum = f" van {self.aangemaakt_op.date().isoformat()}" if self.aangemaakt_op else ""
            if self.bron == "geboekt":
                boekstuk = f"boekstuk {self.boekstuknummer} / " if self.boekstuknummer else ""
                return f"Duplicaat van {self.referentie} ({boekstuk}document {self.bestandsnaam}{datum}, al geboekt)"
            return f"Duplicaat van {self.referentie} (document {self.bestandsnaam}{datum} in de werkvoorraad)"
        boekstuk = f"boekstuk {self.boekstuknummer}" if self.boekstuknummer else "al geboekt in de boekhouding"
        return f"Duplicaat van {self.referentie} ({boekstuk})"


@dataclass(frozen=True)
class _Lid:
    document_id: uuid.UUID
    status: DocumentStatus
    bestandsnaam: str
    aangemaakt_op: datetime
    vendor_id: uuid.UUID | None
    referentie: str
    totaalbedrag: Decimal


@dataclass(frozen=True)
class Groep:
    """Eén duplicaatgroep rond een document: het origineel + de leden die afgevoerd mogen worden."""

    origineel: Origineel
    duplicaten: list[_Lid]


@dataclass(frozen=True)
class AfgevoerdDuplicaat:
    """Origineel-kant van de kruisverwijzing: één afgevoerd duplicaat van dít document."""

    afwijzing_id: uuid.UUID
    document_id: uuid.UUID
    bestandsnaam: str
    aangemaakt_op: datetime
    referentie: str | None
    automatisch: bool
    afgewezen_op: datetime
    afgewezen_door: uuid.UUID


@dataclass(frozen=True)
class DuplicaatAfvoerStand:
    """Wat het controlescherm nodig heeft: kandidaat (knop + bevestiging), de eigen afvoer (afgevoerd-
    kant) en de afgevoerde duplicaten (origineel-kant)."""

    kandidaat: Origineel | None
    afgevoerd_als_duplicaat_van: Origineel | None
    afgevoerde_duplicaten: list[AfgevoerdDuplicaat]


@dataclass(frozen=True)
class AfvoerResultaat:
    afwijzing: afwijzen.AfwijzingData
    origineel: Origineel
    al_afgevoerd: bool


# ----------------------------------------------------------------------------- groepsbepaling


def _vendor_sleutel(vendor_id: uuid.UUID | None, btw: dict[str, str]) -> str | None:
    """Crediteur-identiteit voor de match: btw-nummer als bekend (dekt dubbele crediteuren), anders de
    vendor zelf. None = geen crediteur → niet toetsbaar."""
    if vendor_id is None:
        return None
    nummer = btw.get(str(vendor_id))
    return f"btw:{nummer}" if nummer else f"vendor:{vendor_id}"


def _leden_met_kop(session: Session, *, administratie_id: uuid.UUID) -> list[_Lid]:
    """Alle toetsbare inkoopfacturen van de administratie mét hun getoetste kop (duplicaat_signaal-rij),
    exclusief verwijderd/gesplitst/samengevoegd/afgewezen/niet_toegewezen."""
    rijen = session.execute(
        select(DuplicaatSignaal, Document)
        .join(Document, DuplicaatSignaal.document_id == Document.id)
        .where(
            DuplicaatSignaal.administratie_id == administratie_id,
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status.notin_(list(_UITGESLOTEN_STATUSSEN)),
            DuplicaatSignaal.vendor_id.isnot(None),
            DuplicaatSignaal.referentie.isnot(None),
            DuplicaatSignaal.totaalbedrag.isnot(None),
        )
    ).all()
    leden: list[_Lid] = []
    for signaal, document in rijen:
        ref = normaliseer_referentie(signaal.referentie)
        if ref is None or signaal.totaalbedrag is None:
            continue
        leden.append(
            _Lid(
                document_id=document.id,
                status=document.status,
                bestandsnaam=document.bestandsnaam,
                aangemaakt_op=document.aangemaakt_op,
                vendor_id=signaal.vendor_id,
                referentie=ref,
                totaalbedrag=Decimal(signaal.totaalbedrag).quantize(Decimal("0.01")),
            )
        )
    return leden


def _groepeer(leden: list[_Lid], btw: dict[str, str]) -> dict[tuple[str, str, Decimal], list[_Lid]]:
    groepen: dict[tuple[str, str, Decimal], list[_Lid]] = {}
    for lid in leden:
        sleutel_vendor = _vendor_sleutel(lid.vendor_id, btw)
        if sleutel_vendor is None:
            continue
        groepen.setdefault((sleutel_vendor, lid.referentie, lid.totaalbedrag), []).append(lid)
    return groepen


def _rang(lid: _Lid) -> tuple[int, datetime, str]:
    return (_STATUS_RANG.get(lid.status, 2), lid.aangemaakt_op, str(lid.document_id))


def _rlz_treffers(session: Session, document_id: uuid.UUID) -> list[dict]:
    rij = session.get(DuplicaatSignaal, document_id)
    if rij is None or rij.uitkomst != DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT.value:
        return []
    return list(rij.treffers or [])


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _origineel_uit_geboekt_lid(session: Session, lid: _Lid, treffers: list[dict]) -> Origineel:
    """In de app geboekt origineel: koppel het RLZ-/Odoo-id (uit de treffers als die er zijn, anders het
    deterministische herboek-GUID) en het boekstuknummer uit het boekvoorstel."""
    voorstel = session.get(Boekvoorstel, lid.document_id)
    cyclus = voorstel.boek_cyclus if voorstel is not None else 0
    eigen_ids = {str(rlz_herboeking_id(lid.document_id, c)) for c in range(cyclus + 1)}
    treffer = next((t for t in treffers if str(t.get("id")) in eigen_ids), None)
    rlz_id = _als_uuid(treffer.get("id")) if treffer else rlz_herboeking_id(lid.document_id, cyclus)
    boekstuk = (voorstel.rlz_boekstuknummer if voorstel is not None else None) or (
        treffer.get("invoice_number") if treffer else None
    )
    return Origineel(
        bron="geboekt",
        referentie=lid.referentie,
        document_id=lid.document_id,
        rlz_document_id=rlz_id,
        boekstuknummer=boekstuk,
        bestandsnaam=lid.bestandsnaam,
        aangemaakt_op=lid.aangemaakt_op,
        status=lid.status.value,
    )


def _bepaal_origineel(session: Session, *, groep: list[_Lid], treffers: list[dict], referentie: str) -> Origineel:
    geboekt = sorted((lid for lid in groep if lid.status == DocumentStatus.GEBOEKT), key=_rang)
    if geboekt:
        return _origineel_uit_geboekt_lid(session, geboekt[0], treffers)
    if treffers:
        t = treffers[0]
        return Origineel(
            bron="geboekt",
            referentie=str(t.get("reference") or referentie),
            rlz_document_id=_als_uuid(t.get("id")),
            boekstuknummer=(str(t["invoice_number"]) if t.get("invoice_number") else None),
        )
    eerste = sorted(groep, key=_rang)[0]
    return Origineel(
        bron="werkvoorraad",
        referentie=eerste.referentie,
        document_id=eerste.document_id,
        bestandsnaam=eerste.bestandsnaam,
        aangemaakt_op=eerste.aangemaakt_op,
        status=eerste.status.value,
    )


def bepaal_groep(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> Groep | None:
    """De duplicaatgroep rond één document, of None als het document niet toetsbaar is (kop incompleet)
    of geen harde match heeft. Sessie van de aanroeper, al gescoopt op de administratie."""
    leden = _leden_met_kop(session, administratie_id=administratie_id)
    btw = btw_per_vendor(session, administratie_id=administratie_id)
    groepen = _groepeer(leden, btw)
    eigen = next((lid for lid in leden if lid.document_id == document_id), None)
    treffers = _rlz_treffers(session, document_id)
    if eigen is None:
        # Kop incompleet of document niet (meer) toetsbaar: zonder eigen kop is er geen groep — óók niet
        # op RLZ-treffers (die horen bij een kop die we dan niet kennen).
        return None
    sleutel_vendor = _vendor_sleutel(eigen.vendor_id, btw)
    if sleutel_vendor is None:
        return None
    groep = groepen.get((sleutel_vendor, eigen.referentie, eigen.totaalbedrag), [eigen])
    if len(groep) < 2 and not treffers:
        return None
    origineel = _bepaal_origineel(session, groep=groep, treffers=treffers, referentie=eigen.referentie)
    duplicaten = sorted(
        (lid for lid in groep if lid.document_id != origineel.document_id and lid.status in AFVOERBARE_STATUSSEN),
        key=_rang,
    )
    return Groep(origineel=origineel, duplicaten=duplicaten)


def werkvoorraad_matches_bulk(
    *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Origineel]:
    """Lijst-lezer (geen N+1): per document dat níét het origineel van zijn groep is, het origineel binnen
    de werkvoorraad/app (RLZ-treffers lopen al via de duplicaatsignaal-chip). Alleen groepen met ≥ 2
    app-documenten."""
    if not document_ids:
        return {}
    gevraagd = set(document_ids)
    with scoped_session(administratie_id) as session:
        leden = _leden_met_kop(session, administratie_id=administratie_id)
        btw = btw_per_vendor(session, administratie_id=administratie_id)
        resultaat: dict[uuid.UUID, Origineel] = {}
        for groep in _groepeer(leden, btw).values():
            if len(groep) < 2:
                continue
            origineel = _bepaal_origineel(session, groep=groep, treffers=[], referentie=groep[0].referentie)
            for lid in groep:
                if lid.document_id != origineel.document_id and lid.document_id in gevraagd:
                    resultaat[lid.document_id] = origineel
        return resultaat


# ----------------------------------------------------------------------------- lezen (UI)


def _origineel_uit_afwijzing(session: Session, afwijzing: Afwijzing) -> Origineel | None:
    if not (
        afwijzing.duplicaat_van_document_id
        or afwijzing.duplicaat_van_rlz_document_id
        or afwijzing.duplicaat_van_referentie
    ):
        return None
    document = (
        session.get(Document, afwijzing.duplicaat_van_document_id) if afwijzing.duplicaat_van_document_id else None
    )
    voorstel = session.get(Boekvoorstel, document.id) if document is not None else None
    return Origineel(
        bron="geboekt" if (document is None or document.status == DocumentStatus.GEBOEKT) else "werkvoorraad",
        referentie=afwijzing.duplicaat_van_referentie or "",
        document_id=afwijzing.duplicaat_van_document_id,
        rlz_document_id=afwijzing.duplicaat_van_rlz_document_id,
        boekstuknummer=voorstel.rlz_boekstuknummer if voorstel is not None else None,
        bestandsnaam=document.bestandsnaam if document is not None else None,
        aangemaakt_op=document.aangemaakt_op if document is not None else None,
        status=document.status.value if document is not None else None,
    )


def afgevoerde_duplicaten_van(session: Session, *, document_id: uuid.UUID) -> list[AfgevoerdDuplicaat]:
    """Origineel-kant: alle OPEN afwijzingen die naar dít document verwijzen (heropend = niet meer
    'afgevoerd', de historie blijft in de rij staan)."""
    rijen = session.execute(
        select(Afwijzing, Document)
        .join(Document, Afwijzing.document_id == Document.id)
        .where(
            Afwijzing.duplicaat_van_document_id == document_id,
            Afwijzing.status == AfwijzingStatus.OPEN.value,
        )
        .order_by(Afwijzing.afgewezen_op)
    ).all()
    return [
        AfgevoerdDuplicaat(
            afwijzing_id=a.id,
            document_id=d.id,
            bestandsnaam=d.bestandsnaam,
            aangemaakt_op=d.aangemaakt_op,
            referentie=a.duplicaat_van_referentie,
            automatisch=bool(a.automatisch),
            afgewezen_op=a.afgewezen_op,
            afgewezen_door=a.afgewezen_door,
        )
        for a, d in rijen
    ]


def _open_afwijzing(session: Session, document_id: uuid.UUID) -> Afwijzing | None:
    return session.scalars(
        select(Afwijzing).where(Afwijzing.document_id == document_id, Afwijzing.status == AfwijzingStatus.OPEN.value)
    ).first()


def stand_voor_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DuplicaatAfvoerStand:
    """Voedt het controlescherm; geen RLZ-/Odoo-calls (alleen cache + DB)."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            return DuplicaatAfvoerStand(kandidaat=None, afgevoerd_als_duplicaat_van=None, afgevoerde_duplicaten=[])
        kandidaat: Origineel | None = None
        if document.status in AFVOERBARE_STATUSSEN and document.soort == DocumentSoort.INKOOPFACTUUR.value:
            groep = bepaal_groep(session, administratie_id=administratie_id, document_id=document_id)
            if groep is not None and any(lid.document_id == document_id for lid in groep.duplicaten):
                kandidaat = groep.origineel
        afgevoerd_van: Origineel | None = None
        if document.status == DocumentStatus.AFGEWEZEN:
            afwijzing = _open_afwijzing(session, document_id)
            if afwijzing is not None:
                afgevoerd_van = _origineel_uit_afwijzing(session, afwijzing)
        return DuplicaatAfvoerStand(
            kandidaat=kandidaat,
            afgevoerd_als_duplicaat_van=afgevoerd_van,
            afgevoerde_duplicaten=afgevoerde_duplicaten_van(session, document_id=document_id),
        )


# ----------------------------------------------------------------------------- afvoeren


def _voer_af(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, origineel: Origineel, automatisch: bool
) -> afwijzen.AfwijzingData:
    """Eén motor voor beide ingangen: de bestaande afwijs-route mét kruisverwijzing."""
    return afwijzen.wijs_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        reden=origineel.reden(),
        duplicaat_van_document_id=origineel.document_id,
        duplicaat_van_rlz_document_id=origineel.rlz_document_id,
        duplicaat_van_referentie=origineel.referentie,
        automatisch=automatisch,
    )


def _origineel_json(origineel: Origineel) -> dict:
    return {
        "bron": origineel.bron,
        "referentie": origineel.referentie,
        "document_id": str(origineel.document_id) if origineel.document_id else None,
        "rlz_document_id": str(origineel.rlz_document_id) if origineel.rlz_document_id else None,
        "boekstuknummer": origineel.boekstuknummer,
        "bestandsnaam": origineel.bestandsnaam,
    }


def voer_af_als_duplicaat(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> AfvoerResultaat:
    """Één-klik "Afvoeren als duplicaat" (altijd beschikbaar, ook zonder opt-in). Idempotent: een document
    dat al als duplicaat is afgevoerd geeft dezelfde data terug (`al_afgevoerd=True`)."""
    from app.documenten.service import DocumentNietGevonden

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status == DocumentStatus.AFGEWEZEN:
            afwijzing = _open_afwijzing(session, document_id)
            origineel = _origineel_uit_afwijzing(session, afwijzing) if afwijzing is not None else None
            if afwijzing is not None and origineel is not None:
                return AfvoerResultaat(
                    afwijzing=afwijzen._naar_data(afwijzing, document), origineel=origineel, al_afgevoerd=True
                )
            raise AfvoerNietMogelijk(
                "Dit document is al afgewezen om een andere reden — heropen het eerst als je het als duplicaat "
                "wilt afvoeren"
            )
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise AfvoerNietMogelijk("Alleen inkoopfacturen kunnen als duplicaat afgevoerd worden")
        if document.status not in AFVOERBARE_STATUSSEN:
            raise AfvoerNietMogelijk(
                f"Vanuit status {document.status.value} kan een document niet als duplicaat afgevoerd worden — "
                "alleen vanuit te controleren, handmatig afmaken of klaar om te boeken"
            )
        groep = bepaal_groep(session, administratie_id=administratie_id, document_id=document_id)
        if groep is None:
            raise GeenHardeMatch(
                "Geen harde duplicaat-match (meer): crediteur, referentie en totaalbedrag komen niet alle drie "
                "overeen met een geboekte of oudere factuur"
            )
        if not any(lid.document_id == document_id for lid in groep.duplicaten):
            raise GeenHardeMatch(
                "Dit document is zelf het origineel van deze duplicaatgroep — voer het nieuwere document af, niet dit"
            )
        origineel = groep.origineel
    data = _voer_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        origineel=origineel,
        automatisch=False,
    )
    return AfvoerResultaat(afwijzing=data, origineel=origineel, al_afgevoerd=False)


def _afgevoerd_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    """Volumerem-teller: automatische afvoer-overgangen van vandaag (tijdlijn-detail `automatisch_afgevoerd`)."""
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .join(Document, DocumentGebeurtenis.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.AFGEWEZEN,
                DocumentGebeurtenis.detail.has_key("automatisch_afgevoerd"),
                DocumentGebeurtenis.tijdstip >= vandaag_begin,
            )
        )
        or 0
    )


def _audit(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actie: str, waarde: dict) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=actie,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=waarde,
            administratie_id=administratie_id,
        )


def verwerk_na_signaal(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[uuid.UUID]:
    """Automatisch pad, post-commit ná de duplicaatsignaal-berekening (extractie én veldopslag). Alleen
    bij de opt-in; systeem-actor; volumerem; elke poging geauditeerd. Geeft de afgevoerde document-id's
    terug (test-/log-doel). Zonder opt-in bewust géén audit-ruis (dat is de default voor alles)."""
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.duplicaat_autoafvoer_ingeschakeld:
            return []
        groep = bepaal_groep(session, administratie_id=administratie_id, document_id=document_id)
        if groep is None or not groep.duplicaten:
            return []
        origineel = groep.origineel
        duplicaten = list(groep.duplicaten)
        limiet = settings.max_duplicaat_afvoer_per_dag_per_administratie
        al_vandaag = _afgevoerd_vandaag(session, administratie_id=administratie_id)

    afgevoerd: list[uuid.UUID] = []
    for lid in duplicaten:
        if al_vandaag + len(afgevoerd) >= limiet:
            _audit(
                administratie_id=administratie_id,
                document_id=lid.document_id,
                actie="duplicaat_afvoer_geweigerd",
                waarde={
                    "reden": (
                        f"Volumerem: dagelijkse limiet van {limiet} automatische duplicaat-afvoeren bereikt — "
                        "document blijft in de werkvoorraad"
                    ),
                    "origineel": _origineel_json(origineel),
                },
            )
            continue
        try:
            _voer_af(
                administratie_id=administratie_id,
                document_id=lid.document_id,
                actor_id=SYSTEEM_ACTOR_ID,
                origineel=origineel,
                automatisch=True,
            )
        except (GeenToewijzingMogelijk, ToegewezeneBuitenScope, OngeldigeStatusovergang, afwijzen.AfwijzingFout) as exc:
            _audit(
                administratie_id=administratie_id,
                document_id=lid.document_id,
                actie="duplicaat_afvoer_geweigerd",
                waarde={"reden": str(exc), "origineel": _origineel_json(origineel)},
            )
            continue
        afgevoerd.append(lid.document_id)
        _audit(
            administratie_id=administratie_id,
            document_id=lid.document_id,
            actie="duplicaat_afgevoerd",
            waarde={"reden": origineel.reden(), "origineel": _origineel_json(origineel), "automatisch": True},
        )
    return afgevoerd


def verwerk_na_signaal_stil(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID) -> None:
    """Hook-variant: een fout is een gelogde waarschuwing — de afvoer is een optimalisatie bovenop de
    normale flow, nooit een blokkade van extractie of opslag."""
    if administratie_id is None:
        return
    try:
        verwerk_na_signaal(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — automatisering mag de upload/worker/opslag nooit laten falen
        logger.exception("Duplicaat-afvoer mislukt voor document %s", document_id)
