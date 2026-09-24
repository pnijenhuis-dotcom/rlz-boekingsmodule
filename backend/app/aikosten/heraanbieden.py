"""AI-heraanbieding ná een limietverhoging of een nieuwe maand (BUG Peter 24-09: "dat AI limiet voor alle nieuwe
facturen is nog steeds niet opgelost" — ná de verhoging van € 100 → € 150 op 23-09 bleven 202 verzamelbak-rijen
`ai_limiet_bereikt` en documenten mét tijdlijn `ai_extractie_overgeslagen: ai_limiet_bereikt` liggen; niets bood ze
opnieuw aan, `extractie-heraanbieden` pakt alleen `ai_extractie_fout`).

Kernprincipe 7.6 (geen stille no-op): één motor die AUTOMATISCH draait — aan het einde van élke intake-job-run (beide
postvakken, elke 10 min) én als dagelijkse stap — zolang de kostenpoort open is (`geblokkeerd=false`, live verbruik <
limiet), in volgorde oud → nieuw, en zichtbaar stopt zodra de poort weer dichtgaat. Twee populaties:
(a) verzamelbak-PDF's waarvan de jongste intake-reden `ai_limiet_bereikt` is — die lopen opnieuw door de NORMALE
    intake-keten (`app/intake/herlezen.py`: splitsingsdetectie → toewijzing op tenaamstelling → extractie ná
    toewijzing, mét hetzelfde intake-bericht/afzender-hint; het toewijzings-geheugen leert bewust niet — geen
    mens-besluit); vóór de AI-stap eerst de byte-identieke dubbelencheck (`app/intake/dubbel_voor_ai.py`);
(b) documenten mét administratie (te_controleren/handmatig_afmaken, PDF) waarvan de LAATSTE extractie-uitkomst
    `ai_extractie_overgeslagen == ai_limiet_bereikt` is — die lopen door de bestaande opnieuw-route
    (`herextraheer_document`: AVG-gate van de administratie, klein/groot-routing via de wachtrij, template-terugval).
Élke heraanbieding = tijdlijnregel + audit `ai_heraanbieding` (oude reden → uitkomst); élke run één audit
`ai_heraanbieding_run` (bezig → klaar) mét tellers en uitkomst per rij — bron van de dagteller `ai_heraanbiedingen`
(verwacht/gedaan/overgeslagen) in de reconciliatiemail én van de uitkomstlijst achter de knop "Opnieuw verwerken (N)"
op de verzamelbak. Volumerem `ai_heraanbieden_max_per_run` (300; de rest = overgeslagen `volumerem` → LET-OP) en
tijdbudget `ai_heraanbieden_tijdbudget_s` (de intake-job heeft 900 s; de rest = `tijdbudget`, zacht — de volgende run
over 10 min pakt 'm op). Geen tweede extractiepad, geen limiet in code.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.aikosten import service as aikosten_service
from app.aikosten.service import AiKostenLimietBereikt
from app.beheer import service as beheer_service
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.storage import DocumentOpslag
from app.intake import dubbel_voor_ai
from app.intake.models import IntakeSplitsing, IntakeSplitsingStatus

logger = logging.getLogger(__name__)

LABEL = "ai_heraanbieding"
AUDIT_DOCUMENT = "ai_heraanbieding"
AUDIT_RUN = "ai_heraanbieding_run"
AUDIT_AANGEVRAAGD = "ai_heraanbieding_aangevraagd"
REDEN_LIMIET = "ai_limiet_bereikt"

BRON_INTAKE_JOB = "intake_job"
BRON_DAGELIJKS = "dagelijks"
BRON_KNOP = "knop"
BRON_CLI = "cli"

# Overslaan-redenen (categorieën van app/reconciliatie/automatiseringen.py: kostengrens/volumerem/avg_gate/api_key =
# harde voorwaarde → LET-OP; tijdbudget/mens_bezig = zacht, zichtbaar).
OVER_KOSTENGRENS = "kostengrens"
OVER_VOLUMEREM = "volumerem"
OVER_TIJDBUDGET = "tijdbudget"
OVER_AVG_GATE = "avg_gate"
OVER_API_KEY = "api_key"
OVER_MENS_BEZIG = "mens_bezig"

UITKOMST_TOEGEWEZEN = "toegewezen"
UITKOMST_VERZAMELBAK = "verzamelbak"  # blijft in de bak mét een andere reden (tenaamstelling niet eenduidig, …)
UITKOMST_SPLITSING = "splitsingsvoorstel"
UITKOMST_DUBBEL = "dubbel"
UITKOMST_GEEXTRAHEERD = "geextraheerd"
UITKOMST_WACHTRIJ = "naar_wachtrij"
UITKOMST_MISLUKT = "mislukt"
UITKOMST_WACHT_OP_BUDGET = "wacht_op_budget"
UITKOMST_OVERGESLAGEN = "overgeslagen"

SOORT_VERZAMELBAK = "verzamelbak"
SOORT_DOCUMENT = "document"

_PDF = ".pdf"
_HERAANBIEDBARE_STATUSSEN = (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN)
_AI_UITKOMST_KEYS = ("veldvoorstel", "ai_extractie_fout", "ai_extractie_overgeslagen", "ai_extractie_onvolledig")
#: Een run-audit `bezig` ouder dan dit geldt als gestrand (job gekilld) — de stand-route toont dan niet eeuwig "bezig".
BEZIG_MAX = timedelta(minutes=20)


@dataclass(frozen=True)
class Kandidaat:
    soort: str  # verzamelbak | document
    document_id: uuid.UUID
    administratie_id: uuid.UUID | None
    bestandsnaam: str
    aangemaakt_op: datetime
    oude_reden: str = REDEN_LIMIET


@dataclass
class RijUitkomst:
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    uitkomst: str
    detail: str | None = None
    administratie_id: uuid.UUID | None = None

    def als_dict(self) -> dict:
        return {
            "document_id": str(self.document_id),
            "bestandsnaam": self.bestandsnaam,
            "soort": self.soort,
            "uitkomst": self.uitkomst,
            "detail": self.detail,
            "administratie_id": str(self.administratie_id) if self.administratie_id else None,
        }


@dataclass
class RunResultaat:
    run_id: uuid.UUID
    bron: str
    gestart_op: datetime
    dry_run: bool
    kandidaten_verzamelbak: int = 0
    kandidaten_documenten: int = 0
    geblokkeerd: bool = False
    uitkomsten: list[RijUitkomst] = field(default_factory=list)
    overgeslagen: dict[str, int] = field(default_factory=dict)
    gestopt_reden: str | None = None
    klaar_op: datetime | None = None

    @property
    def kandidaten(self) -> int:
        return self.kandidaten_verzamelbak + self.kandidaten_documenten

    @property
    def gedaan(self) -> int:
        return sum(1 for u in self.uitkomsten if u.uitkomst not in (UITKOMST_WACHT_OP_BUDGET, UITKOMST_OVERGESLAGEN))

    @property
    def rest(self) -> int:
        """Wat ná deze run nog wacht (overgeslagen + wacht op budget) — de banner telt dit mee."""
        return sum(self.overgeslagen.values())

    def tel_over(self, reden: str, n: int = 1) -> None:
        self.overgeslagen[reden] = self.overgeslagen.get(reden, 0) + n

    def tellers(self) -> dict[str, int]:
        uit: dict[str, int] = {}
        for u in self.uitkomsten:
            uit[u.uitkomst] = uit.get(u.uitkomst, 0) + 1
        return uit

    def als_dict(self) -> dict:
        return {
            "run_id": str(self.run_id),
            "bron": self.bron,
            "dry_run": self.dry_run,
            "gestart_op": self.gestart_op.isoformat(),
            "klaar_op": self.klaar_op.isoformat() if self.klaar_op else None,
            "geblokkeerd": self.geblokkeerd,
            "kandidaten_verzamelbak": self.kandidaten_verzamelbak,
            "kandidaten_documenten": self.kandidaten_documenten,
            "kandidaten": self.kandidaten,
            "gedaan": self.gedaan,
            "rest": self.rest,
            "overgeslagen": dict(self.overgeslagen),
            "tellers": self.tellers(),
            "gestopt_reden": self.gestopt_reden,
            "uitkomsten": [u.als_dict() for u in self.uitkomsten],
        }


# --- selectie ---------------------------------------------------------------------------------------------------


def vind_kandidaten_verzamelbak() -> list[Kandidaat]:
    """(a) Verzamelbak-PDF's (administratie NULL, niet_toegewezen) waarvan de jongste intake-reden `ai_limiet_bereikt`
    is en die geen open splitsingsvoorstel dragen — oud → nieuw."""
    from app.intake.verzamelbak import _jongste_intake_redenen  # lokaal: houdt de importgraaf klein

    with scoped_session(None) as session:
        documenten = session.scalars(
            select(Document)
            .where(Document.administratie_id.is_(None), Document.status == DocumentStatus.NIET_TOEGEWEZEN)
            .order_by(Document.aangemaakt_op.asc(), Document.id)
        ).all()
        pdfs = [d for d in documenten if d.bestandsnaam.lower().endswith(_PDF)]
        if not pdfs:
            return []
        redenen = _jongste_intake_redenen(session, [d.id for d in pdfs])
        open_splitsingen = set(
            session.scalars(
                select(IntakeSplitsing.bron_document_id).where(
                    IntakeSplitsing.bron_document_id.in_([d.id for d in pdfs]),
                    IntakeSplitsing.status == IntakeSplitsingStatus.VOORGESTELD.value,
                )
            )
        )
        return [
            Kandidaat(
                soort=SOORT_VERZAMELBAK,
                document_id=d.id,
                administratie_id=None,
                bestandsnaam=d.bestandsnaam,
                aangemaakt_op=d.aangemaakt_op,
            )
            for d in pdfs
            if (redenen.get(d.id) or "").strip() == REDEN_LIMIET and d.id not in open_splitsingen
        ]


def _actieve_administraties() -> list[uuid.UUID]:
    with scoped_session(None) as session:
        return list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))).all())


def _laatste_uitkomst_is_limiet(session, document_id: uuid.UUID) -> tuple[bool, bool]:
    """(jongste extractie-uitkomst == limiet, mens raakte het document daarná aan). Een document dat ná de limiet-uitkomst
    alsnog een voorstel kreeg (handmatige "opnieuw"-klik) blijft met rust; een document waar een mens ná de limiet iets
    aan deed (niet-systeem-actor in de tijdlijn) wordt overgeslagen mét reden `mens_bezig` — nooit een voorstel over een
    mens heen schrijven."""
    gebeurtenissen = session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id)
        .order_by(DocumentGebeurtenis.tijdstip.desc(), DocumentGebeurtenis.id.desc())
    ).all()
    mens_erna = False
    for g in gebeurtenissen:
        d = g.detail or {}
        if any(k in d for k in _AI_UITKOMST_KEYS):
            return d.get("ai_extractie_overgeslagen") == REDEN_LIMIET, mens_erna
        if g.actor_id != SYSTEEM_ACTOR_ID:
            mens_erna = True
    return False, mens_erna


def vind_kandidaten_documenten(
    administratie_ids: list[uuid.UUID] | None = None,
) -> tuple[list[Kandidaat], list[Kandidaat]]:
    """(b) Documenten mét administratie (te_controleren/handmatig_afmaken, PDF) waarvan de laatste extractie-uitkomst
    `ai_extractie_overgeslagen: ai_limiet_bereikt` is — per administratie in eigen RLS-scope. Retourneert
    (kandidaten, mens_bezig)."""
    kandidaten: list[Kandidaat] = []
    mens_bezig: list[Kandidaat] = []
    for administratie_id in administratie_ids if administratie_ids is not None else _actieve_administraties():
        with scoped_session(administratie_id) as session:
            ids = session.scalars(
                select(DocumentGebeurtenis.document_id)
                .join(Document, Document.id == DocumentGebeurtenis.document_id)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.status.in_(_HERAANBIEDBARE_STATUSSEN),
                    DocumentGebeurtenis.detail["ai_extractie_overgeslagen"].astext == REDEN_LIMIET,
                )
                .distinct()
            ).all()
            for document_id in ids:
                document = session.get(Document, document_id)
                if document is None or not document.bestandsnaam.lower().endswith(_PDF):
                    continue
                is_limiet, mens = _laatste_uitkomst_is_limiet(session, document_id)
                if not is_limiet:
                    continue
                k = Kandidaat(
                    soort=SOORT_DOCUMENT,
                    document_id=document.id,
                    administratie_id=administratie_id,
                    bestandsnaam=document.bestandsnaam,
                    aangemaakt_op=document.aangemaakt_op,
                )
                (mens_bezig if mens else kandidaten).append(k)
    return kandidaten, mens_bezig


def tel_kandidaten() -> tuple[int, int]:
    """(N(a), N(b)) — de dry-run-telling / banner-telling."""
    b, _mens = vind_kandidaten_documenten()
    return len(vind_kandidaten_verzamelbak()), len(b)


# --- uitvoering -------------------------------------------------------------------------------------------------


def _tijdlijn(session, document: Document, reden: str, extra: dict | None = None, *, actor_id: uuid.UUID) -> None:
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            # `notitie`: geen nieuwe intake-uitkomst — de verzamelbak-reden blijft staan (verzamelbak._jongste_intake_redenen).
            detail={"reden": reden, LABEL: True, "notitie": True, **(extra or {})},
        )
    )


def _audit_document(*, run_id: uuid.UUID, kandidaat: Kandidaat, uitkomst: RijUitkomst, actor_id: uuid.UUID) -> None:
    scope = uitkomst.administratie_id or kandidaat.administratie_id
    with scoped_session(scope, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=kandidaat.document_id,
            actie=AUDIT_DOCUMENT,
            correlatie_id=run_id,
            oude_waarde={"reden": kandidaat.oude_reden, "soort": kandidaat.soort},
            nieuwe_waarde={
                "uitkomst": uitkomst.uitkomst,
                "detail": (uitkomst.detail or "")[:500],
                "run_id": str(run_id),
            },
            administratie_id=scope,
        )


def _audit_run(resultaat: RunResultaat, *, status: str, actor_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=resultaat.run_id,
            actie=AUDIT_RUN,
            correlatie_id=resultaat.run_id,
            nieuwe_waarde={"status": status, **resultaat.als_dict()},
            administratie_id=None,
        )


def _heraanbied_verzamelbak(
    kandidaat: Kandidaat, *, opslag: DocumentOpslag, actor_id: uuid.UUID, bron: str
) -> RijUitkomst:
    from app.intake import herlezen

    with scoped_session(None) as session:
        document = session.get(Document, kandidaat.document_id)
        if (
            document is None
            or document.status != DocumentStatus.NIET_TOEGEWEZEN
            or document.administratie_id is not None
        ):
            return RijUitkomst(
                kandidaat.document_id,
                kandidaat.bestandsnaam,
                kandidaat.soort,
                UITKOMST_OVERGESLAGEN,
                "intussen verwerkt (niet meer in de verzamelbak)",
            )
        sha = document.sha256_hash
    # Dubbelencheck vóór de AI-stap (ook hier): een byte-identiek origineel elders = huls, geen AI-call.
    treffer = dubbel_voor_ai.zoek_byte_identiek(sha, uitgezonderd_document_id=kandidaat.document_id)
    if treffer is not None:
        eind = dubbel_voor_ai.handel_exemplaar_af(
            exemplaar_id=kandidaat.document_id,
            treffer=treffer,
            actor_id=actor_id,
            bron=LABEL,
            herkomst="heraanbieding ná AI-limiet",
        )
        waar = f"administratie {treffer.administratie_id}" if treffer.administratie_id else "de verzamelbak"
        wat = "afgevoerd als duplicaat" if eind == dubbel_voor_ai.UITKOMST_AFGEVOERD else "samengevoegd als exemplaar"
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_DUBBEL,
            f"byte-identiek aan '{treffer.bestandsnaam}' in {waar} — {wat}, geen AI-call",
            administratie_id=treffer.administratie_id,
        )
    with scoped_session(None, actor_id=actor_id) as session:
        document = session.get(Document, kandidaat.document_id)
        assert document is not None
        _tijdlijn(
            session,
            document,
            f"opnieuw aangeboden ná AI-limiet ({bron}) — splitsingsdetectie en toewijzing lopen opnieuw",
            actor_id=actor_id,
        )
    telling = herlezen.HerleesTelling()
    herlezen._herlees_een(
        herlezen.HerleesKandidaat(
            document_id=kandidaat.document_id,
            bestandsnaam=kandidaat.bestandsnaam,
            reden=REDEN_LIMIET,
            al_herlezen=False,
        ),
        opslag=opslag,
        telling=telling,
        label=LABEL,
        ai_bron=LABEL,
    )
    detail = telling.details[-1] if telling.details else None
    if telling.mislukt:
        uitkomst = UITKOMST_MISLUKT
    elif telling.toegewezen:
        uitkomst = UITKOMST_TOEGEWEZEN
    elif telling.splitsingsvoorstel:
        uitkomst = UITKOMST_SPLITSING
    else:
        uitkomst = UITKOMST_VERZAMELBAK
    administratie_id = telling.laatste_toewijzing_administratie_id if uitkomst == UITKOMST_TOEGEWEZEN else None
    return RijUitkomst(
        kandidaat.document_id, kandidaat.bestandsnaam, kandidaat.soort, uitkomst, detail, administratie_id
    )


def _heraanbied_document(
    kandidaat: Kandidaat, *, opslag: DocumentOpslag, actor_id: uuid.UUID, bron: str
) -> RijUitkomst:
    from app.documenten.service import (
        DocumentNietGevonden,
        HerextractieNietToegestaan,
        herextraheer_document,
    )

    assert kandidaat.administratie_id is not None
    with scoped_session(kandidaat.administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, kandidaat.document_id)
        if document is None or document.status not in _HERAANBIEDBARE_STATUSSEN:
            return RijUitkomst(
                kandidaat.document_id,
                kandidaat.bestandsnaam,
                kandidaat.soort,
                UITKOMST_OVERGESLAGEN,
                "intussen verwerkt (status veranderd)",
                kandidaat.administratie_id,
            )
        _tijdlijn(
            session, document, f"opnieuw aangeboden ná AI-limiet ({bron}) — extractie loopt opnieuw", actor_id=actor_id
        )
    try:
        eind = herextraheer_document(
            administratie_id=kandidaat.administratie_id,
            document_id=kandidaat.document_id,
            actor_id=actor_id,
            opslag=opslag,
        )
    except (DocumentNietGevonden, HerextractieNietToegestaan) as exc:
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_OVERGESLAGEN,
            str(exc),
            kandidaat.administratie_id,
        )
    # Sinds blok 1c (08-09) gaat élke AI-extractie via de wachtrij (cloud: job `rlz-extractie-wachtrij`, ≤ 10 min;
    # suite: direct). Staat het document ná de aanroep nog op wachtrij → 'naar_wachtrij' (de worker doet de rest en
    # schrijft zijn eigen uitkomst); anders lezen we de verse uitkomst.
    with scoped_session(kandidaat.administratie_id) as session:
        document = session.get(Document, kandidaat.document_id)
        status_nu = document.status if document is not None else eind
        laatste = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == kandidaat.document_id)
            .order_by(DocumentGebeurtenis.tijdstip.desc(), DocumentGebeurtenis.id.desc())
        ).all()
        uitkomst_detail = (
            next((g.detail for g in laatste if any(k in (g.detail or {}) for k in _AI_UITKOMST_KEYS)), None) or {}
        )
    if status_nu in (DocumentStatus.EXTRACTIE_WACHTRIJ, DocumentStatus.EXTRACTIE_BEZIG):
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_WACHTRIJ,
            "extractie via de wachtrij (achtergrond-job)",
            kandidaat.administratie_id,
        )
    if uitkomst_detail.get("ai_extractie_overgeslagen") == REDEN_LIMIET:
        raise AiKostenLimietBereikt("AI-maandlimiet bereikt tijdens de heraanbieding")
    if "veldvoorstel" in uitkomst_detail:
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_GEEXTRAHEERD,
            "voorstel opgesteld — ter controle",
            kandidaat.administratie_id,
        )
    if "ai_extractie_fout" in uitkomst_detail:
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_MISLUKT,
            f"AI-extractie mislukt: {str(uitkomst_detail['ai_extractie_fout'])[:200]}",
            kandidaat.administratie_id,
        )
    if "ai_extractie_overgeslagen" in uitkomst_detail:
        return RijUitkomst(
            kandidaat.document_id,
            kandidaat.bestandsnaam,
            kandidaat.soort,
            UITKOMST_OVERGESLAGEN,
            f"extractie overgeslagen: {uitkomst_detail['ai_extractie_overgeslagen']}",
            kandidaat.administratie_id,
        )
    return RijUitkomst(
        kandidaat.document_id,
        kandidaat.bestandsnaam,
        kandidaat.soort,
        UITKOMST_GEEXTRAHEERD,
        "extractie afgerond (regelset niet compleet — handmatig afmaken)"
        if "ai_extractie_onvolledig" in uitkomst_detail
        else "extractie afgerond",
        kandidaat.administratie_id,
    )


def draai(
    *,
    bron: str,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    dry_run: bool = False,
    max_per_run: int | None = None,
    tijdbudget_s: int | None = None,
    deadline: datetime | None = None,
    opslag: DocumentOpslag | None = None,
    administratie_ids: list[uuid.UUID] | None = None,
) -> RunResultaat:
    """De motor. Poort dicht (`geblokkeerd`) = álle kandidaten overgeslagen `kostengrens` mét run-audit — géén exception,
    nooit stil. `dry_run` telt en lijst, schrijft niets (ook geen audit)."""
    from app.documenten.service import _standaard_opslag

    nu = datetime.now(UTC)
    resultaat = RunResultaat(run_id=uuid.uuid4(), bron=bron, gestart_op=nu, dry_run=dry_run)
    max_per_run = settings.ai_heraanbieden_max_per_run if max_per_run is None else max_per_run
    if deadline is None:
        deadline = nu + timedelta(
            seconds=settings.ai_heraanbieden_tijdbudget_s if tijdbudget_s is None else tijdbudget_s
        )

    verzamelbak = vind_kandidaten_verzamelbak()
    documenten, mens_bezig = vind_kandidaten_documenten(administratie_ids)
    resultaat.kandidaten_verzamelbak = len(verzamelbak)
    resultaat.kandidaten_documenten = len(documenten) + len(mens_bezig)
    for k in mens_bezig:
        resultaat.tel_over(OVER_MENS_BEZIG)
        resultaat.uitkomsten.append(
            RijUitkomst(
                k.document_id,
                k.bestandsnaam,
                k.soort,
                UITKOMST_OVERGESLAGEN,
                "een mens werkt aan dit document sinds de limiet — niet overschreven",
                k.administratie_id,
            )
        )
    kandidaten = sorted(verzamelbak + documenten, key=lambda k: (k.aangemaakt_op, str(k.document_id)))

    status = aikosten_service.haal_status_op()
    resultaat.geblokkeerd = status.geblokkeerd
    if dry_run:
        for k in kandidaten:
            resultaat.uitkomsten.append(
                RijUitkomst(
                    k.document_id,
                    k.bestandsnaam,
                    k.soort,
                    "kandidaat",
                    f"oude reden {k.oude_reden}",
                    k.administratie_id,
                )
            )
        resultaat.klaar_op = datetime.now(UTC)
        return resultaat

    _audit_run(resultaat, status="bezig", actor_id=actor_id)
    try:
        if status.geblokkeerd:
            resultaat.tel_over(OVER_KOSTENGRENS, len(kandidaten))
            resultaat.gestopt_reden = (
                f"AI-maandlimiet bereikt (€ {status.verbruik_eur:.2f} van € {status.limiet_eur:.2f} in {status.maand:%Y-%m}) — "
                f"{len(kandidaten)} document(en) wachten op AI-budget (verhoog de limiet op Instellingen of wacht op de nieuwe maand)"
            )
            return resultaat
        intake_gate_dicht = not beheer_service.intake_ai_effectief_ingeschakeld()
        api_key_leeg = not settings.anthropic_api_key
        opslag = opslag or _standaard_opslag()
        te_doen = kandidaten[:max_per_run]
        if len(kandidaten) > max_per_run:
            resultaat.tel_over(OVER_VOLUMEREM, len(kandidaten) - max_per_run)
        for i, k in enumerate(te_doen):
            if datetime.now(UTC) >= deadline:
                resultaat.tel_over(OVER_TIJDBUDGET, len(te_doen) - i)
                resultaat.gestopt_reden = (
                    f"tijdbudget van deze run op — {len(te_doen) - i} document(en) volgen in de volgende run"
                )
                break
            if k.soort == SOORT_VERZAMELBAK and (intake_gate_dicht or api_key_leeg):
                reden = OVER_AVG_GATE if intake_gate_dicht else OVER_API_KEY
                resultaat.tel_over(reden)
                resultaat.uitkomsten.append(
                    RijUitkomst(
                        k.document_id,
                        k.bestandsnaam,
                        k.soort,
                        UITKOMST_OVERGESLAGEN,
                        f"intake-AI niet beschikbaar ({reden})",
                        None,
                    )
                )
                continue
            try:
                if k.soort == SOORT_VERZAMELBAK:
                    uitkomst = _heraanbied_verzamelbak(k, opslag=opslag, actor_id=actor_id, bron=bron)
                else:
                    uitkomst = _heraanbied_document(k, opslag=opslag, actor_id=actor_id, bron=bron)
            except AiKostenLimietBereikt as exc:
                # De poort ging tijdens de run dicht: dít document én de rest wachten zichtbaar op budget — geen fout.
                rest = len(te_doen) - i
                resultaat.tel_over(OVER_KOSTENGRENS, rest)
                resultaat.gestopt_reden = f"AI-maandlimiet bereikt tijdens de run bij '{k.bestandsnaam}' — {rest} document(en) wachten op AI-budget: {exc}"
                uitkomst = RijUitkomst(
                    k.document_id,
                    k.bestandsnaam,
                    k.soort,
                    UITKOMST_WACHT_OP_BUDGET,
                    "wacht op AI-budget (maandlimiet bereikt)",
                    k.administratie_id,
                )
                with scoped_session(k.administratie_id, actor_id=actor_id) as session:
                    document = session.get(Document, k.document_id)
                    if document is not None:
                        _tijdlijn(
                            session,
                            document,
                            "wacht op AI-budget — de maandlimiet is (weer) bereikt; wordt automatisch opnieuw aangeboden zodra er budget is",
                            actor_id=actor_id,
                        )
                resultaat.uitkomsten.append(uitkomst)
                _audit_document(run_id=resultaat.run_id, kandidaat=k, uitkomst=uitkomst, actor_id=actor_id)
                break
            except Exception as exc:  # noqa: BLE001 — één kapotte rij stopt de stapel niet; wél zichtbaar
                logger.exception("AI-heraanbieding mislukt voor %s", k.document_id)
                uitkomst = RijUitkomst(
                    k.document_id,
                    k.bestandsnaam,
                    k.soort,
                    UITKOMST_MISLUKT,
                    f"onverwachte fout: {type(exc).__name__}: {str(exc)[:200]}",
                    k.administratie_id,
                )
            if uitkomst.uitkomst == UITKOMST_OVERGESLAGEN:
                resultaat.tel_over(OVER_MENS_BEZIG if "mens" in (uitkomst.detail or "") else "overgeslagen")
            resultaat.uitkomsten.append(uitkomst)
            _audit_document(run_id=resultaat.run_id, kandidaat=k, uitkomst=uitkomst, actor_id=actor_id)
        return resultaat
    finally:
        resultaat.klaar_op = datetime.now(UTC)
        _audit_run(resultaat, status="klaar", actor_id=actor_id)
        logger.info(
            "AI-heraanbieding (%s): %s kandidaten, %s gedaan, overgeslagen %s%s",
            bron,
            resultaat.kandidaten,
            resultaat.gedaan,
            resultaat.overgeslagen,
            f" — {resultaat.gestopt_reden}" if resultaat.gestopt_reden else "",
        )


# --- knop / dagelijkse stap: delegeren aan de intake-job (die draagt de API-key) ---------------------------------


@dataclass(frozen=True)
class AanvraagResultaat:
    voertuig: str
    kandidaten_verzamelbak: int
    kandidaten_documenten: int


def vraag_aan(*, actor_id: uuid.UUID, bron: str) -> AanvraagResultaat:
    """Start de heraanbieding buiten de request/het reconciliatieproces: de intake-job van het facturen-postvak (die
    ná zijn postvak-pas altijd de heraanbieding draait en als enige de Anthropic-key draagt) — in de cloud via de
    Cloud Run v2 `:run`, lokaal een daemon-thread. De service leest zelf nooit IMAP en doet zelf geen AI-werk van
    minutenlang. Audit `ai_heraanbieding_aangevraagd` (wie/bron/voertuig)."""
    from app.documenten.betaalstatus import KANAAL_FACTUREN
    from app.intake import nu_verwerken

    a, b = tel_kandidaten()
    start = nu_verwerken.start(kanaal=KANAAL_FACTUREN, actor_id=actor_id)
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=uuid.uuid4(),
            actie=AUDIT_AANGEVRAAGD,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "bron": bron,
                "voertuig": start.voertuig,
                "kandidaten_verzamelbak": a,
                "kandidaten_documenten": b,
            },
            administratie_id=None,
        )
    return AanvraagResultaat(voertuig=start.voertuig, kandidaten_verzamelbak=a, kandidaten_documenten=b)


def laatste_run(*, nu: datetime | None = None) -> dict | None:
    """De jongste run-audit (bezig of klaar) als dict — bron van de stand-route en de banner-telling."""
    nu = nu or datetime.now(UTC)
    with scoped_session(None) as session:
        rijen = session.scalars(
            select(AuditEvent).where(AuditEvent.actie == AUDIT_RUN).order_by(AuditEvent.tijdstip.desc()).limit(2)
        ).all()
    if not rijen:
        return None
    jongste = rijen[0]
    waarde = dict(jongste.nieuwe_waarde or {})
    waarde["tijdstip"] = jongste.tijdstip.isoformat()
    if waarde.get("status") == "bezig":
        tijdstip = jongste.tijdstip if jongste.tijdstip.tzinfo else jongste.tijdstip.replace(tzinfo=UTC)
        waarde["bezig"] = (nu - tijdstip) <= BEZIG_MAX
        # De vorige afgeronde run (zelfde run_id = klaar-rij hoort erbij; anders de run ervoor) voor de uitkomstlijst.
        vorige = rijen[1] if len(rijen) > 1 else None
        if vorige is not None and (vorige.nieuwe_waarde or {}).get("status") == "klaar":
            waarde["vorige"] = {**(vorige.nieuwe_waarde or {}), "tijdstip": vorige.tijdstip.isoformat()}
    else:
        waarde["bezig"] = False
    return waarde


def aangevraagd_recent(*, nu: datetime | None = None, binnen: timedelta = timedelta(minutes=10)) -> bool:
    nu = nu or datetime.now(UTC)
    with scoped_session(None) as session:
        rij = session.scalars(
            select(AuditEvent).where(AuditEvent.actie == AUDIT_AANGEVRAAGD).order_by(AuditEvent.tijdstip.desc())
        ).first()
    if rij is None:
        return False
    tijdstip = rij.tijdstip if rij.tijdstip.tzinfo else rij.tijdstip.replace(tzinfo=UTC)
    return (nu - tijdstip) <= binnen


def stand() -> dict:
    """Voor `GET /verzamelbak/ai-heraanbieden/stand` en de banner: live N(a), de jongste run (bezig/klaar mét uitkomsten)
    en 'wachten' = N(a) + wat de jongste run als rest achterliet (N(b) is per administratie en wordt niet live geteld —
    de motor telt 'm bij élke run)."""
    laatste = laatste_run()
    a = len(vind_kandidaten_verzamelbak())
    rest_b = 0
    if laatste is not None:
        bron_rest = laatste if laatste.get("status") == "klaar" else laatste.get("vorige") or {}
        rest_b = int(bron_rest.get("rest") or 0) if isinstance(bron_rest, dict) else 0
    bezig = bool(laatste and laatste.get("bezig"))
    if not bezig and aangevraagd_recent():
        # Aangevraagd (knop/dagelijks) maar de job is nog niet aan de heraanbieding toe — toon "bezig" i.p.v. niets.
        laatste_klaar_op = (laatste or {}).get("klaar_op")
        bezig = (
            laatste is None
            or laatste.get("status") != "klaar"
            or not laatste_klaar_op
            or _ouder_dan_aanvraag(laatste_klaar_op)
        )
    return {
        "bezig": bezig,
        "kandidaten_verzamelbak": a,
        "wachten": a + rest_b,
        "geblokkeerd": aikosten_service.haal_status_op().geblokkeerd,
        "laatste_run": laatste,
    }


def _ouder_dan_aanvraag(klaar_op: str) -> bool:
    with scoped_session(None) as session:
        rij = session.scalars(
            select(AuditEvent).where(AuditEvent.actie == AUDIT_AANGEVRAAGD).order_by(AuditEvent.tijdstip.desc())
        ).first()
    if rij is None:
        return False
    try:
        klaar = datetime.fromisoformat(klaar_op)
    except ValueError:
        return False
    tijdstip = rij.tijdstip if rij.tijdstip.tzinfo else rij.tijdstip.replace(tzinfo=UTC)
    if klaar.tzinfo is None:
        klaar = klaar.replace(tzinfo=UTC)
    return klaar < tijdstip
