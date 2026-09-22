"""Omzetvoorstel-servicelaag (mockup #omzetreview): het reviewscherm-voorstel per
kassarapport-document — prefill uit het AI-veldvoorstel + de onthouden categorie-mapping,
opslaan mét mapping-leren, en de orkestratie van de harde checks (app/omzet/checks.py)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport, CheckResultaat
from app.documenten.models import Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.documenten.service import DocumentNietGevonden
from app.omzet import checks as omzet_checks
from app.omzet.mapping import MappingData, actieve_mappings, normaliseer_categorie_sleutel, onthoud_mapping
from app.omzet.models import (
    OmzetBoeking,
    OmzetBoekingStatus,
    OmzetInstelling,
    OmzetVoorstel,
    OmzetVoorstelRegel,
)
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

# Zelfde bevriezings-regel als het inkoop-boekvoorstel: na GEBOEKT is RLZ de bron van waarheid,
# na VERWIJDERD eerst expliciet herstellen.
_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class OmzetVoorstelFout(Exception):
    """Domeinfout in de omzetvoorstel-servicelaag."""


class GeenKassarapport(OmzetVoorstelFout):
    """Het omzetvoorstel bestaat alleen voor documenten met soort 'kassarapport'."""


@dataclass(frozen=True)
class OmzetRegelData:
    categorie: str
    categorie_sleutel: str | None
    omzet_bedrag: Decimal | None
    kostprijs_bedrag: Decimal | None
    omzet_ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    kostprijs_ledger_id: uuid.UUID | None
    # Herkomst voor de UI-chips: 'mapping' (onthouden), 'nieuw' (geen mapping — blokkerend tot
    # ingesteld), 'default' (PSP-kostenrekening op naam) of 'opgeslagen' (uit een eerder opgeslagen voorstel).
    herkomst: str
    # Blok C/D (16-09): waar de voorgestelde btw vandaan komt — 'mapping' | 'instelling' (categorie_btw, mens) |
    # 'default_laag' | 'default_hoog' | 'verlegd' (PSP-kosten Stripe: "Stripe · EU-dienst verlegd") | 'opgeslagen' |
    # None (mens kiest). Chip-tekst in `btw_herkomst_detail`.
    btw_herkomst: str | None = None
    btw_herkomst_detail: str | None = None


@dataclass(frozen=True)
class OmzetVoorstelData:
    document_id: uuid.UUID
    periode_start: date | None
    periode_eind: date | None
    rapport_totaal_omzet: Decimal | None
    rapport_totaal_kostprijs: Decimal | None
    marge_pct: Decimal | None
    regels: list[OmzetRegelData]
    voorraad_ledger_id: uuid.UUID | None
    opgeslagen: bool
    rapport_titel: str | None = None
    entiteit_naam: str | None = None
    # Omzetbronnen (Peter 15-09): 'zonnestudio_dagstaat' | 'pilates_betalingsexport' | None (AI-rapport); `bron_detail`
    # = betaalwijzen/kas/controles/batch uit de bron — informatief voor het controlescherm én de harde checks.
    bron: str | None = None
    bron_detail: dict | None = None
    # Peter 19-09: bron van de automatische typering (inkoopfactuur → kassarapport); None = mens koos de soort.
    automatisch_getypeerd_bron: str | None = None


def _laad_kassarapport(session: Session, *, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != DocumentSoort.KASSARAPPORT.value:
        raise GeenKassarapport(f"Document {document_id} is geen kassarapport (soort: {document.soort})")
    return document


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    return next(
        (
            g.detail["veldvoorstel"]
            for g in reversed(
                list(
                    session.scalars(
                        select(DocumentGebeurtenis)
                        .where(DocumentGebeurtenis.document_id == document_id)
                        .order_by(DocumentGebeurtenis.tijdstip)
                    )
                )
            )
            if g.detail and "veldvoorstel" in g.detail
        ),
        None,
    )


def _als_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _als_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde)
    except ValueError:
        return None


def _instelling(session: Session, administratie_id: uuid.UUID) -> OmzetInstelling | None:
    return session.get(OmzetInstelling, administratie_id)


@dataclass(frozen=True)
class BtwDefaults:
    """Btw-prefill van de omzetbronnen (blok C/D, 16-09): mens-override per categorie (`categorie_btw`) > mapping >
    klasse-default (laag/hoog uit het RLZ-tarief van de administratie; PSP-kosten verlegd/hoog per `psp`) > leeg."""

    categorie_btw: dict[str, uuid.UUID]
    per_klasse: dict[str, uuid.UUID | None]
    instellingen: dict
    psp_kosten_ledger_id: uuid.UUID | None = None
    verlegd_detail: str | None = None

    def voor(self, sleutel: str | None, mapping: MappingData | None) -> tuple[uuid.UUID | None, str | None, str | None]:
        from app.omzet.bronnen import tegenzijde as tz

        if sleutel and sleutel in self.categorie_btw:
            return self.categorie_btw[sleutel], "instelling", "btw ingesteld per categorie"
        if mapping is not None:
            return mapping.taxrate_id, "mapping", None
        klasse = tz.btw_klasse_voor(sleutel, self.instellingen)
        if klasse is None:
            return None, None, None
        taxrate_id = self.per_klasse.get(klasse)
        if taxrate_id is None:
            return None, None, None
        if klasse == tz.BTW_VERLEGD:
            return taxrate_id, "verlegd", tz.psp_btw_herkomst(tz.psp_naam(self.instellingen)) or self.verlegd_detail
        if sleutel == tz.CATEGORIE_PSP_KOSTEN_SLEUTEL:
            return taxrate_id, f"default_{klasse}", tz.psp_btw_herkomst(tz.psp_naam(self.instellingen))
        return taxrate_id, f"default_{klasse}", f"standaard {klasse} tarief voor deze categorie"


def _btw_defaults(session: Session, administratie_id: uuid.UUID) -> BtwDefaults:
    from app.omzet.bronnen import service as bronnen_service

    instellingen = bronnen_service.bron_instellingen_voor(session, administratie_id)
    defaults = bronnen_service.defaults_voor(session, administratie_id, instellingen=instellingen)
    categorie_btw: dict[str, uuid.UUID] = {}
    for categorie, taxrate in (instellingen.get("categorie_btw") or {}).items():
        sleutel = normaliseer_categorie_sleutel(categorie)
        if sleutel and taxrate:
            try:
                categorie_btw[sleutel] = uuid.UUID(str(taxrate))
            except ValueError:
                continue
    pk = instellingen.get("psp_kosten_ledger_id") or defaults.get("psp_kosten_ledger_id")
    return BtwDefaults(
        categorie_btw=categorie_btw,
        per_klasse={k: (uuid.UUID(v) if v else None) for k, v in (defaults.get("btw_per_klasse") or {}).items()},
        instellingen=instellingen,
        psp_kosten_ledger_id=uuid.UUID(str(pk)) if pk else None,
        verlegd_detail=defaults.get("verlegd_herkomst"),
    )


def _regel_uit_mapping(
    *,
    categorie: str,
    omzet: Decimal | None,
    kostprijs: Decimal | None,
    mappings: dict[str, MappingData],
    btw_defaults: BtwDefaults | None = None,
) -> OmzetRegelData:
    from app.omzet.bronnen import tegenzijde as tz

    sleutel = normaliseer_categorie_sleutel(categorie)
    mapping = mappings.get(sleutel) if sleutel else None
    taxrate_id = mapping.taxrate_id if mapping else None
    btw_herkomst = "mapping" if mapping else None
    btw_detail = None
    omzet_ledger_id = mapping.omzet_ledger_id if mapping else None
    herkomst = "mapping" if mapping else "nieuw"
    if btw_defaults is not None:
        taxrate_id, btw_herkomst, btw_detail = btw_defaults.voor(sleutel, mapping)
        if (
            mapping is None
            and sleutel == tz.CATEGORIE_PSP_KOSTEN_SLEUTEL
            and btw_defaults.psp_kosten_ledger_id is not None
        ):
            omzet_ledger_id = btw_defaults.psp_kosten_ledger_id
            herkomst = "default"
    return OmzetRegelData(
        categorie=categorie,
        categorie_sleutel=sleutel,
        omzet_bedrag=omzet,
        kostprijs_bedrag=kostprijs,
        omzet_ledger_id=omzet_ledger_id,
        taxrate_id=taxrate_id,
        kostprijs_ledger_id=mapping.kostprijs_ledger_id if mapping else None,
        herkomst=herkomst,
        btw_herkomst=btw_herkomst,
        btw_herkomst_detail=btw_detail,
    )


def _met_tegenzijde(session: Session, administratie_id: uuid.UUID, veldvoorstel: dict) -> dict | None:
    """`bron_detail` + `tegenzijde` (blok A): per betaalwijze bedrag, datum-anker, tegenrekening + herkomst en de
    controles "Tegenrekening ‹betaalwijze›" — live berekend uit de actuele instellingen (niet bevroren in het
    veldvoorstel, zodat een Beheerder-instelling direct doorwerkt op nog niet geboekte documenten)."""
    from app.omzet.bronnen import service as bronnen_service
    from app.omzet.bronnen import tegenzijde as tz

    bron = veldvoorstel.get("bron")
    detail = veldvoorstel.get("bron_detail")
    if not bron or detail is None:
        return detail
    uitkomst = tz.bepaal_tegenzijde(
        bron=bron,
        bron_detail={**detail, "periode_eind": veldvoorstel.get("periode_eind")},
        instellingen=bronnen_service.bron_instellingen_voor(session, administratie_id),
        rekeningen=bronnen_service.rekeningen_voor(session, administratie_id),
    )
    verrijkt = {**detail, "tegenzijde": uitkomst.als_dict()} if uitkomst is not None else dict(detail)
    # ProfX (blok F): live kostprijs-stand (verwacht / gekoppeld weekrapport / geboekt / gebundeld) op het dagjournaal.
    marge_stand = bronnen_service.profx_marge_stand(
        session, administratie_id=administratie_id, veldvoorstel=veldvoorstel
    )
    if marge_stand is not None:
        verrijkt["marge"] = marge_stand
    return verrijkt


def haal_omzet_voorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> OmzetVoorstelData:
    """Het opgeslagen omzetvoorstel, of — zolang er niets opgeslagen is — een prefill uit het
    AI-veldvoorstel met de onthouden mapping per categorie erop toegepast. De marge wordt hier
    (code, niet AI) uit de actuele totalen berekend."""
    with scoped_session(administratie_id) as session:
        _laad_kassarapport(session, document_id=document_id)
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
        instelling = _instelling(session, administratie_id)
        voorraad_ledger_id = instelling.voorraad_ledger_id if instelling else None
        mappings = actieve_mappings(session, administratie_id=administratie_id)
        bron_detail = _met_tegenzijde(session, administratie_id, veldvoorstel)
        btw_defaults = _btw_defaults(session, administratie_id) if veldvoorstel.get("bron") else None
        from app.omzet import autotype

        auto = autotype.is_automatisch_getypeerd(session, document_id=document_id)
        auto_bron = (auto.get("bron") or "onbekend") if auto is not None else None

        bestaand = session.get(OmzetVoorstel, document_id)
        if bestaand is not None:
            regels_orm = session.scalars(
                select(OmzetVoorstelRegel)
                .where(OmzetVoorstelRegel.document_id == document_id)
                .order_by(OmzetVoorstelRegel.volgnummer)
            ).all()
            regels = [
                OmzetRegelData(
                    categorie=r.categorie,
                    categorie_sleutel=r.categorie_sleutel,
                    omzet_bedrag=r.omzet_bedrag,
                    kostprijs_bedrag=r.kostprijs_bedrag,
                    omzet_ledger_id=r.omzet_ledger_id,
                    taxrate_id=r.taxrate_id,
                    kostprijs_ledger_id=r.kostprijs_ledger_id,
                    herkomst="opgeslagen" if r.omzet_ledger_id is not None else "nieuw",
                    btw_herkomst="opgeslagen" if r.taxrate_id is not None else None,
                )
                for r in regels_orm
            ]
            return OmzetVoorstelData(
                document_id=document_id,
                periode_start=bestaand.periode_start,
                periode_eind=bestaand.periode_eind,
                rapport_totaal_omzet=bestaand.rapport_totaal_omzet,
                rapport_totaal_kostprijs=bestaand.rapport_totaal_kostprijs,
                marge_pct=omzet_checks.bereken_marge_pct(
                    totaal_omzet=bestaand.rapport_totaal_omzet,
                    totaal_kostprijs=bestaand.rapport_totaal_kostprijs,
                ),
                regels=regels,
                voorraad_ledger_id=voorraad_ledger_id,
                opgeslagen=True,
                rapport_titel=veldvoorstel.get("rapport_titel"),
                entiteit_naam=veldvoorstel.get("entiteit_naam"),
                bron=veldvoorstel.get("bron"),
                bron_detail=bron_detail,
                automatisch_getypeerd_bron=auto_bron,
            )

        totaal_omzet = _als_decimal(veldvoorstel.get("totaal_omzet"))
        totaal_kostprijs = _als_decimal(veldvoorstel.get("totaal_kostprijs"))
        regels = [
            _regel_uit_mapping(
                categorie=r.get("categorie") or f"Categorie {i}",
                omzet=_als_decimal(r.get("omzet_bedrag")),
                kostprijs=_als_decimal(r.get("kostprijs_bedrag")),
                mappings=mappings,
                btw_defaults=btw_defaults,
            )
            for i, r in enumerate((veldvoorstel.get("regels") or []), start=1)
            if isinstance(r, dict)
        ]
        return OmzetVoorstelData(
            document_id=document_id,
            periode_start=_als_datum(veldvoorstel.get("periode_start")),
            periode_eind=_als_datum(veldvoorstel.get("periode_eind")),
            rapport_totaal_omzet=totaal_omzet,
            rapport_totaal_kostprijs=totaal_kostprijs,
            marge_pct=omzet_checks.bereken_marge_pct(totaal_omzet=totaal_omzet, totaal_kostprijs=totaal_kostprijs),
            regels=regels,
            voorraad_ledger_id=voorraad_ledger_id,
            opgeslagen=False,
            rapport_titel=veldvoorstel.get("rapport_titel"),
            entiteit_naam=veldvoorstel.get("entiteit_naam"),
            bron=veldvoorstel.get("bron"),
            bron_detail=bron_detail,
            automatisch_getypeerd_bron=auto_bron,
        )


@dataclass(frozen=True)
class OmzetRegelInput:
    categorie: str
    omzet_bedrag: Decimal | None
    kostprijs_bedrag: Decimal | None
    omzet_ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    kostprijs_ledger_id: uuid.UUID | None


def sla_omzet_voorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    periode_start: date | None,
    periode_eind: date | None,
    rapport_totaal_omzet: Decimal | None,
    rapport_totaal_kostprijs: Decimal | None,
    regels: list[OmzetRegelInput],
    voorraad_ledger_id: uuid.UUID | None,
    mapping_onthouden: bool = True,
) -> OmzetVoorstelData:
    """Slaat het reviewscherm-voorstel op. `mapping_onthouden` (default aan, mockup: "mapping
    onthouden per administratie") legt de gekozen GB/btw/kostprijs-GB per volledig gemapte
    categorie vast als mapping voor volgende rapporten; de voorraad-tegenrekening gaat naar de
    omzet-instelling van de administratie."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_kassarapport(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN:
            raise OmzetVoorstelFout(
                f"Document {document_id} kan niet meer gewijzigd worden (status: {document.status.value})"
            )

        bestaand = session.get(OmzetVoorstel, document_id)
        if bestaand is None:
            bestaand = OmzetVoorstel(document_id=document_id)
            session.add(bestaand)
        bestaand.periode_start = periode_start
        bestaand.periode_eind = periode_eind
        bestaand.rapport_totaal_omzet = rapport_totaal_omzet
        bestaand.rapport_totaal_kostprijs = rapport_totaal_kostprijs

        session.execute(delete(OmzetVoorstelRegel).where(OmzetVoorstelRegel.document_id == document_id))
        for i, regel in enumerate(regels, start=1):
            session.add(
                OmzetVoorstelRegel(
                    document_id=document_id,
                    volgnummer=i,
                    categorie=regel.categorie,
                    categorie_sleutel=normaliseer_categorie_sleutel(regel.categorie) or "",
                    omzet_bedrag=regel.omzet_bedrag,
                    kostprijs_bedrag=regel.kostprijs_bedrag,
                    omzet_ledger_id=regel.omzet_ledger_id,
                    taxrate_id=regel.taxrate_id,
                    kostprijs_ledger_id=regel.kostprijs_ledger_id,
                )
            )
            if mapping_onthouden and regel.omzet_ledger_id is not None and regel.taxrate_id is not None:
                onthoud_mapping(
                    session,
                    administratie_id=administratie_id,
                    actor_id=actor_id,
                    categorie=regel.categorie,
                    omzet_ledger_id=regel.omzet_ledger_id,
                    taxrate_id=regel.taxrate_id,
                    kostprijs_ledger_id=regel.kostprijs_ledger_id,
                )

        if voorraad_ledger_id is not None:
            instelling = _instelling(session, administratie_id)
            if instelling is None:
                instelling = OmzetInstelling(administratie_id=administratie_id)
                session.add(instelling)
            if instelling.voorraad_ledger_id != voorraad_ledger_id:
                oud = instelling.voorraad_ledger_id
                instelling.voorraad_ledger_id = voorraad_ledger_id
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="omzet_instelling",
                    record_id=administratie_id,
                    actie="omzet_voorraad_rekening_gewijzigd",
                    correlatie_id=uuid.uuid4(),
                    oude_waarde={"voorraad_ledger_id": str(oud)} if oud else None,
                    nieuwe_waarde={"voorraad_ledger_id": str(voorraad_ledger_id)},
                    administratie_id=administratie_id,
                )

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="omzet_voorstel",
            record_id=document_id,
            actie="omzet_voorstel_opgeslagen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "periode_start": periode_start.isoformat() if periode_start else None,
                "periode_eind": periode_eind.isoformat() if periode_eind else None,
                "aantal_regels": len(regels),
            },
            administratie_id=administratie_id,
        )

    return haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)


