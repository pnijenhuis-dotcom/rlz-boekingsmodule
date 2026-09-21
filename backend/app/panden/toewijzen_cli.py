"""CLI `pand-toewijzen` — mens-toewijzing van één RLZ-boekstuk aan een pand mét soort (VGG beslispunt 1, Peter 21-09).

Het pandenregister kende tot 21-09 geen mens-toewijzingspad: `pandenregister-afleiden --schrijf` schrijft alleen
VOORSTELLEN (`herkomst='voorstel'`), en de vertaling RLZ → Odoo neemt een pand pas als analytic + RJ-220-rol wanneer
`pand_telt` (herkomst `mens` óf zekerheid `hoog`) én de soort past (`app/migratie/vertaling.py`). Dit commando is dat
mens-pad als CLI: één boekstuk → één pand → één soort, herkomst `mens`, zekerheid `hoog`, bevestigd door de actor.

Regels: RLZ wordt uitsluitend GELEZEN (`GET <collectie>?$filter=ReceiptNumber eq '…'&$top=2`); geschreven wordt alleen
in `pand`/`pand_boeking` van de module + audit_event. Default DRY-RUN; `--schrijf` voert uit. Niets wordt stil
overschreven: een bestaande koppeling van hetzelfde document aan een ÁNDER pand = STOP (exit 2). Idempotent: dezelfde
stand nogmaals = "ongewijzigd". Productie uitsluitend op de gedeployde job-image (`gcloud run jobs execute`); nooit via
`scripts/gcp/nameting.sh` (weigerlijst)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Gebruiker
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.panden import afleiding
from app.panden.models import (
    Pand,
    PandBoeking,
    PandBoekingHerkomst,
    PandBoekingSoort,
    PandHerkomst,
    PandStatus,
    Zekerheid,
    bron_sleutel_voor,
)
from app.rlz.client import RlzApiError
from app.rlz.lezen import LeesClient, als_bedrag, als_datum, entity_van

PAND_TOEWIJZEN_COMMANDO = "pand-toewijzen"
#: Zoekvolgorde (contract C stap 2): het bewijspaar is een Receipt; bij 0 treffers óók de factuurcollecties.
COLLECTIES: tuple[str, ...] = ("Receipts", "SalesInvoices", "PurchaseInvoices")
STANDAARD_REDEN = "opdracht Peter 21-09 — Toewijzing pand + soort verkoop voor het bewijspaar (bankkoppeling 00112)"
OPDRACHT_REFERENTIE = (
    "Peter 21-09 — VGG beslispunt 1: toewijzing pand + soort verkoop (BESLISSINGEN 'VGG — BESLISPUNT 1 BESLIST')"
)
NAMENS_STANDAARD = "P. Nijenhuis (opdracht 21-09)"
AUDIT_PAND = "pand_toegewezen_mens"
AUDIT_BOEKING = "pand_boeking_toegewezen_mens"
EXIT_OK = 0
EXIT_STOP = 2


class ToewijzingStop(Exception):
    """Een STOP mét reden — de CLI print 'STOP  <reden>' en eindigt met exit 2; er is dan niets geschreven."""


@dataclass(frozen=True)
class RlzDocument:
    rlz_id: uuid.UUID
    collectie: str
    boekstuk: str
    datum: date | None
    bedrag: Decimal | None
    entity_naam: str | None

    def als_dict(self) -> dict[str, Any]:
        return {
            "rlz_id": str(self.rlz_id),
            "collectie": self.collectie,
            "boekstuk": self.boekstuk,
            "datum": self.datum.isoformat() if self.datum else None,
            "bedrag": str(self.bedrag) if self.bedrag is not None else None,
            "entity_naam": self.entity_naam,
        }


@dataclass(frozen=True)
class PandSleutel:
    """Genormaliseerde pand-code uit `afleiding.AdresVoorstel.code` — dezelfde sleutel als de afleiding, nooit een
    tweede normalisatie. `adres` is de leesbare vorm (straat + huisnummer + toevoeging), plaats/postcode apart."""

    code: str
    adres: str
    plaats: str | None
    postcode: str | None


@dataclass
class Toewijzing:
    administratie_id: uuid.UUID
    administratie_naam: str
    document: RlzDocument
    pand: PandSleutel
    soort: str
    dossier: str | None
    reden: str
    actor_id: uuid.UUID
    namens: str | None
    schrijf: bool
    pand_status: str = "?"  # nieuw | bestaand | bestaand_bijgewerkt
    boeking_status: str = "?"  # nieuw | ongewijzigd | bijgewerkt
    pand_id: uuid.UUID | None = None
    pand_boeking_id: uuid.UUID | None = None
    audit_acties: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["administratie_id"] = str(self.administratie_id)
        d["document"] = self.document.als_dict()
        d["actor_id"] = str(self.actor_id)
        d["pand_id"] = str(self.pand_id) if self.pand_id else None
        d["pand_boeking_id"] = str(self.pand_boeking_id) if self.pand_boeking_id else None
        return d


# ---- stap 2: RLZ-document lees-only ---------------------------------------------------------------------------


def zoek_rlz_document(client: LeesClient, boekstuk: str) -> RlzDocument:
    """Precies één treffer op `ReceiptNumber eq '<boekstuk>'` in de collecties op volgorde; 0 in álle collecties =
    STOP "boekstuk niet gevonden", 2 in één collectie = STOP "meerduidig". Alleen GET's."""
    filter_ = f"ReceiptNumber eq '{boekstuk.replace(chr(39), chr(39) * 2)}'"
    gelezen: list[str] = []
    for collectie in COLLECTIES:
        try:
            antwoord = client.get(collectie, params={"$filter": filter_, "$top": 2, "$expand": "Entity"})
        except RlzApiError as exc:
            raise ToewijzingStop(f"RLZ {collectie} niet leesbaar ({exc.status_code}) — {exc.body[:120]}") from exc
        rijen = antwoord.get("value", []) if isinstance(antwoord, dict) else []
        gelezen.append(f"{collectie} {len(rijen)}")
        if len(rijen) >= 2:
            raise ToewijzingStop(
                f"boekstuk {boekstuk} meerduidig in {collectie} ({len(rijen)} treffers) — eerst beoordelen"
            )
        if len(rijen) == 1:
            rij = rijen[0]
            try:
                rlz_id = uuid.UUID(str(rij.get("id")))
            except ValueError as exc:
                raise ToewijzingStop(f"boekstuk {boekstuk} in {collectie} zonder geldig RLZ-id") from exc
            _, naam = entity_van(rij)
            bedrag = als_bedrag(rij.get("TotalPayableAmount"))
            if bedrag is None:
                bedrag = als_bedrag(rij.get("BaseInvoiceAmount"))
            return RlzDocument(
                rlz_id=rlz_id,
                collectie=collectie,
                boekstuk=str(rij.get("ReceiptNumber") or boekstuk),
                datum=als_datum(rij.get("Date")) or als_datum(rij.get("BookDate")),
                bedrag=bedrag,
                entity_naam=naam,
            )
    raise ToewijzingStop(f"boekstuk {boekstuk} niet gevonden ({', '.join(gelezen)})")


