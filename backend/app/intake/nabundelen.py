"""Nabundel-nazorg (akkoord Peter 02-09, casus IC-stapel Universal Nederland → Universal Steigerbouw):
UBL+PDF-paren die vóór de bundeling (migratie 0098) GESCHEIDEN verwerkt zijn — de PDF al via AI
toegewezen en als document in de werkvoorraad, de UBL nog in de verzamelbak mét zusje-chip
"tegenhanger al toegewezen" — alsnog samenvoegen volgens het bundelingsmodel van vandaag:

- het bestaande PDF-document blijft HET document (id, tijdlijn, administratie, vragen — niets verhuist);
- de UBL wordt zijn hoofdbestand/databron (`opslag_pad`/`bestandsnaam`/`sha256_hash` → de UBL;
  `/bestand?vorm=data` levert de UBL), de PDF gaat naar de bron-kolommen als beeld (`bron_*`) — exact
  de vorm die `documenten/beeld.py::beeld_is_bron` herkent, dus preview, controlescherm en RLZ-bijlage
  tonen de PDF;
- daarna de deterministische her-extractie uit de UBL (`_start_extractie`, zelfde pad als een verse
  UBL-upload — het UBL-veldvoorstel wint als "laatste veldvoorstel"), ná de commit de bestaande
  post-extractie-hooks (duplicaatsignaal, factuurmatch, autoboek-poorten);
- de verzamelbak-rij van de UBL gaat naar de terminale status `samengevoegd` mét verwijzing
  (`samengevoegd_in_id` = het PDF-document) — nooit verwijderen; de ongedaan-route werkt ook hier
  (`maak_nabundeling_ongedaan`, aangeroepen vanuit `verzamelbak.maak_samenvoegen_ongedaan`).

UITBREIDING DUBBELPAREN (akkoord Peter 03-09, `ook_toegewezen=True` / CLI `--ook-toegewezen`): de UBL
hoeft niet meer in de verzamelbak te staan — een al TOEGEWEZEN UBL-DOCUMENT dat náást zijn
PDF-tegenhanger in DEZELFDE administratie staat (25 IC-facturen, bulk-toegewezen tijdens de
proxy-storing van 03-09) wordt op dezelfde manier in dat PDF-document nagebundeld. Zelfde
naamstam-zekerheid (zelfde intake-bericht + naamstam, precies één PDF-document én precies één
UBL-document met die stam in die administratie), zelfde waarborgen aan BEIDE kanten (alleen
te_controleren/handmatig_afmaken; een opgeslagen boekvoorstel op het UBL-document = overslaan, want
dan heeft een mens dat exemplaar beoordeeld), het UBL-document zelf → terminaal `samengevoegd` (nooit
verwijderd; tijdlijn + audit beide kanten; ongedaan = terug naar zijn status van vóór de nabundeling).

HARDE VOORWAARDEN (besluit Peter 02-09):
- uitsluitend PDF-documenten op `te_controleren` of `handmatig_afmaken`; geboekt, ter_accordering,
  vraag_open, afgewezen, … = overslaan mét reden in het rapport;
- een OPGESLAGEN boek-/veldvoorstel (rij in `boekvoorstel`) wordt nooit overschreven: dan wordt de UBL
  alleen als data/beeld gekoppeld, het voorstel blijft staan, geen her-extractie — reden in het rapport;
- het toewijzings-geheugen leert hier níéts (geen mens-besluit);
- MATCH-ZEKERHEID: alleen paren die de zusje-detectie eenduidig legt (zelfde intake-bericht + zelfde
  naamstam, precies één toegewezen PDF-tegenhanger én precies één UBL met die stam in dat
  bericht); twijfel = overslaan mét reden, nooit gokken.

PDF-DUBBELEN SAMENVOUWEN (besluit Peter 07-09, beslispunt 2 optie b — HERZIET het 03-09-besluit "deel-4/
deel-7-dubbelmails niet bouwen, afwijs-klikwerk voor kantoor"): staan er in DEZELFDE administratie meer
PDF-documenten met dezelfde naamstam uit HETZELFDE intake-bericht (de dubbele deel-mails van 02-09: 50
stammen × 2 byte-identieke PDF's), dan is dat géén gok meer zodra hun `sha256_hash` gelijk is — de motor
vouwt ze deterministisch samen vóór de paarvorming: één exemplaar wordt het GEHOUDEN exemplaar (= de
tegenhanger voor de UBL), de overige gaan naar de terminale status `samengevoegd` mét verwijzing
(`samengevoegd_in_id` = het gehouden exemplaar), tijdlijn + audit, nooit verwijderd. Rangorde gehouden
exemplaar (`_samenvouw_plan`): (1) GEBOEKT wint altijd (bewaarplicht, boekstuk hangt eraan); (2) daarna
elk exemplaar dat een mens verder heeft gebracht (klaar_om_te_boeken, ter_accordering, …); (3) daarna
een exemplaar mét opgeslagen boekvoorstel (mens heeft dít exemplaar beoordeeld); (4) anders het OUDSTE
(`aangemaakt_op`, dan id — stabiel en herhaalbaar). De weggevouwen exemplaren moeten zelf op
te_controleren/handmatig_afmaken staan zónder opgeslagen boekvoorstel; is meer dan één exemplaar door een
mens aangeraakt, of verschilt de inhoud (sha256), dan blijft het paar "meerduidig" = overslaan mét reden.
Het samenvouwen gebeurt in DEZELFDE transactie als de nabundeling (wordt het paar om een andere reden
overgeslagen — gehouden exemplaar al geboekt e.d. — dan wordt er óók niets samengevouwen: niets half).
Dry-run toont het samenvouw-plan per paar. Ongedaan maken (`maak_nabundeling_ongedaan`) zet óók de
weggevouwen exemplaren terug naar hun status van vóór de run (weer losse exemplaren in de werkvoorraad).
Dezelfde sha256-regel geldt SYMMETRISCH voor byte-identieke UBL-dubbelen uit hetzelfde bericht (de dry-run van
07-09 legde 5 stammen bloot met 2 identieke UBL's + 2 identieke PDF's — verborgen achter de PDF-telling): het
gehouden UBL-exemplaar (zelfde rangorde) is de kandidaat, de overige UBL's worden in dezelfde transactie
samengevouwen in het uiteindelijke document (het gehouden PDF-exemplaar) — beslispunt Peter, zie rapport 07-09.

AFGEWEZEN TELT ALS TERMINAAL VOOR DE TELLING (besluit Peter 07-09, beslispunt 3): een afgewezen
dubbel-exemplaar (mét reden, blijft zichtbaar) telt niet meer als tegenhanger en ontgrendelt het paar —
het afwijs-klikwerk van kantoor maakt een meerduidig paar dus wél eenduidig.

Deterministisch (geen AI, geen RLZ-calls), systeem-actor, audit per paar, idempotent (een tweede run
vindt 0 kandidaten: de UBL-rij is dan `samengevoegd`). Bestanden worden nooit verwijderd — de oude
PDF-locatie ís de nieuwe bron-locatie, het UBL-bestand komt er als kopie naast onder het
administratie-prefix. Verbindings-blips (03-09): elk paar krijgt precies één herkansing bij een
verbroken databaseverbinding (`app/db/herkansing.py`); drie opeenvolgende paren die óók ná de
herkansing op de verbinding stranden = de run stopt zichtbaar (de rest blijft onaangeroerd voor een
volgende, idempotente run)."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.herkansing import VerbindingVerbroken, voer_uit_met_herkansing
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.beeld import beeld_is_bron
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.service import (
    DocumentNietGevonden,
    _na_extractie_hook,
    _schrijf_overgang,
    _standaard_opslag,
    _start_extractie,
)
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur
from app.intake.models import IntakeBericht

logger = logging.getLogger(__name__)

_TOEGEWEZEN_DETAIL = re.compile(r"→\s*([0-9a-f-]{36})\s*$")
_NABUNDEL_STATUSSEN = frozenset({DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN})
#: Statussen die bij het tellen van tegenhangers binnen een administratie niet meedoen (terminaal, geen
#: exemplaar meer in de werkvoorraad) — een zacht-verwijderd derde exemplaar maakt een paar niet meerduidig.
#: AFGEWEZEN sinds 07-09 (besluit Peter, beslispunt 3): een afgewezen dubbel-exemplaar ontgrendelt het paar.
#: AFGEVOERD_DUPLICAAT (blok 3, fixrun 08-09) telt óók terminaal — zelfde reden als afgewezen.
_TERMINAAL_VOOR_TELLING = frozenset(
    {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.GESPLITST,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
    }
)
#: Noodrem: zoveel opeenvolgende paren die óók ná de herkansing op de verbinding stranden = run stopt.
MAX_OPEENVOLGENDE_VERBINDINGSFOUTEN = 3

UITKOMST_SAMENGEVOEGD = "samengevoegd"
UITKOMST_GEKOPPELD_VOORSTEL_BEHOUDEN = "gekoppeld_voorstel_behouden"
UITKOMST_OVERGESLAGEN = "overgeslagen"
UITKOMST_MISLUKT = "mislukt"
UITKOMST_KANDIDAAT = "kandidaat"  # dry-run

#: Sleutel in het tijdlijn-detail van de `samengevoegd`-overgang van de UBL-rij; draagt de administratie
#: van het leidende PDF-document zodat de ongedaan-route (scope!) 'm terugvindt zonder RLS-doorbraak.
NABUNDEL_ADMINISTRATIE_SLEUTEL = "nagebundeld_administratie_id"
#: Sleutel in datzelfde detail: de status van het UBL-DOCUMENT vóór de nabundeling (dubbelparen 03-09) —
#: de ongedaan-route zet 'm daarop terug; afwezig = het was een verzamelbak-rij (→ niet_toegewezen).
NABUNDEL_VORIGE_STATUS_SLEUTEL = "vorige_status"
#: Sleutel (True) in het tijdlijn-detail van de `samengevoegd`-overgang van een WEGGEVOUWEN byte-identiek
#: dubbel-exemplaar (PDF of UBL, 07-09) — onderscheidt die rij van de nagebundelde UBL-rij die naar hetzelfde
#: gehouden exemplaar verwijst (de ongedaan-route zet beide soorten terug, elk naar zijn eigen vorige status).
NABUNDEL_SAMENVOUW_SLEUTEL = "samengevouwen_dubbel"
AUDIT_DUBBEL_SAMENGEVOUWEN = "document_dubbel_samengevouwen"
AUDIT_DUBBEL_SAMENVOUW_ONGEDAAN = "document_dubbel_samenvouw_ongedaan"


class NabundelingOngedaanGeweigerd(Exception):
    """Ongedaan maken kan alleen zolang het leidende document nog op te_controleren/handmatig_afmaken staat."""


@dataclass(frozen=True)
class NabundelKandidaat:
    ubl_document_id: uuid.UUID
    ubl_bestandsnaam: str
    intake_bericht_id: uuid.UUID
    #: Het al-toegewezen PDF-zusje; None als de detectie twijfelt (`twijfel_reden` gevuld).
    pdf_document_id: uuid.UUID | None
    pdf_bestandsnaam: str | None
    administratie_id: uuid.UUID | None
    twijfel_reden: str | None = None
    #: True = de UBL is zelf al een toegewezen DOCUMENT in `administratie_id` (dubbelpaar, 03-09);
    #: False = verzamelbak-rij (platformbreed).
    ubl_in_administratie: bool = False
    #: Byte-identieke dubbel-exemplaren (PDF én UBL, 07-09) die vóór de paarvorming in `pdf_document_id` (het
    #: uiteindelijke document) worden weggevouwen — leeg als er niets samen te vouwen is.
    samen_te_vouwen: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class NabundelUitkomst:
    ubl_document_id: uuid.UUID
    ubl_bestandsnaam: str
    pdf_document_id: uuid.UUID | None
    uitkomst: str
    reden: str | None = None
    herkanst: bool = False
    administratie_id: uuid.UUID | None = None
    #: Dubbel-exemplaren (PDF/UBL) die in dit paar zijn (dry-run: zouden worden) weggevouwen in `pdf_document_id`.
    samengevouwen: tuple[uuid.UUID, ...] = ()

    def als_regel(self) -> str:
        ids = f"UBL {self.ubl_document_id}"
        if self.pdf_document_id is not None:
            ids += f" → PDF {self.pdf_document_id}"
        kern = f"{self.ubl_bestandsnaam} ({ids}): {self.uitkomst}"
        if self.herkanst:
            kern += " (ná herkansing)"
        if self.reden:
            kern += f" — {self.reden}"
        if self.samengevouwen:
            ids_dubbelen = ", ".join(map(str, self.samengevouwen))
            kern += f" [dubbel-exemplaren samengevouwen in het gehouden exemplaar: {ids_dubbelen}]"
        return kern


@dataclass
class NabundelTelling:
    kandidaten: int = 0
    samengevoegd: int = 0
    gekoppeld_voorstel_behouden: int = 0
    overgeslagen: int = 0
    mislukt: int = 0
    #: Paren waarvan de eerste poging op een verbroken verbinding strandde en de herkansing slaagde.
    herkanst: int = 0
    #: Paren die niet meer geprobeerd zijn omdat de run op de noodrem stopte.
    niet_geprobeerd: int = 0
    gestopt_reden: str | None = None
    #: Aantal byte-identieke dubbel-exemplaren (PDF + UBL) dat in deze run is weggevouwen (dry-run: zou worden) —
    #: over alle paren die daadwerkelijk samengevoegd/gekoppeld zijn (of, in dry-run, kandidaat zijn).
    samengevouwen_dubbelen: int = 0
    #: Aantal paren mét zo'n samenvouw-plan.
    paren_met_samenvouw: int = 0
    uitkomsten: list[NabundelUitkomst] = field(default_factory=list)

    def registreer(self, uitkomst: NabundelUitkomst) -> None:
        self.uitkomsten.append(uitkomst)
        if uitkomst.herkanst:
            self.herkanst += 1
        if uitkomst.samengevouwen:
            self.samengevouwen_dubbelen += len(uitkomst.samengevouwen)
            self.paren_met_samenvouw += 1
        if uitkomst.uitkomst == UITKOMST_SAMENGEVOEGD:
            self.samengevoegd += 1
        elif uitkomst.uitkomst == UITKOMST_GEKOPPELD_VOORSTEL_BEHOUDEN:
            self.gekoppeld_voorstel_behouden += 1
        elif uitkomst.uitkomst == UITKOMST_OVERGESLAGEN:
            self.overgeslagen += 1
        elif uitkomst.uitkomst == UITKOMST_MISLUKT:
            self.mislukt += 1

    def per_administratie(self) -> dict[uuid.UUID | None, dict[str, int]]:
        """Uitkomst-telling per (leidende) administratie — de CLI zet er de naam bij."""
        telling: dict[uuid.UUID | None, dict[str, int]] = {}
        for u in self.uitkomsten:
            per = telling.setdefault(u.administratie_id, {})
            per[u.uitkomst] = per.get(u.uitkomst, 0) + 1
        return telling

    def overgeslagen_per_reden(self) -> dict[str, int]:
        telling: dict[str, int] = {}
        for u in self.uitkomsten:
            if u.uitkomst == UITKOMST_OVERGESLAGEN:
                telling[u.reden or "?"] = telling.get(u.reden or "?", 0) + 1
        return telling

    def als_dict(self) -> dict:
        return {
            "kandidaten": self.kandidaten,
            "samengevoegd": self.samengevoegd,
            "gekoppeld_voorstel_behouden": self.gekoppeld_voorstel_behouden,
            "overgeslagen": self.overgeslagen,
            "mislukt": self.mislukt,
        }


def _stam(bestandsnaam: str) -> str:
    return Path(bestandsnaam).stem.strip().lower()


def _sha256(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


def _is_xml(bestandsnaam: str) -> bool:
    return bestandsnaam.lower().endswith(".xml")


def _is_pdf(bestandsnaam: str) -> bool:
    return bestandsnaam.lower().endswith(".pdf")


def _vind_verzamelbak_kandidaten() -> list[NabundelKandidaat]:
    """Alle verzamelbak-UBL's mét een PDF-tegenhanger uit hetzelfde intake-bericht die al is
    toegewezen (uitkomst 'toegewezen' in `intake_bericht.detail.bijlagen` — géén RLS-doorbraak: de
    toegewezen rij zelf wordt hier niet gelezen). Strikter dan het zusje-signaal in de verzamelbak: precies
    één toegewezen PDF met die naamstam én precies één verzamelbak-UBL met die stam per bericht, anders
    `twijfel_reden` (wordt gerapporteerd als overgeslagen, nooit gegokt)."""
    with scoped_session(None) as session:
        ubls = [
            d
            for d in session.scalars(
                select(Document)
                .where(
                    Document.administratie_id.is_(None),
                    Document.status == DocumentStatus.NIET_TOEGEWEZEN,
                    Document.intake_bericht_id.is_not(None),
                )
                .order_by(Document.aangemaakt_op)
            )
            if _is_xml(d.bestandsnaam)
        ]
        bericht_ids = {d.intake_bericht_id for d in ubls}
        berichten = (
            {b.id: b for b in session.scalars(select(IntakeBericht).where(IntakeBericht.id.in_(bericht_ids)))}
            if bericht_ids
            else {}
        )
        # Verzamelbak-UBL's per (bericht, stam) — meer dan één = twijfel.
        ubls_per_stam: dict[tuple[uuid.UUID, str], int] = {}
        for d in ubls:
            sleutel = (d.intake_bericht_id, _stam(d.bestandsnaam))
            ubls_per_stam[sleutel] = ubls_per_stam.get(sleutel, 0) + 1

        kandidaten: list[NabundelKandidaat] = []
        for d in ubls:
            assert d.intake_bericht_id is not None
            bericht = berichten.get(d.intake_bericht_id)
            if bericht is None:
                continue
            stam = _stam(d.bestandsnaam)
            treffers: list[dict] = [
                b
                for b in (bericht.detail or {}).get("bijlagen", []) or []
                if isinstance(b, dict)
                and b.get("uitkomst") == "toegewezen"
                and _is_pdf(b.get("bestandsnaam") or "")
                and _stam(b.get("bestandsnaam") or "") == stam
                and b.get("document_id")
            ]
            if not treffers:
                continue  # geen zusje → geen kandidaat (gewone bak-rij)
            basis = {
                "ubl_document_id": d.id,
                "ubl_bestandsnaam": d.bestandsnaam,
                "intake_bericht_id": d.intake_bericht_id,
            }
            if len(treffers) > 1:
                kandidaten.append(
                    NabundelKandidaat(
                        **basis,
                        pdf_document_id=None,
                        pdf_bestandsnaam=None,
                        administratie_id=None,
                        twijfel_reden="meerduidig: meer dan één toegewezen PDF met dezelfde naamstam in deze e-mail",
                    )
                )
                continue
            if ubls_per_stam[(d.intake_bericht_id, stam)] > 1:
                kandidaten.append(
                    NabundelKandidaat(
                        **basis,
                        pdf_document_id=None,
                        pdf_bestandsnaam=None,
                        administratie_id=None,
                        twijfel_reden="meerduidig: meer dan één verzamelbak-UBL met dezelfde naamstam in deze e-mail",
                    )
                )
                continue
            treffer = treffers[0]
            match = _TOEGEWEZEN_DETAIL.search(treffer.get("detail") or "")
            try:
                pdf_id = uuid.UUID(str(treffer["document_id"]))
                adm = uuid.UUID(match.group(1)) if match else None
            except ValueError:
                pdf_id, adm = None, None
            if pdf_id is None or adm is None:
                kandidaten.append(
                    NabundelKandidaat(
                        **basis,
                        pdf_document_id=pdf_id,
                        pdf_bestandsnaam=str(treffer.get("bestandsnaam")),
                        administratie_id=None,
                        twijfel_reden="administratie van de tegenhanger niet af te leiden uit het intake-bericht",
                    )
                )
                continue
            kandidaten.append(
                NabundelKandidaat(
                    **basis,
                    pdf_document_id=pdf_id,
                    pdf_bestandsnaam=str(treffer.get("bestandsnaam")),
                    administratie_id=adm,
                )
            )
        return kandidaten


def _status_rang(status: DocumentStatus) -> int:
    """Rangorde van het GEHOUDEN exemplaar bij byte-identieke PDF-dubbelen (07-09): geboekt wint altijd
    (bewaarplicht, RLZ-boekstuk hangt eraan); daarna alles wat een mens verder heeft gebracht dan het
    controlescherm; te_controleren/handmatig_afmaken zijn gelijkwaardig (daar beslissen boekvoorstel en ouderdom)."""
    if status == DocumentStatus.GEBOEKT:
        return 2
    if status not in _NABUNDEL_STATUSSEN:
        return 1
    return 0


def _samenvouw_plan(session, exemplaren: list[Document], soort: str) -> tuple[Document, list[Document]] | str:
    """Meer dan één document van dezelfde soort (`soort` = "PDF-document"/"UBL-document") met dezelfde naamstam
    uit hetzelfde intake-bericht in één administratie: byte-identiek (zelfde `sha256_hash`) → (gehouden exemplaar,
    weg te vouwen exemplaren); anders een twijfel-reden (string). Zie de module-docstring voor de rangorde. Weg te
    vouwen exemplaren moeten op te_controleren/handmatig_afmaken staan zónder opgeslagen boekvoorstel en zonder
    eigen beeld/bron — anders heeft een mens (of een eerdere bundeling) dat exemplaar aangeraakt en is samenvouwen
    een gok."""
    if len({p.sha256_hash for p in exemplaren}) > 1:
        return (
            f"meerduidig: meer dan één {soort} met dezelfde naamstam uit deze e-mail in de administratie "
            "én de inhoud verschilt (sha256) — geen byte-identiek dubbel"
        )
    met_voorstel = set(
        session.scalars(
            select(Boekvoorstel.document_id).where(Boekvoorstel.document_id.in_([p.id for p in exemplaren]))
        )
    )
    gesorteerd = sorted(
        exemplaren,
        key=lambda p: (-_status_rang(p.status), 0 if p.id in met_voorstel else 1, p.aangemaakt_op, str(p.id)),
    )
    gehouden, weg = gesorteerd[0], gesorteerd[1:]
    for p in weg:
        if p.status not in _NABUNDEL_STATUSSEN or p.id in met_voorstel or p.bron_opslag_pad is not None:
            return (
                f"meerduidig: byte-identieke {soort}-dubbelen, maar meer dan één exemplaar is door een mens "
                f"aangeraakt (status/boekvoorstel/beeld — o.a. {p.bestandsnaam} {p.id}) — mensenwerk"
            )
    return gehouden, weg


def _vind_dubbelpaar_kandidaten() -> list[NabundelKandidaat]:
    """Dubbelparen (03-09): per actieve administratie de al toegewezen UBL-DOCUMENTEN op
    te_controleren/handmatig_afmaken die een PDF-document uit HETZELFDE intake-bericht met DEZELFDE
    naamstam naast zich hebben in die administratie. Beide documenten leven in dezelfde RLS-scope —
    geen doorbraak nodig. Zekerheid: precies één PDF-document én precies één UBL-document met die stam
    uit dat bericht (terminale exemplaren tellen niet mee); anders twijfel = overslaan mét reden. De
    status van de PDF-tegenhanger toetst `_nabundel_een` (geboekt/ter accordering/… = reden)."""
    with scoped_session(None) as session:
        administratie_ids = list(
            session.scalars(select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam))
        )
    kandidaten: list[NabundelKandidaat] = []
    for adm in administratie_ids:
        with scoped_session(adm, actor_id=SYSTEEM_ACTOR_ID) as session:
            documenten = session.scalars(
                select(Document)
                .where(
                    Document.administratie_id == adm,
                    Document.intake_bericht_id.is_not(None),
                    Document.status.notin_(list(_TERMINAAL_VOOR_TELLING)),
                )
                .order_by(Document.aangemaakt_op)
            ).all()
            ubls = [d for d in documenten if _is_xml(d.bestandsnaam) and d.status in _NABUNDEL_STATUSSEN]
            if not ubls:
                continue
            pdfs_per_sleutel: dict[tuple[uuid.UUID, str], list[Document]] = {}
            ubls_per_sleutel: dict[tuple[uuid.UUID, str], list[Document]] = {}
            for d in documenten:
                assert d.intake_bericht_id is not None
                sleutel = (d.intake_bericht_id, _stam(d.bestandsnaam))
                if _is_pdf(d.bestandsnaam):
                    pdfs_per_sleutel.setdefault(sleutel, []).append(d)
                elif _is_xml(d.bestandsnaam):
                    ubls_per_sleutel.setdefault(sleutel, []).append(d)
            for ubl in ubls:
                assert ubl.intake_bericht_id is not None
                sleutel = (ubl.intake_bericht_id, _stam(ubl.bestandsnaam))
                pdfs = pdfs_per_sleutel.get(sleutel, [])
                if not pdfs:
                    continue  # gewone UBL-factuur zonder PDF-exemplaar — geen dubbelpaar
                basis = {
                    "ubl_document_id": ubl.id,
                    "ubl_bestandsnaam": ubl.bestandsnaam,
                    "intake_bericht_id": ubl.intake_bericht_id,
                    "ubl_in_administratie": True,
                }

                def twijfel(reden: str, _basis: dict = basis, _adm: uuid.UUID = adm) -> NabundelKandidaat:
                    return NabundelKandidaat(
                        **_basis,
                        pdf_document_id=None,
                        pdf_bestandsnaam=None,
                        administratie_id=_adm,
                        twijfel_reden=reden,
                    )

                samen_te_vouwen: list[uuid.UUID] = []
                # UBL-dubbelen (07-09, symmetrisch): byte-identiek = het gehouden UBL-exemplaar is dé kandidaat, de
                # overige gaan in zijn plan mee; de niet-gehouden exemplaren zelf leveren geen eigen kandidaat op
                # (zouden anders dubbel rapporteren) — tenzij het gehouden exemplaar niet nabundelbaar is, dan wordt
                # dat zichtbaar gemeld (niets verdwijnt stil).
                ubl_groep = ubls_per_sleutel.get(sleutel, [ubl])
                if len(ubl_groep) > 1:
                    ubl_plan = _samenvouw_plan(session, ubl_groep, "UBL-document")
                    if isinstance(ubl_plan, str):
                        kandidaten.append(twijfel(ubl_plan))
                        continue
                    gehouden_ubl, weg_ubls = ubl_plan
                    if gehouden_ubl.id != ubl.id:
                        if gehouden_ubl.status not in _NABUNDEL_STATUSSEN:
                            kandidaten.append(
                                twijfel(
                                    "meerduidig: byte-identiek dubbel UBL-exemplaar, maar het gehouden exemplaar "
                                    f"{gehouden_ubl.id} is al verder verwerkt (status "
                                    f"{gehouden_ubl.status.value.replace('_', ' ')}) — mensenwerk"
                                )
                            )
                        continue
                    samen_te_vouwen.extend(p.id for p in weg_ubls)
                gehouden = pdfs[0]
                if len(pdfs) > 1:
                    # PDF-dubbelen (07-09): byte-identiek = samenvouwen vóór de paarvorming, anders twijfel.
                    plan = _samenvouw_plan(session, pdfs, "PDF-document")
                    if isinstance(plan, str):
                        kandidaten.append(twijfel(plan))
                        continue
                    gehouden, weg = plan
                    samen_te_vouwen.extend(p.id for p in weg)
                kandidaten.append(
                    NabundelKandidaat(
                        **basis,
                        pdf_document_id=gehouden.id,
                        pdf_bestandsnaam=gehouden.bestandsnaam,
                        administratie_id=adm,
                        samen_te_vouwen=tuple(samen_te_vouwen),
                    )
                )
    return kandidaten


def vind_kandidaten(*, ook_toegewezen: bool = False) -> list[NabundelKandidaat]:
    """Verzamelbak-UBL's mét toegewezen PDF-zusje; mét `ook_toegewezen` daarnaast de dubbelparen
    (al toegewezen UBL-document naast zijn PDF-document in dezelfde administratie, 03-09)."""
    kandidaten = _vind_verzamelbak_kandidaten()
    if ook_toegewezen:
        kandidaten.extend(_vind_dubbelpaar_kandidaten())
    return kandidaten


def _status_reden(status: DocumentStatus) -> str:
    """Leesbare overslaan-reden per status (harde voorwaarde Peter: alleen te_controleren/handmatig_afmaken)."""
    teksten = {
        DocumentStatus.GEBOEKT: "tegenhanger is al geboekt",
        DocumentStatus.TER_ACCORDERING: "tegenhanger ligt ter accordering bij de klant",
        DocumentStatus.VRAAG_OPEN: "tegenhanger heeft een open vraag",
        DocumentStatus.AFGEWEZEN: "tegenhanger is afgewezen (ter controle)",
        DocumentStatus.KLAAR_OM_TE_BOEKEN: "tegenhanger staat al klaar om te boeken (mens heeft 'm beoordeeld)",
    }
    return teksten.get(status, f"tegenhanger heeft status {status.value.replace('_', ' ')}")


def _tijdlijn_notitie(session, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
    """Tijdlijnregel zonder statuswijziging (zelfde patroon als `verzamelbak.voeg_samen`); `reden` verplicht."""
    assert isinstance(detail.get("reden"), str) and detail["reden"].strip()
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
    )


def _nabundel_een(kandidaat: NabundelKandidaat, *, opslag: DocumentOpslag, dry_run: bool) -> NabundelUitkomst:
    def overgeslagen(reden: str) -> NabundelUitkomst:
        return NabundelUitkomst(
            ubl_document_id=kandidaat.ubl_document_id,
            ubl_bestandsnaam=kandidaat.ubl_bestandsnaam,
            pdf_document_id=kandidaat.pdf_document_id,
            uitkomst=UITKOMST_OVERGESLAGEN,
            reden=reden,
            administratie_id=kandidaat.administratie_id,
        )

    if kandidaat.twijfel_reden or kandidaat.pdf_document_id is None or kandidaat.administratie_id is None:
        return overgeslagen(kandidaat.twijfel_reden or "tegenhanger onbekend")

    adm = kandidaat.administratie_id
    pdf_id = kandidaat.pdf_document_id
    voorstel_behouden = False
    eind_status: DocumentStatus | None = None
    soort: str | None = None
    with scoped_session(adm, actor_id=SYSTEEM_ACTOR_ID) as session:
        ubl = session.get(Document, kandidaat.ubl_document_id)
        if kandidaat.ubl_in_administratie:
            # Dubbelpaar (03-09): het UBL-exemplaar is zelf een document in deze administratie.
            if ubl is None or ubl.administratie_id != adm:
                return overgeslagen("UBL-document niet (meer) gevonden in de administratie")
            if ubl.status not in _NABUNDEL_STATUSSEN:
                return overgeslagen(
                    f"UBL-document is intussen verder verwerkt (status {ubl.status.value.replace('_', ' ')})"
                )
            if session.get(Boekvoorstel, ubl.id) is not None:
                return overgeslagen(
                    "UBL-document heeft een opgeslagen boekvoorstel (mens heeft dit exemplaar beoordeeld) — "
                    "beide exemplaren blijven staan"
                )
        elif ubl is None or ubl.administratie_id is not None or ubl.status != DocumentStatus.NIET_TOEGEWEZEN:
            return overgeslagen("UBL-rij is intussen al verwerkt")
        pdf = session.get(Document, kandidaat.pdf_document_id)
        if pdf is None or pdf.administratie_id != adm:
            return overgeslagen("tegenhanger niet (meer) gevonden in de administratie uit het intake-bericht")
        if not _is_pdf(pdf.bestandsnaam):
            return overgeslagen(f"tegenhanger is geen PDF-document ({pdf.bestandsnaam})")
        if pdf.intake_bericht_id != ubl.intake_bericht_id:
            return overgeslagen("tegenhanger komt uit een ander intake-bericht dan het intake-bericht vermeldt")
        if pdf.soort != ubl.soort:
            return overgeslagen(f"documentsoort verschilt (UBL {ubl.soort}, tegenhanger {pdf.soort})")
        if pdf.bron_opslag_pad is not None:
            return overgeslagen(f"tegenhanger heeft al een beeld/bron ({pdf.bron_bestandsnaam})")
        if pdf.status not in _NABUNDEL_STATUSSEN:
            return overgeslagen(
                _status_reden(pdf.status)
                + (
                    f" (gehouden exemplaar van {len(kandidaat.samen_te_vouwen) + 1} byte-identieke PDF's — niets "
                    "samengevouwen)"
                    if kandidaat.samen_te_vouwen
                    else ""
                )
            )
        voorstel_behouden = session.get(Boekvoorstel, pdf.id) is not None

        # Dubbel-exemplaren (07-09): de weg te vouwen PDF's/UBL's opnieuw toetsen bínnen deze transactie — het plan
        # komt uit een eerdere leesronde; intussen kan een mens geklikt hebben. Elke afwijking = overslaan.
        dubbelen: list[Document] = []
        for dubbel_id in kandidaat.samen_te_vouwen:
            dubbel = session.get(Document, dubbel_id)
            if (
                dubbel is None
                or dubbel.id in (ubl.id, pdf.id)
                or dubbel.administratie_id != adm
                or dubbel.intake_bericht_id != pdf.intake_bericht_id
            ):
                return overgeslagen(f"dubbel-exemplaar {dubbel_id} niet (meer) gevonden bij het gehouden exemplaar")
            if dubbel.status not in _NABUNDEL_STATUSSEN:
                return overgeslagen(
                    f"dubbel-exemplaar {dubbel.bestandsnaam} ({dubbel_id}) is intussen verder verwerkt "
                    f"(status {dubbel.status.value.replace('_', ' ')}) — niets samengevouwen"
                )
            # Byte-identiek aan zíjn gehouden exemplaar: een PDF-dubbel aan de PDF, een UBL-dubbel aan de UBL.
            referentie_sha = pdf.sha256_hash if _is_pdf(dubbel.bestandsnaam) else ubl.sha256_hash
            if dubbel.sha256_hash != referentie_sha or _stam(dubbel.bestandsnaam) != _stam(pdf.bestandsnaam):
                return overgeslagen(
                    f"dubbel-exemplaar {dubbel_id} is niet (meer) byte-identiek aan het gehouden exemplaar"
                )
            if dubbel.bron_opslag_pad is not None or dubbel.samengevoegd_in_id is not None:
                return overgeslagen(f"dubbel-exemplaar {dubbel_id} draagt intussen een beeld/bron of verwijzing")
            if session.get(Boekvoorstel, dubbel.id) is not None:
                return overgeslagen(
                    f"dubbel-exemplaar {dubbel.bestandsnaam} ({dubbel_id}) heeft intussen een opgeslagen "
                    "boekvoorstel — mensenwerk, niets samengevouwen"
                )
            dubbelen.append(dubbel)
        n_pdf = sum(1 for d in dubbelen if _is_pdf(d.bestandsnaam))
        n_ubl = len(dubbelen) - n_pdf
        samenvouw_tekst = (
            f" + {len(dubbelen)} byte-identiek(e) dubbel-exemplaar/-exemplaren ({n_pdf} PDF, {n_ubl} UBL) "
            f"samengevouwen in het gehouden exemplaar {pdf.bestandsnaam} ({pdf.id})"
            if dubbelen
            else ""
        )

        if dry_run:
            return NabundelUitkomst(
                ubl_document_id=ubl.id,
                ubl_bestandsnaam=ubl.bestandsnaam,
                pdf_document_id=pdf.id,
                uitkomst=UITKOMST_KANDIDAAT,
                administratie_id=adm,
                reden=(
                    "opgeslagen boekvoorstel aanwezig — UBL wordt alleen gekoppeld, voorstel blijft staan"
                    if voorstel_behouden
                    else f"samenvoegen + her-extractie uit de UBL (tegenhanger {pdf.bestandsnaam}, {pdf.status.value})"
                )
                + (" [dubbelpaar: UBL-document → samengevoegd]" if kandidaat.ubl_in_administratie else "")
                + samenvouw_tekst,
                samengevouwen=tuple(d.id for d in dubbelen),
            )

        ubl_inhoud = opslag.lezen(pad=ubl.opslag_pad)
        try:
            parseer_ubl_factuur(ubl_inhoud)
        except GeenGeldigeUbl as exc:
            return NabundelUitkomst(
                ubl_document_id=ubl.id,
                ubl_bestandsnaam=ubl.bestandsnaam,
                pdf_document_id=pdf.id,
                uitkomst=UITKOMST_MISLUKT,
                reden=f"geen geldige UBL — niet gekoppeld: {exc}",
                administratie_id=adm,
            )

        correlatie_id = uuid.uuid4()

        # 0. Dubbel-exemplaren (07-09): byte-identieke PDF's/UBL's wegvouwen in het uiteindelijke document (het
        #    gehouden PDF-exemplaar) — terminaal `samengevoegd` mét verwijzing, vorige status in het tijdlijn-detail
        #    (ongedaan-route), audit; het bestand van het dubbel blijft op de opslag staan (nooit verwijderen).
        for dubbel in dubbelen:
            dubbel_oud = {"status": dubbel.status.value, "samengevoegd_in_id": None}
            dubbel_soort = "PDF" if _is_pdf(dubbel.bestandsnaam) else "UBL"
            dubbel.samengevoegd_in_id = pdf.id
            _schrijf_overgang(
                session,
                document=dubbel,
                naar=DocumentStatus.SAMENGEVOEGD,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "samengevoegd_in": str(pdf.id),
                    "leidend_bestandsnaam": pdf.bestandsnaam,
                    NABUNDEL_SAMENVOUW_SLEUTEL: True,
                    NABUNDEL_ADMINISTRATIE_SLEUTEL: str(adm),
                    NABUNDEL_VORIGE_STATUS_SLEUTEL: dubbel.status.value,
                    "sha256_hash": dubbel.sha256_hash,
                    "reden": f"nabundel-nazorg: byte-identiek dubbel {dubbel_soort}-exemplaar (zelfde e-mail, zelfde "
                    "naam, zelfde sha256) samengevouwen in het gehouden exemplaar van dezelfde factuur — niets "
                    "verwijderd",
                },
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="document",
                record_id=dubbel.id,
                actie=AUDIT_DUBBEL_SAMENGEVOUWEN,
                correlatie_id=correlatie_id,
                oude_waarde=dubbel_oud,
                nieuwe_waarde={
                    "status": DocumentStatus.SAMENGEVOEGD.value,
                    "samengevoegd_in_id": str(pdf.id),
                    "sha256_hash": dubbel.sha256_hash,
                },
                administratie_id=adm,
            )

        # 1. UBL onder het administratie-prefix (kopie; de oude UBL-locatie blijft staan).
        nieuw_pad = f"{adm}/{pdf.id}.xml"
        opslag.opslaan(pad=nieuw_pad, inhoud=ubl_inhoud)

        # 2. Bestandskolommen omdraaien: PDF → bron/beeld, UBL → hoofdbestand/data.
        oud = {"opslag_pad": pdf.opslag_pad, "bestandsnaam": pdf.bestandsnaam, "sha256_hash": pdf.sha256_hash}
        pdf.bron_opslag_pad = pdf.opslag_pad
        pdf.bron_bestandsnaam = pdf.bestandsnaam
        pdf.bron_content_type = "application/pdf"
        pdf.opslag_pad = nieuw_pad
        pdf.bestandsnaam = ubl.bestandsnaam
        pdf.sha256_hash = ubl.sha256_hash
        if pdf.tenaamstelling is None and ubl.tenaamstelling:
            pdf.tenaamstelling = ubl.tenaamstelling
        herkomst = (
            "UBL-document van dezelfde factuur uit dezelfde e-mail (dubbel exemplaar in deze administratie)"
            if kandidaat.ubl_in_administratie
            else "UBL uit dezelfde e-mail"
        )
        reden_pdf = (
            f"nabundel-nazorg: {herkomst} gekoppeld als databron, deze PDF is het beeld"
            + (
                " — opgeslagen boekvoorstel blijft ongewijzigd (geen her-extractie)"
                if voorstel_behouden
                else " — velden opnieuw uit de UBL gelezen"
            )
            + (
                f" — {len(dubbelen)} byte-identiek(e) dubbel-exemplaar/-exemplaren ({n_pdf} PDF, {n_ubl} UBL) uit "
                "dezelfde e-mail hierin samengevouwen"
                if dubbelen
                else ""
            )
        )
        _tijdlijn_notitie(
            session,
            pdf,
            SYSTEEM_ACTOR_ID,
            {
                "nagebundeld_met": str(ubl.id),
                "ubl_bestandsnaam": ubl.bestandsnaam,
                "vorige_bestandsnaam": oud["bestandsnaam"],
                "vorige_sha256_hash": oud["sha256_hash"],
                "voorstel_behouden": voorstel_behouden,
                "dubbelpaar": kandidaat.ubl_in_administratie,
                "samengevouwen_dubbelen": [str(d.id) for d in dubbelen],
                "reden": reden_pdf,
            },
        )

        # 3. UBL-rij/-document → samengevoegd (terminaal, nooit verwijderen), mét de administratie voor de
        #    ongedaan-route en — voor een dubbelpaar — de status van vóór de nabundeling.
        ubl_oud = {
            "status": ubl.status.value,
            "administratie_id": str(ubl.administratie_id) if ubl.administratie_id else None,
        }
        overgang_detail: dict = {
            "samengevoegd_in": str(pdf.id),
            "leidend_bestandsnaam": oud["bestandsnaam"],
            "nagebundeld": True,
            NABUNDEL_ADMINISTRATIE_SLEUTEL: str(adm),
            "reden": (
                "nabundel-nazorg: dubbel exemplaar — samengevoegd met het PDF-document van dezelfde factuur uit "
                "dezelfde e-mail; de UBL is nu de databron van dat document"
                if kandidaat.ubl_in_administratie
                else "nabundel-nazorg: gekoppeld aan het al toegewezen PDF-document uit dezelfde e-mail"
            ),
        }
        if kandidaat.ubl_in_administratie:
            overgang_detail[NABUNDEL_VORIGE_STATUS_SLEUTEL] = ubl.status.value
        ubl.samengevoegd_in_id = pdf.id
        _schrijf_overgang(
            session, document=ubl, naar=DocumentStatus.SAMENGEVOEGD, actor_id=SYSTEEM_ACTOR_ID, detail=overgang_detail
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=pdf.id,
            actie="document_nagebundeld",
            correlatie_id=correlatie_id,
            oude_waarde=oud,
            nieuwe_waarde={
                "opslag_pad": nieuw_pad,
                "bestandsnaam": ubl.bestandsnaam,
                "sha256_hash": ubl.sha256_hash,
                "bron_bestandsnaam": oud["bestandsnaam"],
                "samengevoegd_document_id": str(ubl.id),
                "voorstel_behouden": voorstel_behouden,
                "dubbelpaar": kandidaat.ubl_in_administratie,
                "samengevouwen_dubbelen": [str(d.id) for d in dubbelen],
            },
            administratie_id=adm,
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=ubl.id,
            actie="document_nagebundeld_in",
            correlatie_id=correlatie_id,
            oude_waarde=ubl_oud,
            nieuwe_waarde={
                "status": DocumentStatus.SAMENGEVOEGD.value,
                "samengevoegd_in_id": str(pdf.id),
                "administratie_id": ubl_oud["administratie_id"],
            },
            administratie_id=ubl.administratie_id,
        )

        # 4. Her-extractie uit de UBL — deterministisch, zelfde pad als een verse UBL-upload. Niet als een
        #    opgeslagen voorstel bestaat (harde voorwaarde: nooit overschrijven).
        if not voorstel_behouden:
            _start_extractie(session, document=pdf, actor_id=SYSTEEM_ACTOR_ID, opslag=opslag)
        eind_status = pdf.status
        soort = pdf.soort

    if not voorstel_behouden and soort is not None:
        _na_extractie_hook(administratie_id=adm, document_id=pdf_id, soort=soort)

    return NabundelUitkomst(
        ubl_document_id=kandidaat.ubl_document_id,
        ubl_bestandsnaam=kandidaat.ubl_bestandsnaam,
        pdf_document_id=pdf_id,
        uitkomst=UITKOMST_GEKOPPELD_VOORSTEL_BEHOUDEN if voorstel_behouden else UITKOMST_SAMENGEVOEGD,
        administratie_id=adm,
        reden=(
            "opgeslagen boekvoorstel aanwezig — alleen gekoppeld, voorstel ongewijzigd"
            if voorstel_behouden
            else f"status nu {eind_status.value if eind_status else '?'}"
        )
        + samenvouw_tekst,
        samengevouwen=tuple(d.id for d in dubbelen),
    )


def nabundel_verzamelbak(
    *,
    dry_run: bool = False,
    opslag: DocumentOpslag | None = None,
    ook_toegewezen: bool = False,
    administratie_id: uuid.UUID | None = None,
    herkansing_wacht_seconds: float | None = None,
) -> NabundelTelling:
    """Zie module-docstring. `dry_run` toetst álle poorten maar schrijft niets (uitkomst 'kandidaat' per rij);
    `ook_toegewezen` neemt de dubbelparen mee (03-09); `administratie_id` beperkt de run tot paren waarvan het
    leidende document in die administratie staat (bereik-begrenzing van een cloud-run — twijfelparen zonder
    afgeleide administratie vallen dan buiten de run). Elk paar is één transactie mét precies één herkansing
    bij een verbroken databaseverbinding; `herkansing_wacht_seconds` (tests) overschrijft de wachttijd."""
    telling = NabundelTelling()
    kandidaten = vind_kandidaten(ook_toegewezen=ook_toegewezen)
    if administratie_id is not None:
        kandidaten = [k for k in kandidaten if k.administratie_id == administratie_id]
    telling.kandidaten = len(kandidaten)
    opslag = opslag or _standaard_opslag()
    herkansing_kwargs = {} if herkansing_wacht_seconds is None else {"wacht_seconds": herkansing_wacht_seconds}
    opeenvolgende_verbindingsfouten = 0
    for index, kandidaat in enumerate(kandidaten):
        herkanst = False
        try:
            uitkomst, herkanst = voer_uit_met_herkansing(
                lambda: _nabundel_een(kandidaat, opslag=opslag, dry_run=dry_run),  # noqa: B023 — direct uitgevoerd
                label=f"nabundelen {kandidaat.ubl_bestandsnaam}",
                **herkansing_kwargs,
            )
            opeenvolgende_verbindingsfouten = 0
        except VerbindingVerbroken as exc:
            opeenvolgende_verbindingsfouten += 1
            logger.warning("Nabundelen %s: %s", kandidaat.ubl_document_id, exc)
            uitkomst = NabundelUitkomst(
                ubl_document_id=kandidaat.ubl_document_id,
                ubl_bestandsnaam=kandidaat.ubl_bestandsnaam,
                pdf_document_id=kandidaat.pdf_document_id,
                uitkomst=UITKOMST_MISLUKT,
                reden="databaseverbinding verbroken, ook ná één herkansing — niets gewijzigd; opnieuw draaien zodra "
                "de verbinding er weer is",
                administratie_id=kandidaat.administratie_id,
            )
        except Exception as exc:  # noqa: BLE001 — één kapot paar mag de stapel niet stoppen; wél zichtbaar
            opeenvolgende_verbindingsfouten = 0
            logger.exception("Nabundelen mislukt voor %s", kandidaat.ubl_document_id)
            uitkomst = NabundelUitkomst(
                ubl_document_id=kandidaat.ubl_document_id,
                ubl_bestandsnaam=kandidaat.ubl_bestandsnaam,
                pdf_document_id=kandidaat.pdf_document_id,
                uitkomst=UITKOMST_MISLUKT,
                reden=f"onverwachte fout ({type(exc).__name__}: {exc})",
                administratie_id=kandidaat.administratie_id,
            )
        if herkanst and uitkomst.herkanst is False:
            uitkomst = NabundelUitkomst(
                ubl_document_id=uitkomst.ubl_document_id,
                ubl_bestandsnaam=uitkomst.ubl_bestandsnaam,
                pdf_document_id=uitkomst.pdf_document_id,
                uitkomst=uitkomst.uitkomst,
                reden=uitkomst.reden,
                herkanst=True,
                administratie_id=uitkomst.administratie_id,
            )
        telling.registreer(uitkomst)
        if opeenvolgende_verbindingsfouten >= MAX_OPEENVOLGENDE_VERBINDINGSFOUTEN:
            telling.niet_geprobeerd = len(kandidaten) - index - 1
            telling.gestopt_reden = (
                f"gestopt: {opeenvolgende_verbindingsfouten} opeenvolgende paren strandden op de databaseverbinding "
                f"(ook ná herkansing) — {telling.niet_geprobeerd} paar/paren niet geprobeerd; de run is idempotent, "
                "draai 'm opnieuw zodra de verbinding er weer is"
            )
            logger.error(telling.gestopt_reden)
            break
    return telling


# ---- Ongedaan maken ----------------------------------------------------------------------------


def _jongste_samengevoegd_overgang(session, ubl_document_id: uuid.UUID) -> DocumentGebeurtenis | None:
    return session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == ubl_document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.SAMENGEVOEGD,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).first()


def _is_samenvouw_rij(session, document: Document) -> bool:
    """True als deze `samengevoegd`-rij een weggevouwen byte-identiek PDF-dubbel is (07-09) — herkend aan
    het tijdlijn-detail van zijn jongste samengevoegd-overgang, nooit aan de bestandsnaam alleen."""
    rij = _jongste_samengevoegd_overgang(session, document.id)
    return bool(rij is not None and (rij.detail or {}).get(NABUNDEL_SAMENVOUW_SLEUTEL) is True)


def nagebundelde_ubl_rij(session, leidend_document_id: uuid.UUID, administratie_id: uuid.UUID | None = None):
    """De nagebundelde UBL-rij die naar `leidend_document_id` verwijst — NIET een weggevouwen PDF-dubbel
    (07-09: meerdere `samengevoegd`-rijen kunnen naar hetzelfde gehouden exemplaar verwijzen). `administratie_id`
    beperkt tot rijen in die administratie (dubbelpaar); None = platformbreed lezen binnen de huidige scope.
    Geeft None als er geen nagebundelde UBL-rij is."""
    query = select(Document).where(
        Document.samengevoegd_in_id == leidend_document_id, Document.status == DocumentStatus.SAMENGEVOEGD
    )
    if administratie_id is not None:
        query = query.where(Document.administratie_id == administratie_id)
    for rij in session.scalars(query.order_by(Document.aangemaakt_op)):
        if not _is_samenvouw_rij(session, rij):
            return rij
    return None


def nagebundelde_administratie(session, ubl_document_id: uuid.UUID) -> uuid.UUID | None:
    """De administratie uit de jongste `samengevoegd`-overgang van een nagebundelde UBL-rij (None =
    handmatig samengevoegd in de bak, of geen samengevoegd-overgang)."""
    rij = _jongste_samengevoegd_overgang(session, ubl_document_id)
    waarde = (rij.detail or {}).get(NABUNDEL_ADMINISTRATIE_SLEUTEL) if rij is not None else None
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _status_van_voor_nabundeling(session, ubl: Document) -> DocumentStatus:
    """Waar de UBL-rij ná ongedaan maken heen gaat: een verzamelbak-rij terug in de bak; een UBL-DOCUMENT
    (dubbelpaar) terug naar zijn status van vóór de nabundeling uit het tijdlijn-detail (terugval
    te_controleren — nooit een status buiten de nabundel-statussen)."""
    if ubl.administratie_id is None:
        return DocumentStatus.NIET_TOEGEWEZEN
    rij = _jongste_samengevoegd_overgang(session, ubl.id)
    waarde = (rij.detail or {}).get(NABUNDEL_VORIGE_STATUS_SLEUTEL) if rij is not None else None
    try:
        status = DocumentStatus(str(waarde)) if waarde else DocumentStatus.TE_CONTROLEREN
    except ValueError:
        status = DocumentStatus.TE_CONTROLEREN
    return status if status in _NABUNDEL_STATUSSEN else DocumentStatus.TE_CONTROLEREN


def maak_nabundeling_ongedaan(
    *,
    administratie_id: uuid.UUID,
    ubl_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
) -> uuid.UUID:
    """Spiegel van `_nabundel_een` zolang het leidende document nog op te_controleren/handmatig_afmaken
    staat: de PDF wordt weer het hoofdbestand (kolommen terug, sha256 opnieuw uit de bytes), de
    bron-kolommen leeg, de UBL-rij terug in de verzamelbak — of, bij een dubbelpaar (03-09), het
    UBL-document terug naar zijn status van vóór de nabundeling (weer een los exemplaar in de
    werkvoorraad). Het UBL-bestand onder het administratie-prefix blijft op de opslag staan (niets wordt
    verwijderd). Het veldvoorstel uit de UBL blijft in de tijdlijn — de tijdlijnregel zegt dat en verwijst
    naar 'Opnieuw extraheren' voor een verse PDF-lezing. Geeft het id van de teruggezette UBL-rij."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        ubl = session.get(Document, ubl_document_id)
        if ubl is None or ubl.status != DocumentStatus.SAMENGEVOEGD or ubl.samengevoegd_in_id is None:
            raise DocumentNietGevonden("Geen nagebundelde UBL-rij — er is niets ongedaan te maken.")
        leidend = session.get(Document, ubl.samengevoegd_in_id)
        if leidend is None or leidend.administratie_id != administratie_id:
            raise DocumentNietGevonden("Het samengevoegde document is niet zichtbaar binnen deze administratie.")
        if leidend.status not in _NABUNDEL_STATUSSEN:
            raise NabundelingOngedaanGeweigerd(
                f"Het document is al verder verwerkt ({leidend.status.value.replace('_', ' ')}) — "
                "de nabundeling kan niet meer ongedaan gemaakt worden."
            )
        if not beeld_is_bron(leidend) or leidend.bron_opslag_pad is None or leidend.bron_bestandsnaam is None:
            raise NabundelingOngedaanGeweigerd("Het document draagt geen nagebundeld PDF-beeld meer.")

        pdf_inhoud = opslag.lezen(pad=leidend.bron_opslag_pad)
        oud = {
            "opslag_pad": leidend.opslag_pad,
            "bestandsnaam": leidend.bestandsnaam,
            "sha256_hash": leidend.sha256_hash,
            "bron_bestandsnaam": leidend.bron_bestandsnaam,
        }
        leidend.opslag_pad = leidend.bron_opslag_pad
        leidend.bestandsnaam = leidend.bron_bestandsnaam
        leidend.sha256_hash = _sha256(pdf_inhoud)
        leidend.bron_opslag_pad = None
        leidend.bron_bestandsnaam = None
        leidend.bron_content_type = None
        _tijdlijn_notitie(
            session,
            leidend,
            actor_id,
            {
                "nabundeling_ongedaan": str(ubl.id),
                "reden": "nabundeling ongedaan gemaakt — de PDF is weer het hoofdbestand; het veldvoorstel uit de UBL "
                "blijft in de tijdlijn staan, kies 'Opnieuw extraheren' voor een nieuwe lezing van de PDF",
            },
        )
        terug_naar = _status_van_voor_nabundeling(session, ubl)
        ubl.samengevoegd_in_id = None
        _schrijf_overgang(
            session,
            document=ubl,
            naar=terug_naar,
            actor_id=actor_id,
            detail={
                "reden": (
                    "nabundeling ongedaan gemaakt — dit UBL-document staat weer los in de werkvoorraad "
                    "(dubbel exemplaar van dezelfde factuur)"
                    if terug_naar != DocumentStatus.NIET_TOEGEWEZEN
                    else "nabundeling ongedaan gemaakt — terug in de verzamelbak"
                ),
                "was_samengevoegd_in": str(leidend.id),
            },
        )
        # Dubbel-exemplaren (07-09): de in dezelfde run weggevouwen byte-identieke PDF's/UBL's komen óók terug, elk
        # naar zijn status van vóór de run — de hele nabundeling is één handeling, dus ongedaan = de hele vorige stand.
        teruggezette_dubbelen: list[str] = []
        for dubbel in session.scalars(
            select(Document)
            .where(
                Document.samengevoegd_in_id == leidend.id,
                Document.status == DocumentStatus.SAMENGEVOEGD,
                Document.administratie_id == administratie_id,
            )
            .order_by(Document.aangemaakt_op)
        ).all():
            if not _is_samenvouw_rij(session, dubbel):
                continue
            dubbel_terug = _status_van_voor_nabundeling(session, dubbel)
            dubbel.samengevoegd_in_id = None
            _schrijf_overgang(
                session,
                document=dubbel,
                naar=dubbel_terug,
                actor_id=actor_id,
                detail={
                    "reden": "nabundeling ongedaan gemaakt — dit dubbele exemplaar staat weer los in de "
                    "werkvoorraad (byte-identiek aan het exemplaar waarin het was samengevouwen)",
                    "was_samengevoegd_in": str(leidend.id),
                },
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=dubbel.id,
                actie=AUDIT_DUBBEL_SAMENVOUW_ONGEDAAN,
                correlatie_id=uuid.uuid4(),
                oude_waarde={"status": DocumentStatus.SAMENGEVOEGD.value, "samengevoegd_in_id": str(leidend.id)},
                nieuwe_waarde={"status": dubbel_terug.value, "samengevoegd_in_id": None},
                administratie_id=administratie_id,
            )
            teruggezette_dubbelen.append(str(dubbel.id))
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=leidend.id,
            actie="document_nabundeling_ongedaan",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "opslag_pad": leidend.opslag_pad,
                "bestandsnaam": leidend.bestandsnaam,
                "sha256_hash": leidend.sha256_hash,
                "bron_bestandsnaam": None,
                "teruggezet_document_id": str(ubl.id),
                "teruggezet_naar_status": terug_naar.value,
                "teruggezette_dubbelen": teruggezette_dubbelen,
            },
            administratie_id=administratie_id,
        )
        return ubl.id
