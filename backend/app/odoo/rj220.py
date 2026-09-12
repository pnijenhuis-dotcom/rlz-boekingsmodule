"""RJ-220-rollen voor een Odoo-doelcompany (run 2 Vastgoedgroep Nederland → Odoo, blok 4, 12-09-2026).

Besluit Peter 12-09 (contract run 2 §2): VIER rollen per administratie, in de koppeling-rij (migratie 0138), NOOIT
hardgecodeerd — `voorraad_panden` (asset_current), `vooruitbetaald_voorraad` (asset_current), `opbrengst_panden`
(income), `kostprijs_panden` (expense_direct_cost) + het analytic account "Overhead" (plan Project).

Drie dingen leven hier:
1. `rollen_voor(administratie_id)` — de vastgestelde rollen uit de koppeling-rij (alles None zonder rij/zonder waarde);
   leest de rij DIRECT, niet via `credentials.koppeling_voor` (die weigert een migratiedoel-rij bewust).
2. `stel_rollen_voor(client, company_id=…)` — LEES-ONLY: leest de bestaande rekeningen van de company (Odoo 19:
   `account.account` is per company via de m2m `company_ids`) en stelt per rol een bestaande rekening (alleen bij een
   ondubbelzinnige naamtreffer mét het juiste type) of een NIEUW nummer in de NL-templatereeks voor. Bezette codes
   worden nooit voorgesteld; alternatieven (bv. de bestaande "Stock 1") worden als optie GEMELD, nooit blind gekozen.
   `maak_rollen_aan(...)` — de write (CLI `vgg-rekeningen --maak-aan`): `account.account.create` mét `company_ids`
   (Odoo 19 kent geen `company_id` op account.account — live fields_get 12-09: `company_ids` m2m REQUIRED), analytic
   "Overhead" lookup-vóór-create, koppeling-rij bijwerken, audit oud→nieuw, post-write terug-lezen. Kill-switch:
   `settings.migratie_odoo_writes_ingeschakeld` (default UIT) + harde company-pin (client.company_id == company_id).
3. `vertaal_grootboek(rlz_ledgers, odoo_accounts)` — hergebruikt `mapping.bepaal_grootboek_voorstel` (zelfde_code,
   code_verlengd) en voegt één ORANJE trap toe: `rgs` = genormaliseerde naamgelijkheid ÉN dezelfde rekeningklasse
   (leidend cijfer RLZ 4-cijferig == leidend cijfer Odoo 6-cijferig), alleen bij precies één kandidaat. Ongemapt =
   None — E rapporteert dat als tabel "ongemapte rekeningen"; er wordt nooit gegokt.

Btw: Vastgoedgroep is niet btw-plichtig → geen btw-mapping; élke regel `tax_ids = [[6,0,[]]]`. Het bewijs "nul
btw-regels in de RLZ-historie" is een teller in E's replay-rapport, niet hier.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.odoo import mapping
from app.odoo import sync as odoo_sync
from app.odoo.client import OdooClient
from app.odoo.ids import odoo_uuid
from app.odoo.models import OdooKoppeling

logger = logging.getLogger(__name__)

ROLLEN = ("voorraad_panden", "vooruitbetaald_voorraad", "opbrengst_panden", "kostprijs_panden")

#: Odoo-kolom in de koppeling-rij per rol (0138).
KOLOM_PER_ROL = {
    "voorraad_panden": "rekening_voorraad_panden_id",
    "vooruitbetaald_voorraad": "rekening_vooruitbetaald_voorraad_id",
    "opbrengst_panden": "rekening_opbrengst_panden_id",
    "kostprijs_panden": "rekening_kostprijs_panden_id",
}

ACCOUNT_TYPE_PER_ROL = {
    "voorraad_panden": "asset_current",
    "vooruitbetaald_voorraad": "asset_current",
    "opbrengst_panden": "income",
    "kostprijs_panden": "expense_direct_cost",
}

#: Voorkeursnaam per rol (Nederlands, zoals de accountant 'm in het rekeningschema wil zien).
NAAM_PER_ROL = {
    "voorraad_panden": "Voorraad panden",
    "vooruitbetaald_voorraad": "Vooruitbetaald op voorraad panden",
    "opbrengst_panden": "Opbrengst verkoop panden",
    "kostprijs_panden": "Kostprijs verkochte panden",
}

#: Kandidaat-codes per rol, in voorkeursvolgorde binnen de NL-templatereeks (live gelezen company 6, 12-09):
#: - 3xxxxx = voorraden (300100 Raw materials … 320000 Stock 1 / 321000 Stock 2 … 331000 Packaging): panden náást Stock;
#:   vooruitbetalingen op voorraden horen onder de voorraden (BW 2:369 sub d, RJ 220) → óók 3xxxxx, niet 12xxxx/13xxxx
#:   (13xxxx is in deze template de crediteuren-/schuldenreeks: 130000 Creditors, 135000 Payments in transit).
#: - 80x100 = "Turnover NL trade goods n" (800100/801100/802100 bezet) → 803100 als "goods 4 NL"; 804xxx = derdenwerk.
#: - 70xx00 = "Cost price NL trade goods n" (700100/700500/700900 bezet) → 701300 als eerstvolgende NL-kostprijs.
KANDIDAAT_CODES_PER_ROL = {
    "voorraad_panden": ("325000", "322000", "323000", "324000"),
    "vooruitbetaald_voorraad": ("326000", "327000", "328000", "329000"),
    "opbrengst_panden": ("803100", "803000", "803200", "805100"),
    "kostprijs_panden": ("701300", "701400", "701500", "701600"),
}

#: Bestaande rekeningen die inhoudelijk in de buurt komen — gemeld als optie (nooit gekozen), zodat Peter ze kan
#: verkiezen (live company 6: Stock 1/2, Prepaid expenses, Deposit, Turnover NL trade goods 1/services 1, Cost price 1).
NABIJE_BESTAANDE_CODES_PER_ROL = {
    "voorraad_panden": ("320000", "321000"),
    "vooruitbetaald_voorraad": ("320000", "321000", "120500", "121000"),
    "opbrengst_panden": ("800100", "800500"),
    "kostprijs_panden": ("700100",),
}

ANALYTIC_OVERHEAD_NAAM = "Overhead"

BRON_RGS = "rgs"


class RolFout(Exception):
    """Leesbare weigering in het rollen-pad (kill-switch, company-pin, ontbrekende koppeling-rij, Odoo-uitkomst)."""


class MigratieWritesUit(RolFout):
    """`settings.migratie_odoo_writes_ingeschakeld` staat UIT — geen enkele Odoo-write in dit pad."""


class CompanyPinGeschonden(RolFout):
    """De client is aan een andere company gebonden dan de rol-aanmaak beoogt — geweigerd vóór de call."""


@dataclass(frozen=True)
class RolRekeningen:
    voorraad_panden: int | None
    vooruitbetaald_voorraad: int | None
    opbrengst_panden: int | None
    kostprijs_panden: int | None
    analytic_overhead: int | None

    @property
    def compleet(self) -> bool:
        return all(getattr(self, rol) is not None for rol in ROLLEN)

    def als_dict(self) -> dict[str, int | None]:
        return asdict(self)


LEEG = RolRekeningen(None, None, None, None, None)


@dataclass(frozen=True)
class RolVoorstel:
    rol: str
    account_type: str
    bestaand_odoo_id: int | None
    bestaand_code: str | None
    voorstel_code: str
    voorstel_naam: str
    reden: str

    @property
    def is_hergebruik(self) -> bool:
        return self.bestaand_odoo_id is not None


@dataclass(frozen=True)
class GrootboekVertaling:
    rlz_ledger_id: uuid.UUID
    rlz_code: str | None
    rlz_naam: str | None
    odoo_account_id: int | None
    odoo_code: str | None
    bron: str | None  # zelfde_code | code_verlengd | rgs | None


# ----------------------------------------------------------------------------- 1. rollen uit de koppeling-rij


def rollen_uit_rij(rij: OdooKoppeling | None) -> RolRekeningen:
    if rij is None:
        return LEEG
    return RolRekeningen(
        voorraad_panden=rij.rekening_voorraad_panden_id,
        vooruitbetaald_voorraad=rij.rekening_vooruitbetaald_voorraad_id,
        opbrengst_panden=rij.rekening_opbrengst_panden_id,
        kostprijs_panden=rij.rekening_kostprijs_panden_id,
        analytic_overhead=rij.analytic_overhead_id,
    )


def rollen_voor(administratie_id: uuid.UUID) -> RolRekeningen:
    """De vastgestelde rollen uit `platform.odoo_koppeling` (0138); alles None zonder rij. Leest de rij direct —
    `credentials.koppeling_voor` weigert een migratiedoel-rij bewust en is hier niet de poort."""
    with scoped_session(None) as session:
        return rollen_uit_rij(session.get(OdooKoppeling, administratie_id))


# ----------------------------------------------------------------------------- 2. voorstellen (lees-only)

ACCOUNT_VELDEN = ["id", "code", "name", "account_type", "reconcile", "company_ids"]


def lees_rekeningen(client: OdooClient, *, company_id: int) -> list[dict[str, Any]]:
    """Alle `account.account` van de company (Odoo 19: m2m `company_ids`), gepagineerd, lees-only."""
    return client.search_read_alles(
        odoo_sync.MODEL_ACCOUNT, [["company_ids", "in", [int(company_id)]]], ACCOUNT_VELDEN, order="code"
    )


def _norm(naam: str | None) -> str:
    return mapping._norm_naam(naam)  # noqa: SLF001 — dezelfde normalisatie als de projectmapping


def _code(rij: dict[str, Any]) -> str:
    return str(rij.get("code") or "").strip()


def _bestaande_met_rol(rol: str, rekeningen: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rekeningen waarvan de genormaliseerde naam gelijk is aan de voorkeursnaam van de rol én het type klopt —
    de enige vorm van 'bestaand' die zonder mens gekozen mag worden (lookup-vóór-create, idempotente herdraai)."""
    doel = _norm(NAAM_PER_ROL[rol])
    return [
        r
        for r in rekeningen
        if _norm(str(r.get("name") or "")) == doel and r.get("account_type") == ACCOUNT_TYPE_PER_ROL[rol]
    ]


