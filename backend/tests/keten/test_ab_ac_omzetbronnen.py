"""Casussen (ab) zonnestudio-dagstaat + kascheck en (ac) pilates-betalingsexport (Peter 15-09) — de omzetbronnen
door de echte keten: upload als kassarapport → deterministische parser (geen AI, geen AVG-gate) → veldvoorstel mét
bron-controles → bundeling van de wederhelft / splitsing per uitbetaling. De diepe asserts (cent-exact per categorie,
kasverschil, dedupe-sleutel) staan in tests/omzet/test_bronnen.py; hier alleen de keten-uitkomst per casus zodat de
gouden set meebeweegt (fixtures/ab_omzet_zonnestudio, fixtures/ac_omzet_pilates — bron.json beschrijft herkomst).

Besluiten Peter 16-09 (opdracht 4): punten = omzet zonnebank 21 % bij verkoop (check "Puntenwaarde bekend"
vervallen), tegenzijde per betaalwijze in het voorstel (PIN → kruispost, cash/storting → kas, kasverschil → signaal),
combi pro rato, Stripe-kosten = EU-dienst verlegd. Besluit Peter 16-09 AVOND (0151): Sunshine Island is een EIGEN BV —
de store routeert platformbreed naar een ándere administratie dan Elderveld (Instellingen › Boeken › Stores)."""

from __future__ import annotations

import copy
import uuid
from decimal import Decimal

from sqlalchemy import select, text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.intake import verwerking
from app.intake.eml import IntakeBijlage
from app.omzet import voorstel as voorstel_service
from app.omzet.bronnen import BRON_PILATES, BRON_ZONNESTUDIO_DAGSTAAT, pilates
from app.omzet.bronnen import service as bronnen_service
from app.omzet.bronnen import stores as stores_service
from tests.omzet.test_bronnen import DAGSTAAT, EXPORT, KASCHECK, grid_naar_xlsx, seed_rekeningschema, seed_tarieven


def _upload(administratie_id: uuid.UUID, actor: uuid.UUID, opslag, naam: str, inhoud: bytes) -> uuid.UUID:  # noqa: ANN001
    return documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=inhoud,
        actor_id=actor,
        opslag=opslag,
        soort=DocumentSoort.KASSARAPPORT,
    ).document_id


def test_ab_dagstaat_plus_kascheck_wordt_een_gebundeld_kassarapport(
    administratie_id, gescoopte_gebruiker, opslag
) -> None:  # noqa: ANN001
    dag = _upload(administratie_id, gescoopte_gebruiker, opslag, "8-9-26.xlsx", grid_naar_xlsx(DAGSTAAT))
    kas = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "kascheck-2026-09-08.xlsx",
        grid_naar_xlsx(KASCHECK, blad="Kascheck"),
    )
    with scoped_session(administratie_id) as session:
        kas_doc = session.get(Document, kas)
        assert (kas_doc.status, kas_doc.samengevoegd_in_id) == (DocumentStatus.SAMENGEVOEGD, dag)
        vv = bronnen_service._laatste_veldvoorstel(session, dag)  # noqa: SLF001
    assert vv["bron"] == BRON_ZONNESTUDIO_DAGSTAAT and vv["totaal_omzet"] == "1019.03"
    assert vv["bron_detail"]["wacht_op"] is None and vv["bron_detail"]["kas"]["contante_omzet"] == "87.80"
    rood = [c["naam"] for c in vv["bron_detail"]["controles"] if not c["ok"] and c["blokkerend"]]
    assert rood == []  # besluit Peter 16-09: punten = omzet, geen puntenwaarde-blokkade; de dag sluit cent-exact
    assert Decimal(vv["bron_detail"]["points_redeemed"]) == 921  # informatief, geen boeking
    punten = next(r for r in vv["regels"] if r["categorie"] == "Points")
    assert punten["balans"] is False and punten["omzet_bedrag"] == "250.00"


