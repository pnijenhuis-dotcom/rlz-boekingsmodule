"""Kassarapport automatisch typeren (Peter 19-09, screenshot Reconciliatie Van Boxtel: "dit zijn meldingen waar ik dus
niks mee doe. Als de module weet dat het verkoopboekingen zijn, wijzig het dan automatisch").

Regel: een document dat als INKOOPFACTUUR binnenkomt (upload, bulk, verzamelbak) of in de werkvoorraad staat, maar
waarop een bron-parser DETERMINISTISCH aanslaat (ProfX Journaal/Margerapport op de PDF-tekstlaag, zonnestudio-dagstaat/
-kascheck en pilates-export op het raster — `app/omzet/bronnen/herkenning.py`, géén AI, geen AVG-gate) krijgt DIRECT
soort `kassarapport` en gaat de omzet-verwerking in. Eenduidig = het systeem doet het; alleen het zachte signaal "alle
regels op een omzetrekening" (geen parser) blijft een melding mét knop. Kernprincipe 7 (2)+(3): signalering zonder
handeling is niet af, een mens laten klikken op een vaststaande actie is een testfase-drempel.

Terugweg + leren: "Tóch inkoopfactuur" (verplichte reden) zet het document terug in de inkoopstroom en schrijft een
observatie `typering_correctie` (audit, append-only) op de sleutel administratie × bron × afzender. Ná
`CORRECTIE_DREMPEL` (2) correcties binnen `CORRECTIE_VENSTER_DAGEN` valt het systeem voor die sleutel terug op MELDEN
i.p.v. doen (zelfde recency-gedachte als het boekingsgeheugen: de laatste mens-beslissingen winnen). Geen LLM in deze
beslissing. Geen stille no-op: élke overgeslagen kandidaat draagt een reden en telt in de dagteller
`kassarapport_autotype` (verwacht/gedaan/overgeslagen) van de reconciliatiemail.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from app.db.audit import record_audit_event
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentSoort
from app.documenten.storage import DocumentOpslag, standaard_opslag

logger = logging.getLogger(__name__)

#: Audit-acties (append-only spoor; bron van de dagteller `kassarapport_autotype`).
AUDIT_GEWIJZIGD = "soort_automatisch_gewijzigd"  # per document: inkoopfactuur → kassarapport, automatisch
AUDIT_OVERGESLAGEN = "kassarapport_autotype_overgeslagen"  # per document: parser-treffer, bewust niet gedaan + reden
AUDIT_CORRECTIE = "typering_correctie"  # per document: mens zei "Tóch inkoopfactuur" (observatie voor het leren)
AUDIT_RUN = "kassarapport_autotype_run"  # per administratie per run: verwacht/gedaan/overgeslagen
#: Sleutel van de automatisering in de reconciliatie-tellers.
AUTOMATISERING = "kassarapport_autotype"
#: Ná zoveel "Tóch inkoopfactuur"-correcties op dezelfde sleutel valt het systeem terug op melden.
CORRECTIE_DREMPEL = 2
#: Correcties ouder dan dit tellen niet meer (recency: oude beslissingen wegen niet eeuwig).
CORRECTIE_VENSTER_DAGEN = 180
#: Reden-codes voor overgeslagen kandidaten (leesbaar in teksten.py + teller-categorieën).
REDEN_CORRECTIES = "correcties"
REDEN_STATUS = "status"
REDEN_FOUT = "fout"
#: Detail-sleutel in de tijdlijn (document_gebeurtenis.detail) én de chip-bron voor het omzet-controlescherm.
TIJDLIJN_SLEUTEL = "soort_automatisch_gewijzigd"

_LEESBARE_BRON = {
    "profx_journaal": "ProfX-journaal",
    "profx_margerapport": "ProfX-margerapport",
    "zonnestudio_dagstaat": "zonnestudio-dagstaat",
    "zonnestudio_kascheck": "zonnestudio-kascheck",
    "pilates_betalingsexport": "pilates-betalingsexport",
}


def bron_leesbaar(bron: str) -> str:
    return _LEESBARE_BRON.get(bron, bron.replace("_", " "))


def herken(bestandsnaam: str, inhoud: bytes) -> str | None:
    """Welke deterministische omzetbron is dit bestand? PDF → tekstlaag (ProfX), spreadsheet → raster; None = geen
    parser-treffer (dan de gewone inkoop-/AI-route). Nooit een exception richting de aanroeper."""
    from app.omzet.bronnen import herken_bron, herkenning, is_spreadsheet

    try:
        if is_spreadsheet(bestandsnaam):
            return herken_bron(bestandsnaam, inhoud)
        if bestandsnaam.lower().endswith(".pdf"):
            return herkenning.herken_pdf(inhoud)
    except Exception:  # noqa: BLE001 — onleesbaar bestand = geen bron
        return None
    return None


def normaliseer_afzender(afzender: str | None) -> str:
    """Sleuteldeel van de leer-sleutel: e-mailadres kleine letters; upload zonder afzender = ''."""
    return (afzender or "").strip().casefold()


def tel_correcties(
    session: Session, *, administratie_id: uuid.UUID, bron: str, afzender: str | None, nu: datetime | None = None
) -> int:
    """Aantal `typering_correctie`-observaties op (administratie, bron, afzender) binnen het venster."""
    sinds = (nu or datetime.now(UTC)) - timedelta(days=CORRECTIE_VENSTER_DAGEN)
    return int(
        session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.actie == AUDIT_CORRECTIE,
                AuditEvent.administratie_id == administratie_id,
                AuditEvent.tijdstip >= sinds,
                cast(AuditEvent.nieuwe_waarde["bron"].astext, String) == bron,
                func.coalesce(cast(AuditEvent.nieuwe_waarde["afzender"].astext, String), "")
                == normaliseer_afzender(afzender),
            )
        )
        or 0
    )


@dataclass(frozen=True)
class Besluit:
    bron: str | None  # parser-treffer (None = geen kandidaat)
    doen: bool  # True = automatisch typeren
    reden: str | None = None  # REDEN_* als niet gedaan
    correcties: int = 0

    @property
    def kenmerken(self) -> str:
        return f"{bron_leesbaar(self.bron or '')} herkend"


def beslis(
    session: Session, *, administratie_id: uuid.UUID, bestandsnaam: str, inhoud: bytes, afzender: str | None
) -> Besluit:
    """Parser-treffer + leer-sleutel → doen of melden. Puur deterministisch."""
    bron = herken(bestandsnaam, inhoud)
    if bron is None:
        return Besluit(bron=None, doen=False)
    n = tel_correcties(session, administratie_id=administratie_id, bron=bron, afzender=afzender)
    if n >= CORRECTIE_DREMPEL:
        return Besluit(bron=bron, doen=False, reden=REDEN_CORRECTIES, correcties=n)
    return Besluit(bron=bron, doen=True, correcties=n)


def tijdlijn_detail(besluit: Besluit, *, van: str = DocumentSoort.INKOOPFACTUUR.value) -> dict:
    """Detail voor de tijdlijnregel "type automatisch gewijzigd: inkoopfactuur → kassarapport (ProfX-journaal
    herkend)"."""
    return {
        "reden": f"type automatisch gewijzigd: {van} → {DocumentSoort.KASSARAPPORT.value} ({besluit.kenmerken})",
        TIJDLIJN_SLEUTEL: {"van": van, "naar": DocumentSoort.KASSARAPPORT.value, "bron": besluit.bron},
    }


