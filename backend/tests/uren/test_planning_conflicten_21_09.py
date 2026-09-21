"""Planning — conflictenpaneel mét handeling + dubbele veldwerkers op harde sleutels (opdracht Peter 21-09;
migratie 0169).

Backend-deel: (1) `bevestig_conflict` — "Beide (halve dagen)" zet álle kaartjes van persoon × dag op
½ en legt een akkoord vast mét de planningsstand (gesorteerde project-id's) + reden; idempotent op
dezelfde stand; nieuwe stand = nieuw akkoord; soort afwezig zonder dubbele planning; 404 zonder
planning; 422 zonder dubbel/zonder reden; audit. (2) Leesroute draagt `conflict_akkoorden`. (3)
Bulkroute accepteert bron `conflict` ("Houd ‹project›" = de andere kaartjes weg, audit mét bron).
(4) Rolpoort + scope op de nieuwe route. (5) Dubbelen-detector: alleen harde sleutels
(KvK/IBAN/e-mail) — naamgelijkenis en planningspatroon NOOIT (correctie Peter 21-09: broers in één
ploeg)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.session import scoped_session
from app.documenten.models import LeverancierIban
from app.main import app
from app.security.tokens import create_access_token
from app.uren import dubbelen, planning, service
from app.uren.models import VeldwerkerCrediteur, VeldwerkerDossier
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI = date(2026, 8, 17), date(2026, 8, 18)
VANDAAG = date(2026, 8, 10)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"), {"a": actie}
            ).mappings()
        ]


def _dagdelen(
    admin_engine: Engine, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, datum: date
) -> dict[str, str]:
    with admin_engine.begin() as conn:
        return {
            str(r[0]): r[1]
            for r in conn.execute(
                text(
                    "SELECT project_id, dagdeel FROM boekhouding.planning_toewijzing "
                    "WHERE administratie_id = :a AND gebruiker_id = :g AND datum = :d"
                ),
                {"a": administratie_id, "g": gebruiker_id, "d": datum},
            ).all()
        }


def _plan(administratie_id, gebruiker_id, project_id, datum, actor_id) -> None:  # noqa: ANN001
    planning.plan_toewijzing(
        administratie_id=administratie_id,
        gebruiker_id=gebruiker_id,
        project_id=project_id,
        datum=datum,
        actor_id=actor_id,
    )


class TestConflictAkkoord:
    def test_beide_halve_dagen_zet_dagdelen_en_legt_akkoord_vast_idempotent(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper, tweede_project_id, MA, beheerder_id)
        a1 = planning.bevestig_conflict(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            datum=MA,
            soort="dubbel",
            reden="Ochtend Eindhoven, middag Tilburg — afgesproken met de uitvoerder",
            halve_dagen=True,
            actor_id=beheerder_id,
        )
        assert a1.soort == "dubbel"
        assert a1.project_ids == sorted([str(project_id), str(tweede_project_id)])
        assert _dagdelen(admin_engine, administratie_id, zzper, MA) == {
            str(project_id): "half",
            str(tweede_project_id): "half",
        }
        # Audit: één akkoord-rij + twee dagdeel-rijen mét bron conflict_akkoord.
        akkoord_audit = _audit(admin_engine, "planning_conflict_akkoord")
        assert len(akkoord_audit) == 1
        assert akkoord_audit[0]["nieuwe_waarde"]["halve_dagen"] is True
        assert sorted(akkoord_audit[0]["nieuwe_waarde"]["dagdeel_gewijzigd_projecten"]) == a1.project_ids
        dagdeel_audit = [
            r
            for r in _audit(admin_engine, "planning_dagdeel_gezet")
            if r["nieuwe_waarde"].get("bron") == "conflict_akkoord"
        ]
        assert len(dagdeel_audit) == 2
        # Idempotent: dezelfde stand nog eens = dezelfde rij terug, geen tweede audit.
        a2 = planning.bevestig_conflict(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            datum=MA,
            soort="dubbel",
            reden="nog eens",
            halve_dagen=True,
            actor_id=beheerder_id,
        )
        assert a2.id == a1.id
        assert len(_audit(admin_engine, "planning_conflict_akkoord")) == 1
        # Leesroute draagt het akkoord.
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        assert [a.id for a in data.conflict_akkoorden] == [a1.id]
        assert data.conflict_akkoorden[0].project_ids == a1.project_ids

    def test_nieuwe_planningsstand_geeft_nieuw_akkoord_oude_blijft_staan(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper, tweede_project_id, MA, beheerder_id)
        a1 = planning.bevestig_conflict(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            datum=MA,
            soort="dubbel",
            reden="bewust",
            actor_id=beheerder_id,
        )
        assert _dagdelen(admin_engine, administratie_id, zzper, MA) == {
            str(project_id): "heel",
            str(tweede_project_id): "heel",
        }
        derde = uuid.uuid4()
        from tests.uren.conftest import maak_project

        derde = maak_project(admin_engine, administratie_id, "26030 Scherpenzeel")
        _plan(administratie_id, zzper, derde, MA, beheerder_id)
        a2 = planning.bevestig_conflict(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            datum=MA,
            soort="dubbel",
            reden="drie halve",
            actor_id=beheerder_id,
        )
        assert a2.id != a1.id and len(a2.project_ids) == 3
        with admin_engine.begin() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM boekhouding.planning_conflict_akkoord WHERE administratie_id = :a"),
                {"a": administratie_id},
            ).scalar_one()
        assert n == 2  # nooit DELETE — historie blijft

    def test_afwezig_akkoord_zonder_dubbele_planning_en_foutpaden(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        with pytest.raises(service.NietGevonden):
            planning.bevestig_conflict(
                administratie_id=administratie_id,
                gebruiker_id=zzper,
                datum=MA,
                soort="afwezig",
                reden="toch",
                actor_id=beheerder_id,
            )
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        a = planning.bevestig_conflict(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            datum=MA,
            soort="afwezig",
            reden="komt tóch een halve dag",
            actor_id=beheerder_id,
        )
        assert a.soort == "afwezig" and a.project_ids == [str(project_id)]
        with pytest.raises(service.OngeldigeInvoer):
            planning.bevestig_conflict(
                administratie_id=administratie_id,
                gebruiker_id=zzper,
                datum=MA,
                soort="dubbel",
                reden="geen dubbel",
                actor_id=beheerder_id,
            )
        with pytest.raises(service.OngeldigeInvoer):
            planning.bevestig_conflict(
                administratie_id=administratie_id,
                gebruiker_id=zzper,
                datum=MA,
                soort="afwezig",
                reden="  ",
                actor_id=beheerder_id,
            )
        with pytest.raises(service.OngeldigeInvoer):
            planning.bevestig_conflict(
                administratie_id=administratie_id,
                gebruiker_id=zzper,
                datum=MA,
                soort="te_groot",
                reden="x y z",
                actor_id=beheerder_id,
            )

    def test_route_rolpoort_scope_en_200(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper, tweede_project_id, MA, beheerder_id)
        payload = {
            "administratie_id": str(administratie_id),
            "gebruiker_id": str(zzper),
            "datum": MA.isoformat(),
            "soort": "dubbel",
            "reden": "Beide halve dagen, afgesproken",
            "halve_dagen": True,
        }
        pad = f"/uren/kantoor/planning/conflict-akkoord?administratie_id={administratie_id}"
        assert client.post(pad, json=payload, headers=_bearer(zzper, rol="zzper")).status_code == 403
        zonder = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zonder, administratie_id=administratie_id)
        assert client.post(pad, json=payload, headers=_bearer(zonder, rol="boekhouding")).status_code == 403
        met_recht = maak_gebruiker(admin_engine, "boekhouding", "Met Recht Geen Scope")
        service.zet_meerwerk_recht(gebruiker_id=met_recht, ingeschakeld=True, actor_id=beheerder_id)
        assert client.post(pad, json=payload, headers=_bearer(met_recht, rol="boekhouding")).status_code == 403
        assert _dagdelen(admin_engine, administratie_id, zzper, MA) == {
            str(project_id): "heel",
            str(tweede_project_id): "heel",
        }
        r = client.post(pad, json=payload, headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 200, r.text
        assert r.json()["soort"] == "dubbel" and len(r.json()["project_ids"]) == 2
        # Te korte reden = 422 (pydantic min_length).
        assert (
            client.post(
                pad, json={**payload, "reden": "ok"}, headers=_bearer(beheerder_id, rol="beheerder")
            ).status_code
            == 422
        )
        # Leesroute draagt het akkoord.
        week = client.get(
            f"/uren/kantoor/planning?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert week.status_code == 200
        assert len(week.json()["conflict_akkoorden"]) == 1

    def test_houd_project_via_bulkroute_bron_conflict(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        """ "Houd ‹A›" = de andere kaartjes van die persoon × dag weg via de bestaande bulkroute mét bron `conflict`."""
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper, tweede_project_id, MA, beheerder_id)
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(zzper, tweede_project_id, MA, "heel")],
            bron="conflict",
            verwijderen=True,
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in res.resultaten] == ["gedaan"]
        assert _dagdelen(admin_engine, administratie_id, zzper, MA) == {str(project_id): "heel"}
        verwijderd = _audit(admin_engine, "planning_verwijderd")
        assert verwijderd and verwijderd[-1]["nieuwe_waarde"]["bron"] == "conflict"
        # Ongedaan = dezelfde set terug (idempotent patroon): de kaart staat er weer.
        planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(zzper, tweede_project_id, MA, "heel")],
            bron="ongedaan",
            correlatie_id=res.correlatie_id,
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert set(_dagdelen(admin_engine, administratie_id, zzper, MA)) == {str(project_id), str(tweede_project_id)}
        with pytest.raises(service.OngeldigeInvoer):
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=[(zzper, project_id, MA, "heel")],
                bron="paneel",
                actor_id=beheerder_id,
            )


class TestDubbelenHardeSleutels:
    def test_puur_alleen_harde_sleutels_nooit_naam(self):
        g1, g2, g3, g4 = (uuid.uuid4() for _ in range(4))
        vw = [
            # Broers: zelfde achternaam, zelfde ploeg — GEEN kandidaat (correctie Peter 21-09).
            dubbelen.VeldwerkerSleutels(g1, "M. Demir", "zzper", "m@x.nl", None, ()),
            dubbelen.VeldwerkerSleutels(g2, "R. Demir", "zzper", "r@x.nl", None, ()),
            # Zelfde KvK = kandidaat, ook al lijken de namen nergens op elkaar.
            dubbelen.VeldwerkerSleutels(g3, "Z.V. Panchev", "zzper", "z@x.nl", "68750110", ("NL91ABNA0417164300",)),
            dubbelen.VeldwerkerSleutels(
                g4, "Jan de Vries", "uitvoerder", "j@x.nl", "68750110", ("NL91ABNA0417164300",)
            ),
        ]
        k = dubbelen.kandidaten_uit_sleutels(vw)
        assert [(x.sleutel, x.waarde) for x in k] == [("iban", "NL91ABNA0417164300"), ("kvk", "68750110")]
        assert all(set(x.gebruiker_ids) == {g3, g4} for x in k)
        # Alleen namen gelijk → niets.
        assert dubbelen.kandidaten_uit_sleutels(vw[:2]) == []
        # Identieke naam mét eigen sleutels → óók niets (naam is geen sleutel).
        assert (
            dubbelen.kandidaten_uit_sleutels(
                [
                    dubbelen.VeldwerkerSleutels(g1, "V. Ponchev", "zzper", "a@x.nl", "11111111", ()),
                    dubbelen.VeldwerkerSleutels(g2, "V. Ponchev", "zzper", "b@x.nl", "22222222", ()),
                ]
            )
            == []
        )
        assert "telefoon" in dubbelen.NIET_TOETSBAAR

    def test_normalisatie(self):
        assert dubbelen.normaliseer_kvk("6875 0110") == "68750110"
        assert dubbelen.normaliseer_iban("nl91 abna 0417 1643 00") == "NL91ABNA0417164300"
        assert dubbelen.normaliseer_e_mail("  Piet@Test.NL ") == "piet@test.nl"
        assert dubbelen.normaliseer_kvk(None) is None and dubbelen.normaliseer_iban("") is None

    def test_rapport_uit_de_database_kvk_en_iban_via_crediteur(
        self, admin_engine, administratie_id, zzper, uitvoerder, beheerder_id
    ):
        derde = maak_gebruiker(admin_engine, "zzper", "Ali Y.")
        for g in (zzper, uitvoerder, derde):
            auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=g, administratie_id=administratie_id)
        vendor_a, vendor_b = uuid.uuid4(), uuid.uuid4()
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(VeldwerkerDossier(administratie_id=administratie_id, gebruiker_id=zzper, kvk_nummer="68750110"))
            session.add(
                VeldwerkerDossier(administratie_id=administratie_id, gebruiker_id=uitvoerder, kvk_nummer="68750110")
            )
            session.add(VeldwerkerDossier(administratie_id=administratie_id, gebruiker_id=derde, kvk_nummer="12345678"))
            session.add(
                VeldwerkerCrediteur(
                    administratie_id=administratie_id,
                    gebruiker_id=zzper,
                    vendor_id=vendor_a,
                    gekoppeld_door=beheerder_id,
                )
            )
            session.add(
                VeldwerkerCrediteur(
                    administratie_id=administratie_id,
                    gebruiker_id=derde,
                    vendor_id=vendor_b,
                    gekoppeld_door=beheerder_id,
                )
            )
            session.add(
                LeverancierIban(
                    administratie_id=administratie_id, vendor_id=vendor_a, iban="NL91ABNA0417164300", bron="rlz_seed"
                )
            )
            session.add(
                LeverancierIban(
                    administratie_id=administratie_id,
                    vendor_id=vendor_b,
                    iban="NL91 ABNA 0417 1643 00",
                    bron="rlz_seed",
                )
            )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            r = dubbelen.rapport_voor_administratie(
                session, administratie_id=administratie_id, administratie_naam="Test"
            )
        assert r.aantal_veldwerkers == 3 and r.aantal_met_kvk == 3 and r.aantal_met_iban == 2
        assert [(k.sleutel, k.waarde, set(k.gebruiker_ids)) for k in r.kandidaten] == [
            ("iban", "NL91ABNA0417164300", {zzper, derde}),
            ("kvk", "68750110", {zzper, uitvoerder}),
        ]
        regels = dubbelen.rapportregels(r)
        assert any("KANDIDAAT kvk=68750110" in x for x in regels) and any(
            "niet toetsbaar: telefoon" in x for x in regels
        )

    def test_cli_lees_only_geen_write(self, admin_engine, administratie_id, zzper, beheerder_id, capsys):
        from app import cli

        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
        with admin_engine.begin() as conn:
            voor = conn.execute(text("SELECT count(*) FROM platform.audit_event")).scalar_one()
        assert cli.main(["veldwerkers-dubbelen", "--administratie", str(administratie_id)]) == 0
        uit = capsys.readouterr().out
        assert (
            "TOTAAL 0 kandidaat-cluster(s) over 1 veldwerker(s)" in uit and "geen kandidaten op harde sleutels" in uit
        )
        assert cli.main(["veldwerkers-dubbelen"]) == 2  # precies één van --administratie/--alles
        with admin_engine.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.audit_event")).scalar_one() == voor
