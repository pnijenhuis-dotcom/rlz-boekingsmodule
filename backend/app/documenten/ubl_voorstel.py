"""UBL-voorstel verrijken met de crediteur-match (blok 3 herstelrun "Basis eerst" 08-09, casus BDO 6088744).

Een UBL is DETERMINISTISCH: crediteurnaam, KvK, btw-nummer, IBAN, referentie, datums, totalen en regels komen
rechtstreeks uit de XML (`documenten/ubl.py`) — nooit via AI, nooit leeg als de XML ze draagt. Wat tot 08-09
ontbrak: de crediteur-match liep voor een UBL uitsluitend op een EXACTE naam (`boekvoorstel._raad_vendor_id`),
terwijl het AI-pad al btw-nummer → KvK → naam (exact/fuzzy mét mismatch-guard) kende. Hier hetzelfde matchpad
voor de UBL, plus het IBAN als vierde sleutel (vertrouwde rekening van precies één bruikbare crediteur).

Twee afnemers, één functie:
- `verrijk_met_crediteur_match` — bij de extractie-afronding van een UBL (`service._rond_extractie_af`): het
  veldvoorstel in de tijdlijn draagt `vendor_suggestie`/`vendor_waarschuwing` in dezelfde vorm als het AI-voorstel;
- `raad_vendor_id` — live bij de prefill (`boekvoorstel._bereken_prefill`) voor UBL-voorstellen van vóór 08-09
  (geen suggestie in de tijdlijn) én voor een UBL die geopend wordt ná het aanmaken van de crediteur.
Voorstel, geen automatische keuze: bij twijfel (nummer bij twee crediteuren, twee namen) géén suggestie.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documenten.crediteur_kenmerk import kandidaten_met_kenmerken
from app.documenten.models import LeverancierIban
from app.documenten.ubl import is_ubl_veldvoorstel
from app.extractie.controle import TaxRateKandidaat, VendorWaarschuwing, leid_btw_af, match_vendor_met_waarschuwing

MATCH_IBAN = "iban"


def _decimal(waarde: object) -> Decimal | None:
    if waarde is None or waarde == "":
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def regel_btw_bedrag(regel: dict) -> Decimal | None:
    """Btw-bedrag van één UBL-regel: expliciet meegegeven (`btw_bedrag`, ná verrijking) of deterministisch netto ×
    cbc:Percent / 100 (cent-exact afgerond). None als netto of percentage ontbreekt — nooit een gok."""
    expliciet = _decimal(regel.get("btw_bedrag"))
    if expliciet is not None:
        return expliciet
    netto, pct = _decimal(regel.get("netto_bedrag")), _decimal(regel.get("btw_percentage"))
    if netto is None or pct is None:
        return None
    return (netto * pct / Decimal(100)).quantize(Decimal("0.01"))


def regels_met_btw(ubl_regels: list[dict], *, taxrates: list[TaxRateKandidaat]) -> list[dict]:
    """Per UBL-regel het btw-bedrag (uit cbc:Percent) en de btw-code van de administratie (`leid_btw_af`: netto ×
    tarief ≈ btw, RLZ-favoriet als tiebreak; 0/meerduidig = leeg mét reden) — zelfde deterministische afleiding als het
    AI-pad, dus dezelfde sleutels (`btw_bedrag`, `taxrate_id`, `btw_bron`, `btw_afleiding_reden`)."""
    uit: list[dict] = []
    for regel in ubl_regels:
        netto = _decimal(regel.get("netto_bedrag"))
        btw = regel_btw_bedrag(regel)
        afleiding = leid_btw_af(netto, btw, taxrates)
        uit.append(
            {
                **regel,
                "btw_bedrag": str(btw) if btw is not None else None,
                "taxrate_id": str(afleiding.taxrate_id) if afleiding.taxrate_id is not None else None,
                "btw_bron": afleiding.bron,
                "btw_afleiding_reden": afleiding.reden,
            }
        )
    return uit


def _vendor_op_iban(session: Session, *, administratie_id: uuid.UUID, iban: str | None) -> uuid.UUID | None:
    """Vertrouwde rekening (`leverancier_iban`) van precies één BRUIKBARE crediteur (verliezer → voorkeur, B13)."""
    if not iban:
        return None
    from app.crediteuren.voorkeur import voorkeur_van

    vendor_ids = session.scalars(
        select(LeverancierIban.vendor_id).where(
            LeverancierIban.administratie_id == administratie_id, LeverancierIban.iban == iban
        )
    ).all()
    kandidaten = {voorkeur_van(session, administratie_id=administratie_id, vendor_id=v) for v in vendor_ids}
    kandidaten.discard(None)
    return kandidaten.pop() if len(kandidaten) == 1 else None


def crediteur_match(
    session: Session, *, administratie_id: uuid.UUID, veldvoorstel: dict
) -> tuple[uuid.UUID | None, str | None, VendorWaarschuwing | None]:
    """(vendor_id, match, waarschuwing) — volgorde btw-nummer → KvK → IBAN → naam (exact, fuzzy mét guard)."""
    kandidaten = kandidaten_met_kenmerken(session, administratie_id=administratie_id)
    btw = veldvoorstel.get("btw_nummer") or None
    kvk = veldvoorstel.get("kvk_nummer") or None
    naam = veldvoorstel.get("leverancier_naam") or None
    # Stap 1: uitsluitend op nummer (naam=None → de naam-tak wordt niet geraakt).
    vendor_id, match, _ = match_vendor_met_waarschuwing(None, kandidaten, btw_nummer=btw, kvk_nummer=kvk)
    if vendor_id is not None:
        return vendor_id, match, None
    # Stap 2: IBAN — een vertrouwde rekening van precies één crediteur.
    op_iban = _vendor_op_iban(session, administratie_id=administratie_id, iban=veldvoorstel.get("iban") or None)
    if op_iban is not None:
        return op_iban, MATCH_IBAN, None
    # Stap 3: naam (exact/fuzzy) mét de KvK-/btw-mismatch-guard van het AI-pad.
    return match_vendor_met_waarschuwing(naam, kandidaten, btw_nummer=btw, kvk_nummer=kvk)


def verrijk_met_crediteur_match(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    veldvoorstel: dict,
    taxrates: list[TaxRateKandidaat] | None = None,
) -> dict:
    """Zelfde sleutels als het AI-veldvoorstel (`vendor_suggestie`, `vendor_waarschuwing`) op het UBL-voorstel; mét
    `taxrates` krijgen de `ubl_regels` óók btw-bedrag + btw-code (deterministisch, `regels_met_btw`)."""
    vendor_id, match, waarschuwing = crediteur_match(
        session, administratie_id=administratie_id, veldvoorstel=veldvoorstel
    )
    regels = veldvoorstel.get("ubl_regels")
    return {
        **veldvoorstel,
        "ubl_regels": regels_met_btw(list(regels), taxrates=taxrates)
        if taxrates is not None and isinstance(regels, list)
        else regels,
        "vendor_suggestie": {"vendor_id": str(vendor_id), "match": match} if vendor_id is not None else None,
        "vendor_waarschuwing": waarschuwing.als_dict() if waarschuwing is not None else None,
    }


def raad_vendor_id(session: Session, *, administratie_id: uuid.UUID, veldvoorstel: dict | None) -> uuid.UUID | None:
    """Live crediteur-suggestie voor een UBL-veldvoorstel (prefill-pad). None voor niet-UBL of geen match."""
    if not is_ubl_veldvoorstel(veldvoorstel):
        return None
    vendor_id, _, _ = crediteur_match(session, administratie_id=administratie_id, veldvoorstel=veldvoorstel or {})
    return vendor_id
