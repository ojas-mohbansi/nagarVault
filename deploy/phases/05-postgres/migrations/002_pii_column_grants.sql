-- 002 — column-level SELECT grants so the PII denylist has a database-level backstop
-- (ADR-030). Idempotent (invariant I-2): the migration Job replays every file in
-- migrations/ on each Argo sync, so this must converge no matter how often it runs.
--
-- WHY THIS EXISTS. 001 grants SELECT at TABLE level on nmc_complaints, which means the
-- database would happily return name, phone, email, address and aadhaar to any role
-- holding that grant. The only thing preventing PII disclosure was queryService's AST
-- gate (SECURITY §3 layer 4), and a whole-row reference (`SELECT c FROM nmc_complaints c`,
-- `to_jsonb(c)`, ...) walked straight past a denylist that matched column NAMES. Two
-- independent layers are the posture SECURITY §3 asks for: the AST gate stops the query
-- from being formed, these grants stop the column from being returned if it ever is.
--
-- Deliberate I-9 exception: this is a Phase 7b security fix landing in the Phase 5
-- subtree. Recorded in ADR-030 with owner approval.
--
-- The grant list is derived from the catalog rather than hardcoded, so a non-PII column
-- added to the DDL later is granted automatically and a column renamed to a denylisted
-- name is excluded automatically. `nagar` owns the table and queryService runs
-- `SET ROLE` before every statement, so the officer roles' grants are what apply.

DO $$
DECLARE
    grantable text;
BEGIN
    IF to_regclass('public.nmc_complaints') IS NULL THEN
        RAISE NOTICE 'nmc_complaints absent; nothing to restrict';
        RETURN;
    END IF;

    SELECT string_agg(format('%I', column_name), ', ' ORDER BY ordinal_position)
      INTO grantable
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'nmc_complaints'
       AND column_name <> ALL (ARRAY['name', 'phone', 'email', 'address', 'aadhaar']);

    IF grantable IS NULL THEN
        RAISE NOTICE 'nmc_complaints has no grantable columns; refusing to leave it open';
        RAISE EXCEPTION 'refusing to grant SELECT on a fully-PII table';
    END IF;

    EXECUTE format('REVOKE ALL ON TABLE nmc_complaints FROM nmc_officer, health_officer');
    EXECUTE format('GRANT SELECT (%s) ON TABLE nmc_complaints TO nmc_officer', grantable);
    EXECUTE format('GRANT SELECT (%s) ON TABLE nmc_complaints TO health_officer', grantable);

    RAISE NOTICE 'nmc_complaints: table-level SELECT revoked, % non-PII columns granted',
        (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'nmc_complaints'
            AND column_name <> ALL (ARRAY['name','phone','email','address','aadhaar']));
END
$$;
