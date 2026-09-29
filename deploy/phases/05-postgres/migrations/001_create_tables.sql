-- NagarVault warehouse schema — migration 001 (Phase 5, PHASES.md §2 Phase 5).
--
-- IDEMPOTENT BY CONSTRUCTION (invariant I-2): every statement below is either
-- `CREATE ... IF NOT EXISTS`, a `DO` block guarded on a catalog lookup, or a `GRANT`
-- (which is naturally idempotent). The migration Job re-runs this file on every sync
-- where its spec changes and after every restore; re-running it against a populated
-- database is a no-op that changes nothing and prints no errors.
--
-- PROVENANCE: this file is authored fresh in Phase 5. ARCHITECTURE §3.3 named the path
-- `enrichWorker/migrations/001_create_tables.sql`, but the service tree was removed before
-- the mission began and ADR-013 forbids restoring it, so the warehouse schema — a Phase 5
-- deliverable per PHASES.md §2 — lives in the phase subtree that owns the relational store
-- and is delivered to the database by this phase's migration Job. See ADR-019 §6.
--
-- COLUMN CONTRACT (sources: ARCHITECTURE §3.2/§3.3/§4.3, SECURITY §2/§3/§9, OPERATIONS §11):
--   * `users`        — authService credential store (argon2id hashes, SECURITY §2).
--   * `sessions`     — server-side session/`jti` revocation store (SECURITY §2).
--   * `audit_logs`   — every SQL attempt, allowed or blocked (SECURITY §9: actor, role, SQL,
--                      verdict, block reason, rows, client IP, time).
--   * five department tables — enriched civic events; deduplicated on the
--                      `source_system + source_record_id` pair that ARCHITECTURE §3.2 makes
--                      the ingestion idempotency key, so an at-least-once Kafka redelivery
--                      upserts rather than duplicates.
--   * PII columns in `nmc_complaints` are declared with exactly the names the queryService
--     denylist matches (`name, phone, email, address, aadhaar`, ARCHITECTURE §3.4) so the
--     column-level guard and the storage layer agree.
--
-- Grants model (SECURITY §3.3, "second wall"): the service role `nagar` owns the objects and
-- has full DML; the two officer projection roles are NOLOGIN and hold SELECT only on the
-- tables their JWT role permits, with no grant at all on `users`, `sessions` or `audit_logs`.
-- `nagar` is made a member of both officer roles so queryService can activate the database
-- wall with `SET ROLE` before executing officer-supplied SQL (Phase 7b). The JWT role
-- `ROLE_HEALTH_OFFICER` maps to the PostgreSQL role `health_officer` (PostgreSQL folds
-- unquoted identifiers to lower case, so the wire constant is not a legal role name as-is).

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------
-- CREATE ROLE has no IF NOT EXISTS form; the guard is a catalog lookup.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nmc_officer') THEN
    CREATE ROLE nmc_officer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'health_officer') THEN
    CREATE ROLE health_officer NOLOGIN;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Auth, session and audit tables (schema owned by the `nagar` service role)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  user_id       text        PRIMARY KEY,
  username      text        NOT NULL UNIQUE,
  password_hash text        NOT NULL,                       -- argon2id, never plaintext
  role          text        NOT NULL,                       -- nmc_officer | ROLE_HEALTH_OFFICER | admin
  is_active     boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Server-side revocation list. A row whose `revoked_at` is set is a denylisted jti;
-- expiry pruning is a maintenance concern, not a correctness one.
CREATE TABLE IF NOT EXISTS sessions (
  jti        text        PRIMARY KEY,
  user_id    text        NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  issued_at  timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);

-- Full audit trail: written for every attempt, including blocked ones (ARCHITECTURE §3.4).
CREATE TABLE IF NOT EXISTS audit_logs (
  id           bigserial   PRIMARY KEY,
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  actor        text,
  role         text,
  query_sql    text,                                        -- the SQL as received
  verdict      text        NOT NULL,                        -- allowed | blocked
  block_reason text,                                        -- e.g. pii-column, table-rbac, non-select
  row_count    integer,
  client_ip    inet,
  source       text                                         -- queryService | slmService | adminService
);

-- ---------------------------------------------------------------------------
-- Department tables (enriched civic events)
-- ---------------------------------------------------------------------------
-- Shared envelope columns: event_id (ingestion-assigned), source_system + source_record_id
-- (the §3.2 duplicate key), occurred_at (source event time), ingested_at (warehouse arrival),
-- payload (the normalised event as received, retained for re-derivation), and the media
-- reference pair (bucket + object key) for events that carry attachments — never media bytes
-- (§3.2 invariant).

-- Citizen complaints. Restricted class: carries PII columns.
CREATE TABLE IF NOT EXISTS nmc_complaints (
  id               bigserial   PRIMARY KEY,
  event_id         text        NOT NULL UNIQUE,
  source_system    text        NOT NULL,
  source_record_id text        NOT NULL,
  occurred_at      timestamptz NOT NULL,
  ingested_at      timestamptz NOT NULL DEFAULT now(),
  ward             text,
  category         text,
  status           text,
  description      text,
  name             text,                                    -- PII (denylist)
  phone            text,                                    -- PII (denylist)
  email            text,                                    -- PII (denylist)
  address          text,                                    -- PII (denylist)
  aadhaar          text,                                    -- PII (denylist)
  media_bucket     text,
  media_object_key text,
  payload          jsonb       NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_system, source_record_id)
);

