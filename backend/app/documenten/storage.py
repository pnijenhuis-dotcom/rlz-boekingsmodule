from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentOpslag(ABC):
    """Interface voor documentopslag. `pad` is een opaque sleutel voor de implementatie (geen
    filesystem-aanname buiten LokaleBestandsopslag) — een Cloud Storage-implementatie (productie,
    7 jaar bewaarplicht met retentie) volgt dezelfde interface zodat aanroepende code niet
    verandert bij de overstap."""

    @abstractmethod
    def opslaan(self, *, pad: str, inhoud: bytes) -> None: ...

    @abstractmethod
    def lezen(self, *, pad: str) -> bytes: ...

    @abstractmethod
    def bestaat(self, *, pad: str) -> bool: ...


class LokaleBestandsopslag(DocumentOpslag):
    """Dev-implementatie: bestanden op de lokale schijf onder één basismap."""

    def __init__(self, basismap: Path) -> None:
        self._basismap = basismap.resolve()
        self._basismap.mkdir(parents=True, exist_ok=True)

    def _volledig_pad(self, pad: str) -> Path:
        volledig = (self._basismap / pad).resolve()
        if volledig != self._basismap and self._basismap not in volledig.parents:
            raise ValueError(f"Pad buiten de opslagmap: {pad!r}")
        return volledig

    def opslaan(self, *, pad: str, inhoud: bytes) -> None:
        volledig = self._volledig_pad(pad)
        volledig.parent.mkdir(parents=True, exist_ok=True)
        volledig.write_bytes(inhoud)

    def lezen(self, *, pad: str) -> bytes:
        return self._volledig_pad(pad).read_bytes()

    def bestaat(self, *, pad: str) -> bool:
        return self._volledig_pad(pad).exists()
