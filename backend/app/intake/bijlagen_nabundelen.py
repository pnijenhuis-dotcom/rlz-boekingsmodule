"""Nazorg `bijlagen-nabundelen` (Peter 02-10 "één mail = één document — bijlagen blijven bij de factuur"; BESLISSINGEN
"BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)"): de al GESPLITSTE
documenten van vóór 02-10 volgens dezelfde mail-regel alsnog samenvoegen.

Per `intake_bericht` (Message-ID) mét ≥ 2 documenten: élk document wordt deterministisch geklasseerd zoals de intake dat
sinds 02-10 doet (`app/intake/bijlage_herkenning.py`: UBL = factuur; PDF mét factuursignalen = factuur; PDF zonder
tekstlaag / kassarapport = kandidaat = factuur; PDF mét tekstlaag zonder factuursignalen, spreadsheet, csv/doc, foto =
bijlage). Precies één factuur → élke open bijlage eraan; meerdere facturen → treffer op factuurnummer/werknummer
(UBL `cbc:ID`/`cbc:Note`, anders de opgeslagen referentie) in bestandsnaam of tekstlaag, geen eenduidige treffer → bij
álle facturen mét rol `bijlage_niet_eenduidig` (de tweede en volgende factuur krijgen een KOPIE van het bestand als
bijlage-rij — liever dubbel dan kwijt); nul facturen → bericht overgeslagen.

Bijlage-documenten krijgen status `samengevoegd` mét verwijzing (`app/documenten/bijlagen.koppel_document_als_bijlage`:
tijdlijn beide kanten, audit `bijlage_gekoppeld`, `vorige_status` voor ongedaan) — nooit verwijderd, terugdraaibaar
(`--ongedaan <bijlage-document-id>`). Alleen OPEN bijlage-documenten (ontvangen/te_controleren/handmatig_afmaken/
klaar_om_te_boeken/niet_toegewezen); een document waar een mens al over oordeelde (vraag, accordering, geboekt,
afgewezen) wordt zichtbaar overgeslagen mét reden. Een al GEBOEKTE factuur krijgt de bijlage alsnog als RLZ-upload
(`PurchaseInvoices/{herboeking-GUID}` resp. `SalesInvoices/{verkoop_rlz_id}`, idempotent op bestandsnaam; Odoo =
overgeslagen mét reden). Scope: élk document in zijn eigen RLS-scope; een bijlage in de verzamelbak (NULL) verhuist
mee naar de administratie van de factuur, een bijlage in een ándere administratie wordt overgeslagen ("eerst
verplaatsen").

Dry-run is de default (lees-only, nameting-allowlist): lijst "factuur ← bijlagen" per administratie + totalen; de
échte run = `gcloud run jobs execute rlz-reconciliatie --args=-m,app.cli,bijlagen-nabundelen,--uitvoeren` ná Peters
"ja".
"""

from __future__ import annotations

import argparse
import base64
import logging
import re
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import bijlagen as bijlagen_module
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus
from app.documenten.rlz_ids import rlz_bijlage_upload_id, rlz_herboeking_id
from app.documenten.storage import DocumentOpslag
from app.intake import bijlage_herkenning as bh
from app.intake.models import IntakeBericht

logger = logging.getLogger(__name__)

COMMANDO = "bijlagen-nabundelen"
#: Uitkomsten in `intake_bericht.detail.bijlagen` waarachter een document-rij staat.
_MET_DOCUMENT = frozenset({"toegewezen", "verzamelbak", "splitsingsvoorstel", "dubbel"})
#: Bijlage-document dat nog samengevoegd mag worden (statusmachine → samengevoegd).
BIJLAGE_OPEN = frozenset(
    {
        DocumentStatus.ONTVANGEN,
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.NIET_TOEGEWEZEN,
    }
)
#: Factuur-documenten die niet (meer) als drager tellen.
_FACTUUR_UITGESLOTEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
        DocumentStatus.GESPLITST,
        DocumentStatus.AFGEWEZEN,
    }
)

