"""Gouden set — één ketentest op échte (geanonimiseerde) documenten (blok 0 herstelrun "Basis eerst", 08-09-2026).

Elke casus loopt de ECHTE keten: intake (mail-/bestandsroute) → bundeling/nabundel → extractie (deterministische
stub die de bewaarde AI-uitkomst afspeelt) → prefill (regel_prefill/veldvoorstel_regels) → checks → lijst-DTO →
afvoer/status. Geen echte AI-call, geen echte RLZ-call: de RLZ-kant is een FakeBoekClient (tests/documenten/
fake_rlz_client.py) die per test treffers krijgt.

De testadministratie heet 'Universal Steigerbouw B.V.' (de tenaamstelling op álle casus-UBL's behalve BOOT/Kempen),
mét projectplicht, boeken aan, AI-extractie aan, intake-AI aan en ZONDER eigenaar (casus j: leeg = doorlopen).

Doelgedrag van deze run dat nog niet staat is `@pytest.mark.xfail(strict=True, reason="blok N — …")` gemarkeerd;
de agent van blok N haalt zijn xfail weg zodra zijn gedrag staat (grep op "blok N" in tests/keten)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, duplicaatsignaal, tegenboeken
from app.documenten import service as documenten_service
from app.documenten.models import CrediteurKenmerk, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.intake.conftest import bouw_eml
from tests.keten import casussen
from tests.keten.casussen import Casus, normaliseer_voor_export

UNIVERSAL_NAAM = "Universal Steigerbouw B.V."

# Stamgegevens (vaste id's zodat de frontend-fixtures stabiel blijven).
TAXRATE_HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
TAXRATE_VERLEGD_HOOG = uuid.UUID("55555555-0000-0000-0000-000000000009")
TAXRATE_GEEN_BTW = uuid.UUID("55555555-0000-0000-0000-000000000000")
GB_INHUUR = uuid.UUID("44444444-0000-0000-0000-000000004400")
GB_HUUR_MATERIEEL = uuid.UUID("44444444-0000-0000-0000-000000004600")
GB_ADVIES = uuid.UUID("44444444-0000-0000-0000-000000004700")
PROJECT_26049 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026049")  # Hoofddorp (Spot Services 2026-608)
PROJECT_25011 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000025011")  # Zwolle (Floor 26219)
PROJECT_26084 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026084")  # Werk 26084 (Universal Nederland, werknummer W03611)

VENDORS: dict[str, tuple[uuid.UUID, str]] = {
    "universal_nederland": (uuid.UUID("33333333-0000-0000-0000-000000000001"), "Universal Nederland B.V."),
    "floor": (uuid.UUID("33333333-0000-0000-0000-000000000002"), "Floor Bouwliftenservice"),
    "spot": (uuid.UUID("33333333-0000-0000-0000-000000000003"), "Spot Services B.V."),
    "bdo": (uuid.UUID("33333333-0000-0000-0000-000000000004"), "BDO Accountancy, Tax & Legal B.V."),
    # Zoals in RLZ (productie): de crediteurnaam wijkt af van de UBL-partijnaam 'DCTE B.V.' — match hoort op KvK/btw.
    "dcte": (uuid.UUID("33333333-0000-0000-0000-000000000005"), "DCTE B.V. (Derks Computers, Telecom & Electronica)"),
    "kader": (uuid.UUID("33333333-0000-0000-0000-000000000006"), "Kader Consultancy & Interim B.V."),
    "boot": (uuid.UUID("33333333-0000-0000-0000-000000000007"), "BOOT organiserend ingenieursburo B.V."),
}

FRONTEND_KETEN_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "dev" / "keten"


def _sha(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


@dataclass
class AiStub:
    """Speelt per PDF (sha256) de bewaarde AI-uitkomst af; een onbekende PDF is een testfout (nooit een gok)."""

    antwoorden: dict[str, AiFactuurExtractie] = field(default_factory=dict)
    # Op tekstmarker (casus d): een gesplitst deel heeft nieuwe bytes (pypdf), maar draagt zijn factuurnummer in de
    # tekstlaag — dáárop herkent de stub het bewaarde antwoord van dat deel.
    op_marker: list[tuple[bytes, AiFactuurExtractie]] = field(default_factory=list)
    aanroepen: list[str] = field(default_factory=list)

    def registreer(self, pdf: bytes, antwoord: AiFactuurExtractie) -> None:
        self.antwoorden[_sha(pdf)] = antwoord

    def registreer_op_marker(self, marker: str, antwoord: AiFactuurExtractie) -> None:
        self.op_marker.append((marker.encode("latin-1"), antwoord))

    def __call__(self, pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        sleutel = _sha(pdf_bytes)
        self.aanroepen.append(sleutel)
        if sleutel in self.antwoorden:
            return self.antwoorden[sleutel]
        for marker, antwoord in self.op_marker:
            if marker in pdf_bytes:
                return antwoord
        raise AssertionError("gouden set: AI-extractie gevraagd voor een PDF zonder geregistreerd ai_antwoord.json")


@dataclass
class SplitsingStub:
    """Intake-splitsings-AI: per PDF (sha256) het bewaarde voorstel; default = één factuur over alle pagina's met
    de tenaamstelling van de testadministratie (zoals de AI dat voor een enkelvoudige Universal-factuur leest)."""

    antwoorden: dict[str, list[FactuurSegment]] = field(default_factory=dict)
    aanroepen: list[str] = field(default_factory=list)
    standaard_tenaamstelling: str = UNIVERSAL_NAAM

    def registreer(self, pdf: bytes, segmenten: list[FactuurSegment]) -> None:
        self.antwoorden[_sha(pdf)] = segmenten

    def __call__(self, inhoud: bytes, *, paginas: int, verbruik_referentie=None, mail_context=None) -> list[FactuurSegment]:
        sleutel = _sha(inhoud)
        self.aanroepen.append(sleutel)
        if sleutel in self.antwoorden:
            return self.antwoorden[sleutel]
        return [
            FactuurSegment(
                start_pagina=1,
                eind_pagina=paginas,
                tenaamstelling=self.standaard_tenaamstelling,
                leverancier=None,
                factuurnummer=None,
                zekerheid=0.9,
                documentsoort="factuur",
            )
        ]


@pytest.fixture
def universal(
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
    admin_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> uuid.UUID:
    """De testadministratie als Universal Steigerbouw: naam (tenaamstelling-register), projectplicht, boeken aan,
    AI-extractie aan, intake-AI aan (platform-gate), API-key gezet, GEEN eigenaar (casus j)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = :naam, project_verplicht = true WHERE id = :id"),
            {"naam": UNIVERSAL_NAAM, "id": administratie_id},
        )
        conn.execute(text("UPDATE platform.intake_instelling SET ai_ingeschakeld = true"))
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return administratie_id


