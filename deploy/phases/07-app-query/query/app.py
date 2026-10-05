# queryService — FastAPI SQL execution + RBAC (port 4003), Phase 7b fresh rebuild (ADR-013).
#
# CONTRACTS (verbatim — ARCHITECTURE §4.1 `POST /query` JWT + role RBAC; ARCHITECTURE §3.4
# guardrails; SECURITY §3 layered authorization; Phase-5 DDL audit_logs + officer grant roles):
#   POST /query  { sql } -> execute validated SQL behind the role wall
#   GET  /dbcheck  SELECT 1 (public, readiness)
#   GET  /       liveness
#
# Gate layers, in order (SECURITY §3):
#   1. JWT (cookie or Bearer) — iss=nagar-auth, aud=nagar-services, exp; jti denylist
#      (same nagar-jwt secret and sessions table as authService).
#   2. sqlglot AST gate — parse (postgres dialect), exactly ONE statement, SELECT-shaped
#      only; everything else is `non-select` (403) or `parse-error` (400).
#   3. Table RBAC — nmc_officer: the four civic tables; ROLE_HEALTH_OFFICER: + health
#      camp records; admin: NO warehouse tables (SECURITY §3: admin acts via adminService
#      only); unknown roles: nothing (fail closed). users/sessions/audit_logs are never
#      queryable through this service.
#   4. PII column denylist — name, phone, email, address, aadhaar (ARCHITECTURE §3.4)
#      anywhere in the AST; star-expansion over a PII-bearing table is blocked too.
#   5. SET ROLE wall — the Phase-5 grants make the service role a member of nmc_officer /
#      health_officer; every execution runs after `SET ROLE <pg_role>` and RESETs after,
#      so the database re-checks what the application allowed (SECURITY §3 layer 3,
#      migration 001 grant block). One fresh connection per request: SET ROLE is
#      connection-scoped and must never leak across requests.
#   6. Audit — every attempt, allowed or blocked, with reason, to audit_logs (SECURITY §9).
#
# The DB surface is the module-level seam (run_query_rows, wall_begin, wall_end,
# insert_audit, jti_is_revoked, dbcheck_query); tests monkeypatch it, the real
# implementations use psycopg3 per request.
import os
import time

import jwt as pyjwt
import psycopg
import sqlglot
from sqlglot import expressions as exp
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

ISSUER = "nagar-auth"
AUDIENCE = "nagar-services"
ALGORITHM = "HS256"
COOKIE_NAME = "session_token"
ROW_LIMIT = 500  # service cap below the wall-level fetch limit
# The gate can bound the SHAPE of a query, never the work it does. A statement timeout
# is what stops an expensive-but-legal SELECT (cartesian joins, pg_sleep) from pinning a
# connection; it is a per-connection setting, applied in _conn().
STATEMENT_TIMEOUT_MS = 15000

# SECURITY §3 matrix -> Phase-5 DDL grant roles. The JWT wire constant ROLE_HEALTH_OFFICER
# maps to the PostgreSQL role health_officer (migration 001 header note).
ROLE_TABLES = {
    "nmc_officer": {"nmc_complaints", "traffic_events", "water_sensor_readings", "ev_bus_telemetry"},
    "ROLE_HEALTH_OFFICER": {
        "nmc_complaints", "traffic_events", "water_sensor_readings", "ev_bus_telemetry",
        "health_camp_records",
    },
}
ROLE_PG = {"nmc_officer": "nmc_officer", "ROLE_HEALTH_OFFICER": "health_officer"}
PII_COLUMNS = {"name", "phone", "email", "address", "aadhaar"}  # ARCHITECTURE §3.4 denylist
PII_TABLES = {"nmc_complaints"}  # tables carrying denylisted columns (migration 001)

app = FastAPI(title="queryService", docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------------- seams


def jti_is_revoked(jti: str) -> bool:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE jti = %s AND revoked_at IS NOT NULL", (jti,))
        return cur.fetchone() is not None


def wall_begin(pg_role: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f'SET ROLE "{pg_role}"')  # role names are from ROLE_PG above, not input
        conn.commit()


def wall_end() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("RESET ROLE")
        conn.commit()


def run_query_rows(sql: str, limit: int) -> list[dict]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM ({sql}) AS gated LIMIT %s", (limit,))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_audit(actor, role, query_sql, verdict, block_reason, row_count, source) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs (actor, role, query_sql, verdict, block_reason, row_count, source)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (actor, role, query_sql, verdict, block_reason, row_count, source),
        )
        conn.commit()


