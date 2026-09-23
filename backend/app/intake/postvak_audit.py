"""Dubbele mailbox-audit, LEES-ONLY (Peter 22-09 avond: "laat hem de mailbox goed controleren welke facturen wel en
niet zijn doorgekomen, dubbele controle"; opdracht D). Drie lagen per bronbericht in facturen@kempengroep.nl:

1. **Bron** — élk bericht mét factuurbijlage (PDF/UBL-XML/afbeelding) in INBOX + spam-map + "Alle e-mail":
   Message-ID, datum, afzender, onderwerp, bestandsnamen + sha256 per bijlage.
2. **Doorgifte** — dezelfde set in facturen@ak-nijenhuis.nl: koppeling op het oorspronkelijke Message-ID (de
   Gmail-auto-forward behoudt 'm, of zet 'm in References/In-Reply-To), anders op bijlage-sha256 (handmatige
   "Fwd:" = nieuw Message-ID), als laatste redmiddel op bestandsnaam — élke koppelvorm draagt zijn label.
   Per bronbericht: aangekomen ja/nee, map (INBOX/Spam), gelezen-vlag.
3. **Module** — `intake_bericht.message_id` (bron- óf doorgifte-Message-ID) en `detail.bijlage_hashes` → documenten
   (status, administratie, boekstuk) via de verwerkt-administratie en één query per administratie (RLS).

Uitvalcategorieën: (a) nooit doorgestuurd, (b) aangekomen in Spam en daardoor overgeslagen, (c) aangekomen in INBOX
maar niet verwerkt (gelezen-vlag vóór de intake / andere oorzaak). Plus de omgekeerde controle: berichten in
ak-nijenhuis mét factuurbijlage zonder module-spoor die NIET uit kempengroep komen (rechtstreekse leveranciers).
De vergelijking (`koppel`) is pure code — testbaar zonder IMAP of DB. Geen PII buiten afzender/onderwerp/bestandsnaam.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from app.intake.eml import GeenGeldigeEml, parse_eml
from app.intake.postvak import INBOX, ImapInstellingen, PostvakKop, PostvakVerbinding

ALLE_MAIL = "[Gmail]/All Mail"
_FACTUUR_EXT = (".pdf", ".xml", ".jpg", ".jpeg", ".png", ".heic")

KOPPEL_MESSAGE_ID = "message_id"
KOPPEL_REFERENCES = "references"
KOPPEL_SHA256 = "bijlage_sha256"
KOPPEL_BESTANDSNAAM = "bestandsnaam"

UITVAL_NIET_DOORGESTUURD = "a_niet_doorgestuurd"
UITVAL_SPAM_OVERGESLAGEN = "b_spam_overgeslagen"
UITVAL_INBOX_NIET_VERWERKT = "c_inbox_niet_verwerkt"


@dataclass(frozen=True)
class Bijlage:
    bestandsnaam: str
    sha256: str


@dataclass(frozen=True)
class Bericht:
    """Eén bericht mét factuurbijlage(n) in een postvak (bron of doorgifte)."""

    kanaal: str
    message_id: str | None
    uid: str
    map: str
    datum: datetime | None
    afzender: str | None
    onderwerp: str | None
    gelezen: bool
    bijlagen: tuple[Bijlage, ...]
    references: tuple[str, ...] = ()

    @property
    def hashes(self) -> frozenset[str]:
        return frozenset(b.sha256 for b in self.bijlagen)

    @property
    def bestandsnamen(self) -> frozenset[str]:
        return frozenset(b.bestandsnaam.lower() for b in self.bijlagen)

    @property
    def uit_spam(self) -> bool:
        return self.map not in (INBOX, ALLE_MAIL)


@dataclass(frozen=True)
class ModuleSpoor:
    """Wat de module van dit bericht weet: intake-bericht + documenten (status/administratie/boekstuk)."""

    intake_bericht_id: uuid.UUID | None
    kanaal: str | None
    # (status, administratie, boekstuk, bestandsnaam)
    documenten: tuple[tuple[str, str | None, str | None, str | None], ...]
    via: str  # 'message_id' | 'bijlage_sha256' | ''

    @property
    def aanwezig(self) -> bool:
        return self.intake_bericht_id is not None or bool(self.documenten)

    @property
    def samenvatting(self) -> str:
        if not self.aanwezig:
            return "geen module-spoor"
        if not self.documenten:
            return "intake-bericht zonder document (alle bijlagen niet verwerkbaar/genegeerd)"
        return "; ".join(
            f"{status}" + (f" · {adm}" if adm else " · verzamelbak") + (f" · {boekstuk}" if boekstuk else "")
            for status, adm, boekstuk, _ in self.documenten
        )


@dataclass(frozen=True)
class Koppeling:
    bron: Bericht
    doorgifte: Bericht | None
    koppelvorm: str | None
    module: ModuleSpoor

    @property
    def uitval(self) -> str | None:
        if self.module.aanwezig:
            return None
        if self.doorgifte is None:
            return UITVAL_NIET_DOORGESTUURD
        if self.doorgifte.uit_spam:
            return UITVAL_SPAM_OVERGESLAGEN
        return UITVAL_INBOX_NIET_VERWERKT

    @property
    def oorzaak(self) -> str:
        u = self.uitval
        if u is None:
            return "ok"
        if u == UITVAL_NIET_DOORGESTUURD:
            return "nooit doorgestuurd (Gmail-forward: eigen spam-/duplicaatclassificatie of forward stond niet aan)"
        if u == UITVAL_SPAM_OVERGESLAGEN:
            return "aangekomen in Spam (SPF-breuk door de forward) — de intake las alleen INBOX"
        d = self.doorgifte
        if d is not None and d.gelezen:
            return "aangekomen in INBOX maar al gelezen vóór de intake 'm zag (gelezen-vlag was de administratie)"
        return "aangekomen in INBOX, ongelezen, toch geen module-spoor — verwerking niet gelopen/gestrand (log lezen)"


@dataclass
class AuditRapport:
    sinds: date
    kanaal_bron: str
    kanaal_doel: str
    bron: list[Bericht] = field(default_factory=list)
    doorgifte: list[Bericht] = field(default_factory=list)
    koppelingen: list[Koppeling] = field(default_factory=list)
    #: Omgekeerde controle: doorgifte-berichten mét factuurbijlage zonder module-spoor die niet uit de bron komen.
    rechtstreeks_zonder_spoor: list[tuple[Bericht, ModuleSpoor]] = field(default_factory=list)
    mappen_gelezen: dict[str, dict[str, int]] = field(default_factory=dict)

    def tel(self) -> dict[str, int]:
        t = {"bron": len(self.bron), "aangekomen": 0, "module": 0, UITVAL_NIET_DOORGESTUURD: 0,
             UITVAL_SPAM_OVERGESLAGEN: 0, UITVAL_INBOX_NIET_VERWERKT: 0}
        for k in self.koppelingen:
            if k.doorgifte is not None:
                t["aangekomen"] += 1
            if k.module.aanwezig:
                t["module"] += 1
            if k.uitval:
                t[k.uitval] += 1
        return t


# ---- pure vergelijking ---------------------------------------------------------------------------------------------


def is_factuurbijlage(bestandsnaam: str, content_type: str) -> bool:
    naam = (bestandsnaam or "").lower()
    return naam.endswith(_FACTUUR_EXT) or content_type in ("application/pdf", "application/xml", "text/xml")


def bericht_uit_eml(kop: PostvakKop, inhoud: bytes, *, kanaal: str) -> Bericht | None:
    """Parseert een .eml tot een audit-`Bericht`; None als er geen factuurbijlage in zit (geen document → niet in
    de audit) of het bericht niet parsebaar is."""
    try:
        mail = parse_eml(inhoud)
    except GeenGeldigeEml:
        return None
    bijlagen = tuple(
        Bijlage(bestandsnaam=b.bestandsnaam, sha256=hashlib.sha256(b.inhoud).hexdigest())
        for b in mail.bijlagen
        if not b.inline and is_factuurbijlage(b.bestandsnaam, b.content_type)
    )
    if not bijlagen:
        return None
    return Bericht(
        kanaal=kanaal,
        message_id=mail.message_id or kop.message_id,
        uid=kop.uid,
        map=kop.map,
        datum=mail.ontvangen_op or kop.datum,
        afzender=mail.afzender or kop.afzender,
        onderwerp=mail.onderwerp or kop.onderwerp,
        gelezen=kop.gelezen,
        bijlagen=bijlagen,
        references=kop.references,
    )


def ontdubbel(berichten: list[Bericht]) -> list[Bericht]:
    """Eén bericht kan in INBOX/Spam én "Alle e-mail" staan: houd per Message-ID (anders per hash-set) de meest
    specifieke map (INBOX/Spam boven Alle e-mail) en 'gelezen' als één exemplaar gelezen is."""
    volgorde = {INBOX: 0, ALLE_MAIL: 2}
    per_sleutel: dict[str, Bericht] = {}
    for b in berichten:
        sleutel = b.message_id or f"hash:{'|'.join(sorted(b.hashes))}"
        bestaand = per_sleutel.get(sleutel)
        if bestaand is None:
            per_sleutel[sleutel] = b
            continue
        kies = b if volgorde.get(b.map, 1) < volgorde.get(bestaand.map, 1) else bestaand
        gelezen = b.gelezen or bestaand.gelezen
        per_sleutel[sleutel] = Bericht(**{**kies.__dict__, "gelezen": gelezen})
    return sorted(per_sleutel.values(), key=lambda b: b.datum.replace(tzinfo=None) if b.datum else datetime.min)


def zoek_doorgifte(bron: Bericht, doorgiften: list[Bericht]) -> tuple[Bericht | None, str | None]:
    """Koppelvolgorde: Message-ID exact → bron-Message-ID in References/In-Reply-To → gelijke bijlage-sha256 →
    gelijke bestandsnaam (laatste redmiddel, zichtbaar gelabeld)."""
    if bron.message_id:
        for d in doorgiften:
            if d.message_id == bron.message_id:
                return d, KOPPEL_MESSAGE_ID
        for d in doorgiften:
            if bron.message_id in d.references:
                return d, KOPPEL_REFERENCES
    for d in doorgiften:
        if bron.hashes & d.hashes:
            return d, KOPPEL_SHA256
    for d in doorgiften:
        if bron.bestandsnamen & d.bestandsnamen:
            return d, KOPPEL_BESTANDSNAAM
    return None, None


def koppel(
    bron: list[Bericht],
    doorgifte: list[Bericht],
    module_spoor: Callable[[Bericht, Bericht | None], ModuleSpoor],
) -> tuple[list[Koppeling], list[tuple[Bericht, ModuleSpoor]]]:
    """Pure kern van de audit: per bronbericht de doorgifte + het module-spoor; daarna de omgekeerde controle."""
    koppelingen: list[Koppeling] = []
    gekoppeld: set[tuple[str, str]] = set()
    for b in bron:
        d, vorm = zoek_doorgifte(b, doorgifte)
        if d is not None:
            gekoppeld.add((d.map, d.uid))
        koppelingen.append(Koppeling(bron=b, doorgifte=d, koppelvorm=vorm, module=module_spoor(b, d)))
    rechtstreeks: list[tuple[Bericht, ModuleSpoor]] = []
    for d in doorgifte:
        if (d.map, d.uid) in gekoppeld:
            continue
        spoor = module_spoor(d, None)
        if not spoor.aanwezig:
            rechtstreeks.append((d, spoor))
    return koppelingen, rechtstreeks


# ---- IMAP-verzameling + module-lookup (job-image) ------------------------------------------------------------------


def lees_postvak(kanaal: str, *, sinds: date, mappen: tuple[str, ...]) -> tuple[list[Bericht], dict[str, int]]:
    """Alle berichten mét factuurbijlage in de gegeven mappen vanaf `sinds` — BODY.PEEK, zet geen vlag. Een map die
    niet bestaat (bv. geen Gmail) wordt zichtbaar geteld als -1, nooit stil overgeslagen."""
    instellingen = ImapInstellingen.voor_kanaal(kanaal)
    berichten: list[Bericht] = []
    telling: dict[str, int] = {}
    with PostvakVerbinding(instellingen) as verbinding:
        for map in mappen:
            try:
                koppen = verbinding.koppen(map, sinds=sinds)
            except Exception as exc:  # noqa: BLE001 — zichtbaar per map, de andere mappen lopen door
                telling[map] = -1
                print(f"WAARSCHUWING map {map} in {kanaal} niet leesbaar: {exc}")
                continue
            telling[map] = len(koppen)
            for kop in koppen:
                b = bericht_uit_eml(kop, verbinding.bericht(kop), kanaal=kanaal)
                if b is not None:
                    berichten.append(b)
    return ontdubbel(berichten), telling


def module_spoor_uit_db() -> Callable[[Bericht, Bericht | None], ModuleSpoor]:
    """Bouwt de lookup één keer (alle intake-berichten mét message_id/hashes + documenten per administratie in eigen
    scope) en geeft de pure toets terug."""
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, Document
    from app.intake.models import IntakeBericht

    per_message_id: dict[str, tuple[uuid.UUID, str]] = {}
    per_hash: dict[str, tuple[uuid.UUID, str]] = {}
    with scoped_session(None) as session:
        for rij in session.scalars(select(IntakeBericht)).all():
            if rij.message_id:
                per_message_id[rij.message_id] = (rij.id, rij.kanaal)
            for h in (rij.detail or {}).get("bijlage_hashes") or []:
                per_hash.setdefault(h, (rij.id, rij.kanaal))
        administraties = session.execute(select(Administratie.id, Administratie.naam)).all()
    documenten_per_bericht: dict[uuid.UUID, list[tuple[str, str | None, str | None, str | None]]] = {}
    documenten_per_hash: dict[str, list[tuple[str, str | None, str | None, str | None]]] = {}
    scopes: list[tuple[uuid.UUID | None, str | None]] = [(None, None), *((aid, naam) for aid, naam in administraties)]
    for aid, naam in scopes:
        with scoped_session(aid) as session:
            q = select(Document, Boekvoorstel.rlz_boekstuknummer).outerjoin(
                Boekvoorstel, Boekvoorstel.document_id == Document.id
            )
            if aid is None:
                q = q.where(Document.administratie_id.is_(None))
            else:
                q = q.where(Document.administratie_id == aid)
            for doc, boekstuk in session.execute(q).all():
                status = str(doc.status.value if hasattr(doc.status, "value") else doc.status)
                rij = (status, naam, boekstuk, doc.bestandsnaam)
                if doc.intake_bericht_id is not None:
                    documenten_per_bericht.setdefault(doc.intake_bericht_id, []).append(rij)
                documenten_per_hash.setdefault(doc.sha256_hash, []).append(rij)

    def toets(bron: Bericht, doorgifte: Bericht | None) -> ModuleSpoor:
        for mid in (bron.message_id, doorgifte.message_id if doorgifte else None):
            if mid and mid in per_message_id:
                bid, kanaal = per_message_id[mid]
                return ModuleSpoor(bid, kanaal, tuple(documenten_per_bericht.get(bid, [])), KOPPEL_MESSAGE_ID)
        for h in sorted(bron.hashes | (doorgifte.hashes if doorgifte else frozenset())):
            if h in per_hash:
                bid, kanaal = per_hash[h]
                return ModuleSpoor(bid, kanaal, tuple(documenten_per_bericht.get(bid, [])), KOPPEL_SHA256)
            if h in documenten_per_hash:
                return ModuleSpoor(None, None, tuple(documenten_per_hash[h]), KOPPEL_SHA256)
        return ModuleSpoor(None, None, (), "")

    return toets


def voer_uit(*, sinds: date, kanaal_bron: str, kanaal_doel: str, detail: bool = False) -> AuditRapport:
    rapport = AuditRapport(sinds=sinds, kanaal_bron=kanaal_bron, kanaal_doel=kanaal_doel)
    mappen = (INBOX, PostvakVerbinding.standaard_mappen()[1], ALLE_MAIL)
    rapport.bron, rapport.mappen_gelezen[kanaal_bron] = lees_postvak(kanaal_bron, sinds=sinds, mappen=mappen)
    rapport.doorgifte, rapport.mappen_gelezen[kanaal_doel] = lees_postvak(kanaal_doel, sinds=sinds, mappen=mappen)
    rapport.koppelingen, rapport.rechtstreeks_zonder_spoor = koppel(
        rapport.bron, rapport.doorgifte, module_spoor_uit_db()
    )
    return rapport


def rapport_regels(rapport: AuditRapport, *, detail: bool = False) -> list[str]:
    t = rapport.tel()
    regels = [
        f"== intake-postvak-audit — bron {rapport.kanaal_bron} → doorgifte {rapport.kanaal_doel} → module, sinds "
        f"{rapport.sinds.isoformat()} (lees-only, BODY.PEEK) ==",
        "Mappen gelezen (berichten in het venster, mét en zonder bijlage; -1 = map niet leesbaar): "
        + "; ".join(f"{k}: " + ", ".join(f"{m}={n}" for m, n in v.items()) for k, v in rapport.mappen_gelezen.items()),
        f"Bronberichten mét factuurbijlage: {t['bron']} · aangekomen in {rapport.kanaal_doel}: {t['aangekomen']} · "
        f"met module-spoor: {t['module']}",
        f"Uitval (a) nooit doorgestuurd: {t[UITVAL_NIET_DOORGESTUURD]}",
        f"Uitval (b) aangekomen in Spam, overgeslagen: {t[UITVAL_SPAM_OVERGESLAGEN]}",
        f"Uitval (c) aangekomen in INBOX, niet verwerkt: {t[UITVAL_INBOX_NIET_VERWERKT]}",
        f"Omgekeerd — rechtstreeks in {rapport.kanaal_doel} mét factuurbijlage zonder module-spoor: "
        f"{len(rapport.rechtstreeks_zonder_spoor)}",
    ]
    uitval = [k for k in rapport.koppelingen if k.uitval]
    if uitval:
        regels.append("")
        regels.append(
            "UITVAL per bronbericht (datum · afzender · onderwerp · bestanden → doorgifte → module → oorzaak):"
        )
        for k in uitval:
            regels.append(_rij(k))
    if rapport.rechtstreeks_zonder_spoor:
        regels.append("")
        regels.append("RECHTSTREEKS zonder module-spoor (datum · map · gelezen · afzender · onderwerp · bestanden):")
        for d, _ in rapport.rechtstreeks_zonder_spoor:
            regels.append(
                f"  {_dat(d.datum)} · {d.map} · {'gelezen' if d.gelezen else 'ongelezen'} · {d.afzender or '?'} · "
                f"{(d.onderwerp or '')[:60]} · {', '.join(b.bestandsnaam for b in d.bijlagen)} · "
                f"{d.message_id or 'geen Message-ID'}"
            )
    if detail:
        regels.append("")
        regels.append("ALLE bronberichten:")
        for k in rapport.koppelingen:
            regels.append(_rij(k))
    totaal_uitval = t[UITVAL_NIET_DOORGESTUURD] + t[UITVAL_SPAM_OVERGESLAGEN] + t[UITVAL_INBOX_NIET_VERWERKT]
    regels.append("")
    regels.append(
        f"Oordeel: {'GROEN' if totaal_uitval == 0 and not rapport.rechtstreeks_zonder_spoor else 'ROOD'} — "
        f"{t['bron']} bronberichten, {totaal_uitval} zonder module-spoor (a {t[UITVAL_NIET_DOORGESTUURD]} / b "
        f"{t[UITVAL_SPAM_OVERGESLAGEN]} / c {t[UITVAL_INBOX_NIET_VERWERKT]}), {len(rapport.rechtstreeks_zonder_spoor)} "
        "rechtstreeks zonder spoor"
    )
    return regels


def _dat(d: datetime | None) -> str:
    return d.strftime("%d-%m-%Y %H:%M") if d else "?"


def _rij(k: Koppeling) -> str:
    b = k.bron
    d = k.doorgifte
    doorgifte = (
        f"→ {d.map} ({'gelezen' if d.gelezen else 'ongelezen'}, koppel={k.koppelvorm})" if d else "→ NIET aangekomen"
    )
    return (
        f"  {_dat(b.datum)} · {b.afzender or '?'} · {(b.onderwerp or '')[:60]} · "
        f"{', '.join(x.bestandsnaam for x in b.bijlagen)} {doorgifte} → module: {k.module.samenvatting} → {k.oorzaak}"
        f" · {b.message_id or 'geen Message-ID'}"
    )
