"""Refresh-TTL over de zomertijdwissel (run A 02-10, punt 16).

De rode test van 25-09 → 25-10 (`test_kantoor_passkeys::…jwt_semantiek`) had geen code-oorzaak:
`_issue_token_paar` rekent al in UTC/absolute seconden (`datetime.now(UTC) + timedelta(seconds=ttl)`)
en beide kolommen zijn `timestamptz`. De TEST trok de twee teruggelezen datetimes van elkaar af;
psycopg geeft ze mét dezelfde ZoneInfo (Europe/Amsterdam) terug en Python trekt aware datetimes
mét hetzelfde tzinfo-object NAÏEF (wandkloktijd) van elkaar af — over een wissel heen dus ±1 uur.

Hier het bewijs mét vaste peildata rond BEIDE wissels van 2026 (29-03 en 25-10): de uitgifte
op het peilmoment levert exact `ttl` absolute seconden, ongeacht de systeemdatum; de naïeve
wandklok-aftrek wijkt op de wissel-overspannende peildata precies 1 uur af (dat is de
reproductie van de oude testfout, geen gedrag van de code)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.config import settings
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.security.passwords import hash_password

NL = ZoneInfo("Europe/Amsterdam")
LENTE_WISSEL = datetime(2026, 3, 29, 2, 0, tzinfo=NL)  # laatste zondag maart → +1 u
HERFST_WISSEL = datetime(2026, 10, 25, 3, 0, tzinfo=NL)  # laatste zondag oktober → −1 u

# (naam, peilmoment, overspant de 30-dagen-TTL een wissel?)
PEILDATA = [
    ("30 d vóór de lentewissel", datetime(2026, 2, 27, 12, 0, tzinfo=NL), True),
    ("dag ná de lentewissel", datetime(2026, 3, 30, 12, 0, tzinfo=NL), False),
    ("30 d vóór de herfstwissel", datetime(2026, 9, 25, 12, 0, tzinfo=NL), True),
    ("dag ná de herfstwissel", datetime(2026, 10, 26, 12, 0, tzinfo=NL), False),
    ("vandaag 02-10 (de rode dag)", datetime(2026, 10, 2, 12, 0, tzinfo=NL), True),
]


def _maak_gebruiker(admin_engine: Engine, rol: str) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status, wachtwoord_hash) "
                "VALUES (:id, 'TTL Test', :mail, :rol, 'actief', :hash)"
            ),
            {"id": gid, "mail": f"{gid}@test.local", "rol": rol, "hash": hash_password("een-heel-lang-wachtwoord")},
        )
    return gid


def _bevries_klok(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class VasteKlok(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return moment.astimezone(tz or UTC)

    monkeypatch.setattr(service, "datetime", VasteKlok)


def _overspant(peilmoment: datetime, ttl: int) -> bool:
    einde = peilmoment + timedelta(seconds=ttl)
    return peilmoment < LENTE_WISSEL < einde or peilmoment < HERFST_WISSEL < einde


@pytest.mark.parametrize(
    ("rol", "ttl_setting"),
    [
        (GebruikerRol.BOEKHOUDING, "jwt_refresh_ttl_seconds"),
        (GebruikerRol.KLANT_ACCORDEUR, "jwt_refresh_ttl_accordeur_seconds"),
    ],
    ids=["kantoor-30d", "accordeur-7d"],
)
@pytest.mark.parametrize(("naam", "peilmoment", "overspant_30d"), PEILDATA, ids=[p[0] for p in PEILDATA])
def test_refresh_ttl_is_absolute_seconden_rond_beide_wissels(
    admin_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    naam: str,
    peilmoment: datetime,
    overspant_30d: bool,
    rol: GebruikerRol,
    ttl_setting: str,
) -> None:
    ttl = getattr(settings, ttl_setting)
    gid = _maak_gebruiker(admin_engine, rol.value)
    _bevries_klok(monkeypatch, peilmoment)

    with scoped_session(None) as session:
        service._issue_token_paar(session, gebruiker_id=gid, rol=rol)

    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT verloopt_op, EXTRACT(EPOCH FROM (verloopt_op - :peil)) AS seconden "
                "FROM platform.refresh_token WHERE gebruiker_id = :g"
            ),
            {"g": gid, "peil": peilmoment},
        ).one()

    # 1. De code: exact ttl absolute seconden, in SQL én in Python (UTC) — ongeacht de peildatum.
    assert int(rij.seconden) == ttl, naam
    assert rij.verloopt_op.astimezone(UTC) - peilmoment.astimezone(UTC) == timedelta(seconds=ttl), naam
    # Aware-vergelijking = instant; de verwachting zelf in UTC optellen — `peilmoment + timedelta`
    # mét een ZoneInfo-tzinfo is in Python óók wandklok-rekenen en zou hier 1 uur verkeerd zitten.
    assert rij.verloopt_op == peilmoment.astimezone(UTC) + timedelta(seconds=ttl), naam

    # 2. De oude testfout gereproduceerd: naïeve wandklok-aftrek mét hetzelfde tzinfo wijkt
    #    precies 1 uur af als de TTL een wissel overspant, anders niet.
    wandklok = rij.verloopt_op.astimezone(NL).replace(tzinfo=None) - peilmoment.replace(tzinfo=None)
    if _overspant(peilmoment, ttl):
        assert abs(wandklok - timedelta(seconds=ttl)) == timedelta(hours=1), naam
    else:
        assert wandklok == timedelta(seconds=ttl), naam
    if ttl_setting == "jwt_refresh_ttl_seconds":
        assert _overspant(peilmoment, ttl) == overspant_30d, naam  # de tabel klopt mét de wissels


def test_naieve_aftrek_met_gedeeld_tzinfo_is_wandkloktijd() -> None:
    """Pure reproductie van de Python-eigenschap achter de flake (datetime-docs: zelfde tzinfo →
    tzinfo wordt genegeerd bij aftrekken): dit deed de oude test, en daarom was alleen de test fout."""
    a = datetime(2026, 10, 2, 12, 0, tzinfo=NL)
    b = (a.astimezone(UTC) + timedelta(days=30)).astimezone(NL)  # absolute 30 dagen; ná 25-10 → wandklok 11:00
    assert b - a == timedelta(days=29, hours=23)  # zelfde tzinfo → naïef
    assert b.astimezone(UTC) - a.astimezone(UTC) == timedelta(days=30)