UITKOMST_KANDIDAAT = "kandidaat"
UITKOMST_GEKOPPELD = "gekoppeld"
UITKOMST_GEKOPPELD_UPLOAD_FOUT = "gekoppeld_upload_mislukt"
UITKOMST_OVERGESLAGEN = "overgeslagen"
UITKOMST_MISLUKT = "mislukt"


@dataclass(frozen=True)
class DocRef:
    document_id: uuid.UUID
    administratie_id: uuid.UUID | None
    administratie_naam: str
    bestandsnaam: str
    status: DocumentStatus
    soort: str
    klasse: str
    klasse_reden: str
    sleutels: frozenset[str] = frozenset()
    referentie: str | None = None
    geboekt: bool = False
    boek_cyclus: int = 0

    @property
    def scope_label(self) -> str:
        return self.administratie_naam if self.administratie_id else "verzamelbak"


@dataclass(frozen=True)
class BijlageKandidaat:
    bericht_id: uuid.UUID
    bijlage: DocRef
    doelen: tuple[DocRef, ...]
    niet_eenduidig: bool
    overgeslagen_reden: str | None = None


@dataclass(frozen=True)
class Uitkomst:
    kandidaat: BijlageKandidaat
    uitkomst: str
    reden: str | None = None
    upload: str | None = None

    def als_regel(self) -> str:
        k = self.kandidaat
        doelen = ", ".join(f"{d.bestandsnaam}{' (geboekt)' if d.geboekt else ''}" for d in k.doelen) or "—"
        kern = f"{doelen} ← {k.bijlage.bestandsnaam} [{k.bijlage.klasse_reden}]: {self.uitkomst}"
        if k.niet_eenduidig:
            kern += " (niet eenduidig)"
        if self.reden:
            kern += f" — {self.reden}"
        if self.upload:
            kern += f" [upload: {self.upload}]"
        return kern


@dataclass
class Telling:
    berichten: int = 0
    kandidaten: int = 0
    gekoppeld: int = 0
    overgeslagen: int = 0
    mislukt: int = 0
    uitkomsten: list[Uitkomst] = field(default_factory=list)
    overgeslagen_redenen: dict[str, int] = field(default_factory=dict)

    def registreer(self, u: Uitkomst) -> None:
        self.uitkomsten.append(u)
        if u.uitkomst in (UITKOMST_GEKOPPELD, UITKOMST_GEKOPPELD_UPLOAD_FOUT):
            self.gekoppeld += 1
        elif u.uitkomst == UITKOMST_OVERGESLAGEN:
            self.overgeslagen += 1
            sleutel = (u.reden or "onbekend").split(" (")[0][:60]
            self.overgeslagen_redenen[sleutel] = self.overgeslagen_redenen.get(sleutel, 0) + 1
        elif u.uitkomst == UITKOMST_MISLUKT:
            self.mislukt += 1

    def per_administratie(self) -> dict[str, dict[str, int]]:
        uit: dict[str, dict[str, int]] = {}
        for u in self.uitkomsten:
            naam = u.kandidaat.doelen[0].scope_label if u.kandidaat.doelen else u.kandidaat.bijlage.scope_label
            per = uit.setdefault(naam, {})
            per[u.uitkomst] = per.get(u.uitkomst, 0) + 1
        return uit


# ---- kandidaten ---------------------------------------------------------------------------------------------------


def _administraties() -> dict[uuid.UUID, str]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        return dict(session.execute(select(Administratie.id, Administratie.naam)).all())


def _scope_uit_detail(rij: dict) -> uuid.UUID | None:
    detail = str(rij.get("detail") or "")
    if rij.get("uitkomst") != "toegewezen":
        return None
    m = bh_uuid.search(detail)
    return uuid.UUID(m.group(0)) if m else None


