"""Wachtwoord-herstel voor actieve externe gebruikers (RLZ-feedbackronde 25-08 deel 2, punt 7;
migratie 0068).

Gat uit de kliktest 25-08: kill-switch + wachtwoord kwijt = accordeur zit klem, want de
uitnodiging-opnieuw-route weigert geactiveerde accounts. De Beheerder stuurt een eenmalige
72-uurs herstel-link (zelfde token-mechaniek): nieuw wachtwoord → direct door naar
apparaat-registratie; status, passkeys en akkoorden blijven staan; lopende sessies vervallen;
alle oudere open links van die gebruiker zijn ongeldig; alles geauditeerd. Geen selfservice.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.security.tokens import create_access_token
from tests.auth.soft_webauthn import SoftWebauthnApparaat
from tests.auth.test_webauthn_cadans import (
    WACHTWOORD,
    _activeer_accordeur,
    _bearer,
    _beheerder_bearer,
    client,
)
from tests.uren.conftest import maak_gebruiker

NIEUW_WACHTWOORD = "een-nieuw-en-lang-wachtwoord"


def _gebruiker_id_van(e_mail: str, admin_engine: Engine) -> uuid.UUID:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM platform.gebruiker WHERE e_mail = :m"), {"m": e_mail}
        ).scalar_one()


def _status(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM platform.gebruiker WHERE id = :id"), {"id": gebruiker_id}
        ).scalar_one()


def _audit_acties(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": record_id},
            ).scalars()
        )


def _rij(beheerder_id: uuid.UUID, gebruiker_id: uuid.UUID) -> dict:
    resp = client.get("/auth/gebruikers", headers=_beheerder_bearer(beheerder_id))
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["gebruikers"] if g["id"] == str(gebruiker_id))


class TestVolledigeHerstelcyclus:
    def test_kill_switch_scenario_end_to_end(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        """Het kliktest-scenario: actieve accordeur mét passkey + sessie is zijn wachtwoord kwijt.
        Herstel-link → nieuw wachtwoord → passkey-setup-token → nieuw apparaat registreren."""
        e_mail, _apparaat, oud_access = _activeer_accordeur(beheerder_id)
        gebruiker_id = _gebruiker_id_van(e_mail, admin_engine)
        assert _status(admin_engine, gebruiker_id) == "actief"

        # 1. Beheerder stuurt de herstel-link (mail niet geconfigureerd in de suite → zichtbaar
        #    mislukt, de link zit als terugval in de respons — nooit stil).
        resp = client.post(f"/auth/gebruikers/{gebruiker_id}/herstel-link", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        herstel = resp.json()
        assert herstel["gebruiker_id"] == str(gebruiker_id)
        assert herstel["token"]
        assert herstel["mail_verzonden"] is False
        assert herstel["mail_fout"]

        # 2. De gebruikerslijst toont een open HERSTEL-link, geen open uitnodiging; het account
        #    blijft 'actief' met zijn passkey — er is niets teruggezet.
        rij = _rij(beheerder_id, gebruiker_id)
        assert rij["status"] == "actief"
        assert rij["open_herstel_verloopt_op"] is not None
        assert rij["open_uitnodiging_verloopt_op"] is None
        assert rij["aantal_passkeys"] == 1

        # 3. De gebruiker verzilvert de link: nieuw wachtwoord, direct een passkey-setup-token.
        resp = client.post(
            "/auth/uitnodigingen/accepteren", json={"token": herstel["token"], "wachtwoord": NIEUW_WACHTWOORD}
        )
        assert resp.status_code == 200, resp.text
        accept = resp.json()
        assert accept["soort"] == "passkey"
        assert accept["passkey_setup_token"]
        assert accept["totp_setup_token"] is None

        # Status ongewijzigd, bestaande passkey blijft staan, herstel-link is verbruikt.
        assert _status(admin_engine, gebruiker_id) == "actief"
        rij = _rij(beheerder_id, gebruiker_id)
        assert rij["aantal_passkeys"] == 1
        assert rij["open_herstel_verloopt_op"] is None

        # 4. Nieuw wachtwoord werkt, het oude niet meer (accordeur-wachtwoordstap).
        resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": NIEUW_WACHTWOORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["heeft_passkeys"] is True
        resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
        assert resp.status_code == 401

        # 5. Lopende sessies zijn ingetrokken: de refresh-cookie van de oude activatie is dood.
        resp = client.post("/auth/token/vernieuwen")
        assert resp.status_code == 401, resp.text

        # 6. "Direct door naar apparaat-registratie": met het setup-token registreert het nieuwe
        #    apparaat en krijgt meteen een werkende sessie — twee apparaten, niets verwijderd.
        nieuw_apparaat = SoftWebauthnApparaat()
        setup = _bearer(accept["passkey_setup_token"])
        resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
        assert resp.status_code == 200, resp.text
        resp = client.post(
            "/auth/webauthn/registratie/voltooien",
            json={"credential": nieuw_apparaat.registreer(resp.json()["opties"]), "apparaat_naam": "Nieuwe iPhone"},
            headers=setup,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        assert _rij(beheerder_id, gebruiker_id)["aantal_passkeys"] == 2

        # 7. Beide kanten geauditeerd: de beheerhandeling op de link, de verzilvering op de gebruiker.
        assert _audit_acties(admin_engine, uuid.UUID(herstel["uitnodiging_id"])) == [
            "wachtwoord_herstel_link_aangemaakt"
        ]
        assert "wachtwoord_hersteld" in _audit_acties(admin_engine, gebruiker_id)
        del oud_access  # access-JWT's blijven tot hun eigen expiry geldig — bewust (bestaand model).

    def test_wacht_op_passkey_account_mag_ook_herstellen(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        """Wachtwoord gezet maar registratie nooit afgerond = ook 'wachtwoord ooit gezet'; de
        herstel-link laat de status ongemoeid (registratie maakt hem later actief, 0040-lijn)."""
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Half Klaar",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.ZZPER,
            administratie_ids=[],
        )
        service.accepteer_uitnodiging(token=resultaat.token, wachtwoord=WACHTWOORD)
        assert _status(admin_engine, resultaat.gebruiker_id) == "wacht_op_passkey"
        herstel = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=resultaat.gebruiker_id)
        acceptatie = service.accepteer_uitnodiging(token=herstel.resultaat.token, wachtwoord=NIEUW_WACHTWOORD)
        assert acceptatie.soort == "passkey"
        assert _status(admin_engine, resultaat.gebruiker_id) == "wacht_op_passkey"


class TestEenWerkendeLinkTegelijk:
    def test_nieuwe_herstel_link_laat_oudere_links_verlopen(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        gid = maak_gebruiker(admin_engine, "klant_accordeur", "Twee Links")
        eerste = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=gid)
        tweede = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=gid)
        with pytest.raises(service.AuthError, match="verlopen"):
            service.accepteer_uitnodiging(token=eerste.resultaat.token, wachtwoord=NIEUW_WACHTWOORD)
        acceptatie = service.accepteer_uitnodiging(token=tweede.resultaat.token, wachtwoord=NIEUW_WACHTWOORD)
        assert acceptatie.soort == "passkey"
        # Eenmalig: verzilverd = verbruikt.
        with pytest.raises(service.AuthError, match="al gebruikt"):
            service.accepteer_uitnodiging(token=tweede.resultaat.token, wachtwoord=NIEUW_WACHTWOORD)

    def test_te_kort_wachtwoord_faalt_ook_bij_herstel(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        gid = maak_gebruiker(admin_engine, "uitvoerder", "Kort W.")
        herstel = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=gid)
        with pytest.raises(service.AuthError, match="minimaal"):
            service.accepteer_uitnodiging(token=herstel.resultaat.token, wachtwoord="kort")


class TestPoorten:
    def test_kantoorrol_krijgt_geen_herstel_link(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        gid = maak_gebruiker(admin_engine, "boekhouding", "Kantoor K.")
        resp = client.post(f"/auth/gebruikers/{gid}/herstel-link", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 409
        assert "externe app-gebruikers" in resp.json()["detail"]

    def test_nog_niet_geactiveerd_verwijst_naar_opnieuw_mailen(self, beheerder_id: uuid.UUID) -> None:
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Nog Uitgenodigd",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.KLANT_ACCORDEUR,
            administratie_ids=[],
        )
        with pytest.raises(service.AuthError, match="Opnieuw mailen"):
            service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=resultaat.gebruiker_id)

    def test_geblokkeerd_account_eerst_heractiveren(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        gid = maak_gebruiker(admin_engine, "klant_accordeur", "Geblokkeerd G.")
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=gid)
        with pytest.raises(service.AuthError, match="heractiveer"):
            service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=gid)

    def test_blokkade_na_uitgifte_maakt_de_link_waardeloos(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        """Blokkade wint altijd (0052-lijn): een al verstuurde herstel-link opent niets meer."""
        gid = maak_gebruiker(admin_engine, "klant_accordeur", "Later Geblokkeerd")
        herstel = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=gid)
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=gid)
        with pytest.raises(service.AuthError, match="geblokkeerd"):
            service.accepteer_uitnodiging(token=herstel.resultaat.token, wachtwoord=NIEUW_WACHTWOORD)
        assert _status(admin_engine, gid) == "geblokkeerd"

    def test_systeem_actor_en_onbekende_gebruiker(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(service.AuthError, match="systeemgebruiker"):
            service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=SYSTEEM_ACTOR_ID)
        with pytest.raises(service.AuthError, match="Onbekende"):
            service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=uuid.uuid4())

    @pytest.mark.parametrize("rol", ["boekhouding", "boekhouding_projecten", "klant_accordeur", "zzper"])
    def test_alleen_beheerder_mag_sturen(self, rol: str, admin_engine: Engine) -> None:
        actor = maak_gebruiker(admin_engine, rol, f"Actor {rol}")
        doel = maak_gebruiker(admin_engine, "klant_accordeur", "Doel D.")
        resp = client.post(
            f"/auth/gebruikers/{doel}/herstel-link",
            headers={"Authorization": f"Bearer {create_access_token(actor, rol=rol)}"},
        )
        assert resp.status_code == 403

    def test_uitnodiging_opnieuw_blijft_geactiveerde_accounts_weigeren(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """De bestaande route is niet verbreed: herstel is een eigen, expliciete handeling."""
        gid = maak_gebruiker(admin_engine, "klant_accordeur", "Actief A.")
        resp = client.post(f"/auth/gebruikers/{gid}/uitnodiging-opnieuw", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 409
