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

HARDE VOORWAARDEN (besluit Peter 02-09):
- uitsluitend PDF-documenten op `te_controleren` of `handmatig_afmaken`; geboekt, ter_accordering,
  vraag_open, afgewezen, … = overslaan mét reden in het rapport;
- een OPGESLAGEN boek-/veldvoorstel (rij in `boekvoorstel`) wordt nooit overschreven: dan wordt de UBL
  alleen als data/beeld gekoppeld, het voorstel blijft staan, geen her-extractie — reden in het rapport;
- het toewijzings-geheugen leert hier níéts (geen mens-besluit);
- MATCH-ZEKERHEID: alleen paren die de zusje-detectie eenduidig legt (zelfde intake-bericht + zelfde
  naamstam, precies één toegewezen PDF-tegenhanger én precies één verzamelbak-UBL met die stam in dat
  bericht); twijfel = overslaan mét reden, nooit gokken.

Deterministisch (geen AI, geen RLZ-calls), systeem-actor, audit per paar, idempotent (een tweede run
vindt 0 kandidaten: de UBL-rij is dan `samengevoegd`). Bestanden worden nooit verwijderd — de oude
PDF-locatie ís de nieuwe bron-locatie, het UBL-bestand komt er als kopie naast onder het
administratie-prefix."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.db.audit import record_audit_event
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

UITKOMST_SAMENGEVOEGD = "samengevoegd"
UITKOMST_GEKOPPELD_VOORSTEL_BEHOUDEN = "gekoppeld_voorstel_behouden"
UITKOMST_OVERGESLAGEN = "overgeslagen"
UITKOMST_MISLUKT = "mislukt"
UITKOMST_KANDIDAAT = "kandidaat"  # dry-run

#: Sleutel in het tijdlijn-detail van de `samengevoegd`-overgang van de UBL-rij; draagt de administratie
#: van het leidende PDF-document zodat de ongedaan-route (scope!) 'm terugvindt zonder RLS-doorbraak.
NABUNDEL_ADMINISTRATIE_SLEUTEL = "nagebundeld_administratie_id"


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


@dataclass(frozen=True)
class NabundelUitkomst:
    ubl_document_id: uuid.UUID
    ubl_bestandsnaam: str
    pdf_document_id: uuid.UUID | None
    uitkomst: str
    reden: str | None = None

    def als_regel(self) -> str:
        kern = f"{self.ubl_bestandsnaam}: {self.uitkomst}"
        return f"{kern} — {self.reden}" if self.reden else kern


@dataclass
class NabundelTelling:
    kandidaten: int = 0
    samengevoegd: int = 0
    gekoppeld_voorstel_behouden: int = 0
    overgeslagen: int = 0
    mislukt: int = 0
    uitkomsten: list[NabundelUitkomst] = field(default_factory=list)

    def registreer(self, uitkomst: NabundelUitkomst) -> None:
        self.uitkomsten.append(uitkomst)
        if uitkomst.uitkomst == UITKOMST_SAMENGEVOEGD:
            self.samengevoegd += 1
        elif uitkomst.uitkomst == UITKOMST_GEKOPPELD_VOORSTEL_BEHOUDEN:
            self.gekoppeld_voorstel_behouden += 1
        elif uitkomst.uitkomst == UITKOMST_OVERGESLAGEN:
            self.overgeslagen += 1
        elif uitkomst.uitkomst == UITKOMST_MISLUKT:
            self.mislukt += 1

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