def _nabije_opties(rol: str, rekeningen: Sequence[dict[str, Any]]) -> list[str]:
    codes = NABIJE_BESTAANDE_CODES_PER_ROL[rol]
    uit = []
    for r in rekeningen:
        code = _code(r)
        if code in codes:
            n_comp = len(r.get("company_ids") or [])
            gedeeld = f", gedeeld over {n_comp} companies" if n_comp > 1 else ""
            type_ = "" if r.get("account_type") == ACCOUNT_TYPE_PER_ROL[rol] else f" [{r.get('account_type')}]"
            uit.append(f"{code} {r.get('name')}{type_}{gedeeld}")
    return uit


def stel_rollen_voor(client: OdooClient, *, company_id: int) -> list[RolVoorstel]:
    """Lees-only voorstel per rol. Volgorde: (1) precies één bestaande rekening mét de voorkeursnaam én het juiste
    type → hergebruik (bestaand_*, voorstel_code = die code); méér dan één → geen hergebruik, mens kiest (gemeld);
    (2) anders het eerste VRIJE nummer uit de kandidatenreeks; alle kandidaten bezet → voorstel_code leeg mét reden.
    Bestaande rekeningen in de buurt (Stock 1/2, Turnover NL trade goods 1, Cost price NL trade goods 1, Prepaid
    expenses) worden in `reden` als optie gemeld — nooit gekozen (Engelse templatenaam, gedeeld over alle companies)."""
    rekeningen = lees_rekeningen(client, company_id=company_id)
    return bepaal_rolvoorstellen(rekeningen)