def audit_gewijzigd(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    besluit: Besluit,
    bestandsnaam: str,
    afzender: str | None,
    ingang: str,
    van: str = DocumentSoort.INKOOPFACTUUR.value,
) -> None:
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="document",
        record_id=document_id,
        actie=AUDIT_GEWIJZIGD,
        correlatie_id=uuid.uuid4(),
        oude_waarde={"soort": van},
        nieuwe_waarde={
            "soort": DocumentSoort.KASSARAPPORT.value,
            "bron": besluit.bron,
            "bestandsnaam": bestandsnaam,
            "afzender": normaliseer_afzender(afzender) or None,
            "ingang": ingang,
        },
        administratie_id=administratie_id,
    )


def audit_overgeslagen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    besluit: Besluit,
    bestandsnaam: str,
    afzender: str | None,
    ingang: str,
    detail: str | None = None,
) -> None:
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="document",
        record_id=document_id,
        actie=AUDIT_OVERGESLAGEN,
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "bron": besluit.bron,
            "reden": besluit.reden,
            "correcties": besluit.correcties,
            "bestandsnaam": bestandsnaam,
            "afzender": normaliseer_afzender(afzender) or None,
            "ingang": ingang,
            "detail": detail,
        },
        administratie_id=administratie_id,
    )


