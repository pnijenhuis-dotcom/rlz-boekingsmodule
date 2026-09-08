from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backends.port import CrediteurNietGekoppeld
from app.backends.registry import inkoop_port_voor, standaard_regels_samenvoegen
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import kop_omschrijving as kop_omschrijving_regels
from app.documenten import leverancier_iban, veldvoorstel_regels
from app.documenten import periode as periode_regels
from app.documenten.checks import (
    CheckRapport,
    CheckRegel,
    CheckResultaat,
    check_afdeling,
    check_buitenland_tarief_crediteurkaart,
    check_duplicaat_module,
    check_iban_wissel,
    check_regeltelling,
    check_verplichte_velden,
    check_vervaldatum,
    historie_melding,
    vervaldatum_signaal,
    voer_harde_checks_uit,
)
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    LeverancierVoorkeur,
)
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.documenten.service import DocumentNietGevonden
from app.documenten.ubl import is_ubl_veldvoorstel
from app.projectverdeling.data import ProjectverdelingData
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)

# Zodra het document GEBOEKT is, is het RLZ-boekstuk de bron van waarheid (CLAUDE.md, kernprincipe
# 1) — het boekvoorstel wordt dan bevroren, geen bewerking (PUT) of herberekening (checks) meer via
# deze service. VERWIJDERD (soft-delete) is om een andere reden bevroren: een zachtgewist document
# hoort niet meer bewerkt te worden vóórdat het expliciet hersteld is (service.py::herstel_document)
# — anders zou een "verwijderd" document alsnog stiekem wijzigen terwijl het uit het zicht is.
_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class BoekvoorstelFout(Exception):
    """Domeinfout in de boekvoorstel-servicelaag."""


def _controleer_niet_bevroren(document: Document) -> None:
    if document.status in _BEVROREN_STATUSSEN:
        raise BoekvoorstelFout(
            f"Document {document.id} kan niet meer gewijzigd of gecontroleerd worden (status: {document.status.value})"
        )


@dataclass(frozen=True)
class BoekvoorstelRegelData:
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    omschrijving: str | None
    # DB-id van de opgeslagen regel (boekvoorstel_regel.id) — alleen gevuld voor persisted
    # regels; prefills (AI/UBL, nog niet opgeslagen) hebben er geen. De doorbelasting-verdeling
    # (blok 3) sleutelt hierop (bron_regel_id), en die bestaat alleen op GEBOEKTE documenten.
    id: uuid.UUID | None = None
    # Herkomst van de btw-code (feedbackronde 26-08 punt 3): "factuur" = deterministisch uit
    # netto/btw van de gelezen regel afgeleid (prefill, nog niet opgeslagen). None = leeg of van
    # de mens/het geheugen. Alleen gevuld op prefill-regels — ná opslaan is de keuze van de
    # controleur (zelfde regel als de AI-zekerheidschips). Sinds blok E 04-09 óók "standaard" = de
    # btw-default van de administratie (vult alleen wat factuur én leverancier-geheugen leeg lieten).
    btw_bron: str | None = None
    # Blok 6 herstelrun 08-09: leesbare herkomst van de verlegd-keuze bij `btw_bron='factuur_verlegd'` ("voorkeur
    # beheerder" / "meest gebruikt in RLZ-historie (n×)" / "administratie-default" / …, regel_prefill.VerlegdKeuze) —
    # chip-tekst in de UI, informatief; in de snapshot zodat de chip ná het persisteren terugkomt.
    btw_bron_detail: str | None = None
    # Herkomst van het grootboek-voorstel per regel (blok D 04-09, app/geheugen/regel_gb.py):
    # "geheugen" (groen, app-bevestigd) | "geheugen_seed" / "geheugen_conflict" (oranje) | "ai"
    # (oranje, AI-classificatie tegen de historische grootboeken van deze leverancier). None = leeg of
    # van de mens. Alleen gevuld op prefill-regels; `gb_voorstel_detail` = tooltip-tekst.
    gb_bron: str | None = None
    gb_voorstel_detail: str | None = None
    # Blok A3 04-09 (besluit Peter): heeft de scan het btw-veld BEWUST leeg gelaten — 0 % is ambigu
    # (verlegd/vrijgesteld/0 %-tarief), meerduidige tariefmatch of een btw-bedrag dat op geen tarief past —
    # dan mag de administratie-default (blok E) 'm níét vullen: de default vult uitsluitend velden waarvoor
    # scan én geheugen niets hadden. Alleen op prefill-regels; komt uit `btw_afleiding_reden` van de
    # extractie (app/extractie/controle.py::leid_btw_af). Intern veld, niet in de DTO.
    btw_bewust_leeg: bool = False
    # Slotstuk 04-09 (C1, migratie 0112): spoor van de hervertaling van een OPEN voorstel bij een Odoo-overstap
    # (`app/odoo/hervertaling.py`) — per veld van→naar of "geen tegenhanger". Alleen op opgeslagen regels; de
    # eerstvolgende PUT door de mens schrijft de regels opnieuw zonder dit spoor (chip verdwijnt, bewust).
    overstap_vertaling: dict | None = None
    # Blok A10 07-09 (stale check bij geheugen-prefill): herkomst per gevuld veld op een prefill-regel —
    # {"grootboek"|"btw"|"project": bron} met bron = gb_bron-waarde (blok D) | "leverancier_geheugen" (kop-niveau-
    # engine, chip "Geheugen N %") | "factuur" | "standaard" (blok E). Intern: stuurt de autosave-trigger en het
    # herstel van de herkomst-chips ná het persisteren (regel_prefill.py). Niet in de DTO.
    prefill_herkomst: dict[str, str] | None = None
    # Blok 10 07-09 (project uit de factuur, casus Spot Services): `project_tekst` = het op de factuur gelezen
    # projectnummer/werknummer voor déze regel (regel-`proj`, anders kop-`proj`; ruw, alleen op prefill-regels —
    # intern). `project_bron` = herkomst van het ingevulde project: "factuur" (groen: exacte projectcode of
    # bevestigde werknummer-mapping) | "factuur_onbevestigd" (oranje: eerste keer / fuzzy) |
    # "factuur_meerduidig" (niets ingevuld — meerdere kandidaten, `project_bron_detail` noemt ze); None = leeg/
    # mens/geheugen. `project_bron_detail` = tooltip-tekst. Beide in de DTO (informatief; de server negeert
    # ze bij opslaan), zelfde chip-regel als gb_bron/btw_bron: weg zodra de mens het veld aanraakt.
    project_tekst: str | None = None
    project_bron: str | None = None
    project_bron_detail: str | None = None


@dataclass(frozen=True)
class BoekvoorstelData:
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None
    referentie: str | None
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    rlz_boekstuknummer: str | None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelData]
    # Fix 3 (2026-07-10): regels standaard samengevoegd tot één boekingsregel, keuze per
    # leverancier onthouden (LeverancierVoorkeur). `samenvoegen_toegestaan` is False bij
    # projectplicht (hard: project per regel, samenvoegen kan daar niet); `regels_samenvoegen`
    # is de effectieve stand voor dit document (voorkeur van deze crediteur, default AAN);
    # `samengevoegde_regel` is de deterministisch berekende één-regel-variant (None als er
    # geen veldvoorstel met bruikbare totalen is).
    regels_samenvoegen: bool = True
    samenvoegen_toegestaan: bool = True
    samengevoegde_regel: BoekvoorstelRegelData | None = None
    # Tegenboek-pad (migratie 0061): bepaalt het RLZ-GUID van de (her)boeking — cyclus 0 is de
    # oorspronkelijke boeking, elke "tegenboeken én opnieuw boeken" verhoogt 'm.
    boek_cyclus: int = 0
    # "Btw verlegd"-vermelding uit de laatste extractie (punt 3, 26-08) — HINT voor de
    # controleur bij 0%-regels, nooit een invulling. None = niets gelezen of geen veldvoorstel.
    btw_verlegd_vermelding: str | None = None
    # Vervaldatum (C1 26-08): kopveld uit de scan; None = leeg (RLZ leidt DueDate dan zelf af).
    vervaldatum: date | None = None
    # Betalingskenmerk (Odoo-adapter fase 1, migratie 0101): kopveld uit de scan (sentinel-patroon) →
    # Odoo `payment_reference`; RLZ negeert het. None = niet gelezen.
    betalingskenmerk: str | None = None
    # Oranje signaal bij een implausibele betaaltermijn (> 90 dagen) — checks.vervaldatum_signaal.
    vervaldatum_signaal: str | None = None
    # Afdeling (blok A 28-08, migratie 0084): de handmatige keuze op dit document. `afdeling_prefill`
    # = vorige keuze voor deze leverancier (alleen zolang het document zelf nog geen afdeling heeft;
    # herkomst-chip "🧠 vorige keuze bij <leverancier>") — een voorstel, de mens beslist.
    afdeling_id: uuid.UUID | None = None
    afdeling_prefill_id: uuid.UUID | None = None
    afdeling_prefill_leverancier: str | None = None
    # Projectverdeling pro rato omzet (blok C 04-09, migratie 0107): vaste regels + restant pro rato over de
    # projecten mét omzet; None = niet van toepassing. Voorstel = live herrekend, geboekt = bevroren snapshot.
    # De adapters (RLZ: regels splitsen; Odoo: analytic_distribution) lezen hieruit — app/projectverdeling/.
    projectverdeling: ProjectverdelingData | None = None
    # Blok A10 07-09: True als het OPGESLAGEN voorstel de automatische prefill van het openen is
    # (`persisteer_prefill_bij_openen`) en de kopvelden sindsdien niet door een mens gewijzigd zijn — de UI houdt
    # dan de AI-zekerheidschips aan (zelfde stand als een nog niet opgeslagen prefill). Altijd False op een
    # niet-opgeslagen voorstel en op een door een mens opgeslagen voorstel.
    prefill_automatisch: bool = False
    # Blok 9 vervolgrun 07-09 (besluit Peter, auto-first): kop-omschrijving van het document — RLZ `Description`
    # op de PurchaseInvoice, Odoo `narration`. Deterministisch afgeleid (app/documenten/kop_omschrijving.py:
    # één regel → regeltekst | `betreft` uit de scan | "‹leverancier› ‹nummer›") tenzij de mens 'm zette
    # (herkomst "handmatig", bewaard als tijdlijn-notitie `kop_omschrijving` — geen kolom). Herkomst =
    # "regel" | "factuur" | "afgeleid" | "handmatig" | None (chip op het controlescherm).
    omschrijving: str | None = None
    omschrijving_herkomst: str | None = None
    # Blok 11 vervolgrun 07-09 (kosten op weekniveau — datalaag): de ISO-week(s) waarop de factuur betrekking heeft,
    # mét herkomst (`factuur`/`factuur_maand` = voorgelezen en deterministisch genormaliseerd, `afgeleid_van_
    # factuurdatum` = terugval, `mens` = correctie via de PUT, wint altijd) en de ruwe factuurtekst. Kolommen op
    # `boekvoorstel` (migratie 0120); op een oud voorstel zonder kolomwaarde wordt de stand live afgeleid.
    periode: periode_regels.FactuurPeriode | None = None


def _met_projectverdeling(
    session: Session, administratie_id: uuid.UUID, project_verplicht: bool, data: BoekvoorstelData
) -> BoekvoorstelData:
    """Koppelpunt blok C: zet `projectverdeling` op het (frozen) voorstel — lazy import, geen kring."""
    from app.projectverdeling import service as projectverdeling_service

    return projectverdeling_service.verrijk_boekvoorstel(
        session, administratie_id=administratie_id, data=data, project_verplicht=project_verplicht
    )


def _project_verplicht_per_regel(project_verplicht: bool, voorstel: BoekvoorstelData) -> bool:
    """Draagt het document een GELDIGE opgeslagen projectverdeling (actief én compleet: vaste regels + evt.
    pro-rato-restant sluiten exact op het te verdelen bedrag), dan telt élke regel zonder kolom-project als gedekt en
    toetst "Verplichte velden" het project niet meer per regel. Een onvolledige/ongeldige verdeling dekt níéts: de
    projectplicht per regel blijft blokkeren (mét de verwijzing naar "Verdelen over projecten…") én de check
    "Projectverdeling" benoemt de blokkade. Nooit een verzwakking; onafhankelijk van de leverancier-opt-in
    (B3-dekking, bugfix 04-09). Dezelfde functie voedt het controlescherm én de boekmotor-poort (voer_checks_uit)."""
    if voorstel.projectverdeling is not None and voorstel.projectverdeling.dekt_regels_zonder_project:
        return False
    return project_verplicht


