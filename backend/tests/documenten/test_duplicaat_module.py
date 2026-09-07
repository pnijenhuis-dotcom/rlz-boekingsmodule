"""Duplicaat (module) — blok 1 07-09 (besluit Peter: "duplicaten eruit; moet er toch een geboekt worden, dan zoek ik hem
in het archief"; bug: een duplicaat kon GEBOEKT worden omdat alle harde checks live tegen RLZ liepen).

Dekking (opdracht 1g): normalisatie-tabel, categorie (a) bestand / (b) referentie + bedrag / (c) crediteur + referentie,
UBL+PDF-uitzondering (1d), geboekt wint, idempotentie, afmelding respecteren (reden verplicht, audit), RLS
(niet-Beheerder mét scope, cross-administratie nooit duplicaat), backfill dry-run vs echt, archief-statusfilter +
zoeken-chip."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boekvoorstel, duplicaat_afvoer, duplicaat_module, service
from app.documenten.checks import NAAM_DUPLICAAT_MODULE, check_duplicaat_module
from app.documenten.duplicaat_afvoer import normaliseer_referentie
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.zoeken import service as zoeken_service
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_duplicaat_afvoer import REF, TOTAAL, _afwijzing_rij, _audit_acties, _bearer, _upload_met_kop
from tests.documenten.test_vragen import _extra_gebruiker, _status

client = TestClient(app)


# ----------------------------------------------------------------------------- normalisatie (pure)


@pytest.mark.parametrize(
    ("invoer", "verwacht"),
    [
        ("2026-0042", "202642"),
        ("Factuur 2026-0042", "202642"),
        ("FACTUURNR 2026-0042", "202642"),
        ("Factuurnummer: 2026/0042", "202642"),
        ("factuur nr. 2026 0042", "202642"),
        ("F-2026-0042", "f202642"),
        ("f 2026 42", "f202642"),
        ("INV #0042", "42"),
        ("Invoice no. 0042", "42"),
        ("#42", "42"),
        ("No 007", "7"),
        ("20260042", "20260042"),  # aaneengesloten: geen scheidingsteken = geen cijfergroep-strip
        ("  F-2026-0042  ", "f202642"),
        ("Factuur", None),
        ("#", None),
        ("", None),
        (None, None),
        ("0", "0"),
    ],
)
def test_normaliseer_referentie_tabel(invoer: str | None, verwacht: str | None) -> None:
    assert normaliseer_referentie(invoer) == verwacht


def test_check_duplicaat_module_pure() -> None:
    assert check_duplicaat_module(treffers=[]).ok is True
    t = duplicaat_module.Treffer(
        document_id=uuid.uuid4(),
        categorie=duplicaat_module.CATEGORIE_REFERENTIE_BEDRAG,
        status=DocumentStatus.TE_CONTROLEREN,
        bestandsnaam="kopie.pdf",
        aangemaakt_op=__import__("datetime").datetime(2026, 9, 1),
        referentie=REF,
        totaalbedrag=TOTAAL,
        vendor_id=None,
    )
    r = check_duplicaat_module(treffers=[t])
    assert r.naam == NAAM_DUPLICAAT_MODULE and r.ok is False
    assert "kopie.pdf" in r.melding and "dezelfde referentie en hetzelfde totaalbedrag" in r.melding
    assert "geen duplicaat" in r.melding


# ----------------------------------------------------------------------------- fixtures


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


@pytest.fixture
def noodrem_uit(beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=False)


def _noodrem_aan(beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=True)


def _upload_bytes(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    inhoud: bytes,
    naam: str,
) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor_id, opslag=opslag
    ).document_id


def _kop(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str,
    totaal: Decimal,
) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=totaal,
        regels=[],
    )


def _module_check(administratie_id: uuid.UUID, document_id: uuid.UUID):
    rapport = boekvoorstel.voer_checks_uit(
        administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
    )
    return next(r for r in rapport.resultaten if r.naam == NAAM_DUPLICAAT_MODULE)


def _vlag(admin_engine: Engine, document_id: uuid.UUID) -> uuid.UUID | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT mogelijk_duplicaat_van_id FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _hernoem(admin_engine: Engine, document_id: uuid.UUID, naam: str) -> None:
    """Test-only: de vorm (xml/pdf) van een document zetten zonder de intake-keten te doorlopen."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET bestandsnaam = :naam WHERE id = :id"),
            {"naam": naam, "id": document_id},
        )