def _kenmerken_uit_xml(xml: bytes) -> tuple[str | None, str | None]:
    """(btw-nummer, KvK) van de LEVERANCIER uit een casus-UBL (geanonimiseerde waarden)."""
    tekst = xml.decode("utf-8")
    m = re.search(r"<cac:AccountingSupplierParty>(.*?)</cac:AccountingSupplierParty>", tekst, re.S)
    blok = m.group(1) if m else ""
    btw = re.search(r"NL\d{9}B\d{2}", blok)
    kvk = re.search(r"(?:schemeID=\"(?:0106|NL:KVK)\"[^>]*>|schemeAgencyName=\"KvK\">)(\d{8})<", blok)
    return (btw.group(0) if btw else None), (kvk.group(1) if kvk else None)


@pytest.fixture
def stamgegevens(universal: uuid.UUID, admin_engine: Engine) -> dict[str, uuid.UUID]:
    """Crediteuren (mét btw-/KvK-kenmerk uit de casus-UBL's), btw-tarieven, grootboek en projecten zoals de
    Universal-administratie ze uit RLZ kent."""
    kenmerken = {
        "universal_nederland": _kenmerken_uit_xml(Casus(casussen.A_UNIVERSAL_NEDERLAND).xml()),
        "floor": _kenmerken_uit_xml(Casus(casussen.B_FLOOR).xml()),
        "bdo": _kenmerken_uit_xml(Casus(casussen.H_BDO).xml()),
        "dcte": _kenmerken_uit_xml(Casus(casussen.K1_DCTE).xml()),
        "kader": _kenmerken_uit_xml(Casus(casussen.K2_KADER).xml()),
        "boot": _kenmerken_uit_xml(Casus(casussen.E_BOOT).xml()),
    }
    spot_kop = json.loads((Casus(casussen.C_SPOT).map / "ai_antwoord.json").read_text())["kop"]
    kenmerken["spot"] = (spot_kop["btw_nummer"]["waarde"], spot_kop["kvk_nummer"]["waarde"])
    with scoped_session(universal) as session:
        for sleutel, (vendor_id, naam) in VENDORS.items():
            session.add(VendorCache(id=vendor_id, administratie_id=universal, naam=naam, brondata={"Name": naam}))
            btw, kvk = kenmerken[sleutel]
            session.add(
                CrediteurKenmerk(
                    administratie_id=universal,
                    vendor_id=vendor_id,
                    btw_nummer=btw,
                    btw_nummer_geverifieerd=bool(btw),
                    btw_nummer_bron="factuur" if btw else None,
                    kvk_nummer=kvk,
                    kvk_nummer_bron="rlz" if kvk else None,
                )
            )
        for id_, naam, pct, brondata in (
            (TAXRATE_HOOG, "NL, Hoog Tarief", Decimal("0.2100"), {"IsRelayed": False, "IsFavorite": True, "Percentage": 0.21}),
            (TAXRATE_VERLEGD_HOOG, "NL, BTW verlegd (hoog)", Decimal("0"), {"IsRelayed": True, "IsFavorite": False, "Percentage": 0.0}),
            (TAXRATE_GEEN_BTW, "NL, Geen BTW (Vrijgesteld)", Decimal("0"), {"IsRelayed": False, "IsExcempt": True, "Percentage": 0.0}),
        ):
            session.add(
                TaxRateCache(
                    id=id_, administratie_id=universal, naam=naam, percentage=pct, brondata={"Name": naam, **brondata}
                )
            )
        for ledger_id, code, naam in (
            (GB_INHUUR, "4400", "Inhuur onderaannemers"),
            (GB_HUUR_MATERIEEL, "4600", "Huur materieel"),
            (GB_ADVIES, "4700", "Advies- en accountantskosten"),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id, administratie_id=universal, code=code, naam=naam, soort=2, is_totaalrekening=False
                )
            )
        for project_id, naam in (
            (PROJECT_26049, "26049 Hoofddorp (Grunsven)"),
            (PROJECT_25011, "25011 Zwolle (Bouwbedrijf Zwolle)"),
            (PROJECT_26084, "26084 Opdrachtgever A (Universal Nederland)"),
        ):
            session.add(ProjectCache(id=project_id, administratie_id=universal, naam=naam, is_actief=True, brondata={}))
    return {sleutel: vendor_id for sleutel, (vendor_id, _) in VENDORS.items()}