def bepaal_rolvoorstellen(rekeningen: Sequence[dict[str, Any]]) -> list[RolVoorstel]:
    """Pure kern van `stel_rollen_voor` (testbaar op een fixture)."""
    bezet = {_code(r) for r in rekeningen if _code(r)}
    uit: list[RolVoorstel] = []
    for rol in ROLLEN:
        account_type = ACCOUNT_TYPE_PER_ROL[rol]
        naam = NAAM_PER_ROL[rol]
        opties = _nabije_opties(rol, rekeningen)
        opties_tekst = f" Bestaand in de buurt (optie, niet gekozen): {'; '.join(opties)}." if opties else ""
        bestaand = _bestaande_met_rol(rol, rekeningen)
        if len(bestaand) == 1:
            rij = bestaand[0]
            uit.append(
                RolVoorstel(
                    rol=rol,
                    account_type=account_type,
                    bestaand_odoo_id=int(rij["id"]),
                    bestaand_code=_code(rij),
                    voorstel_code=_code(rij),
                    voorstel_naam=str(rij.get("name") or naam),
                    reden=f"bestaat al met deze naam en type {account_type} — hergebruik (niets aanmaken).",
                )
            )
            continue
        if len(bestaand) > 1:
            codes = ", ".join(_code(r) for r in bestaand)
            uit.append(
                RolVoorstel(
                    rol=rol,
                    account_type=account_type,
                    bestaand_odoo_id=None,
                    bestaand_code=None,
                    voorstel_code="",
                    voorstel_naam=naam,
                    reden=f"{len(bestaand)} bestaande rekeningen dragen deze naam ({codes}) — kies handmatig.",
                )
            )
            continue
        vrij = next((c for c in KANDIDAAT_CODES_PER_ROL[rol] if c not in bezet), None)
        overgeslagen = [c for c in KANDIDAAT_CODES_PER_ROL[rol] if c in bezet]
        if vrij is None:
            uit.append(
                RolVoorstel(
                    rol=rol,
                    account_type=account_type,
                    bestaand_odoo_id=None,
                    bestaand_code=None,
                    voorstel_code="",
                    voorstel_naam=naam,
                    reden=f"alle kandidaatnummers bezet ({', '.join(overgeslagen)}) — kies handmatig.{opties_tekst}",
                )
            )
            continue
        bezet_tekst = f" Bezet en overgeslagen: {', '.join(overgeslagen)}." if overgeslagen else ""
        uit.append(
            RolVoorstel(
                rol=rol,
                account_type=account_type,
                bestaand_odoo_id=None,
                bestaand_code=None,
                voorstel_code=vrij,
                voorstel_naam=naam,
                reden=f"nieuw nummer {vrij} ({_reeks_uitleg(rol)}); nog geen rekening met deze naam."
                f"{bezet_tekst}{opties_tekst}",
            )
        )
    return uit


