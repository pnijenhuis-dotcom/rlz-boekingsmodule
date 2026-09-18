"""Btw-keuzelijst: land van de leverancier + gebruiksfrequentie per tarief (opdracht Peter 18-09 DEEL B: "ik zie telkens
alle nul % tarieven, ook alle EU-regels. Als leverancier NLD adres heeft dan die hele rits graag niet tonen").

Feit (api-verkenning "Land en btw-nummer van een Vendor", probe 31-08): het land van de crediteur is via de RLZ-API NIET
leesbaar. Deterministisch beschikbaar, in deze volgorde (eerste treffer wint):
  1. btw-nummer van de crediteur in `crediteur_kenmerk.btw_nummer` (landprefix NL/BE/DE/…);
  2. btw-nummer op de factuur (extractie, mod-97/elfproef-gevalideerd in de controlelaag);
  3. IBAN-landcode: de factuur-IBAN, anders de vertrouwde IBAN-set van de crediteur (`leverancier_iban`) als die
     eenduidig één land geeft;
  4. onbekend → de keuzelijst toont ÁLLES (nooit iets wegnemen op een gok).
Het factuuradres-land (AI, lagere zekerheid) is bewust NIET gebouwd: het inkoop-extractieschema kent geen adresveld en
een
nieuw AI-veld is een schema-uitbreiding (sentinel, ≤ 16 unions) — beslispunt in het rapport 18-09.

De frontend (`useTaxrateOptiesGefilterd`) toont bij land NL alleen de NL-tarieven en klapt de buitenland-tarieven in;
de prefill/autoboek-winnaarsvolgorde verandert hier NIET (weergave). `taxrate_gebruik_12m` levert per tarief het aantal
inkoop-/bankboekingsregels van de administratie in de laatste 12 maanden (boekingsgeheugen `boeking_observatie`, bron
'app'/'rlz' — de mens-boekingen én de RLZ-historie) zodat de vijf werk-tarieven bovenaan staan.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.documenten.models import LeverancierIban
from app.geheugen.models import BoekingObservatie
from app.tijd import vandaag_nl

LAND_BRON_BTW_CREDITEUR = "btw_nummer_crediteur"
LAND_BRON_BTW_FACTUUR = "btw_nummer_factuur"
LAND_BRON_IBAN_FACTUUR = "iban_factuur"
LAND_BRON_IBAN_CREDITEUR = "iban_crediteur"

LAND_BRON_TEKST = {
    LAND_BRON_BTW_CREDITEUR: "uit btw-nummer crediteur",
    LAND_BRON_BTW_FACTUUR: "uit btw-nummer factuur",
    LAND_BRON_IBAN_FACTUUR: "uit IBAN factuur",
    LAND_BRON_IBAN_CREDITEUR: "uit IBAN crediteur",
}

_LANDCODE = re.compile(r"^[A-Z]{2}$")
GEBRUIK_VENSTER_DAGEN = 365


@dataclass(frozen=True)
class LandInfo:
    land: str | None
    bron: str | None

    @property
    def bron_tekst(self) -> str | None:
        return LAND_BRON_TEKST.get(self.bron or "")


ONBEKEND = LandInfo(None, None)


def land_uit_btw_nummer(nummer: str | None) -> str | None:
    """Landprefix van een EU-btw-nummer ("NL001234567B01" → "NL"; Griekenland gebruikt "EL" — dat blijft "EL", de
    frontend toetst alleen op 'NL')."""
    if not nummer:
        return None
    kaal = re.sub(r"[\s.\-]", "", nummer).upper()
    prefix = kaal[:2]
    return prefix if _LANDCODE.match(prefix) and not prefix.isdigit() else None


def land_uit_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    kaal = re.sub(r"\s", "", iban).upper()
    prefix = kaal[:2]
    return prefix if _LANDCODE.match(prefix) else None


def bepaal_leverancier_land(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None, veldvoorstel: dict | None
) -> LandInfo:
    """Zie de moduledocstring: kenmerk → factuur-btw-nummer → factuur-IBAN → vertrouwde IBAN's (eenduidig) →
    onbekend."""
    if vendor_id is not None:
        from app.documenten import crediteur_kenmerk  # lokaal: crediteur_kenmerk leest de controlelaag

        kenmerk = crediteur_kenmerk.kenmerken_per_vendor(session, administratie_id=administratie_id).get(vendor_id)
        land = land_uit_btw_nummer(kenmerk.btw_nummer) if kenmerk is not None else None
        if land:
            return LandInfo(land, LAND_BRON_BTW_CREDITEUR)
    vv = veldvoorstel or {}
    land = land_uit_btw_nummer(vv.get("btw_nummer"))
    if land:
        return LandInfo(land, LAND_BRON_BTW_FACTUUR)
    land = land_uit_iban(vv.get("iban"))
    if land:
        return LandInfo(land, LAND_BRON_IBAN_FACTUUR)
    if vendor_id is not None:
        ibans = session.scalars(
            select(LeverancierIban.iban).where(
                LeverancierIban.administratie_id == administratie_id, LeverancierIban.vendor_id == vendor_id
            )
        ).all()
        landen = {land_uit_iban(i) for i in ibans} - {None}
        if len(landen) == 1:
            return LandInfo(next(iter(landen)), LAND_BRON_IBAN_CREDITEUR)
    return ONBEKEND


def taxrate_gebruik_12m(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """{taxrate_id: aantal boekingsregels in de laatste 12 maanden} uit het boekingsgeheugen — één statement."""
    vanaf = vandaag_nl() - timedelta(days=GEBRUIK_VENSTER_DAGEN)
    rijen = session.execute(
        select(BoekingObservatie.btw_id, func.count())
        .where(
            BoekingObservatie.administratie_id == administratie_id,
            BoekingObservatie.btw_id.is_not(None),
            BoekingObservatie.bron_datum >= vanaf,
        )
        .group_by(BoekingObservatie.btw_id)
    ).all()
    return {btw_id: int(n) for btw_id, n in rijen if btw_id is not None}
