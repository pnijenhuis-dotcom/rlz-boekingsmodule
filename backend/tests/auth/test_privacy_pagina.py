"""Publieke privacy-/voorwaardenpagina (/accordeur/privacy, store-gereedheid A1).

Eén bron van waarheid: de pagina rendert AKKOORD_TEKST + versie uit app/auth/voorwaarden.py
— dezelfde tekst die de accordeur in de activeringsflow accepteert. Publiek (geen auth),
placeholders neutraal ingevuld."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.voorwaarden import AKKOORD_TEKST_VERSIE
from app.main import app

client = TestClient(app)


def test_privacy_pagina_publiek_en_volledig():
    respons = client.get("/accordeur/privacy")
    assert respons.status_code == 200
    assert respons.headers["content-type"].startswith("text/html")
    tekst = respons.text
    # Kerninhoud uit de akkoordtekst (alinea 2 = de privacy-informatielaag).
    assert "goedkeuringsapp van Administratiekantoor Nijenhuis" in tekst
    assert "verwerkingsverantwoordelijke" in tekst
    assert "7 jaar" in tekst
    assert "Staande goedkeuringen" in tekst
    # Tekstversie zichtbaar — de pagina kan nooit stil uit de pas lopen met de akkoordflow.
    assert AKKOORD_TEKST_VERSIE in tekst


def test_privacy_pagina_placeholders_neutraal_ingevuld():
    tekst = client.get("/accordeur/privacy").text
    # De PWA-placeholders horen op de publieke pagina nooit rauw zichtbaar te zijn.
    assert "[klantnaam]" not in tekst
    assert "[Klantnaam]" not in tekst
    assert "[administratie]" not in tekst
    assert "uw organisatie" in tekst
