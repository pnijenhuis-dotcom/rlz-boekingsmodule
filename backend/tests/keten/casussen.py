"""Gouden set — laden van de geanonimiseerde échte casussen (blok 0 herstelrun 08-09).

Per casusmap onder `fixtures/`:
- `factuur.xml` / `creditnota.xml`  — de échte UBL uit productie, geanonimiseerd (IBAN/KvK/btw/e-mail/telefoon/
  persoonsnamen vervangen door syntactisch geldige fictieve waarden; bedrijfsnamen, bedragen, factuurnummers en
  datums exact). Een ingesloten PDF staat als placeholder `KETEN-INGESLOTEN-PDF` en wordt bij het laden vervangen
  door de base64 van de gegenereerde vervang-PDF, zodat de ingesloten en de losse PDF byte-identiek zijn (zoals in
  productie — bundelreden `ingesloten_pdf_hash`).
- `pdf_tekst.json`                   — kerntekst per pagina voor de vervang-PDF (tests/keten/pdf.py).
- `ai_antwoord.json`                 — de AI-uitkomst voor die PDF in AiFactuurExtractie-vorm (kop/regels/
  zekerheden). Productie bewaart alleen het gecontroleerde `veldvoorstel`; dit is dezelfde inhoud in invoer-vorm.
- `splitsing_antwoord.json`          — het splitsingsvoorstel van de intake-AI (casus d).
- `bron.json`                        — herkomst (document-id's, intake-bericht, productie-uitkomst), voor de lezer.

Geen echte AI-call: de stubs in conftest.py spelen deze bestanden af, gekoppeld aan de sha256 van de PDF-bytes."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.extractie.splitsing import FactuurSegment
from tests.keten.pdf import maak_pdf

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLACEHOLDER = "KETEN-INGESLOTEN-PDF"

A_UNIVERSAL_NEDERLAND = "a_universal_nederland_rlz2080143037"
B_FLOOR = "b_floor_26219"
C_SPOT = "c_spot_services_2026_608"
D_SPLITSING = "d_universal_nederland_splitsing_rlz2080143038_39"
E_BOOT = "e_boot_creditnota_202633199"
H_BDO = "h_bdo_6088744"
K1_DCTE = "k1_dcte_202611050"
K2_KADER = "k2_kader_f212604921"
# Blok 3 bundel 08-09 (B3): synthetische incasso-factuur (betaalstatus) — zie fixtures/m_incasso_factuur/bron.json.
M_INCASSO = "m_incasso_factuur"
# Blok 2 bundel 08-09 (bankmatchmotor): géén document-casus maar een bank-casus — mutaties.json + open_posten.json
# (productiegevallen C.V. 08-09 + TransIP/NPG); `alle_casussen()` slaat 'm daarom over (geen factuur.xml/pdf_tekst).
L_BANK_CV = "l_bank_cv_08-09"
#: Peter 15-09: bankmatch op klantreferentie (Clean Care Arnhem).
Y_BANK_KLANTREFERENTIE = "y_bank_klantreferentie_15-09"
# Blok A bundel 10-09 (autoboeken per administratie — leerregel): géén eigen UBL maar varianten van casus h (BDO) met een
# ander factuurnummer per exemplaar — zie fixtures/q_autoboek_leren/bron.json; `alle_casussen()` slaat de map over.
Q_AUTOBOEK_LEREN = "q_autoboek_leren"
# Bug-onderzoek 15-09 (LHG/KPN-patroon): regels excl. btw + één btw-totaal — zie
# fixtures/w_telefonie_btw_totaal/bron.json.
W_TELEFONIE_BTW_TOTAAL = "w_telefonie_btw_totaal"
#: Peter 15-09: verlegd herkennen op kolomcode "V" zonder het woord verlegd (Olieman-patroon, bouw-onderaannemer).
Z_VERLEGD_KOLOMCODE = "z_verlegd_kolomcode_v"
# BUG 18-09 (Zilver Horeca Fac-25-022711, BLOW): btw-KOLOM per regel ("9%"/"0%"), afgedekte bedragen, pinbon-totaal,
# modus volgt de data.
AE_ZILVER_REGELKOLOM = "ae_zilver_horeca_regelkolom"
# Peter 16-09 (ProfX-opdracht): coffeeshop-kassarapport als PDF mét tekstlaag (pdf_tekst.json = journaal 4 pagina's,
# marge_tekst.json = margerapport) — zie fixtures/ad_omzet_profx_journaal/bron.json.
AD_OMZET_PROFX = "ad_omzet_profx_journaal"
# Peter 15-09 (omzetbronnen): géén document-casussen maar spreadsheet-rasters als JSON-grid
# (dagstaat_grid.json / kascheck_grid.json / export_grid.json) — `alle_casussen()` slaat ze over; zie bron.json per map.
#: Peter 16-09 (Zenvoices-casus Hello Kitchen / Kempen Facilities): UBL met referentie "2 4594 001722" terwijl RLZ het
#: exemplaar al kent als "24594001722" — de bestaanscheck moet genormaliseerd vergelijken (blok B).
AA_ZENVOICES_DUBBEL = "aa_zenvoices_dubbel"
#: Peter 18-09 (casus Rituals 88-186308, BLOW): 0 % · NL, Nul mét € 20,24 btw op € 96,36 — "btw volgt het tarief" + BUA.
AE_RITUALS_BUA = "ae_rituals_bua_0pct"
AB_OMZET_ZONNESTUDIO = "ab_omzet_zonnestudio"
AC_OMZET_PILATES = "ac_omzet_pilates"

AFZENDER_UNIVERSAL = "administratie@universal-steigerbouw.example"


@dataclass(frozen=True)
class Casus:
    naam: str

    @property
    def map(self) -> Path:
        return FIXTURES / self.naam

    def _json(self, bestand: str):
        return json.loads((self.map / bestand).read_text(encoding="utf-8"))

    @property
    def bron(self) -> dict:
        return self._json("bron.json")

    def pdf(self) -> bytes:
        """De deterministische vervang-PDF (alle pagina's uit pdf_tekst.json)."""
        return maak_pdf(self._json("pdf_tekst.json"))

    def pdf_paginas(self) -> int:
        return len(self._json("pdf_tekst.json"))

    def xml(self, *, ingesloten_pdf: bytes | None = None) -> bytes:
        """De UBL; `ingesloten_pdf` (default: de eigen vervang-PDF) vult de placeholder als die er is."""
        pad = self.map / "factuur.xml"
        if not pad.exists():
            pad = self.map / "creditnota.xml"
        tekst = pad.read_text(encoding="utf-8")
        if PLACEHOLDER in tekst:
            pdf = ingesloten_pdf if ingesloten_pdf is not None else self.pdf()
            tekst = tekst.replace(PLACEHOLDER, base64.b64encode(pdf).decode("ascii"))
        return tekst.encode("utf-8")

    def ai_antwoord(self, bestand: str = "ai_antwoord.json") -> AiFactuurExtractie:
        return ai_uit_json(self._json(bestand))

    def splitsing_antwoord(self) -> list[FactuurSegment]:
        return [FactuurSegment(**deel) for deel in self._json("splitsing_antwoord.json")]

    # ---- bank-casus (blok 2 bundel 08-09) ------------------------------------------------------------------
    def bank_mutaties(self) -> list[dict]:
        """Onverwerkte bankmutaties zoals de sync ze in `bank_mutatie` zet (bedragen als string, cent-exact)."""
        return self._json("mutaties.json")

    def bank_open_posten(self) -> list[dict]:
        """Open posten zoals de sync ze in `payment_item_cache` zet (RLZ-teken: inkoop negatief, verkoop positief)."""
        return self._json("open_posten.json")

    def bank_batch(self) -> dict:
        """Blok C 16-09: `{"sleutel", "mutatie", "posten", "post_zonder_sleutel"}` — een deels afgeletterde
        RLZ-betaalbatch (Bouwadvies-casus) plus de nog open posten met dezelfde batchsleutel. Additief: mutaties.json/open_posten.json
        ongewijzigd."""
        return self._json("batch.json")

    def bank_historie(self) -> dict:
        """Blok B bundel 10-09: `{"mutatie", "grootboek", "boekingen"}` — een vijfde open mutatie
        (huur, zonder open post) plus de historie-cache-rijen (`bank_historie_boeking`) waaruit de historie-regel 'm
        moet herkennen. Additief: mutaties.json/open_posten.json blijven ongewijzigd."""
        return self._json("historie.json")

    def xml_bestandsnaam(self) -> str:
        """Bestandsnaam zoals de leverancier/RLZ 'm meestuurde (uit bron.json-conventie: '<naam>.xml')."""
        return BESTANDSNAMEN[self.naam][0]

    def pdf_bestandsnaam(self) -> str:
        return BESTANDSNAMEN[self.naam][1]


# Echte bijlagenamen uit de intake-berichten (naamstam = bundelsleutel als er geen ingesloten PDF is).
BESTANDSNAMEN: dict[str, tuple[str, str]] = {
    A_UNIVERSAL_NEDERLAND: (
        "Universal Nederland B.V - RLZ-2080143037 - 2026-08-01.xml",
        "Universal Nederland B.V - RLZ-2080143037 - 2026-08-01.pdf",
    ),
    B_FLOOR: ("Floor Bouwliftenservice - 26219 - 2026-08-13.xml", "Floor Bouwliftenservice - 26219 - 2026-08-13.pdf"),
    C_SPOT: ("", "2026-608 Universal.pdf"),
    D_SPLITSING: ("", "Universal Nederland B.V - RLZ-2080143038 RLZ-2080143038 - 2026-08-01.pdf"),
    E_BOOT: ("Factuur 202633199.xml", "Factuur 202633199.pdf"),
    H_BDO: (
        "BDO Accountancy_ Tax _ Legal B.V - 6088744 - 2026-07-02.xml",
        "BDO Accountancy_ Tax _ Legal B.V - 6088744 - 2026-07-02.pdf",
    ),
    K1_DCTE: ("DCTE B.V - 202611050 - 2026-07-27.xml", "DCTE B.V - 202611050 - 2026-07-27.pdf"),
    K2_KADER: ("Factuur F212604921.xml", "Projectfactuur F212604921.PDF"),
    M_INCASSO: ("", "Factuur KTD-2026-09-0417.pdf"),
    W_TELEFONIE_BTW_TOTAAL: ("", "Factuur KTD-2026-09-0904.pdf"),
    AA_ZENVOICES_DUBBEL: ("Hello Kitchen Duiven B.V - 2 4594 001722 - 2026-08-10.xml", ""),
    Z_VERLEGD_KOLOMCODE: ("", "Factuur 32948.pdf"),
    AE_ZILVER_REGELKOLOM: ("", "2025-12-17_Zilverhoreca Groothandel B.V._25-022711.pdf"),
    AE_RITUALS_BUA: ("", "Rituals bon 88-186308.pdf"),
}


def ai_uit_json(data: dict) -> AiFactuurExtractie:
    kop = {
        naam: AiVeld(waarde=v.get("waarde"), zekerheid=float(v.get("zekerheid", 0.0)))
        for naam, v in data["kop"].items()
    }
    regels = [
        AiRegel(
            omschrijving=r.get("omschrijving"),
            netto_bedrag=r.get("netto_bedrag"),
            btw_bedrag=r.get("btw_bedrag"),
            hoeveelheid=r.get("hoeveelheid"),
            zekerheid=float(r.get("zekerheid", 0.9)),
            eenheid=r.get("eenheid"),
            stuksprijs=r.get("stuksprijs"),
            artikelcode=r.get("artikelcode"),
            project_tekst=r.get("project_tekst"),
            btw_kolom=r.get("btw_kolom"),
            niet_gelezen=r.get("niet_gelezen"),
        )
        for r in data.get("regels", [])
    ]
    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=0, volledig=bool(data.get("volledig", True)))


