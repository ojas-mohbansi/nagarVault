# queryService test suite — Phase 7b (hermetic; no database, no network).
#
# CONTRACT UNDER TEST (ARCHITECTURE §4.1 `POST /query` JWT + role RBAC; ARCHITECTURE §3.4
# guardrails; SECURITY §3 layered authorization; Phase-5 DDL audit_logs + officer grant roles):
#   * SELECT-only AST gate via sqlglot (multi-statement, DML/DDL all rejected)
#   * per-role table RBAC: nmc_officer -> 4 civic tables; ROLE_HEALTH_OFFICER -> +health;
#     admin -> NO warehouse tables (admin path is adminService only)
#   * PII column denylist (name, phone, email, address, aadhaar) even for permitted tables
#   * SET ROLE wall before execution + RESET after (Phase-5 grants, ADR-019/§3.3)
#   * audit row for EVERY attempt — allowed and blocked, with reason (SECURITY §9)
#   * JWT via cookie or Bearer; iss/aud/exp verified; denylisted jti -> 401
#   * row caps on the response (defense against table dumps)
#
# The DB seam is the module-level function surface (run_query_rows, insert_audit,
# jti_is_revoked); tests monkeypatch it. run_query_rows takes the pg_role and opens the
# walled connection itself — role and statement must share one connection.
import sys
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as qs  # noqa: E402

SECRET = "test-secret-not-a-real-credential"


class FakeDB:
    def __init__(self):
        self.audit = []
        self.wall = []
        self.executed = None
        self.rows = [{"ward": "1", "status": "open", "count": 3}]

    def reset(self, rows=None):
        self.rows = rows if rows is not None else [{"ward": "1", "status": "open", "count": 3}]


@pytest.fixture()
def db():
    return FakeDB()


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setattr(qs, "jti_is_revoked", lambda jti: False)
    monkeypatch.setattr(
        qs, "run_query_rows",
        lambda sql, limit, pg_role: (db.wall.append(("SET ROLE", pg_role)), db.rows)[1])
    monkeypatch.setattr(
        qs, "insert_audit",
        lambda actor, role, query_sql, verdict, block_reason, row_count, source:
            db.audit.append(dict(actor=actor, role=role, query_sql=query_sql, verdict=verdict,
                                 block_reason=block_reason, row_count=row_count, source=source)),
    )
    with TestClient(qs.app) as c:
        yield c


def token(role="nmc_officer", sub="officer-001", jti="jti-1", secret=SECRET, **extra):
    now = int(time.time())
    payload = {"iss": "nagar-auth", "aud": "nagar-services", "sub": sub, "role": role,
               "jti": jti, "iat": now, "exp": now + 600}
    payload.update(extra)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def auth_header(t):
    return {"Authorization": f"Bearer {t}"}


# --------------------------------------------------------------------------- auth


def test_query_requires_token(client):
    r = client.post("/query", json={"sql": "SELECT 1"})
    assert r.status_code == 401


def test_query_rejects_garbage_token(client):
    r = client.post("/query", json={"sql": "SELECT 1"}, headers=auth_header("not.a.jwt"))
    assert r.status_code == 401


def test_query_rejects_wrong_audience(client):
    t = token(aud="elsewhere")
    r = client.post("/query", json={"sql": "SELECT 1"}, headers=auth_header(t))
    assert r.status_code == 401


def test_query_rejects_denylisted_jti(client, monkeypatch):
    monkeypatch.setattr(qs, "jti_is_revoked", lambda jti: True)
    r = client.post("/query", json={"sql": "SELECT 1"}, headers=auth_header(token()))
    assert r.status_code == 401


# --------------------------------------------------------------------------- AST gate


def test_select_passes_and_returns_rows(client, db):
    r = client.post("/query", json={"sql": "SELECT ward, status FROM nmc_complaints LIMIT 5"},
                    headers=auth_header(token()))
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == db.rows


def test_rejects_insert(client):
    r = client.post("/query", json={"sql": "INSERT INTO nmc_complaints DEFAULT VALUES"},
                    headers=auth_header(token()))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "non-select"


def test_rejects_multi_statement(client):
    r = client.post("/query",
                    json={"sql": "SELECT 1; SELECT 2"},
                    headers=auth_header(token()))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "non-select"


