# ruff: noqa: F811 — pytest-fixtures als parameters
"""ProfX Journaal + Margerapport (coffeeshop-kassa, Peter 16-09): deterministische tekstparser (groepen, retouren,
kortingen, sluitcontroles rood/groen, periode 05:00→05:00 = kassadag), herkenning op inhoud (fail-closed sweep: élke
bron heeft precies één regel), btw-klasse-defaults (Wiet/Hash/Joints/Edible vrijgesteld — Edible mét bevestig-controle,
Dranken/Snacks laag, Headshop hoog), tegenzijde kas/PIN (blad 3 ontbreekt = alles kas mét signaal), bundeling journaal
+ margerapport (zelfde dag → één document, weekrapport → eigen document mét periode-dekking), profiel "Winkel / kassa"
afgeleid + override."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.main import app
from app.omzet import voorstel as voorstel_service
from app.omzet.bronnen import herkenning, profx, tegenzijde
from app.omzet.bronnen import service as bronnen_service
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401
from tests.keten import pdf as keten_pdf
from tests.omzet.test_bronnen import seed_rekeningschema, seed_tarieven

FIX = Path(__file__).resolve().parents[1] / "keten" / "fixtures" / "ad_omzet_profx_journaal"
JOURNAAL_PAGINAS = json.loads((FIX / "pdf_tekst.json").read_text(encoding="utf-8"))
MARGE_PAGINAS = json.loads((FIX / "marge_tekst.json").read_text(encoding="utf-8"))
JOURNAAL_REGELS = [r for p in JOURNAAL_PAGINAS for r in p if isinstance(r, str)]
MARGE_REGELS = [r for p in MARGE_PAGINAS for r in p if isinstance(r, str)]
D = Decimal


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class TestHerkenning:
    def test_elke_bron_heeft_een_herkenningsregel(self) -> None:
        """Fail-closed sweep: élke BRON_* constante in app/omzet/bronnen staat in de registry."""
        from app.omzet.bronnen import pilates, zonnestudio

        bronnen = {
            zonnestudio.BRON_DAGSTAAT,
            zonnestudio.BRON_KASCHECK,
            pilates.BRON,
            profx.BRON_JOURNAAL,
            profx.BRON_MARGE,
        }
        assert set(herkenning.ALLE_BRONNEN) == bronnen
        assert len(herkenning.REGELS) == len(bronnen), "een bron zonder eigen regel of een dubbele regel"
        assert {profx.BRON_JOURNAAL, profx.BRON_MARGE} == herkenning.PDF_BRONNEN

    def test_journaal_en_margerapport_op_inhoud_niet_op_afzender(self) -> None:
        assert herkenning.herken_pdf_tekst(JOURNAAL_REGELS) == profx.BRON_JOURNAAL
        assert herkenning.herken_pdf_tekst(MARGE_REGELS) == profx.BRON_MARGE
        assert (
            herkenning.herken_pdf_tekst(["Factuur 2026-608", "Spot Services B.V.", "Totaal incl. btw 1.210,00"]) is None
        )
        # Echte PDF-bytes (keten-pdf-bouwer) → tekstlaag → herkenning.
        assert herkenning.herken_pdf(keten_pdf.maak_pdf(JOURNAAL_PAGINAS)) == profx.BRON_JOURNAAL
        assert herkenning.herken_pdf(keten_pdf.maak_pdf(MARGE_PAGINAS)) == profx.BRON_MARGE


class TestParserJournaal:
    def test_kop_groepen_totalen_en_betaalwijzen(self) -> None:
        j = profx.parse_journaal(JOURNAAL_REGELS)
        assert j.kassas == ["Kassa 1", "Kassa 2"] and j.klanten == 604 and j.bedrijf == "De Bazar Apeldoorn B.V."
        assert j.kassadag == date(2026, 9, 11) and j.eind_dag == date(2026, 9, 11)  # 05:00 → 05:00 = één kassadag
        assert [g.naam for g in j.groepen] == ["Dranken", "Edible", "Hash", "Headshop", "Joints", "Snacks", "Wiet"]
        assert j.groepen[2].bedrag == D("1669.64") and j.groepen[6].aantal == D("604")
        assert (j.bruto, j.kortingen, j.vouchers, j.netto) == (D("10998.16"), D("0.00"), D("0.00"), D("10998.16"))
        assert j.betaalwijzen == {"Cash": D("6410.66"), "PIN": D("4587.50")}
        assert all(c.ok for c in j.controles), [c for c in j.controles if not c.ok]

    def test_retouren_en_kortingen_zijn_negatieve_component_en_sluitcontroles_worden_rood(self) -> None:
        regels = [
            "ProfX Journaal",
            "Rapportperiode: 11-09-2026 05:00 t/m 12-09-2026 05:00",
            "Artikelgroepen",
            "Wiet 10 100,00 1 10,00 5,00",
            "Snacks 2 7,50 0 0,00 0,00",
            "Bruto omzet 92,50",
            "Kortingen 5,00",
            "Vouchers 0,00",
            "Netto omzet 87,50",
        ]
        j = profx.parse_journaal(regels)
        assert j.groepen[0].omzet == D("85.00")  # 100 − 10 retour − 5 korting
        namen = {c.naam: c for c in j.controles}
        assert namen["Σ artikelgroepen (bedrag − retour − korting) = Bruto omzet"].ok  # 85 + 7,50 = 92,50
        assert namen["Bruto − Kortingen − Vouchers = Netto omzet"].ok
        assert not namen["Betaalwijzen gelezen"].ok and not namen["Betaalwijzen gelezen"].blokkerend
        fout = profx.parse_journaal([r.replace("Bruto omzet 92,50", "Bruto omzet 99,99") for r in regels])
        assert not {c.naam: c for c in fout.controles}["Σ artikelgroepen (bedrag − retour − korting) = Bruto omzet"].ok
        leeg = profx.parse_journaal(["ProfX Journaal", "Rapportperiode: 11-09-2026 05:00", "Artikelgroepen"])
        assert not {c.naam: c for c in leeg.controles}["Artikelgroepen gelezen"].ok


class TestParserMarge:
    def test_inkoopwaarde_per_groep_uit_de_kolomkop(self) -> None:
        m = profx.parse_margerapport(MARGE_REGELS)
        assert (m.periode_van, m.periode_tot) == (date(2026, 9, 11), date(2026, 9, 11))
        assert m.groepen["Wiet"] == D("3858.88") and m.groepen["Dranken"] == D("31.00") and m.totaal == D("6295.23")
        assert all(c.ok for c in m.controles), [c for c in m.controles if not c.ok]
        assert profx.dekt(date(2026, 9, 8), date(2026, 9, 14), date(2026, 9, 11))
        assert not profx.dekt(date(2026, 9, 8), date(2026, 9, 14), date(2026, 9, 15))


class TestVeldvoorstelEnBtw:
    def test_veldvoorstel_regels_incl_btw_kostprijs_defaults_en_edible_bevestiging(self) -> None:
        j = profx.parse_journaal(JOURNAAL_REGELS)
        m = profx.parse_margerapport(MARGE_REGELS)
        vv = profx.bouw_veldvoorstel(j, m, marge_document_id="m-1")
        assert vv["bron"] == profx.BRON_JOURNAAL and vv["soort"] == "kassarapport"
        assert (vv["periode_start"], vv["periode_eind"], vv["totaal_omzet"], vv["totaal_kostprijs"]) == (
            "2026-09-11",
            "2026-09-11",
            "10998.16",
            "6295.23",
        )
        per = {r["categorie"]: r for r in vv["regels"]}
        assert per["Wiet"]["omzet_bedrag"] == "6431.47" and per["Wiet"]["kostprijs_bedrag"] == "3858.88"
        assert per["Wiet"]["btw_klasse_default"] == "vrijgesteld" and per["Headshop"]["btw_klasse_default"] == "hoog"
        assert per["Dranken"]["btw_klasse_default"] == "laag" and per["Edible"]["bevestig_categorie"] is True
        assert vv["regelsom_omzet"]["sluit"] and vv["regelsom_kostprijs"]["sluit"]
        namen = [c["naam"] for c in vv["bron_detail"]["controles"]]
        assert any(n.startswith("Edible: categorie uit default") for n in namen)
        assert (
            vv["bron_detail"]["marge"]["stand"] == "gekoppeld" and vv["bron_detail"]["betaalwijzen"]["PIN"] == "4587.50"
        )
        # Zonder margerapport: alleen omzet, kostprijs oranje (geen blokkade).
        alleen = profx.bouw_veldvoorstel(j, None)
        assert alleen["totaal_kostprijs"] is None and alleen["bron_detail"]["marge"] == {"stand": "verwacht"}
        c = {x["naam"]: x for x in alleen["bron_detail"]["controles"]}["Margerapport (kostprijs)"]
        assert not c["ok"] and not c["blokkerend"]

    def test_btw_klasse_defaults_en_vrijgesteld_tarief(self) -> None:
        assert tegenzijde.btw_klasse_voor("wiet", {}) == tegenzijde.BTW_VRIJGESTELD
        assert tegenzijde.btw_klasse_voor("edible", {}) == tegenzijde.BTW_VRIJGESTELD
        assert tegenzijde.btw_klasse_voor("dranken", {}) == tegenzijde.BTW_LAAG
        assert tegenzijde.btw_klasse_voor("headshop", {}) == tegenzijde.BTW_HOOG
        tarieven = [
            tegenzijde.Tarief(uuid.uuid4(), "NL, Hoog", D("0.21")),
            tegenzijde.Tarief(uuid.uuid4(), "NL, Geen BTW (Vrijgesteld)", D("0"), is_vrijgesteld=True),
            tegenzijde.Tarief(uuid.uuid4(), "NL, Verlegd", D("0"), is_verlegd=True),
        ]
        vrij = tegenzijde.default_tarief(tegenzijde.BTW_VRIJGESTELD, tarieven)
        assert vrij is not None and vrij.naam == "NL, Geen BTW (Vrijgesteld)"
        # Twee vrijgestelde tarieven zonder NL-onderscheid = meerduidig → None (mens kiest).
        twee = [*tarieven, tegenzijde.Tarief(uuid.uuid4(), "Vrijgesteld (oud)", D("0"), is_vrijgesteld=True)]
        assert tegenzijde.default_tarief(tegenzijde.BTW_VRIJGESTELD, twee) is not None  # 'NL, …' is de enige NL-variant

    def test_tegenzijde_kas_en_pin_en_zonder_blad_3_alles_op_kas(self) -> None:
        r = lambda naam, code="1": tegenzijde.Rekening(uuid.uuid4(), code, naam)  # noqa: E731
        schema = [r("Kas", "1000"), r("Kruispost PIN", "1301")]
        detail = {"datum": "2026-09-11", "betaalwijzen": {"Cash": "6410.66", "PIN": "4587.50"}, "bruto": "10998.16"}
        t = tegenzijde.bepaal_tegenzijde(
            bron=profx.BRON_JOURNAAL, bron_detail=detail, instellingen={}, rekeningen=schema
        )
        assert t is not None and {x.betaalwijze: x.bedrag for x in t.regels} == {
            "pin": D("4587.50"),
            "cash": D("6410.66"),
        }
        assert all(c.ok for c in t.controles)
        zonder = tegenzijde.bepaal_tegenzijde(
            bron=profx.BRON_JOURNAAL,
            bron_detail={"datum": "2026-09-11", "bruto": "10998.16"},
            instellingen={},
            rekeningen=schema,
        )
        assert zonder is not None and [(x.betaalwijze, x.bedrag) for x in zonder.regels] == [("cash", D("10998.16"))]


def _upload_pdf(administratie_id: uuid.UUID, actor: uuid.UUID, opslag, naam: str, paginas) -> uuid.UUID:  # noqa: ANN001
    r = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=keten_pdf.maak_pdf(paginas),
        actor_id=actor,
        opslag=opslag,
        soort=DocumentSoort.KASSARAPPORT,
    )
    return r.document_id


def _vv(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    with scoped_session(administratie_id) as session:
        return bronnen_service._laatste_veldvoorstel(session, document_id) or {}  # noqa: SLF001


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


class TestVerwerkingEnBundeling:
    def test_journaal_pdf_wordt_deterministisch_kassarapport_zonder_ai_en_margerapport_zelfde_dag_bundelt(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag,
        admin_engine: Engine,  # noqa: ANN001
    ) -> None:
        seed_rekeningschema(administratie_id)
        seed_tarieven(administratie_id)
        j = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag, "journaal.pdf", JOURNAAL_PAGINAS)
        vv = _vv(administratie_id, j)
        assert vv.get("bron") == profx.BRON_JOURNAAL, vv.keys()
        # te_controleren, of vraag_open als de omzet-autovraag (bestaand gedrag kassarapporten) direct vuurt.
        assert _status(admin_engine, j) in ("te_controleren", "vraag_open")
        assert vv["bron_detail"]["marge"] == {"stand": "verwacht"}
        # Het omzet-voorstel: regels per groep mét btw-default uit de klasse (vrijgesteld/laag/hoog) en live
        # marge-stand.
        data = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=j)
        assert [r.categorie for r in data.regels] == [
            "Dranken",
            "Edible",
            "Hash",
            "Headshop",
            "Joints",
            "Snacks",
            "Wiet",
        ]
        assert data.bron_detail["marge"]["stand"] == "verwacht" and data.bron_detail["marge"]["week"] == 37
        # Margerapport van dezelfde dag → in het journaal gebundeld (kostprijs gevuld), zelf SAMENGEVOEGD.
        m = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag, "marge.pdf", MARGE_PAGINAS)
        assert _status(admin_engine, m) == "samengevoegd"
        vv2 = _vv(administratie_id, j)
        assert vv2["bron_detail"]["marge"]["stand"] == "gebundeld" and vv2["totaal_kostprijs"] == "6295.23"
        assert {r["categorie"]: r["kostprijs_bedrag"] for r in vv2["regels"]}["Wiet"] == "3858.88"
        data2 = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=j)
        assert data2.rapport_totaal_kostprijs == D("6295.23") and data2.bron_detail["marge"]["stand"] == "gebundeld"

    def test_weekmargerapport_blijft_eigen_document_en_dekt_dagjournalen(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag,
        admin_engine: Engine,  # noqa: ANN001
    ) -> None:
        j = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag, "journaal.pdf", JOURNAAL_PAGINAS)
        week = [[r.replace("11-09-2026 t/m 11-09-2026", "08-09-2026 t/m 14-09-2026") for r in MARGE_PAGINAS[0]]]
        m = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag, "marge-week.pdf", week)
        assert _status(admin_engine, m) in ("te_controleren", "vraag_open")  # eigen document: één memoriaal per periode
        vvm = _vv(administratie_id, m)
        assert vvm["bron"] == profx.BRON_MARGE and vvm["bron_detail"]["gedekte_journalen"] == [str(j)]
        dekking = {c["naam"]: c for c in vvm["bron_detail"]["controles"]}[
            "Periode-dekking: dagjournalen in de margeperiode"
        ]
        assert not dekking["ok"] and not dekking["blokkerend"] and "1 van 7 dagen" in dekking["detail"]
        # Het dagjournaal toont live "kostprijs: weekrapport 37 gekoppeld" — zonder herextractie.
        data = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=j)
        assert data.bron_detail["marge"]["stand"] == "gekoppeld_periode" and data.bron_detail["marge"]["week"] == 37
        assert data.bron_detail["marge"]["document_id"] == str(m)


class TestKassaProfiel:
    def test_afgeleid_uit_kassarapport_en_beheerder_override(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag,  # noqa: ANN001
    ) -> None:
        assert beheer_service.haal_kassa_profiel_op(administratie_id=administratie_id).kassa_profiel is False
        _upload_pdf(administratie_id, gescoopte_gebruiker, opslag, "journaal.pdf", JOURNAAL_PAGINAS)
        stand = beheer_service.haal_kassa_profiel_op(administratie_id=administratie_id)
        assert (stand.kassa_profiel, stand.bron, stand.override) == (True, "afgeleid", None)
        client = TestClient(app)
        bh = _bearer(beheerder_id, rol="beheerder")
        pad = f"/administraties/{administratie_id}/kassa-profiel"
        assert (
            client.patch(
                pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json={"kassa_profiel": False}
            ).status_code
            == 403
        )
        r = client.patch(pad, headers=bh, json={"kassa_profiel": False})
        assert r.status_code == 200 and r.json() == {"kassa_profiel": False, "bron": "override", "override": False}
        r2 = client.patch(pad, headers=bh, json={"kassa_profiel": None})
        assert r2.json() == {"kassa_profiel": True, "bron": "afgeleid", "override": None}
        lijst = client.get("/instellingen/administraties", headers=bh).json()["administraties"]
        rij = next(a for a in lijst if a["id"] == str(administratie_id))
        assert (rij["kassa_profiel"], rij["kassa_profiel_bron"]) == (True, "afgeleid")


class TestInkoopstroomRapport:
    def test_profx_pdf_als_inkoopfactuur_wordt_gemeld_en_geboekt_alleen_gemeld(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag, admin_engine: Engine  # noqa: ANN001
    ) -> None:
        """Blok A2: lees-only rapport — een ProfX-PDF die (vóór 16-09) als inkoopfactuur is opgeslagen is een treffer
        'herclassificeren'; een geboekt exemplaar wordt alleen gemeld; een gewone factuur-PDF telt niet."""
        from app.omzet.bronnen import inkoopstroom_rapport

        fout = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="journaal-als-factuur.pdf",
            inhoud=keten_pdf.maak_pdf(JOURNAAL_PAGINAS),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.INKOOPFACTUUR,
        ).document_id
        gewoon = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=keten_pdf.maak_pdf([["Factuur 123", "Totaal 10,00"]]),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.INKOOPFACTUUR,
        ).document_id
        geboekt = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="journaal-geboekt.pdf",
            inhoud=keten_pdf.maak_pdf(MARGE_PAGINAS),
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.INKOOPFACTUUR,
        ).document_id
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": geboekt})
        rapporten = inkoopstroom_rapport.rapport(dagen=30, administratie_ids=[administratie_id], opslag=opslag)
        assert len(rapporten) == 1
        per = {t.document_id: t for t in rapporten[0].treffers}
        assert set(per) == {fout, geboekt} and gewoon not in per
        assert (per[fout].bron, per[fout].actie) == (profx.BRON_JOURNAAL, "herclassificeren")
        assert (per[geboekt].bron, per[geboekt].actie) == (profx.BRON_MARGE, "melden (geboekt)")