def is_automatisch_getypeerd(session: Session, *, document_id: uuid.UUID) -> dict | None:
    """De laatste tijdlijnregel mét `soort_automatisch_gewijzigd` (chip "automatisch getypeerd") — None = mens koos
    de soort zelf, of het document is intussen teruggezet ("Tóch inkoopfactuur" schrijft een gewone soort-wissel)."""
    from app.documenten.models import DocumentGebeurtenis

    rijen = session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id)
        .order_by(DocumentGebeurtenis.tijdstip.desc(), DocumentGebeurtenis.id.desc())
    ).all()
    for g in rijen:
        d = g.detail or {}
        if TIJDLIJN_SLEUTEL in d:
            m = d[TIJDLIJN_SLEUTEL]
            return dict(m) if isinstance(m, dict) else {"bron": None}
        if d.get("documentsoort_gewijzigd"):
            # Een latere (mens-)soortwissel maakt de automatische typering ongedaan.
            return None
    return None


# --- werkvoorraad-motor (dagelijkse reconciliatie + nazorg-CLI) --------------------------------------------------


@dataclass(frozen=True)
class DocumentUitkomst:
    document_id: uuid.UUID
    bestandsnaam: str
    bron: str
    uitkomst: str  # 'gedaan' | 'overgeslagen' | 'dry_run'
    reden: str | None = None
    correcties: int = 0


@dataclass
class RunUitkomst:
    administratie_id: uuid.UUID
    dry_run: bool
    documenten: list[DocumentUitkomst] = field(default_factory=list)

    @property
    def verwacht(self) -> int:
        return len(self.documenten)

    @property
    def gedaan(self) -> int:
        return sum(1 for d in self.documenten if d.uitkomst == "gedaan")

    @property
    def zou_doen(self) -> int:
        return sum(1 for d in self.documenten if d.uitkomst == "dry_run")

    @property
    def overgeslagen(self) -> dict[str, int]:
        uit: dict[str, int] = {}
        for d in self.documenten:
            if d.uitkomst == "overgeslagen":
                uit[d.reden or REDEN_FOUT] = uit.get(d.reden or REDEN_FOUT, 0) + 1
        return uit


