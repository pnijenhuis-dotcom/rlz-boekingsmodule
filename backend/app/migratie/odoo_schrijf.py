"""Schrijf-primitieven voor de RLZ → Odoo-migratie op company 6 (run 2 VGG blok 5; interface D → E, bindend).

Regels (besluit Peter 12-09 punt 1):
- KILL-SWITCH: `settings.migratie_odoo_writes_ingeschakeld` (default UIT) — élke primitief weigert VÓÓR de eerste call
  met `MigratieWritesUit`, ook vóór het zoeken. Alleen per job-run expliciet AAN via env.
- Alles landt als CONCEPT (`state == 'draft'`, terug-gelezen). Blok 7 (besluit Peter 12-09 punt 2): ÉÉN bewuste
  uitzondering — `post_move` post het ene reconcile-bewijspaar (eerste echte factuur juli 2025 + bankregel); de massa
  posten = run 3.
- Partners (besluit Peter 12-09 punt 3): `zoek_of_maak_partner` = aparte stap vóór de concepten, zoek-vóór-create op
  KvK → btw → IBAN → naam, >1 treffer = `PartnerMeerduidig` (nooit gokken), audit per partner "aangemaakt/hergebruikt";
  een concept-factuur draagt altijd een partner.
- Fout = `button_cancel` (of tegenboeken) — NOOIT `unlink`. Dit bestand bevat het woord unlink alleen in deze zin.
- Idempotentie = zoek-vóór-create op het anker (`ref ilike 'mig:<anker>'` bij moves, `unique_import_id`/`ref` bij
  statement lines); meerdere treffers = `AnkerMeerduidig` (meerduidig = nooit invullen).
- Elke call krijgt een append-only audit-rij (`module="boekhouding"`, `tabel="odoo_migratie"`) met model / methode /
  odoo-id / company / anker / route — nooit de key. De audit-schrijver is injecteerbaar (`AuditSchrijver`) zodat de
  dry-run en de tests niets in de DB zetten.
- De client is altijd een `CompanyGepindeClient` (company-pin vóór de call + post-write-verificatie ná create).

Reconcile kent een ROUTE-REGISTRY (odoo-verkenning §11.4 stap 4): (i) publieke statement-line-methode, (ii) `write` op
de suspense-regel → tegenrekening + partner, dan `account.move.line.reconcile`, (iii) reconciliatiemodel `trigger
manual`. De routes worden in volgorde geprobeerd; de eerste werkende wordt `ReconcileUitkomst.route` én komt in de audit
— dát is de vorm die in odoo-verkenning §12 wordt vastgelegd.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.migratie.odoo_doel import CompanyGepindeClient, _m2o_id
from app.odoo.client import OdooFout

logger = logging.getLogger(__name__)

MODEL_MOVE = "account.move"
MODEL_MOVE_LINE = "account.move.line"
MODEL_STATEMENT_LINE = "account.bank.statement.line"
MODEL_RECONCILE_MODEL = "account.reconcile.model"
MODEL_JOURNAL = "account.journal"
MODEL_PARTNER = "res.partner"
MODEL_PARTNER_BANK = "res.partner.bank"
_PARTNER_VELDEN = ["id", "name", "vat", "company_registry", "company_id"]

_MOVE_VELDEN = ["id", "name", "state", "company_id", "ref", "move_type", "journal_id", "date", "amount_total"]
_STL_VELDEN = [
    "id",
    "move_id",
    "is_reconciled",
    "company_id",
    "journal_id",
    "date",
    "amount",
    "unique_import_id",
    "ref",
]


class MigratieWritesUit(Exception):
    """Kill-switch staat uit — geen enkele Odoo-migratie-write."""


class AnkerMeerduidig(Exception):
    """Meer dan één Odoo-record draagt hetzelfde anker — nooit gokken, mens kijkt."""


class ConceptNietDraft(Exception):
    """Een zojuist aangemaakte move is niet `draft` — geannuleerd en gemeld."""


class NietEenConcept(Exception):
    """`annuleer_concept` op een geposte move: dat is tegenboeken (run 3), geen annulering."""


class PartnerMeerduidig(Exception):
    """Meer dan één `res.partner` past op dezelfde sleutel (KvK/btw/IBAN/naam) — nooit gokken, mens kijkt."""


class PartnerOnbekend(Exception):
    """Het voorstel draagt geen enkele sleutel én geen naam — een concept zonder partner mag niet (besluit 3)."""


def anker_marker(anker: str | uuid.UUID) -> str:
    return f"mig:{anker}"


def eis_writes_aan() -> None:
    if not settings.migratie_odoo_writes_ingeschakeld:
        raise MigratieWritesUit(
            "Odoo-migratie-writes staan UIT (settings.migratie_odoo_writes_ingeschakeld=false) — zet "
            "MIGRATIE_ODOO_WRITES_INGESCHAKELD=true alleen expliciet op de job-run"
        )


# --- audit ------------------------------------------------------------------------------------------------------------


class AuditSchrijver(Protocol):
    def leg_vast(
        self, actie: str, *, nieuwe_waarde: dict[str, Any], oude_waarde: dict[str, Any] | None = None
    ) -> None: ...


@dataclass
class DbAudit:
    """Append-only `audit_event` in `scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID)`."""

    administratie_id: uuid.UUID
    correlatie_id: uuid.UUID = field(default_factory=uuid.uuid4)
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID

    def leg_vast(self, actie: str, *, nieuwe_waarde: dict[str, Any], oude_waarde: dict[str, Any] | None = None) -> None:
        with scoped_session(self.administratie_id, actor_id=self.actor_id) as session:
            record_audit_event(
                session,
                actor_id=self.actor_id,
                module="boekhouding",
                tabel="odoo_migratie",
                record_id=self.administratie_id,
                actie=actie,
                correlatie_id=self.correlatie_id,
                oude_waarde=oude_waarde,
                nieuwe_waarde=nieuwe_waarde,
                administratie_id=self.administratie_id,
            )


@dataclass
class GeheugenAudit:
    """Audit in het geheugen (dry-run, tests) — zelfde interface, niets in de DB."""

    regels: list[dict[str, Any]] = field(default_factory=list)

    def leg_vast(self, actie: str, *, nieuwe_waarde: dict[str, Any], oude_waarde: dict[str, Any] | None = None) -> None:
        self.regels.append({"actie": actie, "nieuwe_waarde": nieuwe_waarde, "oude_waarde": oude_waarde})


def _audit_basis(client: CompanyGepindeClient, model: str, methode: str, **extra: Any) -> dict[str, Any]:
    return {"model": model, "methode": methode, "company": client.pin, **extra}


# --- concept-move -----------------------------------------------------------------------------------------------------


def zoek_move_op_anker(client: CompanyGepindeClient, anker: str) -> list[dict[str, Any]]:
    return client.search_read(
        MODEL_MOVE,
        [["company_id", "=", client.pin], ["ref", "ilike", anker_marker(anker)], ["state", "!=", "cancel"]],
        _MOVE_VELDEN,
        limit=5,
    )


def maak_concept_move(client: CompanyGepindeClient, vals: dict[str, Any], *, anker: str, audit: AuditSchrijver) -> int:
    """Zoek-vóór-create op `ref ilike 'mig:<anker>'`; `company_id` verplicht = pin; ná create `state == 'draft'`
    terug-gelezen (anders `button_cancel` + `ConceptNietDraft`). Geeft het move-id (bestaand of nieuw)."""
    eis_writes_aan()
    marker = anker_marker(anker)
    treffers = zoek_move_op_anker(client, anker)
    if len(treffers) > 1:
        raise AnkerMeerduidig(f"{len(treffers)} account.move-records dragen {marker}: {[t['id'] for t in treffers]}")
    if treffers:
        bestaand = treffers[0]
        audit.leg_vast(
            "odoo_migratie_move_bestaat",
            nieuwe_waarde=_audit_basis(
                client, MODEL_MOVE, "search_read", odoo_id=bestaand["id"], anker=anker, state=bestaand.get("state")
            ),
        )
        return int(bestaand["id"])

    vals = dict(vals)
    vals["company_id"] = client.pin
    ref = str(vals.get("ref") or "").strip()
    vals["ref"] = ref if marker in ref else (f"{ref} · {marker}" if ref else marker)
    move_id = client.create(MODEL_MOVE, vals)
    move = client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN) or {}
    if move.get("state") != "draft":
        _cancel_stil(client, move_id)
        audit.leg_vast(
            "odoo_migratie_move_geannuleerd",
            nieuwe_waarde=_audit_basis(
                client,
                MODEL_MOVE,
                "button_cancel",
                odoo_id=move_id,
                anker=anker,
                reden=f"state {move.get('state')!r} ≠ draft",
            ),
        )
        raise ConceptNietDraft(f"account.move {move_id} landde als {move.get('state')!r} — geannuleerd")
    audit.leg_vast(
        "odoo_migratie_move_aangemaakt",
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_MOVE,
            "create",
            odoo_id=move_id,
            anker=anker,
            move_type=vals.get("move_type"),
            journal_id=vals.get("journal_id"),
            date=vals.get("date"),
            ref=vals["ref"],
            state=move.get("state"),
        ),
    )
    return int(move_id)


def _cancel_stil(client: CompanyGepindeClient, move_id: int) -> None:
    try:
        client.call(MODEL_MOVE, "button_cancel", ids=[int(move_id)])
    except OdooFout as exc:  # noqa: BLE001 — de oorspronkelijke fout blijft leidend, dit is nazorg
        logger.warning("button_cancel op account.move %s mislukte: %s", move_id, exc)


# --- partner (besluit Peter 12-09 punt 3) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerUitkomst:
    partner_id: int
    herkomst: str  # "aangemaakt" | "hergebruikt"
    sleutel: str  # kvk | btw | iban | naam | nieuw
    naam: str | None
    detail: str


def _schoon(waarde: Any) -> str | None:
    if not isinstance(waarde, str):
        return None
    tekst = "".join(waarde.split()).upper()
    return tekst or None


def _partner_domein(sleutel: str, waarde: str) -> list[Any]:
    if sleutel == "kvk":
        return [["company_registry", "=", waarde]]
    if sleutel == "btw":
        return [["vat", "=", waarde]]
    if sleutel == "naam":
        return [["name", "=ilike", waarde]]
    raise ValueError(sleutel)


def zoek_partner(client: CompanyGepindeClient, voorstel: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Zoek-vóór-create in de volgorde KvK → btw → IBAN → naam; de EERSTE sleutel met ≥ 1 treffer bepaalt de uitkomst
    (sleutel, treffers). Geen enkele treffer → ("nieuw", []). Partners zijn in Odoo groepsgedeeld (`company_id`
    meestal leeg) — daarom géén company-filter in het zoeken; de create pint wél op de doelcompany."""
    kvk, btw, iban, naam = (
        _schoon(voorstel.get("kvk")),
        _schoon(voorstel.get("btw")),
        _schoon(voorstel.get("iban")),
        (voorstel.get("naam") or "").strip() or None,
    )
    for sleutel, waarde in (("kvk", kvk), ("btw", btw)):
        if waarde:
            treffers = client.search_read(MODEL_PARTNER, _partner_domein(sleutel, waarde), _PARTNER_VELDEN, limit=5)
            if treffers:
                return sleutel, treffers
    if iban:
        rekeningen = client.search_read(
            MODEL_PARTNER_BANK, [["sanitized_acc_number", "=", iban]], ["id", "partner_id"], limit=5
        )
        partner_ids = sorted({_m2o_id(r.get("partner_id")) for r in rekeningen if _m2o_id(r.get("partner_id"))})
        if partner_ids:
            treffers = client.read(MODEL_PARTNER, [int(i) for i in partner_ids], _PARTNER_VELDEN)
            if treffers:
                return "iban", treffers
    if naam:
        treffers = client.search_read(MODEL_PARTNER, _partner_domein("naam", naam), _PARTNER_VELDEN, limit=5)
        if treffers:
            return "naam", treffers
    return "nieuw", []


