"""Bijlagen bij de factuur (Peter 02-10 "één mail = één document"; migratie 0174; BESLISSINGEN "BOEKEN PRETTIG 1 —
BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)") — de ENIGE schrijver van
`document.samenvoeg_rol`.

Een bijlage = een `document`-rij mét status `samengevoegd`, `samengevoegd_in_id` = de factuur en `samenvoeg_rol`
'bijlage' | 'bijlage_niet_eenduidig' (0098-patroon: nooit verwijderen, terugvindbaar onder "Toon afgehandelde
documenten", terugdraaibaar). Geen eigen werkvoorraad-rij (samengevoegd telt in geen enkele teller), nooit
geëxtraheerd, nooit gesplitst. Zichtbaar in het controlescherm náást de factuur (tabblad in het bijlage-paneel, route
`GET …/documenten/{factuur}/bijlagen/{bijlage}/bestand`) en bij boeken mee als extra bijlage
(`extra_bijlagen_voor_boeking` → RLZ `/Uploads` naast het factuurbeeld, Odoo `ir.attachment`). Élke koppeling =
tijdlijnregel op beide kanten + audit `bijlage_gekoppeld` (bron van de dagteller `bijlagen_gebundeld` in de
reconciliatiemail).

Twee ingangen: `registreer_bijlage` (intake: verse bytes uit de mail) en `koppel_document_als_bijlage` (nazorg
`bijlagen-nabundelen`: een al gesplitst document in dezelfde scope). Ongedaan = `maak_bijlage_ongedaan`: terug naar de
status van vóór de koppeling (tijdlijn-detail `vorige_status`; een intake-bijlage gaat naar ontvangen en loopt de
normale keten vanaf daar), nooit verwijderd."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backends.port import ExtraBijlage
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.mime import content_type_voor
from app.documenten.models import Document, DocumentBron, DocumentGebeurtenis, DocumentStatus
from app.documenten.rlz_ids import rlz_bijlage_upload_id
from app.documenten.storage import DocumentOpslag
from app.werkvoorraad import tellers as werkvoorraad_tellers

logger = logging.getLogger(__name__)

ROL_BIJLAGE = "bijlage"
ROL_BIJLAGE_NIET_EENDUIDIG = "bijlage_niet_eenduidig"
ROLLEN = frozenset({ROL_BIJLAGE, ROL_BIJLAGE_NIET_EENDUIDIG})
AUDIT_BIJLAGE_GEKOPPELD = "bijlage_gekoppeld"
AUDIT_BIJLAGE_ONGEDAAN = "bijlage_ongedaan"
#: Sleutel (True) in het tijdlijn-detail van de `samengevoegd`-overgang van een bijlage — onderscheidt de bijlage van
#: de handmatige verzamelbak-samenvoeging, de nabundel-nazorg en het byte-identieke exemplaar.
TIJDLIJN_SLEUTEL = "bijlage_bij_factuur"
HERKOMST_INTAKE = "intake"
HERKOMST_NAZORG = "nazorg bijlagen-nabundelen"


class BijlageFout(Exception):
    """Basis (router: 404/409)."""


class BijlageNietGevonden(BijlageFout):
    pass


class BijlageOngedaanGeweigerd(BijlageFout):
    pass


@dataclass(frozen=True)
class BijlageInfo:
    id: uuid.UUID
    bestandsnaam: str
    content_type: str
    niet_eenduidig: bool
    aangemaakt_op: object  # datetime


def _standaard_opslag() -> DocumentOpslag:
    from app.documenten.service import _standaard_opslag

    return _standaard_opslag()


def _rol(niet_eenduidig: bool) -> str:
    return ROL_BIJLAGE_NIET_EENDUIDIG if niet_eenduidig else ROL_BIJLAGE


def _tijdlijn_notitie(session: Session, document: Document, *, actor_id: uuid.UUID, detail: dict) -> None:
    assert isinstance(detail.get("reden"), str) and detail["reden"].strip()
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
    )


def _audit_gekoppeld(
    session: Session,
    *,
    actor_id: uuid.UUID,
    factuur: Document,
    bijlage: Document,
    herkomst: str,
    niet_eenduidig: bool,
    correlatie_id: uuid.UUID,
) -> None:
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="document",
        record_id=bijlage.id,
        actie=AUDIT_BIJLAGE_GEKOPPELD,
        correlatie_id=correlatie_id,
        nieuwe_waarde={
            "factuur_document_id": str(factuur.id),
            "factuur_bestandsnaam": factuur.bestandsnaam,
            "bijlage_bestandsnaam": bijlage.bestandsnaam,
            "samenvoeg_rol": bijlage.samenvoeg_rol,
            "niet_eenduidig": niet_eenduidig,
            "herkomst": herkomst,
            "intake_bericht_id": str(bijlage.intake_bericht_id) if bijlage.intake_bericht_id else None,
        },
        administratie_id=factuur.administratie_id,
    )


def _reden_koppeling(bijlage_naam: str, factuur_naam: str, *, herkomst: str, niet_eenduidig: bool) -> str:
    kern = f"bijlage bij de factuur ({herkomst}): '{bijlage_naam}' hoort bij '{factuur_naam}' uit dezelfde e-mail"
    if niet_eenduidig:
        kern += (
            " — niet eenduidig (meerdere facturen in de mail, geen treffer op factuur-/werknummer): bij álle facturen"
        )
    return kern


def registreer_bijlage(
    *,
    factuur_document_id: uuid.UUID,
    administratie_id: uuid.UUID | None,
    bestandsnaam: str,
    inhoud: bytes,
    content_type: str | None,
    actor_id: uuid.UUID,
    intake_bericht_id: uuid.UUID | None,
    opslag: DocumentOpslag | None = None,
    niet_eenduidig: bool = False,
    kanaal: DocumentBron = DocumentBron.EMAIL,
) -> uuid.UUID:
    """Intake: verse bijlage-bytes → bijlage-rij van de factuur (in de scope van de factuur: administratie óf
    verzamelbak NULL). Idempotent op (intake-bericht, sha256, factuur) — een herverwerking registreert niets dubbel.
    Retourneert het bijlage-document-id (bestaand of nieuw)."""
    opslag = opslag or _standaard_opslag()
    sha256_hash = hashlib.sha256(inhoud).hexdigest()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        factuur = session.get(Document, factuur_document_id)
        if factuur is None:
            raise BijlageNietGevonden(f"Factuur-document {factuur_document_id} niet gevonden in de scope")
        bestaand = session.scalars(
            select(Document).where(
                Document.samengevoegd_in_id == factuur.id,
                Document.sha256_hash == sha256_hash,
                Document.samenvoeg_rol.is_not(None),
            )
        ).first()
        if bestaand is not None:
            return bestaand.id
        bijlage_id = uuid.uuid4()
        prefix = str(administratie_id) if administratie_id is not None else "niet_toegewezen"
        opslag_pad = f"{prefix}/{bijlage_id}{Path(bestandsnaam).suffix.lower()}"
        opslag.opslaan(pad=opslag_pad, inhoud=inhoud)
        bijlage = Document(
            id=bijlage_id,
            administratie_id=administratie_id,
            bron=kanaal,
            soort=factuur.soort,
            bestandsnaam=bestandsnaam,
            sha256_hash=sha256_hash,
            status=DocumentStatus.ONTVANGEN,
            opslag_pad=opslag_pad,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=factuur.afzender_hint,
            samengevoegd_in_id=factuur.id,
            samenvoeg_rol=_rol(niet_eenduidig),
        )
        session.add(bijlage)
        session.flush()
        werkvoorraad_tellers.verwerk_nieuw_document(session, administratie_id, DocumentStatus.ONTVANGEN)
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=bijlage_id,
                van_status=None,
                naar_status=DocumentStatus.ONTVANGEN,
                actor_id=actor_id,
                detail={"intake": f"bijlage bij factuur {factuur.bestandsnaam}", TIJDLIJN_SLEUTEL: True},
            )
        )
        _koppel_in_sessie(
            session,
            factuur=factuur,
            bijlage=bijlage,
            actor_id=actor_id,
            herkomst=HERKOMST_INTAKE,
            niet_eenduidig=niet_eenduidig,
            vorige_status=DocumentStatus.ONTVANGEN,
        )
    return bijlage_id


def _koppel_in_sessie(
    session: Session,
    *,
    factuur: Document,
    bijlage: Document,
    actor_id: uuid.UUID,
    herkomst: str,
    niet_eenduidig: bool,
    vorige_status: DocumentStatus,
) -> None:
    from app.documenten.service import _schrijf_overgang  # lokaal: geen kring (service importeert bijlagen)

    correlatie_id = uuid.uuid4()
    reden = _reden_koppeling(
        bijlage.bestandsnaam, factuur.bestandsnaam, herkomst=herkomst, niet_eenduidig=niet_eenduidig
    )
    bijlage.samengevoegd_in_id = factuur.id
    bijlage.samenvoeg_rol = _rol(niet_eenduidig)
    _schrijf_overgang(
        session,
        document=bijlage,
        naar=DocumentStatus.SAMENGEVOEGD,
        actor_id=actor_id,
        detail={
            TIJDLIJN_SLEUTEL: True,
            "samengevoegd_in": str(factuur.id),
            "leidend_bestandsnaam": factuur.bestandsnaam,
            "samenvoeg_rol": bijlage.samenvoeg_rol,
            "niet_eenduidig": niet_eenduidig,
            "vorige_status": vorige_status.value,
            "herkomst": herkomst,
            "reden": reden,
        },
    )
    _tijdlijn_notitie(
        session,
        factuur,
        actor_id=actor_id,
        detail={
            TIJDLIJN_SLEUTEL: True,
            "bijlage_document_id": str(bijlage.id),
            "bijlage_bestandsnaam": bijlage.bestandsnaam,
            "niet_eenduidig": niet_eenduidig,
            "herkomst": herkomst,
            "reden": (
                f"bijlage gekoppeld ({herkomst}): '{bijlage.bestandsnaam}' uit dezelfde e-mail"
                + (" — niet eenduidig (ook bij andere facturen uit die mail)" if niet_eenduidig else "")
            ),
        },
    )
    _audit_gekoppeld(
        session,
        actor_id=actor_id,
        factuur=factuur,
        bijlage=bijlage,
        herkomst=herkomst,
        niet_eenduidig=niet_eenduidig,
        correlatie_id=correlatie_id,
    )


def koppel_document_als_bijlage(
    session: Session,
    *,
    factuur: Document,
    bijlage: Document,
    actor_id: uuid.UUID,
    niet_eenduidig: bool,
    herkomst: str = HERKOMST_NAZORG,
) -> None:
    """Nazorg: een bestaand document (zelfde scope als de factuur, open status) wordt de bijlage van de factuur. De
    aanroeper toetst status/scope en houdt de transactie; de statusmachine bewaakt de overgang."""
    if bijlage.administratie_id != factuur.administratie_id:
        raise BijlageFout("bijlage en factuur staan niet in dezelfde administratie — eerst verplaatsen")
    _koppel_in_sessie(
        session,
        factuur=factuur,
        bijlage=bijlage,
        actor_id=actor_id,
        herkomst=herkomst,
        niet_eenduidig=niet_eenduidig,
        vorige_status=bijlage.status,
    )


# ---- lezen ---------------------------------------------------------------------------------------------------------


def lijst_bijlagen_in_sessie(session: Session, document_id: uuid.UUID) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(
                Document.samengevoegd_in_id == document_id,
                Document.status == DocumentStatus.SAMENGEVOEGD,
                Document.samenvoeg_rol.is_not(None),
            )
            .order_by(Document.aangemaakt_op, Document.bestandsnaam)
        )
    )


def _info(d: Document) -> BijlageInfo:
    return BijlageInfo(
        id=d.id,
        bestandsnaam=d.bestandsnaam,
        content_type=content_type_voor(d.bestandsnaam),
        niet_eenduidig=d.samenvoeg_rol == ROL_BIJLAGE_NIET_EENDUIDIG,
        aangemaakt_op=d.aangemaakt_op,
    )


def bijlagen_voor(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID) -> list[BijlageInfo]:
    with scoped_session(administratie_id) as session:
        return [_info(d) for d in lijst_bijlagen_in_sessie(session, document_id)]


def haal_bijlage_op(
    *,
    administratie_id: uuid.UUID | None,
    document_id: uuid.UUID,
    bijlage_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
) -> tuple[bytes, str, str]:
    """(inhoud, bestandsnaam, content_type) van één bijlage van dít document — 404 als de bijlage er niet (meer)
    aan hangt."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id) as session:
        bijlage = session.get(Document, bijlage_id)
        if (
            bijlage is None
            or bijlage.samengevoegd_in_id != document_id
            or bijlage.samenvoeg_rol is None
            or bijlage.status != DocumentStatus.SAMENGEVOEGD
        ):
            raise BijlageNietGevonden(f"Bijlage {bijlage_id} hoort niet bij document {document_id}")
        pad, naam = bijlage.opslag_pad, bijlage.bestandsnaam
    return opslag.lezen(pad=pad), naam, content_type_voor(naam)


