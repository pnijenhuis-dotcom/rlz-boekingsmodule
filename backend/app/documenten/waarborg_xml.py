"""VASTLY-WAARBORG-berichtparser (koppelcontract §2d-waarborgroute, velddefinitie DEFINITIEF
v1.11 — blok E grote opdracht 2026-08-10).

Een waarborg is geen fiscaal factuurstuk: vastgoed levert 'm bewust NIET als pseudo-factuur-UBL
maar als een klein, deterministisch XML-bijlageformaat met root `VastlyWaarborg` (de markering
ís het root-element-kind, zelfde herkenningspatroon als §2d). Wij herkennen, valideren en
boeken het memoriaal; `bericht_id` (UUIDv5, door vastgoed gegenereerd) is de
idempotentiesleutel.

Concrete elementvorm (schema-versie 1.0, registers/schema-versions.md — vastgoed bouwt de
verzendkant op deze vorm, zie OPEN_ITEMS 2026-08-10):

    <VastlyWaarborg versie="1.0">
      <BerichtId>7d444840-…</BerichtId>
      <VerhuurderEntiteit rlzAdminId="be5e66b3-…">Rubicon Investments B.V.</VerhuurderEntiteit>
      <ContractReferentie>CT-2026-0042</ContractReferentie>
      <Huurder>J. de Tester</Huurder>
      <Bedrag>1500.00</Bedrag>
      <Richting>ontvangst</Richting>
      <Datum>2026-08-01</Datum>
      <BalansGbCode>0204</BalansGbCode>
    </VastlyWaarborg>

`rlzAdminId` is een hint — de tenaamstelling (`VerhuurderEntiteit`-tekst) is leidend voor de
administratie-toewijzing, exact zoals bij elke intake (CLAUDE.md verzamelbak-principe)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

WAARBORG_ROOT = "VastlyWaarborg"
RICHTINGEN = ("ontvangst", "terugbetaling")


class OngeldigWaarborgBericht(Exception):
    """De inhoud is geen (herkenbaar) VASTLY-WAARBORG-bericht."""


@dataclass(frozen=True)
class WaarborgBerichtData:
    schema_versie: str | None
    bericht_id: uuid.UUID | None
    verhuurder_entiteit: str | None
    rlz_admin_id_hint: str | None
    contract_referentie: str | None
    huurder: str | None
    bedrag: Decimal | None
    richting: str | None
    datum: date | None
    balans_gb_code: str | None


def _lokale_naam(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_waarborg_xml(inhoud: bytes) -> bool:
    """Snelle root-herkenning zonder volledige validatie — de intake beslist hiermee of het
    waarborg-pad (incl. failsafe naar de verzamelbak) van toepassing is."""
    if b"<!DOCTYPE" in inhoud[:4096].upper():
        return False
    try:
        root = ET.fromstring(inhoud)
    except ET.ParseError:
        return False
    return _lokale_naam(root.tag) == WAARBORG_ROOT


def parseer_waarborg_bericht(inhoud: bytes) -> WaarborgBerichtData:
    """Parseert best-effort: ontbrekende of onbruikbare velden worden None — de intake-failsafe
    (`waarborg_velden_ontbrekend`) beslist daarna zichtbaar over verzamelbak vs verwerken.
    Zelfde DOCTYPE-weigering als de UBL-parser (entity-expansion)."""
    if b"<!DOCTYPE" in inhoud[:4096].upper():
        raise OngeldigWaarborgBericht("XML met DOCTYPE wordt geweigerd (entity-expansion-risico)")
    try:
        root = ET.fromstring(inhoud)
    except ET.ParseError as exc:
        raise OngeldigWaarborgBericht(f"Geen geldige XML: {exc}") from exc
    if _lokale_naam(root.tag) != WAARBORG_ROOT:
        raise OngeldigWaarborgBericht(f"Root-element is {root.tag}, geen {WAARBORG_ROOT}")

    velden: dict[str, str] = {}
    rlz_admin_id_hint: str | None = None
    for kind in root:
        naam = _lokale_naam(kind.tag)
        velden[naam] = (kind.text or "").strip()
        if naam == "VerhuurderEntiteit":
            rlz_admin_id_hint = (kind.get("rlzAdminId") or "").strip() or None

    def _uuid(waarde: str | None) -> uuid.UUID | None:
        try:
            return uuid.UUID(waarde) if waarde else None
        except ValueError:
            return None

    def _decimal(waarde: str | None) -> Decimal | None:
        try:
            return Decimal(waarde) if waarde else None
        except InvalidOperation:
            return None

    def _datum(waarde: str | None) -> date | None:
        try:
            return date.fromisoformat(waarde) if waarde else None
        except ValueError:
            return None

    richting = (velden.get("Richting") or "").strip().lower() or None
    return WaarborgBerichtData(
        schema_versie=(root.get("versie") or "").strip() or None,
        bericht_id=_uuid(velden.get("BerichtId")),
        verhuurder_entiteit=velden.get("VerhuurderEntiteit") or None,
        rlz_admin_id_hint=rlz_admin_id_hint,
        contract_referentie=velden.get("ContractReferentie") or None,
        huurder=velden.get("Huurder") or None,
        bedrag=_decimal(velden.get("Bedrag")),
        richting=richting if richting in RICHTINGEN else None,
        datum=_datum(velden.get("Datum")),
        balans_gb_code=velden.get("BalansGbCode") or None,
    )


def waarborg_velden_ontbrekend(bericht: WaarborgBerichtData) -> list[str]:
    """Failsafe-toets (§2d-waarborgroute): elk contractueel veld moet aanwezig én bruikbaar
    zijn — incompleet bericht → verzamelbak, nooit stil verwerken. `bedrag` moet bovendien
    positief zijn (contract: "altijd positief"; de richting bepaalt debet/credit)."""
    ontbrekend = []
    if bericht.bericht_id is None:
        ontbrekend.append("bericht_id (BerichtId, uuid)")
    if not bericht.verhuurder_entiteit:
        ontbrekend.append("verhuurder_entiteit (VerhuurderEntiteit)")
    if not bericht.contract_referentie:
        ontbrekend.append("contract_referentie (ContractReferentie)")
    if not bericht.huurder:
        ontbrekend.append("huurder (Huurder)")
    if bericht.bedrag is None or bericht.bedrag <= 0:
        ontbrekend.append("bedrag (Bedrag, positief)")
    if bericht.richting is None:
        ontbrekend.append("richting (Richting: ontvangst|terugbetaling)")
    if bericht.datum is None:
        ontbrekend.append("datum (Datum, ISO)")
    if not bericht.balans_gb_code:
        ontbrekend.append("balans_gb_code (BalansGbCode)")
    return ontbrekend
