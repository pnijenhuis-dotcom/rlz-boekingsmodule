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
}


def ai_uit_json(data: dict) -> AiFactuurExtractie:
    kop = {naam: AiVeld(waarde=v.get("waarde"), zekerheid=float(v.get("zekerheid", 0.0))) for naam, v in data["kop"].items()}
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
        )
        for r in data.get("regels", [])
    ]
    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=0, volledig=bool(data.get("volledig", True)))


def alle_casussen() -> list[Casus]:
    """Alle DOCUMENT-casussen (map mét pdf_tekst.json); bank-casussen (mutaties.json) vallen erbuiten."""
    return [Casus(p.name) for p in sorted(FIXTURES.iterdir()) if p.is_dir() and (p / "pdf_tekst.json").exists()]


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_TIJDSTIP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


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
                return "2026-09-08T12:00:00Z"
            return _UUID.sub(lambda m: _id(m.group(0)), obj)
        return obj

    return _loop(payload)