@pytest.fixture
def ai_stub(monkeypatch: pytest.MonkeyPatch) -> AiStub:
    stub = AiStub()
    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", stub)
    # Regel-GB-classificatie (blok D 04-09) doet een eigen AI-call — in de gouden set bewust uit.
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)
    return stub


@pytest.fixture
def splitsing_stub(monkeypatch: pytest.MonkeyPatch) -> SplitsingStub:
    stub = SplitsingStub()
    monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", stub)
    return stub


@pytest.fixture
def rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    """Dé RLZ-kant voor de hele keten (checks, duplicaatsignaal, boeken, tegenboeken) — één instantie per test,
    zodat een test `rlz.duplicaten = [...]` kan zetten en `rlz.puts` kan lezen."""
    client = FakeBoekClient()
    for module in (boekvoorstel, duplicaatsignaal, boeken, tegenboeken):
        monkeypatch.setattr(module, "client_voor_rlz_admin_id", lambda rlz_admin_id, _c=client: _c)
    return client


@pytest.fixture
def keten(
    universal: uuid.UUID,
    stamgegevens: dict[str, uuid.UUID],
    ai_stub: AiStub,
    splitsing_stub: SplitsingStub,
    rlz: FakeBoekClient,
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
    admin_engine: Engine,
) -> Keten:
    return Keten(
        administratie_id=universal,
        vendors=stamgegevens,
        ai=ai_stub,
        splitsing=splitsing_stub,
        rlz=rlz,
        actor=gescoopte_gebruiker,
        opslag=opslag,
        admin_engine=admin_engine,
        api=TestClient(app),
    )


