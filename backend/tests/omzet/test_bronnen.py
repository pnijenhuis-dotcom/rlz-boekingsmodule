"""Omzetbronnen zonnestudio-dagstaat + kascheck en pilates-betalingsexport (Peter 15-09): deterministische parsers op de
geanonimiseerde rasters (gouden-set-fixtures ab_omzet_zonnestudio / ac_omzet_pilates) én — als de echte voorbeelden in
verkenning/voorbeelden aanwezig zijn — alle zes dagen/kaschecks en de volledige export cent-exact; de kassarapport-hook
(upload → veldvoorstel mét bron, bundeling dagstaat + kascheck, splitsing per uitbetaling, idempotentie op
Factuurnummer),
de harde bron-controles als check-rijen, de intake-routering op store en de Beheerder-instellingen."""

from __future__ import annotations

import io
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.intake import verwerking
from app.intake.eml import IntakeBijlage
from app.main import app
from app.omzet import voorstel as voorstel_service
from app.omzet.bronnen import (
    BRON_PILATES,
    BRON_ZONNESTUDIO_DAGSTAAT,
    BRON_ZONNESTUDIO_KASCHECK,
    herken_bron,
    herken_bron_in_grid,
    lees_grid,
    pilates,
    zonnestudio,
)
from app.omzet.bronnen import service as bronnen_service
from app.omzet.bronnen.grid import grid_uit_json
from app.security.tokens import create_access_token

FIXTURES = Path(__file__).resolve().parents[1] / "keten" / "fixtures"
VOORBEELDEN = Path(__file__).resolve().parents[3] / "verkenning" / "voorbeelden"


def _grid(naam: str, bestand: str):
    return grid_uit_json(naam, json.loads((FIXTURES / naam / bestand).read_text(encoding="utf-8")))


