"""Vastly-PDF-tweelingen achteraf bundelen (blok 1 bundelrun 24-09, casus Vastly-batch 23-09: per factuur een UBL
`factuur-XXX-2026-NNNN-ubl.xml` (correct → verkoopfactuur, VASTLY-VERKOOP) én een PDF `factuur-XXX-2026-NNNN.pdf`
die NIET gebundeld werd en als losse INKOOPFACTUUR `te_controleren` in de werkvoorraad stond — Rubicon 10, Elissen 4,
ARVUM 3, Meyer 3, Shuto 3 = 23). De intake-bundeling kende het `-ubl`-suffix niet (`app/intake/bundeling.py`, sinds
24-09 wél).

Eén kandidaten-motor voor drie afnemers (één bron, nooit drie definities):
- nazorg-CLI `vastly-pdf-tweelingen-herstel [--dry-run] [--uitvoeren] [--administratie <uuid|naamdeel>]` (dry-run =
  default: tonen zonder schrijven; `--uitvoeren` = échte run, systeem-actor);
- reconciliatieblok `documenten`: bevinding `ubl_pdf_ongebundeld` (in `meten`) per eenduidig paar — lees-only;
- actie "Bundelen" op die rij (`POST /reconciliatie/documenten/{document_id}/bundelen`, mens-actor).

Kandidaat = in één administratie (eigen `scoped_session(aid)` — RLS) een losse INKOOPFACTUUR-PDF in een open status
(te_controleren / handmatig_afmaken / klaar_om_te_boeken, bron e-mail, geen beeld, geen samenvoeg-verwijzing) én een
VERKOOPFACTUUR-UBL-document (.xml, niet terminaal) uit hetzelfde intake-bericht — of, zonder bericht, van dezelfde
kalenderdag — waarvan (a) de GENORMALISEERDE naamstam gelijk is (`bundeling.genormaliseerde_stam`: `-ubl`/`_ubl`/
`-xml`/`_xml` weg) óf (b) het UBL-factuurnummer (`cbc:ID`, ≥ 4 tekens) in de PDF-bestandsnaam of -tekstlaag staat.
Precies één UBL per PDF én precies één PDF per UBL; anders `twijfel` (zichtbaar overgeslagen mét reden, nooit raden).

Herstel = het UBL-document blijft HET document (het is al verkoopfactuur, mogelijk al geboekt): de PDF wordt zijn beeld
(`bron_opslag_pad`/`bron_bestandsnaam`/`bron_content_type` — `documenten/beeld.bepaal_beeld` toont 'm), het PDF-document
gaat terminaal naar `samengevoegd` mét `samengevoegd_in_id` (nooit verwijderd; `_schrijf_overgang` = statusmachine +
tijdlijn + audit), tijdlijnregel op beide kanten, audit `gebundeld_achteraf` op beide rijen. Is het UBL-document al
GEBOEKT (`verkoop_boeking` status geboekt, casus RUB-2026-0031), dan gaat de PDF óók als RLZ-bijlage mee via
`app/rlz/bijlage.zorg_voor_bijlage` op `SalesInvoices/{verkoop_rlz_id}` (idempotent op bestandsnaam; een bijlage-fout is
een zichtbare regel — de lokale bundeling staat dan al, niets half). Odoo-administratie: bijlage overgeslagen mét reden.
Idempotent: een tweede run vindt 0 kandidaten (de PDF is `samengevoegd`, het UBL-document draagt een beeld).
"""

from __future__ import annotations

import argparse
import base64
import logging
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentBron, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.documenten.service import _schrijf_overgang, _standaard_opslag
from app.documenten.storage import DocumentOpslag
from app.intake.bundeling import (
    REDEN_FACTUURNUMMER,
    REDEN_NAAMSTAM,
    genormaliseerde_stam,
    pdf_draagt_factuurnummer,
    pdf_tekstlaag_genormaliseerd,
    ubl_factuurnummer,
)

logger = logging.getLogger(__name__)

