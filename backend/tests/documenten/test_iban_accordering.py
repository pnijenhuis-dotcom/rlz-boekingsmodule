"""IBAN-wissel vier-ogen-accordering (docs/ontwerp/iban-wissel-accordering.md): aanbieden
blokkeert boeken; accorderen alleen door een bevoegde accordeur ≠ aanvrager (vier ogen,
server-side) → IBAN vertrouwd + herkomst-status hersteld; buiten de set of aanvrager-zelf =
geweigerd; lege instelling → beheerder mag; afwijzen met verplichte reden houdt het document
geblokkeerd; audit op alle drie. Geldpad, dus elk pad expliciet — zelfde testopzet als
test_vragen.py/test_afwijzen.py."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken, boekvoorstel, iban_accordering, service
from app.documenten.models import DocumentStatus, IbanAccorderingStatus, IbanSoort
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.test_iban_wissel import _regel
from tests.documenten.test_vragen import _extra_gebruiker, _status, _zet_document_op

_HERKOMSTEN = [
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
]

NIEUW_IBAN = "NL91ABNA0417164300"


def _audit_acties(admin_engine: Engine, accordering_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'iban_accordering' "
                    "AND record_id = :id ORDER BY tijdstip"
                ),
                {"id": accordering_id},
            )
            .scalars()
            .all()
        )


def _vertrouwde_rijen(admin_engine: Engine, vendor_id: uuid.UUID) -> list[tuple[str, str, uuid.UUID | None]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT iban, bron, bevestigd_door FROM boekhouding.leverancier_iban "
                "WHERE vendor_id = :vendor ORDER BY aangemaakt_op"
            ),
            {"vendor": vendor_id},
        ).all()
    return [(r.iban, r.bron, r.bevestigd_door) for r in rijen]


@pytest.fixture
def vendor_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def document_met_voorstel(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
) -> uuid.UUID:
    """Geüpload document (te_controleren) mét boekvoorstel + crediteur — de toestand waarin een
    IBAN-wissel-blokkade in de praktijk optreedt."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur-iban-wissel.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=vendor_id,
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


@pytest.fixture
def accordeur_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    """Actieve collega mét scope, ingesteld als enige IBAN-accordeur."""
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    iban_accordering.zet_accordeurs(
        administratie_id=administratie_id, actor_id=beheerder_id, accordeurs=[gid]
    )
    return gid


def _bied_aan(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> iban_accordering.AccorderingData:
    return iban_accordering.bied_aan(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        nieuw_iban=NIEUW_IBAN,
        soort=IbanSoort.G_REKENING,
    )


class TestAanbieden:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_zet_document_op_wachtstatus_vanuit_elke_herkomst_en_blokkeert_boeken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        admin_engine: Engine,
        herkomst: DocumentStatus,
    ) -> None:
        _zet_document_op(
            admin_engine,
            administratie_id=administratie_id,
            document_id=document_met_voorstel,
            actor_id=gescoopte_gebruiker,
            herkomst=herkomst,
        )
        data = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        assert data.status == IbanAccorderingStatus.OPEN.value
        assert data.status_voor_accordering == herkomst.value
        assert data.aangevraagd_door == gescoopte_gebruiker
        assert data.nieuw_iban == NIEUW_IBAN
        assert (
            _status(admin_engine, document_met_voorstel) == DocumentStatus.WACHT_OP_IBAN_ACCORDERING.value
        )

        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_met_voorstel, actor_id=gescoopte_gebruiker
            )

    def test_ongeldig_iban_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        from app.documenten.leverancier_iban import OngeldigIban

        with pytest.raises(OngeldigIban):
            iban_accordering.bied_aan(
                administratie_id=administratie_id,
                document_id=document_met_voorstel,
                actor_id=gescoopte_gebruiker,
                nieuw_iban="NL00FOUT0000000000",
                soort=IbanSoort.REGULIER,
            )
        assert _status(admin_engine, document_met_voorstel) == DocumentStatus.TE_CONTROLEREN.value

    def test_al_vertrouwd_iban_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        from app.documenten.leverancier_iban import bevestig_iban

        bevestig_iban(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            iban=NIEUW_IBAN,
            actor_id=gescoopte_gebruiker,
        )
        with pytest.raises(iban_accordering.IbanAlVertrouwd):
            _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        assert _status(admin_engine, document_met_voorstel) == DocumentStatus.TE_CONTROLEREN.value

    def test_tweede_open_aanvraag_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
    ) -> None:
        _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.ErIsAlEenOpenAccordering):
            _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)


