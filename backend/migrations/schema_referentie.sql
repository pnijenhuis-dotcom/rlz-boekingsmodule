-- =============================================================================
-- GEGENEREERD BESTAND — NIET MET DE HAND BEWERKEN.
-- Alembic (backend/migrations/versions/) is de bron van waarheid voor het schema;
-- dit bestand is een referentie-dump voor leesbaarheid en code-review.
-- Regenereren: scripts/dump_schema.sh (pg_dump --schema-only boekhouding_test @ head).
-- Migratie-head bij deze dump: 0109
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
-- Name: mi; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA mi;


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
    'samengevoegd',
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
    'wacht_op_passkey',
    'gearchiveerd'
);


--
-- Name: verplaats_document(uuid, uuid, uuid); Type: FUNCTION; Schema: boekhouding; Owner: -
--

CREATE FUNCTION boekhouding.verplaats_document(p_document_id uuid, p_van uuid, p_naar uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
DECLARE
    v_status text;
BEGIN
    IF p_van IS NULL OR p_naar IS NULL OR p_van = p_naar THEN
        RAISE EXCEPTION 'verplaats_document: bron en doel moeten twee verschillende administraties zijn';
    END IF;
    IF platform.current_administratie_id() IS DISTINCT FROM p_van THEN
        RAISE EXCEPTION 'verplaats_document: aanroeper is niet gescoped op de bron-administratie';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM platform.administratie WHERE id = p_naar) THEN
        RAISE EXCEPTION 'verplaats_document: onbekende doeladministratie %', p_naar;
    END IF;

    SELECT status::text INTO v_status
    FROM boekhouding.document
    WHERE id = p_document_id AND administratie_id = p_van
    FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'verplaats_document: document % niet gevonden in de bron-administratie', p_document_id;
    END IF;
    IF v_status <> 'ontvangen' THEN
        -- De servicelaag zet het document vóór de verhuizing via de statusmachine op ontvangen;
        -- geboekt/ter_accordering hebben dat pad niet en stranden dus ook hier.
        RAISE EXCEPTION 'verplaats_document: document staat op %, verwacht ontvangen', v_status;
    END IF;

    UPDATE boekhouding.document SET administratie_id = p_naar WHERE id = p_document_id;

    -- Kindtabellen mét eigen administratie_id: rijen van dit document volgen mee, zodat ze in de
    -- doel-scope zichtbaar blijven (vragen/afwijzingen = historie + open vragen; signaal-caches
    -- worden ná de her-extractie in het doel opnieuw berekend).
    UPDATE boekhouding.vraag SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.vraag_bericht b SET administratie_id = p_naar
        FROM boekhouding.vraag v
        WHERE b.vraag_id = v.id AND v.document_id = p_document_id AND b.administratie_id = p_van;
    UPDATE boekhouding.afwijzing SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.iban_accordering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.duplicaat_signaal SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.factuurmatch SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.factuurmatch_staat SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.materiaalmatch SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.accordering_stap s SET administratie_id = p_naar
        FROM boekhouding.document_accordering a
        WHERE s.accordering_id = a.id AND a.document_id = p_document_id AND s.administratie_id = p_van;
    UPDATE boekhouding.document_accordering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
    UPDATE boekhouding.document_herinnering SET administratie_id = p_naar
        WHERE document_id = p_document_id AND administratie_id = p_van;
END
$$;


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
        OR ((p_module = 'boekhouding' OR p_module LIKE 'boekhouding.%') AND platform.current_actor_is_beheerder())
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


--
-- Name: veldwerker_scope_binnen_actor(uuid, uuid); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.veldwerker_scope_binnen_actor(p_doel uuid, p_actor uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
                SELECT p_actor = platform.current_actor_id()
                   AND EXISTS (SELECT 1 FROM platform.gebruiker_administratie WHERE gebruiker_id = p_doel)
                   AND NOT EXISTS (
                       SELECT 1 FROM platform.gebruiker_administratie d
                       WHERE d.gebruiker_id = p_doel
                         AND d.administratie_id NOT IN (
                             SELECT a.administratie_id FROM platform.gebruiker_administratie a
                             WHERE a.gebruiker_id = p_actor
                         )
                   )
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
    gedeactiveerd_op timestamp with time zone,
    afdeling_id uuid
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
-- Name: administratie_sync_run; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.administratie_sync_run (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    status text NOT NULL,
    aangevraagd_door uuid,
    aangevraagd_op timestamp with time zone DEFAULT now() NOT NULL,
    gestart_op timestamp with time zone,
    laatst_actief_op timestamp with time zone,
    beeindigd_op timestamp with time zone,
    onderdelen jsonb,
    fout_reden text,
    CONSTRAINT ck_administratie_sync_run_status CHECK ((status = ANY (ARRAY['wachtrij'::text, 'bezig'::text, 'klaar'::text, 'fout'::text])))
);

ALTER TABLE ONLY boekhouding.administratie_sync_run FORCE ROW LEVEL SECURITY;


--
-- Name: afdeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.afdeling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text NOT NULL,
    is_terugval boolean DEFAULT false NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gearchiveerd_door uuid,
    gearchiveerd_op timestamp with time zone
);

ALTER TABLE ONLY boekhouding.afdeling FORCE ROW LEVEL SECURITY;


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
    duplicaat_van_document_id uuid,
    duplicaat_van_rlz_document_id uuid,
    duplicaat_van_referentie text,
    automatisch boolean DEFAULT false NOT NULL,
    CONSTRAINT afwijzing_herkomst_herstelbaar CHECK ((status_voor_afwijzing = ANY (ARRAY['te_controleren'::text, 'handmatig_afmaken'::text, 'klaar_om_te_boeken'::text]))),
    CONSTRAINT afwijzing_heropening_consistent CHECK ((((status = 'open'::text) AND (heropend_door IS NULL) AND (heropend_op IS NULL)) OR ((status = 'heropend'::text) AND (heropend_door IS NOT NULL) AND (heropend_op IS NOT NULL)))),
    CONSTRAINT afwijzing_reden_niet_leeg CHECK ((btrim(reden) <> ''::text)),
    CONSTRAINT afwijzing_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'heropend'::text])))
);

ALTER TABLE ONLY boekhouding.afwijzing FORCE ROW LEVEL SECURITY;


--
-- Name: autoboek_kandidaat_stand; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.autoboek_kandidaat_stand (
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    reeks_ongewijzigd integer DEFAULT 0 NOT NULL,
    correcties integer DEFAULT 0 NOT NULL,
    mens_boekingen integer DEFAULT 0 NOT NULL,
    open_vragen integer DEFAULT 0 NOT NULL,
    kwalificeert boolean DEFAULT false NOT NULL,
    actief boolean DEFAULT false NOT NULL,
    actief_sinds timestamp with time zone,
    redenen jsonb DEFAULT '[]'::jsonb NOT NULL,
    chips jsonb DEFAULT '[]'::jsonb NOT NULL,
    heroverweeg_signalen jsonb DEFAULT '[]'::jsonb NOT NULL,
    laatste_factuur_datum date,
    laatste_factuur_bedrag numeric(14,2),
    laatste_document_id uuid,
    snooze_reden text,
    snooze_op timestamp with time zone,
    snooze_door uuid,
    berekend_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.autoboek_kandidaat_stand FORCE ROW LEVEL SECURITY;


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
    deel_id uuid,
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
-- Name: bank_relatie_boeking; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_relatie_boeking (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    payment_transaction_id uuid NOT NULL,
    deel_id uuid,
    relatie_soort text NOT NULL,
    entity_id uuid NOT NULL,
    entity_naam text,
    bedrag numeric(14,2) NOT NULL,
    vooruit_ledger_id uuid NOT NULL,
    taxrate_id uuid NOT NULL,
    rlz_document_id uuid NOT NULL,
    rlz_boekstuknummer text,
    rlz_payment_item_id uuid,
    omschrijving text,
    status text NOT NULL,
    geboekt_door uuid NOT NULL,
    geboekt_op timestamp with time zone DEFAULT now() NOT NULL,
    verrekend_met_document_id uuid,
    verrekend_op timestamp with time zone,
    gestorneerd_door uuid,
    gestorneerd_op timestamp with time zone,
    storno_reden text,
    CONSTRAINT ck_bank_relatie_boeking_soort CHECK ((relatie_soort = ANY (ARRAY['crediteur'::text, 'debiteur'::text]))),
    CONSTRAINT ck_bank_relatie_boeking_status CHECK ((status = ANY (ARRAY['geboekt'::text, 'verrekend'::text, 'gestorneerd'::text]))),
    CONSTRAINT ck_bank_relatie_boeking_storno_reden CHECK (((status <> 'gestorneerd'::text) OR ((storno_reden IS NOT NULL) AND (length(btrim(storno_reden)) > 0))))
);

ALTER TABLE ONLY boekhouding.bank_relatie_boeking FORCE ROW LEVEL SECURITY;


--
-- Name: bank_splitsing; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_splitsing (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    payment_transaction_id uuid NOT NULL,
    mutatie_bedrag numeric(14,2) NOT NULL,
    status text NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    laatst_verwerkt_op timestamp with time zone,
    gestorneerd_op timestamp with time zone,
    CONSTRAINT ck_bank_splitsing_status CHECK ((status = ANY (ARRAY['bezig'::text, 'verwerkt'::text, 'half_verwerkt'::text, 'gestorneerd'::text])))
);

ALTER TABLE ONLY boekhouding.bank_splitsing FORCE ROW LEVEL SECURITY;


--
-- Name: bank_splitsing_deel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_splitsing_deel (
    id uuid NOT NULL,
    splitsing_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    soort text NOT NULL,
    bedrag numeric(14,2) NOT NULL,
    spec jsonb NOT NULL,
    status text NOT NULL,
    fout text,
    cyclus integer NOT NULL,
    bank_boeking_id uuid,
    afletter_opdracht_id uuid,
    relatie_boeking_id uuid,
    verwerkt_op timestamp with time zone,
    CONSTRAINT ck_bank_splitsing_deel_bedrag CHECK ((bedrag <> (0)::numeric)),
    CONSTRAINT ck_bank_splitsing_deel_soort CHECK ((soort = ANY (ARRAY['grootboek'::text, 'open_post'::text, 'relatie'::text]))),
    CONSTRAINT ck_bank_splitsing_deel_status CHECK ((status = ANY (ARRAY['wacht'::text, 'verwerkt'::text, 'fout'::text, 'gestorneerd'::text])))
);

ALTER TABLE ONLY boekhouding.bank_splitsing_deel FORCE ROW LEVEL SECURITY;


--
-- Name: bank_sync_run; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.bank_sync_run (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    status text NOT NULL,
    aangevraagd_door uuid,
    aangevraagd_op timestamp with time zone DEFAULT now() NOT NULL,
    gestart_op timestamp with time zone,
    laatst_actief_op timestamp with time zone,
    beeindigd_op timestamp with time zone,
    resultaat jsonb,
    fout_reden text,
    CONSTRAINT ck_bank_sync_run_status CHECK ((status = ANY (ARRAY['wachtrij'::text, 'bezig'::text, 'klaar'::text, 'fout'::text])))
);

ALTER TABLE ONLY boekhouding.bank_sync_run FORCE ROW LEVEL SECURITY;


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
    boek_cyclus integer DEFAULT 0 NOT NULL,
    vervaldatum date,
    afdeling_id uuid,
    betalingskenmerk text
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
-- Name: crediteur_archiveer_werklijst; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.crediteur_archiveer_werklijst (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    voorkeur_vendor_id uuid NOT NULL,
    voorkeur_naam text,
    te_archiveren jsonb NOT NULL,
    status text NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gedaan_op timestamp with time zone,
    gedaan_door uuid,
    gedaan_bron text,
    laatste_hertoets_op timestamp with time zone,
    hertoets_detail jsonb,
    CONSTRAINT ck_crediteur_archiveer_werklijst_status CHECK ((status = ANY (ARRAY[('open'::character varying)::text, ('gedaan'::character varying)::text])))
);

ALTER TABLE ONLY boekhouding.crediteur_archiveer_werklijst FORCE ROW LEVEL SECURITY;


--
-- Name: crediteur_dubbel_afmelding; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.crediteur_dubbel_afmelding (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    sleutel_soort text NOT NULL,
    sleutel text NOT NULL,
    combinatie text NOT NULL,
    vendor_ids jsonb NOT NULL,
    reden text NOT NULL,
    afgemeld_door uuid NOT NULL,
    afgemeld_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_crediteur_dubbel_afmelding_soort CHECK ((sleutel_soort = ANY (ARRAY[('btw_nummer'::character varying)::text, ('kvk_nummer'::character varying)::text, ('iban'::character varying)::text, ('naam'::character varying)::text])))
);

ALTER TABLE ONLY boekhouding.crediteur_dubbel_afmelding FORCE ROW LEVEL SECURITY;


--
-- Name: crediteur_kenmerk; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.crediteur_kenmerk (
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    btw_nummer text,
    btw_nummer_geverifieerd boolean,
    btw_nummer_bron text,
    kvk_nummer text,
    kvk_nummer_bron text,
    laatst_uit_document_id uuid,
    bijgewerkt_door uuid,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_crediteur_kenmerk_btw_bron CHECK (((btw_nummer_bron IS NULL) OR (btw_nummer_bron = ANY (ARRAY['factuur'::text, 'handmatig'::text])))),
    CONSTRAINT ck_crediteur_kenmerk_kvk_bron CHECK (((kvk_nummer_bron IS NULL) OR (kvk_nummer_bron = ANY (ARRAY['factuur'::text, 'rlz'::text, 'handmatig'::text]))))
);

ALTER TABLE ONLY boekhouding.crediteur_kenmerk FORCE ROW LEVEL SECURITY;


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
    bron_opslag_pad text,
    bron_bestandsnaam text,
    bron_content_type text,
    samengevoegd_in_id uuid,
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
    factuur_pdf_status character varying,
    factuur_pdf_reden character varying,
    factuur_pdf_bestandsnaam character varying,
    factuur_pdf_opslag_pad character varying,
    factuur_pdf_op timestamp with time zone,
    CONSTRAINT doorbelasting_boeking_factuur_pdf_status CHECK (((factuur_pdf_status IS NULL) OR ((factuur_pdf_status)::text = ANY ((ARRAY['aanwezig'::character varying, 'ontbreekt'::character varying])::text[])))),
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
    project_id uuid,
    project_aandeel numeric(9,6),
    verdeelbasis text,
    m2 numeric(10,2),
    CONSTRAINT doorbelasting_regel_pct_bereik CHECK (((percentage > (0)::numeric) AND (percentage <= (100)::numeric))),
    CONSTRAINT doorbelasting_regel_project_aandeel CHECK (((project_aandeel IS NULL) OR ((project_aandeel > (0)::numeric) AND (project_aandeel <= (1)::numeric)))),
    CONSTRAINT doorbelasting_regel_verdeelbasis CHECK (((verdeelbasis IS NULL) OR (verdeelbasis = ANY (ARRAY['m2'::text, 'gelijk'::text]))))
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
    verdeelsleutel_id uuid,
    verdeelsleutel_toegepast_op timestamp with time zone,
    CONSTRAINT doorbelasting_run_status CHECK ((status = ANY (ARRAY['klaargezet'::text, 'concept'::text, 'geboekt'::text, 'gestorneerd'::text, 'vervallen'::text])))
);

