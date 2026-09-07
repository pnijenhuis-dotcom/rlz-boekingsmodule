"""Duplicaat (module) — de duplicaat-toets tegen onze EIGEN database (besluit Peter 07-09: "duplicaten eruit; moet er
toch een geboekt worden, dan zoek ik hem in het archief"; aanleiding: een duplicaat kon GEBOEKT worden omdat álle
bestaande harde checks live tegen RLZ liepen en het sha256-signaal een chip zonder poort was).

Eén motor, drie afnemers:
- de HARDE check "Duplicaat (module)" (`checks.check_duplicaat_module`, gevoed door `treffers_voor_document`) —
  blokkerend, draait overal waar de harde checks draaien (controlescherm, boekpad, autoboek-poort, accordering);
- de auto-afvoer / één-klik / bulk (`duplicaat_afvoer.bepaal_groep`) — categorie (a) en (b) gaan DIRECT af;
- de backfill-CLI (`duplicaten-backfill`) — dezelfde verzameling, dezelfde regels.

Categorieën (geld in code, geen AI; alleen binnen DEZELFDE administratie — cross-administratie is nooit een duplicaat):
  (a) `bestand`               — zelfde sha256 van het hoofdbestand;
  (b) `referentie_bedrag`     — zelfde genormaliseerde referentie (`duplicaat_afvoer.normaliseer_referentie`, de ENIGE
                                normalisatie) + totaalbedrag cent-exact, over ÁLLE crediteur-records;
  (c) `crediteur_referentie`  — zelfde crediteur (zelfde vendor, zelfde KvK- óf btw-nummer, óf verliezer en voorkeur van
                                één afgehandeld dubbel-cluster — `crediteuren/voorkeur.py`) + zelfde genormaliseerde
                                referentie, óók bij een afwijkend bedrag (deelfactuur/creditnota met hetzelfde nummer =
                                mens kijkt; nooit automatisch afgevoerd).
Een tegenhanger die in meer categorieën valt draagt de zwaarste (a > b > c).

Welke documenten tellen als tegenhanger? Inkoopfacturen van dezelfde administratie in élke status behalve
verwijderd, afgewezen (dus óók al-afgevoerde duplicaten — anders komt een heropend origineel nooit terug),
gesplitst en samengevoegd (terminale hulzen: hun inhoud leeft voort in de kinderen resp. het leidende document — een
nagebundelde UBL-rij draagt zelfs dezelfde sha256 als het leidende document en zou zichzelf als duplicaat aanwijzen)
en niet_toegewezen (geen administratie). Het document zelf is nooit zijn eigen duplicaat — de boek-cyclus/
herboeking/tegenboek-keten is in onze database één rij, dus dat is hier vanzelf geborgd.

Kop van een tegenhanger: het opgeslagen boekvoorstel (mens heeft 'm gezien) met per veld terugval op de
`duplicaat_signaal`-kop (zoals bij extractie/veldopslag getoetst — dekt een document dat nog niemand opende).

UBL-XML + PDF van DEZELFDE factuur is GEEN duplicaat maar een bundel (XML = data, PDF = beeld; `intake/bundeling.py`,
`intake/nabundelen.py`): twee documenten van verschillende vorm (.xml vs. niet-.xml) uit hetzelfde intake-bericht óf met
dezelfde bestandsnaam-stam worden hier NOOIT als duplicaat aangemerkt — nabundelen/samenvoegen is dáár de weg.

Mens-override = "Geen duplicaat — afmelden" (`meld_af`): reden verplicht, tijdlijnregel zónder statusovergang met
detail `duplicaat_afgemeld` + de afgemelde tegenhangers, audit oud→nieuw; de sha256-vlag gaat eraf. De afmelding geldt
voor het PAAR (beide kanten) en alleen voor de op dat moment genoemde tegenhangers — een NIEUW derde exemplaar blokkeert
weer. Geen migratie: de tijdlijn is append-only en al de bron van waarheid voor documenthistorie."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.crediteur_kenmerk import kenmerken_per_vendor
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    DuplicaatSignaal,
)

logger = logging.getLogger(__name__)

CATEGORIE_BESTAND = "bestand"
CATEGORIE_REFERENTIE_BEDRAG = "referentie_bedrag"
CATEGORIE_CREDITEUR_REFERENTIE = "crediteur_referentie"
#: Categorieën die het systeem zonder mens afvoert (besluit Peter 07-09); (c) blijft op de Mogelijk-duplicaat-tab.
AFVOER_CATEGORIEEN = frozenset({CATEGORIE_BESTAND, CATEGORIE_REFERENTIE_BEDRAG})
_ZWAARTE = {CATEGORIE_BESTAND: 0, CATEGORIE_REFERENTIE_BEDRAG: 1, CATEGORIE_CREDITEUR_REFERENTIE: 2}

#: Statussen die een document uitsluiten als tegenhanger én als eigen toetsobject (zie module-docstring).
UITGESLOTEN_STATUSSEN = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.GESPLITST,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.NIET_TOEGEWEZEN,
    }
)

#: Sleutel in het tijdlijn-detail van een afmelding ("Geen duplicaat").
AFMELDING_SLEUTEL = "duplicaat_afgemeld"
AFMELDING_TEGENHANGERS = "afgemelde_tegenhangers"


class AfmeldingFout(Exception):
    """Domeinfout bij het afmelden (router → 409/422 mét tekst)."""


class RedenVerplicht(AfmeldingFout):
    pass


class NietsAfTeMelden(AfmeldingFout):
    """Er is op dit moment geen module-tegenhanger om af te melden."""


@dataclass(frozen=True)
class Kop:
    """Eén document mét zijn vergelijkingskop."""

    document_id: uuid.UUID
    status: DocumentStatus
    bestandsnaam: str
    aangemaakt_op: datetime
    sha256_hash: str | None
    vendor_id: uuid.UUID | None
    referentie: str | None
    referentie_norm: str | None
    totaalbedrag: Decimal | None
    intake_bericht_id: uuid.UUID | None

    @property
    def is_xml(self) -> bool:
        return self.bestandsnaam.lower().endswith(".xml")

    @property
    def stam(self) -> str:
        return Path(self.bestandsnaam).stem.strip().lower()


@dataclass(frozen=True)
class Treffer:
    """Eén tegenhanger van een document, mét de zwaarste categorie waarin hij valt."""

    document_id: uuid.UUID
    categorie: str
    status: DocumentStatus
    bestandsnaam: str
    aangemaakt_op: datetime
    referentie: str | None
    totaalbedrag: Decimal | None
    vendor_id: uuid.UUID | None

    @property
    def afvoerbaar_categorie(self) -> bool:
        return self.categorie in AFVOER_CATEGORIEEN


def _stam(bestandsnaam: str) -> str:
    return Path(bestandsnaam).stem.strip().lower()


def is_bundelpaar(a: Kop, b: Kop) -> bool:
    """UBL+PDF van dezelfde factuur (1d): verschillende vorm én (zelfde intake-bericht óf zelfde naamstam)."""
    if a.is_xml == b.is_xml:
        return False
    if a.intake_bericht_id is not None and a.intake_bericht_id == b.intake_bericht_id:
        return True
    return bool(a.stam) and a.stam == b.stam


def normaliseer(referentie: str | None) -> str | None:
    """Doorgeefluik naar DE normalisatie (`duplicaat_afvoer.normaliseer_referentie`) — lokale import om de kring
    duplicaat_afvoer → duplicaat_module → duplicaat_afvoer te vermijden."""
    from app.documenten.duplicaat_afvoer import normaliseer_referentie

    return normaliseer_referentie(referentie)


def _bedrag(waarde: Decimal | None) -> Decimal | None:
    return Decimal(waarde).quantize(Decimal("0.01")) if waarde is not None else None


@dataclass
class Verzameling:
    """Alles wat de match voor één administratie nodig heeft, één keer geladen (de backfill en de lijst-lezer lopen
    er honderden documenten over zonder N+1)."""

    administratie_id: uuid.UUID
    koppen: dict[uuid.UUID, Kop]
    #: vendor-id → set identiteitssleutels (vendor/voorkeur, btw, kvk); twee vendors zijn dezelfde crediteur als de
    #: sets elkaar snijden.
    identiteit: dict[uuid.UUID, frozenset[str]]
    #: Afgemelde paren, als bevroren paar van document-id's (volgorde-onafhankelijk).
    afmeldingen: set[frozenset[uuid.UUID]] = field(default_factory=set)

    def kop(self, document_id: uuid.UUID) -> Kop | None:
        return self.koppen.get(document_id)

    def zelfde_crediteur(self, a: uuid.UUID | None, b: uuid.UUID | None) -> bool:
        if a is None or b is None:
            return False
        if a == b:
            return True
        return bool(self.identiteit.get(a, frozenset()) & self.identiteit.get(b, frozenset()))

    def afgemeld(self, a: uuid.UUID, b: uuid.UUID) -> bool:
        return frozenset({a, b}) in self.afmeldingen

    def bundelparen_voor(self, eigen: Kop) -> list[Kop]:
        """Tegenhangers die zonder de bundel-uitzondering (1d) een (a)/(b)-match zouden zijn — rapportage-doel."""
        uit: list[Kop] = []
        for kop in self.koppen.values():
            if kop.document_id == eigen.document_id or not is_bundelpaar(eigen, kop):
                continue
            zelfde_bestand = bool(eigen.sha256_hash) and eigen.sha256_hash == kop.sha256_hash
            zelfde_kop = (
                eigen.referentie_norm is not None
                and eigen.referentie_norm == kop.referentie_norm
                and eigen.totaalbedrag is not None
                and eigen.totaalbedrag == kop.totaalbedrag
            )
            if zelfde_bestand or zelfde_kop:
                uit.append(kop)
        return uit

    def afgemelde_tegenhangers(self, eigen: Kop) -> list[Treffer]:
        """Tegenhangers die alleen door een mens-afmelding niet (meer) tellen — rapportage-doel."""
        return [
            t for t in self.treffers_voor(eigen, met_afgemeld=True) if self.afgemeld(eigen.document_id, t.document_id)
        ]

    def treffers_voor(self, eigen: Kop, *, met_afgemeld: bool = False) -> list[Treffer]:
        """Alle tegenhangers van `eigen` in deze administratie (zwaarste eerst, dan oudste). `met_afgemeld=True`
        laat ook afgemelde paren zien (UI: "afgemeld door …")."""
        treffers: list[Treffer] = []
        for kop in self.koppen.values():
            if kop.document_id == eigen.document_id:
                continue
            categorie = categorie_van(eigen, kop, self)
            if categorie is None:
                continue
            if not met_afgemeld and self.afgemeld(eigen.document_id, kop.document_id):
                continue
            treffers.append(
                Treffer(
                    document_id=kop.document_id,
                    categorie=categorie,
                    status=kop.status,
                    bestandsnaam=kop.bestandsnaam,
                    aangemaakt_op=kop.aangemaakt_op,
                    referentie=kop.referentie,
                    totaalbedrag=kop.totaalbedrag,
                    vendor_id=kop.vendor_id,
                )
            )
        treffers.sort(key=lambda t: (_ZWAARTE[t.categorie], t.aangemaakt_op, str(t.document_id)))
        return treffers


def categorie_van(eigen: Kop, ander: Kop, verzameling: Verzameling) -> str | None:
    """Pure match van één paar → zwaarste categorie of None. De bundel-uitzondering (1d) gaat vóór alles."""
    if is_bundelpaar(eigen, ander):
        return None
    if eigen.sha256_hash and ander.sha256_hash and eigen.sha256_hash == ander.sha256_hash:
        return CATEGORIE_BESTAND
    ref_gelijk = eigen.referentie_norm is not None and eigen.referentie_norm == ander.referentie_norm
    if not ref_gelijk:
        return None
    if eigen.totaalbedrag is not None and ander.totaalbedrag is not None and eigen.totaalbedrag == ander.totaalbedrag:
        return CATEGORIE_REFERENTIE_BEDRAG
    if verzameling.zelfde_crediteur(eigen.vendor_id, ander.vendor_id):
        return CATEGORIE_CREDITEUR_REFERENTIE
    return None


# ----------------------------------------------------------------------------- laden


def _identiteiten(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, frozenset[str]]:
    from app.crediteuren.voorkeur import verliezers

    kenmerken = kenmerken_per_vendor(session, administratie_id=administratie_id)
    kaart = verliezers(session, administratie_id=administratie_id)
    resultaat: dict[uuid.UUID, frozenset[str]] = {}
    vendor_ids = set(kenmerken) | set(kaart) | set(kaart.values())
    for vendor_id in vendor_ids:
        voorkeur = kaart.get(vendor_id, vendor_id)
        sleutels = {f"vendor:{voorkeur}"}
        for vid in (vendor_id, voorkeur):
            k = kenmerken.get(vid)
            if k is None:
                continue
            if k.btw_nummer:
                sleutels.add(f"btw:{k.btw_nummer}")
            if k.kvk_nummer:
                sleutels.add(f"kvk:{k.kvk_nummer}")
        resultaat[vendor_id] = frozenset(sleutels)
    return resultaat


def _afmeldingen(session: Session, *, administratie_id: uuid.UUID) -> set[frozenset[uuid.UUID]]:
    rijen = session.execute(
        select(DocumentGebeurtenis.document_id, DocumentGebeurtenis.detail)
        .join(Document, DocumentGebeurtenis.document_id == Document.id)
        .where(Document.administratie_id == administratie_id, DocumentGebeurtenis.detail.has_key(AFMELDING_SLEUTEL))
    ).all()
    paren: set[frozenset[uuid.UUID]] = set()
    for document_id, detail in rijen:
        for ander in (detail or {}).get(AFMELDING_TEGENHANGERS) or []:
            try:
                paren.add(frozenset({document_id, uuid.UUID(str(ander))}))
            except ValueError:
                continue
    return paren


def _kop_uit(document: Document, bv: Boekvoorstel | None, ds: DuplicaatSignaal | None) -> Kop:
    vendor_id = (bv.vendor_id if bv is not None else None) or (ds.vendor_id if ds is not None else None)
    referentie = (bv.referentie if bv is not None else None) or (ds.referentie if ds is not None else None)
    totaal = bv.totaalbedrag if bv is not None and bv.totaalbedrag is not None else (ds.totaalbedrag if ds else None)
    return Kop(
        document_id=document.id,
        status=document.status,
        bestandsnaam=document.bestandsnaam,
        aangemaakt_op=document.aangemaakt_op,
        sha256_hash=document.sha256_hash or None,
        vendor_id=vendor_id,
        referentie=referentie,
        referentie_norm=normaliseer(referentie),
        totaalbedrag=_bedrag(totaal),
        intake_bericht_id=document.intake_bericht_id,
    )


def laad_verzameling(session: Session, *, administratie_id: uuid.UUID) -> Verzameling:
    """Alle toetsbare inkoopfacturen van de administratie (sessie van de aanroeper, al gescoopt)."""
    rijen = session.execute(
        select(Document, Boekvoorstel, DuplicaatSignaal)
        .outerjoin(Boekvoorstel, Boekvoorstel.document_id == Document.id)
        .outerjoin(DuplicaatSignaal, DuplicaatSignaal.document_id == Document.id)
        .where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status.notin_(list(UITGESLOTEN_STATUSSEN)),
        )
    ).all()
    koppen = {document.id: _kop_uit(document, bv, ds) for document, bv, ds in rijen}
    return Verzameling(
        administratie_id=administratie_id,
        koppen=koppen,
        identiteit=_identiteiten(session, administratie_id=administratie_id),
        afmeldingen=_afmeldingen(session, administratie_id=administratie_id),
    )


def eigen_kop(
    verzameling: Verzameling,
    *,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
) -> Kop | None:
    """De kop van het te toetsen document zoals de CONTROLEUR 'm ziet (het boekvoorstel op het scherm), op het
    document-record uit de verzameling. None als het document niet (meer) toetsbaar is."""
    basis = verzameling.kop(document_id)
    if basis is None:
        return None
    return Kop(
        document_id=basis.document_id,
        status=basis.status,
        bestandsnaam=basis.bestandsnaam,
        aangemaakt_op=basis.aangemaakt_op,
        sha256_hash=basis.sha256_hash,
        vendor_id=vendor_id if vendor_id is not None else basis.vendor_id,
        referentie=referentie or basis.referentie,
        referentie_norm=normaliseer(referentie or basis.referentie),
        totaalbedrag=_bedrag(totaalbedrag) if totaalbedrag is not None else basis.totaalbedrag,
        intake_bericht_id=basis.intake_bericht_id,
    )


def treffers_voor_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
) -> list[Treffer]:
    """Voeding voor de harde check (`boekvoorstel.voer_checks_uit`): eigen sessie, geen RLZ/Odoo."""
    with scoped_session(administratie_id) as session:
        verzameling = laad_verzameling(session, administratie_id=administratie_id)
        eigen = eigen_kop(
            verzameling, document_id=document_id, vendor_id=vendor_id, referentie=referentie, totaalbedrag=totaalbedrag
        )
        if eigen is None:
            return []
        return verzameling.treffers_voor(eigen)


def treffers_bulk(
    session: Session, *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Treffer]]:
    """Lijst-lezer: per gevraagd document zijn tegenhangers (één verzameling, geen N+1)."""
    if not document_ids:
        return {}
    verzameling = laad_verzameling(session, administratie_id=administratie_id)
    resultaat: dict[uuid.UUID, list[Treffer]] = {}
    for document_id in document_ids:
        kop = verzameling.kop(document_id)
        if kop is None:
            continue
        treffers = verzameling.treffers_voor(kop)
        if treffers:
            resultaat[document_id] = treffers
    return resultaat


# ----------------------------------------------------------------------------- afmelden (mens-override)


@dataclass(frozen=True)
class Afmelding:
    document_id: uuid.UUID
    tegenhangers: list[uuid.UUID]
    reden: str
    actor_id: uuid.UUID
    tijdstip: datetime


def laatste_afmelding(session: Session, *, document_id: uuid.UUID) -> Afmelding | None:
    rij = session.execute(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id, DocumentGebeurtenis.detail.has_key(AFMELDING_SLEUTEL))
        .order_by(DocumentGebeurtenis.tijdstip.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rij is None:
        return None
    detail = rij.detail or {}
    return Afmelding(
        document_id=document_id,
        tegenhangers=[uuid.UUID(str(t)) for t in detail.get(AFMELDING_TEGENHANGERS) or []],
        reden=str(detail.get("reden") or ""),
        actor_id=rij.actor_id,
        tijdstip=rij.tijdstip,
    )


def meld_af(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> Afmelding:
    """ "Geen duplicaat — afmelden": de mens verklaart dat de HUIDIGE module-tegenhangers geen duplicaten zijn.
    Reden verplicht. Schrijft één tijdlijnregel zonder statusovergang (`duplicaat_afgemeld`, tegenhangers, reden),
    haalt de sha256-vlag `mogelijk_duplicaat_van_id` eraf en audit oud→nieuw. Daarna zwijgt de harde check voor precies
    deze paren (beide kanten) en voert de auto-afvoer ze niet af; een nieuwe tegenhanger blokkeert weer."""
    from app.documenten.service import DocumentNietGevonden

    reden_tekst = reden.strip()
    if not reden_tekst:
        raise RedenVerplicht("Een afmelding zonder reden is niet toegestaan")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        verzameling = laad_verzameling(session, administratie_id=administratie_id)
        kop = verzameling.kop(document_id)
        treffers = verzameling.treffers_voor(kop) if kop is not None else []
        tegenhangers = [t.document_id for t in treffers]
        if document.mogelijk_duplicaat_van_id is not None and document.mogelijk_duplicaat_van_id not in tegenhangers:
            tegenhangers.append(document.mogelijk_duplicaat_van_id)
        if not tegenhangers:
            raise NietsAfTeMelden("Er is op dit moment geen duplicaat-tegenhanger om af te melden")
        vlag = document.mogelijk_duplicaat_van_id
        oud = {"mogelijk_duplicaat_van_id": str(vlag) if vlag else None}
        detail = {
            AFMELDING_SLEUTEL: True,
            AFMELDING_TEGENHANGERS: [str(t) for t in tegenhangers],
            "reden": reden_tekst,
        }
        gebeurtenis = DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
        session.add(gebeurtenis)
        document.mogelijk_duplicaat_van_id = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document.id,
            actie="duplicaat_afgemeld",
            correlatie_id=gebeurtenis.id,
            oude_waarde=oud,
            nieuwe_waarde={**detail, "mogelijk_duplicaat_van_id": None},
            administratie_id=administratie_id,
        )
        session.flush()
        return Afmelding(
            document_id=document.id,
            tegenhangers=tegenhangers,
            reden=reden_tekst,
            actor_id=actor_id,
            tijdstip=gebeurtenis.tijdstip or datetime.now(),
        )


# ----------------------------------------------------------------------------- signaal-vlag (tab-zichtbaarheid)


def markeer_mogelijk_duplicaat(
    session: Session, *, document: Document, treffers: list[Treffer], administratie_id: uuid.UUID, actor_id: uuid.UUID
) -> bool:
    """Zet de bestaande losse vlag `mogelijk_duplicaat_van_id` (Mogelijk-duplicaat-tab, chip, bulk-selectie) op de
    zwaarste tegenhanger als het document na de afvoer-ronde blijft staan mét tegenhangers — categorie (c) en alles wat
    niet automatisch afgevoerd kon worden blijft zo ZICHTBAAR (nooit stil). Alleen zetten als de vlag nog leeg is;
    audit."""
    if not treffers or document.mogelijk_duplicaat_van_id is not None:
        return False
    doel = treffers[0].document_id
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="document",
        record_id=document.id,
        actie="duplicaat_module_gesignaleerd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"mogelijk_duplicaat_van_id": None},
        nieuwe_waarde={
            "mogelijk_duplicaat_van_id": str(doel),
            "categorie": treffers[0].categorie,
            "tegenhangers": [str(t.document_id) for t in treffers],
        },
        administratie_id=administratie_id,
    )
    document.mogelijk_duplicaat_van_id = doel
    return True


def groepeer_per_categorie(treffers: list[Treffer]) -> dict[str, list[Treffer]]:
    per: dict[str, list[Treffer]] = defaultdict(list)
    for t in treffers:
        per[t.categorie].append(t)
    return dict(per)
