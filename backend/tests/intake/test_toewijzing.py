"""Toewijzingsregels: tenaamstelling leidend, afzender hint, nooit auto-toewijzen bij twijfel —
en het geheugen leert van handmatige toewijzingen."""

from __future__ import annotations

import uuid

from app.db.session import scoped_session
from app.intake.toewijzing import bepaal_toewijzing, leer_toewijzing, normaliseer_partijnaam


class TestNormaliseerPartijnaam:
    def test_rechtsvorm_is_opmaak(self) -> None:
        assert normaliseer_partijnaam("BLOW B.V.") == normaliseer_partijnaam("Blow bv")

    def test_holding_blijft_onderscheidend(self) -> None:
        # Mockup-casus: tenaamstelling "BLOW Holding" matcht "BLOW B.V." níét.
        assert normaliseer_partijnaam("BLOW Holding") != normaliseer_partijnaam("BLOW B.V.")


class TestBepaalToewijzing:
    def test_tenaamstelling_matcht_administratieregister(
        self, administratie_heet_blow: uuid.UUID
    ) -> None:
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling="Blow bv", afzender="x@y.nl")
        assert besluit.administratie_id == administratie_heet_blow
        assert besluit.bron == "tenaamstelling_register"

    def test_geen_match_geeft_verzamelbak_zonder_suggestie(
        self, administratie_heet_blow: uuid.UUID
    ) -> None:
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling="Onbekend BV", afzender=None)
        assert besluit.administratie_id is None
        assert besluit.suggestie_administratie_id is None

    def test_geleerde_tenaamstelling_regel_wint(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(
                session,
                administratie_id=administratie_heet_blow,
                actor_id=gescoopte_gebruiker,
                tenaamstelling="BLOW Holding",
                afzender=None,
            )
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling="BLOW Holding", afzender=None)
        assert besluit.administratie_id == administratie_heet_blow
        assert besluit.bron == "tenaamstelling_regel"

    def test_afzender_regel_wijst_toe_zonder_tenaamstelling(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(
                session,
                administratie_id=administratie_heet_blow,
                actor_id=gescoopte_gebruiker,
                tenaamstelling=None,
                afzender="info@blow.nl",
            )
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling=None, afzender="info@blow.nl")
        assert besluit.administratie_id == administratie_heet_blow
        assert besluit.bron == "afzender_regel"

    def test_afzender_regel_bij_onbekende_tenaamstelling_is_twijfel(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        """Tegenstrijdig signaal: afzender bekend, maar de gelezen tenaamstelling matcht niets —
        verzamelbak mét de afzender-administratie als suggestie, nooit auto-toewijzen."""
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(
                session,
                administratie_id=administratie_heet_blow,
                actor_id=gescoopte_gebruiker,
                tenaamstelling=None,
                afzender="info@blow.nl",
            )
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling="BLOW Holding", afzender="info@blow.nl")
        assert besluit.administratie_id is None
        assert besluit.suggestie_administratie_id == administratie_heet_blow
        assert besluit.suggestie_bron == "afzender_regel_maar_onbekende_tenaamstelling"

    def test_herleren_deactiveert_oude_regel(
        self,
        administratie_heet_blow: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine,
    ) -> None:
        from sqlalchemy import text

        tweede_admin = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Tweede', :rlz)"),
                {"id": tweede_admin, "rlz": f"rlz-{tweede_admin}"},
            )
        for doel in (administratie_heet_blow, tweede_admin):
            with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
                leer_toewijzing(
                    session,
                    administratie_id=doel,
                    actor_id=gescoopte_gebruiker,
                    tenaamstelling="Dubbelzinnig BV",
                    afzender=None,
                )
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling="Dubbelzinnig BV", afzender=None)
        assert besluit.administratie_id == tweede_admin


class TestNoOpSemantiek:
    """Vastly-port (g), 2026-08-07 — "veld/waarde aanwezig ≠ gewijzigd" gepind: dezelfde
    handmatige toewijzing nogmaals vastleggen is een no-op (geen extra regelrijen, geen extra
    audit_event). NB de beheer-toggles auditen bewust wél elke herbevestiging — dat is een
    gedocumenteerde uitzondering (app/beheer/service.py), geen gemiste toepassing."""

    def test_zelfde_toewijzing_opnieuw_leren_is_no_op(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine
    ) -> None:
        from sqlalchemy import text

        for _ in range(2):
            with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
                leer_toewijzing(
                    session,
                    administratie_id=administratie_heet_blow,
                    actor_id=gescoopte_gebruiker,
                    tenaamstelling="BLOW Holding",
                    afzender="info@blow.nl",
                )
        with admin_engine.connect() as conn:
            regels = conn.execute(
                text("SELECT count(*) FROM boekhouding.toewijzing_regel WHERE actief")
            ).scalar_one()
            audits = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE tabel = 'toewijzing_regel'")
            ).scalar_one()
        assert regels == 2  # één tenaamstelling-regel + één afzender-regel, géén duplicaten
        assert audits == 2  # alleen de eerste keer per regel — herbevestigen is geen handeling