def zoek_of_maak_partner(
    client: CompanyGepindeClient, voorstel: Mapping[str, Any], *, audit: AuditSchrijver
) -> PartnerUitkomst:
    """Eén partner voor één voorstel (`vertaling.PartnerVoorstel` als dict): hergebruik bij precies één treffer,
    `PartnerMeerduidig` bij meer, anders `res.partner.create` gepind op de doelcompany (post-write company terug-
    gelezen door de client). Een btw-nummer dat Odoo weigert (formaatcontrole) wordt weggelaten en gemeld — de
    partner ontstaat dan zónder `vat`, zichtbaar in audit en rapport. Audit per partner."""
    eis_writes_aan()
    naam = (voorstel.get("naam") or "").strip() or None
    sleutel, treffers = zoek_partner(client, voorstel)
    if len(treffers) > 1:
        raise PartnerMeerduidig(
            f"{len(treffers)} res.partner-records op {sleutel}={voorstel.get(sleutel)!r}: {[t['id'] for t in treffers]}"
        )
    if treffers:
        bestaand = treffers[0]
        audit.leg_vast(
            "odoo_migratie_partner_hergebruikt",
            nieuwe_waarde=_audit_basis(
                client, MODEL_PARTNER, "search_read", odoo_id=bestaand["id"], sleutel=sleutel, naam=bestaand.get("name")
            ),
        )
        return PartnerUitkomst(
            int(bestaand["id"]), "hergebruikt", sleutel, bestaand.get("name"), f"gevonden op {sleutel}"
        )
    if naam is None:
        raise PartnerOnbekend("partner-voorstel zonder naam en zonder KvK/btw/IBAN — geen partner aan te maken")
    vals: dict[str, Any] = {"name": naam, "is_company": True, "company_id": client.pin}
    kvk, btw, iban = _schoon(voorstel.get("kvk")), _schoon(voorstel.get("btw")), _schoon(voorstel.get("iban"))
    if kvk:
        vals["company_registry"] = kvk
    if btw:
        vals["vat"] = btw
    if iban:
        vals["bank_ids"] = [[0, 0, {"acc_number": iban}]]
    detail = "nieuw"
    try:
        partner_id = client.create(MODEL_PARTNER, vals)
    except OdooFout as exc:
        if "vat" not in vals or "vat" not in (exc.melding or "").lower():
            raise
        vals.pop("vat")
        partner_id = client.create(MODEL_PARTNER, vals)
        detail = f"nieuw; btw-nummer {btw!r} door Odoo geweigerd en weggelaten ({exc.melding[:120]})"
    rij = client.read_een(MODEL_PARTNER, partner_id, _PARTNER_VELDEN) or {}
    audit.leg_vast(
        "odoo_migratie_partner_aangemaakt",
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_PARTNER,
            "create",
            odoo_id=partner_id,
            naam=rij.get("name"),
            kvk=kvk,
            btw=vals.get("vat"),
            iban=iban,
            detail=detail,
        ),
    )
    return PartnerUitkomst(int(partner_id), "aangemaakt", "nieuw", rij.get("name") or naam, detail)


