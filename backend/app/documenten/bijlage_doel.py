"""Bijlage volgt het duplicaat naar het origineel (BUG 03-10, Peter: "werkdetails zonder factuur kan niet"; BESLISSINGEN
"BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)", subkop "Bijlage
volgt het
duplicaat naar het origineel (03-10)").

De mail zei bij welke factuur de bijlage hoort. Is die factuur intussen als duplicaat afgevoerd
(`afgevoerd_duplicaat`) of
afgewezen, dan gooien we die kennis niet weg maar volgen we 'm naar het document dat wél telt:

1. `afwijzing.duplicaat_van_document_id` van de open afvoer-afwijzing (de kruisverwijzing van 04-09);
2. anders de losse vlag `document.mogelijk_duplicaat_van_id`;
3. anders hetzelfde factuurnummer (`boekvoorstel.referentie_norm` — de ENE normalisatie van 16-09) binnen dezelfde
   administratie, mét een niet-uitgesloten status.

Een doel mag GEBOEKT zijn (bijlage mag bij een geboekt document hangen — bestaand gedrag "(geboekt)"); een doel dat
zelf weer
afgevoerd/afgewezen is wordt verder gevolgd (keten, max `MAX_STAPPEN`). Nooit een doel buiten de administratie van het
duplicaat, nooit raden bij meerdere factuurnummer-treffers (= geen doel, zichtbaar overgeslagen).

Drie afnemers: de nazorg `bijlagen-nabundelen` (lees het doel in de dry-run, koppelt in de échte run), het
live-intakepad
(`verwerking._verwerk_items_met_bijlagen`: een factuur die vóór de AI-stap als byte-identiek duplicaat wordt
afgevoerd draagt
haar bijlagen aan het origineel) en de referentie-afvoer ná extractie (`duplicaat_afvoer._voer_af` →
`verhuis_bijlagen_naar_
origineel`: bijlagen die al aan het duplicaat hingen verhuizen mee). Geen origineel gevonden = nooit stil: de nazorg
meldt
"factuur afgewezen (‹reden›) — bijlage ook afwijzen?" en zet in de échte run een tijdlijn-notitie op de bijlage
(`TIJDLIJN_SLEUTEL_AFGEWEZEN`) die het controlescherm als chip mét link naar de afgewezen factuur toont. Nooit
automatisch
afwijzen."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.documenten.models import (
    Afwijzing,
    AfwijzingStatus,
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
)
from app.documenten.referentie import normaliseer_referentie

logger = logging.getLogger(__name__)

#: Statussen waarin een factuur geen drager (meer) is — gelijk aan `bijlagen_nabundelen._FACTUUR_UITGESLOTEN`.
UITGESLOTEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
        DocumentStatus.GESPLITST,
        DocumentStatus.AFGEWEZEN,
    }
)
#: Een factuur in deze stand wordt naar haar origineel/tegenhanger gevolgd.
VOLGBAAR = frozenset({DocumentStatus.AFGEVOERD_DUPLICAAT, DocumentStatus.AFGEWEZEN})
MAX_STAPPEN = 5

BRON_AFWIJZING = "afwijzing"
BRON_VLAG = "vlag"
BRON_FACTUURNUMMER = "factuurnummer"

#: Tijdlijn-sleutel op een BIJLAGE-document: de factuur uit dezelfde mail is afgewezen en er is geen tegenhanger.
TIJDLIJN_SLEUTEL_AFGEWEZEN = "bijlage_factuur_afgewezen"
#: Tijdlijn-sleutel op een bijlage-rij die van het duplicaat naar het origineel verhuisde.
TIJDLIJN_SLEUTEL_VERHUISD = "bijlage_naar_origineel"
AUDIT_BIJLAGE_NAAR_ORIGINEEL = "bijlage_naar_origineel"


@dataclass(frozen=True)
class Doel:
    """Het document waar de bijlage uiteindelijk bij hoort, mét het pad dat ernaartoe leidde."""

    document: Document
    bron: str  # BRON_AFWIJZING | BRON_VLAG | BRON_FACTUURNUMMER
    via_document_id: uuid.UUID  # het afgevoerde/afgewezen document waarvan we vertrokken
    via_bestandsnaam: str
    via_status: DocumentStatus
    stappen: int

    @property
    def label(self) -> str:
        """Leesbaar voor de dry-run-regel/chip: "via duplicaat → ‹origineel›"."""
        soort = "duplicaat" if self.via_status == DocumentStatus.AFGEVOERD_DUPLICAAT else "afgewezen factuur"
        return f"via {soort} → {self.document.bestandsnaam}"


@dataclass(frozen=True)
class GeenDoel:
    """Geen tegenhanger gevonden — de reden is zichtbaar (nooit stil)."""

    via_document_id: uuid.UUID
    via_bestandsnaam: str
    via_status: DocumentStatus
    reden: str
    afwijs_reden: str | None = None


def open_afwijzing(session: Session, document_id: uuid.UUID) -> Afwijzing | None:
    return session.scalars(
        select(Afwijzing).where(Afwijzing.document_id == document_id, Afwijzing.status == AfwijzingStatus.OPEN.value)
    ).first()


def _zelfde_factuurnummer(session: Session, document: Document) -> tuple[Document | None, str | None]:
    """Precies één ander document in dezelfde administratie mét hetzelfde genormaliseerde factuurnummer en een
    niet-uitgesloten status; meerdere = nooit raden (None mét reden)."""
    voorstel = session.get(Boekvoorstel, document.id)
    if voorstel is None or not voorstel.referentie:
        return None, "geen factuurnummer bekend op het afgevoerde/afgewezen document"
    norm = voorstel.referentie_norm or normaliseer_referentie(voorstel.referentie)
    if not norm:
        return None, "factuurnummer niet normaliseerbaar"
    kandidaten = [
        d
        for d, _ in session.execute(
            select(Document, Boekvoorstel.document_id)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .where(
                Boekvoorstel.referentie_norm == norm,
                Document.id != document.id,
                Document.administratie_id == document.administratie_id,
            )
            .order_by(Document.aangemaakt_op)
        ).all()
        if d.status not in UITGESLOTEN
    ]
    if len(kandidaten) == 1:
        return kandidaten[0], None
    if not kandidaten:
        return None, f"geen ander document mét factuurnummer {voorstel.referentie} in deze administratie"
    return None, f"{len(kandidaten)} documenten mét factuurnummer {voorstel.referentie} — niet eenduidig"


def _volgende(session: Session, document: Document) -> tuple[Document | None, str | None, str | None]:
    """(doel, bron, reden-als-geen-doel) voor één stap. Volgorde: afwijzing-link → vlag → factuurnummer."""
    afwijzing = open_afwijzing(session, document.id)
    if afwijzing is not None and afwijzing.duplicaat_van_document_id is not None:
        doel = session.get(Document, afwijzing.duplicaat_van_document_id)
        if doel is not None and doel.administratie_id == document.administratie_id:
            return doel, BRON_AFWIJZING, None
    if document.mogelijk_duplicaat_van_id is not None:
        doel = session.get(Document, document.mogelijk_duplicaat_van_id)
        if doel is not None and doel.administratie_id == document.administratie_id:
            return doel, BRON_VLAG, None
    doel, reden = _zelfde_factuurnummer(session, document)
    if doel is not None:
        return doel, BRON_FACTUURNUMMER, None
    return None, None, reden


def volg_naar_origineel(session: Session, document: Document) -> Doel | GeenDoel | None:
    """None = het document is geen afgevoerd duplicaat/afgewezen factuur (niets te volgen). Anders het doel óf een
    zichtbare reden. De sessie is de RLS-scope van het document (zelfde administratie); een origineel in een andere
    administratie is onbereikbaar en telt dus als niet gevonden."""
    if document.status not in VOLGBAAR:
        return None
    start = document
    huidig = document
    bron = ""
    afwijs_reden = None
    afwijzing = open_afwijzing(session, start.id)
    if afwijzing is not None:
        afwijs_reden = afwijzing.reden
    for stap in range(1, MAX_STAPPEN + 1):
        doel, doel_bron, reden = _volgende(session, huidig)
        if doel is None:
            return GeenDoel(
                via_document_id=start.id,
                via_bestandsnaam=start.bestandsnaam,
                via_status=start.status,
                reden=reden or "geen origineel gevonden",
                afwijs_reden=afwijs_reden,
            )
        bron = bron or doel_bron or ""
        if doel.status in UITGESLOTEN:
            if doel.status in VOLGBAAR and doel.id != start.id:
                huidig = doel  # keten: het origineel is zelf ook weer afgevoerd/afgewezen
                continue
            return GeenDoel(
                via_document_id=start.id,
                via_bestandsnaam=start.bestandsnaam,
                via_status=start.status,
                reden=f"origineel {doel.bestandsnaam} is zelf {doel.status.value.replace('_', ' ')}",
                afwijs_reden=afwijs_reden,
            )
        return Doel(
            document=doel,
            bron=bron,
            via_document_id=start.id,
            via_bestandsnaam=start.bestandsnaam,
            via_status=start.status,
            stappen=stap,
        )
    return GeenDoel(
        via_document_id=start.id,
        via_bestandsnaam=start.bestandsnaam,
        via_status=start.status,
        reden=f"keten van duplicaten langer dan {MAX_STAPPEN} stappen",
        afwijs_reden=afwijs_reden,
    )


# ---- verhuizen van bijlagen die al aan het duplicaat hingen --------------------------------------------------------


def verhuis_bijlagen_naar_origineel(
    session: Session, *, duplicaat: Document, origineel: Document, actor_id: uuid.UUID, herkomst: str
) -> list[uuid.UUID]:
    """Élke bijlage-rij (`samengevoegd` mét `samenvoeg_rol`) van het duplicaat gaat over naar het origineel: zelfde rol,
    tijdlijnregel op bijlage én origineel, audit `bijlage_naar_origineel`. Idempotent (tweede keer: niets). Zelfde
    scope-eis als de koppeling zelf."""
    from app.documenten import (
        bijlagen as bijlagen_module,
    )  # lokaal: bijlagen importeert dit module niet, maar houd het los

    if origineel.id == duplicaat.id or origineel.administratie_id != duplicaat.administratie_id:
        return []
    if origineel.status in UITGESLOTEN:
        return []
    verhuisd: list[uuid.UUID] = []
    for bijlage in bijlagen_module.lijst_bijlagen_in_sessie(session, duplicaat.id):
        bijlage.samengevoegd_in_id = origineel.id
        reden = (
            f"bijlage volgt het duplicaat naar het origineel ({herkomst}): '{bijlage.bestandsnaam}' hing aan "
            f"'{duplicaat.bestandsnaam}' ({duplicaat.status.value.replace('_', ' ')}) en hoort nu bij "
            f"'{origineel.bestandsnaam}'"
        )
        detail = {
            TIJDLIJN_SLEUTEL_VERHUISD: True,
            "van_document_id": str(duplicaat.id),
            "samengevoegd_in": str(origineel.id),
            "leidend_bestandsnaam": origineel.bestandsnaam,
            "herkomst": herkomst,
            "reden": reden,
        }
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=bijlage.id,
                van_status=bijlage.status,
                naar_status=bijlage.status,
                actor_id=actor_id,
                detail=detail,
            )
        )
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=origineel.id,
                van_status=origineel.status,
                naar_status=origineel.status,
                actor_id=actor_id,
                detail={
                    bijlagen_module.TIJDLIJN_SLEUTEL: True,
                    TIJDLIJN_SLEUTEL_VERHUISD: True,
                    "bijlage_document_id": str(bijlage.id),
                    "bijlage_bestandsnaam": bijlage.bestandsnaam,
                    "niet_eenduidig": bijlage.samenvoeg_rol == bijlagen_module.ROL_BIJLAGE_NIET_EENDUIDIG,
                    "herkomst": herkomst,
                    "reden": (
                        f"bijlage '{bijlage.bestandsnaam}' overgenomen van duplicaat "
                        f"'{duplicaat.bestandsnaam}' ({herkomst})"
                    ),
                },
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=bijlage.id,
            actie=AUDIT_BIJLAGE_NAAR_ORIGINEEL,
            correlatie_id=uuid.uuid4(),
            oude_waarde={"samengevoegd_in_id": str(duplicaat.id)},
            nieuwe_waarde={
                "samengevoegd_in_id": str(origineel.id),
                "factuur_bestandsnaam": origineel.bestandsnaam,
                "bijlage_bestandsnaam": bijlage.bestandsnaam,
                "samenvoeg_rol": bijlage.samenvoeg_rol,
                "niet_eenduidig": bijlage.samenvoeg_rol == bijlagen_module.ROL_BIJLAGE_NIET_EENDUIDIG,
                "herkomst": herkomst,
                "via_duplicaat": True,
            },
            administratie_id=origineel.administratie_id,
        )
        verhuisd.append(bijlage.id)
    return verhuisd


def verhuis_na_afvoer(
    *, administratie_id: uuid.UUID, duplicaat_id: uuid.UUID, origineel_id: uuid.UUID | None, actor_id: uuid.UUID
) -> list[uuid.UUID]:
    """Haakje ná `duplicaat_afvoer._voer_af`: eigen transactie; een fout stopt de afvoer niet (die staat al) maar is
    zichtbaar in het log. Origineel buiten de module (None) = niets te verhuizen."""
    from app.db.session import scoped_session

    if origineel_id is None:
        return []
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            duplicaat = session.get(Document, duplicaat_id)
            origineel = session.get(Document, origineel_id)
            if duplicaat is None or origineel is None:
                return []
            return verhuis_bijlagen_naar_origineel(
                session, duplicaat=duplicaat, origineel=origineel, actor_id=actor_id, herkomst="duplicaat-afvoer"
            )
    except Exception:  # noqa: BLE001 — de afvoer staat; de nazorg `bijlagen-nabundelen` vangt een gemiste verhuizing op
        logger.exception("bijlagen verhuizen ná duplicaat-afvoer mislukt (%s → %s)", duplicaat_id, origineel_id)
        return []


# ---- afgewezen factuur zonder tegenhanger: notitie op de bijlage ---------------------------------------------------


def noteer_factuur_afgewezen(
    session: Session, *, bijlage: Document, factuur: Document, afwijs_reden: str | None, actor_id: uuid.UUID
) -> bool:
    """Tijdlijn-notitie op de LOSSE bijlage (blijft open in de werkvoorraad): "factuur ‹naam› uit dezelfde e-mail is
    afgewezen (‹reden›) — bijlage ook afwijzen?". Het controlescherm toont 'm als chip mét link. Idempotent per
    (bijlage, factuur). Nooit automatisch afwijzen. Retourneert True als er geschreven is."""
    bestaand = session.scalars(select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == bijlage.id)).all()
    for g in bestaand:
        d = g.detail or {}
        if d.get(TIJDLIJN_SLEUTEL_AFGEWEZEN) and d.get("factuur_document_id") == str(factuur.id):
            return False
    reden = afwijs_reden or "reden onbekend"
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=bijlage.id,
            van_status=bijlage.status,
            naar_status=bijlage.status,
            actor_id=actor_id,
            detail={
                TIJDLIJN_SLEUTEL_AFGEWEZEN: True,
                "factuur_document_id": str(factuur.id),
                "factuur_bestandsnaam": factuur.bestandsnaam,
                "factuur_status": factuur.status.value,
                "afwijs_reden": reden,
                "reden": (
                    f"factuur '{factuur.bestandsnaam}' uit dezelfde e-mail is afgewezen ({reden}) — "
                    "bijlage ook afwijzen? "
                    "Geen tegenhanger mét hetzelfde factuurnummer gevonden; niets automatisch gedaan."
                ),
            },
        )
    )
    return True


def factuur_afgewezen_uit_tijdlijn(gebeurtenissen: list[DocumentGebeurtenis]) -> dict | None:
    """Voor de detail-DTO: de jongste `bijlage_factuur_afgewezen`-notitie als dict, of None."""
    for g in sorted(gebeurtenissen, key=lambda g: g.tijdstip, reverse=True):
        d = g.detail or {}
        if d.get(TIJDLIJN_SLEUTEL_AFGEWEZEN) and d.get("factuur_document_id"):
            try:
                factuur_id = uuid.UUID(str(d["factuur_document_id"]))
            except ValueError:
                continue
            return {
                "document_id": factuur_id,
                "bestandsnaam": str(d.get("factuur_bestandsnaam") or ""),
                "afwijs_reden": str(d.get("afwijs_reden") or ""),
                "tijdstip": g.tijdstip,
            }
    return None