def _regels_zonder_project(voorstel: BoekvoorstelData) -> int:
    return sum(1 for r in voorstel.regels if r.project_id is None)


def _als_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _als_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _raad_vendor_id(session: Session, *, administratie_id: uuid.UUID, leverancier_naam: str | None) -> uuid.UUID | None:
    """Best-effort suggestie op basis van een exacte (case-insensitive) naammatch tegen de
    vendor-cache — alleen bij precies één match, anders geen giswerk (consistent met CLAUDE.md's
    "nooit auto-toewijzen bij twijfel", hier toegepast op de crediteurkeuze i.p.v. de administratie-
    toewijzing)."""
    if not leverancier_naam:
        return None
    from app.crediteuren.voorkeur import BRUIKBAAR  # B13 07-09: een verliezer wordt nooit voorgesteld

    kandidaten = session.scalars(
        select(VendorCache).where(
            VendorCache.administratie_id == administratie_id,
            func.lower(VendorCache.naam) == leverancier_naam.strip().lower(),
            BRUIKBAAR,
        )
    ).all()
    if len(kandidaten) == 1:
        return kandidaten[0].id
    return None


_UBL_TOTAALSLEUTELS = ("totaal_excl", "totaal_incl", "totaal_btw", "btw_bedrag")
_UBL_PROJECT_PATROON = re.compile(r"^\s*project(?:nummer|nr\.?|code)?\s*[:#]\s*(.+?)\s*$", re.IGNORECASE)


def _is_ubl_creditnota(veldvoorstel: dict | None) -> bool:
    return is_ubl_veldvoorstel(veldvoorstel) and bool((veldvoorstel or {}).get("is_creditnota"))


def _veldvoorstel_met_teken(veldvoorstel: dict | None) -> dict | None:
    """Blok 3 herstelrun 08-09 (gouden casus BOOT 202633199): een UBL-CreditNote (381) draagt per conventie POSITIEVE
    bedragen; in het boekvoorstel, de lijst en de checks is een creditnota NEGATIEF (zo boekt de mens 'm, zo boekt RLZ
    'm). De totalen worden hier één keer van teken gewisseld; de regels doen dat zelf in `_regel_prefill_uit_ubl`."""
    if not _is_ubl_creditnota(veldvoorstel):
        return veldvoorstel
    kopie = dict(veldvoorstel or {})
    for sleutel in _UBL_TOTAALSLEUTELS:
        bedrag = _als_decimal(kopie.get(sleutel))
        if bedrag is not None:
            kopie[sleutel] = str(-bedrag)
    return kopie


def _ubl_project_tekst(veldvoorstel: dict) -> str | None:
    """Projectnummer dat een leverancier als NULREGEL op de UBL zet ("Project: 25011" — casus Floor 26219): één
    distinct projecttekst uit de nulregel-omschrijvingen (of het kop-`project_tekst`); meerdere = None (nooit
    gokken)."""
    kop = veldvoorstel.get("project_tekst")
    if isinstance(kop, str) and kop.strip():
        return kop.strip()
    gevonden: dict[str, str] = {}
    for regel in veldvoorstel.get("ubl_regels") or []:
        if not isinstance(regel, dict):
            continue
        m = _UBL_PROJECT_PATROON.match(str(regel.get("omschrijving") or ""))
        if m:
            gevonden.setdefault(m.group(1).lower(), m.group(1))
    return next(iter(gevonden.values())) if len(gevonden) == 1 else None


def _regel_prefill_uit_ubl(veldvoorstel: dict) -> list[BoekvoorstelRegelData]:
    """Regels van een UBL-voorstel. Blok 3 herstelrun 08-09: RECHTSTREEKS uit de XML-regels (`ubl_regels`:
    netto = LineExtensionAmount, btw = netto × cbc:Percent (of het verrijkte `btw_bedrag`), omschrijving = Item/Name,
    btw-code = deterministische afleiding uit de extractie-afronding) — mits élke regel een netto én een btw-bedrag
    draagt en de som exact op de gelezen totalen sluit (code voor cijfers: bij twijfel de bewezen één-regel-prefill uit
    de totalen, nooit een half regelsetje)."""
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
    if totaal_excl is None or totaal_incl is None:
        return []
    een_regel = [
        BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=None,
            project_id=None,
            netto_bedrag=totaal_excl,
            btw_bedrag=totaal_incl - totaal_excl,
            omschrijving=None,
        )
    ]
    ubl_regels = veldvoorstel.get("ubl_regels")
    if not isinstance(ubl_regels, list) or not ubl_regels:
        return een_regel
    from app.documenten.ubl_voorstel import regel_btw_bedrag  # lokaal: ubl_voorstel leest crediteur_kenmerk

    # CreditNote (381): de UBL-regels zijn positief, het voorstel negatief (totalen zijn al gewisseld, zie
    # `_veldvoorstel_met_teken`). Nulregels (aantal 0, bedrag 0 — "Plaats: …", "Project: …", "Periode: …", casus
    # Floor) zijn bron, geen boekingsregel; hun projecttekst gaat als `project_tekst` mee naar de échte regels.
    teken = Decimal(-1) if veldvoorstel.get("is_creditnota") else Decimal(1)
    project_tekst = _ubl_project_tekst(veldvoorstel)
    regels: list[BoekvoorstelRegelData] = []
    echte = [
        r
        for r in ubl_regels
        if isinstance(r, dict)
        and not veldvoorstel_regels.is_nulregel(
            netto=_als_decimal(r.get("netto_bedrag")),
            btw=regel_btw_bedrag(r),
            hoeveelheid=veldvoorstel_regels.parse_hoeveelheid(r.get("aantal")),
        )
    ]
    if len(echte) != len([r for r in ubl_regels if isinstance(r, dict)]) and not echte:
        echte = [r for r in ubl_regels if isinstance(r, dict)]  # louter nulregels: niets stil wegfilteren
    for regel in echte:
        netto, btw = _als_decimal(regel.get("netto_bedrag")), regel_btw_bedrag(regel)
        if netto is None:
            return een_regel
        if btw is None and len(echte) == 1:
            btw = (totaal_incl - totaal_excl) * teken  # één regel zonder percentage: de document-btw ís de regel-btw
        if btw is None:
            return een_regel
        regels.append(
            BoekvoorstelRegelData(
                ledger_id=None,
                taxrate_id=_als_uuid(regel.get("taxrate_id")),
                project_id=None,
                netto_bedrag=netto * teken,
                btw_bedrag=btw * teken,
                omschrijving=regel.get("omschrijving") or None,
                btw_bron=_btw_bron(regel),
                btw_bewust_leeg=_btw_bewust_leeg(regel),
                project_tekst=project_tekst,
            )
        )
    if not regels or sum((r.netto_bedrag for r in regels), Decimal(0)) != totaal_excl:
        return een_regel
    if sum((r.btw_bedrag for r in regels), Decimal(0)) != totaal_incl - totaal_excl:
        return een_regel
    return regels


def _als_uuid(waarde: str | None) -> uuid.UUID | None:
    if not waarde:
        return None
    try:
        return uuid.UUID(waarde)
    except ValueError:
        return None


def _regels_prefill(veldvoorstel: dict) -> list[BoekvoorstelRegelData]:
    """AI-veldvoorstellen (bron "ai", app/extractie/controle.py) dragen echte factuurregels —
    die worden één-op-één regels in het boekvoorstel, incl. de eventuele btw-code-suggestie uit
    de sync-cache. GB (`ledger_id`) blijft bewust leeg: het boekingsgeheugen is een volgende
    sessie, en zonder geheugen is elke GB-keuze een gok. UBL-voorstellen houden hun bestaande
    één-regel-prefill uit de totalen.

    Blok 4 (08-09, Spot Services): tariefstaffel-regels (aantal 0, bedrag 0, btw 0) worden GEEN boekingsregel —
    ze blijven als bron in het veldvoorstel (`veldvoorstel_regels.boekbare_regels`). Kop-`proj` = default voor regels
    zonder eigen tekst; staat het nummer alleen op één regel, dan is dát de kop (`kop_project_tekst`)."""
    if not isinstance(veldvoorstel.get("regels"), list) or not veldvoorstel.get("regels"):
        return _regel_prefill_uit_ubl(veldvoorstel)
    ai_regels = veldvoorstel_regels.boekbare_regels(veldvoorstel)
    kop_project = veldvoorstel_regels.kop_project_tekst(veldvoorstel)
    return [
        BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=_als_uuid(regel.get("taxrate_id")),
            project_id=None,
            netto_bedrag=_als_decimal(regel.get("netto_bedrag")),
            btw_bedrag=_als_decimal(regel.get("btw_bedrag")),
            omschrijving=regel.get("omschrijving"),
            btw_bron=_btw_bron(regel),
            btw_bewust_leeg=_btw_bewust_leeg(regel),
            # Blok 10: regel-`proj` wint van kop-`proj`; de kop is de default voor regels zonder eigen tekst.
            project_tekst=_str_of_none(regel.get("project_tekst") or kop_project or None),
        )
        for regel in ai_regels
    ]


def _btw_bron(regel: dict) -> str | None:
    """Alleen "factuur" als de regel ook écht een afgeleide btw-code draagt."""
    return "factuur" if regel.get("btw_bron") == "factuur" and _als_uuid(regel.get("taxrate_id")) else None


# Redenen uit `leid_btw_af` waarbij de scan het btw-veld BEWUST leeg liet (de scan hád informatie, maar die
# is ambigu of past op geen tarief) — blok A3 04-09. "onbepaalbaar" (netto/btw niet gelezen) hoort er niet
# bij: dan had de scan niets, en mag de administratie-default wél vullen.
_BTW_BEWUST_LEEG_REDENEN = frozenset({"btw_nul", "meerduidig", "geen_match"})


def _btw_bewust_leeg(regel: dict) -> bool:
    return _als_uuid(regel.get("taxrate_id")) is None and regel.get("btw_afleiding_reden") in _BTW_BEWUST_LEEG_REDENEN


def _samengevoegde_regel(veldvoorstel: dict) -> BoekvoorstelRegelData | None:
    """Eén boekingsregel voor het hele factuurbedrag (fix 3, mockup: "één grootboek voor het
    hele factuurbedrag"): netto = gelezen totaal excl., btw = gelezen btw-bedrag (of incl −
    excl), met als vangnet de deterministische som van de geëxtraheerde regels — alleen als álle
    regelbedragen geparst zijn, nooit een gedeeltelijke som. Grootboek blijft leeg
    (boekingsgeheugen = sessie 2); btw-code alleen als alle regels dezelfde cache-suggestie
    dragen. De AI blijft altijd alle regels extraheren — dit is puur de weergave-/boekvorm.
    Tariefstaffel-regels (blok 4 08-09) tellen niet mee in het regelaantal (som ongewijzigd: ze zijn 0)."""
    regels = veldvoorstel_regels.boekbare_regels(veldvoorstel)

    netto = _als_decimal(veldvoorstel.get("totaal_excl"))
    if netto is None and regels:
        netto_bedragen = [_als_decimal(r.get("netto_bedrag")) for r in regels]
        if all(bedrag is not None for bedrag in netto_bedragen):
            netto = sum(netto_bedragen, Decimal(0))
    if netto is None:
        return None

    btw = _als_decimal(veldvoorstel.get("btw_bedrag"))
    if btw is None:
        totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
        if totaal_incl is not None:
            btw = totaal_incl - netto
    if btw is None and regels:
        btw_bedragen = [_als_decimal(r.get("btw_bedrag")) for r in regels]
        if all(bedrag is not None for bedrag in btw_bedragen):
            btw = sum(btw_bedragen, Decimal(0))

    taxrate_ids = {r.get("taxrate_id") for r in regels}
    taxrate_id = _als_uuid(next(iter(taxrate_ids))) if len(taxrate_ids) == 1 else None
    btw_bron = "factuur" if taxrate_id is not None and all(_btw_bron(r) == "factuur" for r in regels) else None
    # Blok A3: liet de scan op ook maar één regel de btw bewust leeg, dan is de samengevoegde regel dat óók —
    # de administratie-default mag 'm dan niet vullen.
    btw_bewust_leeg = taxrate_id is None and any(_btw_bewust_leeg(r) for r in regels)

    omschrijving = None
    if regels:
        factuurnummer = veldvoorstel.get("factuurnummer")
        omschrijving = (
            f"Factuur {factuurnummer} — samengevoegd ({len(regels)} regels)"
            if factuurnummer
            else f"Samengevoegd ({len(regels)} regels)"
        )

    return BoekvoorstelRegelData(
        ledger_id=None,
        taxrate_id=taxrate_id,
        project_id=None,
        netto_bedrag=netto,
        btw_bedrag=btw,
        omschrijving=omschrijving,
        btw_bron=btw_bron,
        btw_bewust_leeg=btw_bewust_leeg,
    )


