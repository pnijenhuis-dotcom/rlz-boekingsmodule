"""Doelkoppeling + HARDE COMPANY-PIN voor de RLZ → Odoo-migratie (run 2 VGG blok 5, besluit Peter 12-09 punt 1(c)).

Waarom een aparte laag naast `app/odoo/credentials.py`:
- `koppeling_voor()` weigert een `odoo_koppeling`-rij van een administratie met `boekhoud_backend='rlz'` (tenzij
  alleen-lezen) — terecht: de dagelijkse adapter mag nooit op company 6 schrijven vóór de kanteling. De migratie
  heeft precies zo'n rij nodig (`migratie_doel=True`) en leest 'm UITSLUITEND hier (`doelkoppeling_voor`).
- `CompanyGepindeClient` legt bovenop de client-poort (`context.allowed_company_ids`) een tweede, inspecterende poort:
  élke call wordt VÓÓR verzending recursief doorzocht op `company_id`/`company_ids` in `vals`, `vals_list`, `domain`
  (triples) en `context.allowed_company_ids`; elke waarde ≠ pin = `CompanyPinGeschonden` zonder HTTP-call. Ná élke
  `create` op de bewaakte modellen wordt `company_id` verplicht terug-gelezen (post-write-verificatie); een afwijking
  op een `account.move` (of de move achter een statement line) wordt direct `button_cancel`'d (nooit `unlink`) en
  gemeld als `CompanyPinGeschonden`.

Geen enkele functie hier schrijft naar Odoo behalve die annulering ná een bewezen company-mismatch.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.db.models import Administratie
from app.db.session import scoped_session
from app.odoo.client import OdooAlleenLezen, OdooClient, OdooFout
from app.odoo.credentials import OdooVerbinding
from app.odoo.models import OdooKoppeling
from app.security.envelope import unwrap_secret

#: Modellen waarvan ná `create` de `company_id` verplicht terug-gelezen wordt.
BEWAAKTE_CREATE_MODELLEN = frozenset(
    {"account.move", "account.bank.statement.line", "account.account", "account.analytic.account"}
)
#: Sleutel in `odoo_koppeling.probe_rapport` waaronder de migratiedoel-CLI het bankdagboek (BNK1) vastlegt —
#: de koppeling-rij heeft (0101/0138) geen kolom voor een bankdagboek; de waarde is altijd gelezen, nooit hardgecodeerd.
PROBE_SLEUTEL_BANKDAGBOEK = "migratie:journal_bank_id"
#: Extra methoden die een read-only client óók weigert (niet in `client.SCHRIJFMETHODEN`, wél muterend).
EXTRA_SCHRIJFMETHODEN = frozenset({"remove_move_reconcile", "set_line_bank_statement_line", "action_reconcile"})

_COMPANY_SLEUTELS = frozenset({"company_id", "company_ids"})


class GeenMigratieDoel(Exception):
    """De administratie heeft geen `odoo_koppeling`-rij met `migratie_doel=True` (of bestaat niet)."""


class CompanyPinGeschonden(Exception):
    """Een call droeg (of leverde) een company ≠ de pin uit de koppeling-rij. Vóór de call = geen HTTP-verkeer;
    ná een create = het record is (waar mogelijk) direct geannuleerd."""

    def __init__(self, melding: str, *, pin: int, gezien: Any, plek: str) -> None:
        self.pin = pin
        self.gezien = gezien
        self.plek = plek
        super().__init__(f"{melding} (pin company {pin}, gezien {gezien!r} in {plek})")


@dataclass(frozen=True)
class MigratieDoel(OdooVerbinding):
    """`OdooVerbinding` + wat de migratie extra nodig heeft. Blijft een `OdooVerbinding` (contract D → E)."""

    journal_bank_id: int | None = None
    migratie_doel: bool = True


# --- company-pin-inspectie (pure functies, geen netwerk) ----------------------------------------------------------


def _ids_uit_waarde(waarde: Any) -> list[Any]:
    """Alle company-id-kandidaten uit een veldwaarde: int, lijst van ints, of ORM-commando's ([4,0,id], [6,0,[ids]])."""
    if isinstance(waarde, bool):
        return []
    if isinstance(waarde, int):
        return [waarde]
    if isinstance(waarde, (list, tuple)):
        gevonden: list[Any] = []
        for item in waarde:
            if isinstance(item, (list, tuple)) and item and isinstance(item[0], int) and len(item) in (2, 3):
                # ORM-commando (0,0,vals) / (4,id) / (6,0,[ids]) — alleen 4 en 6 dragen id's, 0 draagt vals (elders
                # getoetst)
                if item[0] == 4 and len(item) >= 2:
                    gevonden.append(item[1])
                elif item[0] == 6 and len(item) == 3:
                    gevonden.extend(_ids_uit_waarde(item[2]))
            elif isinstance(item, int) and not isinstance(item, bool):
                gevonden.append(item)
        return gevonden
    return []


