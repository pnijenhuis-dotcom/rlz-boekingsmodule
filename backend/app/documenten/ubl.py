from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer
from app.extractie.iban import is_geldig_iban, normaliseer_iban

#: `bron` in het veldvoorstel-dict van een UBL (blok 3 herstelrun 08-09): de frontend en de prefill herkennen
#: hieraan een DETERMINISTISCH voorstel (naast "ai" en "template"). Oudere UBL-voorstellen dragen geen `bron`
#: maar wél `ubl_regels` — `is_ubl_veldvoorstel` kent beide vormen.
BRON_UBL = "ubl"

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
    # Bugfix 04-09 (kortingsregels): "korting" / "toeslag" voor een regel die uit een document-niveau
    # cac:AllowanceCharge komt (BG-20/BG-21); None = gewone factuurregel (InvoiceLine/CreditNoteLine).
    soort: str | None = None

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
    # Blok 3 herstelrun "Basis eerst" 08-09 (casus BDO 6088744): de crediteur-identiteit en de betaalgegevens
    # komen RECHTSTREEKS uit de XML — nooit via AI, nooit leeg als de UBL ze draagt. Zelfde sleutelnamen als het
    # AI-veldvoorstel (`iban`, `btw_nummer`, `kvk_nummer`, `vervaldatum`, `betalingskenmerk`) zodat élke afnemer
    # (crediteur-match, crediteur-kenmerk-geheugen, IBAN-wissel-check, "Nieuwe crediteur in RLZ") één leespad heeft.
    vervaldatum: str | None = None
    kvk_nummer: str | None = None
    btw_nummer: str | None = None
    btw_nummer_geverifieerd: bool | None = None
    iban: str | None = None
    leverancier_adres: str | None = None
    betalingskenmerk: str | None = None

    def als_dict(self) -> dict:
        d = asdict(self)
        d["bron"] = BRON_UBL
        d["additional_document_reference_ids"] = list(self.additional_document_reference_ids)
        d["referenties"] = list(self.referenties)
        d["gecrediteerde_factuurnummers"] = list(self.gecrediteerde_factuurnummers)
        d["ubl_regels"] = list(self.ubl_regels)
        return d


def _element_tekst(element: ET.Element, pad: str) -> str | None:
    el = element.find(pad, _NS)
    return el.text.strip() if el is not None and el.text else None


# Partijnaam in volgorde van voorkeur. EN 16931/NLCIUS zet de officiële naam in
# cac:PartyLegalEntity/cbc:RegistrationName (BT-27/BT-44); oudere SI-UBL-1.x-exporten — waaronder
# RLZ's eigen UBL-export (parser-gap 02-09: 97 IC-facturen Universal Nederland → Universal
# Steigerbouw stonden zonder tenaamstelling in de verzamelbak) — dragen uitsluitend
# cac:PartyName/cbc:Name (BT-28/BT-45) en een PartyLegalEntity mét alleen een KvK-CompanyID.
_PARTIJNAAM_PADEN = (
    "cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
    "cac:Party/cac:PartyName/cbc:Name",
)


def _partijnaam(root: ET.Element, partij: str) -> str | None:
    """Naam van AccountingSupplierParty/AccountingCustomerParty: RegistrationName wint, anders
    PartyName/Name (SI-UBL 1.x, RLZ-export). Contact/Name is bewust géén bron (dat is een persoon)."""
    partij_el = root.find(partij, _NS)
    if partij_el is None:
        return None
    for pad in _PARTIJNAAM_PADEN:
        naam = _element_tekst(partij_el, pad)
        if naam:
            return naam
    return None


def _document_btw_percentage(root: ET.Element) -> str | None:
    """Eén btw-percentage voor het hele document uit cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent —
    alleen als álle subtotalen hetzelfde percentage dragen (blok 3 08-09, casus BDO: de regel zelf draagt geen
    ClassifiedTaxCategory/Percent, het TaxSubtotal wél). Meerdere percentages = None (nooit gokken per regel)."""
    percentages = {
        el.text.strip()
        for el in root.findall("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent", _NS)
        if el.text and el.text.strip()
    }
    return percentages.pop() if len(percentages) == 1 else None


