from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.documenten.regelsom import (
    REDEN_BTW_PER_REGEL_ONTBREEKT,
    REDEN_GEEN_REGELS,
    REDEN_NETTO_ONTBREEKT,
    toets_regelsom,
)
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
    # Punt 14 (28-08): oranje SIGNAAL — ok=True (geen blokkade) maar de controleur moet kijken; het
    # controlescherm toont 'm oranje i.p.v. groen. Alleen gezet door checks die dat bewust doen.
    signaal: bool = False


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
        melding = f"Ontbrekend: {', '.join(ontbrekend)}"
        if any(o.startswith("project (regel") for o in ontbrekend):
            # B3 (04-09): handelingsperspectief — één project per regel óf de projectverdeling
            # (vaste regels en/of pro rato omzet) die élke regel zonder project een project geeft.
            melding += ' — kies per regel een project óf gebruik "Verdelen over projecten…" onder de boekingsregels'
        return CheckResultaat("Verplichte velden", False, melding)
    return CheckResultaat("Verplichte velden", True, "Alle verplichte velden zijn ingevuld")


def check_afdeling(
    *,
    afdelingen_ingeschakeld: bool,
    afdeling_id: object | None,
    afdeling_actief: bool | None,
    afdeling_naam: str | None,
    administratie_naam: str | None,
) -> CheckResultaat:
    """Blok A 28-08 (mockup afdelingen.html §2): staat de administratie-toggle aan, dan is een
    ACTIEVE afdeling op het document verplicht — ontbreekt ze of is ze gearchiveerd, dan blokkeert
    boeken én ter accordering aanbieden. Toggle uit = check zwijgt (altijd ok)."""
    if not afdelingen_ingeschakeld:
        return CheckResultaat("Afdeling", True, "Afdelingen niet van toepassing voor deze administratie")
    wie = f" voor {administratie_naam}" if administratie_naam else ""
    if afdeling_id is None:
        return CheckResultaat("Afdeling", False, f"Afdeling ontbreekt — verplicht{wie}")
    if afdeling_actief is None:
        return CheckResultaat("Afdeling", False, "Gekozen afdeling bestaat niet (meer) — kies een andere afdeling")
    if not afdeling_actief:
        return CheckResultaat(
            "Afdeling", False, f"Afdeling '{afdeling_naam}' is gearchiveerd — kies een actieve afdeling"
        )
    return CheckResultaat("Afdeling", True, f"Afdeling gekozen — {afdeling_naam}")


# Betaaltermijn waarboven de vervaldatum als implausibel geldt (C1 26-08): een scan die per
# ongeluk een jaartal/andere datum als vervaldatum aanwijst valt zo op — signaal, geen blokkade.
VERVALDATUM_TERMIJN_SIGNAAL_DAGEN = 90


def check_vervaldatum(*, factuurdatum: date | None, vervaldatum: date | None) -> CheckResultaat:
    """Deterministische kopveld-check (C1 26-08): een vervaldatum vóór de factuurdatum is
    onmogelijk en blokkeert (de controleur corrigeert of leegt het veld); leeg is toegestaan —
    RLZ leidt de DueDate dan zelf af uit de betaaltermijn van de crediteur."""
    naam = "Vervaldatum"
    if vervaldatum is None or factuurdatum is None:
        return CheckResultaat(naam, True, "Geen vervaldatum opgegeven (RLZ leidt 'm af uit de betaaltermijn)")
    if vervaldatum < factuurdatum:
        return CheckResultaat(
            naam,
            False,
            f"Vervaldatum {vervaldatum.isoformat()} ligt vóór de factuurdatum {factuurdatum.isoformat()}",
        )
    return CheckResultaat(
        naam, True, f"Vervaldatum {vervaldatum.isoformat()} (termijn {(vervaldatum - factuurdatum).days} dagen)"
    )


def vervaldatum_signaal(*, factuurdatum: date | None, vervaldatum: date | None) -> str | None:
    """Oranje signaal (geen blokkade): betaaltermijn langer dan VERVALDATUM_TERMIJN_SIGNAAL_DAGEN."""
    if vervaldatum is None or factuurdatum is None or vervaldatum < factuurdatum:
        return None
    termijn = (vervaldatum - factuurdatum).days
    if termijn > VERVALDATUM_TERMIJN_SIGNAAL_DAGEN:
        return f"Betaaltermijn van {termijn} dagen is ongebruikelijk lang — controleer de vervaldatum"
    return None