def grid_naar_xlsx(grid, *, blad: str = "Sheet1") -> bytes:  # noqa: ANN001
    """Fixture-raster → echte .xlsx-bytes (zelfde celposities) — de upload-route leest het als spreadsheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = blad
    for r, rij in enumerate(grid.rijen, start=1):
        for c, w in rij.items():
            ws.cell(row=r, column=c + 1, value=float(w) if isinstance(w, Decimal) else w)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


DAGSTAAT = _grid("ab_omzet_zonnestudio", "dagstaat_grid.json")
KASCHECK = _grid("ab_omzet_zonnestudio", "kascheck_grid.json")
KASCHECK.naam = "Kascheck"
KASCHECK.bladen = {"Kascheck": KASCHECK}
EXPORT = _grid("ac_omzet_pilates", "export_grid.json")


class TestZonnestudioParser:
    def test_dagstaat_8_9_26_leest_categorieen_totalen_en_betaalwijzen(self) -> None:
        assert herken_bron_in_grid(DAGSTAAT) == BRON_ZONNESTUDIO_DAGSTAAT
        s = zonnestudio.parse_dagstaat(DAGSTAAT)
        assert (s.datum, s.store) == (date(2026, 9, 8), "Elderveld")
        assert [(c.naam, str(c.netto), str(c.btw), str(c.bruto)) for c in s.categorieen] == [
            ("Points", "250.00", "0.00", "250.00"),
            ("Products", "288.45", "60.58", "349.03"),
            ("Tanning (Walk-ins)", "347.12", "72.88", "420.00"),
        ]
        assert (s.grand_netto, s.grand_btw, s.grand_bruto) == (Decimal("885.57"), Decimal("133.46"), Decimal("1019.03"))
        assert s.betaalwijzen == {"Cash": Decimal("86.81"), "PIN": Decimal("932.22"), "Punten": Decimal("0.00")}
        assert s.deposit_totaal == Decimal("1019.03") and s.points_redeemed == Decimal("921.00")
        rood = [c.naam for c in s.controles if not c.ok]
        assert rood == [
            "Puntenwaarde bekend"
        ]  # de enige bewuste blokkade: eenheid/waarde van 921 punten = STAP-0-vraag

    def test_kascheck_leest_saldi_en_sluit(self) -> None:
        assert herken_bron_in_grid(KASCHECK) == BRON_ZONNESTUDIO_KASCHECK
        k = zonnestudio.parse_kascheck(KASCHECK)
        assert (k.datum, k.beginsaldo, k.telling, k.eindsaldo) == (
            date(2026, 9, 8),
            Decimal("198.20"),
            Decimal("286.00"),
            Decimal("286.00"),
        )
        assert (k.storting, k.eindsaldo_na_storting, k.contante_omzet) == (
            Decimal("80.00"),
            Decimal("206.00"),
            Decimal("87.80"),
        )
        assert all(c.ok for c in k.controles)

    def test_veldvoorstel_gebundeld_kassabedragen_incl_kasverschil_signaal(self) -> None:
        vv = zonnestudio.bouw_veldvoorstel(
            zonnestudio.parse_dagstaat(DAGSTAAT), zonnestudio.parse_kascheck(KASCHECK), bestandsnaam="8-9-26.xls"
        )
        assert vv["bron"] == BRON_ZONNESTUDIO_DAGSTAAT and vv["periode_start"] == vv["periode_eind"] == "2026-09-08"
        assert vv["totaal_omzet"] == "1019.03" and [r["omzet_bedrag"] for r in vv["regels"]] == [
            "250.00",
            "349.03",
            "420.00",
        ]
        assert vv["regels"][0]["balans"] is True  # Points = vooruitontvangen, geen omzet
        d = vv["bron_detail"]
        assert d["wacht_op"] is None and d["kas"]["contante_omzet"] == "87.80"
        per_naam = {c["naam"]: c for c in d["controles"]}
        assert per_naam["Regelsom = Grand Total"]["ok"] and per_naam["Deposit-som = Grand Total gross"]["ok"]
        assert (
            per_naam["Datum in bestand = datum in bestandsnaam"]["ok"]
            and per_naam["Kascheck-datum = dagstaat-datum"]["ok"]
        )
        kv = per_naam["Kasverschil (contante omzet kascheck vs Cash POS)"]
        assert kv["ok"] is False and kv["blokkerend"] is False and "0.99" in kv["detail"]  # oranje signaal
        assert d["sluit"] is False  # puntenwaarde blokkeert nog

    def test_alleen_kascheck_wacht_op_dagstaat(self) -> None:
        vv = zonnestudio.bouw_veldvoorstel(None, zonnestudio.parse_kascheck(KASCHECK))
        assert vv["regels"] == [] and vv["bron_detail"]["wacht_op"] == "dagstaat"
        assert any(c["naam"].startswith("Wederhelft") and not c["ok"] for c in vv["bron_detail"]["controles"])

    @pytest.mark.skipif(not (VOORBEELDEN / "zonnestudio").exists(), reason="echte voorbeelden alleen lokaal")
    def test_alle_zes_echte_dagen_en_kaschecks_sluiten_cent_exact(self) -> None:
        for pad in sorted((VOORBEELDEN / "zonnestudio").glob("*.xls")):
            s = zonnestudio.parse_dagstaat(lees_grid(pad.name, pad.read_bytes()))
            rood = [c.naam for c in s.controles if not c.ok]
            assert rood == ["Puntenwaarde bekend"], (pad.name, rood)
            assert s.store == "Elderveld" and zonnestudio.datum_uit_bestandsnaam(pad.name) == s.datum
        for pad in sorted((VOORBEELDEN / "zonnestudio").glob("kascheck-*.xlsx")):
            k = zonnestudio.parse_kascheck(lees_grid(pad.name, pad.read_bytes()))
            assert all(c.ok for c in k.controles), pad.name
            assert zonnestudio.datum_uit_bestandsnaam(pad.name) == k.datum


class TestPilatesParser:
    def test_export_159_transacties_23_batches_sluitend(self) -> None:
        assert herken_bron_in_grid(EXPORT) == BRON_PILATES
        ts = pilates.parse_transacties(EXPORT)
        assert len(ts) == 159 and all(t.geslaagd for t in ts)
        bs = pilates.groepeer_batches(ts)
        assert (
            len(bs) == 23
            and sum(b.bruto for b in bs) == Decimal("14288.98")
            and sum(b.kosten for b in bs) == Decimal("196.35")
        )
        contant = next(b for b in bs if b.contant)
        assert contant.bruto == Decimal("398.48") and contant.kosten == 0
        # PII: geen namen/e-mails in de veldvoorstellen
        for b in bs:
            vv = pilates.bouw_batch_veldvoorstel(b)
            assert "@" not in json.dumps(vv) and vv["bron"] == BRON_PILATES
            assert Decimal(vv["totaal_omzet"]) == b.netto
            assert vv["bron_detail"]["controles"][0]["ok"]  # som regels = netto uitbetaling

    def test_categorie_defaults_en_beslispunt_combi(self) -> None:
        assert pilates.categorie_voor("10 rittenkaart") == pilates.CATEGORIE_PILATES
        assert pilates.categorie_voor("DROP-IN") == pilates.CATEGORIE_PILATES
        assert (
            pilates.categorie_voor("Proefles Reformer Pilates (1 maand geldig) - Proefles") == pilates.CATEGORIE_PILATES
        )
        assert pilates.categorie_voor("Yoga 5 rittenkaart") == pilates.CATEGORIE_YOGA
        assert pilates.categorie_voor("combi Abonnement") is None  # BESLISPUNT Peter
        assert (
            pilates.categorie_voor("combi Abonnement", {"combi Abonnement": pilates.CATEGORIE_PILATES})
            == pilates.CATEGORIE_PILATES
        )
        assert pilates.categorie_voor(None) is None

    def test_batch_met_dispute_en_kosten(self) -> None:
        bs = {b.batch_id: b for b in pilates.groepeer_batches(pilates.parse_transacties(EXPORT))}
        b = bs["2026-7-9-ca834c16"]
        vv = pilates.bouw_batch_veldvoorstel(b, product_categorieen={"combi Abonnement": pilates.CATEGORIE_PILATES})
        regels = {r["categorie"]: Decimal(r["omzet_bedrag"]) for r in vv["regels"]}
        assert regels[pilates.CATEGORIE_KOSTEN] == -b.kosten and regels[pilates.CATEGORIE_YOGA] == Decimal("33.00")
        assert vv["bron_detail"]["disputes"] == [
            {"factuurnummer": "06ead052", "bedrag": "-175.00", "categorie": pilates.CATEGORIE_PILATES}
        ]
        assert vv["bron_detail"]["sluit"] is True
        dubbel = pilates.bouw_batch_veldvoorstel(
            b,
            product_categorieen={"combi Abonnement": pilates.CATEGORIE_PILATES},
            al_geboekte_factuurnummers={"06ead052|dispute|-175.00|2026-07-07"},
        )
        assert dubbel["bron_detail"]["sluit"] is False and "06ead052" in dubbel["bron_detail"]["controles"][2]["detail"]

    @pytest.mark.skipif(
        not (VOORBEELDEN / "pilates-betalingen-2026-07.xlsx").exists(), reason="echt voorbeeld alleen lokaal"
    )
    def test_echte_export_sluit(self) -> None:
        pad = VOORBEELDEN / "pilates-betalingen-2026-07.xlsx"
        assert herken_bron(pad.name, pad.read_bytes()) == BRON_PILATES
        bs = pilates.groepeer_batches(pilates.parse_transacties(lees_grid(pad.name, pad.read_bytes())))
        assert len(bs) == 23 and sum(b.bruto for b in bs) == Decimal("14288.98")


def _laatste_vv(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict | None:  # noqa: F811
    with scoped_session(administratie_id) as session:
        return bronnen_service._laatste_veldvoorstel(session, document_id)  # noqa: SLF001


def _status(administratie_id: uuid.UUID, document_id: uuid.UUID):  # noqa: ANN202, F811
    with scoped_session(administratie_id) as session:
        d = session.get(Document, document_id)
        return d.status, d.samengevoegd_in_id


class _FakeRlz:
    def find_manual_journals_by_reference(self, *, reference):  # noqa: ANN001, ANN202
        return []

    def find_receipts_by_description_prefix(self, *, prefix):  # noqa: ANN001, ANN202
        return []

    def close(self) -> None:
        pass


class TestKassarapportHook:
    def test_dagstaat_dan_kascheck_wordt_een_gebundeld_document(
        self, administratie_id, gescoopte_gebruiker, opslag
    ) -> None:  # noqa: F811
        dag = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="8-9-26.xlsx",
            inhoud=grid_naar_xlsx(DAGSTAAT),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        vv = _laatste_vv(administratie_id, dag)
        assert vv["bron"] == BRON_ZONNESTUDIO_DAGSTAAT and vv["bron_detail"]["wacht_op"] == "kascheck"
        # Nieuwe categorieën zonder GB-mapping → de bestaande mapping-autovraag (omzetbesluit), dus vraag_open.
        assert _status(administratie_id, dag)[0] == DocumentStatus.VRAAG_OPEN
        kas = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="kascheck-2026-09-08.xlsx",
            inhoud=grid_naar_xlsx(KASCHECK, blad="Kascheck"),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        status, in_ = _status(administratie_id, kas)
        assert status == DocumentStatus.SAMENGEVOEGD and in_ == dag
        compleet = _laatste_vv(administratie_id, dag)
        assert (
            compleet["bron_detail"]["wacht_op"] is None and compleet["bron_detail"]["kas"]["contante_omzet"] == "87.80"
        )
        # Het omzetvoorstel + de harde checks dragen de bron-controles (puntenwaarde blokkeert, kasverschil = signaal).
        voorstel = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=dag)
        assert voorstel.bron == BRON_ZONNESTUDIO_DAGSTAAT and [r.categorie for r in voorstel.regels] == [
            "Points",
            "Products",
            "Tanning (Walk-ins)",
        ]
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=dag, client=_FakeRlz()
        )
        per_naam = {r.naam: r for r in rapport.resultaten}
        assert per_naam["Bron: Puntenwaarde bekend"].ok is False
        assert per_naam["Bron: Kasverschil (contante omzet kascheck vs Cash POS)"].ok is True
        assert per_naam["Bron: Kasverschil (contante omzet kascheck vs Cash POS)"].signaal is True
        assert rapport.geblokkeerd

    def test_kascheck_eerst_dan_dagstaat_bundelt_ook(self, administratie_id, gescoopte_gebruiker, opslag) -> None:  # noqa: F811
        kas = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="kascheck-2026-09-08.xlsx",
            inhoud=grid_naar_xlsx(KASCHECK, blad="Kascheck"),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        assert _laatste_vv(administratie_id, kas)["bron_detail"]["wacht_op"] == "dagstaat"
        dag = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="8-9-26.xlsx",
            inhoud=grid_naar_xlsx(DAGSTAAT),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        assert _status(administratie_id, kas) == (DocumentStatus.SAMENGEVOEGD, dag)
        vv = _laatste_vv(administratie_id, dag)
        assert vv["bron_detail"]["wacht_op"] is None and vv["bron_detail"]["kascheck_document_id"] == str(kas)

    def test_pilates_export_wordt_gesplitst_per_uitbetaling_en_dedupet_op_factuurnummer(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,  # noqa: F811
    ) -> None:
        ouder = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="betalingen-juli.xlsx",
            inhoud=grid_naar_xlsx(EXPORT, blad="Standaardweergave"),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        assert _status(administratie_id, ouder)[0] == DocumentStatus.GESPLITST
        with scoped_session(administratie_id) as session:
            kinderen = list(
                session.scalars(session.query(Document).where(Document.gesplitst_uit_id == ouder).statement)
            )
        assert len(kinderen) == 23
        kind = next(k for k in kinderen if "2026-7-9-ca834c16" in k.bestandsnaam)
        vv = _laatste_vv(administratie_id, kind.id)
        assert vv["bron"] == BRON_PILATES and vv["bron_detail"]["batch_id"] == "2026-7-9-ca834c16"
        assert vv["totaal_omzet"] == "637.08" and vv["bron_detail"]["controles"][2]["ok"]  # nog nergens geboekt
        # Tweede (overlappende) export: dezelfde transacties zijn al in een ander document → blokkerende controle.
        ouder2 = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="betalingen-week28.xlsx",
            inhoud=grid_naar_xlsx(EXPORT, blad="Standaardweergave"),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        with scoped_session(administratie_id) as session:
            kind2 = next(
                k
                for k in session.scalars(session.query(Document).where(Document.gesplitst_uit_id == ouder2).statement)
                if "2026-7-9-ca834c16" in k.bestandsnaam
            )
            kind2_id = kind2.id
        vv2 = _laatste_vv(administratie_id, kind2_id)
        dubbel = vv2["bron_detail"]["controles"][2]
        assert dubbel["ok"] is False and "06ead052" in dubbel["detail"]


class TestInstellingenEnIntake:
    def test_bron_instellingen_put_get_beheerder_en_store_routering(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag
    ) -> None:  # noqa: F811
        client = TestClient(app)
        kop = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        r = client.get(f"/administraties/{administratie_id}/omzet/bron-instellingen", headers=kop)
        assert r.status_code == 200 and r.json()["stores"] == []
        r = client.put(
            f"/administraties/{administratie_id}/omzet/bron-instellingen",
            headers=kop,
            json={
                "stores": ["Elderveld"],
                "product_categorieen": {"combi Abonnement": "Pilateslessen"},
                "psp": {"naam": "Mollie", "kosten_btw": "21"},
                "rekeningen": {},
            },
        )
        assert r.status_code == 200 and r.json()["stores"] == ["Elderveld"]
        # niet-Beheerder → 403
        kop_boekhouder = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        assert (
            client.put(
                f"/administraties/{administratie_id}/omzet/bron-instellingen",
                headers=kop_boekhouder,
                json={"stores": ["X"]},
            ).status_code
            == 403
        )
        assert bronnen_service.administratie_voor_store("elderveld") == administratie_id
        assert bronnen_service.administratie_voor_store("Onbekend") is None
        # Intake: de dagstaat routeert op de store naar de studio-administratie; een onbekende store → verzamelbak
        # mét reden.
        res = verwerking._verwerk_spreadsheet(  # noqa: SLF001
            IntakeBijlage(
                bestandsnaam="8-9-26.xlsx", inhoud=grid_naar_xlsx(DAGSTAAT), content_type="application/octet-stream"
            ),
            afzender="pos@zonnestudio.example",
            actor_id=gescoopte_gebruiker,
            intake_bericht_id=None,
            opslag=opslag,
        )
        assert res.uitkomst == "toegewezen" and "Elderveld" in (res.detail or "")
        with scoped_session(administratie_id) as session:
            assert session.get(Document, res.document_id).soort == DocumentSoort.KASSARAPPORT.value
        bronnen_service.zet_bron_instellingen(
            administratie_id=administratie_id, actor_id=beheerder_id, waarden={"stores": []}
        )
        res2 = verwerking._verwerk_spreadsheet(  # noqa: SLF001
            IntakeBijlage(
                bestandsnaam="9-9-26.xlsx", inhoud=grid_naar_xlsx(DAGSTAAT), content_type="application/octet-stream"
            ),
            afzender="pos@zonnestudio.example",
            actor_id=gescoopte_gebruiker,
            intake_bericht_id=None,
            opslag=opslag,
        )
        assert res2.uitkomst == "verzamelbak" and "niet ingesteld" in (res2.detail or "")
        # Geen omzetbron (willekeurige spreadsheet) = zichtbaar overgeslagen, nooit stil.
        wb = openpyxl.Workbook()
        wb.active["A1"] = "hallo"
        buf = io.BytesIO()
        wb.save(buf)
        res3 = verwerking._verwerk_spreadsheet(  # noqa: SLF001
            IntakeBijlage(bestandsnaam="x.xlsx", inhoud=buf.getvalue(), content_type="application/octet-stream"),
            afzender=None,
            actor_id=gescoopte_gebruiker,
            intake_bericht_id=None,
            opslag=opslag,
        )
        assert res3.uitkomst == "overgeslagen"