def _parse_regels(root: ET.Element, *, regel_element: str, document_gb_code: str | None) -> tuple[dict, ...]:
    """Regels uit InvoiceLine/CreditNoteLine PLUS de document-niveau kortingen/toeslagen
    (bugfix 04-09, Huvanco-casus): een korting die de leverancier als eigen regel op de factuur zet,
    komt in de UBL als `cac:AllowanceCharge` op documentniveau (BG-20 korting / BG-21 toeslag) —
    zonder die regel telt Σregels niet op tot het totaal. REGEL-niveau AllowanceCharge (binnen een
    InvoiceLine, BG-27/BG-28) wordt bewust NIET als aparte regel opgenomen: per UBL-/EN 16931-
    definitie is `cbc:LineExtensionAmount` (BT-131) al het nettobedrag NÁ regelkorting/-toeslag —
    nog eens aftrekken zou dubbel tellen (de RLZ-export-fixture draagt zo'n regelkorting van 0)."""
    regels: list[dict] = []
    document_percentage = _document_btw_percentage(root)
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
                # Regel-percentage; ontbreekt het, dan het ene document-percentage uit de TaxSubtotal (blok 3 08-09).
                btw_percentage=_element_tekst(lijn, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")
                or _element_tekst(lijn, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent")
                or document_percentage,
                btw_categorie=_element_tekst(lijn, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID")
                or _element_tekst(lijn, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID"),
                # BT-133 per regel; BT-19 (documentniveau) is de contractuele fallback wanneer
                # alle regels dezelfde code delen (§2d-GB-uitbreiding v1.10).
                gb_code=_element_tekst(lijn, "cbc:AccountingCost") or document_gb_code,
                aantal=aantal,
                eenheid=eenheid,
                prijs=_element_tekst(lijn, "cac:Price/cbc:PriceAmount"),
            ).als_dict()
        )
    # Document-niveau kortingen/toeslagen als eigen regel — `findall("cac:AllowanceCharge")` matcht
    # uitsluitend DIRECTE kinderen van de root, dus nooit de regel-niveau varianten (zie docstring).
    for ac in root.findall("cac:AllowanceCharge", _NS):
        regel = _allowance_charge_als_regel(ac, volgnummer=len(regels) + 1, document_gb_code=document_gb_code)
        if regel is not None:
            regels.append(regel.als_dict())
    return tuple(regels)


def _allowance_charge_als_regel(ac: ET.Element, *, volgnummer: int, document_gb_code: str | None) -> UblRegel | None:
    """Eén document-niveau cac:AllowanceCharge → UblRegel: ChargeIndicator false = korting (netto
    NEGATIEF), true = toeslag (positief). Bedrag = cbc:Amount (per UBL non-negatief; een al negatief
    bedrag wordt niet nog eens omgekeerd — |Amount| met het teken van de soort). Omschrijving =
    cbc:AllowanceChargeReason, anders "Korting"/"Toeslag"; btw-categorie/-percentage uit
    cac:TaxCategory (zelfde vorm als ClassifiedTaxCategory op een regel). Zonder leesbaar bedrag of
    zonder ChargeIndicator: géén regel (niets gokken)."""
    indicator = (_element_tekst(ac, "cbc:ChargeIndicator") or "").strip().lower()
    if indicator not in {"true", "false"}:
        return None
    bedrag_tekst = _element_tekst(ac, "cbc:Amount")
    if not bedrag_tekst:
        return None
    try:
        bedrag = abs(Decimal(bedrag_tekst))
    except InvalidOperation:
        return None
    is_korting = indicator == "false"
    netto = -bedrag if is_korting else bedrag
    return UblRegel(
        volgnummer=volgnummer,
        omschrijving=_element_tekst(ac, "cbc:AllowanceChargeReason") or ("Korting" if is_korting else "Toeslag"),
        netto_bedrag=str(netto),
        btw_percentage=_element_tekst(ac, "cac:TaxCategory/cbc:Percent"),
        btw_categorie=_element_tekst(ac, "cac:TaxCategory/cbc:ID"),
        gb_code=document_gb_code,
        soort="korting" if is_korting else "toeslag",
    )


# Scheme-id's waaronder een KvK-nummer in UBL/NLCIUS voorkomt (PartyLegalEntity/CompanyID of PartyIdentification/ID):
# SI-UBL "NL:KVK", EN 16931/Peppol ICD "0106" (NL KvK). Zonder schemeID telt een 8-cijferige CompanyID onder
# PartyLegalEntity óók als KvK (BT-30 is in NL de KvK-inschrijving); een PartyIdentification zónder scheme niet
# (dat kan een klantnummer zijn).
_KVK_SCHEMES = {"NL:KVK", "0106", "KVK"}


def _leverancier_partij(root: ET.Element) -> ET.Element | None:
    return root.find("cac:AccountingSupplierParty/cac:Party", _NS)


def _leverancier_kvk(partij: ET.Element | None) -> str | None:
    """KvK uit PartyLegalEntity/CompanyID (voorkeur) of PartyIdentification/ID mét KvK-scheme — deterministisch
    genormaliseerd (8 cijfers) via dezelfde functie als de AI-controlelaag."""
    if partij is None:
        return None
    for el in partij.findall("cac:PartyLegalEntity/cbc:CompanyID", _NS):
        scheme = (el.get("schemeID") or "").upper()
        kvk = normaliseer_kvk_nummer(el.text)
        if kvk and (not scheme or scheme in _KVK_SCHEMES):
            return kvk
    for el in partij.findall("cac:PartyIdentification/cbc:ID", _NS):
        # SI-UBL 1.x / RLZ-export: `schemeAgencyName="KvK"` (zonder schemeID) — zelfde betekenis.
        scheme = (el.get("schemeID") or "").upper()
        agency = (el.get("schemeAgencyName") or "").upper()
        if scheme in _KVK_SCHEMES or agency == "KVK":
            kvk = normaliseer_kvk_nummer(el.text)
            if kvk:
                return kvk
    return None


def _leverancier_btw(partij: ET.Element | None) -> tuple[str | None, bool | None]:
    """Btw-nummer uit PartyTaxScheme/CompanyID (TaxScheme VAT of geen TaxScheme) — gevalideerd met dezelfde
    proef als de AI-controlelaag (`valideer_btw_nummer`): (genormaliseerd, geverifieerd) of (None, None)."""
    if partij is None:
        return None, None
    for pts in partij.findall("cac:PartyTaxScheme", _NS):
        scheme = (_element_tekst(pts, "cac:TaxScheme/cbc:ID") or "VAT").upper()
        if scheme not in {"VAT", "BTW"}:
            continue
        nummer = valideer_btw_nummer(_element_tekst(pts, "cbc:CompanyID"))
        if nummer is not None:
            return nummer.genormaliseerd, nummer.geverifieerd
    return None, None


def _leverancier_adres(partij: ET.Element | None) -> str | None:
    """Postadres als één leesbare regel ("Straat 1, 1234 AB Plaats, NL") — alleen voor de crediteur-dialoog."""
    if partij is None:
        return None
    adres = partij.find("cac:PostalAddress", _NS)
    if adres is None:
        return None
    straat = " ".join(
        t for t in (_element_tekst(adres, "cbc:StreetName"), _element_tekst(adres, "cbc:BuildingNumber")) if t
    )
    plaats = " ".join(t for t in (_element_tekst(adres, "cbc:PostalZone"), _element_tekst(adres, "cbc:CityName")) if t)
    land = _element_tekst(adres, "cac:Country/cbc:IdentificationCode")
    delen = [d for d in (straat, plaats, land) if d]
    return ", ".join(delen) or None


def _payee_iban(root: ET.Element) -> str | None:
    """Eerste GELDIG IBAN uit cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID (mod-97, `app/extractie/iban.py`)
    — een ongeldig nummer wordt nooit overgenomen (code voor cijfers)."""
    for el in root.findall("cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID", _NS):
        if is_geldig_iban(el.text):
            return normaliseer_iban(el.text)
    return None


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
    leverancier_naam = _partijnaam(root, "cac:AccountingSupplierParty")
    klant_naam = _partijnaam(root, "cac:AccountingCustomerParty")
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
    # Blok 3 (08-09): crediteur-identiteit + betaalgegevens deterministisch uit de XML.
    partij = _leverancier_partij(root)
    btw_nummer, btw_geverifieerd = _leverancier_btw(partij)
    vervaldatum = _tekst("cbc:DueDate") or _tekst("cac:PaymentMeans/cbc:PaymentDueDate")
    betalingskenmerk = next(
        (r for r in root.findall("cac:PaymentMeans/cbc:PaymentID", _NS) if r.text and r.text.strip()), None
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
        vervaldatum=vervaldatum,
        kvk_nummer=_leverancier_kvk(partij),
        btw_nummer=btw_nummer,
        btw_nummer_geverifieerd=btw_geverifieerd,
        iban=_payee_iban(root),
        leverancier_adres=_leverancier_adres(partij),
        betalingskenmerk=betalingskenmerk.text.strip() if betalingskenmerk is not None else None,
    )


def is_ubl_veldvoorstel(veldvoorstel: dict | None) -> bool:
    """Herkent een deterministisch UBL-veldvoorstel in de tijdlijn: `bron == "ubl"` (sinds 08-09) óf — voor
    voorstellen van vóór die datum — de UBL-eigen sleutel `ubl_regels`. Een AI-/template-voorstel is het nooit."""
    if not isinstance(veldvoorstel, dict):
        return False
    if veldvoorstel.get("bron") == BRON_UBL:
        return True
    return veldvoorstel.get("bron") is None and "ubl_regels" in veldvoorstel


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


@dataclass(frozen=True)
class IngeslotenBestand:
    """PDF die in de UBL zelf zit (cac:AdditionalDocumentReference/cac:Attachment/
    cbc:EmbeddedDocumentBinaryObject, doorgaans DocumentType "PrimaryImage")."""

    bestandsnaam: str
    inhoud: bytes


def lees_ingesloten_pdf(inhoud: bytes) -> IngeslotenBestand | None:
    """Eerste ingesloten PDF uit een UBL-bestand (bundeling 02-09). None bij geen/kapotte
    inhoud — nooit een fout: dit is een hulpmiddel voor beeld/bundeling, geen poort."""
    if b"<!DOCTYPE" in inhoud[:4096].upper():
        return None
    try:
        root = ET.fromstring(inhoud)
    except ET.ParseError:
        return None
    for ref in root.findall("cac:AdditionalDocumentReference", _NS):
        binair = ref.find("cac:Attachment/cbc:EmbeddedDocumentBinaryObject", _NS)
        if binair is None or not (binair.text or "").strip():
            continue
        mime = (binair.get("mimeCode") or "").lower()
        naam = (binair.get("filename") or "").strip()
        ref_id = (_element_tekst(ref, "cbc:ID") or "").strip()
        is_pdf = mime == "application/pdf" or naam.lower().endswith(".pdf") or ref_id.lower().endswith(".pdf")
        if not is_pdf:
            continue
        try:
            data = base64.b64decode("".join(binair.text.split()), validate=False)
        except (ValueError, TypeError):
            continue
        if not data.startswith(b"%PDF"):
            continue
        bestandsnaam = naam or (ref_id if ref_id.lower().endswith(".pdf") else "ingesloten.pdf")
        return IngeslotenBestand(bestandsnaam=bestandsnaam, inhoud=data)
    return None