# ---- stap 3: pand-sleutel -------------------------------------------------------------------------------------


def pand_sleutel(adres: str, plaats: str | None, postcode: str | None) -> PandSleutel:
    """Zelfde code als de afleiding (`AdresVoorstel.code`): "Schoffelstraat 29" → `schoffelstraat-29`. Geen herkenbaar
    adres (geen huisnummer, twee adressen) = STOP — nooit een eigen sleutel verzinnen."""
    voorstel = afleiding.adres_uit_tekst(adres)
    if voorstel is None:
        raise ToewijzingStop(f"adres {adres!r} niet als straat + huisnummer herkend — geef 'Straatnaam 12[A]'")
    plaats_uit = (plaats or voorstel.plaats or "").strip() or None
    postcode_uit = (postcode or voorstel.postcode or "").replace(" ", "").upper() or None
    return PandSleutel(code=voorstel.code, adres=voorstel.weergave_kort, plaats=plaats_uit, postcode=postcode_uit)


# ---- stap 5: actor --------------------------------------------------------------------------------------------


def zoek_actor(term: str | None) -> tuple[uuid.UUID, str | None]:
    """`--actor` e-mail of UUID → `platform.gebruiker` (platformbreed gelezen); default = de systeem-actor mét
    `namens` in de audit. Onbekende actor = STOP (nooit stil terugvallen op het systeem)."""
    if not term:
        return SYSTEEM_ACTOR_ID, NAMENS_STANDAARD
    from app.auth.normalisatie import normaliseer_e_mail

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        gebruiker: Gebruiker | None
        try:
            gebruiker = session.get(Gebruiker, uuid.UUID(term))
        except ValueError:
            gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == normaliseer_e_mail(term))).first()
        if gebruiker is None:
            raise ToewijzingStop(f"actor {term!r} onbekend in platform.gebruiker")
        return gebruiker.id, None