COMMANDO = "vastly-pdf-tweelingen-herstel"
SOORT_ONGEBUNDELD = "ubl_pdf_ongebundeld"
AUDIT_GEBUNDELD_ACHTERAF = "gebundeld_achteraf"
#: Sleutel (True) in het tijdlijn-detail van de `samengevoegd`-overgang van de PDF — onderscheidt deze bundeling
#: van de handmatige verzamelbak-samenvoeging en de nabundel-nazorg.
TIJDLIJN_SLEUTEL = "gebundeld_achteraf"
_UPLOAD_NAMESPACE = uuid.UUID("7c1a9d3e-24a0-4b2f-9b8e-0b6c2f1e5a44")

#: Open statussen waarin een losse PDF nog een tweeling kan zijn (zelfde set als de opdracht: geen geboekt/ter
#: accordering — dáár heeft een mens al geoordeeld of staat de boeking al).
OPEN_STATUSSEN = frozenset(
    {DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN, DocumentStatus.KLAAR_OM_TE_BOEKEN}
)
#: UBL-documenten die niet meer als tegenhanger tellen (terminaal weg).
_UBL_UITGESLOTEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
        DocumentStatus.GESPLITST,
        DocumentStatus.AFGEWEZEN,
    }
)

UITKOMST_KANDIDAAT = "kandidaat"
UITKOMST_GEBUNDELD = "gebundeld"
UITKOMST_GEBUNDELD_BIJLAGE_FOUT = "gebundeld_bijlage_mislukt"
UITKOMST_OVERGESLAGEN = "overgeslagen"
UITKOMST_MISLUKT = "mislukt"


class TweelingFout(Exception):
    """Basis voor de route-vertaling (404/409/422)."""


class TweelingNietGevonden(TweelingFout):
    """Geen eenduidige tweeling voor dit document (404)."""


class TweelingTwijfel(TweelingFout):
    """Het paar is niet (meer) ondubbelzinnig of één kant is intussen verder verwerkt (409)."""


class GeenToegang(TweelingFout):
    """Administratie buiten de scope van de actor (403)."""


@dataclass(frozen=True)
class TweelingKandidaat:
    administratie_id: uuid.UUID
    administratie_naam: str
    pdf_document_id: uuid.UUID
    pdf_bestandsnaam: str
    pdf_status: str
    ubl_document_id: uuid.UUID | None
    ubl_bestandsnaam: str | None
    ubl_status: str | None
    intake_bericht_id: uuid.UUID | None
    #: `naamstam` | `factuurnummer` (bundeling-redenen) — None bij twijfel.
    match_basis: str | None
    factuurnummer: str | None = None
    ubl_geboekt: bool = False
    twijfel_reden: str | None = None

    @property
    def eenduidig(self) -> bool:
        return self.twijfel_reden is None and self.ubl_document_id is not None


@dataclass(frozen=True)
class TweelingUitkomst:
    kandidaat: TweelingKandidaat
    uitkomst: str
    reden: str | None = None
    bijlage: str | None = None

    def als_regel(self) -> str:
        k = self.kandidaat
        kern = f"{k.pdf_bestandsnaam} (PDF {k.pdf_document_id})"
        if k.ubl_document_id is not None:
            kern += f" → {k.ubl_bestandsnaam} (UBL {k.ubl_document_id}, {k.match_basis}"
            kern += ", geboekt)" if k.ubl_geboekt else ")"
        kern += f": {self.uitkomst}"
        if self.reden:
            kern += f" — {self.reden}"
        if self.bijlage:
            kern += f" [RLZ-bijlage: {self.bijlage}]"
        return kern


