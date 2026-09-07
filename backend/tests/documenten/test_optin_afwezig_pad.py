"""Afwezig-pad-tests per opt-in (herstelrun "geen stille no-op" 07-09, blok 2; besluit Peter, kernprincipe 7):
automatisering wacht NOOIT op een menselijke instelling. Per opt-in-vlag (`platform.administratie.*_ingeschakeld`,
de platformbrede noodremmen en de per-leverancier-/per-veldwerker-opt-ins) één test waarin de OPTIONELE voorwaarde
ontbreekt — hier: de administratie heeft géén eigenaar (`eigenaar_gebruiker_id IS NULL`, zoals in productie op álle
administraties) — en die bewijst dat de poort van de automatisering tóch open gaat. Alleen echte harde voorwaarden
(credential, API-key, geldpoort, aflever-config) mogen blokkeren, en dan ZICHTBAAR.

De vlaggen met een echte eigenaar-/toewijzingsafhankelijkheid (duplicaat-afvoer → afwijzen/vragen) hebben hun
afwezig-pad-test in de eigen suite (`test_duplicaat_afvoer.py`, gemarkeerd met dezelfde marker); de vlaggen zónder
zo'n afhankelijkheid krijgen hier een minimale, eerlijke test: vlag AAN + geen eigenaar → de poort-functie die het
automatische pad daadwerkelijk leest geeft True (of het pad loopt tot aan zijn harde voorwaarde en meldt die
zichtbaar). De guard `tests/unit/test_optin_afwezig_pad_guard.py` dwingt af dat élke vlag zo'n test heeft en dat geen
module buiten de bewuste allowlist op `eigenaar_gebruiker_id` vertakt."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.afdelingen import service as afdelingen_service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import autoboeken, webhook_afleveraar
from app.mini_voorraad import service as mini_voorraad_service
from app.voorraad import service as voorraad_service


def _zet_vlag(admin_engine: Engine, administratie_id: uuid.UUID, kolom: str) -> None:
    """Zet de per-administratie-vlag rechtstreeks (de Beheerder-zetters hebben eigen poorten — is_vastgoed, opt-in-
    volgorde — die hier niet de kern zijn) en borg dat er GEEN eigenaar is: dát is de afwezige voorwaarde."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(f"UPDATE platform.administratie SET {kolom} = true, eigenaar_gebruiker_id = NULL WHERE id = :a"),
            {"a": administratie_id},
        )


