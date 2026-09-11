"""Bewakingsprobe `rls_weigering` + reconciliatie-LET-OP "systeemfout — automatisch gemeld" (blok 1 run 11-09 middag).

De bron is het audit-event `rls_weigering` (app/db/rls_weigering.py); de probe telt rijen in de laatste 24 u, de
reconciliatie maakt er per route-patroon één beheer-LET-OP van (systeemmail, nooit de kantoor-actiemail) mét deeplink
naar het geraakte document en een leesbare tekst zonder GUID's."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from app.bewaking import service
from app.config import settings
from app.db import rls_weigering
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.reconciliatie.run import Bevinding, is_beheer_signaal, is_regressie

ADMIN = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
DOC = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
ROUTE = f"/administraties/{ADMIN}/documenten/{DOC}/verplaats"


def _fout(tabel: str = "document") -> ProgrammingError:
    return ProgrammingError(
        "UPDATE", {}, InsufficientPrivilege(f'new row violates row-level security policy for table "{tabel}"')
    )


def _registreer(route: str = ROUTE, tabel: str = "document", gebruiker: uuid.UUID | None = None) -> uuid.UUID:
    cid = uuid.uuid4()
    assert rls_weigering.registreer(
        exc=_fout(tabel), route=route, methode="POST", correlatie_id=cid, gebruiker_id=gebruiker
    )
    return cid


class TestHerkenning:
    def test_vindt_insufficient_privilege_door_orig_cause_en_context(self) -> None:
        binnen = _fout()
        try:
            try:
                raise binnen
            except ProgrammingError as e:
                raise RuntimeError("wrapper") from e
        except RuntimeError as buiten:
            assert rls_weigering.vind_insufficient_privilege(buiten) is binnen.orig
        assert rls_weigering.vind_insufficient_privilege(RuntimeError("x")) is None
        assert rls_weigering.vind_insufficient_privilege(None) is None
        assert rls_weigering.tabel_uit_melding(str(binnen.orig)) == "document"
        assert rls_weigering.tabel_uit_melding('permission denied for relation "vraag"') == "vraag"
        assert rls_weigering.tabel_uit_melding("iets anders") is None

    def test_registreer_negeert_andere_fouten(self, admin_engine: Engine) -> None:
        assert (
            rls_weigering.registreer(exc=RuntimeError("x"), route="/x", methode="GET", correlatie_id=uuid.uuid4())
            is False
        )
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.audit_event WHERE actie = 'rls_weigering'")
                ).scalar_one()
                == 0
            )

    def test_route_patroon_en_deeplink(self) -> None:
        assert rls_weigering.route_patroon(ROUTE) == "/administraties/{id}/documenten/{id}/verplaats"
        assert rls_weigering.doel_pad_voor_route(ROUTE) == f"/documenten/{ADMIN}/{DOC}"
        assert rls_weigering.doel_pad_voor_route("/bank/x") == "/reconciliatie"

    def test_gebruiker_uit_bearer(self) -> None:
        from app.security.tokens import create_access_token

        gid = uuid.uuid4()
        assert rls_weigering.gebruiker_uit_bearer(f"Bearer {create_access_token(gid, rol='boekhouding')}") == gid
        assert rls_weigering.gebruiker_uit_bearer("Bearer kapot") is None
        assert rls_weigering.gebruiker_uit_bearer(None) is None


class TestProbe:
    def test_zonder_rijen_ok_met_rij_fout_met_route_en_code(self) -> None:
        nu = datetime.now(UTC)
        assert service._probe_rls_weigering(nu).status == "ok"
        cid = _registreer()
        u = service._probe_rls_weigering(nu + timedelta(minutes=1))
        assert u.status == "fout"
        assert "1 RLS-weigering(en)" in (u.detail or "")
        assert ROUTE in (u.detail or "") and "tabel document" in (u.detail or "") and str(cid) in (u.detail or "")
        # Ná 24 u telt de rij niet meer → groen (de storing sluit via de statemachine, met herstelmelding).
        assert service._probe_rls_weigering(nu + timedelta(hours=25)).status == "ok"

    def test_staat_in_de_kwartierrun(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "bewaking_service_resource", None)
        monkeypatch.setattr(service, "_probe_health", lambda: service.ProbeUitkomst(soort="health", status="ok"))
        monkeypatch.setattr(
            service, "_probe_documentopslag", lambda: service.ProbeUitkomst(soort="documentopslag", status="ok")
        )
        monkeypatch.setattr(service, "_probe_rlz", lambda: service.ProbeUitkomst(soort="rlz", status="ok"))
        monkeypatch.setattr(service, "_probe_ai", lambda: service.ProbeUitkomst(soort="ai", status="ok"))
        monkeypatch.setattr(service, "_verzend_alert", lambda **kw: True)
        statussen = service.voer_probes_uit(nu=datetime.now(UTC) + timedelta(days=400))
        assert statussen["rls_weigering"] == "ok"


class TestReconciliatieLetOp:
    def test_een_let_op_per_route_patroon_beheer_niet_regressie_leesbaar(self) -> None:
        nu = datetime.now(UTC)
        gebruiker = uuid.uuid4()
        _registreer(gebruiker=gebruiker)
        cid2 = _registreer(route=f"/administraties/{uuid.uuid4()}/documenten/{uuid.uuid4()}/verplaats", tabel="vraag")
        _registreer(route="/bank/x/boek", tabel="bank_mutatie")
        bev = auto.rls_weigering_bevindingen(nu=nu + timedelta(minutes=1))
        assert [b["detail"]["route_patroon"] for b in bev] == [
            "POST /administraties/{id}/documenten/{id}/verplaats",
            "POST /bank/x/boek",
        ]
        verplaats = bev[0]
        assert verplaats["soort"] == "let_op" and verplaats["administratie_id"] is None
        assert verplaats["detail"]["reden"] == auto.RLS_WEIGERING and verplaats["detail"]["aantal"] == 2
        assert verplaats["detail"]["tabel"] == "document, vraag"
        assert verplaats["detail"]["correlatie_id"] == str(cid2)  # de jongste wint
        assert verplaats["detail"]["doel_pad"].startswith("/documenten/")
        assert (
            auto.REGRESSIE_TEKST in verplaats["tekst"] and "RLS-weigering op POST /administraties" in verplaats["tekst"]
        )
        b = Bevinding(
            blok=verplaats["blok"],
            soort=verplaats["soort"],
            administratie_id=None,
            vingerafdruk=verplaats["vingerafdruk"],
            tekst=verplaats["tekst"],
            detail=verplaats["detail"],
        )
        assert is_beheer_signaal(b) and not is_regressie(b)
        lees = teksten.leesbaar(b, administratie_naam=None)
        assert lees.titel.startswith("RLS-weigering") and "Systeemfout — automatisch gemeld" in lees.doe
        assert "2× in 24 u" in lees.wat and "document, vraag" in lees.wat
        assert not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)
        # Vingerafdruk stabiel per route-patroon (mailt één keer), en weg ná het etmaal.
        assert (
            auto.rls_weigering_bevindingen(nu=nu + timedelta(hours=2))[0]["vingerafdruk"] == verplaats["vingerafdruk"]
        )
        assert auto.rls_weigering_bevindingen(nu=nu + timedelta(hours=25)) == []

    def test_registreer_zet_de_let_op_op_de_verzamelaar(self) -> None:
        from app.reconciliatie.run import Verzamelaar

        _registreer()
        verzamelaar = Verzamelaar()
        verzamelaar.start_blok(auto.BLOK)
        auto.registreer(verzamelaar, nu=datetime.now(UTC) + timedelta(minutes=1))
        assert any((b.detail or {}).get("reden") == auto.RLS_WEIGERING for b in verzamelaar.bevindingen), [
            b.tekst for b in verzamelaar.bevindingen
        ]
