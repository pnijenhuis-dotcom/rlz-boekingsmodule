-- =============================================================================
-- GEGENEREERD BESTAND — NIET MET DE HAND BEWERKEN.
-- Alembic (backend/migrations/versions/) is de bron van waarheid voor het schema;
-- dit bestand is een referentie-dump voor leesbaarheid en code-review.
-- Regenereren: scripts/dump_schema.sh (pg_dump --schema-only boekhouding_test @ head).
-- Migratie-head bij deze dump: 0063
-- =============================================================================
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14 (Homebrew)
-- Dumped by pg_dump version 16.14 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: boekhouding; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA boekhouding;


--
-- Name: platform; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA platform;


--
-- Name: document_bron; Type: TYPE; Schema: boekhouding; Owner: -
--

CREATE TYPE boekhouding.document_bron AS ENUM (
    'upload',
    'email'
);


--
-- Name: document_status; Type: TYPE; Schema: boekhouding; Owner: -
--

CREATE TYPE boekhouding.document_status AS ENUM (
    'ontvangen',
    'extractie_wachtrij',
    'extractie_bezig',
    'te_controleren',
    'klaar_om_te_boeken',
    'geboekt',
    'vraag_open',
    'afgewezen',
    'boeken_mislukt',
    'niet_toegewezen',
    'verwijderd',
    'gesplitst',
    'handmatig_afmaken',
    'wacht_op_iban_accordering',
    'ter_accordering'
);


--
-- Name: gebruiker_rol; Type: TYPE; Schema: platform; Owner: -
--

CREATE TYPE platform.gebruiker_rol AS ENUM (
    'beheerder',
    'boekhouding_projecten',
    'boekhouding',
    'klant_accordeur',
    'zzper',
    'uitvoerder',
    'detacheerder'
);


--
-- Name: gebruiker_status; Type: TYPE; Schema: platform; Owner: -
--

CREATE TYPE platform.gebruiker_status AS ENUM (
    'uitgenodigd',
    'wacht_op_totp',
    'actief',
    'geblokkeerd',
    'wacht_op_passkey'
);


--
-- Name: actor_is_module_beheerder(text); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.actor_is_module_beheerder(p_module text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM platform.gebruiker_module_rol r
                WHERE r.gebruiker_id = platform.current_actor_id()
                  AND r.module = p_module
                  AND r.rol = CASE p_module WHEN 'vastgoed' THEN 'superadmin' ELSE NULL END
            )
            OR (p_module = 'boekhouding' AND platform.current_actor_is_beheerder())
        $$;


