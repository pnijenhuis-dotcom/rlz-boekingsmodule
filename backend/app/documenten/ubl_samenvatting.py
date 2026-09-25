"""UBL-samenvattingskaart voor het controlescherm — FV-01 (feedbackrun A 25-09, casus Universal Nederland
RLZ-2080142898 → Universal Steigerbouw).

Een UBL-document ZONDER beeld (geen bron-PDF, geen ingesloten PDF — `documenten/beeld.py` stap 3: het hoofdbestand
zelf) werd tot 25-09 in het bijlage-paneel als RUWE XML getoond (`<pre class="xml-bron">`). Dat is voor een mens
"een blok code". Sinds 25-09 rendert het paneel deze deterministische samenvatting (zelfde parser als de intake:
`documenten/ubl.py`, géén AI) en staat de XML-bron alleen nog achter een tekstknop "XML-bron tonen".

Lees-only: geen DB-schrijfactie, geen RLZ-call. Een niet-parsebare XML is géén fout van de route: de kaart zegt dan
"niet leesbaar" mét de reden (`GeenGeldigeUbl`-melding), zodat scherm en tijdlijn (`ubl_parse_fout`) hetzelfde
zeggen."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import GeenGeldigeUbl, UblVeldvoorstel, parseer_ubl_factuur, ubl_onvolledig_reden
from app.documenten.ubl_voorstel import regel_btw_bedrag


class GeenXmlDocument(Exception):
    """Het hoofdbestand van het document is geen .xml — de kaart is niet van toepassing (422)."""


@dataclass(frozen=True)
class SamenvattingRegel:
    volgnummer: int
    omschrijving: str | None
    aantal: str | None
    eenheid: str | None
    netto_bedrag: str | None
    btw_percentage: str | None
    btw_bedrag: str | None
    soort: str | None


@dataclass(frozen=True)
class UblSamenvattingDocument:
    leesbaar: bool
    reden: str | None = None
    bestandsnaam: str | None = None
    is_creditnota: bool = False
    leverancier: str | None = None
    afnemer: str | None = None
    factuurnummer: str | None = None
    factuurdatum: str | None = None
    vervaldatum: str | None = None
    valuta: str | None = None
    totaal_excl: str | None = None
    totaal_btw: str | None = None
    totaal_incl: str | None = None
    kvk_nummer: str | None = None
    btw_nummer: str | None = None
    iban: str | None = None
    leverancier_adres: str | None = None
    betalingskenmerk: str | None = None
    note: str | None = None
    project_tekst: str | None = None
    regelaantal: int = 0
    regels: list[SamenvattingRegel] = field(default_factory=list)
    onvolledig: str | None = None


def samenvatting_uit_ubl(inhoud: bytes, *, bestandsnaam: str | None = None) -> UblSamenvattingDocument:
    """Pure functie (bytes → kaart) — de route én de ketentest gebruiken 'm; nooit een exception voor een kapotte
    XML."""
    try:
        v: UblVeldvoorstel = parseer_ubl_factuur(inhoud)
    except GeenGeldigeUbl as exc:
        return UblSamenvattingDocument(leesbaar=False, reden=str(exc), bestandsnaam=bestandsnaam)
    regels = [
        SamenvattingRegel(
            volgnummer=int(r.get("volgnummer") or i),
            omschrijving=r.get("omschrijving"),
            aantal=r.get("aantal"),
            eenheid=r.get("eenheid"),
            netto_bedrag=r.get("netto_bedrag"),
            btw_percentage=r.get("btw_percentage"),
            btw_bedrag=(str(b) if (b := regel_btw_bedrag(r)) is not None else None),
            soort=r.get("soort"),
        )
        for i, r in enumerate(v.ubl_regels, start=1)
    ]
    return UblSamenvattingDocument(
        leesbaar=True,
        bestandsnaam=bestandsnaam,
        is_creditnota=v.is_creditnota,
        leverancier=v.leverancier_naam,
        afnemer=v.klant_naam,
        factuurnummer=v.factuurnummer,
        factuurdatum=v.factuurdatum,
        vervaldatum=v.vervaldatum,
        valuta=v.valuta,
        totaal_excl=v.totaal_excl,
        totaal_btw=v.totaal_btw,
        totaal_incl=v.totaal_incl,
        kvk_nummer=v.kvk_nummer,
        btw_nummer=v.btw_nummer,
        iban=v.iban,
        leverancier_adres=v.leverancier_adres,
        betalingskenmerk=v.betalingskenmerk,
        note=v.note,
        project_tekst=v.project_tekst,
        regelaantal=v.regelaantal,
        regels=regels,
        onvolledig=ubl_onvolledig_reden(v),
    )


def samenvatting_voor_document(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag: DocumentOpslag | None = None
) -> UblSamenvattingDocument:
    """De kaart voor één document in de administratie-scope (RLS via `haal_bijlage_op`, vorm=data = de UBL zelf)."""
    from app.documenten import service  # lokaal: service importeert deze module niet, maar houdt de graaf klein

    inhoud, bestandsnaam, _ = service.haal_bijlage_op(
        administratie_id=administratie_id, document_id=document_id, opslag=opslag, vorm="data"
    )
    if not bestandsnaam.lower().endswith(".xml"):
        raise GeenXmlDocument(f"{bestandsnaam} is geen XML-document")
    return samenvatting_uit_ubl(inhoud, bestandsnaam=bestandsnaam)
