"""Leesbare reconciliatie-teksten (fixrun 07-09 blok A8, opdracht Peter).

Elke bevinding krijgt een TITEL (kort, ≤ 60 tekens), één zin WAT ("wat is er") en één zin DOE ("wat doe
je"), met NAMEN in plaats van GUID's: leverancier, factuurnummer, boekstuk, administratie-/doelnaam,
referentie, bedragen in NL-notatie (€ 1.234,56) en datums als DD-MM-JJJJ. Technische sleutels
(GUID's, vingerafdruk, record-id's) verhuizen naar een DETAILS-lijst (label, waarde) voor de uitklap
in de UI en de technische regel in de mail.

Pure module: geen DB, geen RLZ, geen AI. De invoer is een bevinding (`run.Bevinding`,
`kantoorbreed.Rij` of de ORM-rij) — duck-typed op `blok`, `soort`, `tekst`, `detail`, `vingerafdruk`.
De naamvelden komen uit `detail` (documenten: contract A↔A8 — `leverancier_naam`, `factuurnummer`,
`rlz_boekstuk`, `bedrag_lokaal`, `bedrag_extern`, `backend`, `extern_id`, `extern_state`; bank/omzet/
doorbelasting: `app/reconciliatie/verrijking.py`). Ontbreken ze (oude runs), dan valt de tekst
DEFENSIEF terug op de bestaande CLI-regel — ontdaan van labels en GUID's — zodat er nooit een lege
of kale technische hoofdregel ontstaat. Onbekende soorten krijgen een default-tekst (verplicht per
contract): niets verdwijnt stil, ook geen nieuwe soort."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_TITEL = 60

_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_VAF = re.compile(r"\s*\[vaf:[0-9a-f]+\]")
_PREFIX = re.compile(r"^(AFWIJKING|OK|FOUT|LET-OP|UITGESLOTEN|GEACCEPTEERD|STORNO)\s+", re.IGNORECASE)
_EIGEN_RLZ = re.compile(r"eigen=€?\s*(-?[\d.,]+)\s+(?:rlz|odoo)=€?\s*(-?[\d.,]+)")
_STATUS = re.compile(r"(?:RLZ-?)?[Ss]tatus\s*=?\s*(\d+)")
_ISO_DATUM = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


@dataclass(frozen=True)
class Leesbaar:
    titel: str
    wat: str
    doe: str
    details: list[tuple[str, str]] = field(default_factory=list)


# ---- formatters --------------------------------------------------------------------------------


def euro(waarde: Any) -> str | None:
    """'274.89' / Decimal / float → '€ 274,89'; '1234.5' → '€ 1.234,50'. None/onparseerbaar → None."""
    if waarde is None or waarde == "":
        return None
    try:
        d = Decimal(str(waarde).replace(",", ".").replace("€", "").strip())
    except (InvalidOperation, ValueError):
        return None
    q = d.quantize(Decimal("0.01"))
    teken = "-" if q < 0 else ""
    hele, _, cent = f"{abs(q):.2f}".partition(".")
    groepen: list[str] = []
    while len(hele) > 3:
        groepen.insert(0, hele[-3:])
        hele = hele[:-3]
    groepen.insert(0, hele)
    return f"€ {teken}{'.'.join(groepen)},{cent}"


def datum(waarde: Any) -> str | None:
    """date/datetime/'2026-09-03'/'2026-09-03T04:31:00+00:00' → '03-09-2026'."""
    if waarde is None or waarde == "":
        return None
    if isinstance(waarde, datetime):
        return waarde.strftime("%d-%m-%Y")
    if isinstance(waarde, date):
        return waarde.strftime("%d-%m-%Y")
    m = _ISO_DATUM.search(str(waarde))
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return str(waarde)


def zonder_guids(tekst: str) -> str:
    """GUID's en [vaf:…] uit een vrije tekst; datums ISO → NL. Voor de defensieve terugval."""
    t = _VAF.sub("", tekst or "")
    t = _GUID.sub("…", t)
    t = _ISO_DATUM.sub(lambda m: f"{m.group(3)}-{m.group(2)}-{m.group(1)}", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _kort(titel: str) -> str:
    """≤ 60 tekens: eerst het haakjesdeel (boekstuk) laten vallen, dan ' · '-segmenten van achteren,
    pas als laatste redmiddel afkappen — nooit een half boekstuknummer in de titel."""
    titel = re.sub(r"\s+", " ", titel).strip(" —-")
    if len(titel) <= MAX_TITEL:
        return titel
    zonder_haakjes = re.sub(r"\s*\([^()]*\)\s*$", "", titel).strip(" —-")
    if zonder_haakjes != titel and len(zonder_haakjes) <= MAX_TITEL:
        return zonder_haakjes
    titel = zonder_haakjes or titel
    while " · " in titel and len(titel) > MAX_TITEL:
        titel = titel.rsplit(" · ", 1)[0]
    if len(titel) <= MAX_TITEL:
        return titel
    return titel[: MAX_TITEL - 1].rstrip(" —-(·") + "…"


def _s(d: dict, *sleutels: str) -> str | None:
    for k in sleutels:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _terugval_wat(tekst: str) -> str:
    """De CLI-regel zonder label/GUID's — de veiligste zin als er geen naamvelden zijn."""
    t = _PREFIX.sub("", tekst or "").strip()
    t = re.sub(r"^(document|record|boeking)=\S+\s*", "", t)
    t = re.sub(r"^(rlz_document|mutatie)=\S+\s*", "", t)
    t = re.sub(r"^soort=\S+\s*", "", t)
    t = zonder_guids(t).lstrip(":;— ").strip()
    return t or "Zie de technische details."


# ---- onderwerp per blok ---------------------------------------------------------------------------


def _systeem(d: dict) -> str:
    return "Odoo" if (d.get("backend") or "").lower() == "odoo" else "RLZ"


Segmenten = list[str]
"""Onderwerp van een titel als segmenten in AFLOPENDE prioriteit: past de titel niet in 60 tekens, dan
valt het laatste segment als eerste weg (boekstuk vóór factuurnummer, datum vóór tegenpartij …)."""


def _onderwerp_documenten(d: dict) -> Segmenten:
    lev = _s(d, "leverancier_naam")
    fnr = _s(d, "factuurnummer", "referentie")
    boekstuk = _s(d, "rlz_boekstuk", "rlz_boekstuknummer")
    kern = " ".join(x for x in (lev, fnr) if x)
    if kern and boekstuk:
        return [kern, f"({boekstuk})"]
    return [x for x in (kern or boekstuk,) if x]


def _onderwerp_bank(d: dict) -> Segmenten:
    wie = _s(d, "tegenpartij_naam", "relatie_naam", "omschrijving")
    bedrag = euro(_s(d, "mutatie_bedrag", "bedrag_lokaal"))
    dat = datum(_s(d, "mutatie_datum"))
    return [x for x in (wie, bedrag, dat) if x]


def _periode_kort(d: dict) -> str | None:
    """'01-08-2026 t/m 31-08-2026' (zonder het woord periode — voor de titel)."""
    start, eind = datum(_s(d, "periode_start")), datum(_s(d, "periode_eind"))
    if start and eind:
        return f"{start} t/m {eind}"
    m = re.search(r"Periode\s+(\S+)\s+t/m\s+(\S+)", d.get("detail") or "")
    if m:
        return f"{datum(m.group(1))} t/m {datum(m.group(2))}"
    return None


def _periode(d: dict) -> str | None:
    kort = _periode_kort(d)
    return f"periode {kort}" if kort else None


def _onderwerp_omzet(d: dict) -> Segmenten:
    boekstuk = _s(d, "rlz_boekstuk", "verkoop_boekstuknummer")
    return [x for x in (_periode_kort(d), boekstuk) if x]


def _onderwerp_projecten(d: dict) -> Segmenten:
    return [x for x in (_s(d, "nummer"), _s(d, "administratie_naam")) if x]


def _onderwerp_doorbelasting(d: dict) -> Segmenten:
    doel = _s(d, "doelentiteit_naam", "doel_administratie_naam")
    ref = _s(d, "verkoop_referentie", "referentie")
    bron = " ".join(x for x in (_s(d, "leverancier_naam"), _s(d, "factuurnummer")) if x)
    return [x for x in (doel, f"ref {ref}" if ref else None, f"({bron})" if bron else None) if x]


def _onderwerp_doorbelasting_aansluiting(d: dict) -> Segmenten:
    """Blok 2 16-09 nacht: 'Kempen Facilities → Kempen Chalets · 2026-0123' — bron → doelentiteit, dan nummer."""
    v, o = _s(d, "verkoper_naam", "administratie_naam"), _s(d, "doelentiteit_naam", "ontvanger_naam")
    relatie = f"{v} → {o}" if v and o else (v or o or "")
    return [relatie, _s(d, "nummer") or ""]


def _onderwerp_rlz_dubbel(d: dict) -> Segmenten:
    """Blok 6 (08-09) / blok 1 10-09: leverancier · referentie · alle boekstuknummers (N ≥ 2)."""
    boekstukken = _rlz_dubbel_boekstukken(d)
    ref = _s(d, "referentie")
    if not ref:
        ref_a, ref_b = _s(d, "referentie_a"), _s(d, "referentie_b")
        ref = ref_a if ref_a and (ref_a == ref_b or not ref_b) else " / ".join(x for x in (ref_a, ref_b) if x)
    if len(boekstukken) > 2:
        boekstuk_tekst: str | None = f"{len(boekstukken)} boekstukken"
    else:
        boekstuk_tekst = " + ".join(boekstukken) or None
    return [x for x in (_s(d, "leverancier_naam"), ref or None, boekstuk_tekst) if x]


_SCHEIDING = {
    "documenten": " ",
    "doorbelasting": " ",
    "bank": " · ",
    "omzet": " · ",
    "rlz_dubbel": " · ",
    "intercompany": " · ",
}


def _onderwerp_intercompany(d: dict) -> Segmenten:
    """Blok B 16-09: 'Universal Verkoop → Universal Nederland · 2026-0123' — verkoper → ontvanger, dan nummer."""
    v, o = _s(d, "verkoper_naam"), _s(d, "ontvanger_naam")
    relatie = f"{v} → {o}" if v and o else (v or o or "")
    return [relatie, _s(d, "nummer") or ""]


def _onderwerp_rekening_courant(d: dict) -> Segmenten:
    """Blok C 16-09: 'Kempen B.V. ↔ Kempen Facilities' — de twee administraties van het RC-paar."""
    a, b = _s(d, "administratie_a_naam"), _s(d, "administratie_b_naam")
    return [a or "", f"↔ {b}" if b else ""]


def _onderwerp(blok: str, d: dict) -> Segmenten:
    if blok == "documenten":
        return _onderwerp_documenten(d)
    if blok == "rlz_dubbel":
        return _onderwerp_rlz_dubbel(d)
    if blok == "bank":
        return _onderwerp_bank(d)
    if blok == "omzet":
        return _onderwerp_omzet(d)
    if blok == "projecten":
        return _onderwerp_projecten(d)
    if blok == "doorbelasting":
        return _onderwerp_doorbelasting(d)
    if blok == "rekening_courant":
        return _onderwerp_rekening_courant(d)
    if blok == "intercompany":
        return _onderwerp_intercompany(d)
    if blok == "doorbelasting_aansluiting":
        return _onderwerp_doorbelasting_aansluiting(d)
    return []


def _titel(kop: str, onderwerp: Segmenten | str, scheiding: str = " ") -> str:
    """kop + ' — ' + onderwerp, ≤ 60 tekens: segmenten vallen van achteren weg tot het past; pas als het
    kale onderwerp nog te lang is wordt er afgekapt (`_kort`)."""
    if isinstance(onderwerp, str):  # noqa: SIM108 — leesbaarder dan een geneste ternary
        segmenten = [onderwerp] if onderwerp else []
    else:
        segmenten = [x for x in onderwerp if x]
    while segmenten:
        kandidaat = f"{kop} — {scheiding.join(segmenten)}"
        if len(kandidaat) <= MAX_TITEL:
            return kandidaat
        if len(segmenten) == 1:
            return _kort(kandidaat)
        segmenten = segmenten[:-1]
    return _kort(kop)


# ---- afwijkingen per blok -------------------------------------------------------------------------

_DOE_ACCEPTEER = "klopt die, accepteer met reden."
_DOE_DUBBELE_BETALING = (
    "Factuur ontbreekt (verwijderd of nooit geboekt): controleer de betalingen in Reeleezee en vorder terug bij de "
    "leverancier óf boek de factuur alsnog; is het bewust (deelbetaling, creditnota), accepteer met reden."
)


def _dubbele_betaling_wat(d: dict, tekst: str) -> str:
    datums_ruw = d.get("dubbele_betaling_datums") or []
    bedrag_ruw = _s(d, "dubbele_betaling_bedrag", "mutatie_bedrag")
    try:
        datums = [date.fromisoformat(str(x)[:10]) for x in datums_ruw]
        bedrag = abs(Decimal(str(bedrag_ruw).replace(",", ".")))
    except (ValueError, InvalidOperation, TypeError):
        return _terugval_wat(d.get("detail") or tekst)
    if len(datums) < 2:
        return _terugval_wat(d.get("detail") or tekst)
    from app.bank.dubbele_betaling import tekst_uit_delen

    # Herdefinitie 17-09: mét de factuurtelling als de bevinding die draagt (oudere bevindingen: de zin van 16-09).
    aantal_facturen = d.get("dubbele_betaling_facturen_aantal") if d.get("dubbele_betaling_factuur_bronnen") else None
    return tekst_uit_delen(
        _s(d, "tegenpartij_naam"),
        bedrag,
        datums,
        iban=_s(d, "tegenrekening_iban"),
        aantal_facturen=int(aantal_facturen) if aantal_facturen is not None else None,
        sterk=bool(d.get("dubbele_betaling_sterk")),
    )


_DOE_CONTROLE_MISLUKT = (
    "Controleer verbinding en credentials van deze administratie; de volgende run controleert opnieuw."
)


def _bedragen(d: dict) -> tuple[str | None, str | None]:
    lokaal, extern = euro(_s(d, "bedrag_lokaal")), euro(_s(d, "bedrag_extern"))
    if lokaal is None or extern is None:
        m = _EIGEN_RLZ.search(d.get("detail") or "")
        if m:
            lokaal, extern = lokaal or euro(m.group(1)), extern or euro(m.group(2))
    return lokaal, extern


def _status_uit_detail(d: dict) -> str | None:
    st = _s(d, "extern_state")
    if st:
        return st
    m = _STATUS.search(d.get("detail") or "")
    return m.group(1) if m else None


def _status_label(st: str | None) -> str:
    if st == "1":
        return "status 1 (concept)"
    if st in ("2", "3"):
        return f"status {st}"
    return f"status '{st}'" if st else "een andere status"


def _documenten(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    sys_ = _systeem(d)
    onderwerp = _onderwerp_documenten(d)
    lokaal, extern = _bedragen(d)
    boekdatum = datum(_s(d, "boekdatum", "geboekt_op", "factuurdatum"))
    verleden = " (vóór de overstap naar Odoo geboekt in Reeleezee)" if d.get("rlz_verleden") else ""
    if soort in ("ontbreekt_in_rlz", "ontbreekt_in_odoo"):
        geboekt = " ".join(x for x in ("Wij boekten", lokaal, f"op {boekdatum}" if boekdatum else None) if x)
        if not (lokaal or boekdatum):
            geboekt = "Wij boekten dit document definitief"
        return (
            _titel(f"{sys_}-document verdwenen", onderwerp),
            f"{geboekt}{verleden}, in {sys_} bestaat het boekstuk niet meer.",
            "Boek opnieuw via de actie op deze rij, of accepteer met reden.",
        )
    if soort == "bedrag_wijkt_af":
        wat = (
            f"Wij boekten {lokaal}, {sys_} toont {extern}."
            if lokaal and extern
            else f"Het bedrag in {sys_} verschilt van wat wij boekten ({_terugval_wat(tekst)})."
        )
        doe = f"Controleer de wijziging in {sys_}; {_DOE_ACCEPTEER}"
        return _titel(f"Bedrag afwijkt in {sys_}", onderwerp), wat, doe
    if soort in ("status_wijkt_af", "status_niet_definitief"):
        st = _status_uit_detail(d)
        return (
            _titel(f"Boeking teruggezet in {sys_}", onderwerp),
            f"Wij boekten definitief, in {sys_} staat het document op {_status_label(st)} — vermoedelijk in de "
            f"{sys_}-UI gestorneerd.",
            "Verwerk de storno ook hier of boek opnieuw; klopt de terugzetting, accepteer met reden.",
        )
    if soort == "boekstuknummer_wijkt_af":
        m = re.search(r"eigen=(.+?)\s+(?:rlz|odoo)=(.+)$", d.get("detail") or "")
        eigen, rlz = (m.group(1), m.group(2)) if m else (None, None)
        wat = (
            f"Wij registreerden boekstuk {eigen}, {sys_} toont {rlz}."
            if eigen
            else f"Het boekstuknummer in {sys_} verschilt van het onze ({_terugval_wat(tekst)})."
        )
        return _titel("Boekstuknummer afwijkt", onderwerp), wat, f"Controleer in {sys_}; {_DOE_ACCEPTEER}"
    if soort == "controle_mislukt":
        if "geen bewaarde RLZ-credential" in (d.get("detail") or tekst or ""):
            # Besluit Peter 07-09 (A12 beslispunt 1): het RLZ-verleden van een overgestapte administratie wordt
            # tegen Reeleezee getoetst; zonder bewaarde webservice-login is dat niet mogelijk — zichtbaar, niet stil.
            return (
                _titel("Reeleezee-verleden niet controleerbaar", onderwerp),
                "Dit document is vóór de overstap naar Odoo in Reeleezee geboekt, maar er is geen bewaarde "
                "Reeleezee-login voor deze administratie om het te controleren; over de boeking zelf zegt dat niets.",
                "Registreer de Reeleezee-webservice-login voor deze administratie opnieuw (Instellingen › "
                "Administraties); de controle loopt daarna automatisch mee.",
            )
        return (
            _titel("Controle mislukt", onderwerp),
            f"{sys_} gaf een fout bij het ophalen van dit document{verleden}; over de boeking zelf zegt dat niets.",
            _DOE_CONTROLE_MISLUKT,
        )
    if soort == "niet_geboekt_in_odoo":
        st = _s(d, "extern_state")
        return (
            _titel("Niet geboekt in Odoo", onderwerp),
            "Wij registreerden de boeking als definitief, in Odoo staat de factuur "
            + (f"op '{st}'." if st else "niet op 'geboekt'."),
            "Boek de factuur in Odoo definitief of boek opnieuw via de actie op deze rij; "
            "klopt het, accepteer met reden.",
        )
    if soort == "wordt_geboekt_verouderd":
        sinds = datum(_s(d, "sinds"))
        return (
            _titel("Boeking blijft hangen", onderwerp),
            "Deze boeking is ingediend" + (f" op {sinds}" if sinds else "") + " maar de verwerking naar "
            f"{sys_} is niet afgerond; het document staat nog op 'Wordt geboekt…'.",
            "Open het document en kies 'Opnieuw proberen' (het systeem plant de boeking ook zelf opnieuw in); blijft "
            "het hangen, meld het als systeemfout.",
        )
    if soort == "teruggedraaid_in_odoo":
        return (
            _titel("Teruggedraaid in Odoo", onderwerp),
            "In Odoo staat een tegenboeking (reversal) op deze factuur; bij ons staat ze nog als geboekt.",
            "Verwerk de terugdraaiing ook hier (storno) of boek opnieuw; klopt het, accepteer met reden.",
        )
    return (
        _titel(f"Afwijking in {sys_}", onderwerp),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer het document in {sys_}; {_DOE_ACCEPTEER}",
    )


def _bank(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    onderwerp = _onderwerp_bank(d)
    _t = lambda kop: _titel(kop, onderwerp, " · ")  # noqa: E731
    wie = _s(d, "tegenpartij_naam", "relatie_naam")
    bedrag = euro(_s(d, "mutatie_bedrag", "bedrag_lokaal"))
    dat = datum(_s(d, "mutatie_datum"))
    rekening = _s(d, "rekening_naam") or _s(d, "rekening_iban")
    if wie:  # noqa: SIM108 — leesbaarder dan een dubbele ternary
        tussen = f" ({wie}, {bedrag})" if bedrag else f" ({wie})"
    else:
        tussen = f" van {bedrag}" if bedrag else ""
    mutatie = "de bankmutatie" + (f" van {dat}" if dat else "") + tussen
    op_rek = f" op {rekening}" if rekening else ""
    if soort == "document_ontbreekt_in_rlz":
        return (
            _t("Bankboeking verdwenen uit RLZ"),
            f"Wij boekten {mutatie}{op_rek} rechtstreeks op een grootboekrekening; "
            "in RLZ bestaat die boeking niet meer.",
            "Boek de mutatie opnieuw in het bankscherm, of accepteer met reden.",
        )
    if soort == "boeking_teruggedraaid_in_rlz":
        st = _status_uit_detail(d)
        return (
            _t("Bankboeking teruggedraaid in RLZ"),
            f"Wij boekten {mutatie}{op_rek}; in RLZ staat de boeking op {_status_label(st)} in plaats van gesloten — "
            "vermoedelijk in de RLZ-UI gestorneerd.",
            "Verwerk de storno ook hier (bankscherm) of boek opnieuw; klopt de terugdraaiing, accepteer met reden.",
        )
    if soort == "mutatie_ontbreekt_in_rlz":
        return (
            _t("Bankmutatie verdwenen uit RLZ"),
            f"Wij letterden {mutatie}{op_rek} af; in RLZ bestaat die mutatie niet meer.",
            "Controleer het bankafschrift in RLZ; klopt het, accepteer met reden.",
        )
    if soort == "aflettering_teruggedraaid_in_rlz":
        m = re.search(r"OpenAmount=(-?[\d.]+)", d.get("detail") or "")
        open_ = euro(m.group(1)) if m else None
        ref = _s(d, "referentie")
        return (
            _t("Aflettering teruggedraaid in RLZ"),
            f"Wij letterden {mutatie}{op_rek} af"
            + (f" op {ref}" if ref else "")
            + "; in RLZ staat er weer "
            + (f"{open_} open." if open_ else "een bedrag open."),
            "Letter opnieuw af in het bankscherm, of accepteer met reden.",
        )
    if soort == "controle_mislukt":
        return (
            _t("Controle mislukt"),
            f"RLZ gaf een fout bij het ophalen van {mutatie}; over de boeking zelf zegt dat niets.",
            _DOE_CONTROLE_MISLUKT,
        )
    if soort == "dubbele_betaling_vermoed":
        # Blok C 16-09: dezelfde zin als de chip in het bankscherm (app/bank/dubbele_betaling.py::tekst_uit_delen),
        # opgebouwd uit de detail-velden; ontbreekt een bouwsteen, dan de CLI-regel zonder id's.
        return (_t("Mogelijk dubbel betaald"), _dubbele_betaling_wat(d, tekst), _DOE_DUBBELE_BETALING)
    return (
        _t("Afwijking in de bank"),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer in RLZ; {_DOE_ACCEPTEER}",
    )


def _kant_omzet(d: dict) -> str:
    t = (d.get("detail") or "").lower()
    if "kostprijsmemoriaal" in t:
        return "het kostprijsmemoriaal"
    if "verkoopfactuur" in t:
        return "de verkoopfactuur"
    return "de boeking"


def _omzet(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    onderwerp = _onderwerp_omzet(d)
    _t = lambda kop: _titel(kop, onderwerp, " · ")  # noqa: E731
    per = _periode(d) or "deze periode"
    omzet = euro(_s(d, "totaal_omzet", "bedrag_lokaal"))
    kant = _kant_omzet(d)
    if soort == "half_geboekt":
        return (
            _t("Omzet half geboekt"),
            f"De verkoopfactuur van {per}{f' ({omzet})' if omzet else ''} staat geboekt, het kostprijsmemoriaal niet.",
            "Herstel via de half-geboekt-route (omzet-reconciliatie) — nooit laten staan.",
        )
    if soort == "ontbreekt_in_rlz":
        return (
            _t("Omzetboeking verdwenen uit RLZ"),
            f"Van de omzetboeking over {per}{f' ({omzet})' if omzet else ''} bestaat {kant} niet meer in RLZ.",
            "Boek de omzet opnieuw of accepteer met reden.",
        )
    if soort == "status_niet_definitief":
        st = _status_uit_detail(d)
        return (
            _t("Omzetboeking teruggezet in RLZ"),
            f"Van de omzetboeking over {per} staat {kant} in RLZ op {_status_label(st)} — vermoedelijk teruggedraaid.",
            "Verwerk de storno ook hier of boek opnieuw; klopt de terugzetting, accepteer met reden.",
        )
    if soort == "controle_mislukt":
        return (
            _t("Controle mislukt"),
            f"RLZ gaf een fout bij het ophalen van {kant} over {per}; over de boeking zelf zegt dat niets.",
            _DOE_CONTROLE_MISLUKT,
        )
    if soort == "verkoop_categorie_afwijkt":
        m = re.search(r"onder '(?P<binder>[^']+)' \(categorie (?P<cat>[^)]+)\)", d.get("detail") or tekst)
        binder = m.group("binder") if m else "een andere map dan Inkomsten"
        return (
            _t("Omzetboeking staat in RLZ niet onder Inkomsten"),
            f"De verkoopboeking over {per}{f' ({omzet})' if omzet else ''} staat in Reeleezee onder {binder}"
            f"{f' (categorie {m.group("cat")})' if m else ''} — de categorie hoort binder Inkomsten te dragen.",
            "Kies in het omzet-controlescherm de juiste categorie (Inkomsten) en herboek via storno + opnieuw boeken; "
            "of accepteer met reden als dit bewust zo hoort.",
        )
    if soort == "omzet_in_inkoopstroom":
        m = re.search(r"Inkoopfactuur (?P<nr>\S+) \((?P<bestand>[^,]+), factuurdatum (?P<datum>[^)]+)\)", d.get("detail") or tekst)
        nr = m.group("nr") if m else "—"
        bestand = m.group("bestand") if m else "het rapport"
        return (
            _titel("Omzet als inkoopfactuur geboekt", [bestand, nr], " · "),
            f"Kassarapport {bestand} is als inkoopfactuur {nr} geboekt{f' (factuurdatum {datum(m.group("datum"))})' if m and m.group('datum') != '?' else ''}: "
            "alle regels staan op omzetrekeningen, dus verschijnt het in Reeleezee onder Uitgaven in plaats van "
            "Inkomsten.",
            "Klik \"Herboeken als omzet…\": de inkoopfactuur wordt gestorneerd (actie 19, achter de btw-aangiftepoort) en het "
            "document wordt een kassarapport dat je in het omzet-controlescherm als Receipt onder Inkomsten boekt.",
        )
    if soort == "kassarapport_in_werkvoorraad":
        m = re.search(
            r"Kassarapport (?P<bestand>.+?) staat als inkoopfactuur in de werkvoorraad "
            r"\(status (?P<status>[^;]+); signaal (?P<signaal>[^,)]+)",
            d.get("detail") or tekst,
        )
        bestand = m.group("bestand") if m else "het document"
        signaal = m.group("signaal") if m else ""
        if signaal == "omzetrekeningen":
            signaal_tekst = "alle boekingsregels staan op omzetrekeningen"
        elif signaal:
            signaal_tekst = f"de inhoud is een herkend kassarapport ({signaal.replace('_', ' ')})"
        else:
            signaal_tekst = "de inhoud is een kassarapport"
        return (
            _titel("Kassarapport in de werkvoorraad", [bestand], " · "),
            f"{bestand} is als inkoopfactuur binnengekomen, maar {signaal_tekst}. Zo geboekt zou het in Reeleezee "
            "onder Uitgaven landen in plaats van Inkomsten.",
            'Klik "Type wijzigen → kassarapport": het document gaat opnieuw door de omzet-verwerking en verschijnt '
            "in het omzet-controlescherm. Is het tóch een inkoopfactuur, accepteer dan met reden.",
        )
    if soort == "tussenrekening_open":
        m = re.search(
            r"Omzetbatch (?P<label>.+?): (?P<wijze>.+?) € (?P<bedrag>[\d.,-]+) staat al (?P<dagen>\d+) dagen",
            d.get("detail") or tekst,
        )
        label = m.group("label") if m else (_periode_kort(d) or "deze omzetbatch")
        wijze = m.group("wijze") if m else "de ontvangst"
        bedrag = euro(m.group("bedrag")) if m else (euro(_s(d, "totaal_omzet", "bedrag_lokaal")) or "")
        dagen = m.group("dagen") if m else None
        return (
            _titel("Omzetontvangst nog niet op de bank", [label, wijze], " · "),
            f"Van omzetbatch {label} is de {wijze.lower()}{f' van {bedrag}' if bedrag else ''} "
            f"{f'al {dagen} dagen ' if dagen else ''}niet op de bankrekening teruggevonden.",
            "Koppel de bankontvangst aan deze omzetboeking (bankscherm: voorstel 'omzetbatch …') of accepteer met "
            "reden als het geld anders is binnengekomen.",
        )
    return (
        _t("Afwijking in de omzet"),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer in RLZ; {_DOE_ACCEPTEER}",
    )


def _kant_doorbelasting(d: dict) -> str:
    t = (d.get("detail") or "").lower()
    if "spiegel" in t:
        return "de spiegel-inkoopfactuur in de doel-administratie"
    if "verkoop" in t:
        return "de verkoopfactuur in de bron-administratie"
    return "de boeking"


def _doorbelasting(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    onderwerp = _onderwerp_doorbelasting(d)
    doel = _s(d, "doelentiteit_naam", "doel_administratie_naam") or "de doelentiteit"
    bedrag = euro(_s(d, "bedrag_lokaal"))
    kant = _kant_doorbelasting(d)
    aan = f"aan {doel}{f' ({bedrag})' if bedrag else ''}"
    if soort == "half_geboekt":
        m = re.search(r"sinds\s+(\d{4}-\d{2}-\d{2})", d.get("detail") or "")
        sinds = f" sinds {datum(m.group(1))}" if m else ""
        return (
            _titel("Doorbelasting half geboekt", onderwerp),
            f"De verkoopfactuur {aan} staat geboekt, de spiegel-inkoopfactuur niet{sinds}.",
            "Herstel via de half-geboekt-route (doorbelasting-reconciliatie) — nooit laten staan.",
        )
    if soort == "ontbreekt_in_rlz":
        return (
            _titel("Doorbelasting verdwenen uit RLZ", onderwerp),
            f"Van de doorbelasting {aan} bestaat {kant} niet meer in RLZ.",
            "Boek de doorbelasting opnieuw (tegenboek-pad) of accepteer met reden.",
        )
    if soort == "status_niet_definitief":
        st = _status_uit_detail(d)
        return (
            _titel("Doorbelasting teruggezet in RLZ", onderwerp),
            f"Van de doorbelasting {aan} staat {kant} in RLZ op {_status_label(st)} — vermoedelijk teruggedraaid.",
            "Verwerk de storno ook hier (tegenboek-pad) of boek opnieuw; klopt de terugzetting, accepteer met reden.",
        )
    if soort == "spiegel_open_verouderd":
        m = re.search(r"al\s+(\d+)\s+dagen", d.get("detail") or "")
        dagen = f" al {m.group(1)} dagen" if m else " lang"
        return (
            _titel("Spiegelboeking wacht te lang", onderwerp),
            f"De spiegel-inkoopfactuur bij {doel} staat{dagen} open — is de doel-administratie wel onboarded?",
            "Onboard de doel-administratie of verwerk de spiegel handmatig; klopt het wachten, accepteer met reden.",
        )
    if soort == "controle_mislukt":
        geen_cred = "credentials" in (d.get("detail") or "").lower()
        return (
            _titel("Controle mislukt", onderwerp),
            (
                f"De doel-administratie van {doel} heeft geen werkende RLZ-credentials; "
                "de spiegel is niet controleerbaar."
                if geen_cred
                else f"RLZ gaf een fout bij het ophalen van {kant}; over de boeking zelf zegt dat niets."
            ),
            _DOE_CONTROLE_MISLUKT,
        )
    return (
        _titel("Afwijking in de doorbelasting", onderwerp),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer in RLZ; {_DOE_ACCEPTEER}",
    )


def _rlz_dubbel_exemplaren(d: dict) -> list[dict]:
    """Exemplaren als lijst: sinds 10-09 `exemplaren` (N ≥ 2); oudere bevindingen dragen alleen de A/B-velden."""
    ruw = d.get("exemplaren")
    if isinstance(ruw, list) and len(ruw) >= 2 and all(isinstance(x, dict) for x in ruw):
        return ruw
    uit = []
    for kant in ("a", "b"):
        if any(d.get(f"{k}_{kant}") not in (None, "") for k in ("boekstuk", "rlz_id", "datum", "bedrag")):
            uit.append(
                {
                    "boekstuk": d.get(f"boekstuk_{kant}"),
                    "datum": d.get(f"datum_{kant}"),
                    "bedrag": d.get(f"bedrag_{kant}"),
                    "status": d.get(f"status_{kant}"),
                    "concept": str(d.get(f"status_{kant}")) == "1",
                    "van_module": bool(d.get(f"van_module_{kant}")),
                }
            )
    return uit


def _rlz_dubbel_boekstukken(d: dict) -> list[str]:
    ruw = d.get("boekstukken")
    if isinstance(ruw, list) and ruw:
        return [str(x) for x in ruw if x not in (None, "")]
    return [str(x["boekstuk"]) for x in _rlz_dubbel_exemplaren(d) if x.get("boekstuk") not in (None, "")]


def _exemplaar_tekst(x: dict) -> str:
    """'RLZ-04-00004037 (22-06-2026, € 1.234,56, concept, via de module geboekt)' — één RLZ-exemplaar."""
    delen = [
        datum(x.get("datum")),
        euro(x.get("bedrag")),
        "concept" if x.get("concept") or str(x.get("status")) == "1" else None,
        "via de module geboekt" if x.get("van_module") else None,
    ]
    binnen = ", ".join(v for v in delen if v)
    boekstuk = _s(x, "boekstuk") or "zonder boekstuknummer"
    return f"{boekstuk} ({binnen})" if binnen else boekstuk


def _exemplaar(d: dict, kant: str) -> str:
    """Terugval voor oude paar-bevindingen (A/B-velden)."""
    return _exemplaar_tekst(
        {
            "boekstuk": d.get(f"boekstuk_{kant}"),
            "datum": d.get(f"datum_{kant}"),
            "bedrag": d.get(f"bedrag_{kant}"),
            "status": d.get(f"status_{kant}"),
            "van_module": d.get(f"van_module_{kant}"),
        }
    )


def _opsomming(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " en " + items[-1]


def rlz_dubbel_waarschijnlijk(d: dict) -> bool:
    """Rangorde (blok 1 10-09): minstens twee exemplaren die beide concept zijn + zelfde factuurdatum + zelfde
    bedrag. Uit het detail (`waarschijnlijk_dubbel`) of, voor oude paar-bevindingen, afgeleid uit de A/B-velden."""
    if "waarschijnlijk_dubbel" in d:
        return bool(d.get("waarschijnlijk_dubbel"))
    groepen: dict[tuple[str, str], int] = {}
    for x in _rlz_dubbel_exemplaren(d):
        if (x.get("concept") or str(x.get("status")) == "1") and x.get("datum") and x.get("bedrag") not in (None, ""):
            sleutel = (str(x["datum"]), str(x["bedrag"]))
            groepen[sleutel] = groepen.get(sleutel, 0) + 1
    return any(n >= 2 for n in groepen.values())


def _rlz_dubbel(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok 6 (08-09) / blok 1 vervolgrun 10-09: één cluster inkoopfacturen van dezelfde crediteur met dezelfde
    referentie in Reeleezee (N ≥ 2, minstens één niet via de module). Rangorde: "Waarschijnlijk dubbel" als minstens
    twee exemplaren beide concept zijn met dezelfde factuurdatum en hetzelfde bedrag (6-Steps-casus), anders "Zelfde
    referentie, controleer" (koppen kort: het blok-label zegt al "Dubbel in RLZ"). De bedrag+datum-tak blijft alleen
    voor bevindingen van vóór blok 7
    (herstelrun 08-09). Handeling ligt in Reeleezee (de app verwijdert nooit); geen deeplink (geen bekende URL-vorm)."""
    onderwerp = _onderwerp_rlz_dubbel(d)
    lev = _s(d, "leverancier_naam") or "dezelfde crediteur"
    regel = str(d.get("regel") or "")
    exemplaren = _rlz_dubbel_exemplaren(d)
    n = max(len(exemplaren), 2)
    ref = _s(d, "referentie") or _s(d, "referentie_a") or _s(d, "referentie_b") or ""
    ref_a, ref_b = _s(d, "referentie_a"), _s(d, "referentie_b")
    if "referentie" in regel and "bedrag_datum" in regel:
        waarom = f"dezelfde referentie {ref} én hetzelfde bedrag op dezelfde datum".replace("  ", " ")
    elif "referentie" in regel or ref:
        waarom = f"dezelfde referentie {ref}".strip()
    else:
        waarom = "hetzelfde bedrag op dezelfde factuurdatum" + (
            f" (referenties {ref_a} en {ref_b})" if ref_a and ref_b and ref_a != ref_b else ""
        )
    aantal_module = sum(1 for x in exemplaren if x.get("van_module"))
    if aantal_module == 0:
        herkomst = (
            "geen van beide via de module geboekt (handmatig ingevoerd of geïmporteerd)"
            if n == 2
            else "geen ervan via de module geboekt (handmatig ingevoerd of geïmporteerd)"
        )
    elif n == 2:
        herkomst = "één ervan via de module, de andere handmatig ingevoerd"
    else:
        herkomst = f"{aantal_module} via de module, de andere handmatig ingevoerd"
    waarschijnlijk = rlz_dubbel_waarschijnlijk(d)
    if waarschijnlijk:
        slot = (
            " Twee exemplaren zijn concept met dezelfde factuurdatum en hetzelfde bedrag — waarschijnlijk dubbel "
            "ingevoerd."
        )
    elif d.get("concept") or any(x.get("concept") or str(x.get("status")) == "1" for x in exemplaren):
        slot = " Minstens één exemplaar is nog concept."
    else:
        slot = ""
    deels = d.get("acceptatie_gedeeltelijk")
    if isinstance(deels, list) and deels:
        nieuw = _opsomming([str(x) for x in deels])
        slot += f" Een eerder geaccepteerd paar zit in dit cluster; {nieuw} is/zijn nieuw."
    # Korte koppen: mét het onderwerp moet de titel binnen 60 tekens blijven ("in RLZ" zegt het blok-label al).
    kop = "Waarschijnlijk dubbel" if waarschijnlijk else "Zelfde referentie, controleer"
    lijst = _opsomming([_exemplaar_tekst(x) for x in exemplaren]) if exemplaren else "(exemplaren onbekend)"
    telwoord = {2: "twee", 3: "drie", 4: "vier", 5: "vijf"}.get(n, str(n))
    welke = "beide" if n == 2 else f"alle {n}"
    return (
        _titel(kop, onderwerp, " · "),
        f"In Reeleezee staan {telwoord} inkoopfacturen van {lev} met {waarom}: {lijst} — {herkomst}.{slot}",
        f"Open {welke} boekstuknummers in Reeleezee en beoordeel; is er één dubbel, corrigeer dáár (de app verwijdert "
        "nooit). Klopt het zo, accepteer met reden.",
    )


def _rc_lijst(d: dict, sleutel: str) -> list[str]:
    v = d.get(sleutel)
    return [str(x) for x in v if x] if isinstance(v, list) else []


def _rekening(code: str | None, naam: str | None) -> str:
    return " ".join(x for x in (code, naam) if x) or "de rekening-courant"


def _rekening_courant(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok C 16-09 (opdracht Peter): het eindsaldo van de RC-rekening in A sluit niet aan op de tegenrekening in B.
    WAT noemt beide saldi en de verklaring (welke mutatie(s) ontbreken aan welke kant — meerdere kandidaten met
    hetzelfde bedrag allemaal, nooit raden); DOE is "boek de ontbrekende mutatie bij <kant>" of, als de restlijst de
    Δ niet verklaart, "controleer handmatig op afronding/koers". Het systeem herstelt niets: andermans boekhouding."""
    onderwerp = _onderwerp_rekening_courant(d)
    naam_a = _s(d, "administratie_a_naam") or "administratie A"
    naam_b = _s(d, "administratie_b_naam") or "administratie B"
    delta = euro(d.get("delta"))
    saldo_a, saldo_b = euro(d.get("saldo_a")), euro(d.get("saldo_b"))
    bij_b, bij_a = _rc_lijst(d, "ontbreekt_bij_b"), _rc_lijst(d, "ontbreekt_bij_a")
    niet_herleidbaar = bool(d.get("niet_herleidbaar"))
    if soort != "rc_sluit_niet" and soort:
        return (
            _titel("Rekening-courant, controleer", onderwerp),
            _terugval_wat(d.get("detail") or tekst),
            f"Controleer de rekening-courant in beide administraties; {_DOE_ACCEPTEER}",
        )
    # Kort ("RC"): mét Δ én beide namen moet de titel binnen 60 tekens blijven; past het niet, dan valt eerst B weg.
    kop = f"RC wijkt {delta} af" if delta else "RC wijkt af"
    stand = (
        f"Het saldo van {_rekening(_s(d, 'rekening_a_code'), _s(d, 'rekening_a_naam'))} in {naam_a} is "
        f"{saldo_a or 'onbekend'}; de tegenrekening {_rekening(_s(d, 'rekening_b_code'), _s(d, 'rekening_b_naam'))} "
        f"in {naam_b} staat op {saldo_b or 'onbekend'}"
    )

    def _telwoord(n: int, wat: str) -> str:
        return f"{n} {wat}" if n == 1 else f"{n} {wat}s"

    delen: list[str] = []
    if bij_b:
        delen.append(f"{_telwoord(len(bij_b), 'mutatie')} ontbreekt bij {naam_b}: {'; '.join(bij_b)}")
    if bij_a:
        delen.append(f"{_telwoord(len(bij_a), 'mutatie')} ontbreekt bij {naam_a}: {'; '.join(bij_a)}")
    if niet_herleidbaar:
        delen.append(
            f"Δ {delta or 'onbekend'} niet herleidbaar tot losse mutaties — vermoedelijk afronding/koers; "
            "controleer handmatig"
        )
    wat = f"{stand} — {' en '.join(delen)}." if delen else f"{stand} (verschil {delta or 'onbekend'})."
    if niet_herleidbaar:
        doe = f"Controleer handmatig op afronding/koers in beide administraties; {_DOE_ACCEPTEER}"
    elif bij_b and bij_a:
        doe = f"Boek de ontbrekende mutaties bij {naam_b} en {naam_a}, of accepteer met reden."
    elif bij_a:
        doe = f"Boek de ontbrekende mutatie bij {naam_a}, of accepteer met reden."
    elif bij_b:
        doe = f"Boek de ontbrekende mutatie bij {naam_b}, of accepteer met reden."
    else:
        doe = f"Vergelijk de rekening-courant in beide administraties; {_DOE_ACCEPTEER}"
    return (_titel(kop, onderwerp), wat, doe)


def _rc_zonder_tegenrekening(d: dict, administratie_naam: str | None) -> tuple[str, str, str]:
    """Blok C 16-09 (let_op): een RC-rekening in A verwijst naar B, maar in B is geen tegenrekening gevonden — het
    saldo kan niet worden aangesloten. Handeling: tegenrekening aanwijzen (Instellingen › Boeken › Rekening-courant)
    of de koppeling uitsluiten met reden; deeplink op de rij (`doel_pad`)."""
    naam_a = _s(d, "administratie_a_naam") or administratie_naam or "deze administratie"
    naam_b = _s(d, "administratie_b_naam") or "de andere administratie"
    rekening = _rekening(_s(d, "rekening_a_code"), _s(d, "rekening_a_naam"))
    return (
        _titel("RC zonder tegenrekening", [naam_a, f"↔ {naam_b}"]),
        f"{rekening} in {naam_a} verwijst naar {naam_b}, maar daar is geen tegenrekening gevonden — het saldo "
        "kan niet worden aangesloten.",
        f"Wijs de tegenrekening in {naam_b} aan op Instellingen › Boeken › Rekening-courant, of sluit de koppeling "
        "uit met reden.",
    )


#: Blok B 16-09 (beslispunt 4, default): status-verschil telt pas ná 7 dagen — spiegelt `factuurmatch.STATUS_VERSCHIL_NA_DAGEN`.
_STATUS_VERSCHIL_DAGEN = 7


def _intercompany(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok B 16-09 (Peter): factuur tussen twee eigen administraties — verkoop bij de verkoper ↔ inkoop bij de
    ontvanger. Namen komen uit `verkoper_naam`/`ontvanger_naam`; het woord 'intercompany' staat bewust NIET in de
    zinnen (blok-sleutel, actiemail-guard) — de mail zegt 'onderlinge factuur'."""
    onderwerp = _onderwerp_intercompany(d)
    verkoper = _s(d, "verkoper_naam") or "de verkopende administratie"
    ontvanger = _s(d, "ontvanger_naam") or "de ontvangende administratie"
    nummer = _s(d, "nummer") or "zonder nummer"
    bedrag_v = euro(_s(d, "bedrag_verkoop"))
    bedrag_i = euro(_s(d, "bedrag_inkoop"))
    delta = euro(_s(d, "delta"))
    factuurdatum = datum(_s(d, "datum"))
    op = f" van {factuurdatum}" if factuurdatum else ""
    verrekend = " (factuur mét creditnota als één geheel)" if d.get("verrekend") else ""
    if soort == "ic_ontbreekt_bij_ontvanger":
        bedrag = f" {bedrag_v}" if bedrag_v else ""
        return (
            _titel("Onderlinge factuur ontbreekt bij ontvanger", onderwerp, " · "),
            f"{verkoper} factureerde {nummer}{bedrag}{op} aan {ontvanger}; bij {ontvanger} staat die inkoop niet"
            f"{verrekend}.",
            f"Controleer bij {ontvanger} of de factuur is ontvangen en boek 'm, of accepteer met reden.",
        )
    if soort == "ic_ontbreekt_bij_verkoper":
        bedrag = f" {bedrag_i}" if bedrag_i else ""
        return (
            _titel("Onderlinge inkoop zonder verkoopfactuur", onderwerp, " · "),
            f"{ontvanger} boekte inkoopfactuur {nummer}{bedrag}{op} van {verkoper}; bij {verkoper} staat geen "
            f"verkoopfactuur met dat nummer{verrekend}.",
            f"Controleer bij {verkoper} of de factuur wél is aangemaakt (of het nummer klopt), of accepteer met reden.",
        )
    if soort == "ic_bedrag_verschilt":
        verschil = f" (verschil {delta})" if delta else ""
        wat = (
            f"Factuur {nummer}: {verkoper} boekte {bedrag_v}, {ontvanger} {bedrag_i}{verschil}."
            if bedrag_v and bedrag_i
            else f"Factuur {nummer} staat bij {verkoper} en {ontvanger} voor een verschillend bedrag "
            f"({_terugval_wat(tekst)})."
        )
        return (
            _titel("Onderlinge factuur — bedrag verschilt", onderwerp, " · "),
            wat,
            "Vergelijk beide boekingen en corrigeer aan de kant die fout zit; klopt het verschil, accepteer met reden.",
        )
    if soort == "ic_status_verschilt":
        concept_kant = _s(d, "concept_kant")
        concept = verkoper if concept_kant == "verkoop" else ontvanger if concept_kant == "inkoop" else "één kant"
        geboekt = ontvanger if concept_kant == "verkoop" else verkoper if concept_kant == "inkoop" else "de andere kant"
        return (
            _titel("Onderlinge factuur — concept tegenover geboekt", onderwerp, " · "),
            f"Factuur {nummer}{op} staat bij {concept} nog als concept en bij {geboekt} geboekt, al langer dan "
            f"{_STATUS_VERSCHIL_DAGEN} dagen.",
            f"Boek het concept bij {concept} definitief of laat het dáár corrigeren; klopt het zo, accepteer met "
            "reden.",
        )
    return (
        _titel("Afwijking in een onderlinge factuur", onderwerp, " · "),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer beide administraties; {_DOE_ACCEPTEER}",
    )


def _doorbelasting_aansluiting(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok 2 (Peter 12-09/16-09): verkoop bij de bron ↔ inkoop in de doelentiteit, whitelist-volledigheid."""
    onderwerp = _onderwerp_doorbelasting_aansluiting(d)
    doel = _s(d, "doelentiteit_naam") or "de doelentiteit"
    bron = _s(d, "verkoper_naam", "administratie_naam") or "de bron"
    nummer = _s(d, "nummer")
    bv, bi = _s(d, "bedrag_verkoop"), _s(d, "bedrag_inkoop")
    inhaal = _s(d, "spiegel_boeking_id")
    if soort == "da_ontbreekt_in_doel":
        doe = (
            "Boek de inkoop in het doel via de open spiegel-taak (Doorbelasten › 'Boek inkoop in doel')."
            if inhaal
            else f"Zet de verkoopfactuur als inkoopfactuur in {doel} (aanleveren via facturen@ of Zenvoices) — of accepteer met reden als er bewust geen inkoop hoort."
        )
        return (
            _titel("Doorbelasting zonder inkoop in doel", onderwerp),
            f"Verkoopfactuur {nummer or '?'} van {bron} aan {doel}{f' ({bv})' if bv else ''} heeft geen inkoopfactuur in {doel}.",
            doe,
        )
    if soort == "da_bedrag_afwijkt":
        return (
            _titel("Doorbelasting — bedrag afwijkt", onderwerp),
            f"Verkoop {nummer or '?'} bij {bron} is {bv or '?'}, de inkoop in {doel} is {bi or '?'} (verschil {_s(d, 'delta') or '?'}).",
            "Corrigeer de kant die fout is (verkoop bij de bron of inkoop in het doel) — of accepteer met reden.",
        )
    if soort == "da_status_verschilt":
        return (
            _titel("Doorbelasting — status verschilt", onderwerp),
            f"Verkoop {nummer or '?'} en de inkoop in {doel} staan al langer dan 7 dagen in een andere status (concept/open/gesloten).",
            "Boek het concept definitief of letter de openstaande kant af; klopt het verschil, accepteer met reden.",
        )
    if soort == "da_doel_niet_in_module":
        return (
            _titel("Doelentiteit zonder administratie", doel),
            f"{_s(d, 'aantal') or '?'} verkoopfactu(u)r(en) ({_s(d, 'som') or '?'}) van {bron} aan {doel}, maar {doel} heeft geen administratie in de module — de inkoop is niet toetsbaar.",
            "Koppel de administratie aan de whitelist-rij (Instellingen › Administraties › bron › Doorbelasting › 'Koppel administratie…') of onboard 'm eerst.",
        )
    if soort == "da_inkoop_zonder_verkoop":
        return (
            _titel("Inkoop in doel zonder verkoop bij de bron", onderwerp),
            f"In {doel} staat een inkoopfactuur van {bron} ({nummer or '?'}, {bi or '?'}) zonder verkoopfactuur bij {bron}.",
            "Controleer of de verkoop bij de bron ontbreekt (boek 'm) of de inkoop dubbel/verkeerd is — of accepteer met reden.",
        )
    return (_titel("Doorbelasting-aansluiting", onderwerp), tekst, "Beoordeel de afwijking en accepteer met reden als het klopt.")


def _projecten(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok `projecten` (blok 3 18-09): dubbel projectnummer binnen één administratie."""
    if soort == "project_nummer_dubbel":
        nummer = _s(d, "nummer") or "?"
        projecten = d.get("projecten") if isinstance(d.get("projecten"), list) else []
        namen = "; ".join(
            f"{p.get('naam')} ({p.get('status', 'lopend')}; {p.get('facturen', 0)} facturen, "
            f"{p.get('weekstaten', 0)} weekstaten, {p.get('planning', 0)} planningregels)"
            for p in projecten
            if isinstance(p, dict)
        )
        return (
            _titel("Projectnummer dubbel", _onderwerp_projecten(d)),
            f"Projectnummer {nummer} staat op {len(projecten) or 'meerdere'} projecten in deze administratie"
            + (f": {namen}." if namen else "."),
            "Kies welk project blijft en verhuis de facturen/uren/planning van de ander (klikpunt, nooit "
            "automatisch); zet de verliezer daarna op afgesloten (IsActive uit) — een project wordt nooit verwijderd. "
            "Lees-only rapport: `projecten-dubbele-nummers`.",
        )
    return (
        _titel("Afwijking projecten", _onderwerp_projecten(d)),
        _terugval_wat(d.get("detail") or tekst),
        f"Controleer de projecten; {_DOE_ACCEPTEER}",
    )


_BLOK_AFWIJKING = {
    "projecten": _projecten,
    "documenten": _documenten,
    "doorbelasting_aansluiting": _doorbelasting_aansluiting,
    "intercompany": _intercompany,
    "bank": _bank,
    "omzet": _omzet,
    "doorbelasting": _doorbelasting,
    "rlz_dubbel": _rlz_dubbel,
    "rekening_courant": _rekening_courant,
}


def _afwijking(blok: str, d: dict, tekst: str) -> tuple[str, str, str]:
    soort = _s(d, "afwijking_soort") or ""
    maker = _BLOK_AFWIJKING.get(blok)
    if maker is None:
        return (
            _titel("Afwijking", _onderwerp(blok, d)),
            _terugval_wat(d.get("detail") or tekst),
            (f"Controleer in RLZ; {_DOE_ACCEPTEER}"),
        )
    return maker(soort, d, tekst)


# ---- let-op / fout / uitgesloten ------------------------------------------------------------------

_REDEN_LABEL = {
    "gestorneerd": "van een gestorneerde doorbelasting",
    "vervallen_run": "van een vervallen boekpoging",
    "gestorneerd+vervallen_run": "van een gestorneerde doorbelasting én een vervallen boekpoging",
}


def _automatisering(d: dict, administratie_naam: str | None) -> tuple[str, str, str]:
    """LET-OP uit de tellers per automatisering (herstelrun 07-09 blok C): ontbrekende harde voorwaarde of een
    automatisering die zeven dagen stil is. Labels uit `app/reconciliatie/automatiseringen.py`; de handeling
    is altijd de instelling herstellen (deeplink op de rij) — nooit een menselijke instelling als poort."""
    from app.reconciliatie import automatiseringen as auto

    label = _s(d, "automatisering_label") or _s(d, "automatisering") or "automatisering"
    reden = str(d.get("reden") or "")
    aantal = d.get("aantal") or 0
    waar = _s(d, "administratie_naam") or administratie_naam
    if reden == auto.STIL_7_DAGEN:
        return (
            _titel("Stil sinds zeven dagen", label),
            f"{label} staat aan, maar deed {auto.STIL_DAGEN} dagen niets bij {aantal} kandidaat/kandidaten — "
            "geen boeking en geen geregistreerde reden.",
            "Controleer de instelling en het achtergrondwerk (sync-alles/Cloud Run-jobs); blijft het stil, "
            "dan is het een storing.",
        )
    if reden == auto.ZONDER_AI_TOETS:
        # Blok 4 (10-09 avond): geen ontbrekende voorwaarde — de boekingen zijn er, zonder AI-oordeel (technische
        # uitval van de toets). Handeling = steekproef op de plek van de boekingen (deeplink op de rij).
        oorzaak = str(d.get("oorzaak") or "")
        oorzaak_label = auto.REDEN_LABEL.get(oorzaak, oorzaak.replace("_", " ") or "onbekende oorzaak")
        boeking_soort = _s(d, "boeking_soort") or "bank"
        plek = "het bankscherm" if boeking_soort == "bank" else "de documentenlijst (filter automatisch geboekt)"
        return (
            _titel("Automatisch geboekt zonder AI-toets", waar or ""),
            f"{aantal} automatische {boeking_soort}boeking(en){f' in {waar}' if waar else ''} liepen door zonder "
            f"AI-plausibiliteitstoets — de toets viel technisch uit ({oorzaak_label}); de deterministische controles "
            "waren groen.",
            f"Controleer steekproefsgewijs of rekening en btw kloppen via {plek}; herstel zo nodig de oorzaak "
            "(Instellingen › Intake & AI) zodat de toets weer meeloopt.",
        )
    if reden == auto.SA_KEY_ROTATIE:
        # Blok 1 nametingen-run 10-09 (§F7): beheer-signaal (systeemmail) — jaarlijkse rotatie van de nameting-key.
        return (
            _titel("Nameting-serviceaccount: key roteren", "beheer"),
            f"De key van het nameting-serviceaccount is aangemaakt op {_s(d, 'aangemaakt_op') or '?'}; de jaarlijkse "
            f"rotatiedatum is {_s(d, 'rotatie_op') or '?'}.",
            "Roteer volgens GCP_UITROL §F7: nieuwe key aanmaken en activeren, oude key verwijderen, "
            "NAMETING_SA_AANGEMAAKT_OP op de job bijwerken.",
        )
    if reden == auto.DEPLOY_DRIFT:
        # Ochtendrun 11-09 blok 2.1: open bewakingsstoring deploy_drift — beheer-signaal; de bewaking alarmeert zelf.
        sinds = _s(d, "sinds") or "?"
        return (
            _titel("Deploy-drift: jobs achter op de service", "beheer"),
            f"De Cloud Run-jobs draaien op een ander beeld dan de service (bewaking sinds "
            f"{sinds[:16].replace('T', ' ')} UTC, {aantal} metingen): "
            f"{zonder_guids(_s(d, 'laatste_detail') or '')[:300]}.",
            auto.REGRESSIE_TEKST[0].upper() + auto.REGRESSIE_TEKST[1:] + ". Controleer de deploy-workflow (GitHub "
            "Actions) — de eerstvolgende groene push zet jobs én service-envs weer gelijk; handmatig jobs bijwerken "
            "hoort niet (regel 08-09).",
        )
    if reden == auto.RLS_WEIGERING:
        # Blok 1 run 11-09: een schrijfpad van de app werd door Row-Level Security geweigerd — bug in de app-laag,
        # beheer-signaal; de bewakingsprobe `rls_weigering` alarmeert zelf. Deeplink = het geraakte document.
        patroon = _s(d, "route_patroon") or _s(d, "route") or "onbekende route"
        tabel = _s(d, "tabel") or "?"
        laatste = (_s(d, "laatste_op") or "")[:16].replace("T", " ")
        return (
            _titel("RLS-weigering op een schrijfpad", "beheer"),
            f"Een handeling via {patroon} werd {aantal}× in {auto.VENSTER_UREN} u door Row-Level Security geweigerd "
            f"(tabel {tabel}{f', jongste {laatste} UTC' if laatste else ''}) — de gebruiker zag een leesbare "
            "foutmelding, er is niets gewijzigd.",
            auto.REGRESSIE_TEKST[0].upper() + auto.REGRESSIE_TEKST[1:] + ": RLS-weigering op " + patroon + ". "
            "Zoek in de server-log op de code uit de melding (correlatie-id) en herstel het schrijfpad of het "
            "beleid; de rij verdwijnt zodra er een etmaal geen weigering meer is.",
        )
    if reden == auto.RECHTEN_NA_24U:
        # Blok 3 run 11-09: de eerste sync kreeg 403 op een route die de rechten-probe groen had en is 24 u lang
        # herprobeerd (5/15/60 min, daarna elk uur) — RLZ weigert nog steeds. Handeling = het recht in RLZ + RLZ-check.
        voorbeeld = _s(d, "voorbeeld")
        return (
            _titel("Eerste sync: RLZ weigert na 24 uur nog steeds", waar or ""),
            f"De eerste sync{f' van {waar}' if waar else ''} kreeg een dag lang HTTP 403 op leesroutes die de "
            "rechten-probe groen had — RLZ heeft de rechten van de webservice-gebruiker niet doorgezet"
            + (f" ({zonder_guids(voorbeeld)[:300]})" if voorbeeld else "")
            + ".",
            "Controleer in Reeleezee de leesrechten van de webservice-gebruiker op deze administratie, klik dan "
            "'RLZ-check' en 'Sync opnieuw starten' op Instellingen › Administraties › ‹administratie›.",
        )
    if reden == auto.TOETS_UIT:
        # Blok 3.2 (10-09 avond): bewuste opt-out, geen storing — de keuze blijft zichtbaar tot iemand 'm terugdraait.
        sinds = _s(d, "voorbeeld") or "sinds onbekend moment"
        return (
            _titel("AI-toets facturen staat uit", "platformbreed"),
            f"De AI-plausibiliteitstoets vóór automatische factuurboekingen staat platformbreed uit {sinds}; "
            f"{aantal} automatische factuurboeking(en) liepen het afgelopen etmaal door zonder toets (alleen de "
            "vaste controles).",
            "Zet de toets weer aan via Instellingen › Boeken, of laat 'm bewust uit — deze melding blijft dan staan "
            "als herinnering.",
        )
    reden_label = auto.REDEN_LABEL.get(reden, reden.replace("_", " "))
    voorbeeld = _s(d, "voorbeeld")
    wat = (
        f"{label} sloeg {aantal} stuk(s) over{f' in {waar}' if waar else ''}: {reden_label}"
        + (f" ({zonder_guids(voorbeeld)[:120]})" if voorbeeld else "")
        + "."
    )
    if reden in auto.REGRESSIE_CATEGORIEEN:
        # Bundel 09-09 blok 1: een regressie-categorie is een bug, geen handeling voor de gebruiker. De run legt
        # audit `automatisering_regressie` vast en de bewaking alarmeert — hier alleen de constatering.
        doe_regressie = auto.REGRESSIE_TEKST[0].upper() + auto.REGRESSIE_TEKST[1:] + "."
        return _titel("Wacht op instelling", label), wat, doe_regressie
    doe = {
        auto.CREDENTIAL: "Registreer de webservice-login opnieuw (Instellingen › Administraties); "
        "de volgende run loopt door.",
        auto.API_KEY: "Zet de API-key (Instellingen › Intake & AI); de wachtende stukken worden daarna verwerkt.",
        auto.GELDPOORT: "Zet boeken weer aan (Instellingen › Boeken) of verwerk de wachtende stukken handmatig.",
        auto.NOODREM: "Zet de noodrem weer aan (Instellingen › Boeken) of voer de gesignaleerde duplicaten "
        "handmatig af.",
        auto.VOLUMEREM: "Verwerk de wachtende stukken handmatig of verhoog de dagelijkse limiet "
        "(Instellingen › Autoboeken).",
        auto.VANGNET_SCHEDULER: "De documenten zijn wél verwerkt (scheduler-vangnet, tot 10 min later). Controleer in "
        "Cloud Logging de melding 'triggeren mislukt' en het IAM-recht run.invoker van de service op de job "
        "rlz-extractie-wachtrij.",
        # Blok 1 bundel 08-09: bank-sync draait dagelijks in sync-alles; geen run = de job is niet (volledig) gedraaid.
        auto.GEEN_SYNC_RUN: "De nachtelijke bank-sync (job rlz-sync, 07:00) heeft deze administratie(s) niet bereikt. "
        "Controleer in Cloud Logging de regels 'bank-sync' van de laatste run (afgebroken/timeout?) en open desnoods "
        "het bankscherm van de klant — dat start direct een verversing.",
    }.get(reden, "Herstel de voorwaarde via de instelling op deze rij; de volgende run loopt door.")
    return _titel("Wacht op instelling", label), wat, doe


def _let_op(d: dict, tekst: str, administratie_naam: str | None) -> tuple[str, str, str]:
    if d.get("automatisering"):
        return _automatisering(d, administratie_naam)
    if d.get("rc_zonder_tegenrekening") or d.get("afwijking_soort") == "rc_zonder_tegenrekening":
        return _rc_zonder_tegenrekening(d, administratie_naam)
    if d.get("afwijking_soort") == "project_naam_afgesloten_status_actief":
        # Opdracht 19-09: de projectverdeling sluit afgesloten projecten uit op STATUS, nooit op naam — dit is de actie.
        naam = _s(d, "project_naam") or "?"
        return (
            _titel("Project heet 'Afgesloten' maar staat actief", administratie_naam or ""),
            f"Project {naam} heet afgesloten, maar de status is lopend en het project staat in de bron actief — de "
            "pro-rato-projectverdeling verdeelt er dus nog kosten over.",
            "Sluit het project af via Projecten › Afsluiten… (zet de bron inactief en de status afgesloten); daarna "
            "valt het uit de verdeelsleutel. Hoort het project wél open te blijven: hernoem het in Reeleezee.",
        )
    if d.get("reden") == "opruimlijst_fout" or (not d.get("kant") and "opruimlijst" in (tekst or "").lower()):
        return (
            "Opruimlijst niet compleet",
            _terugval_wat(re.sub(r"^LET-OP\s+opruimlijst:\s*", "", tekst or "")),
            "Controleer verbinding en credentials; de volgende run controleert opnieuw.",
        )
    if d.get("kant"):
        kant = (
            "verkoop-concept in de bron-administratie"
            if d["kant"] == "verkoop_bron"
            else "spiegel-concept in de doel-administratie"
        )
        waar = _s(d, "concept_administratie_naam") or (
            "de doel-administratie" if d["kant"] == "spiegel_doel" else administratie_naam
        )
        reden = _REDEN_LABEL.get(str(d.get("reden") or ""), str(d.get("reden") or "").replace("_", " "))
        bron = " ".join(x for x in (_s(d, "leverancier_naam"), _s(d, "factuurnummer")) if x)
        ref = _s(d, "referentie")
        van = f" van {bron}" if bron else ""
        refz = f" (ref {ref})" if ref else ""
        doel = _s(d, "doelentiteit_naam")
        doelz = f" aan {doel}" if doel else ""
        return (
            _titel("Achtergebleven concept in RLZ", waar or ""),
            f"Een {kant} {reden}{doelz}{van}{refz} staat nog in Reeleezee — "
            "het telt nergens mee, maar vervuilt de administratie.",
            "Opruimen is klikwerk in Reeleezee (de app verwijdert nooit); 'Gezien' met reden haalt 'm uit de teller.",
        )
    return (
        _titel("Let op", administratie_naam or ""),
        _terugval_wat(tekst),
        "Beoordeel de melding; 'Gezien' met reden haalt 'm uit de teller.",
    )


def _fout(blok: str, d: dict, tekst: str, administratie_naam: str | None) -> tuple[str, str, str]:
    t = tekst or ""
    if "viel om" in t:
        m = re.search(r"viel om:\s*(.*)$", t, re.DOTALL)
        return (
            _titel(f"Controle {blok} viel om", ""),
            f"Het blok {blok} is niet gedraaid: {zonder_guids(m.group(1)) if m else 'onbekende fout'}.",
            "Niets is gecontroleerd in dit blok; de volgende run probeert opnieuw. Blijft het, dan is het een storing.",
        )
    if "storno-detectie" in t:
        fout = _s(d, "fout") or re.sub(r"^FOUT\s+storno-detectie\s+\S+:\s*", "", t)
        return (
            _titel("Storno-detectie mislukt", administratie_naam or ""),
            f"De storno-detectie voor deze administratie kon niet draaien: {zonder_guids(fout)}.",
            _DOE_CONTROLE_MISLUKT,
        )
    fout = _s(d, "fout") or re.sub(r"^FOUT\s+\S+:\s*", "", t)
    return (
        _titel("Administratie niet gecontroleerd", administratie_naam or ""),
        f"Het blok {blok} kon deze administratie niet controleren: {zonder_guids(fout)}.",
        _DOE_CONTROLE_MISLUKT,
    )


def _uitgesloten(blok: str, d: dict, tekst: str, administratie_naam: str | None) -> tuple[str, str, str]:
    uitsluiting = _s(d, "uitsluiting")
    if d.get("bron"):
        titel, wat, _ = _afwijking(blok, d, tekst)
        return (
            titel,
            wat,
            "Deze administratie is uitgesloten van de teller"
            + (f" ({uitsluiting})" if uitsluiting else "")
            + "; geen handeling nodig, wel zichtbaar.",
        )
    m = re.search(r"\(uitgesloten:\s*(.*)\)\s*$", tekst or "")
    reden = uitsluiting or (m.group(1) if m else None)
    kern = re.sub(r"\s*\(uitgesloten:.*\)\s*$", "", re.sub(r"^UITGESLOTEN\s+\S+:\s*", "", tekst or ""))
    return (
        _titel("Uitgesloten van controle", administratie_naam or ""),
        f"{zonder_guids(kern) or 'De administratie kon niet gecontroleerd worden'}"
        + (f" — uitgesloten omdat: {reden}." if reden else "."),
        "Telt niet mee in de teller; geen handeling nodig.",
    )


# ---- details ----------------------------------------------------------------------------------------

_DETAIL_LABELS: tuple[tuple[str, str], ...] = (
    ("afwijking_soort", "soort"),
    ("backend", "systeem"),
    ("rlz_verleden", "vóór de overstap in Reeleezee geboekt"),
    ("record_id", "record"),
    ("document_id", "document-id"),
    ("extern_id", "extern id"),
    ("rlz_id", "RLZ-id"),
    ("rlz_document_id", "RLZ-document"),
    ("rlz_id_a", "RLZ-document A"),
    ("rlz_id_b", "RLZ-document B"),
    ("rlz_ids_tekst", "RLZ-documenten (cluster)"),
    ("cluster", "cluster-sleutel"),
    ("vervangen_door_vingerafdruk", "vervangen door cluster"),
    ("rlz_admin_id", "RLZ-administratie"),
    ("koppeling_id", "RC-koppeling"),
    ("venster_vanaf", "verklaringsvenster vanaf"),
    ("regel", "matchregel"),
    ("payment_transaction_id", "RLZ-mutatie"),
    ("payment_item_id", "RLZ-openstaande post"),
    ("concept_administratie_id", "administratie-id concept"),
    ("extern_state", "externe status"),
    ("boek_cyclus", "boekcyclus"),
    ("reden", "reden"),
    ("uitsluiting", "uitsluiting"),
    ("detail", "ruwe controle-uitkomst"),
)


def _details(bevinding: Any, d: dict) -> list[tuple[str, str]]:
    uit: list[tuple[str, str]] = []
    vaf = getattr(bevinding, "vingerafdruk", None)
    if vaf:
        uit.append(("vingerafdruk", str(vaf)))
    for sleutel, label in _DETAIL_LABELS:
        v = d.get(sleutel)
        if v in (None, "", False):
            continue
        uit.append((label, str(v)))
    tekst = getattr(bevinding, "tekst", None)
    if tekst:
        uit.append(("ruwe regel", str(tekst)))
    return uit


# ---- hoofdingang -----------------------------------------------------------------------------------


def leesbaar(bevinding: Any, *, administratie_naam: str | None = None, soort: str | None = None) -> Leesbaar:
    """Titel + wat + doe + details voor één bevinding van élk blok en élke soort. Faalt nooit: bij
    ontbrekende velden valt elke zin terug op de bestaande CLI-regel zonder GUID's. `soort` overschrijft
    de opgeslagen soort — de kantoorbrede lijst geeft de LIVE soort mee (geaccepteerd/afwijking na een
    acceptatie of intrekking zonder nieuwe run)."""
    d = dict(getattr(bevinding, "detail", None) or {})
    blok = str(getattr(bevinding, "blok", "") or "")
    soort = str(soort or getattr(bevinding, "soort", "") or "")
    tekst = str(getattr(bevinding, "tekst", "") or "")
    naam = administratie_naam or _s(d, "administratie_naam") or getattr(bevinding, "administratie_naam", None)
    try:
        if soort == "let_op":
            titel, wat, doe = _let_op(d, tekst, naam)
        elif soort == "fout":
            titel, wat, doe = _fout(blok, d, tekst, naam)
        elif soort == "uitgesloten":
            titel, wat, doe = _uitgesloten(blok, d, tekst, naam)
        elif soort == "geaccepteerd":
            titel, wat, _ = _afwijking(blok, d, tekst)
            doe = "Beoordeeld en blijvend (geaccepteerd); intrekken kan via de actie op deze rij."
        else:
            titel, wat, doe = _afwijking(blok, d, tekst)
    except Exception:  # noqa: BLE001 — tekstopbouw mag een lijst of mail nooit laten omvallen
        titel, wat, doe = _titel("Bevinding", naam or ""), _terugval_wat(tekst), "Zie de technische details."
    return Leesbaar(titel=_kort(titel), wat=wat.strip(), doe=doe.strip(), details=_details(bevinding, d))


def bevat_technische_sleutel(tekst: str) -> bool:
    """Testhulp + vangrail: staat er een GUID of vingerafdruk in een leesbare zin?"""
    return bool(_GUID.search(tekst or "") or _VAF.search(tekst or ""))