def _verlegd_vermelding(veldvoorstel: dict | None) -> str | None:
    waarde = veldvoorstel.get("btw_verlegd_vermelding") if veldvoorstel else None
    return waarde if isinstance(waarde, str) and waarde else None


def _factuur_is_verlegd(veldvoorstel: dict | None) -> bool:
    """Blok 4c (08-09, Spot Services): de factuur draagt een verleggings-vermelding (kop/totaalblok, deterministisch
    getoetst in controle.is_verlegd_vermelding) ÉN de factuur-btw is 0 — gelezen btw-bedrag 0, of (zonder gelezen
    btw-bedrag) incl. = excl. Onbekend = False: nooit raden."""
    if veldvoorstel is None or _verlegd_vermelding(veldvoorstel) is None:
        return False
    # NB niet via `_gelezen_totalen`: die zet een gelezen btw-bedrag van 0 met `or` op None.
    factuur_btw = _als_decimal(veldvoorstel.get("btw_bedrag"))
    if factuur_btw is None:
        factuur_btw = _als_decimal(veldvoorstel.get("totaal_btw"))
    if factuur_btw is not None:
        return factuur_btw == 0
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
    return totaal_excl is not None and totaal_incl is not None and totaal_excl == totaal_incl


def _gelezen_totalen(veldvoorstel: dict | None) -> tuple[Decimal | None, Decimal | None]:
    """(totaal excl., factuur-btw-bedrag) zoals GELEZEN in het laatste veldvoorstel — voor de
    regeltelling-check (bugfix 04-09, Huvanco). Het boekvoorstel zelf draagt alleen het incl-totaal
    (mens-veld, blijft leidend voor de incl-kant); de excl-/btw-kant komt uit de extractie: AI-/
    template-voorstel `totaal_excl` + `btw_bedrag`, UBL `totaal_excl` + `totaal_btw`. Geen
    veldvoorstel = (None, None) → de check valt terug op de incl-vergelijking of meldt expliciet dat
    er niets te toetsen is (nooit stil excl-vs-incl)."""
    if not veldvoorstel:
        return None, None
    veldvoorstel = _veldvoorstel_met_teken(veldvoorstel) or veldvoorstel  # UBL-creditnota: negatief (blok 3 08-09)
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    factuur_btw = _als_decimal(veldvoorstel.get("btw_bedrag")) or _als_decimal(veldvoorstel.get("totaal_btw"))
    return totaal_excl, factuur_btw


