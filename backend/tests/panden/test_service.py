# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok D2 (bundel 10-09) + run 2 VGG blok 3 (12-09): `service.leid_af` met een dict-client — voorstellen in de DB,
idempotent, dry-run schrijft niets, mens wint, Overhead-project alleen gerapporteerd, 403 op één collectie = zichtbare
fout; run 2: knip-reparatie via `ontknip`, clusters i.p.v. varianten, 31-12 = balans, Ouwerkerk-ontvangst via
PaymentTransactions = verkoop, pandenlijst-binding (CSV) + meerduidig, `pand_per_document`, dossier-guards."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.panden import service
from app.panden.cli_cmd import register_panden
from app.panden.models import Pand, PandBoeking
from app.panden.pandenlijst import CsvPandenlijst
from app.rlz import lezen
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.panden.test_afleiding import rlz_vorm

NOTARIS = {"id": str(uuid.uuid4()), "Name": "Ouwerkerk Notariaat B.V."}
HOMEKEUR = {"id": str(uuid.uuid4()), "Name": "Homekeur B.V."}
AKN = {"id": str(uuid.uuid4()), "Name": "Administratiekantoor Nijenhuis C.V."}
CONSTEN = {"id": str(uuid.uuid4()), "Name": "Consten Vastgoed B.V."}
SAASIT = {"id": str(uuid.uuid4()), "Name": "SaaSIT B.V."}