def _toets_waarde(sleutel: str, waarde: Any, pin: int, plek: str) -> None:
    for kandidaat in _ids_uit_waarde(waarde):
        if kandidaat != pin:
            raise CompanyPinGeschonden(f"{sleutel} ≠ pin", pin=pin, gezien=kandidaat, plek=plek)
    if waarde is False or waarde is None:
        raise CompanyPinGeschonden(f"{sleutel} leeg — company is verplicht", pin=pin, gezien=waarde, plek=plek)


def _is_domeintriple(item: Any) -> bool:
    return isinstance(item, (list, tuple)) and len(item) == 3 and isinstance(item[0], str) and isinstance(item[1], str)


def _toets_domein(domein: Iterable[Any], pin: int, plek: str) -> None:
    for item in domein:
        if _is_domeintriple(item):
            veld, operator, waarde = item
            laatste = veld.split(".")[-1]
            if laatste in _COMPANY_SLEUTELS or veld in _COMPANY_SLEUTELS:
                ids = _ids_uit_waarde(waarde)
                if operator in ("=", "in", "child_of", "parent_of"):
                    for kandidaat in ids:
                        if kandidaat != pin:
                            raise CompanyPinGeschonden(
                                f"domein {veld} {operator}", pin=pin, gezien=kandidaat, plek=plek
                            )
                    if not ids and waarde is not False:
                        raise CompanyPinGeschonden(f"domein {veld} {operator}", pin=pin, gezien=waarde, plek=plek)
                elif operator in ("!=", "not in"):
                    if pin in ids:
                        raise CompanyPinGeschonden(
                            f"domein {veld} {operator} sluit de pin uit", pin=pin, gezien=waarde, plek=plek
                        )
                else:
                    raise CompanyPinGeschonden(
                        f"domein {veld} {operator} niet toegestaan", pin=pin, gezien=waarde, plek=plek
                    )
        elif isinstance(item, (list, tuple)):
            _toets_domein(item, pin, plek)


def _toets_recursief(obj: Any, pin: int, plek: str) -> None:
    if isinstance(obj, Mapping):
        for sleutel, waarde in obj.items():
            if sleutel in _COMPANY_SLEUTELS:
                _toets_waarde(str(sleutel), waarde, pin, plek)
            elif sleutel == "allowed_company_ids":
                ids = _ids_uit_waarde(waarde)
                if ids != [pin]:
                    raise CompanyPinGeschonden("allowed_company_ids ≠ [pin]", pin=pin, gezien=waarde, plek=plek)
            elif sleutel == "domain" and isinstance(waarde, (list, tuple)):
                _toets_domein(waarde, pin, plek)
            else:
                _toets_recursief(waarde, pin, f"{plek}.{sleutel}")
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            if isinstance(item, (list, tuple)) and len(item) == 3 and item[0] == 0 and isinstance(item[2], Mapping):
                _toets_recursief(item[2], pin, f"{plek}[{i}]")  # ORM-commando (0, 0, vals)
            else:
                _toets_recursief(item, pin, f"{plek}[{i}]")