def verwerk_werkvoorraad(
    administratie_id: uuid.UUID,
    *,
    dry_run: bool = False,
    opslag: DocumentOpslag | None = None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
) -> RunUitkomst:
    """Alle INKOOPFACTUUR-documenten in de werkvoorraad van deze administratie mét een deterministische parser-treffer
    (signaal ≠ 'omzetrekeningen') automatisch omzetten naar kassarapport via de bestaande soort-wissel
    (`documenten/soort.py`: terug naar ONTVANGEN, extractie opnieuw via het omzetpad — deterministisch, geen AI).
    Per document: gedaan / overgeslagen mét reden (correcties ≥ drempel, status laat de wissel niet toe, fout).
    `dry_run` schrijft niets (0 writes) en meldt wat er zou gebeuren. Niet-dry-run schrijft één audit-rij
    `kassarapport_autotype_run` per administratie mét de tellers (bron van de dagteller)."""
    from app.documenten import soort as soort_service
    from app.omzet import inkoopstroom

    lezer = opslag or standaard_opslag()
    uit = RunUitkomst(administratie_id=administratie_id, dry_run=dry_run)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        treffers = inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom(
            session, administratie_id=administratie_id, opslag=lezer
        )
        kandidaten = [t for t in treffers if t.signaal != "omzetrekeningen"]
        afzenders = {
            d.id: d.afzender_hint
            for d in session.scalars(select(Document).where(Document.id.in_([t.document_id for t in kandidaten]))).all()
        }
        besluiten = {
            t.document_id: Besluit(
                bron=t.signaal,
                doen=(
                    n := tel_correcties(
                        session,
                        administratie_id=administratie_id,
                        bron=t.signaal,
                        afzender=afzenders.get(t.document_id),
                    )
                )
                < CORRECTIE_DREMPEL,
                reden=None if n < CORRECTIE_DREMPEL else REDEN_CORRECTIES,
                correcties=n,
            )
            for t in kandidaten
        }

    for t in kandidaten:
        b = besluiten[t.document_id]
        afzender = afzenders.get(t.document_id)
        if not b.doen:
            uit.documenten.append(
                DocumentUitkomst(t.document_id, t.bestandsnaam, t.signaal, "overgeslagen", b.reden, b.correcties)
            )
            if not dry_run:
                _schrijf_overgeslagen_veilig(
                    administratie_id=administratie_id,
                    document_id=t.document_id,
                    actor_id=actor_id,
                    besluit=b,
                    bestandsnaam=t.bestandsnaam,
                    afzender=afzender,
                    ingang="werkvoorraad",
                )
            continue
        if dry_run:
            uit.documenten.append(
                DocumentUitkomst(t.document_id, t.bestandsnaam, t.signaal, "dry_run", None, b.correcties)
            )
            continue
        try:
            soort_service.wijzig_documentsoort(
                administratie_id=administratie_id,
                document_id=t.document_id,
                soort=DocumentSoort.KASSARAPPORT,
                actor_id=actor_id,
                opslag=lezer,
                automatisch=b,
                ingang="werkvoorraad",
            )
            uit.documenten.append(
                DocumentUitkomst(t.document_id, t.bestandsnaam, t.signaal, "gedaan", None, b.correcties)
            )
        except soort_service.SoortWisselNietToegestaan as exc:
            over = Besluit(bron=b.bron, doen=False, reden=REDEN_STATUS, correcties=b.correcties)
            uit.documenten.append(
                DocumentUitkomst(t.document_id, t.bestandsnaam, t.signaal, "overgeslagen", REDEN_STATUS, b.correcties)
            )
            _schrijf_overgeslagen_veilig(
                administratie_id=administratie_id,
                document_id=t.document_id,
                actor_id=actor_id,
                besluit=over,
                bestandsnaam=t.bestandsnaam,
                afzender=afzender,
                ingang="werkvoorraad",
                detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — één kapot document stopt de rest niet; zichtbaar als overgeslagen
            logger.exception("autotype mislukt voor document %s", t.document_id)
            over = Besluit(bron=b.bron, doen=False, reden=REDEN_FOUT, correcties=b.correcties)
            uit.documenten.append(
                DocumentUitkomst(t.document_id, t.bestandsnaam, t.signaal, "overgeslagen", REDEN_FOUT, b.correcties)
            )
            _schrijf_overgeslagen_veilig(
                administratie_id=administratie_id,
                document_id=t.document_id,
                actor_id=actor_id,
                besluit=over,
                bestandsnaam=t.bestandsnaam,
                afzender=afzender,
                ingang="werkvoorraad",
                detail=str(exc),
            )

    if not dry_run and uit.documenten:
        try:
            with scoped_session(administratie_id, actor_id=actor_id) as session:
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="document",
                    record_id=administratie_id,
                    actie=AUDIT_RUN,
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "verwacht": uit.verwacht,
                        "gedaan": uit.gedaan,
                        "overgeslagen": uit.overgeslagen,
                        "bronnen": sorted({d.bron for d in uit.documenten}),
                    },
                    administratie_id=administratie_id,
                )
        except Exception:  # noqa: BLE001 — de teller mag de run nooit laten omvallen
            logger.exception("audit %s mislukt voor %s", AUDIT_RUN, administratie_id)
    return uit


