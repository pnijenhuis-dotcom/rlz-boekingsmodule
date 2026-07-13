"""RLZ-seed van het boekingsgeheugen (app/geheugen/seed.py): idempotent, hervatbaar, telt
overslagen expliciet. Fake-client — geen echte HTTP; de padvormen zijn live geverifieerd
(B1-verkenning 2026-07-13)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Engine, text

from app.geheugen import seed

VENDOR_A = str(uuid.uuid4())
GB_X = str(uuid.uuid4())
GB_Y = str(uuid.uuid4())
BTW_H = str(uuid.uuid4())


class FakeSeedClient:
    """PurchaseInvoices-lijst + Lines per factuur, met dezelfde respons-vormen als live."""

    def __init__(self, facturen: list[dict], lines_per_factuur: dict[str, list[dict]]) -> None:
        self.facturen = facturen
        self.lines_per_factuur = lines_per_factuur
        self.lijst_filters: list[str] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        assert path == "PurchaseInvoices"
        self.lijst_filters.append((params or {}).get("$filter", ""))
        skip = int((params or {}).get("$skip", "0"))
        top = int((params or {}).get("$top", "100"))
        return {"value": self.facturen[skip : skip + top]}

    def get_lines(self, entity_path: str, entity_id, *, expand: str = "Account,Project") -> list[dict]:
        return self.lines_per_factuur.get(str(entity_id), [])


def _factuur(factuur_id: str, *, entity: str | None, datum: str = "2026-06-01", receipt: str | None = "R-1") -> dict:
    body: dict = {"id": factuur_id, "Date": f"{datum}T00:00:00", "ReceiptNumber": receipt}
    if entity is not None:
        body["Entity"] = {"id": entity}
    return body


def _line(
    line_id: str, *, gb: str | None = GB_X, btw: str | None = None, omschrijving: str | None = "Diesel NEN590"
) -> dict:
    body: dict = {"id": line_id, "Description": omschrijving, "NetAmount": 10.0}
    if gb is not None:
        body["Account"] = {"id": gb}
    if btw is not None:
        body["TaxRate"] = {"id": btw}
    return body


def _observaties(admin_engine: Engine, administratie_id: uuid.UUID) -> list:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT vendor_id, regel_sleutel, gb_id, btw_id, bron, bron_datum, boekstuk_ref "
                    "FROM boekhouding.boeking_observatie WHERE administratie_id = :a ORDER BY regel_sleutel"
                ),
                {"a": administratie_id},
            )
        )


class TestSeed:
    def test_seed_maakt_observaties_met_sleutel_en_bron(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        f1 = str(uuid.uuid4())
        client = FakeSeedClient(
            facturen=[_factuur(f1, entity=VENDOR_A)],
            lines_per_factuur={
                f1: [
                    _line(str(uuid.uuid4()), gb=GB_X, btw=BTW_H, omschrijving="Diesel NEN590"),
                    _line(str(uuid.uuid4()), gb=GB_Y, omschrijving=None),  # leverancier-niveau
                ]
            },
        )
        rapport = seed.seed_boekingsgeheugen(
            administratie_id=administratie_id, client=client, vandaag=date(2026, 7, 13)
        )
        assert rapport.aantal_facturen_geseed == 1
        assert rapport.observaties_nieuw == 2
        rijen = _observaties(admin_engine, administratie_id)
        # ORDER BY regel_sleutel: NULL (leverancier-niveau) sorteert in Postgres als laatste.
        assert [(str(r.vendor_id), r.regel_sleutel, str(r.gb_id), r.bron) for r in rijen] == [
            (VENDOR_A, "diesel nen590", GB_X, "rlz_seed"),
            (VENDOR_A, None, GB_Y, "rlz_seed"),
        ]
        met_sleutel = rijen[0]
        assert str(met_sleutel.btw_id) == BTW_H
        assert met_sleutel.bron_datum == date(2026, 6, 1)  # bron_datum = factuurdatum
        assert met_sleutel.boekstuk_ref == "R-1"

    def test_her_run_maakt_geen_dubbele_observaties(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        f1 = str(uuid.uuid4())
        lijn = _line(str(uuid.uuid4()))
        client = FakeSeedClient(facturen=[_factuur(f1, entity=VENDOR_A)], lines_per_factuur={f1: [lijn]})

        eerste = seed.seed_boekingsgeheugen(administratie_id=administratie_id, client=client)
        tweede = seed.seed_boekingsgeheugen(administratie_id=administratie_id, client=client)

        assert eerste.observaties_nieuw == 1
        assert tweede.observaties_nieuw == 0
        assert tweede.observaties_bestonden_al == 1
        assert len(_observaties(admin_engine, administratie_id)) == 1

    def test_overslagen_worden_geteld_nooit_stil(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        f_zonder_entity = str(uuid.uuid4())
        f_zonder_regels = str(uuid.uuid4())
        f_alleen_totaalregel = str(uuid.uuid4())
        client = FakeSeedClient(
            facturen=[
                _factuur(f_zonder_entity, entity=None),
                _factuur(f_zonder_regels, entity=VENDOR_A),
                _factuur(f_alleen_totaalregel, entity=VENDOR_A),
            ],
            lines_per_factuur={
                f_zonder_regels: [],
                f_alleen_totaalregel: [_line(str(uuid.uuid4()), gb=None)],  # regel zonder GB telt niet
            },
        )
        rapport = seed.seed_boekingsgeheugen(administratie_id=administratie_id, client=client)
        assert rapport.aantal_facturen_bekeken == 3
        assert rapport.aantal_facturen_geseed == 0
        assert rapport.overgeslagen_zonder_entity == 1
        assert rapport.overgeslagen_zonder_bruikbare_regels == 2
        assert _observaties(admin_engine, administratie_id) == []

    def test_recency_cap_stuurt_server_side_datumfilter(self, administratie_id: uuid.UUID) -> None:
        client = FakeSeedClient(facturen=[], lines_per_factuur={})
        seed.seed_boekingsgeheugen(
            administratie_id=administratie_id, client=client, maanden=12, vandaag=date(2026, 7, 13)
        )
        # 12 maanden × 31 dagen (372) vóór 2026-07-13 = 2025-07-06 — het filter reist server-side mee.
        assert client.lijst_filters == ["Date ge 2025-07-06"]

    def test_paginatie_haalt_alles_op(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        facturen = []
        lines: dict[str, list[dict]] = {}
        for _ in range(150):  # meer dan één pagina van 100
            fid = str(uuid.uuid4())
            facturen.append(_factuur(fid, entity=VENDOR_A))
            lines[fid] = [_line(str(uuid.uuid4()))]
        client = FakeSeedClient(facturen=facturen, lines_per_factuur=lines)
        rapport = seed.seed_boekingsgeheugen(administratie_id=administratie_id, client=client)
        assert rapport.aantal_facturen_bekeken == 150
        assert rapport.observaties_nieuw == 150
