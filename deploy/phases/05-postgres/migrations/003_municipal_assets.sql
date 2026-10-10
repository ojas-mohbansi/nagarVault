-- 003 — municipal_assets: the municipal asset registry the officer console's ledger renders.
-- (ADR-034. Idempotent by construction, invariant I-2: every statement below is either
-- `CREATE ... IF NOT EXISTS`, an `ALTER`/`GRANT` that is naturally idempotent, or an
-- `INSERT ... ON CONFLICT DO NOTHING`. The migration Job replays every file in
-- migrations/ on each sync where its spec changes and after every restore; re-running
-- this file converges with no error and no change to existing rows.)
--
-- WHY THIS EXISTS. The officer console (Phase 7g) renders a "Municipal Asset Ledger" whose
-- columns were, until now, invented in the design: the mock held hard-coded rows for a table
-- (`municipal_assets`) that no migration created. Rendering a console against a table that
-- does not exist is the failure mode AGENTS §6.3 forbids in documentation and the console
-- equivalent of it: the officer reads confident column headers backed by nothing. Either the
-- console drops the ledger or the ledger gets a real table. ADR-034 records that decision,
-- taken with owner approval, and this migration is its schema half.
--
-- Deliberate I-9 exception: this is a Phase 7g console deliverable landing in the Phase 5
-- subtree, because the Phase-5 migration Job is the only sanctioned way schema reaches
-- `nagardb` (ADR-019 §6 established the location; ADR-030 set the precedent for a later
-- phase's need landing here). Recorded in ADR-034 with owner approval, like ADR-030 before it.
--
-- SHAPE: a REGISTRY table, not an event table. The five department tables in 001 all carry the
-- ingestion envelope (event_id, source_system + source_record_id, occurred_at, ingested_at,
-- payload) because rows arrive as events over Kafka and deduplicate on that pair. A physical
-- asset is not an event: it is one row per asset that is updated in place, keyed by the
-- municipal asset identifier. So the envelope columns are deliberately absent, and the key is
-- `asset_id` — the same "text natural key" shape `users.user_id` already uses in 001. What the
-- table does share with the rest of the warehouse: it is owned by `nagar`, it follows the
-- snake_case plural naming rule (CONVENTIONS §5), and it carries no PII columns at all.
--
-- WRITER: there is none in the ingestion path, and that is stated rather than implied. No
-- topic in the frozen registry (CONVENTIONS §4) maps to this table and enrichWorker has no
-- department for it (worker/enrich.py), so nothing upserts here yet. The fixture rows below are
-- therefore the only rows, they are demo data, and `source_system` provenance cannot be
-- recorded without inventing an envelope. Closing that gap means an ingestion path for asset
-- registry updates, which is a topic + enrichWorker change and an ADR of its own. ADR-034
-- records the limitation.
--
-- CONSOLE COLUMN MAP (the Phase 7g ledger reads these, and only these):
--   ASSET ID        <- asset_id
--   WARD / SECTOR   <- ward, sector
--   COMPONENT TYPE  <- component_type, with component_detail as the sub-line
--   GRID REFERENCE  <- grid_lat, grid_lon
--   STATUS MANIFEST <- status
--   LAST EPOCH      <- updated_at (row recency), with last_inspected_at as the inspection date
--
-- `status` is a controlled vocabulary, documented here rather than enforced with a CHECK
-- constraint: a CHECK would turn an unexpected value from a future ingestion path into a
-- failed upsert (silent data loss), whereas a documented list is visible to the SLM's schema
-- retrieval and to operators. Values: UNVERIFIED, FLAGGED_TRIAGE, PENDING_CREW, INSPECTED.

CREATE TABLE IF NOT EXISTS municipal_assets (
  asset_id          text        PRIMARY KEY,                -- e.g. 'VALV-702' (municipal identifier)
  ward              text        NOT NULL,                   -- free text, same convention as nmc_complaints.ward
  sector            text,                                   -- sub-ward sector label, e.g. 'SEC-3A'
  component_type    text        NOT NULL,                   -- e.g. 'Sluice Gate A', 'Butterfly Valve'
  component_detail  text,                                   -- model/spec line, e.g. 'DN-400 high-pressure main'
  grid_lat          numeric(9, 6),
  grid_lon          numeric(9, 6),
  status            text        NOT NULL,                   -- UNVERIFIED | FLAGGED_TRIAGE | PENDING_CREW | INSPECTED
  last_inspected_at timestamptz,                            -- NULL until a crew has inspected the asset
  installed_at      timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Access patterns: the console filters by ward and status ("uninspected valves in Ward 7")
-- and breaks down by component type.
CREATE INDEX IF NOT EXISTS municipal_assets_ward_status_idx    ON municipal_assets (ward, status);
CREATE INDEX IF NOT EXISTS municipal_assets_component_type_idx ON municipal_assets (component_type);

-- Ownership follows 001: the objects belong to the service role, not to the superuser the
-- migration Job connects as. queryService runs SET ROLE before every statement, so it is the
-- officer projection role's grant below that actually applies to officer SQL.
ALTER TABLE IF EXISTS municipal_assets OWNER TO nagar;

-- Grants model (SECURITY §3, "second wall"): `nagar` is already a member of both officer roles
-- (001), so SET ROLE works without touching membership here.
--
-- nmc_officer ONLY. The console's officer role is nmc_officer, and the registry carries no
-- restricted class, so the table-level SELECT that 001 uses for the four civic tables is the
-- right shape (unlike nmc_complaints, which needed column-level grants in 002 because it
-- carries PII). health_officer deliberately gets no grant: nothing in the health workflow reads
-- the asset registry, and SECURITY §3's posture is least privilege per role. Widening this is a
-- one-line grant plus the ROLE_TABLES entry in queryService, and it is recorded in ADR-034 as a
-- deliberate narrowing so a future reader does not mistake it for an oversight.
GRANT SELECT ON municipal_assets TO nmc_officer;

-- ---------------------------------------------------------------------------
-- Fixture rows (demo data — see the WRITER note above)
-- ---------------------------------------------------------------------------
-- Relative timestamps (`now() - interval ...`) rather than fixed dates so a freshly built
-- cluster's ledger reads as recent operating state instead of four-year-old history.
-- `ON CONFLICT (asset_id) DO NOTHING` is what makes this converge: the second and every later
-- replay inserts nothing and touches no existing row. The consequence, stated plainly: these
-- eight fixtures are reasserted by convergence, so deleting one by hand brings it back on the
-- next migration run. That is intended for demo data and would be wrong for real rows — the
-- reason the WRITER gap above has to be closed by an ingestion path rather than by growing
-- this list.
INSERT INTO municipal_assets
  (asset_id, ward, sector, component_type, component_detail, grid_lat, grid_lon,
   status, last_inspected_at, installed_at, updated_at)
VALUES
  ('VALV-702', 'W-07', 'SEC-3A', 'Sluice Gate A', 'DN-400 high-pressure main',
   19.076000, 72.877700, 'UNVERIFIED', NULL, '2018-03-12T00:00:00Z', now() - interval '2 days'),
  ('VALV-789', 'W-07', 'SEC-1F', 'Distribution Main', 'Primary feed trunk 12 inch',
   19.081200, 72.883400, 'FLAGGED_TRIAGE', NULL, '2016-11-04T00:00:00Z', now() - interval '1 day'),
  ('VALV-714', 'W-07', 'SEC-2B', 'Butterfly Valve', 'Hydraulic actuator C',
   19.073400, 72.871100, 'PENDING_CREW', NULL, '2020-06-23T00:00:00Z', now() - interval '22 hours'),
  ('VALV-740', 'W-07', 'SEC-4D', 'Pressure Relief Valve', 'Surge chamber unit 2',
   19.088900, 72.879500, 'UNVERIFIED', NULL, '2019-09-30T00:00:00Z', now() - interval '8 hours'),
  ('VALV-765', 'W-07', 'SEC-1A', 'Drain Off-take', 'Storm overflow bypass',
   19.069900, 72.868000, 'PENDING_CREW', NULL, '2021-07-19T00:00:00Z', now() - interval '35 minutes'),
  ('FLTR-052', 'W-07', 'SEC-3C', 'Filter Bed', 'Rapid gravity filter bed 2',
   19.079800, 72.880900, 'FLAGGED_TRIAGE', NULL, '2015-02-17T00:00:00Z', now() - interval '3 days'),
  ('VALV-803', 'W-12', 'SEC-2C', 'Isolation Valve', 'Ward boundary stop valve',
   19.104500, 72.893200, 'INSPECTED', now() - interval '5 days', '2017-05-08T00:00:00Z',
   now() - interval '5 days'),
  ('PMP-118',  'W-12', 'SEC-1D', 'Booster Pump', 'Booster pump house 4',
   19.110200, 72.901400, 'INSPECTED', now() - interval '12 days', '2014-08-21T00:00:00Z',
   now() - interval '12 days')
ON CONFLICT (asset_id) DO NOTHING;
