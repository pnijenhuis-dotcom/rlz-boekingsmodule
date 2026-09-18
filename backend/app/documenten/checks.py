from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.documenten.regelsom import (
    REDEN_BTW_PER_REGEL_ONTBREEKT,
    REDEN_GEEN_REGELS,
    REDEN_NETTO_ONTBREEKT,
    btw_uit_tarief,
    marge_voor,
    toets_regelsom,
    verklarende_percentages,
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
class CheckActie:
    """Handeling op een check-rij (opdracht Peter 18-09 "btw volgt tarief"): `code` = "btw_in_kosten" (regel 2:
    netto := netto + btw, btw := 0, tarief := het 0 %-tarief `taxrate_id`) of "zet_tarief" (het ene RLZ-tarief dat de
    factuur-btw binnen de marge verklaart). `regel` is 1-gebaseerd (zoals de meldingen). De frontend voert de
    handeling uit op de regelstate en slaat op — de check draait daarna opnieuw; de server vertrouwt nooit de knop."""

    code: str
    label: str
    regel: int
    taxrate_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CheckResultaat:
    naam: str
    ok: bool
    melding: str
    # Punt 14 (28-08): oranje SIGNAAL — ok=True (geen blokkade) maar de controleur moet kijken; het
    # controlescherm toont 'm oranje i.p.v. groen. Alleen gezet door checks die dat bewust doen.
    signaal: bool = False
    # 18-09: acties op de rij ("signalering zonder handeling is niet af") — alleen bij een blokkerende uitkomst.
    acties: tuple[CheckActie, ...] = ()


@dataclass(frozen=True)
class CheckRapport:
    resultaten: tuple[CheckResultaat, ...]
    # Boeken sneller (18-09, checks_extern.py): wanneer het EXTERNE deel (IBAN-seed, duplicaatquery's) voor het laatst
    # écht bij RLZ/Odoo is opgehaald en of dat uit de cache kwam — de UI toont "gecontroleerd HH:MM" op die rijen.
    extern_gecontroleerd_op: datetime | None = None
    extern_uit_cache: bool = False
    # CACHE-modus zonder geldige cache: de externe rijen staan op "loopt nog" (blokkerend) — de frontend start de
    # externe run apart. Nooit boeken op zo'n rapport (geblokkeerd is dan al True).
    extern_nog_niet: bool = False

    @property
    def geblokkeerd(self) -> bool:
        return any(not r.ok for r in self.resultaten)


_MAX_LOSSE_REGELNUMMERS = 4


def _regelplekken(nummers: list[int], totaal: int) -> str:
    """Leesbare plek-aanduiding: "(regel 3)", "(alle 11 regels)", "(regel 1, 3, 5)" of "(7 regels: 1, 2, 3, 4, …)"."""
    if len(nummers) == 1:
        return f"(regel {nummers[0]})"
    if totaal > 1 and len(nummers) == totaal:
        return f"(alle {totaal} regels)"
    if len(nummers) <= _MAX_LOSSE_REGELNUMMERS:
        return f"(regel {', '.join(str(n) for n in nummers)})"
    kop = ", ".join(str(n) for n in nummers[:_MAX_LOSSE_REGELNUMMERS])
    return f"({len(nummers)} regels: {kop}, …)"


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
    # Blok 4d (08-09, Spot Services 12 regels): per veld GEAGGREGEERD i.p.v. per regel opgesomd — "grootboekrekening
    # (alle 11 regels)" / "(regel 1, 3, 5)" i.p.v. 33 losse fragmenten. Eén regel houdt de bestaande vorm "(regel i)".
    per_veld: dict[str, list[int]] = {"grootboekrekening": [], "btw-code": [], "netto bedrag": [], "project": []}
    for i, regel in enumerate(regels, start=1):
        if regel.ledger_id is None:
            per_veld["grootboekrekening"].append(i)
        if regel.taxrate_id is None:
            per_veld["btw-code"].append(i)
        if regel.netto_bedrag is None:
            per_veld["netto bedrag"].append(i)
        if project_verplicht and regel.project_id is None:
            per_veld["project"].append(i)
    for veld, nummers in per_veld.items():
        if nummers:
            ontbrekend.append(f"{veld} {_regelplekken(nummers, len(regels))}")

    if ontbrekend:
        melding = f"Ontbrekend: {', '.join(ontbrekend)}"
        if per_veld["project"]:
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


def check_project_afgesloten(
    *, regels: Sequence[CheckRegel], afgesloten: Mapping[uuid.UUID, tuple[str | None, date | None]]
) -> CheckResultaat | None:
    """Blok 3 18-09 (Peter: "als een project afgesloten is kan het uit de lijst"): een regel op een AFGESLOTEN project =
    ORANJE SIGNAAL (ok=True, signaal=True) — nagekomen facturen bestaan, dus nooit blokkerend. `afgesloten` =
    project_id →
    (naam, afgesloten_op) voor de projecten die de aanroeper als afgesloten kent. Geen treffer = None (geen rij: de
    check is
    pas relevant als hij iets te zeggen heeft)."""
    treffers: list[str] = []
    gezien: set[uuid.UUID] = set()
    for regel in regels:
        pid = regel.project_id
        if pid is None or pid in gezien or pid not in afgesloten:
            continue
        gezien.add(pid)
        naam, op = afgesloten[pid]
        treffers.append(f"{naam or pid}" + (f" (afgesloten op {op.strftime('%d-%m-%Y')})" if op else " (afgesloten)"))
    if not treffers:
        return None
    return CheckResultaat(
        "Project afgesloten",
        True,
        "Project afgesloten: "
        + "; ".join(treffers)
        + " — nagekomen factuur? Boeken kan; heropen het project als het werk toch doorloopt.",
        signaal=True,
    )


def check_betaalstatus_declaraties(*, kanaal: str | None, betaalstatus: str | None) -> CheckResultaat:
    """Harde check "Betaalstatus (declaraties)" (blok 3 bundel 08-09): een document uit het declaraties@-kanaal is al
    door een medewerker betaald — boeken ZONDER betaalstatus zou 'm in RLZ's betaallijst zetten (dubbele betaling).
    Blokkerend zolang de betaalstatus leeg of ongeldig is; buiten het declaraties-kanaal niet van toepassing (groen),
    een
    gezette status op een gewoon document is informatief groen (mens/kanaal/factuur staan erop)."""
    from app.documenten import betaalstatus as bs  # lokaal: pure module, houdt checks.py vrij van kringen

    naam = "Betaalstatus (declaraties)"
    if kanaal != bs.KANAAL_DECLARATIES:
        if betaalstatus and bs.is_geldig(betaalstatus):
            return CheckResultaat(
                naam, True, f"Betaalstatus {bs.canoniek(betaalstatus)!r} gaat mee naar de boekhouding"
            )
        return CheckResultaat(naam, True, "Niet van toepassing — geen declaratie")
    if not betaalstatus:
        return CheckResultaat(
            naam, False, "Declaratie zonder betaalstatus — kies hoe deze al betaald is (bijv. Betaald per bank)"
        )
    if not bs.is_geldig(betaalstatus):
        return CheckResultaat(naam, False, f"Onbekende betaalstatus {betaalstatus!r} — kies één van de RLZ-waarden")
    if bs.canoniek(betaalstatus) == bs.NOG_TE_BETALEN:
        return CheckResultaat(
            naam, False, "Declaratie staat op 'Nog te betalen' — een declaratie is al betaald; kies de betaalwijze"
        )
    return CheckResultaat(naam, True, f"Declaratie — betaalstatus {bs.canoniek(betaalstatus)!r}")


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


@dataclass(frozen=True)
class TariefInfo:
    """Eén gesynct btw-tarief zoals de tarief-check 'm nodig heeft (uit `taxrate_cache`, lokaal — geen RLZ-call):
    percentage als fractie (0.21), naam, en de RLZ-vlaggen `IsRelayed` (verlegd) / `IsExcempt` (vrijgesteld) /
    `IsFavorite`; `buitenland` = naam-prefix ≠ NL (`is_buitenland_tarief`)."""

    percentage: Decimal | None
    naam: str | None = None
    verlegd: bool = False
    vrijgesteld: bool = False
    favoriet: bool = False
    buitenland: bool = False

    @property
    def verwacht_nul(self) -> bool:
        """Verlegd, vrijgesteld en EU-/buitenland-tarieven dragen per definitie géén btw-bedrag op de regel."""
        nul = self.percentage is not None and self.percentage == 0
        return self.verlegd or self.vrijgesteld or self.buitenland or nul


NAAM_BTW_TARIEF = "Btw-bedrag past bij tarief"
ACTIE_BTW_IN_KOSTEN = "btw_in_kosten"
ACTIE_ZET_TARIEF = "zet_tarief"


def _pct_tekst(p: Decimal | None) -> str:
    if p is None:
        return "?"
    v = p * 100
    return f"{int(v)} %" if v == v.to_integral_value() else f"{v.normalize()} %"


def nul_tarief_voor(tarieven: Mapping[uuid.UUID, TariefInfo], *, huidig: uuid.UUID | None = None) -> uuid.UUID | None:
    """Het 0 %-tarief voor "btw in kosten": het huidige tarief als dat al een NL-0 %-tarief is, anders de RLZ-favoriet
    onder de NL-0 %-tarieven (niet verlegd, niet buitenland, niet vrijgesteld), anders de eerste op naam. None als de
    administratie geen zo'n tarief heeft (dan alleen de melding, geen knop)."""

    def nl_nul(t: TariefInfo) -> bool:
        return t.percentage is not None and t.percentage == 0 and not (t.verlegd or t.buitenland or t.vrijgesteld)

    if huidig is not None and huidig in tarieven and nl_nul(tarieven[huidig]):
        return huidig
    kandidaten = [(tid, t) for tid, t in tarieven.items() if nl_nul(t)]
    if not kandidaten:
        return None
    kandidaten.sort(key=lambda kt: (not kt[1].favoriet, kt[1].naam or "", str(kt[0])))
    return kandidaten[0][0]


def check_btw_past_bij_tarief(
    *,
    regels: list[CheckRegel],
    tarieven: Mapping[uuid.UUID, TariefInfo],
    samengevoegd_n: int = 1,
) -> CheckResultaat:
    """HARDE check (opdracht Peter 18-09, casus Rituals 88-186308: 0 % · NL, Nul mét € 20,24 btw op € 96,36 — 11/11
    groen, Boeken actief): per regel |btw − netto × percentage| ≤ marge, marge = 1 cent × aantal samengevoegde
    factuurregels (min 1, max 5; `regelsom.marge_voor`). Vervangt de grijze hint "tarief geeft € … — factuur leidend"
    (REGELRIJ-UI 25-08 (b), HERZIEN 18-09) volledig. Buiten de marge = ROOD mét twee acties: "Btw in kosten (0 %)"
    (regel 2: netto := netto + btw, btw := 0 — de niet-aftrekbare btw zit in de kosten) en "Zet N %" (het ene RLZ-tarief
    dat de factuur-btw binnen de marge verklaart; géén of meerdere kandidaten → alleen de eerste actie). Verlegd/
    vrijgesteld/buitenland-tarief = verwacht 0,00 (daar staat immers geen btw op de factuur). Een regel zonder tarief,
    netto of btw-bedrag telt hier niet (verplichte velden/regeltelling vangen dat); een tarief dat niet in de cache
    staat is niet toetsbaar en wordt benoemd. Lokaal, geen RLZ-call — draait óók in de storings-tak en op het
    autoboek-pad (rood = niet boeken)."""
    marge = marge_voor(samengevoegd_n)
    marge_ct = int(marge * 100)
    fouten: list[str] = []
    acties: list[CheckActie] = []
    niet_toetsbaar: list[int] = []
    getoetst = 0
    for i, regel in enumerate(regels, start=1):
        if regel.taxrate_id is None or regel.netto_bedrag is None or regel.btw_bedrag is None:
            continue
        info = tarieven.get(regel.taxrate_id)
        if info is None or (info.percentage is None and not info.verwacht_nul):
            niet_toetsbaar.append(i)
            continue
        getoetst += 1
        verwacht = (
            Decimal("0.00") if info.verwacht_nul else btw_uit_tarief(regel.netto_bedrag, info.percentage or Decimal(0))
        )
        if abs(regel.btw_bedrag - verwacht) <= marge:
            continue
        pct_tekst = _pct_tekst(Decimal(0) if info.verwacht_nul else info.percentage)
        tarief_tekst = f"{pct_tekst} · {info.naam or regel.taxrate_id}"
        fouten.append(
            f"regel {i}: {tarief_tekst} met btw € {regel.btw_bedrag} op netto € {regel.netto_bedrag} — "
            f"verwacht € {verwacht}"
        )
        if regel.btw_bedrag != 0:
            nul = nul_tarief_voor(tarieven, huidig=regel.taxrate_id)
            acties.append(
                CheckActie(
                    ACTIE_BTW_IN_KOSTEN,
                    f"Btw in kosten (0 %) — regel {i}: netto € {regel.netto_bedrag + regel.btw_bedrag}, btw € 0,00",
                    i,
                    nul,
                )
            )
            # "Zet N %": precies één NL-percentage (niet verlegd/buitenland/vrijgesteld) verklaart de btw.
            kandidaten = {
                t.percentage
                for tid, t in tarieven.items()
                if t.percentage is not None and t.percentage != 0 and not (t.verlegd or t.buitenland or t.vrijgesteld)
            }
            treffers = verklarende_percentages(
                regel.netto_bedrag, regel.btw_bedrag, sorted(kandidaten), samengevoegd_n=samengevoegd_n
            )
            if len(treffers) == 1:
                p = treffers[0]
                opties = [
                    (tid, t)
                    for tid, t in tarieven.items()
                    if t.percentage == p and not (t.verlegd or t.buitenland or t.vrijgesteld)
                ]
                opties.sort(key=lambda kt: (not kt[1].favoriet, kt[1].naam or "", str(kt[0])))
                acties.append(CheckActie(ACTIE_ZET_TARIEF, f"Zet {_pct_tekst(p)} — regel {i}", i, opties[0][0]))
    if fouten:
        return CheckResultaat(
            NAAM_BTW_TARIEF,
            False,
            f"Btw-bedrag past niet bij het tarief (marge {marge_ct} ct): " + "; ".join(fouten)
            + ". Kies 'Btw in kosten (0 %)' als de btw niet aftrekbaar is (representatie, relatiegeschenken), of zet "
            "het tarief dat op de factuur staat.",
            acties=tuple(acties),
        )
    if niet_toetsbaar and not getoetst:
        return CheckResultaat(
            NAAM_BTW_TARIEF,
            True,
            f"Tarief zonder percentage in de gesyncte btw-codes (regel {', '.join(map(str, niet_toetsbaar))}) — "
            "niet toetsbaar",
        )
    if not getoetst:
        return CheckResultaat(NAAM_BTW_TARIEF, True, "Geen regel met tarief, netto én btw-bedrag om te toetsen")
    extra = ""
    if niet_toetsbaar:
        extra = f"; regel {', '.join(map(str, niet_toetsbaar))} niet toetsbaar (tarief zonder percentage)"
    return CheckResultaat(
        NAAM_BTW_TARIEF, True, f"Btw-bedrag volgt het tarief op {getoetst} regel(s) (marge {marge_ct} ct){extra}"
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
    factuurdatum: date | None = None,
    identiteit_vendor_ids: Sequence[uuid.UUID] = (),
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
    ongeacht de live uitkomst (dedup op `id`, zelfde uitzonderingen).

    Herstelrun 07-09 (blok 1b, casus Kempen Facilities 281637 / 2026-0322): de cloud-diagnose bewees dat deze
    check NIET faalde — beide tweede exemplaren zijn nooit in RLZ geboekt; de live check kan alleen zien wat al
    in RLZ staat (ook concepten), een tweede exemplaar dat nog in de module wacht is het domein van
    `check_duplicaat_module`. Verharding hier: het bedrag gaat als Decimal mee en wordt in de client cent-exact
    vergeleken (geen OData-float-`eq` meer), zodat een wankele float-match nooit een treffer verbergt.

    Zenvoices-casus 16-09 (Hello Kitchen / Kempen Facilities, blok B): de vergelijking loopt sinds 16-09 via
    `extern_bestaan.zoek_extern_bestaand` — letterlijke `Reference eq` PLUS kandidaten in ± 60 dagen rond de
    factuurdatum over álle crediteurrecords van dezelfde identiteit (`identiteit_vendor_ids`), client-side
    GENORMALISEERD vergeleken ("2 4594 001722" ≡ "24594001722"). Zelfde genormaliseerde referentie (met of zonder
    gelijk bedrag) = BLOKKEREND mét boekstuknummer; zelfde bedrag én datum ± 30 dagen bij een ander nummer = oranje
    signaal (mens kijkt). Concepten tellen mee (een Zenvoices-concept wordt straks geboekt)."""
    if vendor_id is None or not referentie:
        # Blok 3 herstelrun 08-09: benoem precies wat ontbreekt — een UBL draagt de referentie altijd, dan is
        # alleen de crediteur de open post (kies of maak 'm) en zegt de tekst niet meer "en referentie".
        ontbreekt = [naam for naam, leeg in (("crediteur", vendor_id is None), ("referentie", not referentie)) if leeg]
        tekst = f"Kan niet controleren zonder {' en '.join(ontbreekt)}"
        if vendor_id is None and referentie:
            tekst += f" — kies of maak de crediteur; referentie {referentie} is bekend"
        return CheckResultaat("Duplicaatcheck", False, tekst)
    bedrag = totaalbedrag
    uitgezonderd = {str(eigen_rlz_document_id)} | {str(i) for i in uitgezonderde_rlz_document_ids}
    historie = [t for t in historie_treffers if str(t.get("id")) not in uitgezonderd]
    from app.documenten import extern_bestaan  # lokaal: houdt checks.py puur importeerbaar in tests

    vendor_ids = list(dict.fromkeys([vendor_id, *identiteit_vendor_ids]))
    try:
        gevonden = extern_bestaan.zoek_extern_bestaand(
            client,
            vendor_ids=vendor_ids,
            referentie=referentie,
            totaalbedrag=bedrag,
            factuurdatum=factuurdatum,
            uitgezonderd_ids=uitgezonderd,
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
    anderen = [f for f in gevonden if str(f.get("id")) not in historie_ids]
    blokkerend = [f for f in anderen if f.get("match_basis") in extern_bestaan.BLOKKERENDE_BASES]
    signalen = [f for f in anderen if f.get("match_basis") == extern_bestaan.BASIS_BEDRAG_DATUM]
    if blokkerend or historie:
        delen = []
        if blokkerend:
            delen.append(
                f"{len(blokkerend)} bestaande factuur/facturen in RLZ met dezelfde crediteur en referentie — "
                + "; ".join(extern_bestaan.omschrijf_treffer(f) for f in blokkerend[:3])
            )
        if historie:
            delen.append(historie_melding(historie))
        return CheckResultaat("Duplicaatcheck", False, "; ".join(delen))
    if signalen:
        return CheckResultaat(
            "Duplicaatcheck",
            True,
            f"Geen factuur met dezelfde referentie, wél {len(signalen)} met hetzelfde bedrag rond dezelfde datum bij "
            "deze crediteur — controleer op een dubbel exemplaar: "
            + "; ".join(extern_bestaan.omschrijf_treffer(f) for f in signalen[:3]),
            signaal=True,
        )
    return CheckResultaat("Duplicaatcheck", True, "Geen bestaande factuur met dezelfde crediteur/referentie/bedrag")


NAAM_DUPLICAAT_MODULE = "Duplicaat (module)"

_CATEGORIE_TEKST = {
    "bestand": "hetzelfde bestand (sha256)",
    "referentie_bedrag": "dezelfde referentie en hetzelfde totaalbedrag",
    "crediteur_referentie": "dezelfde crediteur en dezelfde referentie (ander bedrag)",
}


def check_duplicaat_module(*, treffers: Sequence[object]) -> CheckResultaat:
    """HARDE check "Duplicaat (module)" (besluit Peter 07-09) — tegen onze EIGEN database, binnen de administratie,
    náást de live-RLZ-check: een ander niet-afgevoerd document met (a) hetzelfde bestand, (b) dezelfde
    genormaliseerde referentie + totaalbedrag over álle crediteur-records, of (c) dezelfde crediteur (vendor / KvK /
    btw / dubbel-cluster) + referentie bij een ander bedrag = BLOKKEREND. Pure functie: de aanroeper
    (app/documenten/boekvoorstel.py) levert de tegenhangers uit `duplicaat_module.treffers_voor_document`, waar de
    bundel-uitzondering (UBL+PDF) en de mens-afmelding ("Geen duplicaat") al zijn toegepast. Geen tegenhangers =
    groen. Geen RLZ/Odoo-call, dus deze check draait óók in de RLZ-storings-tak."""
    if not treffers:
        return CheckResultaat(
            NAAM_DUPLICAAT_MODULE,
            True,
            "Geen ander document in deze administratie met hetzelfde bestand, dezelfde referentie + bedrag of "
            "dezelfde crediteur + referentie",
        )
    delen: list[str] = []
    for t in treffers:
        categorie = getattr(t, "categorie", "")
        status = getattr(t, "status", None)
        status_tekst = status.value.replace("_", " ") if hasattr(status, "value") else str(status or "")
        tekst = _CATEGORIE_TEKST.get(categorie, categorie)
        delen.append(f"{getattr(t, 'bestandsnaam', '?')} ({status_tekst}) — {tekst}")
    n = len(treffers)
    return CheckResultaat(
        NAAM_DUPLICAAT_MODULE,
        False,
        f"{n} ander{'' if n == 1 else 'e'} document{'' if n == 1 else 'en'} in deze administratie: "
        + "; ".join(delen)
        + ' — voer dit document af als duplicaat, of meld het af als "geen duplicaat" (reden verplicht)',
    )


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
    client: RlzClient | None,
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
    identiteit_vendor_ids: Sequence[uuid.UUID] = (),
    tarieven: Mapping[uuid.UUID, TariefInfo] | None = None,
    samengevoegd_n: int = 1,
    duplicaat_resultaat: CheckResultaat | None = None,
    duplicaat_over_crediteuren_resultaat: CheckResultaat | None = None,
) -> CheckRapport:
    """Alle harde checks (CLAUDE.md: "áltijd blokkerend"), in vaste volgorde zodat de UI
    consistent dezelfde vier rijen toont. Verplichte-velden staat vóórop: als die al faalt, zijn
    de andere checks vaak ook zinloos (bv. geen totaalbedrag -> regeltelling kan niet zinvol
    getoetst worden) — de UI toont ze desondanks alle vier, nooit stil overslaan.
    `project_verplicht` komt uit de administratie-instelling (design-pass taak 4) — alleen dan
    telt een ontbrekend project per regel als blokkerend. `factuur_iban`/`vertrouwde_ibans`/
    `iban_baseline_vastgelegd` komen uit de orkestratie in app/documenten/boekvoorstel.py
    (extractie + leverancier_iban-set). `duplicaat_resultaat`/`duplicaat_over_crediteuren_resultaat` (boeken
    sneller 18-09, `checks_extern.py`): de EXTERNE uitkomsten al berekend (parallel of uit de cache) — dan raakt deze
    functie RLZ/Odoo niet meer aan; zonder die twee draait ze de live queries zelf (bestaand gedrag)."""
    assert client is not None or (duplicaat_resultaat is not None and duplicaat_over_crediteuren_resultaat is not None)
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
            # 18-09 (Peter, casus Rituals): btw-bedrag volgt het tarief — lokaal, direct ná de regeltelling.
            check_btw_past_bij_tarief(regels=regels, tarieven=tarieven or {}, samengevoegd_n=samengevoegd_n),
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
            duplicaat_resultaat
            if duplicaat_resultaat is not None
            else check_duplicaat(
                client=client,
                vendor_id=vendor_id,
                referentie=referentie,
                totaalbedrag=totaalbedrag,
                factuurdatum=factuurdatum,
                identiteit_vendor_ids=identiteit_vendor_ids,
                eigen_rlz_document_id=eigen_rlz_document_id,
                uitgezonderde_rlz_document_ids=uitgezonderde_rlz_document_ids,
                historie_treffers=historie_treffers,
            ),
            duplicaat_over_crediteuren_resultaat
            if duplicaat_over_crediteuren_resultaat is not None
            else check_duplicaat_over_crediteuren(
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
            vendor_id=None, reference=referentie, total_amount=totaalbedrag, expand_entity=True
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
