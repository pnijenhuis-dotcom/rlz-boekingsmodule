"""Reconciliatie-blok `rlz_dubbel` — periodieke toets "mogelijk dubbel geboekt in RLZ" (blok 6, bundel 08-09;
aanleiding BESLISSINGEN "HERSTELRUN 07-09 — BLOK A" beslispunt 4: in Kempen Facilities stonden twee HANDMATIG
ingevoerde BOOT-facturen (RLZ-04-00004037/38, GUID-versie 4) die de module nooit kon zien — onze duplicaatchecks
kijken alleen naar wat de module zélf boekt).

Wat dit blok doet — en bewust níét:
- Per RLZ-administratie (Odoo-administraties zichtbaar OVERGESLAGEN, `RLZ_ONLY_OVERGESLAGEN`-patroon) worden de
  PurchaseInvoices van de laatste `VENSTER_DAGEN` dagen gelezen in ÉÉN gepagineerde lees-reeks ($top/$skip, zelfde
  vorm als `app/geheugen/seed.py::_facturen` — live bewezen op deze collectie; `$expand=Entity` omdat Entity op de
  collectie alleen mét expand zichtbaar is). Concepten (Status 1) komen mee (STAP-0 07-09) en worden gemarkeerd.
- Binnen dezelfde crediteur (Entity) worden paren gezocht op UITSLUITEND gelijke GENORMALISEERDE referentie
  (`duplicaat_afvoer.normaliseer_referentie` — één normalisatie in de hele module). Placeholder-referenties
  ("Ingescand document", alleen nullen, "factuur"/"invoice", zie `PLACEHOLDER_REFERENTIES`) tellen als LEEG en
  matchen nooit. **Herstelrun "Basis eerst" 08-09 (blok 7, besluit Peter 08-09): de vroegere variant (B) "gelijk
  bedrag + gelijke factuurdatum" is VOLLEDIG vervallen** — de Kempen-live-check gaf 516 paren, waarvan 508 op
  bedrag+datum: reeksfacturen van Lusso-Design Interior Projects en Kempen Airco (identieke bedragen op één datum,
  opeenvolgende nummers = echte losse facturen) en "Ingescand document"-referenties die elkaar matchten.
  **Aanvaarde grens:** de aanleiding-casus BOOT 202632703/202632704 (RLZ-04-00004037/38, € 2.976,30 vs € 1.775,98,
  beide 22-06-2026) heeft een ándere referentie én een ánder bedrag en wordt door deze toets bewust NIET gevangen
  (viel ook onder (B) al buiten de criteria).
- Een paar waarvan BEIDE documenten door de module zijn aangemaakt telt niet: die GUID's zijn deterministisch
  (UUIDv5, `documenten/rlz_ids.py`) en worden per administratie uit de eigen DB afgeleid (document × boek_cyclus,
  tegenboekingen, doorbelasting-spiegels, bank-relatieboekingen). Eén module-exemplaar + één handmatig exemplaar
  IS een treffer (de mens typte in RLZ wat de module ook boekte). Een GUID-versie-4 is nooit van ons (A11-diagnose).
- Uitkomst = bevinding `afwijking` soort `dubbel_in_rlz`, vingerafdruk stabiel per paar (acceptatie-vingerafdruk
  over bron|soort|detail met detail = de twee RLZ-id's gesorteerd) → de delta-motor mailt één keer; acceptatie mét
  reden via het bestaande pad (bron `documenten`: de DB-CHECK op `reconciliatie_acceptatie.bron` kent geen vijfde
  waarde en dit blok brengt bewust GEEN migratie). GEEN automatische actie: de RLZ-kant is mensenwerk, de app
  verwijdert nooit (kernprincipe 3). Er is geen bekende URL-vorm van de RLZ-web-UI per document → de handeling is
  "open beide boekstuknummers in Reeleezee".

Geen AI, geen RLZ-writes. Alle geldvergelijking in Decimal."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.duplicaat_afvoer import normaliseer_referentie
from app.documenten.models import Boekvoorstel, Document, Tegenboeking
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.rlz.client import RlzClient, bedrag_cent_exact
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

BLOK = "rlz_dubbel"
SOORT = "dubbel_in_rlz"
#: Acceptaties lopen via de bestaande `reconciliatie_acceptatie`-tabel; de DB-CHECK op `bron` kent alleen
#: documenten/bank/omzet/doorbelasting (migraties 0042/0044) — dit blok brengt geen migratie en meldt onder
#: `documenten`.
ACCEPTATIE_BRON = "documenten"
#: Leesvenster: factuurdatum (`Date`) niet ouder dan dit. 400 dagen dekt een boekjaar plús de nakomers van het vorige;
#: ouder handwerk is boekhoudkundig afgesloten (aangifte ingediend) en hoort niet elke nacht opnieuw gemeld te worden.
VENSTER_DAGEN = 400
PAGINA_GROOTTE = 200
REGEL_REFERENTIE = "referentie"
#: Genormaliseerde referenties (`normaliseer_referentie`) die geen factuurnummer zijn maar een plaatsvervanger van de
#: RLZ-UI/scan-import — tellen als leeg, matchen nooit (blok 7 herstelrun 08-09). Alleen nullen (`0`, `000`, `00-00`)
#: vallen er via `_ALLEEN_NULLEN` ook onder; "factuur"/"invoice" zijn ná normalisatie al leeg (voorvoegsel-strip).
PLACEHOLDER_REFERENTIES: frozenset[str] = frozenset(
    {
        "ingescanddocument",
        "ingescand",
        "document",
        "scan",
        "factuur",
        "invoice",
        "nota",
        "bon",
        "onbekend",
        "nvt",
        "geen",
    }
)
_ALLEEN_NULLEN = re.compile(r"0+")


def is_placeholder_referentie(referentie_norm: str | None) -> bool:
    """Deterministisch: leeg, alleen nullen of een generieke plaatsvervanger = geen toetsbare referentie."""
    if not referentie_norm:
        return True
    return bool(_ALLEEN_NULLEN.fullmatch(referentie_norm)) or referentie_norm in PLACEHOLDER_REFERENTIES


def toetsbare_referentie(referentie: object) -> str | None:
    """Genormaliseerde referentie voor de match, of None als die leeg/placeholder is."""
    if referentie in (None, ""):
        return None
    norm = normaliseer_referentie(str(referentie))
    return None if is_placeholder_referentie(norm) else norm


# ---- data ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RlzDocument:
    """Eén PurchaseInvoice zoals RLZ 'm teruggeeft, platgeslagen tot wat de toets nodig heeft."""

    rlz_id: uuid.UUID
    entity_id: uuid.UUID | None
    entity_naam: str | None
    referentie: str | None
    referentie_norm: str | None
    datum: date | None
    boekdatum: date | None
    bedrag: Decimal | None
    boekstuk: str | None
    status: int | None
    van_module: bool

    @property
    def concept(self) -> bool:
        return self.status == 1