def _reeks_uitleg(rol: str) -> str:
    return {
        "voorraad_panden": "3xxxxx-voorraadreeks náást Stock 1/2, asset_current",
        "vooruitbetaald_voorraad": "vooruitbetalingen op voorraden = voorraden, BW 2:369 sub d / RJ 220, asset_current",
        "opbrengst_panden": "80x100-reeks 'Turnover NL' — eerstvolgende vrije NL-omzetreeks, income",
        "kostprijs_panden": "70xx00-reeks 'Cost price NL trade goods' — eerstvolgende vrije, expense_direct_cost",
    }[rol]


# ----------------------------------------------------------------------------- 2b. aanmaken (write, kill-switch)


def _writes_ingeschakeld() -> bool:
    return bool(getattr(settings, "migratie_odoo_writes_ingeschakeld", False))


def _company_ids(rij: dict[str, Any]) -> list[int]:
    waarde = rij.get("company_ids")
    if isinstance(waarde, list):
        return [int(v) for v in waarde if isinstance(v, int | str) and str(v).isdigit()]
    return []


def _maak_rekening(client: Any, voorstel: RolVoorstel, *, company_id: int) -> int:
    """`account.account.create` mét `company_ids` (Odoo 19) + post-write terug-lezen (code, type, company)."""
    if voorstel.is_hergebruik:
        assert voorstel.bestaand_odoo_id is not None
        return voorstel.bestaand_odoo_id
    if not voorstel.voorstel_code:
        raise RolFout(f"{voorstel.rol}: geen voorstelcode — {voorstel.reden}")
    # Lookup-vóór-create op de CODE binnen de company (idempotente herdraai ná een halve run).
    bestaand = client.search_read(
        odoo_sync.MODEL_ACCOUNT,
        [["code", "=", voorstel.voorstel_code], ["company_ids", "in", [int(company_id)]]],
        ACCOUNT_VELDEN,
        limit=5,
    )
    if len(bestaand) == 1 and bestaand[0].get("account_type") == voorstel.account_type:
        return int(bestaand[0]["id"])
    if bestaand:
        raise RolFout(
            f"{voorstel.rol}: code {voorstel.voorstel_code} bestaat al in company {company_id} "
            f"({len(bestaand)}×, type {bestaand[0].get('account_type')}) — niet aangemaakt, kies handmatig"
        )
    vals = {
        "code": voorstel.voorstel_code,
        "name": voorstel.voorstel_naam,
        "account_type": voorstel.account_type,
        "reconcile": False,
        "company_ids": [[6, 0, [int(company_id)]]],
    }
    nieuw_id = int(client.create(odoo_sync.MODEL_ACCOUNT, vals))
    terug = client.read_een(odoo_sync.MODEL_ACCOUNT, nieuw_id, ACCOUNT_VELDEN)
    if terug is None:
        raise RolFout(f"{voorstel.rol}: aangemaakt als {nieuw_id} maar niet terug te lezen — controleer in Odoo")
    if _code(terug) != voorstel.voorstel_code or terug.get("account_type") != voorstel.account_type:
        raise RolFout(
            f"{voorstel.rol}: aangemaakt als {nieuw_id} maar Odoo gaf code {_code(terug)!r}/type "
            f"{terug.get('account_type')!r} terug i.p.v. {voorstel.voorstel_code}/{voorstel.account_type} "
            "— controleer in Odoo"
        )
    if int(company_id) not in _company_ids(terug):
        raise RolFout(
            f"{voorstel.rol}: aangemaakt als {nieuw_id} maar company {company_id} staat niet in company_ids "
            f"{terug.get('company_ids')} — niet gekoppeld, controleer in Odoo"
        )
    return nieuw_id


