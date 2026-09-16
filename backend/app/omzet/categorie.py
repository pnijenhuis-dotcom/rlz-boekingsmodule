"""Omzet-Receipts: de RLZ-`DocumentCategory` op BINDER, niet op naam (Peter 16-09, melding Van Boxtel "omzet onder
Uitgaven"). STAP-0 16-09 (api-verkenning "Receipts — binder Inkomsten/Uitgaven"): de RLZ-UI groepeert documenten op de
`DocumentBinder` van hun categorie (navigatie, alleen zichtbaar mét `$expand=DocumentBinder`; op documentniveau is
`DocumentBinder` altijd null). Een entity-loze Receipt verschijnt dus onder "Inkomsten" zodra zijn categorie die binder
draagt. Selectie: DocumentType 10 + binder "Inkomsten" (voorkeursnaam "Verkoopfactuur (Omzet)" binnen die binder);
meerduidig of geen Inkomsten-categorie = blokkerende check "Omzetcategorie (Inkomsten)" — de mens kiest dan in het
omzet-controlescherm (mens wint, wordt de nieuwe default voor de administratie mét audit). Geen migratie: id in de
bestaande kolom `omzet_instelling.verkoop_categorie_id`, herkomst + categorie-cache in `bron_instellingen` (JSON)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.checks import CheckResultaat
from app.omzet.models import OmzetInstelling

logger = logging.getLogger(__name__)

BINDER_INKOMSTEN = "Inkomsten"
VERKOOP_DOCUMENTTYPE = 10
VOORKEURSNAAM = "Verkoopfactuur (Omzet)"
CHECK_NAAM = "Omzetcategorie (Inkomsten)"
SLEUTEL = "verkoop_categorie"
CACHE_SLEUTEL = "categorieen_cache"
BRON_MENS = "mens"
BRON_AUTOMATISCH = "automatisch"


class CategorieFout(Exception):
    """Basis: de omzetcategorie is niet deterministisch te kiezen."""


class GeenInkomstenCategorie(CategorieFout):
    pass


class CategorieNietEenduidig(CategorieFout):
    pass


class CategorieOnbekend(CategorieFout):
    """De gekozen categorie staat niet (meer) in de gesynchroniseerde lijst van deze administratie."""


@dataclass(frozen=True)
class Categorie:
    id: str
    naam: str
    document_type: int | None
    binder: str | None

    @property
    def is_verkoop(self) -> bool:
        return self.document_type == VERKOOP_DOCUMENTTYPE

    @property
    def is_inkomsten(self) -> bool:
        return (self.binder or "").casefold() == BINDER_INKOMSTEN.casefold()


def lees_categorieen(raw: list[dict]) -> list[Categorie]:
    """RLZ `DocumentCategories?$expand=DocumentBinder` → Categorie. Binder = `Description` van de navigatie (leesbaar:
    Inkomsten/Uitgaven/Kas & Bank/…), terugval `Name`; zonder expand blijft de binder None (nooit gokken)."""
    uit: list[Categorie] = []
    for c in raw:
        binder = c.get("DocumentBinder") or {}
        uit.append(
            Categorie(
                id=str(c.get("id")),
                naam=str(c.get("Name") or ""),
                document_type=c.get("DocumentType"),
                binder=(binder.get("Description") or binder.get("Name")) if isinstance(binder, dict) else None,
            )
        )
    return uit


def verkoopcategorieen(categorieen: list[Categorie]) -> list[Categorie]:
    return [c for c in categorieen if c.is_verkoop]


def kies_verkoop_categorie(categorieen: list[Categorie]) -> Categorie:
    """Deterministisch: DocumentType 10 én binder Inkomsten; daarbinnen de voorkeursnaam, anders de enige. Meerdere
    Inkomsten-categorieën zonder voorkeursnaam = niet eenduidig (mens kiest); géén Inkomsten-categorie = fout."""
    verkoop = verkoopcategorieen(categorieen)
    inkomsten = [c for c in verkoop if c.is_inkomsten]
    if not inkomsten:
        binders = sorted({c.binder or "?" for c in verkoop}) or ["geen DocumentType-10-categorieën"]
        raise GeenInkomstenCategorie(
            f"Geen verkoopcategorie (DocumentType {VERKOOP_DOCUMENTTYPE}) mét binder '{BINDER_INKOMSTEN}' in deze "
            f"administratie (gevonden binders: {', '.join(binders)}) — kies de omzetcategorie in het "
            "omzet-controlescherm"
        )
    voorkeur = [c for c in inkomsten if c.naam == VOORKEURSNAAM]
    if len(voorkeur) == 1:
        return voorkeur[0]
    if len(inkomsten) == 1:
        return inkomsten[0]
    raise CategorieNietEenduidig(
        f"{len(inkomsten)} verkoopcategorieën mét binder '{BINDER_INKOMSTEN}' zonder de voorkeursnaam "
        f"'{VOORKEURSNAAM}' ({', '.join(c.naam for c in inkomsten)}) — kies de omzetcategorie in het "
        "omzet-controlescherm"
    )


@dataclass(frozen=True)
class VerkoopCategorieStand:
    id: uuid.UUID | None
    naam: str | None
    binder: str | None
    bron: str | None  # 'mens' | 'automatisch' | None (nog nooit bepaald)

    @property
    def is_inkomsten(self) -> bool:
        return (self.binder or "").casefold() == BINDER_INKOMSTEN.casefold()


def _instelling(session: Session, administratie_id: uuid.UUID, *, maak: bool = False) -> OmzetInstelling | None:
    instelling = session.get(OmzetInstelling, administratie_id)
    if instelling is None and maak:
        instelling = OmzetInstelling(administratie_id=administratie_id)
        session.add(instelling)
    return instelling


def stand_voor(session: Session, administratie_id: uuid.UUID) -> VerkoopCategorieStand:
    instelling = _instelling(session, administratie_id)
    if instelling is None:
        return VerkoopCategorieStand(None, None, None, None)
    meta = dict((instelling.bron_instellingen or {}).get(SLEUTEL) or {})
    cid = instelling.verkoop_categorie_id
    if cid is None:
        return VerkoopCategorieStand(None, None, None, None)
    # Legacy (vóór 16-09): id gecachet op naam zonder herkomst — telt als 'automatisch' en wordt bij de volgende
    # boeking/controle opnieuw op binder getoetst (`bepaal_en_bewaar`).
    return VerkoopCategorieStand(cid, meta.get("naam"), meta.get("binder"), meta.get("bron") or BRON_AUTOMATISCH)


def _schrijf(session: Session, administratie_id: uuid.UUID, *, categorie: Categorie, bron: str) -> None:
    instelling = _instelling(session, administratie_id, maak=True)
    assert instelling is not None
    instelling.verkoop_categorie_id = uuid.UUID(categorie.id)
    instelling.bron_instellingen = {
        **(instelling.bron_instellingen or {}),
        SLEUTEL: {"id": categorie.id, "naam": categorie.naam, "binder": categorie.binder, "bron": bron},
    }


def bewaar_cache(session: Session, administratie_id: uuid.UUID, categorieen: list[Categorie]) -> None:
    """Gesynchroniseerde DocumentType-10-categorieën mét binder, voor de keuzelijst in het omzet-controlescherm
    (geen aparte sync-tabel: het is één klein JSON-blok per administratie, ververst bij élke check/boeking)."""
    instelling = _instelling(session, administratie_id, maak=True)
    assert instelling is not None
    instelling.bron_instellingen = {
        **(instelling.bron_instellingen or {}),
        CACHE_SLEUTEL: [asdict(c) for c in verkoopcategorieen(categorieen)],
        f"{CACHE_SLEUTEL}_op": datetime.now(UTC).isoformat(),
    }


def cache_keuzes(session: Session, administratie_id: uuid.UUID) -> list[Categorie]:
    instelling = _instelling(session, administratie_id)
    if instelling is None:
        return []
    return [
        Categorie(
            id=str(c["id"]), naam=c.get("naam") or "", document_type=c.get("document_type"), binder=c.get("binder")
        )
        for c in (instelling.bron_instellingen or {}).get(CACHE_SLEUTEL) or []
        if isinstance(c, dict) and c.get("id")
    ]


def bepaal_en_bewaar(
    session: Session, administratie_id: uuid.UUID, categorieen: list[Categorie]
) -> VerkoopCategorieStand:
    """Mens wint: een menselijke keuze die nog bestaat blijft. Anders (nooit bepaald, legacy-op-naam, of automatisch
    gekozen) opnieuw op binder kiezen — een eerder op naam gecachete categorie zonder Inkomsten-binder wordt zo
    vervangen (cache-invalidatie uit de opdracht). Schrijft ook de keuzelijst-cache. Gooit `CategorieFout`."""
    bewaar_cache(session, administratie_id, categorieen)
    per_id = {c.id: c for c in categorieen}
    huidig = stand_voor(session, administratie_id)
    if huidig.bron == BRON_MENS and huidig.id is not None and str(huidig.id) in per_id:
        c = per_id[str(huidig.id)]
        return VerkoopCategorieStand(huidig.id, c.naam, c.binder, BRON_MENS)
    keuze = kies_verkoop_categorie(categorieen)
    _schrijf(session, administratie_id, categorie=keuze, bron=BRON_AUTOMATISCH)
    return VerkoopCategorieStand(uuid.UUID(keuze.id), keuze.naam, keuze.binder, BRON_AUTOMATISCH)


def zet_verkoop_categorie_mens(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, categorie_id: uuid.UUID, document_id: uuid.UUID | None = None
) -> VerkoopCategorieStand:
    """Blok B2: de medewerker kiest in het omzet-controlescherm — geldt voor dit document ÉN wordt de default van de
    administratie (bron 'mens'), audit oud→nieuw + tijdlijnregel op het document. Alleen een categorie uit de
    gesynchroniseerde keuzelijst (nooit een vrij GUID)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        keuzes = {c.id: c for c in cache_keuzes(session, administratie_id)}
        keuze = keuzes.get(str(categorie_id))
        if keuze is None:
            raise CategorieOnbekend(
                "Onbekende omzetcategorie — de keuzelijst kent alleen de gesynchroniseerde categorieën"
            )
        oud = stand_voor(session, administratie_id)
        _schrijf(session, administratie_id, categorie=keuze, bron=BRON_MENS)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="omzet_instelling",
            record_id=administratie_id,
            actie="omzet_verkoop_categorie_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "id": str(oud.id) if oud.id else None,
                "naam": oud.naam,
                "binder": oud.binder,
                "bron": oud.bron,
            },
            nieuwe_waarde={
                "id": keuze.id,
                "naam": keuze.naam,
                "binder": keuze.binder,
                "bron": BRON_MENS,
                "document_id": str(document_id) if document_id else None,
            },
            administratie_id=administratie_id,
        )
        if document_id is not None:
            from app.documenten.models import Document, DocumentGebeurtenis

            document = session.get(Document, document_id)
            if document is not None:
                session.add(
                    DocumentGebeurtenis(
                        id=uuid.uuid4(),
                        document_id=document.id,
                        van_status=document.status,
                        naar_status=document.status,
                        actor_id=actor_id,
                        detail={
                            "reden": f"omzetcategorie gekozen: {keuze.naam} · {keuze.binder or '?'} (wordt de default)",
                            "verkoop_categorie": {"id": keuze.id, "naam": keuze.naam, "binder": keuze.binder},
                        },
                    )
                )
        return VerkoopCategorieStand(uuid.UUID(keuze.id), keuze.naam, keuze.binder, BRON_MENS)


