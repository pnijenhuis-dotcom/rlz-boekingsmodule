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
from app.omzet.bronnen import stores as stores_service
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
        # Besluit Peter 16-09: punten = omzet zonnebank 21 % bij verkoop; "Points Redeemed" informatief, geen check.
        assert [c.naam for c in s.controles if not c.ok] == []
        assert "Puntenwaarde bekend" not in {c.naam for c in s.controles}

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
        assert vv["regels"][0]["categorie"] == "Points" and vv["regels"][0]["balans"] is False  # punten = omzet (16-09)
        assert vv["regels"][0]["btw_klasse_default"] == "hoog"
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
        assert d["sluit"] is True  # de dag sluit cent-exact; het kasverschil is een signaal, geen blokkade

    def test_alleen_kascheck_wacht_op_dagstaat(self) -> None:
        vv = zonnestudio.bouw_veldvoorstel(None, zonnestudio.parse_kascheck(KASCHECK))
        assert vv["regels"] == [] and vv["bron_detail"]["wacht_op"] == "dagstaat"
        assert any(c["naam"].startswith("Wederhelft") and not c["ok"] for c in vv["bron_detail"]["controles"])

    @pytest.mark.skipif(not (VOORBEELDEN / "zonnestudio").exists(), reason="echte voorbeelden alleen lokaal")
    def test_alle_zes_echte_dagen_en_kaschecks_sluiten_cent_exact(self) -> None:
        for pad in sorted((VOORBEELDEN / "zonnestudio").glob("*.xls")):
            s = zonnestudio.parse_dagstaat(lees_grid(pad.name, pad.read_bytes()))
            rood = [c.naam for c in s.controles if not c.ok]
            assert rood == [], (pad.name, rood)
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
        # Besluit Peter 16-09: combi = pro rato over Pilates/Yoga (pseudo-categorie); een expliciete mapping wint.
        assert pilates.categorie_voor("combi Abonnement") == pilates.CATEGORIE_COMBI
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
            {"factuurnummer": "06ead052", "bedrag": "-175.00", "categorie": pilates.CATEGORIE_PILATES, "fee": "7.50"}
        ]  # blok D: de dispute-fee (7,50) zit in de transactiekosten
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
        assert "Bron: Puntenwaarde bekend" not in per_naam  # vervallen (besluit Peter 16-09)
        assert per_naam["Bron: Kasverschil (contante omzet kascheck vs Cash POS)"].ok is True
        assert per_naam["Bron: Kasverschil (contante omzet kascheck vs Cash POS)"].signaal is True
        # Blok A: zonder rekeningschema is er geen tegenrekening voor PIN/kas/storting → blokkerend mét handeling.
        assert (
            per_naam["Bron: Tegenrekening PIN"].ok is False
            and "Instellingen" in per_naam["Bron: Tegenrekening PIN"].melding
        )
        assert per_naam["Bron: Tegenrekening Kasverschil"].signaal is True  # kasverschil blijft een signaal
        assert rapport.geblokkeerd  # de categorie-mapping (omzet-GB) ontbreekt nog + tegenrekeningen

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
            json={"product_categorieen": {"combi Abonnement": "Pilateslessen"}, "psp": "mollie"},
        )
        assert r.status_code == 200 and r.json()["stores"] == []
        assert r.json()["psp"] == "mollie" and "defaults" in r.json() and "rekeningen" in r.json()
        # Stores zijn sinds 0151 (Peter 16-09 avond: Sunshine Island = eigen BV) PLATFORMBREED — de per-administratie-PUT
        # weigert de sleutel (422), het Stores-blok koppelt; de per-administratie-DTO toont de AFGELEIDE lijst.
        assert (
            client.put(
                f"/administraties/{administratie_id}/omzet/bron-instellingen", headers=kop, json={"stores": ["X"]}
            ).status_code
            == 422
        )
        stores_service.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
        r = client.get(f"/administraties/{administratie_id}/omzet/bron-instellingen", headers=kop)
        assert r.json()["stores"] == ["Elderveld"]
        assert bronnen_service.administratie_voor_store("sunshine island") is None
        # niet-Beheerder → 403
        kop_boekhouder = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        assert (
            client.put(
                f"/administraties/{administratie_id}/omzet/bron-instellingen",
                headers=kop_boekhouder,
                json={"psp": "stripe"},
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
        [elderveld] = stores_service.lijst()
        stores_service.zet_actief(routering_id=elderveld.id, actief=False, actor_id=beheerder_id)
        res2 = verwerking._verwerk_spreadsheet(  # noqa: SLF001
            IntakeBijlage(
                bestandsnaam="9-9-26.xlsx", inhoud=grid_naar_xlsx(DAGSTAAT), content_type="application/octet-stream"
            ),
            afzender="pos@zonnestudio.example",
            actor_id=gescoopte_gebruiker,
            intake_bericht_id=None,
            opslag=opslag,
        )
        assert res2.uitkomst == "verzamelbak" and "niet gekoppeld" in (res2.detail or "")
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


# ---------------------------------------------------------------------------------------- besluiten Peter 16-09


def seed_rekeningschema(administratie_id: uuid.UUID, *, met_kruispost: bool = True) -> dict[str, uuid.UUID]:
    """Rekeningschema op NAAM (nooit nummers in code): kas, kruispost PIN, kasverschillen, Stripe onderweg,
    transactiekosten PSP + een totaalrekening die nooit mag winnen."""
    from app.db.models import Grootboekrekening

    namen = [
        ("1000", "Kas", 3),
        ("1300", "Kasverschillen", 2),
        ("1310", "Stripe onderweg", 3),
        ("4720", "Transactiekosten PSP", 2),
        ("8000", "Omzet zonnebank", 1),
    ]
    if met_kruispost:
        namen.append(("1200", "Kruispost PIN", 3))
    ids: dict[str, uuid.UUID] = {}
    with scoped_session(administratie_id) as session:
        for code, naam, soort in namen:
            ledger_id = uuid.uuid4()
            ids[naam] = ledger_id
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=soort,
                    is_totaalrekening=False,
                )
            )
        session.add(
            Grootboekrekening(
                ledger_id=uuid.uuid4(),
                administratie_id=administratie_id,
                code="1",
                naam="Kas en bank (totaal)",
                soort=3,
                is_totaalrekening=True,
            )
        )
    return ids