bh_uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _klasseer(document: Document, inhoud_lezer: Callable[[], bytes]) -> bh.Herkenning:
    naam = document.bestandsnaam.lower()
    if naam.endswith(".xml"):
        return bh.Herkenning(bh.KLASSE_FACTUUR, "UBL/XML = factuur")
    if document.bron_opslag_pad is not None:
        # Een PDF-beeld van een UBL (gebundeld) of een omgezette foto met origineel: het document ís de factuur/bron.
        if naam.endswith(".pdf"):
            return bh.Herkenning(bh.KLASSE_KANDIDAAT, "document mét bronbestand — bestaande keten")
    if naam.endswith(".pdf"):
        try:
            return bh.herken_pdf(inhoud_lezer())
        except Exception as exc:  # noqa: BLE001 — onleesbaar = kandidaat (nooit raden dat het een bijlage is)
            return bh.Herkenning(bh.KLASSE_KANDIDAAT, f"PDF niet leesbaar ({type(exc).__name__})")
    suffix = Path(naam).suffix
    if suffix in (".xls", ".xlsx"):
        from app.omzet.bronnen import herken_bron

        try:
            if herken_bron(document.bestandsnaam, inhoud_lezer()) is not None:
                return bh.Herkenning(bh.KLASSE_KANDIDAAT, "omzetbron-spreadsheet — eigen route")
        except Exception:  # noqa: BLE001
            pass
        return bh.Herkenning(bh.KLASSE_BIJLAGE, "spreadsheet (geen omzetbron) bij de factuur")
    if suffix in bh.BIJLAGE_EXTENSIES:
        return bh.Herkenning(bh.KLASSE_BIJLAGE, f"{suffix}-bestand bij de factuur")
    from app.documenten.afbeelding import is_afbeelding

    if is_afbeelding(document.bestandsnaam, None):
        return bh.Herkenning(bh.KLASSE_BIJLAGE, "foto/afbeelding bij de factuur")
    return bh.Herkenning(bh.KLASSE_KANDIDAAT, f"bijlagetype {suffix or '?'} — bestaande route")


def _sleutels(
    document: Document, klasse: str, inhoud_lezer: Callable[[], bytes], referentie: str | None
) -> frozenset[str]:
    uit: set[str] = set(bh.sleutels_uit_tekst(referentie))
    if document.bestandsnaam.lower().endswith(".xml") and klasse == bh.KLASSE_FACTUUR:
        try:
            uit |= bh.sleutels_uit_ubl(inhoud_lezer())
        except Exception:  # noqa: BLE001
            pass
    return frozenset(uit)


def _refs_in_scope(
    scope: uuid.UUID | None,
    naam: str,
    document_ids: list[uuid.UUID],
    *,
    opslag: DocumentOpslag,
) -> list[DocRef]:
    uit: list[DocRef] = []
    with scoped_session(scope, actor_id=SYSTEEM_ACTOR_ID) as session:
        documenten = session.scalars(select(Document).where(Document.id.in_(document_ids))).all()
        for d in documenten:
            if scope is None and d.administratie_id is not None:
                continue  # intussen toegewezen: komt via de administratie-scope terug (detail is dan verouderd)
            bytes_cache: dict[str, bytes] = {}

            def lezer(d=d) -> bytes:
                if "b" not in bytes_cache:
                    bytes_cache["b"] = opslag.lezen(pad=d.opslag_pad)
                return bytes_cache["b"]

            herkenning = _klasseer(d, lezer)
            voorstel = session.get(Boekvoorstel, d.id) if scope is not None else None
            referentie = voorstel.referentie if voorstel is not None else None
            geboekt = d.status == DocumentStatus.GEBOEKT
            uit.append(
                DocRef(
                    document_id=d.id,
                    administratie_id=d.administratie_id,
                    administratie_naam=naam if scope is not None else "verzamelbak",
                    bestandsnaam=d.bestandsnaam,
                    status=d.status,
                    soort=d.soort,
                    klasse=herkenning.klasse,
                    klasse_reden=herkenning.reden,
                    sleutels=_sleutels(d, herkenning.klasse, lezer, referentie),
                    referentie=referentie,
                    geboekt=geboekt,
                    boek_cyclus=voorstel.boek_cyclus if voorstel is not None else 0,
                )
            )
    return uit