--
-- Name: audit_gebruiker_administratie_wijziging(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.audit_gebruiker_administratie_wijziging() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_actor uuid;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — scope-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_record := NEW.gebruiker_id;
                v_actie := 'scope_toegevoegd';
                v_nieuwe := jsonb_build_object('administratie_id', NEW.administratie_id);
                v_oude := NULL;
            ELSE
                v_record := OLD.gebruiker_id;
                v_actie := 'scope_verwijderd';
                v_oude := jsonb_build_object('administratie_id', OLD.administratie_id);
                v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, 'platform', 'gebruiker_administratie', v_record, v_actie, v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$;


--
-- Name: audit_gebruiker_entiteit_wijziging(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.audit_gebruiker_entiteit_wijziging() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
        DECLARE
            v_actor uuid;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — entiteit-scope-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_record := NEW.gebruiker_id; v_actie := 'entiteit_scope_toegevoegd';
                v_oude := NULL; v_nieuwe := jsonb_build_object('entiteit_id', NEW.entiteit_id);
            ELSE
                v_record := OLD.gebruiker_id; v_actie := 'entiteit_scope_verwijderd';
                v_oude := jsonb_build_object('entiteit_id', OLD.entiteit_id); v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, 'vastgoed', 'gebruiker_entiteit', v_record, v_actie,
                    v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$;


--
-- Name: audit_gebruiker_module_rol_wijziging(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.audit_gebruiker_module_rol_wijziging() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
        DECLARE
            v_actor uuid;
            v_module text;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — module-rol-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_module := NEW.module; v_record := NEW.gebruiker_id; v_actie := 'module_rol_toegevoegd';
                v_oude := NULL; v_nieuwe := jsonb_build_object('module', NEW.module, 'rol', NEW.rol);
            ELSIF TG_OP = 'UPDATE' THEN
                v_module := NEW.module; v_record := NEW.gebruiker_id; v_actie := 'module_rol_gewijzigd';
                v_oude := jsonb_build_object('module', OLD.module, 'rol', OLD.rol);
                v_nieuwe := jsonb_build_object('module', NEW.module, 'rol', NEW.rol);
            ELSE
                v_module := OLD.module; v_record := OLD.gebruiker_id; v_actie := 'module_rol_verwijderd';
                v_oude := jsonb_build_object('module', OLD.module, 'rol', OLD.rol); v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, v_module, 'gebruiker_module_rol', v_record, v_actie,
                    v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$;


--
-- Name: audit_gebruiker_rol_wijziging(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.audit_gebruiker_rol_wijziging() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_actor uuid;
        BEGIN
            IF NEW.rol IS DISTINCT FROM OLD.rol THEN
                v_actor := platform.current_actor_id();
                IF v_actor IS NULL THEN
                    RAISE EXCEPTION 'app.current_actor_id niet gezet — rol-wijziging vereist een bekende actor voor audit_event';
                END IF;
                INSERT INTO platform.audit_event
                    (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
                VALUES (
                    gen_random_uuid(), v_actor, 'platform', 'gebruiker', NEW.id, 'rol_wijziging',
                    jsonb_build_object('rol', OLD.rol), jsonb_build_object('rol', NEW.rol), gen_random_uuid()
                );
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: current_actor_id(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.current_actor_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
            SELECT nullif(current_setting('app.current_actor_id', true), '')::uuid
        $$;


--
-- Name: current_actor_is_beheerder(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.current_actor_is_beheerder() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM platform.gebruiker g
                WHERE g.id = platform.current_actor_id()
                  AND g.rol = 'beheerder'
                  AND g.status = 'actief'
            )
        $$;


--
-- Name: current_administratie_id(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.current_administratie_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
            SELECT nullif(current_setting('app.current_administratie_id', true), '')::uuid
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accordering_laag; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.accordering_laag (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    accordeur_gebruiker_id uuid NOT NULL,
    bedrag_drempel numeric(14,2),
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gedeactiveerd_door uuid,
    gedeactiveerd_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.accordering_laag FORCE ROW LEVEL SECURITY;


--
-- Name: accordering_stap; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.accordering_stap (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    accordering_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    accordeur_gebruiker_id uuid NOT NULL,
    bedrag_drempel numeric(14,2),
    vereist boolean DEFAULT true NOT NULL,
    besluit text,
    besluit_bron text,
    staande_regel_id uuid,
    reden text,
    besloten_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.accordering_stap FORCE ROW LEVEL SECURITY;


--
-- Name: afwijzing; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.afwijzing (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    afgewezen_door uuid NOT NULL,
    afgewezen_op timestamp with time zone DEFAULT now() NOT NULL,
    reden text NOT NULL,
    toegewezen_aan uuid NOT NULL,
    status_voor_afwijzing text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    heropend_door uuid,
    heropend_op timestamp with time zone,
    CONSTRAINT afwijzing_herkomst_herstelbaar CHECK ((status_voor_afwijzing = ANY (ARRAY['te_controleren'::text, 'handmatig_afmaken'::text, 'klaar_om_te_boeken'::text]))),
    CONSTRAINT afwijzing_heropening_consistent CHECK ((((status = 'open'::text) AND (heropend_door IS NULL) AND (heropend_op IS NULL)) OR ((status = 'heropend'::text) AND (heropend_door IS NOT NULL) AND (heropend_op IS NOT NULL)))),
    CONSTRAINT afwijzing_reden_niet_leeg CHECK ((btrim(reden) <> ''::text)),
    CONSTRAINT afwijzing_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'heropend'::text])))
);

ALTER TABLE ONLY boekhouding.afwijzing FORCE ROW LEVEL SECURITY;


--
-- Name: bank_afletter_opdracht; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_afletter_opdracht (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    payment_transaction_id uuid NOT NULL,
    payment_item_id uuid,
    rlz_document_id uuid,
    voorstel_detail jsonb,
    status text DEFAULT 'klaargezet'::text NOT NULL,
    klaargezet_door uuid NOT NULL,
    klaargezet_op timestamp with time zone DEFAULT now() NOT NULL,
    geverifieerd_op timestamp with time zone,
    verificatie_detail jsonb,
    ingetrokken_door uuid,
    ingetrokken_op timestamp with time zone,
    laatste_verificatie_poging_op timestamp with time zone,
    CONSTRAINT bank_afletter_opdracht_intrekking_consistent CHECK (((status = 'ingetrokken'::text) = (ingetrokken_op IS NOT NULL))),
    CONSTRAINT bank_afletter_opdracht_status_geldig CHECK ((status = ANY (ARRAY['klaargezet'::text, 'geverifieerd'::text, 'ingetrokken'::text]))),
    CONSTRAINT bank_afletter_opdracht_verificatie_consistent CHECK (((status = 'geverifieerd'::text) = (geverifieerd_op IS NOT NULL)))
);

ALTER TABLE ONLY boekhouding.bank_afletter_opdracht FORCE ROW LEVEL SECURITY;


--
-- Name: bank_boeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_boeking (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    payment_transaction_id uuid NOT NULL,
    rlz_document_id uuid NOT NULL,
    omschrijving text,
    rlz_boekstuknummer text,
    bron text DEFAULT 'handmatig'::text NOT NULL,
    status text DEFAULT 'geboekt'::text NOT NULL,
    geboekt_door uuid NOT NULL,
    geboekt_op timestamp with time zone DEFAULT now() NOT NULL,
    gestorneerd_door uuid,
    gestorneerd_op timestamp with time zone,
    storno_reden text,
    CONSTRAINT bank_boeking_bron_geldig CHECK ((bron = ANY (ARRAY['handmatig'::text, 'vaste_regel'::text, 'automatisch'::text]))),
    CONSTRAINT bank_boeking_status_geldig CHECK ((status = ANY (ARRAY['geboekt'::text, 'gestorneerd'::text]))),
    CONSTRAINT bank_boeking_storno_consistent CHECK (((status = 'gestorneerd'::text) = (gestorneerd_op IS NOT NULL)))
);

ALTER TABLE ONLY boekhouding.bank_boeking FORCE ROW LEVEL SECURITY;


--
-- Name: bank_boeking_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_boeking_regel (
    id uuid NOT NULL,
    bank_boeking_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    ledger_id uuid NOT NULL,
    taxrate_id uuid,
    project_id uuid,
    netto_bedrag numeric(14,2) NOT NULL,
    btw_bedrag numeric(14,2),
    omschrijving text
);

ALTER TABLE ONLY boekhouding.bank_boeking_regel FORCE ROW LEVEL SECURITY;


--
-- Name: bank_mutatie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_mutatie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    payment_account_id uuid,
    boekdatum date,
    bedrag numeric(14,2),
    open_bedrag numeric(14,2),
    tegenrekening_iban text,
    tegenpartij_naam text,
    omschrijving text,
    mutatie_type smallint,
    rlz_voorstel_item_id uuid,
    rlz_create_date timestamp with time zone,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.bank_mutatie FORCE ROW LEVEL SECURITY;


--
-- Name: bank_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_regel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    tegenpartij_sleutel text NOT NULL,
    tegenrekening_iban text,
    ledger_id uuid NOT NULL,
    taxrate_id uuid,
    project_id uuid,
    omschrijving text,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gedeactiveerd_door uuid,
    gedeactiveerd_op timestamp with time zone,
    CONSTRAINT bank_regel_sleutel_niet_leeg CHECK ((tegenpartij_sleutel <> ''::text))
);

ALTER TABLE ONLY boekhouding.bank_regel FORCE ROW LEVEL SECURITY;


--
-- Name: bank_sync_stand; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_sync_stand (
    administratie_id uuid NOT NULL,
    mutaties_watermark timestamp with time zone,
    laatste_sync_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.bank_sync_stand FORCE ROW LEVEL SECURITY;


--
-- Name: boeking_observatie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.boeking_observatie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    regel_sleutel text,
    regel_omschrijving_raw text,
    gb_id uuid NOT NULL,
    btw_id uuid,
    project_id uuid,
    bron text NOT NULL,
    bron_datum date NOT NULL,
    boekstuk_ref text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT boeking_observatie_bron_geldig CHECK ((bron = ANY (ARRAY['rlz_seed'::text, 'app'::text])))
);

ALTER TABLE ONLY boekhouding.boeking_observatie FORCE ROW LEVEL SECURITY;


--
-- Name: boekvoorstel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.boekvoorstel (
    document_id uuid NOT NULL,
    vendor_id uuid,
    referentie text,
    factuurdatum date,
    totaalbedrag numeric(14,2),
    rlz_boekstuknummer text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    boek_cyclus integer DEFAULT 0 NOT NULL
);

ALTER TABLE ONLY boekhouding.boekvoorstel FORCE ROW LEVEL SECURITY;


--
-- Name: boekvoorstel_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.boekvoorstel_regel (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    ledger_id uuid,
    taxrate_id uuid,
    project_id uuid,
    netto_bedrag numeric(14,2),
    btw_bedrag numeric(14,2),
    omschrijving text
);

ALTER TABLE ONLY boekhouding.boekvoorstel_regel FORCE ROW LEVEL SECURITY;


--
-- Name: document; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.document (
    id uuid NOT NULL,
    administratie_id uuid,
    bron boekhouding.document_bron NOT NULL,
    bestandsnaam text NOT NULL,
    sha256_hash text NOT NULL,
    status boekhouding.document_status DEFAULT 'ontvangen'::boekhouding.document_status NOT NULL,
    toegewezen_aan uuid,
    mogelijk_duplicaat_van_id uuid,
    opslag_pad text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    laatst_gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    soort text DEFAULT 'inkoopfactuur'::text NOT NULL,
    intake_bericht_id uuid,
    afzender_hint text,
    tenaamstelling text,
    toewijzing_suggestie_administratie_id uuid,
    toewijzing_suggestie_bron text,
    gesplitst_uit_id uuid,
    CONSTRAINT document_soort_geldig CHECK ((soort = ANY (ARRAY['inkoopfactuur'::text, 'kassarapport'::text, 'verkoopfactuur'::text, 'waarborg'::text])))
);

ALTER TABLE ONLY boekhouding.document FORCE ROW LEVEL SECURITY;


--
-- Name: document_accordering; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.document_accordering (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    aangeboden_door uuid NOT NULL,
    aangeboden_op timestamp with time zone DEFAULT now() NOT NULL,
    afgerond_op timestamp with time zone,
    detail jsonb
);

ALTER TABLE ONLY boekhouding.document_accordering FORCE ROW LEVEL SECURITY;


--
-- Name: document_gebeurtenis; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.document_gebeurtenis (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    van_status boekhouding.document_status,
    naar_status boekhouding.document_status NOT NULL,
    actor_id uuid NOT NULL,
    detail jsonb,
    tijdstip timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.document_gebeurtenis FORCE ROW LEVEL SECURITY;


--
-- Name: document_herinnering; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.document_herinnering (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    accordeur_gebruiker_id uuid NOT NULL,
    datum date NOT NULL,
    status text DEFAULT 'bezig'::text NOT NULL,
    kanaal text,
    detail jsonb,
    verzonden_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verzonden_op timestamp with time zone,
    CONSTRAINT ck_document_herinnering_kanaal CHECK (((kanaal IS NULL) OR (kanaal = ANY (ARRAY['push'::text, 'e-mail'::text])))),
    CONSTRAINT ck_document_herinnering_status CHECK ((status = ANY (ARRAY['bezig'::text, 'verzonden'::text, 'mislukt'::text, 'overgeslagen'::text])))
);

ALTER TABLE ONLY boekhouding.document_herinnering FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_boeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_boeking (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    mapping_id uuid NOT NULL,
    doel_administratie_id uuid,
    status text DEFAULT 'geboekt'::text NOT NULL,
    netto_totaal numeric(14,2) NOT NULL,
    provisie_bedrag numeric(14,2) NOT NULL,
    btw_bedrag numeric(14,2) NOT NULL,
    verkoop_rlz_id uuid NOT NULL,
    verkoop_referentie text,
    verkoop_invoice_number integer,
    spiegel_rlz_id uuid NOT NULL,
    spiegel_geboekt_op timestamp with time zone,
    half_geboekt_detail jsonb,
    storno_reden text,
    geboekt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT doorbelasting_boeking_status CHECK ((status = ANY (ARRAY['geboekt'::text, 'spiegel_open'::text, 'half_geboekt'::text, 'gestorneerd'::text]))),
    CONSTRAINT doorbelasting_boeking_storno_reden CHECK (((status <> 'gestorneerd'::text) OR ((storno_reden IS NOT NULL) AND (length(btrim(storno_reden)) >= 5))))
);

ALTER TABLE ONLY boekhouding.doorbelasting_boeking FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_instelling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_instelling (
    administratie_id uuid NOT NULL,
    provisie_percentage numeric(5,2) DEFAULT 5.00 NOT NULL,
    btw_taxrate_id uuid,
    omzet_ledger_id uuid,
    provisie_omzet_ledger_id uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT doorbelasting_instelling_provisie_bereik CHECK (((provisie_percentage >= (0)::numeric) AND (provisie_percentage <= (100)::numeric)))
);

ALTER TABLE ONLY boekhouding.doorbelasting_instelling FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_mapping; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_mapping (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    doelentiteit_naam text NOT NULL,
    doel_customer_guid uuid NOT NULL,
    doel_administratie_id uuid,
    intercompany boolean DEFAULT true NOT NULL,
    provisie_kosten_ledger_id uuid,
    laatste_kosten_ledger_id uuid,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.doorbelasting_mapping FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_regel (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    bron_regel_id uuid NOT NULL,
    mapping_id uuid NOT NULL,
    percentage numeric(5,2) NOT NULL,
    netto_deel numeric(14,2) NOT NULL,
    doel_kosten_ledger_id uuid,
    CONSTRAINT doorbelasting_regel_pct_bereik CHECK (((percentage > (0)::numeric) AND (percentage <= (100)::numeric)))
);

ALTER TABLE ONLY boekhouding.doorbelasting_regel FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_run; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_run (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    status text DEFAULT 'concept'::text NOT NULL,
    laatste_fout jsonb,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    geboekt_op timestamp with time zone,
    CONSTRAINT doorbelasting_run_status CHECK ((status = ANY (ARRAY['concept'::text, 'geboekt'::text, 'gestorneerd'::text])))
);

ALTER TABLE ONLY boekhouding.doorbelasting_run FORCE ROW LEVEL SECURITY;


--
-- Name: factuurmatch; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.factuurmatch (
    document_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    veldwerker_gebruiker_id uuid NOT NULL,
    uitkomst text NOT NULL,
    staten_som_uren numeric(8,2) NOT NULL,
    staten_som_bedrag numeric(12,2),
    factuur_bedrag numeric(14,2),
    factuur_uren numeric(8,2),
    verschil_bedrag numeric(14,2),
    verschil_uren numeric(8,2),
    tarief_ontbreekt boolean NOT NULL,
    details jsonb,
    berekend_op timestamp with time zone DEFAULT now() NOT NULL,
    afwijking_bevestigd_door uuid,
    afwijking_bevestigd_op timestamp with time zone,
    CONSTRAINT ck_factuurmatch_bevestigd_samen CHECK (((afwijking_bevestigd_door IS NULL) = (afwijking_bevestigd_op IS NULL))),
    CONSTRAINT ck_factuurmatch_uitkomst CHECK ((uitkomst = ANY (ARRAY['match'::text, 'match_alleen_uren'::text, 'afwijking'::text, 'niet_toetsbaar'::text])))
);

ALTER TABLE ONLY boekhouding.factuurmatch FORCE ROW LEVEL SECURITY;


--
-- Name: factuurmatch_staat; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.factuurmatch_staat (
    document_id uuid NOT NULL,
    weekstaat_id uuid NOT NULL,
    administratie_id uuid NOT NULL
);

ALTER TABLE ONLY boekhouding.factuurmatch_staat FORCE ROW LEVEL SECURITY;


--
-- Name: iban_accordering; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.iban_accordering (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    document_id uuid NOT NULL,
    nieuw_iban text NOT NULL,
    soort text NOT NULL,
    aangevraagd_door uuid NOT NULL,
    aangevraagd_op timestamp with time zone DEFAULT now() NOT NULL,
    status_voor_accordering text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    besloten_door uuid,
    besloten_op timestamp with time zone,
    afwijs_reden text,
    CONSTRAINT iban_accordering_besluit_consistent CHECK ((((status = 'open'::text) AND (besloten_door IS NULL) AND (besloten_op IS NULL) AND (afwijs_reden IS NULL)) OR ((status = 'geaccordeerd'::text) AND (besloten_door IS NOT NULL) AND (besloten_op IS NOT NULL) AND (afwijs_reden IS NULL)) OR ((status = 'afgewezen'::text) AND (besloten_door IS NOT NULL) AND (besloten_op IS NOT NULL) AND (btrim(afwijs_reden) <> ''::text)))),
    CONSTRAINT iban_accordering_herkomst_herstelbaar CHECK ((status_voor_accordering = ANY (ARRAY['te_controleren'::text, 'handmatig_afmaken'::text, 'klaar_om_te_boeken'::text]))),
    CONSTRAINT iban_accordering_iban_niet_leeg CHECK ((btrim(nieuw_iban) <> ''::text)),
    CONSTRAINT iban_accordering_soort_geldig CHECK ((soort = ANY (ARRAY['regulier'::text, 'g_rekening'::text]))),
    CONSTRAINT iban_accordering_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'geaccordeerd'::text, 'afgewezen'::text]))),
    CONSTRAINT iban_accordering_vier_ogen CHECK (((besloten_door IS NULL) OR (besloten_door <> aangevraagd_door)))
);

ALTER TABLE ONLY boekhouding.iban_accordering FORCE ROW LEVEL SECURITY;


--
-- Name: iban_accordeur; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.iban_accordeur (
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.iban_accordeur FORCE ROW LEVEL SECURITY;


--
-- Name: intake_bericht; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.intake_bericht (
    id uuid NOT NULL,
    message_id text,
    afzender text,
    onderwerp text,
    bron text DEFAULT 'eml_upload'::text NOT NULL,
    ontvangen_op timestamp with time zone,
    verwerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    verwerkt_door uuid NOT NULL,
    detail jsonb NOT NULL,
    CONSTRAINT intake_bericht_bron_geldig CHECK ((bron = ANY (ARRAY['eml_upload'::text, 'imap'::text])))
);

ALTER TABLE ONLY boekhouding.intake_bericht FORCE ROW LEVEL SECURITY;


--
-- Name: intake_splitsing; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.intake_splitsing (
    id uuid NOT NULL,
    bron_document_id uuid NOT NULL,
    voorstel jsonb NOT NULL,
    status text DEFAULT 'voorgesteld'::text NOT NULL,
    voorgesteld_op timestamp with time zone DEFAULT now() NOT NULL,
    besloten_door uuid,
    besloten_op timestamp with time zone,
    besluit_detail jsonb,
    CONSTRAINT intake_splitsing_besluit_consistent CHECK (((status = 'voorgesteld'::text) = (besloten_op IS NULL))),
    CONSTRAINT intake_splitsing_status_geldig CHECK ((status = ANY (ARRAY['voorgesteld'::text, 'bevestigd'::text, 'afgewezen'::text])))
);

ALTER TABLE ONLY boekhouding.intake_splitsing FORCE ROW LEVEL SECURITY;


--
-- Name: intercompany_tegenpartij; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.intercompany_tegenpartij (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    entity_guid uuid NOT NULL,
    naam text NOT NULL,
    bron text DEFAULT 'doorbelasting_mapping'::text NOT NULL,
    mapping_id uuid,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.intercompany_tegenpartij FORCE ROW LEVEL SECURITY;


--
-- Name: leverancier_iban; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.leverancier_iban (
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    iban text NOT NULL,
    bron text NOT NULL,
    bevestigd_door uuid,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT leverancier_iban_bevestigd_door_verplicht CHECK (((bron <> 'bevestigd'::text) OR (bevestigd_door IS NOT NULL))),
    CONSTRAINT leverancier_iban_bron_geldig CHECK ((bron = ANY (ARRAY['rlz_seed'::text, 'baseline'::text, 'bevestigd'::text])))
);

ALTER TABLE ONLY boekhouding.leverancier_iban FORCE ROW LEVEL SECURITY;


--
-- Name: leverancier_voorkeur; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.leverancier_voorkeur (
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    regels_samenvoegen boolean NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    autoboeken_ingeschakeld boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY boekhouding.leverancier_voorkeur FORCE ROW LEVEL SECURITY;


--
-- Name: leverancier_werknummer; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.leverancier_werknummer (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    werknummer text NOT NULL,
    bron text NOT NULL,
    bevestigd boolean NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bevestigd_door uuid,
    bevestigd_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.leverancier_werknummer FORCE ROW LEVEL SECURITY;


--
-- Name: meerwerk; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.meerwerk (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    omschrijving text NOT NULL,
    aantal numeric(10,2) NOT NULL,
    eenheid text NOT NULL,
    datum_uitgevoerd date NOT NULL,
    in_opdracht_van text,
    foto_opslag_pad text,
    foto_bestandsnaam text,
    foto_content_type text,
    gemeld_door uuid NOT NULL,
    gemeld_op timestamp with time zone DEFAULT now() NOT NULL,
    status text NOT NULL,
    prijs_per_eenheid numeric(10,2),
    bedrag numeric(12,2),
    facturatie_notitie text,
    beoordeeld_door uuid,
    beoordeeld_op timestamp with time zone,
    afwijs_reden text,
    doorbelast_op timestamp with time zone,
    verkoopfactuur_referentie text,
    vraag_tekst text,
    vraag_gesteld_door uuid,
    vraag_gesteld_op timestamp with time zone,
    vraag_antwoord text,
    vraag_beantwoord_op timestamp with time zone,
    CONSTRAINT ck_meerwerk_aantal CHECK ((aantal > (0)::numeric)),
    CONSTRAINT ck_meerwerk_afwijs_reden CHECK (((status <> 'afgewezen'::text) OR (afwijs_reden IS NOT NULL))),
    CONSTRAINT ck_meerwerk_doorbelast_referentie CHECK (((status <> 'doorbelast'::text) OR (verkoopfactuur_referentie IS NOT NULL))),
    CONSTRAINT ck_meerwerk_eenheid CHECK ((eenheid = ANY (ARRAY['m2'::text, 'm1'::text, 'stuks'::text, 'manuren'::text]))),
    CONSTRAINT ck_meerwerk_prijs_bevestigd CHECK (((status <> ALL (ARRAY['goedgekeurd'::text, 'doorbelast'::text])) OR ((prijs_per_eenheid IS NOT NULL) AND (bedrag IS NOT NULL)))),
    CONSTRAINT ck_meerwerk_status CHECK ((status = ANY (ARRAY['gemeld'::text, 'goedgekeurd'::text, 'doorbelast'::text, 'afgewezen'::text])))
);

ALTER TABLE ONLY boekhouding.meerwerk FORCE ROW LEVEL SECURITY;


--
-- Name: omzet_boeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.omzet_boeking (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    periode_start date NOT NULL,
    periode_eind date NOT NULL,
    totaal_omzet numeric(14,2) NOT NULL,
    totaal_kostprijs numeric(14,2) NOT NULL,
    verkoop_rlz_id uuid NOT NULL,
    verkoop_invoice_number integer,
    verkoop_referentie text,
    verkoop_boekstuknummer text,
    memoriaal_rlz_id uuid,
    memoriaal_referentie text,
    memoriaal_boekstuknummer text,
    status text DEFAULT 'geboekt'::text NOT NULL,
    half_geboekt_detail jsonb,
    geboekt_door uuid NOT NULL,
    geboekt_op timestamp with time zone DEFAULT now() NOT NULL,
    gestorneerd_door uuid,
    gestorneerd_op timestamp with time zone,
    storno_reden text,
    CONSTRAINT omzet_boeking_half_geboekt_consistent CHECK (((status = 'half_geboekt'::text) = (half_geboekt_detail IS NOT NULL))),
    CONSTRAINT omzet_boeking_periode_geldig CHECK ((periode_start <= periode_eind)),
    CONSTRAINT omzet_boeking_status_geldig CHECK ((status = ANY (ARRAY['geboekt'::text, 'half_geboekt'::text, 'gestorneerd'::text]))),
    CONSTRAINT omzet_boeking_storno_consistent CHECK (((status = 'gestorneerd'::text) = (gestorneerd_op IS NOT NULL)))
);

ALTER TABLE ONLY boekhouding.omzet_boeking FORCE ROW LEVEL SECURITY;


--
-- Name: omzet_categorie_mapping; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.omzet_categorie_mapping (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    categorie_sleutel text NOT NULL,
    weergave_naam text NOT NULL,
    omzet_ledger_id uuid NOT NULL,
    taxrate_id uuid NOT NULL,
    kostprijs_ledger_id uuid,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    gedeactiveerd_door uuid,
    gedeactiveerd_op timestamp with time zone,
    CONSTRAINT omzet_mapping_sleutel_niet_leeg CHECK ((categorie_sleutel <> ''::text))
);

ALTER TABLE ONLY boekhouding.omzet_categorie_mapping FORCE ROW LEVEL SECURITY;


--
-- Name: omzet_instelling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.omzet_instelling (
    administratie_id uuid NOT NULL,
    kasomzet_customer_id uuid,
    kasomzet_naam text,
    voorraad_ledger_id uuid,
    memoriaal_diary_id uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    verkoop_categorie_id uuid
);

ALTER TABLE ONLY boekhouding.omzet_instelling FORCE ROW LEVEL SECURITY;


--
-- Name: omzet_voorstel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.omzet_voorstel (
    document_id uuid NOT NULL,
    periode_start date,
    periode_eind date,
    rapport_totaal_omzet numeric(14,2),
    rapport_totaal_kostprijs numeric(14,2),
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.omzet_voorstel FORCE ROW LEVEL SECURITY;


--
-- Name: omzet_voorstel_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.omzet_voorstel_regel (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    categorie text NOT NULL,
    categorie_sleutel text NOT NULL,
    omzet_bedrag numeric(14,2),
    kostprijs_bedrag numeric(14,2),
    omzet_ledger_id uuid,
    taxrate_id uuid,
    kostprijs_ledger_id uuid
);

ALTER TABLE ONLY boekhouding.omzet_voorstel_regel FORCE ROW LEVEL SECURITY;


--
-- Name: payment_account_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.payment_account_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text,
    iban text,
    rekening_type smallint,
    saldo numeric(14,2),
    saldo_datum date,
    is_gearchiveerd boolean,
    gateway_state smallint,
    gateway_type smallint,
    laatste_import jsonb,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone,
    laatste_import_probe_fout text
);

ALTER TABLE ONLY boekhouding.payment_account_cache FORCE ROW LEVEL SECURITY;


--
-- Name: payment_item_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.payment_item_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    bedrag numeric(14,2),
    boekdatum date,
    vervaldatum date,
    referentie text,
    referentie2 text,
    rlz_document_id uuid,
    payment_status smallint,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone,
    entity_guid uuid,
    entity_naam text
);

ALTER TABLE ONLY boekhouding.payment_item_cache FORCE ROW LEVEL SECURITY;


--
-- Name: planning_toewijzing; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.planning_toewijzing (
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    project_id uuid NOT NULL,
    datum date NOT NULL,
    dagdeel text NOT NULL,
    toegevoegd_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_planning_toewijzing_dagdeel CHECK ((dagdeel = ANY (ARRAY['heel'::text, 'half'::text])))
);

ALTER TABLE ONLY boekhouding.planning_toewijzing FORCE ROW LEVEL SECURITY;


--
-- Name: project_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text,
    is_actief boolean,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.project_cache FORCE ROW LEVEL SECURITY;


--
-- Name: project_cijfers_sync_run; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_cijfers_sync_run (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    status text NOT NULL,
    aangevraagd_door uuid,
    aangevraagd_op timestamp with time zone DEFAULT now() NOT NULL,
    gestart_op timestamp with time zone,
    laatst_actief_op timestamp with time zone,
    beeindigd_op timestamp with time zone,
    documenten integer,
    regels integer,
    verdwenen integer,
    leesfouten integer,
    fout_reden text,
    CONSTRAINT ck_project_cijfers_sync_run_status CHECK ((status = ANY (ARRAY['wachtrij'::text, 'bezig'::text, 'klaar'::text, 'fout'::text])))
);

ALTER TABLE ONLY boekhouding.project_cijfers_sync_run FORCE ROW LEVEL SECURITY;


--
-- Name: project_document; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_document (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    soort text NOT NULL,
    titel text NOT NULL,
    versie_omschrijving text,
    opslag_pad text NOT NULL,
    bestandsnaam text NOT NULL,
    geupload_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_document_soort CHECK ((soort = ANY (ARRAY['contract'::text, 'offerte'::text])))
);

ALTER TABLE ONLY boekhouding.project_document FORCE ROW LEVEL SECURITY;


--
-- Name: project_ontleding_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_ontleding_regel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    project_document_id uuid NOT NULL,
    soort text NOT NULL,
    omschrijving text NOT NULL,
    citaat text,
    waarde jsonb,
    zekerheid numeric(4,3),
    status text NOT NULL,
    beslist_door uuid,
    beslist_op timestamp with time zone,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_ontleding_regel_soort CHECK ((soort = ANY (ARRAY['contract_m2'::text, 'looptijd'::text, 'huurtijd'::text, 'doorlopende_huur'::text, 'opdrachtgever'::text, 'werknummer'::text, 'staffel'::text, 'boete'::text]))),
    CONSTRAINT ck_project_ontleding_regel_status CHECK ((status = ANY (ARRAY['voorstel'::text, 'bevestigd'::text, 'afgewezen'::text])))
);

ALTER TABLE ONLY boekhouding.project_ontleding_regel FORCE ROW LEVEL SECURITY;


--
-- Name: project_regel_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_regel_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    rlz_document_id uuid NOT NULL,
    soort text NOT NULL,
    project_id uuid NOT NULL,
    ledger_id uuid,
    netto_bedrag numeric(14,2) NOT NULL,
    btw_bedrag numeric(14,2),
    datum date,
    referentie text,
    omschrijving text,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone,
    CONSTRAINT ck_project_regel_cache_soort CHECK ((soort = ANY (ARRAY['inkoop'::text, 'verkoop'::text])))
);

ALTER TABLE ONLY boekhouding.project_regel_cache FORCE ROW LEVEL SECURITY;


--
-- Name: project_specificatie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_specificatie (
    project_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    opdrachtgever text,
    werknummer_opdrachtgever text,
    soort_werk text,
    contract_m2 numeric(10,2),
    looptijd_van date,
    looptijd_tot date,
    huurtijd_omschrijving text,
    doorlopende_huur_omschrijving text,
    bijgewerkt_door uuid NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.project_specificatie FORCE ROW LEVEL SECURITY;


--
-- Name: project_staffel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_staffel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    omschrijving text NOT NULL,
    eenheid text NOT NULL,
    prijs_per_eenheid numeric(10,2) NOT NULL,
    verrekenbaar boolean NOT NULL,
    bron text,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_staffel_eenheid CHECK ((eenheid = ANY (ARRAY['m2'::text, 'm1'::text, 'stuks'::text, 'manuren'::text]))),
    CONSTRAINT ck_project_staffel_prijs CHECK ((prijs_per_eenheid >= (0)::numeric))
);

ALTER TABLE ONLY boekhouding.project_staffel FORCE ROW LEVEL SECURITY;


--
-- Name: projectaanvraag; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.projectaanvraag (
    bericht_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    nonce text NOT NULL,
    pand_referentie text NOT NULL,
    naam_invoer text NOT NULL,
    projectnaam text NOT NULL,
    rlz_project_id uuid NOT NULL,
    status text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT projectaanvraag_status_geldig CHECK ((status = ANY (ARRAY['aangemaakt'::text, 'bestond_al'::text])))
);

ALTER TABLE ONLY boekhouding.projectaanvraag FORCE ROW LEVEL SECURITY;


--
-- Name: reconciliatie_acceptatie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.reconciliatie_acceptatie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    bron text NOT NULL,
    record_id uuid NOT NULL,
    soort text NOT NULL,
    vingerafdruk text NOT NULL,
    detail text NOT NULL,
    reden text NOT NULL,
    geaccepteerd_door uuid NOT NULL,
    geaccepteerd_op timestamp with time zone DEFAULT now() NOT NULL,
    ingetrokken_door uuid,
    ingetrokken_op timestamp with time zone,
    CONSTRAINT reconciliatie_acceptatie_bron_geldig CHECK ((bron = ANY (ARRAY['documenten'::text, 'bank'::text, 'omzet'::text, 'doorbelasting'::text]))),
    CONSTRAINT reconciliatie_acceptatie_intrekking_compleet CHECK (((ingetrokken_op IS NULL) = (ingetrokken_door IS NULL))),
    CONSTRAINT reconciliatie_acceptatie_reden_gevuld CHECK ((length(btrim(reden)) >= 5))
);

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie FORCE ROW LEVEL SECURITY;


--
-- Name: staande_goedkeuring; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.staande_goedkeuring (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    accordeur_gebruiker_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    leverancier_naam text,
    bedrag numeric(14,2) NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bron_document_id uuid,
    ingetrokken_door uuid,
    ingetrokken_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.staande_goedkeuring FORCE ROW LEVEL SECURITY;


--
-- Name: taxrate_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.taxrate_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone,
    percentage numeric(6,4)
);

ALTER TABLE ONLY boekhouding.taxrate_cache FORCE ROW LEVEL SECURITY;


--
-- Name: tegenboeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.tegenboeking (
    document_id uuid NOT NULL,
    boek_cyclus integer NOT NULL,
    administratie_id uuid NOT NULL,
    soort text NOT NULL,
    reden text NOT NULL,
    rlz_tegenboeking_id uuid NOT NULL,
    rlz_boekstuknummer text,
    origineel_betaald_bedrag numeric(14,2),
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tegenboeking_reden CHECK ((length(btrim(reden)) >= 5)),
    CONSTRAINT ck_tegenboeking_soort CHECK ((soort = ANY (ARRAY['volledig'::text, 'vervang'::text])))
);

ALTER TABLE ONLY boekhouding.tegenboeking FORCE ROW LEVEL SECURITY;


--
-- Name: toewijzing_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.toewijzing_regel (
    id uuid NOT NULL,
    soort text NOT NULL,
    sleutel text NOT NULL,
    administratie_id uuid NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gedeactiveerd_door uuid,
    gedeactiveerd_op timestamp with time zone,
    CONSTRAINT toewijzing_regel_sleutel_niet_leeg CHECK ((sleutel <> ''::text)),
    CONSTRAINT toewijzing_regel_soort_geldig CHECK ((soort = ANY (ARRAY['tenaamstelling'::text, 'afzender'::text])))
);

ALTER TABLE ONLY boekhouding.toewijzing_regel FORCE ROW LEVEL SECURITY;


--
-- Name: uren_project_toewijzing; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.uren_project_toewijzing (
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    project_id uuid NOT NULL,
    toegevoegd_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.uren_project_toewijzing FORCE ROW LEVEL SECURITY;


--
-- Name: veldwerker_crediteur; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.veldwerker_crediteur (
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    uurtarief numeric(8,2),
    autoboeken_ingeschakeld boolean NOT NULL,
    gekoppeld_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_veldwerker_crediteur_uurtarief CHECK (((uurtarief IS NULL) OR (uurtarief >= (0)::numeric)))
);

ALTER TABLE ONLY boekhouding.veldwerker_crediteur FORCE ROW LEVEL SECURITY;


--
-- Name: vendor_cache; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.vendor_cache (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text,
    is_gearchiveerd boolean,
    brondata jsonb NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.vendor_cache FORCE ROW LEVEL SECURITY;


--
-- Name: verkoop_boeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.verkoop_boeking (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    factuurnummer text NOT NULL,
    is_creditnota boolean DEFAULT false NOT NULL,
    totaalbedrag_incl numeric(14,2) NOT NULL,
    debiteur_customer_id uuid NOT NULL,
    debiteur_naam text NOT NULL,
    verkoop_rlz_id uuid NOT NULL,
    verkoop_invoice_number integer,
    verkoop_referentie text,
    verkoop_boekstuknummer text,
    status text DEFAULT 'geboekt'::text NOT NULL,
    geboekt_door uuid NOT NULL,
    geboekt_op timestamp with time zone DEFAULT now() NOT NULL,
    gestorneerd_door uuid,
    gestorneerd_op timestamp with time zone,
    storno_reden text,
    CONSTRAINT verkoop_boeking_factuurnummer_niet_leeg CHECK ((factuurnummer <> ''::text)),
    CONSTRAINT verkoop_boeking_status_geldig CHECK ((status = ANY (ARRAY['geboekt'::text, 'gestorneerd'::text]))),
    CONSTRAINT verkoop_boeking_storno_consistent CHECK (((status = 'gestorneerd'::text) = (gestorneerd_op IS NOT NULL)))
);

ALTER TABLE ONLY boekhouding.verkoop_boeking FORCE ROW LEVEL SECURITY;


--
-- Name: verkoop_btw_voorkeur; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.verkoop_btw_voorkeur (
    administratie_id uuid NOT NULL,
    btw_categorie text NOT NULL,
    percentage_fractie numeric(6,4) NOT NULL,
    taxrate_id uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.verkoop_btw_voorkeur FORCE ROW LEVEL SECURITY;


--
-- Name: verkoop_voorstel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.verkoop_voorstel (
    document_id uuid NOT NULL,
    debiteur_naam text,
    factuurnummer text,
    factuurdatum date,
    totaalbedrag_incl numeric(14,2),
    is_creditnota boolean DEFAULT false NOT NULL,
    gecrediteerd_factuurnummer text,
    rlz_boekstuknummer text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.verkoop_voorstel FORCE ROW LEVEL SECURITY;


--
-- Name: verkoop_voorstel_regel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.verkoop_voorstel_regel (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    omschrijving text,
    netto_bedrag numeric(14,2),
    btw_bedrag numeric(14,2),
    gb_code text,
    ledger_id uuid,
    taxrate_id uuid
);

ALTER TABLE ONLY boekhouding.verkoop_voorstel_regel FORCE ROW LEVEL SECURITY;


--
-- Name: vraag; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.vraag (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    gesteld_door uuid NOT NULL,
    gesteld_op timestamp with time zone DEFAULT now() NOT NULL,
    vraag_tekst text NOT NULL,
    toegewezen_aan uuid NOT NULL,
    status_voor_vraag text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    antwoord_tekst text,
    beantwoord_door uuid,
    beantwoord_op timestamp with time zone,
    ingetrokken_door uuid,
    ingetrokken_op timestamp with time zone,
    ingetrokken_reden text,
    CONSTRAINT vraag_antwoord_consistent CHECK ((((status = 'open'::text) AND (antwoord_tekst IS NULL) AND (beantwoord_door IS NULL) AND (beantwoord_op IS NULL) AND (ingetrokken_door IS NULL) AND (ingetrokken_op IS NULL) AND (ingetrokken_reden IS NULL)) OR ((status = 'beantwoord'::text) AND (btrim(antwoord_tekst) <> ''::text) AND (beantwoord_door IS NOT NULL) AND (beantwoord_op IS NOT NULL) AND (ingetrokken_door IS NULL) AND (ingetrokken_op IS NULL) AND (ingetrokken_reden IS NULL)) OR ((status = 'ingetrokken'::text) AND (ingetrokken_door IS NOT NULL) AND (ingetrokken_op IS NOT NULL) AND (antwoord_tekst IS NULL) AND (beantwoord_door IS NULL) AND (beantwoord_op IS NULL)))),
    CONSTRAINT vraag_herkomst_herstelbaar CHECK ((status_voor_vraag = ANY (ARRAY['te_controleren'::text, 'handmatig_afmaken'::text, 'klaar_om_te_boeken'::text]))),
    CONSTRAINT vraag_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'beantwoord'::text, 'ingetrokken'::text]))),
    CONSTRAINT vraag_tekst_niet_leeg CHECK ((btrim(vraag_tekst) <> ''::text))
);

ALTER TABLE ONLY boekhouding.vraag FORCE ROW LEVEL SECURITY;


--
-- Name: waarborg_bericht; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.waarborg_bericht (
    document_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    bericht_id uuid NOT NULL,
    schema_versie text,
    verhuurder_entiteit text NOT NULL,
    rlz_admin_id_hint text,
    contract_referentie text NOT NULL,
    huurder text NOT NULL,
    bedrag numeric(12,2) NOT NULL,
    richting text NOT NULL,
    datum date NOT NULL,
    balans_gb_code text NOT NULL,
    tegenrekening_ledger_id uuid,
    status text DEFAULT 'open'::text NOT NULL,
    rlz_boekstuknummer text,
    geboekt_door uuid,
    geboekt_op timestamp with time zone,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT waarborg_bedrag_positief CHECK ((bedrag > (0)::numeric)),
    CONSTRAINT waarborg_richting_geldig CHECK ((richting = ANY (ARRAY['ontvangst'::text, 'terugbetaling'::text]))),
    CONSTRAINT waarborg_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'geboekt'::text])))
);

