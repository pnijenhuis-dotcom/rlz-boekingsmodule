"""Meerwerk-statusmachine (fase 1): gemeld → goedgekeurd-nog-doorbelasten → doorbelast /
afgewezen-met-verplichte-reden; prijs door een MENS bevestigd (contract-toets = voorstel);
module-recht 'Meerwerk & urenstaten' server-side; 2-weken-bewakingssignaal."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.db.models import GebruikerModuleRol
from app.uren import service
from tests.uren.conftest import maak_gebruiker


def _meld(administratie_id, project_id, uitvoerder, **kw):
    args = dict(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=uitvoerder,
        omschrijving="Extra trapsteiger achterzijde",
        aantal=Decimal("84"),
        eenheid="m2",
        datum_uitgevoerd=date(2026, 8, 12),
        in_opdracht_van="J. Timmers (BAM)",
    )
    args.update(kw)
    return service.meld_meerwerk(**args)


class TestMelden:
    def test_uitvoerder_meldt(self, administratie_id, project_id, gekoppelde_uitvoerder):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        assert melding.status == "gemeld"
        assert melding.gemeld_door_naam == "Ben v. Dijk"
        assert melding.prijs_per_eenheid is None  # melden is zonder prijzen

    def test_omschrijving_en_aantal_verplicht(self, administratie_id, project_id, gekoppelde_uitvoerder):
        with pytest.raises(service.OngeldigeInvoer, match="Omschrijving"):
            _meld(administratie_id, project_id, gekoppelde_uitvoerder, omschrijving="  ")
        with pytest.raises(service.OngeldigeInvoer, match="Aantal"):
            _meld(administratie_id, project_id, gekoppelde_uitvoerder, aantal=Decimal("0"))
        with pytest.raises(service.OngeldigeInvoer, match="eenheid"):
            _meld(administratie_id, project_id, gekoppelde_uitvoerder, eenheid="km")

    def test_alleen_gekoppelde_uitvoerder(self, administratie_id, project_id, uitvoerder, gekoppelde_zzper):
        with pytest.raises(service.GeenToegang, match="niet aan dit project gekoppeld"):
            _meld(administratie_id, project_id, uitvoerder)
        with pytest.raises(service.GeenToegang, match="Alleen een uitvoerder"):
            _meld(administratie_id, project_id, gekoppelde_zzper)

    def test_foto_wordt_opgeslagen(self, administratie_id, project_id, gekoppelde_uitvoerder, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path))
        melding = _meld(
            administratie_id,
            project_id,
            gekoppelde_uitvoerder,
            foto=("trapsteiger.jpg", "image/jpeg", b"\xff\xd8fake-jpeg"),
        )
        assert melding.heeft_foto is True
        assert melding.foto_bestandsnaam == "trapsteiger.jpg"


class TestBeoordelen:
    def test_beheerder_keurt_goed_met_bevestigde_prijs(
        self, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        goed = service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            prijs_per_eenheid=Decimal("9.20"),
            bedrag=Decimal("772.80"),
        )
        assert goed.status == "goedgekeurd"
        assert goed.bedrag == Decimal("772.80")
        herhaald = service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            prijs_per_eenheid=Decimal("9.20"),
            bedrag=Decimal("772.80"),
        )
        assert herhaald.beoordeeld_op == goed.beoordeeld_op  # idempotent

    def test_module_recht_vereist_voor_kantoormedewerker(
        self, admin_engine: Engine, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        with pytest.raises(service.GeenToegang, match="module-recht"):
            service.keur_meerwerk_goed(
                administratie_id=administratie_id,
                meerwerk_id=melding.id,
                actor_id=medewerker,
                prijs_per_eenheid=Decimal("1"),
                bedrag=Decimal("1"),
            )
        # recht toekennen (zoals het fase-3-beheer-endpoint dat doet: Beheerder-actor, RLS +
        # audit-trigger uit migratie 0034 bijten mee) → nu mag het wel
        with scoped_session(None, actor_id=beheerder_id) as session:
            session.add(GebruikerModuleRol(gebruiker_id=medewerker, module="boekhouding", rol="meerwerk_urenstaten"))
        goed = service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=medewerker,
            prijs_per_eenheid=Decimal("9.20"),
            bedrag=Decimal("772.80"),
        )
        assert goed.status == "goedgekeurd"

    def test_uitvoerder_beoordeelt_nooit(self, administratie_id, project_id, gekoppelde_uitvoerder):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        with pytest.raises(service.GeenToegang):
            service.keur_meerwerk_goed(
                administratie_id=administratie_id,
                meerwerk_id=melding.id,
                actor_id=gekoppelde_uitvoerder,
                prijs_per_eenheid=Decimal("1"),
                bedrag=Decimal("1"),
            )

    def test_afwijzen_vereist_reden_en_blijft_zichtbaar(
        self, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        with pytest.raises(service.RedenVerplicht):
            service.wijs_meerwerk_af(
                administratie_id=administratie_id, meerwerk_id=melding.id, actor_id=beheerder_id, reden=""
            )
        afgewezen = service.wijs_meerwerk_af(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            reden="Eigen rekening — niet vooraf gemeld",
        )
        assert afgewezen.status == "afgewezen"
        assert afgewezen.afwijs_reden == "Eigen rekening — niet vooraf gemeld"
        # terminaal: goedkeuren kan niet meer
        with pytest.raises(service.OngeldigeOvergang):
            service.keur_meerwerk_goed(
                administratie_id=administratie_id,
                meerwerk_id=melding.id,
                actor_id=beheerder_id,
                prijs_per_eenheid=Decimal("1"),
                bedrag=Decimal("1"),
            )

    def test_doorbelast_vereist_referentie_en_goedgekeurde_status(
        self, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        with pytest.raises(service.OngeldigeOvergang):
            service.markeer_doorbelast(
                administratie_id=administratie_id,
                meerwerk_id=melding.id,
                actor_id=beheerder_id,
                verkoopfactuur_referentie="VF-2608",
            )
        service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            prijs_per_eenheid=Decimal("9.20"),
            bedrag=Decimal("772.80"),
        )
        with pytest.raises(service.OngeldigeInvoer, match="referentie"):
            service.markeer_doorbelast(
                administratie_id=administratie_id,
                meerwerk_id=melding.id,
                actor_id=beheerder_id,
                verkoopfactuur_referentie=" ",
            )
        doorbelast = service.markeer_doorbelast(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            verkoopfactuur_referentie="VF-2608",
        )
        assert doorbelast.status == "doorbelast"
        assert doorbelast.verkoopfactuur_referentie == "VF-2608"


class TestVraagEnToets:
    def test_vraag_stellen_en_beantwoorden(
        self, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        met_vraag = service.stel_vraag(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            tekst="Wie gaf hiervoor opdracht op de bouw?",
        )
        assert met_vraag.status == "gemeld"  # vraag verandert de status niet
        beantwoord = service.beantwoord_vraag(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=gekoppelde_uitvoerder,
            tekst="J. Timmers, ter plekke op 12 aug",
        )
        assert beantwoord.vraag_antwoord == "J. Timmers, ter plekke op 12 aug"

    def test_contract_toets_matcht_op_eenheid(
        self, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            from app.uren.models import ProjectStaffel

            session.add(
                ProjectStaffel(
                    administratie_id=administratie_id,
                    project_id=project_id,
                    omschrijving="Trapsteigers",
                    eenheid="m2",
                    prijs_per_eenheid=Decimal("9.20"),
                    bron="§ 4.2",
                    aangemaakt_door=beheerder_id,
                )
            )
        voorstel = service.contract_toets(administratie_id=administratie_id, project_id=project_id, eenheid="m2")
        assert len(voorstel) == 1
        assert voorstel[0].prijs_per_eenheid == Decimal("9.20")
        assert voorstel[0].bron == "§ 4.2"
        assert service.contract_toets(administratie_id=administratie_id, project_id=project_id, eenheid="manuren") == []

    def test_bewaking_niet_doorbelast_na_twee_weken(
        self, admin_engine: Engine, administratie_id, project_id, gekoppelde_uitvoerder, beheerder_id
    ):
        melding = _meld(administratie_id, project_id, gekoppelde_uitvoerder)
        service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            prijs_per_eenheid=Decimal("9.20"),
            bedrag=Decimal("772.80"),
        )
        assert service.bewaking_niet_doorbelast(administratie_id=administratie_id) == []
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.meerwerk SET beoordeeld_op = now() - interval '15 days' WHERE id = :id"
                ),
                {"id": melding.id},
            )
        signaal = service.bewaking_niet_doorbelast(administratie_id=administratie_id)
        assert [m.id for m in signaal] == [melding.id]
        # doorbelasten sluit de bewaking
        service.markeer_doorbelast(
            administratie_id=administratie_id,
            meerwerk_id=melding.id,
            actor_id=beheerder_id,
            verkoopfactuur_referentie="VF-2608",
        )
        assert service.bewaking_niet_doorbelast(administratie_id=administratie_id) == []