def is_buitenland_tarief(naam: str | None) -> bool:
    """Deterministisch op RLZ's tarief-naamconventie "<land/zone>, <omschrijving>": het prefix
    vóór de eerste komma ≠ NL = EU-/Ex-EU-/buitenland-tarief ("EU, Producten Hoog tarief",
    "Ex EU, …", "EU + Ex-EU, …", landcodes zoals 'DE'). Zonder komma-prefix geen uitspraak
    (nooit vals signaleren op een vrije naam) — geverifieerd tegen de gesyncte taxrate_cache
    (verzamelrun 31-08 blok A)."""
    if not naam or "," not in naam:
        return False
    prefix = naam.split(",", 1)[0].strip().upper()
    return bool(prefix) and prefix != "NL"


def check_buitenland_tarief_crediteurkaart(
    *,
    regels: list[CheckRegel],
    taxrate_namen: dict[uuid.UUID, str],
    factuur_btw_nummer: str | None,
) -> CheckResultaat:
    """Casus Labo Derva 31-08: RLZ weigert de boekactie (17) van een EU-/buitenland-tarief met
    400 "ongeldig belastingtarief" zolang de CREDITEURKAART in RLZ geen land/btw-nummer draagt —
    een crediteur-datakwaliteitsfout, geen tarief-fout. Land en btw-nummer van de crediteur zijn
    via de RLZ-API níét leesbaar (probe 31-08: Vendors/{id} — óók fields=all — en
    Vendors/{id}/Addresses ($expand=Country blijft {}) dragen geen van beide; api-verkenning
    "EU-tarieven op PurchaseInvoice-Actions"), dus dit is bewust een ONVOORWAARDELIJK oranje
    signaal bij élk buitenland-tarief: waarschuwen vóór de boekpoging, nooit blokkeren."""
    naam = "Btw-tarief buitenland"
    treffers = [
        (i, taxrate_namen.get(regel.taxrate_id, ""))
        for i, regel in enumerate(regels, start=1)
        if regel.taxrate_id is not None and is_buitenland_tarief(taxrate_namen.get(regel.taxrate_id))
    ]
    if not treffers:
        return CheckResultaat(naam, True, "Geen EU-/buitenland-tarief op de regels")
    plekken = ", ".join(f"regel {i} ('{tarief}')" for i, tarief in treffers)
    hint = f" Btw-nummer uit de factuur: {factuur_btw_nummer}." if factuur_btw_nummer else ""
    return CheckResultaat(
        naam,
        True,
        f"EU-/buitenland-tarief op {plekken} — controleer vóór het boeken dat de crediteurkaart in "
        "RLZ een land én btw-nummer draagt (via de API niet controleerbaar); ontbreekt dat, dan "
        f"weigert RLZ het boeken met 'ongeldig belastingtarief'.{hint}",
        signaal=True,
    )