def _geen_eigenaar(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.connect() as conn:
        eigenaar = conn.execute(
            text("SELECT eigenaar_gebruiker_id FROM platform.administratie WHERE id = :a"), {"a": administratie_id}
        ).scalar_one()
    assert eigenaar is None, "de afwezige voorwaarde van deze test is: géén eigenaar"


# Per-administratie-vlag → de poort-functie die het automatische pad daadwerkelijk leest.
_PER_ADMINISTRATIE: dict[str, Callable[[uuid.UUID], bool]] = {
    "boeken_ingeschakeld": lambda a: beheer_service.haal_boeken_ingeschakeld_op(administratie_id=a),
    "ai_extractie_ingeschakeld": lambda a: beheer_service.haal_ai_extractie_ingeschakeld_op(administratie_id=a),
    "bank_autoboeken_ingeschakeld": lambda a: beheer_service.haal_bank_autoboeken_ingeschakeld_op(administratie_id=a),
    "verkoop_autoboeken_ingeschakeld": lambda a: beheer_service.haal_verkoop_autoboeken_ingeschakeld_op(
        administratie_id=a
    ),
    "omzet_autoboeken_ingeschakeld": lambda a: beheer_service.haal_omzet_autoboeken_ingeschakeld_op(administratie_id=a),
    "accordering_ingeschakeld": lambda a: accordering_service.is_accordering_ingeschakeld(administratie_id=a),
    "doorbelasting_ingeschakeld": lambda a: beheer_service.haal_doorbelasting_ingeschakeld_op(administratie_id=a),
    "uren_meerwerk_ingeschakeld": lambda a: beheer_service.haal_uren_meerwerk_ingeschakeld_op(administratie_id=a),
    "afdelingen_ingeschakeld": lambda a: afdelingen_service.is_ingeschakeld(administratie_id=a),
}


def _in_sessie(lezer: Callable) -> Callable[[uuid.UUID], bool]:
    def _poort(administratie_id: uuid.UUID) -> bool:
        with scoped_session(administratie_id) as session:
            return lezer(session, administratie_id)

    return _poort


_PER_ADMINISTRATIE["voorraad_ingeschakeld"] = _in_sessie(voorraad_service.is_ingeschakeld)
_PER_ADMINISTRATIE["mini_voorraad_ingeschakeld"] = _in_sessie(mini_voorraad_service.is_ingeschakeld)


class TestPerAdministratieOptIns:
    @pytest.mark.afwezig_pad("administratie.boeken_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.ai_extractie_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.bank_autoboeken_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.verkoop_autoboeken_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.omzet_autoboeken_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.accordering_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.doorbelasting_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.uren_meerwerk_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.afdelingen_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.voorraad_ingeschakeld")
    @pytest.mark.afwezig_pad("administratie.mini_voorraad_ingeschakeld")
    @pytest.mark.parametrize("kolom", sorted(_PER_ADMINISTRATIE))
    def test_vlag_aan_zonder_eigenaar_opent_de_poort(
        self, kolom: str, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Vlag AAN, geen eigenaar → de poort die het automatische pad leest staat open. De poort mag alleen op de
        vlag zelf (en echte harde voorwaarden) vertakken — nooit op een persoon."""
        with admin_engine.begin() as conn:
            conn.execute(
                text(f"UPDATE platform.administratie SET {kolom} = false WHERE id = :a"), {"a": administratie_id}
            )
        _geen_eigenaar(admin_engine, administratie_id)
        assert _PER_ADMINISTRATIE[kolom](administratie_id) is False
        _zet_vlag(admin_engine, administratie_id, kolom)
        _geen_eigenaar(admin_engine, administratie_id)
        assert _PER_ADMINISTRATIE[kolom](administratie_id) is True

    @pytest.mark.afwezig_pad("administratie.afgeletterd_event_ingeschakeld")
    def test_afgeletterd_event_zonder_eigenaar_passeert_de_poort(
        self, administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """De bank-sync-stap `detecteer_en_meld_afgeletterd` leest de vlag (én is_vastgoed) en gaat daarna door naar de
        RLZ-kant — zonder eigenaar. Gespioneerd op de eerste stap ná de poort (`rlz_admin_id_voor`)."""
        from app.bank import vastly

        aanroepen: list[uuid.UUID] = []
        monkeypatch.setattr(vastly, "rlz_admin_id_voor", lambda a: aanroepen.append(a) or "rlz-test")
        # Poort dicht: niets voorbij de vlag.
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=None) == 0  # type: ignore[arg-type]
        assert aanroepen == []
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.administratie SET is_vastgoed = true, afgeletterd_event_ingeschakeld = true, "
                    "eigenaar_gebruiker_id = NULL WHERE id = :a"
                ),
                {"a": administratie_id},
            )
        _geen_eigenaar(admin_engine, administratie_id)
        # Poort open: het pad loopt door (geen kandidaten → 0 meldingen), zonder persoon.
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=None) == 0  # type: ignore[arg-type]
        assert aanroepen == [administratie_id]


class TestPlatformbredeNoodremmen:
    @pytest.mark.afwezig_pad("boeken_instelling.globaal_ingeschakeld")
    def test_boeken_kill_switch_aan_zonder_zetter_of_eigenaar(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """De globale boeken-schakelaar staat AAN zonder dat ooit een mens 'm zette (gewijzigd_door NULL) en zonder
        eigenaar op de administratie — boeken is dan niet op een persoon geblokkeerd."""
        with admin_engine.connect() as conn:
            zetter = conn.execute(text("SELECT gewijzigd_door FROM platform.boeken_instelling")).scalar_one()
        assert zetter is None
        _geen_eigenaar(admin_engine, administratie_id)
        assert beheer_service.haal_globale_kill_switch_op() is True

    @pytest.mark.afwezig_pad("webhook_instelling.aflevering_ingeschakeld")
    def test_webhook_aflevering_aan_zonder_config_meldt_de_harde_voorwaarde_zichtbaar(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Aflevering AAN, geen eigenaar → de run gaat de poort door; de ontbrekende doel-URL/HMAC-secret is een ÉCHTE
        harde voorwaarde en wordt zichtbaar gerapporteerd (`overgeslagen_reden`), nooit een stille return."""
        _geen_eigenaar(admin_engine, administratie_id)
        uit = webhook_afleveraar.verwerk_openstaande_webhooks()
        assert uit.overgeslagen_reden is not None and "aflevering staat uit" in uit.overgeslagen_reden
        assert beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True) is True
        rapport = webhook_afleveraar.verwerk_openstaande_webhooks()
        assert rapport.overgeslagen_reden is not None
        assert "onvoldoende geconfigureerd" in rapport.overgeslagen_reden
        assert "rijen blijven openstaand" in rapport.overgeslagen_reden

    @pytest.mark.afwezig_pad("intake_instelling.ai_ingeschakeld")
    def test_intake_ai_aan_zonder_eigenaar(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _geen_eigenaar(admin_engine, administratie_id)
        assert beheer_service.haal_intake_ai_ingeschakeld_op() is False
        assert beheer_service.zet_intake_ai_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True) is True
        assert beheer_service.haal_intake_ai_ingeschakeld_op() is True


class TestOptInsPerRelatie:
    @pytest.mark.afwezig_pad("leverancier_voorkeur.autoboeken_ingeschakeld")
    def test_leverancier_autoboeken_aan_zonder_eigenaar(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Opt-in per leverancier (migratie 0036): de poort die het autoboek-pad leest (`_autoboeken_ingeschakeld`)
        kent geen persoon — alleen de vlag."""
        _geen_eigenaar(admin_engine, administratie_id)
        vendor_id = uuid.uuid4()
        assert autoboeken._autoboeken_ingeschakeld(administratie_id=administratie_id, vendor_id=vendor_id) is False
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=beheerder_id, ingeschakeld=True
        )
        assert autoboeken._autoboeken_ingeschakeld(administratie_id=administratie_id, vendor_id=vendor_id) is True

    @pytest.mark.afwezig_pad("veldwerker_crediteur.autoboeken_ingeschakeld")
    def test_veldwerker_autoboeken_aan_zonder_eigenaar(
        self,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Opt-in per veldwerker-koppeling (factuurmatch fase 4): het autoboek-pad leest
        `koppeling.autoboeken_ingeschakeld` (documenten/autoboeken.py) — zonder eigenaar net zo."""
        from app.uren import service as uren_service
        from app.uren.factuurmatch import vind_veldwerker_koppeling
        from app.uren.models import VeldwerkerCrediteur

        _zet_vlag(admin_engine, administratie_id, "uren_meerwerk_ingeschakeld")
        _geen_eigenaar(admin_engine, administratie_id)
        vendor_id = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                VeldwerkerCrediteur(
                    administratie_id=administratie_id,
                    gebruiker_id=gescoopte_gebruiker,
                    vendor_id=vendor_id,
                    gekoppeld_door=beheerder_id,
                )
            )
        with scoped_session(administratie_id) as session:
            koppeling = vind_veldwerker_koppeling(session, administratie_id=administratie_id, vendor_id=vendor_id)
            assert koppeling is not None and koppeling.autoboeken_ingeschakeld is False
        uren_service.zet_veldwerker_autoboeken(
            administratie_id=administratie_id,
            gebruiker_id=gescoopte_gebruiker,
            ingeschakeld=True,
            actor_id=beheerder_id,
        )
        with scoped_session(administratie_id) as session:
            koppeling = vind_veldwerker_koppeling(session, administratie_id=administratie_id, vendor_id=vendor_id)
            assert koppeling is not None and koppeling.autoboeken_ingeschakeld is True
