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


def _onderwerp_doorbelasting(d: dict) -> Segmenten:
    doel = _s(d, "doelentiteit_naam", "doel_administratie_naam")
    ref = _s(d, "verkoop_referentie", "referentie")
    bron = " ".join(x for x in (_s(d, "leverancier_naam"), _s(d, "factuurnummer")) if x)
    return [x for x in (doel, f"ref {ref}" if ref else None, f"({bron})" if bron else None) if x]


def _onderwerp_rlz_dubbel(d: dict) -> Segmenten:
    """Blok 6 (08-09): leverancier · referentie(s) · beide boekstuknummers."""
    ref_a, ref_b = _s(d, "referentie_a"), _s(d, "referentie_b")
    refs = ref_a if ref_a and (ref_a == ref_b or not ref_b) else " / ".join(x for x in (ref_a, ref_b) if x)
    boekstukken = " + ".join(x for x in (_s(d, "boekstuk_a"), _s(d, "boekstuk_b")) if x)
    return [x for x in (_s(d, "leverancier_naam"), refs or None, boekstukken or None) if x]


_SCHEIDING = {"documenten": " ", "doorbelasting": " ", "bank": " · ", "omzet": " · ", "rlz_dubbel": " · "}


def _onderwerp(blok: str, d: dict) -> Segmenten:
    if blok == "documenten":
        return _onderwerp_documenten(d)
    if blok == "rlz_dubbel":
        return _onderwerp_rlz_dubbel(d)
    if blok == "bank":
        return _onderwerp_bank(d)
    if blok == "omzet":
        return _onderwerp_omzet(d)
    if blok == "doorbelasting":
        return _onderwerp_doorbelasting(d)
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


def _exemplaar(d: dict, kant: str) -> str:
    """'RLZ-04-00004037 (22-06-2026, € 1.234,56, concept, via de module)' — één RLZ-exemplaar van het paar."""
    delen = [
        datum(_s(d, f"datum_{kant}")),
        euro(_s(d, f"bedrag_{kant}")),
        "concept" if str(d.get(f"status_{kant}")) == "1" else None,
        "via de module geboekt" if d.get(f"van_module_{kant}") else None,
    ]
    binnen = ", ".join(x for x in delen if x)
    boekstuk = _s(d, f"boekstuk_{kant}") or "zonder boekstuknummer"
    return f"{boekstuk} ({binnen})" if binnen else boekstuk


def _rlz_dubbel(soort: str, d: dict, tekst: str) -> tuple[str, str, str]:
    """Blok 6 (08-09): mogelijk dubbel geboekt in Reeleezee — twee inkoopfacturen van dezelfde crediteur met
    dezelfde referentie, waarvan minstens één niet via de module kwam. De bedrag+datum-tak blijft alleen voor
    bevindingen van vóór blok 7 (herstelrun 08-09) in de DB — nieuwe paren zijn altijd op referentie.
    Handeling ligt in Reeleezee (de app verwijdert nooit); geen deeplink beschikbaar (geen bekende URL-vorm)."""
    onderwerp = _onderwerp_rlz_dubbel(d)
    lev = _s(d, "leverancier_naam") or "dezelfde crediteur"
    regel = str(d.get("regel") or "")
    ref_a, ref_b = _s(d, "referentie_a"), _s(d, "referentie_b")
    if "referentie" in regel and "bedrag_datum" in regel:
        waarom = f"dezelfde referentie {ref_a or ''} én hetzelfde bedrag op dezelfde datum".replace("  ", " ")
    elif "referentie" in regel:
        waarom = f"dezelfde referentie {ref_a or ref_b or ''}".strip()
    else:
        waarom = "hetzelfde bedrag op dezelfde factuurdatum" + (
            f" (referenties {ref_a} en {ref_b})" if ref_a and ref_b and ref_a != ref_b else ""
        )
    handmatig = (
        "geen van beide via de module geboekt (handmatig ingevoerd of geïmporteerd)"
        if not d.get("van_module_a") and not d.get("van_module_b")
        else "één ervan via de module, de andere handmatig ingevoerd"
    )
    concept = " Minstens één exemplaar is nog concept." if d.get("concept") else ""
    return (
        _titel("Mogelijk dubbel in RLZ", onderwerp, " · "),
        f"In Reeleezee staan twee inkoopfacturen van {lev} met {waarom}: {_exemplaar(d, 'a')} en "
        f"{_exemplaar(d, 'b')} — {handmatig}.{concept}",
        "Open beide boekstuknummers in Reeleezee en beoordeel; is er één dubbel, corrigeer dáár (de app verwijdert "
        "nooit). Klopt het zo, accepteer met reden.",
    )


_BLOK_AFWIJKING = {
    "documenten": _documenten,
    "bank": _bank,
    "omzet": _omzet,
    "doorbelasting": _doorbelasting,
    "rlz_dubbel": _rlz_dubbel,
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
            _titel("Automatisering stil", label),
            f"{label} staat aan, maar deed {auto.STIL_DAGEN} dagen niets bij {aantal} kandidaat/kandidaten — "
            "geen boeking en geen geregistreerde reden.",
            "Controleer de instelling en het achtergrondwerk (sync-alles/Cloud Run-jobs); blijft het stil, "
            "dan is het een storing.",
        )
    reden_label = auto.REDEN_LABEL.get(reden, reden.replace("_", " "))
    doe = {
        auto.CREDENTIAL: "Registreer de webservice-login opnieuw (Instellingen › Administraties); "
        "de volgende run loopt door.",
        auto.API_KEY: "Zet de API-key (Instellingen › Intake & AI); de wachtende stukken worden daarna verwerkt.",
        auto.GELDPOORT: "Zet boeken weer aan (Instellingen › Boeken) of verwerk de wachtende stukken handmatig.",
        auto.NOODREM: "Zet de noodrem weer aan (Instellingen › Boeken) of voer de gesignaleerde duplicaten "
        "handmatig af.",
        auto.VOLUMEREM: "Verwerk de wachtende stukken handmatig of verhoog de dagelijkse limiet "
        "(Instellingen › Autoboeken).",
        auto.GEEN_EIGENAAR: "Dit mag sinds 07-09 niet meer voorkomen (een eigenaar is geen poort): stel de eigenaar in "
        "(Instellingen › Administraties) en meld de regressie.",
        auto.VANGNET_SCHEDULER: "De documenten zijn wél verwerkt (scheduler-vangnet, tot 10 min later). Controleer in "
        "Cloud Logging de melding 'triggeren mislukt' en het IAM-recht run.invoker van de service op de job "
        "rlz-extractie-wachtrij.",
    }.get(reden, "Herstel de voorwaarde via de instelling op deze rij; de volgende run loopt door.")
    voorbeeld = _s(d, "voorbeeld")
    return (
        _titel("Automatisering wacht op voorwaarde", label),
        f"{label} sloeg {aantal} stuk(s) over{f' in {waar}' if waar else ''}: {reden_label}"
        + (f" ({zonder_guids(voorbeeld)[:120]})" if voorbeeld else "")
        + ".",
        doe,
    )


def _let_op(d: dict, tekst: str, administratie_naam: str | None) -> tuple[str, str, str]:
    if d.get("automatisering"):
        return _automatisering(d, administratie_naam)
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
    ("rlz_admin_id", "RLZ-administratie"),
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