def _overgeslagen(bericht_id: uuid.UUID, ref: DocRef, reden: str) -> BijlageKandidaat:
    return BijlageKandidaat(
        bericht_id=bericht_id, bijlage=ref, doelen=(), niet_eenduidig=False, overgeslagen_reden=reden
    )


def vind_kandidaten(
    *,
    administratie_id: uuid.UUID | None = None,
    sinds: date | None = None,
    opslag: DocumentOpslag | None = None,
    bericht_id: uuid.UUID | None = None,
) -> tuple[list[BijlageKandidaat], int]:
    """Alle bijlage-kandidaten (mét doel-facturen of overgeslagen-reden) + het aantal beoordeelde berichten.
    Lees-only."""
    from app.documenten.service import _standaard_opslag

    opslag = opslag or _standaard_opslag()
    namen = _administraties()
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(IntakeBericht).order_by(IntakeBericht.verwerkt_op)
        if sinds is not None:
            q = q.where(IntakeBericht.verwerkt_op >= datetime(sinds.year, sinds.month, sinds.day))
        if bericht_id is not None:
            q = q.where(IntakeBericht.id == bericht_id)
        berichten = [(b.id, b.detail or {}) for b in session.scalars(q)]

    kandidaten: list[BijlageKandidaat] = []
    beoordeeld = 0
    for bid, detail in berichten:
        rijen = [
            r for r in (detail.get("bijlagen") or []) if r.get("uitkomst") in _MET_DOCUMENT and r.get("document_id")
        ]
        if len(rijen) < 2:
            continue
        per_scope: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for r in rijen:
            try:
                did = uuid.UUID(str(r["document_id"]))
            except ValueError:
                continue
            per_scope.setdefault(_scope_uit_detail(r), []).append(did)
        if administratie_id is not None and administratie_id not in per_scope:
            continue
        beoordeeld += 1
        refs: list[DocRef] = []
        for scope, ids in per_scope.items():
            if scope is not None and scope not in namen:
                continue
            try:
                refs.extend(_refs_in_scope(scope, namen.get(scope, ""), ids, opslag=opslag))
            except Exception as exc:  # noqa: BLE001 — één kapotte scope stopt de rest niet; zichtbaar
                logger.exception("bijlagen-nabundelen: lezen mislukt voor bericht %s scope %s", bid, scope)
                print(f"FOUT bericht {bid} scope {scope}: {type(exc).__name__}: {exc}", file=sys.stderr)
        facturen = [r for r in refs if r.klasse != bh.KLASSE_BIJLAGE and r.status not in _FACTUUR_UITGESLOTEN]
        bijlagen = [r for r in refs if r.klasse == bh.KLASSE_BIJLAGE]
        if not bijlagen:
            continue
        for b in bijlagen:
            if administratie_id is not None and b.administratie_id not in (None, administratie_id):
                continue
            if b.status not in BIJLAGE_OPEN:
                kandidaten.append(
                    _overgeslagen(bid, b, f"status {b.status.value.replace('_', ' ')} — een mens heeft al geoordeeld")
                )
                continue
            if not facturen:
                kandidaten.append(_overgeslagen(bid, b, "geen factuur-document in deze mail"))
                continue
            if len(facturen) == 1:
                doelen, niet_eenduidig = facturen, False
            else:
                treffers = [
                    f
                    for f in facturen
                    if bh.bijlage_draagt_sleutel(b.bestandsnaam, _lees_veilig(opslag, b, refs), f.sleutels)
                ]
                doelen, niet_eenduidig = (treffers, False) if len(treffers) == 1 else (facturen, True)
            if administratie_id is not None:
                doelen = [d for d in doelen if d.administratie_id == administratie_id]
                if not doelen:
                    continue
            buiten = [d for d in doelen if b.administratie_id is not None and d.administratie_id != b.administratie_id]
            if buiten:
                kandidaten.append(
                    _overgeslagen(
                        bid,
                        b,
                        f"factuur staat in een andere administratie ({buiten[0].scope_label}) — eerst verplaatsen",
                    )
                )
                continue
            kandidaten.append(
                BijlageKandidaat(bericht_id=bid, bijlage=b, doelen=tuple(doelen), niet_eenduidig=niet_eenduidig)
            )
    return kandidaten, beoordeeld


