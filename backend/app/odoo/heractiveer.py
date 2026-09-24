"""Odoo-adapter voor dearchiveren (blok 3 bundelrun 24-09; BUG Peter 24-09 "Recreatief Vastgoed Nederland":
`dearchiveer_administratie` eiste een Reeleezee-webservice-login die een Odoo-administratie niet heeft → de enige
aangewezen weg — "dearchiveer die administratie" uit `CompanyClaim.reden` — was dood).

Gedrag: géén loginvelden. Archiveren laat de `OdooKoppeling` mét de versleutelde API-sleutel STAAN (besluit 24-09:
`trek_credential_in` raakt alleen de RLZ-credential; een gearchiveerde administratie is geen verwijderde), dus
dearchiveren = dezelfde koppeling opnieuw proben via `odoo_client_voor` (company-poort), company_id moet ongewijzigd
terug-gelezen worden (`res.company` op de gebonden company), probe groen → `probe_rapport`/`probe_op` bijgewerkt en het
rapport terug. Rood of mismatch = `HeractiverenGeweigerd` mét rapport, niets gewijzigd. Een meegegeven login = 422
"niet van toepassing" — niets stil negeren."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.backends.port import Backend, HeractiverenGeweigerd
from app.db.session import scoped_session
from app.odoo.client import OdooFout
from app.odoo.credentials import GeenOdooKoppeling, odoo_client_voor
from app.odoo.models import OdooKoppeling
from app.odoo.probe import voer_probe_uit

logger = logging.getLogger(__name__)

TEKST_LOGIN_NIET_VAN_TOEPASSING = (
    "Een webservice-login is niet van toepassing voor een Odoo-administratie — de opgeslagen Odoo-API-sleutel wordt "
    "hergebruikt; laat de loginvelden leeg"
)


def lees_company_id(client: Any) -> int | None:
    """Het company-id zoals Odoo het terug-leest voor de gebonden company (None = niet leesbaar/onbekend)."""
    try:
        rij = client.read_een("res.company", client.company_id, ["id", "name"])
    except OdooFout:
        return None
    if not rij:
        return None
    try:
        return int(rij.get("id"))
    except (TypeError, ValueError):
        return None


class OdooHeractiveerPort:
    backend = Backend.ODOO

    def heractiveer_probe(
        self,
        *,
        administratie_id: uuid.UUID,
        actor_id: uuid.UUID,
        webservice_username: str | None,
        wachtwoord: str | None,
        client: Any = None,
    ) -> dict[str, str]:
        if (webservice_username or "").strip() or wachtwoord:
            raise HeractiverenGeweigerd(TEKST_LOGIN_NIET_VAN_TOEPASSING)
        with scoped_session(None) as session:
            rij = session.get(OdooKoppeling, administratie_id)
            if rij is None or not rij.api_key_ciphertext:
                raise HeractiverenGeweigerd(
                    "Deze Odoo-administratie heeft geen (volledige) Odoo-koppeling mét API-sleutel meer — "
                    "koppel opnieuw "
                    "via 'Odoo koppelen…' op de detailpagina"
                )
            company_id = int(rij.company_id)
        try:
            eigen = client is None
            client = client or odoo_client_voor(administratie_id)
        except GeenOdooKoppeling as exc:
            raise HeractiverenGeweigerd(str(exc)) from exc
        try:
            p = voer_probe_uit(client)
            teruggelezen = lees_company_id(client) if p.groen else None
        finally:
            if eigen:
                client.close()
        if not p.groen:
            raise HeractiverenGeweigerd(
                f"Odoo-rechten-probe niet groen — niets gewijzigd. {p.rode_regels()}", rapport=p.rapport
            )
        if teruggelezen != company_id:
            raise HeractiverenGeweigerd(
                f"Odoo geeft company {teruggelezen if teruggelezen is not None else 'onbekend'} terug waar de "
                f"koppeling "
                f"company {company_id} verwacht — niets gewijzigd; controleer de koppeling in Odoo",
                rapport=p.rapport,
            )
        with scoped_session(None, actor_id=actor_id) as session:
            rij = session.get(OdooKoppeling, administratie_id)
            assert rij is not None
            rij.probe_rapport = p.rapport
            rij.probe_op = datetime.now(UTC)
            rij.company_naam = p.company_naam or rij.company_naam
        logger.info("Odoo-dearchiveer-probe groen voor %s (company %s)", administratie_id, company_id)
        return dict(p.rapport)
