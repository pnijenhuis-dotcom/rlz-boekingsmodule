"""Waarborg-servicelaag (§2d-waarborgroute DEFINITIEF v1.11, blok E 2026-08-10): het
reviewvoorstel per waarborg-document en de harde checks. De berichtvelden zijn BRONGEGEVEN
(niet muteerbaar door de controleur — het bericht is de bron, zelfde principe als
is_creditnota bij verkoop); de éne menselijke keuze is de tegenrekening van het
saldo-0-memoriaal. De balansrekening zelf komt als `balans_gb_code` uit het bericht en wordt —
zelfde §2d-semantiek als de verkoop-GB-codes — per administratie op bestaan gevalideerd
(onbekend/totaalrekening = blokkerend, nooit stil een andere rekening)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport, CheckResultaat
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.service import DocumentNietGevonden
from app.waarborg.models import WaarborgBericht, WaarborgStatus

_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class WaarborgFout(Exception):
    """Domeinfout in de waarborg-servicelaag."""


class GeenWaarborgDocument(WaarborgFout):
    """Het waarborg-voorstel bestaat alleen voor documenten met soort 'waarborg'."""


@dataclass(frozen=True)
class WaarborgVoorstelData:
    document_id: uuid.UUID
    bericht_id: uuid.UUID
    verhuurder_entiteit: str
    contract_referentie: str
    huurder: str
    bedrag: Decimal
    richting: str
    datum: date
    balans_gb_code: str
    # Resolutie van de balans-GB-code in het rekeningschema van deze administratie:
    # 'bekend' | 'onbekend' (blokkerend) — plus de geresolvede ledger.
    balans_ledger_id: uuid.UUID | None
    balans_gb_status: str
    tegenrekening_ledger_id: uuid.UUID | None
    status: str
    rlz_boekstuknummer: str | None


def _laad_waarborg(session: Session, *, document_id: uuid.UUID) -> tuple[Document, WaarborgBericht]:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != DocumentSoort.WAARBORG.value:
        raise GeenWaarborgDocument(f"Document {document_id} is geen waarborg-bericht (soort: {document.soort})")
    bericht = session.get(WaarborgBericht, document_id)
    if bericht is None:
        raise WaarborgFout(
            f"Document {document_id} heeft geen waarborg-berichtregistratie — een verzamelbak-"
            "document zonder geldig bericht kan niet als waarborg geboekt worden"
        )
    return document, bericht


def _resolve_balans_gb(
    session: Session, *, administratie_id: uuid.UUID, code: str
) -> tuple[uuid.UUID | None, str]:
    """Zelfde regels als de verkoop-GB-resolutie (§2d): bestaan per administratie, nooit een
    totaalrekening of een uit de bron verdwenen rekening."""
    rijen = session.scalars(
        select(Grootboekrekening).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.code == code.strip(),
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            Grootboekrekening.is_totaalrekening.is_(False),
        )
    ).all()
    if len(rijen) == 1:
        return rijen[0].ledger_id, "bekend"
    return None, "onbekend"


def _naar_data(
    session: Session, *, administratie_id: uuid.UUID, bericht: WaarborgBericht
) -> WaarborgVoorstelData:
    ledger_id, status = _resolve_balans_gb(
        session, administratie_id=administratie_id, code=bericht.balans_gb_code
    )
    return WaarborgVoorstelData(
        document_id=bericht.document_id,
        bericht_id=bericht.bericht_id,
        verhuurder_entiteit=bericht.verhuurder_entiteit,
        contract_referentie=bericht.contract_referentie,
        huurder=bericht.huurder,
        bedrag=bericht.bedrag,
        richting=bericht.richting,
        datum=bericht.datum,
        balans_gb_code=bericht.balans_gb_code,
        balans_ledger_id=ledger_id,
        balans_gb_status=status,
        tegenrekening_ledger_id=bericht.tegenrekening_ledger_id,
        status=bericht.status,
        rlz_boekstuknummer=bericht.rlz_boekstuknummer,
    )


def haal_waarborg_voorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> WaarborgVoorstelData:
    with scoped_session(administratie_id) as session:
        _, bericht = _laad_waarborg(session, document_id=document_id)
        return _naar_data(session, administratie_id=administratie_id, bericht=bericht)


def sla_tegenrekening_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    tegenrekening_ledger_id: uuid.UUID | None,
) -> WaarborgVoorstelData:
    """De énige muteerbare keuze: de tegenrekening. Alle berichtvelden zijn brongegeven en
    blijven onaantastbaar (geen parameters — er valt niets anders op te slaan)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document, bericht = _laad_waarborg(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN or bericht.status == WaarborgStatus.GEBOEKT.value:
            raise WaarborgFout(f"Waarborg {document_id} is al geboekt of bevroren — niet meer te wijzigen")
        oude_waarde = (
            {"tegenrekening_ledger_id": str(bericht.tegenrekening_ledger_id)}
            if bericht.tegenrekening_ledger_id
            else None
        )
        bericht.tegenrekening_ledger_id = tegenrekening_ledger_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="waarborg_bericht",
            record_id=document_id,
            actie="waarborg_tegenrekening_gekozen",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oude_waarde,
            nieuwe_waarde={
                "tegenrekening_ledger_id": str(tegenrekening_ledger_id) if tegenrekening_ledger_id else None
            },
            administratie_id=administratie_id,
        )
    return haal_waarborg_voorstel_op(administratie_id=administratie_id, document_id=document_id)


