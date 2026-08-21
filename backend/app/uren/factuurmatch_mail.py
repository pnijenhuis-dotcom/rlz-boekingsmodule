"""Factuurmatch fase 2 — concept-mail aan de veldwerker bij een match-afwijking (opdracht
Peter 2026-08-21, uitwerking van "afwijzen → terugkoppeling naar de indiener").

Twee stappen, bewust gescheiden (het mailkanaal-patroon `bericht_teksten` uit
app/berichten/herinneringen.py, gesplitst in "bouw tekst" en "verzend"):

1. `bouw_concept_mail` — genereert een CONCEPT (onderwerp + tekst) uit de match-cijfers en de
   eventuele afwijzingsreden. De mens leest, bewerkt en beslist — er wordt hier niets
   verzonden en niets vastgelegd.
2. `verzend_match_mail` — verzendt de (eventueel bewerkte) tekst via het gedeelde SMTP-kanaal
   (app/berichten/mail.py, fail-zichtbaar: niet geconfigureerd/verzendfout = expliciete
   exception) en legt de verzending vast in audit_event + een tijdlijn-notitie zónder
   statusovergang (patroon accordering/herinnering.py). Nooit automatisch — alleen op een
   expliciete mens-klik (endpoint in app/documenten/router.py).

De ontvanger is altijd de veldwerker van de match (ZZP'er of detacheerder) — diens
platform-account-e-mail; een vrij ontvangersveld bestaat bewust niet (geen open mail-relay)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.berichten import mail
from app.db.audit import record_audit_event
from app.db.models import Gebruiker
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentGebeurtenis
from app.uren.models import Factuurmatch
from app.uren.service import NietGevonden, OngeldigeInvoer


@dataclass(frozen=True)
class ConceptMail:
    ontvanger_naam: str | None
    ontvanger_e_mail: str
    onderwerp: str
    tekst: str


def _bedrag(waarde: Decimal | None) -> str:
    return f"€ {waarde:.2f}".replace(".", ",") if waarde is not None else "onbekend"


def _uren(waarde: Decimal | None) -> str:
    return f"{waarde:.2f} uur".replace(".", ",") if waarde is not None else "onbekend"


def _match_en_veldwerker(session, document_id: uuid.UUID) -> tuple[Factuurmatch, Document, Gebruiker]:
    match = session.get(Factuurmatch, document_id)
    if match is None:
        raise NietGevonden("Geen factuurmatch voor dit document")
    document = session.get(Document, document_id)
    if document is None:
        raise NietGevonden(f"Document {document_id} niet gevonden")
    veldwerker = session.get(Gebruiker, match.veldwerker_gebruiker_id)
    if veldwerker is None:
        raise NietGevonden("Veldwerker van de match niet gevonden")
    return match, document, veldwerker


def bouw_concept_mail(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> ConceptMail:
    """Concept-tekst uit de actuele match-cijfers. Werkt voor élke uitkomst (ook een vraag
    over een niet-toetsbare factuur is legitiem), maar de aanleiding is de afwijking — de
    tekst benoemt dan concreet wat niet sluit, plus de weekstaat-uitsplitsing en de
    eventuele afwijzingsreden van het kantoor."""
    from app.documenten import afwijzen

    with scoped_session(administratie_id) as session:
        match, document, veldwerker = _match_en_veldwerker(session, document_id)
        bestandsnaam = document.bestandsnaam
        veldwerker_naam = veldwerker.naam
        veldwerker_e_mail = veldwerker.e_mail
        referentie = None
        from app.documenten.models import Boekvoorstel

        voorstel = session.get(Boekvoorstel, document_id)
        if voorstel is not None:
            referentie = voorstel.referentie
        details = match.details or {}
        staten = details.get("staten") or []
        tarief_ontbreekt_voor = details.get("tarief_ontbreekt_voor") or []
        uitkomst = match.uitkomst
        verschil_bedrag = match.verschil_bedrag
        verschil_uren = match.verschil_uren
        staten_som_uren = match.staten_som_uren
        staten_som_bedrag = match.staten_som_bedrag
        factuur_bedrag = match.factuur_bedrag
        factuur_uren = match.factuur_uren

    open_afwijzing = afwijzen.open_afwijzing_van(administratie_id=administratie_id, document_id=document_id)

    factuurnaam = f"factuur {referentie}" if referentie else f"document {bestandsnaam}"
    regels: list[str] = [
        f"Beste {veldwerker_naam},",
        "",
        f"Bij de controle van uw {factuurnaam} hebben wij deze vergeleken met de goedgekeurde "
        "(getekende) weekstaten. Daarbij zien wij het volgende:",
        "",
        f"- Uren volgens de goedgekeurde weekstaten: {_uren(staten_som_uren)}",
    ]
    if factuur_uren is not None:
        regels.append(f"- Uren volgens de factuur: {_uren(factuur_uren)}")
    if staten_som_bedrag is not None:
        regels.append(f"- Bedrag volgens de weekstaten (uren × afgesproken tarief): {_bedrag(staten_som_bedrag)}")
    if factuur_bedrag is not None:
        regels.append(f"- Bedrag volgens de factuur (excl. btw): {_bedrag(factuur_bedrag)}")
    if verschil_bedrag is not None and abs(verschil_bedrag) > Decimal("0.01"):
        regels.append(f"- Verschil in bedrag: {_bedrag(verschil_bedrag)}")
    if verschil_uren is not None and abs(verschil_uren) > Decimal("0.01"):
        regels.append(f"- Verschil in uren: {_uren(verschil_uren)}")
    if uitkomst == "niet_toetsbaar":
        regels.append(
            "- Wij konden de factuur niet toetsen: er is geen tarief bekend en de factuur vermeldt geen uren."
        )
    if tarief_ontbreekt_voor:
        regels.append(f"- Let op: voor {', '.join(tarief_ontbreekt_voor)} is (nog) geen tarief bekend.")
    if staten:
        regels.append("")
        regels.append("Meegetelde weekstaten:")
        for s in staten:
            week = f"week {s.get('weeknummer')}-{s.get('jaar')}"
            project = s.get("project_naam") or "onbekend project"
            regels.append(f"- {week}, {project}: {_uren(Decimal(s['uren']))}")
    if open_afwijzing is not None:
        regels.append("")
        regels.append(f"De factuur is daarom voorlopig niet verwerkt. Reden: {open_afwijzing.reden}")
    regels += [
        "",
        "Kunt u hiernaar kijken en zo nodig een aangepaste factuur sturen? Neem bij vragen "
        "gerust contact met ons op.",
        "",
        "Met vriendelijke groet,",
        "Administratiekantoor Nijenhuis",
    ]

    return ConceptMail(
        ontvanger_naam=veldwerker_naam,
        ontvanger_e_mail=veldwerker_e_mail,
        onderwerp=f"Vraag over uw {factuurnaam} — aansluiting met de weekstaten",
        tekst="\n".join(regels),
    )


def verzend_match_mail(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    onderwerp: str,
    tekst: str,
) -> str:
    """Verzend de (door de mens gereviewde) mail aan de veldwerker van de match. Raise-t
    fail-zichtbaar bij een leeg onderwerp/lege tekst of een mailkanaal-fout; ná een geslaagde
    verzending worden audit_event + tijdlijn-notitie geschreven. Retourneert het
    ontvangeradres (response/UI)."""
    onderwerp = onderwerp.strip()
    tekst = tekst.strip()
    if not onderwerp or not tekst:
        raise OngeldigeInvoer("Onderwerp en tekst zijn verplicht — een lege mail versturen kan niet")

    with scoped_session(administratie_id) as session:
        _, _, veldwerker = _match_en_veldwerker(session, document_id)
        naar = veldwerker.e_mail

    # Verzenden buiten de DB-transactie (patroon herinnering.py): een SMTP-fout raise-t hier
    # expliciet (503/502 in de router) en er wordt dan óók niets vastgelegd.
    mail.verzend_mail(naar=naar, onderwerp=onderwerp, tekst=tekst)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is not None:
            # Tijdlijn-notitie zonder statusovergang (patroon accordering/herinnering.py).
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={
                        "match_mail_verzonden": {
                            "aan": naar,
                            "onderwerp": onderwerp,
                            "verzonden_op": datetime.now(UTC).isoformat(),
                        }
                    },
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="factuurmatch",
            record_id=document_id,
            actie="match_mail_verzonden",
            correlatie_id=document_id,
            nieuwe_waarde={"aan": naar, "onderwerp": onderwerp},
            administratie_id=administratie_id,
        )
    return naar