def zonder_btw_totaal(extractie: AiFactuurExtractie) -> AiFactuurExtractie:
    """Variant van een AI-uitkomst waarin de factuur géén leesbaar btw-totaal en géén incl-totaal draagt (15-09):
    sinds de
    factuur-niveau-afleiding (controle.py::leid_btw_af_uit_totaal) krijgen regels zonder regel-btw anders de code uit
    het
    btw-totaal — casussen u/v testen juist de stappen ná de factuur (grootboek-default, historie) en spelen daarom deze
    variant af ("Floor-PDF zonder leesbaar btw-totaal")."""
    kop = dict(extractie.kop)
    for veld in ("btw_bedrag", "totaal_incl"):
        kop[veld] = AiVeld(waarde=None, zekerheid=0.0)
    return AiFactuurExtractie(
        kop=kop,
        regels=extractie.regels,
        bsn_verwijderd=extractie.bsn_verwijderd,
        volledig=extractie.volledig,
        metriek=extractie.metriek,
    )


def alle_casussen() -> list[Casus]:
    """Alle DOCUMENT-casussen (map mét pdf_tekst.json); bank-casussen (mutaties.json) vallen erbuiten."""
    return [Casus(p.name) for p in sorted(FIXTURES.iterdir()) if p.is_dir() and (p / "pdf_tekst.json").exists()]


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_TIJDSTIP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
#: Hét vaste tijdstip in de frontend-fixtures — conftest.REFERENTIE_TIJDSTIP is dezelfde waarde (blok 5, 10-09 avond).
EXPORT_TIJDSTIP = "2026-09-08T12:00:00Z"