def memoriaal_lines(voorstel: WaarborgVoorstelData) -> list[dict]:
    """Het saldo-0-memoriaal (twee regels, per constructie sluitend): bij `ontvangst` staat de
    waarborg-balansrekening aan de CREDITZIJDE (het saldo presenteert zich als verplichting —
    inrichtingskeuze Peter 2026-08-09, §6.4/v1.11) en de tegenrekening debet; `terugbetaling`
    is exact het spiegelbeeld."""
    assert voorstel.balans_ledger_id is not None and voorstel.tegenrekening_ledger_id is not None
    omschrijving = (
        f"Waarborg {voorstel.richting} {voorstel.contract_referentie} — {voorstel.huurder}"
    )
    bedrag = float(voorstel.bedrag)
    waarborg_kant = {
        "Account": {"id": str(voorstel.balans_ledger_id)},
        "Description": omschrijving,
    }
    tegen_kant = {
        "Account": {"id": str(voorstel.tegenrekening_ledger_id)},
        "Description": omschrijving,
    }
    if voorstel.richting == "ontvangst":
        waarborg_kant.update({"CreditOrDebit": 2, "CreditAmount": bedrag})
        tegen_kant.update({"CreditOrDebit": 1, "DebitAmount": bedrag})
    else:
        waarborg_kant.update({"CreditOrDebit": 1, "DebitAmount": bedrag})
        tegen_kant.update({"CreditOrDebit": 2, "CreditAmount": bedrag})
    return [waarborg_kant, tegen_kant]


def waarborg_referentie(voorstel: WaarborgVoorstelData) -> str:
    """Deterministische memoriaal-Reference (herleidbaarheid + RLZ-side duplicaatsignaal;
    RLZ kapt Reference op 30 tekens — het bericht_id-blok vooraan is het onderscheidende deel)."""
    return f"WBG-{str(voorstel.bericht_id)[:8]}-{voorstel.contract_referentie}"[:30]


def voer_waarborg_checks_uit(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    rlz_memoriaal_hits: int | None = 0,
) -> CheckRapport:
    """Harde checks — zelfde conventies als inkoop/omzet/verkoop (ok=False blokkeert, alle
    checks draaien altijd). `rlz_memoriaal_hits` is de uitkomst van de RLZ-side
    Reference-duplicaatquery (None = kon niet uitgevoerd worden → fail-closed blokkerend);
    de boekmotor voert die query zelf uit, het checks-endpoint geeft 0 door (lokale checks —
    de motor herdraait alles mét de live query vóór elke echte boeking)."""
    voorstel = haal_waarborg_voorstel_op(administratie_id=administratie_id, document_id=document_id)

    ontbrekend: list[str] = []
    if voorstel.tegenrekening_ledger_id is None:
        ontbrekend.append("tegenrekening (de rekening waartegen het memoriaal sluit — kies er één)")
    verplicht = CheckResultaat(
        naam="verplichte_velden",
        ok=not ontbrekend,
        melding="Alle verplichte velden zijn gevuld" if not ontbrekend else "Ontbrekend: " + "; ".join(ontbrekend),
    )

    gb_bekend = CheckResultaat(
        naam="balans_gb_bekend",
        ok=voorstel.balans_gb_status == "bekend",
        melding=(
            f"Balansrekening {voorstel.balans_gb_code} gevonden in het rekeningschema"
            if voorstel.balans_gb_status == "bekend"
            else f"Balansrekening {voorstel.balans_gb_code} uit het bericht bestaat niet (of is een "
            "totaalrekening) in het rekeningschema van deze administratie — blokkerend (§2d)"
        ),
    )

    bedrag_ok = voorstel.bedrag > 0
    bedrag = CheckResultaat(
        naam="bedrag_positief",
        ok=bedrag_ok,
        melding=f"Waarborgbedrag € {voorstel.bedrag}" if bedrag_ok else "Waarborgbedrag moet positief zijn",
    )

    # Saldo-0 per constructie (twee regels, zelfde bedrag) — hier expliciet hergetoetst met de
    # bestaande omzet-check zodra de regels construeerbaar zijn (fail-closed als dat niet kan).
    if voorstel.balans_ledger_id is not None and voorstel.tegenrekening_ledger_id is not None:
        from app.omzet.checks import MemoriaalRegel, check_memoriaal_saldo_0

        lines = memoriaal_lines(voorstel)
        saldo = check_memoriaal_saldo_0(
            regels=[
                MemoriaalRegel(
                    debet_bedrag=Decimal(str(line.get("DebitAmount", 0))),
                    credit_bedrag=Decimal(str(line.get("CreditAmount", 0))),
                )
                for line in lines
            ]
        )
    else:
        saldo = CheckResultaat(
            naam="memoriaal_saldo_0",
            ok=False,
            melding="Memoriaal nog niet construeerbaar (balansrekening of tegenrekening ontbreekt)",
        )

    with scoped_session(administratie_id) as session:
        boeking_bestaat = session.get(WaarborgBericht, document_id)
        al_geboekt = boeking_bestaat is not None and boeking_bestaat.status == WaarborgStatus.GEBOEKT.value
    duplicaat_meldingen: list[str] = []
    if al_geboekt:
        duplicaat_meldingen.append("dit bericht is al geboekt (idempotent op bericht_id)")
    if rlz_memoriaal_hits is None:
        duplicaat_meldingen.append("RLZ-duplicaatcheck kon niet uitgevoerd worden (fail-closed)")
    elif rlz_memoriaal_hits > 0:
        duplicaat_meldingen.append(
            f"in Reeleezee staan al {rlz_memoriaal_hits} memoriaal/-alen met deze waarborg-referentie"
        )
    duplicaat = CheckResultaat(
        naam="duplicaat",
        ok=not duplicaat_meldingen,
        melding="Geen duplicaat gevonden" if not duplicaat_meldingen else "; ".join(duplicaat_meldingen),
    )

    return CheckRapport(resultaten=(verplicht, gb_bekend, bedrag, saldo, duplicaat))