def _rlz_leesclient(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _historie_treffers(*, administratie_id: uuid.UUID, voorstel: BoekvoorstelData) -> list[dict]:
    """Odoo-slotstuk 04-09 (`documenten/duplicaat_historie.py`): RLZ-era GEBOEKTE documenten met dezelfde kop,
    alleen voor een overgestapte administratie — de live query van de Odoo-backend kent Reeleezee niet."""
    from app.documenten.duplicaat_historie import geboekte_treffers_uit_historie

    with scoped_session(administratie_id) as session:
        return geboekte_treffers_uit_historie(
            session,
            administratie_id=administratie_id,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            totaalbedrag=voorstel.totaalbedrag,
            eigen_document_id=voorstel.document_id,
        )


def _project_verplicht(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie.project_verplicht if administratie else False


def _voorkeur_samenvoegen(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> bool | None:
    if vendor_id is None:
        return None
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    return voorkeur.regels_samenvoegen if voorkeur else None


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    """Nieuwste wint: na "opnieuw extraheren" is de laatste extractie de actuele."""
    return next(
        (
            g.detail["veldvoorstel"]
            for g in reversed(_gebeurtenissen_van(session, document_id))
            if g.detail and "veldvoorstel" in g.detail
        ),
        None,
    )


def _laad_document(session: Session, *, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    return document


def _samenvoeg_velden(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    veldvoorstel: dict | None,
    project_verplicht: bool,
    standaard_samenvoegen: bool,
) -> dict:
    """Fix 3: effectieve samenvoeg-stand (projectplicht = hard gesplitst; anders de onthouden
    leverancier-voorkeur, default = backend-capability) + de berekende één-regel-variant."""
    if project_verplicht:
        return {"regels_samenvoegen": False, "samenvoegen_toegestaan": False, "samengevoegde_regel": None}
    voorkeur = _voorkeur_samenvoegen(session, administratie_id=administratie_id, vendor_id=vendor_id)
    return {
        # Default zonder leverancier-voorkeur = backend-capability (RLZ AAN; Odoo UIT — regelniveau-
        # data moet in Odoo landen, eis Peter 03-09); de leverancier-voorkeur wint altijd.
        "regels_samenvoegen": voorkeur if voorkeur is not None else standaard_samenvoegen,
        "samenvoegen_toegestaan": True,
        "samengevoegde_regel": _samengevoegde_regel(veldvoorstel) if veldvoorstel else None,
    }


def _afdeling_velden(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None, huidige_afdeling_id: uuid.UUID | None
) -> dict:
    """Blok A 28-08: prefill uit het leverancier-geheugen alleen als er nog geen keuze op het
    document staat; toggle uit = niets (het veld is dan onzichtbaar)."""
    from app.afdelingen.service import afdelingen_ingeschakeld_in_sessie, prefill_voor_vendor

    if not afdelingen_ingeschakeld_in_sessie(session, administratie_id):
        return {"afdeling_id": huidige_afdeling_id}
    prefill = (
        prefill_voor_vendor(session, administratie_id=administratie_id, vendor_id=vendor_id)
        if huidige_afdeling_id is None
        else None
    )
    return {
        "afdeling_id": huidige_afdeling_id,
        "afdeling_prefill_id": prefill.afdeling_id if prefill else None,
        "afdeling_prefill_leverancier": prefill.leverancier_naam if prefill else None,
    }


# ---------------------------------------------------------------------------------------------
# Blok 9 vervolgrun 07-09 — kop-omschrijving (RLZ `Description` / Odoo `narration`), auto-first.
# De afleiding is puur (kop_omschrijving.py); hier de koppeling met het voorstel: welke regelteksten
# tellen (de synthetische samengevoegde regel niet), waar `betreft`/leveranciersnaam vandaan komen,
# en de mens-override als tijdlijn-notitie (`DocumentGebeurtenis.detail["kop_omschrijving"]`,
# zelfde JSON-patroon als de A10-prefill-snapshot; geen kolom, geen migratie — opdracht blok 9).
# ---------------------------------------------------------------------------------------------
KOP_OMSCHRIJVING_SLEUTEL = "kop_omschrijving"


def _laatste_kop_omschrijving_notitie(gebeurtenissen: list[DocumentGebeurtenis]) -> dict | None:
    return next(
        (
            g.detail[KOP_OMSCHRIJVING_SLEUTEL]
            for g in reversed(gebeurtenissen)
            if g.detail and isinstance(g.detail.get(KOP_OMSCHRIJVING_SLEUTEL), dict)
        ),
        None,
    )


def _kop_omschrijving_override(gebeurtenissen: list[DocumentGebeurtenis]) -> str | None:
    """De door een mens gezette kop-omschrijving (laatste notitie wint); `tekst: null` = terug naar automatisch."""
    notitie = _laatste_kop_omschrijving_notitie(gebeurtenissen)
    if notitie is None:
        return None
    return kop_omschrijving_regels.normaliseer(notitie.get("tekst"))


def _leverancier_naam(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    vendor = session.get(VendorCache, (vendor_id, administratie_id))
    return vendor.naam if vendor else None


def _echte_regelteksten(
    regels: list[BoekvoorstelRegelData], *, veldvoorstel: dict | None, samengevoegde_regel: BoekvoorstelRegelData | None
) -> list[str | None]:
    """Regelteksten voor de afleiding. Is de ene boekingsregel de SYNTHETISCHE samengevoegde regel ("Factuur X —
    samengevoegd (n regels)"), dan is dat geen factuurtekst: dan tellen de gelezen factuurregels uit het
    veldvoorstel (precies één gelezen regel → die tekst; meerdere → geen regeltekst, `betreft` of terugval)."""
    if (
        len(regels) == 1
        and samengevoegde_regel is not None
        and samengevoegde_regel.omschrijving is not None
        and regels[0].omschrijving == samengevoegde_regel.omschrijving
    ):
        # Blok 4 (08-09): tariefstaffel-regels zijn geen factuurtekst voor de kop-omschrijving.
        return [r.get("omschrijving") for r in veldvoorstel_regels.boekbare_regels(veldvoorstel)]
    return [r.omschrijving for r in regels]


def _afgeleide_kop_omschrijving(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    regels: list[BoekvoorstelRegelData],
    veldvoorstel: dict | None,
) -> kop_omschrijving_regels.KopOmschrijving:
    """Eén bron voor leesroute (GET), autosave en PUT: dezelfde invoer geeft dezelfde omschrijving."""
    return kop_omschrijving_regels.bepaal_kop_omschrijving(
        regel_omschrijvingen=_echte_regelteksten(
            regels,
            veldvoorstel=veldvoorstel,
            samengevoegde_regel=_samengevoegde_regel(veldvoorstel) if veldvoorstel else None,
        ),
        betreft=(veldvoorstel or {}).get("betreft"),
        leverancier_naam=_leverancier_naam(session, administratie_id=administratie_id, vendor_id=vendor_id),
        referentie=referentie,
    )


def _met_kop_omschrijving(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    data: BoekvoorstelData,
    regels: list[BoekvoorstelRegelData],
    veldvoorstel: dict | None,
    gebeurtenissen: list[DocumentGebeurtenis] | None,
) -> BoekvoorstelData:
    """Zet `omschrijving` + `omschrijving_herkomst` op het (frozen) voorstel: mens-override (tijdlijn) wint,
    anders de afleiding. `gebeurtenissen=None` = prefill-pad (een override veronderstelt een opgeslagen voorstel)."""
    override = _kop_omschrijving_override(gebeurtenissen) if gebeurtenissen is not None else None
    if override is not None:
        return replace(
            data,
            omschrijving=kop_omschrijving_regels.kap_af(override),
            omschrijving_herkomst=kop_omschrijving_regels.HERKOMST_HANDMATIG,
        )
    afgeleid = _afgeleide_kop_omschrijving(
        session,
        administratie_id=administratie_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        regels=regels,
        veldvoorstel=veldvoorstel,
    )
    return replace(data, omschrijving=afgeleid.tekst, omschrijving_herkomst=afgeleid.herkomst)


# ---------------------------------------------------------------------------------------------
# Blok A10 07-09 — stale check bij geheugen-prefill: de prefill uit geheugen/template/default wordt
# bij het OPENEN van het controlescherm gepersisteerd (autosave), mét een herkomst-snapshot in de
# tijdlijn (DocumentGebeurtenis.detail["boekvoorstel_prefill"]) zodat (1) de checks en het
# doorbelasten-blok exact zien wat de mens ziet, (2) de herkomst-chips blijven staan tot de mens
# een waarde wijzigt (waarde-gelijkheid met het snapshot — dezelfde regel als de GeheugenChipBlok),
# (3) openen 2× niets opnieuw persisteert en een door een mens gezette waarde nooit overschreven
# wordt, en (4) een VERSE extractie ná een nog onaangeraakte autosave de prefill opnieuw afleidt
# (anders zou "opnieuw extraheren" stil niets meer tonen — niets verdwijnt stil).
# ---------------------------------------------------------------------------------------------
PREFILL_SNAPSHOT_SLEUTEL = "boekvoorstel_prefill"
# Statussen waarin het controlescherm bewerkbaar is (spiegel van DoorbelastenNaBoeken.KLAARZETBAAR
# en `doorbelasting.service._KLAARZETBARE_DOCUMENTSTATUSSEN`): alleen dáár mag de prefill
# gepersisteerd worden — bevroren/afgewezen/ter accordering/vraag open: nooit.
_AUTOSAVE_STATUSSEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.BOEKEN_MISLUKT,
    }
)
# Herkomsten die de autosave TRIGGEREN (opdracht Peter 07-09: "prefills uit geheugen/template/default"):
# regel-geheugen (alle drie de blok-D-varianten, ook seed-only oranje), leverancier-geheugen (kop-niveau-
# engine) en de btw-default van de administratie; plus een template-veldvoorstel (kop). AI-classificatie
# ("ai") en de uit de factuur afgeleide btw ("factuur") triggeren níét — een AI-only prefill blijft
# zoals voorheen niet-opgeslagen (de checks zagen die al).
_AUTOSAVE_HERKOMSTEN = frozenset(
    {"geheugen", "geheugen_seed", "geheugen_conflict", "leverancier_geheugen", "standaard"}
)
# Blok 10 07-09: een project uit de factuur (exacte code, werknummer-mapping of fuzzy — ingevuld) triggert de autosave
# óók (opdracht: "via het A10-prefill-/autosave-pad") — de projectplicht-check en het doorbelasten-blok zien dan
# hetzelfde project als de mens. "factuur_meerduidig" vult niets en triggert dus niet.
_PROJECT_FACTUUR_HERKOMSTEN = frozenset({"factuur", "factuur_onbevestigd"})


def _str_of_none(waarde: object) -> str | None:
    return None if waarde is None else str(waarde)


def _regel_snapshot(volgnummer: int, regel: BoekvoorstelRegelData) -> dict:
    return {
        "volgnummer": volgnummer,
        "ledger_id": _str_of_none(regel.ledger_id),
        "taxrate_id": _str_of_none(regel.taxrate_id),
        "project_id": _str_of_none(regel.project_id),
        "netto_bedrag": _str_of_none(regel.netto_bedrag),
        "btw_bedrag": _str_of_none(regel.btw_bedrag),
        "omschrijving": regel.omschrijving or None,
        "gb_bron": regel.gb_bron,
        "gb_voorstel_detail": regel.gb_voorstel_detail,
        "btw_bron": regel.btw_bron,
        "btw_bron_detail": regel.btw_bron_detail,
        "project_bron": regel.project_bron,
        "project_bron_detail": regel.project_bron_detail,
        "herkomst": dict(regel.prefill_herkomst or {}),
    }


def _maak_prefill_snapshot(
    prefill: BoekvoorstelData,
    *,
    regels: list[BoekvoorstelRegelData],
    veldvoorstel: dict,
    triggers: list[str],
    geopend_door: uuid.UUID,
    aanleiding: str = "openen",
) -> dict:
    return {
        "bron": aanleiding,
        "geopend_door": str(geopend_door),
        "veldvoorstel_bron": veldvoorstel.get("bron") or ("ubl" if is_ubl_veldvoorstel(veldvoorstel) else None),
        "triggers": triggers,
        "regels_samenvoegen": bool(prefill.regels_samenvoegen and prefill.samengevoegde_regel is not None),
        "kop": {
            "vendor_id": _str_of_none(prefill.vendor_id),
            "referentie": prefill.referentie or None,
            "factuurdatum": _str_of_none(prefill.factuurdatum),
            "vervaldatum": _str_of_none(prefill.vervaldatum),
            "totaalbedrag": _str_of_none(prefill.totaalbedrag),
            "betalingskenmerk": prefill.betalingskenmerk or None,
            "afdeling_prefill_id": _str_of_none(prefill.afdeling_prefill_id),
            "afdeling_prefill_leverancier": prefill.afdeling_prefill_leverancier,
            # Blok 9: informatief — de kop-omschrijving is een afleiding (geen kolom), de leesroute herleidt 'm zelf.
            "omschrijving": prefill.omschrijving,
            "omschrijving_herkomst": prefill.omschrijving_herkomst,
            # Blok 11: factuurperiode zoals de prefill 'm afleidde (informatief; de kolommen zijn de stand).
            "periode": _periode_snapshot(prefill.periode),
        },
        "regels": [_regel_snapshot(i, r) for i, r in enumerate(regels, start=1)],
    }


def _prefill_triggers(prefill: BoekvoorstelData, regels: list[BoekvoorstelRegelData], veldvoorstel: dict) -> list[str]:
    """Leesbare redenen waarom de prefill gepersisteerd wordt (leeg = niet persisteren)."""
    triggers: list[str] = []
    if veldvoorstel.get("bron") == "template":
        triggers.append("kop: template")
    if is_ubl_veldvoorstel(veldvoorstel):
        # Blok 3 herstelrun 08-09: een UBL-kop is deterministisch (geen AI-gok) — altijd persisteren, zodat lijst,
        # checks en duplicaat-motor dezelfde stand zien als de mens (vóór én bij het openen).
        triggers.append("kop: ubl")
    if prefill.afdeling_prefill_id is not None:
        triggers.append("afdeling: leverancier_geheugen")
    # Blok 11: een periode die de factuur zélf noemt (week/datumbereik/maand) triggert de autosave — de terugval uit de
    # factuurdatum niet (die is altijd live af te leiden; persisteren zou een AI-only prefill alsnog opslaan).
    if prefill.periode is not None and prefill.periode.herkomst in periode_regels.HERKOMSTEN_UIT_FACTUUR:
        triggers.append(f"periode: {prefill.periode.herkomst}")
    for i, regel in enumerate(regels, start=1):
        for veld, bron in (regel.prefill_herkomst or {}).items():
            if bron in _AUTOSAVE_HERKOMSTEN or (veld == "project" and bron in _PROJECT_FACTUUR_HERKOMSTEN):
                triggers.append(f"{veld} regel {i}: {bron}")
    return triggers


def _effectieve_regels(prefill: BoekvoorstelData) -> list[BoekvoorstelRegelData]:
    """De regels zoals het controlescherm ze toont (en de PUT ze zou sturen): samengevoegd = de ene
    samengevoegde regel, anders de gesplitste regels — zelfde keuze als autoboeken.py."""
    if prefill.regels_samenvoegen and prefill.samengevoegde_regel is not None:
        return [prefill.samengevoegde_regel]
    return list(prefill.regels)


def _laatste_prefill_snapshot(gebeurtenissen: list[DocumentGebeurtenis]) -> DocumentGebeurtenis | None:
    return next(
        (g for g in reversed(gebeurtenissen) if g.detail and PREFILL_SNAPSHOT_SLEUTEL in g.detail),
        None,
    )


def _laatste_veldvoorstel_gebeurtenis(gebeurtenissen: list[DocumentGebeurtenis]) -> DocumentGebeurtenis | None:
    return next((g for g in reversed(gebeurtenissen) if g.detail and "veldvoorstel" in g.detail), None)


def _regel_komt_overeen(regel: BoekvoorstelRegel, snap: dict) -> bool:
    """Match voor het herstel van de herkomst-chips: zelfde plek én zelfde omschrijving (een verplaatste/
    andere regel krijgt nooit de chip van een ander)."""
    return regel.volgnummer == snap.get("volgnummer") and (regel.omschrijving or None) == snap.get("omschrijving")


def _regel_onaangeraakt(regel: BoekvoorstelRegel, snap: dict) -> bool:
    return (
        _regel_komt_overeen(regel, snap)
        and _str_of_none(regel.ledger_id) == snap.get("ledger_id")
        and _str_of_none(regel.taxrate_id) == snap.get("taxrate_id")
        and _str_of_none(regel.project_id) == snap.get("project_id")
        and _str_of_none(regel.netto_bedrag) == snap.get("netto_bedrag")
        and _str_of_none(regel.btw_bedrag) == snap.get("btw_bedrag")
    )


def _kop_onaangeraakt(bestaand: Boekvoorstel, kop: dict) -> bool:
    return (
        _str_of_none(bestaand.vendor_id) == kop.get("vendor_id")
        and (bestaand.referentie or None) == kop.get("referentie")
        and _str_of_none(bestaand.factuurdatum) == kop.get("factuurdatum")
        and _str_of_none(bestaand.totaalbedrag) == kop.get("totaalbedrag")
        # Blok 11: een door de mens gecorrigeerde periode is een kop-wijziging (een verse extractie mag 'm niet
        # overschrijven).
        and bestaand.periode_herkomst != periode_regels.HERKOMST_MENS
    )


# --- factuurperiode (blok 11 vervolgrun 07-09) -------------------------------------------------------------------
# De normalisatie is puur (periode.py); hier de koppeling met het voorstel: automatische stand uit veldvoorstel +
# factuurdatum, de opgeslagen kolommen als bron zodra ze gevuld zijn, en de mens-correctie via de PUT (waarde ≠
# automatische afleiding → herkomst `mens`, wint; gelijk → automatisch blijft meebewegen — dezelfde regel als de
# kop-omschrijving en de A10-chips).


def _periode_snapshot(periode: periode_regels.FactuurPeriode | None) -> dict | None:
    if periode is None:
        return None
    return {
        "jaar": periode.jaar,
        "week_van": periode.week_van,
        "week_tot": periode.week_tot,
        "herkomst": periode.herkomst,
        "tekst": periode.tekst,
    }


def _automatische_periode(veldvoorstel: dict | None, factuurdatum: date | None) -> periode_regels.FactuurPeriode | None:
    return periode_regels.bepaal_periode((veldvoorstel or {}).get("periode_tekst"), factuurdatum=factuurdatum)


def _opgeslagen_periode(bestaand: Boekvoorstel, veldvoorstel: dict | None) -> periode_regels.FactuurPeriode | None:
    """De kolommen zijn de stand; een voorstel van vóór 0120 (kolommen leeg) krijgt de automatische afleiding live
    (niet-opgeslagen) — de eerstvolgende PUT of autosave persisteert 'm."""
    if bestaand.periode_jaar is not None and bestaand.periode_week_van is not None and bestaand.periode_herkomst:
        return periode_regels.FactuurPeriode(
            jaar=bestaand.periode_jaar,
            week_van=bestaand.periode_week_van,
            week_tot=bestaand.periode_week_tot if bestaand.periode_week_tot is not None else bestaand.periode_week_van,
            herkomst=bestaand.periode_herkomst,
            tekst=bestaand.periode_tekst,
        )
    return _automatische_periode(veldvoorstel, bestaand.factuurdatum)


def _verwerk_periode(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document: Document,
    actor_id: uuid.UUID,
    bestaand: Boekvoorstel,
    factuurdatum: date | None,
    periode: tuple[int, int, int] | None,
    autosave: bool,
) -> None:
    """Zet de periode-kolommen. `periode` = (jaar, week_van, week_tot) zoals de client 'm toont/de mens 'm liet
    staan; None = niet meegegeven (oude client/autoboeken) → de opgeslagen stand blijft, of — nog leeg — de
    automatische afleiding wordt gepersisteerd. Gelijk aan de automatische afleiding = automatische herkomst;
    afwijkend = `mens`. De ruwe factuurtekst blijft altijd staan. Een échte wijziging van de stand door een mens
    wordt geaudit (oud→nieuw); de autosave staat al in het prefill-snapshot + zijn eigen audit-event."""
    veldvoorstel = _laatste_veldvoorstel(session, document.id)
    auto = _automatische_periode(veldvoorstel, factuurdatum)
    oud = _opgeslagen_periode(bestaand, veldvoorstel) if bestaand.periode_herkomst else None
    if periode is None:
        nieuw = oud if oud is not None else auto
    elif auto is not None and auto.sleutel == tuple(periode):
        nieuw = auto
    else:
        jaar, week_van, week_tot = periode
        try:
            nieuw = periode_regels.maak_periode(
                jaar,
                week_van,
                week_tot,
                herkomst=periode_regels.HERKOMST_MENS,
                tekst=auto.tekst if auto is not None else (oud.tekst if oud is not None else None),
            )
        except periode_regels.OngeldigePeriode as exc:
            raise BoekvoorstelFout(f"Ongeldige periode: {exc}") from exc
    bestaand.periode_jaar = nieuw.jaar if nieuw else None
    bestaand.periode_week_van = nieuw.week_van if nieuw else None
    bestaand.periode_week_tot = nieuw.week_tot if nieuw else None
    bestaand.periode_herkomst = nieuw.herkomst if nieuw else None
    bestaand.periode_tekst = nieuw.tekst if nieuw else None
    if autosave or _periode_snapshot(oud) == _periode_snapshot(nieuw):
        return
    if oud is None and nieuw is not None and nieuw.herkomst != periode_regels.HERKOMST_MENS:
        return  # eerste persist van de automatische afleiding (voorstel van vóór 0120) — geen mens-handeling
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="boekvoorstel",
        record_id=document.id,
        actie="boekvoorstel_periode_gewijzigd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"periode": _periode_snapshot(oud)},
        nieuwe_waarde={"periode": _periode_snapshot(nieuw)},
        administratie_id=administratie_id,
    )


def _voorstel_onaangeraakt(bestaand: Boekvoorstel, regels: list[BoekvoorstelRegel], snapshot: dict) -> bool:
    snaps = snapshot.get("regels") or []
    if len(snaps) != len(regels):
        return False
    return _kop_onaangeraakt(bestaand, snapshot.get("kop") or {}) and all(
        _regel_onaangeraakt(regel, snap) for regel, snap in zip(regels, snaps, strict=True)
    )


def _opgeslagen_regel_data(regel: BoekvoorstelRegel, snapshot: dict | None) -> BoekvoorstelRegelData:
    """Opgeslagen regel → data, mét herstelde herkomst-chips per veld zolang de waarde nog de
    autosave-prefill is (waarde-gelijkheid; een gewijzigd veld verliest zijn chip, bewust)."""
    snap = None
    if snapshot is not None:
        snap = next((x for x in snapshot.get("regels") or [] if _regel_komt_overeen(regel, x)), None)
    gb_bron = gb_detail = btw_bron = btw_detail = project_bron = project_detail = None
    herkomst: dict[str, str] = {}
    if snap is not None:
        snap_herkomst = snap.get("herkomst") or {}
        if regel.ledger_id is not None and _str_of_none(regel.ledger_id) == snap.get("ledger_id"):
            gb_bron, gb_detail = snap.get("gb_bron"), snap.get("gb_voorstel_detail")
            if "grootboek" in snap_herkomst:
                herkomst["grootboek"] = snap_herkomst["grootboek"]
        if regel.taxrate_id is not None and _str_of_none(regel.taxrate_id) == snap.get("taxrate_id"):
            btw_bron, btw_detail = snap.get("btw_bron"), snap.get("btw_bron_detail")
            if "btw" in snap_herkomst:
                herkomst["btw"] = snap_herkomst["btw"]
        if (
            regel.project_id is not None
            and _str_of_none(regel.project_id) == snap.get("project_id")
            and "project" in snap_herkomst
        ):
            herkomst["project"] = snap_herkomst["project"]
            project_bron, project_detail = snap.get("project_bron"), snap.get("project_bron_detail")
        elif regel.project_id is None and snap.get("project_id") is None and snap.get("project_bron"):
            # Blok 10: "meerdere projecten passen" — niets ingevuld, de kandidaten-chip blijft tot de mens kiest.
            project_bron, project_detail = snap.get("project_bron"), snap.get("project_bron_detail")
    return BoekvoorstelRegelData(
        ledger_id=regel.ledger_id,
        taxrate_id=regel.taxrate_id,
        project_id=regel.project_id,
        netto_bedrag=regel.netto_bedrag,
        btw_bedrag=regel.btw_bedrag,
        omschrijving=regel.omschrijving,
        id=regel.id,
        btw_bron=btw_bron,
        btw_bron_detail=btw_detail if btw_bron else None,
        gb_bron=gb_bron,
        gb_voorstel_detail=gb_detail if gb_bron else None,
        overstap_vertaling=regel.overstap_vertaling,
        prefill_herkomst=herkomst or None,
        project_bron=project_bron,
        project_bron_detail=project_detail if project_bron else None,
    )


def _lees_opgeslagen_voorstel(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bestaand: Boekvoorstel,
    gebeurtenissen: list[DocumentGebeurtenis],
    project_verplicht: bool,
    standaard_samenvoegen: bool,
) -> BoekvoorstelData:
    document_id = bestaand.document_id
    # B13 07-09: een crediteur die intussen VERLIEZER van een afgehandeld dubbel-cluster werd, wordt bij het openen
    # doorvertaald naar de voorkeur (de afhandeling hervertaalt open voorstellen al persistent mét audit; dit is het
    # vangnet voor een race). Eén bron: crediteuren/voorkeur.py.
    from app.crediteuren.voorkeur import voorkeur_van

    vendor_id = voorkeur_van(session, administratie_id=administratie_id, vendor_id=bestaand.vendor_id)
    veldvoorstel = _laatste_veldvoorstel(session, document_id)
    regels = session.scalars(
        select(BoekvoorstelRegel)
        .where(BoekvoorstelRegel.document_id == document_id)
        .order_by(BoekvoorstelRegel.volgnummer)
    ).all()
    snapshot_gebeurtenis = _laatste_prefill_snapshot(gebeurtenissen)
    snapshot = snapshot_gebeurtenis.detail[PREFILL_SNAPSHOT_SLEUTEL] if snapshot_gebeurtenis is not None else None
    kop = (snapshot or {}).get("kop") or {}
    prefill_automatisch = snapshot is not None and _kop_onaangeraakt(bestaand, kop)
    afdeling = _afdeling_velden(
        session,
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        huidige_afdeling_id=bestaand.afdeling_id,
    )
    # Afdeling-prefill (blok A 28-08) is bij de autosave als KEUZE weggeschreven — de chip "vorige keuze bij
    # <leverancier>" blijft staan zolang de waarde de prefill is (zelfde waarde-gelijkheid als de regels).
    if (
        snapshot is not None
        and bestaand.afdeling_id is not None
        and kop.get("afdeling_prefill_id") == str(bestaand.afdeling_id)
        and "afdeling_prefill_id" in afdeling
    ):
        afdeling["afdeling_prefill_id"] = bestaand.afdeling_id
        afdeling["afdeling_prefill_leverancier"] = kop.get("afdeling_prefill_leverancier")
    regel_data = [_opgeslagen_regel_data(r, snapshot) for r in regels]
    data = _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
        document_id=document_id,
        vendor_id=vendor_id,
        referentie=bestaand.referentie,
        factuurdatum=bestaand.factuurdatum,
        vervaldatum=bestaand.vervaldatum,
        vervaldatum_signaal=vervaldatum_signaal(factuurdatum=bestaand.factuurdatum, vervaldatum=bestaand.vervaldatum),
        betalingskenmerk=bestaand.betalingskenmerk,
        totaalbedrag=bestaand.totaalbedrag,
        rlz_boekstuknummer=bestaand.rlz_boekstuknummer,
        opgeslagen=True,
        regels=regel_data,
        boek_cyclus=bestaand.boek_cyclus,
        btw_verlegd_vermelding=_verlegd_vermelding(veldvoorstel),
        prefill_automatisch=prefill_automatisch,
        periode=_opgeslagen_periode(bestaand, veldvoorstel),
        **_samenvoeg_velden(
            session,
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            veldvoorstel=veldvoorstel,
            project_verplicht=project_verplicht,
            standaard_samenvoegen=standaard_samenvoegen,
        ),
        **afdeling,
    ))
    # Blok 9: kop-omschrijving over de OPGESLAGEN regels (= wat de motoren boeken); mens-override uit de tijdlijn wint.
    return _met_kop_omschrijving(
        session,
        administratie_id=administratie_id,
        data=data,
        regels=regel_data,
        veldvoorstel=veldvoorstel,
        gebeurtenissen=gebeurtenissen,
    )