def test_rejects_update_delete_ddl(client):
    t = auth_header(token())
    for sql in ["UPDATE nmc_complaints SET status='x'",
                "DELETE FROM nmc_complaints",
                "CREATE TABLE sneaky (id int)",
                "DROP TABLE nmc_complaints",
                "TRUNCATE nmc_complaints",
                "GRANT SELECT ON nmc_complaints TO PUBLIC"]:
        r = client.post("/query", json={"sql": sql}, headers=t)
        assert r.status_code == 403, sql
        assert r.json()["detail"]["reason"] == "non-select"


def test_rejects_unparseable_sql(client):
    r = client.post("/query", json={"sql": "SELEKT nonsense FRM nowhere"}, headers=auth_header(token()))
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "parse-error"


# --------------------------------------------------------------------------- table RBAC


def test_nmc_officer_blocked_from_health(client):
    r = client.post("/query", json={"sql": "SELECT * FROM health_camp_records"},
                    headers=auth_header(token(role="nmc_officer")))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "table-rbac"


def test_health_officer_allowed_health(client):
    r = client.post("/query", json={"sql": "SELECT screening_type FROM health_camp_records"},
                    headers=auth_header(token(role="ROLE_HEALTH_OFFICER")))
    assert r.status_code == 200


def test_admin_has_no_warehouse_tables(client):
    r = client.post("/query", json={"sql": "SELECT count(*) FROM nmc_complaints"},
                    headers=auth_header(token(role="admin")))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "table-rbac"


def test_unknown_role_has_no_tables(client):
    r = client.post("/query", json={"sql": "SELECT 1"},
                    headers=auth_header(token(role="mystery")))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "table-rbac"


def test_auth_tables_never_queryable_by_officers(client):
    t = auth_header(token(role="ROLE_HEALTH_OFFICER"))  # broadest officer role
    for sql in ["SELECT * FROM users", "SELECT * FROM sessions", "SELECT * FROM audit_logs"]:
        r = client.post("/query", json={"sql": sql}, headers=t)
        assert r.status_code == 403, sql
        assert r.json()["detail"]["reason"] == "table-rbac"


# --------------------------------------------------------------------------- PII denylist


@pytest.mark.parametrize("col", ["name", "phone", "email", "address", "aadhaar"])
def test_pii_columns_blocked(client, col):
    r = client.post("/query", json={"sql": f"SELECT {col} FROM nmc_complaints"},
                    headers=auth_header(token()))
    assert r.status_code == 403, col
    assert r.json()["detail"]["reason"] == "pii-column"


def test_pii_blocked_with_alias_and_qualifier(client):
    r = client.post("/query",
                    json={"sql": "SELECT c.phone AS contact FROM nmc_complaints c"},
                    headers=auth_header(token()))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "pii-column"


def test_pii_blocked_in_where(client):
    r = client.post("/query",
                    json={"sql": "SELECT ward FROM nmc_complaints WHERE name = 'x'"},
                    headers=auth_header(token()))
    assert r.status_code == 403


def test_count_star_allowed_on_pii_table(client):
    """COUNT(*) projects no columns — the denylist is about columns (ARCH §3.4).
    Refined after the Phase-7d live E2E showed the model's COUNT(*) gate-blocked."""
    r = client.post("/query", json={"sql": "SELECT COUNT(*) FROM nmc_complaints"},
                    headers=auth_header(token()))
    assert r.status_code == 200


def test_select_star_still_blocked(client):
    r = client.post("/query", json={"sql": "SELECT * FROM nmc_complaints"},
                    headers=auth_header(token()))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "pii-column"


# --------------------------------------------------------------------------- wall + audit


def test_set_role_wall_wraps_execution(client, db):
    """The pg_role must reach the executor, or the statement runs as the connecting role."""
    r = client.post("/query", json={"sql": "SELECT ward FROM nmc_complaints"},
                    headers=auth_header(token(role="nmc_officer")))
    assert r.status_code == 200
    assert db.wall == [("SET ROLE", "nmc_officer")]


def test_health_officer_executes_as_health_officer(client, db):
    r = client.post("/query", json={"sql": "SELECT camp_id FROM health_camp_records"},
                    headers=auth_header(token(role="ROLE_HEALTH_OFFICER")))
    assert r.status_code == 200
    assert db.wall == [("SET ROLE", "health_officer")]