ALTER TABLE ONLY boekhouding.doorbelasting_run FORCE ROW LEVEL SECURITY;


--
-- Name: doorbelasting_verdeelsleutel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.doorbelasting_verdeelsleutel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text NOT NULL,
    versie integer NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    definitie jsonb NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT doorbelasting_verdeelsleutel_versie CHECK ((versie >= 1))
);

ALTER TABLE ONLY boekhouding.doorbelasting_verdeelsleutel FORCE ROW LEVEL SECURITY;


--
-- Name: dossier_document; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.dossier_document (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    type_code text NOT NULL,
    status text NOT NULL,
    geldig_tot date,
    opslag_pad text NOT NULL,
    bestandsnaam text NOT NULL,
    content_type text NOT NULL,
    bron text NOT NULL,
    geupload_door uuid NOT NULL,
    geupload_op timestamp with time zone DEFAULT now() NOT NULL,
    beoordeeld_door uuid,
    beoordeeld_op timestamp with time zone,
    afwijs_reden text,
    CONSTRAINT ck_dossier_document_afwijs_reden CHECK (((status <> 'afgewezen'::text) OR ((afwijs_reden IS NOT NULL) AND (length(btrim(afwijs_reden)) > 0)))),
    CONSTRAINT ck_dossier_document_beoordeeld CHECK (((status = 'ter_controle'::text) = (beoordeeld_op IS NULL))),
    CONSTRAINT ck_dossier_document_bron CHECK ((bron = ANY (ARRAY['kantoor'::text, 'app'::text]))),
    CONSTRAINT ck_dossier_document_status CHECK ((status = ANY (ARRAY['ter_controle'::text, 'goedgekeurd'::text, 'afgewezen'::text])))
);

ALTER TABLE ONLY boekhouding.dossier_document FORCE ROW LEVEL SECURITY;


--
-- Name: dossier_documenttype; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.dossier_documenttype (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    code text NOT NULL,
    naam text NOT NULL,
    verplicht boolean NOT NULL,
    geldig_tot_vereist boolean NOT NULL,
    bsn_gevoelig boolean NOT NULL,
    volgorde integer NOT NULL,
    actief boolean NOT NULL,
    bijgewerkt_door uuid NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_dossier_documenttype_code CHECK ((code ~ '^[a-z0-9_]{2,40}$'::text))
);

ALTER TABLE ONLY boekhouding.dossier_documenttype FORCE ROW LEVEL SECURITY;


--
-- Name: dossier_herinnering; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.dossier_herinnering (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    datum date NOT NULL,
    volgnummer integer NOT NULL,
    status text NOT NULL,
    kanaal text,
    detail jsonb,
    verzonden_door uuid NOT NULL,
    verzonden_op timestamp with time zone,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_dossier_herinnering_status CHECK ((status = ANY (ARRAY['bezig'::text, 'verzonden'::text, 'mislukt'::text, 'overgeslagen'::text])))
);

ALTER TABLE ONLY boekhouding.dossier_herinnering FORCE ROW LEVEL SECURITY;


--
-- Name: duplicaat_signaal; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.duplicaat_signaal (
    document_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    uitkomst text NOT NULL,
    vendor_id uuid,
    referentie text,
    totaalbedrag numeric(14,2),
    treffers jsonb,
    melding text,
    berekend_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_duplicaat_signaal_uitkomst CHECK ((uitkomst = ANY (ARRAY['geen'::text, 'mogelijk_duplicaat'::text, 'niet_toetsbaar'::text, 'onbekend'::text])))
);

ALTER TABLE ONLY boekhouding.duplicaat_signaal FORCE ROW LEVEL SECURITY;


--
-- Name: extractie_template; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.extractie_template (
    id uuid NOT NULL,
    sleutel text NOT NULL,
    sleutel_soort text NOT NULL,
    administratie_id uuid,
    vendor_id uuid,
    definitie jsonb NOT NULL,
    geleerd_uit jsonb NOT NULL,
    geleerd_op timestamp with time zone DEFAULT now() NOT NULL,
    versie integer DEFAULT 1 NOT NULL,
    geldig boolean NOT NULL,
    ongeldig_op timestamp with time zone,
    ongeldig_reden text,
    gebruikt_aantal integer DEFAULT 0 NOT NULL,
    laatst_gebruikt_op timestamp with time zone,
    CONSTRAINT ck_extractie_template_sleutel_soort CHECK ((sleutel_soort = ANY (ARRAY['btw_nummer'::text, 'kvk_nummer'::text, 'administratie_vendor'::text])))
);


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
    body_tekst text,
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
-- Name: intake_splitsing_uitsluiting; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.intake_splitsing_uitsluiting (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    afzender_adres text NOT NULL,
    leverancier_naam text,
    reden text,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verwijderd_op timestamp with time zone,
    verwijderd_door uuid
);

ALTER TABLE ONLY boekhouding.intake_splitsing_uitsluiting FORCE ROW LEVEL SECURITY;


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
-- Name: leverancier_afdeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.leverancier_afdeling (
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    afdeling_id uuid NOT NULL,
    laatste_document_id uuid,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.leverancier_afdeling FORCE ROW LEVEL SECURITY;


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
    autoboeken_ingeschakeld boolean DEFAULT false NOT NULL,
    projectverdeling_pro_rato boolean DEFAULT false NOT NULL
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
-- Name: materiaal_bestelling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_bestelling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    leverancier_id uuid NOT NULL,
    volgnummer integer NOT NULL,
    status text NOT NULL,
    revisie integer NOT NULL,
    regels jsonb NOT NULL,
    gewenste_leverdatum date,
    gewenste_levertijd time without time zone,
    leveradres text,
    contactpersoon text,
    opmerking text,
    annulering_reden text,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_door uuid NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_materiaal_bestelling_annulering CHECK (((status <> 'geannuleerd'::text) OR ((annulering_reden IS NOT NULL) AND (length(btrim(annulering_reden)) > 0)))),
    CONSTRAINT ck_materiaal_bestelling_revisie CHECK ((revisie >= 0)),
    CONSTRAINT ck_materiaal_bestelling_status CHECK ((status = ANY (ARRAY['concept'::text, 'verstuurd'::text, 'geannuleerd'::text])))
);

ALTER TABLE ONLY boekhouding.materiaal_bestelling FORCE ROW LEVEL SECURITY;


--
-- Name: materiaal_bestelling_revisie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_bestelling_revisie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    bestelling_id uuid NOT NULL,
    revisie integer NOT NULL,
    regels jsonb NOT NULL,
    m2_totaal numeric(12,2) NOT NULL,
    delta jsonb,
    gewenste_leverdatum date,
    gewenste_levertijd time without time zone,
    leveradres text,
    pdf_opslag_pad text NOT NULL,
    verzonden_naar text NOT NULL,
    mail_status text NOT NULL,
    mail_fout text,
    verstuurd_door uuid NOT NULL,
    verstuurd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_materiaal_bestelling_revisie_mail CHECK ((mail_status = ANY (ARRAY['verzonden'::text, 'mislukt'::text])))
);

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie FORCE ROW LEVEL SECURITY;


--
-- Name: materiaal_categorie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_categorie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    leverancier_id uuid NOT NULL,
    naam text NOT NULL,
    bundel text NOT NULL,
    volgorde integer NOT NULL,
    actief boolean NOT NULL
);

ALTER TABLE ONLY boekhouding.materiaal_categorie FORCE ROW LEVEL SECURITY;


--
-- Name: materiaal_leverancier; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_leverancier (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text NOT NULL,
    bestel_email text,
    telefoon text,
    adres text,
    vendor_id uuid,
    actief boolean NOT NULL,
    bijgewerkt_door uuid NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    transport_contact_naam text,
    transport_contact_email text,
    materiaal_contact_naam text,
    materiaal_contact_email text
);

ALTER TABLE ONLY boekhouding.materiaal_leverancier FORCE ROW LEVEL SECURITY;


--
-- Name: materiaal_product; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_product (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    leverancier_id uuid NOT NULL,
    categorie_id uuid NOT NULL,
    naam text NOT NULL,
    verpakking text,
    eenheid text NOT NULL,
    m2_lengte numeric(8,3),
    volgorde integer NOT NULL,
    actief boolean NOT NULL,
    CONSTRAINT ck_materiaal_product_m2_lengte CHECK (((m2_lengte IS NULL) OR (m2_lengte >= (0)::numeric)))
);

ALTER TABLE ONLY boekhouding.materiaal_product FORCE ROW LEVEL SECURITY;


--
-- Name: materiaal_transport; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaal_transport (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    leverancier_id uuid NOT NULL,
    bestelling_id uuid,
    soort text NOT NULL,
    datum date NOT NULL,
    tijdstip time without time zone,
    status text NOT NULL,
    status_bron text NOT NULL,
    status_reden text,
    status_gewijzigd_door uuid,
    status_gewijzigd_op timestamp with time zone,
    regels jsonb NOT NULL,
    omschrijving text,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    voertuig text,
    transportplanner text,
    CONSTRAINT ck_materiaal_transport_annulering CHECK (((status <> 'geannuleerd'::text) OR ((status_reden IS NOT NULL) AND (length(btrim(status_reden)) > 0)))),
    CONSTRAINT ck_materiaal_transport_soort CHECK ((soort = ANY (ARRAY['levering'::text, 'retour'::text]))),
    CONSTRAINT ck_materiaal_transport_status CHECK ((status = ANY (ARRAY['gereserveerd'::text, 'bevestigd'::text, 'definitief'::text, 'geleverd'::text, 'geannuleerd'::text, 'gepland'::text]))),
    CONSTRAINT ck_materiaal_transport_voertuig CHECK (((voertuig IS NULL) OR (voertuig = ANY (ARRAY['combi'::text, 'voorwagen'::text]))))
);

ALTER TABLE ONLY boekhouding.materiaal_transport FORCE ROW LEVEL SECURITY;


--
-- Name: materiaalmatch; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.materiaalmatch (
    document_id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    leverancier_id uuid NOT NULL,
    project_id uuid,
    uitkomst text NOT NULL,
    aantal_regels_getoetst integer NOT NULL,
    aantal_regels_afwijkend integer NOT NULL,
    aantal_regels_onbekend integer NOT NULL,
    details jsonb,
    berekend_op timestamp with time zone DEFAULT now() NOT NULL,
    afwijking_bevestigd_door uuid,
    afwijking_bevestigd_op timestamp with time zone,
    CONSTRAINT ck_materiaalmatch_bevestigd_samen CHECK (((afwijking_bevestigd_door IS NULL) = (afwijking_bevestigd_op IS NULL))),
    CONSTRAINT ck_materiaalmatch_uitkomst CHECK ((uitkomst = ANY (ARRAY['match'::text, 'afwijking'::text, 'niet_toetsbaar'::text])))
);

ALTER TABLE ONLY boekhouding.materiaalmatch FORCE ROW LEVEL SECURITY;


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
-- Name: odoo_document_koppeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.odoo_document_koppeling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    boek_cyclus integer NOT NULL,
    soort character varying(16) NOT NULL,
    odoo_move_id integer NOT NULL,
    odoo_naam text,
    odoo_move_type character varying(16) NOT NULL,
    company_id integer NOT NULL,
    state character varying(16) NOT NULL,
    reversal_van_move_id integer,
    detail jsonb,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_odoo_document_koppeling_soort CHECK (((soort)::text = ANY ((ARRAY['boeking'::character varying, 'tegenboeking'::character varying])::text[])))
);

ALTER TABLE ONLY boekhouding.odoo_document_koppeling FORCE ROW LEVEL SECURITY;