def memoriaal_referentie(periode_start: date, periode_eind: date) -> str:
    """Deterministische, periode-gebonden referentie van het kostprijsmemoriaal — bewust een
    functie van de PERIODE (niet het document): een tweede document over dezelfde periode raakt
    dezelfde referentie en valt daarmee door de RLZ-side duplicaatcheck. Past ruim binnen RLZ's
    30-tekens-afkap (24 tekens)."""
    return f"OMZ-{periode_start:%Y%m%d}-{periode_eind:%Y%m%d}-KP"


def verkoop_omschrijving(periode_start: date, periode_eind: date) -> str:
    """Deterministische, periode-gebonden duplicaat-marker van de entity-loze verkoopboeking —
    zelfde principe als memoriaal_referentie: een tweede document over dezelfde periode raakt
    dezelfde marker en valt daarmee door de Receipts-duplicaatcheck (de collectie ziet óók
    API-documenten — Receipts-verkenning). ⚠️ Sinds verkoop-STAP-0 (2026-08-09) staat de marker
    als PREFIX in regel 1 van de boeking en filtert de check op startswith: RLZ negeert de
    document-Description en leidt 'm af uit de éérste regel-Description — een marker die alleen
    op documentniveau gezet wordt landt dus nooit in de collectie. Prefix-botsing kan niet:
    het formaat heeft een vaste lengte (OMZ-YYYYMMDD-YYYYMMDD-VK)."""
    return f"OMZ-{periode_start:%Y%m%d}-{periode_eind:%Y%m%d}-VK"


