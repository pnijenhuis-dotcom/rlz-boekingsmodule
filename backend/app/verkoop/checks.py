"""Harde checks voor het Vastly-verkoopfactuur-boekpad (koppelcontract §2d v1.10/v1.11) —
puur en deterministisch, zelfde conventies als app/documenten/checks.py: elke check geeft een
CheckResultaat, ok=False blokkeert boeken onvoorwaardelijk, en een check die niet uitgevoerd
kón worden is blokkerend (fail-closed), nooit stil overgeslagen.

De orkestratie (voorstel laden, GB-codes resolven, RLZ-duplicaatquery) staat in
app/verkoop/voorstel.py::voer_verkoop_checks_uit — hier alleen logica op primitieven."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.documenten.checks import CheckRapport, CheckResultaat

_ROND_TOLERANTIE = Decimal("0.01")


@dataclass(frozen=True)
class VerkoopCheckRegel:
    volgnummer: int
    omschrijving: str | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    gb_code: str | None
    ledger_id_bekend: bool
    taxrate_id_bekend: bool
    # Resultaat van de code→ledger-resolutie (voorstel.py): 'bekend', 'onbekend' (code staat
    # niet in het rekeningschema van deze administratie — blokkerend, §2d), of 'ontbreekt'
    # (geen AccountingCost — géén fout, mens kiest; de verplichte-velden-check dekt dit).
    gb_code_status: str = "ontbreekt"


def check_verplichte_velden_verkoop(
    *,
    debiteur_naam: str | None,
    factuurnummer: str | None,
    factuurdatum: date | None,
    totaalbedrag_incl: Decimal | None,
    regels: list[VerkoopCheckRegel],
) -> CheckResultaat:
    """Alles wat de SalesInvoice-PUT nodig heeft: debiteur (Entity), Vastly-factuurnummer
    (webhook-referentie + duplicaatsleutel), datum, totaal en per regel bedrag + GB + btw-code."""
    ontbrekend: list[str] = []
    if not (debiteur_naam or "").strip():
        ontbrekend.append("debiteur (huurder uit de UBL)")
    if not (factuurnummer or "").strip():
        ontbrekend.append("factuurnummer")
    if factuurdatum is None:
        ontbrekend.append("factuurdatum")
    if totaalbedrag_incl is None:
        ontbrekend.append("totaalbedrag")
    if not regels:
        ontbrekend.append("minimaal één factuurregel")
    for regel in regels:
        if regel.netto_bedrag is None:
            ontbrekend.append(f"regel {regel.volgnummer}: nettobedrag")
        if not regel.ledger_id_bekend:
            ontbrekend.append(f"regel {regel.volgnummer}: grootboekrekening")
        if not regel.taxrate_id_bekend:
            ontbrekend.append(f"regel {regel.volgnummer}: btw-code")
    if ontbrekend:
        return CheckResultaat(
            naam="verplichte_velden",
            ok=False,
            melding="Ontbrekend: " + "; ".join(ontbrekend),
        )
    return CheckResultaat(naam="verplichte_velden", ok=True, melding="Alle verplichte velden zijn gevuld")


def check_regelsom_verkoop(
    *, totaalbedrag_incl: Decimal | None, regels: list[VerkoopCheckRegel]
) -> CheckResultaat:
    """Som van netto+btw over de regels moet het factuurtotaal (incl.) dekken — zelfde
    tolerantie (€ 0,01) als de inkoop-regeltelling. Bedragen zijn hier altijd de positieve
    UBL-bedragen; het credit-teken komt pas bij het boeken (tegenboeking)."""
    if totaalbedrag_incl is None or not regels:
        return CheckResultaat(
            naam="regelsom",
            ok=False,
            melding="Regelsom niet controleerbaar: totaalbedrag of regels ontbreken",
        )
    som = sum(((r.netto_bedrag or Decimal(0)) + (r.btw_bedrag or Decimal(0)) for r in regels), Decimal(0))
    verschil = abs(som - totaalbedrag_incl)
    if verschil > _ROND_TOLERANTIE:
        return CheckResultaat(
            naam="regelsom",
            ok=False,
            melding=f"Regels tellen op tot {som}, factuurtotaal is {totaalbedrag_incl} (verschil {verschil})",
        )
    return CheckResultaat(naam="regelsom", ok=True, melding=f"Regels dekken het factuurtotaal ({som})")


def check_gb_codes_bekend(*, regels: list[VerkoopCheckRegel]) -> CheckResultaat:
    """§2d-GB-uitbreiding v1.10, hard: een AccountingCost-code die niet in het rekeningschema
    van deze administratie bestaat is blokkerend + automatische vraag — nooit stil een andere
    rekening kiezen. Een regel zónder code is hier géén fout (mens kiest — verplichte velden
    dekt de uiteindelijke keuze)."""
    onbekend = [f"regel {r.volgnummer}: {r.gb_code}" for r in regels if r.gb_code_status == "onbekend"]
    if onbekend:
        return CheckResultaat(
            naam="gb_code_bekend",
            ok=False,
            melding="Onbekende grootboekcode uit de UBL (bestaat niet in het rekeningschema van "
            "deze administratie): " + "; ".join(onbekend),
        )
    return CheckResultaat(naam="gb_code_bekend", ok=True, melding="Alle GB-codes uit de UBL zijn bekend")


def check_duplicaat_verkoop(
    *,
    lokale_hits: int,
    rlz_hits: int | None,
    factuurnummer: str | None,
) -> CheckResultaat:
    """Duplicaatbewaking verkoop: lokaal per (administratie, Vastly-factuurnummer, soort) +
    RLZ-side via de Receipts-collectie op de deterministische Description (de collectie ziet —
    anders dan SalesInvoices — óók API-documenten; Receipts-verkenning 2026-08-09). rlz_hits
    None = de RLZ-check kon niet uitgevoerd worden → blokkerend (fail-closed)."""
    if lokale_hits > 0:
        return CheckResultaat(
            naam="duplicaat",
            ok=False,
            melding=f"Factuurnummer {factuurnummer} is al geboekt voor deze administratie "
            f"({lokale_hits} eerdere boeking(en))",
        )
    if rlz_hits is None:
        return CheckResultaat(
            naam="duplicaat",
            ok=False,
            melding="RLZ-duplicaatcheck kon niet uitgevoerd worden — boeken geblokkeerd (fail-closed)",
        )
    if rlz_hits > 0:
        return CheckResultaat(
            naam="duplicaat",
            ok=False,
            melding=f"In Reeleezee staan al {rlz_hits} document(en) met deze factuur-omschrijving",
        )
    return CheckResultaat(naam="duplicaat", ok=True, melding="Geen duplicaat gevonden (lokaal + RLZ)")


def check_creditnota_herleiding(
    *,
    is_creditnota: bool,
    gecrediteerd_factuurnummer: str | None,
    origineel_geboekt: bool,
) -> CheckResultaat:
    """§2d-creditnota's v1.11: de BillingReference is de koppelsleutel naar de eerder geboekte
    verkoopfactuur — zonder herleidbaar, geboekt origineel is er geen tegenboeking mogelijk."""
    if not is_creditnota:
        return CheckResultaat(naam="creditnota_herleiding", ok=True, melding="n.v.t. (geen creditnota)")
    if not (gecrediteerd_factuurnummer or "").strip():
        return CheckResultaat(
            naam="creditnota_herleiding",
            ok=False,
            melding="Creditnota zonder gecrediteerd factuurnummer (BillingReference)",
        )
    if not origineel_geboekt:
        return CheckResultaat(
            naam="creditnota_herleiding",
            ok=False,
            melding=f"De gecrediteerde factuur {gecrediteerd_factuurnummer} is niet als geboekte "
            "verkoopfactuur bekend in deze administratie",
        )
    return CheckResultaat(
        naam="creditnota_herleiding",
        ok=True,
        melding=f"Crediteert geboekte factuur {gecrediteerd_factuurnummer}",
    )


def voer_verkoop_checks_uit(
    *,
    debiteur_naam: str | None,
    factuurnummer: str | None,
    factuurdatum: date | None,
    totaalbedrag_incl: Decimal | None,
    regels: list[VerkoopCheckRegel],
    lokale_duplicaat_hits: int,
    rlz_duplicaat_hits: int | None,
    is_creditnota: bool,
    gecrediteerd_factuurnummer: str | None,
    origineel_geboekt: bool,
) -> CheckRapport:
    """Vaste volgorde, alle checks draaien altijd (geen short-circuit — de controleur ziet het
    volledige rapport in één keer, mockup #review-patroon)."""
    resultaten = (
        check_verplichte_velden_verkoop(
            debiteur_naam=debiteur_naam,
            factuurnummer=factuurnummer,
            factuurdatum=factuurdatum,
            totaalbedrag_incl=totaalbedrag_incl,
            regels=regels,
        ),
        check_regelsom_verkoop(totaalbedrag_incl=totaalbedrag_incl, regels=regels),
        check_gb_codes_bekend(regels=regels),
        check_duplicaat_verkoop(
            lokale_hits=lokale_duplicaat_hits,
            rlz_hits=rlz_duplicaat_hits,
            factuurnummer=factuurnummer,
        ),
        check_creditnota_herleiding(
            is_creditnota=is_creditnota,
            gecrediteerd_factuurnummer=gecrediteerd_factuurnummer,
            origineel_geboekt=origineel_geboekt,
        ),
    )
    return CheckRapport(resultaten=resultaten)
