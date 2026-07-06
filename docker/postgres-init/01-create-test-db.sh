#!/bin/sh
# Postgres image maakt alleen POSTGRES_DB aan; boekhouding_test is nodig voor pytest (zie
# backend/tests/conftest.py) en bestaat lokaal (Homebrew-pariteit) ook naast boekhouding.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    SELECT 'CREATE DATABASE boekhouding_test'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'boekhouding_test')\gexec
SQL