@dataclass
class TweelingTelling:
    kandidaten: int = 0
    gebundeld: int = 0
    overgeslagen: int = 0
    mislukt: int = 0
    uitkomsten: list[TweelingUitkomst] = field(default_factory=list)

    def registreer(self, u: TweelingUitkomst) -> None:
        self.uitkomsten.append(u)
        if u.uitkomst in (UITKOMST_GEBUNDELD, UITKOMST_GEBUNDELD_BIJLAGE_FOUT):
            self.gebundeld += 1
        elif u.uitkomst == UITKOMST_OVERGESLAGEN:
            self.overgeslagen += 1
        elif u.uitkomst == UITKOMST_MISLUKT:
            self.mislukt += 1

    def per_administratie(self) -> dict[str, dict[str, int]]:
        telling: dict[str, dict[str, int]] = {}
        for u in self.uitkomsten:
            per = telling.setdefault(u.kandidaat.administratie_naam, {})
            per[u.uitkomst] = per.get(u.uitkomst, 0) + 1
        return telling


# ---- kandidaten ---------------------------------------------------------------------------------------------------


def _is_pdf(naam: str) -> bool:
    return naam.lower().endswith(".pdf")


def _is_xml(naam: str) -> bool:
    return naam.lower().endswith(".xml")


def _dag(d: Document) -> date | None:
    return d.aangemaakt_op.date() if d.aangemaakt_op is not None else None


def _ubl_geboekt(session, ubl_id: uuid.UUID) -> bool:
    from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus

    return (
        session.scalar(
            select(VerkoopBoeking.id)
            .where(VerkoopBoeking.document_id == ubl_id, VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value)
            .limit(1)
        )
        is not None
    )


def _actieve_administraties(administratie_id: uuid.UUID | None) -> list[tuple[uuid.UUID, str]]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie.id, Administratie.naam).where(Administratie.actief.is_(True))
        if administratie_id is not None:
            q = q.where(Administratie.id == administratie_id)
        return [(r.id, r.naam) for r in session.execute(q.order_by(Administratie.naam))]


