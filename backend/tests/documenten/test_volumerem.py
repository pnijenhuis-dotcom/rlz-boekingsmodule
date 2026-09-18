"""Volumerem — alleen automatisch (SPOED Peter 18-09, "Dagelijkse limiet van 20 boekingen bereikt" bij handmatig
boeken van 180 BLOW-bonnen). Eén helper `app/documenten/volumerem.py` voor álle boekpaden:
20/dag = alleen automatische boekingen; handmatig én ná klant-akkoord = de 500-noodrem; élke melding noemt rem,
teller en handeling."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken, boekvoorstel, service, volumerem
from app.documenten.storage import LokaleBestandsopslag
from app.reconciliatie import automatiseringen as auto
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_boeken import _regel


class TestPuur:
    def test_herkomst_nooit_geraden(self) -> None:
        mens = uuid.uuid4()
        assert volumerem.bepaal_herkomst(actor_id=mens) == volumerem.MENS
        assert volumerem.bepaal_herkomst(actor_id=SYSTEEM_ACTOR_ID) == volumerem.AUTOMATISCH
        assert (
            volumerem.bepaal_herkomst(actor_id=mens, overgang_detail={"automatisch_geboekt": True})
            == volumerem.AUTOMATISCH
        )
        assert volumerem.bepaal_herkomst(actor_id=mens, na_klant_akkoord=True) == volumerem.NA_KLANT_AKKOORD
        # klant-akkoord wint van de markering (de gang ná akkoord is een mens-gang, punt 23)
        assert (
            volumerem.bepaal_herkomst(actor_id=SYSTEEM_ACTOR_ID, na_klant_akkoord=True) == volumerem.NA_KLANT_AKKOORD
        )

    def test_limiet_per_herkomst(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 20)
        monkeypatch.setattr(settings, "max_handmatige_boekingen_per_dag_per_administratie", 500)
        assert volumerem.limiet_voor(volumerem.AUTOMATISCH) == 20
        assert volumerem.limiet_voor(volumerem.MENS) == 500
        assert volumerem.limiet_voor(volumerem.NA_KLANT_AKKOORD) == 500

    def test_melding_noemt_rem_teller_en_handeling(self) -> None:
        m = volumerem.melding(herkomst=volumerem.AUTOMATISCH, teller=20, limiet=20)
        assert "20 van 20 automatische boekingen" in m and "handmatig boeken kan gewoon door" in m
        n = volumerem.melding(herkomst=volumerem.MENS, teller=500, limiet=500)
        assert n.startswith("Noodrem: 500 van 500 handmatige boekingen") and "Beheerder" in n
        a = volumerem.melding(herkomst=volumerem.NA_KLANT_AKKOORD, teller=3, limiet=500)
        assert a.startswith("Noodrem ná klant-akkoord: 3 van 500")

    def test_reconciliatie_herkent_beide_remmen(self) -> None:
        """De reconciliatie classificeert op tekst: automatisch = VOLUMEREM (actiemail-categorie), de handmatige
        noodrem = NOODREM (LET-OP)."""
        assert (
            auto.categoriseer_reden(volumerem.melding(herkomst=volumerem.AUTOMATISCH, teller=20, limiet=20))
            == auto.VOLUMEREM
        )
        assert (
            auto.categoriseer_reden(volumerem.melding(herkomst=volumerem.MENS, teller=500, limiet=500))
            == auto.NOODREM
        )

    def test_toets_met_extra_telt_de_gang_mee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 2)
        # 1 gedaan + 1 in deze gang = 2 → mag (niet groter dan de limiet)
        volumerem.toets(None, uuid.uuid4(), herkomst=volumerem.AUTOMATISCH, teller=1, extra=1)
        with pytest.raises(volumerem.VolumeremBereikt, match="deze gang meegeteld"):
            volumerem.toets(None, uuid.uuid4(), herkomst=volumerem.AUTOMATISCH, teller=1, extra=2)


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


def _nieuw_klaar_document(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{uuid.uuid4()}.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


def _tellers(administratie_id: uuid.UUID) -> tuple[int, int]:
    with scoped_session(administratie_id) as session:
        return (
            volumerem.documentboekingen_vandaag(
                session, administratie_id=administratie_id, herkomst=volumerem.AUTOMATISCH
            ),
            volumerem.documentboekingen_vandaag(session, administratie_id=administratie_id, herkomst=volumerem.MENS),
        )


class TestBoekpad:
    def test_automatische_rem_vol_maar_handmatig_gaat_door(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Peter's casus: de automatische rem staat op 0 (= vol) — een mens op de knop boekt gewoon door, de
        automatische poging krijgt de melding mét 'handmatig boeken kan gewoon door'."""
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        handmatig = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=handmatig, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status.value == "geboekt"

        automatisch = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        with pytest.raises(boeken.VolumeremBereikt) as exc:
            boeken.boek_document(
                administratie_id=administratie_id,
                document_id=automatisch,
                actor_id=SYSTEEM_ACTOR_ID,
                extra_overgang_detail={"automatisch_geboekt": True, "bron": "test"},
            )
        assert "0 van 0 automatische boekingen" in str(exc.value)
        assert "handmatig boeken kan gewoon door" in str(exc.value)
        # de fout is óók de helper-basisfout (één contract voor alle paden)
        assert isinstance(exc.value, volumerem.VolumeremBereikt)

    def test_teller_splitst_op_herkomst_en_telt_alleen_echte_overgangen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        assert _tellers(administratie_id) == (0, 0)

        mens_doc = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        boeken.boek_document(administratie_id=administratie_id, document_id=mens_doc, actor_id=gescoopte_gebruiker)
        assert _tellers(administratie_id) == (0, 1)

        auto_doc = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        boeken.boek_document(
            administratie_id=administratie_id,
            document_id=auto_doc,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail={"automatisch_geboekt": True, "bron": "test"},
        )
        assert _tellers(administratie_id) == (1, 1)

        # Een tijdlijn-notitie geboekt → geboekt (bv. webhook-notitie) telt in géén van beide (bugfix punt 23 blijft).
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.document_gebeurtenis (id, document_id, van_status, naar_status, actor_id, detail)"
                    " VALUES (:id, :doc, 'geboekt', 'geboekt', :actor, '{\"notitie\": true}'::jsonb)"
                ),
                {"id": uuid.uuid4(), "doc": mens_doc, "actor": gescoopte_gebruiker},
            )
        assert _tellers(administratie_id) == (1, 1)

    def test_handmatige_noodrem_bijt_zichtbaar(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "max_handmatige_boekingen_per_dag_per_administratie", 1)
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        eerste = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        boeken.boek_document(administratie_id=administratie_id, document_id=eerste, actor_id=gescoopte_gebruiker)
        tweede = _nieuw_klaar_document(administratie_id, gescoopte_gebruiker, opslag)
        with pytest.raises(boeken.VolumeremBereikt, match="Noodrem: 1 van 1 handmatige boekingen"):
            boeken.boek_document(administratie_id=administratie_id, document_id=tweede, actor_id=gescoopte_gebruiker)
        assert len(fake_client.puts) == 1

    def test_vervallen_setting_wordt_niet_meer_gelezen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regel 3 (eenvoudigste vorm): ná klant-akkoord = dezelfde noodrem als handmatig; de oude 200-setting
        blijft bestaan voor oude env-sets maar stuurt niets meer."""
        monkeypatch.setattr(settings, "max_boekingen_na_klant_akkoord_per_dag_per_administratie", 1)
        monkeypatch.setattr(settings, "max_handmatige_boekingen_per_dag_per_administratie", 7)
        assert volumerem.limiet_voor(volumerem.NA_KLANT_AKKOORD) == 7
