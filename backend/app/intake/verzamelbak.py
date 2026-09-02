"""Verzamelbak "Niet toegewezen" (mockup werkvoorraad-paneel): alles wat niet eenduidig aan een
administratie koppelt, zichtbaar tot een mens beslist. Toewijzen leert het toewijzings-geheugen
en start de normale extractieflow onder de AVG-gate van de gekozen administratie; "hoort niet
bij ons" vergt een verplichte reden en blijft terugvindbaar (status afgewezen) — nooit een
delete."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.mime import content_type_voor
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.service import (
    BronBestand,
    DocumentNietGevonden,
    _schrijf_overgang,
    _sla_bronbestand_op,
    _standaard_opslag,
    beeld_is_bron,
    start_extractie_na_toewijzing,
)
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur
from app.documenten.storage import DocumentOpslag
from app.intake.models import IntakeSplitsing, IntakeSplitsingStatus
from app.intake.redenen import omschrijf_intake_reden
from app.intake.toewijzing import leer_toewijzing


class VerzamelbakFout(Exception):
    pass


class DocumentNietInVerzamelbak(VerzamelbakFout):
    """De actie kan alleen op een document met status niet_toegewezen zonder administratie."""


class RedenVerplicht(VerzamelbakFout):
    """ "Hoort niet bij ons" zonder reden wordt geweigerd (mockup: verplichte reden)."""


class OnbekendeAdministratie(VerzamelbakFout):
    pass


class SamenvoegenGeweigerd(VerzamelbakFout):
    """Poort van de handmatige samenvoeg-actie (zelfde document, al een beeld, niet in de bak)."""


class ZelfdeTypeBevestigingNodig(VerzamelbakFout):
    """Twee UBL's of twee PDF's samenvoegen kan alleen mét expliciete bevestiging (nooit stil)."""


@dataclass(frozen=True)
class VerzamelbakItem:
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    bron: str
    afzender_hint: str | None
    tenaamstelling: str | None
    suggestie_administratie_id: uuid.UUID | None
    suggestie_bron: str | None
    #: Technische intake-reden uit de jongste niet_toegewezen-overgang in de tijdlijn (02-09:
    #: niet langer None — de rij toont waaróm het document in de bak ligt).
    reden: str | None
    #: Leesbare vertaling van `reden` voor de rij (app/intake/redenen.py); None = niets extra.
    reden_label: str | None
    aangemaakt_op: datetime
    splitsing_id: uuid.UUID | None
    splitsing_voorstel: dict | None
    #: Bundeling/samenvoegen 02-09: bestandsnaam van het beeld (PDF) naast een UBL-document, anders None.
    beeld_bestandsnaam: str | None = None
    #: Handmatig samengevoegde tweede rij (status samengevoegd) die in dit document is opgegaan.
    samengevoegd_document_id: uuid.UUID | None = None
    samengevoegd_bestandsnaam: str | None = None
    #: Herkomst-mail (voor de samenvoeg-waarschuwing "ander intake-bericht").
    intake_bericht_id: uuid.UUID | None = None


def haal_bijlage_op(
    *, document_id: uuid.UUID, opslag: DocumentOpslag | None = None, vorm: str = "beeld"
) -> tuple[bytes, str, str]:
    """Bestand van een VERZAMELBAK-document (besluit Peter 25-08, punt D1: preview-popup in de
    verzamelbak). Verzamelbak-documenten hebben geen administratie (RLS-scope NULL), dus de
    administratie-gescoopte bestand-route past niet; deze leesroute is fail-closed beperkt tot
    documenten die écht nog in de verzamelbak staan (administratie NULL + status
    niet_toegewezen) — een al toegewezen document loopt via zijn administratie-route.
    Retourneert (inhoud, bestandsnaam, content_type)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(None) as session:
        document = session.get(Document, document_id)
        if (
            document is None
            or document.administratie_id is not None
            or document.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            raise DocumentNietGevonden(f"Geen verzamelbak-document: {document_id}")
        if vorm != "data" and beeld_is_bron(document):
            # Gebundeld UBL+PDF (02-09): de mens ziet de PDF; de UBL blijft als vorm=data leesbaar.
            opslag_pad = document.bron_opslag_pad
            bestandsnaam = document.bron_bestandsnaam or "beeld.pdf"
            content_type = document.bron_content_type or "application/pdf"
        else:
            opslag_pad = document.opslag_pad
            bestandsnaam = document.bestandsnaam
            content_type = content_type_voor(bestandsnaam)
    inhoud = opslag.lezen(pad=opslag_pad)
    return inhoud, bestandsnaam, content_type


def _jongste_intake_redenen(session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Per document de `reden` uit de jóngste tijdlijnrij die op niet_toegewezen uitkomt (de
    intake-registratie óf een latere herlezing) — één gebatchte query, geen lookup per rij."""
    if not document_ids:
        return {}
    rangnummer = (
        func.row_number()
        .over(partition_by=DocumentGebeurtenis.document_id, order_by=DocumentGebeurtenis.tijdstip.desc())
        .label("rang")
    )
    sub = (
        select(DocumentGebeurtenis.document_id, DocumentGebeurtenis.detail, rangnummer)
        .where(
            DocumentGebeurtenis.document_id.in_(document_ids),
            DocumentGebeurtenis.naar_status == DocumentStatus.NIET_TOEGEWEZEN,
        )
        .subquery()
    )
    rijen = session.execute(select(sub.c.document_id, sub.c.detail).where(sub.c.rang == 1)).all()
    redenen: dict[uuid.UUID, str | None] = {}
    for document_id, detail in rijen:
        reden = (detail or {}).get("reden") if isinstance(detail, dict) else None
        redenen[document_id] = reden if isinstance(reden, str) and reden.strip() else None
    return redenen


def lijst_verzamelbak() -> list[VerzamelbakItem]:
    """Alle open verzamelbak-documenten (administratie NULL, status niet_toegewezen), incl. een
    eventueel openstaand splitsingsvoorstel én de intake-reden (02-09) — nieuwste eerst."""
    with scoped_session(None) as session:
        documenten = session.scalars(
            select(Document)
            .where(Document.administratie_id.is_(None), Document.status == DocumentStatus.NIET_TOEGEWEZEN)
            .order_by(Document.aangemaakt_op.desc())
        ).all()
        redenen = _jongste_intake_redenen(session, [d.id for d in documenten])
        splitsingen = {
            s.bron_document_id: s
            for s in session.scalars(
                select(IntakeSplitsing).where(
                    IntakeSplitsing.bron_document_id.in_([d.id for d in documenten]),
                    IntakeSplitsing.status == IntakeSplitsingStatus.VOORGESTELD.value,
                )
            )
        }
        samengevoegd_per_leidend = {
            d.samengevoegd_in_id: d
            for d in session.scalars(
                select(Document).where(
                    Document.samengevoegd_in_id.in_([d.id for d in documenten]),
                    Document.status == DocumentStatus.SAMENGEVOEGD,
                )
            )
        }
        items = []
        for document in documenten:
            splitsing = splitsingen.get(document.id)
            reden = redenen.get(document.id)
            samengevoegd = samengevoegd_per_leidend.get(document.id)
            items.append(
                VerzamelbakItem(
                    document_id=document.id,
                    bestandsnaam=document.bestandsnaam,
                    soort=document.soort,
                    bron=document.bron.value,
                    afzender_hint=document.afzender_hint,
                    tenaamstelling=document.tenaamstelling,
                    suggestie_administratie_id=document.toewijzing_suggestie_administratie_id,
                    suggestie_bron=document.toewijzing_suggestie_bron,
                    reden=reden,
                    reden_label=omschrijf_intake_reden(reden, tenaamstelling=document.tenaamstelling),
                    aangemaakt_op=document.aangemaakt_op,
                    splitsing_id=splitsing.id if splitsing else None,
                    splitsing_voorstel=splitsing.voorstel if splitsing else None,
                    beeld_bestandsnaam=document.bron_bestandsnaam if beeld_is_bron(document) else None,
                    samengevoegd_document_id=samengevoegd.id if samengevoegd else None,
                    samengevoegd_bestandsnaam=samengevoegd.bestandsnaam if samengevoegd else None,
                    intake_bericht_id=document.intake_bericht_id,
                )
            )
        return items


@dataclass(frozen=True)
class VerzamelbakActieResultaat:
    """Uitkomst van toewijzen / hoort-niet-bij-ons (avondrun 26-08, optimistisch paneel):
    `al_verwerkt` = de actie was al eerder gedaan (tweede klik, collega, retry ná time-out) —
    géén fout, niets opnieuw gedaan, rustig gemeld; de DB blijft de bron van waarheid."""

    status: DocumentStatus
    al_verwerkt: bool = False
    melding: str | None = None


def _menselijke_toestand(document: Document) -> str:
    """Geen enum-jargon in een melding aan de gebruiker (de oude tekst "staat niet (meer) in de
    verzamelbak (status: ontvangen)" toonde een geslaagde actie als fout)."""
    if document.status == DocumentStatus.AFGEWEZEN and document.administratie_id is None:
        return "is al afgehandeld als 'hoort niet bij ons'"
    if document.status == DocumentStatus.GESPLITST:
        return "is intussen gesplitst in losse facturen"
    if document.status == DocumentStatus.SAMENGEVOEGD:
        return "is intussen samengevoegd met een ander document"
    if document.administratie_id is not None:
        return "is intussen al toegewezen aan een administratie"
    return f"is intussen al verwerkt ({document.status.value.replace('_', ' ')})"


NIET_MEER_ZICHTBAAR_MELDING = (
    "Dit document staat niet (meer) in de verzamelbak — waarschijnlijk heeft een collega het "
    "intussen aan een andere administratie toegewezen. Ververs de lijst."
)


def _laad_verzamelbak_document(session, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(NIET_MEER_ZICHTBAAR_MELDING)
    if document.administratie_id is not None or document.status != DocumentStatus.NIET_TOEGEWEZEN:
        raise DocumentNietInVerzamelbak(f"Dit document {_menselijke_toestand(document)} — er is niets gewijzigd.")
    return document


def wijs_toe(
    *, document_id: uuid.UUID, administratie_id: uuid.UUID, actor_id: uuid.UUID
) -> VerzamelbakActieResultaat:
    """Handmatige toewijzing vanuit de verzamelbak: administratie zetten, toewijzings-geheugen
    leren (mockup: "wordt onthouden"), terug naar ontvangen en de normale extractieflow starten
    (AVG-gate van de gekozen administratie geldt vanaf hier).

    Idempotent (avondrun 26-08): is het document al aan DEZE administratie toegewezen (tweede
    klik, retry ná een time-out, collega), dan gebeurt er niets en komt `al_verwerkt=True` terug —
    geen fout. Toegewezen aan een ándere administratie = onzichtbaar onder RLS →
    DocumentNietGevonden met een leesbare melding (router: 404)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OnbekendeAdministratie(f"Onbekende administratie: {administratie_id}")
        bestaand = session.get(Document, document_id)
        if (
            bestaand is not None
            and bestaand.administratie_id == administratie_id
            and bestaand.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            return VerzamelbakActieResultaat(
                status=bestaand.status,
                al_verwerkt=True,
                melding=f"Was al toegewezen aan {administratie.naam} — niets opnieuw gedaan.",
            )
        document = _laad_verzamelbak_document(session, document_id)
        document.administratie_id = administratie_id
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.ONTVANGEN,
            actor_id=actor_id,
            detail={"toegewezen_aan_administratie": str(administratie_id), "vanuit": "verzamelbak"},
        )
        leer_toewijzing(
            session,
            administratie_id=administratie_id,
            actor_id=actor_id,
            tenaamstelling=document.tenaamstelling,
            afzender=document.afzender_hint,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="verzamelbak_toegewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"administratie_id": str(administratie_id)},
            administratie_id=administratie_id,
        )

    eind_status = start_extractie_na_toewijzing(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )
    return VerzamelbakActieResultaat(status=eind_status)


def hoort_niet_bij_ons(*, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> VerzamelbakActieResultaat:
    """ "Hoort niet bij ons" — verplichte reden, document blijft terugvindbaar als afgewezen
    (mockup: "blijft in het archief terugvindbaar"). Het toewijzings-geheugen leert hier bewust
    níéts (een verkeerd geadresseerd document is geen betrouwbare hint).

    Idempotent (avondrun 26-08): al afgewezen-zonder-administratie (= eerder "hoort niet bij
    ons") → `al_verwerkt=True`, niets opnieuw vastgelegd — de eerste reden blijft de reden."""
    schone_reden = reden.strip() if reden else ""
    if not schone_reden:
        raise RedenVerplicht("'Hoort niet bij ons' vereist een reden")
    with scoped_session(None, actor_id=actor_id) as session:
        bestaand = session.get(Document, document_id)
        if bestaand is not None and bestaand.administratie_id is None and bestaand.status == DocumentStatus.AFGEWEZEN:
            return VerzamelbakActieResultaat(
                status=bestaand.status,
                al_verwerkt=True,
                melding="Was al vastgelegd als 'hoort niet bij ons' — niets opnieuw gedaan.",
            )
        document = _laad_verzamelbak_document(session, document_id)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.AFGEWEZEN,
            actor_id=actor_id,
            detail={"hoort_niet_bij_ons": True, "reden": schone_reden},
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="verzamelbak_hoort_niet_bij_ons",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": schone_reden},
            administratie_id=None,
        )
        return VerzamelbakActieResultaat(status=document.status)


# ---- UBL-samenvatting (preview zonder beeld) ---------------------------------------------------


@dataclass(frozen=True)
class UblSamenvatting:
    leverancier: str | None
    afnemer: str | None
    factuurnummer: str | None
    factuurdatum: str | None
    totaal_excl: str | None
    totaal_incl: str | None
    valuta: str | None
    regelaantal: int
    regels: list[dict]


def ubl_samenvatting(*, document_id: uuid.UUID, opslag: DocumentOpslag | None = None) -> UblSamenvatting:
    """Gerenderde samenvatting van een losse UBL zonder beeld (diagnose 02-09 punt 2: "geen
    paginabeeld" wordt een leesbare kaart). Alleen voor échte verzamelbak-documenten."""
    inhoud, bestandsnaam, _ = haal_bijlage_op(document_id=document_id, opslag=opslag, vorm="data")
    if not bestandsnaam.lower().endswith(".xml"):
        raise DocumentNietGevonden("Geen UBL-document")
    try:
        v = parseer_ubl_factuur(inhoud)
    except GeenGeldigeUbl as exc:
        raise DocumentNietGevonden(f"Geen geldige UBL: {exc}") from exc
    return UblSamenvatting(
        leverancier=v.leverancier_naam,
        afnemer=v.klant_naam,
        factuurnummer=v.factuurnummer,
        factuurdatum=v.factuurdatum,
        totaal_excl=v.totaal_excl,
        totaal_incl=v.totaal_incl,
        valuta=v.valuta,
        regelaantal=v.regelaantal,
        regels=[
            {"omschrijving": r.get("omschrijving"), "netto_bedrag": r.get("netto_bedrag"), "aantal": r.get("aantal")}
            for r in list(v.ubl_regels)[:8]
        ],
    )


# ---- Handmatig samenvoegen (diagnose 02-09 punt 2, toevoeging Peter) ---------------------------


@dataclass(frozen=True)
class SamenvoegResultaat:
    document_id: uuid.UUID
    samengevoegd_document_id: uuid.UUID
    beeld_bestandsnaam: str
    waarschuwingen: list[str]


def _is_xml(document: Document) -> bool:
    return document.bestandsnaam.lower().endswith(".xml")


def voeg_samen(
    *,
    leidend_document_id: uuid.UUID,
    ander_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    bevestig_zelfde_type: bool = False,
    opslag: DocumentOpslag | None = None,
) -> SamenvoegResultaat:
    """Twee verzamelbak-rijen → één document. De mens kiest het LEIDENDE bestand (UBL → velden
    deterministisch; PDF → normale extractie ná toewijzing); het andere bestand wordt het beeld/de
    bron (zelfde `bron_*`-mechaniek als het automatische paar). De tweede rij krijgt de terminale
    status `samengevoegd` mét verwijzing — nooit verwijderen (beide sha256's blijven terugvindbaar),
    tijdlijn op beide kanten, audit oud→nieuw.

    Poorten: beide rijen echt in de verzamelbak; niet hetzelfde document; het leidende document
    heeft nog geen beeld/bron; twee UBL's of twee PDF's alleen mét `bevestig_zelfde_type`. Een
    ander intake-bericht is een WAARSCHUWING (in het resultaat), geen blokkade."""
    if leidend_document_id == ander_document_id:
        raise SamenvoegenGeweigerd("Kies twee verschillende documenten.")
    opslag = opslag or _standaard_opslag()
    waarschuwingen: list[str] = []
    with scoped_session(None, actor_id=actor_id) as session:
        leidend = _laad_verzamelbak_document(session, leidend_document_id)
        ander = _laad_verzamelbak_document(session, ander_document_id)
        if leidend.bron_opslag_pad is not None:
            raise SamenvoegenGeweigerd(
                f"'{leidend.bestandsnaam}' heeft al een beeld/bron ({leidend.bron_bestandsnaam}) — maak dat eerst ongedaan."
            )
        if ander.bron_opslag_pad is not None:
            raise SamenvoegenGeweigerd(
                f"'{ander.bestandsnaam}' heeft zelf al een beeld/bron ({ander.bron_bestandsnaam}) — kies dát document als leidend of maak het eerst ongedaan."
            )
        if _is_xml(leidend) == _is_xml(ander) and not bevestig_zelfde_type:
            soort = "UBL-bestanden" if _is_xml(leidend) else "PDF's"
            raise ZelfdeTypeBevestigingNodig(
                f"Beide bestanden zijn {soort} — dat is zelden één factuur. Bevestig expliciet als je ze toch wilt samenvoegen."
            )
        if leidend.intake_bericht_id != ander.intake_bericht_id:
            waarschuwingen.append("De twee bestanden komen uit verschillende e-mails/uploads.")
        ander_inhoud = opslag.lezen(pad=ander.opslag_pad)
        bron = BronBestand(
            bestandsnaam=ander.bestandsnaam, inhoud=ander_inhoud, content_type=content_type_voor(ander.bestandsnaam)
        )
        bron_pad = _sla_bronbestand_op(opslag, opslag_pad=leidend.opslag_pad, bron=bron)
        oud = {"bron_bestandsnaam": leidend.bron_bestandsnaam}
        leidend.bron_opslag_pad = bron_pad
        leidend.bron_bestandsnaam = bron.bestandsnaam
        leidend.bron_content_type = bron.content_type
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=leidend.id,
                van_status=leidend.status,
                naar_status=leidend.status,
                actor_id=actor_id,
                detail={
                    "samengevoegd_met": str(ander.id),
                    "bestandsnaam": ander.bestandsnaam,
                    "reden": "handmatig samengevoegd in de verzamelbak — dit bestand is leidend",
                },
            )
        )
        ander.samengevoegd_in_id = leidend.id
        _schrijf_overgang(
            session,
            document=ander,
            naar=DocumentStatus.SAMENGEVOEGD,
            actor_id=actor_id,
            detail={
                "samengevoegd_in": str(leidend.id),
                "leidend_bestandsnaam": leidend.bestandsnaam,
                "reden": "handmatig samengevoegd in de verzamelbak — dit bestand is het beeld/de bron",
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=leidend.id,
            actie="verzamelbak_samengevoegd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "bron_bestandsnaam": bron.bestandsnaam,
                "samengevoegd_document_id": str(ander.id),
                "zelfde_type_bevestigd": bevestig_zelfde_type,
                "waarschuwingen": waarschuwingen,
            },
            administratie_id=None,
        )
        return SamenvoegResultaat(
            document_id=leidend.id,
            samengevoegd_document_id=ander.id,
            beeld_bestandsnaam=bron.bestandsnaam,
            waarschuwingen=waarschuwingen,
        )


def maak_samenvoegen_ongedaan(*, document_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID:
    """Ongedaan maken zolang het leidende document nog in de verzamelbak staat: de tweede rij komt
    terug (samengevoegd → niet_toegewezen), het leidende document verliest zijn beeld/bron-kolommen
    (het bestand blijft op de opslag staan — niets wordt verwijderd). Geeft het id van de teruggezette
    rij."""
    with scoped_session(None, actor_id=actor_id) as session:
        leidend = _laad_verzamelbak_document(session, document_id)
        ander = session.scalars(
            select(Document).where(
                Document.samengevoegd_in_id == leidend.id, Document.status == DocumentStatus.SAMENGEVOEGD
            )
        ).first()
        if ander is None:
            raise SamenvoegenGeweigerd("Dit document is niet handmatig samengevoegd — er is niets ongedaan te maken.")
        oud = {"bron_bestandsnaam": leidend.bron_bestandsnaam, "samengevoegd_document_id": str(ander.id)}
        leidend.bron_opslag_pad = None
        leidend.bron_bestandsnaam = None
        leidend.bron_content_type = None
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=leidend.id,
                van_status=leidend.status,
                naar_status=leidend.status,
                actor_id=actor_id,
                detail={"samenvoegen_ongedaan": str(ander.id), "reden": "samenvoegen ongedaan gemaakt in de verzamelbak"},
            )
        )
        ander.samengevoegd_in_id = None
        _schrijf_overgang(
            session,
            document=ander,
            naar=DocumentStatus.NIET_TOEGEWEZEN,
            actor_id=actor_id,
            detail={"reden": "samenvoegen ongedaan gemaakt — terug in de verzamelbak", "was_samengevoegd_in": str(leidend.id)},
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=leidend.id,
            actie="verzamelbak_samenvoegen_ongedaan",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"bron_bestandsnaam": None},
            administratie_id=None,
        )
        return ander.id