def _analytic_overhead(client: Any, *, company_id: int, analytic_plan_id: int) -> int:
    """Lookup-vóór-create van het analytic account "Overhead" in plan Project van de company; precies één ACTIEF =
    hergebruik, méér = fout (mens kiest), gearchiveerd-alleen = fout (Odoo weigert boekingen erop)."""
    velden = ["id", "name", "code", "active", "company_id", "plan_id"]
    bestaand = client.search_read(
        odoo_sync.MODEL_ANALYTIC,
        [
            ["name", "=", ANALYTIC_OVERHEAD_NAAM],
            ["plan_id", "=", int(analytic_plan_id)],
            ["company_id", "in", [int(company_id), False]],
            ["active", "in", [True, False]],
        ],
        velden,
        limit=5,
    )
    actief = [r for r in bestaand if r.get("active", True)]
    if len(actief) == 1:
        return int(actief[0]["id"])
    if len(actief) > 1:
        raise RolFout(
            f"{len(actief)} actieve analytic accounts '{ANALYTIC_OVERHEAD_NAAM}' in plan {analytic_plan_id} — kies zelf"
        )
    if bestaand:
        raise RolFout(
            f"analytic account '{ANALYTIC_OVERHEAD_NAAM}' bestaat alleen GEARCHIVEERD — heractiveer 'm in Odoo"
        )
    nieuw_id = int(
        client.create(
            odoo_sync.MODEL_ANALYTIC,
            {"name": ANALYTIC_OVERHEAD_NAAM, "plan_id": int(analytic_plan_id), "company_id": int(company_id)},
        )
    )
    terug = client.read_een(odoo_sync.MODEL_ANALYTIC, nieuw_id, velden)
    if terug is None:
        raise RolFout(f"analytic '{ANALYTIC_OVERHEAD_NAAM}' aangemaakt als {nieuw_id} maar niet terug te lezen")
    terug_company = odoo_sync._id(terug.get("company_id"))  # noqa: SLF001 — zelfde m2o-lezer als de sync
    if terug_company not in (None, int(company_id)):
        raise RolFout(
            f"analytic '{ANALYTIC_OVERHEAD_NAAM}' aangemaakt als {nieuw_id} maar Odoo zette company {terug_company} "
            f"i.p.v. {company_id} — niet gekoppeld, controleer in Odoo"
        )
    return nieuw_id


