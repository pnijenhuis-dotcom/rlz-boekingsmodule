# ruff: noqa: F811 — pytest-fixtures als parameters
"""Teller `autoboek_leren` in de reconciliatie (blok A bundel 10-09, A5): stand "aan N van M administraties", gedaan =
automatisch geboekt (bron leverancier_opt_in) in administraties mét schakelaar, detail lerend/actief/uitgezonderd +
activaties/resets, géén dubbele LET-OP (die staat op autoboeken_inkoop), JSON-roundtrip mét detail, DB-laag (RLS) en de
nieuwe reden-categorieën van de AI-toets (api_key / avg_gate / kostengrens)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.reconciliatie import automatiseringen as auto
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

NU = datetime(2026, 9, 10, 4, 30, tzinfo=UTC)


def _uur(n: float) -> datetime:
    return NU - timedelta(hours=n)


def _teller(tellers, sleutel: str) -> auto.Teller:
    return next(t for t in tellers if t.sleutel == sleutel)


class TestBereken:
    def test_uit_zonder_schakelaars(self) -> None:
        aid = uuid.uuid4()
        t = _teller(auto.bereken(auto.Feiten(administraties={aid: "A"}), nu=NU), auto.AUTOBOEK_LEREN)
        assert t.is_uit and t.stand_detail == "0 van 1 administraties"
        assert t.detail == {
            "lerend": 0,
            "actief": 0,
            "uitgezonderd": 0,
            "geactiveerd_24u": 0,
            "gereset_24u": 0,
            "per_administratie": [],
        }
        assert t.label == "Autoboeken per administratie (leren en boeken)"

    def test_volgorde_direct_na_kandidaten(self) -> None:
        sleutels = [t.sleutel for t in auto.bereken(auto.Feiten(), nu=NU)]
        assert sleutels.index(auto.AUTOBOEK_LEREN) == sleutels.index(auto.AUTOBOEK_KANDIDATEN) + 1

    def test_gedaan_overgeslagen_detail_en_geen_dubbele_let_op(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "Aan B.V.", b: "Uit B.V."},
            autoboek_leren_aan={a},
            autoboek_leren_detail={a: {"lerend": 4, "actief": 2, "uitgezonderd": 1}},
            leverancier_optins={a: 2, b: 1},
            audit=[
                auto.AuditFeit("automatisch_geboekt", _uur(1), a, {"bron": "leverancier_opt_in"}),
                auto.AuditFeit("automatisch_geboekt", _uur(2), b, {"bron": "leverancier_opt_in"}),  # zonder schakelaar
                auto.AuditFeit("automatisch_geboekt", _uur(3), a, {"bron": "veldwerker_opt_in"}),  # fase 4, niet hier
                auto.AuditFeit(
                    "autoboeken_geweigerd", _uur(4), a, {"bron": "leverancier_opt_in", "reden": "Volumerem bereikt"}
                ),
                auto.AuditFeit(
                    "autoboeken_geweigerd",
                    _uur(5),
                    a,
                    {"bron": "leverancier_opt_in", "reden": "AI-plausibiliteitstoets: twijfel — x"},
                ),
                auto.AuditFeit("autoboek_leverancier_geactiveerd", _uur(6), a, {"reeks_ongewijzigd": 3}),
                auto.AuditFeit("autoboek_leverancier_gereset", _uur(7), a, {"reden": "storno"}),
                auto.AuditFeit("autoboek_leverancier_geactiveerd", _uur(30), a, {}),  # buiten het etmaal
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.AUTOBOEK_LEREN)
        assert (t.stand, t.stand_detail) == ("deels", "1 van 2 administraties")
        assert (t.dag.verwacht, t.dag.gedaan, t.dag.overgeslagen[auto.VOLUMEREM], t.dag.overgeslagen[auto.TWIJFEL]) == (
            3,
            1,
            1,
            1,
        )
        assert t.detail is not None
        assert (t.detail["lerend"], t.detail["actief"], t.detail["uitgezonderd"]) == (4, 2, 1)
        assert (t.detail["geactiveerd_24u"], t.detail["gereset_24u"]) == (1, 1)
        [rij] = t.detail["per_administratie"]
        assert rij == {
            "administratie_id": str(a),
            "naam": "Aan B.V.",
            "lerend": 4,
            "actief": 2,
            "uitgezonderd": 1,
            "automatisch_geboekt_24u": 1,
        }
        # De volumerem is een harde voorwaarde — de LET-OP hangt op autoboeken_inkoop, niet nog eens op autoboek_leren.
        assert t.harde_voorwaarden == []
        inkoop = _teller(tellers, auto.AUTOBOEK_INKOOP)
        assert [h.categorie for h in inkoop.harde_voorwaarden] == [auto.VOLUMEREM]
        bev = auto.bevindingen(tellers)
        assert [b["detail"]["automatisering"] for b in bev] == [auto.AUTOBOEK_INKOOP]

    def test_json_roundtrip_draagt_detail_en_regels_tonen_de_teller(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "A"},
            autoboek_leren_aan={a},
            autoboek_leren_detail={a: {"lerend": 1, "actief": 0, "uitgezonderd": 0}},
        )
        tellers = auto.bereken(f, nu=NU)
        terug = auto.uit_samenvatting(auto.als_samenvatting(tellers, nu=NU))
        assert _teller(terug, auto.AUTOBOEK_LEREN).detail["lerend"] == 1
        assert _teller(terug, auto.AUTOBOEK_INKOOP).detail is None
        regel = next(r for r in auto.regels(tellers) if "Autoboeken per administratie" in r)
        assert "aan" in regel and "verwacht 0, gedaan 0" in regel

    @pytest.mark.parametrize(
        "reden,categorie",
        [
            ("AI-plausibiliteitstoets: overgeslagen — api_key ontbreekt", auto.API_KEY),
            ("overgeslagen: avg_gate — intake-AI staat uit", auto.AVG_GATE),
            ("overgeslagen: kostengrens — € 100 bereikt", auto.KOSTENGRENS),
            ("AI-plausibiliteitstoets: twijfel — omschrijving past niet", auto.TWIJFEL),
            ("overgeslagen: ai_fout — timeout", auto.FOUT),
        ],
    )
    def test_categoriseer_ai_toets_redenen(self, reden: str, categorie: str) -> None:
        assert auto.categoriseer_reden(reden) == categorie
        assert categorie in auto.REDEN_LABEL
        if categorie in (auto.AVG_GATE, auto.KOSTENGRENS):
            assert categorie in auto.HARDE_VOORWAARDEN and auto.DOEL_PAD[categorie] == "/instellingen/intake-ai"


class TestVerzamel:
    def test_leest_schakelaar_en_leveranciersstand_per_administratie(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.autoboek_kandidaten import service
        from app.beheer import service as beheer_service

        v_actief, v_uit, v_leert = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        beheer_service.zet_autoboeken_leren(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.leverancier_voorkeur (administratie_id, vendor_id, regels_samenvoegen, "
                    "autoboeken_ingeschakeld, autoboeken_bron, autoboeken_uitgezonderd) VALUES "
                    "(:a, :v1, true, true, 'systeem', false), (:a, :v2, true, false, NULL, true)"
                ),
                {"a": administratie_id, "v1": v_actief, "v2": v_uit},
            )
            conn.execute(
                text(
                    "INSERT INTO boekhouding.autoboek_kandidaat_stand (administratie_id, vendor_id, reeks_ongewijzigd, "
                    "correcties, mens_boekingen, open_vragen, kwalificeert, actief, redenen, chips, heroverweeg_signalen) VALUES "
                    "(:a, :v1, 3, 0, 4, 0, false, true, '[]', '[]', '[]'), (:a, :v2, 1, 0, 2, 0, false, false, '[]', '[]', '[]'), "
                    "(:a, :v3, 2, 0, 3, 0, false, false, '[]', '[]', '[]')"
                ),
                {"a": administratie_id, "v1": v_actief, "v2": v_uit, "v3": v_leert},
            )
        feiten = auto.verzamel_feiten(nu=datetime.now(UTC))
        assert administratie_id in feiten.autoboek_leren_aan
        assert feiten.autoboek_leren_detail[administratie_id] == {"lerend": 1, "actief": 1, "uitgezonderd": 1}
        t = _teller(auto.bereken(feiten, nu=datetime.now(UTC)), auto.AUTOBOEK_LEREN)
        assert t.stand == "aan" and t.detail["per_administratie"][0]["administratie_id"] == str(administratie_id)
        # Kempen-regel: doorbelasting → telt als uit, ook al zou de kolom aan staan.
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        assert administratie_id not in auto.verzamel_feiten(nu=datetime.now(UTC)).autoboek_leren_aan
        assert service.haal_instelling_op()[0] >= 1


class TestVerzoekenBlokBEnC:
    """Wensen van blok B (`verzoeken_B_automatiseringen.md`) en blok C (`verzoeken_C_automatiseringen.md`), verwerkt door A."""

    def test_bank_overgeslagen_lijst_telt_met_categorie_en_verwacht_is_gedaan_plus_overgeslagen(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "A"},
            bank_aan={a},
            bank_runs=[
                auto.BankRunFeit(
                    a,
                    _uur(1),
                    {
                        "automatisch_geboekt": 2,
                        "overgeslagen": [
                            "twijfel: 1111 (historie_regel) — omschrijving past niet [eerder getoetst, voorstel ongewijzigd]",
                            "overgeslagen: avg_gate — AI staat platformbreed uit (2222, vaste_regel)",
                            "overgeslagen: kostengrens — AI-maandlimiet bereikt (3333, historie_regel)",
                            "overgeslagen: api_key — geen API-key geconfigureerd (4444, vaste_regel)",
                            "overgeslagen: ai_fout — timeout (5555, vaste_regel)",
                        ],
                    },
                )
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        bank = _teller(tellers, auto.BANK)
        assert (bank.dag.verwacht, bank.dag.gedaan) == (7, 2)
        assert {k: v for k, v in bank.dag.overgeslagen.items() if v} == {
            auto.TWIJFEL: 1,
            auto.AVG_GATE: 1,
            auto.KOSTENGRENS: 1,
            auto.API_KEY: 1,
            auto.FOUT: 1,
        }
        assert sorted(h.categorie for h in bank.harde_voorwaarden) == [auto.API_KEY, auto.AVG_GATE, auto.KOSTENGRENS]
        paden = {b["detail"]["reden"]: b["detail"]["doel_pad"] for b in auto.bevindingen(tellers)}
        assert (
            paden[auto.AVG_GATE] == "/instellingen/intake-ai" and paden[auto.KOSTENGRENS] == "/instellingen/intake-ai"
        )

    def test_ai_plausibiliteit_teller_uit_audit_zonder_eigen_let_op(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "A"},
            intake_ai_aan=True,
            audit=[
                auto.AuditFeit(
                    "ai_plausibiliteitstoets",
                    _uur(1),
                    a,
                    {"soort": "bank_historie", "uitkomst": "plausibel", "reden": "ok"},
                ),
                auto.AuditFeit(
                    "ai_plausibiliteitstoets",
                    _uur(2),
                    a,
                    {"soort": "factuur_autoboeking", "uitkomst": "twijfel", "reden": "x"},
                ),
                auto.AuditFeit(
                    "ai_plausibiliteitstoets",
                    _uur(3),
                    a,
                    {"soort": "bank_vaste_regel", "uitkomst": "overgeslagen", "reden": "api_key — geen API-key"},
                ),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.AI_PLAUSIBILITEIT)
        assert (t.stand, t.dag.verwacht, t.dag.gedaan, t.dag.overgeslagen[auto.API_KEY]) == ("aan", 3, 2, 1)
        assert t.harde_voorwaarden == [] and auto.bevindingen(tellers) == []
        uit = _teller(auto.bereken(auto.Feiten(administraties={a: "A"}), nu=NU), auto.AI_PLAUSIBILITEIT)
        assert uit.is_uit and "avg_gate" in (uit.stand_detail or "")

    def test_bank_sync_historie_fouten_tellen_als_fout(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "A"},
            bank_rlz_verbinding={a},
            bank_sync_runs=[auto.BankSyncRunFeit(a, _uur(1), "klaar", None, "sync_alles", historie_fouten=3)],
        )
        t = _teller(auto.bereken(f, nu=NU), auto.BANK_SYNC)
        assert t.dag.gedaan == 1 and t.dag.overgeslagen[auto.FOUT] == 3 and t.harde_voorwaarden == []

    def test_eerste_sync_weigering_is_let_op_credential_met_deeplink_en_fout_reden(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        reden = "Niet alle onderdelen gelukt: Ledgers. LET OP: Reeleezee weigert de opgeslagen webservice-login (HTTP 403) op Ledgers"
        f = auto.Feiten(
            administraties={a: "Nieuw B.V.", b: "Klaar B.V."},
            eerste_sync_runs=[
                auto.EersteSyncFeit(a, _uur(2), "fout", geweigerd=True, fout_reden=reden),
                auto.EersteSyncFeit(b, _uur(3), "klaar"),
                auto.EersteSyncFeit(b, _uur(4), "fout", geweigerd=False, fout_reden="Afgebroken — geen voortgang"),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.EERSTE_SYNC)
        assert (
            t.stand,
            t.dag.verwacht,
            t.dag.gedaan,
            t.dag.overgeslagen[auto.CREDENTIAL],
            t.dag.overgeslagen[auto.FOUT],
        ) == ("op_aanvraag", 3, 1, 1, 1)
        [bev] = auto.bevindingen(tellers, namen=f.administraties)
        assert bev["administratie_id"] == a and bev["detail"]["reden"] == auto.CREDENTIAL
        assert bev["detail"]["doel_pad"] == f"/instellingen/administraties/{a}" and bev["detail"]["voorbeeld"] == reden
        assert bev["detail"]["administratie_naam"] == "Nieuw B.V."

    def test_verzamel_leest_eerste_sync_en_intake_ai(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.intake_instelling SET ai_ingeschakeld = true"))
            conn.execute(
                text(
                    "INSERT INTO boekhouding.administratie_sync_run (id, administratie_id, status, beeindigd_op, onderdelen, fout_reden) "
                    "VALUES (:i, :a, 'fout', now() - interval '1 hour', "
                    '\'{"Ledgers": {"status": "fout", "http_status": 403, "rlz_recht": "Grootboek lezen"}}\', '
                    "'LET OP: Reeleezee weigert de opgeslagen webservice-login (HTTP 403) op Ledgers')"
                ),
                {"i": uuid.uuid4(), "a": administratie_id},
            )
        feiten = auto.verzamel_feiten(nu=datetime.now(UTC))
        assert feiten.intake_ai_aan is True
        [es] = [e for e in feiten.eerste_sync_runs if e.administratie_id == administratie_id]
        assert es.status == "fout" and es.geweigerd is True and "HTTP 403" in (es.fout_reden or "")
