"""CLI `xml-documenten-rapport` — LEES-ONLY nameting-instrument (FV-01, feedbackrun A 25-09; nameting-allowlist,
dispatch-onderdeel `xml-documenten`).

Aanleiding: Universal Steigerbouw document 250895e8 (RLZ-2080142898.xml, 02-09) stond zónder PDF-beeld in de module
en toonde de ruwe XML. Dit rapport telt kantoorbreed álle documenten met een `.xml`-HOOFDBESTAND per administratie in
haar EIGEN RLS-scope (patroon `app/beheer/bua_cli.py`): status, beeld (bron-PDF / ingesloten PDF / geen), of de
laatste extractie een `ubl_parse_fout` droeg (= "niet leesbaar", sinds 25-09 status handmatig_afmaken), en of er in
hetzelfde intake-bericht een PDF-tweeling bestaat (in de administratie, in de verzamelbak, of als splitsingsbron) —
mét het voorstel per rij: opnieuw aanbieden via het BESTAANDE pad (`verzamelbak-nabundelen --ook-toegewezen` voor een
tweeling, `intake-herlezen --alleen-ubl` voor een onleesbare UBL zonder tweeling). Schrijft niets, geen RLZ-call.

Oordeelregel (TOTAAL): "N xml-documenten · M zonder beeld · K niet leesbaar · T mét PDF-tweeling · fouten F".
Productie: `scripts/gcp/nameting.sh xml-documenten-rapport [--administratie <uuid|naamdeel>] [--alles]`.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass, field

COMMANDO = "xml-documenten-rapport"

BEELD_BRON = "bron_pdf"
BEELD_INGESLOTEN = "ingesloten_pdf"
BEELD_GEEN = "geen"

VOORSTEL_TWEELING = "verzamelbak-nabundelen --ook-toegewezen (PDF-tweeling koppelen; UBL blijft het document)"
VOORSTEL_HERLEZEN = "intake-herlezen --alleen-ubl (deterministisch opnieuw aanbieden)"
VOORSTEL_GEEN = "—"


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="LEES-ONLY (25-09, FV-01): documenten met een .xml-hoofdbestand per administratie — status, beeld "
        "(bron-PDF/ingesloten/geen), niet-leesbaar-reden, PDF-tweeling in hetzelfde intake-bericht, voorstel. "
        "Schrijft niets, geen RLZ-call.",
    )
    doel = p.add_mutually_exclusive_group()
    doel.add_argument("--administratie", default=None, help="Eén administratie (uuid of naamdeel).")
    doel.add_argument(
        "--alles", action="store_true", help="Alle actieve administraties (default als niets is opgegeven)."
    )
    p.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer (JSON).")
    p.add_argument("--detail", action="store_true", help="Toon ook de rijen per document.")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return rapport(args)


@dataclass(frozen=True)
class XmlRij:
    administratie: str
    document_id: str
    bestandsnaam: str
    status: str
    aangemaakt_op: str | None
    beeld: str
    niet_leesbaar_reden: str | None
    pdf_tweeling: str | None  # bestandsnaam van de PDF in hetzelfde intake-bericht (administratie/verzamelbak)
    voorstel: str


@dataclass
class Meting:
    administraties: int
    rijen: list[XmlRij] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)

    @property
    def zonder_beeld(self) -> int:
        return sum(1 for r in self.rijen if r.beeld == BEELD_GEEN)

    @property
    def niet_leesbaar(self) -> int:
        return sum(1 for r in self.rijen if r.niet_leesbaar_reden)

    @property
    def met_tweeling(self) -> int:
        return sum(1 for r in self.rijen if r.pdf_tweeling)

    def totaal_regel(self) -> str:
        return (
            f"TOTAAL {len(self.rijen)} xml-documenten · {self.zonder_beeld} zonder beeld · "
            f"{self.niet_leesbaar} niet leesbaar · {self.met_tweeling} mét PDF-tweeling · fouten {len(self.fouten)}"
        )


def _administraties(term: str | None) -> list[tuple[uuid.UUID, str]] | None:
    from app.beheer.bua_cli import _administraties as bua_administraties

    return bua_administraties(term)


def _laatste_parse_fout(session, document_id: uuid.UUID) -> str | None:  # noqa: ANN001
    """De `ubl_parse_fout` van de LAATSTE extractie-eindovergang; None als de laatste extractie een voorstel gaf."""
    from sqlalchemy import select

    from app.documenten.models import DocumentGebeurtenis, DocumentStatus

    rijen = session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status.in_((DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN)),
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
        .limit(1)
    ).all()
    if not rijen:
        return None
    detail = rijen[0].detail or {}
    fout = detail.get("ubl_parse_fout")
    return str(fout) if fout else None


def _pdf_tweelingen_per_bericht(session, bericht_ids: set[uuid.UUID], *, administratie_id: uuid.UUID | None):  # noqa: ANN001
    """{intake_bericht_id → [pdf-bestandsnaam]} — PDF-documenten uit dezelfde berichten (in deze scope)."""
    from collections import defaultdict

    from sqlalchemy import select

    from app.documenten.models import Document

    if not bericht_ids:
        return {}
    voorwaarden = [Document.intake_bericht_id.in_(list(bericht_ids)), Document.bestandsnaam.ilike("%.pdf")]
    if administratie_id is not None:
        voorwaarden.append(Document.administratie_id == administratie_id)
    else:
        voorwaarden.append(Document.administratie_id.is_(None))
    uit: dict[uuid.UUID, list[str]] = defaultdict(list)
    for bericht_id, naam in session.execute(
        select(Document.intake_bericht_id, Document.bestandsnaam).where(*voorwaarden)
    ).all():
        uit[bericht_id].append(naam)
    return uit


def rijen_voor(administratie_id: uuid.UUID, administratie_naam: str, *, opslag=None) -> list[XmlRij]:  # noqa: ANN001
    """Alle documenten mét .xml-hoofdbestand van één administratie (eigen RLS-scope) — lees-only."""
    from sqlalchemy import select

    from app.db.session import scoped_session
    from app.documenten.beeld import BestandenSnapshot, bepaal_beeld
    from app.documenten.models import Document
    from app.documenten.storage import standaard_opslag
    from app.intake.bundeling import genormaliseerde_stam

    opslag = opslag or standaard_opslag()
    uit: list[XmlRij] = []
    with scoped_session(administratie_id) as session:
        docs = list(
            session.scalars(
                select(Document)
                .where(Document.administratie_id == administratie_id, Document.bestandsnaam.ilike("%.xml"))
                .order_by(Document.aangemaakt_op.desc())
            )
        )
        bericht_ids = {d.intake_bericht_id for d in docs if d.intake_bericht_id is not None}
        tweelingen = _pdf_tweelingen_per_bericht(session, bericht_ids, administratie_id=administratie_id)
        snapshots = [(d, BestandenSnapshot.van(d), _laatste_parse_fout(session, d.id)) for d in docs]
    # Verzamelbak-PDF's uit dezelfde berichten (administratie NULL) — apart, buiten de administratie-scope.
    with scoped_session(None) as session:
        bak = _pdf_tweelingen_per_bericht(session, bericht_ids, administratie_id=None)
    for d, snapshot, parse_fout in snapshots:
        if snapshot.bron_opslag_pad and (snapshot.bron_bestandsnaam or "").lower().endswith(".pdf"):
            beeld = BEELD_BRON
        else:
            try:
                b = bepaal_beeld(snapshot, opslag=opslag)
                beeld = BEELD_INGESLOTEN if b.content_type == "application/pdf" else BEELD_GEEN
            except Exception as exc:  # noqa: BLE001 — een onleesbaar opslagpad is een zichtbare rij, geen crash
                beeld = f"onleesbaar ({exc.__class__.__name__})"
        stam = genormaliseerde_stam(d.bestandsnaam)
        kandidaten = [
            *tweelingen.get(d.intake_bericht_id, []),
            *(f"{n} (verzamelbak)" for n in bak.get(d.intake_bericht_id, [])),
        ]
        op_stam = [n for n in kandidaten if genormaliseerde_stam(n.replace(" (verzamelbak)", "")) == stam]
        tweeling = op_stam[0] if len(op_stam) == 1 else (f"{len(op_stam)} kandidaten" if op_stam else None)
        if beeld == BEELD_GEEN and tweeling:
            voorstel = VOORSTEL_TWEELING
        elif parse_fout:
            voorstel = VOORSTEL_HERLEZEN
        else:
            voorstel = VOORSTEL_GEEN
        uit.append(
            XmlRij(
                administratie=administratie_naam,
                document_id=str(d.id),
                bestandsnaam=d.bestandsnaam,
                status=d.status.value,
                aangemaakt_op=d.aangemaakt_op.isoformat() if d.aangemaakt_op else None,
                beeld=beeld,
                niet_leesbaar_reden=parse_fout,
                pdf_tweeling=tweeling,
                voorstel=voorstel,
            )
        )
    return uit


def meet(*, administratie: str | None, opslag=None) -> Meting | None:  # noqa: ANN001
    adms = _administraties(administratie)
    if adms is None:
        return None
    meting = Meting(administraties=len(adms))
    for aid, naam in adms:
        try:
            meting.rijen.extend(rijen_voor(aid, naam, opslag=opslag))
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de rest niet (zichtbare FOUT-regel)
            meting.fouten.append(f"{naam}: {exc.__class__.__name__}: {exc}")
    return meting


def rapport(args: argparse.Namespace) -> int:
    meting = meet(administratie=args.administratie)
    if meting is None:
        return 2
    if args.json_uit:
        print(
            json.dumps(
                {
                    "administraties": meting.administraties,
                    "rijen": [asdict(r) for r in meting.rijen],
                    "fouten": meting.fouten,
                    "totaal": meting.totaal_regel(),
                },
                indent=1,
                ensure_ascii=False,
            )
        )
        return 0
    print(f"== xml-documenten-rapport (lees-only) — {meting.administraties} administratie(s) ==")
    per_adm: dict[str, list[XmlRij]] = {}
    for r in meting.rijen:
        per_adm.setdefault(r.administratie, []).append(r)
    for naam, rijen in sorted(per_adm.items()):
        z = sum(1 for r in rijen if r.beeld == BEELD_GEEN)
        n = sum(1 for r in rijen if r.niet_leesbaar_reden)
        t = sum(1 for r in rijen if r.pdf_tweeling)
        print(f"- {naam}: {len(rijen)} xml · {z} zonder beeld · {n} niet leesbaar · {t} mét PDF-tweeling")
        if args.detail:
            for r in rijen:
                print(
                    f"    {r.document_id[:8]} {r.status:<20} beeld={r.beeld:<14} "
                    f"{r.bestandsnaam} | reden={r.niet_leesbaar_reden or '-'} | tweeling={r.pdf_tweeling or '-'} "
                    f"| voorstel={r.voorstel}"
                )
    for fout in meting.fouten:
        print(f"FOUT  {fout}", file=sys.stderr)
        print(f"FOUT  {fout}")
    print(meting.totaal_regel())
    return 0
