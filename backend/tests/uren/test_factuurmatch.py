"""Factuurmatch-motor (fase 1, akkoord Peter 2026-08-21): ZZP-factuur vs getekende staat,
bureaufactuur vs som van (uren per ZZP'er × koppeling-tarief), ontbrekend tarief = match
alleen op uren ("geen tarief bekend", geen blokkade), afwijking als vlag, dubbeltelling-
preventie via staten-verrekening, expliciete staten-selectie."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.boekvoorstel import BoekvoorstelRegelData, sla_boekvoorstel_op
from app.documenten.models import DocumentSoort
from app.documenten.storage import LokaleBestandsopslag
from app.uren import factuurmatch, service
from app.uren.models import Factuurmatch, FactuurmatchStaat, VeldwerkerCrediteur
from tests.uren.conftest import maak_gebruiker

JAAR = 2026
WEEK = 30
FACTUURDATUM = date(2026, 8, 7)  # ISO-week 32 — ná de staten-weken


@pytest.fixture
def opslag(tmp_path: Path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")


def maak_goedgekeurde_staat(
    administratie_id: uuid.UUID,
    zzper: uuid.UUID,
    project_id: uuid.UUID,
    uitvoerder: uuid.UUID,
    *,
    week: int = WEEK,
    uren_per_dag: tuple[str, ...] = ("8", "8"),
) -> uuid.UUID:
    maandag = date.fromisocalendar(JAAR, week, 1)
    for i, uren in enumerate(uren_per_dag):
        service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=zzper,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=week,
            datum=maandag + timedelta(days=i),
            uren=Decimal(uren),
            m2=None,
            actor_id=zzper,
        )
    staat = service.dien_week_in(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=week,
        actor_id=zzper,
    )
    service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)
    return staat.id


def maak_factuur(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    *,
    nettos: tuple[str, ...],
    factuurdatum: date = FACTUURDATUM,
    soort: DocumentSoort = DocumentSoort.INKOOPFACTUUR,
) -> uuid.UUID:
    referentie = f"ZZP-{uuid.uuid4().hex[:8]}"
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
        soort=soort,
    )
    sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=factuurdatum,
        totaalbedrag=sum((Decimal(n) for n in nettos), Decimal("0")),
        regels=[
            BoekvoorstelRegelData(
                ledger_id=None,
                taxrate_id=None,
                project_id=None,
                netto_bedrag=Decimal(n),
                btw_bedrag=Decimal("0"),
                omschrijving=None,
            )
            for n in nettos
        ],
    )
    return resultaat.document_id


def koppel_crediteur(
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    vendor_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    *,
    uurtarief: str | None,
) -> None:
    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        session.add(
            VeldwerkerCrediteur(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                vendor_id=vendor_id,
                uurtarief=Decimal(uurtarief) if uurtarief is not None else None,
                gekoppeld_door=beheerder_id,
            )
        )


def zet_bureau_tarief(
    detacheerder: uuid.UUID, zzper: uuid.UUID, beheerder_id: uuid.UUID, *, uurtarief: str | None
) -> None:
    from app.db.models import DetacheerderKoppeling

    with scoped_session(None, actor_id=beheerder_id) as session:
        koppeling = session.get(DetacheerderKoppeling, (detacheerder, zzper))
        koppeling.uurtarief = Decimal(uurtarief) if uurtarief is not None else None


class TestZzpMatch:
    def test_exacte_bedragmatch(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        staat_id = maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat is not None
        assert resultaat.uitkomst == "match"
        assert resultaat.staten_som_uren == Decimal("16")
        assert resultaat.staten_som_bedrag == Decimal("680.00")
        assert resultaat.factuur_bedrag == Decimal("680.00")
        assert resultaat.verschil_bedrag == Decimal("0.00")
        assert resultaat.tarief_ontbreekt is False
        assert resultaat.weekstaat_ids == [staat_id]
        with scoped_session(administratie_id) as session:
            match = session.get(Factuurmatch, document_id)
            assert match is not None and match.uitkomst == "match"
            assert match.details["staten"][0]["weekstaat_id"] == str(staat_id)

    def test_bedragafwijking_is_vlag(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("700.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "afwijking"
        assert resultaat.verschil_bedrag == Decimal("20.00")

    def test_zonder_tarief_match_alleen_uren(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief=None)
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, factuur_uren=Decimal("16")
        )

        assert resultaat.uitkomst == "match_alleen_uren"
        assert resultaat.tarief_ontbreekt is True
        assert resultaat.staten_som_bedrag is None
        assert resultaat.verschil_uren == Decimal("0")
        assert resultaat.details["tarief_ontbreekt_voor"] == ["Milan K."]

    def test_zonder_tarief_en_zonder_uren_niet_toetsbaar(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief=None)
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "niet_toetsbaar"

    def test_kloppend_bedrag_maar_afwijkende_uren_is_afwijking(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, factuur_uren=Decimal("15")
        )

        assert resultaat.uitkomst == "afwijking"
        assert resultaat.verschil_uren == Decimal("-1")

    def test_alleen_goedgekeurde_staten_tellen(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        # Week 31 wél ingediend maar niet gekeurd — telt niet mee.
        maandag = date.fromisocalendar(JAAR, 31, 1)
        service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=31,
            datum=maandag,
            uren=Decimal("8"),
            m2=None,
            actor_id=gekoppelde_zzper,
        )
        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=31,
            actor_id=gekoppelde_zzper,
        )
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.staten_som_uren == Decimal("16")
        assert resultaat.uitkomst == "match"

    def test_staat_na_factuurweek_telt_niet_mee(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=40, uren_per_dag=("8",)
        )
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.staten_som_uren == Decimal("16")  # week 40 (ná ISO-week 32) niet mee
        assert resultaat.uitkomst == "match"

    def test_herberekening_vervangt_staatselectie(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("1020.00",))

        eerste = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)
        assert eerste.uitkomst == "afwijking"

        # Tweede week wordt alsnog goedgekeurd → herberekening telt hem mee en sluit.
        maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=31, uren_per_dag=("8",)
        )
        tweede = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert tweede.uitkomst == "match"
        assert tweede.staten_som_uren == Decimal("24")
        with scoped_session(administratie_id) as session:
            from sqlalchemy import select

            rijen = session.scalars(
                select(FactuurmatchStaat).where(FactuurmatchStaat.document_id == document_id)
            ).all()
            assert len(rijen) == 2  # vervangen, geen residu/duplicaten

    def test_geen_koppeling_of_verkeerde_soort_geeft_none(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        vendor_id = uuid.uuid4()
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("100.00",))
        assert factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id) is None

        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        rapport_id = maak_factuur(
            administratie_id, beheerder_id, opslag, vendor_id, nettos=("100.00",), soort=DocumentSoort.KASSARAPPORT
        )
        assert factuurmatch.bereken_match(administratie_id=administratie_id, document_id=rapport_id, actor_id=beheerder_id) is None


class TestBureauMatch:
    @pytest.fixture
    def tweede_zzper(self, admin_engine: Engine, administratie_id, project_id, beheerder_id) -> uuid.UUID:
        gid = maak_gebruiker(admin_engine, "zzper", "Jesse B.")
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=gid, project_id=project_id, actor_id=beheerder_id
        )
        return gid

    def test_bureaufactuur_som_per_zzper_tarief(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        tweede_zzper,
        gekoppelde_uitvoerder,
        detacheerder,
        beheerder_id,
        opslag,
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)  # 16 u
        maak_goedgekeurde_staat(
            administratie_id, tweede_zzper, project_id, gekoppelde_uitvoerder, uren_per_dag=("8",)
        )  # 8 u
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=gekoppelde_zzper, actor_id=beheerder_id)
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=tweede_zzper, actor_id=beheerder_id)
        zet_bureau_tarief(detacheerder, gekoppelde_zzper, beheerder_id, uurtarief="40.00")
        zet_bureau_tarief(detacheerder, tweede_zzper, beheerder_id, uurtarief="45.00")
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, detacheerder, vendor_id, beheerder_id, uurtarief=None)
        # 16 × 40 + 8 × 45 = 640 + 360 = 1000
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("1000.00",))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "match"
        assert resultaat.staten_som_uren == Decimal("24")
        assert resultaat.staten_som_bedrag == Decimal("1000.00")
        assert resultaat.tarief_ontbreekt is False
        assert len(resultaat.details["leden"]) == 2

    def test_bureaufactuur_ontbrekend_koppeltarief_matcht_alleen_op_uren(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        tweede_zzper,
        gekoppelde_uitvoerder,
        detacheerder,
        beheerder_id,
        opslag,
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)
        maak_goedgekeurde_staat(
            administratie_id, tweede_zzper, project_id, gekoppelde_uitvoerder, uren_per_dag=("8",)
        )
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=gekoppelde_zzper, actor_id=beheerder_id)
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=tweede_zzper, actor_id=beheerder_id)
        zet_bureau_tarief(detacheerder, gekoppelde_zzper, beheerder_id, uurtarief="40.00")
        # tweede_zzper bewust ZONDER tarief (besluit 1: match alleen op uren, geen blokkade)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, detacheerder, vendor_id, beheerder_id, uurtarief=None)
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("1000.00",))

        kloppend = factuurmatch.bereken_match(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, factuur_uren=Decimal("24")
        )
        assert kloppend.uitkomst == "match_alleen_uren"
        assert kloppend.tarief_ontbreekt is True
        assert kloppend.details["tarief_ontbreekt_voor"] == ["Jesse B."]

        afwijkend = factuurmatch.bereken_match(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, factuur_uren=Decimal("30")
        )
        assert afwijkend.uitkomst == "afwijking"


class TestVerrekening:
    def _match_opzet(self, administratie_id, project_id, zzper, uitvoerder, beheerder_id, opslag):
        staat_id = maak_goedgekeurde_staat(administratie_id, zzper, project_id, uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))
        factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)
        return staat_id, vendor_id, document_id

    def test_verrekenen_markeert_staten_en_audit(
        self,
        admin_engine: Engine,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
    ):
        staat_id, _, document_id = self._match_opzet(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )

        verrekend = factuurmatch.verreken_staten(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
        )
        assert verrekend == [staat_id]

        # Idempotent: tweede aanroep doet niets (geen fout, geen dubbel audit-event).
        assert (
            factuurmatch.verreken_staten(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
            )
            == []
        )
        with admin_engine.begin() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'factuurmatch' AND actie = 'staten_verrekend' AND record_id = :doc"
                ),
                {"doc": document_id},
            ).scalar()
        assert audit == 1

    def test_verrekende_staat_telt_nooit_dubbel(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
    ):
        staat_id, vendor_id, document_a = self._match_opzet(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
        )
        factuurmatch.verreken_staten(
            administratie_id=administratie_id, document_id=document_a, actor_id=beheerder_id
        )

        # Herberekening op document A blijft de verrekende staat zien (idempotent).
        opnieuw = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_a, actor_id=beheerder_id)
        assert opnieuw.staten_som_uren == Decimal("16")

        # Een nieuwe factuur B van dezelfde ZZP'er ziet de staat niet meer: som 0 → afwijking.
        document_b = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))
        resultaat_b = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_b, actor_id=beheerder_id)
        assert resultaat_b.staten_som_uren == Decimal("0")
        assert resultaat_b.uitkomst == "afwijking"

        # Expliciet de verrekende staat aanwijzen = zichtbare fout, nooit stil dubbel.
        with pytest.raises(service.OngeldigeInvoer):
            factuurmatch.bereken_match(
                administratie_id=administratie_id, document_id=document_b, actor_id=beheerder_id, weekstaat_ids=[staat_id]
            )

    def test_expliciete_selectie_valideert_gebruiker(
        self,
        admin_engine: Engine,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
    ):
        # Staat van een ándere ZZP'er mag niet in de selectie van deze koppeling.
        andere = maak_gebruiker(admin_engine, "zzper", "Sam V.")
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=andere, project_id=project_id, actor_id=beheerder_id
        )
        andere_staat = maak_goedgekeurde_staat(administratie_id, andere, project_id, gekoppelde_uitvoerder)
        eigen_staat = maak_goedgekeurde_staat(
            administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=31
        )
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))

        resultaat = factuurmatch.bereken_match(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, weekstaat_ids=[eigen_staat]
        )
        assert resultaat.weekstaat_ids == [eigen_staat]
        assert resultaat.uitkomst == "match"

        with pytest.raises(service.OngeldigeInvoer):
            factuurmatch.bereken_match(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, weekstaat_ids=[andere_staat]
            )