@dataclass(frozen=True)
class DubbelPaar:
    a: RlzDocument  # a.rlz_id < b.rlz_id (sortering op tekst) — stabiel over runs
    b: RlzDocument
    regels: tuple[str, ...]  # sinds 08-09 altijd (REGEL_REFERENTIE,); oude bevindingen kunnen nog 'bedrag_datum' dragen

    @property
    def detail(self) -> str:
        """De acceptatie-sleutel (bron|soort|detail) — uitsluitend de twee RLZ-id's, zodat het paar over runs
        dezelfde vingerafdruk houdt (één mail; acceptatie blijft plakken zolang het paar bestaat)."""
        return f"rlz_a={self.a.rlz_id} rlz_b={self.b.rlz_id}"

    @property
    def record_id(self) -> uuid.UUID:
        return self.a.rlz_id

    @property
    def concept(self) -> bool:
        return self.a.concept or self.b.concept

    def context(self, *, administratie_naam: str | None = None, rlz_admin_id: str | None = None) -> dict[str, Any]:
        """Naamvelden voor `teksten.py` + de UI-uitklap (contract A↔A8: titel/wat/doe zonder GUID's, GUID's in de
        details)."""
        return {
            "leverancier_naam": self.a.entity_naam or self.b.entity_naam,
            "regel": "+".join(self.regels),
            "concept": self.concept,
            "referentie_a": self.a.referentie,
            "referentie_b": self.b.referentie,
            "boekstuk_a": self.a.boekstuk,
            "boekstuk_b": self.b.boekstuk,
            "bedrag_a": str(self.a.bedrag) if self.a.bedrag is not None else None,
            "bedrag_b": str(self.b.bedrag) if self.b.bedrag is not None else None,
            "datum_a": self.a.datum.isoformat() if self.a.datum else None,
            "datum_b": self.b.datum.isoformat() if self.b.datum else None,
            "boekdatum_a": self.a.boekdatum.isoformat() if self.a.boekdatum else None,
            "boekdatum_b": self.b.boekdatum.isoformat() if self.b.boekdatum else None,
            "status_a": self.a.status,
            "status_b": self.b.status,
            "van_module_a": self.a.van_module,
            "van_module_b": self.b.van_module,
            "rlz_id_a": str(self.a.rlz_id),
            "rlz_id_b": str(self.b.rlz_id),
            "administratie_naam": administratie_naam,
            "rlz_admin_id": rlz_admin_id,
        }