def _bereken_prefill(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    veldvoorstel: dict | None,
    project_verplicht: bool,
    standaard_samenvoegen: bool,
) -> BoekvoorstelData:
    """Het NIET-opgeslagen voorstel: prefill uit het veldvoorstel (UBL deterministisch geparst, of het AI-/
    template-voorstel uit app/extractie/ — zelfde tijdlijn-sleutel), verrijkt met regel-geheugen, leverancier-
    geheugen en btw-default (regel_prefill.py). Geen veldvoorstel = volledig leeg voorstel."""
    if veldvoorstel is None:
        return _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
            document_id=document_id,
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            rlz_boekstuknummer=None,
            opgeslagen=False,
            regels=[],
            **_samenvoeg_velden(
                session,
                administratie_id=administratie_id,
                vendor_id=None,
                veldvoorstel=None,
                project_verplicht=project_verplicht,
                standaard_samenvoegen=standaard_samenvoegen,
            ),
            **_afdeling_velden(session, administratie_id=administratie_id, vendor_id=None, huidige_afdeling_id=None),
        ))

    # Blok 3 08-09: UBL-CreditNote → negatieve totalen (regels: `_regel_prefill_uit_ubl`).
    veldvoorstel = _veldvoorstel_met_teken(veldvoorstel) or veldvoorstel
    # AI-voorstellen dragen een vendor-suggestie uit de controlelaag (exacte of fuzzy match
    # tegen de vendor-cache, alleen bij een uniek resultaat); anders de bestaande exacte
    # naammatch. In beide gevallen een voorstel dat de controleur kan overschrijven.
    suggestie = veldvoorstel.get("vendor_suggestie")
    vendor_id = _als_uuid(suggestie.get("vendor_id")) if isinstance(suggestie, dict) else None
    # B13 07-09: een oud AI-veldvoorstel kan een intussen afgehandelde VERLIEZER suggereren → voorkeur.
    from app.crediteuren.voorkeur import voorkeur_van

    vendor_id = voorkeur_van(session, administratie_id=administratie_id, vendor_id=vendor_id)
    if vendor_id is None:
        vendor_id = _raad_vendor_id(
            session, administratie_id=administratie_id, leverancier_naam=veldvoorstel.get("leverancier_naam")
        )
    if vendor_id is None:
        # Blok 3 herstelrun 08-09: een UBL draagt KvK/btw/IBAN — live matchen (btw → KvK → IBAN → naam incl.
        # fuzzy mét mismatch-guard), ook voor UBL-voorstellen van vóór 08-09 en ná het aanmaken van de crediteur.
        from app.documenten import ubl_voorstel  # lokaal: ubl_voorstel leest crediteur_kenmerk

        vendor_id = ubl_voorstel.raad_vendor_id(session, administratie_id=administratie_id, veldvoorstel=veldvoorstel)
    # Blok D + E (medewerker-wensen 04-09) + A10 (07-09): regel-GB-voorstel (regel-geheugen → persistente
    # AI-classificatie), leverancier-geheugen (kop-niveau-engine, server-side sinds 07-09) en btw-default van de
    # administratie — uitsluitend op dit prefill-pad; een opgeslagen keuze van de mens wint altijd.
    from app.documenten import regel_prefill  # lokaal: regel_prefill leest de dataclass hierboven

    samenvoeg = _samenvoeg_velden(
        session,
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        veldvoorstel=veldvoorstel,
        project_verplicht=project_verplicht,
        standaard_samenvoegen=standaard_samenvoegen,
    )
    prefill_regels, samenvoeg["samengevoegde_regel"] = regel_prefill.verrijk_prefill(
        session,
        administratie_id=administratie_id,
        document_id=document_id,
        vendor_id=vendor_id,
        regels=_regels_prefill(veldvoorstel),
        samengevoegde_regel=samenvoeg["samengevoegde_regel"],
        project_verplicht=project_verplicht,
        kop_project_tekst=veldvoorstel_regels.kop_project_tekst(veldvoorstel),
        # Blok 4c (08-09): "btw verlegd" op de factuur + btw 0 → verlegd-tarief voorstellen (oranje, vóór de default).
        factuur_verlegd=_factuur_is_verlegd(veldvoorstel),
    )
    data = _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
        document_id=document_id,
        vendor_id=vendor_id,
        referentie=veldvoorstel.get("factuurnummer"),
        factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
        vervaldatum=_als_datum(veldvoorstel.get("vervaldatum")),
        vervaldatum_signaal=vervaldatum_signaal(
            factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
            vervaldatum=_als_datum(veldvoorstel.get("vervaldatum")),
        ),
        betalingskenmerk=(veldvoorstel.get("betalingskenmerk") or None),
        totaalbedrag=_als_decimal(veldvoorstel.get("totaal_incl")),
        rlz_boekstuknummer=None,
        opgeslagen=False,
        regels=prefill_regels,
        btw_verlegd_vermelding=_verlegd_vermelding(veldvoorstel),
        # Blok 11: voorgelezen periode → ISO-weken (deterministisch), anders de week van de factuurdatum.
        periode=_automatische_periode(veldvoorstel, _als_datum(veldvoorstel.get("factuurdatum"))),
        **samenvoeg,
        **_afdeling_velden(session, administratie_id=administratie_id, vendor_id=vendor_id, huidige_afdeling_id=None),
    ))
    # Blok 9: kop-omschrijving over de regels zoals het scherm ze toont (samengevoegd = de ene regel); nog geen
    # opgeslagen voorstel, dus geen mens-override mogelijk.
    return _met_kop_omschrijving(
        session,
        administratie_id=administratie_id,
        data=data,
        regels=_effectieve_regels(data),
        veldvoorstel=veldvoorstel,
        gebeurtenissen=None,
    )


def haal_boekvoorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> BoekvoorstelData:
    """Het opgeslagen boekvoorstel, of — als er nog niets opgeslagen is — een niet-opgeslagen
    voorstel op basis van het veldvoorstel (CLAUDE.md-taak 2.1: "veldvoorstellen (UBL)
    vooringevuld waar aanwezig"). PDF-documenten zonder extractie krijgen een volledig leeg
    voorstel — de controleur vult alles handmatig in. Leest alleen; het persisteren van de prefill
    bij het openen doet `persisteer_prefill_bij_openen` (GET-router)."""
    project_verplicht = _project_verplicht(administratie_id)
    standaard_samenvoegen = standaard_regels_samenvoegen(administratie_id)

    with scoped_session(administratie_id) as session:
        _laad_document(session, document_id=document_id)
        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is not None:
            return _lees_opgeslagen_voorstel(
                session,
                administratie_id=administratie_id,
                bestaand=bestaand,
                gebeurtenissen=_gebeurtenissen_van(session, document_id),
                project_verplicht=project_verplicht,
                standaard_samenvoegen=standaard_samenvoegen,
            )
        return _bereken_prefill(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            veldvoorstel=_laatste_veldvoorstel(session, document_id),
            project_verplicht=project_verplicht,
            standaard_samenvoegen=standaard_samenvoegen,
        )