def seed_tarieven(administratie_id: uuid.UUID) -> dict[str, uuid.UUID]:
    from app.sync.models import TaxRateCache

    tarieven = {
        "laag": ("NL, Laag", Decimal("0.09"), {}),
        "hoog": ("NL, Hoog", Decimal("0.21"), {}),
        "verlegd": ("NL, Verlegd", Decimal("0"), {"IsRelayed": True}),
        "eu_hoog": ("EU, Hoog", Decimal("0.21"), {}),
    }
    ids: dict[str, uuid.UUID] = {}
    with scoped_session(administratie_id) as session:
        for sleutel, (naam, pct, brondata) in tarieven.items():
            tid = uuid.uuid4()
            ids[sleutel] = tid
            session.add(
                TaxRateCache(id=tid, administratie_id=administratie_id, naam=naam, percentage=pct, brondata=brondata)
            )
    return ids


class TestTegenzijdePerBetaalwijze:
    def test_defaults_op_naam_meerduidig_is_geen_default(self) -> None:
        from app.omzet.bronnen import tegenzijde as tz

        r = lambda naam, code="1", totaal=False: tz.Rekening(uuid.uuid4(), code, naam, totaal)  # noqa: E731
        schema = [r("Kas"), r("Kasverschillen"), r("Kruispost PIN"), r("Stripe onderweg"), r("Totaal kas", totaal=True)]
        d = tz.default_tegenrekeningen(schema)
        assert d[tz.CASH] == d[tz.STORTING] == schema[0].ledger_id  # 'kas' raakt 'Kasverschillen' niet
        assert d[tz.KASVERSCHIL] == schema[1].ledger_id and d[tz.PIN] == schema[2].ledger_id
        assert d[tz.STRIPE] == schema[3].ledger_id
        # Twee kandidaten voor hetzelfde patroon = meerduidig → dat patroon valt door; het volgende patroon mét precies
        # één treffer wint ("pin": 3, "kruispost": 2, "onderweg": 0, "te ontvangen": 1).
        twee = [r("Kruispost PIN A"), r("Kruispost PIN B"), r("Nog te ontvangen PIN-omzet")]
        assert tz.default_rekening(tz.PIN, twee) == twee[2]
        assert tz.default_rekening(tz.PIN, twee[:2]) is None  # alleen meerduidige treffers → mens kiest
        assert tz.default_tegenrekeningen([]) == {k: None for k in tz.BETAALWIJZEN}

    def test_zonnestudio_tegenzijde_pin_cash_storting_kasverschil(self) -> None:
        from app.omzet.bronnen import tegenzijde as tz

        vv = zonnestudio.bouw_veldvoorstel(
            zonnestudio.parse_dagstaat(DAGSTAAT), zonnestudio.parse_kascheck(KASCHECK), bestandsnaam="8-9-26.xls"
        )
        kas, pin, kv = (
            tz.Rekening(uuid.uuid4(), c, n)
            for c, n in (("1000", "Kas"), ("1200", "Kruispost PIN"), ("1300", "Kasverschillen"))
        )
        uit = tz.bepaal_tegenzijde(
            bron=vv["bron"], bron_detail=vv["bron_detail"], instellingen={}, rekeningen=[kas, pin, kv]
        )
        per = {r.betaalwijze: r for r in uit.regels}
        assert per[tz.PIN].bedrag == Decimal("932.22") and per[tz.PIN].ledger_id == pin.ledger_id
        assert per[tz.CASH].bedrag == Decimal("86.81") and per[tz.CASH].ledger_id == kas.ledger_id
        assert per[tz.STORTING].bedrag == Decimal("80.00") and per[tz.STORTING].ledger_id == kas.ledger_id
        assert per[tz.KASVERSCHIL].bedrag == Decimal("0.99") and per[tz.KASVERSCHIL].richting == "signaal"
        assert all(r.herkomst == tz.HERKOMST_DEFAULT for r in uit.regels) and all(c.ok for c in uit.controles)
        assert per[tz.PIN].datum == date(2026, 9, 8) and uit.vorm == tz.VORM_AFLETTERING
        # Instelling wint van de default
        eigen = uuid.uuid4()
        uit2 = tz.bepaal_tegenzijde(
            bron=vv["bron"],
            bron_detail=vv["bron_detail"],
            instellingen={"tegenrekeningen": {"pin": str(eigen)}},
            rekeningen=[kas, pin, kv],
        )
        r_pin = next(r for r in uit2.regels if r.betaalwijze == tz.PIN)
        assert (r_pin.ledger_id, r_pin.herkomst) == (eigen, tz.HERKOMST_INSTELLING)

    def test_geen_tegenrekening_is_blokkerende_check_met_handelingsperspectief(self) -> None:
        from app.omzet.bronnen import tegenzijde as tz

        vv = zonnestudio.bouw_veldvoorstel(zonnestudio.parse_dagstaat(DAGSTAAT), None)
        uit = tz.bepaal_tegenzijde(bron=vv["bron"], bron_detail=vv["bron_detail"], instellingen={}, rekeningen=[])
        c = {c.naam: c for c in uit.controles}
        assert c["Tegenrekening PIN"].ok is False and c["Tegenrekening PIN"].blokkerend
        assert "Instellingen › Administraties" in c["Tegenrekening PIN"].detail
        assert "Tegenrekening Kasverschil" not in c  # zonder kascheck geen kasverschil

    def test_pilates_stripe_en_contant(self) -> None:
        from app.omzet.bronnen import tegenzijde as tz

        bs = {b.batch_id: b for b in pilates.groepeer_batches(pilates.parse_transacties(EXPORT))}
        stripe = tz.Rekening(uuid.uuid4(), "1310", "Stripe onderweg")
        kas = tz.Rekening(uuid.uuid4(), "1000", "Kas")
        vv = pilates.bouw_batch_veldvoorstel(bs["2026-7-9-ca834c16"])
        uit = tz.bepaal_tegenzijde(
            bron=vv["bron"], bron_detail=vv["bron_detail"], instellingen={}, rekeningen=[stripe, kas]
        )
        assert [(r.betaalwijze, r.bedrag, r.ledger_id, r.datum) for r in uit.regels] == [
            (tz.STRIPE, Decimal("637.08"), stripe.ledger_id, date(2026, 7, 9))
        ]
        contant = next(b for b in bs.values() if b.contant)
        vvc = pilates.bouw_batch_veldvoorstel(contant)
        uitc = tz.bepaal_tegenzijde(
            bron=vvc["bron"], bron_detail=vvc["bron_detail"], instellingen={}, rekeningen=[stripe, kas]
        )
        assert [(r.betaalwijze, r.ledger_id, r.richting) for r in uitc.regels] == [(tz.CASH, kas.ledger_id, "kas")]

    def test_voorstel_draagt_tegenzijde_en_checks_blokkeren_zonder_rekening(
        self, administratie_id, gescoopte_gebruiker, opslag
    ) -> None:  # noqa: F811
        ids = seed_rekeningschema(administratie_id)
        dag = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="9-9-26.xlsx",
            inhoud=grid_naar_xlsx(DAGSTAAT),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        v = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=dag)
        tz_detail = v.bron_detail["tegenzijde"]
        per = {r["betaalwijze"]: r for r in tz_detail["regels"]}
        assert per["pin"]["ledger_id"] == str(ids["Kruispost PIN"]) and per["pin"]["herkomst"] == "default"
        assert per["cash"]["ledger_id"] == str(ids["Kas"]) and "storting" not in per  # zonder kascheck geen storting
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=dag, client=_FakeRlz()
        )
        per_naam = {r.naam: r for r in rapport.resultaten}
        assert per_naam["Bron: Tegenrekening PIN"].ok and per_naam["Bron: Tegenrekening Contant (kas)"].ok