@dataclass(frozen=True)
class RlzDubbelRapport:
    administratie_id: uuid.UUID | None
    aantal_getoetst: int  # documenten in het venster
    aantal_module: int  # waarvan door de module aangemaakt
    aantal_zonder_crediteur: int  # zonder Entity — niet toetsbaar
    paren: tuple[DubbelPaar, ...]
    venster_vanaf: date


@dataclass(frozen=True)
class RlzDubbelResultaat:
    rapporten: dict[uuid.UUID, RlzDubbelRapport] = field(default_factory=dict)
    fouten: dict[uuid.UUID, str] = field(default_factory=dict)
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)


# ---- RLZ lezen -----------------------------------------------------------------------------------


def venster_vanaf(vandaag: date | None = None) -> date:
    return (vandaag or datetime.now(UTC).date()) - timedelta(days=VENSTER_DAGEN)


def lees_purchase_invoices(client: RlzClient, *, vanaf: date) -> list[dict[str, Any]]:
    """Alle inkoopfacturen met `Date ge <vanaf>` in één gepagineerde reeks — exact de literal- en pagineervorm van
    `app/geheugen/seed.py::_facturen` (draait dagelijks live op PurchaseInvoices). Throttling/retry zit in de
    client (`_request`). Bewust geen `$select` (niet STAP-0-geverifieerd op deze collectie) en geen `Status`-filter
    (`Status eq 1` = 400, enum-type; concepten moeten juist méé)."""
    uit: list[dict[str, Any]] = []
    skip = 0
    while True:
        batch = client.get(
            "PurchaseInvoices",
            params={
                "$filter": f"Date ge {vanaf.isoformat()}",
                "$expand": "Entity",
                "$top": str(PAGINA_GROOTTE),
                "$skip": str(skip),
            },
        ).get("value", [])
        uit.extend(batch)
        if len(batch) < PAGINA_GROOTTE:
            return uit
        skip += PAGINA_GROOTTE


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _als_int(waarde: object) -> int | None:
    try:
        return int(waarde) if waarde is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def naar_rlz_document(rij: dict[str, Any], *, module_ids: set[uuid.UUID]) -> RlzDocument | None:
    """Eén RLZ-rij → `RlzDocument`; None als de rij geen leesbaar id draagt (dan is er niets te vergelijken)."""
    rlz_id = _als_uuid(rij.get("id"))
    if rlz_id is None:
        return None
    entity = rij.get("Entity") or {}
    referentie = rij.get("Reference")
    return RlzDocument(
        rlz_id=rlz_id,
        entity_id=_als_uuid(entity.get("id")) if isinstance(entity, dict) else None,
        entity_naam=(entity.get("Name") or entity.get("SearchName")) if isinstance(entity, dict) else None,
        referentie=str(referentie) if referentie not in (None, "") else None,
        referentie_norm=toetsbare_referentie(referentie),
        datum=_als_datum(rij.get("Date")),
        boekdatum=_als_datum(rij.get("BookDate")),
        bedrag=bedrag_cent_exact(rij.get("BaseInvoiceAmount")),
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        status=_als_int(rij.get("Status")),
        van_module=is_van_module(rlz_id, module_ids),
    )