# --- posten (besluit Peter 12-09 punt 2 — één bewijspaar) -----------------------------------------------------------


def post_move(client: CompanyGepindeClient, move_id: int, *, audit: AuditSchrijver) -> dict[str, Any]:
    """`action_post` op één CONCEPT; `state == 'posted'` + `name` terug-gelezen. Al gepost = idempotent (audit
    'bestaat'); `cancel` = `NietEenConcept`. Bewust de enige geposte boeking van run 2."""
    eis_writes_aan()
    move = client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN)
    if move is None:
        raise OdooFout(404, None, f"account.move {move_id} bestaat niet", model=MODEL_MOVE, methode="read")
    if move.get("state") == "posted":
        audit.leg_vast(
            "odoo_migratie_move_al_gepost",
            nieuwe_waarde=_audit_basis(client, MODEL_MOVE, "read", odoo_id=int(move_id), name=move.get("name")),
        )
        return move
    if move.get("state") != "draft":
        raise NietEenConcept(f"account.move {move_id} staat op {move.get('state')!r} — alleen een concept is te posten")
    client.call(MODEL_MOVE, "action_post", ids=[int(move_id)])
    na = client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN) or {}
    audit.leg_vast(
        "odoo_migratie_move_gepost",
        oude_waarde={"state": move.get("state"), "name": move.get("name")},
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_MOVE,
            "action_post",
            odoo_id=int(move_id),
            state=na.get("state"),
            name=na.get("name"),
            date=na.get("date"),
            amount_total=na.get("amount_total"),
        ),
    )
    if na.get("state") != "posted":
        raise OdooFout(
            422,
            None,
            f"account.move {move_id} staat ná action_post op {na.get('state')!r}",
            model=MODEL_MOVE,
            methode="action_post",
        )
    return na


