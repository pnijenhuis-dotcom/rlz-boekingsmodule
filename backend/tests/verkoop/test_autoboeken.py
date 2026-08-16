"""Verkoop-autoboeken-opt-in (besluit Peter 2026-08-15, migratie 0051): het pad boekt
uitsluitend wanneer het hele voorstel deterministisch uit de UBL volgt én alle failsafes
groen zijn — elke weiger-reden getest, plus de opt-in-beheerlaag (alleen is_vastgoed)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as documenten_boeken
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import TaxRateCache
from app.verkoop import autoboeken as verkoop_autoboeken
from app.verkoop import voorstel as voorstel_service
from app.verkoop.models import VerkoopBtwVoorkeur
from tests.verkoop.conftest import (
    TAXRATE_21_ID,
    FakeVerkoopClient,
    bouw_vastly_creditnote_ubl,
    bouw_vastly_verkoop_ubl,
    upload_verkoopfactuur,
)

TAXRATE_21_VOORUIT_ID = uuid.UUID("22222222-2222-2222-2222-222222222229")


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeVerkoopClient) -> None:
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _weiger_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'reden' FROM platform.audit_event "
                    "WHERE actie = 'autoboeken_geweigerd' AND record_id = :id"
                ),
                {"id": document_id},
            )
        ]


@pytest.fixture
def vastgoed_administratie(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id


@pytest.fixture
def optin_aan(vastgoed_administratie: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_verkoop_autoboeken_ingeschakeld(
        actor_id=beheerder_id, administratie_id=vastgoed_administratie, ingeschakeld=True
    )


def _upload(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag,
    inhoud: bytes, bestandsnaam: str = "vastly-verkoop.xml",
) -> uuid.UUID:
    return upload_verkoopfactuur(
        administratie_id=administratie_id, actor_id=actor_id, opslag=opslag,
        inhoud=inhoud, bestandsnaam=bestandsnaam,
    )


class TestOptInBeheer:
    def test_aanzetten_weigert_niet_vastgoed(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        with pytest.raises(beheer_service.BeheerFout, match="is_vastgoed"):
            beheer_service.zet_verkoop_autoboeken_ingeschakeld(
                actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
            )
        assert beheer_service.haal_verkoop_autoboeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_uitzetten_kan_altijd_en_zetten_wordt_geauditeerd(
        self, admin_engine: Engine, vastgoed_administratie: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        beheer_service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=vastgoed_administratie, ingeschakeld=True
        )
        # is_vastgoed later teruggedraaid: uitzetten blijft mogelijk (geen vergrendelde vlag).
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = false WHERE id = :id"),
                {"id": vastgoed_administratie},
            )
        beheer_service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=vastgoed_administratie, ingeschakeld=False
        )
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'verkoop_autoboeken_ingeschakeld_gewijzigd' AND record_id = :id"
                ),
                {"id": vastgoed_administratie},
            ).scalar_one()
        assert audit == 2


class TestVerkoopAutoboeken:
    def test_optin_uit_doet_niets_en_audit_stil(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
    ) -> None:
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, document_id) == "te_controleren"
        assert _weiger_redenen(admin_engine, document_id) == []

    def test_happy_path_boekt_automatisch_met_zichtbare_herkomst(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        _patch_client(monkeypatch, FakeVerkoopClient())
        # De upload-hook probeert autoboeken zelf al (post-commit) — geen menselijke klik.
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            detail, actor = conn.execute(
                text(
                    "SELECT detail, actor_id FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": document_id},
            ).one()
            assert detail["automatisch_geboekt"] is True
            assert detail["bron"] == "verkoop_opt_in"
            assert str(actor) == str(SYSTEEM_ACTOR_ID)
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt' AND record_id = :id"
                ),
                {"id": document_id},
            ).scalar_one()
            assert audit == 1
            # De factuur_geboekt-webhook vuurt identiek aan handmatig boeken (is_vastgoed).
            event = conn.execute(
                text("SELECT event FROM boekhouding.webhook_uitgaand WHERE document_id = :id"),
                {"id": document_id},
            ).scalar_one()
            assert event == "factuur_geboekt"
        # Werkvoorraad-lijst draagt de markering (zelfde chip/filter als het inkoop-pad).
        items = documenten_service.lijst_documenten(administratie_id=vastgoed_administratie)
        item = next(i for i in items if i.document.id == document_id)
        assert item.automatisch_geboekt is True

    def test_gb_code_ontbreekt_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        _patch_client(monkeypatch, FakeVerkoopClient())
        ubl = bouw_vastly_verkoop_ubl(
            regels=[{"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": None}]
        )
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=ubl
        )
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "geen grootboekcode" in reden

    def test_onbekende_gb_code_weigert_en_autovraag_blijft(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET eigenaar_gebruiker_id = :g WHERE id = :id"),
                {"g": gescoopte_gebruiker, "id": vastgoed_administratie},
            )
        _patch_client(monkeypatch, FakeVerkoopClient())
        ubl = bouw_vastly_verkoop_ubl(
            regels=[{"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": "9999"}]
        )
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=ubl
        )
        # De weigering is geauditeerd én de autovraag is daarná gewoon gesteld (volgorde-eis
        # van de hook: autoboek eerst, anders verstopt de vraag-status de weigering).
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "onbekend in het rekeningschema" in reden
        with admin_engine.connect() as conn:
            vragen = conn.execute(
                text("SELECT count(*) FROM boekhouding.vraag WHERE document_id = :id"),
                {"id": document_id},
            ).scalar_one()
        assert vragen == 1

    def test_btw_ambigu_zonder_voorkeur_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        with scoped_session(vastgoed_administratie) as session:
            session.add(
                TaxRateCache(
                    id=TAXRATE_21_VOORUIT_ID, administratie_id=vastgoed_administratie,
                    naam="NL, Hoog Tarief (vooruit)", percentage=Decimal("0.2100"),
                    brondata={"Name": "NL, Hoog Tarief (vooruit)", "Percentage": 0.21,
                              "IsRelayed": False, "IsExcempt": False, "IsMixed": False, "TaxKind": 1},
                )
            )
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "ambigu" in reden

    def test_btw_onthouden_voorkeur_boekt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        """De eerder door een mens bevestigde ambiguïteitskeuze (verkoop_btw_voorkeur) telt als
        groen — zelfde lijn als app-bevestigd boekingsgeheugen bij inkoop."""
        with scoped_session(vastgoed_administratie) as session:
            session.add(
                TaxRateCache(
                    id=TAXRATE_21_VOORUIT_ID, administratie_id=vastgoed_administratie,
                    naam="NL, Hoog Tarief (vooruit)", percentage=Decimal("0.2100"),
                    brondata={"Name": "NL, Hoog Tarief (vooruit)", "Percentage": 0.21,
                              "IsRelayed": False, "IsExcempt": False, "IsMixed": False, "TaxKind": 1},
                )
            )
            session.add(
                VerkoopBtwVoorkeur(
                    administratie_id=vastgoed_administratie, btw_categorie="S",
                    percentage_fractie=Decimal("0.2100"), taxrate_id=TAXRATE_21_ID,
                )
            )
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, document_id) == "geboekt"

    def test_harde_check_blokkeert_autoboeken(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        """Duplicaat (zelfde Vastly-factuurnummer, andere bestandsinhoud): het voorstel is
        deterministisch groen, maar de harde checks in de motor winnen — weiger, geen boeking."""
        _patch_client(monkeypatch, FakeVerkoopClient())
        eerste = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, eerste) == "geboekt"
        tweede = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(huurder="Ander Huurder B.V."),
            bestandsnaam="vastly-verkoop-2.xml",
        )
        assert _status(admin_engine, tweede) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, tweede)
        assert "harde checks blokkeren" in reden
        assert "duplicaat" in reden

    def test_mogelijk_duplicaat_signaal_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        _patch_client(monkeypatch, FakeVerkoopClient())
        _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        # Identieke bestandsinhoud → sha256-signaal; de weigering komt vóór alle checks.
        tweede = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(), bestandsnaam="kopie.xml",
        )
        assert _status(admin_engine, tweede) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, tweede)
        assert "mogelijk-duplicaat" in reden

    def test_volumerem_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        # De checks waren groen (de motor zette klaar_om_te_boeken), de volumerem blokkeerde
        # daarná — het document blijft zichtbaar mensenwerk, niet geboekt.
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "limiet" in reden.lower()

    def test_boeken_toggle_uit_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        # Bewust géén boeken_aan-fixture: de boeken-failsafe wint van de autoboek-opt-in.
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        # Zelfde patroon als de volumerem: checks groen → klaar_om_te_boeken, toggle blokkeert.
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "Boeken staat uit" in reden

    def test_is_vastgoed_teruggedraaid_weigert_fail_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = false WHERE id = :id"),
                {"id": vastgoed_administratie},
            )
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, document_id)
        assert "is_vastgoed" in reden

    def test_opgeslagen_voorstel_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        """Her-verwerking van een document waar een mens al aan zat: de mens is eigenaar van
        het voorstel — het autoboek-pad blijft er vanaf (weiger, geauditeerd)."""
        _patch_client(monkeypatch, FakeVerkoopClient())
        document_id = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=vastgoed_administratie, document_id=document_id
        )
        voorstel_service.sla_verkoop_voorstel_op(
            administratie_id=vastgoed_administratie,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            debiteur_naam=prefill.debiteur_naam,
            factuurnummer=prefill.factuurnummer,
            factuurdatum=prefill.factuurdatum,
            totaalbedrag_incl=prefill.totaalbedrag_incl,
            regels=[
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving, netto_bedrag=r.netto_bedrag, btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code, ledger_id=r.ledger_id, taxrate_id=r.taxrate_id,
                )
                for r in prefill.regels
            ],
        )
        beheer_service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=vastgoed_administratie, ingeschakeld=True
        )
        besluit = verkoop_autoboeken.probeer_verkoop_autoboeken_na_intake(
            administratie_id=vastgoed_administratie, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert "opgeslagen voorstel" in besluit.reden
        assert _status(admin_engine, document_id) == "te_controleren"

    def test_creditnota_zonder_geboekt_origineel_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        _patch_client(monkeypatch, FakeVerkoopClient())
        credit = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_creditnote_ubl(), bestandsnaam="vastly-credit.xml",
        )
        assert _status(admin_engine, credit) == "te_controleren"
        [reden] = _weiger_redenen(admin_engine, credit)
        assert "creditnota_herleiding" in reden

    def test_creditnota_met_geboekt_origineel_boekt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
        vastgoed_administratie: uuid.UUID,
        optin_aan: None,
    ) -> None:
        """Een creditnota is geen aparte weigergrond: herleiding-check groen (origineel
        automatisch geboekt) → de tegenboeking boekt automatisch, herkenbaar als creditnota."""
        _patch_client(monkeypatch, FakeVerkoopClient())
        origineel = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert _status(admin_engine, origineel) == "geboekt"
        credit = _upload(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker,
            opslag=opslag, inhoud=bouw_vastly_creditnote_ubl(), bestandsnaam="vastly-credit.xml",
        )
        assert _status(admin_engine, credit) == "geboekt"
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": credit},
            ).scalar_one()
        assert detail["is_creditnota"] is True
        assert detail["automatisch_geboekt"] is True
