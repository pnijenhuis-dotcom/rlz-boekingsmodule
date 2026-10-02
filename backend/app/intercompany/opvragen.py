"""Handeling "Factuur opvragen bij ‹BV›" op een `ic_inkoop_ontbreekt`-bevinding (run D 02-10 blok D, Peter 02-10).

De verkopende eigen BV heeft de factuur wél (nummer/datum/bedrag staan in haar verkoopboek), de ontvangende BV heeft 'm
nooit aangeleverd gekregen (rapport 28-09: 36 Nederland-facturen, € 84.376,56, "nergens in de module"). De handeling
maakt een MAILCONCEPT aan de boekhouding van de verkopende BV met het verzoek de PDF/UBL naar onze boekhoudmail (het
intake-adres) te sturen — zodat de factuur via de gewone intake binnenkomt en geboekt wordt. Het concept wordt NOOIT
automatisch verzonden: de mens kopieert/opent 'm (mailto) en verstuurt zelf. Geadresseerde: de module kent geen
e-mailadres per administratie; het concept draagt daarom de naam van de BV en laat het adres aan de mens (zichtbaar in
het concept als "aan: ‹vul het adres van de boekhouding van ‹BV› in›"). Audit `ic_factuur_opgevraagd_concept` op de
ontvangende administratie (de scope van de bevinding), mét bevinding-id, nummer, bedrag en datum."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import quote

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.intercompany.factuurmatch import SOORT_INKOOP_ONTBREEKT
from app.reconciliatie.models import ReconciliatieBevinding

AUDIT_ACTIE = "ic_factuur_opgevraagd_concept"
_MODULE = "boekhouding"
ADRES_PLAATSHOUDER = "‹vul het adres van de boekhouding van {bv} in›"


class OpvragenNietMogelijk(Exception):
    """Bevinding is geen `ic_inkoop_ontbreekt` (of mist de velden) — 409 in de router."""


@dataclass(frozen=True)
class MailConcept:
    bevinding_id: uuid.UUID
    administratie_id: uuid.UUID
    verkoper_naam: str
    ontvanger_naam: str
    nummer: str | None
    datum: str | None
    bedrag: str | None
    aan: str | None  # None = adres onbekend (plaatshouder in `aan_tekst`)
    aan_tekst: str
    onderwerp: str
    tekst: str
    mailto: str
    intake_adres: str | None


def _euro(bedrag: str | None) -> str:
    if not bedrag:
        return "een onbekend bedrag"
    try:
        waarde = float(bedrag)
    except ValueError:
        return bedrag
    return "€ " + f"{waarde:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _datum_nl(iso: str | None) -> str:
    if not iso or len(iso) < 10:
        return "onbekende datum"
    j, m, d = iso[:4], iso[5:7], iso[8:10]
    return f"{d}-{m}-{j}"


def bouw_concept(
    *,
    bevinding_id: uuid.UUID,
    administratie_id: uuid.UUID,
    detail: dict,
    intake_adres: str | None,
) -> MailConcept:
    """PUUR: het concept uit het detail van de bevinding (`verkoper_naam`, `ontvanger_naam`, `nummer`, `datum`,
    `bedrag_verkoop`). Geen e-mailadres bekend → plaatshouder, `mailto` zonder adres (de mens vult 'm in)."""
    verkoper = str(detail.get("verkoper_naam") or "de verkopende administratie")
    ontvanger = str(detail.get("ontvanger_naam") or "de ontvangende administratie")
    nummer = detail.get("nummer")
    datum = detail.get("datum")
    bedrag = detail.get("bedrag_verkoop")
    aan = None
    aan_tekst = ADRES_PLAATSHOUDER.format(bv=verkoper)
    onderwerp = f"Factuur {nummer or '(nummer onbekend)'} aan {ontvanger} — graag de PDF/UBL naar onze boekhoudmail"
    waarheen = f"naar {intake_adres}" if intake_adres else "naar onze boekhoudmail (het intake-adres van de module)"
    tekst = (
        f"Beste administratie van {verkoper},\n\n"
        f"In jullie verkoopboek staat factuur {nummer or '(nummer onbekend)'} van {_datum_nl(datum)} aan {ontvanger} "
        f"voor {_euro(bedrag)}. Bij {ontvanger} is die factuur niet aangekomen: er staat geen inkoopfactuur met dat "
        f"nummer en er is ook niets onderweg in de boekhoudmodule.\n\n"
        f"Willen jullie de factuur (PDF en/of UBL) {waarheen} sturen? Dan komt 'm via de gewone intake binnen en "
        f"wordt 'm bij {ontvanger} geboekt.\n\n"
        f"Met vriendelijke groet,\nAdministratiekantoor Nijenhuis"
    )
    mailto = f"mailto:?subject={quote(onderwerp)}&body={quote(tekst)}"
    return MailConcept(
        bevinding_id=bevinding_id,
        administratie_id=administratie_id,
        verkoper_naam=verkoper,
        ontvanger_naam=ontvanger,
        nummer=str(nummer) if nummer is not None else None,
        datum=str(datum) if datum else None,
        bedrag=str(bedrag) if bedrag is not None else None,
        aan=aan,
        aan_tekst=aan_tekst,
        onderwerp=onderwerp,
        tekst=tekst,
        mailto=mailto,
        intake_adres=intake_adres,
    )


def factuur_opvragen_concept(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, bevinding_id: uuid.UUID
) -> MailConcept:
    """Leest de bevinding in de scope van de ontvangende administratie (RLS), toetst de soort, bouwt het concept en
    legt één audit vast. Buiten scope/onbekend = `LookupError` (404), verkeerde soort = `OpvragenNietMogelijk` (409)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(ReconciliatieBevinding, bevinding_id)
        if rij is None or rij.administratie_id != administratie_id:
            raise LookupError("Bevinding niet gevonden in deze administratie")
        detail = dict(rij.detail or {})
        if rij.blok != "intercompany" or detail.get("afwijking_soort") != SOORT_INKOOP_ONTBREEKT:
            raise OpvragenNietMogelijk(
                "Alleen op een bevinding 'onderlinge factuur ontbreekt bij ontvanger' (ic_inkoop_ontbreekt) is een "
                "factuur op te vragen"
            )
        concept = bouw_concept(
            bevinding_id=bevinding_id,
            administratie_id=administratie_id,
            detail=detail,
            intake_adres=settings.intake_postvak_adres,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="reconciliatie_bevinding",
            record_id=bevinding_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "verkoper_naam": concept.verkoper_naam,
                "ontvanger_naam": concept.ontvanger_naam,
                "nummer": concept.nummer,
                "datum": concept.datum,
                "bedrag": concept.bedrag,
                "verzonden": False,
            },
            administratie_id=administratie_id,
        )
        return concept


__all__ = ["AUDIT_ACTIE", "MailConcept", "OpvragenNietMogelijk", "bouw_concept", "factuur_opvragen_concept"]
