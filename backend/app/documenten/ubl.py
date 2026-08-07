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
    voor niet-UBL-documenten (PDF's zonder gestructureerde data).

    De intake-velden (migratie 0028): `klant_naam` = AccountingCustomerParty (de tenaamstelling —
    leidend voor de administratie-toewijzing van een inkoopfactuur),
    `additional_document_reference_ids` = de cbc:ID's van cac:AdditionalDocumentReference (§2d:
    de vaste markering VASTLY-VERKOOP routeert naar de omzetkant), `referenties` =
    BuyerReference + PaymentID's (het VGB-prefixfilter, koppelcontract §2 punt 2)."""

    factuurnummer: str | None
    factuurdatum: str | None
    valuta: str | None
    totaal_excl: str | None
    totaal_incl: str | None
    leverancier_naam: str | None
    regelaantal: int
    klant_naam: str | None = None
    additional_document_reference_ids: tuple[str, ...] = ()
    referenties: tuple[str, ...] = ()

    def als_dict(self) -> dict[str, str | int | None]:
        d = asdict(self)
        d["additional_document_reference_ids"] = list(self.additional_document_reference_ids)
        d["referenties"] = list(self.referenties)
        return d


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
    klant_naam = _tekst("cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName")
    regels = root.findall("cac:InvoiceLine", _NS)

    adr_ids = tuple(
        el.text.strip()
        for el in root.findall("cac:AdditionalDocumentReference/cbc:ID", _NS)
        if el.text and el.text.strip()
    )
    referenties = tuple(
        el.text.strip()
        for pad in ("cbc:BuyerReference", "cac:PaymentMeans/cbc:PaymentID")
        for el in root.findall(pad, _NS)
        if el.text and el.text.strip()
    )

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
        klant_naam=klant_naam,
        additional_document_reference_ids=adr_ids,
        referenties=referenties,
    )


# §2d-markering (koppelcontract, vaste constante — nooit een prefix-match).
VASTLY_VERKOOP_MARKERING = "VASTLY-VERKOOP"
# Koppelcontract §2 punt 2: documenten van de vastgoedmodule dragen dit Reference-prefix — al
# door vastgoed geboekt, nooit als werkvoorraad tonen.
VGB_PREFIX = "VGB-"


def is_vastly_verkoop(voorstel: UblVeldvoorstel) -> bool:
    """§2d-routeringsregel: exact `VASTLY-VERKOOP` in cac:AdditionalDocumentReference/cbc:ID."""
    return VASTLY_VERKOOP_MARKERING in voorstel.additional_document_reference_ids


def is_vgb_document(voorstel: UblVeldvoorstel) -> bool:
    """VGB-prefixfilter (koppelcontract §2 punt 2): Reference/betalingskenmerk (of het
    factuurnummer zelf) begint met `VGB-` → al door vastgoed geboekt, negeren als werkvoorraad."""
    kandidaten = [*voorstel.referenties]
    if voorstel.factuurnummer:
        kandidaten.append(voorstel.factuurnummer)
    return any(ref.startswith(VGB_PREFIX) for ref in kandidaten)


def nlcius_kernvelden_ontbrekend(voorstel: UblVeldvoorstel) -> list[str]:
    """Minimale NLCIUS-kernveldencheck voor de §2d-failsafe: een Vastly-UBL zónder deze velden
    telt als NLCIUS-invalide → verzamelbak, nooit stil doorrouteren. Bewust een kernvelden-proxy,
    geen volledige schematron-validatie (genoteerd vervolg — het contract legt de échte
    NLCIUS-borging bij de genererende kant, §2d punt 3)."""
    ontbrekend = []
    if not voorstel.factuurnummer:
        ontbrekend.append("factuurnummer (cbc:ID)")
    if not voorstel.factuurdatum:
        ontbrekend.append("factuurdatum (cbc:IssueDate)")
    if not voorstel.leverancier_naam:
        ontbrekend.append("leverancier (AccountingSupplierParty)")
    if not voorstel.klant_naam:
        ontbrekend.append("afnemer (AccountingCustomerParty)")
    if not voorstel.totaal_incl:
        ontbrekend.append("totaalbedrag (PayableAmount)")
    if voorstel.regelaantal == 0:
        ontbrekend.append("factuurregels (InvoiceLine)")
    return ontbrekend