def zet_terug_naar_concept(client: CompanyGepindeClient, move_id: int, *, audit: AuditSchrijver) -> None:
    """`button_draft` op een geannuleerde move → `state == 'draft'` terug-gelezen (terugweg-bewijs blok 7 stap 6:
    cancel → concept, nooit unlink). Een geposte move wordt hier NIET teruggezet (dat is tegenboeken, run 3)."""
    eis_writes_aan()
    move = client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN) or {}
    if move.get("state") == "posted":
        raise NietEenConcept(f"account.move {move_id} is gepost — tegenboeken, niet terugzetten")
    if move.get("state") != "draft":
        client.call(MODEL_MOVE, "button_draft", ids=[int(move_id)])
    na = client.read_een(MODEL_MOVE, move_id, ["state"]) or {}
    audit.leg_vast(
        "odoo_migratie_move_terug_naar_concept",
        oude_waarde={"state": move.get("state")},
        nieuwe_waarde=_audit_basis(client, MODEL_MOVE, "button_draft", odoo_id=int(move_id), state=na.get("state")),
    )
    if na.get("state") != "draft":
        raise OdooFout(
            422,
            None,
            f"account.move {move_id} staat ná button_draft op {na.get('state')!r}",
            model=MODEL_MOVE,
            methode="button_draft",
        )


