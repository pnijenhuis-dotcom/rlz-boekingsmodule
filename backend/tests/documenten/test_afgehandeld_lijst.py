"""Definitieve aanvulling blok 3 (bundel 08-09, Peter): eindstatussen `samengevoegd`, `afgevoerd_duplicaat`,
`verwijderd` en `afgewezen` staan standaard NIET in de documentenlijst (en dus niet in de "Alle"-teller, die de
lijst telt); één toggle `toon_afgehandeld` haalt ze erbij mét reden en verwijzing ("→ samengevoegd in ‹document›",
"→ duplicaat van ‹document›"); het echte document draagt "N exemplaren samengevoegd"; een huls is nooit te boeken
of aan te bieden (409). Regressie-casus: Floor Bouwliftenservice 26219 (één document + twee hulzen) en Universal
Nederland RLZ-2080143037 (één document + één UBL-huls) — de live Universal-Steigerbouw-situatie van 08-09."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.accordering import service as accordering_service
from app.db.session import scoped_session
from app.documenten import afwijzen, service
from app.documenten.models import Document, DocumentStatus
from app.documenten.statusmachine import _TOEGESTANE_OVERGANGEN
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, zet_schema

client = TestClient(app)

FLOOR_DOCUMENT = "Floor Bouwliftenservice - 26219 - 2026-07-20.pdf"
FLOOR_HULS_1 = "Floor Bouwliftenservice - 26219 - 2026-07-20 (2).pdf"
FLOOR_HULS_2 = "Floor Bouwliftenservice - 26219 - 2026-07-20 (3).pdf"
UNIVERSAL_DOCUMENT = "Universal Nederland B.V - RLZ-2080143037 - 2026-08-01.xml"
UNIVERSAL_HULS = "Universal Nederland B.V - RLZ-2080143037 - 2026-08-01.pdf"


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _upload(actor: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=uuid.uuid4().bytes, actor_id=actor, opslag=opslag
    ).document_id


def _maak_huls(administratie_id: uuid.UUID, actor: uuid.UUID, huls_id: uuid.UUID, leidend_id: uuid.UUID) -> None:
    """Zoals de nabundel-motor: terminaal `samengevoegd` mét `samengevoegd_in_id` naar het leidende document."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, huls_id)
        assert document is not None
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.SAMENGEVOEGD,
            actor_id=actor,
            detail={"samengevoegd_in": str(leidend_id)},
        )
        document.samengevoegd_in_id = leidend_id
        session.commit()


def _casus(actor: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag) -> dict[str, uuid.UUID]:
    """Floor 26219: document + twee hulzen; Universal Nederland RLZ-2080143037: document + één huls; plus een
    verwijderd document (reden "dubbel") en een afgevoerd duplicaat mét app-origineel."""
    ids = {
        "floor": _upload(actor, administratie_id, opslag, FLOOR_DOCUMENT),
        "floor_huls_1": _upload(actor, administratie_id, opslag, FLOOR_HULS_1),
        "floor_huls_2": _upload(actor, administratie_id, opslag, FLOOR_HULS_2),
        "universal": _upload(actor, administratie_id, opslag, UNIVERSAL_DOCUMENT),
        "universal_huls": _upload(actor, administratie_id, opslag, UNIVERSAL_HULS),
        "verwijderd": _upload(actor, administratie_id, opslag, "dubbel-geupload.pdf"),
        "afgevoerd": _upload(actor, administratie_id, opslag, "duplicaat-van-floor.pdf"),
    }
    _maak_huls(administratie_id, actor, ids["floor_huls_1"], ids["floor"])
    _maak_huls(administratie_id, actor, ids["floor_huls_2"], ids["floor"])
    _maak_huls(administratie_id, actor, ids["universal_huls"], ids["universal"])
    service.verwijder_document(
        administratie_id=administratie_id, document_id=ids["verwijderd"], actor_id=actor, reden="dubbel"
    )
    afwijzen.wijs_af(
        administratie_id=administratie_id,
        document_id=ids["afgevoerd"],
        actor_id=actor,
        reden="Duplicaat van 26219 (document Floor Bouwliftenservice)",
        duplicaat_van_document_id=ids["floor"],
        duplicaat_van_referentie="26219",
        naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT,
    )
    return ids