--
-- Name: odoo_id_koppeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.odoo_id_koppeling (
    administratie_id uuid NOT NULL,
    model character varying(64) NOT NULL,
    odoo_id integer NOT NULL,
    lokaal_id uuid NOT NULL,
    naam text,
    laatst_gezien_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.odoo_id_koppeling FORCE ROW LEVEL SECURITY;


--
-- Name: odoo_product_koppeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.odoo_product_koppeling (
    administratie_id uuid NOT NULL,
    materiaal_product_id uuid NOT NULL,
    odoo_product_id integer NOT NULL,
    odoo_template_id integer,
    default_code text,
    naam text,
    bron character varying(16) NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_odoo_product_koppeling_bron CHECK (((bron)::text = ANY ((ARRAY['gevonden'::character varying, 'aangemaakt'::character varying])::text[])))
);

ALTER TABLE ONLY boekhouding.odoo_product_koppeling FORCE ROW LEVEL SECURITY;


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
-- Name: project_prijsafspraak; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.project_prijsafspraak (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    eenheid text NOT NULL,
    tarief numeric(10,2) NOT NULL,
    geldig_vanaf_jaar integer,
    geldig_vanaf_week integer,
    geldig_tm_jaar integer,
    geldig_tm_week integer,
    toelichting text,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    ingetrokken_door uuid,
    ingetrokken_op timestamp with time zone,
    ingetrokken_reden text,
    CONSTRAINT ck_project_prijsafspraak_eenheid CHECK ((eenheid = ANY (ARRAY['uur'::text, 'm2'::text]))),
    CONSTRAINT ck_project_prijsafspraak_ingetrokken_reden CHECK (((ingetrokken_op IS NULL) OR ((ingetrokken_reden IS NOT NULL) AND (length(btrim(ingetrokken_reden)) > 0)))),
    CONSTRAINT ck_project_prijsafspraak_tarief CHECK ((tarief >= (0)::numeric)),
    CONSTRAINT ck_project_prijsafspraak_tm_samen CHECK (((geldig_tm_jaar IS NULL) = (geldig_tm_week IS NULL))),
    CONSTRAINT ck_project_prijsafspraak_tm_week CHECK (((geldig_tm_week IS NULL) OR ((geldig_tm_week >= 1) AND (geldig_tm_week <= 53)))),
    CONSTRAINT ck_project_prijsafspraak_vanaf_samen CHECK (((geldig_vanaf_jaar IS NULL) = (geldig_vanaf_week IS NULL))),
    CONSTRAINT ck_project_prijsafspraak_vanaf_week CHECK (((geldig_vanaf_week IS NULL) OR ((geldig_vanaf_week >= 1) AND (geldig_vanaf_week <= 53))))
);

ALTER TABLE ONLY boekhouding.project_prijsafspraak FORCE ROW LEVEL SECURITY;


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
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    locatie_adres text,
    locatie_lat numeric(9,6),
    locatie_lon numeric(9,6),
    zone_straal_m smallint,
    CONSTRAINT ck_project_specificatie_zone_straal CHECK (((zone_straal_m IS NULL) OR ((zone_straal_m >= 50) AND (zone_straal_m <= 1000))))
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
-- Name: projectverdeling; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.projectverdeling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    vaste_regels jsonb DEFAULT '[]'::jsonb NOT NULL,
    pro_rato_periode date,
    pro_rato_bedrag numeric(14,2),
    verdeling jsonb DEFAULT '[]'::jsonb NOT NULL,
    omzetstanden jsonb DEFAULT '[]'::jsonb NOT NULL,
    status text DEFAULT 'voorstel'::text NOT NULL,
    geboekt_op timestamp with time zone,
    boek_cyclus integer,
    hercontrole_op timestamp with time zone,
    hercontrole_afwijking_pct numeric(7,2),
    hercontrole_verdeling jsonb,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_projectverdeling_status CHECK ((status = ANY (ARRAY['voorstel'::text, 'geboekt'::text, 'vervallen'::text])))
);

ALTER TABLE ONLY boekhouding.projectverdeling FORCE ROW LEVEL SECURITY;


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
-- Name: regel_gb_classificatie; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.regel_gb_classificatie (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid NOT NULL,
    regel_volgnummer integer NOT NULL,
    regel_sleutel text,
    ledger_id uuid,
    kandidaten_n integer NOT NULL,
    model text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY boekhouding.regel_gb_classificatie FORCE ROW LEVEL SECURITY;


--
-- Name: registersync_levering; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.registersync_levering (
    id uuid NOT NULL,
    nonce text NOT NULL,
    ontvangen_op timestamp with time zone DEFAULT now() NOT NULL,
    generated_at timestamp with time zone NOT NULL,
    aantal_administraties integer NOT NULL,
    aantal_grootboekrekeningen integer NOT NULL,
    duur_ms integer NOT NULL
);


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
    ingetrokken_op timestamp with time zone,
    afdeling_id uuid
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
-- Name: terugkerend_herbereken_run; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.terugkerend_herbereken_run (
    id uuid NOT NULL,
    status text DEFAULT 'wachtend'::character varying NOT NULL,
    gestart_door uuid,
    aangevraagd_op timestamp with time zone DEFAULT now() NOT NULL,
    gestart_op timestamp with time zone,
    laatst_actief_op timestamp with time zone,
    klaar_op timestamp with time zone,
    aantal_administraties integer DEFAULT 0 NOT NULL,
    aantal_verwerkt integer DEFAULT 0 NOT NULL,
    aantal_fouten integer DEFAULT 0 NOT NULL,
    foutreden text,
    resultaat jsonb,
    CONSTRAINT ck_terugkerend_herbereken_run_status CHECK ((status = ANY (ARRAY[('wachtend'::character varying)::text, ('bezig'::character varying)::text, ('klaar'::character varying)::text, ('fout'::character varying)::text])))
);


--
-- Name: terugkerend_signaal; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.terugkerend_signaal (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    patroon text NOT NULL,
    interval_dagen integer NOT NULL,
    aantal_facturen integer NOT NULL,
    laatste_datum date NOT NULL,
    laatste_bedrag numeric(14,2),
    laatste_document_id uuid,
    vorige_datum date,
    vorige_bedrag numeric(14,2),
    verwacht_op date NOT NULL,
    uiterlijk_op date NOT NULL,
    ontbreekt_sinds date,
    prijsstijging_pct numeric(7,2),
    snooze_tot date,
    afgemeld_op timestamp with time zone,
    afgemeld_door uuid,
    berekend_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_terugkerend_signaal_patroon CHECK ((patroon = ANY (ARRAY['maand'::text, 'kwartaal'::text])))
);

ALTER TABLE ONLY boekhouding.terugkerend_signaal FORCE ROW LEVEL SECURITY;


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
-- Name: veldwerker_dossier; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.veldwerker_dossier (
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    herinneringen_teller integer DEFAULT 0 NOT NULL,
    laatste_herinnering_op timestamp with time zone,
    geblokkeerd boolean DEFAULT false NOT NULL,
    geblokkeerd_op timestamp with time zone,
    gedeblokkeerd_op timestamp with time zone,
    kvk_nummer text,
    btw_nummer text,
    kvk_naam text,
    kvk_plaats text,
    kvk_rechtsvorm text,
    kvk_bevestigd_door uuid,
    kvk_bevestigd_op timestamp with time zone,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_veldwerker_dossier_kvk CHECK (((kvk_nummer IS NULL) OR (kvk_nummer ~ '^[0-9]{8}$'::text))),
    CONSTRAINT ck_veldwerker_dossier_teller CHECK ((herinneringen_teller >= 0))
);

ALTER TABLE ONLY boekhouding.veldwerker_dossier FORCE ROW LEVEL SECURITY;


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
    aan_de_beurt uuid,
    afgehandeld_door uuid,
    afgehandeld_op timestamp with time zone,
    aan_de_beurt_sinds timestamp with time zone,
    accordeur_gemeld_op timestamp with time zone,
    CONSTRAINT vraag_antwoord_consistent CHECK ((((status = 'open'::text) AND (antwoord_tekst IS NULL) AND (beantwoord_door IS NULL) AND (beantwoord_op IS NULL) AND (ingetrokken_door IS NULL) AND (ingetrokken_op IS NULL) AND (ingetrokken_reden IS NULL) AND (afgehandeld_door IS NULL) AND (afgehandeld_op IS NULL)) OR ((status = 'beantwoord'::text) AND (btrim(antwoord_tekst) <> ''::text) AND (beantwoord_door IS NOT NULL) AND (beantwoord_op IS NOT NULL) AND (ingetrokken_door IS NULL) AND (ingetrokken_op IS NULL) AND (ingetrokken_reden IS NULL) AND (afgehandeld_door IS NULL) AND (afgehandeld_op IS NULL)) OR ((status = 'ingetrokken'::text) AND (ingetrokken_door IS NOT NULL) AND (ingetrokken_op IS NOT NULL) AND (antwoord_tekst IS NULL) AND (beantwoord_door IS NULL) AND (beantwoord_op IS NULL) AND (afgehandeld_door IS NULL) AND (afgehandeld_op IS NULL)) OR ((status = 'afgehandeld'::text) AND (afgehandeld_door IS NOT NULL) AND (afgehandeld_op IS NOT NULL) AND (antwoord_tekst IS NULL) AND (beantwoord_door IS NULL) AND (beantwoord_op IS NULL) AND (ingetrokken_door IS NULL) AND (ingetrokken_op IS NULL) AND (ingetrokken_reden IS NULL)))),
    CONSTRAINT vraag_herkomst_herstelbaar CHECK ((status_voor_vraag = ANY (ARRAY['te_controleren'::text, 'handmatig_afmaken'::text, 'klaar_om_te_boeken'::text, 'ter_accordering'::text, 'geboekt'::text]))),
    CONSTRAINT vraag_status_geldig CHECK ((status = ANY (ARRAY['open'::text, 'beantwoord'::text, 'ingetrokken'::text, 'afgehandeld'::text]))),
    CONSTRAINT vraag_tekst_niet_leeg CHECK ((btrim(vraag_tekst) <> ''::text))
);

ALTER TABLE ONLY boekhouding.vraag FORCE ROW LEVEL SECURITY;


--
-- Name: vraag_bericht; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.vraag_bericht (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    vraag_id uuid NOT NULL,
    auteur_id uuid NOT NULL,
    tekst text NOT NULL,
    geplaatst_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vraag_bericht_tekst_niet_leeg CHECK ((btrim(tekst) <> ''::text))
);

ALTER TABLE ONLY boekhouding.vraag_bericht FORCE ROW LEVEL SECURITY;


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
-- Name: werkopdracht; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.werkopdracht (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    project_id uuid NOT NULL,
    groep_id uuid NOT NULL,
    versie integer NOT NULL,
    van date NOT NULL,
    tot_en_met date NOT NULL,
    tekst text NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_werkopdracht_periode CHECK ((van <= tot_en_met)),
    CONSTRAINT ck_werkopdracht_tekst CHECK ((length(btrim(tekst)) > 0)),
    CONSTRAINT ck_werkopdracht_versie CHECK ((versie >= 1))
);

ALTER TABLE ONLY boekhouding.werkopdracht FORCE ROW LEVEL SECURITY;


--
-- Name: werkopdracht_dag; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.werkopdracht_dag (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    groep_id uuid NOT NULL,
    datum date NOT NULL,
    versie integer NOT NULL,
    tekst text NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_werkopdracht_dag_tekst CHECK ((length(btrim(tekst)) > 0)),
    CONSTRAINT ck_werkopdracht_dag_versie CHECK ((versie >= 1))
);

ALTER TABLE ONLY boekhouding.werkopdracht_dag FORCE ROW LEVEL SECURITY;


--
-- Name: werkstempel; Type: TABLE; Schema: boekhouding; Owner: -
--

CREATE TABLE boekhouding.werkstempel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    project_id uuid NOT NULL,
    tijdstip timestamp with time zone NOT NULL,
    soort text NOT NULL,
    bron text DEFAULT 'app'::text NOT NULL,
    apparaat_id uuid,
    ontvangen_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_werkstempel_bron CHECK ((bron = ANY (ARRAY['app'::text, 'os_geofence'::text]))),
    CONSTRAINT ck_werkstempel_soort CHECK ((soort = ANY (ARRAY['in'::text, 'uit'::text])))
);

ALTER TABLE ONLY boekhouding.werkstempel FORCE ROW LEVEL SECURITY;


--
-- Name: artikelcode_koppeling; Type: TABLE; Schema: mi; Owner: -
--

CREATE TABLE mi.artikelcode_koppeling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    richting text NOT NULL,
    vendor_id uuid NOT NULL,
    code text NOT NULL,
    artikelgroep_id uuid,
    soort text DEFAULT 'artikel'::text NOT NULL,
    zekerheid numeric(4,3),
    bron text NOT NULL,
    voorbeeld_tekst text,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_door uuid,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_artikelcode_koppeling_bron CHECK ((bron = ANY (ARRAY['ai'::text, 'handmatig'::text]))),
    CONSTRAINT ck_artikelcode_koppeling_groep_bij_artikel CHECK (((soort = 'artikel'::text) OR (artikelgroep_id IS NULL))),
    CONSTRAINT ck_artikelcode_koppeling_richting CHECK ((richting = ANY (ARRAY['in'::text, 'uit'::text]))),
    CONSTRAINT ck_artikelcode_koppeling_soort CHECK ((soort = ANY (ARRAY['artikel'::text, 'dienst'::text, 'transport'::text])))
);

ALTER TABLE ONLY mi.artikelcode_koppeling FORCE ROW LEVEL SECURITY;


--
-- Name: artikelgroep; Type: TABLE; Schema: mi; Owner: -
--

CREATE TABLE mi.artikelgroep (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    naam text NOT NULL,
    eenheid text DEFAULT 'st'::text NOT NULL,
    tolerantie_pct numeric(5,2) DEFAULT 1.00 NOT NULL,
    actief boolean DEFAULT true NOT NULL,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_artikelgroep_tolerantie CHECK (((tolerantie_pct >= (0)::numeric) AND (tolerantie_pct <= (100)::numeric)))
);

ALTER TABLE ONLY mi.artikelgroep FORCE ROW LEVEL SECURITY;


--
-- Name: normalisatie_regel; Type: TABLE; Schema: mi; Owner: -
--

CREATE TABLE mi.normalisatie_regel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    artikeltekst_norm text NOT NULL,
    artikelgroep_id uuid,
    uitgesloten boolean DEFAULT false NOT NULL,
    zekerheid numeric(4,3),
    bron text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_door uuid,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    soort text DEFAULT 'artikel'::text NOT NULL,
    CONSTRAINT ck_normalisatie_regel_bron CHECK ((bron = ANY (ARRAY['ai'::text, 'handmatig'::text, 'regel'::text]))),
    CONSTRAINT ck_normalisatie_regel_soort CHECK ((soort = ANY (ARRAY['artikel'::text, 'dienst'::text, 'transport'::text])))
);

ALTER TABLE ONLY mi.normalisatie_regel FORCE ROW LEVEL SECURITY;


--
-- Name: voorraad_regel; Type: TABLE; Schema: mi; Owner: -
--

CREATE TABLE mi.voorraad_regel (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    document_id uuid,
    richting text NOT NULL,
    bron text NOT NULL,
    datum date NOT NULL,
    vendor_id uuid,
    relatie_naam text,
    regel_volgnummer integer NOT NULL,
    artikeltekst text NOT NULL,
    aantal numeric(12,3),
    eenheid text,
    prijs numeric(14,4),
    netto_bedrag numeric(14,2),
    artikelgroep_id uuid,
    normalisatie_status text NOT NULL,
    normalisatie_zekerheid numeric(4,3),
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    rlz_document_id uuid,
    rlz_referentie text,
    soort text DEFAULT 'artikel'::text NOT NULL,
    artikelcode text,
    CONSTRAINT ck_voorraad_regel_herkomst CHECK (((document_id IS NOT NULL) <> (rlz_document_id IS NOT NULL))),
    CONSTRAINT ck_voorraad_regel_richting CHECK ((richting = ANY (ARRAY['in'::text, 'uit'::text]))),
    CONSTRAINT ck_voorraad_regel_soort CHECK ((soort = ANY (ARRAY['artikel'::text, 'dienst'::text, 'transport'::text]))),
    CONSTRAINT ck_voorraad_regel_status CHECK ((normalisatie_status = ANY (ARRAY['genormaliseerd'::text, 'onzeker'::text, 'uitgesloten'::text, 'niet_genormaliseerd'::text])))
);

