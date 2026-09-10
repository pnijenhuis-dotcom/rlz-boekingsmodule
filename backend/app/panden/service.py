"""Pandenregister afleiden uit RLZ (bundel 10-09 blok D2) — `leid_af(administratie_id, *, dry_run, client)`.

Leest ManualJournals, SalesInvoices en PurchaseInvoices gepagineerd (`app/rlz/lezen.py`), classificeert élk document
deterministisch (`afleiding.classificeer`), bundelt per pand-code en schrijft — alleen mét `dry_run=False` —
`pand`-voorstellen (status `voorstel`, herkomst `afgeleid`) en `pand_boeking`-voorstellen (herkomst `voorstel`).
Idempotent: upsert op (administratie, code) resp. (administratie, bron_sleutel, pand); een rij met herkomst `mens` of
een pand dat niet meer `voorstel` is wordt NOOIT overschreven (mens wint). Niets wordt automatisch bevestigd.

Overhead-project: alle niet-pand-kosten horen in run 2 op het project "Overhead". Projectaanmaak is in deze module een
RLZ-write (`app/projecten/kantoor.py::maak_project_aan` → `put_project`) en gebeurt hier dus NIET — ook niet buiten
dry-run; het rapport zegt "aanwezig" of "ontbreekt — aanmaken in run 2".

AI-aanvulling uit de notaris-PDF: bewust niet gebouwd (seam: `BoekingsFeit.tekst` is de enige tekstbron; run 2 kan
daar een mens-bevestigde PDF-extractie aan toevoegen). Geen RLZ-/Odoo-writes. Geld in Decimal."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.panden import afleiding
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
    koppelingen: list[KoppelingVoorstel] = field(default_factory=list)
    db_status: str = "nog niet geschreven"  # nieuw | bijgewerkt | ongewijzigd | mens_beschermd | dry-run

    def tel(self) -> dict[str, dict[str, int]]:
        uit: dict[str, dict[str, int]] = {}
        for k in self.koppelingen:
            uit.setdefault(k.soort, {}).setdefault(k.zekerheid, 0)
            uit[k.soort][k.zekerheid] += 1
        return uit


@dataclass(frozen=True)
class KoppelingVoorstel:
    pand_code: str
    boeking: RlzBoeking
    soort: str
    zekerheid: str
    reden: str


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

    @property
    def aantal_koppelingen(self) -> int:
        return sum(len(p.koppelingen) for p in self.panden)

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
            },
            "gelezen": dict(sorted(self.gelezen.items())),
            "geen_signaal": dict(sorted(self.geen_signaal.items())),
            "bijlage_checks": self.bijlage_checks,
            "bijlage_niet_gecontroleerd": self.bijlage_niet_gecontroleerd,
            "overhead_project": self.overhead_project,
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


def _naar_boeking(collectie: str, rij: dict[str, Any]) -> RlzBoeking | None:
    try:
        rlz_id = uuid.UUID(str(rij.get("id")))
    except (ValueError, TypeError):
        return None
    _, entity_naam = entity_van(rij)
    dagboek = rij.get("JournalEntryDiary")
    dagboek_naam = (dagboek.get("Name") or dagboek.get("Description")) if isinstance(dagboek, dict) else None
    tekst = " ".join(
        " ".join(str(rij[v]).split()) for v in ("Reference", "Description", "Header") if isinstance(rij.get(v), str)
    )
    return RlzBoeking(
        collectie=collectie,
        rlz_id=rlz_id,
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        datum=als_datum(rij.get("Date")) or als_datum(rij.get("BookDate")),
        bedrag=als_bedrag(rij.get("BaseInvoiceAmount")),
        entity_naam=entity_naam,
        tekst=tekst,
        dagboek=str(dagboek_naam) if dagboek_naam else None,
    )


def lees_boekingen(client: LeesClient, rapport: AfleidingRapport, *, max_bijlage_checks: int) -> list[RlzBoeking]:
    """Alle documenten van de drie collecties; memorialen mét adres/dossier krijgen een bijlagecheck (begrensd)."""
    uit: list[RlzBoeking] = []
    for pad, expand in COLLECTIES:
        uitkomst = lees_collectie(client, pad, expand=expand)
        if uitkomst.fout is not None:
            rapport.fouten.append(
                f"{pad}: {uitkomst.fout.status_code} — collectie niet gelezen ({uitkomst.fout.body[:120]})"
            )
            continue
        if not uitkomst.expand_gelukt:
            rapport.overgeslagen.append(f"{pad}: $expand={expand} geweigerd — gelezen zonder relatie-/dagboeknaam")
        rapport.gelezen[pad] = len(uitkomst.rijen)
        uit.extend(b for b in (_naar_boeking(pad, r) for r in uitkomst.rijen) if b is not None)

    budget = max(0, int(max_bijlage_checks))
    kandidaten = [
        b
        for b in uit
        if b.collectie == "ManualJournals"
        and (afleiding.adres_uit_tekst(b.tekst) or afleiding.dossiernummers_uit_tekst(b.tekst))
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


# ---- voorstellen bouwen (puur) --------------------------------------------------------------------


def bouw_voorstellen(boekingen: list[RlzBoeking], rapport: AfleidingRapport | None = None) -> dict[str, PandVoorstel]:
    """Classificeer élk document en bundel per pand-code. Alleen-dossier-documenten haken aan bij een pand dat dit
    dossier al draagt; anders ontstaat een dossier-pand (code `dossier-<nr>`, adres onbekend) voor de mens."""
    panden: dict[str, PandVoorstel] = {}
    dossier_naar_code: dict[str, str] = {}
    uitgesteld: list[tuple[RlzBoeking, afleiding.Classificatie]] = []

    for b in sorted(boekingen, key=lambda x: (x.datum or date.min, str(x.rlz_id))):
        c = afleiding.classificeer(b.feit())
        if c is None:
            if rapport is not None:
                rapport.geen_signaal[b.collectie] = rapport.geen_signaal.get(b.collectie, 0) + 1
                if len(afleiding.adressen_uit_tekst(b.tekst)) > 1:
                    rapport.meerduidig += 1
            continue
        if c.adres is None:
            uitgesteld.append((b, c))
            continue
        p = panden.get(c.adres.code)
        if p is None:
            p = panden[c.adres.code] = PandVoorstel(
                code=c.adres.code,
                adres=c.adres.weergave.split(",")[0],
                plaats=c.adres.plaats,
                postcode=c.adres.postcode,
            )
        if not p.plaats and c.adres.plaats:
            p.plaats = c.adres.plaats
        if not p.postcode and c.adres.postcode:
            p.postcode = c.adres.postcode
        _voeg_koppeling_toe(p, b, c, dossier_naar_code)

    for b, c in uitgesteld:
        code = next((dossier_naar_code[d] for d in c.dossiers if d in dossier_naar_code), None)
        if code is None:
            code = f"dossier-{afleiding._norm(c.dossiers[0])}"
            panden.setdefault(code, PandVoorstel(code=code, adres=f"dossier {c.dossiers[0]} (adres onbekend)"))
        _voeg_koppeling_toe(panden[code], b, c, dossier_naar_code)
    return panden


def _voeg_koppeling_toe(
    p: PandVoorstel, b: RlzBoeking, c: afleiding.Classificatie, dossier_naar_code: dict[str, str]
) -> None:
    for d in c.dossiers:
        if d not in p.dossiers:
            p.dossiers.append(d)
        dossier_naar_code.setdefault(d, p.code)
    if c.soort == "aankoop" and b.datum and (p.aankoopdatum is None or b.datum < p.aankoopdatum):
        p.aankoopdatum = b.datum
    if c.soort == "verkoop" and b.datum and (p.verkoopdatum is None or b.datum > p.verkoopdatum):
        p.verkoopdatum = b.datum
    p.koppelingen.append(
        KoppelingVoorstel(pand_code=p.code, boeking=b, soort=c.soort, zekerheid=c.zekerheid, reden=c.reden)
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
        pand = session.scalars(select(Pand).where(Pand.administratie_id == administratie_id, Pand.code == code)).first()
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
                nieuwe_waarde={**nieuw, "herkomst": pand.herkomst, "status": pand.status},
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
    finally:
        if eigen_client and hasattr(client, "close"):
            client.close()  # type: ignore[union-attr]

    panden = bouw_voorstellen(boekingen, rapport)
    rapport.panden = sorted(panden.values(), key=lambda p: p.code)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rapport.overhead_project = overhead_project_status(session, administratie_id)
        if dry_run:
            bestaand = {
                p.code: p for p in session.scalars(select(Pand).where(Pand.administratie_id == administratie_id)).all()
            }
            for v in rapport.panden:
                huidig = bestaand.get(v.code)
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


# ---- weergave -------------------------------------------------------------------------------------


def als_markdown(rapport: AfleidingRapport, *, administratie_naam: str | None = None) -> str:
    kop = administratie_naam or rapport.administratie_id
    regels = [
        f"### Pandenregister-afleiding {kop} (RLZ {rapport.rlz_admin_id or '?'}, "
        f"{'DRY-RUN — niets geschreven' if rapport.dry_run else 'GESCHREVEN als voorstel'}, {rapport.gegenereerd_op})",
        "",
        f"- Gelezen: {', '.join(f'{k} {v}' for k, v in sorted(rapport.gelezen.items())) or 'niets'}",
        f"- Panden (voorstel): {len(rapport.panden)} · koppelingen: {rapport.aantal_koppelingen}",
        f"- Geen pand-signaal (kandidaat Overhead, mens beslist in run 2): "
        f"{', '.join(f'{k} {v}' for k, v in sorted(rapport.geen_signaal.items())) or '0'}"
        + (f" · meerduidig adres: {rapport.meerduidig}" if rapport.meerduidig else ""),
        f"- Bijlagechecks memoriaal: {rapport.bijlage_checks} gedaan, "
        f"{rapport.bijlage_niet_gecontroleerd} niet (grens)",
        f"- {rapport.overhead_project}",
    ]
    if rapport.geschreven:
        regels.append("- Geschreven: " + ", ".join(f"{k} {v}" for k, v in rapport.geschreven.items()))
    for f in rapport.fouten:
        regels.append(f"- FOUT {f}")
    for o in rapport.overgeslagen:
        regels.append(f"- OVERGESLAGEN {o}")
    regels += [
        "",
        "| Pand | Plaats | Aankoop | Verkoop | Dossiers | Koppelingen (soort: hoog/midden/laag) | DB |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in rapport.panden:
        tel = p.tel()
        kop_tel = "; ".join(
            f"{soort}: {tel[soort].get('hoog', 0)}/{tel[soort].get('midden', 0)}/{tel[soort].get('laag', 0)}"
            for soort in sorted(tel)
        )
        aankoop = p.aankoopdatum.isoformat() if p.aankoopdatum else "—"
        verkoop = p.verkoopdatum.isoformat() if p.verkoopdatum else "—"
        regels.append(
            f"| {p.adres} | {p.plaats or '—'} | {aankoop} | {verkoop} | {', '.join(p.dossiers) or '—'} | "
            f"{kop_tel} | {p.db_status} |"
        )
    if not rapport.panden:
        regels.append("| _geen_ | | | | | | |")
    return "\n".join(regels) + "\n"
