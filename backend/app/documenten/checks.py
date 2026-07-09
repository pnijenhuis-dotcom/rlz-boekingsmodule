from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rlz.client import RlzClient

# Toegestane afronding tussen "som van de regels" en het factuurtotaal — RLZ zelf rekent met
# centen, en het UBL-veldvoorstel/handmatige invoer kan een cent afwijken door afronding per
# regel. Geen harde 0-tolerantie, wél klein genoeg om een echte fout (verkeerd bedrag) te vangen.
_ROND_TOLERANTIE = Decimal("0.01")


@dataclass(frozen=True)
class CheckRegel:
    """Eén boekingsregel zoals de checks 'm nodig hebben — bewust los van het SQLAlchemy-model
    (app/documenten/models.py::BoekvoorstelRegel), zodat deze module zonder DB/sessie te testen
    is (Code voor cijfers: pure functies op primitieven, geen ORM-koppeling in de rekenlogica)."""

    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None


@dataclass(frozen=True)
class CheckResultaat:
    naam: str
    ok: bool
    melding: str


@dataclass(frozen=True)
class CheckRapport:
    resultaten: tuple[CheckResultaat, ...]

    @property
    def geblokkeerd(self) -> bool:
        return any(not r.ok for r in self.resultaten)


def check_verplichte_velden(
    *,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[CheckRegel],
) -> CheckResultaat:
    ontbrekend: list[str] = []
    if vendor_id is None:
        ontbrekend.append("crediteur")
    if not referentie:
        ontbrekend.append("referentie")
    if factuurdatum is None:
        ontbrekend.append("factuurdatum")
    if totaalbedrag is None:
        ontbrekend.append("totaalbedrag")
    if not regels:
        ontbrekend.append("minstens één boekingsregel")
    for i, regel in enumerate(regels, start=1):
        if regel.ledger_id is None:
            ontbrekend.append(f"grootboekrekening (regel {i})")
        if regel.taxrate_id is None:
            ontbrekend.append(f"btw-code (regel {i})")
        if regel.netto_bedrag is None:
            ontbrekend.append(f"netto bedrag (regel {i})")

    if ontbrekend:
        return CheckResultaat("Verplichte velden", False, f"Ontbrekend: {', '.join(ontbrekend)}")
    return CheckResultaat("Verplichte velden", True, "Alle verplichte velden zijn ingevuld")


def check_regeltelling(*, totaalbedrag: Decimal | None, regels: list[CheckRegel]) -> CheckResultaat:
    if totaalbedrag is None:
        return CheckResultaat("Regeltelling vs totaal", False, "Geen factuurtotaal ingevuld om tegen te controleren")
    som = sum((r.netto_bedrag or Decimal(0)) + (r.btw_bedrag or Decimal(0)) for r in regels)
    verschil = abs(som - totaalbedrag)
    if verschil > _ROND_TOLERANTIE:
        return CheckResultaat(
            "Regeltelling vs totaal",
            False,
            f"Som van de regels (€ {som}) wijkt € {verschil} af van het factuurtotaal (€ {totaalbedrag})",
        )
    return CheckResultaat("Regeltelling vs totaal", True, f"Som van de regels (€ {som}) komt overeen met het totaal")


def check_duplicaat(
    *,
    client: RlzClient,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
    eigen_rlz_document_id: uuid.UUID,
) -> CheckResultaat:
    """Eigen duplicaatquery (RLZ's actie 138 geeft geen bruikbaar signaal, besluit 0013): zoekt
    op Entity+Reference(afgekapt op 30 tekens, zie RlzClient.find_purchase_invoices_by_reference)
    +bedrag. Een hit op het EIGEN client-GUID (`eigen_rlz_document_id`) is geen duplicaat maar de
    eigen, eventueel al eerder gelukte PUT — anders zou een retry na boeken_mislukt zichzelf als
    duplicaat blokkeren."""
    if vendor_id is None or not referentie:
        return CheckResultaat("Duplicaatcheck", False, "Kan niet controleren zonder crediteur en referentie")
    bedrag = float(totaalbedrag) if totaalbedrag is not None else None
    gevonden = client.find_purchase_invoices_by_reference(
        vendor_id=vendor_id, reference=referentie, total_amount=bedrag
    )
    anderen = [f for f in gevonden if f.get("id") != str(eigen_rlz_document_id)]
    if anderen:
        return CheckResultaat(
            "Duplicaatcheck",
            False,
            f"{len(anderen)} bestaande factuur/facturen in RLZ met dezelfde crediteur, referentie en bedrag",
        )
    return CheckResultaat("Duplicaatcheck", True, "Geen bestaande factuur met dezelfde crediteur/referentie/bedrag")


def voer_harde_checks_uit(
    *,
    client: RlzClient,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[CheckRegel],
    eigen_rlz_document_id: uuid.UUID,
) -> CheckRapport:
    """Alle harde checks (CLAUDE.md: "áltijd blokkerend"), in vaste volgorde zodat de UI
    consistent dezelfde drie rijen toont. Verplichte-velden staat vóórop: als die al faalt, zijn
    de andere twee checks vaak ook zinloos (bv. geen totaalbedrag -> regeltelling kan niet
    zinvol getoetst worden) — de UI toont ze desondanks alle drie, nooit stil overslaan."""
    return CheckRapport(
        (
            check_verplichte_velden(
                vendor_id=vendor_id,
                referentie=referentie,
                factuurdatum=factuurdatum,
                totaalbedrag=totaalbedrag,
                regels=regels,
            ),
            check_regeltelling(totaalbedrag=totaalbedrag, regels=regels),
            check_duplicaat(
                client=client,
                vendor_id=vendor_id,
                referentie=referentie,
                totaalbedrag=totaalbedrag,
                eigen_rlz_document_id=eigen_rlz_document_id,
            ),
        )
    )
