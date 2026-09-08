"""Blok 4 bundel 08-09 avond (besluit Peter 08-09): een leverancier met IC-vlag (actieve rij in
`intercompany_tegenpartij` van de ADMINISTRATIE VAN HET DOCUMENT) slaat in een administratie mét klant-accordering
de stap "ter accordering" over — zelfde flow (checks, boeken/autoboek), géén ronde, wél tijdlijn + audit
"intercompany — klant-accordering overgeslagen (leveranciersregel)". Niet-IC = ongewijzigd; lege/inactieve IC-tabel =
gewone flow (kernprincipe 7: geen stille no-op, maar ook niets bijzonders)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import autoboeken, boeken
from app.documenten.storage import LokaleBestandsopslag
from tests.accordering.conftest import VENDOR_ID, document_status, zet_schema
from tests.bank.conftest import maak_intercompany_tegenpartij
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_autoboeken import (  # noqa: F401 — fixtures via import geregistreerd
    VENDOR_ID as BOUWMAAT_VENDOR_ID,
)
from tests.documenten.test_autoboeken import (  # noqa: F401
    _upload,
    bevestigd_geheugen,
    optin_aan,
    vendor_bouwmaat,
)


def _laag(volgnummer: int, accordeur: uuid.UUID) -> service.LaagInput:
    return service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)


def _patch_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


def _rondes(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.document_accordering WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _overgeslagen_notities(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[str, str, uuid.UUID, dict]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT van_status, naar_status, actor_id, detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id AND jsonb_exists(detail, :sleutel) ORDER BY tijdstip, id"
            ),
            {"id": document_id, "sleutel": service.OVERGESLAGEN_TIJDLIJN_SLEUTEL},
        ).all()
    return [(r[0], r[1], r[2], r[3][service.OVERGESLAGEN_TIJDLIJN_SLEUTEL]) for r in rijen]


def _audit(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :actie AND record_id = :id"),
            {"actie": service.OVERGESLAGEN_AUDIT_ACTIE, "id": document_id},
        ).all()
    return [r[0] for r in rijen]


@pytest.fixture
def accordering_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, accordeur_1: uuid.UUID) -> None:
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])


@pytest.fixture
def ic_leverancier(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    """De crediteur van `klaar_document` (VENDOR_ID) draagt in déze administratie de IC-vlag."""
    return maak_intercompany_tegenpartij(
        admin_engine, administratie_id=administratie_id, entity_guid=VENDOR_ID, naam="Universal Nederland B.V."
    )


class TestHandmatigBoekPad:
    def test_ic_document_boekt_direct_zonder_ronde_met_tijdlijn_en_audit(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        ic_leverancier: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake.puts) == 1
        assert _rondes(admin_engine, klaar_document) == 0, "IC = géén accorderingsronde"

        [(van, naar, actor, detail)] = _overgeslagen_notities(admin_engine, klaar_document)
        assert van == naar == "klaar_om_te_boeken", "notitie zonder statusovergang, vóór de boeking"
        assert actor == gescoopte_gebruiker
        assert detail["reden"] == "intercompany"
        assert detail["vendor_id"] == str(VENDOR_ID)
        assert detail["leverancier_naam"] == "Universal Nederland B.V."
        assert detail["tekst"] == "intercompany — klant-accordering overgeslagen (leveranciersregel)"
        [audit] = _audit(admin_engine, klaar_document)
        assert audit["vendor_id"] == str(VENDOR_ID) and audit["reden"] == "intercompany"

    def test_niet_ic_document_blijft_geblokkeerd(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        with pytest.raises(boeken.AccorderingVereist):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        assert _overgeslagen_notities(admin_engine, klaar_document) == []
        assert _audit(admin_engine, klaar_document) == []

    def test_inactieve_ic_rij_of_andere_administratie_telt_niet(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Alleen een ACTIEVE rij in de administratie van het document is de IC-vlag (`actief=False` = mapping
        uitgezet/niet-IC; een rij van een andere administratie is een andere scope)."""
        maak_intercompany_tegenpartij(
            admin_engine, administratie_id=administratie_id, entity_guid=VENDOR_ID, actief=False
        )
        _patch_rlz(monkeypatch)
        with pytest.raises(boeken.AccorderingVereist):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

    def test_accordering_uit_ic_rij_verandert_niets(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        ic_leverancier: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Zonder klant-accordering is er niets over te slaan: gewone boeking, géén IC-notitie/-audit (geen ruis)."""
        _patch_rlz(monkeypatch)
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert _overgeslagen_notities(admin_engine, klaar_document) == []
        assert service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document) is None

    def test_open_ronde_blijft_leidend_als_ic_vlag_later_komt(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Niets verdwijnt stil: ligt het document al bij de klant, dan omzeilt een later gezette IC-vlag die ronde
        niet — het kantoor haalt 'm zichtbaar terug (bestaande knop) en boekt dan direct."""
        _patch_rlz(monkeypatch)
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        maak_intercompany_tegenpartij(admin_engine, administratie_id=administratie_id, entity_guid=VENDOR_ID)
        with pytest.raises(boeken.AccorderingVereist, match="ligt bij de klant-accordeur"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
        service.trek_accordering_in(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(_overgeslagen_notities(admin_engine, klaar_document)) == 1


class TestAanbiedenEnHistorie:
    def test_ter_accordering_op_ic_document_maakt_geen_ronde_maar_boekt(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        ic_leverancier: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De bulk-knop "Ter accordering aanbieden" (of een verouderd scherm) op een IC-document = de bestaande
        boekstap door de mens die klikte — geen ronde, uitkomst zichtbaar."""
        fake = _patch_rlz(monkeypatch)
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat.accordering is None
        assert resultaat.overgeslagen_reden == "intercompany"
        assert resultaat.geboekt and resultaat.boek_fout is None and resultaat.alles_akkoord
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert _rondes(admin_engine, klaar_document) == 0
        assert len(fake.puts) == 1
        [(_, _, actor, _)] = _overgeslagen_notities(admin_engine, klaar_document)
        assert actor == gescoopte_gebruiker, "de mens die klikte, niet de systeem-actor"

    def test_ter_accordering_op_ic_document_met_boeken_uit_is_zichtbare_fout_geen_ronde(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        ic_leverancier: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat.accordering is None and not resultaat.geboekt
        assert resultaat.boek_fout and "Boeken staat uit" in resultaat.boek_fout
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        assert _rondes(admin_engine, klaar_document) == 0

    def test_bulk_aanbieden_ic_document_uitkomst_geboekt_met_reden(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        ic_leverancier: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        [uitkomst] = service.bulk_aanbieden(
            administratie_id=administratie_id,
            document_ids=[klaar_document],
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert uitkomst.uitkomst == "geboekt"
        assert uitkomst.reden == "intercompany — klant-accordering overgeslagen (leveranciersregel)"
        assert _rondes(admin_engine, klaar_document) == 0

    def test_historie_toont_overgeslagen_voor_en_na_boeking(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordering_aan: None,
        ic_leverancier: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kantoor-historie (controlescherm-sectie): status "overgeslagen" mét reden + leveranciersnaam, geen
        stappen — al vóór de boeking (live) en daarna (blijvend)."""
        _patch_rlz(monkeypatch)
        vooraf = service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document)
        assert vooraf is not None and vooraf.status == "overgeslagen" and vooraf.stappen == []
        assert vooraf.overgeslagen_reden == "intercompany"
        assert vooraf.overgeslagen_leverancier_naam == "Universal Nederland B.V."
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        achteraf = service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document)
        assert achteraf is not None and achteraf.status == "overgeslagen"

    def test_dto_reden_alleen_bij_accordering_aan_en_ic(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        ic_leverancier: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        assert (
            service.accordering_overgeslagen_reden_voor_dto(
                administratie_id=administratie_id, document_id=klaar_document
            )
            is None
        ), "accordering uit → niets over te slaan"
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        assert (
            service.accordering_overgeslagen_reden_voor_dto(
                administratie_id=administratie_id, document_id=klaar_document
            )
            == "intercompany"
        )


class TestAutoboekPad:
    def test_ic_document_autoboekt_ondanks_klant_accordering(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,  # noqa: F811
        bevestigd_geheugen: None,  # noqa: F811
        accordering_aan: None,
    ) -> None:
        """Spiegel van tests/documenten/test_autoboeken.py::test_accordering_aan_weigert_direct_autoboeken — mét
        IC-vlag op de crediteur loopt het autoboek-pad wél door: geboekt door de systeem-actor, géén ronde, IC-notitie
        + audit op de systeem-actor."""
        maak_intercompany_tegenpartij(
            admin_engine, administratie_id=administratie_id, entity_guid=BOUWMAAT_VENDOR_ID, naam="Bouwmaat (IC)"
        )
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert document_status(admin_engine, document_id) == "geboekt"
        assert _rondes(admin_engine, document_id) == 0
        [(_, _, actor, detail)] = _overgeslagen_notities(admin_engine, document_id)
        assert actor == SYSTEEM_ACTOR_ID and detail["vendor_id"] == str(BOUWMAAT_VENDOR_ID)
        assert len(_audit(admin_engine, document_id)) == 1

    def test_zonder_ic_vlag_weigert_autoboeken_nog_steeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,  # noqa: F811
        bevestigd_geheugen: None,  # noqa: F811
        accordering_aan: None,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert document_status(admin_engine, document_id) != "geboekt"
        assert _overgeslagen_notities(admin_engine, document_id) == []
        assert autoboeken is not None  # module-import bewust (het pad loopt via de upload-hook)