_PAD_CACHE: dict[uuid.UUID, bytes] = {}


def _lees_veilig(opslag: DocumentOpslag, ref: DocRef, refs: list[DocRef]) -> bytes | None:
    """Bytes van een bijlage-document voor de tekstlaag-toets (alleen PDF); één lezing per document."""
    if not ref.bestandsnaam.lower().endswith(".pdf"):
        return None
    if ref.document_id not in _PAD_CACHE:
        with scoped_session(ref.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            d = session.get(Document, ref.document_id)
            pad = d.opslag_pad if d is not None else None
        try:
            _PAD_CACHE[ref.document_id] = opslag.lezen(pad=pad) if pad else b""
        except Exception:  # noqa: BLE001
            _PAD_CACHE[ref.document_id] = b""
    return _PAD_CACHE[ref.document_id]


# ---- uitvoeren ----------------------------------------------------------------------------------------------------


def _client_voor(administratie_id: uuid.UUID):  # noqa: ANN202 — RlzClient (seam)
    from app.documenten.boeken import _rlz_client_voor

    return _rlz_client_voor(administratie_id)


def _is_odoo(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        a = session.get(Administratie, administratie_id)
        return bool(a is not None and getattr(a, "boekhoud_backend", "rlz") == "odoo")


def _upload_naar_backend(
    *,
    doel: DocRef,
    bijlage_id: uuid.UUID,
    bestandsnaam: str,
    inhoud: bytes,
    client_factory: Callable[[uuid.UUID], object],
) -> str:
    """Geboekte factuur: de bijlage alsnog als extra upload. Retourneert een leesbare uitkomst."""
    from app.rlz.bijlage import zorg_voor_bijlage

    if doel.administratie_id is None:
        return "overgeslagen — factuur zonder administratie"
    if _is_odoo(doel.administratie_id):
        return "overgeslagen — Odoo-administratie (bijlage in Odoo volgt de Odoo-adapter, niet deze nazorg)"
    if doel.soort == DocumentSoort.VERKOOPFACTUUR.value:
        from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus

        with scoped_session(doel.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            rlz_id = session.scalar(
                select(VerkoopBoeking.verkoop_rlz_id).where(
                    VerkoopBoeking.document_id == doel.document_id,
                    VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
                )
            )
        if rlz_id is None:
            return "overgeslagen — geen geboekte verkoopboeking gevonden"
        entity, extern_id = "SalesInvoices", rlz_id
    elif doel.soort == DocumentSoort.INKOOPFACTUUR.value:
        entity, extern_id = "PurchaseInvoices", rlz_herboeking_id(doel.document_id, doel.boek_cyclus)
    else:
        return f"overgeslagen — documentsoort {doel.soort} kent geen bijlage-upload in deze nazorg"
    client = client_factory(doel.administratie_id)
    try:
        geupload = zorg_voor_bijlage(
            client,
            entity,
            extern_id,
            upload_id=rlz_bijlage_upload_id(bijlage_id, doel.boek_cyclus),
            filename=bestandsnaam,
            content_base64=base64.b64encode(inhoud).decode(),
            op_bestandsnaam=True,
        )
    finally:
        sluit = getattr(client, "close", None)
        if callable(sluit):
            sluit()
    return f"geüpload op {entity}/{extern_id}" if geupload else f"stond al op {entity}/{extern_id}"


def koppel_een(
    kandidaat: BijlageKandidaat,
    *,
    opslag: DocumentOpslag | None = None,
    dry_run: bool = True,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    client_factory: Callable[[uuid.UUID], object] | None = None,
) -> Uitkomst:
    """Eén bijlage → één of meer facturen. Eerste doel: het bestaande document wordt de bijlage-rij (zelfde scope;
    verzamelbak → mee naar de administratie). Tweede en volgende doel (niet eenduidig): een kopie als bijlage-rij.
    Geboekt doel → upload ná de commit (fout = zichtbaar, de koppeling staat)."""
    from app.documenten.service import _standaard_opslag

    if kandidaat.overgeslagen_reden:
        return Uitkomst(kandidaat, UITKOMST_OVERGESLAGEN, reden=kandidaat.overgeslagen_reden)
    opslag = opslag or _standaard_opslag()
    b = kandidaat.bijlage
    if dry_run:
        doelen = ", ".join(d.bestandsnaam for d in kandidaat.doelen)
        extra = " + RLZ-upload (factuur geboekt)" if any(d.geboekt for d in kandidaat.doelen) else ""
        return Uitkomst(kandidaat, UITKOMST_KANDIDAAT, reden=f"zou koppelen aan {doelen}{extra}")

    uploads: list[str] = []
    inhoud: bytes | None = None
    for i, doel in enumerate(kandidaat.doelen):
        scope = doel.administratie_id
        with scoped_session(scope, actor_id=actor_id) as session:
            factuur = session.get(Document, doel.document_id)
            if factuur is None or factuur.status in _FACTUUR_UITGESLOTEN:
                return Uitkomst(
                    kandidaat, UITKOMST_OVERGESLAGEN, reden="factuur niet (meer) gevonden of intussen afgehandeld"
                )
            if i == 0:
                bijlage = session.get(Document, b.document_id)
                if bijlage is None or bijlage.status not in BIJLAGE_OPEN:
                    return Uitkomst(kandidaat, UITKOMST_OVERGESLAGEN, reden="bijlage-document intussen verder verwerkt")
                if bijlage.administratie_id is None and scope is not None:
                    bijlage.administratie_id = scope  # verzamelbak → mee naar de administratie van de factuur
                inhoud = opslag.lezen(pad=bijlage.opslag_pad)
                bijlagen_module.koppel_document_als_bijlage(
                    session,
                    factuur=factuur,
                    bijlage=bijlage,
                    actor_id=actor_id,
                    niet_eenduidig=kandidaat.niet_eenduidig,
                )
                bijlage_id = bijlage.id
                naam = bijlage.bestandsnaam
            else:
                assert inhoud is not None
                bijlage_id = bijlagen_module.registreer_bijlage(
                    factuur_document_id=factuur.id,
                    administratie_id=scope,
                    bestandsnaam=naam,
                    inhoud=inhoud,
                    content_type=None,
                    actor_id=actor_id,
                    intake_bericht_id=factuur.intake_bericht_id,
                    opslag=opslag,
                    niet_eenduidig=True,
                )
        if doel.geboekt:
            try:
                uploads.append(
                    _upload_naar_backend(
                        doel=doel,
                        bijlage_id=bijlage_id,
                        bestandsnaam=naam,
                        inhoud=inhoud or b"",
                        client_factory=client_factory or _client_voor,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — de koppeling staat; de upload-fout is zichtbaar, nooit stil
                logger.warning("bijlagen-nabundelen: upload mislukt voor %s: %s", bijlage_id, exc)
                return Uitkomst(
                    kandidaat,
                    UITKOMST_GEKOPPELD_UPLOAD_FOUT,
                    reden="lokaal gekoppeld; upload naar Reeleezee mislukt — opnieuw via de nazorg",
                    upload=f"mislukt: {type(exc).__name__}: {str(exc)[:200]}",
                )
    return Uitkomst(kandidaat, UITKOMST_GEKOPPELD, upload="; ".join(uploads) or None)


def nabundel_alle(
    *,
    dry_run: bool = True,
    administratie_id: uuid.UUID | None = None,
    sinds: date | None = None,
    opslag: DocumentOpslag | None = None,
    client_factory: Callable[[uuid.UUID], object] | None = None,
) -> Telling:
    telling = Telling()
    kandidaten, telling.berichten = vind_kandidaten(administratie_id=administratie_id, sinds=sinds, opslag=opslag)
    telling.kandidaten = len([k for k in kandidaten if not k.overgeslagen_reden])
    for k in kandidaten:
        try:
            u = koppel_een(k, opslag=opslag, dry_run=dry_run, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001 — één kapotte koppeling stopt de stapel niet; wél zichtbaar
            logger.exception("bijlagen-nabundelen: koppelen mislukt voor %s", k.bijlage.document_id)
            u = Uitkomst(k, UITKOMST_MISLUKT, reden=f"onverwachte fout ({type(exc).__name__}: {exc})")
        telling.registreer(u)
    return telling


# ---- CLI ----------------------------------------------------------------------------------------------------------


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Nazorg (Peter 02-10, bijlagen bij de factuur): per e-mail de al gesplitste niet-factuur-bijlagen "
        "(specificaties, huurstaten, werkbonnen, foto's, xlsx/csv) alsnog aan hun factuur koppelen — status "
        "samengevoegd mét verwijzing, geboekte factuur → bijlage óók naar RLZ. Dry-run is de default; --uitvoeren "
        "schrijft.",
    )
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tonen (default).")
    p.add_argument("--uitvoeren", action="store_true", dest="uitvoeren", help="Échte run (schrijft).")
    p.add_argument("--administratie", default=None, help="Beperk tot één administratie (uuid of naamdeel).")
    p.add_argument("--sinds", default=None, help="Alleen e-mails verwerkt vanaf deze datum (JJJJ-MM-DD).")
    p.add_argument("--ongedaan", default=None, help="Maak één bijlage-koppeling ongedaan (bijlage-document-id).")
    p.add_argument("--reden", default=None, help="Reden bij --ongedaan (verplicht).")


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
    if getattr(args, "ongedaan", None):
        if dry_run:
            print("FOUT: --ongedaan is schrijvend — geef --uitvoeren mee", file=sys.stderr)
            return 2
        reden = (getattr(args, "reden", None) or "").strip()
        if not reden:
            print("FOUT: --ongedaan vereist --reden", file=sys.stderr)
            return 2
        try:
            eind = bijlagen_module.maak_bijlage_ongedaan(
                administratie_id=administratie_id,
                bijlage_id=uuid.UUID(args.ongedaan),
                actor_id=SYSTEEM_ACTOR_ID,
                reden=reden,
            )
        except (bijlagen_module.BijlageFout, ValueError) as exc:
            print(f"FOUT: {exc}", file=sys.stderr)
            return 1
        print(f"{COMMANDO} — ONGEDAAN: bijlage {args.ongedaan} → {eind.value}")
        return 0
    sinds: date | None = None
    if getattr(args, "sinds", None):
        try:
            sinds = date.fromisoformat(args.sinds)
        except ValueError:
            print(f"FOUT: --sinds {args.sinds!r} is geen datum (JJJJ-MM-DD)", file=sys.stderr)
            return 2
    label = "DRY-RUN (niets geschreven)" if dry_run else "UITGEVOERD"
    telling = nabundel_alle(dry_run=dry_run, administratie_id=administratie_id, sinds=sinds)
    print(f"{COMMANDO} — {label}: {telling.berichten} e-mail(s) beoordeeld, {telling.kandidaten} kandidaat/kandidaten")
    for naam, per in sorted(telling.per_administratie().items()):
        print(f"  {naam}: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items())))
        for u in telling.uitkomsten:
            scope = u.kandidaat.doelen[0].scope_label if u.kandidaat.doelen else u.kandidaat.bijlage.scope_label
            if scope == naam:
                print(f"    - {u.als_regel()}")
    for reden, n in sorted(telling.overgeslagen_redenen.items()):
        print(f"  overgeslagen · {reden}: {n}")
    print(
        f"TOTAAL: {telling.berichten} e-mails, {telling.kandidaten} kandidaten, {telling.gekoppeld} gekoppeld, "
        f"{telling.overgeslagen} overgeslagen, {telling.mislukt} mislukt — {label}"
    )
    return 1 if telling.mislukt else 0
