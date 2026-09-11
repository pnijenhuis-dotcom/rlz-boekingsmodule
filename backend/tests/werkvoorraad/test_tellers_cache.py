"""Blok 6 run 11-09 — de tellers-cache van de klantenlijst: fail-safe (ontbrekende rij → direct tellen + aanmaken),
incrementeel bij statusovergang en aanmaak (zelfde transactie), vragen-hook, herrekenen/dry-run, de reconciliatie-
LET-OP
`werkvoorraad_tellers`, het CLI-commando en de route (200 voor een niet-Beheerder mét scope, `spiegel_taken` in de
DTO)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.db.session import scoped_session
from app.documenten import service, vragen
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.reconciliatie import automatiseringen
from app.security.tokens import create_access_token
from app.werkvoorraad import tellers

client = TestClient(app)


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=f"%PDF-1.4 {naam}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _cache(admin_engine: Engine, administratie_id: uuid.UUID) -> dict[str, int]:
    with admin_engine.begin() as conn:
        rijen = conn.execute(
            text("SELECT teller, waarde FROM boekhouding.werkvoorraad_teller_cache WHERE administratie_id = :a"),
            {"a": administratie_id},
        ).all()
    return {t: w for t, w in rijen}


class TestFailSafe:
    def test_zonder_cache_wordt_direct_geteld_en_de_rij_aangemaakt(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        _upload(administratie_id, gescoopte_gebruiker, opslag, "a.pdf")
        _upload(administratie_id, gescoopte_gebruiker, opslag, "b.pdf")
        assert _cache(admin_engine, administratie_id) == {}  # incrementeel zonder rij = bewust niets
        [klant] = service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "A")], actor_id=gescoopte_gebruiker
        )
        assert klant.te_controleren == 2
        cache = _cache(admin_engine, administratie_id)
        assert set(cache) == set(tellers.ALLE_TELLERS)
        assert cache[tellers.TE_CONTROLEREN] == 2

    def test_halve_cache_telt_als_ontbrekend(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.werkvoorraad_teller_cache (administratie_id, teller, waarde) "
                    "VALUES (:a, 'te_controleren', 99)"
                ),
                {"a": administratie_id},
            )
        [klant] = service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "A")], actor_id=gescoopte_gebruiker
        )
        assert klant.te_controleren == 0  # de halve cache is overschreven door de telling
        assert _cache(admin_engine, administratie_id)[tellers.TE_CONTROLEREN] == 0


class TestIncrementeel:
    def test_aanmaak_en_statusovergang_verschuiven_de_buckets(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        tellers.herreken(administratie_id)  # cache bestaat (zoals ná de nachtelijke run)
        assert _cache(admin_engine, administratie_id)[tellers.TE_CONTROLEREN] == 0
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.pdf")
        assert _cache(admin_engine, administratie_id)[tellers.TE_CONTROLEREN] == 1
        service.verwijder_document(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker, reden="test"
        )
        cache = _cache(admin_engine, administratie_id)
        assert cache[tellers.TE_CONTROLEREN] == 0
        # en de cache is exact de telling
        assert tellers.herreken(administratie_id, dry_run=True).afwijkingen == []

    def test_vraag_stellen_en_afhandelen_verversen_de_vragen_teller(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        tellers.herreken(administratie_id)
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.pdf")
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=doc,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Welk project?",
        )
        cache = _cache(admin_engine, administratie_id)
        assert cache[tellers.VRAGEN] == 1
        assert cache[tellers.TE_CONTROLEREN] == 0  # vraag_open telt in geen status-bucket (ongewijzigde definitie)
        vragen.handel_vraag_af(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker)
        cache = _cache(admin_engine, administratie_id)
        assert cache[tellers.VRAGEN] == 0
        assert cache[tellers.TE_CONTROLEREN] == 1  # terug naar de herkomst-status
        assert tellers.herreken(administratie_id, dry_run=True).afwijkingen == []

    def test_nooit_onder_nul(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        tellers.herreken(administratie_id)
        with scoped_session(administratie_id) as session:
            tellers._verschuif(session, administratie_id, tellers.TE_CONTROLEREN, -1)
        assert _cache(admin_engine, administratie_id)[tellers.TE_CONTROLEREN] == 0


class TestHerrekenen:
    def test_dry_run_meldt_afwijking_en_schrijft_niet_herreken_herstelt(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        tellers.herreken(administratie_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.werkvoorraad_teller_cache SET waarde = 7 "
                    "WHERE administratie_id = :a AND teller = 'afgewezen'"
                ),
                {"a": administratie_id},
            )
        rapport = tellers.herreken_alle(administratie_ids=[administratie_id], dry_run=True)
        assert [(a.teller, a.cache, a.telling) for a in rapport.afwijkingen] == [("afgewezen", 7, 0)]
        assert rapport.administraties_met_afwijking == 1
        assert _cache(admin_engine, administratie_id)[tellers.AFGEWEZEN] == 7  # dry-run schrijft niet
        echt = tellers.herreken_alle(administratie_ids=[administratie_id])
        assert len(echt.afwijkingen) == 1
        assert _cache(admin_engine, administratie_id)[tellers.AFGEWEZEN] == 0
        assert tellers.herreken_alle(administratie_ids=[administratie_id], dry_run=True).afwijkingen == []

    def test_ontbrekende_cache_is_geen_afwijking_halve_cache_wel(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Nog nooit gelezen: geen enkele rij → ontbrekend, géén afwijking (de fail-safe vult hem; geen LET-OP).
        rapport = tellers.herreken_alle(administratie_ids=[administratie_id], dry_run=True)
        assert (rapport.ontbrekend, rapport.afwijkingen) == (1, [])
        # Halve cache: één rij aanwezig → de ontbrekende tellers zijn wél drift (cache=None).
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.werkvoorraad_teller_cache (administratie_id, teller, waarde) "
                    "VALUES (:a, 'te_controleren', 0)"
                ),
                {"a": administratie_id},
            )
        rapport = tellers.herreken_alle(administratie_ids=[administratie_id], dry_run=True)
        assert rapport.ontbrekend == 0
        assert len(rapport.afwijkingen) == len(tellers.ALLE_TELLERS) - 1
        assert all(a.cache is None for a in rapport.afwijkingen)

    def test_cli_dry_run_exit_1_bij_afwijking_en_0_na_herrekenen(
        self, administratie_id: uuid.UUID, admin_engine: Engine, capsys
    ) -> None:  # noqa: ANN001
        assert cli.main(["werkvoorraad-tellers-herrekenen", "--administratie", str(administratie_id)]) == 0
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.werkvoorraad_teller_cache SET waarde = 3 "
                    "WHERE administratie_id = :a AND teller = 'vragen'"
                ),
                {"a": administratie_id},
            )
        assert cli.main(["werkvoorraad-tellers-herrekenen", "--dry-run", "--administratie", str(administratie_id)]) == 1
        uit = capsys.readouterr().out
        assert "AFWIJKING" in uit and "vragen cache=3 telling=0" in uit and "dry-run, niets geschreven" in uit
        assert cli.main(["werkvoorraad-tellers-herrekenen", "--administratie", str(administratie_id)]) == 0
        assert cli.main(["werkvoorraad-tellers-herrekenen", "--dry-run", "--administratie", str(administratie_id)]) == 0
        assert cli.main(["werkvoorraad-tellers-herrekenen", "--administratie", "geen-uuid"]) == 1


class TestReconciliatieBevinding:
    def test_geen_afwijking_geen_signaal(self) -> None:
        from datetime import UTC, datetime

        rapport = tellers.HerrekenRapport(dry_run=True, administraties=3)
        assert automatiseringen.werkvoorraad_tellers_bevinding(nu=datetime.now(UTC), rapport=rapport) is None

    def test_afwijking_is_platformbrede_let_op_met_voorbeelden(self) -> None:
        from datetime import UTC, datetime

        aid = uuid.uuid4()
        rapport = tellers.HerrekenRapport(dry_run=True, administraties=3)
        rapport.afwijkingen = [
            tellers.Afwijking(administratie_id=aid, naam="Baard B.V.", teller="vragen", cache=3, telling=1),
            tellers.Afwijking(administratie_id=aid, naam="Baard B.V.", teller="afgewezen", cache=None, telling=2),
        ]
        nu = datetime(2026, 9, 11, 4, 0, tzinfo=UTC)
        kw = automatiseringen.werkvoorraad_tellers_bevinding(nu=nu, rapport=rapport)
        assert kw is not None
        assert kw["soort"] == "let_op" and kw["administratie_id"] is None and kw["blok"] == automatiseringen.BLOK
        assert "2 teller(s) bij 1 administratie(s)" in kw["tekst"]
        assert "Baard B.V.: vragen cache=3 telling=1" in kw["tekst"]
        assert "afgewezen cache=ontbreekt telling=2" in kw["tekst"]
        assert kw["detail"]["automatisering"] == "werkvoorraad_tellers" and kw["detail"]["doel_pad"] == "/reconciliatie"
        # stabiel per dag
        assert (
            kw["vingerafdruk"]
            == automatiseringen.werkvoorraad_tellers_bevinding(nu=nu, rapport=rapport)["vingerafdruk"]
        )

    def test_live_dry_run_zonder_administraties_is_stil(self) -> None:
        from datetime import UTC, datetime

        assert automatiseringen.werkvoorraad_tellers_bevinding(nu=datetime.now(UTC)) is None


class TestRoute:
    def test_overzicht_200_voor_niet_beheerder_met_scope_en_draagt_spiegel_taken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        _upload(administratie_id, gescoopte_gebruiker, opslag, "a.pdf")
        headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        r = client.get("/werkvoorraad/overzicht", headers=headers)
        assert r.status_code == 200, r.text
        [klant] = [k for k in r.json()["klanten"] if k["administratie_id"] == str(administratie_id)]
        assert klant["te_controleren"] == 1
        assert klant["spiegel_taken"] == 0
        # tweede aanroep komt uit de cache en is identiek
        assert client.get("/werkvoorraad/overzicht", headers=headers).json() == r.json()