# ---- stap 3/4: toewijzen (DB) ---------------------------------------------------------------------------------


def _pand_waarden(p: Pand) -> dict[str, Any]:
    return {
        "code": p.code,
        "adres": p.adres,
        "plaats": p.plaats,
        "postcode": p.postcode,
        "aankoopdatum": p.aankoopdatum.isoformat() if p.aankoopdatum else None,
        "verkoopdatum": p.verkoopdatum.isoformat() if p.verkoopdatum else None,
        "notaris_dossiernummers": list(p.notaris_dossiernummers or []),
        "herkomst": p.herkomst,
        "status": p.status,
    }


def _boeking_waarden(b: PandBoeking) -> dict[str, Any]:
    return {
        "soort": b.soort,
        "herkomst": b.herkomst,
        "zekerheid": b.zekerheid,
        "reden": b.reden,
        "rlz_boekstuknummer": b.rlz_boekstuknummer,
        "rlz_collectie": b.rlz_collectie,
        "datum": b.datum.isoformat() if b.datum else None,
        "bedrag": str(b.bedrag) if b.bedrag is not None else None,
        "bevestigd_door": str(b.bevestigd_door) if b.bevestigd_door else None,
    }


def _audit(session, t: Toewijzing, *, tabel: str, record_id: uuid.UUID, actie: str, oud, nieuw, correlatie_id) -> None:  # noqa: ANN001
    nieuw = {**nieuw, "opdracht": OPDRACHT_REFERENTIE}
    if t.namens:
        nieuw["namens"] = t.namens
    record_audit_event(
        session,
        actor_id=t.actor_id,
        module="boekhouding",
        tabel=tabel,
        record_id=record_id,
        actie=actie,
        correlatie_id=correlatie_id,
        oude_waarde=oud,
        nieuwe_waarde=nieuw,
        administratie_id=t.administratie_id,
    )
    t.audit_acties.append(actie)