class TestAccorderen:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_geldige_accordeur_maakt_iban_vertrouwd_en_herstelt_herkomst(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
        herkomst: DocumentStatus,
    ) -> None:
        _zet_document_op(
            admin_engine,
            administratie_id=administratie_id,
            document_id=document_met_voorstel,
            actor_id=gescoopte_gebruiker,
            herkomst=herkomst,
        )
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        data = iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=accordeur_id
        )
        assert data.status == IbanAccorderingStatus.GEACCORDEERD.value
        assert data.besloten_door == accordeur_id
        assert data.document_status == herkomst
        assert _status(admin_engine, document_met_voorstel) == herkomst.value
        # IBAN in de vertrouwde set, bron=bevestigd, besluter als bevestiger.
        assert _vertrouwde_rijen(admin_engine, vendor_id) == [(NIEUW_IBAN, "bevestigd", accordeur_id)]

    def test_aanvrager_mag_eigen_aanvraag_niet_accorderen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
    ) -> None:
        """Vier-ogen: óók als de aanvrager zelf in de accordeur-set zit, blijft zijn eigen
        aanvraag voor hem verboden terrein."""
        iban_accordering.zet_accordeurs(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            accordeurs=[accordeur_id, gescoopte_gebruiker],
        )
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.VierOgenGeschonden):
            iban_accordering.accordeer(
                administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=gescoopte_gebruiker
            )
        # Niets veranderd: aanvraag open, document geblokkeerd, geen vertrouwd IBAN.
        assert (
            _status(admin_engine, document_met_voorstel) == DocumentStatus.WACHT_OP_IBAN_ACCORDERING.value
        )
        assert _vertrouwde_rijen(admin_engine, vendor_id) == []

    def test_buiten_de_accordeur_set_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        accordeur_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Bij een niet-lege set telt uitsluitend de set — ook een collega mét scope (en zelfs
        een beheerder buiten de set) is dan niet bevoegd."""
        buiten_set = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.GeenBevoegdeAccordeur):
            iban_accordering.accordeer(
                administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=buiten_set
            )
        with pytest.raises(iban_accordering.GeenBevoegdeAccordeur):
            iban_accordering.accordeer(
                administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=beheerder_id
            )
        assert _vertrouwde_rijen(admin_engine, vendor_id) == []

    def test_lege_instelling_valt_terug_op_beheerder(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        data = iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=beheerder_id
        )
        assert data.status == IbanAccorderingStatus.GEACCORDEERD.value
        assert _vertrouwde_rijen(admin_engine, vendor_id) == [(NIEUW_IBAN, "bevestigd", beheerder_id)]

    def test_lege_instelling_niet_beheerder_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        collega = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.GeenBevoegdeAccordeur):
            iban_accordering.accordeer(
                administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=collega
            )

    def test_boeken_weer_mogelijk_tot_aan_de_checks(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Na accorderen is de status-poort naar boeken weer open: een boekpoging strandt niet
        meer op OngeldigeBoekpoging (maar verderop — hier op de RLZ-credentials van de
        testomgeving), precies zoals vóór het aanbieden."""
        from app.rlz.credentials import GeenRlzCredentials

        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=accordeur_id
        )
        with pytest.raises((GeenRlzCredentials, boeken.BoekenFout)) as excinfo:
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_met_voorstel, actor_id=gescoopte_gebruiker
            )
        assert not isinstance(excinfo.value, boeken.OngeldigeBoekpoging)


