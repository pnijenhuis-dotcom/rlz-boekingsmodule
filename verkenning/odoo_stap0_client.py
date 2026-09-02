#!/usr/bin/env python3
"""Gedeelde client voor de Odoo STAP-0-verkenning (02-09-2026) — JSON-2 (Odoo 19).

Leest ODOO_URL / ODOO_DB / ODOO_GEBRUIKER / ODOO_API_KEY uit verkenning/.env; de key komt NOOIT
in output of logs. Elke SCHRIJFactie (create/write/action_post/reverse/…) gaat via `schrijf()` en
wordt append-only gelogd in verkenning/output/odoo_stap0_audit.jsonl (gitignored). Kill-switch:
bestaat verkenning/POC_STOP, dan weigert élke schrijfactie.

Feit 02-09: `ODOO_DB` in .env ("universal-steigerbouw") is NIET de echte databasenaam op de
server (XML-RPC authenticate → KeyError). Odoo Online is single-database per host, dus JSON-2
werkt zónder `X-Odoo-Database`-header; mét een verkeerde header antwoordt Odoo 404 "No database
is selected". De client zet de header daarom bewust niet.
"""

from __future__ import annotations

import json
import pathlib
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from dotenv import dotenv_values

HIER = pathlib.Path(__file__).resolve().parent
OUTPUT = HIER / "output"
KILL_SWITCH = HIER / "POC_STOP"
AUDIT_LOG = OUTPUT / "odoo_stap0_audit.jsonl"

_SCHRIJFMETHODEN = {
    "create", "write", "unlink", "action_post", "button_draft", "button_cancel", "reverse_moves",
    "action_reverse", "reconcile", "action_archive", "action_unarchive", "toggle_active",
    "register_as_main_attachment", "message_post",
}


class OdooFout(Exception):
    def __init__(self, status: int | None, naam: str | None, melding: str | None, ruw: Any = None):
        super().__init__(f"{status} {naam}: {melding}")
        self.status, self.naam, self.melding, self.ruw = status, naam, melding, ruw


class OdooJson2:
    def __init__(self) -> None:
        env = dotenv_values(HIER / ".env")
        self.url = (env.get("ODOO_URL") or "").rstrip("/")
        self._key = env.get("ODOO_API_KEY") or ""
        self.gebruiker = env.get("ODOO_GEBRUIKER") or ""
        self.env_db_label = env.get("ODOO_DB") or ""
        if not self.url or not self._key:
            raise SystemExit("ODOO_URL/ODOO_API_KEY ontbreken in verkenning/.env")
        self.aanroepen: list[dict[str, Any]] = []  # timing-log (read-only observatie rate limits)

    # --- transport -----------------------------------------------------------------------
    def _post(self, pad: str, body: dict[str, Any]) -> tuple[int, Any]:
        req = urllib.request.Request(self.url + pad, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", "bearer " + self._key)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "rlz-odoo-stap0")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                status = r.status
                data = json.loads(raw.decode()) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            try:
                data = json.loads(raw.decode())
            except Exception:  # noqa: BLE001
                data = raw.decode(errors="replace")[:500]
        finally:
            self.aanroepen.append({"pad": pad, "ms": round((time.monotonic() - t0) * 1000)})
        return status, data

    def call(self, model: str, methode: str, **kwargs: Any) -> Any:
        """Read-only aanroep (of expliciet toegestaan via schrijf())."""
        if methode in _SCHRIJFMETHODEN and not kwargs.pop("_schrijf_toegestaan", False):
            raise RuntimeError(f"{model}.{methode} is een schrijfactie — gebruik schrijf()")
        status, data = self._post(f"/json/2/{model}/{methode}", kwargs)
        if status != 200:
            if isinstance(data, dict):
                raise OdooFout(status, data.get("name"), data.get("message"), data)
            raise OdooFout(status, None, str(data), data)
        return data

    def schrijf(self, model: str, methode: str, *, reden: str, **kwargs: Any) -> Any:
        """Enige toegestane schrijfroute: kill-switch + audit-log vóór én ná de call."""
        if KILL_SWITCH.exists():
            raise SystemExit(f"POC_STOP aanwezig — schrijfactie {model}.{methode} geweigerd")
        entry = {"ts": datetime.now(UTC).isoformat(), "model": model, "methode": methode, "reden": reden,
                 "args": _kort(kwargs)}
        try:
            resultaat = self.call(model, methode, _schrijf_toegestaan=True, **kwargs)
            entry["resultaat"] = _kort(resultaat)
            return resultaat
        except OdooFout as f:
            entry["fout"] = {"status": f.status, "naam": f.naam, "melding": (f.melding or "")[:500]}
            raise
        finally:
            OUTPUT.mkdir(exist_ok=True)
            with AUDIT_LOG.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")

    # --- gemak ---------------------------------------------------------------------------
    def search_read(self, model: str, domain: list, fields: list[str], **kw: Any) -> list[dict]:
        return self.call(model, "search_read", domain=domain, fields=fields, **kw)

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict]:
        return self.call(model, "read", ids=ids, fields=fields)

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, dict]:
        return self.call(model, "fields_get", attributes=attributes or ["type", "string", "relation", "readonly", "required"])

    def versie(self) -> dict:
        req = urllib.request.Request(self.url + "/web/webclient/version_info",
                                     data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "rlz-odoo-stap0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())["result"]


def _kort(x: Any, n: int = 800) -> Any:
    s = json.dumps(x, default=str)
    if len(s) <= n:
        return x
    return s[:n] + f"… ({len(s)} tekens)"


def bewaar(naam: str, data: Any) -> pathlib.Path:
    OUTPUT.mkdir(exist_ok=True)
    p = OUTPUT / naam
    p.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    return p