ALTER TABLE ONLY mi.voorraad_regel FORCE ROW LEVEL SECURITY;


--
-- Name: voorraad_telling; Type: TABLE; Schema: mi; Owner: -
--

CREATE TABLE mi.voorraad_telling (
    id uuid NOT NULL,
    administratie_id uuid NOT NULL,
    artikelgroep_id uuid NOT NULL,
    datum date NOT NULL,
    aantal numeric(12,3) NOT NULL,
    opmerking text,
    ingevoerd_door uuid NOT NULL,
    ingevoerd_op timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY mi.voorraad_telling FORCE ROW LEVEL SECURITY;


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
    uren_dagmax_uren numeric(4,2) DEFAULT 12 NOT NULL,
    afdelingen_ingeschakeld boolean DEFAULT false NOT NULL,
    voorraad_ingeschakeld boolean DEFAULT false NOT NULL,
    gearchiveerd_op timestamp with time zone,
    gearchiveerd_door uuid,
    terugkerend_prijsstijging_pct numeric(5,2) DEFAULT 10.00 NOT NULL,
    verkoopmodule_afwezig boolean DEFAULT false NOT NULL,
    omzet_autoboeken_ingeschakeld boolean DEFAULT false NOT NULL,
    boekhoud_backend character varying(16) DEFAULT 'rlz'::character varying NOT NULL,
    duplicaat_autoafvoer_ingeschakeld boolean DEFAULT false NOT NULL,
    projectverdeling_drempel_pct numeric(5,2) DEFAULT 5.00 NOT NULL,
    inkoop_zonder_omzet_wachtweken integer DEFAULT 4 NOT NULL,
    standaard_taxrate_id uuid,
    CONSTRAINT administratie_reconciliatie_uitsluiting_reden CHECK (((NOT reconciliatie_uitgesloten) OR ((reconciliatie_uitsluiting_reden IS NOT NULL) AND (length(btrim(reconciliatie_uitsluiting_reden)) >= 5)))),
    CONSTRAINT ck_administratie_boekhoud_backend CHECK (((boekhoud_backend)::text = ANY ((ARRAY['rlz'::character varying, 'odoo'::character varying])::text[]))),
    CONSTRAINT ck_administratie_uren_dagmax CHECK (((uren_dagmax_uren > (0)::numeric) AND (uren_dagmax_uren <= (24)::numeric)))
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
-- Name: autoboek_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.autoboek_instelling (
    singleton boolean DEFAULT true NOT NULL,
    drempel_op_rij integer DEFAULT 5 NOT NULL,
    laatste_run_op timestamp with time zone,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT autoboek_instelling_drempel CHECK (((drempel_op_rij >= 1) AND (drempel_op_rij <= 50))),
    CONSTRAINT autoboek_instelling_singleton CHECK (singleton)
);


--
-- Name: bewaking_probe_run; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.bewaking_probe_run (
    id uuid NOT NULL,
    gestart_op timestamp with time zone DEFAULT now() NOT NULL,
    beeindigd_op timestamp with time zone,
    met_ai boolean NOT NULL,
    uitkomsten jsonb NOT NULL,
    alles_ok boolean NOT NULL
);


--
-- Name: bewaking_storing; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.bewaking_storing (
    id uuid NOT NULL,
    soort text NOT NULL,
    begonnen_op timestamp with time zone DEFAULT now() NOT NULL,
    opeenvolgende_fouten integer NOT NULL,
    laatste_fout_op timestamp with time zone,
    laatste_detail text,
    alert_verzonden_op timestamp with time zone,
    hersteld_op timestamp with time zone,
    herstel_gemeld_op timestamp with time zone
);


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
-- Name: duplicaat_afvoer_instelling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.duplicaat_afvoer_instelling (
    singleton boolean DEFAULT true NOT NULL,
    platformbreed_ingeschakeld boolean DEFAULT true NOT NULL,
    gewijzigd_door uuid,
    gewijzigd_op timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT duplicaat_afvoer_instelling_singleton CHECK (singleton)
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
    gearchiveerd_op timestamp with time zone,
    gearchiveerd_door uuid,
    status_voor_archivering text,
    digest_opt_out boolean DEFAULT false NOT NULL,
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
    CONSTRAINT ck_gebruiker_module_rol_geldig CHECK ((((module = 'vastgoed'::text) AND (rol = ANY (ARRAY['superadmin'::text, 'eigenaar'::text, 'kantoor'::text]))) OR ((module = 'boekhouding'::text) AND (rol = 'meerwerk_urenstaten'::text)) OR ((module = 'boekhouding.veldwerkerbeheer'::text) AND (rol = 'veldwerkerbeheer'::text))))
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
-- Name: kantoor_digest; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.kantoor_digest (
    id uuid NOT NULL,
    gebruiker_id uuid NOT NULL,
    iso_week text NOT NULL,
    status text DEFAULT 'bezig'::text NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    verzonden_op timestamp with time zone,
    detail jsonb
);


--
-- Name: odoo_koppeling; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.odoo_koppeling (
    administratie_id uuid NOT NULL,
    odoo_url text NOT NULL,
    company_id integer NOT NULL,
    company_naam text,
    api_gebruiker text,
    api_key_ciphertext bytea NOT NULL,
    wrapped_data_key bytea NOT NULL,
    api_key_verloopt_op date,
    journal_purchase_id integer,
    journal_general_id integer,
    journal_sale_id integer,
    analytic_plan_id integer,
    probe_rapport jsonb,
    probe_op timestamp with time zone,
    aangemaakt_door uuid NOT NULL,
    aangemaakt_op timestamp with time zone DEFAULT now() NOT NULL,
    bijgewerkt_op timestamp with time zone DEFAULT now() NOT NULL,
    alleen_lezen boolean DEFAULT false NOT NULL,
    voorraad_knip_datum date,
    overgangsdatum date,
    rlz_admin_id_voor_overstap text,
    CONSTRAINT ck_odoo_koppeling_company CHECK ((company_id > 0))
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
    gebruikt_op timestamp with time zone,
    soort text DEFAULT 'uitnodiging'::text NOT NULL,
    wachtwoord_hash_in_wacht text,
    CONSTRAINT ck_uitnodiging_soort CHECK ((soort = ANY (ARRAY['uitnodiging'::text, 'wachtwoord_herstel'::text])))
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
-- Name: administratie_sync_run administratie_sync_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.administratie_sync_run
    ADD CONSTRAINT administratie_sync_run_pkey PRIMARY KEY (id);


--
-- Name: afdeling afdeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afdeling
    ADD CONSTRAINT afdeling_pkey PRIMARY KEY (id);


--
-- Name: afwijzing afwijzing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_pkey PRIMARY KEY (id);


--
-- Name: autoboek_kandidaat_stand autoboek_kandidaat_stand_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.autoboek_kandidaat_stand
    ADD CONSTRAINT autoboek_kandidaat_stand_pkey PRIMARY KEY (administratie_id, vendor_id);


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
-- Name: bank_relatie_boeking bank_relatie_boeking_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_relatie_boeking
    ADD CONSTRAINT bank_relatie_boeking_pkey PRIMARY KEY (id);


--
-- Name: bank_splitsing_deel bank_splitsing_deel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing_deel
    ADD CONSTRAINT bank_splitsing_deel_pkey PRIMARY KEY (id);


--
-- Name: bank_splitsing bank_splitsing_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing
    ADD CONSTRAINT bank_splitsing_pkey PRIMARY KEY (id);


--
-- Name: bank_sync_run bank_sync_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_sync_run
    ADD CONSTRAINT bank_sync_run_pkey PRIMARY KEY (id);


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
-- Name: crediteur_archiveer_werklijst crediteur_archiveer_werklijst_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_archiveer_werklijst
    ADD CONSTRAINT crediteur_archiveer_werklijst_pkey PRIMARY KEY (id);


--
-- Name: crediteur_dubbel_afmelding crediteur_dubbel_afmelding_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_dubbel_afmelding
    ADD CONSTRAINT crediteur_dubbel_afmelding_pkey PRIMARY KEY (id);


--
-- Name: crediteur_kenmerk crediteur_kenmerk_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_kenmerk
    ADD CONSTRAINT crediteur_kenmerk_pkey PRIMARY KEY (administratie_id, vendor_id);


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
    ADD CONSTRAINT doorbelasting_regel_uniek UNIQUE NULLS NOT DISTINCT (run_id, bron_regel_id, mapping_id, project_id);


--
-- Name: doorbelasting_run doorbelasting_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT doorbelasting_run_pkey PRIMARY KEY (id);


--
-- Name: doorbelasting_verdeelsleutel doorbelasting_verdeelsleutel_naam_versie; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_verdeelsleutel
    ADD CONSTRAINT doorbelasting_verdeelsleutel_naam_versie UNIQUE (administratie_id, naam, versie);


--
-- Name: doorbelasting_verdeelsleutel doorbelasting_verdeelsleutel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_verdeelsleutel
    ADD CONSTRAINT doorbelasting_verdeelsleutel_pkey PRIMARY KEY (id);


--
-- Name: dossier_document dossier_document_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_document
    ADD CONSTRAINT dossier_document_pkey PRIMARY KEY (id);


--
-- Name: dossier_documenttype dossier_documenttype_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_documenttype
    ADD CONSTRAINT dossier_documenttype_pkey PRIMARY KEY (id);


--
-- Name: dossier_herinnering dossier_herinnering_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_herinnering
    ADD CONSTRAINT dossier_herinnering_pkey PRIMARY KEY (id);


--
-- Name: duplicaat_signaal duplicaat_signaal_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.duplicaat_signaal
    ADD CONSTRAINT duplicaat_signaal_pkey PRIMARY KEY (document_id);


--
-- Name: extractie_template extractie_template_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.extractie_template
    ADD CONSTRAINT extractie_template_pkey PRIMARY KEY (id);


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
-- Name: intake_splitsing_uitsluiting intake_splitsing_uitsluiting_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing_uitsluiting
    ADD CONSTRAINT intake_splitsing_uitsluiting_pkey PRIMARY KEY (id);


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
-- Name: leverancier_afdeling leverancier_afdeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_afdeling
    ADD CONSTRAINT leverancier_afdeling_pkey PRIMARY KEY (administratie_id, vendor_id);


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
-- Name: materiaal_bestelling materiaal_bestelling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT materiaal_bestelling_pkey PRIMARY KEY (id);


--
-- Name: materiaal_bestelling_revisie materiaal_bestelling_revisie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie
    ADD CONSTRAINT materiaal_bestelling_revisie_pkey PRIMARY KEY (id);


--
-- Name: materiaal_categorie materiaal_categorie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_categorie
    ADD CONSTRAINT materiaal_categorie_pkey PRIMARY KEY (id);


--
-- Name: materiaal_leverancier materiaal_leverancier_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_leverancier
    ADD CONSTRAINT materiaal_leverancier_pkey PRIMARY KEY (id);


--
-- Name: materiaal_product materiaal_product_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_product
    ADD CONSTRAINT materiaal_product_pkey PRIMARY KEY (id);


--
-- Name: materiaal_transport materiaal_transport_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_pkey PRIMARY KEY (id);


--
-- Name: materiaalmatch materiaalmatch_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaalmatch
    ADD CONSTRAINT materiaalmatch_pkey PRIMARY KEY (document_id);


--
-- Name: meerwerk meerwerk_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.meerwerk
    ADD CONSTRAINT meerwerk_pkey PRIMARY KEY (id);


--
-- Name: odoo_document_koppeling odoo_document_koppeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_document_koppeling
    ADD CONSTRAINT odoo_document_koppeling_pkey PRIMARY KEY (id);


--
-- Name: odoo_id_koppeling odoo_id_koppeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_id_koppeling
    ADD CONSTRAINT odoo_id_koppeling_pkey PRIMARY KEY (administratie_id, model, odoo_id);


--
-- Name: odoo_product_koppeling odoo_product_koppeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_product_koppeling
    ADD CONSTRAINT odoo_product_koppeling_pkey PRIMARY KEY (administratie_id, materiaal_product_id);


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
-- Name: project_prijsafspraak project_prijsafspraak_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT project_prijsafspraak_pkey PRIMARY KEY (id);


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
-- Name: projectverdeling projectverdeling_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectverdeling
    ADD CONSTRAINT projectverdeling_pkey PRIMARY KEY (id);


--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.reconciliatie_acceptatie
    ADD CONSTRAINT reconciliatie_acceptatie_pkey PRIMARY KEY (id);


--
-- Name: regel_gb_classificatie regel_gb_classificatie_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.regel_gb_classificatie
    ADD CONSTRAINT regel_gb_classificatie_pkey PRIMARY KEY (id);


--
-- Name: registersync_levering registersync_levering_nonce_key; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.registersync_levering
    ADD CONSTRAINT registersync_levering_nonce_key UNIQUE (nonce);


--
-- Name: registersync_levering registersync_levering_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.registersync_levering
    ADD CONSTRAINT registersync_levering_pkey PRIMARY KEY (id);


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
-- Name: terugkerend_herbereken_run terugkerend_herbereken_run_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_herbereken_run
    ADD CONSTRAINT terugkerend_herbereken_run_pkey PRIMARY KEY (id);


--
-- Name: terugkerend_signaal terugkerend_signaal_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_signaal
    ADD CONSTRAINT terugkerend_signaal_pkey PRIMARY KEY (id);


--
-- Name: toewijzing_regel toewijzing_regel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.toewijzing_regel
    ADD CONSTRAINT toewijzing_regel_pkey PRIMARY KEY (id);


--
-- Name: crediteur_dubbel_afmelding uq_crediteur_dubbel_afmelding_combinatie; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_dubbel_afmelding
    ADD CONSTRAINT uq_crediteur_dubbel_afmelding_combinatie UNIQUE (administratie_id, combinatie);


--
-- Name: dossier_documenttype uq_dossier_documenttype_code; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_documenttype
    ADD CONSTRAINT uq_dossier_documenttype_code UNIQUE (administratie_id, code);


--
-- Name: dossier_herinnering uq_dossier_herinnering_dag; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_herinnering
    ADD CONSTRAINT uq_dossier_herinnering_dag UNIQUE (administratie_id, gebruiker_id, datum);


--
-- Name: extractie_template uq_extractie_template_sleutel; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.extractie_template
    ADD CONSTRAINT uq_extractie_template_sleutel UNIQUE (sleutel);


--
-- Name: leverancier_werknummer uq_leverancier_werknummer; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_werknummer
    ADD CONSTRAINT uq_leverancier_werknummer UNIQUE (administratie_id, vendor_id, werknummer);


--
-- Name: materiaal_bestelling_revisie uq_materiaal_bestelling_revisie; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie
    ADD CONSTRAINT uq_materiaal_bestelling_revisie UNIQUE (bestelling_id, revisie);


--
-- Name: materiaal_bestelling uq_materiaal_bestelling_volgnummer; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT uq_materiaal_bestelling_volgnummer UNIQUE (administratie_id, volgnummer);


--
-- Name: materiaal_categorie uq_materiaal_categorie_naam; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_categorie
    ADD CONSTRAINT uq_materiaal_categorie_naam UNIQUE (leverancier_id, naam);


--
-- Name: materiaal_leverancier uq_materiaal_leverancier_naam; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_leverancier
    ADD CONSTRAINT uq_materiaal_leverancier_naam UNIQUE (administratie_id, naam);


--
-- Name: materiaal_product uq_materiaal_product_naam; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_product
    ADD CONSTRAINT uq_materiaal_product_naam UNIQUE (leverancier_id, naam);


--
-- Name: odoo_document_koppeling uq_odoo_document_koppeling_cyclus; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_document_koppeling
    ADD CONSTRAINT uq_odoo_document_koppeling_cyclus UNIQUE (administratie_id, document_id, boek_cyclus, soort);


--
-- Name: odoo_id_koppeling uq_odoo_id_koppeling_lokaal; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_id_koppeling
    ADD CONSTRAINT uq_odoo_id_koppeling_lokaal UNIQUE (administratie_id, lokaal_id);


--
-- Name: projectverdeling uq_projectverdeling_document; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectverdeling
    ADD CONSTRAINT uq_projectverdeling_document UNIQUE (document_id);


--
-- Name: regel_gb_classificatie uq_regel_gb_classificatie_document_regel; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.regel_gb_classificatie
    ADD CONSTRAINT uq_regel_gb_classificatie_document_regel UNIQUE (document_id, regel_volgnummer);


--
-- Name: terugkerend_signaal uq_terugkerend_signaal_vendor; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_signaal
    ADD CONSTRAINT uq_terugkerend_signaal_vendor UNIQUE (administratie_id, vendor_id);


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
-- Name: werkopdracht_dag uq_werkopdracht_dag_versie; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht_dag
    ADD CONSTRAINT uq_werkopdracht_dag_versie UNIQUE (groep_id, datum, versie);


--
-- Name: werkopdracht uq_werkopdracht_groep_versie; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht
    ADD CONSTRAINT uq_werkopdracht_groep_versie UNIQUE (groep_id, versie);


--
-- Name: werkstempel uq_werkstempel_moment; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkstempel
    ADD CONSTRAINT uq_werkstempel_moment UNIQUE (gebruiker_id, project_id, tijdstip, soort);


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
-- Name: veldwerker_dossier veldwerker_dossier_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_dossier
    ADD CONSTRAINT veldwerker_dossier_pkey PRIMARY KEY (administratie_id, gebruiker_id);


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
-- Name: vraag_bericht vraag_bericht_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag_bericht
    ADD CONSTRAINT vraag_bericht_pkey PRIMARY KEY (id);


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
-- Name: werkopdracht_dag werkopdracht_dag_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht_dag
    ADD CONSTRAINT werkopdracht_dag_pkey PRIMARY KEY (id);


--
-- Name: werkopdracht werkopdracht_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht
    ADD CONSTRAINT werkopdracht_pkey PRIMARY KEY (id);


--
-- Name: werkstempel werkstempel_pkey; Type: CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkstempel
    ADD CONSTRAINT werkstempel_pkey PRIMARY KEY (id);


--
-- Name: artikelcode_koppeling artikelcode_koppeling_pkey; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelcode_koppeling
    ADD CONSTRAINT artikelcode_koppeling_pkey PRIMARY KEY (id);


--
-- Name: artikelgroep artikelgroep_pkey; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelgroep
    ADD CONSTRAINT artikelgroep_pkey PRIMARY KEY (id);


--
-- Name: normalisatie_regel normalisatie_regel_pkey; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.normalisatie_regel
    ADD CONSTRAINT normalisatie_regel_pkey PRIMARY KEY (id);


--
-- Name: artikelcode_koppeling uq_artikelcode_koppeling; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelcode_koppeling
    ADD CONSTRAINT uq_artikelcode_koppeling UNIQUE (administratie_id, richting, vendor_id, code);


--
-- Name: normalisatie_regel uq_normalisatie_regel_tekst; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.normalisatie_regel
    ADD CONSTRAINT uq_normalisatie_regel_tekst UNIQUE (administratie_id, vendor_id, artikeltekst_norm);


--
-- Name: voorraad_regel uq_voorraad_regel_document_regel; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_regel
    ADD CONSTRAINT uq_voorraad_regel_document_regel UNIQUE (document_id, richting, regel_volgnummer);


--
-- Name: voorraad_telling uq_voorraad_telling_groep_datum; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_telling
    ADD CONSTRAINT uq_voorraad_telling_groep_datum UNIQUE (artikelgroep_id, datum);


--
-- Name: voorraad_regel voorraad_regel_pkey; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_regel
    ADD CONSTRAINT voorraad_regel_pkey PRIMARY KEY (id);


--
-- Name: voorraad_telling voorraad_telling_pkey; Type: CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_telling
    ADD CONSTRAINT voorraad_telling_pkey PRIMARY KEY (id);


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
-- Name: autoboek_instelling autoboek_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.autoboek_instelling
    ADD CONSTRAINT autoboek_instelling_pkey PRIMARY KEY (singleton);


--
-- Name: bewaking_probe_run bewaking_probe_run_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.bewaking_probe_run
    ADD CONSTRAINT bewaking_probe_run_pkey PRIMARY KEY (id);


--
-- Name: bewaking_storing bewaking_storing_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.bewaking_storing
    ADD CONSTRAINT bewaking_storing_pkey PRIMARY KEY (id);


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
-- Name: duplicaat_afvoer_instelling duplicaat_afvoer_instelling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.duplicaat_afvoer_instelling
    ADD CONSTRAINT duplicaat_afvoer_instelling_pkey PRIMARY KEY (singleton);


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
-- Name: kantoor_digest kantoor_digest_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.kantoor_digest
    ADD CONSTRAINT kantoor_digest_pkey PRIMARY KEY (id);


--
-- Name: odoo_koppeling odoo_koppeling_pkey; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.odoo_koppeling
    ADD CONSTRAINT odoo_koppeling_pkey PRIMARY KEY (administratie_id);


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
-- Name: kantoor_digest uq_kantoor_digest_week; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.kantoor_digest
    ADD CONSTRAINT uq_kantoor_digest_week UNIQUE (gebruiker_id, iso_week);


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
-- Name: afwijzing_duplicaat_van_document_idx; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX afwijzing_duplicaat_van_document_idx ON boekhouding.afwijzing USING btree (duplicaat_van_document_id) WHERE (duplicaat_van_document_id IS NOT NULL);


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

CREATE UNIQUE INDEX doorbelasting_run_document_actief_uniek ON boekhouding.doorbelasting_run USING btree (document_id) WHERE (status <> ALL (ARRAY['gestorneerd'::text, 'vervallen'::text]));


--
-- Name: iban_accordering_een_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX iban_accordering_een_open_per_document ON boekhouding.iban_accordering USING btree (document_id) WHERE (status = 'open'::text);


--
-- Name: ix_accordering_laag_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_accordering_laag_administratie_id ON boekhouding.accordering_laag USING btree (administratie_id);


--
-- Name: ix_accordering_laag_afdeling_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_accordering_laag_afdeling_id ON boekhouding.accordering_laag USING btree (afdeling_id);


--
-- Name: ix_accordering_stap_accordering_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_accordering_stap_accordering_id ON boekhouding.accordering_stap USING btree (accordering_id);


--
-- Name: ix_administratie_sync_run_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_administratie_sync_run_administratie_id ON boekhouding.administratie_sync_run USING btree (administratie_id);


--
-- Name: ix_administratie_sync_run_administratie_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_administratie_sync_run_administratie_status ON boekhouding.administratie_sync_run USING btree (administratie_id, status);


--
-- Name: ix_afdeling_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_afdeling_administratie_id ON boekhouding.afdeling USING btree (administratie_id);


--
-- Name: ix_autoboek_kandidaat_stand_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_autoboek_kandidaat_stand_administratie_id ON boekhouding.autoboek_kandidaat_stand USING btree (administratie_id);


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
-- Name: ix_bank_relatie_boeking_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_relatie_boeking_administratie_id ON boekhouding.bank_relatie_boeking USING btree (administratie_id);


--
-- Name: ix_bank_relatie_boeking_entity; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_relatie_boeking_entity ON boekhouding.bank_relatie_boeking USING btree (administratie_id, entity_id, status);


--
-- Name: ix_bank_splitsing_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_splitsing_administratie_id ON boekhouding.bank_splitsing USING btree (administratie_id);


--
-- Name: ix_bank_splitsing_deel_splitsing_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_splitsing_deel_splitsing_id ON boekhouding.bank_splitsing_deel USING btree (splitsing_id);


--
-- Name: ix_bank_sync_run_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_sync_run_administratie_id ON boekhouding.bank_sync_run USING btree (administratie_id);


--
-- Name: ix_bank_sync_run_administratie_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_bank_sync_run_administratie_status ON boekhouding.bank_sync_run USING btree (administratie_id, status);


--
-- Name: ix_boeking_observatie_admin_vendor_sleutel; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_boeking_observatie_admin_vendor_sleutel ON boekhouding.boeking_observatie USING btree (administratie_id, vendor_id, regel_sleutel);


--
-- Name: ix_boekvoorstel_regel_document_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_boekvoorstel_regel_document_id ON boekhouding.boekvoorstel_regel USING btree (document_id);


--
-- Name: ix_crediteur_archiveer_werklijst_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_crediteur_archiveer_werklijst_administratie_id ON boekhouding.crediteur_archiveer_werklijst USING btree (administratie_id);


--
-- Name: ix_crediteur_dubbel_afmelding_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_crediteur_dubbel_afmelding_administratie_id ON boekhouding.crediteur_dubbel_afmelding USING btree (administratie_id);


--
-- Name: ix_crediteur_kenmerk_btw; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_crediteur_kenmerk_btw ON boekhouding.crediteur_kenmerk USING btree (administratie_id, btw_nummer);


--
-- Name: ix_crediteur_kenmerk_kvk; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_crediteur_kenmerk_kvk ON boekhouding.crediteur_kenmerk USING btree (administratie_id, kvk_nummer);


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
-- Name: ix_document_samengevoegd_in_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_samengevoegd_in_id ON boekhouding.document USING btree (samengevoegd_in_id) WHERE (samengevoegd_in_id IS NOT NULL);


--
-- Name: ix_document_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_document_status ON boekhouding.document USING btree (status);


--
-- Name: ix_doorbelasting_verdeelsleutel_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_doorbelasting_verdeelsleutel_administratie_id ON boekhouding.doorbelasting_verdeelsleutel USING btree (administratie_id);


--
-- Name: ix_dossier_document_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_dossier_document_administratie_id ON boekhouding.dossier_document USING btree (administratie_id);


--
-- Name: ix_dossier_document_veldwerker; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_dossier_document_veldwerker ON boekhouding.dossier_document USING btree (administratie_id, gebruiker_id, type_code);


--
-- Name: ix_dossier_documenttype_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_dossier_documenttype_administratie_id ON boekhouding.dossier_documenttype USING btree (administratie_id);


--
-- Name: ix_dossier_herinnering_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_dossier_herinnering_administratie_id ON boekhouding.dossier_herinnering USING btree (administratie_id);


--
-- Name: ix_duplicaat_signaal_administratie_uitkomst; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_duplicaat_signaal_administratie_uitkomst ON boekhouding.duplicaat_signaal USING btree (administratie_id, uitkomst);


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
-- Name: ix_intake_splitsing_uitsluiting_afzender_actief; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_intake_splitsing_uitsluiting_afzender_actief ON boekhouding.intake_splitsing_uitsluiting USING btree (afzender_adres) WHERE actief;


--
-- Name: ix_leverancier_werknummer_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_leverancier_werknummer_administratie_id ON boekhouding.leverancier_werknummer USING btree (administratie_id);


--
-- Name: ix_leverancier_werknummer_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_leverancier_werknummer_project ON boekhouding.leverancier_werknummer USING btree (administratie_id, project_id);


--
-- Name: ix_materiaal_bestelling_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_bestelling_administratie_id ON boekhouding.materiaal_bestelling USING btree (administratie_id);


--
-- Name: ix_materiaal_bestelling_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_bestelling_project ON boekhouding.materiaal_bestelling USING btree (administratie_id, project_id);


--
-- Name: ix_materiaal_bestelling_revisie_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_bestelling_revisie_administratie_id ON boekhouding.materiaal_bestelling_revisie USING btree (administratie_id);


--
-- Name: ix_materiaal_categorie_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_categorie_administratie_id ON boekhouding.materiaal_categorie USING btree (administratie_id);


--
-- Name: ix_materiaal_leverancier_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_leverancier_administratie_id ON boekhouding.materiaal_leverancier USING btree (administratie_id);


--
-- Name: ix_materiaal_product_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_product_administratie_id ON boekhouding.materiaal_product USING btree (administratie_id);


--
-- Name: ix_materiaal_product_leverancier; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_product_leverancier ON boekhouding.materiaal_product USING btree (leverancier_id, categorie_id, volgorde);


--
-- Name: ix_materiaal_transport_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_transport_administratie_id ON boekhouding.materiaal_transport USING btree (administratie_id);


--
-- Name: ix_materiaal_transport_datum; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_transport_datum ON boekhouding.materiaal_transport USING btree (administratie_id, datum);


--
-- Name: ix_materiaal_transport_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaal_transport_project ON boekhouding.materiaal_transport USING btree (administratie_id, project_id, datum);


--
-- Name: ix_materiaalmatch_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaalmatch_administratie_id ON boekhouding.materiaalmatch USING btree (administratie_id);


--
-- Name: ix_materiaalmatch_administratie_uitkomst; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_materiaalmatch_administratie_uitkomst ON boekhouding.materiaalmatch USING btree (administratie_id, uitkomst);


--
-- Name: ix_meerwerk_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_meerwerk_administratie_id ON boekhouding.meerwerk USING btree (administratie_id);


--
-- Name: ix_meerwerk_administratie_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_meerwerk_administratie_status ON boekhouding.meerwerk USING btree (administratie_id, status);


--
-- Name: ix_odoo_document_koppeling_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_odoo_document_koppeling_administratie_id ON boekhouding.odoo_document_koppeling USING btree (administratie_id);


--
-- Name: ix_odoo_document_koppeling_move; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_odoo_document_koppeling_move ON boekhouding.odoo_document_koppeling USING btree (company_id, odoo_move_id);


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
-- Name: ix_project_prijsafspraak_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_prijsafspraak_administratie_id ON boekhouding.project_prijsafspraak USING btree (administratie_id);


--
-- Name: ix_project_prijsafspraak_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_project_prijsafspraak_project ON boekhouding.project_prijsafspraak USING btree (administratie_id, project_id, gebruiker_id);


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
-- Name: ix_projectverdeling_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_projectverdeling_administratie_id ON boekhouding.projectverdeling USING btree (administratie_id);


--
-- Name: ix_projectverdeling_hercontrole_signaal; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_projectverdeling_hercontrole_signaal ON boekhouding.projectverdeling USING btree (administratie_id, hercontrole_afwijking_pct) WHERE ((status = 'geboekt'::text) AND (hercontrole_afwijking_pct IS NOT NULL));


--
-- Name: ix_regel_gb_classificatie_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_regel_gb_classificatie_administratie_id ON boekhouding.regel_gb_classificatie USING btree (administratie_id);


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
-- Name: ix_terugkerend_herbereken_run_aangevraagd_op; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_terugkerend_herbereken_run_aangevraagd_op ON boekhouding.terugkerend_herbereken_run USING btree (aangevraagd_op);


--
-- Name: ix_terugkerend_herbereken_run_status; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_terugkerend_herbereken_run_status ON boekhouding.terugkerend_herbereken_run USING btree (status);


--
-- Name: ix_terugkerend_signaal_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_terugkerend_signaal_administratie_id ON boekhouding.terugkerend_signaal USING btree (administratie_id);


--
-- Name: ix_uren_project_toewijzing_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_uren_project_toewijzing_administratie_id ON boekhouding.uren_project_toewijzing USING btree (administratie_id);


--
-- Name: ix_veldwerker_crediteur_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_veldwerker_crediteur_administratie_id ON boekhouding.veldwerker_crediteur USING btree (administratie_id);


--
-- Name: ix_veldwerker_dossier_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_veldwerker_dossier_administratie_id ON boekhouding.veldwerker_dossier USING btree (administratie_id);


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
-- Name: ix_vraag_bericht_vraag_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_vraag_bericht_vraag_id ON boekhouding.vraag_bericht USING btree (vraag_id);


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
-- Name: ix_werkopdracht_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkopdracht_administratie_id ON boekhouding.werkopdracht USING btree (administratie_id);


--
-- Name: ix_werkopdracht_dag_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkopdracht_dag_administratie_id ON boekhouding.werkopdracht_dag USING btree (administratie_id);


--
-- Name: ix_werkopdracht_dag_groep; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkopdracht_dag_groep ON boekhouding.werkopdracht_dag USING btree (administratie_id, groep_id, datum);


--
-- Name: ix_werkopdracht_groep; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkopdracht_groep ON boekhouding.werkopdracht USING btree (administratie_id, groep_id);


--
-- Name: ix_werkopdracht_project; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkopdracht_project ON boekhouding.werkopdracht USING btree (administratie_id, project_id, van);


--
-- Name: ix_werkstempel_administratie_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkstempel_administratie_id ON boekhouding.werkstempel USING btree (administratie_id);


--
-- Name: ix_werkstempel_gebruiker_tijdstip; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE INDEX ix_werkstempel_gebruiker_tijdstip ON boekhouding.werkstempel USING btree (gebruiker_id, tijdstip);


--
-- Name: reconciliatie_acceptatie_actief_uniek; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX reconciliatie_acceptatie_actief_uniek ON boekhouding.reconciliatie_acceptatie USING btree (administratie_id, bron, vingerafdruk) WHERE (ingetrokken_op IS NULL);


--
-- Name: uq_afdeling_actieve_naam; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX uq_afdeling_actieve_naam ON boekhouding.afdeling USING btree (administratie_id, lower(naam)) WHERE actief;


--
-- Name: uq_afdeling_terugval; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX uq_afdeling_terugval ON boekhouding.afdeling USING btree (administratie_id) WHERE is_terugval;


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

CREATE UNIQUE INDEX ux_bank_boeking_actief_per_mutatie ON boekhouding.bank_boeking USING btree (administratie_id, payment_transaction_id) WHERE ((status = 'geboekt'::text) AND (deel_id IS NULL));


--
-- Name: ux_bank_regel_actief_per_tegenpartij; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_regel_actief_per_tegenpartij ON boekhouding.bank_regel USING btree (administratie_id, tegenpartij_sleutel) WHERE actief;


--
-- Name: ux_bank_relatie_boeking_actief_per_mutatie; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_relatie_boeking_actief_per_mutatie ON boekhouding.bank_relatie_boeking USING btree (administratie_id, payment_transaction_id) WHERE ((status = ANY (ARRAY['geboekt'::text, 'verrekend'::text])) AND (deel_id IS NULL));


--
-- Name: ux_bank_splitsing_actief_per_mutatie; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_bank_splitsing_actief_per_mutatie ON boekhouding.bank_splitsing USING btree (administratie_id, payment_transaction_id) WHERE (status = ANY (ARRAY['bezig'::text, 'verwerkt'::text, 'half_verwerkt'::text]));


--
-- Name: ux_intake_bericht_message_id; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_intake_bericht_message_id ON boekhouding.intake_bericht USING btree (message_id) WHERE (message_id IS NOT NULL);


--
-- Name: ux_intake_splitsing_open_per_document; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_intake_splitsing_open_per_document ON boekhouding.intake_splitsing USING btree (bron_document_id) WHERE (status = 'voorgesteld'::text);


--
-- Name: ux_intake_splitsing_uitsluiting_actief; Type: INDEX; Schema: boekhouding; Owner: -
--

CREATE UNIQUE INDEX ux_intake_splitsing_uitsluiting_actief ON boekhouding.intake_splitsing_uitsluiting USING btree (administratie_id, afzender_adres) WHERE actief;


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
-- Name: ix_artikelcode_koppeling_administratie_id; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_artikelcode_koppeling_administratie_id ON mi.artikelcode_koppeling USING btree (administratie_id);


--
-- Name: ix_artikelgroep_administratie_id; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_artikelgroep_administratie_id ON mi.artikelgroep USING btree (administratie_id);


--
-- Name: ix_voorraad_regel_administratie_datum; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_voorraad_regel_administratie_datum ON mi.voorraad_regel USING btree (administratie_id, datum);


--
-- Name: ix_voorraad_regel_artikelcode; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_voorraad_regel_artikelcode ON mi.voorraad_regel USING btree (administratie_id, artikelcode);


--
-- Name: ix_voorraad_regel_artikelgroep_id; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_voorraad_regel_artikelgroep_id ON mi.voorraad_regel USING btree (artikelgroep_id);


--
-- Name: ix_voorraad_regel_rlz_document_id; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_voorraad_regel_rlz_document_id ON mi.voorraad_regel USING btree (rlz_document_id);


--
-- Name: ix_voorraad_telling_administratie_id; Type: INDEX; Schema: mi; Owner: -
--

CREATE INDEX ix_voorraad_telling_administratie_id ON mi.voorraad_telling USING btree (administratie_id);


--
-- Name: uq_artikelgroep_naam; Type: INDEX; Schema: mi; Owner: -
--

CREATE UNIQUE INDEX uq_artikelgroep_naam ON mi.artikelgroep USING btree (administratie_id, lower(naam)) WHERE actief;


--
-- Name: uq_voorraad_regel_rlz_regel; Type: INDEX; Schema: mi; Owner: -
--

CREATE UNIQUE INDEX uq_voorraad_regel_rlz_regel ON mi.voorraad_regel USING btree (rlz_document_id, richting, regel_volgnummer) WHERE (rlz_document_id IS NOT NULL);


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
-- Name: ix_bewaking_probe_run_gestart_op; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_bewaking_probe_run_gestart_op ON platform.bewaking_probe_run USING btree (gestart_op);


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
-- Name: uq_bewaking_storing_open_soort; Type: INDEX; Schema: platform; Owner: -
--

CREATE UNIQUE INDEX uq_bewaking_storing_open_soort ON platform.bewaking_storing USING btree (soort) WHERE (hersteld_op IS NULL);


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
-- Name: accordering_laag accordering_laag_afdeling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.accordering_laag
    ADD CONSTRAINT accordering_laag_afdeling_id_fkey FOREIGN KEY (afdeling_id) REFERENCES boekhouding.afdeling(id);


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
-- Name: administratie_sync_run administratie_sync_run_aangevraagd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.administratie_sync_run
    ADD CONSTRAINT administratie_sync_run_aangevraagd_door_fkey FOREIGN KEY (aangevraagd_door) REFERENCES platform.gebruiker(id);


--
-- Name: administratie_sync_run administratie_sync_run_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.administratie_sync_run
    ADD CONSTRAINT administratie_sync_run_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: afdeling afdeling_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afdeling
    ADD CONSTRAINT afdeling_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: afdeling afdeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afdeling
    ADD CONSTRAINT afdeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: afdeling afdeling_gearchiveerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afdeling
    ADD CONSTRAINT afdeling_gearchiveerd_door_fkey FOREIGN KEY (gearchiveerd_door) REFERENCES platform.gebruiker(id);


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
-- Name: afwijzing afwijzing_duplicaat_van_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.afwijzing
    ADD CONSTRAINT afwijzing_duplicaat_van_document_id_fkey FOREIGN KEY (duplicaat_van_document_id) REFERENCES boekhouding.document(id);


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
-- Name: autoboek_kandidaat_stand autoboek_kandidaat_stand_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.autoboek_kandidaat_stand
    ADD CONSTRAINT autoboek_kandidaat_stand_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: autoboek_kandidaat_stand autoboek_kandidaat_stand_snooze_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.autoboek_kandidaat_stand
    ADD CONSTRAINT autoboek_kandidaat_stand_snooze_door_fkey FOREIGN KEY (snooze_door) REFERENCES platform.gebruiker(id);


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
-- Name: bank_relatie_boeking bank_relatie_boeking_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_relatie_boeking
    ADD CONSTRAINT bank_relatie_boeking_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_relatie_boeking bank_relatie_boeking_geboekt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_relatie_boeking
    ADD CONSTRAINT bank_relatie_boeking_geboekt_door_fkey FOREIGN KEY (geboekt_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_relatie_boeking bank_relatie_boeking_gestorneerd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_relatie_boeking
    ADD CONSTRAINT bank_relatie_boeking_gestorneerd_door_fkey FOREIGN KEY (gestorneerd_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_splitsing bank_splitsing_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing
    ADD CONSTRAINT bank_splitsing_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_splitsing bank_splitsing_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing
    ADD CONSTRAINT bank_splitsing_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_splitsing_deel bank_splitsing_deel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing_deel
    ADD CONSTRAINT bank_splitsing_deel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: bank_splitsing_deel bank_splitsing_deel_splitsing_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_splitsing_deel
    ADD CONSTRAINT bank_splitsing_deel_splitsing_id_fkey FOREIGN KEY (splitsing_id) REFERENCES boekhouding.bank_splitsing(id);


--
-- Name: bank_sync_run bank_sync_run_aangevraagd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_sync_run
    ADD CONSTRAINT bank_sync_run_aangevraagd_door_fkey FOREIGN KEY (aangevraagd_door) REFERENCES platform.gebruiker(id);


--
-- Name: bank_sync_run bank_sync_run_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.bank_sync_run
    ADD CONSTRAINT bank_sync_run_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


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
-- Name: boekvoorstel boekvoorstel_afdeling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.boekvoorstel
    ADD CONSTRAINT boekvoorstel_afdeling_id_fkey FOREIGN KEY (afdeling_id) REFERENCES boekhouding.afdeling(id);


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
-- Name: crediteur_archiveer_werklijst crediteur_archiveer_werklijst_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_archiveer_werklijst
    ADD CONSTRAINT crediteur_archiveer_werklijst_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: crediteur_archiveer_werklijst crediteur_archiveer_werklijst_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_archiveer_werklijst
    ADD CONSTRAINT crediteur_archiveer_werklijst_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: crediteur_archiveer_werklijst crediteur_archiveer_werklijst_gedaan_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_archiveer_werklijst
    ADD CONSTRAINT crediteur_archiveer_werklijst_gedaan_door_fkey FOREIGN KEY (gedaan_door) REFERENCES platform.gebruiker(id);


--
-- Name: crediteur_dubbel_afmelding crediteur_dubbel_afmelding_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_dubbel_afmelding
    ADD CONSTRAINT crediteur_dubbel_afmelding_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: crediteur_dubbel_afmelding crediteur_dubbel_afmelding_afgemeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_dubbel_afmelding
    ADD CONSTRAINT crediteur_dubbel_afmelding_afgemeld_door_fkey FOREIGN KEY (afgemeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: crediteur_kenmerk crediteur_kenmerk_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_kenmerk
    ADD CONSTRAINT crediteur_kenmerk_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: crediteur_kenmerk crediteur_kenmerk_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.crediteur_kenmerk
    ADD CONSTRAINT crediteur_kenmerk_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


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
-- Name: document document_samengevoegd_in_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.document
    ADD CONSTRAINT document_samengevoegd_in_id_fkey FOREIGN KEY (samengevoegd_in_id) REFERENCES boekhouding.document(id);


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
-- Name: doorbelasting_verdeelsleutel doorbelasting_verdeelsleutel_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_verdeelsleutel
    ADD CONSTRAINT doorbelasting_verdeelsleutel_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: doorbelasting_verdeelsleutel doorbelasting_verdeelsleutel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_verdeelsleutel
    ADD CONSTRAINT doorbelasting_verdeelsleutel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: dossier_document dossier_document_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_document
    ADD CONSTRAINT dossier_document_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: dossier_document dossier_document_beoordeeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_document
    ADD CONSTRAINT dossier_document_beoordeeld_door_fkey FOREIGN KEY (beoordeeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: dossier_document dossier_document_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_document
    ADD CONSTRAINT dossier_document_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: dossier_document dossier_document_geupload_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_document
    ADD CONSTRAINT dossier_document_geupload_door_fkey FOREIGN KEY (geupload_door) REFERENCES platform.gebruiker(id);


--
-- Name: dossier_documenttype dossier_documenttype_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_documenttype
    ADD CONSTRAINT dossier_documenttype_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: dossier_documenttype dossier_documenttype_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_documenttype
    ADD CONSTRAINT dossier_documenttype_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: dossier_herinnering dossier_herinnering_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_herinnering
    ADD CONSTRAINT dossier_herinnering_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: dossier_herinnering dossier_herinnering_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_herinnering
    ADD CONSTRAINT dossier_herinnering_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: dossier_herinnering dossier_herinnering_verzonden_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.dossier_herinnering
    ADD CONSTRAINT dossier_herinnering_verzonden_door_fkey FOREIGN KEY (verzonden_door) REFERENCES platform.gebruiker(id);


--
-- Name: duplicaat_signaal duplicaat_signaal_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.duplicaat_signaal
    ADD CONSTRAINT duplicaat_signaal_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: duplicaat_signaal duplicaat_signaal_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.duplicaat_signaal
    ADD CONSTRAINT duplicaat_signaal_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: extractie_template extractie_template_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.extractie_template
    ADD CONSTRAINT extractie_template_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


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
-- Name: doorbelasting_run fk_doorbelasting_run_verdeelsleutel; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.doorbelasting_run
    ADD CONSTRAINT fk_doorbelasting_run_verdeelsleutel FOREIGN KEY (verdeelsleutel_id) REFERENCES boekhouding.doorbelasting_verdeelsleutel(id);


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
-- Name: materiaal_bestelling fk_materiaal_bestelling_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT fk_materiaal_bestelling_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


--
-- Name: materiaal_transport fk_materiaal_transport_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT fk_materiaal_transport_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


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
-- Name: project_prijsafspraak fk_project_prijsafspraak_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT fk_project_prijsafspraak_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


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
-- Name: werkopdracht fk_werkopdracht_project_cache; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht
    ADD CONSTRAINT fk_werkopdracht_project_cache FOREIGN KEY (project_id, administratie_id) REFERENCES boekhouding.project_cache(id, administratie_id);


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
-- Name: intake_splitsing_uitsluiting intake_splitsing_uitsluiting_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing_uitsluiting
    ADD CONSTRAINT intake_splitsing_uitsluiting_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: intake_splitsing_uitsluiting intake_splitsing_uitsluiting_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing_uitsluiting
    ADD CONSTRAINT intake_splitsing_uitsluiting_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: intake_splitsing_uitsluiting intake_splitsing_uitsluiting_verwijderd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intake_splitsing_uitsluiting
    ADD CONSTRAINT intake_splitsing_uitsluiting_verwijderd_door_fkey FOREIGN KEY (verwijderd_door) REFERENCES platform.gebruiker(id);


--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.intercompany_tegenpartij
    ADD CONSTRAINT intercompany_tegenpartij_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_afdeling leverancier_afdeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_afdeling
    ADD CONSTRAINT leverancier_afdeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: leverancier_afdeling leverancier_afdeling_afdeling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_afdeling
    ADD CONSTRAINT leverancier_afdeling_afdeling_id_fkey FOREIGN KEY (afdeling_id) REFERENCES boekhouding.afdeling(id);


--
-- Name: leverancier_afdeling leverancier_afdeling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.leverancier_afdeling
    ADD CONSTRAINT leverancier_afdeling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


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
-- Name: materiaal_bestelling materiaal_bestelling_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT materiaal_bestelling_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaal_bestelling materiaal_bestelling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT materiaal_bestelling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_bestelling materiaal_bestelling_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT materiaal_bestelling_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaal_bestelling materiaal_bestelling_leverancier_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling
    ADD CONSTRAINT materiaal_bestelling_leverancier_id_fkey FOREIGN KEY (leverancier_id) REFERENCES boekhouding.materiaal_leverancier(id);


--
-- Name: materiaal_bestelling_revisie materiaal_bestelling_revisie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie
    ADD CONSTRAINT materiaal_bestelling_revisie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_bestelling_revisie materiaal_bestelling_revisie_bestelling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie
    ADD CONSTRAINT materiaal_bestelling_revisie_bestelling_id_fkey FOREIGN KEY (bestelling_id) REFERENCES boekhouding.materiaal_bestelling(id);


--
-- Name: materiaal_bestelling_revisie materiaal_bestelling_revisie_verstuurd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_bestelling_revisie
    ADD CONSTRAINT materiaal_bestelling_revisie_verstuurd_door_fkey FOREIGN KEY (verstuurd_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaal_categorie materiaal_categorie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_categorie
    ADD CONSTRAINT materiaal_categorie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_categorie materiaal_categorie_leverancier_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_categorie
    ADD CONSTRAINT materiaal_categorie_leverancier_id_fkey FOREIGN KEY (leverancier_id) REFERENCES boekhouding.materiaal_leverancier(id);


--
-- Name: materiaal_leverancier materiaal_leverancier_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_leverancier
    ADD CONSTRAINT materiaal_leverancier_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_leverancier materiaal_leverancier_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_leverancier
    ADD CONSTRAINT materiaal_leverancier_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaal_product materiaal_product_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_product
    ADD CONSTRAINT materiaal_product_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_product materiaal_product_categorie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_product
    ADD CONSTRAINT materiaal_product_categorie_id_fkey FOREIGN KEY (categorie_id) REFERENCES boekhouding.materiaal_categorie(id);


--
-- Name: materiaal_product materiaal_product_leverancier_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_product
    ADD CONSTRAINT materiaal_product_leverancier_id_fkey FOREIGN KEY (leverancier_id) REFERENCES boekhouding.materiaal_leverancier(id);


--
-- Name: materiaal_transport materiaal_transport_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaal_transport materiaal_transport_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaal_transport materiaal_transport_bestelling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_bestelling_id_fkey FOREIGN KEY (bestelling_id) REFERENCES boekhouding.materiaal_bestelling(id);


--
-- Name: materiaal_transport materiaal_transport_leverancier_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_leverancier_id_fkey FOREIGN KEY (leverancier_id) REFERENCES boekhouding.materiaal_leverancier(id);


--
-- Name: materiaal_transport materiaal_transport_status_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaal_transport
    ADD CONSTRAINT materiaal_transport_status_gewijzigd_door_fkey FOREIGN KEY (status_gewijzigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaalmatch materiaalmatch_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaalmatch
    ADD CONSTRAINT materiaalmatch_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: materiaalmatch materiaalmatch_afwijking_bevestigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaalmatch
    ADD CONSTRAINT materiaalmatch_afwijking_bevestigd_door_fkey FOREIGN KEY (afwijking_bevestigd_door) REFERENCES platform.gebruiker(id);


--
-- Name: materiaalmatch materiaalmatch_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaalmatch
    ADD CONSTRAINT materiaalmatch_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: materiaalmatch materiaalmatch_leverancier_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.materiaalmatch
    ADD CONSTRAINT materiaalmatch_leverancier_id_fkey FOREIGN KEY (leverancier_id) REFERENCES boekhouding.materiaal_leverancier(id);


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
-- Name: odoo_document_koppeling odoo_document_koppeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_document_koppeling
    ADD CONSTRAINT odoo_document_koppeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: odoo_document_koppeling odoo_document_koppeling_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_document_koppeling
    ADD CONSTRAINT odoo_document_koppeling_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: odoo_id_koppeling odoo_id_koppeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_id_koppeling
    ADD CONSTRAINT odoo_id_koppeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: odoo_product_koppeling odoo_product_koppeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_product_koppeling
    ADD CONSTRAINT odoo_product_koppeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: odoo_product_koppeling odoo_product_koppeling_materiaal_product_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.odoo_product_koppeling
    ADD CONSTRAINT odoo_product_koppeling_materiaal_product_id_fkey FOREIGN KEY (materiaal_product_id) REFERENCES boekhouding.materiaal_product(id);


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
-- Name: project_prijsafspraak project_prijsafspraak_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT project_prijsafspraak_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: project_prijsafspraak project_prijsafspraak_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT project_prijsafspraak_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: project_prijsafspraak project_prijsafspraak_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT project_prijsafspraak_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: project_prijsafspraak project_prijsafspraak_ingetrokken_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.project_prijsafspraak
    ADD CONSTRAINT project_prijsafspraak_ingetrokken_door_fkey FOREIGN KEY (ingetrokken_door) REFERENCES platform.gebruiker(id);


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
-- Name: projectverdeling projectverdeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectverdeling
    ADD CONSTRAINT projectverdeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: projectverdeling projectverdeling_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.projectverdeling
    ADD CONSTRAINT projectverdeling_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


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
-- Name: regel_gb_classificatie regel_gb_classificatie_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.regel_gb_classificatie
    ADD CONSTRAINT regel_gb_classificatie_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: regel_gb_classificatie regel_gb_classificatie_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.regel_gb_classificatie
    ADD CONSTRAINT regel_gb_classificatie_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


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
-- Name: staande_goedkeuring staande_goedkeuring_afdeling_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.staande_goedkeuring
    ADD CONSTRAINT staande_goedkeuring_afdeling_id_fkey FOREIGN KEY (afdeling_id) REFERENCES boekhouding.afdeling(id);


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
-- Name: terugkerend_herbereken_run terugkerend_herbereken_run_gestart_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_herbereken_run
    ADD CONSTRAINT terugkerend_herbereken_run_gestart_door_fkey FOREIGN KEY (gestart_door) REFERENCES platform.gebruiker(id);


--
-- Name: terugkerend_signaal terugkerend_signaal_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_signaal
    ADD CONSTRAINT terugkerend_signaal_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: terugkerend_signaal terugkerend_signaal_afgemeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_signaal
    ADD CONSTRAINT terugkerend_signaal_afgemeld_door_fkey FOREIGN KEY (afgemeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: terugkerend_signaal terugkerend_signaal_laatste_document_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.terugkerend_signaal
    ADD CONSTRAINT terugkerend_signaal_laatste_document_id_fkey FOREIGN KEY (laatste_document_id) REFERENCES boekhouding.document(id);


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
-- Name: veldwerker_dossier veldwerker_dossier_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_dossier
    ADD CONSTRAINT veldwerker_dossier_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: veldwerker_dossier veldwerker_dossier_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_dossier
    ADD CONSTRAINT veldwerker_dossier_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: veldwerker_dossier veldwerker_dossier_kvk_bevestigd_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.veldwerker_dossier
    ADD CONSTRAINT veldwerker_dossier_kvk_bevestigd_door_fkey FOREIGN KEY (kvk_bevestigd_door) REFERENCES platform.gebruiker(id);


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
-- Name: vraag vraag_aan_de_beurt_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_aan_de_beurt_fkey FOREIGN KEY (aan_de_beurt) REFERENCES platform.gebruiker(id);


--
-- Name: vraag vraag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: vraag vraag_afgehandeld_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_afgehandeld_door_fkey FOREIGN KEY (afgehandeld_door) REFERENCES platform.gebruiker(id);


--
-- Name: vraag vraag_beantwoord_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag
    ADD CONSTRAINT vraag_beantwoord_door_fkey FOREIGN KEY (beantwoord_door) REFERENCES platform.gebruiker(id);


--
-- Name: vraag_bericht vraag_bericht_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag_bericht
    ADD CONSTRAINT vraag_bericht_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: vraag_bericht vraag_bericht_auteur_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag_bericht
    ADD CONSTRAINT vraag_bericht_auteur_id_fkey FOREIGN KEY (auteur_id) REFERENCES platform.gebruiker(id);


--
-- Name: vraag_bericht vraag_bericht_vraag_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.vraag_bericht
    ADD CONSTRAINT vraag_bericht_vraag_id_fkey FOREIGN KEY (vraag_id) REFERENCES boekhouding.vraag(id);


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
-- Name: werkopdracht werkopdracht_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht
    ADD CONSTRAINT werkopdracht_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: werkopdracht werkopdracht_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht
    ADD CONSTRAINT werkopdracht_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: werkopdracht_dag werkopdracht_dag_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht_dag
    ADD CONSTRAINT werkopdracht_dag_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: werkopdracht_dag werkopdracht_dag_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkopdracht_dag
    ADD CONSTRAINT werkopdracht_dag_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: werkstempel werkstempel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkstempel
    ADD CONSTRAINT werkstempel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: werkstempel werkstempel_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: boekhouding; Owner: -
--

ALTER TABLE ONLY boekhouding.werkstempel
    ADD CONSTRAINT werkstempel_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: artikelcode_koppeling artikelcode_koppeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelcode_koppeling
    ADD CONSTRAINT artikelcode_koppeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: artikelcode_koppeling artikelcode_koppeling_artikelgroep_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelcode_koppeling
    ADD CONSTRAINT artikelcode_koppeling_artikelgroep_id_fkey FOREIGN KEY (artikelgroep_id) REFERENCES mi.artikelgroep(id);


--
-- Name: artikelcode_koppeling artikelcode_koppeling_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelcode_koppeling
    ADD CONSTRAINT artikelcode_koppeling_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: artikelgroep artikelgroep_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelgroep
    ADD CONSTRAINT artikelgroep_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: artikelgroep artikelgroep_administratie_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.artikelgroep
    ADD CONSTRAINT artikelgroep_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: normalisatie_regel normalisatie_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.normalisatie_regel
    ADD CONSTRAINT normalisatie_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: normalisatie_regel normalisatie_regel_artikelgroep_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.normalisatie_regel
    ADD CONSTRAINT normalisatie_regel_artikelgroep_id_fkey FOREIGN KEY (artikelgroep_id) REFERENCES mi.artikelgroep(id);


--
-- Name: normalisatie_regel normalisatie_regel_bijgewerkt_door_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.normalisatie_regel
    ADD CONSTRAINT normalisatie_regel_bijgewerkt_door_fkey FOREIGN KEY (bijgewerkt_door) REFERENCES platform.gebruiker(id);


--
-- Name: voorraad_regel voorraad_regel_administratie_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_regel
    ADD CONSTRAINT voorraad_regel_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: voorraad_regel voorraad_regel_artikelgroep_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_regel
    ADD CONSTRAINT voorraad_regel_artikelgroep_id_fkey FOREIGN KEY (artikelgroep_id) REFERENCES mi.artikelgroep(id);


--
-- Name: voorraad_regel voorraad_regel_document_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_regel
    ADD CONSTRAINT voorraad_regel_document_id_fkey FOREIGN KEY (document_id) REFERENCES boekhouding.document(id);


--
-- Name: voorraad_telling voorraad_telling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_telling
    ADD CONSTRAINT voorraad_telling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


--
-- Name: voorraad_telling voorraad_telling_artikelgroep_id_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_telling
    ADD CONSTRAINT voorraad_telling_artikelgroep_id_fkey FOREIGN KEY (artikelgroep_id) REFERENCES mi.artikelgroep(id);


--
-- Name: voorraad_telling voorraad_telling_ingevoerd_door_fkey; Type: FK CONSTRAINT; Schema: mi; Owner: -
--

ALTER TABLE ONLY mi.voorraad_telling
    ADD CONSTRAINT voorraad_telling_ingevoerd_door_fkey FOREIGN KEY (ingevoerd_door) REFERENCES platform.gebruiker(id);


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
-- Name: administratie administratie_gearchiveerd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.administratie
    ADD CONSTRAINT administratie_gearchiveerd_door_fkey FOREIGN KEY (gearchiveerd_door) REFERENCES platform.gebruiker(id);


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
-- Name: autoboek_instelling autoboek_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.autoboek_instelling
    ADD CONSTRAINT autoboek_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


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
-- Name: duplicaat_afvoer_instelling duplicaat_afvoer_instelling_gewijzigd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.duplicaat_afvoer_instelling
    ADD CONSTRAINT duplicaat_afvoer_instelling_gewijzigd_door_fkey FOREIGN KEY (gewijzigd_door) REFERENCES platform.gebruiker(id);


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
-- Name: gebruiker gebruiker_gearchiveerd_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.gebruiker
    ADD CONSTRAINT gebruiker_gearchiveerd_door_fkey FOREIGN KEY (gearchiveerd_door) REFERENCES platform.gebruiker(id);


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
-- Name: kantoor_digest kantoor_digest_gebruiker_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.kantoor_digest
    ADD CONSTRAINT kantoor_digest_gebruiker_id_fkey FOREIGN KEY (gebruiker_id) REFERENCES platform.gebruiker(id);


--
-- Name: odoo_koppeling odoo_koppeling_aangemaakt_door_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.odoo_koppeling
    ADD CONSTRAINT odoo_koppeling_aangemaakt_door_fkey FOREIGN KEY (aangemaakt_door) REFERENCES platform.gebruiker(id);


--
-- Name: odoo_koppeling odoo_koppeling_administratie_id_fkey; Type: FK CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.odoo_koppeling
    ADD CONSTRAINT odoo_koppeling_administratie_id_fkey FOREIGN KEY (administratie_id) REFERENCES platform.administratie(id);


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
-- Name: administratie_sync_run; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.administratie_sync_run ENABLE ROW LEVEL SECURITY;

--
-- Name: administratie_sync_run administratie_sync_run_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY administratie_sync_run_scope ON boekhouding.administratie_sync_run USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: afdeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.afdeling ENABLE ROW LEVEL SECURITY;

--
-- Name: afdeling afdeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY afdeling_scope ON boekhouding.afdeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: afwijzing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.afwijzing ENABLE ROW LEVEL SECURITY;

--
-- Name: afwijzing afwijzing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY afwijzing_scope ON boekhouding.afwijzing USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: autoboek_kandidaat_stand; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.autoboek_kandidaat_stand ENABLE ROW LEVEL SECURITY;

--
-- Name: autoboek_kandidaat_stand autoboek_kandidaat_stand_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY autoboek_kandidaat_stand_scope ON boekhouding.autoboek_kandidaat_stand USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: bank_relatie_boeking; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_relatie_boeking ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_relatie_boeking bank_relatie_boeking_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_relatie_boeking_scope ON boekhouding.bank_relatie_boeking USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_splitsing; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_splitsing ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_splitsing_deel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_splitsing_deel ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_splitsing_deel bank_splitsing_deel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_splitsing_deel_scope ON boekhouding.bank_splitsing_deel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_splitsing bank_splitsing_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_splitsing_scope ON boekhouding.bank_splitsing USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: bank_sync_run; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.bank_sync_run ENABLE ROW LEVEL SECURITY;

--
-- Name: bank_sync_run bank_sync_run_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY bank_sync_run_scope ON boekhouding.bank_sync_run USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: crediteur_archiveer_werklijst; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.crediteur_archiveer_werklijst ENABLE ROW LEVEL SECURITY;

--
-- Name: crediteur_archiveer_werklijst crediteur_archiveer_werklijst_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY crediteur_archiveer_werklijst_scope ON boekhouding.crediteur_archiveer_werklijst USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: crediteur_dubbel_afmelding; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.crediteur_dubbel_afmelding ENABLE ROW LEVEL SECURITY;

--
-- Name: crediteur_dubbel_afmelding crediteur_dubbel_afmelding_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY crediteur_dubbel_afmelding_scope ON boekhouding.crediteur_dubbel_afmelding USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: crediteur_kenmerk; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.crediteur_kenmerk ENABLE ROW LEVEL SECURITY;

--
-- Name: crediteur_kenmerk crediteur_kenmerk_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY crediteur_kenmerk_scope ON boekhouding.crediteur_kenmerk USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: doorbelasting_verdeelsleutel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.doorbelasting_verdeelsleutel ENABLE ROW LEVEL SECURITY;

--
-- Name: doorbelasting_verdeelsleutel doorbelasting_verdeelsleutel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY doorbelasting_verdeelsleutel_scope ON boekhouding.doorbelasting_verdeelsleutel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: dossier_document; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.dossier_document ENABLE ROW LEVEL SECURITY;

--
-- Name: dossier_document dossier_document_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY dossier_document_scope ON boekhouding.dossier_document USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: dossier_documenttype; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.dossier_documenttype ENABLE ROW LEVEL SECURITY;

--
-- Name: dossier_documenttype dossier_documenttype_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY dossier_documenttype_scope ON boekhouding.dossier_documenttype USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: dossier_herinnering; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.dossier_herinnering ENABLE ROW LEVEL SECURITY;

--
-- Name: dossier_herinnering dossier_herinnering_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY dossier_herinnering_scope ON boekhouding.dossier_herinnering USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: duplicaat_signaal; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.duplicaat_signaal ENABLE ROW LEVEL SECURITY;

--
-- Name: duplicaat_signaal duplicaat_signaal_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY duplicaat_signaal_scope ON boekhouding.duplicaat_signaal USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: intake_splitsing_uitsluiting; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.intake_splitsing_uitsluiting ENABLE ROW LEVEL SECURITY;

--
-- Name: intake_splitsing_uitsluiting intake_splitsing_uitsluiting_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY intake_splitsing_uitsluiting_scope ON boekhouding.intake_splitsing_uitsluiting USING (true) WITH CHECK (true);


--
-- Name: intercompany_tegenpartij; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.intercompany_tegenpartij ENABLE ROW LEVEL SECURITY;

--
-- Name: intercompany_tegenpartij intercompany_tegenpartij_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY intercompany_tegenpartij_scope ON boekhouding.intercompany_tegenpartij USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: leverancier_afdeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.leverancier_afdeling ENABLE ROW LEVEL SECURITY;

--
-- Name: leverancier_afdeling leverancier_afdeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY leverancier_afdeling_scope ON boekhouding.leverancier_afdeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: materiaal_bestelling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_bestelling ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_bestelling_revisie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_bestelling_revisie ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_bestelling_revisie materiaal_bestelling_revisie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_bestelling_revisie_scope ON boekhouding.materiaal_bestelling_revisie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaal_bestelling materiaal_bestelling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_bestelling_scope ON boekhouding.materiaal_bestelling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaal_categorie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_categorie ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_categorie materiaal_categorie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_categorie_scope ON boekhouding.materiaal_categorie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaal_leverancier; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_leverancier ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_leverancier materiaal_leverancier_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_leverancier_scope ON boekhouding.materiaal_leverancier USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaal_product; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_product ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_product materiaal_product_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_product_scope ON boekhouding.materiaal_product USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaal_transport; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaal_transport ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaal_transport materiaal_transport_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaal_transport_scope ON boekhouding.materiaal_transport USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: materiaalmatch; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.materiaalmatch ENABLE ROW LEVEL SECURITY;

--
-- Name: materiaalmatch materiaalmatch_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY materiaalmatch_scope ON boekhouding.materiaalmatch USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: meerwerk; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.meerwerk ENABLE ROW LEVEL SECURITY;

--
-- Name: meerwerk meerwerk_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY meerwerk_scope ON boekhouding.meerwerk USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: odoo_document_koppeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.odoo_document_koppeling ENABLE ROW LEVEL SECURITY;

--
-- Name: odoo_document_koppeling odoo_document_koppeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY odoo_document_koppeling_scope ON boekhouding.odoo_document_koppeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: odoo_id_koppeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.odoo_id_koppeling ENABLE ROW LEVEL SECURITY;

--
-- Name: odoo_id_koppeling odoo_id_koppeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY odoo_id_koppeling_scope ON boekhouding.odoo_id_koppeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: odoo_product_koppeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.odoo_product_koppeling ENABLE ROW LEVEL SECURITY;

--
-- Name: odoo_product_koppeling odoo_product_koppeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY odoo_product_koppeling_scope ON boekhouding.odoo_product_koppeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: project_prijsafspraak; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.project_prijsafspraak ENABLE ROW LEVEL SECURITY;

--
-- Name: project_prijsafspraak project_prijsafspraak_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY project_prijsafspraak_scope ON boekhouding.project_prijsafspraak USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: projectverdeling; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.projectverdeling ENABLE ROW LEVEL SECURITY;

--
-- Name: projectverdeling projectverdeling_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY projectverdeling_scope ON boekhouding.projectverdeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: reconciliatie_acceptatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.reconciliatie_acceptatie ENABLE ROW LEVEL SECURITY;

--
-- Name: reconciliatie_acceptatie reconciliatie_acceptatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY reconciliatie_acceptatie_scope ON boekhouding.reconciliatie_acceptatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: regel_gb_classificatie; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.regel_gb_classificatie ENABLE ROW LEVEL SECURITY;

--
-- Name: regel_gb_classificatie regel_gb_classificatie_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY regel_gb_classificatie_scope ON boekhouding.regel_gb_classificatie USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: terugkerend_signaal; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.terugkerend_signaal ENABLE ROW LEVEL SECURITY;

--
-- Name: terugkerend_signaal terugkerend_signaal_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY terugkerend_signaal_scope ON boekhouding.terugkerend_signaal USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: veldwerker_dossier; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.veldwerker_dossier ENABLE ROW LEVEL SECURITY;

--
-- Name: veldwerker_dossier veldwerker_dossier_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY veldwerker_dossier_scope ON boekhouding.veldwerker_dossier USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: vraag_bericht; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.vraag_bericht ENABLE ROW LEVEL SECURITY;

--
-- Name: vraag_bericht vraag_bericht_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY vraag_bericht_scope ON boekhouding.vraag_bericht USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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
-- Name: werkopdracht; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.werkopdracht ENABLE ROW LEVEL SECURITY;

--
-- Name: werkopdracht_dag; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.werkopdracht_dag ENABLE ROW LEVEL SECURITY;

--
-- Name: werkopdracht_dag werkopdracht_dag_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY werkopdracht_dag_scope ON boekhouding.werkopdracht_dag USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: werkopdracht werkopdracht_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY werkopdracht_scope ON boekhouding.werkopdracht USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: werkstempel; Type: ROW SECURITY; Schema: boekhouding; Owner: -
--

ALTER TABLE boekhouding.werkstempel ENABLE ROW LEVEL SECURITY;

--
-- Name: werkstempel werkstempel_scope; Type: POLICY; Schema: boekhouding; Owner: -
--

CREATE POLICY werkstempel_scope ON boekhouding.werkstempel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: artikelcode_koppeling; Type: ROW SECURITY; Schema: mi; Owner: -
--

ALTER TABLE mi.artikelcode_koppeling ENABLE ROW LEVEL SECURITY;

--
-- Name: artikelcode_koppeling artikelcode_koppeling_scope; Type: POLICY; Schema: mi; Owner: -
--

CREATE POLICY artikelcode_koppeling_scope ON mi.artikelcode_koppeling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: artikelgroep; Type: ROW SECURITY; Schema: mi; Owner: -
--

ALTER TABLE mi.artikelgroep ENABLE ROW LEVEL SECURITY;

--
-- Name: artikelgroep artikelgroep_scope; Type: POLICY; Schema: mi; Owner: -
--

CREATE POLICY artikelgroep_scope ON mi.artikelgroep USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: normalisatie_regel; Type: ROW SECURITY; Schema: mi; Owner: -
--

ALTER TABLE mi.normalisatie_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: normalisatie_regel normalisatie_regel_scope; Type: POLICY; Schema: mi; Owner: -
--

CREATE POLICY normalisatie_regel_scope ON mi.normalisatie_regel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: voorraad_regel; Type: ROW SECURITY; Schema: mi; Owner: -
--

ALTER TABLE mi.voorraad_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: voorraad_regel voorraad_regel_scope; Type: POLICY; Schema: mi; Owner: -
--

CREATE POLICY voorraad_regel_scope ON mi.voorraad_regel USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


--
-- Name: voorraad_telling; Type: ROW SECURITY; Schema: mi; Owner: -
--

ALTER TABLE mi.voorraad_telling ENABLE ROW LEVEL SECURITY;

--
-- Name: voorraad_telling voorraad_telling_scope; Type: POLICY; Schema: mi; Owner: -
--

CREATE POLICY voorraad_telling_scope ON mi.voorraad_telling USING ((administratie_id = platform.current_administratie_id())) WITH CHECK ((administratie_id = platform.current_administratie_id()));


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