class TestAfwijzen:
    def test_afwijzen_met_reden_houdt_document_geblokkeerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        vendor_id: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        data = iban_accordering.wijs_af(
            administratie_id=administratie_id,
            accordering_id=aanvraag.id,
            actor_id=accordeur_id,
            reden="Rekeningnummer wijkt af van het contract — eerst telefonisch verifiëren bij de leverancier",
        )
        assert data.status == IbanAccorderingStatus.AFGEWEZEN.value
        assert data.besloten_door == accordeur_id
        assert data.afwijs_reden is not None
        # Document blijft geblokkeerd (gemarkeerd verdacht via de afgewezen aanvraag).
        assert (
            _status(admin_engine, document_met_voorstel) == DocumentStatus.WACHT_OP_IBAN_ACCORDERING.value
        )
        assert _vertrouwde_rijen(admin_engine, vendor_id) == []
        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_met_voorstel, actor_id=gescoopte_gebruiker
            )

    @pytest.mark.parametrize("reden", ["", "   ", "\n\t"])
    def test_afwijzen_zonder_reden_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
        reden: str,
    ) -> None:
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.AfwijsRedenVerplicht):
            iban_accordering.wijs_af(
                administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=accordeur_id, reden=reden
            )
        # Aanvraag blijft gewoon open (beslisbaar) — de weigering liet niets achter.
        nog_open = iban_accordering.lijst_accorderingen(
            administratie_id=administratie_id,
            status=IbanAccorderingStatus.OPEN,
            document_id=document_met_voorstel,
        )
        assert len(nog_open) == 1

    def test_afwijzen_vereist_ook_vier_ogen_en_bevoegdheid(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        buiten_set = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with pytest.raises(iban_accordering.VierOgenGeschonden):
            iban_accordering.wijs_af(
                administratie_id=administratie_id,
                accordering_id=aanvraag.id,
                actor_id=gescoopte_gebruiker,
                reden="Eigen aanvraag afwijzen",
            )
        with pytest.raises(iban_accordering.GeenBevoegdeAccordeur):
            iban_accordering.wijs_af(
                administratie_id=administratie_id,
                accordering_id=aanvraag.id,
                actor_id=buiten_set,
                reden="Buiten de set",
            )

    def test_afwijzing_en_heraanvraag_staan_in_de_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """De afwijzing (wie + reden) en de nieuwe ronde zijn zichtbaar in de document-
        geschiedenis zelf (mockup-tijdlijn), niet alleen in het audit_event — beide zonder
        statusovergang (van=naar op de wachtstatus)."""
        eerste = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.wijs_af(
            administratie_id=administratie_id,
            accordering_id=eerste.id,
            actor_id=accordeur_id,
            reden="Eerst navragen bij de leverancier",
        )
        _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND (detail ? 'iban_afgewezen' OR detail ? 'iban_aangeboden') "
                    "ORDER BY tijdstip"
                ),
                {"id": document_met_voorstel},
            ).all()
        assert [r.detail.get("iban_aangeboden", False) or None for r in rijen] == [True, None, True]
        afwijzing = rijen[1]
        assert afwijzing.detail["iban_afgewezen"] is True
        assert afwijzing.detail["reden"] == "Eerst navragen bij de leverancier"
        assert afwijzing.van_status == afwijzing.naar_status == "wacht_op_iban_accordering"

    def test_na_afwijzing_kan_een_nieuwe_aanvraag_met_zelfde_herkomst(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Bewuste keuze 2 (ontwerpnotitie): geen doodlopende status — na een afwijzing mag een
        nieuwe vier-ogen-ronde, de herkomst reist mee van de vorige aanvraag."""
        eerste = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.wijs_af(
            administratie_id=administratie_id,
            accordering_id=eerste.id,
            actor_id=accordeur_id,
            reden="Eerst navragen",
        )
        tweede = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        assert tweede.status_voor_accordering == eerste.status_voor_accordering
        data = iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=tweede.id, actor_id=accordeur_id
        )
        assert _status(admin_engine, document_met_voorstel) == DocumentStatus.TE_CONTROLEREN.value
        assert data.status == IbanAccorderingStatus.GEACCORDEERD.value


class TestInstelling:
    def test_accordeur_buiten_scope_geweigerd(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        buitenstaander = _extra_gebruiker(admin_engine, met_scope_op=None, beheerder_id=beheerder_id)
        with pytest.raises(iban_accordering.AccordeurBuitenScope):
            iban_accordering.zet_accordeurs(
                administratie_id=administratie_id, actor_id=beheerder_id, accordeurs=[buitenstaander]
            )
        assert iban_accordering.haal_accordeurs_op(administratie_id=administratie_id) == []

    def test_set_vervangen_met_audit(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        a = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        b = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        iban_accordering.zet_accordeurs(administratie_id=administratie_id, actor_id=beheerder_id, accordeurs=[a])
        iban_accordering.zet_accordeurs(
            administratie_id=administratie_id, actor_id=beheerder_id, accordeurs=[b]
        )
        assert iban_accordering.haal_accordeurs_op(administratie_id=administratie_id) == [b]
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'iban_accordeur' "
                        "AND record_id = :id ORDER BY tijdstip"
                    ),
                    {"id": administratie_id},
                )
                .scalars()
                .all()
            )
        assert acties == ["iban_accordeurs_gewijzigd", "iban_accordeurs_gewijzigd"]


class TestAudit:
    def test_audit_op_aanbieden_accorderen_en_afwijzen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        eerste = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.wijs_af(
            administratie_id=administratie_id,
            accordering_id=eerste.id,
            actor_id=accordeur_id,
            reden="Eerst navragen",
        )
        assert _audit_acties(admin_engine, eerste.id) == [
            "iban_accordering_aangeboden",
            "iban_accordering_afgewezen",
        ]
        tweede = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=tweede.id, actor_id=accordeur_id
        )
        assert _audit_acties(admin_engine, tweede.id) == [
            "iban_accordering_aangeboden",
            "iban_accordering_geaccordeerd",
        ]

    def test_besliste_aanvraag_niet_opnieuw_beslisbaar(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_met_voorstel: uuid.UUID,
        accordeur_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        aanvraag = _bied_aan(administratie_id, document_met_voorstel, gescoopte_gebruiker)
        iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=aanvraag.id, actor_id=accordeur_id
        )
        with pytest.raises(iban_accordering.GeenOpenAccordering):
            iban_accordering.wijs_af(
                administratie_id=administratie_id,
                accordering_id=aanvraag.id,
                actor_id=accordeur_id,
                reden="Toch afwijzen",
            )


class TestZonderCrediteur:
    def test_aanbieden_zonder_crediteur_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-zonder-crediteur.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(iban_accordering.GeenCrediteurOpVoorstel):
            _bied_aan(administratie_id, resultaat.document_id, gescoopte_gebruiker)
        assert _status(admin_engine, resultaat.document_id) == DocumentStatus.TE_CONTROLEREN.value