ALTER TABLE ONLY boekhouding.waarborg_bericht FORCE ROW LEVEL SECURITY;


--
-- Name: webhook_uitgaand; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.webhook_uitgaand (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    event text NOT NULL,
    payload jsonb NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    afgeleverd_op timestamp with time zone,
    status text DEFAULT 'openstaand'::text NOT NULL,
    pogingen integer DEFAULT 0 NOT NULL,
    laatste_poging_op timestamp with time zone,
    laatste_fout text,
    volgende_poging_op timestamp with time zone,
    administratie_id uuid,
    CONSTRAINT webhook_uitgaand_status_geldig CHECK ((status = ANY (ARRAY['openstaand'::text, 'afgeleverd'::text, 'mislukt'::text])))
);

ALTER TABLE ONLY boekhouding.webhook_uitgaand FORCE ROW LEVEL SECURITY;


--
-- Name: weekstaat; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.weekstaat (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    project_id uuid NOT NULL,
    jaar smallint NOT NULL,
    weeknummer smallint NOT NULL,
    status text NOT NULL,
    ingediend_op timestamp with time zone,
    ingediend_door uuid,
    goedgekeurd_op timestamp with time zone,
    goedgekeurd_door uuid,
    afgekeurd_op timestamp with time zone,
    afgekeurd_door uuid,
    afkeur_reden text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    verrekend_met_document_id uuid,
    verrekend_op timestamp with time zone,
    CONSTRAINT ck_weekstaat_afkeur_reden CHECK (((status <> 'corrigeren'::text) OR (afkeur_reden IS NOT NULL))),
    CONSTRAINT ck_weekstaat_goedgekeurd_velden CHECK (((status <> 'goedgekeurd'::text) OR ((goedgekeurd_op IS NOT NULL) AND (goedgekeurd_door IS NOT NULL)))),
    CONSTRAINT ck_weekstaat_status CHECK ((status = ANY (ARRAY['concept'::text, 'ingediend'::text, 'goedgekeurd'::text, 'corrigeren'::text]))),
    CONSTRAINT ck_weekstaat_verrekend_samen CHECK (((verrekend_met_document_id IS NULL) = (verrekend_op IS NULL))),
    CONSTRAINT ck_weekstaat_weeknummer CHECK (((weeknummer >= 1) AND (weeknummer <= 53)))
);

ALTER TABLE ONLY boekhouding.weekstaat FORCE ROW LEVEL SECURITY;


--
-- Name: weekstaat_correctie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.weekstaat_correctie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    weekstaat_id uuid NOT NULL,
    zzper_gebruiker_id uuid NOT NULL,
    afgekeurd_door uuid NOT NULL,
    afgekeurd_op timestamp with time zone DEFAULT now() NOT NULL,
    ingediend_uren numeric(8,2) NOT NULL,
    voorgesteld_uren numeric(8,2) NOT NULL,
    delta_uren numeric(8,2) NOT NULL,
    goedgekeurd_uren numeric(8,2),
    goedgekeurd_op timestamp with time zone,
    details jsonb,
    CONSTRAINT ck_weekstaat_correctie_goedgekeurd_samen CHECK (((goedgekeurd_uren IS NULL) = (goedgekeurd_op IS NULL))),
    CONSTRAINT ck_weekstaat_correctie_ingediend CHECK ((ingediend_uren >= (0)::numeric)),
    CONSTRAINT ck_weekstaat_correctie_voorgesteld CHECK ((voorgesteld_uren >= (0)::numeric))
);

ALTER TABLE ONLY boekhouding.weekstaat_correctie FORCE ROW LEVEL SECURITY;


--
-- Name: weekstaat_dag; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.weekstaat_dag (
    id uuid NOT NULL,
    weekstaat_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    datum date NOT NULL,
    uren numeric(5,2) NOT NULL,
    m2 numeric(8,2),
    opmerking text,
    ingevuld_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    voorstel_uren numeric(5,2),
    voorstel_m2 numeric(8,2),
    voorstel_opmerking text,
    CONSTRAINT ck_weekstaat_dag_m2 CHECK (((m2 IS NULL) OR (m2 >= (0)::numeric))),
    CONSTRAINT ck_weekstaat_dag_uren CHECK (((uren >= (0)::numeric) AND (uren <= (24)::numeric))),
    CONSTRAINT ck_weekstaat_dag_voorstel_m2 CHECK (((voorstel_m2 IS NULL) OR (voorstel_m2 >= (0)::numeric))),
    CONSTRAINT ck_weekstaat_dag_voorstel_uren CHECK (((voorstel_uren IS NULL) OR ((voorstel_uren >= (0)::numeric) AND (voorstel_uren <= (24)::numeric))))
);

ALTER TABLE ONLY boekhouding.weekstaat_dag FORCE ROW LEVEL SECURITY;


