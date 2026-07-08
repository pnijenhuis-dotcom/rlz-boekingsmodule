from __future__ import annotations

from dataclasses import asdict, dataclass
from xml.etree import ElementTree as ET

_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


class GeenGeldigeUbl(Exception):
    """De inhoud is geen (herkenbare) UBL-factuur-XML."""


@dataclass(frozen=True)
class UblVeldvoorstel:
    """Deterministisch geparste velden — een voorstel, geen boeking. Code voor cijfers: dit is
    pure XML-veldextractie, geen AI; de echte AI-extractiestap (fase-vervolg) haakt hierachter in
    voor niet-UBL-documenten (PDF's zonder gestructureerde data)."""

    factuurnummer: str | None
    factuurdatum: str | None
    valuta: str | None
    totaal_excl: str | None
    totaal_incl: str | None
    leverancier_naam: str | None
    regelaantal: int

    def als_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def parseer_ubl_factuur(inhoud: bytes) -> UblVeldvoorstel:
    """Uitsluitend well-formed XML zonder DOCTYPE (voorkomt entity-expansion-aanvallen — UBL-
    facturen hebben legitiem nooit een DTD nodig; dit vervangt geen volwaardige XML-hardening
    zoals defusedxml, maar is voldoende voor deze stub-parser zonder een nieuwe dependency)."""
    if b"<!DOCTYPE" in inhoud[:4096].upper():
        raise GeenGeldigeUbl("XML met DOCTYPE wordt geweigerd (entity-expansion-risico)")
    try:
        root = ET.fromstring(inhoud)
    except ET.ParseError as exc:
        raise GeenGeldigeUbl(f"Geen geldige XML: {exc}") from exc

    def _tekst(pad: str) -> str | None:
        el = root.find(pad, _NS)
        return el.text.strip() if el is not None and el.text else None

    factuurnummer = _tekst("cbc:ID")
    factuurdatum = _tekst("cbc:IssueDate")
    valuta = _tekst("cbc:DocumentCurrencyCode")
    totaal_excl = _tekst("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")
    totaal_incl = _tekst("cac:LegalMonetaryTotal/cbc:PayableAmount")
    leverancier_naam = _tekst("cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName")
    regels = root.findall("cac:InvoiceLine", _NS)

    if factuurnummer is None and totaal_incl is None:
        raise GeenGeldigeUbl("Geen UBL-Invoice-velden gevonden (ID/PayableAmount ontbreken)")

    return UblVeldvoorstel(
        factuurnummer=factuurnummer,
        factuurdatum=factuurdatum,
        valuta=valuta,
        totaal_excl=totaal_excl,
        totaal_incl=totaal_incl,
        leverancier_naam=leverancier_naam,
        regelaantal=len(regels),
    )
