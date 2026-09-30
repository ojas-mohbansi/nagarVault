# adminService — FastAPI cluster admin surface (port 4001), Phase 7f fresh rebuild (ADR-013).
#
# CONTRACTS (verbatim — ARCHITECTURE §4.1 adminService rows, all admin JWT; §4.2 DLQ
# registry row (`adminService (inspect)`); §4.3 storage registry; SECURITY §3 (admin scope
# lives only here), §6.2 (secrets), §8 (egress = postgres + kafka + schema-indexer only),
# §9 audit; Phase-5 DDL audit_logs; the 7c DLQ wrapper from worker/enrich.py
# record_to_dlq — {dlqReason, detail, originalTopic, raw}):
#   GET /health/cluster   admin JWT -> {db, kafka, schemaIndexer, all} — infra summary
#   GET /dlq?limit=N      admin JWT -> bounded tail of nmc.complaints.dlq.v1, entries in
#                         the exact shape the 7c worker produces (+ topic/partition/offset)
#   GET /audit-logs       admin JWT -> latest audit_logs rows (Phase-5 DDL columns)
#   GET /                 public liveness
#   GET /dbcheck          public readiness (SELECT 1)
#
# The /vector/resync row (§4.1) is NOT implemented yet: the charter's exit criteria for 7f
# are /health/cluster, /dlq, /audit-logs; resync needs an admin-auth story on the indexer
# that §4.1 leaves as "internal" — deferred to 7g/Phase 8 rather than inventing auth here
# (deviation recorded in ADR-022, revisited with the frontend work).
#
# Design notes:
#   * DLQ reads use a DISTINCT consumer group (admin-dlq-inspect, auto.offset.reset=latest)
#     so inspection never disturbs enrichWorker's commit positions.
#   * JWT semantics copied from the 7b gate (cookie or Bearer; iss/aud/exp; shared
#     sessions-denylist via jti_is_revoked — 7b proved the cross-service denylist).
#   * The DB surface is the module-level seam (probe_*, fetch_audit_rows,
#     fetch_dlq_entries, dbcheck_query); tests monkeypatch it; the real implementations
#     run in-cluster (G7f.4).
import json
import os
import time
import uuid

import jwt as pyjwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

ISSUER = "nagar-auth"
AUDIENCE = "nagar-services"
ALGORITHM = "HS256"
COOKIE_NAME = "session_token"
DLQ_TOPIC = "nmc.complaints.dlq.v1"  # frozen name, ARCHITECTURE §4.2
DEFAULT_DLQ_LIMIT = 50
MAX_DLQ_LIMIT = 200
DEFAULT_AUDIT_LIMIT = 100
MAX_AUDIT_LIMIT = 500
HEALTH_TIMEOUT_S = 3

app = FastAPI(title="adminService", docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------------- seams

def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"service misconfigured: {name} unset")
    return value


def _conn():
    return psycopg.connect(env("DATABASE_URL"), connect_timeout=5)


def dbcheck_query() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


def probe_db() -> bool:
    try:
        dbcheck_query()
        return True
    except Exception:  # noqa: BLE001 - any DB failure means not ready
        return False


def probe_kafka() -> bool:
    try:
        from confluent_kafka.admin import AdminClient

        admin_client = AdminClient({"bootstrap.servers": env("KAFKA_BOOTSTRAP")})
        metadata = admin_client.list_topics(timeout=HEALTH_TIMEOUT_S)
        return DLQ_TOPIC in metadata.topics
    except Exception:  # noqa: BLE001
        return False


def probe_schema_indexer() -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(
            os.environ.get("SCHEMA_INDEXER_URL", "http://schema-indexer.nagar-platform.svc.cluster.local:4005/health"),
            timeout=GET_TIMEOUT_S,
        ) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def fetch_audit_rows(limit: int) -> list[dict]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, occurred_at, actor, role, query_sql, verdict, block_reason,"
            " row_count, client_ip, source"
            " FROM audit_logs ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def tail_starts(partitions_with_end: list, limit: int) -> list:
    """[(topic, partition, end_offset)] -> [(topic, partition, start_offset)] for a
    bounded tail read (pure; hermetically tested). End offsets come from
    get_watermark_offsets as plain ints — never from position(), whose
    TopicPartition objects must not be tuple-unpacked (G7f finding)."""
    return [(t, p, max(0, o - limit)) for (t, p, o) in partitions_with_end]