def check_resultaat(client, administratie_id: uuid.UUID) -> CheckResultaat:  # noqa: ANN001
    """Harde check "Omzetcategorie (Inkomsten)": leest de categorieën live (mét binder), ververst de keuzelijst-cache en
    toetst de stand — automatisch eenduidig = OK, mens-keuze = OK (oranje signaal als de mens bewust een niet-Inkomsten-
    binder koos), niet eenduidig/geen Inkomsten = BLOKKEREND, RLZ niet leesbaar = blokkerend (fail-closed)."""
    if client is None:
        return CheckResultaat(
            naam=CHECK_NAAM, ok=False, melding="Omzetcategorie nog niet gecontroleerd (geen RLZ-verbinding)"
        )
    try:
        categorieen = lees_categorieen(client.list_document_categories())
        with scoped_session(administratie_id) as session:
            stand = bepaal_en_bewaar(session, administratie_id, categorieen)
    except CategorieFout as exc:
        return CheckResultaat(naam=CHECK_NAAM, ok=False, melding=str(exc))
    except Exception as exc:  # noqa: BLE001 — fail-closed, nooit een kale 500
        logger.warning("Omzetcategorie kon niet gecontroleerd worden voor %s: %s", administratie_id, exc)
        return CheckResultaat(
            naam=CHECK_NAAM, ok=False, melding=f"Omzetcategorie kon niet gecontroleerd worden (RLZ: {exc})"
        )
    herkomst = "gekozen door de medewerker" if stand.bron == BRON_MENS else "automatisch op binder"
    melding = f"Boekt in Reeleezee als {stand.binder or '?'} · {stand.naam or '?'} ({herkomst})"
    if not stand.is_inkomsten:
        return CheckResultaat(
            naam=CHECK_NAAM,
            ok=True,
            signaal=True,
            melding=f"{melding} — let op: verschijnt in RLZ niet onder Inkomsten",
        )
    return CheckResultaat(naam=CHECK_NAAM, ok=True, melding=melding)
