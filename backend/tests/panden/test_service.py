# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok D2 (bundel 10-09): `service.leid_af` met een dict-client — voorstellen in de DB, idempotent, dry-run schrijft
niets, mens wint, Overhead-project alleen gerapporteerd, 403 op één collectie = zichtbare fout."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.panden import service
from app.panden.models import Pand, PandBoeking
from app.rlz import lezen
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id  # noqa: F401

NOTARIS = {"id": str(uuid.uuid4()), "Name": "Ouwerkerk Notariaat B.V."}
HOMEKEUR = {"id": str(uuid.uuid4()), "Name": "Homekeur B.V."}
AKN = {"id": str(uuid.uuid4()), "Name": "Administratiekantoor Nijenhuis C.V."}


def _id(boekstuk: str) -> str:
    """Deterministisch RLZ-id per boekstuk — een herdraai van `_vgg()` levert dezelfde documenten."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-vgg-{boekstuk}"))


def _doc(
    boekstuk: str,
    tekst: str,
    *,
    datum: str,
    bedrag: float,
    entity: dict | None = None,
    status: int = 3,
    rlz_id: str | None = None,
) -> dict:
    return {
        "id": rlz_id or _id(boekstuk),
        "ReceiptNumber": boekstuk,
        "Reference": tekst,
        "Description": None,
        "Date": f"{datum}T00:00:00",
        "BookDate": f"{datum}T00:00:00",
        "BaseInvoiceAmount": bedrag,
        "Entity": entity,
        "Status": status,
    }


class NepClient:
    def __init__(
        self,
        collecties: dict[str, list[dict]],
        *,
        uploads: dict[str, list] | None = None,
        fouten: dict[str, RlzApiError] | None = None,
    ) -> None:
        self.collecties = collecties
        self.uploads = uploads or {}
        self.fouten = fouten or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        if path in self.fouten:
            raise self.fouten[path]
        if path.endswith("/Uploads"):
            _, doc_id, _ = path.split("/")
            return {"value": self.uploads.get(doc_id, [])}
        rijen = self.collecties.get(path, [])
        skip, top = int(params.get("$skip", 0)), int(params.get("$top", 200))
        return {"value": rijen[skip : skip + top]}

    def close(self) -> None:
        self.closed = True


AANKOOP_ID = _id("RLZ-06-00000012")
JAN_ID = _id("RLZ-06-00000013")
VERKOOP_ID = _id("RLZ-01-00000007")
KEURING_ID = _id("RLZ-04-00000868")
DOSSIER_ID = _id("RLZ-04-00000870")


def _vgg() -> dict[str, list[dict]]:
    return {
        "ManualJournals": [
            _doc(
                "RLZ-06-00000012",
                "Aankoop Kerkstraat 44 Ede dossier 2025.058870.01",
                datum="2025-09-02",
                bedrag=185000.0,
                rlz_id=AANKOOP_ID,
            ),
            _doc("RLZ-06-00000013", "Aankoop Jan Collongstraat 8, Arnhem", datum="2025-10-24", bedrag=210000.0),
            _doc("RLZ-06-00000020", "Rente lening Q3 2026", datum="2026-09-30", bedrag=1200.0),
        ],
        "SalesInvoices": [
            _doc(
                "RLZ-01-00000007",
                "Verkoop Kerkstraat 44, Ede",
                datum="2026-02-13",
                bedrag=225000.0,
                entity=NOTARIS,
                rlz_id=VERKOOP_ID,
            ),
        ],
        "PurchaseInvoices": [
            _doc(
                "RLZ-04-00000868",
                "95514 keuring Kerkstraat 44",
                datum="2026-08-28",
                bedrag=349.0,
                entity=HOMEKEUR,
                rlz_id=KEURING_ID,
            ),
            _doc(
                "RLZ-04-00000870",
                "honorarium dossier 2025.058870.01",
                datum="2025-09-03",
                bedrag=1862.91,
                entity=NOTARIS,
                rlz_id=DOSSIER_ID,
            ),
            _doc("RLZ-17-00000853", "2026047", datum="2026-09-01", bedrag=59.9, entity=AKN),
        ],
    }


def _tel(administratie_id: uuid.UUID) -> tuple[int, int]:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
        return (
            s.scalar(select(func.count()).select_from(Pand)) or 0,
            s.scalar(select(func.count()).select_from(PandBoeking)) or 0,
        )


class TestDryRun:
    def test_dry_run_schrijft_niets_en_rapporteert(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(_vgg(), uploads={AANKOOP_ID: [{"id": "u1", "FileName": "nota.pdf"}]})
        rapport = service.leid_af(administratie_id, dry_run=True, client=client)
        assert _tel(administratie_id) == (0, 0)
        assert rapport.dry_run is True and rapport.geschreven == {}
        assert rapport.gelezen == {"ManualJournals": 3, "SalesInvoices": 1, "PurchaseInvoices": 3}
        codes = {p.code: p for p in rapport.panden}
        assert set(codes) == {"kerkstraat-44", "jan-collongstraat-8"}
        kerk = codes["kerkstraat-44"]
        assert (kerk.aankoopdatum, kerk.verkoopdatum) == (date(2025, 9, 2), date(2026, 2, 13))
        assert kerk.dossiers == ["2025.058870.01"] and kerk.plaats == "Ede"
        assert kerk.tel() == {"aankoop": {"hoog": 1}, "verkoop": {"hoog": 1}, "kosten": {"midden": 1, "laag": 1}}
        assert codes["jan-collongstraat-8"].tel() == {"aankoop": {"midden": 1}}  # geen bijlage, geen dossier
        assert rapport.geen_signaal == {"ManualJournals": 1, "PurchaseInvoices": 1}  # rente + AKN → Overhead (mens)
        assert rapport.overhead_project == service.OVERHEAD_ONTBREEKT
        assert rapport.bijlage_checks == 2  # alleen memorialen mét adres/dossier
        assert all(p.db_status == "dry-run: zou nieuw zijn" for p in rapport.panden)
        assert client.closed is False  # meegegeven client wordt niet gesloten
        md = service.als_markdown(rapport, administratie_naam="VGG")
        assert (
            "DRY-RUN — niets geschreven" in md
            and "| Kerkstraat 44 | Ede | 2025-09-02 | 2026-02-13 | 2025.058870.01 |" in md
        )
        assert "Overhead-project ontbreekt — aanmaken in run 2" in md

    def test_dossier_zonder_adres_haakt_aan_bij_pand_met_dat_dossier(self, administratie_id: uuid.UUID) -> None:
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_vgg()))
        kerk = next(p for p in rapport.panden if p.code == "kerkstraat-44")
        assert any(k.boeking.rlz_id == uuid.UUID(DOSSIER_ID) and k.zekerheid == "laag" for k in kerk.koppelingen)

    def test_alleen_dossier_zonder_bekend_pand_wordt_dossier_pand(self, administratie_id: uuid.UUID) -> None:
        data = {
            "ManualJournals": [_doc("RLZ-06-1", "Notarisafrekening 2026.014305.01", datum="2026-07-15", bedrag=1.0)],
            "SalesInvoices": [],
            "PurchaseInvoices": [],
        }
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(data))
        assert [p.code for p in rapport.panden] == ["dossier-2026-014305-01"]
        assert rapport.panden[0].adres == "dossier 2026.014305.01 (adres onbekend)"

    def test_403_op_een_collectie_is_zichtbare_fout(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(_vgg(), fouten={"SalesInvoices": RlzApiError(403, "GET", "SalesInvoices", "Forbidden")})
        rapport = service.leid_af(administratie_id, dry_run=True, client=client)
        assert rapport.fouten == ["SalesInvoices: 403 — collectie niet gelezen (Forbidden)"]
        assert "SalesInvoices" not in rapport.gelezen and len(rapport.panden) == 2

    def test_pagineert(self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lezen, "PAGINA_GROOTTE", 2)
        client = NepClient(_vgg())
        service.leid_af(administratie_id, dry_run=True, client=client)
        skips = [p["$skip"] for pad, p in client.calls if pad == "PurchaseInvoices"]
        assert skips == ["0", "2"]
        assert [p.get("$expand") for pad, p in client.calls if pad == "ManualJournals"][0] == "JournalEntryDiary"

    def test_overhead_project_aanwezig_in_projectcache(self, administratie_id: uuid.UUID, admin_engine) -> None:  # noqa: ANN001
        pid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                    "VALUES (:id, :aid, 'Overhead', true, '{}'::jsonb)"
                ),
                {"id": pid, "aid": administratie_id},
            )
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_vgg()))
        assert rapport.overhead_project == f"Overhead-project aanwezig: Overhead ({pid})"


class TestSchrijf:
    def test_schrijft_voorstellen_idempotent(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(_vgg(), uploads={AANKOOP_ID: [{"id": "u1"}]})
        r1 = service.leid_af(administratie_id, dry_run=False, client=client)
        assert r1.geschreven["pand_nieuw"] == 2 and r1.geschreven["koppeling_nieuw"] == 5
        assert _tel(administratie_id) == (2, 5)
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            kerk = s.scalars(select(Pand).where(Pand.code == "kerkstraat-44")).one()
            assert (kerk.herkomst, kerk.status) == ("afgeleid", "voorstel")
            assert kerk.notaris_dossiernummers == ["2025.058870.01"]
            koppelingen = s.scalars(select(PandBoeking).where(PandBoeking.pand_id == kerk.id)).all()
            assert all(k.herkomst == "voorstel" and k.bevestigd_op is None for k in koppelingen)
            aankoop = next(k for k in koppelingen if k.rlz_document_id == uuid.UUID(AANKOOP_ID))
            assert (aankoop.soort, aankoop.zekerheid, aankoop.bedrag) == ("aankoop", "hoog", Decimal("185000.00"))
            assert aankoop.bron_sleutel == f"rlz:{AANKOOP_ID}" and aankoop.rlz_collectie == "ManualJournals"
            audits = s.scalars(select(AuditEvent).where(AuditEvent.tabel.in_(["pand", "pand_boeking"]))).all()
            assert len(audits) == 7 and {a.actie for a in audits} == {
                "pand_voorstel_aangemaakt",
                "pand_boeking_voorstel_aangemaakt",
            }

        r2 = service.leid_af(
            administratie_id, dry_run=False, client=NepClient(_vgg(), uploads={AANKOOP_ID: [{"id": "u1"}]})
        )
        assert r2.geschreven["pand_nieuw"] == 0 and r2.geschreven["koppeling_nieuw"] == 0
        assert r2.geschreven["pand_ongewijzigd"] == 2 and r2.geschreven["koppeling_ongewijzigd"] == 5
        assert _tel(administratie_id) == (2, 5)

    def test_nieuwe_informatie_werkt_voorstel_bij_met_audit(self, administratie_id: uuid.UUID) -> None:
        data = _vgg()
        service.leid_af(
            administratie_id, dry_run=False, client=NepClient(data)
        )  # Jan Collongstraat: geen bijlage → midden
        r2 = service.leid_af(administratie_id, dry_run=False, client=NepClient(data, uploads={JAN_ID: [{"id": "u1"}]}))
        assert r2.geschreven["koppeling_bijgewerkt"] == 1 and r2.geschreven["koppeling_nieuw"] == 0
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            k = s.scalars(select(PandBoeking).where(PandBoeking.rlz_document_id == uuid.UUID(JAN_ID))).one()
            assert k.zekerheid == "hoog"
            audit = s.scalars(select(AuditEvent).where(AuditEvent.actie == "pand_boeking_voorstel_bijgewerkt")).one()
            assert audit.oude_waarde["zekerheid"] == "midden" and audit.nieuwe_waarde["zekerheid"] == "hoog"

    def test_mens_wint(self, administratie_id: uuid.UUID) -> None:
        service.leid_af(administratie_id, dry_run=False, client=NepClient(_vgg()))
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            kerk = s.scalars(select(Pand).where(Pand.code == "kerkstraat-44")).one()
            kerk.status, kerk.herkomst, kerk.adres = "bevestigd", "mens", "Kerkstraat 44 (door mens)"
            k = s.scalars(select(PandBoeking).where(PandBoeking.rlz_document_id == uuid.UUID(KEURING_ID))).one()
            k.herkomst, k.zekerheid, k.soort = "mens", "hoog", "overhead"
        r = service.leid_af(
            administratie_id, dry_run=False, client=NepClient(_vgg(), uploads={AANKOOP_ID: [{"id": "u1"}]})
        )
        assert r.geschreven["pand_beschermd"] == 1
        assert r.geschreven["koppeling_beschermd"] == 1
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            kerk = s.scalars(select(Pand).where(Pand.code == "kerkstraat-44")).one()
            assert (kerk.status, kerk.adres) == ("bevestigd", "Kerkstraat 44 (door mens)")
            k = s.scalars(select(PandBoeking).where(PandBoeking.rlz_document_id == uuid.UUID(KEURING_ID))).one()
            assert (k.herkomst, k.soort) == ("mens", "overhead")
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_vgg()))
        assert (
            next(p for p in rapport.panden if p.code == "kerkstraat-44").db_status
            == "dry-run: mens_beschermd (niet overschreven)"
        )

    def test_dry_run_na_schrijf_ziet_bestaand_voorstel(self, administratie_id: uuid.UUID) -> None:
        service.leid_af(administratie_id, dry_run=False, client=NepClient(_vgg()))
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_vgg()))
        assert all(p.db_status == "dry-run: bestaand voorstel, zou bijgewerkt worden" for p in rapport.panden)
        assert _tel(administratie_id) == (2, 5)