# --- statement line ---------------------------------------------------------------------------------------------------


def zoek_statement_line_op_anker(
    client: CompanyGepindeClient, anker: str, *, journal_id: int | None
) -> list[dict[str, Any]]:
    domein: list[Any] = [["company_id", "=", client.pin]]
    if journal_id is not None:
        domein.append(["journal_id", "=", int(journal_id)])
    domein.extend(["|", ["unique_import_id", "=", str(anker)], ["ref", "=", str(anker)]])
    return client.search_read(MODEL_STATEMENT_LINE, domein, _STL_VELDEN, limit=5)


def maak_statement_line(
    client: CompanyGepindeClient, vals: dict[str, Any], *, anker: str, audit: AuditSchrijver
) -> int:
    """Bankregel (fase 1 van de bank — aanleveren, NIET afletteren). `unique_import_id` = `ref` = anker; ná create
    worden `move_id` en `is_reconciled` terug-gelezen (Odoo maakt de move 103001 ↔ suspense zelf)."""
    eis_writes_aan()
    vals = dict(vals)
    vals["company_id"] = client.pin
    vals["unique_import_id"] = str(anker)
    vals.setdefault("ref", str(anker))
    treffers = zoek_statement_line_op_anker(client, anker, journal_id=vals.get("journal_id"))
    if len(treffers) > 1:
        raise AnkerMeerduidig(f"{len(treffers)} statement lines dragen anker {anker}: {[t['id'] for t in treffers]}")
    if treffers:
        bestaand = treffers[0]
        audit.leg_vast(
            "odoo_migratie_statement_line_bestaat",
            nieuwe_waarde=_audit_basis(
                client,
                MODEL_STATEMENT_LINE,
                "search_read",
                odoo_id=bestaand["id"],
                anker=anker,
                move_id=_m2o_id(bestaand.get("move_id")),
                is_reconciled=bestaand.get("is_reconciled"),
            ),
        )
        return int(bestaand["id"])
    stl_id = client.create(MODEL_STATEMENT_LINE, vals)
    rij = client.read_een(MODEL_STATEMENT_LINE, stl_id, _STL_VELDEN) or {}
    audit.leg_vast(
        "odoo_migratie_statement_line_aangemaakt",
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_STATEMENT_LINE,
            "create",
            odoo_id=stl_id,
            anker=anker,
            journal_id=vals.get("journal_id"),
            date=vals.get("date"),
            amount=vals.get("amount"),
            move_id=_m2o_id(rij.get("move_id")),
            is_reconciled=rij.get("is_reconciled"),
            unique_import_id_teruggelezen=rij.get("unique_import_id"),
        ),
    )
    return int(stl_id)