@dataclass
class Keten:
    """De ketenstappen als één handvat per test (alle echte servicelaag-/API-aanroepen, geen shortcuts)."""

    administratie_id: uuid.UUID
    vendors: dict[str, uuid.UUID]
    ai: AiStub
    splitsing: SplitsingStub
    rlz: FakeBoekClient
    actor: uuid.UUID
    opslag: LokaleBestandsopslag
    admin_engine: Engine
    api: TestClient

    # ---- intake -------------------------------------------------------------------------------------------------
    def mail(
        self,
        bijlagen: list[tuple[str, bytes]],
        *,
        afzender: str = casussen.AFZENDER_UNIVERSAL,
        onderwerp: str = "Facturen universal steigerbouw",
        message_id: str | None = None,
    ):
        """Eén intake-bericht (IMAP-route) met de gegeven bijlagen — zoals de leverancier/RLZ 'm stuurde."""
        eml = bouw_eml(
            afzender=afzender,
            onderwerp=onderwerp,
            message_id=message_id,
            bijlagen=[(naam, inhoud, *_mime(naam)) for naam, inhoud in bijlagen],
        )
        return verwerking.verwerk_eml(eml, actor_id=self.actor, bron="imap", opslag=self.opslag)

    def upload(self, bestandsnaam: str, inhoud: bytes):
        """Losse upload in de administratie (werkvoorraad-sleepzone mét klant)."""
        return documenten_service.upload_document(
            administratie_id=self.administratie_id,
            bestandsnaam=bestandsnaam,
            inhoud=inhoud,
            actor_id=self.actor,
            opslag=self.opslag,
        )

    # ---- lezen ----------------------------------------------------------------------------------------------------
    def document(self, document_id: uuid.UUID):
        return documenten_service.haal_document_op(administratie_id=self.administratie_id, document_id=document_id)

    def status(self, document_id: uuid.UUID) -> DocumentStatus:
        return self.document(document_id).document.status

    def rij(self, document_id: uuid.UUID) -> dict:
        with self.admin_engine.connect() as conn:
            return dict(
                conn.execute(
                    text(
                        "SELECT status, toegewezen_aan, samengevoegd_in_id, mogelijk_duplicaat_van_id, bron_bestandsnaam, "
                        "administratie_id FROM boekhouding.document WHERE id = :id"
                    ),
                    {"id": document_id},
                )
                .mappings()
                .one()
            )

    def tijdlijn(self, document_id: uuid.UUID) -> list[dict]:
        with self.admin_engine.connect() as conn:
            return [
                dict(d) if d else {}
                for d in conn.execute(
                    text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id ORDER BY tijdstip"),
                    {"id": document_id},
                ).scalars()
            ]

    def afwijzing(self, document_id: uuid.UUID) -> dict | None:
        with self.admin_engine.connect() as conn:
            rij = (
                conn.execute(
                    text(
                        "SELECT status, reden, automatisch, toegewezen_aan, duplicaat_van_document_id, "
                        "duplicaat_van_rlz_document_id, duplicaat_van_referentie FROM boekhouding.afwijzing "
                        "WHERE document_id = :id ORDER BY afgewezen_op DESC LIMIT 1"
                    ),
                    {"id": document_id},
                )
                .mappings()
                .first()
            )
        return dict(rij) if rij else None

    # ---- API (zoals de kantoor-frontend) ------------------------------------------------------------------------
    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(self.actor, rol='boekhouding')}"}

    def lijst(self, **params) -> dict:
        resp = self.api.get(f"/administraties/{self.administratie_id}/documenten", params=params, headers=self.headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def standaardlijst_ids(self) -> set[str]:
        return {d["id"] for d in self.lijst()["documenten"]}

    def lijst_rij(self, document_id: uuid.UUID, **params) -> dict | None:
        return next((d for d in self.lijst(**params)["documenten"] if d["id"] == str(document_id)), None)

    def open_controlescherm(self, document_id: uuid.UUID) -> dict:
        """GET boekvoorstel = het openen van het controlescherm (persisteert de prefill, A10 07-09)."""
        resp = self.api.get(
            f"/administraties/{self.administratie_id}/documenten/{document_id}/boekvoorstel", headers=self.headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def detail(self, document_id: uuid.UUID) -> dict:
        resp = self.api.get(f"/administraties/{self.administratie_id}/documenten/{document_id}", headers=self.headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def prefill(self, document_id: uuid.UUID) -> boekvoorstel.BoekvoorstelData:
        return boekvoorstel.haal_boekvoorstel_op(administratie_id=self.administratie_id, document_id=document_id)

    def checks(self, document_id: uuid.UUID) -> dict[str, tuple[bool, str]]:
        """Harde checks over het (opgeslagen/geprefillde) voorstel — {naam: (ok, melding)}."""
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=self.administratie_id, document_id=document_id, client=self.rlz
        )
        return {r.naam: (r.ok, r.melding) for r in rapport.resultaten}

    def checks_dto(self, document_id: uuid.UUID) -> dict:
        resp = self.api.post(
            f"/administraties/{self.administratie_id}/documenten/{document_id}/boekvoorstel/checks",
            headers=self.headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # ---- frontend-fixture-export ------------------------------------------------------------------------------------
    def exporteer(self, casus: str, document_id: uuid.UUID, *, extra: dict | None = None) -> None:
        """Schrijft de DTO's die het controlescherm en de documentenlijst voor dit document tonen naar
        frontend/src/dev/keten/<casus>.json — het frontend-harnas (harness-keten.html) rendert exact deze stand."""
        if not FRONTEND_KETEN_DIR.parent.exists():
            return
        FRONTEND_KETEN_DIR.mkdir(exist_ok=True)
        # Stamgegevens (crediteuren, btw-tarieven, grootboek, projecten) houden hun vaste id — het harnas kent ze.
        stam = [v for v, _ in VENDORS.values()] + [
            TAXRATE_HOOG, TAXRATE_VERLEGD_HOOG, TAXRATE_GEEN_BTW, GB_INHUUR, GB_HUUR_MATERIEEL, GB_ADVIES,
            PROJECT_26049, PROJECT_25011, PROJECT_26084,
        ]
        vaste = {str(x).lower(): str(x).lower() for x in stam}
        vaste[str(self.administratie_id).lower()] = "aaaaaaaa-0000-4000-8000-000000000001"
        vaste[str(document_id).lower()] = "bbbbbbbb-0000-4000-8000-000000000001"
        payload = {
            "casus": casus,
            "administratie_id": vaste[str(self.administratie_id).lower()],
            "document_id": vaste[str(document_id).lower()],
            "detail": self.detail(document_id),
            "boekvoorstel": self.open_controlescherm(document_id),
            "checks": self.checks_dto(document_id),
            "lijst": self.lijst(),
            "lijst_afgehandeld": self.lijst(toon_afgehandeld="true"),
            **(extra or {}),
        }
        (FRONTEND_KETEN_DIR / f"{casus}.json").write_text(
            json.dumps(normaliseer_voor_export(payload, vaste_ids=vaste), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _mime(naam: str) -> tuple[str, str]:
    lager = naam.lower()
    if lager.endswith(".xml"):
        return "application", "xml"
    if lager.endswith(".pdf"):
        return "application", "pdf"
    return "application", "octet-stream"


VANDAAG_NA_BOEKEN = date(2026, 9, 8)
