from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.extractie.iban import masker_iban
from app.rlz.client import RlzApiError, RlzClient

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
    project_id: uuid.UUID | None = None


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
    project_verplicht: bool = False,
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
        if project_verplicht and regel.project_id is None:
            ontbrekend.append(f"project (regel {i})")

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
    duplicaat blokkeren.

    Een falende RLZ-aanroep hier mag nooit als kale 500 bij de gebruiker terechtkomen — zonder
    duplicaatcheck is boeken net zo onverantwoord als met een echte duplicaat-hit, dus dit
    resultaat blijft blokkerend, maar wél als een normaal (herkenbaar) checkresultaat i.p.v. een
    onafgevangen exception die de hele PUT/checks-aanroep laat crashen."""
    if vendor_id is None or not referentie:
        return CheckResultaat("Duplicaatcheck", False, "Kan niet controleren zonder crediteur en referentie")
    bedrag = float(totaalbedrag) if totaalbedrag is not None else None
    try:
        gevonden = client.find_purchase_invoices_by_reference(
            vendor_id=vendor_id, reference=referentie, total_amount=bedrag
        )
    except RlzApiError as exc:
        return CheckResultaat("Duplicaatcheck", False, f"Duplicaatcheck kon niet uitgevoerd worden: {exc}")
    except Exception as exc:  # noqa: BLE001 — bewust breed: elke RLZ-connectiefout blokkeert, crasht nooit
        return CheckResultaat("Duplicaatcheck", False, f"Duplicaatcheck kon niet uitgevoerd worden: {exc}")
    anderen = [f for f in gevonden if f.get("id") != str(eigen_rlz_document_id)]
    if anderen:
        return CheckResultaat(
            "Duplicaatcheck",
            False,
            f"{len(anderen)} bestaande factuur/facturen in RLZ met dezelfde crediteur, referentie en bedrag",
        )
    return CheckResultaat("Duplicaatcheck", True, "Geen bestaande factuur met dezelfde crediteur/referentie/bedrag")


def check_iban_wissel(
    *,
    factuur_iban: str | None,
    vertrouwde_ibans: set[str],
    baseline_vastgelegd: bool = False,
    seed_mislukt: bool = False,
) -> CheckResultaat:
    """IBAN-wissel-fraudecontrole (CLAUDE.md harde checks; open item 2026-07-13). Pure functie:
    de aanroeper (app/documenten/boekvoorstel.py) levert het gevalideerde factuur-IBAN uit de
    extractie en de vertrouwde set (app/documenten/leverancier_iban.py — RLZ-seed/baseline/
    bevestigd) van vóór een eventuele baseline-vastlegging.

    Regels op het geldpad, geen gok: (1) IBAN in de vertrouwde set -> OK — de set is meerwaardig,
    want meerdere bevestigde rekeningen per leverancier (G-rekening/WKA, gesplitste betaling) is
    in de bouwketen de NORM, geen wissel-signaal. (2) Set leeg (nieuwe leverancier, geen
    RLZ-seed) -> baseline vastgelegd, zichtbaar ter bevestiging, NIET blokkeren — er is niets om
    mee te vergelijken. (3) IBAN wijkt af van een niet-lege set -> HARD blokkeren: pas na
    menselijke bevestiging (leverancier_iban.bevestig_iban) hoort de nieuwe rekening erbij.
    (4) Fail-closed: kon de RLZ-seed niet opgehaald worden terwijl er wél een factuur-IBAN te
    toetsen is (`seed_mislukt`), dan blokkeert deze check op eigen titel — een wissel is dan niet
    uit te sluiten; nooit leunen op het toeval dat de duplicaatcheck óók blokkeert.
    Meldingen tonen het IBAN gemaskeerd (privacy — het volledige nummer staat op de
    factuur-preview zelf)."""
    if factuur_iban is None:
        return CheckResultaat(
            "IBAN-wissel", True, "Geen (geldig) IBAN op de factuur gelezen — geen wisselcontrole mogelijk"
        )
    if factuur_iban in vertrouwde_ibans:
        return CheckResultaat(
            "IBAN-wissel", True, f"IBAN {masker_iban(factuur_iban)} komt overeen met een vertrouwde rekening"
        )
    if seed_mislukt:
        return CheckResultaat(
            "IBAN-wissel",
            False,
            "IBAN-referentie kon niet worden opgehaald uit RLZ — een IBAN-wissel is niet uit te "
            "sluiten; probeer opnieuw of bevestig het rekeningnummer expliciet",
        )
    if not vertrouwde_ibans:
        if baseline_vastgelegd:
            return CheckResultaat(
                "IBAN-wissel",
                True,
                f"Eerste IBAN voor deze crediteur ({masker_iban(factuur_iban)}) vastgelegd als "
                "baseline — controleer het rekeningnummer op de factuur",
            )
        return CheckResultaat(
            "IBAN-wissel", True, "Nog geen vertrouwde rekeningen bekend voor deze crediteur — niets te vergelijken"
        )
    return CheckResultaat(
        "IBAN-wissel",
        False,
        f"IBAN op de factuur ({masker_iban(factuur_iban)}) wijkt af van de vertrouwde rekening(en) "
        "van deze crediteur — mogelijke IBAN-wissel; bevestig het nieuwe rekeningnummer expliciet "
        "voordat er geboekt kan worden",
    )


def voer_harde_checks_uit(
    *,
    client: RlzClient,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[CheckRegel],
    eigen_rlz_document_id: uuid.UUID,
    project_verplicht: bool = False,
    factuur_iban: str | None = None,
    vertrouwde_ibans: set[str] | None = None,
    iban_baseline_vastgelegd: bool = False,
    iban_seed_mislukt: bool = False,
) -> CheckRapport:
    """Alle harde checks (CLAUDE.md: "áltijd blokkerend"), in vaste volgorde zodat de UI
    consistent dezelfde vier rijen toont. Verplichte-velden staat vóórop: als die al faalt, zijn
    de andere checks vaak ook zinloos (bv. geen totaalbedrag -> regeltelling kan niet zinvol
    getoetst worden) — de UI toont ze desondanks alle vier, nooit stil overslaan.
    `project_verplicht` komt uit de administratie-instelling (design-pass taak 4) — alleen dan
    telt een ontbrekend project per regel als blokkerend. `factuur_iban`/`vertrouwde_ibans`/
    `iban_baseline_vastgelegd` komen uit de orkestratie in app/documenten/boekvoorstel.py
    (extractie + leverancier_iban-set)."""
    return CheckRapport(
        (
            check_verplichte_velden(
                vendor_id=vendor_id,
                referentie=referentie,
                factuurdatum=factuurdatum,
                totaalbedrag=totaalbedrag,
                regels=regels,
                project_verplicht=project_verplicht,
            ),
            check_regeltelling(totaalbedrag=totaalbedrag, regels=regels),
            check_iban_wissel(
                factuur_iban=factuur_iban,
                vertrouwde_ibans=vertrouwde_ibans or set(),
                baseline_vastgelegd=iban_baseline_vastgelegd,
                seed_mislukt=iban_seed_mislukt,
            ),
            check_duplicaat(
                client=client,
                vendor_id=vendor_id,
                referentie=referentie,
                totaalbedrag=totaalbedrag,
                eigen_rlz_document_id=eigen_rlz_document_id,
            ),
        )
    )