# --- reconcile (route-registry) ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileUitkomst:
    route: str | None  # "i" | "ii" | "iii" | None (geen route werkte)
    geslaagd: bool
    is_reconciled: bool | None
    pogingen: tuple[dict[str, Any], ...]
    detail: dict[str, Any]


@dataclass(frozen=True)
class ReconcileOpdracht:
    """Wat een reconcile-route nodig heeft. `move_line_ids` = de te matchen regels van het DOCUMENT (debiteuren-/
    crediteurenregel van de factuur); `statement_line_id` = de bankregel; `tegenrekening_id`/`partner_id` voor
    route ii."""

    move_line_ids: tuple[int, ...]
    statement_line_id: int | None = None
    tegenrekening_id: int | None = None
    partner_id: int | None = None


RouteFunctie = Callable[[CompanyGepindeClient, ReconcileOpdracht], dict[str, Any]]


def _route_bestaat_niet(exc: OdooFout) -> bool:
    """403 = private methode, 404 = onbekende methode/model, 500 'Invalid field' = veld bestaat niet in deze versie."""
    if exc.status in (403, 404):
        return True
    return exc.status == 500 and ("Invalid field" in exc.melding or "has no attribute" in exc.melding)


def _route_i_statement_line_methode(client: CompanyGepindeClient, opdracht: ReconcileOpdracht) -> dict[str, Any]:
    if opdracht.statement_line_id is None:
        raise OdooFout(404, None, "route i vereist een statement_line_id", model=MODEL_STATEMENT_LINE, methode="-")
    # Kandidaat-naam uit §11.4 (i); privaat/onbekend = 403/404 → registry gaat door naar (ii).
    client.call(
        MODEL_STATEMENT_LINE,
        "set_line_bank_statement_line",
        ids=[int(opdracht.statement_line_id)],
        line_ids=list(opdracht.move_line_ids),
    )
    return {"methode": f"{MODEL_STATEMENT_LINE}.set_line_bank_statement_line"}


def _suspense_regel(client: CompanyGepindeClient, statement_line_id: int) -> tuple[int, int]:
    """(suspense-regel-id, move-id) van de bankregel: de regel van de move die NIET op de default-rekening van het
    dagboek staat (103001) — dus de suspense-kant (103002)."""
    stl = client.read_een(MODEL_STATEMENT_LINE, statement_line_id, ["move_id", "journal_id"]) or {}
    move_id = _m2o_id(stl.get("move_id"))
    journal_id = _m2o_id(stl.get("journal_id"))
    if move_id is None or journal_id is None:
        raise OdooFout(404, None, "statement line zonder move/journal", model=MODEL_STATEMENT_LINE, methode="read")
    journal = client.read_een(MODEL_JOURNAL, journal_id, ["default_account_id"]) or {}
    default_account = _m2o_id(journal.get("default_account_id"))
    regels = client.search_read(
        MODEL_MOVE_LINE,
        [["move_id", "=", move_id], ["company_id", "=", client.pin]],
        ["id", "account_id", "reconciled"],
    )
    kandidaten = [r for r in regels if _m2o_id(r.get("account_id")) != default_account]
    if len(kandidaten) != 1:
        raise OdooFout(
            422,
            "AnkerMeerduidig",
            f"{len(kandidaten)} niet-bankregels in move {move_id} — verwacht precies één suspense-regel",
            model=MODEL_MOVE_LINE,
            methode="search_read",
        )
    return int(kandidaten[0]["id"]), int(move_id)


