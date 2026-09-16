# ruff: noqa: F811 — pytest-fixtures als parameters
"""Omzet-Receipts op BINDER Inkomsten (Peter 16-09, casus Van Boxtel): categoriekeuze deterministisch op binder,
mens wint en wordt default, legacy-op-naam-cache wordt geïnvalideerd, harde check "Omzetcategorie (Inkomsten)",
omzet die als inkoopfactuur geboekt is wordt gevonden en via storno + herclassificatie hersteld achter de
aangiftepoort, reconciliatie-soorten `verkoop_categorie_afwijkt` en `omzet_in_inkoopstroom`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol, Grootboekrekening
from app.db.session import scoped_session
from app.documenten import herboeken
from app.documenten import service as documenten_service
from app.documenten import soort as soort_service
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.omzet import categorie, inkoopstroom
from app.omzet import reconciliatie as omzet_reconciliatie
from app.omzet import voorstel as voorstel_service
from app.omzet.models import OmzetInstelling
from app.rlz.aangifte import KantToets
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401
from tests.omzet.conftest import FakeOmzetClient, sla_compleet_voorstel_op

INK = FakeOmzetClient.INKOMSTEN
UIT = FakeOmzetClient.UITGAVEN


def _cat(naam: str, binder: dict | None, dt: int = 10, cid: str | None = None) -> dict:
    return {"id": cid or str(uuid.uuid4()), "Name": naam, "DocumentType": dt, "DocumentBinder": binder}


class TestKiesVerkoopCategorie:
    def test_voorkeursnaam_binnen_inkomsten_wint(self) -> None:
        cats = categorie.lees_categorieen(
            [
                _cat("Diverse opbrengsten", INK),
                _cat("Verkoopfactuur (Omzet)", INK, cid="9138fa50-0000-0000-0000-000000000000"),
                _cat("BTW Prive bijdrage auto", UIT),
                _cat("Kasomzet", None, dt=19),
            ]
        )
        keuze = categorie.kies_verkoop_categorie(cats)
        assert keuze.id.startswith("9138fa50") and keuze.is_inkomsten

    def test_enige_inkomsten_categorie_zonder_voorkeursnaam_wint(self) -> None:
        cats = categorie.lees_categorieen([_cat("Omzet kas", INK), _cat("Verkoopfactuur (Omzet)", UIT)])
        assert categorie.kies_verkoop_categorie(cats).naam == "Omzet kas"

    def test_alleen_uitgaven_of_meerduidig_blokkeert(self) -> None:
        with pytest.raises(categorie.GeenInkomstenCategorie, match="Inkomsten"):
            categorie.kies_verkoop_categorie(categorie.lees_categorieen([_cat("Verkoopfactuur (Omzet)", UIT)]))
        with pytest.raises(categorie.CategorieNietEenduidig):
            categorie.kies_verkoop_categorie(categorie.lees_categorieen([_cat("Omzet A", INK), _cat("Omzet B", INK)]))
        # Zonder expand (binder onbekend) nooit gokken.
        with pytest.raises(categorie.GeenInkomstenCategorie):
            categorie.kies_verkoop_categorie(categorie.lees_categorieen([_cat("Verkoopfactuur (Omzet)", None)]))


class TestStandEnCache:
    def test_legacy_naamkeuze_zonder_inkomsten_binder_wordt_vervangen_en_mens_wint(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        uitgaven_id = uuid.uuid4()
        goed = _cat("Verkoopfactuur (Omzet)", INK)
        cats = categorie.lees_categorieen([_cat("Verkoopfactuur (Omzet)", UIT, cid=str(uitgaven_id)), goed])
        with scoped_session(administratie_id) as session:
            session.add(OmzetInstelling(administratie_id=administratie_id, verkoop_categorie_id=uitgaven_id))
        with scoped_session(administratie_id) as session:
            assert categorie.stand_voor(session, administratie_id).bron == categorie.BRON_AUTOMATISCH  # legacy
            stand = categorie.bepaal_en_bewaar(session, administratie_id, cats)
        assert (str(stand.id), stand.binder, stand.bron) == (goed["id"], "Inkomsten", "automatisch")
        # Mens kiest bewust de Uitgaven-variant → blijft staan bij de volgende bepaling, mét audit.
        with scoped_session(administratie_id) as session:
            assert {c.id for c in categorie.cache_keuzes(session, administratie_id)} == {goed["id"], str(uitgaven_id)}
        mens = categorie.zet_verkoop_categorie_mens(
            administratie_id=administratie_id, actor_id=beheerder_id, categorie_id=uitgaven_id
        )
        assert mens.bron == "mens" and not mens.is_inkomsten
        with scoped_session(administratie_id) as session:
            stand2 = categorie.bepaal_en_bewaar(session, administratie_id, cats)
        assert (stand2.id, stand2.bron) == (uitgaven_id, "mens")
        with pytest.raises(categorie.CategorieOnbekend):
            categorie.zet_verkoop_categorie_mens(
                administratie_id=administratie_id, actor_id=beheerder_id, categorie_id=uuid.uuid4()
            )
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id AND actie LIKE 'omzet_verkoop_%'"),
                {"id": administratie_id},
            ).scalars().all()
        assert acties == ["omzet_verkoop_categorie_gewijzigd"]


class TestHardeCheck:
    def test_check_rood_zonder_inkomsten_categorie_en_groen_met(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        taxrate_vrijgesteld: uuid.UUID,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=taxrate_vrijgesteld,
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        client = FakeOmzetClient()
        client.categorieen = FakeOmzetClient.DOCUMENT_CATEGORIES_ALLEEN_UITGAVEN
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=client
        )
        per = {r.naam: r for r in rapport.resultaten}
        assert not per[categorie.CHECK_NAAM].ok and "Inkomsten" in per[categorie.CHECK_NAAM].melding
        client.categorieen = None
        rapport2 = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=client
        )
        r = {x.naam: x for x in rapport2.resultaten}[categorie.CHECK_NAAM]
        assert r.ok and not r.signaal and "Inkomsten · Verkoopfactuur (Omzet)" in r.melding


@dataclass
class StubPort:
    toegestaan: bool = True

    class _Backend:
        value = "rlz"

    backend = _Backend()

    def toets_btw_periode(self, *, boekdatum: date) -> KantToets:
        if self.toegestaan:
            return KantToets(kant="inkoopfactuur", toegestaan=True)
        return KantToets(
            kant="inkoopfactuur", toegestaan=False, reden="ingediend", periode_start=date(2026, 7, 1),
            periode_eind=date(2026, 9, 30),
        )

    def __exit__(self, *exc: object) -> None:
        return None


def _geboekte_inkoopfactuur(
    administratie_id: uuid.UUID, actor: uuid.UUID, opslag, *, ledgers: list[uuid.UUID], naam: str  # noqa: ANN001
) -> uuid.UUID:
    doc_id = documenten_service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=b"%PDF-1.4 test", actor_id=actor, opslag=opslag
    ).document_id
    with scoped_session(administratie_id, actor_id=actor) as session:
        document = session.get(Document, doc_id)
        assert document is not None
        session.add(
            Boekvoorstel(
                document_id=doc_id, referentie="11-09/12-09", factuurdatum=date(2026, 9, 11),
                totaalbedrag=Decimal("10998.15"), boek_cyclus=0, rlz_boekstuknummer="RLZ-04-00000686",
            )
        )
        for i, ledger in enumerate(ledgers, start=1):
            session.add(
                BoekvoorstelRegel(
                    document_id=doc_id, volgnummer=i, ledger_id=ledger, netto_bedrag=Decimal("100"),
                    btw_bedrag=Decimal("0"), omschrijving=f"regel {i}",
                )
            )
        for stap in (DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.GEBOEKT):
            _schrijf_overgang(session, document=document, naar=stap, actor_id=actor)
    return doc_id


@pytest.fixture
def omzet_ledgers(administratie_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids = {"omzet_hoog": uuid.uuid4(), "omzet_laag": uuid.uuid4(), "kosten": uuid.uuid4()}
    with scoped_session(administratie_id) as session:
        for sleutel, (code, naam) in {
            "omzet_hoog": ("8000", "Omzet hoog"), "omzet_laag": ("8010", "Omzet laag"), "kosten": ("4000", "Huur"),
        }.items():
            session.add(
                Grootboekrekening(
                    ledger_id=ids[sleutel], administratie_id=administratie_id, code=code, naam=naam, soort=0,
                    is_totaalrekening=False,
                )
            )
    return ids


class TestOmzetInInkoopstroom:
    def test_detectie_alleen_als_alle_regels_op_omzetrekeningen_staan(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag, omzet_ledgers  # noqa: ANN001
    ) -> None:
        omzet_doc = _geboekte_inkoopfactuur(
            administratie_id, gescoopte_gebruiker, opslag,
            ledgers=[omzet_ledgers["omzet_hoog"], omzet_ledgers["omzet_laag"]], naam="journaal.pdf",
        )
        _geboekte_inkoopfactuur(
            administratie_id, gescoopte_gebruiker, opslag,
            ledgers=[omzet_ledgers["omzet_hoog"], omzet_ledgers["kosten"]], naam="gemengd.pdf",
        )
        with scoped_session(administratie_id) as session:
            treffers = inkoopstroom.geboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id)
        assert [(t.document_id, t.signaal, t.regels_op_omzet, t.regels_totaal, t.boekstuknummer) for t in treffers] == [
            (omzet_doc, "omzetrekeningen", 2, 2, "RLZ-04-00000686")
        ]
        afw = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id)
        assert [(a.soort, a.document_id) for a in afw] == [(inkoopstroom.SOORT, omzet_doc)]
        assert "onder Uitgaven" in afw[0].detail

    def test_herboek_als_omzet_storno_achter_aangiftepoort_en_herclassificatie(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag,  # noqa: ANN001
        omzet_ledgers,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        doc = _geboekte_inkoopfactuur(
            administratie_id, gescoopte_gebruiker, opslag, ledgers=[omzet_ledgers["omzet_hoog"]], naam="journaal.pdf"
        )
        # Geen echte extractie ná de type-wissel (geen AI in de suite).
        monkeypatch.setattr(
            soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False
        )
        client = FakeOmzetClient()
        # Ingediende aangifte: 409-pad; een gewone kantoorrol mag niet doorzetten, een Beheerder wél mét reden.
        with pytest.raises(herboeken.BtwMogelijkAangegeven):
            inkoopstroom.herboek_als_omzet(
                administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker,
                rol=GebruikerRol.BOEKHOUDING, reden="omzet als inkoop geboekt", client=client, port=StubPort(False),
            )
        with pytest.raises(herboeken.GeenToegang):
            inkoopstroom.herboek_als_omzet(
                administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker,
                rol=GebruikerRol.BOEKHOUDING, reden="omzet als inkoop geboekt", client=client, port=StubPort(False),
                btw_niet_in_aangifte_bevestigd=True, bevestiging_reden="zat er niet in",
            )
        assert not getattr(client, "gestorneerde_inkoop", [])
        r = inkoopstroom.herboek_als_omzet(
            administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER,
            reden="omzet als inkoop geboekt (Van Boxtel)", client=client, port=StubPort(False),
            btw_niet_in_aangifte_bevestigd=True, bevestiging_reden="btw-periode nog niet ingediend volgens Peter",
        )
        assert r.gestorneerd and client.gestorneerde_inkoop == [str(herboeken.rlz_herboeking_id(doc, 0))]
        with admin_engine.connect() as conn:
            soort, status, cyclus, boekstuk = conn.execute(
                text(
                    "SELECT d.soort, d.status, b.boek_cyclus, b.rlz_boekstuknummer FROM boekhouding.document d "
                    "JOIN boekhouding.boekvoorstel b ON b.document_id = d.id WHERE d.id = :id"
                ),
                {"id": doc},
            ).one()
            acties = conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"), {"id": doc}
            ).scalars().all()
        assert (soort, status, cyclus, boekstuk) == ("kassarapport", "ontvangen", 1, None)
        assert "herboekt_als_omzet" in acties and "documentsoort_gewijzigd" in acties
        # Niet meer in de inkoopstroom-lijst (niet meer geboekt); een tweede herboeking is niet mogelijk.
        with scoped_session(administratie_id) as session:
            rest = inkoopstroom.geboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id)
            assert rest == []
        with pytest.raises(herboeken.HerboekenFout):
            inkoopstroom.herboek_als_omzet(
                administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER,
                reden="nog een keer", client=client, port=StubPort(True),
            )


class TestReconciliatieBinder:
    def test_receipt_onder_andere_binder_is_afwijking(self) -> None:
        client = FakeOmzetClient()
        rlz_id = uuid.uuid4()
        client.sales_invoices[str(rlz_id)] = {
            "id": str(rlz_id), "Status": 2,
            "DocumentCategory": {"Name": "BTW Prive bijdrage auto", "DocumentBinder": UIT},
        }
        soort, detail = omzet_reconciliatie._controleer_rlz_document(  # noqa: SLF001
            client=client, pad="SalesInvoices", rlz_id=rlz_id, label="verkoopfactuur"
        )
        assert soort == "verkoop_categorie_afwijkt" and "Uitgaven" in detail
        client.sales_invoices[str(rlz_id)]["DocumentCategory"] = {
            "Name": "Verkoopfactuur (Omzet)",
            "DocumentBinder": INK,
        }
        assert (
            omzet_reconciliatie._controleer_rlz_document(  # noqa: SLF001
                client=client, pad="SalesInvoices", rlz_id=rlz_id, label="verkoopfactuur"
            )
            is None
        )
