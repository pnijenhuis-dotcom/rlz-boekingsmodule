"""Pandenregister afleiden uit RLZ (bundel 10-09 blok D2; HERBOUWD run 2 VGG 12-09 blok 3) — `leid_af(administratie_id,
*, dry_run, client, pandenlijst)`.

Leest ManualJournals, SalesInvoices, PurchaseInvoices (+ Receipts als leesbaar, ontdubbeld op id) én — via de seam
`lees_bankmutaties` — PaymentTransactions, gepagineerd (`app/rlz/lezen.py`). De tekst van élk document is de ONTKNIPTE
samenvoeging van Reference/Description/Header (`app/rlz/tekst.py::ontknip`; een veld dat letterlijk in een ander veld
zit
—
RLZ's op 20 tekens afgekapte Reference — telt één keer). Classificatie per document deterministisch
(`afleiding.classificeer`, soorten aankoop/verkoop/kosten/aanbetaling/vaste_lasten/balans); een PaymentTransaction telt
alleen mee als GEEN geclassificeerd document hetzelfde |bedrag| binnen ±3 dagen draagt (de bankregel vult een tekstloze
systeemhuls aan, verdubbelt nooit een bank-geïmporteerd document).

Adressen worden geclusterd (`pandenlijst.cluster_adressen`: huisnummer + straat-gelijkenis) — één cluster = één pand-
voorstel mét varianten in de reden; mét `--pandenlijst <csv>` wordt élk cluster aan precies één lijst-pand gebonden
(code = lijst-code, `salesforce_id` in het rapport), meerduidig = niet gebonden en apart gemeld. Aankoopdatum = vroegste
échte aankoop (nooit een 31-12-balansboeking, nooit een aanbetaling).

Schrijft — alleen mét `dry_run=False` — `pand`-voorstellen (status `voorstel`, herkomst `afgeleid`) en `pand_boeking`-
voorstellen (herkomst `voorstel`). Idempotent: upsert op (administratie, code — óf een eerdere variant-code van
hetzelfde
cluster) resp. (administratie, bron_sleutel, pand); herkomst `mens` of een pand dat niet meer `voorstel` is wordt NOOIT
overschreven (mens wint). Niets wordt automatisch bevestigd. Geen RLZ-/Odoo-writes. Geld in Decimal.

`pand_per_document(administratie_id, *, boekingen=None)` (contract B → E): DB-toewijzingen (mens/bevestigd altijd)
aangevuld
met de afleiding voor documenten zonder DB-rij."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.panden import afleiding, pandenlijst
from app.panden.models import (
    Pand,
    PandBoeking,
    PandBoekingHerkomst,
    PandHerkomst,
    PandStatus,
    bron_sleutel_voor,
)
from app.rlz.client import RlzClient
from app.rlz.lezen import LeesClient, als_bedrag, als_datum, entity_van, heeft_bijlage, lees_collectie
from app.rlz.tekst import ontknip

logger = logging.getLogger(__name__)

MAX_BIJLAGE_CHECKS_DEFAULT = 200
OVERHEAD_PROJECTNAAM = "Overhead"
OVERHEAD_ONTBREEKT = "Overhead-project ontbreekt — aanmaken in run 2 (projectaanmaak = RLZ-write, niet in deze run)"
#: (collectie, $expand) — Entity is alleen mét expand zichtbaar; het memoriaal-dagboek idem (valt terug zonder expand,
#: dan geldt de RLZ-06-boekstukreeks als dagboek-signaal).
COLLECTIES: tuple[tuple[str, str | None], ...] = (
    ("ManualJournals", "JournalEntryDiary"),
    ("SalesInvoices", "Entity"),
    ("PurchaseInvoices", "Entity"),
)
#: Receipts = alle bonnen/bank-directe documenten (RLZ-09-hulzen, RLZ-04-kopieën); bestaat mogelijk niet op elke login —
#: een fout dáár is een OVERGESLAGEN-regel, geen FOUT. Rijen die al via een andere collectie gelezen zijn tellen één
#: keer.
OPTIONELE_COLLECTIES: tuple[tuple[str, str | None], ...] = (("Receipts", None),)
BANKMUTATIES_PAD = "PaymentTransactions"
BANK_VENSTER_DAGEN = 3
TEKSTVELDEN: tuple[str, ...] = ("Reference", "Description", "Header")
DOSSIER_PREFIX_MIN = 10  # "2025.079507" (11 tekens) mag aanhaken bij één bekend "2025.079507.01"; "2025.079" niet


# ---- data ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RlzBoeking:
    collectie: str
    rlz_id: uuid.UUID
    boekstuk: str | None
    datum: date | None
    bedrag: Decimal | None
    entity_naam: str | None
    tekst: str
    dagboek: str | None = None
    heeft_bijlage: bool | None = None

    def feit(self) -> afleiding.BoekingsFeit:
        return afleiding.BoekingsFeit(
            collectie=self.collectie,
            boekstuk=self.boekstuk,
            entity_naam=self.entity_naam,
            tekst=self.tekst,
            heeft_bijlage=self.heeft_bijlage,
            dagboek=self.dagboek,
            bedrag=self.bedrag,
            datum=self.datum,
        )


@dataclass
class PandVoorstel:
    code: str
    adres: str
    plaats: str | None = None
    postcode: str | None = None
    aankoopdatum: date | None = None
    verkoopdatum: date | None = None
    dossiers: list[str] = field(default_factory=list)
    dossiers_onvolledig: list[str] = field(default_factory=list)
    koppelingen: list[KoppelingVoorstel] = field(default_factory=list)
    db_status: str = "nog niet geschreven"  # nieuw | bijgewerkt | ongewijzigd | mens_beschermd | dry-run
    varianten: list[str] = field(default_factory=list)  # straatvarianten in het cluster, representant eerst
    variant_codes: list[str] = field(default_factory=list)  # alle adres-codes in het cluster (upsert-sleutels)
    lijst_gebonden: bool = False
    salesforce_id: str | None = None

    def tel(self) -> dict[str, dict[str, int]]:
        uit: dict[str, dict[str, int]] = {}
        for k in self.koppelingen:
            uit.setdefault(k.soort, {}).setdefault(k.zekerheid, 0)
            uit[k.soort][k.zekerheid] += 1
        return uit

    @property
    def varianten_tekst(self) -> str:
        return f"varianten: {', '.join(self.varianten)}" if len(self.varianten) > 1 else ""


@dataclass(frozen=True)
class KoppelingVoorstel:
    pand_code: str
    boeking: RlzBoeking
    soort: str
    zekerheid: str
    reden: str


@dataclass(frozen=True)
class PandToewijzing:
    """Contract B → E: pand per RLZ-document (of bankmutatie)."""

    pand_code: str
    adres: str
    soort: str
    zekerheid: str
    herkomst: str  # mens | voorstel (DB) | afgeleid (deze run, geen DB-rij)


@dataclass
class AfleidingRapport:
    administratie_id: str
    rlz_admin_id: str | None
    dry_run: bool
    gegenereerd_op: str
    panden: list[PandVoorstel] = field(default_factory=list)
    gelezen: dict[str, int] = field(default_factory=dict)
    geen_signaal: dict[str, int] = field(default_factory=dict)  # per collectie → kandidaat Overhead (mens, run 2)
    meerduidig: int = 0
    bijlage_checks: int = 0
    bijlage_niet_gecontroleerd: int = 0
    fouten: list[str] = field(default_factory=list)
    overgeslagen: list[str] = field(default_factory=list)
    overhead_project: str = OVERHEAD_ONTBREEKT
    geschreven: dict[str, int] = field(default_factory=dict)
    # run 2 VGG
    bankmutaties_gelezen: int = 0
    bankmutaties_gebruikt: int = 0
    bankmutaties_document_aanwezig: int = 0  # bankregel overgeslagen: een document draagt de tekst al
    dossier_zonder_pand: list[str] = field(default_factory=list)  # onvolledig/zonder dossier-woord → geen pand
    lijst_meerduidig: list[str] = field(default_factory=list)
    lijst_panden: int | None = None  # None = geen lijst meegegeven

    @property
    def aantal_koppelingen(self) -> int:
        return sum(len(p.koppelingen) for p in self.panden)

    @property
    def soorten(self) -> dict[str, int]:
        uit: dict[str, int] = {}
        for p in self.panden:
            for k in p.koppelingen:
                uit[k.soort] = uit.get(k.soort, 0) + 1
        return dict(sorted(uit.items()))

    def als_dict(self) -> dict[str, Any]:
        def _k(k: KoppelingVoorstel) -> dict[str, Any]:
            b = k.boeking
            return {
                "collectie": b.collectie,
                "rlz_id": str(b.rlz_id),
                "boekstuk": b.boekstuk,
                "datum": b.datum.isoformat() if b.datum else None,
                "bedrag": str(b.bedrag) if b.bedrag is not None else None,
                "entity": b.entity_naam,
                "soort": k.soort,
                "zekerheid": k.zekerheid,
                "reden": k.reden,
            }

        return {
            "administratie_id": self.administratie_id,
            "rlz_admin_id": self.rlz_admin_id,
            "dry_run": self.dry_run,
            "gegenereerd_op": self.gegenereerd_op,
            "tellers": {
                "panden": len(self.panden),
                "koppelingen": self.aantal_koppelingen,
                "geen_signaal": sum(self.geen_signaal.values()),
                "meerduidig": self.meerduidig,
                "clusters_met_varianten": sum(1 for p in self.panden if len(p.varianten) > 1),
                "lijst_gebonden": sum(1 for p in self.panden if p.lijst_gebonden),
                "lijst_meerduidig": len(self.lijst_meerduidig),
                "bankmutaties_gelezen": self.bankmutaties_gelezen,
                "bankmutaties_gebruikt": self.bankmutaties_gebruikt,
                "bankmutaties_document_aanwezig": self.bankmutaties_document_aanwezig,
                "dossier_zonder_pand": len(self.dossier_zonder_pand),
                "soorten": self.soorten,
            },
            "gelezen": dict(sorted(self.gelezen.items())),
            "geen_signaal": dict(sorted(self.geen_signaal.items())),
            "bijlage_checks": self.bijlage_checks,
            "bijlage_niet_gecontroleerd": self.bijlage_niet_gecontroleerd,
            "overhead_project": self.overhead_project,
            "lijst_panden": self.lijst_panden,
            "lijst_meerduidig": list(self.lijst_meerduidig),
            "dossier_zonder_pand": list(self.dossier_zonder_pand),
            "geschreven": dict(self.geschreven),
            "fouten": list(self.fouten),
            "overgeslagen": list(self.overgeslagen),
            "panden": [
                {
                    "code": p.code,
                    "adres": p.adres,
                    "plaats": p.plaats,
                    "postcode": p.postcode,
                    "aankoopdatum": p.aankoopdatum.isoformat() if p.aankoopdatum else None,
                    "verkoopdatum": p.verkoopdatum.isoformat() if p.verkoopdatum else None,
                    "dossiers": list(p.dossiers),
                    "dossiers_onvolledig": list(p.dossiers_onvolledig),
                    "varianten": list(p.varianten),
                    "variant_codes": list(p.variant_codes),
                    "lijst_gebonden": p.lijst_gebonden,
                    "salesforce_id": p.salesforce_id,
                    "db_status": p.db_status,
                    "tellers": p.tel(),
                    "koppelingen": [_k(k) for k in sorted(p.koppelingen, key=_koppeling_sleutel)],
                }
                for p in sorted(self.panden, key=lambda p: p.code)
            ],
        }

    def als_json(self) -> str:
        return json.dumps(self.als_dict(), ensure_ascii=False, indent=2)


def _koppeling_sleutel(k: KoppelingVoorstel) -> tuple[str, str, str]:
    return (k.boeking.datum.isoformat() if k.boeking.datum else "", k.boeking.boekstuk or "", str(k.boeking.rlz_id))


# ---- RLZ lezen -----------------------------------------------------------------------------------


def tekst_uit_rij(rij: dict[str, Any], velden: Sequence[str] = TEKSTVELDEN) -> str:
    """Spatie-gescheiden samenvoeging van de ONTKNIPTE velden; een veld dat (hoofdletter-ongevoelig) letterlijk in een
    ander veld voorkomt telt één keer — RLZ herhaalt een op 20 tekens afgekapte Reference vóór de Description
    ("Burgemeester Norbrui" + "Burgemeester Norbruislaan 422")."""
    delen: list[str] = []
    for v in velden:
        w = ontknip(rij.get(v)) if isinstance(rij.get(v), str) else None
        if w:
            delen.append(w)
    uit: list[str] = []
    for i, d in enumerate(delen):
        laag = d.lower()
        if any(j != i and laag in ander.lower() and (len(ander) > len(d) or j < i) for j, ander in enumerate(delen)):
            continue
        uit.append(d)
    return " ".join(uit)


def _naar_boeking(collectie: str, rij: dict[str, Any]) -> RlzBoeking | None:
    try:
        rlz_id = uuid.UUID(str(rij.get("id")))
    except (ValueError, TypeError):
        return None
    _, entity_naam = entity_van(rij)
    dagboek = rij.get("JournalEntryDiary")
    dagboek_naam = (dagboek.get("Name") or dagboek.get("Description")) if isinstance(dagboek, dict) else None
    return RlzBoeking(
        collectie=collectie,
        rlz_id=rlz_id,
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        datum=als_datum(rij.get("Date")) or als_datum(rij.get("BookDate")),
        bedrag=als_bedrag(rij.get("BaseInvoiceAmount")),
        entity_naam=entity_naam,
        tekst=tekst_uit_rij(rij),
        dagboek=str(dagboek_naam) if dagboek_naam else None,
    )


def _naar_bankmutatie(rij: dict[str, Any]) -> RlzBoeking | None:
    """PaymentTransaction → boeking-feit: Name = tegenpartij, Reference (ontknipt) = tekst, Amount mét teken."""
    try:
        rlz_id = uuid.UUID(str(rij.get("id")))
    except (ValueError, TypeError):
        return None
    naam = rij.get("Name")
    return RlzBoeking(
        collectie=BANKMUTATIES_PAD,
        rlz_id=rlz_id,
        boekstuk=str(rij["TransactionId"]) if rij.get("TransactionId") else None,
        datum=als_datum(rij.get("BookDate")) or als_datum(rij.get("Date")),
        bedrag=als_bedrag(rij.get("Amount")),
        entity_naam=" ".join(str(naam).split()) if isinstance(naam, str) and naam.strip() else None,
        tekst=tekst_uit_rij(rij, ("Reference", "Description")),
        dagboek=None,
    )


def lees_boekingen(client: LeesClient, rapport: AfleidingRapport, *, max_bijlage_checks: int) -> list[RlzBoeking]:
    """Alle documenten van de drie collecties (+ Receipts als leesbaar, ontdubbeld op id); memorialen mét adres/dossier
    krijgen een bijlagecheck (begrensd)."""
    uit: list[RlzBoeking] = []
    gezien: set[uuid.UUID] = set()
    for pad, expand in COLLECTIES + OPTIONELE_COLLECTIES:
        optioneel = (pad, expand) in OPTIONELE_COLLECTIES
        uitkomst = lees_collectie(client, pad, expand=expand)
        if uitkomst.fout is not None:
            regel = f"{pad}: {uitkomst.fout.status_code} — collectie niet gelezen ({uitkomst.fout.body[:120]})"
            (rapport.overgeslagen if optioneel else rapport.fouten).append(regel)
            continue
        if not uitkomst.expand_gelukt:
            rapport.overgeslagen.append(f"{pad}: $expand={expand} geweigerd — gelezen zonder relatie-/dagboeknaam")
        rapport.gelezen[pad] = len(uitkomst.rijen)
        for b in (_naar_boeking(pad, r) for r in uitkomst.rijen):
            if b is None or b.rlz_id in gezien:
                continue
            gezien.add(b.rlz_id)
            uit.append(b)

    budget = max(0, int(max_bijlage_checks))
    kandidaten = [
        b
        for b in uit
        if b.collectie == "ManualJournals"
        and afleiding.is_memoriaal(b.feit())
        and (afleiding.adres_uit_tekst(b.tekst) or afleiding.dossiers_uit_tekst(b.tekst).volledig)
    ]
    kandidaten.sort(key=lambda b: (b.datum or date.min, str(b.rlz_id)), reverse=True)
    gecheckt: dict[uuid.UUID, bool | None] = {}
    for b in kandidaten:
        if rapport.bijlage_checks >= budget:
            rapport.bijlage_niet_gecontroleerd += 1
            continue
        rapport.bijlage_checks += 1
        gecheckt[b.rlz_id] = heeft_bijlage(client, b.collectie, str(b.rlz_id))
    return [
        RlzBoeking(**{**asdict(b), "heeft_bijlage": gecheckt.get(b.rlz_id, b.heeft_bijlage)})
        if b.rlz_id in gecheckt
        else b
        for b in uit
    ]


def lees_bankmutaties(client: LeesClient, rapport: AfleidingRapport) -> list[RlzBoeking]:
    """Seam: PaymentTransactions als boeking-feiten (collectie "PaymentTransactions"). Een weigerende route is een
    OVERGESLAGEN-regel (de afleiding op documenten loopt door)."""
    uitkomst = lees_collectie(client, BANKMUTATIES_PAD)
    if uitkomst.fout is not None:
        rapport.overgeslagen.append(
            f"{BANKMUTATIES_PAD}: {uitkomst.fout.status_code} — bankmutaties niet gelezen ({uitkomst.fout.body[:120]})"
        )
        return []
    uit = [b for b in (_naar_bankmutatie(r) for r in uitkomst.rijen) if b is not None]
    rapport.gelezen[BANKMUTATIES_PAD] = len(uitkomst.rijen)
    rapport.bankmutaties_gelezen = len(uit)
    return uit


# ---- voorstellen bouwen (puur) --------------------------------------------------------------------


def _bankmutatie_gedekt(b: RlzBoeking, gedekt: dict[Decimal, list[date]]) -> bool:
    if b.bedrag is None or b.datum is None:
        return False
    return any(abs((d - b.datum).days) <= BANK_VENSTER_DAGEN for d in gedekt.get(abs(b.bedrag), ()))


def bouw_voorstellen(
    boekingen: list[RlzBoeking],
    rapport: AfleidingRapport | None = None,
    *,
    pandenlijst_bron: pandenlijst.PandenlijstBron | None = None,
) -> dict[str, PandVoorstel]:
    """Classificeer élk document, cluster de adressen (of bind ze aan de pandenlijst) en bundel per pand-code.
    Alleen-dossier-documenten haken aan bij een pand dat dit dossier al draagt; een volledig notarisdossier mét het
    woord
    "dossier" in de tekst wordt anders een dossier-pand (code `dossier-<nr>`, adres onbekend); onvolledig/zonder woord =
    geen pand (zichtbaar in `rapport.dossier_zonder_pand`)."""
    documenten = [b for b in boekingen if b.collectie != BANKMUTATIES_PAD]
    bankmutaties = [b for b in boekingen if b.collectie == BANKMUTATIES_PAD]
    geclassificeerd: list[tuple[RlzBoeking, afleiding.Classificatie]] = []
    gedekt: dict[Decimal, list[date]] = {}

    for b in sorted(documenten, key=lambda x: (x.datum or date.min, str(x.rlz_id))):
        c = afleiding.classificeer(b.feit())
        if c is None:
            if rapport is not None:
                rapport.geen_signaal[b.collectie] = rapport.geen_signaal.get(b.collectie, 0) + 1
            continue
        if c.meerduidig and rapport is not None:
            rapport.meerduidig += 1
        geclassificeerd.append((b, c))
        if b.bedrag is not None and b.datum is not None:
            gedekt.setdefault(abs(b.bedrag), []).append(b.datum)

    for b in sorted(bankmutaties, key=lambda x: (x.datum or date.min, str(x.rlz_id))):
        if _bankmutatie_gedekt(b, gedekt):
            if rapport is not None:
                rapport.bankmutaties_document_aanwezig += 1
            continue
        c = afleiding.classificeer_bankmutatie(b.feit())
        if c is None:
            continue
        if rapport is not None:
            rapport.bankmutaties_gebruikt += 1
            if c.meerduidig:
                rapport.meerduidig += 1
        geclassificeerd.append((b, c))

    # -- clusteren / binden aan de lijst
    lijst = list(pandenlijst_bron.panden()) if pandenlijst_bron is not None else None
    if rapport is not None and lijst is not None:
        rapport.lijst_panden = len(lijst)
    adressen = [c.adres for _, c in geclassificeerd if c.adres is not None]
    clusters = pandenlijst.cluster_adressen(adressen)
    panden: dict[str, PandVoorstel] = {}
    cluster_naar_code: dict[int, str] = {}
    for i, cl in enumerate(clusters):
        code = cl.representant.code
        adres_tekst = cl.representant.weergave_kort
        plaats, postcode = cl.representant.plaats, cl.representant.postcode
        gebonden, sf = False, None
        if lijst is not None:
            match = pandenlijst.zoek_in_lijst(cl.representant, lijst)
            for lid in cl.leden:
                if match.gebonden or match.meerduidig:
                    break
                match = pandenlijst.zoek_in_lijst(lid, lijst)
            if match.gebonden and match.pand is not None:
                code, gebonden, sf = match.pand.code, True, match.pand.salesforce_id
                adres_tekst = match.pand.als_adres.weergave_kort
                plaats, postcode = match.pand.plaats or plaats, match.pand.postcode or postcode
            elif match.meerduidig and rapport is not None:
                rapport.lijst_meerduidig.append(
                    f"{adres_tekst}: {len(match.kandidaten)} lijst-panden even goed "
                    f"({', '.join(k.als_adres.weergave for k in match.kandidaten)}) — niet gebonden"
                )
        p = panden.get(code)
        if p is None:
            p = panden[code] = PandVoorstel(code=code, adres=adres_tekst, plaats=plaats, postcode=postcode)
        p.lijst_gebonden = p.lijst_gebonden or gebonden
        p.salesforce_id = p.salesforce_id or sf
        if not p.plaats and plaats:
            p.plaats = plaats
        if not p.postcode and postcode:
            p.postcode = postcode
        for v in cl.varianten:
            if v not in p.varianten:
                p.varianten.append(v)
        for vc in cl.codes:
            if vc not in p.variant_codes:
                p.variant_codes.append(vc)
        cluster_naar_code[i] = code
    adres_naar_code: dict[afleiding.AdresVoorstel, str] = {}
    for i, cl in enumerate(clusters):
        for lid in cl.leden:
            adres_naar_code[lid] = cluster_naar_code[i]

    dossier_naar_code: dict[str, str] = {}
    uitgesteld: list[tuple[RlzBoeking, afleiding.Classificatie]] = []
    for b, c in geclassificeerd:
        if c.adres is None:
            uitgesteld.append((b, c))
            continue
        p = panden[adres_naar_code[c.adres]]
        _voeg_koppeling_toe(p, b, c, dossier_naar_code)

    for b, c in uitgesteld:
        code = next((dossier_naar_code[d] for d in c.dossiers if d in dossier_naar_code), None)
        if code is None:
            for onv in c.dossiers_onvolledig:
                if len(onv) < DOSSIER_PREFIX_MIN:
                    continue
                treffers = {dossier_naar_code[d] for d in dossier_naar_code if d.startswith(onv)}
                if len(treffers) == 1:
                    code = treffers.pop()
                    break
        if code is None and c.dossiers and c.dossierwoord:
            code = f"dossier-{afleiding._norm(c.dossiers[0])}"
            panden.setdefault(code, PandVoorstel(code=code, adres=f"dossier {c.dossiers[0]} (adres onbekend)"))
        if code is None:
            if rapport is not None:
                reden = "onvolledig dossiernummer" if not c.dossiers else "geen dossier-woord in de tekst"
                rapport.dossier_zonder_pand.append(
                    f"{b.boekstuk or b.rlz_id}: {', '.join(c.dossiers or c.dossiers_onvolledig)} — {reden}, geen pand"
                )
            continue
        _voeg_koppeling_toe(panden[code], b, c, dossier_naar_code)
    return panden


def _voeg_koppeling_toe(
    p: PandVoorstel, b: RlzBoeking, c: afleiding.Classificatie, dossier_naar_code: dict[str, str]
) -> None:
    for d in c.dossiers:
        if d not in p.dossiers:
            p.dossiers.append(d)
        dossier_naar_code.setdefault(d, p.code)
    for d in c.dossiers_onvolledig:
        if d not in p.dossiers_onvolledig and not any(v.startswith(d) for v in p.dossiers):
            p.dossiers_onvolledig.append(d)
    if c.soort == "aankoop" and b.datum and (p.aankoopdatum is None or b.datum < p.aankoopdatum):
        p.aankoopdatum = b.datum
    if c.soort == "verkoop" and b.datum and (p.verkoopdatum is None or b.datum > p.verkoopdatum):
        p.verkoopdatum = b.datum
    reden = c.reden
    if p.varianten_tekst:
        reden = f"{reden} · {p.varianten_tekst}"
    p.koppelingen.append(
        KoppelingVoorstel(pand_code=p.code, boeking=b, soort=c.soort, zekerheid=c.zekerheid, reden=reden)
    )


# ---- DB -------------------------------------------------------------------------------------------


def overhead_project_status(session, administratie_id: uuid.UUID) -> str:  # noqa: ANN001
    from app.sync.models import ProjectCache

    rijen = session.scalars(
        select(ProjectCache).where(
            ProjectCache.administratie_id == administratie_id, ProjectCache.naam.ilike(OVERHEAD_PROJECTNAAM)
        )
    ).all()
    actief = [r for r in rijen if r.is_actief is not False and r.verdwenen_uit_bron_op is None]
    if actief:
        return f"Overhead-project aanwezig: {actief[0].naam} ({actief[0].id})"
    if rijen:
        return f"Overhead-project alleen inactief/verdwenen in de projectcache ({rijen[0].id}) — {OVERHEAD_ONTBREEKT}"
    return OVERHEAD_ONTBREEKT


def _zoek_pand(session, administratie_id: uuid.UUID, v: PandVoorstel) -> Pand | None:  # noqa: ANN001
    """Bestaande rij op de voorstel-code, anders op een variant-code van hetzelfde cluster (een eerdere run kan een
    andere variant als representant gekozen hebben — de bestaande rij wint, geen tweede pand)."""
    codes = [v.code] + [c for c in v.variant_codes if c != v.code]
    rijen = session.scalars(select(Pand).where(Pand.administratie_id == administratie_id, Pand.code.in_(codes))).all()
    for code in codes:
        for r in rijen:
            if r.code == code:
                return r
    return None


def schrijf_voorstellen(
    session,  # noqa: ANN001
    *,
    administratie_id: uuid.UUID,
    panden: dict[str, PandVoorstel],
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
) -> dict[str, int]:
    """Upsert; herkomst `mens` / status ≠ voorstel = beschermd. Audit per gemuteerd pand en per nieuwe/gewijzigde
    koppeling (oud → nieuw)."""
    stats = {
        "pand_nieuw": 0,
        "pand_bijgewerkt": 0,
        "pand_ongewijzigd": 0,
        "pand_beschermd": 0,
        "koppeling_nieuw": 0,
        "koppeling_bijgewerkt": 0,
        "koppeling_ongewijzigd": 0,
        "koppeling_beschermd": 0,
    }
    for code in sorted(panden):
        v = panden[code]
        pand = _zoek_pand(session, administratie_id, v)
        nieuw = {
            "adres": v.adres,
            "plaats": v.plaats,
            "postcode": v.postcode,
            "aankoopdatum": v.aankoopdatum.isoformat() if v.aankoopdatum else None,
            "verkoopdatum": v.verkoopdatum.isoformat() if v.verkoopdatum else None,
            "notaris_dossiernummers": list(v.dossiers),
        }
        if pand is None:
            pand = Pand(
                administratie_id=administratie_id,
                code=code,
                adres=v.adres,
                plaats=v.plaats,
                postcode=v.postcode,
                aankoopdatum=v.aankoopdatum,
                verkoopdatum=v.verkoopdatum,
                notaris_dossiernummers=list(v.dossiers),
                herkomst=PandHerkomst.AFGELEID.value,
                status=PandStatus.VOORSTEL.value,
            )
            session.add(pand)
            session.flush()
            stats["pand_nieuw"] += 1
            v.db_status = "nieuw"
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="pand",
                record_id=pand.id,
                actie="pand_voorstel_aangemaakt",
                correlatie_id=correlatie_id,
                oude_waarde=None,
                nieuwe_waarde={**nieuw, "herkomst": pand.herkomst, "status": pand.status, "varianten": v.varianten},
                administratie_id=administratie_id,
            )
        elif pand.herkomst != PandHerkomst.AFGELEID.value or pand.status != PandStatus.VOORSTEL.value:
            stats["pand_beschermd"] += 1
            v.db_status = "mens_beschermd"
        else:
            oud = {
                "adres": pand.adres,
                "plaats": pand.plaats,
                "postcode": pand.postcode,
                "aankoopdatum": pand.aankoopdatum.isoformat() if pand.aankoopdatum else None,
                "verkoopdatum": pand.verkoopdatum.isoformat() if pand.verkoopdatum else None,
                "notaris_dossiernummers": list(pand.notaris_dossiernummers or []),
            }
            samengevoegd = {
                **nieuw,
                "notaris_dossiernummers": sorted(set(oud["notaris_dossiernummers"]) | set(v.dossiers)),
            }
            if samengevoegd == oud:
                stats["pand_ongewijzigd"] += 1
                v.db_status = "ongewijzigd"
            else:
                pand.adres, pand.plaats, pand.postcode = v.adres, v.plaats, v.postcode
                pand.aankoopdatum, pand.verkoopdatum = v.aankoopdatum, v.verkoopdatum
                pand.notaris_dossiernummers = samengevoegd["notaris_dossiernummers"]
                stats["pand_bijgewerkt"] += 1
                v.db_status = "bijgewerkt"
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="pand",
                    record_id=pand.id,
                    actie="pand_voorstel_bijgewerkt",
                    correlatie_id=correlatie_id,
                    oude_waarde=oud,
                    nieuwe_waarde=samengevoegd,
                    administratie_id=administratie_id,
                )
        for k in v.koppelingen:
            _schrijf_koppeling(
                session,
                administratie_id=administratie_id,
                pand=pand,
                k=k,
                actor_id=actor_id,
                correlatie_id=correlatie_id,
                stats=stats,
            )
    return stats


def _schrijf_koppeling(
    session,  # noqa: ANN001
    *,
    administratie_id: uuid.UUID,
    pand: Pand,
    k: KoppelingVoorstel,
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    stats: dict[str, int],
) -> None:
    sleutel = bron_sleutel_voor(rlz_document_id=k.boeking.rlz_id, document_id=None)
    rij = session.scalars(
        select(PandBoeking).where(
            PandBoeking.administratie_id == administratie_id,
            PandBoeking.bron_sleutel == sleutel,
            PandBoeking.pand_id == pand.id,
        )
    ).first()
    nieuw = {"soort": k.soort, "zekerheid": k.zekerheid, "reden": k.reden, "rlz_boekstuknummer": k.boeking.boekstuk}
    if rij is None:
        rij = PandBoeking(
            administratie_id=administratie_id,
            pand_id=pand.id,
            rlz_document_id=k.boeking.rlz_id,
            rlz_boekstuknummer=k.boeking.boekstuk,
            rlz_collectie=k.boeking.collectie,
            bron_sleutel=sleutel,
            soort=k.soort,
            herkomst=PandBoekingHerkomst.VOORSTEL.value,
            zekerheid=k.zekerheid,
            reden=k.reden,
            datum=k.boeking.datum,
            bedrag=k.boeking.bedrag,
        )
        session.add(rij)
        session.flush()
        stats["koppeling_nieuw"] += 1
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="pand_boeking",
            record_id=rij.id,
            actie="pand_boeking_voorstel_aangemaakt",
            correlatie_id=correlatie_id,
            oude_waarde=None,
            nieuwe_waarde={**nieuw, "pand_code": pand.code, "rlz_document_id": str(k.boeking.rlz_id)},
            administratie_id=administratie_id,
        )
        return
    if rij.herkomst == PandBoekingHerkomst.MENS.value or rij.bevestigd_op is not None:
        stats["koppeling_beschermd"] += 1
        return
    oud = {
        "soort": rij.soort,
        "zekerheid": rij.zekerheid,
        "reden": rij.reden,
        "rlz_boekstuknummer": rij.rlz_boekstuknummer,
    }
    if oud == nieuw:
        stats["koppeling_ongewijzigd"] += 1
        return
    rij.soort, rij.zekerheid, rij.reden, rij.rlz_boekstuknummer = k.soort, k.zekerheid, k.reden, k.boeking.boekstuk
    rij.datum, rij.bedrag = k.boeking.datum, k.boeking.bedrag
    stats["koppeling_bijgewerkt"] += 1
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="pand_boeking",
        record_id=rij.id,
        actie="pand_boeking_voorstel_bijgewerkt",
        correlatie_id=correlatie_id,
        oude_waarde=oud,
        nieuwe_waarde=nieuw,
        administratie_id=administratie_id,
    )


# ---- hoofdfunctie ---------------------------------------------------------------------------------


def leid_af(
    administratie_id: uuid.UUID,
    *,
    dry_run: bool = True,
    client: LeesClient | None = None,
    client_factory: Callable[[str], RlzClient] | None = None,
    max_bijlage_checks: int = MAX_BIJLAGE_CHECKS_DEFAULT,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    nu: datetime | None = None,
    pandenlijst_bron: pandenlijst.PandenlijstBron | None = None,
    met_bankmutaties: bool = True,
) -> AfleidingRapport:
    """Default dry-run: leest RLZ + DB, schrijft niets. `dry_run=False` (CLI `--schrijf`) schrijft voorstellen —
    nooit bevestigingen. Een meegegeven `client` (tests) omzeilt de credential-store."""
    from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

    rlz_admin_id: str | None = None
    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
    except Exception as exc:  # noqa: BLE001 — zonder rlz_admin_id is er geen client; melden, niet crashen
        if client is None:
            raise
        logger.info("rlz_admin_id niet gelezen voor %s: %s", administratie_id, exc)

    rapport = AfleidingRapport(
        administratie_id=str(administratie_id),
        rlz_admin_id=rlz_admin_id,
        dry_run=dry_run,
        gegenereerd_op=(nu or datetime.now(UTC)).isoformat(timespec="seconds"),
    )
    eigen_client = client is None
    if client is None:
        assert rlz_admin_id is not None
        maak = client_factory or (lambda rid: client_voor_rlz_admin_id(rid).for_administration(rid))
        client = maak(rlz_admin_id)
    try:
        boekingen = lees_boekingen(client, rapport, max_bijlage_checks=max_bijlage_checks)
        if met_bankmutaties:
            boekingen = boekingen + lees_bankmutaties(client, rapport)
    finally:
        if eigen_client and hasattr(client, "close"):
            client.close()  # type: ignore[union-attr]

    panden = bouw_voorstellen(boekingen, rapport, pandenlijst_bron=pandenlijst_bron)
    rapport.panden = sorted(panden.values(), key=lambda p: p.code)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rapport.overhead_project = overhead_project_status(session, administratie_id)
        if dry_run:
            for v in rapport.panden:
                huidig = _zoek_pand(session, administratie_id, v)
                if huidig is None:
                    v.db_status = "dry-run: zou nieuw zijn"
                elif huidig.herkomst != PandHerkomst.AFGELEID.value or huidig.status != PandStatus.VOORSTEL.value:
                    v.db_status = "dry-run: mens_beschermd (niet overschreven)"
                else:
                    v.db_status = "dry-run: bestaand voorstel, zou bijgewerkt worden"
            session.rollback()
        else:
            rapport.geschreven = schrijf_voorstellen(
                session,
                administratie_id=administratie_id,
                panden=panden,
                actor_id=actor_id,
                correlatie_id=uuid.uuid4(),
            )
    return rapport


# ---- contract B → E ------------------------------------------------------------------------------


def pand_per_document(
    administratie_id: uuid.UUID,
    *,
    boekingen: list[RlzBoeking] | None = None,
    pandenlijst_bron: pandenlijst.PandenlijstBron | None = None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
) -> dict[uuid.UUID, PandToewijzing]:
    """Pand per RLZ-document-id. Bron = DB (`pand_boeking` mét herkomst `mens` of `bevestigd_op` → herkomst "mens",
    altijd leidend; overige DB-rijen → "voorstel"), aangevuld met de afleiding (`bouw_voorstellen` over `boekingen`,
    herkomst "afgeleid") voor documenten zonder DB-rij. Geen RLZ-lezen hier: E geeft de boekingen mee. E neemt alleen
    `herkomst == "mens"` of `zekerheid == "hoog"` als pand-analytic."""
    uit: dict[uuid.UUID, PandToewijzing] = {}
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rijen = session.execute(
            select(PandBoeking, Pand)
            .join(Pand, Pand.id == PandBoeking.pand_id)
            .where(PandBoeking.administratie_id == administratie_id, PandBoeking.rlz_document_id.is_not(None))
            .order_by(PandBoeking.aangemaakt_op, PandBoeking.id)
        ).all()
        for rij, pand in rijen:
            mens = rij.herkomst == PandBoekingHerkomst.MENS.value or rij.bevestigd_op is not None
            if pand.status == PandStatus.VERVALLEN.value and not mens:
                continue
            bestaand = uit.get(rij.rlz_document_id)
            if bestaand is not None and bestaand.herkomst == "mens" and not mens:
                continue
            uit[rij.rlz_document_id] = PandToewijzing(
                pand_code=pand.code,
                adres=pand.adres,
                soort=rij.soort,
                zekerheid=rij.zekerheid,
                herkomst="mens" if mens else "voorstel",
            )
        session.rollback()
    if boekingen:
        for p in bouw_voorstellen(boekingen, None, pandenlijst_bron=pandenlijst_bron).values():
            for k in p.koppelingen:
                if k.boeking.rlz_id not in uit:
                    uit[k.boeking.rlz_id] = PandToewijzing(
                        pand_code=p.code, adres=p.adres, soort=k.soort, zekerheid=k.zekerheid, herkomst="afgeleid"
                    )
    return uit


# ---- weergave -------------------------------------------------------------------------------------


def als_markdown(rapport: AfleidingRapport, *, administratie_naam: str | None = None) -> str:
    kop = administratie_naam or rapport.administratie_id
    regels = [
        f"### Pandenregister-afleiding {kop} (RLZ {rapport.rlz_admin_id or '?'}, "
        f"{'DRY-RUN — niets geschreven' if rapport.dry_run else 'GESCHREVEN als voorstel'}, {rapport.gegenereerd_op})",
        "",
        f"- Gelezen: {', '.join(f'{k} {v}' for k, v in sorted(rapport.gelezen.items())) or 'niets'}",
        f"- Panden (voorstel): {len(rapport.panden)} · koppelingen: {rapport.aantal_koppelingen} · "
        f"clusters met varianten: {sum(1 for p in rapport.panden if len(p.varianten) > 1)}",
        f"- Soorten: {', '.join(f'{k} {v}' for k, v in rapport.soorten.items()) or '—'}",
        f"- Geen pand-signaal (kandidaat Overhead, mens beslist in run 2): "
        f"{', '.join(f'{k} {v}' for k, v in sorted(rapport.geen_signaal.items())) or '0'}"
        + (f" · meerduidig adres: {rapport.meerduidig}" if rapport.meerduidig else ""),
        f"- Bankmutaties: {rapport.bankmutaties_gelezen} gelezen, {rapport.bankmutaties_gebruikt} gebruikt, "
        f"{rapport.bankmutaties_document_aanwezig} overgeslagen (document draagt de tekst al)",
        f"- Bijlagechecks memoriaal: {rapport.bijlage_checks} gedaan, "
        f"{rapport.bijlage_niet_gecontroleerd} niet (grens)",
        "- Pandenlijst: "
        + (
            f"{rapport.lijst_panden} panden, {sum(1 for p in rapport.panden if p.lijst_gebonden)} gebonden, "
            f"{len(rapport.lijst_meerduidig)} meerduidig"
            if rapport.lijst_panden is not None
            else "geen lijst meegegeven (clusteren op adres)"
        ),
        f"- Dossier zonder pand (onvolledig / zonder dossier-woord): {len(rapport.dossier_zonder_pand)}",
        f"- {rapport.overhead_project}",
    ]
    if rapport.geschreven:
        regels.append("- Geschreven: " + ", ".join(f"{k} {v}" for k, v in rapport.geschreven.items()))
    for f in rapport.fouten:
        regels.append(f"- FOUT {f}")
    for o in rapport.overgeslagen:
        regels.append(f"- OVERGESLAGEN {o}")
    for m in rapport.lijst_meerduidig:
        regels.append(f"- MEERDUIDIG (lijst) {m}")
    regels += [
        "",
        "| Pand | Plaats | Aankoop | Verkoop | Dossiers | Koppelingen (soort: hoog/midden/laag) | Varianten | Lijst "
        "| DB |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in rapport.panden:
        tel = p.tel()
        kop_tel = "; ".join(
            f"{soort}: {tel[soort].get('hoog', 0)}/{tel[soort].get('midden', 0)}/{tel[soort].get('laag', 0)}"
            for soort in sorted(tel)
        )
        aankoop = p.aankoopdatum.isoformat() if p.aankoopdatum else "—"
        verkoop = p.verkoopdatum.isoformat() if p.verkoopdatum else "—"
        dossiers = ", ".join(p.dossiers + [f"{d}… (onvolledig)" for d in p.dossiers_onvolledig]) or "—"
        varianten = ", ".join(p.varianten[1:]) or "—"
        lijst = (f"sf {p.salesforce_id}" if p.salesforce_id else "gebonden") if p.lijst_gebonden else "—"
        regels.append(
            f"| {p.adres} | {p.plaats or '—'} | {aankoop} | {verkoop} | {dossiers} | {kop_tel} | {varianten} | "
            f"{lijst} | {p.db_status} |"
        )
    if not rapport.panden:
        regels.append("| _geen_ | | | | | | | | |")
    if rapport.dossier_zonder_pand:
        regels += ["", "Dossier zonder pand:"] + [f"- {d}" for d in rapport.dossier_zonder_pand]
    return "\n".join(regels) + "\n"
