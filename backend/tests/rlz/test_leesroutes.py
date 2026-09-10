"""Blok C 10-09 (Baard): de rechten-probe toetst EXACT de leesroutes die de eerste sync gebruikt — fail-closed.

Twee lagen bewijs:
  1. statisch: élk onderdeel in `eerste_sync.ONDERDELEN` heeft een `Leesroute` mét `sync_onderdeel`, en die route zit in
     de probe-set (`PROBE_LEESROUTES`). Een nieuw sync-onderdeel zonder probe-route = rood.
  2. dynamisch: de sync-motoren (`sync_ledgers/taxrates/vendors/projects`, `bank.sync_payment_accounts`) krijgen een
     client die élk opgevraagd pad vastlegt en dan stopt (403-sentinel vóór de DB); élk pad moet, ontdaan van de
     adminId-prefix, in de probe-set of de gedeclareerde afgeleide paden zitten. En omgekeerd: de probe vraagt met een
     gescoped client precies `PROBE_LEESROUTES` op.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.beheer import eerste_sync
from app.credentialstore import service as credentialstore
from app.rlz import leesroutes
from app.rlz.client import RlzApiError, RlzClient


class _Stop(Exception):
    """Sentinel: pad vastgelegd, sync mag niet verder (geen DB nodig)."""


class _RegistrerendeHttpx:
    """Duck-typed httpx.Client: legt method+url vast en antwoordt 403 (niet-retryable) → RlzApiError → de sync stopt
    vóór de DB."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:  # noqa: ANN003
        self.urls.append(url)
        params = kwargs.get("params")
        if params:
            self.urls[-1] = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return httpx.Response(403, text="sentinel", request=httpx.Request(method, "https://x" + url))

    def close(self) -> None:
        pass


def test_elk_eerste_sync_onderdeel_heeft_een_probe_route() -> None:
    ontbrekend = [naam for naam in eerste_sync.ONDERDELEN if naam not in leesroutes.SYNC_LEESROUTES]
    assert not ontbrekend, (
        f"Sync-onderdeel zonder Leesroute in app/rlz/leesroutes.py: {ontbrekend} — voeg de route toe (mét "
        "sync_onderdeel) zodat de rechten-probe 'm toetst vóór de eerste sync erop stukloopt"
    )
    probe_namen = {r.naam for r in leesroutes.PROBE_LEESROUTES}
    for naam in eerste_sync.ONDERDELEN:
        assert leesroutes.SYNC_LEESROUTES[naam].naam in probe_namen
    # compat-alias in de credentialstore volgt dezelfde bron
    assert tuple(r.naam for r in leesroutes.PROBE_LEESROUTES) == credentialstore._TE_PROBEREN_ENDPOINTS
    assert len(leesroutes.PROBE_LEESROUTES) == 10  # "10 leesroutes" in de UI-teksten


@pytest.mark.parametrize("onderdeel", eerste_sync.ONDERDELEN)
def test_sync_motor_vraagt_precies_het_probe_pad_op(onderdeel: str) -> None:
    from app.bank import sync as bank_sync
    from app.sync import service as sync_service

    http = _RegistrerendeHttpx()
    client = RlzClient(username="", password="", admin_id="ADM", client=http)  # type: ignore[arg-type]
    motoren = {
        "ledgers": lambda: sync_service.sync_ledgers(administratie_id=uuid.uuid4(), client=client),
        "taxrates": lambda: sync_service.sync_taxrates(administratie_id=uuid.uuid4(), client=client),
        "vendors": lambda: sync_service.sync_vendors(administratie_id=uuid.uuid4(), client=client),
        "projects": lambda: sync_service.sync_projects(administratie_id=uuid.uuid4(), client=client),
        "payment_accounts": lambda: bank_sync.sync_payment_accounts(administratie_id=uuid.uuid4(), client=client),
    }
    assert set(motoren) == set(eerste_sync.ONDERDELEN), "nieuw sync-onderdeel: motor hier toevoegen"
    with pytest.raises(RlzApiError):
        motoren[onderdeel]()
    assert http.urls, "de motor deed geen enkele GET"
    verwacht = leesroutes.SYNC_LEESROUTES[onderdeel]
    for url in http.urls:
        route = leesroutes.route_voor_pad(url)
        assert route is not None and route.naam == verwacht.naam, (
            f"{onderdeel} vraagt {url!r} op, dat pad zit niet in de probe-set (app/rlz/leesroutes.py)"
        )
    assert http.urls[0] == f"/ADM/{verwacht.pad}" + (
        "?" + "&".join(f"{k}={v}" for k, v in verwacht.params) if verwacht.params else ""
    )


def test_probe_vraagt_precies_de_probe_set_op_met_adminid_prefix() -> None:
    http = _RegistrerendeHttpx()
    root = RlzClient(username="u", password="p", client=http)  # type: ignore[arg-type]
    uitkomst = credentialstore.voer_probe_uit(root, "ADM")
    assert list(uitkomst.rapport) == [r.naam for r in leesroutes.PROBE_LEESROUTES]
    assert http.urls == [("/" if r.scope == "root" else "/ADM/") + r.pad for r in leesroutes.PROBE_LEESROUTES]
    # sentinel-403 overal → per route status + letterlijke melding
    assert set(uitkomst.rapport.values()) == {"403"}
    assert all(m == "HTTP 403 — sentinel" for m in uitkomst.meldingen.values())


def test_route_voor_pad_kent_afgeleide_paden_en_querystrings() -> None:
    assert leesroutes.route_voor_pad("/adm/PaymentAccounts/1234/LastBankImport").naam == "PaymentAccounts"
    assert leesroutes.route_voor_pad("Ledgers?$top=1").naam == "Ledgers"
    assert leesroutes.route_voor_pad("/adm/Onbekend") is None
    assert leesroutes.rlz_recht_voor("Vendors").startswith("leesrecht Relaties")
    with pytest.raises(KeyError, match="geen Leesroute"):
        leesroutes.pad_voor_sync_onderdeel("bestaat_niet")