def is_van_module(rlz_id: uuid.UUID, module_ids: set[uuid.UUID]) -> bool:
    """Van de module = het GUID staat in de deterministische set uit onze eigen DB. Een GUID-versie-4 (RLZ-UI/
    import) is per definitie nooit van ons — die kortsluiting voorkomt dat een lege/verouderde set een handmatig
    exemplaar per ongeluk als 'module' laat doorgaan."""
    if rlz_id.version == 4:
        return False
    return rlz_id in module_ids


# ---- paren zoeken (puur) -------------------------------------------------------------------------


def vind_paren(documenten: Iterable[RlzDocument]) -> list[DubbelPaar]:
    """Paren binnen dezelfde crediteur op UITSLUITEND gelijke genormaliseerde referentie (placeholder-referenties zijn
    al None, zie `toetsbare_referentie`). Bedrag en datum spelen sinds 08-09 GEEN rol meer (blok 7: 508 ruis-paren bij
    Kempen). Beide-van-de-module = geen treffer. Documenten zonder Entity zijn niet toetsbaar. Elk paar hooguit één
    keer, gesorteerd op RLZ-id (stabiele vingerafdruk)."""
    per_crediteur: dict[uuid.UUID, list[RlzDocument]] = {}
    for d in documenten:
        if d.entity_id is None:
            continue
        per_crediteur.setdefault(d.entity_id, []).append(d)

    paren: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = {}

    def _voeg_toe(x: RlzDocument, y: RlzDocument, regel: str) -> None:
        if x.rlz_id == y.rlz_id or (x.van_module and y.van_module):
            return
        sleutel = (x.rlz_id, y.rlz_id) if str(x.rlz_id) < str(y.rlz_id) else (y.rlz_id, x.rlz_id)
        paren.setdefault(sleutel, set()).add(regel)

    for docs in per_crediteur.values():
        op_referentie: dict[str, list[RlzDocument]] = {}
        for d in docs:
            if d.referentie_norm:
                op_referentie.setdefault(d.referentie_norm, []).append(d)
        for groep in op_referentie.values():
            for i, x in enumerate(groep):
                for y in groep[i + 1 :]:
                    _voeg_toe(x, y, REGEL_REFERENTIE)

    op_id = {d.rlz_id: d for d in documenten}
    uit = [
        DubbelPaar(a=op_id[a_id], b=op_id[b_id], regels=tuple(sorted(regels))) for (a_id, b_id), regels in paren.items()
    ]
    uit.sort(key=lambda p: (str(p.a.rlz_id), str(p.b.rlz_id)))
    return uit


# ---- module-GUID's uit de eigen DB ----------------------------------------------------------------


