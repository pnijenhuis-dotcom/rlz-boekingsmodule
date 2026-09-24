"""Reeleezee-adapter voor dearchiveren (blok 3 bundelrun 24-09) — exact het gedrag van vóór 24-09, nu achter de port:
nieuwe webservice-login verplicht → admin-pin + rechten-probe + herprobe in de opgeslagen vorm
(`onboarding.probe_nieuwe_login`), credential in de store, probe-rapport op de credential. Rood = OnboardingFout
(422 mét rapport, niets opgeslagen) — ongewijzigd t.o.v. v2 30-08 zodat bestaande tests/gedrag identiek blijven."""

from __future__ import annotations

import uuid
from typing import Any

from app.backends.port import Backend, HeractiverenGeweigerd
from app.credentialstore import service as credentialstore_service
from app.db.models import Administratie
from app.db.session import scoped_session


class RlzHeractiveerPort:
    backend = Backend.RLZ

    def heractiveer_probe(
        self,
        *,
        administratie_id: uuid.UUID,
        actor_id: uuid.UUID,
        webservice_username: str | None,
        wachtwoord: str | None,
        client: Any = None,
    ) -> dict[str, str]:
        from app.beheer import onboarding

        if not (webservice_username or "").strip() or not wachtwoord:
            raise HeractiverenGeweigerd(
                "Dearchiveren van een Reeleezee-administratie vereist een nieuwe webservice-login "
                "(gebruiker + wachtwoord)"
            )
        with scoped_session(None) as session:
            administratie = session.get(Administratie, administratie_id)
            assert administratie is not None
            rlz_admin_id, naam = administratie.rlz_admin_id, administratie.naam
        rapport = onboarding.probe_nieuwe_login(
            rlz_admin_id=rlz_admin_id,
            naam=naam,
            webservice_username=webservice_username,
            wachtwoord=wachtwoord,
            client=client,
        )
        credentialstore_service.zet_credential(
            actor_id=actor_id,
            administratie_id=administratie_id,
            webservice_username=webservice_username,
            wachtwoord=wachtwoord,
        )
        with scoped_session(None, actor_id=actor_id) as session:
            credentialstore_service.sla_probe_op(
                session, administratie_id=administratie_id, rapport=rapport, actor_id=actor_id
            )
        return rapport
