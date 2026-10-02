"""Heraanbieding Vastly-verkoopdocumenten door het automatische pad (Peter 29-09, punt 6 + dagelijkse stap).

Twee soorten kandidaten, beide deterministisch en zonder AI:
 (a) NIET-GEKOPPELD: verkoopfactuur-documenten zonder administratie (status niet_toegewezen) met een Vastly-reden
     (`vastly_entiteit_niet_gekoppeld: …` of de oude `vastly_verkoop_zonder_eenduidige_entiteit`). Per document wordt
     de UBL opnieuw gelezen en de entiteit via het register geresolved; gevonden → administratie zetten (tijdlijn
     `vanuit: entiteitenregister`, audit `vastly_entiteit_toegewezen`, GEEN toewijzings-geheugen) + de gewone
     extractieroute (`start_extractie_na_toewijzing`, waarvan de post-commit-hook het autoboek-pad draait);
     niet gevonden → blijft staan (de bevinding `vastly_entiteit_niet_gekoppeld` blijft).
 (b) OPEN IN ADMINISTRATIE: verkoopfactuur-UBL's op te_controleren in élke actieve is_vastgoed-administratie (eigen
     RLS-scope) → `probeer_verkoop_autoboeken_na_intake` (elke uitkomst geauditeerd door dat pad).

`dry_run` = telling per administratie en per verwachte uitkomst (lees-only oordeel `autoboeken.beoordeel_lees_only`,
niets geschreven, geen audit). De échte run schrijft één audit `vastly_verkoop_heraanbieding_run` (kandidaten,
uitkomsten per soort) → dagteller `vastly_verkoop_heraanbieding` in de reconciliatiemail. Geboekte documenten krijgen
via de boekmotor dezelfde `factuur_geboekt`-webhook als handmatig boeken. Volumerem en harde checks gelden in de
motor onverkort — deze module heeft geen eigen geldlogica."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur
from app.intake.redenen import is_vastly_verkoop_reden
from app.verkoop import autoboeken, entiteit

logger = logging.getLogger(__name__)

COMMANDO = "vastly-verkoop-heraanbieden"
AUDIT_RUN = "vastly_verkoop_heraanbieding_run"
AUDIT_TOEGEWEZEN = "vastly_entiteit_toegewezen"
SOORT_NIET_GEKOPPELD = "niet_gekoppeld"
SOORT_OPEN = "open_in_administratie"
UITKOMST_GEBOEKT = "geboekt"
UITKOMST_TOEGEWEZEN = "toegewezen"
UITKOMST_GEWEIGERD = "geweigerd"
UITKOMST_NIET_GEKOPPELD = "entiteit_niet_gekoppeld"
UITKOMST_ONLEESBAAR = "ubl_onleesbaar"
UITKOMST_FOUT = "fout"
UITKOMST_ZOU_BOEKEN = "zou_boeken"
UITKOMST_ZOU_TOEWIJZEN = "zou_toewijzen"


@dataclass(frozen=True)
class Kandidaat:
    soort: str
    document_id: uuid.UUID
    administratie_id: uuid.UUID | None
    administratie_naam: str | None
    bestandsnaam: str
    aangemaakt_op: datetime


@dataclass
class RijUitkomst:
    kandidaat: Kandidaat
    uitkomst: str
    reden: str | None = None
    administratie_naam: str | None = None

    def als_regel(self) -> str:
        naam = self.administratie_naam or self.kandidaat.administratie_naam or "(geen administratie)"
        return f"{self.kandidaat.bestandsnaam} · {naam} → {self.uitkomst}" + (f" — {self.reden}" if self.reden else "")

    def als_dict(self) -> dict:
        return {
            "document_id": str(self.kandidaat.document_id),
            "soort": self.kandidaat.soort,
            "administratie_id": str(self.kandidaat.administratie_id) if self.kandidaat.administratie_id else None,
            "bestandsnaam": self.kandidaat.bestandsnaam,
            "uitkomst": self.uitkomst,
            "reden": (self.reden or "")[:300] or None,
        }


@dataclass
class RunResultaat:
    run_id: uuid.UUID
    bron: str
    dry_run: bool
    gestart_op: datetime
    uitkomsten: list[RijUitkomst] = field(default_factory=list)
    klaar_op: datetime | None = None

    @property
    def kandidaten(self) -> int:
        return len(self.uitkomsten)

    def per_uitkomst(self) -> dict[str, int]:
        uit: dict[str, int] = {}
        for u in self.uitkomsten:
            uit[u.uitkomst] = uit.get(u.uitkomst, 0) + 1
        return dict(sorted(uit.items()))

    def per_administratie(self) -> dict[str, dict[str, int]]:
        uit: dict[str, dict[str, int]] = {}
        for u in self.uitkomsten:
            naam = u.administratie_naam or u.kandidaat.administratie_naam or "(geen administratie)"
            per = uit.setdefault(naam, {})
            per[u.uitkomst] = per.get(u.uitkomst, 0) + 1
        return dict(sorted(uit.items()))

    def als_dict(self) -> dict:
        return {
            "run_id": str(self.run_id),
            "bron": self.bron,
            "dry_run": self.dry_run,
            "kandidaten": self.kandidaten,
            "per_uitkomst": self.per_uitkomst(),
            "per_administratie": self.per_administratie(),
            "uitkomsten": [u.als_dict() for u in self.uitkomsten[:300]],
        }


def _jongste_reden(session, document_id: uuid.UUID) -> str | None:  # noqa: ANN001
    from app.intake.verzamelbak import _jongste_intake_redenen

    return _jongste_intake_redenen(session, [document_id]).get(document_id)


def vind_niet_gekoppeld() -> list[Kandidaat]:
    """(a) Verkoopfactuur-documenten zonder administratie met een Vastly-reden — oud → nieuw."""
    with scoped_session(None) as session:
        documenten = session.scalars(
            select(Document)
            .where(
                Document.administratie_id.is_(None),
                Document.status == DocumentStatus.NIET_TOEGEWEZEN,
                Document.soort == DocumentSoort.VERKOOPFACTUUR.value,
            )
            .order_by(Document.aangemaakt_op.asc(), Document.id)
        ).all()
        uit: list[Kandidaat] = []
        for d in documenten:
            if is_vastly_verkoop_reden(_jongste_reden(session, d.id)):
                uit.append(
                    Kandidaat(
                        soort=SOORT_NIET_GEKOPPELD,
                        document_id=d.id,
                        administratie_id=None,
                        administratie_naam=None,
                        bestandsnaam=d.bestandsnaam,
                        aangemaakt_op=d.aangemaakt_op,
                    )
                )
        return uit


def vastgoed_administraties(administratie_ids: list[uuid.UUID] | None = None) -> list[tuple[uuid.UUID, str]]:
    with scoped_session(None) as session:
        q = select(Administratie.id, Administratie.naam).where(
            Administratie.actief.is_(True), Administratie.gearchiveerd_op.is_(None), Administratie.is_vastgoed.is_(True)
        )
        if administratie_ids is not None:
            q = q.where(Administratie.id.in_(administratie_ids))
        return [(r.id, r.naam) for r in session.execute(q.order_by(Administratie.naam)).all()]


def vind_open_in_administraties(administratie_ids: list[uuid.UUID] | None = None) -> list[Kandidaat]:
    """(b) Verkoopfactuur-UBL's op te_controleren per actieve is_vastgoed-administratie (eigen RLS-scope)."""
    uit: list[Kandidaat] = []
    for administratie_id, naam in vastgoed_administraties(administratie_ids):
        with scoped_session(administratie_id) as session:
            documenten = session.scalars(
                select(Document)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.soort == DocumentSoort.VERKOOPFACTUUR.value,
                    Document.status == DocumentStatus.TE_CONTROLEREN,
                )
                .order_by(Document.aangemaakt_op.asc(), Document.id)
            ).all()
            uit.extend(
                Kandidaat(
                    soort=SOORT_OPEN,
                    document_id=d.id,
                    administratie_id=administratie_id,
                    administratie_naam=naam,
                    bestandsnaam=d.bestandsnaam,
                    aangemaakt_op=d.aangemaakt_op,
                )
                for d in documenten
            )
    return uit