def module_ids_voor(administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """Alle RLZ-inkoopdocument-GUID's die de module voor deze administratie kan hebben aangemaakt — deterministisch
    afgeleid (rlz_ids.py bewaart ze bewust niet als kolom): élk inkoopdocument × élke boek_cyclus (herboekingen),
    tegenboekingen, doorbelasting-spiegels in deze (doel-)administratie en bank-relatieboekingen. Ruimer dan strikt
    nodig is onschadelijk: de set bepaalt alleen "beide van de module → geen treffer"."""
    uit: set[uuid.UUID] = set()
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document.id, Boekvoorstel.boek_cyclus)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
            .where(Document.administratie_id == administratie_id)
        ).all()
        for document_id, boek_cyclus in rijen:
            for cyclus in range(int(boek_cyclus or 0) + 1):
                uit.add(rlz_herboeking_id(document_id, cyclus))
        for rij in session.execute(
            select(Tegenboeking.document_id, Tegenboeking.boek_cyclus, Tegenboeking.rlz_tegenboeking_id).where(
                Tegenboeking.administratie_id == administratie_id
            )
        ).all():
            uit.add(rij.rlz_tegenboeking_id)
            uit.add(rlz_tegenboeking_id(rij.document_id, rij.boek_cyclus))
        try:
            from app.doorbelasting.models import DoorbelastingBoeking

            for spiegel_id in session.scalars(
                select(DoorbelastingBoeking.spiegel_rlz_id).where(
                    DoorbelastingBoeking.doel_administratie_id == administratie_id
                )
            ):
                if spiegel_id is not None:
                    uit.add(spiegel_id)
        except Exception:  # noqa: BLE001 — een ontbrekende neventabel mag de toets nooit laten omvallen
            logger.exception("doorbelasting-spiegel-GUID's niet gelezen voor %s", administratie_id)
        try:
            from app.bank.models import BankRelatieBoeking

            for rlz_id in session.scalars(
                select(BankRelatieBoeking.rlz_document_id).where(
                    BankRelatieBoeking.administratie_id == administratie_id
                )
            ):
                if rlz_id is not None:
                    uit.add(rlz_id)
        except Exception:  # noqa: BLE001
            logger.exception("bank-relatieboeking-GUID's niet gelezen voor %s", administratie_id)
    return uit


# ---- toets per administratie ---------------------------------------------------------------------


def toets_met_client(
    client: RlzClient,
    *,
    module_ids: set[uuid.UUID],
    administratie_id: uuid.UUID | None = None,
    vandaag: date | None = None,
) -> RlzDubbelRapport:
    """De toets zelf, los van DB en credentials — ook het hart van het read-only live-script."""
    vanaf = venster_vanaf(vandaag)
    rijen = lees_purchase_invoices(client, vanaf=vanaf)
    documenten = [d for d in (naar_rlz_document(r, module_ids=module_ids) for r in rijen) if d is not None]
    return RlzDubbelRapport(
        administratie_id=administratie_id,
        aantal_getoetst=len(documenten),
        aantal_module=sum(1 for d in documenten if d.van_module),
        aantal_zonder_crediteur=sum(1 for d in documenten if d.entity_id is None),
        paren=tuple(vind_paren(documenten)),
        venster_vanaf=vanaf,
    )


def toets_administratie(
    administratie_id: uuid.UUID,
    *,
    client_factory: Callable[[str], RlzClient] | None = None,
    vandaag: date | None = None,
) -> RlzDubbelRapport:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    module_ids = module_ids_voor(administratie_id)
    maak = client_factory or (lambda rid: client_voor_rlz_admin_id(rid).for_administration(rid))
    with maak(rlz_admin_id) as client:
        return toets_met_client(client, module_ids=module_ids, administratie_id=administratie_id, vandaag=vandaag)