class TestAfgehandeldStandaardVerborgen:
    def test_alleen_de_echte_documenten_in_de_lijst_met_exemplaren_chip_en_tellers(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)

        lijst = {item.document.id: item for item in service.lijst_documenten(administratie_id=administratie_id)}
        assert set(lijst) == {ids["floor"], ids["universal"]}
        # Blok 4c herstelrun 08-09: 2 hulzen + 1 als duplicaat afgevoerd exemplaar mét Floor als origineel.
        assert lijst[ids["floor"]].samengevoegde_exemplaren == 3 and lijst[ids["floor"]].afgevoerde_exemplaren == 1
        assert lijst[ids["universal"]].samengevoegde_exemplaren == 1
        assert lijst[ids["floor"]].samengevoegd_in is None and lijst[ids["floor"]].duplicaat_van is None
        # Werkvoorraad-tellers: alleen de twee echte documenten zijn werk.
        klant = service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "X")])[0]
        assert klant.te_controleren == 2
        # De aantallen van het verborgen werk reizen mee (niets verdwijnt stil).
        tellers = service.tel_afgehandeld(administratie_id=administratie_id)
        assert tellers == {
            DocumentStatus.VERWIJDERD: 1,
            DocumentStatus.AFGEWEZEN: 0,
            DocumentStatus.SAMENGEVOEGD: 3,
            DocumentStatus.AFGEVOERD_DUPLICAAT: 1,
            DocumentStatus.GEBOEKT: 0,
            DocumentStatus.GESPLITST: 0,
            DocumentStatus.GEACCORDEERD: 0,
        }

    def test_toon_afgehandeld_geeft_reden_en_verwijzingen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)

        alles = {
            item.document.id: item
            for item in service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        }
        assert set(alles) == set(ids.values())
        for huls, leidend, naam in (
            ("floor_huls_1", "floor", FLOOR_DOCUMENT),
            ("floor_huls_2", "floor", FLOOR_DOCUMENT),
            ("universal_huls", "universal", UNIVERSAL_DOCUMENT),
        ):
            rij = alles[ids[huls]]
            assert rij.document.status is DocumentStatus.SAMENGEVOEGD
            assert rij.samengevoegd_in is not None
            assert rij.samengevoegd_in.document_id == ids[leidend] and rij.samengevoegd_in.bestandsnaam == naam
        assert alles[ids["verwijderd"]].verwijderd_reden == "dubbel"
        afgevoerd = alles[ids["afgevoerd"]]
        assert afgevoerd.document.status is DocumentStatus.AFGEVOERD_DUPLICAAT
        assert afgevoerd.duplicaat_van is not None
        assert afgevoerd.duplicaat_van.document_id == ids["floor"]
        assert afgevoerd.duplicaat_van.bestandsnaam == FLOOR_DOCUMENT

    def test_afgewezen_telt_als_afgehandeld_en_legacy_deeltoggles_blijven_werken(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)
        afgewezen_id = _upload(gescoopte_gebruiker, administratie_id, opslag, "onleesbaar.pdf")
        afwijzen.wijs_af(
            administratie_id=administratie_id, document_id=afgewezen_id, actor_id=gescoopte_gebruiker, reden="onleesbaar"
        )

        standaard = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert afgewezen_id not in standaard
        assert service.tel_afgehandeld(administratie_id=administratie_id)[DocumentStatus.AFGEWEZEN] == 1
        met_verwijderd = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, toon_verwijderd=True)
        }
        assert met_verwijderd == {ids["floor"], ids["universal"], ids["verwijderd"]}
        met_afgevoerd = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, toon_afgevoerd=True)
        }
        assert met_afgevoerd == {
            ids["floor"],
            ids["universal"],
            ids["afgevoerd"],
            ids["floor_huls_1"],
            ids["floor_huls_2"],
            ids["universal_huls"],
        }

    def test_router_lijst_draagt_tellers_verwijzingen_en_exemplaren(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)
        headers = _bearer(gescoopte_gebruiker)

        standaard = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
        assert standaard.status_code == 200, standaard.text
        body = standaard.json()
        assert {d["id"] for d in body["documenten"]} == {str(ids["floor"]), str(ids["universal"])}
        assert body["afgehandeld"] == {
            "verwijderd": 1,
            "afgewezen": 0,
            "samengevoegd": 3,
            "afgevoerd_duplicaat": 1,
            "geboekt": 0,
            "gesplitst": 0,
            "geaccordeerd": 0,
            "totaal": 5,
        }
        assert body["groepen"] == {"kantoor": 2, "wachten": 0, "afgehandeld": 5}
        floor = next(d for d in body["documenten"] if d["id"] == str(ids["floor"]))
        assert floor["samengevoegde_exemplaren"] == 3 and floor["afgevoerde_exemplaren"] == 1
        assert floor["samengevoegd_in"] is None

        alles = client.get(
            f"/administraties/{administratie_id}/documenten", params={"toon_afgehandeld": "true"}, headers=headers
        )
        assert alles.status_code == 200, alles.text
        per_id = {d["id"]: d for d in alles.json()["documenten"]}
        assert len(per_id) == 7
        huls = per_id[str(ids["floor_huls_1"])]
        assert huls["status"] == "samengevoegd"
        assert huls["samengevoegd_in"] == {"document_id": str(ids["floor"]), "bestandsnaam": FLOOR_DOCUMENT}
        assert per_id[str(ids["verwijderd"])]["verwijderd_reden"] == "dubbel"
        assert per_id[str(ids["afgevoerd"])]["duplicaat_van"] == {
            "document_id": str(ids["floor"]),
            "bestandsnaam": FLOOR_DOCUMENT,
        }