--
-- Name: accordeur_akkoord; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.accordeur_akkoord (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    tekst_versie text NOT NULL,
    akkoord_op timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: accordeur_herinnering; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.accordeur_herinnering (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    datum date NOT NULL,
    aantal_open integer NOT NULL,
    status text DEFAULT 'bezig'::text NOT NULL,
    kanaal text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verzonden_op timestamp with time zone,
    detail jsonb,
    CONSTRAINT ck_accordeur_herinnering_kanaal CHECK (((kanaal IS NULL) OR (kanaal = ANY (ARRAY['push'::text, 'e-mail'::text])))),
    CONSTRAINT ck_accordeur_herinnering_status CHECK ((status = ANY (ARRAY['bezig'::text, 'verzonden'::text, 'mislukt'::text, 'overgeslagen'::text])))
);


--
-- Name: accordeur_nieuw_gemeld; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.accordeur_nieuw_gemeld (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    document_id uuid NOT NULL,
    status text DEFAULT 'bezig'::text NOT NULL,
    kanaal text,
    detail jsonb,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verzonden_op timestamp with time zone,
    CONSTRAINT ck_accordeur_nieuw_gemeld_kanaal CHECK (((kanaal IS NULL) OR (kanaal = ANY (ARRAY['push'::text, 'e-mail'::text])))),
    CONSTRAINT ck_accordeur_nieuw_gemeld_status CHECK ((status = ANY (ARRAY['bezig'::text, 'verzonden'::text, 'mislukt'::text, 'overgeslagen'::text])))
);


--
-- Name: administratie; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.administratie (
    id uuid NOT NULL,
    naam text NOT NULL,
    rlz_admin_id text NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    boeken_ingeschakeld boolean DEFAULT false NOT NULL,
    project_verplicht boolean DEFAULT false NOT NULL,
    ai_extractie_ingeschakeld boolean DEFAULT false NOT NULL,
    is_vastgoed boolean DEFAULT false NOT NULL,
    eigenaar_gebruiker_id uuid,
    bank_autoboeken_ingeschakeld boolean DEFAULT false NOT NULL,
    accordering_ingeschakeld boolean DEFAULT false NOT NULL,
    afgeletterd_event_ingeschakeld boolean DEFAULT false NOT NULL,
    reconciliatie_uitgesloten boolean DEFAULT false NOT NULL,
    reconciliatie_uitsluiting_reden text,
    reconciliatie_uitgesloten_op timestamp with time zone,
    reconciliatie_uitgesloten_door uuid,
    doorbelasting_ingeschakeld boolean DEFAULT false NOT NULL,
    verkoop_autoboeken_ingeschakeld boolean DEFAULT false NOT NULL,
    uren_meerwerk_ingeschakeld boolean DEFAULT false NOT NULL,
    CONSTRAINT administratie_reconciliatie_uitsluiting_reden CHECK (((NOT reconciliatie_uitgesloten) OR ((reconciliatie_uitsluiting_reden IS NOT NULL) AND (length(btrim(reconciliatie_uitsluiting_reden)) >= 5))))
);


--
-- Name: ai_gebruik; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.ai_gebruik (
    id uuid NOT NULL,
    tijdstip timestamp with time zone DEFAULT now() NOT NULL,
    maand date NOT NULL,
    model character varying NOT NULL,
    bron character varying NOT NULL,
    document_id uuid,
    intake_bericht_id uuid,
    input_tokens bigint NOT NULL,
    output_tokens bigint NOT NULL,
    cache_schrijf_tokens bigint NOT NULL,
    cache_lees_tokens bigint NOT NULL,
    kosten_eur numeric(12,6) NOT NULL,
    CONSTRAINT ai_gebruik_kosten_niet_negatief CHECK ((kosten_eur >= (0)::numeric))
);


--
-- Name: ai_kosten_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.ai_kosten_instelling (
    singleton boolean DEFAULT true NOT NULL,
    maandlimiet_eur numeric(12,2) DEFAULT 100 NOT NULL,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_kosten_instelling_limiet_niet_negatief CHECK ((maandlimiet_eur >= (0)::numeric)),
    CONSTRAINT ai_kosten_instelling_singleton CHECK (singleton)
);


--
-- Name: ai_kosten_maandstatus; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.ai_kosten_maandstatus (
    maand date NOT NULL,
    waarschuwing_80_op timestamp with time zone,
    limiet_bereikt_op timestamp with time zone
);


--
-- Name: audit_event; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.audit_event (
    id uuid NOT NULL,
    tijdstip timestamp with time zone DEFAULT now() NOT NULL,
    actor_id uuid NOT NULL,
    module text NOT NULL,
    tabel text NOT NULL,
    record_id uuid NOT NULL,
    actie text NOT NULL,
    oude_waarde jsonb,
    nieuwe_waarde jsonb,
    correlatie_id uuid NOT NULL,
    administratie_id uuid
);

ALTER TABLE ONLY platform.audit_event FORCE ROW LEVEL SECURITY;


--
-- Name: TABLE audit_event; Type: COMMENT; Schema: platform; Owner: -
--

COMMENT ON TABLE platform.audit_event IS 'Append-only audit-log (bron voor de WORM-export). UPDATE/DELETE zijn niet gegrant aan de app-rol — zie GRANTs onderaan deze migratie.';


--
-- Name: boeken_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.boeken_instelling (
    singleton boolean DEFAULT true NOT NULL,
    globaal_ingeschakeld boolean DEFAULT true NOT NULL,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT boeken_instelling_singleton CHECK (singleton)
);


--
-- Name: detacheerder_koppeling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.detacheerder_koppeling (
    detacheerder_gebruiker_id uuid NOT NULL,
    zzper_gebruiker_id uuid NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    uurtarief numeric(8,2),
    CONSTRAINT ck_detacheerder_koppeling_uurtarief CHECK (((uurtarief IS NULL) OR (uurtarief >= (0)::numeric)))
);


--
-- Name: gebruiker; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.gebruiker (
    id uuid NOT NULL,
    naam text NOT NULL,
    e_mail text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gepseudonimiseerd_op timestamp with time zone,
    wachtwoord_hash text,
    rol platform.gebruiker_rol NOT NULL,
    status platform.gebruiker_status DEFAULT 'uitgenodigd'::platform.gebruiker_status NOT NULL,
    geblokkeerd_op timestamp with time zone,
    geblokkeerd_door uuid,
    status_voor_blokkade text,
    CONSTRAINT ck_gebruiker_e_mail_lowercase CHECK ((e_mail = lower(e_mail)))
);


--
-- Name: TABLE gebruiker; Type: COMMENT; Schema: platform; Owner: -
--

COMMENT ON TABLE platform.gebruiker IS 'PII van platformgebruikers. Bevat nooit financiële velden — die leven uitsluitend in het boekhouding-schema.';


--
-- Name: gebruiker_administratie; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.gebruiker_administratie (
    gebruiker_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY platform.gebruiker_administratie FORCE ROW LEVEL SECURITY;


--
-- Name: gebruiker_entiteit; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.gebruiker_entiteit (
    gebruiker_id uuid NOT NULL,
    entiteit_id uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY platform.gebruiker_entiteit FORCE ROW LEVEL SECURITY;


--
-- Name: gebruiker_module_rol; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.gebruiker_module_rol (
    gebruiker_id uuid NOT NULL,
    module text NOT NULL,
    rol text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_gebruiker_module_rol_geldig CHECK ((((module = 'vastgoed'::text) AND (rol = ANY (ARRAY['superadmin'::text, 'eigenaar'::text, 'kantoor'::text]))) OR ((module = 'boekhouding'::text) AND (rol = 'meerwerk_urenstaten'::text))))
);


--
-- Name: grootboekrekening; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.grootboekrekening (
    ledger_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    code text NOT NULL,
    naam text NOT NULL,
    soort smallint NOT NULL,
    is_totaalrekening boolean NOT NULL,
    laatst_gesynchroniseerd timestamp with time zone DEFAULT now() NOT NULL,
    verdwenen_uit_bron_op timestamp with time zone
);

ALTER TABLE ONLY platform.grootboekrekening FORCE ROW LEVEL SECURITY;


--
-- Name: intake_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.intake_instelling (
    singleton boolean DEFAULT true NOT NULL,
    ai_ingeschakeld boolean DEFAULT false NOT NULL,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT intake_instelling_singleton CHECK (singleton)
);


--
-- Name: push_subscriptie; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.push_subscriptie (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    apparaat_id uuid NOT NULL,
    endpoint text NOT NULL,
    p256dh text,
    auth text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    laatst_gebruikt_op timestamp with time zone,
    ingetrokken_op timestamp with time zone,
    ingetrokken_reden text,
    soort text DEFAULT 'webpush'::text NOT NULL,
    CONSTRAINT ck_push_subscriptie_reden CHECK (((ingetrokken_reden IS NULL) OR (ingetrokken_reden = ANY (ARRAY['gebruiker'::text, 'kill_switch'::text, 'vervallen'::text])))),
    CONSTRAINT ck_push_subscriptie_sleutels_bij_soort CHECK ((((soort = 'webpush'::text) AND (p256dh IS NOT NULL) AND (auth IS NOT NULL)) OR ((soort = ANY (ARRAY['apns'::text, 'fcm'::text])) AND (p256dh IS NULL) AND (auth IS NULL)))),
    CONSTRAINT ck_push_subscriptie_soort CHECK ((soort = ANY (ARRAY['webpush'::text, 'apns'::text, 'fcm'::text])))
);


--
-- Name: refresh_token; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.refresh_token (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    token_hash text NOT NULL,
    voorganger_id uuid,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verloopt_op timestamp with time zone NOT NULL,
    gebruikt_op timestamp with time zone,
    ingetrokken_op timestamp with time zone,
    apparaat_id uuid
);


--
-- Name: rlz_credential; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.rlz_credential (
    administratie_id uuid NOT NULL,
    webservice_username text NOT NULL,
    wachtwoord_ciphertext bytea NOT NULL,
    wrapped_data_key bytea NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rlz_rechten_probe; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.rlz_rechten_probe (
    administratie_id uuid NOT NULL,
    rapport jsonb NOT NULL,
    uitgevoerd_door uuid NOT NULL,
    uitgevoerd_op timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: totp_secret; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.totp_secret (
    gebruiker_id uuid NOT NULL,
    secret_ciphertext bytea NOT NULL,
    wrapped_data_key bytea NOT NULL,
    laatste_stap bigint,
    bevestigd_op timestamp with time zone,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: uitnodiging; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.uitnodiging (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    token_hash text NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verloopt_op timestamp with time zone NOT NULL,
    gebruikt_op timestamp with time zone
);


--
-- Name: webauthn_challenge; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.webauthn_challenge (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    soort text NOT NULL,
    challenge bytea NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verloopt_op timestamp with time zone NOT NULL,
    gebruikt_op timestamp with time zone,
    CONSTRAINT ck_webauthn_challenge_soort CHECK ((soort = ANY (ARRAY['registratie'::text, 'assertie'::text])))
);


--
-- Name: webauthn_credential; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.webauthn_credential (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count bigint DEFAULT '0'::bigint NOT NULL,
    aaguid text,
    transports jsonb,
    apparaat_naam text,
    is_dev_stub boolean DEFAULT false NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    laatst_gebruikt_op timestamp with time zone,
    ingetrokken_op timestamp with time zone,
    ingetrokken_door uuid
);


--
-- Name: webhook_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.webhook_instelling (
    singleton boolean DEFAULT true NOT NULL,
    aflevering_ingeschakeld boolean DEFAULT false NOT NULL,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT webhook_instelling_singleton CHECK (singleton)
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: accordering_laag accordering_laag_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_pkey PRIMARY KEY (id);


--
-- Name: accordering_stap accordering_stap_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_stap
    ADD CONSTRAINT accordering_stap_pkey PRIMARY KEY (id);


--
-- Name: afwijzing afwijzing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_pkey PRIMARY KEY (id);


--
-- Name: bank_afletter_opdracht bank_afletter_opdracht_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_afletter_opdracht
    ADD CONSTRAINT bank_afletter_opdracht_pkey PRIMARY KEY (id);


--
-- Name: bank_boeking bank_boeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking
    ADD CONSTRAINT bank_boeking_pkey PRIMARY KEY (id);


--
-- Name: bank_boeking_regel bank_boeking_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking_regel
    ADD CONSTRAINT bank_boeking_regel_pkey PRIMARY KEY (id);


--
-- Name: bank_mutatie bank_mutatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_mutatie
    ADD CONSTRAINT bank_mutatie_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: bank_regel bank_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_regel
    ADD CONSTRAINT bank_regel_pkey PRIMARY KEY (id);


--
-- Name: bank_sync_stand bank_sync_stand_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_sync_stand
    ADD CONSTRAINT bank_sync_stand_pkey PRIMARY KEY (administratie_id);


--
-- Name: boeking_observatie boeking_observatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boeking_observatie
    ADD CONSTRAINT boeking_observatie_pkey PRIMARY KEY (id);


--
-- Name: boekvoorstel boekvoorstel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boekvoorstel
    ADD CONSTRAINT boekvoorstel_pkey PRIMARY KEY (document_id);


--
-- Name: boekvoorstel_regel boekvoorstel_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boekvoorstel_regel
    ADD CONSTRAINT boekvoorstel_regel_pkey PRIMARY KEY (id);


--
-- Name: document_accordering document_accordering_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_accordering
    ADD CONSTRAINT document_accordering_pkey PRIMARY KEY (id);


--
-- Name: document_gebeurtenis document_gebeurtenis_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_gebeurtenis
    ADD CONSTRAINT document_gebeurtenis_pkey PRIMARY KEY (id);


--
-- Name: document_herinnering document_herinnering_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_herinnering
    ADD CONSTRAINT document_herinnering_pkey PRIMARY KEY (id);


--
-- Name: document document_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_pkey PRIMARY KEY (id);


--
-- Name: doorbelasting_instelling doorbelasting_instelling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_instelling
    ADD CONSTRAINT doorbelasting_instelling_pkey PRIMARY KEY (administratie_id);


--
-- Name: doorbelasting_mapping doorbelasting_mapping_doel_uniek; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_mapping
    ADD CONSTRAINT doorbelasting_mapping_doel_uniek UNIQUE (administratie_id, doel_customer_guid);


--
-- Name: doorbelasting_mapping doorbelasting_mapping_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_mapping
    ADD CONSTRAINT doorbelasting_mapping_pkey PRIMARY KEY (id);


--
-- Name: doorbelasting_regel doorbelasting_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_pkey PRIMARY KEY (id);


--
-- Name: doorbelasting_regel doorbelasting_regel_uniek; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_uniek UNIQUE (run_id, bron_regel_id, mapping_id);


--
-- Name: doorbelasting_run doorbelasting_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT doorbelasting_run_pkey PRIMARY KEY (id);


--
-- Name: factuurmatch factuurmatch_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch
    ADD CONSTRAINT factuurmatch_pkey PRIMARY KEY (document_id);


--
-- Name: factuurmatch_staat factuurmatch_staat_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch_staat
    ADD CONSTRAINT factuurmatch_staat_pkey PRIMARY KEY (document_id, weekstaat_id);


--
-- Name: iban_accordering iban_accordering_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordering
    ADD CONSTRAINT iban_accordering_pkey PRIMARY KEY (id);


--
-- Name: iban_accordeur iban_accordeur_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordeur
    ADD CONSTRAINT iban_accordeur_pkey PRIMARY KEY (administratie_id, gebruiker_id);


--
-- Name: intake_bericht intake_bericht_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_bericht
    ADD CONSTRAINT intake_bericht_pkey PRIMARY KEY (id);


--
-- Name: intake_splitsing intake_splitsing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing
    ADD CONSTRAINT intake_splitsing_pkey PRIMARY KEY (id);


--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intercompany_tegenpartij
    ADD CONSTRAINT intercompany_tegenpartij_pkey PRIMARY KEY (id);


--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_uniek; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intercompany_tegenpartij
    ADD CONSTRAINT intercompany_tegenpartij_uniek UNIQUE (administratie_id, entity_guid);


--
-- Name: leverancier_iban leverancier_iban_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_iban
    ADD CONSTRAINT leverancier_iban_pkey PRIMARY KEY (administratie_id, vendor_id, iban);


--
-- Name: leverancier_voorkeur leverancier_voorkeur_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_voorkeur
    ADD CONSTRAINT leverancier_voorkeur_pkey PRIMARY KEY (administratie_id, vendor_id);


--
-- Name: leverancier_werknummer leverancier_werknummer_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT leverancier_werknummer_pkey PRIMARY KEY (id);


--
-- Name: meerwerk meerwerk_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_pkey PRIMARY KEY (id);


--
-- Name: omzet_boeking omzet_boeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_boeking
    ADD CONSTRAINT omzet_boeking_pkey PRIMARY KEY (id);


--
-- Name: omzet_categorie_mapping omzet_categorie_mapping_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_categorie_mapping
    ADD CONSTRAINT omzet_categorie_mapping_pkey PRIMARY KEY (id);


--
-- Name: omzet_instelling omzet_instelling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_instelling
    ADD CONSTRAINT omzet_instelling_pkey PRIMARY KEY (administratie_id);


--
-- Name: omzet_voorstel omzet_voorstel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_voorstel
    ADD CONSTRAINT omzet_voorstel_pkey PRIMARY KEY (document_id);


--
-- Name: omzet_voorstel_regel omzet_voorstel_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_voorstel_regel
    ADD CONSTRAINT omzet_voorstel_regel_pkey PRIMARY KEY (id);


--
-- Name: payment_account_cache payment_account_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.payment_account_cache
    ADD CONSTRAINT payment_account_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: payment_item_cache payment_item_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.payment_item_cache
    ADD CONSTRAINT payment_item_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: planning_toewijzing planning_toewijzing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.planning_toewijzing
    ADD CONSTRAINT planning_toewijzing_pkey PRIMARY KEY (administratie_id, gebruiker_id, project_id, datum);


--
-- Name: project_cache project_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_cache
    ADD CONSTRAINT project_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: project_cijfers_sync_run project_cijfers_sync_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_cijfers_sync_run
    ADD CONSTRAINT project_cijfers_sync_run_pkey PRIMARY KEY (id);


--
-- Name: project_document project_document_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_document
    ADD CONSTRAINT project_document_pkey PRIMARY KEY (id);


--
-- Name: project_ontleding_regel project_ontleding_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_ontleding_regel
    ADD CONSTRAINT project_ontleding_regel_pkey PRIMARY KEY (id);


--
-- Name: project_regel_cache project_regel_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_regel_cache
    ADD CONSTRAINT project_regel_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: project_specificatie project_specificatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_specificatie
    ADD CONSTRAINT project_specificatie_pkey PRIMARY KEY (project_id, administratie_id);


--
-- Name: project_staffel project_staffel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_staffel
    ADD CONSTRAINT project_staffel_pkey PRIMARY KEY (id);


--
-- Name: projectaanvraag projectaanvraag_nonce_key; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectaanvraag
    ADD CONSTRAINT projectaanvraag_nonce_key UNIQUE (nonce);


--
-- Name: projectaanvraag projectaanvraag_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectaanvraag
    ADD CONSTRAINT projectaanvraag_pkey PRIMARY KEY (bericht_id);


--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie
    ADD CONSTRAINT reconciliatie_acceptatie_pkey PRIMARY KEY (id);


--
-- Name: staande_goedkeuring staande_goedkeuring_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_pkey PRIMARY KEY (id);


--
-- Name: taxrate_cache taxrate_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.taxrate_cache
    ADD CONSTRAINT taxrate_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: tegenboeking tegenboeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.tegenboeking
    ADD CONSTRAINT tegenboeking_pkey PRIMARY KEY (document_id, boek_cyclus);


--
-- Name: toewijzing_regel toewijzing_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.toewijzing_regel
    ADD CONSTRAINT toewijzing_regel_pkey PRIMARY KEY (id);


--
-- Name: leverancier_werknummer uq_leverancier_werknummer; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT uq_leverancier_werknummer UNIQUE (administratie_id, vendor_id, werknummer);


--
-- Name: veldwerker_crediteur uq_veldwerker_crediteur_vendor; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_crediteur
    ADD CONSTRAINT uq_veldwerker_crediteur_vendor UNIQUE (administratie_id, vendor_id);


--
-- Name: weekstaat_dag uq_weekstaat_dag_datum; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_dag
    ADD CONSTRAINT uq_weekstaat_dag_datum UNIQUE (weekstaat_id, datum);


--
-- Name: weekstaat uq_weekstaat_persoon_project_week; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT uq_weekstaat_persoon_project_week UNIQUE (administratie_id, gebruiker_id, project_id, jaar, weeknummer);


--
-- Name: uren_project_toewijzing uren_project_toewijzing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.uren_project_toewijzing
    ADD CONSTRAINT uren_project_toewijzing_pkey PRIMARY KEY (administratie_id, gebruiker_id, project_id);


--
-- Name: veldwerker_crediteur veldwerker_crediteur_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_crediteur
    ADD CONSTRAINT veldwerker_crediteur_pkey PRIMARY KEY (administratie_id, gebruiker_id);


--
-- Name: vendor_cache vendor_cache_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vendor_cache
    ADD CONSTRAINT vendor_cache_pkey PRIMARY KEY (id, administratie_id);


--
-- Name: verkoop_boeking verkoop_boeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_boeking
    ADD CONSTRAINT verkoop_boeking_pkey PRIMARY KEY (id);


--
-- Name: verkoop_btw_voorkeur verkoop_btw_voorkeur_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_btw_voorkeur
    ADD CONSTRAINT verkoop_btw_voorkeur_pkey PRIMARY KEY (administratie_id, btw_categorie, percentage_fractie);


--
-- Name: verkoop_voorstel verkoop_voorstel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_voorstel
    ADD CONSTRAINT verkoop_voorstel_pkey PRIMARY KEY (document_id);


--
-- Name: verkoop_voorstel_regel verkoop_voorstel_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_voorstel_regel
    ADD CONSTRAINT verkoop_voorstel_regel_pkey PRIMARY KEY (id);


--
-- Name: vraag vraag_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_pkey PRIMARY KEY (id);


--
-- Name: waarborg_bericht waarborg_bericht_bericht_id_key; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.waarborg_bericht
    ADD CONSTRAINT waarborg_bericht_bericht_id_key UNIQUE (bericht_id);


--
-- Name: waarborg_bericht waarborg_bericht_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.waarborg_bericht
    ADD CONSTRAINT waarborg_bericht_pkey PRIMARY KEY (document_id);


--
-- Name: webhook_uitgaand webhook_uitgaand_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.webhook_uitgaand
    ADD CONSTRAINT webhook_uitgaand_pkey PRIMARY KEY (id);


--
-- Name: weekstaat_correctie weekstaat_correctie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_correctie
    ADD CONSTRAINT weekstaat_correctie_pkey PRIMARY KEY (id);


--
-- Name: weekstaat_dag weekstaat_dag_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_dag
    ADD CONSTRAINT weekstaat_dag_pkey PRIMARY KEY (id);


--
-- Name: weekstaat weekstaat_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_pkey PRIMARY KEY (id);


--
-- Name: accordeur_akkoord accordeur_akkoord_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_akkoord
    ADD CONSTRAINT accordeur_akkoord_pkey PRIMARY KEY (id);


--
-- Name: accordeur_herinnering accordeur_herinnering_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_herinnering
    ADD CONSTRAINT accordeur_herinnering_pkey PRIMARY KEY (id);


--
-- Name: accordeur_nieuw_gemeld accordeur_nieuw_gemeld_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_nieuw_gemeld
    ADD CONSTRAINT accordeur_nieuw_gemeld_pkey PRIMARY KEY (id);


--
-- Name: administratie administratie_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.administratie
    ADD CONSTRAINT administratie_pkey PRIMARY KEY (id);


--
-- Name: administratie administratie_rlz_admin_id_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.administratie
    ADD CONSTRAINT administratie_rlz_admin_id_key UNIQUE (rlz_admin_id);


--
-- Name: ai_gebruik ai_gebruik_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.ai_gebruik
    ADD CONSTRAINT ai_gebruik_pkey PRIMARY KEY (id);


--
-- Name: ai_kosten_instelling ai_kosten_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.ai_kosten_instelling
    ADD CONSTRAINT ai_kosten_instelling_pkey PRIMARY KEY (singleton);


--
-- Name: ai_kosten_maandstatus ai_kosten_maandstatus_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.ai_kosten_maandstatus
    ADD CONSTRAINT ai_kosten_maandstatus_pkey PRIMARY KEY (maand);


--
-- Name: audit_event audit_event_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.audit_event
    ADD CONSTRAINT audit_event_pkey PRIMARY KEY (id);


--
-- Name: boeken_instelling boeken_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.boeken_instelling
    ADD CONSTRAINT boeken_instelling_pkey PRIMARY KEY (singleton);


--
-- Name: detacheerder_koppeling detacheerder_koppeling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.detacheerder_koppeling
    ADD CONSTRAINT detacheerder_koppeling_pkey PRIMARY KEY (detacheerder_gebruiker_id, zzper_gebruiker_id);


--
-- Name: gebruiker_administratie gebruiker_administratie_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_administratie
    ADD CONSTRAINT gebruiker_administratie_pkey PRIMARY KEY (gebruiker_id, administratie_id);


--
-- Name: gebruiker gebruiker_e_mail_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker
    ADD CONSTRAINT gebruiker_e_mail_key UNIQUE (e_mail);


--
-- Name: gebruiker_entiteit gebruiker_entiteit_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_entiteit
    ADD CONSTRAINT gebruiker_entiteit_pkey PRIMARY KEY (gebruiker_id, entiteit_id);


--
-- Name: gebruiker_module_rol gebruiker_module_rol_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_module_rol
    ADD CONSTRAINT gebruiker_module_rol_pkey PRIMARY KEY (gebruiker_id, module);


--
-- Name: gebruiker gebruiker_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker
    ADD CONSTRAINT gebruiker_pkey PRIMARY KEY (id);


--
-- Name: grootboekrekening grootboekrekening_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.grootboekrekening
    ADD CONSTRAINT grootboekrekening_pkey PRIMARY KEY (ledger_id, administratie_id);


--
-- Name: intake_instelling intake_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.intake_instelling
    ADD CONSTRAINT intake_instelling_pkey PRIMARY KEY (singleton);


--
-- Name: push_subscriptie push_subscriptie_endpoint_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.push_subscriptie
    ADD CONSTRAINT push_subscriptie_endpoint_key UNIQUE (endpoint);


--
-- Name: push_subscriptie push_subscriptie_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.push_subscriptie
    ADD CONSTRAINT push_subscriptie_pkey PRIMARY KEY (id);


--
-- Name: refresh_token refresh_token_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.refresh_token
    ADD CONSTRAINT refresh_token_pkey PRIMARY KEY (id);


--
-- Name: refresh_token refresh_token_token_hash_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.refresh_token
    ADD CONSTRAINT refresh_token_token_hash_key UNIQUE (token_hash);


--
-- Name: rlz_credential rlz_credential_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_credential
    ADD CONSTRAINT rlz_credential_pkey PRIMARY KEY (administratie_id);


--
-- Name: rlz_rechten_probe rlz_rechten_probe_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_rechten_probe
    ADD CONSTRAINT rlz_rechten_probe_pkey PRIMARY KEY (administratie_id);


--
-- Name: totp_secret totp_secret_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.totp_secret
    ADD CONSTRAINT totp_secret_pkey PRIMARY KEY (gebruiker_id);


--
-- Name: uitnodiging uitnodiging_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.uitnodiging
    ADD CONSTRAINT uitnodiging_pkey PRIMARY KEY (id);


--
-- Name: uitnodiging uitnodiging_token_hash_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.uitnodiging
    ADD CONSTRAINT uitnodiging_token_hash_key UNIQUE (token_hash);


--
-- Name: accordeur_akkoord uq_accordeur_akkoord_versie; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_akkoord
    ADD CONSTRAINT uq_accordeur_akkoord_versie UNIQUE (gebruiker_id, tekst_versie);


--
-- Name: accordeur_herinnering uq_accordeur_herinnering_dag; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_herinnering
    ADD CONSTRAINT uq_accordeur_herinnering_dag UNIQUE (gebruiker_id, datum);


--
-- Name: accordeur_nieuw_gemeld uq_accordeur_nieuw_gemeld; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_nieuw_gemeld
    ADD CONSTRAINT uq_accordeur_nieuw_gemeld UNIQUE (gebruiker_id, document_id);


--
-- Name: webauthn_challenge webauthn_challenge_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_challenge
    ADD CONSTRAINT webauthn_challenge_pkey PRIMARY KEY (id);


--
-- Name: webauthn_credential webauthn_credential_credential_id_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_credential
    ADD CONSTRAINT webauthn_credential_credential_id_key UNIQUE (credential_id);


--
-- Name: webauthn_credential webauthn_credential_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_credential
    ADD CONSTRAINT webauthn_credential_pkey PRIMARY KEY (id);


--
-- Name: webhook_instelling webhook_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webhook_instelling
    ADD CONSTRAINT webhook_instelling_pkey PRIMARY KEY (singleton);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: afwijzing_een_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX afwijzing_een_open_per_document ON boekhouding.afwijzing USING btree (document_id) WHERE (status = 'open'::text);


--
-- Name: doorbelasting_boeking_doc_doel_uniek; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX doorbelasting_boeking_doc_doel_uniek ON boekhouding.doorbelasting_boeking USING btree (document_id, mapping_id) WHERE (status <> 'gestorneerd'::text);


--
-- Name: doorbelasting_run_document_actief_uniek; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX doorbelasting_run_document_actief_uniek ON boekhouding.doorbelasting_run USING btree (document_id) WHERE (status <> 'gestorneerd'::text);


--
-- Name: iban_accordering_een_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX iban_accordering_een_open_per_document ON boekhouding.iban_accordering USING btree (document_id) WHERE (status = 'open'::text);


--
-- Name: ix_accordering_laag_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_accordering_laag_administratie_id ON boekhouding.accordering_laag USING btree (administratie_id);


--
-- Name: ix_accordering_stap_accordering_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_accordering_stap_accordering_id ON boekhouding.accordering_stap USING btree (accordering_id);


--
-- Name: ix_bank_boeking_regel_boeking_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_boeking_regel_boeking_id ON boekhouding.bank_boeking_regel USING btree (bank_boeking_id);


--
-- Name: ix_bank_mutatie_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_mutatie_administratie_id ON boekhouding.bank_mutatie USING btree (administratie_id);


--
-- Name: ix_bank_mutatie_open; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_mutatie_open ON boekhouding.bank_mutatie USING btree (administratie_id, payment_account_id) WHERE ((open_bedrag IS NOT NULL) AND (open_bedrag <> (0)::numeric));


--
-- Name: ix_boeking_observatie_admin_vendor_sleutel; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_boeking_observatie_admin_vendor_sleutel ON boekhouding.boeking_observatie USING btree (administratie_id, vendor_id, regel_sleutel);


--
-- Name: ix_boekvoorstel_regel_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_boekvoorstel_regel_document_id ON boekhouding.boekvoorstel_regel USING btree (document_id);


--
-- Name: ix_document_accordering_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_accordering_document_id ON boekhouding.document_accordering USING btree (document_id);


--
-- Name: ix_document_administratie_hash; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_administratie_hash ON boekhouding.document USING btree (administratie_id, sha256_hash);


--
-- Name: ix_document_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_administratie_id ON boekhouding.document USING btree (administratie_id);


--
-- Name: ix_document_gebeurtenis_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_gebeurtenis_document_id ON boekhouding.document_gebeurtenis USING btree (document_id);


--
-- Name: ix_document_gebeurtenis_tijdstip; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_gebeurtenis_tijdstip ON boekhouding.document_gebeurtenis USING btree (tijdstip);


--
-- Name: ix_document_herinnering_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_herinnering_administratie_id ON boekhouding.document_herinnering USING btree (administratie_id);


--
-- Name: ix_document_herinnering_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_herinnering_document_id ON boekhouding.document_herinnering USING btree (document_id);


--
-- Name: ix_document_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_status ON boekhouding.document USING btree (status);


--
-- Name: ix_factuurmatch_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_factuurmatch_administratie_id ON boekhouding.factuurmatch USING btree (administratie_id);


--
-- Name: ix_factuurmatch_administratie_uitkomst; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_factuurmatch_administratie_uitkomst ON boekhouding.factuurmatch USING btree (administratie_id, uitkomst);


--
-- Name: ix_factuurmatch_staat_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_factuurmatch_staat_administratie_id ON boekhouding.factuurmatch_staat USING btree (administratie_id);


--
-- Name: ix_factuurmatch_staat_weekstaat_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_factuurmatch_staat_weekstaat_id ON boekhouding.factuurmatch_staat USING btree (weekstaat_id);


--
-- Name: ix_leverancier_werknummer_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_leverancier_werknummer_administratie_id ON boekhouding.leverancier_werknummer USING btree (administratie_id);


--
-- Name: ix_leverancier_werknummer_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_leverancier_werknummer_project ON boekhouding.leverancier_werknummer USING btree (administratie_id, project_id);


--
-- Name: ix_meerwerk_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_meerwerk_administratie_id ON boekhouding.meerwerk USING btree (administratie_id);


--
-- Name: ix_meerwerk_administratie_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_meerwerk_administratie_status ON boekhouding.meerwerk USING btree (administratie_id, status);


--
-- Name: ix_omzet_boeking_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_omzet_boeking_document_id ON boekhouding.omzet_boeking USING btree (document_id);


--
-- Name: ix_omzet_voorstel_regel_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_omzet_voorstel_regel_document_id ON boekhouding.omzet_voorstel_regel USING btree (document_id);


--
-- Name: ix_payment_account_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_payment_account_cache_administratie_id ON boekhouding.payment_account_cache USING btree (administratie_id);


--
-- Name: ix_payment_item_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_payment_item_cache_administratie_id ON boekhouding.payment_item_cache USING btree (administratie_id);


--
-- Name: ix_planning_toewijzing_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_planning_toewijzing_administratie_id ON boekhouding.planning_toewijzing USING btree (administratie_id);


--
-- Name: ix_planning_toewijzing_datum; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_planning_toewijzing_datum ON boekhouding.planning_toewijzing USING btree (administratie_id, datum);


--
-- Name: ix_planning_toewijzing_gebruiker; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_planning_toewijzing_gebruiker ON boekhouding.planning_toewijzing USING btree (administratie_id, gebruiker_id, datum);


--
-- Name: ix_project_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_cache_administratie_id ON boekhouding.project_cache USING btree (administratie_id);


--
-- Name: ix_project_cijfers_sync_run_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_cijfers_sync_run_administratie_id ON boekhouding.project_cijfers_sync_run USING btree (administratie_id);


--
-- Name: ix_project_cijfers_sync_run_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_cijfers_sync_run_status ON boekhouding.project_cijfers_sync_run USING btree (administratie_id, status);


--
-- Name: ix_project_document_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_document_administratie_id ON boekhouding.project_document USING btree (administratie_id);


--
-- Name: ix_project_document_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_document_project ON boekhouding.project_document USING btree (administratie_id, project_id);


--
-- Name: ix_project_ontleding_regel_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_ontleding_regel_administratie_id ON boekhouding.project_ontleding_regel USING btree (administratie_id);


--
-- Name: ix_project_ontleding_regel_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_ontleding_regel_project ON boekhouding.project_ontleding_regel USING btree (administratie_id, project_id);


--
-- Name: ix_project_regel_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_regel_cache_administratie_id ON boekhouding.project_regel_cache USING btree (administratie_id);


--
-- Name: ix_project_regel_cache_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_regel_cache_document ON boekhouding.project_regel_cache USING btree (administratie_id, rlz_document_id);


--
-- Name: ix_project_regel_cache_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_regel_cache_project ON boekhouding.project_regel_cache USING btree (administratie_id, project_id);


--
-- Name: ix_project_staffel_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_staffel_administratie_id ON boekhouding.project_staffel USING btree (administratie_id);


--
-- Name: ix_project_staffel_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_staffel_project ON boekhouding.project_staffel USING btree (administratie_id, project_id);


--
-- Name: ix_staande_goedkeuring_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_staande_goedkeuring_administratie_id ON boekhouding.staande_goedkeuring USING btree (administratie_id);


--
-- Name: ix_taxrate_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_taxrate_cache_administratie_id ON boekhouding.taxrate_cache USING btree (administratie_id);


--
-- Name: ix_tegenboeking_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_tegenboeking_administratie_id ON boekhouding.tegenboeking USING btree (administratie_id);


--
-- Name: ix_uren_project_toewijzing_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_uren_project_toewijzing_administratie_id ON boekhouding.uren_project_toewijzing USING btree (administratie_id);


--
-- Name: ix_veldwerker_crediteur_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_veldwerker_crediteur_administratie_id ON boekhouding.veldwerker_crediteur USING btree (administratie_id);


--
-- Name: ix_vendor_cache_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_vendor_cache_administratie_id ON boekhouding.vendor_cache USING btree (administratie_id);


--
-- Name: ix_verkoop_boeking_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_verkoop_boeking_document_id ON boekhouding.verkoop_boeking USING btree (document_id);


--
-- Name: ix_verkoop_voorstel_regel_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_verkoop_voorstel_regel_document_id ON boekhouding.verkoop_voorstel_regel USING btree (document_id);


--
-- Name: ix_webhook_uitgaand_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_webhook_uitgaand_administratie_id ON boekhouding.webhook_uitgaand USING btree (administratie_id);


--
-- Name: ix_webhook_uitgaand_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_webhook_uitgaand_document_id ON boekhouding.webhook_uitgaand USING btree (document_id);


--
-- Name: ix_webhook_uitgaand_openstaand; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_webhook_uitgaand_openstaand ON boekhouding.webhook_uitgaand USING btree (volgende_poging_op) WHERE (status = 'openstaand'::text);


--
-- Name: ix_weekstaat_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_administratie_id ON boekhouding.weekstaat USING btree (administratie_id);


--
-- Name: ix_weekstaat_administratie_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_administratie_status ON boekhouding.weekstaat USING btree (administratie_id, status);


--
-- Name: ix_weekstaat_correctie_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_correctie_administratie_id ON boekhouding.weekstaat_correctie USING btree (administratie_id);


--
-- Name: ix_weekstaat_correctie_weekstaat_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_correctie_weekstaat_id ON boekhouding.weekstaat_correctie USING btree (weekstaat_id);


--
-- Name: ix_weekstaat_correctie_zzper; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_correctie_zzper ON boekhouding.weekstaat_correctie USING btree (administratie_id, zzper_gebruiker_id);


--
-- Name: ix_weekstaat_dag_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_dag_administratie_id ON boekhouding.weekstaat_dag USING btree (administratie_id);


--
-- Name: ix_weekstaat_dag_weekstaat_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_dag_weekstaat_id ON boekhouding.weekstaat_dag USING btree (weekstaat_id);


--
-- Name: ix_weekstaat_gebruiker; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_weekstaat_gebruiker ON boekhouding.weekstaat USING btree (administratie_id, gebruiker_id);


--
-- Name: reconciliatie_acceptatie_actief_uniek; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX reconciliatie_acceptatie_actief_uniek ON boekhouding.reconciliatie_acceptatie USING btree (administratie_id, bron, vingerafdruk) WHERE (ingetrokken_op IS NULL);


--
-- Name: uq_document_accordering_open; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX uq_document_accordering_open ON boekhouding.document_accordering USING btree (document_id) WHERE (status = 'open'::text);


--
-- Name: uq_document_herinnering_dag; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX uq_document_herinnering_dag ON boekhouding.document_herinnering USING btree (document_id, datum);


--
-- Name: ux_bank_afletter_opdracht_open; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_afletter_opdracht_open ON boekhouding.bank_afletter_opdracht USING btree (administratie_id, payment_transaction_id) WHERE (status = 'klaargezet'::text);


--
-- Name: ux_bank_boeking_actief_per_mutatie; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_boeking_actief_per_mutatie ON boekhouding.bank_boeking USING btree (administratie_id, payment_transaction_id) WHERE (status = 'geboekt'::text);


--
-- Name: ux_bank_regel_actief_per_tegenpartij; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_regel_actief_per_tegenpartij ON boekhouding.bank_regel USING btree (administratie_id, tegenpartij_sleutel) WHERE actief;


--
-- Name: ux_intake_bericht_message_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_intake_bericht_message_id ON boekhouding.intake_bericht USING btree (message_id) WHERE (message_id IS NOT NULL);


--
-- Name: ux_intake_splitsing_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_intake_splitsing_open_per_document ON boekhouding.intake_splitsing USING btree (bron_document_id) WHERE (status = 'voorgesteld'::text);


--
-- Name: ux_omzet_boeking_actief_per_periode; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_omzet_boeking_actief_per_periode ON boekhouding.omzet_boeking USING btree (administratie_id, periode_start, periode_eind) WHERE (status = ANY (ARRAY['geboekt'::text, 'half_geboekt'::text]));


--
-- Name: ux_omzet_mapping_actief_per_categorie; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_omzet_mapping_actief_per_categorie ON boekhouding.omzet_categorie_mapping USING btree (administratie_id, categorie_sleutel) WHERE actief;


--
-- Name: ux_toewijzing_regel_actief; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_toewijzing_regel_actief ON boekhouding.toewijzing_regel USING btree (soort, sleutel) WHERE actief;


--
-- Name: ux_verkoop_boeking_actief_per_factuurnummer; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_verkoop_boeking_actief_per_factuurnummer ON boekhouding.verkoop_boeking USING btree (administratie_id, factuurnummer, is_creditnota) WHERE (status = 'geboekt'::text);


--
-- Name: vraag_een_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX vraag_een_open_per_document ON boekhouding.vraag USING btree (document_id) WHERE (status = 'open'::text);


--
-- Name: ix_accordeur_nieuw_gemeld_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_accordeur_nieuw_gemeld_gebruiker_id ON platform.accordeur_nieuw_gemeld USING btree (gebruiker_id);


--
-- Name: ix_audit_event_administratie_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_audit_event_administratie_id ON platform.audit_event USING btree (administratie_id);


--
-- Name: ix_audit_event_correlatie_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_audit_event_correlatie_id ON platform.audit_event USING btree (correlatie_id);


--
-- Name: ix_audit_event_tabel_record; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_audit_event_tabel_record ON platform.audit_event USING btree (tabel, record_id);


--
-- Name: ix_audit_event_tijdstip; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_audit_event_tijdstip ON platform.audit_event USING btree (tijdstip);


--
-- Name: ix_detacheerder_koppeling_zzper; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_detacheerder_koppeling_zzper ON platform.detacheerder_koppeling USING btree (zzper_gebruiker_id);


--
-- Name: ix_gebruiker_entiteit_entiteit_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_gebruiker_entiteit_entiteit_id ON platform.gebruiker_entiteit USING btree (entiteit_id);


--
-- Name: ix_grootboekrekening_administratie_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_grootboekrekening_administratie_id ON platform.grootboekrekening USING btree (administratie_id);


--
-- Name: ix_platform_ai_gebruik_maand; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_platform_ai_gebruik_maand ON platform.ai_gebruik USING btree (maand);


--
-- Name: ix_push_subscriptie_apparaat_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_push_subscriptie_apparaat_id ON platform.push_subscriptie USING btree (apparaat_id);


--
-- Name: ix_push_subscriptie_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_push_subscriptie_gebruiker_id ON platform.push_subscriptie USING btree (gebruiker_id);


--
-- Name: ix_refresh_token_apparaat_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_refresh_token_apparaat_id ON platform.refresh_token USING btree (apparaat_id);


--
-- Name: ix_refresh_token_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_refresh_token_gebruiker_id ON platform.refresh_token USING btree (gebruiker_id);


--
-- Name: ix_uitnodiging_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_uitnodiging_gebruiker_id ON platform.uitnodiging USING btree (gebruiker_id);


--
-- Name: ix_webauthn_challenge_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_webauthn_challenge_gebruiker_id ON platform.webauthn_challenge USING btree (gebruiker_id);


--
-- Name: ix_webauthn_credential_gebruiker_id; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_webauthn_credential_gebruiker_id ON platform.webauthn_credential USING btree (gebruiker_id);


--
-- Name: gebruiker_administratie trg_audit_gebruiker_administratie_delete; Type: TRIGGER; Schema: platform; Owner: -
--

CREATE TRIGGER trg_audit_gebruiker_administratie_delete AFTER DELETE ON platform.gebruiker_administratie FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_administratie_wijziging();


--
-- Name: gebruiker_administratie trg_audit_gebruiker_administratie_insert; Type: TRIGGER; Schema: platform; Owner: -
--

CREATE TRIGGER trg_audit_gebruiker_administratie_insert AFTER INSERT ON platform.gebruiker_administratie FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_administratie_wijziging();


--
-- Name: gebruiker_entiteit trg_audit_gebruiker_entiteit; Type: TRIGGER; Schema: platform; Owner: -
--

CREATE TRIGGER trg_audit_gebruiker_entiteit AFTER INSERT OR DELETE ON platform.gebruiker_entiteit FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_entiteit_wijziging();


--
-- Name: gebruiker_module_rol trg_audit_gebruiker_module_rol; Type: TRIGGER; Schema: platform; Owner: -
--

CREATE TRIGGER trg_audit_gebruiker_module_rol AFTER INSERT OR DELETE OR UPDATE ON platform.gebruiker_module_rol FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_module_rol_wijziging();


--
-- Name: gebruiker trg_audit_gebruiker_rol_wijziging; Type: TRIGGER; Schema: platform; Owner: -
--

CREATE TRIGGER trg_audit_gebruiker_rol_wijziging AFTER UPDATE ON platform.gebruiker FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_rol_wijziging();


--
-- Name: accordering_laag accordering_laag_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: accordering_laag accordering_laag_accordeur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_accordeur_gebruiker_id_fkey FOREIGN KEY (accordeur_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: accordering_laag accordering_laag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: accordering_laag accordering_laag_gedeactiveerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_gedeactiveerd_door_fkey FOREIGN KEY (gedeactiveerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: accordering_stap accordering_stap_accordering_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_stap
    ADD CONSTRAINT accordering_stap_accordering_id_fkey FOREIGN KEY (accordering_id) REFERENCES boekhouding.document_accordering(id);


--
-- Name: accordering_stap accordering_stap_accordeur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_stap
    ADD CONSTRAINT accordering_stap_accordeur_gebruiker_id_fkey FOREIGN KEY (accordeur_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: accordering_stap accordering_stap_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_stap
    ADD CONSTRAINT accordering_stap_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: afwijzing afwijzing_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: afwijzing afwijzing_afgewezen_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_afgewezen_door_fkey FOREIGN KEY (afgewezen_door) REFERENCES platform.gebruiker(id);


--
-- Name: afwijzing afwijzing_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: afwijzing afwijzing_heropend_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_heropend_door_fkey FOREIGN KEY (heropend_door) REFERENCES platform.gebruiker(id);


--
-- Name: afwijzing afwijzing_toegewezen_aan_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_toegewezen_aan_fkey FOREIGN KEY (toegewezen_aan) REFERENCES platform.gebruiker(id);


--
-- Name: bank_afletter_opdracht bank_afletter_opdracht_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_afletter_opdracht
    ADD CONSTRAINT bank_afletter_opdracht_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_afletter_opdracht bank_afletter_opdracht_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_afletter_opdracht
    ADD CONSTRAINT bank_afletter_opdracht_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_afletter_opdracht bank_afletter_opdracht_klaargezet_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_afletter_opdracht
    ADD CONSTRAINT bank_afletter_opdracht_klaargezet_door_fkey FOREIGN KEY (klaargezet_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_boeking bank_boeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking
    ADD CONSTRAINT bank_boeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_boeking bank_boeking_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking
    ADD CONSTRAINT bank_boeking_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_boeking bank_boeking_gestorneerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking
    ADD CONSTRAINT bank_boeking_gestorneerd_door_fkey FOREIGN KEY (gestorneerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_boeking_regel bank_boeking_regel_bank_boeking_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_boeking_regel
    ADD CONSTRAINT bank_boeking_regel_bank_boeking_id_fkey FOREIGN KEY (bank_boeking_id) REFERENCES boekhouding.bank_boeking(id);


--
-- Name: bank_mutatie bank_mutatie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_mutatie
    ADD CONSTRAINT bank_mutatie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_regel bank_regel_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_regel
    ADD CONSTRAINT bank_regel_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_regel bank_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_regel
    ADD CONSTRAINT bank_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_regel bank_regel_gedeactiveerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_regel
    ADD CONSTRAINT bank_regel_gedeactiveerd_door_fkey FOREIGN KEY (gedeactiveerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_sync_stand bank_sync_stand_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_sync_stand
    ADD CONSTRAINT bank_sync_stand_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: boeking_observatie boeking_observatie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boeking_observatie
    ADD CONSTRAINT boeking_observatie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: boekvoorstel boekvoorstel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boekvoorstel
    ADD CONSTRAINT boekvoorstel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: boekvoorstel_regel boekvoorstel_regel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boekvoorstel_regel
    ADD CONSTRAINT boekvoorstel_regel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.boekvoorstel(document_id);


--
-- Name: document_accordering document_accordering_aangeboden_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_accordering
    ADD CONSTRAINT document_accordering_aangeboden_door_fkey FOREIGN KEY (aangeboden_door) REFERENCES platform.gebruiker(id);


--
-- Name: document_accordering document_accordering_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_accordering
    ADD CONSTRAINT document_accordering_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: document_accordering document_accordering_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_accordering
    ADD CONSTRAINT document_accordering_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: document document_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: document_gebeurtenis document_gebeurtenis_actor_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_gebeurtenis
    ADD CONSTRAINT document_gebeurtenis_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES platform.gebruiker(id);


--
-- Name: document_gebeurtenis document_gebeurtenis_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_gebeurtenis
    ADD CONSTRAINT document_gebeurtenis_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: document document_gesplitst_uit_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_gesplitst_uit_id_fkey FOREIGN KEY (gesplitst_uit_id) REFERENCES boekhouding.document(id);


--
-- Name: document_herinnering document_herinnering_accordeur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_herinnering
    ADD CONSTRAINT document_herinnering_accordeur_gebruiker_id_fkey FOREIGN KEY (accordeur_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: document_herinnering document_herinnering_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_herinnering
    ADD CONSTRAINT document_herinnering_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: document_herinnering document_herinnering_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_herinnering
    ADD CONSTRAINT document_herinnering_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: document_herinnering document_herinnering_verzonden_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document_herinnering
    ADD CONSTRAINT document_herinnering_verzonden_door_fkey FOREIGN KEY (verzonden_door) REFERENCES platform.gebruiker(id);


--
-- Name: document document_intake_bericht_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_intake_bericht_id_fkey FOREIGN KEY (intake_bericht_id) REFERENCES boekhouding.intake_bericht(id);


--
-- Name: document document_mogelijk_duplicaat_van_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_mogelijk_duplicaat_van_id_fkey FOREIGN KEY (mogelijk_duplicaat_van_id) REFERENCES boekhouding.document(id);


--
-- Name: document document_toegewezen_aan_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_toegewezen_aan_fkey FOREIGN KEY (toegewezen_aan) REFERENCES platform.gebruiker(id);


--
-- Name: document document_toewijzing_suggestie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_toewijzing_suggestie_administratie_id_fkey FOREIGN KEY (toewijzing_suggestie_administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_doel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_doel_administratie_id_fkey FOREIGN KEY (doel_administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_mapping_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_mapping_id_fkey FOREIGN KEY (mapping_id) REFERENCES boekhouding.doorbelasting_mapping(id);


--
-- Name: doorbelasting_boeking doorbelasting_boeking_run_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_boeking
    ADD CONSTRAINT doorbelasting_boeking_run_id_fkey FOREIGN KEY (run_id) REFERENCES boekhouding.doorbelasting_run(id);


--
-- Name: doorbelasting_instelling doorbelasting_instelling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_instelling
    ADD CONSTRAINT doorbelasting_instelling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_mapping doorbelasting_mapping_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_mapping
    ADD CONSTRAINT doorbelasting_mapping_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: doorbelasting_mapping doorbelasting_mapping_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_mapping
    ADD CONSTRAINT doorbelasting_mapping_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_mapping doorbelasting_mapping_doel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_mapping
    ADD CONSTRAINT doorbelasting_mapping_doel_administratie_id_fkey FOREIGN KEY (doel_administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_regel doorbelasting_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_regel doorbelasting_regel_bron_regel_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_bron_regel_id_fkey FOREIGN KEY (bron_regel_id) REFERENCES boekhouding.boekvoorstel_regel(id);


--
-- Name: doorbelasting_regel doorbelasting_regel_mapping_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_mapping_id_fkey FOREIGN KEY (mapping_id) REFERENCES boekhouding.doorbelasting_mapping(id);


--
-- Name: doorbelasting_regel doorbelasting_regel_run_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_regel
    ADD CONSTRAINT doorbelasting_regel_run_id_fkey FOREIGN KEY (run_id) REFERENCES boekhouding.doorbelasting_run(id);


--
-- Name: doorbelasting_run doorbelasting_run_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT doorbelasting_run_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: doorbelasting_run doorbelasting_run_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT doorbelasting_run_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: doorbelasting_run doorbelasting_run_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT doorbelasting_run_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: factuurmatch factuurmatch_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch
    ADD CONSTRAINT factuurmatch_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: factuurmatch factuurmatch_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch
    ADD CONSTRAINT factuurmatch_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: factuurmatch_staat factuurmatch_staat_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch_staat
    ADD CONSTRAINT factuurmatch_staat_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: factuurmatch_staat factuurmatch_staat_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch_staat
    ADD CONSTRAINT factuurmatch_staat_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.factuurmatch(document_id);


--
-- Name: factuurmatch_staat factuurmatch_staat_weekstaat_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch_staat
    ADD CONSTRAINT factuurmatch_staat_weekstaat_id_fkey FOREIGN KEY (weekstaat_id) REFERENCES boekhouding.weekstaat(id);


--
-- Name: factuurmatch factuurmatch_veldwerker_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch
    ADD CONSTRAINT factuurmatch_veldwerker_gebruiker_id_fkey FOREIGN KEY (veldwerker_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: factuurmatch fk_factuurmatch_bevestigd_door; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.factuurmatch
    ADD CONSTRAINT fk_factuurmatch_bevestigd_door FOREIGN KEY (afwijking_bevestigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: leverancier_werknummer fk_leverancier_werknummer_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT fk_leverancier_werknummer_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: meerwerk fk_meerwerk_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT fk_meerwerk_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: planning_toewijzing fk_planning_toewijzing_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.planning_toewijzing
    ADD CONSTRAINT fk_planning_toewijzing_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: project_document fk_project_document_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_document
    ADD CONSTRAINT fk_project_document_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: project_ontleding_regel fk_project_ontleding_regel_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_ontleding_regel
    ADD CONSTRAINT fk_project_ontleding_regel_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: project_specificatie fk_project_specificatie_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_specificatie
    ADD CONSTRAINT fk_project_specificatie_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: project_staffel fk_project_staffel_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_staffel
    ADD CONSTRAINT fk_project_staffel_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: uren_project_toewijzing fk_uren_project_toewijzing_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.uren_project_toewijzing
    ADD CONSTRAINT fk_uren_project_toewijzing_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: weekstaat fk_weekstaat_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT fk_weekstaat_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: weekstaat fk_weekstaat_verrekend_document; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT fk_weekstaat_verrekend_document FOREIGN KEY (verrekend_met_document_id) REFERENCES boekhouding.document(id);


--
-- Name: iban_accordering iban_accordering_aangevraagd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordering
    ADD CONSTRAINT iban_accordering_aangevraagd_door_fkey FOREIGN KEY (aangevraagd_door) REFERENCES platform.gebruiker(id);


--
-- Name: iban_accordering iban_accordering_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordering
    ADD CONSTRAINT iban_accordering_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: iban_accordering iban_accordering_besloten_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordering
    ADD CONSTRAINT iban_accordering_besloten_door_fkey FOREIGN KEY (besloten_door) REFERENCES platform.gebruiker(id);


--
-- Name: iban_accordering iban_accordering_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordering
    ADD CONSTRAINT iban_accordering_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: iban_accordeur iban_accordeur_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordeur
    ADD CONSTRAINT iban_accordeur_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: iban_accordeur iban_accordeur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.iban_accordeur
    ADD CONSTRAINT iban_accordeur_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: intake_bericht intake_bericht_verwerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_bericht
    ADD CONSTRAINT intake_bericht_verwerkt_door_fkey FOREIGN KEY (verwerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: intake_splitsing intake_splitsing_besloten_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing
    ADD CONSTRAINT intake_splitsing_besloten_door_fkey FOREIGN KEY (besloten_door) REFERENCES platform.gebruiker(id);


--
-- Name: intake_splitsing intake_splitsing_bron_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing
    ADD CONSTRAINT intake_splitsing_bron_document_id_fkey FOREIGN KEY (bron_document_id) REFERENCES boekhouding.document(id);


--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intercompany_tegenpartij
    ADD CONSTRAINT intercompany_tegenpartij_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_iban leverancier_iban_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_iban
    ADD CONSTRAINT leverancier_iban_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_iban leverancier_iban_bevestigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_iban
    ADD CONSTRAINT leverancier_iban_bevestigd_door_fkey FOREIGN KEY (bevestigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: leverancier_voorkeur leverancier_voorkeur_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_voorkeur
    ADD CONSTRAINT leverancier_voorkeur_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_werknummer leverancier_werknummer_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT leverancier_werknummer_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: leverancier_werknummer leverancier_werknummer_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT leverancier_werknummer_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_werknummer leverancier_werknummer_bevestigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT leverancier_werknummer_bevestigd_door_fkey FOREIGN KEY (bevestigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: meerwerk meerwerk_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: meerwerk meerwerk_beoordeeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_beoordeeld_door_fkey FOREIGN KEY (beoordeeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: meerwerk meerwerk_gemeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_gemeld_door_fkey FOREIGN KEY (gemeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: meerwerk meerwerk_vraag_gesteld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_vraag_gesteld_door_fkey FOREIGN KEY (vraag_gesteld_door) REFERENCES platform.gebruiker(id);


--
-- Name: omzet_boeking omzet_boeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_boeking
    ADD CONSTRAINT omzet_boeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: omzet_boeking omzet_boeking_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_boeking
    ADD CONSTRAINT omzet_boeking_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: omzet_boeking omzet_boeking_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_boeking
    ADD CONSTRAINT omzet_boeking_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: omzet_boeking omzet_boeking_gestorneerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_boeking
    ADD CONSTRAINT omzet_boeking_gestorneerd_door_fkey FOREIGN KEY (gestorneerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: omzet_categorie_mapping omzet_categorie_mapping_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_categorie_mapping
    ADD CONSTRAINT omzet_categorie_mapping_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: omzet_categorie_mapping omzet_categorie_mapping_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_categorie_mapping
    ADD CONSTRAINT omzet_categorie_mapping_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: omzet_categorie_mapping omzet_categorie_mapping_gedeactiveerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_categorie_mapping
    ADD CONSTRAINT omzet_categorie_mapping_gedeactiveerd_door_fkey FOREIGN KEY (gedeactiveerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: omzet_instelling omzet_instelling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_instelling
    ADD CONSTRAINT omzet_instelling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: omzet_voorstel omzet_voorstel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_voorstel
    ADD CONSTRAINT omzet_voorstel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: omzet_voorstel_regel omzet_voorstel_regel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.omzet_voorstel_regel
    ADD CONSTRAINT omzet_voorstel_regel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.omzet_voorstel(document_id);


--
-- Name: payment_account_cache payment_account_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.payment_account_cache
    ADD CONSTRAINT payment_account_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: payment_item_cache payment_item_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.payment_item_cache
    ADD CONSTRAINT payment_item_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: planning_toewijzing planning_toewijzing_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.planning_toewijzing
    ADD CONSTRAINT planning_toewijzing_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: planning_toewijzing planning_toewijzing_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.planning_toewijzing
    ADD CONSTRAINT planning_toewijzing_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: planning_toewijzing planning_toewijzing_toegevoegd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.planning_toewijzing
    ADD CONSTRAINT planning_toewijzing_toegevoegd_door_fkey FOREIGN KEY (toegevoegd_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_cache project_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_cache
    ADD CONSTRAINT project_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_cijfers_sync_run project_cijfers_sync_run_aangevraagd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_cijfers_sync_run
    ADD CONSTRAINT project_cijfers_sync_run_aangevraagd_door_fkey FOREIGN KEY (aangevraagd_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_cijfers_sync_run project_cijfers_sync_run_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_cijfers_sync_run
    ADD CONSTRAINT project_cijfers_sync_run_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_document project_document_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_document
    ADD CONSTRAINT project_document_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_document project_document_geupload_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_document
    ADD CONSTRAINT project_document_geupload_door_fkey FOREIGN KEY (geupload_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_ontleding_regel project_ontleding_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_ontleding_regel
    ADD CONSTRAINT project_ontleding_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_ontleding_regel project_ontleding_regel_beslist_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_ontleding_regel
    ADD CONSTRAINT project_ontleding_regel_beslist_door_fkey FOREIGN KEY (beslist_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_ontleding_regel project_ontleding_regel_project_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_ontleding_regel
    ADD CONSTRAINT project_ontleding_regel_project_document_id_fkey FOREIGN KEY (project_document_id) REFERENCES boekhouding.project_document(id);


--
-- Name: project_regel_cache project_regel_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_regel_cache
    ADD CONSTRAINT project_regel_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_specificatie project_specificatie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_specificatie
    ADD CONSTRAINT project_specificatie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_specificatie project_specificatie_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_specificatie
    ADD CONSTRAINT project_specificatie_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_staffel project_staffel_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_staffel
    ADD CONSTRAINT project_staffel_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_staffel project_staffel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_staffel
    ADD CONSTRAINT project_staffel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: projectaanvraag projectaanvraag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectaanvraag
    ADD CONSTRAINT projectaanvraag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie
    ADD CONSTRAINT reconciliatie_acceptatie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_geaccepteerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie
    ADD CONSTRAINT reconciliatie_acceptatie_geaccepteerd_door_fkey FOREIGN KEY (geaccepteerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie
    ADD CONSTRAINT reconciliatie_acceptatie_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


--
-- Name: staande_goedkeuring staande_goedkeuring_accordeur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_accordeur_gebruiker_id_fkey FOREIGN KEY (accordeur_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: staande_goedkeuring staande_goedkeuring_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: staande_goedkeuring staande_goedkeuring_bron_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_bron_document_id_fkey FOREIGN KEY (bron_document_id) REFERENCES boekhouding.document(id);


--
-- Name: staande_goedkeuring staande_goedkeuring_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


--
-- Name: taxrate_cache taxrate_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.taxrate_cache
    ADD CONSTRAINT taxrate_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: tegenboeking tegenboeking_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.tegenboeking
    ADD CONSTRAINT tegenboeking_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: tegenboeking tegenboeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.tegenboeking
    ADD CONSTRAINT tegenboeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: tegenboeking tegenboeking_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.tegenboeking
    ADD CONSTRAINT tegenboeking_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: toewijzing_regel toewijzing_regel_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.toewijzing_regel
    ADD CONSTRAINT toewijzing_regel_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: toewijzing_regel toewijzing_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.toewijzing_regel
    ADD CONSTRAINT toewijzing_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: toewijzing_regel toewijzing_regel_gedeactiveerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.toewijzing_regel
    ADD CONSTRAINT toewijzing_regel_gedeactiveerd_door_fkey FOREIGN KEY (gedeactiveerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: uren_project_toewijzing uren_project_toewijzing_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.uren_project_toewijzing
    ADD CONSTRAINT uren_project_toewijzing_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: uren_project_toewijzing uren_project_toewijzing_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.uren_project_toewijzing
    ADD CONSTRAINT uren_project_toewijzing_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: uren_project_toewijzing uren_project_toewijzing_toegevoegd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.uren_project_toewijzing
    ADD CONSTRAINT uren_project_toewijzing_toegevoegd_door_fkey FOREIGN KEY (toegevoegd_door) REFERENCES platform.gebruiker(id);


--
-- Name: veldwerker_crediteur veldwerker_crediteur_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_crediteur
    ADD CONSTRAINT veldwerker_crediteur_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: veldwerker_crediteur veldwerker_crediteur_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_crediteur
    ADD CONSTRAINT veldwerker_crediteur_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: veldwerker_crediteur veldwerker_crediteur_gekoppeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_crediteur
    ADD CONSTRAINT veldwerker_crediteur_gekoppeld_door_fkey FOREIGN KEY (gekoppeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: vendor_cache vendor_cache_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vendor_cache
    ADD CONSTRAINT vendor_cache_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: verkoop_boeking verkoop_boeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_boeking
    ADD CONSTRAINT verkoop_boeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: verkoop_boeking verkoop_boeking_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_boeking
    ADD CONSTRAINT verkoop_boeking_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: verkoop_boeking verkoop_boeking_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_boeking
    ADD CONSTRAINT verkoop_boeking_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: verkoop_boeking verkoop_boeking_gestorneerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_boeking
    ADD CONSTRAINT verkoop_boeking_gestorneerd_door_fkey FOREIGN KEY (gestorneerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: verkoop_btw_voorkeur verkoop_btw_voorkeur_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_btw_voorkeur
    ADD CONSTRAINT verkoop_btw_voorkeur_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: verkoop_voorstel verkoop_voorstel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_voorstel
    ADD CONSTRAINT verkoop_voorstel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: verkoop_voorstel_regel verkoop_voorstel_regel_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.verkoop_voorstel_regel
    ADD CONSTRAINT verkoop_voorstel_regel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.verkoop_voorstel(document_id);


--
-- Name: vraag vraag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: vraag vraag_beantwoord_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_beantwoord_door_fkey FOREIGN KEY (beantwoord_door) REFERENCES platform.gebruiker(id);


--
-- Name: vraag vraag_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: vraag vraag_gesteld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_gesteld_door_fkey FOREIGN KEY (gesteld_door) REFERENCES platform.gebruiker(id);


--
-- Name: vraag vraag_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


--
-- Name: vraag vraag_toegewezen_aan_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_toegewezen_aan_fkey FOREIGN KEY (toegewezen_aan) REFERENCES platform.gebruiker(id);


--
-- Name: waarborg_bericht waarborg_bericht_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.waarborg_bericht
    ADD CONSTRAINT waarborg_bericht_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: waarborg_bericht waarborg_bericht_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.waarborg_bericht
    ADD CONSTRAINT waarborg_bericht_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: waarborg_bericht waarborg_bericht_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.waarborg_bericht
    ADD CONSTRAINT waarborg_bericht_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: webhook_uitgaand webhook_uitgaand_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.webhook_uitgaand
    ADD CONSTRAINT webhook_uitgaand_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: webhook_uitgaand webhook_uitgaand_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.webhook_uitgaand
    ADD CONSTRAINT webhook_uitgaand_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: weekstaat weekstaat_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: weekstaat weekstaat_afgekeurd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_afgekeurd_door_fkey FOREIGN KEY (afgekeurd_door) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat_correctie weekstaat_correctie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_correctie
    ADD CONSTRAINT weekstaat_correctie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: weekstaat_correctie weekstaat_correctie_afgekeurd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_correctie
    ADD CONSTRAINT weekstaat_correctie_afgekeurd_door_fkey FOREIGN KEY (afgekeurd_door) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat_correctie weekstaat_correctie_weekstaat_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_correctie
    ADD CONSTRAINT weekstaat_correctie_weekstaat_id_fkey FOREIGN KEY (weekstaat_id) REFERENCES boekhouding.weekstaat(id);


--
-- Name: weekstaat_correctie weekstaat_correctie_zzper_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_correctie
    ADD CONSTRAINT weekstaat_correctie_zzper_gebruiker_id_fkey FOREIGN KEY (zzper_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat_dag weekstaat_dag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_dag
    ADD CONSTRAINT weekstaat_dag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: weekstaat_dag weekstaat_dag_ingevuld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_dag
    ADD CONSTRAINT weekstaat_dag_ingevuld_door_fkey FOREIGN KEY (ingevuld_door) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat_dag weekstaat_dag_weekstaat_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat_dag
    ADD CONSTRAINT weekstaat_dag_weekstaat_id_fkey FOREIGN KEY (weekstaat_id) REFERENCES boekhouding.weekstaat(id);


--
-- Name: weekstaat weekstaat_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat weekstaat_goedgekeurd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_goedgekeurd_door_fkey FOREIGN KEY (goedgekeurd_door) REFERENCES platform.gebruiker(id);


--
-- Name: weekstaat weekstaat_ingediend_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.weekstaat
    ADD CONSTRAINT weekstaat_ingediend_door_fkey FOREIGN KEY (ingediend_door) REFERENCES platform.gebruiker(id);


--
-- Name: accordeur_akkoord accordeur_akkoord_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_akkoord
    ADD CONSTRAINT accordeur_akkoord_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: accordeur_herinnering accordeur_herinnering_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_herinnering
    ADD CONSTRAINT accordeur_herinnering_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: accordeur_nieuw_gemeld accordeur_nieuw_gemeld_document_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_nieuw_gemeld
    ADD CONSTRAINT accordeur_nieuw_gemeld_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: accordeur_nieuw_gemeld accordeur_nieuw_gemeld_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.accordeur_nieuw_gemeld
    ADD CONSTRAINT accordeur_nieuw_gemeld_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: administratie administratie_eigenaar_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.administratie
    ADD CONSTRAINT administratie_eigenaar_gebruiker_id_fkey FOREIGN KEY (eigenaar_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: administratie administratie_reconciliatie_uitgesloten_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.administratie
    ADD CONSTRAINT administratie_reconciliatie_uitgesloten_door_fkey FOREIGN KEY (reconciliatie_uitgesloten_door) REFERENCES platform.gebruiker(id);


--
-- Name: ai_kosten_instelling ai_kosten_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.ai_kosten_instelling
    ADD CONSTRAINT ai_kosten_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: audit_event audit_event_actor_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.audit_event
    ADD CONSTRAINT audit_event_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES platform.gebruiker(id);


--
-- Name: audit_event audit_event_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.audit_event
    ADD CONSTRAINT audit_event_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: boeken_instelling boeken_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.boeken_instelling
    ADD CONSTRAINT boeken_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: detacheerder_koppeling detacheerder_koppeling_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.detacheerder_koppeling
    ADD CONSTRAINT detacheerder_koppeling_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: detacheerder_koppeling detacheerder_koppeling_detacheerder_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.detacheerder_koppeling
    ADD CONSTRAINT detacheerder_koppeling_detacheerder_gebruiker_id_fkey FOREIGN KEY (detacheerder_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: detacheerder_koppeling detacheerder_koppeling_zzper_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.detacheerder_koppeling
    ADD CONSTRAINT detacheerder_koppeling_zzper_gebruiker_id_fkey FOREIGN KEY (zzper_gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: gebruiker_administratie gebruiker_administratie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_administratie
    ADD CONSTRAINT gebruiker_administratie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: gebruiker_administratie gebruiker_administratie_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_administratie
    ADD CONSTRAINT gebruiker_administratie_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: gebruiker_entiteit gebruiker_entiteit_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_entiteit
    ADD CONSTRAINT gebruiker_entiteit_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: gebruiker gebruiker_geblokkeerd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker
    ADD CONSTRAINT gebruiker_geblokkeerd_door_fkey FOREIGN KEY (geblokkeerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: gebruiker_module_rol gebruiker_module_rol_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker_module_rol
    ADD CONSTRAINT gebruiker_module_rol_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: grootboekrekening grootboekrekening_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.grootboekrekening
    ADD CONSTRAINT grootboekrekening_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: intake_instelling intake_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.intake_instelling
    ADD CONSTRAINT intake_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: push_subscriptie push_subscriptie_apparaat_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.push_subscriptie
    ADD CONSTRAINT push_subscriptie_apparaat_id_fkey FOREIGN KEY (apparaat_id) REFERENCES platform.webauthn_credential(id);


--
-- Name: push_subscriptie push_subscriptie_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.push_subscriptie
    ADD CONSTRAINT push_subscriptie_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: refresh_token refresh_token_apparaat_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.refresh_token
    ADD CONSTRAINT refresh_token_apparaat_id_fkey FOREIGN KEY (apparaat_id) REFERENCES platform.webauthn_credential(id);


--
-- Name: refresh_token refresh_token_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.refresh_token
    ADD CONSTRAINT refresh_token_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: refresh_token refresh_token_voorganger_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.refresh_token
    ADD CONSTRAINT refresh_token_voorganger_id_fkey FOREIGN KEY (voorganger_id) REFERENCES platform.refresh_token(id);


--
-- Name: rlz_credential rlz_credential_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_credential
    ADD CONSTRAINT rlz_credential_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: rlz_credential rlz_credential_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_credential
    ADD CONSTRAINT rlz_credential_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: rlz_rechten_probe rlz_rechten_probe_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_rechten_probe
    ADD CONSTRAINT rlz_rechten_probe_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: rlz_rechten_probe rlz_rechten_probe_uitgevoerd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.rlz_rechten_probe
    ADD CONSTRAINT rlz_rechten_probe_uitgevoerd_door_fkey FOREIGN KEY (uitgevoerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: totp_secret totp_secret_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.totp_secret
    ADD CONSTRAINT totp_secret_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: uitnodiging uitnodiging_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.uitnodiging
    ADD CONSTRAINT uitnodiging_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: uitnodiging uitnodiging_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.uitnodiging
    ADD CONSTRAINT uitnodiging_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: webauthn_challenge webauthn_challenge_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_challenge
    ADD CONSTRAINT webauthn_challenge_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: webauthn_credential webauthn_credential_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_credential
    ADD CONSTRAINT webauthn_credential_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: webauthn_credential webauthn_credential_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webauthn_credential
    ADD CONSTRAINT webauthn_credential_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


--
-- Name: webhook_instelling webhook_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.webhook_instelling
    ADD CONSTRAINT webhook_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: accordering_laag; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.accordering_laag ENABLE ROW LEVEL SECURITY;

--
-- Name: accordering_laag accordering_laag_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY accordering_laag_scope ON boekhouding.accordering_laag USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: accordering_stap; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.accordering_stap ENABLE ROW LEVEL SECURITY;

--
-- Name: accordering_stap accordering_stap_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY accordering_stap_scope ON boekhouding.accordering_stap USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: afwijzing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.afwijzing ENABLE ROW LEVEL SECURITY;

--
-- Name: afwijzing afwijzing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY afwijzing_scope ON boekhouding.afwijzing USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_afletter_opdracht; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_afletter_opdracht ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_afletter_opdracht bank_afletter_opdracht_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_afletter_opdracht_scope ON boekhouding.bank_afletter_opdracht USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_boeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_boeking ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_boeking_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_boeking_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_boeking_regel bank_boeking_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_boeking_regel_scope ON boekhouding.bank_boeking_regel USING ((EXISTS ( SELECT 1
   FROM boekhouding.bank_boeking b
  WHERE ((b.id = bank_boeking_regel.bank_boeking_id) AND (b.administratie_id = platform.current_administratie_id()))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.bank_boeking b
  WHERE ((b.id = bank_boeking_regel.bank_boeking_id) AND (b.administratie_id = platform.current_administratie_id())))));


--
-- Name: bank_boeking bank_boeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_boeking_scope ON boekhouding.bank_boeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_mutatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_mutatie ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_mutatie bank_mutatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_mutatie_scope ON boekhouding.bank_mutatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_regel bank_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_regel_scope ON boekhouding.bank_regel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_sync_stand; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_sync_stand ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_sync_stand bank_sync_stand_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_sync_stand_scope ON boekhouding.bank_sync_stand USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: boeking_observatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.boeking_observatie ENABLE ROW LEVEL SECURITY;

--
-- Name: boeking_observatie boeking_observatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY boeking_observatie_scope ON boekhouding.boeking_observatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: boekvoorstel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.boekvoorstel ENABLE ROW LEVEL SECURITY;

--
-- Name: boekvoorstel_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.boekvoorstel_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: boekvoorstel_regel boekvoorstel_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY boekvoorstel_regel_scope ON boekhouding.boekvoorstel_regel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = boekvoorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = boekvoorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: boekvoorstel boekvoorstel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY boekvoorstel_scope ON boekhouding.boekvoorstel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = boekvoorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = boekvoorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: document; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.document ENABLE ROW LEVEL SECURITY;

--
-- Name: document_accordering; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.document_accordering ENABLE ROW LEVEL SECURITY;

--
-- Name: document_accordering document_accordering_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY document_accordering_scope ON boekhouding.document_accordering USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: document document_administratie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY document_administratie_scope ON boekhouding.document USING (((administratie_id IS NULL) OR (administratie_id = platform.current_administratie_id()))) WITH CHECK (((administratie_id IS NULL) OR (administratie_id = platform.current_administratie_id())));


--
-- Name: document_gebeurtenis; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.document_gebeurtenis ENABLE ROW LEVEL SECURITY;

--
-- Name: document_gebeurtenis document_gebeurtenis_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY document_gebeurtenis_scope ON boekhouding.document_gebeurtenis USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = document_gebeurtenis.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = document_gebeurtenis.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: document_herinnering; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.document_herinnering ENABLE ROW LEVEL SECURITY;

--
-- Name: document_herinnering document_herinnering_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY document_herinnering_scope ON boekhouding.document_herinnering USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: doorbelasting_boeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_boeking ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_boeking doorbelasting_boeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_boeking_scope ON boekhouding.doorbelasting_boeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: doorbelasting_instelling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_instelling ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_instelling doorbelasting_instelling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_instelling_scope ON boekhouding.doorbelasting_instelling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: doorbelasting_mapping; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_mapping ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_mapping doorbelasting_mapping_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_mapping_scope ON boekhouding.doorbelasting_mapping USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: doorbelasting_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_regel doorbelasting_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_regel_scope ON boekhouding.doorbelasting_regel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: doorbelasting_run; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_run ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_run doorbelasting_run_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_run_scope ON boekhouding.doorbelasting_run USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: factuurmatch; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.factuurmatch ENABLE ROW LEVEL SECURITY;

--
-- Name: factuurmatch factuurmatch_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY factuurmatch_scope ON boekhouding.factuurmatch USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: factuurmatch_staat; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.factuurmatch_staat ENABLE ROW LEVEL SECURITY;

--
-- Name: factuurmatch_staat factuurmatch_staat_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY factuurmatch_staat_scope ON boekhouding.factuurmatch_staat USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: iban_accordering; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.iban_accordering ENABLE ROW LEVEL SECURITY;

--
-- Name: iban_accordering iban_accordering_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY iban_accordering_scope ON boekhouding.iban_accordering USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: iban_accordeur; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.iban_accordeur ENABLE ROW LEVEL SECURITY;

--
-- Name: iban_accordeur iban_accordeur_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY iban_accordeur_scope ON boekhouding.iban_accordeur USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: intake_bericht; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.intake_bericht ENABLE ROW LEVEL SECURITY;

--
-- Name: intake_bericht intake_bericht_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY intake_bericht_scope ON boekhouding.intake_bericht USING (true) WITH CHECK (true);


--
-- Name: intake_splitsing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.intake_splitsing ENABLE ROW LEVEL SECURITY;

--
-- Name: intake_splitsing intake_splitsing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY intake_splitsing_scope ON boekhouding.intake_splitsing USING (true) WITH CHECK (true);


--
-- Name: intercompany_tegenpartij; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.intercompany_tegenpartij ENABLE ROW LEVEL SECURITY;

--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY intercompany_tegenpartij_scope ON boekhouding.intercompany_tegenpartij USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: leverancier_iban; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.leverancier_iban ENABLE ROW LEVEL SECURITY;

--
-- Name: leverancier_iban leverancier_iban_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY leverancier_iban_scope ON boekhouding.leverancier_iban USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: leverancier_voorkeur; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.leverancier_voorkeur ENABLE ROW LEVEL SECURITY;

--
-- Name: leverancier_voorkeur leverancier_voorkeur_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY leverancier_voorkeur_scope ON boekhouding.leverancier_voorkeur USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: leverancier_werknummer; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.leverancier_werknummer ENABLE ROW LEVEL SECURITY;

--
-- Name: leverancier_werknummer leverancier_werknummer_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY leverancier_werknummer_scope ON boekhouding.leverancier_werknummer USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: meerwerk; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.meerwerk ENABLE ROW LEVEL SECURITY;

--
-- Name: meerwerk meerwerk_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY meerwerk_scope ON boekhouding.meerwerk USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: omzet_boeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.omzet_boeking ENABLE ROW LEVEL SECURITY;

--
-- Name: omzet_boeking omzet_boeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY omzet_boeking_scope ON boekhouding.omzet_boeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: omzet_categorie_mapping; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.omzet_categorie_mapping ENABLE ROW LEVEL SECURITY;

--
-- Name: omzet_categorie_mapping omzet_categorie_mapping_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY omzet_categorie_mapping_scope ON boekhouding.omzet_categorie_mapping USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: omzet_instelling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.omzet_instelling ENABLE ROW LEVEL SECURITY;

--
-- Name: omzet_instelling omzet_instelling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY omzet_instelling_scope ON boekhouding.omzet_instelling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: omzet_voorstel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.omzet_voorstel ENABLE ROW LEVEL SECURITY;

--
-- Name: omzet_voorstel_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.omzet_voorstel_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: omzet_voorstel_regel omzet_voorstel_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY omzet_voorstel_regel_scope ON boekhouding.omzet_voorstel_regel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = omzet_voorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = omzet_voorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: omzet_voorstel omzet_voorstel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY omzet_voorstel_scope ON boekhouding.omzet_voorstel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = omzet_voorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = omzet_voorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: payment_account_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.payment_account_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: payment_account_cache payment_account_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY payment_account_cache_scope ON boekhouding.payment_account_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: payment_item_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.payment_item_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: payment_item_cache payment_item_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY payment_item_cache_scope ON boekhouding.payment_item_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: planning_toewijzing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.planning_toewijzing ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_toewijzing planning_toewijzing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY planning_toewijzing_scope ON boekhouding.planning_toewijzing USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: project_cache project_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_cache_scope ON boekhouding.project_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_cijfers_sync_run; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_cijfers_sync_run ENABLE ROW LEVEL SECURITY;

--
-- Name: project_cijfers_sync_run project_cijfers_sync_run_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_cijfers_sync_run_scope ON boekhouding.project_cijfers_sync_run USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_document; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_document ENABLE ROW LEVEL SECURITY;

--
-- Name: project_document project_document_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_document_scope ON boekhouding.project_document USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_ontleding_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_ontleding_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: project_ontleding_regel project_ontleding_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_ontleding_regel_scope ON boekhouding.project_ontleding_regel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_regel_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_regel_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: project_regel_cache project_regel_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_regel_cache_scope ON boekhouding.project_regel_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_specificatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_specificatie ENABLE ROW LEVEL SECURITY;

--
-- Name: project_specificatie project_specificatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_specificatie_scope ON boekhouding.project_specificatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: project_staffel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_staffel ENABLE ROW LEVEL SECURITY;

--
-- Name: project_staffel project_staffel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_staffel_scope ON boekhouding.project_staffel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: projectaanvraag; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.projectaanvraag ENABLE ROW LEVEL SECURITY;

--
-- Name: projectaanvraag projectaanvraag_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY projectaanvraag_scope ON boekhouding.projectaanvraag USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: reconciliatie_acceptatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.reconciliatie_acceptatie ENABLE ROW LEVEL SECURITY;

--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY reconciliatie_acceptatie_scope ON boekhouding.reconciliatie_acceptatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: staande_goedkeuring; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.staande_goedkeuring ENABLE ROW LEVEL SECURITY;

--
-- Name: staande_goedkeuring staande_goedkeuring_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY staande_goedkeuring_scope ON boekhouding.staande_goedkeuring USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: taxrate_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.taxrate_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: taxrate_cache taxrate_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY taxrate_cache_scope ON boekhouding.taxrate_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: tegenboeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.tegenboeking ENABLE ROW LEVEL SECURITY;

--
-- Name: tegenboeking tegenboeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY tegenboeking_scope ON boekhouding.tegenboeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: toewijzing_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.toewijzing_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: toewijzing_regel toewijzing_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY toewijzing_regel_scope ON boekhouding.toewijzing_regel USING (true) WITH CHECK (true);


--
-- Name: uren_project_toewijzing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.uren_project_toewijzing ENABLE ROW LEVEL SECURITY;

--
-- Name: uren_project_toewijzing uren_project_toewijzing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY uren_project_toewijzing_scope ON boekhouding.uren_project_toewijzing USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: veldwerker_crediteur; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.veldwerker_crediteur ENABLE ROW LEVEL SECURITY;

--
-- Name: veldwerker_crediteur veldwerker_crediteur_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY veldwerker_crediteur_scope ON boekhouding.veldwerker_crediteur USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: vendor_cache; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.vendor_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: vendor_cache vendor_cache_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY vendor_cache_scope ON boekhouding.vendor_cache USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: verkoop_boeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.verkoop_boeking ENABLE ROW LEVEL SECURITY;

--
-- Name: verkoop_boeking verkoop_boeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY verkoop_boeking_scope ON boekhouding.verkoop_boeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: verkoop_btw_voorkeur; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.verkoop_btw_voorkeur ENABLE ROW LEVEL SECURITY;

--
-- Name: verkoop_btw_voorkeur verkoop_btw_voorkeur_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY verkoop_btw_voorkeur_scope ON boekhouding.verkoop_btw_voorkeur USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: verkoop_voorstel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.verkoop_voorstel ENABLE ROW LEVEL SECURITY;

--
-- Name: verkoop_voorstel_regel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.verkoop_voorstel_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: verkoop_voorstel_regel verkoop_voorstel_regel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY verkoop_voorstel_regel_scope ON boekhouding.verkoop_voorstel_regel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = verkoop_voorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = verkoop_voorstel_regel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: verkoop_voorstel verkoop_voorstel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY verkoop_voorstel_scope ON boekhouding.verkoop_voorstel USING ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = verkoop_voorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = verkoop_voorstel.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))));


--
-- Name: vraag; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.vraag ENABLE ROW LEVEL SECURITY;

--
-- Name: vraag vraag_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY vraag_scope ON boekhouding.vraag USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: waarborg_bericht; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.waarborg_bericht ENABLE ROW LEVEL SECURITY;

--
-- Name: waarborg_bericht waarborg_bericht_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY waarborg_bericht_scope ON boekhouding.waarborg_bericht USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: webhook_uitgaand; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.webhook_uitgaand ENABLE ROW LEVEL SECURITY;

--
-- Name: webhook_uitgaand webhook_uitgaand_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY webhook_uitgaand_scope ON boekhouding.webhook_uitgaand USING ((((administratie_id IS NOT NULL) AND (administratie_id = platform.current_administratie_id())) OR (EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = webhook_uitgaand.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id()))))))) WITH CHECK ((((administratie_id IS NOT NULL) AND (administratie_id = platform.current_administratie_id())) OR (EXISTS ( SELECT 1
   FROM boekhouding.document d
  WHERE ((d.id = webhook_uitgaand.document_id) AND ((d.administratie_id IS NULL) OR (d.administratie_id = platform.current_administratie_id())))))));


--
-- Name: weekstaat; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.weekstaat ENABLE ROW LEVEL SECURITY;

--
-- Name: weekstaat_correctie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.weekstaat_correctie ENABLE ROW LEVEL SECURITY;

--
-- Name: weekstaat_correctie weekstaat_correctie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY weekstaat_correctie_scope ON boekhouding.weekstaat_correctie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: weekstaat_dag; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.weekstaat_dag ENABLE ROW LEVEL SECURITY;

--
-- Name: weekstaat_dag weekstaat_dag_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY weekstaat_dag_scope ON boekhouding.weekstaat_dag USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: weekstaat weekstaat_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY weekstaat_scope ON boekhouding.weekstaat USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: audit_event; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.audit_event ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_event audit_event_administratie_scope; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY audit_event_administratie_scope ON platform.audit_event USING (((administratie_id IS NULL) OR (administratie_id = platform.current_administratie_id()))) WITH CHECK (((administratie_id IS NULL) OR (administratie_id = platform.current_administratie_id())));


--
-- Name: detacheerder_koppeling; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.detacheerder_koppeling ENABLE ROW LEVEL SECURITY;

--
-- Name: detacheerder_koppeling detacheerder_koppeling_lees; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY detacheerder_koppeling_lees ON platform.detacheerder_koppeling FOR SELECT USING (((detacheerder_gebruiker_id = platform.current_actor_id()) OR platform.current_actor_is_beheerder() OR (platform.current_actor_id() = '00000000-0000-0000-0000-000000000001'::uuid)));


--
-- Name: detacheerder_koppeling detacheerder_koppeling_muteren; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY detacheerder_koppeling_muteren ON platform.detacheerder_koppeling FOR UPDATE USING (platform.current_actor_is_beheerder()) WITH CHECK (platform.current_actor_is_beheerder());


--
-- Name: detacheerder_koppeling detacheerder_koppeling_toevoegen; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY detacheerder_koppeling_toevoegen ON platform.detacheerder_koppeling FOR INSERT WITH CHECK (platform.current_actor_is_beheerder());


--
-- Name: detacheerder_koppeling detacheerder_koppeling_verwijderen; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY detacheerder_koppeling_verwijderen ON platform.detacheerder_koppeling FOR DELETE USING (platform.current_actor_is_beheerder());


--
-- Name: gebruiker_administratie; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.gebruiker_administratie ENABLE ROW LEVEL SECURITY;

--
-- Name: gebruiker_administratie gebruiker_administratie_scope; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_administratie_scope ON platform.gebruiker_administratie USING (((administratie_id = platform.current_administratie_id()) OR platform.current_actor_is_beheerder() OR (gebruiker_id = platform.current_actor_id()))) WITH CHECK (((administratie_id = platform.current_administratie_id()) OR platform.current_actor_is_beheerder()));


--
-- Name: gebruiker_entiteit; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.gebruiker_entiteit ENABLE ROW LEVEL SECURITY;

--
-- Name: gebruiker_entiteit gebruiker_entiteit_delete; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_entiteit_delete ON platform.gebruiker_entiteit FOR DELETE USING ((platform.actor_is_module_beheerder('vastgoed'::text) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id())));


--
-- Name: gebruiker_entiteit gebruiker_entiteit_insert; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_entiteit_insert ON platform.gebruiker_entiteit FOR INSERT WITH CHECK ((platform.actor_is_module_beheerder('vastgoed'::text) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id())));


--
-- Name: gebruiker_entiteit gebruiker_entiteit_lees; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_entiteit_lees ON platform.gebruiker_entiteit FOR SELECT USING (((gebruiker_id = platform.current_actor_id()) OR platform.actor_is_module_beheerder('vastgoed'::text)));


--
-- Name: gebruiker_module_rol; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.gebruiker_module_rol ENABLE ROW LEVEL SECURITY;

--
-- Name: gebruiker_module_rol gebruiker_module_rol_delete; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_module_rol_delete ON platform.gebruiker_module_rol FOR DELETE USING ((platform.actor_is_module_beheerder(module) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id())));


--
-- Name: gebruiker_module_rol gebruiker_module_rol_insert; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_module_rol_insert ON platform.gebruiker_module_rol FOR INSERT WITH CHECK ((platform.actor_is_module_beheerder(module) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id())));


--
-- Name: gebruiker_module_rol gebruiker_module_rol_lees; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_module_rol_lees ON platform.gebruiker_module_rol FOR SELECT USING (((gebruiker_id = platform.current_actor_id()) OR platform.actor_is_module_beheerder(module)));


--
-- Name: gebruiker_module_rol gebruiker_module_rol_update; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY gebruiker_module_rol_update ON platform.gebruiker_module_rol FOR UPDATE USING ((platform.actor_is_module_beheerder(module) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id()))) WITH CHECK ((platform.actor_is_module_beheerder(module) AND (gebruiker_id IS DISTINCT FROM platform.current_actor_id())));


--
-- Name: grootboekrekening; Type: ROW SECURITY; Schema: platform; Owner: -
--

ALTER TABLE platform.grootboekrekening ENABLE ROW LEVEL SECURITY;

--
-- Name: grootboekrekening grootboekrekening_scope; Type: POLICY; Schema: platform; Owner: -
--

CREATE POLICY grootboekrekening_scope ON platform.grootboekrekening USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- PostgreSQL database dump complete
--


