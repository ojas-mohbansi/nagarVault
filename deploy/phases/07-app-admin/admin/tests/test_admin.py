# adminService test suite — Phase 7f (hermetic; no Kafka, no Postgres, no schemaIndexer).
#
# CONTRACT UNDER TEST (ARCHITECTURE §4.1 adminService rows — all admin JWT; §4.2 DLQ
# registry row (`adminService (inspect)`); SECURITY §3 admin-only, §9 audit; Phase-5 DDL
# audit_logs; the 7c DLQ wrapper from worker/enrich.py record_to_dlq):
#   * GET /health/cluster  admin JWT -> per-dependency booleans + `all`
#   * GET /dlq             admin JWT -> bounded consumer-group tail of nmc.complaints.dlq.v1,
#                            entries shaped EXACTLY as enrichWorker.record_to_dlq produces
#                            (dlqReason, detail, originalTopic, raw) + topic/partition/offset
#   * GET /audit-logs      admin JWT -> latest audit_logs rows (Phase-5 DDL columns)
#   * JWT gate: Bearer/cookie; iss=nagar-auth aud=nagar-services; nmc_officer -> 403
#     (SECURITY §3: admin scope lives only here); denylisted jti -> 401 (7b cross-service
#     denylist); missing/garbage -> 401
#   * GET / and /dbcheck are public liveness/readiness
#
# Seams are module-level (fetch_audit_rows, jti_is_revoked, probe_*, fetch_dlq_entries);
# tests monkeypatch them. The REAL DLQ tail against live Kafka + the real malformed-event
# round-trip are proven in-cluster (G7f.4). The DLQ entry test below pins the consumer to
# the byte shape enrichWorker.record_to_dlq emits — change one side without the other and
# this suite fails.
import base64
import json
import os
import sys
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret-not-a-real-credential"
os.environ.setdefault("JWT_SECRET", SECRET)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as admin  # noqa: E402

DLQ = "nmc.complaints.dlq.v1"


def token(role="admin", jti="j-1", **extra):
    now = int(time.time())
    claims = {
        "iss": "nagar-auth", "aud": "nagar-services", "sub": "admin-001", "role": role,
        "jti": jti, "iat": now, "exp": now + 600,
    }
    claims.update(extra)
    return pyjwt.encode(claims, SECRET, algorithm="HS256")


ADMIN_AUTH = {"Authorization": f"Bearer {token()}"}


@pytest.fixture()
def client(monkeypatch):
    admin.jti_is_revoked = lambda jti: False
    return TestClient(admin.app)


# --------------------------------------------------------------------------- cross-service pin

def test_dlq_entry_shape_pins_the_7c_wrapper():
    """The consumer's parser must round-trip exactly what enrichWorker.record_to_dlq
    produces: json.dumps({dlqReason, detail, originalTopic, raw})."""
    wrapper = {
        "dlqReason": "invalid-payload",
        "detail": "field vehicleCount must be an integer",
        "originalTopic": "traffic.events.raw.v1",
        "raw": '{"eventId": "evt-x", "payload": {"vehicleCount": "many"}}',
    }
    parsed = admin.parse_dlq_value(json.dumps(wrapper).encode(), topic=DLQ, partition=0, offset=41)
    assert parsed["dlqReason"] == "invalid-payload"
    assert parsed["detail"].startswith("field vehicleCount")
    assert parsed["originalTopic"] == "traffic.events.raw.v1"
    assert parsed["raw"].startswith('{"eventId"')
    assert parsed["topic"] == DLQ and parsed["partition"] == 0 and parsed["offset"] == 41


def test_parse_dlq_value_survives_garbage():
    parsed = admin.parse_dlq_value(b"\xff not json", topic=DLQ, partition=2, offset=7)
    assert parsed["dlqReason"] == "undecodable-dlq-message"
    assert parsed["offset"] == 7


# --------------------------------------------------------------------------- /dlq

