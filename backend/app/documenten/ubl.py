from __future__ import annotations

from dataclasses import asdict, dataclass, field
from xml.etree import ElementTree as ET

_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# Root-namespaces van de twee UBL 2.1-documenttypen die de intake kent. Een CreditNote (381,
# koppelcontract §2d-creditnota's v1.11) is een APART documenttype met een eigen root en
# CreditNoteLine-regels — géén Invoice met TypeCode 381.
_INVOICE_ROOT = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
_CREDITNOTE_ROOT = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"


class GeenGeldigeUbl(Exception):
    """De inhoud is geen (herkenbare) UBL-factuur-XML."""


@dataclass(frozen=True)
class UblRegel:
    """Eén factuurregel, deterministisch uit de UBL gelezen (code voor cijfers — geen AI).
    `gb_code` = cbc:AccountingCost (EN 16931 BT-133, koppelcontract §2d-GB-uitbreiding v1.10);
    ontbreekt de regelwaarde, dan geldt het document-niveau BT-19 als fallback (de parser vult
    dat hier al in). `btw_percentage`/`btw_categorie` komen uit cac:ClassifiedTaxCategory —
    de btw-bedragsplitsing zelf gebeurt in code op basis van LineExtensionAmount (netto)."""

    volgnummer: int
    omschrijving: str | None
    netto_bedrag: str | None
    btw_percentage: str | None
    btw_categorie: str | None
    gb_code: str | None
    # Blok D 28-08 (voorraad-aansluiting): hoeveelheid (BT-129, `unitCode` = eenheid) en prijs per
    # eenheid (BT-146) — deterministisch uit de UBL, voedt de uitstroom-feitenlaag.
    aantal: str | None = None
    eenheid: str | None = None
    prijs: str | None = None

    def als_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


@dataclass(frozen=True)
class UblVeldvoorstel:
    """Deterministisch geparste velden — een voorstel, geen boeking. Code voor cijfers: dit is
    pure XML-veldextractie, geen AI; de echte AI-extractiestap (fase-vervolg) haakt hierachter in
    voor niet-UBL-documenten (PDF's zonder gestructureerde data).

    De intake-velden (migratie 0028): `klant_naam` = AccountingCustomerParty (de tenaamstelling —
    leidend voor de administratie-toewijzing van een inkoopfactuur),
    `additional_document_reference_ids` = de cbc:ID's van cac:AdditionalDocumentReference (§2d:
    de vaste markering VASTLY-VERKOOP routeert naar de omzetkant), `referenties` =
    BuyerReference + PaymentID's (het VGB-prefixfilter, koppelcontract §2 punt 2).

    Verkoopfactuur-boekpad (§2d v1.10/v1.11): `ubl_regels` draagt per regel netto/btw%/GB-code
    (bewust een eigen sleutel — `regels` is in het veldvoorstel de AI-regelconventie van de
    inkoop-/rapportextractie en heeft een andere veldvorm),
    `is_creditnota` + `gecrediteerde_factuurnummers` de CreditNote-381-herkenning
    (BillingReference = koppelsleutel naar de eerder geboekte factuur)."""

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
    totaal_btw: str | None = None
    is_creditnota: bool = False
    gecrediteerde_factuurnummers: tuple[str, ...] = ()
    ubl_regels: tuple[dict, ...] = field(default=())

    def als_dict(self) -> dict:
        d = asdict(self)
        d["additional_document_reference_ids"] = list(self.additional_document_reference_ids)
        d["referenties"] = list(self.referenties)
        d["gecrediteerde_factuurnummers"] = list(self.gecrediteerde_factuurnummers)
        d["ubl_regels"] = list(self.ubl_regels)
        return d


def _element_tekst(element: ET.Element, pad: str) -> str | None:
    el = element.find(pad, _NS)
    return el.text.strip() if el is not None and el.text else None


