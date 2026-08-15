from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class PushConfigResponse(BaseModel):
    """De VAPID-publieke sleutel (geen geheim — de client heeft 'm nodig als
    applicationServerKey). None = push niet geconfigureerd op deze omgeving."""

    publieke_sleutel: str | None


class PushSubscriptieRequest(StrikteInvoer):
    """De velden van een browser-PushSubscription (endpoint + encryptiesleutels)."""

    endpoint: str
    p256dh: str
    auth: str


class PushSubscriptieResponse(BaseModel):
    id: uuid.UUID
    endpoint: str
    aangemaakt_op: datetime


class PushSubscriptieIntrekkenRequest(StrikteInvoer):
    endpoint: str
