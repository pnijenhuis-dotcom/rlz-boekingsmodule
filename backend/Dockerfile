# Productie-container voor Cloud Run (GCP-draaiboek F2.1 + F2.2). Lokale dev blijft `make run`
# (uvicorn --reload buiten Docker) + Vite-dev-server; dit beeld is de productie-verpakking.
#
# BUILD-CONTEXT = REPO-ROOT (niet backend/): sinds F2.2 (same-origin, beslispunt 4) bakt het
# beeld óók de frontend-build in — bouwen met:
#   docker build -f backend/Dockerfile -t <tag> .
# De .dockerignore leeft daarom in de repo-root.
#
# Twee commando's, één beeld (draaiboek-patroon "eerst migreren, dan de revisie live"):
#   serve (default)  — uvicorn zonder --reload; poort uit $PORT (Cloud Run-contract, lokaal 8080)
#   migratie         — als aparte Cloud Run-job/deploystap vóór de nieuwe revisie:
#                        docker run <image> alembic upgrade head
#                      De migratie-guard in de lifespan is de vangrail die een vergeten
#                      upgrade tegenhoudt (fail-fast bij een schema dat achterloopt).

# ---- Stage 1: frontend-build (Vite) ----------------------------------------
# Node 26 gepind — zelfde major als lokaal (pariteitsprincipe, vgl. Python hieronder).
FROM node:26-slim AS frontend
WORKDIR /bouw
# Lockfile-laag apart: een broncode-wijziging herinstalleert niet alle npm-packages.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# `npm run build` = tsc -b && vite build → /bouw/dist (hashed assets + index.html + PWA-bestanden)
RUN npm run build

# ---- Stage 2: backend + statische frontend ---------------------------------
# Python 3.12 gepind — zelfde pariteitseis als backend/Makefile::check-versions (lokaal
# nooit nieuwer dan productie).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency-laag apart van de code-laag (cache: een codewijziging herinstalleert niet alle
# dependencies). tomllib is stdlib in 3.12 — geen extra tooling nodig om pyproject te lezen.
COPY backend/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Alleen wat de runtime nodig heeft: de app, de migratieketen (alembic-job draait uit ditzelfde
# beeld) en alembic.ini. Tests, .env en dev-data blijven buiten het beeld (zie .dockerignore
# in de repo-root).
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
RUN pip install --no-cache-dir --no-deps .

# Frontend-build uit stage 1; FRONTEND_DIST_MAP activeert de same-origin-serving
# (app/static_frontend.py — hashed assets immutable, index.html no-cache, SPA-fallback).
COPY --from=frontend /bouw/dist ./static
ENV FRONTEND_DIST_MAP=/app/static

# Non-root (Cloud Run vereist het niet, maar er is geen reden om als root te draaien).
# /app blijft root-owned read-only voor de user — de app schrijft niet in z'n eigen code;
# documentopslag gaat in productie naar GCS, lokaal-in-container naar /tmp indien nodig.
RUN useradd --uid 1001 --no-create-home appuser
USER appuser

# $PORT is het Cloud Run-contract (default 8080). Shell-vorm + exec zodat de env-expansie
# werkt én uvicorn PID 1 wordt (signalen/afsluiting netjes).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
