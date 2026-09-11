"""`rlz-lezen` — LEES-ONLY nameting-instrument voor één OData-GET op de Reeleezee-API van één administratie
(blok 10 run 11-09 middag; productie-regel Peter 08-09: alleen via de gedeployde job-image, `scripts/gcp/nameting.sh`).

    python -m app.cli rlz-lezen --administratie "<naam of UUID>" --pad "PaymentTransactions" \
        [--expand "Batch,PaymentReferenceList($expand=Document)"] [--filter "PaymentBatchId ne null"] \
        [--orderby "BookDate desc"] [--top 5] [--anonimiseer]

Waarborgen (hard, getest in tests/rlz/test_rlz_lezen_cli.py):
  * UITSLUITEND GET — `LeesOnlyClient` weigert élke andere methode met `SchrijfGeweigerd`; `put`/`post_action` bestaan
    niet meer als werkend pad. Een pad met een `Actions`-segment (RLZ's actie-route, óók de GET-lijst), `Download`
    (binair), `$metadata`, een `?`/`$`-query of `..` wordt vóór de eerste call geweigerd (exit 2).
  * `--top` ≤ 50 (afgedwongen, exit 2 daarboven) — een nameting is een steekproef, geen export.
  * Uitvoer ALTIJD geanonimiseerd (de uitvoer landt in Cloud Logging): GUID's → eerste 8 tekens, IBAN's → laatste 4,
    naamvelden → initialen; bedragen, datums, enum-waarden en referenties blijven. `--anonimiseer` is een expliciete
    (no-op) bevestiging — er is bewust geen schakelaar om het uit te zetten.
  * Credential via de bestaande store-resolutie (`resolve_credentials`, store-first) — geen nieuwe geheimen-route;
    Odoo-administratie of ontbrekende credential = leesbare melding, exit 1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from typing import Any

from app.rlz.client import RlzApiError, RlzClient

RLZ_LEZEN_COMMANDO = "rlz-lezen"
MAX_TOP = 50
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Nameting 11-09: een IBAN in een bestandsnaam (`NL..INGB…_260908.xml`, Batch.FileName op de C.V.) eindigt op `_` — een
# woordteken — waardoor `\b` niet matchte en de IBAN leesbaar in Cloud Logging landde. Grenzen daarom als "geen letter/cijfer".
IBAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}[A-Z0-9]{8,30}(?![A-Za-z0-9])")
NAAM_SLEUTELS = frozenset(
    {
        "Name",
        "OwnerName",
        "DebtorName",
        "CreditorName",
        "CounterName",
        "SearchName",
        "FullName",
        "AccountHolder",
        "EntityName",
        "CounterPartyName",
        "FirstName",
        "LastName",
        "ContactName",
    }
)
IBAN_SLEUTELS = frozenset({"IBAN", "Iban", "CounterAccount", "CounterIban", "DebtorIban", "CreditorIban"})
VERBODEN_SEGMENTEN = frozenset({"actions", "download", "$metadata"})


class SchrijfGeweigerd(RuntimeError):
    """Een niet-GET op de lees-only client — mag structureel niet voorkomen."""


class OngeldigPad(ValueError):
    """Het opgegeven OData-pad is geen toegestaan lees-pad."""


class LeesOnlyClient(RlzClient):
    """RlzClient die élke niet-GET weigert vóór er een HTTP-request bestaat."""

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if method.upper() != "GET":
            raise SchrijfGeweigerd(f"rlz-lezen is lees-only: {method} {path} geweigerd")
        return super()._request(method, path, **kwargs)

    def put(self, path: str, body: dict[str, Any], *, params: dict[str, Any] | None = None) -> Any:  # noqa: ARG002
        raise SchrijfGeweigerd(f"rlz-lezen is lees-only: PUT {path} geweigerd")

    def post_action(self, path: str, action_type: int, **extra_body: Any) -> Any:  # noqa: ARG002
        raise SchrijfGeweigerd(f"rlz-lezen is lees-only: POST {path}/Actions (Type {action_type}) geweigerd")

    def for_administration(self, admin_id: str) -> LeesOnlyClient:
        return LeesOnlyClient(username="", password="", admin_id=admin_id, client=self._client)


def valideer_pad(pad: str) -> str:
    """Relatief OData-pad zónder query; weigert Actions/Download/$metadata, `..`, absolute URL's en query-tekens."""
    kaal = (pad or "").strip().strip("/")
    if not kaal:
        raise OngeldigPad("--pad is leeg")
    if "://" in kaal or kaal.startswith("//"):
        raise OngeldigPad("--pad moet relatief zijn (bv. 'PaymentTransactions'), geen URL")
    if "?" in kaal or "$" in kaal or "&" in kaal or "#" in kaal:
        raise OngeldigPad("--pad draagt geen query: gebruik --expand/--filter/--orderby/--top")
    for segment in kaal.split("/"):
        if segment in ("", ".", ".."):
            raise OngeldigPad("--pad bevat een leeg of relatief segment")
        if segment.lower() in VERBODEN_SEGMENTEN:
            raise OngeldigPad(
                f"--pad segment {segment!r} is niet toegestaan: rlz-lezen leest alleen collecties/records "
                "(Actions is RLZ's actie-route, Download is binair)"
            )
    return kaal