def extra_bijlagen_voor_boeking(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, boek_cyclus: int, opslag: DocumentOpslag | None = None
) -> list[ExtraBijlage]:
    """De bijlagen die bij het boeken mee moeten (RLZ `/Uploads` naast het factuurbeeld). Lees-only."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id) as session:
        rijen = [(d.id, d.opslag_pad, d.bestandsnaam) for d in lijst_bijlagen_in_sessie(session, document_id)]
    uit: list[ExtraBijlage] = []
    for bijlage_id, pad, naam in rijen:
        uit.append(
            ExtraBijlage(
                bijlage_document_id=bijlage_id,
                bestandsnaam=naam,
                inhoud=opslag.lezen(pad=pad),
                content_type=content_type_voor(naam),
                upload_id=rlz_bijlage_upload_id(bijlage_id, boek_cyclus),
            )
        )
    return uit


# ---- verhuizen mét de factuur --------------------------------------------------------------------------------------


def verhuis_bijlagen_mee(session: Session, *, factuur: Document, naar_administratie_id: uuid.UUID) -> int:
    """Verzamelbak-toewijzing (`verzamelbak.wijs_toe`): de bijlage-rijen (scope NULL) gaan mee naar de administratie —
    dezelfde UPDATE-vorm als het document zelf (NULL → current scope). Retourneert het aantal."""
    n = 0
    for bijlage in lijst_bijlagen_in_sessie(session, factuur.id):
        if bijlage.administratie_id is None:
            bijlage.administratie_id = naar_administratie_id
            n += 1
    return n


# ---- ongedaan ------------------------------------------------------------------------------------------------------


def maak_bijlage_ongedaan(
    *, administratie_id: uuid.UUID | None, bijlage_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> DocumentStatus:
    """De bijlage wordt weer een eigen document: status terug naar `vorige_status` uit de koppelings-tijdlijnregel
    (intake-bijlage → ontvangen en direct de normale keten via `start_extractie_na_toewijzing`; verzamelbak →
    niet_toegewezen). Alleen zolang de factuur niet geboekt is (anders 409: de bijlage staat al in RLZ)."""
    from app.documenten.service import _schrijf_overgang, start_extractie_na_toewijzing

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bijlage = session.get(Document, bijlage_id)
        if bijlage is None or bijlage.samenvoeg_rol is None or bijlage.status != DocumentStatus.SAMENGEVOEGD:
            raise BijlageNietGevonden(f"{bijlage_id} is geen bijlage (of al ongedaan gemaakt)")
        factuur = session.get(Document, bijlage.samengevoegd_in_id) if bijlage.samengevoegd_in_id else None
        if factuur is not None and factuur.status in (DocumentStatus.GEBOEKT, DocumentStatus.WORDT_GEBOEKT):
            raise BijlageOngedaanGeweigerd("de factuur is al geboekt — de bijlage staat in Reeleezee/Odoo")
        koppeling = next(
            (
                g
                for g in sorted(
                    session.scalars(select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == bijlage.id)),
                    key=lambda g: g.tijdstip,
                    reverse=True,
                )
                if g.detail and g.detail.get(TIJDLIJN_SLEUTEL) and g.naar_status == DocumentStatus.SAMENGEVOEGD
            ),
            None,
        )
        vorige = (koppeling.detail or {}).get("vorige_status") if koppeling else None
        try:
            naar = DocumentStatus(vorige) if vorige else DocumentStatus.ONTVANGEN
        except ValueError:
            naar = DocumentStatus.ONTVANGEN
        if administratie_id is None and naar == DocumentStatus.ONTVANGEN:
            naar = DocumentStatus.NIET_TOEGEWEZEN
        oud = {"samengevoegd_in_id": str(bijlage.samengevoegd_in_id), "samenvoeg_rol": bijlage.samenvoeg_rol}
        bijlage.samengevoegd_in_id = None
        bijlage.samenvoeg_rol = None
        _schrijf_overgang(
            session,
            document=bijlage,
            naar=naar,
            actor_id=actor_id,
            detail={"reden": f"bijlage ongedaan gemaakt: {reden}", "was_bijlage_van": oud["samengevoegd_in_id"]},
        )
        if factuur is not None:
            _tijdlijn_notitie(
                session,
                factuur,
                actor_id=actor_id,
                detail={
                    "reden": f"bijlage '{bijlage.bestandsnaam}' losgekoppeld: {reden}",
                    "bijlage_document_id": str(bijlage.id),
                },
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=bijlage.id,
            actie=AUDIT_BIJLAGE_ONGEDAAN,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"status": naar.value, "reden": reden},
            administratie_id=administratie_id,
        )
        eind = naar
    if eind == DocumentStatus.ONTVANGEN and administratie_id is not None:
        eind = start_extractie_na_toewijzing(
            administratie_id=administratie_id, document_id=bijlage_id, actor_id=actor_id
        )
    return eind