def _id(boekstuk: str) -> str:
    """Deterministisch RLZ-id per boekstuk — een herdraai van `_vgg()` levert dezelfde documenten."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-vgg-{boekstuk}"))


def _doc(
    boekstuk: str,
    tekst: str | None,
    *,
    datum: str,
    bedrag: float,
    entity: dict | None = None,
    status: int = 3,
    rlz_id: str | None = None,
    reference: str | None = None,
) -> dict:
    """RLZ-rij; `tekst` gaat als Description in de RLZ-OPSLAGVORM (32-tekens-knip met `\\n`), `reference` letterlijk."""
    return {
        "id": rlz_id or _id(boekstuk),
        "ReceiptNumber": boekstuk,
        "Reference": reference,
        "Description": rlz_vorm(tekst) if tekst else None,
        "Date": f"{datum}T00:00:00",
        "BookDate": f"{datum}T00:00:00",
        "BaseInvoiceAmount": bedrag,
        "Entity": entity,
        "Status": status,
    }


def _bank(transactie: str, reference: str | None, *, datum: str, bedrag: float, naam: str | None, nr: int) -> dict:
    return {
        "id": _id(f"pt-{transactie}-{nr}"),
        "TransactionId": transactie,
        "Reference": rlz_vorm(reference) if reference else None,
        "Name": naam,
        "BookDate": f"{datum}T00:00:00",
        "Amount": bedrag,
        "OpenAmount": bedrag,
        "IsComplete": False,
    }


class NepClient:
    def __init__(
        self,
        collecties: dict[str, list[dict]],
        *,
        uploads: dict[str, list] | None = None,
        fouten: dict[str, RlzApiError] | None = None,
        regels: dict[str, list[dict]] | None = None,
    ) -> None:
        self.collecties = collecties
        self.uploads = uploads or {}
        self.fouten = fouten or {}
        self.regels = regels or {}  # blok 7c: `PurchaseInvoices/{id}/Lines` → regels mét Account.AccountNumber
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
        if path.endswith("/Lines"):
            _, doc_id, _ = path.split("/")
            return {"value": self.regels.get(doc_id, [])}
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


GELEZEN_LEEG = {"Receipts": 0, "PaymentTransactions": 0}


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
        assert rapport.gelezen == {"ManualJournals": 3, "SalesInvoices": 1, "PurchaseInvoices": 3, **GELEZEN_LEEG}
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
        assert "geen lijst meegegeven (clusteren op adres)" in md

    def test_dossier_zonder_adres_haakt_aan_bij_pand_met_dat_dossier(self, administratie_id: uuid.UUID) -> None:
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_vgg()))
        kerk = next(p for p in rapport.panden if p.code == "kerkstraat-44")
        assert any(k.boeking.rlz_id == uuid.UUID(DOSSIER_ID) and k.zekerheid == "laag" for k in kerk.koppelingen)

    def test_alleen_dossier_met_dossierwoord_wordt_dossier_pand(self, administratie_id: uuid.UUID) -> None:
        data = {
            "ManualJournals": [
                _doc("RLZ-06-1", "Notarisafrekening dossier 2026.014305.01", datum="2026-07-15", bedrag=1.0),
                # zonder het woord "dossier" (run 2): geen pand, wél zichtbaar
                _doc("RLZ-06-2", "Notarisafrekening 2026.014306.01", datum="2026-07-16", bedrag=1.0),
                # onvolledig dossiernummer (run 2): nooit een sleutel
                _doc("RLZ-06-3", "Overdracht Utrecht, ons dossier: 2025.079", datum="2026-07-17", bedrag=1.0),
            ],
            "SalesInvoices": [],
            "PurchaseInvoices": [],
        }
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(data))
        assert [p.code for p in rapport.panden] == ["dossier-2026-014305-01"]
        assert rapport.panden[0].adres == "dossier 2026.014305.01 (adres onbekend)"
        assert len(rapport.dossier_zonder_pand) == 2
        assert any("geen dossier-woord" in r for r in rapport.dossier_zonder_pand)
        assert any("onvolledig dossiernummer" in r for r in rapport.dossier_zonder_pand)

    def test_403_op_een_collectie_is_zichtbare_fout(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(_vgg(), fouten={"SalesInvoices": RlzApiError(403, "GET", "SalesInvoices", "Forbidden")})
        rapport = service.leid_af(administratie_id, dry_run=True, client=client)
        assert rapport.fouten == ["SalesInvoices: 403 — collectie niet gelezen (Forbidden)"]
        assert "SalesInvoices" not in rapport.gelezen and len(rapport.panden) == 2

    def test_receipts_en_bankmutaties_zijn_optioneel(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(
            _vgg(),
            fouten={
                "Receipts": RlzApiError(404, "GET", "Receipts", "Not Found"),
                "PaymentTransactions": RlzApiError(403, "GET", "PaymentTransactions", "Forbidden"),
            },
        )
        rapport = service.leid_af(administratie_id, dry_run=True, client=client)
        assert rapport.fouten == []
        assert any(o.startswith("Receipts: 404") for o in rapport.overgeslagen)
        assert any(o.startswith("PaymentTransactions: 403") for o in rapport.overgeslagen)
        assert len(rapport.panden) == 2

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

    def test_nieuwe_soorten_passen_in_de_check_constraint(self, administratie_id: uuid.UUID) -> None:
        data = {
            "ManualJournals": [
                _doc("RLZ-06-00000076", "Aanbetaling Heidebeemd 3 Weert", datum="2025-09-02", bedrag=-20000.0),
                _doc("RLZ-25-00000205", "Vaste lasten Molenstraat 13, Brunssum", datum="2025-10-30", bedrag=500.0),
                _doc("RLZ-06-00000111", "Chevremontstraat 68 Kerkrade", datum="2025-12-31", bedrag=290000.0),
            ],
            "SalesInvoices": [],
            "PurchaseInvoices": [],
        }
        r = service.leid_af(administratie_id, dry_run=False, client=NepClient(data))
        assert r.geschreven["koppeling_nieuw"] == 3
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            soorten = set(s.scalars(select(PandBoeking.soort)).all())
        assert soorten == {"aanbetaling", "vaste_lasten", "balans"}

    def test_variant_code_vindt_bestaand_pand_terug(self, administratie_id: uuid.UUID) -> None:
        run1 = {
            "ManualJournals": [],
            "SalesInvoices": [],
            "PurchaseInvoices": [_doc("RLZ-04-1", "Kleiweg 667 Rotterdam", datum="2026-01-05", bedrag=100.0)],
        }
        r1 = service.leid_af(administratie_id, dry_run=False, client=NepClient(run1))
        assert r1.geschreven["pand_nieuw"] == 1 and [p.code for p in r1.panden] == ["kleiweg-667"]
        run2 = {
            **run1,
            "PurchaseInvoices": run1["PurchaseInvoices"]
            + [
                _doc("RLZ-04-2", "Overschiese Kleiweg 667 Rotterdam", datum="2026-02-05", bedrag=100.0),
                _doc("RLZ-04-3", "Overschiese Kleiweg 667", datum="2026-03-05", bedrag=100.0),
            ],
        }
        r2 = service.leid_af(administratie_id, dry_run=False, client=NepClient(run2))
        # representant is nu "Overschiese Kleiweg" maar de bestaande rij (kleiweg-667) wint: geen tweede pand
        assert [p.code for p in r2.panden] == ["overschiese-kleiweg-667"]
        assert r2.geschreven["pand_nieuw"] == 0 and r2.geschreven["pand_bijgewerkt"] == 1
        assert r2.geschreven["koppeling_nieuw"] == 2 and _tel(administratie_id) == (1, 3)
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            pand = s.scalars(select(Pand)).one()
            assert pand.code == "kleiweg-667" and pand.adres == "Overschiese Kleiweg 667"


# ---- run 2 VGG ------------------------------------------------------------------------------------

OUWERKERK_PT = "Ouwerkerk Notariaat"


def _nameting() -> dict[str, list[dict]]:
    """Een 214-achtige input: letterlijke omschrijvingen uit de nameting 11-09 (in RLZ-vorm), varianten, 31-12-
    memorialen, aanbetalingen, vaste lasten, factuurnummer-ruis, Ouwerkerk-ontvangsten als tekstloze RLZ-09-hulzen +
    PaymentTransactions."""
    return {
        "ManualJournals": [
            # Azielaan 334: aanbetaling (sept) → vaste lasten → overdracht mét notaris-PDF (jan) → 31-12-balans
            _doc("RLZ-06-00000040", "Aanbetaling Azielaan 334 Utrecht", datum="2025-09-02", bedrag=-10000.0),
            _doc(
                "RLZ-06-00000041",
                "Aanbetaling volgens afspraak: Azielaan 334 te Utrecht",
                datum="2025-09-30",
                bedrag=-10000.0,
            ),
            _doc("RLZ-06-00000112", "Azielaan 334 Utrecht", datum="2025-12-31", bedrag=250000.0),
            _doc(
                "RLZ-06-00000150",
                "Overdracht Azielaan 334 te Utrecht, ons dossier: 2025.078804.01",
                datum="2026-01-12",
                bedrag=250000.0,
                rlz_id=_id("overdracht-azielaan"),
            ),
            # Chevremontstraat 68: knip-varianten (pre-ontknip "C hevremontstraat") + 31-12
            _doc("RLZ-06-00000111", "Chevremontstraat 68 Kerkrade", datum="2025-12-31", bedrag=290000.0),
            # Bleijeheiderstraat 123B — twee spellingen + PaymentReference-restant "Bleijeheiderstraat 1" als Reference
            _doc(
                "RLZ-06-00000225",
                "Bleijeheiderstraat 123B Kerkrade",
                datum="2026-07-15",
                bedrag=190000.0,
                reference="Bleijeheiderstraat 1",
            ),
            _doc(
                "RLZ-06-00000226",
                "betreft: Bleijerheiderstraat 123B te Kerkrade, ons dossier:2025.079527.01",
                datum="2026-06-16",
                bedrag=190000.0,
                rlz_id=_id("overdracht-bleijer"),
            ),
            _doc(
                "RLZ-06-00000250",
                "Aanbetaling volgens afspraak: Bleijeheiderstraat 123B, te Kerkrade",
                datum="2025-10-30",
                bedrag=-10000.0,
            ),
            # herhaalde straatnaam (Reference 20 tekens + Description)
            _doc(
                "RLZ-06-00000130",
                "Burgemeester Norbruislaan 422",
                datum="2025-12-31",
                bedrag=300000.0,
                reference="Burgemeester Norbrui",
            ),
            _doc(
                "RLZ-06-00000131",
                "Gustaaf Gelderstraat 60",
                datum="2025-12-31",
                bedrag=200000.0,
                reference="Gustaaf Gelderstraat",
            ),
            # aanbetaling Heidebeemd (verkoop volgt uit een notaris-ontvangst — hieronder als PaymentTransaction)
            _doc("RLZ-06-00000076", "Aanbetaling Heidebeemd 3 Weert", datum="2025-09-02", bedrag=-20000.0),
            # bankreeksen in ManualJournals
            _doc("RLZ-25-00000568", "Vaste lasten: Dwartsweg 22, Zeist maand mei", datum="2026-05-04", bedrag=230.99),
            _doc("RLZ-25-00000205", "Vaste lasten Molenstraat 13, Brunssum", datum="2025-10-30", bedrag=500.0),
            _doc("RLZ-28-00000090", "Belasting verkoop Verschoorstraat 70-2", datum="2026-04-01", bedrag=-2100.0),
            _doc("RLZ-28-00000061", "rc", datum="2025-11-07", bedrag=135000.0),
            _doc("RLZ-46-00000166", "Lening", datum="2026-02-20", bedrag=70000.0),
            # tekstloze RLZ-09-hulzen van de Ouwerkerk-ontvangsten (Receipts-kopieën hieronder, zelfde id)
            _doc("RLZ-09-00001056", None, datum="2026-08-03", bedrag=21388.37, status=1),
            _doc("RLZ-09-00001142", None, datum="2026-09-03", bedrag=139834.74, status=1),
        ],
        "SalesInvoices": [
            _doc("RLZ-01-00000077", "Haringvlietstraat 44 Dordrecht Rente", datum="2026-02-25", bedrag=770.83),
        ],
        "PurchaseInvoices": [
            _doc(
                "RLZ-04-00000062",
                "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum",
                datum="2025-08-22",
                bedrag=65000.0,
                status=1,
            ),
            _doc("RLZ-04-00000162", "Molenstraat 13", datum="2025-10-03", bedrag=749.99, entity=CONSTEN),
            _doc("RLZ-04-00000163", "Dautzenbergstraat 18F Heerlen", datum="2025-10-03", bedrag=749.99, entity=CONSTEN),
            _doc("RLZ-04-00000300", "C hevremontstraat 68 Kerkrade", datum="2025-11-03", bedrag=120.0),
            _doc("RLZ-04-00000301", "Chevr emontstraat 68 Kerkrade", datum="2025-11-04", bedrag=120.0),
            _doc("RLZ-04-00000797", "Kouvenderstraat34b Hoensbroek", datum="2026-07-27", bedrag=1595.0),
            _doc("RLZ-04-00000798", "F2026-0083 Lidwinahof 47", datum="2026-07-28", bedrag=250.0),
            _doc("RLZ-04-00000799", "HL Arnhem Papaverstraat 44", datum="2026-07-29", bedrag=250.0),
            _doc(
                "RLZ-04-00000800",
                "Vaste lasten volgens afspraak: Papaverstraat 44, Utrecht",
                datum="2026-08-04",
                bedrag=1000.0,
            ),
            _doc("RLZ-04-00000801", "Verhuizing Rotterdam Tapuitstraat 52A", datum="2026-08-05", bedrag=800.0),
            _doc("RLZ-04-00000802", "Overschiese Kleiweg 667 Rotterdam", datum="2026-08-06", bedrag=300.0),
            _doc("RLZ-04-00000803", "Kleiweg 667", datum="2026-08-07", bedrag=300.0),
            # ruis: factuurnummers en een Verhagen-dossier — nooit een pand
            _doc("RLZ-04-00000837", "2026-0050", datum="2026-08-11", bedrag=261.36, entity=SAASIT),
            _doc("RLZ-17-00000464", "Dossiernummer: 118261", datum="2026-03-09", bedrag=1500.0, status=1),
            _doc("RLZ-04-00000900", "2026-00084", datum="2026-08-12", bedrag=10.0),
            _doc("RLZ-04-00000901", "2025-02494", datum="2026-08-12", bedrag=10.0),
            _doc("RLZ-04-00000902", "2026-021018", datum="2026-08-12", bedrag=10.0),
            _doc("RLZ-04-00000576", "Maandelijkse aanbetaling: maand mei 2026", datum="2026-05-04", bedrag=1324.26),
        ],
        "Receipts": [
            # dezelfde hulzen als in ManualJournals (zelfde id → één keer geteld) + een RLZ-04-kopie
            _doc("RLZ-09-00001056", None, datum="2026-08-03", bedrag=21388.37, status=1),
            _doc("RLZ-04-00000797", "Kouvenderstraat34b Hoensbroek", datum="2026-07-27", bedrag=1595.0),
        ],
        "PaymentTransactions": [
            _bank(
                "00112",
                "Overdracht hogevecht 123 te Amsterdam, ons dossier: 2026.080369.01",
                datum="2026-08-03",
                bedrag=21388.37,
                naam=OUWERKERK_PT,
                nr=1,
            ),
            _bank(
                "00112",
                "Overdracht van de Spiegelstraat 42 te Bergen op Zoom, ons dossier: 2026.080912.01",
                datum="2026-08-04",
                bedrag=89023.39,
                naam=OUWERKERK_PT,
                nr=2,
            ),
            _bank(
                "00112",
                "Overdracht Apollolaan 644 te Leiden, ons dossier: 2026.081052.01",
                datum="2026-08-05",
                bedrag=38423.39,
                naam=OUWERKERK_PT,
                nr=3,
            ),
            _bank(
                "00112",
                "Overdracht Duifhuis 11 te Berlicum, ons dossier: 2026.080906.01",
                datum="2026-08-06",
                bedrag=56153.28,
                naam=OUWERKERK_PT,
                nr=4,
            ),
            _bank(
                "00112",
                "Overdracht Sportlaan 180 te Purmerend, ons dossier: 2026.080301.01",
                datum="2026-08-06",
                bedrag=30831.89,
                naam=OUWERKERK_PT,
                nr=5,
            ),
            _bank(
                "00112",
                "Overdracht Knopkruid 45, ons dossier 2025.079458.01",
                datum="2026-09-03",
                bedrag=139834.74,
                naam=OUWERKERK_PT,
                nr=6,
            ),
            # verkoop Heidebeemd 3 uit een notaris-ontvangst
            _bank(
                "00112",
                "Overdracht Heidebeemd 3 te Weert, ons dossier: 2026.081100.01",
                datum="2026-09-05",
                bedrag=201500.0,
                naam=OUWERKERK_PT,
                nr=7,
            ),
            # bankregel die een bank-geïmporteerd document (RLZ-04-00000062, 65.000, 22-08) verdubbelt → overgeslagen
            _bank(
                "00112",
                "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum",
                datum="2025-08-22",
                bedrag=-65000.0,
                naam="J.B.",
                nr=8,
            ),
            # aanbetaling op een pand dat verder alleen op de bank leeft
            _bank(
                "00112",
                "Aanbetaling volgens afspraak: Wadden 66, Zwijndrecht",
                datum="2026-08-31",
                bedrag=-20000.0,
                naam="I.B.",
                nr=9,
            ),
            # ruis
            _bank("01018", "ADWORDS:5600916770:GG104IN2RL", datum="2026-09-09", bedrag=-500.0, naam="G.I.L.", nr=10),
        ],
    }


class TestRun2:
    def test_clusters_soorten_en_datums(self, administratie_id: uuid.UUID) -> None:
        client = NepClient(
            _nameting(), uploads={_id("overdracht-azielaan"): [{"id": "u1"}], _id("overdracht-bleijer"): [{"id": "u2"}]}
        )
        rapport = service.leid_af(administratie_id, dry_run=True, client=client)
        codes = {p.code: p for p in rapport.panden}
        assert set(codes) == {
            "azielaan-334",
            "chevremontstraat-68",
            "bleijeheiderstraat-123-b",
            "burgemeester-norbruislaan-422",
            "gustaaf-gelderstraat-60",
            "heidebeemd-3",
            "dwartsweg-22",
            "molenstraat-13",
            "verschoorstraat-70-2",
            "haringvlietstraat-44",
            "oosterdiepswal-7",
            "dautzenbergstraat-18-f",
            "kouvenderstraat-34-b",
            "lidwinahof-47",
            "papaverstraat-44",
            "tapuitstraat-52-a",
            "overschiese-kleiweg-667",
            "hogevecht-123",
            "van-de-spiegelstraat-42",
            "apollolaan-644",
            "duifhuis-11",
            "sportlaan-180",
            "knopkruid-45",
            "wadden-66",
        }, sorted(codes)
        # géén "dossier 2026-0050"-achtige panden, géén "Dossiernummer: 118261"
        assert not any(c.startswith("dossier-") for c in codes)
        # Azielaan: aanbetaling ×2, balans (31-12), aankoop = de overdracht mét PDF — aankoopdatum ≠ 31-12
        az = codes["azielaan-334"]
        assert az.tel() == {"aanbetaling": {"hoog": 2}, "balans": {"midden": 1}, "aankoop": {"hoog": 1}}
        assert az.aankoopdatum == date(2026, 1, 12) and az.dossiers == ["2025.078804.01"] and az.plaats == "Utrecht"
        # Chevremontstraat: drie spelvarianten = één pand, 31-12 = balans, geen aankoopdatum
        ch = codes["chevremontstraat-68"]
        assert ch.adres == "Chevremontstraat 68" and ch.aankoopdatum is None
        assert ch.tel() == {"balans": {"midden": 1}, "kosten": {"midden": 2}}
        assert set(ch.varianten) == {"Chevremontstraat", "C hevremontstraat", "Chevr emontstraat"}
        assert any("varianten:" in k.reden for k in ch.koppelingen)
        # Bleijeheiderstraat: twee spellingen + de Reference-restant "Bleijeheiderstraat 1" → één pand
        bl = codes["bleijeheiderstraat-123-b"]
        assert (
            set(bl.varianten) == {"Bleijeheiderstraat", "Bleijerheiderstraat"} and "bleijeheiderstraat-1" not in codes
        )
        assert bl.aankoopdatum == date(2026, 6, 16) and bl.dossiers == ["2025.079527.01"]
        # herhaalde straatnaam gevouwen
        assert codes["burgemeester-norbruislaan-422"].adres == "Burgemeester Norbruislaan 422"
        assert codes["gustaaf-gelderstraat-60"].adres == "Gustaaf Gelderstraat 60"
        # 31-12 is nooit een aankoopdatum
        assert all(p.aankoopdatum != date(2025, 12, 31) for p in rapport.panden)
        # verkoop-signalen: Verschoorstraat (RLZ-28, midden), Heidebeemd + de zes Ouwerkerk-ontvangsten (hoog)
        assert codes["verschoorstraat-70-2"].tel() == {"verkoop": {"midden": 1}}
        assert codes["heidebeemd-3"].tel() == {"aanbetaling": {"hoog": 1}, "verkoop": {"hoog": 1}}
        assert codes["heidebeemd-3"].verkoopdatum == date(2026, 9, 5)
        for code in (
            "hogevecht-123",
            "van-de-spiegelstraat-42",
            "apollolaan-644",
            "duifhuis-11",
            "sportlaan-180",
            "knopkruid-45",
        ):
            p = codes[code]
            assert p.tel() == {"verkoop": {"hoog": 1}}, code
            (k,) = p.koppelingen
            assert k.boeking.collectie == "PaymentTransactions" and p.verkoopdatum is not None
        # rente is geen verkoop; vaste lasten en aanbetalingen als eigen soort
        assert codes["haringvlietstraat-44"].tel() == {"kosten": {"hoog": 1}}
        assert codes["dwartsweg-22"].tel() == {"vaste_lasten": {"hoog": 1}}
        assert codes["molenstraat-13"].tel() == {"vaste_lasten": {"hoog": 1}, "kosten": {"midden": 1}}
        assert codes["oosterdiepswal-7"].tel() == {"aanbetaling": {"hoog": 1}}
        assert codes["wadden-66"].tel() == {"aanbetaling": {"hoog": 1}}
        assert codes["papaverstraat-44"].tel() == {"kosten": {"midden": 1}, "vaste_lasten": {"hoog": 1}}
        assert codes["overschiese-kleiweg-667"].tel() == {"kosten": {"midden": 2}}
        # tellers
        assert rapport.bankmutaties_gelezen == 10 and rapport.bankmutaties_gebruikt == 8
        assert rapport.bankmutaties_document_aanwezig == 1  # Oosterdiepswal-bankregel: document draagt de tekst al
        assert rapport.gelezen["Receipts"] == 2 and rapport.gelezen["ManualJournals"] == 18
        # aanbetaling: Azielaan ×2, Bleijeheider, Heidebeemd, Oosterdiepswal, Wadden · aankoop: 2 overdrachten + het
        # memoriaal "Bleijeheiderstraat 123B Kerkrade" (midden) · kosten: rente, Consten ×2, Chevremont ×2, Kouvender,
        # Lidwinahof, Papaver, Tapuit, Kleiweg ×2
        assert rapport.soorten == {
            "aanbetaling": 6,
            "aankoop": 3,
            "balans": 4,
            "kosten": 11,
            "vaste_lasten": 3,
            "verkoop": 8,
        }
        assert rapport.geen_signaal["PurchaseInvoices"] == 6 and rapport.geen_signaal["ManualJournals"] == 4
        md = service.als_markdown(rapport, administratie_naam="VGG")
        assert "Bankmutaties: 10 gelezen, 8 gebruikt, 1 overgeslagen" in md
        rij = (
            "| Chevremontstraat 68 | Kerkrade | — | — | — | balans: 0/1/0; kosten: 0/2/0 | "
            "C hevremontstraat, Chevr emontstraat | — |"
        )
        assert rij in md

    def test_pandenlijst_bindt_en_meldt_meerduidig(self, administratie_id: uuid.UUID, tmp_path: Path) -> None:
        csv = tmp_path / "panden.csv"
        csv.write_text(
            "adres;huisnummer;toevoeging;postcode;plaats;salesforce_id\n"
            "Chevremontstraat;68;;6461 XT;Kerkrade;a0X1\n"
            "Bleijerheiderstraat;123;B;;Kerkrade;a0X2\n"
            "Overschiese Kleiweg;667;;;Rotterdam;a0X3\n"
            "Papaverstraat;44;;;Utrecht;a0X4\n"
            "Papaverstraat;44;;;Arnhem;a0X5\n"  # tweede Papaverstraat 44 → meerduidig zonder plaats in de tekst
            "Sportlaan;180;;;Purmerend;a0X6\n",
            encoding="utf-8",
        )
        rapport = service.leid_af(
            administratie_id, dry_run=True, client=NepClient(_nameting()), pandenlijst_bron=CsvPandenlijst(csv)
        )
        codes = {p.code: p for p in rapport.panden}
        assert rapport.lijst_panden == 6
        assert codes["sf-a0x1"].adres == "Chevremontstraat 68" and codes["sf-a0x1"].salesforce_id == "a0X1"
        assert codes["sf-a0x1"].postcode == "6461XT" and codes["sf-a0x1"].lijst_gebonden
        assert codes["sf-a0x2"].adres == "Bleijerheiderstraat 123B"  # lijst-spelling wint
        assert "sf-a0x3" in codes and "overschiese-kleiweg-667" not in codes
        assert codes["sf-a0x6"].tel() == {"verkoop": {"hoog": 1}}
        # Papaverstraat 44: "HL Arnhem Papaverstraat 44" en "Papaverstraat 44, Utrecht" clusteren; het cluster heeft
        # plaats Utrecht (eerste gevulde) → eenduidig a0X4
        assert "sf-a0x4" in codes and "papaverstraat-44" not in codes
        assert rapport.lijst_meerduidig == []
        md = service.als_markdown(rapport)
        assert "Pandenlijst: 6 panden, 5 gebonden, 0 meerduidig" in md and "| sf a0X1 |" in md

    def test_pandenlijst_meerduidig_wordt_niet_gebonden(self, administratie_id: uuid.UUID, tmp_path: Path) -> None:
        csv = tmp_path / "panden.csv"
        csv.write_text(
            "adres,huisnummer,plaats,salesforce_id\nKleiweg,667,Rotterdam,a1\nKleiweg,667,Schiedam,a2\n",
            encoding="utf-8",
        )
        data = {
            "ManualJournals": [],
            "SalesInvoices": [],
            "PurchaseInvoices": [_doc("RLZ-04-1", "Kleiweg 667", datum="2026-01-05", bedrag=100.0)],
        }
        rapport = service.leid_af(
            administratie_id, dry_run=True, client=NepClient(data), pandenlijst_bron=CsvPandenlijst(csv)
        )
        assert [p.code for p in rapport.panden] == ["kleiweg-667"] and not rapport.panden[0].lijst_gebonden
        assert len(rapport.lijst_meerduidig) == 1 and "2 lijst-panden even goed" in rapport.lijst_meerduidig[0]
        assert "MEERDUIDIG (lijst) Kleiweg 667" in service.als_markdown(rapport)

    def test_pand_per_document(self, administratie_id: uuid.UUID) -> None:
        data = _nameting()
        service.leid_af(administratie_id, dry_run=False, client=NepClient(data))
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as s:
            k = s.scalars(select(PandBoeking).where(PandBoeking.rlz_boekstuknummer == "RLZ-04-00000162")).one()
            k.herkomst, k.soort, k.zekerheid = "mens", "overhead", "hoog"
        # (a) alleen DB
        uit = service.pand_per_document(administratie_id)
        mens = uit[uuid.UUID(_id("RLZ-04-00000162"))]
        assert (mens.herkomst, mens.soort, mens.pand_code, mens.adres) == (
            "mens",
            "overhead",
            "molenstraat-13",
            "Molenstraat 13",
        )
        pt = uit[uuid.UUID(_id("pt-00112-6"))]  # Knopkruid 45 via PaymentTransactions
        assert (pt.herkomst, pt.soort, pt.zekerheid, pt.pand_code) == ("voorstel", "verkoop", "hoog", "knopkruid-45")
        assert uuid.UUID(_id("RLZ-04-00000837")) not in uit  # "2026-0050" heeft geen pand
        # (b) aangevuld met de afleiding voor documenten zonder DB-rij
        rapport = service.AfleidingRapport(
            administratie_id=str(administratie_id), rlz_admin_id=None, dry_run=True, gegenereerd_op=""
        )
        nieuw = service.RlzBoeking(
            collectie="PurchaseInvoices",
            rlz_id=uuid.uuid4(),
            boekstuk="RLZ-04-9",
            datum=date(2026, 9, 10),
            bedrag=Decimal("120.00"),
            entity_naam=None,
            tekst="Chevremontstraat 68 Kerkrade",
        )
        boekingen = service.lees_boekingen(NepClient(data), rapport, max_bijlage_checks=0) + [nieuw]
        uit2 = service.pand_per_document(administratie_id, boekingen=boekingen)
        assert uit2[nieuw.rlz_id] == service.PandToewijzing(
            pand_code="chevremontstraat-68",
            adres="Chevremontstraat 68",
            soort="kosten",
            zekerheid="midden",
            herkomst="afgeleid",
        )
        assert uit2[uuid.UUID(_id("RLZ-04-00000162"))].herkomst == "mens"  # DB blijft leidend
        assert len(uit2) == len(uit) + 1

    def test_tekst_uit_rij_ontknipt_en_ontdubbelt(self) -> None:
        assert service.tekst_uit_rij({"Reference": "Aanbetaling volgens afspraak: Oo\nsterdiepswal 7 te Kollum"}) == (
            "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum"
        )
        rij = {"Reference": "Burgemeester Norbrui", "Description": "Burgemeester Norbruislaan 422", "Header": None}
        assert service.tekst_uit_rij(rij) == "Burgemeester Norbruislaan 422"
        assert service.tekst_uit_rij(
            {"Reference": "2623009", "Description": "Bornholmstraat 49 Almere", "Header": "2623009"}
        ) == ("2623009 Bornholmstraat 49 Almere")
        assert service.tekst_uit_rij({"Reference": None, "Description": 12}) == ""


def _adres_signalen_data() -> dict[str, list[dict]]:
    """Blok 7b punt 7 (13-09): de straatnaam-varianten en huisnummer-typo's uit de productienameting 13-09 — de
    clusterdrempel voegt ze NIET samen; het rapport moet ze als kandidaat resp. signaal noemen."""
    return {
        "ManualJournals": [],
        "SalesInvoices": [],
        "PurchaseInvoices": [
            # B: Rooseveltstraat 13 / Rooseveltweg 13, beide Hulst → één cluster-kandidaat, twee panden
            _doc("RLZ-04-00000901", "Aanbetaling Rooseveltstraat 13, Hulst", datum="2026-02-02", bedrag=2500.0),
            _doc(
                "RLZ-04-00000902",
                "Extra aanbetaling volgens afspraak: Rooseveltweg 13, Hulst",
                datum="2026-03-02",
                bedrag=2500.0,
            ),
            # B: Groningenstraat 203 (plaats onbekend) / Groningerstraatweg 203 Leeuwarden → kandidaat (plaats bij één
            # onbekend)
            _doc("RLZ-04-00000903", "Groningenstraat 203", datum="2026-04-01", bedrag=120.0, entity=CONSTEN),
            _doc(
                "RLZ-04-00000904",
                "Vaste lasten volgens afspraak: Groningerstraatweg 203, Leeuwarden",
                datum="2026-04-02",
                bedrag=330.1,
            ),
            # C: Kouvenderstraat 34b / 43b Hoensbroek → huisnummer-signaal
            _doc("RLZ-04-00000905", "Kouvenderstraat34b Hoensbroek", datum="2026-07-27", bedrag=1595.0),
            _doc("RLZ-04-00000906", "Kouvenderstraat 43b Hoensbroek", datum="2026-07-28", bedrag=150.0),
            # C: Donkerslootstraat 101A / 105B Rotterdam
            _doc("RLZ-04-00000907", "Aankoop Donkerslootstraat 101A Rotterdam", datum="2026-02-18", bedrag=100.0),
            _doc("RLZ-04-00000908", "Donkerslootstraat 105B Rotterdam", datum="2026-02-19", bedrag=100.0),
            # geen regel: twee gewone, ongelijke panden
            _doc("RLZ-04-00000909", "Aanbetaling Azielaan 334 Utrecht", datum="2025-09-02", bedrag=10000.0),
            _doc("RLZ-04-00000910", "Aanbetaling Barendrechtstraat 30, Tilburg", datum="2025-09-03", bedrag=10000.0),
            # geen regel: zelfde huisnummer + lijkende straat maar ANDERE plaats
            _doc("RLZ-04-00000911", "Kerkstraat 44 Ede", datum="2026-05-01", bedrag=100.0),
            _doc("RLZ-04-00000912", "Kerklaan 44 Zeist", datum="2026-05-02", bedrag=100.0),
        ],
    }


class TestAdresSignalen:
    def test_straat_lijkt_drempel(self) -> None:
        assert service.straat_lijkt("Rooseveltstraat", "Rooseveltweg")  # kern "roosevelt" gelijk
        assert service.straat_lijkt("Groningenstraat", "Groningerstraatweg")  # voorvoegsel "groning" ≥ 6
        assert service.straat_lijkt("Kerkstraat", "Kerklaan")  # kern "kerk" gelijk ná suffix-strip
        assert not service.straat_lijkt("Azielaan", "Barendrechtstraat")
        assert not service.straat_lijkt("Kerkstraat", "Kerkstraat")  # identiek = zelfde cluster, geen kandidaat
        assert not service.straat_lijkt("", "Kerkstraat")
        assert service._straat_kern("Groningerstraatweg") == "groninger"
        assert service._straat_kern("Rooseveltstraat") == "roosevelt" and service._straat_kern("Weg") == "weg"

    def test_cluster_kandidaten_en_huisnummer_signalen_in_rapport(self, administratie_id: uuid.UUID) -> None:
        rapport = service.leid_af(administratie_id, dry_run=True, client=NepClient(_adres_signalen_data()))
        codes = {p.code for p in rapport.panden}
        # de kandidaten blijven TWEE panden — nooit automatisch samengevoegd
        assert {"rooseveltstraat-13", "rooseveltweg-13", "groningenstraat-203", "groningerstraatweg-203"} <= codes
        assert {
            "kouvenderstraat-34-b",
            "kouvenderstraat-43-b",
            "donkerslootstraat-101-a",
            "donkerslootstraat-105-b",
        } <= codes
        assert rapport.cluster_kandidaten == [
            "Groningenstraat 203 (plaats onbekend) ↔ Groningerstraatweg 203 (Leeuwarden) — "
            "zelfde huisnummer (plaats bij één onbekend), straat lijkt; mens beslist",
            "Rooseveltstraat 13 (Hulst) ↔ Rooseveltweg 13 (Hulst) — zelfde huisnummer + plaats, straat lijkt; "
            "mens beslist",
        ]
        assert rapport.huisnummer_signalen == [
            "Donkerslootstraat 101A (Rotterdam) ↔ Donkerslootstraat 105B (Rotterdam) — "
            "zelfde straat + plaats, ander huisnummer; alleen signaal",
            "Kouvenderstraat 34b (Hoensbroek) ↔ Kouvenderstraat 43b (Hoensbroek) — "
            "zelfde straat + plaats, ander huisnummer; alleen signaal",
        ]
        # Azielaan/Barendrechtstraat en Kerkstraat 44 Ede/Kerklaan 44 Zeist (andere plaats) leveren geen regel
        alles = "\n".join(rapport.cluster_kandidaten + rapport.huisnummer_signalen)
        assert "Azielaan" not in alles and "Barendrechtstraat" not in alles and "Kerk" not in alles
        md = service.als_markdown(rapport, administratie_naam="VGG")
        assert "Cluster-kandidaten (mens beslist) — 2" in md
        assert "Huisnummer-varianten (alleen signaal, geen actie) — 2" in md
        assert "- Rooseveltstraat 13 (Hulst) ↔ Rooseveltweg 13 (Hulst)" in md
        d = rapport.als_dict()
        assert d["cluster_kandidaten"] == rapport.cluster_kandidaten
        assert d["huisnummer_signalen"] == rapport.huisnummer_signalen
        assert d["tellers"]["cluster_kandidaten"] == 2 and d["tellers"]["huisnummer_signalen"] == 2

    def test_zonder_rapport_geen_berekening_en_lege_secties(self, administratie_id: uuid.UUID) -> None:
        # pand_per_document (contract B → E) bouwt zonder rapport — geen signalen nodig, geen fout
        rapport = service.AfleidingRapport(
            administratie_id=str(administratie_id), rlz_admin_id=None, dry_run=True, gegenereerd_op=""
        )
        boekingen = service.lees_boekingen(NepClient(_adres_signalen_data()), rapport, max_bijlage_checks=0)
        assert rapport.cluster_kandidaten == [] and rapport.huisnummer_signalen == []
        panden = service.bouw_voorstellen(boekingen, None)
        assert "rooseveltstraat-13" in panden and "rooseveltweg-13" in panden
        md = service.als_markdown(rapport)
        assert "Cluster-kandidaten (mens beslist) — 0" in md
        assert "Huisnummer-varianten (alleen signaal, geen actie) — 0" in md

    def test_aan_zelfde_lijstpand_gebonden_clusters_zijn_geen_kandidaat(self, tmp_path: Path) -> None:
        from app.panden.afleiding import AdresVoorstel
        from app.panden.pandenlijst import cluster_adressen

        clusters = cluster_adressen(
            [
                AdresVoorstel("Rooseveltstraat", "13", plaats="Hulst"),
                AdresVoorstel("Rooseveltweg", "13", plaats="Hulst"),
            ]
        )
        assert len(clusters) == 2
        kandidaten, signalen = service.adres_signalen(clusters, {0: "sf-a001", 1: "sf-a001"})
        assert kandidaten == [] and signalen == []
        kandidaten, _ = service.adres_signalen(clusters)
        assert len(kandidaten) == 1


class TestCli:
    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        register_panden(parser.add_subparsers(dest="commando"))
        return parser

    def test_vlaggen(self) -> None:
        args = self._parser().parse_args(
            [
                "pandenregister-afleiden",
                "--administratie",
                "Vastgoedgroep",
                "--pandenlijst",
                "/tmp/p.csv",
                "--zonder-bankmutaties",
            ]
        )
        assert args.pandenlijst == "/tmp/p.csv" and args.zonder_bankmutaties is True and args.schrijf is False
        default = self._parser().parse_args(["pandenregister-afleiden", "--administratie", "x"])
        assert (
            default.pandenlijst is None and default.zonder_bankmutaties is False and default.max_bijlage_checks == 200
        )

    def test_onleesbare_pandenlijst_is_exit_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # noqa: ANN001
        from app.migratie import cli_cmd as migratie_cli
        from app.panden.cli_cmd import run_panden

        monkeypatch.setattr(migratie_cli, "zoek_administratie", lambda _q: (uuid.uuid4(), "VGG", "rlz"))
        csv = tmp_path / "leeg.csv"
        csv.write_text("naam;plaats\n", encoding="utf-8")
        args = self._parser().parse_args(
            ["pandenregister-afleiden", "--administratie", "VGG", "--pandenlijst", str(csv)]
        )
        assert run_panden(args) == 2
        assert "pandenlijst niet leesbaar" in capsys.readouterr().err


class TestRegelchecksGrootboek:
    """Blok 7c punt 4: `lees_boekingen` leest voor inkoopfacturen mét pand-signaal de regels (begrensd, in tempo) en
    de afleiding classificeert op grootboek: 7000 = aankoop (notaris-nota), alleen 0101 = geen pand."""

    def _client(self) -> NepClient:
        nota_id = _id("RLZ-04-00000077")
        vast_id = _id("RLZ-24-00000770")
        kosten_id = _id("RLZ-04-00000010")
        collecties = {
            "ManualJournals": [],
            "SalesInvoices": [],
            "PurchaseInvoices": [
                _doc(
                    "RLZ-04-00000077",
                    "Nota van afrekening Rijswijkseweg 409 Den Haag, dossier 2025.078758.01",
                    datum="2025-08-11",
                    bedrag=341333.86,
                    entity=NOTARIS,
                ),
                _doc("RLZ-24-00000770", "Donkerslootstraat 105B Rotterdam", datum="2025-10-23", bedrag=183871.22),
                _doc(
                    "RLZ-04-00000010",
                    "honorarium Kapershoek 34 dossier 2025.078175.01",
                    datum="2025-07-11",
                    bedrag=1352.18,
                    entity=NOTARIS,
                ),
            ],
        }
        regels = {
            nota_id: [
                {"Account": {"AccountNumber": "7000", "AccountType": 2}, "NetAmount": 330000.0},
                {"Account": {"AccountNumber": "4612", "AccountType": 2}, "NetAmount": 9500.0},
                {"Account": {"AccountNumber": "7001", "AccountType": 2}, "NetAmount": 1833.86},
            ],
            vast_id: [
                {
                    "Account": {"AccountNumber": "0101", "AccountType": 3, "IsFixedAssetAccount": True},
                    "NetAmount": 183871.22,
                }
            ],
            kosten_id: [{"Account": {"AccountNumber": "4601", "AccountType": 2}, "NetAmount": 1352.18}],
        }
        return NepClient(collecties, regels=regels)

    def test_regels_sturen_de_soort(self, administratie_id: uuid.UUID) -> None:
        client = self._client()
        rapport = service.leid_af(administratie_id, dry_run=True, client=client, met_bankmutaties=False)
        codes = {p.code: p for p in rapport.panden}
        assert codes["rijswijkseweg-409"].tel() == {"aankoop": {"hoog": 1}}
        assert codes["kapershoek-34"].tel() == {"kosten": {"hoog": 1}}
        assert "donkerslootstraat-105-b" not in codes  # vast actief → geen pand
        assert rapport.regel_checks == 3 and rapport.regel_niet_gecontroleerd == 0
        lines = [p for p, prm in client.calls if p.endswith("/Lines")]
        assert len(lines) == 3 and all(
            prm.get("$expand") == "Account" for p, prm in client.calls if p.endswith("/Lines")
        )
        assert "Regelchecks inkoopfacturen" in service.als_markdown(rapport)
        assert rapport.als_dict()["regel_checks"] == 3

    def test_regelchecks_begrensd_en_grootste_bedragen_eerst(self, administratie_id: uuid.UUID) -> None:
        client = self._client()
        rapport = service.leid_af(
            administratie_id, dry_run=True, client=client, met_bankmutaties=False, max_regel_checks=1
        )
        codes = {p.code: p for p in rapport.panden}
        assert rapport.regel_checks == 1 and rapport.regel_niet_gecontroleerd == 2
        assert codes["rijswijkseweg-409"].tel() == {"aankoop": {"hoog": 1}}  # grootste bedrag eerst gecontroleerd
        assert "donkerslootstraat-105-b" in codes  # niet gecontroleerd → tekstregel (kosten), zichtbaar in de teller

    def test_grootboeken_uit_regels(self) -> None:
        codes, vast = service.grootboeken_uit_regels(
            [
                {"Account": {"AccountNumber": "0107", "AccountType": 3}},
                {"Account": {"AccountNumber": "1405", "AccountType": 3}},
                {"Account": {"AccountNumber": "7000", "AccountType": 2}},
                {"Description": "zonder account"},
            ]
        )
        assert codes == frozenset({"0107", "1405", "7000"}) and vast == frozenset({"0107"})
