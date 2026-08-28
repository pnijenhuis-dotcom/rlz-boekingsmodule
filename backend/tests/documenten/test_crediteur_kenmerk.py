"""Opruimrun 28-08 punt 14 — crediteur-dedup + duplicaat over crediteuren heen (besluiten Peter 27-08):
btw-/KvK-nummer uit de factuur (deterministisch gevalideerd), opslag per crediteur (migratie 0082),
nummer-eerst crediteur-match, blokkerende drievoudige match over ÁLLE crediteuren, oranje signaal op
Reference+bedrag, dubbel-signalering (naam/IBAN/nummer) — nooit auto-samenvoegen of verwijderen."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import crediteur_kenmerk
from app.documenten.checks import check_duplicaat_over_crediteuren
from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer
from app.extractie.controle import VendorKandidaat, match_vendor

# 123456782: 9·1+8·2+7·3+6·4+5·5+4·6+3·7+2·8 − 2 = 154 = 14·11 → elfproef groen
BTW_GELDIG = "NL123456782B01"


class TestBtwNummerValidatie:
    def test_nl_nummer_normalisatie_en_elfproef(self) -> None:
        r = valideer_btw_nummer("btw-nr.: nl 1234.56.782.b01")
        assert r is not None and r.genormaliseerd == BTW_GELDIG and r.nederlands and r.geverifieerd

    def test_nl_nummer_zonder_geldige_proef_wordt_overgenomen_maar_niet_geverifieerd(self) -> None:
        r = valideer_btw_nummer("NL123456789B01")  # elfproef: 155 % 11 = 1 → rood; mod-97 óók rood
        assert r is not None and r.genormaliseerd == "NL123456789B01" and r.geverifieerd is False

    def test_btw_id_natuurlijk_persoon_mod97(self) -> None:
        # Construeer een nummer dat de mod-97-toets haalt: zoek het controlegetal bij vaste cijfers.
        basis = "NL000099998B"
        kandidaat = next(f"{basis}{i:02d}" for i in range(100) if valideer_btw_nummer(f"{basis}{i:02d}").geverifieerd)
        assert valideer_btw_nummer(kandidaat).geverifieerd

    def test_foute_vorm_geeft_none_en_buitenlands_nooit_geverifieerd(self) -> None:
        assert valideer_btw_nummer("NL12345B01") is None
        assert valideer_btw_nummer("") is None and valideer_btw_nummer(None) is None
        de = valideer_btw_nummer("DE 123456789")
        assert de is not None and de.genormaliseerd == "DE123456789" and not de.nederlands and not de.geverifieerd

    def test_kvk_precies_acht_cijfers(self) -> None:
        assert normaliseer_kvk_nummer("KvK 1234 5678") == "12345678"
        assert normaliseer_kvk_nummer("1234567") is None
        assert normaliseer_kvk_nummer(None) is None


class TestNummerEerstCrediteurMatch:
    WOLA = uuid.uuid4()
    WOLA_BV = uuid.uuid4()

    def _kandidaten(self) -> list[VendorKandidaat]:
        return [
            VendorKandidaat(id=self.WOLA, naam="Wola B.V.", btw_nummer=BTW_GELDIG, kvk_nummer="12345678"),
            VendorKandidaat(id=self.WOLA_BV, naam="Wola b.v."),
        ]

    def test_dubbele_naam_zonder_nummer_geeft_geen_suggestie(self) -> None:
        # Het structurele Wola/Wola b.v.-gat: twee fuzzy-1.0-kandidaten → geen keuze.
        assert match_vendor("Wola", self._kandidaten()) == (None, None)

    def test_btw_nummer_wint_voor_de_naam(self) -> None:
        assert match_vendor("Wola", self._kandidaten(), btw_nummer=BTW_GELDIG) == (self.WOLA, "btw_nummer")
        # KvK als secundaire sleutel; naam mag zelfs ontbreken.
        assert match_vendor(None, self._kandidaten(), kvk_nummer="12345678") == (self.WOLA, "kvk_nummer")

    def test_nummer_bij_twee_crediteuren_valt_terug_op_de_naam(self) -> None:
        dubbel = [
            VendorKandidaat(id=self.WOLA, naam="Wola B.V.", btw_nummer=BTW_GELDIG),
            VendorKandidaat(id=self.WOLA_BV, naam="Anders B.V.", btw_nummer=BTW_GELDIG),
        ]
        assert match_vendor("Anders B.V.", dubbel, btw_nummer=BTW_GELDIG) == (self.WOLA_BV, "exact")


class _CrossClient:
    def __init__(self, treffers: list[dict]) -> None:
        self.treffers = treffers
        self.aanroepen: list[dict] = []

    def find_purchase_invoices_by_reference(self, *, vendor_id, reference, total_amount=None, expand_entity=False):
        self.aanroepen.append({"vendor_id": vendor_id, "expand_entity": expand_entity})
        return self.treffers


class TestDuplicaatOverCrediteuren:
    EIGEN = uuid.uuid4()
    ANDER = uuid.uuid4()

    def _treffer(self, entity: uuid.UUID, naam: str = "Wola b.v.") -> dict:
        return {"id": str(uuid.uuid4()), "Reference": "F-100", "Entity": {"id": str(entity), "Name": naam}}

    def test_drievoudige_match_blokkeert(self) -> None:
        client = _CrossClient([self._treffer(self.ANDER)])
        r = check_duplicaat_over_crediteuren(
            client=client,
            vendor_id=self.EIGEN,
            referentie="F-100",
            totaalbedrag=Decimal("121.00"),
            eigen_btw_nummer=BTW_GELDIG,
            btw_per_vendor={str(self.ANDER): BTW_GELDIG},
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert r.ok is False and "hetzelfde btw-nummer" in r.melding and "Wola b.v." in r.melding
        assert client.aanroepen == [{"vendor_id": None, "expand_entity": True}]

    def test_alleen_referentie_en_bedrag_is_oranje_signaal(self) -> None:
        client = _CrossClient([self._treffer(self.ANDER)])
        r = check_duplicaat_over_crediteuren(
            client=client,
            vendor_id=self.EIGEN,
            referentie="F-100",
            totaalbedrag=Decimal("121.00"),
            eigen_btw_nummer=BTW_GELDIG,
            btw_per_vendor={str(self.ANDER): "NL999999999B01"},
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert r.ok is True and r.signaal is True and "andere crediteur" in r.melding

    def test_zelfde_crediteur_en_eigen_keten_tellen_niet(self) -> None:
        eigen_id = uuid.uuid4()
        client = _CrossClient([self._treffer(self.EIGEN), {"id": str(eigen_id), "Entity": {"id": str(self.ANDER)}}])
        r = check_duplicaat_over_crediteuren(
            client=client,
            vendor_id=self.EIGEN,
            referentie="F-100",
            totaalbedrag=Decimal("121.00"),
            eigen_btw_nummer=None,
            btw_per_vendor={},
            eigen_rlz_document_id=eigen_id,
        )
        assert r.ok is True and r.signaal is False

    def test_rlz_fout_is_signaal_geen_blokkade(self) -> None:
        class Kapot:
            def find_purchase_invoices_by_reference(self, **kw):
                raise RuntimeError("RLZ weg")

        r = check_duplicaat_over_crediteuren(
            client=Kapot(),  # type: ignore[arg-type]
            vendor_id=self.EIGEN,
            referentie="F-100",
            totaalbedrag=Decimal("1"),
            eigen_btw_nummer=None,
            btw_per_vendor={},
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert r.ok is True and r.signaal is True


def _vendor(admin_engine: Engine, administratie_id: uuid.UUID, naam: str, brondata: str = "{}") -> uuid.UUID:
    vid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, :naam, CAST(:brondata AS jsonb))"
            ),
            {"id": vid, "aid": administratie_id, "naam": naam, "brondata": brondata},
        )
    return vid


class TestKenmerkOpslagEnDubbelen:
    def test_upsert_uit_veldvoorstel_met_audit_en_handmatig_wint(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        wola = _vendor(admin_engine, administratie_id, "Wola B.V.")
        document_id = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            assert crediteur_kenmerk.neem_over_uit_veldvoorstel(
                session,
                administratie_id=administratie_id,
                vendor_id=wola,
                veldvoorstel={"btw_nummer": BTW_GELDIG, "btw_nummer_geverifieerd": True, "kvk_nummer": "12345678"},
                document_id=document_id,
                actor_id=beheerder_id,
            )
            # Zelfde nummers nog eens = geen wijziging, geen tweede audit.
            assert not crediteur_kenmerk.neem_over_uit_veldvoorstel(
                session,
                administratie_id=administratie_id,
                vendor_id=wola,
                veldvoorstel={"btw_nummer": BTW_GELDIG, "kvk_nummer": "12345678"},
                document_id=document_id,
                actor_id=beheerder_id,
            )
        with scoped_session(administratie_id) as session:
            kenmerken = crediteur_kenmerk.kenmerken_per_vendor(session, administratie_id=administratie_id)
            assert kenmerken[wola].btw_nummer == BTW_GELDIG and kenmerken[wola].kvk_nummer == "12345678"
            assert crediteur_kenmerk.btw_per_vendor(session, administratie_id=administratie_id) == {
                str(wola): BTW_GELDIG
            }
        with admin_engine.connect() as conn:
            audits = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE actie = 'crediteur_kenmerk_uit_factuur' AND record_id = :v"
                ),
                {"v": wola},
            ).scalar_one()
            conn.execute(text("SELECT 1"))
        assert audits == 1
        # Handmatig gezet nummer wordt nooit door de factuur overschreven.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.crediteur_kenmerk SET btw_nummer = 'NL000000000B01', btw_nummer_bron = 'handmatig' WHERE vendor_id = :v"
                ),
                {"v": wola},
            )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            crediteur_kenmerk.neem_over_uit_veldvoorstel(
                session,
                administratie_id=administratie_id,
                vendor_id=wola,
                veldvoorstel={"btw_nummer": BTW_GELDIG},
                document_id=document_id,
                actor_id=beheerder_id,
            )
        with scoped_session(administratie_id) as session:
            assert (
                crediteur_kenmerk.kenmerken_per_vendor(session, administratie_id=administratie_id)[wola].btw_nummer
                == "NL000000000B01"
            )

    def test_rlz_kvk_als_fallback_en_dubbelen_op_naam_nummer_iban(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        a = _vendor(admin_engine, administratie_id, "Wola B.V.", '{"ChamberOfCommerceNumber": "1234 5678"}')
        b = _vendor(admin_engine, administratie_id, "Wola b.v.")
        c = _vendor(admin_engine, administratie_id, "Technische Unie", '{"ChamberOfCommerceNumber": "12345678"}')
        d = _vendor(admin_engine, administratie_id, "Eneco")
        with admin_engine.begin() as conn:
            for vid in (b, d):
                conn.execute(
                    text(
                        "INSERT INTO boekhouding.leverancier_iban (administratie_id, vendor_id, iban, bron) "
                        "VALUES (:aid, :v, 'NL91ABNA0417164300', 'rlz_seed')"
                    ),
                    {"aid": administratie_id, "v": vid},
                )
        with scoped_session(administratie_id) as session:
            kenmerken = crediteur_kenmerk.kenmerken_per_vendor(session, administratie_id=administratie_id)
            assert kenmerken[a].kvk_nummer == "12345678" and kenmerken[a].kvk_nummer_bron == "rlz"
        groepen = crediteur_kenmerk.dubbele_crediteuren(administratie_id=administratie_id)
        per_soort = {(g.soort, g.sleutel): {x.vendor_id for x in g.crediteuren} for g in groepen}
        assert per_soort[("kvk_nummer", "12345678")] == {a, c}
        assert per_soort[("iban", "NL91ABNA0417164300")] == {b, d}
        assert per_soort[("naam", "wola")] == {a, b}
        assert [g.soort for g in groepen] == ["kvk_nummer", "iban", "naam"]  # zekerste eerst
        # Niets gewijzigd of verwijderd in de caches.
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM boekhouding.vendor_cache WHERE administratie_id = :aid"),
                    {"aid": administratie_id},
                ).scalar_one()
                == 4
            )