class TestBtwDefaultsEnStripe:
    def test_klasse_defaults_uit_rlz_tarief_nooit_hardgecodeerd(self) -> None:
        from app.omzet.bronnen import tegenzijde as tz

        laag = tz.Tarief(uuid.uuid4(), "NL, Laag", Decimal("0.09"))
        hoog = tz.Tarief(uuid.uuid4(), "NL, Hoog", Decimal("0.21"))
        eu = tz.Tarief(uuid.uuid4(), "EU, Hoog", Decimal("0.21"))
        verlegd = tz.Tarief(uuid.uuid4(), "NL, Verlegd", Decimal("0"), is_verlegd=True)
        assert tz.default_tarief("laag", [laag, hoog, eu, verlegd]) == laag
        assert tz.default_tarief("hoog", [laag, hoog, eu, verlegd]) == hoog  # EU-variant telt niet mee
        assert tz.default_tarief("hoog", [hoog, tz.Tarief(uuid.uuid4(), "NL, Hoog oud", Decimal("0.21"))]) is None
        assert tz.default_tarief("laag", []) is None
        assert tz.btw_klasse_voor("pilateslessen", {}) == "laag" and tz.btw_klasse_voor("yoga", {}) == "laag"
        assert tz.btw_klasse_voor("kleding producten", {}) == "hoog" and tz.btw_klasse_voor("points", {}) == "hoog"
        assert tz.btw_klasse_voor("eten drinken", {}) == "laag"
        assert tz.btw_klasse_voor("eten drinken", {"eten_drinken_tarief": "hoog"}) == "hoog"
        assert tz.btw_klasse_voor("transactiekosten psp", {"psp": "stripe"}) == "verlegd"
        assert tz.btw_klasse_voor("transactiekosten psp", {"psp": "mollie"}) == "hoog"
        assert tz.btw_klasse_voor("transactiekosten psp", {"psp": "anders"}) is None
        assert tz.btw_klasse_voor("transactiekosten psp", {"psp": {"naam": "Mollie", "kosten_btw": "21"}}) == "hoog"
        assert tz.btw_klasse_voor("onbekende categorie", {}) is None

    def test_prefill_pilates_laag_hoog_stripe_verlegd_en_mens_override(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag
    ) -> None:  # noqa: F811
        ids = seed_rekeningschema(administratie_id)
        tarieven = seed_tarieven(administratie_id)
        bs = {b.batch_id: b for b in pilates.groepeer_batches(pilates.parse_transacties(EXPORT))}
        vv = pilates.bouw_batch_veldvoorstel(bs["2026-7-9-ca834c16"])
        vv["regels"].append({"categorie": "Kleding & producten", "omzet_bedrag": "10.00", "kostprijs_bedrag": None})
        from tests.omzet.conftest import voeg_veldvoorstel_toe

        doc = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="batch.pdf",
            inhoud=b"%PDF-1.4 batch",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        ).document_id
        voeg_veldvoorstel_toe(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker, veldvoorstel=vv
        )
        v = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=doc)
        per = {r.categorie: r for r in v.regels}
        assert (per["Pilateslessen"].taxrate_id, per["Pilateslessen"].btw_herkomst) == (
            tarieven["laag"],
            "default_laag",
        )
        assert (per["Yoga"].taxrate_id, per["Yoga"].btw_herkomst) == (tarieven["laag"], "default_laag")
        assert (per["Kleding & producten"].taxrate_id, per["Kleding & producten"].btw_herkomst) == (
            tarieven["hoog"],
            "default_hoog",
        )
        kosten = per[pilates.CATEGORIE_KOSTEN]
        assert (kosten.taxrate_id, kosten.btw_herkomst) == (
            tarieven["verlegd"],
            "verlegd",
        )  # Stripe = EU-dienst verlegd
        assert kosten.btw_herkomst_detail == "Stripe · EU-dienst verlegd"
        assert (kosten.omzet_ledger_id, kosten.herkomst) == (ids["Transactiekosten PSP"], "default")
        assert per["Pilateslessen"].omzet_ledger_id is None  # omzet-GB blijft mensenwerk (mapping-check blokkeert)
        # Mollie → NL 21 % voorbelasting; mens-override per categorie wint (vanaf de volgende batch = prefill).
        bronnen_service.zet_bron_instellingen(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            waarden={"psp": "mollie", "categorie_btw": {"Yoga": str(tarieven["hoog"])}},
        )
        v2 = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=doc)
        per2 = {r.categorie: r for r in v2.regels}
        assert (per2[pilates.CATEGORIE_KOSTEN].taxrate_id, per2[pilates.CATEGORIE_KOSTEN].btw_herkomst_detail) == (
            tarieven["hoog"],
            "Mollie · NL 21 % voorbelasting",
        )
        assert (per2["Yoga"].taxrate_id, per2["Yoga"].btw_herkomst) == (tarieven["hoog"], "instelling")
        assert per2["Pilateslessen"].taxrate_id == tarieven["laag"]

    def test_put_valideert_ids_tegen_caches_en_geeft_defaults_en_keuzelijsten(
        self, administratie_id, beheerder_id
    ) -> None:  # noqa: F811
        ids = seed_rekeningschema(administratie_id)
        tarieven = seed_tarieven(administratie_id)
        client = TestClient(app)
        kop = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        url = f"/administraties/{administratie_id}/omzet/bron-instellingen"
        r = client.get(url, headers=kop)
        body = r.json()
        assert r.status_code == 200 and body["psp"] == "stripe" and body["combi_regel"] == "pro_rato_batch"
        assert body["defaults"]["tegenrekeningen"]["pin"] == str(ids["Kruispost PIN"])
        assert body["defaults"]["btw_per_klasse"] == {
            "laag": str(tarieven["laag"]),
            "hoog": str(tarieven["hoog"]),
            "verlegd": str(tarieven["verlegd"]),
            "vrijgesteld": None,  # ProfX 16-09: klasse bestaat; deze fixture heeft geen vrijgesteld-tarief
        }
        assert body["defaults"]["categorie_btw"]["transactiekosten psp"]["klasse"] == "verlegd"
        assert {r["naam"] for r in body["rekeningen"]} >= {"Kas", "Kruispost PIN"} and "Kas en bank (totaal)" in {
            r["naam"] for r in body["rekeningen"]
        }
        assert {t["taxrate_id"] for t in body["tarieven"]} == {str(v) for v in tarieven.values()}
        # vreemde ledger → 422; onbekende psp → 422
        assert client.put(url, headers=kop, json={"tegenrekeningen": {"pin": str(uuid.uuid4())}}).status_code == 422
        assert client.put(url, headers=kop, json={"psp": "adyen"}).status_code == 422
        assert client.put(url, headers=kop, json={"tegenrekeningen": {"bitcoin": None}}).status_code == 422
        r = client.put(
            url,
            headers=kop,
            json={
                "tegenrekeningen": {"pin": str(ids["Kas"])},
                "categorie_btw": {"Yoga": str(tarieven["hoog"])},
                "psp": "stripe",
            },
        )
        assert r.status_code == 200 and r.json()["tegenrekeningen"]["pin"] == str(ids["Kas"])
        assert r.json()["categorie_btw"] == {"Yoga": str(tarieven["hoog"])}