def boekvoorstel_door_mens_aangeraakt(session: Session, *, document_id: uuid.UUID) -> bool:
    """Is er een boekvoorstel waar een MENS aan gewerkt heeft? Blok 3 herstelrun 08-09: sinds een UBL-kop bij intake
    (en elke prefill bij openen) machinaal gepersisteerd wordt, is "er bestaat een boekvoorstel-rij" geen bewijs meer
    van menselijke beoordeling. Mens-aangeraakt = een rij zónder prefill-snapshot (door een mens opgeslagen) óf een rij
    waarvan de waarden afwijken van het laatste snapshot (`_voorstel_onaangeraakt`). Eén bron voor de nabundel-motor
    (`intake/nabundelen.py`: "nooit een door een mens beoordeeld exemplaar aanraken") en elke andere poort die
    "heeft een boekvoorstel" als mens-signaal las."""
    bestaand = session.get(Boekvoorstel, document_id)
    if bestaand is None:
        return False
    snapshot = _laatste_prefill_snapshot(_gebeurtenissen_van(session, document_id))
    if snapshot is None:
        return True
    regels_db = session.scalars(
        select(BoekvoorstelRegel)
        .where(BoekvoorstelRegel.document_id == document_id)
        .order_by(BoekvoorstelRegel.volgnummer)
    ).all()
    return not _voorstel_onaangeraakt(bestaand, regels_db, snapshot.detail[PREFILL_SNAPSHOT_SLEUTEL])


def persisteer_ubl_prefill_na_intake(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """Blok 3 herstelrun 08-09: direct ná de (synchrone) UBL-extractie de prefill persisteren — hetzelfde
    A10-pad als bij het openen, met de systeem-actor en snapshot-bron `intake`. Alleen voor een UBL-veldvoorstel
    (`is_ubl_veldvoorstel`); een PDF wacht op zijn extractie en volgt het openen-pad. True = geschreven."""
    with scoped_session(administratie_id) as session:
        veldvoorstel = _laatste_veldvoorstel(session, document_id)
    if not is_ubl_veldvoorstel(veldvoorstel):
        return False
    return persisteer_prefill_bij_openen(
        administratie_id=administratie_id, document_id=document_id, geopend_door=SYSTEEM_ACTOR_ID, aanleiding="intake"
    )


def persisteer_prefill_bij_openen(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, geopend_door: uuid.UUID, aanleiding: str = "openen"
) -> bool:
    """Blok A10 07-09 (opdracht Peter, auto-first): persisteer bij het openen van het controlescherm de prefill
    zodra die minstens één veld uit geheugen/template/default draagt (`_AUTOSAVE_HERKOMSTEN`), zodat de checks en
    het doorbelasten-blok exact zien wat de mens ziet. Geeft True terug als er geschreven is.

    Poorten (fail-closed, in deze volgorde): bewerkbare status én inkoopfactuur; een veldvoorstel (zonder
    extractie is er niets eenduidigs — een leeg voorstel persisteren zou een latere extractie stil verbergen);
    géén bestaand voorstel — óf een bestaand voorstel dat (a) zelf een autosave is, (b) sindsdien niet door een
    mens is aangeraakt (waarde-gelijkheid met het snapshot) én (c) een NIEUWER veldvoorstel heeft (opnieuw
    extraheren): dan wordt de prefill opnieuw afgeleid en overschreven. Een door een mens opgeslagen voorstel
    wordt nooit geraakt. Schrijft onder de systeem-actor (de waarden zijn machinaal afgeleid; de opener staat in
    het audit-event als `geopend_door`). Een fout in de autosave blokkeert het openen nooit (gelogd; het
    scherm toont dan de niet-opgeslagen prefill zoals voorheen); een parallelle GET die net eerder schreef =
    IntegrityError op de PK = geen fout."""
    project_verplicht = _project_verplicht(administratie_id)
    standaard_samenvoegen = standaard_regels_samenvoegen(administratie_id)
    with scoped_session(administratie_id) as session:
        document = _laad_document(session, document_id=document_id)
        if document.status not in _AUTOSAVE_STATUSSEN or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return False
        gebeurtenissen = _gebeurtenissen_van(session, document_id)
        veldvoorstel_gebeurtenis = _laatste_veldvoorstel_gebeurtenis(gebeurtenissen)
        if veldvoorstel_gebeurtenis is None:
            return False
        veldvoorstel = veldvoorstel_gebeurtenis.detail["veldvoorstel"]
        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is not None:
            snapshot_gebeurtenis = _laatste_prefill_snapshot(gebeurtenissen)
            if snapshot_gebeurtenis is None:
                return False  # door een mens opgeslagen — nooit raken
            if veldvoorstel_gebeurtenis.tijdstip <= snapshot_gebeurtenis.tijdstip:
                return False  # al gepersisteerd op basis van dit veldvoorstel (idempotent)
            regels_db = session.scalars(
                select(BoekvoorstelRegel)
                .where(BoekvoorstelRegel.document_id == document_id)
                .order_by(BoekvoorstelRegel.volgnummer)
            ).all()
            if not _voorstel_onaangeraakt(bestaand, regels_db, snapshot_gebeurtenis.detail[PREFILL_SNAPSHOT_SLEUTEL]):
                return False  # de mens heeft er intussen aan gewerkt — zijn keuzes winnen van de verse extractie
        prefill = _bereken_prefill(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            veldvoorstel=veldvoorstel,
            project_verplicht=project_verplicht,
            standaard_samenvoegen=standaard_samenvoegen,
        )
        regels = _effectieve_regels(prefill)
        triggers = _prefill_triggers(prefill, regels, veldvoorstel)
        if not triggers:
            return False
        snapshot = _maak_prefill_snapshot(
            prefill,
            regels=regels,
            veldvoorstel=veldvoorstel,
            triggers=triggers,
            geopend_door=geopend_door,
            aanleiding=aanleiding,
        )

    try:
        sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            vendor_id=prefill.vendor_id,
            referentie=prefill.referentie,
            factuurdatum=prefill.factuurdatum,
            vervaldatum=prefill.vervaldatum,
            betalingskenmerk=prefill.betalingskenmerk,
            totaalbedrag=prefill.totaalbedrag,
            regels=regels,
            afdeling_id=prefill.afdeling_prefill_id,
            periode=prefill.periode.sleutel if prefill.periode is not None else None,
            prefill_snapshot=snapshot,
        )
    except IntegrityError:
        # Twee GET's tegelijk (controlescherm + doorbelasten-blok openen beide het voorstel): de ander won.
        logger.info("Prefill-autosave voor document %s al door een parallelle aanvraag gedaan", document_id)
        return False
    except Exception:  # noqa: BLE001 — de autosave is een verbetering, nooit een blokkade van het openen
        logger.exception("Prefill-autosave bij openen mislukt voor document %s", document_id)
        return False
    return True


def _gebeurtenissen_van(session: Session, document_id: uuid.UUID) -> list[DocumentGebeurtenis]:
    return list(
        session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        )
    )