def _schrijf_overgeslagen_veilig(**kw) -> None:  # noqa: ANN003
    administratie_id = kw["administratie_id"]
    actor_id = kw["actor_id"]
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            audit_overgeslagen(session, **kw)
    except Exception:  # noqa: BLE001
        logger.exception("audit %s mislukt voor %s", AUDIT_OVERGESLAGEN, kw.get("document_id"))


# --- terugweg: "Tóch inkoopfactuur" ----------------------------------------------------------------------------

MIN_REDEN_LENGTE = 5


class TochInkoopfactuurFout(Exception):
    """Reden ontbreekt/te kort, document geen kassarapport, of de status laat de wissel niet toe."""


@dataclass(frozen=True)
class TochInkoopfactuurResultaat:
    document_id: uuid.UUID
    status: str
    correcties: int
    bron: str | None
    #: True zodra deze correctie de drempel raakt: vanaf nu meldt het systeem voor deze sleutel i.p.v. doen.
    valt_terug_op_melden: bool


def toch_inkoopfactuur(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    opslag: DocumentOpslag | None = None,
) -> TochInkoopfactuurResultaat:
    """Omzet-controlescherm: het kassarapport is tóch een inkoopfactuur → terug naar de inkoopstroom via de bestaande
    soort-wissel (ONTVANGEN, extractie opnieuw via het inkooppad) + observatie `typering_correctie` op
    administratie × bron × afzender (alleen als er een parser-treffer is — anders valt er niets te leren)."""
    from app.documenten import soort as soort_service

    if len((reden or "").strip()) < MIN_REDEN_LENGTE:
        raise TochInkoopfactuurFout(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")
    reden = reden.strip()
    lezer = opslag or standaard_opslag()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise TochInkoopfactuurFout("Document niet gevonden")
        if document.soort != DocumentSoort.KASSARAPPORT.value:
            raise TochInkoopfactuurFout("Alleen een kassarapport kan terug naar inkoopfactuur")
        bestandsnaam, afzender, pad = document.bestandsnaam, document.afzender_hint, document.opslag_pad
    try:
        bron = herken(bestandsnaam, lezer.lezen(pad=pad))
    except Exception:  # noqa: BLE001
        bron = None
    try:
        r = soort_service.wijzig_documentsoort(
            administratie_id=administratie_id,
            document_id=document_id,
            soort=DocumentSoort.INKOOPFACTUUR,
            actor_id=actor_id,
            opslag=lezer,
            reden=reden,
        )
    except soort_service.SoortWisselNietToegestaan as exc:
        raise TochInkoopfactuurFout(str(exc)) from exc
    correcties = 0
    if bron is not None:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie=AUDIT_CORRECTIE,
                correlatie_id=uuid.uuid4(),
                oude_waarde={"soort": DocumentSoort.KASSARAPPORT.value},
                nieuwe_waarde={
                    "soort": DocumentSoort.INKOOPFACTUUR.value,
                    "bron": bron,
                    "afzender": normaliseer_afzender(afzender) or None,
                    "bestandsnaam": bestandsnaam,
                    "reden": reden,
                },
                administratie_id=administratie_id,
            )
            session.flush()
            correcties = tel_correcties(session, administratie_id=administratie_id, bron=bron, afzender=afzender)
    status = r.status.value if hasattr(r.status, "value") else str(r.status)
    return TochInkoopfactuurResultaat(
        document_id=document_id,
        status=status,
        correcties=correcties,
        bron=bron,
        valt_terug_op_melden=correcties >= CORRECTIE_DREMPEL,
    )