class _FakeCursor:
    def __init__(self, log):
        self.log = log
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *params):
        self.log.append(sql)
        if sql.startswith("SELECT * FROM (") and self.description is None:
            self.description = [type("D", (), {"name": "ward"})()]

    def fetchall(self):
        return [("W1",)]

    def commit(self):
        pass


class _FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self.log)

    def commit(self):
        pass


def test_set_role_and_statement_share_one_connection(monkeypatch):
    """Regression for the wall that never applied: SET ROLE was issued on a connection that
    was closed before the statement ran, so the statement executed as the connecting role —
    in production `nagar`, the owner of every table. The role must be set on the SAME
    connection that carries the query, and RESET on the way out."""
    log: list[str] = []
    monkeypatch.setattr(qs, "_conn", lambda: _FakeConn(log))
    rows = qs.run_query_rows("SELECT ward FROM nmc_complaints", 500, "nmc_officer")
    assert rows == [{"ward": "W1"}]
    assert log[0].startswith('SET ROLE "nmc_officer"'), log
    assert any(s.startswith("SELECT * FROM (") for s in log), log
    assert log[-1] == "RESET ROLE", log


def test_audit_row_on_success(client, db):
    client.post("/query", json={"sql": "SELECT ward FROM nmc_complaints"},
                headers=auth_header(token(role="nmc_officer", jti="jt-a")))
    row = db.audit[-1]
    assert row["verdict"] == "allowed"
    assert row["role"] == "nmc_officer"
    assert row["source"] == "queryService"
    assert "nmc_complaints" in row["query_sql"]


def test_audit_row_on_block_with_reason(client, db):
    client.post("/query", json={"sql": "DELETE FROM nmc_complaints"},
                headers=auth_header(token(role="nmc_officer")))
    row = db.audit[-1]
    assert row["verdict"] == "blocked"
    assert row["block_reason"] == "non-select"


def test_row_cap_applied(client, db, monkeypatch):
    db.reset(rows=[{"i": i} for i in range(1000)])
    r = client.post("/query", json={"sql": "SELECT i FROM traffic_events"},
                    headers=auth_header(token()))
    assert r.status_code == 200
    assert len(r.json()["rows"]) <= 500  # service cap below the wall-level limit


def test_db_errors_surface_503(client, monkeypatch):
    def boom(sql, limit, pg_role):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(qs, "run_query_rows", boom)
    r = client.post("/query", json={"sql": "SELECT 1"}, headers=auth_header(token()))
    assert r.status_code == 503


# --------------------------------------------------------------------------- liveness


def test_liveness(client):
    assert client.get("/").status_code == 200


# ------------------------------------------------- whole-row PII exfiltration (ADR-030)
#
# The denylist used to match denylisted COLUMN NAMES only. That left a hole any
# `nmc_officer` could walk through: reference the PII table itself (or an alias of it) and
# PostgreSQL hands back every column, PII included. Every case below reached the database
# before the fix; the to_jsonb/row_to_json/json_agg family wraps the same whole-row
# reference in a serializer and leaked just as effectively.

WHOLE_ROW_LEAKS = [
    "SELECT c FROM nmc_complaints c",
    "SELECT nmc_complaints FROM nmc_complaints",
    "SELECT to_jsonb(c) FROM nmc_complaints c",
    "SELECT to_json(c) FROM nmc_complaints c",
    "SELECT row_to_json(c) FROM nmc_complaints c",
    "SELECT json_agg(c) FROM nmc_complaints c",
    "SELECT array_agg(c) FROM nmc_complaints c",
    "SELECT string_agg(c::text, ',') FROM nmc_complaints c",
    "SELECT to_jsonb(c.*) FROM nmc_complaints c",
    "SELECT c.* FROM nmc_complaints c",
    "SELECT to_json(t) FROM (SELECT * FROM nmc_complaints) t",
    "SELECT (nmc_complaints).name FROM nmc_complaints",
]