def _sleutels_voor(document: Document, *, opslag: DocumentOpslag) -> entiteit.EntiteitSleutels | None:
    """De UBL opnieuw lezen (deterministisch) — None = niet leesbaar."""
    try:
        voorstel = parseer_ubl_factuur(opslag.lezen(pad=document.opslag_pad))
    except (GeenGeldigeUbl, Exception) as exc:  # noqa: BLE001 — onleesbaar = zichtbare uitkomst, geen crash
        logger.warning("Vastly-heraanbieding: UBL %s niet leesbaar: %s", document.id, exc)
        return None
    return entiteit.sleutels_uit_voorstel(voorstel)


def wijs_toe_via_register(
    *, document_id: uuid.UUID, administratie_id: uuid.UUID, actor_id: uuid.UUID, bron: str, opslag: DocumentOpslag
) -> DocumentStatus:
    """Zelfde stappen als `verzamelbak.wijs_toe` maar ZONDER toewijzings-geheugen (dit is een registerfeit, geen
    mens-besluit) en mét eigen tijdlijn-/auditspoor; daarna de gewone extractieroute (post-commit-hook = autoboek)."""
    from app.documenten.service import _schrijf_overgang, start_extractie_na_toewijzing

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        niet_toegewezen = document is not None and document.administratie_id is None
        if not niet_toegewezen or document.status != DocumentStatus.NIET_TOEGEWEZEN:
            raise ValueError("document staat niet (meer) zonder administratie")
        document.administratie_id = administratie_id
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.ONTVANGEN,
            actor_id=actor_id,
            detail={
                "toegewezen_aan_administratie": str(administratie_id),
                "vanuit": "entiteitenregister",
                "bron": bron,
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=AUDIT_TOEGEWEZEN,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"administratie_id": str(administratie_id), "bron": bron},
            administratie_id=administratie_id,
        )
    return start_extractie_na_toewijzing(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, opslag=opslag
    )