def maak_rollen_aan(
    client: Any,
    *,
    company_id: int,
    voorstellen: Sequence[RolVoorstel],
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    analytic_plan_id: int | None = None,
) -> RolRekeningen:
    """`--maak-aan`: rekeningen + analytic "Overhead" aanmaken (lookup-vóór-create, post-write terug-lezen),
    koppeling-rij bijwerken, audit oud→nieuw. Weigert vóór de eerste call als de kill-switch UIT staat, de client aan
    een andere company hangt of de koppeling-rij ontbreekt. Odoo-writes lopen vóór de DB-transactie: een mislukte run
    laat hooguit lege rekeningen achter (zichtbaar in de fout, geen boeking) — nooit unlink."""
    if not _writes_ingeschakeld():
        raise MigratieWritesUit(
            "migratie_odoo_writes_ingeschakeld staat UIT — geen Odoo-write; zet de setting bewust aan voor deze run"
        )
    if int(getattr(client, "company_id", -1)) != int(company_id):
        raise CompanyPinGeschonden(
            f"client is gebonden aan company {getattr(client, 'company_id', None)}, "
            f"rol-aanmaak beoogt company {company_id}"
        )
    if getattr(client, "read_only", False):
        raise RolFout("client is alleen-lezen — rol-aanmaak vergt een schrijvende client op de doelcompany")
    per_rol = {v.rol: v for v in voorstellen}
    ontbrekend = [rol for rol in ROLLEN if rol not in per_rol]
    if ontbrekend:
        raise RolFout(f"voorstellen ontbreken voor rol(len): {', '.join(ontbrekend)}")

    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise RolFout(
                f"administratie {administratie_id} heeft geen odoo_koppeling-rij — "
                "maak 'm eerst aan (odoo-koppeling-migratiedoel)"
            )
        if int(rij.company_id) != int(company_id):
            raise CompanyPinGeschonden(
                f"koppeling-rij noemt company {rij.company_id}, rol-aanmaak beoogt company {company_id}"
            )
        plan_id = analytic_plan_id or rij.analytic_plan_id
        oud = rollen_uit_rij(rij).als_dict()
        session.expunge(rij)
    if plan_id is None:
        raise RolFout(
            "geen analytic_plan_id in de koppeling-rij (probe) en geen --plan meegegeven — Overhead niet aanmaakbaar"
        )

    nieuw_ids: dict[str, int] = {}
    for rol in ROLLEN:
        nieuw_ids[rol] = _maak_rekening(client, per_rol[rol], company_id=company_id)
    overhead_id = _analytic_overhead(client, company_id=company_id, analytic_plan_id=int(plan_id))

    # Audit-RLS: de audit-rij draagt administratie_id → schrijven in de scope van die administratie.
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        assert rij is not None
        for rol, odoo_id in nieuw_ids.items():
            setattr(rij, KOLOM_PER_ROL[rol], odoo_id)
        rij.analytic_overhead_id = overhead_id
        session.flush()
        uitkomst = rollen_uit_rij(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_rj220_rollen_vastgesteld",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                **uitkomst.als_dict(),
                "company_id": int(company_id),
                "analytic_plan_id": int(plan_id),
                "codes": {rol: per_rol[rol].voorstel_code for rol in ROLLEN},
                "hergebruikt": [rol for rol in ROLLEN if per_rol[rol].is_hergebruik],
            },
            administratie_id=administratie_id,
        )
    logger.info(
        "RJ-220-rollen vastgesteld voor %s op company %s: %s", administratie_id, company_id, uitkomst.als_dict()
    )
    return uitkomst


# ----------------------------------------------------------------------------- 3. grootboekvertaling RLZ → Odoo


def _klasse(code: str | None) -> str | None:
    c = (code or "").strip()
    return c[0] if c and c[0].isdigit() else None


#: Nederlands decimaal rekeningstelsel (RLZ 4-cijferig, leidend cijfer) → toegestane Odoo `account_type`s. Live proef
#: 12-09 op company 6: `code_verlengd` maakte van RLZ 1300 "Debiteuren" → 130000 "Creditors" (NL-template: 110000 =
#: Debtors, 130000 = Creditors) — de stelsels lopen niet parallel. Een onverenigbaar type = GEEN voorstel (geen gok).
TYPES_PER_RLZ_KLASSE: dict[str, frozenset[str]] = {
    "0": frozenset({"asset_fixed", "asset_non_current", "equity", "equity_unaffected", "liability_non_current"}),
    "1": frozenset(
        {
            "asset_cash",
            "asset_receivable",
            "asset_current",
            "asset_prepayments",
            "liability_payable",
            "liability_current",
            "liability_credit_card",
        }
    ),
    "2": frozenset({"asset_current", "liability_current"}),
    "3": frozenset({"asset_current"}),
    "4": frozenset({"expense", "expense_depreciation", "expense_other", "expense_direct_cost"}),
    "5": frozenset({"expense", "expense_other", "expense_direct_cost"}),
    "6": frozenset({"expense", "expense_other", "expense_direct_cost"}),
    "7": frozenset({"expense_direct_cost", "expense", "asset_current"}),
    "8": frozenset({"income", "income_other"}),
    "9": frozenset({"income_other", "expense_other", "equity_unaffected", "income", "expense"}),
}
#: Grootboekkaarten: een RLZ-naam met dit woord mag alleen op dít Odoo-type landen (debiteuren ≠ crediteuren), en een
#: Odoo-kaartrekening (Debtors/Creditors) alleen op een RLZ-rekening die zich zo noemt.
KAART_TYPE_PER_NAAMWOORD = {"debiteur": "asset_receivable", "crediteur": "liability_payable"}