def voer_toewijzing_uit(t: Toewijzing) -> Toewijzing:
    """Pand hergebruiken/aanmaken + `pand_boeking` upsert, alles in één `scoped_session(aid, actor_id=actor)`.
    Dry-run doet dezelfde stappen en draait terug (`session.rollback()`), zodat de melding exact zegt wat `--schrijf`
    zou doen. De uniciteitsguard (ander pand op hetzelfde document) is een STOP vóór er iets geschreven is."""
    aid = t.administratie_id
    correlatie_id = uuid.uuid4()
    sleutel = bron_sleutel_voor(rlz_document_id=t.document.rlz_id, document_id=None)
    nu = datetime.now(UTC)
    with scoped_session(aid, actor_id=t.actor_id) as session:
        # guard eerst: hetzelfde document al aan een ánder pand gekoppeld → STOP (ook een voorstel-rij: eerst
        # beoordelen)
        anderen = session.execute(
            select(PandBoeking, Pand)
            .join(Pand, Pand.id == PandBoeking.pand_id)
            .where(PandBoeking.administratie_id == aid, PandBoeking.bron_sleutel == sleutel, Pand.code != t.pand.code)
        ).all()
        if anderen:
            codes = ", ".join(sorted(f"{p.code} ({b.herkomst}/{b.soort})" for b, p in anderen))
            session.rollback()
            raise ToewijzingStop(f"document {t.document.boekstuk} al toegewezen aan {codes} — eerst beoordelen")

        pand = session.scalars(select(Pand).where(Pand.administratie_id == aid, Pand.code == t.pand.code)).first()
        verkoop = t.soort == PandBoekingSoort.VERKOOP.value
        if pand is None:
            pand = Pand(
                administratie_id=aid,
                code=t.pand.code,
                adres=t.pand.adres,
                plaats=t.pand.plaats,
                postcode=t.pand.postcode,
                verkoopdatum=t.document.datum if verkoop else None,
                notaris_dossiernummers=[t.dossier] if t.dossier else [],
                herkomst=PandHerkomst.MENS.value,
                status=PandStatus.VERKOCHT.value if verkoop else PandStatus.BEVESTIGD.value,
            )
            session.add(pand)
            session.flush()
            t.pand_status = "nieuw"
            _audit(
                session,
                t,
                tabel="pand",
                record_id=pand.id,
                actie=AUDIT_PAND,
                oud=None,
                nieuw=_pand_waarden(pand),
                correlatie_id=correlatie_id,
            )
        else:
            oud = _pand_waarden(pand)
            if t.dossier and t.dossier not in (pand.notaris_dossiernummers or []):
                pand.notaris_dossiernummers = [*(pand.notaris_dossiernummers or []), t.dossier]
            if verkoop and pand.verkoopdatum is None and t.document.datum is not None:
                pand.verkoopdatum = t.document.datum
            if not pand.plaats and t.pand.plaats:
                pand.plaats = t.pand.plaats
            if not pand.postcode and t.pand.postcode:
                pand.postcode = t.pand.postcode
            session.flush()
            nieuw = _pand_waarden(pand)
            if nieuw == oud:
                t.pand_status = "bestaand"
            else:
                t.pand_status = "bestaand_bijgewerkt"
                _audit(
                    session,
                    t,
                    tabel="pand",
                    record_id=pand.id,
                    actie=AUDIT_PAND,
                    oud=oud,
                    nieuw=nieuw,
                    correlatie_id=correlatie_id,
                )
        t.pand_id = pand.id

        rij = session.scalars(
            select(PandBoeking).where(
                PandBoeking.administratie_id == aid, PandBoeking.bron_sleutel == sleutel, PandBoeking.pand_id == pand.id
            )
        ).first()
        if rij is None:
            rij = PandBoeking(
                administratie_id=aid,
                pand_id=pand.id,
                rlz_document_id=t.document.rlz_id,
                rlz_boekstuknummer=t.document.boekstuk,
                rlz_collectie=t.document.collectie,
                bron_sleutel=sleutel,
                soort=t.soort,
                herkomst=PandBoekingHerkomst.MENS.value,
                zekerheid=Zekerheid.HOOG.value,
                reden=t.reden,
                datum=t.document.datum,
                bedrag=t.document.bedrag,
                bevestigd_door=t.actor_id,
                bevestigd_op=nu,
            )
            session.add(rij)
            session.flush()
            t.boeking_status = "nieuw"
            _audit(
                session,
                t,
                tabel="pand_boeking",
                record_id=rij.id,
                actie=AUDIT_BOEKING,
                oud=None,
                nieuw={**_boeking_waarden(rij), "pand_code": pand.code, "rlz_document_id": str(t.document.rlz_id)},
                correlatie_id=correlatie_id,
            )
        else:
            oud_b = _boeking_waarden(rij)
            doel = {
                **oud_b,
                "soort": t.soort,
                "herkomst": PandBoekingHerkomst.MENS.value,
                "zekerheid": Zekerheid.HOOG.value,
                "reden": t.reden,
                "rlz_boekstuknummer": t.document.boekstuk,
                "rlz_collectie": t.document.collectie,
                "datum": t.document.datum.isoformat() if t.document.datum else None,
                "bedrag": str(t.document.bedrag) if t.document.bedrag is not None else None,
            }
            if doel == oud_b:
                t.boeking_status = "ongewijzigd"
            else:
                rij.soort, rij.herkomst, rij.zekerheid, rij.reden = (
                    t.soort,
                    PandBoekingHerkomst.MENS.value,
                    Zekerheid.HOOG.value,
                    t.reden,
                )
                rij.rlz_boekstuknummer, rij.rlz_collectie = t.document.boekstuk, t.document.collectie
                rij.datum, rij.bedrag = t.document.datum, t.document.bedrag
                rij.bevestigd_door, rij.bevestigd_op = t.actor_id, nu
                session.flush()
                t.boeking_status = "bijgewerkt"
                _audit(
                    session,
                    t,
                    tabel="pand_boeking",
                    record_id=rij.id,
                    actie=AUDIT_BOEKING,
                    oud=oud_b,
                    nieuw={**_boeking_waarden(rij), "pand_code": pand.code, "rlz_document_id": str(t.document.rlz_id)},
                    correlatie_id=correlatie_id,
                )
        t.pand_boeking_id = rij.id
        if not t.schrijf:
            session.rollback()
    return t


# ---- weergave -------------------------------------------------------------------------------------------------