def _parse_regels(root: ET.Element, *, regel_element: str, document_gb_code: str | None) -> tuple[dict, ...]:
    regels: list[dict] = []
    for i, lijn in enumerate(root.findall(regel_element, _NS), start=1):
        # Invoice-regels dragen cbc:InvoicedQuantity, CreditNote-regels cbc:CreditedQuantity (BT-129).
        hoeveelheid_el = lijn.find("cbc:InvoicedQuantity", _NS)
        if hoeveelheid_el is None:
            hoeveelheid_el = lijn.find("cbc:CreditedQuantity", _NS)
        aantal = hoeveelheid_el.text.strip() if hoeveelheid_el is not None and hoeveelheid_el.text else None
        eenheid = hoeveelheid_el.get("unitCode") if hoeveelheid_el is not None else None
        regels.append(
            UblRegel(
                volgnummer=i,
                omschrijving=_element_tekst(lijn, "cac:Item/cbc:Name")
                or _element_tekst(lijn, "cac:Item/cbc:Description"),
                netto_bedrag=_element_tekst(lijn, "cbc:LineExtensionAmount"),
                btw_percentage=_element_tekst(lijn, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
                btw_categorie=_element_tekst(lijn, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
                # BT-133 per regel; BT-19 (documentniveau) is de contractuele fallback wanneer
                # alle regels dezelfde code delen (§2d-GB-uitbreiding v1.10).
                gb_code=_element_tekst(lijn, "cbc:AccountingCost") or document_gb_code,
                aantal=aantal,
                eenheid=eenheid,
                prijs=_element_tekst(lijn, "cac:Price/cbc:PriceAmount"),
            ).als_dict()
        )
    return tuple(regels)


def parseer_ubl_factuur(inhoud: bytes) -> UblVeldvoorstel:
    """Uitsluitend well-formed XML zonder DOCTYPE (voorkomt entity-expansion-aanvallen — UBL-
    facturen hebben legitiem nooit een DTD nodig; dit vervangt geen volwaardige XML-hardening
    zoals defusedxml, maar is voldoende voor deze stub-parser zonder een nieuwe dependency).

    Parseert zowel UBL Invoice als UBL CreditNote (381) — de velden zijn gelijkvormig, alleen
    de regel-elementen verschillen (InvoiceLine vs CreditNoteLine) en een CreditNote draagt de
    BillingReference-herleiding naar de oorspronkelijke factuur."""
    if b"<!DOCTYPE" in inhoud[:4096].upper():
        raise GeenGeldigeUbl("XML met DOCTYPE wordt geweigerd (entity-expansion-risico)")
    try:
        root = ET.fromstring(inhoud)
    except ET.ParseError as exc:
        raise GeenGeldigeUbl(f"Geen geldige XML: {exc}") from exc

    is_creditnota = root.tag == _CREDITNOTE_ROOT

    def _tekst(pad: str) -> str | None:
        el = root.find(pad, _NS)
        return el.text.strip() if el is not None and el.text else None

    factuurnummer = _tekst("cbc:ID")
    factuurdatum = _tekst("cbc:IssueDate")
    valuta = _tekst("cbc:DocumentCurrencyCode")
    totaal_excl = _tekst("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")
    totaal_incl = _tekst("cac:LegalMonetaryTotal/cbc:PayableAmount")
    totaal_btw = _tekst("cac:TaxTotal/cbc:TaxAmount")
    leverancier_naam = _tekst("cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName")
    klant_naam = _tekst("cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName")
    regel_element = "cac:CreditNoteLine" if is_creditnota else "cac:InvoiceLine"
    regels = _parse_regels(root, regel_element=regel_element, document_gb_code=_tekst("cbc:AccountingCost"))

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
    gecrediteerd = tuple(
        el.text.strip()
        for el in root.findall("cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID", _NS)
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
        totaal_btw=totaal_btw,
        is_creditnota=is_creditnota,
        gecrediteerde_factuurnummers=gecrediteerd,
        ubl_regels=regels,
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
    NLCIUS-borging bij de genererende kant, §2d punt 3). Voor een CreditNote (381) is de
    BillingReference-herleiding een kernveld: zonder gecrediteerde factuur is er geen
    tegenboeking mogelijk (§2d-creditnota's v1.11)."""
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
        regelnaam = "CreditNoteLine" if voorstel.is_creditnota else "InvoiceLine"
        ontbrekend.append(f"factuurregels ({regelnaam})")
    if voorstel.is_creditnota and not voorstel.gecrediteerde_factuurnummers:
        ontbrekend.append("gecrediteerde factuur (cac:BillingReference)")
    return ontbrekend