def _zet_intake_bericht(admin_engine: Engine, document_ids: list[uuid.UUID], *, actor_id: uuid.UUID) -> None:
    bericht_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.intake_bericht (id, message_id, afzender, onderwerp, bron, ontvangen_op, "
                "verwerkt_door, detail) VALUES (:id, :mid, 'x@test.local', 'test', 'eml_upload', now(), :actor, "
                "'{}'::jsonb)"
            ),
            {"id": bericht_id, "mid": f"<{bericht_id}@test>", "actor": actor_id},
        )
        for d in document_ids:
            conn.execute(
                text("UPDATE boekhouding.document SET intake_bericht_id = :b WHERE id = :id"),
                {"b": bericht_id, "id": d},
            )


# ----------------------------------------------------------------------------- categorieën


class TestCategorieen:
    def test_a_zelfde_bestand_wordt_direct_afgevoerd_en_check_blokkeert_zonder_afvoer(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        """Casus 1a (Kempen Facilities 31-08): byte-identiek PDF, tweede exemplaar kon geboekt worden. Nu: de harde
        check "Duplicaat (module)" is rood zolang beide staan (noodrem uit = geen auto-afvoer), en mét de noodrem aan
        gaat het jongste exemplaar bij het eerstvolgende signaal DIRECT af (categorie a, buiten de rem)."""
        inhoud = b"%PDF-1.4 identiek " + uuid.uuid4().bytes
        a = _upload_bytes(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="a.pdf"
        )
        b = _upload_bytes(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="a.pdf"
        )
        assert _vlag(admin_engine, b) == a  # bestaande sha256-vlag
        # Geen kop nodig: de check is rood op het bestand alleen.
        check_b = _module_check(administratie_id, b)
        assert check_b.ok is False and "hetzelfde bestand" in check_b.melding and "a.pdf" in check_b.melding
        check_a = _module_check(administratie_id, a)
        assert check_a.ok is False  # symmetrisch: zolang beide staan blokkeren beide
        # Noodrem aan → afvoer bij het eerstvolgende signaal; het oudste blijft.
        _noodrem_aan(beheerder_id)
        afgevoerd = duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=b)
        assert afgevoerd == [b]
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        rij = _afwijzing_rij(admin_engine, b)
        assert rij is not None and rij["duplicaat_van_document_id"] == a and rij["automatisch"] is True
        assert rij["duplicaat_van_referentie"] == "bestand a.pdf"  # kale bestandsmatch zonder kop
        assert "duplicaat_afgevoerd" in _audit_acties(admin_engine, tabel="document", record_id=b)
        # Ná de afvoer is het origineel weer groen.
        assert _module_check(administratie_id, a).ok is True
        # Idempotent.
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=b) == []
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=a) == []

    def test_b_referentie_variant_en_ander_crediteur_record_zonder_btw(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """ "Factuur 2026-0042" bij crediteur X en "2026-0042" bij crediteur Y (ander record, geen btw-nummers) met
        hetzelfde bedrag = categorie (b) → afgevoerd bij binnenkomst, kruisverwijzing naar het oudste."""
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=uuid.uuid4(),
            referentie="Factuur 2026-0042",
            naam="x.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=uuid.uuid4(),
            referentie="2026-0042",
            naam="y.pdf",
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        rij = _afwijzing_rij(admin_engine, b)
        assert rij is not None and rij["duplicaat_van_document_id"] == a
        assert rij["reden"].startswith("Duplicaat van Factuur 2026-0042 (document x.pdf")

    def test_c_zelfde_crediteur_via_kvk_en_referentie_ander_bedrag_blokkeert_maar_voert_nooit_af(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Twee vendor-records met hetzelfde KvK-nummer, dezelfde referentie, ander bedrag: harde check rood (c), geen
        automatische afvoer, geen één-klik (geen harde match), wél de vlag voor de Mogelijk-duplicaat-tab."""
        from app.documenten.models import CrediteurKenmerk

        v1, v2 = uuid.uuid4(), uuid.uuid4()
        with scoped_session(administratie_id) as session:
            for v in (v1, v2):
                session.add(
                    CrediteurKenmerk(
                        administratie_id=administratie_id, vendor_id=v, kvk_nummer="12345678", kvk_nummer_bron="factuur"
                    )
                )
        a = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=v1, naam="a.pdf"
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=v2,
            totaal=Decimal("99.00"),
            naam="b.pdf",
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        check = _module_check(administratie_id, b)
        assert check.ok is False and "dezelfde crediteur en dezelfde referentie (ander bedrag)" in check.melding
        assert _vlag(admin_engine, b) == a
        with pytest.raises(duplicaat_afvoer.GeenHardeMatch):
            duplicaat_afvoer.voer_af_als_duplicaat(
                administratie_id=administratie_id, document_id=b, actor_id=gescoopte_gebruiker
            )
        stand = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=b)
        assert stand.kandidaat is None
        assert [t.categorie for t in stand.module_treffers] == [duplicaat_module.CATEGORIE_CREDITEUR_REFERENTIE]

    def test_1d_ubl_xml_plus_pdf_van_dezelfde_factuur_is_een_bundel_geen_duplicaat(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        """Zelfde naamstam (2026-8151.xml + 2026-8151.pdf) én daarna óók zelfde intake-bericht: dezelfde referentie +
        bedrag, maar de check blijft groen en de afvoer raakt ze nooit — nabundelen is de weg. Een derde, kale PDF
        met dezelfde kop is wél een duplicaat (van de PDF)."""
        vendor = uuid.uuid4()
        xml = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="tmp.pdf",
        )
        _hernoem(admin_engine, xml, "2026-8151.xml")
        pdf = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="2026-8151.pdf",
        )
        assert _module_check(administratie_id, xml).ok is True
        assert _module_check(administratie_id, pdf).ok is True
        _noodrem_aan(beheerder_id)
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=pdf) == []
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=xml) == []
        # Zelfde bericht, andere stam: nog steeds een bundelpaar.
        _hernoem(admin_engine, xml, "factuur-data.xml")
        _zet_intake_bericht(admin_engine, [xml, pdf], actor_id=gescoopte_gebruiker)
        assert _module_check(administratie_id, pdf).ok is True
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=pdf) == []
        # Een derde, losse PDF met dezelfde kop is wél een duplicaat — van de PDF (zelfde vorm), niet van de XML.
        kopie = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="kopie.pdf",
        )
        assert _status(admin_engine, kopie) == DocumentStatus.AFGEWEZEN.value
        rij = _afwijzing_rij(admin_engine, kopie)
        assert rij is not None and rij["duplicaat_van_document_id"] in (pdf, xml)
        assert _status(admin_engine, pdf) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, xml) == DocumentStatus.TE_CONTROLEREN.value

    def test_geboekt_exemplaar_wint_ook_als_het_jonger_is(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        vendor = uuid.uuid4()
        oud = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="oud.pdf",
        )
        jong = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="jong.pdf",
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, jong)
            assert document is not None
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)
        _noodrem_aan(beheerder_id)
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=oud) == [oud]
        assert _status(admin_engine, jong) == DocumentStatus.GEBOEKT.value
        rij = _afwijzing_rij(admin_engine, oud)
        assert rij is not None and rij["duplicaat_van_document_id"] == jong
        assert "al geboekt" in rij["reden"]
        # Het geboekte origineel heeft geen module-tegenhangers meer (het duplicaat is afgevoerd = uitgesloten); de
        # checks zelf draaien niet op een bevroren (geboekt) document, dus rechtstreeks via de motor.
        assert (
            duplicaat_module.treffers_voor_document(
                administratie_id=administratie_id,
                document_id=jong,
                vendor_id=vendor,
                referentie=REF,
                totaalbedrag=TOTAAL,
            )
            == []
        )


# ----------------------------------------------------------------------------- afmelding (mens-override)


class TestAfmelding:
    def test_afmelden_maakt_check_groen_voor_dit_paar_en_auto_afvoer_respecteert_het(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        vendor = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="a.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="b.pdf",
        )
        assert _module_check(administratie_id, b).ok is False
        # Reden verplicht (422), daarna afmelden mét reden via de router (niet-Beheerder mét scope).
        pad = f"/administraties/{administratie_id}/documenten/{b}/duplicaat-afmelden"
        r = client.post(pad, json={"reden": ""}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert r.status_code == 422
        r = client.post(
            pad,
            json={"reden": "Deelfactuur 2 van 2 met hetzelfde nummer"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["tegenhangers"] == [str(a)]
        # Beide kanten groen; vlag weg; audit oud→nieuw; noodrem aan → geen afvoer meer voor dit paar.
        assert _module_check(administratie_id, b).ok is True
        assert _module_check(administratie_id, a).ok is True
        assert _vlag(admin_engine, b) is None
        assert "duplicaat_afgemeld" in _audit_acties(admin_engine, tabel="document", record_id=b)
        _noodrem_aan(beheerder_id)
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=b) == []
        assert duplicaat_afvoer.verwerk_na_signaal(administratie_id=administratie_id, document_id=a) == []
        stand = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=b)
        assert stand.afmelding is not None and stand.afmelding.reden.startswith("Deelfactuur")
        # Een NIEUW derde exemplaar blokkeert weer (en wordt afgevoerd — van het oudste, a).
        c = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="c.pdf",
        )
        assert _status(admin_engine, c) == DocumentStatus.AFGEWEZEN.value
        # Niets af te melden → 409.
        r = client.post(
            f"/administraties/{administratie_id}/documenten/{a}/duplicaat-afmelden",
            json={"reden": "x"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 409


# ----------------------------------------------------------------------------- RLS / scope


class TestScope:
    def test_cross_administratie_is_nooit_duplicaat_en_scope_blijft_de_waarheid(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=andere
        )
        inhoud = b"%PDF-1.4 cross " + uuid.uuid4().bytes
        a = _upload_bytes(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="a.pdf"
        )
        b = _upload_bytes(
            administratie_id=andere, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="a.pdf"
        )
        vendor = uuid.uuid4()
        _kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            document_id=a,
            vendor_id=vendor,
            referentie=REF,
            totaal=TOTAAL,
        )
        _kop(
            administratie_id=andere,
            actor_id=gescoopte_gebruiker,
            document_id=b,
            vendor_id=vendor,
            referentie=REF,
            totaal=TOTAAL,
        )
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        assert _module_check(administratie_id, a).ok is True
        assert _module_check(andere, b).ok is True
        assert _vlag(admin_engine, b) is None
        # Een niet-Beheerder MÉT scope ziet alleen zijn eigen administratie in de verzameling.
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            verz = duplicaat_module.laad_verzameling(session, administratie_id=administratie_id)
        assert set(verz.koppen) == {a}
        # Zonder scope: 403 op het afmeld-endpoint, geen effect.
        derde = _extra_gebruiker(admin_engine, met_scope_op=None, beheerder_id=beheerder_id)
        r = client.post(
            f"/administraties/{administratie_id}/documenten/{a}/duplicaat-afmelden",
            json={"reden": "x"},
            headers=_bearer(derde, rol="boekhouding"),
        )
        assert r.status_code == 403


# ----------------------------------------------------------------------------- backfill


class TestBackfill:
    def test_dry_run_telt_zonder_te_schrijven_echt_voert_af_en_is_idempotent(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        noodrem_uit: None,
    ) -> None:
        vendor = uuid.uuid4()
        inhoud = b"%PDF-1.4 backfill " + uuid.uuid4().bytes
        a = _upload_bytes(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="s.pdf"
        )
        b = _upload_bytes(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, inhoud=inhoud, naam="s.pdf"
        )
        c = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="c.pdf",
        )
        d = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="d.pdf",
        )
        # Bundelpaar (beschermd) én een (c)-geval (niet afvoerbaar) tellen niet als af te voeren.
        x = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            referentie="U-1",
            naam="u.pdf",
        )
        _hernoem(admin_engine, x, "u.xml")
        y = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            referentie="U-1",
            naam="u.pdf",
        )
        # Noodrem UIT → de backfill weigert zichtbaar.
        [u] = duplicaat_afvoer.backfill(dry_run=True, administratie_id=administratie_id)
        assert u.gestopt_reden is not None and "noodrem" in u.gestopt_reden
        _noodrem_aan(beheerder_id)
        [u] = duplicaat_afvoer.backfill(dry_run=True, administratie_id=administratie_id)
        assert u.naam and u.kandidaten == 4 and u.af_te_voeren == 2 and u.afgevoerd == 0
        assert u.overgeslagen == {"zelf het origineel van zijn groep": 2}
        assert u.bundelparen_beschermd == 2
        for doc in (a, b, c, d, x, y):
            assert _status(admin_engine, doc) == DocumentStatus.TE_CONTROLEREN.value  # dry-run schrijft niets
        [u] = duplicaat_afvoer.backfill(dry_run=False, administratie_id=administratie_id)
        assert u.af_te_voeren == 2 and u.afgevoerd == 2
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, c) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, d) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, x) == DocumentStatus.TE_CONTROLEREN.value
        assert _status(admin_engine, y) == DocumentStatus.TE_CONTROLEREN.value
        with admin_engine.connect() as conn:
            backfill_events = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE actie = 'duplicaat_afgevoerd' "
                    "AND (nieuwe_waarde->>'backfill')::boolean IS TRUE AND record_id IN (:b, :d)"
                ),
                {"b": b, "d": d},
            ).scalar_one()
        assert backfill_events == 2
        [u] = duplicaat_afvoer.backfill(dry_run=False, administratie_id=administratie_id)
        assert u.af_te_voeren == 0 and u.afgevoerd == 0  # idempotent


# ----------------------------------------------------------------------------- archief + zoeken


class TestArchiefEnZoeken:
    def test_afgevoerd_filter_toont_het_duplicaat_met_origineel_en_heropenen_haalt_terug(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        vendor = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="orig.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor,
            naam="dup.pdf",
        )
        assert _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        koppen = _bearer(gescoopte_gebruiker, rol="boekhouding")
        # Default archief (geboekt) toont 'm niet; statusfilter afgevoerd wél, mét origineel.
        r = client.get(f"/administraties/{administratie_id}/archief", headers=koppen)
        assert r.status_code == 200 and r.json()["totaal"] == 0
        r = client.get(f"/administraties/{administratie_id}/archief?status=afgevoerd", headers=koppen)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totaal"] == 1
        [rij] = body["documenten"]
        assert rij["document_id"] == str(b) and rij["status"] == "afgewezen" and rij["geboekt_op"] is None
        assert rij["afgevoerd_als_duplicaat_van"]["document_id"] == str(a)
        assert rij["afgevoerd_als_duplicaat_van"]["referentie"] == REF
        assert rij["afgevoerd_als_duplicaat_van"]["bestandsnaam"] == "orig.pdf"
        assert rij["afgevoerd_als_duplicaat_van"]["automatisch"] is True
        # Kantoorbreed (B4) idem.
        r = client.get("/archief?status=afgevoerd", headers=koppen)
        assert r.status_code == 200 and r.json()["totaal"] == 1
        assert r.json()["documenten"][0]["afgevoerd_als_duplicaat_van"]["document_id"] == str(a)
        r = client.get("/archief?status=onzin", headers=koppen)
        assert r.status_code == 422
        # Zoeken draagt de chip.
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker,
            rol=__import__("app.db.models", fromlist=["GebruikerRol"]).GebruikerRol.BOEKHOUDING,
            term="dup.pdf",
        )
        hit = next(h for h in resultaat.documenten if h.document_id == b)
        assert hit.afgevoerd_als_duplicaat_van is not None and hit.afgevoerd_als_duplicaat_van.document_id == a
        # "Terug naar werkvoorraad" = heropenen: uit het afgevoerd-filter, check blijft rood tot afmelding.
        r = client.post(f"/administraties/{administratie_id}/documenten/{b}/heropenen", headers=koppen)
        assert r.status_code == 200, r.text
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        r = client.get(f"/administraties/{administratie_id}/archief?status=afgevoerd", headers=koppen)
        assert r.json()["totaal"] == 0
        assert _module_check(administratie_id, b).ok is False
