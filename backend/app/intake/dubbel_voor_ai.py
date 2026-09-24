"""Byte-identieke dubbelencheck VÓÓR de AI-stap (BUG Peter 24-09: "waarschijnlijk vist die er nog wel redelijk wat
dubbele uit" — de herstelrun van 23-09 las het kempengroep-postvak vanaf 01-09 inclusief mail die eerder al via de
forward binnenkwam; élk exemplaar ging opnieuw door de splitsings-AI).

Regel: in het intake-pad (én in de heraanbieding) wordt de sha256 van een PDF vóór de splitsingsdetectie kantoorbreed
vergeleken met álle bestaande documenten (verzamelbak + élke actieve administratie — per scope, want `document` staat
onder RLS; nooit een SECURITY-DEFINER-doorbraak). Bestaat hetzelfde bestand al (niet door een mens verwijderd), dan:
- hetzelfde intake-bericht (herverwerking van een afgebroken run / twee identieke bijlagen in één mail) → géén nieuwe
  rij, de bestaande rij is de uitkomst — zelfde idempotentie als `registreer_niet_toegewezen_document`, nu zonder AI;
- een ánder bericht/kanaal → het exemplaar wordt wél geregistreerd (niets verdwijnt stil, bewaarplicht) en volgt
  direct de bestaande duplicatenregels: origineel in een administratie → toegewezen aan die administratie en als
  duplicaat AFGEVOERD (`afgevoerd_duplicaat` mét kruisverwijzing — categorie (a) sha256, gouden-set-casus g; zichtbaar
  onder "Toon afgehandelde documenten → duplicaat van ‹document›"); origineel zelf nog in de verzamelbak → de huls
  (`samengevoegd` mét `samengevoegd_in_id`; de bak-rij van het origineel toont het samengevoegde exemplaar).
Géén AI-call, tijdlijn "dubbel vóór extractie herkend (bespaard)" op beide kanten, audit `ai_dubbel_voor_extractie`
(bron van de dagteller `ai_bespaard_dubbel` in de reconciliatiemail). Referentie-dubbelen (zelfde factuur, andere
bytes) kunnen pas ná extractie — die blijven bij de bestaande duplicaten-motor.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus

logger = logging.getLogger(__name__)

AUDIT_ACTIE = "ai_dubbel_voor_extractie"
TIJDLIJN_SLEUTEL = "ai_bespaard_dubbel"
REDEN_PREFIX = "dubbel_voor_ai"

#: Een huls (samengevoegd/afgevoerd) of een door een mens verwijderd exemplaar is nooit het origineel; een gesplitste
#: bron-PDF wél (de splitsing is al gedaan — een tweede exemplaar hoeft niet nóg een keer door de AI).
_GEEN_ORIGINEEL = frozenset(
    {DocumentStatus.VERWIJDERD, DocumentStatus.SAMENGEVOEGD, DocumentStatus.AFGEVOERD_DUPLICAAT}
)


@dataclass(frozen=True)
class Treffer:
    document_id: uuid.UUID
    administratie_id: uuid.UUID | None
    status: DocumentStatus
    bestandsnaam: str
    aangemaakt_op: datetime
    intake_bericht_id: uuid.UUID | None


def sha256_van(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


def _actieve_administratie_ids() -> list[uuid.UUID]:
    with scoped_session(None) as session:
        return list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))).all())


def _treffers_in_scope(
    administratie_id: uuid.UUID | None, sha256_hash: str, uitgezonderd_document_id: uuid.UUID | None
) -> list[Treffer]:
    with scoped_session(administratie_id) as session:
        q = select(Document).where(Document.sha256_hash == sha256_hash).order_by(Document.aangemaakt_op)
        if administratie_id is None:
            q = q.where(Document.administratie_id.is_(None))
        else:
            q = q.where(Document.administratie_id == administratie_id)
        return [
            Treffer(
                document_id=d.id,
                administratie_id=d.administratie_id,
                status=d.status,
                bestandsnaam=d.bestandsnaam,
                aangemaakt_op=d.aangemaakt_op,
                intake_bericht_id=d.intake_bericht_id,
            )
            for d in session.scalars(q)
            if d.id != uitgezonderd_document_id and d.status not in _GEEN_ORIGINEEL
        ]


def zoek_byte_identiek(sha256_hash: str, *, uitgezonderd_document_id: uuid.UUID | None = None) -> Treffer | None:
    """Het oudste échte exemplaar mét dezelfde bytes, kantoorbreed (verzamelbak + élke actieve administratie in haar
    eigen RLS-scope). None = onbekend bestand → het normale pad."""
    treffers = _treffers_in_scope(None, sha256_hash, uitgezonderd_document_id)
    for administratie_id in _actieve_administratie_ids():
        treffers.extend(_treffers_in_scope(administratie_id, sha256_hash, uitgezonderd_document_id))
    if not treffers:
        return None
    return min(treffers, key=lambda t: (t.aangemaakt_op, str(t.document_id)))


def _tijdlijn_notitie(session, document: Document, detail: dict, *, actor_id: uuid.UUID) -> None:
    """Zelf-overgang (status ongewijzigd) — bewust niet via `_schrijf_overgang`."""
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail={**detail, TIJDLIJN_SLEUTEL: True},
        )
    )


def _audit(*, actor_id: uuid.UUID, administratie_id: uuid.UUID | None, exemplaar_id: uuid.UUID, waarde: dict) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=exemplaar_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=waarde,
            administratie_id=administratie_id,
        )


def registreer_zelfde_bericht(
    *, treffer: Treffer, bestandsnaam: str, sha256_hash: str, actor_id: uuid.UUID, bron: str
) -> None:
    """Herverwerking / tweede identieke bijlage in hetzelfde bericht: geen nieuwe rij, wél het spoor (tijdlijn op
    het origineel + audit) — de AI-call die hier vroeger nóg een keer liep, is bespaard."""
    with scoped_session(treffer.administratie_id, actor_id=actor_id) as session:
        origineel = session.get(Document, treffer.document_id)
        if origineel is not None:
            _tijdlijn_notitie(
                session,
                origineel,
                {
                    "reden": (
                        f"dubbel vóór extractie herkend (bespaard): '{bestandsnaam}' is byte-identiek aan dit "
                        "document en kwam uit hetzelfde bericht — niet opnieuw verwerkt, geen AI-call"
                    ),
                    "dubbel_bron": bron,
                },
                actor_id=actor_id,
            )
    _audit(
        actor_id=actor_id,
        administratie_id=treffer.administratie_id,
        exemplaar_id=treffer.document_id,
        waarde={
            "sha256": sha256_hash,
            "bestandsnaam": bestandsnaam,
            "origineel_document_id": str(treffer.document_id),
            "origineel_administratie_id": str(treffer.administratie_id) if treffer.administratie_id else None,
            "exemplaar_document_id": None,
            "zelfde_bericht": True,
            "bron": bron,
        },
    )


UITKOMST_SAMENGEVOEGD = "samengevoegd"
UITKOMST_AFGEVOERD = "afgevoerd_duplicaat"


def handel_exemplaar_af(
    *, exemplaar_id: uuid.UUID, treffer: Treffer, actor_id: uuid.UUID, bron: str, herkomst: str
) -> str:
    """Het exemplaar (een verzamelbak-rij, status niet_toegewezen) volgt de BESTAANDE duplicatenregels, zonder AI:
    - origineel in een administratie → het exemplaar wordt aan die administratie toegewezen (niet_toegewezen → ontvangen,
      zelfde patroon als een toewijzing) en direct als duplicaat AFGEVOERD (`afgevoerd_duplicaat` mét kruisverwijzing via
      `duplicaat_afvoer._voer_af` — categorie (a) sha256, gouden-set-casus g "PDF twee keer uit twee mails");
    - origineel zelf nog in de verzamelbak → het exemplaar wordt de huls (`samengevoegd` mét `samengevoegd_in_id`; de
      bak-rij van het origineel toont 'm als samengevoegd exemplaar) — een afvoer heeft daar geen administratie voor.
    Tijdlijn op beide kanten + audit `ai_dubbel_voor_extractie`; nooit verwijderen, terugdraaibaar (heropenen resp.
    samenvoegen-ongedaan). Retourneert de eindstatus van het exemplaar."""
    from app.documenten import duplicaat_afvoer
    from app.documenten.models import Boekvoorstel
    from app.documenten.service import _schrijf_overgang  # lokaal: houdt de importgraaf intake → documenten klein

    scope = treffer.administratie_id
    waar = f"administratie {scope}" if scope else "de verzamelbak"
    with scoped_session(scope, actor_id=actor_id) as session:
        exemplaar = session.get(Document, exemplaar_id)
        origineel = session.get(Document, treffer.document_id)
        if exemplaar is None or origineel is None or exemplaar.status != DocumentStatus.NIET_TOEGEWEZEN:
            raise RuntimeError(
                f"dubbel afhandelen kan niet: exemplaar {exemplaar_id} / origineel {treffer.document_id} niet (meer) in de "
                "verwachte stand"
            )
        origineel_naam = origineel.bestandsnaam
        origineel_status = origineel.status
        voorstel = session.get(Boekvoorstel, origineel.id) if scope is not None else None
        referentie = (voorstel.referentie if voorstel is not None and voorstel.referentie else None) or origineel_naam
        if scope is None:
            exemplaar.samengevoegd_in_id = origineel.id
            _schrijf_overgang(
                session,
                document=exemplaar,
                naar=DocumentStatus.SAMENGEVOEGD,
                actor_id=actor_id,
                detail={
                    "reden": (
                        f"dubbel vóór extractie herkend (bespaard): byte-identiek aan '{origineel_naam}' in {waar} "
                        f"({herkomst}) — samengevoegd als exemplaar, geen AI-call"
                    ),
                    "samengevoegd_in": str(origineel.id),
                    "leidend_bestandsnaam": origineel_naam,
                    "dubbel_bron": bron,
                    TIJDLIJN_SLEUTEL: True,
                },
            )
            eind = UITKOMST_SAMENGEVOEGD
        else:
            exemplaar.administratie_id = scope
            _schrijf_overgang(
                session,
                document=exemplaar,
                naar=DocumentStatus.ONTVANGEN,
                actor_id=actor_id,
                detail={
                    "reden": (
                        f"dubbel vóór extractie herkend (bespaard): byte-identiek aan '{origineel_naam}' in {waar} "
                        f"({herkomst}) — toegewezen aan die administratie en direct afgevoerd als duplicaat, geen AI-call"
                    ),
                    "toegewezen_aan_administratie": str(scope),
                    "vanuit": "verzamelbak",
                    "dubbel_bron": bron,
                    TIJDLIJN_SLEUTEL: True,
                },
            )
            # Zonder AI tóch een eerlijke extractie-uitkomst op de tijdlijn (ontvangen → bezig → te_controleren mét
            # `ai_extractie_overgeslagen: dubbel_voor_ai`) — precies de stand van waaruit de bestaande afvoer-route werkt en
            # waarnaar "Heropenen" terugzet; geen statusmachine-uitbreiding nodig.
            _schrijf_overgang(
                session,
                document=exemplaar,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=actor_id,
                detail={"reden": "extractie gestart (dubbel vóór extractie herkend — geen AI-call)"},
            )
            _schrijf_overgang(
                session,
                document=exemplaar,
                naar=DocumentStatus.TE_CONTROLEREN,
                actor_id=actor_id,
                detail={
                    "ai_extractie_overgeslagen": "dubbel_voor_ai",
                    "reden": "extractie overgeslagen: dubbel vóór extractie herkend (bespaard) — wordt afgevoerd als duplicaat",
                },
            )
            eind = UITKOMST_AFGEVOERD
        _tijdlijn_notitie(
            session,
            origineel,
            {
                "reden": (
                    f"dubbel vóór extractie herkend (bespaard): '{exemplaar.bestandsnaam}' ({herkomst}) is "
                    f"byte-identiek aan dit document — {'als duplicaat afgevoerd' if scope else 'als exemplaar samengevoegd'}, "
                    "geen AI-call"
                ),
                "exemplaar_document_id": str(exemplaar.id),
                "bestandsnaam": exemplaar.bestandsnaam,
                "dubbel_bron": bron,
            },
            actor_id=actor_id,
        )
    if scope is not None:
        origineel_obj = duplicaat_afvoer.Origineel(
            bron="geboekt" if origineel_status == DocumentStatus.GEBOEKT else "werkvoorraad",
            referentie=referentie,
            document_id=treffer.document_id,
            bestandsnaam=origineel_naam,
            aangemaakt_op=treffer.aangemaakt_op,
            status=origineel_status.value,
        )
        # De afvoer zelf is een systeemhandeling (zoals `verwerk_na_signaal`): systeem-actor, toewijzing = eigenaar of leeg.
        duplicaat_afvoer._voer_af(
            administratie_id=scope,
            document_id=exemplaar_id,
            actor_id=SYSTEEM_ACTOR_ID,
            origineel=origineel_obj,
            automatisch=True,
        )
        duplicaat_afvoer._audit(
            administratie_id=scope,
            document_id=exemplaar_id,
            actie="duplicaat_afgevoerd",
            waarde={
                "reden": origineel_obj.reden(),
                "origineel": duplicaat_afvoer._origineel_json(origineel_obj),
                "automatisch": True,
                "dubbel_voor_ai": True,
            },
        )
    _audit(
        actor_id=actor_id,
        administratie_id=scope,
        exemplaar_id=exemplaar_id,
        waarde={
            "sha256": None,
            "bestandsnaam": treffer.bestandsnaam,
            "origineel_document_id": str(treffer.document_id),
            "origineel_administratie_id": str(scope) if scope else None,
            "exemplaar_document_id": str(exemplaar_id),
            "exemplaar_status": eind,
            "zelfde_bericht": False,
            "bron": bron,
        },
    )
    return eind


def herkomst_tekst(*, afzender: str | None, kanaal: str | None) -> str:
    delen = [d for d in (f"via {kanaal}" if kanaal else None, f"van {afzender}" if afzender else None) if d]
    return " ".join(delen) if delen else "onbekende herkomst"