def test_ab_tegenzijde_per_betaalwijze_en_tweede_store_sunshine_island(
    administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine
) -> None:  # noqa: ANN001
    ids = seed_rekeningschema(administratie_id)
    tarieven = seed_tarieven(administratie_id)
    # Besluit Peter 16-09 avond (0151): Sunshine Island = eigen BV → eigen administratie; de store-routering is
    # platformbreed (één tabel, unieke storenaam), de dagstaat volgt de store en niet de mailbox/tenaamstelling.
    sunshine = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Sunshine Island B.V.', :rlz)"),
            {"id": sunshine, "rlz": f"rlz-{sunshine}"},
        )
    stores_service.koppel(store="Elderveld", administratie_id=administratie_id, actor_id=beheerder_id)
    stores_service.koppel(store="Sunshine Island", administratie_id=sunshine, actor_id=beheerder_id)
    assert bronnen_service.administratie_voor_store("Elderveld") == administratie_id
    assert bronnen_service.administratie_voor_store("Sunshine Island") == sunshine
    sunshine_grid = copy.deepcopy(DAGSTAAT)
    for rij in sunshine_grid.rijen:
        for c, w in list(rij.items()):
            if isinstance(w, str) and w.strip() == "Elderveld":
                rij[c] = "Sunshine Island"
    res_s = verwerking._verwerk_spreadsheet(  # noqa: SLF001
        IntakeBijlage(
            bestandsnaam="8-9-26.xlsx", inhoud=grid_naar_xlsx(sunshine_grid), content_type="application/octet-stream"
        ),
        afzender="pos@zonnestudio.example",
        actor_id=gescoopte_gebruiker,
        intake_bericht_id=None,
        opslag=opslag,
    )
    assert res_s.uitkomst == "toegewezen"
    with scoped_session(sunshine) as session:
        assert session.get(Document, res_s.document_id).administratie_id == sunshine
    res = verwerking._verwerk_spreadsheet(  # noqa: SLF001
        IntakeBijlage(
            bestandsnaam="8-9-26.xlsx", inhoud=grid_naar_xlsx(DAGSTAAT), content_type="application/octet-stream"
        ),
        afzender="pos@zonnestudio.example",
        actor_id=gescoopte_gebruiker,
        intake_bericht_id=None,
        opslag=opslag,
    )
    assert res.uitkomst == "toegewezen"
    dag = res.document_id
    _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "kascheck-2026-09-08.xlsx",
        grid_naar_xlsx(KASCHECK, blad="Kascheck"),
    )
    v = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=dag)
    per = {r["betaalwijze"]: r for r in v.bron_detail["tegenzijde"]["regels"]}
    assert (per["pin"]["bedrag"], per["pin"]["ledger_id"], per["pin"]["herkomst"]) == (
        "932.22",
        str(ids["Kruispost PIN"]),
        "default",
    )
    assert (per["cash"]["bedrag"], per["cash"]["ledger_id"]) == ("86.81", str(ids["Kas"]))
    assert (per["storting"]["bedrag"], per["storting"]["ledger_id"]) == ("80.00", str(ids["Kas"]))
    assert (per["kasverschil"]["bedrag"], per["kasverschil"]["ledger_id"], per["kasverschil"]["richting"]) == (
        "0.99",
        str(ids["Kasverschillen"]),
        "signaal",
    )
    assert v.bron_detail["tegenzijde"]["vorm"] == "aflettering"
    # Btw-default: alle zonnestudio-categorieën (incl. Points) = hoog uit het RLZ-tarief van de administratie.
    assert {r.categorie: (r.taxrate_id, r.btw_herkomst) for r in v.regels} == {
        "Points": (tarieven["hoog"], "default_hoog"),
        "Products": (tarieven["hoog"], "default_hoog"),
        "Tanning (Walk-ins)": (tarieven["hoog"], "default_hoog"),
    }


def test_ac_betalingsexport_wordt_gesplitst_per_uitbetaling(administratie_id, gescoopte_gebruiker, opslag) -> None:  # noqa: ANN001
    ouder = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "betalingen-juli.xlsx",
        grid_naar_xlsx(EXPORT, blad="Standaardweergave"),
    )
    with scoped_session(administratie_id) as session:
        assert session.get(Document, ouder).status == DocumentStatus.GESPLITST
        kinderen = list(session.scalars(select(Document).where(Document.gesplitst_uit_id == ouder)))
        assert len(kinderen) == 23
        vvs = [bronnen_service._laatste_veldvoorstel(session, k.id) for k in kinderen]  # noqa: SLF001
    assert all(vv["bron"] == BRON_PILATES for vv in vvs)
    assert all(vv["bron_detail"]["controles"][0]["ok"] for vv in vvs)  # som regels = netto uitbetaling, per batch
    # Combi pro rato (Peter 16-09): geen batch heeft nog een ongecategoriseerd "combi Abonnement"; elke verdeling
    # sluit cent-exact op het combi-bedrag.
    # (de contant-batch heeft in de export geen productnaam — bestaand gedrag, blijft blokkerend tot een mens kiest)
    assert all(vv["bron_detail"]["controles"][1]["ok"] for vv in vvs if not vv["bron_detail"]["contant"])
    met_combi = [vv for vv in vvs if vv["bron_detail"]["combi_verdeling"]]
    assert met_combi and all(
        sum(Decimal(x) for x in vv["bron_detail"]["combi_verdeling"]["verdeling"].values())
        == Decimal(vv["bron_detail"]["combi_verdeling"]["bedrag"])
        for vv in met_combi
    )
    assert {vv["bron_detail"]["combi_verdeling"]["basis"] for vv in met_combi} <= {"batch", "historie_30d", "50_50"}


def test_ac_stripe_kosten_verlegd_en_tegenzijde_stripe(administratie_id, gescoopte_gebruiker, opslag) -> None:  # noqa: ANN001
    ids = seed_rekeningschema(administratie_id)
    tarieven = seed_tarieven(administratie_id)
    ouder = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        "betalingen-juli.xlsx",
        grid_naar_xlsx(EXPORT, blad="Standaardweergave"),
    )
    with scoped_session(administratie_id) as session:
        kind = next(
            k
            for k in session.scalars(select(Document).where(Document.gesplitst_uit_id == ouder))
            if "2026-7-9-ca834c16" in k.bestandsnaam
        )
        kind_id = kind.id
    v = voorstel_service.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=kind_id)
    per = {r.categorie: r for r in v.regels}
    kosten = per[pilates.CATEGORIE_KOSTEN]
    assert (kosten.taxrate_id, kosten.btw_herkomst, kosten.btw_herkomst_detail) == (
        tarieven["verlegd"],
        "verlegd",
        "Stripe · EU-dienst verlegd",
    )
    assert (kosten.omzet_ledger_id, kosten.herkomst) == (ids["Transactiekosten PSP"], "default")
    assert (
        per[pilates.CATEGORIE_PILATES].btw_herkomst == "default_laag"
        and per[pilates.CATEGORIE_YOGA].btw_herkomst == "default_laag"
    )
    tz = v.bron_detail["tegenzijde"]
    assert [(r["betaalwijze"], r["bedrag"], r["ledger_id"], r["datum"]) for r in tz["regels"]] == [
        ("stripe", "637.08", str(ids["Stripe onderweg"]), "2026-07-09")
    ]
    assert tz["regels"][0]["venster_dagen"] == [1, 7]  # Stripe loopt achter: +1 … +7 dagen, nooit ervoor