def check_regeltelling(
    *,
    totaalbedrag: Decimal | None,
    regels: list[CheckRegel],
    totaal_excl: Decimal | None = None,
    factuur_btw: Decimal | None = None,
) -> CheckResultaat:
    """Regeltelling vs totaal — sinds 04-09 (Huvanco-casus) EXPLICIET over welke basis vergeleken
    wordt, via dezelfde beslisboom als de veldvoorstel-badge (app/documenten/regelsom.py):
    btw per regel compleet → Σ(netto+btw) vs `totaalbedrag` (incl); anders Σnetto vs `totaal_excl`;
    anders Σnetto + `factuur_btw` vs incl; anders een leesbare blokkade — nooit meer stil Σnetto
    (feitelijk exclusief) tegen een inclusief totaal.

    `totaalbedrag` is het boekvoorstel-veld "Totaalbedrag (incl. btw)" — dat vult/wijzigt de mens en
    blijft leidend voor de incl-kant. `totaal_excl`/`factuur_btw` zijn de GELEZEN totalen uit het
    laatste veldvoorstel (het boekvoorstel draagt geen excl-veld; de aanroeper in boekvoorstel.py
    levert ze aan). Negatieve regels (korting/rabat/credit) tellen gewoon mee."""
    naam = "Regeltelling vs totaal"
    if totaalbedrag is None and totaal_excl is None:
        return CheckResultaat(naam, False, "Geen factuurtotaal ingevuld om tegen te controleren")
    toets = toets_regelsom(
        netto=[r.netto_bedrag for r in regels],
        btw=[r.btw_bedrag for r in regels],
        totaal_incl=totaalbedrag,
        totaal_excl=totaal_excl,
        factuur_btw=factuur_btw,
        tolerantie=_ROND_TOLERANTIE,
    )
    if toets.reden == REDEN_GEEN_REGELS:
        return CheckResultaat(naam, False, "Geen boekingsregels om tegen het factuurtotaal te tellen")
    if toets.reden == REDEN_NETTO_ONTBREEKT:
        return CheckResultaat(naam, False, "Netto bedrag ontbreekt op een regel — regeltelling niet toetsbaar")
    if toets.reden == REDEN_BTW_PER_REGEL_ONTBREEKT:
        regelnrs = ", ".join(str(n) for n in toets.regels_zonder_btw)
        return CheckResultaat(
            naam,
            False,
            f"Btw per regel ontbreekt (regel {regelnrs}) en er is geen totaal excl. btw gelezen — vul de btw "
            f"per regel of het totaal excl. in; de regels (netto € {toets.netto_som}) zijn niet tegen het "
            f"totaal incl. (€ {totaalbedrag}) te toetsen",
        )
    if not toets.toetsbaar:
        return CheckResultaat(naam, False, "Geen factuurtotaal ingevuld om tegen te controleren")

    # De melding benoemt altijd welke basis vergeleken is (netto-vs-excl, netto+btw-vs-incl of
    # netto+factuur-btw-vs-incl) — de controleur ziet zo direct wat er opgeteld is.
    basis_tekst = "totaal incl." if toets.basis == "incl" else "totaal excl."
    btw_per_regel_compleet = all(r.btw_bedrag is not None for r in regels)
    if toets.basis == "excl":
        som_tekst = f"netto € {toets.regelsom}"
    elif btw_per_regel_compleet:
        som_tekst = f"netto + btw € {toets.regelsom}"
    else:
        som_tekst = f"netto € {toets.netto_som} + factuur-btw € {toets.btw_bijgeteld} = € {toets.regelsom}"
    if toets.wijkt_af:
        return CheckResultaat(
            naam,
            False,
            f"Som van de regels ({som_tekst}) wijkt € {toets.verschil} af van het {basis_tekst} (€ {toets.vergelijk})",
        )
    return CheckResultaat(
        naam, True, f"Som van de regels ({som_tekst}) komt overeen met het {basis_tekst} (€ {toets.vergelijk})"
    )


