"""Deterministische stub voor de AI-plausibiliteitstoets (blok B bundel 10-09) — nooit een echte Claude-call.

Gebruik: `plausibiliteit._client_factory = lambda ref: StubPlausibiliteitClient({...})` (via `zet_ai_toets_stub`) en zet
de AVG-gate aan met `zet_intake_ai(admin_engine, True)`. `antwoorden` mapt op een fragment van de opdracht-tekst
(tegenpartij of omschrijving) → ("plausibel" | "twijfel", reden); `standaard` geldt als niets matcht; `fout` laat
`vraag_json` een AiExtractieFout gooien; `kostenfout` een AiKostenLimietBereikt."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text

from app.aitoets import plausibiliteit


@dataclass
class StubAntwoord:
    data: dict[str, Any] | None
    afgekapt: bool = False
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class StubPlausibiliteitClient:
    antwoorden: dict[str, tuple[str, str]] = field(default_factory=dict)
    standaard: tuple[str, str] = ("plausibel", "past bij eerdere boekingen")
    fout: str | None = None
    kostenfout: str | None = None
    afgekapt: bool = False
    rauw: dict[str, Any] | None = None
    aanroepen: list[dict[str, str]] = field(default_factory=list)
    _model: str = "stub-model"

    def vraag_json(self, *, system: str, opdracht: str, json_schema: dict[str, Any]) -> StubAntwoord:
        from app.aikosten.service import AiKostenLimietBereikt
        from app.extractie.client import AiExtractieFout

        self.aanroepen.append({"system": system, "opdracht": opdracht})
        assert json_schema is plausibiliteit.PLAUSIBILITEIT_SCHEMA
        if self.kostenfout:
            raise AiKostenLimietBereikt(self.kostenfout)
        if self.fout:
            raise AiExtractieFout(self.fout)
        if self.afgekapt:
            return StubAntwoord(data=None, afgekapt=True)
        if self.rauw is not None:
            return StubAntwoord(data=self.rauw)
        for fragment, (uitkomst, reden) in self.antwoorden.items():
            if fragment.lower() in opdracht.lower():
                return StubAntwoord(data={"uitkomst": uitkomst, "reden": reden})
        return StubAntwoord(data={"uitkomst": self.standaard[0], "reden": self.standaard[1]})


def zet_ai_toets_stub(monkeypatch, stub: StubPlausibiliteitClient | None = None) -> StubPlausibiliteitClient:
    stub = stub or StubPlausibiliteitClient()
    monkeypatch.setattr(plausibiliteit, "_client_factory", lambda referentie: stub)
    return stub


def zet_ai_toets_geen_key(monkeypatch) -> None:
    from app.extractie.client import AiExtractieNietGeconfigureerd

    def _factory(referentie):
        raise AiExtractieNietGeconfigureerd("Geen anthropic_api_key geconfigureerd (test)")

    monkeypatch.setattr(plausibiliteit, "_client_factory", _factory)


def zet_intake_ai(admin_engine: Engine, aan: bool) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.intake_instelling SET ai_ingeschakeld = :aan WHERE singleton = true"), {"aan": aan}
        )


def audit_toetsen(admin_engine: Engine, record_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT tabel, nieuwe_waarde FROM platform.audit_event "
                "WHERE actie = 'ai_plausibiliteitstoets' AND record_id = :rid ORDER BY tijdstip"
            ),
            {"rid": record_id},
        ).all()
    return [{"tabel": r[0], **r[1]} for r in rijen]