def vind_kandidaten() -> list[NabundelKandidaat]:
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
            if d.bestandsnaam.lower().endswith(".xml")
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
                and (b.get("bestandsnaam") or "").lower().endswith(".pdf")
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
        if ubl is None or ubl.administratie_id is not None or ubl.status != DocumentStatus.NIET_TOEGEWEZEN:
            return overgeslagen("UBL-rij is intussen al verwerkt")
        pdf = session.get(Document, kandidaat.pdf_document_id)
        if pdf is None or pdf.administratie_id != adm:
            return overgeslagen("tegenhanger niet (meer) gevonden in de administratie uit het intake-bericht")
        if not pdf.bestandsnaam.lower().endswith(".pdf"):
            return overgeslagen(f"tegenhanger is geen PDF-document ({pdf.bestandsnaam})")
        if pdf.intake_bericht_id != ubl.intake_bericht_id:
            return overgeslagen("tegenhanger komt uit een ander intake-bericht dan het intake-bericht vermeldt")
        if pdf.soort != ubl.soort:
            return overgeslagen(f"documentsoort verschilt (UBL {ubl.soort}, tegenhanger {pdf.soort})")
        if pdf.bron_opslag_pad is not None:
            return overgeslagen(f"tegenhanger heeft al een beeld/bron ({pdf.bron_bestandsnaam})")
        if pdf.status not in _NABUNDEL_STATUSSEN:
            return overgeslagen(_status_reden(pdf.status))
        voorstel_behouden = session.get(Boekvoorstel, pdf.id) is not None

        if dry_run:
            return NabundelUitkomst(
                ubl_document_id=ubl.id,
                ubl_bestandsnaam=ubl.bestandsnaam,
                pdf_document_id=pdf.id,
                uitkomst=UITKOMST_KANDIDAAT,
                reden=(
                    "opgeslagen boekvoorstel aanwezig — UBL wordt alleen gekoppeld, voorstel blijft staan"
                    if voorstel_behouden
                    else f"samenvoegen + her-extractie uit de UBL (tegenhanger {pdf.bestandsnaam}, {pdf.status.value})"
                ),
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
            )

        # 1. UBL onder het administratie-prefix (kopie; de verzamelbak-locatie blijft staan).
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
        reden_pdf = "nabundel-nazorg: UBL uit dezelfde e-mail gekoppeld als databron, deze PDF is het beeld" + (
            " — opgeslagen boekvoorstel blijft ongewijzigd (geen her-extractie)"
            if voorstel_behouden
            else " — velden opnieuw uit de UBL gelezen"
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
                "reden": reden_pdf,
            },
        )

        # 3. UBL-rij → samengevoegd (terminaal, nooit verwijderen), mét de administratie voor de ongedaan-route.
        ubl.samengevoegd_in_id = pdf.id
        _schrijf_overgang(
            session,
            document=ubl,
            naar=DocumentStatus.SAMENGEVOEGD,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={
                "samengevoegd_in": str(pdf.id),
                "leidend_bestandsnaam": oud["bestandsnaam"],
                "nagebundeld": True,
                NABUNDEL_ADMINISTRATIE_SLEUTEL: str(adm),
                "reden": "nabundel-nazorg: gekoppeld aan het al toegewezen PDF-document uit dezelfde e-mail",
            },
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=pdf.id,
            actie="document_nagebundeld",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "opslag_pad": nieuw_pad,
                "bestandsnaam": ubl.bestandsnaam,
                "sha256_hash": ubl.sha256_hash,
                "bron_bestandsnaam": oud["bestandsnaam"],
                "samengevoegd_document_id": str(ubl.id),
                "voorstel_behouden": voorstel_behouden,
            },
            administratie_id=adm,
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
        reden=(
            "opgeslagen boekvoorstel aanwezig — alleen gekoppeld, voorstel ongewijzigd"
            if voorstel_behouden
            else f"status nu {eind_status.value if eind_status else '?'}"
        ),
    )


def nabundel_verzamelbak(*, dry_run: bool = False, opslag: DocumentOpslag | None = None) -> NabundelTelling:
    """Zie module-docstring. `dry_run` toetst álle poorten maar schrijft niets (uitkomst 'kandidaat' per rij)."""
    telling = NabundelTelling()
    kandidaten = vind_kandidaten()
    telling.kandidaten = len(kandidaten)
    opslag = opslag or _standaard_opslag()
    for kandidaat in kandidaten:
        try:
            uitkomst = _nabundel_een(kandidaat, opslag=opslag, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 — één kapot paar mag de stapel niet stoppen; wél zichtbaar
            logger.exception("Nabundelen mislukt voor %s", kandidaat.ubl_document_id)
            uitkomst = NabundelUitkomst(
                ubl_document_id=kandidaat.ubl_document_id,
                ubl_bestandsnaam=kandidaat.ubl_bestandsnaam,
                pdf_document_id=kandidaat.pdf_document_id,
                uitkomst=UITKOMST_MISLUKT,
                reden=f"onverwachte fout ({type(exc).__name__}: {exc})",
            )
        telling.registreer(uitkomst)
    return telling


# ---- Ongedaan maken ----------------------------------------------------------------------------


def nagebundelde_administratie(session, ubl_document_id: uuid.UUID) -> uuid.UUID | None:
    """De administratie uit de jongste `samengevoegd`-overgang van een nagebundelde UBL-rij (None =
    handmatig samengevoegd in de bak, of geen samengevoegd-overgang)."""
    rij = session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == ubl_document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.SAMENGEVOEGD,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).first()
    waarde = (rij.detail or {}).get(NABUNDEL_ADMINISTRATIE_SLEUTEL) if rij is not None else None
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def maak_nabundeling_ongedaan(
    *,
    administratie_id: uuid.UUID,
    ubl_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
) -> uuid.UUID:
    """Spiegel van `_nabundel_een` zolang het leidende document nog op te_controleren/handmatig_afmaken
    staat: de PDF wordt weer het hoofdbestand (kolommen terug, sha256 opnieuw uit de bytes), de
    bron-kolommen leeg, de UBL-rij terug in de verzamelbak. Het UBL-bestand onder het administratie-prefix
    blijft op de opslag staan (niets wordt verwijderd). Het veldvoorstel uit de UBL blijft in de tijdlijn —
    de tijdlijnregel zegt dat en verwijst naar 'Opnieuw extraheren' voor een verse PDF-lezing. Geeft het id
    van de teruggezette UBL-rij."""
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
        ubl.samengevoegd_in_id = None
        _schrijf_overgang(
            session,
            document=ubl,
            naar=DocumentStatus.NIET_TOEGEWEZEN,
            actor_id=actor_id,
            detail={
                "reden": "nabundeling ongedaan gemaakt — terug in de verzamelbak",
                "was_samengevoegd_in": str(leidend.id),
            },
        )
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
            },
            administratie_id=administratie_id,
        )
        return ubl.id