def check_duplicaat(
    *,
    client: RlzClient,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
    eigen_rlz_document_id: uuid.UUID,
    uitgezonderde_rlz_document_ids: frozenset[uuid.UUID] = frozenset(),
    historie_treffers: Sequence[dict] = (),
) -> CheckResultaat:
    """Eigen duplicaatquery (RLZ's actie 138 geeft geen bruikbaar signaal, besluit 0013): zoekt
    op Entity+Reference(afgekapt op 30 tekens, zie RlzClient.find_purchase_invoices_by_reference)
    +bedrag. Een hit op het EIGEN client-GUID (`eigen_rlz_document_id`) is geen duplicaat maar de
    eigen, eventueel al eerder gelukte PUT — anders zou een retry na boeken_mislukt zichzelf als
    duplicaat blokkeren. `uitgezonderde_rlz_document_ids` (tegenboek-pad, mockup 22-08): bij
    "tegenboeken én opnieuw boeken" heeft de herboeking bewust dezelfde Entity+Reference+bedrag
    als het origineel — alle eerdere (her)boekings- en tegenboekings-GUID's van hetzélfde
    document zijn dan geen duplicaat maar de gekoppelde correctieketen (zichtbaar in de
    tijdlijn); élk ander RLZ-document blijft onverkort blokkerend.

    Een falende RLZ-aanroep hier mag nooit als kale 500 bij de gebruiker terechtkomen — zonder
    duplicaatcheck is boeken net zo onverantwoord als met een echte duplicaat-hit, dus dit
    resultaat blijft blokkerend, maar wél als een normaal (herkenbaar) checkresultaat i.p.v. een
    onafgevangen exception die de hele PUT/checks-aanroep laat crashen.

    `historie_treffers` (Odoo-slotstuk 04-09, `documenten/duplicaat_historie.py`): documenten die vóór een overstap
    al in Reeleezee geboekt zijn — de live query van de Odoo-backend ziet die niet. Aanwezig = rood mét boekstuk,
    ongeacht de live uitkomst (dedup op `id`, zelfde uitzonderingen)."""
    if vendor_id is None or not referentie:
        return CheckResultaat("Duplicaatcheck", False, "Kan niet controleren zonder crediteur en referentie")
    bedrag = float(totaalbedrag) if totaalbedrag is not None else None
    uitgezonderd = {str(eigen_rlz_document_id)} | {str(i) for i in uitgezonderde_rlz_document_ids}
    historie = [t for t in historie_treffers if str(t.get("id")) not in uitgezonderd]
    try:
        gevonden = client.find_purchase_invoices_by_reference(
            vendor_id=vendor_id, reference=referentie, total_amount=bedrag
        )
    except RlzApiError as exc:
        return CheckResultaat(
            "Duplicaatcheck", False, _met_historie(f"Duplicaatcheck kon niet uitgevoerd worden: {exc}", historie)
        )
    except Exception as exc:  # noqa: BLE001 — bewust breed: elke RLZ-connectiefout blokkeert, crasht nooit
        return CheckResultaat(
            "Duplicaatcheck", False, _met_historie(f"Duplicaatcheck kon niet uitgevoerd worden: {exc}", historie)
        )
    historie_ids = {str(t.get("id")) for t in historie}
    anderen = [f for f in gevonden if f.get("id") not in uitgezonderd and str(f.get("id")) not in historie_ids]
    if anderen or historie:
        delen = []
        if anderen:
            delen.append(
                f"{len(anderen)} bestaande factuur/facturen in RLZ met dezelfde crediteur, referentie en bedrag"
            )
        if historie:
            delen.append(historie_melding(historie))
        return CheckResultaat("Duplicaatcheck", False, "; ".join(delen))
    return CheckResultaat("Duplicaatcheck", True, "Geen bestaande factuur met dezelfde crediteur/referentie/bedrag")


def historie_melding(historie: Sequence[dict]) -> str:
    """Rode melding voor treffers uit de eigen historie (Odoo-slotstuk 04-09): al geboekt in Reeleezee vóór de
    overstap, mét boekstuknummer(s) zodat de controleur 'm in RLZ terugvindt."""
    from app.documenten.duplicaat_historie import boekstukken

    n = len(historie)
    return (
        f"{n} factu{'ur' if n == 1 else 'ren'} met dezelfde crediteur, referentie en bedrag al geboekt in Reeleezee "
        f"vóór de overstap (boekstuk {boekstukken(list(historie))})"
    )


def _met_historie(melding: str, historie: Sequence[dict]) -> str:
    return f"{melding}; {historie_melding(historie)}" if historie else melding


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
    uitgezonderde_rlz_document_ids: frozenset[uuid.UUID] = frozenset(),
    project_verplicht: bool = False,
    factuur_iban: str | None = None,
    vertrouwde_ibans: set[str] | None = None,
    iban_baseline_vastgelegd: bool = False,
    iban_seed_mislukt: bool = False,
    eigen_btw_nummer: str | None = None,
    btw_per_vendor: dict[str, str] | None = None,
    vervaldatum: date | None = None,
    taxrate_namen: dict[uuid.UUID, str] | None = None,
    totaal_excl: Decimal | None = None,
    factuur_btw: Decimal | None = None,
    historie_treffers: Sequence[dict] = (),
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
            check_regeltelling(
                totaalbedrag=totaalbedrag, regels=regels, totaal_excl=totaal_excl, factuur_btw=factuur_btw
            ),
            check_vervaldatum(factuurdatum=factuurdatum, vervaldatum=vervaldatum),
            check_buitenland_tarief_crediteurkaart(
                regels=regels,
                taxrate_namen=taxrate_namen or {},
                factuur_btw_nummer=eigen_btw_nummer,
            ),
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
                uitgezonderde_rlz_document_ids=uitgezonderde_rlz_document_ids,
                historie_treffers=historie_treffers,
            ),
            check_duplicaat_over_crediteuren(
                client=client,
                vendor_id=vendor_id,
                referentie=referentie,
                totaalbedrag=totaalbedrag,
                eigen_btw_nummer=eigen_btw_nummer,
                btw_per_vendor=btw_per_vendor or {},
                eigen_rlz_document_id=eigen_rlz_document_id,
                uitgezonderde_rlz_document_ids=uitgezonderde_rlz_document_ids,
            ),
        )
    )