def dbcheck_query() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


def _conn():
    return psycopg.connect(env("DATABASE_URL"), connect_timeout=5,
                           options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}")


# --------------------------------------------------------------------------- helpers


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"service misconfigured: {name} unset")
    return value


def claims_from_request(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing session")
    try:
        return pyjwt.decode(token, env("JWT_SECRET"), algorithms=[ALGORITHM],
                            audience=AUDIENCE, issuer=ISSUER)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session")


def identity_from_request(request: Request) -> dict:
    claims = claims_from_request(request)
    if jti_is_revoked(claims["jti"]):
        raise HTTPException(status_code=401, detail="session revoked")
    return claims


class GateBlock(Exception):
    def __init__(self, reason: str, status: int = 403):
        self.reason = reason
        self.status = status


_NON_SELECT_KEYWORDS = ("insert", "update", "delete", "merge", "create", "drop", "alter",
                        "truncate", "grant", "revoke", "copy", "call", "do", "vacuum",
                        "analyze", "comment", "lock", "reindex", "cluster", "set", "reset",
                        "begin", "commit", "rollback", "prepare", "execute")


def parse_single_select(sql: str):
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        # sqlglot cannot parse every DML form (e.g. INSERT ... DEFAULT VALUES). A parse
        # failure on a statement that OPENS with a known non-SELECT keyword is reported
        # truthfully as non-select (the audit reason matters); anything else is a 400.
        first = sql.lstrip().split(None, 1)[0].lower() if sql.lstrip() else ""
        if first in _NON_SELECT_KEYWORDS:
            raise GateBlock("non-select")
        raise GateBlock("parse-error", status=400)
    if len(statements) != 1 or statements[0] is None:
        raise GateBlock("non-select")

    def is_select_shape(node) -> bool:
        if isinstance(node, exp.Select):
            return True
        if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
            return is_select_shape(node.this) and is_select_shape(node.expression)
        return False

    if not is_select_shape(statements[0]):
        raise GateBlock("non-select")

    # A SELECT-shaped statement can still carry a data-modifying statement in a CTE
    # (PostgreSQL 14+: `WITH x AS (INSERT ... RETURNING *) SELECT * FROM x`). Block any
    # DML node anywhere in the tree rather than relying on its target table happening to
    # miss the role's set.
    for node_kind in _DML_NODES:
        if next(statements[0].find_all(node_kind), None) is not None:
            raise GateBlock("non-select")
    return statements[0]


_DML_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop)


def cte_names(tree) -> set[str]:
    """CTE aliases are not tables. `find_all(exp.Table)` sees the alias reference in the
    outer FROM as a table, which both failed the RBAC set for a legitimate CTE and let a
    smuggled CTE borrow an allowlisted name. Bodies are still collected, so a CTE cannot
    hide a non-allowlisted table from the RBAC check."""
    return {c.alias.lower() for c in tree.find_all(exp.CTE) if c.alias}


def referenced_tables(tree) -> set[str]:
    return {t.name.lower() for t in tree.find_all(exp.Table)} - cte_names(tree)


def check_table_rbac(role: str, tables: set[str]) -> None:
    allowed = ROLE_TABLES.get(role)
    if allowed is None:  # unknown/admin roles: fail closed even for table-less SELECTs
        raise GateBlock("table-rbac")
    if not tables <= allowed:
        raise GateBlock("table-rbac")


# Aggregates that collapse their argument to a scalar. A whole-row or star argument
# inside one of these never reaches the result set, so it cannot leak a column. Every
# other wrapper (to_json, to_jsonb, row_to_json, json_agg, array_agg, string_agg, ...)
# can serialise the row it is handed and is therefore NOT exempt.
_SCALAR_AGGS = {"count", "sum", "avg", "min", "max", "stddev", "variance",
                "bool_and", "bool_or", "every", "bit_and", "bit_or"}


def _ancestors(node):
    while node.parent is not None:
        node = node.parent
        yield node


def _in_scalar_agg(node) -> bool:
    """True when `node` is an argument of a scalar-collapsing aggregate. The walk stops at
    the enclosing Select: past the projection the value escapes into the returned rows."""
    for anc in _ancestors(node):
        if isinstance(anc, exp.AggFunc):
            return (anc.sql_name() or "").lower() in _SCALAR_AGGS
        if isinstance(anc, exp.Select):
            return False
    return False