def kandidaten_voor_administratie(
    administratie_id: uuid.UUID,
    administratie_naam: str,
    *,
    opslag: DocumentOpslag | None = None,
    document_id: uuid.UUID | None = None,
) -> list[TweelingKandidaat]:
    """Alle losse open inkoopfactuur-PDF's van deze administratie mét hun (eenduidige óf twijfelachtige)
    UBL-tegenhanger. `document_id` beperkt tot één PDF (de actie op de rij). Lees-only."""
    opslag = opslag or _standaard_opslag()
    uit: list[TweelingKandidaat] = []
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        pdf_q = select(Document).where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status.in_(list(OPEN_STATUSSEN)),
            Document.bron == DocumentBron.EMAIL,
            Document.bron_opslag_pad.is_(None),
            Document.samengevoegd_in_id.is_(None),
            Document.bestandsnaam.ilike("%.pdf"),
        )
        if document_id is not None:
            pdf_q = pdf_q.where(Document.id == document_id)
        pdfs = session.scalars(pdf_q.order_by(Document.aangemaakt_op)).all()
        if not pdfs:
            return []
        ubls = session.scalars(
            select(Document)
            .where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.VERKOOPFACTUUR.value,
                Document.status.notin_(list(_UBL_UITGESLOTEN)),
                Document.bestandsnaam.ilike("%.xml"),
            )
            .order_by(Document.aangemaakt_op)
        ).all()
        if not ubls:
            return []

        # UBL-factuurnummer alleen lezen als de stam niet al matcht (één opslag-lees per UBL, gecachet).
        nummers: dict[uuid.UUID, str | None] = {}

        def nummer_van(u: Document) -> str | None:
            if u.id not in nummers:
                try:
                    nummers[u.id] = ubl_factuurnummer(opslag.lezen(pad=u.opslag_pad))
                except Exception:  # noqa: BLE001 — onleesbare UBL = geen nummer, geen fout
                    nummers[u.id] = None
            return nummers[u.id]

        tekstlagen: dict[uuid.UUID, str] = {}

        def tekstlaag_van(p: Document) -> str:
            if p.id not in tekstlagen:
                try:
                    tekstlagen[p.id] = pdf_tekstlaag_genormaliseerd(opslag.lezen(pad=p.opslag_pad))
                except Exception:  # noqa: BLE001
                    tekstlagen[p.id] = ""
            return tekstlagen[p.id]

        def zelfde_herkomst(p: Document, u: Document) -> bool:
            if p.intake_bericht_id is not None:
                return u.intake_bericht_id == p.intake_bericht_id
            return u.intake_bericht_id is None and _dag(u) == _dag(p)

        # (PDF → [(UBL, basis, nummer)])
        matches: dict[uuid.UUID, list[tuple[Document, str, str | None]]] = {}
        for p in pdfs:
            stam = genormaliseerde_stam(p.bestandsnaam)
            gevonden: list[tuple[Document, str, str | None]] = []
            for u in ubls:
                if not zelfde_herkomst(p, u):
                    continue
                if stam and genormaliseerde_stam(u.bestandsnaam) == stam:
                    gevonden.append((u, REDEN_NAAMSTAM, None))
                    continue
                nummer = nummer_van(u)
                if nummer and pdf_draagt_factuurnummer(p.bestandsnaam, None, nummer, tekstlaag=tekstlaag_van(p)):
                    gevonden.append((u, REDEN_FACTUURNUMMER, nummer))
            if gevonden:
                matches[p.id] = gevonden

        # Omgekeerd: één UBL mag maar bij één PDF horen.
        ubl_gebruik: dict[uuid.UUID, int] = {}
        for lijst in matches.values():
            for u, _, _ in lijst:
                ubl_gebruik[u.id] = ubl_gebruik.get(u.id, 0) + 1

        for p in pdfs:
            lijst = matches.get(p.id)
            if not lijst:
                continue
            basis_kandidaat = dict(
                administratie_id=administratie_id,
                administratie_naam=administratie_naam,
                pdf_document_id=p.id,
                pdf_bestandsnaam=p.bestandsnaam,
                pdf_status=p.status.value,
                intake_bericht_id=p.intake_bericht_id,
            )
            if len(lijst) > 1:
                namen = ", ".join(u.bestandsnaam for u, _, _ in lijst)
                uit.append(
                    TweelingKandidaat(
                        **basis_kandidaat,
                        ubl_document_id=None,
                        ubl_bestandsnaam=None,
                        ubl_status=None,
                        match_basis=None,
                        twijfel_reden=f"meerdere UBL-kandidaten ({namen}) — niet gebundeld",
                    )
                )
                continue
            u, basis, nummer = lijst[0]
            if ubl_gebruik.get(u.id, 0) > 1:
                uit.append(
                    TweelingKandidaat(
                        **basis_kandidaat,
                        ubl_document_id=u.id,
                        ubl_bestandsnaam=u.bestandsnaam,
                        ubl_status=u.status.value,
                        match_basis=None,
                        twijfel_reden=f"UBL {u.bestandsnaam} past op meerdere PDF's — niet gebundeld",
                    )
                )
                continue
            uit.append(
                TweelingKandidaat(
                    **basis_kandidaat,
                    ubl_document_id=u.id,
                    ubl_bestandsnaam=u.bestandsnaam,
                    ubl_status=u.status.value,
                    match_basis=basis,
                    factuurnummer=nummer,
                    ubl_geboekt=_ubl_geboekt(session, u.id),
                )
            )
    return uit


def vind_kandidaten(
    *, administratie_id: uuid.UUID | None = None, opslag: DocumentOpslag | None = None
) -> list[TweelingKandidaat]:
    """Kantoorbreed (of één administratie) — élke administratie in haar eigen RLS-scope."""
    uit: list[TweelingKandidaat] = []
    for aid, naam in _actieve_administraties(administratie_id):
        try:
            uit.extend(kandidaten_voor_administratie(aid, naam, opslag=opslag))
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de rest niet; zichtbaar
            logger.exception("tweelingen: kandidaten lezen mislukt voor %s", aid)
            print(f"FOUT {naam} ({aid}): kandidaten lezen mislukt — {type(exc).__name__}: {exc}", file=sys.stderr)
    return uit