def _route_ii_write_en_reconcile(client: CompanyGepindeClient, opdracht: ReconcileOpdracht) -> dict[str, Any]:
    if opdracht.statement_line_id is None or opdracht.tegenrekening_id is None:
        raise OdooFout(
            404, None, "route ii vereist statement_line_id + tegenrekening_id", model=MODEL_MOVE_LINE, methode="-"
        )
    suspense_id, move_id = _suspense_regel(client, opdracht.statement_line_id)
    schrijf: dict[str, Any] = {"account_id": int(opdracht.tegenrekening_id)}
    if opdracht.partner_id is not None:
        schrijf["partner_id"] = int(opdracht.partner_id)
    client.write(MODEL_MOVE_LINE, [suspense_id], schrijf)
    client.call(MODEL_MOVE_LINE, "reconcile", ids=[suspense_id, *map(int, opdracht.move_line_ids)])
    return {"methode": f"{MODEL_MOVE_LINE}.write + reconcile", "suspense_line_id": suspense_id, "bank_move_id": move_id}


def _route_iii_reconciliatiemodel(client: CompanyGepindeClient, opdracht: ReconcileOpdracht) -> dict[str, Any]:
    if opdracht.statement_line_id is None:
        raise OdooFout(404, None, "route iii vereist een statement_line_id", model=MODEL_RECONCILE_MODEL, methode="-")
    modellen = client.search_read(
        MODEL_RECONCILE_MODEL, [["company_id", "=", client.pin], ["trigger", "=", "manual"]], ["id", "name"], limit=1
    )
    if not modellen:
        raise OdooFout(
            404, None, "geen reconciliatiemodel met trigger manual", model=MODEL_RECONCILE_MODEL, methode="search_read"
        )
    # Kandidaat-aanroep (AANNAME, §11.4 (iii)): een publieke toepassingsmethode op het model — privaat = 403 → geen
    # route.
    client.call(
        MODEL_RECONCILE_MODEL,
        "action_reconcile",
        ids=[int(modellen[0]["id"])],
        statement_line_ids=[int(opdracht.statement_line_id)],
    )
    return {"methode": f"{MODEL_RECONCILE_MODEL}.action_reconcile", "model_id": modellen[0]["id"]}


#: De registry — volgorde is de probeervolgorde uit §11.4 stap 4.
RECONCILE_ROUTES: tuple[tuple[str, RouteFunctie], ...] = (
    ("i", _route_i_statement_line_methode),
    ("ii", _route_ii_write_en_reconcile),
    ("iii", _route_iii_reconciliatiemodel),
)


def reconcile(
    client: CompanyGepindeClient,
    *,
    move_line_ids: Sequence[int],
    audit: AuditSchrijver,
    statement_line_id: int | None = None,
    tegenrekening_id: int | None = None,
    partner_id: int | None = None,
    routes: Sequence[tuple[str, RouteFunctie]] = RECONCILE_ROUTES,
) -> ReconcileUitkomst:
    """Probeer de routes in volgorde; de eerste die zonder fout loopt én `is_reconciled` oplevert is DE route (audit +
    §12). Een route die 'niet bestaat' (403/404/Invalid field) telt als overgeslagen; een echte fout (422) stopt niet
    de registry maar wordt per poging vastgelegd."""
    eis_writes_aan()
    opdracht = ReconcileOpdracht(
        move_line_ids=tuple(int(i) for i in move_line_ids),
        statement_line_id=statement_line_id,
        tegenrekening_id=tegenrekening_id,
        partner_id=partner_id,
    )
    pogingen: list[dict[str, Any]] = []
    for naam, functie in routes:
        try:
            detail = functie(client, opdracht)
        except OdooFout as exc:
            pogingen.append(
                {
                    "route": naam,
                    "uitkomst": "bestaat niet" if _route_bestaat_niet(exc) else "fout",
                    "status": exc.status,
                    "fout": f"{exc.naam or ''} {exc.melding[:200]}".strip(),
                }
            )
            continue
        is_reconciled = _lees_is_reconciled(client, statement_line_id)
        pogingen.append({"route": naam, "uitkomst": "gelopen", "is_reconciled": is_reconciled, **detail})
        uitkomst = ReconcileUitkomst(
            route=naam, geslaagd=True, is_reconciled=is_reconciled, pogingen=tuple(pogingen), detail=detail
        )
        audit.leg_vast(
            "odoo_migratie_reconcile",
            nieuwe_waarde=_audit_basis(
                client,
                MODEL_MOVE_LINE,
                "reconcile",
                route=naam,
                move_line_ids=list(opdracht.move_line_ids),
                statement_line_id=statement_line_id,
                is_reconciled=is_reconciled,
                pogingen=pogingen,
            ),
        )
        return uitkomst
    audit.leg_vast(
        "odoo_migratie_reconcile_geen_route",
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_MOVE_LINE,
            "reconcile",
            route=None,
            move_line_ids=list(opdracht.move_line_ids),
            statement_line_id=statement_line_id,
            pogingen=pogingen,
        ),
    )
    return ReconcileUitkomst(route=None, geslaagd=False, is_reconciled=None, pogingen=tuple(pogingen), detail={})


