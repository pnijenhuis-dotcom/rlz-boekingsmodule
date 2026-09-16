"""Groepssaldi debiteuren/crediteuren per groep — lees-only (Peter 16-09 09:20: "kan jij voor mij van de Kempengroep een
huidig saldo van de (cumulatieve) debiteuren en crediteuren geven?").

Wat dit is: per administratie in een groep (BESLISSINGEN "GROEPSKENMERK OP ADMINISTRATIE") het saldo per NL-dag op de
debiteuren- en crediteurenrekening(en), plus het INTERCOMPANY-deel (open posten op groepsmaatschappijen — de
`intercompany_relatie`-rijen van de IC/RC-run 16-09, beperkt tot tegenpartijen die zélf in de groep zitten). Drie
kolommen, controleerbaar: BRUTO (Peters "cumulatief" = som over de groep) = ZONDER-IC + IC.

Regels:
- Rekeningen komen uit de BRON, nooit hardgecodeerd 1300/1600: RLZ `Ledgers` (balans, geen totaalrekening) mét
  `$expand=SystemAccountList` → RGS-code `BVorDeb…` (handelsdebiteuren) / `BSchCre…` (handelscrediteuren); zonder RGS
  de naam ("debiteuren"/"crediteuren"). Odoo: `account.account.account_type` asset_receivable / liability_payable.
  Meerdere treffers = allemaal (subadministratie over meer rekeningen), geen treffer = status `geen_rekening`.
- Saldo = Σ Debit − Credit over de journaalregels van die rekening(en) (RLZ `JournalEntryLines`, Odoo
  `account.move.line` posted); crediteuren als positief bedrag getoond (Credit − Debit). Datumgrens = NL-dag in UTC
  (les 14-09: een `Z`-literal op middernacht schuift een dag) — zonder `--datum` géén filter (alles t/m vandaag).
- IC = Σ open bedrag (RLZ `BaseRemainingAmount` op Status 2, Odoo `amount_residual_signed` op posted/not paid) van de
  verkoop- resp. inkoopfacturen op IC-entity's. Geen namen van debiteuren/crediteuren in de uitvoer (geen PII).
- Webfilter-blokkering (`RlzWebfilterError`) = status `ongeldig` voor díe administratie, nooit een fout in het totaal;
  geen credential/koppeling = `overgeslagen`; elke andere fout = `fout` mét de melding. Alles zichtbaar, niets stil.
- Levering: lees-only CLI `groep-saldi --groep <naam|code> [--datum]` (nameting-allowlist) leest LIVE; de kaart op de
  klantenlijst leest de NACHTELIJKE stand uit `groep_saldo_stand` (sync-alles, `meet_en_schrijf_alle`) — live lezen bij
  openen niet (76 administraties). RLS op de cache = scope-waarheid ("N van M administraties in je scope").
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Administratie, Groep
from app.db.session import scoped_session
from app.groepen.models import GroepSaldoStand
from app.intercompany.models import IntercompanyRelatie
from app.rlz.client import RlzWebfilterError
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

NUL = Decimal("0.00")
_CENT = Decimal("0.01")
PAGINA = 200
MAX_PAGINAS = 200
NL = ZoneInfo("Europe/Amsterdam")
ACTIEVE_RELATIE_STATUSSEN = ("afgeleid", "bevestigd")

#: RGS-stammen (RLZ `SystemAccountList[].RgsCode`) — handelsdebiteuren resp. handelscrediteuren.
RGS_DEBITEUREN = ("BVorDeb",)
RGS_CREDITEUREN = ("BSchCre",)
#: Naam-terugval (zonder RGS): heel woord in de rekeningnaam.
NAAM_DEBITEUREN = ("debiteuren", "debiteur")
NAAM_CREDITEUREN = ("crediteuren", "crediteur")
#: RLZ AccountType: 3 activa, 4 passiva (api-verkenning "Ledgers").
ACTIVA, PASSIVA = 3, 4

GEEN_CREDENTIAL = "geen RLZ-credential in de store"
GEEN_ODOO_KOPPELING = "geen Odoo-koppeling"


class GroepOnbekend(Exception):
    """Groep bestaat niet — leesbaar melden ("maak hem aan op Instellingen › Administraties"), nooit stil leeg."""


def groep_onbekend_tekst(zoekterm: str) -> str:
    return f"groep '{zoekterm}' niet gevonden — maak hem aan op Instellingen › Administraties (blok Groepen)"


# ---- rekeningen -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rekening:
    id: str
    code: str | None
    naam: str | None

    @property
    def label(self) -> str:
        return " ".join(x for x in (self.code, self.naam) if x) or self.id


def _decimal(waarde: object) -> Decimal:
    if waarde is None:
        return NUL
    try:
        return Decimal(str(waarde))
    except (InvalidOperation, ValueError):
        return NUL


def _rgs_codes(rij: dict[str, Any]) -> list[str]:
    lijst = rij.get("SystemAccountList") or []
    uit: list[str] = []
    for item in lijst:
        if isinstance(item, dict):
            code = item.get("RgsCode") or item.get("Code")
            if isinstance(code, str) and code:
                uit.append(code.removeprefix("RGS."))
    return uit


def _naam_treft(naam: str | None, woorden: Iterable[str]) -> bool:
    laag = (naam or "").lower()
    return any(w in laag for w in woorden)


def vind_rekeningen_rlz(ledgers: Sequence[dict[str, Any]], *, soort: str) -> list[Rekening]:
    """Deterministisch uit RLZ-`Ledgers`-rijen (mét `SystemAccountList`): eerst RGS-stam op de juiste balanszijde,
    anders de naam. `soort` = 'debiteuren' | 'crediteuren'. Totaalrekeningen en de andere balanszijde tellen nooit."""
    rgs, woorden, zijde = (
        (RGS_DEBITEUREN, NAAM_DEBITEUREN, ACTIVA)
        if soort == "debiteuren"
        else (RGS_CREDITEUREN, NAAM_CREDITEUREN, PASSIVA)
    )
    kandidaten = [
        r for r in ledgers if not r.get("IsTotalAccount") and int(r.get("AccountType") or 0) == zijde and r.get("id")
    ]
    via_rgs = [r for r in kandidaten if any(c.startswith(rgs) for c in _rgs_codes(r))]
    gekozen = via_rgs or [r for r in kandidaten if _naam_treft(r.get("Description"), woorden)]
    return [Rekening(str(r["id"]), r.get("AccountNumber"), r.get("Description")) for r in gekozen]


# ---- datumgrens -------------------------------------------------------------------------------------------


def nl_dag_einde_utc(datum: date) -> str:
    """Eerste moment van de VOLGENDE NL-kalenderdag als UTC-literal — de grens voor `BookDate lt …` (les 14-09)."""
    volgende = datetime.combine(datum + timedelta(days=1), time.min, tzinfo=NL).astimezone(UTC)
    return volgende.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- bronnen ----------------------------------------------------------------------------------------------


class BronOvergeslagen(Exception):
    """Geen credential / geen koppeling — zichtbaar overgeslagen, geen fout."""


class Bron:
    """Leesbron van één administratie (RLZ of Odoo). Test-seam: een nep-bron implementeert dezelfde vier methoden."""

    backend = "rlz"

    def rekeningen(self, soort: str) -> list[Rekening]:  # pragma: no cover
        raise NotImplementedError

    def saldo(self, rekeningen: Sequence[Rekening], *, tot_en_met: date | None) -> Decimal:  # pragma: no cover
        """Σ Debit − Credit over álle regels van de rekeningen (t/m `tot_en_met`, None = alles)."""
        raise NotImplementedError

    def ic_open(
        self, entity_ids: Sequence[uuid.UUID], *, kant: str, tot_en_met: date | None
    ) -> Decimal:  # pragma: no cover
        """Σ open bedrag van de verkoop- ('debiteuren') of inkoopfacturen ('crediteuren') op de IC-entity's."""
        raise NotImplementedError

    def sluit(self) -> None:
        return None