CREATE TABLE IF NOT EXISTS traffic_events (
  id               bigserial   PRIMARY KEY,
  event_id         text        NOT NULL UNIQUE,
  source_system    text        NOT NULL,
  source_record_id text        NOT NULL,
  occurred_at      timestamptz NOT NULL,
  ingested_at      timestamptz NOT NULL DEFAULT now(),
  junction         text,
  corridor         text,
  direction        text,
  event_type       text,                                    -- congestion | incident | signal_fault
  severity         text,
  vehicle_count    integer,
  average_speed    numeric(6, 2),
  media_bucket     text,
  media_object_key text,
  payload          jsonb       NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_system, source_record_id)
);

CREATE TABLE IF NOT EXISTS water_sensor_readings (
  id               bigserial     PRIMARY KEY,
  event_id         text          NOT NULL UNIQUE,
  source_system    text          NOT NULL,
  source_record_id text          NOT NULL,
  occurred_at      timestamptz   NOT NULL,
  ingested_at      timestamptz   NOT NULL DEFAULT now(),
  sensor_id        text          NOT NULL,
  parameter        text          NOT NULL,                  -- ph | turbidity | tds | flow | level
  value            numeric(12, 4),
  unit             text,
  quality_flag     text,
  payload          jsonb         NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_system, source_record_id)
);

-- Health camp records. Restricted class: only ROLE_HEALTH_OFFICER may read these
-- (ARCHITECTURE §3.4, SECURITY §3). Patient identity is kept as a camp-local reference, not
-- the PII column names the denylist matches, so a health officer can still aggregate.
CREATE TABLE IF NOT EXISTS health_camp_records (
  id               bigserial   PRIMARY KEY,
  event_id         text        NOT NULL UNIQUE,
  source_system    text        NOT NULL,
  source_record_id text        NOT NULL,
  occurred_at      timestamptz NOT NULL,
  ingested_at      timestamptz NOT NULL DEFAULT now(),
  camp_id          text,
  patient_ref      text,
  age_band         text,
  sex              text,
  screening_type   text,
  diagnosis        text,
  referral         text,
  payload          jsonb       NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_system, source_record_id)
);

CREATE TABLE IF NOT EXISTS ev_bus_telemetry (
  id               bigserial     PRIMARY KEY,
  event_id         text          NOT NULL UNIQUE,
  source_system    text          NOT NULL,
  source_record_id text          NOT NULL,
  occurred_at      timestamptz   NOT NULL,
  ingested_at      timestamptz   NOT NULL DEFAULT now(),
  bus_id           text          NOT NULL,
  route_id         text,
  latitude         numeric(9, 6),
  longitude        numeric(9, 6),
  speed_kph        numeric(6, 2),
  state_of_charge  numeric(5, 2),
  payload          jsonb         NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_system, source_record_id)
);

-- ---------------------------------------------------------------------------
-- Indexes for the access patterns the officer queries actually use
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS nmc_complaints_occurred_at_idx   ON nmc_complaints (occurred_at DESC);
CREATE INDEX IF NOT EXISTS nmc_complaints_ward_idx          ON nmc_complaints (ward);
CREATE INDEX IF NOT EXISTS traffic_events_occurred_at_idx   ON traffic_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS traffic_events_junction_idx      ON traffic_events (junction);
CREATE INDEX IF NOT EXISTS water_readings_sensor_time_idx   ON water_sensor_readings (sensor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS health_camp_records_camp_idx     ON health_camp_records (camp_id);
CREATE INDEX IF NOT EXISTS ev_bus_telemetry_bus_time_idx    ON ev_bus_telemetry (bus_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS sessions_user_idx                ON sessions (user_id);
CREATE INDEX IF NOT EXISTS audit_logs_occurred_at_idx       ON audit_logs (occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_actor_idx             ON audit_logs (actor);

-- ---------------------------------------------------------------------------
-- Ownership: the warehouse objects belong to the service role, not to the
-- superuser the migration Job connects as (see the Job's header note).
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS users                 OWNER TO nagar;
ALTER TABLE IF EXISTS sessions              OWNER TO nagar;
ALTER TABLE IF EXISTS audit_logs            OWNER TO nagar;
ALTER TABLE IF EXISTS nmc_complaints        OWNER TO nagar;
ALTER TABLE IF EXISTS traffic_events        OWNER TO nagar;
ALTER TABLE IF EXISTS water_sensor_readings OWNER TO nagar;
ALTER TABLE IF EXISTS health_camp_records   OWNER TO nagar;
ALTER TABLE IF EXISTS ev_bus_telemetry      OWNER TO nagar;
-- bigserial sequences follow their table's ownership automatically, so the OWNER TO above
-- covers them; no separate sequence statement is needed (or wanted).

-- ---------------------------------------------------------------------------
-- Grants — the database-level half of the SECURITY §3 role matrix
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO nagar, nmc_officer, health_officer;

-- nmc_officer: civic tables only, never health records (SECURITY §3).
GRANT SELECT ON nmc_complaints, traffic_events, water_sensor_readings, ev_bus_telemetry
  TO nmc_officer;

-- health_officer: the above plus health records — the only role that may touch them.
GRANT SELECT ON nmc_complaints, traffic_events, water_sensor_readings, ev_bus_telemetry,
  health_camp_records TO health_officer;

-- No grant of any kind on users, sessions or audit_logs to either officer role: those are
-- reachable only through adminService (SECURITY §3) and the service role.

-- queryService activates the wall with SET ROLE (Phase 7b); membership is what makes that
-- possible while the service keeps connecting as `nagar`.
GRANT nmc_officer TO nagar;
GRANT health_officer TO nagar;