class TestHulsNooitTeBoeken:
    def test_boeken_van_een_huls_geeft_409(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)
        for huls in ("floor_huls_1", "universal_huls"):
            resp = client.post(
                f"/administraties/{administratie_id}/documenten/{ids[huls]}/boeken", headers=_bearer(gescoopte_gebruiker)
            )
            assert resp.status_code == 409, resp.text
            assert "samengevoegd" in str(resp.json()["detail"])

    def test_ter_accordering_aanbieden_van_een_huls_geeft_409(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
    ) -> None:
        # Accordering aan mét één laag — anders is het antwoord een 400 "Accordering staat uit" en toetst de
        # test de statuspoort niet.
        accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "S. Bakker")
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
        )
        ids = _casus(gescoopte_gebruiker, administratie_id, opslag)
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/documenten/{ids['floor_huls_2']}/aanbieden",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 409, resp.text
        assert "samengevoegd" in str(resp.json()["detail"])


def _zet_status(administratie_id: uuid.UUID, actor: uuid.UUID, document_id: uuid.UUID, *pad: DocumentStatus) -> None:
    """Loopt de statusmachine af (elke stap gevalideerd) — bv. ontvangen → … → geboekt zonder RLZ-call."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        for naar in pad:
            service._schrijf_overgang(session, document=document, naar=naar, actor_id=actor)
        session.commit()


NAAR_KLAAR = (DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.TE_CONTROLEREN, DocumentStatus.KLAAR_OM_TE_BOEKEN)


class TestBlok11LijstGroepen:
    """Blok 11 herstelrun "Basis eerst" (08-09, besluit Peter): de standaardlijst is kantoorwerk; `geboekt` is
    afgehandeld (achter de toggle, mét boekstuknummer — terugvinden via Archief/Zoeken); ter accordering + open vraag
    vormen de groep "wachten op anderen" die niet in "Alle" telt; tellers per groep reizen mee."""

    def test_elke_status_in_precies_een_groep(self) -> None:
        alle = [*service.KANTOOR_STATUSSEN, *service.WACHTEN_STATUSSEN, *service.AFGEHANDELDE_STATUSSEN]
        assert sorted(alle) == sorted(DocumentStatus), "elke DocumentStatus hoort in exact één lijst-groep"
        assert len(alle) == len(set(alle))
        # Ook een status die de statusmachine kent maar hier zou ontbreken, valt op:
        assert set(_TOEGESTANE_OVERGANGEN) <= set(alle)
        for status in DocumentStatus:
            assert service.groep_van_status(status) in service.LIJST_GROEPEN

    def _casus_groepen(
        self, actor: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> dict[str, uuid.UUID]:
        ids = {
            "werk": _upload(actor, administratie_id, opslag, "werk.pdf"),
            "geboekt": _upload(actor, administratie_id, opslag, "geboekt.pdf"),
            "bij_klant": _upload(actor, administratie_id, opslag, "bij-klant.pdf"),
            "vraag": _upload(actor, administratie_id, opslag, "vraag.pdf"),
        }
        _zet_status(administratie_id, actor, ids["werk"], DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.TE_CONTROLEREN)
        _zet_status(administratie_id, actor, ids["geboekt"], *NAAR_KLAAR, DocumentStatus.GEBOEKT)
        _zet_status(administratie_id, actor, ids["bij_klant"], *NAAR_KLAAR, DocumentStatus.TER_ACCORDERING)
        _zet_status(
            administratie_id, actor, ids["vraag"], DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.VRAAG_OPEN,
        )
        return ids

    def test_geboekt_niet_in_standaardlijst_wel_achter_toggle_en_via_groep(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = self._casus_groepen(gescoopte_gebruiker, administratie_id, opslag)

        standaard = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert ids["geboekt"] not in standaard
        assert standaard == {ids["werk"], ids["bij_klant"], ids["vraag"]}, "kantoor + wachten; afgehandeld verborgen"

        met_toggle = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        }
        assert met_toggle == set(ids.values())

        kantoor = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="kantoor")}
        wachten = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="wachten")}
        afgehandeld = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="afgehandeld")
        }
        assert kantoor == {ids["werk"]}
        assert wachten == {ids["bij_klant"], ids["vraag"]}
        assert afgehandeld == {ids["geboekt"]}
        with pytest.raises(ValueError):
            service.lijst_documenten(administratie_id=administratie_id, groep="onzin")

    def test_tellers_per_groep_en_afgehandeld_incl_geboekt_uit_een_group_by(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        self._casus_groepen(gescoopte_gebruiker, administratie_id, opslag)
        per_status = service.tel_per_status(administratie_id=administratie_id)
        assert service.tel_groepen(administratie_id=administratie_id, per_status=per_status) == {
            "kantoor": 1,
            "wachten": 2,
            "afgehandeld": 1,
        }
        afgehandeld = service.tel_afgehandeld(administratie_id=administratie_id, per_status=per_status)
        assert afgehandeld[DocumentStatus.GEBOEKT] == 1
        # Klantenlijst-tellers (inzicht) blijven ongewijzigd: bij_klant en vragen tellen daar gewoon mee.
        klant = service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "X")])[0]
        assert klant.te_controleren == 1
        assert klant.bij_klant == 1

    def test_router_groep_parameter_en_tellers(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        ids = self._casus_groepen(gescoopte_gebruiker, administratie_id, opslag)
        headers = _bearer(gescoopte_gebruiker)
        basis = f"/administraties/{administratie_id}/documenten"

        standaard = client.get(basis, headers=headers)
        assert standaard.status_code == 200, standaard.text
        body = standaard.json()
        assert {d["id"] for d in body["documenten"]} == {str(ids["werk"]), str(ids["bij_klant"]), str(ids["vraag"])}
        assert body["groepen"] == {"kantoor": 1, "wachten": 2, "afgehandeld": 1}
        assert body["afgehandeld"]["geboekt"] == 1 and body["afgehandeld"]["totaal"] == 1

        per_groep = (("kantoor", {"werk"}), ("wachten", {"bij_klant", "vraag"}), ("afgehandeld", {"geboekt"}))
        for groep, verwacht in per_groep:
            resp = client.get(basis, params={"groep": groep}, headers=headers)
            assert resp.status_code == 200, resp.text
            assert {d["id"] for d in resp.json()["documenten"]} == {str(ids[k]) for k in verwacht}
        assert client.get(basis, params={"groep": "onzin"}, headers=headers).status_code == 422
        # Bestaande deeplink-parameter blijft werken.
        alles = client.get(basis, params={"toon_afgehandeld": "true"}, headers=headers)
        assert {d["id"] for d in alles.json()["documenten"]} == {str(i) for i in ids.values()}