def _lees_is_reconciled(client: CompanyGepindeClient, statement_line_id: int | None) -> bool | None:
    if statement_line_id is None:
        return None
    rij = client.read_een(MODEL_STATEMENT_LINE, statement_line_id, ["is_reconciled"]) or {}
    waarde = rij.get("is_reconciled")
    return bool(waarde) if waarde is not None else None


# --- terugweg ---------------------------------------------------------------------------------------------------------


def annuleer_concept(client: CompanyGepindeClient, move_id: int, *, reden: str, audit: AuditSchrijver) -> None:
    """`button_cancel` op een CONCEPT (nooit unlink); state 'cancel' terug-gelezen. Een geposte move is geen concept:
    `NietEenConcept` — tegenboeken is run 3."""
    eis_writes_aan()
    move = client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN)
    if move is None:
        raise OdooFout(404, None, f"account.move {move_id} bestaat niet", model=MODEL_MOVE, methode="read")
    if move.get("state") == "posted":
        raise NietEenConcept(f"account.move {move_id} ({move.get('name')}) is gepost — tegenboeken, niet annuleren")
    oud = {"state": move.get("state"), "name": move.get("name"), "ref": move.get("ref")}
    if move.get("state") != "cancel":
        client.call(MODEL_MOVE, "button_cancel", ids=[int(move_id)])
    na = client.read_een(MODEL_MOVE, move_id, ["state"]) or {}
    audit.leg_vast(
        "odoo_migratie_move_geannuleerd",
        oude_waarde=oud,
        nieuwe_waarde=_audit_basis(
            client, MODEL_MOVE, "button_cancel", odoo_id=int(move_id), reden=reden, state=na.get("state")
        ),
    )
    if na.get("state") != "cancel":
        raise OdooFout(
            422,
            None,
            f"account.move {move_id} staat ná button_cancel op {na.get('state')!r}",
            model=MODEL_MOVE,
            methode="button_cancel",
        )


def koppel_los(client: CompanyGepindeClient, *, move_line_ids: Sequence[int], audit: AuditSchrijver) -> None:
    """`account.move.line.remove_move_reconcile` — de bankregel blijft staan, alleen de koppeling verdwijnt."""
    eis_writes_aan()
    ids = [int(i) for i in move_line_ids]
    client.call(MODEL_MOVE_LINE, "remove_move_reconcile", ids=ids)
    na = client.read(MODEL_MOVE_LINE, ids, ["reconciled"]) if ids else []
    audit.leg_vast(
        "odoo_migratie_koppel_los",
        nieuwe_waarde=_audit_basis(
            client,
            MODEL_MOVE_LINE,
            "remove_move_reconcile",
            move_line_ids=ids,
            reconciled_na={int(r["id"]): r.get("reconciled") for r in na},
        ),
    )