def sla_boekvoorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[BoekvoorstelRegelData],
    regels_samenvoegen: bool | None = None,
    vervaldatum: date | None = None,
    afdeling_id: uuid.UUID | None = None,
    betalingskenmerk: str | None = None,
    prefill_snapshot: dict | None = None,
    omschrijving: str | None = None,
    periode: tuple[int, int, int] | None = None,
) -> BoekvoorstelData:
    """`periode` (blok 11 vervolgrun 07-09) = (jaar, week_van, week_tot) zoals de client 'm toont; None = niet
    meegegeven (oude client/autoboeken) → opgeslagen stand blijft, of de automatische afleiding wordt gepersisteerd.
    Gelijk aan de automatische afleiding = automatische herkomst; afwijkend = `mens` (wint). Zie `_verwerk_periode`.

    `omschrijving` (blok 9 vervolgrun 07-09) = de kop-omschrijving zoals de mens 'm in het veld liet staan.
    None = niet meegegeven (oude client/autosave/autoboeken): niets aan de omschrijving gedaan. Gelijk aan de
    automatische afleiding (of leeg) = geen override — de omschrijving blijft automatisch meebewegen; anders
    wordt de tekst als mens-override bewaard (tijdlijn-notitie `kop_omschrijving` + audit oud→nieuw) en wint
    voortaan altijd (herkomst "handmatig"). Leegmaken ná een override = terug naar automatisch (`tekst: null`).

    `prefill_snapshot` (blok A10 07-09) ≠ None = AUTOSAVE van de prefill bij het openen
    (`persisteer_prefill_bij_openen`): zelfde schrijfpad, maar (1) géén leerlus-bijeffecten die een
    MENSELIJKE bevestiging veronderstellen — crediteur-kenmerk (btw-/KvK-nummer) onthouden, afdeling-
    keuze per leverancier onthouden, samenvoeg-voorkeur — de autosave mag het geheugen nooit met zijn
    eigen voorstel voeden; (2) audit-actie `boekvoorstel_prefill_opgeslagen` mét de herkomst per veld
    + wie opende; (3) een tijdlijn-notitie (status blijft) met het snapshot, waaruit de leesroute de
    herkomst-chips herstelt en de idempotentie/staleness toetst.

    `regels_samenvoegen` (fix 3) is de weergavekeuze van de controleur op het moment van
    opslaan — die wordt als voorkeur per (administratie, crediteur) onthouden. None = niet
    meegegeven (bv. oude client of geen crediteur gekozen): voorkeur blijft ongemoeid. Bij
    projectplicht wordt de keuze genegeerd — daar is per-regel hard.

    `afdeling_id` (blok A 28-08): de handmatige afdelingskeuze; moet een afdeling van déze
    administratie zijn (gearchiveerd mag opgeslagen worden — de check blokkeert dan zichtbaar).
    Mét crediteur wordt de keuze als leverancier-geheugen onthouden (laatste wint). Verandert de
    afdeling terwijl een accorderingsronde open staat, dan vervalt die ronde zichtbaar mét reden
    (zelfde regel als een configuratiewijziging)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, document_id=document_id)
        _controleer_niet_bevroren(document)

        if afdeling_id is not None:
            from app.afdelingen.models import Afdeling

            afdeling = session.get(Afdeling, afdeling_id)
            if afdeling is None or afdeling.administratie_id != administratie_id:
                raise BoekvoorstelFout("Onbekende afdeling voor deze administratie")

        bestaand = session.get(Boekvoorstel, document_id)
        was_nieuw = bestaand is None
        if bestaand is None:
            bestaand = Boekvoorstel(document_id=document_id)
            session.add(bestaand)
        oude_afdeling_id = bestaand.afdeling_id
        bestaand.vendor_id = vendor_id
        bestaand.referentie = referentie
        bestaand.factuurdatum = factuurdatum
        bestaand.vervaldatum = vervaldatum
        bestaand.betalingskenmerk = (" ".join(betalingskenmerk.split()) or None) if betalingskenmerk else None
        bestaand.afdeling_id = afdeling_id
        autosave = prefill_snapshot is not None
        if afdeling_id is not None and vendor_id is not None and not autosave:
            from app.afdelingen.service import onthoud_keuze

            onthoud_keuze(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                afdeling_id=afdeling_id,
                document_id=document_id,
                actor_id=actor_id,
            )
        if oude_afdeling_id != afdeling_id and document.status == DocumentStatus.TER_ACCORDERING:
            from app.accordering.service import laat_ronde_vervallen_bij_afdelingwijziging

            laat_ronde_vervallen_bij_afdelingwijziging(
                session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
            )
        # Punt 14 (28-08): het btw-/KvK-nummer van de factuur per crediteur onthouden zodra de mens de
        # crediteur bevestigt (opslaan mét vendor) — voedt nummer-match, cross-crediteur-check en de
        # dubbel-signalering. Lazy import: crediteur_kenmerk gebruikt de extractie-controlelaag.
        if vendor_id is not None and not autosave:
            from app.documenten.crediteur_kenmerk import neem_over_uit_veldvoorstel

            neem_over_uit_veldvoorstel(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                veldvoorstel=_laatste_veldvoorstel(session, document_id),
                document_id=document_id,
                actor_id=actor_id,
            )
        bestaand.totaalbedrag = totaalbedrag
        # Blok 11: factuurperiode (kolommen 0120) — automatische afleiding of mens-correctie, audit bij echte wijziging.
        _verwerk_periode(
            session,
            administratie_id=administratie_id,
            document=document,
            actor_id=actor_id,
            bestaand=bestaand,
            factuurdatum=factuurdatum,
            periode=periode,
            autosave=autosave,
        )

        # Klaargezette doorbelasting (besluit 25-08) verwijst per regel-id — over de
        # delete+insert heen meenemen per volgnummer. Lazy import: doorbelasting.service
        # gebruikt deze module-familie (geen kringimport op moduleniveau).
        from app.doorbelasting import service as doorbelasting_service

        verdeling_snapshot = doorbelasting_service.neem_klaargezette_verdeling_los(session, document_id=document_id)
        oude_regels_snapshot: dict | None = None
        if prefill_snapshot is not None and not was_nieuw:
            # Her-autosave ná een verse extractie (persisteer_prefill_bij_openen): de vorige stand in het audit-event.
            oude_regels = session.scalars(
                select(BoekvoorstelRegel)
                .where(BoekvoorstelRegel.document_id == document_id)
                .order_by(BoekvoorstelRegel.volgnummer)
            ).all()
            if oude_regels:
                oude_regels_snapshot = {
                    "opgeslagen": True,
                    "regels": [
                        {
                            "volgnummer": r.volgnummer,
                            "ledger_id": _str_of_none(r.ledger_id),
                            "taxrate_id": _str_of_none(r.taxrate_id),
                            "netto_bedrag": _str_of_none(r.netto_bedrag),
                        }
                        for r in oude_regels
                    ],
                }
        session.execute(delete(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        nieuwe_regels: list[BoekvoorstelRegel] = []
        for i, regel in enumerate(regels, start=1):
            nieuwe_regel = BoekvoorstelRegel(
                document_id=document_id,
                volgnummer=i,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving=regel.omschrijving,
            )
            session.add(nieuwe_regel)
            nieuwe_regels.append(nieuwe_regel)
        if verdeling_snapshot is not None:
            session.flush()
            doorbelasting_service.zet_klaargezette_verdeling_terug(
                session,
                snapshot=verdeling_snapshot,
                nieuwe_regels={r.volgnummer: r.id for r in nieuwe_regels},
            )

        if (
            regels_samenvoegen is not None
            and vendor_id is not None
            and not autosave
            and not _project_verplicht(administratie_id)
        ):
            _onthoud_voorkeur_samenvoegen(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                actor_id=actor_id,
                regels_samenvoegen=regels_samenvoegen,
            )

        if omschrijving is not None and not autosave:
            _verwerk_kop_omschrijving(
                session,
                administratie_id=administratie_id,
                document=document,
                actor_id=actor_id,
                vendor_id=vendor_id,
                referentie=referentie,
                regels=regels,
                ingevoerd=omschrijving,
            )

        if autosave:
            assert prefill_snapshot is not None
            # Eén tijdlijn-notitie (status blijft) + één audit-event per autosave; de herkomst per veld staat in
            # beide (audit: oud = leeg voorstel / de vorige autosave-stand, nieuw = de gepersisteerde prefill).
            session.add(
                DocumentGebeurtenis(
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={PREFILL_SNAPSHOT_SLEUTEL: prefill_snapshot},
                )
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="boekvoorstel",
                record_id=document_id,
                actie="boekvoorstel_prefill_opgeslagen",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"opgeslagen": False} if oude_regels_snapshot is None else oude_regels_snapshot,
                nieuwe_waarde={
                    "referentie": referentie,
                    "aantal_regels": len(regels),
                    "afdeling_id": str(afdeling_id) if afdeling_id else None,
                    "geopend_door": prefill_snapshot.get("geopend_door"),
                    "triggers": prefill_snapshot.get("triggers"),
                    "herkomst_per_regel": [
                        {"volgnummer": r["volgnummer"], **r["herkomst"]} for r in prefill_snapshot.get("regels", [])
                    ],
                },
                administratie_id=administratie_id,
            )
        else:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="boekvoorstel",
                record_id=document_id,
                actie="boekvoorstel_opgeslagen",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "referentie": referentie,
                    "aantal_regels": len(regels),
                    "afdeling_id": str(afdeling_id) if afdeling_id else None,
                },
                administratie_id=administratie_id,
            )

    # Factuurmatch (fase 2): ná élke voorstel-opslag herberekenen — crediteur, factuurdatum en
    # regelbedragen sturen alle drie de match. Post-commit en onder de systeem-actor (de
    # lees-policy op de bureau-tarieven is actor-gebonden, 0057); een fout is een gelogde
    # waarschuwing — de match is signalering, nooit een blokkade van de opslag.
    from app.uren import factuurmatch_pipeline  # lokaal: houdt de importgraaf klein

    try:
        factuurmatch_pipeline.draai_match_voor_document(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — de match is signalering, nooit een blokkade
        logger.exception("Factuurmatch-run na voorstel-opslag mislukt voor document %s", document_id)
    # Materiaalmatch (steigerbouw-run D6): crediteur, project en factuurdatum sturen de toets.
    from app.materiaal import match as materiaalmatch  # lokaal: houdt de importgraaf klein

    try:
        materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
        logger.exception("Materiaalmatch-run na voorstel-opslag mislukt voor document %s", document_id)

    # Duplicaatsignaal (besluit Peter 25-08, deel 2 punt 6): herberekenen bij elke veldwijziging
    # — crediteur, referentie en totaal sturen de RLZ-duplicaatquery. Post-commit; signalering
    # (de live check op het boekmoment blijft bindend), fouten zichtbaar als 'onbekend'.
    from app.documenten import duplicaatsignaal  # lokaal: houdt de importgraaf klein

    duplicaatsignaal.bereken_duplicaatsignaal_stil(administratie_id=administratie_id, document_id=document_id)

    return haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _verwerk_kop_omschrijving(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document: Document,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    regels: list[BoekvoorstelRegelData],
    ingevoerd: str,
) -> None:
    """Blok 9: mens-override van de kop-omschrijving als tijdlijn-notitie. Alleen een ÉCHTE wijziging van de
    override-stand schrijft (notitie + audit) — elke opslaan-actie herhaalt de actuele veldwaarde, dat is geen
    handeling op de omschrijving. Ingevoerd == afleiding → geen override (chip blijft, automatisch beweegt mee)."""
    gebeurtenissen = _gebeurtenissen_van(session, document.id)
    veldvoorstel = next(
        (g.detail["veldvoorstel"] for g in reversed(gebeurtenissen) if g.detail and "veldvoorstel" in g.detail), None
    )
    afgeleid = _afgeleide_kop_omschrijving(
        session,
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        referentie=referentie,
        regels=regels,
        veldvoorstel=veldvoorstel,
    )
    nieuw_tekst = kop_omschrijving_regels.normaliseer(ingevoerd)
    nieuw_override = nieuw_tekst if nieuw_tekst and nieuw_tekst != afgeleid.tekst else None
    if nieuw_override is not None:
        nieuw_override = kop_omschrijving_regels.kap_af(nieuw_override)
    oud_override = _kop_omschrijving_override(gebeurtenissen)
    if nieuw_override == oud_override:
        return
    session.add(
        DocumentGebeurtenis(
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail={
                KOP_OMSCHRIJVING_SLEUTEL: {
                    "tekst": nieuw_override,
                    "herkomst": kop_omschrijving_regels.HERKOMST_HANDMATIG if nieuw_override else afgeleid.herkomst,
                    "afgeleid": afgeleid.tekst,
                }
            },
        )
    )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="boekvoorstel",
        record_id=document.id,
        actie="boekvoorstel_omschrijving_gewijzigd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={
            "omschrijving": oud_override if oud_override is not None else afgeleid.tekst,
            "handmatig": oud_override is not None,
        },
        nieuwe_waarde={
            "omschrijving": nieuw_override if nieuw_override is not None else afgeleid.tekst,
            "handmatig": nieuw_override is not None,
        },
        administratie_id=administratie_id,
    )


def _onthoud_voorkeur_samenvoegen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    regels_samenvoegen: bool,
) -> None:
    """Upsert van de leverancier-voorkeur (fix 3). Alleen een échte wijziging krijgt een
    audit_event — elke opslaan-actie herhaalt de actuele stand, dat is geen handeling op de
    voorkeur zelf."""
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    oud = voorkeur.regels_samenvoegen if voorkeur else None
    if oud == regels_samenvoegen:
        return
    if voorkeur is None:
        session.add(
            LeverancierVoorkeur(
                administratie_id=administratie_id, vendor_id=vendor_id, regels_samenvoegen=regels_samenvoegen
            )
        )
    else:
        voorkeur.regels_samenvoegen = regels_samenvoegen
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="leverancier_voorkeur",
        record_id=vendor_id,
        actie="leverancier_voorkeur_samenvoegen_gewijzigd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"regels_samenvoegen": oud} if oud is not None else None,
        nieuwe_waarde={"regels_samenvoegen": regels_samenvoegen},
        administratie_id=administratie_id,
    )


def _naar_check_regels(
    voorstel: BoekvoorstelData, taxrate_percentages: dict[uuid.UUID, Decimal | None] | None = None
) -> list[CheckRegel]:
    """Boekvoorstelregels → CheckRegel. Een LEGE btw op een opgeslagen regel is in het boekvoorstel
    van oudsher "geen btw" (verlegd/vrijgesteld — de motoren boeken TaxAmount 0, zie
    tests/documenten/test_boeken.py::TestBoekDocumentRegelZonderBtw); pas sinds de regelsom-bugfix
    04-09 (Huvanco) telt een lege btw als ONBEKEND. Beide kloppen, afhankelijk van het tarief: bij een
    gesynct 0%-/verlegd-tarief (percentage 0 of zonder percentage in de cache) is leeg = 0 (bekend);
    bij een tarief mét percentage > 0, een niet-gesynct tarief óf géén tarief is leeg = niet gelezen —
    de regeltelling toetst dan netto-vs-netto (tak 2) of meldt expliciet wat ontbreekt (tak 4), nooit
    stil Σnetto tegen een incl-totaal. `taxrate_percentages` = de gesyncte cache (id → percentage)."""
    percentages = taxrate_percentages or {}

    def btw_van(r: BoekvoorstelRegelData) -> Decimal | None:
        if r.btw_bedrag is not None:
            return r.btw_bedrag
        if r.taxrate_id is None or r.taxrate_id not in percentages:
            return None
        pct = percentages[r.taxrate_id]
        return Decimal(0) if pct is None or pct == 0 else None

    return [
        CheckRegel(
            ledger_id=r.ledger_id,
            taxrate_id=r.taxrate_id,
            project_id=r.project_id,
            netto_bedrag=r.netto_bedrag,
            btw_bedrag=btw_van(r),
        )
        for r in voorstel.regels
    ]


def _taxrate_percentages(administratie_id: uuid.UUID) -> dict[uuid.UUID, Decimal | None]:
    """Tariefpercentages uit de gesyncte taxrate_cache (lokaal, geen RLZ-call) — voor de
    lege-btw-interpretatie in `_naar_check_regels`."""
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(TaxRateCache.id, TaxRateCache.percentage).where(TaxRateCache.administratie_id == administratie_id)
        ).all()
    return {r.id: r.percentage for r in rijen}


def _taxrate_namen(administratie_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Tariefnamen uit de gesyncte taxrate_cache voor de buitenland-tarief-check (blok A 31-08) —
    lokaal, geen RLZ-call: draait dus ook in de storings-tak mee."""
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(TaxRateCache.id, TaxRateCache.naam).where(TaxRateCache.administratie_id == administratie_id)
        ).all()
    return {r.id: r.naam for r in rijen if r.naam}


