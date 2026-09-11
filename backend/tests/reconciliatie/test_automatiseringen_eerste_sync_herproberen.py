# ruff: noqa: F811 — pytest-fixtures als parameters
"""Teller `eerste_sync_herproberen` (blok 3 run 11-09 middag): wachtende runs zichtbaar als `rechten_onderweg`
(geen LET-OP — het systeem handelt zelf), herpogingen als verwacht/gedaan, en ná 24 u nog rood = harde voorwaarde
`rechten_na_24u` mét deeplink naar Instellingen › Administraties › ‹administratie› (actiemail, leesbare tekst)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

NU = datetime(2026, 9, 12, 4, 30, tzinfo=UTC)
BODY = '{"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}'


def _uur(n: float) -> datetime:
    return NU - timedelta(hours=n)


def _teller(tellers: list[auto.Teller], sleutel: str) -> auto.Teller:
    return next(t for t in tellers if t.sleutel == sleutel)


class TestBereken:
    def test_wachtende_run_is_zichtbaar_overgeslagen_zonder_let_op(self) -> None:
        aid = uuid.uuid4()
        f = auto.Feiten(
            administraties={aid: "Baard beheer & management"},
            eerste_sync_runs=[
                auto.EersteSyncFeit(
                    aid,
                    _uur(1),
                    "rechten_onderweg",
                    geweigerd=True,
                    pogingen=2,
                    volgende_poging_op=NU + timedelta(minutes=9),
                )
            ],
            audit=[
                auto.AuditFeit("eerste_sync_herpoging_gestart", _uur(1.2), aid, {"poging": 2, "aanleiding": "wekker"}),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.EERSTE_SYNC_HERPROBEREN)
        assert t.stand == "altijd" and "elk kwartier" in (t.stand_detail or "")
        assert t.dag.overgeslagen == {auto.RECHTEN_ONDERWEG: 1}
        assert t.dag.verwacht == 2 and t.dag.gedaan == 1  # 1 wachtend (overgeslagen) + 1 gestarte herpoging (gedaan)
        assert t.harde_voorwaarden == []
        assert not [
            b for b in auto.bevindingen(tellers) if b["detail"]["automatisering"] == auto.EERSTE_SYNC_HERPROBEREN
        ]
        # de bestaande eerste-sync-teller telt een wachtende run niet als fout
        assert _teller(tellers, auto.EERSTE_SYNC).dag.overgeslagen.get(auto.CREDENTIAL, 0) == 0

    def test_na_24_uur_rood_is_harde_voorwaarde_met_deeplink_naar_de_administratie(self) -> None:
        aid = uuid.uuid4()
        reden = (
            "Na 24 uur herproberen (25 pogingen sinds 11-09-2026 10:00 UTC) weigert Reeleezee nog steeds. "
            f'RLZ zegt: "{BODY}"'
        )
        f = auto.Feiten(
            administraties={aid: "Box Beheer B.V."},
            eerste_sync_runs=[auto.EersteSyncFeit(aid, _uur(2), "fout", geweigerd=True, fout_reden=reden, pogingen=25)],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.EERSTE_SYNC_HERPROBEREN)
        assert t.dag.overgeslagen[auto.RECHTEN_NA_24U] == 1
        [hv] = t.harde_voorwaarden
        assert hv.categorie == auto.RECHTEN_NA_24U and hv.administratie_id == aid
        assert auto.RECHTEN_NA_24U in auto.HARDE_VOORWAARDEN and auto.RECHTEN_NA_24U not in auto.BEHEER_CATEGORIEEN
        [bev] = [
            b for b in auto.bevindingen(tellers, namen=f.administraties) if b["detail"]["reden"] == auto.RECHTEN_NA_24U
        ]
        assert bev["administratie_id"] == aid
        assert bev["detail"]["doel_pad"] == f"/instellingen/administraties/{aid}"
        assert bev["detail"]["administratie_naam"] == "Box Beheer B.V."
        # niet dubbel: de oude teller `eerste_sync` geeft géén tweede credential-LET-OP voor dezelfde run
        assert _teller(tellers, auto.EERSTE_SYNC).harde_voorwaarden == []
        # leesbare tekst (actiemail): titel + handeling RLZ-check / Sync opnieuw starten, letterlijk RLZ-antwoord erin
        lb = teksten.leesbaar(
            type("B", (), {"detail": bev["detail"], "blok": auto.BLOK, "soort": "let_op", "tekst": bev["tekst"]})()
        )
        assert lb.titel.startswith("Eerste sync: RLZ weigert na 24 uur")
        assert "Box Beheer B.V." in lb.wat and "Actie niet toegestaan" in lb.wat
        assert "RLZ-check" in lb.doe and "Sync opnieuw starten" in lb.doe

    def test_eerste_poging_direct_fout_blijft_op_de_oude_teller_en_herpoging_die_slaagt_telt_als_gedaan(self) -> None:
        aid = uuid.uuid4()
        f = auto.Feiten(
            administraties={aid: "Kempen B.V."},
            eerste_sync_runs=[
                auto.EersteSyncFeit(aid, _uur(3), "fout", geweigerd=True, fout_reden="401", pogingen=1),
                auto.EersteSyncFeit(aid, _uur(4), "klaar", pogingen=3),
            ],
            audit=[
                auto.AuditFeit("eerste_sync_herpoging_gestart", _uur(4.5), aid, {"poging": 2, "aanleiding": "wekker"}),
                auto.AuditFeit("eerste_sync_herpoging_gestart", _uur(4.2), aid, {"poging": 3, "aanleiding": "wekker"}),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        oud = _teller(tellers, auto.EERSTE_SYNC)
        assert oud.dag.overgeslagen[auto.CREDENTIAL] == 1 and oud.dag.gedaan == 1
        nieuw = _teller(tellers, auto.EERSTE_SYNC_HERPROBEREN)
        # 2 gestarte herpogingen = gedaan; de uitkomst (klaar) telt op de teller eerste_sync
        assert nieuw.dag.gedaan == 2 and nieuw.dag.verwacht == 2
        assert nieuw.stil is False
        assert nieuw.harde_voorwaarden == []
        regels = auto.regels(tellers)
        assert any("Eerste sync — RLZ zet rechten door" in r for r in regels)


class TestVerzamelFeiten:
    def test_wachtende_run_uit_de_db_komt_als_feit_met_pogingen_en_volgende_poging(
        self, administratie_id: uuid.UUID, admin_engine
    ) -> None:
        volgende = datetime(2026, 9, 12, 5, 0, tzinfo=UTC)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.administratie_sync_run (id, administratie_id, status, aangevraagd_op, "
                    "laatst_actief_op, onderdelen, pogingen, volgende_poging_op) VALUES (:id, :aid, "
                    "'rechten_onderweg', :aangevraagd, :actief, CAST(:o AS jsonb), 2, :volgende)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "aangevraagd": _uur(2),
                    "actief": _uur(1),
                    "o": '{"ledgers": {"status": "rechten_onderweg", "http_status": 403}, '
                    '"taxrates": {"status": "klaar"}}',
                    "volgende": volgende,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO boekhouding.administratie_sync_run (id, administratie_id, status, aangevraagd_op, "
                    "beeindigd_op, onderdelen, pogingen, fout_reden) VALUES (:id, :aid, 'fout', :aangevraagd, :einde, "
                    "CAST(:o AS jsonb), 25, 'Na 24 uur herproberen …')"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "aangevraagd": _uur(30),
                    "einde": _uur(5),
                    "o": '{"ledgers": {"status": "fout", "http_status": 403}}',
                },
            )
        feiten = auto.verzamel_feiten(nu=NU, administratie_ids=[administratie_id])
        per_status = {es.status: es for es in feiten.eerste_sync_runs if es.administratie_id == administratie_id}
        wachtend = per_status["rechten_onderweg"]
        assert wachtend.pogingen == 2 and wachtend.geweigerd is True and wachtend.volgende_poging_op == volgende
        assert wachtend.tijdstip == _uur(1)
        opgegeven = per_status["fout"]
        assert opgegeven.pogingen == 25 and opgegeven.geweigerd is True
        tellers = auto.bereken(feiten, nu=NU)
        t = _teller(tellers, auto.EERSTE_SYNC_HERPROBEREN)
        assert t.dag.overgeslagen[auto.RECHTEN_ONDERWEG] == 1 and t.dag.overgeslagen[auto.RECHTEN_NA_24U] == 1