def test_dlq_returns_entries_and_passes_limit(client, monkeypatch):
    captured = {}

    def fake_fetch(limit):
        captured["limit"] = limit
        return [{
            "dlqReason": "invalid-envelope", "detail": "missing or non-string eventId",
            "originalTopic": "nmc.complaints.raw.restricted.v1",
            "raw": '{"payload": {"ward": "1"}}',
            "topic": DLQ, "partition": 0, "offset": 12,
        }]

    monkeypatch.setattr(admin, "fetch_dlq_entries", fake_fetch)
    r = client.get("/dlq", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["topic"] == DLQ and body["count"] == 1
    assert body["entries"][0]["dlqReason"] == "invalid-envelope"
    assert captured["limit"] == 50


def test_dlq_limit_is_bounded(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(admin, "fetch_dlq_entries", lambda limit: seen.update(limit=limit) or [])
    # Out-of-range limits are rejected by validation (422), never silently clamped.
    assert client.get("/dlq?limit=999", headers=ADMIN_AUTH).status_code == 422
    assert "limit" not in seen
    assert client.get("/dlq?limit=77", headers=ADMIN_AUTH).status_code == 200
    assert seen["limit"] == 77 <= admin.MAX_DLQ_LIMIT


# --------------------------------------------------------------------------- /audit-logs

def test_audit_logs_shape_matches_phase5_ddl(client, monkeypatch):
    row = {
        "id": 9, "occurred_at": "2026-09-30T01:02:03+00:00", "actor": "off-1",
        "role": "nmc_officer", "query_sql": "SELECT 1", "verdict": "allowed",
        "block_reason": None, "row_count": 1, "client_ip": "10.42.0.9", "source": "queryService",
    }
    captured = {}
    monkeypatch.setattr(admin, "fetch_audit_rows", lambda limit: captured.update(limit=limit) or [row])
    r = client.get("/audit-logs", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    entry = body["entries"][0]
    for col in ("id", "occurred_at", "actor", "role", "query_sql", "verdict",
                "block_reason", "row_count", "client_ip", "source"):
        assert col in entry, f"audit_logs column {col} missing"
    assert entry["verdict"] in ("allowed", "blocked")
    assert captured["limit"] == 100


# --------------------------------------------------------------------------- /health/cluster

def test_health_cluster_all_up(client, monkeypatch):
    monkeypatch.setattr(admin, "probe_db", lambda: True)
    monkeypatch.setattr(admin, "probe_kafka", lambda: True)
    monkeypatch.setattr(admin, "probe_schema_indexer", lambda: True)
    r = client.get("/health/cluster", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body == {"db": True, "kafka": True, "schemaIndexer": True, "all": True}


def test_health_cluster_reports_the_down_dependency(client, monkeypatch):
    monkeypatch.setattr(admin, "probe_db", lambda: False)
    monkeypatch.setattr(admin, "probe_kafka", lambda: True)
    monkeypatch.setattr(admin, "probe_schema_indexer", lambda: True)
    body = client.get("/health/cluster", headers=ADMIN_AUTH).json()
    assert body["db"] is False and body["all"] is False


def test_health_cluster_dependency_failure_is_not_an_error(client, monkeypatch):
    def boom():
        raise RuntimeError("connection refused")
    monkeypatch.setattr(admin, "probe_db", boom)
    monkeypatch.setattr(admin, "probe_kafka", lambda: True)
    monkeypatch.setattr(admin, "probe_schema_indexer", lambda: True)
    body = client.get("/health/cluster", headers=ADMIN_AUTH).json()
    assert body["db"] is False and body["all"] is False


# --------------------------------------------------------------------------- authz gate

def test_officer_is_403_on_every_admin_endpoint(client):
    officer = {"Authorization": f"Bearer {token(role='nmc_officer', sub='off-1')}"}
    for path in ("/health/cluster", "/dlq", "/audit-logs"):
        assert client.get(path, headers=officer).status_code == 403, path


def test_missing_and_garbage_tokens_are_401(client):
    assert client.get("/health/cluster").status_code == 401
    assert client.get("/health/cluster", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cross_service_jti_denylist_is_honoured(client, monkeypatch):
    # 7b lesson: the sessions denylist is shared across services (same table).
    monkeypatch.setattr(admin, "jti_is_revoked", lambda jti: jti == "revoked-jti")
    revoked = {"Authorization": f"Bearer {token(jti='revoked-jti')}"}
    assert client.get("/health/cluster", headers=revoked).status_code == 401


def test_wrong_audience_or_issuer_is_401(client):
    bad_aud = {"Authorization": f"Bearer {token(aud='somewhere-else')}"}
    bad_iss = {"Authorization": f"Bearer {token(iss='other-issuer')}"}
    assert client.get("/health/cluster", headers=bad_aud).status_code == 401
    assert client.get("/health/cluster", headers=bad_iss).status_code == 401


# --------------------------------------------------------------------------- liveness

def test_public_endpoints(client, monkeypatch):
    assert client.get("/").status_code == 200
    monkeypatch.setattr(admin, "dbcheck_query", lambda: None)
    assert client.get("/dbcheck").status_code == 200
    admin.dbcheck_query = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    assert client.get("/dbcheck").status_code == 503