class TestCombiProRato:
    def _batch_met_combi(self):  # noqa: ANN202
        """Batch 2026-7-9-ca834c16: combi Abonnement 145,00 náást Pilates én Yoga (beide als batch-basis aanwezig)."""
        bs = {b.batch_id: b for b in pilates.groepeer_batches(pilates.parse_transacties(EXPORT))}
        return bs["2026-7-9-ca834c16"]

    def test_batch_basis_cent_exact_restcent_op_grootste(self) -> None:
        from app.omzet.bronnen.tegenzijde import verdeel_pro_rato

        v = verdeel_pro_rato(Decimal("100.00"), {"Pilateslessen": Decimal("2"), "Yoga": Decimal("1")})
        assert v == {"Pilateslessen": Decimal("66.67"), "Yoga": Decimal("33.33")}
        assert sum(v.values()) == Decimal("100.00")
        v2 = verdeel_pro_rato(Decimal("0.01"), {"Pilateslessen": Decimal("1"), "Yoga": Decimal("1")})
        assert v2 == {"Pilateslessen": Decimal("0.01"), "Yoga": Decimal("0.00")}  # gelijkspel → alfabetisch eerste
        assert verdeel_pro_rato(Decimal("10"), {"Pilateslessen": Decimal("0"), "Yoga": None}) == {}

    def test_drie_takken_batch_historie_50_50(self) -> None:
        b = self._batch_met_combi()
        combi_totaal = sum(t.bedrag for t in b.transacties if (t.product or "").lower().startswith("combi"))
        vv = pilates.bouw_batch_veldvoorstel(b)
        cv = vv["bron_detail"]["combi_verdeling"]
        regels = {r["categorie"]: Decimal(r["omzet_bedrag"]) for r in vv["regels"]}
        assert cv["basis"] == "batch" and Decimal(cv["bedrag"]) == combi_totaal
        assert sum(Decimal(x) for x in cv["verdeling"].values()) == combi_totaal  # cent-exact sluitend
        assert set(cv["verdeling"]) == {pilates.CATEGORIE_PILATES, pilates.CATEGORIE_YOGA}
        assert "combi Abonnement" not in regels and vv["bron_detail"]["controles"][1]["ok"]  # gecategoriseerd
        assert vv["regelsom_omzet"]["sluit"] is True
        combi_ctrl = next(c for c in vv["bron_detail"]["controles"] if c["naam"] == "Combi-verdeling Pilates/Yoga")
        assert combi_ctrl["ok"] and not combi_ctrl["blokkerend"]
        # Historie-tak: een batch met alléén combi-transacties heeft geen batch-basis.
        alleen_combi = pilates.Batch(
            batch_id="x",
            uitbetaaldatum=date(2026, 7, 9),
            transacties=[t for t in b.transacties if (t.product or "").lower().startswith("combi")],
        )
        vv_h = pilates.bouw_batch_veldvoorstel(
            alleen_combi,
            combi_historie_basis={pilates.CATEGORIE_PILATES: Decimal("300"), pilates.CATEGORIE_YOGA: Decimal("100")},
        )
        cvh = vv_h["bron_detail"]["combi_verdeling"]
        assert cvh["basis"] == "historie_30d" and cvh["aandeel"] == {
            pilates.CATEGORIE_PILATES: "0.7500",
            pilates.CATEGORIE_YOGA: "0.2500",
        }
        assert sum(Decimal(x) for x in cvh["verdeling"].values()) == combi_totaal
        # 50/50-tak mét oranje signaal
        vv_5 = pilates.bouw_batch_veldvoorstel(alleen_combi)
        cv5 = vv_5["bron_detail"]["combi_verdeling"]
        assert cv5["basis"] == "50_50" and sum(Decimal(x) for x in cv5["verdeling"].values()) == combi_totaal
        ctrl = next(c for c in vv_5["bron_detail"]["controles"] if c["naam"] == "Combi-verdeling Pilates/Yoga")
        assert ctrl["ok"] is False and ctrl["blokkerend"] is False  # oranje, nooit blokkerend
        assert vv_5["bron_detail"]["sluit"] is True

    def test_expliciete_mapping_wint_van_pro_rato(self) -> None:
        b = self._batch_met_combi()
        vv = pilates.bouw_batch_veldvoorstel(b, product_categorieen={"combi Abonnement": pilates.CATEGORIE_PILATES})
        assert vv["bron_detail"]["combi_verdeling"] is None