def _pii_aliases(tree) -> set[str]:
    """Every name a PII table can be referred to: its own name plus each alias, collected
    across the whole tree so a subquery alias is covered too."""
    names: set[str] = set()
    for tbl in tree.find_all(exp.Table):
        if tbl.name.lower() in PII_TABLES:
            names.add(tbl.name.lower())
            if tbl.alias:
                names.add(tbl.alias.lower())
    return names


def check_pii(tree, tables: set[str]) -> None:
    aliases = _pii_aliases(tree)
    for column in tree.find_all(exp.Column):
        name = (column.name or "").lower()
        if name in PII_COLUMNS:
            raise GateBlock("pii-column")
        # A bare reference to a table or its alias IS the whole row, PII columns included,
        # and it survives every column-name rewrite: `SELECT c ...`, `to_jsonb(c)`,
        # `row_to_json(c)`, `json_agg(c)`. Blocking the denylisted column names alone is
        # not enough — the projection must be proven column-by-column.
        if name in aliases and not _in_scalar_agg(column):
            raise GateBlock("pii-column")
    # A star must not project PII columns past the column scan. A star anywhere over a PII
    # table is blocked — in a SELECT list, qualified (`c.*`), or wrapped in a function
    # (`to_jsonb(c.*)`) — unless a scalar aggregate collapses it. COUNT(*) stays allowed:
    # the denylist is about COLUMNS (ARCHITECTURE §3.4), refined after the live Phase-7d
    # E2E caught COUNT(*) blocked.
    if tables & PII_TABLES:
        for star in tree.find_all(exp.Star):
            if not _in_scalar_agg(star):
                raise GateBlock("pii-column")


class QueryBody(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)


@app.post("/query")
def query(body: QueryBody, request: Request):
    actor = role = None
    try:
        claims = identity_from_request(request)
        actor, role, jti = claims["sub"], claims["role"], claims["jti"]

        try:
            tree = parse_single_select(body.sql)
        except GateBlock as g:
            insert_audit(actor, role, body.sql, "blocked", g.reason, None, "queryService")
            raise HTTPException(status_code=g.status,
                                detail={"reason": g.reason, "verdict": "blocked"})

        tables = referenced_tables(tree)
        try:
            check_table_rbac(role, tables)
            check_pii(tree, tables)
        except GateBlock as g:
            insert_audit(actor, role, body.sql, "blocked", g.reason, None, "queryService")
            raise HTTPException(status_code=g.status,
                                detail={"reason": g.reason, "verdict": "blocked"})

        wall_begin(ROLE_PG[role])
        try:
            # The gate tolerates a trailing semicolon (single statement either way); the
            # wall-wrap subquery does not, so strip it for execution only (audit keeps the
            # SQL exactly as received).
            exec_sql = body.sql.strip().rstrip(";").rstrip()
            rows = run_query_rows(exec_sql, ROW_LIMIT)
        except psycopg.errors.InsufficientPrivilege:
            # The Phase-5 column-level grants are the independent second wall under the
            # AST gate (ADR-030). A denial here is a BLOCKED verdict, not an outage: it
            # must be audited as such and must never be reported as "database unreachable".
            insert_audit(actor, role, body.sql, "blocked", "db-wall", None, "queryService")
            raise HTTPException(status_code=403,
                                detail={"reason": "db-wall", "verdict": "blocked"})
        except psycopg.errors.QueryCanceled:
            insert_audit(actor, role, body.sql, "blocked", "statement-timeout", None,
                         "queryService")
            raise HTTPException(status_code=504,
                                detail={"reason": "statement-timeout", "verdict": "blocked"})
        finally:
            wall_end()

        rows = rows[:ROW_LIMIT]
        insert_audit(actor, role, body.sql, "allowed", None, len(rows), "queryService")
        return {"rows": rows, "row_count": len(rows), "role": role}
    except HTTPException:
        raise
    except GateBlock as g:  # parse-error raised before identity-dependent audit shape
        insert_audit(actor, role, body.sql, "blocked", g.reason, None, "queryService")
        raise HTTPException(status_code=g.status, detail={"reason": g.reason, "verdict": "blocked"})
    except Exception:  # noqa: BLE001 - DB failures are readiness failures, not 500s
        raise HTTPException(status_code=503, detail="database unreachable")


@app.get("/dbcheck")
def dbcheck():
    try:
        dbcheck_query()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.get("/")
def liveness():
    return {"status": "ok", "service": "queryService"}