def normaliseer_voor_export(payload, *, vaste_ids: dict[str, str] | None = None):
    """Maakt een API-antwoord deterministisch voor de frontend-fixtures: élke UUID wordt — in volgorde van eerste
    voorkomen — een stabiel placeholder-id, tijdstippen worden één vaste waarde. `vaste_ids` pint bekende id's
    (administratie, document) op een gekozen placeholder zodat het harnas ze kan adresseren."""
    mapping: dict[str, str] = {k.lower(): v for k, v in (vaste_ids or {}).items()}
    placeholders = set(mapping.values())

    def _id(waarde: str) -> str:
        sleutel = waarde.lower()
        if sleutel in placeholders:
            return sleutel  # al een placeholder/vaste stamgegeven-id — nooit nog eens hernummeren
        if sleutel not in mapping:
            mapping[sleutel] = f"00000000-0000-4000-8000-{len(mapping) + 1:012d}"
        return mapping[sleutel]

    def _loop(obj):
        if isinstance(obj, dict):
            return {k: _loop(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_loop(v) for v in obj]
        if isinstance(obj, str):
            if _TIJDSTIP.match(obj):
                return EXPORT_TIJDSTIP
            return _UUID.sub(lambda m: _id(m.group(0)), obj)
        return obj

    return _loop(payload)