def fetch_dlq_entries(limit: int) -> list[dict]:
    """Bounded, STATELESS tail of the DLQ via a dedicated consumer group. Offsets come
    from get_watermark_offsets (concrete end offsets) and are NEVER committed — the
    group exists only to own a stable identity per pod; every inspection re-reads the
    live tail (I-2: safe forever, no cluster state mutated)."""
    from confluent_kafka import Consumer, TopicPartition

    group_id = os.environ.get("ADMIN_DLQ_GROUP", "admin-dlq-inspect")
    consumer = Consumer({
        "bootstrap.servers": env("KAFKA_BOOTSTRAP"),
        "group.id": group_id,
        "enable.auto.commit": False,
        "auto.offset.reset": "latest",  # inspection tail; never replays history
    })
    try:
        meta = consumer.list_topics(DLQ_TOPIC, timeout=HEALTH_TIMEOUT_S)
        partitions = sorted(meta.topics[DLQ_TOPIC].partitions)
        ends = []
        for p in partitions:
            # NB (G7f findings, both found live): this binding rejects timeout= as a
            # keyword AND requires a TopicPartition OBJECT (not topic+partition ints)
            # as the first argument — the 2-arg int form raises
            # "TypeError: expected cimpl.TopicPartition".
            low, high = consumer.get_watermark_offsets(TopicPartition(DLQ_TOPIC, p), HEALTH_TIMEOUT_S)
            ends.append((DLQ_TOPIC, p, high))
        starts = [TopicPartition(t, p, o) for (t, p, o) in tail_starts(ends, limit)]
        consumer.assign(starts)
        entries, deadline = [], time.time() + max(2.0, HEALTH_TIMEOUT_S * 2)
        got = {tp.partition: 0 for tp in starts}
        while time.time() < deadline and sum(got.values()) < limit * len(starts):
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                continue
            got[msg.partition()] = got.get(msg.partition(), 0) + 1
            entries.append(parse_dlq_value(
                msg.value(), topic=msg.topic(), partition=msg.partition(), offset=msg.offset(),
            ))
        entries.sort(key=lambda e: (e["partition"], e["offset"]))
        return entries
    finally:
        consumer.close()


GET_TIMEOUT_S = 5


def parse_dlq_value(value: bytes, topic: str, partition: int, offset: int) -> dict:
    """Parse one DLQ message into the exact shape enrichWorker.record_to_dlq produces
    ({dlqReason, detail, originalTopic, raw}); undecodable DLQ payloads are reported
    verbatim-bounded rather than dropped — an inspection tool must not lose evidence."""
    entry = {"topic": topic, "partition": partition, "offset": offset}
    try:
        wrapper = json.loads(value.decode("utf-8", "replace"))
        if isinstance(wrapper, dict):
            entry.update({
                "dlqReason": wrapper.get("dlqReason"),
                "detail": wrapper.get("detail"),
                "originalTopic": wrapper.get("originalTopic"),
                "raw": wrapper.get("raw"),
            })
            return entry
    except (json.JSONDecodeError, ValueError):
        pass
    entry.update({
        "dlqReason": "undecodable-dlq-message",
        "detail": "DLQ wrapper itself was not the expected JSON object",
        "originalTopic": None,
        "raw": value.decode("utf-8", "replace")[:2000],
    })
    return entry


# --------------------------------------------------------------------------- auth

def jwt_secret() -> str:
    return env("JWT_SECRET")


def decode_token(token_str: str) -> dict:
    try:
        return pyjwt.decode(
            token_str, jwt_secret(), algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER
        )
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session")


def claims_from_request(request: Request) -> dict:
    token_str = request.cookies.get(COOKIE_NAME)
    if not token_str:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token_str = auth_header[7:].strip()
    if not token_str:
        raise HTTPException(status_code=401, detail="missing session")
    return decode_token(token_str)


def identity_from_request(request: Request) -> dict:
    claims = claims_from_request(request)
    if jti_is_revoked(claims["jti"]):
        raise HTTPException(status_code=401, detail="session revoked")
    return claims


def jti_is_revoked(jti: str) -> bool:
    """Same sessions denylist as authService/queryService (7b cross-service proof)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE jti = %s AND revoked_at IS NOT NULL", (jti,))
        return cur.fetchone() is not None


def admin_identity(claims: dict = Depends(identity_from_request)) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return claims


# --------------------------------------------------------------------------- endpoints

@app.get("/")
def liveness():
    return {"status": "ok", "service": "adminService"}


@app.get("/dbcheck")
def dbcheck():
    try:
        dbcheck_query()
    except Exception:  # noqa: BLE001 - any DB failure means not ready
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.get("/health/cluster")
def health_cluster(claims: dict = Depends(admin_identity)):
    db_ok = _safe(probe_db)
    kafka_ok = _safe(probe_kafka)
    indexer_ok = _safe(probe_schema_indexer)
    return {
        "db": db_ok,
        "kafka": kafka_ok,
        "schemaIndexer": indexer_ok,
        "all": db_ok and kafka_ok and indexer_ok,
    }


def _safe(fn) -> bool:
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001
        return False


@app.get("/dlq")
def dlq(
    claims: dict = Depends(admin_identity),
    limit: int = Query(DEFAULT_DLQ_LIMIT, ge=1, le=MAX_DLQ_LIMIT),
):
    entries = _safe_list(lambda: fetch_dlq_entries(limit))
    return {"topic": DLQ_TOPIC, "count": len(entries), "entries": entries}


@app.get("/audit-logs")
def audit_logs(
    claims: dict = Depends(admin_identity),
    limit: int = Query(DEFAULT_AUDIT_LIMIT, ge=1, le=MAX_AUDIT_LIMIT),
):
    rows = _safe_list(lambda: fetch_audit_rows(limit))
    return {"count": len(rows), "entries": rows}


def _safe_list(fn) -> list:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - admin inspection reports failure, never masks it
        raise HTTPException(status_code=503, detail=f"inspection backend unavailable: {e}")


# --------------------------------------------------------------------------- runtime

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4001)
