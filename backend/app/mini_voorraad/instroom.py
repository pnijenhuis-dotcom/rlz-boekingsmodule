"""Instroom + storno-spiegel ÍN de boek-/tegenboek-transactie (②: het boekmoment, nooit het voorstel).

`registreer_bij_boeking` draait direct ná `projectverdeling_service.bevries_bij_boeking` in de GEBOEKT-transactie
(app/documenten/boeken.py) — samen met de statusovergang, of samen niet. Per productregel uit het LAATSTE
VELDVOORSTEL van het document (dezelfde lezer als de voorraad-aansluiting: `voorraad.service._laatste_veldvoorstel`
— dáár leven `hoeveelheid`, `artikelcode` (AI-veld `a`) en `eenheid` (`e`); het boekvoorstel kent alleen bedragen):

  dienst-/transportregel (`classificeer_soort`) → overslaan · geen/0 aantal → overslaan mét reden ·
  artikelcode per leverancier → bestaand product · exacte genormaliseerde omschrijving per leverancier → bestaand
  product · anders NIEUW product mét vlag "nieuw — controleer" (④: de stroom stopt nooit).

Idempotent per (document, boek_cyclus). Tijdlijnregel (detail-sleutel `mini_voorraad_bijgewerkt`) + audit in dezelfde
transactie. `registreer_storno` spiegelt élke instroom-mutatie van (document, cyclus) als −aantal (idempotent) —
aangeroepen vanuit het tegenboek-pad én de RLZ-UI-storno-detectie."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort
from app.mini_voorraad import service
from app.mini_voorraad.models import SOORT_INSTROOM, SOORT_STORNO, MiniProduct, MiniVoorraadMutatie
from app.sync.models import VendorCache
from app.voorraad import service as voorraad_service
from app.voorraad.models import ONBEKENDE_LEVERANCIER
from app.voorraad.normalisatie import classificeer_soort

logger = logging.getLogger(__name__)

TIJDLIJN_SLEUTEL = "mini_voorraad_bijgewerkt"
TIJDLIJN_SLEUTEL_STORNO = "mini_voorraad_teruggedraaid"


@dataclass(frozen=True)
class InstroomResultaat:
    regels: int
    nieuwe_producten: list[str] = field(default_factory=list)
    bestaande: int = 0
    overgeslagen: list[str] = field(default_factory=list)

    @property
    def tekst(self) -> str:
        delen = [f"Mini-voorraad bijgewerkt — {self.regels} regel{'s' if self.regels != 1 else ''}"]
        if self.nieuwe_producten:
            delen.append("nieuw: " + ", ".join(self.nieuwe_producten))
        if self.overgeslagen:
            delen.append(f"overgeslagen: {len(self.overgeslagen)}")
        return " · ".join(delen)


@dataclass(frozen=True)
class RegelUitkomst:
    """Pure matchbeslissing per regel (testbaar zonder DB): `actie` verwerken | overslaan mét reden."""

    volgnummer: int
    omschrijving: str
    aantal: Decimal | None
    artikelcode: str | None
    eenheid: str | None
    overslaan_reden: str | None = None


def beoordeel_regels(regels: list[dict]) -> list[RegelUitkomst]:
    """Deterministische voorselectie (③/①): dienst-/transportregels en regels zonder aantal vallen af mét reden;
    de rest gaat door naar de productmatch. `regels` = de `regels`-lijst van het veldvoorstel."""
    uit: list[RegelUitkomst] = []
    volgnummer = 0
    for r in regels:
        if not isinstance(r, dict) or not r.get("omschrijving"):
            continue
        volgnummer += 1
        omschrijving = str(r["omschrijving"]).strip()
        aantal = voorraad_service._als_decimal(r.get("hoeveelheid"))
        code = str(r["artikelcode"]) if r.get("artikelcode") else None
        eenheid = str(r["eenheid"]) if r.get("eenheid") else None
        soort = classificeer_soort(omschrijving)
        reden: str | None = None
        if soort is not None:
            reden = f"{soort}regel"
        elif aantal is None:
            reden = "geen aantal op de regel"
        elif aantal == 0:
            reden = "aantal 0"
        uit.append(RegelUitkomst(volgnummer, omschrijving, aantal, code, eenheid, reden))
    return uit


def _instroom_bestaat(session: Session, *, document_id: uuid.UUID, boek_cyclus: int) -> bool:
    return (
        session.scalar(
            select(MiniVoorraadMutatie.id)
            .where(
                MiniVoorraadMutatie.document_id == document_id,
                MiniVoorraadMutatie.boek_cyclus == boek_cyclus,
                MiniVoorraadMutatie.soort == SOORT_INSTROOM,
            )
            .limit(1)
        )
        is not None
    )


def _tijdlijn(session: Session, *, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
    """Tijdlijnregel zónder statusovergang (tegenboeken/doorbelasting-patroon)."""
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


def registreer_bij_boeking(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    boek_cyclus: int,
    actor_id: uuid.UUID,
    regels: object | None = None,  # boekvoorstel-regels: alleen bedragen — de aantallen komen uit het veldvoorstel
    vendor_id: uuid.UUID | None = None,
) -> InstroomResultaat | None:
    """None = opt-in uit, geen inkoopfactuur, of al verwerkt voor deze (document, cyclus). Anders het resultaat —
    ook met 0 regels (alles overgeslagen), zodat de tijdlijn laat zien dát de mini-voorraad gekeken heeft."""
    if not service.is_ingeschakeld(session, administratie_id):
        return None
    document = session.get(Document, document_id)
    if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
        return None
    if _instroom_bestaat(session, document_id=document_id, boek_cyclus=boek_cyclus):
        return None

    voorstel = session.get(Boekvoorstel, document_id)
    vendor = vendor_id or (voorstel.vendor_id if voorstel is not None else None) or ONBEKENDE_LEVERANCIER
    leverancier: str | None = None
    if vendor != ONBEKENDE_LEVERANCIER:
        vc = session.get(VendorCache, (vendor, administratie_id))
        leverancier = vc.naam if vc is not None else None
    veldvoorstel = voorraad_service._laatste_veldvoorstel(session, document_id) or {}
    leverancier = leverancier or veldvoorstel.get("leverancier_naam")
    # Boekingsdatum = factuurdatum (BookDate-lijn 28-08); zonder factuurdatum de dag van boeken.
    datum: date = (voorstel.factuurdatum if voorstel is not None and voorstel.factuurdatum else None) or date.today()

    uitkomsten = beoordeel_regels(veldvoorstel.get("regels") or [])
    nieuwe: list[str] = []
    bestaande = 0
    overgeslagen: list[str] = []
    verwerkt = 0
    gezien: set[uuid.UUID] = set()
    for u in uitkomsten:
        if u.overslaan_reden is not None:
            overgeslagen.append(f"regel {u.volgnummer} '{u.omschrijving[:60]}' — {u.overslaan_reden}")
            continue
        assert u.aantal is not None
        product, is_nieuw = service.vind_of_maak_product(
            session,
            administratie_id=administratie_id,
            vendor_id=vendor,
            leverancier_naam=leverancier,
            omschrijving=u.omschrijving,
            artikelcode=u.artikelcode,
            eenheid=u.eenheid,
            bron_document_id=document_id,
            actor_id=actor_id,
        )
        if is_nieuw:
            nieuwe.append(product.omschrijving)
        elif product.id not in gezien:
            bestaande += 1
        gezien.add(product.id)
        session.add(
            MiniVoorraadMutatie(
                administratie_id=administratie_id,
                product_id=product.id,
                soort=SOORT_INSTROOM,
                aantal=u.aantal.quantize(Decimal("0.001")),
                datum=datum,
                document_id=document_id,
                regel_volgnummer=u.volgnummer,
                boek_cyclus=boek_cyclus,
                aangemaakt_door=actor_id,
            )
        )
        verwerkt += 1
    session.flush()
    resultaat = InstroomResultaat(
        regels=verwerkt, nieuwe_producten=nieuwe, bestaande=bestaande, overgeslagen=overgeslagen
    )
    if verwerkt == 0 and not overgeslagen:
        return resultaat  # geen productregels in het veldvoorstel — niets te melden
    _tijdlijn(
        session,
        document=document,
        actor_id=actor_id,
        detail={
            TIJDLIJN_SLEUTEL: {
                "regels": verwerkt,
                "nieuwe_producten": nieuwe,
                "bestaande": bestaande,
                "overgeslagen": overgeslagen,
                "boek_cyclus": boek_cyclus,
                "tekst": resultaat.tekst,
            }
        },
    )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="mi",
        tabel="mini_voorraad_mutatie",
        record_id=document_id,
        actie="mini_voorraad_instroom",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "document_id": str(document_id),
            "boek_cyclus": boek_cyclus,
            "regels": verwerkt,
            "nieuwe_producten": nieuwe,
            "bestaande": bestaande,
            "overgeslagen": overgeslagen,
        },
        administratie_id=administratie_id,
    )
    return resultaat


def registreer_storno(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    boek_cyclus: int,
    actor_id: uuid.UUID,
    reden: str | None = None,
) -> int:
    """Spiegelt élke instroom-mutatie van (document, cyclus) als `storno` met −aantal — idempotent (bestaat er al
    een storno voor die combinatie, dan 0). Datum = de dag van terugdraaien. Geeft het aantal spiegelrijen terug.
    Geen opt-in-toets: wat ooit is bijgeteld moet altijd terug kunnen, ook als de opt-in intussen uit staat."""
    instroom = session.scalars(
        select(MiniVoorraadMutatie).where(
            MiniVoorraadMutatie.document_id == document_id,
            MiniVoorraadMutatie.boek_cyclus == boek_cyclus,
            MiniVoorraadMutatie.soort == SOORT_INSTROOM,
        )
    ).all()
    if not instroom:
        return 0
    al_gestorneerd = session.scalar(
        select(MiniVoorraadMutatie.id)
        .where(
            MiniVoorraadMutatie.document_id == document_id,
            MiniVoorraadMutatie.boek_cyclus == boek_cyclus,
            MiniVoorraadMutatie.soort == SOORT_STORNO,
        )
        .limit(1)
    )
    if al_gestorneerd is not None:
        return 0
    vandaag = date.today()
    toelichting = (reden or "boeking teruggedraaid").strip()[:1000]
    for m in instroom:
        session.add(
            MiniVoorraadMutatie(
                administratie_id=administratie_id,
                product_id=m.product_id,
                soort=SOORT_STORNO,
                aantal=-m.aantal,
                datum=vandaag,
                document_id=document_id,
                regel_volgnummer=m.regel_volgnummer,
                boek_cyclus=boek_cyclus,
                toelichting=toelichting,
                aangemaakt_door=actor_id,
            )
        )
    session.flush()
    document = session.get(Document, document_id)
    omschrijvingen = [
        p.omschrijving
        for p in session.scalars(select(MiniProduct).where(MiniProduct.id.in_({m.product_id for m in instroom})))
    ]
    if document is not None:
        _tijdlijn(
            session,
            document=document,
            actor_id=actor_id,
            detail={
                TIJDLIJN_SLEUTEL_STORNO: {
                    "regels": len(instroom),
                    "producten": omschrijvingen,
                    "boek_cyclus": boek_cyclus,
                    "reden": toelichting,
                    "tekst": f"Mini-voorraad teruggedraaid — {len(instroom)} regel{'s' if len(instroom) != 1 else ''}",
                }
            },
        )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="mi",
        tabel="mini_voorraad_mutatie",
        record_id=document_id,
        actie="mini_voorraad_storno",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "document_id": str(document_id),
            "boek_cyclus": boek_cyclus,
            "regels": len(instroom),
            "producten": omschrijvingen,
            "reden": toelichting,
        },
        administratie_id=administratie_id,
    )
    return len(instroom)