def check_duplicaat_over_crediteuren(
    *,
    client: RlzClient,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
    eigen_btw_nummer: str | None,
    btw_per_vendor: dict[str, str],
    eigen_rlz_document_id: uuid.UUID,
    uitgezonderde_rlz_document_ids: frozenset[uuid.UUID] = frozenset(),
) -> CheckResultaat:
    """Punt 14 (opruimrun 28-08, besluiten Peter 27-08) — bovenop de harde zelfde-crediteur-check:
    zoekt Reference+bedrag over ÁLLE crediteuren van de administratie (geen Entity-filter, mét
    `$expand=Entity`). Treffer bij een ÁNDERE crediteur:
    - mét hetzelfde btw-nummer (factuur-btw-nummer == bekend btw-nummer van die crediteur) →
      BLOKKEREND ("drievoudige match btw-nummer + factuurnummer + bedrag": dezelfde factuur staat al
      geboekt onder een dubbele crediteur — mens wijst af met één klik, nooit auto-verwijderen);
    - anders → ORANJE SIGNAAL (ok=True, signaal=True): zelfde referentie + bedrag bij een andere
      crediteur, controleur kijkt.
    Zonder referentie/bedrag niet toetsbaar (groen — de gewone duplicaatcheck blokkeert dan al op
    ontbrekende gegevens). Een RLZ-fout hier is een signaal, geen blokkade: de harde zelfde-
    crediteur-check blokkeert al bij onbereikbaarheid."""
    naam = "Duplicaat bij andere crediteur"
    if not referentie or totaalbedrag is None:
        return CheckResultaat(naam, True, "Niet toetsbaar zonder referentie en totaalbedrag")
    try:
        gevonden = client.find_purchase_invoices_by_reference(
            vendor_id=None, reference=referentie, total_amount=float(totaalbedrag), expand_entity=True
        )
    except Exception as exc:  # noqa: BLE001 — bewust breed: signaal, nooit een crash
        return CheckResultaat(naam, True, f"Kon niet over crediteuren heen toetsen: {exc}", signaal=True)
    uitgezonderd = {str(eigen_rlz_document_id)} | {str(i) for i in uitgezonderde_rlz_document_ids}
    anderen: list[dict] = []
    for f in gevonden:
        if f.get("id") in uitgezonderd:
            continue
        entity = f.get("Entity") or {}
        entity_id = str(entity.get("id") or "")
        if vendor_id is not None and entity_id == str(vendor_id):
            continue  # zelfde crediteur = domein van check_duplicaat
        anderen.append(f)
    if not anderen:
        return CheckResultaat(naam, True, "Geen factuur met dezelfde referentie en bedrag bij een andere crediteur")
    if eigen_btw_nummer:
        zelfde_btw = [
            f for f in anderen if btw_per_vendor.get(str((f.get("Entity") or {}).get("id") or "")) == eigen_btw_nummer
        ]
        if zelfde_btw:
            namen = sorted({str((f.get("Entity") or {}).get("Name") or "onbekend") for f in zelfde_btw})
            return CheckResultaat(
                naam,
                False,
                f"{len(zelfde_btw)} bestaande factuur/facturen met hetzelfde btw-nummer, factuurnummer en bedrag "
                f"onder een andere crediteur ({', '.join(namen)}) — dubbele crediteur in RLZ; wijs dit "
                "document af of kies die crediteur",
            )
    namen = sorted({str((f.get("Entity") or {}).get("Name") or "onbekend") for f in anderen})
    return CheckResultaat(
        naam,
        True,
        f"Zelfde referentie en bedrag bij een andere crediteur ({', '.join(namen)}) — controleer op een "
        "dubbele crediteur",
        signaal=True,
    )
