""" "Nooit splitsen" per afzender (blok B medewerker-wensen 04-09, migratie 0106): regel leren via
"Is één factuur" mét vink (+ audit), intake slaat de splitsings-AI over bij een actieve regel (geen
AI-call), gedeactiveerde regel = weer AI, uitgesloten kantoordomein = 422, lijst/verwijderen mét
administratie-scope."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.db.session import scoped_session
from app.extractie.splitsing import FactuurSegment
from app.intake import splitsing as splitsing_service
from app.intake import splitsing_uitsluiting, verwerking, verzamelbak
from app.intake.toewijzing import leer_toewijzing
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_eml, bouw_pdf

client = TestClient(app)
AFZENDER = "administratie@bouwmaat.nl"  # default-afzender van bouw_eml


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _stub_twee_facturen(monkeypatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        verwerking.splitsing_extractie,
        "detecteer_facturen",
        lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
            FactuurSegment(1, 2, "BLOW B.V.", "Bouwmaat", "F-1", 0.95, factuur_paginas=1),
            FactuurSegment(3, 3, "Onbekend BV", "Sligro", "F-2", 0.9),
        ],
    )


@pytest.fixture
def splitsingsvoorstel(
    administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, monkeypatch
) -> tuple[uuid.UUID, uuid.UUID]:
    """(bron_document_id, splitsing_id) — 3-pagina-PDF van AFZENDER met twee 'herkende' facturen."""
    _stub_twee_facturen(monkeypatch)
    eml = bouw_eml(bijlagen=[("factuur-met-werkbonnen.pdf", bouw_pdf(3), "application", "pdf")])
    resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    bron_id = resultaat.bijlagen[0].document_id
    items = verzamelbak.lijst_verzamelbak()
    return bron_id, next(i.splitsing_id for i in items if i.document_id == bron_id)


def _audit_acties(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :actie ORDER BY tijdstip"),
            {"actie": actie},
        ).all()
    return [r.nieuwe_waarde for r in rijen]


class TestLerenViaAfwijzen:
    def test_afwijzen_met_vink_maakt_regel_en_audit(
        self,
        splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        bron_id, splitsing_id = splitsingsvoorstel
        regel_id = splitsing_service.wijs_splitsing_af(
            splitsing_id=splitsing_id,
            actor_id=gescoopte_gebruiker,
            reden="Werkbonnen horen bij de factuur",
            onthoud_niet_splitsen=True,
            administratie_id=administratie_heet_blow,
        )
        assert regel_id is not None
        with admin_engine.connect() as conn:
            regel = conn.execute(
                text(
                    "SELECT administratie_id, afzender_adres, leverancier_naam, reden, actief "
                    "FROM boekhouding.intake_splitsing_uitsluiting WHERE id = :id"
                ),
                {"id": regel_id},
            ).one()
            bron_status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": bron_id}
            ).scalar_one()
            besluit = conn.execute(
                text("SELECT besluit_detail FROM boekhouding.intake_splitsing WHERE id = :id"), {"id": splitsing_id}
            ).scalar_one()
        assert regel.administratie_id == administratie_heet_blow
        assert regel.afzender_adres == AFZENDER
        assert regel.leverancier_naam == "Bouwmaat"  # informatief, uit het voorstel
        assert regel.reden == "Werkbonnen horen bij de factuur"
        assert regel.actief is True
        assert bron_status == "niet_toegewezen"  # het origineel blijft als één geheel in de bak
        assert besluit["nooit_splitsen_regel_id"] == str(regel_id)
        audits = _audit_acties(admin_engine, "splitsing_uitsluiting_aangemaakt")
        assert len(audits) == 1
        assert audits[0]["afzender_adres"] == AFZENDER
        assert audits[0]["administratie_id"] == str(administratie_heet_blow)
        assert audits[0]["bron_splitsing_id"] == str(splitsing_id)

    def test_zonder_vink_geen_regel(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, splitsing_id = splitsingsvoorstel
        assert splitsing_service.wijs_splitsing_af(splitsing_id=splitsing_id, actor_id=gescoopte_gebruiker) is None
        with admin_engine.connect() as conn:
            aantal = conn.execute(text("SELECT count(*) FROM boekhouding.intake_splitsing_uitsluiting")).scalar_one()
        assert aantal == 0

    def test_vink_zonder_administratie_is_fout_en_wijst_niets_af(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, splitsing_id = splitsingsvoorstel
        with pytest.raises(splitsing_uitsluiting.AdministratieVerplicht):
            splitsing_service.wijs_splitsing_af(
                splitsing_id=splitsing_id, actor_id=gescoopte_gebruiker, onthoud_niet_splitsen=True
            )
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.intake_splitsing WHERE id = :id"), {"id": splitsing_id}
            ).scalar_one()
        assert status == "voorgesteld"  # alles-of-niets: niets afgewezen

    def test_uitgesloten_kantoordomein_krijgt_geen_regel(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        """peter@ak-nijenhuis.nl (default in `intake_afzender_uitgesloten_domeinen`) is meerduidig."""
        _stub_twee_facturen(monkeypatch)
        eml = bouw_eml(
            afzender="peter@ak-nijenhuis.nl",
            bijlagen=[("doorgestuurd.pdf", bouw_pdf(3), "application", "pdf")],
        )
        bron_id = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0].document_id
        splitsing_id = next(i.splitsing_id for i in verzamelbak.lijst_verzamelbak() if i.document_id == bron_id)
        resp = client.post(
            f"/intake/splitsingen/{splitsing_id}/afwijzen",
            json={"onthoud_niet_splitsen": True, "administratie_id": str(administratie_heet_blow)},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 422
        assert "kantoor-/doorstuurdomein" in resp.json()["detail"]

    def test_upload_zonder_afzender_kan_niet_onthouden(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        _stub_twee_facturen(monkeypatch)
        resultaat = verwerking.verwerk_los_bestand(
            bestandsnaam="scan.pdf", inhoud=bouw_pdf(3), content_type="application/pdf", actor_id=gescoopte_gebruiker
        )
        bron_id = resultaat.document_id
        splitsing_id = next(i.splitsing_id for i in verzamelbak.lijst_verzamelbak() if i.document_id == bron_id)
        with pytest.raises(splitsing_uitsluiting.GeenAfzenderBekend):
            splitsing_service.wijs_splitsing_af(
                splitsing_id=splitsing_id,
                actor_id=gescoopte_gebruiker,
                onthoud_niet_splitsen=True,
                administratie_id=administratie_heet_blow,
            )

    def test_route_afwijzen_met_vink_via_api(
        self,
        splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        _, splitsing_id = splitsingsvoorstel
        resp = client.post(
            f"/intake/splitsingen/{splitsing_id}/afwijzen",
            json={
                "reden": "één factuur",
                "onthoud_niet_splitsen": True,
                "administratie_id": str(administratie_heet_blow),
            },
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nooit_splitsen_regel_id"]
        lijst = client.get(
            f"/administraties/{administratie_heet_blow}/intake/splitsing-uitsluitingen",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert lijst.status_code == 200
        regels = lijst.json()["regels"]
        assert [r["afzender_adres"] for r in regels] == [AFZENDER]
        assert regels[0]["aangemaakt_door_naam"] == "Boekhouder"


def _maak_regel(administratie_id: uuid.UUID, actor_id: uuid.UUID, afzender: str = AFZENDER) -> uuid.UUID:
    with scoped_session(None, actor_id=actor_id) as session:
        regel = splitsing_uitsluiting.maak_regel(
            session,
            administratie_id=administratie_id,
            afzender=afzender,
            leverancier_naam="Bouwmaat",
            reden=None,
            actor_id=actor_id,
        )
        return regel.id


class TestIntakeSlaatAiOver:
    @pytest.fixture
    def ai_mag_niet(self, monkeypatch) -> list[str]:
        """Splitsings-AI die FAALT als hij tóch wordt aangeroepen — de test bewijst dat er geen AI-call is."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        aanroepen: list[str] = []

        def verboden(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            aanroepen.append("aangeroepen")
            raise AssertionError("splitsings-AI mag niet worden aangeroepen bij een 'nooit splitsen'-regel")

        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", verboden)
        return aanroepen

    def test_actieve_regel_geen_ai_verzamelbak_met_reden_en_suggestie(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        ai_mag_niet: list[str],
        admin_engine: Engine,
    ) -> None:
        _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        eml = bouw_eml(bijlagen=[("factuur-met-bijlagen.pdf", bouw_pdf(5), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        bijlage = resultaat.bijlagen[0]
        assert ai_mag_niet == []
        # Geen tenaamstelling zonder AI en geen afzender-regel → verzamelbak, mét zichtbare reden en de
        # regel-administratie als SUGGESTIE (nooit auto-toewijzing).
        assert bijlage.uitkomst == "verzamelbak"
        assert bijlage.detail == f"splitsing_overgeslagen_nooit_splitsen: {AFZENDER}"
        rij = {i.document_id: i for i in verzamelbak.lijst_verzamelbak()}[bijlage.document_id]
        assert rij.splitsing_voorstel is None
        assert rij.reden == f"splitsing_overgeslagen_nooit_splitsen: {AFZENDER}"
        assert rij.reden_label == (
            f"splitsing overgeslagen: regel 'nooit splitsen' voor {AFZENDER} — handmatig toewijzen"
        )
        assert rij.suggestie_administratie_id == administratie_heet_blow
        assert rij.suggestie_bron == "nooit_splitsen_regel"
        # Kostenmeter onaangeroerd: géén ai_gebruik-rij.
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.ai_gebruik")).scalar_one() == 0

    def test_actieve_regel_plus_afzender_geheugen_wijst_direct_toe(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        ai_mag_niet: list[str],
    ) -> None:
        _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(
                session,
                administratie_id=administratie_heet_blow,
                actor_id=gescoopte_gebruiker,
                tenaamstelling=None,
                afzender=AFZENDER,
            )
        eml = bouw_eml(bijlagen=[("factuur-met-bijlagen.pdf", bouw_pdf(4), "application", "pdf")])
        bijlage = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0]
        assert ai_mag_niet == []
        assert bijlage.uitkomst == "toegewezen"
        assert bijlage.detail == f"afzender_regel → {administratie_heet_blow}"

    def test_regel_werkt_boven_de_ai_gate(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, ai_mag_niet: list[str]
    ) -> None:
        """Zonder intake_ai_aan: een regel-afzender komt tóch als één geheel binnen mét de regel-reden
        (de route heeft geen AI nodig; gate/limiet staan 'm niet in de weg)."""
        _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(2), "application", "pdf")])
        bijlage = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0]
        assert bijlage.uitkomst == "verzamelbak"
        assert bijlage.detail.startswith("splitsing_overgeslagen_nooit_splitsen:")

    def test_regel_voor_andere_administratie_telt_kantoorbreed_zonder_suggestie_bij_meerdere(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        ai_mag_niet: list[str],
        admin_engine: Engine,
    ) -> None:
        """Twee BV's sluiten dezelfde afzender uit: de intake slaat de AI over (kantoorbreed), maar er is
        geen eenduidige suggestie meer — de mens kiest."""
        tweede = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Tweede BV', :rlz)"),
                {"id": tweede, "rlz": f"rlz-{tweede}"},
            )
        _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        _maak_regel(tweede, gescoopte_gebruiker)
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(2), "application", "pdf")])
        bijlage = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0]
        assert ai_mag_niet == []
        rij = {i.document_id: i for i in verzamelbak.lijst_verzamelbak()}[bijlage.document_id]
        assert rij.suggestie_administratie_id is None

    def test_gedeactiveerde_regel_is_weer_ai(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_aan: None,
        monkeypatch,
        admin_engine: Engine,
    ) -> None:
        regel_id = _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        splitsing_uitsluiting.deactiveer_regel(
            administratie_id=administratie_heet_blow, regel_id=regel_id, actor_id=gescoopte_gebruiker
        )
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        aanroepen: list[int] = []

        def een_factuur(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            aanroepen.append(paginas)
            return [FactuurSegment(1, paginas, "BLOW B.V.", "Bouwmaat", "F-9", 0.95, factuur_paginas=1)]

        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", een_factuur)
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(2), "application", "pdf")])
        bijlage = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0]
        assert aanroepen == [2]  # de AI draait weer
        assert bijlage.uitkomst == "toegewezen"
        audits = _audit_acties(admin_engine, "splitsing_uitsluiting_verwijderd")
        assert len(audits) == 1 and audits[0]["actief"] is False
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT actief, verwijderd_op, verwijderd_door FROM boekhouding.intake_splitsing_uitsluiting "
                    "WHERE id = :id"
                ),
                {"id": regel_id},
            ).one()
        assert rij.actief is False and rij.verwijderd_op is not None and rij.verwijderd_door == gescoopte_gebruiker

    def test_uitgesloten_domein_wordt_nooit_getroffen(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Een (hypothetische, bv. vóór een config-uitbreiding aangemaakte) regel op een uitgesloten domein
        # werkt niet stil door: de intake-toets weigert er op.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.intake_splitsing_uitsluiting "
                    "(id, administratie_id, afzender_adres, aangemaakt_door) VALUES (:id, :adm, :afz, :door)"
                ),
                {
                    "id": uuid.uuid4(),
                    "adm": administratie_heet_blow,
                    "afz": "peter@ak-nijenhuis.nl",
                    "door": gescoopte_gebruiker,
                },
            )
        assert splitsing_uitsluiting.vind_uitsluiting("Peter <peter@ak-nijenhuis.nl>".lower()) is None
        assert splitsing_uitsluiting.vind_uitsluiting("peter@ak-nijenhuis.nl") is None
        assert splitsing_uitsluiting.vind_uitsluiting(None) is None

    def test_maak_regel_is_idempotent(self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        eerste = _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        tweede = _maak_regel(administratie_heet_blow, gescoopte_gebruiker, afzender="  Administratie@Bouwmaat.NL ")
        assert eerste == tweede  # genormaliseerde sleutel, geen tweede actieve rij


class TestBeheerEndpoints:
    def test_lijst_en_verwijderen_met_scope(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        regel_id = _maak_regel(administratie_heet_blow, gescoopte_gebruiker)
        # Andere administratie zonder scope voor de boekhouder → 403; de Beheerder is platform-breed.
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        assert (
            client.get(
                f"/administraties/{andere}/intake/splitsing-uitsluitingen", headers=_bearer(gescoopte_gebruiker)
            ).status_code
            == 403
        )
        eigen = client.get(
            f"/administraties/{administratie_heet_blow}/intake/splitsing-uitsluitingen",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert eigen.status_code == 200
        assert [r["id"] for r in eigen.json()["regels"]] == [str(regel_id)]
        # De regel is vanuit een andere administratie onvindbaar (scope server-side, ook voor de Beheerder).
        assert (
            client.delete(
                f"/administraties/{andere}/intake/splitsing-uitsluitingen/{regel_id}",
                headers=_bearer(beheerder_id, rol="beheerder"),
            ).status_code
            == 404
        )
        weg = client.delete(
            f"/administraties/{administratie_heet_blow}/intake/splitsing-uitsluitingen/{regel_id}",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert weg.status_code == 204
        # Tweede keer: al verwijderd → 404 (idempotent leesbaar), rij blijft bestaan (nooit hard weg).
        assert (
            client.delete(
                f"/administraties/{administratie_heet_blow}/intake/splitsing-uitsluitingen/{regel_id}",
                headers=_bearer(gescoopte_gebruiker),
            ).status_code
            == 404
        )
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.intake_splitsing_uitsluiting")).scalar_one() == 1
        assert (
            client.get(
                f"/administraties/{administratie_heet_blow}/intake/splitsing-uitsluitingen",
                headers=_bearer(gescoopte_gebruiker),
            ).json()["regels"]
            == []
        )

    def test_afwijzen_met_vink_op_administratie_buiten_scope_is_403(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        _, splitsing_id = splitsingsvoorstel
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        resp = client.post(
            f"/intake/splitsingen/{splitsing_id}/afwijzen",
            json={"onthoud_niet_splitsen": True, "administratie_id": str(andere)},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 403
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.intake_splitsing WHERE id = :id"), {"id": splitsing_id}
            ).scalar_one()
        assert status == "voorgesteld"


class TestBijlagePaginasInVoorstel:
    def test_voorstel_draagt_factuur_en_bijlagepaginas(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID
    ) -> None:
        bron_id, _ = splitsingsvoorstel
        resp = client.get("/verzamelbak", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200
        rij = next(i for i in resp.json()["items"] if i["document_id"] == str(bron_id))
        delen = rij["splitsing_voorstel"]
        assert (delen[0]["factuur_paginas"], delen[0]["bijlage_paginas"]) == (1, 1)  # p.1–2, factuur 1 → 1 bijlage
        assert (delen[1]["factuur_paginas"], delen[1]["bijlage_paginas"]) == (None, None)  # fp onbekend