def _duplicaatcheck_niet_uitgevoerd_rapport(
    *,
    administratie_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    project_verplicht: bool,
    factuur_iban: str | None,
    factuur_btw_nummer: str | None,
    reden: str,
    gelezen_totalen: tuple[Decimal | None, Decimal | None] = (None, None),
    historie_treffers: list[dict] | None = None,
    module_check: CheckResultaat | None = None,
    crediteur_niet_gekoppeld: str | None = None,
) -> CheckRapport:
    """Bouwt het rapport voor het geval de RLZ-verbinding zelf al niet tot stand komt (credential-
    fout, netwerkfout) — vóórdat check_duplicaat() de kans krijgt zijn eigen RlzApiError-vangnet te
    gebruiken (app/documenten/checks.py). De lokale checks (geen RLZ nodig) draaien gewoon door,
    inclusief de IBAN-wissel-check tegen de al opgeslagen vertrouwde set (zonder RLZ-seed of
    baseline — die vergen een werkende verbinding); alleen de duplicaatcheck wordt een blokkerend,
    herkenbaar checkresultaat — nooit een kale 500 bij de gebruiker.

    `crediteur_niet_gekoppeld` (blok D 07-09, Odoo): de crediteur heeft nog geen partner-koppeling — dan is óók de
    IBAN-rij BLOKKEREND met die leesbare tekst (de seed kan niet draaien; een wissel is niet uit te sluiten), i.p.v.
    "niets te vergelijken"."""
    regels = _naar_check_regels(voorstel, _taxrate_percentages(administratie_id))
    vertrouwd: set[str] = set()
    if voorstel.vendor_id is not None:
        vertrouwd = leverancier_iban.vertrouwde_ibans(administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
    iban_check = (
        CheckResultaat("IBAN-wissel", False, crediteur_niet_gekoppeld)
        if crediteur_niet_gekoppeld
        else check_iban_wissel(factuur_iban=factuur_iban, vertrouwde_ibans=vertrouwd)
    )
    return CheckRapport(
        (
            check_verplichte_velden(
                vendor_id=voorstel.vendor_id,
                referentie=voorstel.referentie,
                factuurdatum=voorstel.factuurdatum,
                totaalbedrag=voorstel.totaalbedrag,
                regels=regels,
                project_verplicht=_project_verplicht_per_regel(project_verplicht, voorstel),
            ),
            _afdeling_check(administratie_id=administratie_id, voorstel=voorstel),
            _projectverdeling_check(voorstel, project_verplicht=project_verplicht),
            check_regeltelling(
                totaalbedrag=voorstel.totaalbedrag,
                regels=regels,
                totaal_excl=gelezen_totalen[0],
                factuur_btw=gelezen_totalen[1],
            ),
            check_vervaldatum(factuurdatum=voorstel.factuurdatum, vervaldatum=voorstel.vervaldatum),
            check_buitenland_tarief_crediteurkaart(
                regels=regels,
                taxrate_namen=_taxrate_namen(administratie_id),
                factuur_btw_nummer=factuur_btw_nummer,
            ),
            iban_check,
            # Odoo-slotstuk 04-09: treffers uit de eigen RLZ-era-historie (overgestapte administratie) horen óók
            # in de storings-tak thuis — de reden blijft rood, het boekstuk komt erbij.
            CheckResultaat(
                "Duplicaatcheck",
                False,
                f"Duplicaatcheck kon niet uitgevoerd worden: {reden}"
                + (f"; {historie_melding(historie_treffers)}" if historie_treffers else ""),
            ),
            # 07-09: de module-check (eigen database, geen RLZ) draait óók in de storings-tak — nooit stil wegvallen.
            *([module_check] if module_check is not None else []),
        )
    )


def _projectverdeling_check(voorstel: BoekvoorstelData, *, project_verplicht: bool) -> CheckResultaat:
    """Blok C 04-09: lokale check op de OPGESLAGEN projectverdeling (app/projectverdeling/service.py::check) —
    geldig = ok mét samenvatting, ongeldig = blokkerend mét de blokkade-zin, afwezig = niet van toepassing tenzij er
    onder projectplicht regels zonder project zijn (dan benoemt de check de actie)."""
    from app.projectverdeling import service as projectverdeling_service

    return projectverdeling_service.check(
        voorstel.projectverdeling,
        regels_zonder_project=_regels_zonder_project(voorstel),
        project_verplicht=project_verplicht,
    )


def _afdeling_check(*, administratie_id: uuid.UUID, voorstel: BoekvoorstelData) -> CheckResultaat:
    """Blok A 28-08: lokale check (geen RLZ nodig) — draait in beide rapport-takken, zodat hij ook
    bij een RLZ-storing niet stil wegvalt (valkuil _duplicaatcheck_niet_uitgevoerd_rapport)."""
    from app.afdelingen.models import Afdeling

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        ingeschakeld = administratie.afdelingen_ingeschakeld if administratie else False
        administratie_naam = administratie.naam if administratie else None
    afdeling_actief: bool | None = None
    afdeling_naam: str | None = None
    if ingeschakeld and voorstel.afdeling_id is not None:
        with scoped_session(administratie_id) as session:
            afdeling = session.get(Afdeling, voorstel.afdeling_id)
            if afdeling is not None:
                afdeling_actief, afdeling_naam = afdeling.actief, afdeling.naam
    return check_afdeling(
        afdelingen_ingeschakeld=ingeschakeld,
        afdeling_id=voorstel.afdeling_id,
        afdeling_actief=afdeling_actief,
        afdeling_naam=afdeling_naam,
        administratie_naam=administratie_naam,
    )


def voer_checks_uit(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> CheckRapport:
    """Herleest het OPGESLAGEN boekvoorstel (nooit het niet-opgeslagen UBL-voorstel — de checks
    gelden over wat de controleur daadwerkelijk heeft bevestigd) en toetst de drie harde checks
    (app/documenten/checks.py). `client=None` opent een eigen RlzClient voor deze administratie
    (store/`.env`-credential-resolutie, zie app/rlz/credentials.py) — een aanroeper met een al
    open verbinding (bv. de boek-actie zelf) geeft 'm door om niet twee keer in te loggen.

    Lukt het openen van die eigen verbinding niet (credential-fout, RLZ onbereikbaar), dan wordt
    dat NOOIT een onafgevangen exception (dus geen kale 500) — zie _duplicaatcheck_niet_uitgevoerd_rapport."""
    with scoped_session(administratie_id) as session:
        document = _laad_document(session, document_id=document_id)
        _controleer_niet_bevroren(document)
        veldvoorstel = _laatste_veldvoorstel(session, document_id)
        # Punt 14 (28-08): bekende btw-nummers per crediteur voor de check over crediteuren heen.
        from app.documenten.crediteur_kenmerk import btw_per_vendor as _btw_per_vendor

        btw_map = _btw_per_vendor(session, administratie_id=administratie_id)
    factuur_btw_nummer = veldvoorstel.get("btw_nummer") if veldvoorstel else None

    # Factuur-IBAN uit de extractie (gestructureerd kopveld sinds 2026-07-13); de controlelaag
    # heeft 'm al mod-97-gevalideerd (app/extractie/controle.py) — oudere veldvoorstellen zonder
    # iban-sleutel geven None: geen wisselcontrole mogelijk, nooit een blok op ontbrekende data.
    factuur_iban = veldvoorstel.get("iban") if veldvoorstel else None
    # Bugfix 04-09 (Huvanco): gelezen excl-totaal + factuur-btw voor een expliciete regeltelling-basis.
    gelezen_totalen = _gelezen_totalen(veldvoorstel)

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        project_verplicht = administratie.project_verplicht if administratie else False
    # Odoo-slotstuk 04-09: duplicaat over de backend-grens — voor een OVERGESTAPTE administratie de in de app
    # geboekte RLZ-era documenten met dezelfde kop (geen RLZ-/Odoo-call; leeg voor alle andere administraties).
    historie_treffers = _historie_treffers(administratie_id=administratie_id, voorstel=voorstel)
    # HARDE check "Duplicaat (module)" (besluit Peter 07-09): tegen onze eigen database, binnen de administratie,
    # over álle statussen behalve afgevoerd/afgewezen/verwijderd/gesplitst/samengevoegd — geen RLZ/Odoo nodig, dus
    # in BEIDE takken (ook bij een RLZ-storing). Bundelparen (UBL+PDF) en mens-afmeldingen zijn al toegepast.
    from app.documenten import duplicaat_module  # lokaal: houdt de importgraaf klein

    module_check = check_duplicaat_module(
        treffers=duplicaat_module.treffers_voor_document(
            administratie_id=administratie_id,
            document_id=document_id,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            totaalbedrag=voorstel.totaalbedrag,
        )
    )

    eigen_client = client is None
    eigen_port = None
    if client is None:
        try:
            # Via de boekhoud-backend-port (0016): RLZ opent de bestaande client (test-seam
            # `client_voor_rlz_admin_id` blijft de patch-plek), Odoo zijn eigen leesfacade.
            eigen_port = inkoop_port_voor(
                administratie_id, rlz_client_factory=lambda: _rlz_leesclient(administratie_id)
            )
            client = eigen_port.leesclient()
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie de docstring hierboven
            return _duplicaatcheck_niet_uitgevoerd_rapport(
                administratie_id=administratie_id,
                voorstel=voorstel,
                project_verplicht=project_verplicht,
                factuur_iban=factuur_iban,
                factuur_btw_nummer=factuur_btw_nummer,
                reden=str(exc),
                gelezen_totalen=gelezen_totalen,
                historie_treffers=historie_treffers,
                module_check=module_check,
            )
    try:
        try:
            vertrouwde_ibans, baseline_vastgelegd, seed_mislukt = leverancier_iban.seed_en_baseline_voor_checks(
                administratie_id=administratie_id,
                vendor_id=voorstel.vendor_id,
                factuur_iban=factuur_iban,
                client=client,
                # Systeem-actor: seed/baseline gebeuren als bijeffect van de checks, niet als
                # bewuste gebruikershandeling — de menselijke bevestiging (bevestig_iban) draagt
                # wél de echte actor.
                actor_id=SYSTEEM_ACTOR_ID,
            )
        except CrediteurNietGekoppeld as exc:
            # Blok D 07-09: Odoo-administratie, crediteur zonder partner-koppeling — de IBAN-seed én de live
            # duplicaatquery kunnen niet draaien (dezelfde koppeling). Geen 500: de storings-tak mét een leesbare,
            # BLOKKERENDE uitkomst op de IBAN-rij (handelingsperspectief in de tekst); lokale checks + module-check
            # draaien gewoon door. Fail-closed tot de koppeling er is.
            return _duplicaatcheck_niet_uitgevoerd_rapport(
                administratie_id=administratie_id,
                voorstel=voorstel,
                project_verplicht=project_verplicht,
                factuur_iban=factuur_iban,
                factuur_btw_nummer=factuur_btw_nummer,
                reden=str(exc),
                gelezen_totalen=gelezen_totalen,
                historie_treffers=historie_treffers,
                module_check=module_check,
                crediteur_niet_gekoppeld=str(exc),
            )
        # Tegenboek-pad: het eigen GUID volgt de boek_cyclus (herboeking = nieuw GUID); alle
        # eerdere (her)boekings- en tegenboekings-GUID's van dit document zijn de gekoppelde
        # correctieketen en tellen niet als duplicaat (mockup 22-08 — de herboeking heeft
        # bewust dezelfde Entity+Reference+bedrag als het origineel).
        keten = frozenset(
            {rlz_herboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
            | {rlz_tegenboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
        )
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            vervaldatum=voorstel.vervaldatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=_naar_check_regels(voorstel, _taxrate_percentages(administratie_id)),
            eigen_rlz_document_id=rlz_herboeking_id(document_id, voorstel.boek_cyclus),
            uitgezonderde_rlz_document_ids=keten,
            project_verplicht=_project_verplicht_per_regel(project_verplicht, voorstel),
            factuur_iban=factuur_iban,
            vertrouwde_ibans=vertrouwde_ibans,
            iban_baseline_vastgelegd=baseline_vastgelegd,
            iban_seed_mislukt=seed_mislukt,
            eigen_btw_nummer=factuur_btw_nummer,
            btw_per_vendor=btw_map,
            taxrate_namen=_taxrate_namen(administratie_id),
            totaal_excl=gelezen_totalen[0],
            factuur_btw=gelezen_totalen[1],
            historie_treffers=historie_treffers,
        )
        # Blok A 28-08: afdeling-check direct ná de verplichte velden (zelfde plek als in de
        # storings-tak), vóór de RLZ-afhankelijke checks.
        resultaten = list(rapport.resultaten)
        resultaten.insert(1, _afdeling_check(administratie_id=administratie_id, voorstel=voorstel))
        # Blok C 04-09: projectverdeling-check (lokaal, geen RLZ) direct ná de afdeling — zelfde plek als in
        # de storings-tak; blokkeert zolang een actieve verdeling niet exact op 100 % sluit.
        resultaten.insert(2, _projectverdeling_check(voorstel, project_verplicht=project_verplicht))
        # 07-09: "Duplicaat (module)" als laatste rij, ná de twee live-RLZ-duplicaatchecks.
        resultaten.append(module_check)
        return CheckRapport(tuple(resultaten))
    finally:
        if eigen_client and eigen_port is not None:
            eigen_port.__exit__(None, None, None)