def _verwerk_niet_gekoppeld(k: Kandidaat, *, dry_run: bool, actor_id: uuid.UUID, opslag: DocumentOpslag) -> RijUitkomst:
    with scoped_session(None, actor_id=actor_id) as session:
        document = session.get(Document, k.document_id)
        weg = document is None or document.status != DocumentStatus.NIET_TOEGEWEZEN
        if weg or document.administratie_id is not None:
            return RijUitkomst(k, UITKOMST_GEWEIGERD, "intussen verwerkt (status veranderd)")
        sleutels = _sleutels_voor(document, opslag=opslag)
        if sleutels is None:
            return RijUitkomst(k, UITKOMST_ONLEESBAAR, "UBL niet leesbaar — blijft staan (bevinding)")
        besluit = entiteit.resolve_administratie(session, sleutels)
        if dry_run:
            session.rollback()
        administratie_id = besluit.administratie_id
        naam = session.get(Administratie, administratie_id).naam if administratie_id is not None else None
    if administratie_id is None:
        entiteit_naam = sleutels.weergave or sleutels.naam_norm or sleutels.kvk or "?"
        return RijUitkomst(
            k,
            UITKOMST_NIET_GEKOPPELD,
            f"entiteit {entiteit_naam}: {entiteit.weigering_tekst(sleutels, besluit.weigering)}",
        )
    if dry_run:
        return RijUitkomst(k, UITKOMST_ZOU_TOEWIJZEN, f"entiteitenregister:{besluit.bron}", administratie_naam=naam)
    try:
        wijs_toe_via_register(
            document_id=k.document_id,
            administratie_id=administratie_id,
            actor_id=actor_id,
            bron=besluit.bron or "",
            opslag=opslag,
        )
    except Exception as exc:  # noqa: BLE001 — één document mag de rest niet stoppen; zichtbaar in de uitkomst
        logger.exception("Vastly-heraanbieding: toewijzen van %s mislukt", k.document_id)
        return RijUitkomst(k, UITKOMST_FOUT, str(exc)[:300], administratie_naam=naam)
    return RijUitkomst(k, _eindstand(administratie_id, k.document_id), None, administratie_naam=naam)


