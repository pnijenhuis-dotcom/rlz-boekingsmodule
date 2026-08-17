from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class NatieveSubscriptieRequest(StrikteInvoer):
    """Native store-app (fase 3): het APNs-/FCM-device-token van dit apparaat. Intrekken loopt
    via het bestaande intrekken-endpoint met het token als endpoint."""

    soort: Literal["apns", "fcm"]
    token: str = Field(min_length=8, max_length=4096)