# ---- herstel ------------------------------------------------------------------------------------------------------


def _tijdlijn_notitie(session, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
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


def _client_voor(administratie_id: uuid.UUID):  # noqa: ANN202 — RlzClient (seam)
    from app.documenten.boeken import _rlz_client_voor

    return _rlz_client_voor(administratie_id)


def _is_odoo(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        a = session.get(Administratie, administratie_id)
        return bool(a is not None and getattr(a, "boekhoud_backend", "rlz") == "odoo")


def upload_id_voor(pdf_document_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor de nagezonden PDF-bijlage (uniek per PDF-document; RLZ kent geen her-PUT op
    Uploads, `zorg_voor_bijlage` regelt de aanwezigheids-check op bestandsnaam)."""
    return uuid.uuid5(_UPLOAD_NAMESPACE, f"tweeling-beeld:{pdf_document_id}")


def _bijlage_nazenden(
    *,
    administratie_id: uuid.UUID,
    ubl_document_id: uuid.UUID,
    pdf_document_id: uuid.UUID,
    bestandsnaam: str,
    inhoud: bytes,
    client_factory: Callable[[uuid.UUID], object],
) -> str:
    """Geboekt UBL-document → PDF als extra bijlage op de SalesInvoice. Retourneert een leesbare uitkomst."""
    from app.rlz.bijlage import zorg_voor_bijlage
    from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus

    if _is_odoo(administratie_id):
        return "overgeslagen — Odoo-administratie (bijlage in Odoo volgt de Odoo-adapter, niet deze nazorg)"
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rlz_id = session.scalar(
            select(VerkoopBoeking.verkoop_rlz_id).where(
                VerkoopBoeking.document_id == ubl_document_id,
                VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
            )
        )
    if rlz_id is None:
        return "overgeslagen — geen geboekte verkoopboeking gevonden"
    client = client_factory(administratie_id)
    try:
        geupload = zorg_voor_bijlage(
            client,
            "SalesInvoices",
            rlz_id,
            upload_id=upload_id_voor(pdf_document_id),
            filename=bestandsnaam,
            content_base64=base64.b64encode(inhoud).decode(),
            op_bestandsnaam=True,
        )
    finally:
        sluit = getattr(client, "close", None)
        if callable(sluit):
            sluit()
    return f"geüpload op SalesInvoices/{rlz_id}" if geupload else f"stond al op SalesInvoices/{rlz_id}"


def herstel_een(
    kandidaat: TweelingKandidaat,
    *,
    opslag: DocumentOpslag | None = None,
    dry_run: bool = True,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    client_factory: Callable[[uuid.UUID], object] | None = None,
    bron_label: str = "nazorg vastly-pdf-tweelingen-herstel",
) -> TweelingUitkomst:
    """Eén paar, één transactie (bijlage-upload ná de commit). Zie module-docstring."""

    def overgeslagen(reden: str) -> TweelingUitkomst:
        return TweelingUitkomst(kandidaat, UITKOMST_OVERGESLAGEN, reden=reden)

    if not kandidaat.eenduidig or kandidaat.ubl_document_id is None:
        return overgeslagen(kandidaat.twijfel_reden or "tegenhanger onbekend")
    opslag = opslag or _standaard_opslag()
    aid = kandidaat.administratie_id
    pdf_inhoud: bytes | None = None
    pdf_naam = kandidaat.pdf_bestandsnaam
    with scoped_session(aid, actor_id=actor_id) as session:
        pdf = session.get(Document, kandidaat.pdf_document_id)
        ubl = session.get(Document, kandidaat.ubl_document_id)
        if pdf is None or pdf.administratie_id != aid or ubl is None or ubl.administratie_id != aid:
            return overgeslagen("PDF of UBL-document niet (meer) gevonden in de administratie")
        if pdf.status not in OPEN_STATUSSEN:
            return overgeslagen(f"PDF is intussen verder verwerkt (status {pdf.status.value.replace('_', ' ')})")
        if pdf.bron_opslag_pad is not None or pdf.samengevoegd_in_id is not None:
            return overgeslagen("PDF draagt intussen een beeld of samenvoeg-verwijzing")
        if ubl.status in _UBL_UITGESLOTEN:
            return overgeslagen(f"UBL-document is intussen {ubl.status.value.replace('_', ' ')}")
        if ubl.bron_opslag_pad is not None:
            return overgeslagen(f"UBL-document heeft al een beeld ({ubl.bron_bestandsnaam})")
        if not _is_pdf(pdf.bestandsnaam) or not _is_xml(ubl.bestandsnaam):
            return overgeslagen("bestandsnamen passen niet (PDF/XML)")
        if dry_run:
            return TweelingUitkomst(
                kandidaat,
                UITKOMST_KANDIDAAT,
                reden=f"zou bundelen: PDF → beeld van {ubl.bestandsnaam}, PDF-document → samengevoegd"
                + (" + RLZ-bijlage nazenden (UBL is geboekt)" if kandidaat.ubl_geboekt else ""),
            )

        correlatie_id = uuid.uuid4()
        reden = (
            f"{bron_label}: {pdf.bestandsnaam} is het beeld van {ubl.bestandsnaam} (zelfde factuur, match op "
            f"{kandidaat.match_basis}) — achteraf gebundeld; het UBL-document blijft het document"
        )
        ubl_oud = {"bron_opslag_pad": ubl.bron_opslag_pad, "bron_bestandsnaam": ubl.bron_bestandsnaam}
        ubl.bron_opslag_pad = pdf.opslag_pad
        ubl.bron_bestandsnaam = pdf.bestandsnaam
        ubl.bron_content_type = "application/pdf"
        _tijdlijn_notitie(
            session,
            ubl,
            actor_id,
            {
                TIJDLIJN_SLEUTEL: True,
                "beeld_van": str(pdf.id),
                "beeld_bestandsnaam": pdf.bestandsnaam,
                "match_basis": kandidaat.match_basis,
                "reden": reden,
            },
        )
        pdf_oud = {"status": pdf.status.value, "samengevoegd_in_id": None}
        pdf.samengevoegd_in_id = ubl.id
        _schrijf_overgang(
            session,
            document=pdf,
            naar=DocumentStatus.SAMENGEVOEGD,
            actor_id=actor_id,
            detail={
                "samengevoegd_in": str(ubl.id),
                "leidend_bestandsnaam": ubl.bestandsnaam,
                TIJDLIJN_SLEUTEL: True,
                "match_basis": kandidaat.match_basis,
                "reden": reden,
            },
        )
        for record_id, oud, nieuw in (
            (
                ubl.id,
                ubl_oud,
                {
                    "bron_opslag_pad": ubl.bron_opslag_pad,
                    "bron_bestandsnaam": ubl.bron_bestandsnaam,
                    "beeld_document_id": str(pdf.id),
                    "match_basis": kandidaat.match_basis,
                },
            ),
            (
                pdf.id,
                pdf_oud,
                {
                    "status": DocumentStatus.SAMENGEVOEGD.value,
                    "samengevoegd_in_id": str(ubl.id),
                    "match_basis": kandidaat.match_basis,
                },
            ),
        ):
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=record_id,
                actie=AUDIT_GEBUNDELD_ACHTERAF,
                correlatie_id=correlatie_id,
                oude_waarde=oud,
                nieuwe_waarde=nieuw,
                administratie_id=aid,
            )
        if kandidaat.ubl_geboekt:
            pdf_inhoud = opslag.lezen(pad=pdf.opslag_pad)
            pdf_naam = pdf.bestandsnaam

    if not kandidaat.ubl_geboekt or pdf_inhoud is None:
        return TweelingUitkomst(kandidaat, UITKOMST_GEBUNDELD)
    try:
        bijlage = _bijlage_nazenden(
            administratie_id=aid,
            ubl_document_id=kandidaat.ubl_document_id,
            pdf_document_id=kandidaat.pdf_document_id,
            bestandsnaam=pdf_naam,
            inhoud=pdf_inhoud,
            client_factory=client_factory or _client_voor,
        )
    except Exception as exc:  # noqa: BLE001 — de lokale bundeling staat; de bijlage-fout is zichtbaar, nooit stil
        logger.warning("tweelingen: RLZ-bijlage nazenden mislukt voor %s: %s", kandidaat.pdf_document_id, exc)
        return TweelingUitkomst(
            kandidaat,
            UITKOMST_GEBUNDELD_BIJLAGE_FOUT,
            reden="lokaal gebundeld; RLZ-bijlage nazenden mislukt — opnieuw via de nazorg-CLI",
            bijlage=f"mislukt: {type(exc).__name__}: {str(exc)[:200]}",
        )
    return TweelingUitkomst(kandidaat, UITKOMST_GEBUNDELD, bijlage=bijlage)


def herstel_alle(
    *,
    dry_run: bool = True,
    administratie_id: uuid.UUID | None = None,
    opslag: DocumentOpslag | None = None,
    client_factory: Callable[[uuid.UUID], object] | None = None,
) -> TweelingTelling:
    telling = TweelingTelling()
    kandidaten = vind_kandidaten(administratie_id=administratie_id, opslag=opslag)
    telling.kandidaten = len(kandidaten)
    for k in kandidaten:
        try:
            uitkomst = herstel_een(k, opslag=opslag, dry_run=dry_run, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001 — één kapot paar stopt de stapel niet; wél zichtbaar
            logger.exception("tweelingen: herstel mislukt voor %s", k.pdf_document_id)
            uitkomst = TweelingUitkomst(k, UITKOMST_MISLUKT, reden=f"onverwachte fout ({type(exc).__name__}: {exc})")
        telling.registreer(uitkomst)
    return telling


def bundel_vanuit_bevinding(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, rol
) -> TweelingUitkomst:  # noqa: ANN001 — GebruikerRol
    """Actie "Bundelen" op de rij `ubl_pdf_ongebundeld` (Inzicht › Reconciliatie): exact `herstel_een` voor dít
    PDF-document, mens-actor. Scope-toets via `mijn_administraties`; 404 zonder eenduidig paar; 409 bij twijfel/
    intussen verwerkt."""
    from app.auth import service as auth_service

    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise GeenToegang("Geen toegang tot deze administratie")
    naam = next((n for a, n in _actieve_administraties(administratie_id) if a == administratie_id), None)
    if naam is None:
        raise TweelingNietGevonden("Administratie niet gevonden of niet actief")
    kandidaten = kandidaten_voor_administratie(administratie_id, naam, document_id=document_id)
    if not kandidaten:
        raise TweelingNietGevonden(
            "Geen UBL-tegenhanger (verkoopfactuur uit dezelfde e-mail) voor dit document gevonden"
        )
    k = kandidaten[0]
    if not k.eenduidig:
        raise TweelingTwijfel(k.twijfel_reden or "paar is niet ondubbelzinnig")
    uitkomst = herstel_een(k, dry_run=False, actor_id=actor_id, bron_label="Bundelen (Inzicht › Reconciliatie)")
    if uitkomst.uitkomst == UITKOMST_OVERGESLAGEN:
        raise TweelingTwijfel(uitkomst.reden or "niet gebundeld")
    if uitkomst.uitkomst == UITKOMST_MISLUKT:
        raise TweelingFout(uitkomst.reden or "bundelen mislukt")
    return uitkomst


# ---- reconciliatie (lees-only) ------------------------------------------------------------------------------------


def afwijkingen_voor_reconciliatie(administratie_id: uuid.UUID, administratie_naam: str) -> list:
    """Blok `documenten`: één `ReconciliatieAfwijking` per EENDUIDIG paar (soort `ubl_pdf_ongebundeld`, in `meten`).
    Lees-only — schrijft niets; twijfelparen tellen hier niet (de nazorg-CLI toont ze). Nooit een exception."""
    from app.documenten.reconciliatie import ReconciliatieAfwijking
    from app.documenten.rlz_ids import rlz_purchase_invoice_id

    try:
        kandidaten = kandidaten_voor_administratie(administratie_id, administratie_naam)
    except Exception as exc:  # noqa: BLE001 — een leesfout mag het blok niet laten omvallen
        logger.warning("tweelingen: reconciliatie-toets mislukt voor %s: %s", administratie_id, exc)
        return []
    uit = []
    for k in kandidaten:
        if not k.eenduidig or k.ubl_document_id is None:
            continue
        uit.append(
            ReconciliatieAfwijking(
                k.pdf_document_id,
                rlz_purchase_invoice_id(k.pdf_document_id),
                SOORT_ONGEBUNDELD,
                f"losse PDF {k.pdf_bestandsnaam} hoort bij UBL-verkoopfactuur {k.ubl_bestandsnaam} "
                f"(match op {k.match_basis}) — niet gebundeld",
                {
                    "administratie_naam": administratie_naam,
                    "bestandsnaam": k.pdf_bestandsnaam,
                    "ubl_document_id": str(k.ubl_document_id),
                    "ubl_bestandsnaam": k.ubl_bestandsnaam,
                    "match_basis": k.match_basis,
                    "factuurnummer": k.factuurnummer,
                    "ubl_geboekt": "ja" if k.ubl_geboekt else "nee",
                    "document_status": k.pdf_status,
                },
            )
        )
    return uit


# ---- CLI ------------------------------------------------------------------------------------------------------------


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Nazorg (blok 1 bundelrun 24-09): losse inkoopfactuur-PDF's die de tweeling zijn van een "
        "UBL-verkoopfactuur (Vastly-batch 23-09, 23 documenten) achteraf bundelen — PDF wordt beeld van het "
        "UBL-document, PDF-document → samengevoegd, tijdlijn + audit `gebundeld_achteraf`; geboekt UBL → PDF óók als "
        "RLZ-bijlage. Dry-run is de default; --uitvoeren schrijft.",
    )
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tonen (default).")
    p.add_argument("--uitvoeren", action="store_true", dest="uitvoeren", help="Échte run (schrijft).")
    p.add_argument("--administratie", default=None, help="Beperk tot één administratie (uuid of naamdeel).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run_cli(args)


def _administratie_id(term: str) -> uuid.UUID | None:
    from app.rlz.lezen_cli import _zoek_administraties

    treffers = _zoek_administraties(term)
    if len(treffers) != 1:
        print(
            f"FOUT: --administratie {term!r} is niet eenduidig ({len(treffers)} treffers) — niets gedaan",
            file=sys.stderr,
        )
        return None
    return treffers[0][0]


def run_cli(args: argparse.Namespace) -> int:
    dry_run = not bool(getattr(args, "uitvoeren", False))
    if getattr(args, "dry_run", False) and getattr(args, "uitvoeren", False):
        print("FOUT: kies --dry-run óf --uitvoeren, niet beide", file=sys.stderr)
        return 2
    administratie_id: uuid.UUID | None = None
    if getattr(args, "administratie", None):
        administratie_id = _administratie_id(args.administratie)
        if administratie_id is None:
            return 2
    label = "DRY-RUN (niets geschreven)" if dry_run else "UITGEVOERD"
    telling = herstel_alle(dry_run=dry_run, administratie_id=administratie_id)
    print(f"{COMMANDO} — {label}: {telling.kandidaten} kandidaat/kandidaten")
    for u in telling.uitkomsten:
        print(f"  - [{u.kandidaat.administratie_naam}] {u.als_regel()}")
    for naam, per in sorted(telling.per_administratie().items()):
        print(f"  {naam}: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items())))
    print(
        f"TOTAAL: {telling.kandidaten} kandidaten, {telling.gebundeld} gebundeld, {telling.overgeslagen} overgeslagen, "
        f"{telling.mislukt} mislukt — {label}"
    )
    return 1 if telling.mislukt else 0