class RlzBron(Bron):
    backend = "rlz"

    def __init__(self, client: Any) -> None:
        self.client = client
        self._ledgers: list[dict[str, Any]] | None = None

    def _alle_ledgers(self) -> list[dict[str, Any]]:
        if self._ledgers is None:
            params = {
                "$filter": f"IsTotalAccount eq false and (AccountType eq {ACTIVA} or AccountType eq {PASSIVA})",
                "$expand": "SystemAccountList",
                "$top": "500",
            }
            antwoord = self.client.get("Ledgers", params=params)
            self._ledgers = list(antwoord.get("value", [])) if isinstance(antwoord, dict) else []
        return self._ledgers

    def rekeningen(self, soort: str) -> list[Rekening]:
        return vind_rekeningen_rlz(self._alle_ledgers(), soort=soort)

    def saldo(self, rekeningen: Sequence[Rekening], *, tot_en_met: date | None) -> Decimal:
        totaal = NUL
        for rek in rekeningen:
            filter_ = f"Account/id eq {rek.id}"
            if tot_en_met is not None:
                filter_ += f" and JournalEntry/BookDate lt {nl_dag_einde_utc(tot_en_met)}"
            for pagina in range(MAX_PAGINAS):
                params = {
                    "$filter": filter_,
                    "$select": "id,DebitAmount,CreditAmount",
                    "$top": str(PAGINA),
                    "$skip": str(pagina * PAGINA),
                }
                antwoord = self.client.get("JournalEntryLines", params=params)
                deel = antwoord.get("value", []) if isinstance(antwoord, dict) else []
                for rij in deel:
                    totaal += _decimal(rij.get("DebitAmount")) - _decimal(rij.get("CreditAmount"))
                if len(deel) < PAGINA:
                    break
        return totaal.quantize(_CENT)

    def ic_open(self, entity_ids: Sequence[uuid.UUID], *, kant: str, tot_en_met: date | None) -> Decimal:
        ids = sorted(str(e) for e in entity_ids if e)
        if not ids:
            return NUL
        entity = " or ".join(f"Entity/id eq {e}" for e in ids)
        filter_ = f"({entity}) and Status eq 2" if len(ids) > 1 else f"{entity} and Status eq 2"
        if tot_en_met is not None:
            filter_ += f" and Date lt {nl_dag_einde_utc(tot_en_met)}"
        collectie = "SalesInvoices" if kant == "debiteuren" else "PurchaseInvoices"
        totaal = NUL
        for pagina in range(MAX_PAGINAS):
            params = {
                "$filter": filter_,
                "$select": "id,BaseRemainingAmount,IsCreditInvoice",
                "$top": str(PAGINA),
                "$skip": str(pagina * PAGINA),
            }
            antwoord = self.client.get(collectie, params=params)
            deel = antwoord.get("value", []) if isinstance(antwoord, dict) else []
            for rij in deel:
                bedrag = _decimal(rij.get("BaseRemainingAmount"))
                if rij.get("IsCreditInvoice") and bedrag > 0:
                    bedrag = -bedrag
                totaal += bedrag
            if len(deel) < PAGINA:
                break
        return totaal.quantize(_CENT)

    def sluit(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            logger.debug("RLZ-client sluiten mislukt", exc_info=True)


class OdooBron(Bron):
    backend = "odoo"

    def __init__(self, administratie_id: uuid.UUID, client: Any) -> None:
        self.administratie_id = administratie_id
        self.client = client

    def rekeningen(self, soort: str) -> list[Rekening]:
        account_type = "asset_receivable" if soort == "debiteuren" else "liability_payable"
        rijen = self.client.search_read(
            "account.account",
            [["account_type", "=", account_type], ["deprecated", "=", False]],
            ["code", "name"],
        )
        return [Rekening(str(r["id"]), r.get("code"), r.get("name")) for r in rijen if r.get("id") is not None]

    def saldo(self, rekeningen: Sequence[Rekening], *, tot_en_met: date | None) -> Decimal:
        totaal = NUL
        for rek in rekeningen:
            domain: list[Any] = [
                ["company_id", "=", int(self.client.company_id)],
                ["account_id", "=", int(rek.id)],
                ["parent_state", "=", "posted"],
            ]
            if tot_en_met is not None:
                domain.append(["date", "<=", tot_en_met.isoformat()])
            offset = 0
            for _ in range(MAX_PAGINAS):
                deel = self.client.search_read(
                    "account.move.line", domain, ["balance"], limit=500, offset=offset, order="id asc"
                )
                for rij in deel:
                    totaal += _decimal(rij.get("balance"))
                if len(deel) < 500:
                    break
                offset += 500
        return totaal.quantize(_CENT)

    def _partner_ids(self, entity_ids: Sequence[uuid.UUID]) -> list[int]:
        from app.intercompany.factuurmatch import OdooBron as IcOdooBron
        from app.odoo.inkoop import OdooInkoopPort

        return IcOdooBron(self.administratie_id, OdooInkoopPort.voor(self.administratie_id))._partner_ids(entity_ids)

    def ic_open(self, entity_ids: Sequence[uuid.UUID], *, kant: str, tot_en_met: date | None) -> Decimal:
        if not entity_ids:
            return NUL
        partners = self._partner_ids(entity_ids)
        if not partners:
            return NUL
        soorten = ["out_invoice", "out_refund"] if kant == "debiteuren" else ["in_invoice", "in_refund"]
        domain: list[Any] = [
            ["company_id", "=", int(self.client.company_id)],
            ["partner_id", "in", partners],
            ["move_type", "in", soorten],
            ["state", "=", "posted"],
            ["payment_state", "!=", "paid"],
        ]
        if tot_en_met is not None:
            domain.append(["invoice_date", "<=", tot_en_met.isoformat()])
        rijen = self.client.search_read("account.move", domain, ["amount_residual_signed"])
        totaal = sum((_decimal(r.get("amount_residual_signed")) for r in rijen), NUL)
        # Odoo tekent een inkoopfactuur negatief; crediteuren tonen we als positieve schuld.
        return (-totaal if kant == "crediteuren" else totaal).quantize(_CENT)

    def sluit(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Odoo-client sluiten mislukt", exc_info=True)


def open_bron(administratie_id: uuid.UUID) -> Bron:
    """RLZ- of Odoo-bron (`Administratie.boekhoud_backend`); geen credential/koppeling = `BronOvergeslagen`.
    De ENE monkeypatch-plek voor tests."""
    from app.backends.registry import Backend, backend_voor
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    if backend_voor(administratie_id) == Backend.ODOO:
        from app.odoo.credentials import GeenOdooKoppeling, odoo_client_voor

        try:
            return OdooBron(administratie_id, odoo_client_voor(administratie_id, read_only=True))
        except GeenOdooKoppeling as exc:
            raise BronOvergeslagen(GEEN_ODOO_KOPPELING) from exc
    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    except GeenRlzCredentials as exc:
        raise BronOvergeslagen(GEEN_CREDENTIAL) from exc
    return RlzBron(client)


# ---- meting per administratie ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdministratieSaldo:
    administratie_id: uuid.UUID
    naam: str
    status: str  # ok | geen_rekening | ongeldig | fout | overgeslagen
    detail: str | None = None
    debiteuren: Decimal | None = None
    crediteuren: Decimal | None = None
    ic_debiteuren: Decimal | None = None
    ic_crediteuren: Decimal | None = None
    debiteuren_rekening: str | None = None
    crediteuren_rekening: str | None = None

    @property
    def geldig(self) -> bool:
        return self.status == "ok"

    @property
    def debiteuren_zonder_ic(self) -> Decimal | None:
        if self.debiteuren is None:
            return None
        return (self.debiteuren - (self.ic_debiteuren or NUL)).quantize(_CENT)

    @property
    def crediteuren_zonder_ic(self) -> Decimal | None:
        if self.crediteuren is None:
            return None
        return (self.crediteuren - (self.ic_crediteuren or NUL)).quantize(_CENT)


def ic_entities_voor(administratie_id: uuid.UUID, groepsleden: Iterable[uuid.UUID]) -> dict[str, list[uuid.UUID]]:
    """IC-entity's van deze administratie op tegenpartijen die ZÉLF in de groep zitten, per kant: 'debiteuren' =
    relaties met richting debiteur (wij verkopen aan een groepsmaatschappij), 'crediteuren' = richting crediteur."""
    leden = set(groepsleden) - {administratie_id}
    uit: dict[str, list[uuid.UUID]] = {"debiteuren": [], "crediteuren": []}
    if not leden:
        return uit
    with scoped_session(None) as session:
        rijen = session.execute(
            select(IntercompanyRelatie.entity_in_a, IntercompanyRelatie.richting).where(
                IntercompanyRelatie.administratie_a_id == administratie_id,
                IntercompanyRelatie.administratie_b_id.in_(leden),
                IntercompanyRelatie.status.in_(ACTIEVE_RELATIE_STATUSSEN),
            )
        ).all()
    for entity, richting in rijen:
        kant = "debiteuren" if richting == "debiteur" else "crediteuren"
        if entity not in uit[kant]:
            uit[kant].append(entity)
    return uit


def meet_administratie(
    administratie_id: uuid.UUID,
    naam: str,
    *,
    groepsleden: Iterable[uuid.UUID],
    tot_en_met: date | None,
    bron: Bron | None = None,
) -> AdministratieSaldo:
    """Eén administratie: rekeningen → saldo → IC-deel. Webfilter = `ongeldig`, geen bron = `overgeslagen`, andere fout
    = `fout` mét melding; nooit een exception naar de aanroeper (de groep loopt door)."""
    eigen_bron = bron is None
    try:
        bron = bron or open_bron(administratie_id)
    except BronOvergeslagen as exc:
        return AdministratieSaldo(administratie_id, naam, "overgeslagen", str(exc))
    except Exception as exc:  # noqa: BLE001 — zichtbaar als fout-regel
        return AdministratieSaldo(administratie_id, naam, "fout", str(exc) or exc.__class__.__name__)
    try:
        deb_rek = bron.rekeningen("debiteuren")
        cred_rek = bron.rekeningen("crediteuren")
        ontbreekt = [s for s, r in (("debiteuren", deb_rek), ("crediteuren", cred_rek)) if not r]
        if ontbreekt:
            return AdministratieSaldo(
                administratie_id,
                naam,
                "geen_rekening",
                " en ".join(f"geen {s}rekening gevonden" for s in ontbreekt),
                debiteuren_rekening=", ".join(r.label for r in deb_rek) or None,
                crediteuren_rekening=", ".join(r.label for r in cred_rek) or None,
            )
        debiteuren = bron.saldo(deb_rek, tot_en_met=tot_en_met)
        crediteuren = (-bron.saldo(cred_rek, tot_en_met=tot_en_met)).quantize(_CENT)  # schuld als positief bedrag
        ic = ic_entities_voor(administratie_id, groepsleden)
        ic_deb = bron.ic_open(ic["debiteuren"], kant="debiteuren", tot_en_met=tot_en_met)
        ic_cred = bron.ic_open(ic["crediteuren"], kant="crediteuren", tot_en_met=tot_en_met)
        return AdministratieSaldo(
            administratie_id,
            naam,
            "ok",
            None,
            debiteuren=debiteuren,
            crediteuren=crediteuren,
            ic_debiteuren=ic_deb,
            ic_crediteuren=ic_cred,
            debiteuren_rekening=", ".join(r.label for r in deb_rek),
            crediteuren_rekening=", ".join(r.label for r in cred_rek),
        )
    except RlzWebfilterError as exc:
        return AdministratieSaldo(administratie_id, naam, "ongeldig", f"RLZ-blokkering — meting ongeldig: {exc}"[:500])
    except Exception as exc:  # noqa: BLE001
        return AdministratieSaldo(administratie_id, naam, "fout", (str(exc) or exc.__class__.__name__)[:500])
    finally:
        if eigen_bron and bron is not None:
            bron.sluit()


# ---- groep ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroepInfo:
    id: uuid.UUID
    naam: str
    code: str
    actief: bool


@dataclass(frozen=True)
class Totalen:
    debiteuren: Decimal = NUL
    crediteuren: Decimal = NUL
    ic_debiteuren: Decimal = NUL
    ic_crediteuren: Decimal = NUL

    @property
    def debiteuren_zonder_ic(self) -> Decimal:
        return (self.debiteuren - self.ic_debiteuren).quantize(_CENT)

    @property
    def crediteuren_zonder_ic(self) -> Decimal:
        return (self.crediteuren - self.ic_crediteuren).quantize(_CENT)


def totalen(rijen: Iterable[AdministratieSaldo]) -> Totalen:
    """Som over de GELDIGE rijen; bruto = zonder-IC + IC blijft per definitie cent-exact."""
    t = Totalen()
    for r in rijen:
        if not r.geldig:
            continue
        t = Totalen(
            t.debiteuren + (r.debiteuren or NUL),
            t.crediteuren + (r.crediteuren or NUL),
            t.ic_debiteuren + (r.ic_debiteuren or NUL),
            t.ic_crediteuren + (r.ic_crediteuren or NUL),
        )
    return t


@dataclass(frozen=True)
class GroepSaldi:
    groep: GroepInfo
    datum: date
    rijen: list[AdministratieSaldo]
    #: Totaal aantal actieve leden (ook buiten de scope van de lezer) — "N van M administraties in je scope".
    aantal_leden: int
    bron: str = "live"  # live | stand
    totalen: Totalen = field(default_factory=Totalen)
    #: Leden in de scope van de lezer (live/CLI: alle leden); `zonder_stand` = in scope maar nog geen cache-rij.
    aantal_in_scope: int = 0
    zonder_stand: int = 0


def zoek_groep(zoekterm: str) -> GroepInfo:
    """Op id, code (hoofdletterongevoelig) of naam (hoofdletterongevoelig, getrimd); onbekend = GroepOnbekend."""
    term = " ".join(zoekterm.split())
    with scoped_session(None) as session:
        groep: Groep | None = None
        try:
            groep = session.get(Groep, uuid.UUID(term))
        except ValueError:
            groep = None
        if groep is None:
            groep = session.scalar(
                select(Groep).where((func.upper(Groep.code) == term.upper()) | (func.lower(Groep.naam) == term.lower()))
            )
        if groep is None:
            raise GroepOnbekend(groep_onbekend_tekst(zoekterm))
        return GroepInfo(groep.id, groep.naam, groep.code, groep.actief)


def groep_info(groep_id: uuid.UUID) -> GroepInfo:
    with scoped_session(None) as session:
        groep = session.get(Groep, groep_id)
        if groep is None:
            raise GroepOnbekend(groep_onbekend_tekst(str(groep_id)))
        return GroepInfo(groep.id, groep.naam, groep.code, groep.actief)


def leden(groep_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """Actieve administraties in de groep, alfabetisch (administratie-rij kent geen RLS)."""
    with scoped_session(None) as session:
        return list(
            session.execute(
                select(Administratie.id, Administratie.naam)
                .where(Administratie.groep_id == groep_id, Administratie.actief.is_(True))
                .order_by(Administratie.naam)
            ).all()
        )


def meet_groep_live(groep: GroepInfo, *, datum: date | None = None) -> GroepSaldi:
    """LIVE lezen (CLI): alle actieve leden, per lid één meting; `datum` None = per vandaag zonder datumfilter."""
    ids_namen = leden(groep.id)
    ids = [aid for aid, _ in ids_namen]
    rijen = [meet_administratie(aid, naam, groepsleden=ids, tot_en_met=datum) for aid, naam in ids_namen]
    return GroepSaldi(
        groep=groep,
        datum=datum or vandaag_nl(),
        rijen=rijen,
        aantal_leden=len(ids),
        bron="live",
        totalen=totalen(rijen),
        aantal_in_scope=len(ids),
    )


# ---- cache (nachtelijke stand) ----------------------------------------------------------------------------


def schrijf_stand(rij: AdministratieSaldo, *, datum: date) -> None:
    """Eén rij per administratie per dag (upsert) — óók bij rood, zodat de kaart zegt wáárom er geen stand is."""
    with scoped_session(rij.administratie_id) as session:
        waarden = {
            "status": rij.status,
            "detail": rij.detail,
            "debiteuren": rij.debiteuren,
            "crediteuren": rij.crediteuren,
            "ic_debiteuren": rij.ic_debiteuren,
            "ic_crediteuren": rij.ic_crediteuren,
            "debiteuren_rekening": rij.debiteuren_rekening,
            "crediteuren_rekening": rij.crediteuren_rekening,
            "gemeten_op": datetime.now(UTC),
        }
        stmt = pg_insert(GroepSaldoStand).values(administratie_id=rij.administratie_id, datum=datum, **waarden)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GroepSaldoStand.administratie_id, GroepSaldoStand.datum], set_=waarden
        )
        session.execute(stmt)
        session.commit()


@dataclass
class NachtRapport:
    groepen: int = 0
    administraties: int = 0
    ok: int = 0
    niet_ok: list[str] = field(default_factory=list)


def meet_en_schrijf_alle(*, datum: date | None = None) -> NachtRapport:
    """Nachtelijke stap (sync-alles): voor élke administratie die in een ACTIEVE groep zit één meting + cache-rij.
    Fouten per administratie zijn zichtbaar in het rapport, nooit een stop van de sync."""
    datum = datum or vandaag_nl()
    rapport = NachtRapport()
    with scoped_session(None) as session:
        groepen = list(session.scalars(select(Groep).where(Groep.actief.is_(True)).order_by(Groep.naam)).all())
        infos = [GroepInfo(g.id, g.naam, g.code, g.actief) for g in groepen]
    for groep in infos:
        rapport.groepen += 1
        ids_namen = leden(groep.id)
        ids = [aid for aid, _ in ids_namen]
        for aid, naam in ids_namen:
            rij = meet_administratie(aid, naam, groepsleden=ids, tot_en_met=None)
            schrijf_stand(rij, datum=datum)
            rapport.administraties += 1
            if rij.geldig:
                rapport.ok += 1
            else:
                rapport.niet_ok.append(f"{naam}: {rij.status}{' — ' + rij.detail if rij.detail else ''}")
    return rapport


def _leden_in_scope(actor_id: uuid.UUID, ids: Sequence[uuid.UUID]) -> int:
    """Hoeveel van de leden de lezer mag zien: Beheerder = alle; anders de `gebruiker_administratie`-rijen van de
    actor (gelezen in de eigen scoped_session mét actor — RLS-les 25-08)."""
    from app.db.models import Gebruiker, GebruikerAdministratie, GebruikerRol

    if not ids:
        return 0
    with scoped_session(None, actor_id=actor_id) as session:
        rol = session.scalar(select(Gebruiker.rol).where(Gebruiker.id == actor_id))
        if rol == GebruikerRol.BEHEERDER:
            return len(ids)
        return int(
            session.scalar(
                select(func.count())
                .select_from(GebruikerAdministratie)
                .where(
                    GebruikerAdministratie.gebruiker_id == actor_id, GebruikerAdministratie.administratie_id.in_(ids)
                )
            )
            or 0
        )


def lees_stand_voor_groep(groep_id: uuid.UUID, *, actor_id: uuid.UUID) -> GroepSaldi:
    """De kaart: laatste cache-rij per lid, gelezen in `scoped_session(None, actor_id=…)` — RLS laat alleen de
    administraties in de scope van de lezer door; `aantal_leden` telt álle actieve leden ("N van M")."""
    groep = groep_info(groep_id)
    ids_namen = leden(groep.id)
    namen = dict(ids_namen)
    ids = list(namen)
    rijen: list[AdministratieSaldo] = []
    datum: date | None = None
    if ids:
        with scoped_session(None, actor_id=actor_id) as session:
            sub = (
                select(GroepSaldoStand.administratie_id, func.max(GroepSaldoStand.datum).label("datum"))
                .where(GroepSaldoStand.administratie_id.in_(ids))
                .group_by(GroepSaldoStand.administratie_id)
                .subquery()
            )
            standen = session.scalars(
                select(GroepSaldoStand).join(
                    sub,
                    (GroepSaldoStand.administratie_id == sub.c.administratie_id)
                    & (GroepSaldoStand.datum == sub.c.datum),
                )
            ).all()
            for s in standen:
                datum = s.datum if datum is None or s.datum > datum else datum
                rijen.append(
                    AdministratieSaldo(
                        s.administratie_id,
                        namen.get(s.administratie_id, "?"),
                        s.status,
                        s.detail,
                        debiteuren=s.debiteuren,
                        crediteuren=s.crediteuren,
                        ic_debiteuren=s.ic_debiteuren,
                        ic_crediteuren=s.ic_crediteuren,
                        debiteuren_rekening=s.debiteuren_rekening,
                        crediteuren_rekening=s.crediteuren_rekening,
                    )
                )
    rijen.sort(key=lambda r: r.naam.lower())
    in_scope = _leden_in_scope(actor_id, ids)
    return GroepSaldi(
        groep=groep,
        datum=datum or vandaag_nl(),
        rijen=rijen,
        aantal_leden=len(ids),
        bron="stand",
        totalen=totalen(rijen),
        aantal_in_scope=in_scope,
        zonder_stand=max(0, in_scope - len(rijen)),
    )


# ---- CLI-rapport ------------------------------------------------------------------------------------------


def _euro(bedrag: Decimal | None) -> str:
    if bedrag is None:
        return "—"
    s = f"{bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


def rapport_tekst(saldi: GroepSaldi) -> str:
    """Tabel per administratie + totalen; geen debiteur-/crediteurnamen (geen PII)."""
    r = saldi
    regels = [
        f"Groepssaldi {r.groep.naam} ({r.groep.code}) — per {r.datum:%d-%m-%Y} — bron: {r.bron} — "
        f"{len(r.rijen)} van {r.aantal_leden} administraties",
        "",
        f"{'Administratie':<40} {'Deb. bruto':>16} {'Deb. IC':>14} {'Deb. zonder IC':>16} "
        f"{'Cred. bruto':>16} {'Cred. IC':>14} {'Cred. zonder IC':>16}  Status",
    ]
    for rij in r.rijen:
        status = "ok" if rij.geldig else f"{rij.status}{' — ' + rij.detail if rij.detail else ''}"
        regels.append(
            f"{rij.naam[:40]:<40} {_euro(rij.debiteuren):>16} {_euro(rij.ic_debiteuren):>14} "
            f"{_euro(rij.debiteuren_zonder_ic):>16} {_euro(rij.crediteuren):>16} {_euro(rij.ic_crediteuren):>14} "
            f"{_euro(rij.crediteuren_zonder_ic):>16}  {status}"
        )
    t = r.totalen
    geldig = sum(1 for x in r.rijen if x.geldig)
    regels += [
        "",
        f"{'TOTAAL (' + str(geldig) + ' geldig)':<40} {_euro(t.debiteuren):>16} {_euro(t.ic_debiteuren):>14} "
        f"{_euro(t.debiteuren_zonder_ic):>16} {_euro(t.crediteuren):>16} {_euro(t.ic_crediteuren):>14} "
        f"{_euro(t.crediteuren_zonder_ic):>16}",
        "",
        "Bruto = zonder intercompany + intercompany (cent-exact). Intercompany = open posten op groepsmaatschappijen "
        "die zelf in de groep zitten (intercompany_relatie). Rekeningen uit de bron (RGS/naam, Odoo account_type):",
    ]
    for rij in r.rijen:
        if rij.debiteuren_rekening or rij.crediteuren_rekening:
            regels.append(
                f"  {rij.naam[:40]}: debiteuren {rij.debiteuren_rekening or '—'} · "
                f"crediteuren {rij.crediteuren_rekening or '—'}"
            )
    niet_ok = [x for x in r.rijen if not x.geldig]
    if niet_ok:
        regels.append(f"LET OP: {len(niet_ok)} administratie(s) niet in het totaal (status ≠ ok) — zie de statuskolom.")
    return "\n".join(regels)