def _eindstand(administratie_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """Ná de extractie + post-commit-hook: geboekt, of toegewezen mét de weigerreden uit het jongste audit."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is not None and document.status == DocumentStatus.GEBOEKT:
            return UITKOMST_GEBOEKT
    return UITKOMST_TOEGEWEZEN


def _jongste_weigerreden(administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
    from app.db.models import AuditEvent

    with scoped_session(administratie_id) as session:
        rij = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.record_id == document_id,
                AuditEvent.actie == "autoboeken_geweigerd",
            )
            .order_by(AuditEvent.tijdstip.desc())
        ).first()
        return (rij.nieuwe_waarde or {}).get("reden") if rij is not None else None


def _verwerk_open(k: Kandidaat, *, dry_run: bool) -> RijUitkomst:
    assert k.administratie_id is not None
    if dry_run:
        reden = autoboeken.beoordeel_lees_only(administratie_id=k.administratie_id, document_id=k.document_id)
        return RijUitkomst(k, UITKOMST_ZOU_BOEKEN if reden is None else UITKOMST_GEWEIGERD, reden)
    try:
        besluit = autoboeken.probeer_verkoop_autoboeken_na_intake(
            administratie_id=k.administratie_id, document_id=k.document_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Vastly-heraanbieding: autoboek van %s mislukt", k.document_id)
        return RijUitkomst(k, UITKOMST_FOUT, str(exc)[:300])
    if besluit is None:
        return RijUitkomst(k, UITKOMST_GEWEIGERD, "geen autoboek-kandidaat (status/soort/administratie)")
    if besluit.geboekt:
        return RijUitkomst(k, UITKOMST_GEBOEKT, None)
    return RijUitkomst(k, UITKOMST_GEWEIGERD, besluit.reden)


def _audit_run(resultaat: RunResultaat, *, actor_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=resultaat.run_id,
            actie=AUDIT_RUN,
            correlatie_id=resultaat.run_id,
            nieuwe_waarde={
                **resultaat.als_dict(),
                "klaar_op": resultaat.klaar_op.isoformat() if resultaat.klaar_op else None,
            },
        )


def draai(
    *,
    bron: str,
    dry_run: bool = False,
    administratie_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    opslag: DocumentOpslag | None = None,
) -> RunResultaat:
    """De motor (module-doc). `administratie_ids` beperkt (b); (a) is per definitie administratie-loos en draait
    alleen zonder filter. Dry-run schrijft niets, ook geen audit."""
    from app.documenten.service import _standaard_opslag

    opslag = opslag or _standaard_opslag()
    resultaat = RunResultaat(run_id=uuid.uuid4(), bron=bron, dry_run=dry_run, gestart_op=datetime.now(UTC))
    kandidaten: list[Kandidaat] = []
    if administratie_ids is None:
        kandidaten.extend(vind_niet_gekoppeld())
    kandidaten.extend(vind_open_in_administraties(administratie_ids))
    for k in kandidaten:
        if k.soort == SOORT_NIET_GEKOPPELD:
            resultaat.uitkomsten.append(_verwerk_niet_gekoppeld(k, dry_run=dry_run, actor_id=actor_id, opslag=opslag))
        else:
            resultaat.uitkomsten.append(_verwerk_open(k, dry_run=dry_run))
    for u in resultaat.uitkomsten:
        if u.uitkomst == UITKOMST_TOEGEWEZEN and u.kandidaat.soort == SOORT_NIET_GEKOPPELD and not dry_run:
            # Toegewezen maar niet geboekt: de weigerreden komt uit het audit van het autoboek-pad.
            administratie_id = _administratie_van(u.kandidaat.document_id)
            if administratie_id is not None:
                u.reden = _jongste_weigerreden(administratie_id, u.kandidaat.document_id)
    resultaat.klaar_op = datetime.now(UTC)
    if not dry_run:
        _audit_run(resultaat, actor_id=actor_id)
    return resultaat


def _administratie_van(document_id: uuid.UUID) -> uuid.UUID | None:
    with scoped_session(None) as session:
        document = session.get(Document, document_id)
        return document.administratie_id if document is not None else None


# ---- CLI ------------------------------------------------------------------------------------------------------------


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Nazorg (Peter 29-09): alle open Vastly-verkoopdocumenten door het automatische pad — niet-gekoppelde "
        "documenten via het entiteitenregister, open UBL's in de vastgoed-administraties via het autoboek-pad. "
        "Dry-run is de default (telling per administratie en per uitkomst); --uitvoeren boekt.",
    )
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tellen (default).")
    p.add_argument("--uitvoeren", action="store_true", dest="uitvoeren", help="Échte run (schrijft, boekt).")
    p.add_argument("--administratie", default=None, help="Beperk (b) tot één administratie (uuid of naamdeel).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run_cli(args)


def run_cli(args: argparse.Namespace) -> int:
    from app.rlz.lezen_cli import _zoek_administraties

    dry_run = not bool(getattr(args, "uitvoeren", False))
    if getattr(args, "dry_run", False) and getattr(args, "uitvoeren", False):
        print("FOUT: kies --dry-run óf --uitvoeren, niet beide", file=sys.stderr)
        return 2
    administratie_ids: list[uuid.UUID] | None = None
    if getattr(args, "administratie", None):
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"FOUT: --administratie {args.administratie!r} is niet eenduidig ({len(treffers)} treffers)",
                file=sys.stderr,
            )
            return 2
        administratie_ids = [treffers[0][0]]
    label = "DRY-RUN (niets geschreven)" if dry_run else "UITGEVOERD"
    r = draai(bron="cli", dry_run=dry_run, administratie_ids=administratie_ids)
    print(f"{COMMANDO} — {label} (run {r.run_id}): {r.kandidaten} kandidaat/kandidaten")
    for u in r.uitkomsten:
        print(f"  - [{u.kandidaat.soort}] {u.als_regel()}")
    for naam, per in r.per_administratie().items():
        print(f"  {naam}: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items())))
    per_uitkomst = ", ".join(f"{k} {v}" for k, v in r.per_uitkomst().items())
    print(f"PER UITKOMST: {per_uitkomst}" if r.uitkomsten else "PER UITKOMST: —")
    print(f"TOTAAL: {r.kandidaten} kandidaten — {label}")
    return 1 if any(u.uitkomst == UITKOMST_FOUT for u in r.uitkomsten) else 0
