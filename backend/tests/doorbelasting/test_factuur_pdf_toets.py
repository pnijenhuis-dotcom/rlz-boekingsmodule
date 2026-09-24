# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 4 bundelrun 24-09 — lees-only meetinstrument `doorbelasting-factuur-pdf-toets` (casus Lusso 261004: per-regel-afronding
995,73 + 49,79 = 1.045,52 versus factuur-niveau 21 % × 4.978,63 = 1.045,51). Puur: classificatie + PDF-tekst-toets; DB: de
telling over een échte 'ontbreekt'-boeking mét fake RLZ-client (alleen GET), élke CLI-argumentvorm letterlijk."""

from __future__ import annotations

import argparse
import io
import uuid
from decimal import Decimal

import pytest

from app import cli
from app.db.session import scoped_session
from app.doorbelasting import factuur_pdf_toets as toets
from app.doorbelasting.factuur import FACTUUR_STATUS_ONTBREEKT, nl_bedrag
from app.doorbelasting.models import DoorbelastingBoeking
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.doorbelasting.conftest import DoorbelastingOpzet, FakeDoorbelastingClient, haal_boekingen, onboarded_opzet  # noqa: F401
from tests.doorbelasting.test_boeken import _boek
from tests.extractie.pdf_helper import maak_tekst_pdf

LUSSO_REDEN = (
    "factuur-PDF onvolledig: btw-som € 1.045,52, totaal incl. € 6.024,15 — lay-out/stamgegevens in de RLZ-UI "
    "(Instellingen › Factuurlay-out) aanvullen, daarna doorbelasting-facturen-herstel"
)


class TestClassificatie:
    def test_lusso_is_een_cent_verschil_door_per_regel_afronding(self) -> None:
        k = toets.classificeer(
            reden=LUSSO_REDEN, netto_totaal=Decimal("4741.55"), provisie=Decimal("237.08"), btw_geboekt=Decimal("1045.52")
        )
        assert k.klasse == toets.KLASSE_CENT
        assert k.btw_factuurniveau == Decimal("1045.51") and k.verschil_ct == 1 and k.percentage == Decimal("21")
        assert k.ontbrekend == ("btw-som € 1.045,52", "totaal incl. € 6.024,15")

    def test_kvk_ontbreekt_is_anders_ook_bij_cent_verschil(self) -> None:
        reden = "factuur-PDF onvolledig: KvK-nummer afzender, btw-som € 1.045,52 — lay-out/stamgegevens …"
        k = toets.classificeer(reden=reden, netto_totaal=Decimal("4741.55"), provisie=Decimal("237.08"), btw_geboekt=Decimal("1045.52"))
        assert k.klasse == toets.KLASSE_ANDERS

    def test_groot_verschil_is_anders(self) -> None:
        reden = "factuur-PDF onvolledig: btw-som € 1.100,00 — …"
        k = toets.classificeer(reden=reden, netto_totaal=Decimal("4741.55"), provisie=Decimal("237.08"), btw_geboekt=Decimal("1100.00"))
        assert k.klasse == toets.KLASSE_ANDERS and abs(k.verschil_ct) > 1

    @pytest.mark.parametrize(
        ("reden", "klasse"),
        [
            ("RLZ-factuurrender mislukt (500) — opnieuw via doorbelasting-facturen-herstel", toets.KLASSE_RENDER),
            ("RLZ gaf geen PDF terug voor de verkoopfactuur", toets.KLASSE_GEEN_PDF),
            ("factuur-PDF onleesbaar (PdfReadError)", toets.KLASSE_ONLEESBAAR),
            (None, toets.KLASSE_OVERIG),
        ],
    )
    def test_overige_redenen(self, reden: str | None, klasse: str) -> None:
        k = toets.classificeer(reden=reden, netto_totaal=Decimal("100"), provisie=Decimal("5"), btw_geboekt=Decimal("22.05"))
        assert k.klasse == klasse


class TestPdfTekstToets:
    def _pdf(self, btw: Decimal, totaal: Decimal) -> bytes:
        return maak_tekst_pdf(
            [
                "Factuurnummer: RLZ-01-00002999",
                "Subtotaal (excl. BTW) € " + nl_bedrag(Decimal("4978.63")),
                "BTW 21 % € " + nl_bedrag(btw),
                "Te betalen € " + nl_bedrag(totaal),
                "KVK: 12345678 BTW nr: NL123456789B01",
            ]
        )

    def test_uitkomst_a_pdf_factuurniveau_record_regelsom(self) -> None:
        from app.doorbelasting.factuur import pdf_tekst

        tekst = pdf_tekst(self._pdf(Decimal("1045.51"), Decimal("6024.14")))
        b_g, b_f, t_g, t_f = toets.toets_pdf_tekst(
            tekst,
            netto_totaal=Decimal("4741.55"),
            provisie=Decimal("237.08"),
            btw_geboekt=Decimal("1045.52"),
            btw_factuurniveau_bedrag=Decimal("1045.51"),
        )
        assert (b_g, b_f, t_g, t_f) == (False, True, False, True)
        uit = toets.bepaal_uitkomst(
            record_regelsom_btw=Decimal("1045.52"),
            btw_geboekt=Decimal("1045.52"),
            btw_factuurniveau_bedrag=Decimal("1045.51"),
            pdf_geboekt=False,
            pdf_factuurniveau=True,
        )
        assert uit == toets.UITKOMST_A

    def test_uitkomst_b_record_ook_factuurniveau(self) -> None:
        uit = toets.bepaal_uitkomst(
            record_regelsom_btw=Decimal("1045.51"),
            btw_geboekt=Decimal("1045.52"),
            btw_factuurniveau_bedrag=Decimal("1045.51"),
            pdf_geboekt=False,
            pdf_factuurniveau=True,
        )
        assert uit == toets.UITKOMST_B

    def test_compleet_en_onbekend(self) -> None:
        assert (
            toets.bepaal_uitkomst(record_regelsom_btw=None, btw_geboekt=Decimal("1"), btw_factuurniveau_bedrag=Decimal("1"), pdf_geboekt=True, pdf_factuurniveau=True)
            == toets.UITKOMST_COMPLEET
        )
        assert (
            toets.bepaal_uitkomst(record_regelsom_btw=None, btw_geboekt=Decimal("1"), btw_factuurniveau_bedrag=Decimal("2"), pdf_geboekt=False, pdf_factuurniveau=False)
            == toets.UITKOMST_ONBEKEND
        )


class _RenderAfwijkendClient(FakeDoorbelastingClient):
    """RLZ-render die de btw op factuur-niveau toont (één cent lager dan de regelsom) — de Lusso-hypothese."""

    def download_sales_invoice_pdf(self, invoice_id: uuid.UUID | str) -> bytes:
        record = self.get_sales_invoice(invoice_id)
        netto = sum((Decimal(str(r["NetAmount"])) for r in record["DocumentLineList"]), Decimal(0))
        btw_regelsom = sum((Decimal(str(r["TaxAmount"])) for r in record["DocumentLineList"]), Decimal(0))
        btw_factuur = btw_regelsom - Decimal("0.01")
        self.factuur_renders.append(str(invoice_id))
        return maak_tekst_pdf(
            [
                f"Factuurnummer:{record['Reference']}",
                "Subtotaal (excl. BTW) € " + nl_bedrag(netto),
                "BTW 21 % € " + nl_bedrag(btw_factuur),
                "Te betalen € " + nl_bedrag(netto + btw_factuur),
                "KVK: 12345678  BTW nr: NL123456789B01",
            ]
        )


class TestMetingOpDeDatabase:
    def _ontbreekt_boeking(self, opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> tuple[DoorbelastingBoeking, _RenderAfwijkendClient]:
        bron, doel = _RenderAfwijkendClient(), FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT, boeking.factuur_pdf_reden
        # Zet de Lusso-casus (KF → Molenhof Verhuur, 261004) op deze boeking: geboekt per regel 995,73 + 49,79 = 1.045,52;
        # het RLZ-record draagt dezelfde regels, de render (fake) toont het factuur-niveau-bedrag 1.045,51.
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            rij = session.get(DoorbelastingBoeking, boeking.id)
            rij.netto_totaal = Decimal("4741.55")
            rij.provisie_bedrag = Decimal("237.08")
            rij.btw_bedrag = Decimal("1045.52")
            rij.factuur_pdf_reden = LUSSO_REDEN
            verkoop_id = str(rij.verkoop_rlz_id)
        record = bron.sales_invoices[verkoop_id]
        record["DocumentLineList"] = [
            {**record["DocumentLineList"][0], "NetAmount": 4741.55, "TaxAmount": 995.73},
            {**record["DocumentLineList"][0], "NetAmount": 237.08, "TaxAmount": 49.79},
        ]
        return haal_boekingen(opzet.administratie_id, opzet.run.id)[0], bron

    def test_telling_en_pdf_toets_lees_only(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        boeking, bron = self._ontbreekt_boeking(onboarded_opzet, beheerder_id)
        renders_voor = list(bron.factuur_renders)
        puts_voor = len(bron.sales_invoices)
        meting = toets.meet(administratie=None, referentie=None, met_pdf=False, maximum=3)
        assert meting is not None and [r.boeking_id for r in meting.rijen] == [str(boeking.id)]
        rij = meting.rijen[0]
        assert rij.klasse == toets.KLASSE_CENT and rij.verschil_ct == 1 and rij.pdf is None
        assert meting.per_klasse == {toets.KLASSE_CENT: 1} and meting.fouten == []
        assert bron.factuur_renders == renders_voor  # zonder --pdf geen RLZ-call

        meting2 = toets.meet(
            administratie=str(onboarded_opzet.administratie_id),
            referentie=None,
            met_pdf=True,
            maximum=3,
            client_factory=lambda _aid: bron,
        )
        assert meting2 is not None and meting2.rijen[0].pdf is not None
        p = meting2.rijen[0].pdf
        assert p["uitkomst"] == toets.UITKOMST_A and p["pdf_bevat_btw_factuurniveau"] is True and p["pdf_bevat_btw_geboekt"] is False
        assert Decimal(p["record_regelsom_btw"]) == Decimal(rij.btw_geboekt)
        assert len(bron.factuur_renders) == len(renders_voor) + 1 and len(bron.sales_invoices) == puts_voor  # alleen GET
        with scoped_session(onboarded_opzet.administratie_id) as session:
            na = session.get(DoorbelastingBoeking, boeking.id)
            assert na.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT  # niets geschreven

    def test_referentie_filter_en_onbekende_administratie(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        self._ontbreekt_boeking(onboarded_opzet, beheerder_id)
        assert toets.meet(administratie=None, referentie="bestaat-niet-xyz", met_pdf=False, maximum=3).rijen == []
        assert toets.meet(administratie="administratie-die-niet-bestaat-zzz", referentie=None, met_pdf=False, maximum=3) is None

    @pytest.mark.parametrize(
        "argv",
        [
            ["doorbelasting-factuur-pdf-toets"],
            ["doorbelasting-factuur-pdf-toets", "--json-uit"],
            ["doorbelasting-factuur-pdf-toets", "--administratie", "{adm}", "--referentie", "TEST", "--pdf", "--max", "1"],
            ["doorbelasting-factuur-pdf-toets", "--administratie", "{adm}", "--pdf", "--json-uit"],
        ],
    )
    def test_elke_cli_argumentvorm_uit_het_meetrecept(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, argv: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boeking, bron = self._ontbreekt_boeking(onboarded_opzet, beheerder_id)
        monkeypatch.setattr(toets, "_standaard_client", lambda _aid: bron)
        argv = [a.replace("{adm}", str(onboarded_opzet.administratie_id)) for a in argv]
        parser = argparse.ArgumentParser()
        toets.register(parser.add_subparsers(dest="commando"))
        args = parser.parse_args(argv)
        uit = io.StringIO()
        assert toets.run(args, uit=uit) == 0
        tekst = uit.getvalue()
        if "--referentie" in argv:
            assert "TOTAAL: 0 boeking(en)" in tekst  # filter TEST past niet op de fixture-referentie
        elif "--json-uit" in argv:
            assert '"per_klasse"' in tekst and str(boeking.id) in tekst
        else:
            assert "TOTAAL: 1 boeking(en) zonder factuur-PDF in 1 administratie(s)" in tekst and toets.KLASSE_CENT in tekst

    def test_commando_geregistreerd_in_app_cli(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, capsys) -> None:
        boeking, _bron = self._ontbreekt_boeking(onboarded_opzet, beheerder_id)
        assert cli.main(["doorbelasting-factuur-pdf-toets", "--json-uit"]) == 0
        assert str(boeking.id) in capsys.readouterr().out