def toets_alle(*, client_factory: Callable[[str], RlzClient] | None = None) -> RlzDubbelResultaat:
    """Alle actieve RLZ-administraties; één kapotte administratie stopt de rest niet (zichtbaar als fout);
    Odoo-administraties zichtbaar overgeslagen (A12-patroon)."""
    from app.backends.registry import RLZ_ONLY_OVERGESLAGEN, actieve_administraties_per_backend

    rlz_ids, odoo_ids = actieve_administraties_per_backend()
    rapporten: dict[uuid.UUID, RlzDubbelRapport] = {}
    fouten: dict[uuid.UUID, str] = {}
    for aid in rlz_ids:
        try:
            rapporten[aid] = toets_administratie(aid, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001 — rapporteren en door
            logger.exception("rlz_dubbel-toets mislukt voor administratie %s", aid)
            fouten[aid] = str(exc)
    return RlzDubbelResultaat(
        rapporten=rapporten, fouten=fouten, overgeslagen={aid: RLZ_ONLY_OVERGESLAGEN for aid in odoo_ids}
    )


# ---- CLI-blok (reconciliatie-alles) -------------------------------------------------------------


def _regel_tekst(administratie_id: uuid.UUID, paar: DubbelPaar, beoordeeld) -> str:  # noqa: ANN001
    kop = (
        f"{administratie_id} rlz_a={paar.a.rlz_id} rlz_b={paar.b.rlz_id} soort={SOORT} "
        f"[vaf:{beoordeeld.vingerafdruk}]: {paar.a.boekstuk or '?'} + {paar.b.boekstuk or '?'} "
        f"({'+'.join(paar.regels)}{', concept' if paar.concept else ''})"
    )
    if beoordeeld.acceptatie is None:
        return kop
    return (
        f"GEACCEPTEERD {kop} — reden: {beoordeeld.acceptatie.reden} "
        f"(sinds {beoordeeld.acceptatie.geaccepteerd_op.date().isoformat()})"
    )


def cli_blok(args, verzamelaar=None, *, stdout: Callable[[str], None] = print, stderr=None) -> int:  # noqa: ANN001
    """Blokfunctie voor `reconciliatie-alles` (zelfde contract als `_omzet_reconciliatie` in app/cli.py): print
    dezelfde soort regels, registreer élke regel als bevinding, exit 1 zodra er een open paar of een fout is.
    Losse aanroep zonder verzamelaar blijft werken (alleen printen)."""
    import sys

    from app.reconciliatie import service as acceptatie_service
    from app.reconciliatie import verrijking

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))

    def meld(**kw) -> None:  # noqa: ANN003
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)

    def naam_van(aid: uuid.UUID) -> str | None:
        try:
            return verrijking.administratie_naam(aid)
        except Exception:  # noqa: BLE001
            return None

    resultaat = toets_alle()
    for aid, reden in resultaat.overgeslagen.items():
        stdout(f"OVERGESLAGEN {aid}: {reden}")
    uitgesloten = acceptatie_service.uitgesloten_administraties()

    echte_fouten = 0
    for aid, fout in resultaat.fouten.items():
        uitsluiting = uitgesloten.get(aid)
        if uitsluiting:
            tekst = f"UITGESLOTEN {aid}: {fout} (uitgesloten: {uitsluiting})"
            stdout(tekst)
            meld(
                soort="uitgesloten",
                administratie_id=aid,
                tekst=tekst,
                detail=verrijking.administratie(aid, fout=fout, uitsluiting=uitsluiting) or None,
            )
            continue
        echte_fouten += 1
        tekst = f"FOUT       {aid}: {fout}"
        stderr(tekst)
        meld(soort="fout", administratie_id=aid, tekst=tekst, detail=verrijking.administratie(aid, fout=fout) or None)

    open_totaal = 0
    geaccepteerd_totaal = 0
    getoetst_totaal = 0
    paren_totaal = 0
    for aid, rapport in resultaat.rapporten.items():
        getoetst_totaal += rapport.aantal_getoetst
        paren_totaal += len(rapport.paren)
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(rapport.aantal_getoetst)
        uitsluiting = uitgesloten.get(aid)
        if not rapport.paren:
            stdout(
                f"OK         {aid}: {rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()} "
                f"({rapport.aantal_module} van de module, {rapport.aantal_zonder_crediteur} zonder crediteur), "
                "geen dubbele paren"
            )
            continue
        beoordeeld = acceptatie_service.beoordeel(
            bron=ACCEPTATIE_BRON,
            administratie_id=aid,
            afwijkingen=[(p.record_id, SOORT, p.detail) for p in rapport.paren],
        )
        open_hier = sum(1 for b in beoordeeld if b.telt_mee)
        kop = "UITGESLOTEN" if uitsluiting else ("AFWIJKING " if open_hier else "OK        ")
        stdout(
            f"{kop} {aid}: {rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()}, "
            f"{len(rapport.paren)} mogelijk dubbel paar/paren ({open_hier} open, {len(beoordeeld) - open_hier} "
            f"geaccepteerd){f' — telt niet mee ({uitsluiting})' if uitsluiting else ''}"
        )
        administratie_naam = naam_van(aid)
        rlz_admin_id: str | None
        try:
            rlz_admin_id = rlz_admin_id_voor(aid)
        except Exception:  # noqa: BLE001
            rlz_admin_id = None
        for paar, b in zip(rapport.paren, beoordeeld, strict=True):
            regel = _regel_tekst(aid, paar, b)
            if uitsluiting:
                soort = "uitgesloten"
                tekst = f"    - UITGESLOTEN {regel}"
                stdout(tekst)
            elif b.telt_mee:
                soort = "afwijking"
                open_totaal += 1
                tekst = f"    - AFWIJKING  {regel}"
                stderr(tekst)
            else:
                soort = "geaccepteerd"
                geaccepteerd_totaal += 1
                tekst = f"    - {regel}"
                stdout(tekst)
            meld(
                soort=soort,
                administratie_id=aid,
                tekst=tekst.strip(),
                vingerafdruk=b.vingerafdruk,
                detail={
                    "bron": ACCEPTATIE_BRON,
                    "record_id": str(b.record_id),
                    "afwijking_soort": SOORT,
                    "detail": b.detail,
                    "geaccepteerd": not b.telt_mee,
                    "uitsluiting": uitsluiting,
                    **paar.context(administratie_naam=administratie_naam, rlz_admin_id=rlz_admin_id),
                },
            )

    stdout(
        f"\n{len(resultaat.rapporten)}/{len(resultaat.rapporten) + len(resultaat.fouten)} administraties getoetst, "
        f"{getoetst_totaal} inkoopfacturen, {paren_totaal} mogelijk dubbel paar/paren "
        f"({open_totaal} open, {geaccepteerd_totaal} geaccepteerd)."
    )
    if echte_fouten or open_totaal:
        stderr(f"{open_totaal} open paar/paren en {echte_fouten} mislukte administratie(s) in de RLZ-dubbel-toets")
        return 1
    return 0


def paren_als_tekst(rapport: RlzDubbelRapport) -> Sequence[str]:
    """Leesbare regels voor het live/dry-run-script (geen bevindingen, geen DB)."""
    uit = [
        f"{rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()} "
        f"({rapport.aantal_module} van de module, {rapport.aantal_zonder_crediteur} zonder crediteur) — "
        f"{len(rapport.paren)} mogelijk dubbel paar/paren"
    ]
    for p in rapport.paren:
        uit.append(
            f"  - {p.a.entity_naam or '?'}: {p.a.boekstuk or '?'} ({p.a.referentie}, {p.a.datum}, {p.a.bedrag}, "
            f"status {p.a.status}{', module' if p.a.van_module else ''}) ↔ {p.b.boekstuk or '?'} "
            f"({p.b.referentie}, {p.b.datum}, {p.b.bedrag}, status {p.b.status}{', module' if p.b.van_module else ''}) "
            f"[{'+'.join(p.regels)}] rlz_a={p.a.rlz_id} rlz_b={p.b.rlz_id}"
        )
    return uit