@pytest.mark.parametrize("sql", WHOLE_ROW_LEAKS)
def test_whole_row_reference_over_pii_table_is_blocked(client, db, sql):
    r = client.post("/query", json={"sql": sql}, headers=auth_header(token()))
    assert r.status_code == 403, f"{sql} was not blocked: {r.text}"
    assert r.json()["detail"]["reason"] == "pii-column"
    assert db.audit[-1]["block_reason"] == "pii-column"
    assert db.audit[-1]["verdict"] == "blocked"


LEGITIMATE_OVER_PII = [
    "SELECT count(*) FROM nmc_complaints",
    "SELECT count(c) FROM nmc_complaints c",
    "SELECT ward, count(*) FROM nmc_complaints GROUP BY ward",
    "SELECT max(occurred_at) FROM nmc_complaints",
    "SELECT c.ward, c.status FROM nmc_complaints c",
    "SELECT upper(description) FROM nmc_complaints",
    "SELECT count(*) FROM nmc_complaints JOIN traffic_events ON true",
    "SELECT * FROM traffic_events",
    "WITH recent AS (SELECT ward, occurred_at FROM nmc_complaints) "
    "SELECT count(*) FROM recent",
]


@pytest.mark.parametrize("sql", LEGITIMATE_OVER_PII)
def test_legitimate_queries_still_pass_the_gate(client, sql):
    """The whole-row rule must not become a blanket block: officers and the SLM both need
    aggregates, explicit non-PII columns, and CTEs to keep working."""
    r = client.post("/query", json={"sql": sql}, headers=auth_header(token()))
    assert r.status_code == 200, f"{sql} was wrongly blocked: {r.text}"


def test_dml_hidden_in_a_cte_is_blocked(client):
    """A CTE can smuggle a data-modifying statement under a SELECT root. This was stopped
    before only because the CTE alias was miscounted as an unknown table - naming the CTE
    after an allowlisted table slipped past the application gate entirely."""
    for sql in ["WITH nmc_complaints AS (INSERT INTO nmc_complaints (complaint_text) "
                "VALUES ('x') RETURNING *) SELECT count(*) FROM nmc_complaints",
                "WITH traffic_events AS (DELETE FROM nmc_complaints RETURNING *) "
                "SELECT count(*) FROM traffic_events"]:
        r = client.post("/query", json={"sql": sql}, headers=auth_header(token()))
        assert r.status_code == 403, f"{sql} was not blocked: {r.text}"
        assert r.json()["detail"]["reason"] == "non-select"


def test_cte_alias_cannot_hide_a_non_allowlisted_table(client):
    """Subtracting CTE aliases from the table set must not blind the RBAC check to the
    tables inside the CTE body."""
    r = client.post("/query",
                    json={"sql": "WITH traffic_events AS (SELECT * FROM users) "
                                 "SELECT count(*) FROM traffic_events"},
                    headers=auth_header(token()))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "table-rbac"


# ------------------------------------------------- DB wall is a block, not an outage


def test_insufficient_privilege_is_reported_as_a_block(client, db, monkeypatch):
    """The Phase-5 column-level grants (ADR-030) can deny a column the AST gate let
    through. That must surface as an audited 403, never as 'database unreachable'."""
    import psycopg

    def deny(sql, limit, pg_role):
        raise psycopg.errors.InsufficientPrivilege("permission denied for table")

    monkeypatch.setattr(qs, "run_query_rows", deny)
    r = client.post("/query", json={"sql": "SELECT ward FROM nmc_complaints"},
                    headers=auth_header(token()))
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == {"reason": "db-wall", "verdict": "blocked"}
    assert db.audit[-1]["block_reason"] == "db-wall"


def test_statement_timeout_is_reported_as_a_block(client, db, monkeypatch):
    import psycopg

    def slow(sql, limit, pg_role):
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(qs, "run_query_rows", slow)
    r = client.post("/query", json={"sql": "SELECT pg_sleep(60)"},
                    headers=auth_header(token()))
    assert r.status_code == 504, r.text
    assert r.json()["detail"]["reason"] == "statement-timeout"
    assert db.audit[-1]["block_reason"] == "statement-timeout"


def test_connections_carry_a_statement_timeout(monkeypatch):
    """The gate bounds query shape, not query cost; the timeout bounds the cost."""
    seen = {}

    class FakeConn:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(qs.psycopg, "connect", lambda dsn, **kw: FakeConn(**kw))
    qs._conn()
    assert "statement_timeout" in seen["options"]