def als_tekst(t: Toewijzing) -> str:
    d = t.document
    kop = "GESCHREVEN" if t.schrijf else "DRY-RUN — niets geschreven"
    regels = [
        f"pand-toewijzen — {t.administratie_naam} ({t.administratie_id}) — {kop}",
        f"- RLZ-document: {d.boekstuk} in {d.collectie} · id {d.rlz_id} · datum {d.datum or '?'} · "
        f"bedrag € {d.bedrag if d.bedrag is not None else '?'} · relatie {d.entity_naam or '—'}",
        f"- pand: {t.pand.code} — {t.pand.adres}{', ' + t.pand.plaats if t.pand.plaats else ''}"
        f"{' ' + t.pand.postcode if t.pand.postcode else ''} · dossier {t.dossier or '—'} → {t.pand_status}",
        f"- pand_boeking: soort {t.soort} · herkomst mens · zekerheid hoog · bron rlz:{d.rlz_id} → {t.boeking_status}",
        f"- actor: {t.actor_id}{' namens ' + t.namens if t.namens else ''} · reden: {t.reden}",
        f"- audit: {', '.join(t.audit_acties) if t.audit_acties else 'geen (ongewijzigd)'}"
        + ("" if t.schrijf else " — in dry-run teruggedraaid"),
    ]
    return "\n".join(regels)


# ---- argparse -------------------------------------------------------------------------------------------------


def register_pand_toewijzen(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        PAND_TOEWIJZEN_COMMANDO,
        help=(
            "Mens-toewijzing van één RLZ-boekstuk aan een pand mét soort (herkomst mens, zekerheid hoog). RLZ alleen "
            "gelezen; schrijft pand/pand_boeking + audit. Default dry-run; --schrijf voert uit. Nooit via nameting.sh."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam van de administratie.")
    p.add_argument("--boekstuk", required=True, help="RLZ-boekstuknummer, bv. RLZ-01-00000082 (ReceiptNumber).")
    p.add_argument("--soort", required=True, choices=[s.value for s in PandBoekingSoort], help="Soort pand-boeking.")
    p.add_argument("--adres", required=True, help='Straat + huisnummer, bv. "Schoffelstraat 29".')
    p.add_argument("--plaats", default=None, help="Plaats (leesbare vorm; hoort niet in de pand-code).")
    p.add_argument("--postcode", default=None)
    p.add_argument("--dossier", default=None, help="Notaris-dossiernummer, bv. 2026.079950.01.")
    p.add_argument("--reden", default=STANDAARD_REDEN, help="Reden in pand_boeking + audit.")
    p.add_argument("--actor", default=None, help="E-mail of UUID van de mens; default systeem-actor mét 'namens'.")
    p.add_argument("--schrijf", action="store_true", help="Uitvoeren (zonder deze vlag: dry-run).")
    p.add_argument("--json-uit", dest="json_uit", default=None, help="Pad voor een JSON-uitkomst.")


def run_pand_toewijzen(args: argparse.Namespace) -> int:
    from pathlib import Path

    from app.geheugen.btw_default_cli import _zoek_administratie
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return EXIT_STOP
    aid, naam = gevonden
    try:
        sleutel = pand_sleutel(args.adres, args.plaats, args.postcode)
        actor_id, namens = zoek_actor(args.actor)
        try:
            rid = rlz_admin_id_voor(aid)
            client = client_voor_rlz_admin_id(rid).for_administration(rid)
        except GeenRlzCredentials as exc:
            raise ToewijzingStop(f"geen RLZ-credential voor {naam}: {exc}") from exc
        try:
            document = zoek_rlz_document(client, args.boekstuk)
        finally:
            if hasattr(client, "close"):
                client.close()
        t = voer_toewijzing_uit(
            Toewijzing(
                administratie_id=aid,
                administratie_naam=naam,
                document=document,
                pand=sleutel,
                soort=args.soort,
                dossier=args.dossier,
                reden=args.reden,
                actor_id=actor_id,
                namens=namens,
                schrijf=bool(args.schrijf),
            )
        )
    except ToewijzingStop as exc:
        print(f"STOP  {exc}", file=sys.stderr)
        return EXIT_STOP
    print(als_tekst(t))
    if args.json_uit:
        Path(args.json_uit).write_text(json.dumps(t.als_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON geschreven: {args.json_uit}")
    return EXIT_OK
