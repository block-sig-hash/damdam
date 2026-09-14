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
ALTER DEFAULT PRIVILEGES FOR ROLE damdam_migrate IN SCHEMA public
    GRANT SELECT ON TABLES TO damdam_readonly;

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