def _type_compatibel(rlz_code: str | None, rlz_naam: str | None, account_type: str | None) -> bool:
    """False = deterministisch onverenigbaar (klasse ↔ type, of debiteur/crediteur-naam ↔ kaarttype). Zonder
    `account_type` in de Odoo-rij (oudere lezer) is er niets te toetsen → True."""
    if not account_type:
        return True
    klasse = _klasse(rlz_code)
    if klasse is not None and klasse in TYPES_PER_RLZ_KLASSE and account_type not in TYPES_PER_RLZ_KLASSE[klasse]:
        return False
    naam = (rlz_naam or "").casefold()
    for woord, kaarttype in KAART_TYPE_PER_NAAMWOORD.items():
        if woord in naam and account_type != kaarttype:
            return False
    if account_type in KAART_TYPE_PER_NAAMWOORD.values() and naam:
        return any(w in naam for w in KAART_TYPE_PER_NAAMWOORD)
    return True


def vertaal_grootboek(
    rlz_ledgers: Sequence[tuple[uuid.UUID, str | None, str | None]], odoo_accounts: Sequence[dict[str, Any]]
) -> list[GrootboekVertaling]:
    """Per RLZ-ledger (id, code, naam): (1) `zelfde_code`, (2) `code_verlengd` (RLZ-code + "00") via
    `mapping.bepaal_grootboek_voorstel`; (3) ORANJE `rgs`: genormaliseerde naam gelijk ÉN dezelfde rekeningklasse
    (leidend cijfer) — alleen bij precies één kandidaat en alleen als beide codes er zijn. Elke treffer passeert
    bovendien `_type_compatibel` (RLZ-klasse ↔ Odoo account_type, debiteur/crediteur ↔ kaarttype); onverenigbaar =
    None (geen gok)."""
    type_per_id = {int(a["id"]): (a.get("account_type") or None) for a in odoo_accounts if _code(a)}
    odoo_rek = [
        mapping.OdooRekening(
            odoo_id=int(a["id"]),
            lokaal_id=odoo_uuid(0, odoo_sync.MODEL_ACCOUNT, int(a["id"])),  # intern; E gebruikt odoo_id
            code=_code(a),
            naam=str(a.get("name") or ""),
            soort=None,
        )
        for a in odoo_accounts
        if _code(a)
    ]
    rlz_rek = [
        mapping.RlzRekening(rlz_id=lid, code=code, naam=naam, in_gebruik_observaties=0, in_gebruik_open_regels=0)
        for lid, code, naam in rlz_ledgers
    ]
    per_naam: dict[str, list[mapping.OdooRekening]] = {}
    for o in odoo_rek:
        per_naam.setdefault(_norm(o.naam), []).append(o)

    uit: list[GrootboekVertaling] = []
    for rij in mapping.bepaal_grootboek_voorstel(rlz_rek, odoo_rek):
        voorstel, bron = rij.voorstel, rij.reden
        if voorstel is not None and not _type_compatibel(rij.rlz.code, rij.rlz.naam, type_per_id.get(voorstel.odoo_id)):
            voorstel, bron = None, None  # code-treffer op een onverenigbaar type (1300 Debiteuren ↔ 130000 Creditors)
        if voorstel is None and rij.rlz.naam and _klasse(rij.rlz.code) is not None:
            kandidaten = [
                o
                for o in per_naam.get(_norm(rij.rlz.naam), [])
                if _klasse(o.code) == _klasse(rij.rlz.code)
                and _type_compatibel(rij.rlz.code, rij.rlz.naam, type_per_id.get(o.odoo_id))
            ]
            if len(kandidaten) == 1:
                voorstel, bron = kandidaten[0], BRON_RGS
        uit.append(
            GrootboekVertaling(
                rlz_ledger_id=rij.rlz.rlz_id,
                rlz_code=rij.rlz.code,
                rlz_naam=rij.rlz.naam,
                odoo_account_id=voorstel.odoo_id if voorstel else None,
                odoo_code=voorstel.code if voorstel else None,
                bron=bron if voorstel else None,
            )
        )
    return uit