def _initialen(tekst: str) -> str:
    woorden = [w for w in re.split(r"\s+", tekst.strip()) if w]
    return "".join(w[0].upper() + "." for w in woorden[:4]) if woorden else ""


def _tekst_anon(t: str) -> str:
    t = GUID_RE.sub(lambda m: m.group(0)[:8] + "…", t)
    return IBAN_RE.sub(lambda m: "…" + m.group(0)[-4:], t)


def anonimiseer(obj: Any, sleutel: str | None = None) -> Any:
    """GUID's → eerste 8, IBAN's → laatste 4 (ook in vrije tekst), naamvelden → initialen; recursief. Bedragen,
    datums, booleans en enum-leden (dicts mét `ShortDescription`: hun `Name` is de enum-naam) blijven."""
    if isinstance(obj, dict):
        if "ShortDescription" in obj:
            return {k: (v if k == "Name" else anonimiseer(v, k)) for k, v in obj.items()}
        return {k: anonimiseer(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [anonimiseer(v, sleutel) for v in obj]
    if isinstance(obj, str):
        if sleutel in NAAM_SLEUTELS:
            return _initialen(_tekst_anon(obj))
        if sleutel in IBAN_SLEUTELS or (sleutel == "AccountNumber" and IBAN_RE.fullmatch(obj)):
            return "…" + obj[-4:] if obj else obj
        return _tekst_anon(obj)
    return obj


def bouw_params(args: argparse.Namespace) -> dict[str, str]:
    top = int(args.top)
    if top < 1 or top > MAX_TOP:
        raise OngeldigPad(f"--top moet tussen 1 en {MAX_TOP} liggen (nameting = steekproef), kreeg {top}")
    params: dict[str, str] = {"$top": str(top)}
    if getattr(args, "expand", None):
        params["$expand"] = args.expand
    if getattr(args, "filter", None):
        params["$filter"] = args.filter
    if getattr(args, "orderby", None):
        params["$orderby"] = args.orderby
    if getattr(args, "count", False):
        params["$count"] = "true"
    return params


def register_rlz_lezen(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        RLZ_LEZEN_COMMANDO,
        help="LEES-ONLY: één OData-GET op de Reeleezee-API van één administratie (nameting-instrument, blok 10 11-09). "
        "Weigert Actions/Download-paden en élke niet-GET; --top ≤ 50; uitvoer altijd geanonimiseerd.",
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam — precies één treffer vereist.")
    p.add_argument(
        "--pad",
        required=True,
        help="Relatief OData-pad zonder query, bv. 'PaymentTransactions' of "
        "'PurchaseInvoices/<guid>'. Geen 'Actions', geen 'Download'.",
    )
    p.add_argument("--expand", default=None, help="$expand, bv. 'Batch,PaymentReferenceList($expand=Document)'.")
    p.add_argument("--filter", default=None, help='$filter, bv. "PaymentBatchId ne null".')
    p.add_argument("--orderby", default=None, help="$orderby, bv. 'BookDate desc'.")
    p.add_argument("--top", type=int, default=5, help=f"$top (1–{MAX_TOP}, default 5).")
    p.add_argument("--count", action="store_true", help="Voeg $count=true toe (totaal in '@odata.count').")
    p.add_argument(
        "--anonimiseer", action="store_true", help="Expliciete bevestiging; uitvoer is ALTIJD geanonimiseerd."
    )


def _zoek_administraties(tekst: str) -> list[tuple[uuid.UUID, str, str]]:
    """(id, naam, rlz_admin_id) op exacte UUID óf naam-substring; DB-toegang als systeem-actor (RLS)."""
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        try:
            rij = session.get(Administratie, uuid.UUID(tekst))
            return [(rij.id, rij.naam, rij.rlz_admin_id)] if rij is not None else []
        except ValueError:
            rijen = session.scalars(
                select(Administratie).where(Administratie.naam.ilike(f"%{tekst}%")).order_by(Administratie.naam)
            ).all()
            return [(r.id, r.naam, r.rlz_admin_id) for r in rijen]


def _client_voor(rlz_admin_id: str) -> LeesOnlyClient:
    from app.rlz.credentials import resolve_credentials

    username, password = resolve_credentials(rlz_admin_id)
    return LeesOnlyClient(username=username, password=password, admin_id=rlz_admin_id)


def run_rlz_lezen(args: argparse.Namespace, *, zoek=None, client_factory=None, uit=None) -> int:  # noqa: ANN001
    """Exit 0 = JSON (geanonimiseerd) op stdout; 1 = RLZ-/credential-fout (leesbaar op stderr); 2 = ongeldige invoer."""
    from app.rlz.credentials import GeenRlzCredentials

    uit = uit or sys.stdout
    zoek = zoek or _zoek_administraties
    client_factory = client_factory or _client_voor
    try:
        pad = valideer_pad(args.pad)
        params = bouw_params(args)
    except OngeldigPad as exc:
        print(f"rlz-lezen: {exc}", file=sys.stderr)
        return 2
    treffers = zoek(args.administratie)
    if len(treffers) != 1:
        namen = ", ".join(n for _, n, _ in treffers[:10]) or "geen"
        print(
            f"rlz-lezen: --administratie {args.administratie!r} is niet eenduidig ({len(treffers)} treffers: {namen})",
            file=sys.stderr,
        )
        return 2
    administratie_id, naam, rlz_admin_id = treffers[0]
    try:
        client = client_factory(rlz_admin_id)
    except GeenRlzCredentials as exc:
        print(f"rlz-lezen: geen Reeleezee-verbinding voor {naam!r}: {exc}", file=sys.stderr)
        return 1
    try:
        try:
            response = client.request_raw("GET", pad, params=params)
        finally:
            client.close()
    except RlzApiError as exc:
        print(f"rlz-lezen: GET {pad} → HTTP {exc.status_code}: {_tekst_anon(exc.body[:300])}", file=sys.stderr)
        return 1
    try:
        data = response.json()
    except ValueError:
        data = {
            "_status": response.status_code,
            "_content_type": response.headers.get("content-type"),
            "_lengte": len(response.content),
            "_geen_json": True,
        }
    kop = {
        "administratie": naam,
        "administratie_id": str(administratie_id)[:8] + "…",
        "pad": pad,
        "params": params,
        "status": response.status_code,
    }
    print(
        json.dumps({"rlz_lezen": kop, "antwoord": anonimiseer(data)}, indent=2, ensure_ascii=False, default=str),
        file=uit,
    )
    return 0
