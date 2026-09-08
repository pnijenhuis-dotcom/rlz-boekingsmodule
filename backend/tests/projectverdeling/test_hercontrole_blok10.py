"""Blok 10 herstelrun "Basis eerst" 08-09 — hercontrole signaleert fout (Universal, 5 valse signalen op de boekdag).

Wortel (cloud read-only): `hercontrole_verdeling` werd bij het BOEKEN als JSON `null` geschreven (JSONB zonder
`none_as_null`) → `IS NOT NULL` waar → rij-chip + Inzicht › Projectverdeling toonden "0 % afwijking" met een lege
nieuwe verdeling. Hier: (1) een vers geboekte verdeling is nooit een signaal (SQL NULL, lezers toetsen op array);
(2) een historische JSON-null-rij is óók geen signaal; (3) ontbrekende omzet = bevinding mét actie i.p.v. herverdeling;
(4) het document-DTO draagt de bevinding."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.projectverdeling import hercontrole, service
from tests.projectverdeling.conftest import na_boekmaand
from tests.projectverdeling.test_service import geboekt_met_verdeling  # noqa: F401 — fixture her-exporteren


def _typ(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str | None, str | None, str | None]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT jsonb_typeof(hercontrole_verdeling), hercontrole_verdeling::text, hercontrole_bevinding "
                "FROM boekhouding.projectverdeling WHERE document_id = :id"
            ),
            {"id": document_id},
        ).one()


def _beheerder(admin_engine: Engine) -> uuid.UUID:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT id FROM platform.gebruiker WHERE rol = 'beheerder' LIMIT 1")).scalar_one()


class TestJsonNullIsGeenSignaal:
    def test_vers_geboekt_is_sql_null_en_geen_signaal(
        self,
        geboekt_met_verdeling,  # noqa: F811
        administratie_id,
        admin_engine,
    ):
        document_id, _ = geboekt_met_verdeling
        typ, tekst, bevinding = _typ(admin_engine, document_id)
        assert (typ, tekst, bevinding) == (None, None, None)  # SQL NULL — niet de string 'null'
        with scoped_session(administratie_id) as session:
            assert service.afwijkingen_per_document(session, [document_id]) == {}
        lijst = service.hercontrole_signalen(actor_id=_beheerder(admin_engine), rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 0 and lijst.tellers.signalen == 0
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert voorstel.projectverdeling is not None and voorstel.projectverdeling.hercontrole is None

    def test_historische_json_null_rij_is_geen_signaal(
        self,
        geboekt_met_verdeling,  # noqa: F811
        administratie_id,
        admin_engine,
    ):
        """Productie-stand 08-09 (rijen van vóór de fix): JSON null in de kolom mag nooit meer als signaal tellen."""
        document_id, _ = geboekt_met_verdeling
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.projectverdeling SET hercontrole_verdeling = 'null'::jsonb "
                    "WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        assert _typ(admin_engine, document_id)[0] == "null"
        with scoped_session(administratie_id) as session:
            assert service.afwijkingen_per_document(session, [document_id]) == {}
        lijst = service.hercontrole_signalen(actor_id=_beheerder(admin_engine), rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 0
        # De eerstvolgende ronde normaliseert de rij (ongewijzigde omzet → 0 %, SQL NULL).
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=na_boekmaand(2))
        assert tellers["herrekend"] == 1 and tellers["signalen"] == 0
        assert _typ(admin_engine, document_id) == (None, None, None)


class TestOmzetOntbreekt:
    @pytest.fixture
    def zonder_juli_omzet(self, geboekt_met_verdeling, administratie_id, admin_engine):  # noqa: F811
        document_id, _ = geboekt_met_verdeling
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM boekhouding.project_regel_cache WHERE administratie_id = :aid "
                    "AND datum >= '2026-07-01' AND datum < '2026-08-01'"
                ),
                {"aid": administratie_id},
            )
        return document_id

    def test_bevinding_met_actie_in_lijst_en_document(self, zonder_juli_omzet, administratie_id, admin_engine):
        document_id = zonder_juli_omzet
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=na_boekmaand(2))
        assert tellers["signalen"] == 0 and tellers["herrekend"] == 0 and tellers["omzet_ontbreekt"] == 1
        typ, _, bevinding = _typ(admin_engine, document_id)
        assert typ is None and bevinding == "omzet_ontbreekt"
        # Lijst-chip (afwijking) blijft leeg; de kantoorbrede lijst toont de bevinding mét tekst, bovenaan.
        with scoped_session(administratie_id) as session:
            assert service.afwijkingen_per_document(session, [document_id]) == {}
        lijst = service.hercontrole_signalen(actor_id=_beheerder(admin_engine), rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 1
        rij = lijst.rijen[0]
        assert rij.soort == service.SOORT_OMZET_ONTBREEKT
        assert rij.bevinding == "omzetcijfers ontbreken voor juli 2026"
        assert rij.delen_nieuw == []
        # Document-DTO: bevinding zichtbaar, geen signaal → herverdelen geblokkeerd (bestaande 422-poort).
        voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        hc = voorstel.projectverdeling.hercontrole
        assert hc is not None and hc.signaal is False and hc.bevinding == "omzet_ontbreekt"
        assert hc.bevinding_tekst == "omzetcijfers ontbreken voor juli 2026"
        with pytest.raises(service.ProjectverdelingServiceFout, match="geen hercontrole-afwijking"):
            service.herverdelen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=_beheerder(admin_engine),
                reden="test",
            )
        # Tijdlijn + audit: één keer, idempotent bij een tweede ronde.
        with admin_engine.connect() as conn:
            tijdlijn = conn.execute(
                text(
                    "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND detail ? 'projectverdeling_omzet_ontbreekt'"
                ),
                {"id": document_id},
            ).scalar_one()
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE record_id = :id "
                    "AND actie = 'projectverdeling_omzet_ontbreekt'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert (tijdlijn, audit) == (1, 1)
        hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=na_boekmaand(2), forceer=True)
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                        "AND detail ? 'projectverdeling_omzet_ontbreekt'"
                    ),
                    {"id": document_id},
                ).scalar_one()
                == 1
            )

    def test_bevinding_vervalt_zodra_er_cijfers_zijn(
        self, zonder_juli_omzet, administratie_id, projecten, admin_engine
    ):
        from datetime import date

        from tests.projectverdeling.conftest import seed_omzet

        document_id = zonder_juli_omzet
        hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=na_boekmaand(2))
        assert _typ(admin_engine, document_id)[2] == "omzet_ontbreekt"
        seed_omzet(admin_engine, administratie_id, projecten["eindhoven"], "6000.00", date(2026, 7, 3))
        seed_omzet(admin_engine, administratie_id, projecten["tilburg"], "2500.00", date(2026, 7, 15))
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1500.00", date(2026, 7, 31))
        tellers = hercontrole.herbereken_administratie(
            administratie_id=administratie_id, vandaag=na_boekmaand(2), forceer=True
        )
        assert tellers["herrekend"] == 1 and tellers["omzet_ontbreekt"] == 0 and tellers["signalen"] == 0
        assert _typ(admin_engine, document_id) == (None, None, None)
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM platform.audit_event WHERE record_id = :id "
                        "AND actie = 'projectverdeling_omzet_ontbreekt_vervallen'"
                    ),
                    {"id": document_id},
                ).scalar_one()
                == 1
            )