def bouw_memoriaal_regels(*, regels: list[OmzetRegelData] | list[OmzetRegelInput]) -> list[omzet_checks.MemoriaalRegel]:
    """Het kostprijsmemoriaal zoals het geboekt gaat worden (debet kostprijs per categorie,
    credit voorraad voor het totaal) in check-vorm — de saldo-0-check toetst wat er écht naar
    RLZ zou gaan, niet een aanname. Zonder kostprijsregels is er geen memoriaal (lege lijst)."""
    kostprijs_regels = [r for r in regels if r.kostprijs_bedrag is not None and r.kostprijs_bedrag != 0]
    if not kostprijs_regels:
        return []
    memoriaal = [omzet_checks.MemoriaalRegel(debet_bedrag=r.kostprijs_bedrag or Decimal(0)) for r in kostprijs_regels]
    totaal = sum((r.kostprijs_bedrag or Decimal(0) for r in kostprijs_regels), Decimal(0))
    memoriaal.append(omzet_checks.MemoriaalRegel(credit_bedrag=totaal))
    return memoriaal


def _historische_marges(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[Decimal]:
    boekingen = session.scalars(
        select(OmzetBoeking)
        .where(
            OmzetBoeking.administratie_id == administratie_id,
            OmzetBoeking.document_id != document_id,
            OmzetBoeking.status == OmzetBoekingStatus.GEBOEKT.value,
        )
        .order_by(OmzetBoeking.periode_eind.desc())
        .limit(settings.omzet_marge_historie_boekingen)
    ).all()
    marges = []
    for boeking in boekingen:
        marge = omzet_checks.bereken_marge_pct(
            totaal_omzet=boeking.totaal_omzet, totaal_kostprijs=boeking.totaal_kostprijs
        )
        if marge is not None:
            marges.append(marge)
    return marges


def _bestaande_periodes(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[date, date]]:
    boekingen = session.scalars(
        select(OmzetBoeking).where(
            OmzetBoeking.administratie_id == administratie_id,
            OmzetBoeking.document_id != document_id,
            OmzetBoeking.status.in_((OmzetBoekingStatus.GEBOEKT.value, OmzetBoekingStatus.HALF_GEBOEKT.value)),
        )
    )
    return [(b.periode_start, b.periode_eind) for b in boekingen]


def _naar_check_regels(regels: list[OmzetRegelData]) -> list[omzet_checks.OmzetCheckRegel]:
    return [
        omzet_checks.OmzetCheckRegel(
            categorie=r.categorie,
            omzet_bedrag=r.omzet_bedrag,
            kostprijs_bedrag=r.kostprijs_bedrag,
            omzet_ledger_id=r.omzet_ledger_id,
            taxrate_id=r.taxrate_id,
            kostprijs_ledger_id=r.kostprijs_ledger_id,
        )
        for r in regels
    ]


def voer_omzet_checks_uit(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> CheckRapport:
    """Herleest het actuele voorstel en toetst alle harde omzet-checks. `client=None` opent een
    eigen RLZ-verbinding; lukt dat niet, dan wordt uitsluitend de RLZ-side duplicaatcheck een
    blokkerend "kon niet uitgevoerd worden"-resultaat (fail-closed) — de lokale checks draaien
    gewoon door, nooit een kale 500 (zelfde patroon als de inkoopchecks)."""
    voorstel = haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(administratie_id) as session:
        document = _laad_kassarapport(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN:
            raise OmzetVoorstelFout(
                f"Document {document_id} kan niet meer gecontroleerd worden (status: {document.status.value})"
            )
        historie = _historische_marges(session, administratie_id=administratie_id, document_id=document_id)
        periodes = _bestaande_periodes(session, administratie_id=administratie_id, document_id=document_id)

    rlz_hits: int | None = None
    rlz_verkoop_hits: int | None = None
    # Peter 16-09 (Van Boxtel): harde check "Omzetcategorie (Inkomsten)" — leest de categorieën mét binder, ververst de
    # keuzelijst-cache voor het scherm; zonder client = blokkerend "niet gecontroleerd" (fail-closed).
    categorie_check: CheckResultaat | None = None
    if voorstel.periode_start is not None and voorstel.periode_eind is not None:
        referentie = memoriaal_referentie(voorstel.periode_start, voorstel.periode_eind)
        omschrijving = verkoop_omschrijving(voorstel.periode_start, voorstel.periode_eind)
        eigen_memoriaal_id = None
        eigen_verkoop_id = None
        with scoped_session(administratie_id) as session:
            eigen = session.scalars(select(OmzetBoeking).where(OmzetBoeking.document_id == document_id)).first()
            eigen_memoriaal_id = str(eigen.memoriaal_rlz_id) if eigen else None
            eigen_verkoop_id = str(eigen.verkoop_rlz_id) if eigen else None
        eigen_client = client is None
        try:
            if client is None:
                rlz_admin_id = rlz_admin_id_voor(administratie_id)
                client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
            from app.documenten.rlz_ids import rlz_kostprijs_memoriaal_id, rlz_sales_invoice_id

            # Memoriaal-kant: vreemde ManualJournals met onze periode-referentie. Een hit op ons
            # EIGEN GUID (retry na een eerdere poging) is geen duplicaat.
            gevonden = client.find_manual_journals_by_reference(reference=referentie)
            eigen_ids = {str(rlz_kostprijs_memoriaal_id(document_id))}
            if eigen_memoriaal_id:
                eigen_ids.add(eigen_memoriaal_id)
            rlz_hits = len([m for m in gevonden if m.get("id") not in eigen_ids])
            # Verkoop-kant (Receipts-verkenning: de Receipts-collectie ziet — anders dan
            # SalesInvoices — óók API-documenten): vreemde Receipts met onze deterministische
            # periode-marker. Startswith, niet exact: RLZ leidt de document-Description af uit
            # de éérste regel-Description (verkoop-STAP-0 2026-08-09), dus de marker staat als
            # prefix in regel 1 van de boeking.
            receipts = client.find_receipts_by_description_prefix(prefix=omschrijving)
            eigen_verkoop_ids = {str(rlz_sales_invoice_id(document_id))}
            if eigen_verkoop_id:
                eigen_verkoop_ids.add(eigen_verkoop_id)
            rlz_verkoop_hits = len([r for r in receipts if r.get("id") not in eigen_verkoop_ids])
            from app.omzet import categorie as categorie_service

            categorie_check = categorie_service.check_resultaat(client, administratie_id)
        except Exception as exc:  # noqa: BLE001 — fail-closed: check wordt blokkerend, crasht nooit
            logger.warning("RLZ-duplicaatcheck omzet kon niet uitgevoerd worden: %s", exc)
            rlz_hits = None
            rlz_verkoop_hits = None
        finally:
            if eigen_client and client is not None:
                client.close()

    periode_compleet = bool(voorstel.periode_start and voorstel.periode_eind)
    rapport = omzet_checks.voer_omzet_checks_uit(
        periode_start=voorstel.periode_start,
        periode_eind=voorstel.periode_eind,
        regels=_naar_check_regels(voorstel.regels),
        voorraad_ledger_id=voorstel.voorraad_ledger_id,
        memoriaal_regels=bouw_memoriaal_regels(regels=voorstel.regels),
        rapport_totaal_omzet=voorstel.rapport_totaal_omzet,
        rapport_totaal_kostprijs=voorstel.rapport_totaal_kostprijs,
        bestaande_periodes=periodes,
        rlz_memoriaal_hits=rlz_hits if periode_compleet else 0,
        rlz_verkoop_hits=rlz_verkoop_hits if periode_compleet else 0,
        historische_marges=historie,
        bandbreedte_procentpunt=Decimal(str(settings.omzet_marge_bandbreedte_procentpunt)),
    )
    rapport = _met_bron_controles(rapport, voorstel.bron_detail)
    rapport = _met_niet_btw_plichtig(rapport, administratie_id=administratie_id, regels=voorstel.regels)
    from app.omzet import categorie as categorie_service

    if categorie_check is None:
        categorie_check = CheckResultaat(
            naam=categorie_service.CHECK_NAAM,
            ok=False,
            melding="Omzetcategorie nog niet gecontroleerd (periode ontbreekt of geen RLZ-verbinding)",
        )
    return CheckRapport((*rapport.resultaten, categorie_check))


NAAM_BTW_NIET_PLICHTIG = "Btw in niet-btw-plichtige administratie"


def _met_niet_btw_plichtig(
    rapport: CheckRapport, *, administratie_id: uuid.UUID, regels: list[OmzetRegelData]
) -> CheckRapport:
    """22-09 (BUG Peter, casus VGG / Lacy Lion): in een NIET-btw-plichtige administratie wordt het kassabedrag bruto
    geboekt (`boeken._taxrate_percentages` → 0); een categorie mét een tarief > 0 % / verlegd is dan BLOKKEREND
    (de mens kiest 'geen btw' in de categorie-mapping). Btw-plichtig = geen extra rij."""
    from app.db.models import Administratie
    from app.sync.btw import taxrate_vlaggen
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or administratie.btw_plichtig:
            return rapport
        tarieven = {
            t.id: t
            for t in session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
        }
    fouten: list[str] = []
    for r in regels:
        if r.taxrate_id is None:
            continue
        t = tarieven.get(r.taxrate_id)
        if t is None:
            continue
        verlegd, _ = taxrate_vlaggen(t.brondata)
        if (t.percentage is not None and t.percentage > 0) or verlegd:
            fouten.append(f"{r.categorie}: {t.naam or r.taxrate_id}")
    if fouten:
        rij = CheckResultaat(
            NAAM_BTW_NIET_PLICHTIG,
            False,
            "Deze administratie is niet btw-plichtig — het kassabedrag gaat bruto in de omzet; kies per categorie de "
            "btw-code 'geen btw' (vrijgesteld/0 %): " + "; ".join(fouten),
        )
    else:
        rij = CheckResultaat(
            NAAM_BTW_NIET_PLICHTIG, True, "Administratie is niet btw-plichtig — omzet bruto, geen btw-splitsing"
        )
    return CheckRapport((*rapport.resultaten, rij))


def _met_bron_controles(rapport: CheckRapport, bron_detail: dict | None) -> CheckRapport:
    """Omzetbronnen (Peter 15-09): de deterministische controles van de bron (Grand Total sluit, deposit-som,
    kascheck-datum, wederhelft ontvangen, puntenwaarde, factuurnummer al geboekt, …) als harde check-rijen —
    blokkerend rood, niet-blokkerend als oranje SIGNAAL (kasverschil, disputes). Alles wat niet klopt is zichtbaar;
    niets boekt stil."""
    controles = list((bron_detail or {}).get("controles") or [])
    # Blok A (16-09): de tegenrekening-controles per betaalwijze reizen als dezelfde check-rijen mee.
    controles += list(((bron_detail or {}).get("tegenzijde") or {}).get("controles") or [])
    extra: list[CheckResultaat] = []
    for c in controles:
        if not isinstance(c, dict) or "naam" not in c:
            continue
        ok = bool(c.get("ok"))
        blokkerend = bool(c.get("blokkerend", True))
        extra.append(
            CheckResultaat(
                naam=f"Bron: {c['naam']}",
                ok=ok or not blokkerend,
                melding=str(c.get("detail") or ""),
                signaal=(not ok) and not blokkerend,
            )
        )
    return CheckRapport(rapport.resultaten + tuple(extra)) if extra else rapport