def toets_company_pin(model: str, methode: str, kwargs: Mapping[str, Any], *, pin: int) -> None:
    """Pure poort: `CompanyPinGeschonden` zodra ergens in de argumenten een company ≠ pin staat."""
    _toets_recursief(dict(kwargs), pin, f"{model}.{methode}")


def _m2o_id(waarde: Any) -> int | None:
    if isinstance(waarde, (list, tuple)) and waarde:
        return int(waarde[0])
    if isinstance(waarde, int) and not isinstance(waarde, bool):
        return int(waarde)
    return None


# --- de gepinde client ----------------------------------------------------------------------------------------------


class CompanyGepindeClient(OdooClient):
    """`OdooClient` met inspecterende company-pin vóór élke call en post-write-verificatie ná élke bewaakte create."""

    def __init__(self, *, pin: int | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.pin = int(pin if pin is not None else self.company_id)
        if self.pin != self.company_id:
            raise ValueError(f"company-pin {self.pin} ≠ client-company {self.company_id}")
        #: Wat er ná een geschonden post-write-verificatie is gedaan (voor rapport/tests).
        self.laatste_herstel: dict[str, Any] | None = None

    def call(self, model: str, methode: str, **kwargs: Any) -> Any:
        if self.read_only and methode in EXTRA_SCHRIJFMETHODEN:
            raise OdooAlleenLezen(f"{model}.{methode} geweigerd: deze Odoo-verbinding is alleen-lezen")
        toets_company_pin(model, methode, kwargs, pin=self.pin)
        resultaat = super().call(model, methode, **kwargs)
        if methode == "create" and model in BEWAAKTE_CREATE_MODELLEN:
            self._verifieer_na_create(model, resultaat)
        return resultaat

    # --- post-write-verificatie ---
    def _verifieer_na_create(self, model: str, resultaat: Any) -> None:
        ids = [int(i) for i in (resultaat if isinstance(resultaat, list) else [resultaat])]
        velden = ["company_id"] + (["move_id"] if model == "account.bank.statement.line" else [])
        rijen = super().call(model, "read", ids=ids, fields=velden)
        gelezen = {int(r["id"]): r for r in rijen}
        for odoo_id in ids:
            rij = gelezen.get(odoo_id)
            if rij is None:
                raise CompanyPinGeschonden(
                    f"{model} {odoo_id} niet terug te lezen ná create",
                    pin=self.pin,
                    gezien=None,
                    plek=f"{model}.create",
                )
            company = _m2o_id(rij.get("company_id"))
            if company != self.pin:
                self._herstel_na_mismatch(model, odoo_id, rij)
                raise CompanyPinGeschonden(
                    f"POST-WRITE: {model} {odoo_id} staat op company {company}",
                    pin=self.pin,
                    gezien=company,
                    plek=f"{model}.create",
                )

    def _herstel_na_mismatch(self, model: str, odoo_id: int, rij: dict[str, Any]) -> None:
        """Een move op de verkeerde company wordt direct geannuleerd (`button_cancel`, nooit `unlink`). Voor een
        statement line: de move erachter. Rekeningen/analytic accounts kennen geen annulering — alleen melden."""
        move_id: int | None = None
        if model == "account.move":
            move_id = odoo_id
        elif model == "account.bank.statement.line":
            move_id = _m2o_id(rij.get("move_id"))
        herstel: dict[str, Any] = {"model": model, "odoo_id": odoo_id, "actie": "geen (alleen gemeld)"}
        if move_id is not None:
            try:
                super().call("account.move", "button_cancel", ids=[move_id])
                herstel["actie"] = f"button_cancel account.move {move_id}"
            except OdooFout as exc:  # noqa: BLE001 — de mismatch zelf is al de leidende fout
                herstel["actie"] = f"button_cancel account.move {move_id} MISLUKT: {exc.status} {exc.naam or ''}"
        self.laatste_herstel = herstel


# --- doelkoppeling --------------------------------------------------------------------------------------------------


def _lees_migratie_doel_vlag(session: Any, rij: OdooKoppeling) -> bool:
    """`migratie_doel` uit het model (blok 4/C) of — zolang het ORM-attribuut ontbreekt — rechtstreeks uit de kolom
    (0138)."""
    vlag = getattr(rij, "migratie_doel", None)
    if vlag is not None:
        return bool(vlag)
    waarde = session.execute(
        text("SELECT migratie_doel FROM platform.odoo_koppeling WHERE administratie_id = :id"),
        {"id": rij.administratie_id},
    ).scalar()
    return bool(waarde)


def _bankdagboek_uit_probe(probe_rapport: Mapping[str, Any] | None) -> int | None:
    if not probe_rapport:
        return None
    waarde = probe_rapport.get(PROBE_SLEUTEL_BANKDAGBOEK)
    try:
        return int(waarde) if waarde not in (None, "", False) else None
    except (TypeError, ValueError):
        return None


def doelkoppeling_voor(administratie_id: uuid.UUID) -> MigratieDoel:
    """De migratie-DOELkoppeling van een (RLZ-)administratie. Eist `migratie_doel=True`; weigert anders zichtbaar."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise GeenMigratieDoel(f"Onbekende administratie: {administratie_id}")
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise GeenMigratieDoel(
                f"Administratie {administratie.naam} heeft geen Odoo-koppeling — maak het migratiedoel aan met "
                "`odoo-koppeling-migratiedoel`"
            )
        if not _lees_migratie_doel_vlag(session, rij):
            raise GeenMigratieDoel(
                f"Odoo-koppeling van {administratie.naam} (company {rij.company_id}) is geen migratiedoel "
                "(migratie_doel=false) — de migratie schrijft nooit op een gewone koppeling"
            )
        if rij.alleen_lezen:
            raise GeenMigratieDoel(f"Odoo-koppeling van {administratie.naam} is alleen-lezen — geen migratiedoel")
        return MigratieDoel(
            administratie_id=administratie_id,
            odoo_url=rij.odoo_url,
            company_id=int(rij.company_id),
            company_naam=rij.company_naam,
            journal_purchase_id=rij.journal_purchase_id,
            journal_general_id=rij.journal_general_id,
            journal_sale_id=rij.journal_sale_id,
            analytic_plan_id=rij.analytic_plan_id,
            alleen_lezen=False,
            voorraad_knip_datum=rij.voorraad_knip_datum,
            overgangsdatum=rij.overgangsdatum,
            journal_bank_id=_bankdagboek_uit_probe(rij.probe_rapport),
            migratie_doel=True,
        )


def _api_key_voor_doel(administratie_id: uuid.UUID) -> str:
    """Uitsluitend uit de credential-store — geen dev-env-terugval: een migratiedoel zonder opgeslagen key is een
    harde, zichtbare voorwaarde (kernprincipe 7(6))."""
    with scoped_session(None) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None or not rij.api_key_ciphertext:
            raise GeenMigratieDoel("Geen Odoo-API-key in de credential-store voor dit migratiedoel")
        return unwrap_secret(rij.api_key_ciphertext, rij.wrapped_data_key).decode()


def doelclient_voor(administratie_id: uuid.UUID, *, read_only: bool = False) -> CompanyGepindeClient:
    """Gepinde client op de company van de doelkoppeling — de enige toegestane ingang voor migratie-writes."""
    doel = doelkoppeling_voor(administratie_id)
    return CompanyGepindeClient(
        url=doel.odoo_url,
        api_key=_api_key_voor_doel(administratie_id),
        company_id=doel.company_id,
        pin=doel.company_id,
        read_only=read_only,
    )
