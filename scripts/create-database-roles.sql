-- Least-privilege runtime roles (US-42, chunk 26D).
--
-- Run once per environment, as a superuser, before the first deploy. It is
-- idempotent: re-running grants the same rights again rather than failing.
--
-- The separation that matters is `damdam_app` from `damdam_migrate`. The
-- application connects as a role that cannot issue DDL, so "no schema changes
-- at runtime" is enforced by the database rather than by everyone remembering.
-- A compromised application credential cannot drop a table, and — the more
-- insidious case — cannot TRUNCATE one and leave the schema looking intact.
--
-- Passwords are NOT set here. Supply them out of band; a password in a file in
-- a repository is not a credential, it is a published string.

\set ON_ERROR_STOP on

-- --- roles -----------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'damdam_migrate') THEN
        CREATE ROLE damdam_migrate LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'damdam_app') THEN
        CREATE ROLE damdam_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'damdam_readonly') THEN
        CREATE ROLE damdam_readonly LOGIN;
    END IF;
END
$$;

-- --- schema ownership ------------------------------------------------------

-- Alembic needs to create, alter and drop. Nothing serving a request does.
ALTER SCHEMA public OWNER TO damdam_migrate;
GRANT USAGE ON SCHEMA public TO damdam_app, damdam_readonly;

-- Revoke the implicit public grant before granting anything deliberately.
-- Without this, PUBLIC retains CREATE on `public` in older clusters and the
-- whole exercise is decorative.
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- Adopting these roles in an existing environment must also move existing
-- objects. Owning only the schema lets Alembic create the *next* table but does
-- not let it alter a table owned by the role used for earlier deployments.
-- Indexes and table-owned sequences follow their parent table; standalone
-- sequences, views and materialized views have independent owners and are
-- transferred explicitly.
DO $$
DECLARE
    object record;
BEGIN
    FOR object IN
        SELECT c.relkind, n.nspname, c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
          AND (
              c.relkind <> 'S'
              OR NOT EXISTS (
                  SELECT 1
                  FROM pg_depend AS d
                  WHERE d.classid = 'pg_class'::regclass
                    AND d.objid = c.oid
                    AND d.refclassid = 'pg_class'::regclass
                    AND d.deptype IN ('a', 'i')
              )
          )
        -- Tables must move before views that depend on them. Standalone
        -- sequences can move at either point; keeping them last is clearer.
        ORDER BY CASE c.relkind
            WHEN 'r' THEN 1
            WHEN 'p' THEN 1
            WHEN 'v' THEN 2
            WHEN 'm' THEN 2
            ELSE 3
        END
    LOOP
        IF object.relkind = 'S' THEN
            EXECUTE format(
                'ALTER SEQUENCE %I.%I OWNER TO damdam_migrate',
                object.nspname, object.relname
            );
        ELSIF object.relkind = 'v' THEN
            EXECUTE format(
                'ALTER VIEW %I.%I OWNER TO damdam_migrate',
                object.nspname, object.relname
            );
        ELSIF object.relkind = 'm' THEN
            EXECUTE format(
                'ALTER MATERIALIZED VIEW %I.%I OWNER TO damdam_migrate',
                object.nspname, object.relname
            );
        ELSE
            EXECUTE format(
                'ALTER TABLE %I.%I OWNER TO damdam_migrate',
                object.nspname, object.relname
            );
        END IF;
    END LOOP;
END
$$;

-- PostgreSQL enum and domain types are schema objects too. A later Alembic
-- migration cannot rename or extend a type retained by the former deploy role.
DO $$
DECLARE
    object record;
BEGIN
    FOR object IN
        SELECT t.typtype, n.nspname, t.typname
        FROM pg_type AS t
        JOIN pg_namespace AS n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public'
          AND t.typtype IN ('d', 'e')
    LOOP
        IF object.typtype = 'd' THEN
            EXECUTE format(
                'ALTER DOMAIN %I.%I OWNER TO damdam_migrate',
                object.nspname, object.typname
            );
        ELSE
            EXECUTE format(
                'ALTER TYPE %I.%I OWNER TO damdam_migrate',
                object.nspname, object.typname
            );
        END IF;
    END LOOP;
END
$$;

-- --- the application role: data, never structure ---------------------------

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO damdam_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO damdam_app;

-- Tables created by future migrations get the same rights without anyone
-- remembering to re-run this.
ALTER DEFAULT PRIVILEGES FOR ROLE damdam_migrate IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO damdam_app;
ALTER DEFAULT PRIVILEGES FOR ROLE damdam_migrate IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO damdam_app;

-- --- the read-only role: for metrics and support ---------------------------

GRANT SELECT ON ALL TABLES IN SCHEMA public TO damdam_readonly;

-- Deliberately no default SELECT grant for read-only. A future migration may
-- create another credential or privacy-sensitive table; automatically exposing
-- it until this script is rerun would make least privilege depend on deployment
-- timing. Re-run this reviewed script to grant new tables explicitly.

-- Sealed activation material is one-time-use customer property. A read-only
-- credential is the one most likely to be shared with a dashboard, a notebook
-- or a contractor, so it is denied the table outright rather than trusted not
-- to select from it. The ciphertext is useless without the key, but "useless
-- without the key" is an argument, and this is a permission.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'esim_activation_credentials'
    ) THEN
        EXECUTE 'REVOKE ALL ON TABLE public.esim_activation_credentials FROM damdam_readonly';
    END IF;
END
$$;

-- --- what is deliberately absent -------------------------------------------
--
-- No SUPERUSER, no CREATEDB, no CREATEROLE, no BYPASSRLS on any of the three.
-- No role may TRUNCATE: it is not included in the grant above, and a TRUNCATE
-- on `journal_lines` would destroy the ledger while leaving every table in
-- place and every schema check passing.
