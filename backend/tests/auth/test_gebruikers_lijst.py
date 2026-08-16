"""Gebruikers & toegang (fase 3 modernisering 15-08): de nieuwe gebruikerslijst +
"opnieuw mailen" van een open uitnodiging."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401


def _vind(items: list[service.GebruikerOverzicht], gebruiker_id: uuid.UUID) -> service.GebruikerOverzicht:
    return next(item for item in items if item.id == gebruiker_id)


class TestLijstGebruikers:
    def test_lijst_toont_rol_scope_status_en_open_uitnodiging(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Nieuwe Medewerker",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[administratie_id],
        )
        items = service.lijst_gebruikers(actor_id=beheerder_id)
        rij = _vind(items, resultaat.gebruiker_id)
        assert rij.rol == GebruikerRol.BOEKHOUDING
        assert rij.status.value == "uitgenodigd"
        assert rij.administratie_ids == [administratie_id]
        assert rij.heeft_totp is False
        assert rij.aantal_passkeys == 0
        assert rij.open_uitnodiging_verloopt_op is not None

    def test_gepseudonimiseerde_gebruiker_blijft_buiten_de_lijst(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        gid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status, gepseudonimiseerd_op) "
                    "VALUES (:id, 'Weg', :mail, 'boekhouding', 'actief', :nu)"
                ),
                {"id": gid, "mail": f"{gid}@test.local", "nu": datetime.now(UTC)},
            )
        assert all(item.id != gid for item in service.lijst_gebruikers(actor_id=beheerder_id))


class TestVernieuwUitnodiging:
    def test_nieuw_token_werkt_en_oude_open_link_verloopt(
        self, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        eerste = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Wacht Nog",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[],
        )
        vernieuwd = service.vernieuw_uitnodiging(actor_id=beheerder_id, gebruiker_id=eerste.gebruiker_id)
        assert vernieuwd.resultaat.gebruiker_id == eerste.gebruiker_id
        assert vernieuwd.e_mail.endswith("@test.local")
        # De oude link is per direct verlopen — één werkende link tegelijk.
        with pytest.raises(service.AuthError, match="verlopen"):
            service.accepteer_uitnodiging(token=eerste.token, wachtwoord="een-heel-lang-wachtwoord")
        # De nieuwe link werkt gewoon.
        acceptatie = service.accepteer_uitnodiging(
            token=vernieuwd.resultaat.token, wachtwoord="een-heel-lang-wachtwoord"
        )
        assert acceptatie.soort == "totp"

    def test_geactiveerd_account_krijgt_nooit_een_verse_link(
        self, beheerder_id: uuid.UUID  # noqa: F811
    ) -> None:
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Al Bezig",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[],
        )
        service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
        with pytest.raises(service.AuthError, match="geactiveerde"):
            service.vernieuw_uitnodiging(actor_id=beheerder_id, gebruiker_id=resultaat.gebruiker_id)

    def test_opnieuw_mailen_wordt_geaudit(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:  # noqa: F811
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Audit Check",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[],
        )
        vernieuwd = service.vernieuw_uitnodiging(actor_id=beheerder_id, gebruiker_id=resultaat.gebruiker_id)
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'uitnodiging_opnieuw_gemaild' AND record_id = :rid"
                ),
                {"rid": vernieuwd.resultaat.uitnodiging_id},
            ).scalar_one()
        assert aantal == 1
